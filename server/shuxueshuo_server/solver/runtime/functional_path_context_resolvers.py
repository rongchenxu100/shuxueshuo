"""Context-closure resolvers for path transformation mechanisms."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.runtime.context_closure import (
    ContextClosureResolverSpec,
)
from shuxueshuo_server.solver.runtime.coupled_segment_path_roles import (
    CoupledSegmentPathRoleError,
    build_coupled_segment_path_role_candidates,
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
from shuxueshuo_server.solver.runtime.quadratic_square_path_roles import (
    QuadraticSquarePathRoleError,
    build_quadratic_square_path_role_candidates,
)
from shuxueshuo_server.solver.runtime.weighted_axis_path_roles import (
    WeightedAxisPathRoleError,
    build_weighted_axis_path_role_candidates,
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


def resolve_coupled_segment_path_args(
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
    """Resolve the private proof closure for the coupled-segment Macro."""

    del call
    if (
        capability.kind != "macro"
        or capability.capability_id
        != "coupled_segment_endpoint_replacement_path_minimum"
    ):
        return {}, (), (), False
    path_values = tuple(
        value
        for value in resolved_args.get("path_minimum_target", ())
        if handle_registry.fact_types.get(value.handle) == "path_minimum_target"
    )
    relation_values = tuple(
        value
        for value in resolved_args.get("segment_binding_relation", ())
        if handle_registry.fact_types.get(value.handle)
        in {"segment_relation", "segment_length_relation"}
    )
    counts = {
        "path_minimum_target": len(path_values),
        "segment_binding_relation": len(relation_values),
    }
    if any(count != 1 for count in counts.values()):
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.macro_search_public_input_invalid",
                    "coupled path minimum requires one path target and one segment relation",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": capability.capability_id,
                        "expected_candidate_counts": {name: 1 for name in counts},
                        "observed_candidate_counts": counts,
                        "repair_action": "repair_macro_public_inputs",
                        "retryability": "planner_repairable",
                    },
                ),
            ),
            False,
        )
    try:
        candidates = build_coupled_segment_path_role_candidates(
            path_minimum_target=path_values[0].handle,
            segment_binding_relation=relation_values[0].handle,
            scope_id=scope_id,
            registry=handle_registry,
        )
    except CoupledSegmentPathRoleError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.macro_search_no_structural_candidate",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": capability.capability_id,
                        "repair_action": "select_compatible_path_and_segment_relation",
                        "retryability": "planner_repairable",
                        **exc.details,
                    },
                ),
            ),
            False,
        )
    if len(candidates) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    (
                        "functional.macro_search_no_structural_candidate"
                        if not candidates
                        else "functional.macro_search_ambiguous"
                    ),
                    "the public Facts do not determine one coupled path mechanism",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": capability.capability_id,
                        "candidate_count": len(candidates),
                        "candidate_ids": [item.candidate_id for item in candidates],
                        "phase": "structural_elaboration",
                        "repair_action": "select_compatible_path_and_segment_relation",
                        "retryability": "planner_repairable",
                    },
                ),
            ),
            False,
        )
    roles = candidates[0]
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for role, handle in (
        ("first_membership", roles.first_membership),
        ("second_membership", roles.second_membership),
    ):
        arg_name = resolver.arg_name(role, capability.context_arg_bindings)
        condition = condition_value_by_handle(
            handle,
            semantic_index=semantic_index,
            scope_id=scope_id,
        )
        if condition is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.coupled_segment_path_condition_unavailable",
                    f"connected proof condition is unavailable: {handle}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"arg": arg_name, "condition_handle": handle},
                )
            )
        else:
            additions[arg_name] = (condition,)
    for role, object_ref in (
        ("first_segment_start", roles.first_segment_start),
        ("joint_point", roles.joint_point),
        ("second_segment_end", roles.second_segment_end),
        ("transformed_fixed_endpoint", roles.transformed_fixed_endpoint),
    ):
        arg_name = resolver.arg_name(role, capability.context_arg_bindings)
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
                    "functional.coupled_segment_path_state_unavailable",
                    f"coupled path minimum requires Point state: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "object_ref": object_ref,
                        "repair_action": (
                            "materialize_constructed_point_before_macro"
                            if role == "transformed_fixed_endpoint"
                            else "provide_visible_state_producer"
                        ),
                        **_state_scope_diagnostic_details(
                            object_ref,
                            scope_id=scope_id,
                            produced=produced,
                            required_scope_ref=(
                                handle_registry.handle_valid_scopes.get(object_ref)
                                or scope_id
                            ),
                        ),
                    },
                )
            )
        else:
            additions[arg_name] = (point,)
    moving_arg = resolver.arg_name("moving_point", capability.context_arg_bindings)
    moving_identity = object_identity_value(
        roles.moving_point,
        domain_runtime_types=("Point", "PointRef"),
        scope_id=scope_id,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    if moving_identity is None:
        issues.append(
            _issue(
                "functional_elaboration",
                "functional.coupled_segment_path_identity_unavailable",
                "coupled path minimum requires the reduced moving Point identity",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": moving_arg,
                    "object_ref": roles.moving_point,
                    "repair_action": "select_compatible_path_and_segment_relation",
                },
            )
        )
    else:
        additions[moving_arg] = (moving_identity,)
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_coupled_segment_path_roles",
                roles.path_minimum_target,
                ",".join(
                    (
                        f"first_moving={roles.first_moving_point}",
                        f"moving={roles.moving_point}",
                        f"joint={roles.joint_point}",
                    )
                ),
            ),
        ),
        (),
        True,
    )


def _state_scope_diagnostic_details(
    object_ref: str,
    *,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    required_scope_ref: str | None = None,
) -> dict[str, Any]:
    producers = state_producer_locations_for_object(
        object_ref,
        produced=produced,
    )
    producer_scope = required_scope_ref or scope_id
    return {
        "required_producer_scope": producer_scope,
        "required_scope_ref": producer_scope,
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


def resolve_path_reduction_args(
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
    if capability.kind != "macro" or not any(
        item.runtime_type == "PathTransformation"
        for item in capability.returns
    ):
        return {}, (), (), False
    path_targets = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if handle_registry.fact_types.get(value.handle)
        == "path_minimum_target"
    )
    if not path_targets:
        return {}, (), (), False
    if len(path_targets) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_reduction_target_ambiguous",
                    "path reduction requires one path-minimum target",
                    call_id=call_id,
                    scope_id=scope_id,
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
    selected_moving_refs = resolved_value_object_refs(
        resolved_args.get("moving_point", ())
    )
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    selected_moving = object_identity_value(
        roles.second_moving_point,
        domain_runtime_types=("Point", "PointRef"),
        scope_id=scope_id,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    if selected_moving is None:
        issues.append(
            _issue(
                "functional_elaboration",
                "functional.path_reduction_point_state_unavailable",
                "path reduction requires the selected moving Point identity",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "arg": "moving_point",
                    "object_ref": roles.second_moving_point,
                    "state_requirement": "visible Point identity",
                    "repair_action": "choose_visible_moving_point",
                },
            )
        )
    else:
        # The wire value is an authored search hint.  Static lineage and the
        # executable Macro graph must use the candidate selected by the
        # declared role builder; runtime checks authenticate it before commit.
        additions["moving_point"] = (selected_moving,)
    for semantic_role, handle in (
        ("first_membership", roles.first_membership),
        ("second_membership", roles.second_membership),
        ("binding_relation", roles.binding_relation),
    ):
        arg_name = resolver.arg_name(
            semantic_role,
            capability.context_arg_bindings,
        )
        condition = condition_value_by_handle(
            handle,
            semantic_index=semantic_index,
            scope_id=scope_id,
        )
        if condition is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.path_reduction_condition_unavailable",
                    f"path reduction condition is unavailable: {handle}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"arg": arg_name, "condition_handle": handle},
                )
            )
        else:
            if semantic_role == "second_membership":
                moving_role = StateObjectRoleBinding(
                    role="moving_object",
                    object_refs=(roles.second_moving_point,),
                    source_state_slot_ids=condition.source_state_slot_ids,
                    source_handles=(condition.handle,),
                )
                locus_role = StateObjectRoleBinding(
                    role="moving_locus",
                    object_refs=(roles.second_track,),
                    source_state_slot_ids=condition.source_state_slot_ids,
                    source_handles=(condition.handle,),
                )
                condition = replace(
                    condition,
                    object_roles=tuple(
                        dict(condition.object_roles).items()
                    )
                    + (("moving_object", (roles.second_moving_point,)),),
                    lineage=merge_state_semantic_lineages(
                        condition.lineage,
                        object_roles=(moving_role, locus_role),
                    ),
                )
            additions[arg_name] = (condition,)
    for semantic_role, object_ref in (
        ("first_segment_start", roles.first_segment_start),
        ("joint_point", roles.joint_point),
        ("second_segment_end", roles.second_segment_end),
        (
            "transformed_fixed_endpoint",
            roles.transformed_fixed_endpoint,
        ),
        ("moving_locus_endpoint_1", roles.joint_point),
        ("moving_locus_endpoint_2", roles.second_segment_end),
    ):
        arg_name = resolver.arg_name_or_none(
            semantic_role,
            capability.context_arg_bindings,
        )
        if arg_name is None:
            continue
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
                    "functional.path_reduction_point_state_unavailable",
                    (
                        "path reduction requires a computed Point state: "
                        f"{object_ref}"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "arg": arg_name,
                        "object_ref": object_ref,
                        "state_requirement": (
                            "materialized Point state for the structured "
                            "path role"
                        ),
                        "repair_guidance": (
                            "Add or retain the producer for this structured "
                            "endpoint before the path transformation. Do not "
                            "substitute another visible Point by name or type."
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
            additions[arg_name] = (point,)
    if issues:
        return additions, (), tuple(issues), False
    role_repair = FunctionalDeterministicRepair(
        call_id,
        (
            "accept_macro_role_hint"
            if selected_moving_refs == (roles.second_moving_point,)
            else "correct_macro_role_hint"
        ),
        (
            selected_moving_refs[0]
            if len(selected_moving_refs) == 1
            else "<unspecified>"
        ),
        roles.second_moving_point,
    )
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_path_reduction_roles",
                roles.path_target,
                ",".join(
                    (
                        f"first_moving={roles.first_moving_point}",
                        f"second_moving={roles.second_moving_point}",
                        f"joint={roles.joint_point}",
                    )
                ),
            ),
            role_repair,
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


def resolve_quadratic_square_path_args(
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
    """Resolve the minimal connected proof closure for the atomic Macro."""

    del call
    if (
        capability.kind != "macro"
        or capability.capability_id != "quadratic_square_path_minimum"
    ):
        return {}, (), (), False
    path_values = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if handle_registry.fact_types.get(value.handle) == "path_minimum_target"
    )
    square_values = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if handle_registry.fact_types.get(value.handle) == "square"
    )
    parabola_refs = resolved_value_object_refs(
        resolved_args.get("parabola", ())
    )
    public_input_counts = {
        "path_minimum_target": len(path_values),
        "square": len(square_values),
        "parabola": len(parabola_refs),
    }
    if any(count != 1 for count in public_input_counts.values()):
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.macro_search_public_input_invalid",
                    (
                        "quadratic_square_path_minimum requires exactly one "
                        "resolved parabola, path target and square"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": "quadratic_square_path_minimum",
                        "expected_candidate_counts": {
                            name: 1 for name in public_input_counts
                        },
                        "observed_candidate_counts": public_input_counts,
                        "repair_action": "repair_macro_public_inputs",
                        "retryability": "planner_repairable",
                    },
                ),
            ),
            False,
        )
    try:
        candidates = build_quadratic_square_path_role_candidates(
            path_minimum_target=path_values[0].handle,
            square=square_values[0].handle,
            parabola_ref=parabola_refs[0],
            scope_id=scope_id,
            registry=handle_registry,
        )
    except QuadraticSquarePathRoleError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.quadratic_square_path.{exc.code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=exc.details,
                ),
            ),
            False,
        )
    if len(candidates) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    (
                        "functional.macro_search_no_structural_candidate"
                        if not candidates
                        else "functional.macro_search_ambiguous"
                    ),
                    (
                        "the selected quadratic state, path and square do not "
                        "determine one midpoint/center path-minimum mechanism"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "candidate_count": len(candidates),
                        "candidate_ids": [item.candidate_id for item in candidates],
                        "macro_id": "quadratic_square_path_minimum",
                        "phase": "structural_elaboration",
                        "retryability": "planner_repairable",
                        "repair_action": (
                            "select_a_compatible_quadratic_path_and_square_or_"
                            "choose_another_capability"
                        ),
                    },
                ),
            ),
            False,
        )
    roles = candidates[0]
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for role, handle in (
        ("midpoint_definition", roles.midpoint_definition),
        ("square_center", roles.square_center),
        ("axis_membership", roles.axis_membership),
    ):
        value = condition_value_by_handle(
            handle,
            semantic_index=semantic_index,
            scope_id=scope_id,
        )
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.quadratic_square_path_condition_unavailable",
                    f"connected proof condition is unavailable: {handle}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"role": role, "handle": handle},
                )
            )
        else:
            additions[resolver.arg_name(role, capability.context_arg_bindings)] = (
                value,
            )
    side_start = latest_point_state_for_object(
        roles.side_start,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
        allow_unique_planned_producer=True,
    )
    if side_start is None:
        issues.append(
            _issue(
                "functional_elaboration",
                "functional.quadratic_square_path_state_unavailable",
                "the square side start requires one materialized Point state",
                call_id=call_id,
                scope_id=scope_id,
                details={"role": "side_start", "object_ref": roles.side_start},
            )
        )
    else:
        additions[
            resolver.arg_name("side_start", capability.context_arg_bindings)
        ] = (side_start,)
    for role, object_ref in (
        ("axis_point", roles.axis_point),
        ("moving_point", roles.moving_point),
        ("fixed_endpoint", roles.fixed_endpoint),
    ):
        value = object_identity_value(
            object_ref,
            domain_runtime_types=("Point", "PointRef"),
            scope_id=scope_id,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.quadratic_square_path_identity_unavailable",
                    f"the path role has no unique Point identity: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"role": role, "object_ref": object_ref},
                )
            )
        else:
            additions[resolver.arg_name(role, capability.context_arg_bindings)] = (
                value,
            )
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "resolve_quadratic_square_path_proof_closure",
                path_values[0].handle,
                roles.candidate_id,
            ),
        ),
        (),
        True,
    )


def resolve_weighted_axis_path_minimum_args(
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
    """Resolve every code-owned role of the atomic weighted-path Macro."""

    del call
    if (
        capability.kind != "macro"
        or capability.capability_id != "weighted_axis_path_minimum"
    ):
        return {}, (), (), False
    path_values = tuple(
        value
        for value in resolved_args.get("path_minimum_target", ())
        if handle_registry.fact_types.get(value.handle) == "path_minimum_target"
    )
    if len(path_values) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.macro_search_public_input_invalid",
                    "weighted_axis_path_minimum requires exactly one path target",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": capability.capability_id,
                        "expected_candidate_counts": {"path_minimum_target": 1},
                        "observed_candidate_counts": {
                            "path_minimum_target": len(path_values)
                        },
                        "repair_action": "repair_macro_public_inputs",
                        "retryability": "planner_repairable",
                    },
                ),
            ),
            False,
        )
    try:
        candidates = build_weighted_axis_path_role_candidates(
            path_minimum_target=path_values[0].handle,
            scope_id=scope_id,
            registry=handle_registry,
        )
    except WeightedAxisPathRoleError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.weighted_axis_path.{exc.code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": capability.capability_id,
                        "repair_action": "select_compatible_weighted_path_target",
                        "retryability": "planner_repairable",
                        **exc.details,
                    },
                ),
            ),
            False,
        )
    if len(candidates) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    (
                        "functional.macro_search_no_structural_candidate"
                        if not candidates
                        else "functional.macro_search_ambiguous"
                    ),
                    "the path target does not determine one weighted-axis mechanism",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "macro_id": capability.capability_id,
                        "candidate_count": len(candidates),
                        "candidate_ids": [item.candidate_id for item in candidates],
                        "phase": "structural_elaboration",
                        "repair_action": "select_compatible_weighted_path_target",
                        "retryability": "planner_repairable",
                    },
                ),
            ),
            False,
        )
    roles = candidates[0]
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for role, object_ref in (
        ("fixed_point", roles.fixed_point),
        ("curve_point", roles.curve_point),
        ("moving_point", roles.moving_point),
    ):
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
                    "functional.weighted_axis_path.state_unavailable",
                    f"weighted path minimum requires Point state: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": role,
                        "object_ref": object_ref,
                        "repair_action": "materialize_weighted_path_endpoint_before_macro",
                        **_state_scope_diagnostic_details(
                            object_ref,
                            scope_id=scope_id,
                            produced=produced,
                            required_scope_ref=(
                                handle_registry.handle_valid_scopes.get(object_ref)
                                or scope_id
                            ),
                        ),
                    },
                )
            )
        else:
            additions[
                resolver.arg_name(role, capability.context_arg_bindings)
            ] = (value,)
    for role, object_ref in (
        ("parameter", roles.parameter),
        ("dynamic_parameter", roles.dynamic_parameter),
    ):
        value = object_identity_value(
            object_ref,
            domain_runtime_types=("Symbol",),
            scope_id=scope_id,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.weighted_axis_path.identity_unavailable",
                    f"weighted path role has no unique Symbol identity: {object_ref}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"role": role, "object_ref": object_ref},
                )
            )
        else:
            additions[
                resolver.arg_name(role, capability.context_arg_bindings)
            ] = (value,)
    for role, handle in (
        ("parameter_constraint", roles.parameter_constraint),
        ("dynamic_constraint", roles.dynamic_constraint),
    ):
        value = condition_value_by_handle(
            handle,
            semantic_index=semantic_index,
            scope_id=scope_id,
        )
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.weighted_axis_path.condition_unavailable",
                    f"weighted path domain condition is unavailable: {handle}",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"role": role, "condition_handle": handle},
                )
            )
        else:
            additions[
                resolver.arg_name(role, capability.context_arg_bindings)
            ] = (value,)
    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "resolve_weighted_axis_path_roles",
                roles.path_minimum_target,
                roles.candidate_id,
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
    "resolve_equal_length_ray_path_args",
    "resolve_path_reduction_args",
    "resolve_square_path_transformation_args",
    "resolve_weighted_axis_path_minimum_args",
    "resolve_weighted_path_transformation_args",
]
