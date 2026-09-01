"""F5-F5B0 recorded/live lesson-authoring baseline harness.

This module is deliberately an offline audit tool.  It observes the existing
Snapshot -> LessonIR -> VisualStepIR -> page pipeline without changing any of
the production contracts or builders that the later F5-F5B phases will replace.
"""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
from time import perf_counter
from typing import Any, Callable, Literal, Mapping, Sequence
import unicodedata

from shuxueshuo_server.solver.explanation import (
    ExplanationBuilder,
    ExplanationSnapshot,
    ExplanationSnapshotBuilder,
    LLMLessonPlanner,
    LessonIR,
    LessonIRValidator,
)
from shuxueshuo_server.solver.explanation import builder as explanation_builder
from shuxueshuo_server.solver.explanation.llm import (
    ExplanationPrompt,
    build_lesson_planner_payload,
    render_lesson_prompt,
)
from shuxueshuo_server.solver.explanation.models import (
    iter_teaching_sources,
    teaching_source_owners,
)
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.scoped_functional_plan_smoke import (
    _build_planner_authority,
)
from shuxueshuo_server.solver.visual import (
    VisualStepBuilder,
    VisualStepIR,
    VisualStepIRValidator,
    forward_compile,
)
from shuxueshuo_server.solver.visual.compiler import CompiledVisualArtifacts


CASE_ID = "tj-2026-heping-ermo-25"
BASELINE_SOURCE_REVISION = "b42f0e2"
BASELINE_SCHEMA = "lesson-authoring-b0-baseline/v1"
RUBRIC_SCHEMA = "lesson-teaching-rubric/v1"
EVALUATION_SCHEMA = "lesson-teaching-evaluation/v1"
COVERAGE_SCHEMA = "lesson-teaching-spec-coverage/v1"
SAMPLE_RESULT_SCHEMA = "lesson-authoring-smoke-sample/v1"
BATCH_SUMMARY_SCHEMA = "lesson-authoring-smoke-summary/v1"
DEFAULT_OUTPUT_ROOT = (
    "internal/solver-runs/explanation-builder-deepseek-scope-vnext"
)
SmokeMode = Literal["recorded", "live"]


class LessonAuthoringSmokeError(ValueError):
    """The B0 audit input or generated artifact is inconsistent."""


@dataclass(frozen=True)
class RecordedLessonArtifacts:
    """Deterministic artifacts that form the checked-in B0 baseline."""

    lesson: LessonIR
    visual_ir: VisualStepIR
    compiled: CompiledVisualArtifacts


@dataclass(frozen=True)
class CurrentLessonPrompt:
    """The exact pre-vNext lesson prompt and the groups used to render it."""

    groups: tuple[Any, ...]
    payload: dict[str, Any]
    prompt: ExplanationPrompt


def load_teaching_rubric(path: str | Path) -> dict[str, Any]:
    """Load and strictly validate the smoke-only teaching rubric."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_teaching_rubric(payload)


def validate_teaching_rubric(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached rubric payload or fail on ambiguous matcher shape."""

    allowed_root = {"schema_version", "problem_id", "points"}
    if set(payload) != allowed_root:
        raise LessonAuthoringSmokeError(
            "lesson_teaching_rubric_invalid: root fields must be "
            f"{sorted(allowed_root)}"
        )
    if payload.get("schema_version") != RUBRIC_SCHEMA:
        raise LessonAuthoringSmokeError(
            "lesson_teaching_rubric_invalid: unsupported schema_version"
        )
    problem_id = str(payload.get("problem_id") or "")
    raw_points = payload.get("points")
    if not problem_id or not isinstance(raw_points, list) or not raw_points:
        raise LessonAuthoringSmokeError(
            "lesson_teaching_rubric_invalid: problem_id and points are required"
        )
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_point = {
        "point_id",
        "description",
        "source_step_id",
        "required_pattern_groups",
    }
    for index, raw in enumerate(raw_points):
        if not isinstance(raw, Mapping) or set(raw) != allowed_point:
            raise LessonAuthoringSmokeError(
                "lesson_teaching_rubric_invalid: "
                f"points[{index}] fields must be {sorted(allowed_point)}"
            )
        point_id = str(raw.get("point_id") or "")
        source_step_id = str(raw.get("source_step_id") or "")
        description = str(raw.get("description") or "")
        groups = raw.get("required_pattern_groups")
        if (
            not point_id
            or point_id in seen
            or not source_step_id
            or not description
            or not isinstance(groups, list)
            or not groups
        ):
            raise LessonAuthoringSmokeError(
                f"lesson_teaching_rubric_invalid: points[{index}] is incomplete"
            )
        normalized_groups: list[list[str]] = []
        for group_index, group in enumerate(groups):
            if (
                not isinstance(group, list)
                or not group
                or any(not isinstance(item, str) or not item.strip() for item in group)
            ):
                raise LessonAuthoringSmokeError(
                    "lesson_teaching_rubric_invalid: "
                    f"points[{index}].required_pattern_groups[{group_index}] "
                    "must contain non-empty alternatives"
                )
            normalized_groups.append([str(item) for item in group])
        seen.add(point_id)
        points.append(
            {
                "point_id": point_id,
                "description": description,
                "source_step_id": source_step_id,
                "required_pattern_groups": normalized_groups,
            }
        )
    return {
        "schema_version": RUBRIC_SCHEMA,
        "problem_id": problem_id,
        "points": points,
    }


