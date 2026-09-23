"""Real sample replay, source-preserving lowering and authoring-only admission."""

import ast
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.basic_inequality_frozen import (
    FILES,
    digest,
    freeze_runs,
    load_verified_case,
    read_json,
    write_json,
)
from shuxueshuo_server.problem_understanding.basic_inequality_problem_ir import (
    DEFERRED_CASES,
    REPRESENTATIVE_CASES,
    BasicInequalityProblemIRError,
    build_problem_ir_from_file,
    convert_notation,
    validate_family_match,
)
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.solver.family import (
    BASIC_INEQUALITY_FAMILY,
    DEFAULT_FAMILY_REGISTRY,
    FamilyRegistry,
)
from shuxueshuo_server.solver.runtime.projection import (
    _runtime_path_from_handle,
    problem_from_canonical_input,
)

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "tests/solver/fixtures/math-notation-v1/basic-inequality"
FIXTURES = ROOT / "tests/solver/fixtures/basic-inequality-problem-ir/v1"
SCHEMA = read_json(ROOT.parent / "internal/schemas/solver-problem-ir.schema.json")


def pointer(document, path):
    for segment in path.strip("/").split("/"):
        document = (
            document[int(segment)] if isinstance(document, list) else document[segment]
        )
    return document


def symbol_runtime_paths(payload):
    parents = {scope["scope_id"]: scope["parent"] or "problem" for scope in payload["scopes"]}
    names = {entity["handle"]: entity["name"] for entity in payload["entities"]}
    assert len(names) == len(payload["entities"])
    paths = {}
    for entity in payload["entities"]:
        assert entity["handle"] == f"symbol:{entity['scope_id']}:{entity['name']}"
        paths[entity["handle"]] = _runtime_path_from_handle(
            entity["handle"], parents, container="values", entity_names=names,
        )
    assert all(set(fact["entity_handles"]) <= names.keys() for fact in payload["facts"])
    return paths


@pytest.mark.parametrize("case", REPRESENTATIVE_CASES)
def test_real_samples_replay_and_rebuild_exactly(case):
    # This validates raw/schema/canonical/comparison, gold and image byte hashes,
    # actual request baseline and two distinct successful provider response IDs.
    artifact = build_problem_ir_from_file(GOLD / f"{case}.json")
    assert artifact == read_json(FIXTURES / case / "problem-ir.json")
    assert artifact["provenance"] == read_json(FIXTURES / case / "provenance.json")
    Draft202012Validator(SCHEMA).validate(
        {"meta": artifact["meta"], "input": artifact["input"]}
    )
    samples = artifact["provenance"]["samples"]
    assert len(samples) == 2
    assert len({s["response_id"] for s in samples}) == 2
    assert all(set(s["files"]) == set(FILES) for s in samples)
    assert artifact["provenance"]["gold_sha256"] == digest(
        (GOLD / f"{case}.json").read_bytes()
    )
    payload = artifact["input"]
    assert symbol_runtime_paths(payload) == {
        f"symbol:s0:{entity['name']}": f"$question.s0.values.{entity['name']}"
        for entity in payload["entities"]
    }
    problem = problem_from_canonical_input(payload)
    assert DEFAULT_FAMILY_REGISTRY.match(problem) is None
    assert artifact["family_match"]["authoring_only"] is True
    assert {"expected_answers", "route_metadata", "family_id"}.isdisjoint(payload)
    assert problem.expected_answers == {}
    expected = read_json(FIXTURES / case / "expected.json")
    route = read_json(FIXTURES / case / "route-metadata.json")
    assert expected["problem_id"] == route["problem_id"] == case
    assert expected["answer"] and expected["equality_branches"]
    assert route["allowed_method_chains"] and route["required_evidence"]
    assert route["expected_page_steps"]["count"] == len(
        route["expected_page_steps"]["titles"]
    )
    assert all(
        set(chain) <= set(BASIC_INEQUALITY_FAMILY.method_ids)
        for chain in route["allowed_method_chains"]
    )


