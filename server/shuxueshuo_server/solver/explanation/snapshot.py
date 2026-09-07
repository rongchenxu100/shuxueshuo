"""Build the student-safe, canonical-owner ExplanationSnapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from typing import Any

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
    ProblemPlanningBindingError,
)
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.runtime.projection import RuntimeProjection
from shuxueshuo_server.solver.runtime.recipes.registry import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalGoalPlan,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedStepResultRef,
    scoped_functional_plan_id,
)
from shuxueshuo_server.solver.student_display import student_math_display

from .evidence_projectors import (
    TeachingEvidenceProjectionError,
    TeachingEvidenceProjectorRegistry,
    default_teaching_evidence_projector_registry,
)
from .models import (
    ExplanationSnapshot,
    TeachingGoal,
    TeachingScope,
    TeachingSource,
    iter_teaching_scopes,
    iter_teaching_sources,
)


class ExplanationSnapshotError(RuntimeError):
    """The verified teaching projection is incomplete or inconsistent."""


class ExplanationSnapshotBuilder:
    """Project one successful verified execution into the teaching boundary."""

    def __init__(
        self,
        *,
        evidence_projectors: TeachingEvidenceProjectorRegistry | None = None,
    ) -> None:
        self._evidence_projectors = (
            evidence_projectors
            or default_teaching_evidence_projector_registry()
        )
        self._macro_ids = frozenset(
            RecipeSpecRegistry.load_from_code().specs
        )

    def build(self, artifacts: Any) -> ExplanationSnapshot:
        result = artifacts.solver_result
        if getattr(result, "status", None) != "ok":
            raise ExplanationSnapshotError(
                "explanation snapshot requires ok SolverResult"
            )
        execution = getattr(artifacts, "verified_functional_execution", None)
        if execution is None:
            raise ExplanationSnapshotError(
                "teaching_projection_verified_execution_missing: "
                "ExplanationSnapshot requires VerifiedFunctionalPlanExecution"
            )
        canonical_plan = execution.canonical_plan
        computed_plan_hash = scoped_functional_plan_id(canonical_plan)
        if computed_plan_hash != execution.plan_id:
            raise ExplanationSnapshotError(
                "teaching_projection_plan_hash_drift: verified Plan identity mismatch"
            )

        problem_payload = RuntimeProjection(artifacts.problem).to_llm_problem_payload()
        problem_authority = getattr(artifacts, "problem_authority", None)
        planning_context = getattr(problem_authority, "planning_context", None)
        binding_catalog = getattr(artifacts, "problem_binding_catalog", None)
        if not isinstance(binding_catalog, ProblemPlanningBindingCatalog):
            raise ExplanationSnapshotError(
                "teaching_projection_binding_catalog_missing"
            )
        plan_execution = getattr(artifacts, "execution", None)
        step_execution_results = {
            str(item.step_id): item
            for item in getattr(plan_execution, "step_results", ())
        }
        if len(step_execution_results) != len(
            tuple(_iter_canonical_steps(canonical_plan.root_scope))
        ):
            raise ExplanationSnapshotError(
                "teaching_projection_method_execution_shape_mismatch"
            )
        output_labels = _point_answer_labels_by_result(
            canonical_plan.root_scope,
            problem_payload=problem_payload,
        )
        evidence: dict[str, dict[str, Any]] = {}
        root_scope = _project_scope(
            canonical_plan.root_scope,
            execution.root_scope,
            problem_payload=problem_payload,
            binding_catalog=binding_catalog,
            planning_context=planning_context,
            evidence_projectors=self._evidence_projectors,
            evidence=evidence,
            step_execution_results=step_execution_results,
            macro_ids=self._macro_ids,
            output_labels=output_labels,
        )
        answers = _verified_answers(
            root_scope,
            question_goals=tuple(getattr(artifacts, "question_goals", ())),
        )
        observed_answers = _json_value(getattr(result, "answers", {}))
        answer_runtime_types = _answer_runtime_types(
            root_scope,
            question_goals=tuple(getattr(artifacts, "question_goals", ())),
        )
        if not _answer_payloads_equivalent(
            answers,
            observed_answers,
            runtime_types=answer_runtime_types,
        ):
            raise ExplanationSnapshotError(
                "teaching_projection_answer_mismatch: SolverResult answers do not "
                "match canonical answer_from public results"
            )
        # SolverResult has already passed answer verification and preserves the
        # authored display order for set-like answers.  Public runtime results
        # remain unchanged in each TeachingSource.
        answers = observed_answers

        snapshot = ExplanationSnapshot(
            problem_id=str(artifacts.problem.problem_id),
            family_id=str(getattr(artifacts.family, "family_id", "")),
            problem_revision=execution.problem_revision_id,
            problem_semantic_hash=execution.problem_semantic_hash,
            canonical_plan_hash=execution.plan_id,
            verified_execution_hash=execution.execution_signature,
            problem=problem_payload,
            root_scope=root_scope,
            evidence=evidence,
            answers=answers,
        )
        _assert_safe_snapshot(snapshot)
        return snapshot


def _iter_canonical_steps(
    scope: ScopedFunctionalScope,
) -> Sequence[ScopedFunctionalStep]:
    result: list[ScopedFunctionalStep] = [*scope.steps]
    for goal in scope.goals:
        result.extend(goal.steps)
    for child in scope.children:
        result.extend(_iter_canonical_steps(child))
    return tuple(result)


def _point_answer_labels_by_result(
    root: ScopedFunctionalScope,
    *,
    problem_payload: Mapping[str, Any],
) -> dict[tuple[str, str], str]:
    point_names = {
        str(item.get("name") or "")
        for item in problem_payload.get("entities", ())
        if isinstance(item, Mapping)
        and str(item.get("entity_type") or "") == "point"
        and item.get("name")
    }
    candidates: dict[tuple[str, str], set[str]] = {}

    def visit(scope: ScopedFunctionalScope) -> None:
        for goal in scope.goals:
            label = str(goal.goal_ref).rsplit(".", 1)[-1]
            if label in point_names:
                key = (
                    goal.answer_from.step_id,
                    goal.answer_from.return_name,
                )
                candidates.setdefault(key, set()).add(label)
        for child in scope.children:
            visit(child)

    visit(root)
    return {
        key: next(iter(labels))
        for key, labels in candidates.items()
        if len(labels) == 1
    }


def _project_scope(
    canonical: ScopedFunctionalScope,
    executed: Any,
    *,
    problem_payload: Mapping[str, Any],
    binding_catalog: ProblemPlanningBindingCatalog,
    planning_context: Any | None,
    evidence_projectors: TeachingEvidenceProjectorRegistry,
    evidence: dict[str, dict[str, Any]],
    step_execution_results: Mapping[str, Any],
    macro_ids: frozenset[str],
    output_labels: Mapping[tuple[str, str], str],
) -> TeachingScope:
    if canonical.scope_ref != executed.scope_ref:
        raise ExplanationSnapshotError(
            "teaching_projection_scope_owner_mismatch: "
            f"canonical={canonical.scope_ref}, execution={executed.scope_ref}"
        )
    if len(canonical.steps) != len(executed.scope_steps):
        raise ExplanationSnapshotError(
            f"teaching_projection_scope_step_shape_mismatch: {canonical.scope_ref}"
        )
    if len(canonical.goals) != len(executed.goals):
        raise ExplanationSnapshotError(
            f"teaching_projection_goal_shape_mismatch: {canonical.scope_ref}"
        )
    if len(canonical.children) != len(executed.children):
        raise ExplanationSnapshotError(
            f"teaching_projection_child_shape_mismatch: {canonical.scope_ref}"
        )

    scope_steps = tuple(
        _project_source(
            authored,
            runtime,
            scope_ref=canonical.scope_ref,
            problem_payload=problem_payload,
            binding_catalog=binding_catalog,
            planning_context=planning_context,
            evidence_projectors=evidence_projectors,
            evidence=evidence,
            step_execution_results=step_execution_results,
            macro_ids=macro_ids,
            output_labels=output_labels,
        )
        for authored, runtime in zip(
            canonical.steps,
            executed.scope_steps,
            strict=True,
        )
    )
    goals: list[TeachingGoal] = []
    for authored_goal, runtime_goal in zip(
        canonical.goals,
        executed.goals,
        strict=True,
    ):
        _assert_goal_shape(authored_goal, runtime_goal, canonical.scope_ref)
        goals.append(
            TeachingGoal(
                goal_ref=authored_goal.goal_ref,
                steps=tuple(
                    _project_source(
                        authored,
                        runtime,
                        scope_ref=canonical.scope_ref,
                        problem_payload=problem_payload,
                        binding_catalog=binding_catalog,
                        planning_context=planning_context,
                        evidence_projectors=evidence_projectors,
                        evidence=evidence,
                        step_execution_results=step_execution_results,
                        macro_ids=macro_ids,
                        output_labels=output_labels,
                    )
                    for authored, runtime in zip(
                        authored_goal.steps,
                        runtime_goal.steps,
                        strict=True,
                    )
                ),
                answer_from=authored_goal.answer_from.to_payload(),
            )
        )
    return TeachingScope(
        scope_ref=canonical.scope_ref,
        steps=scope_steps,
        goals=tuple(goals),
        children=tuple(
            _project_scope(
                authored,
                runtime,
                problem_payload=problem_payload,
                binding_catalog=binding_catalog,
                planning_context=planning_context,
                evidence_projectors=evidence_projectors,
                evidence=evidence,
                step_execution_results=step_execution_results,
                macro_ids=macro_ids,
                output_labels=output_labels,
            )
            for authored, runtime in zip(
                canonical.children,
                executed.children,
                strict=True,
            )
        ),
    )


def _assert_goal_shape(
    authored: ScopedFunctionalGoalPlan,
    runtime: Any,
    scope_ref: str,
) -> None:
    if authored.goal_ref != runtime.goal_ref:
        raise ExplanationSnapshotError(
            "teaching_projection_goal_owner_mismatch: "
            f"scope={scope_ref}, canonical={authored.goal_ref}, "
            f"execution={runtime.goal_ref}"
        )
    if runtime.status != "provisionally_solved":
        raise ExplanationSnapshotError(
            f"teaching_projection_goal_not_verified: {runtime.goal_ref}"
        )
    if len(authored.steps) != len(runtime.steps):
        raise ExplanationSnapshotError(
            f"teaching_projection_goal_step_shape_mismatch: {runtime.goal_ref}"
        )


def _project_source(
    authored: ScopedFunctionalStep,
    runtime: Any,
    *,
    scope_ref: str,
    problem_payload: Mapping[str, Any],
    binding_catalog: ProblemPlanningBindingCatalog,
    planning_context: Any | None,
    evidence_projectors: TeachingEvidenceProjectorRegistry,
    evidence: dict[str, dict[str, Any]],
    step_execution_results: Mapping[str, Any],
    macro_ids: frozenset[str],
    output_labels: Mapping[tuple[str, str], str],
) -> TeachingSource:
    if authored.step_id != runtime.step_id:
        raise ExplanationSnapshotError(
            "teaching_projection_step_owner_mismatch: "
            f"canonical={authored.step_id}, execution={runtime.step_id}"
        )
    if dict(runtime.authored_step) != authored.to_payload():
        raise ExplanationSnapshotError(
            f"teaching_projection_authored_step_drift: {authored.step_id}"
        )
    if runtime.status != "runtime_verified":
        raise ExplanationSnapshotError(
            "teaching_projection_unverified_step_forbidden: "
            f"step={authored.step_id}, status={runtime.status}"
        )
    public_results = _public_results(
        runtime.actual_outputs,
        step_id=authored.step_id,
        output_targets=authored.output_targets,
        resolved_output_labels=output_labels,
        student_safe=True,
    )
    calculations: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for item in runtime.evidence:
        try:
            projected = evidence_projectors.project(
                item,
                planning_context=planning_context,
            )
        except TeachingEvidenceProjectionError as exc:
            raise ExplanationSnapshotError(
                f"{exc}: step={authored.step_id}"
            ) from exc
        evidence_ref = projected.evidence_ref
        payload = _json_value(projected.payload)
        previous = evidence.get(evidence_ref)
        if previous is not None and previous != payload:
            raise ExplanationSnapshotError(
                f"teaching_projection_evidence_id_collision: {evidence_ref}"
            )
        evidence[evidence_ref] = payload
        calculations.extend(dict(item) for item in projected.calculations)
        checks.extend(dict(item) for item in projected.checks)
    method_checks = (
        ()
        if authored.capability_id in macro_ids
        else _project_method_checks(
            step_execution_results.get(authored.step_id),
            step_id=authored.step_id,
        )
    )
    return TeachingSource(
        source_step_id=authored.step_id,
        capability_id=authored.capability_id,
        inputs=_project_inputs(
            authored,
            runtime,
            scope_ref=scope_ref,
            problem_payload=problem_payload,
            binding_catalog=binding_catalog,
        ),
        output_targets=dict(authored.output_targets),
        intent=authored.intent,
        outputs=public_results,
        calculations=tuple(calculations),
        checks=(*method_checks, *checks),
    )


def _project_inputs(
    authored: ScopedFunctionalStep,
    runtime: Any,
    *,
    scope_ref: str,
    problem_payload: Mapping[str, Any],
    binding_catalog: ProblemPlanningBindingCatalog,
) -> dict[str, tuple[dict[str, Any], ...]]:
    runtime_items: dict[tuple[str, int], Mapping[str, Any]] = {}
    for raw in runtime.resolved_inputs:
        arg_name = str(raw.get("arg") or "")
        index = raw.get("index")
        if not arg_name or not isinstance(index, int):
            raise ExplanationSnapshotError(
                f"teaching_projection_runtime_input_invalid: {authored.step_id}"
            )
        key = (arg_name, index)
        if key in runtime_items:
            raise ExplanationSnapshotError(
                f"teaching_projection_runtime_input_duplicate: {authored.step_id}"
            )
        runtime_items[key] = raw

    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for arg_name, values in authored.args.items():
        items: list[dict[str, Any]] = []
        for index, authored_value in enumerate(values):
            runtime_item = runtime_items.pop((arg_name, index), None)
            if runtime_item is None:
                raise ExplanationSnapshotError(
                    "teaching_projection_runtime_input_missing: "
                    f"step={authored.step_id}, arg={arg_name}[{index}]"
                )
            ref = _teaching_ref(authored_value)
            resolved_from = _resolved_step_ref(runtime_item.get("resolved_ref"))
            runtime_type = str(runtime_item.get("runtime_type") or "")
            value = runtime_item.get("value", _MISSING)
            if value is _MISSING and ref["kind"] == "source":
                runtime_type, value = _problem_source_value(
                    local_ref=str(ref["ref"]),
                    scope_ref=scope_ref,
                    problem_payload=problem_payload,
                    binding_catalog=binding_catalog,
                    runtime_type=runtime_type,
                )
            if value is _MISSING or not runtime_type:
                raise ExplanationSnapshotError(
                    "teaching_projection_runtime_input_incomplete: "
                    f"step={authored.step_id}, arg={arg_name}[{index}]"
                )
            value = _student_safe_runtime_value(_json_value(value))
            if ref["kind"] == "source" and resolved_from is None:
                value = _student_safe_problem_source_value(
                    value,
                    runtime_type=runtime_type,
                )
            _assert_public_value(
                value,
                path=f"step={authored.step_id}.inputs.{arg_name}[{index}].value",
            )
            item = {
                "ref": ref,
                "runtime_type": runtime_type,
                "value": value,
                "display": _display_value(
                    value,
                    runtime_type=runtime_type,
                    label=(
                        str(ref.get("ref") or "")
                        if ref["kind"] == "source"
                        else None
                    ),
                ),
            }
            if resolved_from is not None:
                item["resolved_from"] = resolved_from
            items.append(item)
        result[arg_name] = tuple(items)
    if runtime_items:
        raise ExplanationSnapshotError(
            "teaching_projection_runtime_input_shape_drift: "
            f"step={authored.step_id}, extras={sorted(runtime_items)}"
        )
    return result


_MISSING = object()


def _teaching_ref(value: Any) -> dict[str, str]:
    if isinstance(value, ScopedStepResultRef):
        return {
            "kind": "step_result",
            "step_id": value.step_id,
            "return": value.return_name,
        }
    if isinstance(value, str) and value:
        return {"kind": "source", "ref": value}
    raise ExplanationSnapshotError(
        "teaching_projection_authored_input_ref_invalid"
    )


def _resolved_step_ref(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"step_id", "return"}:
        raise ExplanationSnapshotError(
            "teaching_projection_resolved_step_ref_invalid"
        )
    step_id = str(value.get("step_id") or "")
    return_name = str(value.get("return") or "")
    if not step_id or not return_name:
        raise ExplanationSnapshotError(
            "teaching_projection_resolved_step_ref_invalid"
        )
    return {
        "kind": "step_result",
        "step_id": step_id,
        "return": return_name,
    }


def _problem_source_value(
    *,
    local_ref: str,
    scope_ref: str,
    problem_payload: Mapping[str, Any],
    binding_catalog: ProblemPlanningBindingCatalog,
    runtime_type: str,
) -> tuple[str, Any]:
    try:
        binding = binding_catalog.resolve_input_binding(
            scope_id=scope_ref,
            local_ref=local_ref,
        )
    except ProblemPlanningBindingError as exc:
        raise ExplanationSnapshotError(
            "teaching_projection_problem_input_binding_unresolved: "
            f"scope={scope_ref}, ref={local_ref}"
        ) from exc
    types = tuple(
        sorted(
            {
                str(item.runtime_type)
                for item in binding.typed_sources
                if item.runtime_type
            }
        )
    )
    if not runtime_type and len(types) == 1:
        runtime_type = types[0]
    if not runtime_type:
        runtime_type = str(binding.semantic_ref.value_type or "") or {
            "symbol": "Symbol",
            "point": "Point",
            "function": "Parabola",
            "line": "Line",
        }.get(str(binding.semantic_ref.kind), str(binding.semantic_ref.kind))
    matches = [
        dict(item)
        for collection in ("entities", "facts")
        for item in problem_payload.get(collection, ())
        if isinstance(item, Mapping)
        and str(item.get("handle") or "") == binding.runtime_node_id
    ]
    if len(matches) > 1 or not runtime_type:
        raise ExplanationSnapshotError(
            "teaching_projection_problem_input_value_unresolved: "
            f"scope={scope_ref}, ref={local_ref}, node={binding.runtime_node_id}"
        )
    # Some canonical symbolic identities (for example a free coefficient)
    # have no separate ProblemIR entity row.  Their exact public value is the
    # verified semantic ref itself; no internal MathObjectId is projected.
    return runtime_type, matches[0] if matches else binding.semantic_ref.ref


_PROBLEM_SOURCE_PRIVATE_KEYS = frozenset(
    {
        "handle",
        "math_object_id",
        "runtime_node_id",
        "scope_id",
        "valid_scope",
    }
)
_PUBLIC_REFERENCE_PREFIXES = frozenset(
    {
        "fact",
        "function",
        "line",
        "point",
        "polygon",
        "segment",
        "symbol",
    }
)


def _student_safe_problem_source_value(
    value: Any,
    *,
    runtime_type: str,
) -> Any:
    """Remove canonical binding identities while preserving public mathematics."""

    projected = _student_safe_problem_value(value)
    if (
        runtime_type in {"ParameterValue", "Symbol"}
        and isinstance(projected, Mapping)
        and str(projected.get("entity_type") or "") == "symbol"
        and projected.get("name") not in (None, "")
    ):
        return str(projected["name"])
    return projected


def _student_safe_problem_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _student_safe_problem_value(item)
            for key, item in value.items()
            if str(key) not in _PROBLEM_SOURCE_PRIVATE_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_student_safe_problem_value(item) for item in value]
    if isinstance(value, str):
        parts = value.split(":")
        if len(parts) >= 3 and parts[0] in _PUBLIC_REFERENCE_PREFIXES:
            return parts[-1]
    return value


def _display_value(
    value: Any,
    *,
    runtime_type: str,
    label: str | None = None,
) -> str:
    safe_label = (label or "").rsplit(".", 1)[-1]
    if runtime_type == "Point" and isinstance(value, (list, tuple)) and len(value) == 2:
        coordinate = f"({student_math_display(value[0])},{student_math_display(value[1])})"
        return f"{safe_label}{coordinate}" if safe_label else coordinate
    if runtime_type == "PointList" and isinstance(value, (list, tuple)):
        return "，".join(
            _display_value(item, runtime_type="Point") for item in value
        )
    if isinstance(value, Mapping):
        if runtime_type == "path_minimum_target" and value.get("path"):
            return student_math_display(value["path"])
        if runtime_type == "square" and isinstance(value.get("vertices"), list):
            vertices = "".join(str(item) for item in value["vertices"])
            return f"正方形 {vertices}"
        if (
            runtime_type == "minimum_value"
            and value.get("path")
            and value.get("value") is not None
        ):
            return student_math_display(f"{value['path']}={value['value']}")
        for key in ("display", "expression", "equation", "name", "description"):
            if value.get(key) not in (None, ""):
                return student_math_display(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    rendered = student_math_display(value)
    if not rendered:
        raise ExplanationSnapshotError(
            "teaching_projection_display_value_empty"
        )
    return rendered


def _public_results(
    outputs: Sequence[Mapping[str, Any]],
    *,
    step_id: str,
    output_targets: Mapping[str, str],
    resolved_output_labels: Mapping[tuple[str, str], str],
    student_safe: bool,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, output in enumerate(outputs):
        return_name = str(output.get("return") or "")
        if not return_name or return_name in result:
            raise ExplanationSnapshotError(
                "teaching_projection_runtime_output_invalid: "
                f"step={step_id}, index={index}, missing_or_duplicate_return"
            )
        runtime_type = str(output.get("runtime_type") or "")
        if not runtime_type or "value" not in output or "value_omitted_reason" in output:
            raise ExplanationSnapshotError(
                "teaching_projection_runtime_output_incomplete: "
                f"step={step_id}, return={return_name}"
            )
        value = _json_value(output["value"])
        if student_safe:
            value = _student_safe_runtime_value(value)
            _assert_public_value(
                value,
                path=f"step={step_id}.public_results.{return_name}.value",
            )
        result[return_name] = {
            "runtime_type": runtime_type,
            "value": value,
            "display": _display_value(
                value,
                runtime_type=runtime_type,
                label=(
                    output_targets.get(return_name)
                    or resolved_output_labels.get((step_id, return_name))
                ),
            ),
        }
    return result


def _project_method_checks(
    execution_step: Any,
    *,
    step_id: str,
) -> tuple[dict[str, Any], ...]:
    if execution_step is None:
        raise ExplanationSnapshotError(
            f"teaching_projection_method_execution_missing: {step_id}"
        )
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in getattr(execution_step, "checks", ()):
        check_id = str(getattr(item, "name", "") or "")
        if not check_id or check_id in seen:
            raise ExplanationSnapshotError(
                f"teaching_projection_method_check_identity_invalid: {step_id}"
            )
        seen.add(check_id)
        projected.append(
            {
                "check_id": check_id,
                "kind": "runtime_method_check",
                "passed": str(getattr(item, "status", "")) == "passed",
                "detail": str(getattr(item, "detail", "") or check_id),
            }
        )
    return tuple(projected)


def _verified_answers(
    root: TeachingScope,
    *,
    question_goals: tuple[Any, ...],
) -> dict[str, Any]:
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(root)
    }
    goal_authority = {
        str(getattr(goal, "id", "")): goal
        for goal in question_goals
    }
    answers: dict[str, dict[str, Any]] = {}
    seen_goal_refs: set[str] = set()
    for scope in iter_teaching_scopes(root):
        for goal in scope.goals:
            authority = goal_authority.get(goal.goal_ref)
            if authority is None:
                raise ExplanationSnapshotError(
                    f"teaching_projection_question_goal_missing: {goal.goal_ref}"
                )
            source = sources.get(str(goal.answer_from.get("step_id") or ""))
            return_name = str(goal.answer_from.get("return") or "")
            runtime_result = (
                source.public_results.get(return_name)
                if source is not None
                else None
            )
            if runtime_result is None:
                raise ExplanationSnapshotError(
                    "teaching_projection_answer_source_missing: "
                    f"goal={goal.goal_ref}, answer_from={dict(goal.answer_from)}"
                )
            question_id = str(getattr(authority, "question_id", ""))
            answer_key = str(getattr(authority, "answer_key", ""))
            if not question_id or not answer_key:
                raise ExplanationSnapshotError(
                    f"teaching_projection_question_goal_invalid: {goal.goal_ref}"
                )
            answers.setdefault(question_id, {})[answer_key] = _json_value(
                runtime_result["value"]
            )
            seen_goal_refs.add(goal.goal_ref)
    missing = sorted(set(goal_authority) - seen_goal_refs)
    if missing:
        raise ExplanationSnapshotError(
            f"teaching_projection_canonical_goals_missing: {missing}"
        )
    return answers


def _answer_runtime_types(
    root: TeachingScope,
    *,
    question_goals: tuple[Any, ...],
) -> dict[tuple[str, str], str]:
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(root)
    }
    goal_authority = {
        str(getattr(goal, "id", "")): goal
        for goal in question_goals
    }
    result: dict[tuple[str, str], str] = {}
    for scope in iter_teaching_scopes(root):
        for goal in scope.goals:
            authority = goal_authority.get(goal.goal_ref)
            source = sources.get(str(goal.answer_from.get("step_id") or ""))
            return_name = str(goal.answer_from.get("return") or "")
            runtime_result = (
                source.public_results.get(return_name)
                if source is not None
                else None
            )
            if authority is None or runtime_result is None:
                continue
            result[
                (
                    str(getattr(authority, "question_id", "")),
                    str(getattr(authority, "answer_key", "")),
                )
            ] = str(runtime_result.get("runtime_type") or "")
    return result


def _answer_payloads_equivalent(
    derived: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    runtime_types: Mapping[tuple[str, str], str],
) -> bool:
    if set(derived) != set(observed):
        return False
    for question_id, expected_answers in derived.items():
        actual_answers = observed.get(question_id)
        if not isinstance(expected_answers, Mapping) or not isinstance(
            actual_answers,
            Mapping,
        ):
            return False
        if set(expected_answers) != set(actual_answers):
            return False
        for answer_key, expected in expected_answers.items():
            actual = actual_answers[answer_key]
            runtime_type = runtime_types.get((str(question_id), str(answer_key)), "")
            if runtime_type == "PointList":
                if not _unordered_json_sequence_equal(expected, actual):
                    return False
            elif expected != actual:
                return False
    return True


def _unordered_json_sequence_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    return sorted(
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in left
    ) == sorted(
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in right
    )


def _assert_public_value(value: Any, *, path: str) -> None:
    internal_keys = {
        "handle",
        "math_object_id",
        "runtime_node_id",
        "scope_id",
        "valid_scope",
        "state_version",
        "state_version_id",
        "checkpoint_id",
        "transaction_id",
        "runtime_path",
        "target_path",
        "provenance_signature",
    }
    if isinstance(value, Mapping):
        hit = next((str(key) for key in value if str(key) in internal_keys), None)
        if hit is not None:
            raise ExplanationSnapshotError(
                f"teaching_projection_internal_identity_forbidden: {path}.{hit}"
            )
        for key, item in value.items():
            _assert_public_value(item, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _assert_public_value(item, path=f"{path}[{index}]")
    if contains_private_path_projection_marker(value):
        raise ExplanationSnapshotError(
            f"teaching_projection_private_macro_value_forbidden: {path}"
        )


def _json_value(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ExplanationSnapshotError(
            "teaching_projection_value_not_json_safe"
        ) from exc


_INTERNAL_AXIS_PARAMETER = re.compile(
    r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+"
)


def _student_safe_runtime_value(value: Any) -> Any:
    """Give anonymous runtime parameters a public, local mathematical name."""

    if isinstance(value, Mapping):
        return {
            str(key): _student_safe_runtime_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_student_safe_runtime_value(item) for item in value]
    if isinstance(value, str):
        return _INTERNAL_AXIS_PARAMETER.sub("t", value)
    return value


def _assert_safe_snapshot(snapshot: ExplanationSnapshot) -> None:
    payload = snapshot.to_payload()
    text = json.dumps(payload, ensure_ascii=False)
    forbidden = (
        "$problem.",
        "$question.",
        "$subquestion.",
        "<html",
        "<svg",
        "<script",
        "execution_scope_id",
        "presentation_scope_id",
        "student_step_placements",
        "student_scope_references",
        "raw_response",
        "expected_answer",
        "return_expectations",
        "_axis_param_",
    )
    hit = next((item for item in forbidden if item in text), None)
    if hit:
        raise ExplanationSnapshotError(
            f"unsafe explanation snapshot contains {hit}"
        )
    if contains_private_path_projection_marker(payload):
        raise ExplanationSnapshotError(
            "unsafe explanation snapshot contains private Macro projection"
        )
