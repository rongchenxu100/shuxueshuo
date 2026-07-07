"""Strategy Planner 的数据模型与 JSON schema。

本模块只保存 LLM StepIntent 草稿、校验报告和 executable candidate 报告等
轻量数据结构，不依赖 runtime context 或 method 执行层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from shuxueshuo_server.solver.runtime.handle_alias_index import SEMANTIC_READ_KIND_ORDER

STEP_INTENT_OUTPUT_TYPES: tuple[str, ...] = (
    "AngleEquality",
    "Coefficients",
    "Equation",
    "Expression",
    "Line",
    "MinimumExpression",
    "Parabola",
    "ParameterValue",
    "PathTransformation",
    "Point",
    "PointList",
    "StraighteningCandidate",
)


def answer_output_type_compatible(expected_type: str | None, actual_type: str | None) -> bool:
    """判断 StepIntent answer 产物类型能否满足 QuestionGoal 类型。

    题目解析阶段可能只知道“求点 E”，但不知道最后会有两个候选坐标。因此
    ``PointList`` 可以满足 ``Point`` 型答案目标；其它类型继续严格匹配。
    """
    if expected_type is None or actual_type is None:
        return True
    if expected_type == actual_type:
        return True
    return expected_type == "Point" and actual_type == "PointList"


@dataclass(frozen=True)
class CreatedEntity:
    """StepIntent 在推导过程中声明的新实体。

    这里的实体只表示“题设之外新出现的对象”，例如辅助点、辅助线。它不承载坐标、
    方程或答案值；这些数值性结论必须通过 ``ProducedFact`` 表达。
    """

    handle: str
    entity_type: str
    valid_scope: str
    description: str = ""

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        return {
            "handle": self.handle,
            "entity_type": self.entity_type,
            "valid_scope": self.valid_scope,
            "description": self.description,
        }


@dataclass(frozen=True)
class ProducedFact:
    """StepIntent 产生的一条新事实或最终答案。

    ``handle`` 只能是 ``fact:<scope>:<semantic_name>`` 或
    ``answer:<QuestionGoal.id>``。后续 step 复用时直接在 ``reads`` 中引用该 handle，
    不再引入 ``@step`` 临时输出。
    """

    handle: str
    valid_scope: str
    description: str = ""
    output_type: str | None = None

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        payload = {
            "handle": self.handle,
            "valid_scope": self.valid_scope,
            "description": self.description,
        }
        if self.output_type is not None:
            payload["output_type"] = self.output_type
        return payload


@dataclass(frozen=True)
class SemanticRef:
    """LLM-facing semantic read reference.

    ``SemanticRef`` is only accepted at the raw JSON boundary. It is resolved to
    canonical ``StepIntent.reads`` before runtime validation and execution.
    """

    ref: str
    kind: str
    value_type: str | None = None
    from_step: str | None = None

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        payload = {
            "ref": self.ref,
            "kind": self.kind,
        }
        if self.value_type is not None:
            payload["value_type"] = self.value_type
        if self.from_step is not None:
            payload["from_step"] = self.from_step
        return payload


@dataclass(frozen=True)
class StepIntent:
    """LLM 输出的一步“解题意图”。

    它不是可执行计划，也不是 method invocation。字段全部使用自然语言或语义
    handle，后续阶段才会由代码解析为 method/recipe 候选和实际 ContextPath。
    """

    scope_id: str
    step_id: str
    recipe_hint: str | None
    goal_type: str
    target: str
    strategy: str
    reads: tuple[str, ...] = ()
    creates: tuple[CreatedEntity, ...] = ()
    produces: tuple[ProducedFact, ...] = ()
    reason: str = ""

    def to_payload(self, *, include_scope_id: bool = True) -> dict[str, Any]:
        """转成 JSON 友好的 dict，便于 debug artifact 落盘。"""
        payload = {
            "step_id": self.step_id,
            "recipe_hint": self.recipe_hint,
            "goal_type": self.goal_type,
            "target": self.target,
            "strategy": self.strategy,
            "reads": list(self.reads),
            "creates": [item.to_payload() for item in self.creates],
            "produces": [item.to_payload() for item in self.produces],
            "reason": self.reason,
        }
        if include_scope_id:
            payload["scope_id"] = self.scope_id
        return payload


@dataclass(frozen=True)
class StepIntentScope:
    """某个 question/subquestion scope 下的一组 StepIntent。"""

    scope_id: str
    label: str
    steps: tuple[StepIntent, ...]

    def to_payload(self) -> dict[str, Any]:
        """转成与 LLM 输出一致的 scoped JSON。"""
        return {
            "scope_id": self.scope_id,
            "label": self.label,
            "steps": [
                step.to_payload(include_scope_id=False)
                for step in self.steps
            ],
        }


@dataclass(frozen=True)
class StepIntentDraft:
    """一次 LLM 返回的 StepIntent 列表。"""

    scopes: tuple[StepIntentScope, ...]

    @property
    def steps(self) -> tuple[StepIntent, ...]:
        """按输出顺序展开所有 scope 下的 steps。"""
        return tuple(step for scope in self.scopes for step in scope.steps)

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好的 dict。"""
        return {"scopes": [scope.to_payload() for scope in self.scopes]}


