"""StepIntent JSON 解析与语义边界校验。

Validator 只检查 LLM 输出结构、canonical handle、valid_scope、重复 fact 和
recipe/method 对齐，不执行 method。
"""

from __future__ import annotations

import json
import re
from typing import Any

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    HandleResolver,
    _ENTITY_HANDLE_RE,
    _ENTITY_TYPES,
    _FACT_HANDLE_RE,
    _NON_CANONICAL_PREFIXES,
    _handle_scope,
    _handle_suggestions,
    _parse_scoped_non_answer_handle,
    _reject_noncanonical_handle,
    _semantic_name,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    ProducedFact,
    RecipeAlignmentReport,
    StepIntent,
    StepIntentDraft,
    StepIntentScope,
    StepIntentValidationReport,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    _output_type_from_text,
    _produced_output_type,
    build_executable_capabilities,
)

class StepIntentValidator:
    """Phase 1 StepIntent 校验器。

    它只检查 LLM 输出是否适合作为“下一阶段解析”的输入：结构正确、安全边界清晰、
    语义上覆盖题面最终目标。是否能找到 method/recipe/binding 留到后续 resolver。
    """

    def __init__(self) -> None:
        self.last_handle_resolution_report: HandleResolutionReport | None = None

    def validate_json(
        self,
        raw: str,
        *,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...] = (),
        handle_registry: CanonicalHandleRegistry | None = None,
        family_spec: SolverFamilySpec | None = None,
    ) -> StepIntentDraft:
        """解析并校验 LLM 原始 JSON 字符串。"""
        self.last_handle_resolution_report = None
        data = _parse_json_object(raw)
        return self.validate(
            data,
            question_goals=question_goals,
            handle_registry=handle_registry,
            family_spec=family_spec,
        )

    def validate_json_with_report(
        self,
        raw: str,
        *,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...] = (),
        handle_registry: CanonicalHandleRegistry | None = None,
        family_spec: SolverFamilySpec | None = None,
    ) -> tuple[StepIntentDraft | None, StepIntentValidationReport]:
        """校验并返回报告；集成测试用它把失败原因写入 debug artifact。"""
        try:
            draft = self.validate_json(
                raw,
                question_goals=question_goals,
                handle_registry=handle_registry,
                family_spec=family_spec,
            )
        except StrategyDraftValidationError as exc:
            return None, StepIntentValidationReport(
                ok=False,
                errors=(str(exc),),
            )
        return draft, self.report(
            draft,
            question_goals=question_goals,
            family_spec=family_spec,
            handle_resolution=self.last_handle_resolution_report,
        )

    def validate(
        self,
        data: object,
        *,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...] = (),
        handle_registry: CanonicalHandleRegistry | None = None,
        family_spec: SolverFamilySpec | None = None,
    ) -> StepIntentDraft:
        """校验已解析 JSON 对象，并转成 StepIntentDraft。"""
        self.last_handle_resolution_report = None
        if not isinstance(data, dict):
            raise StrategyDraftValidationError("top-level response must be an object")
        extra = sorted(set(data) - {"scopes"})
        if extra:
            raise StrategyDraftValidationError(
                f"top-level response contains unsupported fields: {', '.join(extra)}"
            )
        _reject_forbidden_payload(data)
        raw_scopes = data.get("scopes")
        if not isinstance(raw_scopes, list) or not raw_scopes:
            raise StrategyDraftValidationError("scopes must be a non-empty list")
        scopes: list[StepIntentScope] = []
        for scope_index, raw_scope in enumerate(raw_scopes):
            scope = _parse_scope(raw_scope, scope_index=scope_index)
            seen_step_ids: set[str] = set()
            for step in scope.steps:
                if step.step_id in seen_step_ids:
                    raise StrategyDraftValidationError(
                        f"duplicate step_id in scope {scope.scope_id}: {step.step_id}"
                    )
                seen_step_ids.add(step.step_id)
            scopes.append(scope)
        draft = StepIntentDraft(scopes=tuple(scopes))
        if question_goals:
            _validate_step_scope_targets(draft, question_goals)
        if handle_registry is not None:
            draft, handle_resolution = HandleResolver().resolve_draft(
                draft,
                handle_registry,
            )
            self.last_handle_resolution_report = handle_resolution
            _validate_step_handles(draft, handle_registry)
        report = self.report(
            draft,
            question_goals=question_goals,
            family_spec=family_spec,
            handle_resolution=self.last_handle_resolution_report,
        )
        if report.missing_goals:
            raise StrategyDraftValidationError(
                "missing required answer handles: "
                + ", ".join(report.missing_goals)
            )
        return draft

    def report(
        self,
        draft: StepIntentDraft,
        *,
        question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...] = (),
        family_spec: SolverFamilySpec | None = None,
        handle_resolution: HandleResolutionReport | None = None,
    ) -> StepIntentValidationReport:
        """生成覆盖情况报告。"""
        produced_text = "\n".join(
            "\n".join((step.target, *(item.handle for item in step.produces)))
            for step in draft.steps
        )
        required_handles = [
            f"answer:{goal.id}"
            for goal in question_goals
            if goal.required
        ]
        covered = tuple(
            handle for handle in required_handles
            if handle in produced_text or handle.removeprefix("answer:") in produced_text
        )
        missing = tuple(handle for handle in required_handles if handle not in covered)
        alignment = (
            _recipe_alignment_report(draft, family_spec)
            if family_spec is not None
            else None
        )
        return StepIntentValidationReport(
            ok=not missing,
            step_count=len(draft.steps),
            covered_goals=covered,
            missing_goals=missing,
            recipe_alignment=alignment,
            handle_resolution=handle_resolution,
        )

