"""Method binding selector registry。

FamilySpec 通过 selector 字符串声明 method input 的语义绑定；本模块把这些
selector 解析成具体 RuntimeContext path。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping

from shuxueshuo_server.solver.family.models import MethodBindingRuleSpec, SolverFamilySpec
from shuxueshuo_server.solver.runtime.auxiliary_points import fresh_auxiliary_point_handle
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
from shuxueshuo_server.solver.runtime.entity_state_resolver import EntityStateResolver

BindingSelectorFn = Callable[
    [StepIntent, CanonicalRuntimeBindingIndex, Mapping[str, str]],
    str | None,
]

ExpansionSelectorFn = Callable[
    [StepIntent, CanonicalRuntimeBindingIndex, Mapping[str, str]],
    dict[str, str],
]


@dataclass(frozen=True)
class _PointValueCandidate:
    """A readable Point value for one geometric point object."""

    point_name: str
    handle: str
    rank: int

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
        include_expansion_selectors: bool = True,
        expansion_selectors_override: tuple[str, ...] | None = None,
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
        if expansion_selectors_override is not None:
            expansion_selectors = expansion_selectors_override
        elif include_expansion_selectors:
            expansion_selectors = rule.expansion_selectors
        else:
            expansion_selectors = ()
        for selector in expansion_selectors:
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

def _optional_fact_selector(fact_type: str, expected_type: str) -> BindingSelectorFn:
    """创建可选 fact selector；找不到时返回 None。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str | None:
        try:
            return index.path_for(
                index.fact_handle_by_type(fact_type, step=step),
                expected_type=expected_type,
            )
        except StrategyDraftValidationError:
            return None

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

def _free_parameter_if_single_curve_point_selector(name: str) -> BindingSelectorFn:
    """仅当 step 只读到一个曲线点约束时，保留指定自由参数。

    这类 selector 用于“先把函数化简成单参数表达式”的场景。若同一步读到了
    两个或更多曲线点，通常已经足以完全确定系数，此时不应再强行保留自由参数。
    """

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str | None:
        if len(_curve_point_handles_from_reads(step, index)) != 1:
            return None
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


def _read_type_union_selector(*value_types: str) -> BindingSelectorFn:
    """创建可读取一组 runtime 类型的 selector，优先遵守 step.reads 顺序。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        for value_type in value_types:
            local_path = local_outputs.get(f"type:{value_type}")
            if local_path is not None:
                return local_path
        value_type_set = set(value_types)
        for handle in step.reads:
            binding = index.bindings.get(handle)
            if binding is not None and binding.value_type in value_type_set:
                return binding.path
        for value_type in value_types:
            path = _path_for_readable_type_or_none(index, step, value_type)
            if path is not None:
                return path
        joined = "|".join(value_types)
        raise StrategyDraftValidationError(
            f"binding_type_not_found: step={step.step_id}, type={joined}"
        )

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

def _square_side_start_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 square fact 的第一个顶点，作为以 AE 为边的起点 A。"""
    side_start = _square_side_start_handle(step, index)
    try:
        return _point_state_path_for_name(
            _handle_name(side_start),
            step,
            index,
            error_code="square_side_start_state_not_found",
        )
    except StrategyDraftValidationError:
        return _point_path_from_step_reads(side_start, step, index)

def _square_side_end_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 square step 的已知边第二端点。"""
    side_end = _square_side_end_handle(step, index)
    return _point_state_path_for_name(
        _handle_name(side_end),
        step,
        index,
        error_code="square_side_end_state_not_found",
    )

def _square_side_start_ref_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 square 已知边起点 PointRef。"""
    return index.point_ref_path_for(_square_side_start_handle(step, index))

def _square_side_end_ref_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 square 已知边终点 PointRef。"""
    return index.point_ref_path_for(_square_side_end_handle(step, index))

def _square_side_start_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取 square fact 的第一个顶点 handle。"""
    fact = index.fact_handle_by_type("square", step=step)
    payload = index.fact_payload(fact)
    vertices = payload.get("vertices")
    if not isinstance(vertices, list) or len(vertices) < 2:
        raise StrategyDraftValidationError(f"square_vertices_not_found: {fact}")
    return str(vertices[0])

def _square_side_end_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """根据当前 target 从 reads 中选择 square 已知边第二端点。"""
    side_start = _square_side_start_handle(step, index)
    target = _point_output_handle(step, index)
    candidates: list[str] = []
    for handle in step.reads:
        point_name = _point_state_read_name(handle, index)
        if point_name is None or point_name in {_handle_name(side_start), _handle_name(target)}:
            continue
        try:
            point_handle = index.point_handle_by_name(point_name, step=step)
        except StrategyDraftValidationError:
            continue
        try:
            _point_state_path_for_name(
                point_name,
                step,
                index,
                error_code="square_side_end_state_not_found",
            )
        except StrategyDraftValidationError:
            continue
        candidates.append(point_handle)
    unique = _unique_ordered(candidates)
    if len(unique) == 1:
        return unique[0]
    raise StrategyDraftValidationError(
        "square_side_end_not_found: "
        f"step={step.step_id}, candidates={','.join(unique)}"
    )

