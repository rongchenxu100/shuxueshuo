"""Review-only mathematical Planner view; the production prompt is unchanged."""

from copy import deepcopy

from shuxueshuo_server.solver.extraction.source_identity import thaw_json
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)

from .runtime_lowering import BindingError


def compact_problem(binding, *, scope_path=(), execution=None):
    raw = thaw_json(binding.bundle.candidate)
    root = deepcopy(raw["root"])
    indices = tuple(scope_path)
    node = root
    labels = []
    for index in indices:
        if type(index) is not int or not 0 <= index < len(node.get("children", [])):
            raise BindingError(
                "planner.scope_unresolved",
                "/planning_scope",
                "scope path is not in this candidate",
            )
        child = node["children"][index]
        labels.append(child.get("label", "题目"))
        # Retain the ancestor chain with its original mathematical conditions.
        node.pop("goals", None)
        node["children"] = [child]
        node = child
    results = []
    if execution is not None:
        from shuxueshuo_server.solver.runtime.functional_goal_execution import (
            VerifiedFunctionalPlanExecution,
        )

        if not isinstance(execution, VerifiedFunctionalPlanExecution):
            raise BindingError(
                "planner.unverified_result",
                "/known_results",
                "only verified committed execution is accepted",
            )
        expected = binding.planning_context
        if (
            execution.planning_context_id,
            execution.problem_revision_id,
            execution.problem_semantic_hash,
        ) != (
            expected.planning_context_id,
            expected.problem_revision_id,
            expected.problem_semantic_hash,
        ):
            raise BindingError(
                "planner.result_version_changed",
                "/known_results",
                "execution belongs to another source snapshot",
            )
        scopes = {s.scope_id: s for s in expected.scopes}
        owner_by_id = {
            s.scope_id: binding.bundle.provenance[s.source_scope_unit_id]["path"]
            for s in expected.scopes
        }
        selected = "/root" + "".join(f"/children/{i}" for i in indices)
        goals = {g.goal_unit_id: g for g in expected.goal_views}
        goal_by_ref = {g.answer_ref.ref: g for g in goals.values()}
        steps = {}

        def collect(scope):
            for step in (
                *scope.scope_steps,
                *(s for g in scope.goals for s in g.steps),
            ):
                if step.status == "runtime_verified":
                    steps[step.step_id] = step
            for c in scope.children:
                collect(c)

        collect(execution.root_scope)

        def visit(scope):
            owner = owner_by_id[scope.scope_ref]
            if indices and not (
                selected == owner or selected.startswith(owner + "/children/")
            ):
                return
            for goal in scope.goals:
                view = goal_by_ref[goal.goal_ref]
                source = goal.answer_from
                step = steps.get(source.step_id)
                output = (
                    next(
                        (
                            v
                            for v in step.actual_outputs
                            if v["return"] == source.return_name
                        ),
                        None,
                    )
                    if step
                    else None
                )
                if output is None:
                    continue
                pointer = binding.bundle.provenance[view.goal_unit_id]["path"]
                source_goal = raw
                for component in pointer.strip("/").split("/"):
                    source_goal = (
                        source_goal[int(component)]
                        if isinstance(source_goal, list)
                        else source_goal[component]
                    )
                expression = result_expression(source_goal, output)
                if expression is not None:
                    chain = []
                    current = scope.scope_ref
                    while scopes[current].parent_scope_id is not None:
                        chain.insert(0, scopes[current].label)
                        current = scopes[current].parent_scope_id
                    results.append({"scope_path": chain, "facts": [expression]})
            for c in scope.children:
                visit(c)

        visit(execution.canonical_plan.root_scope)
    return {
        "problem_id": binding.bundle.problem_id,
        "planning_scope": labels if indices else "all",
        "scope_policy": "ancestors_only",
        "solution_policy": "all",
        "known_results": results,
        "root": root,
    }


def result_expression(goal, output):
    target = goal.get("object") or goal.get("expression")
    if goal["kind"] == "find_minimum":
        target = f"min({target})"

    def math(value):
        return str(value).replace("**", "^")

    value = output.get("value")
    kind = output.get("runtime_type")
    if kind == "Point" and isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{target} = ({math(value[0])},{math(value[1])})"
    if (
        kind == "PointList"
        and isinstance(value, (list, tuple))
        and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in value)
    ):
        points = ",".join(f"({math(p[0])},{math(p[1])})" for p in value)
        return f"{target} ∈ {{{points}}}"
    if kind == "Parabola" and isinstance(value, str):
        return f"{target}: y = {math(value)}"
    if kind in ("Expression", "ParameterValue", "MinimumExpression") and isinstance(
        value, (str, int, float)
    ):
        return f"{target} = {math(value)}"
    # Do not guess an expression from a serialized runtime/debug structure.
    return None


def compact_methods(binding):
    from shuxueshuo_server.solver.runtime.capability_math_signatures import (
        MATH_PRECONDITIONS,
    )

    full = FunctionalCapabilityCatalog.from_family_spec(
        binding.inputs.family_spec, binding.inputs.method_specs
    ).to_prompt_payload()
    missing = {
        item["capability_id"] for item in full["capabilities"]
    } - MATH_PRECONDITIONS.keys()
    if missing:
        raise BindingError(
            "planner.math_signature_missing", "/methods", str(sorted(missing))
        )
    return {
        "capabilities": [
            {
                "method": item["capability_id"],
                "args": [
                    {
                        k: v
                        for k, v in arg.items()
                        if k in ("name", "domain_type", "required", "cardinality")
                    }
                    for arg in item.get("args", [])
                ],
                "returns": [
                    {k: v for k, v in out.items() if k in ("name", "type", "required")}
                    for out in item.get("returns", [])
                ],
                "preconditions": MATH_PRECONDITIONS[item["capability_id"]],
            }
            for item in full["capabilities"]
        ]
    }


def coverage(binding):
    index = binding.bundle.projection_index
    rows = []
    source_nodes = {}

    def compile_paths(raw, compiled, path="/root"):
        offset = 0
        for name in ("definitions", "facts"):
            for i in range(len(raw.get(name, []))):
                source_nodes[f"{path}/{name}/{i}"] = compiled["facts"][offset]
                offset += 1
        for i, g in enumerate(compiled["goals"]):
            source_nodes[f"{path}/goals/{i}"] = g
        for i, (r, c) in enumerate(zip(raw.get("children", []), compiled["children"])):
            compile_paths(r, c, f"{path}/children/{i}")

    compile_paths(
        thaw_json(binding.bundle.candidate)["root"], thaw_json(binding.compiled_tree)
    )
    for uid, source in binding.bundle.provenance.items():
        rows.append(
            {
                "source_path": source["path"],
                "rule": source["rule"],
                "premises": list(source["premises"]),
                "scope_path": list(source["scope_path"]),
                "compiled": source_nodes.get(source["path"]),
                "source_unit_id": uid,
                "runtime_nodes": list(index.source_unit_runtime_nodes.get(uid, ())),
                "compact_path": source["path"],
            }
        )
    return {
        "schema_version": "math-runtime-coverage/v1",
        "candidate": thaw_json(binding.source_identity),
        "entries": rows,
    }
