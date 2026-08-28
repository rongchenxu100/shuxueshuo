from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
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
    ):
        assert hidden_name not in prompt_text


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
