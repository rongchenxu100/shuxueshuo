"""SolverFamily 规格模型。

本模块只描述“题型级共性”，不保存某一道题的解法步骤、答案结构或 planner 选择。
Phase 4 后，FamilySpec 只作为 RuntimeOrchestrator 和 Planner 的题型上下文，
不承担求解执行职责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
]


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

    def to_payload(self) -> dict[str, object]:
        return {
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
    )

@dataclass(frozen=True)
class RecipeExecutionSpec:
    """Recipe 的可执行编排规格。

    ``StepRecipeSpec`` 面向 LLM 展示“标准解题动作”，而这里描述 runtime 如何把这个
    标准动作拆成 method 序列。它仍然是 family 级配置，不包含某道题的点名、分问 id
    或答案值。
    """

    recipe_id: str
    method_sequence: tuple[str, ...]
    # 执行策略名只选择通用编译器分支，例如“单 method”“构造候选后筛选”。
    # 它不是题号模板名，也不应该包含 D/M/N/F/G 这类具体点名。
    execution_strategy: str = "single_method"
    creates: tuple[str, ...] = ()
    input_aliases: tuple[tuple[str, str], ...] = ()
    intermediate_wiring: tuple[tuple[str, str], ...] = ()
    output_aliases: tuple[RecipeOutputAliasSpec, ...] = ()


@dataclass(frozen=True)
class MethodInputBindingSpec:
    """单个 method input slot 的语义选择规则。

    ``selector`` 指向 runtime 中的一类通用选择器，例如“读取系数关系 fact”或“读取
    当前 step 输出点的 PointRef”。method 专属的输入名留在 spec 中，避免在 runtime
    主流程里写一串 method_id 分支。
    """

    input_name: str
    selector: str
    required: bool = True


@dataclass(frozen=True)
class MethodCompanionOutputSpec:
    """method 固有伴随输出的 promote/register 规则。

    伴随输出不是 LLM 独立规划出来的结论，而是某个 method 调用稳定返回、后续
    runtime 常需要读取的输出。例如 ``quadratic_from_constraints`` 总会返回
    ``coefficients``，weighted path 三角形转化总会返回辅助点和辅助点轨迹。
    """

    output_name: str
    target_selector: str
    registration_selector: str | None = None


@dataclass(frozen=True)
class MethodPrepInvocationSpec:
    """method 前置补位 invocation 的声明式规则。

    有些 method 的教学 step 会把“先生成可读前置对象”和“使用前置对象求目标”
    合并表达。prep 规则只处理这类可确定补位：满足 ``trigger_selector`` 时，
    先执行 ``method_id``，把 ``output_aliases`` promote 到当前 scope 的临时输出，
    再通过 ``local_output_aliases`` 暴露给主 method 的 binding selector 使用。
    """

    trigger_selector: str
    method_id: str
    output_aliases: tuple[tuple[str, str], ...] = ()
    local_output_aliases: tuple[tuple[str, str], ...] = ()
    include_expansion_selectors: bool = True
    expansion_selectors: tuple[str, ...] | None = None


@dataclass(frozen=True)
class MethodBindingRuleSpec:
    """一个 method 的 declarative binding 规则。

    ``input_bindings`` 负责固定 slot；``expansion_selectors`` 用于一次性补充一组
    可选输入，例如 quadratic_from_constraints 的已知系数、参数值和曲线点。
    """

    method_id: str
    input_bindings: tuple[MethodInputBindingSpec, ...] = ()
    expansion_selectors: tuple[str, ...] = ()
    prep_invocations: tuple[MethodPrepInvocationSpec, ...] = ()
    always_emit_outputs: tuple[str, ...] = ()
    companion_outputs: tuple[MethodCompanionOutputSpec, ...] = ()
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


CapabilityExecutionStatus = Literal["executable", "catalog_only", "internal"]
CapabilityContractSource = Literal["explicit", "projected"]
CapabilityScopePolicy = Literal["current", "current_or_visible", "problem", "same_as_target"]
CapabilityCardinality = Literal["one", "optional", "many"]


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
    scope_policy: CapabilityScopePolicy = "current_or_visible"
    cardinality: CapabilityCardinality = "one"
    required: bool = True
    write_mode: StateWriteMode = "value"

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
        return payload


@dataclass(frozen=True)
class ConditionPattern:
    """Capability contract pattern for condition/fact prerequisites or writes."""

    condition_kind: str
    runtime_type: str = "Condition"
    scope_policy: CapabilityScopePolicy = "current_or_visible"
    cardinality: CapabilityCardinality = "one"
    required: bool = True

    def to_payload(self) -> dict[str, object]:
        return {
            "condition_kind": self.condition_kind,
            "runtime_type": self.runtime_type,
            "scope_policy": self.scope_policy,
            "cardinality": self.cardinality,
            "required": self.required,
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
    enabled_problem_ids: tuple[str, ...] = field(default_factory=tuple)

    def supports(self, problem: ProblemIR) -> bool:
        """判断当前 spec 是否支持某个 ProblemIR。

        ``enabled_problem_ids`` 是 Phase 1 的临时兼容硬门控：当前 deterministic
        planner 只支持 canonical 南开 25，因此即使题型 match 命中，也必须先限制
        题号，避免 alt-label 或其他 25 题误走固定南开计划。

        退出条件：至少两道同 family 的完整 E2E 题能通过，Planner 不再依赖
        canonical 点名/分问 id，且测试证明去掉该门控后不会误路由到错误 family。
        """
        if not self.match.matches(problem):
            return False
        if self.enabled_problem_ids and problem.problem_id not in self.enabled_problem_ids:
            return False
        return True


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
    return SolverFamilySpec(
        family_id=family.family_id,
        match=family.match,
        common_goal_types=family.common_goal_types,
        strategy_principles=strategy_principles,
        base_packs=family.base_packs,
        mechanism_packs=family.mechanism_packs,
        method_ids=method_ids,
        step_recipes=recipes,
        method_binding_rules=method_binding_rules,
        capability_contracts=capability_contracts,
        enabled_problem_ids=family.enabled_problem_ids,
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
        """返回第一个支持该题的 family；没有命中则返回 ``None``。"""
        for family in self.families:
            if family.supports(problem):
                return family
        return None
