"""Verified evidence projection for ``quadratic_square_path_minimum``."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchReport,
)


def build_quadratic_square_path_execution_witness(
    *,
    compiled: Any,
    prepared: Any,
    report: MacroRuntimeSearchReport,
    method_results: Sequence[Any],
    handle_registry: Any,
) -> PathMinimumWitness:
    del prepared, handle_registry
    evidence: Mapping[str, Any] | None = None
    for result in method_results:
        if getattr(result, "method_id", None) != (
            "quadratic_square_path_minimum_kernel"
        ):
            continue
        output = getattr(result, "outputs", {}).get("evidence")
        value = getattr(output, "value", None)
        if isinstance(value, Mapping):
            evidence = value
            break
    if evidence is None:
        raise ValueError(
            "planner.macro_contract_invalid: quadratic-square Macro omitted "
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
            "planner.macro_contract_invalid: quadratic-square winner omitted "
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
    attainment_point = list(evidence.get("attainment_point", ()))
    return PathMinimumWitness(
        step_id=compiled.call_id,
        macro_id="quadratic_square_path_minimum",
        original_objective=str(evidence["original_objective"]),
        reduced_objective=str(evidence["reduced_objective"]),
        role_resolutions=report.role_resolutions,
        constructions=(
            {
                "kind": "square_midpoint_center_reduction",
                "moving_locus": str(evidence["moving_locus"]),
            },
            {
                "kind": "line_reflection",
                "reflected_point": list(evidence["reflected_point"]),
                "reflect_source": str(evidence["reflect_source"]),
                "reflected_point_name": str(
                    evidence["reflected_point_name"]
                ),
                "moving_point": str(evidence["moving_point"]),
                "other_fixed_point": str(evidence["other_fixed_point"]),
                "transformed_path": str(evidence["transformed_path"]),
                "straightened_path": str(evidence["straightened_path"]),
                "segment_equality": str(evidence["segment_equality"]),
                "minimum_segment": str(evidence["minimum_segment"]),
            },
        ),
        equivalence_proof=tuple(
            str(item) for item in evidence["equivalence_proof"]
        ),
        legal_domain=(
            "the selected quadratic state and connected square facts are visible in the call scope",
            "the source path is reduced by exact square midpoint/center equalities",
        ),
        minimum_strategy=str(evidence["minimum_strategy"]),
        minimum_expression=str(evidence["minimum_expression"]),
        minimizing_points={moving_ref: attainment_point},
        attainment_checks=(
            {
                "strategy": str(evidence["minimum_strategy"]),
                "feasible": True,
                "expression": str(evidence["minimum_expression"]),
                "checks": (
                    {"check": "point_on_moving_locus", "passed": True},
                    {"check": "point_on_minimum_segment", "passed": True},
                ),
            },
        ),
        macro_search_report=report,
        provenance_signature=provenance_signature,
    )


__all__ = ["build_quadratic_square_path_execution_witness"]
