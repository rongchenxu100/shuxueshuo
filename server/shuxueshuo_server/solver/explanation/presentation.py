"""Deterministic student-facing placement for verified solver steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class StudentStepPlacement:
    step_id: str
    execution_scope_id: str
    presentation_scope_id: str
    placement_reason: str
    source_scope_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "execution_scope_id": self.execution_scope_id,
            "presentation_scope_id": self.presentation_scope_id,
            "placement_reason": self.placement_reason,
            "source_scope_ids": list(self.source_scope_ids),
        }


@dataclass(frozen=True)
class StudentScopeReference:
    source_step_id: str
    target_step_id: str
    source_scope_id: str
    target_scope_id: str
    semantic_roles: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_step_id": self.source_step_id,
            "target_step_id": self.target_step_id,
            "source_scope_id": self.source_scope_id,
            "target_scope_id": self.target_scope_id,
            "semantic_roles": list(self.semantic_roles),
        }


@dataclass(frozen=True)
class StudentNarrativePlacementResult:
    placements: tuple[StudentStepPlacement, ...]
    references: tuple[StudentScopeReference, ...]


class StudentNarrativePlacementProjector:
    """Project one verified call graph into a coherent lesson order."""

    def project(
        self,
        *,
        effective_steps: Sequence[dict[str, Any]],
        problem: Mapping[str, Any],
        functional_reconciliation: Any | None = None,
        raw_functional_plan: Any | None = None,
    ) -> StudentNarrativePlacementResult:
        if not effective_steps:
            return StudentNarrativePlacementResult((), ())
        scope_parents, scope_order = _scope_metadata(problem)
        step_by_id = {str(step["step_id"]): step for step in effective_steps}
        if functional_reconciliation is None:
            return StudentNarrativePlacementResult(
                placements=tuple(
                    StudentStepPlacement(
                        step_id=step_id,
                        execution_scope_id=str(step.get("scope_id") or "problem"),
                        presentation_scope_id=str(step.get("scope_id") or "problem"),
                        placement_reason="legacy_step_intent",
                        source_scope_ids=(str(step.get("scope_id") or "problem"),),
                    )
                    for step_id, step in step_by_id.items()
                ),
                references=(),
            )
        original_order = {step_id: index for index, step_id in enumerate(step_by_id)}
        dependencies = _step_dependencies(
            effective_steps,
            functional_reconciliation=functional_reconciliation,
        )
        consumers = _consumer_graph(dependencies)
        answer_scopes = _answer_scopes_by_step(effective_steps, problem)
        terminal_scopes = _terminal_answer_scopes(
            tuple(step_by_id),
            answer_scopes=answer_scopes,
            consumers=consumers,
        )
        source_scopes = _source_scopes_by_step(
            effective_steps,
            functional_reconciliation=functional_reconciliation,
            raw_functional_plan=raw_functional_plan,
        )
        placement_by_id: dict[str, StudentStepPlacement] = {}
        for step_id, step in step_by_id.items():
            execution_scope = str(step.get("scope_id") or "problem")
            presentation_scope, reason = _presentation_scope(
                execution_scope=execution_scope,
                source_scopes=source_scopes.get(step_id, (execution_scope,)),
                own_answer_scopes=answer_scopes.get(step_id, ()),
                terminal_answer_scopes=terminal_scopes.get(step_id, ()),
                scope_parents=scope_parents,
                scope_order=scope_order,
            )
            placement_by_id[step_id] = StudentStepPlacement(
                step_id=step_id,
                execution_scope_id=execution_scope,
                presentation_scope_id=presentation_scope,
                placement_reason=reason,
                source_scope_ids=source_scopes.get(step_id, (execution_scope,)),
            )

        ordered_ids = _narrative_topological_order(
            tuple(step_by_id),
            dependencies=dependencies,
            placement_by_id=placement_by_id,
            scope_order=scope_order,
            original_order=original_order,
        )
        return_roles = _return_roles_by_step(functional_reconciliation)
        references: list[StudentScopeReference] = []
        for target_id in ordered_ids:
            target_scope = placement_by_id[target_id].presentation_scope_id
            for source_id in dependencies.get(target_id, ()):
                if source_id not in placement_by_id:
                    continue
                source_scope = placement_by_id[source_id].presentation_scope_id
                if source_scope == target_scope or _is_ancestor(
                    source_scope,
                    target_scope,
                    scope_parents,
                ):
                    continue
                references.append(
                    StudentScopeReference(
                        source_step_id=source_id,
                        target_step_id=target_id,
                        source_scope_id=source_scope,
                        target_scope_id=target_scope,
                        semantic_roles=return_roles.get(source_id, ()),
                    )
                )
        return StudentNarrativePlacementResult(
            placements=tuple(placement_by_id[step_id] for step_id in ordered_ids),
            references=tuple(_unique_references(references)),
        )


def _scope_metadata(
    problem: Mapping[str, Any],
) -> tuple[dict[str, str | None], dict[str, int]]:
    scopes = tuple(
        item for item in problem.get("scopes", ()) if isinstance(item, Mapping)
    )
    parents = {
        str(item.get("scope_id")): (
            str(item.get("parent")) if item.get("parent") is not None else None
        )
        for item in scopes
        if item.get("scope_id")
    }
    parents.setdefault("problem", None)
    order = {
        str(item.get("scope_id")): index
        for index, item in enumerate(scopes)
        if item.get("scope_id")
    }
    order.setdefault("problem", -1)
    return parents, order


def _step_dependencies(
    effective_steps: Sequence[dict[str, Any]],
    *,
    functional_reconciliation: Any | None,
) -> dict[str, tuple[str, ...]]:
    step_ids = {str(step["step_id"]) for step in effective_steps}
    result: dict[str, list[str]] = {step_id: [] for step_id in step_ids}
    graph = getattr(functional_reconciliation, "dependency_graph", {}) or {}
    for target, sources in graph.items():
        if target not in step_ids:
            continue
        result[target].extend(source for source in sources if source in step_ids)

    producer_by_handle: dict[str, str] = {}
    for step in effective_steps:
        step_id = str(step["step_id"])
        for item in (*step.get("creates", ()), *step.get("produces", ())):
            if isinstance(item, Mapping) and item.get("handle"):
                producer_by_handle[str(item["handle"])] = step_id
    for step in effective_steps:
        target = str(step["step_id"])
        for handle in step.get("reads", ()):
            source = producer_by_handle.get(str(handle))
            if source is not None and source != target:
                result[target].append(source)
    return {
        step_id: tuple(dict.fromkeys(sources))
        for step_id, sources in result.items()
    }


def _consumer_graph(
    dependencies: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {step_id: [] for step_id in dependencies}
    for target, sources in dependencies.items():
        for source in sources:
            result.setdefault(source, []).append(target)
    return {key: tuple(dict.fromkeys(value)) for key, value in result.items()}


def _answer_scopes_by_step(
    effective_steps: Sequence[dict[str, Any]],
    problem: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    goal_scopes: dict[str, str] = {}
    for goal in problem.get("question_goals", ()):
        if not isinstance(goal, Mapping) or not goal.get("scope_id"):
            continue
        for key in ("handle", "semantic_ref"):
            handle = goal.get(key)
            if handle:
                goal_scopes[str(handle)] = str(goal["scope_id"])
    result: dict[str, tuple[str, ...]] = {}
    for step in effective_steps:
        handles = [str(step.get("target") or "")]
        handles.extend(
            str(item.get("handle") or "")
            for item in step.get("produces", ())
            if isinstance(item, Mapping)
        )
        scopes = tuple(
            dict.fromkeys(
                goal_scopes[handle]
                for handle in handles
                if handle.startswith("answer:") and handle in goal_scopes
            )
        )
        if scopes:
            result[str(step["step_id"])] = scopes
    return result


def _terminal_answer_scopes(
    step_ids: tuple[str, ...],
    *,
    answer_scopes: Mapping[str, tuple[str, ...]],
    consumers: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    memo: dict[str, tuple[str, ...]] = {}
    visiting: set[str] = set()

    def visit(step_id: str) -> tuple[str, ...]:
        if step_id in memo:
            return memo[step_id]
        if step_id in visiting:
            return answer_scopes.get(step_id, ())
        visiting.add(step_id)
        scopes = list(answer_scopes.get(step_id, ()))
        for consumer in consumers.get(step_id, ()):
            scopes.extend(visit(consumer))
        visiting.remove(step_id)
        memo[step_id] = tuple(dict.fromkeys(scopes))
        return memo[step_id]

    for step_id in step_ids:
        visit(step_id)
    return memo


def _source_scopes_by_step(
    effective_steps: Sequence[dict[str, Any]],
    *,
    functional_reconciliation: Any | None,
    raw_functional_plan: Any | None,
) -> dict[str, tuple[str, ...]]:
    raw_scopes = {
        call.call_id: scope.scope_id
        for scope in getattr(raw_functional_plan, "scopes", ())
        for call in scope.calls
    }
    placements = {
        item.canonical_call_id: item
        for item in getattr(functional_reconciliation, "call_placements", ())
    }
    result: dict[str, tuple[str, ...]] = {}
    for step in effective_steps:
        step_id = str(step["step_id"])
        placement = placements.get(step_id)
        if placement is None:
            result[step_id] = (str(step.get("scope_id") or "problem"),)
            continue
        scopes = [placement.declared_scope_id]
        scopes.extend(
            raw_scopes[call_id]
            for call_id in placement.alias_call_ids
            if call_id in raw_scopes
        )
        result[step_id] = tuple(dict.fromkeys(scopes))
    return result


def _presentation_scope(
    *,
    execution_scope: str,
    source_scopes: tuple[str, ...],
    own_answer_scopes: tuple[str, ...],
    terminal_answer_scopes: tuple[str, ...],
    scope_parents: Mapping[str, str | None],
    scope_order: Mapping[str, int],
) -> tuple[str, str]:
    if own_answer_scopes:
        return _non_global_common_scope(
            own_answer_scopes,
            scope_parents=scope_parents,
            scope_order=scope_order,
        ), "answer_scope_anchor"
    if terminal_answer_scopes:
        return _non_global_common_scope(
            terminal_answer_scopes,
            scope_parents=scope_parents,
            scope_order=scope_order,
        ), "shared_consumer_scope"
    if source_scopes:
        return _non_global_common_scope(
            source_scopes,
            scope_parents=scope_parents,
            scope_order=scope_order,
        ), "declared_scope"
    if execution_scope != "problem":
        return execution_scope, "execution_scope_fallback"
    return _first_question_scope(scope_order), "first_question_fallback"


def _non_global_common_scope(
    scopes: Sequence[str],
    *,
    scope_parents: Mapping[str, str | None],
    scope_order: Mapping[str, int],
) -> str:
    common = _least_common_scope(scopes, scope_parents)
    if common != "problem":
        return common
    non_global = tuple(scope for scope in scopes if scope != "problem")
    if non_global:
        return min(non_global, key=lambda scope: scope_order.get(scope, 10**6))
    return _first_question_scope(scope_order)


def _least_common_scope(
    scopes: Sequence[str],
    parents: Mapping[str, str | None],
) -> str:
    if not scopes:
        return "problem"
    chains = [_ancestor_chain(scope, parents) for scope in scopes]
    return next(
        (scope for scope in chains[0] if all(scope in chain for chain in chains[1:])),
        "problem",
    )


def _ancestor_chain(
    scope: str,
    parents: Mapping[str, str | None],
) -> tuple[str, ...]:
    result: list[str] = []
    current: str | None = scope
    while current is not None and current not in result:
        result.append(current)
        current = parents.get(current)
    if "problem" not in result:
        result.append("problem")
    return tuple(result)


def _is_ancestor(
    ancestor: str,
    scope: str,
    parents: Mapping[str, str | None],
) -> bool:
    return ancestor in _ancestor_chain(scope, parents)


def _first_question_scope(scope_order: Mapping[str, int]) -> str:
    candidates = tuple(scope for scope in scope_order if scope != "problem")
    return min(candidates, key=lambda scope: scope_order[scope]) if candidates else "problem"


def _narrative_topological_order(
    step_ids: tuple[str, ...],
    *,
    dependencies: Mapping[str, tuple[str, ...]],
    placement_by_id: Mapping[str, StudentStepPlacement],
    scope_order: Mapping[str, int],
    original_order: Mapping[str, int],
) -> tuple[str, ...]:
    remaining = set(step_ids)
    emitted: list[str] = []
    while remaining:
        available = [
            step_id
            for step_id in remaining
            if all(source not in remaining for source in dependencies.get(step_id, ()))
        ]
        if not available:
            return step_ids
        selected = min(
            available,
            key=lambda step_id: (
                scope_order.get(
                    placement_by_id[step_id].presentation_scope_id,
                    10**6,
                ),
                original_order[step_id],
            ),
        )
        remaining.remove(selected)
        emitted.append(selected)
    return tuple(emitted)


def _return_roles_by_step(
    functional_reconciliation: Any | None,
) -> dict[str, tuple[str, ...]]:
    return {
        item.call_id: tuple(allocation.return_name for allocation in item.returns)
        for item in getattr(functional_reconciliation, "calls", ())
    }


def _unique_references(
    values: Sequence[StudentScopeReference],
) -> tuple[StudentScopeReference, ...]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[StudentScopeReference] = []
    for item in values:
        key = (
            item.source_step_id,
            item.target_step_id,
            item.source_scope_id,
            item.target_scope_id,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


__all__ = [
    "StudentNarrativePlacementProjector",
    "StudentNarrativePlacementResult",
    "StudentScopeReference",
    "StudentStepPlacement",
]
