"""Methods compose registered admissions and bindings without driver edits."""

import json
import shutil
from copy import deepcopy

import pytest
import sympy as sp
from test_graph_stage_three_methods import Q01, TARGET, candidate

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    driver,
    execution_contracts,
    method_admission,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    source = execution_contracts.DATA
    folder = tmp_path / "knowledge"
    shutil.copytree(source / "execution", folder / "execution")
    shutil.copytree(source / "selection", folder / "selection")
    nodes = deepcopy(execution_contracts.load_nodes())
    monkeypatch.setattr(execution_contracts, "DATA", folder)
    monkeypatch.setattr(execution_contracts, "DIRECTORY", folder / "execution")
    monkeypatch.setattr(execution_contracts, "load_nodes", lambda: nodes)
    return folder, nodes


def _rewrite(registry, name, edit):
    folder, _ = registry
    path = folder / "execution" / f"{name}.json"
    value = json.loads(path.read_text())
    edit(value)
    _save(path, value)


def _virtual_route(registry):
    folder, nodes = registry
    original, method = "method-discriminant", "method-fixture-quadratic"
    value = execution_contracts.read(original)
    value["method"] = method
    value["inputs"]["new_input"] = {"role": "fixture_input"}
    value["admission"]["bindings"]["new_input"] = {"constant": {"kind": "new-existing-capability-route"}}
    _save(folder / "execution" / f"{method}.json", value)
    nodes[method] = deepcopy(nodes[original])
    nodes[method]["id"] = method
    _save(folder / "selection" / "fixture-rule.json", {
        "schema_version": "graph-method-selection/v1", "branches": [{"target": method}],
    })
    _rewrite(registry, "presentation-registry", lambda data: data["boundary_steps"].update({method: "merge"}))
    _rewrite(registry, "milestones", lambda data: data["milestones"]["6"].append(method))

    def clone_internal_positions(data):
        for refs in data["internal"].values():
            refs.extend(ref.replace(original + "#", method + "#") for ref in list(refs)
                        if ref.startswith(original + "#"))

    _rewrite(registry, "skill-capabilities", clone_internal_positions)
    return method


def test_method_is_discovered_and_executed_from_config_without_driver_branches(registry):
    method = _virtual_route(registry)
    contracts = execution_contracts.load_contracts()
    assert method in contracts and method in execution_contracts.route_methods()
    assert method in execution_contracts.allowed_methods("6")
    assert method not in execution_contracts.allowed_methods("5")
    state = driver.create_state(
        features=extract_features(Q01)["features"], context=build_context(Q01, TARGET), method=method,
        route_id="fixture", branch="fixture", target_ref=TARGET, run_id="fixture", lesson_version="v1",
        contracts=contracts,
    )
    assert state["status"] == "running"
    assert decode_value(state["input_values"])["new_input"] == {"kind": "new-existing-capability-route"}
    for _ in range(100):
        if state["status"] != "running":
            break
        state = driver.advance(state, contracts=contracts)
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == sp.Union(sp.Interval(-sp.oo, -1), sp.Interval(4, sp.oo))
    assert all(row["method_ref"].startswith(method + "#") for row in state["fragments"])


