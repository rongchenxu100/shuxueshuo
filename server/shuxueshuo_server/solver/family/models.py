"""SolverFamily 规格模型。

本模块只描述“题型级共性”，不保存某一道题的解法步骤、答案结构或 planner 选择。
Phase 4 后，FamilySpec 只作为 RuntimeOrchestrator 和 Planner 的题型上下文，
不承担求解执行职责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shuxueshuo_server.solver.contracts import (
    FunctionalArgBindingAuthority,
    MacroExecutionMode,
    MacroSearchSpec,
    MethodInputBindingSpec,
    ScalarResultFormSpec,
    SourceObjectIdentityDerivationSpec,
)
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.state_semantics import state_kind_for_runtime_type
from shuxueshuo_server.solver.utils import unique_ordered

StateIdentityPolicy = Literal[
    "preserve_input_object",
    "target_object",
    "derived_role",
    "value_only",
]
StateWriteMode = Literal["create", "transition", "value"]
GoalEvidenceTag = Literal[
    "path_minimum_witness",
    "path_minimum_expression",
    "path_minimum_extremal_point",
    "curve_membership",
]
FamilySourcePrimitiveKind = Literal["entity_type", "fact_type"]
FamilySourceEvidenceAuthority = Literal["candidate_structure", "printed_source"]
@dataclass(frozen=True)
class FamilySourceRequirementSpec:
    """Machine-checkable source primitive required for family admission."""

    primitive_kind: FamilySourcePrimitiveKind
    primitive_types: tuple[str, ...]
    description: str
    min_count: int = 1
    source_authority: FamilySourceEvidenceAuthority = "candidate_structure"
    printed_source_markers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.primitive_types
            or any(not item.strip() for item in self.primitive_types)
            or len(set(self.primitive_types)) != len(self.primitive_types)
            or not self.description.strip()
        ):
            raise ValueError("family source requirement must be fully described")
        if self.min_count <= 0:
            raise ValueError("family source requirement min_count must be positive")
        if self.source_authority == "printed_source":
            if (
                not self.printed_source_markers
                or any(not item.strip() for item in self.printed_source_markers)
                or len(set(self.printed_source_markers))
                != len(self.printed_source_markers)
            ):
                raise ValueError(
                    "printed-source family requirements need unique source markers"
                )
        elif self.printed_source_markers:
            raise ValueError(
                "candidate-structure family requirements cannot declare source markers"
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "primitive_kind": self.primitive_kind,
            "primitive_types": list(self.primitive_types),
            "min_count": self.min_count,
            "description": self.description,
        }


@dataclass(frozen=True)
class FamilyRuntimePreflightSpec:
    """A pure method invocation that must be runnable from source state.

    Extraction uses this contract after ContextBuilder has projected the
    authored ProblemIR. It binds through the same selectors as production and
    executes the stateless method on a forked RuntimeContext, without planner
    calls, state promotion, or answer construction.
    """

    method_id: str
    trigger_fact_types: tuple[str, ...]
    source_input_names: tuple[str, ...]
    description: str
    trigger_selector_id: str = "all"
    required_fact_types: tuple[str, ...] = ()
    source_trigger_fact_types: tuple[str, ...] = ()
    source_required_fact_types: tuple[str, ...] = ()
    execution_mode: Literal["method", "source_structure_only"] = "method"
    planner_authored_roles: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name, values in (
            ("trigger_fact_types", self.trigger_fact_types),
            ("source_input_names", self.source_input_names),
        ):
            if (
                not values
                or any(not item.strip() for item in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError(
                    f"family runtime preflight {field_name} must be non-empty and unique"
                )
        if (
            any(not item.strip() for item in self.required_fact_types)
            or len(set(self.required_fact_types)) != len(self.required_fact_types)
        ):
            raise ValueError(
                "family runtime preflight required_fact_types must be unique"
            )
        for field_name, values in (
            ("source_trigger_fact_types", self.source_trigger_fact_types),
            ("source_required_fact_types", self.source_required_fact_types),
        ):
            if (
                any(not item.strip() for item in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError(
                    f"family runtime preflight {field_name} must be unique"
                )
        if bool(self.source_trigger_fact_types) != bool(
            self.source_required_fact_types
        ):
            raise ValueError(
                "source-visible preflight guidance requires both trigger and required fact types"
            )
        if self.execution_mode not in {"method", "source_structure_only"}:
            raise ValueError("family runtime preflight execution mode is invalid")
        if (
            any(not item.strip() for item in self.planner_authored_roles)
            or len(set(self.planner_authored_roles))
            != len(self.planner_authored_roles)
        ):
            raise ValueError(
                "family runtime preflight planner-authored roles must be unique"
            )
        if (
            self.execution_mode == "source_structure_only"
            and not self.planner_authored_roles
        ):
            raise ValueError(
                "source-structure preflight must name its planner-authored roles"
            )
        if self.execution_mode == "method" and self.planner_authored_roles:
            raise ValueError(
                "method preflight cannot defer planner-authored roles"
            )
        if (
            not self.method_id.strip()
            or not self.description.strip()
            or not self.trigger_selector_id.strip()
        ):
            raise ValueError("family runtime preflight must be fully described")

    def to_payload(self) -> dict[str, object]:
        return {
            "method_id": self.method_id,
            "trigger_fact_types": list(self.trigger_fact_types),
            "trigger_selector_id": self.trigger_selector_id,
            "required_fact_types": list(self.required_fact_types),
            "source_input_names": list(self.source_input_names),
            "description": self.description,
            "execution_mode": self.execution_mode,
            "planner_authored_roles": list(self.planner_authored_roles),
        }

    def source_authoring_payload(self) -> dict[str, object] | None:
        """Return source-domain guidance without runtime method vocabulary."""

        if not self.source_trigger_fact_types:
            return None
        return {
            "when_fact_types": list(self.source_trigger_fact_types),
            "require_visible_fact_types": list(self.source_required_fact_types),
            "description": self.description,
        }


@dataclass(frozen=True)
class FamilySourceGoalContractSpec:
    """Source structure that determines a required answer value type."""

    selector_id: str
    expected_value_type: str
    description: str

    def __post_init__(self) -> None:
        if not (
            self.selector_id.strip()
            and self.expected_value_type.strip()
            and self.description.strip()
        ):
            raise ValueError("family source goal contract must be fully described")

    def to_payload(self) -> dict[str, object]:
        return {
            "selector_id": self.selector_id,
            "expected_value_type": self.expected_value_type,
            "description": self.description,
        }


@dataclass(frozen=True)
class GoalEvidencePolicySpec:
    """Require evidence for goals served inside one mechanism boundary."""

    goal_types: tuple[str, ...]
    value_types: tuple[str, ...]
    required_evidence_tags: tuple[GoalEvidenceTag, ...]
    mechanism_pack_id: str | None = None
    producer_goal_types: tuple[str, ...] = ()
StateIdentityRelation = Literal["same_object", "same_object_set"]
StateRoleRequirement = Literal["identity_only", "materialized"]
StateIdentityConstraintApplicability = Literal[
    "required",
    "when_all_present",
]


@dataclass(frozen=True)
class StateObjectRoleProjectionSpec:
    """Project one output object role from an argument or sibling return."""

    role: str
    source_arg: str | None = None
    source_return: str | None = None
    source_object_role: str | None = None
    state_requirement: StateRoleRequirement = "identity_only"

    def __post_init__(self) -> None:
        if (self.source_arg is None) == (self.source_return is None):
            raise ValueError(
                "object-role projection requires exactly one of "
                "source_arg or source_return"
            )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"role": self.role}
        if self.source_arg is not None:
            payload["source_arg"] = self.source_arg
        if self.source_return is not None:
            payload["source_return"] = self.source_return
        if self.source_object_role is not None:
            payload["source_object_role"] = self.source_object_role
        if self.state_requirement != "identity_only":
            payload["state_requirement"] = self.state_requirement
        return payload


@dataclass(frozen=True)
class CapabilityContextRoleBindingSpec:
    """Bind a resolver role as a dependency-only capability argument."""

    resolver_id: CapabilityContextResolver
    semantic_role: str
    arg_name: str

    def to_payload(self) -> dict[str, str]:
        return {
            "resolver_id": self.resolver_id,
            "semantic_role": self.semantic_role,
            "arg_name": self.arg_name,
        }


@dataclass(frozen=True)
class EvidenceInputGroupSpec:
    """One all-of input group required by an evidence closure."""

    source_args: tuple[str, ...]
    required_semantic_roles: tuple[str, ...] = ()
    required_evidence_tags: tuple[str, ...] = ()
    required_witness_object_roles: tuple[str, ...] = ()
    witness_role_aliases: tuple[tuple[str, str], ...] = ()
    require_same_witness: bool = False

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_args": list(self.source_args),
            "required_semantic_roles": list(self.required_semantic_roles),
            "required_evidence_tags": list(self.required_evidence_tags),
            "required_witness_object_roles": list(
                self.required_witness_object_roles
            ),
        }
        if self.witness_role_aliases:
            payload["witness_role_aliases"] = [
                list(item) for item in self.witness_role_aliases
            ]
        if self.require_same_witness:
            payload["require_same_witness"] = True
        return payload


@dataclass(frozen=True)
class StateLineageClosureSpec:
    """Conditionally promote semantic evidence from a closed set of inputs."""

    source_args: tuple[str, ...]
    required_semantic_roles: tuple[str, ...] = ()
    required_evidence_tags: tuple[str, ...] = ()
    shared_object_role: str | None = None
    require_same_source_call: bool = False
    add_semantic_roles: tuple[str, ...] = ()
    add_evidence_tags: tuple[str, ...] = ()
    description: str = ""
    input_groups: tuple[EvidenceInputGroupSpec, ...] = ()
    input_group_matching: Literal["ordered", "commutative"] = "ordered"
    output_object_role: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_args": list(self.source_args),
            "required_semantic_roles": list(self.required_semantic_roles),
            "required_evidence_tags": list(self.required_evidence_tags),
            "add_semantic_roles": list(self.add_semantic_roles),
            "add_evidence_tags": list(self.add_evidence_tags),
        }
        if self.shared_object_role is not None:
            payload["shared_object_role"] = self.shared_object_role
        if self.require_same_source_call:
            payload["require_same_source_call"] = True
        if self.description:
            payload["description"] = self.description
        if self.input_groups:
            payload["input_groups"] = [
                item.to_payload() for item in self.input_groups
            ]
        if self.input_group_matching != "ordered":
            payload["input_group_matching"] = self.input_group_matching
        if self.output_object_role is not None:
            payload["output_object_role"] = self.output_object_role
        return payload


@dataclass(frozen=True)
class StateIdentityConstraintSpec:
    """A declarative equality constraint over argument/return object roles."""

    left: str
    right: str
    relation: StateIdentityRelation = "same_object"
    description: str = ""
    applicability: StateIdentityConstraintApplicability = "required"

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "left": self.left,
            "right": self.right,
            "relation": self.relation,
        }
        if self.applicability != "required":
            payload["applicability"] = self.applicability
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(frozen=True)
class RecipeOutputAliasSpec:
    """One recipe output role and its state/object identity contract."""

    output_key: str
    runtime_type: str
    semantic_role: str
    state_kind: str
    required: bool = True
    cardinality: Literal["one", "optional", "many"] = "one"
    identity_policy: StateIdentityPolicy = "value_only"
    identity_arg: str | None = None
    write_mode: StateWriteMode = "value"
    goal_evidence_tags: tuple[GoalEvidenceTag, ...] = ()
    description: str = ""
    equivalent_to: str | None = None
    provides_semantic_roles: tuple[str, ...] = ()
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = ()
    return_binding: FunctionalReturnBindingPolicy = "auto"
    result_form: ScalarResultFormSpec | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "output_key": self.output_key,
            "runtime_type": self.runtime_type,
            "semantic_role": self.semantic_role,
            "state_kind": self.state_kind,
            "required": self.required,
            "cardinality": self.cardinality,
            "identity_policy": self.identity_policy,
            "identity_arg": self.identity_arg,
            "write_mode": self.write_mode,
            "goal_evidence_tags": list(self.goal_evidence_tags),
        }
        if self.description:
            payload["description"] = self.description
        if self.equivalent_to is not None:
            payload["equivalent_to"] = self.equivalent_to
        if self.provides_semantic_roles:
            payload["provides_semantic_roles"] = list(
                self.provides_semantic_roles
            )
        if self.object_role_projections:
            payload["object_role_projections"] = [
                item.to_payload() for item in self.object_role_projections
            ]
        if self.return_binding != "auto":
            payload["return_binding"] = self.return_binding
        if self.result_form is not None:
            payload["result_form"] = self.result_form.to_payload()
        return payload


def recipe_output_alias(
    output_key: str,
    runtime_type: str,
    semantic_role: str,
    *,
    required: bool = True,
    cardinality: Literal["one", "optional", "many"] = "one",
    identity_policy: StateIdentityPolicy = "value_only",
    identity_arg: str | None = None,
    write_mode: StateWriteMode | None = None,
    goal_evidence_tags: tuple[GoalEvidenceTag, ...] = (),
    description: str = "",
    equivalent_to: str | None = None,
    provides_semantic_roles: tuple[str, ...] = (),
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = (),
    return_binding: FunctionalReturnBindingPolicy = "auto",
    result_form: ScalarResultFormSpec | None = None,
) -> RecipeOutputAliasSpec:
    """Build a structured recipe return without duplicating state-kind rules."""
    return RecipeOutputAliasSpec(
        output_key=output_key,
        runtime_type=runtime_type,
        semantic_role=semantic_role,
        state_kind=state_kind_for_runtime_type(runtime_type),
        required=required,
        cardinality=cardinality,
        identity_policy=identity_policy,
        identity_arg=identity_arg,
        write_mode=(
            write_mode
            if write_mode is not None
            else ("create" if runtime_type in {"Point", "PointList"} else "value")
        ),
        goal_evidence_tags=goal_evidence_tags,
        description=description,
        equivalent_to=equivalent_to,
        provides_semantic_roles=provides_semantic_roles,
        object_role_projections=object_role_projections,
        return_binding=return_binding,
        result_form=result_form,
    )


@dataclass(frozen=True)
class RecipeInputDerivationSpec:
    """Derive one hidden Method input from an explicit public Macro input.

    A derivation is compiler wiring, not another Planner argument.  The first
    supported rule preserves the object identity carried by a state value;
    for example a ``ParameterValue`` for symbol ``m`` supplies both the value
    input and the hidden ``Symbol`` input required by an internal Method.
    """

    target: str
    derivation: SourceObjectIdentityDerivationSpec

    @property
    def source_arg(self) -> str:
        return self.derivation.source_input

    @property
    def kind(self) -> Literal["source_object_identity"]:
        return self.derivation.kind

    def to_payload(self) -> dict[str, str]:
        return {
            "source_arg": self.source_arg,
            "target": self.target,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class RecipeExecutionSpec:
    """Recipe 的可执行编排规格。

    ``StepRecipeSpec`` 面向 LLM 展示“标准解题动作”，而这里描述 runtime 如何把这个
    标准动作拆成 method 序列。它仍然是 family 级配置，不包含某道题的点名、分问 id
    或答案值。
    """

    recipe_id: str
    method_sequence: tuple[str, ...]
    execution_mode: MacroExecutionMode
    search: MacroSearchSpec | None = None
    # 执行策略名只选择通用编译器分支，例如“单 method”“构造候选后筛选”。
    # 它不是题号模板名，也不应该包含 D/M/N/F/G 这类具体点名。
    execution_strategy: str = "single_method"
    creates: tuple[str, ...] = ()
    # ``(macro_arg, "method_id.input_name")`` mappings preserve an explicit
    # Functional macro argument when the recipe is compiled into its internal
    # method call. Custom compiler strategies must consume these aliases before
    # considering legacy read-based selectors.
    input_aliases: tuple[tuple[str, str], ...] = ()
    # Hidden Method inputs derived from one declared public Macro input.  This
    # keeps public-to-internal lowering auditable and prevents compiler branches
    # from independently guessing companion identities.
    input_derivations: tuple[RecipeInputDerivationSpec, ...] = ()
    # Required Method inputs supplied by the named compiler strategy from
    # context closure, target identity, or an internal role resolver.  Listing
    # them closes the static lowering graph without exposing them to Planner.
    strategy_input_targets: tuple[str, ...] = ()
    intermediate_wiring: tuple[tuple[str, str], ...] = ()
    output_aliases: tuple[RecipeOutputAliasSpec, ...] = ()


@dataclass(frozen=True)
class MethodAggregateInputBindingSpec:
    """Lower one public aggregate argument into declared scalar inputs.

    FunctionalPlan exposes item-level values instead of runtime containers.
    This declaration preserves the exact reconciled item identities when a
    legacy method accepts a fixed number of scalar compatibility inputs.
    """

    source_input: str
    item_inputs: tuple[str, ...]
    singleton_input: str | None = None


@dataclass(frozen=True)
class MethodScalarAggregateLoweringSpec:
    """Lower one item-level aggregate value through declared scalar inputs."""

    source_input: str
    item_runtime_type: str
    identity_input: str
    value_input: str


@dataclass(frozen=True)
class MethodPrepInvocationSpec:
    """method 前置补位 invocation 的声明式规则。

    有些 method 的教学 step 会把“先生成可读前置对象”和“使用前置对象求目标”
    合并表达。prep 只检查父调用已经 finalize 的 ``source_input`` authority；
    当该输入尚不是 ``produced_runtime_type`` 时执行 ``method_id``，再把结果作为
    当前调用的本地 typed input。它不得扫描 Context 选择新的数学 source。
    """

    method_id: str
    source_input: str
    produced_runtime_type: str
    output_aliases: tuple[tuple[str, str], ...] = ()
    local_output_aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FunctionalOutputTargetSelectorSpec:
    """Select one existing Problem object from visible source facts.

    The selector is deliberately structural: it names a fact kind and fields,
    never a capability id, object label, or runtime handle.  It may only be
    used when the visible facts identify one target object.
    """

    output_name: str
    selector_id: Literal["unique_visible_fact_target"]
    fact_kind: str
    target_field: str
    prompt_fact_kind: str | None = None
    related_arg: str | None = None
    related_field: str | None = None
    required_field_values: tuple[tuple[str, str], ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        required = (
            self.output_name,
            self.selector_id,
            self.fact_kind,
            self.target_field,
            self.description,
        )
        if any(not item.strip() for item in required):
            raise ValueError("functional output target selector must be described")
        if (self.related_arg is None) != (self.related_field is None):
            raise ValueError(
                "functional output target selector related arg/field must be paired"
            )
        if self.prompt_fact_kind is not None and not self.prompt_fact_kind.strip():
            raise ValueError(
                "functional output target selector prompt fact kind is empty"
            )
        keys = [key for key, _value in self.required_field_values]
        if (
            any(not key.strip() or not value.strip() for key, value in self.required_field_values)
            or len(keys) != len(set(keys))
        ):
            raise ValueError(
                "functional output target selector field constraints must be unique"
            )

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "selector": self.selector_id,
            "fact_kind": self.prompt_fact_kind or self.fact_kind,
            "target_field": self.target_field,
            "description": self.description,
        }
        if self.related_arg is not None:
            payload["related_arg"] = self.related_arg
            payload["related_field"] = self.related_field
        if self.required_field_values:
            payload["required_fields"] = {
                key: value for key, value in self.required_field_values
            }
        return payload

    def to_prompt_payload(self) -> dict[str, object]:
        payload = self.to_payload()
        payload["policy"] = payload.pop("selector")
        return payload


@dataclass(frozen=True)
class MethodBindingRuleSpec:
    """一个 method 的 declarative binding 规则。

    ``input_bindings`` 负责typed source/derivation；aggregate lowerings负责把公开
    集合按声明映射到runtime slots，不允许再通过字符串selector扩展输入。
    """

    method_id: str
    # Planner-facing names may be clearer than legacy method slot/output keys.
    # Each tuple is ``(runtime_name, functional_name)`` and must be bijective.
    functional_input_names: tuple[tuple[str, str], ...] = ()
    functional_output_names: tuple[tuple[str, str], ...] = ()
    functional_output_target_selectors: tuple[
        FunctionalOutputTargetSelectorSpec, ...
    ] = ()
    input_bindings: tuple[MethodInputBindingSpec, ...] = ()
    aggregate_input_bindings: tuple[MethodAggregateInputBindingSpec, ...] = ()
    scalar_aggregate_lowerings: tuple[
        MethodScalarAggregateLoweringSpec, ...
    ] = ()
    prep_invocations: tuple[MethodPrepInvocationSpec, ...] = ()
    constraint_analyzer: str | None = None


@dataclass(frozen=True)
class StepRecipeSpec:
    """题型级“标准解题动作”规格。

    Recipe 位于 method 之上，用来表达一个教学步骤常常需要的一组 method 能力，
    例如“直角等腰构造候选点后再按约束筛选”。它只给 Strategy Planner 提供
    菜单和正向引导，不直接决定执行结果；后续 resolver/trial 仍需要用可验算的
    method 输出裁决。
    """

    recipe_id: str
    goal_type: str
    title: str
    description: str
    method_ids: tuple[str, ...] = ()
    execution: RecipeExecutionSpec | None = None
    # 首版只支持 preferred / None。preferred 用来告诉 LLM：这类题优先选择这个
    # 标准路径，尤其用于路径最值，避免模型默认走参数化求导。
    priority: str | None = None
    do_not_use_when: tuple[str, ...] = ()
    repair_feedback_provider_id: str | None = None


CapabilityExecutionStatus = Literal["executable", "catalog_only", "internal"]
CapabilityContractSource = Literal["explicit", "projected"]
CapabilityScopePolicy = Literal["current", "current_or_visible", "problem", "same_as_target"]
CapabilityCardinality = Literal["one", "optional", "many"]
CapabilityDependencyPolicy = Literal["explicit_args", "context_closure"]
FunctionalSemanticRefRole = Literal["value", "object_identity"]
FunctionalReturnBindingPolicy = Literal[
    "auto",
    "internal_only",
    "external_allowed",
    "explicit_external_required",
    "call_local_allowed",
]
CapabilityStateClosurePolicy = Literal[
    "any",
    "closed_only",
    "closed_or_single_free",
]
CapabilityContextResolver = Literal[
    "condition_object_roles",
    "equal_length_ray_path_roles",
    "path_reduction_roles",
    "square_path_transformation_roles",
    "weighted_path_transformation_roles",
]
CONDITION_OBJECT_ROLES_RESOLVER: CapabilityContextResolver = (
    "condition_object_roles"
)
EQUAL_LENGTH_RAY_PATH_ROLES_RESOLVER: CapabilityContextResolver = (
    "equal_length_ray_path_roles"
)
PATH_REDUCTION_ROLES_RESOLVER: CapabilityContextResolver = (
    "path_reduction_roles"
)
SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER: CapabilityContextResolver = (
    "square_path_transformation_roles"
)
WEIGHTED_PATH_TRANSFORMATION_ROLES_RESOLVER: CapabilityContextResolver = (
    "weighted_path_transformation_roles"
)


@dataclass(frozen=True)
class StateSlotPattern:
    """Capability contract pattern for semantic state values.

    Patterns intentionally describe object/state semantics instead of canonical
    handles. Canonical handles remain projection metadata owned by the runtime.
    """

    state_kind: str
    runtime_type: str
    object_kind: str | None = None
    object_ref: str | None = None
    semantic_role: str | None = None
    output_key: str | None = None
    scope_policy: CapabilityScopePolicy = "current_or_visible"
    cardinality: CapabilityCardinality = "one"
    required: bool = True
    identity_policy: StateIdentityPolicy | None = None
    identity_arg: str | None = None
    write_mode: StateWriteMode = "value"
    description: str = ""
    provides_semantic_roles: tuple[str, ...] = ()
    result_form: ScalarResultFormSpec | None = None
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = ()
    lineage_closures: tuple[StateLineageClosureSpec, ...] = ()
    input_closure_policy: CapabilityStateClosurePolicy = "any"
    return_binding: FunctionalReturnBindingPolicy = "auto"
    semantic_ref_role: FunctionalSemanticRefRole = "value"
    allows_anonymous_result: bool = False

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "state_kind": self.state_kind,
            "runtime_type": self.runtime_type,
            "scope_policy": self.scope_policy,
            "cardinality": self.cardinality,
            "required": self.required,
            "write_mode": self.write_mode,
        }
        if self.object_kind is not None:
            payload["object_kind"] = self.object_kind
        if self.object_ref is not None:
            payload["object_ref"] = self.object_ref
        if self.identity_policy is not None:
            payload["identity_policy"] = self.identity_policy
        if self.identity_arg is not None:
            payload["identity_arg"] = self.identity_arg
        if self.semantic_role is not None:
            payload["semantic_role"] = self.semantic_role
        if self.semantic_ref_role != "value":
            payload["semantic_ref_role"] = self.semantic_ref_role
        if self.allows_anonymous_result:
            payload["allows_anonymous_result"] = True
        if self.output_key is not None:
            payload["output_key"] = self.output_key
        if self.description:
            payload["description"] = self.description
        if self.provides_semantic_roles:
            payload["provides_semantic_roles"] = list(
                self.provides_semantic_roles
            )
        if self.result_form is not None:
            payload["result_form"] = self.result_form.to_payload()
        if self.object_role_projections:
            payload["object_role_projections"] = [
                item.to_payload() for item in self.object_role_projections
            ]
        if self.lineage_closures:
            payload["lineage_closures"] = [
                item.to_payload() for item in self.lineage_closures
            ]
        if self.input_closure_policy != "any":
            payload["input_closure_policy"] = self.input_closure_policy
        if self.return_binding != "auto":
            payload["return_binding"] = self.return_binding
        return payload


@dataclass(frozen=True)
class ConditionPattern:
    """Capability contract pattern for condition/fact prerequisites or writes."""

    condition_kind: str
    runtime_type: str = "Condition"
    scope_policy: CapabilityScopePolicy = "current_or_visible"
    cardinality: CapabilityCardinality = "one"
    required: bool = True
    deterministic_resolver: str | None = None
    description: str = ""

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "condition_kind": self.condition_kind,
            "runtime_type": self.runtime_type,
            "scope_policy": self.scope_policy,
            "cardinality": self.cardinality,
            "required": self.required,
        }
        if self.description:
            payload["description"] = self.description
        if self.deterministic_resolver is not None:
            payload["deterministic_resolver"] = self.deterministic_resolver
        return payload


@dataclass(frozen=True)
class CapabilityInputClosureRequirement:
    """A conditionally required semantic input.

    The role may be supplied explicitly, embedded in one of the declared
    provider arguments, or recovered from uniquely linked provenance. Merely
    having a compatible value somewhere in Context never satisfies it.
    """

    semantic_role: str
    provider_arg_roles: tuple[str, ...] = ()
    cardinality: CapabilityCardinality = "one"
    description: str = ""

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "semantic_role": self.semantic_role,
            "provider_arg_roles": list(self.provider_arg_roles),
            "cardinality": self.cardinality,
        }
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass(frozen=True)
class PathTransformationConsumerSpec:
    """Declare the semantic role profile consumed from a transformation."""

    transformation_arg: str
    required_roles: tuple[str, ...]
    profile: Literal["standard_broken_path", "linked_auxiliary"]

    def to_payload(self) -> dict[str, object]:
        return {
            "transformation_arg": self.transformation_arg,
            "required_roles": list(self.required_roles),
            "profile": self.profile,
        }


@dataclass(frozen=True)
class CapabilityContractSpec:
    """Declarative semantic contract for a method or recipe capability.

    Contract specs are a prompt/context/preflight declaration layer. Runtime
    execution still uses existing method specs, recipe specs, and binding rules.
    """

    capability_id: str
    kind: str = "method"
    execution_status: CapabilityExecutionStatus = "executable"
    source: CapabilityContractSource = "explicit"
    slot_reads: tuple[StateSlotPattern, ...] = ()
    condition_reads: tuple[ConditionPattern, ...] = ()
    slot_writes: tuple[StateSlotPattern, ...] = ()
    condition_writes: tuple[ConditionPattern, ...] = ()
    exposes_to_llm: bool = True
    notes: tuple[str, ...] = ()
    complete: bool | None = None
    constraint_analyzer: str | None = None
    dependency_policy: CapabilityDependencyPolicy = "explicit_args"
    context_resolvers: tuple[CapabilityContextResolver, ...] = ()
    context_role_bindings: tuple[CapabilityContextRoleBindingSpec, ...] = ()
    input_closure_requirements: tuple[
        CapabilityInputClosureRequirement, ...
    ] = ()
    identity_constraints: tuple[StateIdentityConstraintSpec, ...] = ()
    path_transformation_consumer: PathTransformationConsumerSpec | None = None

    @property
    def is_complete(self) -> bool:
        """Whether the contract declares an externally visible state effect."""
        if self.complete is not None:
            return self.complete
        return bool(self.slot_writes or self.condition_writes)

    def to_payload(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "execution_status": self.execution_status,
            "source": self.source,
            "slot_reads": [item.to_payload() for item in self.slot_reads],
            "condition_reads": [item.to_payload() for item in self.condition_reads],
            "slot_writes": [item.to_payload() for item in self.slot_writes],
            "condition_writes": [item.to_payload() for item in self.condition_writes],
            "exposes_to_llm": self.exposes_to_llm,
            "notes": list(self.notes),
            "complete": self.is_complete,
            "constraint_analyzer": self.constraint_analyzer,
            "dependency_policy": self.dependency_policy,
            "context_resolvers": list(self.context_resolvers),
            "context_role_bindings": [
                item.to_payload() for item in self.context_role_bindings
            ],
            "input_closure_requirements": [
                item.to_payload() for item in self.input_closure_requirements
            ],
            "identity_constraints": [
                item.to_payload() for item in self.identity_constraints
            ],
            "path_transformation_consumer": (
                self.path_transformation_consumer.to_payload()
                if self.path_transformation_consumer is not None
                else None
            ),
        }


@dataclass(frozen=True)
class CapabilityPackSpec:
    """一组可复用 method / recipe 能力。

    Phase 2 starts moving reusable capability contracts and generic binding
    rules into packs. Family-level declarations remain as local additions or
    overrides.
    """

    pack_id: str
    kind: str
    method_ids: tuple[str, ...] = ()
    step_recipes: tuple[StepRecipeSpec, ...] = ()
    strategy_notes: tuple[str, ...] = ()
    contracts: tuple[CapabilityContractSpec, ...] = ()
    method_binding_rules: tuple[MethodBindingRuleSpec, ...] = ()
    goal_evidence_policies: tuple[GoalEvidencePolicySpec, ...] = ()


@dataclass(frozen=True)
class CapabilityPackRegistry:
    """内存中的 CapabilityPackSpec 注册表。"""

    packs: tuple[CapabilityPackSpec, ...]
    _by_id: dict[str, CapabilityPackSpec] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_id: dict[str, CapabilityPackSpec] = {}
        for pack in self.packs:
            if pack.pack_id in by_id:
                raise ValueError(f"duplicate capability pack: {pack.pack_id}")
            by_id[pack.pack_id] = pack
        object.__setattr__(self, "_by_id", by_id)

    def require(self, pack_id: str) -> CapabilityPackSpec:
        """按 pack_id 读取 pack；不存在时给出稳定错误。"""
        try:
            return self._by_id[pack_id]
        except KeyError as exc:
            raise ValueError(f"unknown capability pack: {pack_id}") from exc


@dataclass(frozen=True)
class FamilyMatchRule:
    """Family 的粗粒度匹配条件。

    这里目前只匹配 ``pattern`` 和 ``problem_type``。更细的对象结构、目标类型、
    历史相似度等信号后续可以继续加入，但不应该把单题答案或固定步骤放进来。
    """

    patterns: tuple[str, ...] = ()
    problem_types: tuple[str, ...] = ()

    def matches(self, problem: ProblemIR) -> bool:
        """判断 ProblemIR 是否命中当前 family 的题型范围。"""
        pattern_ok = not self.patterns or problem.pattern in self.patterns
        type_ok = not self.problem_types or problem.problem_type in self.problem_types
        return pattern_ok and type_ok


@dataclass(frozen=True)
class SolverFamilySpec:
    """SolverFamily 的题型策略参考。

    ``SolverFamilySpec`` 给 Planner 提供“这类题通常怎么想”的上下文，例如常见
    goal、策略原则、可用 method 菜单和标准 recipe 菜单。它不指定 planner，不写死
    分问答案结构，也不包含任何具体题目的最终答案。
    """

    family_id: str
    match: FamilyMatchRule
    title: str = ""
    description: str = ""
    use_when: str = ""
    do_not_use_when: tuple[str, ...] = ()
    required_source_requirements: tuple[FamilySourceRequirementSpec, ...] = ()
    runtime_preflights: tuple[FamilyRuntimePreflightSpec, ...] = ()
    source_goal_contracts: tuple[FamilySourceGoalContractSpec, ...] = ()
    common_goal_types: tuple[str, ...] = ()
    strategy_principles: tuple[str, ...] = ()
    base_packs: tuple[str, ...] = ()
    mechanism_packs: tuple[str, ...] = ()
    # Intent Planner 用这个 allowlist 控制 prompt 中可见的 method 集合。它只是
    # family 给 planner 的能力边界，不表示 family 指定某个 planner 或固定步骤。
    method_ids: tuple[str, ...] = ()
    # Recipe 是 family 级标准动作菜单。单 method 步骤可以直接用 method_id 作为
    # recipe_hint，只有多个 method 组合或非常关键的标准用法才需要抽成 recipe。
    step_recipes: tuple[StepRecipeSpec, ...] = ()
    # Method binding 规则也是 family 级能力边界的一部分：LLM 只输出 canonical
    # handles，runtime 通过这些规则把 handles 映射成 method input slots。
    method_binding_rules: tuple[MethodBindingRuleSpec, ...] = ()
    # Capability contracts are the semantic declaration layer consumed by
    # prompt gates, preflight, context snapshots, and future functional
    # orchestration. They do not replace runtime execution in Phase 2.
    capability_contracts: tuple[CapabilityContractSpec, ...] = ()
    goal_evidence_policies: tuple[GoalEvidencePolicySpec, ...] = ()

    def supports(self, problem: ProblemIR) -> bool:
        """判断当前 spec 是否在结构上支持某个 ProblemIR。"""
        return self.match.matches(problem)

    def authoring_guidance_payload(self) -> dict[str, object]:
        """Return source-visible family selection guidance for extraction."""
        if (
            not self.title.strip()
            or not self.description.strip()
            or not self.use_when.strip()
        ):
            raise ValueError(
                f"family {self.family_id!r} has incomplete authoring guidance"
            )
        if not self.do_not_use_when:
            raise ValueError(
                f"family {self.family_id!r} must declare do_not_use_when"
            )
        if not self.required_source_requirements:
            raise ValueError(
                f"family {self.family_id!r} must declare source requirements"
            )
        unknown_preflight_methods = tuple(
            item.method_id
            for item in self.runtime_preflights
            if item.method_id not in self.method_ids
        )
        if unknown_preflight_methods:
            raise ValueError(
                f"family {self.family_id!r} runtime preflight methods are not enabled: "
                f"{unknown_preflight_methods}"
            )
        return {
            "family_id": self.family_id,
            "patterns": list(self.match.patterns),
            "problem_types": list(self.match.problem_types),
            "title": self.title.strip(),
            "description": self.description.strip(),
            "use_when": self.use_when.strip(),
            "required_source_primitives": [
                item.to_payload() for item in self.required_source_requirements
            ],
            "runtime_preflights": [
                item.to_payload() for item in self.runtime_preflights
            ],
            "source_goal_contracts": [
                item.to_payload() for item in self.source_goal_contracts
            ],
            "do_not_use_when": list(self.do_not_use_when),
        }


def expand_family_spec(
    family: SolverFamilySpec,
    packs: CapabilityPackRegistry,
) -> SolverFamilySpec:
    """把 family 声明的 packs 展开成 runtime 仍可直接消费的 SolverFamilySpec。

    合并顺序固定为 base packs -> mechanism packs -> family local additions。
    ``method_ids`` 稳定去重；``step_recipes`` 按 recipe_id 去重，family local recipe
    可以覆盖 pack recipe；pack-level binding rules and contracts are merged as
    defaults, while family local declarations can override them. Pack-to-pack
    conflicts for the same method binding or capability contract are rejected.
    """

    selected_packs = tuple(
        packs.require(pack_id)
        for pack_id in (*family.base_packs, *family.mechanism_packs)
    )
    method_ids = unique_ordered((
        *[
            method_id
            for pack in selected_packs
            for method_id in pack.method_ids
        ],
        *family.method_ids,
    ))
    recipes = _merge_step_recipes(
        *(
            recipe
            for pack in selected_packs
            for recipe in pack.step_recipes
        ),
        *family.step_recipes,
    )
    strategy_principles = unique_ordered((
        *[
            note
            for pack in selected_packs
            for note in pack.strategy_notes
        ],
        *family.strategy_principles,
    ))
    method_binding_rules = _merge_method_binding_rules(
        *(
            rule
            for pack in selected_packs
            for rule in pack.method_binding_rules
        ),
        family_rules=family.method_binding_rules,
    )
    capability_contracts = _merge_capability_contracts(
        *(
            contract
            for pack in selected_packs
            for contract in pack.contracts
        ),
        family_contracts=family.capability_contracts,
    )
    goal_evidence_policies = unique_ordered(
        (
            *(
                policy
                for pack in selected_packs
                for policy in pack.goal_evidence_policies
            ),
            *family.goal_evidence_policies,
        )
    )
    return SolverFamilySpec(
        family_id=family.family_id,
        match=family.match,
        title=family.title,
        description=family.description,
        use_when=family.use_when,
        do_not_use_when=family.do_not_use_when,
        required_source_requirements=family.required_source_requirements,
        runtime_preflights=family.runtime_preflights,
        source_goal_contracts=family.source_goal_contracts,
        common_goal_types=family.common_goal_types,
        strategy_principles=strategy_principles,
        base_packs=family.base_packs,
        mechanism_packs=family.mechanism_packs,
        method_ids=method_ids,
        step_recipes=recipes,
        method_binding_rules=method_binding_rules,
        capability_contracts=capability_contracts,
        goal_evidence_policies=goal_evidence_policies,
    )


def _merge_step_recipes(*recipes: StepRecipeSpec) -> tuple[StepRecipeSpec, ...]:
    """按 recipe_id 稳定合并，后出现的 recipe 覆盖同 id 的内容。"""
    index_by_id: dict[str, int] = {}
    result: list[StepRecipeSpec] = []
    for recipe in recipes:
        existing = index_by_id.get(recipe.recipe_id)
        if existing is None:
            index_by_id[recipe.recipe_id] = len(result)
            result.append(recipe)
        else:
            result[existing] = recipe
    return tuple(result)


def _merge_method_binding_rules(
    *pack_rules: MethodBindingRuleSpec,
    family_rules: tuple[MethodBindingRuleSpec, ...],
) -> tuple[MethodBindingRuleSpec, ...]:
    """Merge pack default binding rules with family local overrides."""
    index_by_id: dict[str, int] = {}
    result: list[MethodBindingRuleSpec] = []
    for rule in pack_rules:
        existing = index_by_id.get(rule.method_id)
        if existing is None:
            index_by_id[rule.method_id] = len(result)
            result.append(rule)
            continue
        if not _method_binding_rules_equivalent(result[existing], rule):
            raise ValueError(
                f"conflicting capability pack binding rule: {rule.method_id}"
            )
    for rule in family_rules:
        existing = index_by_id.get(rule.method_id)
        if existing is None:
            index_by_id[rule.method_id] = len(result)
            result.append(rule)
        else:
            result[existing] = rule
    return tuple(result)


def _method_binding_rules_equivalent(
    left: MethodBindingRuleSpec,
    right: MethodBindingRuleSpec,
) -> bool:
    """Return whether two pack binding declarations are the same contract.

    This intentionally uses dataclass value equality today: selector tuple order
    remains part of the declaration because prep and expansion order may affect
    deterministic binding behavior. Keeping the comparison named makes that
    policy explicit and gives us one place to relax order sensitivity later.
    """
    return left == right


def _merge_capability_contracts(
    *pack_contracts: CapabilityContractSpec,
    family_contracts: tuple[CapabilityContractSpec, ...],
) -> tuple[CapabilityContractSpec, ...]:
    """Merge pack default capability contracts with family local overrides."""
    index_by_id: dict[str, int] = {}
    result: list[CapabilityContractSpec] = []
    for contract in pack_contracts:
        existing = index_by_id.get(contract.capability_id)
        if existing is None:
            index_by_id[contract.capability_id] = len(result)
            result.append(contract)
            continue
        if result[existing] != contract:
            raise ValueError(
                f"conflicting capability pack contract: {contract.capability_id}"
            )
    for contract in family_contracts:
        existing = index_by_id.get(contract.capability_id)
        if existing is None:
            index_by_id[contract.capability_id] = len(result)
            result.append(contract)
        else:
            result[existing] = contract
    return tuple(result)


@dataclass(frozen=True)
class FamilyRegistry:
    """内存中的 SolverFamilySpec 注册表。

    Phase 1 只有一个 quadratic path minimum family，但这里先保留注册表形态，方便
    engine 先匹配 family，再交给通用 RuntimeOrchestrator 编排执行。
    """

    families: tuple[SolverFamilySpec, ...]

    def match(self, problem: ProblemIR) -> SolverFamilySpec | None:
        """返回唯一结构匹配的 family；歧义配置直接失败。"""
        matches = tuple(
            family for family in self.families if family.supports(problem)
        )
        if len(matches) > 1:
            raise ValueError(
                "ambiguous solver family match: "
                + ", ".join(family.family_id for family in matches)
            )
        return matches[0] if matches else None
