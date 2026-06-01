"""Canonical handle 注册、校验与安全修正。

这里负责把 LLM ProblemIR 中的 Entity/Fact/Answer handle 建成只读索引，
并只做“父级可见 scope 误写”的确定性修正，不承担 method 绑定。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
    HandleCorrection,
    HandleResolutionReport,
    ProducedFact,
    StepIntent,
    StepIntentDraft,
    StepIntentScope,
    StrategyDraftValidationError,
)

_ENTITY_TYPES = frozenset(
    ("point", "line", "segment", "ray", "function", "symbol", "angle", "circle", "polygon")
)
_ENTITY_HANDLE_RE = re.compile(
    r"^(?P<kind>point|line|segment|ray|function|symbol|angle|circle|polygon):"
    r"(?P<scope>[A-Za-z0-9_]+):(?P<name>[A-Za-z0-9_]+)$"
)
_FACT_HANDLE_RE = re.compile(r"^fact:(?P<scope>[A-Za-z0-9_]+):(?P<name>[A-Za-z0-9_]+)$")
_ANSWER_HANDLE_RE = re.compile(r"^answer:[A-Za-z0-9_.]+$")
_NON_CANONICAL_PREFIXES = (
    "relation:",
    "condition:",
    "constraint:",
    "value:",
)
_LEGACY_LLM_PROBLEM_KEYS = {
    "relations",
    "points",
    "target_path",
    "expected",
    "expected_answers",
}


@dataclass(frozen=True)
class CanonicalHandleRegistry:
    """LLM ProblemIR 中 Entity / Fact / answer handle 的唯一索引。

    Strategy Planner 阶段不再让 LLM 自由发明 ``condition:*``、``point:D`` 这类
    名字。所有可读取的题设对象都必须来自这个 registry；推导中新产生的实体或
    fact 也必须遵守同一套命名规则。
    """

    scope_ids: frozenset[str]
    entity_handles: frozenset[str]
    fact_handles: frozenset[str]
    answer_handles: frozenset[str]
    scope_parents: dict[str, str | None] = field(default_factory=dict)
    fact_types: dict[str, str] = field(default_factory=dict)
    answer_value_types: dict[str, str] = field(default_factory=dict)
    handle_valid_scopes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_problem_payload(cls, payload: dict[str, Any]) -> "CanonicalHandleRegistry":
        """从 ``*.llm.json`` 构建 registry，并同步校验输入边界。"""
        _validate_llm_problem_payload_shape(payload)
        scope_ids, scope_parents = _scope_ids_from_payload(payload)
        entity_handles, entity_valid_scopes = _entity_handles_from_payload(payload, scope_ids)
        fact_handles, fact_types, fact_valid_scopes = _fact_handles_from_payload(payload, scope_ids)
        answer_handles, answer_value_types, answer_valid_scopes = _answer_handles_from_payload(payload, scope_ids)
        handle_valid_scopes = {
            **entity_valid_scopes,
            **fact_valid_scopes,
            **answer_valid_scopes,
        }
        return cls(
            scope_ids=frozenset(scope_ids),
            entity_handles=frozenset(entity_handles),
            fact_handles=frozenset(fact_handles),
            answer_handles=frozenset(answer_handles),
            scope_parents=scope_parents,
            fact_types=fact_types,
            answer_value_types=answer_value_types,
            handle_valid_scopes=handle_valid_scopes,
        )

    @property
    def initial_handles(self) -> frozenset[str]:
        """题面一开始已经存在、LLM 可以在 reads 中引用的 handle。"""
        return self.entity_handles | self.fact_handles | self.answer_handles

    def validate_scope(self, scope_id: str, *, context: str) -> None:
        """校验 scope 是否来自 LLM ProblemIR 的 scopes[]。"""
        if scope_id not in self.scope_ids:
            raise StrategyDraftValidationError(
                f"unknown_scope: {context} uses {scope_id!r}; available_scopes={sorted(self.scope_ids)}"
            )

    def ancestor_scopes(self, scope_id: str) -> tuple[str, ...]:
        """返回从当前 scope 到根 scope 的可见父链。

        例如 ``ii_1`` 会返回 ``("ii_1", "ii", "problem")``。HandleResolver
        只会把误写到当前 scope 的读入 handle 修正到这条父链中的已有 handle，不会跨
        sibling scope 猜测。
        """
        self.validate_scope(scope_id, context="ancestor lookup")
        result: list[str] = []
        current: str | None = scope_id
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise StrategyDraftValidationError(
                    f"scope_parent_cycle: {scope_id} reaches {current}"
                )
            seen.add(current)
            result.append(current)
            current = self.scope_parents.get(current)
        return tuple(result)

class HandleResolver:
    """对 LLM reads handle 做最小安全修正。

    它不是 fuzzy matcher，也不做语义猜测。唯一支持的自动修正是：LLM 把一个已经
    存在于父级可见 scope 的 Entity/Fact handle 误写成当前 step scope。典型例子：

    ``fact:ii_1:path_minimum_target`` -> ``fact:ii:path_minimum_target``
    ``point:ii:D`` -> ``point:problem:D``

    这能减少无意义 repair 轮次，同时仍保留严格边界：answer 不修正、sibling 不修正、
    多候选不修正、语义名不一致不修正。
    """

    def resolve_draft(
        self,
        draft: StepIntentDraft,
        registry: CanonicalHandleRegistry,
    ) -> tuple[StepIntentDraft, HandleResolutionReport]:
        """返回修正后的 draft 与修正报告。"""
        available = set(registry.initial_handles)
        corrections: list[HandleCorrection] = []
        scopes: list[StepIntentScope] = []

        for scope in draft.scopes:
            steps: list[StepIntent] = []
            for step in scope.steps:
                corrected_reads: list[str] = []
                for handle in step.reads:
                    corrected = self._resolve_read_handle(
                        handle,
                        step=step,
                        registry=registry,
                        available=available,
                    )
                    corrected_reads.append(corrected.handle)
                    if corrected.correction is not None:
                        corrections.append(corrected.correction)
                corrected_step = StepIntent(
                    scope_id=step.scope_id,
                    step_id=step.step_id,
                    recipe_hint=step.recipe_hint,
                    goal_type=step.goal_type,
                    target=step.target,
                    strategy=step.strategy,
                    reads=tuple(corrected_reads),
                    creates=step.creates,
                    produces=step.produces,
                    reason=step.reason,
                )
                steps.append(corrected_step)

                # 修正后续 step 时，需要知道前序 creates/produces 已经可读。
                available.update(item.handle for item in step.creates)
                available.update(item.handle for item in step.produces)

            scopes.append(
                StepIntentScope(
                    scope_id=scope.scope_id,
                    label=scope.label,
                    steps=tuple(steps),
                )
            )

        return (
            StepIntentDraft(scopes=tuple(scopes)),
            HandleResolutionReport(corrections=tuple(corrections)),
        )

    def _resolve_read_handle(
        self,
        handle: str,
        *,
        step: StepIntent,
        registry: CanonicalHandleRegistry,
        available: set[str],
    ) -> "_ResolvedReadHandle":
        """尝试把当前 scope 误写修正到可见父 scope。"""
        if handle in available:
            return _ResolvedReadHandle(handle=handle)

        parsed = _parse_scoped_non_answer_handle(handle)
        if parsed is None:
            return _ResolvedReadHandle(handle=handle)
        kind, written_scope, name = parsed
        visible_scopes = registry.ancestor_scopes(step.scope_id)
        if written_scope not in visible_scopes:
            return _ResolvedReadHandle(handle=handle)
        written_index = visible_scopes.index(written_scope)

        candidates: list[str] = []
        # 当前/中间 scope 已确认不存在同名可读 handle，只继续向更高父级查找；
        # 不反向修正到子 scope，也不跨 sibling。
        for scope_id in visible_scopes[written_index + 1:]:
            candidate = f"{kind}:{scope_id}:{name}"
            if candidate in available:
                candidates.append(candidate)

        if len(candidates) != 1:
            return _ResolvedReadHandle(handle=handle)

        corrected = candidates[0]
        return _ResolvedReadHandle(
            handle=corrected,
            correction=HandleCorrection(
                step_id=step.step_id,
                scope_id=step.scope_id,
                from_handle=handle,
                to_handle=corrected,
                reason="same semantic handle exists in a visible ancestor scope",
            ),
        )


@dataclass(frozen=True)
class _ResolvedReadHandle:
    """HandleResolver 内部使用的读取结果。"""

    handle: str
    correction: HandleCorrection | None = None

def _require_scoped_handle(handle: str) -> tuple[str, str, str]:
    """解析 canonical Entity/Fact handle。

    返回 ``(kind, scope_id, name)``。这里不接受 ``answer:*``，因为 answer 的真实
    runtime path 必须从 QuestionGoal 读取。
    """
    parsed = _parse_scoped_non_answer_handle(handle)
    if parsed is None:
        raise StrategyDraftValidationError(f"not_a_scoped_handle: {handle}")
    return parsed


def _handle_scope(handle: str) -> str:
    """读取 canonical handle 中的 scope。"""
    return _require_scoped_handle(handle)[1]


def _handle_name(handle: str) -> str:
    """读取 Entity handle 的 name。"""
    return _require_scoped_handle(handle)[2]


def _semantic_name(handle: str) -> str:
    """读取 Fact handle 的 semantic_name。"""
    return _require_scoped_handle(handle)[2]

def _validate_llm_problem_payload_shape(payload: dict[str, Any]) -> None:
    """校验 LLM ProblemIR 的输入边界。

    这个 JSON 是 LLM 读题事实源，不应该夹带旧 solver fixture 的工程字段，例如
    ``relations``、``target_path`` 或 expected answer。
    """
    required = {"original_text", "scopes", "entities", "facts", "question_goals"}
    missing = sorted(required - set(payload))
    if missing:
        raise StrategyDraftValidationError(
            "LLM ProblemIR missing required fields: " + ", ".join(missing)
        )
    _reject_legacy_llm_problem_keys(payload)
    for key in ("scopes", "entities", "facts", "question_goals"):
        if not isinstance(payload.get(key), list):
            raise StrategyDraftValidationError(f"LLM ProblemIR {key} must be a list")


def _reject_legacy_llm_problem_keys(value: Any, *, path: str = "$") -> None:
    """递归拒绝会让 LLM 误以为自己能读旧 runtime 结构的字段。"""
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in _LEGACY_LLM_PROBLEM_KEYS:
                raise StrategyDraftValidationError(
                    f"LLM ProblemIR contains forbidden legacy field {path}.{key}"
                )
            _reject_legacy_llm_problem_keys(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_legacy_llm_problem_keys(child, path=f"{path}[{index}]")


def _scope_ids_from_payload(payload: dict[str, Any]) -> tuple[set[str], dict[str, str | None]]:
    """读取并校验 scopes[]，同时保留 scope 父子关系。"""
    scope_ids: set[str] = set()
    scope_parents: dict[str, str | None] = {}
    for index, item in enumerate(payload["scopes"]):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(f"LLM ProblemIR scopes[{index}] must be an object")
        scope_id = item.get("scope_id")
        if not isinstance(scope_id, str) or not scope_id.strip():
            raise StrategyDraftValidationError(
                f"LLM ProblemIR scopes[{index}].scope_id must be a string"
            )
        if scope_id in scope_ids:
            raise StrategyDraftValidationError(f"duplicate scope_id in LLM ProblemIR: {scope_id}")
        scope_ids.add(scope_id)
        parent = item.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise StrategyDraftValidationError(
                f"LLM ProblemIR scopes[{index}].parent must be null or string"
            )
        scope_parents[scope_id] = parent
    for index, item in enumerate(payload["scopes"]):
        parent = item.get("parent")
        if isinstance(parent, str) and parent not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR scopes[{index}] references unknown parent scope: {parent}"
            )
    return scope_ids, scope_parents


def _entity_handles_from_payload(
    payload: dict[str, Any],
    scope_ids: set[str],
) -> tuple[set[str], dict[str, str]]:
    """读取并校验 entities[].handle。"""
    handles: set[str] = set()
    valid_scopes: dict[str, str] = {}
    for index, item in enumerate(payload["entities"]):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(f"LLM ProblemIR entities[{index}] must be an object")
        handle = _required_payload_string(item, "handle", f"entities[{index}]")
        entity_type = _required_payload_string(item, "entity_type", f"entities[{index}]")
        scope_id = _required_payload_string(item, "scope_id", f"entities[{index}]")
        if entity_type not in _ENTITY_TYPES:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR entities[{index}] unknown entity_type: {entity_type}"
            )
        match = _ENTITY_HANDLE_RE.fullmatch(handle)
        if match is None:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR entities[{index}].handle is not canonical: {handle}"
            )
        if match.group("kind") != entity_type:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR entities[{index}] handle/type mismatch: {handle} vs {entity_type}"
            )
        if match.group("scope") != scope_id:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR entities[{index}] handle/scope mismatch: {handle} vs {scope_id}"
            )
        if scope_id not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR entities[{index}] unknown scope_id: {scope_id}"
            )
        if handle in handles:
            raise StrategyDraftValidationError(f"duplicate entity handle in LLM ProblemIR: {handle}")
        handles.add(handle)
        valid_scopes[handle] = scope_id
    return handles, valid_scopes


def _fact_handles_from_payload(
    payload: dict[str, Any],
    scope_ids: set[str],
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    """读取并校验 facts[].handle，同时保存题设 fact 类型。"""
    handles: set[str] = set()
    types: dict[str, str] = {}
    valid_scopes: dict[str, str] = {}
    for index, item in enumerate(payload["facts"]):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(f"LLM ProblemIR facts[{index}] must be an object")
        handle = _required_payload_string(item, "handle", f"facts[{index}]")
        scope_id = _required_payload_string(item, "scope_id", f"facts[{index}]")
        valid_scope = _required_payload_string(item, "valid_scope", f"facts[{index}]")
        match = _FACT_HANDLE_RE.fullmatch(handle)
        if match is None:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR facts[{index}].handle is not canonical: {handle}"
            )
        if match.group("scope") != scope_id:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR facts[{index}] handle/scope mismatch: {handle} vs {scope_id}"
            )
        if scope_id not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR facts[{index}] unknown scope_id: {scope_id}"
            )
        if valid_scope not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR facts[{index}] unknown valid_scope: {valid_scope}"
            )
        if handle in handles:
            raise StrategyDraftValidationError(f"duplicate fact handle in LLM ProblemIR: {handle}")
        handles.add(handle)
        fact_type = item.get("type")
        if isinstance(fact_type, str) and fact_type.strip():
            types[handle] = fact_type.strip()
        valid_scopes[handle] = valid_scope
    return handles, types, valid_scopes


def _answer_handles_from_payload(
    payload: dict[str, Any],
    scope_ids: set[str],
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    """读取并校验 question_goals[].handle，同时保存答案值类型。"""
    handles: set[str] = set()
    value_types: dict[str, str] = {}
    valid_scopes: dict[str, str] = {}
    for index, item in enumerate(payload["question_goals"]):
        if not isinstance(item, dict):
            raise StrategyDraftValidationError(
                f"LLM ProblemIR question_goals[{index}] must be an object"
            )
        handle = _required_payload_string(item, "handle", f"question_goals[{index}]")
        scope_id = _required_payload_string(item, "scope_id", f"question_goals[{index}]")
        if _ANSWER_HANDLE_RE.fullmatch(handle) is None:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR question_goals[{index}].handle is not canonical: {handle}"
            )
        if scope_id not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR question_goals[{index}] unknown scope_id: {scope_id}"
            )
        if handle in handles:
            raise StrategyDraftValidationError(f"duplicate answer handle in LLM ProblemIR: {handle}")
        handles.add(handle)
        value_type = item.get("value_type")
        if isinstance(value_type, str) and value_type.strip():
            value_types[handle] = value_type.strip()
        valid_scopes[handle] = scope_id
    return handles, value_types, valid_scopes


def _required_payload_string(item: dict[str, Any], key: str, label: str) -> str:
    """读取 LLM ProblemIR 中的必填字符串字段。"""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(f"LLM ProblemIR {label}.{key} must be a string")
    return value.strip()

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

def _handle_suggestions(handle: str, available: set[str]) -> list[str]:
    """根据前缀给 repair prompt 友好的候选提示。"""
    prefix = handle.split(":", 1)[0] + ":"
    matched = sorted(item for item in available if item.startswith(prefix))
    return matched[:12] if matched else sorted(available)[:12]
