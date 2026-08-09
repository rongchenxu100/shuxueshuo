from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DoubaoMultimodalExtractionProvider,
    build_multimodal_provider_request,
    problem_domain_family_catalog,
)
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    _uses_patch_after_first_draft,
)

from _problem_extraction_f3_support import make_f3_fixture
from test_problem_domain_retry import _domain_payload
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL


def test_pass1_uses_strict_domain_schema_and_no_runtime_authoring_vocabulary(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)

    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="synthetic-f2",
    )

    assert request.contract_version == "problem-domain/v1"
    assert request.response_format["type"] == "json_schema"
    schema = request.response_format["json_schema"]["schema"]
    assert schema["properties"]["schema_version"]["const"] == "problem-domain/v1"
    assert schema["properties"]["root"]["$ref"] == "#/$defs/scope_level_0"
    assert "scope" not in schema["$defs"]
    assert {
        name for name in schema["$defs"] if name.startswith("scope_level_")
    } == {"scope_level_0", "scope_level_1", "scope_level_2", "scope_level_3"}
    assert schema["$defs"]["scope_level_3"]["properties"]["children"][
        "maxItems"
    ] == 0
    for level in range(4):
        properties = schema["$defs"][f"scope_level_{level}"]["properties"]
        assert properties["source_text"]["maxItems"] == 12
        assert properties["source_text"]["items"]["maxLength"] == 2_048
        assert properties["entities"]["maxItems"] == 32
        assert properties["facts"]["maxItems"] == 48
        assert properties["goals"]["maxItems"] == 12
        assert properties["children"]["maxItems"] == (0 if level == 3 else 8)
    assert schema["$defs"]["expression"]["maxLength"] == 1_024
    assert '"$ref":"#/$defs/scope"' not in json.dumps(
        schema, ensure_ascii=False, separators=(",", ":")
    )
    assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))) <= 20_000
    assert request.thinking_mode == "disabled"
    assert request.reasoning_effort is None
    assert request.redacted_payload()["max_tokens"] == 4_096
    assert request.redacted_payload()["stream"] is True
    assert request.redacted_payload()["stream_options"] == {"include_usage": True}
    assert '"schema_version":"problem-domain/v1"' in request.prompt.system
    prompt = request.prompt.user_debug
    assert "仅当题面文字、Fact 或 Goal 实际引用坐标原点 O" in prompt
    assert "不得仅因出现坐标系或抛物线而补 O" in prompt
    assert "关闭顶层 root 对象后立即结束输出" in request.prompt.system
    assert "父 scope 已有相同 kind+label" in prompt
    assert "不同的取值或约束只写在本 scope 的 Fact" in prompt
    assert "不跨 sibling 合并" in prompt
    for retired in (
        "runtime_preflights",
        "canonical handle",
        "valid_scope",
        "target_path",
        "full-replacement",
    ):
        assert retired not in prompt


def test_family_catalog_contains_only_source_selection_contract() -> None:
    catalog = problem_domain_family_catalog()

    assert len(catalog) == 4
    assert all(
        set(item)
        == {
            "family_id",
            "title",
            "use_when",
            "required_source_primitives",
            "conditional_source_requirements",
            "do_not_use_when",
        }
        for item in catalog
    )
    assert all(item["required_source_primitives"] for item in catalog)
    assert all(item["do_not_use_when"] for item in catalog)
    square = next(
        item
        for item in catalog
        if item["family_id"] == "QuadraticSquareReflectionPathMinimumSolver"
    )
    assert square["conditional_source_requirements"] == [
        {
            "when_fact_types": ["minimum_value_given"],
            "require_visible_fact_types": [
                "minimum_target",
                "square",
                "midpoint",
                "square_center",
            ],
            "description": (
                "路径目标须以正方形、中点、中心事实通过三段降维；moving_point"
                " 由事实验证。"
            ),
        }
    ]
    assert "PointList" not in json.dumps(catalog, ensure_ascii=False)


class _RecordedStream:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.pulls = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.pulls += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


class _StreamingClient:
    def __init__(self, stream: _RecordedStream) -> None:
        self.stream = stream
        self.create_kwargs: dict[str, Any] | None = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: Any) -> _RecordedStream:
        self.create_kwargs = kwargs
        return self.stream


def _chunk(content: str, *, finish_reason: str | None = None) -> Any:
    return SimpleNamespace(
        model=DEFAULT_DOUBAO_MODEL,
        usage=None,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
    )


