"""Wire and reconciliation models for the strict FunctionalPlan protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.contracts import FunctionalResultForm
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityDependencyPolicy,
)
from shuxueshuo_server.solver.runtime.condition_roles import ConditionObjectRoles
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpec
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpec
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef, StepIntentDraft
from shuxueshuo_server.solver.state_semantics import (
    dependent_role_object_ref,
    derived_role_object_ref,
    is_object_handle,
    is_object_semantic_kind,
)

FunctionalCapabilityKind = Literal["function", "macro"]
FunctionalIssueLayer = Literal[
    "functional_validation",
    "functional_elaboration",
    "functional_reconciliation",
]
FunctionalArgMode = Literal["explicit", "optional", "auto"]
FunctionalAggregation = Literal[
    "none",
    "coefficients_by_symbol",
    "point_list",
    "symbol_list",
]
FunctionalCallStatus = Literal["valid", "invalid", "blocked_by_dependency"]
FunctionalResultFormEventStatus = Literal[
    "matched",
    "result_form_closed",
    "mismatch",
    "provenance_missing",
]


@dataclass(frozen=True)
class CallResultRef:
    """A reference to an earlier call's declared return role."""

    from_call: str
    return_name: str

    def to_payload(self) -> dict[str, str]:
        return {"from_call": self.from_call, "return": self.return_name}


FunctionalRef = SemanticRef | CallResultRef


@dataclass(frozen=True)
class FunctionalCall:
    call_id: str
    capability_id: str
    args: dict[str, tuple[FunctionalRef, ...]]
    return_bindings: dict[str, SemanticRef]
    strategy: str
    reason: str
    return_expectations: dict[str, FunctionalResultForm] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        args: dict[str, Any] = {}
        for name, values in self.args.items():
            payloads = [item.to_payload() for item in values]
            args[name] = payloads[0] if len(payloads) == 1 else payloads
        payload = {
            "call_id": self.call_id,
            "capability_id": self.capability_id,
            "args": args,
            "return_bindings": {
                name: value.to_payload()
                for name, value in self.return_bindings.items()
            },
            "strategy": self.strategy,
            "reason": self.reason,
        }
        if self.return_expectations:
            payload["return_expectations"] = dict(self.return_expectations)
        return payload


@dataclass(frozen=True)
class FunctionalScope:
    scope_id: str
    label: str
    calls: tuple[FunctionalCall, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "label": self.label,
            "calls": [item.to_payload() for item in self.calls],
        }


@dataclass(frozen=True)
class FunctionalPlan:
    scopes: tuple[FunctionalScope, ...]
    format: str = "functional_plan/v1"

    @property
    def calls(self) -> tuple[FunctionalCall, ...]:
        return tuple(call for scope in self.scopes for call in scope.calls)

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "scopes": [item.to_payload() for item in self.scopes],
        }


@dataclass(frozen=True)
class FunctionalPlanIssue:
    layer: FunctionalIssueLayer
    code: str
    message: str
    call_id: str | None = None
    scope_id: str | None = None
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "layer": self.layer,
            "code": self.code,
            "message": self.message,
            "call_id": self.call_id,
            "scope_id": self.scope_id,
        }
        if self.details is not None:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class FunctionalPlanValidationReport:
    issues: tuple[FunctionalPlanIssue, ...] = ()
    partially_parsed_payload: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [item.to_payload() for item in self.issues],
            "partially_parsed_payload": self.partially_parsed_payload,
        }


@dataclass(frozen=True)
class FunctionalCapabilityArg:
    name: str
    runtime_type: str
    required: bool
    cardinality: str
    kind: str
    semantic_role: str | None = None
    llm_mode: FunctionalArgMode = "explicit"
    accepted_item_types: tuple[str, ...] = ()
    accepted_condition_kinds: tuple[str, ...] = ()
    accepted_semantic_roles: tuple[str, ...] = ()
    requires_materialized_state: bool = False
    aggregation: FunctionalAggregation = "none"
    runtime_input: str | None = None
    deterministic_resolver: str | None = None
    description: str = ""
    provides_semantic_roles: tuple[str, ...] = ()

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "accepts": list(
                self.accepted_item_types or (self.runtime_type,)
            ),
            "required": self.required,
            "cardinality": self.cardinality,
        }
        if self.accepted_condition_kinds:
            payload["fact_types"] = list(
                self.accepted_condition_kinds
            )
        if self.accepted_semantic_roles:
            payload["roles"] = list(
                self.accepted_semantic_roles
            )
        if self.requires_materialized_state:
            payload["requires_computed_value"] = True
        if self.description:
            payload["desc"] = self.description
        return payload


