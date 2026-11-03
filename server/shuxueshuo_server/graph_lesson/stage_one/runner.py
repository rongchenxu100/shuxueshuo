"""Image-only live runs and portable, hash-checked offline replay."""

import fcntl
import json
import shutil
import traceback
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import cached_property
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter, time

from jsonschema import Draft202012Validator, ValidationError
from PIL import Image

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow import run_workflow
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.problem_understanding.workflow_usage import stages
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
    MultimodalImageInput,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalExtractionPrompt,
    MultimodalProviderImage,
    MultimodalProviderRequest,
)

from . import contracts
from .evaluation import evaluate, read_json, validate_fixture
from .extraction import (
    REPO,
    GraphStageOneContract,
    StageOneStorage,
    frozen_files,
    validate_candidate,
)
from .features import extract_features, registry
from .report import STATE_FILE, batch_rows, sample_number, sample_state

CORPUS = REPO / "server/tests/solver/fixtures/graph-guided-stage-one/quadratic-always"


class _CorpusCases(Sequence):
    """Load acceptance-only fixtures when a batch command actually needs them."""

    @cached_property
    def values(self):
        return tuple(case["case_id"] for case in read_json(CORPUS / "manifest.json")["cases"])

    def __len__(self):
        return len(self.values)

    def __getitem__(self, index):
        return self.values[index]


CASES = _CorpusCases()


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def build_request(fixture, store):
    """Only pixels and shared contracts enter the provider request."""
    return build_image_request((Path(fixture) / "source.png").read_bytes(), store)


def build_image_request(content, store, *, original_content=None):
    """Question image, optionally with an unprocessed view of the very same crop.

    The caller validates the crop correspondence. The supplemental image uses
    the existing detail/zoom transport, on the same page, rather than pretending
    this is a second question or a multi-page upload.
    """
    source_hash = sha256(content).hexdigest()
    with Image.open(BytesIO(content)) as image:
        if image.format != "PNG":
            raise ValueError("stage one expects a PNG question image")
        width, height = image.size
    artifact = store.put_bytes(kind="graph_stage_one_source", content=content, media_type="image/png", suffix=".png")
    pack = MultimodalEvidencePack(
        schema_version="multimodal-evidence-pack/v1", evidence_pack_id="graph-stage-one",
        base_context_id="graph-stage-one", source_id=source_hash, source_revision_hash=source_hash,
        selection_id="whole-image", observation_hash=source_hash,
        images=(MultimodalImageInput("primary", "page-1", "primary", artifact, width, height),),
        printed_text=(), recognized_formulas=(), unresolved_items=(), region_index=(),
    )
    images = [MultimodalProviderImage("primary", "page-1", "primary", artifact, content, width, height)]
    if original_content is not None:
        with Image.open(BytesIO(original_content)) as original:
            if original.format != "PNG":
                raise ValueError("stage one expects a PNG original image")
            original_size = original.size
        original_artifact = store.put_bytes(kind="graph_stage_one_original", content=original_content,
                                             media_type="image/png", suffix=".png")
        images.append(MultimodalProviderImage("original", "page-1", "zoom", original_artifact,
                                              original_content, *original_size))
    return MultimodalProviderRequest(
        evidence_pack=pack,
        prompt=MultimodalExtractionPrompt(
            contracts.SYSTEM,
            json.dumps({"response_schema": contracts.schema(), "math_expression_catalog": contracts.expression_catalog()}, ensure_ascii=False),
            "读取完整题图，转录原题文字，按 Schema 提取数学题意。只返回 JSON。",
        ),
        images=tuple(images),
        contract_version=contracts.CONTRACT, contract_schema=contracts.schema(),
        response_format={"type": "json_object"},
    )


def mark(output, phase):
    """Atomically record how far a sample got; recovery reads only this."""
    save(Path(output) / STATE_FILE, {"schema_version": "graph-stage-one-sample-state/v1", "phase": phase})


