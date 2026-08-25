from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.contracts import (
    MethodInputBindingSpec,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationRequest,
    _build_equal_length_ray_preparation_context,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    MacroDefinitionError,
    build_point_name_candidates,
    default_macro_definition_registry,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchError,
)
from shuxueshuo_server.solver.runtime.recipes import (
    EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC,
)
from test_functional_transaction_execution import _replay


pytestmark = pytest.mark.solver_contract


def _definition():
    return default_macro_definition_registry().require(
        "equal_length_ray_path_reduction"
    )


def _equal_length_role_authority(*, structured: bool):
    points = {
        "point:problem:C": {"type": "point", "name": "C"},
        "point:ii:C": {"type": "point", "name": "C"},
        "point:problem:B": {"type": "point", "name": "B"},
        "point:problem:D": {"type": "point", "name": "D"},
        "point:problem:G": {"type": "point", "name": "G"},
        "point:problem:M": {"type": "point", "name": "M"},
        "point:problem:O": {"type": "point", "name": "O"},
    }
    entities = {
        **points,
        "ray:problem:CD": {
            "type": "ray",
            "origin": "point:problem:C",
            "through": "point:problem:D",
        },
        "segment:problem:CB": {
            "type": "segment",
            "endpoints": ["point:problem:C", "point:problem:B"],
        },
    }
    equal_payload = {
        "left": (
            ["point:problem:C", "point:problem:G"]
            if structured
            else "CG"
        ),
        "right": (
            ["point:problem:C", "point:problem:M"]
            if structured
            else "CM"
        ),
    }
    target_payload = (
        {
            "terms": [
                ["point:problem:O", "point:problem:M"],
                ["point:problem:B", "point:problem:G"],
            ]
        }
        if structured
        else {"path": "OM+BG"}
    )
    facts = {
        "fact:ii:point_on_ray": {
            "type": "point_on_ray",
            "point": "point:problem:G",
            "ray": "ray:problem:CD",
        },
        "fact:ii:point_on_segment": {
            "type": "point_on_segment",
            "point": "point:problem:M",
            "segment": "segment:problem:CB",
        },
        "fact:ii:equal_length": {
            "type": "equal_length_condition",
            **equal_payload,
        },
        "fact:ii:path_target": {
            "type": "path_minimum_target",
            **target_payload,
        },
    }
    point_names = build_point_name_candidates(
        point_handles=points,
        entity_payloads=entities,
    )
    context = {
        "entity_payloads": entities,
        "point_name_candidates": point_names,
        "ray_facts": (("fact:ii:point_on_ray", facts["fact:ii:point_on_ray"]),),
        "segment_facts": (
            ("fact:ii:point_on_segment", facts["fact:ii:point_on_segment"]),
        ),
        "equal_facts": (("fact:ii:equal_length", facts["fact:ii:equal_length"]),),
        "target_facts": (("fact:ii:path_target", facts["fact:ii:path_target"]),),
        "max_candidates": 32,
    }
    valid_scopes = {
        handle: ("ii" if handle.startswith("point:ii:") else "problem")
        for handle in entities
    }
    valid_scopes.update({handle: "ii" for handle in facts})
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset({"problem", "ii"}),
        entity_handles=frozenset(entities),
        fact_handles=frozenset(facts),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        fact_types={handle: payload["type"] for handle, payload in facts.items()},
        handle_valid_scopes=valid_scopes,
        entity_payloads=entities,
        fact_payloads=facts,
    )
    return context, registry, facts


def test_definition_owns_equal_length_search_and_function_fragment() -> None:
    definition = _definition()

    assert definition.search_contract.searchable_roles == (
        "anchor",
        "reference_point",
        "ray_point",
        "fixed_point",
    )
    assert definition.search_contract.validation_policy_id == (
        "verified_function_fragment"
    )
    assert definition.search_contract.evidence_builder_id == (
        "verified_subplan_execution"
    )
    assert {
        "construct_point_on_ray_at_reference_distance",
        "verify_distance_equality",
        "verify_two_segment_path_attainment",
    } <= set(definition.blueprint.function_capability_ids)
    assert EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC.method_sequence == ()
    assert EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC.execution_strategy == (
        "verified_function_fragment_presentation"
    )


def test_equal_length_role_provider_is_removed_and_families_are_strict() -> None:
    runtime_root = (
        Path(__file__).resolve().parents[2]
        / "shuxueshuo_server/solver/runtime"
    )
    assert not (runtime_root / "debug_equal_length_ray_roles.py").exists()
    assert all(
        isinstance(binding, MethodInputBindingSpec)
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )


def test_equal_length_preparation_preserves_ambiguous_point_name_authority() -> None:
    _context, registry, facts = _equal_length_role_authority(structured=False)
    resolved_args = {
        "point_on_ray": (SimpleNamespace(handle="fact:ii:point_on_ray"),),
        "point_on_segment": (
            SimpleNamespace(handle="fact:ii:point_on_segment"),
        ),
        "equal_length_condition": (
            SimpleNamespace(handle="fact:ii:equal_length"),
        ),
        "path_minimum_target": (
            SimpleNamespace(handle="fact:ii:path_target"),
        ),
    }
    request = MacroPreparationRequest(
        planning_context_id="context:test",
        problem_revision_id="revision:test",
        problem_semantic_hash="semantic:test",
        plan_id="plan:test",
        call_id="reduce_path",
        goal_unit_ids=("ii.a",),
        scope_id="ii",
        macro_id="equal_length_ray_path_reduction",
        catalog_signature="catalog:test",
        authored_roles={},
        candidate_dependency_envelope=(),
        upstream_exact_state_signature="state:test",
        environment=SimpleNamespace(
            prepared_call=SimpleNamespace(
                execution_scope_id="ii",
                reconciliation=SimpleNamespace(resolved_args=resolved_args),
            ),
            handle_registry=registry,
            max_candidates=32,
        ),
    )

    preparation = _build_equal_length_ray_preparation_context(request)

    assert preparation.payload["point_name_candidates"]["C"] == (
        "point:ii:C",
        "point:problem:C",
    )
    assert set(facts) <= set(preparation.candidate_dependency_envelope)
    with pytest.raises(MacroDefinitionError) as error:
        default_macro_definition_registry().project_role_bindings(
            "equal_length_ray_path_reduction",
            builder_context=preparation.payload,
            max_candidates=32,
        )
    assert error.value.code == "planner.macro_point_name_ambiguous"
    assert not error.value.retryable
    assert error.value.details == {
        "name": "C",
        "candidate_count": 2,
        "candidates": ("point:ii:C", "point:problem:C"),
    }


def test_equal_length_prompt_projection_does_not_swallow_ambiguous_name() -> None:
    _context, registry, facts = _equal_length_role_authority(structured=False)
    semantic_index = FunctionalSemanticIndex(
        (),
        handle_registry=registry,
        entity_payloads=registry.entity_payloads,
        fact_payloads=facts,
        relation_authority_views=(),
    )

    with pytest.raises(MacroRuntimeSearchError) as error:
        semantic_index.macro_role_ref_candidates(
            "equal_length_ray_path_reduction"
        )

    assert error.value.code == "planner.macro_point_name_ambiguous"
    assert error.value.details["name"] == "C"


def test_structured_equal_length_roles_allow_duplicate_display_names() -> None:
    context, _registry, _facts = _equal_length_role_authority(structured=True)

    candidates = default_macro_definition_registry().project_role_bindings(
        "equal_length_ray_path_reduction",
        builder_context=context,
        max_candidates=32,
    )

    assert len(candidates) == 1
    assert dict(candidates[0]) == {
        "anchor": "point:problem:C",
        "fixed_point": "point:problem:O",
        "ray_point": "point:problem:D",
        "reference_point": "point:problem:B",
    }


def test_macro_winner_is_the_only_f5c_role_authority() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    binding = compiled.problem_call_binding
    assert binding is not None

    assert dict(binding.authored_roles) == {}
    assert dict(binding.chosen_roles) == {
        "anchor": "point:problem:C",
        "fixed_point": "point:problem:O",
        "ray_point": "point:problem:D",
        "reference_point": "point:problem:B",
    }
    assert binding.macro_preparation_signature
    assert binding.macro_search_signature
    assert compiled.problem_source_provenance is not None
    assert (
        compiled.problem_source_provenance.macro_search_signature
        == binding.macro_search_signature
    )


def test_macro_clean_replay_executes_only_the_selected_function_fragment() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    assert compiled.plans == ()
    assert compiled.replay_plans == ()
    assert compiled.output_write_authorities == ()
    execution = compiled.fragment_execution
    assert execution is not None and execution.passed
    assert execution.standard_outputs["minimum_expression"] is not None
    assert {
        item.capability_id for item in execution.step_executions
    } >= {
        "construct_point_on_ray_at_reference_distance",
        "verify_distance_equality",
        "verify_two_segment_path_attainment",
    }
    assert all(item.runtime_path for item in compiled.public_returns)


def test_fragment_reads_finalized_f5c_identity_and_exact_runtime_pins() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    binding = compiled.problem_call_binding
    assert binding is not None
    by_arg = {item.arg_name: item for item in binding.input_bindings}
    for role in ("anchor", "reference_point", "ray_point", "fixed_point"):
        source = by_arg[role].typed_source
        assert source is not None
        assert source.math_object_id is not None or source.state_version_id is not None
        if source.state_version_id is not None:
            assert source.state_version_id in report.runtime_version_values
    preparation = compiled.macro_preparation_authority
    assert preparation is not None
    assert preparation.upstream_exact_state_signature
    execution = compiled.fragment_execution
    assert execution is not None
    assert all(
        item.source_authority_signatures
        for item in execution.step_executions
        if item.capability_id
        in {
            "construct_point_on_ray_at_reference_distance",
            "distance_between_points",
        }
    )