@dataclass(frozen=True)
class FunctionalAutoArg:
    name: str
    selector: str
    required: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "selector": self.selector,
            "required": self.required,
        }


@dataclass(frozen=True)
class FunctionalCapabilityReturn:
    name: str
    runtime_type: str
    required: bool
    cardinality: str
    state_kind: str
    semantic_role: str
    identity_policy: str
    identity_arg: str | None
    write_mode: str
    description: str = ""
    possible_forms: tuple[FunctionalResultForm, ...] = ()
    result_form_description: str = ""

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.runtime_type,
            "binding": _prompt_return_binding(self),
        }
        if not self.required:
            payload["required"] = False
        if self.cardinality != "one":
            payload["cardinality"] = self.cardinality
        description = _joined_description(
            self.description,
            self.result_form_description,
        )
        if description:
            payload["desc"] = description
        if self.possible_forms:
            payload["possible_forms"] = list(self.possible_forms)
        return payload


@dataclass(frozen=True)
class FunctionalContextArgBinding:
    """Internal projection from a resolver role to one runtime argument."""

    resolver_id: CapabilityContextResolver
    semantic_role: str
    arg_name: str


def _joined_description(*parts: str) -> str:
    values = tuple(dict.fromkeys(item.strip() for item in parts if item.strip()))
    return " ".join(values)


@dataclass(frozen=True)
class FunctionalCapability:
    capability_id: str
    kind: FunctionalCapabilityKind
    goal_types: tuple[str, ...]
    title: str
    use_when: str
    do_not_use_when: tuple[str, ...]
    args: tuple[FunctionalCapabilityArg, ...]
    returns: tuple[FunctionalCapabilityReturn, ...]
    source: FunctionSpec | MacroSpec = field(repr=False)
    is_pure: bool
    dependency_policy: CapabilityDependencyPolicy
    reconciliation_validators: tuple[str, ...] = field(default=(), repr=False)
    context_resolvers: tuple[CapabilityContextResolver, ...] = field(
        default=(),
        repr=False,
    )
    context_arg_bindings: tuple[FunctionalContextArgBinding, ...] = field(
        default=(),
        repr=False,
    )
    auto_args: tuple[FunctionalAutoArg, ...] = field(default=(), repr=False)
    context_preflight_selectors: tuple[str, ...] = field(
        default=(),
        repr=False,
    )

    @property
    def goal_type(self) -> str:
        """Return the canonical execution goal derived from this capability."""
        if not self.goal_types:
            raise ValueError(
                "planner_configuration_error: functional capability has no "
                f"goal type: {self.capability_id}"
            )
        return self.goal_types[0]

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability_id": self.capability_id,
            "title": self.title,
            "use_when": self.use_when,
            "args": [item.to_prompt_payload() for item in self.args],
            "returns": [item.to_prompt_payload() for item in self.returns],
        }
        if self.do_not_use_when:
            payload["do_not_use_when"] = list(self.do_not_use_when)
        return payload


def _prompt_return_binding(result: FunctionalCapabilityReturn) -> str:
    if result.identity_policy == "derived_role":
        return "internal_only"
    if result.identity_policy == "preserve_input_object":
        return (
            f"same_object_as:{result.identity_arg}"
            if result.identity_arg
            else "same_input_object"
        )
    return "answer_or_existing_object"

@dataclass(frozen=True)
class ResolvedFunctionalValue:
    handle: str
    runtime_type: str | None
    valid_scope: str
    state_slot_id: str | None = None
    source_call_id: str | None = None
    return_name: str | None = None
    object_ref: str | None = None
    condition_id: str | None = None
    object_roles: ConditionObjectRoles = ()
    dependency_object_refs: tuple[str, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "runtime_type": self.runtime_type,
            "valid_scope": self.valid_scope,
            "state_slot_id": self.state_slot_id,
            "source_call_id": self.source_call_id,
            "return_name": self.return_name,
            "object_ref": self.object_ref,
            "condition_id": self.condition_id,
            "object_roles": {
                role: list(object_refs)
                for role, object_refs in self.object_roles
            },
            "dependency_object_refs": list(self.dependency_object_refs),
            "free_symbol_refs": list(self.free_symbol_refs),
            "source_state_slot_ids": list(self.source_state_slot_ids),
        }


