"""StepIntent 到 PlannerOutput 的编译和 recipe trial 执行。

这里把 canonical handle 与 family recipe/method binding rule 转成 MethodInvocation，
并通过 prefix dry-run 选择可执行候选。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Mapping

from shuxueshuo_server.solver.family.models import (
    MethodBindingRuleSpec,
    RecipeExecutionSpec as FamilyRecipeExecutionSpec,
    SolverFamilySpec,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder, RuntimeContext
from shuxueshuo_server.solver.runtime._planner_helpers import single_invocation_step
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
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
    _require_scoped_handle,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ExecutablePlanResolutionReport,
    ProducedFact,
    StepIntent,
    StepIntentDraft,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    StepIntentCandidateResolver,
    _produced_output_type,
    _unique_ordered,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer

@dataclass(frozen=True)
class RuntimeHandleBinding:
    """canonical handle 到 RuntimeContext path 的绑定记录。"""

    handle: str
    path: str
    value_type: str
    source: str


@dataclass(frozen=True)
class _CompiledStep:
    """RecipeTrialExecutor 编译单个 StepIntent 的临时结果。"""

    plan: StepPlan
    declarations: tuple[Any, ...] = ()
    registrations: tuple[RuntimeHandleBinding, ...] = ()


class CanonicalRuntimeBindingIndex:
    """把 LLM canonical handle 映射到 runtime ContextPath。

    这层是泛化 RecipeTrialExecutor 的关键：binding rule 只读取 Entity/Fact/answer
    handle，不再记住某一道题的固定点名。若 LLM 创建辅助点或 method 产生新 fact，
    index 会把它们注册为后续 step 可读取的语义 alias。
    """

    def __init__(
        self,
        context: RuntimeContext,
        handle_registry: CanonicalHandleRegistry,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
    ) -> None:
        self.context = context
        self.handle_registry = handle_registry
        self.bindings: dict[str, RuntimeHandleBinding] = {}
        self.fact_types = dict(handle_registry.fact_types)
        self.answer_value_types = dict(handle_registry.answer_value_types)
        self.question_goals = {f"answer:{goal.id}": goal for goal in question_goals}
        self.declarations: dict[str, Any] = {}
        self._register_initial_handles()

    @classmethod
    def from_context(
        cls,
        context: RuntimeContext,
        *,
        handle_registry: CanonicalHandleRegistry,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
    ) -> "CanonicalRuntimeBindingIndex":
        """构建 handle index。"""
        return cls(context, handle_registry, question_goals)

    def register(self, handle: str, path: str, value_type: str, *, source: str) -> None:
        """注册或覆盖一个 handle -> ContextPath 绑定。"""
        self.bindings[handle] = RuntimeHandleBinding(handle, path, value_type, source)

    def path_for(self, handle: str, *, expected_type: str | None = None) -> str:
        """读取 handle 对应 ContextPath，并可选校验类型。"""
        try:
            binding = self.bindings[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"binding_not_found: {handle}") from exc
        if expected_type is not None and binding.value_type != expected_type:
            if not (expected_type == "Point" and binding.value_type == "PointRef"):
                if expected_type == "PointRef" and binding.value_type == "Point":
                    raise StrategyDraftValidationError(
                        "duplicate_point_coordinate_fact: "
                        f"handle={handle} is already a computed Point at {binding.path}; "
                        "do not call a construction/midpoint method with this point as an unresolved target. "
                        "Read the existing coordinate fact instead, or produce the broader reusable fact before "
                        "subquestion-specific substitutions."
                    )
                raise StrategyDraftValidationError(
                    f"binding_type_mismatch: {handle} expected {expected_type}, got {binding.value_type}"
                )
        return binding.path

    def binding_for(self, handle: str) -> RuntimeHandleBinding:
        """返回绑定对象。"""
        try:
            return self.bindings[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"binding_not_found: {handle}") from exc

    def register_created_entity(self, item: CreatedEntity) -> RuntimeHandleBinding:
        """把 LLM creates[] 声明成 runtime PointRef。"""
        if item.entity_type != "point":
            raise StrategyDraftValidationError(
                f"recipe_trial_unsupported_created_entity: {item.handle}"
            )
        kind, scope_id, name = _require_scoped_handle(item.handle)
        if kind != "point":
            raise StrategyDraftValidationError(
                f"created_entity_handle_type_mismatch: {item.handle}"
            )
        path = _runtime_path_for_scope(self.context, scope_id, "points", name)
        declaration = _point_declaration_for_path(
            self.context,
            path,
            definition="straightening_auxiliary_point",
        )
        self.declarations[item.handle] = declaration
        binding = RuntimeHandleBinding(item.handle, path, "PointRef", "created_entity")
        self.bindings[item.handle] = binding
        return binding

    def ensure_point_declaration(self, handle: str, *, definition: str) -> Any | None:
        """确保某个 point handle 有 PointRef declaration。

        已存在于 RuntimeContext 的点不需要 declaration；尚未存在但后续 method 需要
        写入的目标点会在这里声明。
        """
        binding = self.binding_for(handle)
        if binding.value_type == "Point" and _context_path_exists(self.context, binding.path):
            return None
        kind, scope_id, name = _require_scoped_handle(handle)
        if kind != "point":
            raise StrategyDraftValidationError(f"declaration_requires_point_handle: {handle}")
        declaration = _point_declaration_for_path(
            self.context,
            binding.path,
            definition=definition,
        )
        self.declarations[handle] = declaration
        self.bindings[handle] = RuntimeHandleBinding(handle, declaration.path, "PointRef", "declaration")
        return declaration

    def register_produced(
        self,
        produced: ProducedFact,
        *,
        output_path: str,
        output_type: str,
        source: str,
    ) -> None:
        """把 method 输出路径注册成 produced fact/answer 的后续可读 alias。"""
        self.register(produced.handle, output_path, output_type, source=source)

    def handles_by_fact_type(self, fact_type: str) -> list[str]:
        """按 fact type 返回 handle，保持字符串排序稳定。"""
        return sorted(
            handle for handle, current_type in self.fact_types.items()
            if current_type == fact_type
        )

    def entity_handles(self, kind: str, *, step: StepIntent | None = None) -> list[str]:
        """按实体类型返回 handle；若提供 step，优先保留 step.reads 中出现的实体。"""
        handles = [
            handle for handle in self.bindings
            if handle.startswith(f"{kind}:")
        ]
        if step is None:
            return sorted(handles)
        read_set = set(step.reads)
        return [
            handle for handle in step.reads if handle in handles
        ] + sorted(handle for handle in handles if handle not in read_set)

    def point_handle_by_name(self, name: str, *, step: StepIntent | None = None) -> str:
        """按点名查找 point handle，优先当前 step reads。"""
        candidates = [
            handle for handle in self.entity_handles("point", step=step)
            if _handle_name(handle) == name
        ]
        if not candidates:
            raise StrategyDraftValidationError(f"point_handle_not_found: {name}")
        return candidates[0]

    def fact_handle_by_type(
        self,
        fact_type: str,
        *,
        step: StepIntent | None = None,
        predicate: Any | None = None,
    ) -> str:
        """按 fact type 查找 handle，优先 step.reads。"""
        handles = self.handles_by_fact_type(fact_type)
        if predicate is not None:
            handles = [handle for handle in handles if predicate(handle)]
        if step is not None:
            for handle in step.reads:
                if handle in handles:
                    return handle
        if len(handles) == 1:
            return handles[0]
        if handles:
            return handles[0]
        raise StrategyDraftValidationError(f"fact_handle_not_found: {fact_type}")

    def parameter_symbol_path(self) -> str:
        """返回当前 step family 要求解的主参数符号路径。

        主参数不是“除去 x/a/b/c 后剩下的字母”。例如河西第（Ⅲ）问要求解
        的是系数 ``b``，而动点参数是 ``n``。这里优先读 QuestionGoal 和
        ProblemIR 的 ``symbol_roles``，只有旧数据缺少角色声明时才使用 runtime
        中的系数列表作保守兜底。
        """
        symbol_handle, _constraint_handle = self._primary_parameter_handles()
        return self.path_for(symbol_handle, expected_type="Symbol")

    def parameter_constraint_path(self) -> str:
        """返回当前主参数的范围约束路径。"""
        _symbol_handle, constraint_handle = self._primary_parameter_handles()
        return self.path_for(constraint_handle, expected_type="Constraint")

    def _primary_parameter_handles(self) -> tuple[str, str]:
        """返回 ``(symbol_handle, constraint_handle)`` 主参数候选。"""
        candidates = self._symbol_constraint_candidates()
        if not candidates:
            raise StrategyDraftValidationError("dynamic_parameter_symbol_not_found")

        # 若题面最终答案就是某个参数值，优先把这个符号作为主参数。河西第（Ⅲ）
        # 问的 ``answer_key=b`` 就属于这种情况，不能因为 b 是二次函数系数而排除。
        answer_parameter_names = {
            goal.answer_key
            for goal in self.question_goals.values()
            if goal.value_type == "ParameterValue"
        }
        for candidate in candidates:
            symbol = _handle_name(candidate[0])
            if symbol in answer_parameter_names:
                return candidate

        for candidate in candidates:
            symbol = _handle_name(candidate[0])
            if self._symbol_has_role(symbol, "primary_parameter"):
                return candidate

        for candidate in candidates:
            symbol = _handle_name(candidate[0])
            if self._symbol_has_role(symbol, "dynamic_parameter"):
                return candidate

        structural_symbols = self._structural_symbol_names()
        non_structural = [
            candidate for candidate in candidates
            if _handle_name(candidate[0]) not in structural_symbols
        ]
        if len(non_structural) == 1:
            return non_structural[0]
        if len(candidates) == 1:
            return candidates[0]
        raise StrategyDraftValidationError("dynamic_parameter_symbol_not_found")

    def _symbol_constraint_candidates(self) -> list[tuple[str, str]]:
        """返回所有带范围约束且存在 runtime symbol 的符号候选。"""
        candidates: list[tuple[str, str]] = []
        for handle in self.handles_by_fact_type("symbol_constraint"):
            symbol = _symbol_from_constraint_handle(handle)
            symbol_handle = f"symbol:problem:{symbol}"
            if symbol_handle in self.bindings:
                candidates.append((symbol_handle, handle))
        return candidates

    def _symbol_has_role(self, symbol: str, role: str) -> bool:
        """判断 ProblemIR 是否给某个符号声明了指定角色。"""
        return self.context.problem.symbol_roles.get(symbol) == role

    def _structural_symbol_names(self) -> set[str]:
        """返回函数变量、二次函数系数等结构性符号名。

        这些符号通常不是“本问要求解的主参数”。首选 ProblemIR.symbol_roles；
        若旧 fixture 没有角色声明，则读取 ContextBuilder 已生成的
        ``quadratic_coefficients`` 列表，避免在 compiler 中写死 a/b/c。
        """
        names = {
            name
            for name, role in self.context.problem.symbol_roles.items()
            if role in {"function_variable", "quadratic_coefficient"}
        }
        if names:
            return names
        coefficients = self.context.problem_scope.container("symbol_lists").get(
            "quadratic_coefficients"
        )
        if coefficients is None:
            return set()
        return {str(symbol) for symbol in coefficients.value}

    def dynamic_parameter_symbol_path(self, *, step: StepIntent | None = None) -> str:
        """返回动点参数符号路径。

        ``parameter_symbol_path`` 表示当前要求解的主参数，例如河西第（Ⅲ）问的
        ``b``。weighted path method 还需要动点自身的参数，例如 ``N(n,0)`` 中
        的 ``n``。这里从 ``symbol_constraint`` fact 中排除主参数，再按当前
        StepIntent.reads 消歧，避免把动点参数名写死为 ``n``。
        """
        symbol_handle, _constraint_handle = self._dynamic_parameter_handles(step=step)
        return self.path_for(symbol_handle, expected_type="Symbol")

    def dynamic_constraint_path(self, *, step: StepIntent | None = None) -> str:
        """返回动点参数范围约束路径。"""
        _symbol_handle, constraint_handle = self._dynamic_parameter_handles(step=step)
        return self.path_for(constraint_handle, expected_type="Constraint")

    def _dynamic_parameter_handles(
        self,
        *,
        step: StepIntent | None = None,
    ) -> tuple[str, str]:
        """返回 ``(symbol_handle, constraint_handle)`` 动点参数候选。"""
        primary_symbol = ContextPath.parse(self.parameter_symbol_path()).key
        candidates: list[tuple[str, str]] = []
        for symbol_handle, constraint_handle in self._symbol_constraint_candidates():
            symbol = _handle_name(symbol_handle)
            if symbol == primary_symbol:
                continue
            candidates.append((symbol_handle, constraint_handle))
        if step is not None:
            for read_handle in step.reads:
                for candidate in candidates:
                    if read_handle in candidate:
                        return candidate
        role_candidates = [
            candidate for candidate in candidates
            if self._symbol_has_role(_handle_name(candidate[0]), "dynamic_parameter")
            or self._symbol_has_role(_handle_name(candidate[0]), "moving_point_parameter")
        ]
        if len(role_candidates) == 1:
            return role_candidates[0]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise StrategyDraftValidationError("dynamic_parameter_symbol_not_found")
        raise StrategyDraftValidationError(
            "dynamic_parameter_symbol_ambiguous: "
            + ",".join(symbol for symbol, _constraint in candidates)
        )

    def _register_initial_handles(self) -> None:
        """注册题设已有 Entity/Fact/answer。"""
        for handle in sorted(self.handle_registry.entity_handles):
            self._register_entity_handle(handle)
        for handle in sorted(self.handle_registry.fact_handles):
            self._register_fact_handle(handle)
        for handle, goal in self.question_goals.items():
            self.register(handle, goal.target_path, goal.value_type, source="question_goal")
            if goal.value_type == "Point":
                self._register_answer_point_entity(handle, goal)

    def _register_entity_handle(self, handle: str) -> None:
        kind, scope_id, name = _require_scoped_handle(handle)
        if kind == "point":
            path = self.context.find_visible_path("points", name, from_scope_id=scope_id)
            if path is None:
                path = _runtime_path_for_scope(self.context, scope_id, "points", name)
                value_type = "PointRef"
            else:
                parsed = ContextPath.parse(path)
                value_type = self.context.get_scope(parsed.scope_id).container(parsed.container)[parsed.key].type
            self.register(handle, path, value_type, source="entity")
        elif kind == "symbol":
            path = self.context.find_visible_path("symbols", name, from_scope_id=scope_id)
            if path is not None:
                self.register(handle, path, "Symbol", source="entity")
        elif kind == "function" and name == "parabola":
            self.register(handle, "$problem.expressions.quadratic", "Expression", source="entity")

    def _register_fact_handle(self, handle: str) -> None:
        fact_type = self.fact_types.get(handle)
        scope_id = _handle_scope(handle)
        name = _semantic_name(handle)
        if fact_type == "coefficient_relation":
            self.register(handle, "$problem.equations.coefficient_relation", "Equation", source="fact")
        elif fact_type == "symbol_constraint":
            symbol = name.split("_", 1)[0]
            self.register(handle, f"$problem.constraints.{symbol}", "Constraint", source="fact")
        elif fact_type == "path_minimum_target":
            self.register(handle, "$problem.conditions.path_minimum", "Condition", source="fact")
        elif fact_type == "segment_membership":
            point = _segment_membership_point(name)
            self.register(handle, f"$problem.conditions.segment_membership_{point}", "Condition", source="fact")
        elif fact_type == "segment_relation":
            left, right = _segment_relation_names(name)
            self.register(handle, f"$problem.conditions.segment_relation_{left}_{right}", "Condition", source="fact")
        elif fact_type == "orientation_constraint":
            point = name.split("_", 1)[0]
            point_handle = self.point_handle_by_name(point)
            point_scope = _handle_scope(point_handle)
            self.register(handle, _runtime_path_for_scope(self.context, point_scope, "constraints", f"{point}_quadrant"), "OrientationHint", source="fact")
        elif fact_type == "length_squared":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "length_squared"), "Condition", source="fact")
        elif fact_type == "minimum_value":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "minimum_value"), "Condition", source="fact")
        elif fact_type == "point_coordinate":
            point_name = name.split("_", 1)[0]
            point_handle = self.point_handle_by_name(point_name)
            point_binding = self.binding_for(point_handle)
            self.register(handle, point_binding.path, "Point", source="fact")
            self.register(point_handle, point_binding.path, "Point", source="fact")
        elif fact_type == "symbol_value":
            # 题设直接给出的 a=2、c=-5 会在 RuntimeContext 中合并存为
            # coefficients.known。具体单个系数值由 method 从该结构化容器读取。
            self.register(
                handle,
                _runtime_path_for_scope(self.context, scope_id, "coefficients", "known"),
                "Coefficients",
                source="fact",
            )

    def _register_answer_point_entity(self, answer_handle: str, goal: QuestionGoal) -> None:
        """若 answer 指向某个点，同时把同名 point entity 绑定到该 target path。"""
        parsed = ContextPath.parse(goal.target_path)
        if parsed.container != "points":
            return
        point_handle = f"point:{parsed.scope_id}:{parsed.key}"
        if point_handle in self.handle_registry.entity_handles:
            self.register(point_handle, goal.target_path, "PointRef", source="question_goal")


BindingSelectorFn = Callable[
    [StepIntent, CanonicalRuntimeBindingIndex, Mapping[str, str]],
    str | None,
]
ExpansionSelectorFn = Callable[
    [StepIntent, CanonicalRuntimeBindingIndex, Mapping[str, str]],
    dict[str, str],
]


class MethodBindingRuleRegistry:
    """把 StepIntent semantic handles 绑定到 method input slots。

    这里不再按 method_id 写一大段专属分支。FamilySpec 提供
    ``MethodBindingRuleSpec``，runtime 只根据 selector 名调用通用解析器。这样新增
    或调整某个 family 的 method slot 映射时，优先改 family spec，而不是改编译器
    主流程。
    """

    def __init__(
        self,
        rules: tuple[MethodBindingRuleSpec, ...] = (),
        *,
        selectors: Mapping[str, BindingSelectorFn] | None = None,
        expansion_selectors: Mapping[str, ExpansionSelectorFn] | None = None,
    ) -> None:
        self.rules = {rule.method_id: rule for rule in rules}
        self.selectors = dict(selectors or DEFAULT_BINDING_SELECTORS)
        self.expansion_selectors = dict(expansion_selectors or DEFAULT_EXPANSION_SELECTORS)

    @classmethod
    def from_family_spec(cls, family_spec: SolverFamilySpec) -> "MethodBindingRuleRegistry":
        """从 FamilySpec 构建 binding rule registry。"""
        return cls(tuple(family_spec.method_binding_rules))

    def bind(
        self,
        method_id: str,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        *,
        local_outputs: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """返回 method invocation inputs。"""
        local_outputs = local_outputs or {}
        rule = self.rules.get(method_id)
        if rule is None:
            raise StrategyDraftValidationError(f"method_binding_rule_missing: {method_id}")
        inputs: dict[str, str] = {}
        for binding in rule.input_bindings:
            try:
                value = self._select(binding.selector, step, index, local_outputs=local_outputs)
            except StrategyDraftValidationError:
                if binding.required:
                    raise
                continue
            if value is not None:
                inputs[binding.input_name] = value
        for selector in rule.expansion_selectors:
            inputs.update(
                self._expand(selector, step, index, local_outputs=local_outputs)
            )
        return inputs

    def _select(
        self,
        selector: str,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        *,
        local_outputs: dict[str, str],
    ) -> str | None:
        """执行一个通用 selector。"""
        fn = self.selectors.get(selector)
        if fn is None:
            raise StrategyDraftValidationError(f"binding_selector_missing: {selector}")
        return fn(step, index, local_outputs)

    def _expand(
        self,
        selector: str,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        *,
        local_outputs: dict[str, str],
    ) -> dict[str, str]:
        """执行一个可选输入扩展 selector。"""
        fn = self.expansion_selectors.get(selector)
        if fn is None:
            raise StrategyDraftValidationError(f"binding_expansion_selector_missing: {selector}")
        return fn(step, index, local_outputs)


def _fact_selector(fact_type: str, expected_type: str) -> BindingSelectorFn:
    """创建按 fact type 读取 ContextPath 的 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        return index.path_for(
            index.fact_handle_by_type(fact_type, step=step),
            expected_type=expected_type,
        )

    return select


