#!/usr/bin/env python3
"""Regenerate FunctionalPlan mechanism few-shot assets.

Usage::

    python tools/sync_strategy_few_shots.py
    python tools/sync_strategy_few_shots.py quadratic-constraints-vertex

Each manifest selects a closed subgraph from an authored FunctionalPlan fixture.
The tool preserves an asset's optional human-authored annotation and
deterministically regenerates its ``functional_plan/v1`` example.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = REPO_ROOT / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from shuxueshuo_server.solver.runtime.functional_few_shots import (  # noqa: E402
    FunctionalFewShotEntry,
    load_functional_plan_fixture,
    project_functional_few_shot_prompt_example,
    split_functional_few_shot_asset,
    validate_functional_few_shot_entry,
)


def main(argv: list[str] | None = None) -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "example_ids",
        nargs="*",
        help="example id；省略时同步全部 manifest",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "functional-few-shot-manifests",
        help="functional few-shot manifest 目录",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "functional-plan-fixtures",
        help="authored FunctionalPlan fixture 目录",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "internal" / "functional-few-shots",
        help="FunctionalPlan few-shot 输出目录",
    )
    args = parser.parse_args(argv)

    example_ids = args.example_ids or [
        path.name.removesuffix(".manifest.json")
        for path in sorted(args.manifest_dir.glob("*.manifest.json"))
    ]
    if not example_ids:
        parser.error(f"no manifests found in {args.manifest_dir}")
    for example_id in example_ids:
        output_path = sync_one(
            example_id,
            manifest_dir=args.manifest_dir,
            fixture_dir=args.fixture_dir,
            output_dir=args.output_dir,
        )
        print(output_path)
    return 0


def sync_one(
    example_id: str,
    *,
    manifest_dir: Path,
    fixture_dir: Path,
    output_dir: Path,
) -> Path:
    """Regenerate one annotated mechanism example."""
    manifest_path = manifest_dir / f"{example_id}.manifest.json"
    output_path = output_dir / f"{example_id}.functional-few-shot.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    if not output_path.exists():
        raise FileNotFoundError(
            f"annotation source is missing for {example_id}: {output_path}"
        )

    entry = FunctionalFewShotEntry.from_payload(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    source_plan = load_functional_plan_fixture(
        entry.source_problem_id,
        fixture_dir=fixture_dir,
    )
    validate_functional_few_shot_entry(entry, source_plan=source_plan)
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    annotation, _stored_plan = split_functional_few_shot_asset(stored)
    payload = project_functional_few_shot_prompt_example(
        replace(entry, annotation=annotation),
        source_plan=source_plan,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    raise SystemExit(main())
