"""Project verified runtime evidence into student-safe teaching facts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Protocol, TypeVar

from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    CurveCandidateParameterExecutionEvidence,
    FunctionalExecutionEvidence,
    PathMinimumPromptWitnessProjector,
    PathMinimumWitness,
    RightAngleConstructSelectExecutionEvidence,
    SymbolicClosureExecutionEvidence,
    thaw_json,
)


SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT = (
    "symbolic-closure-teaching-evidence/v1"
)
RIGHT_ANGLE_CONSTRUCT_SELECT_TEACHING_EVIDENCE_CONTRACT = (
    "right-angle-construct-select-teaching-evidence/v1"
)
CURVE_CANDIDATE_PARAMETER_TEACHING_EVIDENCE_CONTRACT = (
    "curve-candidate-parameter-teaching-evidence/v1"
)


class TeachingEvidenceProjectionError(ValueError):
    """One verified evidence value has no complete public teaching projection."""


@dataclass(frozen=True)
class ProjectedTeachingEvidence:
    evidence_ref: str
    payload: Mapping[str, Any]
    calculations: tuple[Mapping[str, Any], ...] = ()
    checks: tuple[Mapping[str, Any], ...] = ()


EvidenceT = TypeVar("EvidenceT", bound=FunctionalExecutionEvidence)


class TeachingEvidenceProjector(Protocol[EvidenceT]):
    def project(
        self,
        evidence: EvidenceT,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence: ...


class PathMinimumTeachingEvidenceProjector:
    """Expose the verified equivalence, locus, reflection and attainment proof."""

    def project(
        self,
        evidence: PathMinimumWitness,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        if planning_context is None:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_planning_context_missing: "
                f"step={evidence.step_id}"
            )
        payload = PathMinimumPromptWitnessProjector().project(
            evidence,
            planning_context,
        ).to_payload()
        if evidence.macro_id == "weighted_axis_path_minimum":
            payload = _studentize_weighted_path_witness(
                payload,
                planning_context=planning_context,
            )
        elif evidence.macro_id == (
            "coupled_segment_endpoint_replacement_path_minimum"
        ):
            payload = _studentize_coupled_path_witness(
                payload,
                planning_context=planning_context,
            )
        calculations: list[dict[str, Any]] = [
            {
                "calculation_id": "path_equivalence",
                "kind": "equivalence_chain",
                "statements": list(payload["equivalence_proof"]),
                "result": (
                    f'{payload["original_objective"]}='
                    f'{payload["reduced_objective"]}'
                ),
            }
        ]
        for index, construction in enumerate(payload.get("constructions", ())):
            if not isinstance(construction, Mapping):
                continue
            kind = str(construction.get("kind") or f"construction_{index + 1}")
            calculations.append(
                {
                    "calculation_id": f"path_construction_{index + 1}",
                    "kind": kind,
                    "facts": dict(construction),
                }
            )
        calculations.extend(
            (
                {
                    "calculation_id": "path_minimum",
                    "kind": "minimum",
                    "strategy": payload["minimum_strategy"],
                    "expression": payload["minimum_expression"],
                },
                {
                    "calculation_id": "path_attainment",
                    "kind": "attainment",
                    "points": dict(payload["minimizing_points"]),
                },
            )
        )
        checks: list[dict[str, Any]] = []
        for attainment_index, attainment in enumerate(
            payload.get("attainment_checks", ())
        ):
            if not isinstance(attainment, Mapping):
                continue
            for check_index, check in enumerate(attainment.get("checks", ())):
                if not isinstance(check, Mapping):
                    continue
                checks.append(
                    {
                        "check_id": (
                            f"path_attainment_{attainment_index + 1}_"
                            f"{check_index + 1}"
                        ),
                        "kind": str(check.get("check") or "attainment"),
                        "passed": bool(check.get("passed")),
                        **(
                            {"parameter": str(check["parameter"])}
                            if check.get("parameter") is not None
                            else {}
                        ),
                    }
                )
        return ProjectedTeachingEvidence(
            evidence_ref=f"path-minimum:{evidence.witness_id}",
            payload=payload,
            calculations=tuple(calculations),
            checks=tuple(checks),
        )


def _studentize_coupled_path_witness(
    payload: Mapping[str, Any],
    *,
    planning_context: Any,
) -> dict[str, Any]:
    """Name the two feet in a verified endpoint-replacement certificate."""

    constructions = [
        dict(item)
        for item in payload.get("constructions", ())
        if isinstance(item, Mapping)
    ]
    matches = [
        index
        for index, item in enumerate(constructions)
        if item.get("kind") == "existing_fixed_endpoint_replacement"
        and isinstance(item.get("geometry_certificate"), Mapping)
    ]
    if not matches:
        return dict(payload)
    if len(matches) != 1:
        raise TeachingEvidenceProjectionError(
            "teaching_projection_coupled_geometry_ambiguous"
        )
    index = matches[0]
    construction = constructions[index]
    geometry = dict(construction["geometry_certificate"])
    if geometry.get("kind") != "right_isosceles_perpendicular_bisector":
        raise TeachingEvidenceProjectionError(
            "teaching_projection_coupled_geometry_invalid"
        )
    roles = geometry.get("roles")
    if not isinstance(roles, Mapping) or not all(
        _is_student_point_label(str(value)) for value in roles.values()
    ):
        raise TeachingEvidenceProjectionError(
            "teaching_projection_coupled_roles_invalid"
        )
    used = {str(value) for value in roles.values()}
    second_leg_foot = _fresh_student_point_label(
        planning_context,
        additional_labels=used,
        preferred_labels=("H",),
    )
    first_leg_foot = _fresh_student_point_label(
        planning_context,
        additional_labels={*used, second_leg_foot},
        preferred_labels=("K",),
    )
    geometry["student_second_leg_projection"] = {
        "label": second_leg_foot,
    }
    geometry["student_first_leg_projection"] = {
        "label": first_leg_foot,
    }
    construction["geometry_certificate"] = geometry
    constructions[index] = construction
    result = dict(payload)
    result["constructions"] = constructions
    return result


def _studentize_weighted_path_witness(
    payload: Mapping[str, Any],
    *,
    planning_context: Any,
) -> dict[str, Any]:
    """Attach student point identities to already-verified structured facts.

    The runtime witness deliberately keeps its synthetic ``auxiliary``
    PointRef private.  Teaching projection owns the public presentation
    identities because it can see every point name already used by the
    problem. It does not rebuild objectives, equivalence equations or proof
    prose; those remain runtime-owned structured facts and are rendered by the
    teaching/visual consumers.
    """

    all_constructions = [
        dict(item)
        for item in payload.get("constructions", ())
        if isinstance(item, Mapping)
    ]
    matching_indices = [
        index
        for index, item in enumerate(all_constructions)
        if item.get("kind") == "weighted_right_triangle"
    ]
    if len(matching_indices) != 1:
        raise TeachingEvidenceProjectionError(
            "teaching_projection_weighted_construction_invalid: "
            f"expected=1, observed={len(matching_indices)}"
        )
    roles = {
        str(item.get("role") or ""): str(item.get("chosen_ref") or "")
        for item in payload.get("role_resolutions", ())
        if isinstance(item, Mapping)
    }
    fixed = roles.get("fixed_point", "")
    curve = roles.get("curve_point", "")
    moving = roles.get("moving_point", "")
    if not all(_is_student_point_label(item) for item in (fixed, curve, moving)):
        raise TeachingEvidenceProjectionError(
            "teaching_projection_weighted_public_roles_invalid: "
            f"fixed={fixed!r}, curve={curve!r}, moving={moving!r}"
        )

    construction_index = matching_indices[0]
    construction = all_constructions[construction_index]
    formula = construction.get("auxiliary_point_formula")
    path_equivalence = construction.get("path_equivalence")
    if (
        not isinstance(formula, (list, tuple))
        or len(formula) != 2
        or not isinstance(path_equivalence, Mapping)
    ):
        raise TeachingEvidenceProjectionError(
            "teaching_projection_weighted_public_construction_incomplete"
        )
    auxiliary = _fresh_student_point_label(
        planning_context,
        additional_labels={fixed, curve, moving},
    )
    construction["student_auxiliary_point"] = {
        "label": auxiliary,
        "coordinates": [str(item) for item in formula],
    }
    public_role_labels = {
        "fixed_point": fixed,
        "curve_point": curve,
        "moving_point": moving,
        "auxiliary_point": auxiliary,
    }
    construction["path_equivalence"] = {
        **dict(path_equivalence),
        **{
            field: _project_weighted_segment_roles(
                path_equivalence.get(field),
                role_labels=public_role_labels,
                field=field,
            )
            for field in (
                "weighted_segment",
                "unit_segment",
                "auxiliary_segment",
            )
        },
    }
    triangle_geometry = construction.get("triangle_geometry")
    if isinstance(triangle_geometry, Mapping):
        public_triangle_geometry = dict(triangle_geometry)
        right_angle_role = str(
            public_triangle_geometry.get("right_angle_vertex_role") or ""
        )
        hypotenuse_role = str(
            public_triangle_geometry.get("hypotenuse_role") or ""
        )
        scaled_leg_role = str(
            public_triangle_geometry.get("scaled_leg_role") or ""
        )
        segment_labels = {
            "fixed_to_moving": f"{fixed}{moving}",
            "auxiliary_to_moving": f"{auxiliary}{moving}",
        }
        if (
            right_angle_role not in public_role_labels
            or hypotenuse_role not in segment_labels
            or scaled_leg_role not in segment_labels
        ):
            raise TeachingEvidenceProjectionError(
                "teaching_projection_weighted_triangle_roles_invalid"
            )
        public_triangle_geometry["right_angle_vertex_role"] = (
            public_role_labels[right_angle_role]
        )
        public_triangle_geometry["hypotenuse_role"] = segment_labels[
            hypotenuse_role
        ]
        public_triangle_geometry["scaled_leg_role"] = segment_labels[
            scaled_leg_role
        ]
        construction["triangle_geometry"] = public_triangle_geometry
    geometry = construction.get("axis_projection_geometry")
    if isinstance(geometry, Mapping):
        public_geometry = dict(geometry)
        projection_formula = public_geometry.get("projection_point")
        boundary_formula = public_geometry.get("boundary_point")
        if (
            not isinstance(projection_formula, (list, tuple))
            or len(projection_formula) != 2
            or not isinstance(boundary_formula, (list, tuple))
            or len(boundary_formula) != 2
        ):
            raise TeachingEvidenceProjectionError(
                "teaching_projection_weighted_axis_geometry_incomplete"
            )
        projection_label = _fresh_student_point_label(
            planning_context,
            additional_labels={fixed, curve, moving, auxiliary},
            preferred_labels=("H",),
        )
        boundary_preference = (
            ("O",)
            if all(str(item).strip() == "0" for item in boundary_formula)
            else ("B",)
        )
        boundary_label = _fresh_student_point_label(
            planning_context,
            additional_labels={
                fixed,
                curve,
                moving,
                auxiliary,
                projection_label,
            },
            preferred_labels=boundary_preference,
        )
        public_geometry["student_projection_point"] = {
            "label": projection_label,
            "coordinates": [str(item) for item in projection_formula],
        }
        public_geometry["student_boundary_point"] = {
            "label": boundary_label,
            "coordinates": [str(item) for item in boundary_formula],
        }
        construction["axis_projection_geometry"] = public_geometry
    all_constructions[construction_index] = construction

    result = dict(payload)
    result["constructions"] = all_constructions
    return result


def _project_weighted_segment_roles(
    value: Any,
    *,
    role_labels: Mapping[str, str],
    field: str,
) -> list[str]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(str(item) not in role_labels for item in value)
    ):
        raise TeachingEvidenceProjectionError(
            "teaching_projection_weighted_path_segment_invalid: "
            f"{field}"
        )
    return [role_labels[str(item)] for item in value]


def _fresh_student_point_label(
    planning_context: Any,
    *,
    additional_labels: set[str],
    preferred_labels: tuple[str, ...] = ("Q",),
) -> str:
    used = set(additional_labels)
    for scope in getattr(planning_context, "scopes", ()):
        for entity in getattr(scope, "entities", ()):
            to_payload = getattr(entity, "to_prompt_payload", None)
            raw = to_payload() if callable(to_payload) else getattr(entity, "payload", {})
            if not isinstance(raw, Mapping):
                continue
            if str(raw.get("kind") or "") != "point":
                continue
            name = str(raw.get("id") or "")
            if _is_student_point_label(name):
                used.add(name)
    # Callers choose conventional labels for the semantic role (for example,
    # Q for the weighted auxiliary point, H for a perpendicular foot, O for
    # an axis endpoint), then fall back deterministically without case data.
    candidates = tuple(dict.fromkeys(preferred_labels)) + tuple(
        chr(codepoint)
        for codepoint in range(ord("A"), ord("Z") + 1)
        if chr(codepoint) not in preferred_labels
    )
    for candidate in candidates:
        if candidate not in used:
            return candidate
    raise TeachingEvidenceProjectionError(
        "teaching_projection_student_auxiliary_label_exhausted"
    )


def _is_student_point_label(value: str) -> bool:
    return re.fullmatch(r"[A-Z](?:[0-9]+|[′']+)?", value) is not None


class SymbolicClosureTeachingEvidenceProjector:
    """Expose only the public algebra used to select the verified solution."""

    def project(
        self,
        evidence: SymbolicClosureExecutionEvidence,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        del planning_context
        payload = {
            "schema_version": SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT,
            "step_id": evidence.step_id,
            "target": evidence.target,
            "target_value": evidence.target_value,
            "equations": list(evidence.equations),
            "equation_sources": list(evidence.equation_sources),
            "substitutions": [
                {"symbol": symbol, "value": value}
                for symbol, value in evidence.substitutions
            ],
            "branch_count": evidence.branch_count,
            "residual_symbols": list(evidence.residual_symbols),
            "affected_returns": list(evidence.affected_returns),
            "constraint_summary": evidence.constraint_summary,
        }
        calculations: list[dict[str, Any]] = [
            {
                "calculation_id": "symbolic_equations",
                "kind": "equation_system",
                "equations": list(evidence.equations),
                "sources": list(evidence.equation_sources),
            }
        ]
        if evidence.substitutions:
            calculations.append(
                {
                    "calculation_id": "symbolic_substitutions",
                    "kind": "substitution",
                    "values": [
                        {"symbol": symbol, "value": value}
                        for symbol, value in evidence.substitutions
                    ],
                }
            )
        calculations.append(
            {
                "calculation_id": "symbolic_solution",
                "kind": "solution",
                "target": evidence.target,
                "value": evidence.target_value,
            }
        )
        checks = (
            {
                "check_id": "symbolic_unique_branch",
                "kind": "unique_solution_branch",
                "passed": evidence.branch_count == 1
                and not evidence.residual_symbols,
                "branch_count": evidence.branch_count,
                "residual_symbols": list(evidence.residual_symbols),
            },
            *(
                (
                    {
                        "check_id": "symbolic_constraint_filter",
                        "kind": "constraint_filter",
                        "passed": True,
                        "summary": evidence.constraint_summary,
                    },
                )
                if evidence.constraint_summary
                else ()
            ),
        )
        return ProjectedTeachingEvidence(
            evidence_ref=f"symbolic-closure:{evidence.evidence_id}",
            payload=payload,
            calculations=tuple(calculations),
            checks=tuple(checks),
        )


class RightAngleConstructSelectTeachingEvidenceProjector:
    """Expose candidate construction and the verified branch selection."""

    def project(
        self,
        evidence: RightAngleConstructSelectExecutionEvidence,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        candidates = [list(item) for item in evidence.candidates]
        construction_geometry = None
        if evidence.construction_geometry is not None:
            if planning_context is None:
                raise TeachingEvidenceProjectionError(
                    "teaching_projection_right_angle_context_missing: "
                    f"step={evidence.step_id}"
                )
            construction_geometry = (
                _studentize_right_angle_candidate_construction_geometry(
                    evidence.construction_geometry,
                    planning_context=planning_context,
                )
            )
        selection_geometry = None
        if evidence.selection_geometry is not None:
            if planning_context is None:
                raise TeachingEvidenceProjectionError(
                    "teaching_projection_right_angle_context_missing: "
                    f"step={evidence.step_id}"
                )
            selection_geometry = _studentize_right_angle_selection_geometry(
                evidence.selection_geometry,
                planning_context=planning_context,
            )
        payload = {
            "schema_version": (
                RIGHT_ANGLE_CONSTRUCT_SELECT_TEACHING_EVIDENCE_CONTRACT
            ),
            "step_id": evidence.step_id,
            "macro_id": evidence.macro_id,
            "candidates": candidates,
            "selected_point": list(evidence.selected_point),
            "construction_checks": list(evidence.construction_checks),
            "selection_condition": evidence.selection_condition,
            "candidate_decisions": list(evidence.candidate_decisions),
            **(
                {"construction_geometry": construction_geometry}
                if construction_geometry is not None
                else {}
            ),
            **(
                {"selection_geometry": selection_geometry}
                if selection_geometry is not None
                else {}
            ),
        }
        return ProjectedTeachingEvidence(
            evidence_ref=f"right-angle-construct-select:{evidence.evidence_id}",
            payload=payload,
            calculations=(
                {
                    "calculation_id": "right_angle_rotation_candidates",
                    "kind": "candidate_construction",
                    "candidates": candidates,
                    # ``checks`` is reserved for the separate runtime-check
                    # channel in the LLM-facing projection.  These are the
                    # student-readable geometric relations used to construct
                    # the candidates, not internal verification records.
                    "verified_relations": list(evidence.construction_checks),
                    **(
                        {"geometry": construction_geometry}
                        if construction_geometry is not None
                        else {}
                    ),
                },
                {
                    "calculation_id": "right_angle_candidate_selection",
                    "kind": "candidate_selection",
                    "condition": evidence.selection_condition,
                    "decisions": list(evidence.candidate_decisions),
                    "result": list(evidence.selected_point),
                    **(
                        {"geometry": selection_geometry}
                        if selection_geometry is not None
                        else {}
                    ),
                },
            ),
            checks=(
                {
                    "check_id": "right_angle_selection_unique",
                    "kind": "unique_candidate",
                    "passed": True,
                    "display": "题设条件筛选出唯一合法候选点",
                },
            ),
        )


def _studentize_right_angle_candidate_construction_geometry(
    geometry: Mapping[str, Any],
    *,
    planning_context: Any,
) -> dict[str, Any]:
    """Assign collision-free labels to all verified projection feet."""

    if geometry.get("kind") != "axis_projection_candidate_construction":
        raise TeachingEvidenceProjectionError(
            "teaching_projection_right_angle_construction_geometry_invalid"
        )
    reference_projection = geometry.get("reference_projection")
    branches = geometry.get("candidate_branches")
    if (
        not isinstance(reference_projection, (list, tuple))
        or len(reference_projection) != 2
        or not isinstance(branches, (list, tuple))
        or len(branches) < 2
    ):
        raise TeachingEvidenceProjectionError(
            "teaching_projection_right_angle_construction_projection_missing"
        )
    reference_label = _fresh_student_point_label(
        planning_context,
        additional_labels=set(),
        preferred_labels=("U",),
    )
    used_labels = {reference_label}
    public_branches: list[dict[str, Any]] = []
    for branch in branches:
        if not isinstance(branch, Mapping):
            raise TeachingEvidenceProjectionError(
                "teaching_projection_right_angle_construction_branch_invalid"
            )
        projection = branch.get("projection")
        if not isinstance(projection, (list, tuple)) or len(projection) != 2:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_right_angle_construction_projection_missing"
            )
        label = _fresh_student_point_label(
            planning_context,
            additional_labels=used_labels,
            preferred_labels=("V", "W", "H", "K"),
        )
        used_labels.add(label)
        public_branches.append(
            {
                **thaw_json(branch),
                "student_projection": {
                    "label": label,
                    "coordinates": [str(item) for item in projection],
                },
            }
        )
    return {
        **thaw_json(geometry),
        "student_reference_projection": {
            "label": reference_label,
            "coordinates": [str(item) for item in reference_projection],
        },
        "candidate_branches": public_branches,
    }


def _studentize_right_angle_selection_geometry(
    geometry: Mapping[str, Any],
    *,
    planning_context: Any,
) -> dict[str, Any]:
    """Assign collision-free labels to the two runtime-verified feet."""

    if geometry.get("kind") != "axis_projection_congruence":
        raise TeachingEvidenceProjectionError(
            "teaching_projection_right_angle_geometry_invalid"
        )
    reference_projection = geometry.get("reference_projection")
    selected_projection = geometry.get("selected_projection")
    if (
        not isinstance(reference_projection, (list, tuple))
        or len(reference_projection) != 2
        or not isinstance(selected_projection, (list, tuple))
        or len(selected_projection) != 2
    ):
        raise TeachingEvidenceProjectionError(
            "teaching_projection_right_angle_projection_missing"
        )
    reference_label = _fresh_student_point_label(
        planning_context,
        additional_labels=set(),
        preferred_labels=("U",),
    )
    selected_label = _fresh_student_point_label(
        planning_context,
        additional_labels={reference_label},
        preferred_labels=("V",),
    )
    public_geometry = thaw_json(geometry)
    return {
        **public_geometry,
        "student_reference_projection": {
            "label": reference_label,
            "coordinates": [str(item) for item in reference_projection],
        },
        "student_selected_projection": {
            "label": selected_label,
            "coordinates": [str(item) for item in selected_projection],
        },
    }


class CurveCandidateParameterTeachingEvidenceProjector:
    """Expose candidate substitution, branch filtering and curve closure."""

    def project(
        self,
        evidence: CurveCandidateParameterExecutionEvidence,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        del planning_context
        candidates = [list(item) for item in evidence.candidates]
        payload = {
            "schema_version": CURVE_CANDIDATE_PARAMETER_TEACHING_EVIDENCE_CONTRACT,
            "step_id": evidence.step_id,
            "macro_id": evidence.macro_id,
            "candidates": candidates,
            "candidate_equations": list(evidence.candidate_equations),
            "candidate_decisions": list(evidence.candidate_decisions),
            "selected_point": list(evidence.selected_point),
            "parameter_name": evidence.parameter_name,
            "parameter_equation": evidence.parameter_equation,
            "parameter_value": evidence.parameter_value,
            "solved_curve": evidence.solved_curve,
        }
        return ProjectedTeachingEvidence(
            evidence_ref=f"curve-candidate-parameter:{evidence.evidence_id}",
            payload=payload,
            calculations=(
                {
                    "calculation_id": "curve_candidate_filter",
                    "kind": "candidate_filter",
                    "candidates": candidates,
                    "equations": list(evidence.candidate_equations),
                    "decisions": list(evidence.candidate_decisions),
                },
                {
                    "calculation_id": "curve_parameter_solution",
                    "kind": "parameter_solution",
                    "equation": evidence.parameter_equation,
                    "parameter": evidence.parameter_name,
                    "value": evidence.parameter_value,
                    "point": list(evidence.selected_point),
                    "curve": evidence.solved_curve,
                },
            ),
            checks=(
                {
                    "check_id": "curve_candidate_unique",
                    "kind": "unique_candidate",
                    "passed": True,
                    "display": "曲线条件与参数约束筛选出唯一合法候选点",
                },
            ),
        )


class TeachingEvidenceProjectorRegistry:
    """Exact-type registry; unknown verified evidence fails loudly."""

    def __init__(self) -> None:
        self._projectors: dict[type[Any], TeachingEvidenceProjector[Any]] = {}

    def register(
        self,
        evidence_type: type[EvidenceT],
        projector: TeachingEvidenceProjector[EvidenceT],
    ) -> None:
        if evidence_type in self._projectors:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_evidence_projector_duplicate: "
                f"{evidence_type.__name__}"
            )
        self._projectors[evidence_type] = projector

    def project(
        self,
        evidence: FunctionalExecutionEvidence,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        projector = self._projectors.get(type(evidence))
        if projector is None:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_evidence_projector_missing: "
                f"evidence={type(evidence).__name__}"
            )
        return projector.project(
            evidence,
            planning_context=planning_context,
        )


def default_teaching_evidence_projector_registry(
) -> TeachingEvidenceProjectorRegistry:
    registry = TeachingEvidenceProjectorRegistry()
    from ..runtime.inequality_teaching_evidence import InequalityTeachingEvidence
    from .basic_inequality_teaching import InequalityTeachingProjector
    registry.register(InequalityTeachingEvidence, InequalityTeachingProjector())
    from ..runtime.rewrite_teaching_evidence import RewriteTeachingEvidence
    from .expression_rewrite import RewriteTeachingProjector
    registry.register(RewriteTeachingEvidence, RewriteTeachingProjector())
    from ..runtime.elimination_teaching_evidence import EliminationTeachingEvidence
    from .elimination import EliminationTeachingProjector
    registry.register(EliminationTeachingEvidence, EliminationTeachingProjector())
    registry.register(PathMinimumWitness, PathMinimumTeachingEvidenceProjector())
    registry.register(
        SymbolicClosureExecutionEvidence,
        SymbolicClosureTeachingEvidenceProjector(),
    )
    registry.register(
        RightAngleConstructSelectExecutionEvidence,
        RightAngleConstructSelectTeachingEvidenceProjector(),
    )
    registry.register(
        CurveCandidateParameterExecutionEvidence,
        CurveCandidateParameterTeachingEvidenceProjector(),
    )
    return registry


__all__ = [
    "CURVE_CANDIDATE_PARAMETER_TEACHING_EVIDENCE_CONTRACT",
    "CurveCandidateParameterTeachingEvidenceProjector",
    "PathMinimumTeachingEvidenceProjector",
    "ProjectedTeachingEvidence",
    "RIGHT_ANGLE_CONSTRUCT_SELECT_TEACHING_EVIDENCE_CONTRACT",
    "RightAngleConstructSelectTeachingEvidenceProjector",
    "SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT",
    "SymbolicClosureTeachingEvidenceProjector",
    "TeachingEvidenceProjectionError",
    "TeachingEvidenceProjector",
    "TeachingEvidenceProjectorRegistry",
    "default_teaching_evidence_projector_registry",
]
