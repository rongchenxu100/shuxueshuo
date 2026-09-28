"""Independent checker, exact legacy replay and trusted rule-package isolation."""

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path

import pytest
import sympy as sp
from shuxueshuo_server.solver.math_kernel import proof_checker as checker
from shuxueshuo_server.solver.math_kernel import proof_kernel as kernel
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure, digest
from shuxueshuo_server.solver.math_kernel.proof_rule_registry import (
    RulePackage,
    RuleRegistry,
)
from shuxueshuo_server.solver.math_kernel.proof_types import (
    ProofContext,
    ProofLimits,
    ProofResult,
)

CORPUS_PATH = (
    Path(__file__).parent / "fixtures/scoped-proof-search/checker-legacy-corpus.json"
)
CORPUS = json.loads(CORPUS_PATH.read_text())


def restore(raw):
    symbols = {s: sp.Symbol(s, real=True) for s in raw["symbols"]}
    premises = {
        k: replace(
            parse_math_relation(v["source"], symbols),
            source_path=v["source_path"],
            step=v["step"],
        )
        for k, v in raw["premises"].items()
    }
    return ProofContext(
        symbols, premises, ProofLimits(**raw["limits"]), raw["scope_id"]
    )


def test_legacy_identity_and_all_rules_frozen_before_extraction():
    assert (
        checker.RULESET_HASH
        == CORPUS["ruleset_hash"]
        == "8d9a1f9ccc4061513641ce0f15f70f821e4f1e19598c4d149d3191e32167bb16"
    )
    assert CORPUS["covered_rules"] == sorted(checker.LEGACY_RULE_PACKAGE.rule_ids)
    assert not CORPUS["missing_rules"]
    assert checker.RULESET_VERSION == "bounded-real-proof/v1"
    assert kernel.ProofContext is checker.ProofContext is ProofContext
    assert kernel._Environment is checker._Environment
    assert kernel.replay_proof is checker.replay_proof