def test_doubao_stream_stops_at_first_complete_json_object(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="synthetic-f2",
    )
    expected = '{"schema_version":"problem-domain/v1","root":{}}'
    stream = _RecordedStream(
        [
            _chunk(expected[:24]),
            _chunk(expected[24:] + " trailing explanation"),
            _chunk("this chunk must never be consumed", finish_reason="length"),
        ]
    )
    client = _StreamingClient(stream)
    provider = DoubaoMultimodalExtractionProvider(
        api_key="test-key",
        base_url="https://ark.example/v3",
        model=DEFAULT_DOUBAO_MODEL,
        client_factory=lambda **_: client,
    )

    response = provider.complete(request)

    assert response.text == expected
    assert response.finish_reason == "json_complete"
    assert response.raw_payload["stream_terminated_at_json"] is True
    assert response.raw_payload["discarded_trailing_characters"] > 0
    metadata = response.metadata_payload()
    assert metadata["stream_terminated_at_json"] is True
    assert metadata["usage_complete"] is False
    assert metadata["received_output_characters"] == len(expected)
    assert stream.pulls == 2
    assert stream.closed is True
    assert client.create_kwargs is not None
    assert client.create_kwargs["stream"] is True
    assert client.create_kwargs["stream_options"] == {"include_usage": True}
    assert client.create_kwargs["max_tokens"] == 4_096


def test_retry_uses_patch_schema_low_thinking_and_projects_frozen_units(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    payload = _domain_payload()
    payload["family_id"] = "QuadraticWeightedPathMinimumSolver"
    validated = ProblemDomainValidator().validate(ProblemDraft.create(payload)).draft

    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="synthetic-f2",
        current_draft=validated,
        validation_issues=validated.validation_report.issues,
        semantic_attempt_number=2,
    )

    assert request.contract_version == "problem-repair/v1"
    assert request.response_format["json_schema"]["schema"]["properties"][
        "schema_version"
    ]["const"] == "problem-repair/v1"
    repair_schema = request.response_format["json_schema"]["schema"]
    assert "scope" not in repair_schema["$defs"]
    assert '"$ref":"#/$defs/scope"' not in json.dumps(
        repair_schema, ensure_ascii=False, separators=(",", ":")
    )
    assert request.thinking_mode == "enabled"
    assert request.reasoning_effort == "low"
    assert '"schema_version":"problem-repair/v1"' in request.prompt.system
    assert validated.revision_id in request.prompt.user_debug
    assert '"unit_id":"family"' in request.prompt.user_debug
    assert "frozen_unit_ids" in request.prompt.user_debug
    assert "repairable_unit_ids" in request.prompt.user_debug
    assert all(image.role == "primary" for image in request.images)


def test_full_domain_schema_retry_keeps_thinking_disabled_until_a_draft_exists(
    tmp_path,
) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)

    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="synthetic-f2",
        semantic_attempt_number=2,
    )

    assert request.contract_version == "problem-domain/v1"
    assert request.thinking_mode == "disabled"
    assert request.reasoning_effort is None


def test_deepseek_text_baseline_uses_json_object_and_embeds_finite_schema(
    tmp_path,
) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)

    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="synthetic-f2",
        include_images=False,
        response_format_mode="json_object",
    )

    assert request.images == ()
    assert request.response_format == {"type": "json_object"}
    assert request.contract_schema["properties"]["root"]["$ref"] == (
        "#/$defs/scope_level_0"
    )
    assert "[本次文本基线不发送图片]" in request.prompt.user_debug
    assert "完整 JSON Schema（必须逐字段遵守）" in request.prompt.user_debug
    messages = request.provider_messages()
    assert isinstance(messages[1]["content"], str)
    assert "image_url" not in str(messages)


def test_smoke_requires_patch_only_after_a_schema_valid_draft_exists() -> None:
    complete = lambda draft=None: SimpleNamespace(
        request=SimpleNamespace(contract_version="problem-domain/v1"),
        patch=None,
        resulting_draft=draft,
    )
    repair = lambda draft=None: SimpleNamespace(
        request=SimpleNamespace(contract_version="problem-repair/v1"),
        patch=object(),
        resulting_draft=draft,
    )
    draft = object()

    assert _uses_patch_after_first_draft((complete(), complete(draft), repair(draft)))
    assert not _uses_patch_after_first_draft((complete(draft), complete(draft)))
