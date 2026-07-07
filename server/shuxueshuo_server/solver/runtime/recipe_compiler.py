"""StepIntent recipe/method 编译器。

本模块把已校验的 StepIntentDraft 编译成 PlannerOutput，并通过 prefix dry-run
选择可执行的 recipe/method 候选。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from typing import Any, Callable, Mapping

from shuxueshuo_server.solver.family.models import (
    MethodCompanionOutputSpec,
    MethodPrepInvocationSpec,
    RecipeExecutionSpec as FamilyRecipeExecutionSpec,
    SolverFamilySpec,
)
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.auxiliary_points import fresh_auxiliary_point_handle
from shuxueshuo_server.solver.runtime.context import ContextBuilder, RuntimeContext
from shuxueshuo_server.solver.runtime._planner_helpers import single_invocation_step
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import (
    ContextPath,
    MethodInvocation,
    PlannerOutput,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_name,
    _handle_scope,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    StepIntent,
    StepIntentAcceptedStep,
    StepIntentDraft,
    StepIntentExecutionBlocker,
    StepIntentExecutionDiagnostic,
    StepIntentPlannerInsight,
    StepIntentResolutionStepReport,
    StepIntentScope,
    StepIntentSkippedStep,
    StrategyDraftValidationError,
    answer_output_type_compatible,
)
from shuxueshuo_server.solver.runtime.straightening_metadata import (
    STRAIGHTENING_ENDPOINT_POINT_1,
    STRAIGHTENING_ENDPOINT_POINT_2,
    collect_straightening_endpoint_handles,
    is_straightening_endpoint_name,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer
from shuxueshuo_server.solver.runtime.strategy_preflight import StepIntentPreflightAnalyzer
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    StepIntentCandidateResolver,
    _produced_output_type,
    _unique_ordered,
)
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    RuntimeHandleBinding,
    _binding_scope,
    _context_path_exists,
    _point_declaration_for_path,
    _runtime_path_for_scope,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    MethodBindingRuleRegistry,
    _answer_scope_from_step,
    _created_point_handle,
    _curve_candidate_target_handle,
    _moving_membership_for_straightening,
    _parameter_value_handle,
    _path_for_first_type,
    _path_for_readable_type,
    _path_for_readable_type_or_none,
    _point_output_handle,
    _length_endpoint_handles,
    _other_endpoint_handle,
    _payload_handle,
    _right_angle_roles,
    _segment_endpoints_from_entity_payload,
    _straightening_point_roles,
    _weighted_auxiliary_point_handle_for_step,
)

RecipeCompileStrategyFn = Callable[
    ["_RecipePlanCompiler", StepIntent, FamilyRecipeExecutionSpec],
    "_CompiledStep",
]


@dataclass(frozen=True)
class _CompiledStep:
    """RecipeTrialExecutor 编译单个 StepIntent 的临时结果。"""

    plan: StepPlan
    declarations: tuple[Any, ...] = ()
    registrations: tuple[RuntimeHandleBinding, ...] = ()


@dataclass(frozen=True)
class _PrepInvocationBuildResult:
    """单 method 编译前自动补位产生的 invocation 与局部输出。"""

    invocations: tuple[MethodInvocation, ...] = ()
    promote: dict[str, str] | None = None
    local_outputs: dict[str, str] | None = None


class PrepInvocationBuilder:
    """根据 FamilySpec 中的 prep rule 构建前置 invocation。

    Builder 只负责可确定的 runtime 补位，例如“求顶点前当前 scope 还没有可读
    Parabola，就先用二次函数约束生成一个临时 Parabola”。它不负责发明数学步骤，
    也不读取 LLM strategy/reason 中的数值。
    """

    def __init__(
        self,
        *,
        binding_rules: MethodBindingRuleRegistry,
        index: CanonicalRuntimeBindingIndex,
    ) -> None:
        self.binding_rules = binding_rules
        self.index = index

    def build(self, method_id: str, step: StepIntent) -> _PrepInvocationBuildResult:
        """为 method 构建所有命中的 prep invocation。"""
        rule = self.binding_rules.rule_for(method_id)
        if rule is None or not rule.prep_invocations:
            return _PrepInvocationBuildResult(promote={}, local_outputs={})

        invocations: list[MethodInvocation] = []
        promote: dict[str, str] = {}
        local_outputs: dict[str, str] = {}
        for prep in rule.prep_invocations:
            if not _prep_trigger_matches(prep, step, self.index):
                continue
            outputs = _prep_outputs(step, prep, self.index)
            invocations.append(
                MethodInvocation(
                    invocation_id=f"{step.step_id}.prepare_{prep.method_id}",
                    method_id=prep.method_id,
                    scope=step.step_id,
                    inputs=self.binding_rules.bind(
                        prep.method_id,
                        step,
                        self.index,
                        include_expansion_selectors=prep.include_expansion_selectors,
                        expansion_selectors_override=prep.expansion_selectors,
                    ),
                    outputs=outputs,
                )
            )
            for output_name, scoped_key in prep.output_aliases:
                output_path = outputs.get(output_name)
                if output_path is None:
                    continue
                if scoped_key == "__local_only__":
                    continue
                promote[output_path] = _scoped_output_path(
                    self.index.context,
                    step.scope_id,
                    scoped_key,
                )
            for local_key, output_name in prep.local_output_aliases:
                output_path = outputs.get(output_name)
                if output_path is not None:
                    local_outputs[local_key] = output_path
        return _PrepInvocationBuildResult(
            invocations=tuple(invocations),
            promote=promote,
            local_outputs=local_outputs,
        )


class RecipeExecutionSpecRegistry:
    """RecipeExecutionSpec 注册表。"""

    def __init__(self, specs: tuple[FamilyRecipeExecutionSpec, ...]) -> None:
        self.specs = {spec.recipe_id: spec for spec in specs}

    @classmethod
    def from_family_spec(cls, family_spec: SolverFamilySpec) -> "RecipeExecutionSpecRegistry":
        """从 FamilySpec.step_recipes 构建执行规格。

        若某个 recipe 还没有显式 execution 配置，且只包含单个 method，则自动退化为
        ``single_method``。多 method recipe 必须显式声明 execution，避免 runtime 再
        偷偷维护一份题型专属默认表。
        """
        specs: list[FamilyRecipeExecutionSpec] = []
        for recipe in family_spec.step_recipes:
            if recipe.execution is not None:
                specs.append(recipe.execution)
                continue
            if len(recipe.method_ids) == 1:
                specs.append(
                    FamilyRecipeExecutionSpec(
                        recipe_id=recipe.recipe_id,
                        method_sequence=recipe.method_ids,
                        execution_strategy="single_method",
                    )
                )
                continue
            raise StrategyDraftValidationError(
                f"recipe_execution_spec_missing: {recipe.recipe_id}"
            )
        return cls(tuple(specs))

    def get(self, recipe_id: str) -> FamilyRecipeExecutionSpec | None:
        """按 recipe_id 读取执行规格。"""
        return self.specs.get(recipe_id)

class RecipeTrialExecutor:
    """把 StepIntentDraft 编译成可执行 PlannerOutput。

    它按 StepIntent 选择 recipe/method capability，再通过 binding index 与 binding
    rules 生成真正的 MethodInvocation。每接受一个候选都会对当前 prefix plan 做
    dry-run，确保输出能被 runtime method 验算通过。
    """

    def __init__(
        self,
        *,
        recipe_specs: RecipeExecutionSpecRegistry | None = None,
        binding_rules: MethodBindingRuleRegistry | None = None,
        recipe_compilers: Mapping[str, RecipeCompileStrategyFn] | None = None,
    ) -> None:
        self.recipe_specs = recipe_specs
        self.binding_rules = binding_rules
        self.recipe_compilers = dict(recipe_compilers or DEFAULT_RECIPE_COMPILERS)

    def compile(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
        context: RuntimeContext,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
    ) -> PlannerOutput:
        """根据 StepIntent 生成 PlannerOutput。"""
        output, diagnostic, _effective_draft = self.diagnose(
            draft,
            family_spec=family_spec,
            method_specs=method_specs,
            handle_registry=handle_registry,
            context=context,
            question_goals=question_goals,
        )
        if output is not None:
            return output
        blocker = diagnostic.first_blocker
        if blocker is not None:
            raise StrategyDraftValidationError(
                f"recipe_trial_step_failed: step={blocker.step_id}, "
                f"errors={list(blocker.capability_errors)}"
            )
        raise StrategyDraftValidationError(
            "recipe_trial_candidate_resolution_failed: "
            + json.dumps(diagnostic.candidate_errors, ensure_ascii=False)
        )

    def diagnose(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
        context: RuntimeContext,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
    ) -> tuple[PlannerOutput | None, StepIntentExecutionDiagnostic, StepIntentDraft]:
        """编译 StepIntent，并返回 effective draft 的执行诊断。"""
        draft, _normalization_report = StepIntentNormalizer().normalize(
            draft,
            family_spec=family_spec,
            question_goals=question_goals,
            handle_registry=handle_registry,
        )
        resolution_report = StepIntentCandidateResolver().resolve(
            draft,
            family_spec=family_spec,
            method_specs=method_specs,
            handle_registry=handle_registry,
        )
        preflight_issues = StepIntentPreflightAnalyzer().analyze(
            draft,
            family_spec=family_spec,
            handle_registry=handle_registry,
        )
        index = CanonicalRuntimeBindingIndex.from_context(
            context,
            handle_registry=handle_registry,
            question_goals=question_goals,
        )
        recipe_specs = self.recipe_specs or RecipeExecutionSpecRegistry.from_family_spec(family_spec)
        binding_rules = self.binding_rules or MethodBindingRuleRegistry.from_family_spec(family_spec)
        compiler = _RecipePlanCompiler(
            context=context,
            index=index,
            resolution_report=resolution_report,
            method_specs=method_specs,
            recipe_specs=recipe_specs,
            binding_rules=binding_rules,
            recipe_compilers=self.recipe_compilers,
        )
        output, diagnostic, effective_draft = compiler.diagnose(draft)
        diagnostic = replace(
            diagnostic,
            preflight_issues=preflight_issues,
            function_binding_events=tuple(binding_rules.function_binding_events),
        )
        return output, diagnostic, effective_draft

class _RecipePlanCompiler:
    """StepIntent -> StepPlan 的通用编译器。"""

    def __init__(
        self,
        *,
        context: RuntimeContext,
        index: CanonicalRuntimeBindingIndex,
        resolution_report: ExecutablePlanResolutionReport,
        method_specs: MethodSpecRegistry,
        recipe_specs: RecipeExecutionSpecRegistry,
        binding_rules: MethodBindingRuleRegistry,
        recipe_compilers: Mapping[str, RecipeCompileStrategyFn],
    ) -> None:
        self.context = context
        self.index = index
        self.resolution_report = resolution_report
        self.method_specs = method_specs
        self.recipe_specs = recipe_specs
        self.binding_rules = binding_rules
        self.recipe_compilers = dict(recipe_compilers)
        self.step_reports = {
            report.step_id: report for report in resolution_report.step_reports
        }
        self.allowed_capability_ids = {
            capability.capability_id
            for capability in resolution_report.capability_catalog
        }

    def compile(self, draft: StepIntentDraft) -> PlannerOutput:
        """按 LLM 输出顺序编译并 dry-run prefix。"""
        output, diagnostic, _effective_draft = self.diagnose(draft)
        if output is not None:
            return output
        blocker = diagnostic.first_blocker
        if blocker is not None:
            raise StrategyDraftValidationError(
                f"recipe_trial_step_failed: step={blocker.step_id}, "
                f"errors={list(blocker.capability_errors)}"
            )
        raise StrategyDraftValidationError(
            "recipe_trial_candidate_resolution_failed: "
            + json.dumps(diagnostic.candidate_errors, ensure_ascii=False)
        )

    def diagnose(
        self,
        draft: StepIntentDraft,
    ) -> tuple[PlannerOutput | None, StepIntentExecutionDiagnostic, StepIntentDraft]:
        """按顺序编译并记录 accepted prefix 与首个 runtime blocker。"""
        plans: list[StepPlan] = []
        declarations: list[Any] = []
        seen_plan_keys: set[str] = set()
        accepted: list[StepIntentAcceptedStep] = []
        planner_insights: list[StepIntentPlannerInsight] = []
        steps = list(draft.steps)
        index = 0
        while index < len(steps):
            step = steps[index]
            candidate_errors: list[str] = []
            capability_ids = self._capability_ids_for_step(step)
            if not capability_ids:
                report = self.step_reports.get(step.step_id)
                candidate_errors = list(report.errors) if report is not None else [
                    "no_executable_candidate"
                ]
                candidate_errors.extend(_candidate_warnings_for_report(report))
                blocker = StepIntentExecutionBlocker(
                    step_id=step.step_id,
                    scope_id=step.scope_id,
                    stage="candidate_resolution",
                    code=_execution_blocker_code(candidate_errors),
                    message=_execution_blocker_message(step.step_id, candidate_errors),
                    capability_errors=tuple(candidate_errors),
                    capability_id=_execution_blocker_capability_id(candidate_errors),
                    missing_runtime_type=_execution_blocker_missing_runtime_type(candidate_errors),
                )
                skipped = tuple(
                    StepIntentSkippedStep(
                        step_id=later.step_id,
                        scope_id=later.scope_id,
                        reason=f"skipped_due_to_prefix_blocker:{step.step_id}",
                    )
                    for later in steps[index + 1:]
                )
                return (
                    None,
                    StepIntentExecutionDiagnostic(
                        ok=False,
                        accepted_prefix=tuple(accepted),
                        applied_fills=tuple(self.index.applied_fills),
                        planner_insights=tuple(planner_insights),
                        preflight_issues=(),
                        blockers=(blocker,),
                        skipped_steps=skipped,
                        candidate_errors=tuple(candidate_errors),
                    ),
                    _draft_with_steps(draft, steps),
                )
            accepted_current_step = False
            for capability_id in capability_ids:
                try:
                    compiled = self._compile_with_capability(step, capability_id)
                    key = f"{compiled.plan.step_id}:{compiled.plan.goal.target_path}"
                    if key in seen_plan_keys:
                        continue
                    trial_declarations = _unique_declarations([*declarations, *compiled.declarations])
                    trial_context = self._dry_run_prefix(trial_declarations, [*plans, compiled.plan])
                    declarations = trial_declarations
                    plans.append(compiled.plan)
                    seen_plan_keys.add(key)
                    self._apply_registrations(compiled)
                    planner_insights.extend(
                        PlannerInsightExtractorRegistry().extract(
                            step=step,
                            compiled=compiled,
                            trial_context=trial_context,
                            index=self.index,
                        )
                    )
                    accepted.append(
                        StepIntentAcceptedStep(
                            step_id=step.step_id,
                            scope_id=step.scope_id,
                            capability_id=capability_id,
                            method_ids=tuple(
                                invocation.method_id
                                for invocation in compiled.plan.invocations
                            ),
                            produced_handles=tuple(
                                produced.handle for produced in step.produces
                            ),
                        )
                    )
                    accepted_current_step = True
                    break
                except Exception as exc:
                    candidate_errors.append(
                        _candidate_error_for_exception(
                            step=step,
                            capability_id=capability_id,
                            exc=exc,
                            planner_insights=tuple(planner_insights),
                            handle_registry=self.index.handle_registry,
                        )
                    )
            if accepted_current_step:
                index += 1
                continue

            blocker = StepIntentExecutionBlocker(
                step_id=step.step_id,
                scope_id=step.scope_id,
                stage="recipe_trial",
                code=_execution_blocker_code(candidate_errors),
                message=_execution_blocker_message(step.step_id, candidate_errors),
                capability_errors=tuple(
                    _unique_ordered(
                        [
                            *candidate_errors,
                            *self._candidate_warnings_for_step(step),
                        ]
                    )
                ),
                capability_id=_execution_blocker_capability_id(candidate_errors),
                missing_runtime_type=_execution_blocker_missing_runtime_type(candidate_errors),
            )
            skipped = tuple(
                StepIntentSkippedStep(
                    step_id=later.step_id,
                    scope_id=later.scope_id,
                    reason=f"skipped_due_to_prefix_blocker:{step.step_id}",
                )
                for later in steps[index + 1:]
            )
            return (
                None,
                StepIntentExecutionDiagnostic(
                    ok=False,
                    accepted_prefix=tuple(accepted),
                    applied_fills=tuple(self.index.applied_fills),
                    planner_insights=tuple(planner_insights),
                    preflight_issues=(),
                    blockers=(blocker,),
                    skipped_steps=skipped,
                ),
                _draft_with_steps(draft, steps),
            )
        return (
            PlannerOutput(
                context_declarations=declarations,
                step_plans=plans,
            ),
            StepIntentExecutionDiagnostic(
                ok=True,
                accepted_prefix=tuple(accepted),
                applied_fills=tuple(self.index.applied_fills),
                planner_insights=tuple(planner_insights),
                preflight_issues=(),
            ),
            _draft_with_steps(draft, steps),
        )

    def _capability_ids_for_step(self, step: StepIntent) -> list[str]:
        """返回某个 step 的候选 capability 顺序。"""
        report = self.step_reports.get(step.step_id)
        candidates: list[str] = []
        if step.recipe_hint and step.recipe_hint in self.allowed_capability_ids:
            return [step.recipe_hint]
        if report is not None and report.selected_capability_id:
            candidates.append(report.selected_capability_id)
        if report is not None:
            candidates.extend(candidate.capability_id for candidate in report.candidates if candidate.ok)
        return _unique_ordered(candidates)

    def _candidate_warnings_for_step(self, step: StepIntent) -> list[str]:
        """返回 resolver 生成的 LLM-facing warning，供 runtime blocker 兼容携带。"""
        return _candidate_warnings_for_report(self.step_reports.get(step.step_id))

    def _compile_with_capability(self, step: StepIntent, capability_id: str) -> _CompiledStep:
        """按 recipe 或 method capability 编译单个 StepIntent。"""
        recipe = self.recipe_specs.get(capability_id)
        if recipe is not None:
            return self._compile_recipe(step, recipe)
        return self._compile_method(step, capability_id)

    def _compile_recipe(self, step: StepIntent, recipe: FamilyRecipeExecutionSpec) -> _CompiledStep:
        """编译 recipe。"""
        fn = self.recipe_compilers.get(recipe.execution_strategy)
        if fn is None:
            raise StrategyDraftValidationError(
                f"recipe_execution_strategy_missing: {recipe.recipe_id}:{recipe.execution_strategy}"
            )
        return fn(self, step, recipe)

    def _compile_method(self, step: StepIntent, method_id: str) -> _CompiledStep:
        """编译单 method step。"""
        spec = self.method_specs.require(method_id)
        declaration_keys_before = set(self.index.declarations)
        for created in step.creates:
            if created.entity_type == "point" and created.handle not in self.index.bindings:
                self.index.register_created_entity(created)
        prep = PrepInvocationBuilder(
            binding_rules=self.binding_rules,
            index=self.index,
        ).build(method_id, step)
        inputs = self.binding_rules.bind(
            method_id,
            step,
            self.index,
            local_outputs=prep.local_outputs or {},
        )
        outputs = _method_outputs_for_step(
            method_id,
            step,
            spec.outputs,
            self.index,
            self.binding_rules,
        )
        main_promote = _promote_outputs_for_step(
            step,
            method_id,
            outputs,
            spec.outputs,
            self.index,
            self.binding_rules,
        )
        promote = {**(prep.promote or {}), **main_promote}
        plan = single_invocation_step(
            step_id=step.step_id,
            parent_scope=_step_parent_scope(step, promote),
            method_id=method_id,
            inputs=inputs,
            outputs=outputs,
            promote=promote,
            goal_type=step.goal_type,
            target_path=next(iter(main_promote.values())),
        )
        if prep.invocations:
            plan = StepPlan(
                step_id=plan.step_id,
                goal=plan.goal,
                scope=plan.scope,
                invocations=[*prep.invocations, *plan.invocations],
                expected_outputs=plan.expected_outputs,
                promote_outputs=plan.promote_outputs,
            )
        registrations = [
            RuntimeHandleBinding(handle, path, spec.outputs[output_name], f"step:{step.step_id}")
            for handle, output_name, path in _produced_registrations(
                step,
                method_id,
                promote,
                self.index,
            )
        ]
        registrations.extend(
            _companion_registrations_for_step(
                step,
                method_id,
                outputs,
                promote,
                spec.outputs,
                self.index,
                self.binding_rules,
            )
        )
        for created in step.creates:
            binding = self.index.bindings.get(created.handle)
            if created.entity_type == "point" and binding is not None and binding.path in promote.values():
                registrations.append(
                    RuntimeHandleBinding(
                        created.handle,
                        binding.path,
                        "Point",
                        f"step:{step.step_id}",
                    )
                )
        declarations = tuple(
            declaration
            for key, declaration in self.index.declarations.items()
            if key not in declaration_keys_before
        )
        return _CompiledStep(plan=plan, declarations=declarations, registrations=tuple(registrations))

    def _compile_right_angle_recipe(self, step: StepIntent) -> _CompiledStep:
        """编译“直角等腰候选 + 约束筛选” recipe。"""
        anchor, reference, target = _right_angle_roles(step, self.index)
        candidates = _temp(step.step_id, "candidates")
        selected = _temp(step.step_id, "selected_point")
        target_path = self.index.path_for(target, expected_type="PointRef")
        invocations = [
            MethodInvocation(
                invocation_id=f"{step.step_id}.right_angle_equal_length_candidates",
                method_id="right_angle_equal_length_candidates",
                scope=step.step_id,
                inputs={
                    "anchor": self.index.path_for(anchor, expected_type="Point"),
                    "reference": self.index.path_for(reference, expected_type="Point"),
                    "target": target_path,
                },
                outputs={"candidates": candidates},
            ),
            MethodInvocation(
                invocation_id=f"{step.step_id}.select_point_by_quadrant_constraint",
                method_id="select_point_by_quadrant_constraint",
                scope=step.step_id,
                inputs={
                    "candidates": candidates,
                    "target": target_path,
                    "quadrant": self.index.path_for(
                        self.index.fact_handle_by_type("orientation_constraint", step=step),
                        expected_type="OrientationHint",
                    ),
                    "parameter": self.index.parameter_symbol_path(),
                    "parameter_constraint": self.index.parameter_constraint_path(),
                },
                outputs={"selected_point": selected},
            ),
        ]
        plan = StepPlan(
            step_id=step.step_id,
            goal=StepGoal(
                goal_id=f"{step.goal_type}:{step.step_id}",
                type=step.goal_type,
                target_path=target_path,
                scope_id=_handle_scope(target),
            ),
            scope=_handle_scope(target),
            invocations=invocations,
            expected_outputs=[target_path],
            promote_outputs={selected: target_path},
        )
        registrations = tuple(
            RuntimeHandleBinding(item.handle, target_path, "Point", f"step:{step.step_id}")
            for item in step.produces
        )
        return _CompiledStep(plan=plan, registrations=registrations)

    def _compile_straightening_recipe(self, step: StepIntent) -> _CompiledStep:
        """编译“折线拉直候选 + 选择方案” recipe。"""
        auxiliary_handle = _created_point_handle(step)
        declarations = []
        if auxiliary_handle is not None:
            self.index.register_created_entity(auxiliary_handle)
            declarations.append(self.index.declarations[auxiliary_handle.handle])
            auxiliary_path = self.index.path_for(auxiliary_handle.handle, expected_type="PointRef")
        else:
            auxiliary_handle = _auto_created_recipe_point(step, self.index)
            self.index.register_created_entity(auxiliary_handle)
            declarations.append(self.index.declarations[auxiliary_handle.handle])
            auxiliary_path = self.index.path_for(auxiliary_handle.handle, expected_type="PointRef")
        candidates = _temp(step.step_id, "candidates")
        selected = _temp(step.step_id, "selected_candidate")
        auxiliary = _temp(step.step_id, "auxiliary_point")
        minimum_point_1 = _temp(step.step_id, "minimum_point_1")
        minimum_point_2 = _temp(step.step_id, "minimum_point_2")
        moving_membership = _moving_membership_for_straightening(step, self.index)
        fixed_1, fixed_2, line_1, line_2 = _straightening_point_roles(step, self.index)
        fixed_1_path, fixed_1_prep = _point_value_path_or_prepare(fixed_1, step, self.index)
        fixed_2_path, fixed_2_prep = _point_value_path_or_prepare(fixed_2, step, self.index)
        prep_invocations = [*fixed_1_prep[0], *fixed_2_prep[0]]
        prep_promote = {**fixed_1_prep[1], **fixed_2_prep[1]}
        invocations = [
            *prep_invocations,
            MethodInvocation(
                invocation_id=f"{step.step_id}.broken_path_straightening_candidates",
                method_id="broken_path_straightening_candidates",
                scope=step.step_id,
                inputs={
                    "path_transformation": _path_for_first_type(self.index, step, "PathTransformation"),
                    "moving_point_membership": self.index.path_for(moving_membership, expected_type="Condition"),
                    "fixed_point_1": fixed_1_path,
                    "fixed_point_2": fixed_2_path,
                    "line_point_1": self.index.path_for(line_1, expected_type="Point"),
                    "line_point_2": self.index.path_for(line_2, expected_type="Point"),
                },
                outputs={"candidates": candidates},
            ),
            MethodInvocation(
                invocation_id=f"{step.step_id}.select_straightening_candidate",
                method_id="select_straightening_candidate",
                scope=step.step_id,
                inputs={"candidates": candidates, "target": auxiliary_path},
                outputs={
                    "selected_candidate": selected,
                    "auxiliary_point": auxiliary,
                    "minimum_point_1": minimum_point_1,
                    "minimum_point_2": minimum_point_2,
                },
            ),
        ]
        endpoint_point_1, endpoint_point_2 = _straightening_endpoint_target_paths(
            step,
            self.index,
        )
        promote = {
            **prep_promote,
            candidates: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidates"),
            selected: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidate"),
            auxiliary: auxiliary_path,
            minimum_point_1: endpoint_point_1,
            minimum_point_2: endpoint_point_2,
        }
        plan = StepPlan(
            step_id=step.step_id,
            goal=StepGoal(
                goal_id=f"{step.goal_type}:{step.step_id}",
                type=step.goal_type,
                target_path=promote[selected],
                scope_id=step.scope_id,
            ),
            scope=step.scope_id,
            invocations=invocations,
            expected_outputs=list(promote.values()),
            promote_outputs=promote,
        )
        registrations: list[RuntimeHandleBinding] = []
        for item in step.produces:
            output_type = _produced_output_type(item, self.index.handle_registry)
            if output_type == "StraighteningCandidate":
                registrations.append(
                    RuntimeHandleBinding(
                        item.handle,
                        promote[selected],
                        "StraighteningCandidate",
                        f"step:{step.step_id}",
                    )
                )
            elif output_type == "Point":
                semantic = _semantic_name(item.handle)
                if semantic == STRAIGHTENING_ENDPOINT_POINT_1:
                    registrations.append(
                        RuntimeHandleBinding(
                            item.handle,
                            endpoint_point_1,
                            "Point",
                            f"step:{step.step_id}",
                        )
                    )
                elif semantic == STRAIGHTENING_ENDPOINT_POINT_2:
                    registrations.append(
                        RuntimeHandleBinding(
                            item.handle,
                            endpoint_point_2,
                            "Point",
                            f"step:{step.step_id}",
                        )
                    )
        if auxiliary_handle is not None:
            registrations.append(
                RuntimeHandleBinding(auxiliary_handle.handle, auxiliary_path, "Point", f"step:{step.step_id}")
            )
        return _CompiledStep(
            plan=plan,
            declarations=tuple(declarations),
            registrations=tuple(registrations),
        )

    def _compile_curve_candidate_parameter_recipe(self, step: StepIntent) -> _CompiledStep:
        """编译“候选点曲线筛选 + 曲线点反求参数” recipe。

        这个 recipe 只处理候选点已经存在之后的通用动作：用含参抛物线筛选候选，
        再把唯一候选点代入抛物线反求参数。它不负责化简函数、求参考点或生成候选；
        这些上下文准备应由独立 method step 完成。
        """
        target = _curve_candidate_target_handle(step, self.index)
        target_path = self.index.path_for(target, expected_type="PointRef")
        candidates_path = _path_for_readable_type(self.index, step, "PointList")
        parabola_path = _path_for_readable_type(self.index, step, "Parabola")
        filtered = _temp(step.step_id, "filtered_candidates")
        rejected = _temp(step.step_id, "rejected_candidates")
        selected_candidate = _temp(step.step_id, "selected_candidate")
        point = _temp(step.step_id, "point")
        parameter_value = _temp(step.step_id, "parameter_value")
        parabola = _temp(step.step_id, "parabola")
        primary_symbol = self.index.parameter_symbol_path()
        primary_constraint = self.index.parameter_constraint_path()
        parameter_output_key = _parameter_output_key_from_symbol_path(primary_symbol)
        invocations = [
            MethodInvocation(
                invocation_id=f"{step.step_id}.filter_point_candidates_by_quadratic_curve",
                method_id="filter_point_candidates_by_quadratic_curve",
                scope=step.step_id,
                inputs={
                    "candidates": candidates_path,
                    "target": target_path,
                    "parabola": parabola_path,
                    "x": self.index.path_for("symbol:problem:x", expected_type="Symbol"),
                    "parameter": primary_symbol,
                    "parameter_constraint": primary_constraint,
                },
                outputs={
                    "filtered_candidates": filtered,
                    "rejected_candidates": rejected,
                    "selected_candidate": selected_candidate,
                },
            ),
            MethodInvocation(
                invocation_id=f"{step.step_id}.parameter_from_curve_point_on_quadratic",
                method_id="parameter_from_curve_point_on_quadratic",
                scope=step.step_id,
                inputs={
                    "quadratic": parabola_path,
                    "x": self.index.path_for("symbol:problem:x", expected_type="Symbol"),
                    "point": selected_candidate,
                    "parameter": primary_symbol,
                    "parameter_constraint": primary_constraint,
                },
                outputs={
                    "point": point,
                    "parameter_value": parameter_value,
                    "parabola": parabola,
                },
            ),
        ]
        parabola_target = _scoped_output_path(self.index.context, step.scope_id, "parabola")
        if parabola_path == parabola_target:
            parabola_target = _scoped_output_path(self.index.context, step.scope_id, "solved_parabola")
        promote = {
            point: target_path,
            parameter_value: _scoped_output_path(
                self.index.context,
                step.scope_id,
                parameter_output_key,
            ),
            parabola: parabola_target,
        }
        for produced in step.produces:
            if produced.handle.startswith("answer:"):
                goal = self.index.question_goals.get(produced.handle)
                if goal is not None and goal.value_type == "Point":
                    promote[point] = goal.target_path
        plan = StepPlan(
            step_id=step.step_id,
            goal=StepGoal(
                goal_id=f"{step.goal_type}:{step.step_id}",
                type=step.goal_type,
                target_path=target_path,
                scope_id=step.scope_id,
            ),
            scope=step.scope_id,
            invocations=invocations,
            expected_outputs=list(promote.values()),
            promote_outputs=promote,
        )
        registrations = [
            RuntimeHandleBinding(item.handle, promote[point], "Point", f"step:{step.step_id}")
            for item in step.produces
            if _produced_output_type(item, self.index.handle_registry) == "Point"
        ]
        return _CompiledStep(plan=plan, registrations=tuple(registrations))

    def _compile_equal_length_ray_path_reduction_recipe(self, step: StepIntent) -> _CompiledStep:
        """编译“等长射线路径降维为单距离最值” recipe。

        这个 recipe 面向 LLM 是一个高层标准动作：把“两动点距离和”转化为一个
        固定点到内部辅助点的距离最值。runtime 内部仍复用低层
        ``equal_length_ray_point`` 与 ``distance_between_points`` method，并由
        compiler 自动声明辅助点，避免让 LLM 自己命名/创建辅助点。
        """
        roles = _equal_length_ray_path_reduction_roles(step, self.index)
        auxiliary_path = _generated_equal_length_auxiliary_point_path(step, self.index)
        declaration = _point_declaration_for_path(
            self.index.context,
            auxiliary_path,
            definition="equal_length_ray_path_auxiliary_point",
        )
        self.index.declarations[auxiliary_path] = declaration
        auxiliary_point = _temp(step.step_id, "equal_length_auxiliary_point")
        distance = _temp(step.step_id, "distance")
        minimum_target = _minimum_expression_target_path(step, self.index)
        invocations = [
            MethodInvocation(
                invocation_id=f"{step.step_id}.equal_length_ray_point",
                method_id="equal_length_ray_point",
                scope=step.step_id,
                inputs={
                    "anchor": _point_value_path_for_step(roles["anchor"], step, self.index),
                    "reference_point": _point_value_path_for_step(
                        roles["reference_point"],
                        step,
                        self.index,
                    ),
                    "ray_point": _point_value_path_for_step(roles["ray_point"], step, self.index),
                    "target": auxiliary_path,
                },
                outputs={"point": auxiliary_point},
            ),
            MethodInvocation(
                invocation_id=f"{step.step_id}.distance_between_points",
                method_id="distance_between_points",
                scope=step.step_id,
                inputs={
                    "p1": _point_value_path_for_step(roles["fixed_point"], step, self.index),
                    "p2": auxiliary_point,
                },
                outputs={"distance": distance},
            ),
        ]
        promote = {
            auxiliary_point: auxiliary_path,
            distance: minimum_target,
        }
        plan = StepPlan(
            step_id=step.step_id,
            goal=StepGoal(
                goal_id=f"{step.goal_type}:{step.step_id}",
                type=step.goal_type,
                target_path=minimum_target,
                scope_id=step.scope_id,
            ),
            scope=step.scope_id,
            invocations=invocations,
            expected_outputs=list(promote.values()),
            promote_outputs=promote,
        )
        registrations = tuple(
            RuntimeHandleBinding(item.handle, minimum_target, "MinimumExpression", f"step:{step.step_id}")
            for item in step.produces
            if _produced_output_type(item, self.index.handle_registry) == "MinimumExpression"
        )
        return _CompiledStep(
            plan=plan,
            declarations=(declaration,),
            registrations=registrations,
        )

    def _compile_straightened_distance_minimum_recipe(self, step: StepIntent) -> _CompiledStep:
        """编译“已拉直方案 -> 端点距离最值” recipe。

        split recipe 路径中，前序 ``broken_path_straightening_and_select`` 已经确定
        最短线段端点；这里优先消费这些 endpoint metadata，避免继续让 LLM
        通过普通 point reads 猜测距离两端。
        """
        endpoints = _straightening_endpoint_handles_from_reads(step, self.index)
        if endpoints is None:
            return self._compile_method(step, "distance_between_points")
        point_1, point_2 = endpoints
        output_name = "evaluated_distance" if _parameter_value_handle(step, self.index) else "distance"
        distance = _temp(step.step_id, output_name)
        target_path = _minimum_expression_target_path(step, self.index)
        inputs = {
            "p1": self.index.path_for(point_1, expected_type="Point"),
            "p2": self.index.path_for(point_2, expected_type="Point"),
        }
        parameter_handle = _parameter_value_handle(step, self.index)
        if parameter_handle is not None:
            inputs["parameter"] = self.index.parameter_symbol_path()
            inputs["parameter_value"] = self.index.path_for(
                parameter_handle,
                expected_type="ParameterValue",
            )
        plan = StepPlan(
            step_id=step.step_id,
            goal=StepGoal(
                goal_id=f"{step.goal_type}:{step.step_id}",
                type=step.goal_type,
                target_path=target_path,
                scope_id=step.scope_id,
            ),
            scope=step.scope_id,
            invocations=[
                MethodInvocation(
                    invocation_id=f"{step.step_id}.distance_between_points",
                    method_id="distance_between_points",
                    scope=step.step_id,
                    inputs=inputs,
                    outputs={output_name: distance},
                )
            ],
            expected_outputs=[target_path],
            promote_outputs={distance: target_path},
        )
        registrations = tuple(
            RuntimeHandleBinding(item.handle, target_path, "MinimumExpression", f"step:{step.step_id}")
            for item in step.produces
            if _produced_output_type(item, self.index.handle_registry) == "MinimumExpression"
        )
        return _CompiledStep(plan=plan, registrations=registrations)

    def _compile_broken_path_straightening_minimum_expression_recipe(self, step: StepIntent) -> _CompiledStep:
        """编译“折线拉直候选 + 选择方案 + 计算最小值表达式” recipe。"""
        fixed_1, fixed_2 = _straightening_minimum_fixed_points(step, self.index)
        straightening_inputs: dict[str, str] = {}
        moving_locus = _path_for_readable_type_or_none(self.index, step, "Line")
        if moving_locus is not None:
            straightening_inputs["moving_locus"] = moving_locus
        else:
            moving_membership = _moving_membership_for_straightening(step, self.index)
            role_fixed_1, role_fixed_2, line_1, line_2 = _straightening_point_roles(step, self.index)
            fixed_1, fixed_2 = role_fixed_1, role_fixed_2
            straightening_inputs.update(
                {
                    "moving_point_membership": self.index.path_for(
                        moving_membership,
                        expected_type="Condition",
                    ),
                    "line_point_1": self.index.path_for(line_1, expected_type="Point"),
                    "line_point_2": self.index.path_for(line_2, expected_type="Point"),
                }
            )
        fixed_1_path, fixed_1_prep = _point_value_path_or_prepare(fixed_1, step, self.index)
        fixed_2_path, fixed_2_prep = _point_value_path_or_prepare(fixed_2, step, self.index)
        candidates = _temp(step.step_id, "candidates")
        selected = _temp(step.step_id, "selected_candidate")
        auxiliary = _temp(step.step_id, "auxiliary_point")
        minimum_point_1 = _temp(step.step_id, "minimum_point_1")
        minimum_point_2 = _temp(step.step_id, "minimum_point_2")
        distance = _temp(step.step_id, "distance")
        target_path = _minimum_expression_target_path(step, self.index)
        declarations = []
        auxiliary_handle = _created_point_handle(step)
        if auxiliary_handle is not None:
            self.index.register_created_entity(auxiliary_handle)
            declarations.append(self.index.declarations[auxiliary_handle.handle])
            auxiliary_path = self.index.path_for(auxiliary_handle.handle, expected_type="PointRef")
        else:
            auxiliary_path = _generated_straightening_auxiliary_point_path(step, self.index)
            declarations.append(
                _point_declaration_for_path(
                    self.index.context,
                    auxiliary_path,
                    definition="straightening_auxiliary_point",
                )
            )
        prep_invocations = [*fixed_1_prep[0], *fixed_2_prep[0]]
        prep_promote = {**fixed_1_prep[1], **fixed_2_prep[1]}
        invocations = [
            *prep_invocations,
            MethodInvocation(
                invocation_id=f"{step.step_id}.broken_path_straightening_candidates",
                method_id="broken_path_straightening_candidates",
                scope=step.step_id,
                inputs={
                    "path_transformation": _path_for_readable_type(self.index, step, "PathTransformation"),
                    "fixed_point_1": fixed_1_path,
                    "fixed_point_2": fixed_2_path,
                    **straightening_inputs,
                },
                outputs={"candidates": candidates},
            ),
            MethodInvocation(
                invocation_id=f"{step.step_id}.select_straightening_candidate",
                method_id="select_straightening_candidate",
                scope=step.step_id,
                inputs={"candidates": candidates, "target": auxiliary_path},
                outputs={
                    "selected_candidate": selected,
                    "auxiliary_point": auxiliary,
                    "minimum_point_1": minimum_point_1,
                    "minimum_point_2": minimum_point_2,
                },
            ),
            MethodInvocation(
                invocation_id=f"{step.step_id}.distance_between_points",
                method_id="distance_between_points",
                scope=step.step_id,
                inputs={
                    "p1": minimum_point_1,
                    "p2": minimum_point_2,
                },
                outputs={"distance": distance},
            ),
        ]
        endpoint_point_1, endpoint_point_2 = _straightening_endpoint_target_paths(
            step,
            self.index,
        )
        promote = {
            **prep_promote,
            candidates: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidates"),
            selected: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidate"),
            auxiliary: auxiliary_path,
            minimum_point_1: endpoint_point_1,
            minimum_point_2: endpoint_point_2,
            distance: target_path,
        }
        plan = StepPlan(
            step_id=step.step_id,
            goal=StepGoal(
                goal_id=f"{step.goal_type}:{step.step_id}",
                type=step.goal_type,
                target_path=target_path,
                scope_id=step.scope_id,
            ),
            scope=step.scope_id,
            invocations=invocations,
            expected_outputs=list(promote.values()),
            promote_outputs=promote,
        )
        registrations: list[RuntimeHandleBinding] = []
        for item in step.produces:
            output_type = _produced_output_type(item, self.index.handle_registry)
            if output_type == "MinimumExpression":
                registrations.append(
                    RuntimeHandleBinding(item.handle, target_path, "MinimumExpression", f"step:{step.step_id}")
                )
            elif output_type == "Point":
                semantic = _semantic_name(item.handle)
                if "point_1" in semantic:
                    registrations.append(
                        RuntimeHandleBinding(
                            item.handle,
                            promote[minimum_point_1],
                            "Point",
                            f"step:{step.step_id}",
                        )
                    )
                elif "point_2" in semantic:
                    registrations.append(
                        RuntimeHandleBinding(
                            item.handle,
                            promote[minimum_point_2],
                            "Point",
                            f"step:{step.step_id}",
                        )
                    )
        return _CompiledStep(plan=plan, declarations=tuple(declarations), registrations=registrations)

    def _apply_registrations(self, compiled: _CompiledStep) -> None:
        """把已通过 dry-run 的输出 alias 写回 index。"""
        for declaration in compiled.declarations:
            self.index.declarations[declaration.path] = declaration
        for binding in compiled.registrations:
            self.index.register(binding.handle, binding.path, binding.value_type, source=binding.source)
            if binding.value_type == "Point":
                for handle, existing in list(self.index.bindings.items()):
                    if handle.startswith("point:") and existing.path == binding.path:
                        self.index.register(handle, binding.path, "Point", source=binding.source)

    def _dry_run_prefix(self, declarations: list[Any], plans: list[StepPlan]) -> RuntimeContext:
        """在 fresh RuntimeContext 上执行当前 prefix，作为 trial 裁决。"""
        from shuxueshuo_server.solver.runtime.executor import (
            DeclarationValidator,
            InvocationExecutor,
        )
        from shuxueshuo_server.solver.runtime.methods import default_stateless_registry

        trial_context = ContextBuilder(self.context.kernel).build(self.context.problem)
        DeclarationValidator().validate_declarations(trial_context, declarations)
        trial_context.apply_declarations(declarations)
        executor = InvocationExecutor(
            self.method_specs,
            methods=default_stateless_registry(),
            kernel=self.context.kernel,
        )
        execution = executor.execute_plan(trial_context, plans)
        failed = [check.name for check in execution.checks if not check.ok]
        if failed:
            raise StrategyDraftValidationError(
                "recipe_trial_checks_failed: " + ", ".join(failed)
            )
        return trial_context


class PlannerInsightExtractorRegistry:
    """从已执行 prefix 的 method 输出中抽取 planner-visible insight。"""

    path_transformation_methods: frozenset[str] = frozenset({
        "square_path_dimension_reduction",
    })

    def extract(
        self,
        *,
        step: StepIntent,
        compiled: _CompiledStep,
        trial_context: RuntimeContext,
        index: CanonicalRuntimeBindingIndex,
    ) -> tuple[StepIntentPlannerInsight, ...]:
        """返回当前 accepted step 产生的语义 insight。"""
        method_ids = {invocation.method_id for invocation in compiled.plan.invocations}
        insights: list[StepIntentPlannerInsight] = []
        if method_ids & self.path_transformation_methods:
            insights.extend(
                self._path_transformation_insights(
                    step=step,
                    compiled=compiled,
                    trial_context=trial_context,
                    index=index,
                )
            )
        insights.extend(
            self._straightening_endpoint_insights(
                step=step,
                compiled=compiled,
                index=index,
            )
        )
        return tuple(insights)

    def _path_transformation_insights(
        self,
        *,
        step: StepIntent,
        compiled: _CompiledStep,
        trial_context: RuntimeContext,
        index: CanonicalRuntimeBindingIndex,
    ) -> list[StepIntentPlannerInsight]:
        """抽取 PathTransformation 中的动点和固定端点信息。"""
        registrations = {binding.handle: binding for binding in compiled.registrations}
        insights: list[StepIntentPlannerInsight] = []
        for produced in step.produces:
            if _produced_output_type(produced, index.handle_registry) != "PathTransformation":
                continue
            binding = registrations.get(produced.handle)
            if binding is None:
                continue
            try:
                payload = trial_context.read_path(
                    binding.path,
                    from_scope_id=step.scope_id,
                    expected_type="PathTransformation",
                ).value
            except Exception:
                continue
            if not isinstance(payload, Mapping):
                continue
            facts = self._path_transformation_facts(payload, step=step, index=index)
            if not facts:
                continue
            insights.append(
                StepIntentPlannerInsight(
                    step_id=step.step_id,
                    scope_id=step.scope_id,
                    produced_handle=produced.handle,
                    output_type="PathTransformation",
                    facts=facts,
                    repair_note=_path_transformation_repair_note(facts),
                )
            )
        return insights

    def _path_transformation_facts(
        self,
        payload: Mapping[str, Any],
        *,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
    ) -> dict[str, Any]:
        """把 runtime PathTransformation payload 转成 canonical handle 事实。"""
        facts: dict[str, Any] = {}
        moving_name = payload.get("moving_point_name") or payload.get("moving_point")
        moving_handle: str | None = None
        if isinstance(moving_name, str):
            moving_handle = _point_handle_for_insight(moving_name, step=step, index=index)
            facts["moving_point"] = moving_handle or moving_name
        fixed_names = payload.get("fixed_point_names") or payload.get("fixed_points")
        if isinstance(fixed_names, (list, tuple)):
            fixed_handles: list[str] = []
            for name in fixed_names:
                if not isinstance(name, str):
                    continue
                fixed_handles.append(_point_handle_for_insight(name, step=step, index=index) or name)
            if fixed_handles:
                facts["fixed_points"] = fixed_handles
        transformed_path = payload.get("transformed_path")
        if isinstance(transformed_path, str) and transformed_path:
            facts["transformed_path"] = transformed_path
        if moving_handle is not None:
            locus_step = _recommended_locus_step_for_moving_point(
                moving_handle,
                step=step,
                index=index,
            )
            if locus_step is not None:
                facts["next_locus_step"] = locus_step
        return facts

    def _straightening_endpoint_insights(
        self,
        *,
        step: StepIntent,
        compiled: _CompiledStep,
        index: CanonicalRuntimeBindingIndex,
    ) -> list[StepIntentPlannerInsight]:
        """抽取通用将军饮马 recipe 暴露的最短线段端点。"""
        method_ids = {invocation.method_id for invocation in compiled.plan.invocations}
        if "select_straightening_candidate" not in method_ids:
            return []
        endpoint_handles = [
            produced.handle
            for produced in step.produces
            if (
                _produced_output_type(produced, index.handle_registry) == "Point"
                and is_straightening_endpoint_name(_semantic_name(produced.handle))
            )
        ]
        endpoint_handles = _unique_ordered(endpoint_handles)
        if len(endpoint_handles) < 2:
            return []
        minimum_handles = [
            produced.handle
            for produced in step.produces
            if _produced_output_type(produced, index.handle_registry) == "MinimumExpression"
        ]
        return [
            StepIntentPlannerInsight(
                step_id=step.step_id,
                scope_id=step.scope_id,
                produced_handle=minimum_handles[0] if minimum_handles else step.target,
                output_type="StraighteningMinimum",
                facts={
                    "minimum_points": endpoint_handles,
                    "next_method": "line_locus_minimum_point",
                },
                repair_note=(
                    "将军饮马 recipe 已给出拉直后最短线段端点；后续若要求最短状态动点，"
                    "应读取这些端点和动点轨迹，使用 line_locus_minimum_point，再由几何关系恢复最终答案点。"
                ),
            )
        ]


def _point_handle_for_insight(
    name: str,
    *,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """把 method output 中的点名映射为当前可见 canonical point handle。"""
    try:
        return index.point_handle_by_name(name, step=step)
    except StrategyDraftValidationError:
        return None


def _recommended_locus_step_for_moving_point(
    moving_handle: str,
    *,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, Any] | None:
    """若可唯一找到 moving point 的参数化坐标 fact，给出下一步轨迹线建议。"""
    point_name = _handle_name(moving_handle)
    matches: list[str] = []
    for handle, binding in sorted(index.bindings.items()):
        if not handle.startswith("fact:"):
            continue
        if binding.value_type != "Point":
            continue
        try:
            if not index.context.is_visible(step.scope_id, _binding_scope(binding.path)):
                continue
        except Exception:
            continue
        semantic_name = _semantic_name(handle)
        if _parameterized_point_state_name(semantic_name) != point_name:
            continue
        matches.append(handle)
    unique = _unique_ordered(matches)
    if len(unique) != 1:
        return None
    return {
        "recommended_next_capability": "parameterized_point_locus_line",
        "recommended_reads": [unique[0]],
        "recommended_produces": f"fact:{step.scope_id}:{point_name}_locus_line",
        "before_capability": "broken_path_straightening_minimum_expression",
    }


def _draft_with_steps(
    draft: StepIntentDraft,
    steps: list[StepIntent] | tuple[StepIntent, ...],
) -> StepIntentDraft:
    """用已执行/补位后的 flat steps 重建 scoped effective draft。"""
    grouped: dict[str, list[StepIntent]] = {scope.scope_id: [] for scope in draft.scopes}
    for step in steps:
        grouped.setdefault(step.scope_id, []).append(step)
    scopes = [
        replace(scope, steps=tuple(grouped.get(scope.scope_id, ())))
        for scope in draft.scopes
    ]
    known_scope_ids = {scope.scope_id for scope in draft.scopes}
    for scope_id, scope_steps in grouped.items():
        if scope_id in known_scope_ids:
            continue
        scopes.append(
            StepIntentScope(
                scope_id=scope_id,
                label=f"scope {scope_id}",
                steps=tuple(scope_steps),
            )
        )
    return StepIntentDraft(scopes=tuple(scopes))


def _parameterized_point_state_name(semantic_name: str) -> str | None:
    """识别 ``G_parametric_coordinate`` / ``G_parameterized_point`` 类状态名。"""
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_"
        r"(?:parametric|parameterized|param)_"
        r"(?:coord|coordinate|point)(?:_[A-Za-z0-9_]+)?",
        semantic_name,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    point = match.group("point")
    return point[:1].upper() + point[1:]


def _path_transformation_repair_note(facts: Mapping[str, Any]) -> str:
    """生成 PathTransformation insight 的 repair 提示。"""
    moving = facts.get("moving_point")
    fixed = facts.get("fixed_points")
    path = facts.get("transformed_path")
    parts = []
    if moving:
        parts.append(f"后续轨迹、折线拉直和最短状态点应围绕 moving_point={moving}")
    if fixed:
        parts.append(f"固定端点为 {fixed}")
    if path:
        parts.append(f"降维后的路径为 {path}")
    locus_step = facts.get("next_locus_step")
    if isinstance(locus_step, Mapping):
        reads = locus_step.get("recommended_reads")
        produces = locus_step.get("recommended_produces")
        if reads and produces:
            parts.append(
                "进入将军饮马前，先用 parameterized_point_locus_line 读取 "
                f"{reads}，produces {produces}"
            )
    parts.append("最终答案若不是该 moving point，需要再用对应几何关系从极值状态动点恢复。")
    return "；".join(parts)


def _compile_single_method_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译单 method recipe。"""
    if len(recipe.method_sequence) != 1:
        raise StrategyDraftValidationError(
            f"recipe_execution_strategy_missing: {recipe.recipe_id}:{recipe.execution_strategy}"
        )
    return compiler._compile_method(step, recipe.method_sequence[0])


