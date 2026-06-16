"""Shared geometry naming helpers for generated VisualStepIR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def scope_root(scope_id: str | None) -> str:
    if not scope_id:
        return "problem"
    text = str(scope_id)
    if text.startswith("ii"):
        return "ii"
    if text.startswith("i"):
        return "i"
    return text.split("_", 1)[0]


@dataclass(frozen=True)
class GeometryPointScopeNamer:
    """Map a mathematical point label and scope to a stable geometry id."""

    problem_point_names: frozenset[str]
    label_roots: Mapping[str, frozenset[str]]

    def geometry_id(self, label: str, scope_id: str | None) -> str:
        root = scope_root(scope_id)
        if root == "i" and self._needs_first_part_suffix(label):
            return f"{label}1"
        return label

    def candidate_ids(self, label: str, scope_id: str | None) -> tuple[str, ...]:
        preferred = self.geometry_id(label, scope_id)
        candidates = [preferred, label, f"{label}1"]
        out: list[str] = []
        for item in candidates:
            if item and item not in out:
                out.append(item)
        return tuple(out)

    def point_meta(self, label: str, scope_id: str | None) -> dict[str, str]:
        root = scope_root(scope_id)
        return {
            "label": label,
            "scopeId": str(scope_id or ""),
            "scopeRoot": root,
        }

    def _needs_first_part_suffix(self, label: str) -> bool:
        if label not in self.problem_point_names:
            return True
        roots = set(self.label_roots.get(label, frozenset()))
        return bool({"ii", "iii"} & roots)

    @classmethod
    def from_geometry_spec(
        cls,
        geometry_spec: dict[str, Any],
        problem: dict[str, Any] | None = None,
    ) -> "GeometryPointScopeNamer":
        problem_point_names = {
            str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            for entity in (problem or {}).get("entities") or ()
            if isinstance(entity, dict)
            and entity.get("entity_type") == "point"
            and str(entity.get("scope_id") or "") == "problem"
        }
        roots: dict[str, set[str]] = {}
        for point_id, raw_meta in (geometry_spec.get("pointMeta") or {}).items():
            if not isinstance(raw_meta, dict):
                continue
            label = str(raw_meta.get("label") or point_id)
            root = str(raw_meta.get("scopeRoot") or scope_root(str(raw_meta.get("scopeId") or "")))
            if label and root:
                roots.setdefault(label, set()).add(root)
        if not roots:
            for point_id in (
                *(geometry_spec.get("fixedPoints") or {}).keys(),
                *(geometry_spec.get("movingPoints") or {}).keys(),
            ):
                label = _label_from_geometry_id(str(point_id))
                roots.setdefault(label, set()).add("i" if str(point_id).endswith("1") else "problem")
        return cls(
            problem_point_names=frozenset(problem_point_names),
            label_roots={key: frozenset(value) for key, value in roots.items()},
        )


def _handle_tail(handle: str) -> str:
    return handle.rsplit(":", 1)[-1] if handle else ""


def _label_from_geometry_id(point_id: str) -> str:
    if len(point_id) > 1 and point_id.endswith("1") and point_id[-2].isalpha():
        return point_id[:-1]
    return point_id
