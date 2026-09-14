"""Shared recorded-fixture and teaching-evaluation support for F5 Lesson work.

This module deliberately contains no Lesson builder or LLM prompt code.  It
keeps the B1-B4 review tools independent from the retired flat B0 authoring
pipeline while preserving the evaluation-only rubric contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import unicodedata

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
)
from shuxueshuo_server.solver.explanation.snapshot import (
    ExplanationSnapshotBuilder,
)
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.scoped_functional_plan_smoke import (
    _build_planner_authority,
)


CASE_ID = "tj-2026-heping-ermo-25"
DEFAULT_OUTPUT_ROOT = (
    "internal/solver-runs/explanation-builder-deepseek-scope-vnext"
)
RUBRIC_SCHEMA = "lesson-teaching-rubric/v1"
EVALUATION_SCHEMA = "lesson-teaching-evaluation/v1"


class LessonAuthoringSupportError(ValueError):
    """A recorded Lesson fixture or evaluation contract is inconsistent."""


def load_teaching_rubric(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_teaching_rubric(payload)


def validate_teaching_rubric(payload: Mapping[str, Any]) -> dict[str, Any]:
    allowed_root = {"schema_version", "problem_id", "points"}
    if set(payload) != allowed_root:
        raise LessonAuthoringSupportError(
            "lesson_teaching_rubric_invalid: root fields must be "
            f"{sorted(allowed_root)}"
        )
    if payload.get("schema_version") != RUBRIC_SCHEMA:
        raise LessonAuthoringSupportError(
            "lesson_teaching_rubric_invalid: unsupported schema_version"
        )
    problem_id = str(payload.get("problem_id") or "")
    raw_points = payload.get("points")
    if not problem_id or not isinstance(raw_points, list) or not raw_points:
        raise LessonAuthoringSupportError(
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
            raise LessonAuthoringSupportError(
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
            raise LessonAuthoringSupportError(
                f"lesson_teaching_rubric_invalid: points[{index}] is incomplete"
            )
        normalized_groups: list[list[str]] = []
        for group_index, group in enumerate(groups):
            if (
                not isinstance(group, list)
                or not group
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in group
                )
            ):
                raise LessonAuthoringSupportError(
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
    return text.translate(str.maketrans("", "", " \t\r\n，,。；;：:、"))


def evaluate_lesson_teaching(
    lesson: Any | Mapping[str, Any],
    rubric: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate either historical flat LessonIR or recursive LessonIR v2."""

    rubric_payload = validate_teaching_rubric(rubric)
    lesson_payload = (
        lesson.to_payload() if hasattr(lesson, "to_payload") else dict(lesson)
    )
    if str(lesson_payload.get("problem_id") or "") != rubric_payload["problem_id"]:
        raise LessonAuthoringSupportError(
            "lesson_teaching_evaluation_problem_mismatch: lesson and rubric differ"
        )
    if lesson_payload.get("schema_version") == "lesson-ir/v2":
        raw_steps = _recursive_lesson_rows(lesson_payload.get("root_scope"))
    else:
        raw_steps = lesson_payload.get("steps")
        if not isinstance(raw_steps, list):
            raise LessonAuthoringSupportError(
                "lesson_teaching_evaluation_invalid: LessonIR steps are missing"
            )
    return evaluate_teaching_rows(
        raw_steps,
        rubric_payload,
        problem_id=str(lesson_payload["problem_id"]),
    )


def evaluate_teaching_rows(
    rows: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any],
    *,
    problem_id: str,
) -> dict[str, Any]:
    rubric_payload = validate_teaching_rubric(rubric)
    if problem_id != rubric_payload["problem_id"]:
        raise LessonAuthoringSupportError(
            "lesson_teaching_evaluation_problem_mismatch: rows and rubric differ"
        )
    covered: list[str] = []
    missing: list[str] = []
    evidence_by_point: dict[str, Any] = {}
    for point in rubric_payload["points"]:
        source_step_id = point["source_step_id"]
        selected = [
            step
            for step in rows
            if isinstance(step, Mapping)
            and source_step_id in tuple(step.get("source_step_ids") or ())
        ]
        combined = normalize_teaching_math_text(
            "\n".join(_lesson_step_student_text(step) for step in selected)
        )
        matched_groups = [
            next(
                (
                    alternative
                    for alternative in alternatives
                    if normalize_teaching_math_text(alternative) in combined
                ),
                None,
            )
            for alternatives in point["required_pattern_groups"]
        ]
        point_id = point["point_id"]
        is_covered = bool(selected) and all(matched_groups)
        (covered if is_covered else missing).append(point_id)
        evidence_by_point[point_id] = {
            "source_step_id": source_step_id,
            "lesson_step_ids": [
                str(step.get("lesson_step_id") or step.get("id") or "")
                for step in selected
            ],
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


def build_recorded_snapshot(
    problem_id: str,
    *,
    authority_dir: Path,
    f2_root: Path,
) -> ExplanationSnapshot:
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
        raise LessonAuthoringSupportError(
            "lesson_recorded_solver_failed: "
            + "; ".join(result.errors or [result.status])
        )
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _selected_case(problem_id: str) -> GoldCorpusCase:
    matches = [
        item for item in load_gold_corpus().cases if item.problem_id == problem_id
    ]
    if len(matches) != 1:
        raise LessonAuthoringSupportError(
            f"lesson_recorded_case_invalid: expected one gold case for {problem_id}"
        )
    return matches[0]


def _recursive_lesson_rows(raw_scope: Any) -> list[Mapping[str, Any]]:
    if not isinstance(raw_scope, Mapping):
        raise LessonAuthoringSupportError(
            "lesson_teaching_evaluation_invalid: recursive root_scope is missing"
        )
    rows: list[Mapping[str, Any]] = []
    raw_steps = raw_scope.get("steps")
    raw_goals = raw_scope.get("goals")
    raw_children = raw_scope.get("children")
    if (
        not isinstance(raw_steps, list)
        or not isinstance(raw_goals, Mapping)
        or not isinstance(raw_children, list)
    ):
        raise LessonAuthoringSupportError(
            "lesson_teaching_evaluation_invalid: recursive Scope is malformed"
        )
    rows.extend(item for item in raw_steps if isinstance(item, Mapping))
    for raw_goal in raw_goals.values():
        if not isinstance(raw_goal, Mapping) or not isinstance(
            raw_goal.get("steps"), list
        ):
            raise LessonAuthoringSupportError(
                "lesson_teaching_evaluation_invalid: recursive Goal is malformed"
            )
        rows.extend(
            item for item in raw_goal["steps"] if isinstance(item, Mapping)
        )
    for child in raw_children:
        rows.extend(_recursive_lesson_rows(child))
    return rows


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


__all__ = [
    "CASE_ID",
    "DEFAULT_OUTPUT_ROOT",
    "EVALUATION_SCHEMA",
    "LessonAuthoringSupportError",
    "RUBRIC_SCHEMA",
    "build_recorded_snapshot",
    "evaluate_lesson_teaching",
    "evaluate_teaching_rows",
    "load_teaching_rubric",
    "normalize_teaching_math_text",
    "validate_teaching_rubric",
]
