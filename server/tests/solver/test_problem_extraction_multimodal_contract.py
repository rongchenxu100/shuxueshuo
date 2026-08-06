from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DoubaoMultimodalExtractionProvider,
    MULTIMODAL_MAX_OUTPUT_TOKENS,
    MULTIMODAL_THINKING_MODE,
    MultimodalProviderError,
    build_multimodal_provider_request,
)
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL

from _problem_extraction_f3_support import (
    make_f3_fixture,
    valid_candidate_json,
)


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeFactory:
    def __init__(self, outcomes):
        self.completions = FakeCompletions(outcomes)

    def __call__(self, **kwargs):
        self.client_kwargs = kwargs
        return SimpleNamespace(chat=SimpleNamespace(completions=self.completions))


def response(text: str):
    return SimpleNamespace(
        model=DEFAULT_DOUBAO_MODEL,
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=text),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        ),
    )


def provider(factory: FakeFactory, *, sleeper=lambda _: None):
    return DoubaoMultimodalExtractionProvider(
        api_key="test-key",
        base_url="https://example.invalid/api/v3",
        model=DEFAULT_DOUBAO_MODEL,
        client_factory=factory,
        sleeper=sleeper,
    )


def test_multimodal_request_is_full_image_json_and_thinking_disabled(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    factory = FakeFactory([response(valid_candidate_json(pack))])
    client = provider(factory)
    request = build_multimodal_provider_request(pack, artifact_reader=store)

    result = client.complete(request)

    sent = factory.completions.requests[0]
    content = sent["messages"][1]["content"]
    images = [item for item in content if item["type"] == "image_url"]
    assert result.text == valid_candidate_json(pack)
    assert factory.client_kwargs["max_retries"] == 0
    assert len(images) == 1
    assert images[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["extra_body"] == {"thinking": {"type": MULTIMODAL_THINKING_MODE}}
    assert sent["temperature"] == 0
    assert sent["stream"] is False
    assert sent["max_tokens"] == MULTIMODAL_MAX_OUTPUT_TOKENS
    assert "tools" not in sent
    assert "base64" not in str(request.redacted_payload())
    assert "逐小问" in request.prompt.system
    assert "不求解题目" in request.prompt.system


@dataclass
class FakeHTTPError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def test_rate_limit_retries_once_and_records_subattempts(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    factory = FakeFactory(
        [
            FakeHTTPError(429, "rate limit"),
            response(valid_candidate_json(pack)),
        ]
    )
    client = provider(factory)

    result = client.complete(
        build_multimodal_provider_request(pack, artifact_reader=store)
    )

    assert len(factory.completions.requests) == 2
    assert [item.status for item in result.provider_attempts] == ["error", "completed"]
    assert result.provider_attempts[0].error_code == "extraction.multimodal_provider_rate_limited"


def test_empty_response_does_not_trigger_hidden_reprompt(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    factory = FakeFactory([response("")])
    client = provider(factory)

    with pytest.raises(MultimodalProviderError) as error:
        client.complete(
            build_multimodal_provider_request(pack, artifact_reader=store)
        )

    assert error.value.code == "extraction.multimodal_provider_empty_response"
    assert len(factory.completions.requests) == 1


def test_contract_unsupported_does_not_fallback(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    factory = FakeFactory([FakeHTTPError(400, "response_format unsupported")])
    client = provider(factory)

    with pytest.raises(MultimodalProviderError) as error:
        client.complete(
            build_multimodal_provider_request(pack, artifact_reader=store)
        )

    assert error.value.code == "extraction.multimodal_provider_contract_unsupported"
    assert len(factory.completions.requests) == 1


def test_wrong_model_is_rejected_before_client_construction() -> None:
    factory = FakeFactory([])

    with pytest.raises(MultimodalProviderError) as error:
        DoubaoMultimodalExtractionProvider(
            api_key="test-key",
            base_url="https://example.invalid/api/v3",
            model="some-other-model",
            client_factory=factory,
        )

    assert error.value.code == "extraction.multimodal_provider_config_invalid"
    assert not hasattr(factory, "client_kwargs")