@dataclass(frozen=True)
class FunctionalReturnAllocation:
    call_id: str
    return_name: str
    handle: str
    runtime_type: str
    valid_scope: str
    state_slot_id: str
    object_ref: str | None
    identity_policy: str
    write_mode: str
    bound_ref: SemanticRef | None = None
    dependency_object_refs: tuple[str, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "return_name": self.return_name,
            "handle": self.handle,
            "runtime_type": self.runtime_type,
            "valid_scope": self.valid_scope,
            "state_slot_id": self.state_slot_id,
            "object_ref": self.object_ref,
            "identity_policy": self.identity_policy,
            "write_mode": self.write_mode,
            "bound_ref": self.bound_ref.to_payload() if self.bound_ref else None,
            "dependency_object_refs": list(self.dependency_object_refs),
            "free_symbol_refs": list(self.free_symbol_refs),
            "source_state_slot_ids": list(self.source_state_slot_ids),
        }


@dataclass(frozen=True)
class FunctionalCallReconciliation:
    call_id: str
    scope_id: str
    capability_id: str
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]]
    returns: tuple[FunctionalReturnAllocation, ...]
    reads_closed: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "scope_id": self.scope_id,
            "capability_id": self.capability_id,
            "resolved_args": {
                name: [item.to_payload() for item in values]
                for name, values in self.resolved_args.items()
            },
            "returns": [item.to_payload() for item in self.returns],
            "reads_closed": self.reads_closed,
        }


@dataclass(frozen=True)
class FunctionalCallReport:
    call_id: str
    scope_id: str
    capability_id: str
    status: FunctionalCallStatus
    issue_codes: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "scope_id": self.scope_id,
            "capability_id": self.capability_id,
            "status": self.status,
            "issue_codes": list(self.issue_codes),
            "blocked_by": list(self.blocked_by),
        }


@dataclass(frozen=True)
class FunctionalResultFormEvent:
    call_id: str
    scope_id: str
    return_name: str
    expected_form: FunctionalResultForm
    actual_form: FunctionalResultForm | None
    status: FunctionalResultFormEventStatus
    free_symbol_names: tuple[str, ...] = ()
    available_parameter_states: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "scope_id": self.scope_id,
            "return": self.return_name,
            "expected_form": self.expected_form,
            "actual_form": self.actual_form,
            "status": self.status,
            "free_symbol_names": list(self.free_symbol_names),
            "available_parameter_states": list(self.available_parameter_states),
        }


@dataclass(frozen=True)
class FunctionalCallPlacement:
    """Code-owned placement for one canonical FunctionalPlan call."""

    canonical_call_id: str
    alias_call_ids: tuple[str, ...]
    declared_scope_id: str
    execution_scope_id: str
    return_scopes: dict[str, str]
    dependency_call_ids: tuple[str, ...]
    placement_reason: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "canonical_call_id": self.canonical_call_id,
            "alias_call_ids": list(self.alias_call_ids),
            "declared_scope_id": self.declared_scope_id,
            "execution_scope_id": self.execution_scope_id,
            "return_scopes": dict(self.return_scopes),
            "dependency_call_ids": list(self.dependency_call_ids),
            "placement_reason": self.placement_reason,
        }


@dataclass(frozen=True)
class FunctionalProjectionEntry:
    call_id: str
    step_ids: tuple[str, ...]
    state_slot_ids: tuple[str, ...]
    canonical_call_id: str | None = None
    alias_call_ids: tuple[str, ...] = ()
    declared_scope_id: str | None = None
    execution_scope_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "step_ids": list(self.step_ids),
            "state_slot_ids": list(self.state_slot_ids),
            "canonical_call_id": self.canonical_call_id or self.call_id,
            "alias_call_ids": list(self.alias_call_ids),
            "declared_scope_id": self.declared_scope_id,
            "execution_scope_id": self.execution_scope_id,
        }


@dataclass(frozen=True)
class FunctionalPlanReconciliationResult:
    plan: FunctionalPlan
    calls: tuple[FunctionalCallReconciliation, ...] = ()
    issues: tuple[FunctionalPlanIssue, ...] = ()
    projection_map: tuple[FunctionalProjectionEntry, ...] = ()
    context_delta: dict[str, Any] = field(default_factory=dict)
    projected_draft: StepIntentDraft | None = None
    partial_projected_draft: StepIntentDraft | None = None
    call_reports: tuple[FunctionalCallReport, ...] = ()
    dependency_graph: dict[str, tuple[str, ...]] = field(default_factory=dict)
    call_placements: tuple[FunctionalCallPlacement, ...] = ()
    call_aliases: dict[str, str] = field(default_factory=dict)
    elaboration: dict[str, Any] | None = None
    result_form_events: tuple[FunctionalResultFormEvent, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues and self.projected_draft is not None

    @property
    def effective_plan(self) -> FunctionalPlan:
        """Return the canonical candidate consumed by replay and retry."""
        return self.plan

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": "planner_state_context",
            "effective_plan": self.effective_plan.to_payload(),
            "calls": [item.to_payload() for item in self.calls],
            "issues": [item.to_payload() for item in self.issues],
            "projection_map": [item.to_payload() for item in self.projection_map],
            "context_delta": dict(self.context_delta),
            "call_reports": [item.to_payload() for item in self.call_reports],
            "dependency_graph": {
                key: list(value) for key, value in self.dependency_graph.items()
            },
            "call_placements": [
                item.to_payload() for item in self.call_placements
            ],
            "call_aliases": dict(self.call_aliases),
            "elaboration": self.elaboration,
            "result_form_events": [
                item.to_payload() for item in self.result_form_events
            ],
            "projected_draft": (
                self.projected_draft.to_payload()
                if self.projected_draft is not None
                else None
            ),
            "partial_projected_draft": (
                self.partial_projected_draft.to_payload()
                if self.partial_projected_draft is not None
                else None
            ),
        }