def _validate_step_scope_targets(
    draft: StepIntentDraft,
    question_goals: list[QuestionGoal] | tuple[QuestionGoal, ...],
) -> None:
    """强制 StepIntent 只输出真实作答题问/小问的步骤。

    ``problem`` 和只用于组织子问的父级 scope 很容易诱导模型生成“公共推导段”。
    我们不允许这种展示结构：公共结论应该在最先用到它的真实题问步骤中产生，
    再通过 ``valid_scope`` 标明它可被父级或兄弟子问复用。
    """
    answer_scope_ids = {
        goal.question_id
        for goal in question_goals
        if goal.required
    }
    if not answer_scope_ids:
        return
    for scope in draft.scopes:
        if scope.scope_id not in answer_scope_ids:
            raise StrategyDraftValidationError(
                "public_derivation_scope_not_allowed: "
                f"scope={scope.scope_id}, allowed_answer_scopes={sorted(answer_scope_ids)}; "
                "put shared facts in the first real question/subquestion step and set valid_scope"
            )

def _parse_json_object(raw: str) -> dict[str, Any]:
    """解析模型输出，兼容偶发 markdown fence。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StrategyDraftValidationError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StrategyDraftValidationError("JSON response must be an object")
    return data

_STEP_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_NUMBERED_STEP_RE = re.compile(r"^(step|步骤)_?\d+$", re.IGNORECASE)
_FORBIDDEN_STRINGS = (
    "$problem",
    "$question",
    "$subquestion",
    "$step",
    "ContextPath",
    "ctx_",
)
_FORBIDDEN_KEYS = {
    "answer",
    "answers",
    "binding",
    "bindings",
    "coordinate",
    "coordinates",
    "depends_on",
    "knowns",
    "method_invocation",
    "promote_to",
    "publish",
    "value",
    "values",
}


def _parse_scope(raw_scope: object, *, scope_index: int) -> StepIntentScope:
    """解析一个 question/subquestion scope 分组。"""
    if not isinstance(raw_scope, dict):
        raise StrategyDraftValidationError(f"scopes[{scope_index}] must be an object")
    required = {"scope_id", "label", "steps"}
    extra = sorted(set(raw_scope) - required)
    missing = sorted(required - set(raw_scope))
    if missing:
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}] missing required fields: {', '.join(missing)}"
        )
    if extra:
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}] contains unsupported fields: {', '.join(extra)}"
        )
    scope_id = _required_scope_string(raw_scope, "scope_id", scope_index=scope_index)
    label = _required_scope_string(raw_scope, "label", scope_index=scope_index)
    raw_steps = raw_scope.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps must be a non-empty list"
        )
    steps = tuple(
        _parse_step(raw_step, scope_id=scope_id, scope_index=scope_index, step_index=step_index)
        for step_index, raw_step in enumerate(raw_steps)
    )
    return StepIntentScope(scope_id=scope_id, label=label, steps=steps)


def _required_scope_string(
    raw_scope: dict[str, Any],
    key: str,
    *,
    scope_index: int,
) -> str:
    """读取 scope 分组里的非空字符串字段。"""
    value = raw_scope.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].{key} must be a string"
        )
    return value.strip()


def _parse_step(
    raw_step: object,
    *,
    scope_id: str,
    scope_index: int,
    step_index: int,
) -> StepIntent:
    """解析单个 step 对象并做字段级校验。"""
    if not isinstance(raw_step, dict):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}] must be an object"
        )
    required = {
        "step_id",
        "goal_type",
        "target",
        "strategy",
        "reads",
        "creates",
        "produces",
        "reason",
    }
    optional = {"recipe_hint"}
    extra = sorted(set(raw_step) - required - optional)
    missing = sorted(required - set(raw_step))
    if missing:
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}] missing required fields: {', '.join(missing)}"
        )
    if extra:
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}] contains unsupported fields: {', '.join(extra)}"
        )
    step_id = _required_string(
        raw_step,
        "step_id",
        scope_index=scope_index,
        step_index=step_index,
    )
    if not _STEP_ID_RE.fullmatch(step_id):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].step_id must be semantic snake_case: {step_id!r}"
        )
    if _NUMBERED_STEP_RE.fullmatch(step_id):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].step_id must not be numbered: {step_id!r}"
        )
    recipe_hint = _optional_string_or_null(
        raw_step,
        "recipe_hint",
        scope_index=scope_index,
        step_index=step_index,
    )
    return StepIntent(
        scope_id=scope_id,
        step_id=step_id,
        recipe_hint=recipe_hint,
        goal_type=_required_string(raw_step, "goal_type", scope_index=scope_index, step_index=step_index),
        target=_required_string(raw_step, "target", scope_index=scope_index, step_index=step_index),
        strategy=_required_string(raw_step, "strategy", scope_index=scope_index, step_index=step_index),
        reads=tuple(_string_list(raw_step, "reads", scope_index=scope_index, step_index=step_index)),
        creates=tuple(_creates_list(raw_step, scope_index=scope_index, step_index=step_index)),
        produces=tuple(_produces_list(raw_step, scope_index=scope_index, step_index=step_index)),
        reason=_required_string(raw_step, "reason", scope_index=scope_index, step_index=step_index),
    )


def _optional_string_or_null(
    raw_step: dict[str, Any],
    key: str,
    *,
    scope_index: int,
    step_index: int,
) -> str | None:
    """读取可选字符串/null 字段，空字符串归一化为 None。"""
    if key not in raw_step or raw_step[key] is None:
        return None
    value = raw_step[key]
    if not isinstance(value, str):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].{key} must be a string or null"
        )
    text = value.strip()
    return text or None


def _required_string(
    raw_step: dict[str, Any],
    key: str,
    *,
    scope_index: int,
    step_index: int,
) -> str:
    """读取非空字符串字段。"""
    value = raw_step.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].{key} must be a string"
        )
    return value.strip()


def _string_list(
    raw_step: dict[str, Any],
    key: str,
    *,
    scope_index: int,
    step_index: int,
) -> list[str]:
    """读取字符串数组字段。"""
    value = raw_step.get(key)
    if not isinstance(value, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].{key} must be a string array"
        )
    result: list[str] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].{key}[{item_index}] must be a non-empty string"
            )
        result.append(item.strip())
    return result


def _creates_list(
    raw_step: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
) -> list[CreatedEntity]:
    """读取 creates 对象数组。"""
    value = raw_step.get("creates")
    if not isinstance(value, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].creates must be an object array"
        )
    result: list[CreatedEntity] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].creates[{item_index}] must be an object"
            )
        required = {"handle", "entity_type", "valid_scope", "description"}
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required)
        if missing:
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].creates[{item_index}] missing required fields: {', '.join(missing)}"
            )
        if extra:
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].creates[{item_index}] contains unsupported fields: {', '.join(extra)}"
            )
        handle = _required_output_string(
            item,
            "handle",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        entity_type = _required_output_string(
            item,
            "entity_type",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        valid_scope = _required_output_string(
            item,
            "valid_scope",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        description = _required_output_string(
            item,
            "description",
            field="creates",
            scope_index=scope_index,
            step_index=step_index,
            item_index=item_index,
        )
        result.append(
            CreatedEntity(
                handle=handle,
                entity_type=entity_type,
                valid_scope=valid_scope,
                description=description,
            )
        )
    return result


def _produces_list(
    raw_step: dict[str, Any],
    *,
    scope_index: int,
    step_index: int,
) -> list[ProducedFact]:
    """读取 produces 对象数组。"""
    value = raw_step.get("produces")
    if not isinstance(value, list):
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].produces must be an object array"
        )
    result: list[ProducedFact] = []
    for item_index, item in enumerate(value):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].produces[{item_index}] must be an object"
            )
        required = {"handle", "valid_scope", "description"}
        missing = sorted(required - set(item))
        extra = sorted(set(item) - required)
        if missing:
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].produces[{item_index}] missing required fields: {', '.join(missing)}"
            )
        if extra:
            raise StrategyDraftValidationError(
                f"scopes[{scope_index}].steps[{step_index}].produces[{item_index}] contains unsupported fields: {', '.join(extra)}"
            )
        result.append(
            ProducedFact(
                handle=_required_output_string(
                    item,
                    "handle",
                    field="produces",
                    scope_index=scope_index,
                    step_index=step_index,
                    item_index=item_index,
                ),
                valid_scope=_required_output_string(
                    item,
                    "valid_scope",
                    field="produces",
                    scope_index=scope_index,
                    step_index=step_index,
                    item_index=item_index,
                ),
                description=_required_output_string(
                    item,
                    "description",
                    field="produces",
                    scope_index=scope_index,
                    step_index=step_index,
                    item_index=item_index,
                ),
            )
        )
    return result


def _required_output_string(
    raw_output: dict[str, Any],
    key: str,
    *,
    field: str,
    scope_index: int,
    step_index: int,
    item_index: int,
) -> str:
    """读取 creates/produces 对象里的非空字符串字段。"""
    value = raw_output.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(
            f"scopes[{scope_index}].steps[{step_index}].{field}[{item_index}].{key} must be a string"
        )
    return value.strip()


def _reject_forbidden_payload(value: Any, *, path: str = "$") -> None:
    """递归拒绝旧 planner 的路径/绑定/答案字段泄露到 StepIntent。"""
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in _FORBIDDEN_KEYS:
                raise StrategyDraftValidationError(
                    f"forbidden field {path}.{key}: StepIntent must not contain executable bindings or answers"
                )
            _reject_forbidden_payload(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            # 明确拒绝坐标数组这类裸值输出；reads 仍允许字符串数组。
            if len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
                raise StrategyDraftValidationError(
                    f"forbidden coordinate-like array at {path}"
                )
            _reject_forbidden_payload(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        for forbidden in _FORBIDDEN_STRINGS:
            if forbidden in value:
                raise StrategyDraftValidationError(
                    f"forbidden token {forbidden!r} at {path}"
                )


def _validate_step_handles(
    draft: StepIntentDraft,
    registry: CanonicalHandleRegistry,
) -> None:
    """校验 reads/creates/produces 是否遵守 canonical handle 数据流。

    规则很简单：题设已有的 Entity/Fact/answer 可以读；每一步只能读前面已经产生的
    handle；新实体必须放进 creates，新事实或最终答案必须放进 produces。
    """
    available = set(registry.initial_handles)
    handle_valid_scopes = dict(registry.handle_valid_scopes)
    created_handles: set[str] = set()
    produced_handles: set[str] = set()
    produced_signatures: dict[str, list[tuple[str, str, str]]] = {}
    for step in draft.steps:
        registry.validate_scope(step.scope_id, context=f"step {step.step_id}")
        for handle in step.reads:
            _validate_read_handle(
                handle,
                available=available,
                step_id=step.step_id,
            )
        for item in step.creates:
            _validate_created_entity(
                item,
                registry=registry,
                available=available,
                created_handles=created_handles,
                step_id=step.step_id,
            )
            available.add(item.handle)
            handle_valid_scopes[item.handle] = item.valid_scope
            created_handles.add(item.handle)
        for item in step.produces:
            _validate_produced_fact(
                item,
                registry=registry,
                available=available,
                handle_valid_scopes=handle_valid_scopes,
                produced_handles=produced_handles,
                produced_signatures=produced_signatures,
                step=step,
                step_id=step.step_id,
            )
            available.add(item.handle)
            handle_valid_scopes[item.handle] = item.valid_scope
            produced_handles.add(item.handle)


def _validate_read_handle(
    handle: str,
    *,
    available: set[str],
    step_id: str,
) -> None:
    """校验 reads[] 中的 handle 必须已经存在。"""
    _reject_noncanonical_handle(handle, field=f"step {step_id}.reads")
    if handle not in available:
        raise StrategyDraftValidationError(
            "unknown_read_handle: "
            f"step={step_id}, handle={handle}, available_handles={_handle_suggestions(handle, available)}"
        )


def _parse_scoped_non_answer_handle(handle: str) -> tuple[str, str, str] | None:
    """解析 Entity/Fact handle 为 ``(kind, scope, name)``。

    answer handle 不参与自动修正，因为最终答案目标必须原样来自
    ``question_goals[].handle``，不能根据 scope 猜测。
    """
    fact_match = _FACT_HANDLE_RE.fullmatch(handle)
    if fact_match is not None:
        return ("fact", fact_match.group("scope"), fact_match.group("name"))
    entity_match = _ENTITY_HANDLE_RE.fullmatch(handle)
    if entity_match is not None:
        return (
            entity_match.group("kind"),
            entity_match.group("scope"),
            entity_match.group("name"),
        )
    return None


def _validate_created_entity(
    item: CreatedEntity,
    *,
    registry: CanonicalHandleRegistry,
    available: set[str],
    created_handles: set[str],
    step_id: str,
) -> None:
    """校验 creates[] 只能创建新的 derived Entity。"""
    registry.validate_scope(item.valid_scope, context=f"step {step_id}.creates[{item.handle}]")
    if item.entity_type not in _ENTITY_TYPES:
        raise StrategyDraftValidationError(
            f"invalid_created_entity_type: step={step_id}, handle={item.handle}, entity_type={item.entity_type}"
        )
    match = _ENTITY_HANDLE_RE.fullmatch(item.handle)
    if match is None:
        raise StrategyDraftValidationError(
            f"invalid_created_entity_handle: step={step_id}, handle={item.handle}"
        )
    if match.group("kind") != item.entity_type:
        raise StrategyDraftValidationError(
            f"created_entity_type_mismatch: step={step_id}, handle={item.handle}, entity_type={item.entity_type}"
        )
    if match.group("scope") not in registry.scope_ids:
        raise StrategyDraftValidationError(
            f"unknown_created_entity_scope: step={step_id}, handle={item.handle}"
        )
    if item.handle in registry.entity_handles:
        raise StrategyDraftValidationError(
            f"create_overwrites_given_entity: step={step_id}, handle={item.handle}"
        )
    if item.handle in available or item.handle in created_handles:
        raise StrategyDraftValidationError(
            f"duplicate_created_entity: step={step_id}, handle={item.handle}"
        )


def _validate_produced_fact(
    item: ProducedFact,
    *,
    registry: CanonicalHandleRegistry,
    available: set[str],
    handle_valid_scopes: dict[str, str],
    produced_handles: set[str],
    produced_signatures: dict[str, tuple[str, str, str]],
    step: StepIntent,
    step_id: str,
) -> None:
    """校验 produces[] 只能产生新 fact 或题面 question goal 对应 answer。"""
    registry.validate_scope(item.valid_scope, context=f"step {step_id}.produces[{item.handle}]")
    if item.handle.startswith("answer:"):
        if item.handle not in registry.answer_handles:
            raise StrategyDraftValidationError(
                f"unknown_answer_handle: step={step_id}, handle={item.handle}, available_answers={sorted(registry.answer_handles)}"
            )
    elif item.handle.startswith("fact:"):
        match = _FACT_HANDLE_RE.fullmatch(item.handle)
        if match is None:
            raise StrategyDraftValidationError(
                f"invalid_fact_handle: step={step_id}, handle={item.handle}"
            )
        if match.group("scope") not in registry.scope_ids:
            raise StrategyDraftValidationError(
                f"unknown_fact_scope: step={step_id}, handle={item.handle}"
            )
        if item.handle in registry.fact_handles:
            raise StrategyDraftValidationError(
                f"produce_overwrites_given_fact: step={step_id}, handle={item.handle}"
            )
    else:
        raise StrategyDraftValidationError(
            f"invalid_produce_handle: step={step_id}, handle={item.handle}; expected fact:* or answer:*"
        )
    if item.handle in produced_handles:
        raise StrategyDraftValidationError(
            f"duplicate_produced_handle: step={step_id}, handle={item.handle}"
        )
    if item.handle in available and not item.handle.startswith("answer:"):
        raise StrategyDraftValidationError(
            f"produce_overwrites_available_handle: step={step_id}, handle={item.handle}"
        )
    # valid_scope 是否被 child-only reads 夸大，需要结合最终承接该 step 的
    # recipe/method 判断。LLM 有时会多写一个未被实际 method 使用的 reads；
    # 这种“无害多读”不应在纯结构校验层阻断，后续 CandidateResolver 会按
    # selected capability 对实际会使用的 reads 做更精确检查。
    _validate_produced_semantic_signature(
        item,
        step=step,
        registry=registry,
        produced_signatures=produced_signatures,
    )


def _validate_produced_semantic_signature(
    item: ProducedFact,
    *,
    step: StepIntent,
    registry: CanonicalHandleRegistry,
    produced_signatures: dict[str, list[tuple[str, str, str]]],
) -> None:
    """用语义签名提前发现同一结论的重复/倒序推导。

    LLM 有时会先在小问中产生 ``F_coordinate_numeric``，后面又产生父 scope 下的
    ``F_coordinate_expr``。两者 handle 不同，但语义上都是 F 的坐标，应在
    Strategy 层给出可修复错误，而不是等 runtime 报 PointRef/Point 类型冲突。
    """
    signature = _produced_fact_signature(item, registry)
    if signature is None:
        return
    previous_items = produced_signatures.setdefault(signature, [])
    if not previous_items:
        previous_items.append((item.valid_scope, step.step_id, item.handle))
        return
    for previous_scope, previous_step_id, previous_handle in previous_items:
        previous_is_visible_from_current = previous_scope in registry.ancestor_scopes(item.valid_scope)
        current_is_visible_from_previous = item.valid_scope in registry.ancestor_scopes(previous_scope)
        if item.valid_scope != previous_scope and current_is_visible_from_previous:
            raise StrategyDraftValidationError(
                "common_fact_after_narrow_fact: "
                f"signature={signature}, previous_step={previous_step_id}, "
                f"previous_handle={previous_handle}, previous_valid_scope={previous_scope}, "
                f"current_step={step.step_id}, current_handle={item.handle}, "
                f"current_valid_scope={item.valid_scope}; produce the broader common fact first, "
                "then let later subquestions read it"
            )
        if previous_is_visible_from_current:
            raise StrategyDraftValidationError(
                "duplicate_point_coordinate_fact: "
                f"signature={signature}, previous_step={previous_step_id}, "
                f"previous_handle={previous_handle}, previous_valid_scope={previous_scope}, "
                f"current_step={step.step_id}, current_handle={item.handle}, "
                f"current_valid_scope={item.valid_scope}; read the existing fact instead of "
                "creating another derivation step"
            )
        if signature.startswith("point_coordinate:") and _are_sibling_scopes(
            previous_scope,
            item.valid_scope,
            registry,
        ):
            raise StrategyDraftValidationError(
                "duplicate_point_coordinate_fact: "
                f"signature={signature}, previous_step={previous_step_id}, "
                f"previous_handle={previous_handle}, previous_valid_scope={previous_scope}, "
                f"current_step={step.step_id}, current_handle={item.handle}, "
                f"current_valid_scope={item.valid_scope}; the same parent-scope entity "
                "coordinate cannot be derived separately in sibling subquestions. Produce "
                "the parent-scope coordinate expression first, then let sibling subquestions "
                "read it together with their parameter facts"
            )
    # sibling scope 的同名参数值可能代表不同取值，不能在这里猜测合并。
    previous_items.append((item.valid_scope, step.step_id, item.handle))


def _are_sibling_scopes(
    left: str,
    right: str,
    registry: CanonicalHandleRegistry,
) -> bool:
    """判断两个 scope 是否是同一父级下的兄弟 scope。"""
    if left == right:
        return False
    return (
        registry.scope_parents.get(left) is not None
        and registry.scope_parents.get(left) == registry.scope_parents.get(right)
    )


def _produced_fact_signature(
    item: ProducedFact,
    registry: CanonicalHandleRegistry,
) -> str | None:
    """为 produced fact 生成“同一数学结论”的粗粒度签名。"""
    if not item.handle.startswith("fact:"):
        return None
    name = _semantic_name(item.handle)
    output_type = _produced_output_type(item, registry)
    if output_type == "Point":
        point_name = _point_name_from_coordinate_semantic_name(name)
        if point_name is not None:
            return f"point_coordinate:{point_name}"
    if output_type == "ParameterValue":
        symbol = name.split("_", 1)[0]
        return f"parameter:{symbol}"
    if output_type == "Parabola":
        return f"parabola:{item.valid_scope}"
    if output_type == "MinimumExpression":
        return f"minimum_expr:{item.valid_scope}"
    if output_type == "PathTransformation":
        return f"path_transformation:{item.valid_scope}"
    return None


def _point_name_from_coordinate_semantic_name(name: str) -> str | None:
    """从 ``F_coordinate_expr`` / ``D_coordinate_value`` 这类语义名取点名。"""
    match = re.fullmatch(r"(?P<point>[A-Za-z][A-Za-z0-9]*)_coordinate(?:_[A-Za-z0-9_]+)?", name)
    if match is None:
        return None
    return match.group("point")


def _reject_noncanonical_handle(handle: str, *, field: str) -> None:
    """给常见自造 handle 更明确的错误，而不是只报 unknown。"""
    if any(handle.startswith(prefix) for prefix in _NON_CANONICAL_PREFIXES):
        raise StrategyDraftValidationError(
            f"noncanonical_handle: {field} uses {handle}; use fact:<scope>:<semantic_name>"
        )
    if handle.startswith("fact:") and _FACT_HANDLE_RE.fullmatch(handle) is None:
        raise StrategyDraftValidationError(
            f"noncanonical_handle: {field} uses {handle}; "
            "fact handles require fact:<scope>:<semantic_name>; copy exact handle from ProblemIR or previous produces"
        )
    if re.fullmatch(r"[A-Za-z]+:[A-Za-z0-9_]+", handle) and not handle.startswith("answer:"):
        raise StrategyDraftValidationError(
            f"noncanonical_handle: {field} uses {handle}; entity handles require type:scope:name"
        )


def _recipe_alignment_report(
    draft: StepIntentDraft,
    family: SolverFamilySpec,
) -> RecipeAlignmentReport:
    """统计 StepIntent 中 recipe_hint 与 family 菜单的匹配情况。"""
    recipe_ids = {recipe.recipe_id for recipe in family.step_recipes}
    preferred_recipe_ids = tuple(
        recipe.recipe_id
        for recipe in family.step_recipes
        if recipe.priority == "preferred"
    )
    method_ids = set(family.method_ids)
    goal_types = set(family.common_goal_types)

    matched_recipes: list[str] = []
    matched_methods: list[str] = []
    null_hint_steps: list[str] = []
    unknown_hint_steps: list[str] = []
    unknown_goal_type_steps: list[str] = []
    avoid_pattern_hits: list[dict[str, str]] = []
    capability_errors: list[dict[str, str]] = []
    avoid_pattern_hits.extend(_symbolic_quadratic_order_hits(draft))

    for scope in draft.scopes:
        for step in scope.steps:
            if step.goal_type not in goal_types:
                unknown_goal_type_steps.append(f"{step.step_id}:{step.goal_type}")
            hint = step.recipe_hint
            if hint is None:
                null_hint_steps.append(step.step_id)
            elif hint in recipe_ids:
                matched_recipes.append(hint)
            elif hint in method_ids:
                matched_methods.append(hint)
            else:
                unknown_hint_steps.append(f"{step.step_id}:{hint}")
            hit = _avoid_pattern_hit(step)
            if hit is not None:
                avoid_pattern_hits.append(hit)
            capability_errors.extend(
                _capability_alignment_errors(
                    step,
                    recipe_ids=recipe_ids,
                    method_ids=method_ids,
                )
            )
            symbolic_hit = _symbolic_quadratic_utility_error_for_scope(
                step,
                steps=scope.steps,
            )
            if symbolic_hit is not None:
                capability_errors.append(symbolic_hit)

    covered_preferred = tuple(
        recipe_id for recipe_id in preferred_recipe_ids
        if recipe_id in set(matched_recipes)
    )
    missing_preferred = tuple(
        recipe_id for recipe_id in preferred_recipe_ids
        if recipe_id not in set(matched_recipes)
    )
    return RecipeAlignmentReport(
        matched_recipes=tuple(matched_recipes),
        matched_methods=tuple(matched_methods),
        null_hint_steps=tuple(null_hint_steps),
        unknown_hint_steps=tuple(unknown_hint_steps),
        unknown_goal_type_steps=tuple(unknown_goal_type_steps),
        preferred_recipe_ids=preferred_recipe_ids,
        covered_preferred_recipe_ids=covered_preferred,
        missing_preferred_recipe_ids=missing_preferred,
        avoid_pattern_hits=tuple(avoid_pattern_hits),
        capability_errors=tuple(capability_errors),
    )


_PATH_GOAL_TYPES = frozenset((
    "reduce_path_expression",
    "straighten_broken_path",
    "derive_minimum_value",
))
_AVOID_DERIVATIVE_PATTERN_RE = re.compile(
    r"求导|导数|建函数|函数最值|derivative|differentiate",
    re.IGNORECASE,
)
_PARAMETERIZE_PATTERN_RE = re.compile(r"参数化|parameterize", re.IGNORECASE)
_PATH_RECIPE_HINTS = frozenset((
    "two_moving_points_path_reduction",
    "broken_path_straightening_and_select",
    "path_minimum_by_straightened_distance",
))


def _avoid_pattern_hit(step: StepIntent) -> dict[str, str] | None:
    """识别模型偏离 family 推荐策略的 warning。"""
    text = "\n".join((step.step_id, step.goal_type, step.target, step.strategy, step.reason))
    explicit_bad_ids = {
        "parameterize_moving_points",
        "formulate_path_expression",
        "derive_minimum_expression",
    }
    if step.step_id in explicit_bad_ids:
        return {
            "step_id": step.step_id,
            "goal_type": step.goal_type,
            "pattern": step.step_id,
        }
    if step.goal_type not in _PATH_GOAL_TYPES:
        return None
    if _AVOID_DERIVATIVE_PATTERN_RE.search(text):
        return {
            "step_id": step.step_id,
            "goal_type": step.goal_type,
            "pattern": "parameterization_or_derivative_route",
        }
    if step.recipe_hint not in _PATH_RECIPE_HINTS and _PARAMETERIZE_PATTERN_RE.search(text):
        return {
            "step_id": step.step_id,
            "goal_type": step.goal_type,
            "pattern": "parameterization_or_derivative_route",
        }
    return None


def _symbolic_quadratic_order_hits(draft: StepIntentDraft) -> list[dict[str, str]]:
    """识别“能先定值却先抽通用含参表达式”的绕路步骤。

    单独的含参化简并不总是错：若当前还不能求参数，先代入已知条件减少未知量是
    合理的。这里仅在同一 scope 后续已经出现参数定值 step 时提示模型调整顺序。
    """
    hits: list[dict[str, str]] = []
    for scope in draft.scopes:
        steps = list(scope.steps)
        for index, step in enumerate(steps):
            if not _is_symbolic_quadratic_simplification_step(step):
                continue
            later_parameter_step = next(
                (
                    later
                    for later in steps[index + 1:]
                    if _is_parameter_value_step(later)
                ),
                None,
            )
            if later_parameter_step is None:
                continue
            hits.append(
                {
                    "step_id": step.step_id,
                    "goal_type": step.goal_type,
                    "pattern": "symbolic_quadratic_before_available_parameter_value",
                    "related_step_id": later_parameter_step.step_id,
                }
            )
    return hits


def _symbolic_quadratic_utility_error_for_scope(
    step: StepIntent,
    *,
    steps: tuple[StepIntent, ...],
) -> dict[str, str] | None:
    """把公共含参系数缓存 step 升级为阻断性 capability error。"""
    if not _is_symbolic_quadratic_simplification_step(step):
        return None
    if not _scope_has_parameter_value_step(steps):
        return None
    return _capability_error(
        step,
        step.recipe_hint or "quadratic_from_constraints",
        "utility_symbolic_coefficients_step_not_allowed",
        (
            "Do not produce shared parameterized coefficient cache facts such as "
            "parabola_coefficients_expr. First solve the parameter in the current "
            "subquestion when possible, then use quadratic_from_constraints to "
            "produce the subquestion parabola answer directly."
        ),
    )


def _is_symbolic_quadratic_simplification_step(step: StepIntent) -> bool:
    """判断 step 是否是在产出非答案的含参抛物线/系数化简结果。

    这类 step 如果出现在参数求值前，通常会让解题比“先求参数再代入”更绕。
    """
    if step.recipe_hint != "quadratic_from_constraints":
        return False
    if any(item.handle.startswith("answer:") for item in step.produces):
        return False
    text = _produced_semantic_text(step)
    semantic_names = " ".join(
        item.handle.split(":", 2)[-1].lower()
        for item in step.produces
    )
    has_quadratic_coefficients = _contains_any(
        semantic_names + "\n" + text,
        ("parabola_coefficients", "coefficients_expr", "coefficients_in", "抛物线系数", "系数"),
    )
    has_parameterized_reuse = _contains_any(
        semantic_names + "\n" + text,
        ("_in_m", "with_m", "关于 m", "含参数", "含参", "用 m", "后续", "可复用"),
    )
    return has_quadratic_coefficients and has_parameterized_reuse


def _is_parameter_value_step(step: StepIntent) -> bool:
    """判断 step 是否产出参数数值。"""
    if step.recipe_hint in {
        "parameter_from_segment_length",
        "parameter_from_minimum_value",
    }:
        return True
    return any(
        _output_type_from_text(item.handle, item.description) == "ParameterValue"
        for item in step.produces
    )


def _scope_has_parameter_value_step(steps: tuple[StepIntent, ...]) -> bool:
    """判断当前 scope 中是否存在参数定值 step。"""
    return any(_is_parameter_value_step(step) for step in steps)


def _capability_alignment_errors(
    step: StepIntent,
    *,
    recipe_ids: set[str],
    method_ids: set[str],
) -> list[dict[str, str]]:
    """检查 step 的 produces 是否越过 recipe/method 能力边界。

    这里仍是 probe 层的轻量语义检查，不执行 method。它的目的不是证明 step 一定
    可执行，而是尽早挡住“一步里顺手把后续 method 的答案也产出”的草稿。
    """
    hint = step.recipe_hint
    if hint is None or (hint not in recipe_ids and hint not in method_ids):
        return []
    produced = _produced_semantic_text(step)
    errors: list[dict[str, str]] = []

    if hint == "right_angle_equal_length_construct_and_select":
        if _contains_any(produced, ("candidate", "candidates", "候选")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_outputs_internal_candidates",
                "recipe should output selected constructed point fact, not candidate set",
            ))
        if not _contains_any(produced, ("coordinate", "coord", "坐标", "point")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_missing_selected_point_output",
                "recipe should produce selected point coordinate fact",
            ))
        return errors

    if hint == "two_moving_points_path_reduction":
        if not _contains_any(produced, ("path", "equivalence", "reduced", "路径", "等价", "降维")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_missing_path_reduction_output",
                "recipe should produce path reduction/equivalence fact",
            ))
        if _contains_any(produced, ("minimum", "min_value", "最小值", "distance", "距离")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_mixes_minimum_value",
                "path reduction must not produce minimum value",
            ))
        return errors

    if hint == "broken_path_straightening_and_select":
        if not _contains_any(produced, ("straight", "straightened", "choice", "拉直", "方案")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_missing_straightening_choice",
                "recipe should produce selected straightening choice",
            ))
        if _contains_any(produced, ("minimum", "min_value", "最小值")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_mixes_minimum_value",
                "straightening recipe must not produce minimum value",
            ))
        return errors

    if hint == "path_minimum_by_straightened_distance":
        if not _contains_any(produced, ("minimum", "min_value", "distance", "最小值", "距离")):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_missing_minimum_output",
                "recipe should produce minimum/distance fact or answer",
            ))
        if _contains_any(produced, ("parabola", "抛物线")) or _produces_exact_fact_name(
            step,
            {"m_value", "a_value", "b_value", "c_value"},
        ):
            errors.append(_capability_error(
                step,
                hint,
                "recipe_mixes_parameter_or_parabola",
                "minimum recipe must not solve parameters or parabola",
            ))
        return errors

    if hint == "parameter_from_segment_length":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("parabola", "抛物线", "coordinate", "coord", "坐标", "minimum", "最小值"),
            code="method_mixes_non_parameter_outputs",
            message="parameter_from_segment_length should only produce parameter fact",
        )
        if _produces_answer(step):
            errors.append(_capability_error(
                step,
                hint,
                "method_outputs_answer",
                "parameter method should not produce final answer directly",
            ))
        return errors

    if hint == "parameter_from_minimum_value":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("parabola", "抛物线", "coordinate", "coord", "坐标"),
            code="method_mixes_non_parameter_outputs",
            message="parameter_from_minimum_value should only produce parameter fact",
        )
        if _produces_answer(step):
            errors.append(_capability_error(
                step,
                hint,
                "method_outputs_answer",
                "parameter method should not produce final answer directly",
            ))
        return errors

    if hint == "quadratic_from_constraints":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("m_value", "minimum", "最小值", "coordinate", "coord", "坐标"),
            code="method_mixes_non_quadratic_outputs",
            message="quadratic_from_constraints should produce coefficients/parabola only",
        )
        return errors

    if hint == "midpoint_point":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("parabola", "抛物线", "minimum", "最小值", "m_value", "a_value"),
            code="method_mixes_non_midpoint_outputs",
            message="midpoint_point should produce midpoint coordinate only",
        )
        return errors

    if hint == "line_intersection_point":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("parabola", "抛物线", "minimum", "最小值", "m_value", "a_value"),
            code="method_mixes_non_intersection_outputs",
            message="line_intersection_point should produce intersection point only",
        )
        return errors

    if hint == "distance_between_points":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("parabola", "抛物线", "coordinate", "coord", "坐标", "m_value", "a_value"),
            code="method_mixes_non_distance_outputs",
            message="distance_between_points should produce distance/minimum fact only",
        )
        return errors

    if hint == "quadratic_axis_from_relation":
        _add_forbidden_output_errors(
            errors,
            step,
            hint,
            produced,
            forbidden=("parabola", "抛物线", "minimum", "最小值", "m_value"),
            code="method_mixes_non_axis_outputs",
            message="quadratic_axis_from_relation should produce axis point coordinate only",
        )
    return errors


def _produced_semantic_text(step: StepIntent) -> str:
    """把 produces 的 handle/description 合成小写文本，供轻量能力判断。"""
    return "\n".join(
        f"{item.handle}\n{item.description}"
        for item in step.produces
    ).lower()


def _produces_answer(step: StepIntent) -> bool:
    """判断 step 是否直接产出最终 answer。"""
    return any(item.handle.startswith("answer:") for item in step.produces)


def _produces_exact_fact_name(step: StepIntent, names: set[str]) -> bool:
    """按 fact handle 的 semantic_name 精确判断，避免 minimum_value 误中 m_value。"""
    for item in step.produces:
        if not item.handle.startswith("fact:"):
            continue
        parts = item.handle.split(":", 2)
        if len(parts) == 3 and parts[2] in names:
            return True
    return False


def _contains_any(text: str, values: tuple[str, ...]) -> bool:
    """大小写不敏感地检查任意关键词。"""
    return any(value.lower() in text for value in values)


def _add_forbidden_output_errors(
    errors: list[dict[str, str]],
    step: StepIntent,
    hint: str,
    produced: str,
    *,
    forbidden: tuple[str, ...],
    code: str,
    message: str,
) -> None:
    """把越界 output 追加为 capability error。"""
    if _contains_any(produced, forbidden):
        errors.append(_capability_error(step, hint, code, message))


def _capability_error(
    step: StepIntent,
    hint: str,
    code: str,
    message: str,
) -> dict[str, str]:
    """构造对 LLM repair 友好的能力对齐错误。"""
    return {
        "step_id": step.step_id,
        "goal_type": step.goal_type,
        "recipe_hint": hint,
        "code": code,
        "message": message,
    }
