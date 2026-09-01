from __future__ import annotations

from dataclasses import replace
import json

import pytest

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.models import (
    TeachingSource,
    iter_teaching_sources,
)
from shuxueshuo_server.solver.explanation.role_binders.methods import (
    _next_auxiliary_point_label,
)
from shuxueshuo_server.solver.explanation.teaching_specs import TeachingSpecBinder
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import CASE_ID
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.recipes._spec import MacroTeachingSpec


HEPING_METHODS = (
    "quadratic_from_constraints",
    "quadratic_x_axis_intercept_point",
    "quadratic_vertex_point",
    "quadratic_axis_parameterized_point",
    "square_adjacent_vertex_from_side",
    "point_candidates_from_curve_point_condition",
    "parameter_from_expression_value",
    "evaluate_point_at_parameter",
)


@pytest.fixture(scope="module")
def snapshot():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture(CASE_ID)
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def test_heping_methods_and_macro_have_explicit_generic_specs() -> None:
    methods = MethodSpecRegistry.load_from_code()
    for method_id in HEPING_METHODS:
        unit = methods.require(method_id).teaching_unit
        assert unit is not None, method_id
        assert unit.unit_key.startswith(f"{method_id}/")
        assert unit.derive_templates
        assert unit.role_binder_id

    macro = RecipeSpecRegistry.load_from_code().get(
        "quadratic_square_path_minimum"
    )
    assert macro is not None and macro.teaching is not None
    assert [item.unit_key for item in macro.teaching.teaching_units] == [
        "quadratic_square_path_minimum/path_reduction",
        "quadratic_square_path_minimum/reflection_minimum",
    ]


def test_all_heping_occurrences_bind_to_13_complete_materials(snapshot) -> None:
    binder = TeachingSpecBinder()
    sources = tuple(iter_teaching_sources(snapshot.root_scope))
    bound = {
        source.source_step_id: binder.bind_source(source, snapshot=snapshot)
        for source in sources
    }

    assert len(bound) == 12
    assert sum(len(items) for items in bound.values()) == 13
    assert len(bound["derive_path_minimum_ii"]) == 2
    serialized = json.dumps(
        [item.to_payload() for values in bound.values() for item in values],
        ensure_ascii=False,
    )
    assert all(
        "{" not in text and "}" not in text
        for values in bound.values()
        for item in values
        for text in (
            item.title,
            item.nav_title,
            item.goal,
            *(value for _marker, value in item.derive),
            *item.box,
        )
    )
    assert "和平二模" not in serialized
    assert "tj-2026" not in serialized


def test_repeated_method_specs_bind_distinct_runtime_occurrences(snapshot) -> None:
    binder = TeachingSpecBinder()
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }

    parabola_i = binder.bind_source(
        sources["derive_parabola_i"], snapshot=snapshot
    )[0]
    parabola_ii = binder.bind_source(
        sources["derive_parametric_parabola_ii"], snapshot=snapshot
    )[0]
    assert parabola_i.unit_key == parabola_ii.unit_key
    assert parabola_i.box != parabola_ii.box
    parametric_derive = "\n".join(
        f"{marker}{text}" for marker, text in parabola_ii.derive
    )
    assert "A(－c,0) 在 y＝" in parametric_derive
    assert "b＝1－c" in parametric_derive
    assert parametric_derive.index("A(－c,0) 在 y＝") < parametric_derive.index(
        "b＝1－c"
    )

    square_i = binder.bind_source(
        sources["derive_square_vertex_G_i"], snapshot=snapshot
    )[0]
    square_ii = binder.bind_source(
        sources["recover_target_point_E_ii"], snapshot=snapshot
    )[0]
    assert square_i.unit_key == square_ii.unit_key
    assert "G" in square_i.title and "E" in square_ii.title

    evaluate_a = binder.bind_source(
        sources["evaluate_point_A_ii"], snapshot=snapshot
    )[0]
    evaluate_g = binder.bind_source(
        sources["evaluate_minimum_point_G_ii"], snapshot=snapshot
    )[0]
    assert evaluate_a.unit_key == evaluate_g.unit_key
    assert "A(-c,0)" in evaluate_a.derive[0][1]
    assert "G(1/4-3c/4,-c/2-1/2)" in evaluate_g.derive[0][1]


def test_x_intercept_spec_shows_all_roots_and_verified_side_selection(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_x_intercept_A_i"
    )
    unit = TeachingSpecBinder().bind_source(source, snapshot=snapshot)[0]
    text = json.dumps(unit.to_payload(), ensure_ascii=False)
    assert "x＝－3" in text
    assert "x＝1" in text
    assert "A 定义为左侧交点" in text
    assert "取较小根 x＝－3" in text


