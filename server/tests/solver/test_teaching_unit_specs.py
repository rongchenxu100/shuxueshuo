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
from shuxueshuo_server.solver.explanation.teaching_role_bindings import (
    _next_point_label,
)
from shuxueshuo_server.solver.explanation.teaching_specs import (
    BoundTeachingUnit,
    TeachingSeparationBoundaryResolver,
    TeachingSpecBinder,
    TeachingSpecBindingError,
)
from shuxueshuo_server.solver.lesson_authoring_support import CASE_ID
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


def test_visual_separation_boundaries_use_one_method_macro_rule(snapshot) -> None:
    resolver = TeachingSeparationBoundaryResolver()
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    expected = {
        "derive_parabola_i": ("quadratic_from_constraints/derive_function", False),
        "derive_x_intercept_A_i": (
            "quadratic_x_axis_intercept_point/solve_intercept",
            False,
        ),
        "derive_vertex_P_i": (
            "quadratic_vertex_point/read_vertex",
            False,
        ),
        "parameterize_axis_point_E_i": (
            "quadratic_axis_parameterized_point/parameterize_axis_point",
            True,
        ),
        "derive_square_vertex_G_i": (
            "square_adjacent_vertex_from_side/derive_adjacent_vertex",
            True,
        ),
        "solve_axis_point_candidates_i": (
            "point_candidates_from_curve_point_condition/solve_candidates",
            True,
        ),
        "solve_parameter_c_ii": (
            "parameter_from_expression_value/solve_parameter",
            False,
        ),
        "derive_parametric_parabola_ii": (
            "quadratic_from_constraints/derive_function",
            False,
        ),
        "evaluate_point_A_ii": (
            "evaluate_point_at_parameter/substitute_point_parameter",
            False,
        ),
        "evaluate_minimum_point_G_ii": (
            "evaluate_point_at_parameter/substitute_point_parameter",
            False,
        ),
        "recover_target_point_E_ii": (
            "square_adjacent_vertex_from_side/derive_adjacent_vertex",
            True,
        ),
    }
    for step_id, (unit_key, independent) in expected.items():
        assert resolver.requires_independent_lesson_step(
            sources[step_id],
            capability_kind="function",
            unit_key=unit_key,
        ) is independent

    macro_source = sources["derive_path_minimum_ii"]
    for unit_key in (
        "quadratic_square_path_minimum/path_reduction",
        "quadratic_square_path_minimum/reflection_minimum",
    ):
        assert resolver.requires_independent_lesson_step(
            macro_source,
            capability_kind="macro",
            unit_key=unit_key,
        ) is True


@pytest.mark.parametrize(
    ("capability_id", "unit_keys"),
    [
        (
            "equal_length_ray_path_reduction",
            (
                "equal_length_ray_path_reduction/path_reduction",
                "equal_length_ray_path_reduction/minimum_by_segment",
            ),
        ),
        (
            "coupled_segment_endpoint_replacement_path_minimum",
            (
                "coupled_segment_endpoint_replacement_path_minimum/endpoint_replacement",
                "coupled_segment_endpoint_replacement_path_minimum/reflection_minimum",
            ),
        ),
        (
            "weighted_axis_path_minimum",
            (
                "weighted_axis_path_minimum/weighted_reduction",
                "weighted_axis_path_minimum/domain_minimum",
            ),
        ),
    ],
)
def test_other_public_path_macro_units_have_visual_boundaries(
    capability_id,
    unit_keys,
) -> None:
    source = TeachingSource(
        source_step_id="macro",
        capability_id=capability_id,
        inputs={},
        outputs={},
    )
    resolver = TeachingSeparationBoundaryResolver()
    assert all(
        resolver.requires_independent_lesson_step(
            source,
            capability_kind="macro",
            unit_key=unit_key,
        )
        for unit_key in unit_keys
    )


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


def test_known_coefficient_identity_does_not_depend_on_distinct_values(
    snapshot,
) -> None:
    source = TeachingSource(
        source_step_id="same_value_coefficients",
        capability_id="quadratic_from_constraints",
        inputs={
            "known_coefficients": (
                {
                    "ref": {"kind": "source", "ref": "symbol_value_a"},
                    "runtime_type": "ParameterValue",
                    "value": "1",
                    "display": "1",
                },
                {
                    "ref": {"kind": "source", "ref": "symbol_value_b"},
                    "runtime_type": "ParameterValue",
                    "value": "1",
                    "display": "1",
                },
            )
        },
        outputs={
            "coefficients": {
                "runtime_type": "Coefficients",
                "value": {"a": "1", "b": "1"},
                "display": '{"a":"1","b":"1"}',
            },
            "parabola": {
                "runtime_type": "Parabola",
                "value": "x**2 + x",
                "display": "x²+x",
            },
        },
    )
    unit = TeachingSpecBinder().bind_source(source, snapshot=snapshot)[0]
    text = json.dumps(unit.to_payload(), ensure_ascii=False)
    assert "a＝1，b＝1" in text
    assert "已知系数取值" not in text


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


