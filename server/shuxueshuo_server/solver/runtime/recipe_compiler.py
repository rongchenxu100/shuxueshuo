"""StepIntent recipe/method 编译器。

本模块把已校验的 StepIntentDraft 编译成 PlannerOutput，并通过 prefix dry-run
选择可执行的 recipe/method 候选。
"""

from __future__ import annotations

from dataclasses import dataclass
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
    _handle_scope,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    StepIntent,
    StepIntentDraft,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    StepIntentCandidateResolver,
    _produced_output_type,
    _unique_ordered,
)
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    RuntimeHandleBinding,
    _context_path_exists,
    _point_declaration_for_path,
    _runtime_path_for_scope,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    MethodBindingRuleRegistry,
    _answer_scope_from_step,
    _created_point_handle,
    _curve_candidate_target_handle,
    _first_pointref_handle,
    _moving_membership_for_straightening,
    _parameter_value_handle,
    _path_for_first_type,
    _path_for_readable_type,
    _path_for_readable_type_or_none,
    _point_output_handle,
    _right_angle_roles,
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
                    inputs=self.binding_rules.bind(prep.method_id, step, self.index),
                    outputs=outputs,
                )
            )
            for output_name, scoped_key in prep.output_aliases:
                output_path = outputs.get(output_name)
                if output_path is None:
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
        if not resolution_report.ok:
            raise StrategyDraftValidationError(
                "recipe_trial_candidate_resolution_failed: "
                + json.dumps(resolution_report.errors, ensure_ascii=False)
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
        return compiler.compile(draft)

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

    def compile(self, draft: StepIntentDraft) -> PlannerOutput:
        """按 LLM 输出顺序编译并 dry-run prefix。"""
        plans: list[StepPlan] = []
        declarations: list[Any] = []
        seen_plan_keys: set[str] = set()
        for step in draft.steps:
            candidate_errors: list[str] = []
            for capability_id in self._capability_ids_for_step(step):
                try:
                    compiled = self._compile_with_capability(step, capability_id)
                    key = f"{compiled.plan.step_id}:{compiled.plan.goal.target_path}"
                    if key in seen_plan_keys:
                        continue
                    trial_declarations = _unique_declarations([*declarations, *compiled.declarations])
                    self._dry_run_prefix(trial_declarations, [*plans, compiled.plan])
                    declarations = trial_declarations
                    plans.append(compiled.plan)
                    seen_plan_keys.add(key)
                    self._apply_registrations(compiled)
                    break
                except Exception as exc:
                    candidate_errors.append(f"{capability_id}: {exc}")
            else:
                raise StrategyDraftValidationError(
                    f"recipe_trial_step_failed: step={step.step_id}, errors={candidate_errors}"
                )
        return PlannerOutput(context_declarations=declarations, step_plans=plans)

    def _capability_ids_for_step(self, step: StepIntent) -> list[str]:
        """返回某个 step 的候选 capability 顺序。"""
        report = self.step_reports.get(step.step_id)
        candidates: list[str] = []
        if step.recipe_hint:
            return [step.recipe_hint]
        if report is not None and report.selected_capability_id:
            candidates.append(report.selected_capability_id)
        if report is not None:
            candidates.extend(candidate.capability_id for candidate in report.candidates if candidate.ok)
        return _unique_ordered(candidates)

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
            auxiliary_path = self.index.path_for(_first_pointref_handle(step, self.index), expected_type="PointRef")
        candidates = _temp(step.step_id, "candidates")
        selected = _temp(step.step_id, "selected_candidate")
        auxiliary = _temp(step.step_id, "auxiliary_point")
        moving_membership = _moving_membership_for_straightening(step, self.index)
        fixed_1, fixed_2, line_1, line_2 = _straightening_point_roles(step, self.index)
        invocations = [
            MethodInvocation(
                invocation_id=f"{step.step_id}.broken_path_straightening_candidates",
                method_id="broken_path_straightening_candidates",
                scope=step.step_id,
                inputs={
                    "path_transformation": _path_for_first_type(self.index, step, "PathTransformation"),
                    "moving_point_membership": self.index.path_for(moving_membership, expected_type="Condition"),
                    "fixed_point_1": self.index.path_for(fixed_1, expected_type="Point"),
                    "fixed_point_2": self.index.path_for(fixed_2, expected_type="Point"),
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
                outputs={"selected_candidate": selected, "auxiliary_point": auxiliary},
            ),
        ]
        promote = {
            candidates: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidates"),
            selected: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidate"),
            auxiliary: auxiliary_path,
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
        registrations = [
            RuntimeHandleBinding(item.handle, promote[selected], "StraighteningCandidate", f"step:{step.step_id}")
            for item in step.produces
        ]
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

    def _dry_run_prefix(self, declarations: list[Any], plans: list[StepPlan]) -> None:
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


DEFAULT_RECIPE_COMPILERS: dict[str, RecipeCompileStrategyFn] = {
    "single_method": _compile_single_method_recipe,
    "right_angle_construct_select": _compile_right_angle_construct_select_recipe,
    "curve_candidate_parameter_solve": _compile_curve_candidate_parameter_solve_recipe,
    "straightening_candidates_select": _compile_straightening_candidates_select_recipe,
}


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
    raise StrategyDraftValidationError(f"prep_trigger_selector_missing: {selector}")


def _prep_outputs(
    step: StepIntent,
    prep: MethodPrepInvocationSpec,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """按 prep rule 生成临时输出路径。"""
    outputs: dict[str, str] = {}
    for output_name, scoped_key in prep.output_aliases:
        outputs[output_name] = _temp(step.step_id, scoped_key)
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
    for produced in step.produces:
        output_name = _output_key_for_produced(method_id, produced, output_types, step, index)
        if output_name is None or output_name not in outputs:
            continue
        target = _target_path_for_produced(produced, output_types[output_name], index)
        _ensure_declaration_for_promote_target(target, output_types[output_name], index)
        promote[outputs[output_name]] = target
    _add_companion_promotes(step, method_id, outputs, promote, output_types, index, binding_rules)
    if not promote and outputs:
        first_key, first_path = next(iter(outputs.items()))
        promote[first_path] = _scoped_output_path(index.context, step.scope_id, first_key)
    return promote

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
        return _scoped_output_path(index.context, _answer_scope_from_step(step), key)
    if selector.startswith("scope_output:"):
        key = selector.split(":", 1)[1]
        return _scoped_output_path(index.context, step.scope_id, key)
    if selector == "weighted_path_auxiliary_point":
        auxiliary_handle = _weighted_auxiliary_point_handle_for_step(step, index)
        return index.path_for(auxiliary_handle, expected_type="PointRef")
    raise StrategyDraftValidationError(f"companion_target_selector_missing: {selector}")


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
) -> str:
    """把 produces handle 映射到 runtime promote target path。"""
    if produced.handle.startswith("answer:"):
        return index.path_for(produced.handle)
    fact_type = index.fact_types.get(produced.handle)
    if fact_type == "point_coordinate":
        point_name = _semantic_name(produced.handle).split("_", 1)[0]
        return index.path_for(index.point_handle_by_name(point_name), expected_type="PointRef")
    if output_type == "Point":
        point_name = _semantic_name(produced.handle).split("_", 1)[0]
        return index.path_for(index.point_handle_by_name(point_name), expected_type="PointRef")
    if output_type == "PointList":
        return _scoped_output_path(index.context, produced.valid_scope, _semantic_name(produced.handle))
    if output_type == "Line":
        return _scoped_output_path(index.context, produced.valid_scope, _semantic_name(produced.handle))
    if output_type == "ParameterValue":
        symbol = _semantic_name(produced.handle).split("_", 1)[0]
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
            return _scoped_output_path(index.context, produced.valid_scope, _semantic_name(produced.handle))
        return _scoped_output_path(index.context, produced.valid_scope, "coefficients")
    return _scoped_output_path(index.context, produced.valid_scope, _semantic_name(produced.handle))

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
