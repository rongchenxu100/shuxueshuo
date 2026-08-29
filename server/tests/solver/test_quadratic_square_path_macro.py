from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from _scoped_functional_plan_support import load_v2_fixture_payload
from test_functional_goal_execution import _checkpoint_steps, _execute

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context_closure import (
    QUADRATIC_SQUARE_PATH_ROLES_RESOLVER,
    context_closure_resolver,
)
from shuxueshuo_server.solver.runtime.functional_path_context_resolvers import (
    resolve_quadratic_square_path_args,
)
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.quadratic_square_path_roles import (
    build_quadratic_square_path_role_candidates,
)


pytestmark = pytest.mark.solver_contract

ROOT = Path(__file__).resolve().parents[3]
CASE = "tj-2026-heping-ermo-25"
MACRO_ID = "quadratic_square_path_minimum"
KERNEL_ID = "quadratic_square_path_minimum_kernel"


def _square_macro_capability():
    problem = load_problem_ir(
        ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.json"
    )
    family = DEFAULT_FAMILY_REGISTRY.match(problem)
    assert family is not None
    capability = FunctionalCapabilityCatalog.from_family_spec(
        family,
        MethodSpecRegistry.load_from_code(),
    ).get("quadratic_square_path_minimum")
    assert capability is not None
    return capability


def _resolve_square_roles(registry, resolved_args):
    capability = _square_macro_capability()
    return resolve_quadratic_square_path_args(
        capability,
        FunctionalCall(
            call_id="minimum",
            capability_id=capability.capability_id,
            args={},
            return_bindings={},
            strategy="test",
            reason="test",
        ),
        resolved_args,
        context_closure_resolver(QUADRATIC_SQUARE_PATH_ROLES_RESOLVER),
        call_id="minimum",
        scope_id="ii",
        produced={},
        semantic_index=FunctionalSemanticIndex(
            (),
            handle_registry=registry,
            relation_authority_views=(),
        ),
        handle_registry=registry,
    )


def _resolved_square_public_args(registry):
    return {
        "path_minimum_target": (
            ResolvedFunctionalValue(
                handle="fact:ii:path",
                runtime_type="Condition",
                valid_scope="ii",
            ),
        ),
        "square": (
            ResolvedFunctionalValue(
                handle="fact:problem:square",
                runtime_type="Condition",
                valid_scope="problem",
            ),
        ),
        "parabola": (
            ResolvedFunctionalValue(
                handle="function:problem:q",
                runtime_type="Parabola",
                valid_scope="problem",
                object_ref="function:problem:q",
            ),
        ),
    }


def _registry(vertices: tuple[str, ...]) -> CanonicalHandleRegistry:
    points = {
        handle: {"type": "point", "name": handle.rsplit(":", 1)[-1]}
        for handle in (
            "point:problem:U",
            "point:problem:V",
            "point:problem:W",
            "point:problem:Z",
            "point:problem:F",
            "point:problem:H",
            "point:problem:M",
        )
    }
    points["point:problem:M"].update(
        {"definition": "axis_x_intercept", "of": "function:problem:q"}
    )
    facts = {
        "fact:ii:path": {
            "type": "path_minimum_target",
            "terms": [
                ["point:problem:H", "point:problem:F"],
                ["point:problem:F", "point:problem:M"],
                ["point:problem:M", "point:problem:Z"],
            ],
        },
        "fact:problem:square": {
            "type": "square",
            "vertices": list(vertices),
        },
        "fact:ii:midpoint": {
            "type": "midpoint_definition",
            "point": "point:problem:F",
            "of": ["point:problem:U", "point:problem:V"],
        },
        "fact:ii:center": {
            "type": "square_center",
            "point": "point:problem:H",
            "square": "fact:problem:square",
        },
        "fact:problem:axis": {
            "type": "axis_membership",
            "point": "point:problem:V",
            "axis_of": "function:problem:q",
        },
    }
    entities = {
        **points,
        "function:problem:q": {"type": "function", "name": "q"},
    }
    handles = frozenset(entities)
    fact_handles = frozenset(facts)
    return CanonicalHandleRegistry(
        scope_ids=frozenset({"problem", "ii"}),
        scope_parents={"problem": None, "ii": "problem"},
        entity_handles=handles,
        fact_handles=fact_handles,
        answer_handles=frozenset(),
        fact_types={key: value["type"] for key, value in facts.items()},
        handle_valid_scopes={
            **{key: "problem" for key in entities},
            **{
                key: ("ii" if key.startswith("fact:ii:") else "problem")
                for key in facts
            },
        },
        entity_payloads=entities,
        fact_payloads=facts,
    )