@pytest.mark.parametrize("case", REPRESENTATIVE_CASES)
def test_every_source_location_is_real_and_no_fact_or_goal_is_lost(case):
    gold = read_json(GOLD / f"{case}.json")
    payload = read_json(FIXTURES / case / "problem-ir.json")["input"]
    for table in ("entities", "facts", "question_goals"):
        for item in payload[table]:
            assert pointer(gold, item["source_path"]) == item["source_text"]
            assert item["normalized_expression"] and len(item["sample_refs"]) == 2
    assert len(payload["scopes"]) == 1  # All ten current golds are single questions.
    assert {f["source_path"] for f in payload["facts"]} == {
        f"/root/facts/{i}" for i in range(len(gold["root"]["facts"]))
    }
    assert payload["question_goals"][0]["target_expression"] == next(
        gold["root"]["goals"][0][k]
        for k in ("expression", "symbol")
        if k in gold["root"]["goals"][0]
    )


@pytest.fixture
def isolated(tmp_path):
    root = tmp_path / "gold"
    root.mkdir()
    for name in ("manifest.json", "q01.json"):
        shutil.copyfile(GOLD / name, root / name)
    (root / "images").mkdir()
    shutil.copyfile(GOLD / "images/q01.png", root / "images/q01.png")
    (root / "samples").mkdir()
    shutil.copyfile(GOLD / "samples/index.json", root / "samples/index.json")
    shutil.copytree(GOLD / "samples/q01", root / "samples/q01")
    return root


def reseal(root, name, mutate, sample="sample-01"):
    path = root / "samples/q01" / sample / name
    data = read_json(path)
    mutate(data)
    write_json(path, data)
    index = read_json(root / "samples/index.json")
    next(row for row in index["samples"]["q01"] if row["sample_id"] == sample)["files"][
        name
    ] = digest(path.read_bytes())
    write_json(root / "samples/index.json", index)


@pytest.mark.parametrize("name", FILES)
def test_missing_or_changed_sample_files_fail_closed(isolated, name):
    path = isolated / "samples/q01/sample-01" / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(BasicInequalityProblemIRError, match="file hash mismatch"):
        build_problem_ir_from_file(isolated / "q01.json")
    path.unlink()
    with pytest.raises(FileNotFoundError):
        build_problem_ir_from_file(isolated / "q01.json")


@pytest.mark.parametrize(
    ("name", "mutate", "error"),
    [
        ("frozen.json", lambda x: x.update(gold_sha256="0" * 64), "stale gold"),
        ("frozen.json", lambda x: x.update(system_prompt_hash="0" * 64), "baseline"),
        ("summary.json", lambda x: x.update(passed=False), "stored gate"),
        ("diff.json", lambda x: x.update(ok=False), "comparison replay"),
        ("canonical.json", lambda x: x["root"].update(facts=[]), "canonical replay"),
        ("parsed.json", lambda x: x.update(semantic_revision="bad"), "parsed replay"),
        ("normalized.json", lambda x: x["root"].update(facts=[]), "normalized replay"),
        ("call.json", lambda x: x.update(finish_reason="length"), "invalid live call"),
        ("request.json", lambda x: x.update(model="different-model"), "request hash"),
    ],
)
def test_semantic_and_version_checks_are_not_just_file_hashes(
    isolated, name, mutate, error
):
    reseal(isolated, name, mutate)
    with pytest.raises(BasicInequalityProblemIRError, match=error):
        build_problem_ir_from_file(isolated / "q01.json")


def test_reusing_one_call_with_two_sample_names_fails(isolated):
    index = read_json(isolated / "samples/index.json")
    first = index["samples"]["q01"][0]
    second = deepcopy(first)
    second["sample_id"] = "sample-02"
    second["source_run"] = "different-looking-run"
    index["samples"]["q01"][1] = second
    for name in FILES:
        shutil.copyfile(
            isolated / "samples/q01/sample-01" / name,
            isolated / "samples/q01/sample-02" / name,
        )
    write_json(isolated / "samples/index.json", index)
    with pytest.raises(BasicInequalityProblemIRError, match="same provider call"):
        load_verified_case(isolated / "q01.json")


def test_insufficient_samples_fail(isolated):
    index = read_json(isolated / "samples/index.json")
    index["samples"]["q01"].pop()
    write_json(isolated / "samples/index.json", index)
    with pytest.raises(BasicInequalityProblemIRError, match="two frozen"):
        load_verified_case(isolated / "q01.json")