@pytest.mark.parametrize(("mutation", "error"), [
    ("missing_admission", "missing_admission"),
    ("missing_binding", "admission_bindings"),
    ("unknown_resolver", "unknown_binding_resolver"),
    ("unknown_check", "unknown_admission_check"),
    ("unknown_dependency", "admission_dependency"),
    ("invalid_check_arguments", "admission_check_inputs"),
    ("missing_milestone", "unconfigured_milestone_method"),
    ("missing_boundary", "missing_boundary_step"),
])
def test_new_route_configuration_omissions_fail_at_load(registry, mutation, error):
    method = _virtual_route(registry)

    def mutate(contract):
        admission = contract["admission"]
        if mutation == "missing_admission":
            del contract["admission"]
        elif mutation == "missing_binding":
            del admission["bindings"]["new_input"]
        elif mutation == "unknown_resolver":
            admission["bindings"]["new_input"] = {"resolver": "not_registered"}
        elif mutation == "unknown_check":
            admission["checks"][0]["function"] = "not_registered"
        elif mutation == "unknown_dependency":
            admission["checks"][0]["inputs"]["quantifier"] = "$unbound"
        elif mutation == "invalid_check_arguments":
            admission["checks"][0]["inputs"] = {"typo": "$quantifier"}

    _rewrite(registry, method, mutate)
    if mutation == "missing_milestone":
        _rewrite(registry, "milestones", lambda data: data["milestones"]["6"].remove(method))
    elif mutation == "missing_boundary":
        _rewrite(registry, "presentation-registry", lambda data: data["boundary_steps"].pop(method))
    with pytest.raises(ValueError, match="execution\\." + error):
        execution_contracts.load_contracts()


def test_selection_with_no_executable_contract_fails_instead_of_disappearing(registry):
    folder, _ = registry
    _save(folder / "selection" / "missing.json", {
        "schema_version": "graph-method-selection/v1", "branches": [{"target": "method-missing"}],
    })
    with pytest.raises(ValueError, match="execution.missing_method_contract:method-missing"):
        execution_contracts.load_contracts()


@pytest.mark.parametrize("mutation", ["filename", "schema", "not_selected", "unknown_milestone"])
def test_invalid_method_registry_entries_fail_explicitly(registry, mutation):
    method = _virtual_route(registry)
    if mutation == "filename":
        _rewrite(registry, method, lambda value: value.update(method="wrong-name"))
    elif mutation == "schema":
        _rewrite(registry, method, lambda value: value.update(schema_version="unsupported/v2"))
    elif mutation == "not_selected":
        (registry[0] / "selection" / "fixture-rule.json").unlink()
    else:
        _rewrite(registry, "milestones", lambda value: value["milestones"]["6"].append("unknown"))
    with pytest.raises(ValueError, match="execution\\."):
        execution_contracts.load_contracts()


def test_declared_binding_resolvers_can_supply_new_input_names():
    contract = {
        "method": "renamed-inputs", "inputs": {"principal": {}, "student_goal": {}, "marker": {}},
        "admission": {"bindings": {
            "principal": {"resolver": "bound_variable"}, "student_goal": {"resolver": "goal"},
            "marker": {"constant": "∀"},
        }, "checks": [{"function": "quantifier", "inputs": {"quantifier": "$marker"}}]},
    }
    values = method_admission.initial_bindings(contract, extract_features(Q01)["features"], build_context(Q01, TARGET))
    assert values["principal"] == sp.Symbol("x", real=True)
    assert values["student_goal"] == build_context(Q01, TARGET)["goal"]
    assert method_admission.can_execute(contract, values)


def test_discriminant_admission_uses_quantified_reals_without_retired_checks():
    contract = execution_contracts.read("method-discriminant")
    checks = {check["function"] for check in contract["admission"]["checks"]}
    assert "quantified_reals" in checks
    assert not {"universal_reals", "intersect_conditions"} & method_admission.CHECKS.keys()
    quantified_reals = method_admission.CHECKS["quantified_reals"]
    assert all(quantified_reals(quantifier, sp.S.Reals) for quantifier in ("∀", "∃"))
    assert not quantified_reals("∀", sp.Interval(0, 1))
    assert not quantified_reals("unknown", sp.S.Reals)