def candidate_features(candidate):
    if not candidate:
        return {"ok": False, "features": [], "diagnostics": [{"code": "feature.no_candidate"}]}
    return extract_features(candidate)


def finish_sample(output, fixture, workflow, *, run_id, case_id, sample_id, elapsed, historical=None):
    postprocess_started = perf_counter()
    candidate = workflow.get("candidate")
    validation = validate_candidate(candidate) if candidate else {"contract_valid": False, "reports": {}}
    features = candidate_features(candidate)
    evaluation = evaluate(fixture, candidate, features, source_reviewed=workflow.get("source_reviewed", False))
    frozen = read_json(output / "frozen.json")
    unchanged = historical is not None or frozen["implementation"] == frozen_files()
    passed = evaluation["ok"] and workflow.get("status") == "reviewed_candidate" and unchanged
    statuses = {"extraction": workflow.get("status"), "source_reviewed": workflow.get("source_reviewed", False),
                "features": features["ok"], "evaluation": evaluation["ok"],
                "human_review": "pending", "passed": passed}
    result = {"contract": contracts.RESULT_CONTRACT, "run_id": run_id, "case_id": case_id,
              "sample_id": sample_id, "candidate": candidate,
              "features": features["features"], "statuses": statuses}
    Draft202012Validator(contracts.result_schema()).validate(result)
    summary = {"case_id": case_id, "sample_id": sample_id, "passed": passed,
               "status": workflow.get("status"), "source_kind": "synthetic-rendered",
               "source_reviewed": workflow.get("source_reviewed", False), "human_review": "pending",
               "elapsed_seconds": round(elapsed, 3), "historical_live": historical,
               "implementation_unchanged": unchanged, "frozen_implementation": revision(frozen["implementation"]),
               **{key: workflow.get(key, 0) for key in ("semantic_calls", "content_calls", "review_calls", "network_attempts", "file_api_calls")}}
    if (output / "workflow/ledger.json").exists():
        summary["stages"] = stages(output / "workflow")
        calls = read_json(output / "workflow/ledger.json")["calls"]
        summary["repair_calls"] = sum(call["stage"] == "repair" for call in calls)
    first = workflow.get("first_candidate")
    first_features = candidate_features(first)
    first_evaluation = evaluate(fixture, first, first_features, source_reviewed=False, require_source_review=False)
    first_evaluation["measurement"] = "Independent gold evaluation before repair; not an image-review claim."
    summary["first_passed"] = bool(first_evaluation["ok"] and workflow.get("first_finish_reason") == "stop")
    summary["postprocess_seconds"] = round(perf_counter() - postprocess_started, 3)
    summary["elapsed_seconds"] = round(elapsed + summary["postprocess_seconds"], 3)
    summary["timing_notes"] = "Wall time includes transport and provider work; provider queue and model execution time are unavailable separately."
    for name, data in {"candidate.json": candidate, "features.json": features,
                       "feature-trace.json": {"features": features["features"], "diagnostics": features.get("diagnostics", [])},
                       "feature-registry.json": registry(), "validation.json": validation, "evaluation.json": evaluation,
                       "first-evaluation.json": first_evaluation,
                       "stage-one-result.json": result, "summary.json": summary}.items():
        save(output / name, data)
    mark(output, "summarized")
    return summary


