"""Phase A: real-checker baseline and strict red contracts, not a fact store."""

import ast
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel import proof_kernel as pk
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure, from_node
from shuxueshuo_server.solver.runtime.inequality_teaching_evidence import (
    collect_inequality_evidence,
)
from tools.proof_search_baseline import ASSETS, FIXTURES, ROOT, profiles, verify_assets


class PendingContract(AssertionError):
    """Only the specifically reproduced architecture gap may be xfailed."""


def load(name):
    return json.loads((ASSETS / name).read_text())


def test_frozen_inputs_and_effective_budgets():
    assert len(verify_assets()["cases"]) == 4
    assert profiles() == load("budget-profiles.json")


def test_premise_inventory_matches_constructors_and_excludes_witnesses():
    inventory = load("premise-sites.json")
    assert inventory["unknown_constructor_policy"] == "reject_publication"
    assert len(inventory["sites"]) == 16
    for site in inventory["sites"]:
        tree = ast.parse((ROOT / site["file"]).read_text())
        functions = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == site["function"]
        ]
        assert functions, site
        assert any(site["namespace"] in ast.unparse(n) for n in functions), site
        assert site["validity"] and site["proof_origin"]
        if site["namespace"].startswith(
            ("attainment:", "solution_case", "shared_solution:", "equality_derivation:")
        ):
            assert site["publication"] == "never_global", site
        if site["semantic_kind"] == "definition":
            assert site["publication"] == "definition_only"
            assert "definition_refs" in site["validity"]


def legacy_context():
    fixture = load("legacy-m01-context.json")
    symbols = {s: sp.Symbol(s, real=True) for s in fixture["symbols"]}
    return fixture, pk.ProofContext(
        symbols,
        {
            key: parse_math_relation(value, symbols)
            for key, value in fixture["resolved_conditions"].items()
        },
        scope_id=fixture["scope_id"],
    )


def test_legacy_exact_context_replays_without_search(monkeypatch):
    fixture, context = legacy_context()

    def forbidden(*args, **kwargs):
        pytest.fail("replay called search")

    monkeypatch.setattr(pk._Search, "need", forbidden)
    assert pk.replay_proof(fixture["proof"], context).status == "proved"


@pytest.mark.parametrize(
    "mutation", ["scope", "extra_premise", "missing_premise", "tamper"]
)
def test_legacy_certificate_cannot_silently_change_context(mutation):
    fixture, context = legacy_context()
    proof = deepcopy(fixture["proof"])
    if mutation == "scope":
        context = replace(context, scope_id="sibling")
    elif mutation == "extra_premise":
        context = replace(
            context,
            premises={
                **context.premises,
                "extra": parse_math_relation("x!=0", context.symbols),
            },
        )
    elif mutation == "missing_premise":
        context = replace(context, premises={})
    else:
        proof["nodes"][-1]["conclusion"] = ["=", ["integer", 1], ["integer", 2]]
    assert pk.replay_proof(proof, context).status != "proved"


def test_shared_search_cache_cannot_export_branch_assumption():
    symbols = {"x": sp.Symbol("x", real=True)}
    condition = parse_math_relation("x>0", symbols)
    branch = pk.ProofContext(symbols, {"solution_case": condition}, scope_id="case")
    request = {"kind": "relation", "candidate": pk._document(condition)}
    budget = pk._Budget(branch.limits)
    assert pk._run_request(branch, request, budget=budget).status == "proved"
    for context in (
        pk.ProofContext(symbols, scope_id="problem"),
        pk.ProofContext(symbols, scope_id="sibling"),
    ):
        with pytest.raises(ProofFailure):
            pk._run_request(context, request, budget=budget)


def amgm_target():
    return {
        "type": "extremum_target",
        "goal_kind": "find_minimum",
        "scope_id": "problem",
        "scalar_symbols": ["x", "y"],
        "target_math": "x+4/x",
        "source_conditions": [
            {"handle": f"c{i}", "source_path": f"/facts/{i}", "math": f"{s}>0"}
            for i, s in enumerate(["x", "y"])
        ],
    }


