from __future__ import annotations

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CanonicalStateHandleFactory,
    FunctionalCapabilityReturn,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    _resolve_return_binding,
)
from shuxueshuo_server.solver.runtime.semantic_reads import SemanticReadCatalogItem
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef
from shuxueshuo_server.solver.state_semantics import (
    is_object_handle,
    is_object_semantic_kind,
    object_kind_for_runtime_type,
    runtime_type_for_object_semantic_kind,
    split_runtime_types,
    state_kind_for_runtime_type,
)


def test_runtime_type_state_semantics_are_canonical() -> None:
    assert state_kind_for_runtime_type("MinimumExpression") == "expression"
    assert state_kind_for_runtime_type("Symbol") == "symbol"
    assert state_kind_for_runtime_type("Line") == "locus"
    assert state_kind_for_runtime_type("Point") == "coordinate"
    assert state_kind_for_runtime_type("Expression|MinimumExpression") == "expression"

    assert object_kind_for_runtime_type("Symbol") == "symbol"
    assert object_kind_for_runtime_type("ParameterValue") == "symbol"
    assert object_kind_for_runtime_type("PointRef|Point") == "point"
    assert split_runtime_types(" PointRef | Point ") == ("PointRef", "Point")
    assert runtime_type_for_object_semantic_kind("function") == "Parabola|Function"
    assert runtime_type_for_object_semantic_kind("angle") == "Angle"
    assert runtime_type_for_object_semantic_kind("fact") is None


def test_all_problem_entity_runtime_types_share_canonical_object_semantics() -> None:
    expected = {
        "Point": "point",
        "Line": "line",
        "Segment": "segment",
        "Ray": "ray",
        "Function": "function",
        "Parabola": "function",
        "Symbol": "symbol",
        "Angle": "angle",
        "Circle": "circle",
        "Polygon": "polygon",
    }

    for runtime_type, semantic_kind in expected.items():
        assert object_kind_for_runtime_type(runtime_type) == semantic_kind
        assert is_object_semantic_kind(semantic_kind)
        assert is_object_handle(f"{semantic_kind}:problem:sample")

    assert not is_object_semantic_kind("fact")
    assert not is_object_handle("fact:problem:sample")


def test_angle_return_binding_uses_the_same_object_semantics_as_reads() -> None:
    result = FunctionalCapabilityReturn(
        name="angle_state",
        runtime_type="Angle",
        required=True,
        cardinality="one",
        state_kind="angle",
        semantic_role="measured_angle",
        identity_policy="target_object",
        identity_arg="target",
        write_mode="transition",
    )
    binding = SemanticReadCatalogItem(
        handle="angle:problem:AOB",
        kind="angle",
        ref="AOB",
        scope="problem",
        valid_scope="problem",
        value_type="Angle",
    )

    assert CanonicalStateHandleFactory().handle_for(
        call_id="measure_angle",
        return_spec=result,
        valid_scope="problem",
        binding=binding,
    ) == "fact:problem:AOB_measured_angle"

    resolved, issues = _resolve_return_binding(
        SemanticRef(ref="AOB", kind="angle", value_type="Angle"),
        call_id="measure_angle",
        scope_id="problem",
        return_type="Angle",
        semantic_items=(binding,),
        question_goals=(),
    )
    assert resolved == binding
    assert issues == ()