def test_square_spec_uses_computed_projection_points_and_junior_geometry(
    snapshot,
) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_square_vertex_G_i"
    )
    binder = TeachingSpecBinder()
    generic = binder.generic_spec_payload(source)
    unit = binder.bind_source(source, snapshot=snapshot)[0]
    generic_text = json.dumps(generic, ensure_ascii=False)
    text = json.dumps(unit.to_payload(), ensure_ascii=False)
    assert "M" not in generic_text and "Q" not in generic_text
    assert "GQ⊥x轴于 Q" in text
    assert "Rt△AEM≌Rt△GAQ" in text
    assert "向量" not in text and "坐标差" not in text


def test_square_projection_auxiliary_label_is_allocated_from_namespace(snapshot) -> None:
    assert _next_auxiliary_point_label(
        {"A", "B", "C", "E", "F", "G", "H", "K", "M", "P"}
    ) == "Q"
    assert _next_auxiliary_point_label(
        {"A", "B", "C", "E", "F", "G", "H", "K", "M", "P", "Q"}
    ) == "R"

    problem = dict(snapshot.problem)
    problem["entities"] = [
        *problem.get("entities", ()),
        {
            "entity_type": "point",
            "name": "Q",
            "handle": "point:problem:Q",
            "scope_id": "problem",
            "definition": "reserved_auxiliary_point",
        },
    ]
    snapshot_with_q = replace(snapshot, problem=problem)
    source = next(
        item
        for item in iter_teaching_sources(snapshot_with_q.root_scope)
        if item.source_step_id == "derive_square_vertex_G_i"
    )
    unit = TeachingSpecBinder().bind_source(
        source,
        snapshot=snapshot_with_q,
    )[0]
    text = json.dumps(unit.to_payload(), ensure_ascii=False)
    assert "GR⊥x轴于 R" in text
    assert "Rt△AEM≌Rt△GAR" in text


def test_candidate_spec_solves_original_parameter_without_hardcoded_u(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "solve_axis_point_candidates_i"
    )
    binder = TeachingSpecBinder()
    generic = binder.generic_spec_payload(source)
    bound = binder.bind_source(source, snapshot=snapshot)[0].to_payload()
    text = json.dumps({"generic": generic, "bound": bound}, ensure_ascii=False)
    assert "auxiliary_parameter" not in text
    assert "auxiliary_equation" not in text
    assert "u＝" not in text
    assert "t＝2±√6" in text


def test_macro_bound_units_cover_verified_reduction_reflection_and_attainment(
    snapshot,
) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_path_minimum_ii"
    )
    units = TeachingSpecBinder().bind_source(source, snapshot=snapshot)
    text = json.dumps([item.to_payload() for item in units], ensure_ascii=False)

    for required in (
        "HF+FM+MG＝AG+MG",
        "G 的轨迹",
        "A′",
        "AG=A′G",
        "√5|c+1|/2",
        "G(1/4-3c/4,-c/2-1/2)",
    ):
        assert required in text
    reduction = units[0]
    assert reduction.derive == (
        ("∵", "FM=AE/2，HF=AG/2，AE=AG"),
        ("∴", "HF+FM=AG"),
        ("∴", "HF+FM+MG＝AG+MG"),
    )
    assert "⇒" not in "\n".join(item[1] for item in reduction.derive)


def test_snapshot_step_wire_omits_internal_evidence_refs(snapshot) -> None:
    payload = snapshot.to_payload()
    text = json.dumps(payload["root_scope"], ensure_ascii=False)
    assert "evidence_refs" not in text

    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "solve_parameter_c_ii"
    )
    assert source.calculations
    assert source.checks


def test_method_without_explicit_unit_still_has_default_candidate() -> None:
    source = TeachingSource(
        source_step_id="distance",
        capability_id="distance_between_points",
        inputs={},
        outputs={
            "distance": {
                "runtime_type": "Distance",
                "value": "5",
                "display": "5",
            }
        },
        intent="计算两点间距离。",
    )
    payload = TeachingSpecBinder().generic_spec_payload(source)
    assert payload["kind"] == "function"
    assert payload["declared"] is False
    assert payload["teaching_unit"]["unit_key"].endswith("/default")


def test_macro_teaching_contract_rejects_zero_or_two_paths() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MacroTeachingSpec()
