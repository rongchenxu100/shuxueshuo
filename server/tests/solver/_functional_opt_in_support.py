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
from shuxueshuo_server.solver.functional_parity import (
    provenance_parity_signature,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
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
            functional_transaction_mode=os.getenv(
                "FUNCTIONAL_TRANSACTION_MODE",
                "legacy",
            ),
            functional_symbolic_closure_mode=os.getenv(
                "FUNCTIONAL_SYMBOLIC_CLOSURE_MODE",
                "disabled",
            ),
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
    gate_checks: list[dict[str, Any]] = []
    (
        closure_execution_count,
        closure_drift_count,
        closure_attempt_artifacts_found,
    ) = _attempt_symbolic_closure_counts(debug_dir)
    _record_gate(
        gate_checks,
        "solver_status",
        result.status == "ok",
        str(result.errors),
    )
    _record_gate(
        gate_checks,
        "runtime_checks",
        all(check.ok for check in result.checks),
        str([check for check in result.checks if not check.ok]),
    )
    _record_gate(
        gate_checks,
        "answer_semantics",
        answer_mismatch is None,
        answer_mismatch or "",
    )
    success = orchestrator.last_success_artifacts
    _record_gate(
        gate_checks,
        "success_artifacts",
        success is not None,
        "RuntimeOrchestrator produced no success artifacts",
    )
    _capture_assertion_gate(
        gate_checks,
        "attempt_protocol",
        lambda: _assert_attempt_protocol(
            debug_dir,
            attempt_count=attempt_count,
        ),
    )
    if success is not None:
        artifacts = success.planner.artifacts
        replay = artifacts.retry_replay_result
        if replay is not None:
            transaction_report = replay.transactional_execution_report
            if (
                transaction_report is not None
                and not closure_attempt_artifacts_found
            ):
                closure_execution_count = (
                    transaction_report.symbolic_closure_execution_count
                )
                closure_drift_count = (
                    transaction_report.symbolic_closure_drift_count
                )
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
        expected_closure_mode = os.getenv(
            "FUNCTIONAL_SYMBOLIC_CLOSURE_MODE",
            "disabled",
        )
        _record_gate(
            gate_checks,
            "symbolic_closure_drift",
            closure_drift_count == 0,
            f"mode={expected_closure_mode}, drift={closure_drift_count}",
        )
        if (
            expected_closure_mode == "authoritative"
            and replay is not None
            and artifacts.planner_inputs is not None
            and _functional_replay_declares_symbolic_target(
                replay,
                inputs=artifacts.planner_inputs,
            )
        ):
            _record_gate(
                gate_checks,
                "symbolic_closure_executed",
                closure_execution_count > 0,
                "authoritative FunctionalPlan declared a symbolic target "
                f"but execution_count={closure_execution_count}",
            )
        _record_gate(
            gate_checks,
            "candidate_format",
            artifacts.candidate_format == "functional_plan",
            f"candidate_format={artifacts.candidate_format}",
        )
        _record_gate(
            gate_checks,
            "functional_replay",
            replay is not None
            and replay.functional_plan is not None
            and replay.functional_reconciliation is not None
            and replay.functional_reconciliation.ok
            and bool(replay.functional_reconciliation.projection_map)
            and replay.planner_state_context is not None,
            "missing successful Functional replay artifacts",
        )
        if replay is not None and replay.retry_state is not None:
            _record_gate(
                gate_checks,
                "retry_candidate_format",
                replay.retry_state.candidate_format == "functional_plan",
                f"candidate_format={replay.retry_state.candidate_format}",
            )
        selection = (artifacts.payload or {}).get(
            "functional_few_shot_selection"
        )
        _record_gate(
            gate_checks,
            "strict_few_shot",
            isinstance(selection, dict)
            and selection.get("mode") == "strict_test"
            and selection.get("source_problem_id") != case.problem_id,
            str(selection),
        )
        _capture_assertion_gate(
            gate_checks,
            "prompt_safety",
            lambda: _assert_prompt_is_functional_and_safe(
                artifacts.payload or {},
                artifacts.prompt,
            ),
        )
        if replay is not None and replay.diagnostic is not None:
            provenance = provenance_parity_signature(replay.diagnostic)
            _record_gate(
                gate_checks,
                "provenance_integrity",
                not provenance.integrity_issues,
                "; ".join(provenance.integrity_issues),
            )
        required_debug_artifacts = [
            "functional-plan.json",
            "functional-reconciliation-report.json",
            "effective-step-intents.json",
            "planner-state-context.json",
            "raw-response.txt",
        ]
        if replay is not None and replay.retry_state is not None:
            required_debug_artifacts.append("planner-retry-state.json")
        missing_artifacts = [
            name
            for name in required_debug_artifacts
            if not (debug_dir / name).exists()
        ]
        _record_gate(
            gate_checks,
            "debug_artifacts",
            not missing_artifacts,
            f"missing={missing_artifacts}",
        )
        _record_gate(
            gate_checks,
            "llm_usage",
            _attempt_llm_usage_is_recorded(
                debug_dir,
                attempt_count=attempt_count,
            ),
            "one or more attempts have no LLM usage artifact",
        )

    gate_failures = [
        {
            "stage": "test_harness",
            "code": f"functional_gate_{item['name']}_failed",
            "message": item["message"],
            "retryable": False,
        }
        for item in gate_checks
        if not item["ok"]
    ]
    _write_sample_result(
        debug_dir,
        sample_id=os.getenv("DEEPSEEK_FUNCTIONAL_PLANNER_SAMPLE_ID", "single"),
        case=case,
        result=result,
        attempt_count=attempt_count,
        answer_mismatch=answer_mismatch,
        gate_checks=gate_checks,
        gate_failures=gate_failures,
        closure_execution_count=closure_execution_count,
        closure_drift_count=closure_drift_count,
    )
    assert not gate_failures, gate_failures


def _attempt_symbolic_closure_counts(
    debug_dir: Path,
) -> tuple[int, int, bool]:
    """Aggregate C4 activity from every planner attempt, including failures."""

    execution_count = 0
    drift_count = 0
    found = False
    for path in sorted(debug_dir.glob("attempt-*.planner-state-context.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        state = payload.get("state", payload)
        report = state.get("functional_transaction_execution")
        if not isinstance(report, dict):
            continue
        found = True
        execution_count += int(
            report.get("symbolic_closure_execution_count", 0) or 0
        )
        drift_count += int(
            report.get("symbolic_closure_drift_count", 0) or 0
        )
    return execution_count, drift_count, found


def _functional_replay_declares_symbolic_target(
    replay: Any,
    *,
    inputs: Any,
) -> bool:
    reconciliation = replay.functional_reconciliation
    if reconciliation is None:
        return False
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    for call in reconciliation.calls:
        capability = catalog.get(call.capability_id)
        spec = (
            getattr(capability.source, "symbolic_closure", None)
            if capability is not None
            else None
        )
        if spec is not None and call.resolved_args.get(spec.target_arg):
            return True
    return False


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
    assert attempt_count > 0
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
        planner_output_format = _read_json_value(
            prefix.with_suffix(".payload.planner_output_format.json")
        )
        few_shot_examples = _read_json_value(
            prefix.with_suffix(".payload.few_shot_examples.json")
        )
        user_prompt = prefix.with_suffix(".prompt.user.md").read_text(
            encoding="utf-8"
        )
        _assert_prompt_is_functional_and_safe(
            {
                "planner_output_format": planner_output_format,
                "functional_few_shot_selection": selection,
                "few_shot_examples": few_shot_examples,
            },
            type("_Prompt", (), {"user": user_prompt})(),
        )
        selections.append(selection)
        examples.append(few_shot_examples)
    assert selections, "no FunctionalPlan attempts were recorded"
    assert all(item == selections[0] for item in selections[1:]), (
        "retry changed the locked Functional few-shot selection"
    )
    assert all(item == examples[0] for item in examples[1:]), (
        "retry changed the locked Functional few-shot payload"
    )


def _assert_prompt_is_functional_and_safe(payload: dict[str, Any], prompt: Any) -> None:
    assert payload.get("planner_output_format") == "functional_plan", (
        "planner_output_format is not functional_plan"
    )
    assert "expected_answers" not in json.dumps(payload, ensure_ascii=False), (
        "expected answers leaked into the planner payload"
    )
    _assert_no_few_shot_retrieval_metadata(
        payload.get("few_shot_examples", ())
    )
    user_prompt = str(getattr(prompt, "user", ""))
    serialized = user_prompt.lower()
    for forbidden in (
        "runtime_path",
        '"creates"',
        '"produces"',
        '"format": "step_intent"',
    ):
        assert forbidden not in serialized, (
            f"Functional prompt leaked forbidden token: {forbidden}"
        )
    canonical_handle = re.compile(
        r"(?<![a-z0-9_])(?:fact|point):[a-z0-9_]+:|"
        r"(?<![a-z0-9_])answer:[a-z0-9_]+[.:]"
    )
    assert canonical_handle.search(serialized) is None, (
        "Functional prompt leaked a canonical handle"
    )
    selection = payload.get("functional_few_shot_selection")
    if isinstance(selection, dict):
        for key in ("source_problem_id", "family_id", "selection_tier"):
            value = selection.get(key)
            if isinstance(value, str) and value:
                assert json.dumps(value, ensure_ascii=False) not in user_prompt, (
                    f"Functional prompt leaked few-shot retrieval metadata: {key}"
                )


def _assert_no_few_shot_retrieval_metadata(value: Any) -> None:
    """Inspect prompt-facing examples structurally, not by semantic string value."""
    if isinstance(value, dict):
        forbidden = {
            "example_id",
            "source_problem_id",
            "family_id",
            "selection_tier",
        } & set(value)
        assert not forbidden, (
            "Functional few-shot payload leaked retrieval fields: "
            + ", ".join(sorted(forbidden))
        )
        for item in value.values():
            _assert_no_few_shot_retrieval_metadata(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_few_shot_retrieval_metadata(item)


def _max_attempts() -> int:
    return max(1, int(os.getenv("DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS", "3")))


def _attempt_llm_usage_is_recorded(
    debug_dir: Path,
    *,
    attempt_count: int,
) -> bool:
    if attempt_count < 1:
        return False
    for attempt in range(1, attempt_count + 1):
        metadata = _read_json(
            debug_dir / f"attempt-{attempt}.llm-metadata.json"
        )
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            return False
        if not any(isinstance(value, int) for value in usage.values()):
            return False
    return True


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
    gate_checks: Sequence[dict[str, Any]],
    gate_failures: Sequence[dict[str, Any]],
    closure_execution_count: int,
    closure_drift_count: int,
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
        "gate_checks": [dict(item) for item in gate_checks],
        "gate_failures": [dict(item) for item in gate_failures],
        "gates_passed": not gate_failures,
        "functional_symbolic_closure_mode": os.getenv(
            "FUNCTIONAL_SYMBOLIC_CLOSURE_MODE",
            "disabled",
        ),
        "symbolic_closure_execution_count": closure_execution_count,
        "symbolic_closure_drift_count": closure_drift_count,
    }
    path.mkdir(parents=True, exist_ok=True)
    (path / "sample-result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _record_gate(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    message: str,
) -> None:
    checks.append({"name": name, "ok": bool(ok), "message": message})


def _capture_assertion_gate(
    checks: list[dict[str, Any]],
    name: str,
    callback: Any,
) -> None:
    try:
        callback()
    except Exception as exc:
        _record_gate(checks, name, False, str(exc) or exc.__class__.__name__)
    else:
        _record_gate(checks, name, True, "")


def _read_json(path: Path) -> dict[str, Any]:
    payload = _read_json_value(path)
    assert isinstance(payload, dict), path
    return payload


def _read_json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def case_ids() -> Sequence[str]:
    return tuple(FUNCTIONAL_OPT_IN_CASES)
