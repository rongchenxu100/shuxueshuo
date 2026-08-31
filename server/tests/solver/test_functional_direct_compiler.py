from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

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
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionAdapterRegistry,
)
from shuxueshuo_server.solver.runtime.models import ContextDeclaration
from shuxueshuo_server.solver.runtime import recipe_compiler
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    FunctionalCapabilityCompiler,
)
from shuxueshuo_server.solver.runtime import (
    FunctionalCapabilityCompiler as PublicFunctionalCapabilityCompiler,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    write_strategy_debug_artifacts,
)

from test_functional_transaction_execution import _replay


_COMPILE_MANIFEST_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "functional_compile_manifests"
)

_RETIRED_QUADRATIC_INPUT_SELECTORS = frozenset(
    {
        "function:parabola",
        "read_type:Parabola",
        "symbol:x",
        "quadratic_coefficients",
        "parameter_symbol",
        "parameter_symbol_from_reads",
        "parameter_symbol_from_reads_or_expression",
        "known_parameter_symbol_from_reads",
    }
)


def _functional_compile_manifest(case_id: str) -> dict[str, object]:
    replay = _replay(case_id, mode="context_authoritative")
    report = replay.transactional_execution_report
    attempt = replay.transactional_attempt_result
    reconciliation = replay.functional_reconciliation
    assert report is not None
    assert attempt is not None
    assert reconciliation is not None
    capabilities = {
        call.call_id: call.capability_id for call in reconciliation.calls
    }
    writes_by_call: dict[str, list[object]] = {}
    for write in attempt.state_writes:
        writes_by_call.setdefault(write.step_id, []).append(write)
    calls: list[dict[str, object]] = []
    for compiled in report.compiled_calls:
        calls.append(
            {
                "call_id": compiled.call_id,
                "capability_id": capabilities[compiled.call_id],
                "steps": [
                    {
                        "step_id": plan.step_id,
                        "scope": plan.scope,
                        "invocations": [
                            {
                                "method_id": invocation.method_id,
                                "scope": invocation.scope,
                                "inputs": sorted(invocation.inputs),
                                "outputs": dict(sorted(invocation.outputs.items())),
                            }
                            for invocation in plan.invocations
                        ],
                        "promotions": dict(sorted(plan.promote_outputs.items())),
                    }
                    for plan in compiled.plans
                ],
                "bindings": [
                    {
                        "arg": decision["arg_name"],
                        "item": decision["item_index"],
                        "role": decision["semantic_role"],
                        "authority": decision["binding_authority"],
                        "target": decision["runtime_target"],
                        "paths": decision["actual_runtime_paths"],
                    }
                    for decision in compiled.binding_consumption_decisions
                ],
                "public_returns": [
                    {
                        "name": item.return_name,
                        "runtime_type": item.allocation.runtime_type,
                        "identity_policy": item.allocation.identity_policy,
                        "write_mode": item.allocation.write_mode,
                        "output_key": item.expected_write.output_key,
                        "required": item.required,
                    }
                    for item in compiled.public_returns
                ],
                "provenance": [
                    {
                        "return_name": write.return_name,
                        "runtime_type": write.runtime_type,
                        "allocation_action": write.allocation_action,
                        "result_form": write.result_form,
                        "object_id": (
                            write.math_object_id.value
                            if write.math_object_id is not None
                            else None
                        ),
                        "source_version_count": len(write.source_version_ids),
                        "closure_signature": (
                            repr(
                                write.symbolic_closure_provenance.semantic_signature()
                            )
                            if write.symbolic_closure_provenance is not None
                            else None
                        ),
                    }
                    for write in writes_by_call.get(compiled.call_id, ())
                ],
            }
        )
    return {
        "schema": "functional_compile_manifest/v1",
        "case_id": case_id,
        "calls": calls,
    }


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_direct_compiler_executes_without_drift(
    case_id: str,
) -> None:
    replay = _replay(
        case_id,
        mode="context_authoritative",
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
    )

    report = replay.transactional_execution_report
    assert report is not None
    assert report.functional_compile_count > 0
    assert report.functional_compile_drift_count == 0
    assert replay.output is not None, report.to_payload()


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_direct_compile_manifest_is_stable(case_id: str) -> None:
    expected = json.loads(
        (_COMPILE_MANIFEST_DIR / f"{case_id}.json").read_text(
            encoding="utf-8"
        )
    )

    assert _functional_compile_manifest(case_id) == expected