def _compile_right_angle_construct_select_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译直角等腰候选筛选 recipe。"""
    return compiler._compile_right_angle_recipe(step)


def _compile_curve_candidate_parameter_solve_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译曲线候选点筛选并反求参数 recipe。"""
    return compiler._compile_curve_candidate_parameter_recipe(step)


def _compile_straightening_candidates_select_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译折线拉直候选筛选 recipe。"""
    return compiler._compile_straightening_recipe(step)


def _compile_equal_length_ray_path_reduction_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译等长射线路径降维 recipe。"""
    return compiler._compile_equal_length_ray_path_reduction_recipe(step)


def _compile_straightened_distance_minimum_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译 split 将军饮马后续的端点距离最值 recipe。"""
    return compiler._compile_straightened_distance_minimum_recipe(step)


def _compile_broken_path_straightening_minimum_expression_recipe(
    compiler: _RecipePlanCompiler,
    step: StepIntent,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译通用将军饮马求最值表达式 recipe。"""
    return compiler._compile_broken_path_straightening_minimum_expression_recipe(step)


DEFAULT_RECIPE_COMPILERS: dict[str, RecipeCompileStrategyFn] = {
    "single_method": _compile_single_method_recipe,
    "right_angle_construct_select": _compile_right_angle_construct_select_recipe,
    "curve_candidate_parameter_solve": _compile_curve_candidate_parameter_solve_recipe,
    "straightening_candidates_select": _compile_straightening_candidates_select_recipe,
    "equal_length_ray_path_reduction": _compile_equal_length_ray_path_reduction_recipe,
    "straightened_distance_minimum": _compile_straightened_distance_minimum_recipe,
    "broken_path_straightening_minimum_expression": _compile_broken_path_straightening_minimum_expression_recipe,
}


