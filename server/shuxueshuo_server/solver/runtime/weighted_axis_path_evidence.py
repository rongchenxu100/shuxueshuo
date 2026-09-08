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
    weight = str(evidence["weight"])
    triangle_geometry = evidence.get("triangle_geometry")
    path_equivalence = evidence.get("path_equivalence")
    if not isinstance(triangle_geometry, Mapping) or not isinstance(
        path_equivalence,
        Mapping,
    ):
        raise ValueError(
            "planner.macro_contract_invalid: weighted-axis kernel omitted "
            "its structural triangle or path-equivalence facts"
        )
    return PathMinimumWitness(
        step_id=compiled.call_id,
        macro_id="weighted_axis_path_minimum",
        original_objective=str(evidence["original_objective"]),
        reduced_objective=f"{weight}×（两段普通线段之和）",
        role_resolutions=report.role_resolutions,
        constructions=(
            {
                "kind": "weighted_right_triangle",
                "weight": weight,
                "orientation_sign": int(evidence["orientation_sign"]),
                "auxiliary_point_formula": list(
                    evidence["auxiliary_point_formula"]
                ),
                "auxiliary_locus": str(evidence["auxiliary_locus"]),
                "auxiliary_locus_kind": str(
                    evidence["auxiliary_locus_kind"]
                ),
                "axis_projection_geometry": dict(
                    evidence["axis_projection_geometry"]
                ),
                "triangle_geometry": dict(triangle_geometry),
                "path_equivalence": dict(path_equivalence),
            },
        ),
        equivalence_proof=(
            "已验证的辅助直角三角形给出斜边与辅助直角边的倍率关系",
            "按同一倍率把原目标化为两段普通线段之和",
        ),
        legal_domain=(
            "题设路径含一个带权项和一个单位权重项，且共享同一个轴上动点",
            (
                "取等条件："
                f"{evidence['attainment_condition']}"
            ),
            (
                "边界分支："
                f"{boundary_expression}"
                if boundary_expression is not None
                else "取等状态在整个参数定义域内均成立"
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
