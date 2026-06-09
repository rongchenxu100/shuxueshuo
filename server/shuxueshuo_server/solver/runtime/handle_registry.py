"""Canonical handle 注册、校验与安全修正。

这里负责把 LLM ProblemIR 中的 Entity/Fact/Answer handle 建成只读索引，
并只做“父级可见 scope 误写”的确定性修正，不承担 method 绑定。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    answer_aliases: dict[str, str] = field(default_factory=dict)
    handle_aliases: dict[str, str] = field(default_factory=dict)
    handle_valid_scopes: dict[str, str] = field(default_factory=dict)
    entity_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    fact_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_problem_payload(cls, payload: dict[str, Any]) -> "CanonicalHandleRegistry":
        """从 projection 生成的 LLM Problem payload 构建 registry。"""
        _validate_llm_problem_payload_shape(payload)
        scope_ids, scope_parents = _scope_ids_from_payload(payload)
        entity_handles, entity_valid_scopes, entity_payloads = _entity_handles_from_payload(payload, scope_ids)
        fact_handles, fact_types, fact_valid_scopes, fact_payloads = _fact_handles_from_payload(payload, scope_ids)
        answer_handles, answer_value_types, answer_aliases, answer_valid_scopes = _answer_handles_from_payload(
            payload,
            scope_ids,
        )
        initial_handles = entity_handles | fact_handles | answer_handles
        handle_valid_scopes = {
            **entity_valid_scopes,
            **fact_valid_scopes,
            **answer_valid_scopes,
        }
        handle_aliases = _handle_aliases_from_payload(payload, initial_handles)
        return cls(
            scope_ids=frozenset(scope_ids),
            entity_handles=frozenset(entity_handles),
            fact_handles=frozenset(fact_handles),
            answer_handles=frozenset(answer_handles),
            scope_parents=scope_parents,
            fact_types=fact_types,
            answer_value_types=answer_value_types,
            answer_aliases=answer_aliases,
            handle_aliases=handle_aliases,
            handle_valid_scopes=handle_valid_scopes,
            entity_payloads=entity_payloads,
            fact_payloads=fact_payloads,
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


@dataclass(frozen=True)
class ResolvedHandle:
    """CanonicalHandleAliasResolver 的解析结果。"""

    handle: str
    correction: HandleCorrection | None = None


class CanonicalHandleAliasResolver:
    """统一处理 LLM handle 的确定性 alias/canonicalization。

    本类只做 handle 层面的修正，不做 EntityState 补位，也不按编辑距离猜测。
    """

    def resolve(
        self,
        handle: str,
        *,
        field: str,
        step: StepIntent,
        registry: CanonicalHandleRegistry,
        available: set[str],
    ) -> ResolvedHandle:
        """解析一个 handle；无法确定修正时原样返回。"""
        if handle in available:
            return ResolvedHandle(handle=handle)

        answer_alias = self._resolve_answer_alias(
            handle,
            field=field,
            step=step,
            registry=registry,
        )
        if answer_alias is not None:
            return answer_alias
        if field != "reads":
            return ResolvedHandle(handle=handle)

        registered_alias = self._resolve_registered_alias(
            handle,
            field=field,
            step=step,
            registry=registry,
            available=available,
        )
        if registered_alias is not None:
            return registered_alias

        namespace_alias = self._resolve_namespace_alias(
            handle,
            field=field,
            step=step,
            registry=registry,
            available=available,
        )
        if namespace_alias is not None:
            return namespace_alias

        return self._resolve_visible_ancestor_or_point_entity(
            handle,
            field=field,
            step=step,
            registry=registry,
            available=available,
        )

    def _resolve_answer_alias(
        self,
        handle: str,
        *,
        field: str,
        step: StepIntent,
        registry: CanonicalHandleRegistry,
    ) -> ResolvedHandle | None:
        """解析 question_goals 生成的 answer alias。"""
        if not handle.startswith("answer:"):
            return None
        corrected = registry.answer_aliases.get(handle)
        if corrected is None:
            return None
        return ResolvedHandle(
            handle=corrected,
            correction=HandleCorrection(
                step_id=step.step_id,
                scope_id=step.scope_id,
                from_handle=handle,
                to_handle=corrected,
                reason=f"answer_alias:{field}",
            ),
        )

    def _resolve_registered_alias(
        self,
        handle: str,
        *,
        field: str,
        step: StepIntent,
        registry: CanonicalHandleRegistry,
        available: set[str],
    ) -> ResolvedHandle | None:
        """解析 projection/FamilySpec/code-generated 显式 alias。"""
        corrected = registry.handle_aliases.get(handle)
        if corrected is None or corrected not in available:
            return None
        return ResolvedHandle(
            handle=corrected,
            correction=HandleCorrection(
                step_id=step.step_id,
                scope_id=step.scope_id,
                from_handle=handle,
                to_handle=corrected,
                reason=f"registered_alias:{field}",
            ),
        )

    def _resolve_namespace_alias(
        self,
        handle: str,
        *,
        field: str,
        step: StepIntent,
        registry: CanonicalHandleRegistry,
        available: set[str],
    ) -> ResolvedHandle | None:
        """解析 facts:/seg: 这类 namespace 缩写。"""
        corrected = _namespace_alias_handle(handle)
        if corrected == handle:
            return None
        if corrected in available:
            return ResolvedHandle(
                handle=corrected,
                correction=HandleCorrection(
                    step_id=step.step_id,
                    scope_id=step.scope_id,
                    from_handle=handle,
                    to_handle=corrected,
                    reason=f"namespace_alias:{field}",
                ),
            )
        return self._resolve_visible_ancestor_or_point_entity(
            corrected,
            field=field,
            step=step,
            registry=registry,
            available=available,
            original_handle=handle,
            reason_prefix="namespace_alias",
        )

    def _resolve_visible_ancestor_or_point_entity(
        self,
        handle: str,
        *,
        field: str,
        step: StepIntent,
        registry: CanonicalHandleRegistry,
        available: set[str],
        original_handle: str | None = None,
        reason_prefix: str | None = None,
    ) -> ResolvedHandle:
        """修正唯一可见父级 handle，或 fact namespace 误写的点实体。"""
        from_handle = original_handle or handle
        parsed = _parse_scoped_non_answer_handle(handle)
        if parsed is None:
            return ResolvedHandle(handle=from_handle)
        kind, written_scope, name = parsed
        visible_scopes = registry.ancestor_scopes(step.scope_id)
        if written_scope not in visible_scopes:
            return ResolvedHandle(handle=from_handle)
        written_index = visible_scopes.index(written_scope)

        if kind == "fact":
            entity_correction = self._resolve_fact_as_point_entity(
                written_index=written_index,
                name=name,
                visible_scopes=visible_scopes,
                available=available,
                step=step,
                from_handle=from_handle,
                reason_prefix=reason_prefix,
            )
            if entity_correction is not None:
                return entity_correction

        candidates = [
            f"{kind}:{scope_id}:{name}"
            for scope_id in visible_scopes[written_index + 1:]
            if f"{kind}:{scope_id}:{name}" in available
        ]
        if len(candidates) != 1:
            return ResolvedHandle(handle=from_handle)

        corrected = candidates[0]
        reason = "visible_ancestor_scope"
        if reason_prefix is not None:
            reason = f"{reason_prefix}:{reason}"
        return ResolvedHandle(
            handle=corrected,
            correction=HandleCorrection(
                step_id=step.step_id,
                scope_id=step.scope_id,
                from_handle=from_handle,
                to_handle=corrected,
                reason=f"{reason}:{field}",
            ),
        )

    def _resolve_fact_as_point_entity(
        self,
        *,
        written_index: int,
        name: str,
        visible_scopes: tuple[str, ...],
        available: set[str],
        step: StepIntent,
        from_handle: str,
        reason_prefix: str | None,
    ) -> ResolvedHandle | None:
        """把 fact:<scope>:O 这类 exact-name 点实体误写修正为 point:<scope>:O。"""
        candidates = [
            f"point:{scope_id}:{name}"
            for scope_id in visible_scopes[written_index:]
            if f"point:{scope_id}:{name}" in available
        ]
        if len(candidates) != 1:
            return None
        corrected = candidates[0]
        reason = "fact_namespace_for_point_entity"
        if reason_prefix is not None:
            reason = f"{reason_prefix}:{reason}"
        return ResolvedHandle(
            handle=corrected,
            correction=HandleCorrection(
                step_id=step.step_id,
                scope_id=step.scope_id,
                from_handle=from_handle,
                to_handle=corrected,
                reason=reason,
            ),
        )


class HandleResolver:
    """对整个 StepIntentDraft 做 handle 修正与数据流维护。

    单个 handle 的 alias/canonicalization 委托给
    ``CanonicalHandleAliasResolver``；这里负责遍历 draft、维护前序
    creates/produces 可读集合，以及收窄过宽 produced fact。
    """

    def resolve_draft(
        self,
        draft: StepIntentDraft,
        registry: CanonicalHandleRegistry,
    ) -> tuple[StepIntentDraft, HandleResolutionReport]:
        """返回修正后的 draft 与修正报告。"""
        available = set(registry.initial_handles)
        handle_valid_scopes = dict(registry.handle_valid_scopes)
        handle_rewrites: dict[str, str] = {}
        corrections: list[HandleCorrection] = []
        scopes: list[StepIntentScope] = []
        alias_resolver = CanonicalHandleAliasResolver()

        for scope in draft.scopes:
            steps: list[StepIntent] = []
            for step in scope.steps:
                step = _rewrite_step_handles(step, handle_rewrites)
                step, alias_corrections = self._resolve_handle_aliases(
                    step,
                    registry=registry,
                    available=available,
                    alias_resolver=alias_resolver,
                )
                corrections.extend(alias_corrections)
                step, create_corrections = self._move_existing_entities_to_reads(
                    step,
                    registry=registry,
                    available=available,
                )
                corrections.extend(create_corrections)
                corrected_step = step
                corrected_step, scope_corrections, produce_rewrites = self._narrow_overbroad_produced_facts(
                    corrected_step,
                    registry=registry,
                    handle_valid_scopes=handle_valid_scopes,
                )
                corrections.extend(scope_corrections)
                handle_rewrites.update(produce_rewrites)
                steps.append(corrected_step)

                # 修正后续 step 时，需要知道前序 creates/produces 已经可读。
                available.update(item.handle for item in step.creates)
                available.update(item.handle for item in corrected_step.creates)
                available.update(item.handle for item in corrected_step.produces)
                handle_valid_scopes.update(
                    {item.handle: item.valid_scope for item in corrected_step.creates}
                )
                handle_valid_scopes.update(
                    {item.handle: item.valid_scope for item in corrected_step.produces}
                )

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

    def _narrow_overbroad_produced_facts(
        self,
        step: StepIntent,
        *,
        registry: CanonicalHandleRegistry,
        handle_valid_scopes: dict[str, str],
    ) -> tuple[StepIntent, list[HandleCorrection], dict[str, str]]:
        """收窄被 LLM 误写成父级公共结论的 produced fact。

        若某个 step 在 ``i`` / ``ii_1`` 等局部 scope 中读取了局部条件，却把产物
        写成过宽的公共 fact，这个 fact 不应被后续其它分问当作公共结论。这里选择
        “所有 reads 都可见的最大安全 scope”，并同步改写 fact handle 的 scope 前缀。
        """
        if not step.produces:
            return step, [], {}

        new_produces: list[ProducedFact] = []
        corrections: list[HandleCorrection] = []
        rewrites: dict[str, str] = {}
        for item in step.produces:
            if not item.handle.startswith("fact:"):
                new_produces.append(item)
                continue
            if step.scope_id == "problem":
                new_produces.append(item)
                continue
            safe_scope = self._max_safe_valid_scope(
                step,
                requested_scope=item.valid_scope,
                registry=registry,
                handle_valid_scopes=handle_valid_scopes,
            )
            if safe_scope == item.valid_scope:
                new_produces.append(item)
                continue
            _kind, _scope, name = _require_scoped_handle(item.handle)
            new_handle = f"fact:{safe_scope}:{name}"
            new_item = replace(item, handle=new_handle, valid_scope=safe_scope)
            new_produces.append(new_item)
            rewrites[item.handle] = new_handle
            corrections.append(
                HandleCorrection(
                    step_id=step.step_id,
                    scope_id=step.scope_id,
                    from_handle=item.handle,
                    to_handle=new_handle,
                    reason=(
                        "produced fact depended on narrower-scope reads; narrowed handle "
                        f"and valid_scope from {item.valid_scope} to {safe_scope}"
                    ),
                )
            )

        if not corrections:
            return step, [], {}

        return (
            replace(
                step,
                target=rewrites.get(step.target, step.target),
                produces=tuple(new_produces),
            ),
            corrections,
            rewrites,
        )

    def _max_safe_valid_scope(
        self,
        step: StepIntent,
        *,
        requested_scope: str,
        registry: CanonicalHandleRegistry,
        handle_valid_scopes: dict[str, str],
    ) -> str:
        """返回不超过 requested_scope 且能读取本 step 依赖的最大安全 scope。"""
        try:
            step_chain = registry.ancestor_scopes(step.scope_id)
            requested_index = step_chain.index(requested_scope)
        except StrategyDraftValidationError:
            return requested_scope
        except ValueError:
            return requested_scope
        candidates = step_chain[: requested_index + 1]
        read_scopes = [
            handle_valid_scopes[handle]
            for handle in step.reads
            if handle in handle_valid_scopes
        ]
        for scope_id in reversed(candidates):
            if all(read_scope in registry.ancestor_scopes(scope_id) for read_scope in read_scopes):
                return scope_id
        return step.scope_id

    def _resolve_handle_aliases(
        self,
        step: StepIntent,
        *,
        registry: CanonicalHandleRegistry,
        available: set[str],
        alias_resolver: CanonicalHandleAliasResolver,
    ) -> tuple[StepIntent, list[HandleCorrection]]:
        """统一修正 target/reads/produces 中可确定的 handle alias。"""
        corrections: list[HandleCorrection] = []

        def resolve(handle: str, *, field: str) -> str:
            resolved = alias_resolver.resolve(
                handle,
                field=field,
                step=step,
                registry=registry,
                available=available,
            )
            if resolved.correction is not None:
                corrections.append(resolved.correction)
            return resolved.handle

        target = resolve(step.target, field="target")
        reads = tuple(resolve(handle, field="reads") for handle in step.reads)
        produces = tuple(
            replace(item, handle=resolve(item.handle, field="produces"))
            for item in step.produces
        )
        if not corrections:
            return step, []
        return (
            StepIntent(
                scope_id=step.scope_id,
                step_id=step.step_id,
                recipe_hint=step.recipe_hint,
                goal_type=step.goal_type,
                target=target,
                strategy=step.strategy,
                reads=reads,
                creates=step.creates,
                produces=produces,
                reason=step.reason,
            ),
            corrections,
        )

    def _move_existing_entities_to_reads(
        self,
        step: StepIntent,
        *,
        registry: CanonicalHandleRegistry,
        available: set[str],
    ) -> tuple[StepIntent, list[HandleCorrection]]:
        """把误放到 creates[] 的已有实体改成 reads[]。

        ``creates`` 只应声明推导中新建的辅助实体。若 LLM 把题面已有的点/线放进
        ``creates``，这不是数学步骤，而是字段放错；可以安全移动到 reads，避免
        后续 validator 报 ``create_overwrites_given_entity``。若前序 step 已创建同一
        auxiliary entity，后续重复 creates 也可安全移动到 reads。这里不修正
        produces，也不把未知 entity 伪造成题设 entity。
        """
        if not step.creates:
            return step, []

        reads = list(step.reads)
        creates: list[CreatedEntity] = []
        corrections: list[HandleCorrection] = []
        for item in step.creates:
            if item.handle not in registry.entity_handles and item.handle not in available:
                creates.append(item)
                continue
            if item.handle not in reads:
                reads.append(item.handle)
            reason = (
                "duplicate_created_entity_already_available; moved to reads"
                if item.handle in available and item.handle not in registry.entity_handles
                else "created entity already exists in canonical ProblemIR; moved to reads"
            )
            corrections.append(
                HandleCorrection(
                    step_id=step.step_id,
                    scope_id=step.scope_id,
                    from_handle=f"creates:{item.handle}",
                    to_handle=item.handle,
                    reason=reason,
                )
            )

        if not corrections:
            return step, []

        return (
            StepIntent(
                scope_id=step.scope_id,
                step_id=step.step_id,
                recipe_hint=step.recipe_hint,
                goal_type=step.goal_type,
                target=step.target,
                strategy=step.strategy,
                reads=tuple(reads),
                creates=tuple(creates),
                produces=step.produces,
                reason=step.reason,
            ),
            corrections,
        )

def _rewrite_step_handles(step: StepIntent, rewrites: dict[str, str]) -> StepIntent:
    """把前序 produced fact 改名同步到后续 step。"""
    if not rewrites:
        return step
    return StepIntent(
        scope_id=step.scope_id,
        step_id=step.step_id,
        recipe_hint=step.recipe_hint,
        goal_type=step.goal_type,
        target=rewrites.get(step.target, step.target),
        strategy=step.strategy,
        reads=tuple(rewrites.get(handle, handle) for handle in step.reads),
        creates=step.creates,
        produces=tuple(
            replace(item, handle=rewrites.get(item.handle, item.handle))
            for item in step.produces
        ),
        reason=step.reason,
    )

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
) -> tuple[set[str], dict[str, str], dict[str, dict[str, Any]]]:
    """读取并校验 entities[].handle。"""
    handles: set[str] = set()
    valid_scopes: dict[str, str] = {}
    payloads: dict[str, dict[str, Any]] = {}
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
        payloads[handle] = dict(item)
    return handles, valid_scopes, payloads


def _fact_handles_from_payload(
    payload: dict[str, Any],
    scope_ids: set[str],
) -> tuple[set[str], dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
    """读取并校验 facts[].handle，同时保存题设 fact 类型。"""
    handles: set[str] = set()
    types: dict[str, str] = {}
    valid_scopes: dict[str, str] = {}
    payloads: dict[str, dict[str, Any]] = {}
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
        payloads[handle] = dict(item)
    return handles, types, valid_scopes, payloads


def _answer_handles_from_payload(
    payload: dict[str, Any],
    scope_ids: set[str],
) -> tuple[set[str], dict[str, str], dict[str, str], dict[str, str]]:
    """读取并校验 question_goals[].handle，同时保存答案值类型。"""
    handles: set[str] = set()
    value_types: dict[str, str] = {}
    aliases: dict[str, str] = {}
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
        valid_scope = item.get("valid_scope", scope_id)
        if not isinstance(valid_scope, str) or not valid_scope.strip():
            raise StrategyDraftValidationError(
                f"LLM ProblemIR question_goals[{index}].valid_scope must be a string when provided"
            )
        valid_scope = valid_scope.strip()
        if scope_id not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR question_goals[{index}] unknown scope_id: {scope_id}"
            )
        if valid_scope not in scope_ids:
            raise StrategyDraftValidationError(
                f"LLM ProblemIR question_goals[{index}] unknown valid_scope: {valid_scope}"
            )
        if handle in handles:
            raise StrategyDraftValidationError(f"duplicate answer handle in LLM ProblemIR: {handle}")
        handles.add(handle)
        value_type = item.get("value_type")
        if isinstance(value_type, str) and value_type.strip():
            value_types[handle] = value_type.strip()
        answer_key = item.get("answer_key")
        if isinstance(answer_key, str) and answer_key.strip():
            _add_answer_alias(aliases, handles, f"answer:{scope_id}.{answer_key.strip()}", handle)
            _add_answer_alias(aliases, handles, f"answer:{scope_id}_{answer_key.strip()}", handle)
        valid_scopes[handle] = valid_scope
    return handles, value_types, aliases, valid_scopes


def _handle_aliases_from_payload(
    payload: dict[str, Any],
    handles: set[str],
) -> dict[str, str]:
    """读取 entities/facts/question_goals 上可选的 aliases[]。"""
    aliases: dict[str, str] = {}
    for collection in ("entities", "facts", "question_goals"):
        raw_items = payload.get(collection, [])
        if not isinstance(raw_items, list):
            continue
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            canonical = item.get("handle")
            if not isinstance(canonical, str) or canonical not in handles:
                continue
            raw_aliases = item.get("aliases", ())
            if raw_aliases in (None, ()):
                continue
            if not isinstance(raw_aliases, list):
                raise StrategyDraftValidationError(
                    f"LLM ProblemIR {collection}[{index}].aliases must be a list when provided"
                )
            for raw_alias in raw_aliases:
                if not isinstance(raw_alias, str) or not raw_alias.strip():
                    raise StrategyDraftValidationError(
                        f"LLM ProblemIR {collection}[{index}].aliases must contain strings"
                    )
                _add_handle_alias(aliases, handles, raw_alias.strip(), canonical)
    return aliases


def _add_answer_alias(
    aliases: dict[str, str],
    handles: set[str],
    alias: str,
    canonical: str,
) -> None:
    """注册唯一 answer alias；已有 canonical handle 不需要 alias。"""
    _add_handle_alias(aliases, handles, alias, canonical)


def _add_handle_alias(
    aliases: dict[str, str],
    handles: set[str],
    alias: str,
    canonical: str,
) -> None:
    """注册唯一 handle alias；冲突 alias 会被删除，避免猜测。"""
    if alias == canonical or alias in handles:
        return
    if alias in aliases and aliases[alias] != canonical:
        aliases.pop(alias, None)
        return
    aliases[alias] = canonical


def _required_payload_string(item: dict[str, Any], key: str, label: str) -> str:
    """读取 LLM ProblemIR 中的必填字符串字段。"""
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StrategyDraftValidationError(f"LLM ProblemIR {label}.{key} must be a string")
    return value.strip()


def _namespace_alias_handle(handle: str) -> str:
    """把常见 namespace 缩写临时转为 canonical 形态。

    这只发生在 reads 修正阶段；只有修正后能命中已存在 handle 或唯一可见父级
    handle 时，CanonicalHandleAliasResolver 才会真正接受。
    """
    if handle.startswith("facts:"):
        return "fact:" + handle[len("facts:"):]
    if handle.startswith("seg:"):
        return "segment:" + handle[len("seg:"):]
    return handle


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