def test_current_milestone_adds_function_methods_without_changing_earlier_sets():
    base = {"method-discriminant", "method-separation"}
    interval = base | {"method-interval-extremum"}
    all_methods = interval | {"method-variable-swap"}
    function_methods = {
        'method-domain-intersection', 'method-domain-parameter', 'method-function-equality',
        'method-input-domain-correspondence', 'method-function-evaluation',
        'method-function-assignment', 'method-function-coefficients', 'method-function-equation-system',
        'method-function-matching', 'method-function-substitution', 'method-direct-range',
        'method-equation-real-root-range', 'method-finite-range', 'method-fraction-split-range',
        'method-quadratic-interval-range', 'method-substitution-range', 'method-translation-range',
        'method-absolute-piecewise-graph', 'method-function-graph-transform',
        'method-piecewise-equation', 'method-piecewise-graph-inequality', 'method-piecewise-inequality',
        'method-piecewise-modeling', 'method-piecewise-range', 'method-piecewise-range-parameter',
        'method-monotonicity-definition', 'method-monotonicity-structure', 'method-piecewise-monotonicity',
        'method-monotonicity-extremum', 'method-quantified-range-comparison',
        'method-extremum-condition-parameter', 'method-monotonicity-inequality',
        'method-monotonicity-parameter', 'method-parity-definition', 'method-parity-parameter',
        'method-parity-extension', 'method-function-symmetry',
    }
    assert execution_contracts.default_milestone() == "6"
    assert execution_contracts.milestones() == ("1a", "1b-1", "1b", "2", "3", "4", "5", "6")
    expected = {"1a": set(), "1b-1": {"method-discriminant"}, "1b": base, "2": base,
                "3": interval, "4": interval, "5": all_methods, "6": all_methods | function_methods}
    assert {key: execution_contracts.allowed_methods(key) for key in expected} == expected
    with pytest.raises(ValueError, match="execution.unknown_milestone"):
        execution_contracts.allowed_methods("no-such-version")


def test_unregistered_method_is_configuration_failure_not_mathematical_gap():
    with pytest.raises(ValueError, match="execution.unknown_method"):
        driver.create_state(
            features=extract_features(Q01)["features"], context=build_context(Q01, TARGET),
            method="method-unregistered", route_id="fixture", branch="fixture", target_ref=TARGET,
            run_id="fixture", lesson_version="v1",
        )


@pytest.mark.parametrize(("method", "fact", "expected"), [
    ("method-discriminant", "∀x∈ℝ:x^2+a>=0", True),
    ("method-discriminant", "∃x∈ℝ:x^2+a>=0", True),
    ("method-discriminant", "∃x∈[0,1]:x^2+a>=0", False),
    ("method-discriminant", "∀x∈[0,1]:x^2+a>=0", False),
    ("method-separation", "∀x∈ℝ:x^2+a>=0", True),
    ("method-interval-extremum", "∀x∈[0,1]:x^2+a>=0", True),
    ("method-variable-swap", "∀x∈[0,1]:a*x+1>=0", True),
])
def test_existing_admission_classes_keep_their_mathematical_meaning(method, fact, expected):
    value = candidate(fact)
    assert driver.can_execute(method, extract_features(value)["features"], build_context(value, TARGET)) is expected


@pytest.mark.parametrize(("fact", "expected"), [
    ("∀x∈ℝ:x^2+1>=0", sp.S.Reals),
    ("∀x∈ℝ:x^2+1<0", sp.S.EmptySet),
])
def test_initial_relation_stays_unevaluated_even_when_sympy_knows_its_truth(fact, expected):
    value = candidate(fact)
    features, context = extract_features(value)["features"], build_context(value, TARGET)
    contracts = execution_contracts.load_contracts()
    bindings = driver.initial_bindings("method-discriminant", features, context, contracts=contracts)
    assert isinstance(bindings["relation"], sp.core.relational.Relational)
    assert bindings["relation"].lhs == sp.Symbol("x", real=True) ** 2 + 1
    state = driver.create_state(
        features=features, context=context, method="method-discriminant", route_id="discriminant",
        branch="discriminant", target_ref=TARGET, run_id="fixture", lesson_version="v1", contracts=contracts,
    )
    for _ in range(100):
        if state["status"] != "running":
            break
        state = driver.advance(state, contracts=contracts)
    assert state["status"] == "method_complete", state["diagnostics"]
    assert driver.export_values(state)["feasible_set"] == expected
