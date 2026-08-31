from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from _functional_opt_in_support import (
    FUNCTIONAL_OPT_IN_CASES,
    _attempt_llm_usage_is_recorded,
    _assert_attempt_protocol,
    _assert_prompt_is_functional_and_safe,
    assert_answers_semantically_equal,
)


def test_functional_opt_in_registry_covers_five_existing_fixtures() -> None:
    assert tuple(FUNCTIONAL_OPT_IN_CASES) == (
        "nankai",
        "heping-ermo",
        "xiqing",
        "hexi",
        "heping",
    )
    for case in FUNCTIONAL_OPT_IN_CASES.values():
        assert case.problem_fixture_path.exists()
        assert case.functional_fixture_path.exists()
        assert case.expected_path.exists()
        assert (Path(__file__).resolve().parents[2] / case.test_path).exists()


def test_semantic_answer_comparison_accepts_equivalent_expressions() -> None:
    assert_answers_semantically_equal(
        {
            "i": {"curve": "2*(x - 1)**2 - 7"},
            "ii": {"point": ["2/2", "-6/3"]},
        },
        {
            "i": {"curve": "2*x**2 - 4*x - 5"},
            "ii": {"point": ["1", "-2"]},
        },
    )


def test_semantic_answer_comparison_rejects_key_or_value_drift() -> None:
    with pytest.raises(AssertionError, match="keys differ"):
        assert_answers_semantically_equal({"i": {"a": "1"}}, {"ii": {"a": "1"}})
    with pytest.raises(AssertionError, match="answers.i.a"):
        assert_answers_semantically_equal({"i": {"a": "2"}}, {"i": {"a": "1"}})