def test_identical_raw_content_is_allowed_for_distinct_provider_calls(isolated):
    # Simulate identical model outputs while retaining the two real, distinct
    # response IDs. This guards against treating raw hash equality as reuse.
    index = read_json(isolated / "samples/index.json")
    first, second = index["samples"]["q01"]
    identity, source_run = second["response_id"], second["source_run"]
    original_call = read_json(isolated / "samples/q01/sample-01/call.json")
    for name in FILES:
        shutil.copyfile(
            isolated / "samples/q01/sample-01" / name,
            isolated / "samples/q01/sample-02" / name,
        )
    original_call["provider_attempts"][0]["raw_payload"]["id"] = identity
    write_json(isolated / "samples/q01/sample-02/call.json", original_call)
    second.update(deepcopy(first))
    second.update(sample_id="sample-02", response_id=identity, source_run=source_run)
    second["files"]["call.json"] = digest(
        (isolated / "samples/q01/sample-02/call.json").read_bytes()
    )
    write_json(isolated / "samples/index.json", index)
    result = load_verified_case(isolated / "q01.json")
    samples = result["provenance"]["samples"]
    assert samples[0]["raw_sha256"] == samples[1]["raw_sha256"]
    assert samples[0]["response_id"] != samples[1]["response_id"]


@pytest.mark.parametrize("file", ["q01.json", "images/q01.png"])
def test_gold_and_image_tampering_fails(isolated, file):
    path = isolated / file
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(BasicInequalityProblemIRError, match="file hash mismatch"):
        load_verified_case(isolated / "q01.json")


def candidate(facts, goals=None, **scope):
    return {
        "original_text": "合成作用域边界测试",
        "match_status": "matched",
        "family_id": "basic_inequality",
        "match_reason": "代数条件与目标",
        "root": {"facts": facts, "goals": goals or [], **scope},
    }


@pytest.mark.parametrize(
    ("operator", "normalized"),
    [
        ("=", "="),
        ("!=", "!="),
        ("≠", "!="),
        (">=", ">="),
        ("≥", ">="),
        ("<=", "<="),
        ("≤", "<="),
        (">", ">"),
        ("<", "<"),
    ],
)
def test_relation_typing_uses_bound_operator(operator, normalized):
    payload = convert_notation(candidate([f"x {operator} 1"]), problem_id="any-id")
    fact = payload["facts"][0]
    assert fact["relation_operator"] == normalized
    assert fact["type"] == ("equation" if normalized == "=" else "symbol_constraint")


def test_conjunction_and_chain_preserve_source_and_direction():
    gold = candidate(["a > b > c", "x >= 0 ∧ y != 0"])
    payload = convert_notation(gold, problem_id="no-case-number")
    assert [f["relation_operator"] for f in payload["facts"]] == [">", ">", ">=", "!="]
    assert [f["source_path"] for f in payload["facts"]] == [
        "/root/facts/0",
        "/root/facts/0",
        "/root/facts/1",
        "/root/facts/1",
    ]


def test_child_symbol_visibility_and_unique_goal_keys():
    gold = candidate(
        ["x > 0"],
        children=[
            {
                "facts": ["t > 1"],
                "goals": [{"kind": "find_minimum", "expression": "x+t"}],
            },
            {
                "facts": ["t < -1"],
                "goals": [{"kind": "find_maximum", "expression": "x-t"}],
            },
        ],
    )
    p = convert_notation(gold, problem_id="arbitrary")
    entities = p["entities"]
    assert len([e for e in entities if e["name"] == "x"]) == 1
    t = [e for e in entities if e["name"] == "t"]
    assert len(t) == 2 and t[0]["scope_id"] != t[1]["scope_id"]
    assert [s["parent"] for s in p["scopes"]] == [None, "s0", "s0"]
    assert len({g["answer_key"] for g in p["question_goals"]}) == 2
    for g in p["question_goals"]:
        assert pointer(gold, g["source_path"]) == g["target_expression"]


