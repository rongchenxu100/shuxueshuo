"""Method binding selector registry。

FamilySpec 通过 selector 字符串声明 method input 的语义绑定；本模块把这些
selector 解析成具体 RuntimeContext path。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping

from shuxueshuo_server.solver.contracts import (
    LegacySelectorInputBindingSpec,
    MethodInputBindingSpec,
    OrdinalZeroTemplateDerivationSpec,
)
from shuxueshuo_server.solver.family.models import MethodBindingRuleSpec, SolverFamilySpec
from shuxueshuo_server.solver.runtime.auxiliary_points import fresh_auxiliary_point_handle
from shuxueshuo_server.solver.runtime.condition_roles import (
    resolve_read_closed_right_angle_method_roles,
)
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.path_reduction_roles import (
    resolve_read_closed_path_reduction_inputs,
)
from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_legacy_path_expression,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionAdapterRegistry,
    identity_safe_parameter_value_expansion,
)
from shuxueshuo_server.solver.runtime.functional_compile_contract import (
    compile_capability_id as _compile_capability_id,
    compile_created_entities as _compile_created_entities,
    compile_input_handles as _compile_input_handles,
    compile_return_outputs as _compile_return_outputs,
    compile_target_handle as _compile_target_handle,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    _handle_name,
    _handle_scope,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    FunctionalFunctionBindingEvent,
    FunctionalCompileStepView,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.output_type_inference import (
    produced_output_type as _produced_output_type,
)
from shuxueshuo_server.solver.utils import unique_ordered as _unique_ordered
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    _runtime_path_for_scope,
    _segment_membership_point,
    _segment_relation_names,
)
from shuxueshuo_server.solver.runtime.entity_state_resolver import EntityStateResolver
from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
    EqualLengthRayRoleError,
    build_equal_length_ray_role_candidates,
)

BindingSelectorFn = Callable[
    [FunctionalCompileStepView, CanonicalRuntimeBindingIndex, Mapping[str, str]],
    str | None,
]

ExpansionSelectorFn = Callable[
    [FunctionalCompileStepView, CanonicalRuntimeBindingIndex, Mapping[str, str]],
    dict[str, str],
]


@dataclass(frozen=True)
class _PointValueCandidate:
    """A readable Point value for one geometric point object."""

    point_name: str
    handle: str
    rank: int


_CURVE_MEMBERSHIP_FACT_TYPES = frozenset(
    {
        "point_on_curve",
        "point_on_curve_with_x_coordinate",
    }
)

class MethodBindingRuleRegistry:
    """把 FunctionalCompileStepView semantic handles 绑定到 method input slots。

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
        self.function_adapters = FunctionAdapterRegistry(
            selectors=self.selectors,
            expansion_selectors=self.expansion_selectors,
        )
        self.function_binding_events: list[FunctionalFunctionBindingEvent] = []
        self._validate_rule_selectors()

    @classmethod
    def from_family_spec(cls, family_spec: SolverFamilySpec) -> "MethodBindingRuleRegistry":
        """从 FamilySpec 构建 binding rule registry。"""
        return cls(tuple(family_spec.method_binding_rules))

    def bind(
        self,
        method_id: str,
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        *,
        local_outputs: dict[str, str] | None = None,
        include_expansion_selectors: bool = True,
        expansion_selectors_override: tuple[str, ...] | None = None,
        exact_inputs: Mapping[str, str] | None = None,
        method_input_specs: Mapping[str, object] | None = None,
        distinct_arg_groups: tuple[tuple[str, ...], ...] = (),
        apply_constraint_analyzer: bool = True,
    ) -> dict[str, str]:
        """返回 method invocation inputs。"""
        local_outputs = local_outputs or {}
        rule = self.rules.get(method_id)
        adapter = self.function_adapters.rule_for(method_id)
        if adapter is not None:
            try:
                inputs = self.function_adapters.bind(
                    method_id,
                    step,
                    index,
                    local_outputs=local_outputs,
                    include_expansion_selectors=include_expansion_selectors,
                    expansion_selectors_override=(
                        expansion_selectors_override
                        if expansion_selectors_override is not None
                        else (
                            rule.expansion_selectors
                            if rule is not None and include_expansion_selectors
                            else None
                        )
                    ),
                    input_bindings_override=(
                        rule.input_bindings
                        if rule is not None
                        else None
                    ),
                    exact_inputs=exact_inputs,
                    method_input_specs=method_input_specs,
                    distinct_arg_groups=distinct_arg_groups,
                    apply_constraint_analyzer=apply_constraint_analyzer,
                )
                self.function_binding_events.append(
                    FunctionalFunctionBindingEvent(
                        step_id=step.step_id,
                        scope_id=step.scope_id,
                        method_id=method_id,
                        function_id=adapter.adapter_id,
                        status="success",
                        arg_repairs=(
                            self.function_adapters.last_arg_repairs
                        ),
                    )
                )
                return inputs
            except StrategyDraftValidationError as exc:
                self.function_binding_events.append(
                    FunctionalFunctionBindingEvent(
                        step_id=step.step_id,
                        scope_id=step.scope_id,
                        method_id=method_id,
                        function_id=adapter.adapter_id,
                        status="failure",
                        errors=(str(exc),),
                    )
                )
                raise
        if rule is None:
            raise StrategyDraftValidationError(f"method_binding_rule_missing: {method_id}")
        inputs: dict[str, str] = dict(exact_inputs or {})
        for binding in rule.input_bindings:
            if binding.input_name in inputs:
                continue
            if isinstance(binding, MethodInputBindingSpec):
                if isinstance(
                    binding.derivation,
                    OrdinalZeroTemplateDerivationSpec,
                ):
                    continue
                if not binding.required:
                    continue
                raise StrategyDraftValidationError(
                    "planner.method_input_binding_lowerer_missing: "
                    f"method={method_id}, input={binding.input_name}"
                )
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
            expanded = identity_safe_parameter_value_expansion(
                self._expand(
                    selector,
                    step,
                    index,
                    local_outputs=local_outputs,
                ),
                existing_inputs=inputs,
            )
            for input_name, path in expanded.items():
                inputs.setdefault(input_name, path)
        return inputs

    def rule_for(self, method_id: str) -> MethodBindingRuleSpec | None:
        """返回 method 的 binding rule；不存在时返回 None。"""
        return self.rules.get(method_id)

    def _select(
        self,
        selector: str,
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
                if isinstance(binding, MethodInputBindingSpec):
                    continue
                if not isinstance(binding, LegacySelectorInputBindingSpec):
                    raise StrategyDraftValidationError(
                        "planner.method_input_binding_contract_invalid: "
                        f"method={rule.method_id}, input={binding.input_name}"
                    )
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        local_path = local_outputs.get(f"type:{value_type}")
        if local_path is not None:
            return local_path
        return _path_for_readable_type(index, step, value_type)

    return select


def _read_type_union_selector(*value_types: str) -> BindingSelectorFn:
    """创建可读取一组 runtime 类型的 selector，优先遵守 _compile_input_handles(step) 顺序。"""

    def select(
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        for value_type in value_types:
            local_path = local_outputs.get(f"type:{value_type}")
            if local_path is not None:
                return local_path
        value_type_set = set(value_types)
        for handle in _compile_input_handles(step):
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
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        return value

    return select

def _function_parabola_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """Read the latest visible state of the canonical parabola object.

    The runtime index already contains paths reserved for the current step's
    outputs. Scanning every visible binding here can therefore select the
    Parabola that this invocation has not produced yet. Explicit reads remain
    the first choice, but a named function is state-bearing: a later
    refinement call must continue from the latest earlier typed write even
    when the LLM only supplied the new mathematical constraint. The projected
    state order and visible runtime bindings provide that deterministic view.
    """
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == "Parabola":
            return binding.path
    latest = index.latest_projected_state_write(
        "function:problem:parabola",
        before_step_id=step.step_id,
    )
    if latest is not None:
        binding = index.bindings.get(latest.produced_handle)
        if binding is not None and binding.value_type == "Parabola":
            return binding.path
    return index.path_for("function:problem:parabola", expected_type="Expression")


def _quadratic_template_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """Read the immutable ProblemIR function template, not a refined state."""

    return index.path_for(
        "function:problem:parabola",
        expected_type="Expression",
    )

def _square_side_start_selector(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 square 已知边起点 PointRef。"""
    return index.point_identity_path_for(_square_side_start_handle(step, index))

def _square_side_end_ref_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 square 已知边终点 PointRef。"""
    return index.point_identity_path_for(_square_side_end_handle(step, index))

def _square_side_start_handle(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """根据当前 target 从 reads 中选择 square 已知边第二端点。"""
    side_start = _square_side_start_handle(step, index)
    target = _point_output_handle(step, index)
    candidates: list[str] = []
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取当前 step 目标点的 PointRef。"""
    handle = _point_output_handle(step, index)
    reuse_write = next(
        (
            write
            for write in index.projected_state_writes
            if write.step_id == step.step_id
            and write.runtime_type == "Point"
            and write.object_ref == handle
            and write.allocation_action == "reuse"
        ),
        None,
    )
    if reuse_write is not None:
        # A reuse allocation is only a candidate. Execute it against the
        # step-local target so the transaction layer can compare the actual
        # coordinate without overwriting the existing typed StateVersion.
        return index.runtime_reuse_point_probe_path_for(
            handle,
            step_id=step.step_id,
        )
    if any(
        write.step_id == step.step_id
        and write.runtime_type == "Point"
        and write.object_ref == handle
        and write.write_mode == "transition"
        for write in index.projected_state_writes
    ):
        return _point_transition_target_selector(step, index, local_outputs)
    index.ensure_point_declaration(handle, definition="method_output_point")
    return index.point_ref_path_for(handle)


def _point_output_state_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """Read the latest visible state of the point selected as output target."""

    handle = _point_output_handle(step, index)
    projected = next(
        (
            write
            for write in index.projected_state_writes
            if write.step_id == step.step_id
            and write.object_ref == handle
            and write.runtime_type == "Point"
        ),
        None,
    )
    if projected is not None and projected.previous_version_id is not None:
        return index.runtime_path_for_state_version(
            projected.previous_version_id,
            consumer_scope_id=step.scope_id,
            consumer=f"{step.step_id}.target_state",
        )
    return _point_state_path_for_name(
        _handle_name(handle),
        step,
        index,
        error_code="point_output_state_not_found",
    )


def _point_transition_target_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """Bind a PointRef|Point target without treating an existing Point as duplicate."""
    handle = _point_output_handle(step, index)
    binding = index.binding_for(handle)
    if binding.value_type == "Point":
        return index.path_for(handle, expected_type="PointRef|Point")
    index.ensure_point_declaration(handle, definition="method_transition_point")
    return index.path_for(handle, expected_type="PointRef|Point")

def _translated_point_selector(role: str) -> BindingSelectorFn:
    """创建平移点 method 的 source/target selector。"""

    def select(
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        target_handle = _point_output_handle(step, index)
        target_path = index.immutable_problem_point_ref_path_for(target_handle)
        if role == "target":
            return target_path
        target_payload = index.handle_registry.entity_payloads.get(target_handle)
        if isinstance(target_payload, Mapping):
            source_name = (
                target_payload.get("of")
                or target_payload.get("source")
                or target_payload.get("base")
            )
        else:
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        roles = resolve_read_closed_right_angle_method_roles(
            step,
            index,
        )
        values = {
            "anchor": (roles.anchor, "Point"),
            "reference": (roles.reference, "Point"),
            "target": (roles.target, "PointRef"),
        }
        handle, expected_type = values[role]
        return index.path_for(handle, expected_type=expected_type)

    return select

def _length_segment_selector(role: str) -> BindingSelectorFn:
    """创建线段长度条件的端点 selector。"""

    def select(
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取长度条件，兼容长度平方与两线段比例关系。"""
    return index.path_for(_length_condition_handle(step, index), expected_type="Condition")

def _parameter_symbol_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取 family/runtime 选定的主参数符号。"""
    return index.parameter_symbol_path()


def _parameter_symbol_from_reads_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """Prefer an explicit target Symbol without changing legacy semantics."""
    explicit = _explicit_symbol_paths(step, index)
    if len(explicit) == 1:
        return explicit[0]
    return index.parameter_symbol_path()


def _parameter_symbol_from_reads_or_expression_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """Bind the unique Symbol identity read by, or free in, the input expression."""
    explicit = [
        binding.path
        for handle in _compile_input_handles(step)
        if (binding := index.bindings.get(handle)) is not None
        and binding.value_type == "Symbol"
    ]
    explicit = _unique_ordered(explicit)
    if len(explicit) == 1:
        return explicit[0]
    if len(explicit) > 1:
        raise StrategyDraftValidationError(
            "function.arg_ambiguous: parameter Symbol has multiple explicit reads"
        )
    expression_path = _path_for_readable_type(index, step, "MinimumExpression")
    expression = index.context.read_path(
        expression_path,
        from_scope_id=step.scope_id,
        expected_type="MinimumExpression",
    ).value
    free_symbols = set(getattr(expression, "free_symbols", set()))
    candidates: list[str] = []
    for binding in index.bindings.values():
        if binding.value_type != "Symbol":
            continue
        try:
            symbol = index.context.read_path(
                binding.path,
                from_scope_id=step.scope_id,
                expected_type="Symbol",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        if symbol in free_symbols:
            candidates.append(binding.path)
    candidates = _unique_ordered(candidates)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise StrategyDraftValidationError(
            "function.return_identity_unresolved: "
            "no visible Symbol StateSlot matches the expression free symbols"
        )
    raise StrategyDraftValidationError(
        "function.arg_ambiguous: parameter Symbol matches multiple free symbols"
    )

def _parameter_constraint_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str | None:
    """读取与当前待求 Symbol identity 对应的参数约束。"""
    explicit = _explicit_symbol_paths(step, index)
    if len(explicit) == 1:
        symbol_path = explicit[0]
        symbol_handles = {
            handle
            for handle, binding in index.bindings.items()
            if binding.path == symbol_path and binding.value_type == "Symbol"
        }
        matching = [
            handle
            for handle in index.handles_by_fact_type("symbol_constraint")
            if index.handle_registry.fact_payloads.get(handle, {}).get("subject")
            in symbol_handles
        ]
        if len(matching) == 1:
            return index.path_for(matching[0], expected_type="Constraint")
        if not matching:
            return None
    return index.parameter_constraint_path()


def _explicit_symbol_paths(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    return _unique_ordered(
        binding.path
        for handle in _compile_input_handles(step)
        if (binding := index.bindings.get(handle)) is not None
        and binding.value_type == "Symbol"
    )


def _known_parameter_substitution_pair(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str] | None:
    """Resolve one already-known Symbol value used by the current input state."""
    target_path = _parameter_symbol_from_reads_selector(step, index, {})
    candidates = [
        pair
        for pair in parameter_substitution_pairs_from_reads(step, index)
        if pair[0] != target_path
    ]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise StrategyDraftValidationError(
            "function.arg_ambiguous: multiple known parameter substitutions "
            "are required by the input state"
        )
    return candidates[0]


def parameter_substitution_pairs_from_reads(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[tuple[str, str], ...]:
    """Resolve every explicitly read ParameterValue to its Symbol identity.

    Scalar result closure uses this read-closed projection instead of guessing
    variable names or scanning all globally visible values. Conflicting values
    for the same Symbol are rejected before runtime execution.
    """
    candidates: list[tuple[str, str]] = []
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "ParameterValue":
            continue
        symbol_path = _parameter_symbol_path_for_value(
            handle,
            index,
            step=step,
        )
        candidates.append((symbol_path, binding.path))
    candidates = list(dict.fromkeys(candidates))
    values_by_symbol: dict[str, set[str]] = {}
    for symbol_path, value_path in candidates:
        values_by_symbol.setdefault(symbol_path, set()).add(value_path)
    conflicts = {
        symbol_path: tuple(sorted(value_paths))
        for symbol_path, value_paths in values_by_symbol.items()
        if len(value_paths) > 1
    }
    if conflicts:
        raise StrategyDraftValidationError(
            "function.arg_ambiguous: conflicting ParameterValue states for "
            f"the same Symbol: {conflicts}"
        )
    return tuple(candidates)


def _known_parameter_symbol_from_reads_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str | None:
    pair = _known_parameter_substitution_pair(step, index)
    return pair[0] if pair is not None else None


def _known_parameter_value_from_reads_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str | None:
    pair = _known_parameter_substitution_pair(step, index)
    return pair[1] if pair is not None else None

def _dynamic_constraint_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取动点参数范围约束。"""
    return index.dynamic_constraint_path(step=step)

def _dynamic_symbol_selector(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取动点参数符号。"""
    return index.dynamic_parameter_symbol_path(step=step)

def _x_axis_known_point_selector(
    step: FunctionalCompileStepView,
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
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取当前 scope 可见的 MinimumExpression。"""
    return _path_for_readable_type(index, step, "MinimumExpression")

def _weighted_path_condition_selector(
    step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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


def _weighted_path_identity_selector(role: str) -> BindingSelectorFn:
    """Bind an immutable canonical PointRef for transformation metadata."""

    def select(
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        fixed, moving, curve = _weighted_path_roles(step, index)
        values = {
            "moving_point_ref": moving,
            "linked_fixed_endpoint_ref": curve,
        }
        return index.point_identity_path_for(values[role])

    return select

def _weighted_auxiliary_point_ref_selector(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> str:
    """读取加权路径辅助点坐标。"""
    auxiliary = _auxiliary_point_handle_from_reads(step, index)
    return index.path_for(auxiliary, expected_type="Point")


def _square_path_fixed_endpoint_ref_selector(
    position: int,
) -> BindingSelectorFn:
    """Bind producer-owned square-path endpoint identity metadata."""

    def select(
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
        local_outputs: Mapping[str, str],
    ) -> str:
        side_start, other_fixed = _square_path_fixed_endpoint_handles(
            step,
            index,
        )
        handle = side_start if position == 1 else other_fixed
        return index.point_identity_path_for(handle)

    return select


def _square_path_fixed_endpoint_handles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str]:
    """Resolve square-path roles from exact fact references when available."""

    square_handle = index.fact_handle_by_type("square", step=step)
    square = index.fact_payload(square_handle)
    vertices = tuple(str(item) for item in square.get("vertices", ()))
    if (
        len(vertices) < 4
        or not all(
            handle.startswith("point:") and handle in index.bindings
            for handle in vertices[:4]
        )
    ):
        raise StrategyDraftValidationError(
            "square_path_roles_missing: ordered square vertices"
        )
    side_start, side_end, _, moving_vertex = vertices[:4]

    midpoint_handle = index.fact_handle_by_type(
        "midpoint_definition",
        step=step,
    )
    midpoint = index.fact_payload(midpoint_handle)
    midpoint_point = str(midpoint.get("point", ""))
    midpoint_of = tuple(str(item) for item in midpoint.get("of", ()))
    if (
        midpoint_point not in index.bindings
        or len(midpoint_of) != 2
        or set(midpoint_of) != {side_start, side_end}
    ):
        raise StrategyDraftValidationError(
            "square_path_roles_missing: midpoint of square side"
        )

    center_handle = index.fact_handle_by_type("square_center", step=step)
    center = index.fact_payload(center_handle)
    center_point = str(center.get("point", ""))
    if (
        center_point not in index.bindings
        or str(center.get("square", "")) not in {"", square_handle}
    ):
        raise StrategyDraftValidationError(
            "square_path_roles_missing: square center"
        )

    target_handle = index.fact_handle_by_type(
        "path_minimum_target",
        step=step,
    )
    target = index.fact_payload(target_handle)
    structured = target.get("terms")
    if isinstance(structured, list):
        endpoint_pairs = _typed_path_endpoint_pairs(
            structured,
            step=step,
            index=index,
            context="square_path",
        )
        if len(endpoint_pairs) != 3:
            raise StrategyDraftValidationError(
                "square_path_roles_missing: three typed path terms"
            )
        _validate_typed_path_display(
            endpoint_pairs,
            str(target.get("path", "")),
            step=step,
            index=index,
            context="square_path",
        )
        center_midpoint = _find_endpoint_pair(
            endpoint_pairs,
            center_point,
            midpoint_point,
        )
        remaining = [pair for pair in endpoint_pairs if pair != center_midpoint]
        midpoint_pairs = [pair for pair in remaining if midpoint_point in pair]
        if len(midpoint_pairs) != 1:
            raise StrategyDraftValidationError(
                "square_path_roles_missing: midpoint segment"
            )
        other_fixed = _other_endpoint_handle(
            midpoint_pairs[0],
            midpoint_point,
        )
        final_pairs = [pair for pair in remaining if pair != midpoint_pairs[0]]
        if len(final_pairs) != 1 or set(final_pairs[0]) != {
            other_fixed,
            moving_vertex,
        }:
            raise StrategyDraftValidationError(
                "square_path_roles_missing: moving segment"
            )
        return side_start, other_fixed

    # Old authored fixtures predate typed path terms. Restrict compatibility
    # to source-visible names; local handle ids still never become authority.
    segments = _segments_from_path_text(str(target.get("path", "")))
    moving_name = index.entity_semantic_name(moving_vertex)
    incident = tuple(segment for segment in segments if moving_name in segment)
    if len(incident) != 1:
        raise StrategyDraftValidationError(
            "square_path_roles_missing: moving segment"
        )
    fixed_name = _other_endpoint(incident[0], moving_name)
    return side_start, index.point_handle_by_name(fixed_name, step=step)


def _typed_path_endpoint_pairs(
    raw_terms: list[Any],
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    context: str,
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for term_index, raw_pair in enumerate(raw_terms):
        if (
            not isinstance(raw_pair, list)
            or len(raw_pair) != 2
            or not all(
                isinstance(handle, str)
                and handle.startswith("point:")
                and handle in index.bindings
                and index._handle_binding_visible(handle, step.scope_id)
                for handle in raw_pair
            )
        ):
            raise StrategyDraftValidationError(
                f"{context}_typed_term_invalid: "
                f"index={term_index}, term={raw_pair!r}"
            )
        pairs.append((str(raw_pair[0]), str(raw_pair[1])))
    return pairs


def _validate_typed_path_display(
    endpoint_pairs: list[tuple[str, str]],
    raw_path: str,
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    context: str,
) -> None:
    point_names = tuple(
        sorted(
            {
                index.entity_semantic_name(handle)
                for pair in endpoint_pairs
                for handle in pair
            }
        )
    )
    try:
        display_terms = parse_legacy_path_expression(
            raw_path,
            point_names=point_names,
            resolve_point=lambda name: name,
        )
    except PathTermParseError as exc:
        raise StrategyDraftValidationError(
            f"{context}_expression_invalid: {exc.code}: {exc}"
        ) from exc
    if len(display_terms) != len(endpoint_pairs):
        raise StrategyDraftValidationError(
            f"{context}_term_count_drift: "
            f"display={len(display_terms)}, structured={len(endpoint_pairs)}"
        )
    for term_index, (pair, display_term) in enumerate(
        zip(endpoint_pairs, display_terms)
    ):
        typed_names = {
            index.entity_semantic_name(pair[0]),
            index.entity_semantic_name(pair[1]),
        }
        display_names = {display_term.start, display_term.end}
        if typed_names != display_names:
            raise StrategyDraftValidationError(
                f"{context}_display_term_drift: index={term_index}, "
                f"typed={sorted(typed_names)}, display={sorted(display_names)}"
            )


def _find_endpoint_pair(
    pairs: list[tuple[str, str]],
    first: str,
    second: str,
) -> tuple[str, str]:
    matches = [pair for pair in pairs if set(pair) == {first, second}]
    if len(matches) != 1:
        raise StrategyDraftValidationError(
            "square_path_roles_missing: center-midpoint segment"
        )
    return matches[0]

def _path_reduction_selector(role: str) -> BindingSelectorFn:
    """创建两动点路径转化 recipe 的角色 selector。"""

    def select(
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
            handles=_compile_input_handles(step),
        )
        if not matches:
            matches = _straightening_minimum_endpoint_handles(
                step,
                index,
                semantic_suffixes=semantic_suffixes,
                handles=tuple(index.bindings),
            )
        unique_by_state: dict[tuple[str, str], str] = {}
        for handle in matches:
            binding = index.bindings.get(handle)
            if binding is None:
                continue
            identity = (_handle_scope(handle), _semantic_name(handle))
            existing = unique_by_state.get(identity)
            if existing is None or (
                handle.startswith("fact:")
                and not existing.startswith("fact:")
            ):
                unique_by_state[identity] = handle
        unique = list(unique_by_state.values())
        if len(unique) != 1:
            raise StrategyDraftValidationError(
                f"straightening_minimum_{role}_not_found: "
                f"step={step.step_id}, candidates={','.join(unique)}"
            )
        return index.path_for(unique[0], expected_type="Point")

    return select


def _straightening_minimum_endpoint_handles(
    step: FunctionalCompileStepView,
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
        step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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


def _free_quadratic_parameter_if_read(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> dict[str, str]:
    """Restore one explicit free coefficient from FunctionalPlan Symbol reads.

    FunctionalPlan exposes ``free_parameters`` as item-level Symbol refs, while
    the FunctionalCompileStepView compatibility bridge only carries canonical reads. Filtering
    those reads through the declared quadratic coefficient list recovers an
    unambiguous coefficient preference without treating dynamic parameters as
    coefficients or guessing from symbol names.
    """
    coefficient_value = index.context.read_path(
        "$problem.symbol_lists.quadratic_coefficients",
        from_scope_id=step.scope_id,
        expected_type="SymbolList",
    ).value
    coefficients = set(coefficient_value)
    matches: list[str] = []
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "Symbol":
            continue
        try:
            symbol = index.context.read_path(
                binding.path,
                from_scope_id=step.scope_id,
                expected_type="Symbol",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        if symbol in coefficients:
            matches.append(binding.path)
    matches = _unique_ordered(matches)
    if len(matches) == 1:
        return {"free_parameter": matches[0]}
    return {}


def _parameter_value_if_read(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    local_outputs: Mapping[str, str],
) -> dict[str, str]:
    """若 step 显式读取了参数值，则补充参数输入。"""
    parameter_value = _parameter_value_handle(step, index)
    if parameter_value is None:
        return {}
    parameter_path = _parameter_symbol_path_for_value(
        parameter_value,
        index,
        step=step,
    )
    return {
        "parameter": parameter_path,
        "parameter_value": index.path_for(parameter_value, expected_type="ParameterValue"),
    }


def _parameter_symbol_path_for_value(
    parameter_value_handle: str,
    index: CanonicalRuntimeBindingIndex,
    *,
    step: FunctionalCompileStepView,
) -> str:
    """Resolve a ParameterValue through its typed state/object identity.

    F5-C pins every problem-source value to an exact StateVersionId.  The
    logical key of that version owns the Symbol identity, even when the value
    is stored in a child scope.  Dynamic CallResult values carry the same
    identity on their projected producer write.  Only non-F5 compatibility
    callers may fall back to the older write-provenance lookup.
    """
    dependencies = tuple(
        item
        for item in index.projected_state_dependencies
        if item.step_id == step.step_id
        and item.produced_handle == parameter_value_handle
        and item.runtime_type == "ParameterValue"
    )
    object_ids = set()
    for dependency in dependencies:
        if dependency.state_version_id is not None:
            logical_key = dependency.state_version_id.slot_id.logical_key
            if (
                logical_key.state_kind != "value"
                or logical_key.runtime_type != "ParameterValue"
                or (
                    dependency.object_ref is not None
                    and dependency.object_ref != logical_key.object_id.value
                )
            ):
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_binding_drift: "
                    f"consumer={step.step_id}.parameter_value, "
                    f"handle={parameter_value_handle}, "
                    "reason=typed_parameter_value_identity_drift"
                )
            object_ids.add(logical_key.object_id)
            continue
        producer_writes = tuple(
            item
            for item in index.projected_state_writes
            if dependency.source_step_id is not None
            and item.step_id == dependency.source_step_id
            and item.produced_handle == dependency.produced_handle
            and (
                dependency.source_return_name is None
                or item.return_name == dependency.source_return_name
            )
            and item.runtime_type == "ParameterValue"
        )
        for write in producer_writes:
            if write.math_object_id is not None:
                object_ids.add(write.math_object_id)
            elif write.logical_state_key is not None:
                object_ids.add(write.logical_state_key.object_id)
    if dependencies:
        if len(object_ids) != 1:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={step.step_id}.parameter_value, "
                f"handle={parameter_value_handle}, "
                f"object_identity_count={len(object_ids)}"
            )
        object_id = next(iter(object_ids))
        if object_id.kind != "symbol":
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"consumer={step.step_id}.parameter_value, "
                f"handle={parameter_value_handle}, "
                f"object_kind={object_id.kind}"
            )
        return index.runtime_path_for_object_identity(
            object_id,
            expected_type="Symbol",
            consumer_scope_id=step.scope_id,
            consumer=f"{step.step_id}.parameter_value_symbol",
        )
    if index.problem_binding_authority:
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.runtime_state_binding_drift: "
            f"consumer={step.step_id}.parameter_value, "
            f"handle={parameter_value_handle}, "
            "reason=typed_parameter_value_dependency_missing"
        )

    provenance = next(
        (
            item
            for item in reversed(index.state_write_provenance)
            if item.produced_handle == parameter_value_handle
            and item.runtime_type == "ParameterValue"
        ),
        None,
    )
    if provenance is None or provenance.object_ref is None:
        raise StrategyDraftValidationError(
            "function.return_identity_unresolved: "
            f"parameter_value={parameter_value_handle}"
        )
    symbol_bindings = [
        binding
        for handle, binding in index.bindings.items()
        if handle == provenance.object_ref and binding.value_type == "Symbol"
    ]
    if len(symbol_bindings) == 1:
        return symbol_bindings[0].path
    raise StrategyDraftValidationError(
        "function.return_identity_unresolved: "
        f"parameter_value={parameter_value_handle}, symbol={provenance.object_ref}"
    )


def _curve_points_if_parameterized(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    "quadratic_template": _quadratic_template_selector,
    "square:side_start": _square_side_start_selector,
    "square:side_end": _square_side_end_selector,
    "square:side_start_ref": _square_side_start_ref_selector,
    "square:side_end_ref": _square_side_end_ref_selector,
    "quadratic_coefficients": _constant_selector("$problem.symbol_lists.quadratic_coefficients"),
    "point_output_ref": _point_output_ref_selector,
    "point_output_state": _point_output_state_selector,
    "point_transition_target": _point_transition_target_selector,
    "translated_point:source": _translated_point_selector("source"),
    "translated_point:target": _translated_point_selector("target"),
    "read_type:Coefficients": _read_type_selector("Coefficients"),
    "read_type:Expression": _read_type_selector("Expression"),
    "read_type:Expression|MinimumExpression": _read_type_union_selector(
        "Expression",
        "MinimumExpression",
    ),
    "read_type:Expression|MinimumExpression|Parabola": _read_type_union_selector(
        "Expression",
        "MinimumExpression",
        "Parabola",
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
    "parameter_symbol_from_reads": _parameter_symbol_from_reads_selector,
    "known_parameter_symbol_from_reads": (
        _known_parameter_symbol_from_reads_selector
    ),
    "known_parameter_value_from_reads": (
        _known_parameter_value_from_reads_selector
    ),
    "parameter_symbol_from_reads_or_expression": (
        _parameter_symbol_from_reads_or_expression_selector
    ),
    "parameter_constraint": _parameter_constraint_selector,
    "dynamic_symbol": _dynamic_symbol_selector,
    "dynamic_constraint": _dynamic_constraint_selector,
    "x_axis_known_point": _x_axis_known_point_selector,
    "read_type:MinimumExpression": _read_minimum_expression_selector,
    "weighted_path:condition": _weighted_path_condition_selector,
    "weighted_path:fixed_point": _weighted_path_selector("fixed_point"),
    "weighted_path:moving_point": _weighted_path_selector("moving_point"),
    "weighted_path:curve_point": _weighted_path_selector("curve_point"),
    "weighted_path:moving_point_ref": _weighted_path_identity_selector(
        "moving_point_ref"
    ),
    "weighted_path:linked_fixed_endpoint_ref": _weighted_path_identity_selector(
        "linked_fixed_endpoint_ref"
    ),
    "weighted_path:auxiliary_point_ref": _weighted_auxiliary_point_ref_selector,
    "weighted_path:auxiliary_point": _weighted_auxiliary_point_selector,
    "square_path:fixed_endpoint_1_ref": (
        _square_path_fixed_endpoint_ref_selector(1)
    ),
    "square_path:fixed_endpoint_2_ref": (
        _square_path_fixed_endpoint_ref_selector(2)
    ),
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
    "free_quadratic_parameter_if_read": _free_quadratic_parameter_if_read,
    "parameter_value_if_read": _parameter_value_if_read,
    "curve_point_if_read": _curve_point_if_read,
    "curve_points_if_parameterized": _curve_points_if_parameterized,
    "distance_parameter_value_if_read": _parameter_value_if_read,
    "intersection_parameter_value_if_read": _parameter_value_if_read,
}

def _point_output_handle(step: FunctionalCompileStepView, index: CanonicalRuntimeBindingIndex) -> str:
    """找出当前 step 要写回的点实体 handle。"""
    projected_object_refs = _unique_ordered(
        write.object_ref
        for write in index.projected_state_writes
        if write.step_id == step.step_id
        and write.runtime_type == "Point"
        and write.object_ref is not None
        and write.object_ref.startswith("point:")
    )
    if len(projected_object_refs) == 1:
        return projected_object_refs[0]

    target_handle = _point_handle_from_text(_compile_target_handle(step), index)
    if target_handle is not None:
        return target_handle
    if _compile_target_handle(step).startswith("point:"):
        return _compile_target_handle(step)
    if _compile_target_handle(step).startswith("answer:"):
        goal = index.question_goals.get(_compile_target_handle(step))
        if goal is not None and goal.value_type == "Point":
            parsed = ContextPath.parse(goal.target_path)
            return f"point:{parsed.scope_id}:{parsed.key}"

    created_points = [
        item.handle for item in _compile_created_entities(step)
        if item.entity_type == "point"
    ]
    if len(created_points) == 1:
        return created_points[0]

    for produced in _compile_return_outputs(step):
        if produced.handle.startswith("answer:"):
            goal = index.question_goals.get(produced.handle)
            if goal is not None and goal.value_type == "Point":
                parsed = ContextPath.parse(goal.target_path)
                return f"point:{parsed.scope_id}:{parsed.key}"
        if _produced_output_type(produced, index.handle_registry) == "Point":
            if _compile_capability_id(step) == "quadratic_y_axis_intercept_point":
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


def _point_path_from_step_reads(
    handle: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取点坐标路径，优先使用当前 step 显式读入的同名坐标 fact。"""
    resolved = EntityStateResolver().resolve(handle, "Point", step, index)
    if resolved is not None:
        return resolved
    return index.path_for(handle, expected_type="Point")


def _point_read_is_usable_as_point(
    handle: str,
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从 reads 中找已知系数 fact 所在 scope。"""
    scopes: list[str] = []
    for handle in _compile_input_handles(step):
        if index.fact_types.get(handle) == "symbol_value":
            scopes.append(_handle_scope(handle))
    unique = _unique_ordered(scopes)
    return unique[0] if unique else None

def _parameter_value_handle(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex | None = None,
) -> str | None:
    """Resolve one read ParameterValue without crossing Symbol identities."""
    candidates: list[str] = []
    for handle in _compile_input_handles(step):
        if index is not None:
            binding = index.bindings.get(handle)
            if (
                handle.startswith("fact:")
                and binding is not None
                and binding.value_type == "ParameterValue"
                and not index.is_structural_symbol_value_fact(handle)
            ):
                candidates.append(handle)
                continue
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
        candidates.append(handle)
    candidates = _unique_ordered(candidates)
    if index is None:
        return candidates[0] if candidates else None
    point_symbols = _read_point_free_symbols(step, index)
    if point_symbols:
        matching = [
            handle
            for handle in candidates
            if _parameter_value_symbol(
                handle,
                index,
                scope_id=step.scope_id,
            )
            in point_symbols
        ]
        return matching[0] if len(matching) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


def _read_point_free_symbols(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> set[Any]:
    result: set[Any] = set()
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is None or binding.value_type != "Point":
            continue
        try:
            point = index.context.read_path(
                binding.path,
                from_scope_id=step.scope_id,
                expected_type="Point",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        result.update(
            symbol
            for coordinate in point
            for symbol in getattr(coordinate, "free_symbols", ())
        )
    return result


def _parameter_value_symbol(
    handle: str,
    index: CanonicalRuntimeBindingIndex,
    *,
    scope_id: str,
) -> Any | None:
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
        return None
    binding = index.bindings.get(provenance.object_ref)
    if binding is None or binding.value_type != "Symbol":
        return None
    try:
        return index.context.read_path(
            binding.path,
            from_scope_id=scope_id,
            expected_type="Symbol",
        ).value
    except (KeyError, PermissionError, TypeError, ValueError):
        return None

def _path_for_first_type(
    index: CanonicalRuntimeBindingIndex,
    step: FunctionalCompileStepView,
    value_type: str,
) -> str:
    """从当前 step reads 中找第一个指定类型绑定。"""
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
    value_type: str,
) -> str:
    """从 step reads 或当前 scope 可见父级中寻找指定类型。

    这个 selector 用在需要严格遵守 question/subquestion 可见性的输入上，例如
    ``parameter_from_minimum_value.minimum_expression``。它不能像普通兜底一样扫描
    全局 bindings，否则会误读 sibling 小问的输出。
    """
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
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

def _curve_candidate_target_handle(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取候选点筛选 recipe 最终要写入的点实体。

    recipe 只知道“候选点落在曲线上并反求参数”，不知道候选点来自直角等腰、
    旋转还是其它几何构造；因此 target 统一从 step 的 answer/Point produced
    或 target 字段解析。
    """
    return _point_output_handle(step, index)

def _midpoint_roles(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """midpoint_point 必须绑定当前 step 明确读取的中点定义。"""
    midpoint_reads = [
        handle
        for handle in _compile_input_handles(step)
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str] | None:
    """从线段比例 fact 推断右侧参考线段两端点。"""
    fact = _length_condition_handle(step, index)
    if index.fact_types.get(fact) != "segment_length_relation":
        return None
    segment = _segment_name_from_length_relation(fact, side="right")
    return _segment_point_handles(segment, step, index, fact)

def _length_condition_handle(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """返回当前 step 读取的长度条件 handle。"""
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """返回当前 step 显式读取的曲线点。

    这里不能全局扫描所有 ``point_on_curve`` fact，否则第（Ⅰ）问会误读第（Ⅱ）
    问的 D 或第（Ⅲ）问的 M，造成 sibling/child scope 可见性错误。
    """
    point_names: list[str] = []
    for handle in _compile_input_handles(step):
        if index.fact_types.get(handle) not in _CURVE_MEMBERSHIP_FACT_TYPES:
            continue
        point_handle = _curve_membership_point_handle(handle, step, index)
        if point_handle is not None:
            point_names.append(_handle_name(point_handle))
            continue
        point_names.append(_semantic_name(handle).split("_on_", 1)[0])
    for handle in _compile_input_handles(step):
        if not handle.startswith("point:"):
            continue
        point_name = _handle_name(handle)
        if _visible_point_on_curve_fact_for_name(point_name, step, index) is not None:
            point_names.append(point_name)
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    curve_point_name: str,
) -> str:
    """由 target/answer 语义或显式 reads 确定目标点名。"""
    if _compile_target_handle(step).startswith("point:"):
        return _handle_name(_compile_target_handle(step))
    if _compile_target_handle(step).startswith("answer:"):
        answer_key = _answer_key_from_handle(_compile_target_handle(step))
        if answer_key:
            return answer_key
    for produced in _compile_return_outputs(step):
        if produced.handle.startswith("answer:"):
            answer_key = _answer_key_from_handle(produced.handle)
            if answer_key:
                return answer_key
    candidates = [
        name
        for name in (_point_state_read_name(handle, index) for handle in _compile_input_handles(step))
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    *,
    error_code: str,
) -> str:
    """从当前 step reads 中寻找指定点名的已计算 Point 状态。"""
    explicit_fact_matches: list[tuple[str, str]] = []
    entity_matches: list[tuple[str, str]] = []
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """查找当前 scope 可见的曲线成员关系题设 fact。"""
    prefix = f"{point_name}_on_"
    for handle in _curve_membership_fact_handles(index):
        point_handle = _curve_membership_point_handle(handle, step, index)
        if point_handle is not None:
            if _handle_name(point_handle) != point_name:
                continue
        elif not _semantic_name(handle).startswith(prefix):
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从当前 step reads 中寻找同名点坐标 fact。

    LLM 常写 ``reads=[D_on_parabola, D_coordinate]``。这时 ``point:D``
    仍可能是 PointRef，但 ``D_coordinate`` 已经是可直接作为曲线点约束的 Point。
    """
    for handle in _compile_input_handles(step):
        if not _is_point_coordinate_fact_handle(handle, index):
            continue
        if _semantic_name(handle).split("_", 1)[0] == point_name:
            return handle
    return None

def _visible_curve_point_handles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """返回当前 step scope 可见的曲线点。

    参数已经定值时，像南开 ii_1 这类子问可以复用父级 ii 中已经构造出的 M/N
    曲线点；但不能读取 sibling 或 child-only scope 的曲线点。
    """
    point_names: list[str] = []
    for handle in _curve_membership_fact_handles(index):
        fact_scope = index.handle_registry.handle_valid_scopes.get(handle)
        if fact_scope is None or not index.context.is_visible(step.scope_id, fact_scope):
            continue
        point_handle = _curve_membership_point_handle(handle, step, index)
        if point_handle is not None:
            point_names.append(_handle_name(point_handle))
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, Any]:
    """Consume the read-closed structured path-reduction role set."""
    roles = resolve_read_closed_path_reduction_inputs(step, index)
    second_track_payload = index.handle_registry.entity_payloads.get(
        roles.second_track,
        {},
    )
    second_track = tuple(second_track_payload.get("endpoints", ()))
    return {
        "relation": roles.binding_relation,
        "first_membership": roles.first_membership,
        "second_membership": roles.second_membership,
        "first_segment_start": roles.first_segment_start,
        "joint_point": roles.joint_point,
        "second_segment_end": roles.second_segment_end,
        "second_track": second_track,
        "second_moving": roles.second_moving_point,
    }

def _moving_membership_for_straightening(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """选择折线拉直时的动点所在条件。"""
    roles = _path_reduction_roles(step, index)
    return roles["second_membership"]

def _straightening_point_roles(
    step: FunctionalCompileStepView,
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
    line_1 = track[0]
    line_2 = track[1]
    return fixed_1, fixed_2, line_1, line_2

def _weighted_path_roles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str]:
    """Resolve weighted-path roles from typed endpoint terms.

    The display ``path`` remains useful for coefficients and term order, but it
    is not an object-identity source. When ``path_minimum_target.terms`` exists,
    its canonical point handles are authoritative. Legacy ProblemIR without
    terms is accepted through the semantic-name index only.
    """
    condition_handle = index.fact_handle_by_type("minimum_value", step=step)
    condition_path = index.path_for(condition_handle, expected_type="Condition")
    condition = index.context.read_path(
        condition_path,
        from_scope_id=step.scope_id,
        expected_type="Condition",
    ).value
    raw_path = str(condition.get("path", ""))
    point_names = tuple(
        sorted(
            {
                index.entity_semantic_name(handle)
                for handle in index.entity_handles("point", step=step)
            }
        )
    )
    try:
        display_terms = parse_legacy_path_expression(
            raw_path,
            point_names=point_names,
            resolve_point=lambda name: name,
        )
    except PathTermParseError as exc:
        raise StrategyDraftValidationError(
            f"weighted_path_expression_invalid: {exc.code}: {exc}"
        ) from exc
    if len(display_terms) != 2:
        raise StrategyDraftValidationError(
            f"weighted_path_requires_two_terms: path={raw_path!r}, count={len(display_terms)}"
        )

    target_handles = [
        handle
        for handle in index.handles_by_fact_type("path_minimum_target")
        if index._handle_binding_visible(handle, step.scope_id)
        and _normalized_path_text(
            str(index.fact_payload(handle).get("path", ""))
        )
        == _normalized_path_text(raw_path)
    ]
    if len(target_handles) != 1:
        raise StrategyDraftValidationError(
            "weighted_path_target_not_unique: "
            f"path={raw_path!r}, candidates={sorted(target_handles)}"
        )
    target = index.fact_payload(target_handles[0])
    structured = target.get("terms")
    if isinstance(structured, list):
        if len(structured) != len(display_terms):
            raise StrategyDraftValidationError(
                "weighted_path_term_count_drift: "
                f"display={len(display_terms)}, structured={len(structured)}"
            )
        endpoint_pairs: list[tuple[str, str]] = []
        for term_index, (raw_pair, display_term) in enumerate(
            zip(structured, display_terms)
        ):
            if (
                not isinstance(raw_pair, list)
                or len(raw_pair) != 2
                or not all(
                    isinstance(handle, str)
                    and handle.startswith("point:")
                    and handle in index.bindings
                    for handle in raw_pair
                )
            ):
                raise StrategyDraftValidationError(
                    "weighted_path_typed_term_invalid: "
                    f"index={term_index}, term={raw_pair!r}"
                )
            pair = (str(raw_pair[0]), str(raw_pair[1]))
            typed_names = {
                index.entity_semantic_name(pair[0]),
                index.entity_semantic_name(pair[1]),
            }
            display_names = {display_term.start, display_term.end}
            if typed_names != display_names:
                raise StrategyDraftValidationError(
                    "weighted_path_display_term_drift: "
                    f"index={term_index}, typed={sorted(typed_names)}, "
                    f"display={sorted(display_names)}"
                )
            endpoint_pairs.append(pair)
    else:
        endpoint_pairs = [
            (
                index.point_handle_by_name(term.start, step=step),
                index.point_handle_by_name(term.end, step=step),
            )
            for term in display_terms
        ]

    non_unit = [
        index
        for index, term in enumerate(display_terms)
        if not _is_unit_path_scale(term.scale)
    ]
    if len(non_unit) != 1:
        raise StrategyDraftValidationError(
            "weighted_path_weighted_term_not_unique: "
            f"path={raw_path!r}, scales={[term.scale for term in display_terms]}"
        )
    weighted_index = non_unit[0]
    unit_index = 1 - weighted_index
    weighted_pair = endpoint_pairs[weighted_index]
    unit_pair = endpoint_pairs[unit_index]
    moving = _common_endpoint_handle(weighted_pair, unit_pair)
    if moving is None:
        raise StrategyDraftValidationError(f"weighted_path_common_endpoint_not_found: {raw_path}")
    fixed = _other_endpoint_handle(unit_pair, moving)
    curve = _other_endpoint_handle(weighted_pair, moving)
    return fixed, moving, curve


def _normalized_path_text(value: str) -> str:
    return "".join(value.split())


def _is_unit_path_scale(value: str) -> bool:
    return _normalized_path_text(value) in {"1", "1.0", "(1)"}


def _common_endpoint_handle(
    first: tuple[str, str],
    second: tuple[str, str],
) -> str | None:
    shared = tuple(handle for handle in first if handle in second)
    return shared[0] if len(shared) == 1 else None


def _other_endpoint_handle(
    pair: tuple[str, str],
    endpoint: str,
) -> str:
    """Return the other typed endpoint without interpreting its name."""

    remaining = tuple(item for item in pair if item != endpoint)
    if len(remaining) != 1:
        raise StrategyDraftValidationError(
            "segment_other_endpoint_not_found: "
            f"pair={pair!r}, endpoint={endpoint!r}"
        )
    return remaining[0]


def _segments_from_path_text(raw_path: str) -> list[str]:
    """Compatibility parser for non-weighted legacy selectors."""

    return re.findall(r"[A-Z]{2}", raw_path)


def _common_endpoint(first: str, second: str) -> str | None:
    for name in first:
        if name in second:
            return name
    return None


def _other_endpoint(segment: str, endpoint: str) -> str:
    for name in segment:
        if name != endpoint:
            return name
    raise StrategyDraftValidationError(
        f"segment_other_endpoint_not_found: {segment}"
    )

def _auxiliary_point_handle_from_reads(
    step: FunctionalCompileStepView,
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
    for handle in _compile_input_handles(step):
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
    step: FunctionalCompileStepView,
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

def _created_point_handle(step: FunctionalCompileStepView) -> CreatedEntity | None:
    """返回 creates[] 中的第一个 point entity。"""
    for item in _compile_created_entities(step):
        if item.entity_type == "point":
            return item
    return None

def _fresh_auxiliary_point_handle(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """从 reads 中找第一个 PointRef handle。"""
    for handle in _compile_input_handles(step):
        binding = index.bindings.get(handle)
        if binding is not None and binding.value_type == "PointRef":
            return handle
    raise StrategyDraftValidationError(f"pointref_handle_not_found: {step.step_id}")


def _point_value_candidates_from_reads(
    step: FunctionalCompileStepView,
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
    for handle in _compile_input_handles(step):
        candidate = _point_value_candidate_for_handle(handle, step, index)
        if candidate is None or candidate.handle in seen:
            continue
        seen.add(candidate.handle)
        candidates.append(candidate)
    return candidates


def _point_value_candidate_for_handle(
    handle: str,
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
    candidates: list[_PointValueCandidate],
) -> tuple[str, str] | None:
    """Infer intended distance endpoints from structured handles."""
    point_names = _known_point_names_for_distance(step, index, candidates)
    for handle in _compile_input_handles(step):
        if handle.startswith("segment:"):
            match = _point_pair_from_text(_semantic_name(handle), point_names)
            if match is not None:
                return match
    structured_texts = [_compile_target_handle(step)]
    structured_texts.extend(produced.handle for produced in _compile_return_outputs(step))
    structured_texts.extend(
        produced.description for produced in _compile_return_outputs(step)
        if produced.description
    )
    for text in structured_texts:
        match = _point_pair_from_text(text, point_names)
        if match is not None:
            return match
    return None


def _known_point_names_for_distance(
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
        handle for handle in _compile_input_handles(step)
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """读取当前 step 明确引用的 AngleEquality fact。"""
    for handle in _compile_input_handles(step):
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
) -> tuple[tuple[str, str, str], tuple[str, str, str]]:
    """读取 AngleEquality fact 的左右两个三字母角。"""
    payload = index.handle_registry.fact_payloads.get(fact)
    if payload is None:
        binding = index.bindings.get(fact)
        if binding is not None and binding.value_type == "AngleEquality":
            try:
                runtime_value = index.context.read_path(
                    binding.path,
                    from_scope_id=_binding_scope(binding.path),
                    expected_type="AngleEquality",
                ).value
            except (KeyError, TypeError, ValueError):
                runtime_value = None
            if isinstance(runtime_value, dict):
                payload = runtime_value
    if payload is not None:
        left_points = payload.get("left_angle_points")
        right_points = payload.get("right_angle_points")
        if (
            isinstance(left_points, list)
            and isinstance(right_points, list)
            and len(left_points) == 3
            and len(right_points) == 3
            and all(isinstance(item, str) and item for item in left_points)
            and all(isinstance(item, str) and item for item in right_points)
        ):
            return (
                (left_points[0], left_points[1], left_points[2]),
                (right_points[0], right_points[1], right_points[2]),
            )
        left = payload.get("left_angle")
        right = payload.get("right_angle")
        if (
            isinstance(left, str)
            and isinstance(right, str)
            and re.fullmatch(r"[A-Za-z]{3}", left)
            and re.fullmatch(r"[A-Za-z]{3}", right)
        ):
            return tuple(left), tuple(right)
    name = _semantic_name(fact)
    match = re.fullmatch(
        r"angle_(?P<left>[A-Za-z]{3})_eq_(?P<right>[A-Za-z]{3})",
        name,
    )
    if match is None:
        raise StrategyDraftValidationError(f"invalid_angle_equality_fact_payload: {fact}")
    return tuple(match.group("left")), tuple(match.group("right"))


def _line_parabola_roles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """从 step reads 推断“直线两点 + 已知曲线交点 + 目标点”。"""
    target = _point_output_handle(step, index)
    line_points = [
        handle for handle in _compile_input_handles(step)
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
    known_candidates = set(_curve_point_handles_from_curve_fact_reads(step, index))
    known_candidates.update(_visible_curve_membership_line_points(line_points, step, index))
    known = None
    for handle in line_points:
        if handle in known_candidates:
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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """从 step reads 中的点坐标 fact 反推出对应 point handle。"""
    result: list[str] = []
    for handle in _compile_input_handles(step):
        if not _is_point_coordinate_fact_handle(handle, index):
            continue
        point_name = _semantic_name(handle).split("_coordinate", 1)[0]
        try:
            result.append(index.point_handle_by_name(point_name, step=step))
        except StrategyDraftValidationError:
            continue
    return result

def _curve_point_handles_from_curve_fact_reads(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """读取 step 显式读入的曲线成员关系 fact 对应点 handle。"""
    handles: list[str] = []
    for handle in _compile_input_handles(step):
        if index.fact_types.get(handle) not in _CURVE_MEMBERSHIP_FACT_TYPES:
            continue
        point_handle = _curve_membership_point_handle(handle, step, index)
        if point_handle is not None:
            handles.append(point_handle)
            continue
        point_name = _semantic_name(handle).split("_on_", 1)[0]
        try:
            handles.append(index.point_handle_by_name(point_name, step=step))
        except StrategyDraftValidationError:
            continue
    return _unique_ordered(handles)


def _visible_curve_membership_line_points(
    line_points: list[str],
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> list[str]:
    """从题设可见曲线成员关系中识别直线上的已知曲线点。"""
    handles: list[str] = []
    for point_handle in line_points:
        if _visible_curve_membership_fact_for_point(point_handle, step, index) is not None:
            handles.append(point_handle)
    return _unique_ordered(handles)


def _visible_curve_membership_fact_for_point(
    point_handle: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """查找当前 scope 可见且精确绑定到 ``point_handle`` 的曲线成员关系 fact。"""
    point_name = _handle_name(point_handle)
    for handle in _curve_membership_fact_handles(index):
        fact_scope = index.handle_registry.handle_valid_scopes.get(handle)
        if fact_scope is None or not index.context.is_visible(step.scope_id, fact_scope):
            continue
        fact_point = _curve_membership_point_handle(handle, step, index)
        if fact_point is not None:
            if fact_point == point_handle:
                return handle
            continue
        if _semantic_name(handle).startswith(f"{point_name}_on_"):
            return handle
    return None


def _curve_membership_fact_handles(index: CanonicalRuntimeBindingIndex) -> list[str]:
    """返回所有表示点在曲线上的 fact handle，保持稳定顺序。"""
    handles: list[str] = []
    for fact_type in sorted(_CURVE_MEMBERSHIP_FACT_TYPES):
        handles.extend(index.handles_by_fact_type(fact_type))
    return _unique_ordered(handles)


def _curve_membership_point_handle(
    fact_handle: str,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """从曲线成员关系 fact 的结构化 payload 读取 point handle。"""
    if index.fact_types.get(fact_handle) not in _CURVE_MEMBERSHIP_FACT_TYPES:
        return None
    payload = index.handle_registry.fact_payloads.get(fact_handle)
    if isinstance(payload, Mapping):
        point = payload.get("point")
        if isinstance(point, str) and point.startswith("point:"):
            return point
    point_name = _semantic_name(fact_handle).split("_on_", 1)[0]
    try:
        return index.point_handle_by_name(point_name, step=step)
    except StrategyDraftValidationError:
        return None


def _equal_length_ray_roles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> dict[str, str]:
    """Resolve debug Method wiring through the shared Macro role builder."""

    fact_types = (
        "point_on_ray",
        "point_on_segment",
        "equal_length_condition",
        "path_minimum_target",
    )
    facts = {
        fact_type: index.fact_handle_by_type(fact_type, step=step)
        for fact_type in fact_types
    }
    visible_scopes = set(index.handle_registry.ancestor_scopes(step.scope_id))
    point_handles = tuple(
        sorted(
            handle
            for handle in index.handle_registry.entity_handles
            if handle.startswith("point:")
            and index.handle_registry.handle_valid_scopes.get(handle)
            in visible_scopes
        )
    )
    by_name: dict[str, list[str]] = {}
    for handle in point_handles:
        payload = index.handle_registry.entity_payloads.get(handle, {})
        name = str(payload.get("name", "")).strip() or handle.rsplit(":", 1)[-1]
        by_name.setdefault(name, []).append(handle)
    point_names = {
        name: handles[0]
        for name, handles in by_name.items()
        if len(handles) == 1
    }
    try:
        candidates = build_equal_length_ray_role_candidates(
            ray_facts=((facts["point_on_ray"], index.fact_payload(facts["point_on_ray"])),),
            segment_facts=((facts["point_on_segment"], index.fact_payload(facts["point_on_segment"])),),
            equal_facts=((facts["equal_length_condition"], index.fact_payload(facts["equal_length_condition"])),),
            target_facts=((facts["path_minimum_target"], index.fact_payload(facts["path_minimum_target"])),),
            entity_payload=index.entity_payload,
            visible_point_handles=point_handles,
            resolve_point_name=lambda name: point_names[name],
        )
    except (EqualLengthRayRoleError, KeyError) as exc:
        raise StrategyDraftValidationError(
            f"planner.macro_contract_invalid: {exc}"
        ) from exc
    if len(candidates) != 1:
        raise StrategyDraftValidationError(
            "planner.macro_contract_invalid: debug equal-length binding "
            f"requires one role candidate, got {len(candidates)}"
        )
    return {
        **candidates[0].roles.to_payload(),
        "target": _point_output_handle(step, index),
    }

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
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str, str, str]:
    """推断 line_intersection_point 的两条线和目标点。"""
    explicit = _explicit_line_intersection_roles(step, index)
    if explicit is not None:
        return explicit
    structured = _straightening_candidate_intersection_roles(step, index)
    if structured is not None:
        return structured
    track = _intersection_track_from_membership_read(step, index)
    if track is None:
        roles = _path_reduction_roles(step, index)
        track = roles["second_track"]
    line1_p1, line1_p2 = track
    aux = None
    for handle in _compile_input_handles(step):
        if _is_auxiliary_point_handle(handle, index):
            if not index._handle_binding_visible(handle, step.scope_id):
                raise StrategyDraftValidationError(
                    "intersection_auxiliary_point_not_visible: "
                    f"handle={handle}, scope_id={step.scope_id}, step_id={step.step_id}"
                )
            aux = handle
            break
    if aux is None:
        aux = _visible_intersection_auxiliary_point(step, index)
    midpoint_fact = index.fact_handle_by_type("midpoint_definition", step=step)
    midpoint_name = _semantic_name(midpoint_fact).split("_midpoint_of_", 1)[0]
    line2_p2 = index.point_handle_by_name(midpoint_name, step=step)
    target_handle = _point_output_handle(step, index)
    index.ensure_point_declaration(target_handle, definition="line_intersection")
    if aux is None:
        raise StrategyDraftValidationError(f"intersection_auxiliary_point_not_found: {step.step_id}")
    return line1_p1, line1_p2, aux, line2_p2, target_handle


def _intersection_track_from_membership_read(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str] | None:
    """Resolve the target point's movement track from an explicit read."""

    target = _point_output_handle(step, index)
    memberships = tuple(
        handle
        for handle in _compile_input_handles(step)
        if index.fact_types.get(handle) == "segment_membership"
        and index.handle_registry.fact_payloads.get(handle, {}).get("point")
        == target
    )
    if not memberships:
        return None
    if len(memberships) != 1:
        raise StrategyDraftValidationError(
            "intersection_moving_membership_ambiguous: "
            f"step={step.step_id}, candidates={list(memberships)}"
        )
    segment = index.handle_registry.fact_payloads[memberships[0]].get(
        "segment"
    )
    payload = index.handle_registry.entity_payloads.get(str(segment), {})
    endpoints = payload.get("endpoints")
    if not (
        isinstance(endpoints, list)
        and len(endpoints) == 2
        and all(
            isinstance(item, str) and item.startswith("point:")
            for item in endpoints
        )
    ):
        raise StrategyDraftValidationError(
            "intersection_moving_track_invalid: "
            f"membership={memberships[0]}, segment={segment}"
        )
    return endpoints[0], endpoints[1]


def _straightening_candidate_intersection_roles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str, str, str] | None:
    """Resolve the intersection lines from one read-closed candidate state."""

    candidate_reads = tuple(
        handle
        for handle in _compile_input_handles(step)
        if (
            (binding := index.bindings.get(handle)) is not None
            and binding.value_type == "StraighteningCandidate"
        )
    )
    if not candidate_reads:
        return None
    if len(candidate_reads) != 1:
        raise StrategyDraftValidationError(
            "intersection_straightening_candidate_ambiguous: "
            f"step={step.step_id}, candidates={list(candidate_reads)}"
        )
    candidate_path = index.path_for(
        candidate_reads[0],
        expected_type="StraighteningCandidate",
    )
    candidate = index.context.read_path(
        candidate_path,
        from_scope_id=step.scope_id,
        expected_type="StraighteningCandidate",
    ).value
    if not isinstance(candidate, Mapping):
        return None
    locus_refs = candidate.get("moving_locus_endpoint_refs")
    fixed_ref = candidate.get("other_fixed_point_ref")
    auxiliary_name = candidate.get("auxiliary_point_name")
    if not (
        isinstance(locus_refs, list)
        and len(locus_refs) == 2
        and all(
            isinstance(item, str) and item.startswith("point:")
            for item in locus_refs
        )
        and isinstance(fixed_ref, str)
        and fixed_ref.startswith("point:")
        and isinstance(auxiliary_name, str)
        and auxiliary_name
    ):
        return None
    auxiliary = _point_read_by_name(
        auxiliary_name,
        step=step,
        index=index,
    )
    target = _point_output_handle(step, index)
    index.ensure_point_declaration(target, definition="line_intersection")
    for handle in (*locus_refs, fixed_ref, auxiliary):
        _point_path_from_step_reads(handle, step, index)
    return locus_refs[0], locus_refs[1], auxiliary, fixed_ref, target


def _point_read_by_name(
    point_name: str,
    *,
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    matches = tuple(
        candidate.handle
        for handle in _compile_input_handles(step)
        if (
            (candidate := _point_value_candidate_for_handle(handle, step, index))
            is not None
            and candidate.point_name == point_name
        )
    )
    unique = tuple(dict.fromkeys(matches))
    if len(unique) != 1:
        raise StrategyDraftValidationError(
            "intersection_auxiliary_point_"
            + ("not_found" if not unique else "ambiguous")
            + f": step={step.step_id}, point={point_name}, candidates={list(unique)}"
        )
    return unique[0]


def _explicit_line_intersection_roles(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> tuple[str, str, str, str, str] | None:
    """Use four explicitly read Point states before structural fallback.

    FunctionalPlan preserves argument order when projecting resolved reads. A
    call that supplies four point states therefore already contains complete
    line-role evidence; requiring an unrelated segment relation would discard
    that evidence. Ambiguous cardinality deliberately falls back to the legacy
    structural resolver instead of guessing.
    """
    target = _point_output_handle(step, index)
    target_name = _handle_name(target)
    candidates = [
        candidate.handle
        for candidate in _point_value_candidates_from_reads(step, index)
        if candidate.point_name != target_name
    ]
    if len(candidates) != 4:
        return None
    index.ensure_point_declaration(target, definition="line_intersection")
    return (*candidates, target)


def _visible_intersection_auxiliary_point(
    step: FunctionalCompileStepView,
    index: CanonicalRuntimeBindingIndex,
) -> str | None:
    """Select a visible auxiliary point for line intersection fallback.

    Global binding order is not semantic: sibling subquestions may both create
    ``Aux`` points.  When the LLM does not explicitly read the auxiliary point,
    fallback selection must stay within the current step's visible scope chain.
    """
    candidates = [
        handle
        for handle in index.bindings
        if _is_auxiliary_point_handle(handle, index)
        and index._handle_binding_visible(handle, step.scope_id)
    ]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda handle: (
            index._scope_distance(
                step.scope_id,
                _binding_scope(index.binding_for(handle).path),
            ),
            handle,
        ),
    )
    best_distance = index._scope_distance(
        step.scope_id,
        _binding_scope(index.binding_for(ranked[0]).path),
    )
    same_rank = [
        handle
        for handle in ranked
        if index._scope_distance(
            step.scope_id,
            _binding_scope(index.binding_for(handle).path),
        )
        == best_distance
    ]
    if len(same_rank) > 1:
        raise StrategyDraftValidationError(
            "intersection_auxiliary_point_ambiguous: "
            f"step_id={step.step_id}, scope_id={step.scope_id}, "
            f"handles={','.join(same_rank)}"
        )
    return ranked[0]


def _answer_scope_from_step(step: FunctionalCompileStepView) -> str:
    """从 FunctionalCompileStepView 的 target/produces 中提取 answer 所属 scope。"""
    handles = [_compile_target_handle(step), *(item.handle for item in _compile_return_outputs(step))]
    for handle in handles:
        if handle.startswith("answer:"):
            goal_id = handle.removeprefix("answer:")
            return goal_id.split(".", 1)[0]
    return step.scope_id
