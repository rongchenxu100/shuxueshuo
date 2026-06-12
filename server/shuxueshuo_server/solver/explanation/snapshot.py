"""从成功 runtime run 构建 ExplanationSnapshot。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

import sympy as sp

from shuxueshuo_server.solver.contracts import PointRef, TypedValue
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import PlanExecutionResult, PlannerOutput, StepPlan
from shuxueshuo_server.solver.runtime.projection import RuntimeProjection

from .models import ExplanationSnapshot, TeachingTraceEntry


class ExplanationSnapshotError(RuntimeError):
    """ExplanationSnapshot 构建失败。"""


class ExplanationSnapshotBuilder:
    """把 RuntimeOrchestrator 的成功产物转成讲解层 snapshot。"""

    def build(self, artifacts: Any) -> ExplanationSnapshot:
        """从 ``RuntimeSuccessArtifacts`` 构建 snapshot。"""
        result = artifacts.solver_result
        if getattr(result, "status", None) != "ok":
            raise ExplanationSnapshotError("explanation snapshot requires ok SolverResult")
        planner_artifacts = getattr(artifacts.planner, "artifacts", None)
        effective_draft = getattr(planner_artifacts, "effective_draft", None)
        if effective_draft is None:
            raise ExplanationSnapshotError("strategy planner effective draft is required")
        problem_payload = RuntimeProjection(artifacts.problem).to_llm_problem_payload()
        effective_steps = tuple(
            step.to_payload(include_scope_id=True)
            for step in effective_draft.steps
        )
        step_capabilities = {
            step.step_id: step.recipe_hint or step.goal_type
            for step in effective_draft.steps
        }
        snapshot = ExplanationSnapshot(
            problem_id=artifacts.problem.problem_id,
            family_id=str(getattr(artifacts.family, "family_id", "")),
            problem=problem_payload,
            effective_steps=effective_steps,
            teaching_trace=_build_teaching_trace(
                artifacts.planner_output,
                artifacts.execution,
                step_capabilities,
            ),
            fact_index=_build_fact_index(
                artifacts.context,
                effective_draft.steps,
            ),
            planner_insights=_planner_insights(planner_artifacts),
            answers=_clean_value(result.answers, artifacts.context),
            checks=tuple(_check_payload(check) for check in result.checks),
        )
        _assert_safe_snapshot(snapshot)
        return snapshot


def _build_teaching_trace(
    planner_output: PlannerOutput,
    execution: PlanExecutionResult,
    step_capabilities: dict[str, str],
) -> tuple[TeachingTraceEntry, ...]:
    """按 invocation 建立 trace，避免同 method 多次调用被合并。"""
    entries: list[TeachingTraceEntry] = []
    step_results = {item.step_id: item for item in execution.step_results}
    for plan in planner_output.step_plans:
        step_result = step_results.get(plan.step_id)
        method_results = list(step_result.method_results) if step_result else []
        for index, invocation in enumerate(plan.invocations):
            method_result = method_results[index] if index < len(method_results) else None
            trace_id = f"trace:{plan.step_id}:{index}:{invocation.method_id}"
            entries.append(
                TeachingTraceEntry(
                    trace_id=trace_id,
                    source_step_id=plan.step_id,
                    scope_id=plan.scope,
                    capability_id=step_capabilities.get(plan.step_id, invocation.method_id),
                    method_id=invocation.method_id,
                    input_slots=tuple(invocation.inputs),
                    output_slots=tuple(invocation.outputs),
                    checks=tuple(
                        str(getattr(check, "name", check))
                        for check in getattr(method_result, "checks", [])
                    ),
                    trace_fragments=tuple(
                        _trace_fragment_payload(fragment)
                        for fragment in getattr(method_result, "trace_fragments", [])
                    ),
                    hidden_reason=_hidden_reason(plan, index),
                )
            )
    return tuple(entries)


def _hidden_reason(plan: StepPlan, invocation_index: int) -> str | None:
    """EB1 只隐藏明显的 prep/cache invocation。"""
    invocation = plan.invocations[invocation_index]
    text = f"{invocation.invocation_id} {invocation.method_id}".lower()
    if "prep" in text or "prepared" in text or "cache" in text:
        return "prep_or_cache"
    return None


def _build_fact_index(
    context: RuntimeContext,
    effective_steps: tuple[Any, ...],
) -> dict[str, dict[str, Any]]:
    """建立讲解可用 fact index，不输出 ContextPath。"""
    index: dict[str, dict[str, Any]] = {}
    for step in effective_steps:
        for produced in step.produces:
            index[produced.handle] = {
                "handle": produced.handle,
                "scope_id": produced.valid_scope,
                "type": produced.output_type,
                "description": produced.description,
                "source_step_id": step.step_id,
                "source": "effective_step",
            }
    for scope_id, scope in sorted(context.scopes.items()):
        for container_name, container in _scope_containers(scope).items():
            for key, typed in sorted(container.items()):
                handle = f"runtime:{scope_id}:{container_name}:{key}"
                index[handle] = {
                    "handle": handle,
                    "scope_id": scope_id,
                    "container": container_name,
                    "name": key,
                    "type": typed.type,
                    "value": _typed_value_payload(typed, context),
                    "locked": typed.locked,
                    "source": typed.source,
                }
    return index


def _scope_containers(scope: Any) -> dict[str, dict[str, TypedValue]]:
    containers: dict[str, dict[str, TypedValue]] = {}
    containers.update(scope.facts)
    if scope.constraints:
        containers["constraints"] = scope.constraints
    if scope.outputs:
        containers["outputs"] = scope.outputs
    if scope.temp_values:
        containers["temp"] = scope.temp_values
    return containers


def _typed_value_payload(typed: TypedValue, context: RuntimeContext) -> Any:
    if typed.type == "PointRef":
        point_ref: PointRef = typed.value
        return {
            "name": point_ref.name,
            "scope_id": point_ref.scope_id,
            "definition": _clean_value(point_ref.definition, context),
        }
    return _clean_value(typed.value, context)


def _planner_insights(planner_artifacts: Any) -> tuple[dict[str, Any], ...]:
    diagnostic = getattr(planner_artifacts, "execution_diagnostic", None)
    if diagnostic is None:
        return ()
    return tuple(item.to_payload() for item in diagnostic.planner_insights)


def _trace_fragment_payload(fragment: Any) -> dict[str, Any]:
    if is_dataclass(fragment):
        return _clean_value(asdict(fragment), None)
    if isinstance(fragment, dict):
        return _clean_value(fragment, None)
    return {"text": str(fragment)}


def _check_payload(check: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(check, "name", "")),
        "status": str(getattr(check, "status", "")),
        "detail": str(getattr(check, "detail", "")),
    }


def _clean_value(value: Any, context: RuntimeContext | None) -> Any:
    """转成 JSON 友好值，并避免泄露 runtime path。"""
    if isinstance(value, dict):
        return {
            str(k): _clean_value(v, context)
            for k, v in value.items()
            if str(k) not in {"path", "target_path"}
        }
    if isinstance(value, list | tuple):
        return [_clean_value(item, context) for item in value]
    if isinstance(value, sp.Basic):
        return context.to_answer_value(value) if context is not None else sp.sstr(value)
    if is_dataclass(value):
        return _clean_value(asdict(value), context)
    if isinstance(value, str):
        return value
    if value is None or isinstance(value, bool | int | float):
        return value
    try:
        import json

        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _assert_safe_snapshot(snapshot: ExplanationSnapshot) -> None:
    payload = snapshot.to_payload()
    text = str(payload)
    forbidden = ("$problem.", "$question.", "$subquestion.", "<html", "<svg", "<script")
    hit = next((item for item in forbidden if item in text), None)
    if hit:
        raise ExplanationSnapshotError(f"unsafe explanation snapshot contains {hit}")
