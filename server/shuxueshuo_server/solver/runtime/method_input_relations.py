"""Resolve Method entity relations to exact, scope-visible Conditions.

The FunctionalPlan wire names mathematical entities only.  This module proves
that a Method may use those entities together by resolving the corresponding
structured Condition before state materialization reaches the Method runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.contracts import (
    MethodInputRelationSpec,
    MethodSpec,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
    FunctionalSemanticView,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalMethodRelationBinding,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId


@dataclass(frozen=True)
class MethodInputRelationIssue:
    code: str
    message: str
    details: Mapping[str, Any]


@dataclass(frozen=True)
class MethodInputRelationResolution:
    bindings: tuple[FunctionalMethodRelationBinding, ...] = ()
    issues: tuple[MethodInputRelationIssue, ...] = ()


def resolve_method_input_relations(
    method_spec: MethodSpec,
    resolved_args: Mapping[str, Sequence[ResolvedFunctionalValue]],
    *,
    call_id: str,
    capability_id: str,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> MethodInputRelationResolution:
    """Resolve every declared relation without aliases, labels, or guessing."""

    bindings: list[FunctionalMethodRelationBinding] = []
    issues: list[MethodInputRelationIssue] = []
    for relation in method_spec.input_relations:
        points = tuple(resolved_args.get(relation.point_arg, ()))
        if not points:
            # Optional point inputs do not consume a relation when omitted.
            continue
        curves = tuple(resolved_args.get(relation.curve_arg, ()))
        contract_issue = _relation_contract_issue(
            method_spec,
            relation,
            point_count=len(points),
            curve_count=len(curves),
            call_id=call_id,
            capability_id=capability_id,
            scope_id=scope_id,
        )
        if contract_issue is not None:
            issues.append(contract_issue)
            continue
        curve = curves[0]
        for item_index, point in enumerate(points):
            item = _resolve_one_relation(
                method_spec,
                relation,
                point=point,
                curve=curve,
                item_index=item_index,
                call_id=call_id,
                capability_id=capability_id,
                scope_id=scope_id,
                semantic_index=semantic_index,
            )
            if isinstance(item, MethodInputRelationIssue):
                issues.append(item)
            else:
                bindings.append(item)
    return MethodInputRelationResolution(
        bindings=tuple(bindings),
        issues=tuple(issues),
    )


def _relation_contract_issue(
    method_spec: MethodSpec,
    relation: MethodInputRelationSpec,
    *,
    point_count: int,
    curve_count: int,
    call_id: str,
    capability_id: str,
    scope_id: str,
) -> MethodInputRelationIssue | None:
    expected_point_count = 1 if relation.cardinality == "one" else None
    if curve_count == 1 and (
        expected_point_count is None or point_count == expected_point_count
    ):
        return None
    return MethodInputRelationIssue(
        code="planner.method_relation_contract_invalid",
        message=(
            "Method relation contract cannot identify one curve and the "
            "declared point cardinality"
        ),
        details={
            "method_id": method_spec.method_id,
            "capability_id": capability_id,
            "call_id": call_id,
            "step_id": call_id,
            "scope_id": scope_id,
            "arg_name": relation.point_arg,
            "relation_kind": relation.relation_kind,
            "expected_curve_count": 1,
            "expected_point_count": expected_point_count,
            "observed_curve_count": curve_count,
            "observed_point_count": point_count,
            "retryability": "configuration",
            "repair_action": "fix_runtime_contract",
            "repair_call_ids": [call_id],
        },
    )


def _resolve_one_relation(
    method_spec: MethodSpec,
    relation: MethodInputRelationSpec,
    *,
    point: ResolvedFunctionalValue,
    curve: ResolvedFunctionalValue,
    item_index: int,
    call_id: str,
    capability_id: str,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> FunctionalMethodRelationBinding | MethodInputRelationIssue:
    point_ref = _exact_object_ref(point, semantic_index=semantic_index)
    curve_ref = _exact_object_ref(curve, semantic_index=semantic_index)
    if point_ref is None or curve_ref is None:
        return _issue(
            "planner.method_relation_contract_invalid",
            "Method relation arguments have no exact MathObject identity",
            method_spec=method_spec,
            relation=relation,
            call_id=call_id,
            capability_id=capability_id,
            scope_id=scope_id,
            item_index=item_index,
            point_ref=point_ref,
            curve_ref=curve_ref,
            point=point,
            curve=curve,
            retryability="configuration",
            repair_action="fix_runtime_contract",
        )

    candidates, malformed = _condition_candidates(
        semantic_index,
        accepted_condition_kinds=relation.accepted_condition_kinds,
    )
    if malformed:
        return _issue(
            "planner.method_relation_contract_invalid",
            "A curve-membership Condition has invalid structured object roles",
            method_spec=method_spec,
            relation=relation,
            call_id=call_id,
            capability_id=capability_id,
            scope_id=scope_id,
            item_index=item_index,
            point_ref=point_ref,
            curve_ref=curve_ref,
            point=point,
            curve=curve,
            retryability="configuration",
            repair_action="fix_runtime_contract",
            observed={"malformed_condition_refs": sorted(malformed)},
        )

    exact = tuple(
        item
        for item in candidates
        if _condition_role(item, "point") == point_ref
        and _condition_role(item, "curve") == curve_ref
    )
    visible = tuple(
        item
        for item in exact
        if visible_from_valid_scope(
            item.valid_scope,
            scope_id=scope_id,
            registry=semantic_index.handle_registry,
        )
    )
    if not visible:
        authority_candidates, _authority_malformed = _condition_candidates(
            semantic_index,
            accepted_condition_kinds=relation.accepted_condition_kinds,
            authority=True,
        )
        authority_exact = tuple(
            item
            for item in authority_candidates
            if _condition_role(item, "point") == point_ref
            and _condition_role(item, "curve") == curve_ref
        )
        repairable_descendants = tuple(
            item
            for item in authority_exact
            if scope_id
            in semantic_index.handle_registry.ancestor_scopes(
                item.authority_scope_id or item.valid_scope
            )
        )
        if exact or repairable_descendants:
            owner_scopes = sorted(
                {
                    item.authority_scope_id or item.valid_scope
                    for item in (*exact, *repairable_descendants)
                }
            )
            return _issue(
                "functional.method_relation_not_visible",
                (
                    "The required point-on-curve Condition exists but is not "
                    "visible from the authored call scope"
                ),
                method_spec=method_spec,
                relation=relation,
                call_id=call_id,
                capability_id=capability_id,
                scope_id=scope_id,
                item_index=item_index,
                point_ref=point_ref,
                curve_ref=curve_ref,
                point=point,
                curve=curve,
                repair_action="place_step_in_relation_scope",
                observed={"relation_owner_scopes": owner_scopes},
            )
        mismatched_curves = sorted(
            {
                candidate_curve
                for item in candidates
                if _condition_role(item, "point") == point_ref
                if visible_from_valid_scope(
                    item.valid_scope,
                    scope_id=scope_id,
                    registry=semantic_index.handle_registry,
                )
                if (candidate_curve := _condition_role(item, "curve"))
                is not None
            }
        )
        if mismatched_curves:
            return _issue(
                "functional.method_relation_argument_mismatch",
                "The selected Point is related to a different curve object",
                method_spec=method_spec,
                relation=relation,
                call_id=call_id,
                capability_id=capability_id,
                scope_id=scope_id,
                item_index=item_index,
                point_ref=point_ref,
                curve_ref=curve_ref,
                point=point,
                curve=curve,
                repair_action="align_curve_relation_arguments",
                observed={"related_curve_refs": mismatched_curves},
            )
        return _issue(
            "functional.method_relation_missing",
            "No Goal-visible point-on-curve Condition proves this input relation",
            method_spec=method_spec,
            relation=relation,
            call_id=call_id,
            capability_id=capability_id,
            scope_id=scope_id,
            item_index=item_index,
            point_ref=point_ref,
            curve_ref=curve_ref,
            point=point,
            curve=curve,
            repair_action="provide_visible_curve_relation",
        )

    selected = _select_semantic_duplicate(visible, scope_id, semantic_index)
    if selected is None or selected.condition_id is None:
        return _issue(
            "planner.method_relation_contract_invalid",
            "Visible curve-membership Conditions cannot be folded deterministically",
            method_spec=method_spec,
            relation=relation,
            call_id=call_id,
            capability_id=capability_id,
            scope_id=scope_id,
            item_index=item_index,
            point_ref=point_ref,
            curve_ref=curve_ref,
            point=point,
            curve=curve,
            retryability="configuration",
            repair_action="fix_runtime_contract",
            observed={
                "condition_refs": sorted({item.ref for item in visible})
            },
        )
    return FunctionalMethodRelationBinding(
        call_id=call_id,
        method_id=method_spec.method_id,
        relation_kind=relation.relation_kind,
        point_arg_name=relation.point_arg,
        point_item_index=item_index,
        curve_arg_name=relation.curve_arg,
        condition_id=selected.condition_id,
        condition_ref=selected.ref,
        condition_ref_kind=selected.kind,
        condition_kind=str(selected.condition_kind),
        owner_scope_id=(selected.authority_scope_id or selected.valid_scope),
        point_object_ref=point_ref,
        curve_object_ref=curve_ref,
        point_math_object_id=_math_object_id(point),
        curve_math_object_id=_math_object_id(curve),
    )


def _condition_candidates(
    semantic_index: FunctionalSemanticIndex,
    *,
    accepted_condition_kinds: Sequence[str],
    authority: bool = False,
) -> tuple[tuple[FunctionalSemanticView, ...], tuple[str, ...]]:
    by_condition_id: dict[str, FunctionalSemanticView] = {}
    malformed: list[str] = []
    views = (
        semantic_index.relation_authority_views
        if authority
        else semantic_index.views
    )
    for view in views:
        if (
            view.runtime_type != "Condition"
            or view.condition_kind not in accepted_condition_kinds
        ):
            continue
        point_refs = dict(view.object_roles).get("point", ())
        curve_refs = dict(view.object_roles).get("curve", ())
        if (
            view.condition_id is None
            or len(point_refs) != 1
            or len(curve_refs) != 1
        ):
            malformed.append(view.ref)
            continue
        previous = by_condition_id.get(view.condition_id)
        if previous is None or (view.ref, view.kind) < (
            previous.ref,
            previous.kind,
        ):
            by_condition_id[view.condition_id] = view
    return (
        tuple(
            sorted(
                by_condition_id.values(),
                key=lambda item: (
                    item.valid_scope,
                    item.ref,
                    item.condition_id or "",
                ),
            )
        ),
        tuple(sorted(set(malformed))),
    )


def _select_semantic_duplicate(
    candidates: Sequence[FunctionalSemanticView],
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> FunctionalSemanticView | None:
    if not candidates:
        return None
    ancestors = semantic_index.handle_registry.ancestor_scopes(scope_id)

    def rank(item: FunctionalSemanticView) -> tuple[int, str, str]:
        try:
            scope_rank = ancestors.index(item.valid_scope)
        except ValueError:
            scope_rank = len(ancestors)
        return scope_rank, item.ref, item.condition_id or ""

    # Identical point/curve/kind relations are semantic duplicates. The
    # nearest visible declaration wins; folded source provenance remains on
    # its F5-B binding.
    return min(candidates, key=rank)


def _condition_role(
    condition: FunctionalSemanticView,
    role: str,
) -> str | None:
    values = dict(condition.object_roles).get(role, ())
    return values[0] if len(values) == 1 else None


def _exact_object_ref(
    value: ResolvedFunctionalValue,
    *,
    semantic_index: FunctionalSemanticIndex,
) -> str | None:
    if value.object_ref is not None:
        return value.object_ref
    object_id = _math_object_id(value)
    if object_id is None:
        return None
    refs = {
        view.object_ref
        for view in semantic_index.views
        if view.math_object_id == object_id and view.object_ref is not None
    }
    return next(iter(refs)) if len(refs) == 1 else None


def _math_object_id(
    value: ResolvedFunctionalValue,
) -> MathObjectId | None:
    if value.math_object_id is not None:
        return value.math_object_id
    if value.logical_state_key is not None:
        return value.logical_state_key.object_id
    return None


def _issue(
    code: str,
    message: str,
    *,
    method_spec: MethodSpec,
    relation: MethodInputRelationSpec,
    call_id: str,
    capability_id: str,
    scope_id: str,
    item_index: int,
    point_ref: str | None,
    curve_ref: str | None,
    point: ResolvedFunctionalValue,
    curve: ResolvedFunctionalValue,
    repair_action: str,
    retryability: str = "planner_repairable",
    observed: Mapping[str, Any] | None = None,
) -> MethodInputRelationIssue:
    observed_relation = dict(observed or {})
    relation_owner_scopes = tuple(
        str(item)
        for item in observed_relation.get("relation_owner_scopes", ())
        if isinstance(item, str)
    )
    owner_details: dict[str, Any] = {}
    if len(relation_owner_scopes) == 1:
        owner_details = {
            "relation_owner_scope": relation_owner_scopes[0],
            "expected_relation_owner_scope": relation_owner_scopes[0],
        }
    elif relation_owner_scopes:
        owner_details = {
            "relation_owner_scopes": list(relation_owner_scopes),
            "expected_relation_owner_scopes": list(relation_owner_scopes),
        }
    return MethodInputRelationIssue(
        code=code,
        message=message,
        details={
            "method_id": method_spec.method_id,
            "capability_id": capability_id,
            "call_id": call_id,
            "step_id": call_id,
            "scope_id": scope_id,
            "arg_name": relation.point_arg,
            "item_index": item_index,
            "relation_kind": relation.relation_kind,
            "accepted_condition_kinds": list(
                relation.accepted_condition_kinds
            ),
            "subjects": [
                {
                    "role": "curve_point",
                    "arg_name": relation.point_arg,
                    "item_index": item_index,
                    "internal_ref": point_ref,
                    "expected_type": "Point",
                    "expected_state": "related_by_visible_condition",
                    "observed_type": _observed_entity_type(point),
                },
                {
                    "role": "curve",
                    "arg_name": relation.curve_arg,
                    "item_index": item_index,
                    "internal_ref": curve_ref,
                    "expected_type": "QuadraticFunction",
                    "expected_state": "same_condition_object",
                    "observed_type": _observed_entity_type(curve),
                },
            ],
            "expected_relation": {
                "point_ref": point_ref,
                "curve_ref": curve_ref,
                "condition_kinds": list(
                    relation.accepted_condition_kinds
                ),
            },
            "observed_relation": observed_relation,
            **owner_details,
            "retryability": retryability,
            "repair_action": repair_action,
            "repair_call_ids": [call_id],
        },
    )


def _observed_entity_type(value: ResolvedFunctionalValue) -> str | None:
    """Keep prompt diagnostics on the MathObject view, not its state view."""

    if value.math_object_id is None:
        return value.runtime_type
    return {
        "function": "Function",
        "point": "Point",
        "symbol": "Symbol",
        "line": "Line",
        "segment": "Segment",
        "ray": "Ray",
        "polygon": "Polygon",
        "circle": "Circle",
        "angle": "Angle",
    }.get(value.math_object_id.kind, value.runtime_type)
