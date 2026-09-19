from dataclasses import replace

import pytest
from _math_runtime_binding_support import (
    CASES,
    assert_expected,
    binding,
    candidate,
    execution_audit,
    replay,
    replay_errors,
    reviewed_authority,
)

from shuxueshuo_server.problem_understanding.runtime_binding import (
    AdmissionEvidence,
    authorize_binding,
)
from shuxueshuo_server.problem_understanding.runtime_lowering import (
    BindingError,
    NotationRuntimeLowerer,
)
from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)


@pytest.mark.parametrize("authored", [False, True], ids=["recorded", "authored"])
@pytest.mark.parametrize("case", CASES)
def test_ten_candidate_bindings_execute_trusted_plans(case, authored, tmp_path):
    b = binding(case, authored)
    r = replay(case, b, tmp_path)
    assert r.status == "accepted", replay_errors(r)
    assert r.verified_execution is not None
    assert r.final_execution.checkpoint.all_required_goals_verified
    assert_expected(case, b, r)
    assert execution_audit(b, r)["committed_versions"]
    from shuxueshuo_server.problem_understanding.compact_planner_input import (
        compact_problem,
    )

    assert sum(
        len(v["facts"])
        for v in compact_problem(b, execution=r.verified_execution)["known_results"]
    ) == len(b.planning_context.goal_views)
    assert all(b.bundle.projection_index.source_unit_runtime_nodes.values())
    assert not hasattr(b.bundle, "verified_problem")
    assert b.bundle.build_solver_problem().expected_answers == {}
    assert b.bundle.normalization_report["ruleset_hash"]
    assert b.artifacts()["normalization-report.json"]["ruleset_hash"] == b.bundle.normalization_report["ruleset_hash"]

    # Every actual source definition/fact/goal has a runtime provenance path.
    def paths(scope, path="/root"):
        for name in ("definitions", "facts", "goals"):
            for i in range(len(scope.get(name, []))):
                yield f"{path}/{name}/{i}"
        for i, c in enumerate(scope.get("children", [])):
            yield from paths(c, f"{path}/children/{i}")

    mapped = {x["path"] for x in b.bundle.provenance.values()}
    assert set(paths(candidate(case, authored)["root"])) <= mapped


def test_binding_alone_cannot_authorize_solver():
    b = binding(CASES[3])
    with pytest.raises(BindingError, match="source_review_required"):
        VerifiedPlannerProblemAuthority.from_bundle(b.bundle)
    ev = AdmissionEvidence(
        **{k: v for k, v in b.source_identity.items() if k != "problem_id"},
        review_run_id="review",
        review_current=True,
    )
    for field, value in [
        ("candidate_id", "different"),
        ("candidate_hash", "different"),
        ("source_hash", "different"),
        ("source_version_id", "different"),
    ]:
        with pytest.raises(BindingError, match="version_changed"):
            authorize_binding(b, replace(ev, **{field: value}))
    with pytest.raises(BindingError, match="source_review_required"):
        authorize_binding(b, replace(ev, review_current=False))
    assert reviewed_authority(b).bundle.admission_evidence


def test_local_same_named_points_and_coordinate_aliases_keep_identity():
    b = binding(CASES[3])
    raw = b.bundle.canonical_solver_input
    assert {e["scope_id"] for e in raw["entities"] if e["name"] == "A"} == {"ii", "iii"}
    symbols = {e["name"]: e for e in raw["entities"] if e["entity_type"] == "symbol"}
    assert symbols["y_M"]["role"] == "coordinate_alias"
    assert symbols["n"]["role"] == "dynamic_parameter"
    assert symbols["b"]["role"] == "quadratic_coefficient"
    point = next(e for e in raw["entities"] if e["name"] == "M")
    assert point["definition"] == "point_on_parabola_at_x"
    assert point["x"] == "b + 1/2"


def test_point_on_curve_with_explicit_self_ordinate_lowers_as_curve_at_x():
    raw = candidate(CASES[4])
    raw["root"]["children"][1]["facts"][0] = "D = (b+2, y(D))"

    bound = binding(CASES[4], payload=raw)
    points = [
        entity
        for entity in bound.bundle.canonical_solver_input["entities"]
        if entity["name"] == "D"
    ]
    assert points and points[0]["definition"] == "point_on_parabola_at_x"
    assert points[0]["x"] == "b + 2"


