"""Read-only loader and auditor for the problem extraction gold corpus."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
import json
import mimetypes
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.semantic_diff import (
    compare_problem_semantics,
)


_SOURCE_SCHEMA_VERSION = "problem-extraction-source/v1"
_GOLD_SCHEMA_VERSION = "problem-extraction-gold/v1"
_F0_ANCHOR_PROBLEM_IDS = frozenset(
    {
        "tj-2026-heping-ermo-25",
        "tj-2026-heping-yimo-25",
        "tj-2026-hexi-yimo-25",
        "tj-2026-nankai-yimo-25",
        "tj-2026-xiqing-yimo-25",
    }
)
_ALLOWED_ORIGINS = frozenset({"printed", "handwritten", "mixed", "unknown"})
_ALLOWED_EVIDENCE_KINDS = frozenset(
    {
        "figure",
        "formula",
        "handwriting",
        "handwriting_and_auxiliary_figure",
        "mixed",
        "mixed_text_formula",
        "occlusion",
        "text",
        "text_formula",
        "unknown",
    }
)
_ALLOWED_PURPOSES = frozenset(
    {"problem_source", "student_work", "selection_context"}
)
_ALLOWED_EXCLUSION_SUBJECT_KINDS = frozenset(
    {"neighbor_question", "header", "footer", "watermark", "other"}
)
_REQUIRED_COVERAGE_KEYS = frozenset(
    {
        "column_layout",
        "cross_page_target",
        "expected_route",
        "handwriting",
        "neighbor_question_count",
        "printed_figure_in_target",
        "source_form",
        "zero_llm_expected",
    }
)
_REQUIRED_COVERAGE = (
    (
        "deterministic_complete_anchor",
        "缺少不调用LLM即可完整解析的真实题目图片",
        "提供一张无印刷图形、无笔迹、单页且题干文法明确的题目图片",
    ),
    (
        "printed_figure_in_target",
        "缺少第25题自身包含印刷图形的图片",
        "提供一张题干必须结合印刷几何图或函数图才能理解的题目图片",
    ),
    (
        "cross_page_target",
        "缺少跨页题目",
        "提供一道题干或配图跨两页的原始图片",
    ),
    (
        "unrecoverable_occlusion",
        "缺少关键印刷内容被学生笔迹完全遮挡的失败样本",
        "提供一张关键数字或公式不可恢复的带笔迹图片，预期fail closed",
    ),
)


class GoldCorpusError(ValueError):
    """Raised when the corpus cannot be loaded as structured data."""


@dataclass(frozen=True)
class SourcePage:
    page_id: str
    asset_path: str
    media_type: str
    sha256: str
    width: int
    height: int
    orientation_degrees: int


@dataclass(frozen=True)
class SourceManifest:
    schema_version: str
    problem_id: str
    problem_fixture: str
    pages: tuple[SourcePage, ...]
    path: Path


@dataclass(frozen=True)
class Region:
    region_id: str
    page_id: str
    polygon: tuple[tuple[float, float], ...]
    reason: str = ""
    subject_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExclusionSubject:
    subject_id: str
    kind: str
    label: str


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    page_id: str
    kind: str
    origin: str
    purpose: str
    polygon: tuple[tuple[float, float], ...]
    transcript: str | None = None


@dataclass(frozen=True)
class GoldAnnotation:
    schema_version: str
    problem_id: str
    question_label: str
    selection_source: str
    selection_regions: tuple[Region, ...]
    excluded_subjects: tuple[ExclusionSubject, ...]
    excluded_regions: tuple[Region, ...]
    evidence: tuple[Evidence, ...]
    semantic_evidence: Mapping[str, Mapping[str, tuple[str, ...]]]
    coverage: Mapping[str, Any]
    path: Path


@dataclass(frozen=True)
class GoldCorpusCase:
    manifest: SourceManifest
    annotation: GoldAnnotation

    @property
    def problem_id(self) -> str:
        return self.manifest.problem_id


@dataclass(frozen=True)
class GoldCorpus:
    root: Path
    cases: tuple[GoldCorpusCase, ...]


@dataclass(frozen=True)
class GoldCorpusIssue:
    code: str
    problem_id: str
    path: str
    message: str

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "problem_id": self.problem_id,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class CoverageGap:
    code: str
    description: str
    requested_input: str

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "description": self.description,
            "requested_input": self.requested_input,
        }


@dataclass(frozen=True)
class GoldCorpusAuditReport:
    ok: bool
    case_count: int
    issues: tuple[GoldCorpusIssue, ...]
    coverage: Mapping[str, tuple[str, ...]]
    coverage_gaps: tuple[CoverageGap, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "case_count": self.case_count,
            "issues": [item.to_payload() for item in self.issues],
            "coverage": {
                key: list(value) for key, value in sorted(self.coverage.items())
            },
            "coverage_gaps": [item.to_payload() for item in self.coverage_gaps],
        }

    def to_text(self) -> str:
        lines = [f"gold corpus: {self.case_count} cases, ok={self.ok}"]
        for issue in self.issues:
            lines.append(
                f"ERROR {issue.code} {issue.problem_id} {issue.path}: {issue.message}"
            )
        for gap in self.coverage_gaps:
            lines.append(f"GAP {gap.code}: {gap.requested_input}")
        return "\n".join(lines)


def load_gold_corpus(root: str | Path | None = None) -> GoldCorpus:
    repo_root = _repo_root()
    source_root = (
        Path(root).resolve()
        if root is not None
        else repo_root / "internal" / "source-images"
    )
    cases: list[GoldCorpusCase] = []
    for manifest_path in sorted(source_root.glob("*/source-manifest.json")):
        annotation_path = manifest_path.with_name("gold-annotation.json")
        if not annotation_path.exists():
            raise GoldCorpusError(
                f"missing gold annotation for source manifest: {manifest_path}"
            )
        manifest = _load_source_manifest(manifest_path)
        annotation = _load_gold_annotation(annotation_path)
        cases.append(GoldCorpusCase(manifest=manifest, annotation=annotation))
    return GoldCorpus(root=source_root, cases=tuple(cases))


def audit_gold_corpus(corpus: GoldCorpus) -> GoldCorpusAuditReport:
    issues: list[GoldCorpusIssue] = []
    coverage: dict[str, list[str]] = {}
    seen_problem_ids: set[str] = set()
    if not corpus.cases:
        _issue(
            issues,
            "gold.corpus_empty",
            "",
            "$",
            "the F0 gold corpus contains no cases",
        )
    for case in corpus.cases:
        problem_id = case.problem_id
        if problem_id in seen_problem_ids:
            _issue(
                issues,
                "gold.duplicate_problem_id",
                problem_id,
                "$.problem_id",
                "problem id occurs more than once",
            )
        seen_problem_ids.add(problem_id)
        _audit_case(case, issues)
        for key, value in sorted(case.annotation.coverage.items()):
            token = f"declared.{key}={_coverage_token(value)}"
            coverage.setdefault(token, []).append(problem_id)
        for key, value in sorted(_grounded_coverage(case).items()):
            token = f"grounded.{key}={_coverage_token(value)}"
            coverage.setdefault(token, []).append(problem_id)
    for missing_problem_id in sorted(_F0_ANCHOR_PROBLEM_IDS - seen_problem_ids):
        _issue(
            issues,
            "gold.anchor_case_missing",
            missing_problem_id,
            "$.problem_id",
            "required F0 anchor case is absent",
        )
    coverage_payload = {
        key: tuple(sorted(problem_ids)) for key, problem_ids in coverage.items()
    }
    gaps = _coverage_gaps(corpus)
    ordered_issues = tuple(
        sorted(issues, key=lambda item: (item.problem_id, item.code, item.path))
    )
    return GoldCorpusAuditReport(
        ok=not ordered_issues,
        case_count=len(corpus.cases),
        issues=ordered_issues,
        coverage=coverage_payload,
        coverage_gaps=gaps,
    )


def render_gold_overlays(corpus: GoldCorpus, output_dir: str | Path) -> tuple[Path, ...]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    colors = {
        "printed": (34, 105, 255, 255),
        "handwritten": (255, 128, 0, 255),
        "mixed": (150, 64, 200, 255),
        "unknown": (90, 90, 90, 255),
    }
    for case in corpus.cases:
        pages = {page.page_id: page for page in case.manifest.pages}
        for page_id, page in pages.items():
            source_path = _resolve_repo_path(page.asset_path)
            with Image.open(source_path) as source:
                canvas = source.convert("RGBA")
                draw = ImageDraw.Draw(canvas, "RGBA")
                for region in case.annotation.excluded_regions:
                    if region.page_id == page_id:
                        _draw_polygon(
                            draw,
                            region.polygon,
                            canvas.size,
                            (220, 30, 30, 255),
                            6,
                        )
                for region in case.annotation.selection_regions:
                    if region.page_id == page_id:
                        _draw_polygon(
                            draw,
                            region.polygon,
                            canvas.size,
                            (30, 180, 80, 255),
                            8,
                        )
                for evidence in case.annotation.evidence:
                    if evidence.page_id == page_id:
                        _draw_polygon(
                            draw,
                            evidence.polygon,
                            canvas.size,
                            colors[evidence.origin],
                            4,
                        )
                target = destination / f"{case.problem_id}-{page_id}.png"
                canvas.convert("RGB").save(target, format="PNG")
                rendered.append(target)
    return tuple(rendered)


def _load_source_manifest(path: Path) -> SourceManifest:
    payload = _load_json(path)
    _validate_schema(payload, "problem-extraction-source-manifest.schema.json", path)
    pages = tuple(
        SourcePage(
            page_id=_required_string(item, "page_id", path),
            asset_path=_required_string(item, "asset_path", path),
            media_type=_required_string(item, "media_type", path),
            sha256=_required_string(item, "sha256", path),
            width=int(item.get("width", 0)),
            height=int(item.get("height", 0)),
            orientation_degrees=int(item.get("orientation_degrees", 0)),
        )
        for item in _required_sequence(payload, "pages", path)
        if isinstance(item, Mapping)
    )
    return SourceManifest(
        schema_version=_required_string(payload, "schema_version", path),
        problem_id=_required_string(payload, "problem_id", path),
        problem_fixture=_required_string(payload, "problem_fixture", path),
        pages=pages,
        path=path,
    )


def _load_gold_annotation(path: Path) -> GoldAnnotation:
    payload = _load_json(path)
    _validate_schema(payload, "problem-extraction-gold-annotation.schema.json", path)
    selection = payload.get("selection")
    if not isinstance(selection, Mapping):
        raise GoldCorpusError(f"selection must be an object: {path}")
    semantic_raw = payload.get("semantic_evidence")
    if not isinstance(semantic_raw, Mapping):
        raise GoldCorpusError(f"semantic_evidence must be an object: {path}")
    semantic_evidence: dict[str, dict[str, tuple[str, ...]]] = {}
    for category, entries in semantic_raw.items():
        if not isinstance(entries, Mapping):
            raise GoldCorpusError(
                f"semantic_evidence.{category} must be an object: {path}"
            )
        semantic_evidence[str(category)] = {
            str(identity): tuple(str(ref) for ref in refs)
            for identity, refs in entries.items()
            if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes))
        }
    coverage = payload.get("coverage")
    if not isinstance(coverage, Mapping):
        raise GoldCorpusError(f"coverage must be an object: {path}")
    return GoldAnnotation(
        schema_version=_required_string(payload, "schema_version", path),
        problem_id=_required_string(payload, "problem_id", path),
        question_label=_required_string(payload, "question_label", path),
        selection_source=_required_string(selection, "source", path),
        selection_regions=tuple(
            _load_region(item, path)
            for item in _required_sequence(selection, "regions", path)
            if isinstance(item, Mapping)
        ),
        excluded_subjects=tuple(
            _load_exclusion_subject(item, path)
            for item in _required_sequence(payload, "excluded_subjects", path)
            if isinstance(item, Mapping)
        ),
        excluded_regions=tuple(
            _load_region(item, path, include_subject_ids=True)
            for item in payload.get("excluded_regions", [])
            if isinstance(item, Mapping)
        ),
        evidence=tuple(
            _load_evidence(item, path)
            for item in _required_sequence(payload, "evidence", path)
            if isinstance(item, Mapping)
        ),
        semantic_evidence=semantic_evidence,
        coverage=dict(coverage),
        path=path,
    )


def _load_region(
    payload: Mapping[str, Any],
    path: Path,
    *,
    include_subject_ids: bool = False,
) -> Region:
    return Region(
        region_id=_required_string(payload, "region_id", path),
        page_id=_required_string(payload, "page_id", path),
        polygon=_load_polygon(payload.get("polygon"), path),
        reason=str(payload.get("reason", "")),
        subject_ids=(
            tuple(
                str(item)
                for item in _required_sequence(payload, "subject_ids", path)
            )
            if include_subject_ids
            else ()
        ),
    )


def _load_exclusion_subject(
    payload: Mapping[str, Any],
    path: Path,
) -> ExclusionSubject:
    return ExclusionSubject(
        subject_id=_required_string(payload, "subject_id", path),
        kind=_required_string(payload, "kind", path),
        label=_required_string(payload, "label", path),
    )


def _load_evidence(payload: Mapping[str, Any], path: Path) -> Evidence:
    transcript = payload.get("transcript")
    return Evidence(
        evidence_id=_required_string(payload, "evidence_id", path),
        page_id=_required_string(payload, "page_id", path),
        kind=_required_string(payload, "kind", path),
        origin=_required_string(payload, "origin", path),
        purpose=_required_string(payload, "purpose", path),
        polygon=_load_polygon(payload.get("polygon"), path),
        transcript=str(transcript) if transcript is not None else None,
    )


def _load_polygon(value: Any, path: Path) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GoldCorpusError(f"polygon must be an array: {path}")
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, Sequence) or len(point) != 2:
            raise GoldCorpusError(f"polygon point must be [x,y]: {path}")
        points.append((float(point[0]), float(point[1])))
    return tuple(points)


def _audit_case(case: GoldCorpusCase, issues: list[GoldCorpusIssue]) -> None:
    manifest = case.manifest
    annotation = case.annotation
    problem_id = manifest.problem_id
    if manifest.path.parent.name != problem_id:
        _issue(
            issues,
            "gold.problem_directory_mismatch",
            problem_id,
            "$.problem_id",
            f"case directory is {manifest.path.parent.name!r}",
        )
    if manifest.schema_version != _SOURCE_SCHEMA_VERSION:
        _issue(
            issues,
            "gold.source_schema_invalid",
            problem_id,
            "$.schema_version",
            manifest.schema_version,
        )
    if annotation.schema_version != _GOLD_SCHEMA_VERSION:
        _issue(
            issues,
            "gold.annotation_schema_invalid",
            problem_id,
            "$.schema_version",
            annotation.schema_version,
        )
    if annotation.problem_id != problem_id:
        _issue(
            issues,
            "gold.problem_id_mismatch",
            problem_id,
            "$.problem_id",
            annotation.problem_id,
        )
    if annotation.selection_source != "authored_gold":
        _issue(
            issues,
            "gold.selection_source_invalid",
            problem_id,
            "$.selection.source",
            annotation.selection_source,
        )

    page_ids: set[str] = set()
    for index, page in enumerate(manifest.pages):
        path = f"$.pages[{index}]"
        if page.page_id in page_ids:
            _issue(issues, "gold.duplicate_page_id", problem_id, path, page.page_id)
        page_ids.add(page.page_id)
        _audit_page(page, problem_id, path, issues)
    if not manifest.pages:
        _issue(
            issues,
            "gold.pages_missing",
            problem_id,
            "$.pages",
            "at least one page is required",
        )

    fixture_path: Path | None = None
    fixture_payload: Mapping[str, Any] | None = None
    try:
        fixture_path = _resolve_repo_path(manifest.problem_fixture)
    except GoldCorpusError as exc:
        _issue(
            issues,
            "gold.problem_fixture_path_outside_repo",
            problem_id,
            "$.problem_fixture",
            str(exc),
        )
    if fixture_path is not None:
        if not fixture_path.exists():
            _issue(
                issues,
                "gold.problem_fixture_missing",
                problem_id,
                "$.problem_fixture",
                str(fixture_path),
            )
        else:
            try:
                candidate = _load_json(fixture_path)
            except GoldCorpusError as exc:
                _issue(
                    issues,
                    "gold.problem_fixture_invalid",
                    problem_id,
                    "$.problem_fixture",
                    str(exc),
                )
            else:
                fixture_payload = candidate.get("input", candidate)
                if not isinstance(fixture_payload, Mapping):
                    _issue(
                        issues,
                        "gold.problem_fixture_semantics_invalid",
                        problem_id,
                        "$.problem_fixture",
                        "canonical ProblemIR input must be an object",
                    )
                    fixture_payload = None
                else:
                    try:
                        compare_problem_semantics(fixture_payload, fixture_payload)
                    except ValueError as exc:
                        _issue(
                            issues,
                            "gold.problem_fixture_semantics_invalid",
                            problem_id,
                            "$.problem_fixture",
                            str(exc),
                        )
                        fixture_payload = None
                if (
                    fixture_payload is not None
                    and str(fixture_payload.get("problem_id", "")) != problem_id
                ):
                    _issue(
                        issues,
                        "gold.fixture_problem_id_mismatch",
                        problem_id,
                        "$.problem_fixture",
                        str(fixture_payload.get("problem_id")),
                    )

    for kind, regions in (
        ("selection", annotation.selection_regions),
        ("excluded", annotation.excluded_regions),
    ):
        region_ids: set[str] = set()
        for region in regions:
            if region.region_id in region_ids:
                _issue(
                    issues,
                    "gold.duplicate_region_id",
                    problem_id,
                    f"$.{kind}",
                    region.region_id,
                )
            region_ids.add(region.region_id)
            _audit_polygon(
                region.page_id,
                region.polygon,
                page_ids,
                problem_id,
                f"$.{kind}.{region.region_id}",
                issues,
            )
    exclusion_subjects: dict[str, ExclusionSubject] = {}
    for subject in annotation.excluded_subjects:
        path = f"$.excluded_subjects.{subject.subject_id}"
        if subject.subject_id in exclusion_subjects:
            _issue(
                issues,
                "gold.duplicate_exclusion_subject_id",
                problem_id,
                path,
                subject.subject_id,
            )
        exclusion_subjects[subject.subject_id] = subject
        if subject.kind not in _ALLOWED_EXCLUSION_SUBJECT_KINDS:
            _issue(
                issues,
                "gold.exclusion_subject_kind_invalid",
                problem_id,
                path,
                subject.kind,
            )
    referenced_exclusion_subjects: set[str] = set()
    for region in annotation.excluded_regions:
        path = f"$.excluded.{region.region_id}"
        if not region.subject_ids:
            _issue(
                issues,
                "gold.excluded_region_subject_missing",
                problem_id,
                path,
                "excluded region requires at least one subject reference",
            )
        for subject_id in region.subject_ids:
            referenced_exclusion_subjects.add(subject_id)
            if subject_id not in exclusion_subjects:
                _issue(
                    issues,
                    "gold.exclusion_subject_ref_unresolved",
                    problem_id,
                    path,
                    subject_id,
                )
    for subject_id in sorted(set(exclusion_subjects) - referenced_exclusion_subjects):
        _issue(
            issues,
            "gold.exclusion_subject_orphan",
            problem_id,
            f"$.excluded_subjects.{subject_id}",
            "exclusion subject is not referenced by any excluded region",
        )
    if not annotation.selection_regions:
        _issue(
            issues,
            "gold.selection_missing",
            problem_id,
            "$.selection",
            "selection requires at least one region",
        )

    for selected in annotation.selection_regions:
        for excluded in annotation.excluded_regions:
            overlaps_excluded = (
                selected.page_id == excluded.page_id
                and _polygons_overlap_with_area(
                    selected.polygon,
                    excluded.polygon,
                )
            )
            if overlaps_excluded:
                _issue(
                    issues,
                    "gold.selection_overlaps_excluded_region",
                    problem_id,
                    f"$.selection.{selected.region_id}",
                    f"overlaps {excluded.region_id}",
                )

    evidence_by_id: dict[str, Evidence] = {}
    for evidence in annotation.evidence:
        path = f"$.evidence.{evidence.evidence_id}"
        if evidence.evidence_id in evidence_by_id:
            _issue(
                issues,
                "gold.duplicate_evidence_id",
                problem_id,
                path,
                evidence.evidence_id,
            )
        evidence_by_id[evidence.evidence_id] = evidence
        _audit_polygon(evidence.page_id, evidence.polygon, page_ids, problem_id, path, issues)
        if evidence.origin not in _ALLOWED_ORIGINS:
            _issue(
                issues,
                "gold.evidence_origin_invalid",
                problem_id,
                path,
                evidence.origin,
            )
        if evidence.kind not in _ALLOWED_EVIDENCE_KINDS:
            _issue(
                issues,
                "gold.evidence_kind_invalid",
                problem_id,
                path,
                evidence.kind,
            )
        if evidence.purpose not in _ALLOWED_PURPOSES:
            _issue(
                issues,
                "gold.evidence_purpose_invalid",
                problem_id,
                path,
                evidence.purpose,
            )
        if evidence.purpose == "student_work" and evidence.origin == "printed":
            _issue(
                issues,
                "gold.student_work_marked_printed",
                problem_id,
                path,
                "student work cannot be printed evidence",
            )

    if fixture_payload is not None:
        expected_semantic_ids = _semantic_ids(fixture_payload)
        _audit_semantic_evidence(
            annotation,
            expected_semantic_ids,
            evidence_by_id,
            problem_id,
            issues,
        )
    referenced_evidence_ids = {
        ref
        for entries in annotation.semantic_evidence.values()
        for refs in entries.values()
        for ref in refs
    }
    for evidence in annotation.evidence:
        if (
            evidence.purpose == "problem_source"
            and evidence.evidence_id not in referenced_evidence_ids
        ):
            _issue(
                issues,
                "gold.problem_source_evidence_orphan",
                problem_id,
                f"$.evidence.{evidence.evidence_id}",
                "problem-source evidence is not referenced by semantic_evidence",
            )
    _audit_coverage(case, issues)


def _audit_page(
    page: SourcePage,
    problem_id: str,
    path: str,
    issues: list[GoldCorpusIssue],
) -> None:
    try:
        asset_path = _resolve_repo_path(page.asset_path)
    except GoldCorpusError as exc:
        _issue(
            issues,
            "gold.source_asset_path_outside_repo",
            problem_id,
            path,
            str(exc),
        )
        return
    if not asset_path.exists():
        _issue(issues, "gold.source_asset_missing", problem_id, path, str(asset_path))
        return
    digest = sha256(asset_path.read_bytes()).hexdigest()
    if digest != page.sha256:
        _issue(
            issues,
            "gold.source_sha_mismatch",
            problem_id,
            path,
            f"expected {page.sha256}, got {digest}",
        )
    guessed_media_type = mimetypes.guess_type(asset_path.name)[0]
    if guessed_media_type != page.media_type:
        _issue(
            issues,
            "gold.source_media_type_mismatch",
            problem_id,
            path,
            f"expected {page.media_type}, got {guessed_media_type}",
        )
    try:
        with Image.open(asset_path) as image:
            if image.size != (page.width, page.height):
                _issue(
                    issues,
                    "gold.source_dimensions_mismatch",
                    problem_id,
                    path,
                    f"expected {(page.width, page.height)}, got {image.size}",
                )
            actual_media_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
            }.get(image.format)
            if actual_media_type != page.media_type:
                _issue(
                    issues,
                    "gold.source_content_type_mismatch",
                    problem_id,
                    path,
                    f"expected {page.media_type}, got {actual_media_type}",
                )
            actual_orientation, mirrored = _image_orientation(image)
            if mirrored:
                _issue(
                    issues,
                    "gold.source_mirrored_orientation_unsupported",
                    problem_id,
                    path,
                    "mirrored EXIF orientation requires explicit source normalization",
                )
            elif actual_orientation is None:
                _issue(
                    issues,
                    "gold.source_orientation_unsupported",
                    problem_id,
                    path,
                    "unsupported EXIF orientation",
                )
            elif actual_orientation != page.orientation_degrees:
                _issue(
                    issues,
                    "gold.source_orientation_mismatch",
                    problem_id,
                    path,
                    f"expected {page.orientation_degrees}, got {actual_orientation}",
                )
    except OSError as exc:
        _issue(issues, "gold.source_image_unreadable", problem_id, path, str(exc))
    if page.orientation_degrees not in {0, 90, 180, 270}:
        _issue(
            issues,
            "gold.source_orientation_invalid",
            problem_id,
            path,
            str(page.orientation_degrees),
        )


def _audit_polygon(
    page_id: str,
    polygon: Sequence[tuple[float, float]],
    page_ids: set[str],
    problem_id: str,
    path: str,
    issues: list[GoldCorpusIssue],
) -> None:
    if page_id not in page_ids:
        _issue(issues, "gold.page_ref_unresolved", problem_id, path, page_id)
    if len(polygon) < 3:
        _issue(
            issues,
            "gold.polygon_invalid",
            problem_id,
            path,
            "polygon needs at least three points",
        )
        return
    if any(x < 0 or x > 1 or y < 0 or y > 1 for x, y in polygon):
        _issue(issues, "gold.polygon_out_of_bounds", problem_id, path, str(polygon))
    if abs(_polygon_area(polygon)) <= 1e-8:
        _issue(issues, "gold.polygon_zero_area", problem_id, path, str(polygon))


def _audit_semantic_evidence(
    annotation: GoldAnnotation,
    expected: Mapping[str, set[str]],
    evidence_by_id: Mapping[str, Evidence],
    problem_id: str,
    issues: list[GoldCorpusIssue],
) -> None:
    for category, expected_ids in expected.items():
        actual = annotation.semantic_evidence.get(category, {})
        for identity in sorted(expected_ids):
            refs = tuple(actual.get(identity, ()))
            if not refs:
                _issue(
                    issues,
                    "gold.semantic_evidence_missing",
                    problem_id,
                    f"$.semantic_evidence.{category}.{identity}",
                    "no evidence refs",
                )
            for ref in refs:
                evidence = evidence_by_id.get(ref)
                if evidence is None:
                    _issue(
                        issues,
                        "gold.evidence_ref_unresolved",
                        problem_id,
                        f"$.semantic_evidence.{category}.{identity}",
                        ref,
                    )
                    continue
                if evidence.origin == "handwritten" or evidence.purpose == "student_work":
                    _issue(
                        issues,
                        "gold.semantic_uses_handwriting",
                        problem_id,
                        f"$.semantic_evidence.{category}.{identity}",
                        ref,
                    )
                elif (
                    evidence.origin not in {"printed", "mixed"}
                    or evidence.purpose != "problem_source"
                ):
                    _issue(
                        issues,
                        "gold.semantic_evidence_origin_invalid",
                        problem_id,
                        f"$.semantic_evidence.{category}.{identity}",
                        ref,
                    )
                if not any(
                    region.page_id == evidence.page_id
                    and _polygon_contains(region.polygon, evidence.polygon)
                    for region in annotation.selection_regions
                ):
                    _issue(
                        issues,
                        "gold.semantic_evidence_outside_selection",
                        problem_id,
                        f"$.semantic_evidence.{category}.{identity}",
                        ref,
                    )
        for identity in sorted(set(actual) - expected_ids):
            _issue(
                issues,
                "gold.semantic_identity_unexpected",
                problem_id,
                f"$.semantic_evidence.{category}.{identity}",
                identity,
            )


def _semantic_ids(payload: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {
        "original_text_lines": {
            str(index)
            for index, _ in enumerate(
                (payload.get("original_text") or {}).get("lines", [])
                if isinstance(payload.get("original_text"), Mapping)
                else []
            )
        }
    }
    for category, key in (
        ("scopes", "scope_id"),
        ("entities", "handle"),
        ("facts", "handle"),
        ("question_goals", "handle"),
    ):
        result[category] = {
            str(item[key])
            for item in payload.get(category, [])
            if isinstance(item, Mapping) and item.get(key)
        }
    return result


def _coverage_gaps(corpus: GoldCorpus) -> tuple[CoverageGap, ...]:
    grounded = [_grounded_coverage(case) for case in corpus.cases]
    observed = {
        # Authored route labels cannot prove complete deterministic parsing.
        # F3 closes this gap with an executable parser coverage result.
        "deterministic_complete_anchor": False,
        "printed_figure_in_target": any(
            item["printed_figure_in_target"] is True for item in grounded
        ),
        "cross_page_target": any(
            item["cross_page_target"] is True for item in grounded
        ),
        "unrecoverable_occlusion": any(
            item["unrecoverable_occlusion"] is True for item in grounded
        ),
    }
    return tuple(
        CoverageGap(code=code, description=description, requested_input=requested)
        for code, description, requested in _REQUIRED_COVERAGE
        if not observed[code]
    )


def _grounded_coverage(case: GoldCorpusCase) -> dict[str, bool | int]:
    annotation = case.annotation
    printed_figure = any(
        evidence.kind == "figure"
        and evidence.origin in {"printed", "mixed"}
        and evidence.purpose == "problem_source"
        and _evidence_inside_selection(annotation, evidence)
        for evidence in annotation.evidence
    )
    mixed_problem_source = any(
        evidence.origin in {"mixed", "unknown"}
        and evidence.purpose == "problem_source"
        and _evidence_inside_selection(annotation, evidence)
        for evidence in annotation.evidence
    )
    student_work = any(
        evidence.origin in {"handwritten", "mixed"}
        and evidence.purpose == "student_work"
        and _evidence_inside_selection(annotation, evidence)
        for evidence in annotation.evidence
    )
    unrecoverable_occlusion = any(
        evidence.kind == "occlusion"
        and evidence.origin in {"mixed", "unknown"}
        and evidence.purpose == "problem_source"
        and _evidence_inside_selection(annotation, evidence)
        for evidence in annotation.evidence
    )
    selected_pages = {region.page_id for region in annotation.selection_regions}
    neighbor_question_count = len(
        {
            subject.subject_id
            for subject in annotation.excluded_subjects
            if subject.kind == "neighbor_question"
        }
    )
    return {
        "cross_page_target": len(selected_pages) > 1,
        "excluded_region_count": len(annotation.excluded_regions),
        "excluded_subject_count": len(annotation.excluded_subjects),
        "mixed_problem_source": mixed_problem_source,
        "multimodal_evidence": printed_figure or mixed_problem_source,
        "neighbor_question_count": neighbor_question_count,
        "printed_figure_in_target": printed_figure,
        "student_work": student_work,
        "unrecoverable_occlusion": unrecoverable_occlusion,
    }


def _evidence_inside_selection(
    annotation: GoldAnnotation,
    evidence: Evidence,
) -> bool:
    return any(
        region.page_id == evidence.page_id
        and _polygon_contains(region.polygon, evidence.polygon)
        for region in annotation.selection_regions
    )


def _audit_coverage(
    case: GoldCorpusCase,
    issues: list[GoldCorpusIssue],
) -> None:
    problem_id = case.problem_id
    coverage = case.annotation.coverage
    missing = sorted(_REQUIRED_COVERAGE_KEYS - set(coverage))
    for key in missing:
        _issue(
            issues,
            "gold.coverage_field_missing",
            problem_id,
            f"$.coverage.{key}",
            key,
        )
    if missing:
        return

    grounded = _grounded_coverage(case)
    if coverage["printed_figure_in_target"] is not grounded[
        "printed_figure_in_target"
    ]:
        _issue(
            issues,
            "gold.coverage_printed_figure_mismatch",
            problem_id,
            "$.coverage.printed_figure_in_target",
            "coverage claim does not match printed figure evidence",
        )
    if coverage["cross_page_target"] is not grounded["cross_page_target"]:
        _issue(
            issues,
            "gold.coverage_cross_page_mismatch",
            problem_id,
            "$.coverage.cross_page_target",
            "coverage claim does not match selected page count",
        )
    if coverage["neighbor_question_count"] != grounded["neighbor_question_count"]:
        _issue(
            issues,
            "gold.coverage_neighbor_count_mismatch",
            problem_id,
            "$.coverage.neighbor_question_count",
            "neighbor count does not match unique neighbor-question subjects",
        )

    handwriting = coverage["handwriting"]
    if handwriting == "none" and (
        grounded["student_work"] or grounded["mixed_problem_source"]
    ):
        _issue(
            issues,
            "gold.coverage_handwriting_mismatch",
            problem_id,
            "$.coverage.handwriting",
            "handwriting evidence exists",
        )
    elif handwriting == "non_overlapping" and (
        not grounded["student_work"] or grounded["mixed_problem_source"]
    ):
        _issue(
            issues,
            "gold.coverage_handwriting_mismatch",
            problem_id,
            "$.coverage.handwriting",
            "non-overlapping handwriting requires isolated student work evidence",
        )
    elif handwriting == "overlapping_recoverable" and (
        not grounded["student_work"] or not grounded["mixed_problem_source"]
    ):
        _issue(
            issues,
            "gold.coverage_handwriting_mismatch",
            problem_id,
            "$.coverage.handwriting",
            "overlap requires student work and mixed problem-source evidence",
        )
    elif handwriting == "occluding_unrecoverable" and not grounded[
        "unrecoverable_occlusion"
    ]:
        _issue(
            issues,
            "gold.coverage_handwriting_mismatch",
            problem_id,
            "$.coverage.handwriting",
            "unrecoverable coverage requires an occlusion evidence region",
        )

    route = coverage["expected_route"]
    zero_llm = coverage["zero_llm_expected"]
    if (route == "deterministic_complete") != (zero_llm is True):
        _issue(
            issues,
            "gold.coverage_zero_llm_route_mismatch",
            problem_id,
            "$.coverage.zero_llm_expected",
            "zero-LLM expectation must match deterministic_complete route",
        )
    if route == "deterministic_complete":
        _issue(
            issues,
            "gold.deterministic_route_unverified",
            problem_id,
            "$.coverage.expected_route",
            "F0 annotations cannot prove deterministic parser completeness",
        )
    elif route == "multimodal_required" and not grounded[
        "multimodal_evidence"
    ]:
        _issue(
            issues,
            "gold.coverage_multimodal_ungrounded",
            problem_id,
            "$.coverage.expected_route",
            "multimodal route lacks figure or mixed/unknown source evidence",
        )
    elif route == "text_semantic_required" and grounded["multimodal_evidence"]:
        _issue(
            issues,
            "gold.coverage_text_route_conflict",
            problem_id,
            "$.coverage.expected_route",
            "text route conflicts with figure or mixed/unknown source evidence",
        )


def _image_orientation(image: Image.Image) -> tuple[int | None, bool]:
    orientation = image.getexif().get(274, 1)
    return {
        1: (0, False),
        2: (0, True),
        3: (180, False),
        4: (180, True),
        5: (90, True),
        6: (90, False),
        7: (270, True),
        8: (270, False),
    }.get(orientation, (None, False))


def _polygon_area(polygon: Sequence[tuple[float, float]]) -> float:
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1])
    ) / 2


def _polygons_overlap_with_area(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
) -> bool:
    first_points = tuple(first)
    second_points = tuple(second)
    first_edges = tuple(zip(first_points, first_points[1:] + first_points[:1]))
    second_edges = tuple(zip(second_points, second_points[1:] + second_points[:1]))
    if any(
        _segments_properly_intersect(
            first_start,
            first_end,
            second_start,
            second_end,
        )
        for first_start, first_end in first_edges
        for second_start, second_end in second_edges
    ):
        return True
    if any(
        _point_strictly_in_polygon(point, second_points)
        for point in first_points
    ):
        return True
    if any(
        _point_strictly_in_polygon(point, first_points)
        for point in second_points
    ):
        return True
    return (
        abs(_polygon_area(first_points)) > 1e-8
        and abs(_polygon_area(second_points)) > 1e-8
        and all(
            _point_on_polygon_boundary(point, second_points)
            for point in first_points
        )
        and all(
            _point_on_polygon_boundary(point, first_points)
            for point in second_points
        )
    )


def _polygon_contains(
    container: Sequence[tuple[float, float]],
    candidate: Sequence[tuple[float, float]],
) -> bool:
    container_points = tuple(container)
    candidate_points = tuple(candidate)
    if not all(
        _point_in_polygon_or_boundary(point, container_points)
        for point in candidate_points
    ):
        return False

    container_edges = tuple(
        zip(container_points, container_points[1:] + container_points[:1])
    )
    candidate_edges = tuple(
        zip(candidate_points, candidate_points[1:] + candidate_points[:1])
    )
    for start, end in candidate_edges:
        midpoint = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        if not _point_in_polygon_or_boundary(midpoint, container_points):
            return False
        if any(
            _segments_properly_intersect(start, end, edge_start, edge_end)
            for edge_start, edge_end in container_edges
        ):
            return False
    return True


def _point_in_polygon_or_boundary(
    point: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
) -> bool:
    x, y = point
    points = tuple(polygon)
    inside = False
    for start, end in zip(points, points[1:] + points[:1]):
        if _point_on_segment(point, start, end):
            return True
        x1, y1 = start
        x2, y2 = end
        if (y1 > y) != (y2 > y):
            intersection_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < intersection_x:
                inside = not inside
    return inside


def _point_strictly_in_polygon(
    point: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
) -> bool:
    return _point_in_polygon_or_boundary(
        point,
        polygon,
    ) and not _point_on_polygon_boundary(point, polygon)


def _point_on_polygon_boundary(
    point: tuple[float, float],
    polygon: Sequence[tuple[float, float]],
) -> bool:
    points = tuple(polygon)
    return any(
        _point_on_segment(point, start, end)
        for start, end in zip(points, points[1:] + points[:1])
    )


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    epsilon = 1e-10
    cross = _orientation(start, end, point)
    if abs(cross) > epsilon:
        return False
    return (
        min(start[0], end[0]) - epsilon
        <= point[0]
        <= max(start[0], end[0]) + epsilon
        and min(start[1], end[1]) - epsilon
        <= point[1]
        <= max(start[1], end[1]) + epsilon
    )


def _segments_properly_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    epsilon = 1e-10
    orientations = (
        _orientation(first_start, first_end, second_start),
        _orientation(first_start, first_end, second_end),
        _orientation(second_start, second_end, first_start),
        _orientation(second_start, second_end, first_end),
    )
    if any(abs(value) <= epsilon for value in orientations):
        return False
    return (orientations[0] > 0) != (orientations[1] > 0) and (
        orientations[2] > 0
    ) != (orientations[3] > 0)


def _orientation(
    first: tuple[float, float],
    second: tuple[float, float],
    third: tuple[float, float],
) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (
        second[1] - first[1]
    ) * (third[0] - first[0])


def _draw_polygon(
    draw: ImageDraw.ImageDraw,
    polygon: Sequence[tuple[float, float]],
    size: tuple[int, int],
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    points = [(round(x * size[0]), round(y * size[1])) for x, y in polygon]
    draw.line(points + [points[0]], fill=color, width=width, joint="curve")


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldCorpusError(f"cannot load JSON {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise GoldCorpusError(f"JSON root must be an object: {path}")
    return payload


def _validate_schema(
    payload: Mapping[str, Any],
    schema_name: str,
    payload_path: Path,
) -> None:
    validator = _schema_validator(schema_name)
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    )
    raise GoldCorpusError(
        f"schema validation failed for {payload_path} at {location}: "
        f"{error.message}"
    )


@lru_cache(maxsize=None)
def _schema_validator(schema_name: str) -> Draft202012Validator:
    schema_path = _repo_root() / "internal" / "schemas" / schema_name
    schema = _load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _required_string(payload: Mapping[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GoldCorpusError(f"{key} must be a non-empty string: {path}")
    return value.strip()


def _required_sequence(
    payload: Mapping[str, Any], key: str, path: Path
) -> Sequence[Any]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GoldCorpusError(f"{key} must be an array: {path}")
    return value


def _coverage_token(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    repo_root = _repo_root().resolve()
    candidate = (path if path.is_absolute() else repo_root / path).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise GoldCorpusError(
            f"path escapes repository root: {value}"
        ) from exc
    return candidate


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _issue(
    issues: list[GoldCorpusIssue],
    code: str,
    problem_id: str,
    path: str,
    message: str,
) -> None:
    issues.append(
        GoldCorpusIssue(
            code=code,
            problem_id=problem_id,
            path=path,
            message=message,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--render-dir", type=Path)
    args = parser.parse_args(argv)
    corpus = load_gold_corpus(args.root)
    report = audit_gold_corpus(corpus)
    if args.render_dir:
        render_gold_overlays(corpus, args.render_dir)
    print(
        json.dumps(report.to_payload(), ensure_ascii=False, indent=2)
        if args.json
        else report.to_text()
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
