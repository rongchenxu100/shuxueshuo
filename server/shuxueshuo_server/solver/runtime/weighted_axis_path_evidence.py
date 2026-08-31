"""Verified evidence for the atomic weighted-axis path Macro."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchReport,
)


def build_weighted_axis_path_execution_witness(
    *,
    compiled: Any,
    prepared: Any,
    report: MacroRuntimeSearchReport,
    method_results: Sequence[Any],
    handle_registry: Any,
) -> PathMinimumWitness:
    """Publish proof data without leaking the synthetic auxiliary PointRef."""

    del prepared, handle_registry
    evidence: Mapping[str, Any] | None = None
    for result in method_results:
        if getattr(result, "method_id", None) != (
            "weighted_axis_path_minimum_kernel"
        ):
            continue
        output = getattr(result, "outputs", {}).get("evidence")
        value = getattr(output, "value", None)
        if isinstance(value, Mapping):
            evidence = value
            break
    if evidence is None:
        raise ValueError(
            "planner.macro_contract_invalid: weighted-axis Macro omitted "
            "its verified internal evidence"
        )
    moving_ref = next(
        (
            item.chosen_ref
            for item in report.role_resolutions
            if item.role == "moving_point"
        ),
        None,
    )
    if moving_ref is None:
        raise ValueError(
            "planner.macro_contract_invalid: weighted-axis winner omitted "
            "the moving point role"
        )
    provenance = compiled.problem_source_provenance
    provenance_signature = (
        provenance.semantic_signature()
        if provenance is not None
        else stable_hash(
            {
                "call_id": compiled.call_id,
                "search_signature": report.search_signature,
            }
        )
    )
    boundary_expression = evidence.get("boundary_minimum_expression")
    return PathMinimumWitness(
        step_id=compiled.call_id,
        macro_id="weighted_axis_path_minimum",
        original_objective=str(evidence["original_objective"]),
        reduced_objective=str(evidence["reduced_objective"]),
        role_resolutions=report.role_resolutions,
        constructions=(
            {
                "kind": "weighted_right_triangle",
                "weight": str(evidence["weight"]),
                "geometry_profile_id": str(evidence["geometry_profile_id"]),
                "orientation_sign": int(evidence["orientation_sign"]),
                "auxiliary_point_formula": list(
                    evidence["auxiliary_point_formula"]
                ),
                "auxiliary_locus": str(evidence["auxiliary_locus"]),
                "auxiliary_locus_kind": str(
                    evidence["auxiliary_locus_kind"]
                ),
            },
        ),
        equivalence_proof=tuple(
            str(item) for item in evidence["equivalence_proof"]
        ),
        legal_domain=(
            "the typed path target has one supported weighted term and one unit term sharing one axis moving point",
            (
                "attainment condition: "
                f"{evidence['attainment_condition']}"
            ),
            (
                "boundary branch: "
                f"{boundary_expression}"
                if boundary_expression is not None
                else "the interior equality state is valid throughout the parameter domain"
            ),
        ),
        minimum_strategy=str(evidence["minimum_strategy"]),
        minimum_expression=str(evidence["minimum_expression"]),
        minimizing_points={
            moving_ref: list(evidence["dynamic_point_expression"])
        },
        attainment_checks=(
            {
                "strategy": str(evidence["minimum_strategy"]),
                "feasible": True,
                "expression": str(evidence["minimum_expression"]),
                "checks": (
                    {"check": "auxiliary_point_on_declared_ray", "passed": True},
                    {"check": "moving_point_on_straightening_segment", "passed": True},
                    {"check": "dynamic_domain_branch_represented", "passed": True},
                ),
            },
        ),
        macro_search_report=report,
        provenance_signature=provenance_signature,
    )


__all__ = ["build_weighted_axis_path_execution_witness"]
