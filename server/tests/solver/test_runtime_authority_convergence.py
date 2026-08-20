from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import CallResultRef
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    StateVersionReadSource,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = REPO_ROOT / "server/shuxueshuo_server/solver/runtime"


def _execute(tmp_path, case="tj-2026-heping-yimo-25"):
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    result = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(load_v2_fixture_payload(case), ensure_ascii=False),
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
        "functional_goal_retry.py",
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
