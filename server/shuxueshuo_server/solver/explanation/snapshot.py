"""从成功 runtime run 构建 ExplanationSnapshot。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

import sympy as sp

from shuxueshuo_server.solver.contracts import PointRef, TypedValue
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import PlanExecutionResult, PlannerOutput, StepPlan
from shuxueshuo_server.solver.runtime.projection import RuntimeProjection
from shuxueshuo_server.solver.runtime.strategy_models import (
    canonical_symbolic_expression,
)

from .models import (
    ExplanationSnapshot,
    SymbolicClosureTeachingTrace,
    TeachingTraceEntry,
)
from .presentation import (
    StudentNarrativePlacementProjector,
    transactional_functional_steps,
)


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
        problem_payload = RuntimeProjection(artifacts.problem).to_llm_problem_payload()
        replay = getattr(planner_artifacts, "retry_replay_result", None)
        functional_reconciliation = getattr(replay, "functional_reconciliation", None)
        runtime_effective_steps = transactional_functional_steps(
            replay,
            artifacts.planner_output,
        )
        macro_evidence = _build_macro_evidence(
            artifacts,
            problem_payload=problem_payload,
        )
        problem_authority = getattr(artifacts, "problem_authority", None)
        planning_context = getattr(problem_authority, "planning_context", None)
        prompt_handles_by_ref = {
            authority.semantic_ref.ref: authority.runtime_node_id
            for authority in getattr(
                planning_context,
                "ref_authorities",
                {},
            ).values()
            if authority.usage == "input"
        }
        effective_steps = _macro_presentation_steps(
            runtime_effective_steps,
            macro_evidence,
            prompt_handles_by_ref=prompt_handles_by_ref,
        )
        effective_fact_steps: tuple[Any, ...] = runtime_effective_steps
        if not effective_steps:
            raise ExplanationSnapshotError(
                "strategy planner verified execution steps are required"
            )
        narrative = StudentNarrativePlacementProjector().project(
            effective_steps=effective_steps,
            problem=problem_payload,
            functional_reconciliation=functional_reconciliation,
            raw_functional_plan=getattr(replay, "functional_plan", None),
        )
        step_capabilities = {
            str(step["step_id"]): str(
                step.get("recipe_hint") or step.get("goal_type")
            )
            for step in effective_steps
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
                macro_evidence=macro_evidence,
            ),
            fact_index=_build_fact_index(
                artifacts.context,
                effective_fact_steps,
                macro_evidence=macro_evidence,
            ),
            student_step_placements=narrative.placements,
            student_scope_references=narrative.references,
            planner_insights=_planner_insights(planner_artifacts),
            answers=_clean_value(result.answers, artifacts.context),
            checks=tuple(_check_payload(check) for check in result.checks),
            symbolic_closures=_build_symbolic_closure_teaching(replay),
            macro_evidence=macro_evidence,
        )
        _assert_safe_snapshot(snapshot)
        return snapshot


def _build_macro_evidence(
    artifacts: Any,
    *,
    problem_payload: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Project Macro provenance from expansion records and ordinary steps."""

    execution = getattr(artifacts, "verified_functional_execution", None)
    records = tuple(getattr(artifacts, "macro_expansions", ()))
    if execution is None or not records:
        return ()
    problem_authority = getattr(artifacts, "problem_authority", None)
    planning_context = getattr(problem_authority, "planning_context", None)
    prompt_refs = {
        authority.runtime_node_id: authority.semantic_ref.ref
        for authority in getattr(planning_context, "ref_authorities", {}).values()
        if authority.usage == "input"
    }
    step_index: dict[str, tuple[Any, str]] = {}
    for scope in _execution_scopes(execution.root_scope):
        for step in scope.scope_steps:
            step_index[step.step_id] = (step, scope.scope_ref)
        for goal in scope.goals:
            for step in goal.steps:
                step_index[step.step_id] = (step, scope.scope_ref)
    evidence = [
        _macro_expansion_teaching_projection(
            record,
            step_index=step_index,
            prompt_refs=prompt_refs,
            problem_facts=tuple(problem_payload.get("facts", ())),
        )
        for record in records
    ]
    return tuple(
        sorted(
            evidence,
            key=lambda item: (
                str(item.get("step_id", "")),
                str(item.get("schema_version", "")),
            ),
        )
    )


