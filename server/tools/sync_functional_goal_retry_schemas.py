"""Write checked-in Functional Goal retry schema snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    functional_diagnostic_authority_schema,
    functional_prompt_diagnostic_schema,
)
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    functional_goal_execution_checkpoint_schema,
    verified_functional_plan_execution_schema,
)
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    path_minimum_witness_schema,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    functional_goal_repair_schema,
    planner_goal_retry_context_schema,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    macro_runtime_search_report_schema,
)
from shuxueshuo_server.solver.runtime.problem_source_provenance import (
    problem_call_source_provenance_schema,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    scoped_functional_plan_schema,
)


def main() -> None:
    destination = Path(__file__).resolve().parents[2] / "internal" / "schemas"
    schemas = {
        "functional-diagnostic-authority.schema.json": (
            functional_diagnostic_authority_schema()
        ),
        "functional-prompt-diagnostic.schema.json": (
            functional_prompt_diagnostic_schema()
        ),
        "functional-goal-execution-checkpoint.schema.json": (
            functional_goal_execution_checkpoint_schema()
        ),
        "verified-functional-plan-execution.schema.json": (
            verified_functional_plan_execution_schema()
        ),
        "path-minimum-witness.schema.json": path_minimum_witness_schema(),
        "functional-goal-repair.schema.json": functional_goal_repair_schema(),
        "planner-goal-retry-context.schema.json": (
            planner_goal_retry_context_schema()
        ),
        "functional-plan-v2.schema.json": scoped_functional_plan_schema(),
        "problem-call-source-provenance.schema.json": (
            problem_call_source_provenance_schema()
        ),
        "macro-runtime-search-report.schema.json": (
            macro_runtime_search_report_schema()
        ),
    }
    for name, schema in schemas.items():
        (destination / name).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
