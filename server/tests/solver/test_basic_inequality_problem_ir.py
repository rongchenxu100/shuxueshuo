"""Stage 1 offline replay gates for the representative ten problems."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.basic_inequality_problem_ir import (
    DEFERRED_CASES,
    REPRESENTATIVE_CASES,
    BasicInequalityProblemIRError,
    _fact_parts,
    build_problem_ir_artifact,
    build_problem_ir_from_file,
    validate_family_match,
)
from shuxueshuo_server.solver.family import (
    BASIC_INEQUALITY_FAMILY,
    DEFAULT_FAMILY_REGISTRY,
    FamilyRegistry,
)
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator


ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests/solver/fixtures/math-notation-v1/basic-inequality"
FIXTURES = ROOT / "tests/solver/fixtures/basic-inequality-problem-ir/v1"
SCHEMA = json.loads((ROOT.parent / "internal/schemas/solver-problem-ir.schema.json").read_text())


def _sample_evidence(case):
    return json.loads((FIXTURES / case / "live-samples.json").read_text())["samples"]


def _unit_samples(hashes=("a" * 64, "b" * 64)):
    """Synthetic output hashes for converter unit tests, with a recorded contract."""
    samples = _sample_evidence("q01")
    for sample, digest in zip(samples, hashes, strict=True):
        sample["sha256"] = digest
    return samples


@pytest.mark.parametrize("case", REPRESENTATIVE_CASES)
def test_representative_gold_replays_and_produces_canonical_problem_ir(case):
    gold = json.loads((GOLD / f"{case}.json").read_text(encoding="utf-8"))
    report = NotationValidator().validate(gold)
    assert report.ok, report.payload()
    artifact = build_problem_ir_from_file(
        GOLD / f"{case}.json",
        image_path=f"math-notation-v1/basic-inequality/images/{case}.png",
        sample_hashes=[sample["sha256"] for sample in _sample_evidence(case)],
        sample_provenance=_sample_evidence(case),
    )
    Draft202012Validator(SCHEMA).validate({
        "meta": {"problem_id": case, "title": case},
        "input": artifact["input"],
    })
    assert artifact["problem_id"] == case
    assert artifact["family_match"]["family_id"] == "basic_inequality"
    assert artifact["provenance"]["required_sample_count"] == 2
    assert artifact["provenance"]["sample_ids"] == ["sample-01", "sample-02"]
    assert len(artifact["provenance"]["sample_hashes"]) == 2
    assert artifact["provenance"]["gold_sha256"]
    assert artifact["provenance"]["image_path"].endswith(f"/{case}.png")
    frozen = json.loads((FIXTURES / case / "problem-ir.json").read_text())
    assert artifact["input"] == frozen["input"]
    for key in ("prompt_hashes", "schema_hash", "catalog_hashes"):
        assert artifact["provenance"][key] == frozen["provenance"][key]
    problem = problem_from_canonical_input(artifact["input"])
    assert DEFAULT_FAMILY_REGISTRY.match(problem) is None
    assert "expected_answers" not in artifact["input"]
    assert "route_metadata" not in artifact["input"]


@pytest.mark.parametrize("case", REPRESENTATIVE_CASES)
def test_fixture_has_auditable_source_paths_hashes_and_route_sidecars(case):
    artifact = json.loads((FIXTURES / case / "problem-ir.json").read_text())
    provenance = json.loads((FIXTURES / case / "provenance.json").read_text())
    expected = json.loads((FIXTURES / case / "expected.json").read_text())
    route = json.loads((FIXTURES / case / "route-metadata.json").read_text())
    assert artifact["schema_version"] == "basic-inequality-problem-ir/v1"
    assert artifact["provenance"] == provenance
    samples = _sample_evidence(case)
    assert len(samples) == len(provenance["sample_ids"]) == len(provenance["sample_hashes"]) == provenance["required_sample_count"] == 2
    assert len({sample["response_id"] for sample in samples}) == 2
    assert len({sample["source_run"] for sample in samples}) == 2
    for sample, sample_id, sample_hash in zip(samples, provenance["sample_ids"], provenance["sample_hashes"], strict=True):
        assert sample["sample_id"] == sample_id
        assert sha256(sample["raw_response"].encode("utf-8")).hexdigest() == sample["sha256"] == sample_hash
        assert sample["gold_file_sha256"] == sha256((GOLD / f"{case}.json").read_bytes()).hexdigest()
        assert sample["summary"]["passed"] is True
        assert sample["summary"]["strict_semantics_passed"] is True
        assert sample["summary"]["contract_valid"] is True
        assert NotationValidator().validate(json.loads(sample["raw_response"])).ok
        assert provenance["prompt_hashes"] == {
            "system": sample["template_files"]["internal/llm-prompts/problem-math-notation-system.md"],
            "user": sample["template_files"]["internal/llm-prompts/problem-math-notation-user.md"],
        }
        assert provenance["schema_hash"] == sample["template_files"]["internal/schemas/problem-math-notation-v1.schema.json"]
        assert provenance["catalog_hashes"] == {
            "expressions": sample["template_files"]["internal/llm-prompts/problem-math-notation-expressions.json"],
            "families": sample["notation_family_catalog_hash"],
        }
    canonical_bytes = json.dumps(artifact["input"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    assert sha256(canonical_bytes).hexdigest() == provenance["canonical_hash"]
    assert expected["problem_id"] == route["problem_id"] == case
    assert route["catalog_only"] is True
    assert route["methods"]
    for table in (artifact["input"]["entities"], artifact["input"]["facts"], artifact["input"]["question_goals"]):
        for item in table:
            assert item["source_path"].startswith("/root")
            assert item["source_text"]
            assert item["normalized_expression"]
            assert item["sample_hashes"] == provenance["sample_hashes"]


def test_representative_scope_manifest_excludes_deferred_cases():
    manifest = json.loads((GOLD / "manifest.json").read_text())
    assert manifest["scope"] == "representative-10"
    assert manifest["samples_per_case"] == 2
    assert manifest["deferred_cases"] == DEFERRED_CASES
    assert tuple(manifest["cases"]) == REPRESENTATIVE_CASES
    assert not any((FIXTURES / case).exists() for case in DEFERRED_CASES.split(","))


def test_converter_rejects_deferred_case_labels():
    gold = json.loads((GOLD / "q01.json").read_text())
    gold["root"]["label"] = "q02"
    with pytest.raises(BasicInequalityProblemIRError, match="representative cases"):
        build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())


def test_converter_preserves_caller_supplied_independent_sample_hashes():
    artifact = build_problem_ir_from_file(
        GOLD / "q01.json",
        sample_ids=("sample-01", "sample-02"),
        sample_hashes=("a" * 64, "b" * 64),
        sample_provenance=_unit_samples(),
    )
    assert artifact["provenance"]["sample_hashes"] == ["a" * 64, "b" * 64]
    assert artifact["provenance"]["sample_ids"] == ["sample-01", "sample-02"]
    assert all(
        item["sample_hashes"] == ["a" * 64, "b" * 64]
        for table in (artifact["input"]["entities"], artifact["input"]["facts"], artifact["input"]["question_goals"])
        for item in table
    )


@pytest.mark.parametrize("sample_ids,sample_hashes", [
    (("sample-01", "sample-02"), ()),
    ((), ()),
    (("sample-01", "sample-02"), ("a" * 64,)),
    (("sample-01",), ("a" * 64,)),
    (("sample-01",), ("a" * 64, "b" * 64)),
    (("sample-01", "sample-02", "sample-03"), ("a" * 64,) * 3),
])
def test_converter_rejects_missing_or_incorrect_sample_counts(sample_ids, sample_hashes):
    with pytest.raises(BasicInequalityProblemIRError, match="exactly 2 samples"):
        build_problem_ir_from_file(GOLD / "q01.json", sample_ids=sample_ids, sample_hashes=sample_hashes)


def test_converter_requires_explicit_sample_hashes():
    with pytest.raises(BasicInequalityProblemIRError, match="explicit live sample hashes"):
        build_problem_ir_from_file(GOLD / "q01.json")


@pytest.mark.parametrize("sample_ids,sample_hashes,message", [
    (("sample-01", "sample-01"), ("a" * 64,) * 2, "distinct"),
    (("sample-01", ""), ("a" * 64,) * 2, "non-empty"),
    (("sample-01", "sample-02"), ("", "b" * 64), "SHA-256"),
    (("sample-01", "sample-02"), ("z" * 64, "b" * 64), "SHA-256"),
])
def test_converter_rejects_invalid_sample_evidence(sample_ids, sample_hashes, message):
    with pytest.raises(BasicInequalityProblemIRError, match=message):
        build_problem_ir_from_file(GOLD / "q01.json", sample_ids=sample_ids, sample_hashes=sample_hashes)


def test_independent_samples_may_have_identical_output_hashes():
    artifact = build_problem_ir_from_file(GOLD / "q01.json", sample_hashes=("a" * 64,) * 2, sample_provenance=_unit_samples(("a" * 64,) * 2))
    assert artifact["provenance"]["sample_hashes"] == ["a" * 64] * 2


@pytest.mark.parametrize("text,expected", [
    (f"a {op} 0", (("symbol_constraint", f"a {op} 0"),))
    for op in (">=", "<=", "≥", "≤", ">", "<", "!=", "≠")
] + [
    ("0<=a≤1", (("symbol_constraint", "0 <= a"), ("symbol_constraint", "a ≤ 1"))),
    ("1≥a>0", (("symbol_constraint", "1 ≥ a"), ("symbol_constraint", "a > 0"))),
    ("a = 0", (("equation", "a = 0"),)),
    ("a ∈ R", (("symbol_domain", "a ∈ R"),)),
    ("a is positive", (("statement", "a is positive"),)),
])
def test_fact_parts_classifies_and_splits_relations(text, expected):
    assert _fact_parts(text) == expected


@pytest.mark.parametrize("operator", (":=", "≔", "≡"))
@pytest.mark.parametrize("field", ("definitions", "facts"))
def test_definition_operators_produce_equations_and_preserve_source(operator, field):
    source = f"u{operator}x^2"
    assert _fact_parts(source) == (("equation", "u = x^2"),)
    gold = json.loads((GOLD / "q01.json").read_text())
    gold["root"]["definitions"] = []
    gold["root"]["facts"] = []
    gold["root"][field] = [source]
    gold["root"]["goals"] = [{"kind": "find_minimum", "expression": "u"}]
    assert NotationValidator().validate(gold).ok
    artifact = build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())
    fact, = artifact["input"]["facts"]
    assert fact["type"] == "equation"
    assert fact["normalized_expression"] == "u = x^2"
    assert fact["source_text"] == source
    assert fact["source_path"] == f"/root/{field}/0"
    assert validate_family_match(artifact["input"])["family_id"] == "basic_inequality"


@pytest.mark.parametrize("text", ("a !== 0", "a === 0", "a >== 0", "a ! = 0", "a > = 0", "a <", "<= a", "u :== 1"))
def test_malformed_relations_fail_closed(text):
    with pytest.raises(BasicInequalityProblemIRError, match="relation"):
        _fact_parts(text)
    gold = json.loads((GOLD / "q01.json").read_text())
    gold["root"]["facts"] = [text]
    with pytest.raises(BasicInequalityProblemIRError):
        build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())


def test_mixed_relation_chain_preserves_each_operator_type():
    assert _fact_parts("a != b = c <= 1") == (
        ("symbol_constraint", "a != b"),
        ("equation", "b = c"),
        ("symbol_constraint", "c <= 1"),
    )


@pytest.mark.parametrize("separator", ("∧", "∨", "and", "or", "AND", "OR", ",", "，"))
def test_compound_relations_fail_closed_before_comparison_splitting(separator):
    with pytest.raises(BasicInequalityProblemIRError, match="compound logic or comma-separated"):
        _fact_parts(f"a > 0 {separator} b > 0")


@pytest.mark.parametrize("text", (
    "(a > 0 ∧ b > 0)",
    "a ∈ R ∧ a > 0",
    "a ∈ R ∨ b > 0",
    "a,b ∈ R",
    "a ∈ (0,1)",
    "a = max(b,c)",
))
def test_compound_sources_do_not_bypass_rejection_through_domains_or_parentheses(text):
    with pytest.raises(BasicInequalityProblemIRError, match="compound logic or comma-separated"):
        _fact_parts(text)


@pytest.mark.parametrize("name", ("candy", "origin", "and_value", "or_value"))
def test_boolean_word_detection_preserves_identifier_substrings(name):
    assert _fact_parts(f"{name} > 0") == (("symbol_constraint", f"{name} > 0"),)


@pytest.mark.parametrize("relation", ("a > 0 ∧ b > 0", "a > 0 ∨ b > 0", "a ∈ ℝ ∧ b > 0", "a,b ∈ ℝ"))
@pytest.mark.parametrize("field", ("definitions", "facts"))
@pytest.mark.parametrize("nested", (False, True))
def test_valid_notation_with_compound_logic_cannot_produce_partial_problem_ir(relation, field, nested):
    gold = json.loads((GOLD / "q01.json").read_text())
    # Keep the original root equation: family source checks alone would pass.
    scope = gold["root"]
    if nested:
        scope["children"] = [{"label": "part 1"}]
        scope = scope["children"][0]
    scope.setdefault(field, []).append(relation)
    report = NotationValidator().validate(gold)
    assert report.ok, report.payload()
    with pytest.raises(BasicInequalityProblemIRError, match="compound logic or comma-separated"):
        build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())


@pytest.mark.parametrize("relation", ("0 <= a <= 1", "0 ≤ a ≤ 1", "1 >= a >= 0", "1 ≥ a ≥ 0"))
def test_inequality_only_sources_satisfy_family_gate_and_preserve_source(relation):
    gold = json.loads((GOLD / "q01.json").read_text())
    gold["root"]["facts"] = [relation]
    gold["root"]["goals"] = [{"kind": "find_maximum", "expression": "a"}]
    artifact = build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())
    assert artifact["family_match"]["family_id"] == "basic_inequality"
    facts = artifact["input"]["facts"]
    assert len(facts) == 2
    assert all(fact["type"] == "symbol_constraint" for fact in facts)
    assert all(fact["source_text"] == relation for fact in facts)
    assert all(fact["source_path"] == "/root/facts/0" for fact in facts)


@pytest.mark.parametrize("relation", ("a != 0", "a ≠ 0"))
@pytest.mark.parametrize("other_facts", ([], ["b = 1"]))
def test_not_equal_is_a_constraint_with_or_without_other_equations(relation, other_facts):
    gold = json.loads((GOLD / "q01.json").read_text())
    gold["root"]["facts"] = [relation, *other_facts]
    gold["root"]["goals"] = [{"kind": "find_minimum", "expression": "a^2"}]
    artifact = build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())
    fact = artifact["input"]["facts"][0]
    assert fact["type"] == "symbol_constraint"
    assert fact["normalized_expression"] == fact["source_text"] == relation
    assert validate_family_match(artifact["input"])["family_id"] == "basic_inequality"


@pytest.mark.parametrize("nested", (False, True))
def test_definitions_become_facts_in_their_source_scope(nested):
    gold = json.loads((GOLD / "q01.json").read_text())
    scope = gold["root"]
    path = "/root"
    if nested:
        scope["children"] = [{"label": "part 1"}]
        scope = scope["children"][0]
        path += "/children/0"
    scope["definitions"] = ["u = m+n", "0 < u <= 2"]
    scope["facts"] = ["m > 0"]
    scope["goals"] = [{"kind": "find_maximum", "expression": "u"}]
    artifact = build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())
    data = artifact["input"]
    facts = [fact for fact in data["facts"] if fact["source_path"].startswith(path + "/definitions/")]
    assert [fact["type"] for fact in facts] == ["equation", "symbol_constraint", "symbol_constraint"]
    assert [fact["normalized_expression"] for fact in facts] == ["u = m+n", "0 < u", "u <= 2"]
    assert [fact["source_path"] for fact in facts] == [path + "/definitions/0", path + "/definitions/1", path + "/definitions/1"]
    sid = next(item["scope_id"] for item in data["scopes"] if item["source_path"] == path)
    assert all(fact["scope_id"] == fact["valid_scope"] == sid for fact in facts)
    assert all(fact["sample_hashes"] == ["a" * 64, "b" * 64] for fact in facts)
    assert set(facts[0]["entity_handles"]) == {item["handle"] for item in data["entities"] if item["name"] in {"u", "m", "n"}}
    assert len({fact["handle"] for fact in data["facts"]}) == len(data["facts"])


def test_symbols_are_local_to_first_visible_scope_and_siblings_do_not_leak():
    gold = json.loads((GOLD / "q01.json").read_text())
    gold["root"]["children"] = [
        {
            "label": "part 1",
            "definitions": ["u := m+k"],
            "facts": ["k > 0"],
            "goals": [{"kind": "find_minimum", "expression": "u+v"}],
            "children": [{"label": "part 1a", "facts": ["u > k", "v > 0", "t > 0"]}],
        },
        {
            "label": "part 2",
            "definitions": ["u ≔ n+k"],
            "facts": ["k > 1"],
            "goals": [{"kind": "find_minimum", "expression": "u"}],
        },
    ]
    data = build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=_unit_samples())["input"]
    scopes = {scope["source_path"]: scope["scope_id"] for scope in data["scopes"]}
    entities = {(entity["scope_id"], entity["name"]): entity for entity in data["entities"]}
    root, part1, part1a, part2 = [scopes[path] for path in ("/root", "/root/children/0", "/root/children/0/children/0", "/root/children/1")]
    assert set(entities) == {(root, "m"), (root, "n"), (part1, "u"), (part1, "k"), (part1, "v"), (part1a, "t"), (part2, "u"), (part2, "k")}
    assert entities[part1, "u"]["handle"] != entities[part2, "u"]["handle"]
    assert entities[part1, "u"]["source_path"] == "/root/children/0/definitions/0"
    assert entities[part1, "v"]["source_path"] == "/root/children/0/goals/0"
    by_source = {fact["source_path"]: fact for fact in data["facts"]}
    for path, bindings in (
        ("/root/children/0/definitions/0", ((part1, "u"), (root, "m"), (part1, "k"))),
        ("/root/children/1/definitions/0", ((part2, "u"), (root, "n"), (part2, "k"))),
        ("/root/children/0/children/0/facts/0", ((part1, "u"), (part1, "k"))),
        ("/root/children/0/children/0/facts/1", ((part1, "v"),)),
        ("/root/children/0/children/0/facts/2", ((part1a, "t"),)),
    ):
        assert by_source[path]["entity_handles"] == [entities[binding]["handle"] for binding in bindings]
    assert len({entity["handle"] for entity in data["entities"]}) == len(entities)
    Draft202012Validator(SCHEMA).validate({"meta": {"problem_id": "q01", "title": "nested"}, "input": data})


@pytest.mark.parametrize("field", (
    "internal/llm-prompts/problem-math-notation-system.md",
    "internal/llm-prompts/problem-math-notation-user.md",
    "internal/schemas/problem-math-notation-v1.schema.json",
    "internal/llm-prompts/problem-math-notation-expressions.json",
    "notation_family_catalog_hash",
))
def test_converter_rejects_mixed_sample_contracts(field):
    samples = _unit_samples()
    target = samples[1] if field == "notation_family_catalog_hash" else samples[1]["template_files"]
    target[field] = "0" * 64
    with pytest.raises(BasicInequalityProblemIRError, match="must agree"):
        build_problem_ir_from_file(GOLD / "q01.json", sample_hashes=("a" * 64, "b" * 64), sample_provenance=samples)


@pytest.mark.parametrize("mutation,message", [
    (lambda samples: samples.clear(), "exactly 2"),
    (lambda samples: samples[0].update(sample_id="wrong"), "match sample_ids"),
    (lambda samples: samples[0].update(sha256="c" * 64), "match sample_ids"),
    (lambda samples: samples[0].pop("template_files"), "missing template_files"),
    (lambda samples: samples[0]["template_files"].pop("internal/llm-prompts/problem-math-notation-system.md"), "recorded SHA-256"),
    (lambda samples: samples[0].pop("notation_family_catalog_hash"), "recorded SHA-256"),
])
def test_converter_rejects_missing_or_misassociated_sample_provenance(mutation, message):
    samples = _unit_samples()
    mutation(samples)
    with pytest.raises(BasicInequalityProblemIRError, match=message):
        build_problem_ir_from_file(GOLD / "q01.json", sample_hashes=("a" * 64, "b" * 64), sample_provenance=samples)


def test_converter_uses_historical_contract_even_if_workspace_files_change(monkeypatch):
    samples = _unit_samples()
    gold = json.loads((GOLD / "q01.json").read_text())
    def unexpected_read(*args, **kwargs):
        pytest.fail("converter must not read current prompt files for historical provenance")
    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    artifact = build_problem_ir_artifact(gold, sample_hashes=("a" * 64, "b" * 64), sample_provenance=samples)
    assert artifact["provenance"]["prompt_hashes"]["system"] == samples[0]["template_files"]["internal/llm-prompts/problem-math-notation-system.md"]


def test_family_match_uses_structure_and_fails_closed_for_labels_and_primitives():
    base = json.loads((FIXTURES / "q01" / "problem-ir.json").read_text())["input"]
    assert validate_family_match(base)["family_id"] == "basic_inequality"
    with pytest.raises(BasicInequalityProblemIRError):
        validate_family_match(base, candidate_family_id="quadratic_path_minimum")
    for key, value in (("pattern", "other"), ("problem_type", "other")):
        candidate = deepcopy(base)
        candidate[key] = value
        with pytest.raises(BasicInequalityProblemIRError):
            validate_family_match(candidate)
    mutations = (
        ("no symbol", lambda item: item.update(entity_type="function") or None),
        ("no equation", lambda item: item.update(type="statement") or None),
        ("no supported goal", lambda item: item.update(value_type="Other") or None),
    )
    for label, mutate in mutations:
        candidate = deepcopy(base)
        if label == "no symbol":
            for item in candidate["entities"]:
                mutate(item)
        elif label == "no equation":
            for item in candidate["facts"]:
                mutate(item)
        else:
            for item in candidate["question_goals"]:
                mutate(item)
        with pytest.raises(BasicInequalityProblemIRError):
            validate_family_match(candidate)


def test_basic_inequality_remains_out_of_production_registry():
    assert all(family.family_id != "basic_inequality" for family in DEFAULT_FAMILY_REGISTRY.families)


def test_problem_id_is_not_a_family_signal_and_duplicate_authoring_family_is_ambiguous():
    base = json.loads((FIXTURES / "q01" / "problem-ir.json").read_text())["input"]
    renamed = deepcopy(base)
    renamed["problem_id"] = "unrelated-id"
    assert validate_family_match(renamed)["family_id"] == "basic_inequality"
    problem = problem_from_canonical_input(renamed)
    with pytest.raises(ValueError, match="ambiguous solver family match"):
        FamilyRegistry((BASIC_INEQUALITY_FAMILY, BASIC_INEQUALITY_FAMILY)).match(problem)


def test_converter_has_no_runtime_or_planner_dependencies():
    import ast

    source = (
        ROOT.parent / "server/shuxueshuo_server/problem_understanding/"
        "basic_inequality_problem_ir.py"
    ).read_text()
    imports = [node for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.Import, ast.ImportFrom))]
    imported = {
        alias.name
        for node in imports
        for alias in node.names
    }
    assert not any(name.startswith("shuxueshuo_server.solver.runtime") for name in imported)
    assert not any(name.startswith("shuxueshuo_server.solver.planner") for name in imported)
    assert not any("method" in name or "proof" in name for name in imported)
