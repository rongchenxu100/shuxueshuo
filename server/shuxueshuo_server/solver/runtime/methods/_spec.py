"""MethodSpec 的代码源。

MethodSpec JSON 不再手写维护，而是从每个 method 文件里的 ``SPEC`` 生成。
``description`` 默认取 method class 的 docstring 首段，因此 method 的能力说明会和
代码注释待在一起。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import inspect

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
    MethodVisualSpec,
    PlanTransformerScope,
    ScalarResultFormSpec,
)


@dataclass(frozen=True)
class MethodSpecSource:
    """一个 method 文件内的结构化 MethodSpec 源。

    ``method_cls`` 提供 method_id 和 docstring；其他字段提供 validator 需要的
    输入、输出、solves 和前后置条件。
    """

    method_cls: type
    title: str
    solves: tuple[str, ...]
    inputs: dict[str, dict[str, Any]]
    outputs: dict[str, str]
    scalar_result_forms: dict[str, ScalarResultFormSpec] = field(default_factory=dict)
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    trace_template: tuple[str, ...] = ()
    repair_hints: tuple[dict[str, Any], ...] = ()
    explanation: MethodExplanationSpec | None = None
    visual: MethodVisualSpec | None = None
    description: str = ""
    summary: str = ""
    do_not_use_when: tuple[str, ...] = ()
    constraint_analyzer: str | None = None
    plan_transformer: str | None = None
    plan_transformer_scope: PlanTransformerScope = "single_invocation"
    reconciliation_validators: tuple[str, ...] = ()
    distinct_arg_groups: tuple[tuple[str, ...], ...] = ()
    # This source type is reserved for runtime/stateless methods. Stateful
    # implementations must opt out so liveness analysis cannot delete them.
    is_pure: bool = True

    @property
    def method_id(self) -> str:
        return str(self.method_cls.method_id)

    def to_payload(self) -> dict[str, Any]:
        description = self.description or _first_docstring_paragraph(self.method_cls)
        payload: dict[str, Any] = {
            "method_id": self.method_id,
            "title": self.title,
            "description": description,
            "summary": self.summary,
            "solves": list(self.solves),
            "inputs": self.inputs,
            "outputs": self.outputs,
            "is_pure": self.is_pure,
        }
        if self.scalar_result_forms:
            payload["scalar_result_forms"] = {
                name: spec.to_payload()
                for name, spec in self.scalar_result_forms.items()
            }
        if self.preconditions:
            payload["preconditions"] = list(self.preconditions)
        if self.do_not_use_when:
            payload["do_not_use_when"] = list(self.do_not_use_when)
        if self.postconditions:
            payload["postconditions"] = list(self.postconditions)
        if self.trace_template:
            payload["trace_template"] = list(self.trace_template)
        if self.repair_hints:
            payload["repair_hints"] = [
                _json_ready_hint(item) for item in self.repair_hints
            ]
        if self.explanation is not None:
            payload["explanation"] = _json_ready_explanation(self.explanation)
        if self.visual is not None:
            payload["visual"] = _json_ready_visual(self.visual)
        if self.constraint_analyzer is not None:
            payload["constraint_analyzer"] = self.constraint_analyzer
        if self.plan_transformer is not None:
            payload["plan_transformer"] = self.plan_transformer
            payload["plan_transformer_scope"] = self.plan_transformer_scope
        if self.reconciliation_validators:
            payload["reconciliation_validators"] = list(
                self.reconciliation_validators
            )
        if self.distinct_arg_groups:
            payload["distinct_arg_groups"] = [
                list(group) for group in self.distinct_arg_groups
            ]
        return payload


def _first_docstring_paragraph(method_cls: type) -> str:
    doc = inspect.getdoc(method_cls) or ""
    return doc.split("\n\n", 1)[0]


def _json_ready_hint(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert repair hint tuple values to JSON-equivalent lists."""
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in raw.items()
    }


def _json_ready_explanation(explanation: MethodExplanationSpec) -> dict[str, Any]:
    payload = {
        "role_schema": dict(explanation.role_schema),
        "student_goal_template": explanation.student_goal_template,
        "student_title_template": explanation.student_title_template,
        "student_title_templates_by_goal": dict(explanation.student_title_templates_by_goal),
        "derive_templates": list(explanation.derive_templates),
        "box_templates": list(explanation.box_templates),
        "explanation_level": explanation.explanation_level,
        "role_binding_strategy": explanation.role_binding_strategy,
        "role_binder_id": explanation.role_binder_id,
    }
    if explanation.student_nav_title_template:
        payload["student_nav_title_template"] = explanation.student_nav_title_template
    return payload


def _json_ready_visual(visual: MethodVisualSpec) -> dict[str, Any]:
    return {
        "role_schema": dict(visual.role_schema),
        "scene_templates": [dict(item) for item in visual.scene_templates],
        "annotation_templates": [dict(item) for item in visual.annotation_templates],
        "timeline_templates": [dict(item) for item in visual.timeline_templates],
        "role_binder_id": visual.role_binder_id,
    }