def _macro_presentation_steps(
    execution_steps: tuple[dict[str, Any], ...],
    macro_evidence: tuple[dict[str, Any], ...],
    *,
    prompt_handles_by_ref: Mapping[str, str],
) -> tuple[dict[str, Any], ...]:
    """Collapse generated steps only in the explanation-facing projection."""

    if not macro_evidence:
        return execution_steps
    step_by_id = {str(step.get("step_id") or ""): step for step in execution_steps}
    generated_to_macro: dict[str, dict[str, Any]] = {}
    presentations: dict[str, dict[str, Any]] = {}
    for evidence in macro_evidence:
        generated_ids = tuple(
            str(item)
            for item in evidence.get("generated_step_ids", ())
            if str(item)
        )
        if not generated_ids:
            raise ExplanationSnapshotError(
                "Macro explanation projection has no generated steps"
            )
        generated_steps = []
        for step_id in generated_ids:
            if step_id in generated_to_macro:
                raise ExplanationSnapshotError(
                    "Macro explanation projections overlap on a generated step"
                )
            step = step_by_id.get(step_id)
            if step is None:
                raise ExplanationSnapshotError(
                    "Macro explanation projection cannot find generated step: "
                    f"{step_id}"
                )
            generated_to_macro[step_id] = evidence
            generated_steps.append(step)

        def collect(key: str) -> list[Any]:
            result: list[Any] = []
            seen: set[str] = set()
            for step in generated_steps:
                for item in step.get(key, ()):
                    marker = repr(item)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    result.append(item)
            return result

        internal_handles = {
            str(item.get("handle") or "")
            for key in ("creates", "produces")
            for item in collect(key)
            if isinstance(item, Mapping) and item.get("handle")
        }
        authored_reads = [
            prompt_handles_by_ref[ref]
            for refs in evidence.get("authored_input_refs", {}).values()
            for ref in refs
            if ref in prompt_handles_by_ref
        ]
        reads = list(dict.fromkeys(authored_reads + [
            item
            for item in collect("reads")
            if str(item) not in internal_handles
        ]))
        macro_step_id = str(evidence.get("step_id") or "")
        macro_id = str(evidence.get("macro_id") or "")
        if not macro_step_id or not macro_id:
            raise ExplanationSnapshotError(
                "Macro explanation projection is missing its public identity"
            )
        presentations[macro_step_id] = {
            "scope_id": str(evidence.get("scope_id") or "problem"),
            "step_id": macro_step_id,
            "recipe_hint": macro_id,
            "goal_type": macro_id,
            "target": generated_steps[-1].get("target"),
            "strategy": str(evidence.get("minimum_strategy") or ""),
            "reads": reads,
            "creates": collect("creates"),
            "produces": collect("produces"),
            "reason": "",
        }

    projected: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for step in execution_steps:
        step_id = str(step.get("step_id") or "")
        evidence = generated_to_macro.get(step_id)
        if evidence is None:
            projected.append(step)
            continue
        macro_step_id = str(evidence.get("step_id") or "")
        if macro_step_id not in emitted:
            projected.append(presentations[macro_step_id])
            emitted.add(macro_step_id)
    return tuple(projected)


