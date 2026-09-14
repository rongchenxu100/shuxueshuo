from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    DoubaoPlannerClient,
    LLMClientConfigurationError,
    LLMProviderResponseError,
)
import pytest


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
    assert fake_client.create_kwargs["timeout"] == 120.0
    assert fake_client.create_kwargs["response_format"] == {
        "type": "json_object"
    }
    assert fake_client.create_kwargs["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert "reasoning_effort" not in fake_client.create_kwargs
    assert "temperature" not in fake_client.create_kwargs
    assert fake_client.create_kwargs["messages"][0]["role"] == "system"
    assert "QuadraticPathMinimumSolver" in fake_client.create_kwargs["messages"][1]["content"]
    assert client.last_usage == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
    }
    assert client.last_response_model == "provider-model-version"
    assert client.last_provider_attempts[0] == {
        "provider_attempt": 1,
        "response_model": "provider-model-version",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
        },
        "finish_reason": None,
        "visible_content": True,
        "reasoning_content_available": False,
        "reasoning_content_chars": 0,
        "response_format": "json_object",
        "thinking_mode": "disabled",
        "reasoning_effort": None,
    }


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
    assert "response_format" not in fake_client.create_kwargs
    assert "extra_body" not in fake_client.create_kwargs
    assert "reasoning_effort" not in fake_client.create_kwargs


@pytest.mark.parametrize("planner_attempt", [2, 3])
def test_deepseek_repair_passes_use_low_effort_thinking(
    planner_attempt: int,
) -> None:
    fake_client = _FakeOpenAIClient()
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    client.complete(
        {
            "planner_attempt": planner_attempt,
            "messages": [{"role": "user", "content": "return JSON"}],
        }
    )

    assert fake_client.create_kwargs is not None
    assert fake_client.create_kwargs["response_format"] == {
        "type": "json_object"
    }
    assert fake_client.create_kwargs["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert fake_client.create_kwargs["reasoning_effort"] == "low"
    assert "temperature" not in fake_client.create_kwargs


def test_deepseek_explicit_low_thinking_does_not_fake_a_repair_attempt() -> None:
    fake_client = _FakeOpenAIClient()
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    client.complete(
        {
            "planner_attempt": 1,
            "thinking_effort": "low",
            "messages": [{"role": "user", "content": "return JSON"}],
        }
    )

    assert fake_client.create_kwargs is not None
    assert fake_client.create_kwargs["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert fake_client.create_kwargs["reasoning_effort"] == "low"
    assert client.last_provider_attempts[0]["thinking_mode"] == "enabled"
    assert client.last_provider_attempts[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_client_default_low_thinking_preserves_messages_and_records_mode(attempt) -> None:
    fake = _FakeOpenAIClient()
    client = DeepSeekPlannerClient(
        api_key="test-key", base_url="https://example.test", model="deepseek-v4-flash",
        client_factory=lambda **_: fake, default_thinking_effort="low",
    )
    messages = [{"role": "user", "content": "return JSON"}]
    request = {"planner_attempt": attempt, "messages": messages}
    client.complete(request)
    assert fake.create_kwargs["messages"] == messages
    assert fake.create_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert fake.create_kwargs["reasoning_effort"] == "low"
    assert client.last_provider_attempts[0]["thinking_mode"] == "enabled"
    assert client.last_provider_attempts[0]["reasoning_effort"] == "low"
    assert request == {"planner_attempt": attempt, "messages": messages}

    client.complete({**request, "thinking_effort": "disabled"})
    assert fake.create_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in fake.create_kwargs


def test_deepseek_rejects_unknown_explicit_thinking_effort() -> None:
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: _FakeOpenAIClient(),
    )

    with pytest.raises(LLMClientConfigurationError, match="thinking_effort"):
        client.complete({"thinking_effort": "medium"})


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


class _SequentialOpenAIClient:
    def __init__(
        self,
        contents: list[str | None],
        *,
        reasonings: list[str | None] | None = None,
    ) -> None:
        self.contents = list(contents)
        self.reasonings = list(reasonings or [None] * len(contents))
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        content = self.contents.pop(0)
        reasoning_content = self.reasonings.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=content,
                        reasoning_content=reasoning_content,
                    ),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
            ),
            model="provider-model-version",
        )


def test_reasoning_only_empty_response_retries_inside_one_provider_call() -> None:
    fake_client = _SequentialOpenAIClient([None, '{"format":"functional_plan/v1"}'])
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    result = client.complete(
        {"messages": [{"role": "user", "content": "return JSON"}]}
    )

    assert result == '{"format":"functional_plan/v1"}'
    assert len(fake_client.requests) == 2
    assert "立即输出严格 JSON" in fake_client.requests[1]["messages"][-1]["content"]
    assert all(
        request["extra_body"] == {"thinking": {"type": "disabled"}}
        for request in fake_client.requests
    )
    assert all("reasoning_effort" not in request for request in fake_client.requests)
    assert all(
        request["response_format"] == {"type": "json_object"}
        for request in fake_client.requests
    )
    assert client.last_usage == {
        "prompt_tokens": 20,
        "completion_tokens": 40,
        "total_tokens": 60,
        "provider_request_count": 2,
    }
    assert [item["visible_content"] for item in client.last_provider_attempts] == [
        False,
        True,
    ]


