"""StepIntent capability 解析与输出类型推断。

本模块只负责判断某个 StepIntent 可能由哪些 recipe/method 能力承接，
不生成 MethodInvocation，也不写 RuntimeContext。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutableCapabilitySpec,
    ExecutablePlanResolutionReport,
    ProducedFact,
    StepIntent,
    StepIntentDraft,
    StepIntentResolutionCandidate,
    StepIntentResolutionStepReport,
)

class StepIntentCandidateResolver:
    """把 StepIntent 解析成 recipe/method 可执行候选。

    这层仍然不执行 method，也不生成 MethodInvocation。它只做“可执行性预检”：
    某一步产出的 fact/answer 类型是否能被某个 recipe 或 method 承接。真正的
    参数绑定、并发试执行和验算会在后续 TrialExecutor 中完成。
    """

    def resolve(
        self,
        draft: StepIntentDraft,
        *,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
    ) -> ExecutablePlanResolutionReport:
        """返回每个 StepIntent 的候选解析报告。"""
        capabilities = build_executable_capabilities(family_spec, method_specs)
        by_id = {capability.capability_id: capability for capability in capabilities}
        step_reports: list[StepIntentResolutionStepReport] = []
        errors: list[str] = []

        for step in draft.steps:
            report = _resolve_step_intent_candidates(
                step,
                capabilities=capabilities,
                capabilities_by_id=by_id,
                handle_registry=handle_registry,
            )
            step_reports.append(report)
            errors.extend(
                f"{report.step_id}:{error}"
                for error in report.errors
            )

        return ExecutablePlanResolutionReport(
            ok=not errors,
            step_reports=tuple(step_reports),
            errors=tuple(errors),
            capability_catalog=capabilities,
        )

def build_executable_capabilities(
    family_spec: SolverFamilySpec,
    method_specs: MethodSpecRegistry,
) -> tuple[ExecutableCapabilitySpec, ...]:
    """从 FamilySpec recipe 与 MethodSpec 构建统一能力菜单。

    recipe 优先使用显式 output override，因为 recipe 的产物往往是多个 method 串联后
    的教学结论，不等于内部 method outputs 的简单并集。
    """
    capabilities: list[ExecutableCapabilitySpec] = []
    for recipe in family_spec.step_recipes:
        output_types = _RECIPE_OUTPUT_TYPE_OVERRIDES.get(recipe.recipe_id)
        if output_types is None:
            output_types = _method_output_union(recipe.method_ids, method_specs)
        capabilities.append(
            ExecutableCapabilitySpec(
                capability_id=recipe.recipe_id,
                kind="recipe",
                goal_type=recipe.goal_type,
                method_ids=recipe.method_ids,
                output_types=tuple(output_types),
                preferred=recipe.priority == "preferred",
                title=recipe.title,
                description=recipe.description,
            )
        )
    for method_id in family_spec.method_ids:
        try:
            spec = method_specs.require(method_id)
        except KeyError:
            continue
        capabilities.append(
            ExecutableCapabilitySpec(
                capability_id=spec.method_id,
                kind="method",
                goal_type=spec.solves[0],
                method_ids=(spec.method_id,),
                output_types=tuple(_unique_ordered(spec.outputs.values())),
                preferred=False,
                title=spec.title,
                description=_method_capability_summary(spec),
            )
        )
    return tuple(capabilities)

def _resolve_step_intent_candidates(
    step: StepIntent,
    *,
    capabilities: tuple[ExecutableCapabilitySpec, ...],
    capabilities_by_id: dict[str, ExecutableCapabilitySpec],
    handle_registry: CanonicalHandleRegistry,
) -> StepIntentResolutionStepReport:
    """解析单个 step 的候选能力。"""
    produced_inferences: list[_OutputTypeInference] = []
    errors: list[str] = []
    warnings: list[str] = []
    for produced in step.produces:
        inference = _produced_output_type_inference(produced, handle_registry)
        if inference.output_type is None:
            errors.append(
                "unsupported_produced_handle_type:"
                f"handle={produced.handle}, description={produced.description}"
            )
            continue
        produced_inferences.append(inference)

    produced_types = tuple(inference.output_type for inference in produced_inferences)
    produced_types, correction_warnings = _maybe_correct_output_types_from_hint(
        step,
        produced_inferences=tuple(produced_inferences),
        capabilities_by_id=capabilities_by_id,
    )
    warnings.extend(correction_warnings)

    candidate_caps = _candidate_capabilities_for_step(
        step,
        produced_types=produced_types,
        capabilities=capabilities,
        capabilities_by_id=capabilities_by_id,
        handle_registry=handle_registry,
    )
    candidates = tuple(
        _evaluate_step_candidate(
            step,
            capability,
            produced_types=produced_types,
            handle_registry=handle_registry,
        )
        for capability in candidate_caps
    )
    sorted_candidates = tuple(
        sorted(candidates, key=lambda item: (-item.score, item.capability_id))
    )
    selected = next(
        (candidate for candidate in sorted_candidates if candidate.ok),
        None,
    )
    if step.recipe_hint and step.recipe_hint not in capabilities_by_id:
        warnings.append(f"unknown_recipe_hint:{step.recipe_hint}")
    if not selected:
        if produced_types:
            candidate_error_text = _candidate_error_summary(sorted_candidates)
            errors.append(
                "no_executable_candidate:"
                f"produced_types={sorted(set(produced_types))}, "
                f"recipe_hint={step.recipe_hint}"
                + (f", candidate_errors={candidate_error_text}" if candidate_error_text else "")
            )
        else:
            errors.append(
                "no_typed_outputs_for_step:"
                "produces must map to known method/recipe output types"
            )
    if selected is not None:
        warnings.extend(
            _unused_child_read_scope_warnings(
                step,
                capabilities_by_id[selected.capability_id],
                handle_registry,
            )
        )
    return StepIntentResolutionStepReport(
        step_id=step.step_id,
        scope_id=step.scope_id,
        recipe_hint=step.recipe_hint,
        produced_types=tuple(_unique_ordered(produced_types)),
        selected_capability_id=selected.capability_id if selected else None,
        candidates=sorted_candidates,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _candidate_error_summary(
    candidates: tuple[StepIntentResolutionCandidate, ...],
) -> str:
    """把候选内部失败原因压成适合 previous_attempts 的短文本。"""
    pieces: list[str] = []
    for candidate in candidates[:3]:
        if not candidate.errors:
            continue
        pieces.append(f"{candidate.capability_id}:{'|'.join(candidate.errors)}")
    return "; ".join(pieces)


def _candidate_capabilities_for_step(
    step: StepIntent,
    *,
    produced_types: tuple[str, ...],
    capabilities: tuple[ExecutableCapabilitySpec, ...],
    capabilities_by_id: dict[str, ExecutableCapabilitySpec],
    handle_registry: CanonicalHandleRegistry,
) -> tuple[ExecutableCapabilitySpec, ...]:
    """按 hint、goal_type 和 output type 找候选。"""
    result: list[ExecutableCapabilitySpec] = []
    seen: set[str] = set()

    def add(capability: ExecutableCapabilitySpec) -> None:
        if capability.capability_id not in seen:
            seen.add(capability.capability_id)
            result.append(capability)

    if step.recipe_hint and step.recipe_hint in capabilities_by_id:
        hinted = capabilities_by_id[step.recipe_hint]
        add(hinted)
        # recipe_hint 是 LLM 给出的强执行意图。若它与高置信度产物类型冲突，
        # 不再绕到其他 method “救场”，否则会掩盖 step 本身边界错误。
        if produced_types and not _capability_covers_output_types(hinted, produced_types):
            return tuple(result)

    for capability in capabilities:
        if capability.goal_type == step.goal_type:
            add(capability)

    if set(produced_types) == {"ParameterValue"} and not step.recipe_hint:
        signature_capability = _parameter_capability_from_reads(
            step,
            capabilities_by_id,
            handle_registry,
        )
        if signature_capability is not None:
            add(signature_capability)

    for capability in capabilities:
        if (
            produced_types
            and _output_type_search_allowed(step, produced_types)
            and _capability_covers_output_types(capability, produced_types)
        ):
            add(capability)

    return tuple(result)


def _output_type_search_allowed(
    step: StepIntent,
    produced_types: tuple[str, ...],
) -> bool:
    """控制“只按产物类型搜索”的范围。

    ``ParameterValue`` 太泛：系数 b、参数 m、动态点参数都可能是 ParameterValue。
    没有明确 recipe_hint 时，单靠这个类型很容易把 utility 系数 step 误接到
    ``parameter_from_segment_length`` 等专用 method 上，因此首版不做这类宽搜。
    """
    if set(produced_types) == {"ParameterValue"} and not step.recipe_hint:
        return False
    return True


def _evaluate_step_candidate(
    step: StepIntent,
    capability: ExecutableCapabilitySpec,
    *,
    produced_types: tuple[str, ...],
    handle_registry: CanonicalHandleRegistry,
) -> StepIntentResolutionCandidate:
    """判断某个候选是否覆盖该 step 的产物边界。"""
    errors: list[str] = []
    matched_by: list[str] = []
    if step.recipe_hint == capability.capability_id:
        matched_by.append("recipe_hint")
    if step.goal_type == capability.goal_type:
        matched_by.append("goal_type")
    if produced_types and _capability_covers_output_types(capability, produced_types):
        matched_by.append("output_types")
    for output_type in produced_types:
        if not _type_covered_by_capability(output_type, capability.output_types):
            errors.append(
                "output_type_not_supported:"
                f"{output_type} not in {list(capability.output_types)}"
            )
    if step.creates and not _capability_allows_creates(capability):
        errors.append(
            "capability_does_not_create_entities:"
            f"creates={[item.handle for item in step.creates]}"
        )
    errors.extend(
        _valid_scope_errors_for_candidate(
            step,
            capability,
            handle_registry,
        )
    )
    score = 0
    if "recipe_hint" in matched_by:
        score += 100
    if "goal_type" in matched_by:
        score += 30
    if "output_types" in matched_by:
        score += 40
    if capability.preferred:
        score += 10
    if capability.kind == "recipe":
        score += 3
    return StepIntentResolutionCandidate(
        capability_id=capability.capability_id,
        kind=capability.kind,
        score=score,
        matched_by=tuple(matched_by),
        output_types=capability.output_types,
        errors=tuple(errors),
    )


def _parameter_capability_from_reads(
    step: StepIntent,
    capabilities_by_id: dict[str, ExecutableCapabilitySpec],
    handle_registry: CanonicalHandleRegistry,
) -> ExecutableCapabilitySpec | None:
    """用 reads 语义为无 hint 的参数求解 step 选择专用 method。

    ``ParameterValue`` 本身太宽，不能直接按 output type 搜索。但长度条件和
    最小值条件在 canonical fact 中很清楚，可以确定性地选出对应参数 method。
    """
    if _reads_length_condition(step, handle_registry):
        return capabilities_by_id.get("parameter_from_segment_length")
    if (
        _reads_minimum_expression(step, handle_registry)
        and _reads_given_minimum_value(step, handle_registry)
    ):
        return capabilities_by_id.get("parameter_from_minimum_value")
    return None


def _valid_scope_errors_for_candidate(
    step: StepIntent,
    capability: ExecutableCapabilitySpec,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """只对 selected capability 实际会使用的 child-only reads 做 valid_scope 检查。"""
    errors: list[str] = []
    for produced in step.produces:
        visible_from_output_scope = set(handle_registry.ancestor_scopes(produced.valid_scope))
        for read_handle in step.reads:
            read_scope = handle_registry.handle_valid_scopes.get(read_handle)
            if read_scope is None or read_scope in visible_from_output_scope:
                continue
            if not _capability_uses_read(capability, read_handle, handle_registry):
                continue
            errors.append(
                "invalid_valid_scope:"
                f"produced={produced.handle}, valid_scope={produced.valid_scope}, "
                f"read_handle={read_handle}, read_valid_scope={read_scope}"
            )
    return tuple(errors)


def _unused_child_read_scope_warnings(
    step: StepIntent,
    capability: ExecutableCapabilitySpec,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    """返回 child-only 但 selected capability 不会用到的 reads warning。"""
    warnings: list[str] = []
    for produced in step.produces:
        visible_from_output_scope = set(handle_registry.ancestor_scopes(produced.valid_scope))
        for read_handle in step.reads:
            read_scope = handle_registry.handle_valid_scopes.get(read_handle)
            if read_scope is None or read_scope in visible_from_output_scope:
                continue
            if _capability_uses_read(capability, read_handle, handle_registry):
                continue
            warnings.append(
                "unused_child_read_ignored_for_valid_scope:"
                f"produced={produced.handle}, valid_scope={produced.valid_scope}, "
                f"read_handle={read_handle}, read_valid_scope={read_scope}, "
                f"capability={capability.capability_id}"
            )
    return tuple(_unique_ordered(warnings))


def _capability_uses_read(
    capability: ExecutableCapabilitySpec,
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """粗略判断某 capability 是否会使用某个 read handle。

    这个判断只服务 valid_scope 安全边界：宁可把“会用”判宽，也不能把真实依赖
    判成无害多读。少数 method（如求对称轴）可以安全地窄化到必要事实。
    """
    capability_id = capability.capability_id
    text = _read_semantic_text(handle, handle_registry)
    if capability_id == "quadratic_axis_from_relation":
        return "coefficient_relation" in text or handle.startswith("point:")
    if capability_id == "parameter_from_segment_length":
        return (
            "length" in text
            or "coordinate" in text
            or handle.startswith("point:")
            or "m_gt" in text
        )
    if capability_id == "parameter_from_minimum_value":
        return (
            _read_is_minimum_expression(handle, handle_registry)
            or _read_is_given_minimum_value(handle, handle_registry)
            or "m_gt" in text
            or "parameter" in text
        )
    return True


def _reads_length_condition(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否读取了长度/长度平方条件。"""
    return any(_read_is_length_condition(handle, handle_registry) for handle in step.reads)