@pytest.mark.parametrize("extra_root_symbol", (False, True))
def test_entity_handles_project_by_declaring_scope_not_object_order(extra_root_symbol):
    gold = candidate(
        (["z > 0"] if extra_root_symbol else []) + ["x > 0", "y > 0"],
        children=[
            {
                "facts": ["t > x+y", "u = t+x"],
                "children": [{"facts": ["v = t+u+y"]}],
            },
            {"facts": ["t < x+y", "u = t+y"]},
        ],
    )
    payload = convert_notation(gold, problem_id="scope-handles")
    expected = {
        "symbol:s0:x": "$question.s0.values.x",
        "symbol:s0:y": "$question.s0.values.y",
        "symbol:s1:t": "$subquestion.s1.values.t",
        "symbol:s1:u": "$subquestion.s1.values.u",
        "symbol:s2:v": "$subquestion.s2.values.v",
        "symbol:s3:t": "$subquestion.s3.values.t",
        "symbol:s3:u": "$subquestion.s3.values.u",
    }
    if extra_root_symbol:
        expected["symbol:s0:z"] = "$question.s0.values.z"
    assert symbol_runtime_paths(payload) == expected
    facts = {fact["source_path"]: fact for fact in payload["facts"]}
    assert facts["/root/children/0/facts/0"]["entity_handles"] == [
        "symbol:s1:t", "symbol:s0:x", "symbol:s0:y",
    ]
    assert facts["/root/children/0/children/0/facts/0"]["entity_handles"] == [
        "symbol:s2:v", "symbol:s1:t", "symbol:s1:u", "symbol:s0:y",
    ]
    assert facts["/root/children/1/facts/1"]["entity_handles"] == [
        "symbol:s3:u", "symbol:s3:t", "symbol:s0:y",
    ]


def test_source_definitions_domains_and_expression_obligations():
    gold = candidate(
        ["x ∈ ℝ", "t ∈ (0,2]"],
        definitions=["x^2+t^2 = 1"],
        goals=[{"kind": "find_minimum", "expression": "sqrt(x)+1/t"}],
    )
    p = convert_notation(gold, problem_id="domain")
    assert [f["type"] for f in p["facts"]] == [
        "equation",
        "symbol_domain",
        "symbol_domain",
    ]
    assert p["facts"][0]["source_path"] == "/root/definitions/0"
    assert len(p["question_goals"][0]["domain_obligations"]) == 2
    assert all(
        o["status"] == "unverified"
        for o in p["question_goals"][0]["domain_obligations"]
    )
    assert len(p["facts"]) == 3  # no inferred positivity/default domain/nonzero facts


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("x^(1/2)", ["x >= 0"]),
        ("(a+b)^(2/3)", []),
        ("x^(-1/2)", ["x > 0"]),
        ("x^(1/(-2))", ["x > 0"]),
        ("x^(-2/3)", ["x != 0"]),
        ("x^(2/4)", ["x >= 0"]),
        ("x^(2/6)", []),
        ("x^(4/2)", []),
        ("x^(-4/2)", ["x != 0"]),
        ("x^(-2)", ["x != 0"]),
        ("x^0.5", ["x >= 0"]),
        ("x^(-0.5)", ["x > 0"]),
        ("(1/x)^(1/2)", ["(1/x) >= 0", "x != 0"]),
        ("sqrt(x)^(-1/3)", ["sqrt(x) != 0", "x >= 0"]),
        ("1/(x^(1/2))", ["(x^(1/2)) != 0", "x >= 0"]),
        ("(x^(1/2))^(1/3)", ["x >= 0"]),
    ],
)
@pytest.mark.parametrize("location", ("fact", "goal"))
def test_rational_exponent_domains_respect_exponent_position(expression, expected, location):
    gold = candidate(
        [f"{expression} = 1"] if location == "fact" else ["x > 0"],
        goals=[] if location == "fact" else [{"kind": "find_minimum", "expression": expression}],
    )
    p = convert_notation(gold, problem_id="rational-exponent")
    item = p["facts" if location == "fact" else "question_goals"][0]
    assert item["domain_obligations"] == [
        {"expression": text, "status": "unverified", "origin": "expression_domain"}
        for text in expected
    ]
    assert item["source_text"] == (f"{expression} = 1" if location == "fact" else expression)
    assert len(p["facts"]) == 1  # domain requirements never become source facts


