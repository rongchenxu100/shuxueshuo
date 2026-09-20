"""Two authorized seven-case live batches; no semantic retries or repairs."""

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from shuxueshuo_server.problem_understanding.batch_smoke import (
    CASES, REPO, live_provider_factory, prepare_fixture, preflight, run_batch,
)
from shuxueshuo_server.problem_understanding.notation_contract import CONTRACT, TEMPLATE_FILES
from shuxueshuo_server.problem_understanding.smoke import build_request
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.multimodal_provider import problem_domain_family_catalog

HERE = Path(__file__).resolve().parent
BATCH = REPO / "internal/solver-runs/math-notation-provider-comparison-20260916-153340"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def hashes():
    package = REPO / "server/shuxueshuo_server/problem_understanding"
    paths = [*package.glob("*.py"), *TEMPLATE_FILES]
    return {str(p.relative_to(REPO)): sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def main():
    BATCH.mkdir(parents=True, exist_ok=False)
    registry = list(problem_domain_family_catalog())
    factories = {p: live_provider_factory(p) for p in ("deepseek", "doubao")}
    frozen = {"contract": CONTRACT, "code_and_templates": hashes(), "cases": list(CASES),
              "providers": {}, "inputs": {}, "concurrency_per_batch": 3,
              "execution": "sequential_provider_batches", "semantic_calls_per_case": 1,
              "network_attempts_per_case_max": 2, "timeout_seconds": 300,
              "max_output_tokens": 16384, "frozen_at": datetime.now(timezone.utc).isoformat()}
    # Preflight BOTH providers and all inputs before any paid request.
    for name, factory in factories.items():
        client = factory()
        for case in CASES:
            target = BATCH / "preflight" / name / case
            fixture = prepare_fixture(case, target)
            preflight(fixture, target, client, registry)
            request = client.prepare_request(build_request(fixture, ExtractionArtifactStore(target / "request"), registry))
            save(target / "request.json", request.redacted_payload())
            metadata = {"model": client.model, "thinking_mode": request.thinking_mode,
                        "reasoning_effort": request.reasoning_effort}
            frozen["providers"][name] = metadata
            source = {p.name: sha256(p.read_bytes()).hexdigest() for p in fixture.iterdir() if p.is_file()}
            if case in frozen["inputs"]:
                assert frozen["inputs"][case] == source
            else:
                frozen["inputs"][case] = source
    save(BATCH / "frozen-comparison.json", frozen)
    print(json.dumps({"preflight": "passed", "providers": frozen["providers"], "cases": len(CASES)}, ensure_ascii=False), flush=True)
    timings = {}
    for name, factory in factories.items():
        assert hashes() == frozen["code_and_templates"], "code/template changed after freeze"
        began = datetime.now(timezone.utc).isoformat()
        start = perf_counter()
        print("Starting " + name, flush=True)
        try:
            result = run_batch(BATCH / name, CASES, factory, registry, concurrency=3)
            row = {"passed": result["passed"], "completed": result["completed"]}
        except Exception as exc:
            # Retain incomplete batches; never start an extra paid batch.
            row = {"fatal_error_type": type(exc).__name__}
        row.update(started_at=began, finished_at=datetime.now(timezone.utc).isoformat(),
                   wall_seconds=round(perf_counter() - start, 3))
        timings[name] = row
        save(BATCH / "timings.json", timings)
        print(json.dumps({"provider": name, **row}, ensure_ascii=False), flush=True)
    assert hashes() == frozen["code_and_templates"], "code/template changed during runs"
    save(HERE / "run-locations.json", {"batch": str(BATCH), "timings": timings, "network_runs": 2})


if __name__ == "__main__":
    main()
