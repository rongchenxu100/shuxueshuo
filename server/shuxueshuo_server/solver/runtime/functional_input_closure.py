"""Declarative conditional input closure for FunctionalPlan calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapability,
    FunctionalPlanIssue,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.utils import unique_ordered


class FunctionalSemanticIndexSource(Protocol):
    views: Sequence[Any]

    def compatible_views(
        self,
        *,
        scope_id: str,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
    ) -> tuple[Any, ...]: ...

    def available_refs(
        self,
        *,
        scope_id: str,
        accepted_types: Sequence[str],
        accepted_condition_kinds: Sequence[str] = (),
        accepted_semantic_roles: Sequence[str] = (),
        requires_materialized_state: bool = False,
    ) -> tuple[dict[str, str], ...]: ...


@dataclass(frozen=True)
class FunctionalInputClosureResult:
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]]
    repairs: tuple[FunctionalDeterministicRepair, ...]
    issues: tuple[FunctionalPlanIssue, ...]
    reads_closed: bool


@dataclass(frozen=True)
class _Candidate:
    value: ResolvedFunctionalValue
    prompt_ref: dict[str, str]


def resolve_functional_input_closure(
    capability: FunctionalCapability,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndexSource,
    handle_registry: CanonicalHandleRegistry,
) -> FunctionalInputClosureResult:
    """Close conditionally required args without searching unrelated state."""

    requirements = capability.input_closure_requirements
    if not requirements:
        return FunctionalInputClosureResult({}, (), (), False)

    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    all_requirements_embedded = True
    args_by_role = {
        item.semantic_role or item.name: item for item in capability.args
    }

    for requirement in requirements:
        target = args_by_role[requirement.semantic_role]
        current_args = {**resolved_args, **additions}
        if current_args.get(target.name):
            all_requirements_embedded = False
            continue

        providers = tuple(
            value
            for provider_role in requirement.provider_arg_roles
            if (provider := args_by_role.get(provider_role)) is not None
            for value in current_args.get(provider.name, ())
        )
        if providers and any(
            requirement.semantic_role in value.provides_semantic_roles
            for value in providers
        ):
            continue

        all_requirements_embedded = False
        accepted_types = target.accepted_item_types or (target.runtime_type,)
        candidates = _linked_candidates(
            providers,
            accepted_types=accepted_types,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        if len(candidates) == 1:
            candidate = candidates[0]
            additions[target.name] = (candidate.value,)
            repairs.append(
                FunctionalDeterministicRepair(
                    call_id,
                    "close_input_dependency",
                    f"{target.name}=omitted",
                    _prompt_ref_text(candidate.prompt_ref),
                )
            )
            continue

        available_refs = list(
            semantic_index.available_refs(
                scope_id=scope_id,
                accepted_types=accepted_types,
                accepted_condition_kinds=target.accepted_condition_kinds,
                accepted_semantic_roles=target.accepted_semantic_roles,
                requires_materialized_state=target.requires_materialized_state,
            )
        )
        issue_code = (
            "functional.arg_dependency_ambiguous"
            if len(candidates) > 1
            else "functional.arg_dependency_missing"
        )
        issues.append(
            FunctionalPlanIssue(
                "functional_reconciliation",
                issue_code,
                requirement.description,
                call_id,
                scope_id,
                {
                    "arg": target.name,
                    "semantic_role": requirement.semantic_role,
                    "provider_arg_roles": list(
                        requirement.provider_arg_roles
                    ),
                    "accepted_item_types": list(accepted_types),
                    "linked_candidates": [
                        item.prompt_ref for item in candidates
                    ],
                    "compatible_refs": available_refs,
                    "automatic_selection": (
                        "only_provenance_linked_unique_candidate"
                    ),
                },
            )
        )

    return FunctionalInputClosureResult(
        additions,
        tuple(repairs),
        tuple(issues),
        all_requirements_embedded and not issues,
    )


def _linked_candidates(
    providers: Sequence[ResolvedFunctionalValue],
    *,
    accepted_types: Sequence[str],
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndexSource,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[_Candidate, ...]:
    if not providers:
        return ()
    candidates: list[_Candidate] = []
    for value in produced.values():
        if not _compatible_visible(
            value,
            accepted_types=accepted_types,
            scope_id=scope_id,
            handle_registry=handle_registry,
        ) or not _provenance_linked(value, providers):
            continue
        candidates.append(
            _Candidate(
                value,
                {
                    "from_call": value.source_call_id or "",
                    "return": value.return_name or "",
                },
            )
        )
    for view in semantic_index.compatible_views(
        scope_id=scope_id,
        accepted_types=accepted_types,
    ):
        value = _resolved_from_view(view)
        if not _provenance_linked(value, providers):
            continue
        candidates.append(
            _Candidate(
                value,
                {"kind": str(view.kind), "ref": str(view.ref)},
            )
        )
    return _unique_candidates(candidates)


def _compatible_visible(
    value: ResolvedFunctionalValue,
    *,
    accepted_types: Sequence[str],
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    return (
        value.runtime_type is not None
        and any(
            runtime_type_compatible(expected, value.runtime_type)
            for expected in accepted_types
        )
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )


def _provenance_linked(
    candidate: ResolvedFunctionalValue,
    providers: Sequence[ResolvedFunctionalValue],
) -> bool:
    candidate_slots = {
        *candidate.source_state_slot_ids,
        *((candidate.state_slot_id,) if candidate.state_slot_id else ()),
    }
    candidate_objects = {
        *candidate.dependency_object_refs,
        *((candidate.object_ref,) if candidate.object_ref else ()),
    }
    return any(
        bool(candidate_slots & set(provider.source_state_slot_ids))
        or bool(candidate_objects & set(provider.dependency_object_refs))
        for provider in providers
    )


def _resolved_from_view(view: Any) -> ResolvedFunctionalValue:
    return ResolvedFunctionalValue(
        handle=view.handle,
        runtime_type=view.runtime_type,
        valid_scope=view.valid_scope,
        state_slot_id=view.state_slot_id,
        object_ref=view.object_ref,
        condition_id=view.condition_id,
        object_roles=view.object_roles,
        dependency_object_refs=view.dependency_object_refs,
        free_symbol_refs=view.free_symbol_refs,
        source_state_slot_ids=view.source_state_slot_ids,
        provides_semantic_roles=view.provides_semantic_roles,
        lineage=view.lineage,
    )


def _unique_candidates(items: Sequence[_Candidate]) -> tuple[_Candidate, ...]:
    result: dict[tuple[str, str, str | None], _Candidate] = {}
    for item in items:
        key = (
            item.value.state_slot_id or "",
            item.value.handle,
            item.value.object_ref,
        )
        result.setdefault(key, item)
    return tuple(result.values())


def _prompt_ref_text(ref: Mapping[str, str]) -> str:
    return ":".join(
        unique_ordered(value for value in ref.values() if value)
    )