def run_sample(case_id, output, provider, *, sample_id=1, run_id=None, corpus=CORPUS):
    """Reserve a new directory; recorded calls can never count as a fresh live sample."""
    if case_id not in CASES:
        raise ValueError("unknown case")
    fixture = Path(corpus) / case_id
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    mark(output, "reserved")
    preflight = validate_fixture(fixture)
    save(output / "preflight.json", preflight)
    if not preflight["ok"]:
        raise ValueError("fixture preflight failed; see preflight.json")
    shutil.copytree(fixture, output / "fixture")
    shutil.copyfile(fixture / "source.png", output / "source.png")
    run_id = run_id or output.parent.name
    frozen = {"schema_version": "graph-stage-one-frozen/v1", "run_id": run_id, "case_id": case_id,
              "sample_id": sample_id, "source_kind": "synthetic-rendered", "implementation": frozen_files(),
              "fixture_hashes": {p.name: digest(p) for p in sorted(fixture.iterdir()) if p.is_file()},
              "source_reference": str((fixture / "source.png").resolve())}
    if (fixture / "source.png").resolve().is_relative_to(REPO):
        frozen["source_reference"] = str((fixture / "source.png").resolve().relative_to(REPO))
    save(output / "frozen.json", frozen)
    mark(output, "frozen")
    started = perf_counter()
    request = build_request(output / "fixture", ExtractionArtifactStore(output / "inputs"))
    storage = StageOneStorage(output / "workflow")
    workflow = run_workflow(request, provider, storage.directory, [], problem_id=case_id,
                            storage=storage, contract_adapter=GraphStageOneContract())
    mark(output, "workflow_finished")
    return finish_sample(output, output / "fixture", workflow, run_id=run_id, case_id=case_id,
                         sample_id=sample_id, elapsed=perf_counter() - started)


def run_batch(output, provider_factory, *, cases=CASES, samples=2, workers=3):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    cases = tuple(cases)
    if not cases or len(set(cases)) != len(cases) or not set(cases) <= set(CASES):
        raise ValueError("nonempty unique known cases required")
    if samples < 1 or not 1 <= workers <= 3:
        raise ValueError("samples must be positive; workers must be 1..3")
    results = []
    started = perf_counter()
    save(output / "batch-manifest.json", {"requested_cases": list(cases), "samples_per_case": samples,
                                         "expected_samples": len(cases) * samples, "implementation": frozen_files()})
    save(output / "batch-summary.json", batch_summary(output, results, started, cases=cases, samples=samples))

    def execute(case, sample):
        return run_sample(case, output / case / f"sample-{sample:02d}", provider_factory(),
                          sample_id=sample, run_id=output.name)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(execute, case, sample): (case, sample)
                   for case in cases for sample in range(1, samples + 1)}
        for future in as_completed(pending):
            case, sample = pending[future]
            directory = output / case / f"sample-{sample:02d}"
            try:
                summary = future.result()
            except Exception as exc:  # noqa: BLE001 - keep other cases running; failed case cannot pass
                summary = {"case_id": case, "sample_id": sample, "passed": False,
                           "status": "runner.failed", "error_type": type(exc).__name__}
                save(directory / "failure.json", {**summary,
                     "frames": [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                                for frame in traceback.extract_tb(exc.__traceback__)]})
                save(directory / "summary.json", summary)
                mark(directory, "failed")
            results.append({**summary, "sample_dir": str(directory.relative_to(output))})
            save(output / "batch-summary.json", batch_summary(output, results, started, cases=cases, samples=samples))
    return batch_summary(output, results, started, cases=cases, samples=samples)


def batch_summary(output, results, started, *, cases=CASES, samples=2):
    expected = {(case, sample) for case in cases for sample in range(1, samples + 1)}
    actual = {(row["case_id"], row["sample_id"]) for row in results}
    complete = actual == expected and len(results) == len(expected)
    same_version = len({row.get("frozen_implementation") for row in results}) <= 1
    passed = complete and all(row["passed"] for row in results) and same_version
    formal = set(cases) == set(CASES) and samples == 2
    return {"schema_version": "graph-stage-one-batch/v1", "run_id": output.name,
            "results": sorted(results, key=lambda row: (row["case_id"], row["sample_id"])),
            "passed": passed, "complete": complete, "expected_samples": len(expected),
            "requested_cases": list(cases), "samples_per_case": samples,
            "formal_complete": formal and complete,
            "formal_passed": formal and passed and all(row.get("semantic_calls", 0) >= 2 and row.get("source_reviewed") for row in results),
            "purpose": "formal_acceptance" if formal else "partial_debug",
            "single_frozen_version": same_version,
            "elapsed_seconds": round(perf_counter() - started, 3), "human_review": "pending"}


