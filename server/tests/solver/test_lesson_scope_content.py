from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
    ScopeLessonAuthoringService,
    ScopeLessonConfigurationError,
    evaluate_scope_lesson_content,
)
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import (
    load_teaching_rubric,
)


ROOT = Path(__file__).resolve().parents[3]
B0 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b0"
)
B1 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b1"
)
B2 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b2"
)


@pytest.fixture(scope="module")
def snapshot():
    return explanation_snapshot_from_payload(
        json.loads((B1 / "snapshot.json").read_text(encoding="utf-8"))
    )


@pytest.fixture(scope="module")
def projection(snapshot):
    return AnnotatedTeachingPlanProjector().project(snapshot)


@pytest.fixture()
def validator(projection):
    return LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )


def _merge_steps(first: dict, second: dict) -> dict:
    return {
        "source_steps": [*first["source_steps"], *second["source_steps"]],
        "title": first["title"] + "并" + second["title"],
        "nav_title": "合并讲解",
        "goal": first["goal"] + second["goal"],
        "derive": [*first["derive"], *second["derive"]],
    }


def test_deterministic_content_is_a_complete_valid_scope_response(validator) -> None:
    content = validator.deterministic_fallback
    result = validator.validate_payload(content)

    assert result.direct_acceptance is True
    assert result.contract_pass is True
    assert result.authority_pass is True
    assert result.diagnostics == ()
    assert set(result.scope_sources) == {"i", "i_1", "i_2", "ii"}
    assert sum(len(items) for items in result.bound_steps.values()) == 13
    macro = result.bound_steps["goal:ii.E"]
    assert [item.source_step_ids for item in macro[1:3]] == [
        ("derive_path_minimum_ii",),
        ("derive_path_minimum_ii",),
    ]


def test_adjacent_materials_can_merge_without_authored_provenance(validator) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    steps = payload["i"]["steps"]
    payload["i"]["steps"] = [_merge_steps(*steps)]

    result = validator.validate_payload(payload)

    assert result.direct_acceptance is True
    bound = result.bound_steps["scope:i"]
    assert len(bound) == 1
    assert bound[0].material_positions == (0, 1)
    assert bound[0].source_step_ids == (
        "derive_parabola_i",
        "derive_x_intercept_A_i",
    )


@pytest.mark.parametrize("missing_index", [0, 1])
def test_one_omitted_material_is_completed_at_its_canonical_position(
    validator,
    missing_index,
) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    expected = validator.validate_payload(
        copy.deepcopy(validator.deterministic_fallback)
    ).accepted_content
    remaining_index = 1 - missing_index
    remaining = payload["i"]["steps"][remaining_index]
    remaining["title"] = "保留模型撰写的教学标题"
    payload["i"]["steps"] = [remaining]

    result = validator.validate_payload(payload)

    assert result.direct_acceptance is True
    assert result.fallback_used is False
    assert result.scope_sources["i"] == "llm"
    assert result.source_step_completion_repaired is True
    assert result.to_payload()["source_step_completion_repaired"] is True
    repaired = result.accepted_content["i"]["steps"]
    assert len(repaired) == 2
    assert repaired[missing_index] == expected["i"]["steps"][missing_index]
    assert repaired[remaining_index]["title"] == "保留模型撰写的教学标题"
    assert [
        step.material_positions for step in result.bound_steps["scope:i"]
    ] == [(0,), (1,)]
    diagnostic = next(
        item
        for item in result.diagnostics
        if item.code == "lesson_scope_single_source_step_completed"
    )
    assert diagnostic.severity == "warning"
    assert f"s{missing_index + 1}" in diagnostic.message


def test_one_middle_omission_preserves_all_other_llm_steps(validator) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    expected = validator.validate_payload(
        copy.deepcopy(validator.deterministic_fallback)
    ).accepted_content
    raw_steps = payload["ii"]["goals"]["ii.E"]
    del raw_steps[2]
    raw_steps[1]["title"] = "模型保留的前一步"
    raw_steps[2]["title"] = "模型保留的后一步"

    result = validator.validate_payload(payload)

    repaired = result.accepted_content["ii"]["goals"]["ii.E"]
    assert result.scope_sources["ii"] == "llm"
    assert result.source_step_completion_repaired is True
    assert len(repaired) == 7
    assert repaired[1]["title"] == "模型保留的前一步"
    assert repaired[2] == expected["ii"]["goals"]["ii.E"][2]
    assert repaired[3]["title"] == "模型保留的后一步"
    assert [
        step.material_positions for step in result.bound_steps["goal:ii.E"]
    ] == [(0,), (1,), (2,), (3,), (4,), (5,), (6,)]


