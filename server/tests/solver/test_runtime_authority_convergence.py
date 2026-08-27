from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    diagnostic_authority_from_issue,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    _symbolic_closure_drift_details,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import CallResultRef
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    StateVersionReadSource,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    SymbolicClosureExecutionResult,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = REPO_ROOT / "server/shuxueshuo_server/solver/runtime"


def _execute(
    tmp_path,
    case="tj-2026-heping-yimo-25",
    payload=None,
):
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    result = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(
            payload if payload is not None else load_v2_fixture_payload(case),
            ensure_ascii=False,
        ),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )
    assert result.checkpoint is not None
    assert result.replay.transactional_execution_report is not None
    return result


def test_named_entity_wire_remains_source_ref_while_typed_graph_pins_producer(
    tmp_path,
) -> None:
    result = _execute(tmp_path)
    authority = result.authority
    assert authority is not None
    consumer = next(
        item
        for item in authority.lowered_plan.calls
        if item.call_id == "derive_x_intercept_B_ii"
    )
    parabola_ref = consumer.args["parabola"][0]
    pin = authority.lowered_plan.typed_input_source_pins[
        ("derive_x_intercept_B_ii", "parabola", 0)
    ]

    assert not isinstance(parabola_ref, CallResultRef)
    assert parabola_ref.ref == "parabola"
    assert pin.semantic_ref == "parabola"
    assert pin.producer_call_id == "derive_parametric_parabola_ii"


def test_macro_winner_finalizes_f5c_before_provenance_is_created(tmp_path) -> None:
    result = _execute(tmp_path)
    report = result.replay.transactional_execution_report
    assert report is not None
    ledger = report.functional_problem_binding_ledger
    assert ledger is not None
    binding = ledger.call_binding("reduce_equal_length_ray_path_ii")

    assert binding.status == "finalized"
    assert dict(binding.authored_roles) == {}
    assert dict(binding.chosen_roles) == {
        "anchor": "point:problem:C",
        "fixed_point": "point:problem:O",
        "ray_point": "point:problem:D",
        "reference_point": "point:problem:B",
    }
    by_arg = {
        item.arg_name: item.semantic_ref.ref
        for item in binding.input_bindings
        if item.semantic_ref is not None
    }
    assert by_arg["anchor"] == "C"
    assert by_arg["fixed_point"] == "O"
    assert by_arg["ray_point"] == "D"
    assert by_arg["reference_point"] == "B"
    provenance = binding.source_provenance()
    assert provenance.call_binding_signature == binding.binding_signature
    assert provenance.macro_search_signature == binding.macro_search_signature
    assert provenance.macro_role_resolutions == (
        ("anchor", None, "point:problem:C"),
        ("fixed_point", None, "point:problem:O"),
        ("ray_point", None, "point:problem:D"),
        ("reference_point", None, "point:problem:B"),
    )


def test_scope_native_production_has_one_goal_checkpoint_owner() -> None:
    scope_native_modules = (
        "functional_goal_execution.py",
        "functional_scope_retry.py",
        "scoped_functional_plan_replay.py",
    )
    forbidden = (
        "FunctionalRetryGraphCheckpoint",
        "functional_retry_graph_checkpoint",
        "functional_plan_retry",
    )

    for filename in scope_native_modules:
        source = (RUNTIME_ROOT / filename).read_text(encoding="utf-8")
        assert all(item not in source for item in forbidden), filename


def test_removed_post_hoc_and_legacy_authority_paths_do_not_return() -> None:
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in RUNTIME_ROOT.glob("*.py")
    }
    joined = "\n".join(sources.values())

    assert "runtime_verified_macro_report" not in joined
    assert "with_macro_search" not in joined
    assert "extends_base_authority" not in joined
    assert "_equal_length_ray_roles_from_legacy_problem_fact_names" not in joined
    assert "_equal_length_ray_roles_from_structured_problem_facts" not in joined
    assert "if macro_id == \"equal_length_ray_path_reduction\"" not in joined
    assert "if macro.macro_id == \"equal_length_ray_path_reduction\"" not in joined
    transaction = sources["functional_transaction_execution.py"]
    assert "_macro_candidate_builder_context" not in transaction
    assert "_build_equal_length_ray_execution_witness" not in transaction
    assert "builder=_build_equal_length" not in transaction
    recipe_compiler = sources["recipe_compiler.py"]
    assert "build_equal_length_ray_role_candidates" not in recipe_compiler
    macro_preparation = sources["macro_preparation.py"]
    assert "call_count=2" not in macro_preparation.replace(" ", "")


def test_runtime_contracts_do_not_import_macro_search_types_from_family_layer() -> None:
    for filename in ("macro_runtime_search.py", "macro_preparation.py"):
        source = (RUNTIME_ROOT / filename).read_text(encoding="utf-8")
        assert "family.models import" not in source
        assert "from shuxueshuo_server.solver.contracts import" in source


def test_compiler_selected_identity_never_uses_runtime_path_as_entity_handle(
    tmp_path,
) -> None:
    result = _execute(tmp_path)
    report = result.replay.transactional_execution_report
    assert report is not None

    for compiled in report.compiled_calls:
        for plan in compiled.plans:
            for invocation in plan.invocations:
                for authorities in invocation.input_read_authorities.values():
                    for authority in authorities:
                        source = authority.source
                        entity_handle = getattr(source, "entity_handle", "")
                        assert not entity_handle.startswith("$")


