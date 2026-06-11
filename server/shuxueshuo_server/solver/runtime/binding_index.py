"""Canonical handle 到 RuntimeContext path 的绑定索引。

本模块只维护 LLM canonical Entity/Fact/answer handle 与 runtime ContextPath
之间的映射，不负责 method selector 或 recipe 编译。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    runtime_type_matches,
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
    ProducedFact,
    StepIntentAppliedFill,
    StepIntent,
    StrategyDraftValidationError,
)

@dataclass(frozen=True)
class RuntimeHandleBinding:
    """canonical handle 到 RuntimeContext path 的绑定记录。"""

    handle: str
    path: str
    value_type: str
    source: str

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
        self.applied_fills: list[StepIntentAppliedFill] = []
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

    def record_applied_fill(
        self,
        *,
        step: StepIntent,
        input_handle: str,
        required_type: str,
        resolved_handle: str,
        reason: str,
    ) -> None:
        """记录一次 Entity/Facts 补位，供 execution diagnostic 使用。"""
        fill = StepIntentAppliedFill(
            step_id=step.step_id,
            scope_id=step.scope_id,
            input_handle=input_handle,
            required_type=required_type,
            resolved_handle=resolved_handle,
            reason=reason,
        )
        if fill not in self.applied_fills:
            self.applied_fills.append(fill)

    def path_for(self, handle: str, *, expected_type: str | None = None) -> str:
        """读取 handle 对应 ContextPath，并可选校验类型。"""
        try:
            binding = self.bindings[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"binding_not_found: {handle}") from exc
        if expected_type is not None and not runtime_type_matches(expected_type, binding.value_type):
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

    def point_ref_path_for(self, handle: str) -> str:
        """读取点实体的 PointRef path，兼容可解析 PointRef 的 Point 绑定。

        problem scope 中一些定义点（如 y 轴交点、平移点）在注册时会被标成
        ``Point``，方便普通 method 读取坐标。但当另一个 method 正在显式计算这个
        定义点时，仍需要把底层 ``PointRef`` 作为 target 传入。
        """
        binding = self.binding_for(handle)
        if binding.value_type == "PointRef":
            return binding.path
        try:
            path = ContextPath.parse(binding.path)
            value = self.context.get_scope(path.scope_id).container(path.container)[path.key]
        except Exception as exc:
            raise StrategyDraftValidationError(f"point_ref_path_not_found: {handle}") from exc
        if value.type == "PointRef":
            return binding.path
        raise StrategyDraftValidationError(
            "duplicate_point_coordinate_fact: "
            f"handle={handle} is already a computed Point at {binding.path}; "
            "do not call a construction/midpoint method with this point as an unresolved target. "
            "Read the existing coordinate fact instead."
        )

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
        if binding.value_type in {"Point", "PointRef"} and _context_path_exists(self.context, binding.path):
            return None
        kind, scope_id, name = _require_scoped_handle(handle)
        if kind != "point":
            raise StrategyDraftValidationError(f"declaration_requires_point_handle: {handle}")
        declaration = _point_declaration_for_path(
            self.context,
            binding.path,
            definition=definition,
        )
        self.declarations[declaration.path] = declaration
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

    def entity_payload(self, handle: str) -> dict[str, Any]:
        """读取 canonical Entity 的结构化 payload。"""
        try:
            return self.handle_registry.entity_payloads[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"entity_payload_not_found: {handle}") from exc

    def fact_payload(self, handle: str) -> dict[str, Any]:
        """读取 canonical Fact 的结构化 payload。"""
        try:
            return self.handle_registry.fact_payloads[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(f"fact_payload_not_found: {handle}") from exc

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
        """按点名查找 point handle，优先当前 step reads 和当前 scope。

        同一道综合题中，不同小问经常会复用同一个字母点名，例如
        ``point:i_2:G`` 与 ``point:ii:G``。binding 阶段必须按当前 step
        的可见性选择，不能因为注册顺序误读 sibling scope 的同名点。
        """
        candidates = [
            handle for handle in self.entity_handles("point")
            if _handle_name(handle) == name
        ]
        if step is not None:
            candidates = [
                handle for handle in candidates
                if self._handle_binding_visible(handle, step.scope_id)
            ]
            read_candidates = [
                handle for handle in step.reads
                if handle in candidates
            ]
            if read_candidates:
                return read_candidates[0]
            candidates = sorted(
                candidates,
                key=lambda handle: (
                    self._scope_distance(
                        step.scope_id,
                        _binding_scope(self.binding_for(handle).path),
                    ),
                    handle,
                ),
            )
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
        """按 fact type 查找 handle，优先 step.reads 和当前 scope。"""
        handles = self.handles_by_fact_type(fact_type)
        if predicate is not None:
            handles = [handle for handle in handles if predicate(handle)]
        if step is not None:
            for handle in step.reads:
                if handle in handles and self._handle_binding_visible(handle, step.scope_id):
                    return handle
            visible_handles = [
                handle for handle in handles
                if self._handle_binding_visible(handle, step.scope_id)
            ]
            if visible_handles:
                return sorted(
                    visible_handles,
                    key=lambda handle: (
                        self._scope_distance(
                            step.scope_id,
                            _binding_scope(self.binding_for(handle).path),
                        ),
                        handle,
                    ),
                )[0]
        if len(handles) == 1:
            return handles[0]
        if handles:
            return handles[0]
        raise StrategyDraftValidationError(f"fact_handle_not_found: {fact_type}")

    def _handle_binding_visible(self, handle: str, from_scope_id: str) -> bool:
        """判断 handle 对应 runtime path 是否从当前 step scope 可见。"""
        try:
            binding = self.binding_for(handle)
        except StrategyDraftValidationError:
            return False
        return self.context.is_visible(from_scope_id, _binding_scope(binding.path))

    def _scope_distance(self, from_scope_id: str, target_scope_id: str) -> int:
        """返回 target 在 from_scope 父链上的距离；不可见时排到最后。"""
        current: str | None = from_scope_id
        distance = 0
        while current is not None:
            if current == target_scope_id:
                return distance
            current = self.context.scopes[current].parent_id
            distance += 1
        return 10_000

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

    def is_structural_symbol_value_fact(self, handle: str) -> bool:
        """判断某个 ``*_value`` fact 是否只是结构符号的已知值。

        Strategy binding 中经常需要从 reads 里找“前序 step 求出的参数值”。
        题设给出的二次函数系数值（如 a=2、c=-5）也是 ``symbol_value``，
        但它们不应被当作参数求解结果。这里复用 ProblemIR.symbol_roles /
        quadratic_coefficients，而不是写死 a/b/c。
        """
        if self.fact_types.get(handle) != "symbol_value":
            return False
        name = _semantic_name(handle)
        if not name.endswith("_value"):
            return False
        symbol = name[: -len("_value")]
        if symbol.startswith("parameter_"):
            symbol = symbol[len("parameter_") :]
        return symbol in self._structural_symbol_names()

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
                if value_type == "PointRef" and parsed.scope_id == "problem":
                    try:
                        self.context.read_path(path, from_scope_id=scope_id, expected_type="Point")
                        value_type = "Point"
                    except Exception:
                        pass
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
        elif fact_type == "segment_length_relation":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "segment_length_relation"), "Condition", source="fact")
        elif fact_type == "minimum_value":
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", "minimum_value"), "Condition", source="fact")
        elif fact_type in {
            "angle_sum",
            "equal_length_ray_point",
            "point_on_segment",
            "point_on_ray",
            "equal_length_condition",
            "axis_membership",
            "point_on_curve",
            "square",
            "square_center",
            "midpoint_definition",
        }:
            self.register(handle, _runtime_path_for_scope(self.context, scope_id, "conditions", fact_type), "Condition", source="fact")
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

def _binding_scope(raw_path: str) -> str:
    """读取 runtime path 所在 scope。"""
    return ContextPath.parse(raw_path).scope_id

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

def _segment_membership_point(name: str) -> str:
    """解析 ``segment_<point>_on_<segment>`` 的动点名。"""
    match = re.fullmatch(r"segment_(?P<point>[A-Za-z0-9_]+)_on_(?P<segment>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_membership_name: {name}")
    return match.group("point")

def _segment_relation_names(name: str) -> tuple[str, str]:
    """解析 ``segment_DE_eq_sqrt2_NG`` 的两个线段名。"""
    match = re.fullmatch(
        r"segment_(?P<left>[A-Za-z0-9_]+)_eq_(?:[A-Za-z0-9]+_)?(?P<right>[A-Za-z0-9_]+)",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_relation_name: {name}")
    return match.group("left"), match.group("right")
