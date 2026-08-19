"""Typed identity completeness checks for the Functional authoritative core."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_debug_aliases import (
    legacy_state_slot_aliases,
    parse_functional_call_local_debug_alias,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    StateIdentityFactory,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    merge_state_semantic_lineages,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class FunctionalTypedIdentityCompleteness:
    values_checked: int = 0
    materialized_values: int = 0
    condition_values: int = 0
    identity_only_values: int = 0
    call_result_values: int = 0

    def to_payload(self) -> dict[str, int | bool]:
        return {
            "complete": True,
            "values_checked": self.values_checked,
            "materialized_values": self.materialized_values,
            "condition_values": self.condition_values,
            "identity_only_values": self.identity_only_values,
            "call_result_values": self.call_result_values,
        }

    def merge(
        self,
        other: "FunctionalTypedIdentityCompleteness",
    ) -> "FunctionalTypedIdentityCompleteness":
        return FunctionalTypedIdentityCompleteness(
            values_checked=self.values_checked + other.values_checked,
            materialized_values=(
                self.materialized_values + other.materialized_values
            ),
            condition_values=self.condition_values + other.condition_values,
            identity_only_values=(
                self.identity_only_values + other.identity_only_values
            ),
            call_result_values=(
                self.call_result_values + other.call_result_values
            ),
        )


@dataclass(frozen=True)
class FunctionalTypedSourceCoverage:
    """Classify every legacy source through one exact typed identity kind."""

    legacy_source_ids: tuple[str, ...] = ()
    state_slot_ids: tuple[str, ...] = ()
    call_result_ids: tuple[str, ...] = ()
    condition_ids: tuple[str, ...] = ()
    unresolved_source_ids: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.unresolved_source_ids

    def to_payload(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "legacy_source_ids": list(self.legacy_source_ids),
            "state_slots": list(self.state_slot_ids),
            "call_results": list(self.call_result_ids),
            "conditions": list(self.condition_ids),
            "unresolved": list(self.unresolved_source_ids),
        }


class FunctionalTypedIdentityValidator:
    """Complete and validate typed identity before state allocation."""

    def validate_resolved_args(
        self,
        resolved_args: Mapping[
            str,
            tuple[ResolvedFunctionalValue, ...],
        ],
        *,
        call_id: str,
        identity_factory: StateIdentityFactory,
    ) -> tuple[
        dict[str, tuple[ResolvedFunctionalValue, ...]],
        FunctionalTypedIdentityCompleteness,
    ]:
        result: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
        completeness = FunctionalTypedIdentityCompleteness()
        for arg_name, values in resolved_args.items():
            normalized: list[ResolvedFunctionalValue] = []
            for value in values:
                value = self._complete_value(
                    value,
                    identity_factory=identity_factory,
                )
                category = self._validate_value(
                    value,
                    call_id=call_id,
                    arg_name=arg_name,
                    identity_factory=identity_factory,
                )
                completeness = completeness.merge(
                    self._classification(category)
                )
                normalized.append(value)
            result[arg_name] = tuple(normalized)
        return result, completeness

    def _complete_value(
        self,
        value: ResolvedFunctionalValue,
        *,
        identity_factory: StateIdentityFactory,
    ) -> ResolvedFunctionalValue:
        math_object_id = value.math_object_id or identity_factory.object_id(
            value.object_ref
        )
        direct_versions = unique_ordered(
            (
                *value.source_version_ids,
                *value.lineage.source_version_ids,
            )
        )
        roles = tuple(
            StateObjectRoleBinding(
                role=role.role,
                object_refs=role.object_refs,
                source_state_slot_ids=role.source_state_slot_ids,
                source_handles=role.source_handles,
                object_ids=role.object_ids
                or tuple(
                    object_id
                    for object_ref in role.object_refs
                    if (
                        object_id := identity_factory.object_id(object_ref)
                    )
                    is not None
                ),
                source_version_ids=role.source_version_ids,
                state_requirement=role.state_requirement,
            )
            for role in value.lineage.object_roles
        )
        lineage = merge_state_semantic_lineages(
            value.lineage,
            object_roles=roles,
            source_version_ids=direct_versions,
        )
        return replace(
            value,
            math_object_id=math_object_id,
            source_version_ids=direct_versions,
            lineage=lineage,
        )

    @staticmethod
    def _validate_value(
        value: ResolvedFunctionalValue,
        *,
        call_id: str,
        arg_name: str,
        identity_factory: StateIdentityFactory,
    ) -> str:
        is_call_result = (
            value.source_call_id is not None
            and value.return_name is not None
            and value.logical_state_key is None
            and value.typed_slot_id is None
        )
        if (
            value.state_slot_id is not None
            and value.state_version_id is None
            and not is_call_result
        ):
            _raise_incomplete(
                "planner.state_identity_incomplete",
                call_id=call_id,
                arg_name=arg_name,
                detail="materialized state has no StateVersionId",
            )
        if (
            value.source_state_slot_ids
            and not typed_source_coverage(
                value.source_state_slot_ids,
                value.source_version_ids,
                call_result_ids=value.lineage.source_call_result_ids,
                condition_ids=(
                    (value.condition_id,)
                    if value.condition_id is not None
                    else ()
                ),
            ).complete
            and not is_call_result
        ):
            coverage = typed_source_coverage(
                value.source_state_slot_ids,
                value.source_version_ids,
                call_result_ids=value.lineage.source_call_result_ids,
                condition_ids=(
                    (value.condition_id,)
                    if value.condition_id is not None
                    else ()
                ),
            )
            _raise_incomplete(
                "planner.state_dependency_version_unresolved",
                call_id=call_id,
                arg_name=arg_name,
                detail=(
                    "legacy source slots are not fully covered by typed "
                    "source versions: "
                    f"legacy={value.source_state_slot_ids!r}, "
                    f"typed={tuple(item.to_payload() for item in value.source_version_ids)!r}, "
                    "call_results="
                    f"{value.lineage.source_call_result_ids!r}, "
                    f"coverage={coverage.to_payload()!r}"
                ),
            )
        if (
            value.lineage.source_state_slot_ids
            and not typed_source_coverage(
                value.lineage.source_state_slot_ids,
                value.lineage.source_version_ids,
                call_result_ids=value.lineage.source_call_result_ids,
                condition_ids=(
                    (value.condition_id,)
                    if value.condition_id is not None
                    else ()
                ),
            ).complete
            and not is_call_result
        ):
            coverage = typed_source_coverage(
                value.lineage.source_state_slot_ids,
                value.lineage.source_version_ids,
                call_result_ids=value.lineage.source_call_result_ids,
                condition_ids=(
                    (value.condition_id,)
                    if value.condition_id is not None
                    else ()
                ),
            )
            _raise_incomplete(
                "planner.state_dependency_version_unresolved",
                call_id=call_id,
                arg_name=arg_name,
                detail=(
                    "lineage source slots are not fully covered by typed "
                    "source versions: "
                    f"legacy={value.lineage.source_state_slot_ids!r}, "
                    "typed="
                    f"{tuple(item.to_payload() for item in value.lineage.source_version_ids)!r}, "
                    f"coverage={coverage.to_payload()!r}"
                ),
        )
        for role in value.lineage.object_roles:
            expected_object_ids = {
                identity_factory.object_id(object_ref)
                for object_ref in role.object_refs
            }
            if None in expected_object_ids or not (
                expected_object_ids <= set(role.object_ids)
            ):
                _raise_incomplete(
                    "planner.state_identity_incomplete",
                    call_id=call_id,
                    arg_name=arg_name,
                    detail=(
                        f"object role {role.role} is not fully covered by "
                        "MathObjectId"
                    ),
                )
            if (
                role.state_requirement == "materialized"
                and role.source_state_slot_ids
                and not _legacy_sources_are_fully_typed(
                    role.source_state_slot_ids,
                    role.source_version_ids,
                )
            ):
                _raise_incomplete(
                    "planner.state_dependency_version_unresolved",
                    call_id=call_id,
                    arg_name=arg_name,
                    detail=(
                        f"materialized object role {role.role} has no "
                        "complete StateVersionId coverage: "
                        f"legacy={role.source_state_slot_ids!r}, "
                        "typed="
                        f"{tuple(item.to_payload() for item in role.source_version_ids)!r}"
                    ),
                )
        if (
            value.object_ref is not None
            and value.math_object_id is None
            and value.condition_id is None
        ):
            _raise_incomplete(
                "planner.state_identity_incomplete",
                call_id=call_id,
                arg_name=arg_name,
                detail="identity-only value has no MathObjectId",
            )
        if not any(
            (
                value.state_version_id is not None,
                value.condition_id is not None,
                value.math_object_id is not None,
                value.source_call_id is not None
                and value.return_name is not None,
            )
        ):
            _raise_incomplete(
                "planner.state_identity_incomplete",
                call_id=call_id,
                arg_name=arg_name,
                detail="resolved value has no typed identity category",
            )
        category = _identity_category(value)
        if category is None:
            _raise_incomplete(
                "planner.state_identity_incomplete",
                call_id=call_id,
                arg_name=arg_name,
                detail=(
                    "resolved value does not belong to exactly one typed "
                    "identity category"
                ),
            )
        return category

    @staticmethod
    def _classification(
        category: str,
    ) -> FunctionalTypedIdentityCompleteness:
        return FunctionalTypedIdentityCompleteness(
            values_checked=1,
            materialized_values=int(category == "materialized"),
            condition_values=int(category == "condition"),
            identity_only_values=int(category == "identity"),
            call_result_values=int(category == "call_result"),
            )


def _identity_category(
    value: ResolvedFunctionalValue,
) -> str | None:
    has_materialized_state = value.state_version_id is not None
    has_condition = value.condition_id is not None
    has_object_identity = value.math_object_id is not None
    has_call_result = (
        value.source_call_id is not None
        and value.return_name is not None
    )
    categories = tuple(
        category
        for category, applies in (
            ("materialized", has_materialized_state),
            ("condition", has_condition),
            (
                "identity",
                has_object_identity
                and not has_materialized_state
                and not has_condition,
            ),
            (
                "call_result",
                has_call_result
                and not has_materialized_state
                and not has_condition
                and not has_object_identity,
            ),
        )
        if applies
    )
    return categories[0] if len(categories) == 1 else None


def _legacy_sources_are_fully_typed(
    legacy_slot_ids: tuple[str, ...],
    version_ids: tuple[StateVersionId, ...],
) -> bool:
    return typed_source_coverage(legacy_slot_ids, version_ids).complete


def typed_source_coverage(
    legacy_source_ids: tuple[str, ...],
    version_ids: tuple[StateVersionId, ...],
    *,
    call_result_ids: tuple[str, ...] = (),
    condition_ids: tuple[str, ...] = (),
) -> FunctionalTypedSourceCoverage:
    """Audit the transitional legacy union without conflating typed kinds.

    ``source_state_slot_ids`` historically carried state slots, anonymous call
    results, and occasionally conditions.  During migration we classify each
    member against exact typed authority.  A call result can match its canonical
    ``call.return`` id or the versioned legacy debug alias; no suffix or fuzzy
    matching is allowed.
    """

    state_aliases = {
        alias
        for version_id in version_ids
        for alias in legacy_state_slot_aliases(version_id.slot_id)
    }
    canonical_call_results = set(call_result_ids)
    canonical_conditions = set(condition_ids)
    covered_states: list[str] = []
    covered_results: list[str] = []
    covered_conditions: list[str] = []
    unresolved: list[str] = []
    for legacy_id in dict.fromkeys(legacy_source_ids):
        if legacy_id in state_aliases:
            covered_states.append(legacy_id)
            continue
        canonical_result = (
            legacy_id
            if legacy_id in canonical_call_results
            else parse_functional_call_local_debug_alias(legacy_id)
        )
        if canonical_result in canonical_call_results:
            covered_results.append(str(canonical_result))
            continue
        if legacy_id in canonical_conditions:
            covered_conditions.append(legacy_id)
            continue
        unresolved.append(legacy_id)
    return FunctionalTypedSourceCoverage(
        legacy_source_ids=tuple(dict.fromkeys(legacy_source_ids)),
        state_slot_ids=tuple(covered_states),
        call_result_ids=tuple(covered_results),
        condition_ids=tuple(covered_conditions),
        unresolved_source_ids=tuple(unresolved),
    )


def _raise_incomplete(
    code: str,
    *,
    call_id: str,
    arg_name: str,
    detail: str,
) -> None:
    raise StrategyDraftValidationError(
        "planner_configuration_error: "
        f"{code}: call={call_id}, arg={arg_name}, {detail}"
    )


__all__ = [
    "FunctionalTypedIdentityCompleteness",
    "FunctionalTypedSourceCoverage",
    "FunctionalTypedIdentityValidator",
    "typed_source_coverage",
]
