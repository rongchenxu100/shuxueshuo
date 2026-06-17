"""Explanation LessonIR few-shot loading and selection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from shuxueshuo_server.solver.runtime._paths import repo_root


FORBIDDEN_EXPLANATION_FEW_SHOT_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "expected",
        "expected_answers",
        "raw_response",
    }
)


def default_explanation_few_shot_dir() -> Path:
    return repo_root(Path(__file__)) / "internal" / "explanation-few-shots"


def lesson_few_shot_path_for_problem(
    problem_id: str,
    *,
    few_shot_dir: Path | str | None = None,
) -> Path:
    root = Path(few_shot_dir) if few_shot_dir is not None else default_explanation_few_shot_dir()
    return root / f"{problem_id}.lesson-few-shot.json"


def load_lesson_few_shot_entries(
    *,
    few_shot_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    root = Path(few_shot_dir) if few_shot_dir is not None else default_explanation_few_shot_dir()
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.lesson-few-shot.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        validate_lesson_few_shot_entry(entry)
        entries.append(entry)
    return entries


def select_lesson_few_shot_examples(
    *,
    family_id: str,
    goal_types: Iterable[str],
    capability_ids: Iterable[str],
    problem_id: str | None = None,
    allow_same_problem: bool = True,
    top_k: int = 1,
    few_shot_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Select LessonIR few-shot examples.

    Explanation few-shot prioritizes capability overlap because lesson style follows
    the mechanism/recipe more than the final answer type.
    """
    if top_k <= 0:
        return []
    query_goals = set(goal_types)
    query_capabilities = set(capability_ids)
    candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for entry in load_lesson_few_shot_entries(few_shot_dir=few_shot_dir):
        if entry["family_id"] != family_id:
            continue
        if not allow_same_problem and problem_id and entry["problem_id"] == problem_id:
            continue
        retrieval = entry.get("retrieval", {})
        capabilities = set(retrieval.get("capability_ids", []))
        goals = set(retrieval.get("goal_types", []))
        capability_overlap = len(query_capabilities.intersection(capabilities))
        goal_overlap = len(query_goals.intersection(goals))
        candidates.append(
            (
                capability_overlap,
                goal_overlap,
                len(capabilities) + len(goals),
                entry["problem_id"],
                entry,
            )
        )
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return [entry for *_prefix, entry in candidates[:top_k]]


def validate_lesson_few_shot_entry(entry: dict[str, Any]) -> None:
    forbidden = sorted(_collect_forbidden_keys(entry))
    if forbidden:
        raise ValueError(f"lesson few-shot contains forbidden keys: {forbidden}")
    required = {"problem_id", "family_id", "original_text", "retrieval", "example"}
    missing = sorted(required - set(entry))
    if missing:
        raise ValueError(f"lesson few-shot missing required keys: {missing}")
    if not isinstance(entry["original_text"], list):
        raise TypeError("lesson few-shot original_text must be a list")
    lesson_ir = entry.get("example", {}).get("lesson_ir")
    if not isinstance(lesson_ir, dict):
        raise TypeError("lesson few-shot example.lesson_ir must be an object")
    if not isinstance(lesson_ir.get("steps"), list) or not lesson_ir["steps"]:
        raise TypeError("lesson few-shot lesson_ir.steps must be a non-empty list")
    retrieval = entry.get("retrieval", {})
    if not isinstance(retrieval.get("goal_types"), list):
        raise TypeError("lesson few-shot retrieval.goal_types must be a list")
    if not isinstance(retrieval.get("capability_ids"), list):
        raise TypeError("lesson few-shot retrieval.capability_ids must be a list")
    serialized = json.dumps(entry, ensure_ascii=False)
    if "$problem." in serialized or "$question." in serialized or "$subquestion." in serialized:
        raise ValueError("lesson few-shot must not contain runtime ContextPath values")


def equal_length_ray_lesson_mock_few_shot(family_id: str) -> dict[str, Any]:
    """Family mock example for equal-length ray path reduction explanation style."""
    return {
        "problem_id": "fallback-equal-length-ray-lesson",
        "family_id": family_id,
        "title": "等长射线路径最值讲解示例",
        "original_text": [
            "抽象示例：一个动点在线段上，另一个动点在射线上，二者到公共端点的距离相等，求一条两动点路径和的最小值。"
        ],
        "retrieval": {
            "goal_types": ["derive_path_minimum_expression", "derive_parameter"],
            "capability_ids": [
                "equal_length_ray_path_reduction",
                "parameter_from_expression_value",
            ],
        },
        "example": {
            "lesson_ir": {
                "steps": [
                    {
                        "id": "mock_step_1",
                        "title": "第1步：构造辅助点，把两动点路径转成单动点路径",
                        "source_step_ids": ["mock_equal_length_reduction"],
                        "derive": [
                            ["作", "在射线上取辅助点，使它到公共端点的距离等于线段参考端点到公共端点的距离。"],
                            ["∵", "射线动点与线段动点到公共端点的距离相等，且两组点分别在同一直线或射线上。"],
                            ["∴", "对应三角形全等，原路径中的一段距离可替换为线段动点到辅助点的距离。"],
                            ["∴", "两动点路径和转化为单动点路径和。"],
                        ],
                        "box": ["两动点路径和 = 单动点路径和"],
                    },
                    {
                        "id": "mock_step_2",
                        "title": "第2步：用两点之间线段最短确定最小值",
                        "source_step_ids": ["mock_equal_length_reduction"],
                        "derive": [
                            ["∵", "转化后路径只经过一个动点。"],
                            ["∵", "两点之间线段最短。"],
                            ["∴", "当固定点、动点、辅助点共线时，路径和取得最小值。"],
                        ],
                        "box": ["最小值转化为一条固定线段长度"],
                    },
                ]
            }
        },
    }


def generic_lesson_mock_few_shot(family_id: str) -> dict[str, Any]:
    return {
        "problem_id": f"fallback-{family_id}-lesson",
        "family_id": family_id,
        "title": "通用讲解示例",
        "original_text": ["抽象示例：先由题设条件推出中间结论，再代入计算最终答案。"],
        "retrieval": {
            "goal_types": [],
            "capability_ids": [],
        },
        "example": {
            "lesson_ir": {
                "steps": [
                    {
                        "id": "mock_step_1",
                        "title": "第1步：整理题设条件，得到可用结论",
                        "source_step_ids": ["mock_step"],
                        "derive": [
                            ["∵", "题目给出了可代入的条件。"],
                            ["∴", "先求出后续会用到的中间量。"],
                        ],
                        "box": ["得到中间结论"],
                    }
                ]
            }
        },
    }


def _collect_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_EXPLANATION_FEW_SHOT_KEYS:
                found.add(key)
            found.update(_collect_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_forbidden_keys(item))
    return found


__all__ = [
    "default_explanation_few_shot_dir",
    "equal_length_ray_lesson_mock_few_shot",
    "generic_lesson_mock_few_shot",
    "lesson_few_shot_path_for_problem",
    "load_lesson_few_shot_entries",
    "select_lesson_few_shot_examples",
    "validate_lesson_few_shot_entry",
]