def test_square_spec_reuses_existing_target_projection_point(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "recover_target_point_E_ii"
    )
    unit = TeachingSpecBinder().bind_source(source, snapshot=snapshot)[0]
    text = json.dumps(unit.to_payload(), ensure_ascii=False)

    assert "GQ⊥x轴于 Q" in text
    assert "ER⊥x轴于 R" not in text
    assert "∠GQA＝∠EMA＝90°" in text
    assert "Rt△AGQ≌Rt△EAM" in text
    assert "AM＝QG＝3，EM＝AQ＝3/2" in text


def test_square_projection_reuse_is_driven_by_semantic_relations_not_letters(
    snapshot,
) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "recover_target_point_E_ii"
    )
    inputs = {name: tuple(dict(item) for item in items) for name, items in source.inputs.items()}
    square_item = dict(inputs["square"][0])
    square_value = dict(square_item["value"])
    square_value["vertices"] = ["A", "D", "K", "G"]
    square_value["side"] = "AD"
    square_item["value"] = square_value
    square_item["display"] = "正方形 ADKG"
    inputs["square"] = (square_item,)
    adjacent = dict(source.outputs["adjacent_vertex"])
    adjacent["display"] = "D(-2,3/2)"
    renamed_source = replace(
        source,
        inputs=inputs,
        outputs={**source.outputs, "adjacent_vertex": adjacent},
        output_targets={"adjacent_vertex": "D"},
    )

    problem = dict(snapshot.problem)
    renamed_entities = []
    for entity in problem.get("entities", ()):
        renamed = dict(entity)
        if renamed.get("name") == "E":
            renamed["name"] = "D"
            renamed["description"] = "D"
        elif renamed.get("name") == "M":
            renamed["name"] = "J"
            renamed["description"] = "J"
        renamed_entities.append(renamed)
    problem["entities"] = renamed_entities
    renamed_snapshot = replace(snapshot, problem=problem)

    unit = TeachingSpecBinder().bind_source(
        renamed_source,
        snapshot=renamed_snapshot,
    )[0]
    text = json.dumps(unit.to_payload(), ensure_ascii=False)
    assert "GQ⊥x轴于 Q" in text
    assert "∠GQA＝∠DJA＝90°" in text
    assert "Rt△AGQ≌Rt△DAJ" in text
    assert "AJ＝QG＝3，DJ＝AQ＝3/2" in text


def test_square_projection_semantic_identity_ambiguity_fails_loud(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "recover_target_point_E_ii"
    )
    problem = dict(snapshot.problem)
    problem["entities"] = [
        *problem.get("entities", ()),
        {
            "entity_type": "point",
            "name": "N",
            "handle": "point:problem:N",
            "scope_id": "problem",
            "definition": "axis_x_intercept",
            "of": "function:problem:parabola",
        },
    ]
    ambiguous_snapshot = replace(snapshot, problem=problem)

    with pytest.raises(
        TeachingSpecBindingError,
        match="teaching_projection_existing_object_ambiguous",
    ):
        TeachingSpecBinder().bind_source(source, snapshot=ambiguous_snapshot)


