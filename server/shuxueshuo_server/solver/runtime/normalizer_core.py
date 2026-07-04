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
    _register_published_outputs,
)
from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRule,
    NormalizationRuleContext,
    _recipe_output_types,
)
from shuxueshuo_server.solver.runtime.normalizer_path import (
    _BrokenPathMinimumEndpointProducesRule,
    _MidpointCoordinateBackfillRule,
    _SquarePathLocusBackfillRule,
    _StraightenedDistanceEndpointReadsRule,
    _WeightedAuxiliaryLocusTypeRule,
    _drop_square_pre_reduction_point_utility_steps_for_scope,
    _drop_unreferenced_path_transformation_steps_for_scope,
    _fold_broken_path_internal_sequence_for_scope,
    _normalize_square_final_recovery_for_scope,
)
from shuxueshuo_server.solver.runtime.normalizer_quadratic import (
    _AxisPointAliasRule,
    _AxisPointMethodAliasRule,
    _CandidatePointFactsRule,
    _DropParameterizedParabolaUtilityRule,
    _DropUnavailableQuadraticCoefficientReadsRule,
    _EvaluateParameterizedOutputAliasRule,
    _KnownPointCoordinateUtilityRule,
    _MinimumAnswerParameterReadRule,
    _MixedQuadraticOutputSplitRule,
    _PointAnswerCoordinateRule,
    _QuadraticFromConstraintsRule,
    _fold_curve_candidate_parameter_internal_sequence_for_scope,
    _normalize_angle_sum_axis_intercept_targets_for_scope,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntentDraft,
    StepIntent,
    StepIntentNormalizationAction,
    StepIntentNormalizationReport,
    StepIntentScope,
)

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
        actions: list[StepIntentNormalizationAction] = []
        warnings: list[str] = []
        normalized_scopes: list[StepIntentScope] = []
        context = NormalizationRuleContext(
            handle_registry=handle_registry,
            question_goal_map=question_goal_map,
            recipe_output_types=recipe_output_types,
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

        return (
            StepIntentDraft(scopes=tuple(normalized_scopes)),
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
        "square.drop_pre_reduction_point_utility_steps",
        _drop_square_pre_reduction_point_utility_steps_for_scope,
    ),
    _scope_transform(
        "square.normalize_final_recovery",
        _normalize_square_final_recovery_for_scope,
    ),
)


# Rule order is part of the normalizer contract. Keep the broad data-shape and
# alias rewrites early, then run domain folds/backfills, then run publication and
# de-dup rules late. In particular:
# - _RewriteStepReadsRule must run first so later rules see canonical reads.
# - _DropUnavailableQuadraticCoefficientReadsRule must run before
#   _QuadraticFromConstraintsRule, otherwise quadratic binding may preserve
#   coefficients that are not visible in the current scope.
# - Endpoint/locus/midpoint backfills must run before publication/alias merge
#   rules so inserted helper outputs are registered for later steps.
DEFAULT_NORMALIZATION_RULES: tuple[NormalizationRule, ...] = (
    _RewriteStepReadsRule(),
    _DropUnavailableQuadraticCoefficientReadsRule(),
    _AxisPointMethodAliasRule(),
    _QuadraticFromConstraintsRule(),
    _MixedQuadraticOutputSplitRule(),
    _CandidatePointFactsRule(),
    _WeightedAuxiliaryLocusTypeRule(),
    _BrokenPathMinimumEndpointProducesRule(),
    _SquarePathLocusBackfillRule(),
    _StraightenedDistanceEndpointReadsRule(),
    _PointAnswerCoordinateRule(),
    _AxisPointAliasRule(),
    _CommonScopeOutputPromotionRule(),
    _FactHandleValidScopeRule(),
    _EvaluateParameterizedOutputAliasRule(),
    _DropParameterizedParabolaUtilityRule(),
    _MidpointCoordinateBackfillRule(),
    _MinimumAnswerParameterReadRule(),
    _PublicOutputAliasMergeRule(),
    _KnownPointCoordinateUtilityRule(),
    _MergeRedundantParameterAnswerRule(),
)
