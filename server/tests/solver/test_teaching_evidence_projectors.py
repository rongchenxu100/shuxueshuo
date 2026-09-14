from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation import (
    evidence_projectors as evidence_projectors_module,
)
from shuxueshuo_server.solver.explanation.evidence_projectors import (
    SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT,
    TeachingEvidenceProjectionError,
    default_teaching_evidence_projector_registry,
)
from shuxueshuo_server.solver.explanation.models import iter_teaching_sources
from shuxueshuo_server.solver.lesson_authoring_support import CASE_ID
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    RightAngleConstructSelectExecutionEvidence,
    SymbolicClosureExecutionEvidence,
    functional_execution_evidence_from_payload,
)
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


@pytest.fixture(scope="module")
def snapshot():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture(CASE_ID)
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def test_path_minimum_projector_exposes_complete_public_proof(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_path_minimum_ii"
    )
    source_evidence = snapshot.evidence_for_step(source.source_step_id)
    assert len(source_evidence) == 1
    evidence = source_evidence[0]

    assert evidence["schema_version"] == "path-minimum-prompt-witness/v1"
    assert evidence["original_objective"] == "HF+FM+MG"
    assert evidence["reduced_objective"] == "AG+MG"
    assert len(source.calculations) == 5
    assert {item["calculation_id"] for item in source.calculations} == {
        "path_equivalence",
        "path_construction_1",
        "path_construction_2",
        "path_minimum",
        "path_attainment",
    }
    assert all(item["passed"] for item in source.checks)


def test_weighted_projector_only_attaches_public_point_identities() -> None:
    original = {
        "original_objective": "runtime-owned original",
        "reduced_objective": "runtime-owned reduction",
        "equivalence_proof": ["runtime-owned proof"],
        "role_resolutions": [
            {"role": "fixed_point", "chosen_ref": "A"},
            {"role": "curve_point", "chosen_ref": "D"},
            {"role": "moving_point", "chosen_ref": "M"},
        ],
        "constructions": [
            {
                "kind": "weighted_right_triangle",
                "auxiliary_point_formula": ["3*m/4-1/4", "sqrt(3)*(m+1)/4"],
                "path_equivalence": {
                    "weighted_segment": ["curve_point", "moving_point"],
                    "unit_segment": ["fixed_point", "moving_point"],
                    "auxiliary_segment": ["auxiliary_point", "moving_point"],
                    "scale": "2",
                },
                "triangle_geometry": {
                    "kind": "weighted_right_triangle",
                    "right_angle_vertex_role": "auxiliary_point",
                    "hypotenuse_role": "fixed_to_moving",
                    "scaled_leg_role": "auxiliary_to_moving",
                },
            }
        ],
    }

    projected = evidence_projectors_module._studentize_weighted_path_witness(
        original,
        planning_context=SimpleNamespace(scopes=()),
    )

    assert projected["original_objective"] == original["original_objective"]
    assert projected["reduced_objective"] == original["reduced_objective"]
    assert projected["equivalence_proof"] == original["equivalence_proof"]
    assert original["constructions"][0]["path_equivalence"][
        "auxiliary_segment"
    ] == ["auxiliary_point", "moving_point"]
    assert projected["constructions"][0]["path_equivalence"] == {
        "weighted_segment": ["D", "M"],
        "unit_segment": ["A", "M"],
        "auxiliary_segment": ["Q", "M"],
        "scale": "2",
    }
    assert projected["constructions"][0]["triangle_geometry"] == {
        "kind": "weighted_right_triangle",
        "right_angle_vertex_role": "Q",
        "hypotenuse_role": "AM",
        "scaled_leg_role": "QM",
    }
    assert projected["constructions"][0]["student_auxiliary_point"][
        "label"
    ] == "Q"


def test_coupled_projector_only_names_verified_projection_roles() -> None:
    geometry = {
        "kind": "right_isosceles_perpendicular_bisector",
        "roles": {
            "right_vertex": "P",
            "first_leg_vertex": "Q",
            "second_leg_vertex": "R",
            "first_leg_moving_point": "X",
            "hypotenuse_moving_point": "Y",
        },
        "verified_relations": [
            "right_isosceles_frame",
            "projection_rectangle",
            "perpendicular_bisector",
        ],
    }
    original = {
        "original_objective": "XY+ZY",
        "reduced_objective": "PY+ZY",
        "equivalence_proof": ["XY=PY"],
        "constructions": [
            {
                "kind": "existing_fixed_endpoint_replacement",
                "segment_equality": "XY=PY",
                "geometry_certificate": geometry,
            }
        ],
    }

    projected = evidence_projectors_module._studentize_coupled_path_witness(
        original,
        planning_context=SimpleNamespace(scopes=()),
    )

    assert projected["original_objective"] == "XY+ZY"
    assert projected["reduced_objective"] == "PY+ZY"
    assert projected["equivalence_proof"] == ["XY=PY"]
    assert "student_second_leg_projection" not in geometry
    certificate = projected["constructions"][0]["geometry_certificate"]
    assert certificate["roles"] == geometry["roles"]
    assert certificate["verified_relations"] == geometry["verified_relations"]
    assert certificate["student_second_leg_projection"] == {"label": "H"}
    assert certificate["student_first_leg_projection"] == {"label": "K"}


