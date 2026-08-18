from __future__ import annotations

import json

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry


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


def test_all_registered_macros_declare_execution_and_lowering_contract() -> None:
    methods = MethodSpecRegistry.load_from_code()
    macros: dict[str, list[object]] = {}

    for family in DEFAULT_FAMILY_REGISTRY.families:
        registry = MacroSpecRegistry.from_family_spec(family, methods)
        for macro_id, spec in registry.specs.items():
            macros.setdefault(macro_id, []).append(spec)

    assert set(macros) == {
        "broken_path_straightening_and_select",
        "broken_path_straightening_minimum_expression",
        "curve_candidate_parameter_solve",
        "equal_length_ray_path_reduction",
        "path_minimum_by_straightened_distance",
        "right_angle_equal_length_construct_and_select",
        "two_moving_points_path_reduction",
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
