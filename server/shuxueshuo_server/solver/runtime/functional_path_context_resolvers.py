"""Context-closure resolvers for path transformation mechanisms."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.runtime.context_closure import (
    ContextClosureResolverSpec,
)
from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
    EqualLengthRayRoleError,
    resolve_equal_length_ray_path_roles,
)
from shuxueshuo_server.solver.runtime.functional_context_values import (
    condition_value_by_handle,
    latest_point_state_for_object,
    object_identity_value,
    resolved_value_object_refs,
    state_producer_locations_for_object,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCapability,
    FunctionalPlanIssue,
    ResolvedFunctionalValue,
    _issue,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.path_reduction_roles import (
    PathReductionRoleError,
    PathReductionRoleResolver,
)
from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_path_terms,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    merge_state_semantic_lineages,
)
from shuxueshuo_server.solver.utils import unique_ordered


ContextClosureResolution = tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    bool,
]


def _state_scope_diagnostic_details(
    object_ref: str,
    *,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
) -> dict[str, Any]:
    producers = state_producer_locations_for_object(
        object_ref,
        produced=produced,
    )
    return {
        "required_producer_scope": scope_id,
        "existing_producer_scopes": sorted(
            {producer_scope for _step_id, producer_scope in producers}
        ),
        "existing_producers": [
            {"step_id": step_id, "scope_ref": producer_scope}
            for step_id, producer_scope in producers
        ],
    }


@dataclass(frozen=True)
class SquarePathTransformationRoles:
    """Structured object roles shared by dependency and value resolution."""

    fixed_endpoint_1: str
    moving_object: str
    fixed_endpoint_2: str


class SquarePathTransformationRoleError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any],
    ) -> None:
        super().__init__(message)
        self.details = dict(details)


def infer_square_path_transformation_roles(
    conditions: Sequence[Any],
    *,
    moving_object_ref: str,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> SquarePathTransformationRoles | None:
    """Validate a planner-selected moving point and derive proof-only roles."""

    square = next(
        (
            value
            for value in conditions
            if handle_registry.fact_types.get(value.handle) == "square"
        ),
        None,
    )
    path_target = next(
        (
            value
            for value in conditions
            if handle_registry.fact_types.get(value.handle)
            == "path_minimum_target"
        ),
        None,
    )
    if square is None or path_target is None:
        return None

    midpoint = next(
        (
            value
            for value in conditions
            if handle_registry.fact_types.get(value.handle)
            == "midpoint_definition"
        ),
        None,
    )
    if midpoint is None:
        return None

    square_roles = dict(square.object_roles)
    ordered_vertices = tuple(
        square_roles.get(f"vertex_{index}", ())
        for index in range(1, 5)
    )
    if any(len(refs) != 1 for refs in ordered_vertices):
        raise SquarePathTransformationRoleError(
            "square path transformation requires ordered square vertices",
            details={
                "roles": ["moving_object", "fixed_endpoint_1"],
                "repair_action": "choose_square_path_moving_point",
            },
        )
    vertices = tuple(refs[0] for refs in ordered_vertices)
    midpoint_payload = handle_registry.fact_payloads.get(midpoint.handle, {})
    midpoint_side = tuple(str(item) for item in midpoint_payload.get("of", ()))
    fixed_1_refs = tuple(
        endpoint
        for endpoint in midpoint_side
        if _square_external_neighbor(
            endpoint,
            midpoint_side=midpoint_side,
            vertices=vertices,
        )
        == moving_object_ref
    )
    if len(fixed_1_refs) != 1:
        raise SquarePathTransformationRoleError(
            "selected moving point is incompatible with the square side used by the midpoint proof",
            details={
                "selected_moving_point": moving_object_ref,
                "failed_check": "square_midpoint_side_adjacency",
                "repair_action": "choose_square_path_moving_point",
            },
        )

    point_by_name = _visible_points_by_name(
        scope_id=scope_id,
        handle_registry=handle_registry,
    )
    terms = parse_path_terms(
        handle_registry.fact_payloads.get(path_target.handle, {}),
        point_names=point_by_name,
        resolve_point=lambda name: _resolve_unique_path_point(
            name,
            point_by_name,
        ),
    )
    moving_ref = moving_object_ref
    moving_terms = tuple(
        term
        for term in terms
        if moving_ref in (term.start, term.end)
    )
    if len(moving_terms) != 1:
        raise SquarePathTransformationRoleError(
            "square path must identify one segment incident to the moving object",
            details={
                "role": "fixed_endpoint_2",
                "moving_object": moving_ref,
            },
        )
    moving_term = moving_terms[0]
    fixed_2_ref = (
        moving_term.end
        if moving_term.start == moving_ref
        else moving_term.start
    )
    return SquarePathTransformationRoles(
        fixed_endpoint_1=fixed_1_refs[0],
        moving_object=moving_ref,
        fixed_endpoint_2=fixed_2_ref,
    )


def _square_external_neighbor(
    endpoint: str,
    *,
    midpoint_side: Sequence[str],
    vertices: Sequence[str],
) -> str | None:
    """Return the square neighbor not lying on the selected midpoint side."""

    if len(midpoint_side) != 2 or endpoint not in vertices:
        return None
    other_side_endpoint = next(
        (item for item in midpoint_side if item != endpoint),
        None,
    )
    if other_side_endpoint is None:
        return None
    index = vertices.index(endpoint)
    neighbors = (vertices[(index - 1) % 4], vertices[(index + 1) % 4])
    if other_side_endpoint not in neighbors:
        return None
    return next(item for item in neighbors if item != other_side_endpoint)


def resolve_equal_length_ray_path_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    allow_legacy_planned_producer_visibility: bool = False,
) -> ContextClosureResolution:
    """Bind every materialized geometry role used by the reduction recipe."""

    del call
    if (
        capability.kind != "macro"
        or capability.capability_id != "equal_length_ray_path_reduction"
    ):
        return {}, (), (), False
    conditions: dict[str, ResolvedFunctionalValue] = {}
    for condition_type in (
        "point_on_ray",
        "point_on_segment",
        "equal_length_condition",
        "path_minimum_target",
    ):
        matches = tuple(
            value
            for values in resolved_args.values()
            for value in values
            if handle_registry.fact_types.get(value.handle) == condition_type
        )
        if len(matches) != 1:
            return (
                {},
                (),
                (
                    _issue(
                        "functional_elaboration",
                        "functional.equal_length_ray_condition_unresolved",
                        (
                            "equal-length ray path reduction requires one "
                            f"{condition_type} condition"
                        ),
                        call_id=call_id,
                        scope_id=scope_id,
                        details={
                            "condition_type": condition_type,
                            "match_count": len(matches),
                        },
                    ),
                ),
                False,
            )
        conditions[condition_type] = matches[0]

    visible_points = tuple(
        handle
        for handle in handle_registry.entity_handles
        if handle.startswith("point:")
        and visible_from_valid_scope(
            handle_registry.handle_valid_scopes.get(handle, ""),
            scope_id=scope_id,
            registry=handle_registry,
        )
    )

    def resolve_point_name(name: str) -> str:
        matches = tuple(
            handle
            for handle in visible_points
            if handle_registry.entity_payloads.get(handle, {}).get("name")
            == name
        )
        if len(matches) != 1:
            raise EqualLengthRayRoleError(
                "point_name_unresolved",
                "structured role point name must resolve uniquely",
                details={"name": name, "candidates": matches},
            )
        return matches[0]

    try:
        roles = resolve_equal_length_ray_path_roles(
            ray_payload=handle_registry.fact_payloads[
                conditions["point_on_ray"].handle
            ],
            segment_payload=handle_registry.fact_payloads[
                conditions["point_on_segment"].handle
            ],
            equal_payload=handle_registry.fact_payloads[
                conditions["equal_length_condition"].handle
            ],
            target_payload=handle_registry.fact_payloads[
                conditions["path_minimum_target"].handle
            ],
            entity_payload=lambda handle: handle_registry.entity_payloads[
                handle
            ],
            visible_point_handles=visible_points,
            resolve_point_name=resolve_point_name,
        )
    except (EqualLengthRayRoleError, KeyError) as exc:
        code = (
            exc.code
            if isinstance(exc, EqualLengthRayRoleError)
            else "structured_role_payload_missing"
        )
        details = (
            exc.details
            if isinstance(exc, EqualLengthRayRoleError)
            else {"missing_handle": str(exc)}
        )
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.equal_length_ray.{code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=details,
                ),
            ),
            False,
        )

    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for semantic_role, object_ref in (
        ("anchor", roles.anchor),
        ("reference_point", roles.reference_point),
        ("ray_point", roles.ray_point),
        ("fixed_point", roles.fixed_point),
    ):
        arg_name = resolver.arg_name(
            semantic_role,
            capability.context_arg_bindings,
        )
        point = latest_point_state_for_object(
            object_ref,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            allow_unique_planned_producer=True,
            allow_invisible_planned_producer=(
                allow_legacy_planned_producer_visibility
            ),
        )
        if point is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.equal_length_ray_point_state_unavailable",
                    (
                        "equal-length ray path reduction requires the exact "
                        f"materialized Point state for role {semantic_role}"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "semantic_role": semantic_role,
                        "object_ref": object_ref,
                        **_state_scope_diagnostic_details(
                            object_ref,
                            scope_id=scope_id,
                            produced=produced,
                        ),
                    },
                )
            )
            continue
        additions[arg_name] = (point,)
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_equal_length_ray_path_roles",
                conditions["path_minimum_target"].handle,
                ",".join(
                    (
                        "anchor",
                        "reference_point",
                        "ray_point",
                        "fixed_point",
                    )
                ),
            ),
        ),
        (),
        True,
    )


def resolve_coupled_segment_endpoint_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> ContextClosureResolution:
    """Project one structured coupled-segment graph into Macro role hints."""

    del call
    if (
        capability.kind != "macro"
        or capability.capability_id
        != "coupled_segment_endpoint_replacement_path_minimum"
    ):
        return {}, (), (), False
    path_targets = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if handle_registry.fact_types.get(value.handle)
        == "path_minimum_target"
    )
    if len(path_targets) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.coupled_segment_path_target_unresolved",
                    "coupled-segment path minimum requires one path target",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"match_count": len(path_targets)},
                ),
            ),
            False,
        )
    try:
        roles = PathReductionRoleResolver.resolve(
            path_target=path_targets[0].handle,
            scope_id=scope_id,
            registry=handle_registry,
        )
    except PathReductionRoleError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.{exc.code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=exc.details,
                ),
            ),
            False,
        )

    supplied_conditions = {
        value.handle
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "Condition"
    }
    missing_conditions = tuple(
        handle
        for handle in roles.required_condition_handles
        if handle not in supplied_conditions
    )
    if missing_conditions:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.coupled_segment_condition_unavailable",
                    "Macro call omitted a structured coupled-path Fact",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "missing_condition_handles": list(missing_conditions),
                        "repair_action": "supply_coupled_segment_path_facts",
                    },
                ),
            ),
            False,
        )

    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    identity_roles = (
        ("first_moving_point", roles.first_moving_point),
        ("second_moving_point", roles.second_moving_point),
    )
    state_roles = (
        ("first_track_fixed_endpoint", roles.first_segment_start),
        ("joint_point", roles.joint_point),
        ("second_track_fixed_endpoint", roles.second_segment_end),
        ("fixed_path_endpoint", roles.transformed_fixed_endpoint),
    )
    for semantic_role, object_ref in identity_roles:
        arg_name = resolver.arg_name(
            semantic_role,
            capability.context_arg_bindings,
        )
        point = object_identity_value(
            object_ref,
            domain_runtime_types=("Point", "PointRef"),
            scope_id=scope_id,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        if point is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.coupled_segment_point_identity_unavailable",
                    f"coupled path role is not a visible Point: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"semantic_role": semantic_role, "object_ref": object_ref},
                )
            )
        else:
            additions[arg_name] = (point,)
    for semantic_role, object_ref in state_roles:
        arg_name = resolver.arg_name(
            semantic_role,
            capability.context_arg_bindings,
        )
        point = latest_point_state_for_object(
            object_ref,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            allow_unique_planned_producer=True,
        )
        if point is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.coupled_segment_point_state_unavailable",
                    f"coupled path role needs a materialized Point: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "semantic_role": semantic_role,
                        "object_ref": object_ref,
                        **_state_scope_diagnostic_details(
                            object_ref,
                            scope_id=scope_id,
                            produced=produced,
                        ),
                    },
                )
            )
        else:
            additions[arg_name] = (point,)
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_coupled_segment_endpoint_roles",
                roles.path_target,
                ",".join(
                    (
                        f"first_moving={roles.first_moving_point}",
                        f"second_moving={roles.second_moving_point}",
                        f"joint={roles.joint_point}",
                    )
                ),
            ),
        ),
        (),
        True,
    )


def resolve_square_path_transformation_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> ContextClosureResolution:
    del call
    conditions = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "Condition"
    )
    path_target = next(
        (
            value
            for value in conditions
            if handle_registry.fact_types.get(value.handle)
            == "path_minimum_target"
        ),
        None,
    )
    if path_target is None:
        return {}, (), (), False
    moving_refs = resolved_value_object_refs(
        resolved_args.get("moving_point", ())
    )
    if len(moving_refs) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_reduction_interpretation_invalid",
                    "square path reduction requires one planner-selected moving point",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": "moving_point",
                        "selected_moving_points": list(moving_refs),
                        "repair_action": "choose_square_path_moving_point",
                    },
                ),
            ),
            False,
        )
    try:
        roles = infer_square_path_transformation_roles(
            conditions,
            moving_object_ref=moving_refs[0],
            scope_id=scope_id,
            handle_registry=handle_registry,
        )
    except PathTermParseError as exc:
        return _path_term_issue(
            exc,
            call_id=call_id,
            scope_id=scope_id,
        )
    except SquarePathTransformationRoleError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_transformation_role_missing",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=exc.details,
                ),
            ),
            False,
        )
    if roles is None:
        return {}, (), (), False
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for role, object_ref in (
        ("fixed_endpoint_1", roles.fixed_endpoint_1),
        ("fixed_endpoint_2", roles.fixed_endpoint_2),
    ):
        arg_name = resolver.arg_name(
            role,
            capability.context_arg_bindings,
        )
        value = latest_point_state_for_object(
            object_ref,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
            allow_unique_planned_producer=True,
        )
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.path_transformation_state_unavailable",
                    (
                        "square path transformation requires a computed "
                        f"Point state: {object_ref}"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": role,
                        "object_ref": object_ref,
                        "state_requirement": (
                            "materialized Point state for the structured "
                            "transformation role"
                        ),
                        "repair_guidance": (
                            "Add or retain the producer for this structured "
                            "endpoint before building the transformation. Do "
                            "not replace it with an unrelated visible Point."
                        ),
                        **_state_scope_diagnostic_details(
                            object_ref,
                            scope_id=scope_id,
                            produced=produced,
                        ),
                    },
                )
            )
        else:
            additions[arg_name] = (value,)
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "project_square_path_transformation_roles",
                path_target.handle,
                (
                    f"moving={roles.moving_object},"
                    f"fixed_1={roles.fixed_endpoint_1},"
                    f"fixed_2={roles.fixed_endpoint_2}"
                ),
            ),
        ),
        (),
        True,
    )


def resolve_weighted_path_transformation_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> ContextClosureResolution:
    del call
    conditions = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "Condition"
        and handle_registry.fact_types.get(value.handle) == "minimum_value"
    )
    moving_refs = resolved_value_object_refs(
        resolved_args.get("moving_point", ())
    )
    fixed_refs = resolved_value_object_refs(
        resolved_args.get("fixed_point", ())
    )
    auxiliary_refs = resolved_value_object_refs(
        resolved_args.get("auxiliary_point_ref", ())
    )
    if len(conditions) != 1 or len(moving_refs) != 1 or len(fixed_refs) != 1:
        return {}, (), (), False
    point_by_name = _visible_points_by_name(
        scope_id=scope_id,
        handle_registry=handle_registry,
    )
    try:
        terms = parse_path_terms(
            handle_registry.fact_payloads.get(conditions[0].handle, {}),
            point_names=point_by_name,
            resolve_point=lambda name: _resolve_unique_path_point(
                name,
                point_by_name,
            ),
        )
    except PathTermParseError as exc:
        return _path_term_issue(
            exc,
            call_id=call_id,
            scope_id=scope_id,
        )
    moving_ref = moving_refs[0]
    fixed_ref = fixed_refs[0]
    outer_refs = unique_ordered(
        endpoint
        for term in terms
        if moving_ref in (term.start, term.end)
        for endpoint in (term.start, term.end)
        if endpoint not in {moving_ref, fixed_ref}
    )
    if len(outer_refs) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_transformation_role_missing",
                    (
                        "weighted path must identify one curve-side "
                        "fixed endpoint"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": "fixed_endpoint_1",
                        "candidates": list(outer_refs),
                    },
                ),
            ),
            False,
        )
    curve_ref = outer_refs[0]
    curve = latest_point_state_for_object(
        curve_ref,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
        allow_unique_planned_producer=True,
    )
    if curve is None:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_transformation_state_unavailable",
                    (
                        "weighted path transformation requires a computed "
                        f"curve Point state: {curve_ref}"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": "fixed_endpoint_1",
                        "object_ref": curve_ref,
                        "state_requirement": (
                            "materialized Point state for the structured "
                            "weighted-path role"
                        ),
                        "repair_guidance": (
                            "Add or retain the producer for the structurally "
                            "declared endpoint before building the weighted "
                            "path transformation."
                        ),
                        **_state_scope_diagnostic_details(
                            curve_ref,
                            scope_id=scope_id,
                            produced=produced,
                        ),
                    },
                ),
            ),
            False,
        )
    arg_name = resolver.arg_name(
        "linked_fixed_endpoint",
        capability.context_arg_bindings,
    )
    return (
        {arg_name: (curve,)},
        (
            FunctionalDeterministicRepair(
                call_id,
                "project_weighted_path_transformation_roles",
                conditions[0].handle,
                (
                    f"moving={moving_ref},fixed={curve_ref},"
                    "auxiliary=["
                    f"{','.join(auxiliary_refs)}"
                    "]"
                ),
            ),
        ),
        (),
        True,
    )


def _visible_points_by_name(
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for handle in handle_registry.entity_handles:
        if not handle.startswith("point:"):
            continue
        if not visible_from_valid_scope(
            handle_registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=scope_id,
            registry=handle_registry,
        ):
            continue
        result.setdefault(handle.rsplit(":", 1)[-1], []).append(handle)
    return result


def _resolve_unique_path_point(
    name: str,
    point_by_name: Mapping[str, list[str]],
) -> str:
    matches = point_by_name.get(name, ())
    if len(matches) != 1:
        raise PathTermParseError(
            "path_terms.point_unresolved",
            f"path point name is not unique in scope: {name}",
        )
    return matches[0]


def _path_term_issue(
    exc: PathTermParseError,
    *,
    call_id: str,
    scope_id: str,
) -> ContextClosureResolution:
    return (
        {},
        (),
        (
            _issue(
                "functional_elaboration",
                f"functional.{exc.code}",
                str(exc),
                call_id=call_id,
                scope_id=scope_id,
                details=exc.details,
            ),
        ),
        False,
    )


__all__ = [
    "ContextClosureResolution",
    "SquarePathTransformationRoleError",
    "SquarePathTransformationRoles",
    "infer_square_path_transformation_roles",
    "resolve_coupled_segment_endpoint_args",
    "resolve_equal_length_ray_path_args",
    "resolve_square_path_transformation_args",
    "resolve_weighted_path_transformation_args",
]