def test_positive_axis_coordinate_promotes_motion_symbol_constraint(tmp_path):
    raw = candidate(CASES[3], authored=True)
    part_iii = raw["root"]["children"][2]
    part_iii["facts"] = [
        "x(N)>0" if item == "n > 0" else item
        for item in part_iii["facts"]
    ]

    bound = binding(CASES[3], authored=True, payload=raw)
    constraints = [
        authority.semantic_ref.ref
        for authority in bound.planning_context.ref_authorities.values()
        if authority.semantic_ref.value_type == "symbol_constraint"
    ]

    assert "symbol_constraint_n" in constraints
    result = replay(CASES[3], bound, tmp_path)
    assert result.status == "accepted", replay_errors(result)


def test_shared_endpoint_perpendicular_lowers_to_right_angle():
    raw = candidate("tj-2026-hexi-yimo-25", authored=True)
    ii = raw["root"]["children"][1]
    ii["facts"][5] = "line(A,C) ⟂ line(A,D)"

    bound = binding("tj-2026-hexi-yimo-25", payload=raw)
    ii_scope = bound.bundle.source_graph.root_scope.children[1]
    right_angle = next(
        fact for fact in ii_scope.facts if fact.kind == "right_angle"
    )
    assert right_angle.attributes["angle"] == {
        "start": "C",
        "vertex": "A",
        "end": "D",
    }
    assert any(
        fact.kind == "math_assertion"
        and "⟂" in fact.attributes["expression"]
        for fact in ii_scope.facts
    )
    assert any(
        fact["type"] == "right_angle_equal_length"
        for fact in bound.bundle.canonical_solver_input["facts"]
    )


def test_direct_angle_expression_lowers_to_the_same_right_angle_method_fact():
    raw = candidate("tj-2026-hexi-yimo-25", authored=True)
    ii = raw["root"]["children"][1]
    ii["facts"][5] = "∠CAD=90°"

    bound = binding("tj-2026-hexi-yimo-25", payload=raw)
    ii_scope = bound.bundle.source_graph.root_scope.children[1]
    right_angle = next(fact for fact in ii_scope.facts if fact.kind == "right_angle")
    assert right_angle.attributes["angle"] == {
        "start": "C",
        "vertex": "A",
        "end": "D",
    }
    assert any(
        fact["type"] == "right_angle_equal_length"
        for fact in bound.bundle.canonical_solver_input["facts"]
    )


def test_perpendicular_without_shared_endpoint_fails_explicitly():
    raw = candidate("tj-2026-hexi-yimo-25", authored=True)
    ii = raw["root"]["children"][1]
    ii["facts"][5] = "line(A,C) ⟂ line(B,D)"

    with pytest.raises(
        BindingError, match="perpendicular_requires_shared_endpoint"
    ):
        NotationRuntimeLowerer().lower(raw, problem_id="perpendicular-test")


def test_standalone_segment_declarations_are_audit_only():
    candidate = {
        "family_id": "QuadraticEqualLengthRayPathMinimumSolver",
        "match_status": "matched",
        "match_reason": "segment declarations are source geometry",
        "root": {
            "definitions": ["Γ: y = a*x^2+b*x-3"],
            "facts": [
                "a > 0",
                "A = (-1,0)",
                "C = (0,-3)",
                "D = C+(2,0)",
                "segment(B,C)",
                "M ∈ segment(B,C)",
                "segment(O,M)",
                "N ∈ ray(C,D)",
                "CN = CM",
                "segment(B,N)",
            ],
            "goals": [],
            "uncertainties": [],
            "children": [],
        },
    }

    lowered = NotationRuntimeLowerer().lower(candidate, problem_id="segment-audit")
    assert any(f.kind == "equal_length" for f in lowered.graph.root_scope.facts)


def test_repeated_parent_point_declaration_is_inherited_once():
    raw = candidate(CASES[4])
    raw["root"]["facts"] = [
        "D = (b+2, y_D)",
        "D ∈ Γ",
        *raw["root"].get("facts", []),
    ]

    bound = binding(CASES[4], payload=raw)
    d_points = [
        entity
        for entity in bound.bundle.canonical_solver_input["entities"]
        if entity["name"] == "D"
    ]
    assert len(d_points) == 1


def test_attainment_and_value_are_independent_runtime_conditions():
    for case in CASES[:2]:
        raw = binding(case).bundle.canonical_solver_input
        assert any(f["type"] == "minimum_attained" for f in raw["facts"])
        assert any(f["type"] == "minimum_value" for f in raw["facts"])


