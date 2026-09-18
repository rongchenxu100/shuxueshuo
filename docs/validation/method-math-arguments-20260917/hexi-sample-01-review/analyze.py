"""Read-only review of the frozen Hexi sample; never sends model requests."""

import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
CASE = "tj-2026-hexi-yimo-25"
SAMPLE = ROOT / "internal/solver-runs/method-math-arguments-20260917/live" / CASE / "math/1"
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "server/tests/solver")]

from _math_runtime_binding_support import binding
from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.notation_compile import typecheck
from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import FunctionalCapabilityCatalog
from shuxueshuo_server.solver.runtime.functional_plan_content import FunctionalPlanAuthorityFrame, FunctionalPlanContentCompiler
from shuxueshuo_server.solver.runtime.method_math_arguments import MethodMathArgumentError, MethodMathArgumentResolver


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def steps(plan):
    for scope, values in plan.get("scope_steps", {}).items():
        for i, step in enumerate(values):
            yield scope, None, f"$.scope_steps.{scope}[{i}]", step
    for goal, value in plan.get("goal_plans", {}).items():
        for i, step in enumerate(value.get("steps", [])):
            yield goal.split(".", 1)[0], goal, f"$.goal_plans.{goal}.steps[{i}]", step


def main():
    bound = binding(CASE)
    catalog = FunctionalCapabilityCatalog.from_family_spec(bound.inputs.family_spec, bound.inputs.method_specs)
    resolver = MethodMathArgumentResolver(bound.bundle, bound.planning_context, bound.binding_catalog, catalog)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    data = {"case": CASE, "sample": 1, "source": str(SAMPLE), "model_calls": 0, "attempts": [], "sample_prompt_comparison": []}
    for n in range(1, 4):
        stem = f"attempt-{n}"
        index = read(SAMPLE / f"{stem}.evidence-index.json")
        checked = []
        for role, artifact in index["artifacts"].items():
            if artifact["status"] == "saved":
                actual = digest((SAMPLE / artifact["file"]).read_bytes())
                assert actual == artifact["sha256"], (n, role)
                checked.append(role)
        request = read(SAMPLE / f"{stem}.request.json")
        payload = request["planner_payload"]
        provider_request = read(SAMPLE / f"{stem}.provider-requests.json")[0]
        assert provider_request["messages"] == request["messages"]
        raw = read(SAMPLE / f"{stem}.raw-response.json")
        assert raw["parse_error"] is None
        plan = raw["parsed"]
        assert plan == read(SAMPLE / f"{stem}.normalized-content.json")
        meta = read(SAMPLE / f"{stem}.provider-metadata.json")
        feedback = payload["authoring_feedback"]
        for message in request["messages"]:
            (OUT / f"{stem}.prompt.{message['role']}.md").write_text(message["content"])
        (OUT / f"{stem}.raw-response.txt").write_text(raw["text"])
        save(OUT / f"{stem}.steps.json", plan)
        save(OUT / f"{stem}.context.json", payload)
        reasoning = read(SAMPLE / f"{stem}.provider-reasoning.json")["attempts"][0]["reasoning_content"]
        (OUT / f"{stem}.reasoning.txt").write_text(reasoning)
        sections = []
        user = next(m["content"] for m in request["messages"] if m["role"] == "user")
        markers = list(re.finditer(r"^## .+$", user, re.M))
        for i, match in enumerate(markers):
            text = user[match.start(): markers[i + 1].start() if i + 1 < len(markers) else len(user)]
            sections.append({"name": match.group(), "chars": len(text), "bytes": len(text.encode()), "sha256": digest(text)})
        arg_checks = []
        graph = []
        for scope, goal, path, step in steps(plan):
            graph.append({"scope": scope, "goal": goal, "path": path, "step": step, "runtime_status": "NOT EXECUTED", "actual_result": None})
            for field in ("args", "output_targets"):
                for name, value in step.get(field, {}).items():
                    for i, item in enumerate(value if isinstance(value, list) else [value]):
                        if not isinstance(item, str):
                            continue
                        location = f"{path}.{field}.{name}" + (f"[{i}]" if isinstance(value, list) else "")
                        record = {"path": location, "step_id": step["step_id"], "capability_id": step["capability_id"], "scope": scope, "field": field, "argument": name, "expression": item}
                        try:
                            ref, audit = resolver.resolve(step["capability_id"], name, item, scope_id=scope, path=location, output=field == "output_targets")
                            record.update({"status": "bound_in_isolation", "ref": ref, "audit": audit})
                        except MethodMathArgumentError as exc:
                            record.update({"status": "invalid_in_isolation", "error": exc.to_payload()})
                        arg_checks.append(record)
        compilation = FunctionalPlanContentCompiler().compile_payload(plan, frame=frame, capability_catalog=catalog, math_argument_resolver=resolver)
        assert compilation.plan is None
        assert [v.to_payload() for v in compilation.report.issues] == read(SAMPLE / f"{stem}.content-validation.json")["issues"]
        schema_errors = list(Draft202012Validator(payload["output_json_schema"]).iter_errors(plan))
        usage = meta["provider_attempts"][0]["usage"]
        record = {
            "number": n, "protocol": meta["planner_protocol"], "metadata": meta,
            "provider_options": {k: v for k, v in provider_request.items() if k != "messages"},
            "provider_prompt_matches_saved_messages": True,
            "artifact_hashes_checked": checked, "index": index,
            "system_sha256": digest(request["messages"][0]["content"]), "user_sha256": digest(user),
            "system_chars": len(request["messages"][0]["content"]), "user_chars": len(user), "prompt_sections": sections,
            "thinking_chars": len(reasoning), "thinking_tokens": usage["completion_tokens_details"]["reasoning_tokens"],
            "visible_tokens_by_subtraction": usage["completion_tokens"] - usage["completion_tokens_details"]["reasoning_tokens"],
            "visible_chars": len(raw["text"]), "feedback_received": feedback,
            "previous_plan_sent": "previous_invalid_content" in payload or "annotated_previous_plan" in payload,
            "execution_tree_sent": "retry_execution_tree" in payload,
            "graph": graph, "isolated_argument_checks": arg_checks,
            "actual_failure": read(SAMPLE / f"{stem}.attempt-error.json"),
            "runtime_reuse": read(SAMPLE / f"{stem}.reuse.json"),
            "raw_equals_saved_normalized_content": True,
            "standalone_prompt_schema_check": {"ok": not schema_errors, "errors": [{"path": list(e.path), "message": e.message[:400]} for e in schema_errors]},
        }
        save(OUT / f"{stem}.isolated-arguments.json", arg_checks)
        data["attempts"].append(record)
    for sample in range(1, 4):
        folder = SAMPLE.parent / str(sample)
        r = read(folder / "attempt-1.request.json")
        data["sample_prompt_comparison"].append({"sample": sample, "system_sha256": digest(r["messages"][0]["content"]), "user_sha256": digest(r["messages"][1]["content"]), "catalog_sha256": digest(json.dumps(r["planner_payload"]["functional_capability_catalog"],sort_keys=True,ensure_ascii=False)), "schema_sha256": digest(json.dumps(r["planner_payload"]["output_json_schema"],sort_keys=True,ensure_ascii=False))})
    save(OUT / "analysis.json", data)
    # Controlled probes: these do not modify production parsing or any sample.
    probes = []
    for text, arg in [("A", "curve_point"), ("A=(-1,0)", "curve_point"), ("∠CAD=90°, AC=AD", "right_angle_equal_length"), ("∠CAD=90° ∧ AC=AD", "right_angle_equal_length"), ("AC=AD ∧ ∠CAD=90°", "right_angle_equal_length"), ("D ∈ {X | ∠CAX=90°, AX=AC}", "right_angle_equal_length")]:
        cap = "quadratic_from_constraints" if arg == "curve_point" else "right_angle_equal_length_candidates"
        row = {"expression": text, "scope": "ii", "capability": cap, "argument": arg}
        try:
            ast = parse(text)
            row.update({"ast": ast, "type": typecheck(resolver.environments["ii"].bind(deepcopy(ast)))})
            ref, audit = resolver.resolve(cap, arg, text, scope_id="ii")
            row.update({"status": "resolved", "ref": ref, "audit": audit})
        except Exception as exc:
            row.update({"status": "rejected", "error_type": type(exc).__name__, "message": str(exc)})
        probes.append(row)
    save(OUT / "parser-probes.json", {"kind": "offline_probe_not_live_evidence", "model_calls": 0, "probes": probes})
    print(json.dumps({"attempts": [{"n": a["number"], "steps": len(a["graph"]), "schema_ok_in_isolation": a["standalone_prompt_schema_check"]["ok"], "invalid_arguments": [r["path"] for r in a["isolated_argument_checks"] if r["status"] == "invalid_in_isolation"]} for a in data["attempts"]], "same_first_prompt": len({r['user_sha256'] for r in data['sample_prompt_comparison']}) == 1}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
