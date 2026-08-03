"""Typed logical graph for transactional Functional execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.runtime.functional_plan_graph import (
    topological_scoped_calls,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    FunctionalCallIdentityKey,
    MathObjectId,
)
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalCallLifecycleStatus = Literal[
    "pending",
    "ready",
    "running",
    "verified",
    "failed",
    "blocked_by_dependency",
    "eliminated",
    "aliased",
]
FunctionalDependencyKind = Literal[
    "call_result",
    "state_version",
    "condition",
    "semantic_object",
    "unknown",
]


@dataclass(frozen=True)
class FunctionalDependencyEdge:
    producer_call_id: str
    consumer_call_id: str
    kind: FunctionalDependencyKind
    arg_name: str | None = None
    return_name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "producer_call_id": self.producer_call_id,
            "consumer_call_id": self.consumer_call_id,
            "kind": self.kind,
        }
        if self.arg_name is not None:
            payload["arg_name"] = self.arg_name
        if self.return_name is not None:
            payload["return_name"] = self.return_name
        return payload


@dataclass(frozen=True)
class LogicalFunctionalCall:
    call_id: str
    capability_id: str
    canonical_call_id: str
    declared_scope_id: str
    execution_scope_id: str
    dependency_call_ids: tuple[str, ...]
    consumer_call_ids: tuple[str, ...]
    identity_key: FunctionalCallIdentityKey | None
    answer_handles: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "capability_id": self.capability_id,
            "canonical_call_id": self.canonical_call_id,
            "declared_scope_id": self.declared_scope_id,
            "execution_scope_id": self.execution_scope_id,
            "dependency_call_ids": list(self.dependency_call_ids),
            "consumer_call_ids": list(self.consumer_call_ids),
            "identity_key": (
                self.identity_key.to_payload()
                if self.identity_key is not None
                else None
            ),
            "answer_handles": list(self.answer_handles),
        }


@dataclass(frozen=True)
class LogicalAnswerBinding:
    answer_handle: str
    producer_call_id: str
    return_name: str
    math_object_id: MathObjectId

    def to_payload(self) -> dict[str, Any]:
        return {
            "answer_handle": self.answer_handle,
            "producer_call_id": self.producer_call_id,
            "return_name": self.return_name,
            "math_object_id": self.math_object_id.to_payload(),
        }


@dataclass(frozen=True)
class LogicalFunctionalGraph:
    calls: tuple[LogicalFunctionalCall, ...]
    dependencies: tuple[FunctionalDependencyEdge, ...]
    answer_bindings: tuple[LogicalAnswerBinding, ...]
    canonical_order: tuple[str, ...]
    alias_call_ids: tuple[str, ...]
    eliminated_call_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "calls": [item.to_payload() for item in self.calls],
            "dependencies": [
                item.to_payload() for item in self.dependencies
            ],
            "answer_bindings": [
                item.to_payload() for item in self.answer_bindings
            ],
            "canonical_order": list(self.canonical_order),
            "alias_call_ids": list(self.alias_call_ids),
            "eliminated_call_ids": list(self.eliminated_call_ids),
        }


@dataclass(frozen=True)
class LogicalFunctionalGraphBuildIssue:
    code: str
    call_id: str | None
    detail: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "call_id": self.call_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class LogicalFunctionalGraphBuildResult:
    graph: LogicalFunctionalGraph
    issues: tuple[LogicalFunctionalGraphBuildIssue, ...] = ()


class LogicalFunctionalGraphBuilder:
    """Build a runtime-path-free graph from B2/B3 reconciliation output."""

    def build(
        self,
        raw_plan: FunctionalPlan,
        reconciliation: FunctionalPlanReconciliationResult,
        *,
        handle_registry: CanonicalHandleRegistry,
    ) -> LogicalFunctionalGraphBuildResult:
        effective_plan = reconciliation.effective_plan
        aliases = dict(reconciliation.call_aliases)
        effective_calls = {call.call_id: call for call in effective_plan.calls}
        raw_call_ids = tuple(call.call_id for call in raw_plan.calls)
        canonical_call_ids = tuple(effective_calls)
        alias_call_ids = tuple(
            call_id for call_id in raw_call_ids if call_id in aliases
        )
        eliminated_call_ids = tuple(
            call_id
            for call_id in raw_call_ids
            if call_id not in effective_calls and call_id not in aliases
        )
        canonical_dependencies = _canonical_dependencies(
            reconciliation.dependency_graph,
            aliases=aliases,
            call_ids=set(canonical_call_ids),
        )
        ordered, cyclic_ids = topological_scoped_calls(
            effective_plan,
            dependency_graph=canonical_dependencies,
        )
        issues: list[LogicalFunctionalGraphBuildIssue] = [
            LogicalFunctionalGraphBuildIssue(
                "logical_graph_cycle",
                call_id,
                "canonical dependency graph contains a cycle",
            )
            for call_id in cyclic_ids
        ]
        canonical_order = tuple(call.call_id for _, _, call in ordered)
        scopes = {
            call.call_id: scope.scope_id
            for scope in effective_plan.scopes
            for call in scope.calls
        }
        placements = {
            item.canonical_call_id: item
            for item in reconciliation.call_placements
        }
        identity_keys = _placement_identity_keys(reconciliation)
        consumers = _reverse_dependencies(canonical_dependencies)
        reconciled = {
            item.call_id: item for item in reconciliation.calls
        }
        edges, edge_issues = _dependency_edges(
            effective_plan,
            reconciliation,
            canonical_dependencies=canonical_dependencies,
            aliases=aliases,
        )
        issues.extend(edge_issues)
        answer_bindings, answer_issues = _answer_bindings(
            effective_plan,
            reconciliation,
            aliases=aliases,
        )
        issues.extend(answer_issues)
        logical_calls = tuple(
            LogicalFunctionalCall(
                call_id=call_id,
                capability_id=effective_calls[call_id].capability_id,
                canonical_call_id=call_id,
                declared_scope_id=scopes[call_id],
                execution_scope_id=(
                    placements[call_id].execution_scope_id
                    if call_id in placements
                    else (
                        reconciled[call_id].scope_id
                        if call_id in reconciled
                        else scopes[call_id]
                    )
                ),
                dependency_call_ids=canonical_dependencies.get(call_id, ()),
                consumer_call_ids=consumers.get(call_id, ()),
                identity_key=identity_keys.get(call_id),
                answer_handles=tuple(
                    item.answer_handle
                    for item in answer_bindings
                    if item.producer_call_id == call_id
                ),
            )
            for call_id in canonical_order
        )
        return LogicalFunctionalGraphBuildResult(
            LogicalFunctionalGraph(
                calls=logical_calls,
                dependencies=edges,
                answer_bindings=answer_bindings,
                canonical_order=canonical_order,
                alias_call_ids=alias_call_ids,
                eliminated_call_ids=eliminated_call_ids,
            ),
            tuple(issues),
        )


def _canonical_call_id(call_id: str, aliases: Mapping[str, str]) -> str:
    visited: set[str] = set()
    current = call_id
    while current in aliases and current not in visited:
        visited.add(current)
        current = aliases[current]
    return current


def _canonical_dependencies(
    dependency_graph: Mapping[str, tuple[str, ...]],
    *,
    aliases: Mapping[str, str],
    call_ids: set[str],
) -> dict[str, tuple[str, ...]]:
    collected: dict[str, list[str]] = {
        call_id: [] for call_id in call_ids
    }
    for consumer, dependencies in dependency_graph.items():
        canonical_consumer = _canonical_call_id(consumer, aliases)
        if canonical_consumer not in call_ids:
            continue
        collected[canonical_consumer].extend(
            canonical_dependency
            for dependency in dependencies
            for canonical_dependency in (
                _canonical_call_id(dependency, aliases),
            )
            if canonical_dependency in call_ids
            and canonical_dependency != canonical_consumer
        )
    return {
        call_id: unique_ordered(dependencies)
        for call_id, dependencies in collected.items()
    }


def _reverse_dependencies(
    dependencies: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for consumer, producers in dependencies.items():
        for producer in producers:
            result.setdefault(producer, []).append(consumer)
    return {
        call_id: unique_ordered(values)
        for call_id, values in result.items()
    }


def _placement_identity_keys(
    reconciliation: FunctionalPlanReconciliationResult,
) -> dict[str, FunctionalCallIdentityKey]:
    result: dict[str, FunctionalCallIdentityKey] = {}
    for payload in reconciliation.state_placement_decisions:
        call_id = payload.get("canonical_call_id")
        identity = payload.get("identity_key")
        if isinstance(call_id, str) and isinstance(identity, Mapping):
            result[call_id] = FunctionalCallIdentityKey.from_payload(identity)
    return result


def _dependency_edges(
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    canonical_dependencies: Mapping[str, tuple[str, ...]],
    aliases: Mapping[str, str],
) -> tuple[
    tuple[FunctionalDependencyEdge, ...],
    tuple[LogicalFunctionalGraphBuildIssue, ...],
]:
    explicit: dict[
        tuple[str, str], tuple[str, str | None, str | None]
    ] = {}
    for call in plan.calls:
        consumer = _canonical_call_id(call.call_id, aliases)
        for arg_name, refs in call.args.items():
            for ref in refs:
                if not isinstance(ref, CallResultRef):
                    continue
                producer = _canonical_call_id(ref.from_call, aliases)
                explicit[(producer, consumer)] = (
                    "call_result",
                    arg_name,
                    ref.return_name,
                )
    typed_kinds: dict[tuple[str, str], FunctionalDependencyKind] = {
        (
            _canonical_call_id(producer, aliases),
            _canonical_call_id(consumer, aliases),
        ): kind
        for consumer, producers in reconciliation.dependency_kinds.items()
        for producer, kind in producers.items()
        if kind in {
            "call_result",
            "state_version",
            "condition",
            "semantic_object",
        }
    }
    producer_by_version = {
        returned.selected_version_id: _canonical_call_id(
            call.call_id,
            aliases,
        )
        for call in reconciliation.calls
        for returned in call.returns
        if returned.selected_version_id is not None
    }
    step_to_call = {
        item.call_id: _canonical_call_id(item.canonical_call_id, aliases)
        for item in reconciliation.execution_entries
    }
    for dependency in reconciliation.state_dependencies:
        consumer = step_to_call.get(dependency.step_id)
        producer = (
            step_to_call.get(dependency.source_step_id)
            if dependency.source_step_id is not None
            else None
        )
        if producer is None and dependency.state_version_id is not None:
            producer = producer_by_version.get(
                dependency.state_version_id
            )
        if (
            producer is not None
            and consumer is not None
            and producer != consumer
        ):
            typed_kinds[(producer, consumer)] = "state_version"
    for call in reconciliation.calls:
        consumer = _canonical_call_id(call.call_id, aliases)
        for values in call.resolved_args.values():
            for value in values:
                if value.source_call_id is None:
                    continue
                producer = _canonical_call_id(value.source_call_id, aliases)
                kind: FunctionalDependencyKind
                if value.condition_id is not None:
                    kind = "condition"
                elif value.state_version_id is not None or value.source_version_ids:
                    kind = "state_version"
                else:
                    kind = "semantic_object"
                typed_kinds[(producer, consumer)] = kind
        for returned in call.returns:
            for version_id in (
                *(
                    (returned.previous_version_id,)
                    if returned.previous_version_id is not None
                    else ()
                ),
                *returned.source_version_ids,
            ):
                producer = producer_by_version.get(version_id)
                if producer is not None and producer != consumer:
                    typed_kinds[(producer, consumer)] = "state_version"
    edges: list[FunctionalDependencyEdge] = []
    issues: list[LogicalFunctionalGraphBuildIssue] = []
    for consumer, producers in canonical_dependencies.items():
        for producer in producers:
            explicit_edge = explicit.get((producer, consumer))
            kind = (
                explicit_edge[0]
                if explicit_edge is not None
                else typed_kinds.get((producer, consumer))
            )
            if kind is None:
                kind = "unknown"
                issues.append(
                    LogicalFunctionalGraphBuildIssue(
                        "dependency_kind_unresolved",
                        consumer,
                        f"producer={producer}, consumer={consumer}",
                    )
                )
            edges.append(
                FunctionalDependencyEdge(
                    producer,
                    consumer,
                    kind,
                    (
                        explicit_edge[1]
                        if explicit_edge is not None
                        else None
                    ),
                    (
                        explicit_edge[2]
                        if explicit_edge is not None
                        else None
                    ),
                )
            )
    return tuple(edges), tuple(issues)


def _answer_bindings(
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    aliases: Mapping[str, str],
) -> tuple[
    tuple[LogicalAnswerBinding, ...],
    tuple[LogicalFunctionalGraphBuildIssue, ...],
]:
    allocations = {
        (item.call_id, returned.return_name): returned
        for item in reconciliation.calls
        for returned in item.returns
    }
    bindings: list[LogicalAnswerBinding] = []
    issues: list[LogicalFunctionalGraphBuildIssue] = []
    for call in plan.calls:
        canonical = _canonical_call_id(call.call_id, aliases)
        for return_name, binding in call.return_bindings.items():
            if binding.kind != "answer":
                continue
            allocation = allocations.get((canonical, return_name))
            answer_handle = (
                binding.ref
                if binding.ref.startswith("answer:")
                else f"answer:{binding.ref}"
            )
            object_id = (
                allocation.math_object_id
                if allocation is not None
                else None
            )
            if object_id is None:
                issues.append(
                    LogicalFunctionalGraphBuildIssue(
                        "answer_math_object_identity_missing",
                        canonical,
                        f"answer={answer_handle}, return={return_name}",
                    )
                )
                continue
            bindings.append(
                LogicalAnswerBinding(
                    answer_handle,
                    canonical,
                    return_name,
                    object_id,
                )
            )
    return tuple(bindings), tuple(issues)


__all__ = [
    "FunctionalCallLifecycleStatus",
    "FunctionalDependencyEdge",
    "FunctionalDependencyKind",
    "LogicalAnswerBinding",
    "LogicalFunctionalCall",
    "LogicalFunctionalGraph",
    "LogicalFunctionalGraphBuildIssue",
    "LogicalFunctionalGraphBuildResult",
    "LogicalFunctionalGraphBuilder",
]