def normalize_teaching_math_text(value: str) -> str:
    """Normalize presentation variants without attempting symbolic proof."""

    text = unicodedata.normalize("NFKC", str(value)).lower()
    for source, target in (
        ("−", "-"),
        ("–", "-"),
        ("—", "-"),
        ("′", "'"),
        ("’", "'"),
        ("‘", "'"),
        ("`", "'"),
        ("＝", "="),
        ("＋", "+"),
        ("（", "("),
        ("）", ")"),
        ("｜", "|"),
    ):
        text = text.replace(source, target)
    removable = " \t\r\n，,。；;：:、"
    return text.translate(str.maketrans("", "", removable))


def evaluate_lesson_teaching(
    lesson: LessonIR | Mapping[str, Any],
    rubric: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate smoke-only teaching-point coverage after Lesson generation."""

    rubric_payload = validate_teaching_rubric(rubric)
    lesson_payload = lesson.to_payload() if isinstance(lesson, LessonIR) else dict(lesson)
    if str(lesson_payload.get("problem_id") or "") != rubric_payload["problem_id"]:
        raise LessonAuthoringSmokeError(
            "lesson_teaching_evaluation_problem_mismatch: lesson and rubric differ"
        )
    raw_steps = lesson_payload.get("steps")
    if not isinstance(raw_steps, list):
        raise LessonAuthoringSmokeError(
            "lesson_teaching_evaluation_invalid: LessonIR.steps must be a list"
        )

    covered: list[str] = []
    missing: list[str] = []
    evidence_by_point: dict[str, Any] = {}
    for point in rubric_payload["points"]:
        source_step_id = point["source_step_id"]
        selected = [
            step
            for step in raw_steps
            if isinstance(step, Mapping)
            and source_step_id in tuple(step.get("source_step_ids") or ())
        ]
        combined = normalize_teaching_math_text(
            "\n".join(_lesson_step_student_text(step) for step in selected)
        )
        matched_groups: list[str | None] = []
        for alternatives in point["required_pattern_groups"]:
            matched_groups.append(
                next(
                    (
                        alternative
                        for alternative in alternatives
                        if normalize_teaching_math_text(alternative) in combined
                    ),
                    None,
                )
            )
        is_covered = bool(selected) and all(matched_groups)
        point_id = point["point_id"]
        (covered if is_covered else missing).append(point_id)
        evidence_by_point[point_id] = {
            "source_step_id": source_step_id,
            "lesson_step_ids": [str(step.get("id") or "") for step in selected],
            "matched_patterns": matched_groups,
        }
    total = len(rubric_payload["points"])
    return {
        "schema_version": EVALUATION_SCHEMA,
        "problem_id": rubric_payload["problem_id"],
        "covered": covered,
        "missing": missing,
        "evidence_by_point": evidence_by_point,
        "coverage_rate": round(len(covered) / total, 6),
    }


def _lesson_step_student_text(step: Mapping[str, Any]) -> str:
    values = [
        str(step.get("title") or ""),
        str(step.get("nav_title") or ""),
        str(step.get("goal") or ""),
    ]
    for item in step.get("derive") or ():
        if isinstance(item, Sequence) and not isinstance(item, str | bytes):
            values.extend(str(part) for part in item)
        else:
            values.append(str(item))
    values.extend(str(item) for item in step.get("box") or ())
    return "\n".join(values)


def current_lesson_prompt(snapshot: ExplanationSnapshot) -> CurrentLessonPrompt:
    """Render the unchanged pre-vNext Lesson prompt for B0 comparison."""

    groups = tuple(explanation_builder._build_lesson_groups(snapshot))
    payload = build_lesson_planner_payload(
        snapshot,
        groups,
        allow_same_problem_few_shot=False,
    )
    return CurrentLessonPrompt(
        groups=groups,
        payload=payload,
        prompt=render_lesson_prompt(payload),
    )


def build_recorded_lesson_artifacts(
    snapshot: ExplanationSnapshot,
) -> RecordedLessonArtifacts:
    """Build the current deterministic lesson and page IR from runtime truth."""

    lesson = ExplanationBuilder().build_lesson(snapshot)
    LessonIRValidator().validate(lesson, snapshot)
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir)
    return RecordedLessonArtifacts(
        lesson=lesson,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


def build_teaching_spec_coverage(
    snapshot: ExplanationSnapshot,
    *,
    lesson_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Inventory the capabilities actually executed by one verified Plan."""

    methods = MethodSpecRegistry.load_from_code().specs
    recipes = RecipeSpecRegistry.load_from_code().specs
    owners = teaching_source_owners(snapshot.root_scope)
    by_capability: dict[str, list[dict[str, Any]]] = {}
    for source in iter_teaching_sources(snapshot.root_scope):
        owner_scope, owner_goal = owners[source.source_step_id]
        source_evidence = snapshot.evidence_for_step(source.source_step_id)
        evidence_schemas = [
            str(item.get("schema_version") or "unknown")
            for item in source_evidence
        ]
        by_capability.setdefault(source.capability_id, []).append(
            {
                "step_id": source.source_step_id,
                "owner_scope_ref": owner_scope,
                "owner_goal_ref": owner_goal,
                "public_returns": list(source.public_results),
                "evidence_schemas": evidence_schemas,
            }
        )

    missing_by_source: dict[str, list[str]] = {}
    if lesson_evaluation is not None:
        details = lesson_evaluation.get("evidence_by_point") or {}
        for point_id in lesson_evaluation.get("missing") or ():
            detail = details.get(point_id) or {}
            source_step_id = str(detail.get("source_step_id") or "")
            if source_step_id:
                missing_by_source.setdefault(source_step_id, []).append(str(point_id))

    capabilities: list[dict[str, Any]] = []
    method_count = 0
    macro_count = 0
    for capability_id, occurrences in by_capability.items():
        method = methods.get(capability_id)
        recipe = recipes.get(capability_id)
        if (method is None) == (recipe is None):
            classification = "unknown" if method is None else "ambiguous"
            raise LessonAuthoringSmokeError(
                "lesson_teaching_coverage_capability_invalid: "
                f"{capability_id} classification={classification}"
            )
        is_macro = recipe is not None
        kind = "macro" if is_macro else "function"
        method_count += int(not is_macro)
        macro_count += int(is_macro)
        explanation = recipe.explanation if recipe is not None else method.explanation
        visual = recipe.visual if recipe is not None else method.visual
        all_evidence_schemas = list(
            dict.fromkeys(
                schema
                for occurrence in occurrences
                for schema in occurrence["evidence_schemas"]
            )
        )
        if not all_evidence_schemas:
            evidence_projection = "projector_not_required_for_current_execution"
        elif all(
            schema.startswith("path-minimum-prompt-witness/")
            for schema in all_evidence_schemas
        ):
            evidence_projection = "path_minimum_hardcoded_projector"
        else:
            evidence_projection = "projector_missing"

        recommended_splits = (
            tuple(recipe.explanation.recommended_lesson_splits)
            if recipe is not None and recipe.explanation is not None
            else ()
        )
        teaching_substeps = (
            tuple(recipe.explanation.teaching_substep_specs)
            if recipe is not None and recipe.explanation is not None
            else ()
        )
        explicit_unit_count = max(len(recommended_splits), len(teaching_substeps))
        unit_plan = (
            "explicit_units_required"
            if is_macro and explicit_unit_count > 1
            else "default_unit_candidate"
        )
        b1_actions = [unit_plan]
        gaps: list[str] = []
        if unit_plan == "explicit_units_required":
            gaps.append("explicit_teaching_units_missing")
        if all_evidence_schemas:
            b1_actions.append("evidence_projector_registry_required")
            if evidence_projection == "path_minimum_hardcoded_projector":
                gaps.append("evidence_projector_registry_missing")
            elif evidence_projection == "projector_missing":
                gaps.append("evidence_projector_missing")
        observed_gaps = list(
            dict.fromkeys(
                point_id
                for occurrence in occurrences
                for point_id in missing_by_source.get(occurrence["step_id"], ())
            )
        )
        capabilities.append(
            {
                "capability_id": capability_id,
                "kind": kind,
                "occurrences": occurrences,
                "current": {
                    "legacy_explanation_source": (
                        "explicit" if explanation is not None else "default"
                    ),
                    "legacy_visual_source": (
                        "explicit" if visual is not None else "missing"
                    ),
                    "evidence_projection": evidence_projection,
                    "evidence_schemas": all_evidence_schemas,
                },
                "vnext_b1": {
                    "teaching_unit_contract": "not_implemented_in_b0",
                    "recommended_unit_source": unit_plan,
                    "suggested_unit_count": explicit_unit_count or 1,
                    "actions": b1_actions,
                    "gaps": gaps,
                    "observed_teaching_point_gaps": observed_gaps,
                },
            }
        )

    return {
        "schema_version": COVERAGE_SCHEMA,
        "problem_id": snapshot.problem_id,
        "canonical_plan_hash": snapshot.canonical_plan_hash,
        "source_step_occurrence_count": sum(len(items) for items in by_capability.values()),
        "unique_capability_count": len(capabilities),
        "function_capability_count": method_count,
        "macro_capability_count": macro_count,
        "capabilities": capabilities,
    }


def build_baseline_manifest(
    snapshot: ExplanationSnapshot,
    *,
    current_prompt: CurrentLessonPrompt,
    recorded: RecordedLessonArtifacts,
    coverage: Mapping[str, Any],
    live_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the checked-in deterministic baseline manifest."""

    snapshot_payload = canonical_b0_snapshot_payload(snapshot.to_payload())
    macro_evidence = list(snapshot.macro_evidence)
    lesson_payload = recorded.lesson.to_payload()
    visual_payload = recorded.visual_ir.to_payload()
    compiled_payload = {
        "geometry_spec": recorded.compiled.geometry_spec,
        "step_decorations": recorded.compiled.step_decorations,
        "lesson_data": recorded.compiled.lesson_data,
    }
    prompt = current_prompt.prompt
    return {
        "schema_version": BASELINE_SCHEMA,
        "source_revision": BASELINE_SOURCE_REVISION,
        "problem_id": snapshot.problem_id,
        "contracts": {
            "snapshot": snapshot.schema_version,
            "rubric": RUBRIC_SCHEMA,
            "coverage": COVERAGE_SCHEMA,
        },
        "authority": {
            "canonical_plan_hash": snapshot.canonical_plan_hash,
            "observed_verified_execution_hash": snapshot.verified_execution_hash,
            "verified_execution_hash_golden_policy": (
                "record_only_not_compared_across_equivalent_recorded_runs"
            ),
        },
        "counts": {
            "canonical_source_steps": coverage["source_step_occurrence_count"],
            "unique_capabilities": coverage["unique_capability_count"],
            "function_capabilities": coverage["function_capability_count"],
            "macro_capabilities": coverage["macro_capability_count"],
            "macro_evidence": len(macro_evidence),
            "candidate_groups": len(current_prompt.groups),
            "deterministic_lesson_steps": len(recorded.lesson.steps),
            "visual_steps": len(recorded.visual_ir.steps),
            "nonempty_visual_scenes": sum(
                bool(item.scene) for item in recorded.visual_ir.steps
            ),
            "compiled_lesson_steps": len(
                recorded.compiled.lesson_data.get("steps") or ()
            ),
        },
        "prompt": {
            "allow_same_problem_few_shot": False,
            "few_shot_count": len(
                current_prompt.payload.get("explanation_few_shots") or ()
            ),
            "system_chars": len(prompt.system),
            "user_chars": len(prompt.user),
            "total_chars": len(prompt.system) + len(prompt.user),
            "prompt_hash": stable_hash(
                {"system": prompt.system, "user": prompt.user}
            ),
        },
        "artifact_hashes": {
            "snapshot": stable_hash(snapshot_payload),
            "macro_evidence": stable_hash(macro_evidence),
            "lesson_ir": stable_hash(lesson_payload),
            "visual_step_ir": stable_hash(visual_payload),
            "compiled": stable_hash(compiled_payload),
            "coverage": stable_hash(dict(coverage)),
        },
        "live_observation": dict(live_observation or {}),
    }


def canonical_b0_snapshot_payload(
    snapshot: ExplanationSnapshot | Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize the current run-local execution signature for golden diffing.

    The verified execution signature currently includes run-local state identity,
    while the Canonical Plan, public results, evidence and teaching tree are stable.
    B0 records the observed signature separately instead of pretending it is a
    deterministic semantic hash.
    """

    payload = (
        snapshot.to_payload()
        if isinstance(snapshot, ExplanationSnapshot)
        else copy.deepcopy(dict(snapshot))
    )
    payload["verified_execution_hash"] = "<run-local-verified-execution-signature>"
    return payload


class _AuditedClient:
    """Record every semantic LLM call without changing provider behavior."""

    def __init__(self, client: LLMPlannerClient, debug_dir: Path) -> None:
        self.client = client
        self.debug_dir = debug_dir
        self.records: list[dict[str, Any]] = []

    def complete(self, payload: dict[str, Any]) -> str:
        attempt = len(self.records) + 1
        started = perf_counter()
        raw_response = ""
        error: Exception | None = None
        try:
            raw_response = self.client.complete(payload)
            return raw_response
        except Exception as exc:
            error = exc
            raise
        finally:
            duration = perf_counter() - started
            messages = payload.get("messages") or ()
            usage = dict(getattr(self.client, "last_usage", None) or {})
            record = {
                "schema_version": "lesson-llm-attempt-metadata/v1",
                "semantic_attempt": attempt,
                "provider": getattr(self.client, "provider_name", None),
                "request_model": getattr(self.client, "model", None),
                "response_model": getattr(self.client, "last_response_model", None),
                "prompt_hash": stable_hash(messages),
                "usage": usage,
                "duration_seconds": round(duration, 6),
                "first_token_seconds": None,
                "first_token_unavailable_reason": (
                    "provider_client_uses_non_streaming_chat_completions"
                ),
                "provider_attempts": list(
                    getattr(self.client, "last_provider_attempts", ())
                ),
                "provider_reasoning": list(
                    getattr(self.client, "last_provider_reasoning", ())
                ),
                "raw_response_hash": (
                    stable_hash(raw_response) if raw_response else None
                ),
                "visible_response": bool(raw_response.strip()),
                "error": (
                    f"{error.__class__.__name__}: {error}"
                    if error is not None
                    else None
                ),
            }
            self.records.append(record)
            self._write_attempt_input(
                attempt,
                payload=payload,
                raw_response=raw_response,
                record=record,
            )

    def _write_attempt_input(
        self,
        attempt: int,
        *,
        payload: Mapping[str, Any],
        raw_response: str,
        record: Mapping[str, Any],
    ) -> None:
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"attempt-{attempt}"
        messages = payload.get("messages") or ()
        system = next(
            (
                str(item.get("content") or "")
                for item in messages
                if isinstance(item, Mapping) and item.get("role") == "system"
            ),
            "",
        )
        user = next(
            (
                str(item.get("content") or "")
                for item in messages
                if isinstance(item, Mapping) and item.get("role") == "user"
            ),
            "",
        )
        _write_text(self.debug_dir / f"{prefix}.prompt.system.txt", system)
        _write_text(self.debug_dir / f"{prefix}.prompt.user.txt", user)
        _write_text(self.debug_dir / f"{prefix}.raw-response.txt", raw_response)
        explanation_payload = payload.get("explanation_payload")
        if isinstance(explanation_payload, Mapping):
            _write_json(
                self.debug_dir / f"{prefix}.payload.explanation.json",
                explanation_payload,
            )
        _write_json(
            self.debug_dir / f"{prefix}.llm-metadata.json",
            record,
        )

    @property
    def usage(self) -> dict[str, int]:
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for record in self.records:
            usage = record.get("usage") or {}
            for key in totals:
                value = usage.get(key)
                if isinstance(value, int):
                    totals[key] += value
        return totals

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)


class _ObservedLessonPlanner:
    """Expose whether the existing builder accepted or fell back from LLM."""

    def __init__(self, delegate: LLMLessonPlanner) -> None:
        self.delegate = delegate
        self.returned_draft: dict[str, Any] | None = None
        self.error: Exception | None = None

    def plan_lesson(
        self,
        *,
        groups: tuple[Any, ...],
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        try:
            self.returned_draft = self.delegate.plan_lesson(
                groups=groups,
                snapshot=snapshot,
            )
            return self.returned_draft
        except Exception as exc:
            self.error = exc
            raise


def _llm_draft_was_accepted(
    observed: _ObservedLessonPlanner,
    *,
    lesson: LessonIR,
    groups: tuple[Any, ...],
    snapshot: ExplanationSnapshot,
) -> bool:
    if observed.returned_draft is None:
        return False
    try:
        candidate = explanation_builder._lesson_from_llm_draft(
            observed.returned_draft,
            groups,
            snapshot,
        )
        LessonIRValidator().validate(candidate, snapshot)
    except Exception:
        return False
    return candidate.to_payload() == lesson.to_payload()


def _write_snapshot_artifacts(
    sample_dir: Path,
    *,
    snapshot: ExplanationSnapshot,
) -> None:
    _write_json(sample_dir / "snapshot.json", snapshot.to_payload())
    _write_json(sample_dir / "macro-evidence.json", list(snapshot.macro_evidence))


def _write_prompt_artifacts(
    sample_dir: Path,
    *,
    prompt: ExplanationPrompt,
    payload: Mapping[str, Any],
) -> None:
    _write_json(sample_dir / "payload.explanation.json", payload)
    _write_text(sample_dir / "prompt.system.md", prompt.system)
    _write_text(sample_dir / "prompt.user.md", prompt.user)


def _write_compiled_page(
    sample_dir: Path,
    *,
    compiled: CompiledVisualArtifacts,
) -> Path:
    root = _repo_root()
    compiled_dir = sample_dir / "compiled"
    compiled_dir.mkdir(parents=True, exist_ok=True)
    html_path = sample_dir / "lesson.html"
    lesson_data = copy.deepcopy(compiled.lesson_data)
    lesson_data.setdefault("meta", {})["outputPath"] = str(html_path)
    _write_json(compiled_dir / "geometry-spec.json", compiled.geometry_spec)
    _write_json(
        compiled_dir / "step-decorations.json",
        compiled.step_decorations,
    )
    _write_json(compiled_dir / "lesson-data.json", lesson_data)
    subprocess.run(
        ["node", str(root / "tools/validate-geometry-spec.mjs"), str(compiled_dir)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["node", str(root / "tools/build-lesson-page.mjs"), str(compiled_dir)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if not html_path.exists():
        raise LessonAuthoringSmokeError(
            "lesson_page_compile_missing: compiler did not create lesson.html"
        )
    return html_path


def _run_sample(
    snapshot: ExplanationSnapshot,
    rubric: Mapping[str, Any],
    *,
    sample_id: str,
    sample_dir: Path,
    mode: SmokeMode,
    max_attempts: int,
    client_factory: Callable[[str], LLMPlannerClient] | None,
) -> dict[str, Any]:
    started = perf_counter()
    sample_dir.mkdir(parents=True, exist_ok=False)
    _write_snapshot_artifacts(sample_dir, snapshot=snapshot)
    current_prompt = current_lesson_prompt(snapshot)
    audited: _AuditedClient | None = None
    planner: LLMLessonPlanner | None = None
    llm_accepted = False
    planner_error: str | None = None

    if mode == "recorded":
        lesson = ExplanationBuilder().build_lesson(snapshot)
        lesson_source = "deterministic_recorded"
    else:
        if client_factory is None:
            raise LessonAuthoringSmokeError(
                "lesson_live_client_missing: live mode requires a client factory"
            )
        audited = _AuditedClient(
            client_factory(sample_id),
            sample_dir / "explanation",
        )
        planner = LLMLessonPlanner(
            client=audited,
            debug_dir=sample_dir / "explanation",
            allow_same_problem_few_shot=False,
            max_attempts=max_attempts,
        )
        observed = _ObservedLessonPlanner(planner)
        lesson = ExplanationBuilder(lesson_planner=observed).build_lesson(snapshot)
        llm_accepted = _llm_draft_was_accepted(
            observed,
            lesson=lesson,
            groups=current_prompt.groups,
            snapshot=snapshot,
        )
        lesson_source = "llm" if llm_accepted else "deterministic_fallback"
        if observed.error is not None:
            planner_error = f"{observed.error.__class__.__name__}: {observed.error}"

    LessonIRValidator().validate(lesson, snapshot)
    actual_prompt = (
        planner.last_prompt
        if planner is not None and planner.last_prompt is not None
        else current_prompt.prompt
    )
    actual_payload = (
        planner.last_payload
        if planner is not None and planner.last_payload is not None
        else current_prompt.payload
    )
    _write_prompt_artifacts(
        sample_dir,
        prompt=actual_prompt,
        payload=actual_payload,
    )
    raw_response = (
        planner.last_raw_response
        if planner is not None and planner.last_raw_response is not None
        else ""
    )
    _write_text(sample_dir / "raw-response.txt", raw_response)
    if planner is not None and planner.last_parsed is not None:
        _write_json(sample_dir / "parsed-lesson-draft.json", planner.last_parsed)

    lesson_payload = lesson.to_payload()
    evaluation = evaluate_lesson_teaching(lesson, rubric)
    _write_json(sample_dir / "lesson-ir.json", lesson_payload)
    _write_json(sample_dir / "lesson-evaluation.json", evaluation)

    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir)
    _write_json(sample_dir / "visual-step-ir.json", visual_ir.to_payload())
    compiled = forward_compile(visual_ir)
    html_path = _write_compiled_page(sample_dir, compiled=compiled)

    records = list(audited.records) if audited is not None else []
    usage = audited.usage if audited is not None else {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    provider_response_received = any(
        bool(item.get("visible_response")) for item in records
    )
    aggregate_metadata = {
        "schema_version": "lesson-llm-metadata/v1",
        "invoked": mode == "live",
        "lesson_source": lesson_source,
        "semantic_attempt_count": len(records),
        "provider_response_received": provider_response_received,
        "provider": records[-1].get("provider") if records else None,
        "request_model": records[-1].get("request_model") if records else None,
        "response_model": records[-1].get("response_model") if records else None,
        "prompt_hash": stable_hash(
            {"system": actual_prompt.system, "user": actual_prompt.user}
        ),
        "prompt_chars": {
            "system": len(actual_prompt.system),
            "user": len(actual_prompt.user),
            "total": len(actual_prompt.system) + len(actual_prompt.user),
        },
        "usage": usage,
        "provider_duration_seconds": round(
            sum(float(item.get("duration_seconds") or 0.0) for item in records),
            6,
        ),
        "first_token_seconds": None,
        "first_token_unavailable_reason": (
            "provider_client_uses_non_streaming_chat_completions"
            if mode == "live"
            else "llm_not_invoked"
        ),
        "fallback_used": lesson_source == "deterministic_fallback",
        "planner_error": planner_error,
    }
    _write_json(sample_dir / "llm-metadata.json", aggregate_metadata)

    duration_seconds = round(perf_counter() - started, 6)
    provider_audit_complete = (
        mode == "recorded"
        or (
            bool(records)
            and len(list((sample_dir / "explanation").glob("attempt-*.llm-metadata.json")))
            == len(records)
        )
    )
    pipeline_ok = html_path.exists()
    completion_ok = bool(
        pipeline_ok
        and provider_audit_complete
        and (mode == "recorded" or provider_response_received)
    )
    result = {
        "schema_version": SAMPLE_RESULT_SCHEMA,
        "problem_id": snapshot.problem_id,
        "sample_id": sample_id,
        "mode": mode,
        "completion_ok": completion_ok,
        "pipeline_ok": pipeline_ok,
        "provider_audit_complete": provider_audit_complete,
        "provider_response_received": provider_response_received,
        "lesson_source": lesson_source,
        "llm_accepted": llm_accepted,
        "fallback_used": lesson_source == "deterministic_fallback",
        "semantic_attempt_count": len(records),
        "provider_sub_attempt_count": sum(
            len(item.get("provider_attempts") or ()) for item in records
        ),
        "usage": usage,
        "duration_seconds": duration_seconds,
        "prompt_chars": aggregate_metadata["prompt_chars"],
        "lesson_step_count": len(lesson.steps),
        "visual_step_count": len(visual_ir.steps),
        "nonempty_visual_scene_count": sum(bool(item.scene) for item in visual_ir.steps),
        "teaching_coverage_rate": evaluation["coverage_rate"],
        "covered_teaching_points": evaluation["covered"],
        "missing_teaching_points": evaluation["missing"],
        "planner_error": planner_error,
        "sample_dir": str(sample_dir),
    }
    _write_json(sample_dir / "sample-result.json", result)
    return result


def _unclassified_sample_result(
    *,
    snapshot: ExplanationSnapshot,
    sample_id: str,
    sample_dir: Path,
    mode: SmokeMode,
    error: Exception,
) -> dict[str, Any]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": SAMPLE_RESULT_SCHEMA,
        "problem_id": snapshot.problem_id,
        "sample_id": sample_id,
        "mode": mode,
        "completion_ok": False,
        "pipeline_ok": False,
        "provider_audit_complete": False,
        "provider_response_received": False,
        "lesson_source": "error",
        "llm_accepted": False,
        "fallback_used": False,
        "semantic_attempt_count": 0,
        "provider_sub_attempt_count": 0,
        "usage": {},
        "duration_seconds": 0.0,
        "prompt_chars": {},
        "lesson_step_count": 0,
        "visual_step_count": 0,
        "nonempty_visual_scene_count": 0,
        "teaching_coverage_rate": 0.0,
        "covered_teaching_points": [],
        "missing_teaching_points": [],
        "planner_error": f"{error.__class__.__name__}: {error}",
        "sample_dir": str(sample_dir),
    }
    _write_json(sample_dir / "sample-result.json", result)
    return result


def run_smoke_batch(
    snapshot: ExplanationSnapshot,
    rubric: Mapping[str, Any],
    *,
    mode: SmokeMode,
    batch_dir: Path,
    samples_per_case: int,
    concurrency: int,
    max_attempts: int,
    client_factory: Callable[[str], LLMPlannerClient] | None = None,
    batch_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one recorded/live B0 batch against an already verified Snapshot."""

    if min(samples_per_case, concurrency, max_attempts) < 1:
        raise LessonAuthoringSmokeError(
            "lesson_smoke_config_invalid: sample, concurrency and attempts must be positive"
        )
    if batch_dir.exists():
        raise LessonAuthoringSmokeError(
            f"lesson_smoke_batch_exists: {batch_dir}"
        )
    batch_dir.mkdir(parents=True)
    rubric_payload = validate_teaching_rubric(rubric)
    if rubric_payload["problem_id"] != snapshot.problem_id:
        raise LessonAuthoringSmokeError(
            "lesson_smoke_rubric_problem_mismatch: rubric and Snapshot differ"
        )
    recorded = build_recorded_lesson_artifacts(snapshot)
    recorded_evaluation = evaluate_lesson_teaching(recorded.lesson, rubric_payload)
    coverage = build_teaching_spec_coverage(
        snapshot,
        lesson_evaluation=recorded_evaluation,
    )
    _write_json(batch_dir / "batch-config.json", dict(batch_config or {}))
    _write_json(batch_dir / "teaching-spec-coverage.json", coverage)

    results: list[dict[str, Any]] = []
    jobs = [f"sample-{index:02d}" for index in range(1, samples_per_case + 1)]
    with ThreadPoolExecutor(max_workers=min(concurrency, len(jobs))) as executor:
        futures = {
            executor.submit(
                _run_sample,
                snapshot,
                rubric_payload,
                sample_id=sample_id,
                sample_dir=batch_dir / snapshot.problem_id / sample_id,
                mode=mode,
                max_attempts=max_attempts,
                client_factory=client_factory,
            ): sample_id
            for sample_id in jobs
        }
        for future in as_completed(futures):
            sample_id = futures[future]
            sample_dir = batch_dir / snapshot.problem_id / sample_id
            try:
                result = future.result()
            except Exception as exc:
                result = _unclassified_sample_result(
                    snapshot=snapshot,
                    sample_id=sample_id,
                    sample_dir=sample_dir,
                    mode=mode,
                    error=exc,
                )
            results.append(result)
            print(
                f"{snapshot.problem_id}/{sample_id}: "
                f"completion={result['completion_ok']} "
                f"source={result['lesson_source']} "
                f"attempts={result['semantic_attempt_count']} "
                f"coverage={result['teaching_coverage_rate']}",
                flush=True,
            )

    results.sort(key=lambda item: item["sample_id"])
    summary = _batch_summary(
        mode=mode,
        problem_id=snapshot.problem_id,
        results=results,
    )
    _write_json(batch_dir / "batch-summary.json", summary)
    return summary


def _batch_summary(
    *,
    mode: SmokeMode,
    problem_id: str,
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    durations: list[float] = []
    for result in results:
        durations.append(float(result.get("duration_seconds") or 0.0))
        sample_usage = result.get("usage") or {}
        for key in usage:
            value = sample_usage.get(key)
            if isinstance(value, int):
                usage[key] += value
    sample_count = len(results)
    return {
        "schema_version": BATCH_SUMMARY_SCHEMA,
        "problem_id": problem_id,
        "mode": mode,
        "sample_count": sample_count,
        "completion_count": sum(bool(item.get("completion_ok")) for item in results),
        "completion_gate_ok": bool(results) and all(
            bool(item.get("completion_ok")) for item in results
        ),
        "llm_accepted_count": sum(bool(item.get("llm_accepted")) for item in results),
        "fallback_count": sum(bool(item.get("fallback_used")) for item in results),
        "semantic_attempts": sum(
            int(item.get("semantic_attempt_count") or 0) for item in results
        ),
        "usage": usage,
        "average_usage": {
            key: round(value / sample_count, 3) if sample_count else 0.0
            for key, value in usage.items()
        },
        "duration_seconds": {
            "total": round(sum(durations), 6),
            "average": round(statistics.fmean(durations), 6) if durations else 0.0,
            "p50": round(statistics.median(durations), 6) if durations else 0.0,
            "p95": round(_nearest_rank_percentile(durations, 0.95), 6),
        },
        "teaching_coverage": {
            "average": (
                round(
                    statistics.fmean(
                        float(item.get("teaching_coverage_rate") or 0.0)
                        for item in results
                    ),
                    6,
                )
                if results
                else 0.0
            ),
            "by_sample": {
                str(item["sample_id"]): {
                    "covered": list(item.get("covered_teaching_points") or ()),
                    "missing": list(item.get("missing_teaching_points") or ()),
                }
                for item in results
            },
        },
        "samples": [dict(item) for item in results],
    }


def _nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(len(ordered) * percentile + 0.999999))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _selected_case(problem_id: str) -> GoldCorpusCase:
    matches = [item for item in load_gold_corpus().cases if item.problem_id == problem_id]
    if len(matches) != 1:
        raise LessonAuthoringSmokeError(
            f"lesson_smoke_case_invalid: expected one gold case for {problem_id}"
        )
    return matches[0]


def build_recorded_snapshot(
    problem_id: str,
    *,
    authority_dir: Path,
    f2_root: Path,
) -> ExplanationSnapshot:
    """Build Snapshot from a successful authenticated recorded Solver run."""

    fixture = _build_planner_authority(
        _selected_case(problem_id),
        authority_dir,
        f2_root,
    )
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    result = orchestrator.solve_verified(fixture.bundle)
    if result.status != "ok" or orchestrator.last_success_artifacts is None:
        raise LessonAuthoringSmokeError(
            "lesson_smoke_recorded_solver_failed: "
            + "; ".join(result.errors or [result.status])
        )
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("recorded", "live"), required=True)
    parser.add_argument("--case", default=CASE_ID)
    parser.add_argument("--samples-per-case", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.case != CASE_ID:
        parser.error(f"F5-F5B0 supports only --case {CASE_ID}")
    if min(args.samples_per_case, args.concurrency, args.max_attempts) < 1:
        parser.error("sample, concurrency and max-attempts values must be positive")
    if args.mode == "live" and os.environ.get("RUN_LLM_INTEGRATION") != "1":
        parser.error("live lesson smoke requires RUN_LLM_INTEGRATION=1")

    root = _repo_root()
    output_root = _resolve_repo_path(root, args.output_root)
    batch_dir = output_root / args.batch_id
    fixture_root = (
        root
        / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b0"
    )
    rubric_path = fixture_root / "rubric.json"
    batch_config: dict[str, Any] = {
        "schema_version": "lesson-authoring-smoke-config/v1",
        "batch_id": args.batch_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": args.mode,
        "case_ids": [args.case],
        "samples_per_case": args.samples_per_case,
        "concurrency": min(args.concurrency, args.samples_per_case),
        "max_attempts": args.max_attempts,
        "allow_same_problem_few_shot": False,
        "visual_llm_enabled": False,
        "output_dir": str(batch_dir),
    }
    if args.dry_run:
        print(json.dumps(batch_config, ensure_ascii=False, indent=2))
        return 0
    if not rubric_path.exists():
        parser.error(f"B0 rubric is missing: {rubric_path}")
    if batch_dir.exists():
        parser.error(f"batch output already exists: {batch_dir}")

    f2_root = _resolve_repo_path(root, DEFAULT_F2_INPUT)
    # Planner authority material is only an input used to authenticate the
    # recorded Solver run.  Keeping it outside ``batch_dir`` lets
    # ``run_smoke_batch`` retain its fail-loud, create-once batch contract and
    # prevents implementation-only authority files from entering B0 artifacts.
    with tempfile.TemporaryDirectory(prefix="lesson-b0-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            args.case,
            authority_dir=Path(temp_dir),
            f2_root=f2_root,
        )
    rubric = load_teaching_rubric(rubric_path)

    client_factory: Callable[[str], LLMPlannerClient] | None = None
    if args.mode == "live":
        config = SolverRuntimeConfig.from_sources(
            planner_mode="strategy",
            llm_provider="deepseek",
            env_file=root / "server/.env",
        )
        if not config.deepseek_api_key:
            parser.error("DEEPSEEK_API_KEY is required for live lesson smoke")
        batch_config.update(
            {
                "provider": "deepseek",
                "model": config.llm_model or config.deepseek_model,
            }
        )

        def client_factory(_sample_id: str) -> LLMPlannerClient:
            return config.build_llm_client()
    else:
        batch_config.update({"provider": "recorded", "model": None})

    summary = run_smoke_batch(
        snapshot,
        rubric,
        mode=args.mode,
        batch_dir=batch_dir,
        samples_per_case=args.samples_per_case,
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
        client_factory=client_factory,
        batch_config=batch_config,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["completion_gate_ok"] else 1


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
