"""Typed source authority for immutable runtime Conditions.

Condition selection happens before compiler lowering.  This index is the
single scope-aware view shared by reconciliation and F5-C finalization; it
never selects by runtime path, fact handle spelling, or insertion order.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from shuxueshuo_server.solver.runtime.condition_kinds import (
    condition_kind_matches,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
)
from shuxueshuo_server.solver.utils import unique_ordered

if TYPE_CHECKING:
    from shuxueshuo_server.solver.extraction.problem_planning_binding import (
        ProblemPlanningBindingCatalog,
    )


@dataclass(frozen=True)
class ConditionBindingAuthority:
    condition_id: str
    source_ref: str | None
    condition_kind: str
    owner_scope_id: str
    valid_scope_id: str
    object_roles: tuple[tuple[str, tuple[MathObjectId, ...]], ...]
    object_role_refs: tuple[tuple[str, tuple[str, ...]], ...]
    runtime_type: str
    runtime_handle: str
    source_unit_ids: tuple[str, ...] = ()

    @property
    def related_object_ids(self) -> frozenset[MathObjectId]:
        return frozenset(
            object_id
            for _role, object_ids in self.object_roles
            for object_id in object_ids
        )

    @property
    def related_object_refs(self) -> tuple[str, ...]:
        return unique_ordered(
            object_ref
            for _role, object_refs in self.object_role_refs
            for object_ref in object_refs
        )


class ConditionBindingAuthorityError(ValueError):
    """A Condition source cannot be selected without changing authority."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(message)


