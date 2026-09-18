"""Controlled offline input edits; original live artifacts remain immutable."""

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "server/tests/solver")]

from _math_runtime_binding_support import assert_expected, binding, execution_audit, replay_errors, reviewed_authority
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_attempt_evidence import write_scoped_attempt_evidence
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner


def main():
    case = "tj-2026-hexi-yimo-25"
    bound = binding(case)
    records = []
    for n, point, angle, argument_name in [(1, True, False, False), (1, False, True, False), (1, True, True, False), (2, False, True, False), (3, False, True, False), (3, False, True, True)]:
        label = f"attempt-{n}-" + ("point-and-angle" if point and angle else "point" if point else "angle")
        if argument_name:
            label += "-and-argument-name"
        folder = OUT / "offline-probes" / label
        folder.mkdir(parents=True, exist_ok=True)
        original = json.loads((OUT / f"attempt-{n}.steps.json").read_text())
        payload = deepcopy(original)
        changes = []
        for goal, body in payload["goal_plans"].items():
            for i, step in enumerate(body.get("steps", [])):
                if argument_name and step['capability_id'] == 'quadratic_y_axis_intercept_point':
                    previous = deepcopy(step['args'])
                    step['args']['quadratic'] = step['args'].pop('parabola')
                    changes.append({'path': f'$.goal_plans.{goal}.steps[{i}].args', 'before': previous, 'after': deepcopy(step['args'])})
                for name, old in list(step.get("args", {}).items()):
                    new = old
                    if point and name == "curve_points" and old == ["A=(-1,0)"]:
                        new = ["A"]
                    if angle and name == "right_angle_equal_length":
                        new = "∠CAD=90° ∧ AC=AD"
                    if old != new:
                        step["args"][name] = new
                        changes.append({"path": f"$.goal_plans.{goal}.steps[{i}].args.{name}", "before": old, "after": new})
        (folder / f"{case}.functional-plan-content.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        planner = StrategyPlanner(ContextBuilder().build(bound.bundle.build_solver_problem()), problem_authority=reviewed_authority(bound), argument_encoding="math-expression/v1", scoped_functional_plan_fixture_dir=folder)
        result = planner.run_scoped(bound.inputs, max_attempts=1, attempt_observer=lambda attempt: write_scoped_attempt_evidence(folder, attempt))
        record = {"label": label, "origin_semantic_attempt": n, "kind": "offline_counterfactual_not_live_result", "model_calls": 0, "changes": changes, "status": result.status, "errors": replay_errors(result)}
        if result.status == "accepted":
            assert_expected(case, bound, result)
            audit = execution_audit(bound, result)
            (folder / "execution-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
            record["expected_answers_match"] = True
        records.append(record)
        print(label, result.status, record["errors"], flush=True)
    (OUT / "counterfactual-results.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
