from __future__ import annotations

from dataclasses import replace
import json
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
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationRequest,
    _build_equal_length_ray_preparation_context,
)
from shuxueshuo_server.solver.runtime.macro_plan_materialization import (
    MacroPlanMaterializationError,
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
from shuxueshuo_server.solver.runtime.scoped_functional_plan_replay import (
    ScopedFunctionalPlanReplayService,
)
from shuxueshuo_server.solver.runtime import (
    functional_transaction_execution as transaction_module,
    scoped_functional_plan_replay as scoped_replay_module,
)
from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


pytestmark = pytest.mark.solver_contract


def _definition():
    return default_macro_definition_registry().require(
        "equal_length_ray_path_reduction"
    )


def _materialized_replay(tmp_path: Path):
    case = "tj-2026-heping-yimo-25"
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path / case, case=case)
    return ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(load_v3_fixture_payload(case), ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )


def test_scoped_replay_audits_materialized_winner_outputs(
    tmp_path,
    monkeypatch,
) -> None:
    observed: list[tuple[str, bool]] = []
    original = scoped_replay_module.verify_macro_expansion_clean_outputs

    def track(record, execution_report):
        observed.append((record.macro_step_id, execution_report is not None))
        return original(record, execution_report)

    monkeypatch.setattr(
        scoped_replay_module,
        "verify_macro_expansion_clean_outputs",
        track,
    )

    replay = _materialized_replay(tmp_path)

    assert replay.macro_expansions
    assert observed == [("reduce_equal_length_ray_path_ii", True)]


def test_scoped_replay_rejects_materialized_winner_output_drift(
    tmp_path,
    monkeypatch,
) -> None:
    original = scoped_replay_module.materialize_macro_winner

    def corrupt_winner_signature(*args, **kwargs):
        plan, record = original(*args, **kwargs)
        return plan, replace(record, winner_output_signature="drifted")

    monkeypatch.setattr(
        scoped_replay_module,
        "materialize_macro_winner",
        corrupt_winner_signature,
    )

    with pytest.raises(MacroPlanMaterializationError) as error:
        _materialized_replay(tmp_path)

    assert error.value.code == "planner.macro_winner_replay_drift"


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
        "ordinary_plan_execution"
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


def test_macro_winner_is_the_only_f5c_role_authority(tmp_path) -> None:
    replay = _materialized_replay(tmp_path)
    report = replay.replay.transactional_execution_report
    assert report is not None
    assert len(replay.macro_expansions) == 1
    expansion = replay.macro_expansions[0]
    assert expansion.macro_step_id not in {
        item.call_id for item in report.compiled_calls
    }
    compiled = next(
        item
        for item in report.compiled_calls
        if any(
            invocation.method_id
            == "construct_point_on_ray_at_reference_distance"
            for plan in item.plans
            for invocation in plan.invocations
        )
    )
    binding = compiled.problem_call_binding
    assert binding is not None
    by_arg = {item.arg_name: item for item in binding.input_bindings}

    def source_label(role: str) -> str:
        source = by_arg[role].typed_source
        object_id = source.math_object_id
        if object_id is None:
            object_id = source.state_version_id.slot_id.logical_key.object_id
        return object_id.value.rsplit(":", 1)[-1]

    assert {
        role: source_label(role)
        for role in ("anchor", "reference_point", "ray_point")
    } == {
        "anchor": "C",
        "reference_point": "B",
        "ray_point": "D",
    }
    assert compiled.problem_source_provenance is not None
    assert expansion.search_signature


def test_macro_clean_replay_executes_materialized_ordinary_steps(tmp_path) -> None:
    replay = _materialized_replay(tmp_path)
    report = replay.replay.transactional_execution_report
    assert report is not None
    expansion = replay.macro_expansions[0]
    generated = {
        item.call_id: item
        for item in report.compiled_calls
        if item.call_id in expansion.generated_step_ids
    }
    assert set(generated) == set(expansion.generated_step_ids)
    assert all(item.plans for item in generated.values())
    method_ids = {
        invocation.method_id
        for item in generated.values()
        for plan in item.plans
        for invocation in plan.invocations
    }
    assert method_ids >= {
        "construct_point_on_ray_at_reference_distance",
        "verify_distance_equality",
        "verify_two_segment_path_attainment",
    }


def test_fragment_runner_is_used_only_for_shadow_candidates(
    tmp_path,
    monkeypatch,
) -> None:
    case = "tj-2026-heping-yimo-25"
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path / case, case=case)
    shadow_calls = 0
    captured = None
    original_shadow_execute = (
        transaction_module._execute_macro_candidate_shadow_fragment
    )

    def track_shadow(*args, **kwargs):
        nonlocal shadow_calls
        shadow_calls += 1
        return original_shadow_execute(*args, **kwargs)

    class StopAfterSearch(RuntimeError):
        pass

    def stop_before_materialization(_plan, request, **_kwargs):
        nonlocal captured
        captured = request
        raise StopAfterSearch

    monkeypatch.setattr(
        transaction_module,
        "_execute_macro_candidate_shadow_fragment",
        track_shadow,
    )
    monkeypatch.setattr(
        scoped_replay_module,
        "materialize_macro_winner",
        stop_before_materialization,
    )

    with pytest.raises(StopAfterSearch):
        ScopedFunctionalPlanReplayService().replay_raw_json(
            json.dumps(load_v3_fixture_payload(case), ensure_ascii=False),
            inputs=inputs,
            planning_context=planning_context,
            problem_binding_catalog=binding_catalog,
            handle_registry=registry,
            context=ContextBuilder().build(problem),
            planner_state_context=planner_context,
            problem_payload=problem_payload,
        )

    assert captured is not None
    evaluations = captured.authority.search_report.evaluations
    assert evaluations
    assert shadow_calls == len(evaluations)


def test_generated_steps_read_finalized_f5c_exact_runtime_pins(tmp_path) -> None:
    replay = _materialized_replay(tmp_path)
    report = replay.replay.transactional_execution_report
    assert report is not None
    expansion = replay.macro_expansions[0]
    generated = tuple(
        item
        for item in report.compiled_calls
        if item.call_id in expansion.generated_step_ids
    )
    assert generated
    assert all(
        invocation.input_read_authorities
        for item in generated
        for plan in item.plans
        for invocation in plan.invocations
        if invocation.inputs
    )