@pytest.mark.parametrize("expression", ("x^(1/n)", "x^n", "x^(-n)", "x^(1+1)", "x^(1/0)"))
@pytest.mark.parametrize("location", ("fact", "goal"))
def test_unsupported_exponents_cannot_emit_incomplete_domain_obligations(expression, location):
    gold = candidate(
        [f"{expression} = 1"] if location == "fact" else ["x > 0"],
        goals=[] if location == "fact" else [{"kind": "find_minimum", "expression": expression}],
    )
    with pytest.raises(BasicInequalityProblemIRError, match="exponent"):
        convert_notation(gold, problem_id="unsupported-exponent")


def test_parameter_value_is_not_general_expression_evaluation():
    p = convert_notation(
        candidate(
            ["a > 0"],
            goals=[
                {"kind": "find_value", "expression": "a"},
                {"kind": "find_value", "expression": "a+1"},
            ],
        ),
        problem_id="parameter",
    )
    assert [g["value_type"] for g in p["question_goals"]] == [
        "ParameterValue",
        "ScalarExpression",
    ]
    with pytest.raises(BasicInequalityProblemIRError, match="supported goal"):
        validate_family_match(p, candidate_family_id="basic_inequality")
    p["question_goals"] = p["question_goals"][1:]
    with pytest.raises(BasicInequalityProblemIRError, match="supported goal"):
        validate_family_match(p, candidate_family_id="basic_inequality")


@pytest.mark.parametrize("supported_kind", ("find_minimum", "find_value"))
@pytest.mark.parametrize("nested", (False, True))
@pytest.mark.parametrize("reverse", (False, True))
def test_mixed_goals_fail_family_gate_and_frozen_file_entrypoint(monkeypatch, supported_kind, nested, reverse):
    gold = candidate(
        ["a > 0"],
        goals=[{"kind": supported_kind, "expression": "a"}],
    )
    scope = gold["root"]
    if nested:
        scope["children"] = [{"goals": []}]
        scope = scope["children"][0]
    scope["goals"].append({"kind": "find_value", "expression": "a+1"})
    if reverse:
        scope["goals"].reverse()
    p = convert_notation(gold, problem_id="mixed-goals")
    with pytest.raises(BasicInequalityProblemIRError, match="all goals must be supported"):
        validate_family_match(p, candidate_family_id="basic_inequality")
    # Isolate admission after verified loading; evidence replay has its own tests.
    monkeypatch.setattr(
        "shuxueshuo_server.problem_understanding.basic_inequality_frozen.load_verified_case",
        lambda path: {"gold": gold, "provenance": {"samples": []}},
    )
    with pytest.raises(BasicInequalityProblemIRError, match="all goals must be supported"):
        build_problem_ir_from_file("mixed-goals.json")


def test_family_gate_requires_nonempty_goals_and_accepts_all_supported_types():
    p = convert_notation(candidate(["a > 0"]), problem_id="empty-goals")
    with pytest.raises(BasicInequalityProblemIRError, match="missing supported goal"):
        validate_family_match(p, candidate_family_id="basic_inequality")
    p = convert_notation(
        candidate(["a > 0"], goals=[
            {"kind": kind, "symbol" if kind == "find_range" else "expression": "a"}
            for kind in ("find_minimum", "find_maximum", "find_range", "find_value")
        ]),
        problem_id="supported-goals",
    )
    assert validate_family_match(p, candidate_family_id="basic_inequality")["source_requirements_verified"] is True


@pytest.mark.parametrize(
    "gold",
    [
        candidate(["a > 0 ∨ a < -1"]),
        candidate(
            ["a > 0"], uncertainties=[{"kind": "ambiguous_symbol", "text": "a不清晰"}]
        ),
        candidate(["a > 0"], definitions=["f(t) = t^2"]),
    ],
)
def test_unsupported_or_ambiguous_source_fails_closed(gold):
    with pytest.raises(BasicInequalityProblemIRError):
        convert_notation(gold, problem_id="unsupported")


