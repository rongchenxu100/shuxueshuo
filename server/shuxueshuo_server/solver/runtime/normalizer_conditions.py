"""Condition-driven read closure rules for legacy StepIntent drafts."""

from __future__ import annotations

from dataclasses import replace

from shuxueshuo_server.solver.family.models import (
    CONDITION_OBJECT_ROLES_RESOLVER,
    PATH_REDUCTION_ROLES_RESOLVER,
)
from shuxueshuo_server.solver.runtime.condition_roles import (
    ConditionRoleResolutionError,
    ConditionRoleResolver,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRuleContext,
    NormalizationRuleResult,
)
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_output_type,
)
from shuxueshuo_server.solver.runtime.path_reduction_roles import (
    PathReductionRoleError,
    PathReductionRoleResolver,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StepIntentNormalizationAction,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.utils import unique_ordered


class _ConditionRoleReadClosureRule:
    """Complete mechanical reads declared by a structured Condition."""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        relation_handles = tuple(
            handle
            for handle in step.reads
            if ConditionRoleResolver.supports(
                context.handle_registry.fact_types.get(handle, "")
            )
        )
        if len(relation_handles) != 1:
            return NormalizationRuleResult(step)
        if not _capability_declares_context_resolver(
            step,
            context=context,
            resolver_id=CONDITION_OBJECT_ROLES_RESOLVER,
        ):
            return NormalizationRuleResult(step)
        relation = relation_handles[0]
        condition_kind = context.handle_registry.fact_types.get(relation, "")
        try:
            object_roles = ConditionRoleResolver.object_roles(
                condition_kind,
                context.handle_registry.fact_payloads.get(relation, {}),
            )
            endpoints = dict(object_roles).get("endpoint", ())
            materialized = tuple(
                endpoint
                for endpoint in endpoints
                if _coordinate_fact_for_object(
                    endpoint,
                    step=step,
                    context=context,
                )
                is not None
                or _entity_has_coordinate(endpoint, context=context)
            )
            target_hints = unique_ordered(
                (
                    *_structured_target_hints(step, context=context),
                    *(
                        endpoint
                        for endpoint in endpoints
                        if endpoint in step.reads
                        and endpoint not in materialized
                    ),
                )
            )
            roles = ConditionRoleResolver.resolve_constructed_point_roles(
                object_roles,
                target_hints=target_hints,
                materialized_points=materialized,
            )
        except ConditionRoleResolutionError as exc:
            raise StrategyDraftValidationError(
                f"{exc.code}: {exc}"
            ) from exc

        additions = [roles.anchor, roles.reference, roles.target]
        orientation = _visible_subject_condition(
            "orientation_constraint",
            roles.target,
            step=step,
            context=context,
        )
        if orientation is not None:
            additions.append(orientation)
        symbols = tuple(
            handle for handle in step.reads if handle.startswith("symbol:")
        )
        if len(symbols) == 1:
            constraint = _visible_subject_condition(
                "symbol_constraint",
                symbols[0],
                step=step,
                context=context,
            )
            if constraint is not None:
                additions.append(constraint)
        new_reads = tuple(unique_ordered((*step.reads, *additions)))
        added = tuple(handle for handle in new_reads if handle not in step.reads)
        if not added:
            return NormalizationRuleResult(step)
        return NormalizationRuleResult(
            replace(step, reads=new_reads),
            actions=tuple(
                StepIntentNormalizationAction(
                    action="complete_condition_role_read",
                    step_id=step.step_id,
                    handle=handle,
                    reason=(
                        "structured Condition role closure added a mechanical "
                        "runtime dependency"
                    ),
                )
                for handle in added
            ),
        )


class _PathReductionReadClosureRule:
    """Complete the hidden graph inputs for a PathTransformation producer."""

    def apply(
        self,
        step: StepIntent,
        context: NormalizationRuleContext,
    ) -> NormalizationRuleResult:
        if not any(
            produced_output_type(item, context.handle_registry)
            == "PathTransformation"
            for item in step.produces
        ):
            return NormalizationRuleResult(step)
        if not _capability_declares_context_resolver(
            step,
            context=context,
            resolver_id=PATH_REDUCTION_ROLES_RESOLVER,
        ):
            return NormalizationRuleResult(step)
        targets = tuple(
            handle
            for handle in step.reads
            if context.handle_registry.fact_types.get(handle)
            == "path_minimum_target"
        )
        if len(targets) != 1:
            return NormalizationRuleResult(step)
        try:
            roles = PathReductionRoleResolver.resolve(
                path_target=targets[0],
                scope_id=step.scope_id,
                registry=context.handle_registry,
            )
        except PathReductionRoleError as exc:
            raise StrategyDraftValidationError(
                f"{exc.code}: {exc}"
            ) from exc
        additions = (
            *roles.required_condition_handles,
            *roles.required_point_handles,
        )
        new_reads = tuple(unique_ordered((*step.reads, *additions)))
        added = tuple(handle for handle in new_reads if handle not in step.reads)
        if not added:
            return NormalizationRuleResult(step)
        return NormalizationRuleResult(
            replace(step, reads=new_reads),
            actions=tuple(
                StepIntentNormalizationAction(
                    action="complete_path_reduction_read",
                    step_id=step.step_id,
                    handle=handle,
                    reason=(
                        "structured path-reduction role closure added a "
                        "mechanical runtime dependency"
                    ),
                )
                for handle in added
            ),
        )


def _capability_declares_context_resolver(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
    resolver_id: str,
) -> bool:
    if step.recipe_hint is None:
        return False
    return resolver_id in context.context_resolvers_by_capability.get(
        step.recipe_hint,
        (),
    )


def _coordinate_fact_for_object(
    object_ref: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    return next(
        (
            handle
            for handle in step.reads
            if (
                context.handle_registry.fact_types.get(handle)
                == "point_coordinate"
                and context.handle_registry.fact_payloads.get(handle, {}).get(
                    "subject"
                )
                == object_ref
            )
            or any(
                object_ref in previous.reads
                and any(
                    produced.handle == handle
                    and produced_output_type(
                        produced,
                        context.handle_registry,
                    )
                    == "Point"
                    for produced in previous.produces
                )
                for previous in context.previous_steps
            )
        ),
        None,
    )


def _entity_has_coordinate(
    object_ref: str,
    *,
    context: NormalizationRuleContext,
) -> bool:
    payload = context.handle_registry.entity_payloads.get(object_ref, {})
    coordinate = payload.get("coordinate")
    return isinstance(coordinate, (list, tuple)) and len(coordinate) == 2


def _structured_target_hints(
    step: StepIntent,
    *,
    context: NormalizationRuleContext,
) -> tuple[str, ...]:
    hints = [step.target, *(item.handle for item in step.creates)]
    for handle in step.reads:
        if (
            context.handle_registry.fact_types.get(handle)
            != "orientation_constraint"
        ):
            continue
        subject = context.handle_registry.fact_payloads.get(handle, {}).get(
            "subject"
        )
        if isinstance(subject, str):
            hints.append(subject)
    for item in step.produces:
        subject = context.handle_registry.fact_payloads.get(
            item.handle,
            {},
        ).get("subject")
        if isinstance(subject, str):
            hints.append(subject)
    return tuple(unique_ordered(hints))


def _visible_subject_condition(
    fact_type: str,
    subject: str,
    *,
    step: StepIntent,
    context: NormalizationRuleContext,
) -> str | None:
    matches = tuple(
        handle
        for handle, current_type in context.handle_registry.fact_types.items()
        if current_type == fact_type
        and context.handle_registry.fact_payloads.get(handle, {}).get("subject")
        == subject
        and visible_from_valid_scope(
            context.handle_registry.handle_valid_scopes.get(handle, "problem"),
            scope_id=step.scope_id,
            registry=context.handle_registry,
        )
    )
    return matches[0] if len(matches) == 1 else None
