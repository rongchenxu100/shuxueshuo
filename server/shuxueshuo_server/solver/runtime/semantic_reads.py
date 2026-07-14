"""Semantic reads compatibility layer.

This module accepts LLM-facing ``semantic_reads`` and resolves them to the
canonical ``reads`` handles consumed by the existing StepIntent runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Protocol

from shuxueshuo_server.solver.runtime.handle_alias_index import (
    COORDINATE_FACT_SUFFIXES,
    HandleAliasIndex,
    SEMANTIC_READ_KINDS,
    looks_like_canonical_ref,
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_name,
    _handle_scope,
    _parse_scoped_non_answer_handle,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    STEP_INTENT_OUTPUT_TYPES,
    SemanticReadResolution,
    SemanticReadResolutionError,
    SemanticReadResolutionReport,
    SemanticRef,
    StrategyDraftValidationError,
)

@dataclass(frozen=True)
class SemanticReadCatalogItem:
    """Internal semantic catalog item with its canonical handle."""

    handle: str
    kind: str
    ref: str
    scope: str
    valid_scope: str
    value_type: str | None = None
    source_step_id: str | None = None
    description: str = ""
    state_slot_id: str | None = None
    condition_id: str | None = None
    source_context_id: str | None = None
    prompt_visible: bool = True

    def to_prompt_payload(self) -> dict[str, Any]:
        """Return the LLM-facing payload without the canonical handle."""
        payload: dict[str, Any] = {
            "ref": self.ref,
            "kind": self.kind,
            "scope": self.scope,
            "valid_scope": self.valid_scope,
        }
        if self.value_type is not None:
            payload["value_type"] = self.value_type
        if self.source_step_id is not None:
            payload["from_step"] = self.source_step_id
        if self.description:
            payload["description"] = self.description
        return payload


class ContextSemanticReadSource(Protocol):
    """Planner context projection required by context-driven semantic reads."""

    def semantic_read_catalog(
        self,
        scope_id: str | None = None,
    ) -> tuple[SemanticReadCatalogItem, ...]:
        """Return internal semantic read catalog items."""
        ...

    def semantic_read_catalog_payload(self) -> dict[str, Any]:
        """Return prompt-facing semantic read catalog payload."""
        ...


class SemanticReadResolver:
    """Resolve raw StepIntent ``semantic_reads`` into canonical ``reads``."""

    def __init__(self, registry: CanonicalHandleRegistry) -> None:
        self.registry = registry

    def initial_catalog(self) -> tuple[SemanticReadCatalogItem, ...]:
        """Build semantic catalog items for problem-provided handles."""
        items: list[SemanticReadCatalogItem] = []
        entity_items: list[SemanticReadCatalogItem] = []
        for handle in sorted(self.registry.entity_handles):
            payload = self.registry.entity_payloads.get(handle, {})
            entity_items.append(
                SemanticReadCatalogItem(
                    handle=handle,
                    kind=handle.split(":", 1)[0],
                    ref=_handle_name(handle),
                    scope=_handle_scope(handle),
                    valid_scope=self.registry.handle_valid_scopes.get(
                        handle,
                        _handle_scope(handle),
                    ),
                    description=_description_from_payload(payload),
                )
            )
        items.extend(_disambiguate_entity_refs(entity_items))
        for handle in sorted(self.registry.fact_handles):
            payload = self.registry.fact_payloads.get(handle, {})
            items.append(
                SemanticReadCatalogItem(
                    handle=handle,
                    kind="fact",
                    ref=_semantic_name(handle),
                    scope=_handle_scope(handle),
                    valid_scope=self.registry.handle_valid_scopes.get(
                        handle,
                        _handle_scope(handle),
                    ),
                    value_type=self.registry.fact_types.get(handle),
                    description=_description_from_payload(payload),
                )
            )
        for handle in sorted(self.registry.answer_handles):
            valid_scope = self.registry.handle_valid_scopes.get(handle, "problem")
            items.append(
                SemanticReadCatalogItem(
                    handle=handle,
                    kind="answer",
                    ref=handle.removeprefix("answer:"),
                    scope=valid_scope,
                    valid_scope=valid_scope,
                    value_type=self.registry.answer_value_types.get(handle),
                )
            )
        return tuple(items)

    def initial_catalog_payload(self) -> dict[str, Any]:
        """Return the prompt-facing initial semantic read catalog."""
        items = self.initial_catalog()
        return {
            "items": [
                item.to_prompt_payload()
                for item in items
                if item.prompt_visible
            ],
            "item_count": len([item for item in items if item.prompt_visible]),
        }

    def resolve_payload(
        self,
        data: dict[str, Any],
    ) -> tuple[dict[str, Any], SemanticReadResolutionReport]:
        """Return a payload where semantic_reads have been replaced by reads."""
        raw_scopes = data.get("scopes")
        if not isinstance(raw_scopes, list):
            return data, SemanticReadResolutionReport()

        catalog = list(self.initial_catalog())
        resolutions: list[SemanticReadResolution] = []
        errors: list[SemanticReadResolutionError] = []
        fallbacks: list[SemanticReadFallback] = []
        warnings: list[str] = []
        new_scopes: list[Any] = []
        for scope_index, raw_scope in enumerate(raw_scopes):
            if not isinstance(raw_scope, dict):
                new_scopes.append(raw_scope)
                continue
            scope_id = raw_scope.get("scope_id")
            raw_steps = raw_scope.get("steps")
            if not isinstance(scope_id, str) or not isinstance(raw_steps, list):
                new_scopes.append(dict(raw_scope))
                continue
            new_steps: list[Any] = []
            for step_index, raw_step in enumerate(raw_steps):
                if not isinstance(raw_step, dict):
                    new_steps.append(raw_step)
                    continue
                step_id = raw_step.get("step_id")
                if not isinstance(step_id, str) or not step_id.strip():
                    step_id = f"scope_{scope_index}_step_{step_index}"
                normalized_step = dict(raw_step)
                try:
                    semantic_refs, semantic_warnings = _semantic_refs_from_raw_step(
                        raw_step,
                        scope_index=scope_index,
                        step_index=step_index,
                    )
                    warnings.extend(semantic_warnings)
                except StrategyDraftValidationError as exc:
                    errors.append(
                        _resolution_error(
                            step_id=step_id,
                            scope_id=scope_id,
                            semantic_ref=None,
                            message=str(exc),
                        )
                    )
                    semantic_refs = ()
                if semantic_refs:
                    reads: list[str] = []
                    step_errors: list[SemanticReadResolutionError] = []
                    overrode_legacy_reads = bool(raw_step.get("reads"))
                    for semantic_ref in semantic_refs:
                        try:
                            item, candidate_count = self._resolve_ref(
                                semantic_ref,
                                step_id=step_id,
                                scope_id=scope_id,
                                catalog=tuple(catalog),
                            )
                        except StrategyDraftValidationError as exc:
                            step_errors.append(
                                _resolution_error(
                                    step_id=step_id,
                                    scope_id=scope_id,
                                    semantic_ref=semantic_ref,
                                    message=str(exc),
                                )
                            )
                            continue
                        handle = item.handle
                        inferred_from_step = _inferred_from_step(
                            item,
                            semantic_ref,
                            candidate_count=candidate_count,
                        )
                        reads.append(handle)
                        resolutions.append(
                            SemanticReadResolution(
                                step_id=step_id,
                                scope_id=scope_id,
                                semantic_ref=semantic_ref,
                                handle=handle,
                                candidate_count=candidate_count,
                                overrode_legacy_reads=overrode_legacy_reads,
                                inferred_from_step=inferred_from_step,
                                state_slot_id=item.state_slot_id,
                                condition_id=item.condition_id,
                                source_context_id=item.source_context_id,
                            )
                        )
                    if step_errors:
                        errors.extend(step_errors)
                        normalized_step["reads"] = reads
                    else:
                        normalized_step["reads"] = reads
                elif "reads" not in normalized_step and "semantic_reads" in normalized_step:
                    normalized_step["reads"] = []
                normalized_step.pop("semantic_reads", None)
                new_steps.append(normalized_step)
                try:
                    dynamic_items = _dynamic_items_from_raw_step(
                        normalized_step,
                        scope_id,
                        step_id,
                        registry=self.registry,
                        scope_index=scope_index,
                        step_index=step_index,
                    )
                except StrategyDraftValidationError as exc:
                    errors.append(
                        _resolution_error(
                            step_id=step_id,
                            scope_id=scope_id,
                            semantic_ref=None,
                            message=str(exc),
                        )
                    )
                else:
                    catalog.extend(dynamic_items)
            new_scope = dict(raw_scope)
            new_scope["steps"] = new_steps
            new_scopes.append(new_scope)

        normalized = dict(data)
        normalized["scopes"] = new_scopes
        return normalized, SemanticReadResolutionReport(
            resolutions=tuple(resolutions),
            errors=tuple(errors),
            fallbacks=tuple(fallbacks),
            warnings=tuple(warnings),
            partially_resolved_payload=normalized if errors else None,
        )

    def _resolve_ref(
        self,
        semantic_ref: SemanticRef,
        *,
        step_id: str,
        scope_id: str,
        catalog: tuple[SemanticReadCatalogItem, ...],
    ) -> tuple[SemanticReadCatalogItem, int]:
        candidates = _matching_candidates(
            semantic_ref,
            scope_id=scope_id,
            catalog=catalog,
            registry=self.registry,
            match_handle=_looks_like_canonical_read_ref(semantic_ref.ref),
            allow_missing_from_step_inference=True,
        )
        if not candidates:
            candidates = _matching_candidates(
                semantic_ref,
                scope_id=scope_id,
                catalog=catalog,
                registry=self.registry,
                match_handle=False,
                allow_missing_from_step_inference=True,
            )
        if not candidates:
            candidates = _point_coordinate_fact_alias_candidates(
                semantic_ref,
                scope_id=scope_id,
                catalog=catalog,
                registry=self.registry,
            )
        if not candidates:
            kind_mismatch_candidates = _canonical_kind_mismatch_candidates(
                semantic_ref,
                scope_id=scope_id,
                catalog=catalog,
                registry=self.registry,
            )
            if kind_mismatch_candidates:
                expected_kinds = sorted({
                    item.kind
                    for item in kind_mismatch_candidates
                })
                raise StrategyDraftValidationError(
                    "semantic_read_kind_mismatch: "
                    f"step={step_id}, ref={semantic_ref.to_payload()}, "
                    f"expected_kinds={expected_kinds}"
                )
            scope_prefix_candidates = _missing_scope_prefix_candidates(
                semantic_ref,
                scope_id=scope_id,
                catalog=catalog,
                registry=self.registry,
            )
            if len(scope_prefix_candidates) > 1:
                visible = [
                    _catalog_candidate_payload(item)
                    for item in scope_prefix_candidates
                ]
                raise StrategyDraftValidationError(
                    "semantic_read_ambiguous_missing_scope_prefix: "
                    f"step={step_id}, ref={semantic_ref.to_payload()}, "
                    f"candidates={visible}"
                )
            value_type_candidates = _value_type_mismatch_candidates(
                semantic_ref,
                scope_id=scope_id,
                catalog=catalog,
                registry=self.registry,
            )
            value_type_hint = ""
            if value_type_candidates:
                available_value_types = sorted({
                    item.value_type
                    for item in value_type_candidates
                    if item.value_type is not None
                })
                value_type_hint = (
                    f", available_value_types={available_value_types}"
                )
            raise StrategyDraftValidationError(
                "semantic_read_unknown: "
                f"step={step_id}, ref={semantic_ref.to_payload()}"
                f"{value_type_hint}"
            )
        if len(candidates) > 1:
            unique_handles = {item.handle for item in candidates}
            if len(unique_handles) == 1:
                return candidates[0], len(candidates)
            visible = [
                _catalog_candidate_payload(item)
                for item in candidates
            ]
            if (
                semantic_ref.from_step is None
                and any(item.source_step_id is not None for item in candidates)
            ):
                raise StrategyDraftValidationError(
                    "semantic_read_ambiguous_missing_from_step: "
                    f"step={step_id}, ref={semantic_ref.to_payload()}, candidates={visible}"
                )
            raise StrategyDraftValidationError(
                "semantic_read_ambiguous: "
                f"step={step_id}, ref={semantic_ref.to_payload()}, candidates={visible}"
            )
        return candidates[0], len(candidates)


class ContextSemanticReadResolver(SemanticReadResolver):
    """Resolve semantic reads against a PlannerStateContext projection first."""

    def __init__(
        self,
        registry: CanonicalHandleRegistry,
        planner_state_context: ContextSemanticReadSource,
    ) -> None:
        super().__init__(registry)
        self.planner_state_context = planner_state_context

    def initial_catalog(self) -> tuple[SemanticReadCatalogItem, ...]:
        return self.planner_state_context.semantic_read_catalog()

    def initial_catalog_payload(self) -> dict[str, Any]:
        return self.planner_state_context.semantic_read_catalog_payload()


def _inferred_from_step(
    item: SemanticReadCatalogItem,
    semantic_ref: SemanticRef,
    *,
    candidate_count: int,
) -> str | None:
    """Only report implicit from_step inference for a single visible candidate."""
    if candidate_count != 1:
        return None
    if semantic_ref.from_step is not None:
        return None
    return item.source_step_id


def build_semantic_read_catalog_payload(
    registry: CanonicalHandleRegistry,
    planner_state_context: ContextSemanticReadSource | None = None,
) -> dict[str, Any]:
    """Build the prompt-facing semantic read catalog."""
    if planner_state_context is not None:
        return ContextSemanticReadResolver(
            registry,
            planner_state_context,
        ).initial_catalog_payload()
    return SemanticReadResolver(registry).initial_catalog_payload()


def payload_has_nonempty_semantic_reads(data: object) -> bool:
    """Return whether raw payload needs semantic read resolver pre-processing."""
    if not isinstance(data, dict):
        return False
    raw_scopes = data.get("scopes")
    if not isinstance(raw_scopes, list):
        return False
    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, dict):
            continue
        raw_steps = raw_scope.get("steps")
        if not isinstance(raw_steps, list):
            continue
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                continue
            if "semantic_reads" not in raw_step:
                continue
            semantic_reads = raw_step.get("semantic_reads")
            if isinstance(semantic_reads, list) and semantic_reads:
                return True
    return False


def _semantic_refs_from_raw_step(
    raw_step: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
) -> tuple[tuple[SemanticRef, ...], tuple[str, ...]]:
    if "semantic_reads" not in raw_step:
        return (), ()
    value = raw_step.get("semantic_reads")
    if not isinstance(value, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].semantic_reads must be an object array"
        )
    refs: list[SemanticRef] = []
    warnings: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                "scopes"
                f"[{scope_index}].steps[{step_index}].semantic_reads[{item_index}] "
                "must be an object"
            )
        required = {"ref", "kind"}
        optional = {"value_type", "from_step"}
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required - optional)
        if missing:
            raise StrategyDraftValidationError(
                "scopes"
                f"[{scope_index}].steps[{step_index}].semantic_reads[{item_index}] "
                f"missing required fields: {', '.join(missing)}"
            )
        if extra:
            warnings.append(
                "semantic_read_extra_fields_ignored: "
                "scopes"
                f"[{scope_index}].steps[{step_index}].semantic_reads[{item_index}] "
                f"ignored fields: {', '.join(extra)}"
            )
        ref = _required_semantic_string(item, "ref", scope_index, step_index, item_index)
        kind = _required_semantic_string(item, "kind", scope_index, step_index, item_index)
        if kind not in SEMANTIC_READ_KINDS:
            raise StrategyDraftValidationError(
                "semantic_read_kind_unsupported: "
                f"step_index={step_index}, kind={kind}"
            )
        refs.append(
            SemanticRef(
                ref=ref,
                kind=kind,
                value_type=_optional_semantic_string(
                    item,
                    "value_type",
                    scope_index,
                    step_index,
                    item_index,
                ),
                from_step=_optional_semantic_string(
                    item,
                    "from_step",
                    scope_index,
                    step_index,
                    item_index,
                ),
            )
        )
    return tuple(refs), tuple(warnings)


def _required_semantic_string(
    item: dict[str, Any],
    key: str,
    scope_index: int,
    step_index: int,
    item_index: int,
) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(
            "scopes"
            f"[{scope_index}].steps[{step_index}].semantic_reads[{item_index}].{key} "
            "must be a non-empty string"
        )
    return value.strip()


def _optional_semantic_string(
    item: dict[str, Any],
    key: str,
    scope_index: int,
    step_index: int,
    item_index: int,
) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise StrategyDraftValidationError(
            "scopes"
            f"[{scope_index}].steps[{step_index}].semantic_reads[{item_index}].{key} "
            "must be a string or null"
        )
    text = value.strip()
    return text or None


def _source_matches(item: SemanticReadCatalogItem, semantic_ref: SemanticRef) -> bool:
    if semantic_ref.from_step is None:
        return item.source_step_id is None
    return item.source_step_id == semantic_ref.from_step


def _source_matches_or_can_infer(
    item: SemanticReadCatalogItem,
    semantic_ref: SemanticRef,
    *,
    allow_missing_from_step_inference: bool,
) -> bool:
    if _source_matches(item, semantic_ref):
        return True
    return (
        allow_missing_from_step_inference
        and semantic_ref.from_step is None
        and item.source_step_id is not None
    )


def _resolution_error(
    *,
    step_id: str,
    scope_id: str,
    semantic_ref: SemanticRef | None,
    message: str,
) -> SemanticReadResolutionError:
    return SemanticReadResolutionError(
        step_id=step_id,
        scope_id=scope_id,
        semantic_ref=semantic_ref,
        code=_semantic_error_code(message),
        message=message,
    )


def _semantic_error_code(message: str) -> str:
    if message.startswith("semantic_read"):
        return message.split(":", 1)[0]
    return "semantic_read_malformed"


def _matching_candidates(
    semantic_ref: SemanticRef,
    *,
    scope_id: str,
    catalog: tuple[SemanticReadCatalogItem, ...],
    registry: CanonicalHandleRegistry,
    match_handle: bool,
    allow_missing_from_step_inference: bool = False,
) -> list[SemanticReadCatalogItem]:
    candidates = [
        item
        for item in catalog
        if _semantic_ref_matches_item(
            item,
            semantic_ref,
            match_handle=match_handle,
        )
        and item.kind == semantic_ref.kind
        and _source_matches_or_can_infer(
            item,
            semantic_ref,
            allow_missing_from_step_inference=allow_missing_from_step_inference,
        )
        and _is_visible(item, scope_id, registry)
    ]
    return _filter_candidates_by_value_type_hint(candidates, semantic_ref)


def _filter_candidates_by_value_type_hint(
    candidates: list[SemanticReadCatalogItem],
    semantic_ref: SemanticRef,
) -> list[SemanticReadCatalogItem]:
    """Use ``value_type`` as a deterministic disambiguation hint, not identity.

    The LLM-facing field often names the mathematical role (for example
    ``symbol_value`` or ``minimum_expression``), while dynamic runtime outputs
    use canonical types such as ``ParameterValue`` or ``MinimumExpression``.
    If ref/kind/scope already identify one visible item, a non-structural
    value_type mismatch should not block the plan.
    """
    if semantic_ref.value_type is None or not candidates:
        return candidates
    exact_or_alias_matches = [
        item for item in candidates
        if _value_type_matches(item, semantic_ref)
    ]
    if exact_or_alias_matches:
        return exact_or_alias_matches
    if len(candidates) == 1 and _value_type_hint_can_be_ignored(
        candidates[0],
        semantic_ref,
    ):
        return candidates
    return []


def _point_coordinate_fact_alias_candidates(
    semantic_ref: SemanticRef,
    *,
    scope_id: str,
    catalog: tuple[SemanticReadCatalogItem, ...],
    registry: CanonicalHandleRegistry,
) -> list[SemanticReadCatalogItem]:
    """Allow ``kind=point`` to read a unique dynamic coordinate fact."""
    return HandleAliasIndex.point_coordinate_fact_items(
        kind=semantic_ref.kind,
        ref=semantic_ref.ref,
        from_step=semantic_ref.from_step,
        scope_id=scope_id,
        items=catalog,
        registry=registry,
        value_type_matches=lambda item: _value_type_matches(item, semantic_ref),
    )


def _semantic_ref_matches_item(
    item: SemanticReadCatalogItem,
    semantic_ref: SemanticRef,
    *,
    match_handle: bool,
) -> bool:
    if match_handle:
        return item.handle == semantic_ref.ref
    if item.ref == semantic_ref.ref:
        return True
    return item.handle == _scoped_handle_alias(semantic_ref)


def _scoped_handle_alias(semantic_ref: SemanticRef) -> str | None:
    """Map kind + ``scope:name`` shorthand to a canonical handle."""
    return HandleAliasIndex.scoped_ref_handle(
        kind=semantic_ref.kind,
        ref=semantic_ref.ref,
        allowed_kinds=SEMANTIC_READ_KINDS,
    )


def _looks_like_canonical_read_ref(ref: str) -> bool:
    """Return whether a semantic ref is already a canonical handle."""
    return looks_like_canonical_ref(ref, allowed_kinds=SEMANTIC_READ_KINDS)


def _canonical_kind_mismatch_candidates(
    semantic_ref: SemanticRef,
    *,
    scope_id: str,
    catalog: tuple[SemanticReadCatalogItem, ...],
    registry: CanonicalHandleRegistry,
) -> list[SemanticReadCatalogItem]:
    canonical_ref = (
        semantic_ref.ref
        if _looks_like_canonical_read_ref(semantic_ref.ref)
        else _scoped_handle_alias(semantic_ref)
    )
    if canonical_ref is None:
        return []
    return [
        item
        for item in catalog
        if item.handle == canonical_ref
        and item.kind != semantic_ref.kind
        and _source_matches_or_can_infer(
            item,
            semantic_ref,
            allow_missing_from_step_inference=True,
        )
        and _is_visible(item, scope_id, registry)
    ]


def _disambiguate_entity_refs(
    items: list[SemanticReadCatalogItem],
) -> tuple[SemanticReadCatalogItem, ...]:
    """Scope-qualify duplicate entity refs without exposing canonical handles."""
    counts: dict[tuple[str, str], int] = {}
    for item in items:
        key = (item.kind, item.ref)
        counts[key] = counts.get(key, 0) + 1
    return tuple(
        replace(item, ref=f"{item.scope}.{item.ref}")
        if counts[(item.kind, item.ref)] > 1
        else item
        for item in items
    )


def _value_type_matches(item: SemanticReadCatalogItem, semantic_ref: SemanticRef) -> bool:
    if semantic_ref.value_type is None:
        return True
    if item.value_type == semantic_ref.value_type:
        return True
    if _normalized_value_type(item.value_type) == _normalized_value_type(
        semantic_ref.value_type
    ):
        return True
    if _function_value_type_alias_matches(item, semantic_ref):
        return True
    return _dynamic_point_coordinate_alias_matches(item, semantic_ref)


def _value_type_hint_can_be_ignored(
    item: SemanticReadCatalogItem,
    semantic_ref: SemanticRef,
) -> bool:
    """Return whether a unique ref/kind match may ignore value_type mismatch."""
    if semantic_ref.value_type is None:
        return True
    if _requires_coordinate_fact_semantics(semantic_ref):
        return _dynamic_point_coordinate_alias_matches(item, semantic_ref)
    return True


def _requires_coordinate_fact_semantics(semantic_ref: SemanticRef) -> bool:
    return _normalized_value_type(semantic_ref.value_type) == "point_coordinate"


# LLM-facing value type aliases. This overlaps with output type inference today
# because semantic_reads accepts human labels before a canonical handle exists.
# Keep this table small and migrate toward a shared canonical type mapper when
# output type contracts become the single source of truth.
_VALUE_TYPE_ALIASES: dict[str, str] = {
    "angleequality": "AngleEquality",
    "coefficients": "Coefficients",
    "equation": "Equation",
    "expression": "Expression",
    "line": "Line",
    "minimumexpression": "MinimumExpression",
    "minimumvalueexpression": "MinimumExpression",
    "parabola": "Parabola",
    "quadratic": "Parabola",
    "quadraticfunction": "Parabola",
    "parametervalue": "ParameterValue",
    "parameter": "ParameterValue",
    "symbolvalue": "ParameterValue",
    "pathtransformation": "PathTransformation",
    "transformation": "PathTransformation",
    "point": "Point",
    "pointlist": "PointList",
    "straighteningcandidate": "StraighteningCandidate",
    "straightenedpathchoice": "StraighteningCandidate",
    "pointcoordinate": "point_coordinate",
    "coordinate": "point_coordinate",
    "coordinateexpression": "point_coordinate",
}


def _normalized_value_type(value_type: str | None) -> str | None:
    if value_type is None:
        return None
    key = re.sub(r"[^A-Za-z0-9]+", "", value_type).lower()
    return _VALUE_TYPE_ALIASES.get(key, value_type)


def _function_value_type_alias_matches(
    item: SemanticReadCatalogItem,
    semantic_ref: SemanticRef,
) -> bool:
    """Allow LLM-facing quadratic function labels for untyped function entities."""
    return (
        semantic_ref.kind == "function"
        and semantic_ref.value_type == "quadratic"
        and item.kind == "function"
        and item.value_type is None
    )


def _dynamic_point_coordinate_alias_matches(
    item: SemanticReadCatalogItem,
    semantic_ref: SemanticRef,
) -> bool:
    """Allow LLM-facing coordinate types for dynamic Point outputs."""
    if semantic_ref.value_type not in {"point_coordinate", "point"}:
        return False
    if item.value_type != "Point":
        return False
    if item.source_step_id is None or item.kind != "fact":
        return False
    return _is_coordinate_fact_item(item)


def _is_coordinate_fact_item(item: SemanticReadCatalogItem) -> bool:
    if not item.handle.startswith("fact:"):
        return False
    return any(
        item.ref.endswith(suffix) or _semantic_name(item.handle).endswith(suffix)
        for suffix in COORDINATE_FACT_SUFFIXES
    )


def _missing_scope_prefix_candidates(
    semantic_ref: SemanticRef,
    *,
    scope_id: str,
    catalog: tuple[SemanticReadCatalogItem, ...],
    registry: CanonicalHandleRegistry,
) -> list[SemanticReadCatalogItem]:
    return HandleAliasIndex.missing_scope_prefix_items(
        ref=semantic_ref.ref,
        kind=semantic_ref.kind,
        scope_id=scope_id,
        items=catalog,
        registry=registry,
        source_matches=lambda item: _source_matches(item, semantic_ref),
        value_type_matches=lambda item: _value_type_matches(item, semantic_ref),
    )


def _value_type_mismatch_candidates(
    semantic_ref: SemanticRef,
    *,
    scope_id: str,
    catalog: tuple[SemanticReadCatalogItem, ...],
    registry: CanonicalHandleRegistry,
) -> list[SemanticReadCatalogItem]:
    if semantic_ref.value_type is None:
        return []
    return [
        item
        for item in catalog
        if (
            item.ref == semantic_ref.ref
            or item.handle == semantic_ref.ref
            or item.handle == _scoped_handle_alias(semantic_ref)
        )
        and item.kind == semantic_ref.kind
        and _source_matches_or_can_infer(
            item,
            semantic_ref,
            allow_missing_from_step_inference=True,
        )
        and not _value_type_matches(item, semantic_ref)
        and _is_visible(item, scope_id, registry)
    ]


def _catalog_candidate_payload(item: SemanticReadCatalogItem) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ref": item.ref,
        "kind": item.kind,
        "scope": item.scope,
        "valid_scope": item.valid_scope,
    }
    if item.value_type is not None:
        payload["value_type"] = item.value_type
    if item.source_step_id is not None:
        payload["from_step"] = item.source_step_id
    return payload


def _is_visible(
    item: SemanticReadCatalogItem,
    scope_id: str,
    registry: CanonicalHandleRegistry,
) -> bool:
    return visible_from_valid_scope(
        item.valid_scope,
        scope_id=scope_id,
        registry=registry,
    )


def _dynamic_items_from_raw_step(
    raw_step: dict[str, Any],
    scope_id: str,
    step_id: str,
    *,
    registry: CanonicalHandleRegistry,
    scope_index: int,
    step_index: int,
) -> tuple[SemanticReadCatalogItem, ...]:
    items: list[SemanticReadCatalogItem] = []
    for created in _created_entities_from_raw_step(
        raw_step,
        scope_index=scope_index,
        step_index=step_index,
    ):
        items.append(
            SemanticReadCatalogItem(
                handle=created.handle,
                kind=created.entity_type,
                ref=_handle_name(created.handle),
                scope=_handle_scope(created.handle),
                valid_scope=created.valid_scope,
                source_step_id=step_id,
                description=created.description,
            )
        )
    for produced in _produced_facts_from_raw_step(
        raw_step,
        scope_index=scope_index,
        step_index=step_index,
    ):
        kind = "answer" if produced.handle.startswith("answer:") else "fact"
        ref = (
            produced.handle.removeprefix("answer:")
            if kind == "answer"
            else _semantic_name(produced.handle)
        )
        items.append(
            SemanticReadCatalogItem(
                handle=produced.handle,
                kind=kind,
                ref=ref,
                scope=produced.valid_scope if kind == "answer" else _handle_scope(produced.handle),
                valid_scope=produced.valid_scope,
                value_type=produced.output_type,
                source_step_id=step_id,
                description=produced.description,
            )
        )
        items.extend(
            _answer_target_state_aliases(
                produced,
                step_id=step_id,
                registry=registry,
            )
        )
    return tuple(items)


def _answer_target_state_aliases(
    produced: ProducedFact,
    *,
    step_id: str,
    registry: CanonicalHandleRegistry,
) -> tuple[SemanticReadCatalogItem, ...]:
    """Project a Point answer onto its authored target object's state slot."""
    if not produced.handle.startswith("answer:"):
        return ()
    if produced.output_type not in {"Point", "PointList"}:
        return ()
    target_handle = registry.answer_target_handles.get(produced.handle)
    if target_handle is None or not target_handle.startswith("point:"):
        return ()
    point_name = _handle_name(target_handle)
    target_scope = _handle_scope(target_handle)
    valid_scope = registry.handle_valid_scopes.get(target_handle, target_scope)
    coordinate_ref = f"{point_name}_coordinate"
    return (
        SemanticReadCatalogItem(
            handle=target_handle,
            kind="point",
            ref=point_name,
            scope=target_scope,
            valid_scope=valid_scope,
            value_type=produced.output_type,
            source_step_id=step_id,
            description=produced.description,
        ),
        SemanticReadCatalogItem(
            handle=target_handle,
            kind="fact",
            ref=coordinate_ref,
            scope=produced.valid_scope,
            valid_scope=valid_scope,
            value_type=produced.output_type,
            source_step_id=step_id,
            description=produced.description,
            prompt_visible=False,
        ),
        SemanticReadCatalogItem(
            handle=target_handle,
            kind="fact",
            ref=f"fact:{produced.valid_scope}:{coordinate_ref}",
            scope=produced.valid_scope,
            valid_scope=valid_scope,
            value_type=produced.output_type,
            source_step_id=step_id,
            description=produced.description,
            prompt_visible=False,
        ),
    )


