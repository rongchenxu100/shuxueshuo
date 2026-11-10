"""Validate executable method graphs against the public knowledge graph."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from ..stage_two.recognition import DATA, load_nodes
from . import judgments, method_admission
from .capabilities import PLANNED, REGISTRY

DIRECTORY = DATA / "execution"
SCHEMA = DATA.parents[2] / "internal/schemas/graph-method-execution-v1.schema.json"


@lru_cache(maxsize=1)
def schema_validator():
    return Draft202012Validator(json.loads(SCHEMA.read_text()))


def read(name):
    return json.loads((DIRECTORY / f"{name}.json").read_text())


def route_methods():
    """Top-level routes come from every selection contract, never a Python list."""
    methods = set()
    for path in sorted((DATA / "selection").glob("*.json")):
        selection = json.loads(path.read_text())
        if selection.get("schema_version") == "graph-direct-method-selection/v1":
            if "routes" in selection:
                methods.update(route["method"] for route in selection["routes"])
            else:
                methods.add(selection["method"])
        if selection.get("schema_version") == "graph-method-selection/v1":
            methods.update(branch["target"] for branch in selection["branches"])
    return methods


def discover_contracts():
    """Discover executable methods by their explicit contract marker."""
    contracts = {}
    for path in sorted(DIRECTORY.glob("*.json")):
        value = read(path.stem)
        if value.get("schema_version") != "graph-method-execution/v1":
            if "method" in value and "steps" in value:
                raise ValueError("execution.unknown_contract_schema:" + path.stem)
            continue
        name = value.get("method")
        if name != path.stem:
            raise ValueError("execution.contract_filename_mismatch:" + path.stem)
        contracts[name] = value
    return contracts


def _milestone_configuration(routes=None):
    value = read("milestones")
    schema_path = SCHEMA.parent / "graph-execution-milestones-v1.schema.json"
    Draft202012Validator(json.loads(schema_path.read_text())).validate(value)
    if value["default"] not in value["milestones"]:
        raise ValueError("execution.unknown_default_milestone")
    routes = route_methods() if routes is None else routes
    enabled = set().union(*(set(items) for items in value["milestones"].values()))
    if enabled - routes:
        raise ValueError("execution.unknown_milestone_method:" + ",".join(sorted(enabled - routes)))
    if routes - enabled:
        raise ValueError("execution.unconfigured_milestone_method:" + ",".join(sorted(routes - enabled)))
    return value


def allowed_methods(milestone):
    configuration = _milestone_configuration()
    if milestone not in configuration["milestones"]:
        raise ValueError("execution.unknown_milestone:" + str(milestone))
    return set(configuration["milestones"][milestone])


def milestones():
    return tuple(_milestone_configuration()["milestones"])


def default_milestone():
    return _milestone_configuration()["default"]


def actions(step):
    return sorted(
        [
            *(dict(v, kind="call") for v in step["calls"]),
            *(dict(v, kind="judgment") for v in step["judgments"]),
            *(dict(v, kind="merge") for v in step.get("merges", [])),
        ],
        key=lambda v: v["order"],
    )


def references(value):
    if isinstance(value, str) and value.startswith("$"):
        yield value[1:].split(".")[0]
    elif isinstance(value, dict):
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def valid_ref(reference, nodes):
    name, _, anchor = reference.partition("#")
    if name not in nodes:
        return False
    if not anchor:
        return True

    def ids(value):
        if isinstance(value, dict):
            yield value.get("id")
            for child in value.values():
                yield from ids(child)
        elif isinstance(value, list):
            for child in value:
                yield from ids(child)

    return anchor in set(ids(nodes[name]))


def validate_dependencies(declared, required, available):
    """The readiness declaration must describe every actual binding read."""
    if len(set(declared)) != len(declared) or set(declared) != set(required):
        raise ValueError("execution.dependency_declaration_mismatch")
    if not set(declared) <= available:
        raise ValueError("execution.future_dependency")


def guard_references(guard):
    if not guard:
        return set()
    if "all" in guard:
        return set().union(*(guard_references(item) for item in guard["all"]))
    return {guard["ref"].split(".")[0]} if "ref" in guard else set()


def _atoms(guard):
    if not guard or guard == {"constant": True}:
        return frozenset()
    if guard == {"constant": False}:
        return frozenset({("__never__", "true")})
    if set(guard) == {"all"} and isinstance(guard["all"], list) and guard["all"]:
        return frozenset().union(*(_atoms(item) for item in guard["all"]))
    if set(guard) != {"ref", "equals"} or not isinstance(guard["ref"], str):
        raise ValueError("execution.invalid_guard")
    return frozenset({(guard["ref"], json.dumps(guard["equals"], sort_keys=True))})


def _combine(*guards):
    return {"all": [guard for guard in guards if guard]} if any(guards) else None


def _require(required, environment, guard=None):
    for name in required:
        if name not in environment:
            raise ValueError("execution.future_or_branch_binding")
        if not _atoms(environment[name]) <= _atoms(guard):
            raise ValueError("execution.unmerged_branch_binding")


def validate_contract(contract, nodes=None, *, available_methods=None):
    schema_validator().validate(contract)
    nodes = load_nodes() if nodes is None else nodes
    method = contract["method"]
    if method not in nodes or "steps" not in nodes[method]:
        raise ValueError("execution.unknown_method_node:" + method)
    if "admission" in contract:
        method_admission.validate_admission(contract)
    available_methods = set(discover_contracts()) if available_methods is None else available_methods
    public = nodes[method]["steps"]
    if [s["id"] for s in contract["steps"]] != [s["id"] for s in public]:
        raise ValueError("execution.step_mismatch")
    mappings = read("skill-capabilities")
    templates = read("presentation-registry")["templates"]
    environment = {name: None for name in contract["inputs"]}
    if any(
        not isinstance(role, dict)
        or not isinstance(role.get("role"), str)
        or not role["role"]
        for role in contract["inputs"].values()
    ):
        raise ValueError("execution.input_role")
    expected_exits = {"capability_gap", "math_failed", "execution_error"}
    if set(contract["exits"]) != expected_exits or any(
        contract["exits"][status] != {"status": status} for status in expected_exits
    ):
        raise ValueError("execution.exit_status")
    display_ids = set()

    def validate_step(step, node, env, *, partial=False):
        allowed = {c["ref"] for c in node.get("calls", [])}
        rule = nodes.get(node.get("rule"))
        rule_targets = {branch["id"]: branch["target"] for branch in rule["branches"]} if rule else {}
        # A method-local step decision returns to this method's own continuation;
        # it does not recursively call the complete method again (e.g. FR-T3 J2).
        allowed.update(target for target in rule_targets.values() if target != method)
        ids, executed_refs = set(), set()
        ordered = actions(step)
        if len({action["order"] for action in ordered}) != len(ordered):
            raise ValueError("execution.duplicate_order")
        _atoms(step.get("guard"))
        _require(guard_references(step.get("guard")), env)
        for unit in step["display_units"]:
            if scope := unit.get("source_scope"):
                names = scope.get("steps", [scope.get("step")])
                source_steps = [item for item in contract["steps"] if item["id"] in names]
                if (len(source_steps) != len(names)
                        or any(contract["steps"].index(item) > contract["steps"].index(step)
                               for item in source_steps)
                        or set(scope.get("actions", [])) - {
                            action["id"] for item in source_steps for action in actions(item)}):
                    raise ValueError("execution.invalid_display_source_scope")
            if not isinstance(unit.get("after"), str) or not unit["after"]:
                raise ValueError("execution.display_trigger")
            if unit["id"] in display_ids:
                raise ValueError("execution.duplicate_display_id")
            display_ids.add(unit["id"])
            if unit["template"] not in templates:
                raise ValueError("execution.unknown_display_template")
            if set(unit["bindings"]) != set(
                templates[unit["template"]]["required_bindings"]
            ):
                raise ValueError("execution.template_bindings")
            if not isinstance(unit["bindings"]["before"], list) or not isinstance(
                unit["bindings"]["after"], list
            ):
                raise TypeError("execution.display_math_lists")
        for action in ordered:
            if (
                not isinstance(action.get("id"), str)
                or not action["id"]
                or type(action.get("order")) is not int
            ):
                raise ValueError("execution.action_fields")
            if action["id"] in ids:
                raise ValueError("execution.duplicate_action")
            ids.add(action["id"])
            active_guard = _combine(step.get("guard"), action.get("guard"))
            _atoms(active_guard)
            _require(guard_references(action.get("guard")), env, active_guard)
            if action["kind"] == "merge":
                branch_outputs = [
                    set(branch["bindings"]) for branch in action["branches"]
                ]
                if not branch_outputs or any(
                    keys != branch_outputs[0] for keys in branch_outputs
                ):
                    raise ValueError("execution.merge_outputs")
                for branch in action["branches"]:
                    guard = _combine(active_guard, branch["guard"])
                    _atoms(guard)
                    _require(guard_references(branch["guard"]), env, active_guard)
                    _require(references(branch["bindings"]), env, guard)
                outputs = branch_outputs[0]
            else:
                if not {"inputs", "outputs"} <= action.keys():
                    raise ValueError("execution.action_fields")
                required = set(references(action["inputs"])) | guard_references(
                    action.get("guard")
                )
                _require(required, env, active_guard)
                if action["kind"] == "judgment":
                    if action["function"] not in judgments.REGISTRY:
                        raise ValueError("execution.unregistered_judgment")
                    validate_dependencies(action["depends_on"], required, set(env))
                    choices = [option.get("id") for option in action["options"]]
                    if (
                        not choices
                        or any(
                            not isinstance(choice, str) or not choice
                            for choice in choices
                        )
                        or len(set(choices)) != len(choices)
                    ):
                        raise ValueError("execution.judgment_options")
                    if action.get("rule_ref") and (
                        action["rule_ref"] != node.get("rule") or set(choices) != set(rule_targets)
                    ):
                        raise ValueError("execution.rule_decision_options")
                else:
                    ref, cap = action["public_ref"], action["capability"]
                    if ref is not None:
                        if ref not in allowed or not valid_ref(ref, nodes):
                            raise ValueError("execution.public_call_position")
                        if ref in rule_targets.values():
                            branch = action.get("branch")
                            if action.get("rule_ref") != node["rule"] or rule_targets.get(branch) != ref:
                                raise ValueError("execution.rule_branch_source")
                            decision = next((j for j in step["judgments"]
                                             if j.get("rule_ref") == node["rule"]), None)
                            if not decision or branch not in {o["id"] for o in decision["options"]}:
                                raise ValueError("execution.rule_branch_decision")
                            choice_bindings = [name for name, value in decision["outputs"].items() if value == "choice"]
                            if len(choice_bindings) != 1 or not _atoms({"ref": choice_bindings[0], "equals": branch}) <= _atoms(active_guard):
                                raise ValueError("execution.rule_branch_guard")
                        elif action.get("rule_ref") or action.get("branch"):
                            raise ValueError("execution.unexpected_rule_source")
                        if cap not in mappings["skills"].get(ref, []):
                            raise ValueError("execution.capability_mapping")
                        executed_refs.add(ref)
                    elif method + "#" + node["id"] not in mappings["internal"].get(
                        cap, []
                    ):
                        raise ValueError("execution.internal_call_position")
                    if (
                        cap not in REGISTRY
                        and cap not in PLANNED
                        and cap != "submethod"
                    ):
                        raise ValueError("execution.unknown_capability")
                    if cap == "submethod" and ref not in available_methods:
                        raise ValueError("execution.unavailable_child")
                outputs = set(action["outputs"])
            for name in outputs:
                env[name] = active_guard
            for unit in step["display_units"]:
                if unit["after"] == action["id"]:
                    required = set(references(unit["bindings"]))
                    validate_dependencies(unit["depends_on"], required, set(env))
                    _require(guard_references(unit.get("guard")), env, active_guard)
                    _require(required, env, _combine(active_guard, unit.get("guard")))
        if not partial and executed_refs != allowed:
            raise ValueError("execution.missing_public_call")
        if any(unit["after"] not in ids for unit in step["display_units"]):
            raise ValueError("execution.display_trigger")
        return executed_refs, allowed

    index = 0
    while index < len(contract["steps"]):
        step, node = contract["steps"][index], public[index]
        if step.get('cases') and step.get('options'):
            raise ValueError('execution.ambiguous_iteration_scope')
        cases = step.get("cases") or step.get('options')
        outer_refs, allowed_refs = validate_step(step, node, environment, partial=bool(cases))
        if not cases:
            index += 1
            continue
        _require([cases["source"]], environment)
        end = next(
            (
                i
                for i, row in enumerate(contract["steps"])
                if row["id"] == cases["through"]
            ),
            -1,
        )
        if (
            end < index
            or cases["binding"] in environment
            or cases["collect"] in environment
        ):
            raise ValueError("execution.invalid_case_scope")
        child = dict(environment, **{cases["binding"]: None})
        entry_refs, _ = validate_step(dict(cases["entry"], id=step["id"]), node, child, partial=True)
        if outer_refs | entry_refs != allowed_refs:
            raise ValueError("execution.missing_public_call")
        for child_index in range(index + 1, end + 1):
            if contract["steps"][child_index].get("cases") or contract['steps'][child_index].get('options'):
                raise ValueError("execution.nested_case_span")
            validate_step(contract["steps"][child_index], public[child_index], child)
        _require(references(cases["outputs"]), child)
        environment[cases["collect"]] = None
        index = end + 1
    try:
        _require(references(contract["outputs"]), environment)
    except ValueError as exc:
        raise ValueError("execution.missing_return_binding") from exc
    return contract


def load_contracts():
    nodes = load_nodes()
    discovered = discover_contracts()
    routes = route_methods()
    if routes - set(discovered):
        raise ValueError("execution.missing_method_contract:" + ",".join(sorted(routes - set(discovered))))
    presentation = read("presentation-registry")
    boundary_steps = presentation.get("boundary_steps", {})
    if not isinstance(boundary_steps, dict):
        raise TypeError("execution.invalid_boundary_step")
    missing = routes.difference(boundary_steps)
    if missing:
        raise ValueError("execution.missing_boundary_step:" + ",".join(sorted(missing)))
    contracts = {name: validate_contract(value, nodes, available_methods=set(discovered))
                 for name, value in discovered.items()}
    for method in routes:
        method_admission.validate_admission(contracts[method])
    if orphaned := {name for name, contract in contracts.items() if "admission" in contract} - routes:
        raise ValueError("execution.unselected_route:" + ",".join(sorted(orphaned)))
    _milestone_configuration(routes)
    from .presentation import validate_registry

    validate_registry(presentation)

    def visit(name, path):
        if name in path:
            raise ValueError("execution.recursive_method")
        for step in contracts[name]["steps"]:
            for call in [
                *step["calls"],
                *step.get("cases", {}).get("entry", {}).get("calls", []),
                *step.get('options', {}).get('entry', {}).get('calls', []),
            ]:
                if call["capability"] == "submethod":
                    child = contracts[call["public_ref"]]
                    if set(call["inputs"]) != set(child["inputs"]):
                        raise ValueError("execution.child_inputs")
                    if not set(call["outputs"].values()) <= set(child["outputs"]):
                        raise ValueError("execution.child_outputs")
                    visit(call["public_ref"], (*path, name))

    for method in contracts:
        visit(method, ())
    for refs in read("basis-operations")["operations"].values():
        if not all(valid_ref(ref, nodes) for ref in refs):
            raise ValueError("execution.invalid_basis")
    for method, anchor in boundary_steps.items():
        if not valid_ref(method + "#" + anchor, nodes):
            raise ValueError("execution.invalid_boundary_step")
    return contracts


def revisions():
    files = sorted(DIRECTORY.glob("*.json"))
    result = {
        path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in files
    }
    folder = Path(__file__).parent
    result["capabilities"] = hashlib.sha256(
        b"".join(
            path.read_bytes() for path in sorted((folder / "capabilities").glob("*.py"))
        )
    ).hexdigest()
    for name in (
        "driver",
        "presentation",
        "trajectory",
        "judgments",
        "execution_contracts",
        "method_admission",
        "quantified_subproblem",
        "domain_borrow",
        "presentation_templates",
    ):
        result[name] = hashlib.sha256((folder / f"{name}.py").read_bytes()).hexdigest()
    result["function_evaluation"] = hashlib.sha256((folder.parent / "function_evaluation.py").read_bytes()).hexdigest()
    result['piecewise_evaluation'] = hashlib.sha256((folder.parent / 'piecewise_evaluation.py').read_bytes()).hexdigest()
    result['piecewise_range'] = hashlib.sha256((folder.parent / 'piecewise_range.py').read_bytes()).hexdigest()
    result['piecewise_range_parameter'] = hashlib.sha256((folder.parent / 'piecewise_range_parameter.py').read_bytes()).hexdigest()
    result['piecewise_range_parameter_presentation'] = hashlib.sha256((folder / 'piecewise_range_parameter_presentation.py').read_bytes()).hexdigest()
    result['piecewise_range_presentation'] = hashlib.sha256((folder / 'piecewise_range_presentation.py').read_bytes()).hexdigest()
    result['piecewise_inequality'] = hashlib.sha256((folder.parent / 'piecewise_inequality.py').read_bytes()).hexdigest()
    result['piecewise_inequality_presentation'] = hashlib.sha256((folder / 'piecewise_inequality_presentation.py').read_bytes()).hexdigest()
    result['piecewise_equation'] = hashlib.sha256((folder.parent / 'piecewise_equation.py').read_bytes()).hexdigest()
    result['piecewise_equation_presentation'] = hashlib.sha256((folder / 'piecewise_equation_presentation.py').read_bytes()).hexdigest()
    for name in ('graph_transform_runtime', 'graph_transform_presentation', 'graph_transform_selection', 'absolute_graph_runtime', 'absolute_graph_presentation', 'quadratic_translation_presentation', 'schematic_transform_presentation'):
        result[name] = hashlib.sha256((folder / f'{name}.py').read_bytes()).hexdigest()
    result['quadratic_translation'] = hashlib.sha256((folder.parent / 'quadratic_translation.py').read_bytes()).hexdigest()
    result['schematic_transform'] = hashlib.sha256((folder.parent / 'schematic_transform.py').read_bytes()).hexdigest()
    result['absolute_graph'] = hashlib.sha256((folder.parent / 'absolute_graph.py').read_bytes()).hexdigest()
    result['function_monotonicity'] = hashlib.sha256((folder.parent / 'function_monotonicity.py').read_bytes()).hexdigest()
    result['extremum_math'] = hashlib.sha256((folder.parent / 'extremum_math.py').read_bytes()).hexdigest()
    result['monotonicity_inequality_math'] = hashlib.sha256((folder.parent / 'monotonicity_inequality_math.py').read_bytes()).hexdigest()
    result['monotonicity_parameter_math'] = hashlib.sha256((folder.parent / 'monotonicity_parameter_math.py').read_bytes()).hexdigest()
    for name in ('extremum_runtime', 'extremum_presentation', 'extremum_graphs', 'monotonicity_runtime', 'monotonicity_presentation',
                 'monotonicity_inequality_runtime', 'monotonicity_inequality_presentation',
                 'monotonicity_parameter_runtime', 'monotonicity_parameter_presentation'):
        result[name] = hashlib.sha256((folder / f'{name}.py').read_bytes()).hexdigest()
    result['function_graph'] = hashlib.sha256((folder.parent / 'function_graph.py').read_bytes()).hexdigest()
    result['function_formula'] = hashlib.sha256((folder.parent / 'function_formula.py').read_bytes()).hexdigest()
    result['function_matching'] = hashlib.sha256((folder.parent / 'function_matching.py').read_bytes()).hexdigest()
    result['function_coefficients'] = hashlib.sha256((folder.parent / 'function_coefficients.py').read_bytes()).hexdigest()
    result['function_assignment'] = hashlib.sha256((folder.parent / 'function_assignment.py').read_bytes()).hexdigest()
    result['function_system'] = hashlib.sha256((folder.parent / 'function_system.py').read_bytes()).hexdigest()
    for name in ('formula_runtime', 'formula_presentation', 'matching_runtime', 'matching_presentation', 'coefficients_runtime', 'coefficients_presentation', 'system_runtime', 'system_presentation', 'assignment_runtime', 'assignment_presentation'):
        result[name] = hashlib.sha256((folder / f'{name}.py').read_bytes()).hexdigest()
    result["evaluation_runtime"] = hashlib.sha256((folder / "evaluation_runtime.py").read_bytes()).hexdigest()
    result["evaluation_presentation"] = hashlib.sha256((folder / "evaluation_presentation.py").read_bytes()).hexdigest()
    result["evaluation_algebra"] = hashlib.sha256((folder / "evaluation_algebra.py").read_bytes()).hexdigest()
    for name in ('function_range', 'range_presentation', 'range_tasks', 'range_task_presentation', 'answer_conversion', 'answer_conversion_presentation', 'range_equation', 'range_selection', 'fraction_range', 'fraction_range_presentation', 'abstract_function_range', 'abstract_range_presentation', 'finite_range', 'translation_range', 'translation_presentation'):
        result[name] = hashlib.sha256((folder / f'{name}.py').read_bytes()).hexdigest()
    result['answer_requests'] = hashlib.sha256((folder.parents[1] / 'problem_understanding/answer_requests.py').read_bytes()).hexdigest()
    result['range_syntax'] = hashlib.sha256((folder.parent / 'range_syntax.py').read_bytes()).hexdigest()
    result["selection"] = hashlib.sha256(b"".join(
        path.name.encode() + b"\0" + path.read_bytes() for path in sorted((DATA / "selection").glob("*.json"))
    )).hexdigest()
    return result