def test_narrow_completion_does_not_cover_empty_or_multiply_incomplete_body(
    validator,
) -> None:
    empty_single = copy.deepcopy(validator.deterministic_fallback)
    empty_single["i_1"]["goals"]["i_1.P"] = []
    result = validator.validate_payload(empty_single)
    assert result.scope_sources["i_1"] == "deterministic_fallback"
    assert result.source_step_completion_repaired is False

    two_missing = copy.deepcopy(validator.deterministic_fallback)
    two_missing["ii"]["goals"]["ii.E"] = two_missing["ii"]["goals"][
        "ii.E"
    ][2:]
    result = validator.validate_payload(two_missing)
    assert result.scope_sources["ii"] == "deterministic_fallback"
    assert result.source_step_completion_repaired is False
    assert any(
        item.code == "lesson_scope_source_steps_coverage_incomplete"
        for item in result.diagnostics
    )


def test_single_gap_with_invalid_authored_step_still_falls_back_scope(
    validator,
) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    payload["i"]["steps"] = payload["i"]["steps"][:1]
    payload["i"]["steps"][0]["goal"] = "读取 checkpoint"

    result = validator.validate_payload(payload)

    assert result.scope_sources["i"] == "deterministic_fallback"
    assert result.source_step_completion_repaired is False
    assert any(
        item.code == "lesson_scope_private_identity_leak"
        for item in result.diagnostics
    )


@pytest.mark.parametrize(
    "bad_refs",
    [[], ["s1", "s1"], ["s0"], ["s99"]],
)
def test_bad_source_step_refs_fall_back_only_their_scope(
    validator,
    bad_refs,
) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    payload["ii"]["goals"]["ii.E"][0]["source_steps"] = bad_refs

    result = validator.validate_payload(payload)

    assert result.whole_fallback is False
    assert result.scope_sources["ii"] == "deterministic_fallback"
    assert all(
        result.scope_sources[key] == "llm" for key in ("i", "i_1", "i_2")
    )
    assert result.direct_acceptance is False


def test_invalid_json_uses_one_atomic_whole_fallback(validator) -> None:
    result = validator.validate_raw("```json\n{}\n```")

    assert result.whole_fallback is True
    assert set(result.scope_sources.values()) == {"deterministic_fallback"}
    assert result.parsed_response is None
    assert result.diagnostics[0].code == "lesson_scope_json_invalid"


def test_eof_only_missing_closers_are_repaired_then_fully_validated(validator) -> None:
    raw = json.dumps(
        validator.deterministic_fallback,
        ensure_ascii=False,
        separators=(",", ":"),
    )[:-2]

    result = validator.validate_raw(raw)

    assert result.direct_acceptance is True
    assert result.syntax_repaired is True
    assert result.appended_suffix == "}}"
    assert result.repaired_response == raw + "}}"
    assert result.contract_pass is True
    assert result.authority_pass is True
    assert result.diagnostics[0].code == "lesson_scope_json_closers_repaired"
    assert result.diagnostics[0].severity == "warning"


@pytest.mark.parametrize(
    "raw",
    [
        '{"i":{"steps":[{"source_steps":["s1"],',
        '{"i":{"steps":[}',
        '{"i":{"steps":["unterminated',
        '{"i":{}} trailing',
    ],
)
def test_non_closer_json_errors_are_never_repaired(validator, raw) -> None:
    result = validator.validate_raw(raw)

    assert result.whole_fallback is True
    assert result.syntax_repaired is False
    assert result.diagnostics[0].code == "lesson_scope_json_invalid"


def test_missing_scope_is_local_but_unknown_scope_is_root_failure(validator) -> None:
    missing = copy.deepcopy(validator.deterministic_fallback)
    del missing["i_2"]
    result = validator.validate_payload(missing)
    assert result.whole_fallback is False
    assert result.scope_sources["i_2"] == "deterministic_fallback"

    unknown = copy.deepcopy(validator.deterministic_fallback)
    unknown["invented"] = {"steps": []}
    result = validator.validate_payload(unknown)
    assert result.whole_fallback is True
    assert result.diagnostics[0].code == "lesson_scope_unknown_scope"


@pytest.mark.parametrize("removed_field", ["box", "visuals"])
def test_removed_output_fields_are_rejected(validator, removed_field) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    step = payload["i"]["steps"][0]
    step[removed_field] = []

    result = validator.validate_payload(payload)

    assert result.scope_sources["i"] == "deterministic_fallback"
    assert result.direct_acceptance is False
    assert any(
        item.code == "lesson_scope_step_fields_invalid"
        for item in result.diagnostics
    )


def test_private_or_unknown_object_text_falls_back_scope(validator) -> None:
    private = copy.deepcopy(validator.deterministic_fallback)
    private["i"]["steps"][0]["goal"] = (
        "读取 checkpoint 和 point:problem:A"
    )
    result = validator.validate_payload(private)
    assert result.scope_sources["i"] == "deterministic_fallback"
    assert any(item.code == "lesson_scope_private_identity_leak" for item in result.diagnostics)

    unknown = copy.deepcopy(validator.deterministic_fallback)
    unknown["i"]["steps"][0]["title"] = "构造新点Z"
    result = validator.validate_payload(unknown)
    assert result.scope_sources["i"] == "deterministic_fallback"
    assert any(item.code == "lesson_scope_unexpected_object" for item in result.diagnostics)


