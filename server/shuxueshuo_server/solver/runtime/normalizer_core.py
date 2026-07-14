"""Core StepIntent normalizer orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.question_goals import QuestionGoal
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.normalizer_binding import (
    _CommonScopeOutputPromotionRule,
    _FactHandleValidScopeRule,
    _MergeRedundantParameterAnswerRule,
    _PublicOutputAliasMergeRule,
    _RewriteStepReadsRule,
    _SiblingCommonOutputReadPromotionRule,
    _register_published_outputs,
)
from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRule,
    NormalizationRuleContext,
    _recipe_output_types,
    _recipe_required_creates,
)
from shuxueshuo_server.solver.runtime.normalizer_path import (
    _BrokenPathMinimumEndpointProducesRule,
    _MidpointDefinitionReadCompletionRule,
    _MidpointCoordinateBackfillRule,
    _PathTransformationBackfillRule,
    _RecipeRequiredCreatesRule,
    _SquarePathLocusBackfillRule,
    _StraightenedDistanceEndpointReadsRule,
    _WeightedAuxiliaryLocusTypeRule,
    _drop_square_pre_reduction_point_utility_steps_for_scope,
    _drop_unreferenced_path_transformation_steps_for_scope,
    _fold_internal_equation_utility_steps_for_scope,
    _fold_broken_path_internal_sequence_for_scope,
    _normalize_square_final_recovery_for_scope,
)
from shuxueshuo_server.solver.runtime.normalizer_quadratic import (
    _AnswerPointAliasRule,
    _AxisPointAliasRule,
    _AxisPointMethodAliasRule,
    _CandidatePointFactsRule,
    _DropParameterizedParabolaUtilityRule,
    _DropUnavailableQuadraticCoefficientReadsRule,
    _EvaluateParameterizedOutputAliasRule,
    _KnownPointCoordinateUtilityRule,
    _KnownSymbolValueReadCompletionRule,
    _MinimumAnswerParameterReadRule,
    _MixedQuadraticOutputSplitRule,
    _MultiPointEvaluationSplitRule,
    _ParameterSolverOutputAliasRule,
    _PointAnswerCoordinateRule,
    _QuadraticFromConstraintsRule,
    _fold_curve_candidate_parameter_internal_sequence_for_scope,
    _normalize_angle_sum_axis_intercept_targets_for_scope,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntentDraft,
    StepIntent,
    ProducedFact,
    StepIntentNormalizationAction,
    StepIntentNormalizationReport,
    StepIntentScope,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import _produced_output_type

ScopeTransformFn = Callable[
    [tuple[StepIntent, ...], CanonicalHandleRegistry],
    tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]],
]


class ScopeNormalizationTransform(Protocol):
    """Scope-level transform interface used before per-step rules."""

    name: str

    def apply(
        self,
        steps: tuple[StepIntent, ...],
        *,
        handle_registry: CanonicalHandleRegistry,
    ) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
        """Return transformed steps and emitted normalization actions."""
        ...


@dataclass(frozen=True)
class FunctionScopeTransform:
    """Adapter for existing scope-level normalizer functions."""

    name: str
    transform: ScopeTransformFn

    def apply(
        self,
        steps: tuple[StepIntent, ...],
        *,
        handle_registry: CanonicalHandleRegistry,
    ) -> tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]]:
        """Apply the wrapped transform."""
        return self.transform(steps, handle_registry)


@dataclass(frozen=True)
class NormalizationRuleOrderConstraint:
    """Declared ordering dependency between normalization rules."""

    before: str
    after: str
    reason: str


class StepIntentNormalizer:
    """对 StepIntentDraft 做安全、可解释的结构整理。"""

    def __init__(
        self,
        rules: tuple[NormalizationRule, ...] | None = None,
        scope_transforms: tuple[ScopeNormalizationTransform, ...] | None = None,
    ) -> None:
        self.rules = DEFAULT_NORMALIZATION_RULES if rules is None else rules
        self.scope_transforms = (
            DEFAULT_SCOPE_TRANSFORMS
            if scope_transforms is None
            else scope_transforms
        )
        _validate_normalization_rule_order(self.rules)

    def normalize(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
        handle_registry: CanonicalHandleRegistry,
    ) -> tuple[StepIntentDraft, StepIntentNormalizationReport]:
        """返回整理后的 draft 与报告。"""
        question_goal_map = {f"answer:{goal.id}": goal for goal in question_goals}
        recipe_output_types = _recipe_output_types(family_spec)
        recipe_required_creates = _recipe_required_creates(family_spec)
        actions: list[StepIntentNormalizationAction] = []
        warnings: list[str] = []
        normalized_scopes: list[StepIntentScope] = []
        context = NormalizationRuleContext(
            handle_registry=handle_registry,
            question_goal_map=question_goal_map,
            recipe_output_types=recipe_output_types,
            recipe_required_creates=recipe_required_creates,
            normalized_scopes=normalized_scopes,
        )

        for scope in draft.scopes:
            context.previous_steps = []
            context.current_scope_index = len(normalized_scopes)
            scope_steps = scope.steps
            for transform in self.scope_transforms:
                scope_steps, scope_actions = transform.apply(
                    scope_steps,
                    handle_registry=handle_registry,
                )
                actions.extend(scope_actions)

            for step in scope_steps:
                append_step = True
                for rule in self.rules:
                    result = rule.apply(step, context)
                    step = result.step
                    context.handle_rewrites.update(result.rewrites)
                    actions.extend(result.actions)
                    if not result.append_step:
                        append_step = False
                        break
                if append_step:
                    context.previous_steps.append(step)
                    _register_published_outputs(
                        context,
                        step,
                        step_index=len(context.previous_steps) - 1,
                    )
            normalized_scopes.append(replace(scope, steps=tuple(context.previous_steps)))

        normalized_draft = _apply_final_handle_rewrites(
            StepIntentDraft(scopes=tuple(normalized_scopes)),
            context.handle_rewrites,
        )
        normalized_draft, dedupe_actions = _dedupe_duplicate_produced_handles(
            normalized_draft,
            handle_registry=handle_registry,
        )
        actions.extend(dedupe_actions)

        return (
            normalized_draft,
            StepIntentNormalizationReport(actions=tuple(actions), warnings=tuple(warnings)),
        )


def _scope_transform(
    name: str,
    transform: Callable[
        ...,
        tuple[tuple[StepIntent, ...], list[StepIntentNormalizationAction]],
    ],
) -> FunctionScopeTransform:
    """Adapt existing ``steps, *, handle_registry`` functions to pipeline items."""
    return FunctionScopeTransform(
        name=name,
        transform=lambda steps, handle_registry: transform(
            steps,
            handle_registry=handle_registry,
        ),
    )


def _apply_final_handle_rewrites(
    draft: StepIntentDraft,
    rewrites: dict[str, str],
) -> StepIntentDraft:
    """Apply transitive handle rewrites after rule-specific semantics finish."""
    if not rewrites:
        return draft
    scopes: list[StepIntentScope] = []
    for scope in draft.scopes:
        steps = tuple(
            replace(
                step,
                reads=tuple(_resolve_final_handle(handle, rewrites) for handle in step.reads),
                target=_resolve_final_handle(step.target, rewrites),
            )
            for step in scope.steps
        )
        scopes.append(replace(scope, steps=steps))
    return StepIntentDraft(scopes=tuple(scopes))


def _resolve_final_handle(handle: str, rewrites: dict[str, str]) -> str:
    """Resolve rewrite chains conservatively at the final draft boundary."""
    current = handle
    seen: set[str] = set()
    while current in rewrites and current not in seen:
        seen.add(current)
        current = rewrites[current]
    return current


DEFAULT_SCOPE_TRANSFORMS: tuple[ScopeNormalizationTransform, ...] = (
    _scope_transform(
        "quadratic.angle_sum_axis_intercept_targets",
        _normalize_angle_sum_axis_intercept_targets_for_scope,
    ),
    _scope_transform(
        "path.drop_unreferenced_path_transformation_steps",
        _drop_unreferenced_path_transformation_steps_for_scope,
    ),
    _scope_transform(
        "path.fold_broken_path_internal_sequence",
        _fold_broken_path_internal_sequence_for_scope,
    ),
    _scope_transform(
        "quadratic.fold_curve_candidate_parameter_internal_sequence",
        _fold_curve_candidate_parameter_internal_sequence_for_scope,
    ),
    _scope_transform(
        "path.fold_internal_equation_utility_steps",
        _fold_internal_equation_utility_steps_for_scope,
    ),
    _scope_transform(
        "square.drop_pre_reduction_point_utility_steps",
        _drop_square_pre_reduction_point_utility_steps_for_scope,
    ),
    _scope_transform(
        "square.normalize_final_recovery",
        _normalize_square_final_recovery_for_scope,
    ),
)


NORMALIZATION_RULE_ORDER_CONSTRAINTS: tuple[NormalizationRuleOrderConstraint, ...] = (
    NormalizationRuleOrderConstraint(
        before="_RewriteStepReadsRule",
        after="_SiblingCommonOutputReadPromotionRule",
        reason="later rules must see canonical reads produced by previous rewrites",
    ),
    NormalizationRuleOrderConstraint(
        before="_DropUnavailableQuadraticCoefficientReadsRule",
        after="_QuadraticFromConstraintsRule",
        reason=(
            "quadratic normalization must not preserve coefficient reads that "
            "are unavailable in the current scope"
        ),
    ),
    NormalizationRuleOrderConstraint(
        before="_PathTransformationBackfillRule",
        after="_PublicOutputAliasMergeRule",
        reason="path prerequisite outputs must be inserted before publication/alias merge",
    ),
    NormalizationRuleOrderConstraint(
        before="_SquarePathLocusBackfillRule",
        after="_PublicOutputAliasMergeRule",
        reason="locus helper outputs must be inserted before publication/alias merge",
    ),
    NormalizationRuleOrderConstraint(
        before="_MidpointCoordinateBackfillRule",
        after="_PublicOutputAliasMergeRule",
        reason="midpoint helper outputs must be inserted before publication/alias merge",
    ),
)


# Rule order is part of the normalizer contract. Keep broad data-shape and alias
# rewrites early, domain folds/backfills in the middle, publication and de-dup
# rules late. Add new critical ordering dependencies to
# NORMALIZATION_RULE_ORDER_CONSTRAINTS so they are checked at construction time.
DEFAULT_NORMALIZATION_RULES: tuple[NormalizationRule, ...] = (
    _RewriteStepReadsRule(),
    _SiblingCommonOutputReadPromotionRule(),
    _DropUnavailableQuadraticCoefficientReadsRule(),
    _AxisPointMethodAliasRule(),
    _QuadraticFromConstraintsRule(),
    _MixedQuadraticOutputSplitRule(),
    _ParameterSolverOutputAliasRule(),
    _MultiPointEvaluationSplitRule(),
    _CandidatePointFactsRule(),
    _WeightedAuxiliaryLocusTypeRule(),
    _BrokenPathMinimumEndpointProducesRule(),
    _PathTransformationBackfillRule(),
    _SquarePathLocusBackfillRule(),
    _StraightenedDistanceEndpointReadsRule(),
    _PointAnswerCoordinateRule(),
    _AxisPointAliasRule(),
    _AnswerPointAliasRule(),
    _CommonScopeOutputPromotionRule(),
    _RecipeRequiredCreatesRule(),
    _FactHandleValidScopeRule(),
    _EvaluateParameterizedOutputAliasRule(),
    _DropParameterizedParabolaUtilityRule(),
    _MidpointDefinitionReadCompletionRule(),
    _MidpointCoordinateBackfillRule(),
    _KnownSymbolValueReadCompletionRule(),
    _MinimumAnswerParameterReadRule(),
    _PublicOutputAliasMergeRule(),
    _KnownPointCoordinateUtilityRule(),
    _MergeRedundantParameterAnswerRule(),
)


def _validate_normalization_rule_order(rules: tuple[NormalizationRule, ...]) -> None:
    """Validate declared order dependencies for a rule tuple."""
    positions: dict[str, int] = {}
    for index, rule in enumerate(rules):
        positions.setdefault(rule.__class__.__name__, index)
    for constraint in NORMALIZATION_RULE_ORDER_CONSTRAINTS:
        before = positions.get(constraint.before)
        after = positions.get(constraint.after)
        if before is None or after is None:
            continue
        if before > after:
            raise ValueError(
                "normalization rule order violation: "
                f"{constraint.before} must run before {constraint.after}; "
                f"{constraint.reason}"
            )


def _dedupe_duplicate_produced_handles(
    draft: StepIntentDraft,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[StepIntentDraft, list[StepIntentNormalizationAction]]:
    """Remove duplicate producers created by deterministic alias/promotion rewrites.

    Per-step rules may safely promote sibling-local handles to a shared parent
    scope. Once all scopes are normalized, two previously distinct handles can
    become the same canonical produced handle or the same public state
    signature. Keep the first producer as the authoritative state and remove
    later duplicate output declarations before the runtime compiler sees them.
    """
    producer_by_handle: dict[str, str] = {}
    producer_by_signature: dict[str, tuple[str, str]] = {}
    handle_rewrites: dict[str, str] = {}
    duplicate_producer_by_handle: dict[str, str] = {}
    actions: list[StepIntentNormalizationAction] = []
    normalized_scopes: list[StepIntentScope] = []

    for scope in draft.scopes:
        steps: list[StepIntent] = []
        for step in scope.steps:
            rewritten_reads = tuple(handle_rewrites.get(handle, handle) for handle in step.reads)
            target = handle_rewrites.get(step.target, step.target)
            if rewritten_reads != step.reads or target != step.target:
                for old_handle, new_handle in handle_rewrites.items():
                    if old_handle in step.reads or old_handle == step.target:
                        actions.append(
                            StepIntentNormalizationAction(
                                action="rewrite_duplicate_produced_state_read",
                                step_id=step.step_id,
                                target_step_id=producer_by_handle.get(new_handle),
                                handle=old_handle,
                                reason=(
                                    f"{old_handle} 是已存在公共状态 {new_handle} 的重复 "
                                    "produced handle；后续 step 改为读取保留的 canonical handle。"
                                ),
                            )
                        )
                step = replace(step, reads=rewritten_reads, target=target)

            duplicate_handles: list[str] = []
            retained_produces = []
            for item in step.produces:
                existing_step_id = producer_by_handle.get(item.handle)
                if existing_step_id is None:
                    signature = _dedupe_state_signature(item, handle_registry)
                    existing_signature_producer = (
                        producer_by_signature.get(signature)
                        if signature is not None
                        else None
                    )
                    if existing_signature_producer is None:
                        retained_produces.append(item)
                        continue
                    existing_step_id, existing_handle = existing_signature_producer
                    handle_rewrites[item.handle] = existing_handle
                    duplicate_producer_by_handle[item.handle] = existing_step_id
                    duplicate_handles.append(item.handle)
                    actions.append(
                        StepIntentNormalizationAction(
                            action="drop_duplicate_produced_state",
                            step_id=step.step_id,
                            target_step_id=existing_step_id,
                            handle=item.handle,
                            reason=(
                                f"{item.handle} 与前序 step {existing_step_id} 的 "
                                f"{existing_handle} 表示同一公共状态；保留前序 producer，"
                                "后续 step 读取已有状态。"
                            ),
                        )
                    )
                    continue
                handle_rewrites[item.handle] = item.handle
                duplicate_handles.append(item.handle)
                actions.append(
                    StepIntentNormalizationAction(
                        action="drop_duplicate_produced_handle",
                        step_id=step.step_id,
                        target_step_id=existing_step_id,
                        handle=item.handle,
                        reason=(
                            f"{item.handle} 已由前序 step {existing_step_id} 产生；"
                            "normalization 后的重复 produced handle 会导致 runtime "
                            "重复注册，保留前序 producer，后续 step 只复用该 handle。"
                        ),
                    )
                )

            if duplicate_handles and not retained_produces and not step.creates:
                actions.append(
                    StepIntentNormalizationAction(
                        action="drop_duplicate_producer_step",
                        step_id=step.step_id,
                        target_step_id=(
                            producer_by_handle.get(duplicate_handles[0])
                            or duplicate_producer_by_handle[duplicate_handles[0]]
                        ),
                        handle=",".join(duplicate_handles),
                        reason=(
                            "该 step 在 normalization 后只重复产生已存在 handle；"
                            "删除整个 step，后续 reads 继续指向保留的 canonical handle。"
                        ),
                    )
                )
                continue

            if duplicate_handles:
                if target in duplicate_handles:
                    if retained_produces:
                        target = retained_produces[0].handle
                    elif step.creates:
                        target = step.creates[0].handle
                    else:
                        target = handle_rewrites.get(target, target)
                step = replace(
                    step,
                    target=target,
                    produces=tuple(retained_produces),
                )

            steps.append(step)
            for item in step.produces:
                producer_by_handle.setdefault(item.handle, step.step_id)
                signature = _dedupe_state_signature(item, handle_registry)
                if signature is not None:
                    producer_by_signature.setdefault(signature, (step.step_id, item.handle))
        normalized_scopes.append(replace(scope, steps=tuple(steps)))

    if not actions:
        return draft, []
    return StepIntentDraft(scopes=tuple(normalized_scopes)), actions


def _dedupe_state_signature(
    item: ProducedFact,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """Return public-state signatures safe to merge at normalization time."""
    if not item.handle.startswith("fact:"):
        return None
    output_type = _produced_output_type(item, handle_registry)
    if output_type == "PathTransformation":
        return f"path_transformation:{item.valid_scope}"
    return None
