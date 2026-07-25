from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, Sequence

import pytest
import sympy as sp

from shuxueshuo_server.solver import load_expected_answers
from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
    FunctionalBatchCase,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.strategy_payload import (
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)


RUN_FUNCTIONAL = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_FUNCTIONAL_PLANNER") == "1"
)


FunctionalOptInCase = FunctionalBatchCase
FUNCTIONAL_OPT_IN_CASES: Mapping[str, FunctionalOptInCase] = FUNCTIONAL_BATCH_CASES


def run_deepseek_functional_opt_in(case: FunctionalOptInCase) -> None:
    debug_dir = _debug_dir(case)
    _reset_debug_dir(debug_dir, preserve_batches=debug_dir == case.default_debug_dir)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    if not config.deepseek_api_key:
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    client = config.build_llm_client()
    problem = load_problem_ir(case.problem_fixture_path)
    expected = load_expected_answers(case.expected_path)
    orchestrator = RuntimeOrchestrator(
        planner_providers={},
        default_planner_provider=strategy_planner_provider(
            mode="deepseek",
            client=client,
            functional_few_shot_mode="strict_test",
            output_format="functional_plan",
        ),
        max_attempts=_max_attempts(),
        debug_dir=debug_dir,
    )

    result = orchestrator.solve(problem)
    answer_mismatch = _answer_mismatch(result.answers, expected)
    attempt_count = (
        len(orchestrator.last_session.attempts)
        if orchestrator.last_session is not None
        else 0
    )
    _write_sample_result(
        debug_dir,
        sample_id=os.getenv("DEEPSEEK_FUNCTIONAL_PLANNER_SAMPLE_ID", "single"),
        case=case,
        result=result,
        attempt_count=attempt_count,
        answer_mismatch=answer_mismatch,
    )

    assert result.status == "ok", result.errors
    assert all(check.ok for check in result.checks)
    assert answer_mismatch is None, answer_mismatch
    _assert_attempt_protocol(debug_dir, attempt_count=attempt_count)

    success = orchestrator.last_success_artifacts
    assert success is not None
    artifacts = success.planner.artifacts
    replay = artifacts.retry_replay_result
    assert artifacts.candidate_format == "functional_plan"
    assert replay is not None and replay.functional_plan is not None
    assert replay.functional_reconciliation is not None
    assert replay.functional_reconciliation.ok
    assert replay.functional_reconciliation.projection_map
    assert replay.planner_state_context is not None
    if replay.retry_state is not None:
        assert replay.retry_state.candidate_format == "functional_plan"
    selection = (artifacts.payload or {}).get("functional_few_shot_selection")
    assert isinstance(selection, dict)
    assert selection.get("mode") == "strict_test"
    assert selection.get("source_problem_id") != case.problem_id
    _assert_prompt_is_functional_and_safe(artifacts.payload or {}, artifacts.prompt)
    write_strategy_debug_artifacts(
        debug_dir,
        payload=artifacts.payload or {},
        prompt=artifacts.prompt,
        raw_response=artifacts.raw_response,
        draft=replay.raw_draft,
        report=replay.functional_validation_report,
        normalization_report=replay.normalization_report,
        resolution_report=replay.resolution_report,
        execution_diagnostic=replay.diagnostic,
        effective_draft=replay.effective_draft,
        planner_retry_state=replay.retry_state,
        planner_state_context=replay.planner_state_context,
        functional_plan=replay.functional_plan,
        functional_reconciliation=replay.functional_reconciliation,
        llm_metadata={
            "provider": "deepseek",
            "request_model": getattr(client, "model", None),
            "response_model": getattr(client, "last_response_model", None),
            "usage": getattr(client, "last_usage", None),
            "attempts": attempt_count,
            "candidate_format": "functional_plan",
        },
    )
    required_debug_artifacts = [
        "functional-plan.json",
        "functional-reconciliation-report.json",
        "effective-step-intents.json",
        "planner-state-context.json",
        "raw-response.txt",
    ]
    if replay.retry_state is not None:
        required_debug_artifacts.append("planner-retry-state.json")
    for name in required_debug_artifacts:
        assert (debug_dir / name).exists(), name


