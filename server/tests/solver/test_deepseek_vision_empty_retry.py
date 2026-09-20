"""An empty reasoning-only attempt retries the original visual request."""

from test_deepseek_vision import client_factory, request_fixture, response

from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider,
)


def test_reasoning_limit_then_visible_json_preserves_request_and_both_attempts(
    tmp_path,
):
    _, request = request_fixture(tmp_path)
    calls, init = [], {}
    provider = DeepSeekMultimodalExtractionProvider(
        api_key="test",
        base_url="https://api.deepseek.com",
        client_factory=client_factory(
            [response("", "length"), response('{"value":7}')], calls, init
        ),
        sleeper=lambda _: None,
    )
    result = provider.complete(request)
    assert result.text == '{"value":7}'
    assert len(calls) == 2 and calls[0] == calls[1]
    assert init["max_retries"] == 0
    assert calls[0]["extra_body"]["thinking"] == {"type": "enabled"}
    assert calls[0]["reasoning_effort"] == "low"
    assert [a.finish_reason for a in result.provider_attempts] == ["length", "stop"]
    assert [a.visible_content for a in result.provider_attempts] == [False, True]
    assert len(provider.last_provider_attempts) == 2
    assert result.usage is None  # Unprovided token usage must not become zero.