class CanonicalStateHandleFactory:
    """Allocate deterministic canonical state handles for call returns."""

    def handle_for(
        self,
        *,
        call_id: str,
        return_spec: FunctionalCapabilityReturn,
        valid_scope: str,
        binding: SemanticReadCatalogItem | None,
    ) -> str:
        if binding is not None and binding.kind == "answer":
            return binding.handle
        if binding is not None and is_object_semantic_kind(binding.kind):
            object_name = _safe_name(binding.handle.rsplit(":", 1)[-1])
            state_name = _safe_name(
                return_spec.semantic_role
                if return_spec.write_mode == "transition"
                else return_spec.state_kind
            )
            return f"fact:{valid_scope}:{object_name}_{state_name}"
        role = _safe_name(return_spec.semantic_role or return_spec.name)
        return f"fact:{valid_scope}:{_safe_name(call_id)}_{role}"

    def object_ref_for(
        self,
        *,
        call_id: str,
        return_spec: FunctionalCapabilityReturn,
        valid_scope: str,
        binding: SemanticReadCatalogItem | None,
        resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
        handle_registry: CanonicalHandleRegistry,
        sibling_returns: tuple[FunctionalReturnAllocation, ...] = (),
    ) -> str | None:
        if return_spec.identity_policy == "preserve_input_object":
            values = resolved_args.get(return_spec.identity_arg or "", ())
            if values:
                return values[0].object_ref or _entity_handle_or_none(
                    values[0].handle
                )
        if (
            return_spec.identity_policy == "target_object"
            and return_spec.identity_arg
        ):
            values = resolved_args.get(return_spec.identity_arg, ())
            if values:
                return values[0].object_ref or _entity_handle_or_none(
                    values[0].handle
                )
        if binding is not None:
            if binding.kind == "answer":
                return handle_registry.answer_target_handles.get(binding.handle)
            if is_object_semantic_kind(binding.kind):
                return binding.handle
        if (
            return_spec.identity_policy == "derived_role"
            and return_spec.identity_arg
        ):
            values = resolved_args.get(return_spec.identity_arg, ())
            source_object_refs = {
                value.object_ref
                for value in values
                if value.object_ref is not None
            }
            if not source_object_refs:
                source_object_refs = {
                    item.object_ref
                    for item in sibling_returns
                    if item.object_ref is not None
                }
            if len(source_object_refs) == 1:
                return dependent_role_object_ref(
                    source_object_ref=next(iter(source_object_refs)),
                    semantic_role=(
                        return_spec.semantic_role or return_spec.name
                    ),
                    scope_id=valid_scope,
                    runtime_type=return_spec.runtime_type,
                )
        if (
            return_spec.identity_policy == "derived_role"
            and return_spec.runtime_type == "Point"
        ):
            return derived_role_object_ref(
                call_id=call_id,
                semantic_role=return_spec.semantic_role or return_spec.name,
                scope_id=valid_scope,
                runtime_type=return_spec.runtime_type,
            )
        if (
            return_spec.runtime_type == "Point"
            and return_spec.write_mode == "create"
        ):
            role = _safe_name(return_spec.semantic_role or return_spec.name)
            return f"point:{valid_scope}:{_safe_name(call_id)}_{role}"
        return None



def _issue(
    layer: FunctionalIssueLayer,
    code: str,
    message: str,
    *,
    call_id: str | None = None,
    scope_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> FunctionalPlanIssue:
    return FunctionalPlanIssue(layer, code, message, call_id, scope_id, details)


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return text or "state"


def _entity_handle_or_none(handle: str) -> str | None:
    return handle if is_object_handle(handle) else None
