"""Bind generic Method/Macro Teaching Specs to one verified Snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.contracts import TeachingUnitSpec
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.recipes._spec import MacroTeachingSpec
from shuxueshuo_server.solver.student_display import student_math_display

from .models import ExplanationSnapshot, TeachingSource, iter_teaching_sources
from .teaching_role_bindings import (
    TeachingRoleBindingError,
    bind_teaching_roles,
    format_teaching_template,
    student_quadratic_expression_display,
)
from .weighted_axis_teaching_profiles import (
    WeightedAxisTeachingProfile,
    select_weighted_axis_teaching_profile,
)


class TeachingSpecBindingError(ValueError):
    """A generic teaching spec cannot be bound to verified public facts."""


@dataclass(frozen=True)
class BoundTeachingUnit:
    source_step_id: str
    unit_key: str
    nav_title: str
    title: str
    goal: str
    derive: tuple[tuple[str, str], ...]
    box: tuple[str, ...]
    visuals: tuple[dict[str, Any], ...] = ()

    def to_payload(self, *, include_unit_key: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "nav_title": self.nav_title,
            "title": self.title,
            "goal": self.goal,
            "derive": [list(item) for item in self.derive],
            "box": list(self.box),
        }
        if include_unit_key:
            payload["unit_key"] = self.unit_key
        return payload


@dataclass(frozen=True)
class BoundTeachingSelection:
    """Internal selection authority for one verified teaching source."""

    kind: str
    units: tuple[BoundTeachingUnit, ...]
    variant_key: str | None = None
    evidence_match: Mapping[str, Any] | None = None


TeachingUnitFallback = Callable[
    [TeachingUnitSpec, TeachingSpecBindingError],
    BoundTeachingUnit,
]


INDEPENDENT_LESSON_STEP_TEMPLATE_KEY = (
    "requires_independent_lesson_step"
)


class TeachingSeparationBoundaryResolver:
    """Resolve code-owned teaching boundaries from Method/Macro VisualSpec.

    The result is deliberately material-local.  A visual capability existing
    is not itself a boundary: only an explicitly marked scene template makes
    its corresponding teaching material occupy one LessonStep.  This keeps
    compatible Method visuals composable while giving Method and Macro units
    exactly the same rule.
    """

    def __init__(
        self,
        *,
        methods: MethodSpecRegistry | None = None,
        recipes: RecipeSpecRegistry | None = None,
    ) -> None:
        self._methods = methods or MethodSpecRegistry.load_from_code()
        self._recipes = recipes or RecipeSpecRegistry.load_from_code()

    def requires_independent_lesson_step(
        self,
        source: TeachingSource,
        *,
        capability_kind: str,
        unit_key: str,
    ) -> bool:
        return self.requires_independent_lesson_step_for_unit(
            capability_id=source.capability_id,
            capability_kind=capability_kind,
            unit_key=unit_key,
        )

    def requires_independent_lesson_step_for_unit(
        self,
        *,
        capability_id: str,
        capability_kind: str,
        unit_key: str,
    ) -> bool:
        """Resolve one material without requiring a serialized source object."""

        method = self._methods.specs.get(capability_id)
        recipe = self._recipes.get(capability_id)
        if (method is None) == (recipe is None):
            raise TeachingSpecBindingError(
                "teaching_separation_capability_classification_invalid: "
                f"{capability_id}"
            )
        if method is not None:
            if capability_kind != "function":
                raise TeachingSpecBindingError(
                    "teaching_separation_capability_kind_mismatch: "
                    f"{capability_id}: {capability_kind}"
                )
            for declared in method.teaching_units or ((method.teaching_unit,) if method.teaching_unit else ()):
                if declared.unit_key == unit_key and declared.requires_independent_lesson_step:
                    return True
            if method.teaching_units and unit_key in {u.unit_key for u in method.teaching_units}:
                return False
            expected_key = (
                method.teaching_unit.unit_key
                if method.teaching_unit is not None
                else f"{capability_id}/default"
            )
            if unit_key != expected_key and not unit_key.endswith("/generic"):
                raise TeachingSpecBindingError(
                    "teaching_separation_unit_unknown: "
                    f"{capability_id}: {unit_key}"
                )
            templates = (
                method.visual.scene_templates
                if method.visual is not None
                else ()
            )
            return _templates_require_independent_lesson_step(
                templates,
                capability_id=capability_id,
                unit_key=unit_key,
            )

        assert recipe is not None
        if capability_kind != "macro":
            raise TeachingSpecBindingError(
                "teaching_separation_capability_kind_mismatch: "
                f"{capability_id}: {capability_kind}"
            )
        known_unit_keys = _macro_teaching_unit_keys(recipe.teaching)
        if unit_key not in known_unit_keys:
            if unit_key.endswith("/generic"):
                return False
            raise TeachingSpecBindingError(
                "teaching_separation_unit_unknown: "
                f"{capability_id}: {unit_key}"
            )
        unit_tail = unit_key.rsplit("/", 1)[-1]
        templates = (
            recipe.visual.teaching_substep_templates.get(unit_tail, ())
            if recipe.visual is not None
            else ()
        )
        return _templates_require_independent_lesson_step(
            templates,
            capability_id=capability_id,
            unit_key=unit_key,
        )


def _macro_teaching_unit_keys(
    teaching: MacroTeachingSpec | None,
) -> frozenset[str]:
    if teaching is None:
        return frozenset()
    if teaching.teaching_units:
        return frozenset(unit.unit_key for unit in teaching.teaching_units)
    return frozenset(
        unit.unit_key
        for variant in teaching.teaching_variants
        for unit in variant.teaching_units
    )


def _templates_require_independent_lesson_step(
    templates: Sequence[Mapping[str, Any]],
    *,
    capability_id: str,
    unit_key: str,
) -> bool:
    values: list[bool] = []
    for index, template in enumerate(templates):
        raw = template.get(INDEPENDENT_LESSON_STEP_TEMPLATE_KEY, False)
        if not isinstance(raw, bool):
            raise TeachingSpecBindingError(
                "teaching_separation_template_flag_invalid: "
                f"{capability_id}/{unit_key}[{index}]"
            )
        values.append(raw)
    return any(values)


class TeachingSpecBinder:
    """Resolve one capability spec and bind it using verified Snapshot data."""

    def __init__(
        self,
        *,
        methods: MethodSpecRegistry | None = None,
        recipes: RecipeSpecRegistry | None = None,
    ) -> None:
        self._methods = methods or MethodSpecRegistry.load_from_code()
        self._recipes = recipes or RecipeSpecRegistry.load_from_code()

    def generic_spec_payload(self, source: TeachingSource) -> dict[str, Any]:
        method = self._methods.specs.get(source.capability_id)
        recipe = self._recipes.get(source.capability_id)
        if (method is None) == (recipe is None):
            raise TeachingSpecBindingError(
                "teaching_spec_capability_classification_invalid: "
                f"{source.capability_id}"
            )
        if method is not None:
            if method.teaching_units:
                return {
                    "kind": "function",
                    "declared": True,
                    "teaching_units": [unit.to_payload() for unit in method.teaching_units],
                }
            unit = method.teaching_unit or _default_teaching_unit(source)
            return {
                "kind": "function",
                "declared": method.teaching_unit is not None,
                "teaching_unit": unit.to_payload(),
            }
        assert recipe is not None
        if recipe.teaching is None:
            raise TeachingSpecBindingError(
                f"teaching_spec_macro_missing: {recipe.recipe_id}"
            )
        return {
            "kind": "macro",
            "declared": True,
            "macro_teaching": recipe.teaching.to_payload(),
        }

    def bind_source(
        self,
        source: TeachingSource,
        *,
        snapshot: ExplanationSnapshot,
    ) -> tuple[BoundTeachingUnit, ...]:
        return self.bind_source_selection(
            source,
            snapshot=snapshot,
        ).units

    def bind_source_selection(
        self,
        source: TeachingSource,
        *,
        snapshot: ExplanationSnapshot,
        on_unit_error: TeachingUnitFallback | None = None,
    ) -> BoundTeachingSelection:
        """Bind the selected public teaching path and retain internal authority.

        ``on_unit_error`` is deliberately unit-local.  It lets the B2 teaching
        projector replace one incomplete template with a complete verified
        generic material without discarding successfully bound sibling units.
        Variant selection and role binding remain fail-loud because no unit
        boundary is authoritative before those operations succeed.
        """

        method = self._methods.specs.get(source.capability_id)
        recipe = self._recipes.get(source.capability_id)
        if (method is None) == (recipe is None):
            raise TeachingSpecBindingError(
                "teaching_spec_capability_classification_invalid: "
                f"{source.capability_id}"
            )
        if method is not None:
            bound = []
            for unit in method.teaching_units or (method.teaching_unit or _default_teaching_unit(source),):
                try:
                    roles = bind_teaching_roles(source, unit, snapshot=snapshot)
                except TeachingRoleBindingError as exc:
                    raise TeachingSpecBindingError(str(exc)) from exc
                bound.append(_bind_unit_or_fallback(source, unit, roles, on_unit_error=on_unit_error))
            return BoundTeachingSelection(kind="function", units=tuple(bound))
        assert recipe is not None and recipe.teaching is not None
        units, variant_key, evidence_match = _select_macro_units(
            recipe.teaching,
            source=source,
            snapshot=snapshot,
        )
        roles = _macro_roles(source, snapshot=snapshot)
        return BoundTeachingSelection(
            kind="macro",
            units=tuple(
                _bind_unit_or_fallback(
                    source,
                    unit,
                    roles,
                    on_unit_error=on_unit_error,
                )
                for unit in units
            ),
            variant_key=variant_key,
            evidence_match=evidence_match,
        )


def _default_teaching_unit(source: TeachingSource) -> TeachingUnitSpec:
    outputs = "，".join(
        str(item.get("display") or name)
        for name, item in source.outputs.items()
    )
    return TeachingUnitSpec(
        unit_key=f"{source.capability_id}/default",
        title_template=source.intent or source.capability_id,
        nav_title_template=source.intent or source.capability_id,
        goal_template=source.intent or "完成这一计算。",
        derive_templates=(("∴", outputs or "得到本步结果"),),
        box_templates=((outputs,) if outputs else ()),
        role_binder_id="generic_trace",
    )


def _select_macro_units(
    spec: MacroTeachingSpec,
    *,
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> tuple[
    tuple[TeachingUnitSpec, ...],
    str | None,
    Mapping[str, Any] | None,
]:
    if spec.teaching_units:
        return spec.teaching_units, None, None
    evidence_values = snapshot.evidence_for_step(source.source_step_id)
    matches = [
        variant
        for variant in spec.teaching_variants
        if any(
            _mapping_contains(evidence, variant.evidence_match)
            for evidence in evidence_values
        )
    ]
    if len(matches) != 1:
        raise TeachingSpecBindingError(
            "teaching_spec_macro_variant_match_invalid: "
            f"step={source.source_step_id}, matches={len(matches)}"
        )
    selected = matches[0]
    return (
        selected.teaching_units,
        selected.variant_key,
        dict(selected.evidence_match),
    )


def _mapping_contains(value: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return all(value.get(key) == item for key, item in expected.items())


def _macro_roles(
    source: TeachingSource,
    *,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    witness = _single_macro_witness(source, snapshot=snapshot)
    if source.capability_id == "quadratic_square_path_minimum":
        return _quadratic_square_macro_roles(source, witness=witness)
    if source.capability_id == "equal_length_ray_path_reduction":
        return _equal_length_ray_macro_roles(source, witness=witness)
    if source.capability_id == (
        "coupled_segment_endpoint_replacement_path_minimum"
    ):
        return _coupled_segment_macro_roles(source, witness=witness)
    if source.capability_id == "weighted_axis_path_minimum":
        return _weighted_axis_macro_roles(
            source,
            witness=witness,
        )
    if source.capability_id == "right_angle_equal_length_construct_and_select":
        return _right_angle_construct_select_macro_roles(
            source,
            witness=witness,
            snapshot=snapshot,
        )
    if source.capability_id == "curve_candidate_parameter_solve":
        return _curve_candidate_parameter_macro_roles(
            source,
            witness=witness,
            snapshot=snapshot,
        )
    raise TeachingSpecBindingError(
        "teaching_spec_macro_role_binder_missing: "
        f"{source.capability_id}"
    )


def _single_macro_witness(
    source: TeachingSource,
    *,
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    witnesses = [
        payload
        for payload in snapshot.evidence_for_step(source.source_step_id)
        if payload.get("macro_id") == source.capability_id
    ]
    if len(witnesses) != 1:
        raise TeachingSpecBindingError(
            "teaching_spec_macro_evidence_invalid: "
            f"step={source.source_step_id}, matches={len(witnesses)}"
        )
    return witnesses[0]


def _quadratic_square_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    proof = tuple(str(item) for item in witness.get("equivalence_proof", ()))
    if not proof:
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_equivalence_proof_missing: {source.source_step_id}"
        )
    constructions = tuple(
        item
        for item in witness.get("constructions", ())
        if isinstance(item, Mapping)
    )
    reduction = next(
        (item for item in constructions if item.get("moving_locus")),
        {},
    )
    reflection = next(
        (item for item in constructions if item.get("kind") == "line_reflection"),
        {},
    )
    minimizing = witness.get("minimizing_points")
    if not isinstance(minimizing, Mapping) or len(minimizing) != 1:
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_attainment_invalid: {source.source_step_id}"
        )
    moving_point, point_value = next(iter(minimizing.items()))
    if not isinstance(point_value, Sequence) or isinstance(point_value, str | bytes):
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_attainment_invalid: {source.source_step_id}"
        )
    reflected_name = _student_point_name(
        str(reflection.get("reflected_point_name") or "对称点")
    )
    reflected_value = reflection.get("reflected_point")
    reflected_point = reflected_name
    if isinstance(reflected_value, Sequence) and not isinstance(
        reflected_value, str | bytes
    ):
        reflected_point += _point_coordinates(reflected_value)
    segment_equality = _student_prime_text(
        str(reflection.get("segment_equality") or "")
    )
    transformed = _student_prime_text(
        str(reflection.get("transformed_path") or witness.get("reduced_objective") or "")
    )
    straightened = _student_prime_text(
        str(reflection.get("straightened_path") or "")
    )
    minimum_segment = _student_prime_text(
        str(reflection.get("minimum_segment") or "")
    )
    straightened_path = f"{transformed}＝{straightened}"
    if minimum_segment:
        straightened_path += f"≥{minimum_segment}"
    base_equalities = proof[:-2] if len(proof) >= 3 else proof[:-1]
    path_reduction_equality = proof[-2] if len(proof) >= 2 else proof[-1]
    return {
        "square_equalities": "，".join(base_equalities or proof),
        "path_reduction_equality": path_reduction_equality,
        "original_objective": str(witness.get("original_objective") or ""),
        "reduced_objective": str(witness.get("reduced_objective") or ""),
        "moving_point": str(moving_point),
        "moving_locus": student_math_display(
            str(reduction.get("moving_locus") or "")
        ),
        "reflected_point": reflected_point,
        "segment_equality": segment_equality,
        "straightened_path": straightened_path,
        "minimum_expression": student_math_display(
            str(witness.get("minimum_expression") or "")
        ),
        "attainment_point": (
            f"{moving_point}{_point_coordinates(point_value)}"
        ),
    }


def _right_angle_construct_select_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    candidates = _macro_point_list(
        source,
        witness.get("candidates"),
        role="candidates",
    )
    selected = _macro_point(
        source,
        witness.get("selected_point"),
        role="selected_point",
    )
    checks = tuple(str(item) for item in witness.get("construction_checks", ()))
    decisions = tuple(str(item) for item in witness.get("candidate_decisions", ()))
    if not checks or len(decisions) != len(candidates):
        raise TeachingSpecBindingError(
            "teaching_spec_macro_construct_select_evidence_incomplete: "
            f"{source.source_step_id}"
        )
    target_label = str(
        source.output_targets.get("selected_target_point") or ""
    ).rsplit(":", 1)[-1]
    selected_display = (
        _labeled_macro_point(target_label, selected)
        if re.fullmatch(r"[A-Z](?:[0-9]+|[′']+)?", target_label)
        else _point_coordinates(selected)
    )
    candidate_labels = tuple(
        _indexed_candidate_label(target_label, index)
        for index in range(1, len(candidates) + 1)
    )
    labeled_candidates = tuple(
        _labeled_macro_point(label, point)
        for label, point in zip(candidate_labels, candidates, strict=True)
    )
    anchor, reference = _right_angle_relation_points(
        source,
        target_label=target_label,
    )
    roles: dict[str, Any] = {
        "construction_condition": (
            f"∠{reference}{anchor}{target_label}＝90°，"
            f"{anchor}{reference}＝{anchor}{target_label}"
        ),
        "candidate_points": "，".join(labeled_candidates),
        "selection_condition": str(witness.get("selection_condition") or ""),
        "candidate_decisions": "；".join(decisions),
        "selected_point": selected_display,
    }
    derive_by_unit: dict[str, tuple[str, ...]] = {}
    construction_geometry = witness.get("construction_geometry")
    if isinstance(construction_geometry, Mapping):
        geometric_derive = _right_angle_candidates_axis_congruence_derive(
            source,
            geometry=construction_geometry,
            target_label=target_label,
            candidate_labels=candidate_labels,
        )
        if geometric_derive:
            derive_by_unit[
                "right_angle_equal_length_construct_and_select/construct_candidates"
            ] = geometric_derive
    selection_derive = _right_angle_candidate_selection_derive(
        candidates=candidates,
        candidate_labels=candidate_labels,
        selected=selected,
        selected_display=selected_display,
        selection_condition=roles["selection_condition"],
    )
    if selection_derive:
        derive_by_unit[
            "right_angle_equal_length_construct_and_select/select_candidate"
        ] = selection_derive
    if derive_by_unit:
        roles["derive_items_by_unit"] = derive_by_unit
    return roles


def _right_angle_candidates_axis_congruence_derive(
    source: TeachingSource,
    *,
    geometry: Mapping[str, Any],
    target_label: str,
    candidate_labels: tuple[str, ...],
) -> tuple[str, ...]:
    """Render one runtime-certified projection proof for all candidates."""

    if geometry.get("kind") != "axis_projection_candidate_construction":
        return ()
    try:
        anchor, reference = _right_angle_relation_points(
            source,
            target_label=target_label,
        )
    except TeachingSpecBindingError:
        return ()
    anchor_pair = geometry.get("anchor")
    reference_pair = geometry.get("reference")
    reference_projection = geometry.get("student_reference_projection")
    reference_lengths = geometry.get("reference_lengths")
    branches = geometry.get("candidate_branches")
    if not all(
        isinstance(item, Mapping)
        for item in (reference_projection, reference_lengths)
    ) or not isinstance(branches, Sequence) or isinstance(branches, str | bytes):
        return ()
    assert isinstance(reference_projection, Mapping)
    assert isinstance(reference_lengths, Mapping)
    if len(branches) != len(candidate_labels):
        return ()
    if not all(
        isinstance(item, Sequence)
        and not isinstance(item, str | bytes)
        and len(item) == 2
        for item in (anchor_pair, reference_pair)
    ):
        return ()
    reference_foot = str(reference_projection.get("label") or "")
    reference_foot_pair = reference_projection.get("coordinates")
    if (
        not reference_foot
        or not isinstance(reference_foot_pair, Sequence)
        or isinstance(reference_foot_pair, str | bytes)
        or len(reference_foot_pair) != 2
    ):
        return ()
    axis = str(geometry.get("axis") or "")
    projection_line = geometry.get("projection_line")
    if axis not in {"x", "y"} or not isinstance(projection_line, Mapping):
        return ()
    line_text = (
        f"{axis} 轴"
        if projection_line.get("kind") == "coordinate_axis"
        else f"过{anchor}且平行于 {axis} 轴的直线"
    )

    branch_rows: list[tuple[str, str, Sequence[Any], Sequence[Any]]] = []
    for label, raw_branch in zip(candidate_labels, branches, strict=True):
        if not isinstance(raw_branch, Mapping):
            return ()
        point = raw_branch.get("point")
        projection = raw_branch.get("student_projection")
        lengths = raw_branch.get("lengths")
        if not isinstance(projection, Mapping) or not isinstance(lengths, Mapping):
            return ()
        foot = str(projection.get("label") or "")
        foot_pair = projection.get("coordinates")
        if not foot or not all(
            isinstance(item, Sequence)
            and not isinstance(item, str | bytes)
            and len(item) == 2
            for item in (point, foot_pair)
        ):
            return ()
        if (
            _student_math_text(lengths.get("anchor_to_projection"))
            != _student_math_text(reference_lengths.get("reference_to_projection"))
            or _student_math_text(lengths.get("candidate_to_projection"))
            != _student_math_text(reference_lengths.get("anchor_to_projection"))
        ):
            return ()
        branch_rows.append((label, foot, point, foot_pair))

    construction_parts = [
        f"{reference}{reference_foot}⊥{line_text}于{reference_foot}",
        *(
            f"{label}{foot}⊥{line_text}于{foot}"
            for label, foot, _, _ in branch_rows
        ),
    ]
    anchor_display = _labeled_macro_point(anchor, anchor_pair)
    reference_display = _labeled_macro_point(reference, reference_pair)
    reference_foot_display = _labeled_macro_point(
        reference_foot,
        reference_foot_pair,
    )
    anchor_reference_length = _student_math_text(
        reference_lengths.get("anchor_to_projection")
    )
    reference_projection_length = _student_math_text(
        reference_lengths.get("reference_to_projection")
    )
    angle_equalities = "＝".join(
        f"∠{reference}{anchor}{label}" for label, _, _, _ in branch_rows
    )
    segment_equalities = "＝".join(
        (
            f"{anchor}{reference}",
            *(f"{anchor}{label}" for label, _, _, _ in branch_rows),
        )
    )
    congruent_triangles = "≌".join(
        (
            f"Rt△{anchor}{reference_foot}{reference}",
            *(
                f"Rt△{label}{foot}{anchor}"
                for label, foot, _, _ in branch_rows
            ),
        )
    )
    horizontal_equalities = "＝".join(
        (
            *(f"{anchor}{foot}" for _, foot, _, _ in branch_rows),
            f"{reference}{reference_foot}",
            reference_projection_length,
        )
    )
    vertical_equalities = "＝".join(
        (
            *(f"{label}{foot}" for label, foot, _, _ in branch_rows),
            f"{anchor}{reference_foot}",
            anchor_reference_length,
        )
    )
    branch_points = "，".join(
        (
            *(
                _labeled_macro_point(foot, foot_pair)
                for _, foot, _, foot_pair in branch_rows
            ),
            *(
                _labeled_macro_point(label, point)
                for label, _, point, _ in branch_rows
            ),
        )
    )
    return (
        "设两个候选点分别为" + "、".join(candidate_labels),
        "作" + "，".join(construction_parts),
        f"∵{anchor_display}，{reference_display}",
        f"∴{reference_foot_display}，"
        f"{anchor}{reference_foot}＝{anchor_reference_length}，"
        f"{reference}{reference_foot}＝{reference_projection_length}",
        f"∵{angle_equalities}＝90°，{segment_equalities}",
        f"∴{congruent_triangles}",
        f"∴{horizontal_equalities}，{vertical_equalities}",
        f"∴{branch_points}",
    )


def _right_angle_candidate_selection_derive(
    *,
    candidates: tuple[tuple[str, str], ...],
    candidate_labels: tuple[str, ...],
    selected: tuple[str, str],
    selected_display: str,
    selection_condition: str,
) -> tuple[str, ...]:
    if len(candidates) != len(candidate_labels) or not selection_condition:
        return ()
    decisions = []
    for label, point in zip(candidate_labels, candidates, strict=True):
        decision = (
            "满足上述条件"
            if _macro_same_point(point, selected)
            else "不满足上述条件"
        )
        decisions.append(f"{_labeled_macro_point(label, point)}{decision}")
    condition = (
        _student_relation_text(selection_condition)
        .replace(">", "＞")
        .replace("<", "＜")
    )
    return (
        f"∵{condition}",
        "计算逐一判断，" + "；".join(decisions),
        f"∴唯一符合题意的点为{selected_display}",
    )


def _right_angle_relation_points(
    source: TeachingSource,
    *,
    target_label: str,
) -> tuple[str, str]:
    relation_items = source.inputs.get("right_angle_equal_length", ())
    if len(relation_items) != 1:
        raise TeachingSpecBindingError(
            "teaching_spec_right_angle_relation_missing: "
            f"{source.source_step_id}"
        )
    relation = relation_items[0].get("value")
    if not isinstance(relation, Mapping):
        raise TeachingSpecBindingError(
            "teaching_spec_right_angle_relation_invalid: "
            f"{source.source_step_id}"
        )
    angle = tuple(str(item) for item in relation.get("angle") or ())
    if len(angle) != 3 or target_label not in {angle[0], angle[2]}:
        raise TeachingSpecBindingError(
            "teaching_spec_right_angle_relation_roles_invalid: "
            f"{source.source_step_id}"
        )
    anchor = angle[1]
    reference = angle[2] if target_label == angle[0] else angle[0]
    return anchor, reference


def _curve_candidate_parameter_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    candidates = _macro_point_list(
        source,
        witness.get("candidates"),
        role="candidates",
    )
    selected = _macro_point(
        source,
        witness.get("selected_point"),
        role="selected_point",
    )
    equations = tuple(str(item) for item in witness.get("candidate_equations", ()))
    decisions = tuple(str(item) for item in witness.get("candidate_decisions", ()))
    if len(equations) != len(candidates) or len(decisions) != len(candidates):
        raise TeachingSpecBindingError(
            "teaching_spec_macro_curve_candidate_evidence_incomplete: "
            f"{source.source_step_id}"
        )
    parameter_name = str(witness.get("parameter_name") or "参数")
    parameter_value = str(witness.get("parameter_value") or "")
    parameter_equation = str(witness.get("parameter_equation") or "")
    matching = [
        index
        for index, equation in enumerate(equations)
        if _macro_equations_equivalent(equation, parameter_equation)
    ]
    if len(matching) != 1:
        raise TeachingSpecBindingError(
            "teaching_spec_macro_curve_parameter_equation_ambiguous: "
            f"{source.source_step_id}"
        )
    selected_symbolic = candidates[matching[0]]
    parameter_symbol = sp.Symbol(parameter_name)
    parameter_expr = _macro_sympify(parameter_value)
    substituted = tuple(
        sp.simplify(_macro_sympify(item).subs(parameter_symbol, parameter_expr))
        for item in selected_symbolic
    )
    selected_expr = tuple(_macro_sympify(item) for item in selected)
    if any(
        sp.simplify(actual - expected) != 0
        for actual, expected in zip(substituted, selected_expr, strict=True)
    ):
        raise TeachingSpecBindingError(
            "teaching_spec_macro_curve_selected_point_mismatch: "
            f"{source.source_step_id}"
        )

    target_item = _single_macro_input(source, "target_point")
    target_label = str(target_item.get("display") or "").strip()
    if not re.fullmatch(r"[A-Z](?:[0-9]+|[′']+)?", target_label):
        raise TeachingSpecBindingError(
            "teaching_spec_macro_curve_target_label_invalid: "
            f"{source.source_step_id}"
        )
    parabola_item = _single_macro_input(source, "parabola")
    parabola = _macro_sympify(parabola_item.get("value"))
    x_value, y_value = (_macro_sympify(item) for item in selected_symbolic)
    curve_substitution = sp.expand(parabola.subs(sp.Symbol("x"), x_value))
    residual = sp.expand(curve_substitution - y_value)
    constraint = _macro_symbol_constraint_text(
        source,
        parameter_name=parameter_name,
    )
    candidate_labels = tuple(
        _indexed_candidate_label(target_label, index)
        for index in range(1, len(candidates) + 1)
    )
    labeled_candidates = tuple(
        _labeled_macro_point(label, point)
        for label, point in zip(candidate_labels, candidates, strict=True)
    )
    selected_index = matching[0]
    selected_candidate_label = candidate_labels[selected_index]
    selected_symbolic_display = labeled_candidates[selected_index]
    symbolic_point = _labeled_macro_point(target_label, selected_symbolic)
    selected_point = _labeled_macro_point(target_label, selected_expr)
    parameter_result = (
        f"{parameter_name}＝{_student_parameter_value_text(parameter_expr)}"
    )
    curve_equation = (
        "y＝" + student_quadratic_expression_display(parabola)
    )
    filter_derive = [
        f"∵{target_label} 在抛物线 {curve_equation} 上",
    ]
    for index, (candidate_display, equation) in enumerate(
        zip(labeled_candidates, equations, strict=True)
    ):
        filter_derive.append(
            f"∵将 {candidate_display} 代入，得"
            f"{_student_math_text(equation)}"
        )
        outcome = "保留" if index == selected_index else "排除"
        filter_derive.append(
            f"∴结合{constraint}，{outcome}{candidate_labels[index]}"
        )
    filter_derive.extend(
        (
            f"∴{target_label}＝{selected_candidate_label}，"
            f"即{symbolic_point}",
            f"∵{_student_math_text(parameter_equation)}，{constraint}",
            f"∴{parameter_result}",
        )
    )
    return {
        "target_label": target_label,
        "candidate_points": "，".join(
            labeled_candidates
        ),
        "candidate_substitutions": "；".join(
            _student_math_text(item) for item in equations
        ),
        "candidate_decisions": "；".join(
            _student_relation_text(item) for item in decisions
        ),
        "selected_symbolic_point": symbolic_point,
        "selected_candidate_point": selected_symbolic_display,
        "selected_candidate_label": selected_candidate_label,
        "selected_point": selected_point,
        "curve_equation": curve_equation,
        "substitution_equation": (
            f"{_student_math_text(y_value)}＝"
            f"{_student_math_text(sp.sstr(curve_substitution))}"
        ),
        "zero_equation": f"{_student_math_text(residual)}＝0",
        "parameter_constraint": constraint,
        "parameter_equation": _student_math_text(parameter_equation),
        "parameter_result": parameter_result,
        "solved_curve": (
            "y＝"
            + student_quadratic_expression_display(
                str(witness.get("solved_curve") or "")
            )
        ),
        "derive_items_by_unit": {
            "curve_candidate_parameter_solve/filter_candidates": tuple(
                filter_derive
            ),
            "curve_candidate_parameter_solve/solve_parameter_and_curve": (
                f"∵{parameter_result}，{selected_symbolic_display}",
                f"∴{selected_point}",
            ),
        },
    }


def _macro_same_point(
    left: tuple[sp.Expr, sp.Expr],
    right: tuple[sp.Expr, sp.Expr],
) -> bool:
    return all(
        sp.simplify(_macro_sympify(left_item) - _macro_sympify(right_item)) == 0
        for left_item, right_item in zip(left, right, strict=True)
    )


def _single_macro_input(
    source: TeachingSource,
    name: str,
) -> Mapping[str, Any]:
    items = source.inputs.get(name, ())
    if len(items) != 1 or not isinstance(items[0], Mapping):
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_input_invalid: {source.source_step_id}.{name}"
        )
    return items[0]


def _macro_sympify(value: Any) -> sp.Expr:
    try:
        return sp.sympify(
            str(value),
            locals={
                "Abs": sp.Abs,
                "Eq": sp.Eq,
                "Piecewise": sp.Piecewise,
                "sqrt": sp.sqrt,
            },
        )
    except (TypeError, ValueError, SyntaxError, sp.SympifyError) as exc:
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_math_invalid: {value!r}"
        ) from exc


def _macro_equations_equivalent(left: Any, right: Any) -> bool:
    left_equation = _macro_sympify(left)
    right_equation = _macro_sympify(right)
    if not isinstance(left_equation, sp.Equality) or not isinstance(
        right_equation, sp.Equality
    ):
        return False
    left_residual = sp.expand(left_equation.lhs - left_equation.rhs)
    right_residual = sp.expand(right_equation.lhs - right_equation.rhs)
    return (
        sp.simplify(left_residual - right_residual) == 0
        or sp.simplify(left_residual + right_residual) == 0
    )


def _macro_symbol_constraint_text(
    source: TeachingSource,
    *,
    parameter_name: str,
) -> str:
    item = _single_macro_input(source, "symbol_constraint")
    value = item.get("value")
    if not isinstance(value, Mapping):
        raise TeachingSpecBindingError(
            "teaching_spec_macro_symbol_constraint_invalid: "
            f"{source.source_step_id}"
        )
    subject = str(value.get("subject") or "").rsplit(":", 1)[-1]
    operator = {
        ">": "＞",
        ">=": "≥",
        "<": "＜",
        "<=": "≤",
        "=": "＝",
        "==": "＝",
        "!=": "≠",
    }.get(str(value.get("operator") or ""))
    if subject != parameter_name or not operator or value.get("value") in (None, ""):
        raise TeachingSpecBindingError(
            "teaching_spec_macro_symbol_constraint_invalid: "
            f"{source.source_step_id}"
        )
    return f"{subject}{operator}{_student_math_text(value['value'])}"


def _student_parameter_value_text(value: sp.Expr) -> str:
    """Put positive terms before negative terms in short student answers."""

    expression = sp.simplify(value)
    if not isinstance(expression, sp.Add):
        return _student_math_text(expression)
    terms = tuple(sp.Add.make_args(expression))
    ordered = tuple(item for item in terms if not item.could_extract_minus_sign()) + tuple(
        item for item in terms if item.could_extract_minus_sign()
    )
    text = ""
    for term in ordered:
        negative = term.could_extract_minus_sign()
        body = _student_math_text(-term if negative else term)
        if not text:
            text = ("－" if negative else "") + body
        else:
            text += ("－" if negative else "＋") + body
    return text


def _labeled_macro_point(label: str, values: Sequence[Any]) -> str:
    return (
        f"{label}("
        + ",".join(_student_math_text(item) for item in values)
        + ")"
    )


def _indexed_candidate_label(label: str, index: int) -> str:
    subscript_digits = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    return f"{label}{str(index).translate(subscript_digits)}"


def _macro_point_list(
    source: TeachingSource,
    value: Any,
    *,
    role: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_{role}_invalid: {source.source_step_id}"
        )
    return tuple(_macro_point(source, item, role=role) for item in value)


def _macro_point(
    source: TeachingSource,
    value: Any,
    *,
    role: str,
) -> tuple[str, str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, str | bytes)
        or len(value) != 2
    ):
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_{role}_invalid: {source.source_step_id}"
        )
    return (str(value[0]), str(value[1]))


def _equal_length_ray_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    proof = _macro_equivalence_proof(source, witness)
    construction = _macro_construction(
        source,
        witness,
        kind="equal_length_point_on_ray",
    )
    label = str(construction.get("label") or "辅助点")
    anchor = str(construction.get("anchor") or "公共端点")
    reference = str(construction.get("reference_point") or "参考点")
    ray_point = str(construction.get("ray_direction_point") or "射线方向点")
    auxiliary_construction = (
        f"在射线{anchor}{ray_point}上构造{label}，"
        f"使{anchor}{label}＝{anchor}{reference}"
    )
    minimum_segment = str(construction.get("minimum_segment") or "")
    components = construction.get("minimum_distance_components")
    if (
        not minimum_segment
        or not isinstance(components, Sequence)
        or isinstance(components, str | bytes)
        or len(components) != 2
    ):
        raise TeachingSpecBindingError(
            "teaching_spec_equal_length_minimum_distance_missing: "
            f"{source.source_step_id}"
        )
    component_terms = "＋".join(
        f"({_student_math_text(item)})²" for item in components
    )
    minimum_expression = _student_math_text(
        str(witness.get("minimum_expression") or "")
    )
    return {
        "auxiliary_construction": auxiliary_construction,
        "congruence_facts": "；".join(
            _student_relation_text(item) for item in (proof[:-2] or proof[:-1])
        ),
        "replacement_equality": _student_relation_text(
            proof[-2] if len(proof) >= 2 else proof[-1]
        ),
        "original_objective": _student_relation_text(
            str(witness.get("original_objective") or "")
        ),
        "reduced_objective": _student_relation_text(
            str(witness.get("reduced_objective") or "")
        ),
        "minimum_inequality": (
            f"{_student_relation_text(str(witness.get('reduced_objective') or ''))}"
            f"≥{minimum_segment}"
        ),
        "minimum_calculation": (
            f"{minimum_segment}＝√[{component_terms}]＝{minimum_expression}"
        ),
        "minimum_expression": minimum_expression,
    }


def _coupled_segment_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    proof = _macro_equivalence_proof(source, witness)
    replacement = _macro_construction(
        source,
        witness,
        kind="existing_fixed_endpoint_replacement",
    )
    reflection = _macro_construction(
        source,
        witness,
        kind="line_reflection",
    )
    moving_point, point_value = _single_minimizing_point(source, witness)
    reflected_name = _student_point_name(
        str(reflection.get("reflected_point_name") or "对称点")
    )
    reflected_value = reflection.get("reflected_point")
    reflected_point = reflected_name
    if isinstance(reflected_value, Sequence) and not isinstance(
        reflected_value, str | bytes
    ):
        reflected_point += _point_coordinates(reflected_value)
    reflect_source = str(reflection.get("reflect_source") or "固定点")
    transformed = _student_prime_text(
        str(reflection.get("transformed_path") or witness.get("reduced_objective") or "")
    )
    straightened = _student_prime_text(
        str(reflection.get("straightened_path") or "")
    )
    minimum_segment = _student_prime_text(
        str(reflection.get("minimum_segment") or "")
    )
    straightened_path = f"{transformed}＝{straightened}"
    if minimum_segment:
        straightened_path += f"≥{minimum_segment}"
    roles: dict[str, Any] = {
        "replacement_equality": str(
            replacement.get("segment_equality") or proof[0]
        ),
        "original_objective": str(witness.get("original_objective") or ""),
        "reduced_objective": str(witness.get("reduced_objective") or ""),
        "moving_point": str(moving_point),
        "moving_locus": student_math_display(
            str(replacement.get("moving_locus") or "")
        ),
        "reflection_construction": (
            f"关于{moving_point}的轨迹作{reflect_source}的对称点"
            f"{reflected_point}"
        ),
        "straightened_path": straightened_path,
        "minimum_expression": student_math_display(
            str(witness.get("minimum_expression") or "")
        ),
        "attainment_point": f"{moving_point}{_point_coordinates(point_value)}",
    }
    geometry = replacement.get("geometry_certificate")
    if isinstance(geometry, Mapping):
        geometric_derive = _coupled_replacement_geometry_derive(
            source,
            geometry=geometry,
            original_objective=roles["original_objective"],
            reduced_objective=roles["reduced_objective"],
            replacement_equality=roles["replacement_equality"],
        )
        if geometric_derive:
            roles["derive_items_by_unit"] = {
                (
                    "coupled_segment_endpoint_replacement_path_minimum/"
                    "endpoint_replacement"
                ): geometric_derive,
            }
    return roles


def _coupled_replacement_geometry_derive(
    source: TeachingSource,
    *,
    geometry: Mapping[str, Any],
    original_objective: str,
    reduced_objective: str,
    replacement_equality: str,
) -> tuple[str, ...]:
    """Render the certified right-isosceles perpendicular-bisector proof."""

    if geometry.get("kind") != "right_isosceles_perpendicular_bisector":
        return ()
    role_values = geometry.get("roles")
    binding = geometry.get("binding")
    replacement = geometry.get("replacement")
    second_projection = geometry.get("student_second_leg_projection")
    first_projection = geometry.get("student_first_leg_projection")
    if not all(
        isinstance(item, Mapping)
        for item in (
            role_values,
            binding,
            replacement,
            second_projection,
            first_projection,
        )
    ):
        return ()
    assert isinstance(role_values, Mapping)
    assert isinstance(binding, Mapping)
    assert isinstance(replacement, Mapping)
    assert isinstance(second_projection, Mapping)
    assert isinstance(first_projection, Mapping)
    required_roles = {
        "right_vertex",
        "first_leg_vertex",
        "second_leg_vertex",
        "first_leg_moving_point",
        "hypotenuse_moving_point",
    }
    if set(role_values) != required_roles:
        return ()
    labels = {key: str(value) for key, value in role_values.items()}
    if any(not re.fullmatch(r"[A-Z](?:[0-9]+|[′']+)?", value) for value in labels.values()):
        return ()
    right = labels["right_vertex"]
    first_vertex = labels["first_leg_vertex"]
    second_vertex = labels["second_leg_vertex"]
    first_moving = labels["first_leg_moving_point"]
    hypotenuse_moving = labels["hypotenuse_moving_point"]
    second_foot = str(second_projection.get("label") or "")
    first_foot = str(first_projection.get("label") or "")
    if not second_foot or not first_foot:
        return ()
    expected_segments = {
        "first_leg": {right, first_vertex},
        "second_leg": {right, second_vertex},
        "hypotenuse": {first_vertex, second_vertex},
    }
    for field, expected in expected_segments.items():
        raw = geometry.get(field)
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, str | bytes)
            or len(raw) != 2
            or {str(item) for item in raw} != expected
        ):
            return ()
    binding_left = _point_role_segment(binding.get("left_segment"))
    binding_right = _point_role_segment(binding.get("right_segment"))
    replacement_left = _point_role_segment(replacement.get("left_segment"))
    replacement_right = _point_role_segment(replacement.get("right_segment"))
    if (
        binding_left != {right, first_moving}
        or binding_right != {second_vertex, hypotenuse_moving}
        or replacement_left != {first_moving, hypotenuse_moving}
        or replacement_right != {right, hypotenuse_moving}
        or sp.simplify(_macro_sympify(binding.get("scale")) - sp.sqrt(2)) != 0
    ):
        return ()
    required_relations = {
        "right_isosceles_frame",
        "hypotenuse_projection_isosceles",
        "projection_rectangle",
        "first_projection_is_binding_midpoint",
        "perpendicular_bisector",
        "endpoint_distances_equal",
    }
    if not required_relations.issubset(
        {str(item) for item in geometry.get("verified_relations", ())}
    ):
        return ()
    source_relation = _single_macro_input(source, "segment_binding_relation")
    source_value = source_relation.get("value")
    if isinstance(source_value, Mapping):
        source_scale = source_value.get("scale")
        if source_scale is not None and (
            sp.simplify(_macro_sympify(source_scale) - sp.sqrt(2)) != 0
        ):
            return ()

    right_first = f"{right}{first_vertex}"
    right_second = f"{right}{second_vertex}"
    hypotenuse = f"{first_vertex}{second_vertex}"
    binding_left_text = f"{right}{first_moving}"
    binding_right_text = f"{second_vertex}{hypotenuse_moving}"
    replacement_text = _student_relation_text(replacement_equality)
    return (
        f"作{hypotenuse_moving}{second_foot}⊥{right_second}于{second_foot}，"
        f"{hypotenuse_moving}{first_foot}⊥{right_first}于{first_foot}",
        f"∵△{right}{first_vertex}{second_vertex}是等腰直角三角形，"
        f"{hypotenuse_moving}在线段{hypotenuse}上",
        f"∴△{hypotenuse_moving}{second_vertex}{second_foot}"
        "是等腰直角三角形",
        f"∴{hypotenuse_moving}{second_foot}＝"
        f"{second_foot}{second_vertex}＝{binding_right_text}/√2",
        f"∵四边形{right}{first_foot}{hypotenuse_moving}{second_foot}是矩形",
        f"∴{right}{first_foot}＝{hypotenuse_moving}{second_foot}，"
        f"{hypotenuse_moving}{first_foot}＝{right}{second_foot}",
        f"∵{binding_left_text}＝√2·{binding_right_text}＝"
        f"2{hypotenuse_moving}{second_foot}",
        f"∴{first_moving}{first_foot}＝{binding_left_text}－"
        f"{right}{first_foot}＝{hypotenuse_moving}{second_foot}＝"
        f"{right}{first_foot}",
        f"∵{hypotenuse_moving}{first_foot}⊥{right_first}，"
        f"{right}、{first_moving}、{first_foot}在直线{right_first}上",
        f"∴{hypotenuse_moving}{first_foot}垂直平分"
        f"{right}{first_moving}",
        f"∴△{right}{hypotenuse_moving}{first_moving}是等腰三角形，"
        f"{replacement_text}",
        f"∴{_student_relation_text(original_objective)}＝"
        f"{_student_relation_text(reduced_objective)}",
    )


def _point_role_segment(value: Any) -> set[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, str | bytes)
        or len(value) != 2
    ):
        return set()
    return {str(item) for item in value}


def _weighted_axis_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    _macro_equivalence_proof(source, witness)
    construction = _macro_construction(
        source,
        witness,
        kind="weighted_right_triangle",
    )
    student_auxiliary = construction.get("student_auxiliary_point")
    if not isinstance(student_auxiliary, Mapping):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_student_auxiliary_missing: "
            f"{source.source_step_id}"
        )
    auxiliary_label = str(student_auxiliary.get("label") or "")
    if not auxiliary_label:
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_student_auxiliary_missing: "
            f"{source.source_step_id}"
        )
    weight_expression = _macro_sympify(construction.get("weight"))
    weight = student_math_display(str(weight_expression))
    resolved = {
        str(item.get("role") or ""): str(item.get("chosen_ref") or "")
        for item in witness.get("role_resolutions", ())
        if isinstance(item, Mapping)
    }
    fixed = resolved.get("fixed_point", "")
    curve = resolved.get("curve_point", "")
    moving = resolved.get("moving_point", "")
    if not fixed or not curve or not moving:
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_public_roles_missing: "
            f"{source.source_step_id}"
        )
    legal_domain = tuple(str(item) for item in witness.get("legal_domain", ()))
    domain_parts: list[str] = []
    for item in legal_domain[1:]:
        if item.startswith("取等条件："):
            condition = _student_math_text(item.removeprefix("取等条件："))
            domain_parts.append(
                "取等状态在整个参数定义域内均成立"
                if condition == "恒成立"
                else f"取等条件为 {condition}"
            )
        elif item.startswith("边界分支："):
            domain_parts.append(
                "边界分支为 "
                + _student_math_text(item.removeprefix("边界分支："))
            )
        else:
            domain_parts.append(_student_relation_text(item))
    original_objective = _student_math_text(
        str(witness.get("original_objective") or "")
    )
    locus_equation = _weighted_locus_equation(construction)
    axis_geometry = construction.get("axis_projection_geometry")
    if not isinstance(axis_geometry, Mapping):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_geometry_missing: "
            f"{source.source_step_id}"
        )
    axis_side = _weighted_auxiliary_axis_side(axis_geometry)
    fixed_moving = f"{fixed}{moving}"
    auxiliary_moving = f"{auxiliary_label}{moving}"
    curve_moving = f"{curve}{moving}"
    moving_auxiliary = f"{moving}{auxiliary_label}"
    curve_auxiliary = f"{curve}{auxiliary_label}"
    (
        weighted_segment,
        unit_segment,
        auxiliary_segment,
    ) = _weighted_path_equivalence_segments(
        source=source,
        construction=construction,
        labels={
            "fixed_point": fixed,
            "curve_point": curve,
            "moving_point": moving,
            "auxiliary_point": auxiliary_label,
        },
        weight=weight_expression,
    )
    reduced_objective = (
        f"{weight}({weighted_segment}＋{auxiliary_segment})"
    )
    profile = select_weighted_axis_teaching_profile(
        weight=weight_expression,
        geometry=axis_geometry,
    )
    if profile is not None:
        narrative = profile.reduction_narrative(
            fixed=fixed,
            auxiliary=auxiliary_label,
            moving=moving,
            axis_side=axis_side,
        )
        weighted_construction = narrative.construction
        weighted_equivalence_reason = narrative.equivalence_reason
        locus_angle: str | None = narrative.locus_angle
    else:
        weighted_construction = (
            f"在 x 轴{axis_side}作 Rt△{fixed}{auxiliary_label}{moving}，"
            f"使 ∠{fixed}{auxiliary_label}{moving}＝90°，"
            f"{fixed_moving}＝{weight}·{auxiliary_moving}"
        )
        weighted_equivalence_reason = "由辅助直角三角形的边长关系可得"
        locus_angle = None
    weighted_side_relation = f"{unit_segment}＝{weight}·{auxiliary_segment}"
    objective_expansion = (
        f"{original_objective}＝{weight}{weighted_segment}＋"
        f"{weight}{auxiliary_segment}"
    )
    auxiliary_locus_sentence = _weighted_auxiliary_locus_sentence(
        geometry=axis_geometry,
        auxiliary=auxiliary_label,
        fixed=fixed,
        angle=locus_angle,
        locus_equation=locus_equation,
    )
    domain_condition = (
        "；".join(dict.fromkeys(domain_parts))
        if domain_parts
        else "取等状态位于合法定义域内"
    )
    minimum_expression = _student_math_text(
        str(witness.get("minimum_expression") or "")
    )
    minimum_derive = _weighted_axis_geometric_minimum_derive(
        source=source,
        construction=construction,
        fixed=fixed,
        curve=curve,
        moving=moving,
        auxiliary=auxiliary_label,
        original_objective=original_objective,
        auxiliary_locus_sentence=auxiliary_locus_sentence,
    )
    attained_minimum_expression = _expanded_fraction_student_math(
        axis_geometry.get("scaled_interior_minimum")
    )
    attainment_condition = _student_math_text(
        axis_geometry.get("attainment_condition")
    )
    if not attained_minimum_expression or not attainment_condition:
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_attained_minimum_missing: "
            f"{source.source_step_id}"
        )
    attained_minimum_conclusion = (
        f"最小值为 {attained_minimum_expression}"
        if attainment_condition == "恒成立"
        else f"当 {attainment_condition} 时，最小值为 "
        f"{attained_minimum_expression}"
    )
    return {
        "weighted_construction": weighted_construction,
        "weighted_equivalence_reason": weighted_equivalence_reason,
        "weighted_side_relation": weighted_side_relation,
        "objective_expansion": objective_expansion,
        "original_objective": original_objective,
        "reduced_objective": reduced_objective,
        "auxiliary_locus": locus_equation,
        "auxiliary_locus_sentence": auxiliary_locus_sentence,
        "minimum_reason": "把等价的普通折线拉直，得到内部最短距离",
        "domain_condition": domain_condition,
        "minimum_expression": minimum_expression,
        "attainment_condition": attainment_condition,
        "attained_minimum_expression": attained_minimum_expression,
        "attained_minimum_conclusion": attained_minimum_conclusion,
        "derive_items_by_unit": {
            "weighted_axis_path_minimum/weighted_reduction": (
                f"作{weighted_construction}",
                f"∵{weighted_equivalence_reason}",
                f"∴{weighted_side_relation}",
                f"∴{objective_expansion}",
                f"∴{original_objective}＝{reduced_objective}",
                f"∵{moving} 在 x 轴上运动",
                f"∴{auxiliary_locus_sentence}",
            ),
            "weighted_axis_path_minimum/domain_minimum": minimum_derive,
        },
    }


def _weighted_path_equivalence_segments(
    *,
    source: TeachingSource,
    construction: Mapping[str, Any],
    labels: Mapping[str, str],
    weight: sp.Expr,
) -> tuple[str, str, str]:
    """Render only the role graph already published by runtime evidence."""

    path_equivalence = construction.get("path_equivalence")
    if not isinstance(path_equivalence, Mapping):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_path_equivalence_missing: "
            f"{source.source_step_id}"
        )
    try:
        scale_matches = sp.simplify(
            _macro_sympify(path_equivalence.get("scale")) - weight
        ) == 0
    except (TypeError, ValueError, sp.SympifyError):
        scale_matches = False
    if not scale_matches:
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_path_equivalence_scale_drift: "
            f"{source.source_step_id}"
        )

    expected_roles = {
        "weighted_segment": {
            labels["curve_point"],
            labels["moving_point"],
        },
        "unit_segment": {
            labels["fixed_point"],
            labels["moving_point"],
        },
        "auxiliary_segment": {
            labels["auxiliary_point"],
            labels["moving_point"],
        },
    }
    rendered: list[str] = []
    for field, expected in expected_roles.items():
        raw = path_equivalence.get(field)
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, str | bytes)
            or len(raw) != 2
            or {str(item) for item in raw} != expected
        ):
            raise TeachingSpecBindingError(
                "teaching_spec_weighted_path_equivalence_invalid: "
                f"{source.source_step_id}:{field}"
            )
        rendered.append("".join(str(item) for item in raw))
    return rendered[0], rendered[1], rendered[2]


def _weighted_auxiliary_axis_side(geometry: Mapping[str, Any]) -> str:
    direction = geometry.get("locus_direction")
    if (
        not isinstance(direction, Sequence)
        or isinstance(direction, str | bytes)
        or len(direction) != 2
    ):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_locus_direction_missing"
        )
    vertical = _macro_sympify(direction[1])
    if vertical.is_positive:
        return "上方"
    if vertical.is_negative:
        return "下方"
    raise TeachingSpecBindingError(
        "teaching_spec_weighted_locus_side_undetermined"
    )


def _weighted_auxiliary_locus_sentence(
    *,
    geometry: Mapping[str, Any],
    auxiliary: str,
    fixed: str,
    angle: str | None,
    locus_equation: str,
) -> str:
    reference = geometry.get("locus_reference_point")
    if (
        not isinstance(reference, Sequence)
        or isinstance(reference, str | bytes)
        or len(reference) != 2
    ):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_locus_reference_missing"
        )
    reference_text = "(" + ",".join(
        _student_coordinate_math(item) for item in reference
    ) + ")"
    x_value = _macro_sympify(reference[0])
    y_value = _macro_sympify(reference[1])
    if sp.simplify(x_value) == 0 and y_value.is_positive:
        reference_description = f"y 轴正半轴点 {reference_text}"
    elif sp.simplify(x_value) == 0:
        reference_description = f"y 轴上的点 {reference_text}"
    else:
        reference_description = f"点 {reference_text}"
    angle_description = f"{angle} " if angle else ""
    return (
        f"{auxiliary} 在过 {fixed} 且经过 {reference_description} 的 "
        f"{angle_description}固定射线 {locus_equation} 上运动"
    )


def _weighted_axis_geometric_minimum_derive(
    *,
    source: TeachingSource,
    construction: Mapping[str, Any],
    fixed: str,
    curve: str,
    moving: str,
    auxiliary: str,
    original_objective: str,
    auxiliary_locus_sentence: str,
) -> tuple[str, ...]:
    """Render the shortest-path idea without exposing its internal calculation."""

    geometry = construction.get("axis_projection_geometry")
    if not isinstance(geometry, Mapping):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_geometry_missing: "
            f"{source.source_step_id}"
        )
    if geometry.get("kind") != "axis_projection_geometric_minimum":
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_geometry_invalid: "
            f"{source.source_step_id}"
        )
    moving_domain, _moving_region, _boundary_description = (
        _weighted_axis_domain_phrases(geometry, moving=moving)
    )
    interior_moving_point = _weighted_geometry_point(
        geometry,
        key="interior_moving_point",
        label=moving,
        source=source,
        factor_coordinates=True,
    )
    scaled_minimum = _expanded_fraction_student_math(
        geometry.get("scaled_interior_minimum")
    )
    attainment_condition = _student_math_text(
        geometry.get("attainment_condition")
    )
    if not all((scaled_minimum, attainment_condition)):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_geometry_values_missing: "
            f"{source.source_step_id}"
        )

    curve_moving = f"{curve}{moving}"
    moving_auxiliary = f"{moving}{auxiliary}"
    curve_auxiliary = f"{curve}{auxiliary}"
    fixed_auxiliary = f"{fixed}{auxiliary}"

    return (
        "∵两点之间线段最短",
        f"∴{curve_moving}＋{moving_auxiliary}≥{curve_auxiliary}",
        f"∴当 {curve}、{moving}、{auxiliary} 三点共线时，折线最短",
        f"∵{auxiliary_locus_sentence}",
        f"∴最短时 {curve_auxiliary}⊥{fixed_auxiliary}",
        f"∵取等时 {interior_moving_point}，且 {moving_domain}",
        (
            "∴取等状态在定义域内恒成立"
            if attainment_condition == "恒成立"
            else f"∴取等条件为 {attainment_condition}"
        ),
        f"∴此时 {original_objective} 的最小值为 {scaled_minimum}",
    )


def _weighted_geometry_point(
    geometry: Mapping[str, Any],
    *,
    key: str,
    label: str,
    source: TeachingSource,
    factor_coordinates: bool = False,
) -> str:
    values = geometry.get(key)
    if not isinstance(values, Sequence) or isinstance(values, str | bytes):
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_point_missing: "
            f"{source.source_step_id}:{key}"
        )
    if len(values) != 2:
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_axis_point_invalid: "
            f"{source.source_step_id}:{key}"
        )
    formatter = (
        _factored_student_math
        if factor_coordinates
        else _student_coordinate_math
    )
    return f"{label}({','.join(formatter(item) for item in values)})"


def _student_coordinate_math(value: Any) -> str:
    try:
        expression = _macro_sympify(value)
    except (TypeError, ValueError, sp.SympifyError):
        return _student_math_text(value)
    expanded = sp.expand(expression)
    if (
        isinstance(expanded, sp.Add)
        and expanded.args
        and all(term.could_extract_minus_sign() for term in expanded.args)
    ):
        return _factored_student_math(expanded)
    return _student_math_text(str(expanded))


def _factored_student_math(value: Any) -> str:
    try:
        expression = _macro_sympify(value)
    except (TypeError, ValueError, sp.SympifyError):
        return _student_math_text(value)
    factored = str(sp.factor(expression))
    if "-(-" in factored:
        factored = str(sp.together(expression))
    return _student_math_text(factored)


def _expanded_fraction_student_math(value: Any) -> str:
    try:
        expression = _macro_sympify(value)
    except (TypeError, ValueError, sp.SympifyError):
        return _student_math_text(value)
    numerator, denominator = sp.fraction(sp.together(expression))
    numerator_text = _student_math_text(str(sp.expand(numerator)))
    if denominator == 1:
        return numerator_text
    denominator_text = _student_math_text(str(denominator))
    if isinstance(sp.expand(numerator), sp.Add):
        numerator_text = f"({numerator_text})"
    return f"{numerator_text}/{denominator_text}"


def _student_radical_product(value: str) -> str:
    return re.sub(r"(√\d+)\(", r"\1·(", value)


def _weighted_parameter_complement_range(
    geometry: Mapping[str, Any],
) -> str:
    parameter = str(geometry.get("parameter") or "")
    domain = geometry.get("parameter_constraint")
    attainment = _macro_sympify(geometry.get("attainment_condition"))
    if (
        parameter
        and isinstance(domain, Mapping)
        and domain.get("operator") == ">"
        and isinstance(attainment, sp.StrictGreaterThan)
        and str(attainment.lhs) == parameter
    ):
        lower = _student_math_text(domain.get("value"))
        upper = _student_math_text(attainment.rhs)
        return f"{lower}＜{parameter}≤{upper}"
    return "不满足内部取等条件"


def _weighted_axis_domain_phrases(
    geometry: Mapping[str, Any],
    *,
    moving: str,
) -> tuple[str, str, str]:
    constraint = geometry.get("dynamic_constraint")
    dynamic_parameter = str(geometry.get("dynamic_parameter") or "")
    if not isinstance(constraint, Mapping) or not dynamic_parameter:
        raise TeachingSpecBindingError(
            "teaching_spec_weighted_dynamic_domain_missing"
        )
    operator = str(constraint.get("operator") or "")
    lower = _macro_sympify(constraint.get("value"))
    if operator == ">" and sp.simplify(lower) == 0:
        return (
            f"{moving} 在 x 轴正半轴上",
            " x 轴正半轴",
            "正半轴端点",
        )
    relation = _student_math_text(
        f"{dynamic_parameter}{operator}{lower}"
    )
    return (
        f"{moving} 在 x 轴上且 {relation}",
        "题设的轴上范围",
        "该范围的端点",
    )


def _weighted_locus_equation(construction: Mapping[str, Any]) -> str:
    raw = str(construction.get("auxiliary_locus") or "").strip()
    if not raw:
        raise TeachingSpecBindingError("teaching_spec_weighted_locus_missing")
    try:
        if "=" in raw and not raw.lstrip().startswith("Eq("):
            left, right = raw.split("=", 1)
            expression = _macro_sympify(left) - _macro_sympify(right)
        else:
            parsed = _macro_sympify(raw)
            expression = (
                parsed.lhs - parsed.rhs
                if isinstance(parsed, sp.Equality)
                else parsed
            )
        y = sp.Symbol("y")
        solutions = sp.solve(sp.Eq(expression, 0), y)
    except (
        TypeError,
        ValueError,
        NotImplementedError,
        sp.SympifyError,
        TeachingSpecBindingError,
    ) as exc:
        raise TeachingSpecBindingError(
            f"teaching_spec_weighted_locus_invalid: {raw!r}"
        ) from exc
    if len(solutions) != 1:
        raise TeachingSpecBindingError(
            f"teaching_spec_weighted_locus_invalid: {raw!r}"
        )
    return "y＝" + _student_math_text(sp.simplify(solutions[0]))


def _macro_equivalence_proof(
    source: TeachingSource,
    witness: Mapping[str, Any],
) -> tuple[str, ...]:
    proof = tuple(str(item) for item in witness.get("equivalence_proof", ()))
    if not proof:
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_equivalence_proof_missing: {source.source_step_id}"
        )
    return proof


def _macro_construction(
    source: TeachingSource,
    witness: Mapping[str, Any],
    *,
    kind: str,
) -> Mapping[str, Any]:
    matches = tuple(
        item
        for item in witness.get("constructions", ())
        if isinstance(item, Mapping) and item.get("kind") == kind
    )
    if len(matches) != 1:
        raise TeachingSpecBindingError(
            "teaching_spec_macro_construction_invalid: "
            f"step={source.source_step_id}, kind={kind}, matches={len(matches)}"
        )
    return matches[0]


def _single_minimizing_point(
    source: TeachingSource,
    witness: Mapping[str, Any],
) -> tuple[str, Sequence[Any]]:
    minimizing = witness.get("minimizing_points")
    if not isinstance(minimizing, Mapping) or len(minimizing) != 1:
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_attainment_invalid: {source.source_step_id}"
        )
    moving_point, point_value = next(iter(minimizing.items()))
    if not isinstance(point_value, Sequence) or isinstance(
        point_value, str | bytes
    ):
        raise TeachingSpecBindingError(
            f"teaching_spec_macro_attainment_invalid: {source.source_step_id}"
        )
    return str(moving_point), point_value


def _student_point_name(value: str) -> str:
    return _student_prime_text(value)


def _student_prime_text(value: str) -> str:
    return value.replace("_prime", "′").replace("A_prime", "A′")


def _student_relation_text(value: Any) -> str:
    """Studentize operators without removing spaces from Chinese prose."""

    return (
        _student_prime_text(str(value))
        .replace("=", "＝")
        .replace("+", "＋")
        .replace("-", "－")
    )


def _student_math_text(value: Any) -> str:
    return student_math_display(value, fullwidth_operators=True)


def _point_coordinates(values: Sequence[Any]) -> str:
    return "(" + ",".join(student_math_display(item) for item in values) + ")"


def _bind_unit(
    source: TeachingSource,
    unit: TeachingUnitSpec,
    roles: Mapping[str, Any],
) -> BoundTeachingUnit:
    fields = {
        "nav_title": format_teaching_template(unit.nav_title_template, roles).strip(),
        "title": format_teaching_template(unit.title_template, roles).strip(),
        "goal": format_teaching_template(unit.goal_template, roles).strip(),
    }
    derive = _bound_derive(unit, roles)
    box = tuple(
        format_teaching_template(template, roles).strip()
        for template in unit.box_templates
    )
    all_text = [*fields.values(), *(item[1] for item in derive), *box]
    unresolved = sorted(
        {
            match.group(1)
            for value in all_text
            for match in re.finditer(r"\{([^{}]+)\}", value)
        }
    )
    if unresolved:
        raise TeachingSpecBindingError(
            "teaching_spec_placeholder_unresolved: "
            f"step={source.source_step_id}, unit={unit.unit_key}, "
            f"roles={unresolved}"
        )
    if any(not value for value in all_text) or contains_private_path_projection_marker(
        all_text
    ):
        raise TeachingSpecBindingError(
            "teaching_spec_bound_content_invalid: "
            f"step={source.source_step_id}, unit={unit.unit_key}"
        )
    return BoundTeachingUnit(
        source_step_id=source.source_step_id,
        unit_key=unit.unit_key,
        nav_title=fields["nav_title"],
        title=fields["title"],
        goal=fields["goal"],
        derive=derive,
        box=box,
        visuals=tuple({"spec_id": v["spec_id"], "roles": {k: source.source_step_id if ref == "$source" else ref for k, ref in v["roles"].items()}} for v in unit.visuals),
    )


def _bind_unit_or_fallback(
    source: TeachingSource,
    unit: TeachingUnitSpec,
    roles: Mapping[str, Any],
    *,
    on_unit_error: TeachingUnitFallback | None,
) -> BoundTeachingUnit:
    try:
        return _bind_unit(source, unit, roles)
    except TeachingSpecBindingError as exc:
        if on_unit_error is None:
            raise
        return on_unit_error(unit, exc)


def _bound_derive(
    unit: TeachingUnitSpec,
    roles: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Prefer verified, runtime-bound proof lines when a role binder provides them."""

    dynamic_by_unit = roles.get("derive_items_by_unit")
    dynamic = (
        dynamic_by_unit.get(unit.unit_key)
        if isinstance(dynamic_by_unit, Mapping)
        else None
    )
    if dynamic is None:
        dynamic = roles.get("derive_items")
    if isinstance(dynamic, Sequence) and not isinstance(dynamic, str | bytes):
        result: list[tuple[str, str]] = []
        for raw in dynamic:
            text = format_teaching_template(str(raw), roles).strip()
            marker = next(
                (item for item in ("∵", "∴", "作", "设", "计算") if text.startswith(item)),
                "计算",
            )
            content = text.removeprefix(marker).strip()
            if not content:
                raise TeachingSpecBindingError(
                    "teaching_spec_dynamic_derive_invalid: "
                    f"unit={unit.unit_key}"
                )
            result.append((marker, content))
        if result:
            return tuple(result)
    return tuple(
        (str(marker), format_teaching_template(template, roles).strip())
        for marker, template in unit.derive_templates
    )


__all__ = [
    "BoundTeachingSelection",
    "BoundTeachingUnit",
    "INDEPENDENT_LESSON_STEP_TEMPLATE_KEY",
    "TeachingSeparationBoundaryResolver",
    "TeachingSpecBinder",
    "TeachingSpecBindingError",
    "TeachingUnitFallback",
]
