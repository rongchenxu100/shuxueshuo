"""Wire and reconciliation models for the strict FunctionalPlan protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.contracts import (
    FunctionalResultForm,
    MethodInputViewMode,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityDependencyPolicy,
    CapabilityStateClosurePolicy,
    FunctionalArgBindingAuthority,
    FunctionalSemanticRefRole,
    FunctionalOutputTargetSelectorSpec,
    StateIdentityConstraintSpec,
    StateLineageClosureSpec,
    StateObjectRoleProjectionSpec,
)
from shuxueshuo_server.solver.runtime.condition_roles import ConditionObjectRoles
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpec
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpec
from shuxueshuo_server.solver.runtime.planner_public_types import (
    planner_output_value_type,
    planner_prompt_text,
)
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.state_identity import (
    ComputationKey,
    LogicalStateKey,
    MathObjectId,
    StateAllocationAction,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateDependency,
    SemanticRef,
)
from shuxueshuo_server.solver.state_semantics import (
    StateSemanticLineage,
    dependent_role_object_ref,
    derived_role_object_ref,
    is_object_handle,
    is_object_semantic_kind,
    object_kind_for_runtime_type,
    object_ref_matches_runtime_type,
)

FunctionalCapabilityKind = Literal["function", "macro"]
FunctionalIssueLayer = Literal[
    "functional_validation",
    "functional_elaboration",
    "functional_reconciliation",
]
FunctionalArgMode = Literal["explicit", "optional", "auto"]
FunctionalReturnExpectationPolicy = Literal["selectable", "omit"]
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


@dataclass(frozen=True)
class PublishedGoalCallResultRef(CallResultRef):
    """A solved Goal's final answer published to a repair consumer.

    The execution wire remains a normal call-result edge.  The extra Goal
    authority is intentionally internal so it cannot be authored by Pass 1 or
    inferred from a display value.
    """

    published_goal_ref: str
    semantic_ref: str | None = None

    def authority_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "published_goal_ref": self.published_goal_ref,
            "producer": self.to_payload(),
        }
        if self.semantic_ref is not None:
            payload["semantic_ref"] = self.semantic_ref
        return payload


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
    deterministic_repairs: tuple[dict[str, Any], ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [item.to_payload() for item in self.issues],
            "partially_parsed_payload": self.partially_parsed_payload,
            "deterministic_repairs": [
                dict(item) for item in self.deterministic_repairs
            ],
        }


@dataclass(frozen=True)
class FunctionalCapabilityArg:
    name: str
    runtime_type: str
    required: bool
    cardinality: str
    kind: str
    domain_type: str | None = None
    input_view_mode: MethodInputViewMode | None = field(default=None, repr=False)
    allows_anonymous_result: bool = field(default=False, repr=False)
    allows_empty_collection: bool = field(default=False, repr=False)
    semantic_role: str | None = None
    llm_mode: FunctionalArgMode = "explicit"
    accepted_item_types: tuple[str, ...] = ()
    accepted_condition_kinds: tuple[str, ...] = ()
    prompt_fact_types: tuple[str, ...] = field(default=(), repr=False)
    accepted_semantic_roles: tuple[str, ...] = ()
    requires_materialized_state: bool = False
    aggregation: FunctionalAggregation = "none"
    runtime_input: str | None = None
    aliases: tuple[str, ...] = ()
    deterministic_resolver: str | None = None
    description: str = ""
    provides_semantic_roles: tuple[str, ...] = ()
    input_closure_policy: CapabilityStateClosurePolicy = "any"
    binding_authority: FunctionalArgBindingAuthority = field(
        default="wire",
        repr=False,
    )
    consumption_mode: str = field(default="runtime_input", repr=False)
    semantic_ref_role: FunctionalSemanticRefRole = "value"
    allowed_refs: tuple[str, ...] = field(default=(), repr=False)

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "domain_type": self.domain_type or self.runtime_type,
            "required": self.required,
            "cardinality": self.cardinality,
        }
        public_fact_types = (
            self.prompt_fact_types or self.accepted_condition_kinds
        )
        if public_fact_types:
            payload["fact_types"] = list(
                public_fact_types
            )
        if self.accepted_semantic_roles:
            payload["roles"] = list(
                self.accepted_semantic_roles
            )
        if self.allowed_refs:
            payload["allowed_refs"] = list(self.allowed_refs)
        description = self.description
        if description:
            payload["role"] = description
        return payload


@dataclass(frozen=True)
class FunctionalAutoArg:
    name: str
    selector: str
    required: bool
    binding_authority: FunctionalArgBindingAuthority = "compiler"
    semantic_role: str | None = None
    runtime_input: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "selector": self.selector,
            "required": self.required,
            "semantic_role": self.semantic_role or self.name,
            "runtime_input": self.runtime_input or self.name,
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
    equivalent_to: str | None = None
    provides_semantic_roles: tuple[str, ...] = ()
    evidence_tags: tuple[str, ...] = ()
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = ()
    lineage_closures: tuple[StateLineageClosureSpec, ...] = ()
    max_independent_free_parameters: int | None = None
    return_binding: str = "auto"
    result_form_ignored_input_args: tuple[str, ...] = ()
    free_symbol_return_names: tuple[str, ...] = ()
    output_target_selector: FunctionalOutputTargetSelectorSpec | None = None

    @property
    def binding_mode(self) -> str:
        """Return the wire-level destination policy exposed to the planner."""
        return _prompt_return_binding(self)

    @property
    def return_expectation_policy(self) -> FunctionalReturnExpectationPolicy:
        """Declare whether the planner may author an open/closed form hint."""
        return "selectable" if self.possible_forms else "omit"

    def to_prompt_payload(
        self,
        *,
        exposed_arg_names: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        binding_mode = self.binding_mode
        compiler_selected_identity = (
            exposed_arg_names is not None
            and self.identity_policy == "preserve_input_object"
            and self.identity_arg is not None
            and self.identity_arg not in exposed_arg_names
        )
        if compiler_selected_identity:
            binding_mode = "same_compiler_selected_object"
        payload: dict[str, Any] = {
            "name": self.name,
            "type": planner_output_value_type(self.runtime_type),
            "binding": binding_mode,
        }
        if _is_aggregate_return_type(self.runtime_type):
            payload["value_cardinality"] = "aggregate"
        if not self.required:
            payload["required"] = False
        if self.cardinality != "one":
            payload["cardinality"] = self.cardinality
        description = _joined_description(
            self.description,
            self.result_form_description,
            _aggregate_return_binding_description(self),
            (
                "对象身份由编译器从当前scope的题面权威中选择；"
                "不要为此添加catalog未声明的输入参数。"
                if compiler_selected_identity
                else ""
            ),
        )
        if description:
            payload["desc"] = description
        if self.possible_forms:
            payload["return_expectation_policy"] = "selectable"
            payload["possible_forms"] = list(self.possible_forms)
        if self.max_independent_free_parameters is not None:
            payload["max_independent_free_parameters"] = (
                self.max_independent_free_parameters
            )
        if self.equivalent_to is not None:
            payload["same_state_as"] = self.equivalent_to
        if self.provides_semantic_roles:
            payload["provides"] = list(self.provides_semantic_roles)
        if self.output_target_selector is not None:
            payload["target_selection"] = (
                self.output_target_selector.to_payload()
            )
        return payload


@dataclass(frozen=True)
class FunctionalInputClosureRequirement:
    """LLM-facing conditionally required semantic input contract."""

    semantic_role: str
    provider_arg_roles: tuple[str, ...]
    cardinality: str
    description: str

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "role": self.semantic_role,
            "requirement": self.description,
        }


@dataclass(frozen=True)
class FunctionalContextArgBinding:
    """Internal projection from a resolver role to one runtime argument."""

    resolver_id: CapabilityContextResolver
    semantic_role: str
    arg_name: str
    consumption_mode: str = "runtime_input"


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
    distinct_arg_groups: tuple[tuple[str, ...], ...] = field(
        default=(),
        repr=False,
    )
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
    input_closure_requirements: tuple[
        FunctionalInputClosureRequirement, ...
    ] = ()
    identity_constraints: tuple[StateIdentityConstraintSpec, ...] = field(
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

    def declared_arg_runtime_type(self, name: str) -> str | None:
        """Return the typed Function/Macro arg hidden behind a wire adapter."""
        for arg in self.source.args:
            if arg.name == name:
                return arg.runtime_type
        return None

    def to_prompt_payload(self) -> dict[str, Any]:
        exposed_arg_names = frozenset(item.name for item in self.args)
        payload: dict[str, Any] = {
            "capability_id": self.capability_id,
            "title": self.title,
            "use_when": self.use_when,
            "args": [item.to_prompt_payload() for item in self.args],
            "returns": [
                item.to_prompt_payload(
                    exposed_arg_names=exposed_arg_names,
                )
                for item in self.returns
            ],
        }
        if self.do_not_use_when:
            payload["do_not_use_when"] = list(self.do_not_use_when)
        requirements = [
            item.to_prompt_payload()
            for item in self.input_closure_requirements
        ]
        requirements.extend(
            {"requirement": item.description}
            for item in self.identity_constraints
            if item.description
        )
        requirements.extend(
            {"requirement": closure.description}
            for returned in self.returns
            for closure in returned.lineage_closures
            if closure.description
        )
        exposed_arg_names = {item.name for item in self.args}
        requirements.extend(
            {
                "requirement": (
                    f"{'、'.join(group)} 必须引用彼此不同的语义状态。"
                )
            }
            for group in self.distinct_arg_groups
            if len(group) > 1 and set(group) <= exposed_arg_names
        )
        if requirements:
            payload["input_requirements"] = requirements
        return _planner_safe_payload(payload)


def _prompt_return_binding(result: FunctionalCapabilityReturn) -> str:
    if result.return_binding == "internal_only":
        return "internal_only"
    if result.return_binding == "external_allowed":
        return "answer_or_existing_object"
    if result.return_binding == "explicit_external_required":
        return "explicit_answer_or_existing_object"
    if result.return_binding == "call_local_allowed":
        return "call_result_or_answer_or_existing_object"
    if result.identity_policy == "derived_role":
        return "internal_only"
    if result.identity_policy == "preserve_input_object":
        if _is_aggregate_return_type(result.runtime_type):
            return (
                f"aggregate_elements_same_object_as:{result.identity_arg}"
                if result.identity_arg
                else "aggregate_elements_same_input_object"
            )
        return (
            f"same_object_as:{result.identity_arg}"
            if result.identity_arg
            else "same_input_object"
        )
    # Identity-neutral returns are values first. They can be consumed directly
    # as exact call results, or optionally published to an answer/existing
    # object. Capabilities that require an external destination must opt in via
    # ``explicit_external_required``.
    return "call_result_or_answer_or_existing_object"


def _planner_safe_payload(value: Any) -> Any:
    """Remove runtime representation vocabulary at the LLM boundary."""

    if isinstance(value, dict):
        return {
            key: _planner_safe_payload(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_planner_safe_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_planner_safe_payload(item) for item in value]
    if not isinstance(value, str):
        return value
    return planner_prompt_text(value)


def _is_aggregate_return_type(runtime_type: str) -> bool:
    return runtime_type in {"Coefficients", "PointList", "SymbolList"}


def _aggregate_return_binding_description(
    result: FunctionalCapabilityReturn,
) -> str:
    if not _is_aggregate_return_type(result.runtime_type):
        return ""
    identity_note = (
        f"列表元素保持 {result.identity_arg} 的对象身份；"
        if (
            result.identity_policy == "preserve_input_object"
            and result.identity_arg
        )
        else ""
    )
    if result.return_binding == "internal_only" or (
        result.identity_policy == "derived_role"
    ):
        return (
            f"返回值是一个整体的 {result.runtime_type} 聚合值，不是单个对象。"
            f"{identity_note}该 return 是 internal_only，不能设置 return binding。"
        )
    return (
        f"返回值是一个整体的 {result.runtime_type} 聚合值，不是单个对象。"
        f"{identity_note}若绑定 required answer，必须使用 answer 类型的 binding 且 "
        f"value_type={result.runtime_type}；不得绑定为单个对象。"
    )


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
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()
    provides_semantic_roles: tuple[str, ...] = ()
    lineage: StateSemanticLineage = StateSemanticLineage()
    materialized_runtime_type: str | None = None
    supporting_handles: tuple[str, ...] = ()
    math_object_id: MathObjectId | None = None
    logical_state_key: LogicalStateKey | None = None
    typed_slot_id: StateSlotId | None = None
    state_version_id: StateVersionId | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()

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
            "free_symbol_ids": [
                item.to_payload() for item in self.free_symbol_ids
            ],
            "source_state_slot_ids": list(self.source_state_slot_ids),
            "provides_semantic_roles": list(self.provides_semantic_roles),
            "lineage": self.lineage.to_payload(),
            "materialized_runtime_type": self.materialized_runtime_type,
            "supporting_handles": list(self.supporting_handles),
            "math_object_id": (
                self.math_object_id.to_payload()
                if self.math_object_id is not None
                else None
            ),
            "logical_state_key": (
                self.logical_state_key.to_payload()
                if self.logical_state_key is not None
                else None
            ),
            "typed_slot_id": (
                self.typed_slot_id.to_payload()
                if self.typed_slot_id is not None
                else None
            ),
            "state_version_id": (
                self.state_version_id.to_payload()
                if self.state_version_id is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
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
    state_handle: str | None = None
    dependency_object_refs: tuple[str, ...] = ()
    free_symbol_refs: tuple[str, ...] = ()
    free_symbol_ids: tuple[MathObjectId, ...] = ()
    source_state_slot_ids: tuple[str, ...] = ()
    transition_kind: Literal["direct", "dependency_refinement"] | None = None
    previous_write_step_id: str | None = None
    provides_semantic_roles: tuple[str, ...] = ()
    lineage: StateSemanticLineage = StateSemanticLineage()
    math_object_id: MathObjectId | None = None
    logical_state_key: LogicalStateKey | None = None
    typed_slot_id: StateSlotId | None = None
    selected_version_id: StateVersionId | None = None
    previous_version_id: StateVersionId | None = None
    computation_key: ComputationKey | None = None
    source_version_ids: tuple[StateVersionId, ...] = ()
    allocation_action: StateAllocationAction | None = None
    canonical_producer_call_id: str | None = None
    allocation_reason_code: str | None = None
    allocation_conflict_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
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
            "free_symbol_ids": [
                item.to_payload() for item in self.free_symbol_ids
            ],
            "source_state_slot_ids": list(self.source_state_slot_ids),
            "transition_kind": self.transition_kind,
            "previous_write_step_id": self.previous_write_step_id,
            "provides_semantic_roles": list(self.provides_semantic_roles),
            "lineage": self.lineage.to_payload(),
            "math_object_id": (
                self.math_object_id.to_payload()
                if self.math_object_id is not None
                else None
            ),
            "logical_state_key": (
                self.logical_state_key.to_payload()
                if self.logical_state_key is not None
                else None
            ),
            "typed_slot_id": (
                self.typed_slot_id.to_payload()
                if self.typed_slot_id is not None
                else None
            ),
            "selected_version_id": (
                self.selected_version_id.to_payload()
                if self.selected_version_id is not None
                else None
            ),
            "previous_version_id": (
                self.previous_version_id.to_payload()
                if self.previous_version_id is not None
                else None
            ),
            "computation_key": (
                self.computation_key.to_payload()
                if self.computation_key is not None
                else None
            ),
            "source_version_ids": [
                item.to_payload() for item in self.source_version_ids
            ],
            "allocation_action": self.allocation_action,
            "canonical_producer_call_id": self.canonical_producer_call_id,
            "allocation_reason_code": self.allocation_reason_code,
            "allocation_conflict_code": self.allocation_conflict_code,
        }
        if self.state_handle is not None:
            payload["state_handle"] = self.state_handle
        return payload


@dataclass(frozen=True)
class FunctionalMethodRelationBinding:
    """Exact Condition authority consumed by one Method entity relation."""

    call_id: str
    method_id: str
    relation_kind: str
    point_arg_name: str
    point_item_index: int
    curve_arg_name: str
    condition_id: str
    condition_ref: str
    condition_ref_kind: str
    condition_kind: str
    owner_scope_id: str
    point_object_ref: str
    curve_object_ref: str
    point_math_object_id: MathObjectId | None = None
    curve_math_object_id: MathObjectId | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "method_id": self.method_id,
            "relation_kind": self.relation_kind,
            "point_arg_name": self.point_arg_name,
            "point_item_index": self.point_item_index,
            "curve_arg_name": self.curve_arg_name,
            "condition_id": self.condition_id,
            "condition_ref": self.condition_ref,
            "condition_ref_kind": self.condition_ref_kind,
            "condition_kind": self.condition_kind,
            "owner_scope_id": self.owner_scope_id,
            "point_object_ref": self.point_object_ref,
            "curve_object_ref": self.curve_object_ref,
            "point_math_object_id": (
                self.point_math_object_id.to_payload()
                if self.point_math_object_id is not None
                else None
            ),
            "curve_math_object_id": (
                self.curve_math_object_id.to_payload()
                if self.curve_math_object_id is not None
                else None
            ),
        }


@dataclass(frozen=True)
class FunctionalCallReconciliation:
    call_id: str
    scope_id: str
    capability_id: str
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]]
    returns: tuple[FunctionalReturnAllocation, ...]
    reads_closed: bool = False
    authored_macro_roles: tuple[tuple[str, str], ...] = ()
    relation_bindings: tuple[FunctionalMethodRelationBinding, ...] = ()

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
            "authored_macro_roles": {
                role: object_ref
                for role, object_ref in self.authored_macro_roles
            },
            "relation_bindings": [
                item.to_payload() for item in self.relation_bindings
            ],
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
class FunctionalCallExecutionEntry:
    """Typed execution placement for one canonical Functional call."""

    call_id: str
    canonical_call_id: str
    alias_call_ids: tuple[str, ...]
    declared_scope_id: str
    execution_scope_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "canonical_call_id": self.canonical_call_id,
            "alias_call_ids": list(self.alias_call_ids),
            "declared_scope_id": self.declared_scope_id,
            "execution_scope_id": self.execution_scope_id,
        }


@dataclass(frozen=True)
class FunctionalPlanReconciliationResult:
    plan: FunctionalPlan
    calls: tuple[FunctionalCallReconciliation, ...] = ()
    issues: tuple[FunctionalPlanIssue, ...] = ()
    execution_entries: tuple[FunctionalCallExecutionEntry, ...] = ()
    context_delta: dict[str, Any] = field(default_factory=dict)
    call_reports: tuple[FunctionalCallReport, ...] = ()
    dependency_graph: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dependency_kinds: dict[str, dict[str, str]] = field(
        default_factory=dict
    )
    call_placements: tuple[FunctionalCallPlacement, ...] = ()
    call_aliases: dict[str, str] = field(default_factory=dict)
    elaboration: dict[str, Any] | None = None
    result_form_events: tuple[FunctionalResultFormEvent, ...] = ()
    state_identity_decisions: tuple[dict[str, Any], ...] = ()
    identity_mismatches: tuple[dict[str, Any], ...] = ()
    state_placement_decisions: tuple[dict[str, Any], ...] = ()
    placement_mismatches: tuple[dict[str, Any], ...] = ()
    state_finalization_decisions: tuple[dict[str, Any], ...] = ()
    state_finalization_mismatches: tuple[dict[str, Any], ...] = ()
    runtime_destination_decisions: tuple[dict[str, Any], ...] = ()
    state_dependencies: tuple[ProjectedStateDependency, ...] = ()
    typed_identity_completeness: dict[str, Any] = field(default_factory=dict)
    legacy_identity_fallback_count: int = 0
    functional_binding_context: Any | None = None
    functional_problem_binding_context: Any | None = None
    functional_binding_decisions: tuple[dict[str, Any], ...] = ()
    functional_binding_mismatches: tuple[dict[str, Any], ...] = ()
    legacy_binding_role_fallback_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues and bool(self.calls)

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
            "execution_entries": [
                item.to_payload() for item in self.execution_entries
            ],
            "context_delta": dict(self.context_delta),
            "call_reports": [item.to_payload() for item in self.call_reports],
            "dependency_graph": {
                key: list(value) for key, value in self.dependency_graph.items()
            },
            "dependency_kinds": {
                consumer: dict(producers)
                for consumer, producers in self.dependency_kinds.items()
            },
            "call_placements": [
                item.to_payload() for item in self.call_placements
            ],
            "call_aliases": dict(self.call_aliases),
            "elaboration": self.elaboration,
            "result_form_events": [
                item.to_payload() for item in self.result_form_events
            ],
            "state_identity_decisions": [
                dict(item) for item in self.state_identity_decisions
            ],
            "identity_mismatches": [
                dict(item) for item in self.identity_mismatches
            ],
            "state_placement_decisions": [
                dict(item) for item in self.state_placement_decisions
            ],
            "placement_mismatches": [
                dict(item) for item in self.placement_mismatches
            ],
            "state_finalization_decisions": [
                dict(item) for item in self.state_finalization_decisions
            ],
            "state_finalization_mismatches": [
                dict(item) for item in self.state_finalization_mismatches
            ],
            "runtime_destination_decisions": [
                dict(item) for item in self.runtime_destination_decisions
            ],
            "state_dependencies": [
                item.to_payload()
                for item in self.state_dependencies
            ],
            "typed_identity_completeness": dict(
                self.typed_identity_completeness
            ),
            "legacy_identity_fallback_count": (
                self.legacy_identity_fallback_count
            ),
            "functional_binding_context": (
                self.functional_binding_context.to_payload()
                if self.functional_binding_context is not None
                else None
            ),
            "functional_problem_binding_context": (
                self.functional_problem_binding_context.to_payload()
                if self.functional_problem_binding_context is not None
                else None
            ),
            "functional_binding_decisions": [
                dict(item) for item in self.functional_binding_decisions
            ],
            "functional_binding_mismatches": [
                dict(item) for item in self.functional_binding_mismatches
            ],
            "legacy_binding_role_fallback_count": (
                self.legacy_binding_role_fallback_count
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
                object_ref = values[0].object_ref or _entity_handle_or_none(
                    values[0].handle
                )
                if object_ref_matches_runtime_type(
                    object_ref,
                    return_spec.runtime_type,
                ):
                    return object_ref
        if (
            return_spec.identity_policy == "target_object"
            and return_spec.identity_arg
        ):
            values = resolved_args.get(return_spec.identity_arg, ())
            if values:
                object_ref = values[0].object_ref or _entity_handle_or_none(
                    values[0].handle
                )
                if object_ref_matches_runtime_type(
                    object_ref,
                    return_spec.runtime_type,
                ):
                    return object_ref
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
            and object_kind_for_runtime_type(return_spec.runtime_type)
            is not None
        ):
            return derived_role_object_ref(
                call_id=call_id,
                semantic_role=(
                    return_spec.equivalent_to
                    or return_spec.semantic_role
                    or return_spec.name
                ),
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
