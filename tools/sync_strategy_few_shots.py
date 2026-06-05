#!/usr/bin/env python3
"""同步 Strategy Planner few-shot 条目。

用法：
    python tools/sync_strategy_few_shots.py tj-2026-nankai-yimo-25

工具从 ``internal/solver-fixtures`` 读取同名 canonical ProblemIR fixture 和
``.executable-step-intents.json``，生成 ``internal/few-shots/<problem_id>.few-shot.json``。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY  # noqa: E402
from shuxueshuo_server.solver.fixtures import load_problem_ir  # noqa: E402
from shuxueshuo_server.solver.runtime.strategy_few_shots import (  # noqa: E402
    build_few_shot_entry,
    few_shot_path_for_problem,
    write_few_shot_entry,
)
from shuxueshuo_server.solver.runtime.projection import (  # noqa: E402
    problem_to_llm_payload,
)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem_ids", nargs="+", help="要同步的 problem_id")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "solver-fixtures",
        help="solver fixture 目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "few-shots",
        help="few-shot 输出目录",
    )
    args = parser.parse_args(argv)

    for problem_id in args.problem_ids:
        output_path = sync_one(
            problem_id,
            fixtures_dir=args.fixtures_dir,
            output_dir=args.output_dir,
        )
        print(output_path)
    return 0


def sync_one(problem_id: str, *, fixtures_dir: Path, output_dir: Path) -> Path:
    """同步单个 problem_id，并返回输出路径。"""
    runtime_fixture = fixtures_dir / f"{problem_id}.json"
    executable_fixture = fixtures_dir / f"{problem_id}.executable-step-intents.json"
    for path in (runtime_fixture, executable_fixture):
        if not path.exists():
            raise FileNotFoundError(path)

    problem = load_problem_ir(runtime_fixture)
    if problem.problem_id != problem_id:
        raise ValueError(f"runtime fixture problem_id mismatch: {problem.problem_id}")
    family = DEFAULT_FAMILY_REGISTRY.match(problem)
    if family is None:
        raise ValueError(f"no family matched for {problem_id}")

    problem_payload = problem_to_llm_payload(problem)
    executable_payload = _read_json(executable_fixture)
    entry = build_few_shot_entry(
        problem_payload=problem_payload,
        executable_step_intents=executable_payload,
        family_id=family.family_id,
    )
    output_path = few_shot_path_for_problem(problem_id, few_shot_dir=output_dir)
    write_few_shot_entry(entry, output_path)
    return output_path


def _read_json(path: Path) -> dict[str, Any]:
    """读取 JSON object。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
