"""Method Solver 跨层共享契约。

本模块放置会同时被 solver 对外结果、runtime、stateless method 使用的轻量模型。
它不包含 ProblemIR、SolverResult、RuntimeScope 这类具体层级对象，避免外部 I/O
模型和 runtime 黑板模型互相耦合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import sympy as sp


CheckStatus = Literal["passed", "failed"]
Point = tuple[sp.Expr, sp.Expr]


@dataclass
class CheckResult:
    """一次可机读验算的结果。"""

    name: str
    status: CheckStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "passed"


@dataclass
class DerivationStep:
    """一段可展示给用户或学生的推导骨架。"""

    title: str
    goal: str
    reason: str
    calculation: str
    conclusion: str
    method_id: str


@dataclass
class TypedValue:
    """运行时黑板中的带类型值。

    ``type`` 是 runtime 自己的轻量类型系统，用于校验 MethodSpec 的输入输出；
    ``locked`` 用来保护题设已知量，避免 invocation 把原题给定的点坐标覆盖掉；
    ``source`` 记录值来自题设、某个 method，还是测试辅助写入，便于后续 trace。
    """

    type: str
    value: Any
    locked: bool = False
    source: str = ""


@dataclass(frozen=True)
class PointRef:
    """尚未求出坐标的点引用。

    题目里很多点不是显式坐标，而是“D 是对称轴与 x 轴交点”“N 满足直角等腰
    条件”这类定义。V1.5 用 PointRef 保留原始定义和所在 path，等 Planner 找到
    合适 method 后再把它 promote 成真正的 ``Point``。
    """

    name: str
    path: str
    definition: dict[str, Any] = field(default_factory=dict)
    scope_id: str = "problem"


@dataclass(frozen=True)
class MethodInputSpec:
    """MethodSpec 中的单个输入槽位定义。"""

    name: str
    type: str
    role: str = ""
    required: bool = True


@dataclass(frozen=True)
class MethodSpec:
    """可检索、可校验的 method 能力规格。

    MethodSpec 是 method 代码内 SPEC 或派生 JSON 加载后的 Python 形态。它只描述
    method 能解决什么、需要什么输入、产出什么输出，不绑定具体题号、点名或
    fixture。
    """

    method_id: str
    title: str
    solves: tuple[str, ...]
    inputs: dict[str, MethodInputSpec]
    outputs: dict[str, str]
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    trace_template: tuple[str, ...] = ()


@dataclass
class StatelessMethodResult:
    """无状态 method 的返回结果。

    method 只返回 typed outputs、checks 和 trace fragment；是否写入上层上下文由
    InvocationExecutor/StepPlan 决定。
    """

    method_id: str
    outputs: dict[str, TypedValue] = field(default_factory=dict)
    checks: list[Any] = field(default_factory=list)
    trace_fragments: list[Any] = field(default_factory=list)