def _created_entities_from_raw_step(
    raw_step: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
) -> tuple[CreatedEntity, ...]:
    raw_creates = raw_step.get("creates")
    if not isinstance(raw_creates, list):
        raise StrategyDraftValidationError(
            _dynamic_catalog_error(
                f"scopes[{scope_index}].steps[{step_index}].creates must be an object array"
            )
        )
    result: list[CreatedEntity] = []
    for item_index, item in enumerate(raw_creates):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    f"scopes[{scope_index}].steps[{step_index}].creates[{item_index}] must be an object"
                )
            )
        required = {"handle", "entity_type", "valid_scope", "description"}
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required)
        if missing:
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    "scopes"
                    f"[{scope_index}].steps[{step_index}].creates[{item_index}] "
                    f"missing required fields: {', '.join(missing)}"
                )
            )
        if extra:
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    "scopes"
                    f"[{scope_index}].steps[{step_index}].creates[{item_index}] "
                    f"contains unsupported fields: {', '.join(extra)}"
                )
            )
        handle = _dynamic_catalog_required_string(
            item,
            "handle",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        entity_type = _dynamic_catalog_required_string(
            item,
            "entity_type",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        valid_scope = _dynamic_catalog_required_string(
            item,
            "valid_scope",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        description = _dynamic_catalog_required_string(
            item,
            "description",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        parsed = _parse_scoped_non_answer_handle(handle)
        if parsed is None or parsed[0] != entity_type:
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    "scopes"
                    f"[{scope_index}].steps[{step_index}].creates[{item_index}] "
                    f"invalid entity handle/type: handle={handle}, entity_type={entity_type}"
                )
            )
        result.append(
            CreatedEntity(
                handle=handle,
                entity_type=entity_type,
                valid_scope=valid_scope,
                description=description,
            )
        )
    return tuple(result)


def _produced_facts_from_raw_step(
    raw_step: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
) -> tuple[ProducedFact, ...]:
    raw_produces = raw_step.get("produces")
    if not isinstance(raw_produces, list):
        raise StrategyDraftValidationError(
            _dynamic_catalog_error(
                f"scopes[{scope_index}].steps[{step_index}].produces must be an object array"
            )
        )
    result: list[ProducedFact] = []
    for item_index, item in enumerate(raw_produces):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    f"scopes[{scope_index}].steps[{step_index}].produces[{item_index}] must be an object"
                )
            )
        required = {"handle", "valid_scope", "description"}
        optional = {"output_type"}
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required - optional)
        if missing:
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    "scopes"
                    f"[{scope_index}].steps[{step_index}].produces[{item_index}] "
                    f"missing required fields: {', '.join(missing)}"
                )
            )
        if extra:
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    "scopes"
                    f"[{scope_index}].steps[{step_index}].produces[{item_index}] "
                    f"contains unsupported fields: {', '.join(extra)}"
                )
            )
        handle = _dynamic_catalog_required_string(
            item,
            "handle",
            field="produces",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        valid_scope = _dynamic_catalog_required_string(
            item,
            "valid_scope",
            field="produces",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        description = _dynamic_catalog_required_string(
            item,
            "description",
            field="produces",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        output_type = _dynamic_catalog_optional_output_type(
            item,
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        if not (handle.startswith("answer:") or _is_fact_handle(handle)):
            raise StrategyDraftValidationError(
                _dynamic_catalog_error(
                    "scopes"
                    f"[{scope_index}].steps[{step_index}].produces[{item_index}] "
                    f"invalid produce handle: {handle}; expected fact:* or answer:*"
                )
            )
        result.append(
            ProducedFact(
                handle=handle,
                valid_scope=valid_scope,
                description=description,
                output_type=output_type,
            )
        )
    return tuple(result)


def _dynamic_catalog_required_string(
    raw_output: dict[str, Any],
    key: str,
    *,
    field: str,
    scope_index: int,
    step_index: int,
    item_index: int,
) -> str:
    value = raw_output.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(
            _dynamic_catalog_error(
                "scopes"
                f"[{scope_index}].steps[{step_index}].{field}[{item_index}].{key} "
                "must be a string"
            )
        )
    return value.strip()


def _dynamic_catalog_optional_output_type(
    raw_output: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
    item_index: int,
) -> str | None:
    if "output_type" not in raw_output or raw_output.get("output_type") is None:
        return None
    value = raw_output.get("output_type")
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(
            _dynamic_catalog_error(
                "scopes"
                f"[{scope_index}].steps[{step_index}].produces[{item_index}].output_type "
                "must be a string"
            )
        )
    output_type = value.strip()
    if output_type not in STEP_INTENT_OUTPUT_TYPES:
        raise StrategyDraftValidationError(
            _dynamic_catalog_error(
                "scopes"
                f"[{scope_index}].steps[{step_index}].produces[{item_index}].output_type "
                f"unsupported: {output_type}"
            )
        )
    return output_type


def _is_fact_handle(handle: str) -> bool:
    parsed = _parse_scoped_non_answer_handle(handle)
    return parsed is not None and parsed[0] == "fact"


def _dynamic_catalog_error(detail: str) -> str:
    return f"semantic_read_dynamic_catalog_malformed: {detail}"


def _description_from_payload(payload: dict[str, Any]) -> str:
    description = payload.get("description")
    return description.strip() if isinstance(description, str) else ""