def inline_verified_auxiliary(monkeypatch):
    """Probe legal v1 inline representation, not an implemented shared-store read.

    No checker or proof outcome is mocked. Both fragments and their combined
    certificate pass the real checker. An unused auxiliary is legal in v1.
    """
    original = pk._run_request
    observed = []

    def run(context, request, *, budget=None):
        if (
            request.get("candidate", {}).get("source", "").replace(" ", "")
            != "x+4/x>=4"
        ):
            return original(context, request, budget=budget)
        search = pk._Search(context, request, budget=budget)
        search.need(from_node(parse_math_relation("y+4/y>=4", context.symbols).ast))
        roots = [search.need(goal) for goal in pk._roots_for_request(search)]
        proof = search.payload(roots)
        pk._replay(proof, context)
        observed.append(proof)
        return pk.ProofResult("proved", proof=proof)

    monkeypatch.setattr(pk, "_run_request", run)
    return observed


def test_auxiliary_fragment_is_valid_and_reproduces_m11_gap(monkeypatch):
    assert verify_bound(amgm_target(), [{"math": "x+4/x>=4"}])["bound"] == "4"
    observed = inline_verified_auxiliary(monkeypatch)
    with pytest.raises(ProofFailure) as error:
        verify_bound(amgm_target(), [{"math": "x+4/x>=4"}])
    assert error.value.code == "amgm_remainder_changed"
    assert len(observed) == 1
    assert sum(n["rule_id"] == "math.two_term_amgm" for n in observed[0]["nodes"]) == 2


@pytest.mark.xfail(
    strict=True,
    raises=PendingContract,
    reason="Stage E P1: identify current application, not dependency nodes",
)
def test_m11_ignores_verified_auxiliary_application(monkeypatch):
    inline_verified_auxiliary(monkeypatch)
    try:
        bound = verify_bound(amgm_target(), [{"math": "x+4/x>=4"}])
    except ProofFailure as error:
        assert error.code == "amgm_remainder_changed"
        raise PendingContract(
            "verified auxiliary incorrectly treated as current application"
        ) from error
    assert bound["bound"] == "4"


@pytest.mark.xfail(
    strict=True,
    raises=PendingContract,
    reason="Stage E P1: teaching projects current application evidence",
)
def test_teaching_does_not_attribute_auxiliary_amgm_to_current_row(monkeypatch):
    target = amgm_target()
    bound = verify_bound(target, [{"math": "x+4/x>=4"}])
    observed = inline_verified_auxiliary(monkeypatch)
    try:
        verify_bound(target, [{"math": "x+4/x>=4"}])
    except ProofFailure as error:
        assert error.code == "amgm_remainder_changed"
    assert observed
    bound["derivation"]["proofs"][0] = observed[0]
    method = SimpleNamespace(
        method_id="apply_two_term_amgm",
        trace_fragments=[{"source_target": target, "evidence": bound}],
    )
    projected = collect_inequality_evidence("current", [method])[0].to_payload()[
        "data"
    ]["local_relations"]
    if len(projected) != 1:
        assert [r["math"] for r in projected] == ["y+4/y ≥ 4", "x+4/x ≥ 4"]
        raise PendingContract("auxiliary application attributed to current source row")
    assert projected[0]["math"] == "x+4/x ≥ 4"


@pytest.mark.solver_contract
@pytest.mark.xfail(
    strict=True,
    raises=PendingContract,
    reason="Stage E: conditions become hints; scoped domain remains available",
)
def test_m01_scope_domain_available_with_partial_condition_hints(tmp_path):
    from tools.run_basic_inequality_stage4a import run

    plan = json.loads((FIXTURES / "basic-inequality-stage5c/q30.json").read_text())
    plan["root_scope"]["goals"][0]["steps"][0]["args"]["conditions"] = [
        "symbol_constraint_c"
    ]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    result, _ = run(
        gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
        problem_ir=FIXTURES / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
        plan=path,
        output=tmp_path / "execution",
        mode="recorded",
    )
    if result.status != "ok":
        checkpoint = (tmp_path / "execution/attempt-2.base-checkpoint.json").read_text()
        assert "input_domain_unverified" in checkpoint
        assert "bind_domain_conditions" in checkpoint
        raise PendingContract("partial condition binding hides original target domain")
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"minimum": "4"}}


