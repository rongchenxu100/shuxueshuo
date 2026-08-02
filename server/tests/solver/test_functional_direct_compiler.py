from __future__ import annotations

import ast
import inspect

import pytest

from shuxueshuo_server.solver.runtime import (
    functional_transaction_execution as transaction_execution,
)
from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.explanation.presentation import (
    transactional_functional_steps,
)
from shuxueshuo_server.solver.runtime.functional_direct_compiler import (
    FunctionalDirectCompiler,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    CompiledFunctionalCall,
    FunctionalCallCompilerService,
    _classified_direct_compile_error,
    _compiled_call_signature,
)
from shuxueshuo_server.solver.runtime.models import ContextDeclaration
from shuxueshuo_server.solver.runtime.recipe_compiler import RecipeTrialExecutor
from shuxueshuo_server.solver.runtime.strategy_validator import (
    StepIntentValidator,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    write_strategy_debug_artifacts,
)

from test_functional_transaction_execution import _replay


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_direct_shadow_has_zero_compile_drift(
    case_id: str,
) -> None:
    replay = _replay(
        case_id,
        mode="context_authoritative",
        compile_mode="direct_shadow",
    )

    report = replay.transactional_execution_report
    assert report is not None
    assert report.functional_compile_count > 0
    assert report.functional_compile_drift_count == 0, report.to_payload()


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_direct_authoritative_executes_without_projection(
    case_id: str,
) -> None:
    replay = _replay(
        case_id,
        mode="context_authoritative",
        compile_mode="direct_authoritative",
    )

    report = replay.transactional_execution_report
    assert report is not None
    assert report.functional_compile_count > 0
    assert report.functional_compile_drift_count == 0
    assert replay.output is not None, report.to_payload()


def test_direct_compiler_does_not_import_step_intent_bridge() -> None:
    source = inspect.getsource(FunctionalDirectCompiler)

    assert "StepIntent" not in source
    assert "FunctionalPlanProjector" not in source
    assert "CanonicalDraftFinalizer" not in source
    assert "StepIntentCandidateResolver" not in source
    assert "compile_exact_step" not in source


def test_transactional_compiler_exposes_explicit_direct_modes() -> None:
    source = inspect.getsource(FunctionalCallCompilerService.compile)

    assert 'compile_mode == "direct_authoritative"' in source
    assert 'compile_mode == "projected"' in source
    assert "planner.functional_compile_drift" in source


def test_direct_authoritative_bypasses_step_intent_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("StepIntent validation reached direct authority")

    monkeypatch.setattr(
        StepIntentValidator,
        "validate_json_with_report",
        fail_if_called,
    )

    replay = _replay(
        "nankai",
        mode="context_authoritative",
        compile_mode="direct_authoritative",
    )

    assert replay.output is not None
    assert replay.raw_draft is None
    assert replay.effective_draft is None
    assert replay.functional_reconciliation is not None
    assert replay.functional_reconciliation.projected_draft is None
    assert replay.functional_reconciliation.projection_map