def test_reasoning_content_is_captured_for_each_provider_attempt() -> None:
    fake_client = _SequentialOpenAIClient(
        [None, '{"format":"functional_plan/v1"}'],
        reasonings=["first internal reasoning", "second internal reasoning"],
    )
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    client.complete({"messages": [{"role": "user", "content": "return JSON"}]})

    assert client.last_provider_reasoning == (
        {
            "provider_attempt": 1,
            "reasoning_content": "first internal reasoning",
        },
        {
            "provider_attempt": 2,
            "reasoning_content": "second internal reasoning",
        },
    )
    assert [
        item["reasoning_content_available"]
        for item in client.last_provider_attempts
    ] == [True, True]
    assert [
        item["reasoning_content_chars"] for item in client.last_provider_attempts
    ] == [24, 25]


def test_two_reasoning_only_empty_responses_raise_typed_provider_error() -> None:
    fake_client = _SequentialOpenAIClient([None, ""])
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    with pytest.raises(
        LLMProviderResponseError,
        match="provider.reasoning_only_empty_response",
    ):
        client.complete(
            {"messages": [{"role": "user", "content": "return JSON"}]}
        )

    assert len(fake_client.requests) == 2


def test_scope_lesson_can_disable_reasoning_only_reprompt() -> None:
    fake_client = _SequentialOpenAIClient(
        [None, '{"schema_version":"lesson-scope-content/v1"}']
    )
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **_: fake_client,
    )

    with pytest.raises(
        LLMProviderResponseError,
        match="provider.reasoning_only_empty_response",
    ):
        client.complete(
            {
                "messages": [{"role": "user", "content": "return JSON"}],
                "reasoning_only_empty_response_retry": False,
            }
        )

    assert len(fake_client.requests) == 1


def test_scope_lesson_can_disable_hidden_sdk_retries() -> None:
    factory_calls: list[dict[str, Any]] = []
    fake_client = _FakeOpenAIClient()

    DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        client_factory=lambda **kwargs: (
            factory_calls.append(kwargs) or fake_client
        ),
        sdk_max_retries=0,
    )

    assert factory_calls[0]["max_retries"] == 0


def test_transport_failure_clears_previous_response_metadata():
    fake = _FakeOpenAIClient()
    client = DeepSeekPlannerClient(
        api_key="test-key",
        base_url="https://example.test",
        model="test-model",
        client_factory=lambda **kwargs: fake,
    )
    client.complete({'family_id': 'QuadraticPathMinimumSolver'})
    assert client.last_usage['total_tokens'] == 12

    def fail(**kwargs):
        raise ConnectionError('connection interrupted')

    fake.chat.completions.create = fail
    with pytest.raises(ConnectionError):
        client.complete({'family_id': 'QuadraticPathMinimumSolver'})
    assert client.last_usage is None
    assert client.last_response_model is None
    assert client.last_provider_attempts == ()
    assert client.last_provider_reasoning == ()


def test_provider_retry_records_actual_messages_without_credentials():
    from shuxueshuo_server.solver.runtime.llm_debug import contains_secret_or_data_url
    fake = _SequentialOpenAIClient([None, '{"ok":true}'])
    client = DeepSeekPlannerClient(api_key='secret-test-key', base_url='https://example.test',
                                  model='test-model', client_factory=lambda **_: fake)
    client.complete({'messages': [{'role': 'user', 'content': 'return JSON'}]})
    assert len(client.last_provider_requests) == 2
    assert client.last_provider_requests[0]['messages'] == fake.requests[0]['messages']
    assert client.last_provider_requests[1]['messages'] == fake.requests[1]['messages']
    assert len(client.last_provider_requests[1]['messages']) == len(client.last_provider_requests[0]['messages']) + 1
    assert [item['text'] for item in client.last_provider_responses] == ['', '{"ok":true}']
    assert not contains_secret_or_data_url(client.last_provider_requests)
    assert 'secret-test-key' not in str(client.last_provider_requests)


def test_transport_failure_after_reasoning_preserves_this_invocations_evidence():
    fake = _SequentialOpenAIClient([None], reasonings=['provider supplied partial reasoning'])
    client = DeepSeekPlannerClient(api_key='test-key', base_url='https://example.test',
                                  model='test-model', client_factory=lambda **_: fake)
    complete = fake.chat.completions.create
    def fail_second(**kwargs):
        if fake.requests:
            raise ConnectionError('second request disconnected')
        return complete(**kwargs)
    fake.chat.completions.create = fail_second
    with pytest.raises(ConnectionError):
        client.complete({'messages': [{'role': 'user', 'content': 'return JSON'}]})
    assert client.last_invocation_id == 1
    assert len(client.last_provider_requests) == 2
    assert len(client.last_provider_responses) == 1
    assert client.last_provider_reasoning[0]['reasoning_content'] == 'provider supplied partial reasoning'
    assert client.last_usage['total_tokens'] == 30