def test_compiler_projection_path_keeps_exact_function_state_authority(
    tmp_path,
) -> None:
    result = _execute(tmp_path)
    report = result.replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "derive_y_intercept_C_i"
    )
    invocation = compiled.plans[0].invocations[0]
    authority = invocation.input_read_authorities["quadratic"][0]

    assert authority.view_mode == "latest_state"
    assert isinstance(authority.source, StateVersionReadSource)
    assert "__functional_transaction_" in authority.runtime_path
    assert (
        authority.source.state_version_id.slot_id.logical_key.object_id.value
        == "function:problem:parabola"
    )


def test_polynomial_closure_pins_ordinal_zero_template_authority(
    tmp_path,
) -> None:
    result = _execute(tmp_path)
    report = result.replay.transactional_execution_report
    assert report is not None

    checked = 0
    for compiled in report.compiled_calls:
        for plan in compiled.plans:
            for invocation in plan.invocations:
                if invocation.method_id not in {
                    "quadratic_from_constraints",
                    "parameter_from_curve_point_on_quadratic",
                }:
                    continue
                template = invocation.input_read_authorities[
                    "quadratic_template"
                ][0]
                quadratic = invocation.input_read_authorities["quadratic"][0]
                assert isinstance(template.source, StateVersionReadSource)
                assert template.source.state_version_id.ordinal == 0
                assert isinstance(quadratic.source, StateVersionReadSource)
                assert (
                    template.source.state_version_id.slot_id.logical_key.object_id
                    == quadratic.source.state_version_id.slot_id.logical_key.object_id
                )
                checked += 1

    assert checked >= 2


def test_polynomial_template_drift_diagnostic_preserves_missing_coefficient() -> None:
    x, a, b = sp.symbols("x a b")
    details = _symbolic_closure_drift_details(
        SymbolicClosureExecutionResult(
            status="unique",
            validation_args={
                "quadratic_template": a * x**2 + b * x - 3,
                "quadratic": a * x**2 + (a - 3) * x - 3,
            },
        ),
        ("renamed_structured_coefficient_check",),
    )
    authority = diagnostic_authority_from_issue(
        {
            "code": "planner.contract_runtime_symbol_drift",
            "message": "rewritten outputs violate closure",
            "details": details,
        },
        stage="transaction",
        method_id="quadratic_from_constraints",
        step_id="close_parabola",
    )

    assert details == {
        "expected_template": "a*x**2 + b*x - 3",
        "observed_state": "a*x**2 + x*(a - 3) - 3",
        "missing_symbol_roles": ["b"],
        "missing_symbol_role": "b",
        "failed_checks": ["renamed_structured_coefficient_check"],
        "subjects": [
            {
                "role": "coefficient_identity_template",
                "arg_name": "quadratic_template",
                "expected_type": "Expression",
                "expected_state": "ordinal_0",
                "observed_type": "Add",
                "observed_state": "coefficient_identity_incomplete",
            }
        ],
    }
    assert authority.expected["expected_template"] == (
        "a*x**2 + b*x - 3"
    )
    assert authority.observed["observed_state"] == (
        "a*x**2 + x*(a - 3) - 3"
    )
    assert authority.observed["missing_symbol_role"] == "b"


@pytest.mark.parametrize("incremental", [False, True])
def test_heping_quadratic_closure_supports_full_and_incremental_constraints(
    tmp_path,
    incremental,
) -> None:
    payload = deepcopy(load_v2_fixture_payload("tj-2026-heping-yimo-25"))
    scope_i = next(
        item
        for item in payload["root_scope"]["children"]
        if item["scope_ref"] == "i"
    )
    if incremental:
        close_step = scope_i["steps"][0]
        open_step = deepcopy(close_step)
        open_step["step_id"] = "derive_open_parabola_common"
        open_step["args"] = {
            "curve_point": "A",
            "free_parameters": "a",
        }
        open_step["intent"] = "Use the root-visible curve point to build the open state."
        payload["root_scope"]["steps"].append(open_step)
        close_step["args"] = {"curve_point": "D"}
        close_step["intent"] = "Use the scope-local relation to close the state."

    result = _execute(tmp_path, payload=payload)
    attempt = result.replay.transactional_attempt_result
    assert attempt is not None
    assert all(item.status == "passed" for item in attempt.goal_report.goals)
    answers = {
        item.produced_handle: item.value
        for item in attempt.runtime_results
        if item.produced_handle.startswith("answer:")
    }
    assert sp.expand(
        sp.sympify(answers["answer:i_1.parabola"])
        - (sp.Symbol("x") ** 2 - 2 * sp.Symbol("x") - 3)
    ) == 0
    assert sp.sympify(answers["answer:ii.a"]) == sp.Rational(3, 4)

    pin = result.authority.lowered_plan.typed_input_source_pins[
        ("derive_x_intercept_B_i", "parabola", 0)
    ]
    assert pin.producer_call_id == "derive_parabola_i"