@pytest.mark.parametrize(
    "vertices",
    (
        (
            "point:problem:U",
            "point:problem:V",
            "point:problem:W",
            "point:problem:Z",
        ),
        (
            "point:problem:W",
            "point:problem:Z",
            "point:problem:U",
            "point:problem:V",
        ),
        (
            "point:problem:V",
            "point:problem:U",
            "point:problem:Z",
            "point:problem:W",
        ),
    ),
)
def test_roles_are_structural_across_vertex_orderings(vertices) -> None:
    candidates = build_quadratic_square_path_role_candidates(
        path_minimum_target="fact:ii:path",
        square="fact:problem:square",
        parabola_ref="function:problem:q",
        scope_id="ii",
        registry=_registry(vertices),
    )

    assert len(candidates) == 1
    roles = candidates[0]
    assert roles.side_start == "point:problem:U"
    assert roles.axis_point == "point:problem:V"
    assert roles.moving_point == "point:problem:Z"
    assert roles.fixed_endpoint == "point:problem:M"


def test_catalog_exposes_only_three_public_inputs_and_two_outputs() -> None:
    problem = load_problem_ir(
        ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.json"
    )
    family = DEFAULT_FAMILY_REGISTRY.match(problem)
    assert family is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        family,
        MethodSpecRegistry.load_from_code(),
    )
    capability = catalog.get("quadratic_square_path_minimum")
    assert capability is not None

    assert tuple(item.name for item in capability.args) == (
        "parabola",
        "path_minimum_target",
        "square",
    )
    assert tuple(item.name for item in capability.returns) == (
        "minimum_expression",
        "attainment_point",
    )
    minimum_return = next(
        item
        for item in capability.returns
        if item.name == "minimum_expression"
    )
    assert minimum_return.possible_forms == (
        "open_expression",
        "closed_value",
    )
    attainment_return = next(
        item
        for item in capability.returns
        if item.name == "attainment_point"
    )
    assert minimum_return.reference_mode == "default"
    assert attainment_return.reference_mode == "exact_result"
    assert attainment_return.to_prompt_payload()["reference_mode"] == (
        "exact_result"
    )
    assert attainment_return.binding_mode == "exact_call_result_or_answer"
    prompt_text = json.dumps(capability.to_prompt_payload(), ensure_ascii=False)
    for hidden_name in (
        "midpoint_definition",
        "square_center",
        "axis_membership",
        "side_start",
        "axis_point",
        "moving_point",
        "fixed_endpoint",
        "PathTransformation",
        "PathWitness",
        "#quadratic-square-reflection",
        "straightening_auxiliary_point",
    ):
        assert hidden_name not in prompt_text