@dataclass(frozen=True)
class StrategyPrompt:
    """Jinja 渲染后的 Chat messages。"""

    system: str
    user: str

    @property
    def messages(self) -> list[dict[str, str]]:
        """OpenAI-compatible Chat Completions 可直接消费的 messages。"""
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


@dataclass(frozen=True)
class RecipeAlignmentReport:
    """recipe_hint 与 family recipe/method 菜单的对齐报告。

    这份报告只用于 probe 质量判断和 prompt 调参，不参与执行裁决。后续真正求解时，
    recipe_hint 仍要经过 resolver/trial 的可验算结果确认。
    """

    matched_recipes: tuple[str, ...] = ()
    matched_methods: tuple[str, ...] = ()
    null_hint_steps: tuple[str, ...] = ()
    unknown_hint_steps: tuple[str, ...] = ()
    unknown_goal_type_steps: tuple[str, ...] = ()
    preferred_recipe_ids: tuple[str, ...] = ()
    covered_preferred_recipe_ids: tuple[str, ...] = ()
    missing_preferred_recipe_ids: tuple[str, ...] = ()
    avoid_pattern_hits: tuple[dict[str, str], ...] = ()
    capability_errors: tuple[dict[str, str], ...] = ()

    @property
    def non_empty_hint_count(self) -> int:
        """返回命中 recipe、method 或 unknown 的非空 hint 数量。"""
        return (
            len(self.matched_recipes)
            + len(self.matched_methods)
            + len(self.unknown_hint_steps)
        )

    @property
    def matched_hint_count(self) -> int:
        """返回命中已知 recipe/method 的 hint 数量。"""
        return len(self.matched_recipes) + len(self.matched_methods)

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        return {
            "matched_recipes": list(self.matched_recipes),
            "matched_methods": list(self.matched_methods),
            "null_hint_steps": list(self.null_hint_steps),
            "unknown_hint_steps": list(self.unknown_hint_steps),
            "unknown_goal_type_steps": list(self.unknown_goal_type_steps),
            "preferred_recipe_ids": list(self.preferred_recipe_ids),
            "covered_preferred_recipe_ids": list(self.covered_preferred_recipe_ids),
            "missing_preferred_recipe_ids": list(self.missing_preferred_recipe_ids),
            "avoid_pattern_hits": list(self.avoid_pattern_hits),
            "capability_errors": list(self.capability_errors),
            "non_empty_hint_count": self.non_empty_hint_count,
            "matched_hint_count": self.matched_hint_count,
        }


