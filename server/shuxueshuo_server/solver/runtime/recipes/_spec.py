"""RecipeSpec 的代码源。

Recipe 位于 method 之上，描述一个可复用的复合解题动作。V1 先把 recipe 的
讲解模板和基础元数据收口到代码中；执行编排仍兼容现有 family/recipe compiler。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.contracts import TeachingSubstepSpec


@dataclass(frozen=True)
class RecipeExplanationSpec:
    """recipe 面向讲解层的角色化模板。

    静态模板只能描述数学结构和角色，不写具体题目的点名、题号、路径名或答案。
    当前题的角色由 ExplanationRoleBinder 在 runtime 成功产物中绑定。
    """

    role_schema: dict[str, str]
    student_intent_template: str
    student_title_template: str = ""
    student_nav_title_template: str = ""
    student_title_templates_by_goal: dict[str, str] | None = None
    proof_outline_templates: tuple[str, ...] = ()
    recommended_lesson_splits: tuple[str, ...] = ()
    teaching_substep_specs: tuple[TeachingSubstepSpec, ...] = ()
    allowed_llm_completion: tuple[str, ...] = ()
    method_trace_usage: str = "method trace 只用于计算细节和验算，不用于猜证明。"
    role_binder_id: str = "generic_recipe"

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_schema": dict(self.role_schema),
            "student_intent_template": self.student_intent_template,
            "student_title_template": self.student_title_template,
            "student_nav_title_template": self.student_nav_title_template,
            "student_title_templates_by_goal": dict(self.student_title_templates_by_goal or {}),
            "proof_outline_templates": list(self.proof_outline_templates),
            "recommended_lesson_splits": list(self.recommended_lesson_splits),
            "teaching_substep_specs": [
                item.to_payload() for item in self.teaching_substep_specs
            ],
            "allowed_llm_completion": list(self.allowed_llm_completion),
            "method_trace_usage": self.method_trace_usage,
            "role_binder_id": self.role_binder_id,
        }


@dataclass(frozen=True)
class RecipeVisualSpec:
    """recipe 面向 VisualStepIR 的角色化视觉模板。"""

    role_schema: dict[str, str]
    teaching_substep_templates: dict[str, tuple[dict[str, Any], ...]]
    annotation_templates: tuple[dict[str, Any], ...] = ()
    role_binder_id: str = "generic_visual"

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_schema": dict(self.role_schema),
            "teaching_substep_templates": {
                key: [dict(item) for item in value]
                for key, value in self.teaching_substep_templates.items()
            },
            "annotation_templates": [dict(item) for item in self.annotation_templates],
            "role_binder_id": self.role_binder_id,
        }


@dataclass(frozen=True)
class RecipeSpecSource:
    """一个 recipe 文件内的结构化 RecipeSpec 源。"""

    recipe_id: str
    title: str
    summary: str
    method_sequence: tuple[str, ...]
    execution_strategy: str
    outputs: dict[str, str]
    explanation: RecipeExplanationSpec | None = None
    visual: RecipeVisualSpec | None = None
    repair_hints: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "recipe_id": self.recipe_id,
            "title": self.title,
            "summary": self.summary,
            "method_sequence": list(self.method_sequence),
            "execution_strategy": self.execution_strategy,
            "outputs": self.outputs,
        }
        if self.explanation is not None:
            payload["explanation"] = self.explanation.to_payload()
        if self.visual is not None:
            payload["visual"] = self.visual.to_payload()
        if self.repair_hints:
            payload["repair_hints"] = [
                _json_ready_hint(item) for item in self.repair_hints
            ]
        return payload


@dataclass(frozen=True)
class RecipeSpec:
    """RecipeSpecSource 解析后的轻量 runtime 形态。"""

    recipe_id: str
    title: str
    summary: str
    method_sequence: tuple[str, ...]
    execution_strategy: str
    outputs: dict[str, str]
    explanation: RecipeExplanationSpec | None = None
    visual: RecipeVisualSpec | None = None
    repair_hints: tuple[dict[str, Any], ...] = ()


def recipe_spec_from_source(source: RecipeSpecSource) -> RecipeSpec:
    return RecipeSpec(
        recipe_id=source.recipe_id,
        title=source.title,
        summary=source.summary,
        method_sequence=source.method_sequence,
        execution_strategy=source.execution_strategy,
        outputs=dict(source.outputs),
        explanation=source.explanation,
        visual=source.visual,
        repair_hints=source.repair_hints,
    )


def _json_ready_hint(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in raw.items()
    }