def case_batches_summary(output):
    """Aggregate pytest case directories without writing; partial sessions cannot appear complete."""
    output = Path(output)
    results = []
    for case in CASES:
        path = output / case / "batch-summary.json"
        if path.exists():
            for row in read_json(path)["results"]:
                results.append({**row, "sample_dir": str(Path(case) / row["sample_dir"])})
    manifest = read_json(output / "batch-manifest.json") if (output / "batch-manifest.json").exists() else {}
    result = batch_summary(output, results, perf_counter(), cases=manifest.get("requested_cases", CASES),
                           samples=manifest.get("samples_per_case", 2))
    session = read_json(output / "run-session.json") if (output / "run-session.json").exists() else None
    result["elapsed_seconds"] = round(time() - session["started_unix_seconds"], 3) if session else None
    result["invocation_id"] = session["invocation_id"] if session else None
    return result


def collect_case_batches(output):
    """Refresh the session summary; called after every case and again at teardown."""
    output = Path(output)
    with (output / "collection.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result = case_batches_summary(output)
        save(output / "batch-summary.json", result)
        return result


def load_batch_summary(batch):
    """The saved batch summary, or one rebuilt from what an interrupted run left on disk.

    A pytest session writes its summary after each case, but a crash can still
    leave none; per-case summaries and the frozen manifest are enough to rebuild
    it, and unfinished samples are then discovered from their directories.
    """
    batch = Path(batch)
    if (batch / "batch-summary.json").exists():
        return read_json(batch / "batch-summary.json")
    if (batch / "run-session.json").exists():
        return {**case_batches_summary(batch), "rebuilt_after_interruption": True}
    if (batch / "batch-manifest.json").exists():
        manifest = read_json(batch / "batch-manifest.json")
        result = batch_summary(batch, [], perf_counter(), cases=manifest["requested_cases"],
                               samples=manifest["samples_per_case"])
        return {**result, "elapsed_seconds": None, "rebuilt_after_interruption": True}
    raise FileNotFoundError(batch / "batch-summary.json")


def reserve_live_session(output, invocation_id, *, cases=CASES, samples=2):
    """All pytest workers share one new session; a later invocation cannot reuse it."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "collection.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = output / "run-session.json"
        if path.exists():
            if read_json(path)["invocation_id"] != invocation_id:
                raise ValueError("live_session.already_reserved_use_a_new_directory")
        else:
            if any((output / case).exists() for case in CASES):
                raise ValueError("live_session.existing_samples_use_a_new_directory")
            save(path, {"invocation_id": invocation_id, "started_unix_seconds": time()})
            save(output / "batch-manifest.json", {
                "requested_cases": list(cases), "samples_per_case": samples,
                "expected_samples": len(cases) * samples, "implementation": frozen_files()})
            save(output / "batch-summary.json", case_batches_summary(output))


def verify_recorded_sample(sample):
    """Integrity verification is independent of present-day implementation hashes."""
    sample = Path(sample)
    frozen = read_json(sample / "frozen.json")
    for filename, expected in frozen["fixture_hashes"].items():
        path = sample / "fixture" / filename
        if filename == "source.png" and not path.exists():
            path = REPO / frozen["source_reference"]
        if digest(path) != expected:
            raise ValueError("recording.fixture_hash_mismatch: " + filename)
    ledger = read_json(sample / "workflow/ledger.json")
    raw = []
    for call in ledger["calls"]:
        request = read_json(sample / "workflow" / call["directory"] / "request.json")
        if revision(request) != call["request_hash"]:
            raise ValueError("recording.request_hash_mismatch")
        if call["stage"] in {"review", "repair"}:
            payload = json.loads(request["messages"][1]["content"][0]["text"])
            base = payload["candidate"] if call["stage"] == "review" else payload["base_candidate"]
            if (revision(base) if base is not None else None) != call["base_revision"]:
                raise ValueError("recording.request_candidate_revision_mismatch")
            if call["stage"] == "review" and payload["code_validation"]["candidate_revision"] != call["base_revision"]:
                raise ValueError("recording.review_revision_mismatch")
        if call["status"] == "completed":
            response = read_json(sample / "workflow" / call["response_file"])
            if revision(response) != call["response_hash"]:
                raise ValueError("recording.response_hash_mismatch")
            raw.append({"stage": call["stage"], "base_revision": call["base_revision"], "response": response})
        if "failed_attempts_file" in call:
            data = read_json(sample / "workflow" / call["failed_attempts_file"])
            if revision(data) != call["failed_attempts_hash"]:
                raise ValueError("recording.failed_attempts_hash_mismatch")
    return frozen, raw


def verify_partial_sample(sample):
    if (sample / "workflow/ledger.json").exists() and (sample / "frozen.json").exists():
        verify_recorded_sample(sample)


def replay_sample(sample, output):
    """Re-evaluate retained responses without constructing or importing a provider."""
    sample, output = Path(sample), Path(output)
    phase = sample_state(sample)
    if phase != "summarized":
        # Failed or interrupted samples have no live verdict to re-evaluate.
        # Their retained calls still need the normal integrity checks.
        verify_partial_sample(sample)
        shutil.copytree(sample, output)
        historical = read_json(sample / "summary.json") if phase == "failed" and (sample / "summary.json").exists() else None
        summary = {"case_id": sample.parent.name, "sample_id": sample_number(sample),
                   "status": "failed" if phase == "failed" else f"incomplete:{phase}",
                   "incomplete": phase != "failed", **(historical or {}),
                   "mode": "offline_replay", "historical_live": historical,
                   "new_semantic_calls": 0, "new_network_attempts": 0, "passed": False}
        save(output / "summary.json", summary)
        mark(output, phase)
        return summary
    frozen, responses = verify_recorded_sample(sample)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(sample / "fixture", output / "fixture")
    if not (output / "fixture/source.png").exists():
        shutil.copyfile(REPO / frozen["source_reference"], output / "fixture/source.png")
    shutil.copyfile(output / "fixture/source.png", output / "source.png")
    shutil.copytree(sample / "workflow", output / "workflow")
    save(output / "frozen.json", frozen)
    save(output / "replay-frozen.json", {
        "schema_version": "graph-stage-one-replay/v1", "implementation": frozen_files(),
        "input_recording": {str(path.relative_to(sample)): digest(path) for path in sorted(sample.rglob("*.json"))},
        "historical_frozen_sha256": digest(sample / "frozen.json"),
    })
    raw_validation = [
        {"stage": row["stage"], "validation": validate_candidate(row["response"]["text"])}
        for row in responses if row["stage"] != "review"
    ]
    save(output / "replayed-responses.json", raw_validation)
    workflow = read_json(sample / "workflow/workflow-result.json")
    candidate = workflow.get("candidate")
    # The final adopted candidate must be backed by a retained extraction/repair response.
    if candidate is not None and not any(
        revision(candidate) == row["validation"].get("revision") for row in raw_validation
    ):
        raise ValueError("recording.candidate_not_backed_by_response")
    reviewed = False
    for row in responses:
        if row["stage"] == "review":
            try:
                review = GraphStageOneContract().validate_review(row["response"]["text"], candidate)
                reviewed = (review["status"] == "confirmed" and row["response"]["finish_reason"] == "stop"
                            and row["base_revision"] == revision(candidate))
            except (ValueError, KeyError, TypeError, ValidationError):
                reviewed = False
        else:
            reviewed = False
    workflow["source_reviewed"] = reviewed
    historical = read_json(sample / "summary.json")
    summary = finish_sample(output, output / "fixture", workflow, run_id=output.parent.name,
                            case_id=frozen["case_id"], sample_id=frozen["sample_id"], elapsed=0, historical=historical)
    summary.update(mode="offline_replay", new_semantic_calls=0, new_network_attempts=0,
                   implementation_changed=frozen["implementation"] != frozen_files())
    save(output / "summary.json", summary)
    return summary


def replay_batch(batch, output, *, cases=CASES):
    batch, output = Path(batch), Path(output)
    historical_batch = load_batch_summary(batch)
    manifest = read_json(batch / "batch-manifest.json") if (batch / "batch-manifest.json").exists() else {}
    selected = tuple(cases)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(CASES):
        raise ValueError("replay.invalid_case_selection")
    rows = batch_rows(batch, historical_batch)
    declared = historical_batch.get("requested_cases", manifest.get("requested_cases"))
    if declared is None:  # Legacy probe recordings predate explicit manifests.
        declared = [case for case in CASES if any(row["case_id"] == case for row in rows)]
    if not declared or len(set(declared)) != len(declared) or not set(declared) <= set(CASES):
        raise ValueError("replay.invalid_recorded_case_set")
    if set(selected) != set(CASES) and not set(selected) <= set(declared):
        raise ValueError("replay.case_not_in_recording")
    requested = tuple(case for case in CASES if case in selected and case in declared)
    samples = historical_batch.get("samples_per_case", manifest.get("samples_per_case"))
    if samples is None:
        samples = max((row["sample_id"] for row in historical_batch["results"]), default=0)
    if type(samples) is not int or samples < 1:
        raise ValueError("replay.invalid_recorded_sample_count")
    output.mkdir(parents=True, exist_ok=False)
    results, started = [], perf_counter()
    for row in rows:
        if row["case_id"] not in requested:
            continue
        summary = replay_sample(batch / row["sample_dir"], output / row["sample_dir"])
        results.append({**summary, "sample_dir": row["sample_dir"]})
    result = batch_summary(output, results, started, cases=requested, samples=samples)
    result.update(mode="offline_replay", new_semantic_calls=0, new_network_attempts=0,
                  formal_passed=False, historical_live={key: historical_batch.get(key) for key in ("passed", "complete", "formal_passed")})
    save(output / "batch-summary.json", result)
    return result


def record_batch(batch, destination):
    """Keep every sample, including failures, with frozen evidence for another checkout."""
    batch, destination = Path(batch), Path(destination)
    summary = load_batch_summary(batch)
    destination.mkdir(parents=True, exist_ok=False)
    rows = batch_rows(batch, summary)
    unrecorded = [row["sample_dir"] for row in rows[len(summary["results"]):]]
    if unrecorded:
        summary = {**summary, "unrecorded_samples": unrecorded}
    for row in rows:
        source, target = batch / row["sample_dir"], destination / row["sample_dir"]
        if sample_state(source) != "summarized":
            # Failed and interrupted samples keep their partial calls as-is.
            verify_partial_sample(source)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(
                "*.png", "inputs", "artifacts", "workflow.lock"))
            continue
        verify_recorded_sample(source)
        target.mkdir(parents=True)
        shutil.copytree(source / "fixture", target / "fixture", ignore=shutil.ignore_patterns("*.png"))
        # Ledger calls include redacted requests, complete raw responses and failed reservations.
        shutil.copytree(source / "workflow", target / "workflow", ignore=shutil.ignore_patterns("artifacts", "workflow.lock"))
        for name in (STATE_FILE, "frozen.json", "candidate.json", "summary.json", "stage-one-result.json", "evaluation.json", "first-evaluation.json", "features.json", "validation.json", "failure.json", "preflight.json"):
            if (source / name).exists():
                shutil.copyfile(source / name, target / name)
        if (source / "candidates").exists():
            shutil.copytree(source / "candidates", target / "candidates")
    save(destination / "batch-summary.json", summary)
    for name in ("run-session.json", "batch-manifest.json"):
        if (batch / name).exists():
            shutil.copyfile(batch / name, destination / name)
    return destination
