from __future__ import annotations

from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.explanation.snapshot import (
    _build_symbolic_closure_teaching,
)
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.strategy_models import (
    StateWriteProvenance,
    SymbolicClosureProvenance,
)


def test_explanation_deduplicates_goal_reachable_symbolic_closure() -> None:
    target = MathObjectId("symbol:problem:b", "symbol", "problem")
    residual = MathObjectId("symbol:problem:c", "symbol", "problem")
    provenance = SymbolicClosureProvenance(
        status="unique",
        target_object_id=target,
        target_value="-c+1",
        substitutions=((target, "-c+1"),),
        residual_symbol_ids=(residual,),
        branch_count=1,
        equation_sources=("curve_point",),
        affected_returns=("parameter_value", "parabola"),
    )

    def write(return_name: str, runtime_type: str) -> StateWriteProvenance:
        return StateWriteProvenance(
            step_id="solve_b_step",
            scope_id="ii",
            capability_id="quadratic_from_constraints",
            produced_handle=f"fact:ii:{return_name}",
            output_key=return_name,
            runtime_type=runtime_type,
            identity_policy="target_object",
            identity_role="target",
            return_name=return_name,
            result_form="open_state",
                free_symbol_ids=(residual,),
                symbolic_closure_provenance=provenance,
                canonical_producer_call_id="solve_b",
            )

    replay = SimpleNamespace(
        transactional_attempt_result=SimpleNamespace(
            goal_reachable_call_ids=frozenset({"solve_b"}),
            state_writes=(
                write("parameter_value", "ParameterValue"),
                write("parabola", "Parabola"),
            ),
        ),
        functional_reconciliation=SimpleNamespace(
            execution_entries=(
                SimpleNamespace(
                    call_id="solve_b",
                    canonical_call_id="solve_b",
                ),
            ),
        ),
    )

    traces = _build_symbolic_closure_teaching(replay)

    assert len(traces) == 1
    assert traces[0].target == "b"
    assert traces[0].target_value == "1-c"
    assert traces[0].residual_symbols == ("c",)
    assert {item["return"] for item in traces[0].state_updates} == {
        "parameter_value",
        "parabola",
    }


def test_explanation_excludes_provisional_or_unreachable_closure() -> None:
    replay = SimpleNamespace(
        transactional_attempt_result=SimpleNamespace(
            goal_reachable_call_ids=frozenset(),
            state_writes=(),
        ),
        functional_reconciliation=SimpleNamespace(execution_entries=()),
    )

    assert _build_symbolic_closure_teaching(replay) == ()


def test_explanation_fails_loud_when_closure_write_has_no_call_mapping() -> None:
    target = MathObjectId("symbol:problem:b", "symbol", "problem")
    provenance = SymbolicClosureProvenance(
        status="unique",
        target_object_id=target,
        target_value="1",
        substitutions=((target, "1"),),
        branch_count=1,
        equation_sources=("curve_point",),
        affected_returns=("parameter_value",),
    )
    write = StateWriteProvenance(
        step_id="unmapped_step",
        scope_id="ii",
        capability_id="quadratic_from_constraints",
        produced_handle="answer:ii_b",
        output_key="parameter_value",
        runtime_type="ParameterValue",
        identity_policy="answer",
        identity_role="target",
        return_name="parameter_value",
        symbolic_closure_provenance=provenance,
    )
    replay = SimpleNamespace(
        transactional_attempt_result=SimpleNamespace(
            goal_reachable_call_ids=frozenset({"solve_b"}),
            state_writes=(write,),
        ),
        functional_reconciliation=SimpleNamespace(execution_entries=()),
    )

    with pytest.raises(
        ValueError,
        match="planner.symbolic_closure_explanation_projection_missing",
    ):
        _build_symbolic_closure_teaching(replay)