def test_square_projection_auxiliary_label_is_allocated_from_namespace(snapshot) -> None:
    assert _next_point_label(
        {"A", "B", "C", "E", "F", "G", "H", "K", "M", "P"}
    ) == "Q"
    assert _next_point_label(
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


def test_expression_evaluation_uses_explicit_verified_substitution_unit() -> None:
    source = TeachingSource(
        source_step_id="distance",
        capability_id="evaluate_expression_at_parameter",
        inputs={},
        outputs={
            "evaluated_expression": {
                "runtime_type": "ExactValue",
                "value": "5",
                "display": "5",
            }
        },
        intent="代入参数求表达式的值。",
    )
    payload = TeachingSpecBinder().generic_spec_payload(source)
    assert payload["kind"] == "function"
    assert payload["declared"] is True
    assert payload["teaching_unit"]["unit_key"] == (
        "evaluate_expression_at_parameter/substitute_parameter"
    )
    assert payload["teaching_unit"]["role_binder_id"] == (
        "evaluate_expression_at_parameter"
    )


def test_expression_evaluation_noop_uses_bound_parameter_identity() -> None:
    source = TeachingSource(
        source_step_id="evaluate_closed_expression",
        capability_id="evaluate_expression_at_parameter",
        inputs={
            "expression": (
                {
                    "ref": {
                        "kind": "step_result",
                        "step_id": "closed_expression",
                        "return": "expression",
                    },
                    "runtime_type": "Expression",
                    "value": "5",
                    "display": "5",
                },
            ),
            "parameter": (
                {
                    "ref": {"kind": "source", "ref": "m"},
                    "runtime_type": "Symbol",
                    "value": "m",
                    "display": "m",
                },
            ),
            "parameter_value": (
                {
                    "ref": {
                        "kind": "step_result",
                        "step_id": "solve_m",
                        "return": "parameter_value",
                    },
                    "runtime_type": "ParameterValue",
                    "value": "3",
                    "display": "3",
                },
            ),
        },
        outputs={
            "evaluated_expression": {
                "runtime_type": "Expression",
                "value": "5",
                "display": "5",
            }
        },
        intent="对已经闭合的表达式执行安全求值。",
    )

    unit = TeachingSpecBinder().bind_source(source, snapshot=None)[0]

    assert unit.derive == (
        ("∵", "m＝3"),
        ("计算", "把 m＝3 代入 5，化简得 5"),
        ("∴", "5"),
    )


def test_parameterized_distance_uses_bound_parameter_identity() -> None:
    source = TeachingSource(
        source_step_id="evaluate_parameterized_distance",
        capability_id="distance_between_points",
        inputs={
            "p1": (
                {
                    "ref": {"kind": "source", "ref": "P"},
                    "runtime_type": "Point",
                    "value": ["0", "0"],
                    "display": "P(0,0)",
                },
            ),
            "p2": (
                {
                    "ref": {"kind": "source", "ref": "Q"},
                    "runtime_type": "Point",
                    "value": ["m", "0"],
                    "display": "Q(m,0)",
                },
            ),
            "parameter": (
                {
                    "ref": {"kind": "source", "ref": "m"},
                    "runtime_type": "Symbol",
                    "value": "m",
                    "display": "m",
                },
            ),
            "parameter_value": (
                {
                    "ref": {
                        "kind": "step_result",
                        "step_id": "solve_m",
                        "return": "parameter_value",
                    },
                    "runtime_type": "ParameterValue",
                    "value": "3",
                    "display": "3",
                },
            ),
        },
        outputs={
            "distance": {
                "runtime_type": "MinimumExpression",
                "value": "m",
                "display": "m",
            },
            "evaluated_distance": {
                "runtime_type": "MinimumExpression",
                "value": "3",
                "display": "3",
            },
        },
        intent="求参数确定后的两点距离。",
    )

    unit = TeachingSpecBinder().bind_source(source, snapshot=None)[0]

    assert ("计算", "代入 m＝3，得 3") in unit.derive
    assert unit.derive[-1] == ("∴", "PQ＝3")
    assert unit.box == ("3",)


def test_macro_teaching_contract_rejects_zero_or_two_paths() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        MacroTeachingSpec()


def test_b2_unit_local_fallback_keeps_successful_macro_sibling(
    snapshot,
    monkeypatch,
) -> None:
    import shuxueshuo_server.solver.explanation.teaching_specs as module

    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_path_minimum_ii"
    )
    original_bind = module._bind_unit
    fallback_keys: list[str] = []

    def fail_first(source_value, unit, roles):
        if unit.unit_key.endswith("/path_reduction"):
            raise TeachingSpecBindingError(
                "teaching_spec_placeholder_unresolved: injected"
            )
        return original_bind(source_value, unit, roles)

    def fallback(unit, _error):
        fallback_keys.append(unit.unit_key)
        return BoundTeachingUnit(
            source_step_id=source.source_step_id,
            unit_key=unit.unit_key,
            nav_title="通用路径化简",
            title="使用已验证关系化简路径",
            goal="根据本步的完整计算结果化简路径。",
            derive=(("计算", "使用本步全部已验证计算"),),
            box=(),
        )

    monkeypatch.setattr(module, "_bind_unit", fail_first)
    selection = TeachingSpecBinder().bind_source_selection(
        source,
        snapshot=snapshot,
        on_unit_error=fallback,
    )

    assert selection.kind == "macro"
    assert len(selection.units) == 2
    assert fallback_keys == [
        "quadratic_square_path_minimum/path_reduction"
    ]
    assert selection.units[0].title == "使用已验证关系化简路径"
    assert selection.units[1].unit_key.endswith("/reflection_minimum")
