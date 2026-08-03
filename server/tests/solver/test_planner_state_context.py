from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)

from shuxueshuo_server.solver.runtime.planner_state_context import (  # noqa: E402
    ContextManifest,
    PlannerStateContextBuilder,
    PlannerState,
    PlannerStateContext,
    ScopeGraph,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime import (  # noqa: E402
    planner_state_context as planner_state_context_module,
)
from shuxueshuo_server.solver.runtime.state_identity import (  # noqa: E402
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (  # noqa: E402
    SymbolicClosureProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem

NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


def _nankai_problem():
    return load_problem_ir(NANKAI_FIXTURE)


def _nankai_llm_problem() -> dict[str, Any]:
    return problem_to_llm_payload(_nankai_problem())


def _registry() -> CanonicalHandleRegistry:
    return CanonicalHandleRegistry.from_problem_payload(_nankai_llm_problem())


def _nankai_inputs():
    return build_strategy_probe_inputs(_nankai_problem())


def test_context_semantic_read_catalog_carries_typed_identity() -> None:
    object_id = MathObjectId(
        "point:problem:D",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(
        object_id,
        "coordinate",
        "Point",
    )
    version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    item = SemanticReadCatalogItem(
        handle="fact:problem:D_coordinate",
        kind="fact",
        ref="D_coordinate",
        scope="problem",
        valid_scope="problem",
        value_type="Point",
        math_object_id=object_id,
        state_version_id=version_id,
    )
    assert item.math_object_id == object_id
    assert item.state_version_id == version_id
    assert "math_object_id" not in item.to_prompt_payload()


@pytest.mark.parametrize(
    "missing_field",
    ("canonical_producer_call_id", "valid_scope_id"),
)
def test_typed_provenance_identity_enrichment_is_fail_closed(
    missing_field: str,
) -> None:
    object_id = MathObjectId("point:problem:P", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    payload = {
        "state_slot_id": "point:problem:P.coordinate@problem:Point",
        "object_ref": "point:problem:P",
        "produced_handle": "point:problem:P",
        "runtime_type": "Point",
        "selected_version_id": version_id.to_payload(),
        "canonical_producer_call_id": "construct_P",
        "valid_scope_id": "problem",
    }
    payload.pop(missing_field)

    with pytest.raises(
        StrategyDraftValidationError,
        match=(
            "planner.retry_version_checkpoint_invalid.*"
            f"{missing_field}"
        ),
    ):
        planner_state_context_module._apply_state_write_provenance(
            None,
            payload,
        )


def _symbolic_closure_write_payload(
    *,
    closure_target: MathObjectId | None = None,
    status: str = "unique",
    free_symbol_ids: tuple[MathObjectId, ...] = (),
    residual_symbol_ids: tuple[MathObjectId, ...] = (),
) -> dict[str, Any]:
    target = MathObjectId("symbol:problem:a", "symbol", "problem")
    logical_key = LogicalStateKey(target, "value", "ParameterValue")
    slot_id = StateSlotId(logical_key, "problem")
    version_id = StateVersionId(slot_id, 1)
    provenance = SymbolicClosureProvenance(
        status=status,
        target_object_id=closure_target or target,
        target_value="1",
        substitutions=((closure_target or target, "1"),),
        residual_symbol_ids=residual_symbol_ids,
        branch_count=1 if status == "unique" else 2,
        equation_builder="expression_equals_value",
        target_binding="parameter",
        affected_returns=("parameter_value",),
    )
    return {
        "step_id": "solve_a",
        "scope_id": "problem",
        "capability_id": "parameter_from_expression_value",
        "produced_handle": "fact:problem:a_value",
        "output_key": "parameter_value",
        "runtime_type": "ParameterValue",
        "state_slot_id": "symbol:problem:a.value@problem:ParameterValue",
        "object_ref": "symbol:problem:a",
        "write_mode": "create",
        "math_object_id": target.to_payload(),
        "logical_state_key": logical_key.to_payload(),
        "typed_slot_id": slot_id.to_payload(),
        "selected_version_id": version_id.to_payload(),
        "canonical_producer_call_id": "solve_a",
        "valid_scope_id": "problem",
        "return_name": "parameter_value",
        "free_symbol_names": [item.value for item in free_symbol_ids],
        "free_symbol_ids": [item.to_payload() for item in free_symbol_ids],
        "symbolic_closure_provenance": provenance.to_payload(),
    }


def _mutable_nankai_state() -> Any:
    return PlannerStateContextBuilder._initial_mutable_state(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
        attempt=1,
        parent_context_id=None,
    )


def test_context_hydrate_rejects_closure_target_identity_drift() -> None:
    other = MathObjectId("symbol:problem:b", "symbol", "problem")

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.contract_runtime_symbol_drift",
    ):
        planner_state_context_module._apply_state_write_provenance(
            _mutable_nankai_state(),
            _symbolic_closure_write_payload(closure_target=other),
            require_typed_authority=True,
        )


def test_context_hydrate_rejects_non_unique_closure_provenance() -> None:
    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.symbolic_closure_provenance_drift",
    ):
        planner_state_context_module._apply_state_write_provenance(
            _mutable_nankai_state(),
            _symbolic_closure_write_payload(status="ambiguous"),
            require_typed_authority=True,
        )


def test_context_hydrate_rejects_closure_residual_symbol_drift() -> None:
    residual = MathObjectId("symbol:problem:c", "symbol", "problem")

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.symbolic_closure_provenance_drift",
    ):
        planner_state_context_module._apply_state_write_provenance(
            _mutable_nankai_state(),
            _symbolic_closure_write_payload(
                free_symbol_ids=(residual,),
                residual_symbol_ids=(),
            ),
            require_typed_authority=True,
        )


def test_closure_index_rejects_duplicate_state_version_records() -> None:
    target = MathObjectId("symbol:problem:a", "symbol", "problem")
    logical_key = LogicalStateKey(target, "value", "ParameterValue")
    version_id = StateVersionId(StateSlotId(logical_key, "problem"), 1)
    provenance = SymbolicClosureProvenance(
        status="unique",
        target_object_id=target,
        target_value="1",
        substitutions=((target, "1"),),
        branch_count=1,
        affected_returns=("parameter_value",),
    )
    write = SimpleNamespace(
        version_id=version_id,
        symbolic_closure_provenance=provenance,
    )
    context = SimpleNamespace(
        state=SimpleNamespace(
            state_slots=(SimpleNamespace(write_history=(write, write)),)
        )
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.symbolic_closure_provenance_drift",
    ):
        PlannerStateContext.closure_by_version.fget(context)
from shuxueshuo_server.solver.runtime.strategy_replay import (  # noqa: E402
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
    _planner_state_context_from_replay,
)


def test_planner_state_context_initial_snapshot_is_json_serializable() -> None:
    """Initial context should snapshot registry-visible planner state."""
    ctx = initial_planner_state_context(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )
    payload = ctx.to_payload()

    assert payload["manifest"]["schema_version"] == "planner-state-context/v2"
    assert payload["manifest"]["context_type"] == "planner"
    assert payload["state"]["legacy_identity_fallback_count"] > 0
    assert "problem" in payload["state"]["scope_graph"]["scope_ids"]
    assert payload["state"]["alias_index"]["by_handle"]["point:problem:D"].startswith(
        "point:D@problem"
    )
    m_coordinate_slots = [
        item
        for item in ctx.state.state_slots
        if item.object_ref == "point:ii:M" and item.runtime_type == "Point"
    ]
    assert any(
        item.free_symbol_refs == ("symbol:problem:m",)
        for item in m_coordinate_slots
    )
    assert any(
        item["kind"] == "coefficient_relation"
        for item in payload["state"]["conditions"]
    )
    right_angle = next(
        item
        for item in payload["state"]["conditions"]
        if item["kind"] == "right_angle_equal_length"
    )
    assert right_angle["object_roles"] == {
        "anchor": ["point:problem:D"],
        "endpoint": ["point:ii:M", "point:ii:N"],
    }
    parameter_range = next(
        item
        for item in payload["state"]["conditions"]
        if item["kind"] == "symbol_constraint"
        and item["canonical_handle"] == "fact:problem:m_gt_2"
    )
    assert parameter_range["subject_ids"] == ["symbol:problem:m"]
    assert parameter_range["object_roles"] == {
        "subject": ["symbol:problem:m"],
    }
    contract_ids = {
        item["capability_id"]
        for item in payload["state"]["capability_contracts"]
    }
    assert "quadratic_from_constraints" in contract_ids
    assert "distance_between_points" in contract_ids
    sources = {
        item["capability_id"]: item["source"]
        for item in payload["state"]["capability_contracts"]
    }
    assert sources["quadratic_from_constraints"] == "explicit"
    assert "projected" in set(sources.values())
    point_d = next(
        item
        for item in payload["state"]["math_objects"]
        if item["canonical_handle"] == "point:problem:D"
    )
    assert point_d["valid_scope"] == "problem"
    assert "source_step_id" not in point_d
    assert point_d["math_object_id"] == {
        "value": "point:problem:D",
        "kind": "point",
        "origin_scope_id": "problem",
    }
    materialized_m = next(
        item
        for item in m_coordinate_slots
        if item.logical_state_key is not None
    )
    assert materialized_m.typed_slot_id is not None
    assert materialized_m.latest_version_id is not None
    assert materialized_m.latest_version_id.ordinal == 0
    answer_slots = [
        item
        for item in ctx.state.state_slots
        if item.object_ref and item.object_ref.startswith("answer:")
    ]
    assert answer_slots
    assert all(item.typed_slot_id is None for item in answer_slots)
    json.dumps(payload, ensure_ascii=False)


def test_planner_state_context_scope_graph_and_valid_scope_are_explicit() -> None:
    """Context should expose scope ancestry and fact valid_scope metadata."""
    ctx = PlannerStateContextBuilder.initial_from_inputs(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )

    assert ctx.state.scope_graph.scope_parents["ii"] == "problem"
    assert ctx.state.scope_graph.scope_parents["ii_1"] == "ii"
    coefficient_relation = next(
        item
        for item in ctx.state.conditions
        if item.canonical_handle == "fact:problem:coefficient_relation"
    )
    assert coefficient_relation.scope_id == "problem"
    assert coefficient_relation.valid_scope == "problem"


def test_context_semantic_catalog_preserves_hidden_aliases_for_scoped_entity_refs() -> None:
    """Scope-qualified prompt refs should keep hidden short-ref aliases."""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i", "ii")),
        entity_handles=frozenset(("point:i:A", "point:ii:A")),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "i": "problem", "ii": "problem"},
        handle_valid_scopes={
            "point:i:A": "i",
            "point:ii:A": "ii",
        },
    )
    ctx = PlannerStateContextBuilder.initial_from_inputs(
        _nankai_inputs(),
        problem_payload={"problem_id": "synthetic-duplicate-entities"},
        handle_registry=registry,
    )

    items = ctx.semantic_read_catalog()
    prompt_refs = {
        (item.handle, item.ref)
        for item in items
        if item.kind == "point" and item.prompt_visible
    }
    hidden_refs = {
        (item.handle, item.ref)
        for item in items
        if item.kind == "point" and not item.prompt_visible
    }

    assert prompt_refs == {
        ("point:i:A", "i.A"),
        ("point:ii:A", "ii.A"),
    }
    assert {
        ("point:i:A", "A"),
        ("point:ii:A", "A"),
        ("point:i:A", "point:i:A"),
        ("point:ii:A", "point:ii:A"),
    }.issubset(hidden_refs)


