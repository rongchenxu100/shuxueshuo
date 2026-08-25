from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    family_capability_bundle_for_inputs,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    MacroExpansionRequest,
    default_macro_definition_registry,
)

from _problem_planning_support import planning_binding_fixture
from test_macro_prepared_role_binding import _equal_length_role_authority


pytestmark = pytest.mark.solver_contract


def _expanded_candidates():
    context, registry, facts = _equal_length_role_authority(structured=True)
    source_refs = {
        handle: str(payload.get("name") or handle)
        for handle, payload in registry.entity_payloads.items()
    }
    source_refs.update({handle: handle for handle in facts})
    builder_context = {
        **context,
        "source_refs_by_handle": source_refs,
    }
    definition = default_macro_definition_registry().require(
        "equal_length_ray_path_reduction"
    )
    return definition, tuple(
        definition.expander(
            MacroExpansionRequest(
                macro_id=definition.macro_id,
                call_id="reduce_path",
                scope_id="ii",
                authored_roles={},
                builder_context=builder_context,
                max_candidates=32,
            )
        )
    )


def test_equal_length_macro_expands_roles_times_four_general_strategies() -> None:
    definition, candidates = _expanded_candidates()

    assert {item.strategy_id for item in candidates} == {
        "direct_intersection",
        "reflection_straightening",
        "segment_endpoint_0",
        "segment_endpoint_1",
    }
    assert len(candidates) == 4
    for candidate in candidates:
        assert candidate.fragment.blueprint_id == (
            definition.blueprint.blueprint_version
        )
        assert {
            step.capability_id for step in candidate.fragment.steps
        } <= set(definition.blueprint.function_capability_ids)
        assert candidate.fragment.exports["minimum_expression"][0] in {
            step.step_id for step in candidate.fragment.steps
        }

def test_bundle_keeps_expandable_functions_when_duplicate_recipes_are_removed(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    bundle = family_capability_bundle_for_inputs(fixture[3])

    assert "broken_path_straightening_and_select" not in bundle.catalog.items
    assert "path_minimum_by_straightened_distance" not in bundle.catalog.items
    blueprint = bundle.macro_blueprints["equal_length_ray_path_reduction"]
    assert set(blueprint.function_capability_ids) <= set(bundle.function_ids)
