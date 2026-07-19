from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.config import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_DEEPSEEK_MODEL,
    SolverRuntimeConfig,
    SolverRuntimeConfigError,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMClientConfigurationError
from shuxueshuo_server.solver.fixtures import load_problem_ir


ENV_KEYS = [
    "SOLVER_PLANNER_MODE",
    "SOLVER_LLM_PROVIDER",
    "SOLVER_LLM_MODEL",
    "SOLVER_LLM_MAX_ATTEMPTS",
    "SOLVER_LLM_DEBUG_DIR",
    "SOLVER_ALLOW_SAME_PROBLEM_FEW_SHOT",
    "SOLVER_FUNCTIONAL_FEW_SHOT_MODE",
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


def test_runtime_config_defaults_to_strategy_recorded(tmp_path) -> None:
    """默认配置走 Strategy recorded，不要求 API key。"""
    config = SolverRuntimeConfig.from_sources(env_file=tmp_path / ".env")

    assert config.planner_mode == "strategy"
    assert config.llm_provider == "recorded"
    assert config.deepseek_base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert config.deepseek_model == DEFAULT_DEEPSEEK_MODEL
    assert config.max_llm_attempts == 3
    assert config.llm_debug_dir is None
    assert config.functional_few_shot_mode == "new_problem"


def test_runtime_config_maps_legacy_few_shot_boolean_to_functional_mode(
    tmp_path,
) -> None:
    config = SolverRuntimeConfig.from_sources(
        allow_same_problem_few_shot=False,
        env_file=tmp_path / ".env",
    )

    assert config.allow_same_problem_few_shot is False
    assert config.functional_few_shot_mode == "strict_test"


def test_explicit_functional_few_shot_mode_wins_over_legacy_boolean(
    tmp_path,
) -> None:
    config = SolverRuntimeConfig.from_sources(
        allow_same_problem_few_shot=False,
        functional_few_shot_mode="new_problem",
        env_file=tmp_path / ".env",
    )

    assert config.functional_few_shot_mode == "new_problem"


def test_runtime_config_reads_functional_few_shot_mode_from_env(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SOLVER_FUNCTIONAL_FEW_SHOT_MODE", "strict_test")

    config = SolverRuntimeConfig.from_sources(env_file=tmp_path / ".env")

    assert config.functional_few_shot_mode == "strict_test"


def test_runtime_config_rejects_invalid_functional_few_shot_mode(
    tmp_path,
) -> None:
    with pytest.raises(
        SolverRuntimeConfigError,
        match="functional-few-shot-mode",
    ):
        SolverRuntimeConfig.from_sources(
            functional_few_shot_mode="adaptive",
            env_file=tmp_path / ".env",
        )


def test_runtime_config_cli_overrides_env_file(tmp_path) -> None:
    """CLI 参数优先级高于 .env。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SOLVER_PLANNER_MODE=deterministic",
                "SOLVER_LLM_PROVIDER=recorded",
                "SOLVER_LLM_MODEL=env-model",
                "DEEPSEEK_API_KEY=env-key",
            ]
        ),
        encoding="utf-8",
    )

    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        llm_model="cli-model",
        max_llm_attempts=2,
        llm_debug_dir="../debug",
        env_file=env_file,
    )

    assert config.planner_mode == "strategy"
    assert config.llm_provider == "deepseek"
    assert config.llm_model == "cli-model"
    assert config.deepseek_api_key == "env-key"
    assert config.max_llm_attempts == 2
    assert config.llm_debug_dir == "../debug"


def test_runtime_config_maps_legacy_env_llm_fake_to_strategy_recorded(tmp_path) -> None:
    """旧 .env 的 llm/fake 值应兼容到新 Strategy recorded。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SOLVER_PLANNER_MODE=llm",
                "SOLVER_LLM_PROVIDER=fake",
            ]
        ),
        encoding="utf-8",
    )

    config = SolverRuntimeConfig.from_sources(env_file=env_file)

    assert config.planner_mode == "strategy"
    assert config.llm_provider == "recorded"


def test_runtime_config_rejects_invalid_choice(tmp_path) -> None:
    """非法 planner/provider 名称应在配置阶段失败。"""
    with pytest.raises(SolverRuntimeConfigError, match="invalid --planner"):
        SolverRuntimeConfig.from_sources(
            planner_mode="free-form",
            env_file=tmp_path / ".env",
        )


def test_llm_config_requires_provider_api_key() -> None:
    """真实 provider 缺 key 时不能静默构造。"""
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="deepseek")

    with pytest.raises(LLMClientConfigurationError, match="DEEPSEEK_API_KEY"):
        config.build_llm_client()


def test_strategy_recorded_default_provider_is_constructed() -> None:
    """Strategy recorded 构造 default provider，provider map 本身不注册 deterministic。"""
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")

    assert config.build_planner_providers() == {}
    assert config.build_default_planner_provider() is not None


def test_llm_family_registry_no_longer_relaxes_alt_label_gate() -> None:
    """旧 fake LLM 删除后，alt-label 不再被临时放开。"""
    alt = load_problem_ir("../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json")

    deterministic = SolverRuntimeConfig(planner_mode="deterministic").build_family_registry()
    strategy = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded").build_family_registry()

    assert deterministic.match(alt) is None
    assert strategy.match(alt) is None


def test_environment_blank_key_overrides_env_file(tmp_path, monkeypatch) -> None:
    """空环境变量应覆盖 .env，便于 CLI 测试模拟缺 key。"""
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")

    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        env_file=env_file,
    )

    assert config.deepseek_api_key is None


def test_runtime_config_rejects_invalid_max_llm_attempts(tmp_path) -> None:
    """LLM attempt 预算必须是正整数。"""
    with pytest.raises(SolverRuntimeConfigError, match="llm-max-attempts"):
        SolverRuntimeConfig.from_sources(
            planner_mode="strategy",
            llm_provider="recorded",
            max_llm_attempts=0,
            env_file=tmp_path / ".env",
        )