def _macro_expansion_teaching_projection(
    record: Any,
    *,
    step_index: Mapping[str, tuple[Any, str]],
    prompt_refs: Mapping[str, str],
    problem_facts: tuple[Any, ...],
) -> dict[str, Any]:
    """Build a student view without inventing a second execution object."""

    generated = [step_index[step_id] for step_id in record.generated_step_ids]
    authored_steps = [dict(step.authored_step) for step, _scope in generated]
    function_ids = tuple(
        str(step.get("capability_id") or "") for step in authored_steps
    )
    if "reflect_point_across_line" in function_ids:
        minimum_strategy = "reflection_straightening"
    elif any("endpoint" in item for item in function_ids):
        minimum_strategy = "segment_endpoint"
    else:
        minimum_strategy = "direct_intersection"
    checks = tuple(
        {
            "check": capability_id,
            "passed": execution_step.status == "runtime_verified",
        }
        for (execution_step, _scope), capability_id in zip(
            generated,
            function_ids,
            strict=True,
        )
    )
    proved_checks = tuple(item["check"] for item in checks if item["passed"])

    export_step_id, export_return = record.export_map["minimum_expression"]
    export_step = step_index[export_step_id][0]
    export_output = next(
        (
            item
            for item in export_step.actual_outputs
            if item.get("return") == export_return
        ),
        {},
    )
    minimum_expression = str(export_output.get("value", ""))

    constructions: list[dict[str, Any]] = []
    for (execution_step, scope_id), authored in zip(
        generated,
        authored_steps,
        strict=True,
    ):
        bindings = authored.get("return_bindings", {})
        if not isinstance(bindings, Mapping):
            continue
        for output in execution_step.actual_outputs:
            if output.get("runtime_type") != "Point":
                continue
            value = output.get("value")
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                continue
            binding = bindings.get(str(output.get("return") or ""), {})
            ref = binding.get("ref") if isinstance(binding, Mapping) else None
            semantic_role = record.generated_return_roles.get(
                execution_step.step_id,
                {},
            ).get(str(output.get("return") or ""))
            constructions.append(
                {
                    "ref": str(ref or ""),
                    "domain_type": "Point",
                    "semantic_role": semantic_role or str(
                        output.get("return") or "point"
                    ),
                    "owner_scope": scope_id,
                    "producer_step_id": execution_step.step_id,
                    "capability_id": str(authored.get("capability_id") or ""),
                    "coordinate": {"x": value[0], "y": value[1]},
                }
            )

    def prompt_ref(value: str) -> str:
        projected = prompt_refs.get(value, value)
        if ":" in projected:
            raise ExplanationSnapshotError(
                "Macro expansion Entity cannot be projected to a prompt ref"
            )
        return projected

    original_objective = _macro_path_objective(
        record,
        problem_facts=problem_facts,
        prompt_refs=prompt_refs,
        scope_id=generated[0][1],
    )
    return {
        "schema_version": "macro-expansion-teaching-projection/v1",
        "step_id": record.macro_step_id,
        "scope_id": generated[0][1],
        "macro_id": record.macro_id,
        "authored_input_refs": {
            name: list(refs)
            for name, refs in record.authored_input_refs.items()
        },
        "generated_step_ids": list(record.generated_step_ids),
        "exports": {
            name: {"step_id": producer, "return": return_name}
            for name, (producer, return_name) in record.export_map.items()
        },
        "function_steps": [
            {
                "step_id": execution_step.step_id,
                "capability_id": str(authored.get("capability_id") or ""),
                "input_names": sorted(authored.get("args", {})),
                "output_names": sorted(authored.get("return_bindings", {})),
            }
            for (execution_step, _scope), authored in zip(
                generated,
                authored_steps,
                strict=True,
            )
        ],
        "original_objective": original_objective,
        "reduced_objective": "",
        "role_resolutions": [
            {
                "role": role,
                "authored_ref": (
                    prompt_ref(record.authored_roles[role])
                    if role in record.authored_roles
                    else None
                ),
                "chosen_ref": prompt_ref(chosen_ref),
                "corrected": (
                    role in record.authored_roles
                    and record.authored_roles[role] != chosen_ref
                ),
            }
            for role, chosen_ref in record.chosen_roles.items()
        ],
        "constructions": constructions,
        "equivalence_proof": list(proved_checks),
        "legal_domain": list(proved_checks),
        "minimum_strategy": minimum_strategy,
        "minimum_expression": minimum_expression,
        "minimizing_points": {},
        "attainment_checks": [
            {
                "strategy": minimum_strategy,
                "feasible": all(item["passed"] for item in checks),
                "checks": list(checks),
            }
        ],
        "repair_action": "reuse_verified_macro_steps",
    }