def _point_output_ref_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取当前 step 目标点的 PointRef。"""
    handle = _point_output_handle(step, index)
    index.ensure_point_declaration(handle, definition="method_output_point")
    return index.point_ref_path_for(handle)

def _translated_point_selector(role: str) -> BindingSelectorFn:
    """创建平移点 method 的 source/target selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        target_handle = _point_output_handle(step, index)
        target_path = index.point_ref_path_for(target_handle)
        if role == "target":
            return target_path
        try:
            target_ref = index.context.read_path(
                target_path,
                from_scope_id=step.scope_id,
                expected_type="PointRef",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            raise StrategyDraftValidationError(
                f"translated_point_target_ref_not_found: {target_handle}"
            ) from exc
        source_name = (
            target_ref.definition.get("of")
            or target_ref.definition.get("source")
            or target_ref.definition.get("base")
        )
        if not source_name:
            raise StrategyDraftValidationError(
                f"translated_point_source_not_found: {target_handle}"
            )
        source_handle = index.point_handle_by_name(str(source_name), step=step)
        return _point_path_from_step_reads(source_handle, step, index)

    return select

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

def _length_reference_segment_selector(role: str) -> BindingSelectorFn:
    """创建线段比例条件右侧参考线段的端点 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str | None:
        points = _length_reference_condition_points(step, index)
        if points is None:
            return None
        values = {"p1": points[0], "p2": points[1]}
        return index.path_for(values[role], expected_type="Point")

    return select

def _length_condition_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取长度条件，兼容长度平方与两线段比例关系。"""
    return index.path_for(_length_condition_handle(step, index), expected_type="Condition")

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

def _x_axis_known_point_selector(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str | None:
    """读取 x 轴另一交点 method 用来排除的已知交点。"""
    target_handle = _point_output_handle(step, index)
    index.ensure_point_declaration(target_handle, definition="method_output_point")
    target_path = index.point_ref_path_for(target_handle)
    try:
        target_ref = index.context.read_path(
            target_path,
            from_scope_id=step.scope_id,
            expected_type="PointRef",
        ).value
        exclude_name = target_ref.definition.get("exclude_point") or target_ref.definition.get("known_point")
        if exclude_name:
            return index.path_for(
                index.point_handle_by_name(str(exclude_name), step=step),
                expected_type="Point",
            )
    except (KeyError, PermissionError, TypeError, ValueError):
        pass
    for handle in step.reads:
        if handle.startswith("point:"):
            try:
                binding = index.binding_for(handle)
                if binding.value_type != "Point":
                    continue
                return index.path_for(handle, expected_type="Point")
            except StrategyDraftValidationError:
                continue
    return None

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
        return _point_path_from_step_reads(values[role], step, index)

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

def _angle_sum_selector(role: str) -> BindingSelectorFn:
    """创建角和转 y 轴截点 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        roles = _angle_sum_y_axis_roles(step, index)
        expected_type = "Condition" if role == "condition" else "Point"
        if role == "target":
            expected_type = "PointRef"
            index.ensure_point_declaration(roles[role], definition="method_output_point")
        if expected_type == "Point":
            return _point_path_from_step_reads(roles[role], step, index)
        return index.path_for(roles[role], expected_type=expected_type)

    return select


def _angle_equality_selector(role: str) -> BindingSelectorFn:
    """创建等角转轴截点 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        roles = _angle_equality_axis_roles(step, index)
        if role == "angle_equality":
            return index.path_for(roles[role], expected_type="AngleEquality")
        expected_type = "PointRef" if role == "target" else "Point"
        if role == "target":
            index.ensure_point_declaration(roles[role], definition="method_output_point")
            return index.point_ref_path_for(roles[role])
        return _point_path_from_step_reads(roles[role], step, index)

    return select


def _line_parabola_selector(role: str) -> BindingSelectorFn:
    """创建直线与抛物线第二交点 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        roles = _line_parabola_roles(step, index)
        expected_type = "PointRef" if role == "target" else "Point"
        if role == "target":
            index.ensure_point_declaration(roles[role], definition="method_output_point")
        if expected_type == "Point":
            return _point_path_from_step_reads(roles[role], step, index)
        return index.path_for(roles[role], expected_type=expected_type)

    return select

def _equal_length_ray_selector(role: str) -> BindingSelectorFn:
    """创建射线上等长构造点 method 的角色 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        roles = _equal_length_ray_roles(step, index)
        expected_type = "PointRef" if role == "target" else "Point"
        if role == "target":
            index.ensure_point_declaration(roles[role], definition="method_output_point")
        if expected_type == "Point":
            return _point_path_from_step_reads(roles[role], step, index)
        return index.path_for(roles[role], expected_type=expected_type)

    return select

def _straightening_minimum_point_selector(role: str) -> BindingSelectorFn:
    """读取通用将军饮马 recipe 产出的最短线段端点。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        semantic_suffixes = (
            ("point_1", "endpoint1", "endpoint_1")
            if role == "p1"
            else ("point_2", "endpoint2", "endpoint_2")
        )
        matches = _straightening_minimum_endpoint_handles(
            step,
            index,
            semantic_suffixes=semantic_suffixes,
            handles=step.reads,
        )
        if not matches:
            matches = _straightening_minimum_endpoint_handles(
                step,
                index,
                semantic_suffixes=semantic_suffixes,
                handles=tuple(index.bindings),
            )
        unique = _unique_ordered(matches)
        if len(unique) != 1:
            raise StrategyDraftValidationError(
                f"straightening_minimum_{role}_not_found: "
                f"step={step.step_id}, candidates={','.join(unique)}"
            )
        return index.path_for(unique[0], expected_type="Point")

    return select


def _straightening_minimum_endpoint_handles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    *,
    semantic_suffixes: tuple[str, ...],
    handles: tuple[str, ...],
) -> list[str]:
    """读取当前 step 可见的拉直最短线段端点 handles。"""
    matches: list[str] = []
    for handle in handles:
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "Point":
            continue
        try:
            if not index.context.is_visible(step.scope_id, _binding_scope(binding.path)):
                continue
        except Exception:
            continue
        semantic_name = _answer_key_from_handle(handle) if handle.startswith("answer:") else _semantic_name(handle)
        if any(suffix in semantic_name for suffix in semantic_suffixes):
            matches.append(handle)
    return matches


def _curve_condition_point_selector(role: str) -> BindingSelectorFn:
    """创建“目标点 P(t)、曲线点 Q(t) 且 Q 在曲线上” method 的点 selector。"""

    def select(
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        curve_point_name = _curve_condition_point_name(step, index)
        if role == "curve_point":
            return _point_state_path_for_name(
                curve_point_name,
                step,
                index,
                error_code="curve_condition_curve_point_not_found",
            )
        target_name = _curve_condition_target_point_name(step, index, curve_point_name)
        return _point_state_path_for_name(
            target_name,
            step,
            index,
            error_code="curve_condition_target_point_not_found",
        )

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
    """若 step 读取了参数值，或当前 scope 有唯一可见参数值，则补充参数输入。"""
    parameter_value = _parameter_value_handle(step, index)
    if parameter_value is None:
        parameter_value = _unique_visible_parameter_value_handle(step, index)
    if parameter_value is None:
        return {}
    return {
        "parameter": index.parameter_symbol_path(),
        "parameter_value": index.path_for(parameter_value, expected_type="ParameterValue"),
    }


def _unique_visible_parameter_value_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """读取当前 step 可见的唯一非结构 ParameterValue fact；多候选时不猜。"""
    candidates: list[str] = []
    for handle, binding in sorted(index.bindings.items()):
        if not handle.startswith("fact:"):
            continue
        if binding.value_type != "ParameterValue":
            continue
        if index.is_structural_symbol_value_fact(handle):
            continue
        try:
            if not index.context.is_visible(step.scope_id, _binding_scope(binding.path)):
                continue
        except Exception:
            continue
        candidates.append(handle)
    unique = _unique_ordered(candidates)
    if len(unique) == 1:
        return unique[0]
    return None


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
    "fact:square:Condition": _optional_fact_selector("square", "Condition"),
    "fact:midpoint_definition:Condition": _fact_selector("midpoint_definition", "Condition"),
    "fact:square_center:Condition": _fact_selector("square_center", "Condition"),
    "fact:length_squared:Condition": _fact_selector("length_squared", "Condition"),
    "fact:length_condition:Condition": _length_condition_selector,
    "fact:minimum_value:Condition": _fact_selector("minimum_value", "Condition"),
    "symbol:a": _symbol_selector("a"),
    "symbol:b": _symbol_selector("b"),
    "symbol:c": _symbol_selector("c"),
    "symbol:x": _symbol_selector("x"),
    "free_parameter:a_if_single_curve_point": _free_parameter_if_single_curve_point_selector("a"),
    "free_parameter:b_if_single_curve_point": _free_parameter_if_single_curve_point_selector("b"),
    "free_parameter:c_if_single_curve_point": _free_parameter_if_single_curve_point_selector("c"),
    "function:parabola": _function_parabola_selector,
    "square:side_start": _square_side_start_selector,
    "square:side_end": _square_side_end_selector,
    "square:side_start_ref": _square_side_start_ref_selector,
    "square:side_end_ref": _square_side_end_ref_selector,
    "quadratic_coefficients": _constant_selector("$problem.symbol_lists.quadratic_coefficients"),
    "point_output_ref": _point_output_ref_selector,
    "translated_point:source": _translated_point_selector("source"),
    "translated_point:target": _translated_point_selector("target"),
    "read_type:Coefficients": _read_type_selector("Coefficients"),
    "read_type:Expression": _read_type_selector("Expression"),
    "read_type:Expression|MinimumExpression": _read_type_union_selector(
        "Expression",
        "MinimumExpression",
    ),
    "read_type:Parabola": _read_type_selector("Parabola"),
    "read_type:Point": _read_type_selector("Point"),
    "read_type:PointList": _read_type_selector("PointList"),
    "read_type:PathTransformation": _read_type_selector("PathTransformation"),
    "read_type:Line": _read_type_selector("Line"),
    "read_type:AngleEquality": _read_type_selector("AngleEquality"),
    "read_type:ParameterValue": _read_type_selector("ParameterValue"),
    "right_angle:anchor": _right_angle_selector("anchor"),
    "right_angle:reference": _right_angle_selector("reference"),
    "right_angle:target": _right_angle_selector("target"),
    "midpoint:target": _midpoint_selector("target"),
    "midpoint:p1": _midpoint_selector("p1"),
    "midpoint:p2": _midpoint_selector("p2"),
    "length_segment:p1": _length_segment_selector("p1"),
    "length_segment:p2": _length_segment_selector("p2"),
    "length_reference_segment:p1": _length_reference_segment_selector("p1"),
    "length_reference_segment:p2": _length_reference_segment_selector("p2"),
    "parameter_symbol": _parameter_symbol_selector,
    "parameter_constraint": _parameter_constraint_selector,
    "dynamic_symbol": _dynamic_symbol_selector,
    "dynamic_constraint": _dynamic_constraint_selector,
    "x_axis_known_point": _x_axis_known_point_selector,
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
    "angle_sum:condition": _angle_sum_selector("condition"),
    "angle_sum:x_axis_point": _angle_sum_selector("x_axis_point"),
    "angle_sum:y_axis_point": _angle_sum_selector("y_axis_point"),
    "angle_sum:reference_x_axis_point": _angle_sum_selector("reference_x_axis_point"),
    "angle_sum:origin": _angle_sum_selector("origin"),
    "angle_sum:target": _angle_sum_selector("target"),
    "angle_equality:fact": _angle_equality_selector("angle_equality"),
    "angle_equality:x_axis_point": _angle_equality_selector("x_axis_point"),
    "angle_equality:y_axis_point": _angle_equality_selector("y_axis_point"),
    "angle_equality:reference_x_axis_point": _angle_equality_selector("reference_x_axis_point"),
    "angle_equality:origin": _angle_equality_selector("origin"),
    "angle_equality:target": _angle_equality_selector("target"),
    "line_parabola:line_p1": _line_parabola_selector("line_p1"),
    "line_parabola:line_p2": _line_parabola_selector("line_p2"),
    "line_parabola:known_point": _line_parabola_selector("known_point"),
    "line_parabola:target": _line_parabola_selector("target"),
    "equal_length_ray:anchor": _equal_length_ray_selector("anchor"),
    "equal_length_ray:reference_point": _equal_length_ray_selector("reference_point"),
    "equal_length_ray:ray_point": _equal_length_ray_selector("ray_point"),
    "equal_length_ray:target": _equal_length_ray_selector("target"),
    "straightening_minimum:p1": _straightening_minimum_point_selector("p1"),
    "straightening_minimum:p2": _straightening_minimum_point_selector("p2"),
    "curve_condition:target_point": _curve_condition_point_selector("target_point"),
    "curve_condition:curve_point": _curve_condition_point_selector("curve_point"),
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
    target_handle = _point_handle_from_text(step.target, index)
    if target_handle is not None:
        return target_handle
    if step.target.startswith("point:"):
        return step.target
    if step.target.startswith("answer:"):
        goal = index.question_goals.get(step.target)
        if goal is not None and goal.value_type == "Point":
            parsed = ContextPath.parse(goal.target_path)
            return f"point:{parsed.scope_id}:{parsed.key}"

    created_points = [
        item.handle for item in step.creates
        if item.entity_type == "point"
    ]
    has_point_output = any(
        (
            produced.handle.startswith("answer:")
            and (goal := index.question_goals.get(produced.handle)) is not None
            and goal.value_type == "Point"
        )
        or _produced_output_type(produced, index.handle_registry) == "Point"
        for produced in step.produces
    )
    if len(created_points) == 1 and has_point_output:
        return created_points[0]

    for produced in step.produces:
        if produced.handle.startswith("answer:"):
            goal = index.question_goals.get(produced.handle)
            if goal is not None and goal.value_type == "Point":
                parsed = ContextPath.parse(goal.target_path)
                return f"point:{parsed.scope_id}:{parsed.key}"
        if _produced_output_type(produced, index.handle_registry) == "Point":
            if step.recipe_hint == "quadratic_y_axis_intercept_point":
                target = _unique_point_handle_by_definition(
                    "y_axis_intercept",
                    step,
                    index,
                )
                if target is not None:
                    return target
            name = (
                _point_name_from_state_semantic(_semantic_name(produced.handle))
                or _semantic_name(produced.handle).split("_", 1)[0]
            )
            return index.point_handle_by_name(name, step=step)
    raise StrategyDraftValidationError(f"point_output_handle_not_found: {step.step_id}")


def _point_handle_from_text(
    text: str,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从自然语言 target 中提取完整 canonical point handle。

    只接受 ``point:<scope>:<name>`` 这种完整 handle，不根据单字母点名猜测。
    """
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


def _point_path_from_step_reads(
    handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取点坐标路径，优先使用当前 step 显式读入的同名坐标 fact。"""
    resolved = EntityStateResolver().resolve(handle, "Point", step, index)
    if resolved is not None:
        return resolved
    return index.path_for(handle, expected_type="Point")


def _point_read_is_usable_as_point(
    handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 step 中的 point handle 是否能作为 Point 输入。"""
    binding = index.bindings.get(handle)
    if binding is None:
        return False
    if binding.value_type == "Point":
        return True
    if binding.value_type != "PointRef":
        return False
    return EntityStateResolver().can_resolve(handle, "Point", step, index)


def _is_point_coordinate_fact_handle(
    handle: str,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 handle 是否表示点坐标 fact，兼容题设 fact 与运行中 produces。"""
    if index.fact_types.get(handle) == "point_coordinate":
        return True
    if not handle.startswith("fact:"):
        return False
    return bool(re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_]*_"
        r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate)"
        r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
        _semantic_name(handle),
        flags=re.IGNORECASE,
    ))


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
        if index is not None:
            binding = index.bindings.get(handle)
            if (
                handle.startswith("fact:")
                and binding is not None
                and binding.value_type == "ParameterValue"
                and not index.is_structural_symbol_value_fact(handle)
            ):
                return handle
        if not (handle.startswith("fact:") and _semantic_name(handle).endswith("_value")):
            continue
        if index is not None:
            fact_type = index.fact_types.get(handle)
            binding = index.bindings.get(handle)
            if fact_type != "symbol_value" and (
                binding is None or binding.value_type != "ParameterValue"
            ):
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
        resolved = EntityStateResolver().resolve(handle, value_type, step, index)
        if resolved is not None:
            return resolved
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
    fact = _midpoint_definition_read(step, index)
    name = _semantic_name(fact)
    match = re.fullmatch(r"(?P<target>[A-Za-z0-9_]+)_midpoint_of_(?P<p1>[A-Za-z0-9_]+)(?P<p2>[A-Za-z0-9_]+)", name)
    if match is None:
        raise StrategyDraftValidationError(f"invalid_midpoint_fact_name: {fact}")
    return (
        index.point_handle_by_name(match.group("target"), step=step),
        index.point_handle_by_name(match.group("p1"), step=step),
        index.point_handle_by_name(match.group("p2"), step=step),
    )


def _midpoint_definition_read(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """midpoint_point 必须绑定当前 step 明确读取的中点定义。"""
    midpoint_reads = [
        handle
        for handle in step.reads
        if index.fact_types.get(handle) == "midpoint_definition"
        and index._handle_binding_visible(handle, step.scope_id)
    ]
    if midpoint_reads:
        return midpoint_reads[0]
    raise StrategyDraftValidationError(
        "midpoint_definition_not_read: "
        f"step={step.step_id}, method=midpoint_point requires a "
        "midpoint_definition read such as fact:<scope>:<target>_midpoint_of_<p1><p2>"
    )


def _length_condition_points(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """从长度条件 fact 推断左侧线段两端点。"""
    fact = _length_condition_handle(step, index)
    if index.fact_types.get(fact) == "segment_length_relation":
        segment = _segment_name_from_length_relation(fact, side="left")
        return _segment_point_handles(segment, step, index, fact)
    name = _semantic_name(fact)
    segment = name.split("_", 1)[0]
    return _segment_point_handles(segment, step, index, fact)

def _length_reference_condition_points(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str] | None:
    """从线段比例 fact 推断右侧参考线段两端点。"""
    fact = _length_condition_handle(step, index)
    if index.fact_types.get(fact) != "segment_length_relation":
        return None
    segment = _segment_name_from_length_relation(fact, side="right")
    return _segment_point_handles(segment, step, index, fact)

def _length_condition_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """返回当前 step 读取的长度条件 handle。"""
    for handle in step.reads:
        if index.fact_types.get(handle) in {"length_squared", "segment_length_relation"}:
            return handle
    for fact_type in ("length_squared", "segment_length_relation"):
        try:
            return index.fact_handle_by_type(fact_type, step=step)
        except StrategyDraftValidationError:
            continue
    raise StrategyDraftValidationError("fact_handle_not_found: length_condition")

def _segment_name_from_length_relation(fact: str, *, side: str) -> str:
    """从 ``AD_eq_2BC`` 或 ``AD_eq_2_BC`` 中解析左/右线段。"""
    name = _semantic_name(fact)
    if "_eq_" not in name:
        raise StrategyDraftValidationError(f"invalid_length_relation_name: {fact}")
    left_raw, right_raw = name.split("_eq_", 1)
    raw = left_raw if side == "left" else right_raw
    letters = "".join(re.findall(r"[A-Z]", raw))
    if len(letters) < 2:
        raise StrategyDraftValidationError(f"invalid_length_relation_segment: {fact}")
    return letters[-2:]

def _segment_point_handles(
    segment: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    fact: str,
) -> tuple[str, str]:
    """把两字母线段名转成 point handles。"""
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
    for handle in step.reads:
        if not handle.startswith("point:"):
            continue
        point_name = _handle_name(handle)
        if _visible_point_on_curve_fact_for_name(point_name, step, index) is not None:
            point_names.append(point_name)
    for handle in step.reads:
        if not _is_point_coordinate_fact_handle(handle, index):
            continue
        point_name = _semantic_name(handle).split("_coordinate", 1)[0]
        if _visible_point_on_curve_fact_for_name(point_name, step, index) is not None:
            point_names.append(point_name)
    handles: list[str] = []
    for name in point_names:
        try:
            coordinate_handle = _point_coordinate_fact_for_name(name, step, index)
            if coordinate_handle is not None:
                index.path_for(coordinate_handle, expected_type="Point")
                handles.append(coordinate_handle)
                continue
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


def _curve_condition_point_name(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """由当前 step 读取的 point_on_curve fact 确定曲线点名。"""
    fact = index.fact_handle_by_type("point_on_curve", step=step)
    payload = index.fact_payload(fact)
    point_handle = payload.get("point")
    if isinstance(point_handle, str) and point_handle.startswith("point:"):
        return _handle_name(point_handle)
    name = _semantic_name(fact)
    if "_on_" in name:
        return name.split("_on_", 1)[0]
    raise StrategyDraftValidationError(f"curve_condition_point_not_found: {fact}")


def _curve_condition_target_point_name(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    curve_point_name: str,
) -> str:
    """由 target/answer 语义或显式 reads 确定目标点名。"""
    if step.target.startswith("point:"):
        return _handle_name(step.target)
    if step.target.startswith("answer:"):
        answer_key = _answer_key_from_handle(step.target)
        if answer_key:
            return answer_key
    for produced in step.produces:
        if produced.handle.startswith("answer:"):
            answer_key = _answer_key_from_handle(produced.handle)
            if answer_key:
                return answer_key
    candidates = [
        name
        for name in (_point_state_read_name(handle, index) for handle in step.reads)
        if name is not None and name != curve_point_name
    ]
    unique = _unique_ordered(candidates)
    if len(unique) == 1:
        return unique[0]
    raise StrategyDraftValidationError(
        "curve_condition_target_point_name_not_found: "
        f"step={step.step_id}, candidates={','.join(unique)}"
    )


def _point_state_path_for_name(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    *,
    error_code: str,
) -> str:
    """从当前 step reads 中寻找指定点名的已计算 Point 状态。"""
    explicit_fact_matches: list[tuple[str, str]] = []
    entity_matches: list[tuple[str, str]] = []
    for handle in step.reads:
        name = _point_state_read_name(handle, index)
        if name != point_name:
            continue
        try:
            path = _point_state_read_path(handle, step, index)
        except StrategyDraftValidationError:
            continue
        if handle.startswith("point:"):
            entity_matches.append((handle, path))
        else:
            explicit_fact_matches.append((handle, path))
    matches = explicit_fact_matches if explicit_fact_matches else entity_matches
    unique_paths = _unique_ordered([path for _handle, path in matches])
    if len(unique_paths) == 1:
        return unique_paths[0]
    if len(unique_paths) > 1:
        raise StrategyDraftValidationError(
            f"ambiguous_curve_condition_point_state: point={point_name}, "
            f"handles={','.join(handle for handle, _path in matches)}"
        )
    visible_matches = _visible_point_state_matches_for_name(point_name, step, index)
    unique_visible_paths = _unique_ordered([path for _handle, path in visible_matches])
    if len(unique_visible_paths) == 1:
        source_handle = _point_handle_for_state_fill(point_name, step, index)
        index.record_applied_fill(
            step=step,
            input_handle=source_handle or f"point:{step.scope_id}:{point_name}",
            required_type="Point",
            resolved_handle=visible_matches[0][0],
            reason="unique_visible_point_state_for_curve_condition",
        )
        return unique_visible_paths[0]
    if len(unique_visible_paths) > 1:
        raise StrategyDraftValidationError(
            f"ambiguous_curve_condition_point_state: point={point_name}, "
            f"handles={','.join(handle for handle, _path in visible_matches)}"
        )
    raise StrategyDraftValidationError(
        f"{error_code}: point={point_name}, step={step.step_id}"
    )


def _point_state_read_name(
    handle: str,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """如果 read handle 表示某个点的已计算状态，返回点名。"""
    binding = index.bindings.get(handle)
    if binding is not None and binding.value_type == "Point":
        if handle.startswith("point:"):
            return _handle_name(handle)
        if handle.startswith("fact:"):
            semantic = _semantic_name(handle)
            structured_name = _point_name_from_state_semantic(semantic)
            if structured_name is not None:
                return structured_name
            for separator in (
                "_coordinate",
                "_coord",
                "_parameterized",
                "_point",
                "_expr",
                "_expression",
            ):
                if separator in semantic:
                    return semantic.split(separator, 1)[0]
            return semantic.split("_", 1)[0]
    if handle.startswith("point:"):
        return _handle_name(handle)
    return None


def _point_name_from_state_semantic(semantic: str) -> str | None:
    """从点状态 fact 的语义名中读取点名，支持 ``E_param_coord`` 等变体。"""
    match = re.fullmatch(
        r"(?:optimal|minimum|extremal)_?(?P<point>[A-Za-z][A-Za-z0-9]*)"
        r"(?:_(?:coord|coordinate|point|expr|expression|numeric|value)[A-Za-z0-9_]*)?",
        semantic,
        flags=re.IGNORECASE,
    )
    if match is not None:
        point = match.group("point")
        return point[:1].upper() + point[1:]
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_"
        r"(?:(?:param|parametric|parameterized)_)?"
        r"(?:coord|coordinate|point)(?:_[A-Za-z0-9_]+)?",
        semantic,
        flags=re.IGNORECASE,
    )
    if match is not None:
        return match.group("point")
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_(?:point|expr|expression)(?:_[A-Za-z0-9]+)?",
        semantic,
        flags=re.IGNORECASE,
    )
    if match is not None:
        return match.group("point")
    return None


def _point_state_read_path(
    handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取某个 point state read 的 Point path。"""
    if handle.startswith("point:"):
        resolved = EntityStateResolver().resolve(handle, "Point", step, index)
        if resolved is not None:
            return resolved
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == "Point":
            return index.path_for(handle, expected_type="Point")
        raise StrategyDraftValidationError(f"point_state_read_not_found: {handle}")
    binding = index.bindings.get(handle)
    if binding is not None and binding.value_type == "Point":
        return index.path_for(handle, expected_type="Point")
    raise StrategyDraftValidationError(f"point_state_read_not_found: {handle}")


def _visible_point_state_matches_for_name(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> list[tuple[str, str]]:
    """从可见 prefix binding 中寻找同名点的已计算状态 fact。"""
    matches: list[tuple[str, str]] = []
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
        name = _point_state_read_name(handle, index)
        if name == point_name:
            matches.append((handle, binding.path))
    return matches


def _point_handle_for_state_fill(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """为 applied fill 记录补位来源实体 handle。"""
    try:
        return index.point_handle_by_name(point_name, step=step)
    except StrategyDraftValidationError:
        return None


def _answer_key_from_handle(handle: str) -> str:
    """读取 answer handle 的 key，用作 PointList 目标点名。"""
    if not handle.startswith("answer:"):
        return ""
    value = handle.split(":", 1)[1]
    if "." not in value:
        return value
    return value.rsplit(".", 1)[-1]


def _visible_point_on_curve_fact_for_name(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """查找当前 scope 可见的 ``point_on_curve`` 题设 fact。"""
    prefix = f"{point_name}_on_"
    for handle in index.handles_by_fact_type("point_on_curve"):
        if not _semantic_name(handle).startswith(prefix):
            continue
        fact_scope = index.handle_registry.handle_valid_scopes.get(handle)
        if fact_scope is None or not index.context.is_visible(step.scope_id, fact_scope):
            continue
        return handle
    return None


def _handle_name(handle: str) -> str:
    """读取 canonical handle 的名字段。"""
    return handle.rsplit(":", 1)[-1]


def _point_coordinate_fact_for_name(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从当前 step reads 中寻找同名点坐标 fact。

    LLM 常写 ``reads=[D_on_parabola, D_coordinate]``。这时 ``point:D``
    仍可能是 PointRef，但 ``D_coordinate`` 已经是可直接作为曲线点约束的 Point。
    """
    for handle in step.reads:
        if not _is_point_coordinate_fact_handle(handle, index):
            continue
        if _semantic_name(handle).split("_", 1)[0] == point_name:
            return handle
    return None

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
    handle = fresh_auxiliary_point_handle(
        step.scope_id,
        set(index.bindings) | set(index.handle_registry.entity_handles),
    )
    if handle is not None:
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


def _point_value_candidates_from_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> list[_PointValueCandidate]:
    """Return readable Point values grouped by geometric point name.

    LLMs often mix object reads such as ``point:ii:M`` with state reads such as
    ``fact:ii:M_coordinate_expr``. Binding rules should consume the Point state
    when it is available, while still accepting the object handle as a readable
    alias via ``EntityStateResolver``.
    """
    candidates: list[_PointValueCandidate] = []
    seen: set[str] = set()
    for handle in step.reads:
        candidate = _point_value_candidate_for_handle(handle, step, index)
        if candidate is None or candidate.handle in seen:
            continue
        seen.add(candidate.handle)
        candidates.append(candidate)
    return candidates


def _point_value_candidate_for_handle(
    handle: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> _PointValueCandidate | None:
    """Return a Point candidate represented by ``handle`` if it is readable."""
    binding = index.bindings.get(handle)
    if binding is None:
        return None
    if handle.startswith("point:"):
        if not _point_read_is_usable_as_point(handle, step, index):
            return None
        rank = 10 if binding.value_type == "Point" else 20
        return _PointValueCandidate(_handle_name(handle), handle, rank)
    if binding.value_type != "Point":
        return None
    if handle.startswith("fact:"):
        point_name = _point_name_from_state_semantic(_semantic_name(handle))
        if point_name is None and index.fact_types.get(handle) == "point_coordinate":
            point_name = _point_state_read_name(handle, index)
        if point_name is None:
            return None
        return _PointValueCandidate(point_name, handle, 0)
    if handle.startswith("answer:"):
        point_name = _answer_key_from_handle(handle)
        if not point_name:
            return None
        return _PointValueCandidate(point_name, handle, 5)
    return None


def _point_value_handles_for_names(
    names: tuple[str, str],
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    candidates: list[_PointValueCandidate],
) -> tuple[str, str] | None:
    """Bind a pair of point names to readable Point handles."""
    first = _point_value_handle_for_name(names[0], step, index, candidates)
    second = _point_value_handle_for_name(names[1], step, index, candidates)
    if first is None or second is None:
        return None
    if first == second:
        return None
    return first, second


def _point_value_handle_for_name(
    point_name: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    candidates: list[_PointValueCandidate],
) -> str | None:
    """Return the best explicit or visible Point value for ``point_name``."""
    explicit = [candidate for candidate in candidates if candidate.point_name == point_name]
    if explicit:
        return sorted(explicit, key=lambda item: (item.rank, item.handle))[0].handle

    visible_matches = _visible_point_state_matches_for_name(point_name, step, index)
    unique_visible_handles = _unique_ordered([handle for handle, _path in visible_matches])
    if len(unique_visible_handles) == 1:
        index.record_applied_fill(
            step=step,
            input_handle=f"point:{step.scope_id}:{point_name}",
            required_type="Point",
            resolved_handle=unique_visible_handles[0],
            reason="unique_visible_point_state_for_distance_endpoint",
        )
        return unique_visible_handles[0]
    if len(unique_visible_handles) > 1:
        raise StrategyDraftValidationError(
            f"ambiguous_distance_point_state: point={point_name}, "
            f"handles={','.join(unique_visible_handles)}"
        )

    try:
        point_handle = index.point_handle_by_name(point_name, step=step)
    except StrategyDraftValidationError:
        return None
    if _point_read_is_usable_as_point(point_handle, step, index):
        return point_handle
    return None


def _distance_endpoint_names_from_step(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    candidates: list[_PointValueCandidate],
) -> tuple[str, str] | None:
    """Infer intended distance endpoints from structured handles."""
    point_names = _known_point_names_for_distance(step, index, candidates)
    for handle in step.reads:
        if handle.startswith("segment:"):
            match = _point_pair_from_text(_semantic_name(handle), point_names)
            if match is not None:
                return match
    structured_texts = [step.target]
    structured_texts.extend(produced.handle for produced in step.produces)
    structured_texts.extend(
        produced.description for produced in step.produces
        if produced.description
    )
    for text in structured_texts:
        match = _point_pair_from_text(text, point_names)
        if match is not None:
            return match
    return None


def _known_point_names_for_distance(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    candidates: list[_PointValueCandidate],
) -> tuple[str, ...]:
    """Return point names known to the current step and visible context."""
    names = [candidate.point_name for candidate in candidates]
    names.extend(_handle_name(handle) for handle in index.entity_handles("point", step=step))
    return tuple(_unique_ordered(name for name in names if name))


def _point_pair_from_text(
    text: str,
    point_names: tuple[str, ...],
) -> tuple[str, str] | None:
    """Extract a point-name pair from a semantic handle or short description."""
    ordered_names = sorted(point_names, key=len, reverse=True)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", text):
        lowered = token.lower()
        if lowered in {"fact", "answer", "point", "segment", "length", "distance", "expr", "expression"}:
            continue
        for first in ordered_names:
            if not token.startswith(first):
                continue
            second = token[len(first):]
            if second and second != first and second in point_names:
                return first, second
        if len(token) == 2 and token.isupper():
            return token[0], token[1]
    return None


def _distance_point_handles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """为 distance_between_points 选择两端点。"""
    candidates = _point_value_candidates_from_reads(step, index)
    endpoint_names = _distance_endpoint_names_from_step(step, index, candidates)
    if endpoint_names is not None:
        endpoint_handles = _point_value_handles_for_names(
            endpoint_names,
            step,
            index,
            candidates,
        )
        if endpoint_handles is not None:
            return endpoint_handles

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
    unique_by_name: dict[str, _PointValueCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: (item.rank, item.handle)):
        unique_by_name.setdefault(candidate.point_name, candidate)
    if len(unique_by_name) == 2:
        ordered = list(unique_by_name.values())
        return ordered[0].handle, ordered[1].handle
    raise StrategyDraftValidationError(
        f"distance_points_not_found: {step.step_id}; "
        "need two readable Point states. Read each endpoint point object or its "
        "coordinate fact, and name the target/output with the segment endpoints "
        "when multiple point states are visible."
    )

def _angle_sum_y_axis_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从 angle_sum fact 推断角和转截点角色。

    优先读取 canonical fact payload 的 ``angle_terms`` 和 ``value``，不再从
    ``angle_sum_CBE_ACO_45`` 这类 handle 名里提取题面角。
    """
    fact = index.fact_handle_by_type("angle_sum", step=step)
    left, right = _angle_sum_terms(fact, index)
    return {
        "condition": fact,
        "x_axis_point": index.point_handle_by_name(left[1], step=step),
        "y_axis_point": index.point_handle_by_name(left[0], step=step),
        "reference_x_axis_point": index.point_handle_by_name(right[0], step=step),
        "origin": index.point_handle_by_name(right[2], step=step),
        "target": _point_output_handle(step, index),
    }


def _angle_equality_axis_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从等角 fact 推断正切比角色。

    若 fact payload 携带 ``left_angle/right_angle``，优先读取结构化字段；旧的
    produced fact 目前只保留 handle，因此仍兼容 ``angle_OBF_eq_ACO`` fallback。
    """
    fact = _angle_equality_handle(step, index)
    left, right = _angle_equality_terms(fact, index)
    return {
        "angle_equality": fact,
        "x_axis_point": index.point_handle_by_name(left[1], step=step),
        "target": index.point_handle_by_name(left[2], step=step),
        "reference_x_axis_point": index.point_handle_by_name(right[0], step=step),
        "y_axis_point": index.point_handle_by_name(right[1], step=step),
        "origin": index.point_handle_by_name(right[2], step=step),
    }


def _angle_equality_handle(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取当前 step 明确引用的 AngleEquality fact。"""
    for handle in step.reads:
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == "AngleEquality":
            return handle
        if handle.startswith("fact:") and re.fullmatch(
            r"angle_[A-Za-z]{3}_eq_[A-Za-z]{3}",
            _semantic_name(handle),
        ):
            return handle
    raise StrategyDraftValidationError(f"angle_equality_handle_not_found: {step.step_id}")


def _angle_sum_terms(
    fact: str,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """读取 angle_sum fact 的两个三字母角。"""
    payload = index.handle_registry.fact_payloads.get(fact)
    if payload is not None:
        terms = payload.get("angle_terms")
        if (
            isinstance(terms, list)
            and len(terms) == 2
            and all(isinstance(item, str) and re.fullmatch(r"[A-Za-z]{3}", item) for item in terms)
        ):
            return terms[0], terms[1]
    name = _semantic_name(fact)
    match = re.fullmatch(
        r"angle_sum_(?P<left>[A-Za-z]{3})_(?P<right>[A-Za-z]{3})_45",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_angle_sum_fact_payload: {fact}")
    return match.group("left"), match.group("right")


def _angle_equality_terms(
    fact: str,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """读取 AngleEquality fact 的左右两个三字母角。"""
    payload = index.handle_registry.fact_payloads.get(fact)
    if payload is not None:
        left = payload.get("left_angle")
        right = payload.get("right_angle")
        if (
            isinstance(left, str)
            and isinstance(right, str)
            and re.fullmatch(r"[A-Za-z]{3}", left)
            and re.fullmatch(r"[A-Za-z]{3}", right)
        ):
            return left, right
    name = _semantic_name(fact)
    match = re.fullmatch(
        r"angle_(?P<left>[A-Za-z]{3})_eq_(?P<right>[A-Za-z]{3})",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_angle_equality_fact_payload: {fact}")
    return match.group("left"), match.group("right")


def _line_parabola_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从 step reads 推断“直线两点 + 已知曲线交点 + 目标点”。"""
    target = _point_output_handle(step, index)
    line_points = [
        handle for handle in step.reads
        if handle.startswith("point:")
        and handle != target
        and _point_read_is_usable_as_point(handle, step, index)
    ]
    line_points.extend(
        handle for handle in _point_handles_from_coordinate_fact_reads(step, index)
        if handle != target
    )
    line_points = _unique_ordered(line_points)
    if len(line_points) < 2:
        raise StrategyDraftValidationError(f"line_parabola_line_points_not_found: {step.step_id}")
    known_candidates = _curve_point_names_from_reads(step, index)
    known = None
    for handle in line_points:
        if _handle_name(handle) in known_candidates:
            known = handle
            break
    if known is None:
        known = line_points[0]
    other_points = [handle for handle in line_points if handle != known]
    if not other_points:
        raise StrategyDraftValidationError(f"line_parabola_second_point_not_found: {step.step_id}")
    return {
        "line_p1": known,
        "line_p2": other_points[0],
        "known_point": known,
        "target": target,
    }

def _point_handles_from_coordinate_fact_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """从 step reads 中的点坐标 fact 反推出对应 point handle。"""
    result: list[str] = []
    for handle in step.reads:
        if not _is_point_coordinate_fact_handle(handle, index):
            continue
        point_name = _semantic_name(handle).split("_coordinate", 1)[0]
        try:
            result.append(index.point_handle_by_name(point_name, step=step))
        except StrategyDraftValidationError:
            continue
    return result

def _curve_point_names_from_reads(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> set[str]:
    """读取 step 显式读入的 point_on_curve fact 对应点名。"""
    names: set[str] = set()
    for handle in step.reads:
        if index.fact_types.get(handle) != "point_on_curve":
            continue
        names.add(_semantic_name(handle).split("_on_", 1)[0])
    return names

def _equal_length_ray_roles(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """推断等长射线构造角色。

    兼容旧的解法产物式 ``G_on_ray_CD_with_CG_eq_CB`` fact；新的 canonical
    ProblemIR 不预置辅助点 G，而是从题面真实条件（点在射线、点在线段、等长关系）
    和当前 step 的 ``creates/produces`` 推断要构造的目标点。
    """
    if index.handles_by_fact_type("equal_length_ray_point"):
        return _equal_length_ray_roles_from_constructed_fact(step, index)
    return _equal_length_ray_roles_from_problem_facts(step, index)


def _equal_length_ray_roles_from_constructed_fact(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从 ``G_on_ray_CD_with_CG_eq_CB`` 这类旧 fact 推断角色。"""
    fact = index.fact_handle_by_type("equal_length_ray_point", step=step)
    name = _semantic_name(fact)
    match = re.fullmatch(
        r"(?P<target>[A-Za-z0-9_]+)_on_ray_(?P<ray>[A-Za-z]{2})_with_"
        r"(?P<left>[A-Za-z]{2})_eq_(?P<right>[A-Za-z]{2})",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_equal_length_ray_fact_name: {fact}")
    ray = match.group("ray")
    left = match.group("left")
    right = match.group("right")
    if left[0] != ray[0] or right[0] != ray[0]:
        raise StrategyDraftValidationError(f"equal_length_ray_anchor_mismatch: {fact}")
    return {
        "anchor": index.point_handle_by_name(ray[0], step=step),
        "ray_point": index.point_handle_by_name(ray[1], step=step),
        "reference_point": index.point_handle_by_name(right[1], step=step),
        "target": index.point_handle_by_name(match.group("target"), step=step),
    }


def _equal_length_ray_roles_from_problem_facts(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从题面原始条件推断射线等长构造角色。

    优先读取 canonical ProblemIR 的结构化字段：``point_on_ray.point/ray``、
    ``point_on_segment.point/segment``、``equal_length_condition.left/right``。
    只有旧数据缺少这些字段时，才退回到语义名正则解析。
    """
    ray_fact = index.fact_handle_by_type("point_on_ray", step=step)
    segment_fact = index.fact_handle_by_type("point_on_segment", step=step)
    equal_fact = index.fact_handle_by_type("equal_length_condition", step=step)
    if _equal_length_ray_facts_have_structured_payload(
        index,
        ray_fact=ray_fact,
        segment_fact=segment_fact,
        equal_fact=equal_fact,
    ):
        return _equal_length_ray_roles_from_structured_problem_facts(
            step,
            index,
            ray_fact=ray_fact,
            segment_fact=segment_fact,
            equal_fact=equal_fact,
        )
    return _equal_length_ray_roles_from_legacy_problem_fact_names(
        step,
        index,
        ray_fact=ray_fact,
        segment_fact=segment_fact,
        equal_fact=equal_fact,
    )


def _equal_length_ray_facts_have_structured_payload(
    index: CanonicalRuntimeBindingIndex,
    *,
    ray_fact: str,
    segment_fact: str,
    equal_fact: str,
) -> bool:
    """判断射线等长构造所需 facts 是否携带结构化字段。"""
    ray_payload = index.fact_payload(ray_fact)
    segment_payload = index.fact_payload(segment_fact)
    equal_payload = index.fact_payload(equal_fact)
    return (
        isinstance(ray_payload.get("point"), str)
        and isinstance(ray_payload.get("ray"), str)
        and isinstance(segment_payload.get("point"), str)
        and isinstance(segment_payload.get("segment"), str)
        and "left" in equal_payload
        and "right" in equal_payload
    )


def _equal_length_ray_roles_from_structured_problem_facts(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    *,
    ray_fact: str,
    segment_fact: str,
    equal_fact: str,
) -> dict[str, str]:
    """从结构化 point_on_ray / point_on_segment / equal_length fact 推断角色。"""
    ray_payload = index.fact_payload(ray_fact)
    segment_payload = index.fact_payload(segment_fact)
    equal_payload = index.fact_payload(equal_fact)

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

    ray_equal_endpoint = _other_endpoint_handle(left, anchor) if ray_dynamic_point in left else (
        _other_endpoint_handle(right, anchor) if ray_dynamic_point in right else None
    )
    segment_equal_endpoint = _other_endpoint_handle(left, anchor) if segment_dynamic_point in left else (
        _other_endpoint_handle(right, anchor) if segment_dynamic_point in right else None
    )
    if ray_equal_endpoint != ray_dynamic_point:
        raise StrategyDraftValidationError(
            f"equal_length_ray_dynamic_point_mismatch: {ray_fact}:{equal_fact}"
        )
    if segment_equal_endpoint != segment_dynamic_point:
        raise StrategyDraftValidationError(
            f"equal_length_segment_dynamic_point_mismatch: {segment_fact}:{equal_fact}"
        )
    reference_candidates = [handle for handle in segment_endpoints if handle != anchor]
    if len(reference_candidates) != 1:
        raise StrategyDraftValidationError(f"equal_length_reference_point_not_found: {segment_fact}")
    return {
        "anchor": anchor,
        "ray_point": ray_through,
        "reference_point": reference_candidates[0],
        "target": _point_output_handle(step, index),
    }


def _equal_length_ray_roles_from_legacy_problem_fact_names(
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    *,
    ray_fact: str,
    segment_fact: str,
    equal_fact: str,
) -> dict[str, str]:
    """从旧语义名 ``N_on_ray_CD``、``M_on_segment_BC``、``CN_eq_CM`` 推断角色。"""
    ray_match = re.fullmatch(
        r"(?P<point>[A-Za-z])_on_ray_(?P<ray>[A-Za-z]{2})",
        _semantic_name(ray_fact),
    )
    segment_match = re.fullmatch(
        r"(?P<point>[A-Za-z])_on_segment_(?P<segment>[A-Za-z]{2})",
        _semantic_name(segment_fact),
    )
    equal_match = re.fullmatch(
        r"(?P<left>[A-Za-z]{2})_eq_(?P<right>[A-Za-z]{2})",
        _semantic_name(equal_fact),
    )
    if ray_match is None:
        raise StrategyDraftValidationError(f"invalid_point_on_ray_fact_name: {ray_fact}")
    if segment_match is None:
        raise StrategyDraftValidationError(f"invalid_point_on_segment_fact_name: {segment_fact}")
    if equal_match is None:
        raise StrategyDraftValidationError(f"invalid_equal_length_condition_name: {equal_fact}")

    ray = ray_match.group("ray")
    segment = segment_match.group("segment")
    left = equal_match.group("left")
    right = equal_match.group("right")
    common = set(left) & set(right)
    if len(common) != 1:
        raise StrategyDraftValidationError(f"equal_length_common_anchor_not_found: {equal_fact}")
    anchor = next(iter(common))
    if ray[0] != anchor:
        raise StrategyDraftValidationError(
            f"equal_length_ray_anchor_mismatch: {ray_fact}:{equal_fact}"
        )
    if anchor not in segment:
        raise StrategyDraftValidationError(
            f"equal_length_segment_anchor_mismatch: {segment_fact}:{equal_fact}"
        )
    reference_name = _other_endpoint(segment, anchor)
    return {
        "anchor": index.point_handle_by_name(anchor, step=step),
        "ray_point": index.point_handle_by_name(ray[1], step=step),
        "reference_point": index.point_handle_by_name(reference_name, step=step),
        "target": _point_output_handle(step, index),
    }


def _payload_handle(payload: Mapping[str, Any], key: str, *, context: str) -> str:
    """读取 payload 中的 canonical handle 字符串字段。"""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(f"structured_payload_field_missing: {context}.{key}")
    return value


def _segment_endpoints_from_entity_payload(
    index: CanonicalRuntimeBindingIndex,
    segment_handle: str,
) -> tuple[str, str]:
    """读取 segment entity 的两个端点 handle。"""
    payload = index.entity_payload(segment_handle)
    endpoints = payload.get("endpoints")
    if (
        not isinstance(endpoints, list)
        or len(endpoints) != 2
        or not all(isinstance(item, str) for item in endpoints)
    ):
        raise StrategyDraftValidationError(f"segment_endpoints_missing: {segment_handle}")
    return endpoints[0], endpoints[1]


def _length_endpoint_handles(
    value: Any,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
    *,
    context: str,
) -> tuple[str, str]:
    """把 equal_length 的一侧解析成两个 point handle。

    支持未来的结构化端点列表，也兼容当前 ``"CN"`` 这种短字符串。
    """
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ):
        return value[0], value[1]
    if isinstance(value, str) and ":" in value:
        raise StrategyDraftValidationError(f"invalid_length_endpoint_pair: {context}")
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z]{2}", value):
        return (
            index.point_handle_by_name(value[0], step=step),
            index.point_handle_by_name(value[1], step=step),
        )
    raise StrategyDraftValidationError(f"invalid_length_endpoint_pair: {context}")


def _other_endpoint_handle(pair: tuple[str, str], anchor: str) -> str:
    """返回二元端点中非 anchor 的另一个端点。"""
    if pair[0] == anchor:
        return pair[1]
    if pair[1] == anchor:
        return pair[0]
    raise StrategyDraftValidationError(f"endpoint_pair_missing_anchor: {pair}:{anchor}")

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
