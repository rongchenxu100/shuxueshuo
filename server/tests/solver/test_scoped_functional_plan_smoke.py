from __future__ import annotations

import json
from types import SimpleNamespace

from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRetryError,
    ScopedFunctionalGoalRetryAttempt,
    ScopedFunctionalGoalRetryRunResult,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
)
from shuxueshuo_server.solver.scoped_functional_plan_smoke import (
    ScopedV2SmokeSampleResult,
    _RecordingClient,
    _batch_summary,
    _goal_retry_terminal_error,
    _smoke_completion_request_options,
    _write_provider_attempt_snapshot,
    _write_sample_review,
    main,
    rerender_existing_batch,
)


def _result(*, primary: bool) -> ScopedV2SmokeSampleResult:
    return ScopedV2SmokeSampleResult(
        problem_id="problem",
        sample_id="sample-01",
        provider_response_received=primary,
        provider_sub_attempt_count=1,
        schema_valid=primary,
        scope_goal_tree_ok=primary,
        plan_authority_ok=primary,
        prompt_identity_leaks=(),
        reconciliation_ok=primary,
        compile_ok=primary,
        transaction_ok=primary,
        transaction_attempted=primary,
        authority_valid_step_count=int(primary),
        authority_invalid_step_count=0,
        pruned_dead_step_count=0,
        provisional_executed_step_count=int(primary),
        blocked_by_dependency_step_count=0,
        blocked_stage=None,
        passed_goal_count=int(primary),
        goal_count=1,
        output_ok=primary,
        configuration_error_count=0,
        unclassified_error_count=0,
        usage={"total_tokens": 10},
        duration_seconds=1.0,
        error_code=None,
        error_message=None,
        sample_dir="sample",
    )


def test_summary_separates_primary_authority_from_runtime_diagnostics() -> None:
    result = _result(primary=True)
    result = ScopedV2SmokeSampleResult(
        **{
            **result.__dict__,
            "transaction_ok": False,
            "output_ok": False,
        }
    )
    summary = _batch_summary({"batch_id": "test"}, (result,))
    assert summary["primary_gate_ok"]
    assert summary["primary_passed"] == 1
    assert summary["scope_goal_tree_ok_count"] == 1
    assert summary["plan_authority_ok_count"] == 1
    assert summary["transaction_attempted_count"] == 1
    assert summary["authority_valid_step_count"] == 1
    assert summary["provisional_executed_step_count"] == 1
    assert "scope_goal_authority_count" not in summary
    assert "scope_goal_authority_ok" not in summary["samples"][0]
    assert summary["transaction_ok_count"] == 0
    assert not summary["completion_gate_ok"]


def test_tree_success_does_not_mask_plan_authority_failure() -> None:
    result = _result(primary=True)
    result = ScopedV2SmokeSampleResult(
        **{
            **result.__dict__,
            "plan_authority_ok": False,
            "error_code": "functional.step_contract_invalid",
        }
    )
    summary = _batch_summary({"batch_id": "test"}, (result,))

    assert not result.primary_ok
    assert summary["scope_goal_tree_ok_count"] == 1
    assert summary["plan_authority_ok_count"] == 0
    assert not summary["primary_gate_ok"]


