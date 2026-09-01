"""Build the student-safe, canonical-owner ExplanationSnapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumPromptWitnessProjector,
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.runtime.projection import RuntimeProjection
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalGoalPlan,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedStepResultRef,
    scoped_functional_plan_id,
)

from .models import (
    ExplanationSnapshot,
    TeachingCrossScopeReference,
    TeachingGoal,
    TeachingScope,
    TeachingSource,
    iter_teaching_scopes,
    iter_teaching_sources,
    teaching_source_owners,
)


class ExplanationSnapshotError(RuntimeError):
    """The verified teaching projection is incomplete or inconsistent."""


class ExplanationSnapshotBuilder:
    """Project one successful verified execution into the teaching boundary."""

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
        evidence: dict[str, dict[str, Any]] = {}
        root_scope = _project_scope(
            canonical_plan.root_scope,
            execution.root_scope,
            planning_context=planning_context,
            evidence=evidence,
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
            cross_scope_references=_cross_scope_references(
                root_scope,
                dependency_graph=execution.dependency_graph,
                public_result_dependencies=(
                    execution.public_result_dependencies
                ),
            ),
            evidence=evidence,
            answers=answers,
        )
        _assert_safe_snapshot(snapshot)
        return snapshot


def _project_scope(
    canonical: ScopedFunctionalScope,
    executed: Any,
    *,
    planning_context: Any | None,
    evidence: dict[str, dict[str, Any]],
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
            planning_context=planning_context,
            evidence=evidence,
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
                        planning_context=planning_context,
                        evidence=evidence,
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
        scope_steps=scope_steps,
        goals=tuple(goals),
        children=tuple(
            _project_scope(
                authored,
                runtime,
                planning_context=planning_context,
                evidence=evidence,
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
    planning_context: Any | None,
    evidence: dict[str, dict[str, Any]],
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
    )
    evidence_refs: list[str] = []
    checks: list[dict[str, Any]] = []
    for item in runtime.evidence:
        if not isinstance(item, PathMinimumWitness):
            raise ExplanationSnapshotError(
                "teaching_projection_evidence_projector_missing: "
                f"step={authored.step_id}, evidence={type(item).__name__}"
            )
        if planning_context is None:
            raise ExplanationSnapshotError(
                "teaching_projection_planning_context_missing: "
                f"step={authored.step_id}"
            )
        projected = PathMinimumPromptWitnessProjector().project(
            item,
            planning_context,
        ).to_payload()
        evidence_ref = f"path-minimum:{item.witness_id}"
        previous = evidence.get(evidence_ref)
        if previous is not None and previous != projected:
            raise ExplanationSnapshotError(
                f"teaching_projection_evidence_id_collision: {evidence_ref}"
            )
        evidence[evidence_ref] = projected
        evidence_refs.append(evidence_ref)
        checks.extend(_witness_checks(projected))
    return TeachingSource(
        source_step_id=authored.step_id,
        capability_id=authored.capability_id,
        args={
            name: _authored_arg_payload(values)
            for name, values in authored.args.items()
        },
        output_targets=dict(authored.output_targets),
        return_expectations=dict(authored.return_expectations),
        intent=authored.intent,
        public_results=public_results,
        checks=tuple(checks),
        evidence_refs=tuple(evidence_refs),
    )


def _authored_arg_payload(values: Sequence[Any]) -> Any:
    projected = [
        item.to_payload() if isinstance(item, ScopedStepResultRef) else item
        for item in values
    ]
    return projected[0] if len(projected) == 1 else projected


def _public_results(
    outputs: Sequence[Mapping[str, Any]],
    *,
    step_id: str,
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
        _assert_public_value(
            value,
            path=f"step={step_id}.public_results.{return_name}.value",
        )
        result[return_name] = {
            "runtime_type": runtime_type,
            "value": value,
        }
    return result


def _witness_checks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for attainment in payload.get("attainment_checks", ()):
        if not isinstance(attainment, Mapping):
            continue
        for item in attainment.get("checks", ()):
            if not isinstance(item, Mapping):
                continue
            checks.append(
                {
                    "name": str(item.get("check") or "attainment_check"),
                    "status": "passed" if item.get("passed") else "failed",
                }
            )
    return checks


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


def _cross_scope_references(
    root: TeachingScope,
    *,
    dependency_graph: Mapping[str, Sequence[str]],
    public_result_dependencies: Mapping[
        str, Sequence[tuple[str, str]]
    ],
) -> tuple[TeachingCrossScopeReference, ...]:
    owners = teaching_source_owners(root)
    sources = tuple(iter_teaching_sources(root))
    source_by_id = {item.source_step_id: item for item in sources}

    references: list[TeachingCrossScopeReference] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source_id: str, return_name: str, target_id: str) -> None:
        source_owner = owners.get(source_id)
        target_owner = owners.get(target_id)
        source = source_by_id.get(source_id)
        if source_owner is None or target_owner is None or source is None:
            raise ExplanationSnapshotError(
                "teaching_projection_dependency_step_missing: "
                f"source={source_id}, target={target_id}"
            )
        if return_name not in source.public_results:
            raise ExplanationSnapshotError(
                "teaching_projection_dependency_result_missing: "
                f"source={source_id}, return={return_name}"
            )
        if source_owner[0] == target_owner[0]:
            return
        key = (source_id, return_name, target_id)
        if key in seen:
            return
        seen.add(key)
        references.append(
            TeachingCrossScopeReference(
                source_step_id=source_id,
                target_step_id=target_id,
                source_scope_ref=source_owner[0],
                target_scope_ref=target_owner[0],
                public_result_ref={
                    "step_id": source_id,
                    "return": return_name,
                },
            )
        )

    for target in sources:
        target_id = target.source_step_id
        cross_scope_dependencies = tuple(
            str(source_id)
            for source_id in dependency_graph.get(target_id, ())
            if owners.get(str(source_id), (None, None))[0]
            != owners[target_id][0]
        )
        projected_sources: set[str] = set()
        for source_id, return_name in public_result_dependencies.get(
            target_id,
            (),
        ):
            source = source_by_id.get(str(source_id))
            if source is None:
                raise ExplanationSnapshotError(
                    "teaching_projection_dependency_step_missing: "
                    f"source={source_id}, target={target_id}"
                )
            if owners[source.source_step_id][0] == owners[target_id][0]:
                continue
            add(source.source_step_id, str(return_name), target_id)
            projected_sources.add(source.source_step_id)
        missing_sources = sorted(
            set(cross_scope_dependencies) - projected_sources
        )
        if missing_sources:
            raise ExplanationSnapshotError(
                "teaching_projection_dependency_public_result_unresolved: "
                f"target={target_id}, sources={missing_sources}"
            )
    return tuple(references)


def _assert_public_value(value: Any, *, path: str) -> None:
    internal_keys = {
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