@pytest.mark.parametrize(
    "record", CORPUS["certificates"], ids=lambda c: c["proof"]["request"]["kind"]
)
def test_frozen_legacy_replay_with_search_disabled(record, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("checker invoked search")

    monkeypatch.setattr(kernel, "_run_request", forbidden)
    monkeypatch.setattr(kernel._Search, "__init__", forbidden)
    original = deepcopy(record["proof"])
    result = checker.replay_proof(record["proof"], restore(record["context"]))
    assert result.status == "proved", result.to_payload()
    assert record["proof"] == result.proof == original


def test_cold_import_and_replay_cannot_import_search():
    script = """
import sys, importlib.abc, json
from pathlib import Path
class NoSearch(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.endswith('.proof_kernel') or '.proof_search' in fullname:
            raise AssertionError('checker imported search: '+fullname)
sys.meta_path.insert(0, NoSearch())
from dataclasses import replace
import sympy as sp
from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
from shuxueshuo_server.solver.math_kernel.proof_types import ProofContext, ProofLimits
from shuxueshuo_server.solver.math_kernel.expression_parser import parse_math_relation
for record in json.loads(Path(sys.argv[1]).read_text())['certificates']:
    raw=record['context']; symbols={s:sp.Symbol(s,real=True) for s in raw['symbols']}
    premises={k:replace(parse_math_relation(v['source'],symbols),source_path=v['source_path'],step=v['step']) for k,v in raw['premises'].items()}
    result=replay_proof(record['proof'],ProofContext(symbols,premises,ProofLimits(**raw['limits']),raw['scope_id']))
    assert result.status=='proved', result.to_payload()
assert not any(n.endswith('.proof_kernel') or '.proof_search' in n for n in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(CORPUS_PATH.resolve())],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "mutation",
    ["rule", "hash", "package", "source", "scope", "premises", "nested_hash"],
)
def test_frozen_certificate_tampering_is_rejected(mutation):
    record = next(
        c
        for c in CORPUS["certificates"]
        if any(n["rule_id"] == "math.witness" for n in c["proof"]["nodes"])
    )
    proof = deepcopy(record["proof"])
    context = restore(record["context"])
    if mutation == "rule":
        proof["nodes"][0]["rule_id"] = "test.foreign"
    elif mutation == "hash":
        proof["ruleset_hash"] = "0" * 64
    elif mutation == "package":
        proof["schema_version"] = "unknown/v1"
    elif mutation == "source":
        proof["sources"] = {}
    elif mutation == "scope":
        context = replace(context, scope_id="other")
    elif mutation == "premises":
        context = replace(
            context,
            premises={
                **context.premises,
                "added": parse_math_relation("1=1", context.symbols),
            },
        )
    else:
        witness = next(n for n in proof["nodes"] if n["rule_id"] == "math.witness")
        witness["certificate"]["proof"]["ruleset_hash"] = "0" * 64
    assert checker.replay_proof(proof, context).status == "not_proved"


TEST_PACKAGE = "test-rational/v1"
TEST_RULE = "test.rational_equality"
TEST_HASH = digest({"package": TEST_PACKAGE, "rule": TEST_RULE, "revision": 1})


def rational_checker(proof, context, *, budget):
    """A real small independent checker, only for registry tests."""
    if (
        set(proof) != {"schema_version", "ruleset_hash", "nodes", "roots"}
        or proof["roots"] != ["r0"]
        or len(proof["nodes"]) != 1
    ):
        raise ProofFailure("invalid_proof", "invalid rational certificate")
    node = proof["nodes"][0]
    if (
        set(node) != {"node_id", "rule_id", "left", "right"}
        or node["node_id"] != "r0"
        or node["rule_id"] != TEST_RULE
    ):
        raise ProofFailure("invalid_proof", "invalid rational node")
    if not all(
        isinstance(node[k], str) and len(node[k]) <= 32 for k in ["left", "right"]
    ):
        raise ProofFailure("invalid_proof", "bounded rational operands required")
    if Fraction(node["left"]) != Fraction(node["right"]):
        raise ProofFailure("invalid_proof", "false equality")
    return ProofResult("proved", proof=proof)


def extension():
    package = RulePackage(TEST_PACKAGE, TEST_HASH, (TEST_RULE,), rational_checker)
    proof = {
        "schema_version": TEST_PACKAGE,
        "ruleset_hash": TEST_HASH,
        "nodes": [
            {"node_id": "r0", "rule_id": TEST_RULE, "left": "1/2", "right": "2/4"}
        ],
        "roots": ["r0"],
    }
    return package, proof


def test_register_extension_preserves_legacy_and_can_be_excluded():
    package, proof = extension()
    base = checker.DEFAULT_RULE_REGISTRY
    extended = base.with_package(package)
    assert base.packages == (checker.LEGACY_RULE_PACKAGE,)
    assert (
        checker.replay_proof(proof, ProofContext({}), registry=extended).status
        == "proved"
    )
    assert (
        checker.replay_proof(proof, ProofContext({}), registry=base).status
        == "not_proved"
    )
    for record in CORPUS["certificates"]:
        assert (
            checker.replay_proof(
                record["proof"], restore(record["context"]), registry=extended
            ).status
            == "proved"
        )
    assert checker.RULESET_HASH == CORPUS["ruleset_hash"]
    with pytest.raises(FrozenInstanceError):
        extended.packages = ()


@pytest.mark.parametrize(
    "mutation",
    ["false", "foreign_rule", "foreign_package", "hash", "untrusted_registration"],
)
def test_extension_rejects_math_error_and_package_spoofing(mutation):
    package, proof = extension()
    registry = checker.DEFAULT_RULE_REGISTRY.with_package(package)
    if mutation == "false":
        proof["nodes"][0]["right"] = "3/4"
    elif mutation == "foreign_rule":
        proof["nodes"][0]["rule_id"] = "math.constant"
    elif mutation == "foreign_package":
        proof.update(
            schema_version=checker.RULESET_VERSION, ruleset_hash=checker.RULESET_HASH
        )
    elif mutation == "hash":
        proof["ruleset_hash"] = "0" * 64
    else:
        proof["register_package"] = {"rule_ids": ["evil.rule"]}
    assert (
        checker.replay_proof(proof, ProofContext({}), registry=registry).status
        == "not_proved"
    )


def test_registry_rejects_replacement_and_cross_package_rule_ownership():
    base = checker.DEFAULT_RULE_REGISTRY
    with pytest.raises(ValueError, match="duplicate"):
        base.with_package(checker.LEGACY_RULE_PACKAGE)
    with pytest.raises(ValueError, match="another package"):
        base.with_package(
            RulePackage(TEST_PACKAGE, TEST_HASH, ("math.constant",), rational_checker)
        )
    with pytest.raises(ProofFailure, match="unknown"):
        RuleRegistry().replay(
            CORPUS["certificates"][0]["proof"],
            restore(CORPUS["certificates"][0]["context"]),
        )


def test_rule_ownership_is_checked_before_extension_dispatch():
    package, proof = extension()
    calls = []

    def observe(*args, **kwargs):
        calls.append(True)
        return rational_checker(*args, **kwargs)

    registry = checker.DEFAULT_RULE_REGISTRY.with_package(
        replace(package, checker=observe)
    )
    proof["nodes"][0]["rule_id"] = "math.constant"
    result = checker.replay_proof(proof, ProofContext({}), registry=registry)
    assert result.status == "not_proved"
    assert "different or unknown package" in result.diagnostic
    assert not calls


def test_legacy_witness_cannot_switch_to_registered_extension():
    package, child = extension()
    calls = []

    def observe(*args, **kwargs):
        calls.append(True)
        return rational_checker(*args, **kwargs)

    registry = checker.DEFAULT_RULE_REGISTRY.with_package(
        replace(package, checker=observe)
    )
    record = next(
        c
        for c in CORPUS["certificates"]
        if any(n["rule_id"] == "math.witness" for n in c["proof"]["nodes"])
    )
    proof = deepcopy(record["proof"])
    witness = next(n for n in proof["nodes"] if n["rule_id"] == "math.witness")
    child["request"] = witness["certificate"]["proof"]["request"]
    witness["certificate"]["proof"] = child
    assert (
        checker.replay_proof(
            proof, restore(record["context"]), registry=registry
        ).status
        == "not_proved"
    )
    assert not calls


def test_solver_lazy_exports_preserve_original_objects():
    from importlib import import_module

    from shuxueshuo_server import solver

    assert set(solver.__all__) == set(solver._EXPORT_MODULES)
    for name, module in solver._EXPORT_MODULES.items():
        assert getattr(solver, name) is getattr(
            import_module(f"{solver.__name__}.{module}"), name
        )
        assert name in dir(solver)
    with pytest.raises(AttributeError):
        _ = solver.unknown_public_export


def test_question_goal_parser_can_be_imported_before_runtime():
    script = """
from shuxueshuo_server.solver.question_goals import _parse_goal
result = _parse_goal('q', {'id':'g','answer_key':'x','target_path':'$problem.scalars.x','value_type':'Scalar','required':True})
assert result.id == 'g'
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_frozen_corpus_was_not_regenerated_by_the_new_checker():
    from hashlib import sha256

    assert (
        sha256(CORPUS_PATH.read_bytes()).hexdigest()
        == "9ca2128f0c7b4fbef1f4ffab87d11454c61100d610ef5a089034cae59548dd60"
    )


def test_registry_versions_are_exact_and_do_not_replace_previous_checker():
    package, proof = extension()
    newer = replace(package, ruleset_hash=digest({"revision": 2}))
    registry = checker.DEFAULT_RULE_REGISTRY.with_package(package).with_package(newer)
    assert registry.resolve(TEST_PACKAGE, TEST_HASH) is package
    assert registry.resolve(TEST_PACKAGE, newer.ruleset_hash) is newer
    assert (
        checker.replay_proof(proof, ProofContext({}), registry=registry).status
        == "proved"
    )
    proof["ruleset_hash"] = newer.ruleset_hash
    assert (
        checker.replay_proof(proof, ProofContext({}), registry=registry).status
        == "proved"
    )
    proof["ruleset_hash"] = digest({"revision": 3})
    assert (
        checker.replay_proof(proof, ProofContext({}), registry=registry).status
        == "not_proved"
    )


@pytest.mark.parametrize(
    "module",
    [
        "shuxueshuo_server.solver.family",
        "shuxueshuo_server.solver.extraction.problem_domain",
        "shuxueshuo_server.solver.runtime.config",
        "shuxueshuo_server.solver.runtime.orchestrator",
    ],
)
def test_runtime_consumers_can_cold_import(module):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib; importlib.import_module({module!r})",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_lazy_exports_preserve_original_objects():
    from importlib import import_module

    from shuxueshuo_server.solver import runtime

    for name, module in runtime._EXPORT_MODULES.items():
        assert getattr(runtime, name) is getattr(import_module(module), name)
        assert name in dir(runtime)
    with pytest.raises(AttributeError):
        _ = runtime.unknown_public_export


@pytest.mark.parametrize("nodes", [None, {}, (), [{}]])
def test_registry_rejects_invalid_common_envelope_before_dispatch(nodes):
    package, proof = extension()
    calls = []

    def observe(*args, **kwargs):
        calls.append(True)
        return rational_checker(*args, **kwargs)

    registry = checker.DEFAULT_RULE_REGISTRY.with_package(
        replace(package, checker=observe)
    )
    proof["nodes"] = nodes
    result = checker.replay_proof(proof, ProofContext({}), registry=registry)
    assert result.status == "not_proved"
    assert not calls


@pytest.mark.parametrize("supplied_budget", [False, True])
def test_registry_and_legacy_checker_use_the_same_effective_node_limit(supplied_budget):
    record = CORPUS["certificates"][0]
    context = restore(record["context"])
    proof = deepcopy(record["proof"])
    if supplied_budget:
        # The context retains its authenticated identity, while the caller's
        # explicit replay budget supplies the effective resource limits.
        limits = context.limits
        context = replace(context, limits=replace(limits, nodes=1))
        proof["context_hash"] = checker._Environment(
            context, proof["request"], budget=kernel._Budget(limits)
        ).context_hash
    else:
        limits = replace(context.limits, nodes=1)
    for replay in (checker._replay_legacy, checker.DEFAULT_RULE_REGISTRY.replay):
        budget = kernel._Budget(limits)
        if supplied_budget:
            assert replay(proof, context, budget=budget).status == "proved"
        else:
            with pytest.raises(ProofFailure, match="certificate node count limit"):
                replay(proof, context, budget=budget)
    if supplied_budget:
        # Without the explicit budget the context's one-node limit applies.
        for replay in (checker._replay_legacy, checker.DEFAULT_RULE_REGISTRY.replay):
            with pytest.raises(ProofFailure, match="certificate node count limit"):
                replay(proof, context)