def _macro_path_objective(
    record: Any,
    *,
    problem_facts: tuple[Any, ...],
    prompt_refs: Mapping[str, str],
    scope_id: str,
) -> str:
    refs = tuple(record.authored_input_refs.get("path_minimum_target", ()))
    if len(refs) != 1:
        return ""
    ref = refs[0]
    candidates = [
        fact
        for fact in problem_facts
        if isinstance(fact, Mapping)
        and (
            str(fact.get("handle") or "") == ref
            or prompt_refs.get(str(fact.get("handle") or "")) == ref
            or str(fact.get("type") or "") == ref
        )
        and str(fact.get("scope_id") or fact.get("valid_scope") or "problem")
        in {"problem", scope_id}
    ]
    if len(candidates) != 1:
        return ""
    return str(candidates[0].get("path") or "")


def _execution_scopes(root: Any) -> tuple[Any, ...]:
    result: list[Any] = []

    def visit(scope: Any) -> None:
        result.append(scope)
        for child in scope.children:
            visit(child)

    visit(root)
    return tuple(result)


def _build_teaching_trace(
    planner_output: PlannerOutput,
    execution: PlanExecutionResult,
    step_capabilities: dict[str, str],
    *,
    macro_evidence: tuple[dict[str, Any], ...] = (),
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
    traced_step_ids = {item.source_step_id for item in entries}
    for evidence in macro_evidence:
        source_step_id = str(evidence.get("step_id") or "")
        if not source_step_id or source_step_id in traced_step_ids:
            continue
        scope_id = str(evidence.get("scope_id") or "problem")
        macro_id = str(evidence.get("macro_id") or "macro")
        checks = tuple(
            str(item.get("check") or "")
            for group in evidence.get("attainment_checks", ())
            if isinstance(group, Mapping)
            for item in group.get("checks", ())
            if isinstance(item, Mapping) and item.get("passed")
        )
        for index, function_step in enumerate(
            evidence.get("function_steps", ())
        ):
            if not isinstance(function_step, Mapping):
                continue
            function_id = str(
                function_step.get("capability_id") or "verified_function"
            )
            entries.append(
                TeachingTraceEntry(
                    trace_id=(
                        f"trace:{source_step_id}:fragment:{index}:{function_id}"
                    ),
                    source_step_id=source_step_id,
                    scope_id=scope_id,
                    capability_id=macro_id,
                    method_id=function_id,
                    input_slots=tuple(
                        str(item)
                        for item in function_step.get("input_names", ())
                    ),
                    output_slots=tuple(
                        str(item)
                        for item in function_step.get("output_names", ())
                    ),
                    checks=checks,
                    trace_fragments=(),
                    hidden_reason=None,
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


def _build_symbolic_closure_teaching(
    replay: Any | None,
) -> tuple[SymbolicClosureTeachingTrace, ...]:
    attempt = getattr(replay, "transactional_attempt_result", None)
    reconciliation = getattr(replay, "functional_reconciliation", None)
    if attempt is None or reconciliation is None:
        return ()
    goal_calls = set(getattr(attempt, "goal_reachable_call_ids", ()))
    call_by_step = {
        item.call_id: item.canonical_call_id
        for item in getattr(reconciliation, "execution_entries", ())
    }
    grouped: dict[tuple[Any, ...], list[Any]] = {}
    call_by_signature: dict[tuple[Any, ...], str] = {}
    for write in getattr(attempt, "state_writes", ()):
        provenance = getattr(
            write,
            "symbolic_closure_provenance",
            None,
        )
        if provenance is None or provenance.status != "unique":
            continue
        call_id = (
            write.canonical_producer_call_id
            or call_by_step.get(write.step_id)
        )
        if call_id is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.symbolic_closure_explanation_projection_missing: "
                f"step={write.step_id}, return={write.return_name}"
            )
        if call_id not in goal_calls:
            continue
        signature = provenance.semantic_signature()
        grouped.setdefault(signature, []).append(write)
        call_by_signature.setdefault(signature, call_id)
    result: list[SymbolicClosureTeachingTrace] = []
    for signature, writes in grouped.items():
        provenance = writes[0].symbolic_closure_provenance
        assert provenance is not None
        target = (
            _student_semantic_ref(provenance.target_object_id.value)
            if provenance.target_object_id is not None
            else "parameter"
        )
        result.append(
            SymbolicClosureTeachingTrace(
                source_call_id=call_by_signature[signature],
                target=target,
                target_value=canonical_symbolic_expression(
                    provenance.target_value
                ),
                equation_sources=tuple(
                    _student_semantic_ref(item)
                    for item in provenance.equation_sources
                ),
                known_substitutions=tuple(
                    (
                        _student_semantic_ref(symbol_id.value),
                        value,
                    )
                    for symbol_id, value in provenance.substitutions
                    if symbol_id != provenance.target_object_id
                ),
                constraint_summary=(
                    "structured_constraint_applied"
                    if provenance.constraint_filter is not None
                    else None
                ),
                branch_count=provenance.branch_count,
                residual_symbols=tuple(
                    _student_semantic_ref(item.value)
                    for item in provenance.residual_symbol_ids
                ),
                affected_returns=tuple(provenance.affected_returns),
                state_updates=tuple(
                    {
                        "return": write.return_name,
                        "type": write.runtime_type,
                        "form": write.result_form,
                        "free": [
                            _student_semantic_ref(item.value)
                            for item in write.free_symbol_ids
                        ],
                    }
                    for write in writes
                    if write.return_name is not None
                ),
            )
        )
    return tuple(result)


def _student_semantic_ref(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def _build_fact_index(
    context: RuntimeContext,
    effective_steps: tuple[Any, ...],
    *,
    macro_evidence: tuple[dict[str, Any], ...] = (),
) -> dict[str, dict[str, Any]]:
    """建立讲解可用 fact index，不输出 ContextPath。"""
    index: dict[str, dict[str, Any]] = {}
    for step in effective_steps:
        step_id = (
            str(step.get("step_id"))
            if isinstance(step, dict)
            else step.step_id
        )
        produced_items = (
            step.get("produces", ())
            if isinstance(step, dict)
            else step.produces
        )
        for produced in produced_items:
            handle = (
                str(produced.get("handle"))
                if isinstance(produced, dict)
                else produced.handle
            )
            index[handle] = {
                "handle": handle,
                "scope_id": (
                    produced.get("valid_scope")
                    if isinstance(produced, dict)
                    else produced.valid_scope
                ),
                "type": (
                    produced.get("output_type")
                    if isinstance(produced, dict)
                    else produced.output_type
                ),
                "description": (
                    produced.get("description", "")
                    if isinstance(produced, dict)
                    else produced.description
                ),
                "source_step_id": step_id,
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
    for evidence in macro_evidence:
        source_step_id = str(evidence.get("step_id") or "")
        for construction in evidence.get("constructions", ()):
            if not isinstance(construction, Mapping):
                continue
            coordinate = construction.get("coordinate")
            if (
                construction.get("domain_type") != "Point"
                or not isinstance(coordinate, Mapping)
            ):
                continue
            local_ref = str(construction.get("ref") or "")
            if not local_ref:
                continue
            index[local_ref] = {
                "handle": local_ref,
                "scope_id": str(
                    construction.get("owner_scope")
                    or evidence.get("scope_id")
                    or "problem"
                ),
                "name": str(construction.get("semantic_role") or ""),
                "semantic_role": str(
                    construction.get("semantic_role") or ""
                ),
                "type": "Point",
                "value": [coordinate.get("x"), coordinate.get("y")],
                "source_step_id": source_step_id,
                "producer_step_id": str(
                    construction.get("producer_step_id") or ""
                ),
                "source": str(construction.get("capability_id") or ""),
                "authority": "macro_expansion",
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