def _symbol_selector(name: str) -> BindingSelectorFn:
    """创建读取 problem scope symbol 的 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        return index.path_for(f"symbol:problem:{name}", expected_type="Symbol")

    return select


def _read_type_selector(value_type: str) -> BindingSelectorFn:
    """创建从当前 step reads 或可见父级中读取指定 runtime 类型的 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        local_path = local_outputs.get(f"type:{value_type}")
        if local_path is not None:
            return local_path
        return _path_for_readable_type(index, step, value_type)

    return select


def _constant_selector(value: str) -> BindingSelectorFn:
    """创建返回固定 runtime path 的 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        return value

    return select


def _function_parabola_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 problem scope 下的二次函数表达式。"""
    return index.path_for("function:problem:parabola", expected_type="Expression")


def _point_output_ref_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取当前 step 目标点的 PointRef。"""
    return index.path_for(_point_output_handle(step, index), expected_type="PointRef")


def _midpoint_selector(role: str) -> BindingSelectorFn:
    """创建中点 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        target, p1, p2 = _midpoint_roles(step, index)
        values = {
            "target": (target, "PointRef"),
            "p1": (p1, "Point"),
            "p2": (p2, "Point"),
        }
        handle, expected_type = values[role]
        return index.path_for(handle, expected_type=expected_type)

    return select