def _reads_minimum_expression(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否读取了已推导出的最小值表达式。"""
    return any(_read_is_minimum_expression(handle, handle_registry) for handle in step.reads)


def _reads_given_minimum_value(
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """判断 step 是否读取了题设给定最小值。"""
    return any(_read_is_given_minimum_value(handle, handle_registry) for handle in step.reads)


def _read_is_length_condition(
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """按 fact type 和 handle 语义识别长度条件。"""
    fact_type = handle_registry.fact_types.get(handle, "")
    text = _read_semantic_text(handle, handle_registry)
    return fact_type in {"length", "length_squared"} or "length" in text


def _read_is_minimum_expression(
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """识别可作为参数方程输入的公共最小值表达式。"""
    fact_type = handle_registry.fact_types.get(handle, "")
    if fact_type in {"minimum_expression", "minimum_value_expression"}:
        return True
    name = _semantic_name(handle).lower()
    if "given" in name:
        return False
    return _output_type_from_text(handle, "") == "MinimumExpression" or (
        "minimum" in name and ("expr" in name or "expression" in name)
    )


def _read_is_given_minimum_value(
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    """识别题设给定的最小值事实。"""
    fact_type = handle_registry.fact_types.get(handle, "")
    name = _semantic_name(handle).lower()
    return fact_type == "minimum_value" or (
        "minimum" in name and ("given" in name or "value_given" in name)
    )


def _read_semantic_text(
    handle: str,
    handle_registry: CanonicalHandleRegistry,
) -> str:
    """把 handle、semantic name 和 fact type 合成小写匹配文本。"""
    return "\n".join((
        handle,
        _semantic_name(handle),
        handle_registry.fact_types.get(handle, ""),
    )).lower()


def _capability_covers_output_types(
    capability: ExecutableCapabilitySpec,
    produced_types: tuple[str, ...],
) -> bool:
    """判断 capability 是否能覆盖所有产物类型。"""
    return all(
        _type_covered_by_capability(output_type, capability.output_types)
        for output_type in produced_types
    )


def _type_covered_by_capability(
    output_type: str,
    capability_output_types: tuple[str, ...],
) -> bool:
    """语义输出类型兼容判断。"""
    if output_type in capability_output_types:
        return True
    if output_type == "Point" and "PointList" in capability_output_types:
        return False
    return False


def _capability_allows_creates(capability: ExecutableCapabilitySpec) -> bool:
    """首版只允许路径拉直类能力声明辅助实体。"""
    return capability.capability_id in {
        "broken_path_straightening_and_select",
        "weighted_axis_path_triangle_transform",
        "select_straightening_candidate",
    }


def _candidate_by_id(
    report: StepIntentResolutionStepReport | None,
    capability_id: str,
) -> StepIntentResolutionCandidate | None:
    """从 step report 中找指定 capability 候选。"""
    if report is None:
        return None
    for candidate in report.candidates:
        if candidate.capability_id == capability_id:
            return candidate
    return None

@dataclass(frozen=True)
class _OutputTypeInference:
    """StepIntent 产物类型推断结果。

    ``source`` 用来区分高置信度的 canonical handle/fact 类型和低置信度的自然语言
    description。后续若要根据 capability hint 修正，只允许修正低置信度结果。
    """

    output_type: str | None
    source: str


def _produced_output_type(
    produced: ProducedFact,
    registry: CanonicalHandleRegistry,
) -> str | None:
    """根据 answer value_type、fact type 和语义名推断产物类型。"""
    return _produced_output_type_inference(produced, registry).output_type


def _produced_output_type_inference(
    produced: ProducedFact,
    registry: CanonicalHandleRegistry,
) -> _OutputTypeInference:
    """返回产物类型和来源，避免 description 文本覆盖 canonical handle。"""
    if produced.handle.startswith("answer:"):
        if produced.handle in registry.answer_value_types:
            return _OutputTypeInference(
                registry.answer_value_types[produced.handle],
                "answer_value_type",
            )
        return _output_type_inference_from_text(produced.handle, produced.description)
    if produced.handle in registry.fact_types:
        fact_type = registry.fact_types[produced.handle]
        if fact_type in _FACT_TYPE_TO_OUTPUT_TYPE:
            return _OutputTypeInference(
                _FACT_TYPE_TO_OUTPUT_TYPE[fact_type],
                "fact_type",
            )
    return _output_type_inference_from_text(produced.handle, produced.description)


def _output_type_from_text(handle: str, description: str) -> str | None:
    """从 handle semantic_name 和说明中推断 method/recipe 输出类型。"""
    return _output_type_inference_from_text(handle, description).output_type


def _output_type_inference_from_text(handle: str, description: str) -> _OutputTypeInference:
    """从 handle 和说明推断类型，优先相信 handle semantic name。

    DeepSeek 常会写“由最小值条件反求参数 m”，如果先看 description 里的“最小值”，
    ``fact:*:m_value`` 会被误判成 ``MinimumExpression``。这里先看 canonical
    semantic name，再把自然语言作为最后兜底。
    """
    text = f"{handle}\n{description}".lower()
    name = handle.split(":", 2)[-1].lower()
    if "relation" in name or "equation" in name:
        return _OutputTypeInference("Equation", "semantic_name")
    if _is_parameter_value_semantic_name(name):
        return _OutputTypeInference("ParameterValue", "semantic_name")
    if any(value in name for value in ("coord", "coordinate", "intersection", "axis_point", "point")):
        return _OutputTypeInference("Point", "semantic_name")
    if any(value in name for value in ("coefficient", "coefficients")):
        return _OutputTypeInference("Coefficients", "semantic_name")
    if any(value in name for value in ("minimum", "min_value", "distance")):
        return _OutputTypeInference("MinimumExpression", "semantic_name")
    if any(value in name for value in ("straightened", "straightening", "choice")):
        return _OutputTypeInference("StraighteningCandidate", "semantic_name")
    if any(value in name for value in ("path", "equivalence", "reduction")):
        return _OutputTypeInference("PathTransformation", "semantic_name")
    if any(value in text for value in ("parabola", "抛物线", "解析式")):
        return _OutputTypeInference("Parabola", "description")
    if any(value in text for value in ("straightened", "straightening", "choice", "拉直", "方案")):
        return _OutputTypeInference("StraighteningCandidate", "description")
    if any(value in text for value in ("path", "equivalence", "reduction", "路径", "等价", "降维")):
        return _OutputTypeInference("PathTransformation", "description")
    if any(value in name for value in ("coord", "coordinate", "intersection", "axis_point", "point")):
        return _OutputTypeInference("Point", "semantic_name")
    if any(value in text for value in ("坐标", "交点")):
        return _OutputTypeInference("Point", "description")
    if any(value in text for value in ("minimum", "min_value", "最小值", "distance", "距离")):
        return _OutputTypeInference("MinimumExpression", "description")
    if "关系" in text:
        return _OutputTypeInference("Equation", "description")
    return _OutputTypeInference(None, "unknown")


def _is_parameter_value_semantic_name(name: str) -> bool:
    """判断 semantic name 是否明确表示参数/系数取值。

    不能用 ``"m_value" in name``，因为 ``minimum_value`` 中也会出现相似片段。
    """
    if name in {"m_value", "a_value", "b_value", "c_value", "parameter_value"}:
        return True
    if re.fullmatch(r"parameter_[a-z][a-z0-9]*", name):
        return True
    return bool(
        re.fullmatch(r"(?:parameter_)?[a-z][a-z0-9]*_(?:parameter_)?value", name)
    )


def _maybe_correct_output_types_from_hint(
    step: StepIntent,
    *,
    produced_inferences: tuple[_OutputTypeInference, ...],
    capabilities_by_id: dict[str, ExecutableCapabilitySpec],
) -> tuple[tuple[str, ...], list[str]]:
    """在低置信度文本推断与明确 hint 冲突时，按 hint 能力窄化输出类型。

    只修正 description 兜底造成的误判；answer value_type、已知 fact type 和 handle
    semantic name 都属于高置信度，不在这里被覆盖。
    """
    output_types = tuple(
        inference.output_type
        for inference in produced_inferences
        if inference.output_type is not None
    )
    capability = capabilities_by_id.get(step.recipe_hint or "")
    if capability is None or not output_types:
        return output_types, []
    if _capability_covers_output_types(capability, output_types):
        return output_types, []
    if (
        len(output_types) == 1
        and len(capability.output_types) == 1
        and produced_inferences[0].source == "description"
    ):
        corrected = capability.output_types[0]
        return (
            (corrected,),
            [
                "capability_hint_corrected_output_type:"
                f"{step.step_id}:{output_types[0]}->{corrected}"
            ],
        )
    return output_types, []


_RECIPE_OUTPUT_TYPE_OVERRIDES: dict[str, tuple[str, ...]] = {
    "right_angle_equal_length_construct_and_select": ("Point",),
    "two_moving_points_path_reduction": ("PathTransformation",),
    "broken_path_straightening_and_select": ("StraighteningCandidate", "Point"),
    "path_minimum_by_straightened_distance": ("MinimumExpression",),
}

_FACT_TYPE_TO_OUTPUT_TYPE: dict[str, str] = {
    "point_coordinate": "Point",
    "symbol_value": "ParameterValue",
    "coefficient_relation": "Equation",
    "length_squared": "Condition",
    "minimum_value": "MinimumExpression",
    "path_minimum_target": "Condition",
    "right_angle_equal_length": "Condition",
    "segment_membership": "Condition",
    "segment_relation": "Condition",
    "midpoint_definition": "Condition",
    "orientation_constraint": "OrientationHint",
}

def _method_capability_summary(spec: Any) -> str:
    """生成给 LLM 看的 method 能力短句。

    优先使用人工摘要，避免 ``quadratic_from_constraints`` 这类通用 method 把十几个
    input slot 全塞进 prompt。没有人工摘要时再按类型集合生成短句。
    """
    if spec.method_id in _METHOD_SUMMARY_OVERRIDES:
        return _METHOD_SUMMARY_OVERRIDES[spec.method_id]
    required_types = _unique_ordered(
        input_spec.type for input_spec in spec.inputs.values() if input_spec.required
    )
    optional_types = _unique_ordered(
        input_spec.type for input_spec in spec.inputs.values() if not input_spec.required
    )
    output_types = _unique_ordered(spec.outputs.values())
    pieces = [f"输入: 必需 {', '.join(required_types) or '无'}"]
    if optional_types:
        pieces.append(f"可选 {', '.join(optional_types)}")
    pieces.append(f"输出: {', '.join(output_types) or '无'}")
    return "；".join(pieces)


def _unique_ordered(values: Any) -> list[str]:
    """保持首次出现顺序的去重。"""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result

_METHOD_SUMMARY_OVERRIDES = {
    "quadratic_axis_from_relation": "输入: 二次函数系数关系与目标点定义；输出: 对称轴与 x 轴交点。",
    "quadratic_from_constraints": "输入: 二次函数表达式、已知系数、系数关系、曲线点或参数条件；输出: 系数与抛物线解析式。",
    "right_angle_equal_length_candidates": "输入: 直角顶点、已知端点和未知端点定义；输出: 直角等腰旋转得到的候选点。",
    "select_point_by_quadrant_constraint": "输入: 候选点、象限条件和参数范围；输出: 符合题设方位的点。",
    "parameter_from_segment_length": "输入: 两点和线段长度条件；输出: 满足条件的参数值。",
    "midpoint_point": "输入: 两端点和中点定义；输出: 中点坐标。",
    "two_moving_points_path_reduction": "输入: 两动点所在关系与线段比例关系；输出: 把两动点线段替换为题面已有固定点到动点的等长线段；不创建辅助点或新轨迹。",
    "broken_path_straightening_candidates": "输入: 折线路径两端点、运动线段和辅助点定义；输出: 可用于将军饮马/折线拉直的候选方案。",
    "select_straightening_candidate": "输入: 折线拉直候选方案；输出: 最适合计算的方案和辅助点。",
    "distance_between_points": "输入: 两点及可选参数值；输出: 两点距离或代入参数后的距离。",
    "parameter_from_minimum_value": "输入: 最小值表达式与给定最小值条件；输出: 参数值。",
    "line_intersection_point": "输入: 两条直线；输出: 交点坐标。",
    "quadratic_vertex_point": "输入: 抛物线表达式；输出: 顶点坐标。",
    "quadratic_y_axis_intercept_point": "输入: 抛物线表达式；输出: y 轴交点。",
    "filter_point_candidates_by_quadratic_curve": "输入: 候选点与抛物线；输出: 在抛物线上的候选点列表。",
    "select_curve_point_candidate_and_solve_coefficients": "输入: 候选点、抛物线约束和参数约束；输出: 被选中的曲线点、系数和抛物线。",
    "point_on_parabola_at_x": "输入: 抛物线和横坐标；输出: 曲线上的点。",
    "weighted_axis_path_triangle_transform": "输入: 加权路径、轴上动点和辅助点定义；输出: 几何转化后的等价路径与辅助点轨迹。",
    "linked_broken_path_geometric_minimum": "输入: 已转化路径和辅助点轨迹；输出: 几何最小值与极值点。",
}