@dataclass(frozen=True)
class HandleCorrection:
    """HandleResolver 对 LLM reads 做的一次保守修正。

    这类修正只处理 scope 前缀写错但语义名完全一致的情况。例如某一步在 ``ii_1``
    scope 中读取 ``fact:ii_1:path_minimum_target``，而题面真实 fact 是父级可见的
    ``fact:ii:path_minimum_target``。我们不修正 sibling scope，不修正 answer，也不
    根据自然语言猜测语义名。
    """

    step_id: str
    scope_id: str
    from_handle: str
    to_handle: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "from_handle": self.from_handle,
            "to_handle": self.to_handle,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HandleResolutionReport:
    """HandleResolver 的修正摘要。"""

    corrections: tuple[HandleCorrection, ...] = ()

    @property
    def changed(self) -> bool:
        """是否实际修正过任意 reads handle。"""
        return bool(self.corrections)

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        return {
            "changed": self.changed,
            "corrections": [
                correction.to_payload()
                for correction in self.corrections
            ],
        }


@dataclass(frozen=True)
class SemanticReadResolution:
    """一次 semantic read 到 canonical handle 的解析结果。"""

    step_id: str
    scope_id: str
    semantic_ref: SemanticRef
    handle: str
    candidate_count: int
    overrode_legacy_reads: bool = False
    inferred_from_step: str | None = None
    state_slot_id: str | None = None
    condition_id: str | None = None
    source_context_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "semantic_ref": self.semantic_ref.to_payload(),
            "handle": self.handle,
            "candidate_count": self.candidate_count,
            "overrode_legacy_reads": self.overrode_legacy_reads,
        }
        if self.inferred_from_step is not None:
            payload["inferred_from_step"] = self.inferred_from_step
        if self.state_slot_id is not None:
            payload["state_slot_id"] = self.state_slot_id
        if self.condition_id is not None:
            payload["condition_id"] = self.condition_id
        if self.source_context_id is not None:
            payload["source_context_id"] = self.source_context_id
        return payload


@dataclass(frozen=True)
class SemanticReadResolutionError:
    """一次 semantic read 解析失败的结构化错误。"""

    step_id: str
    scope_id: str
    code: str
    message: str
    semantic_ref: SemanticRef | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "code": self.code,
            "message": self.message,
        }
        if self.semantic_ref is not None:
            payload["semantic_ref"] = self.semantic_ref.to_payload()
        return payload


@dataclass(frozen=True)
class SemanticReadFallback:
    """Semantic read 失败后采用同 step legacy reads 的一次回退。"""

    step_id: str
    scope_id: str
    reason: str
    reads: tuple[str, ...]
    semantic_errors: tuple[SemanticReadResolutionError, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "reason": self.reason,
            "reads": list(self.reads),
            "semantic_errors": [
                error.to_payload()
                for error in self.semantic_errors
            ],
        }


@dataclass(frozen=True)
class SemanticReadResolutionReport:
    """SemanticReadResolver 的解析摘要。"""

    resolutions: tuple[SemanticReadResolution, ...] = ()
    errors: tuple[SemanticReadResolutionError, ...] = ()
    fallbacks: tuple[SemanticReadFallback, ...] = ()
    warnings: tuple[str, ...] = ()
    partially_resolved_payload: dict[str, Any] | None = None

    @property
    def changed(self) -> bool:
        """是否实际解析过任意 semantic read。"""
        return bool(self.resolutions or self.errors or self.fallbacks or self.warnings)

    @property
    def ok(self) -> bool:
        """是否没有 semantic read 解析错误。"""
        return not self.errors

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload: dict[str, Any] = {
            "changed": self.changed,
            "ok": self.ok,
            "resolutions": [
                resolution.to_payload()
                for resolution in self.resolutions
            ],
            "errors": [
                error.to_payload()
                for error in self.errors
            ],
            "fallbacks": [
                fallback.to_payload()
                for fallback in self.fallbacks
            ],
            "warnings": list(self.warnings),
        }
        if self.partially_resolved_payload is not None:
            payload["partially_resolved_payload"] = self.partially_resolved_payload
        return payload