def _right_angle_selector(role: str) -> BindingSelectorFn:
    """创建直角等腰候选 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        anchor, reference, target = _right_angle_roles(step, index)
        values = {
            "anchor": (anchor, "Point"),
            "reference": (reference, "Point"),
            "target": (target, "PointRef"),
        }
        handle, expected_type = values[role]
        return index.path_for(handle, expected_type=expected_type)

    return select


def _length_segment_selector(role: str) -> BindingSelectorFn:
    """创建线段长度条件的端点 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        p1, p2 = _length_condition_points(step, index)
        values = {"p1": p1, "p2": p2}
        return index.path_for(values[role], expected_type="Point")

    return select


def _parameter_symbol_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取参数符号。"""
    return index.parameter_symbol_path()


def _parameter_constraint_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取参数约束。"""
    return index.parameter_constraint_path()


def _dynamic_constraint_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取动点参数范围约束。"""
    return index.dynamic_constraint_path(step=step)


def _dynamic_symbol_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取动点参数符号。"""
    return index.dynamic_parameter_symbol_path(step=step)


def _read_minimum_expression_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取当前 scope 可见的 MinimumExpression。"""
    return _path_for_readable_type(index, step, "MinimumExpression")


def _weighted_path_condition_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取加权路径题设条件。"""
    return index.path_for(
        index.fact_handle_by_type("minimum_value", step=step),
        expected_type="Condition",
    )


