"""SolverFamily 规格模型。

本模块只描述“题型级共性”，不保存某一道题的解法步骤、答案结构或 planner 选择。
Phase 4 后，FamilySpec 只作为 RuntimeOrchestrator 和 Planner 的题型上下文，
不承担求解执行职责。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shuxueshuo_server.solver.problem_models import ProblemIR


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
    output_aliases: tuple[tuple[str, str], ...] = ()


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
    # Intent Planner 用这个 allowlist 控制 prompt 中可见的 method 集合。它只是
    # family 给 planner 的能力边界，不表示 family 指定某个 planner 或固定步骤。
    method_ids: tuple[str, ...] = ()
    # Recipe 是 family 级标准动作菜单。单 method 步骤可以直接用 method_id 作为
    # recipe_hint，只有多个 method 组合或非常关键的标准用法才需要抽成 recipe。
    step_recipes: tuple[StepRecipeSpec, ...] = ()
    # Method binding 规则也是 family 级能力边界的一部分：LLM 只输出 canonical
    # handles，runtime 通过这些规则把 handles 映射成 method input slots。
    method_binding_rules: tuple[MethodBindingRuleSpec, ...] = ()
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