class ConditionBindingAuthorityIndex:
    """Immutable, lexical index of source Conditions and their object roles."""

    def __init__(
        self,
        authorities: Sequence[ConditionBindingAuthority],
        *,
        scope_parent_ids: Mapping[str, str | None],
        object_ids_by_ref: Mapping[str, MathObjectId],
    ) -> None:
        by_id: dict[str, ConditionBindingAuthority] = {}
        for authority in authorities:
            previous = by_id.setdefault(authority.condition_id, authority)
            if previous != authority:
                raise ConditionBindingAuthorityError(
                    "planner.method_input_view_authority_drift",
                    f"Condition authority differs for {authority.condition_id!r}",
                    details={"condition_id": authority.condition_id},
                )
        self._by_id = MappingProxyType(dict(sorted(by_id.items())))
        self._scope_parent_ids = MappingProxyType(dict(scope_parent_ids))
        self._object_ids_by_ref = MappingProxyType(dict(object_ids_by_ref))

    @classmethod
    def from_context(
        cls,
        planner_state_context: PlannerStateContext,
        *,
        object_registry: MathObjectRegistry,
        problem_binding_catalog: "ProblemPlanningBindingCatalog | None" = None,
    ) -> "ConditionBindingAuthorityIndex":
        source_by_condition: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        if problem_binding_catalog is not None:
            for binding in problem_binding_catalog.bindings.values():
                for source in binding.typed_sources:
                    if source.condition_id is None:
                        continue
                    candidate = (
                        binding.semantic_ref.ref,
                        binding.runtime_node_id,
                        binding.source_unit_ids,
                    )
                    previous = source_by_condition.setdefault(
                        source.condition_id,
                        candidate,
                    )
                    if previous != candidate:
                        raise ConditionBindingAuthorityError(
                            "planner.method_input_view_authority_drift",
                            "one ConditionId maps to multiple problem sources",
                            details={"condition_id": source.condition_id},
                        )

        object_ids_by_ref: dict[str, MathObjectId] = {}
        for item in planner_state_context.state.math_objects:
            if item.math_object_id is None:
                continue
            for ref in (
                item.canonical_handle,
                item.object_id,
                *item.semantic_refs,
            ):
                if ref:
                    object_ids_by_ref.setdefault(ref, item.math_object_id)

        authorities: list[ConditionBindingAuthority] = []
        for condition in planner_state_context.state.conditions:
            source_ref, runtime_node_id, source_units = source_by_condition.get(
                condition.condition_id,
                (None, condition.canonical_handle or condition.condition_id, ()),
            )
            typed_roles: list[tuple[str, tuple[MathObjectId, ...]]] = []
            for role, refs in condition.object_roles:
                object_ids_list: list[MathObjectId] = []
                for ref in refs:
                    object_id = (
                        object_registry.resolve(ref)
                        or object_ids_by_ref.get(ref)
                        or object_registry.register_handle(ref)
                    )
                    if object_id is None:
                        continue
                    object_ids_list.append(object_id)
                    object_ids_by_ref.setdefault(ref, object_id)
                object_ids = tuple(object_ids_list)
                typed_roles.append((role, object_ids))
            authorities.append(
                ConditionBindingAuthority(
                    condition_id=condition.condition_id,
                    source_ref=source_ref,
                    condition_kind=condition.kind,
                    owner_scope_id=condition.scope_id,
                    valid_scope_id=condition.valid_scope or condition.scope_id,
                    object_roles=tuple(typed_roles),
                    object_role_refs=condition.object_roles,
                    runtime_type=condition.value_type or "Condition",
                    runtime_handle=runtime_node_id,
                    source_unit_ids=source_units,
                )
            )
        return cls(
            authorities,
            scope_parent_ids=planner_state_context.state.scope_graph.scope_parents,
            object_ids_by_ref=object_ids_by_ref,
        )

    @property
    def authorities(self) -> tuple[ConditionBindingAuthority, ...]:
        return tuple(self._by_id.values())

    def extended(
        self,
        authorities: Sequence[ConditionBindingAuthority],
    ) -> "ConditionBindingAuthorityIndex":
        """Return a new index containing deterministic produced Conditions."""

        if not authorities:
            return self
        object_ids_by_ref = dict(self._object_ids_by_ref)
        for authority in authorities:
            typed_roles = dict(authority.object_roles)
            for role, refs in authority.object_role_refs:
                ids = typed_roles.get(role, ())
                if len(ids) != len(refs):
                    raise ConditionBindingAuthorityError(
                        "planner.method_input_view_authority_drift",
                        "Condition role refs do not match typed object roles",
                        details={
                            "condition_id": authority.condition_id,
                            "role": role,
                            "object_refs": list(refs),
                            "typed_object_count": len(ids),
                        },
                    )
                for ref, object_id in zip(refs, ids, strict=True):
                    previous = object_ids_by_ref.setdefault(ref, object_id)
                    if previous != object_id:
                        raise ConditionBindingAuthorityError(
                            "planner.method_input_view_authority_drift",
                            f"Condition object ref differs for {ref!r}",
                            details={"object_ref": ref},
                        )
        return ConditionBindingAuthorityIndex(
            (*self.authorities, *authorities),
            scope_parent_ids=self._scope_parent_ids,
            object_ids_by_ref=object_ids_by_ref,
        )

    def require(self, condition_id: str) -> ConditionBindingAuthority:
        try:
            return self._by_id[condition_id]
        except KeyError as exc:
            raise ConditionBindingAuthorityError(
                "planner.method_input_view_authority_missing",
                f"ConditionId {condition_id!r} is absent from source authority",
                details={"condition_id": condition_id},
            ) from exc

    def resolve_runtime_handle(
        self,
        runtime_handle: str,
        *,
        condition_kinds: Sequence[str],
        scope_id: str,
    ) -> ConditionBindingAuthority:
        """Resolve one exact source handle without scanning runtime paths."""

        candidates = tuple(
            item
            for item in self._by_id.values()
            if item.runtime_handle == runtime_handle
            and condition_kind_matches(item.condition_kind, condition_kinds)
        )
        visible_scopes = frozenset(self._scope_path(scope_id))
        visible = tuple(
            item for item in candidates if item.valid_scope_id in visible_scopes
        )
        if len(visible) == 1:
            return visible[0]
        if not visible:
            code = (
                "functional.method_input_condition_not_visible"
                if candidates
                else "functional.method_input_condition_missing"
            )
            raise ConditionBindingAuthorityError(
                code,
                "the selected source Condition is not uniquely visible",
                details=self._resolution_details(
                    condition_kinds=condition_kinds,
                    related_object_ids=frozenset(),
                    related_object_refs=frozenset(),
                    candidates=candidates,
                    scope_id=scope_id,
                ),
            )
        raise ConditionBindingAuthorityError(
            "functional.method_input_condition_ambiguous",
            "the selected source handle maps to multiple Conditions",
            details=self._resolution_details(
                condition_kinds=condition_kinds,
                related_object_ids=frozenset(),
                related_object_refs=frozenset(),
                candidates=visible,
                scope_id=scope_id,
            ),
        )

    def object_id_for_ref(self, object_ref: str) -> MathObjectId | None:
        return self._object_ids_by_ref.get(object_ref)

    def resolve_relation(
        self,
        *,
        condition_kinds: Sequence[str],
        related_object_ids: Sequence[MathObjectId] = (),
        related_object_refs: Sequence[str] = (),
        scope_id: str,
    ) -> ConditionBindingAuthority:
        required_ids = frozenset(related_object_ids)
        required_refs = frozenset(related_object_refs)
        kind_matches = tuple(
            item
            for item in self._by_id.values()
            if condition_kind_matches(item.condition_kind, condition_kinds)
            and required_ids.issubset(item.related_object_ids)
            and required_refs.issubset(set(item.related_object_refs))
        )
        visible_scopes = frozenset(self._scope_path(scope_id))
        visible = tuple(
            item
            for item in kind_matches
            if item.valid_scope_id in visible_scopes
        )
        if len(visible) == 1:
            return visible[0]
        if not visible:
            invisible = tuple(
                item
                for item in kind_matches
                if item.valid_scope_id not in visible_scopes
            )
            code = (
                "functional.method_input_condition_not_visible"
                if invisible
                else "functional.method_input_condition_missing"
            )
            raise ConditionBindingAuthorityError(
                code,
                "no unique visible Condition satisfies the declared relation",
                details=self._resolution_details(
                    condition_kinds=condition_kinds,
                    related_object_ids=required_ids,
                    related_object_refs=required_refs,
                    candidates=invisible,
                    scope_id=scope_id,
                ),
            )
        raise ConditionBindingAuthorityError(
            "functional.method_input_condition_ambiguous",
            "multiple visible Conditions satisfy the declared relation",
            details=self._resolution_details(
                condition_kinds=condition_kinds,
                related_object_ids=required_ids,
                related_object_refs=required_refs,
                candidates=visible,
                scope_id=scope_id,
            ),
        )

    def _resolution_details(
        self,
        *,
        condition_kinds: Sequence[str],
        related_object_ids: frozenset[MathObjectId],
        related_object_refs: frozenset[str],
        candidates: Sequence[ConditionBindingAuthority],
        scope_id: str,
    ) -> dict[str, Any]:
        return {
            "accepted_condition_kinds": list(condition_kinds),
            "related_object_refs": sorted(
                {
                    *related_object_refs,
                    *(item.value for item in related_object_ids),
                }
            ),
            "candidate_refs": [
                item.source_ref or item.runtime_handle for item in candidates
            ],
            "candidate_owner_scopes": [
                item.owner_scope_id for item in candidates
            ],
            "scope_id": scope_id,
        }

    def _scope_path(self, scope_id: str) -> tuple[str, ...]:
        if scope_id not in self._scope_parent_ids:
            raise ConditionBindingAuthorityError(
                "planner.method_input_view_authority_drift",
                f"unknown Condition resolution scope {scope_id!r}",
                details={"scope_id": scope_id},
            )
        result: list[str] = []
        current: str | None = scope_id
        visited: set[str] = set()
        while current is not None:
            if current in visited or current not in self._scope_parent_ids:
                raise ConditionBindingAuthorityError(
                    "planner.method_input_view_authority_drift",
                    "Condition scope ancestry is invalid",
                    details={"scope_id": scope_id},
                )
            visited.add(current)
            result.append(current)
            current = self._scope_parent_ids[current]
        return tuple(result)


__all__ = [
    "ConditionBindingAuthority",
    "ConditionBindingAuthorityError",
    "ConditionBindingAuthorityIndex",
]