@pytest.mark.solver_contract
def test_recorded_baseline_runs_real_runtime_and_replay(tmp_path):
    from tools.proof_search_baseline import run_baseline

    output = tmp_path / "baseline"
    summary = run_baseline(output)
    assert summary["live_llm_calls"] == 0
    assert len(summary["cases"]) == 4
    assert all(c["outcome"]["status"] == "ok" for c in summary["cases"])
    assert summary["cases"][1]["outcome"]["full_five_method_chain"]
    for case in summary["cases"]:
        measurement = json.loads(
            (output / case["id"] / "measurement.json").read_text()
        )["measurement"]
        assert measurement["goal_requests"] > 0
        assert measurement["all_budget_charges"]["nodes"] > 0
        assert measurement["budget_instances"]
    # Never overwrite an earlier run, including its failures.
    with pytest.raises(FileExistsError):
        run_baseline(output)


def test_failed_rewrite_publishes_no_committed_version_or_step_result():
    from shuxueshuo_server.solver.expression_rewrite_transaction import (
        execute_rewrite_transaction,
    )

    fixture = json.loads((FIXTURES / "expression_rewrite/q08.json").read_text())
    fixture["call"]["parameters"]["steps"][-1]["math"] = "a+b"
    report = execute_rewrite_transaction(fixture)
    assert report.call_results[0].status == "failed"
    assert report.committed_versions == ()
    assert report.call_results[0].step_results == ()


def test_old_amgm_conclusion_alone_is_not_a_new_application():
    target = amgm_target()
    target["source_conditions"].append(
        {"handle": "old", "source_path": "/facts/2", "math": "x+4/x>=4"}
    )
    with pytest.raises(ProofFailure) as error:
        verify_bound(target, [{"math": "x+4/x>=4"}])
    assert error.value.code == "inequality_template_unmatched"


def test_frozen_m07_m08_control_uses_no_amgm_and_replays_without_search(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import constraint_elimination as ce
    from shuxueshuo_server.solver.math_kernel.substitution import verify_substitution

    fixture = load("q12-subchain.json")
    original_add = pk._Search.add
    rules = set()
    forbidden_rules = {
        "two_term_amgm",
        "fixed_sum_product_bound",
        "amgm_squared_bound",
        "local_two_term_amgm",
        "two_term_product_bound",
    }

    def no_amgm(search, rule, *args, **kwargs):
        assert rule not in forbidden_rules, rule
        rules.add(rule)
        return original_add(search, rule, *args, **kwargs)

    monkeypatch.setattr(pk._Search, "add", no_amgm)
    substitution, context = verify_substitution(
        fixture["target"], fixture["substitution"]
    )
    elimination, _ = ce.verify_elimination(
        fixture["target"], fixture["elimination"], substitution=substitution
    )
    assert elimination["substitution"] == substitution
    assert (
        elimination["parameters"]["expression"] == fixture["elimination"]["expression"]
    )
    assert rules
    # Current M08 imports the certified transformed equality; sign reuse through
    # a shared fact store is a later C/E gate, not claimed by this baseline.
    used = {
        premise
        for proof in elimination["proofs"]
        for node in proof["nodes"]
        for premise in node["premises"]
    }
    assert "substitution:verified:2" in used
    assert (
        context.premises["substitution:verified:1"].source.replace(" ", "")
        == fixture["expected_import"]
    )

    def no_search(*args, **kwargs):
        pytest.fail("M07/M08 replay searched")

    monkeypatch.setattr(pk, "_run_request", no_search)
    monkeypatch.setattr(ce, "_run_request", no_search)
    ce.replay_elimination(fixture["target"], json.loads(json.dumps(elimination)))
