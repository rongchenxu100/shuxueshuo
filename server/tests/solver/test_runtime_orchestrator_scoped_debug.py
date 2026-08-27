from __future__ import annotations

import json
from types import SimpleNamespace

from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FUNCTIONAL_SCOPE_REPAIR_CONTRACT,
    ScopedFunctionalScopeRetryAttempt,
    ScopedFunctionalScopeRetryRunResult,
    _scope_attempt_llm_metadata,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
)
from shuxueshuo_server.solver.runtime.orchestrator import (
    _write_debug_attempt,
    _write_scoped_debug_attempts,
)
from shuxueshuo_server.solver.runtime.session import StructuredSolveError


def _attempt(index: int, protocol: str) -> ScopedFunctionalScopeRetryAttempt:
    return ScopedFunctionalScopeRetryAttempt(
        semantic_attempt=index,
        planner_protocol=protocol,
        payload={"attempt_marker": index},
        prompt=SimpleNamespace(
            system=f"system-{index}",
            user=f"user-{index}",
            messages=[{"role": "user", "content": f"user-{index}"}],
        ),
        raw_response=json.dumps({"attempt_marker": index}),
        plan=None,
        execution=None,
        llm_metadata={
            "semantic_attempt": index,
            "planner_protocol": protocol,
            "usage": {"completion_tokens": index},
        },
    )


def test_scoped_debug_writes_each_attempt_from_its_own_snapshot(tmp_path) -> None:
    attempts = (
        _attempt(1, FUNCTIONAL_PLAN_CONTENT_CONTRACT),
        _attempt(2, FUNCTIONAL_SCOPE_REPAIR_CONTRACT),
        _attempt(3, FUNCTIONAL_SCOPE_REPAIR_CONTRACT),
    )
    run_result = ScopedFunctionalScopeRetryRunResult(
        status="blocked",
        attempts=attempts,
        final_plan=None,
        final_execution=None,
        restored_call_count=0,
    )
    planner = SimpleNamespace(
        last_prompt=attempts[-1].prompt,
        last_payload=attempts[-1].payload,
        last_raw_response=attempts[-1].raw_response,
        artifacts=None,
        client=SimpleNamespace(
            last_usage={"completion_tokens": 999},
            last_response_model="final-only",
        ),
    )

    _write_scoped_debug_attempts(tmp_path, planner, run_result)

    for index in range(1, 4):
        assert (tmp_path / f"attempt-{index}.prompt.system.md").read_text() == (
            f"system-{index}"
        )
        assert json.loads(
            (tmp_path / f"attempt-{index}.raw-response.txt").read_text()
        ) == {"attempt_marker": index}
        metadata = json.loads(
            (tmp_path / f"attempt-{index}.llm-metadata.json").read_text()
        )
        assert metadata["semantic_attempt"] == index
        assert metadata["usage"] == {"completion_tokens": index}


def test_terminal_error_is_added_to_last_real_scoped_attempt(tmp_path) -> None:
    attempts = (
        _attempt(1, FUNCTIONAL_PLAN_CONTENT_CONTRACT),
        _attempt(2, FUNCTIONAL_SCOPE_REPAIR_CONTRACT),
    )
    planner = SimpleNamespace(artifacts=None, client=None)
    _write_scoped_debug_attempts(
        tmp_path,
        planner,
        SimpleNamespace(attempts=attempts),
    )

    _write_debug_attempt(
        tmp_path,
        2,
        planner,
        None,
        StructuredSolveError(
            stage="scoped_planner",
            code="planner.scoped_retry_blocked",
            message="blocked after two attempts",
        ),
        scoped_attempt=attempts[-1],
    )

    assert not (tmp_path / "attempt-1.structured-error.json").exists()
    error = json.loads(
        (tmp_path / "attempt-2.structured-error.json").read_text()
    )
    assert error["message"] == "blocked after two attempts"
    assert (tmp_path / "attempt-1.prompt.system.md").read_text() == "system-1"


def test_scoped_attempt_metadata_is_frozen_before_next_provider_call() -> None:
    usage = {"completion_tokens": 1}
    provider_attempts = [{"provider_attempt": 1}]
    client = SimpleNamespace(
        provider_name="fake",
        model="request-model",
        last_response_model="response-model-1",
        last_usage=usage,
        last_provider_attempts=provider_attempts,
    )

    metadata = _scope_attempt_llm_metadata(
        client,
        semantic_attempt=1,
        planner_protocol=FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    )
    usage["completion_tokens"] = 999
    provider_attempts[0]["provider_attempt"] = 999

    assert metadata["usage"]["completion_tokens"] == 1
    assert metadata["provider_attempts"][0]["provider_attempt"] == 1
