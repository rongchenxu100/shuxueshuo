"""Raw StepIntent ``outputs[]`` compatibility normalization.

This module is intentionally a JSON-boundary adapter.  It lets the LLM use a
single ``outputs`` list, then deterministically projects it back to the
existing ``creates`` / ``produces`` / ``reads`` fields before StepIntent parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _ENTITY_TYPES,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    STEP_INTENT_OUTPUT_TYPES,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class RawStepOutputNormalizationResult:
    """Summary for raw ``outputs[]`` projection."""

    changed: bool = False
    warnings: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "warnings": list(self.warnings),
        }


def normalize_raw_outputs(
    data: dict[str, Any],
    *,
    handle_registry: CanonicalHandleRegistry | None = None,
) -> tuple[dict[str, Any], RawStepOutputNormalizationResult]:
    """Project optional raw ``outputs[]`` fields into legacy StepIntent fields."""
    raw_scopes = data.get("scopes")
    if not isinstance(raw_scopes, list):
        return data, RawStepOutputNormalizationResult()
    changed = False
    warnings: list[str] = []
    new_scopes: list[Any] = []
    for scope_index, raw_scope in enumerate(raw_scopes):
        if not isinstance(raw_scope, dict):
            new_scopes.append(raw_scope)
            continue
        raw_steps = raw_scope.get("steps")
        if not isinstance(raw_steps, list):
            new_scopes.append(dict(raw_scope))
            continue
        new_steps: list[Any] = []
        for step_index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, dict):
                new_steps.append(raw_step)
                continue
            legacy_output_fields = tuple(
                field for field in ("creates", "produces") if field in raw_step
            )
            raw_step, fill_warnings = _fill_missing_output_lists(
                raw_step,
                scope_index=scope_index,
                step_index=step_index,
            )
            if fill_warnings:
                warnings.extend(fill_warnings)
                changed = True
            if "outputs" not in raw_step:
                new_steps.append(raw_step)
                continue
            normalized_step, step_warnings = _normalize_step_outputs(
                raw_step,
                handle_registry=handle_registry,
                scope_index=scope_index,
                step_index=step_index,
                legacy_output_fields=legacy_output_fields,
            )
            warnings.extend(step_warnings)
            changed = True
            new_steps.append(normalized_step)
        new_scope = dict(raw_scope)
        new_scope["steps"] = new_steps
        new_scopes.append(new_scope)
    if not changed:
        return data, RawStepOutputNormalizationResult()
    normalized = dict(data)
    normalized["scopes"] = new_scopes
    return normalized, RawStepOutputNormalizationResult(
        changed=True,
        warnings=tuple(warnings),
    )


def _normalize_step_outputs(
    raw_step: dict[str, Any],
    *,
    handle_registry: CanonicalHandleRegistry | None,
    scope_index: int,
    step_index: int,
    legacy_output_fields: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    raw_outputs = raw_step.get("outputs")
    if not isinstance(raw_outputs, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].outputs must be an object array"
        )
    normalized = dict(raw_step)
    reads = _string_list_or_empty(
        normalized.get("reads", []),
        field="reads",
        scope_index=scope_index,
        step_index=step_index,
    )
    creates = _object_list_or_empty(
        normalized.get("creates", []),
        field="creates",
        scope_index=scope_index,
        step_index=step_index,
    )
    produces = _object_list_or_empty(
        normalized.get("produces", []),
        field="produces",
        scope_index=scope_index,
        step_index=step_index,
    )
    warnings: list[str] = []
    if legacy_output_fields:
        warnings.append(
            "raw_output_mixed_with_legacy_outputs: "
            f"scopes[{scope_index}].steps[{step_index}] "
            f"uses outputs with {', '.join(legacy_output_fields)}; "
            "outputs will be projected and de-duplicated"
        )
    for item_index, raw_output in enumerate(raw_outputs):
        output = _validated_output_item(
            raw_output,
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        handle = output["handle"]
        if _should_project_output_to_read(handle, handle_registry):
            reads.append(handle)
            warnings.append(
                "raw_output_existing_handle_projected_to_read: "
                f"scopes[{scope_index}].steps[{step_index}].outputs[{item_index}]"
            )
            continue
        entity_type = _entity_type_for_output(handle, output.get("entity_type"))
        if entity_type is not None:
            creates.append(
                {
                    "handle": handle,
                    "entity_type": entity_type,
                    "valid_scope": output["valid_scope"],
                    "description": output["description"],
                }
            )
            continue
        if handle.startswith("fact:") or handle.startswith("answer:"):
            produced = {
                "handle": handle,
                "valid_scope": output["valid_scope"],
                "description": output["description"],
            }
            output_type = output.get("output_type")
            if output_type is not None:
                produced["output_type"] = output_type
            produces.append(produced)
            continue
        raise StrategyDraftValidationError(
            "raw_output_unsupported_handle: "
            f"scopes[{scope_index}].steps[{step_index}].outputs[{item_index}].handle={handle}"
        )
    normalized["reads"] = list(unique_ordered(reads))
    normalized_creates, create_warnings = _unique_objects_by_handle(
        creates,
        field="creates",
        scope_index=scope_index,
        step_index=step_index,
    )
    normalized_produces, produce_warnings = _unique_objects_by_handle(
        produces,
        field="produces",
        scope_index=scope_index,
        step_index=step_index,
    )
    warnings.extend(create_warnings)
    warnings.extend(produce_warnings)
    normalized["creates"] = normalized_creates
    normalized["produces"] = normalized_produces
    normalized.pop("outputs", None)
    return normalized, tuple(warnings)


def _fill_missing_output_lists(
    raw_step: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    has_creates = "creates" in raw_step
    has_produces = "produces" in raw_step
    has_outputs = "outputs" in raw_step
    if has_creates and has_produces:
        return raw_step, ()
    if not (has_creates or has_produces or has_outputs):
        return raw_step, ()
    normalized = dict(raw_step)
    warnings: list[str] = []
    if not has_creates:
        normalized["creates"] = []
        warnings.append(
            "raw_output_missing_creates_defaulted_empty: "
            f"scopes[{scope_index}].steps[{step_index}]"
        )
    if not has_produces:
        normalized["produces"] = []
        warnings.append(
            "raw_output_missing_produces_defaulted_empty: "
            f"scopes[{scope_index}].steps[{step_index}]"
        )
    return normalized, tuple(warnings)


def _validated_output_item(
    raw_output: object,
    *,
    scope_index: int,
    step_index: int,
    item_index: int,
) -> dict[str, str | None]:
    if not isinstance(raw_output, dict):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].outputs[{item_index}] must be an object"
        )
    required = {"handle", "valid_scope", "description"}
    optional = {"entity_type", "output_type"}
    missing = sorted(required - set(raw_output))
    extra = sorted(set(raw_output) - required - optional)
    if missing:
        raise StrategyDraftValidationError(
            "scopes"
            f"[{scope_index}].steps[{step_index}].outputs[{item_index}] "
            f"missing required fields: {', '.join(missing)}"
        )
    if extra:
        raise StrategyDraftValidationError(
            "scopes"
            f"[{scope_index}].steps[{step_index}].outputs[{item_index}] "
            f"contains unsupported fields: {', '.join(extra)}"
        )
    result: dict[str, str | None] = {}
    for key in required:
        value = raw_output.get(key)
        if not isinstance(value, str) or not value.strip():
            raise StrategyDraftValidationError(
                "scopes"
                f"[{scope_index}].steps[{step_index}].outputs[{item_index}].{key} "
                "must be a string"
            )
        result[key] = value.strip()
    for key in optional:
        value = raw_output.get(key)
        if value is None:
            result[key] = None
            continue
        if not isinstance(value, str) or not value.strip():
            raise StrategyDraftValidationError(
                "scopes"
                f"[{scope_index}].steps[{step_index}].outputs[{item_index}].{key} "
                "must be a string or null"
            )
        text = value.strip()
        if key == "output_type" and text not in STEP_INTENT_OUTPUT_TYPES:
            raise StrategyDraftValidationError(
                "scopes"
                f"[{scope_index}].steps[{step_index}].outputs[{item_index}].output_type "
                f"unsupported: {text}"
            )
        result[key] = text
    return result


def _string_list_or_empty(
    value: object,
    *,
    field: str,
    scope_index: int,
    step_index: int,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].{field} must be a string array"
        )
    result: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].{field}[{item_index}] must be a non-empty string"
            )
        result.append(item.strip())
    return result


def _object_list_or_empty(
    value: object,
    *,
    field: str,
    scope_index: int,
    step_index: int,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].{field} must be an object array"
        )
    result: list[dict[str, Any]] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].{field}[{item_index}] must be an object"
            )
        result.append(dict(item))
    return result


def _should_project_output_to_read(
    handle: str,
    registry: CanonicalHandleRegistry | None,
) -> bool:
    if registry is None:
        return False
    if handle.startswith("answer:"):
        return False
    return handle in registry.initial_handles


def _entity_type_for_output(handle: str, explicit_type: str | None) -> str | None:
    parts = handle.split(":", 2)
    if len(parts) != 3 or parts[0] not in _ENTITY_TYPES:
        if explicit_type is not None:
            raise StrategyDraftValidationError(
                "raw_output_entity_type_without_entity_handle: "
                f"handle={handle}, entity_type={explicit_type}"
            )
        return None
    entity_type = parts[0]
    if explicit_type is not None and explicit_type != entity_type:
        raise StrategyDraftValidationError(
            "raw_output_entity_type_mismatch: "
            f"handle={handle}, entity_type={explicit_type}"
        )
    return entity_type


def _unique_objects_by_handle(
    items: list[dict[str, Any]],
    *,
    field: str,
    scope_index: int,
    step_index: int,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    result: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for item in items:
        handle = item.get("handle")
        key = handle if isinstance(handle, str) else repr(item)
        existing = by_key.get(key)
        if existing is not None:
            warnings.extend(
                _merge_duplicate_output_object(
                    existing,
                    item,
                    field=field,
                    handle=key,
                    scope_index=scope_index,
                    step_index=step_index,
                )
            )
            continue
        by_key[key] = item
        result.append(item)
    return result, tuple(warnings)


def _merge_duplicate_output_object(
    existing: dict[str, Any],
    duplicate: dict[str, Any],
    *,
    field: str,
    handle: str,
    scope_index: int,
    step_index: int,
) -> tuple[str, ...]:
    """Merge safe duplicate metadata and reject conflicting structural fields."""
    warnings: list[str] = []
    path = f"scopes[{scope_index}].steps[{step_index}].{field}"
    structural_fields = (
        ("entity_type", "valid_scope")
        if field == "creates"
        else ("valid_scope", "output_type")
    )
    for metadata_field in structural_fields:
        warning = _merge_duplicate_metadata_field(
            existing,
            duplicate,
            metadata_field,
            path=path,
            handle=handle,
        )
        if warning is not None:
            warnings.append(warning)
    warning = _merge_duplicate_description(
        existing,
        duplicate,
        path=path,
        handle=handle,
    )
    if warning is not None:
        warnings.append(warning)
    return tuple(warnings)


def _merge_duplicate_metadata_field(
    existing: dict[str, Any],
    duplicate: dict[str, Any],
    metadata_field: str,
    *,
    path: str,
    handle: str,
) -> str | None:
    left = existing.get(metadata_field)
    right = duplicate.get(metadata_field)
    if _empty_metadata(left) and not _empty_metadata(right):
        existing[metadata_field] = right
        return (
            "raw_output_duplicate_handle_field_merged: "
            f"{path} handle={handle} field={metadata_field}"
        )
    if _empty_metadata(right) or left == right:
        return None
    raise StrategyDraftValidationError(
        "raw_output_duplicate_handle_conflict: "
        f"{path} handle={handle} field={metadata_field} "
        f"existing={left!r} duplicate={right!r}"
    )


def _merge_duplicate_description(
    existing: dict[str, Any],
    duplicate: dict[str, Any],
    *,
    path: str,
    handle: str,
) -> str | None:
    left = existing.get("description")
    right = duplicate.get("description")
    if _empty_metadata(left) and not _empty_metadata(right):
        existing["description"] = right
        return (
            "raw_output_duplicate_handle_field_merged: "
            f"{path} handle={handle} field=description"
        )
    if _empty_metadata(right) or left == right:
        return None
    return (
        "raw_output_duplicate_handle_description_mismatch: "
        f"{path} handle={handle}; keeping first description"
    )


def _empty_metadata(value: object) -> bool:
    return value is None or value == ""


__all__ = [
    "RawStepOutputNormalizationResult",
    "normalize_raw_outputs",
]
