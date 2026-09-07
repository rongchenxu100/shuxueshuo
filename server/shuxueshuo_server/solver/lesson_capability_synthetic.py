"""Typed C0 scenarios for Planner-public capabilities absent from recordings.

The scenarios execute the real stateless Method and then project its verified
inputs/results through the normal TeachingSource -> LessonIR -> VisualStepIR
pipeline.  They are test/debug assets, never Planner or Lesson-LLM examples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import sympy as sp

from shuxueshuo_server.solver.contracts import PointRef, StatelessMethodResult
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingGoal,
    TeachingScope,
    TeachingSource,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.methods import (
    DistanceBetweenPointsMethod,
    EqualLengthRayPointMethod,
    LineIntersectionPointMethod,
)
from shuxueshuo_server.solver.student_display import student_math_display


SYNTHETIC_SCENARIO_CONTRACT = "lesson-capability-synthetic-scenario/v1"


@dataclass(frozen=True)
class SyntheticCapabilityScenario:
    capability_id: str
    snapshot: ExplanationSnapshot
    source: TeachingSource
    result: StatelessMethodResult

    def coverage_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SYNTHETIC_SCENARIO_CONTRACT,
            "problem_id": self.snapshot.problem_id,
            "source_step_id": self.source.source_step_id,
            "execution": "real_stateless_method",
            "input_runtime_types": {
                name: sorted(
                    {str(item["runtime_type"]) for item in items}
                )
                for name, items in self.source.inputs.items()
            },
            "output_runtime_types": {
                name: str(value["runtime_type"])
                for name, value in self.source.outputs.items()
            },
            "checks_passed": all(check.ok for check in self.result.checks),
        }


def build_synthetic_capability_scenarios(
) -> dict[str, SyntheticCapabilityScenario]:
    """Build the exact three C0 coverage scenarios with real Method execution."""

    builders: tuple[Callable[[], SyntheticCapabilityScenario], ...] = (
        _distance_scenario,
        _equal_length_ray_scenario,
        _line_intersection_scenario,
    )
    scenarios = {item.capability_id: item for item in map(lambda fn: fn(), builders)}
    if len(scenarios) != len(builders):
        raise ValueError("lesson_synthetic_capability_id_duplicated")
    return scenarios


def _distance_scenario() -> SyntheticCapabilityScenario:
    points = {"A": (0, 0), "B": (3, 4)}
    result = DistanceBetweenPointsMethod().run(
        {"p1": points["A"], "p2": points["B"]},
        SympyKernel(),
    )
    source = _teaching_source(
        capability_id="distance_between_points",
        intent="用两点距离公式求线段 AB 的长度。",
        inputs={
            "p1": (_point_input("A", points["A"]),),
            "p2": (_point_input("B", points["B"]),),
        },
        result=result,
        output_targets={},
    )
    return _scenario(
        source=source,
        result=result,
        points=points,
        problem_text="已知 A(0,0)，B(3,4)，求线段 AB 的长度。",
        answer_return="distance",
        answer_key="distance",
    )


def _equal_length_ray_scenario() -> SyntheticCapabilityScenario:
    points = {"A": (0, 0), "B": (0, 3), "C": (2, 0)}
    target = PointRef("D", "point:problem:D", scope_id="problem")
    result = EqualLengthRayPointMethod().run(
        {
            "anchor": points["A"],
            "reference_point": points["B"],
            "ray_point": points["C"],
            "target": target,
        },
        SympyKernel(),
    )
    source = _teaching_source(
        capability_id="equal_length_ray_point",
        intent="在射线 AC 上作点 D，使 AD=AB。",
        inputs={
            "anchor": (_point_input("A", points["A"]),),
            "reference_point": (_point_input("B", points["B"]),),
            "ray_point": (_point_input("C", points["C"]),),
            "target": (_point_ref_input(target),),
        },
        result=result,
        output_targets={"point": target.path},
    )
    return _scenario(
        source=source,
        result=result,
        points=points,
        target=target,
        problem_text="在射线 AC 上作点 D，使 AD=AB。",
        answer_return="point",
        answer_key="D",
    )


def _line_intersection_scenario() -> SyntheticCapabilityScenario:
    points = {
        "A": (0, 0),
        "B": (4, 4),
        "C": (0, 4),
        "D": (4, 0),
    }
    target = PointRef("H", "point:problem:H", scope_id="problem")
    result = LineIntersectionPointMethod().run(
        {
            "line1_p1": points["A"],
            "line1_p2": points["B"],
            "line2_p1": points["C"],
            "line2_p2": points["D"],
            "target": target,
        },
        SympyKernel(),
    )
    source = _teaching_source(
        capability_id="line_intersection_point",
        intent="联立直线 AB 与 CD 的方程，求交点 H。",
        inputs={
            "line1_p1": (_point_input("A", points["A"]),),
            "line1_p2": (_point_input("B", points["B"]),),
            "line2_p1": (_point_input("C", points["C"]),),
            "line2_p2": (_point_input("D", points["D"]),),
            "target": (_point_ref_input(target),),
        },
        result=result,
        output_targets={"intersection": target.path},
    )
    return _scenario(
        source=source,
        result=result,
        points=points,
        target=target,
        problem_text="已知直线 AB 与 CD 相交于 H，求 H 的坐标。",
        answer_return="intersection",
        answer_key="H",
    )


def _teaching_source(
    *,
    capability_id: str,
    intent: str,
    inputs: Mapping[str, tuple[Mapping[str, Any], ...]],
    result: StatelessMethodResult,
    output_targets: Mapping[str, str],
) -> TeachingSource:
    if result.method_id != capability_id or not all(check.ok for check in result.checks):
        raise ValueError(f"lesson_synthetic_method_execution_failed: {capability_id}")
    return TeachingSource(
        source_step_id=f"synthetic_{capability_id}",
        capability_id=capability_id,
        inputs={name: tuple(dict(item) for item in values) for name, values in inputs.items()},
        outputs={
            name: _runtime_result_payload(
                typed.type,
                typed.value,
                label=_target_label(output_targets.get(name)),
            )
            for name, typed in result.outputs.items()
        },
        output_targets=dict(output_targets),
        intent=intent,
        checks=tuple(
            {
                "check_id": check.name,
                "kind": "runtime_method_check",
                "passed": check.ok,
                "detail": check.detail,
            }
            for check in result.checks
        ),
    )


def _scenario(
    *,
    source: TeachingSource,
    result: StatelessMethodResult,
    points: Mapping[str, tuple[int, int]],
    problem_text: str,
    answer_return: str,
    answer_key: str,
    target: PointRef | None = None,
) -> SyntheticCapabilityScenario:
    goal_ref = f"problem.{answer_key}"
    root_scope = TeachingScope(
        scope_ref="problem",
        goals=(
            TeachingGoal(
                goal_ref=goal_ref,
                steps=(source,),
                answer_from={
                    "step_id": source.source_step_id,
                    "return": answer_return,
                },
            ),
        ),
    )
    entities = [
        {
            "handle": _point_handle(label),
            "entity_type": "point",
            "name": label,
            "scope_id": "problem",
            "coordinate": [str(pair[0]), str(pair[1])],
            "definition": "given_point",
        }
        for label, pair in points.items()
    ]
    if target is not None:
        entities.append(
            {
                "handle": target.path,
                "entity_type": "point",
                "name": target.name,
                "scope_id": "problem",
                "definition": "derived_point",
            }
        )
    problem = {
        "original_text": [problem_text],
        "scopes": [{"scope_id": "problem", "label": "合成验收"}],
        "question_goals": [
            {
                "handle": f"answer:{goal_ref}",
                "scope_id": "problem",
                "answer_key": answer_key,
                "value_type": source.outputs[answer_return]["runtime_type"],
                **({"target_handle": target.path} if target is not None else {}),
            }
        ],
        "entities": entities,
        "facts": [],
    }
    answer_value = source.outputs[answer_return]["value"]
    snapshot = ExplanationSnapshot(
        problem_id=f"synthetic-{source.capability_id}",
        family_id="lesson_capability_synthetic",
        problem_revision=f"synthetic:{source.capability_id}:v1",
        problem_semantic_hash=stable_hash(problem),
        canonical_plan_hash=stable_hash(root_scope.to_payload()),
        verified_execution_hash=stable_hash(
            {
                "method_id": result.method_id,
                "outputs": source.outputs,
                "checks": [check.ok for check in result.checks],
            }
        ),
        problem=problem,
        root_scope=root_scope,
        answers={"problem": {answer_key: answer_value}},
    )
    return SyntheticCapabilityScenario(
        capability_id=source.capability_id,
        snapshot=snapshot,
        source=source,
        result=result,
    )


def _point_input(label: str, pair: tuple[int, int]) -> dict[str, Any]:
    value = [str(pair[0]), str(pair[1])]
    return {
        "ref": {"kind": "source", "ref": _point_handle(label)},
        "runtime_type": "Point",
        "value": value,
        "display": f"{label}({value[0]},{value[1]})",
    }


def _point_ref_input(target: PointRef) -> dict[str, Any]:
    return {
        "ref": {"kind": "source", "ref": target.path},
        "runtime_type": "PointRef",
        "value": {
            "entity_type": "point",
            "name": target.name,
            "description": target.name,
        },
        "display": target.name,
    }


def _runtime_result_payload(
    runtime_type: str,
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    public_value = _json_math_value(value)
    if runtime_type == "Point" and isinstance(public_value, list):
        coordinate = (
            f"({student_math_display(public_value[0])},"
            f"{student_math_display(public_value[1])})"
        )
        display = f"{label}{coordinate}" if label else coordinate
    else:
        display = student_math_display(public_value)
    return {
        "runtime_type": runtime_type,
        "value": public_value,
        "display": display,
    }


def _json_math_value(value: Any) -> Any:
    if isinstance(value, sp.Basic):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_math_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_math_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"lesson_synthetic_value_not_public: {type(value).__name__}")


def _point_handle(label: str) -> str:
    return f"point:problem:{label}"


def _target_label(value: str | None) -> str:
    return str(value or "").rsplit(":", 1)[-1]


__all__ = [
    "SYNTHETIC_SCENARIO_CONTRACT",
    "SyntheticCapabilityScenario",
    "build_synthetic_capability_scenarios",
]