def test_matching_is_structural_and_production_remains_closed():
    p = convert_notation(read_json(GOLD / "q01.json"), problem_id="not-q01")
    assert (
        validate_family_match(p, candidate_family_id="basic_inequality")["family_id"]
        == "basic_inequality"
    )
    assert DEFAULT_FAMILY_REGISTRY.match(problem_from_canonical_input(p)) is None
    with pytest.raises(ValueError, match="ambiguous"):
        validate_family_match(
            p,
            candidate_family_id="basic_inequality",
            registry=FamilyRegistry((BASIC_INEQUALITY_FAMILY, BASIC_INEQUALITY_FAMILY)),
        )
    with pytest.raises(BasicInequalityProblemIRError, match="label"):
        validate_family_match(p, candidate_family_id="forged")
    for key, value in [
        ("pattern", "other"),
        ("problem_type", "other"),
        ("entities", []),
        ("facts", []),
        ("question_goals", []),
    ]:
        broken = {**p, key: value}
        with pytest.raises(BasicInequalityProblemIRError):
            validate_family_match(broken, candidate_family_id="basic_inequality")


def test_only_ten_cases_are_read_or_generated(monkeypatch):
    manifest = read_json(GOLD / "manifest.json")
    assert manifest["cases"] == list(REPRESENTATIVE_CASES)
    assert manifest["deferred_cases"] == DEFERRED_CASES
    assert {p.name for p in FIXTURES.iterdir() if p.is_dir()} == set(
        REPRESENTATIVE_CASES
    )
    assert {p.name for p in (GOLD / "samples").iterdir() if p.is_dir()} == set(
        REPRESENTATIVE_CASES
    )
    deferred = {f"q{i:02d}" for i in range(1, 32)} - set(REPRESENTATIVE_CASES)

    def forbidden(*args, **kwargs):
        raise AssertionError("deferred asset was read")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    for case in deferred:
        with pytest.raises(BasicInequalityProblemIRError, match="outside"):
            build_problem_ir_from_file(GOLD / f"{case}.json")
    with pytest.raises(BasicInequalityProblemIRError, match="exactly representative"):
        freeze_runs(GOLD, {"q02": []})


def test_freezing_validates_all_samples_before_writing_and_replays(tmp_path):
    root = tmp_path / "gold"
    shutil.copytree(GOLD, root, ignore=shutil.ignore_patterns("samples"))
    selections = {}
    for case in REPRESENTATIVE_CASES:
        selections[case] = []
        for number in (1, 2):
            sid = f"sample-{number:02d}"
            run = tmp_path / "runs" / case / sid / "run"
            shutil.copytree(GOLD / "samples" / case / sid, run)
            parsed = read_json(run / "parsed.json")
            for key in ("canonical", "normalized"):
                checksum = parsed["artifacts"][key]["sha256"]
                directory = run / "artifacts" / checksum[:2]
                directory.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(run / f"{key}.json", directory / f"{checksum}.json")
            selections[case].append(run)
    duplicate = {**selections, "q31": [selections["q31"][0]] * 2}
    with pytest.raises(BasicInequalityProblemIRError, match="same provider call"):
        freeze_runs(root, duplicate)
    assert not (root / "samples").exists()
    freeze_runs(root, selections)
    for case in REPRESENTATIVE_CASES:
        assert (
            len(load_verified_case(root / f"{case}.json")["provenance"]["samples"]) == 2
        )
    with pytest.raises(BasicInequalityProblemIRError, match="index already exists"):
        freeze_runs(root, selections)


def test_pure_lowering_never_runs_semantic_proofs_or_execution(monkeypatch):
    import shuxueshuo_server.problem_understanding.notation_semantics as semantics

    gold = read_json(GOLD / "q20.json")

    def forbidden(*args, **kwargs):
        raise AssertionError("proof/semantic compiler called during lowering")

    monkeypatch.setattr(semantics, "canonical", forbidden)
    monkeypatch.setattr(semantics, "compare", forbidden)
    monkeypatch.setattr(NotationValidator, "validate", forbidden)
    assert {
        e["name"] for e in convert_notation(gold, problem_id="arbitrary")["entities"]
    } == {"x", "y"}
    module = (
        ROOT / "shuxueshuo_server/problem_understanding/basic_inequality_problem_ir.py"
    )
    imports = [
        node.module or ""
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any(
        token in name
        for name in imports
        for token in ("runtime", "planner", "solver.methods", "notation_semantics")
    )
