"""Seven-case compact IR visual extraction, independent of Solver execution/DB."""

import argparse
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
from time import perf_counter

from .candidate_common import validate_match
from .identity import revision
from .notation_contract import CONTRACT
from .smoke import build_request, run
from .transport_accounting import transport_cohorts
from .wire import components

REPO = Path(__file__).resolve().parents[3]
NOTATION_FIXTURES = REPO / "server/tests/solver/fixtures/math-notation-v1"
TEST_IMAGES = NOTATION_FIXTURES / "integration-images-20260916"
CASES = tuple(
    "tj-2026-" + x + "-25"
    for x in ("heping-yimo", "heping-ermo", "hexi-yimo", "nankai-yimo", "xiqing-yimo")
) + ("k-quad", "function-quantifiers")


def prepare_fixture(case, output, *, contract=CONTRACT):
    """Freeze reviewed images without leaking OCR from the old full-page inputs."""
    if case not in CASES:
        raise ValueError("unknown case")
    components(contract)  # Explicit version check before creating any files.
    from PIL import Image

    manifest = json.loads((TEST_IMAGES / "manifest.json").read_text())
    selected = manifest["cases"][case]
    source = TEST_IMAGES / selected["file"]
    digest = sha256(source.read_bytes()).hexdigest()
    if digest != selected["sha256"]:
        raise ValueError("selected image hash mismatch: " + case)
    with Image.open(source) as image:
        width, height = image.size
        if image.format != "PNG" or [width, height] != selected["size"]:
            raise ValueError("selected image dimensions/format mismatch: " + case)
    # This sidecar is explicitly image-only, not fabricated or reused OCR.
    # Missing-figure expectations stay in provenance/gold, never in the prompt.
    observation = {
        "schema_version": "understanding-image-only-observation/v1",
        "evidence_origin": "image_only_no_ocr",
        "source_revision_hash": digest,
        "pages": [{"page_id": "page-1", "width": width, "height": height}],
        "text_spans": [],
        "formulas": [],
    }
    observation["observation_hash"] = revision(observation)
    fixture = output / "input-fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    image_name = "source.png"
    shutil.copyfile(source, fixture / image_name)
    (fixture / "observation.json").write_text(
        json.dumps(observation, ensure_ascii=False, indent=2) + "\n"
    )
    gold = NOTATION_FIXTURES / (case + ".json")
    shutil.copyfile(gold, fixture / "gold.json")
    files = [image_name, "observation.json", "gold.json"]
    revisions = json.loads((NOTATION_FIXTURES / "gold-revisions.json").read_text())
    reviewed = revisions["cases"][case]
    if sha256(gold.read_bytes()).hexdigest() != reviewed["sha256"]:
        raise ValueError("reviewed gold hash mismatch: " + case)
    (fixture / "gold-revision.json").write_text(
        json.dumps(
            {"revision": revisions["revision"], "case": case, **reviewed},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    files.append("gold-revision.json")
    policy = NOTATION_FIXTURES / (case + ".acceptance-policy.json")
    if policy.exists():
        shutil.copyfile(policy, fixture / "acceptance-policy.json")
        files.append("acceptance-policy.json")
    provenance = {
        "case_id": case,
        "output_contract": contract,
        "image_sha256": digest,
        "image_file": image_name,
        "observation_origin": "image_only_no_ocr",
        "source_manifest": str((TEST_IMAGES / "manifest.json").relative_to(REPO)),
        "image_selection": selected,
        "files": [
            {
                "file": n,
                "fixture_sha256": sha256((fixture / n).read_bytes()).hexdigest(),
            }
            for n in files
        ],
    }
    (fixture / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"
    )
    return fixture


def preflight(fixture, output, provider, registry):
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

    request = provider.prepare_request(
        build_request(fixture, ExtractionArtifactStore(output / "preflight"), registry)
    )
    gold = json.loads((fixture / "gold.json").read_text())
    contract = json.loads((fixture / "provenance.json").read_text()).get(
        "output_contract"
    )
    _, Validator, _, evaluate_wire, *_ = components(contract)
    report = Validator().validate(gold)
    if (
        not report.ok
        or not validate_match(gold, [f["family_id"] for f in registry])["ok"]
    ):
        raise ValueError("invalid gold fixture: " + str(report.issues))
    policy = fixture / "acceptance-policy.json"
    acceptance = evaluate_wire(
        gold, gold, json.loads(policy.read_text()) if policy.exists() else None
    )
    if not acceptance["ok"]:
        raise ValueError("gold semantic preflight failed: " + str(acceptance))
    return request


def run_batch(
    output,
    cases,
    provider_factory,
    registry,
    concurrency=3,
    *,
    contract=CONTRACT,
    workflow="single",
):
    if workflow not in {"single", "review-repair"}:
        raise ValueError("unsupported extraction workflow")
    if not 1 <= concurrency <= 3 or not cases or len(set(cases)) != len(cases):
        raise ValueError("invalid batch concurrency or cases")
    runner = run
    if workflow == "review-repair":
        from .workflow_smoke import run as runner
    output.mkdir(parents=True, exist_ok=False)
    prepared = {}
    image_transports = {}
    frozen_cases = {}
    # Verify every dependency and gold before paying for any case.
    for case in cases:
        target = output / case
        fixture = prepare_fixture(case, target, contract=contract)
        provider = provider_factory()
        request = preflight(fixture, target, provider, registry)
        image_transports[case] = request.image_transport
        if workflow == "review-repair":
            from .workflow_smoke import freeze_inputs

            frozen_cases[case] = freeze_inputs(fixture, request, registry)
        prepared[case] = fixture, provider
    if workflow == "review-repair":
        from .workflow_ledger import save

        save(
            output / "frozen-batch.json",
            {"cases": frozen_cases, "concurrency": concurrency},
        )
    results = {}
    started = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(runner, fixture, output / case, provider, registry): case
            for case, (fixture, provider) in prepared.items()
        }
        for future in as_completed(futures):
            case = futures[future]
            try:
                results[case] = future.result()
            except Exception as exc:  # noqa: BLE001 - retain case failure and finish the bounded batch
                results[case] = {
                    "case_id": case,
                    "passed": False,
                    "error_type": type(exc).__name__,
                }
            results[case]["image_transport"] = image_transports[case]
            print(json.dumps(results[case], ensure_ascii=False), flush=True)
            summary = {
                "schema_version": "understanding-batch/v1",
                "output_contract": contract,
                "cases": list(cases),
                "completed": len(results),
                "passed": sum(bool(r["passed"]) for r in results.values()),
                "results": results,
                "image_transport_by_case": image_transports,
                "kpi_by_image_transport": transport_cohorts(results),
                "scope": "compact_ir_extraction_only_no_solver_or_review"
                if workflow == "single"
                else "compact_ir_review_repair_no_solver",
                "workflow": workflow,
                "wall_seconds": round(perf_counter() - started, 3),
            }
            if workflow == "review-repair":
                summary["first_passed"] = sum(
                    bool(r.get("first_passed")) for r in results.values()
                )
            (output / "batch-summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
            )
    return summary


def live_provider_factory(provider_name="deepseek", *, image_transport=None):
    from dotenv import load_dotenv

    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        DeepSeekMultimodalExtractionProvider,
    )
    from shuxueshuo_server.solver.runtime.config import (
        DEFAULT_DOUBAO_BASE_URL,
        DEFAULT_DOUBAO_MODEL,
    )

    from .comparison_provider import DoubaoComparisonProvider

    if image_transport is None:
        image_transport = "files" if provider_name == "deepseek" else "base64"
    if image_transport not in {"files", "base64"}:
        raise ValueError("unsupported image transport")
    if provider_name == "doubao" and image_transport != "base64":
        raise ValueError("Doubao comparison supports base64 image transport only")
    if os.getenv("RUN_LLM_INTEGRATION") != "1":
        raise ValueError("RUN_LLM_INTEGRATION=1 required")
    load_dotenv(REPO / "server/.env")
    load_dotenv(REPO / ".env")
    if provider_name == "doubao":
        key = os.getenv("DOUBAO_API_KEY")
        if not key:
            raise ValueError("missing DOUBAO_API_KEY; live gate not executed")
        return lambda: DoubaoComparisonProvider(
            api_key=key,
            base_url=os.getenv("DOUBAO_BASE_URL") or DEFAULT_DOUBAO_BASE_URL,
            model=os.getenv("DOUBAO_MODEL") or DEFAULT_DOUBAO_MODEL,
            request_timeout=300,
            max_output_tokens=16384,
        )
    if provider_name != "deepseek":
        raise ValueError("unsupported comparison provider")
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("missing DEEPSEEK_API_KEY; live gate not executed")
    return lambda: DeepSeekMultimodalExtractionProvider(
        api_key=key,
        base_url="https://api.deepseek.com",
        model="deepseek-flash",
        request_timeout=300,
        max_output_tokens=16384,
        file_cache_dir=(
            REPO / "internal/solver-runs/.deepseek-files-cache"
            if image_transport == "files"
            else None
        ),
    )


def main():
    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        problem_domain_family_catalog,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("all", *CASES), default="all")
    parser.add_argument(
        "--provider", choices=("deepseek", "doubao"), default="deepseek"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--image-transport",
        choices=("files", "base64"),
        help="DeepSeek defaults to files; Doubao supports base64 only",
    )
    parser.add_argument("--contract", choices=(CONTRACT,), default=CONTRACT)
    parser.add_argument("--concurrency", type=int, choices=range(1, 4), default=3)
    parser.add_argument(
        "--workflow", choices=("single", "review-repair"), default="single"
    )
    args = parser.parse_args()
    cases = CASES if args.case == "all" else (args.case,)
    result = run_batch(
        args.output,
        cases,
        live_provider_factory(args.provider, image_transport=args.image_transport),
        list(problem_domain_family_catalog()),
        args.concurrency,
        contract=args.contract,
        workflow=args.workflow,
    )
    raise SystemExit(0 if result["passed"] == len(cases) else 1)


if __name__ == "__main__":
    main()
