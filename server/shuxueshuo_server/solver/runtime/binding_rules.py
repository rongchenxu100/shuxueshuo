"""Typed Method binding rules used by the derived execution IR."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from shuxueshuo_server.solver.contracts import (
    MethodInputBindingSpec,
    OrdinalZeroTemplateDerivationSpec,
)
from shuxueshuo_server.solver.family.models import MethodBindingRuleSpec, SolverFamilySpec
from shuxueshuo_server.solver.runtime.condition_roles import (
    resolve_read_closed_right_angle_method_roles,
)
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.function_specs import FunctionAdapterRegistry
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
        ``MethodBindingRuleSpec``，runtime只消费已经finalize的typed input。
        新增或调整family的method slot映射时，优先改family spec，而不是改编译器主流程。
    """

    def __init__(
        self,
        rules: tuple[MethodBindingRuleSpec, ...] = (),
    ) -> None:
        self.rules = {rule.method_id: rule for rule in rules}
        self.function_adapters = FunctionAdapterRegistry()
        self.function_binding_events: list[FunctionalFunctionBindingEvent] = []

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
        return inputs

    def rule_for(self, method_id: str) -> MethodBindingRuleSpec | None:
        """返回 method 的 binding rule；不存在时返回 None。"""
        return self.rules.get(method_id)

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

def _created_point_handle(step: FunctionalCompileStepView) -> CreatedEntity | None:
    """返回 creates[] 中的第一个 point entity。"""
    for item in _compile_created_entities(step):
        if item.entity_type == "point":
            return item
    return None

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
    track = _intersection_track_from_membership_read(step, index)
    if track is None:
        raise StrategyDraftValidationError(
            "line_intersection_roles_missing: "
            f"step={step.step_id}, provide explicit line endpoints or one "
            "target-point membership"
        )
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