def _equal_length_ray_path_reduction_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从 canonical facts 推断等长射线路径降维角色。

    返回:
    - ``anchor``: 等长关系的公共端点，也是射线端点；
    - ``ray_point``: 射线方向点；
    - ``reference_point``: 线段另一端，低层等长构造使用；
    - ``fixed_point``: 原路径中连接线段动点的固定端点，最终与辅助点求距离。

    该推断只依赖结构化 ``point_on_segment``、``point_on_ray``、
    ``equal_length_condition`` 与 ``path_minimum_target``，不使用和平题点名。
    """
    ray_fact = index.fact_handle_by_type("point_on_ray", step=step)
    segment_fact = index.fact_handle_by_type("point_on_segment", step=step)
    equal_fact = index.fact_handle_by_type("equal_length_condition", step=step)
    target_fact = index.fact_handle_by_type("path_minimum_target", step=step)

    ray_payload = index.fact_payload(ray_fact)
    segment_payload = index.fact_payload(segment_fact)
    equal_payload = index.fact_payload(equal_fact)
    target_payload = index.fact_payload(target_fact)

    ray_dynamic_point = _payload_handle(ray_payload, "point", context=ray_fact)
    ray_handle = _payload_handle(ray_payload, "ray", context=ray_fact)
    ray_entity = index.entity_payload(ray_handle)
    ray_origin = _payload_handle(ray_entity, "origin", context=ray_handle)
    ray_through = _payload_handle(ray_entity, "through", context=ray_handle)

    segment_dynamic_point = _payload_handle(segment_payload, "point", context=segment_fact)
    segment_handle = _payload_handle(segment_payload, "segment", context=segment_fact)
    segment_endpoints = _segment_endpoints_from_entity_payload(index, segment_handle)

    left = _length_endpoint_handles(equal_payload.get("left"), step, index, context=f"{equal_fact}.left")
    right = _length_endpoint_handles(equal_payload.get("right"), step, index, context=f"{equal_fact}.right")
    common = set(left) & set(right)
    if len(common) != 1:
        raise StrategyDraftValidationError(f"equal_length_common_anchor_not_found: {equal_fact}")
    anchor = next(iter(common))
    if anchor != ray_origin:
        raise StrategyDraftValidationError(
            f"equal_length_ray_anchor_mismatch: {ray_fact}:{equal_fact}"
        )
    if anchor not in segment_endpoints:
        raise StrategyDraftValidationError(
            f"equal_length_segment_anchor_mismatch: {segment_fact}:{equal_fact}"
        )
    if ray_dynamic_point not in left and ray_dynamic_point not in right:
        raise StrategyDraftValidationError(
            f"equal_length_ray_dynamic_point_mismatch: {ray_fact}:{equal_fact}"
        )
    if segment_dynamic_point not in left and segment_dynamic_point not in right:
        raise StrategyDraftValidationError(
            f"equal_length_segment_dynamic_point_mismatch: {segment_fact}:{equal_fact}"
        )
    reference_point = _segment_reference_point(segment_endpoints, anchor, context=segment_fact)
    fixed_point, path_reference_point = _fixed_and_reference_from_path_target(
        target_payload,
        segment_dynamic_point=segment_dynamic_point,
        ray_dynamic_point=ray_dynamic_point,
        step=step,
        index=index,
        context=target_fact,
    )
    if path_reference_point != reference_point:
        raise StrategyDraftValidationError(
            "equal_length_path_reference_mismatch: "
            f"path={path_reference_point}, segment_reference={reference_point}"
        )
    return {
        "anchor": anchor,
        "ray_point": ray_through,
        "reference_point": reference_point,
        "fixed_point": fixed_point,
    }


def _point_value_path_for_step(
    point_handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取点值 path，优先使用 step 显式 reads 的同名坐标 fact。

    对某些题，ProblemIR 中的点是全题实体，但它在当前问才被求成含参坐标。
    例如 ``point:problem:B`` 的第（Ⅱ）问坐标会以
    ``fact:ii:B_coordinate_expr`` 出现。recipe 内部低层 method 需要的是点值，
    所以这里优先使用当前 step 已读入的坐标 fact。
    """
    point_name = _handle_name(point_handle)
    for handle in step.reads:
        if not handle.startswith("fact:"):
            continue
        if not _is_point_coordinate_semantic_name(_semantic_name(handle)):
            continue
        if _point_name_from_point_state_semantic(_semantic_name(handle)) != point_name:
            continue
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == "Point":
            return binding.path
    try:
        path = index.path_for(point_handle, expected_type="Point")
        try:
            index.context.read_path(path, from_scope_id=step.scope_id, expected_type="Point")
            return path
        except Exception:
            state_path = _visible_point_state_path_for_name(point_name, step, index)
            if state_path is not None:
                return state_path
            raise StrategyDraftValidationError(
                f"point_value_not_resolved: {point_handle}"
            )
    except StrategyDraftValidationError:
        path = _visible_point_state_path_for_name(point_name, step, index)
        if path is not None:
            return path
        raise


