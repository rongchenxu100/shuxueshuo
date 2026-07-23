from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from _functional_opt_in_support import _assert_prompt_is_functional_and_safe

from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
    _answer_signature,
    _case_metrics,
    _first_structured_error,
    _hash_files,
    _llm_summary,
    main,
)


def test_prompt_metadata_guard_allows_capability_prefixed_by_example_id() -> None:
    payload = {
        "planner_output_format": "functional_plan",
        "functional_few_shot_selection": {
            "example_id": "broken_path_straightening",
            "source_problem_id": "synthetic-source",
            "family_id": "SyntheticFamily",
            "selection_tier": "cross_family",
        },
    }
    prompt = SimpleNamespace(
        user='{"capability_id":"broken_path_straightening_and_select"}',
    )

    _assert_prompt_is_functional_and_safe(payload, prompt)


def test_batch_dry_run_allocates_isolated_sample_directories(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(
        [
            "--samples",
            "3",
            "--concurrency",
            "3",
            "--batch-id",
            "batch-test",
            "--output-root",
            str(tmp_path),
            "--test-path",
            "tests/solver/test_deepseek_functional_planner_heping_ermo.py",
            "--dry-run",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["concurrency"] == 3
    assert payload["cases"] == ["nankai"]
    assert payload["test_path"] == (
        "tests/solver/test_deepseek_functional_planner_heping_ermo.py"
    )
    assert payload["sample_dirs"] == [
        str(tmp_path / "batch-test" / "nankai" / "sample-01"),
        str(tmp_path / "batch-test" / "nankai" / "sample-02"),
        str(tmp_path / "batch-test" / "nankai" / "sample-03"),
    ]
    assert not (tmp_path / "batch-test").exists()


def test_all_case_dry_run_uses_global_concurrency_and_isolated_case_dirs(
    tmp_path: Path,
    capsys,
) -> None:
    assert main(
        [
            "--case",
            "all",
            "--samples-per-case",
            "2",
            "--concurrency",
            "3",
            "--batch-id",
            "batch-all",
            "--output-root",
            str(tmp_path),
            "--dry-run",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["cases"] == list(FUNCTIONAL_BATCH_CASES)
    assert payload["samples"] == 10
    assert payload["samples_per_case"] == 2
    assert payload["concurrency"] == 3
    assert payload["test_path"] is None
    assert payload["sample_dirs"][0] == str(
        tmp_path / "batch-all" / "nankai" / "sample-01"
    )
    assert payload["sample_dirs"][-1] == str(
        tmp_path / "batch-all" / "heping" / "sample-02"
    )
    assert not (tmp_path / "batch-all").exists()


def test_batch_summary_reads_attempt_errors_and_usage(tmp_path: Path) -> None:
    (tmp_path / "attempt-1.structured-error.json").write_text(
        json.dumps(
            {
                "stage": "planner",
                "code": "planner_failed",
                "message": "typed failure",
                "retryable": True,
                "details": {"ignored": True},
            }
        ),
        encoding="utf-8",
    )
    for attempt, prompt, completion in ((1, 10, 20), (2, 11, 21)):
        (tmp_path / f"attempt-{attempt}.llm-metadata.json").write_text(
            json.dumps(
                {
                    "response_model": "deepseek-test",
                    "usage": {
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": prompt + completion,
                    },
                }
            ),
            encoding="utf-8",
        )

    assert _first_structured_error(tmp_path) == {
        "stage": "planner",
        "code": "planner_failed",
        "message": "typed failure",
        "retryable": True,
    }
    assert _llm_summary(tmp_path) == {
        "models": ["deepseek-test"],
        "usage": {
            "prompt_tokens": 21,
            "completion_tokens": 41,
            "total_tokens": 62,
        },
    }
    assert _answer_signature({"ii": {"value": "sqrt(2)"}}) == (
        '{"ii":{"value":"sqrt(2)"}}'
    )


def test_case_metrics_compute_stage_gates_and_error_frequencies() -> None:
    stage1 = _case_metrics(
        [
            _sample_result("sample-01", "passed", 1),
            _sample_result("sample-02", "passed", 2),
            _sample_result("sample-03", "passed", 3),
        ],
        max_attempts=3,
    )

    assert stage1["pass_at_1"] == 1 / 3
    assert stage1["pass_at_3"] == 1.0
    assert stage1["stage1_gate_passed"] is True
    assert stage1["stage2_gate_passed"] is False
    assert stage1["attempt_distribution"] == {"1": 1, "2": 1, "3": 1}

    results = [
        _sample_result(f"sample-{index:02d}", "passed", 1)
        for index in range(1, 10)
    ]
    results.append(
        _sample_result(
            "sample-10",
            "failed",
            3,
            errors=[
                {
                    "stage": "planner",
                    "code": "planner_failed",
                    "message": "strategy did not converge",
                }
            ],
        )
    )
    stage2 = _case_metrics(results, max_attempts=3)

    assert stage2["pass_at_3"] == 0.9
    assert stage2["stage2_gate_passed"] is True
    assert stage2["error_frequency"] == {"planner/planner_failed": 1}


def test_configuration_or_fingerprint_drift_blocks_parity_gate() -> None:
    results = [
        _sample_result("sample-01", "passed", 1, compatibility_key="a"),
        _sample_result("sample-02", "passed", 1, compatibility_key="b"),
        _sample_result(
            "sample-03",
            "passed",
            1,
            compatibility_key="a",
            errors=[
                {
                    "stage": "planner",
                    "code": "planner_failed",
                    "message": "planner_configuration_error: missing adapter",
                }
            ],
        ),
    ]

    metrics = _case_metrics(results, max_attempts=3)

    assert metrics["compatible"] is False
    assert metrics["configuration_error_count"] == 1
    assert metrics["stage1_gate_passed"] is False


def test_file_fingerprint_ignores_isolated_sample_directory(tmp_path: Path) -> None:
    first = tmp_path / "sample-01" / "attempt-1.prompt.user.md"
    second = tmp_path / "sample-02" / "attempt-1.prompt.user.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("same prompt", encoding="utf-8")
    second.write_text("same prompt", encoding="utf-8")

    assert _hash_files((first,)) == _hash_files((second,))


def _sample_result(
    sample_id: str,
    outcome: str,
    attempts: int,
    *,
    compatibility_key: str = "same",
    errors: list[dict] | None = None,
) -> dict:
    return {
        "sample_id": sample_id,
        "outcome": outcome,
        "attempt_count": attempts,
        "duration_seconds": 1.0,
        "answer_signature": "answer" if outcome == "passed" else None,
        "structured_errors": errors or [],
        "llm": {
            "models": ["deepseek-test"],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
        "fingerprints": {"compatibility_key": compatibility_key},
    }
