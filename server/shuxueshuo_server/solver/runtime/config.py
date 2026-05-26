"""Solver 运行时配置。

配置层只负责根据 CLI / 环境变量 / ``server/.env`` 选择 planner provider，并把
provider map 交给 RuntimeOrchestrator。Orchestrator 本身不需要知道 DeepSeek、
豆包或 Fake LLM 的存在。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dotenv import dotenv_values

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    FamilyRegistry,
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    DoubaoPlannerClient,
    LLMClientConfigurationError,
    LLMPlannerClient,
)

if TYPE_CHECKING:
    from shuxueshuo_server.solver.runtime.orchestrator import PlannerProvider


PlannerMode = Literal["deterministic", "llm"]
LLMProviderName = Literal["fake", "deepseek", "doubao"]

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_DOUBAO_MODEL = "doubao-seed-1-6"


class SolverRuntimeConfigError(ValueError):
    """Solver runtime 配置错误。"""


@dataclass(frozen=True)
class SolverRuntimeConfig:
    """Method Solver 的运行时配置。

    ``planner_mode`` 决定使用 deterministic provider 还是 LLM-backed provider；
    provider map 由 ``build_planner_providers`` 统一构造，调用方不需要手动拼接。
    """

    planner_mode: PlannerMode = "deterministic"
    llm_provider: LLMProviderName = "deepseek"
    llm_model: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    doubao_api_key: str | None = None
    doubao_base_url: str = DEFAULT_DOUBAO_BASE_URL
    doubao_model: str = DEFAULT_DOUBAO_MODEL

    @classmethod
    def from_sources(
        cls,
        *,
        planner_mode: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        env_file: Path | str | None = None,
    ) -> "SolverRuntimeConfig":
        """从 ``server/.env``、环境变量和 CLI 覆盖值构造配置。

        读取优先级固定为：CLI 参数 > 环境变量/``.env`` > 代码默认值。环境变量即使
        是空字符串也会覆盖 ``.env``，方便测试明确模拟“没有 key”。
        """
        values = _load_env_values(env_file)
        resolved_mode = _resolve_choice(
            cli_value=planner_mode,
            env_value=values.get("SOLVER_PLANNER_MODE"),
            default="deterministic",
            allowed={"deterministic", "llm"},
            name="planner",
        )
        resolved_provider = _resolve_choice(
            cli_value=llm_provider,
            env_value=values.get("SOLVER_LLM_PROVIDER"),
            default="deepseek",
            allowed={"fake", "deepseek", "doubao"},
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
        )

    def build_planner_providers(self) -> dict[str, "PlannerProvider"]:
        """构造 RuntimeOrchestrator 可直接使用的 planner provider map。"""
        from shuxueshuo_server.solver.runtime.controlled_llm_fakes import (
            FakeControlledLLMPlannerClient,
            controlled_llm_planner_provider,
        )
        from shuxueshuo_server.solver.runtime.llm_step_planner import (
            llm_step_decomposition_planner_provider,
        )
        from shuxueshuo_server.solver.runtime.orchestrator import (
            DEFAULT_PLANNER_PROVIDERS,
        )

        if self.planner_mode == "deterministic":
            return dict(DEFAULT_PLANNER_PROVIDERS)
        if self.llm_provider == "fake":
            # D2：fake LLM 用完整 controlled draft 覆盖当前两个 supported family。
            # 真实 DeepSeek/Doubao 仍暂走 legacy step decomposition，等后续 prompt 和
            # repair loop 稳定后再切到 controlled draft。
            controlled_provider = controlled_llm_planner_provider(
                FakeControlledLLMPlannerClient()
            )
            return {
                QUADRATIC_PATH_MINIMUM_FAMILY.family_id: controlled_provider,
                QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id: controlled_provider,
            }
        client = self.build_llm_client()
        provider = llm_step_decomposition_planner_provider(client)
        # Phase A 要求当前 supported family 在 --planner llm 下全部走 LLM-backed
        # provider；没有 compiler 的 family 不能静默回退 deterministic。
        return {
            QUADRATIC_PATH_MINIMUM_FAMILY.family_id: provider,
            QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id: provider,
        }

    def build_family_registry(self) -> FamilyRegistry:
        """按运行模式构造 family registry。

        默认 deterministic 仍使用严格白名单，确保 alt-label 不会误走旧模板。只有
        fake LLM controlled draft 模式下，才临时放开南开 alt-label 作为非 canonical
        点名回归样例。
        """
        if self.planner_mode == "llm" and self.llm_provider == "fake":
            path_family = replace(
                QUADRATIC_PATH_MINIMUM_FAMILY,
                enabled_problem_ids=(
                    "tj-2026-nankai-yimo-25",
                    "tj-2026-nankai-yimo-25-alt-labels",
                ),
            )
            return FamilyRegistry((
                path_family,
                QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
            ))
        return DEFAULT_FAMILY_REGISTRY

    def build_llm_client(self) -> LLMPlannerClient:
        """根据 provider 配置创建 LLM client。"""
        if self.llm_provider == "fake":
            from shuxueshuo_server.solver.runtime.llm_step_planner import (
                FakeLLMPlannerClient,
            )

            return FakeLLMPlannerClient()
        if self.llm_provider == "deepseek":
            if not self.deepseek_api_key:
                raise LLMClientConfigurationError(
                    "--planner llm --llm-provider deepseek requires DEEPSEEK_API_KEY"
                )
            return DeepSeekPlannerClient(
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                model=self.llm_model or self.deepseek_model,
            )
        if self.llm_provider == "doubao":
            if not self.doubao_api_key:
                raise LLMClientConfigurationError(
                    "--planner llm --llm-provider doubao requires DOUBAO_API_KEY"
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


def cli_value_or_env(cli_value: str | None, env_value: str | None) -> str | None:
    """CLI 值优先；未提供 CLI 时使用环境配置。"""
    return cli_value if cli_value is not None else env_value


def _clean(value: str | None) -> str | None:
    """把空白字符串归一化为 None。"""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


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
