"""Strict mechanism examples for scope-native FunctionalPlan v2 prompts."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)


def default_scoped_functional_few_shot_dir() -> Path:
    return repo_root() / "internal" / "functional-few-shots-v2"


def load_scoped_functional_few_shot(
    example_id: str,
    *,
    directory: Path | str | None = None,
) -> dict[str, Any] | None:
    """Load one v2 example selected by the existing mechanism index."""

    root = Path(directory) if directory is not None else (
        default_scoped_functional_few_shot_dir()
    )
    if not root.exists():
        return None
    for path in sorted(root.glob("*.functional-few-shot.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        validated = _validated_asset(payload, source=path)
        if validated["example_id"] == example_id:
            result = {
                "annotation": validated["annotation"],
                "plan": validated["plan"],
            }
            if "problem_goal" in validated:
                result["problem_goal"] = validated["problem_goal"]
            return result
    return None


def select_scoped_functional_few_shot(
    capability_ids: set[str] | frozenset[str],
    *,
    preferred_capability_ids: set[str] | frozenset[str] = frozenset(),
    directory: Path | str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Select one self-contained v2 mechanism using capability containment."""

    root = Path(directory) if directory is not None else (
        default_scoped_functional_few_shot_dir()
    )
    preferred = set(preferred_capability_ids)
    candidates: list[tuple[int, int, str, str, dict[str, Any]]] = []
    if root.exists():
        for path in sorted(root.glob("*.functional-few-shot.json")):
            payload = _validated_asset(
                json.loads(path.read_text(encoding="utf-8")),
                source=path,
            )
            required = _plan_capability_ids(payload["plan"])
            if required <= capability_ids:
                candidates.append(
                    (
                        -len(required.intersection(preferred)),
                        -len(required),
                        payload["example_id"],
                        sha256(path.read_bytes()).hexdigest(),
                        payload,
                    )
                )
    if not candidates:
        return None, None
    _preferred_score, _size_score, example_id, asset_sha256, selected = min(
        candidates
    )
    result: dict[str, Any] = {
        "annotation": selected["annotation"],
        "plan": selected["plan"],
    }
    if "problem_goal" in selected:
        result["problem_goal"] = selected["problem_goal"]
    return (
        result,
        {
            "example_id": example_id,
            "mode": "v2_capability_subset",
            "asset_sha256": asset_sha256,
        },
    )


def validate_scoped_functional_few_shot_asset(payload: object) -> None:
    _validated_asset(payload, source=None)


def _validated_asset(
    payload: object,
    *,
    source: Path | None,
) -> dict[str, Any]:
    label = str(source) if source is not None else "scoped functional few-shot"
    if (
        not isinstance(payload, dict)
        or not set(payload)
        <= {"example_id", "annotation", "plan", "problem_goal"}
        or not {"example_id", "annotation", "plan"} <= set(payload)
    ):
        raise ValueError(
            f"{label} must contain example_id, annotation, and plan; "
            "problem_goal is optional"
        )
    problem_goal = payload.get("problem_goal")
    if problem_goal is not None and (
        not isinstance(problem_goal, dict)
        or set(problem_goal) != {
            "goal_ref",
            "kind",
            "target_ref",
            "answer_type",
        }
        or not all(
            isinstance(problem_goal.get(key), str)
            and problem_goal[key].strip()
            for key in problem_goal
        )
    ):
        raise ValueError(
            f"{label} problem_goal must contain non-empty goal_ref, kind, "
            "target_ref, and answer_type"
        )
    example_id = payload.get("example_id")
    if not isinstance(example_id, str) or not example_id.strip():
        raise ValueError(f"{label} example_id must be non-empty")
    annotation = payload.get("annotation")
    if not isinstance(annotation, dict) or set(annotation) != {
        "purpose",
        "use_when",
        "key_idea",
        "do_not_use_when",
    }:
        raise ValueError(f"{label} annotation contract is invalid")
    for key in ("purpose", "use_when", "key_idea"):
        if not isinstance(annotation.get(key), str) or not annotation[key].strip():
            raise ValueError(f"{label} annotation.{key} must be non-empty")
    exclusions = annotation.get("do_not_use_when")
    if not isinstance(exclusions, list) or not exclusions or not all(
        isinstance(item, str) and item.strip() for item in exclusions
    ):
        raise ValueError(
            f"{label} annotation.do_not_use_when must be non-empty strings"
        )
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload.get("plan")
    )
    if not report.ok or plan is None:
        raise ValueError(f"{label} plan is invalid: {report.to_payload()}")
    return payload


def _plan_capability_ids(plan: dict[str, Any]) -> frozenset[str]:
    result: set[str] = set()

    def visit(scope: dict[str, Any]) -> None:
        for step in scope.get("steps", ()):
            result.add(step["capability_id"])
        for goal in scope.get("goals", ()):
            for step in goal.get("steps", ()):
                result.add(step["capability_id"])
        for child in scope.get("children", ()):
            visit(child)

    visit(plan["root_scope"])
    return frozenset(result)
