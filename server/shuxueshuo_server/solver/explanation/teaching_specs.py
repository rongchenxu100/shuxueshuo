"""Bind generic Method/Macro Teaching Specs to one verified Snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping, Sequence

from shuxueshuo_server.solver.contracts import TeachingUnitSpec
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.recipes._spec import MacroTeachingSpec
from shuxueshuo_server.solver.student_display import student_math_display

from .models import ExplanationSnapshot, TeachingSource
from .teaching_role_bindings import (
    TeachingRoleBindingError,
    bind_teaching_roles,
    format_teaching_template,
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
            unit = method.teaching_unit or _default_teaching_unit(source)
            try:
                roles = bind_teaching_roles(
                    source,
                    unit,
                    snapshot=snapshot,
                )
            except TeachingRoleBindingError as exc:
                raise TeachingSpecBindingError(str(exc)) from exc
            return BoundTeachingSelection(
                kind="function",
                units=(
                    _bind_unit_or_fallback(
                        source,
                        unit,
                        roles,
                        on_unit_error=on_unit_error,
                    ),
                ),
            )
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
        return _weighted_axis_macro_roles(source, witness=witness)
    if source.capability_id == "right_angle_equal_length_construct_and_select":
        return _right_angle_construct_select_macro_roles(
            source,
            witness=witness,
        )
    if source.capability_id == "curve_candidate_parameter_solve":
        return _curve_candidate_parameter_macro_roles(
            source,
            witness=witness,
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
    return {
        "construction_condition": "；".join(checks),
        "candidate_points": "，".join(_point_coordinates(item) for item in candidates),
        "selection_condition": str(witness.get("selection_condition") or ""),
        "candidate_decisions": "；".join(decisions),
        "selected_point": _point_coordinates(selected),
    }


def _curve_candidate_parameter_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
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
    return {
        "candidate_points": "，".join(_point_coordinates(item) for item in candidates),
        "candidate_substitutions": "；".join(equations),
        "candidate_decisions": "；".join(decisions),
        "selected_point": _point_coordinates(selected),
        "parameter_equation": str(witness.get("parameter_equation") or ""),
        "parameter_result": f"{parameter_name}＝{parameter_value}",
        "solved_curve": student_math_display(
            str(witness.get("solved_curve") or "")
        ),
    }


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
    coordinate = construction.get("coordinate")
    coordinate_text = ""
    if isinstance(coordinate, Sequence) and not isinstance(
        coordinate, str | bytes
    ):
        coordinate_text = _point_coordinates(coordinate)
    auxiliary_construction = (
        f"在射线{anchor}{ray_point}上构造{label}{coordinate_text}，"
        f"使{anchor}{label}＝{anchor}{reference}"
    )
    return {
        "auxiliary_construction": auxiliary_construction,
        "congruence_facts": "；".join(proof[:-2] or proof[:-1]),
        "replacement_equality": proof[-2] if len(proof) >= 2 else proof[-1],
        "original_objective": str(witness.get("original_objective") or ""),
        "reduced_objective": str(witness.get("reduced_objective") or ""),
        "minimum_reason": "化简后的折线路径不短于两端点间的直线距离",
        "minimum_expression": student_math_display(
            str(witness.get("minimum_expression") or "")
        ),
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
    return {
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


def _weighted_axis_macro_roles(
    source: TeachingSource,
    *,
    witness: Mapping[str, Any],
) -> dict[str, Any]:
    proof = _macro_equivalence_proof(source, witness)
    construction = _macro_construction(
        source,
        witness,
        kind="weighted_right_triangle",
    )
    formula = construction.get("auxiliary_point_formula")
    formula_text = ""
    if isinstance(formula, Sequence) and not isinstance(formula, str | bytes):
        formula_text = f"，辅助点坐标为{_point_coordinates(formula)}"
    weight = student_math_display(str(construction.get("weight") or ""))
    legal_domain = tuple(str(item) for item in witness.get("legal_domain", ()))
    domain_parts: list[str] = []
    for item in legal_domain[1:]:
        if item.startswith("attainment condition: "):
            domain_parts.append(
                "取等条件为 "
                + student_math_display(item.removeprefix("attainment condition: "))
            )
        elif item.startswith("boundary branch: "):
            domain_parts.append(
                "边界分支为 "
                + student_math_display(item.removeprefix("boundary branch: "))
            )
        else:
            domain_parts.append(item)
    return {
        "weighted_construction": (
            f"根据权重 {weight} 构造对应的辅助直角三角形{formula_text}"
        ),
        "weighted_equivalence_reason": proof[0],
        "original_objective": str(witness.get("original_objective") or ""),
        "reduced_objective": str(witness.get("reduced_objective") or ""),
        "auxiliary_locus": student_math_display(
            str(construction.get("auxiliary_locus") or "")
        ),
        "minimum_reason": "把等价的普通折线拉直，得到内部最短距离",
        "domain_condition": "；".join(domain_parts) or "取等状态位于合法定义域内",
        "minimum_expression": student_math_display(
            str(witness.get("minimum_expression") or "")
        ),
    }


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
