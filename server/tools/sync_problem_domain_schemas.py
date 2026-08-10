"""Write the checked-in extraction domain JSON Schemas from code authority."""

from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.extraction.problem_domain import (
    problem_domain_schema,
    problem_repair_schema,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    solver_problem_projection_schema,
)


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    destination = ROOT / "internal/schemas"
    schemas = {
        "problem-domain.schema.json": problem_domain_schema(),
        "problem-repair.schema.json": problem_repair_schema(),
        "solver-problem-projection.schema.json": solver_problem_projection_schema(),
    }
    for name, payload in schemas.items():
        (destination / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(name)


if __name__ == "__main__":
    main()