def test_square_macro_keeps_internal_composition_out_of_public_results(
    tmp_path,
) -> None:
    result, _fixture = _execute(
        tmp_path,
        CASE,
        load_v2_fixture_payload(CASE),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    macro_step = _checkpoint_steps(checkpoint)["derive_path_minimum_ii"]
    assert macro_step.status == "runtime_verified"
    assert {item["return"] for item in macro_step.actual_outputs} == {
        "minimum_expression",
        "attainment_point",
    }
    witnesses = [
        item
        for item in macro_step.evidence
        if isinstance(item, PathMinimumWitness)
    ]
    assert len(witnesses) == 1
    report = result.replay.transactional_attempt_result.execution_report
    call_result = next(
        item
        for item in report.call_results
        if item.call_id == "derive_path_minimum_ii"
    )
    assert call_result.step_results[0].methods_used == [KERNEL_ID]
    assert [
        item.method_id
        for item in call_result.step_results[0].trace_fragments
    ] == [KERNEL_ID]

    public_projection = json.dumps(
        {
            "outputs": [dict(item) for item in macro_step.actual_outputs],
            "evidence": [item.to_payload() for item in witnesses],
        },
        ensure_ascii=False,
    )
    assert "#quadratic-square-reflection" not in public_projection
    assert "PointRef" not in public_projection
    assert "PathTransformation" not in public_projection


def test_role_search_returns_no_candidate_for_disconnected_path() -> None:
    registry = _registry(
        (
            "point:problem:U",
            "point:problem:V",
            "point:problem:W",
            "point:problem:Z",
        )
    )
    disconnected = {
        **registry.fact_payloads,
        "fact:ii:path": {
            "type": "path_minimum_target",
            "terms": [
                ["point:problem:H", "point:problem:F"],
                ["point:problem:F", "point:problem:M"],
                ["point:problem:M", "point:problem:W"],
            ],
        },
    }
    registry = CanonicalHandleRegistry(
        scope_ids=registry.scope_ids,
        scope_parents=registry.scope_parents,
        entity_handles=registry.entity_handles,
        fact_handles=registry.fact_handles,
        answer_handles=registry.answer_handles,
        fact_types=registry.fact_types,
        handle_valid_scopes=registry.handle_valid_scopes,
        entity_payloads=registry.entity_payloads,
        fact_payloads=disconnected,
    )

    assert build_quadratic_square_path_role_candidates(
        path_minimum_target="fact:ii:path",
        square="fact:problem:square",
        parabola_ref="function:problem:q",
        scope_id="ii",
        registry=registry,
    ) == ()


def test_context_resolver_fails_loud_when_public_inputs_are_not_unique() -> None:
    registry = _registry(
        (
            "point:problem:U",
            "point:problem:V",
            "point:problem:W",
            "point:problem:Z",
        )
    )

    _additions, _repairs, issues, closed = _resolve_square_roles(
        registry,
        {},
    )

    assert closed is False
    assert len(issues) == 1
    assert issues[0].code == "functional.macro_search_public_input_invalid"
    assert issues[0].details == {
        "macro_id": "quadratic_square_path_minimum",
        "expected_candidate_counts": {
            "path_minimum_target": 1,
            "square": 1,
            "parabola": 1,
        },
        "observed_candidate_counts": {
            "path_minimum_target": 0,
            "square": 0,
            "parabola": 0,
        },
        "repair_action": "repair_macro_public_inputs",
        "retryability": "planner_repairable",
    }


@pytest.mark.parametrize(
    ("candidate_count", "expected_code"),
    (
        (0, "functional.macro_search_no_structural_candidate"),
        (2, "functional.macro_search_ambiguous"),
    ),
)
def test_context_resolver_uses_runtime_search_diagnostic_codes(
    monkeypatch,
    candidate_count,
    expected_code,
) -> None:
    registry = _registry(
        (
            "point:problem:U",
            "point:problem:V",
            "point:problem:W",
            "point:problem:Z",
        )
    )
    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.functional_path_context_resolvers."
        "build_quadratic_square_path_role_candidates",
        lambda **_kwargs: tuple(
            SimpleNamespace(candidate_id=f"candidate-{index}")
            for index in range(candidate_count)
        ),
    )

    _additions, _repairs, issues, closed = _resolve_square_roles(
        registry,
        _resolved_square_public_args(registry),
    )

    assert closed is False
    assert len(issues) == 1
    assert issues[0].code == expected_code
    assert issues[0].details is not None
    assert issues[0].details["candidate_count"] == candidate_count
    assert issues[0].details["phase"] == "structural_elaboration"
    assert issues[0].details["retryability"] == "planner_repairable"
