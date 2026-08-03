"""Compile typed Functional capabilities into runtime StepPlans."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Callable, Literal, Mapping, Protocol

import sympy as sp

from shuxueshuo_server.solver.family.models import (
    MethodCompanionOutputSpec,
    MethodPrepInvocationSpec,
    RecipeExecutionSpec as FamilyRecipeExecutionSpec,
    SolverFamilySpec,
    StateIdentityPolicy,
    StateWriteMode,
)
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.contracts import (
    PlanTransformerScope,
    PointRef,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    StateSemanticLineage,
    StateSymbolClosureBinding,
    dependent_role_object_ref,
    derived_role_object_ref,
    merge_state_semantic_lineages,
    object_kind_for_runtime_type,
    object_ref_matches_runtime_type,
    state_object_refs_for_role,
    state_kind_for_runtime_type,
)
from shuxueshuo_server.solver.runtime.auxiliary_points import fresh_auxiliary_point_handle
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.condition_roles import (
    ConditionRoleResolver,
    resolve_read_closed_right_angle_inputs,
)
from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
    EqualLengthRayRoleError,
    resolve_equal_length_ray_path_roles,
)
from shuxueshuo_server.solver.runtime._planner_helpers import single_invocation_step
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.macro_specs import (
    MacroAdapterRegistry,
    MacroReturnSpec,
    MacroSpecRegistry,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionReturnSpec,
    FunctionSpec,
    FunctionSpecRegistry,
)
from shuxueshuo_server.solver.runtime.functional_compile_contract import (
    compile_capability_id as _compile_capability_id,
    compile_created_entities as _compile_created_entities,
    compile_input_handles as _compile_input_handles,
    compile_return_outputs as _compile_return_outputs,
    compile_target_handle as _compile_target_handle,
)
from shuxueshuo_server.solver.runtime.binding_selector_semantics import (
    expansion_selector_semantics,
    selector_semantics,
)
from shuxueshuo_server.solver.runtime.models import (
    ContextPath,
    MethodInvocation,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_output_type as _produced_output_type,
    produced_semantic_role,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.path_transformation_state import (
    PathTransformationStateResolver,
    ResolvedPathTransformationRole,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_name,
    _handle_scope,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProjectedFunctionArgBinding,
    ProjectedStateDependency,
    ProjectedStateWrite,
    ProducedFact,
    StateWriteProvenance,
    StrategyDraftValidationError,
    answer_output_type_compatible,
)
from shuxueshuo_server.solver.runtime.straightening_metadata import (
    STRAIGHTENED_ENDPOINT_1,
    STRAIGHTENED_ENDPOINT_2,
    canonical_straightening_endpoint_name,
    collect_straightening_endpoint_handles,
    straightening_endpoint_position,
)
from shuxueshuo_server.solver.runtime.student_symbolic_complexity import (
    analyze_student_symbolic_complexity,
    runtime_free_symbol_names,
)
from shuxueshuo_server.solver.utils import unique_ordered as _unique_ordered
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
    _parameter_value_handle,
    _path_for_readable_type,
    _path_for_readable_type_or_none,
    _point_output_handle,
    _weighted_auxiliary_point_handle_for_step,
    parameter_substitution_pairs_from_reads,
)
from shuxueshuo_server.solver.runtime.functional_symbol_identity import (
    runtime_free_symbol_ids,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    MathObjectId,
    MathObjectRegistry,
)
from shuxueshuo_server.solver.runtime.scalar_result_closure import (
    ScalarResultClosureRegistry,
    close_scalar_plan_output,
)

RecipeCompileStrategyFn = Callable[
    ["_RecipePlanCompiler", "FunctionalCompileStepView", FamilyRecipeExecutionSpec],
    "_CompiledStep",
]


@dataclass(frozen=True)
class _CompiledStep:
    """One Functional capability compiled into a runtime plan fragment."""

    plan: StepPlan
    declarations: tuple[Any, ...] = ()
    registrations: tuple[RuntimeHandleBinding, ...] = ()
    state_write_provenance: tuple[StateWriteProvenance, ...] = ()


@dataclass(frozen=True)
class ExactCompiledStep:
    """One explicitly selected Functional capability."""

    plan: StepPlan
    declarations: tuple[Any, ...] = ()
    state_write_provenance: tuple[StateWriteProvenance, ...] = ()


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

    def build(self, method_id: str, step: FunctionalCompileStepView) -> _PrepInvocationBuildResult:
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
                        apply_constraint_analyzer=False,
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


def _projected_recipe_method_arg_bindings(
    execution: FamilyRecipeExecutionSpec,
    *,
    step_id: str,
    method_id: str,
    projected_bindings: tuple[ProjectedFunctionArgBinding, ...],
) -> dict[str, ProjectedFunctionArgBinding]:
    """Project declared macro arg aliases onto one internal method call."""
    binding_by_arg: dict[str, list[ProjectedFunctionArgBinding]] = {}
    for item in projected_bindings:
        if (
            item.step_id == step_id
            and getattr(item, "consumption_mode", "runtime_input")
            == "runtime_input"
        ):
            binding_by_arg.setdefault(item.arg_name, []).append(item)
    if not binding_by_arg:
        return {}
    result: dict[str, ProjectedFunctionArgBinding] = {}
    for macro_arg, target in execution.input_aliases:
        target_method, separator, input_name = target.partition(".")
        if not separator or not target_method or not input_name:
            raise StrategyDraftValidationError(
                "planner_configuration_error: invalid recipe input alias: "
                f"{execution.recipe_id}.{macro_arg}->{target}"
            )
        if target_method != method_id:
            continue
        items = binding_by_arg.get(macro_arg, ())
        if not items:
            # Optional macro arguments do not need a projected sidecar entry.
            # Required method inputs are checked by the compiler/plan validator.
            continue
        if len(items) != 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: projected recipe argument must "
                f"resolve once: {execution.recipe_id}.{macro_arg}"
            )
        if input_name in result:
            raise StrategyDraftValidationError(
                "planner_configuration_error: duplicate recipe input alias: "
                f"{execution.recipe_id}.{target}"
            )
        result[input_name] = items[0]
    return result


class FunctionalCompileStepView(Protocol):
    """Typed call input used by the Functional capability compiler."""

    scope_id: str
    step_id: str
    capability_id: str
    goal_type: str
    target_handle: str
    input_handles: tuple[str, ...]
    created_entities: tuple[Any, ...]
    return_outputs: tuple[Any, ...]


class FunctionalCapabilityCompiler:
    """Compile one already-selected Functional capability.

    This entry owns no candidate search, wire validation, normalization,
    prefix replay, or draft finalization.  The caller has already fixed the
    capability, typed argument bindings, state reads, and return allocations.
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
        step: FunctionalCompileStepView,
        *,
        capability_id: str,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
        context: RuntimeContext,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
        state_writes: tuple[ProjectedStateWrite, ...] = (),
        state_dependencies: tuple[ProjectedStateDependency, ...] = (),
        arg_bindings: tuple[Any, ...] = (),
        known_state_versions: tuple[IndexedStateVersion, ...] = (),
        known_state_writes: tuple[StateWriteProvenance, ...] = (),
        known_runtime_bindings: tuple[
            tuple[str, str, str, str], ...
        ] = (),
    ) -> ExactCompiledStep:
        """Compile a typed Functional request without an intermediate draft.

        ``step`` is the private compile view exposed by
        ``FunctionalCompileRequest``.  It is intentionally accepted by
        protocol instead of a wire-shaped compatibility object: capability selection,
        scope, argument bindings and return destinations have already been
        fixed by B1-B5b.
        """
        recipe_specs = (
            self.recipe_specs
            or RecipeExecutionSpecRegistry.from_family_spec(family_spec)
        )
        binding_rules = (
            self.binding_rules
            or MethodBindingRuleRegistry.from_family_spec(family_spec)
        )
        macro_specs = MacroSpecRegistry.from_family_spec(
            family_spec,
            method_specs,
        )
        function_specs = FunctionSpecRegistry.from_family_spec(
            family_spec,
            method_specs,
        )
        if (
            function_specs.get(capability_id) is None
            and macro_specs.get(capability_id) is None
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.functional_compile_contract_incomplete: "
                f"call={step.step_id}, capability={capability_id}"
            )

        index = CanonicalRuntimeBindingIndex.from_context(
            context,
            handle_registry=handle_registry,
            question_goals=question_goals,
            functional_consumer_identity_mode="authoritative",
        )
        index.register_projected_state_writes(
            state_writes,
            dependencies=state_dependencies,
            known_state_versions=known_state_versions,
        )
        index.state_write_provenance.extend(known_state_writes)
        for handle, path, runtime_type, source in known_runtime_bindings:
            index.register(handle, path, runtime_type, source=source)
        _register_known_functional_runtime_bindings(
            index,
            step=step,
            handle_registry=handle_registry,
            known_state_versions=known_state_versions,
            known_state_writes=known_state_writes,
        )

        compiler = _RecipePlanCompiler(
            context=context,
            index=index,
            method_specs=method_specs,
            recipe_specs=recipe_specs,
            binding_rules=binding_rules,
            macro_adapters=MacroAdapterRegistry(
                macro_specs,
                handle_registry=handle_registry,
            ),
            function_specs=function_specs,
            projected_state_writes=state_writes,
            projected_state_dependencies=state_dependencies,
            projected_function_arg_bindings=arg_bindings,
            recipe_compilers=self.recipe_compilers,
        )
        declaration_paths_before = set(index.declarations)
        compiled = compiler._compile_with_capability(step, capability_id)
        declarations_by_path = {
            str(item.path): item for item in compiled.declarations
        }
        for path, declaration in index.declarations.items():
            if path not in declaration_paths_before:
                declarations_by_path.setdefault(str(path), declaration)
        return ExactCompiledStep(
            plan=compiled.plan,
            declarations=tuple(declarations_by_path.values()),
            state_write_provenance=compiled.state_write_provenance,
        )


def _output_key_for_promoted_destination(
    plan: StepPlan,
    destination: str,
) -> str | None:
    """Return the invocation output now owning a promoted public destination."""

    source = next(
        (
            source_path
            for source_path, destination_path in plan.promote_outputs.items()
            if destination_path == destination
        ),
        None,
    )
    if source is None:
        return None
    for invocation in reversed(plan.invocations):
        for output_name, output_path in invocation.outputs.items():
            if output_path == source:
                return f"{invocation.method_id}.{output_name}"
    return None



def _register_known_functional_runtime_bindings(
    index: CanonicalRuntimeBindingIndex,
    *,
    step: Any,
    handle_registry: CanonicalHandleRegistry,
    known_state_versions: tuple[IndexedStateVersion, ...],
    known_state_writes: tuple[StateWriteProvenance, ...],
) -> None:
    """Register physical paths after typed visibility has selected a version."""
    visible_scopes = set(handle_registry.ancestor_scopes(step.scope_id))
    for write in known_state_writes:
        destination = write.runtime_destination_key
        runtime_path = (
            destination.runtime_path if destination is not None else None
        )
        valid_scope_id = write.valid_scope_id or write.scope_id
        if not runtime_path or valid_scope_id not in visible_scopes:
            continue
        object_id = write.math_object_id
        symbol_state_alias = (
            getattr(object_id, "kind", None) == "symbol"
            and write.produced_handle == getattr(object_id, "value", None)
            and write.runtime_type != "Symbol"
        )
        if not symbol_state_alias:
            index.register(
                write.produced_handle,
                runtime_path,
                write.runtime_type,
                source=f"step:{write.step_id}",
            )
        if (
            getattr(object_id, "kind", None) == "point"
            and write.runtime_type == "Point"
        ):
            index.register(
                object_id.value,
                runtime_path,
                "Point",
                source=f"step:{write.step_id}",
            )

    for version in known_state_versions:
        valid_scope_id = getattr(version, "valid_scope_id", None)
        destination = getattr(version, "runtime_destination", None)
        runtime_path = getattr(destination, "runtime_path", None)
        produced_handle = getattr(version, "produced_handle", None)
        version_id = getattr(version, "version_id", None)
        logical_key = getattr(
            getattr(version_id, "slot_id", None),
            "logical_key",
            None,
        )
        runtime_type = getattr(logical_key, "runtime_type", None)
        if (
            valid_scope_id not in visible_scopes
            or not isinstance(runtime_path, str)
            or not runtime_path
            or not isinstance(produced_handle, str)
            or not produced_handle
            or not isinstance(runtime_type, str)
            or not runtime_type
        ):
            continue
        object_id = getattr(logical_key, "object_id", None)
        symbol_state_alias = (
            getattr(object_id, "kind", None) == "symbol"
            and produced_handle == getattr(object_id, "value", None)
            and runtime_type != "Symbol"
        )
        producer_call_id = getattr(version, "producer_call_id", None)
        source = (
            f"step:{producer_call_id}"
            if isinstance(producer_call_id, str) and producer_call_id
            else "transactional_state_version"
        )
        if not symbol_state_alias:
            index.register(
                produced_handle,
                runtime_path,
                runtime_type,
                source=source,
            )
        if (
            getattr(object_id, "kind", None) == "point"
            and runtime_type == "Point"
        ):
            index.register(
                object_id.value,
                runtime_path,
                "Point",
                source=source,
            )