def test_attempt_protocol_requires_functional_format_and_locked_few_shot(
    tmp_path: Path,
) -> None:
    selection = {
        "example_id": "quadratic_constraints_vertex",
        "mode": "strict_test",
        "source_problem_id": "synthetic-quadratic-core-reference",
    }
    few_shot = [{"format": "functional-plan-content/v2", "root_scope": {}}]
    context = {
        "schema_version": "planner-problem-view/v2",
        "root_scope": {"id": "problem", "text": ["x"]},
    }
    (tmp_path / "attempt-1.llm-metadata.json").write_text(
        json.dumps(
            {
                "semantic_attempt": 1,
                "planner_protocol": "functional-plan-content/v2",
                "usage": {"total_tokens": 10},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "attempt-1.raw-response.txt").write_text(
        '{"schema_version":"functional-plan-content/v2"}',
        encoding="utf-8",
    )
    (tmp_path / "attempt-1.payload.functional_few_shot_selection.json").write_text(
        json.dumps(selection),
        encoding="utf-8",
    )
    (tmp_path / "attempt-1.payload.few_shot_examples.json").write_text(
        json.dumps(few_shot),
        encoding="utf-8",
    )
    (tmp_path / "attempt-1.payload.planner_protocol.json").write_text(
        json.dumps("functional-plan-content/v2"),
        encoding="utf-8",
    )
    (tmp_path / "attempt-1.payload.problem_planning_context.json").write_text(
        json.dumps(context),
        encoding="utf-8",
    )
    (tmp_path / "attempt-1.prompt.user.md").write_text(
        '{"schema_version":"functional-plan-content/v2"}',
        encoding="utf-8",
    )

    (tmp_path / "attempt-2.llm-metadata.json").write_text(
        json.dumps(
            {
                "semantic_attempt": 2,
                "planner_protocol": "functional-scope-repair/v1",
                "usage": {"total_tokens": 8},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.raw-response.txt").write_text(
        '{"schema_version":"functional-scope-repair/v1"}',
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.planner_protocol.json").write_text(
        json.dumps("functional-scope-repair/v1"),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.problem_planning_context.json").write_text(
        json.dumps(context),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.annotated_previous_plan.json").write_text(
        json.dumps({"schema_version": "functional-annotated-plan/v1"}),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.prompt.user.md").write_text(
        '{"schema_version":"functional-scope-repair/v1"}',
        encoding="utf-8",
    )

    _assert_attempt_protocol(tmp_path)
    assert _attempt_llm_usage_is_recorded(tmp_path)

    # A response that fails before a Canonical Plan exists remains Pass 1,
    # but must carry the prior invalid content instead of pretending to be a
    # Scope Repair attempt.
    (tmp_path / "attempt-2.llm-metadata.json").write_text(
        json.dumps(
            {
                "semantic_attempt": 2,
                "planner_protocol": "functional-plan-content/v2",
                "usage": {"total_tokens": 8},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.planner_protocol.json").write_text(
        json.dumps("functional-plan-content/v2"),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.functional_few_shot_selection.json").write_text(
        json.dumps(selection),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.few_shot_examples.json").write_text(
        json.dumps(few_shot),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.previous_invalid_content.json").write_text(
        json.dumps({"error": {"code": "functional.plan_content_schema_invalid"}}),
        encoding="utf-8",
    )
    (tmp_path / "attempt-2.payload.annotated_previous_plan.json").unlink()
    _assert_attempt_protocol(tmp_path)

    (tmp_path / "attempt-2.llm-metadata.json").write_text(
        json.dumps(
            {
                "semantic_attempt": 1,
                "planner_protocol": "functional-scope-repair/v1",
                "usage": {"total_tokens": 8},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        _assert_attempt_protocol(tmp_path)
    assert not _attempt_llm_usage_is_recorded(tmp_path)


def test_prompt_safety_distinguishes_error_codes_from_canonical_handles() -> None:
    payload = {
        "planner_protocol": "functional-plan-content/v2",
        "problem_planning_context": {
            "schema_version": "planner-problem-view/v2",
            "root_scope": {"id": "problem", "text": ["x"]},
        },
        "functional_few_shot_selection": {
            "mode": "strict_test",
            "example_id": "hidden_example",
            "source_problem_id": "hidden_problem",
        },
    }
    prompt = SimpleNamespace(
        user=(
            "duplicate_point_coordinate_fact: use an existing point; "
            "quadratic_y_axis_intercept_point: function.arg_missing"
        )
    )

    _assert_prompt_is_functional_and_safe(payload, prompt)

    with pytest.raises(AssertionError, match="source_problem_id"):
        _assert_prompt_is_functional_and_safe(
            payload,
            SimpleNamespace(user='{"source_problem_id":"hidden_problem"}'),
        )

    with pytest.raises(AssertionError):
        _assert_prompt_is_functional_and_safe(
            payload,
            SimpleNamespace(user="read fact:ii:coefficient_relation"),
        )


def test_prompt_safety_allows_call_id_equal_to_hidden_example_id() -> None:
    payload = {
        "planner_protocol": "functional-plan-content/v2",
        "problem_planning_context": {
            "schema_version": "planner-problem-view/v2",
            "root_scope": {"id": "problem", "text": ["x"]},
        },
        "functional_few_shot_selection": {
            "mode": "strict_test",
            "example_id": "broken_path_straightening",
            "source_problem_id": "hidden_problem",
            "family_id": "HiddenFamily",
            "selection_tier": "cross_family",
        },
        "few_shot_examples": [
            {"format": "functional-plan-content/v2", "root_scope": {}}
        ],
    }
    prompt = SimpleNamespace(
        user=(
            '{"format":"functional-plan-content/v2","root_scope":{"steps":['
            '{"call_id":"broken_path_straightening"}]}]}'
        )
    )

    _assert_prompt_is_functional_and_safe(payload, prompt)

    payload["few_shot_examples"][0]["example_id"] = "leaked"
    with pytest.raises(AssertionError, match="retrieval fields"):
        _assert_prompt_is_functional_and_safe(payload, prompt)


def test_prompt_safety_allows_problem_family_to_equal_hidden_selection_family() -> None:
    payload = {
        "planner_protocol": "functional-plan-content/v2",
        "problem_planning_context": {
            "schema_version": "planner-problem-view/v2",
            "problem_id": "current_problem",
            "family_id": "quadratic_path_minimum",
            "root_scope": {"id": "problem", "text": ["x"]},
        },
        "functional_few_shot_selection": {
            "mode": "new_problem",
            "example_id": "hidden_example",
            "source_problem_id": "hidden_problem",
            "family_id": "quadratic_path_minimum",
            "selection_tier": "same_family",
        },
        "few_shot_examples": [
            {"format": "functional-plan-content/v2", "root_scope": {}}
        ],
    }
    prompt = SimpleNamespace(
        user=(
            '{"problem_planning_context":{"family_id":'
            '"quadratic_path_minimum"}}'
        )
    )

    _assert_prompt_is_functional_and_safe(payload, prompt)