def test_right_angle_projection_preserves_runtime_geometry_and_only_names_feet() -> None:
    evidence = RightAngleConstructSelectExecutionEvidence(
        step_id="construct_R",
        candidates=(("5", "3 - u"), ("1", "u - 3")),
        selected_point=("5", "3 - u"),
        construction_checks=("两条直角边垂直且等长",),
        selection_condition="R 在第四象限，且 u>3",
        candidate_decisions=("候选 1 保留", "候选 2 排除"),
        construction_geometry={
            "kind": "axis_projection_candidate_construction",
            "axis": "x",
            "reference_projection": ["u", "0"],
            "reference_lengths": {
                "anchor_to_projection": "u - 3",
                "reference_to_projection": "2",
            },
            "candidate_branches": [
                {
                    "point": ["5", "3 - u"],
                    "projection": ["5", "0"],
                    "lengths": {
                        "anchor_to_projection": "2",
                        "candidate_to_projection": "u - 3",
                    },
                },
                {
                    "point": ["1", "u - 3"],
                    "projection": ["1", "0"],
                    "lengths": {
                        "anchor_to_projection": "2",
                        "candidate_to_projection": "u - 3",
                    },
                },
            ],
        },
        selection_geometry={
            "kind": "axis_projection_congruence",
            "axis": "x",
            "reference_projection": ["u", "0"],
            "selected_projection": ["5", "0"],
            "lengths": {
                "anchor_to_reference_projection": "u - 3",
                "reference_to_reference_projection": "2",
                "anchor_to_selected_projection": "2",
                "selected_to_selected_projection": "u - 3",
            },
        },
    )

    projected = (
        evidence_projectors_module.RightAngleConstructSelectTeachingEvidenceProjector()
        .project(
            evidence,
            planning_context=SimpleNamespace(scopes=()),
        )
        .payload
    )

    geometry = projected["selection_geometry"]
    assert geometry["lengths"] == evidence.to_payload()["selection_geometry"][
        "lengths"
    ]
    assert geometry["student_reference_projection"]["label"] == "U"
    assert geometry["student_selected_projection"]["label"] == "V"
    assert "student_reference_projection" not in evidence.to_payload()[
        "selection_geometry"
    ]
    construction = projected["construction_geometry"]
    assert construction["student_reference_projection"]["label"] == "U"
    assert [
        item["student_projection"]["label"]
        for item in construction["candidate_branches"]
    ] == ["V", "W"]
    assert "student_reference_projection" not in evidence.to_payload()[
        "construction_geometry"
    ]
    assert all(
        "student_projection" not in item
        for item in evidence.to_payload()["construction_geometry"][
            "candidate_branches"
        ]
    )
    assert functional_execution_evidence_from_payload(evidence.to_payload()) == evidence


def test_symbolic_closure_is_public_evidence_not_transaction_state(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "solve_parameter_c_ii"
    )
    source_evidence = snapshot.evidence_for_step(source.source_step_id)
    assert len(source_evidence) == 1
    evidence = source_evidence[0]
    text = json.dumps(evidence, ensure_ascii=False)

    assert evidence["schema_version"] == (
        SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT
    )
    assert evidence["target"] == "c"
    assert evidence["target_value"] == "5"
    assert evidence["branch_count"] == 1
    assert [item["calculation_id"] for item in source.calculations] == [
        "symbolic_equations",
        "symbolic_substitutions",
        "symbolic_solution",
    ]
    for forbidden in (
        "StateVersion",
        "checkpoint",
        "MathObjectId",
        "transaction",
        "provenance_signature",
    ):
        assert forbidden not in text


def test_symbolic_execution_evidence_round_trips_strictly() -> None:
    evidence = SymbolicClosureExecutionEvidence(
        step_id="solve_parameter",
        target="a",
        target_value="3/4",
        equations=("Eq(4*a, 3)",),
        equation_sources=("expression", "condition"),
        substitutions=(("a", "3/4"),),
        branch_count=1,
        residual_symbols=(),
        affected_returns=("parameter_value",),
        constraint_summary="题设范围筛选出唯一解",
    )
    hydrated = functional_execution_evidence_from_payload(evidence.to_payload())
    assert hydrated == evidence


def test_evidence_registry_uses_exact_type_and_unknown_evidence_fails_loud() -> None:
    registry = default_teaching_evidence_projector_registry()
    with pytest.raises(
        TeachingEvidenceProjectionError,
        match="evidence_projector_missing",
    ):
        registry.project(object(), planning_context=None)  # type: ignore[arg-type]
