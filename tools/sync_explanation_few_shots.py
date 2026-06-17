#!/usr/bin/env python3
"""同步 ExplanationBuilder LessonIR few-shot 条目。

用法:
    python tools/sync_explanation_few_shots.py tj-2026-heping-yimo-25

V1 从 ``internal/lesson-specs/<problem_id>/lesson-data.json`` 读取人工讲解步骤，
投射为 ``internal/explanation-few-shots/<problem_id>.lesson-few-shot.json``。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem_id")
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "solver-fixtures",
    )
    parser.add_argument(
        "--lesson-spec-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "lesson-specs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "explanation-few-shots",
    )
    args = parser.parse_args()

    from shuxueshuo_server.solver.explanation.few_shots import (
        lesson_few_shot_path_for_problem,
        validate_lesson_few_shot_entry,
    )

    entry = build_entry(args.problem_id, args.fixture_dir, args.lesson_spec_dir)
    validate_lesson_few_shot_entry(entry)
    output = lesson_few_shot_path_for_problem(
        args.problem_id,
        few_shot_dir=args.output_dir,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


def build_entry(problem_id: str, fixture_dir: Path, lesson_spec_dir: Path) -> dict:
    from shuxueshuo_server.solver import load_problem_ir
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.solver.runtime.projection import RuntimeProjection

    problem = load_problem_ir(str(fixture_dir / f"{problem_id}.json"))
    family = SolverRuntimeConfig(
        planner_mode="strategy",
        llm_provider="recorded",
    ).build_family_registry().match(problem)
    if family is None:
        raise RuntimeError(f"family not found for {problem_id}")
    problem_payload = RuntimeProjection(problem).to_llm_problem_payload()
    lesson_data = json.loads(
        (lesson_spec_dir / problem_id / "lesson-data.json").read_text(encoding="utf-8")
    )
    steps = [
        _lesson_step_payload(step)
        for step in lesson_data.get("steps", [])
    ]
    capability_ids = _capability_ids_from_steps(problem_id)
    entry = {
        "problem_id": problem_id,
        "family_id": family.family_id,
        "title": problem_payload.get("title", problem_id),
        "original_text": list(problem_payload.get("original_text", [])),
        "retrieval": {
            "goal_types": _goal_types_from_problem_payload(problem_payload),
            "capability_ids": capability_ids,
        },
        "example": {
            "lesson_ir": {
                "steps": steps,
            }
        },
    }
    return entry


def _lesson_step_payload(step: dict) -> dict:
    return {
        "id": str(step.get("id", "")),
        "title": str(step.get("title", "")),
        "source_step_ids": [str(step.get("id", ""))],
        "derive": [
            [str(item[0]), str(item[1])]
            for item in step.get("body", [])
            if isinstance(item, list) and len(item) == 2
        ],
        "box": [],
    }


def _goal_types_from_problem_payload(problem_payload: dict) -> list[str]:
    result: list[str] = []
    for goal in problem_payload.get("question_goals", []):
        value_type = str(goal.get("value_type", ""))
        if value_type == "Parabola":
            item = "derive_parabola"
        elif value_type == "Point":
            item = "derive_constructed_point"
        elif value_type == "ParameterValue":
            item = "derive_parameter"
        elif value_type == "MinimumExpression":
            item = "derive_path_minimum_expression"
        else:
            item = value_type or "derive_unknown"
        if item not in result:
            result.append(item)
    return result


def _capability_ids_from_steps(problem_id: str) -> list[str]:
    path = REPO_ROOT / "internal" / "solver-fixtures" / f"{problem_id}.executable-step-intents.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    result: list[str] = []
    for scope in data.get("scopes", []):
        for step in scope.get("steps", []):
            capability = step.get("recipe_hint")
            if isinstance(capability, str) and capability and capability not in result:
                result.append(capability)
    return result


if __name__ == "__main__":
    main()
