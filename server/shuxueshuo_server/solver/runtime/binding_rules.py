"""Method binding selector registry。

FamilySpec 通过 selector 字符串声明 method input 的语义绑定；本模块把这些
selector 解析成具体 RuntimeContext path。
"""

from __future__ import annotations

import re
from typing import Callable, Mapping

from shuxueshuo_server.solver.family.models import MethodBindingRuleSpec, SolverFamilySpec
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.handle_registry import (
    _handle_name,
    _handle_scope,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    StepIntent,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    _produced_output_type,
    _unique_ordered,
)
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    _runtime_path_for_scope,
    _segment_membership_point,
    _segment_relation_names,
)

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
        self._validate_rule_selectors()

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

    def rule_for(self, method_id: str) -> MethodBindingRuleSpec | None:
        """返回 method 的 binding rule；不存在时返回 None。"""
        return self.rules.get(method_id)

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

    def _validate_rule_selectors(self) -> None:
        """构造 registry 时提前发现 FamilySpec selector 拼写错误。"""
        for rule in self.rules.values():
            for binding in rule.input_bindings:
                if binding.selector not in self.selectors:
                    raise StrategyDraftValidationError(
                        f"binding_selector_missing: {binding.selector}"
                    )
            for selector in rule.expansion_selectors:
                if selector not in self.expansion_selectors:
                    raise StrategyDraftValidationError(
                        f"binding_expansion_selector_missing: {selector}"
                    )

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
        if index is not None and index.is_structural_symbol_value_fact(handle):
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

def _segment_membership_segment(name: str) -> str:
    """解析 ``segment_<point>_on_<segment>`` 的线段名。"""
    match = re.fullmatch(r"segment_(?P<point>[A-Za-z0-9_]+)_on_(?P<segment>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_segment_membership_name: {name}")
    return match.group("segment")

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
