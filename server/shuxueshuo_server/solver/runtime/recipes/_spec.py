"""RecipeSpec 的代码源。

Recipe 位于 method 之上，描述一个可复用的复合解题动作。V1 先把 recipe 的
讲解模板和基础元数据收口到代码中；执行编排仍兼容现有 family/recipe compiler。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shuxueshuo_server.solver.contracts import TeachingUnitSpec


@dataclass(frozen=True)
class TeachingVariantSpec:
    """A verified-evidence-selected teaching path for one Macro."""

    variant_key: str
    evidence_match: dict[str, Any]
    teaching_units: tuple[TeachingUnitSpec, ...]

    def __post_init__(self) -> None:
        if not self.variant_key or not self.evidence_match or not self.teaching_units:
            raise ValueError("TeachingVariantSpec fields must be non-empty")

    def to_payload(self) -> dict[str, Any]:
        return {
            "variant_key": self.variant_key,
            "evidence_match": dict(self.evidence_match),
            "teaching_units": [item.to_payload() for item in self.teaching_units],
        }


@dataclass(frozen=True)
class MacroTeachingSpec:
    """One fixed unit path or a set of evidence-selected paths, never both."""

    teaching_units: tuple[TeachingUnitSpec, ...] = ()
    teaching_variants: tuple[TeachingVariantSpec, ...] = ()

    def __post_init__(self) -> None:
        if bool(self.teaching_units) == bool(self.teaching_variants):
            raise ValueError(
                "MacroTeachingSpec requires exactly one of teaching_units or "
                "teaching_variants"
            )
        keys = tuple(
            item.unit_key
            for item in self.teaching_units
            or tuple(
                unit
                for variant in self.teaching_variants
                for unit in variant.teaching_units
            )
        )
        if len(keys) != len(set(keys)):
            raise ValueError("MacroTeachingSpec unit keys must be unique")

    def to_payload(self) -> dict[str, Any]:
        return {
            "teaching_units": [item.to_payload() for item in self.teaching_units],
            "teaching_variants": [
                item.to_payload() for item in self.teaching_variants
            ],
        }


@dataclass(frozen=True)
class RecipeVisualSpec:
    """recipe 面向 VisualStepIR 的角色化视觉模板。"""

    role_schema: dict[str, str]
    teaching_substep_templates: dict[str, tuple[dict[str, Any], ...]]
    teaching_substep_timeline_templates: dict[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)
    annotation_templates: tuple[dict[str, Any], ...] = ()
    role_binder_id: str = "generic_visual"

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_schema": dict(self.role_schema),
            "teaching_substep_templates": {
                key: [dict(item) for item in value]
                for key, value in self.teaching_substep_templates.items()
            },
            "teaching_substep_timeline_templates": {
                key: [dict(item) for item in value]
                for key, value in self.teaching_substep_timeline_templates.items()
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
    teaching: MacroTeachingSpec | None = None
    visual: RecipeVisualSpec | None = None
    repair_hints: tuple[dict[str, Any], ...] = ()
    repair_feedback_provider_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "recipe_id": self.recipe_id,
            "title": self.title,
            "summary": self.summary,
            "method_sequence": list(self.method_sequence),
            "execution_strategy": self.execution_strategy,
            "outputs": self.outputs,
        }
        if self.teaching is not None:
            payload["teaching"] = self.teaching.to_payload()
        if self.visual is not None:
            payload["visual"] = self.visual.to_payload()
        if self.repair_hints:
            payload["repair_hints"] = [
                _json_ready_hint(item) for item in self.repair_hints
            ]
        if self.repair_feedback_provider_id is not None:
            payload["repair_feedback_provider_id"] = (
                self.repair_feedback_provider_id
            )
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
    teaching: MacroTeachingSpec | None = None
    visual: RecipeVisualSpec | None = None
    repair_hints: tuple[dict[str, Any], ...] = ()
    repair_feedback_provider_id: str | None = None


def recipe_spec_from_source(source: RecipeSpecSource) -> RecipeSpec:
    return RecipeSpec(
        recipe_id=source.recipe_id,
        title=source.title,
        summary=source.summary,
        method_sequence=source.method_sequence,
        execution_strategy=source.execution_strategy,
        outputs=dict(source.outputs),
        teaching=source.teaching,
        visual=source.visual,
        repair_hints=source.repair_hints,
        repair_feedback_provider_id=source.repair_feedback_provider_id,
    )


def _json_ready_hint(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in raw.items()
    }
