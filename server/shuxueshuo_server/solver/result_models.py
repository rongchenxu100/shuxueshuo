"""求解结果、推导轨迹与 V1 兼容上下文模型。

这里放的是 solver 对外输出和执行聚合结果。它和 ``problem_models`` 分开，是为了
让输入 IR 与输出 trace/answer/check 的生命周期保持独立。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from shuxueshuo_server.solver.contracts import CheckResult, DerivationStep
from shuxueshuo_server.solver.problem_models import ProblemIR


SolverStatus = Literal["ok", "unsupported", "failed"]
MethodStatus = Literal["ok", "skipped", "failed"]


@dataclass
class Fact:
    """旧版求解链路使用的事实记录。

    V1.5 runtime 内部已经转向 ``TypedValue`` + ``RuntimeContext``；保留 ``Fact`` 是
    为了兼容 CLI/SolverResult 的输出结构，以及后续必要时承接人工可读事实。
    """

    id: str
    type: str
    object: str
    value: Any
    source: dict[str, str]
    confidence: float = 1.0


@dataclass
class EquationRecord:
    """求解过程中形成的方程记录。"""

    id: str
    equation: str
    symbols: list[str]
    solution: Any = None


@dataclass
class DerivationTrace:
    """可导出为讲解文档的推导骨架。"""

    problem_id: str
    pattern: str
    methods: list[str] = field(default_factory=list)
    steps: list[DerivationStep] = field(default_factory=list)


@dataclass
class MethodResult:
    """旧版有状态 Method 的返回结构。

    V1.5 的无状态 method 使用 ``StatelessMethodResult``。这个类型暂时保留，是为了
    兼容已有测试/导出入口，并给后续迁移留一个稳定壳。
    """

    method_id: str
    status: MethodStatus
    facts: list[Fact] = field(default_factory=list)
    equations: list[EquationRecord] = field(default_factory=list)
    derivation_steps: list[DerivationStep] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and all(check.ok for check in self.checks)


@dataclass
class SolverResult:
    """solver 的统一输出结构。

    CLI 和测试都依赖这个对象。``to_dict`` 会把 dataclass、tuple 等结构清理成 JSON
    友好的形状，方便导出给人工 review。
    """

    problem_id: str
    status: SolverStatus
    solver_family: str | None = None
    methods_used: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    trace: DerivationTrace | None = None
    answers: dict[str, Any] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return _clean_for_json(asdict(self))


@dataclass
class SolveContext:
    """V1 有状态 method 的执行上下文。

    当前主链路已经切到 V1.5 RuntimeContext；这个类型只作为兼容层存在。后续确认
    没有外部引用后，可以和 ``MethodResult`` 一起删除。
    """

    problem: ProblemIR
    facts: list[Fact] = field(default_factory=list)
    answers: dict[str, Any] = field(default_factory=dict)

    def add_method_result(self, result: MethodResult) -> None:
        self.facts.extend(result.facts)
        _deep_update(self.answers, result.answers)


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    """递归合并答案字典，避免同一个 question 下的不同字段互相覆盖。"""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _clean_for_json(value: Any) -> Any:
    """把 SolverResult 内部值转成 JSON 友好的基础类型。"""
    if isinstance(value, dict):
        return {str(k): _clean_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [_clean_for_json(v) for v in value]
    return value
