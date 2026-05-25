"""SolverFamily 规格模型。

本模块只描述“题型级共性”，不保存某一道题的解法步骤、答案结构或 planner 选择。
Phase 4 后，FamilySpec 只作为 RuntimeOrchestrator 和 Planner 的题型上下文，
不承担求解执行职责。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shuxueshuo_server.solver.problem_models import ProblemIR


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
    goal、关系模式和 method 能力提示。它不指定 planner，不写死分问答案结构，也
    不包含任何具体题目的最终答案。
    """

    family_id: str
    match: FamilyMatchRule
    common_goal_types: tuple[str, ...] = ()
    strategy_principles: tuple[str, ...] = ()
    relation_patterns: tuple[str, ...] = ()
    method_capability_hints: tuple[str, ...] = ()
    result_collection_policy: str = ""
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
