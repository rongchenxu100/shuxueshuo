from __future__ import annotations

from pathlib import Path

import pytest

from shuxueshuo_server.solver import load_problem_ir
from shuxueshuo_server.solver.runtime.answer_goal_verifier import (
    AnswerGoalVerifier,
    FunctionalGoalVerificationContext,
    _state_write_lineage,
    _typed_runtime_symbol_object_ids,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
    RuntimeStateVersionBinding,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    FunctionalExecutionDiagnostic,
    StateWriteProvenance,
    StrategyDraftValidationError,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
NANKAI_FIXTURE = REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
def test_typed_goal_lineage_uses_answer_consumer_scope() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    index = FunctionalStateReadIndex(
        handle_registry=registry,
        mode="authoritative",
    )
    source_object = MathObjectId(
        "point:ii_1:source",
        "point",
        "ii_1",
    )
    source_key = LogicalStateKey(
        source_object,
        "coordinate",
        "Point",
    )
    source_version = StateVersionId(
        StateSlotId(source_key, "ii_1"),
        1,
    )
    answer_object = MathObjectId(
        "point:ii_2:answer",
        "point",
        "ii_2",
    )
    answer_key = LogicalStateKey(
        answer_object,
        "coordinate",
        "Point",
    )
    answer_version = StateVersionId(
        StateSlotId(answer_key, "ii_2"),
        1,
    )
    index.register(
        RuntimeStateVersionBinding(
            source_version,
            source_key,
            source_object,
            "Point",
            "ii_1",
            "produce_source",
            None,
            "fact:ii_1:source",
        )
    )
    index.register(
        RuntimeStateVersionBinding(
            answer_version,
            answer_key,
            answer_object,
            "Point",
            "ii_2",
            "produce_answer",
            None,
            "answer:ii_2.answer",
            source_version_ids=(source_version,),
        )
    )
    source_write = StateWriteProvenance(
        step_id="produce_source",
        scope_id="ii_1",
        capability_id="synthetic_source",
        produced_handle="fact:ii_1:source",
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        math_object_id=source_object,
        logical_state_key=source_key,
        typed_slot_id=source_version.slot_id,
        selected_version_id=source_version,
    )
    answer_write = StateWriteProvenance(
        step_id="produce_answer",
        scope_id="ii_2",
        capability_id="synthetic_answer",
        produced_handle="answer:ii_2.answer",
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        math_object_id=answer_object,
        logical_state_key=answer_key,
        typed_slot_id=answer_version.slot_id,
        selected_version_id=answer_version,
        source_version_ids=(source_version,),
    )
    diagnostic = FunctionalExecutionDiagnostic(
        ok=True,
        state_write_provenance=(source_write, answer_write),
    )
    functional_context = FunctionalGoalVerificationContext(
        logical_graph=None,
        state_read_index=index,
        runtime_writes_by_version={
            source_version: source_write,
            answer_version: answer_write,
        },
        answer_version_ids={
            "answer:ii_2.answer": answer_version,
        },
        verified_call_ids=frozenset(
            {"produce_source", "produce_answer"}
        ),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_visibility_drift",
    ):
        _state_write_lineage(
            answer_write,
            diagnostic=diagnostic,
            functional_context=functional_context,
            consumer_scope_id="ii_2",
        )


def test_typed_runtime_symbol_identity_follows_answer_version_lineage() -> None:
    _payload, registry = _nankai_problem_payload_and_registry()
    index = FunctionalStateReadIndex(
        handle_registry=registry,
        mode="authoritative",
    )
    answer_object = MathObjectId("point:ii:E", "point", "ii")
    answer_key = LogicalStateKey(answer_object, "coordinate", "Point")
    answer_version = StateVersionId(StateSlotId(answer_key, "ii"), 1)
    expected_symbol = MathObjectId(
        "symbol:ii:E_axis_parameter",
        "symbol",
        "ii",
    )
    expected_symbol_key = LogicalStateKey(
        expected_symbol,
        "parameter",
        "Symbol",
    )
    expected_symbol_version = StateVersionId(
        StateSlotId(expected_symbol_key, "ii"),
        1,
    )
    unrelated_symbol = MathObjectId(
        "symbol:i_2:E_axis_parameter",
        "symbol",
        "i_2",
    )
    unrelated_symbol_key = LogicalStateKey(
        unrelated_symbol,
        "parameter",
        "Symbol",
    )
    unrelated_symbol_version = StateVersionId(
        StateSlotId(unrelated_symbol_key, "i_2"),
        1,
    )
    for binding in (
        RuntimeStateVersionBinding(
            expected_symbol_version,
            expected_symbol_key,
            expected_symbol,
            "Symbol",
            "ii",
            "parameterize_answer",
            None,
            "fact:ii:axis_parameter",
        ),
        RuntimeStateVersionBinding(
            unrelated_symbol_version,
            unrelated_symbol_key,
            unrelated_symbol,
            "Symbol",
            "i_2",
            "parameterize_other_point",
            None,
            "fact:i_2:axis_parameter",
        ),
        RuntimeStateVersionBinding(
            answer_version,
            answer_key,
            answer_object,
            "Point",
            "ii",
            "parameterize_answer",
            None,
            "answer:ii.E",
            source_version_ids=(expected_symbol_version,),
        ),
    ):
        index.register(binding)
    provenance = tuple(
        StateWriteProvenance(
            step_id=step_id,
            scope_id=scope_id,
            capability_id="quadratic_axis_parameterized_point",
            produced_handle=handle,
            output_key="parameter",
            runtime_type="Symbol",
            identity_policy="derived_role",
            identity_role="axis_parameter",
            object_ref=object_id.value,
            free_symbol_names=("_axis_param_E",),
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=version_id.slot_id,
            selected_version_id=version_id,
        )
        for (
            step_id,
            scope_id,
            handle,
            object_id,
            logical_key,
            version_id,
        ) in (
            (
                "parameterize_answer",
                "ii",
                "fact:ii:axis_parameter",
                expected_symbol,
                expected_symbol_key,
                expected_symbol_version,
            ),
            (
                "parameterize_other_point",
                "i_2",
                "fact:i_2:axis_parameter",
                unrelated_symbol,
                unrelated_symbol_key,
                unrelated_symbol_version,
            ),
        )
    )
    context = FunctionalGoalVerificationContext(
        logical_graph=None,
        state_read_index=index,
        runtime_writes_by_version={},
        answer_version_ids={"answer:ii.E": answer_version},
        verified_call_ids=frozenset(),
    )

    resolved = _typed_runtime_symbol_object_ids(
        "_axis_param_E",
        answer_write=StateWriteProvenance(
            step_id="parameterize_answer",
            scope_id="ii",
            capability_id="quadratic_axis_parameterized_point",
            produced_handle="answer:ii.E",
            output_key="point",
            runtime_type="Point",
            identity_policy="target_object",
            identity_role="axis_point",
            selected_version_id=answer_version,
        ),
        goal_handle="answer:ii.E",
        functional_context=context,
        provenance=provenance,
    )

    assert resolved == (expected_symbol,)


def test_typed_runtime_symbol_lineage_rejects_missing_version_binding() -> None:
    _payload, registry = _nankai_problem_payload_and_registry()
    index = FunctionalStateReadIndex(
        handle_registry=registry,
        mode="authoritative",
    )
    answer_object = MathObjectId("point:ii:E", "point", "ii")
    answer_key = LogicalStateKey(answer_object, "coordinate", "Point")
    answer_version = StateVersionId(StateSlotId(answer_key, "ii"), 1)
    missing_symbol = MathObjectId(
        "symbol:ii:axis_parameter",
        "symbol",
        "ii",
    )
    missing_key = LogicalStateKey(
        missing_symbol,
        "parameter",
        "Symbol",
    )
    missing_version = StateVersionId(
        StateSlotId(missing_key, "ii"),
        1,
    )
    index.register(
        RuntimeStateVersionBinding(
            answer_version,
            answer_key,
            answer_object,
            "Point",
            "ii",
            "parameterize_answer",
            None,
            "answer:ii.E",
            source_version_ids=(missing_version,),
        )
    )
    context = FunctionalGoalVerificationContext(
        logical_graph=None,
        state_read_index=index,
        runtime_writes_by_version={},
        answer_version_ids={"answer:ii.E": answer_version},
        verified_call_ids=frozenset(),
    )

    with pytest.raises(
        Exception,
        match="planner.runtime_state_version_unresolved",
    ):
        _typed_runtime_symbol_object_ids(
            "_axis_param_E",
            answer_write=StateWriteProvenance(
                step_id="parameterize_answer",
                scope_id="ii",
                capability_id="quadratic_axis_parameterized_point",
                produced_handle="answer:ii.E",
                output_key="point",
                runtime_type="Point",
                identity_policy="target_object",
                identity_role="axis_point",
                selected_version_id=answer_version,
            ),
            goal_handle="answer:ii.E",
            functional_context=context,
            provenance=(),
        )




def _nankai_problem_payload_and_registry() -> tuple[dict, CanonicalHandleRegistry]:
    problem = load_problem_ir(NANKAI_FIXTURE)
    payload = problem_to_llm_payload(problem)
    return payload, CanonicalHandleRegistry.from_problem_payload(payload)
