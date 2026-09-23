"""Rebuild/check the representative ten; optionally freeze a fresh live batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shuxueshuo_server.problem_understanding.basic_inequality_frozen import (
    freeze_runs,
    write_json,
)
from shuxueshuo_server.problem_understanding.basic_inequality_problem_ir import (
    REPRESENTATIVE_CASES,
    build_problem_ir_from_file,
)

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "tests/solver/fixtures/math-notation-v1/basic-inequality"
OUTPUT = ROOT / "tests/solver/fixtures/basic-inequality-problem-ir/v1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--freeze-batch", type=Path, help="A completed real run_batch output directory"
    )
    parser.add_argument(
        "--check", action="store_true", help="Verify existing artifacts without writing"
    )
    args = parser.parse_args()
    if args.freeze_batch and args.check:
        parser.error("--freeze-batch and --check are mutually exclusive")
    if args.freeze_batch:
        freeze_runs(
            GOLD,
            {
                case: [
                    args.freeze_batch / case / f"sample-{number:02d}" / "run"
                    for number in (1, 2)
                ]
                for case in REPRESENTATIVE_CASES
            },
        )
    artifacts = {
        case: build_problem_ir_from_file(GOLD / f"{case}.json")
        for case in REPRESENTATIVE_CASES
    }
    for case, artifact in artifacts.items():
        directory = OUTPUT / case
        for name, payload in (
            ("problem-ir.json", artifact),
            ("provenance.json", artifact["provenance"]),
        ):
            if args.check:
                if json.loads((directory / name).read_text()) != payload:
                    raise ValueError(f"stale generated artifact: {case}/{name}")
            else:
                directory.mkdir(parents=True, exist_ok=True)
                write_json(directory / name, payload)
    print("20/20 frozen samples replayed; 10/10 ProblemIR matched (authoring-only)")


if __name__ == "__main__":
    main()