def assert_answers_semantically_equal(actual: Any, expected: Any, path: str = "answers") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected object, got {type(actual).__name__}"
        assert set(actual) == set(expected), (
            f"{path}: keys differ; actual={sorted(actual)}, expected={sorted(expected)}"
        )
        for key, value in expected.items():
            assert_answers_semantically_equal(actual[key], value, f"{path}.{key}")
        return
    if isinstance(expected, (list, tuple)):
        assert isinstance(actual, (list, tuple)), (
            f"{path}: expected sequence, got {type(actual).__name__}"
        )
        assert len(actual) == len(expected), (
            f"{path}: lengths differ; actual={len(actual)}, expected={len(expected)}"
        )
        for index, value in enumerate(expected):
            assert_answers_semantically_equal(actual[index], value, f"{path}[{index}]")
        return
    if actual == expected:
        return
    if isinstance(actual, str) and isinstance(expected, str):
        try:
            if sp.simplify(sp.sympify(actual) - sp.sympify(expected)) == 0:
                return
        except (TypeError, ValueError, sp.SympifyError):
            pass
    raise AssertionError(f"{path}: actual={actual!r}, expected={expected!r}")


def _answer_mismatch(actual: Any, expected: Any) -> str | None:
    try:
        assert_answers_semantically_equal(actual, expected)
    except AssertionError as exc:
        return str(exc)
    return None


def _assert_attempt_protocol(debug_dir: Path, *, attempt_count: int) -> None:
    selections: list[dict[str, Any]] = []
    examples: list[Any] = []
    for attempt in range(1, attempt_count + 1):
        prefix = debug_dir / f"attempt-{attempt}"
        metadata = _read_json(prefix.with_suffix(".llm-metadata.json"))
        assert metadata.get("candidate_format") == "functional_plan"
        raw_response = prefix.with_suffix(".raw-response.txt").read_text(encoding="utf-8")
        assert '"format":"step_intent"' not in "".join(raw_response.split())
        selection = _read_json(
            prefix.with_suffix(".payload.functional_few_shot_selection.json")
        )
        assert selection.get("mode") == "strict_test"
        selections.append(selection)
        examples.append(
            _read_json_value(prefix.with_suffix(".payload.few_shot_examples.json"))
        )
    assert selections
    assert all(item == selections[0] for item in selections[1:])
    assert all(item == examples[0] for item in examples[1:])


def _assert_prompt_is_functional_and_safe(payload: dict[str, Any], prompt: Any) -> None:
    assert payload.get("planner_output_format") == "functional_plan"
    assert "expected_answers" not in json.dumps(payload, ensure_ascii=False)
    user_prompt = str(getattr(prompt, "user", ""))
    serialized = user_prompt.lower()
    for forbidden in (
        "runtime_path",
        '"creates"',
        '"produces"',
        '"format": "step_intent"',
    ):
        assert forbidden not in serialized
    canonical_handle = re.compile(
        r"(?<![a-z0-9_])(?:fact|point):[a-z0-9_]+:|"
        r"(?<![a-z0-9_])answer:[a-z0-9_]+[.:]"
    )
    assert canonical_handle.search(serialized) is None
    selection = payload.get("functional_few_shot_selection")
    if isinstance(selection, dict):
        for key in ("example_id", "source_problem_id", "family_id", "selection_tier"):
            value = selection.get(key)
            if isinstance(value, str) and value:
                # Retrieval metadata is serialized as standalone JSON values.
                # A raw substring check incorrectly rejects an example id that
                # is also a prefix of a legitimate capability id.
                assert json.dumps(value, ensure_ascii=False) not in user_prompt


def _max_attempts() -> int:
    return max(1, int(os.getenv("DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS", "3")))


def _debug_dir(case: FunctionalOptInCase) -> Path:
    return Path(
        os.getenv(
            "DEEPSEEK_FUNCTIONAL_PLANNER_DEBUG_DIR",
            str(case.default_debug_dir),
        )
    ).expanduser().resolve()


def _reset_debug_dir(path: Path, *, preserve_batches: bool) -> None:
    if path.exists():
        for child in path.iterdir():
            if preserve_batches and child.name == "batches":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _write_sample_result(
    path: Path,
    *,
    sample_id: str,
    case: FunctionalOptInCase,
    result: object,
    attempt_count: int,
    answer_mismatch: str | None,
) -> None:
    payload = {
        "sample_id": sample_id,
        "case_id": case.case_id,
        "problem_id": case.problem_id,
        "status": getattr(result, "status", None),
        "attempt_count": attempt_count,
        "answers": getattr(result, "answers", {}),
        "expected_match": answer_mismatch is None,
        "expected_mismatch": answer_mismatch,
        "errors": getattr(result, "errors", []),
        "checks": [
            {"ok": getattr(check, "ok", False), "message": str(check)}
            for check in getattr(result, "checks", [])
        ],
    }
    path.mkdir(parents=True, exist_ok=True)
    (path / "sample-result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = _read_json_value(path)
    assert isinstance(payload, dict), path
    return payload


def _read_json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def case_ids() -> Sequence[str]:
    return tuple(FUNCTIONAL_OPT_IN_CASES)
