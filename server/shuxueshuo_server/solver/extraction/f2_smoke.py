"""Run the real local Paddle F2 pipeline over the authored five-case corpus."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageOps

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
)
from shuxueshuo_server.solver.extraction.f0_adapter import (
    F0ExtractionContextSeed,
    build_f0_extraction_context_seed,
)
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.observation_context import (
    ObservationContextTransitionService,
    f2_semantic_config,
)
from shuxueshuo_server.solver.extraction.observation_pipeline import (
    F2ObservationAssemblyResult,
    F2ObservationPipeline,
    crop_formula_request,
)
from shuxueshuo_server.solver.extraction.observations import (
    PaddleProviderRecord,
    Polygon,
    SourceObservation,
)
from shuxueshuo_server.solver.extraction.paddle_worker import (
    FormulaWorkerInput,
    PaddleF2ProviderWorker,
    PaddleProviderRun,
)
from shuxueshuo_server.solver.extraction.review import (
    ObservationReviewCase,
    render_observation_review_pack,
)


@dataclass(frozen=True)
class F2SmokeCaseResult:
    problem_id: str
    ok: bool
    observation_hash: str
    context_id: str
    metrics: Mapping[str, Any]
    failures: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "ok": self.ok,
            "observation_hash": self.observation_hash,
            "context_id": self.context_id,
            "metrics": dict(self.metrics),
            "failures": list(self.failures),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all", help="all, a problem id, or a comma-separated list")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--replay-provider-records",
        help="read <case>/provider-records records instead of importing Paddle",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus = load_gold_corpus()
    selected_ids = (
        {item.strip() for item in args.case.split(",") if item.strip()}
        if args.case != "all"
        else {case.problem_id for case in corpus.cases}
    )
    cases = tuple(case for case in corpus.cases if case.problem_id in selected_ids)
    missing = selected_ids - {case.problem_id for case in cases}
    if missing or not cases:
        parser.error(f"unknown or empty case selection: {sorted(missing or selected_ids)}")

    replay_root = Path(args.replay_provider_records).resolve() if args.replay_provider_records else None
    recorded_runs = {
        case.problem_id: _load_provider_runs(replay_root, case.problem_id)
        for case in cases
    } if replay_root is not None else {}
    worker = None if replay_root is not None else PaddleF2ProviderWorker()
    provider_manifests = (
        _provider_manifests_from_runs(tuple(run for runs in recorded_runs.values() for run in runs))
        if replay_root is not None
        else worker.manifests()  # type: ignore[union-attr]
    )
    ink_analyzer = ConservativeInkOriginAnalyzer()
    semantic_config = f2_semantic_config(
        [item.to_payload() for item in provider_manifests + (ink_analyzer.provider,)]
    )
    store = ExtractionArtifactStore(output_dir / "artifacts")
    pipeline = F2ObservationPipeline(artifact_store=store, ink_analyzer=ink_analyzer)
    reviews: list[ObservationReviewCase] = []
    results: list[F2SmokeCaseResult] = []
    for case in cases:
        result, review = _run_case(
            case,
            output_dir=output_dir,
            store=store,
            pipeline=pipeline,
            worker=worker,
            semantic_config=semantic_config,
            recorded_runs=recorded_runs.get(case.problem_id),
        )
        results.append(result)
        reviews.append(review)
        print(
            f"{case.problem_id}: ok={result.ok} cer={result.metrics['normalized_ocr_cer']:.4f} "
            f"spans={result.metrics['text_span_count']} formulas={result.metrics['formula_count']} "
            f"issues={result.metrics['issue_count']}"
        )
    render_observation_review_pack(reviews, output_dir / "review")

    initialization_counts = dict(worker.initialization_counts) if worker is not None else {
        "layout": 0,
        "text_ocr": 0,
        "formula_ocr": 0,
    }
    expected_components = {"layout", "text_ocr", "formula_ocr"}
    initialization_ok = replay_root is not None or all(
        initialization_counts.get(item) == 1 for item in expected_components
    )
    payload = {
        "schema_version": "f2-smoke-summary/v1",
        "ok": all(item.ok for item in results) and initialization_ok,
        "case_count": len(results),
        "cases": [item.to_payload() for item in results],
        "model_initialization_counts": initialization_counts,
        "model_reuse_ok": initialization_ok,
        "recorded_provider_replay": replay_root is not None,
        "human_review_required": True,
        "review_index": str((output_dir / "review" / "index.html").resolve()),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 1


def _run_case(
    case: GoldCorpusCase,
    *,
    output_dir: Path,
    store: ExtractionArtifactStore,
    pipeline: F2ObservationPipeline,
    worker: PaddleF2ProviderWorker | None,
    semantic_config: Mapping[str, Any],
    recorded_runs: tuple[PaddleProviderRun, ...] | None = None,
) -> tuple[F2SmokeCaseResult, ObservationReviewCase]:
    seed = build_f0_extraction_context_seed(
        case,
        semantic_config=semantic_config,
        attempt_budget=max(8, len(case.manifest.pages) * 4),
    )
    page_bytes = _page_bytes(case)
    layout_runs = [item for item in recorded_runs or () if item.record.component == "layout"]
    text_runs = [item for item in recorded_runs or () if item.record.component == "text_ocr"]
    selection_crop_artifacts = []
    for source_page in seed.source.pages:
        content = page_bytes[source_page.page_id]
        if recorded_runs is None:
            if worker is None:
                raise RuntimeError("live F2 execution requires a Paddle worker")
            layout_runs.append(
                worker.layout(
                    source_revision_hash=seed.source.source_revision_hash,
                    page_id=source_page.page_id,
                    image_bytes=content,
                )
            )
        crop_bytes, crop_box = _selection_crop(seed, source_page.page_id, content)
        crop_ref = store.put_bytes(
            kind="selection_crop",
            content=crop_bytes,
            media_type="image/png",
            suffix=".png",
        )
        selection_crop_artifacts.append(crop_ref)
        if recorded_runs is None:
            crop_run = worker.text(
                source_revision_hash=seed.source.source_revision_hash,
                page_id=source_page.page_id,
                image_bytes=crop_bytes,
            )
            text_runs.append(
                _remap_text_run(
                    crop_run,
                    page_width=source_page.width,
                    page_height=source_page.height,
                    left=crop_box[0],
                    top=crop_box[1],
                )
            )

    _validate_selection_scoped_text_runs(seed, text_runs)

    _store_raw_runs(store, layout_runs + text_runs)
    initial = pipeline.assemble(
        source=seed.source,
        selection=seed.selection,
        dependency=seed.dependency,
        page_bytes=page_bytes,
        layout_records=tuple(item.record for item in layout_runs),
        text_records=tuple(item.record for item in text_runs),
        extra_artifacts=tuple(selection_crop_artifacts),
    )
    page_by_id = {item.page_id: item for item in initial.canonical_pages}
    requests_by_page: dict[str, list[FormulaWorkerInput]] = {
        page.page_id: [] for page in initial.canonical_pages
    }
    formula_crop_artifacts = []
    for request in initial.formula_requests:
        crop_ref = crop_formula_request(
            request,
            page_by_id[request.page_id],
            artifact_store=store,
        )
        formula_crop_artifacts.append(crop_ref)
        requests_by_page[request.page_id].append(
            FormulaWorkerInput(
                request=request,
                crop_bytes=store.read_bytes(crop_ref),
                crop_artifact_id=crop_ref.artifact_id,
            )
        )
    formula_runs = [item for item in recorded_runs or () if item.record.component == "formula_ocr"]
    if recorded_runs is None:
        formula_runs = [
            worker.formulas(  # type: ignore[union-attr]
                source_revision_hash=seed.source.source_revision_hash,
                page_id=page.page_id,
                page_width=page.width,
                page_height=page.height,
                inputs=requests_by_page[page.page_id],
            )
            for page in seed.source.pages
        ]
    _store_raw_runs(store, formula_runs)
    extra_artifacts = (
        tuple(selection_crop_artifacts)
        + tuple(formula_crop_artifacts)
    )
    final = pipeline.assemble(
        source=seed.source,
        selection=seed.selection,
        dependency=seed.dependency,
        page_bytes=page_bytes,
        layout_records=tuple(item.record for item in layout_runs),
        text_records=tuple(item.record for item in text_runs),
        formula_records=tuple(item.record for item in formula_runs),
        extra_artifacts=extra_artifacts,
    )
    _write_provider_records(case.problem_id, output_dir, layout_runs + text_runs + formula_runs)
    ledger = _provider_ledger(seed, final)
    context = ObservationContextTransitionService().attach(
        seed.context,
        final.observation,
        artifacts=final.artifacts,
        attempt_ledger=ledger,
    )

    replay = pipeline.assemble(
        source=seed.source,
        selection=seed.selection,
        dependency=seed.dependency,
        page_bytes=page_bytes,
        layout_records=tuple(PaddleProviderRecord.from_payload(item.record.to_payload()) for item in layout_runs),
        text_records=tuple(PaddleProviderRecord.from_payload(item.record.to_payload()) for item in text_runs),
        formula_records=tuple(PaddleProviderRecord.from_payload(item.record.to_payload()) for item in formula_runs),
        extra_artifacts=extra_artifacts,
    )
    replay_context = ObservationContextTransitionService().attach(
        seed.context,
        replay.observation,
        artifacts=replay.artifacts,
        attempt_ledger=_provider_ledger(seed, replay),
    )
    deterministic_replay = (
        replay.observation.observation_hash == final.observation.observation_hash
        and replay_context.manifest.context_id == context.manifest.context_id
        and tuple(item.artifact_id for item in replay.artifacts)
        == tuple(item.artifact_id for item in final.artifacts)
    )
    metrics, failures = evaluate_f2_acceptance(
        case,
        final.observation,
        deterministic_replay,
    )
    case_dir = output_dir / case.problem_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "problem-extraction-context.json").write_text(
        json.dumps(context.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (case_dir / "acceptance.json").write_text(
        json.dumps({"metrics": metrics, "failures": failures}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    smoke_result = F2SmokeCaseResult(
        problem_id=case.problem_id,
        ok=not failures,
        observation_hash=final.observation.observation_hash,
        context_id=context.manifest.context_id,
        metrics=metrics,
        failures=tuple(failures),
    )
    review = ObservationReviewCase(
        problem_id=case.problem_id,
        observation=final.observation,
        context=context,
        page_images=page_bytes,
    )
    return smoke_result, review


def _page_bytes(case: GoldCorpusCase) -> dict[str, bytes]:
    repo_root = Path(__file__).resolve().parents[4]
    return {
        page.page_id: (repo_root / page.asset_path).read_bytes()
        for page in case.manifest.pages
    }


def _selection_crop(
    seed: F0ExtractionContextSeed,
    page_id: str,
    content: bytes,
) -> tuple[bytes, tuple[int, int, int, int]]:
    image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
    regions = [item for item in seed.selection.regions if item.page_id == page_id]
    if not regions:
        raise RuntimeError(f"selection has no region for {page_id}")
    left = max(0, int(min(x for item in regions for x, _ in item.polygon) * image.width))
    top = max(0, int(min(y for item in regions for _, y in item.polygon) * image.height))
    right = min(image.width, max(left + 1, round(max(x for item in regions for x, _ in item.polygon) * image.width)))
    bottom = min(image.height, max(top + 1, round(max(y for item in regions for _, y in item.polygon) * image.height)))
    crop = image.crop((left, top, right, bottom))
    mask = Image.new("L", crop.size, 0)
    draw = ImageDraw.Draw(mask)
    for region in regions:
        draw.polygon(
            [
                (round(x * image.width - left), round(y * image.height - top))
                for x, y in region.polygon
            ],
            fill=255,
        )
    crop.paste(Image.new("RGB", crop.size, "white"), mask=mask.point(lambda value: 255 - value))
    buffer = BytesIO()
    crop.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue(), (left, top, right, bottom)


def _remap_text_run(
    run: PaddleProviderRun,
    *,
    page_width: int,
    page_height: int,
    left: int,
    top: int,
) -> PaddleProviderRun:
    items = []
    for item in run.record.items:
        payload = dict(item)
        payload["polygon"] = [
            [float(point[0]) + left, float(point[1]) + top]
            for point in item["polygon"]
        ]
        items.append(payload)
    record = PaddleProviderRecord.create(
        component="text_ocr",
        provider=run.record.provider,
        source_revision_hash=run.record.source_revision_hash,
        page_id=run.record.page_id,
        width=page_width,
        height=page_height,
        items=items,
        latency_ms=run.record.latency_ms,
    )
    return PaddleProviderRun(record, run.raw_payloads)


def _validate_selection_scoped_text_runs(
    seed: F0ExtractionContextSeed,
    runs: Sequence[PaddleProviderRun],
) -> None:
    regions_by_page = {
        page.page_id: tuple(
            region
            for region in seed.selection.regions
            if region.page_id == page.page_id
        )
        for page in seed.source.pages
    }
    for run in runs:
        record = run.record
        if record.component != "text_ocr":
            continue
        regions = regions_by_page.get(record.page_id, ())
        for index, item in enumerate(record.items):
            polygon = item.get("polygon")
            if not isinstance(polygon, Sequence) or not polygon:
                raise RuntimeError(
                    f"text OCR item has no polygon: {record.page_id}[{index}]"
                )
            points = tuple(
                (float(point[0]) / record.width, float(point[1]) / record.height)
                for point in polygon
            )
            center = (
                (min(x for x, _ in points) + max(x for x, _ in points)) / 2,
                (min(y for _, y in points) + max(y for _, y in points)) / 2,
            )
            if not any(_point_in_polygon(center, region.polygon) for region in regions):
                raise RuntimeError(
                    "text OCR observation falls outside the confirmed selection: "
                    f"{record.page_id}[{index}]"
                )


def _store_raw_runs(
    store: ExtractionArtifactStore,
    runs: Sequence[PaddleProviderRun],
) -> tuple[Any, ...]:
    return tuple(
        store.put_json(
            kind=f"provider_raw_{run.record.component}",
            payload={
                "page_id": run.record.page_id,
                "component": run.record.component,
                "results": list(run.raw_payloads),
            },
        )
        for run in runs
    )


def _write_provider_records(
    problem_id: str,
    output_dir: Path,
    runs: Sequence[PaddleProviderRun],
) -> None:
    target = output_dir / problem_id / "provider-records"
    target.mkdir(parents=True, exist_ok=True)
    for run in runs:
        path = target / f"{run.record.page_id}-{run.record.component}.json"
        path.write_text(
            json.dumps(run.record.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raw_path = target / f"{run.record.page_id}-{run.record.component}.raw.json"
        raw_path.write_text(
            json.dumps(
                {"raw_payloads": list(run.raw_payloads)},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _load_provider_runs(root: Path, problem_id: str) -> tuple[PaddleProviderRun, ...]:
    record_dir = root / problem_id / "provider-records"
    paths = tuple(
        path
        for path in sorted(record_dir.glob("*.json"))
        if not path.name.endswith(".raw.json")
    )
    if not paths:
        raise FileNotFoundError(f"no provider records found in {record_dir}")
    runs = []
    for path in paths:
        raw_path = path.with_name(f"{path.stem}.raw.json")
        raw_payloads: tuple[Any, ...] = ()
        if raw_path.exists():
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_values = raw_payload.get("raw_payloads", [])
            if not isinstance(raw_values, list):
                raise ValueError(f"raw provider payloads must be an array: {raw_path}")
            raw_payloads = tuple(raw_values)
        runs.append(
            PaddleProviderRun(
                PaddleProviderRecord.from_payload(
                    json.loads(path.read_text(encoding="utf-8"))
                ),
                raw_payloads,
            )
        )
    return tuple(runs)


def _provider_manifests_from_runs(
    runs: Sequence[PaddleProviderRun],
) -> tuple[Any, ...]:
    manifests = {}
    for run in runs:
        manifest = run.record.provider
        previous = manifests.get(manifest.provider_id)
        if previous is not None and previous.to_payload() != manifest.to_payload():
            raise RuntimeError("provider id was reused with different manifests")
        manifests[manifest.provider_id] = manifest
    components = {item.component for item in manifests.values()}
    if components != {"layout", "text_ocr", "formula_ocr"}:
        raise RuntimeError(f"recorded provider components are incomplete: {sorted(components)}")
    return tuple(sorted(manifests.values(), key=lambda item: item.provider_id))


def _provider_ledger(
    seed: F0ExtractionContextSeed,
    result: F2ObservationAssemblyResult,
) -> ExtractionAttemptLedger:
    provider_outputs = tuple(
        item
        for item in result.artifacts
        if item.kind
        in {"provider_layout", "provider_text_ocr", "provider_formula_ocr"}
    )
    inputs = tuple(
        item
        for item in result.artifacts
        if item.kind in {"canonical_source_page", "selection_crop", "formula_crop"}
    )
    latency_ms = sum(
        item.latency_ms
        for item in _provider_records_from_artifacts(result.artifacts)
    )
    provider_attempt = ExtractionAttemptRecord(
        attempt_id=f"attempt:f2:paddle:{seed.source.source_revision_hash}",
        base_context_id=seed.context.manifest.context_id,
        provider="paddle_local_cpu",
        route="pending",
        input_artifact_refs=inputs,
        output_artifact_refs=provider_outputs,
        result="succeeded",
        usage={"provider_record_count": len(provider_outputs)},
        latency_ms=latency_ms,
    )
    ledger = ExtractionAttemptLedger(seed.context.manifest.context_id).append(
        seed.context,
        provider_attempt,
    )
    masks = tuple(
        item for item in result.artifacts if item.kind == "handwriting_mask"
    )
    if not masks:
        return ledger
    ink_inputs = tuple(
        item
        for item in result.artifacts
        if item.kind in {"canonical_source_page", "provider_text_ocr"}
    )
    ink_attempt = ExtractionAttemptRecord(
        attempt_id=f"attempt:f2:ink:{seed.source.source_revision_hash}",
        base_context_id=seed.context.manifest.context_id,
        provider="local_cv",
        route="pending",
        input_artifact_refs=ink_inputs,
        output_artifact_refs=masks,
        result="succeeded",
        usage={"page_count": len(masks)},
        latency_ms=0,
    )
    return ledger.append(seed.context, ink_attempt)


def _provider_records_from_artifacts(artifacts: Sequence[Any]) -> tuple[PaddleProviderRecord, ...]:
    records = []
    for artifact in artifacts:
        if artifact.kind not in {"provider_layout", "provider_text_ocr", "provider_formula_ocr"}:
            continue
        payload = json.loads(Path(artifact.locator).read_text(encoding="utf-8"))
        records.append(PaddleProviderRecord.from_payload(payload))
    return tuple(records)


def evaluate_f2_acceptance(
    case: GoldCorpusCase,
    observation: SourceObservation,
    deterministic_replay: bool,
) -> tuple[dict[str, Any], list[str]]:
    evidence_by_id = {item.evidence_id: item for item in case.annotation.evidence}
    printed_evidence = tuple(
        item
        for item in case.annotation.evidence
        if item.purpose == "problem_source" and item.origin in {"printed", "mixed"}
    )
    recognized = observation.text_spans + observation.formulas
    uncovered = [
        item.evidence_id
        for item in printed_evidence
        if not any(
            candidate.page_id == item.page_id
            and _center_in_polygon(candidate.polygon, item.polygon)
            for candidate in recognized
        )
    ]
    handwritten_as_printed = [
        item.evidence_id
        for item in case.annotation.evidence
        if item.origin == "handwritten"
        and any(
            candidate.page_id == item.page_id
            and candidate.origin == "printed"
            and _center_in_polygon(candidate.polygon, item.polygon)
            for candidate in recognized
        )
    ]
    expected_lines = _expected_lines(case)
    student_only_regions = tuple(
        item
        for item in case.annotation.evidence
        if item.purpose == "student_work"
        and not any(
            source.page_id == item.page_id
            and _positive_bbox_overlap(source.polygon, item.polygon)
            for source in printed_evidence
        )
    )
    missing_lines = []
    line_evidence = case.annotation.semantic_evidence.get("original_text_lines", {})
    for index, expected in enumerate(expected_lines):
        ids = line_evidence.get(str(index), ())
        regions = [evidence_by_id[item] for item in ids if item in evidence_by_id]
        spans = sorted(
            (
                span
                for span in observation.text_spans
                if _is_ocr_quality_span(span, student_only_regions)
                if any(
                    span.page_id == region.page_id
                    and _center_in_polygon(span.polygon, region.polygon)
                    for region in regions
                )
            ),
            key=lambda item: (item.page_id, item.reading_order, item.observation_id),
        )
        if not spans:
            missing_lines.append(index)
    expected_normalized = "".join(_ocr_normalize(item) for item in expected_lines)
    actual_normalized = "".join(
        _ocr_normalize(item.text)
        for item in sorted(
            (
                span
                for span in observation.text_spans
                if span.observation_id in observation.selected_observation_ids
                and _is_ocr_quality_span(span, student_only_regions)
            ),
            key=lambda item: (item.page_id, item.reading_order, item.observation_id),
        )
    )
    cer = _edit_distance(expected_normalized, actual_normalized) / max(1, len(expected_normalized))

    target_proposals = [
        item for item in observation.proposals if item.question_label == case.annotation.question_label
    ]
    proposal_incomplete = not target_proposals or any(
        not any(
            evidence.page_id == page_id
            and _center_in_polygon(evidence.polygon, polygon)
            for page_id, polygon in zip(proposal.page_ids, proposal.polygons, strict=False)
        )
        for evidence in printed_evidence
        for proposal in target_proposals[:1]
    )
    proposal_overlaps_excluded = any(
        proposal_page == excluded.page_id and _positive_bbox_overlap(proposal_polygon, excluded.polygon)
        for proposal in target_proposals
        for proposal_page, proposal_polygon in zip(proposal.page_ids, proposal.polygons, strict=False)
        for excluded in case.annotation.excluded_regions
    )
    issue_codes = {item.code for item in observation.issues}
    formula_issues = tuple(
        item
        for item in observation.issues
        if item.code == "extraction.formula_observation_unresolved"
    )
    unresolved_formula_without_issue = [
        item.observation_id
        for item in observation.formulas
        if item.status == "unresolved"
        and not any(
            set(item.source_observation_ids).intersection(issue.observation_ids)
            for issue in formula_issues
        )
    ]
    formula_observed = (
        any(item.status == "recognized" for item in observation.formulas)
        or bool(formula_issues)
    )
    xiqing_overlap_ok = True
    if case.problem_id == "tj-2026-xiqing-yimo-25":
        xiqing_overlap_ok = (
            any(item.origin in {"mixed", "unknown"} for item in observation.ink_origins)
            and bool(observation.occlusions)
        )
    metrics = {
        "normalized_ocr_cer": round(cer, 6),
        "expected_character_count": len(expected_normalized),
        "actual_character_count": len(actual_normalized),
        "missing_original_text_lines": missing_lines,
        "uncovered_printed_evidence_ids": uncovered,
        "handwritten_evidence_marked_printed": handwritten_as_printed,
        "target_proposal_found": bool(target_proposals),
        "target_proposal_incomplete": proposal_incomplete,
        "target_proposal_overlaps_excluded": proposal_overlaps_excluded,
        "formula_observed_or_typed_issue": formula_observed,
        "unresolved_formula_without_typed_issue": unresolved_formula_without_issue,
        "xiqing_overlap_evidence": xiqing_overlap_ok,
        "deterministic_recorded_replay": deterministic_replay,
        "text_span_count": len(observation.text_spans),
        "formula_count": len(observation.formulas),
        "ink_origin_count": len(observation.ink_origins),
        "occlusion_count": len(observation.occlusions),
        "issue_count": len(observation.issues),
    }
    failures = []
    if cer > 0.20:
        failures.append("normalized_ocr_cer_exceeded")
    if missing_lines:
        failures.append("original_text_line_missing")
    if uncovered:
        failures.append("gold_printed_evidence_uncovered")
    if handwritten_as_printed:
        failures.append("handwritten_evidence_promoted_to_printed")
    if not target_proposals or proposal_incomplete:
        failures.append("target_proposal_incomplete")
    if proposal_overlaps_excluded:
        failures.append("target_proposal_overlaps_excluded")
    if not formula_observed:
        failures.append("formula_observation_missing_without_issue")
    if unresolved_formula_without_issue:
        failures.append("unresolved_formula_missing_typed_issue")
    if not xiqing_overlap_ok:
        failures.append("xiqing_overlap_evidence_missing")
    if not deterministic_replay:
        failures.append("recorded_replay_drift")
    return metrics, failures


def _expected_lines(case: GoldCorpusCase) -> tuple[str, ...]:
    evidence_by_id = {
        evidence.evidence_id: evidence
        for evidence in case.annotation.evidence
    }
    authored_lines: list[str] = []
    line_evidence = case.annotation.semantic_evidence.get("original_text_lines", {})
    for line_id in sorted(line_evidence, key=lambda value: int(value)):
        referenced = [evidence_by_id[evidence_id] for evidence_id in line_evidence[line_id]]
        if not referenced or any(evidence.transcript is None for evidence in referenced):
            authored_lines = []
            break
        authored_lines.append("".join(evidence.transcript or "" for evidence in referenced))
    if authored_lines:
        return tuple(authored_lines)

    repo_root = Path(__file__).resolve().parents[4]
    payload = json.loads((repo_root / case.manifest.problem_fixture).read_text(encoding="utf-8"))
    return tuple(str(item) for item in payload["input"]["original_text"]["lines"])


def _ocr_normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return "".join(character for character in normalized if character.isalnum())


def _is_ocr_quality_span(span: object, student_only_regions: Sequence[object]) -> bool:
    if str(getattr(span, "origin")) == "handwritten":
        return False
    text = str(getattr(span, "text"))
    if str(getattr(span, "origin")) == "unknown" and len(_ocr_normalize(text)) <= 2:
        return False
    if re.search(r"第\s*\d+\s*页|共\s*\d+\s*页|作业帮?", text) is not None:
        return False
    return not any(
        getattr(span, "page_id") == getattr(region, "page_id")
        and _center_in_polygon(getattr(span, "polygon"), getattr(region, "polygon"))
        for region in student_only_regions
    )


def _edit_distance(first: str, second: str) -> int:
    previous = list(range(len(second) + 1))
    for row, left in enumerate(first, start=1):
        current = [row]
        for column, right in enumerate(second, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def _center_in_polygon(subject: Polygon, container: Polygon) -> bool:
    xs = [point[0] for point in subject]
    ys = [point[1] for point in subject]
    return _point_in_polygon(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2), container)


def _point_in_polygon(point: tuple[float, float], polygon: Polygon) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x <= crossing:
                inside = not inside
    return inside


def _positive_bbox_overlap(first: Polygon, second: Polygon) -> bool:
    first_x = [item[0] for item in first]
    first_y = [item[1] for item in first]
    second_x = [item[0] for item in second]
    second_y = [item[1] for item in second]
    return (
        min(max(first_x), max(second_x)) > max(min(first_x), min(second_x))
        and min(max(first_y), max(second_y)) > max(min(first_y), min(second_y))
    )


if __name__ == "__main__":
    raise SystemExit(main())