def test_context_catalog_includes_objects_referenced_only_by_structured_facts() -> None:
    """Ordered relations should publish latent objects that the LLM may bind."""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "part")),
        entity_handles=frozenset(
            (
                "point:part:A",
                "point:part:E",
                "point:part:G",
            )
        ),
        fact_handles=frozenset(("fact:part:square_AEKG",)),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "part": "problem"},
        handle_valid_scopes={
            "point:part:A": "part",
            "point:part:E": "part",
            "point:part:G": "part",
            "fact:part:square_AEKG": "part",
        },
        fact_types={"fact:part:square_AEKG": "square"},
        fact_payloads={
            "fact:part:square_AEKG": {
                "handle": "fact:part:square_AEKG",
                "type": "square",
                "scope_id": "part",
                "vertices": [
                    "point:part:A",
                    "point:part:E",
                    "point:part:K",
                    "point:part:G",
                ],
            }
        },
    )
    context = PlannerStateContextBuilder.initial_from_inputs(
        _nankai_inputs(),
        problem_payload={
            "problem_id": "synthetic-structured-object",
            "facts": [
                {
                    "handle": "fact:part:square_AEKG",
                    "type": "square",
                    "scope_id": "part",
                    "vertices": [
                        "point:part:A",
                        "point:part:E",
                        "point:part:K",
                        "point:part:G",
                    ],
                }
            ],
        },
        handle_registry=registry,
    )

    latent = next(
        item
        for item in context.state.math_objects
        if item.canonical_handle == "point:part:K"
    )
    assert latent.source == "problem"
    assert latent.scope_id == "part"
    assert any(
        item.prompt_visible
        and item.kind == "point"
        and item.ref == "K"
        and item.handle == "point:part:K"
        for item in context.semantic_read_catalog()
    )
