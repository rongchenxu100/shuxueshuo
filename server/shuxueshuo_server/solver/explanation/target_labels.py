"""Shared target-label extraction for explanation planning."""

from __future__ import annotations

from typing import Any
import re

from .models import LessonCandidateGroup


TARGET_POINT_HANDLE_SUFFIXES: tuple[str, ...] = (
    "_point_at_parameter",
    "_point_at_c",
    "_at_parameter",
    "_at_c",
    "_coordinate_expr",
    "_coordinate_value",
    "_coordinate",
    "_parameterized_point",
    "_parametric_coordinate",
    "_locus_line",
    "_line",
    "_locus",
)


def target_point_label_for_group(group: LessonCandidateGroup) -> str:
    handles = [str(group.step.get("target") or "")]
    for produced in group.step.get("produces", ()):
        if isinstance(produced, dict):
            handles.append(str(produced.get("handle") or ""))
    for handle in handles:
        name = _target_label_from_handle(handle)
        if name:
            return name
    return ""


def target_point_labels_for_groups(groups: tuple[LessonCandidateGroup, ...]) -> tuple[str, ...]:
    labels = [target_point_label_for_group(group) for group in groups]
    return tuple(dict.fromkeys(label for label in labels if label))


def target_point_labels_from_groups_and_pieces(
    groups: tuple[LessonCandidateGroup, ...],
    pieces: list[dict[str, Any]],
) -> tuple[str, ...]:
    labels: list[str] = list(target_point_labels_for_groups(groups))
    for piece in pieces:
        for item in piece.get("box", ()) or ():
            match = re.match(r"\s*([A-Z][A-Za-z0-9_′]*)\s*[\(（]", str(item))
            if match:
                labels.append(match.group(1))
    return tuple(dict.fromkeys(label for label in labels if label))


def _target_label_from_handle(handle: str) -> str:
    name = str(handle).rsplit(":", 1)[-1]
    for suffix in TARGET_POINT_HANDLE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name if re.fullmatch(r"[A-Z][A-Za-z0-9_′]*", name) else ""
