from __future__ import annotations

import json

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
    _contextualize_dynamic_macro_roles,
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


def test_macro_named_entity_and_anonymous_result_forms_are_explicit() -> None:
    methods = MethodSpecRegistry.load_from_code()
    matching_specs = []

    for family in DEFAULT_FAMILY_REGISTRY.families:
        registry = MacroSpecRegistry.from_family_spec(family, methods)
        for macro_id in (
            "broken_path_straightening_minimum_expression",
        ):
            spec = registry.specs.get(macro_id)
            if spec is not None:
                matching_specs.append(spec)

    assert matching_specs
    for spec in matching_specs:
        line_args = tuple(
            item for item in spec.args if item.runtime_type == "Line"
        )
        assert len(line_args) == 1
        moving_locus = line_args[0]
        assert moving_locus.runtime_type == "Line"
        assert moving_locus.allows_anonymous_result

        prompt_line_args = tuple(
            item
            for item in spec.to_prompt_payload()["args"]
            if item["domain_type"] == "Line"
        )
        assert len(prompt_line_args) == 1
        prompt_arg = prompt_line_args[0]
        assert "allows_anonymous_result" not in prompt_arg


def test_all_registered_macros_declare_execution_and_lowering_contract() -> None:
    methods = MethodSpecRegistry.load_from_code()
    macros: dict[str, list[object]] = {}

    for family in DEFAULT_FAMILY_REGISTRY.families:
        registry = MacroSpecRegistry.from_family_spec(family, methods)
        for macro_id, spec in registry.specs.items():
            macros.setdefault(macro_id, []).append(spec)

    assert set(macros) == {
        "broken_path_straightening_minimum_expression",
        "coupled_segment_endpoint_replacement_path_minimum",
        "curve_candidate_parameter_solve",
        "equal_length_ray_path_reduction",
        "right_angle_equal_length_construct_and_select",
        "two_moving_points_path_reduction",
    }
    for specs in macros.values():
        for spec in specs:
            assert spec.execution_mode in {"direct", "runtime_search"}
            if spec.adapter.execution_strategy == "functional_plan_fragment":
                assert spec.internal_calls == ()
            else:
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


def test_scoped_prompts_do_not_name_internal_path_types() -> None:
    renderer = StrategyPromptRenderer()
    systems = (
        renderer.env.get_template(
            "strategy-functional-content-system.jinja"
        ).render(),
        renderer.env.get_template(
            "strategy-functional-goal-repair-system.jinja"
        ).render(),
    )

    for system in systems:
        assert all(
            term not in system
            for term in ("PathTransformation", "PathWitness", "PathCandidate")
        )


def test_equal_length_macro_exposes_only_ambiguous_roles_as_enums(
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

    class AmbiguousRoles:
        @staticmethod
        def macro_role_ref_candidates(_capability_id):
            return {
                "anchor": ("C",),
                "reference_point": ("B", "M"),
                "ray_point": ("D",),
                "fixed_point": ("O",),
            }

    projected = _contextualize_dynamic_macro_roles(
        capability,
        semantic_catalog=AmbiguousRoles(),
    )
    role_args = {
        item.name: item.allowed_refs
        for item in projected.args
        if item.name in {"anchor", "reference_point", "ray_point", "fixed_point"}
    }

    assert role_args == {"reference_point": ("B", "M")}
    reference_payload = next(
        item
        for item in projected.to_prompt_payload()["args"]
        if item["name"] == "reference_point"
    )
    assert reference_payload["allowed_refs"] == ["B", "M"]
