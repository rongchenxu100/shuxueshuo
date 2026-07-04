"""Strategy Planner 的统一 Entity State 补位层。

LLM 的 StepIntent 可以只读取实体 handle，例如 ``point:problem:B`` 或
``function:problem:parabola``。当 selected method 需要更具体的 runtime 类型时，
本模块从题设 fact、前序 produced fact 和 answer binding 中寻找唯一可见状态。
"""

from __future__ import annotations

import re
from collections.abc import Callable

from shuxueshuo_server.solver.runtime.binding_index import CanonicalRuntimeBindingIndex
from shuxueshuo_server.solver.runtime.handle_registry import (
    _handle_name,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.models import ContextPath, runtime_type_matches
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StrategyDraftValidationError,
)


class EntityStateResolver:
    """把 ``entity handle + required runtime type`` 解析成唯一可见 runtime path。"""

    def resolve(
        self,
        handle: str,
        required_type: str,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
    ) -> str | None:
        """返回补位后的 path；没有候选返回 None，多候选抛结构化错误。"""
        direct = index.bindings.get(handle)
        if direct is not None and _binding_visible(direct.path, step, index):
            if runtime_type_matches(required_type, direct.value_type):
                return direct.path

        if handle.startswith("point:") and required_type == "Point":
            return self._unique_visible_path(
                handle,
                required_type,
                step,
                index,
                predicate=lambda candidate: _is_point_coordinate_for(
                    candidate,
                    _handle_name(handle),
                    index,
                ),
                reason="unique_visible_entity_state",
                missing_ok=True,
            )

        if handle.startswith("function:") and required_type == "Parabola":
            return self._unique_visible_path(
                handle,
                required_type,
                step,
                index,
                predicate=lambda candidate: _is_parabola_state(candidate, index),
                reason="unique_visible_entity_state",
                missing_ok=True,
            )

        if handle.startswith("symbol:") and required_type == "ParameterValue":
            return self._unique_visible_path(
                handle,
                required_type,
                step,
                index,
                predicate=lambda candidate: _is_symbol_value_for(
                    candidate,
                    _handle_name(handle),
                    index,
                ),
                reason="unique_visible_entity_state",
                missing_ok=True,
            )

        if handle.startswith("segment:") and required_type == "Condition":
            return self._unique_visible_path(
                handle,
                required_type,
                step,
                index,
                predicate=lambda candidate: _is_segment_condition_for(
                    candidate,
                    handle,
                    index,
                ),
                reason="unique_visible_entity_state",
                missing_ok=True,
            )

        return None

    def can_resolve(
        self,
        handle: str,
        required_type: str,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
    ) -> bool:
        """判断补位是否可用；歧义保持为错误，不静默降级。"""
        return self.resolve(handle, required_type, step, index) is not None

    def _unique_visible_path(
        self,
        source_handle: str,
        required_type: str,
        step: StepIntent,
        index: CanonicalRuntimeBindingIndex,
        *,
        predicate: Callable[[str], bool],
        reason: str,
        missing_ok: bool,
    ) -> str | None:
        """查找唯一可见候选。"""
        matches: list[tuple[str, str]] = []
        explicit_reads = set(step.reads)
        for handle, binding in sorted(index.bindings.items()):
            if not runtime_type_matches(required_type, binding.value_type):
                continue
            if not _binding_visible(binding.path, step, index):
                continue
            if not predicate(handle):
                continue
            matches.append((handle, binding.path))

        if not matches:
            return None if missing_ok else _raise_missing(source_handle, required_type)

        explicit = [item for item in matches if item[0] in explicit_reads]
        if len(explicit) == 1:
            index.record_applied_fill(
                step=step,
                input_handle=source_handle,
                required_type=required_type,
                resolved_handle=explicit[0][0],
                reason=reason,
            )
            return explicit[0][1]
        if len(explicit) > 1:
            _raise_ambiguous(source_handle, required_type, [handle for handle, _path in explicit])

        if len(matches) == 1:
            index.record_applied_fill(
                step=step,
                input_handle=source_handle,
                required_type=required_type,
                resolved_handle=matches[0][0],
                reason=reason,
            )
            return matches[0][1]
        _raise_ambiguous(source_handle, required_type, [handle for handle, _path in matches])


