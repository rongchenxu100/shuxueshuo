"""Cross-call object identity hints derived from declarative contracts."""

from __future__ import annotations

from collections import defaultdict

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalPlan,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef
from shuxueshuo_server.solver.state_semantics import state_object_refs_for_role
from shuxueshuo_server.solver.utils import unique_ordered


_Node = tuple[str, str, str, str]


class _IdentityGraph:
    def __init__(self) -> None:
        self.parent: dict[_Node, _Node] = {}
        self.constants: dict[_Node, set[str]] = defaultdict(set)

    def add(self, node: _Node) -> None:
        self.parent.setdefault(node, node)

    def find(self, node: _Node) -> _Node:
        self.add(node)
        parent = self.parent[node]
        if parent != node:
            self.parent[node] = self.find(parent)
        return self.parent[node]

    def union(self, nodes: tuple[_Node, ...]) -> _Node | None:
        if not nodes:
            return None
        root = self.find(nodes[0])
        for node in nodes[1:]:
            other = self.find(node)
            if other == root:
                continue
            self.parent[other] = root
            self.constants[root].update(self.constants.pop(other, ()))
        return root

    def attach(self, nodes: tuple[_Node, ...], constants: tuple[str, ...]) -> None:
        root = self.union(nodes)
        if root is not None:
            self.constants[root].update(constants)

    def values(self, node: _Node) -> tuple[str, ...]:
        return unique_ordered(self.constants.get(self.find(node), ()))


def infer_future_return_object_hints(
    plan: FunctionalPlan,
    *,
    catalog: object,
    semantic_index: object,
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Solve uniquely determined return identities across the call graph.

    The graph contains only declared identity relations, return object-role
    projections and structured semantic references. Runtime values, labels,
    strategy text and globally unique objects never participate.
    """

    graph = _IdentityGraph()
    call_scope = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    calls = {call.call_id: call for call in plan.calls}

    for call in plan.calls:
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        scope_id = call_scope[call.call_id]
        returns = {item.name: item for item in capability.returns}

        for return_name, binding in call.return_bindings.items():
            if return_name not in returns:
                continue
            graph.attach(
                (_return_node(call.call_id, return_name, "object_ref"),),
                _semantic_constants(
                    binding,
                    field="object_ref",
                    scope_id=scope_id,
                    semantic_index=semantic_index,
                ),
            )

        for returned in capability.returns:
            return_node = _return_node(
                call.call_id,
                returned.name,
                "object_ref",
            )
            graph.add(return_node)
            if returned.identity_arg:
                source_nodes, source_constants = _arg_selection(
                    call,
                    returned.identity_arg,
                    field="object_ref",
                    scope_id=scope_id,
                    semantic_index=semantic_index,
                )
                if returned.identity_policy in {
                    "preserve_input_object",
                    "target_object",
                }:
                    graph.attach(
                        (return_node, *source_nodes),
                        source_constants,
                    )
            for projection in returned.object_role_projections:
                target = _return_node(
                    call.call_id,
                    returned.name,
                    f"object_role:{projection.role}",
                )
                if projection.source_arg is not None:
                    source_nodes, source_constants = _arg_selection(
                        call,
                        projection.source_arg,
                        field=(
                            f"object_role:{projection.source_object_role}"
                            if projection.source_object_role is not None
                            else "object_ref"
                        ),
                        scope_id=scope_id,
                        semantic_index=semantic_index,
                    )
                else:
                    source_nodes = (
                        _return_node(
                            call.call_id,
                            projection.source_return or "",
                            (
                                f"object_role:{projection.source_object_role}"
                                if projection.source_object_role is not None
                                else "object_ref"
                            ),
                        ),
                    )
                    source_constants = ()
                graph.attach((target, *source_nodes), source_constants)

        for constraint in capability.identity_constraints:
            if constraint.relation != "same_object":
                continue
            left_nodes, left_constants = _selector_selection(
                call,
                constraint.left,
                scope_id=scope_id,
                semantic_index=semantic_index,
            )
            right_nodes, right_constants = _selector_selection(
                call,
                constraint.right,
                scope_id=scope_id,
                semantic_index=semantic_index,
            )
            if (
                constraint.applicability == "when_all_present"
                and (not left_nodes and not left_constants)
            ) or (
                constraint.applicability == "when_all_present"
                and (not right_nodes and not right_constants)
            ):
                continue
            graph.attach(
                (*left_nodes, *right_nodes),
                (*left_constants, *right_constants),
            )

    result: dict[tuple[str, str], tuple[str, ...]] = {}
    for call_id, call in calls.items():
        capability = catalog.get(call.capability_id)
        if capability is None:
            continue
        for returned in capability.returns:
            values = graph.values(
                _return_node(call_id, returned.name, "object_ref")
            )
            if len(values) == 1:
                result[(call_id, returned.name)] = values
    return result


def _selector_selection(
    call: object,
    selector: str,
    *,
    scope_id: str,
    semantic_index: object,
) -> tuple[tuple[_Node, ...], tuple[str, ...]]:
    owner, remainder = selector.split(":", 1)
    name, field = remainder.split(".", 1)
    if owner == "return":
        return (_return_node(call.call_id, name, field),), ()
    return _arg_selection(
        call,
        name,
        field=field,
        scope_id=scope_id,
        semantic_index=semantic_index,
    )


def _arg_selection(
    call: object,
    arg_name: str,
    *,
    field: str,
    scope_id: str,
    semantic_index: object,
) -> tuple[tuple[_Node, ...], tuple[str, ...]]:
    nodes: list[_Node] = []
    constants: list[str] = []
    for ref in call.args.get(arg_name, ()):
        if isinstance(ref, CallResultRef):
            nodes.append(
                _return_node(
                    ref.from_call,
                    ref.return_name,
                    field,
                )
            )
        elif isinstance(ref, SemanticRef):
            constants.extend(
                _semantic_constants(
                    ref,
                    field=field,
                    scope_id=scope_id,
                    semantic_index=semantic_index,
                )
            )
    return unique_ordered(nodes), unique_ordered(constants)


def _semantic_constants(
    ref: SemanticRef,
    *,
    field: str,
    scope_id: str,
    semantic_index: object,
) -> tuple[str, ...]:
    if field == "object_ref":
        if ref.kind == "answer":
            target = semantic_index.handle_registry.answer_target_handles.get(
                f"answer:{ref.ref}"
            )
            return (target,) if target is not None else ()
        return semantic_index.object_refs_for(ref, scope_id=scope_id)
    role = field.split(":", 1)[1]
    result: list[str] = []
    for view in semantic_index.views:
        if (
            view.ref != ref.ref
            or view.kind != ref.kind
            or not visible_from_valid_scope(
                view.valid_scope,
                scope_id=scope_id,
                registry=semantic_index.handle_registry,
            )
        ):
            continue
        result.extend(state_object_refs_for_role(view.lineage, role))
        result.extend(dict(view.object_roles).get(role, ()))
    return unique_ordered(result)


def _return_node(call_id: str, return_name: str, field: str) -> _Node:
    return ("return", call_id, return_name, field)


__all__ = ["infer_future_return_object_hints"]
