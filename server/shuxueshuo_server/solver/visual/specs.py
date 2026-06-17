"""Visual spec models used by VS1 generation.

The specs are intentionally small data containers.  They describe visual
intent in role language; builder/binder code decides how roles map to the
current problem's verified handles and existing geometry objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MethodVisualSpec:
    """Visual template for a single method capability."""

    role_schema: dict[str, str]
    scene_templates: tuple[dict[str, Any], ...] = ()
    annotation_templates: tuple[dict[str, Any], ...] = ()
    timeline_templates: tuple[dict[str, Any], ...] = ()
    role_binder_id: str = "generic_visual"

    def to_payload(self) -> dict[str, Any]:
        return {
            "role_schema": dict(self.role_schema),
            "scene_templates": [dict(item) for item in self.scene_templates],
            "annotation_templates": [dict(item) for item in self.annotation_templates],
            "timeline_templates": [dict(item) for item in self.timeline_templates],
            "role_binder_id": self.role_binder_id,
        }


@dataclass(frozen=True)
class RecipeVisualSpec:
    """Visual template for a recipe and its teaching substeps."""

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
