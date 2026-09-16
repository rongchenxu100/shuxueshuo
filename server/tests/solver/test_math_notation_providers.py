"""Explicit provider switch preserves images, contract and bounded call audit."""

import json

import pytest
from test_deepseek_vision import client_factory, response

from shuxueshuo_server.problem_understanding.batch_smoke import prepare_fixture
from shuxueshuo_server.problem_understanding.comparison_provider import (
    DoubaoComparisonProvider,
)
from shuxueshuo_server.problem_understanding.smoke import build_request, run
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider,
)
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL


@pytest.mark.parametrize("empty_first", [False, True])
def test_doubao_same_visual_request_and_audited_gate(tmp_path, empty_first):
    fixture = prepare_fixture("function-quantifiers", tmp_path)
    calls, init = [], {}
    outputs = [response("", "length")] if empty_first else []
    outputs.append(response((fixture / "gold.json").read_text()))
    for item in outputs:
        item.model = DEFAULT_DOUBAO_MODEL
    provider = DoubaoComparisonProvider(
        api_key="test",
        base_url="https://example.invalid",
        request_timeout=300,
        client_factory=client_factory(outputs, calls, init),
        sleeper=lambda _: None,
    )
    result = run(fixture, tmp_path / "run", provider, [])
    assert result["passed"] and len(calls) == (2 if empty_first else 1)
    request = build_request(fixture, ExtractionArtifactStore(tmp_path / "source"), [])
    deepseek = DeepSeekMultimodalExtractionProvider(
        api_key="test",
        base_url="https://example.invalid",
        client_factory=client_factory([], [], {}),
    )
    a, b = provider.prepare_request(request), deepseek.prepare_request(request)
    assert a.provider_messages() == b.provider_messages()
    for call in calls:
        assert call["model"] == DEFAULT_DOUBAO_MODEL
        assert call["extra_body"] == {"thinking": {"type": "enabled"}}
        assert call["reasoning_effort"] == "low" and not call["stream"]
        assert call["response_format"] == {"type": "json_object"}
        assert call["timeout"] == 300 and call["max_tokens"] == 16384
    assert init["max_retries"] == 0
    audit = json.loads((tmp_path / "run/call.json").read_text())
    assert (
        audit["provider"] == "doubao"
        and audit["response_model"] == DEFAULT_DOUBAO_MODEL
    )
    assert len(audit["provider_attempts"]) == len(calls)