def _point_value_path_or_prepare(
    point_handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, tuple[tuple[MethodInvocation, ...], dict[str, str]]]:
    """读取点值；必要时为可确定定义点生成当前 recipe 内部 prep invocation。"""
    try:
        return _point_value_path_for_step(point_handle, step, index), ((), {})
    except StrategyDraftValidationError:
        definition = _point_definition(point_handle, index)
        if definition == "midpoint":
            return _prepare_midpoint_point_value(point_handle, step, index)
        if definition != "axis_x_intercept":
            raise
        point_name = _handle_name(point_handle)
        output_path = _temp(step.step_id, f"prepared_{point_name}_coordinate")
        promote_path = _scoped_output_path(index.context, step.scope_id, f"{point_name}_coordinate")
        invocation = MethodInvocation(
            invocation_id=f"{step.step_id}.prepare_{point_name}_coordinate",
            method_id="quadratic_axis_x_intercept_point",
            scope=step.step_id,
            inputs={
                "parabola": _path_for_readable_type(index, step, "Parabola"),
                "x": index.path_for("symbol:problem:x", expected_type="Symbol"),
                "target": index.point_ref_path_for(point_handle),
            },
            outputs={"axis_point": output_path},
        )
        return output_path, ((invocation,), {output_path: promote_path})


