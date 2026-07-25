from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from _functional_opt_in_support import (
    FUNCTIONAL_OPT_IN_CASES,
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
    few_shot = [{"format": "functional_plan/v1", "scopes": []}]
    for attempt in (1, 2):
        (tmp_path / f"attempt-{attempt}.llm-metadata.json").write_text(
            json.dumps({"candidate_format": "functional_plan"}),
            encoding="utf-8",
        )
        (tmp_path / f"attempt-{attempt}.raw-response.txt").write_text(
            '{"format":"functional_plan/v1","scopes":[]}',
            encoding="utf-8",
        )
        (tmp_path / f"attempt-{attempt}.payload.functional_few_shot_selection.json").write_text(
            json.dumps(selection),
            encoding="utf-8",
        )
        (tmp_path / f"attempt-{attempt}.payload.few_shot_examples.json").write_text(
            json.dumps(few_shot),
            encoding="utf-8",
        )

    _assert_attempt_protocol(tmp_path, attempt_count=2)

    (tmp_path / "attempt-2.payload.functional_few_shot_selection.json").write_text(
        json.dumps({**selection, "example_id": "changed"}),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        _assert_attempt_protocol(tmp_path, attempt_count=2)


def test_prompt_safety_distinguishes_error_codes_from_canonical_handles() -> None:
    payload = {
        "planner_output_format": "functional_plan",
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

    with pytest.raises(AssertionError):
        _assert_prompt_is_functional_and_safe(
            payload,
            SimpleNamespace(user="read fact:ii:coefficient_relation"),
        )
