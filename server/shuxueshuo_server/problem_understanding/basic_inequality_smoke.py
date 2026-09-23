"""Stage-0 image-only DeepSeek batch for representative basic inequalities.

Each sample gets an isolated output directory and a fresh provider instance.
This deliberately reuses the normal notation ``smoke.run`` gate, so no
ProblemIR, Method or runtime binding is entered by this batch.
"""

from __future__ import annotations

import argparse
import json
import shutil
from hashlib import sha256
from pathlib import Path

from .batch_smoke import live_provider_factory, preflight
from .identity import revision
from .notation_contract import CONTRACT
from .notation_family_catalog import notation_family_catalog
from .smoke import run

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "server/tests/solver/fixtures/math-notation-v1/basic-inequality"
MANIFEST_PATH = FIXTURES / "manifest.json"
CASES = tuple(json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["cases"])
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
SAMPLES_PER_CASE = int(MANIFEST["samples_per_case"])
DEFERRED_CASES = MANIFEST["deferred_cases"]


def failure_category(result: dict) -> str | None:
    """Map the shared smoke result to the stage-0 audit vocabulary."""

    if result.get("passed"):
        return None
    code = str(result.get("error_code") or "")
    if code.startswith(("provider.", "transport.", "network.")):
        return "provider_or_network_error"
    if not result.get("contract_valid", False):
        return "json_or_schema_or_notation_error"
    if result.get("match_correct") is False:
        return "family_mismatch"
    if result.get("strict_semantics_passed") is False:
        return "semantic_gold_difference"
    return "verification_failed"


def prepare_fixture(case: str, output: Path) -> Path:
    if case not in CASES:
        raise ValueError("unknown basic inequality case: " + case)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entry = manifest["images"][case]
    source = FIXTURES / entry["file"]
    if sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
        raise ValueError("selected image hash mismatch: " + case)
    from PIL import Image

    with Image.open(source) as image:
        if image.format != "PNG" or list(image.size) != entry["size"]:
            raise ValueError("selected image dimensions/format mismatch: " + case)
        width, height = image.size
    fixture = output / "input-fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, fixture / "source.png")
    observation = {
        "schema_version": "understanding-image-only-observation/v1",
        "evidence_origin": "image_only_no_ocr",
        "source_revision_hash": entry["sha256"],
        "pages": [{"page_id": "page-1", "width": width, "height": height}],
        "text_spans": [],
        "formulas": [],
    }
    observation["observation_hash"] = revision(observation)
    (fixture / "observation.json").write_text(
        json.dumps(observation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    gold = FIXTURES / f"{case}.json"
    shutil.copyfile(gold, fixture / "gold.json")
    files = ["source.png", "observation.json", "gold.json"]
    provenance = {
        "case_id": case,
        "output_contract": CONTRACT,
        "image_sha256": entry["sha256"],
        "image_file": "source.png",
        "observation_origin": "image_only_no_ocr",
        "source_manifest": str(MANIFEST_PATH.relative_to(REPO)),
        "image_selection": entry,
        "files": [
            {
                "file": name,
                "fixture_sha256": sha256((fixture / name).read_bytes()).hexdigest(),
            }
            for name in files
        ],
    }
    (fixture / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return fixture


def run_batch(
    output: Path,
    *,
    cases: tuple[str, ...] = CASES,
    samples: int = SAMPLES_PER_CASE,
    provider_factory=None,
):
    if samples not in (1, 2):
        raise ValueError("stage 0 supports one smoke sample or two gate samples")
    registry = list(notation_family_catalog())
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    for case in cases:
        for sample in range(1, samples + 1):
            sample_root = output / case / f"sample-{sample:02d}"
            fixture = prepare_fixture(case, sample_root)
            provider = provider_factory()
            preflight(fixture, sample_root, provider, registry)
            result = run(fixture, sample_root / "run", provider, registry)
            result["failure_category"] = failure_category(result)
            results[f"{case}.{sample:02d}"] = result
    summary = {
        "schema_version": "basic-inequality-math-notation-batch/v1",
        "output_contract": CONTRACT,
        "cases": list(cases),
        "samples_per_case": samples,
        "total_samples": len(cases) * samples,
        "passed": sum(bool(item["passed"]) for item in results.values()),
        "results": results,
        "registry_snapshot": revision(registry),
        "scope": "stage_0_image_only_notation_extraction_no_solver",
    }
    (output / "batch-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=("all", *CASES), default="all")
    parser.add_argument("--provider", choices=("deepseek", "doubao"), default="deepseek")
    parser.add_argument("--samples", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    cases = CASES if args.case == "all" else (args.case,)
    result = run_batch(
        args.output,
        cases=cases,
        samples=args.samples,
        provider_factory=live_provider_factory(args.provider),
    )
    raise SystemExit(0 if result["passed"] == result["total_samples"] else 1)


if __name__ == "__main__":
    main()