def _prepare_midpoint_point_value(
    point_handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, tuple[tuple[MethodInvocation, ...], dict[str, str]]]:
    """为 midpoint definition 点生成 recipe 内部 midpoint_point prep。"""
    payload = index.entity_payload(point_handle)
    raw_endpoints = payload.get("of")
    if not (
        isinstance(raw_endpoints, list)
        and len(raw_endpoints) == 2
        and all(isinstance(item, str) for item in raw_endpoints)
    ):
        raise StrategyDraftValidationError(f"midpoint_definition_endpoints_missing: {point_handle}")
    p1_path, p1_prep = _point_value_path_or_prepare(raw_endpoints[0], step, index)
    p2_path, p2_prep = _point_value_path_or_prepare(raw_endpoints[1], step, index)
    point_name = _handle_name(point_handle)
    output_path = _temp(step.step_id, f"prepared_{point_name}_coordinate")
    promote_path = _scoped_output_path(index.context, step.scope_id, f"{point_name}_coordinate")
    invocation = MethodInvocation(
        invocation_id=f"{step.step_id}.prepare_{point_name}_midpoint_coordinate",
        method_id="midpoint_point",
        scope=step.step_id,
        inputs={
            "p1": p1_path,
            "p2": p2_path,
            "target": index.point_ref_path_for(point_handle),
        },
        outputs={"midpoint": output_path},
    )
    return (
        output_path,
        (
            (*p1_prep[0], *p2_prep[0], invocation),
            {**p1_prep[1], **p2_prep[1], output_path: promote_path},
        ),
    )


def _point_definition(point_handle: str, index: CanonicalRuntimeBindingIndex) -> str | None:
    """读取 canonical point entity 的 definition。"""
    try:
        payload = index.entity_payload(point_handle)
    except StrategyDraftValidationError:
        return None
    value = payload.get("definition")
    return str(value) if isinstance(value, str) else None


def _segment_reference_point(
    endpoints: tuple[str, str],
    anchor: str,
    *,
    context: str,
) -> str:
    """返回线段中非等长公共端点的参考端点。"""
    try:
        return _other_endpoint_handle(endpoints, anchor)
    except StrategyDraftValidationError as exc:
        raise StrategyDraftValidationError(
            f"equal_length_reference_point_not_found: {context}"
        ) from exc


