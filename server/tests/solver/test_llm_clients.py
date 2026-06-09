from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    DoubaoPlannerClient,
)


class _FakeOpenAIClient:
    """记录 Chat Completions 调用参数的假 OpenAI client。"""

    def __init__(self) -> None:
        self.create_kwargs: dict[str, Any] | None = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: Any) -> Any:
        self.create_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"steps": []}')
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=2,
                total_tokens=12,
            ),
            model="provider-model-version",
        )


def test_deepseek_client_uses_openai_compatible_arguments() -> None:
    """DeepSeek provider 应通过 base_url/model/api_key 调用 OpenAI SDK。"""
    factory_calls: list[dict[str, Any]] = []
    fake_client = _FakeOpenAIClient()

    def factory(**kwargs: Any) -> _FakeOpenAIClient:
        factory_calls.append(kwargs)
        return fake_client

    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=factory,
    )

    output = client.complete({"family_id": "QuadraticPathMinimumSolver"})

    assert output == '{"steps": []}'
    assert factory_calls == [
        {
            "api_key": "test-key",
            "base_url": "https://api.deepseek.com",
            "timeout": 120.0,
        }
    ]
    assert fake_client.create_kwargs is not None
    assert fake_client.create_kwargs["model"] == "deepseek-v4-flash"
    assert fake_client.create_kwargs["temperature"] == 0.0
    assert fake_client.create_kwargs["timeout"] == 120.0
    assert fake_client.create_kwargs["messages"][0]["role"] == "system"
    assert "QuadraticPathMinimumSolver" in fake_client.create_kwargs["messages"][1]["content"]
    assert client.last_usage == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
    }
    assert client.last_response_model == "provider-model-version"


def test_doubao_client_uses_single_model_configuration() -> None:
    """豆包 provider 首版只接收一个 DOUBAO_MODEL，不区分文本/多模态模型。"""
    fake_client = _FakeOpenAIClient()

    client = DoubaoPlannerClient(
        api_key="doubao-key",
        base_url="https://ark.example/v3",
        model="doubao-model",
        client_factory=lambda **_: fake_client,
    )

    client.complete({"family_id": "QuadraticWeightedPathMinimumSolver"})

    assert fake_client.create_kwargs is not None
    assert fake_client.create_kwargs["model"] == "doubao-model"


def test_openai_compatible_client_uses_rendered_messages_when_present() -> None:
    """Phase C 受控 planner 可把 Jinja 渲染后的 messages 交给 provider。"""
    fake_client = _FakeOpenAIClient()
    messages = [
        {"role": "system", "content": "system prompt from jinja"},
        {"role": "user", "content": "user prompt from jinja"},
    ]
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    client.complete({"messages": messages, "family_id": "QuadraticPathMinimumSolver"})

    assert fake_client.create_kwargs is not None
    assert fake_client.create_kwargs["messages"] == messages


def test_openai_compatible_client_wraps_legacy_payload_without_messages() -> None:
    """legacy planner 未传 messages 时，provider 仍会包装成 system/user prompt。"""
    fake_client = _FakeOpenAIClient()
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    client.complete({"family_id": "QuadraticPathMinimumSolver", "steps": []})

    assert fake_client.create_kwargs is not None
    messages = fake_client.create_kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "QuadraticPathMinimumSolver" in messages[1]["content"]
