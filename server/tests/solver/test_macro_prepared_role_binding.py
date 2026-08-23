from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.contracts import (
    ExactCallResultSourceSpec,
    MacroPreparedRoleSourceSpec,
    MethodInputBindingSpec,
    PreviousOutputIdentityDerivationSpec,
)
from shuxueshuo_server.solver.runtime.equal_length_ray_path_search import (
    _prepared_runtime_arg_value,
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
    build_equal_length_ray_macro_role_candidates,
    build_equal_length_ray_point_name_candidates,
    default_macro_implementation_registry,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchError,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    InvocationResultReadSource,
    StateVersionReadSource,
)

from test_functional_transaction_execution import _replay


pytestmark = pytest.mark.solver_contract


def _implementation():
    return default_macro_implementation_registry()._items[
        "equal_length_ray_path_reduction"
    ]


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
    point_names = build_equal_length_ray_point_name_candidates(
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


def test_registry_owns_every_equal_length_internal_method_input() -> None:
    bindings = {
        item.target: item.binding
        for item in _implementation().method_input_bindings
    }

    assert set(bindings) == {
        "equal_length_ray_point.anchor",
        "equal_length_ray_point.reference_point",
        "equal_length_ray_point.ray_point",
        "equal_length_ray_point.target",
        "distance_between_points.p1",
        "distance_between_points.p2",
    }
    assert {
        bindings[name].source.role
        for name in (
            "equal_length_ray_point.anchor",
            "equal_length_ray_point.reference_point",
            "equal_length_ray_point.ray_point",
            "distance_between_points.p1",
        )
        if isinstance(bindings[name].source, MacroPreparedRoleSourceSpec)
    } == {"anchor", "reference_point", "ray_point", "fixed_point"}
    assert isinstance(
        bindings["equal_length_ray_point.target"].derivation,
        PreviousOutputIdentityDerivationSpec,
    )
    assert isinstance(
        bindings["distance_between_points.p2"].source,
        ExactCallResultSourceSpec,
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
    with pytest.raises(MacroRuntimeSearchError) as error:
        build_equal_length_ray_macro_role_candidates(preparation.payload)
    assert error.value.code == "planner.macro_point_name_ambiguous"
    assert error.value.retryability == "configuration"
    assert error.value.details == {
        "macro_id": "equal_length_ray_path_reduction",
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

    candidates = build_equal_length_ray_macro_role_candidates(context)

    assert len(candidates) == 1
    assert dict(candidates[0].roles) == {
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


def test_macro_clean_replay_uses_canonical_paths_and_exact_internal_result() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    invocations = {
        item.method_id: item
        for plan in compiled.replay_plans
        for item in plan.invocations
    }

    for input_name in ("anchor", "reference_point", "ray_point"):
        source = invocations["equal_length_ray_point"].input_read_authorities[
            input_name
        ][0].source
        assert isinstance(source, StateVersionReadSource)
        assert "__functional_transaction_" not in source.runtime_path
    p2 = invocations["distance_between_points"].input_read_authorities["p2"][
        0
    ].source
    assert isinstance(p2, InvocationResultReadSource)
    assert p2.invocation_id.endswith(".equal_length_ray_point")
    assert p2.return_name == "point"


def test_witness_reads_the_registry_owned_state_pin() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    invocation = compiled.plans[0].invocations[0]
    source = invocation.input_read_authorities["anchor"][0].source
    value = report.runtime_version_values[source.state_version_id]
    declaration = next(
        item
        for item in _implementation().method_input_bindings
        if item.target == "equal_length_ray_point.anchor"
    )
    prepared = SimpleNamespace(
        macro_method_inputs=(
            SimpleNamespace(declaration=declaration, source=source),
        ),
        state_reads=(
            SimpleNamespace(
                selected_version_id=source.state_version_id,
                runtime_value=value,
                arg_name="$macro.equal_length_ray_point.anchor",
            ),
        ),
        arg_bindings=(),
    )

    assert _prepared_runtime_arg_value(prepared, "anchor") == value
