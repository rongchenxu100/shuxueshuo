"""Persist each stage-two decision and keep unsupported goals separate from failures."""

import json
import shutil
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save

from ..stage_one import runner as stage_one
from .contracts import RESULT_CONTRACT, ROOT, targets, validate_input, validate_result

RUNS = ROOT / "internal/solver-runs/graph-guided-stage-two"


def fingerprint():
    paths = [
        *Path(__file__).parent.glob("*.py"),
        *(ROOT / "site/data/knowledge-next/recognition").glob("*.json"),
        *(ROOT / "site/data/knowledge-next/nodes").glob("*.json"),
        *(ROOT / "internal/schemas").glob("graph-stage-two-*.json"),
        *(ROOT / "internal/llm-prompts").glob("graph-stage-two-*.md"),
    ]
    return {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def _counts(goals):
    return {
        key: sum((goal.get("llm") or {}).get(key, 0) for goal in goals)
        for key in ("semantic_calls", "network_attempts", "new_semantic_calls", "new_network_attempts")
    }


def _decision_snapshot(goals):
    return [{key: goal[key] for key in ("target_ref", "status", "primary", "primary_source", "supported")
             if key in goal} for goal in goals]


def compare_replay_decisions(historical, current):
    """Compare decisions with the original run, including selection-path drift."""
    differences = []
    if historical["status"] != current["status"]:
        differences.append({"target_ref": None, "field": "status", "expected": historical["status"],
                            "actual": current["status"]})
    expected = {goal["target_ref"]: goal for goal in historical["goals"]}
    actual = {goal["target_ref"]: goal for goal in current["goals"]}
    for ref in dict.fromkeys([*expected, *actual]):
        if ref not in expected or ref not in actual:
            differences.append({"target_ref": ref, "field": "goal_presence", "expected": ref in expected,
                                "actual": ref in actual})
            continue
        for key in ("status", "primary", "primary_source", "supported"):
            # Older replay artifacts did not retain the supported set. Their
            # recorded status, primary and source still provide a valid baseline.
            if key not in expected[ref]:
                continue
            before, after = expected[ref][key], actual[ref][key]
            same = set(before) == set(after) if key == "supported" else before == after
            if not same:
                differences.append({"target_ref": ref, "field": key, "expected": before, "actual": after})
    return {"ok": not differences, "baseline": "original_recorded_decisions", "differences": differences}


def run_result(value, output, *, provider=None, verify=False, input_reference=None,
               source_image=None, unsupported_root=None, contracts=None, admission="acceptance"):
    """Run a validated stage-one result; an existing output is never overwritten.

    Providers may be lazy factories. Only multiple supported types invoke one.
    ``contracts`` permits independent catalog fixtures without case-ID branches.
    """
    from .fragments import build_d1
    from .recognition import build_d2, derive_knowledge, evaluate_types
    from .selection import select_primary
    from .verification import verify_amgm

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    stamp = datetime.now(UTC).isoformat()
    input_hash = revision(value)
    run_id = output.name
    validation = validate_input(value, admission)
    result = {
        "contract": RESULT_CONTRACT,
        "run_id": run_id,
        "created_at": stamp,
        "stage_one": {"reference": str(input_reference or "input.json"), "sha256": input_hash,
                      "run_id": value.get("run_id") if isinstance(value, dict) else None},
        "input_validation": validation,
        "input_diagnostics": validation["diagnostics"],
        "status": "input_error" if not validation["ok"] else "completed",
        "goals": [],
        "llm": _counts([]),
        "options": {"verify_amgm": verify, "admission": admission},
    }
    save(output / "input.json", value)
    save(output / "frozen.json", {"input_sha256": input_hash, "implementation": fingerprint(),
                                   "created_at": stamp, "recognition_contracts": contracts})
    if source_image is not None and Path(source_image).is_file():
        shutil.copyfile(source_image, output / "source.png")
    if validation["ok"]:
        candidate = value["candidate"]
        for number, target in enumerate(targets(candidate), 1):
            ref = target["target_ref"]
            features = [row for row in value["features"] if row["target_ref"] == ref]
            verification = verify_amgm(candidate, ref, features, enabled=verify)
            reports = evaluate_types(features, verification=verification, contracts=contracts)
            supported = [row["type_id"] for row in reports if row["status"] == "supported"]
            goal = {**target, "status": "unsupported", "diagnostics": [],
                    "knowledge": derive_knowledge(features), "types": reports,
                    "primary": None, "primary_source": "unsupported", "supported": supported,
                    "d1": None, "d2": None, "verification": verification, "llm": None}
            if len(supported) == 1:
                goal.update(status="resolved", primary=supported[0], primary_source="program")
            elif len(supported) > 1:
                selection = select_primary(candidate, ref, reports, output / "calls" / f"goal-{number:03}", provider=provider)
                goal.update(llm=selection["llm"], diagnostics=selection["diagnostics"],
                            status="resolved" if selection["ok"] else "selection_failed",
                            primary=selection["primary"] if selection["ok"] else None,
                            primary_source="llm" if selection["ok"] else None)
            else:
                # Reserve the whole run's destination once; a colliding historical
                # run must not silently overwrite its pending review records.
                if "unsupported_directory" not in result:
                    parent = Path(unsupported_root) if unsupported_root is not None else RUNS / "unsupported"
                    destination = parent / (run_id + "-" + revision(str(output.resolve()))[:12])
                    destination.mkdir(parents=True, exist_ok=False)
                    result["unsupported_directory"] = str(destination.resolve())
                pending = {
                    "contract": "graph-stage-two-unsupported/v1", "run_id": run_id,
                    "created_at": stamp, "target_ref": ref, "label": target["label"],
                    "candidate": candidate, "features": features, "types": reports,
                    "knowledge": goal["knowledge"], "stage_one": result["stage_one"],
                }
                filename = f"goal-{number:03}.json"
                save(Path(result["unsupported_directory"]) / filename, pending)
                save(output / "unsupported" / filename, pending)
                goal["unsupported_record"] = f"unsupported/{filename}"
                goal["debug_d1"] = build_d1(candidate, ref, features, goal["knowledge"])
            if goal["status"] == "resolved":
                goal["knowledge"] = derive_knowledge(features, primary=goal["primary"])
                goal["d1"] = build_d1(candidate, ref, features, goal["knowledge"])
                goal["d2"] = build_d2(reports, goal["primary"])
            result["goals"].append(goal)
            save(output / "goals" / f"goal-{number:03}.json", goal)
        failed = sum(goal["status"] == "selection_failed" for goal in result["goals"])
        result["status"] = "failed" if failed == len(result["goals"]) else "partial" if failed else "completed"
    result["llm"] = _counts(result["goals"])
    result["elapsed_seconds"] = round(perf_counter() - started, 6)
    validate_result(result)
    save(output / "stage-two-result.json", result)
    from .report import render_result

    render_result(output)
    return result


def run_sample(source, output, **options):
    """Read strict JSON; malformed input still produces an input_error report."""
    source = Path(source)
    raw = None
    try:
        raw = source.read_text(encoding="utf-8")
        value = strict_json(raw)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        result = run_result(None, output, input_reference=source, **options)
        result["input_diagnostics"].append({"code": "input.read", "path": str(source),
                                            "message": type(exc).__name__})
        if raw is not None:
            (Path(output) / "input-raw.txt").write_text(raw, encoding="utf-8")
        save(Path(output) / "stage-two-result.json", result)
        from .report import render_result

        render_result(output)
        return result
    return run_result(value, output, input_reference=source, **options)


def run_recorded_batch(batch, output, *, cases=None, provider=None, verify=False):
    """Reverify stage-one evidence before classification. This never redoes OCR."""
    batch, output = Path(batch), Path(output)
    selected = tuple(cases) if cases is not None else stage_one.CASES
    output.mkdir(parents=True, exist_ok=False)
    stage_one.replay_batch(batch, output / "stage-one", cases=selected)
    summary = json.loads((output / "stage-one/batch-summary.json").read_text())
    results = []
    for row in summary["results"]:
        rel = row["sample_dir"]
        source = output / "stage-one" / rel
        target = output / rel
        result = run_sample(source / "stage-one-result.json", target, provider=provider, verify=verify,
                            source_image=source / "source.png", unsupported_root=output / "unsupported")
        results.append({"case_id": row["case_id"], "sample_id": row["sample_id"], "sample_dir": rel,
                        "status": result["status"], "goals": len(result["goals"]),
                        "resolved": sum(g["status"] == "resolved" for g in result["goals"]),
                        "unsupported": sum(g["status"] == "unsupported" for g in result["goals"]),
                        "llm": result["llm"]})
    result = {"contract": "graph-stage-two-batch/v1", "run_id": output.name,
              "stage_one_recording": str(batch.resolve()), "results": results,
              "completed": bool(results) and all(row["status"] == "completed" for row in results),
              "llm": {key: sum(row["llm"][key] for row in results) for key in _counts([])}}
    save(output / "batch-summary.json", result)
    from .report import render_batch

    render_batch(output)
    return result


def record_run(source, destination):
    """Keep portable inputs and every attempted selection; never overwrite a recording."""
    source, destination = Path(source), Path(destination)
    result = json.loads((source / "stage-two-result.json").read_text())
    validate_result(result)
    destination.mkdir(parents=True, exist_ok=False)
    names = ("input.json", "frozen.json", "stage-two-result.json")
    for name in names:
        shutil.copyfile(source / name, destination / name)
    for name in ("source.png", "input-raw.txt"):
        if (source / name).is_file():
            shutil.copyfile(source / name, destination / name)
    for name in ("calls", "goals", "unsupported"):
        if (source / name).is_dir():
            shutil.copytree(source / name, destination / name)
    hashes = {str(path.relative_to(destination)): sha256(path.read_bytes()).hexdigest()
              for path in sorted(destination.rglob("*")) if path.is_file()}
    save(destination / "recording.json", {"contract": "graph-stage-two-recording/v1", "files": hashes})
    return destination


def replay_run(recording, output, *, refresh_features=False):
    """Recompute from a frozen input and exact recorded selections, never a provider."""
    from .selection import RecordedSelectionProvider

    recording = Path(recording).resolve()
    manifest = strict_json((recording / "recording.json").read_text())
    if manifest.get("contract") != "graph-stage-two-recording/v1":
        raise ValueError("recording.invalid_contract")
    required = {"input.json", "frozen.json", "stage-two-result.json"}
    files = manifest.get("files", {})
    if not isinstance(files, dict) or not required <= files.keys():
        raise ValueError("recording.missing_files")
    for name, digest in files.items():
        path = (recording / name).resolve()
        if not path.is_relative_to(recording) or not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("recording.hash_mismatch")
    original = strict_json((recording / "stage-two-result.json").read_text())
    validate_result(original)
    frozen = strict_json((recording / "frozen.json").read_text())
    value = strict_json((recording / "input.json").read_text())
    if revision(value) != frozen.get("input_sha256"):
        raise ValueError("recording.input_mismatch")
    if refresh_features:
        # Teaching upgrades reuse reviewed notation, not obsolete derived feature
        # rows. The input hash above authenticates the old record first; run_result
        # binds the new deterministic features to a new immutable attempt.
        from ..stage_one.runner import candidate_features
        features = candidate_features(value['candidate'])
        if not features['ok']:
            raise ValueError('recording.feature_refresh_failed')
        value['features'] = features['features']
        value['statuses']['features'] = True
    result = run_result(value, output, provider=RecordedSelectionProvider.from_run(recording),
                        verify=original["options"]["verify_amgm"], input_reference=recording / "input.json",
                        contracts=frozen.get("recognition_contracts"),
                        admission=original["options"].get("admission", "acceptance"),
                        source_image=recording / "source.png",
                        unsupported_root=Path(output) / "unsupported")
    if (recording / "input-raw.txt").is_file():
        shutil.copyfile(recording / "input-raw.txt", Path(output) / "input-raw.txt")
    # Re-recording a replay must preserve the original provider run's counts
    # and failures instead of replacing that history with zero replay calls.
    result["historical"] = original.get("historical") or {
        "status": original["status"], "llm": original["llm"],
        "input_diagnostics": original["input_diagnostics"],
        "goals": _decision_snapshot(original["goals"]),
    }
    result["previous_run"] = {"run_id": original["run_id"], "status": original["status"],
                              "llm": original["llm"], "recording": str(recording)}
    result["mode"] = "offline_replay"
    result["replay_comparison"] = compare_replay_decisions(result["historical"], result)
    validate_result(result)
    save(Path(output) / "stage-two-result.json", result)
    from .report import render_result

    render_result(output)
    return result
