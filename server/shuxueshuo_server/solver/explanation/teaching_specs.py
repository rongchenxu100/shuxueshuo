"""Bind generic Method/Macro Teaching Specs to one verified Snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping, Sequence

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
    TeachingUnitSpec,
)
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.recipes._spec import MacroTeachingSpec
from shuxueshuo_server.solver.student_display import student_math_display

from .models import ExplanationSnapshot, LessonCandidateGroup, TeachingSource
from .role_binders import RoleBinderRegistry
from .role_binders.common import format_template
from .role_binders.methods import _quadratic_curve_point_derivation


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


class TeachingSpecBinder:
    """Resolve one capability spec and bind it using verified Snapshot data."""

    def __init__(
        self,
        *,
        methods: MethodSpecRegistry | None = None,
        recipes: RecipeSpecRegistry | None = None,
        role_binders: RoleBinderRegistry | None = None,
    ) -> None:
        self._methods = methods or MethodSpecRegistry.load_from_code()
        self._recipes = recipes or RecipeSpecRegistry.load_from_code()
        self._role_binders = role_binders or RoleBinderRegistry.default()

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
        group = _group_for_source(source, snapshot)
        if method is not None:
            unit = method.teaching_unit or _default_teaching_unit(source)
            explanation = MethodExplanationSpec(
                role_schema=dict(unit.role_schema),
                student_goal_template=unit.goal_template,
                student_title_template=unit.title_template,
                student_nav_title_template=unit.nav_title_template,
                role_binder_id=unit.role_binder_id,
            )
            roles = self._role_binders.require_method(unit.role_binder_id).bind(
                method_id=method.method_id,
                explanation=explanation,
                group=group,
                snapshot=snapshot,
            )
            roles = _enrich_method_roles(
                source,
                roles,
                group=group,
                snapshot=snapshot,
            )
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


def _group_for_source(
    source: TeachingSource,
    snapshot: ExplanationSnapshot,
) -> LessonCandidateGroup:
    step = next(
        (
            item
            for item in snapshot.effective_steps
            if str(item.get("step_id") or "") == source.source_step_id
        ),
        None,
    )
    if step is None:
        raise TeachingSpecBindingError(
            f"teaching_spec_source_step_missing: {source.source_step_id}"
        )
    return LessonCandidateGroup(step=step, sources=(source,))


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


def _enrich_method_roles(
    source: TeachingSource,
    roles: Mapping[str, Any],
    *,
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    result = dict(roles)
    if source.capability_id == "quadratic_from_constraints":
        dynamic = _quadratic_curve_point_derivation(
            group=group,
            snapshot=snapshot,
            calculation="",
            result_parabola=str(result.get("result_parabola") or ""),
            completed_square_suffix=str(result.get("completed_square_suffix") or ""),
            use_verified_source=True,
        )
        if dynamic:
            result["derive_items"] = dynamic
            result["constraint_origin"] = dynamic[0].removeprefix("∵")
            result["constraint_derivation"] = "；".join(
                item.removeprefix("∵").removeprefix("∴")
                for item in dynamic[1:-1]
            )
    if source.capability_id != "evaluate_point_at_parameter":
        return result
    point_inputs = source.inputs.get("point", ())
    parameter_inputs = source.inputs.get("parameter_value", ())
    evaluated = source.outputs.get("evaluated_point")
    if len(point_inputs) == 1:
        source_display = str(point_inputs[0].get("display") or "")
        target = source.output_targets.get("evaluated_point")
        if target and source_display.startswith("("):
            source_display = f"{target}{source_display}"
        result["source_point"] = source_display
    if len(parameter_inputs) == 1:
        item = parameter_inputs[0]
        ref = item.get("ref")
        if isinstance(ref, Mapping) and ref.get("kind") == "source":
            result["parameter"] = str(ref.get("ref") or "")
        result["parameter_value"] = str(item.get("display") or "")
    if evaluated is not None:
        result["evaluated_point"] = str(evaluated.get("display") or "")
    return result


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
    witness = witnesses[0]
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
        "nav_title": format_template(unit.nav_title_template, dict(roles)).strip(),
        "title": format_template(unit.title_template, dict(roles)).strip(),
        "goal": format_template(unit.goal_template, dict(roles)).strip(),
    }
    derive = _bound_derive(unit, roles)
    box = tuple(
        format_template(template, dict(roles)).strip()
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
            text = format_template(str(raw), dict(roles)).strip()
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
        (str(marker), format_template(template, dict(roles)).strip())
        for marker, template in unit.derive_templates
    )


__all__ = [
    "BoundTeachingSelection",
    "BoundTeachingUnit",
    "TeachingSpecBinder",
    "TeachingSpecBindingError",
    "TeachingUnitFallback",
]
