"""Strategy Planner few-shot 条目读写与选择。

few-shot 是题库到 Strategy Planner prompt 的投射层。这里不重新发明解题步骤，
只读取已验证的 executable StepIntent，并按 family/goal_types 选择一个最相似
示例给 prompt 使用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from shuxueshuo_server.solver.runtime._paths import repo_root


FORBIDDEN_FEW_SHOT_KEYS = frozenset(
    {
        "schema_version",
        "source",
        "expected",
        "expected_answers",
    }
)


def default_few_shot_dir() -> Path:
    """返回默认 few-shot 目录。"""
    return repo_root(Path(__file__)) / "internal" / "few-shots"


def few_shot_path_for_problem(problem_id: str, *, few_shot_dir: Path | str | None = None) -> Path:
    """按约定生成 ``<problem_id>.few-shot.json`` 路径。"""
    root = Path(few_shot_dir) if few_shot_dir is not None else default_few_shot_dir()
    return root / f"{problem_id}.few-shot.json"


def build_few_shot_entry(
    *,
    problem_payload: dict[str, Any],
    executable_step_intents: dict[str, Any],
    family_id: str,
) -> dict[str, Any]:
    """由 LLM ProblemIR 与 executable StepIntent 生成 few-shot 条目。"""
    problem_id = str(problem_payload["problem_id"])
    scopes = list(executable_step_intents.get("scopes", ()))
    goal_types = goal_types_from_scopes(scopes)
    entry = {
        "problem_id": problem_id,
        "family_id": family_id,
        "title": problem_payload.get("title", problem_id),
        "original_text": list(problem_payload.get("original_text", ())),
        "retrieval": {
            "goal_types": goal_types,
        },
        "example": {
            "scopes": scopes,
        },
    }
    validate_few_shot_entry(entry)
    return entry


def write_few_shot_entry(entry: dict[str, Any], path: Path | str) -> None:
    """写入 pretty JSON，并创建父目录。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_few_shot_entries(*, few_shot_dir: Path | str | None = None) -> list[dict[str, Any]]:
    """加载目录中的所有 few-shot 条目。"""
    root = Path(few_shot_dir) if few_shot_dir is not None else default_few_shot_dir()
    if not root.exists():
        return []
    entries: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.few-shot.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        validate_few_shot_entry(entry)
        entries.append(entry)
    return entries


def select_few_shot_examples(
    *,
    family_id: str,
    goal_types: Iterable[str],
    problem_id: str | None = None,
    allow_same_problem: bool = True,
    top_k: int = 1,
    few_shot_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """按 family 与 goal_type 重叠度选择 few-shot。

    V1 固定只需要 ``top_k=1``，但保留参数让测试能覆盖排序行为。生产默认允许
    同题命中；测试可传 ``allow_same_problem=False`` 验证泛化。
    """
    if top_k <= 0:
        return []
    query = tuple(dict.fromkeys(goal_types))
    entries = load_few_shot_entries(few_shot_dir=few_shot_dir)
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    query_set = set(query)
    for entry in entries:
        if entry["family_id"] != family_id:
            continue
        if not allow_same_problem and problem_id and entry["problem_id"] == problem_id:
            continue
        entry_goal_types = tuple(entry["retrieval"]["goal_types"])
        overlap = len(query_set.intersection(entry_goal_types))
        # 覆盖更多 goal_type 的样例通常更有用；problem_id 作为稳定 tie-breaker。
        candidates.append((overlap, len(entry_goal_types), entry["problem_id"], entry))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [entry for *_prefix, entry in candidates[:top_k]]


def goal_types_from_scopes(scopes: Iterable[dict[str, Any]]) -> list[str]:
    """从 ``scopes[].steps[].goal_type`` 按首次出现顺序去重。"""
    goal_types: list[str] = []
    seen: set[str] = set()
    for scope in scopes:
        for step in scope.get("steps", ()):
            goal_type = step.get("goal_type")
            if not isinstance(goal_type, str) or not goal_type:
                continue
            if goal_type in seen:
                continue
            seen.add(goal_type)
            goal_types.append(goal_type)
    return goal_types


def validate_few_shot_entry(entry: dict[str, Any]) -> None:
    """轻量校验 few-shot V1 结构。"""
    forbidden = sorted(_collect_forbidden_keys(entry))
    if forbidden:
        raise ValueError(f"few-shot contains forbidden keys: {forbidden}")
    required = {"problem_id", "family_id", "original_text", "retrieval", "example"}
    missing = sorted(required - set(entry))
    if missing:
        raise ValueError(f"few-shot missing required keys: {missing}")
    if not isinstance(entry["original_text"], list):
        raise TypeError("few-shot original_text must be a list")
    scopes = entry.get("example", {}).get("scopes")
    if not isinstance(scopes, list):
        raise TypeError("few-shot example.scopes must be a list")
    expected_goal_types = goal_types_from_scopes(scopes)
    actual_goal_types = entry.get("retrieval", {}).get("goal_types")
    if actual_goal_types != expected_goal_types:
        raise ValueError(
            "few-shot retrieval.goal_types must equal unique example.scopes[].steps[].goal_type"
        )
    serialized = json.dumps(entry, ensure_ascii=False)
    if "$problem." in serialized or "$question." in serialized or "$subquestion." in serialized:
        raise ValueError("few-shot must not contain runtime ContextPath values")


def _collect_forbidden_keys(value: Any) -> set[str]:
    """递归收集禁用字段名。"""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_FEW_SHOT_KEYS:
                found.add(key)
            found.update(_collect_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_forbidden_keys(item))
    return found