def test_ray_cannot_silently_become_line():
    case = CASES[2]
    raw = candidate(case)
    raw["root"]["children"][1]["facts"][1] = "N ∈ line(C,D)"
    with pytest.raises(BindingError, match="unsupported_locus"):
        binding(case, payload=raw)


def test_invisible_object_is_rejected():
    case = CASES[3]
    raw = candidate(case)
    raw["root"]["children"][0]["facts"].append("N ∈ Γ")
    # This declares a separate local N; a reference to N from another sibling
    # cannot acquire the third question's coordinate or motion constraint.
    b = binding(case, payload=raw)
    points = [
        e for e in b.bundle.canonical_solver_input["entities"] if e["name"] == "N"
    ]
    assert len(points) == 2
    assert {e["scope_id"] for e in points} == {"i", "iii"}


def test_family_unmatched_is_not_promoted():
    raw = candidate(CASES[0])
    raw.update(match_status="unmatched", family_id=None)
    with pytest.raises(BindingError, match="family_unmatched"):
        binding(CASES[0], payload=raw)


@pytest.mark.parametrize("case", [CASES[0], CASES[1]])
def test_minimum_value_does_not_replace_attainment_state(case):
    raw = candidate(case)

    def remove(scope):
        scope["facts"] = [f for f in scope.get("facts", []) if not ("= min(" in f)]
        for child in scope.get("children", []):
            remove(child)

    remove(raw["root"])
    with pytest.raises(BindingError, match="attainment_state_required"):
        binding(case, payload=raw)


def test_sibling_condition_cannot_supply_attainment():
    raw = candidate(CASES[0])
    children = raw["root"]["children"][1]["children"]
    children[0]["facts"].append(children[1]["facts"].pop())
    with pytest.raises(BindingError, match="attainment_state_required"):
        binding(CASES[0], payload=raw)


def test_extra_coordinate_constraint_is_not_silently_ignored():
    raw = candidate(CASES[3])
    raw["root"]["children"][1]["facts"].append("x(D) < 0")
    with pytest.raises(BindingError, match="unsupported_coordinate_condition"):
        binding(CASES[3], payload=raw)


def test_multiple_independent_axis_parameters_are_ambiguous():
    raw = candidate(CASES[3])
    raw["root"]["children"][2]["facts"][5] = "N = (n+t,0)"
    with pytest.raises(BindingError, match="motion_ambiguous"):
        binding(CASES[3], payload=raw)


def test_unknown_input_is_not_a_committed_result():
    from shuxueshuo_server.problem_understanding.compact_planner_input import (
        compact_problem,
    )

    with pytest.raises(BindingError, match="unverified_result"):
        compact_problem(binding(CASES[3]), execution={})


def test_other_root_requires_visible_proof_of_distinctness():
    b = binding(CASES[4])
    proof = [
        s
        for s in b.bundle.provenance.values()
        if s["rule"] == "distinct_quadratic_roots"
    ]
    assert proof and all("/root/facts/0" in p["premises"] for p in proof)
    raw = candidate(CASES[4])
    raw["root"]["facts"][0] = "b >= -2"
    with pytest.raises(BindingError, match="intersection_distinctness_unproved"):
        binding(CASES[4], payload=raw)


def test_sibling_ray_does_not_choose_a_path_capability():
    raw = candidate(CASES[3], authored=True)
    raw["root"]["children"][0]["facts"].extend(
        ["U = (0,0)", "V = (1,0)", "Q ∈ ray(U,V)"]
    )
    bound = binding(CASES[3], payload=raw)
    assert bound.bundle.family_id == raw["family_id"]
    assert any(
        entity.kind == "named_ray"
        for scope in bound.bundle.source_graph.root_scope.iter_scopes()
        for entity in scope.entities
    )
    assert bound.bundle.admission_evidence is None


def test_existing_family_source_preflight_remains_enforced():
    raw = candidate(CASES[3], authored=True)
    raw["root"]["children"][2]["facts"][-1] = "min_{n}(MN+AN) = 21/4"
    with pytest.raises(BindingError) as error:
        binding(CASES[3], payload=raw)
    assert error.value.code == "extraction.problem_ir_runtime_preflight_failed"
    assert "weighted_path_minimum" in error.value.message
