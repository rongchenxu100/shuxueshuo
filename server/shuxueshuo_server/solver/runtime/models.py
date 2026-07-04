"""Method Solver V1.5 运行时数据模型。

本模块只定义“计划如何被表达”和“运行时 scope 如何组织”，不包含任何题型逻辑
或数学计算。跨层共享的 ``TypedValue``、``PointRef``、``MethodSpec`` 等契约
来自 ``solver.contracts``，这里仅 re-export 以兼容旧导入路径。

- ``ContextPath`` 负责表达“从哪个 scope 的哪个容器取值”；
- ``StepGoal`` / ``StepPlan`` / ``MethodInvocation`` 负责表达“Planner 生成了什么
  中间目标、分几步、每步调用哪些 method”；
- ``RuntimeScope`` 负责表达运行时黑板的 scope 和容器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shuxueshuo_server.solver.contracts import (
    MethodInputSpec,
    MethodSpec,
    Point,
    PointRef,
    StatelessMethodResult,
    TypedValue,
)


ScopeType = Literal["problem", "question", "subquestion", "step"]


def runtime_type_matches(expected_type: str, actual_type: str) -> bool:
    """判断 RuntimeContext 中的值类型是否能作为 method 输入类型使用。

    首版只开放很窄的类型兼容：已求出的 ``Parabola`` 本质上仍是二次表达式，
    可以传给只需要代入/求截距的 ``Expression`` 输入。其他类型继续保持严格匹配，
    避免 planner 通过宽松类型绕过 method 边界。
    """
    if "|" in expected_type:
        return any(
            runtime_type_matches(item.strip(), actual_type)
            for item in expected_type.split("|")
            if item.strip()
        )
    if expected_type == actual_type:
        return True
    if expected_type == "Expression" and actual_type == "Parabola":
        return True
    return False


@dataclass(frozen=True)
class ContextPath:
    """解析后的上下文引用。

    V1.5 不允许 MethodInvocation 直接传裸坐标或裸数值，而是要求所有输入/输出
    都写成 ContextPath，例如：

    - ``$problem.points.D``：整题 scope 下的点 D；
    - ``$question.ii.points.M``：第 ii 问 scope 下的点 M；
    - ``$step.derive_N.temp.derived_point``：某一步里的临时结果。

    解析后的字段会被 ``RuntimeContext`` 用来做作用域可见性和写入权限校验。
    """

    raw: str
    scope_type: ScopeType
    scope_id: str
    container: str
    key: str

    @classmethod
    def parse(cls, raw: str) -> "ContextPath":
        """把字符串路径解析为结构化对象，并尽早暴露非法路径格式。"""
        if not isinstance(raw, str) or not raw.startswith("$"):
            raise ValueError(f"ContextPath must start with $: {raw!r}")
        parts = raw[1:].split(".")
        if len(parts) < 3:
            raise ValueError(f"ContextPath is too short: {raw}")
        scope_type = parts[0]
        if scope_type == "problem":
            if len(parts) != 3:
                raise ValueError(f"problem path must be $problem.<container>.<key>: {raw}")
            return cls(raw, "problem", "problem", parts[1], parts[2])
        if scope_type not in {"question", "subquestion", "step"}:
            raise ValueError(f"unknown ContextPath scope type: {scope_type}")
        if len(parts) != 4:
            raise ValueError(
                f"{scope_type} path must be ${scope_type}.<id>.<container>.<key>: {raw}"
            )
        return cls(raw, scope_type, parts[1], parts[2], parts[3])

    @property
    def is_context_path(self) -> bool:
        return True


@dataclass(frozen=True)
class ContextDeclaration:
    """Planner 需要运行时提前声明的上下文占位。

    Phase B 首版只允许声明未解出的 ``PointRef``。它表达“后续某个 step 会求出
    这个点”，不携带坐标、参数值或最终答案。
    """

    path: str
    type: str
    name: str
    definition: dict[str, Any]
    scope_id: str
    source: str = "planner"


@dataclass
class StepGoal:
    """Planner 为某个 StepPlan 生成的结构化中间目标。

    ``StepGoal`` 不是题面最终作答目标，也不是 Planner 之前预先抽取的目标。它由
    Planner 在拆解步骤时创建，用来说明当前 step 要推进哪个中间结果。
    """

    goal_id: str
    type: str
    target_path: str
    scope_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MethodInvocation:
    """某个 MethodSpec 在某个 StepScope 里的具体调用。

    ``inputs`` 和 ``outputs`` 的 value 必须都是 ContextPath。点名、scope、输出写回
    位置都属于 invocation；无状态 method 本身只接收解析后的 typed inputs。
    """

    invocation_id: str
    method_id: str
    scope: str
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)


@dataclass
class StepExecutionResult:
    """StepPlan 执行后的聚合结果。"""

    step_id: str
    method_results: list[StatelessMethodResult] = field(default_factory=list)
    checks: list[Any] = field(default_factory=list)
    trace_fragments: list[Any] = field(default_factory=list)

    @property
    def methods_used(self) -> list[str]:
        """本 step 实际执行过的 method id 列表。"""
        return [result.method_id for result in self.method_results]


@dataclass
class PlanExecutionResult:
    """一组 StepPlan 顺序执行后的聚合结果。"""

    step_results: list[StepExecutionResult] = field(default_factory=list)
    checks: list[Any] = field(default_factory=list)
    trace_fragments: list[Any] = field(default_factory=list)

    @property
    def methods_used(self) -> list[str]:
        """按执行顺序展开所有 method id。"""
        return [
            method_id
            for step_result in self.step_results
            for method_id in step_result.methods_used
        ]


@dataclass
class StepPlan:
    """面向解题步骤的执行计划。

    一个 StepPlan 可以包含多个 MethodInvocation。首版样板只有一个 invocation，
    但结构上已经支持“先构造候选点，再联立方程，再筛选解”这样的多 method step。

    ``promote_outputs`` 明确声明哪些 step 临时结果可以写回上层 scope，避免临时量
    默认污染 question/subquestion。
    """

    step_id: str
    goal: StepGoal
    scope: str
    invocations: list[MethodInvocation] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    promote_outputs: dict[str, str] = field(default_factory=dict)


@dataclass
class PlannerOutput:
    """Planner 的统一输出。

    ``context_declarations`` 先由 Orchestrator 校验并应用到 RuntimeContext；
    ``step_plans`` 再交给 InvocationExecutor 顺序执行。这样 planner 不再直接修改
    context，所有写入都经过统一边界。
    """

    context_declarations: list[ContextDeclaration] = field(default_factory=list)
    step_plans: list[StepPlan] = field(default_factory=list)

    @classmethod
    def from_legacy(cls, output: "PlannerOutput | list[StepPlan]") -> "PlannerOutput":
        """兼容迁移期旧 planner 返回的 ``list[StepPlan]``。

        Phase B 后内置 planner 都应返回 PlannerOutput；这个 helper 只用于测试或
        外部调用方短期兼容，避免各处重复写 normalize 逻辑。
        """
        if isinstance(output, cls):
            return output
        if isinstance(output, list):
            return cls(step_plans=output)
        raise TypeError(f"planner returned unsupported output: {type(output).__name__}")


@dataclass
class RuntimeScope:
    """运行时上下文树中的一个作用域节点。

    - ``problem``：整题共享事实；
    - ``question``：大问级事实；
    - ``subquestion``：小问级事实；
    - ``step``：执行某一步时的临时黑板。

    ``facts`` 采用“容器名 -> key -> TypedValue”的结构，方便支持 points、symbols、
    conditions 等不同类别，同时保持 ContextPath 简单。
    """

    scope_id: str
    scope_type: ScopeType
    parent_id: str | None = None
    facts: dict[str, dict[str, TypedValue]] = field(default_factory=dict)
    constraints: dict[str, TypedValue] = field(default_factory=dict)
    temp_values: dict[str, TypedValue] = field(default_factory=dict)
    outputs: dict[str, TypedValue] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    def container(self, name: str) -> dict[str, TypedValue]:
        """按容器名返回可读写字典。

        ``temp``、``outputs``、``constraints`` 是 scope 的固定容器；其他名字统一放进
        ``facts``，例如 ``points``、``symbols``、``questions``、``conditions``。
        """
        if name == "temp":
            return self.temp_values
        if name == "outputs":
            return self.outputs
        if name == "constraints":
            return self.constraints
        return self.facts.setdefault(name, {})
