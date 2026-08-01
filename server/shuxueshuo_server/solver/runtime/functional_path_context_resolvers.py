"""Context-closure resolvers for path transformation mechanisms."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

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
    resolved_value_object_refs,
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
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
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
        return {}, (), (), False
    square_roles = dict(square.object_roles)
    # These are normalized ProblemIR roles for this transformation profile:
    # vertex_1 is the fixed anchor and vertex_4 is the moving square vertex.
    # Diagram orientation and point labels must be normalized upstream.
    fixed_1_refs = square_roles.get("vertex_1", ())
    moving_refs = square_roles.get("vertex_4", ())
    if len(fixed_1_refs) != 1 or len(moving_refs) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_transformation_role_missing",
                    (
                        "square path transformation requires ordered "
                        "square vertices"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "roles": ["fixed_endpoint_1", "moving_object"],
                    },
                ),
            ),
            False,
        )
    point_by_name = _visible_points_by_name(
        scope_id=scope_id,
        handle_registry=handle_registry,
    )
    try:
        terms = parse_path_terms(
            handle_registry.fact_payloads.get(path_target.handle, {}),
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
    moving_terms = tuple(
        term
        for term in terms
        if moving_ref in (term.start, term.end)
    )
    if len(moving_terms) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.path_transformation_role_missing",
                    (
                        "square path must identify one segment incident "
                        "to the moving object"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": "fixed_endpoint_2",
                        "moving_object": moving_ref,
                    },
                ),
            ),
            False,
        )
    moving_term = moving_terms[0]
    fixed_2_ref = (
        moving_term.end
        if moving_term.start == moving_ref
        else moving_term.start
    )
    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    for role, object_ref in (
        ("fixed_endpoint_1", fixed_1_refs[0]),
        ("fixed_endpoint_2", fixed_2_ref),
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
                    f"moving={moving_ref},fixed_1={fixed_1_refs[0]},"
                    f"fixed_2={fixed_2_ref}"
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
    "resolve_equal_length_ray_path_args",
    "resolve_path_reduction_args",
    "resolve_square_path_transformation_args",
    "resolve_weighted_path_transformation_args",
]
