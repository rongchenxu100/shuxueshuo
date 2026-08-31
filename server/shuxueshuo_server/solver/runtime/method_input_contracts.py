"""Shared executable contracts for Method input declarations."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


INTERCHANGEABLE_INPUT_CONTRACT_FIELDS = (
    "domain_type",
    "runtime_type",
    "view",
    "required",
    "functional_exposed",
    "allows_anonymous_result",
    "allows_empty_collection",
    "symbolic_basis_role",
)


def method_input_requires_typed_entity_authority(input_spec: object) -> bool:
    """Return whether a compiler-owned input must name a typed Math Entity."""

    view = _field_value(input_spec, "view")
    return bool(_field_value(view, "object_kind"))


def validate_interchangeable_input_groups(
    groups: Sequence[Sequence[str]],
    *,
    inputs: Mapping[str, object],
    field_name: str,
    error_factory: Callable[[str], Exception] = ValueError,
) -> None:
    """Validate one permutation claim against the full input contract."""

    seen: set[frozenset[str]] = set()
    for raw_group in groups:
        group = tuple(raw_group)
        if len(group) < 2 or len(set(group)) != len(group):
            raise error_factory(
                f"{field_name} groups require at least two unique input names"
            )
        unknown = tuple(name for name in group if name not in inputs)
        if unknown:
            raise error_factory(
                f"{field_name} references unknown inputs: {', '.join(unknown)}"
            )
        group_key = frozenset(group)
        if group_key in seen:
            raise error_factory(
                f"duplicate {field_name} group: {', '.join(group)}"
            )
        seen.add(group_key)
        signatures = {
            tuple(
                _freeze_contract_value(_field_value(inputs[name], field))
                for field in INTERCHANGEABLE_INPUT_CONTRACT_FIELDS
            )
            for name in group
        }
        if len(signatures) != 1:
            raise error_factory(
                f"{field_name} requires identical input type, view, required, "
                "exposure, and source-form contracts: "
                + ", ".join(group)
            )


def _field_value(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _freeze_contract_value(value: object) -> object:
    if hasattr(value, "to_payload"):
        value = value.to_payload()
    if isinstance(value, Mapping):
        return tuple(
            sorted(
                (str(key), _freeze_contract_value(item))
                for key, item in value.items()
            )
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_contract_value(item) for item in value)
    return value


__all__ = [
    "INTERCHANGEABLE_INPUT_CONTRACT_FIELDS",
    "method_input_requires_typed_entity_authority",
    "validate_interchangeable_input_groups",
]