def _weighted_path_selector(role: str) -> BindingSelectorFn:
    """创建 weighted path method 的几何角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        fixed, moving, curve = _weighted_path_roles(step, index)
        values = {
            "fixed_point": fixed,
            "moving_point": moving,
            "curve_point": curve,
        }
        return index.path_for(values[role], expected_type="Point")

    return select


def _weighted_auxiliary_point_ref_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取或声明加权路径辅助点 PointRef。"""
    item = _created_point_handle(step)
    if item is None:
        item = CreatedEntity(
            handle=_fresh_auxiliary_point_handle(step, index),
            entity_type="point",
            valid_scope=step.scope_id,
            description="weighted_axis_path_triangle_transform 自动声明的加权路径辅助点",
        )
    index.register_created_entity(item)
    return index.path_for(item.handle, expected_type="PointRef")


def _weighted_auxiliary_point_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取加权路径辅助点坐标。"""
    auxiliary = _auxiliary_point_handle_from_reads(step, index)
    return index.path_for(auxiliary, expected_type="Point")


def _path_reduction_selector(role: str) -> BindingSelectorFn:
    """创建两动点路径转化 recipe 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        roles = _path_reduction_roles(step, index)
        expected_type = "Condition" if role in {
            "first_membership",
            "second_membership",
            "relation",
        } else "Point"
        return index.path_for(roles[role], expected_type=expected_type)

    return select


def _distance_selector(role: str) -> BindingSelectorFn:
    """创建距离 method 的端点 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        p1, p2 = _distance_point_handles(step, index)
        values = {"p1": p1, "p2": p2}
        return index.path_for(values[role], expected_type="Point")

    return select


def _intersection_selector(role: str) -> BindingSelectorFn:
    """创建直线交点 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        line1_p1, line1_p2, line2_p1, line2_p2, target = _line_intersection_roles(step, index)
        values = {
            "line1_p1": (line1_p1, "Point"),
            "line1_p2": (line1_p2, "Point"),
            "line2_p1": (line2_p1, "Point"),
            "line2_p2": (line2_p2, "Point"),
            "target": (target, "PointRef"),
        }
        handle, expected_type = values[role]
        return index.path_for(handle, expected_type=expected_type)

    return select


