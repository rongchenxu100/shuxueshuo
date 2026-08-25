from __future__ import annotations

import json

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FamilyCapabilityBundle,
    family_capability_bundle_for_inputs,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    default_macro_definition_registry,
)

from _problem_planning_support import planning_binding_fixture


pytestmark = pytest.mark.solver_contract


def test_family_capability_bundle_partitions_functions_and_macros(tmp_path) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )

    bundle = family_capability_bundle_for_inputs(fixture[3])
    prompt_by_id = {
        item["capability_id"]: item
        for item in bundle.to_prompt_payload()["capabilities"]
    }
    prompt_payload = bundle.to_prompt_payload()
    by_id = {
        item["capability_id"]: item
        for item in prompt_payload["capabilities"]
    }

    assert set(bundle.function_ids).isdisjoint(bundle.macro_ids)
    assert set(bundle.function_ids) | set(bundle.macro_ids) == set(by_id)
    assert {item["kind"] for item in by_id.values()} == {
        "function",
        "macro",
    }
    assert "equal_length_ray_path_reduction" in bundle.macro_ids
    assert "equal_length_ray_point" not in bundle.function_ids
    macro = by_id["equal_length_ray_path_reduction"]
    assert macro["kind"] == "macro"
    assert set(macro["semantic_blueprint"]["expandable_functions"]) <= set(
        bundle.function_ids
    )
    macro_projection = bundle.catalog.items[
        "equal_length_ray_path_reduction"
    ].source
    definition = default_macro_definition_registry().require(
        "equal_length_ray_path_reduction"
    )
    assert macro_projection.source == "macro_definition_projection"
    assert macro_projection.search is definition.search_contract
    assert macro_projection.definition_signature == (
        definition.authority_signature
    )
    assert macro_projection.internal_calls == ()


def test_capability_bundle_signature_covers_transparent_blueprint(tmp_path) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    bundle = family_capability_bundle_for_inputs(fixture[3])

    restored = FamilyCapabilityBundle(
        family_id=bundle.family_id,
        catalog=bundle.catalog,
        function_ids=bundle.function_ids,
        macro_ids=bundle.macro_ids,
        macro_blueprints=bundle.macro_blueprints,
        bundle_signature=bundle.bundle_signature,
    )

    assert restored.authority_payload() == bundle.authority_payload()
    assert json.dumps(bundle.to_prompt_payload(), ensure_ascii=False)
    with pytest.raises(ValueError, match="capability_bundle_signature_drift"):
        FamilyCapabilityBundle(
            family_id=bundle.family_id,
            catalog=bundle.catalog,
            function_ids=bundle.function_ids,
            macro_ids=bundle.macro_ids,
            macro_blueprints=bundle.macro_blueprints,
            bundle_signature="stale",
        )


def test_nankai_bundle_exposes_coupled_path_functions_and_transparent_macro(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )
    bundle = family_capability_bundle_for_inputs(fixture[3])
    prompt_by_id = {
        item["capability_id"]: item
        for item in bundle.to_prompt_payload()["capabilities"]
    }

    assert {
        "prove_coupled_segment_endpoint_distance_equality",
        "rewrite_path_target_by_distance_equality",
    }.issubset(bundle.function_ids)
    macro_id = "coupled_segment_endpoint_replacement_path_minimum"
    assert macro_id in bundle.macro_ids
    assert macro_id in bundle.macro_blueprints
    assert set(
        bundle.macro_blueprints[macro_id].function_capability_ids
    ) <= set(bundle.function_ids)
    assert "path_verification_core" in fixture[3].family_spec.base_packs
    assert (
        "coupled_segment_endpoint_replacement_core"
        in fixture[3].family_spec.mechanism_packs
    )
    assert {
        arg["name"]
        for capability_id in (
            "prove_coupled_segment_endpoint_distance_equality",
            "rewrite_path_target_by_distance_equality",
        )
        for arg in prompt_by_id[capability_id]["args"]
    }.isdisjoint(
        {
            "first_track_fixed_endpoint_ref",
            "joint_point_ref",
            "second_track_fixed_endpoint_ref",
            "replacement_start_ref",
            "via_ref",
            "end_ref",
        }
    )
