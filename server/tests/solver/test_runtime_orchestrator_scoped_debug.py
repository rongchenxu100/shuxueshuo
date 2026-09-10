from __future__ import annotations

import json
from dataclasses import dataclass, replace
from types import MappingProxyType, SimpleNamespace

import pytest

from shuxueshuo_server.solver.runtime.llm_debug import safe_debug_json, write_debug_json
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanIssue,
    ScopedFunctionalPlanValidationReport,
)

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
    _safe_json,
    _scoped_run_failure,
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


def test_scoped_run_failure_uses_scope_retry_error_names() -> None:
    error = _scoped_run_failure(
        SimpleNamespace(
            attempts=(),
            final_execution=None,
            no_progress=True,
        )
    )

    assert error.code == "planner.scope_retry_exhausted"
    assert "Scope retry exhausted" in error.message


@pytest.mark.parametrize("serialize", [safe_debug_json, _safe_json])
def test_debug_serializes_nested_frozen_data_without_copying_or_mutating(serialize, tmp_path):
    @dataclass(frozen=True)
    class Evidence:
        value: object

    source = Evidence(MappingProxyType({
        "items": (Evidence(MappingProxyType({"count": 2})),),
    }))
    expected = {"value": {"items": [{"value": {"count": 2}}]}}
    output = serialize(source)
    assert output == expected
    write_debug_json(tmp_path / "evidence.json", source)
    assert json.loads((tmp_path / "evidence.json").read_text()) == expected
    output["value"]["items"][0]["value"]["count"] = 99
    assert source.value["items"][0].value["count"] == 2
    assert isinstance(source.value, MappingProxyType)


def test_failed_validation_does_not_abort_writing_later_successful_attempt(tmp_path):
    issue = ScopedFunctionalPlanIssue(
        code="functional.plan_content_schema_invalid",
        path="$.scope_steps.shared[0]",
        message="required argument missing",
        details={"validator": "oneOf", "schema": MappingProxyType({"required": ("x",)})},
    )
    failed = replace(
        _attempt(1, FUNCTIONAL_PLAN_CONTENT_CONTRACT),
        content_validation_report=ScopedFunctionalPlanValidationReport((issue,)),
    )
    repaired = replace(
        _attempt(2, FUNCTIONAL_PLAN_CONTENT_CONTRACT),
        content_validation_report=ScopedFunctionalPlanValidationReport(),
    )
    _write_scoped_debug_attempts(
        tmp_path, SimpleNamespace(artifacts=None, client=None),
        SimpleNamespace(attempts=(failed, repaired)),
    )
    report = json.loads((tmp_path / "attempt-1.validation-report.json").read_text())
    assert report["issues"][0] == {
        "code": issue.code, "path": issue.path, "message": issue.message,
        "details": {"validator": "oneOf", "schema": {"required": ["x"]}},
    }
    assert json.loads((tmp_path / "attempt-2.validation-report.json").read_text()) == {"issues": []}
    assert json.loads((tmp_path / "attempt-2.raw-response.txt").read_text()) == {"attempt_marker": 2}
    assert isinstance(issue.details, MappingProxyType)


def test_evidence_index_separates_missing_candidate_from_previous_base(tmp_path):
    from hashlib import sha256
    from shuxueshuo_server.solver.runtime.functional_scope_retry import FunctionalScopeRetryError

    old = SimpleNamespace(to_payload=lambda: {"old_base": True})
    attempt = replace(
        _attempt(2, FUNCTIONAL_SCOPE_REPAIR_CONTRACT),
        plan=old, base_plan=old,
        raw_response='{"output_targets": false}',
        normalized_response={},
        candidate_plan={"candidate": "rejected"},
        error=FunctionalScopeRetryError("candidate.invalid", "$.args.x", "wrong type"),
    )
    _write_scoped_debug_attempts(tmp_path, SimpleNamespace(), SimpleNamespace(attempts=(attempt,)))
    index = json.loads((tmp_path / 'attempt-2.evidence-index.json').read_text())
    roles = index['artifacts']
    assert roles['canonical-plan']['status'] == 'not_available'
    assert roles['compiled-plan']['status'] == 'not_available'
    assert roles['transaction']['reason'] == 'transaction_not_started'
    assert json.loads((tmp_path / 'attempt-2.base-plan.json').read_text()) == {'old_base': True}
    assert json.loads((tmp_path / 'attempt-2.normalized-response.json').read_text()) == {}
    assert json.loads((tmp_path / 'attempt-2.raw-response.json').read_text())['parsed'] == {'output_targets': False}
    assert json.loads((tmp_path / 'attempt-2.candidate-plan.json').read_text()) == {'candidate': 'rejected'}
    assert json.loads((tmp_path / 'attempt-2.blockers.json').read_text())['first_reported']['code'] == 'candidate.invalid'
    for role in roles.values():
        if role['status'] == 'saved':
            assert sha256((tmp_path / role['file']).read_bytes()).hexdigest() == role['sha256']


