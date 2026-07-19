"""Liveness analysis for planner-visible state writes."""

from __future__ import annotations

from dataclasses import dataclass

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StepIntentDraft,
    StepIntentNormalizationAction,
)


@dataclass(frozen=True)
class StateDependencyGraph:
    """Producer/read graph used for conservative dead pure-step elimination."""

    producer_by_handle: dict[str, str]
    dependencies_by_step: dict[str, tuple[str, ...]]

    @classmethod
    def from_draft(
        cls,
        draft: StepIntentDraft,
        *,
        implicit_dependencies_by_step: dict[str, tuple[str, ...]] | None = None,
    ) -> "StateDependencyGraph":
        producer_by_handle = {
            produced.handle: step.step_id
            for step in draft.steps
            for produced in step.produces
        }
        implicit_dependencies_by_step = implicit_dependencies_by_step or {}
        dependencies_by_step = {}
        for step in draft.steps:
            dependencies = [
                producer_by_handle[handle]
                for handle in step.reads
                if handle in producer_by_handle
            ]
            dependencies.extend(
                implicit_dependencies_by_step.get(step.step_id, ())
            )
            dependencies_by_step[step.step_id] = tuple(dict.fromkeys(dependencies))
        return cls(producer_by_handle, dependencies_by_step)

    def reachable_steps(self, roots: set[str]) -> set[str]:
        reachable = set(roots)
        pending = list(roots)
        while pending:
            step_id = pending.pop()
            for dependency in self.dependencies_by_step.get(step_id, ()):
                if dependency in reachable:
                    continue
                reachable.add(dependency)
                pending.append(dependency)
        return reachable


def drop_dead_pure_function_steps(
    draft: StepIntentDraft,
    *,
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
    implicit_dependencies_by_step: dict[str, tuple[str, ...]] | None = None,
    semantic_root_handles: tuple[str, ...] = (),
) -> tuple[StepIntentDraft, tuple[StepIntentNormalizationAction, ...]]:
    """Drop only unreachable, side-effect-free direct FunctionSpec steps."""
    functions = FunctionSpecRegistry.from_family_spec(family_spec, method_specs)
    recipe_ids = {recipe.recipe_id for recipe in family_spec.step_recipes}
    candidates = {
        step.step_id
        for step in draft.steps
        if _is_dead_step_candidate(step, functions, recipe_ids)
    }
    if not candidates:
        return draft, ()
    roots = {step.step_id for step in draft.steps if step.step_id not in candidates}
    roots.update(
        step.step_id
        for step in draft.steps
        if any(item.handle.startswith("answer:") for item in step.produces)
    )
    # A scope's terminal state is externally observable to callers even when a
    # partial/unit-test draft has no answer handle yet.
    roots.update(scope.steps[-1].step_id for scope in draft.scopes if scope.steps)
    producer_by_handle = {
        produced.handle: step.step_id
        for step in draft.steps
        for produced in step.produces
    }
    roots.update(
        producer_by_handle[handle]
        for handle in semantic_root_handles
        if handle in producer_by_handle
    )
    # Without any externally observable or non-pure root, liveness is unknown;
    # keep the draft instead of deleting the whole plan speculatively.
    if not roots:
        return draft, ()
    reachable = StateDependencyGraph.from_draft(
        draft,
        implicit_dependencies_by_step=implicit_dependencies_by_step,
    ).reachable_steps(roots)
    dead = candidates - reachable
    if not dead:
        return draft, ()
    actions = tuple(
        StepIntentNormalizationAction(
            action="drop_dead_pure_function_step",
            step_id=step.step_id,
            target_step_id=None,
            handle=(step.produces[0].handle if step.produces else None),
            reason=(
                "该纯 FunctionSpec step 的全部状态写入均未被后续 binding、"
                "condition 或 answer goal 消费。"
            ),
        )
        for step in draft.steps
        if step.step_id in dead
    )
    return (
        StepIntentDraft(
            scopes=tuple(
                type(scope)(
                    scope_id=scope.scope_id,
                    label=scope.label,
                    steps=tuple(step for step in scope.steps if step.step_id not in dead),
                )
                for scope in draft.scopes
            )
        ),
        actions,
    )


def _is_dead_step_candidate(
    step: StepIntent,
    functions: FunctionSpecRegistry,
    recipe_ids: set[str],
) -> bool:
    if not step.recipe_hint or step.recipe_hint in recipe_ids:
        return False
    function = functions.get(step.recipe_hint)
    if function is None or not function.is_pure:
        return False
    if step.creates or not step.produces:
        return False
    if any(item.handle.startswith("answer:") for item in step.produces):
        return False
    if any(item.runtime_type == "Condition" for item in function.returns):
        return False
    return True


__all__ = ["StateDependencyGraph", "drop_dead_pure_function_steps"]
