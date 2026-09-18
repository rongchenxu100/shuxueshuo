"""Replay explicitly edited response copies; never mutate original live evidence."""

import argparse
import json
import sys
import traceback
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "server/tests/solver")]

from _math_runtime_binding_support import (
    assert_expected,
    binding,
    execution_audit,
    replay_errors,
    reviewed_authority,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_attempt_evidence import write_scoped_attempt_evidence
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import FunctionalCapabilityCatalog
from shuxueshuo_server.solver.runtime.method_math_arguments import MethodMathArgumentResolver
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner


CASE = "tj-2026-hexi-yimo-25"


class RecordedContentPlanner(StrategyPlanner):
    """Feed the same recorded content/v2 wire for either argument encoding."""

    def _recorded_scoped_content(self, inputs):
        return (self.scoped_functional_plan_fixture_dir / f"{inputs.problem_id}.functional-plan-content.json").read_text()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def edit(payload, mode):
    changes = []
    for goal, body in payload["goal_plans"].items():
        for index, step in enumerate(body["steps"]):
            for name, original in list(step.get("args", {}).items()):
                value = original
                if mode != "angle-only" and name in ("curve_point", "curve_points"):
                    if original == "A=(-1,0)":
                        value = "A"
                    elif original == ["A=(-1,0)"]:
                        value = ["A"]
                if mode != "point-only" and name == "right_angle_equal_length":
                    value = "∠CAD=90° ∧ AC=AD"
                if original != value:
                    step["args"][name] = value
                    changes.append({"path": f"$.goal_plans.{goal}.steps[{index}].args.{name}", "before": original, "after": value})
    if mode == "add-c-state":
        body = payload["goal_plans"]["ii.D"]
        index = next(i for i, step in enumerate(body["steps"]) if step["capability_id"] == "right_angle_equal_length_candidates")
        producer = {"step_id": "review_materialize_C", "capability_id": "quadratic_y_axis_intercept_point",
                    "args": {"quadratic": "Γ"}, "output_targets": {"point": "C"},
                    "return_expectations": {"point": "open_state"}}
        body["steps"].insert(index, producer)
        changes.append({"path": f"$.goal_plans.ii.D.steps[{index}]", "operation": "insert", "after": producer})
    if mode == "add-i-state":
        producer = {"step_id": "review_materialize_parabola_i", "capability_id": "quadratic_from_constraints",
                    "args": {"known_coefficients": ["a=1", "b=2", "c=3"], "free_parameters": []},
                    "output_targets": {"parabola": "Γ"}, "return_expectations": {"parabola": "closed_state"}}
        payload["goal_plans"]["i.P"]["steps"].insert(0, producer)
        changes.append({"path": "$.goal_plans.i.P.steps[0]", "operation": "insert", "after": producer})
    return changes


def run(sample, attempt, mode="expression-only"):
    review = BASE / f"hexi-sample-{sample:02d}-review"
    folder = review / "offline-probes" / f"attempt-{attempt}-{mode}"
    folder.mkdir(parents=True, exist_ok=True)
    original = json.loads((review / f"attempt-{attempt}.steps.json").read_text())
    payload = deepcopy(original)
    changes = edit(payload, mode)
    bound = binding(CASE)
    encoding = "math-expression/v1"
    if mode == "source-ref":
        catalog = FunctionalCapabilityCatalog.from_family_spec(bound.inputs.family_spec, bound.inputs.method_specs)
        resolver = MethodMathArgumentResolver(bound.bundle, bound.planning_context, bound.binding_catalog, catalog)
        payload, bindings = resolver.transform(payload)
        encoding = "source-ref"
        save(folder / "math-to-source-bindings.json", bindings)
    save(folder / f"{CASE}.functional-plan-content.json", payload)
    planner = RecordedContentPlanner(
        ContextBuilder().build(bound.bundle.build_solver_problem()),
        problem_authority=reviewed_authority(bound),
        argument_encoding=encoding,
        scoped_functional_plan_fixture_dir=folder,
    )
    record = {"sample": sample, "attempt": attempt, "mode": mode,
              "kind": "offline_counterfactual_not_live_result", "model_calls": 0,
              "argument_encoding": encoding, "changes": changes, "evidence": str(folder.relative_to(review))}
    try:
        result = planner.run_scoped(
            bound.inputs, max_attempts=1,
            attempt_observer=lambda value: write_scoped_attempt_evidence(folder, value),
        )
        record.update(status=result.status, errors=replay_errors(result))
        if result.status == "accepted":
            assert_expected(CASE, bound, result)
            save(folder / "execution-audit.json", execution_audit(bound, result))
            record["expected_answers_match"] = True
    except Exception as exc:
        record.update(status="execution_exception", error_type=type(exc).__name__, error=str(exc))
        record["exception_attributes"] = vars(exc)
        current = exc.__traceback__
        while current is not None:
            if current.tb_frame.f_code.co_name == "_value_binding":
                fields = current.tb_frame.f_locals
                source, value, spec = fields["source"], fields["value"], fields["spec"]
                record["binding_failure_frame"] = {
                    key: fields[key] for key in ("call_id", "capability_id", "arg_name", "item_index", "force_exact_source_versions", "debug_materialized_value")
                }
                record["binding_failure_frame"].update(
                    source=source.to_payload(),
                    requires_materialized_state=spec.requires_materialized_state,
                    resolved_value={name: getattr(value, name, None) for name in ("handle", "runtime_type", "materialized_runtime_type", "valid_scope", "source_kind")},
                )
            current = current.tb_next
        (folder / "exception-traceback.txt").write_text(traceback.format_exc())
        if hasattr(exc, "to_payload"):
            record["error_payload"] = exc.to_payload()
    save(folder / "result.json", record)
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, choices=(2, 3))
    parser.add_argument("--attempt", type=int, choices=(1, 2, 3))
    parser.add_argument("--mode", default="expression-only", choices=("expression-only", "point-only", "angle-only", "add-c-state", "add-i-state", "source-ref"))
    args = parser.parse_args()
    for sample in (args.sample,) if args.sample else (2, 3):
        for attempt in (args.attempt,) if args.attempt else (1, 2, 3):
            run(sample, attempt, args.mode)


if __name__ == "__main__":
    main()