def test_future_result_is_an_authority_failure(validator) -> None:
    future = copy.deepcopy(validator.deterministic_fallback)
    accepted = validator.validate_payload(future).accepted_content
    later_conclusion = accepted["ii"]["goals"]["ii.E"][-1]["box"][0]
    ii_steps = future["ii"]["goals"]["ii.E"]
    ii_steps[0]["derive"].append(f"∴ {later_conclusion}")
    result = validator.validate_payload(future)
    assert result.scope_sources["ii"] == "deterministic_fallback"
    assert any(item.code == "lesson_scope_future_result_leak" for item in result.diagnostics)


def test_child_scope_result_cannot_leak_into_parent_scope(validator) -> None:
    payload = copy.deepcopy(validator.deterministic_fallback)
    payload["i"]["steps"][0]["derive"].append("∴ P(－1,4)")

    result = validator.validate_payload(payload)

    assert result.scope_sources["i"] == "deterministic_fallback"
    assert any(
        item.code == "lesson_scope_cross_container_result_leak"
        for item in result.diagnostics
    )


def test_code_owned_box_covers_child_goal_answer_at_ancestor_producer(validator) -> None:
    result = validator.validate_payload(validator.deterministic_fallback)
    producer = next(
        step
        for step in result.accepted_content["i"]["steps"]
        if any("A(－3,0)" in box or "A(-3,0)" in box for box in step["box"])
    )
    assert producer["box"]
    assert result.authority_pass is True


def test_scope_evaluator_reuses_hidden_b0_rubric(validator) -> None:
    result = validator.validate_payload(validator.deterministic_fallback)
    evaluation = evaluate_scope_lesson_content(
        result,
        problem_id="tj-2026-heping-ermo-25",
        rubric=load_teaching_rubric(B0 / "rubric.json"),
    )

    assert evaluation["contract"]["pass"] is True
    assert evaluation["authority"]["pass"] is True
    assert evaluation["teaching_quality"]["coverage_rate"] == 1.0
    assert evaluation["teaching_quality"]["required_points"]["missing"] == []


class _ResponseClient:
    provider_name = "fake"
    model = "fake-model"
    last_response_model = "fake-response-model"
    last_provider_attempts = ()

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.last_usage = None

    def complete(self, payload):
        self.calls.append(copy.deepcopy(payload))
        current = self.responses.pop(0)
        if isinstance(current, Exception):
            self.last_usage = {}
            raise current
        self.last_usage = {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }
        return current


def _valid_response(projection) -> str:
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    return json.dumps(validator.deterministic_fallback, ensure_ascii=False)


def test_service_uses_one_semantic_attempt_and_reviewed_prompt(snapshot, projection) -> None:
    reviewed_hash = json.loads(
        (B2 / "projection-audit.json").read_text(encoding="utf-8")
    )["hashes"]["prompt"]
    client = _ResponseClient([_valid_response(projection)])
    service = ScopeLessonAuthoringService(
        client=client,
        reviewed_prompt_hash=reviewed_hash,
        sleep_fn=lambda _: None,
    )

    result = service.generate(snapshot)

    assert result.semantic_attempt_count == 1
    assert len(result.transport_attempts) == 1
    assert result.validation.direct_acceptance is True
    assert result.usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }
    assert client.calls[0]["planner_attempt"] == 1
    assert client.calls[0]["thinking_effort"] == "disabled"
    assert client.calls[0]["reasoning_only_empty_response_retry"] is False


def test_service_can_request_low_thinking_without_changing_semantic_attempt(
    snapshot,
    projection,
) -> None:
    client = _ResponseClient([_valid_response(projection)])
    result = ScopeLessonAuthoringService(
        client=client,
        thinking_effort="low",
        sleep_fn=lambda _: None,
    ).generate(snapshot)

    assert result.semantic_attempt_count == 1
    assert client.calls[0]["planner_attempt"] == 1
    assert client.calls[0]["thinking_effort"] == "low"


def test_transport_retry_reuses_exact_messages(snapshot, projection) -> None:
    client = _ResponseClient([TimeoutError("temporary"), _valid_response(projection)])
    service = ScopeLessonAuthoringService(
        client=client,
        sleep_fn=lambda _: None,
    )

    result = service.generate(snapshot)

    assert len(client.calls) == 2
    assert client.calls[0] == client.calls[1]
    assert result.validation.direct_acceptance is True
    assert result.semantic_attempt_count == 1
    assert len(result.transport_attempts) == 2


def test_invalid_response_never_semantically_retries(snapshot) -> None:
    client = _ResponseClient(["not-json", "must-not-be-used"])
    result = ScopeLessonAuthoringService(
        client=client,
        sleep_fn=lambda _: None,
    ).generate(snapshot)

    assert len(client.calls) == 1
    assert result.validation.whole_fallback is True
    assert result.validation.direct_acceptance is False


def test_reviewed_prompt_drift_fails_before_provider_call(snapshot) -> None:
    client = _ResponseClient([])
    with pytest.raises(
        ScopeLessonConfigurationError,
        match="reviewed_prompt_drift",
    ):
        ScopeLessonAuthoringService(
            client=client,
            reviewed_prompt_hash="wrong",
        ).generate(snapshot)
    assert client.calls == []