def _fixed_and_reference_from_path_target(
    payload: Mapping[str, Any],
    *,
    segment_dynamic_point: str,
    ray_dynamic_point: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    context: str,
) -> tuple[str, str]:
    """从路径最值目标中找最终距离固定点和射线项参考点。"""
    terms = _path_target_terms(payload, step=step, index=index, context=context)
    fixed_point: str | None = None
    reference_point: str | None = None
    for p1, p2 in terms:
        pair = (p1, p2)
        if segment_dynamic_point in pair:
            fixed_point = _other_endpoint_handle(pair, segment_dynamic_point)
        if ray_dynamic_point in pair:
            reference_point = _other_endpoint_handle(pair, ray_dynamic_point)
    if fixed_point is None:
        raise StrategyDraftValidationError(
            f"equal_length_path_fixed_point_not_found: {context}"
        )
    if reference_point is None:
        raise StrategyDraftValidationError(
            f"equal_length_path_reference_point_not_found: {context}"
        )
    return fixed_point, reference_point


def _path_target_terms(
    payload: Mapping[str, Any],
    *,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    context: str,
) -> list[tuple[str, str]]:
    """把 ``OM+BN`` 或结构化 path terms 转成 point handle 对。"""
    value = payload.get("path")
    if isinstance(value, list):
        terms: list[tuple[str, str]] = []
        for idx, item in enumerate(value):
            if (
                isinstance(item, list)
                and len(item) == 2
                and all(isinstance(handle, str) for handle in item)
            ):
                terms.append((item[0], item[1]))
                continue
            raise StrategyDraftValidationError(
                f"path_minimum_target_term_invalid: {context}[{idx}]"
            )
        return terms
    if isinstance(value, str):
        terms = []
        for token in re.findall(r"[A-Za-z]{2}", value):
            terms.append(
                (
                    index.point_handle_by_name(token[0], step=step),
                    index.point_handle_by_name(token[1], step=step),
                )
            )
        if terms:
            return terms
    raise StrategyDraftValidationError(f"path_minimum_target_path_missing: {context}")