def test_dry_run_does_not_require_live_integration_flag(capsys) -> None:
    assert main(["--batch-id", "dry-run", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert f'"planner_protocol": "{FUNCTIONAL_PLAN_CONTENT_CONTRACT}"' in output
    assert '"semantic_attempts": 3' in output


def test_smoke_disabled_thinking_profile_is_explicit() -> None:
    assert _smoke_completion_request_options(
        "disabled", temperature=0.0
    ) == {
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_provider_boundary_is_persisted_before_plan_execution(tmp_path) -> None:
    class Provider:
        model = "deepseek-v4-flash"
        last_usage = {"prompt_tokens": 10, "completion_tokens": 2}
        last_response_model = "deepseek-v4-flash"
        last_provider_attempts = ({"provider_attempt": 1},)

        def complete(self, _payload):
            return '{"format":"functional-plan-content/v2"}'

    client = _RecordingClient(
        Provider(),
        record_sink=lambda recorder, record: _write_provider_attempt_snapshot(
            tmp_path,
            client=recorder,
            record=record,
            thinking_profile="low",
        ),
    )
    client.complete(
        {
            "planner_attempt": 1,
            "planner_protocol": FUNCTIONAL_PLAN_CONTENT_CONTRACT,
            "planner_payload": {"problem_planning_context": {"id": "p"}},
            "messages": [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
        }
    )

    assert (tmp_path / "attempt-1.raw-response.txt").read_text() == (
        '{"format":"functional-plan-content/v2"}'
    )
    assert (tmp_path / "attempt-1.prompt.system.md").read_text() == (
        "system prompt"
    )
    stage = json.loads((tmp_path / "attempt-1.attempt-stage.json").read_text())
    assert stage["stage"] == "provider_completed"
    assert stage["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
    assert _smoke_completion_request_options("low", temperature=0.0) == {
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "low",
    }
    assert _smoke_completion_request_options(
        "low",
        temperature=0.0,
        semantic_attempt=2,
    ) == {
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "enabled"}},
        "reasoning_effort": "low",
    }


def test_low_thinking_dry_run_applies_to_pass1_and_retry(capsys) -> None:
    assert main(
        [
            "--batch-id",
            "dry-run-low",
            "--thinking",
            "low",
            "--dry-run",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert '"semantic_attempts": 3' in output
    assert '"pass1_thinking": "enabled"' in output
    assert '"pass1_reasoning_effort": "low"' in output
    assert '"retry_thinking": "enabled"' in output
    assert '"retry_reasoning_effort": "low"' in output
    assert '"thinking_profile": "low"' in output


def test_terminal_error_comes_from_the_last_attempt_not_an_early_schema_error() -> None:
    early = FunctionalGoalRetryError(
        "functional.v2_schema_invalid",
        "$.root_scope",
        "early schema failure",
    )
    checkpoint = SimpleNamespace(
        root_issues=(
            {
                "code": "functional.transactional_call_failed",
                "path": "$.steps['latest']",
                "message": "latest runtime failure",
            },
        ),
        root_scope=SimpleNamespace(
            scope_steps=(),
            goals=(),
            children=(),
        ),
    )
    final_execution = SimpleNamespace(checkpoint=checkpoint)
    attempts = (
        ScopedFunctionalGoalRetryAttempt(
            semantic_attempt=1,
            planner_protocol=FUNCTIONAL_PLAN_CONTENT_CONTRACT,
            payload={},
            prompt=SimpleNamespace(system="", user=""),
            raw_response="{}",
            plan=None,
            execution=None,
            error=early,
        ),
        ScopedFunctionalGoalRetryAttempt(
            semantic_attempt=2,
            planner_protocol=FUNCTIONAL_GOAL_REPAIR_CONTRACT,
            payload={},
            prompt=SimpleNamespace(system="", user=""),
            raw_response="{}",
            plan=None,
            execution=final_execution,
        ),
    )
    result = ScopedFunctionalGoalRetryRunResult(
        status="blocked",
        attempts=attempts,
        final_plan=None,
        final_execution=final_execution,
        solved_goal_restore_count=0,
    )

    error = _goal_retry_terminal_error(result)

    assert isinstance(error, FunctionalGoalRetryError)
    assert error.code == "functional.transactional_call_failed"
    assert "latest runtime failure" in error.message


def test_review_displays_exact_problem_view_without_internal_authority(tmp_path) -> None:
    problem_view = _problem_view_payload()
    plan = _plan_payload()
    _write_sample_review(
        tmp_path,
        result_payload={
            **_result(primary=True).to_payload(),
            "problem_id": "problem-25",
        },
        raw_response=json.dumps(plan),
        validation_payload={"ok": True, "issues": []},
        problem_view_payload=problem_view,
        plan_payload=plan,
        normalized_plan_payload=plan,
        raw_structure_report_payload={
            "ok": True,
            "expected_scope_parents": [
                {"scope_ref": "i", "parent_scope_ref": None}
            ],
            "actual_scope_parents": [
                {"scope_ref": "i", "parent_scope_ref": None}
            ],
            "expected_goal_owners": [
                {"goal_ref": "i.answer", "owner_scope_ref": "i"}
            ],
            "actual_goal_owners": [
                {"goal_ref": "i.answer", "owner_scope_ref": "i"}
            ],
            "issues": [],
        },
        goal_normalizations_payload=[],
        structure_report_payload={
            "ok": True,
            "expected_scope_parents": [
                {"scope_ref": "i", "parent_scope_ref": None}
            ],
            "actual_scope_parents": [
                {"scope_ref": "i", "parent_scope_ref": None}
            ],
            "expected_goal_owners": [
                {"goal_ref": "i.answer", "owner_scope_ref": "i"}
            ],
            "actual_goal_owners": [
                {"goal_ref": "i.answer", "owner_scope_ref": "i"}
            ],
            "issues": [],
        },
        authority_report_payload={"ok": True, "error": None},
        llm_metadata={
            "request_model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoning_effort": "low",
            "temperature": 0,
        },
        return_expectation_policies_payload=(
            {
                "capability_id": "solve_answer",
                "returns": [
                    {
                        "name": "answer",
                        "type": "ParameterValue",
                        "return_expectation_policy": "omit",
                    }
                ],
            },
        ),
        checkpoint_payload={
            "schema_version": "functional-goal-execution-checkpoint/v1",
            "root_scope": {"scope_ref": "i"},
            "metrics": {
                "authority_valid_step_count": 1,
                "authority_invalid_step_count": 0,
                "pruned_dead_step_count": 0,
                "provisional_executed_step_count": 1,
                "blocked_by_dependency_step_count": 0,
                "transaction_attempted": True,
                "transaction_ok": True,
                "blocked_stage": None,
            },
        },
    )

    html = (tmp_path / "review.html").read_text(encoding="utf-8")
    assert "Problem JSON sent to LLM" in html
    assert "planner-problem-view/v2" in html
    assert 'payload.problem_planning_context.json' in html
    assert "i.answer" in html
    assert "scope_goal_tree_ok=True" in html
    assert "plan_authority_ok=True" in html
    assert "Return expectation policy" in html
    assert "return_expectation_policy" in html
    assert "functional-goal-execution-checkpoint/v1" in html
    assert "transaction_attempted" in html
    for forbidden in (
        "source_unit_id",
        "runtime_node_id",
        "bundle_authority_token",
        "MathObjectId",
        "StateVersionId",
    ):
        assert forbidden not in html


def test_historical_rerender_changes_only_review_html(tmp_path) -> None:
    sample_dir = tmp_path / "batch" / "problem-25" / "sample-01"
    sample_dir.mkdir(parents=True)
    old_result = _result(primary=True).to_payload()
    old_result.pop("scope_goal_tree_ok")
    old_result.pop("plan_authority_ok")
    old_result["scope_goal_authority_ok"] = True
    artifacts = {
        "sample-result.json": old_result,
        "payload.problem_planning_context.json": _problem_view_payload(),
        "scoped-functional-plan.json": _plan_payload(),
        "contract-validation.json": {"ok": True, "issues": []},
        "llm-metadata.json": {"thinking": "enabled", "reasoning_effort": "low"},
        "structured-error.json": None,
    }
    for name, payload in artifacts.items():
        (sample_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    (sample_dir / "raw-response.txt").write_text(
        json.dumps(_plan_payload()),
        encoding="utf-8",
    )
    before = {
        path: path.read_bytes()
        for path in sample_dir.iterdir()
        if path.suffix in {".json", ".txt"}
    }

    assert rerender_existing_batch(tmp_path / "batch") == 1

    assert before == {path: path.read_bytes() for path in before}
    html = (sample_dir / "review.html").read_text(encoding="utf-8")
    assert "scope_goal_tree_ok=True" in html
    assert "plan_authority_ok=True" in html
    assert "scope_goal_authority_ok" not in html


def _problem_view_payload():
    return {
        "schema_version": "planner-problem-view/v2",
        "problem_id": "problem-25",
        "family_id": "family",
        "source": {"question_number": "25", "score": "10"},
        "root_scope": {
            "id": "i",
            "text": ["求结果。"],
            "goals": [
                {
                    "goal_ref": "i.answer",
                    "answer_type": "Scalar",
                    "kind": "minimum_value",
                    "target": "answer",
                }
            ],
        },
    }


def _plan_payload():
    return {
        "format": "functional_plan/v2",
        "root_scope": {
            "scope_ref": "i",
            "steps": [
                {
                    "step_id": "solve_goal",
                    "capability_id": "solve",
                    "args": {},
                }
            ],
            "goals": [
                {
                    "goal_ref": "i.answer",
                    "answer_from": {"step_id": "solve_goal", "return": "value"},
                }
            ],
        },
    }
