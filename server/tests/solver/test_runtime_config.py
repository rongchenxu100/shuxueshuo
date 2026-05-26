from __future__ import annotations

import pytest

from shuxueshuo_server.solver.family import (
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.runtime.config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    SolverRuntimeConfig,
    SolverRuntimeConfigError,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMClientConfigurationError
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.controlled_llm_planner import ControlledLLMPlanner
from shuxueshuo_server.solver.runtime.llm_step_planner import LLMStepDecompositionPlanner


ENV_KEYS = [
    "SOLVER_PLANNER_MODE",
    "SOLVER_LLM_PROVIDER",
    "SOLVER_LLM_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DOUBAO_API_KEY",
    "DOUBAO_BASE_URL",
    "DOUBAO_MODEL",
]


@pytest.fixture(autouse=True)
def _clear_solver_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """避免开发机本地 .env / shell 环境影响配置单测。"""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_runtime_config_defaults_to_deterministic(tmp_path) -> None:
    """默认配置不触发 LLM，也不要求 API key。"""
    config = SolverRuntimeConfig.from_sources(env_file=tmp_path / ".env")

    assert config.planner_mode == "deterministic"
    assert config.llm_provider == "deepseek"
    assert config.deepseek_base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.deepseek_model == DEFAULT_DEEPSEEK_MODEL


def test_runtime_config_cli_overrides_env_file(tmp_path) -> None:
    """CLI 参数优先级高于 .env。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SOLVER_PLANNER_MODE=deterministic",
                "SOLVER_LLM_PROVIDER=doubao",
                "SOLVER_LLM_MODEL=env-model",
                "DEEPSEEK_API_KEY=env-key",
            ]
        ),
        encoding="utf-8",
    )

    config = SolverRuntimeConfig.from_sources(
        planner_mode="llm",
        llm_provider="deepseek",
        llm_model="cli-model",
        env_file=env_file,
    )

    assert config.planner_mode == "llm"
    assert config.llm_provider == "deepseek"
    assert config.llm_model == "cli-model"
    assert config.deepseek_api_key == "env-key"


def test_runtime_config_rejects_invalid_choice(tmp_path) -> None:
    """非法 planner/provider 名称应在配置阶段失败。"""
    with pytest.raises(SolverRuntimeConfigError, match="invalid --planner"):
        SolverRuntimeConfig.from_sources(
            planner_mode="free-form",
            env_file=tmp_path / ".env",
        )


def test_llm_config_requires_provider_api_key() -> None:
    """真实 provider 缺 key 时不能静默构造。"""
    config = SolverRuntimeConfig(planner_mode="llm", llm_provider="deepseek")

    with pytest.raises(LLMClientConfigurationError, match="DEEPSEEK_API_KEY"):
        config.build_llm_client()


def test_fake_llm_provider_covers_supported_families() -> None:
    """--planner llm 的 fake provider 必须覆盖当前两个 supported family。"""
    config = SolverRuntimeConfig(planner_mode="llm", llm_provider="fake")

    providers = config.build_planner_providers()

    assert set(providers) == {
        QUADRATIC_PATH_MINIMUM_FAMILY.family_id,
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id,
    }


def test_fake_llm_provider_uses_controlled_planner_for_nankai_only() -> None:
    """D1 中南开 fake 走 controlled draft，河西 fake 暂留 legacy slice。"""
    providers = SolverRuntimeConfig(planner_mode="llm", llm_provider="fake").build_planner_providers()
    nankai_context = ContextBuilder().build(
        load_problem_ir("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json")
    )
    hexi_context = ContextBuilder().build(
        load_problem_ir("../internal/solver-fixtures/tj-2026-hexi-yimo-25.json")
    )

    nankai_planner = providers[QUADRATIC_PATH_MINIMUM_FAMILY.family_id](nankai_context)
    hexi_planner = providers[QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id](hexi_context)

    assert isinstance(nankai_planner, ControlledLLMPlanner)
    assert isinstance(hexi_planner, LLMStepDecompositionPlanner)


def test_environment_blank_key_overrides_env_file(tmp_path, monkeypatch) -> None:
    """空环境变量应覆盖 .env，便于 CLI 测试模拟缺 key。"""
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    config = SolverRuntimeConfig.from_sources(
        planner_mode="llm",
        llm_provider="deepseek",
        env_file=env_file,
    )

    assert config.deepseek_api_key is None