def test_reasoning_snapshots_do_not_borrow_later_calls(tmp_path):
    client = SimpleNamespace(last_provider_reasoning=[{'provider_attempt': 1, 'reasoning_content': 'first'}])
    first_meta = _scope_attempt_llm_metadata(client, semantic_attempt=1, planner_protocol=FUNCTIONAL_PLAN_CONTENT_CONTRACT)
    client.last_provider_reasoning[0]['reasoning_content'] = 'second'
    second_meta = _scope_attempt_llm_metadata(client, semantic_attempt=2, planner_protocol=FUNCTIONAL_PLAN_CONTENT_CONTRACT)
    attempts = [replace(_attempt(i, FUNCTIONAL_PLAN_CONTENT_CONTRACT), llm_metadata=meta)
                for i, meta in ((1, first_meta), (2, second_meta))]
    attempts.append(replace(_attempt(3, FUNCTIONAL_PLAN_CONTENT_CONTRACT), llm_metadata=None, raw_response=None))
    _write_scoped_debug_attempts(tmp_path, SimpleNamespace(client=client), SimpleNamespace(attempts=attempts))
    for i, content in ((1, 'first'), (2, 'second')):
        reasoning = json.loads((tmp_path / f'attempt-{i}.provider-reasoning.json').read_text())
        assert reasoning['status'] == 'provided'
        assert reasoning['attempts'][0]['reasoning_content'] == content
    assert json.loads((tmp_path / 'attempt-3.provider-reasoning.json').read_text())['status'] == 'unavailable'
    assert not (tmp_path / 'attempt-3.llm-metadata.json').exists()


def test_debug_json_atomic_failure_preserves_completed_file(tmp_path, monkeypatch):
    path = tmp_path / 'evidence.json'
    write_debug_json(path, {'completed': 1})
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr('shuxueshuo_server.solver.runtime.llm_debug.os.replace', fail)
    with pytest.raises(OSError):
        write_debug_json(path, {'partial': 2})
    assert json.loads(path.read_text()) == {'completed': 1}
    assert list(tmp_path.iterdir()) == [path]


def test_verified_orchestrator_publishes_before_run_scoped_returns(tmp_path, monkeypatch):
    from _problem_planning_support import cached_planning_binding_fixture
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner

    original = StrategyPlanner.run_scoped
    observed = []
    def wrapped(self, inputs, *, max_attempts=3, attempt_observer=None):
        assert callable(attempt_observer)
        def forward(attempt):
            attempt_observer(attempt)
            index = json.loads((tmp_path / f'attempt-{attempt.semantic_attempt}.evidence-index.json').read_text())
            observed.append(index['phase'])
            assert index['phase'] == attempt.evidence_phase
        result = original(self, inputs, max_attempts=max_attempts, attempt_observer=forward)
        assert observed[-1] == 'completed'
        return result
    monkeypatch.setattr(StrategyPlanner, 'run_scoped', wrapped)
    config = SolverRuntimeConfig(planner_mode='strategy', llm_provider='recorded')
    orchestrator = RuntimeOrchestrator(family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(), debug_dir=tmp_path)
    bundle, *_ = cached_planning_binding_fixture('tj-2026-heping-yimo-25')
    result = orchestrator.solve_verified(bundle)
    assert result.ok, result.errors
    assert observed == ['requested', 'received', 'compiled', 'completed']
    index = json.loads((tmp_path / 'attempt-1.evidence-index.json').read_text())
    assert index['artifacts']['canonical-plan']['status'] == 'saved'
    assert index['artifacts']['checkpoint']['status'] == 'saved'
