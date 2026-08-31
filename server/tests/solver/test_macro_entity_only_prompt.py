from __future__ import annotations

import json

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.strategy_payload import StrategyPromptRenderer

from _problem_planning_support import planning_binding_fixture


RUNTIME_TERMS = (
    "PointRef",
    "semantic_ref_role",
    "StateVersion",
    "MathObjectId",
    "runtime_path",
    "PathTransformation",
    "PathWitness",
    "PathCandidate",
    "StraighteningCandidate",
)

RETIRED_PATH_CAPABILITIES = (
    "two_moving_points_path_reduction",
    "square_path_dimension_reduction",
    "parameterized_point_locus_line",
    "line_locus_minimum_point",
    "broken_path_straightening_candidates",
    "select_straightening_candidate",
    "weighted_axis_path_triangle_transform",
    "linked_broken_path_minimum_expression",
    "linked_broken_path_geometric_minimum",
)

STATE_VALUE_TYPES = {"ParameterValue", "Parabola"}


def test_functional_capability_prompt_exposes_only_domain_arguments() -> None:
    methods = MethodSpecRegistry.load_from_code()

    for family in DEFAULT_FAMILY_REGISTRY.families:
        payload = FunctionalCapabilityCatalog.from_family_spec(
            family,
            methods,
        ).to_prompt_payload()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert all(term not in encoded for term in RUNTIME_TERMS), family.family_id
        assert all(
            capability_id not in encoded
            for capability_id in RETIRED_PATH_CAPABILITIES
        ), family.family_id
        for capability in payload["capabilities"]:
            for arg in capability["args"]:
                assert set(arg) <= {
                    "name",
                    "domain_type",
                    "required",
                    "cardinality",
                    "fact_types",
                    "roles",
                    "role",
                }
                assert "domain_type" in arg
                assert arg["domain_type"] not in STATE_VALUE_TYPES


def test_macro_catalog_hides_internal_methods_and_runtime_views() -> None:
    methods = MethodSpecRegistry.load_from_code()

    for family in DEFAULT_FAMILY_REGISTRY.families:
        payload = MacroSpecRegistry.from_family_spec(
            family,
            methods,
        ).to_prompt_payload()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert all(term not in encoded for term in RUNTIME_TERMS), family.family_id
        assert "internal_calls" not in encoded
        assert "candidate_builder_id" not in encoded
        for macro in payload["items"]:
            for arg in macro["args"]:
                assert set(arg) <= {
                    "name",
                    "domain_type",
                    "required",
                    "cardinality",
                    "role",
                }
                assert arg["domain_type"] not in STATE_VALUE_TYPES


def test_atomic_path_macros_expose_only_problem_entities_and_public_results() -> None:
    methods = MethodSpecRegistry.load_from_code()
    matching_specs = {}

    for family in DEFAULT_FAMILY_REGISTRY.families:
        registry = MacroSpecRegistry.from_family_spec(family, methods)
        for macro_id in (
            "coupled_segment_endpoint_replacement_path_minimum",
            "quadratic_square_path_minimum",
            "weighted_axis_path_minimum",
        ):
            spec = registry.specs.get(macro_id)
            if spec is not None:
                matching_specs[macro_id] = spec

    assert set(matching_specs) == {
        "coupled_segment_endpoint_replacement_path_minimum",
        "quadratic_square_path_minimum",
        "weighted_axis_path_minimum",
    }
    for spec in matching_specs.values():
        encoded = json.dumps(spec.to_prompt_payload(), ensure_ascii=False)
        assert all(
            term not in encoded
            for term in ("PathTransformation", "PathWitness", "PathCandidate")
        )


def test_all_registered_macros_declare_execution_and_lowering_contract() -> None:
    methods = MethodSpecRegistry.load_from_code()
    macros: dict[str, list[object]] = {}

    for family in DEFAULT_FAMILY_REGISTRY.families:
        registry = MacroSpecRegistry.from_family_spec(family, methods)
        for macro_id, spec in registry.specs.items():
            macros.setdefault(macro_id, []).append(spec)

    assert set(macros) == {
        "coupled_segment_endpoint_replacement_path_minimum",
        "curve_candidate_parameter_solve",
        "equal_length_ray_path_reduction",
        "quadratic_square_path_minimum",
        "right_angle_equal_length_construct_and_select",
        "weighted_axis_path_minimum",
    }
    for specs in macros.values():
        for spec in specs:
            assert spec.execution_mode in {"direct", "runtime_search"}
            assert spec.internal_calls
            if spec.execution_mode == "direct":
                assert spec.search is None
            else:
                assert spec.search is not None
                assert spec.search.searchable_roles
                assert 1 <= spec.search.max_candidates <= 32


def test_equal_length_macro_hides_roles_proved_by_four_structured_facts(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    semantic_index = FunctionalSemanticIndex.from_semantic_items(
        fixture[6],
        fixture[7].semantic_read_items(),
        handle_registry=fixture[5],
    )
    capability = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    ).contextualized(semantic_index).items["equal_length_ray_path_reduction"]

    assert [item.name for item in capability.args] == [
        "path_minimum_target",
        "equal_length_condition",
        "point_on_segment",
        "point_on_ray",
    ]
    assert [item.name for item in capability.returns] == ["minimum_expression"]
    encoded = json.dumps(
        capability.to_prompt_payload(),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert all(
        term not in encoded
        for term in ("PathTransformation", "PathWitness", "PathCandidate")
    )

    macro = MacroSpecRegistry.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    ).require("equal_length_ray_path_reduction")
    assert macro.code_owned_search_roles == frozenset(
        {"anchor", "reference_point", "ray_point", "fixed_point"}
    )
    assert [item["name"] for item in macro.to_prompt_payload()["args"]] == [
        "path_minimum_target",
        "equal_length_condition",
        "point_on_segment",
        "point_on_ray",
    ]


def test_scoped_prompts_do_not_name_internal_path_types() -> None:
    renderer = StrategyPromptRenderer()
    systems = (
        renderer.env.get_template(
            "strategy-functional-content-system.jinja"
        ).render(),
        renderer.env.get_template(
            "strategy-functional-scope-repair-system.jinja"
        ).render(),
    )

    for system in systems:
        assert all(
            term not in system
            for term in ("PathTransformation", "PathWitness", "PathCandidate")
        )


def test_equal_length_macro_keeps_code_owned_roles_hidden_when_runtime_is_ambiguous(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    capability = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    ).items["equal_length_ray_path_reduction"]

    class AmbiguousRuntimeContext:
        @staticmethod
        def has_compatible_view(**_kwargs):
            return True

        @staticmethod
        def macro_role_ref_candidates(_capability_id):
            raise AssertionError("runtime candidates must not reshape the catalog")

    projected = FunctionalCapabilityCatalog(
        {capability.capability_id: capability}
    ).contextualized(AmbiguousRuntimeContext()).items[capability.capability_id]

    assert [item.name for item in projected.args] == [
        "path_minimum_target",
        "equal_length_condition",
        "point_on_segment",
        "point_on_ray",
    ]
    assert not {
        "anchor",
        "reference_point",
        "ray_point",
        "fixed_point",
    }.intersection(item.name for item in projected.args)
