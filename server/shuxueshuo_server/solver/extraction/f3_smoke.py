"""Run F3 Doubao multimodal extraction over the authored five-case corpus."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.f0_adapter import (
    build_f0_extraction_context_seed,
)
from shuxueshuo_server.solver.extraction.f3_attempt import (
    F3ExtractionAttemptResult,
    F3ExtractionAttemptService,
)
from shuxueshuo_server.solver.extraction.f3_debug import F3AttemptDebugWriter
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MULTIMODAL_MAX_OUTPUT_TOKENS,
    OUTPUT_CONTRACT,
    SYSTEM_PROMPT,
    DoubaoMultimodalExtractionProvider,
    MultimodalProviderError,
)
from shuxueshuo_server.solver.extraction.multimodal_candidates import (
    ProblemExtractionCandidatePatch,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
)
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


DEFAULT_F2_INPUT = (
    "internal/solver-runs/problem-extraction/f2-sixth-review-guided"
)


@dataclass(frozen=True)
class F3SmokeSampleResult:
    problem_id: str
    sample_index: int
    ok: bool
    attempt_result: str
    candidate_counts: Mapping[str, int]
    coarse_coverage: Mapping[str, Any]
    usage: Mapping[str, Any]
    latency_ms: int
    full_question_image_input: bool
    crop_only_request_count: int
    handwritten_only_evidence_candidate_count: int
    model_contract_clean: bool
    normalized_review_region_count: int
    failures: tuple[str, ...]
    sample_dir: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "sample_index": self.sample_index,
            "ok": self.ok,
            "attempt_result": self.attempt_result,
            "candidate_counts": dict(self.candidate_counts),
            "coarse_coverage": dict(self.coarse_coverage),
            "usage": dict(self.usage),
            "latency_ms": self.latency_ms,
            "full_question_image_input": self.full_question_image_input,
            "crop_only_request_count": self.crop_only_request_count,
            "handwritten_only_evidence_candidate_count": (
                self.handwritten_only_evidence_candidate_count
            ),
            "model_contract_clean": self.model_contract_clean,
            "normalized_review_region_count": (
                self.normalized_review_region_count
            ),
            "failures": list(self.failures),
            "sample_dir": self.sample_dir,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all")
    parser.add_argument("--samples-per-case", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--f2-input-dir", default=DEFAULT_F2_INPUT)
    parser.add_argument(
        "--output-root",
        default="internal/solver-runs/problem-extraction/f3",
    )
    args = parser.parse_args(argv)
    if args.samples_per_case < 1 or args.concurrency < 1:
        parser.error("samples-per-case and concurrency must be positive")
    if os.environ.get("RUN_LLM_INTEGRATION") != "1":
        parser.error("live F3 smoke requires RUN_LLM_INTEGRATION=1")

    repo_root = _repo_root()
    f2_root = _resolve_repo_path(repo_root, args.f2_input_dir)
    output_root = _resolve_repo_path(repo_root, args.output_root)
    batch_dir = output_root / args.batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    config = SolverRuntimeConfig.from_sources(env_file=repo_root / "server/.env")
    corpus = load_gold_corpus()
    cases = _selected_cases(corpus.cases, args.case, parser)
    batch_config = {
        "schema_version": "f3-smoke-config/v1",
        "batch_id": args.batch_id,
        "case_ids": [item.problem_id for item in cases],
        "samples_per_case": args.samples_per_case,
        "concurrency": args.concurrency,
        "provider": "doubao",
        "model": config.doubao_model,
        "thinking_mode": "disabled",
        "response_format": "json_object",
        "temperature": 0,
        "max_output_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
        "f2_input_dir": str(f2_root),
        "prompt_hash": stable_hash(
            {"system": SYSTEM_PROMPT, "output_contract": OUTPUT_CONTRACT}
        ),
    }
    _write_json(batch_dir / "batch-config.json", batch_config)

    jobs = [
        (case, sample_index)
        for case in cases
        for sample_index in range(1, args.samples_per_case + 1)
    ]
    results: list[F3SmokeSampleResult] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                _run_sample,
                case,
                sample_index,
                batch_dir=batch_dir,
                f2_root=f2_root,
                config=config,
            ): (case.problem_id, sample_index)
            for case, sample_index in jobs
        }
        for future in as_completed(futures):
            problem_id, sample_index = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                sample_dir = batch_dir / problem_id / f"sample-{sample_index:02d}"
                sample_dir.mkdir(parents=True, exist_ok=True)
                result = F3SmokeSampleResult(
                    problem_id=problem_id,
                    sample_index=sample_index,
                    ok=False,
                    attempt_result="unclassified_error",
                    candidate_counts={},
                    coarse_coverage={},
                    usage={},
                    latency_ms=0,
                    full_question_image_input=False,
                    crop_only_request_count=0,
                    handwritten_only_evidence_candidate_count=0,
                    model_contract_clean=False,
                    normalized_review_region_count=0,
                    failures=(f"{exc.__class__.__name__}: {exc}",),
                    sample_dir=str(sample_dir),
                )
                _write_json(sample_dir / "sample-result.json", result.to_payload())
            results.append(result)
            print(
                f"{problem_id}/sample-{sample_index:02d}: "
                f"ok={result.ok} result={result.attempt_result} "
                f"coverage={result.coarse_coverage.get('ratio', 0):.3f}"
            )

    summary = _batch_summary(batch_config, results)
    _write_json(batch_dir / "batch-summary.json", summary)
    _write_review_index(batch_dir, results)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _run_sample(
    case: GoldCorpusCase,
    sample_index: int,
    *,
    batch_dir: Path,
    f2_root: Path,
    config: SolverRuntimeConfig,
) -> F3SmokeSampleResult:
    sample_dir = batch_dir / case.problem_id / f"sample-{sample_index:02d}"
    sample_dir.mkdir(parents=True, exist_ok=True)
    context = _load_f2_context(case, f2_root)
    input_store = ExtractionArtifactStore(f2_root / "artifacts")
    output_store = ExtractionArtifactStore(sample_dir / "artifacts")
    provider = DoubaoMultimodalExtractionProvider(
        api_key=config.doubao_api_key or "",
        base_url=config.doubao_base_url,
        model=config.doubao_model,
    )
    result = F3ExtractionAttemptService(
        input_artifact_reader=input_store,
        output_artifact_store=output_store,
        provider=provider,
    ).execute(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )
    F3AttemptDebugWriter().write(
        result,
        sample_dir,
        attempt_index=1,
        input_artifact_reader=input_store,
    )
    coverage = _coarse_gold_coverage(case, result)
    candidate_counts = result.summary_payload()["candidate_counts"]
    full_question_image_input = bool(result.request.images) and all(
        item.artifact.kind == "selection_crop"
        for item in result.request.images
    )
    crop_only_request_count = int(
        bool(result.request.images) and not full_question_image_input
    )
    evidence_by_id = result.evidence_pack.evidence_by_id
    handwritten_only_count = sum(
        bool(candidate.evidence_refs)
        and all(
            evidence_by_id[ref].origin == "handwritten"
            for ref in candidate.evidence_refs
        )
        for candidate in (
            result.candidate_patch.candidates
            if result.candidate_patch is not None
            else ()
        )
    )
    failures = []
    if not result.ok:
        first = result.validation_report.issues[0]
        failures.append(f"{first.code}: {first.message}")
    for candidate_type in ("scope", "entity", "fact", "goal"):
        if candidate_counts[candidate_type] == 0:
            failures.append(f"missing_candidate_type:{candidate_type}")
    if coverage["ratio"] < 1.0:
        failures.append("coarse_gold_evidence_incomplete")
    sample = F3SmokeSampleResult(
        problem_id=case.problem_id,
        sample_index=sample_index,
        ok=not failures,
        attempt_result=result.attempt.result,
        candidate_counts=candidate_counts,
        coarse_coverage=coverage,
        usage=(
            result.provider_response.usage or {}
            if result.provider_response is not None
            else {}
        ),
        latency_ms=result.attempt.latency_ms,
        full_question_image_input=full_question_image_input,
        crop_only_request_count=crop_only_request_count,
        handwritten_only_evidence_candidate_count=handwritten_only_count,
        model_contract_clean=not result.validation_report.normalizations,
        normalized_review_region_count=(
            result.validation_report.normalized_review_region_count
        ),
        failures=tuple(failures),
        sample_dir=str(sample_dir),
    )
    _write_json(sample_dir / "sample-result.json", sample.to_payload())
    return sample


def _load_f2_context(
    case: GoldCorpusCase,
    f2_root: Path,
) -> ProblemExtractionContext:
    context_path = f2_root / case.problem_id / "problem-extraction-context.json"
    if not context_path.is_file():
        raise FileNotFoundError(f"F2 Context is missing: {context_path}")
    payload = json.loads(context_path.read_text(encoding="utf-8"))
    _relocate_artifact_locators(payload, f2_root / "artifacts")
    semantic_config = payload["dependency"]["semantic_config"]
    attempt_budget = int(payload["retry"]["attempt_budget"])
    parent = build_f0_extraction_context_seed(
        case,
        semantic_config=semantic_config,
        attempt_budget=attempt_budget,
    ).context
    expected_parent = payload["manifest"]["parent_context_id"]
    if parent.manifest.context_id != expected_parent:
        raise ValueError(
            "F2 Context parent does not match the current F0 corpus/dependency"
        )
    return ProblemExtractionContext.from_payload(
        payload,
        ancestor_contexts=(parent,),
    )


def _relocate_artifact_locators(payload: dict[str, Any], artifact_root: Path) -> None:
    for artifact in payload["state"]["artifacts"]:
        digest = str(artifact["sha256"])
        old_locator = artifact.get("locator")
        suffix = Path(old_locator).suffix if old_locator else _artifact_suffix(artifact)
        candidate = artifact_root / digest[:2] / f"{digest}{suffix}"
        if not candidate.is_file():
            raise FileNotFoundError(f"F2 artifact is missing: {candidate}")
        artifact["locator"] = str(candidate.resolve())


def _artifact_suffix(artifact: Mapping[str, Any]) -> str:
    media_type = artifact.get("media_type")
    if media_type == "application/json":
        return ".json"
    if media_type == "text/plain":
        return ".txt"
    return ".png"


def _coarse_gold_coverage(
    case: GoldCorpusCase,
    result: F3ExtractionAttemptResult,
) -> dict[str, Any]:
    if result.candidate_patch is None:
        return {
            "metric": "coarse_bbox_overlap_v1",
            "semantic_validation": False,
            "covered": 0,
            "total": 0,
            "ratio": 0.0,
            "missing": ["patch"],
        }
    return _coarse_gold_coverage_for_patch(
        case,
        result.evidence_pack,
        result.candidate_patch,
    )


def _coarse_gold_coverage_for_patch(
    case: GoldCorpusCase,
    evidence_pack: MultimodalEvidencePack,
    candidate_patch: ProblemExtractionCandidatePatch,
) -> dict[str, Any]:
    """Measure only spatial evidence overlap, never semantic correctness."""
    evidence_by_id = {
        item.evidence_id: item for item in case.annotation.evidence
    }
    region_by_id = evidence_pack.evidence_by_id
    category_map = {
        "scope": "scopes",
        "entity": "entities",
        "fact": "facts",
        "goal": "question_goals",
    }
    ambiguities_by_candidate: dict[str, list[Any]] = {}
    for ambiguity in candidate_patch.ambiguities:
        for candidate_id in ambiguity.candidate_ids:
            ambiguities_by_candidate.setdefault(candidate_id, []).append(ambiguity)
    covered = 0
    total = 0
    missing: list[str] = []
    for candidate_type, category in category_map.items():
        authored = case.annotation.semantic_evidence.get(category, {})
        candidates = tuple(
            item
            for item in candidate_patch.candidates
            if item.candidate_type == candidate_type
        )
        for identity, gold_refs in authored.items():
            total += 1
            gold_items = tuple(
                evidence_by_id[ref]
                for ref in gold_refs
                if ref in evidence_by_id
            )
            matched = any(
                any(
                    _regions_overlap(region_by_id[ref], gold)
                    for gold in gold_items
                    for ref in _coverage_refs(
                        candidate,
                        ambiguities_by_candidate.get(candidate.candidate_id, ()),
                        gold.origin,
                    )
                    if ref in region_by_id
                )
                for candidate in candidates
            )
            if matched:
                covered += 1
            else:
                missing.append(f"{category}:{identity}")
    return {
        "metric": "coarse_bbox_overlap_v1",
        "semantic_validation": False,
        "covered": covered,
        "total": total,
        "ratio": round(covered / total, 6) if total else 0.0,
        "missing": missing,
    }


def _coverage_refs(
    candidate: Any,
    ambiguities: Sequence[Any],
    gold_origin: str,
) -> tuple[str, ...]:
    if gold_origin == "printed":
        return tuple(candidate.evidence_refs)
    if gold_origin in {"mixed", "unknown"}:
        # A broad authored mixed region may contain a smaller F2 observation that
        # was independently classified as printed. That printed evidence remains
        # valid; uncertain evidence is already guarded by patch validation.
        refs = list(candidate.evidence_refs)
        refs.extend(candidate.review_region_refs)
        for ambiguity in ambiguities:
            refs.extend(ambiguity.evidence_refs)
            refs.extend(ambiguity.review_region_refs)
        return tuple(dict.fromkeys(refs))
    return ()


def _regions_overlap(region: Any, gold: Any) -> bool:
    if region.page_id != gold.page_id:
        return False
    left = _bbox(region.polygon)
    right = _bbox(gold.polygon)
    intersection = max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0,
        min(left[3], right[3]) - max(left[1], right[1]),
    )
    area = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    return bool(area and intersection / area >= 0.1)


def _bbox(polygon: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    return (
        min(x for x, _ in polygon),
        min(y for _, y in polygon),
        max(x for x, _ in polygon),
        max(y for _, y in polygon),
    )


def _batch_summary(
    config: Mapping[str, Any],
    results: Sequence[F3SmokeSampleResult],
) -> dict[str, Any]:
    total = len(results)
    succeeded = sum(item.ok for item in results)
    unclassified = sum(item.attempt_result == "unclassified_error" for item in results)
    contract_errors = sum(
        item.attempt_result not in {"succeeded", "unclassified_error"}
        for item in results
    )
    usage: dict[str, float] = {}
    for result in results:
        for key, value in result.usage.items():
            if isinstance(value, (int, float)):
                usage[key] = usage.get(key, 0) + value
    return {
        "schema_version": "f3-smoke-summary/v1",
        "batch_id": config["batch_id"],
        "ok": total > 0 and succeeded == total,
        "sample_count": total,
        "passed_count": succeeded,
        "provider": config["provider"],
        "model": config["model"],
        "thinking_mode": config["thinking_mode"],
        "response_format": config["response_format"],
        "full_question_image_input_rate": (
            round(
                sum(item.full_question_image_input for item in results) / total,
                6,
            )
            if total
            else 0.0
        ),
        "crop_only_request_count": sum(
            item.crop_only_request_count for item in results
        ),
        "configuration_error_count": sum(
            any("provider_config_invalid" in failure for failure in item.failures)
            for item in results
        ),
        "contract_error_count": contract_errors,
        "unclassified_error_count": unclassified,
        "handwritten_only_evidence_candidate_count": sum(
            item.handwritten_only_evidence_candidate_count for item in results
        ),
        "coarse_gold_evidence_coverage_rate": (
            round(
                sum(
                    float(item.coarse_coverage.get("ratio", 0.0))
                    for item in results
                )
                / total,
                6,
            )
            if total
            else 0.0
        ),
        "coverage_metric": "coarse_bbox_overlap_v1",
        "coverage_is_semantic_validation": False,
        "model_contract_clean_rate": (
            round(
                sum(item.model_contract_clean for item in results) / total,
                6,
            )
            if total
            else 0.0
        ),
        "normalized_sample_count": sum(
            not item.model_contract_clean for item in results
        ),
        "normalized_review_region_count": sum(
            item.normalized_review_region_count for item in results
        ),
        "usage": usage,
        "cases": [
            item.to_payload()
            for item in sorted(results, key=lambda value: (value.problem_id, value.sample_index))
        ],
        "review_index": "review.html",
    }


def _write_review_index(
    batch_dir: Path,
    results: Sequence[F3SmokeSampleResult],
) -> None:
    links = "".join(
        f'<li><a href="{Path(item.sample_dir).relative_to(batch_dir).as_posix()}/review.html">'
        f"{item.problem_id}/sample-{item.sample_index:02d}</a> · "
        f"{'PASS' if item.ok else 'FAIL'}</li>"
        for item in sorted(results, key=lambda value: (value.problem_id, value.sample_index))
    )
    (batch_dir / "review.html").write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>F3 review</title>"
        "<style>body{font:15px system-ui;max-width:900px;margin:32px auto;line-height:1.6}</style>"
        "<h1>F3 豆包多模态提取审查</h1><ul>" + links + "</ul>",
        encoding="utf-8",
    )


def _selected_cases(
    cases: Sequence[GoldCorpusCase],
    selection: str,
    parser: argparse.ArgumentParser,
) -> tuple[GoldCorpusCase, ...]:
    requested = (
        {item.problem_id for item in cases}
        if selection == "all"
        else {item.strip() for item in selection.split(",") if item.strip()}
    )
    selected = tuple(item for item in cases if item.problem_id in requested)
    missing = requested - {item.problem_id for item in selected}
    if missing or not selected:
        parser.error(f"unknown or empty case selection: {sorted(missing or requested)}")
    return selected


def _resolve_repo_path(repo_root: Path, value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
