"""Solver 运行时配置。

配置层只负责根据 CLI / 环境变量 / ``server/.env`` 选择 planner provider，并把
provider map 交给 RuntimeOrchestrator。Orchestrator 本身不需要知道 DeepSeek、
豆包或 Fake LLM 的存在。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dotenv import dotenv_values

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    FamilyRegistry,
)
from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    DoubaoPlannerClient,
    LLMClientConfigurationError,
    LLMPlannerClient,
)

if TYPE_CHECKING:
    from shuxueshuo_server.solver.runtime.orchestrator import PlannerProvider


PlannerMode = Literal["deterministic", "strategy"]
LLMProviderName = Literal["recorded", "deepseek", "doubao"]

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_DOUBAO_MODEL = "doubao-seed-1-6"


class SolverRuntimeConfigError(ValueError):
    """Solver runtime 配置错误。"""


@dataclass(frozen=True)
class SolverRuntimeConfig:
    """Method Solver 的运行时配置。

    ``planner_mode`` 决定使用显式 debug deterministic provider 还是生产 Strategy
    provider；provider map 与 default provider 由本配置统一构造。
    """

    planner_mode: PlannerMode = "strategy"
    llm_provider: LLMProviderName = "recorded"
    llm_model: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    doubao_api_key: str | None = None
    doubao_base_url: str = DEFAULT_DOUBAO_BASE_URL
    doubao_model: str = DEFAULT_DOUBAO_MODEL
    max_llm_attempts: int = 3
    llm_debug_dir: str | None = None
    allow_same_problem_few_shot: bool = True

    def __post_init__(self) -> None:
        """校验直接构造配置时的基础约束。"""
        if self.max_llm_attempts < 1:
            raise SolverRuntimeConfigError(
                "max_llm_attempts must be a positive integer"
            )

    @classmethod
    def from_sources(
        cls,
        *,
        planner_mode: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        max_llm_attempts: str | int | None = None,
        llm_debug_dir: str | None = None,
        allow_same_problem_few_shot: bool | str | None = None,
        env_file: Path | str | None = None,
    ) -> "SolverRuntimeConfig":
        """从 ``server/.env``、环境变量和 CLI 覆盖值构造配置。

        读取优先级固定为：CLI 参数 > 环境变量/``.env`` > 代码默认值。环境变量即使
        是空字符串也会覆盖 ``.env``，方便测试明确模拟“没有 key”。
        """
        values = _load_env_values(env_file)
        env_planner_mode = _legacy_env_alias(
            values.get("SOLVER_PLANNER_MODE"),
            aliases={"llm": "strategy"},
        )
        env_llm_provider = _legacy_env_alias(
            values.get("SOLVER_LLM_PROVIDER"),
            aliases={"fake": "recorded"},
        )
        resolved_mode = _resolve_choice(
            cli_value=planner_mode,
            env_value=env_planner_mode,
            default="strategy",
            allowed={"deterministic", "strategy"},
            name="planner",
        )
        resolved_provider = _resolve_choice(
            cli_value=llm_provider,
            env_value=env_llm_provider,
            default="recorded",
            allowed={"recorded", "deepseek", "doubao"},
            name="llm-provider",
        )
        return cls(
            planner_mode=resolved_mode,  # type: ignore[arg-type]
            llm_provider=resolved_provider,  # type: ignore[arg-type]
            llm_model=_clean(cli_value_or_env(llm_model, values.get("SOLVER_LLM_MODEL"))),
            deepseek_api_key=_clean(values.get("DEEPSEEK_API_KEY")),
            deepseek_base_url=_clean(values.get("DEEPSEEK_BASE_URL"))
            or DEFAULT_DEEPSEEK_BASE_URL,
            deepseek_model=_clean(values.get("DEEPSEEK_MODEL"))
            or DEFAULT_DEEPSEEK_MODEL,
            doubao_api_key=_clean(values.get("DOUBAO_API_KEY")),
            doubao_base_url=_clean(values.get("DOUBAO_BASE_URL"))
            or DEFAULT_DOUBAO_BASE_URL,
            doubao_model=_clean(values.get("DOUBAO_MODEL")) or DEFAULT_DOUBAO_MODEL,
            max_llm_attempts=_resolve_positive_int(
                cli_value=max_llm_attempts,
                env_value=values.get("SOLVER_LLM_MAX_ATTEMPTS"),
                default=3,
                name="llm-max-attempts",
            ),
            llm_debug_dir=_clean(
                cli_value_or_env(llm_debug_dir, values.get("SOLVER_LLM_DEBUG_DIR"))
            ),
            allow_same_problem_few_shot=_resolve_bool(
                cli_value=allow_same_problem_few_shot,
                env_value=values.get("SOLVER_ALLOW_SAME_PROBLEM_FEW_SHOT"),
                default=True,
                name="allow-same-problem-few-shot",
            ),
        )

    def build_planner_providers(self) -> dict[str, "PlannerProvider"]:
        """构造 RuntimeOrchestrator 可直接使用的 planner provider map。"""
        from shuxueshuo_server.solver.runtime.orchestrator import (
            DEBUG_DETERMINISTIC_PLANNER_PROVIDERS,
        )

        if self.planner_mode == "deterministic":
            return dict(DEBUG_DETERMINISTIC_PLANNER_PROVIDERS)
        return {}

    def build_default_planner_provider(self) -> "PlannerProvider | None":
        """构造 Orchestrator 的 default planner provider fallback。"""
        if self.planner_mode == "deterministic":
            return None
        if self.llm_provider == "recorded":
            from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
                strategy_planner_provider,
            )

            return strategy_planner_provider(
                mode="recorded",
                allow_same_problem_few_shot=self.allow_same_problem_few_shot,
            )
        if self.llm_provider == "deepseek":
            from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
                strategy_planner_provider,
            )

            return strategy_planner_provider(
                mode="deepseek",
                client=self.build_llm_client(),
                allow_same_problem_few_shot=self.allow_same_problem_few_shot,
            )
        raise SolverRuntimeConfigError(
            f"--planner strategy does not support --llm-provider {self.llm_provider!r}"
        )

    def build_family_registry(self) -> FamilyRegistry:
        """按运行模式构造 family registry。

        Strategy Planner 仍由 ProblemIR metadata 和 FamilyRegistry 选 family；不引入
        LLM family selector。
        """
        return DEFAULT_FAMILY_REGISTRY

    def build_llm_client(self) -> LLMPlannerClient:
        """根据 provider 配置创建 LLM client。"""
        if self.llm_provider == "recorded":
            raise SolverRuntimeConfigError("recorded provider does not use an LLM client")
        if self.llm_provider == "deepseek":
            if not self.deepseek_api_key:
                raise LLMClientConfigurationError(
                    "--planner strategy --llm-provider deepseek requires DEEPSEEK_API_KEY"
                )
            return DeepSeekPlannerClient(
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                model=self.llm_model or self.deepseek_model,
            )
        if self.llm_provider == "doubao":
            if not self.doubao_api_key:
                raise LLMClientConfigurationError(
                    "--llm-provider doubao requires DOUBAO_API_KEY"
                )
            return DoubaoPlannerClient(
                api_key=self.doubao_api_key,
                base_url=self.doubao_base_url,
                model=self.llm_model or self.doubao_model,
            )
        raise SolverRuntimeConfigError(f"unknown llm provider: {self.llm_provider}")


def _load_env_values(env_file: Path | str | None) -> dict[str, str]:
    """合并 ``.env`` 与真实环境变量。"""
    path = Path(env_file) if env_file is not None else _default_env_file()
    values: dict[str, str] = {}
    if path.exists():
        values.update({key: value or "" for key, value in dotenv_values(path).items()})
    for key, value in os.environ.items():
        values[key] = value
    return values


def _default_env_file() -> Path:
    """返回 server/.env 的默认位置。"""
    return Path(__file__).resolve().parents[3] / ".env"


def _resolve_choice(
    *,
    cli_value: str | None,
    env_value: str | None,
    default: str,
    allowed: set[str],
    name: str,
) -> str:
    """解析枚举型配置，并给出清晰错误。"""
    value = _clean(cli_value_or_env(cli_value, env_value)) or default
    if value not in allowed:
        raise SolverRuntimeConfigError(
            f"invalid --{name}: {value!r}; expected one of {sorted(allowed)}"
        )
    return value


def _resolve_positive_int(
    *,
    cli_value: str | int | None,
    env_value: str | None,
    default: int,
    name: str,
) -> int:
    """解析正整数配置，例如 LLM 总 attempt 预算。"""
    raw = cli_value if cli_value is not None else env_value
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise SolverRuntimeConfigError(f"invalid --{name}: {raw!r}; expected positive integer") from exc
    if value < 1:
        raise SolverRuntimeConfigError(f"invalid --{name}: {raw!r}; expected positive integer")
    return value


def _resolve_bool(
    *,
    cli_value: bool | str | None,
    env_value: str | None,
    default: bool,
    name: str,
) -> bool:
    """解析布尔配置。"""
    raw = cli_value if cli_value is not None else env_value
    if raw is None or str(raw).strip() == "":
        return default
    if isinstance(raw, bool):
        return raw
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SolverRuntimeConfigError(
        f"invalid --{name}: {raw!r}; expected boolean"
    )


def cli_value_or_env(cli_value: str | None, env_value: str | None) -> str | None:
    """CLI 值优先；未提供 CLI 时使用环境配置。"""
    return cli_value if cli_value is not None else env_value


def _clean(value: str | None) -> str | None:
    """把空白字符串归一化为 None。"""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _legacy_env_alias(value: str | None, *, aliases: dict[str, str]) -> str | None:
    """兼容旧 .env 值；CLI 显式旧值仍由 argparse/校验拒绝。"""
    cleaned = _clean(value)
    if cleaned is None:
        return None
    return aliases.get(cleaned, cleaned)


__all__ = [
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_DOUBAO_BASE_URL",
    "DEFAULT_DOUBAO_MODEL",
    "LLMClientConfigurationError",
    "LLMProviderName",
    "PlannerMode",
    "SolverRuntimeConfig",
    "SolverRuntimeConfigError",
]
