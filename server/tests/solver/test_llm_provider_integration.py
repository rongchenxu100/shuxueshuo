"""真实 LLM provider 集成测试。

这些测试会实际调用 DeepSeek / 豆包 Ark API，因此默认跳过。需要本地
``server/.env`` 已配置 key，并显式设置 ``RUN_LLM_INTEGRATION=1`` 后才会运行：

    cd server && RUN_LLM_INTEGRATION=1 uv run pytest tests/solver/test_llm_provider_integration.py -q
"""

from __future__ import annotations

import json
import os

import pytest

from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


RUN_LLM_INTEGRATION = os.getenv("RUN_LLM_INTEGRATION") == "1"


def _provider_config(provider: str) -> SolverRuntimeConfig:
    """读取 server/.env 中对应 provider 的真实配置。"""
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider=provider,
    )
    if provider == "deepseek" and not config.deepseek_api_key:
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    if provider == "doubao" and not config.doubao_api_key:
        pytest.skip("DOUBAO_API_KEY is not configured")
    return config


def _configured_model(config: SolverRuntimeConfig, provider: str) -> str:
    """返回当前 provider 实际发送请求时使用的模型名。"""
    if config.llm_model:
        return config.llm_model
    if provider == "deepseek":
        return config.deepseek_model
    return config.doubao_model


def _smoke_payload(provider: str, model: str) -> dict[str, object]:
    """构造极小 payload，降低 token 消耗并要求模型返回 JSON。"""
    return {
        "task": "llm_provider_smoke_test",
        "instruction": (
            "Return exactly one JSON object and nothing else. "
            f'The object must be {{"ok": true, "provider": "{provider}", '
            f'"model": "{model}"}}.'
        ),
        "output_schema": {
            "type": "object",
            "required": ["ok", "provider", "model"],
            "properties": {
                "ok": {"type": "boolean"},
                "provider": {"type": "string"},
                "model": {"type": "string"},
            },
        },
    }


def _parse_provider_response(raw: str) -> dict[str, object]:
    """解析 provider 返回的 JSON；失败时让测试暴露真实响应片段。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    return json.loads(text)


@pytest.mark.skipif(
    not RUN_LLM_INTEGRATION,
    reason="set RUN_LLM_INTEGRATION=1 to call real LLM providers",
)
@pytest.mark.parametrize("provider", ["deepseek", "doubao"])
def test_real_llm_provider_complete_smoke(provider: str) -> None:
    """真实 provider 应能完成一次 Chat Completions 调用并返回 JSON。"""
    config = _provider_config(provider)
    model = _configured_model(config, provider)
    client = config.build_llm_client()

    raw = client.complete(_smoke_payload(provider, model))
    parsed = _parse_provider_response(raw)

    print(
        "\n"
        f"provider={provider}\n"
        f"configured_model={model}\n"
        f"response_model={getattr(client, 'last_response_model', None)}\n"
        f"usage={json.dumps(getattr(client, 'last_usage', None), ensure_ascii=False, sort_keys=True)}\n"
        f"llm_output={json.dumps(parsed, ensure_ascii=False, sort_keys=True)}"
    )
    assert parsed["ok"] is True
    assert str(parsed["provider"]).lower() == provider
    assert parsed["model"] == model
    assert getattr(client, "last_usage", None) is None or isinstance(
        client.last_usage,
        dict,
    )
