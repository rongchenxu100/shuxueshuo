"""一次 solver 运行的审计记录。

这里的类型只记录“发生了什么”，不参与数学执行。它们不会写入
``RuntimeContext``，也不会成为 method 的输入；后续 gap/fallback 系统可以读取这些
摘要来定位需要补充的 family、method 或 prompt。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StructuredSolveError:
    """可传回 Planner 的结构化错误。

    只保存错误码、位置和可读信息，不保存 Python traceback，避免把实现细节或敏感
    上下文塞进下一轮 LLM prompt。
    """

    stage: str
    code: str
    message: str
    retryable: bool = True
    step_id: str | None = None
    method_id: str | None = None
    invocation_id: str | None = None
    path: str | None = None
    check_name: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """转换成 ``PlannerInputs.previous_errors`` 可直接携带的安全 dict。"""
        payload: dict[str, Any] = {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        for key in ("step_id", "method_id", "invocation_id", "path", "check_name"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        if self.details:
            payload["details"] = _clean_for_json(self.details)
        return payload


@dataclass(frozen=True)
class LLMCallRecord:
    """一次 LLM 调用的安全摘要。"""

    provider: str
    model: str | None = None
    response_model: str | None = None
    usage: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """转换成 CLI/测试可读的 JSON 友好结构。"""
        payload: dict[str, Any] = {"provider": self.provider}
        if self.model:
            payload["model"] = self.model
        if self.response_model:
            payload["response_model"] = self.response_model
        if self.usage:
            payload["usage"] = _clean_for_json(self.usage)
        return payload


@dataclass
class SolveAttemptRecord:
    """一次完整求解 attempt 的摘要。"""

    attempt_index: int
    status: str
    stage: str
    duration_ms: int
    previous_error_count: int = 0
    error: StructuredSolveError | None = None
    llm_call: LLMCallRecord | None = None

    def to_payload(self) -> dict[str, Any]:
        """转换成对外安全摘要，不包含 prompt 或 raw response。"""
        payload: dict[str, Any] = {
            "attempt_index": self.attempt_index,
            "status": self.status,
            "stage": self.stage,
            "duration_ms": self.duration_ms,
            "previous_error_count": self.previous_error_count,
        }
        if self.error is not None:
            payload["error"] = self.error.to_payload()
        if self.llm_call is not None:
            payload["llm_call"] = self.llm_call.to_payload()
        return payload


@dataclass
class SolveSession:
    """一次 ``RuntimeOrchestrator.solve`` 的运行审计信息。"""

    problem_id: str
    family_id: str
    max_attempts: int
    attempts: list[SolveAttemptRecord] = field(default_factory=list)
    final_status: str | None = None

    def add_attempt(self, record: SolveAttemptRecord) -> None:
        """追加 attempt 摘要。"""
        self.attempts.append(record)

    @property
    def has_llm_activity(self) -> bool:
        """是否发生过 LLM 调用。deterministic 路径通常不需要输出 run_log。"""
        return any(record.llm_call is not None for record in self.attempts)

    @property
    def total_usage(self) -> dict[str, int]:
        """聚合所有 attempt 的 token usage。"""
        total: dict[str, int] = {}
        for record in self.attempts:
            usage = record.llm_call.usage if record.llm_call else None
            if not usage:
                continue
            for key, value in usage.items():
                if isinstance(value, int):
                    total[key] = total.get(key, 0) + value
        return total

    def to_public_dict(self) -> dict[str, Any]:
        """生成可写入 ``SolverResult.run_log`` 的安全摘要。"""
        payload: dict[str, Any] = {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "max_attempts": self.max_attempts,
            "final_status": self.final_status,
            "attempts": [attempt.to_payload() for attempt in self.attempts],
        }
        total_usage = self.total_usage
        if total_usage:
            payload["total_usage"] = total_usage
        return payload


def structured_error_from_exception(
    *,
    stage: str,
    exc: Exception,
    retryable: bool = True,
) -> StructuredSolveError:
    """把异常转成可传回 LLM 的结构化错误。"""
    return StructuredSolveError(
        stage=stage,
        code=_error_code(stage, exc),
        message=str(exc) or exc.__class__.__name__,
        retryable=retryable,
        details={"exception_type": exc.__class__.__name__},
    )


def _error_code(stage: str, exc: Exception) -> str:
    """根据阶段和异常文本生成稳定的错误码。"""
    message = str(exc).lower()
    if "invalid json" in message:
        return "invalid_json"
    if "missing required" in message:
        return "missing_required_input"
    if "unknown candidate" in message:
        return "unknown_candidate_id"
    if "unknown declaration" in message:
        return "unknown_declaration"
    if "unknown promote" in message:
        return "unknown_promote_target"
    return f"{stage}_failed"


def _clean_for_json(value: Any) -> Any:
    """把审计数据清理成 JSON 友好结构。"""
    if isinstance(value, dict):
        return {str(key): _clean_for_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_for_json(item) for item in value]
    return value
