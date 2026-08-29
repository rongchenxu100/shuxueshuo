"""Declarative evidence-closure evaluation for FunctionalPlan state lineage."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import permutations
from typing import Any, Mapping

from shuxueshuo_server.solver.family.models import (
    EvidenceInputGroupSpec,
    StateLineageClosureSpec,
)
from shuxueshuo_server.solver.state_semantics import (
    StateSemanticLineage,
    state_object_refs_for_role,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class EvidenceClosureEvaluation:
    """Prompt-safe explanation of one evidence-closure decision."""

    passed: bool
    matched_roles: tuple[tuple[str, str], ...] = ()
    missing_roles: tuple[str, ...] = ()
    missing_evidence_tags: tuple[str, ...] = ()
    missing_object_roles: tuple[str, ...] = ()
    witness_call_ids: tuple[str, ...] = ()
    source_call_ids: tuple[str, ...] = ()
    source_handles: tuple[str, ...] = ()
    input_group_permutation: tuple[int, ...] = ()
    description: str = ""

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "passed": self.passed,
            "matched_roles": [
                {"role": role, "handle": handle}
                for role, handle in self.matched_roles
            ],
            "missing_roles": list(self.missing_roles),
            "missing_evidence_tags": list(self.missing_evidence_tags),
            "missing_object_roles": list(self.missing_object_roles),
            "witness_call_ids": list(self.witness_call_ids),
            "source_call_ids": list(self.source_call_ids),
            "source_handles": list(self.source_handles),
            "description": self.description,
        }
        if self.input_group_permutation:
            payload["input_group_permutation"] = list(
                self.input_group_permutation
            )
        return payload

    def to_feedback_payload(self) -> dict[str, object]:
        """Return the provider/LLM view without canonical state handles."""
        return {
            "passed": self.passed,
            "matched_roles": list(
                unique_ordered(role for role, _handle in self.matched_roles)
            ),
            "missing_roles": list(self.missing_roles),
            "missing_evidence_tags": list(self.missing_evidence_tags),
            "missing_object_roles": list(self.missing_object_roles),
            "witness_call_ids": list(self.witness_call_ids),
            "source_call_ids": list(self.source_call_ids),
            "description": self.description,
        }


def evaluate_lineage_closure(
    closure: StateLineageClosureSpec,
    *,
    resolved_args: Mapping[str, tuple[Any, ...]],
    output_object_ref: str | None = None,
) -> EvidenceClosureEvaluation:
    """Evaluate a closure without mutating any input state lineage."""

    groups = closure.input_groups or (
        EvidenceInputGroupSpec(
            source_args=closure.source_args,
            required_semantic_roles=closure.required_semantic_roles,
            required_evidence_tags=closure.required_evidence_tags,
            require_same_witness=closure.require_same_source_call,
        ),
    )
    all_values = tuple(
        value
        for group in groups
        for arg_name in group.source_args
        for value in resolved_args.get(arg_name, ())
    )
    source_call_ids = unique_ordered(
        call_id
        for value in all_values
        for call_id in value.lineage.source_call_ids
    )
    source_handles = unique_ordered(value.handle for value in all_values)
    witness_carriers = tuple(
        value
        for value in all_values
        if value.lineage.evidence_tags
        or value.lineage.object_roles
    )
    witness_call_ids = unique_ordered(
        call_id
        for value in witness_carriers
        for call_id in value.lineage.source_call_ids
    )
    group_orders = (tuple(range(len(groups))),)
    if closure.input_group_matching == "commutative" and len(groups) > 1:
        group_orders = tuple(permutations(range(len(groups))))
    candidates = []
    for group_order in group_orders:
        mapped_groups = tuple(
            replace(group, source_args=groups[source_index].source_args)
            for group, source_index in zip(groups, group_order, strict=True)
        )
        candidate = _evaluate_input_groups(
            mapped_groups,
            resolved_args=resolved_args,
            witness_carriers=witness_carriers,
        )
        if closure.output_object_role is not None:
            expected_refs = _witness_object_refs(
                witness_carriers,
                closure.output_object_role,
            )
            if (
                output_object_ref is None
                or len(expected_refs) != 1
                or output_object_ref not in expected_refs
            ):
                candidate.missing_object_roles.append(
                    closure.output_object_role
                )
        candidates.append((group_order, candidate))
        if candidate.passed:
            break

    identity_order = tuple(range(len(groups)))
    group_order, selected = min(
        candidates,
        key=lambda item: (
            not item[1].passed,
            len(item[1].missing_roles)
            + len(item[1].missing_evidence_tags)
            + len(item[1].missing_object_roles),
            -len(item[1].matched_roles),
            item[0],
        ),
    )
    return EvidenceClosureEvaluation(
        passed=selected.passed,
        matched_roles=tuple(selected.matched_roles),
        missing_roles=unique_ordered(selected.missing_roles),
        missing_evidence_tags=unique_ordered(
            selected.missing_evidence_tags
        ),
        missing_object_roles=unique_ordered(
            selected.missing_object_roles
        ),
        witness_call_ids=witness_call_ids,
        source_call_ids=source_call_ids,
        source_handles=source_handles,
        input_group_permutation=(
            group_order if group_order != identity_order else ()
        ),
        description=closure.description,
    )


@dataclass
class _InputGroupsEvaluation:
    matched_roles: list[tuple[str, str]]
    missing_roles: list[str]
    missing_evidence_tags: list[str]
    missing_object_roles: list[str]

    @property
    def passed(self) -> bool:
        return not (
            self.missing_roles
            or self.missing_evidence_tags
            or self.missing_object_roles
        )


def _evaluate_input_groups(
    groups: tuple[EvidenceInputGroupSpec, ...],
    *,
    resolved_args: Mapping[str, tuple[Any, ...]],
    witness_carriers: tuple[Any, ...],
) -> _InputGroupsEvaluation:
    matched: list[tuple[str, str]] = []
    missing_roles: list[str] = []
    missing_tags: list[str] = []
    missing_object_roles: list[str] = []
    for group in groups:
        values = tuple(
            value
            for arg_name in group.source_args
            for value in resolved_args.get(arg_name, ())
        )
        if len(values) != len(group.source_args):
            missing_roles.extend(
                role
                for role in (
                    *group.required_semantic_roles,
                    *group.required_witness_object_roles,
                )
                if role
            )
            continue
        aliases = dict(group.witness_role_aliases)
        used_indexes: set[int] = set()
        for raw_role in group.required_semantic_roles:
            role = raw_role
            match_index = _matching_value_index(
                values,
                role=role,
                aliases=aliases,
                witness_carriers=witness_carriers,
                used_indexes=used_indexes,
            )
            if match_index is None:
                missing_roles.append(role)
                continue
            used_indexes.add(match_index)
            matched.append((role, values[match_index].handle))
        for object_role in group.required_witness_object_roles:
            match_index = _matching_object_role_index(
                values,
                object_role=object_role,
                witness_carriers=witness_carriers,
                used_indexes=used_indexes,
            )
            if match_index is None:
                missing_object_roles.append(object_role)
                continue
            used_indexes.add(match_index)
            matched.append((object_role, values[match_index].handle))
        for evidence_tag in group.required_evidence_tags:
            if not any(
                evidence_tag in value.lineage.evidence_tags
                for value in witness_carriers
            ):
                missing_tags.append(evidence_tag)
        if group.require_same_witness and not _has_shared_witness(
            values,
            witness_carriers=witness_carriers,
            aliases=aliases,
            object_roles=group.required_witness_object_roles,
        ):
            missing_tags.append("same_witness")
    return _InputGroupsEvaluation(
        matched_roles=matched,
        missing_roles=missing_roles,
        missing_evidence_tags=missing_tags,
        missing_object_roles=missing_object_roles,
    )


def _matching_value_index(
    values: tuple[Any, ...],
    *,
    role: str,
    aliases: Mapping[str, str],
    witness_carriers: tuple[Any, ...],
    used_indexes: set[int],
) -> int | None:
    for index, value in enumerate(values):
        if index in used_indexes:
            continue
        roles = set(value.lineage.semantic_roles)
        if role in roles:
            return index
    object_role = aliases.get(role)
    if object_role is None:
        return None
    expected_refs = _witness_object_refs(witness_carriers, object_role)
    if len(expected_refs) != 1:
        return None
    for index, value in enumerate(values):
        if (
            index not in used_indexes
            and _value_object_id(value) in expected_refs
        ):
            return index
    return None


def _matching_object_role_index(
    values: tuple[Any, ...],
    *,
    object_role: str,
    witness_carriers: tuple[Any, ...],
    used_indexes: set[int],
) -> int | None:
    expected_refs = _witness_object_refs(witness_carriers, object_role)
    if len(expected_refs) != 1:
        return None
    for index, value in enumerate(values):
        if (
            index not in used_indexes
            and _value_object_id(value) in expected_refs
        ):
            return index
    return None


def _witness_object_refs(
    values: tuple[Any, ...],
    role: str,
) -> tuple[str, ...]:
    return unique_ordered(
        object_ref
        for value in values
        for object_ref in state_object_refs_for_role(value.lineage, role)
    )


def _has_shared_witness(
    values: tuple[Any, ...],
    *,
    witness_carriers: tuple[Any, ...],
    aliases: Mapping[str, str],
    object_roles: tuple[str, ...],
) -> bool:
    direct = [
        set(value.lineage.source_call_ids)
        for value in values
        if value.lineage.evidence_tags
    ]
    if len(direct) >= 2:
        return bool(set.intersection(*direct))
    # An identity-backed endpoint may not carry the witness itself. It is
    # accepted only when a witness carrier uniquely names that MathObject.
    alias_roles = (*aliases.values(), *object_roles)
    expected_refs = {
        object_ref
        for role in alias_roles
        for object_ref in _witness_object_refs(witness_carriers, role)
    }
    if not direct and not expected_refs:
        return False
    return all(
        value.lineage.evidence_tags or _value_object_id(value) in expected_refs
        for value in values
    )


def _value_object_id(value: Any) -> str | None:
    typed = getattr(value, "math_object_id", None)
    typed_value = getattr(typed, "value", None)
    if isinstance(typed_value, str):
        return typed_value
    object_ref = getattr(value, "object_ref", None)
    return object_ref if isinstance(object_ref, str) else None


def closure_lineages(
    evaluation: EvidenceClosureEvaluation,
    *,
    resolved_args: Mapping[str, tuple[Any, ...]],
    closure: StateLineageClosureSpec,
) -> tuple[StateSemanticLineage, ...]:
    """Return source lineages only for a successful closure."""

    if not evaluation.passed:
        return ()
    groups = closure.input_groups or (
        EvidenceInputGroupSpec(source_args=closure.source_args),
    )
    return tuple(
        value.lineage
        for group in groups
        for arg_name in group.source_args
        for value in resolved_args.get(arg_name, ())
    )


__all__ = [
    "EvidenceClosureEvaluation",
    "closure_lineages",
    "evaluate_lineage_closure",
]