def test_direct_compiler_import_guard() -> None:
    module = inspect.getmodule(FunctionalDirectCompiler)
    assert module is not None
    tree = ast.parse(inspect.getsource(module))
    banned = {
        "StepIntentDraft",
        "FunctionalPlanProjector",
        "FunctionalLegacyProjectionAdapter",
        "StepIntentCandidateResolver",
        "CanonicalDraftFinalizer",
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert imported.isdisjoint(banned)


def test_retired_exact_step_bridge_is_not_exposed() -> None:
    assert not hasattr(RecipeTrialExecutor, "compile_exact_step")


def test_direct_authoritative_explanation_uses_canonical_compiled_calls() -> None:
    replay = _replay(
        "nankai",
        mode="context_authoritative",
        compile_mode="direct_authoritative",
    )
    attempt = replay.transactional_attempt_result
    assert attempt is not None
    assert replay.output is not None
    assert replay.effective_draft is None

    steps = transactional_functional_steps(replay, replay.output)
    expected_ids = tuple(
        plan.step_id
        for plan in replay.output.step_plans
        if plan.step_id in attempt.goal_reachable_call_ids
    )

    assert tuple(step["step_id"] for step in steps) == expected_ids
    assert all(step["strategy"] == "" for step in steps)
    assert all(step["reason"] == "" for step in steps)
    assert any(step["reads"] for step in steps)


def test_compile_shadow_signature_uses_context_declaration_type() -> None:
    compiled = CompiledFunctionalCall(
        call_id="derive",
        step_ids=(),
        declarations=(
            ContextDeclaration(
                path="$problem.object_refs.P",
                type="PointRef",
                name="P",
                definition={},
                scope_id="problem",
            ),
        ),
        plans=(),
        public_returns=(),
    )

    signature = _compiled_call_signature(compiled)

    assert signature[1] == (("$problem.object_refs.P", "PointRef"),)


def test_direct_compile_preserves_retryable_functional_arg_error() -> None:
    original = ValueError(
        "functional.arg_identity_mismatch: no matching parameter identity"
    )

    classified = _classified_direct_compile_error("evaluate_point", original)

    assert classified is original
    assert "planner_configuration_error" not in str(classified)


def test_direct_functional_debug_does_not_emit_step_intent_artifact(
    tmp_path,
) -> None:
    replay = _replay(
        "nankai",
        mode="context_authoritative",
        compile_mode="direct_authoritative",
    )

    write_strategy_debug_artifacts(
        tmp_path,
        payload={
            "planner_output_format": "functional_plan",
            "output_json_schema": {},
        },
        prompt=type("Prompt", (), {"system": "", "user": ""})(),
        raw_response="{}",
        draft=replay.raw_draft,
        report=replay.functional_validation_report,
        effective_draft=replay.effective_draft,
        functional_plan=replay.functional_plan,
        functional_reconciliation=replay.functional_reconciliation,
    )

    assert not (tmp_path / "parsed-step-intents.json").exists()
    assert not (tmp_path / "effective-step-intents.json").exists()


def test_per_call_compiler_never_receives_future_state_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RecipeTrialExecutor.compile_functional_call
    observed: list[tuple[str, tuple[str, ...]]] = []
    compiled_prefix: set[str] = set()

    def capture(self, step, **kwargs):
        write_step_ids = tuple(
            item.step_id for item in kwargs.get("state_writes", ())
        )
        observed.append((step.step_id, write_step_ids))
        available = {*compiled_prefix, step.step_id}
        assert set(write_step_ids) <= available
        assert {
            item.step_id
            for item in kwargs.get("state_dependencies", ())
        } <= available
        assert {
            item.step_id for item in kwargs.get("arg_bindings", ())
        } <= available
        result = original(self, step, **kwargs)
        compiled_prefix.add(step.step_id)
        return result

    monkeypatch.setattr(
        RecipeTrialExecutor,
        "compile_functional_call",
        capture,
    )

    replay = _replay(
        "nankai",
        mode="context_authoritative",
        compile_mode="direct_authoritative",
    )

    assert replay.output is not None
    assert observed


def test_direct_shadow_compile_drift_blocks_transactional_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = transaction_execution._compiled_call_signature
    calls = 0

    def divergent_signature(compiled):
        nonlocal calls
        calls += 1
        path = "projected" if calls % 2 else "direct"
        return (*original(compiled), ("synthetic_path", path))

    monkeypatch.setattr(
        transaction_execution,
        "_compiled_call_signature",
        divergent_signature,
    )

    replay = _replay(
        "nankai",
        mode="context_authoritative",
        compile_mode="direct_shadow",
    )

    report = replay.transactional_execution_report
    assert report is not None
    assert report.functional_compile_drift_count > 0
    assert replay.output is None
    assert replay.retry_state is not None