def test_recorded_strict_slices_have_no_legacy_selector_entrypoint() -> None:
    assert not hasattr(FunctionAdapterRegistry, "_select")
    assert not hasattr(FunctionAdapterRegistry, "_expand")
    for case_id in FUNCTIONAL_BATCH_CASES:
        replay = _replay(case_id, mode="context_authoritative")
        assert replay.output is not None


def test_recorded_typed_bindings_never_use_selector_read_authority() -> None:
    checked = 0

    for case_id in FUNCTIONAL_BATCH_CASES:
        replay = _replay(case_id, mode="context_authoritative")
        report = replay.transactional_execution_report
        assert report is not None
        for compiled in report.compiled_calls:
            invocations = {
                invocation.invocation_id: invocation
                for plan in compiled.plans
                for invocation in plan.invocations
            }
            for decision in compiled.binding_consumption_decisions:
                if decision["consumption_mode"] != "typed_binding":
                    continue
                target = decision["runtime_target"]
                input_name = target.rsplit(".", 1)[-1]
                for invocation_id in decision["invocation_ids"]:
                    authorities = invocations[
                        invocation_id
                    ].input_read_authorities[input_name]
                    assert all(
                        authority.source.kind != "compiler_selector"
                        for authority in authorities
                    )
                    checked += 1

    assert checked >= 20


def test_quadratic_template_binding_audit_uses_stamped_invocation() -> None:
    replay = _replay("nankai", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "i_derive_parabola"
    )
    invocation = compiled.plans[0].invocations[0]
    decision = next(
        item
        for item in compiled.binding_consumption_decisions
        if item["arg_name"] == "quadratic_template"
    )

    assert decision["matches"] is True
    assert decision["actual_runtime_paths"] == [
        invocation.inputs["quadratic_template"]
    ]
    assert decision["invocation_ids"] == [invocation.invocation_id]


def test_direct_compiler_does_not_import_step_intent_bridge() -> None:
    source = inspect.getsource(FunctionalDirectCompiler)

    assert "StepIntent" not in source
    assert "FunctionalPlanProjector" not in source
    assert "CanonicalDraftFinalizer" not in source
    assert "StepIntentCandidateResolver" not in source
    assert "compile_exact_step" not in source


def test_curve_candidate_recipe_does_not_supply_code_owned_template() -> None:
    source = inspect.getsource(
        recipe_compiler._RecipePlanCompiler._compile_curve_candidate_parameter_recipe
    )

    assert '"quadratic_template"' not in source


def test_functional_capability_compiler_has_public_runtime_export() -> None:
    assert PublicFunctionalCapabilityCompiler is FunctionalCapabilityCompiler


def test_transactional_compiler_has_one_direct_path() -> None:
    source = inspect.getsource(FunctionalCallCompilerService.compile)

    assert "compile_mode" not in source
    assert "_compile_direct" in source


def test_direct_authoritative_has_no_step_intent_validation() -> None:
    replay = _replay(
        "nankai",
        mode="context_authoritative",
    )

    assert replay.output is not None
    assert "raw_draft" not in replay.to_payload()
    assert "effective_draft" not in replay.to_payload()
    assert replay.functional_reconciliation is not None
    assert replay.functional_reconciliation.execution_entries


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
        "RecipeTrialExecutor",
    }
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert imported.isdisjoint(banned)


def test_retired_exact_step_bridge_is_not_exposed() -> None:
    assert not hasattr(recipe_compiler, "RecipeTrialExecutor")


def test_direct_authoritative_explanation_uses_canonical_compiled_calls() -> None:
    replay = _replay(
        "nankai",
        mode="context_authoritative",
    )
    attempt = replay.transactional_attempt_result
    assert attempt is not None
    assert replay.output is not None

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
    )

    write_strategy_debug_artifacts(
        tmp_path,
        payload={
            "planner_protocol": "functional_plan/v1",
            "output_json_schema": {},
        },
        prompt=type("Prompt", (), {"system": "", "user": ""})(),
        raw_response="{}",
        report=replay.functional_validation_report,
        functional_plan=replay.functional_plan,
        functional_reconciliation=replay.functional_reconciliation,
    )

    assert not (tmp_path / "parsed-step-intents.json").exists()
    assert not (tmp_path / "effective-step-intents.json").exists()


def test_per_call_compiler_never_receives_future_state_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = FunctionalCapabilityCompiler.compile
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
        FunctionalCapabilityCompiler,
        "compile",
        capture,
    )

    replay = _replay(
        "nankai",
        mode="context_authoritative",
    )

    assert replay.output is not None
    assert observed
