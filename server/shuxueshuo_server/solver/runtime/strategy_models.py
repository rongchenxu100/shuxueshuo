"""Strategy Planner 的数据模型与 JSON schema。

本模块只保存 LLM StepIntent 草稿、校验报告和 executable candidate 报告等
轻量数据结构，不依赖 runtime context 或 method 执行层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

    def to_payload(self) -> dict[str, str]:
        """转成 JSON 友好的 dict。"""
        return {
            "handle": self.handle,
            "valid_scope": self.valid_scope,
            "description": self.description,
        }


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
    preferred: bool = False
    title: str = ""
    description: str = ""

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "goal_type": self.goal_type,
            "method_ids": list(self.method_ids),
            "output_types": list(self.output_types),
            "preferred": self.preferred,
            "title": self.title,
            "description": self.description,
        }


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
                            "required": [
                                "step_id",
                                "goal_type",
                                "target",
                                "strategy",
                                "reads",
                                "creates",
                                "produces",
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
                                    "description": "本步读取的 canonical Entity/Fact/answer handle",
                                    "items": {"type": "string"},
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
