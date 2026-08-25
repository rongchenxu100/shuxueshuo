from __future__ import annotations

import pytest

from shuxueshuo_server.solver.contracts import PointRef, TypedValue
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    family_capability_bundle_for_inputs,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.functional_subplan import (
    FragmentRuntimeSource,
    FunctionalPlanFragment,
    FunctionalPlanFragmentTransactionalRunner,
    fragment_published_condition_refs,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    ConditionReadSource,
    EntityIdentityReadSource,
    InvocationResultReadSource,
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
        assert candidate.fragment.source == "macro"
        assert candidate.fragment.blueprint_id == (
            definition.blueprint.blueprint_version
        )
        assert {
            step.capability_id for step in candidate.fragment.steps
        } <= set(definition.blueprint.function_capability_ids)
        assert candidate.fragment.exports["minimum_expression"][0] in {
            step.step_id for step in candidate.fragment.steps
        }


def test_transparent_macro_fragment_can_be_reauthored_as_the_same_llm_graph() -> None:
    _definition, candidates = _expanded_candidates()
    macro_fragment = next(
        item.fragment
        for item in candidates
        if item.strategy_id == "reflection_straightening"
    )
    llm_fragment = FunctionalPlanFragment(
        source="llm",
        scope_id=macro_fragment.scope_id,
        steps=macro_fragment.steps,
        exports=macro_fragment.exports,
        dependency_envelope=macro_fragment.dependency_envelope,
        blueprint_id=macro_fragment.blueprint_id,
    )

    assert llm_fragment.fragment_signature == macro_fragment.fragment_signature
    assert all(step.capability_id for step in llm_fragment.steps)


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


def test_macro_and_llm_fragments_execute_the_same_public_function_graph(
    tmp_path,
) -> None:
    _definition, candidates = _expanded_candidates()
    macro_fragment = next(
        item.fragment
        for item in candidates
        if item.strategy_id == "direct_intersection"
    )
    llm_fragment = FunctionalPlanFragment(
        source="llm",
        scope_id=macro_fragment.scope_id,
        steps=macro_fragment.steps,
        exports=macro_fragment.exports,
        dependency_envelope=macro_fragment.dependency_envelope,
        blueprint_id=macro_fragment.blueprint_id,
    )
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    runner = FunctionalPlanFragmentTransactionalRunner(
        FunctionSpecRegistry.from_family_spec(
            fixture[3].family_spec,
            fixture[3].method_specs,
        ),
        fixture[3].method_specs,
    )
    points = {
        "C": (0, 0),
        "B": (2, 0),
        "D": (0, 1),
        "G": (0, 1),
        "M": (1, 0),
        "O": (0, -1),
    }
    _context, _registry, facts = _equal_length_role_authority(structured=True)

    def execute(fragment: FunctionalPlanFragment):
        context = ContextBuilder().build(fixture[2])

        def resolve(
            ref: str,
            view_mode: str,
            runtime_type: str,
        ) -> FragmentRuntimeSource:
            token = stable_hash(
                {"ref": ref, "view_mode": view_mode, "runtime_type": runtime_type}
            )[:16]
            path = f"$problem.facts.fragment_source_{token}"
            if ref in points:
                if view_mode == "identity":
                    value = PointRef(ref, path, scope_id="problem")
                    typed = TypedValue("PointRef", value, source=ref)
                    read_source = EntityIdentityReadSource(ref, path)
                else:
                    value = points[ref]
                    typed = TypedValue("Point", value, source=ref)
                    read_source = InvocationResultReadSource(
                        "fixture_source",
                        ref,
                        path,
                    )
            else:
                value = facts[ref]
                typed = TypedValue("Condition", value, source=ref)
                read_source = ConditionReadSource(ref, path)
            context.write_path(path, typed, from_scope_id="problem")
            return FragmentRuntimeSource(
                ref,
                runtime_type,
                value,
                stable_hash({"ref": ref, "view_mode": view_mode}),
                runtime_path=path,
                read_source=read_source,
            )

        return runner.execute(
            fragment,
            context=context,
            source_resolver=resolve,
        )

    macro_execution = execute(macro_fragment)
    llm_execution = execute(llm_fragment)

    assert macro_execution.passed
    assert macro_execution.standard_outputs["minimum_expression"] == 3
    assert macro_execution.execution_signature == llm_execution.execution_signature
    macro_conditions = fragment_published_condition_refs(
        macro_fragment,
        macro_execution,
    )
    llm_conditions = fragment_published_condition_refs(
        llm_fragment,
        llm_execution,
    )
    assert macro_conditions == llm_conditions
    assert "path_attainment" in macro_conditions
    assert [item.capability_id for item in macro_execution.step_executions] == [
        item.capability_id for item in macro_fragment.steps
    ]