def _known_coefficients_if_read(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> dict[str, str]:
    """若 step 读取了已知系数，则补充 known_coefficients 输入。"""
    known_scope = _known_coefficients_scope(step, index)
    if known_scope is None:
        return {}
    return {
        "known_coefficients": _runtime_path_for_scope(
            index.context,
            known_scope,
            "coefficients",
            "known",
        )
    }


def _parameter_value_if_read(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> dict[str, str]:
    """若 step 读取了参数值，则补充参数与参数值输入。"""
    parameter_value = _parameter_value_handle(step, index)
    if parameter_value is None:
        return {}
    return {
        "parameter": index.parameter_symbol_path(),
        "parameter_value": index.path_for(parameter_value, expected_type="ParameterValue"),
    }


def _curve_points_if_parameterized(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> dict[str, str]:
    """参数已确定时，若存在曲线点则补充曲线点输入。"""
    if _parameter_value_handle(step, index) is None:
        return {}
    curve_points = _visible_curve_point_handles(step, index)
    if len(curve_points) < 2:
        return {}
    return {
        "p1": index.path_for(curve_points[0], expected_type="Point"),
        "p2": index.path_for(curve_points[1], expected_type="Point"),
    }


def _curve_point_if_read(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> dict[str, str]:
    """若 step 读取了曲线点 fact，则补充 curve_point/p1/p2 输入。

    河西这类题常先代入 ``A(-1,0)`` 得到含参抛物线，此时参数尚未定值，
    但曲线点约束仍应传给 ``quadratic_from_constraints``。
    """
    curve_points = _curve_point_handles_from_reads(step, index)
    if not curve_points:
        return {}
    if len(curve_points) == 1:
        return {"curve_point": index.path_for(curve_points[0], expected_type="Point")}
    return {
        "p1": index.path_for(curve_points[0], expected_type="Point"),
        "p2": index.path_for(curve_points[1], expected_type="Point"),
    }


DEFAULT_BINDING_SELECTORS: dict[str, BindingSelectorFn] = {
    "fact:coefficient_relation:Equation": _fact_selector("coefficient_relation", "Equation"),
    "fact:path_minimum_target:Condition": _fact_selector("path_minimum_target", "Condition"),
    "fact:length_squared:Condition": _fact_selector("length_squared", "Condition"),
    "fact:minimum_value:Condition": _fact_selector("minimum_value", "Condition"),
    "symbol:a": _symbol_selector("a"),
    "symbol:b": _symbol_selector("b"),
    "symbol:c": _symbol_selector("c"),
    "symbol:x": _symbol_selector("x"),
    "function:parabola": _function_parabola_selector,
    "quadratic_coefficients": _constant_selector("$problem.symbol_lists.quadratic_coefficients"),
    "point_output_ref": _point_output_ref_selector,
    "read_type:Coefficients": _read_type_selector("Coefficients"),
    "read_type:Expression": _read_type_selector("Expression"),
    "read_type:Parabola": _read_type_selector("Parabola"),
    "read_type:Point": _read_type_selector("Point"),
    "read_type:PointList": _read_type_selector("PointList"),
    "read_type:PathTransformation": _read_type_selector("PathTransformation"),
    "read_type:Line": _read_type_selector("Line"),
    "right_angle:anchor": _right_angle_selector("anchor"),
    "right_angle:reference": _right_angle_selector("reference"),
    "right_angle:target": _right_angle_selector("target"),
    "midpoint:target": _midpoint_selector("target"),
    "midpoint:p1": _midpoint_selector("p1"),
    "midpoint:p2": _midpoint_selector("p2"),
    "length_segment:p1": _length_segment_selector("p1"),
    "length_segment:p2": _length_segment_selector("p2"),
    "parameter_symbol": _parameter_symbol_selector,
    "parameter_constraint": _parameter_constraint_selector,
    "dynamic_symbol": _dynamic_symbol_selector,
    "dynamic_constraint": _dynamic_constraint_selector,
    "read_type:MinimumExpression": _read_minimum_expression_selector,
    "weighted_path:condition": _weighted_path_condition_selector,
    "weighted_path:fixed_point": _weighted_path_selector("fixed_point"),
    "weighted_path:moving_point": _weighted_path_selector("moving_point"),
    "weighted_path:curve_point": _weighted_path_selector("curve_point"),
    "weighted_path:auxiliary_point_ref": _weighted_auxiliary_point_ref_selector,
    "weighted_path:auxiliary_point": _weighted_auxiliary_point_selector,
    "path_reduction:first_membership": _path_reduction_selector("first_membership"),
    "path_reduction:second_membership": _path_reduction_selector("second_membership"),
    "path_reduction:relation": _path_reduction_selector("relation"),
    "path_reduction:first_segment_start": _path_reduction_selector("first_segment_start"),
    "path_reduction:joint_point": _path_reduction_selector("joint_point"),
    "path_reduction:second_segment_end": _path_reduction_selector("second_segment_end"),
    "distance:p1": _distance_selector("p1"),
    "distance:p2": _distance_selector("p2"),
    "intersection:line1_p1": _intersection_selector("line1_p1"),
    "intersection:line1_p2": _intersection_selector("line1_p2"),
    "intersection:line2_p1": _intersection_selector("line2_p1"),
    "intersection:line2_p2": _intersection_selector("line2_p2"),
    "intersection:target": _intersection_selector("target"),
}


DEFAULT_EXPANSION_SELECTORS: dict[str, ExpansionSelectorFn] = {
    "known_coefficients_if_read": _known_coefficients_if_read,
    "parameter_value_if_read": _parameter_value_if_read,
    "curve_point_if_read": _curve_point_if_read,
    "curve_points_if_parameterized": _curve_points_if_parameterized,
    "distance_parameter_value_if_read": _parameter_value_if_read,
    "intersection_parameter_value_if_read": _parameter_value_if_read,
}


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
    ) -> None:
        self.recipe_specs = recipe_specs
        self.binding_rules = binding_rules

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
    ) -> None:
        self.context = context
        self.index = index
        self.resolution_report = resolution_report
        self.method_specs = method_specs
        self.recipe_specs = recipe_specs
        self.binding_rules = binding_rules
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
        if recipe.execution_strategy == "right_angle_construct_select":
            return self._compile_right_angle_recipe(step)
        if recipe.execution_strategy == "curve_candidate_parameter_solve":
            return self._compile_curve_candidate_parameter_recipe(step)
        if recipe.execution_strategy == "straightening_candidates_select":
            return self._compile_straightening_recipe(step)
        if recipe.execution_strategy == "single_method" and len(recipe.method_sequence) == 1:
            return self._compile_method(step, recipe.method_sequence[0])
        raise StrategyDraftValidationError(
            f"recipe_execution_strategy_missing: {recipe.recipe_id}:{recipe.execution_strategy}"
        )

    def _compile_method(self, step: StepIntent, method_id: str) -> _CompiledStep:
        """编译单 method step。"""
        spec = self.method_specs.require(method_id)
        declaration_keys_before = set(self.index.declarations)
        prep_invocations: list[MethodInvocation] = []
        prep_promote: dict[str, str] = {}
        local_outputs: dict[str, str] = {}
        if method_id == "quadratic_vertex_point" and _path_for_readable_type_or_none(self.index, step, "Parabola") is None:
            # 顶点公式需要当前问的具体抛物线。若 LLM 直接把“代入已知系数并求顶点”
            # 合成一个细粒度 step，代码层固定补上临时 quadratic_from_constraints。
            prepared_coefficients = _temp(step.step_id, "prepared_coefficients")
            prepared_parabola = _temp(step.step_id, "prepared_parabola")
            prep_invocations.append(
                MethodInvocation(
                    invocation_id=f"{step.step_id}.prepare_quadratic_from_constraints",
                    method_id="quadratic_from_constraints",
                    scope=step.step_id,
                    inputs=self.binding_rules.bind(
                        "quadratic_from_constraints",
                        step,
                        self.index,
                    ),
                    outputs={
                        "coefficients": prepared_coefficients,
                        "parabola": prepared_parabola,
                    },
                )
            )
            prep_promote[prepared_coefficients] = _scoped_output_path(
                self.index.context,
                step.scope_id,
                "prepared_coefficients",
            )
            prep_promote[prepared_parabola] = _scoped_output_path(
                self.index.context,
                step.scope_id,
                "prepared_parabola",
            )
            local_outputs["type:Parabola"] = prepared_parabola
            local_outputs["type:Coefficients"] = prepared_coefficients
        inputs = self.binding_rules.bind(
            method_id,
            step,
            self.index,
            local_outputs=local_outputs,
        )
        outputs = _method_outputs_for_step(method_id, step, spec.outputs, self.index)
        main_promote = _promote_outputs_for_step(step, method_id, outputs, spec.outputs, self.index)
        promote = {**prep_promote, **main_promote}
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
        if prep_invocations:
            plan = StepPlan(
                step_id=plan.step_id,
                goal=plan.goal,
                scope=plan.scope,
                invocations=[*prep_invocations, *plan.invocations],
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
                self.index,
            )
        )
        if method_id == "quadratic_from_constraints" and "coefficients" in outputs:
            coefficients_target = promote.get(outputs["coefficients"])
            if coefficients_target is not None:
                # ``quadratic_from_constraints`` 总会返回 coefficients；即使 LLM 只把
                # parabola 作为 produced fact，后续 recipe 仍常需要这些系数依赖。
                # 这里注册内部 binding，不暴露给 LLM，也不新增 canonical fact。
                registrations.append(
                    RuntimeHandleBinding(
                        f"runtime:{step.step_id}:coefficients",
                        coefficients_target,
                        "Coefficients",
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

def _runtime_path_for_scope(
    context: RuntimeContext,
    scope_id: str,
    container: str,
    key: str,
) -> str:
    """按 RuntimeContext scope 类型生成 ContextPath。"""
    scope = context.get_scope(scope_id)
    if scope.scope_type == "problem":
        return f"$problem.{container}.{key}"
    if scope.scope_type == "question":
        return f"$question.{scope_id}.{container}.{key}"
    if scope.scope_type == "subquestion":
        return f"$subquestion.{scope_id}.{container}.{key}"
    if scope.scope_type == "step":
        return f"$step.{scope_id}.{container}.{key}"
    raise StrategyDraftValidationError(f"unknown_runtime_scope_type: {scope.scope_type}")


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


def _symbol_from_constraint_handle(handle: str) -> str:
    """从 ``fact:<scope>:m_gt_2`` 这类约束 handle 中读取符号名。"""
    return _semantic_name(handle).split("_", 1)[0]


def _context_path_exists(context: RuntimeContext, raw_path: str) -> bool:
    """判断某个 ContextPath 当前是否存在。"""
    try:
        path = ContextPath.parse(raw_path)
        return path.key in context.get_scope(path.scope_id).container(path.container)
    except Exception:
        return False


def _point_declaration_for_path(
    context: RuntimeContext,
    raw_path: str,
    *,
    definition: str,
) -> ContextDeclaration:
    """为任意 question/subquestion/problem scope 创建 PointRef declaration。"""
    path = ContextPath.parse(raw_path)
    if path.container != "points":
        raise StrategyDraftValidationError(f"point_declaration_requires_point_path: {raw_path}")
    return ContextDeclaration(
        path=raw_path,
        type="PointRef",
        name=path.key,
        definition={"definition": definition},
        scope_id=path.scope_id,
    )


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


def _method_outputs_for_step(
    method_id: str,
    step: StepIntent,
    spec_outputs: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """为 invocation 生成输出路径，避免声明 method 不会实际返回的可选输出。"""
    output_names: list[str] = []
    for produced in step.produces:
        output_name = _output_key_for_produced(method_id, produced, spec_outputs, step, index)
        if output_name is not None:
            output_names.append(output_name)
    # quadratic_from_constraints 的 coefficients 对后续排查有用，并且 method 总会返回。
    if method_id == "quadratic_from_constraints":
        output_names.append("coefficients")
    if method_id == "weighted_axis_path_triangle_transform":
        # 加权路径转化 method 会稳定返回辅助点坐标与辅助点轨迹。LLM 只需要表达
        # “做路径转化”这个解题动作；这些伴随输出由 compiler 根据 method spec
        # 保留下来，供后续最短路径 method 读取。
        output_names.extend(("auxiliary_point", "auxiliary_locus"))
    if not output_names:
        output_names = list(spec_outputs)
    return {name: _temp(step.step_id, name) for name in _unique_ordered(output_names)}


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
    _add_companion_promotes(step, method_id, outputs, promote, index)
    # 如果 coefficients 被声明成 invocation output 但 LLM 没显式 produces，也可以调试性写出。
    if method_id == "quadratic_from_constraints" and "coefficients" in outputs:
        target_scope = _answer_scope_from_step(step)
        target = _scoped_output_path(index.context, target_scope, "coefficients")
        promote.setdefault(outputs["coefficients"], target)
    if not promote and outputs:
        first_key, first_path = next(iter(outputs.items()))
        promote[first_path] = _scoped_output_path(index.context, step.scope_id, first_key)
    return promote


def _add_companion_promotes(
    step: StepIntent,
    method_id: str,
    outputs: dict[str, str],
    promote: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
) -> None:
    """为 method 固有伴随输出补 promote target。

    这些输出不是 LLM 的独立结论，而是同一个 method 调用天然产生的中间几何对象。
    将它们注册为 runtime alias 可以减少 prompt 负担，同时仍由 method checks 验证。
    """
    if method_id != "weighted_axis_path_triangle_transform":
        return
    auxiliary_point_source = outputs.get("auxiliary_point")
    if auxiliary_point_source is not None:
        auxiliary_handle = _weighted_auxiliary_point_handle_for_step(step, index)
        target = index.path_for(auxiliary_handle, expected_type="PointRef")
        _ensure_declaration_for_promote_target(target, "Point", index)
        promote.setdefault(auxiliary_point_source, target)
    auxiliary_locus_source = outputs.get("auxiliary_locus")
    if auxiliary_locus_source is not None:
        promote.setdefault(
            auxiliary_locus_source,
            _scoped_output_path(index.context, step.scope_id, "auxiliary_locus"),
        )


def _companion_registrations_for_step(
    step: StepIntent,
    method_id: str,
    outputs: dict[str, str],
    promote: dict[str, str],
    index: CanonicalRuntimeBindingIndex,
) -> list[RuntimeHandleBinding]:
    """注册 method 伴随输出的可读 alias。"""
    if method_id != "weighted_axis_path_triangle_transform":
        return []
    result: list[RuntimeHandleBinding] = []
    auxiliary_point_source = outputs.get("auxiliary_point")
    if auxiliary_point_source in promote:
        auxiliary_handle = _weighted_auxiliary_point_handle_for_step(step, index)
        result.append(
            RuntimeHandleBinding(
                auxiliary_handle,
                promote[auxiliary_point_source],
                "Point",
                f"step:{step.step_id}",
            )
        )
    auxiliary_locus_source = outputs.get("auxiliary_locus")
    if auxiliary_locus_source in promote:
        result.append(
            RuntimeHandleBinding(
                f"runtime:{step.step_id}:auxiliary_locus",
                promote[auxiliary_locus_source],
                "Line",
                f"step:{step.step_id}",
            )
        )
    return result


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


def _point_output_handle(step: StepIntent, index: CanonicalRuntimeBindingIndex) -> str:
    """找出当前 step 要写回的点实体 handle。"""
    for produced in step.produces:
        if produced.handle.startswith("answer:"):
            goal = index.question_goals.get(produced.handle)
            if goal is not None and goal.value_type == "Point":
                parsed = ContextPath.parse(goal.target_path)
                return f"point:{parsed.scope_id}:{parsed.key}"
        if _produced_output_type(produced, index.handle_registry) == "Point":
            name = _semantic_name(produced.handle).split("_", 1)[0]
            return index.point_handle_by_name(name, step=step)
    if step.target.startswith("point:"):
        return step.target
    if step.target.startswith("answer:"):
        goal = index.question_goals.get(step.target)
        if goal is not None and goal.value_type == "Point":
            parsed = ContextPath.parse(goal.target_path)
            return f"point:{parsed.scope_id}:{parsed.key}"
    raise StrategyDraftValidationError(f"point_output_handle_not_found: {step.step_id}")


def _known_coefficients_scope(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从 reads 中找已知系数 fact 所在 scope。"""
    scopes: list[str] = []
    for handle in step.reads:
        if index.fact_types.get(handle) == "symbol_value":
            scopes.append(_handle_scope(handle))
    unique = _unique_ordered(scopes)
    return unique[0] if unique else None


def _parameter_value_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex | None = None,
) -> str | None:
    """从 reads 中找参数值 fact。"""
    for handle in step.reads:
        if not (handle.startswith("fact:") and _semantic_name(handle).endswith("_value")):
            continue
        if index is not None and index.fact_types.get(handle) == "symbol_value":
            continue
        if _semantic_name(handle).split("_", 1)[0] in {"a", "b", "c"}:
            continue
        if index is not None and handle not in index.bindings:
            continue
        return handle
    return None


def _path_for_first_type(
    index: CanonicalRuntimeBindingIndex,
    step: StepIntent,
    value_type: str,
) -> str:
    """从当前 step reads 中找第一个指定类型绑定。"""
    for handle in step.reads:
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == value_type:
            return binding.path
    for binding in index.bindings.values():
        if binding.value_type == value_type:
            return binding.path
    raise StrategyDraftValidationError(
        f"binding_type_not_found: step={step.step_id}, type={value_type}"
    )


def _path_for_readable_type(
    index: CanonicalRuntimeBindingIndex,
    step: StepIntent,
    value_type: str,
) -> str:
    """从 step reads 或当前 scope 可见父级中寻找指定类型。

    这个 selector 用在需要严格遵守 question/subquestion 可见性的输入上，例如
    ``parameter_from_minimum_value.minimum_expression``。它不能像普通兜底一样扫描
    全局 bindings，否则会误读 sibling 小问的输出。
    """
    for handle in step.reads:
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == value_type:
            return binding.path
    visible_bindings = [
        binding
        for _handle, binding in sorted(index.bindings.items())
        if binding.value_type == value_type
        and index.context.is_visible(step.scope_id, _binding_scope(binding.path))
    ]
    if value_type == "Coefficients":
        # ``fact:*:a_value`` 这类题设已知系数也会注册为 Coefficients。后续 recipe
        # 需要的是前序 ``quadratic_from_constraints`` 产生的系数依赖时，应优先读
        # step 输出；只有没有推导结果时才退回题设 known coefficients。
        visible_bindings.sort(key=lambda binding: (binding.source == "fact", binding.path))
    if visible_bindings:
        return visible_bindings[0].path
    if value_type == "MinimumExpression":
        raise StrategyDraftValidationError(
            "missing_required_runtime_fact: minimum_expression; "
            "parameter_from_minimum_value needs a readable common MinimumExpression fact. "
            "Do not use a sibling subquestion final answer as this expression; "
            "produce a parent-scope path_minimum_expression fact first and read it here."
        )
    raise StrategyDraftValidationError(
        f"binding_type_not_found: step={step.step_id}, type={value_type}"
    )


def _path_for_readable_type_or_none(
    index: CanonicalRuntimeBindingIndex,
    step: StepIntent,
    value_type: str,
) -> str | None:
    """尝试读取当前 step 可见类型；失败时返回 None 供 recipe 内部补前置步骤。"""
    try:
        return _path_for_readable_type(index, step, value_type)
    except StrategyDraftValidationError:
        return None


def _path_for_point_or_none(
    index: CanonicalRuntimeBindingIndex,
    handle: str,
) -> str | None:
    """尝试把 point handle 当作已知 Point 读取。"""
    binding = index.bindings.get(handle)
    if binding is None or binding.value_type != "Point":
        return None
    try:
        return index.path_for(handle, expected_type="Point")
    except StrategyDraftValidationError:
        return None


def _binding_scope(raw_path: str) -> str:
    """读取 binding path 所在 scope。"""
    return ContextPath.parse(raw_path).scope_id


def _right_angle_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str]:
    """从 ``right_angle_equal_length_ABC`` fact 推断 anchor/reference/target。

    命名约定：三个字母中间点是直角顶点/anchor，首尾两点是等长两端；其中尚未
    求出的 PointRef 或 step target 对应 target，另一点作为 reference。
    """
    fact = index.fact_handle_by_type("right_angle_equal_length", step=step)
    names = _semantic_name(fact).removeprefix("right_angle_equal_length_")
    if len(names) < 3:
        raise StrategyDraftValidationError(f"invalid_right_angle_fact_name: {fact}")
    first, anchor_name, last = names[0], names[1], names[2]
    anchor = index.point_handle_by_name(anchor_name, step=step)
    first_handle = index.point_handle_by_name(first, step=step)
    last_handle = index.point_handle_by_name(last, step=step)
    target_handle = None
    if step.target.startswith("point:"):
        target_handle = step.target
    for produced in step.produces:
        if produced.handle.startswith("answer:"):
            goal = index.question_goals.get(produced.handle)
            if goal is not None and goal.value_type == "Point":
                parsed = ContextPath.parse(goal.target_path)
                target_handle = f"point:{parsed.scope_id}:{parsed.key}"
                break
        if _produced_output_type(produced, index.handle_registry) == "Point":
            point_name = _semantic_name(produced.handle).split("_", 1)[0]
            target_handle = index.point_handle_by_name(point_name, step=step)
            break
    if target_handle is None:
        for candidate in (first_handle, last_handle):
            if index.binding_for(candidate).value_type == "PointRef":
                target_handle = candidate
                break
    if target_handle is None:
        target_handle = last_handle
    reference = first_handle if target_handle == last_handle else last_handle
    return anchor, reference, target_handle


def _curve_candidate_target_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取候选点筛选 recipe 最终要写入的点实体。

    recipe 只知道“候选点落在曲线上并反求参数”，不知道候选点来自直角等腰、
    旋转还是其它几何构造；因此 target 统一从 step 的 answer/Point produced
    或 target 字段解析。
    """
    return _point_output_handle(step, index)


def _midpoint_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str]:
    """从 ``<target>_midpoint_of_<p1><p2>`` fact 推断 target/p1/p2。"""
    fact = index.fact_handle_by_type("midpoint_definition", step=step)
    name = _semantic_name(fact)
    match = re.fullmatch(r"(?P<target>[A-Za-z0-9_]+)_midpoint_of_(?P<p1>[A-Za-z0-9_]+)(?P<p2>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_midpoint_fact_name: {fact}")
    return (
        index.point_handle_by_name(match.group("target"), step=step),
        index.point_handle_by_name(match.group("p1"), step=step),
        index.point_handle_by_name(match.group("p2"), step=step),
    )


def _length_condition_points(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """从 ``MN_length_squared_eq_10`` fact 推断线段两端点。"""
    fact = index.fact_handle_by_type("length_squared", step=step)
    name = _semantic_name(fact)
    segment = name.split("_", 1)[0]
    if len(segment) < 2:
        raise StrategyDraftValidationError(f"invalid_length_fact_name: {fact}")
    return (
        index.point_handle_by_name(segment[0], step=step),
        index.point_handle_by_name(segment[1], step=step),
    )


def _curve_point_handles_from_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """返回当前 step 显式读取的曲线点。

    这里不能全局扫描所有 ``point_on_curve`` fact，否则第（Ⅰ）问会误读第（Ⅱ）
    问的 D 或第（Ⅲ）问的 M，造成 sibling/child scope 可见性错误。
    """
    point_names: list[str] = []
    for handle in step.reads:
        if index.fact_types.get(handle) != "point_on_curve":
            continue
        point_names.append(_semantic_name(handle).split("_on_", 1)[0])
    handles: list[str] = []
    for name in point_names:
        try:
            point_handle = index.point_handle_by_name(name, step=step)
            # 只有当前已经计算成 Point 的点才适合作为曲线约束输入；PointRef
            # 不能在这里提前解析，否则会把“待由当前抛物线求坐标”的点反过来当作
            # 已知曲线点，造成循环依赖。
            if index.binding_for(point_handle).value_type != "Point":
                continue
            index.path_for(point_handle, expected_type="Point")
            handles.append(point_handle)
        except Exception:
            continue
    return _unique_ordered(handles)


def _visible_curve_point_handles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """返回当前 step scope 可见的曲线点。

    参数已经定值时，像南开 ii_1 这类子问可以复用父级 ii 中已经构造出的 M/N
    曲线点；但不能读取 sibling 或 child-only scope 的曲线点。
    """
    point_names: list[str] = []
    for handle in index.handles_by_fact_type("point_on_curve"):
        fact_scope = index.handle_registry.handle_valid_scopes.get(handle)
        if fact_scope is None or not index.context.is_visible(step.scope_id, fact_scope):
            continue
        point_names.append(_semantic_name(handle).split("_on_", 1)[0])
    handles: list[str] = []
    for name in point_names:
        try:
            point_handle = index.point_handle_by_name(name, step=step)
            index.path_for(point_handle, expected_type="Point")
            handles.append(point_handle)
        except Exception:
            continue
    return _unique_ordered(handles)


def _segment_membership_point(name: str) -> str:
    """解析 ``segment_<point>_on_<segment>`` 的动点名。"""
    match = re.fullmatch(r"segment_(?P<point>[A-Za-z0-9_]+)_on_(?P<segment>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_membership_name: {name}")
    return match.group("point")


def _segment_membership_segment(name: str) -> str:
    """解析 ``segment_<point>_on_<segment>`` 的线段名。"""
    match = re.fullmatch(r"segment_(?P<point>[A-Za-z0-9_]+)_on_(?P<segment>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_membership_name: {name}")
    return match.group("segment")


def _segment_relation_names(name: str) -> tuple[str, str]:
    """解析 ``segment_DE_eq_sqrt2_NG`` 的两个线段名。"""
    match = re.fullmatch(
        r"segment_(?P<left>[A-Za-z0-9_]+)_eq_(?:[A-Za-z0-9]+_)?(?P<right>[A-Za-z0-9_]+)",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_relation_name: {name}")
    return match.group("left"), match.group("right")


def _path_reduction_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从线段比例关系与动点所在关系推断路径降维角色。"""
    relation = index.fact_handle_by_type("segment_relation", step=step)
    left_segment, right_segment = _segment_relation_names(_semantic_name(relation))
    membership_by_point = {
        _segment_membership_point(_semantic_name(handle)): handle
        for handle in index.handles_by_fact_type("segment_membership")
    }
    if len(left_segment) < 2 or len(right_segment) < 2:
        raise StrategyDraftValidationError(f"invalid_segment_relation_segments: {relation}")
    first_moving = left_segment[1]
    second_moving = right_segment[1]
    first_segment_start = left_segment[0]
    second_segment_end = right_segment[0]
    second_membership = membership_by_point[second_moving]
    second_track = _segment_membership_segment(_semantic_name(second_membership))
    joint = next((name for name in second_track if name != second_segment_end), second_track[0])
    return {
        "relation": relation,
        "first_membership": membership_by_point[first_moving],
        "second_membership": second_membership,
        "first_segment_start": index.point_handle_by_name(first_segment_start, step=step),
        "joint_point": index.point_handle_by_name(joint, step=step),
        "second_segment_end": index.point_handle_by_name(second_segment_end, step=step),
        "second_track": second_track,
        "second_moving": second_moving,
    }


def _moving_membership_for_straightening(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """选择折线拉直时的动点所在条件。"""
    roles = _path_reduction_roles(step, index)
    return roles["second_membership"]


def _straightening_point_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str, str]:
    """推断 broken_path_straightening_candidates 的四个点。"""
    roles = _path_reduction_roles(step, index)
    fixed_1 = roles["first_segment_start"]
    midpoint_fact = index.fact_handle_by_type("midpoint_definition", step=step)
    midpoint_name = _semantic_name(midpoint_fact).split("_midpoint_of_", 1)[0]
    fixed_2 = index.point_handle_by_name(midpoint_name, step=step)
    track = roles["second_track"]
    if len(track) < 2:
        raise StrategyDraftValidationError(f"invalid_motion_track: {track}")
    line_1 = index.point_handle_by_name(track[0], step=step)
    line_2 = index.point_handle_by_name(track[1], step=step)
    return fixed_1, fixed_2, line_1, line_2


def _weighted_path_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str]:
    """从 ``sqrt(2)*MN+AN`` 这类路径条件中推断 fixed/moving/curve 点。

    返回顺序为 ``fixed_point, moving_point, curve_point``。解析只使用题面
    Condition 的 ``path`` 字段；点名可以变化，但首版路径文本仍要求是两个线段项。
    """
    condition_handle = index.fact_handle_by_type("minimum_value", step=step)
    condition_path = index.path_for(condition_handle, expected_type="Condition")
    condition = index.context.read_path(
        condition_path,
        from_scope_id=step.scope_id,
        expected_type="Condition",
    ).value
    raw_path = str(condition.get("path", ""))
    segments = _segments_from_path_text(raw_path)
    if len(segments) != 2:
        raise StrategyDraftValidationError(f"weighted_path_segments_not_found: {raw_path}")
    first, second = segments
    moving = _common_endpoint(first, second)
    if moving is None:
        raise StrategyDraftValidationError(f"weighted_path_common_endpoint_not_found: {raw_path}")
    fixed = _other_endpoint(second, moving)
    curve = _other_endpoint(first, moving)
    return (
        index.point_handle_by_name(fixed, step=step),
        index.point_handle_by_name(moving, step=step),
        index.point_handle_by_name(curve, step=step),
    )


def _auxiliary_point_handle_from_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """从 reads 中找加权路径辅助点。

    weighted path 的 fixed/moving/curve 三个点可由题设路径解析得到；剩下在 reads
    中可见的 Point 通常就是前一步三角形转化产生的辅助点。这里只做确定性排除，
    不按自然语言猜测点名。
    """
    path_roles = set(_weighted_path_roles(step, index))
    point_candidates: list[str] = []
    fact_candidates: list[str] = []
    for handle in step.reads:
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "Point":
            continue
        if handle in path_roles:
            continue
        if handle.startswith("point:"):
            point_candidates.append(handle)
        elif "aux" in _semantic_name(handle).lower():
            fact_candidates.append(handle)
    unique = _unique_ordered(point_candidates or fact_candidates)
    if len(unique) != 1:
        raise StrategyDraftValidationError(
            f"weighted_auxiliary_point_not_unique: step={step.step_id}, candidates={unique}"
        )
    return unique[0]


def _weighted_auxiliary_point_handle_for_step(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """返回加权路径转化 step 使用的辅助点 handle。"""
    item = _created_point_handle(step)
    if item is not None:
        return item.handle
    for handle, binding in sorted(index.bindings.items()):
        if (
            handle.startswith(f"point:{step.scope_id}:")
            and binding.source == "created_entity"
        ):
            return handle
    handle = _fresh_auxiliary_point_handle(step, index)
    if handle in index.bindings:
        return handle
    raise StrategyDraftValidationError(
        f"weighted_auxiliary_point_handle_not_registered: {step.step_id}"
    )


def _segments_from_path_text(raw_path: str) -> list[str]:
    """从路径文本中提取线段名。

    当前 LLM/ProblemIR 的几何对象点名仍以大写字母为主；如果后续出现 P1 或
    D_prime，多字符点名应先在 Entity/Fact 命名规范中升级后再扩展这里。
    """
    return re.findall(r"[A-Z]{2}", raw_path)


def _common_endpoint(first: str, second: str) -> str | None:
    """返回两个线段名的公共端点。"""
    for name in first:
        if name in second:
            return name
    return None


def _other_endpoint(segment: str, endpoint: str) -> str:
    """返回线段中非公共端点的另一个点名。"""
    for name in segment:
        if name != endpoint:
            return name
    raise StrategyDraftValidationError(f"segment_other_endpoint_not_found: {segment}")


def _created_point_handle(step: StepIntent) -> CreatedEntity | None:
    """返回 creates[] 中的第一个 point entity。"""
    for item in step.creates:
        if item.entity_type == "point":
            return item
    return None


def _fresh_auxiliary_point_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """为 recipe 自动创建当前 scope 下未占用的辅助点 handle。"""
    for suffix in ("", *[str(number) for number in range(1, 20)]):
        name = f"Aux{suffix}"
        handle = f"point:{step.scope_id}:{name}"
        if handle not in index.bindings and handle not in index.handle_registry.entity_handles:
            return handle
    raise StrategyDraftValidationError(
        f"auxiliary_point_handle_exhausted: {step.step_id}"
    )


def _first_pointref_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """从 reads 中找第一个 PointRef handle。"""
    for handle in step.reads:
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == "PointRef":
            return handle
    raise StrategyDraftValidationError(f"pointref_handle_not_found: {step.step_id}")


def _distance_point_handles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """为 distance_between_points 选择两端点。"""
    created_or_aux = [
        handle for handle in step.reads
        if handle.startswith("point:")
        and _is_auxiliary_point_handle(handle, index)
    ]
    if not created_or_aux:
        created_or_aux = [
            handle for handle in index.bindings
            if _is_auxiliary_point_handle(handle, index)
        ]
    midpoint_names = [
        _semantic_name(handle).split("_midpoint_of_", 1)[0]
        for handle in index.handles_by_fact_type("midpoint_definition")
    ]
    midpoint_handles = [
        index.point_handle_by_name(name, step=step)
        for name in midpoint_names
        if (
            index.bindings.get(index.point_handle_by_name(name, step=step)) is not None
            and index.bindings[index.point_handle_by_name(name, step=step)].value_type == "Point"
        )
    ]
    for p1 in created_or_aux:
        for p2 in midpoint_handles:
            if p1 != p2:
                return p1, p2
    point_reads = [
        handle for handle in step.reads
        if handle.startswith("point:") and index.bindings.get(handle) is not None
    ]
    if len(point_reads) >= 2:
        return point_reads[0], point_reads[1]
    raise StrategyDraftValidationError(
        f"distance_points_not_found: {step.step_id}; "
        "need an auxiliary/straightening point and a computed endpoint point "
        "(usually midpoint F with its coordinate fact)"
    )


def _is_auxiliary_point_handle(
    handle: str,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 point handle 是否表示折线拉直辅助点。

    LLM 可能命名为 ``Aux``、``Aux_symmetric_D``，也可能使用别的点名。比点名更可靠
    的信号是：该点不是题设初始 Entity，而是由前序 step/declaration 创建。
    """
    if not handle.startswith("point:"):
        return False
    binding = index.bindings.get(handle)
    if binding is None:
        return False
    name = _handle_name(handle).lower()
    if name.startswith("aux") or "auxiliary" in name:
        return True
    if handle not in index.handle_registry.entity_handles and (
        binding.source in {"created_entity", "declaration"}
        or binding.source.startswith("step:")
    ):
        return True
    return False


def _line_intersection_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str, str, str]:
    """推断 line_intersection_point 的两条线和目标点。"""
    roles = _path_reduction_roles(step, index)
    track = roles["second_track"]
    line1_p1 = index.point_handle_by_name(track[0], step=step)
    line1_p2 = index.point_handle_by_name(track[1], step=step)
    aux = None
    for handle in step.reads:
        if _is_auxiliary_point_handle(handle, index):
            aux = handle
            break
    if aux is None:
        for handle in index.bindings:
            if _is_auxiliary_point_handle(handle, index):
                aux = handle
                break
    midpoint_fact = index.fact_handle_by_type("midpoint_definition", step=step)
    midpoint_name = _semantic_name(midpoint_fact).split("_midpoint_of_", 1)[0]
    line2_p2 = index.point_handle_by_name(midpoint_name, step=step)
    target_handle = _point_output_handle(step, index)
    index.ensure_point_declaration(target_handle, definition="line_intersection")
    if aux is None:
        raise StrategyDraftValidationError(f"intersection_auxiliary_point_not_found: {step.step_id}")
    return line1_p1, line1_p2, aux, line2_p2, target_handle


def _answer_scope_from_step(step: StepIntent) -> str:
    """从 StepIntent 的 target/produces 中提取 answer 所属 scope。"""
    handles = [step.target, *(item.handle for item in step.produces)]
    for handle in handles:
        if handle.startswith("answer:"):
            goal_id = handle.removeprefix("answer:")
            return goal_id.split(".", 1)[0]
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