def _binding_visible(
    raw_path: str,
    step: StepIntent,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 binding path 对当前 step 是否可见。"""
    try:
        scope_id = ContextPath.parse(raw_path).scope_id
    except ValueError:
        return False
    return index.context.is_visible(step.scope_id, scope_id)


def _is_point_coordinate_for(
    candidate: str,
    point_name: str,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 candidate 是否是指定点名的坐标 fact。"""
    if index.fact_types.get(candidate) == "point_coordinate":
        return _point_name_from_coordinate_state(_semantic_name(candidate)) == point_name
    if not candidate.startswith("fact:"):
        return False
    return bool(re.fullmatch(
        rf"{re.escape(point_name)}_"
        r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate|point)"
        r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
        _semantic_name(candidate),
        flags=re.IGNORECASE,
    ))


def _point_name_from_coordinate_state(semantic_name: str) -> str | None:
    """从 ``E_coordinate`` / ``E_parametric_coordinate`` 这类状态 fact 读取点名。"""
    match = re.fullmatch(
        r"(?P<point>[A-Za-z][A-Za-z0-9]*)_"
        r"(?:(?:param|parametric|parameterized)_(?:coord|coordinate|point)"
        r"|(?:coord|coordinate))(?:_[A-Za-z0-9_]+)?",
        semantic_name,
        flags=re.IGNORECASE,
    )
    if match is not None:
        return match.group("point")
    if "_coordinate" in semantic_name:
        return semantic_name.split("_coordinate", 1)[0]
    return None


def _is_parabola_state(
    candidate: str,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 candidate 是否是已求出的抛物线状态。"""
    if candidate.startswith("answer:"):
        return index.answer_value_types.get(candidate) == "Parabola"
    if candidate.startswith("fact:"):
        name = _semantic_name(candidate)
        return name in {"parabola", "parabola_expr", "parabola_expression"} or (
            "parabola" in name and "coefficient" not in name
        )
    return False


def _is_symbol_value_for(
    candidate: str,
    symbol_name: str,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 candidate 是否是指定符号的参数值。"""
    if candidate.startswith("answer:"):
        goal = index.question_goals.get(candidate)
        return goal is not None and goal.value_type == "ParameterValue" and goal.answer_key == symbol_name
    if not candidate.startswith("fact:"):
        return False
    name = _semantic_name(candidate)
    return name in {f"{symbol_name}_value", f"parameter_{symbol_name}_value"}


def _is_segment_condition_for(
    candidate: str,
    segment_handle: str,
    index: CanonicalRuntimeBindingIndex,
) -> bool:
    """判断 candidate 是否是某线段相关条件。"""
    if not candidate.startswith("fact:"):
        return False
    payload = index.handle_registry.fact_payloads.get(candidate, {})
    segment_name = _handle_name(segment_handle)
    segment_values = {
        value
        for value in payload.values()
        if isinstance(value, str) and value.startswith("segment:")
    }
    if segment_handle in segment_values:
        return True
    name = _semantic_name(candidate)
    return segment_name in name


def _raise_missing(source_handle: str, required_type: str) -> None:
    """抛出缺失补位错误。"""
    raise StrategyDraftValidationError(
        f"missing_required_runtime_fact: entity={source_handle}, type={required_type}"
    )


def _raise_ambiguous(source_handle: str, required_type: str, candidates: list[str]) -> None:
    """抛出多候选补位错误。"""
    raise StrategyDraftValidationError(
        "ambiguous_runtime_fact: "
        f"entity={source_handle}, type={required_type}, candidates={','.join(candidates)}"
    )
