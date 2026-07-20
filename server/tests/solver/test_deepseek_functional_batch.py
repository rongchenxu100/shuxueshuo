from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.deepseek_functional_batch import (
    _answer_signature,
    _first_structured_error,
    _llm_summary,
    main,
)


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
    assert payload["test_path"] == (
        "tests/solver/test_deepseek_functional_planner_heping_ermo.py"
    )
    assert payload["sample_dirs"] == [
        str(tmp_path / "batch-test" / "sample-01"),
        str(tmp_path / "batch-test" / "sample-02"),
        str(tmp_path / "batch-test" / "sample-03"),
    ]
    assert not (tmp_path / "batch-test").exists()


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