class _RecipePlanCompiler:
    """Compile a selected Function or Macro contract into a StepPlan."""

    def __init__(
        self,
        *,
        context: RuntimeContext,
        index: CanonicalRuntimeBindingIndex,
        method_specs: MethodSpecRegistry,
        recipe_specs: RecipeExecutionSpecRegistry,
        binding_rules: MethodBindingRuleRegistry,
        macro_adapters: MacroAdapterRegistry,
        function_specs: FunctionSpecRegistry,
        projected_state_writes: tuple[ProjectedStateWrite, ...],
        projected_state_dependencies: tuple[ProjectedStateDependency, ...],
        projected_function_arg_bindings: tuple[
            ProjectedFunctionArgBinding, ...
        ],
        recipe_compilers: Mapping[str, RecipeCompileStrategyFn],
    ) -> None:
        self.context = context
        self.index = index
        self.method_specs = method_specs
        self.recipe_specs = recipe_specs
        self.binding_rules = binding_rules
        self.macro_adapters = macro_adapters
        self.function_specs = function_specs
        self.projected_state_writes = tuple(projected_state_writes)
        self.projected_state_dependencies = tuple(
            projected_state_dependencies
        )
        self.projected_function_arg_bindings = tuple(
            projected_function_arg_bindings
        )
        self.scalar_closures = ScalarResultClosureRegistry(function_specs)
        self.recipe_compilers = dict(recipe_compilers)
        self.state_write_provenance: list[StateWriteProvenance] = list(
            index.state_write_provenance
        )
        self.index.state_write_provenance = self.state_write_provenance


    def _compile_with_capability(
        self,
        step: FunctionalCompileStepView,
        capability_id: str,
    ) -> _CompiledStep:
        """Compile one exact capability from a structural call view."""
        recipe = self.recipe_specs.get(capability_id)
        if recipe is not None:
            compiled = self._compile_recipe(step, recipe)
        else:
            compiled = self._compile_method(step, capability_id)
        return self._apply_declared_scalar_closures(
            compiled,
            step=step,
            capability_id=capability_id,
        )

    def _apply_declared_scalar_closures(
        self,
        compiled: _CompiledStep,
        *,
        step: FunctionalCompileStepView,
        capability_id: str,
    ) -> _CompiledStep:
        """Close dual-form scalar answers using explicitly read parameter states."""
        writes = tuple(
            item
            for item in self.projected_state_writes
            if item.step_id == step.step_id
            and item.expected_result_form == "closed_value"
        )
        if not writes:
            return compiled
        parameter_pairs = parameter_substitution_pairs_from_reads(step, self.index)
        if not parameter_pairs:
            return compiled
        plan = compiled.plan
        provenance = list(compiled.state_write_provenance)
        for write in writes:
            result = self._scalar_return_spec(
                capability_id,
                write.return_name,
            )
            if result is None or result.scalar_result_form is None:
                continue
            if "closed_value" not in result.scalar_result_form.possible_forms:
                continue
            registration = next(
                (
                    item
                    for item in compiled.registrations
                    if item.handle == write.produced_handle
                ),
                None,
            )
            if registration is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: scalar return registration "
                    f"missing: step={step.step_id}, return={write.return_name}, "
                    f"handle={write.produced_handle}"
                )
            plan = close_scalar_plan_output(
                plan,
                target_path=registration.path,
                runtime_type=registration.value_type,
                parameter_pairs=parameter_pairs,
                registry=self.scalar_closures,
                return_name=write.return_name or result.name,
            )
            output_key = _output_key_for_promoted_destination(
                plan,
                registration.path,
            )
            if output_key is not None:
                provenance = [
                    replace(item, output_key=output_key)
                    if item.return_name == write.return_name
                    else item
                    for item in provenance
                ]
        return replace(
            compiled,
            plan=plan,
            state_write_provenance=tuple(provenance),
        )

    def _scalar_return_spec(
        self,
        capability_id: str,
        return_name: str | None,
    ) -> FunctionReturnSpec | MacroReturnSpec | None:
        if return_name is None:
            return None
        function = self.function_specs.get(capability_id)
        if function is not None:
            return next(
                (item for item in function.returns if item.name == return_name),
                None,
            )
        macro = self.macro_adapters.specs.get(capability_id)
        if macro is None:
            return None
        return next(
            (item for item in macro.returns if item.name == return_name),
            None,
        )

    def _projected_macro_method_outputs(
        self,
        step: FunctionalCompileStepView,
        method_id: str,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Compile every allocated Macro return owned by one internal method."""
        macro = self.macro_adapters.specs.get(_compile_capability_id(step) or "")
        if macro is None:
            return {}, {}
        returns = {item.name: item for item in macro.returns}
        produced = {item.handle: item for item in _compile_return_outputs(step)}
        selected_targets: dict[str, tuple[str, bool]] = {}
        outputs: dict[str, str] = {}
        for write in self.projected_state_writes:
            if write.step_id != step.step_id or write.return_name is None:
                continue
            return_spec = returns.get(write.return_name)
            if return_spec is None or return_spec.output_key is None:
                continue
            owner, separator, output_name = return_spec.output_key.partition(".")
            if not separator or owner != method_id:
                continue
            produced_item = produced.get(write.produced_handle)
            if produced_item is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: projected Macro return has "
                    "no Functional return allocation: "
                    f"step={step.step_id}, return={write.return_name}, "
                    f"handle={write.produced_handle}"
                )
            source = outputs.setdefault(
                output_name,
                _temp(step.step_id, output_name),
            )
            target = _target_path_for_produced(
                produced_item,
                return_spec.runtime_type,
                self.index,
                step,
            )
            current = selected_targets.get(source)
            is_answer = produced_item.handle.startswith("answer:")
            if current is None or (is_answer and not current[1]):
                selected_targets[source] = (target, is_answer)
        return (
            outputs,
            {
                source: target
                for source, (target, _) in selected_targets.items()
            },
        )

    def _compile_recipe(
        self,
        step: FunctionalCompileStepView,
        recipe: FamilyRecipeExecutionSpec,
    ) -> _CompiledStep:
        """编译 recipe。"""
        macro_adapters = getattr(self, "macro_adapters", None)
        declared_evidence_roles: tuple[str, ...] = ()
        return_bindings: tuple[tuple[ProducedFact, MacroReturnSpec], ...] = ()
        if macro_adapters is not None:
            try:
                macro = macro_adapters.validate(recipe.recipe_id, step)
                declared_evidence_roles = tuple(
                    _unique_ordered(
                        item.semantic_role or item.name
                        for item in macro.returns
                        if item.goal_evidence_tags
                    )
                )
                return_bindings = macro_adapters.return_bindings(
                    recipe.recipe_id,
                    step,
                )
            except StrategyDraftValidationError as exc:
                raise
        fn = self.recipe_compilers.get(recipe.execution_strategy)
        if fn is None:
            raise StrategyDraftValidationError(
                f"recipe_execution_strategy_missing: {recipe.recipe_id}:{recipe.execution_strategy}"
            )
        compiled = fn(self, step, recipe)
        compiled = _with_macro_return_registrations(
            compiled,
            step=step,
            bindings=return_bindings,
        )
        return replace(
            compiled,
            state_write_provenance=_macro_write_provenance(
                step,
                recipe_id=recipe.recipe_id,
                bindings=return_bindings,
                declared_evidence_roles=declared_evidence_roles,
                plan=compiled.plan,
                function_specs=self.function_specs,
                index=self.index,
                prior=tuple(self.state_write_provenance),
                projected_state_writes=self.projected_state_writes,
            ),
        )

    def _compile_method(
        self,
        step: FunctionalCompileStepView,
        method_id: str,
    ) -> _CompiledStep:
        """编译单 method step。"""
        spec = self.method_specs.require(method_id)
        function = self.function_specs.get(method_id)
        consumer = (
            function.path_transformation_consumer
            if function is not None
            else None
        )
        if consumer is not None:
            transformation_handle, _transformation_path = (
                self._path_transformation_input(step)
            )
            PathTransformationStateResolver(
                index=self.index,
                projected_state_writes=self.projected_state_writes,
                projected_state_dependencies=self.projected_state_dependencies,
            ).resolve(
                transformation_handle,
                step=step,
                required_roles=consumer.required_roles,
            )
        declaration_keys_before = set(self.index.declarations)
        for created in _compile_created_entities(step):
            if created.entity_type == "point" and created.handle not in self.index.bindings:
                self.index.register_created_entity(created)
        prep = PrepInvocationBuilder(
            binding_rules=self.binding_rules,
            index=self.index,
        ).build(method_id, step)
        exact_inputs = self._projected_exact_function_inputs(step, spec)
        exact_inputs.update(
            self._projected_exact_state_dependency_inputs(
                step,
                spec,
                existing=exact_inputs,
            )
        )
        exact_inputs.update(
            self._projected_function_return_identity_inputs(
                step,
                spec,
                existing=exact_inputs,
            )
        )
        inputs = self.binding_rules.bind(
            method_id,
            step,
            self.index,
            local_outputs=prep.local_outputs or {},
            expansion_selectors_override=(
                self._projected_expansion_selectors(step, method_id)
            ),
            exact_inputs=exact_inputs,
            distinct_arg_groups=spec.distinct_arg_groups,
        )
        projected_output_keys = self._projected_function_output_keys(
            step,
            method_id,
        )
        outputs = _method_outputs_for_step(
            method_id,
            step,
            spec.outputs,
            self.index,
            self.binding_rules,
            input_bindings=inputs,
            input_specs=spec.inputs,
            projected_output_keys=projected_output_keys,
        )
        main_promote = _promote_outputs_for_step(
            step,
            method_id,
            outputs,
            spec.outputs,
            self.index,
            self.binding_rules,
            point_transition=_function_writes_point_transition(
                self.function_specs.get(method_id)
            ),
            projected_state_writes=self.projected_state_writes,
            projected_output_keys=projected_output_keys,
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
        if (
            spec.plan_transformer is not None
            and spec.plan_transformer_scope == "single_invocation"
        ):
            plan = _apply_method_plan_transformer(
                spec.plan_transformer,
                transformer_scope=spec.plan_transformer_scope,
                plan=plan,
                step=step,
                index=self.index,
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
        if (
            spec.plan_transformer is not None
            and spec.plan_transformer_scope == "all_invocations"
        ):
            plan = _apply_method_plan_transformer(
                spec.plan_transformer,
                transformer_scope=spec.plan_transformer_scope,
                plan=plan,
                step=step,
                index=self.index,
            )
        produced_registrations = _produced_registrations(
            step,
            method_id,
            promote,
            self.index,
        )
        registrations = [
            RuntimeHandleBinding(handle, path, spec.outputs[output_name], f"step:{step.step_id}")
            for handle, output_name, path in produced_registrations
        ]
        companion_registrations = _companion_registrations_for_step(
                step,
                method_id,
                outputs,
                promote,
                spec.outputs,
                self.index,
                self.binding_rules,
            )
        registrations.extend(companion_registrations)
        for created in _compile_created_entities(step):
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
        return _CompiledStep(
            plan=plan,
            declarations=declarations,
            registrations=tuple(registrations),
            state_write_provenance=_function_write_provenance(
                step,
                method_id=method_id,
                plan=plan,
                registrations=produced_registrations,
                companion_registrations=companion_registrations,
                function_specs=self.function_specs,
                index=self.index,
                prior=tuple(self.state_write_provenance),
                projected_state_writes=self.projected_state_writes,
            ),
        )

    def _projected_function_output_keys(
        self,
        step: FunctionalCompileStepView,
        method_id: str,
    ) -> dict[str, str]:
        """Map Functional return allocations to MethodSpec output keys."""
        function = self.function_specs.get(method_id)
        if function is None:
            return {}
        returns = {item.name: item for item in function.returns}
        result: dict[str, str] = {}
        for write in self.projected_state_writes:
            if write.step_id != step.step_id or write.return_name is None:
                continue
            return_spec = returns.get(write.return_name)
            if return_spec is None or return_spec.output_key is None:
                continue
            result[write.produced_handle] = return_spec.output_key
        return result

    def _projected_expansion_selectors(
        self,
        step: FunctionalCompileStepView,
        method_id: str,
    ) -> tuple[str, ...] | None:
        """Keep expansion selectors inside reconciliation's chosen arg set.

        A Functional projected step may read transitive provenance states that
        were not selected as call arguments. Legacy expansion selectors must
        not turn those inherited reads into additional runtime inputs.
        """
        selected_args = {
            item.arg_name
            for item in self.projected_function_arg_bindings
            if item.step_id == step.step_id
        }
        selected_args.update(
            item.arg_name
            for item in self.projected_state_dependencies
            if item.step_id == step.step_id and item.arg_name is not None
        )
        if not selected_args:
            return None
        rule = self.binding_rules.rules.get(method_id)
        if rule is None:
            return None
        return tuple(
            selector
            for selector in rule.expansion_selectors
            if (
                # C3 owns the free-parameter role for Functional calls. Keep
                # this selector only on the legacy compile contract.
                selector != "free_quadratic_parameter_if_read"
                and not any(
                    arg_name in selected_args
                    for arg_name in expansion_selector_semantics(
                        selector
                    ).suppressed_by_args
                )
                and (
                    not expansion_selector_semantics(selector).arg_resolvers
                    or any(
                        arg_name in selected_args
                        for arg_name, _resolver in (
                            expansion_selector_semantics(selector).arg_resolvers
                        )
                    )
                )
            )
        )

    def _projected_exact_function_inputs(
        self,
        step: FunctionalCompileStepView,
        spec: Any,
    ) -> dict[str, str]:
        """Map named Functional args to method inputs.

        Aggregate semantic args continue through their declared adapter
        primitive. A one-to-one method input must use the exact StateSlot
        selected by reconciliation instead of being inferred from read order.
        """
        function = self.function_specs.get(spec.method_id)
        if function is None:
            return {}
        # Reconciliation is authoritative for an explicitly named, type-safe
        # one-to-one Functional arg even when the method still uses a legacy
        # binding rule. Mechanism-level semantic args whose public names differ
        # from runtime inputs continue through their role-aware selectors.
        grouped: dict[str, list[ProjectedFunctionArgBinding]] = {}
        adapter_bindings = {
            item.input_name: item
            for item in (
                function.adapter.input_bindings
                if function.adapter is not None
                else ()
            )
        }
        runtime_rule = self.binding_rules.rules.get(spec.method_id)
        if runtime_rule is not None:
            adapter_bindings.update(
                {
                    item.input_name: item
                    for item in runtime_rule.input_bindings
                }
            )
        for item in self.projected_function_arg_bindings:
            if (
                item.step_id == step.step_id
                and item.arg_name in spec.inputs
                and getattr(item, "consumption_mode", "runtime_input")
                == "runtime_input"
            ):
                adapter_binding = adapter_bindings.get(item.arg_name)
                declared_authority = (
                    adapter_binding.functional_authority
                    if adapter_binding is not None
                    else None
                )
                if declared_authority == "compiler":
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: compiler-owned "
                        "Functional arg reached exact binding: "
                        f"method={spec.method_id}, arg={item.arg_name}, "
                        f"sidecar_authority={item.binding_authority}, "
                        f"declared_authority={declared_authority or 'wire'}"
                    )
                grouped.setdefault(item.arg_name, []).append(item)
        result: dict[str, str] = {}
        aggregate_lowerings = (
            {
                item.source_input: item
                for item in function.adapter.aggregate_input_bindings
            }
            if function.adapter is not None
            else {}
        )
        scalar_aggregate_lowerings = (
            {
                item.source_input: item
                for item in function.adapter.scalar_aggregate_lowerings
            }
            if function.adapter is not None
            else {}
        )
        selected_items: dict[str, ProjectedFunctionArgBinding] = {}
        for input_name, items in grouped.items():
            aggregate_lowering = aggregate_lowerings.get(input_name)
            if (
                aggregate_lowering is not None
                and len(items) == 1
                and aggregate_lowering.singleton_input is not None
            ):
                singleton_input = aggregate_lowering.singleton_input
                singleton_spec = spec.inputs.get(singleton_input)
                if (
                    singleton_spec is None
                    or items[0].runtime_type is None
                    or not runtime_type_compatible(
                        singleton_spec.type,
                        items[0].runtime_type,
                    )
                ):
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: invalid functional "
                        "singleton aggregate lowering: "
                        f"method={spec.method_id}, arg={input_name}, "
                        f"singleton_input={singleton_input}"
                    )
                result[singleton_input] = self._projected_input_path(
                    items[0],
                    expected_type=singleton_spec.type,
                    consumer_scope_id=step.scope_id,
                )
                selected_items[singleton_input] = items[0]
                continue
            item_inputs = (
                aggregate_lowering.item_inputs
                if aggregate_lowering is not None
                else ()
            )
            if item_inputs:
                if len(items) > len(item_inputs):
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: functional aggregate "
                        "lowering capacity exceeded: "
                        f"method={spec.method_id}, arg={input_name}, "
                        f"items={len(items)}, capacity={len(item_inputs)}"
                    )
                for item_input, item in zip(item_inputs, items, strict=False):
                    item_spec = spec.inputs.get(item_input)
                    if (
                        item_spec is None
                        or item.runtime_type is None
                        or not runtime_type_compatible(
                            item_spec.type,
                            item.runtime_type,
                        )
                    ):
                        raise StrategyDraftValidationError(
                            "planner_configuration_error: invalid functional "
                            "aggregate lowering: "
                            f"method={spec.method_id}, arg={input_name}, "
                            f"item_input={item_input}"
                        )
                    result[item_input] = self._projected_input_path(
                        item,
                        expected_type=item_spec.type,
                        consumer_scope_id=step.scope_id,
                    )
                    selected_items[item_input] = item
                continue
            expected_type = spec.inputs[input_name].type
            singular_name = input_name[:-1] if input_name.endswith("s") else ""
            singular_spec = spec.inputs.get(singular_name)
            if (
                len(items) == 1
                and singular_spec is not None
                and items[0].runtime_type is not None
                and runtime_type_compatible(
                    singular_spec.type,
                    items[0].runtime_type,
                )
            ):
                result[singular_name] = self._projected_input_path(
                    items[0],
                    expected_type=singular_spec.type,
                    consumer_scope_id=step.scope_id,
                )
                selected_items[singular_name] = items[0]
                continue
            if len(items) == 1:
                item = items[0]
                if item.runtime_type is not None and runtime_type_compatible(
                    expected_type,
                    item.runtime_type,
                ):
                    result[input_name] = self._projected_input_path(
                        item,
                        expected_type=expected_type,
                        consumer_scope_id=step.scope_id,
                    )
                    selected_items[input_name] = item
                    continue
            if self._lower_single_parameter_value_aggregate(
                spec,
                lowering=scalar_aggregate_lowerings.get(input_name),
                expected_type=expected_type,
                items=items,
                result=result,
                selected_items=selected_items,
                consumer_scope_id=step.scope_id,
            ):
                continue
            aggregate_path = self._projected_aggregate_input(
                step,
                input_name=input_name,
                expected_type=expected_type,
                items=items,
            )
            if aggregate_path is not None:
                result[input_name] = aggregate_path
        self._add_projected_point_identity_companions(
            spec,
            result,
            selected_items,
            consumer_scope_id=step.scope_id,
            consumer_step_id=step.step_id,
        )
        return result

    def _path_transformation_input(
        self,
        step: FunctionalCompileStepView,
    ) -> tuple[str, str]:
        """Resolve a Functional transformation by producer, not shared path."""

        exact = tuple(
            item
            for item in self.projected_state_dependencies
            if item.step_id == step.step_id
            and item.arg_name == "path_transformation"
            and item.runtime_type is not None
            and runtime_type_compatible(
                "PathTransformation",
                item.runtime_type,
            )
        )
        if len(exact) > 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: Functional "
                "path_transformation dependency is ambiguous: "
                f"step={step.step_id}, "
                f"producers={[item.source_step_id for item in exact]}"
            )
        if exact:
            dependency = exact[0]
            handle = dependency.produced_handle
            if dependency.state_version_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"step={step.step_id}, arg=path_transformation"
                )
            return (
                handle,
                self.index.runtime_path_for_state_version(
                    dependency.state_version_id,
                    consumer_scope_id=step.scope_id,
                    consumer=f"{step.step_id}.path_transformation",
                ),
            )
        wire_exact = tuple(
            item
            for item in getattr(
                self,
                "projected_function_arg_bindings",
                (),
            )
            if item.step_id == step.step_id
            and item.arg_name == "path_transformation"
            and item.runtime_type is not None
            and runtime_type_compatible(
                "PathTransformation",
                item.runtime_type,
            )
        )
        if len(wire_exact) > 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: Functional "
                "path_transformation wire binding is ambiguous: "
                f"step={step.step_id}, "
                f"sources={[item.source_call_id for item in wire_exact]}"
            )
        if wire_exact:
            binding = wire_exact[0]
            return (
                binding.source_handle,
                self._projected_input_path(
                    binding,
                    expected_type="PathTransformation",
                    consumer_scope_id=step.scope_id,
                ),
            )
        if self.index.functional_consumer_identity_mode is not None:
            self.index.record_legacy_runtime_identity_fallback(
                consumer=f"{step.step_id}.path_transformation",
                handle="PathTransformation",
                reason="path_transformation_dependency_missing",
            )
        path = _path_for_readable_type(
            self.index,
            step,
            "PathTransformation",
        )
        return (
            _handle_for_runtime_path(
                self.index,
                step,
                path,
                expected_type="PathTransformation",
            ),
            path,
        )

    def _projected_exact_state_dependency_inputs(
        self,
        step: FunctionalCompileStepView,
        spec: Any,
        *,
        existing: Mapping[str, str],
    ) -> dict[str, str]:
        """Bind resolver-owned args to the exact reconciled state version.

        Functional reconciliation may select a hidden semantic role from a
        StateSlot that has multiple writes. Typed call inputs preserve the
        dependency, but lose the arg name. This sidecar restores both pieces
        without letting legacy selectors choose another version at compile
        time.
        """
        grouped: dict[str, list[ProjectedStateDependency]] = {}
        for item in self.projected_state_dependencies:
            if (
                item.step_id != step.step_id
                or item.arg_name is None
                or item.arg_name not in spec.inputs
                or item.arg_name in existing
                or item.source == "wire"
            ):
                continue
            grouped.setdefault(item.arg_name, []).append(item)

        result: dict[str, str] = {}
        for input_name, items in grouped.items():
            if len(items) != 1:
                continue
            item = items[0]
            if item.source_step_id is not None:
                if item.state_version_id is None:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: resolved Functional "
                        "state dependency lost its typed version: "
                        f"method={spec.method_id}, arg={input_name}, "
                        f"producer={item.source_step_id}"
                    )
                projected_sources = tuple(
                    write
                    for write in self.projected_state_writes
                    if write.step_id == item.source_step_id
                    and (
                        item.source_return_name is None
                        or write.return_name == item.source_return_name
                    )
                    and write.produced_handle == item.produced_handle
                )
                if len(projected_sources) != 1:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: resolved Functional "
                        "state dependency has no unique projected producer: "
                        f"method={spec.method_id}, arg={input_name}, "
                        f"producer={item.source_step_id}"
                    )
                if (
                    projected_sources[0].selected_version_id
                    != item.state_version_id
                ):
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: "
                        "planner.contract_runtime_input_version_drift: "
                        f"method={spec.method_id}, arg={input_name}, "
                        f"producer={item.source_step_id}"
                    )
            expected_type = spec.inputs[input_name].type
            if all(
                runtime_type.endswith("Ref")
                for runtime_type in split_runtime_types(expected_type)
            ):
                # Object-reference inputs are compiler-owned identities. The
                # dependency sidecar records the materialized state evidence,
                # not a replacement for the immutable PointRef binding.
                continue
            if (
                item.runtime_type is None
                or not runtime_type_compatible(
                    expected_type,
                    item.runtime_type,
                )
            ):
                raise StrategyDraftValidationError(
                    "planner_configuration_error: resolved Functional state "
                    "dependency type drift: "
                    f"method={spec.method_id}, arg={input_name}, "
                    f"expected={expected_type}, "
                    f"reconciled={item.runtime_type or 'unknown'}"
                )
            try:
                if item.state_version_id is not None:
                    result[input_name] = (
                        self.index.runtime_path_for_state_version(
                            item.state_version_id,
                            consumer_scope_id=step.scope_id,
                            consumer=f"{step.step_id}.{input_name}",
                        )
                    )
                else:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: "
                        "planner.runtime_state_version_unresolved: "
                        f"method={spec.method_id}, arg={input_name}, "
                        f"handle={item.produced_handle}"
                    )
            except StrategyDraftValidationError as exc:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: resolved Functional state "
                    "dependency is unavailable at compile time: "
                    f"method={spec.method_id}, arg={input_name}, "
                    f"handle={item.produced_handle}"
                ) from exc
        return result

    def _lower_single_parameter_value_aggregate(
        self,
        spec: Any,
        *,
        lowering: Any | None,
        expected_type: str,
        items: list[ProjectedFunctionArgBinding],
        result: dict[str, str],
        selected_items: dict[str, ProjectedFunctionArgBinding],
        consumer_scope_id: str,
    ) -> bool:
        """Lower one coefficient value through a method's scalar pair.

        Functional catalogs expose ``Coefficients`` as item-level
        ``ParameterValue`` reads. When exactly one dynamic value is selected,
        a method that already declares ``parameter`` and ``parameter_value``
        can consume it without constructing a transient aggregate Context
        value. The lowering is driven entirely by runtime types and object
        identity, so other methods with the same contract gain the behavior.
        """
        if lowering is None or len(items) != 1:
            return False
        item = items[0]
        identity_spec = spec.inputs.get(lowering.identity_input)
        value_spec = spec.inputs.get(lowering.value_input)
        if (
            item.runtime_type is None
            or not runtime_type_compatible(
                lowering.item_runtime_type,
                item.runtime_type,
            )
            or item.math_object_id is None
            or item.math_object_id.kind != "symbol"
            or identity_spec is None
            or value_spec is None
            or not runtime_type_compatible(identity_spec.type, "Symbol")
            or not runtime_type_compatible(
                value_spec.type,
                lowering.item_runtime_type,
            )
        ):
            return False
        result[lowering.identity_input] = (
            self.index.runtime_path_for_object_identity(
                item.math_object_id,
                expected_type=identity_spec.type,
                consumer_scope_id=consumer_scope_id,
                consumer=f"{item.step_id}.{lowering.identity_input}",
            )
        )
        result[lowering.value_input] = self._projected_input_path(
            item,
            expected_type=value_spec.type,
            consumer_scope_id=consumer_scope_id,
        )
        selected_items[lowering.value_input] = item
        return True

    def _add_projected_point_identity_companions(
        self,
        spec: Any,
        inputs: dict[str, str],
        selected_items: Mapping[str, ProjectedFunctionArgBinding],
        *,
        consumer_scope_id: str,
        consumer_step_id: str,
    ) -> None:
        """Keep a resolved Point value and its optional ``*_ref`` in sync."""
        for input_name, item in selected_items.items():
            companion_name = f"{input_name}_ref"
            companion_spec = spec.inputs.get(companion_name)
            if (
                companion_spec is None
                or companion_name in inputs
                or item.runtime_type is None
                or not runtime_type_compatible("Point", item.runtime_type)
                or item.math_object_id is None
                or item.math_object_id.kind != "point"
                or "PointRef" not in split_runtime_types(companion_spec.type)
            ):
                continue
            inputs[companion_name] = (
                self.index.runtime_path_for_object_identity(
                    item.math_object_id,
                    expected_type=companion_spec.type,
                    consumer_scope_id=consumer_scope_id,
                    consumer=(
                        f"{consumer_step_id}.{companion_name}"
                    ),
                )
            )

    def _projected_function_return_identity_inputs(
        self,
        step: FunctionalCompileStepView,
        spec: Any,
        *,
        existing: Mapping[str, str],
    ) -> dict[str, str]:
        """Bind a Functional Point return to its proven MathObject identity.

        A Point may already have a broader open state while this call writes a
        closed or question-local version. Reconciliation owns that state
        allocation, so the compiler must pass the existing object identity to
        the method without treating it as a duplicate coordinate write.
        """
        function = self.function_specs.get(spec.method_id)
        if function is None:
            return {}
        returns = {item.name: item for item in function.returns}
        result: dict[str, str] = {}
        for write in self.projected_state_writes:
            if write.step_id != step.step_id or write.return_name is None:
                continue
            return_spec = returns.get(write.return_name)
            identity_arg = (
                return_spec.identity_arg if return_spec is not None else None
            )
            input_spec = (
                spec.inputs.get(identity_arg)
                if identity_arg is not None
                else None
            )
            if (
                return_spec is None
                or return_spec.runtime_type != "Point"
                or input_spec is None
                or identity_arg in existing
                or identity_arg in result
                or "PointRef" not in split_runtime_types(input_spec.type)
            ):
                continue
            adapter_binding = next(
                (
                    binding
                    for binding in (
                        function.adapter.input_bindings
                        if function.adapter is not None
                        else ()
                    )
                    if binding.input_name == identity_arg
                ),
                None,
            )
            if (
                adapter_binding is not None
                and selector_semantics(
                    adapter_binding.selector
                ).owns_identity_binding
            ):
                continue
            if write.math_object_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.state_identity_incomplete: "
                    f"step={step.step_id}, return={write.return_name}"
                )
            result[identity_arg] = (
                self.index.runtime_path_for_return_object_identity(
                    write.math_object_id,
                    expected_type=input_spec.type,
                    consumer_scope_id=step.scope_id,
                    consumer=f"{step.step_id}.{identity_arg}",
                )
            )
        return result

    def _projected_input_path(
        self,
        item: Any,
        *,
        expected_type: str,
        consumer_scope_id: str,
    ) -> str:
        """Resolve an exact sidecar binding and surface cross-layer drift."""
        runtime_path = getattr(item, "runtime_path", None)
        if runtime_path is not None:
            return runtime_path
        if item.state_version_id is not None:
            return self.index.runtime_path_for_state_version(
                item.state_version_id,
                consumer_scope_id=consumer_scope_id,
                consumer=f"{item.step_id}.{item.arg_name}",
            )
        identity_types = {"PointRef", "Symbol", "Function"}
        expected_types = set(split_runtime_types(expected_type))
        materialized_object_state = (
            item.math_object_id is not None
            and item.runtime_type not in identity_types
        )
        if (
            item.math_object_id is not None
            and item.state_slot_id is None
            and (
                bool(expected_types & identity_types)
                or item.runtime_type in identity_types
            )
        ):
            return self.index.runtime_path_for_object_identity(
                item.math_object_id,
                expected_type=expected_type,
                consumer_scope_id=consumer_scope_id,
                consumer=f"{item.step_id}.{item.arg_name}",
            )
        if materialized_object_state:
            self.index.record_legacy_runtime_identity_fallback(
                consumer=f"{item.step_id}.{item.arg_name}",
                handle=item.source_handle,
                reason="materialized_projected_arg_missing_state_version",
            )
        if item.condition_id is not None:
            return self.index.runtime_path_for_condition_identity(
                item.condition_id,
                source_handle=item.source_handle,
                expected_type=expected_type,
                consumer_scope_id=consumer_scope_id,
                consumer=f"{item.step_id}.{item.arg_name}",
            )
        if (
            item.source_call_id is not None
            and item.source_return_name is not None
        ):
            return self.index.runtime_path_for_call_result_identity(
                item.source_call_id,
                item.source_return_name,
                source_handle=item.source_handle,
                expected_type=expected_type,
                consumer_scope_id=consumer_scope_id,
                consumer=f"{item.step_id}.{item.arg_name}",
            )
        self.index.record_legacy_runtime_identity_fallback(
            consumer=f"{item.step_id}.{item.arg_name}",
            handle=item.source_handle,
            reason="projected_arg_missing_typed_identity",
        )
        try:
            return self.index.path_for(
                item.source_handle,
                expected_type=expected_type,
            )
        except StrategyDraftValidationError as exc:
            if (
                "binding_type_mismatch" in str(exc)
                and item.runtime_type is not None
                and runtime_type_compatible(expected_type, item.runtime_type)
            ):
                actual = self.index.bindings.get(item.source_handle)
                actual_type = actual.value_type if actual is not None else "missing"
                raise StrategyDraftValidationError(
                    "planner_configuration_error: functional projected argument "
                    "runtime type drift: "
                    f"arg={item.arg_name}, handle={item.source_handle}, "
                    f"reconciled={item.runtime_type}, runtime={actual_type}"
                ) from exc
            raise

    def _projected_aggregate_input(
        self,
        step: FunctionalCompileStepView,
        *,
        input_name: str,
        expected_type: str,
        items: list[ProjectedFunctionArgBinding],
    ) -> str | tuple[str, ...] | None:
        item_type = {
            "SymbolList": "Symbol",
            "PointList": "Point",
        }.get(expected_type)
        if item_type is None or not items:
            return None
        if any(
            item.runtime_type is None
            or not runtime_type_compatible(item_type, item.runtime_type)
            for item in items
        ):
            return None
        source_paths = tuple(
            binding.path
            for item in items
            if (
                binding := self.index.bindings.get(item.source_handle)
            ) is not None
        )
        if len(source_paths) == 1:
            try:
                existing = self.index.context.read_path(
                    source_paths[0],
                    from_scope_id=step.scope_id,
                    expected_type=expected_type,
                )
            except (KeyError, PermissionError, TypeError, ValueError):
                pass
            else:
                if existing.type == expected_type:
                    return source_paths[0]
        if len(source_paths) == len(items):
            return tuple(source_paths)
        return None

    def _projected_exact_recipe_inputs(
        self,
        step: FunctionalCompileStepView,
        method_id: str,
    ) -> dict[str, str]:
        """Compile declared macro input aliases from reconciliation sidecar."""
        if _compile_capability_id(step) is None:
            return {}
        execution = self.recipe_specs.get(_compile_capability_id(step))
        if execution is None or not execution.input_aliases:
            return {}
        bindings = _projected_recipe_method_arg_bindings(
            execution,
            step_id=step.step_id,
            method_id=method_id,
            projected_bindings=self.projected_function_arg_bindings,
        )
        method_spec = self.method_specs.require(method_id)
        result: dict[str, str] = {}
        for input_name, item in bindings.items():
            input_spec = method_spec.inputs.get(input_name)
            if input_spec is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: recipe input alias targets "
                    f"unknown input: {_compile_capability_id(step)}.{method_id}.{input_name}"
                )
            if item.runtime_type is None or not runtime_type_compatible(
                input_spec.type,
                item.runtime_type,
            ):
                raise StrategyDraftValidationError(
                    "planner_configuration_error: recipe input alias type "
                    f"mismatch: {_compile_capability_id(step)}.{input_name}"
                )
            result[input_name] = self._projected_input_path(
                item,
                expected_type=input_spec.type,
                consumer_scope_id=step.scope_id,
            )
            parameter_spec = method_spec.inputs.get("parameter")
            if (
                input_name == "parameter_value"
                and parameter_spec is not None
                and "parameter" not in result
                and item.math_object_id is not None
                and item.math_object_id.kind == "symbol"
                and runtime_type_compatible(parameter_spec.type, "Symbol")
            ):
                result["parameter"] = (
                    self.index.runtime_path_for_object_identity(
                        item.math_object_id,
                        expected_type=parameter_spec.type,
                        consumer_scope_id=step.scope_id,
                        consumer=f"{step.step_id}.parameter",
                    )
                )
        return result

    def _compile_right_angle_recipe(self, step: FunctionalCompileStepView) -> _CompiledStep:
        """编译“直角等腰候选 + 约束筛选” recipe。"""
        inputs = resolve_read_closed_right_angle_inputs(step, self.index)
        candidates = _temp(step.step_id, "candidates")
        selected = _temp(step.step_id, "selected_point")
        target_path = self.index.path_for(inputs.target, expected_type="PointRef")
        invocations = [
            MethodInvocation(
                invocation_id=f"{step.step_id}.right_angle_equal_length_candidates",
                method_id="right_angle_equal_length_candidates",
                scope=step.step_id,
                inputs={
                    "anchor": self.index.path_for(
                        inputs.anchor,
                        expected_type="Point",
                    ),
                    "reference": self.index.path_for(
                        inputs.reference,
                        expected_type="Point",
                    ),
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
                        inputs.orientation,
                        expected_type="OrientationHint",
                    ),
                    "parameter": self.index.path_for(
                        inputs.parameter,
                        expected_type="Symbol",
                    ),
                    "parameter_constraint": self.index.path_for(
                        inputs.parameter_constraint,
                        expected_type="Constraint",
                    ),
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
                scope_id=_handle_scope(inputs.target),
            ),
            scope=_handle_scope(inputs.target),
            invocations=invocations,
            expected_outputs=[target_path],
            promote_outputs={selected: target_path},
        )
        registrations = tuple(
            RuntimeHandleBinding(item.handle, target_path, "Point", f"step:{step.step_id}")
            for item in _compile_return_outputs(step)
        )
        return _CompiledStep(plan=plan, registrations=registrations)

    def _compile_straightening_recipe(self, step: FunctionalCompileStepView) -> _CompiledStep:
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
        (
            path_transformation_handle,
            path_transformation,
        ) = self._path_transformation_input(
            step,
        )
        straightening_inputs: dict[str, str] = {
            "path_transformation": path_transformation
        }
        transformation_state = PathTransformationStateResolver(
            index=self.index,
            projected_state_writes=self.projected_state_writes,
            projected_state_dependencies=self.projected_state_dependencies,
        ).resolve(
            path_transformation_handle,
            step=step,
            required_roles=("fixed_endpoint_1", "fixed_endpoint_2"),
        )
        fixed_1_role = transformation_state.require("fixed_endpoint_1")
        fixed_2_role = transformation_state.require("fixed_endpoint_2")
        fixed_1_path, fixed_1_prep = _required_path_role_point_input(
            fixed_1_role,
            step=step,
            index=self.index,
        )
        fixed_2_path, fixed_2_prep = _required_path_role_point_input(
            fixed_2_role,
            step=step,
            index=self.index,
        )
        moving_locus = _path_for_readable_type_or_none(self.index, step, "Line")
        role_point_preps: list[
            tuple[tuple[MethodInvocation, ...], dict[str, str]]
        ] = []
        role_map = {item.role: item for item in transformation_state.roles}
        if (
            moving_locus is None
            and all(
                role in role_map
                for role in (
                    "moving_locus",
                    "moving_locus_endpoint_1",
                    "moving_locus_endpoint_2",
                )
            )
        ):
            moving_membership = _required_path_role_source(
                role_map["moving_locus"],
                step=step,
            )
            line_1_path, line_1_prep = _required_path_role_point_input(
                role_map["moving_locus_endpoint_1"],
                step=step,
                index=self.index,
            )
            line_2_path, line_2_prep = _required_path_role_point_input(
                role_map["moving_locus_endpoint_2"],
                step=step,
                index=self.index,
            )
            role_point_preps.extend((line_1_prep, line_2_prep))
            straightening_inputs.update(
                {
                    "moving_point_membership": self.index.path_for(
                        moving_membership,
                        expected_type="Condition",
                    ),
                    "line_point_1": line_1_path,
                    "line_point_2": line_2_path,
                }
            )
        elif moving_locus is not None:
            straightening_inputs["moving_locus"] = moving_locus
        else:
            raise StrategyDraftValidationError(
                "functional.path_transformation_role_missing: "
                f"transformation={path_transformation_handle}, "
                "role=moving_locus"
            )
        straightening_inputs.update(
            {
                "fixed_point_1": fixed_1_path,
                "fixed_point_2": fixed_2_path,
            }
        )
        prep_invocations = [
            *fixed_1_prep[0],
            *fixed_2_prep[0],
            *(
                invocation
                for invocations, _ in role_point_preps
                for invocation in invocations
            ),
        ]
        prep_promote = {
            **fixed_1_prep[1],
            **fixed_2_prep[1],
            **{
                source: target
                for _, promote in role_point_preps
                for source, target in promote.items()
            },
        }
        invocations = [
            *prep_invocations,
            MethodInvocation(
                invocation_id=f"{step.step_id}.broken_path_straightening_candidates",
                method_id="broken_path_straightening_candidates",
                scope=step.step_id,
                inputs=straightening_inputs,
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
            selected: _straightening_candidate_target_path(step, self.index),
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
        for item in _compile_return_outputs(step):
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
                semantic = produced_semantic_role(item)
                if straightening_endpoint_position(semantic) == 1:
                    registrations.append(
                        RuntimeHandleBinding(
                            item.handle,
                            endpoint_point_1,
                            "Point",
                            f"step:{step.step_id}",
                        )
                    )
                elif straightening_endpoint_position(semantic) == 2:
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

    def _compile_curve_candidate_parameter_recipe(self, step: FunctionalCompileStepView) -> _CompiledStep:
        """编译“候选点曲线筛选 + 曲线点反求参数” recipe。

        这个 recipe 只处理候选点已经存在之后的通用动作：用含参抛物线筛选候选，
        再把唯一候选点代入抛物线反求参数。它不负责化简函数、求参考点或生成候选；
        这些上下文准备应由独立 method step 完成。
        """
        filter_inputs = self._projected_exact_recipe_inputs(
            step,
            "filter_point_candidates_by_quadratic_curve",
        )
        parameter_inputs = self._projected_exact_recipe_inputs(
            step,
            "parameter_from_curve_point_on_quadratic",
        )
        has_functional_input_sidecar = bool(filter_inputs or parameter_inputs)
        target_path = filter_inputs.get("target")
        if target_path is None:
            target = _curve_candidate_target_handle(step, self.index)
            target_path = self.index.path_for(
                target,
                expected_type="PointRef",
            )
        candidates_path = filter_inputs.get("candidates")
        if candidates_path is None:
            candidates_path = _path_for_readable_type(
                self.index,
                step,
                "PointList",
            )
        parabola_path = filter_inputs.get("parabola")
        if parabola_path is None:
            parabola_path = parameter_inputs.get("quadratic")
        if parabola_path is None:
            parabola_path = _path_for_readable_type(
                self.index,
                step,
                "Parabola",
            )
        filtered = _temp(step.step_id, "filtered_candidates")
        rejected = _temp(step.step_id, "rejected_candidates")
        selected_candidate = _temp(step.step_id, "selected_candidate")
        point = _temp(step.step_id, "point")
        parameter_value = _temp(step.step_id, "parameter_value")
        parabola = _temp(step.step_id, "parabola")
        primary_symbol = self.index.parameter_symbol_path()
        primary_constraint = filter_inputs.get("parameter_constraint")
        if primary_constraint is None and not has_functional_input_sidecar:
            primary_constraint = self.index.parameter_constraint_path()
        parameter_output_key = _parameter_output_key_from_symbol_path(primary_symbol)
        filter_invocation_inputs = {
            "candidates": candidates_path,
            "target": target_path,
            "parabola": parabola_path,
            "x": self.index.path_for("symbol:problem:x", expected_type="Symbol"),
            "parameter": primary_symbol,
            "quadratic_template": self.index.path_for(
                "function:problem:parabola",
                expected_type="Expression",
            ),
        }
        parameter_invocation_inputs = {
            "quadratic": parameter_inputs.get("quadratic", parabola_path),
            "x": self.index.path_for("symbol:problem:x", expected_type="Symbol"),
            "point": selected_candidate,
            "parameter": primary_symbol,
            "quadratic_template": self.index.path_for(
                "function:problem:parabola",
                expected_type="Expression",
            ),
        }
        if primary_constraint is not None:
            filter_invocation_inputs["parameter_constraint"] = primary_constraint
        parameter_constraint = parameter_inputs.get("parameter_constraint")
        if (
            parameter_constraint is None
            and not has_functional_input_sidecar
        ):
            parameter_constraint = primary_constraint
        if parameter_constraint is not None:
            parameter_invocation_inputs["parameter_constraint"] = (
                parameter_constraint
            )
        invocations = [
            MethodInvocation(
                invocation_id=f"{step.step_id}.filter_point_candidates_by_quadratic_curve",
                method_id="filter_point_candidates_by_quadratic_curve",
                scope=step.step_id,
                inputs=filter_invocation_inputs,
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
                inputs=parameter_invocation_inputs,
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
        for produced in _compile_return_outputs(step):
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
            for item in _compile_return_outputs(step)
            if _produced_output_type(item, self.index.handle_registry) == "Point"
        ]
        return _CompiledStep(plan=plan, registrations=tuple(registrations))

    def _compile_equal_length_ray_path_reduction_recipe(self, step: FunctionalCompileStepView) -> _CompiledStep:
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
            for item in _compile_return_outputs(step)
            if _produced_output_type(item, self.index.handle_registry) == "MinimumExpression"
        )
        return _CompiledStep(
            plan=plan,
            declarations=(declaration,),
            registrations=registrations,
        )

    def _compile_straightened_distance_minimum_recipe(self, step: FunctionalCompileStepView) -> _CompiledStep:
        """编译“已拉直方案 -> 端点距离最值” recipe。

        split recipe 路径中，前序 ``broken_path_straightening_and_select`` 已经确定
        最短线段端点；这里优先消费这些 endpoint metadata，避免继续让 LLM
        通过普通 point reads 猜测距离两端。
        """
        inputs = self._projected_exact_recipe_inputs(
            step,
            "distance_between_points",
        )
        if inputs and not {"p1", "p2"}.issubset(inputs):
            raise StrategyDraftValidationError(
                "planner_configuration_error: straightened distance macro "
                "requires projected p1 and p2"
            )
        if not inputs:
            endpoints = _straightening_endpoint_handles_from_reads(step, self.index)
            if endpoints is None:
                return self._compile_method(step, "distance_between_points")
            point_1, point_2 = endpoints
            inputs = {
                "p1": self.index.path_for(point_1, expected_type="Point"),
                "p2": self.index.path_for(point_2, expected_type="Point"),
            }
        outputs, promote = self._projected_macro_method_outputs(
            step,
            "distance_between_points",
        )
        projected_outputs = bool(outputs)
        if not outputs:
            output_name = (
                "evaluated_distance"
                if _parameter_value_handle(step, self.index)
                else "distance"
            )
            distance = _temp(step.step_id, output_name)
            target_path = _minimum_expression_target_path(step, self.index)
            outputs = {output_name: distance}
            promote = {distance: target_path}
        else:
            target_path = _minimum_expression_target_path(step, self.index)
            if target_path not in promote.values():
                target_path = next(iter(promote.values()))
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
                    outputs=outputs,
                )
            ],
            expected_outputs=list(_unique_ordered(promote.values())),
            promote_outputs=promote,
        )
        registrations = (
            ()
            if projected_outputs
            else tuple(
                RuntimeHandleBinding(
                    item.handle,
                    target_path,
                    "MinimumExpression",
                    f"step:{step.step_id}",
                )
                for item in _compile_return_outputs(step)
                if _produced_output_type(
                    item,
                    self.index.handle_registry,
                )
                == "MinimumExpression"
            )
        )
        return _CompiledStep(plan=plan, registrations=registrations)

    def _compile_broken_path_straightening_minimum_expression_recipe(self, step: FunctionalCompileStepView) -> _CompiledStep:
        """编译“折线拉直候选 + 选择方案 + 计算最小值表达式” recipe。"""
        (
            path_transformation_handle,
            path_transformation,
        ) = self._path_transformation_input(
            step,
        )
        straightening_inputs: dict[str, str] = {}
        transformation_state = PathTransformationStateResolver(
            index=self.index,
            projected_state_writes=self.projected_state_writes,
            projected_state_dependencies=self.projected_state_dependencies,
        ).resolve(
            path_transformation_handle,
            step=step,
            required_roles=("fixed_endpoint_1", "fixed_endpoint_2"),
        )
        fixed_1_path, fixed_1_prep = _required_path_role_point_input(
            transformation_state.require("fixed_endpoint_1"),
            step=step,
            index=self.index,
        )
        fixed_2_path, fixed_2_prep = _required_path_role_point_input(
            transformation_state.require("fixed_endpoint_2"),
            step=step,
            index=self.index,
        )
        moving_locus = _path_for_readable_type_or_none(self.index, step, "Line")
        role_point_preps: list[
            tuple[tuple[MethodInvocation, ...], dict[str, str]]
        ] = []
        role_map = {item.role: item for item in transformation_state.roles}
        if (
            moving_locus is None
            and all(
                role in role_map
                for role in (
                    "moving_locus",
                    "moving_locus_endpoint_1",
                    "moving_locus_endpoint_2",
                )
            )
        ):
            moving_membership = _required_path_role_source(
                role_map["moving_locus"],
                step=step,
            )
            line_1_path, line_1_prep = _required_path_role_point_input(
                role_map["moving_locus_endpoint_1"],
                step=step,
                index=self.index,
            )
            line_2_path, line_2_prep = _required_path_role_point_input(
                role_map["moving_locus_endpoint_2"],
                step=step,
                index=self.index,
            )
            role_point_preps.extend((line_1_prep, line_2_prep))
            straightening_inputs.update(
                {
                    "moving_point_membership": self.index.path_for(
                        moving_membership,
                        expected_type="Condition",
                    ),
                    "line_point_1": line_1_path,
                    "line_point_2": line_2_path,
                }
            )
        elif moving_locus is not None:
            straightening_inputs["moving_locus"] = moving_locus
        else:
            raise StrategyDraftValidationError(
                "functional.path_transformation_role_missing: "
                f"transformation={path_transformation_handle}, "
                "role=moving_locus"
            )
        candidates = _temp(step.step_id, "candidates")
        selected = _temp(step.step_id, "selected_candidate")
        auxiliary = _temp(step.step_id, "auxiliary_point")
        minimum_point_1 = _temp(step.step_id, "minimum_point_1")
        minimum_point_2 = _temp(step.step_id, "minimum_point_2")
        distance = _temp(step.step_id, "distance")
        target_path = _minimum_expression_target_path(step, self.index)
        distance_inputs = {
            "p1": minimum_point_1,
            "p2": minimum_point_2,
            **self._projected_exact_recipe_inputs(
                step,
                "distance_between_points",
            ),
        }
        projected_distance_outputs, projected_distance_promote = (
            self._projected_macro_method_outputs(
                step,
                "distance_between_points",
            )
        )
        distance_outputs = (
            projected_distance_outputs
            if projected_distance_outputs
            else {"distance": distance}
        )
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
        prep_invocations = [
            *fixed_1_prep[0],
            *fixed_2_prep[0],
            *(
                invocation
                for invocations, _ in role_point_preps
                for invocation in invocations
            ),
        ]
        prep_promote = {
            **fixed_1_prep[1],
            **fixed_2_prep[1],
            **{
                source: target
                for _, promote in role_point_preps
                for source, target in promote.items()
            },
        }
        invocations = [
            *prep_invocations,
            MethodInvocation(
                invocation_id=f"{step.step_id}.broken_path_straightening_candidates",
                method_id="broken_path_straightening_candidates",
                scope=step.step_id,
                inputs={
                    "path_transformation": path_transformation,
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
                inputs=distance_inputs,
                outputs=distance_outputs,
            ),
        ]
        endpoint_point_1, endpoint_point_2 = _straightening_endpoint_target_paths(
            step,
            self.index,
        )
        promote = {
            **prep_promote,
            candidates: _scoped_output_path(self.index.context, step.scope_id, "straightening_candidates"),
            selected: _straightening_candidate_target_path(step, self.index),
            auxiliary: auxiliary_path,
            minimum_point_1: endpoint_point_1,
            minimum_point_2: endpoint_point_2,
            **(
                projected_distance_promote
                if projected_distance_outputs
                else {distance: target_path}
            ),
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
        if not projected_distance_outputs:
            for item in _compile_return_outputs(step):
                output_type = _produced_output_type(
                    item,
                    self.index.handle_registry,
                )
                if output_type == "MinimumExpression":
                    registrations.append(
                        RuntimeHandleBinding(
                            item.handle,
                            target_path,
                            "MinimumExpression",
                            f"step:{step.step_id}",
                        )
                    )
                elif output_type == "Point":
                    semantic = produced_semantic_role(item)
                    if straightening_endpoint_position(semantic) == 1:
                        registrations.append(
                            RuntimeHandleBinding(
                                item.handle,
                                promote[minimum_point_1],
                                "Point",
                                f"step:{step.step_id}",
                            )
                        )
                    elif straightening_endpoint_position(semantic) == 2:
                        registrations.append(
                            RuntimeHandleBinding(
                                item.handle,
                                promote[minimum_point_2],
                                "Point",
                                f"step:{step.step_id}",
                            )
                        )
        return _CompiledStep(plan=plan, declarations=tuple(declarations), registrations=registrations)

def _with_macro_return_registrations(
    compiled: _CompiledStep,
    *,
    step: FunctionalCompileStepView,
    bindings: tuple[tuple[ProducedFact, MacroReturnSpec], ...],
) -> _CompiledStep:
    """Register every projected Macro return from its declared output alias.

    Recipe strategies may still register convenience aliases, but the
    MacroSpec output graph is authoritative for Functional public returns.
    A projected return without one promoted runtime output is a compiler/spec
    invariant failure and must never be sent back to the LLM as a retry issue.
    """

    registrations = {item.handle: item for item in compiled.registrations}
    for produced, return_spec in bindings:
        output_key = return_spec.output_key
        if output_key is None or "." not in output_key:
            raise StrategyDraftValidationError(
                "planner_configuration_error: macro return output key missing: "
                f"step={step.step_id}, return={return_spec.name}"
            )
        method_id, output_name = output_key.rsplit(".", 1)
        output_paths = tuple(
            invocation.outputs[output_name]
            for invocation in compiled.plan.invocations
            if invocation.method_id == method_id
            and output_name in invocation.outputs
        )
        if len(output_paths) != 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: macro return runtime output "
                "must resolve uniquely: "
                f"step={step.step_id}, return={return_spec.name}, "
                f"output_key={output_key}, matches={len(output_paths)}"
            )
        runtime_path = compiled.plan.promote_outputs.get(output_paths[0])
        if runtime_path is None:
            raise StrategyDraftValidationError(
                "planner_configuration_error: macro return promotion missing: "
                f"step={step.step_id}, return={return_spec.name}, "
                f"output_key={output_key}"
            )
        projected = RuntimeHandleBinding(
            produced.handle,
            runtime_path,
            return_spec.runtime_type,
            f"step:{step.step_id}",
        )
        existing = registrations.get(produced.handle)
        if existing is not None and (
            existing.path != projected.path
            or existing.value_type != projected.value_type
        ):
            raise StrategyDraftValidationError(
                "planner_configuration_error: macro return registration "
                "conflicts with recipe compiler: "
                f"step={step.step_id}, return={return_spec.name}, "
                f"existing={existing.path}:{existing.value_type}, "
                f"projected={projected.path}:{projected.value_type}"
            )
        registrations[produced.handle] = projected
    return replace(compiled, registrations=tuple(registrations.values()))


def _compile_single_method_recipe(
    compiler: _RecipePlanCompiler,
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译直角等腰候选筛选 recipe。"""
    return compiler._compile_right_angle_recipe(step)


def _compile_curve_candidate_parameter_solve_recipe(
    compiler: _RecipePlanCompiler,
    step: FunctionalCompileStepView,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译曲线候选点筛选并反求参数 recipe。"""
    return compiler._compile_curve_candidate_parameter_recipe(step)


def _compile_straightening_candidates_select_recipe(
    compiler: _RecipePlanCompiler,
    step: FunctionalCompileStepView,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译折线拉直候选筛选 recipe。"""
    return compiler._compile_straightening_recipe(step)


def _compile_equal_length_ray_path_reduction_recipe(
    compiler: _RecipePlanCompiler,
    step: FunctionalCompileStepView,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译等长射线路径降维 recipe。"""
    return compiler._compile_equal_length_ray_path_reduction_recipe(step)


def _compile_straightened_distance_minimum_recipe(
    compiler: _RecipePlanCompiler,
    step: FunctionalCompileStepView,
    recipe: FamilyRecipeExecutionSpec,
) -> _CompiledStep:
    """编译 split 将军饮马后续的端点距离最值 recipe。"""
    return compiler._compile_straightened_distance_minimum_recipe(step)


def _compile_broken_path_straightening_minimum_expression_recipe(
    compiler: _RecipePlanCompiler,
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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

    try:
        roles = resolve_equal_length_ray_path_roles(
            ray_payload=index.fact_payload(ray_fact),
            segment_payload=index.fact_payload(segment_fact),
            equal_payload=index.fact_payload(equal_fact),
            target_payload=index.fact_payload(target_fact),
            entity_payload=index.entity_payload,
            visible_point_handles=index.entity_handles("point", step=step),
            resolve_point_name=lambda name: index.point_handle_by_name(
                name,
                step=step,
            ),
        )
    except EqualLengthRayRoleError as exc:
        raise StrategyDraftValidationError(
            f"{exc.code}: {step.step_id}: {exc}"
        ) from exc
    return {
        "anchor": roles.anchor,
        "ray_point": roles.ray_point,
        "reference_point": roles.reference_point,
        "fixed_point": roles.fixed_point,
    }


def _point_value_path_for_step(
    point_handle: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取点值 path，优先使用 step 显式 reads 的同名坐标 fact。

    对某些题，ProblemIR 中的点是全题实体，但它在当前问才被求成含参坐标。
    例如 ``point:problem:B`` 的第（Ⅱ）问坐标会以
    ``fact:ii:B_coordinate_expr`` 出现。recipe 内部低层 method 需要的是点值，
    所以这里优先使用当前 step 已读入的坐标 fact。
    """
    point_name = _handle_name(point_handle)
    projected = index.latest_projected_state_write_in_handles(
        point_handle,
        _compile_input_handles(step),
        before_step_id=step.step_id,
    )
    if projected is not None and projected.runtime_type == "Point":
        binding = index.bindings.get(projected.produced_handle)
        if binding is not None and binding.value_type == "Point":
            return binding.path
    for handle in reversed(_compile_input_handles(step)):
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, tuple[tuple[MethodInvocation, ...], dict[str, str]]]:
    """读取点值；必要时为可确定定义点生成当前 recipe 内部 prep invocation。"""
    definition = _point_definition(point_handle, index)
    if (
        definition == "midpoint"
        and _projected_midpoint_state_is_stale(point_handle, step, index)
    ):
        return _prepare_midpoint_point_value(point_handle, step, index)
    try:
        return _point_value_path_for_step(point_handle, step, index), ((), {})
    except StrategyDraftValidationError:
        if definition == "midpoint":
            return _prepare_midpoint_point_value(point_handle, step, index)
        if definition != "axis_x_intercept":
            raise
        point_name = _handle_name(point_handle)
        output_path = _temp(step.step_id, f"prepared_{point_name}_coordinate")
        promote_path = _scoped_output_path(
            index.context,
            step.scope_id,
            f"{point_name}_coordinate",
        )
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


def _projected_midpoint_state_is_stale(
    point_handle: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """Return whether a midpoint predates a point-state dependency in reads."""
    current = index.latest_projected_state_write(
        point_handle,
        before_step_id=step.step_id,
    )
    if current is None:
        return False
    payload = index.entity_payload(point_handle)
    endpoints = payload.get("of")
    if not (
        isinstance(endpoints, list)
        and len(endpoints) == 2
        and all(isinstance(item, str) for item in endpoints)
    ):
        return False
    current_sources = set(current.source_state_slot_ids)
    for endpoint in endpoints:
        latest_read = index.latest_projected_state_write_in_handles(
            endpoint,
            _compile_input_handles(step),
            before_step_id=step.step_id,
        )
        if (
            latest_read is not None
            and latest_read.state_slot_id not in current_sources
        ):
            return True
    return False


def _prepare_midpoint_point_value(
    point_handle: str,
    step: FunctionalCompileStepView,
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
            "target": _midpoint_target_identity_path(
                point_handle,
                step=step,
                index=index,
            ),
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


def _midpoint_target_identity_path(
    point_handle: str,
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """Resolve a midpoint target without bypassing Functional typed identity."""

    if index.functional_consumer_identity_mode is None:
        return index.point_identity_path_for(point_handle)
    object_id = _point_object_id_for_handle(point_handle, index)
    if object_id is None:
        index.record_legacy_runtime_identity_fallback(
            consumer=f"{step.step_id}:midpoint_target",
            handle=point_handle,
            reason="midpoint_target_math_object_unresolved",
        )
        return index.point_identity_path_for(point_handle)
    return index.runtime_path_for_object_identity(
        object_id,
        expected_type="PointRef",
        consumer_scope_id=step.scope_id,
        consumer=f"{step.step_id}:midpoint_target",
    )


def _point_definition(point_handle: str, index: CanonicalRuntimeBindingIndex) -> str | None:
    """读取 canonical point entity 的 definition。"""
    try:
        payload = index.entity_payload(point_handle)
    except StrategyDraftValidationError:
        return None
    value = payload.get("definition")
    return str(value) if isinstance(value, str) else None


def _generated_equal_length_auxiliary_point_path(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取 recipe 产出的 MinimumExpression target path。"""
    candidates = tuple(
        produced for produced in _compile_return_outputs(step)
        if _produced_output_type(produced, index.handle_registry) == "MinimumExpression"
    )
    for produced in candidates:
        if _compile_target_handle(step).startswith("answer:") and produced.handle == _compile_target_handle(step):
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """返回 split 拉直 recipe 推广的最短线段端点路径。"""
    return (
        _straightening_endpoint_target_path(step, index, STRAIGHTENED_ENDPOINT_1),
        _straightening_endpoint_target_path(step, index, STRAIGHTENED_ENDPOINT_2),
    )


def _straightening_candidate_target_path(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """Publish a selected candidate at its declared semantic scope."""

    for produced in _compile_return_outputs(step):
        if (
            _produced_output_type(produced, index.handle_registry)
            == "StraighteningCandidate"
        ):
            return _target_path_for_produced(
                produced,
                "StraighteningCandidate",
                index,
                step,
            )
    return _scoped_output_path(
        index.context,
        step.scope_id,
        "straightening_candidate",
    )


def _straightening_endpoint_target_path(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    semantic_name: str,
) -> str:
    """优先使用 step 显式 produced endpoint fact 的 valid_scope。"""
    canonical_name = canonical_straightening_endpoint_name(semantic_name)
    for produced in _compile_return_outputs(step):
        if (
            _produced_output_type(produced, index.handle_registry) == "Point"
            and canonical_straightening_endpoint_name(
                produced_semantic_role(produced)
            )
            == canonical_name
        ):
            return _target_path_for_produced(produced, "Point", index, step)
    return _scoped_output_path(
        index.context,
        step.scope_id,
        canonical_name or semantic_name,
    )


def _straightening_endpoint_handles_from_reads(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str] | None:
    """从 step reads 中读取前序拉直 recipe 暴露的 endpoint facts。"""
    candidates: list[tuple[str, str]] = []
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "Point":
            continue
        provenance = next(
            (
                item
                for item in reversed(index.state_write_provenance)
                if item.produced_handle == handle
                and item.runtime_type == "Point"
            ),
            None,
        )
        semantic_role = (
            provenance.identity_role
            if provenance is not None and provenance.identity_role is not None
            else _semantic_name(handle)
        )
        candidates.append((semantic_role, handle))
    return collect_straightening_endpoint_handles(candidates)


def _handle_for_runtime_path(
    index: CanonicalRuntimeBindingIndex,
    step: FunctionalCompileStepView,
    path: str,
    *,
    expected_type: str,
) -> str:
    matches = tuple(
        handle
        for handle in _compile_input_handles(step)
        if (
            (binding := index.bindings.get(handle)) is not None
            and binding.path == path
            and runtime_type_compatible(binding.value_type, expected_type)
        )
    )
    if len(matches) != 1:
        raise StrategyDraftValidationError(
            "functional.path_transformation_state_unavailable: "
            f"step={step.step_id}, path={path}, matches={list(matches)}"
        )
    return matches[0]


def _required_path_role_point_input(
    role: ResolvedPathTransformationRole,
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, tuple[tuple[MethodInvocation, ...], dict[str, str]]]:
    if index.functional_consumer_identity_mode is not None:
        if role.state_version_id is None or role.runtime_path is None:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.path_transformation_role_version_unresolved: "
                f"step={step.step_id}, role={role.role}"
            )
        exact_path = index.runtime_path_for_state_version(
            role.state_version_id,
            consumer_scope_id=step.scope_id,
            consumer=f"{step.step_id}.{role.role}",
        )
        if exact_path != role.runtime_path:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"step={step.step_id}, role={role.role}"
            )
        return exact_path, ((), {})
    if role.state_handle is None:
        raise StrategyDraftValidationError(
            "functional.path_transformation_state_unavailable: "
            f"step={step.step_id}, role={role.role}, "
            f"object_ref={role.object_ref}"
        )
    return _point_value_path_or_prepare(role.state_handle, step, index)


def _required_path_role_source(
    role: ResolvedPathTransformationRole,
    *,
    step: FunctionalCompileStepView,
) -> str:
    if len(role.source_handles) != 1:
        raise StrategyDraftValidationError(
            "functional.path_transformation_state_unavailable: "
            f"step={step.step_id}, role={role.role}, "
            f"source_count={len(role.source_handles)}"
        )
    return role.source_handles[0]


def _point_handle_from_point_state_fact(
    handle: str,
    step: FunctionalCompileStepView,
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


def _visible_point_state_path_for_name(
    point_name: str,
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
            description=f"{_compile_capability_id(step) or step.step_id} 自动创建的辅助点",
        )
    raise StrategyDraftValidationError(
        f"auxiliary_point_handle_exhausted: {step.step_id}"
    )

def _auto_created_recipe_point_scope(step: FunctionalCompileStepView) -> str:
    """Match auto-created helper visibility to the recipe's public output scope."""
    for item in _compile_return_outputs(step):
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
    step: FunctionalCompileStepView,
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
            not _step_declares_runtime_type(step, index, value_type)
            and _step_has_quadratic_source_reads(step, index)
        )
    raise StrategyDraftValidationError(f"prep_trigger_selector_missing: {selector}")


def _step_declares_runtime_type(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    value_type: str,
) -> bool:
    """Match the read-closed Function adapter boundary used by the main call."""
    return any(
        (binding := index.bindings.get(handle)) is not None
        and binding.value_type == value_type
        for handle in _compile_input_handles(step)
    )


def _step_has_quadratic_source_reads(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 step 是否具备临时构造 Parabola 的题设来源。"""
    # The Function template itself is a sufficient source. The shared
    # quadratic constraint analyzer decides whether it is closed, single-free,
    # or underdetermined; duplicating that symbolic check in this trigger would
    # make prep applicability drift from runtime behavior.
    return any(handle.startswith("function:") for handle in _compile_input_handles(step))


def _prep_outputs(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    spec_outputs: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
    binding_rules: MethodBindingRuleRegistry,
    *,
    input_bindings: Mapping[str, str] | None = None,
    input_specs: Mapping[str, Any] | None = None,
    projected_output_keys: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """为 invocation 生成输出路径，避免声明 method 不会实际返回的可选输出。"""
    output_names: list[str] = []
    projected_output_keys = projected_output_keys or {}
    for produced in _compile_return_outputs(step):
        output_name = projected_output_keys.get(produced.handle)
        if output_name is not None and output_name not in spec_outputs:
            raise StrategyDraftValidationError(
                "planner_configuration_error: projected Function return "
                f"does not map to a MethodSpec output: method={method_id}, "
                f"handle={produced.handle}, output={output_name}"
            )
        if output_name is None:
            output_name = _output_key_for_produced(
                method_id,
                produced,
                spec_outputs,
                step,
                index,
            )
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
        output_names = _active_polymorphic_output_names(
            spec_outputs,
            input_bindings=input_bindings or {},
            input_specs=input_specs or {},
            index=index,
        )
    return {name: _temp(step.step_id, name) for name in _unique_ordered(output_names)}


def _active_polymorphic_output_names(
    spec_outputs: Mapping[str, str],
    *,
    input_bindings: Mapping[str, str],
    input_specs: Mapping[str, Any],
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """Select the output variant matching a union-typed runtime input.

    Some pure methods preserve an input's semantic runtime type and therefore
    declare one output key per variant. When a Functional call does not
    materialize an optional return, the compiler still needs one temporary
    output for dry-run execution; requesting every declared variant would ask
    the method for outputs it intentionally does not emit.
    """
    variant_outputs: set[str] = set()
    active_outputs: set[str] = set()
    for input_name, input_spec in input_specs.items():
        accepted_types = set(
            split_runtime_types(str(getattr(input_spec, "type", "")))
        )
        matching_outputs = {
            output_name
            for output_name, output_type in spec_outputs.items()
            if output_type in accepted_types
        }
        if len(matching_outputs) <= 1:
            continue
        path = input_bindings.get(input_name)
        if path is None:
            continue
        actual_types = {
            binding.value_type
            for binding in index.bindings.values()
            if binding.path == path
        }
        matching_active = {
            output_name
            for output_name in matching_outputs
            if spec_outputs[output_name] in actual_types
        }
        if not matching_active:
            continue
        variant_outputs.update(matching_outputs)
        active_outputs.update(matching_active)
    if not variant_outputs or not active_outputs:
        return list(spec_outputs)
    return [
        output_name
        for output_name in spec_outputs
        if output_name not in variant_outputs or output_name in active_outputs
    ]


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
    step: FunctionalCompileStepView,
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
        "Symbol": ("parameter", "symbol"),
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
    step: FunctionalCompileStepView,
    method_id: str,
    outputs: dict[str, str],
    output_types: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
    binding_rules: MethodBindingRuleRegistry,
    *,
    point_transition: bool = False,
    projected_state_writes: tuple[ProjectedStateWrite, ...] = (),
    projected_output_keys: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """根据 produces/answer 自动生成 promote_outputs。"""
    promote: dict[str, str] = {}
    source_to_produced: dict[str, list[ProducedFact]] = {}
    point_transition = point_transition or _binding_rule_writes_point_transition(
        method_id,
        binding_rules,
    )
    projected_output_keys = projected_output_keys or {}
    for produced in _compile_return_outputs(step):
        output_name = projected_output_keys.get(produced.handle)
        if output_name is None:
            output_name = _output_key_for_produced(
                method_id,
                produced,
                output_types,
                step,
                index,
            )
        if output_name is None or output_name not in outputs:
            continue
        target = _target_path_for_produced(
            produced,
            output_types[output_name],
            index,
            step,
            point_transition=(
                point_transition
                or _produced_is_projected_point_transition(
                    step,
                    produced,
                    projected_state_writes,
                )
            ),
        )
        _ensure_declaration_for_promote_target(target, output_types[output_name], index)
        source = outputs[output_name]
        source_to_produced.setdefault(source, []).append(produced)
        # 同一个 method output 可能同时服务最终答案和可复用 fact alias。
        # promote 只能写一个目标。通常优先 answer；若共享计算执行在 answer
        # scope 之外，则落到 canonical fact，answer handle 注册为同一路径的 alias。
        # 这样公共状态仍可复用，也不会让父 scope 越权写入子问题。
        if source not in promote or (
            produced.handle.startswith("answer:")
            and _answer_promote_scope_is_visible_from_step(
                target,
                step=step,
                index=index,
            )
        ):
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


def _produced_is_projected_point_transition(
    step: FunctionalCompileStepView,
    produced: ProducedFact,
    projected_state_writes: tuple[ProjectedStateWrite, ...],
) -> bool:
    return any(
        write.step_id == step.step_id
        and write.produced_handle == produced.handle
        and write.runtime_type == "Point"
        and write.write_mode == "transition"
        for write in projected_state_writes
    )


def _answer_promote_scope_is_visible_from_step(
    target: str,
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    target_scope = ContextPath.parse(target).scope_id
    return target_scope in index.handle_registry.ancestor_scopes(step.scope_id)


def _binding_rule_writes_point_transition(
    method_id: str,
    binding_rules: MethodBindingRuleRegistry,
) -> bool:
    rule = binding_rules.rule_for(method_id)
    if rule is None:
        return False
    return any(
        binding.selector == "point_transition_target"
        for binding in rule.input_bindings
    )


def _function_writes_point_transition(function: Any | None) -> bool:
    if function is None:
        return False
    return any(
        item.runtime_type == "Point" and item.write_mode == "transition"
        for item in function.returns
    )

def _validate_no_ambiguous_multi_produced_output_aliases(
    step: FunctionalCompileStepView,
    method_id: str,
    source_to_produced: Mapping[str, list[ProducedFact]],
    index: CanonicalRuntimeBindingIndex,
) -> None:
    """防止 single method output 被多个不同语义 fact 静默共用。

    answer + fact alias 是合法的：同一个 runtime output 可同时作为答案与后续
    可复用 fact。两个非 answer fact 若语义名不同，则表示 LLM 把多次函数调用
    合并成了一个 Functional call，必须在 reconciliation 或 retry 中拆开。
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
                companion.output_name,
            )
        )
    return result


def _companion_target_path(
    step: FunctionalCompileStepView,
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
    if selector == "axis_parameter_symbol":
        handle = _axis_parameter_symbol_handle(step, index)
        return _runtime_path_for_scope(
            index.context,
            _handle_scope(handle),
            "symbols",
            _handle_name(handle),
        )
    raise StrategyDraftValidationError(f"companion_target_selector_missing: {selector}")


def _answer_target_scope_from_step(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """从 QuestionGoal target_path 读取 answer 实际写入 scope。"""
    handles = [_compile_target_handle(step), *(item.handle for item in _compile_return_outputs(step))]
    for handle in handles:
        if not handle.startswith("answer:"):
            continue
        goal = index.question_goals.get(handle)
        if goal is not None:
            return ContextPath.parse(goal.target_path).scope_id
    return _answer_scope_from_step(step)


def _companion_registration_handle(
    step: FunctionalCompileStepView,
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
    if selector == "axis_parameter_symbol":
        return _axis_parameter_symbol_handle(step, index)
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


def _axis_parameter_symbol_handle(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    point_object_id = _point_return_object_id(step, index)
    point_handle = (
        point_object_id.value
        if point_object_id is not None
        else _point_output_handle(step, index)
    )
    return dependent_role_object_ref(
        source_object_ref=point_handle,
        semantic_role="axis_parameter",
        scope_id=_handle_scope(point_handle),
        runtime_type="Symbol",
    )


def _point_object_id_for_handle(
    handle: str,
    index: CanonicalRuntimeBindingIndex,
) -> MathObjectId | None:
    projected = index.projected_state_write_for_handle(handle)
    if projected is not None and projected.math_object_id is not None:
        return projected.math_object_id
    return MathObjectRegistry.from_sources(
        index.handle_registry
    ).resolve(handle)


def _point_return_object_id(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> MathObjectId | None:
    candidates = {
        write.math_object_id
        for write in index.projected_state_writes
        if write.step_id == step.step_id
        and write.runtime_type == "Point"
        and write.math_object_id is not None
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    if index.functional_consumer_identity_mode == "authoritative":
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.state_identity_incomplete: "
            f"step={step.step_id}, return_type=Point, "
            f"identity_count={len(candidates)}"
        )
    return None

def _produced_registrations(
    step: FunctionalCompileStepView,
    method_id: str,
    promote: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
) -> list[tuple[str, str, str]]:
    """返回 ``(handle, output_key, promoted_path)`` 注册信息。"""
    result: list[tuple[str, str, str]] = []
    for produced in _compile_return_outputs(step):
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


def _macro_write_provenance(
    step: FunctionalCompileStepView,
    *,
    recipe_id: str,
    bindings: tuple[tuple[ProducedFact, MacroReturnSpec], ...],
    declared_evidence_roles: tuple[str, ...],
    plan: StepPlan,
    function_specs: FunctionSpecRegistry,
    index: CanonicalRuntimeBindingIndex,
    prior: tuple[StateWriteProvenance, ...],
    projected_state_writes: tuple[ProjectedStateWrite, ...],
) -> tuple[StateWriteProvenance, ...]:
    return tuple(
        _state_write_provenance(
            step,
            capability_id=recipe_id,
            produced_handle=produced.handle,
            output_key=return_spec.output_key or return_spec.name,
            runtime_type=return_spec.runtime_type,
            identity_policy=return_spec.identity_policy,
            identity_role=return_spec.semantic_role or return_spec.name,
            evidence_roles=declared_evidence_roles,
            identity_arg=return_spec.identity_arg,
            write_mode=return_spec.write_mode,
            input_path=None,
            index=index,
            prior=prior,
            projected_write=_projected_state_write(
                step.step_id,
                produced.handle,
                projected_state_writes,
            ),
            closure_ignored_symbol_names=(
                _macro_result_form_ignored_symbol_names(
                    return_spec,
                    plan=plan,
                    function_specs=function_specs,
                    index=index,
                    scope_id=step.scope_id,
                )
            ),
        )
        for produced, return_spec in bindings
    )


def _macro_result_form_ignored_symbol_names(
    return_spec: MacroReturnSpec,
    *,
    plan: StepPlan,
    function_specs: FunctionSpecRegistry,
    index: CanonicalRuntimeBindingIndex,
    scope_id: str,
) -> tuple[str, ...]:
    """Resolve closure exclusions from the Macro return's internal Function."""
    output_key = return_spec.output_key
    if output_key is None or "." not in output_key:
        return ()
    method_id, method_output = output_key.rsplit(".", 1)
    function = function_specs.get(method_id)
    if function is None:
        return ()
    function_return = next(
        (
            item
            for item in function.returns
            if method_output in {item.name, item.output_key}
        ),
        None,
    )
    if function_return is None:
        return ()
    invocation = next(
        (
            item
            for item in reversed(plan.invocations)
            if item.method_id == method_id
        ),
        None,
    )
    return _result_form_ignored_symbol_names(
        function_return,
        invocation=invocation,
        index=index,
        scope_id=scope_id,
    )


def _function_write_provenance(
    step: FunctionalCompileStepView,
    *,
    method_id: str,
    plan: StepPlan,
    registrations: list[tuple[str, str, str]],
    companion_registrations: list[RuntimeHandleBinding],
    function_specs: FunctionSpecRegistry,
    index: CanonicalRuntimeBindingIndex,
    prior: tuple[StateWriteProvenance, ...],
    projected_state_writes: tuple[ProjectedStateWrite, ...],
) -> tuple[StateWriteProvenance, ...]:
    function = function_specs.get(method_id)
    if function is None:
        return ()
    returns = {
        item.output_key: item
        for item in function.returns
        if item.output_key is not None
    }
    invocation = next(
        (
            item
            for item in reversed(plan.invocations)
            if item.method_id == method_id
        ),
        None,
    )
    result: list[StateWriteProvenance] = []
    all_registrations = [
        *registrations,
        *(
            (
                item.handle,
                item.output_key or _output_key_for_companion_path(item.path, plan),
                item.path,
            )
            for item in companion_registrations
        ),
    ]
    for produced_handle, output_key, _path in all_registrations:
        return_spec = returns.get(output_key)
        if return_spec is None:
            continue
        projected_write = _projected_state_write(
            step.step_id,
            produced_handle,
            projected_state_writes,
        )
        if projected_write is None:
            matching_writes = tuple(
                item
                for item in projected_state_writes
                if item.step_id == step.step_id
                and item.return_name
                in {return_spec.name, return_spec.output_key}
            )
            if len(matching_writes) == 1:
                projected_write = matching_writes[0]
        if (
            projected_write is not None
            and projected_write.return_name is not None
            and projected_write.return_name
            not in {return_spec.name, return_spec.output_key}
        ):
            raise StrategyDraftValidationError(
                "planner.contract_runtime_identity_drift: "
                f"step={step.step_id}, handle={produced_handle}, "
                f"projected_return={projected_write.return_name}, "
                f"compiled_output={output_key}"
            )
        input_path = (
            invocation.inputs.get(return_spec.identity_arg)
            if invocation is not None and return_spec.identity_arg is not None
            else None
        )
        result.append(
            _state_write_provenance(
                step,
                capability_id=method_id,
                produced_handle=produced_handle,
                output_key=output_key,
                runtime_type=return_spec.runtime_type,
                identity_policy=return_spec.identity_policy,
                identity_role=return_spec.semantic_role or return_spec.name,
                evidence_roles=(),
                identity_arg=return_spec.identity_arg,
                write_mode=return_spec.write_mode,
                input_path=input_path,
                index=index,
                prior=prior,
                projected_write=projected_write,
                closure_ignored_symbol_names=(
                    _result_form_ignored_symbol_names(
                        return_spec,
                        invocation=invocation,
                        index=index,
                        scope_id=step.scope_id,
                    )
                ),
            )
        )
    return _project_compiled_return_object_roles(
        tuple(result),
        function=function,
        invocation=invocation,
        scope_id=step.scope_id,
        index=index,
        prior=prior,
    )


def _project_compiled_return_object_roles(
    provenance: tuple[StateWriteProvenance, ...],
    *,
    function: FunctionSpec,
    invocation: MethodInvocation | None,
    scope_id: str,
    index: CanonicalRuntimeBindingIndex,
    prior: tuple[StateWriteProvenance, ...],
) -> tuple[StateWriteProvenance, ...]:
    """Execute FunctionSpec object-role projections for runtime provenance."""

    if invocation is None:
        return provenance
    returns_by_output = {
        item.output_key: item
        for item in function.returns
        if item.output_key is not None
    }
    writes_by_output = {item.output_key: item for item in provenance}
    args_by_name = {item.name: item for item in function.args}
    result: list[StateWriteProvenance] = []
    for write in provenance:
        return_spec = returns_by_output.get(write.output_key)
        if return_spec is None:
            result.append(write)
            continue
        roles: list[StateObjectRoleBinding] = []
        for projection in return_spec.object_role_projections:
            source: StateWriteProvenance | None = None
            source_handle: str | None = None
            object_refs: tuple[str, ...] = ()
            if projection.source_return is not None:
                sibling_spec = next(
                    (
                        item
                        for item in function.returns
                        if item.name == projection.source_return
                    ),
                    None,
                )
                source = (
                    writes_by_output.get(sibling_spec.output_key)
                    if sibling_spec is not None
                    and sibling_spec.output_key is not None
                    else None
                )
            elif projection.source_arg is not None:
                arg_spec = args_by_name.get(projection.source_arg)
                method_input = (
                    arg_spec.method_input or arg_spec.name
                    if arg_spec is not None
                    else projection.source_arg
                )
                input_path = invocation.inputs.get(method_input)
                if isinstance(input_path, str):
                    source_handle = _source_handle_for_path(
                        input_path,
                        index,
                        prior,
                    )
                    source = next(
                        (
                            item
                            for item in reversed(prior)
                            if item.produced_handle == source_handle
                        ),
                        None,
                    )
                    if source is None and arg_spec is not None:
                        object_ref = _object_ref_for_compiled_input(
                            input_path,
                            arg_spec.runtime_type,
                            scope_id=scope_id,
                            index=index,
                        )
                        object_refs = (
                            (object_ref,) if object_ref is not None else ()
                        )
                    if (
                        not object_refs
                        and source_handle is not None
                        and projection.source_object_role is not None
                        and source_handle in index.fact_types
                    ):
                        condition_roles = ConditionRoleResolver.object_roles(
                            index.fact_types[source_handle],
                            index.fact_payload(source_handle),
                        )
                        object_refs = dict(condition_roles).get(
                            projection.source_object_role,
                            (),
                        )
            if source is not None:
                object_refs = (
                    state_object_refs_for_role(
                        source.lineage,
                        projection.source_object_role,
                    )
                    if projection.source_object_role is not None
                    else ((source.object_ref,) if source.object_ref else ())
                )
                source_handle = source.produced_handle
            if not object_refs:
                continue
            roles.append(
                StateObjectRoleBinding(
                    role=projection.role,
                    object_refs=tuple(_unique_ordered(object_refs)),
                    source_state_slot_ids=(
                        (source.state_slot_id,)
                        if source is not None
                        and source.state_slot_id is not None
                        else ()
                    ),
                    source_handles=(
                        (source_handle,) if source_handle is not None else ()
                    ),
                    state_requirement=projection.state_requirement,
                )
            )
        if not roles:
            result.append(write)
            continue
        lineage = merge_state_semantic_lineages(
            write.lineage,
            object_roles=roles,
            source_state_slot_ids=tuple(
                slot_id
                for role in roles
                for slot_id in role.source_state_slot_ids
            ),
        )
        result.append(
            replace(
                write,
                lineage=lineage,
                source_state_slot_ids=tuple(
                    _unique_ordered(
                        (
                            *write.source_state_slot_ids,
                            *lineage.source_state_slot_ids,
                        )
                    )
                ),
            )
        )
    return tuple(result)


def _object_ref_for_compiled_input(
    path: str,
    runtime_type: str,
    *,
    scope_id: str,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """Recover immutable input identity before considering path aliases."""

    if runtime_type == "PointRef":
        declaration = index.declarations.get(path)
        if declaration is not None and declaration.type == "PointRef":
            return f"point:{declaration.scope_id}:{declaration.name}"
        try:
            value = index.context.read_path(
                path,
                from_scope_id=scope_id,
                expected_type="PointRef",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            pass
        else:
            if isinstance(value, PointRef):
                return f"point:{value.scope_id}:{value.name}"
    return _object_handle_for_path(path, runtime_type, index)


def _output_key_for_companion_path(path: str, plan: StepPlan) -> str:
    for source, target in plan.promote_outputs.items():
        if target == path:
            return ContextPath.parse(source).key
    raise StrategyDraftValidationError(
        f"companion_output_source_not_found: path={path}, step={plan.step_id}"
    )


def _state_write_provenance(
    step: FunctionalCompileStepView,
    *,
    capability_id: str,
    produced_handle: str,
    output_key: str,
    runtime_type: str,
    identity_policy: StateIdentityPolicy,
    identity_role: str,
    evidence_roles: tuple[str, ...],
    identity_arg: str | None,
    write_mode: StateWriteMode,
    input_path: str | None,
    index: CanonicalRuntimeBindingIndex,
    prior: tuple[StateWriteProvenance, ...],
    projected_write: ProjectedStateWrite | None,
    closure_ignored_symbol_names: tuple[str, ...] = (),
) -> StateWriteProvenance:
    del identity_arg
    source_handle = _source_handle_for_path(input_path, index, prior)
    source = next(
        (item for item in reversed(prior) if item.produced_handle == source_handle),
        None,
    )
    if identity_policy == "derived_role":
        object_ref = (
            produced_handle
            if runtime_type == "Symbol"
            else derived_role_object_ref(
                call_id=step.step_id,
                semantic_role=identity_role,
                scope_id=step.scope_id,
                runtime_type=runtime_type,
            )
        )
    elif identity_policy == "preserve_input_object":
        object_ref = _preserved_object_ref(
            runtime_type=runtime_type,
            input_path=input_path,
            source_handle=source_handle,
            source=source,
            produced_handle=produced_handle,
            step=step,
            index=index,
        )
    elif identity_policy == "target_object":
        object_ref = (
            _point_handle_for_path(input_path, index)
            or _point_entity_for_state(produced_handle, step, index)
        )
    else:
        object_ref = None
    if projected_write is not None and projected_write.object_ref is not None:
        # Functional reconciliation has already resolved the MathObject identity.
        # Macro compilation may not expose a direct legacy input path from which
        # the same identity can be reconstructed, so the typed sidecar is
        # authoritative here.
        object_ref = projected_write.object_ref
    source_handles = tuple(
        handle
        for handle in (source_handle, *_compile_input_handles(step))
        if isinstance(handle, str) and handle
    )
    previous_write = _previous_state_write(
        prior,
        projected_write=projected_write,
        object_ref=object_ref,
        runtime_type=runtime_type,
        scope_id=step.scope_id,
    )
    effective_write_mode: StateWriteMode = (
        projected_write.write_mode if projected_write is not None else write_mode
    )
    if write_mode == "transition" and previous_write is None and object_ref is not None:
        # Initial ProblemIR states are not represented in the prior write
        # provenance ledger. The first derived value starts that ledger; later
        # writes to the same object/state must still be explicit transitions.
        effective_write_mode = "create"
    if (
        effective_write_mode == "create"
        and identity_policy == "target_object"
        and previous_write is not None
    ):
        effective_write_mode = "transition"
    if effective_write_mode == "transition":
        _validate_state_transition(
            step,
            object_ref=object_ref,
            previous_write=previous_write,
            prior=prior,
            index=index,
            transition_kind=(
                projected_write.transition_kind
                if projected_write is not None
                else None
            ),
            projected_previous_write_step_id=(
                projected_write.previous_write_step_id
                if projected_write is not None
                else None
            ),
        )
    state_kind = state_kind_for_runtime_type(runtime_type)
    # The compiler/runtime ledger retains its legacy destination key through
    # B1. The typed projected slot is carried beside it and becomes the final
    # ledger authority only in B3, when Macro internal writes are mapped too.
    state_slot_id = (
        f"{object_ref}.{state_kind}@{step.scope_id}:{runtime_type}"
        if object_ref is not None
        else None
    )
    lineage = _compiled_state_lineage(
        identity_policy=identity_policy,
        write_mode=write_mode,
        identity_role=identity_role,
        evidence_roles=evidence_roles,
        source=source,
        projected_write=projected_write,
    )
    return StateWriteProvenance(
        step_id=step.step_id,
        scope_id=step.scope_id,
        capability_id=capability_id,
        produced_handle=produced_handle,
        output_key=output_key,
        runtime_type=runtime_type,
        identity_policy=identity_policy,
        identity_role=identity_role,
        evidence_roles=evidence_roles,
        object_ref=object_ref,
        source_handles=tuple(_unique_ordered(source_handles)),
        source_step_id=source.step_id if source is not None else None,
        state_slot_id=state_slot_id,
        write_mode=effective_write_mode,
        previous_write_step_id=(
            previous_write.step_id if previous_write is not None else None
        ),
        closure_ignored_symbol_names=tuple(
            _unique_ordered(
                (
                    *(source.closure_ignored_symbol_names if source else ()),
                    *closure_ignored_symbol_names,
                )
            )
        ),
        transition_kind=(
            projected_write.transition_kind
            if projected_write is not None
            else None
        ),
        dependency_object_refs=(
            projected_write.dependency_object_refs
            if projected_write is not None
            else ()
        ),
        source_state_slot_ids=(
            projected_write.source_state_slot_ids
            if projected_write is not None
            else lineage.source_state_slot_ids
        ),
        lineage=lineage,
        math_object_id=(
            projected_write.math_object_id
            if projected_write is not None
            else None
        ),
        logical_state_key=(
            projected_write.logical_state_key
            if projected_write is not None
            else None
        ),
        typed_slot_id=(
            projected_write.typed_slot_id
            if projected_write is not None
            else None
        ),
        selected_version_id=(
            projected_write.selected_version_id
            if projected_write is not None
            else None
        ),
        previous_version_id=(
            projected_write.previous_version_id
            if projected_write is not None
            else None
        ),
        computation_key=(
            projected_write.computation_key
            if projected_write is not None
            else None
        ),
        source_version_ids=(
            projected_write.source_version_ids
            if projected_write is not None
            else ()
        ),
        allocation_action=(
            projected_write.allocation_action
            if projected_write is not None
            else None
        ),
        free_symbol_ids=(
            projected_write.free_symbol_ids
            if projected_write is not None
            else ()
        ),
        return_name=(
            projected_write.return_name
            if projected_write is not None
            else None
        ),
        valid_scope_id=(
            projected_write.valid_scope_id
            if projected_write is not None
            else None
        ),
        canonical_producer_call_id=(
            projected_write.canonical_producer_call_id
            if projected_write is not None
            else step.step_id
        ),
    )


def _previous_state_write(
    prior: tuple[StateWriteProvenance, ...],
    *,
    projected_write: ProjectedStateWrite | None,
    object_ref: str | None,
    runtime_type: str,
    scope_id: str,
) -> StateWriteProvenance | None:
    """Resolve the exact typed predecessor before using legacy scope matching."""

    projected_previous_version = (
        projected_write.previous_version_id
        if projected_write is not None
        else None
    )
    if projected_previous_version is not None:
        exact = next(
            (
                item
                for item in reversed(prior)
                if item.selected_version_id == projected_previous_version
            ),
            None,
        )
        if exact is not None:
            return exact
    return next(
        (
            item
            for item in reversed(prior)
            if item.object_ref is not None
            and item.object_ref == object_ref
            and item.runtime_type == runtime_type
            and item.scope_id == scope_id
        ),
        None,
    )


def _compiled_state_lineage(
    *,
    identity_policy: StateIdentityPolicy,
    write_mode: StateWriteMode,
    identity_role: str,
    evidence_roles: tuple[str, ...],
    source: StateWriteProvenance | None,
    projected_write: ProjectedStateWrite | None,
) -> StateSemanticLineage:
    if projected_write is not None:
        return projected_write.lineage
    inherited = (
        (source.lineage,)
        if identity_policy == "preserve_input_object"
        and write_mode == "transition"
        and source is not None
        else ()
    )
    return merge_state_semantic_lineages(
        *inherited,
        semantic_roles=(identity_role,),
        evidence_tags=evidence_roles,
        source_state_slot_ids=(
            (source.state_slot_id,)
            if source is not None and source.state_slot_id is not None
            else ()
        ),
    )


def _projected_state_write(
    step_id: str,
    produced_handle: str,
    projected_state_writes: tuple[ProjectedStateWrite, ...],
) -> ProjectedStateWrite | None:
    matches = tuple(
        item
        for item in projected_state_writes
        if item.step_id == step_id and item.produced_handle == produced_handle
    )
    if len(matches) > 1:
        raise StrategyDraftValidationError(
            "planner_configuration_error: duplicate projected state write: "
            f"step={step_id}, handle={produced_handle}"
        )
    return matches[0] if matches else None


def _enrich_write_provenance_runtime_symbols(
    provenance: tuple[StateWriteProvenance, ...],
    *,
    registrations: tuple[RuntimeHandleBinding, ...],
    context: RuntimeContext,
    handle_registry: CanonicalHandleRegistry,
    known_provenance: tuple[StateWriteProvenance, ...] = (),
) -> tuple[StateWriteProvenance, ...]:
    paths = {item.handle: item.path for item in registrations}
    runtime_values: dict[str, Any] = {}
    for item in provenance:
        path = paths.get(item.produced_handle)
        if path is None:
            continue
        try:
            runtime_values[item.produced_handle] = context.read_path(
                path,
                from_scope_id=item.scope_id,
                expected_type=item.runtime_type,
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
    coefficient_sources = tuple(
        (item, runtime_values.get(item.produced_handle))
        for item in provenance
        if item.runtime_type == "Coefficients"
        and isinstance(runtime_values.get(item.produced_handle), Mapping)
    )
    parameter_value_sources = tuple(
        (item, runtime_values.get(item.produced_handle))
        for item in provenance
        if item.runtime_type == "ParameterValue"
        and item.object_ref is not None
        and item.produced_handle in runtime_values
    )
    result: list[StateWriteProvenance] = []
    object_registry = MathObjectRegistry.from_sources(handle_registry)
    declared_runtime_symbols: dict[sp.Symbol, MathObjectId] = {}
    for binding in registrations:
        if binding.value_type != "Symbol":
            continue
        try:
            runtime_symbol = context.read_path(
                binding.path,
                from_scope_id=ContextPath.parse(binding.path).scope_id,
                expected_type="Symbol",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        object_id = object_registry.resolve(binding.handle)
        if isinstance(runtime_symbol, sp.Symbol) and object_id is not None:
            if object_id.kind == "symbol":
                declared_runtime_symbols[runtime_symbol] = object_id
    for source in (*known_provenance, *provenance):
        path = paths.get(source.produced_handle)
        if path is None or source.runtime_type != "Symbol":
            continue
        try:
            runtime_symbol = context.read_path(
                path,
                from_scope_id=source.scope_id,
                expected_type="Symbol",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        object_id = source.math_object_id
        if object_id is None and source.object_ref is not None:
            object_id = (
                object_registry.resolve(source.object_ref)
                or object_registry.register_handle(source.object_ref)
            )
        if isinstance(runtime_symbol, sp.Symbol) and object_id is not None:
            if object_id.kind == "symbol":
                declared_runtime_symbols[runtime_symbol] = object_id
    for source in provenance:
        value = runtime_values.get(source.produced_handle)
        if not isinstance(value, sp.Symbol):
            continue
        object_id = source.math_object_id
        if object_id is None and source.object_ref is not None:
            object_id = (
                object_registry.resolve(source.object_ref)
                or object_registry.register_handle(source.object_ref)
            )
        if object_id is not None and object_id.kind == "symbol":
            declared_runtime_symbols[value] = object_id
    for item in provenance:
        path = paths.get(item.produced_handle)
        free_symbols: set[Any] = set()
        lineage = item.lineage
        if path is not None:
            try:
                value = runtime_values[item.produced_handle]
                _enrich_runtime_lineage_payload(item, value)
                _validate_runtime_lineage_payload(item, value)
                free_symbols.update(runtime_free_symbol_names(value))
            except StrategyDraftValidationError:
                raise
            except (KeyError, PermissionError, TypeError, ValueError):
                pass
        if lineage.symbol_closures:
            closures: list[StateSymbolClosureBinding] = []
            for closure in lineage.symbol_closures:
                target_name = closure.target_object_ref.rsplit(":", 1)[-1]
                matches = tuple(
                    (source, value)
                    for source, value in parameter_value_sources
                    if source.object_ref == closure.target_object_ref
                )
                coefficient_matches = tuple(
                    (source, value[symbol])
                    for source, value in coefficient_sources
                    for symbol in value
                    if str(symbol) == target_name
                )
                if not matches:
                    matches = coefficient_matches
                if len(matches) != 1:
                    closures.append(closure)
                    continue
                source, expression = matches[0]
                dependency_refs_by_name = {
                    item.rsplit(":", 1)[-1]: item
                    for item in closure.dependency_object_refs
                }
                closures.append(
                    StateSymbolClosureBinding(
                        target_object_ref=closure.target_object_ref,
                        dependency_object_refs=tuple(
                            dependency_refs_by_name.get(
                                str(symbol),
                                f"symbol:problem:{symbol}",
                            )
                            for symbol in sorted(
                                getattr(expression, "free_symbols", set()),
                                key=lambda current: current.name,
                            )
                        ),
                        expression=str(sp.simplify(expression)),
                        source_state_slot_ids=tuple(
                            _unique_ordered(
                                (
                                    *closure.source_state_slot_ids,
                                    *((source.state_slot_id,)
                                      if source.state_slot_id is not None
                                      else ()),
                                )
                            )
                        ),
                        source_handles=tuple(
                            _unique_ordered(
                                (
                                    *closure.source_handles,
                                    source.produced_handle,
                                )
                            )
                        ),
                    )
                )
            lineage = merge_state_semantic_lineages(
                lineage,
                symbol_closures=closures,
            )
        free_symbol_names = tuple(
            sorted(
                set(map(str, free_symbols))
                - set(item.closure_ignored_symbol_names)
            )
        )
        free_symbol_ids = (
            runtime_free_symbol_ids(
                runtime_values[item.produced_handle],
                context=context,
                registry=object_registry,
                declared_runtime_symbols=declared_runtime_symbols,
                ignored_symbol_names=item.closure_ignored_symbol_names,
            )
            if item.produced_handle in runtime_values
            else ()
        )
        result.append(
            replace(
                item,
                free_symbol_names=free_symbol_names,
                free_symbol_ids=free_symbol_ids,
                result_form=(
                    item.result_form
                    or (
                        (
                            "open_expression"
                            if free_symbol_names
                            else "closed_value"
                        )
                        if item.runtime_type
                        in {"Expression", "MinimumExpression"}
                        else (
                            "open_state"
                            if free_symbol_names
                            else "closed_state"
                        )
                    )
                ),
                lineage=lineage,
            )
        )
    return tuple(result)


def _result_form_ignored_symbol_names(
    return_spec: FunctionReturnSpec,
    *,
    invocation: MethodInvocation | None,
    index: CanonicalRuntimeBindingIndex,
    scope_id: str,
) -> tuple[str, ...]:
    """Resolve structural variables excluded from result closure checks.

    The declaration names method inputs, not concrete symbols. This keeps the
    closure rule reusable for any independent variable name while provenance
    records the actual symbol used by this invocation.
    """
    form = return_spec.scalar_result_form
    if form is None or invocation is None:
        return ()
    names: list[str] = []
    for input_name in form.ignored_symbol_input_args:
        path = invocation.inputs.get(input_name)
        if path is None:
            continue
        try:
            value = index.context.read_path(
                path,
                from_scope_id=scope_id,
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        if isinstance(value, sp.Symbol):
            names.append(str(value))
    return tuple(_unique_ordered(names))


def _validate_runtime_lineage_payload(
    provenance: StateWriteProvenance,
    value: Any,
) -> None:
    """Detect contract/runtime identity drift for structured state payloads."""
    if provenance.runtime_type != "PathTransformation" or not isinstance(
        value,
        dict,
    ):
        return
    expected = state_object_refs_for_role(
        provenance.lineage,
        "moving_object",
    )
    actual = value.get("moving_point_ref")
    if not expected:
        return
    if not isinstance(actual, str) or actual not in expected:
        raise StrategyDraftValidationError(
            "planner.contract_runtime_identity_drift: "
            f"step={provenance.step_id}, role=moving_object, "
            f"expected={','.join(expected)}, actual={actual or 'missing'}"
        )


def _enrich_runtime_lineage_payload(
    provenance: StateWriteProvenance,
    value: Any,
) -> None:
    """Attach canonical role refs while keeping runtime names display-only."""
    if provenance.runtime_type != "PathTransformation" or not isinstance(
        value,
        dict,
    ):
        return
    moving_refs = state_object_refs_for_role(
        provenance.lineage,
        "moving_object",
    )
    if "moving_point_ref" not in value and len(moving_refs) == 1:
        value["moving_point_ref"] = moving_refs[0]
    fixed_refs = tuple(
        refs[0]
        for role in ("fixed_endpoint_1", "fixed_endpoint_2")
        if len(
            refs := state_object_refs_for_role(
                provenance.lineage,
                role,
            )
        )
        == 1
    )
    if "fixed_endpoint_refs" not in value and len(fixed_refs) == 2:
        value["fixed_endpoint_refs"] = fixed_refs
    auxiliary_refs = state_object_refs_for_role(
        provenance.lineage,
        "auxiliary_object",
    )
    if "auxiliary_point_ref" not in value and len(auxiliary_refs) == 1:
        value["auxiliary_point_ref"] = auxiliary_refs[0]


def _validate_state_transition(
    step: FunctionalCompileStepView,
    *,
    object_ref: str | None,
    previous_write: StateWriteProvenance | None,
    prior: tuple[StateWriteProvenance, ...],
    index: CanonicalRuntimeBindingIndex,
    transition_kind: Literal["direct", "dependency_refinement"] | None,
    projected_previous_write_step_id: str | None,
) -> None:
    if object_ref is None or previous_write is None:
        raise StrategyDraftValidationError(
            "function.transition_source_missing: "
            f"step={step.step_id}, object_ref={object_ref or 'unknown'}"
        )
    if not index.context.is_visible(step.scope_id, previous_write.scope_id):
        raise StrategyDraftValidationError(
            "function.transition_scope_invisible: "
            f"step={step.step_id}, previous_step={previous_write.step_id}"
        )
    if transition_kind == "dependency_refinement":
        if projected_previous_write_step_id != previous_write.step_id:
            raise StrategyDraftValidationError(
                "function.transition_previous_write_mismatch: "
                f"step={step.step_id}, expected={previous_write.step_id}, "
                f"actual={projected_previous_write_step_id}"
            )
        return
    if projected_previous_write_step_id == previous_write.step_id:
        # FunctionalPlan auto arguments do not become public wire arguments;
        # reconciliation's typed transition sidecar is the dependency proof.
        return
    by_handle = {item.produced_handle: item for item in prior}
    pending = list(_compile_input_handles(step))
    visited: set[str] = set()
    while pending:
        handle = pending.pop()
        if handle in visited:
            continue
        visited.add(handle)
        if handle == previous_write.produced_handle:
            return
        source = by_handle.get(handle)
        if source is None:
            continue
        if source.step_id == previous_write.step_id:
            return
        pending.extend(source.source_handles)
    raise StrategyDraftValidationError(
        "function.transition_dependency_missing: "
        f"step={step.step_id}, object_ref={object_ref}, "
        f"previous_step={previous_write.step_id}"
    )


def _expand_point_parameter_substitutions(
    plan: StepPlan,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> StepPlan:
    """Compile every read, identity-matching Point substitution.

    A call may close one Symbol while leaving other Point coordinates
    parameterized. Student-facing consumers apply their own symbolic
    complexity policy instead of narrowing this runtime state transition.
    """
    if len(plan.invocations) != 1:
        return plan
    base = plan.invocations[0]
    point_path = base.inputs.get("point")
    if point_path is None:
        return plan
    try:
        point = index.context.read_path(
            point_path,
            from_scope_id=step.scope_id,
            expected_type="Point",
        ).value
    except (KeyError, PermissionError, TypeError, ValueError) as exc:
        raise StrategyDraftValidationError(
            f"function.arg_missing: method=evaluate_point_at_parameter, arg=point, reason={exc}"
        ) from exc
    free_symbols = {
        symbol
        for coordinate in point
        for symbol in getattr(coordinate, "free_symbols", set())
    }
    if not free_symbols:
        return plan
    substitutions: list[tuple[Any, str, str, str]] = []
    typed_parameter_versions: set[Any] = set()
    for dependency in index.projected_state_dependencies:
        if (
            dependency.step_id != step.step_id
            or dependency.runtime_type is None
            or not runtime_type_compatible(
                "ParameterValue",
                dependency.runtime_type,
            )
            or dependency.state_version_id is None
        ):
            continue
        version_id = dependency.state_version_id
        object_id = version_id.slot_id.logical_key.object_id
        if object_id.kind != "symbol":
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"step={step.step_id}, arg={dependency.arg_name or 'parameter_value'}, "
                f"parameter_object_kind={object_id.kind}"
            )
        value_path = index.runtime_path_for_state_version(
            version_id,
            consumer_scope_id=step.scope_id,
            consumer=(
                f"{step.step_id}."
                f"{dependency.arg_name or 'parameter_value'}"
            ),
        )
        symbol_path = index.runtime_path_for_object_identity(
            object_id,
            expected_type="Symbol",
            consumer_scope_id=step.scope_id,
            consumer=f"{step.step_id}.parameter_symbol",
        )
        symbol = index.context.read_path(
            symbol_path,
            from_scope_id=step.scope_id,
            expected_type="Symbol",
        ).value
        substitutions.append(
            (
                symbol,
                symbol_path,
                value_path,
                dependency.produced_handle,
            )
        )
        typed_parameter_versions.add(version_id)
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "ParameterValue":
            continue
        provenance = next(
            (
                item
                for item in reversed(index.state_write_provenance)
                if item.produced_handle == handle
                and item.runtime_type == "ParameterValue"
            ),
            None,
        )
        if provenance is None or provenance.object_ref is None:
            continue
        if (
            provenance.selected_version_id is not None
            and provenance.selected_version_id in typed_parameter_versions
        ):
            continue
        symbol_binding = index.bindings.get(provenance.object_ref)
        if symbol_binding is None or symbol_binding.value_type != "Symbol":
            raise StrategyDraftValidationError(
                "function.return_identity_unresolved: "
                f"parameter_value={handle}, symbol={provenance.object_ref}"
            )
        symbol = index.context.read_path(
            symbol_binding.path,
            from_scope_id=step.scope_id,
            expected_type="Symbol",
        ).value
        substitutions.append((symbol, symbol_binding.path, binding.path, handle))
    by_symbol = {item[0]: item for item in substitutions}
    ordered_symbols = sorted(
        (symbol for symbol in free_symbols if symbol in by_symbol),
        key=str,
    )
    if not ordered_symbols:
        raise StrategyDraftValidationError(
            "functional.arg_identity_mismatch: "
            f"step={step.step_id}, no read ParameterValue matches the Point's "
            "unresolved Symbol identities"
        )
    ordered = [by_symbol[symbol] for symbol in ordered_symbols]
    final_output = base.outputs["evaluated_point"]
    current_point = point_path
    invocations: list[MethodInvocation] = []
    for index_number, (_symbol, symbol_path, value_path, _handle) in enumerate(ordered):
        output_path = (
            final_output
            if index_number == len(ordered) - 1
            else _temp(step.step_id, f"evaluated_point_{index_number + 1}")
        )
        invocations.append(
            MethodInvocation(
                invocation_id=f"{step.step_id}.evaluate_point_at_parameter.{index_number + 1}",
                method_id="evaluate_point_at_parameter",
                scope=base.scope,
                inputs={
                    "point": current_point,
                    "parameter": symbol_path,
                    "parameter_value": value_path,
                },
                outputs={"evaluated_point": output_path},
            )
        )
        current_point = output_path
    return StepPlan(
        step_id=plan.step_id,
        goal=plan.goal,
        scope=plan.scope,
        invocations=invocations,
        expected_outputs=plan.expected_outputs,
        promote_outputs=plan.promote_outputs,
    )


def _validate_student_single_degree_of_freedom(
    plan: StepPlan,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    transformer_scope: PlanTransformerScope = "single_invocation",
) -> StepPlan:
    """Require an actual symbolic input to contain at most one unknown.

    Reconciliation dependency metadata is intentionally not used here: it is
    conservative and may retain symbols that an upstream runtime calculation
    has already eliminated. The compiled invocation's current typed values are
    the authority for this student-facing complexity check.
    """
    if transformer_scope == "single_invocation":
        if len(plan.invocations) != 1:
            return plan
        invocations = plan.invocations[:1]
    else:
        invocations = plan.invocations
    symbolic_types = {"Expression", "MinimumExpression", "Point", "Parabola"}
    free_symbol_names: list[str] = []
    target_symbol_names: list[str] = []
    for invocation in invocations:
        for path in invocation.inputs.values():
            try:
                value = index.context.read_path(
                    path,
                    from_scope_id=step.scope_id,
                )
            except (KeyError, PermissionError, TypeError, ValueError):
                continue
            if value.type == "Symbol":
                target_symbol_names.append(str(value.value))
            elif value.type in symbolic_types:
                free_symbol_names.extend(runtime_free_symbol_names(value.value))
    analysis = analyze_student_symbolic_complexity(
        free_symbol_names,
        target_symbol_ref=(
            target_symbol_names[0] if len(set(target_symbol_names)) == 1 else None
        ),
    )
    if analysis.student_ready:
        return plan
    raise StrategyDraftValidationError(
        "function.student_symbolic_complexity_exceeded: "
        f"step={step.step_id}, target={analysis.target_symbol_ref}, "
        f"symbols={'|'.join(analysis.residual_symbol_refs)}, "
        "maximum_student_degrees_of_freedom=1"
    )


MethodPlanTransformer = Callable[
    [
        StepPlan,
        FunctionalCompileStepView,
        CanonicalRuntimeBindingIndex,
        PlanTransformerScope,
    ],
    StepPlan,
]


def _substitute_point_parameters_transformer(
    plan: StepPlan,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    _transformer_scope: PlanTransformerScope,
) -> StepPlan:
    return _expand_point_parameter_substitutions(plan, step, index)

_METHOD_PLAN_TRANSFORMERS: dict[str, MethodPlanTransformer] = {
    "substitute_all_point_parameters": _substitute_point_parameters_transformer,
    "substitute_read_point_parameters": _substitute_point_parameters_transformer,
    "validate_student_single_degree_of_freedom": (
        _validate_student_single_degree_of_freedom
    ),
}


def _apply_method_plan_transformer(
    transformer_id: str,
    *,
    transformer_scope: PlanTransformerScope,
    plan: StepPlan,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> StepPlan:
    transformer = _METHOD_PLAN_TRANSFORMERS.get(transformer_id)
    if transformer is None:
        raise StrategyDraftValidationError(
            f"method.plan_transformer_missing: {transformer_id}"
        )
    return transformer(plan, step, index, transformer_scope)


def _runtime_symbol_for_binding(
    path: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> Any | None:
    try:
        return index.context.read_path(
            path,
            from_scope_id=step.scope_id,
            expected_type="Symbol",
        ).value
    except (KeyError, PermissionError, TypeError, ValueError):
        return None


def _source_handle_for_path(
    path: str | None,
    index: CanonicalRuntimeBindingIndex,
    prior: tuple[StateWriteProvenance, ...],
) -> str | None:
    if path is None:
        return None
    handles = [
        handle
        for handle, binding in index.bindings.items()
        if binding.path == path
    ]
    prior_handles = {item.produced_handle for item in prior}
    for handle in reversed(handles):
        if handle in prior_handles:
            return handle
    for handle in reversed(handles):
        if handle.startswith("fact:"):
            return handle
    return handles[-1] if handles else None


def _point_handle_for_path(
    path: str | None,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    if path is None:
        return None
    handles = [
        handle
        for handle, binding in index.bindings.items()
        if binding.path == path and handle.startswith("point:")
    ]
    return handles[-1] if len(handles) == 1 else None


def _object_handle_for_path(
    path: str | None,
    runtime_type: str,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    if path is None:
        return None
    handles = [
        handle
        for handle, binding in index.bindings.items()
        if binding.path == path
        and object_ref_matches_runtime_type(handle, runtime_type)
    ]
    return handles[-1] if len(handles) == 1 else None


def _preserved_object_ref(
    *,
    runtime_type: str,
    input_path: str | None,
    source_handle: str | None,
    source: StateWriteProvenance | None,
    produced_handle: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """Resolve preserved identity without crossing math-object kinds."""
    if source is not None and object_ref_matches_runtime_type(
        source.object_ref,
        runtime_type,
    ):
        return source.object_ref
    path_object = _object_handle_for_path(input_path, runtime_type, index)
    if path_object is not None:
        return path_object
    if object_ref_matches_runtime_type(source_handle, runtime_type):
        return source_handle
    if object_kind_for_runtime_type(runtime_type) == "point":
        return (
            _point_entity_for_state(source_handle, step, index)
            or _point_entity_for_state(produced_handle, step, index)
        )
    return None


def _point_entity_for_state(
    state_handle: str | None,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    candidates = [
        handle
        for handle in _compile_input_handles(step)
        if handle.startswith("point:")
    ]
    if state_handle:
        name = _provenance_semantic_name(state_handle).lower()
        matching = [
            handle
            for handle in candidates
            if _provenance_semantic_name(handle).lower() in name.split("_")
        ]
        if len(matching) == 1:
            return matching[0]
        state_name = name.split("_", 1)[0]
        registry_matches = [
            handle
            for handle in index.handle_registry.entity_handles
            if handle.startswith("point:")
            and _provenance_semantic_name(handle).lower() == state_name
            and _handle_scope(handle) in index.handle_registry.ancestor_scopes(step.scope_id)
        ]
        if len(registry_matches) == 1:
            return registry_matches[0]
    return candidates[0] if len(candidates) == 1 else None


def _provenance_semantic_name(handle: str) -> str:
    if handle.startswith("answer:"):
        return handle.split(":", 1)[1].rsplit(".", 1)[-1]
    return _semantic_name(handle)

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
    if (
        output_type == "ParameterValue"
        or _is_parameter_output_semantic_name(semantic_name)
        or fact_type == "parameter_value"
    ):
        return _first_candidate(candidates, "parameter_value")
    if output_type == "Symbol":
        return _first_candidate(candidates, semantic_name, "parameter", "symbol")
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
    step: FunctionalCompileStepView,
    *,
    point_transition: bool = False,
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
    if (
        output_type == "Point"
        and point_transition
        and produced.handle.startswith("fact:")
    ):
        # A transition advances a Point's coordinate state without mutating
        # the ProblemIR object declaration. Explicit coordinates are locked
        # input evidence, so the new value lives in a writable state path and
        # remains tied to the same object through StateWriteProvenance.
        return _scoped_output_path(
            index.context,
            produced.valid_scope,
            _semantic_name(produced.handle),
        )
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
        if point_transition:
            return index.path_for(
                point_handle,
                expected_type="PointRef|Point",
            )
        return index.point_ref_path_for(point_handle)
    if output_type == "PointList":
        return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
    if output_type == "Line":
        return _scoped_output_path(index.context, produced.valid_scope, semantic_name)
    if output_type == "ParameterValue":
        projected_write = _projected_state_write(
            step.step_id,
            produced.handle,
            index.projected_state_writes,
        )
        if (
            projected_write is not None
            and projected_write.logical_state_key is not None
        ):
            object_id = projected_write.logical_state_key.object_id
            if object_id.kind != "symbol":
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.contract_runtime_destination_drift: "
                    "ParameterValue state is not owned by a Symbol "
                    f"step={step.step_id}, handle={produced.handle}, "
                    f"object={object_id.value}"
                )
            symbol = _handle_name(object_id.value)
        else:
            # Untyped compatibility callers have no state sidecar.
            symbol = semantic_name.split("_", 1)[0]
        return _scoped_output_path(index.context, produced.valid_scope, symbol)
    if output_type == "PathTransformation":
        return _scoped_output_path(
            index.context,
            produced.valid_scope,
            (
                semantic_name
                if _has_functional_projected_write(
                    produced,
                    step=step,
                    index=index,
                )
                else "path_transformation"
            ),
        )
    if output_type == "StraighteningCandidate":
        return _scoped_output_path(
            index.context,
            produced.valid_scope,
            (
                semantic_name
                if _has_functional_projected_write(
                    produced,
                    step=step,
                    index=index,
                )
                else "straightening_candidate"
            ),
        )
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


def _has_functional_projected_write(
    produced: ProducedFact,
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    return any(
        item.step_id == step.step_id
        and item.produced_handle == produced.handle
        for item in index.projected_state_writes
    )


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
    step: FunctionalCompileStepView,
) -> str | None:
    """为 Point 产物寻找对应 canonical point handle。

    优先接受 _compile_target_handle(step) 中完整的 ``point:<scope>:<name>``；其次对
    ``quadratic_y_axis_intercept_point`` 这类定义点 method，按 Entity
    ``definition`` 找唯一目标点；最后才按 ``<Point>_coordinate`` 的语义名解析。
    """
    target_handle = _point_handle_from_text(_compile_target_handle(step), index)
    if target_handle is not None:
        return target_handle
    if _compile_capability_id(step) == "quadratic_y_axis_intercept_point":
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
    step: FunctionalCompileStepView,
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

def _step_parent_scope(step: FunctionalCompileStepView, promote: dict[str, str]) -> str:
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