@dataclass(frozen=True)
class StepIntentNormalizationAction:
    """StepIntentNormalizer 对草稿做的一次确定性整理。

    normalizer 只做代码可以确定的、保守的结构修正，例如把冗余 answer step 合并到
    前序已能产生同一答案的 recipe。它不会补数学推导，也不会创造普通中间 fact。
    """

    action: str
    step_id: str
    target_step_id: str | None = None
    handle: str | None = None
    reason: str = ""

    def to_payload(self) -> dict[str, str | None]:
        """转成 debug JSON。"""
        return {
            "action": self.action,
            "step_id": self.step_id,
            "target_step_id": self.target_step_id,
            "handle": self.handle,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StepIntentNormalizationReport:
    """StepIntentNormalizer 的整理报告。"""

    actions: tuple[StepIntentNormalizationAction, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """是否实际改写过 StepIntentDraft。"""
        return bool(self.actions)

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        return {
            "changed": self.changed,
            "actions": [action.to_payload() for action in self.actions],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StepIntentValidationReport:
    """StepIntent 校验结果摘要。"""

    ok: bool
    errors: tuple[str, ...] = ()
    step_count: int = 0
    covered_goals: tuple[str, ...] = ()
    missing_goals: tuple[str, ...] = ()
    recipe_alignment: RecipeAlignmentReport | None = None
    handle_resolution: HandleResolutionReport | None = None
    semantic_read_resolution: SemanticReadResolutionReport | None = None
    raw_output_normalization: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 JSON 友好结构。"""
        payload = {
            "ok": self.ok,
            "errors": list(self.errors),
            "step_count": self.step_count,
            "covered_goals": list(self.covered_goals),
            "missing_goals": list(self.missing_goals),
        }
        if self.recipe_alignment is not None:
            payload["recipe_alignment"] = self.recipe_alignment.to_payload()
        if self.handle_resolution is not None:
            payload["handle_resolution"] = self.handle_resolution.to_payload()
        if self.semantic_read_resolution is not None:
            payload["semantic_read_resolution"] = (
                self.semantic_read_resolution.to_payload()
            )
        if self.raw_output_normalization is not None:
            payload["raw_output_normalization"] = self.raw_output_normalization
        return payload


@dataclass(frozen=True)
class StepIntentAppliedFill:
    """执行前代码自动补齐的一条语义输入。

    这类补位只记录 canonical handle 层面的事实，不暴露 RuntimeContext path。
    例如 LLM 只读取 ``point:problem:B``，而 method 需要 ``Point`` 时，代码可
    唯一补到前序已产生的 ``fact:i:B_coordinate``。
    """

    step_id: str
    scope_id: str
    input_handle: str
    required_type: str
    resolved_handle: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "input_handle": self.input_handle,
            "required_type": self.required_type,
            "resolved_handle": self.resolved_handle,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StepIntentAcceptedStep:
    """已通过 compile + prefix dry-run 的 StepIntent。"""

    step_id: str
    scope_id: str
    capability_id: str
    method_ids: tuple[str, ...] = ()
    produced_handles: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "capability_id": self.capability_id,
            "method_ids": list(self.method_ids),
            "produced_handles": list(self.produced_handles),
        }


@dataclass(frozen=True)
class StepIntentPlannerInsight:
    """已执行前缀向下一轮 planner 暴露的语义 insight。

    insight 只来自 method/recipe 已执行产物，用于告诉 LLM 后续规划的关键角色。
    它不包含 RuntimePath、MethodInvocation、traceback 或 expected answer。
    """

    step_id: str
    scope_id: str
    produced_handle: str
    output_type: str
    facts: dict[str, Any]
    repair_note: str

    def to_payload(self) -> dict[str, Any]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "produced_handle": self.produced_handle,
            "output_type": self.output_type,
            "facts": self.facts,
            "repair_note": self.repair_note,
        }


@dataclass(frozen=True)
class StepIntentPreflightIssue:
    """执行前全量扫描发现的结构性提醒。

    Preflight issue 只基于 StepIntent 的 handle graph 与 capability contract，
    不运行 method，也不暴露 RuntimePath。它用于补足 prefix dry-run 只返回首个
    blocker 的盲区。
    """

    step_id: str
    scope_id: str
    category: str
    code: str
    message: str
    repair: str
    related_steps: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "repair": self.repair,
            "related_steps": list(self.related_steps),
        }


@dataclass(frozen=True)
class StepIntentFunctionBindingEvent:
    """FunctionSpec adapter binding result for one method attempt.

    The payload is debug-safe: it exposes function ids, method ids, status, and
    typed error codes, but never RuntimeContext paths.  ``failure`` means the
    migrated FunctionSpec adapter did not bind and execution stops at that
    structured error.
    """

    step_id: str
    scope_id: str
    method_id: str
    function_id: str
    status: Literal["success", "failure"]
    errors: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "method_id": self.method_id,
            "function_id": self.function_id,
            "status": self.status,
        }
        if self.errors:
            payload["errors"] = list(self.errors)
        return payload


@dataclass(frozen=True)
class StepIntentExecutionBlocker:
    """StepIntent 执行诊断中的首个 runtime 阻塞点。"""

    step_id: str
    scope_id: str
    stage: str
    code: str
    message: str
    capability_errors: tuple[str, ...] = ()
    capability_id: str | None = None
    missing_runtime_type: str | None = None
    retryable: bool = True

    def to_payload(self) -> dict[str, Any]:
        """转成可放入 previous_attempts 的安全 JSON。"""
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "capability_errors": list(self.capability_errors),
            "retryable": self.retryable,
        }
        if self.capability_id is not None:
            payload["capability_id"] = self.capability_id
        if self.missing_runtime_type is not None:
            payload["missing_runtime_type"] = self.missing_runtime_type
        return payload


@dataclass(frozen=True)
class StepIntentSkippedStep:
    """由于前缀执行失败而未进入 runtime trial 的后续 step。"""

    step_id: str
    scope_id: str
    reason: str

    def to_payload(self) -> dict[str, str]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StepIntentExecutionDiagnostic:
    """StepIntent effective draft 的执行诊断。

    它描述“代码已经接受了哪些步骤、自动补了哪些输入、在哪个 step 阻塞”。
    这份报告服务于 DeepSeek repair loop 和 debug，不是 PlannerOutput，也不包含
    RuntimePath、MethodInvocation、expected answer 或 traceback。
    """

    ok: bool
    accepted_prefix: tuple[StepIntentAcceptedStep, ...] = ()
    applied_fills: tuple[StepIntentAppliedFill, ...] = ()
    planner_insights: tuple[StepIntentPlannerInsight, ...] = ()
    preflight_issues: tuple[StepIntentPreflightIssue, ...] = ()
    function_binding_events: tuple[StepIntentFunctionBindingEvent, ...] = ()
    blockers: tuple[StepIntentExecutionBlocker, ...] = ()
    skipped_steps: tuple[StepIntentSkippedStep, ...] = ()
    candidate_errors: tuple[str, ...] = ()

    @property
    def first_blocker(self) -> StepIntentExecutionBlocker | None:
        """返回第一个 runtime blocker。"""
        return self.blockers[0] if self.blockers else None

    def to_payload(self) -> dict[str, Any]:
        """转成 debug/repair JSON。"""
        return {
            "ok": self.ok,
            "accepted_prefix": [
                item.to_payload() for item in self.accepted_prefix
            ],
            "applied_fills": [
                item.to_payload() for item in self.applied_fills
            ],
            "planner_insights": [
                item.to_payload() for item in self.planner_insights
            ],
            "preflight_issues": [
                item.to_payload() for item in self.preflight_issues
            ],
            "function_binding_events": [
                item.to_payload() for item in self.function_binding_events
            ],
            "blockers": [item.to_payload() for item in self.blockers],
            "skipped_steps": [item.to_payload() for item in self.skipped_steps],
            "candidate_errors": list(self.candidate_errors),
        }


PlannerRetryLayer = Literal[
    "replay",
    "semantic_reads",
    "handle_resolution",
    "validation",
    "normalization",
    "candidate_resolution",
    "trial_execution",
    "goal_verification",
    "answer_check",
]

PlannerRetryPreservePolicy = Literal[
    "preserve_all",
    "preserve_prefix",
    "preserve_step",
    "preserve_handles",
    "none",
]

PlannerReplayDepth = Literal[
    "semantic_reads",
    "handle_resolution",
    "validation",
    "normalization",
    "candidate_resolution",
    "trial_execution",
    "goal_verification",
    "answer_check",
]


@dataclass(frozen=True)
class PlannerRetryIssue:
    """LLM retry 的统一错误 envelope。"""

    layer: PlannerRetryLayer
    code: str
    step_id: str | None = None
    scope_id: str | None = None
    repair_target: str = "suffix"
    preserve_policy: PlannerRetryPreservePolicy = "preserve_prefix"
    message: str = ""
    hints: tuple[str, ...] = ()
    related_handles: tuple[str, ...] = ()
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 prompt/debug JSON。"""
        payload: dict[str, Any] = {
            "layer": self.layer,
            "code": self.code,
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "repair_target": self.repair_target,
            "preserve_policy": self.preserve_policy,
            "message": self.message,
            "hints": list(self.hints),
            "related_handles": list(self.related_handles),
        }
        if self.details is not None:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class PlannerRetryState:
    """Planner retry 的正式稳定状态。"""

    attempt: int
    baseline_draft: dict[str, Any] | None
    stable_prefix: tuple[dict[str, Any], ...] = ()
    repair_suffix_start: dict[str, str | None] | None = None
    issues: tuple[PlannerRetryIssue, ...] = ()
    recovered_issues: tuple[PlannerRetryIssue, ...] = ()
    preserve_policy: PlannerRetryPreservePolicy = "none"
    repair_instruction: str = ""
    replay_depth: PlannerReplayDepth | None = None
    selected_repair_layer: PlannerRetryLayer | None = None
    replay_timeline: tuple[dict[str, Any], ...] = ()
    replay_reports: dict[str, Any] | None = None
    source_context_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 ``previous_attempts`` 和 prompt 可携带的安全 JSON。"""
        payload = {
            "attempt": self.attempt,
            "baseline_draft": self.baseline_draft,
            "stable_prefix": list(self.stable_prefix),
            "repair_suffix_start": self.repair_suffix_start,
            "issues": [issue.to_payload() for issue in self.issues],
            "recovered_issues": [
                issue.to_payload() for issue in self.recovered_issues
            ],
            "preserve_policy": self.preserve_policy,
            "repair_instruction": self.repair_instruction,
            "replay_depth": self.replay_depth,
            "selected_repair_layer": self.selected_repair_layer,
            "replay_timeline": list(self.replay_timeline),
            "replay_reports": self.replay_reports or {},
        }
        if self.source_context_id is not None:
            payload["source"] = "planner_state_context"
            payload["source_context_id"] = self.source_context_id
        return payload


@dataclass(frozen=True)
class StepIntentRepairAttempt:
    """传回下一轮 LLM 的结构化 repair context。"""

    attempt: int
    effective_draft: dict[str, Any] | None
    diagnostic: StepIntentExecutionDiagnostic | None
    repair_instruction: str
    repair_summary: dict[str, Any] | None = None
    planner_retry_state: PlannerRetryState | None = None
    errors: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成 ``PlannerInputs.previous_errors`` 可携带的安全 JSON。"""
        payload: dict[str, Any] = {
            "attempt": self.attempt,
            "effective_draft": self.effective_draft,
            "repair_summary": self.repair_summary,
            "planner_retry_state": (
                self.planner_retry_state.to_payload()
                if self.planner_retry_state is not None
                else None
            ),
            "repair_instruction": self.repair_instruction,
            "errors": list(self.errors),
        }
        if self.diagnostic is not None:
            payload["diagnostic"] = self.diagnostic.to_payload()
        return payload


@dataclass(frozen=True)
class ExecutableCapabilitySpec:
    """StepIntent 可尝试匹配的执行能力。

    它把 recipe 与 method 统一成一张“可执行候选”菜单。这里仍不绑定具体
    ContextPath，也不执行 SymPy；它只回答一个问题：某个 StepIntent 的目标和
    produces 是否可能由某个 recipe/method 承接。
    """

    capability_id: str
    kind: str
    goal_type: str
    method_ids: tuple[str, ...]
    output_types: tuple[str, ...]
    goal_aliases: tuple[str, ...] = ()
    allows_creates: bool = False
    preferred: bool = False
    title: str = ""
    description: str = ""
    execution_status: str = "executable"
    contract: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        payload = {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "goal_type": self.goal_type,
            "goal_aliases": list(self.goal_aliases),
            "method_ids": list(self.method_ids),
            "output_types": list(self.output_types),
            "allows_creates": self.allows_creates,
            "preferred": self.preferred,
            "title": self.title,
            "description": self.description,
            "execution_status": self.execution_status,
        }
        if self.contract is not None:
            payload["contract"] = self.contract
        return payload


@dataclass(frozen=True)
class StepIntentResolutionCandidate:
    """某个 StepIntent 的一个 recipe/method 候选。"""

    capability_id: str
    kind: str
    score: int
    matched_by: tuple[str, ...]
    output_types: tuple[str, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """候选是否能覆盖该 step 的 produces。"""
        return not self.errors

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "score": self.score,
            "matched_by": list(self.matched_by),
            "output_types": list(self.output_types),
            "errors": list(self.errors),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class StepIntentResolutionStepReport:
    """单个 StepIntent 的可执行候选解析报告。"""

    step_id: str
    scope_id: str
    recipe_hint: str | None
    produced_types: tuple[str, ...]
    selected_capability_id: str | None
    candidates: tuple[StepIntentResolutionCandidate, ...]
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """该 step 是否至少有一个可尝试执行的候选。"""
        return self.selected_capability_id is not None and not self.errors

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "step_id": self.step_id,
            "scope_id": self.scope_id,
            "recipe_hint": self.recipe_hint,
            "produced_types": list(self.produced_types),
            "selected_capability_id": self.selected_capability_id,
            "candidates": [candidate.to_payload() for candidate in self.candidates],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class ExecutablePlanResolutionReport:
    """StepIntentDraft 到 executable candidates 的整体解析报告。"""

    ok: bool
    step_reports: tuple[StepIntentResolutionStepReport, ...]
    errors: tuple[str, ...] = ()
    capability_catalog: tuple[ExecutableCapabilitySpec, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "step_reports": [report.to_payload() for report in self.step_reports],
            "capability_catalog": [
                capability.to_payload()
                for capability in self.capability_catalog
            ],
        }


class StrategyDraftValidationError(ValueError):
    """LLM StepIntent draft 不符合 Phase 1 协议。"""

STEP_INTENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["scopes"],
    "properties": {
        "scopes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scope_id", "label", "steps"],
                "properties": {
                    "scope_id": {
                        "type": "string",
                        "description": "ProblemIR question/subquestion id，例如 i, ii, ii_1, ii_2",
                    },
                    "label": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "anyOf": [
                                {"required": ["reads"]},
                                {"required": ["semantic_reads"]},
                            ],
                            "allOf": [
                                {
                                    "anyOf": [
                                        {"required": ["creates"]},
                                        {"required": ["produces"]},
                                        {"required": ["outputs"]},
                                    ],
                                },
                            ],
                            "required": [
                                "step_id",
                                "goal_type",
                                "target",
                                "strategy",
                                "reason",
                            ],
                            "properties": {
                                "step_id": {
                                    "type": "string",
                                    "description": "语义化 snake_case id，例如 derive_axis_point",
                                },
                                "recipe_hint": {
                                    "type": ["string", "null"],
                                    "description": "优先从 recipe_catalog[].recipe_id 选择；其次从 method_catalog[].method_id 选择；不确定时填 null 或省略",
                                },
                                "goal_type": {"type": "string"},
                                "target": {
                                    "type": "string",
                                    "description": "语义目标或 answer:<QuestionGoal.id>",
                                },
                                "strategy": {
                                    "type": "string",
                                    "description": "本步打算如何推进，不写具体答案",
                                },
                                "reads": {
                                    "type": "array",
                                    "description": "Legacy fallback: 本步读取的 canonical Entity/Fact/answer handle；semantic_reads 解析成功时优先，若 semantic_reads 失败且 reads 全部可见有效，系统可回退到 reads",
                                    "items": {"type": "string"},
                                },
                                "semantic_reads": {
                                    "type": "array",
                                    "description": "推荐字段：读入引用；ref 可写 semantic_read_catalog 短 ref 或 canonical handle，系统会解析为 canonical reads",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["ref", "kind"],
                                        "properties": {
                                            "ref": {
                                                "type": "string",
                                                "description": "semantic_read_catalog 中的 ref、前序产物语义名，或 ProblemIR/前序产物的 canonical handle",
                                            },
                                            "kind": {
                                                "type": "string",
                                                "enum": list(SEMANTIC_READ_KIND_ORDER),
                                            },
                                            "value_type": {
                                                "type": ["string", "null"],
                                                "description": "可选 disambiguation：fact type、answer value_type 或前序 produces.output_type",
                                            },
                                            "from_step": {
                                                "type": ["string", "null"],
                                                "description": "读取前序 step 的 creates/produces 时建议填写；若省略，系统只在唯一可见 exact match 时自动推断；读取题面初始对象时不要填",
                                            },
                                        },
                                    },
                                },
                                "creates": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": [
                                            "handle",
                                            "entity_type",
                                            "valid_scope",
                                            "description",
                                        ],
                                        "properties": {
                                            "handle": {
                                                "type": "string",
                                                "description": "新实体 handle，例如 point:ii:Aux",
                                            },
                                            "entity_type": {
                                                "type": "string",
                                                "description": "实体类型，必须与 handle 前缀一致",
                                            },
                                            "valid_scope": {
                                                "type": "string",
                                                "description": "实体有效 scope，例如 problem、i、ii、ii_1",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "这个新实体的自然语言说明",
                                            },
                                        },
                                    },
                                },
                                "produces": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": [
                                            "handle",
                                            "valid_scope",
                                            "description",
                                        ],
                                        "properties": {
                                            "handle": {
                                                "type": "string",
                                                "description": "新事实或最终答案 handle，例如 fact:ii:N_coordinate_expr 或 answer:i.parabola",
                                            },
                                            "valid_scope": {
                                                "type": "string",
                                                "description": "事实有效 scope，例如 problem、i、ii、ii_1",
                                            },
                                            "description": {
                                                "type": "string",
                                                "description": "这条事实或答案的自然语言说明",
                                            },
                                            "output_type": {
                                                "type": ["string", "null"],
                                                "enum": [*STEP_INTENT_OUTPUT_TYPES, None],
                                                "description": "可选：本 produces 对应的 runtime 输出类型；能确定时请显式填写，减少系统从自然语言猜测",
                                            },
                                        },
                                    },
                                },
                                "outputs": {
                                    "type": "array",
                                    "description": "兼容输入层：可用统一 outputs[] 描述 creates/produces，系统会在校验前分拣成 canonical creates/produces；StepIntent 输出仍只保留 creates/produces",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": [
                                            "handle",
                                            "valid_scope",
                                            "description",
                                        ],
                                        "properties": {
                                            "handle": {
                                                "type": "string",
                                                "description": "entity/fact/answer handle",
                                            },
                                            "entity_type": {
                                                "type": ["string", "null"],
                                                "description": "当 handle 是新 entity 时可填；缺省时系统从 handle 前缀推导",
                                            },
                                            "valid_scope": {
                                                "type": "string",
                                            },
                                            "description": {
                                                "type": "string",
                                            },
                                            "output_type": {
                                                "type": ["string", "null"],
                                                "enum": [*STEP_INTENT_OUTPUT_TYPES, None],
                                                "description": "当输出是 fact/answer 时的可选类型 hint；系统会用 contract/handle 继续校准",
                                            },
                                        },
                                    },
                                },
                                "reason": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}
