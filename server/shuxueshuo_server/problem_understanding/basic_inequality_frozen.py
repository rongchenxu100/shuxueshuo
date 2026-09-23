"""Freeze and replay real extraction evidence, independently of scalar lowering."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from .basic_inequality_problem_ir import (
    DEFERRED_CASES,
    REPRESENTATIVE_CASES,
)
from .basic_inequality_problem_ir import (
    BasicInequalityProblemIRError as EvidenceError,
)
from .identity import revision
from .notation_compile import NotationValidator
from .notation_contract import (
    FAMILY_CATALOG_PATH,
    ROOT,
    SYSTEM,
    TEMPLATE_FILES,
    USER_SUFFIX,
    expression_catalog,
    schema,
)
from .notation_family_catalog import notation_family_catalog
from .notation_semantics import canonical, compare
from .notation_service import parse_candidate

FILES = (
    "request.json",
    "raw-response.txt",
    "parsed.json",
    "normalized.json",
    "canonical.json",
    "diff.json",
    "summary.json",
    "call.json",
    "frozen.json",
)
BASELINE_KEYS = (
    "template_files",
    "system_prompt_hash",
    "authoring_schema_hash",
    "registry_snapshot",
    "notation_family_catalog_hash",
    "expression_catalog_hash",
    "output_contract",
)


def digest(content):
    return sha256(content).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def baseline(frozen, request):
    user = request["messages"][1]["content"]
    prefix = json.loads(user[0]["text"])
    return {
        **{key: frozen[key] for key in BASELINE_KEYS},
        "wire_catalog_sha256": revision(prefix["math_expression_catalog"]),
        "user_suffix_sha256": digest(user[-1]["text"].encode()),
    }


def response_id(call):
    attempts = [a for a in call["provider_attempts"] if a.get("status") == "completed"]
    require(len(attempts) == 1, "expected one completed provider response")
    attempt = attempts[0]
    require(attempt.get("finish_reason") == "stop", "incomplete provider response")
    identity = attempt.get("raw_payload", {}).get("id")
    require(
        isinstance(identity, str) and bool(identity), "missing provider response ID"
    )
    return identity


def _no_uncertainty(scope):
    return not scope.get("uncertainties") and all(
        _no_uncertainty(child) for child in scope.get("children", [])
    )


def _verify_sample(files, *, gold, gold_hash, image_hash, case, selected_baseline):
    """Check hashes, call identity, wire request and replay every semantic gate."""
    data = {
        name: json.loads(content)
        for name, content in files.items()
        if name.endswith(".json")
    }
    frozen, request, call = (
        data[name] for name in ("frozen.json", "request.json", "call.json")
    )
    require(
        baseline(frozen, request) == selected_baseline, "extraction baseline mismatch"
    )
    require(frozen["case_id"] == case, "sample case mismatch")
    require(frozen["gold_sha256"] == gold_hash, "stale gold hash")
    require(frozen["image_sha256"] == image_hash, "sample image mismatch")
    require(frozen["request_hash"] == revision(request), "request hash mismatch")
    require(frozen["semantic_budget"] == 1, "invalid semantic call budget")
    require(
        call.get("provider") == "deepseek" and call.get("finish_reason") == "stop",
        "invalid live call",
    )
    identity = response_id(call)
    raw = files["raw-response.txt"].decode("utf-8")
    completed = next(
        a for a in call["provider_attempts"] if a.get("status") == "completed"
    )
    require(
        completed.get("visible_content") is True, "provider returned no visible content"
    )
    response = completed["raw_payload"]
    require(
        response["choices"][0]["message"]["content"] == raw,
        "provider payload/raw mismatch",
    )
    require(call["request_model"] == request["model"], "request model mismatch")
    messages = request["messages"]
    require(
        digest(messages[0]["content"].encode()) == frozen["system_prompt_hash"],
        "system prompt mismatch",
    )
    user = messages[1]["content"]
    prefix = json.loads(user[0]["text"])
    require(
        revision(prefix["response_schema"]) == frozen["authoring_schema_hash"],
        "schema mismatch",
    )
    require(
        request["contract_schema"] == prefix["response_schema"], "wire schema mismatch"
    )
    require(
        revision(prefix["registered_families"]) == frozen["registry_snapshot"],
        "registry mismatch",
    )
    require(
        any(item.get("image", {}).get("sha256") == image_hash for item in user),
        "request image mismatch",
    )
    parsed = data["parsed.json"]
    replay = parse_candidate(
        raw,
        problem_id=case,
        source_sha256=image_hash,
        registry_snapshot=frozen["registry_snapshot"],
        registered_families=[f["family_id"] for f in prefix["registered_families"]],
    )
    for field in (
        "binding",
        "objects",
        "contract_valid",
        "revision",
        "semantic_revision",
        "continuation",
    ):
        require(
            parsed.get(field) == replay.get(field), f"parsed replay mismatch: {field}"
        )
    require(
        replay["contract_valid"] and not replay["continuation"]["blocked"],
        "invalid or blocked candidate",
    )
    actual = {**replay["objects"]["ir"], **replay["objects"]["match"]}
    require(
        actual["family_id"] == gold["family_id"] == "basic_inequality",
        "family mismatch",
    )
    require(
        actual["match_status"] == gold["match_status"] == "matched",
        "unmatched candidate",
    )
    require(_no_uncertainty(actual["root"]), "unresolved extraction uncertainty")
    report = NotationValidator().validate(json.loads(raw))
    require(report.ok, "notation validation failed")
    require(data["normalized.json"] == report.normalized, "normalized replay mismatch")
    require(data["canonical.json"] == canonical(report), "canonical replay mismatch")
    comparison = compare(gold, actual)
    require(comparison["ok"], "strict semantics failed")
    stored_comparison = {
        k: v
        for k, v in data["diff.json"].items()
        if k not in {"unmatched", "match_correct"}
    }
    require(stored_comparison == comparison, "comparison replay mismatch")
    require(
        data["diff.json"].get("match_correct") is True,
        "stored family comparison failed",
    )
    require(data["diff.json"].get("unmatched") is False, "stored unmatched candidate")
    summary = data["summary.json"]
    require(
        all(
            summary.get(k) is True
            for k in (
                "passed",
                "contract_valid",
                "strict_semantics_passed",
                "match_correct",
            )
        ),
        "stored gate failed",
    )
    require(
        summary["case_id"] == case and summary["semantic_calls"] == 1,
        "invalid call summary",
    )
    return actual, identity


def load_verified_case(gold_path):
    gold_path = Path(gold_path)
    case, root = gold_path.stem, gold_path.parent
    require(case in REPRESENTATIVE_CASES, "case outside representative-10")
    manifest = read_json(root / "manifest.json")
    require(
        tuple(manifest["cases"]) == REPRESENTATIVE_CASES,
        "representative scope mismatch",
    )
    require(
        manifest["scope"] == "representative-10" and manifest["samples_per_case"] == 2,
        "invalid sample scope",
    )
    require(manifest["deferred_cases"] == DEFERRED_CASES, "deferred scope mismatch")
    gold_bytes = gold_path.read_bytes()
    gold_hash = digest(gold_bytes)
    require(gold_hash == manifest["gold_sha256"][case], "gold file hash mismatch")
    image_entry = manifest["images"][case]
    image_hash = digest((root / image_entry["file"]).read_bytes())
    require(image_hash == image_entry["sha256"], "image file hash mismatch")
    gold = json.loads(gold_bytes)
    index = read_json(root / "samples" / "index.json")
    require(index["cases"] == list(REPRESENTATIVE_CASES), "sample index scope mismatch")
    require(
        set(index["samples"]) == set(REPRESENTATIVE_CASES),
        "sample index contains nonrepresentative cases",
    )
    records = index["samples"][case]
    require(len(records) == 2, "exactly two frozen samples required")
    require(len({r["sample_id"] for r in records}) == 2, "duplicate sample ID")
    actuals, identities, samples = [], [], []
    for row in records:
        require(set(row["files"]) == set(FILES), "incomplete sample file index")
        directory = root / "samples" / case / row["sample_id"]
        require(
            directory.resolve().parent == (root / "samples" / case).resolve(),
            "invalid sample path",
        )
        contents = {}
        for name in FILES:
            content = (directory / name).read_bytes()
            require(
                digest(content) == row["files"][name],
                f"sample file hash mismatch: {name}",
            )
            contents[name] = content
        actual, identity = _verify_sample(
            contents,
            gold=gold,
            gold_hash=gold_hash,
            image_hash=image_hash,
            case=case,
            selected_baseline=index["baseline"],
        )
        require(identity == row["response_id"], "provider response ID mismatch")
        identities.append(identity)
        actuals.append(actual)
        samples.append(
            {
                **row,
                "path": f"samples/{case}/{row['sample_id']}",
                "raw_sha256": row["files"]["raw-response.txt"],
            }
        )
    require(len(set(identities)) == 2, "same provider call reused")
    require(len({row["source_run"] for row in records}) == 2, "same source run reused")
    require(compare(actuals[0], actuals[1])["ok"], "two samples disagree")
    return {
        "gold": gold,
        "provenance": {
            "asset_root": "math-notation-v1/basic-inequality",
            "gold_path": gold_path.name,
            "gold_sha256": gold_hash,
            "gold_semantic_sha256": revision(
                canonical(NotationValidator().validate(gold))
            ),
            "image_path": image_entry["file"],
            "image_sha256": image_hash,
            "gold_review": manifest["gold_review"],
            "samples": samples,
            "baseline": index["baseline"],
            "sample_index_sha256": digest((root / "samples/index.json").read_bytes()),
        },
    }


def freeze_runs(root, selections):
    """Freeze selected real runs. Validate everything before writing any assets.

    selections maps the ten case IDs to two run directories. Original files are
    copied byte-for-byte, including historical metadata; locators in parsed.json
    remain audit text and are never followed by the offline loader.
    """
    root = Path(root)
    require(
        set(selections) == set(REPRESENTATIVE_CASES),
        "freeze requires exactly representative-10",
    )
    manifest = read_json(root / "manifest.json")
    require(
        tuple(manifest["cases"]) == REPRESENTATIVE_CASES
        and manifest["scope"] == "representative-10"
        and manifest["samples_per_case"] == 2,
        "invalid freeze scope",
    )
    selected_baseline = None
    staged = []
    index = {
        "schema_version": "basic-inequality-frozen-samples/v1",
        "cases": list(REPRESENTATIVE_CASES),
        "samples": {},
    }
    for case in REPRESENTATIVE_CASES:
        require(len(selections[case]) == 2, "exactly two selected runs required")
        index["samples"][case] = []
        actuals, ids = [], []
        for number, run in enumerate(selections[case], 1):
            run = Path(run).resolve()
            files = {
                name: (run / name).read_bytes()
                for name in FILES
                if name not in {"normalized.json", "canonical.json"}
            }
            parsed = json.loads(files["parsed.json"])
            for key in ("normalized", "canonical"):
                info = parsed["artifacts"][key]
                # Content addressing locates artifacts even after a run moves.
                content = (
                    run / "artifacts" / info["sha256"][:2] / (info["sha256"] + ".json")
                ).read_bytes()
                require(
                    digest(content) == info["sha256"], "original artifact hash mismatch"
                )
                files[key + ".json"] = content
            frozen = json.loads(files["frozen.json"])
            if selected_baseline is None:
                request = json.loads(files["request.json"])
                selected_baseline = baseline(frozen, request)
                for path in TEMPLATE_FILES:
                    require(
                        frozen["template_files"][str(path.relative_to(ROOT))]
                        == digest(path.read_bytes()),
                        "selected baseline is not current",
                    )
                require(
                    frozen["notation_family_catalog_hash"]
                    == digest(FAMILY_CATALOG_PATH.read_bytes()),
                    "stale family catalog",
                )
                prefix = json.loads(request["messages"][1]["content"][0]["text"])
                require(
                    request["messages"][0]["content"] == SYSTEM, "stale system request"
                )
                require(
                    request["messages"][1]["content"][-1]["text"] == USER_SUFFIX,
                    "stale user request",
                )
                require(prefix["response_schema"] == schema(), "stale wire schema")
                require(
                    prefix["math_expression_catalog"] == expression_catalog(),
                    "stale wire catalog",
                )
                require(
                    prefix["registered_families"] == list(notation_family_catalog()),
                    "stale wire family catalog",
                )
                index["baseline"] = selected_baseline
            gold_hash = digest((root / f"{case}.json").read_bytes())
            image = manifest["images"][case]
            require(
                gold_hash == manifest["gold_sha256"][case],
                "current gold manifest mismatch",
            )
            require(
                digest((root / image["file"]).read_bytes()) == image["sha256"],
                "current image manifest mismatch",
            )
            actual, identity = _verify_sample(
                files,
                gold=read_json(root / f"{case}.json"),
                gold_hash=gold_hash,
                image_hash=image["sha256"],
                case=case,
                selected_baseline=selected_baseline,
            )
            actuals.append(actual)
            ids.append(identity)
            sid = f"sample-{number:02d}"
            row = {
                "sample_id": sid,
                "response_id": identity,
                "source_run": str(run.relative_to(ROOT))
                if run.is_relative_to(ROOT)
                else str(run),
                "files": {name: digest(content) for name, content in files.items()},
            }
            index["samples"][case].append(row)
            staged.append((root / "samples" / case / sid, files))
        require(len(set(ids)) == 2, "same provider call reused")
        require(compare(*actuals)["ok"], "two selected samples disagree")
    require(
        not (root / "samples/index.json").exists(), "frozen sample index already exists"
    )
    for directory, _ in staged:
        require(not directory.exists(), "sample destination already exists")
    for directory, files in staged:
        directory.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            (directory / name).write_bytes(content)
    write_json(root / "samples/index.json", index)