def _generated_equal_length_auxiliary_point_path(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """生成 recipe 内部辅助点的稳定 points path。"""
    base = "equal_length_auxiliary_point"
    for suffix in ("", "_2", "_3"):
        name = f"{base}{suffix}"
        path = _runtime_path_for_scope(index.context, step.scope_id, "points", name)
        if not _context_path_exists(index.context, path):
            return path
    return _runtime_path_for_scope(index.context, step.scope_id, "points", f"{base}_{step.step_id}")


def _generated_straightening_auxiliary_point_path(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """生成通用折线拉直 recipe 的内部辅助点 path。"""
    base = "straightening_auxiliary_point"
    for suffix in ("", "_2", "_3"):
        name = f"{base}{suffix}"
        path = _runtime_path_for_scope(index.context, step.scope_id, "points", name)
        if not _context_path_exists(index.context, path):
            return path
    return _runtime_path_for_scope(index.context, step.scope_id, "points", f"{base}_{step.step_id}")


def _minimum_expression_target_path(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取 recipe 产出的 MinimumExpression target path。"""
    candidates = tuple(
        produced for produced in step.produces
        if _produced_output_type(produced, index.handle_registry) == "MinimumExpression"
    )
    for produced in candidates:
        if step.target.startswith("answer:") and produced.handle == step.target:
            return _target_path_for_produced(produced, "MinimumExpression", index, step)
    for produced in candidates:
        if produced.handle.startswith("answer:"):
            return _target_path_for_produced(produced, "MinimumExpression", index, step)
    if candidates:
        return _target_path_for_produced(candidates[0], "MinimumExpression", index, step)
    raise StrategyDraftValidationError(
        f"equal_length_ray_path_reduction_requires_minimum_expression: {step.step_id}"
    )


def _straightening_endpoint_target_paths(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """返回 split 拉直 recipe 推广的最短线段端点路径。"""
    return (
        _straightening_endpoint_target_path(step, index, STRAIGHTENING_ENDPOINT_POINT_1),
        _straightening_endpoint_target_path(step, index, STRAIGHTENING_ENDPOINT_POINT_2),
    )


def _straightening_endpoint_target_path(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    semantic_name: str,
) -> str:
    """优先使用 step 显式 produced endpoint fact 的 valid_scope。"""
    for produced in step.produces:
        if (
            _produced_output_type(produced, index.handle_registry) == "Point"
            and _semantic_name(produced.handle) == semantic_name
        ):
            return _target_path_for_produced(produced, "Point", index, step)
    return _scoped_output_path(index.context, step.scope_id, semantic_name)


def _straightening_endpoint_handles_from_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str] | None:
    """从 step reads 中读取前序拉直 recipe 暴露的 endpoint facts。"""
    candidates: list[tuple[str, str]] = []
    for handle in step.reads:
        semantic_name = _semantic_name(handle)
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "Point":
            continue
        candidates.append((semantic_name, handle))
    return collect_straightening_endpoint_handles(candidates)


def _straightening_minimum_fixed_points(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """从 StepIntent reads 中读取将军饮马最短距离的两个固定端点。"""
    candidates: list[str] = []
    for handle in step.reads:
        if handle.startswith("point:"):
            try:
                _point_value_path_for_step(handle, step, index)
            except StrategyDraftValidationError:
                continue
            candidates.append(handle)
            continue
        point_handle = _point_handle_from_point_state_fact(handle, step, index)
        if point_handle is not None:
            candidates.append(point_handle)
    if len(_unique_ordered(candidates)) < 2:
        candidates.extend(_square_reduced_path_fixed_points(step, index))
    unique = _unique_ordered(candidates)
    if len(unique) < 2:
        raise StrategyDraftValidationError(
            f"broken_path_straightening_minimum_requires_two_fixed_points: {step.step_id}"
        )
    return unique[0], unique[1]


def _point_handle_from_point_state_fact(
    handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """把 ``fact:*:<Point>_coord*`` 这类 Point 状态反推为点实体 handle。"""
    if not handle.startswith("fact:"):
        return None
    binding = index.bindings.get(handle)
    if binding is None or binding.value_type != "Point":
        return None
    point_name = _point_name_from_point_state_semantic(_semantic_name(handle))
    if point_name is None:
        return None
    try:
        return index.point_handle_by_name(point_name, step=step)
    except StrategyDraftValidationError:
        return None


def _square_reduced_path_fixed_points(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """从 square 降维结构 fact 推断将军饮马的两个固定端点。

    该推断只依赖结构化 facts：
    - square 的有序顶点给出降维后路径的第一个固定点；
    - midpoint_definition、square_center 与 path_minimum_target 的 path 项共同确定
      另一个固定点。
    """
    if not any(
        index.bindings.get(handle) is not None
        and index.bindings[handle].value_type == "PathTransformation"
        for handle in step.reads
    ):
        return []
    try:
        square_fact = index.fact_handle_by_type("square", step=step)
        midpoint_fact = index.fact_handle_by_type("midpoint_definition", step=step)
        center_fact = index.fact_handle_by_type("square_center", step=step)
        target_fact = index.fact_handle_by_type("path_minimum_target", step=step)
    except StrategyDraftValidationError:
        return []

    square_payload = index.fact_payload(square_fact)
    vertices = square_payload.get("vertices")
    if not isinstance(vertices, list) or not vertices:
        return []
    first_fixed = str(vertices[0])
    try:
        midpoint = _payload_handle(index.fact_payload(midpoint_fact), "point", context=midpoint_fact)
        center = _payload_handle(index.fact_payload(center_fact), "point", context=center_fact)
        terms = _path_target_terms(index.fact_payload(target_fact), step=step, index=index, context=target_fact)
    except StrategyDraftValidationError:
        return []
    second_fixed = _fixed_endpoint_from_center_midpoint_path(
        terms,
        center=center,
        midpoint=midpoint,
    )
    if second_fixed is None:
        return []
    return [first_fixed, second_fixed]


def _fixed_endpoint_from_center_midpoint_path(
    terms: list[tuple[str, str]],
    *,
    center: str,
    midpoint: str,
) -> str | None:
    """从 ``center-midpoint`` 与 ``midpoint-fixed`` 相邻路径项中找 fixed endpoint。"""
    has_center_midpoint_term = any(
        set(term) == {center, midpoint}
        for term in terms
    )
    if not has_center_midpoint_term:
        return None
    candidates = [
        _other_endpoint_handle(term, midpoint)
        for term in terms
        if midpoint in term and center not in term
    ]
    unique = _unique_ordered(candidates)
    if len(unique) == 1:
        return unique[0]
    return None


def _visible_point_state_path_for_name(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """读取同名可见 Point 状态 fact/answer path；多候选时不猜。"""
    candidates: list[str] = []
    for handle, binding in sorted(index.bindings.items()):
        if not handle.startswith("fact:") and not handle.startswith("answer:"):
            continue
        if binding.value_type != "Point":
            continue
        try:
            if not index.context.is_visible(step.scope_id, _binding_scope(binding.path)):
                continue
        except Exception:
            continue
        semantic_name = _point_state_semantic_name(handle)
        if semantic_name is None:
            continue
        if _point_name_from_point_state_semantic(semantic_name) != point_name:
            continue
        candidates.append(binding.path)
    unique = _unique_ordered(candidates)
    if len(unique) == 1:
        return unique[0]
    return None


def _point_state_semantic_name(handle: str) -> str | None:
    """读取 Point 状态 handle 的语义名，兼容 ``fact:`` 和 ``answer:`` 格式。"""
    if handle.startswith("answer:"):
        return _answer_semantic_name(handle)
    try:
        return _semantic_name(handle)
    except StrategyDraftValidationError:
        return None


def _scoped_output_path(context: RuntimeContext, scope_id: str, key: str) -> str:
    """生成某个 scope 下的 outputs path。"""
    return _runtime_path_for_scope(context, scope_id, "outputs", key)


def _parameter_output_key_from_symbol_path(symbol_path: str) -> str:
    """从参数符号 ContextPath 读取输出 key。

    curve-candidate 类 recipe 会把反求出的参数值 promote 到当前 scope 的
    ``outputs.<symbol>``。这里必须从实际绑定到的参数符号推导，不能假设参数名
    一定是 ``b``。
    """
    path = ContextPath.parse(symbol_path)
    if path.container != "symbols":
        raise StrategyDraftValidationError(
            f"parameter_symbol_path_must_point_to_symbols: {symbol_path}"
        )
    return path.key

def _unique_declarations(declarations: list[Any]) -> list[Any]:
    """按 path 去重 declaration，并保持首次出现顺序。"""
    result: list[Any] = []
    seen: set[str] = set()
    for declaration in declarations:
        path = getattr(declaration, "path", None)
        if not isinstance(path, str):
            continue
        if path in seen:
            continue
        seen.add(path)
        result.append(declaration)
    return result

def _auto_created_recipe_point(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> CreatedEntity:
    """Defensive fallback for recipe-required auxiliary PointRef targets."""
    scope_id = _auto_created_recipe_point_scope(step)
    handle = fresh_auxiliary_point_handle(
        scope_id,
        (
            set(index.bindings)
            | set(index.declarations)
            | set(index.handle_registry.entity_handles)
        ),
    )
    if handle is not None:
        return CreatedEntity(
            handle=handle,
            entity_type="point",
            valid_scope=scope_id,
            description=f"{step.recipe_hint or step.step_id} 自动创建的辅助点",
        )
    raise StrategyDraftValidationError(
        f"auxiliary_point_handle_exhausted: {step.step_id}"
    )

def _auto_created_recipe_point_scope(step: StepIntent) -> str:
    """Match auto-created helper visibility to the recipe's public output scope."""
    for item in step.produces:
        if item.handle.startswith("answer:"):
            continue
        if item.valid_scope:
            return item.valid_scope
    return step.scope_id

def _temp(step_id: str, output_key: str) -> str:
    """生成 step 临时输出路径。"""
    return f"$step.{step_id}.temp.{output_key}"


def _prep_trigger_matches(
    prep: MethodPrepInvocationSpec,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 prep rule 是否需要触发。"""
    selector = prep.trigger_selector
    if selector.startswith("missing_readable_type:"):
        value_type = selector.split(":", 1)[1]
        return _path_for_readable_type_or_none(index, step, value_type) is None
    if selector.startswith("missing_readable_type_with_quadratic_source:"):
        value_type = selector.split(":", 1)[1]
        return (
            _path_for_readable_type_or_none(index, step, value_type) is None
            and _step_has_quadratic_source_reads(step, index)
        )
    raise StrategyDraftValidationError(f"prep_trigger_selector_missing: {selector}")


def _step_has_quadratic_source_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 step 是否具备临时构造 Parabola 的题设来源。"""
    has_function = any(handle.startswith("function:") for handle in step.reads)
    if not has_function:
        return False
    source_fact_types = {
        "symbol_value",
        "coefficient_relation",
        "point_on_curve",
        "point_coordinate",
    }
    return any(index.handle_registry.fact_types.get(handle) in source_fact_types for handle in step.reads)


def _prep_outputs(
    step: StepIntent,
    prep: MethodPrepInvocationSpec,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """按 prep rule 生成临时输出路径。"""
    outputs: dict[str, str] = {}
    for output_name, scoped_key in prep.output_aliases:
        output_key = output_name if scoped_key == "__local_only__" else scoped_key
        outputs[output_name] = _temp(step.step_id, output_key)
    if not outputs:
        raise StrategyDraftValidationError(
            f"prep_outputs_missing: {prep.method_id}:{step.step_id}"
        )
    return outputs


def _method_outputs_for_step(
    method_id: str,
    step: StepIntent,
    spec_outputs: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
    binding_rules: MethodBindingRuleRegistry,
) -> dict[str, str]:
    """为 invocation 生成输出路径，避免声明 method 不会实际返回的可选输出。"""
    output_names: list[str] = []
    for produced in step.produces:
        output_name = _output_key_for_produced(method_id, produced, spec_outputs, step, index)
        if output_name is not None:
            output_names.append(output_name)
    rule = binding_rules.rule_for(method_id)
    if rule is not None:
        for output_name in rule.always_emit_outputs:
            _append_declared_output_name(output_names, output_name, method_id, spec_outputs)
        for companion in rule.companion_outputs:
            _append_declared_output_name(
                output_names,
                companion.output_name,
                method_id,
                spec_outputs,
            )
    if not output_names:
        output_names = list(spec_outputs)
    return {name: _temp(step.step_id, name) for name in _unique_ordered(output_names)}


def _append_declared_output_name(
    output_names: list[str],
    output_name: str,
    method_id: str,
    spec_outputs: dict[str, str],
) -> None:
    """追加 FamilySpec 声明的 method output，并校验它确实由 MethodSpec 提供。"""
    if output_name not in spec_outputs:
        raise StrategyDraftValidationError(
            f"method_output_missing: {method_id}.{output_name}"
        )
    output_names.append(output_name)

def _output_key_for_produced(
    method_id: str,
    produced: ProducedFact,
    spec_outputs: dict[str, str],
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """把 produces handle 映射到某个 method output key。"""
    output_type = _produced_output_type(produced, index.handle_registry)
    if method_id == "distance_between_points":
        if output_type == "MinimumExpression":
            return "evaluated_distance" if _parameter_value_handle(step, index) else "distance"
    preferred_by_type = {
        "Point": ("axis_point", "midpoint", "intersection", "selected_point", "auxiliary_point"),
        "PointList": ("candidates", "filtered_candidates"),
        "Line": ("auxiliary_locus", "line"),
        "Parabola": ("parabola",),
        "Coefficients": ("coefficients",),
        "ParameterValue": ("parameter_value",),
        "MinimumExpression": ("minimum_expression", "distance", "evaluated_distance", "minimum_value"),
        "PathTransformation": ("path_transformation",),
        "StraighteningCandidate": ("selected_candidate",),
    }
    for key in preferred_by_type.get(str(output_type), ()):
        if key in spec_outputs:
            return key
    for key, current_type in spec_outputs.items():
        if current_type == output_type:
            return key
    return next(iter(spec_outputs), None)

def _promote_outputs_for_step(
    step: StepIntent,
    method_id: str,
    outputs: dict[str, str],
    output_types: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
    binding_rules: MethodBindingRuleRegistry,
) -> dict[str, str]:
    """根据 produces/answer 自动生成 promote_outputs。"""
    promote: dict[str, str] = {}
    source_to_produced: dict[str, list[ProducedFact]] = {}
    for produced in step.produces:
        output_name = _output_key_for_produced(method_id, produced, output_types, step, index)
        if output_name is None or output_name not in outputs:
            continue
        target = _target_path_for_produced(produced, output_types[output_name], index, step)
        _ensure_declaration_for_promote_target(target, output_types[output_name], index)
        source = outputs[output_name]
        source_to_produced.setdefault(source, []).append(produced)
        # 同一个 method output 可能同时服务最终答案和可复用 fact alias。
        # promote 只能写一个目标，因此优先落到 answer target；普通 fact 后续注册到
        # 同一条 runtime path，避免 answer 被 alias 覆盖后 ResultBuilder 找不到答案。
        if source not in promote or produced.handle.startswith("answer:"):
            promote[source] = target
    _validate_no_ambiguous_multi_produced_output_aliases(
        step,
        method_id,
        source_to_produced,
        index,
    )
    _add_companion_promotes(step, method_id, outputs, promote, output_types, index, binding_rules)
    if not promote and outputs:
        first_key, first_path = next(iter(outputs.items()))
        promote[first_path] = _scoped_output_path(index.context, step.scope_id, first_key)
    return promote

def _validate_no_ambiguous_multi_produced_output_aliases(
    step: StepIntent,
    method_id: str,
    source_to_produced: Mapping[str, list[ProducedFact]],
    index: CanonicalRuntimeBindingIndex,
) -> None:
    """防止 single method output 被多个不同语义 fact 静默共用。

    answer + fact alias 是合法的：同一个 runtime output 可同时作为答案与后续
    可复用 fact。两个非 answer fact 若语义名不同，则表示 LLM 把多次函数调用
    合并成了一个 StepIntent，必须在 normalizer 或 retry 中拆开。
    """
    for source, produced_items in source_to_produced.items():
        if len(produced_items) < 2:
            continue
        non_answer_items = [
            item for item in produced_items
            if not item.handle.startswith("answer:")
        ]
        if len(non_answer_items) < 2:
            continue
        identities = {
            _produced_output_alias_identity(item, index)
            for item in non_answer_items
        }
        if len(identities) <= 1:
            continue
        output_key = source.rsplit(".", 1)[-1]
        handles = ",".join(item.handle for item in non_answer_items)
        raise StrategyDraftValidationError(
            "ambiguous_multi_produced_single_output:"
            f"step={step.step_id},method={method_id},output={output_key},handles={handles}"
        )

def _produced_output_alias_identity(
    produced: ProducedFact,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """用于判断多个 produced fact 是否只是同一状态的 alias。"""
    output_type = _produced_output_type(produced, index.handle_registry)
    return f"{output_type}:{_semantic_name(produced.handle)}"

def _add_companion_promotes(
    step: StepIntent,
    method_id: str,
    outputs: dict[str, str],
    promote: dict[str, str],
    output_types: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
    binding_rules: MethodBindingRuleRegistry,
) -> None:
    """为 method 固有伴随输出补 promote target。

    这些输出不是 LLM 的独立结论，而是同一个 method 调用天然产生的中间几何对象。
    将它们注册为 runtime alias 可以减少 prompt 负担，同时仍由 method checks 验证。
    """
    rule = binding_rules.rule_for(method_id)
    if rule is None:
        return
    for companion in rule.companion_outputs:
        source = outputs.get(companion.output_name)
        if source is None:
            continue
        target = _companion_target_path(step, companion, index)
        output_type = _companion_output_type(companion, method_id, output_types)
        _ensure_declaration_for_promote_target(target, output_type, index)
        promote.setdefault(source, target)

def _companion_registrations_for_step(
    step: StepIntent,
    method_id: str,
    outputs: dict[str, str],
    promote: dict[str, str],
    output_types: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
    binding_rules: MethodBindingRuleRegistry,
) -> list[RuntimeHandleBinding]:
    """注册 method 伴随输出的可读 alias。"""
    rule = binding_rules.rule_for(method_id)
    if rule is None:
        return []
    result: list[RuntimeHandleBinding] = []
    for companion in rule.companion_outputs:
        source = outputs.get(companion.output_name)
        if source not in promote or companion.registration_selector is None:
            continue
        handle = _companion_registration_handle(step, companion, index)
        output_type = _companion_output_type(companion, method_id, output_types)
        result.append(
            RuntimeHandleBinding(
                handle,
                promote[source],
                output_type,
                f"step:{step.step_id}",
            )
        )
    return result


def _companion_target_path(
    step: StepIntent,
    companion: MethodCompanionOutputSpec,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """根据 companion output selector 生成 promote target。"""
    selector = companion.target_selector
    if selector.startswith("answer_scope_output:"):
        key = selector.split(":", 1)[1]
        return _scoped_output_path(index.context, _answer_target_scope_from_step(step, index), key)
    if selector.startswith("scope_output:"):
        key = selector.split(":", 1)[1]
        return _scoped_output_path(index.context, step.scope_id, key)
    if selector == "weighted_path_auxiliary_point":
        auxiliary_handle = _weighted_auxiliary_point_handle_for_step(step, index)
        return index.path_for(auxiliary_handle, expected_type="PointRef")
    raise StrategyDraftValidationError(f"companion_target_selector_missing: {selector}")


def _answer_target_scope_from_step(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """从 QuestionGoal target_path 读取 answer 实际写入 scope。"""
    handles = [step.target, *(item.handle for item in step.produces)]
    for handle in handles:
        if not handle.startswith("answer:"):
            continue
        goal = index.question_goals.get(handle)
        if goal is not None:
            return ContextPath.parse(goal.target_path).scope_id
    return _answer_scope_from_step(step)


def _companion_registration_handle(
    step: StepIntent,
    companion: MethodCompanionOutputSpec,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """根据 companion registration selector 生成 runtime handle。"""
    selector = companion.registration_selector
    if selector is None:
        raise StrategyDraftValidationError(
            f"companion_registration_selector_missing: {companion.output_name}"
        )
    if selector.startswith("runtime_step_output:"):
        key = selector.split(":", 1)[1]
        return f"runtime:{step.step_id}:{key}"
    if selector == "weighted_path_auxiliary_point":
        return _weighted_auxiliary_point_handle_for_step(step, index)
    raise StrategyDraftValidationError(f"companion_registration_selector_missing: {selector}")


def _companion_output_type(
    companion: MethodCompanionOutputSpec,
    method_id: str,
    output_types: dict[str, str],
) -> str:
    """从 MethodSpec 读取 companion output 的 runtime 类型。"""
    try:
        return output_types[companion.output_name]
    except KeyError as exc:
        raise StrategyDraftValidationError(
            f"companion_output_missing: {method_id}.{companion.output_name}"
        ) from exc

def _produced_registrations(
    step: StepIntent,
    method_id: str,
    promote: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
) -> list[tuple[str, str, str]]:
    """返回 ``(handle, output_key, promoted_path)`` 注册信息。"""
    result: list[tuple[str, str, str]] = []
    for produced in step.produces:
        output_key = _output_key_from_promote_source(
            step.step_id,
            produced,
            method_id,
            promote,
            index,
        )
        if output_key is None:
            continue
        source = _temp(step.step_id, output_key)
        if source in promote:
            result.append((produced.handle, output_key, promote[source]))
    return result

def _output_key_from_promote_source(
    step_id: str,
    produced: ProducedFact,
    method_id: str,
    promote: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从 promote source 中反推 output_key。"""
    # 这里的目标只是生成 alias 注册；如果无法精确反推，后续 step 会在 binding 阶段报错。
    candidates = [
        source.removeprefix(f"$step.{step_id}.temp.")
        for source in promote
        if source.startswith(f"$step.{step_id}.temp.")
    ]
    if len(candidates) == 1:
        return candidates[0]
    structured = _structured_output_key_from_produced(
        produced,
        method_id,
        candidates,
        index,
    )
    if structured is not None:
        return structured
    text = produced.handle + "\n" + produced.description
    if "parabola" in text or "抛物线" in text:
        return "parabola" if "parabola" in candidates else None
    if "minimum" in text or "最小值" in text:
        if method_id == "distance_between_points" and "evaluated_distance" in candidates:
            return "evaluated_distance"
        return "distance" if "distance" in candidates else None
    if "m_value" in text or "参数" in text:
        return "parameter_value" if "parameter_value" in candidates else None
    return candidates[0] if candidates else None

def _structured_output_key_from_produced(
    produced: ProducedFact,
    method_id: str,
    candidates: list[str],
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """优先使用 handle / answer type / fact type 反推 output key。"""
    if not candidates:
        return None
    if produced.handle.startswith("answer:"):
        semantic_name = _answer_semantic_name(produced.handle)
        value_type = index.answer_value_types.get(produced.handle)
        if semantic_name in candidates:
            return semantic_name
        if semantic_name == "parabola" or value_type == "Parabola":
            return _first_candidate(candidates, "parabola")
        if semantic_name in {"minimum_value", "min_value"} or value_type == "MinimumExpression":
            return _minimum_expression_output_key(method_id, candidates, prefer_evaluated=True)
        if value_type == "Point":
            if (
                produced.output_type is not None
                and produced.output_type != value_type
                and answer_output_type_compatible(value_type, produced.output_type)
            ):
                return _first_candidate(candidates, "candidates", "filtered_candidates")
            return _first_candidate(
                candidates,
                semantic_name,
                "axis_point",
                "midpoint",
                "intersection",
                "selected_point",
                "auxiliary_point",
                "point",
            )
    fact_type = index.fact_types.get(produced.handle)
    semantic_name = _semantic_name(produced.handle) if produced.handle.startswith("fact:") else ""
    output_type = _produced_output_type(produced, index.handle_registry)
    if _is_parameter_output_semantic_name(semantic_name) or fact_type == "parameter_value":
        return _first_candidate(candidates, "parameter_value")
    if semantic_name in {"parabola", "parabola_expr", "parabola_expression"} or output_type == "Parabola":
        return _first_candidate(candidates, "parabola")
    if output_type == "Coefficients":
        return _first_candidate(candidates, "coefficients")
    if (
        fact_type in {"minimum_expression", "minimum_value_expression"}
        or output_type == "MinimumExpression"
    ):
        return _minimum_expression_output_key(method_id, candidates, prefer_evaluated=False)
    if output_type == "Point":
        return _first_candidate(
            candidates,
            semantic_name,
            "axis_point",
            "midpoint",
            "intersection",
            "selected_point",
            "auxiliary_point",
            "point",
        )
    if output_type == "PointList":
        return _first_candidate(candidates, "candidates", "filtered_candidates")
    if output_type == "Line":
        return _first_candidate(candidates, semantic_name, "auxiliary_locus", "line")
    if output_type == "PathTransformation":
        return _first_candidate(candidates, semantic_name, "path_transformation")
    return None

def _answer_semantic_name(handle: str) -> str:
    """读取 ``answer:<scope>.<key>`` 的 key 部分。"""
    if not handle.startswith("answer:"):
        return ""
    value = handle.split(":", 1)[1]
    if "." not in value:
        return value
    return value.split(".", 1)[1]

def _is_parameter_output_semantic_name(name: str) -> bool:
    """判断 produced fact semantic name 是否表示参数值。"""
    if name in {"m_value", "a_value", "b_value", "c_value", "parameter_value"}:
        return True
    return bool(re.fullmatch(r"(?:parameter_)?[a-z][a-z0-9]*_(?:parameter_)?value", name))

def _minimum_expression_output_key(
    method_id: str,
    candidates: list[str],
    *,
    prefer_evaluated: bool,
) -> str | None:
    """在 MinimumExpression 相关候选中选择 output key。"""
    if prefer_evaluated and method_id == "distance_between_points":
        key = _first_candidate(candidates, "evaluated_distance")
        if key is not None:
            return key
    return _first_candidate(candidates, "minimum_expression", "distance", "evaluated_distance", "minimum_value")

def _first_candidate(candidates: list[str], *keys: str) -> str | None:
    """按优先级返回第一个存在的候选 key。"""
    for key in keys:
        if key in candidates:
            return key
    return None

def _target_path_for_produced(
    produced: ProducedFact,
    output_type: str,
    index: CanonicalRuntimeBindingIndex,
    step: StepIntent,
) -> str:
    """把 produces handle 映射到 runtime promote target path。"""
    if produced.handle.startswith("answer:"):
        goal = index.question_goals.get(produced.handle)
        if (
            goal is not None
            and goal.value_type != output_type
            and answer_output_type_compatible(goal.value_type, output_type)
        ):
            answer_key = _answer_semantic_name(produced.handle) or goal.answer_key
            return _scoped_output_path(index.context, produced.valid_scope, answer_key)
        return index.path_for(produced.handle)
    fact_type = index.fact_types.get(produced.handle)
    semantic_name = _semantic_name(produced.handle)
    if fact_type == "point_coordinate" or _is_point_coordinate_semantic_name(semantic_name):
        point_handle = _point_handle_for_produced_point(produced, index, step)
        if point_handle is None:
            return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
        if _handle_scope(point_handle) != produced.valid_scope:
            return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
        return index.point_ref_path_for(point_handle)
    if output_type == "Point":
        point_handle = _point_handle_for_produced_point(produced, index, step)
        if point_handle is None:
            return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
        if _handle_scope(point_handle) != produced.valid_scope:
            return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
        return index.point_ref_path_for(point_handle)
    if output_type == "PointList":
        return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
    if output_type == "Line":
        return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
    if output_type == "ParameterValue":
        symbol = semantic_name.split("_", 1)[0]
        return _scoped_output_path(index.context, produced.valid_scope, symbol)
    if output_type == "PathTransformation":
        return _scoped_output_path(index.context, produced.valid_scope, "path_transformation")
    if output_type == "StraighteningCandidate":
        return _scoped_output_path(index.context, produced.valid_scope, "straightening_candidate")
    if output_type == "MinimumExpression":
        key = "minimum_expression"
        if produced.handle.startswith("answer:"):
            return index.path_for(produced.handle)
        return _scoped_output_path(index.context, produced.valid_scope, key)
    if output_type == "Parabola":
        if produced.handle.startswith("fact:"):
            return _scoped_output_path(index.context, produced.valid_scope, _semantic_name(produced.handle))
        return _scoped_output_path(index.context, produced.valid_scope, "parabola")
    if output_type == "Coefficients":
        if produced.handle.startswith("fact:"):
            return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
        return _scoped_output_path(index.context, produced.valid_scope, "coefficients")
    return _scoped_output_path(index.context, produced.valid_scope, semantic_name)


def _is_point_coordinate_semantic_name(name: str) -> bool:
    """判断 produced semantic name 是否表示某点坐标 fact。"""
    return bool(
        re.fullmatch(
            r"[A-Za-z][A-Za-z0-9]*_"
            r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate)"
            r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
            name,
            flags=re.IGNORECASE,
        )
    )


def _point_name_from_point_state_semantic(name: str) -> str | None:
    """从 ``E_param_coord`` / ``M_coordinate_expr`` 中读取点名。"""
    match = re.fullmatch(
        r"(?:optimal|minimum|extremal)_?(?P<point>[A-Za-z][A-Za-z0-9]*)",
        name,
        flags=re.IGNORECASE,
    )
    if match is not None:
        point = match.group("point")
        return point[:1].upper() + point[1:]
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_"
        r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate)"
        r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
        name,
        flags=re.IGNORECASE,
    )
    if match is not None:
        return match.group("point")
    return None


def _point_handle_for_produced_point(
    produced: ProducedFact,
    index: CanonicalRuntimeBindingIndex,
    step: StepIntent,
) -> str | None:
    """为 Point 产物寻找对应 canonical point handle。

    优先接受 step.target 中完整的 ``point:<scope>:<name>``；其次对
    ``quadratic_y_axis_intercept_point`` 这类定义点 method，按 Entity
    ``definition`` 找唯一目标点；最后才按 ``<Point>_coordinate`` 的语义名解析。
    """
    target_handle = _point_handle_from_text(step.target, index)
    if target_handle is not None:
        return target_handle
    if step.recipe_hint == "quadratic_y_axis_intercept_point":
        target = _unique_point_handle_by_definition("y_axis_intercept", step, index)
        if target is not None:
            return target
    semantic_name = _semantic_name(produced.handle)
    if _is_point_coordinate_semantic_name(semantic_name):
        point_name = _point_name_from_point_state_semantic(semantic_name)
        if point_name is None:
            return None
        return index.point_handle_by_name(point_name, step=step)
    point_name = _point_name_from_point_state_semantic(semantic_name)
    if point_name is not None:
        return index.point_handle_by_name(point_name, step=step)
    return None


def _point_handle_from_text(
    text: str,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从文本中读取完整 canonical point handle。"""
    for match in re.finditer(r"point:[A-Za-z0-9_]+:[A-Za-z0-9_]+", text):
        handle = match.group(0)
        if handle in index.bindings and handle.startswith("point:"):
            return handle
    return None


def _unique_point_handle_by_definition(
    definition: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """按 Entity definition 找唯一可见点。"""
    candidates = [
        handle
        for handle in index.entity_handles("point", step=step)
        if index.handle_registry.entity_payloads.get(handle, {}).get("definition") == definition
    ]
    unique = _unique_ordered(candidates)
    return unique[0] if len(unique) == 1 else None


def _ensure_declaration_for_promote_target(
    target_path: str,
    output_type: str,
    index: CanonicalRuntimeBindingIndex,
) -> None:
    """若 Point 输出要写入尚不存在的 points path，则补 planner declaration。"""
    if output_type != "Point":
        return
    parsed = ContextPath.parse(target_path)
    if parsed.container != "points" or _context_path_exists(index.context, target_path):
        return
    declaration = _point_declaration_for_path(
        index.context,
        target_path,
        definition="planner_result_point",
    )
    index.declarations[target_path] = declaration

def _step_parent_scope(step: StepIntent, promote: dict[str, str]) -> str:
    """确定 StepPlan 的父 scope。"""
    if promote:
        target = ContextPath.parse(next(iter(promote.values())))
        return step.scope_id if target.scope_id == "problem" else step.scope_id
    return step.scope_id

def _method_output_union(
    method_ids: tuple[str, ...],
    method_specs: MethodSpecRegistry,
) -> tuple[str, ...]:
    """把 recipe 内部 method outputs 合并成类型集合。"""
    output_types: list[str] = []
    for method_id in method_ids:
        try:
            spec = method_specs.require(method_id)
        except KeyError:
            continue
        output_types.extend(spec.outputs.values())
    return tuple(_unique_ordered(output_types))


def _execution_blocker_code(candidate_errors: list[str]) -> str:
    """把候选执行错误压成稳定短错误码。"""
    text = "\n".join(candidate_errors)
    if "unsupported_direction_point_utility" in text:
        return "unsupported_direction_point_utility"
    if "final_point_requires_square_recovery" in text:
        return "final_point_requires_square_recovery"
    if "missing_required_runtime_fact" in text:
        return "missing_required_runtime_fact"
    if "line_parabola_line_points_not_found" in text:
        return "missing_line_parabola_inputs"
    if "binding_not_found" in text:
        return "binding_not_found"
    if "binding_type_mismatch" in text:
        return "binding_type_mismatch"
    if "duplicate_point_coordinate_fact" in text:
        return "duplicate_point_coordinate_fact"
    if "distance_points_not_found" in text:
        return "distance_points_not_found"
    if "method_binding_rule_missing" in text:
        return "missing_binding_rule"
    if not candidate_errors:
        return "no_trial_candidate"
    return "recipe_trial_step_failed"


def _execution_blocker_message(step_id: str, candidate_errors: list[str]) -> str:
    """生成 previous_attempts 可读的 blocker 说明。"""
    if not candidate_errors:
        return f"step {step_id} has no executable trial candidate"
    return f"step {step_id} failed executable trial: " + "; ".join(candidate_errors[:3])


def _execution_blocker_capability_id(candidate_errors: list[str]) -> str | None:
    """从候选错误前缀提取最可能的 capability id。"""
    for error in candidate_errors:
        prefix, separator, _rest = error.partition(":")
        if separator and prefix:
            return prefix.strip()
    return None


def _execution_blocker_missing_runtime_type(candidate_errors: list[str]) -> str | None:
    """从 binding_type_not_found 错误中提取缺失 runtime 类型。"""
    marker = "type="
    for error in candidate_errors:
        if "binding_type_not_found" not in error or marker not in error:
            continue
        value = error.split(marker, 1)[1].split(",", 1)[0].split(";", 1)[0].strip()
        if value:
            return value
    return None


def _candidate_warnings_for_report(report: StepIntentResolutionStepReport | None) -> list[str]:
    """把 resolver warnings 安全带到 runtime diagnostic。"""
    if report is None:
        return []
    return [f"candidate_warning:{warning}" for warning in report.warnings]


def _candidate_error_for_exception(
    *,
    step: StepIntent,
    capability_id: str,
    exc: Exception,
    planner_insights: tuple[StepIntentPlannerInsight, ...],
    handle_registry: CanonicalHandleRegistry,
) -> str:
    """把单个 capability trial 异常压成 LLM 可修复的候选错误。"""
    message = str(exc)
    if (
        capability_id == "evaluate_point_at_parameter"
        and "missing required input: parameter" in message
        and _step_produces_point_answer(step, handle_registry)
        and any(insight.output_type == "PathTransformation" for insight in planner_insights)
    ):
        return "evaluate_point_at_parameter: final_point_requires_square_recovery"
    return f"{capability_id}: {message}"


def _step_produces_point_answer(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否正在 produces Point answer。"""
    return any(
        produced.handle.startswith("answer:")
        and _produced_output_type(produced, handle_registry) == "Point"
        for produced in step.produces
    )
