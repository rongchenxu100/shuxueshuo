"""Verify argument-encoding controls and archive compact original-run metadata."""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "server/tests/solver")]

from _math_runtime_binding_support import binding
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import FunctionalCapabilityCatalog
from shuxueshuo_server.solver.runtime.functional_plan_content import FunctionalPlanAuthorityFrame, FunctionalPlanContentCompiler
from shuxueshuo_server.solver.runtime.method_math_arguments import MethodMathArgumentResolver


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def main():
    bound = binding("tj-2026-hexi-yimo-25")
    catalog = FunctionalCapabilityCatalog.from_family_spec(bound.inputs.family_spec, bound.inputs.method_specs)
    resolver = MethodMathArgumentResolver(bound.bundle, bound.planning_context, bound.binding_catalog, catalog)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    for sample in (2, 3):
        folder = BASE / f"hexi-sample-{sample:02d}-review"
        analysis = json.loads((folder / "analysis.json").read_text())
        original = Path(analysis["source"])
        result = json.loads((original / "result.json").read_text())
        save(folder / "original-result.json", result)
        assert all(a["metadata"]["provider_attempts"][0]["finish_reason"] == "stop" for a in analysis["attempts"])
        for a in analysis["attempts"]:
            assert not a["runtime_reuse"]["execution_started"]
            assert not a["runtime_reuse"]["executed_call_ids"]
            assert "∧" not in (folder / f"attempt-{a['number']}.prompt.user.md").read_text()
            assert "∧" not in (folder / f"attempt-{a['number']}.prompt.system.md").read_text()
        probes = [json.loads(p.read_text()) for p in sorted((folder / "offline-probes").glob("*/result.json"))]
        save(folder / "counterfactual-results.json", probes)
        context = json.loads((folder / "attempt-1.context.json").read_text())
        relevant = [c for c in context["functional_capability_catalog"]["capabilities"] if c["capability_id"] in {"quadratic_vertex_point", "right_angle_equal_length_candidates", "curve_candidate_parameter_solve", "quadratic_from_constraints"}]
        save(folder / "relevant-catalog.json", relevant)
    folder = BASE / "hexi-sample-03-review"
    controls = []
    for attempt in (1, 3):
        math_folder = folder / "offline-probes" / f"attempt-{attempt}-expression-only"
        source_folder = folder / "offline-probes" / f"attempt-{attempt}-source-ref"
        name = "tj-2026-hexi-yimo-25.functional-plan-content.json"
        math_payload = json.loads((math_folder / name).read_text())
        source_payload = json.loads((source_folder / name).read_text())
        expected_source, _ = resolver.transform(math_payload)
        assert source_payload == expected_source
        math_compilation = FunctionalPlanContentCompiler().compile_payload(math_payload, frame=frame, capability_catalog=catalog, math_argument_resolver=resolver)
        source_compilation = FunctionalPlanContentCompiler().compile_payload(source_payload, frame=frame, capability_catalog=catalog)
        math_plan = math_compilation.plan.to_payload()
        source_plan = source_compilation.plan.to_payload()
        assert math_plan == source_plan
        save(math_folder / "review-canonical-plan.json", math_plan)
        save(source_folder / "review-canonical-plan.json", source_plan)
        math_result = json.loads((math_folder / "result.json").read_text())
        source_result = json.loads((source_folder / "result.json").read_text())
        key = "errors" if attempt == 1 else "error"
        assert math_result[key] == source_result[key]
        if attempt == 3:
            assert math_result["binding_failure_frame"] == source_result["binding_failure_frame"]
        controls.append({"attempt": attempt, "source_payload_exactly_matches_transform": True, "canonical_plan_equal": True,
                         "canonical_plan_sha256": digest(math_plan), "same_blocker": math_result[key],
                         "binding_failure_frame": math_result.get("binding_failure_frame"), "model_calls": 0})
    save(folder / "encoding-controls.json", controls)
    extra = []
    for text in ("∠CAD∈90°, AC=AD", "∠CAD∈90° ∧ AC=AD", "∠CAD=90° ∧ AC=AD"):
        row = {"expression": text, "scope": "ii"}
        try:
            ref, audit = resolver.resolve("right_angle_equal_length_candidates", "right_angle_equal_length", text, scope_id="ii")
            row.update(status="bound", source_ref=ref, audit=audit)
        except Exception as exc:
            row.update(status="rejected", error_type=type(exc).__name__, error=str(exc))
        extra.append(row)
    save(BASE / "hexi-sample-02-review" / "angle-membership-probes.json", extra)
    print(json.dumps({"encoding_controls": controls, "angle_probes": extra}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
