"""Notation contract, binding, semantic mutations and versioned integration gates."""

import json
import re
from copy import deepcopy
from hashlib import sha256

import pytest
from _math_notation_test_support import Recorded
from jsonschema import Draft202012Validator

from shuxueshuo_server.problem_understanding.batch_smoke import (
    CASES,
    NOTATION_FIXTURES,
    prepare_fixture,
)
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_contract import (
    CONTRACT,
    EXPRESSIONS_PATH,
    NOTATION,
    SYSTEM_PATH,
    TEMPLATE_FILES,
    USER_PATH,
    expression_catalog,
    schema,
)
from shuxueshuo_server.problem_understanding.notation_semantics import compare, evaluate
from shuxueshuo_server.problem_understanding.notation_service import (
    parse_candidate,
    render,
)
from shuxueshuo_server.problem_understanding.smoke import build_request, run
from shuxueshuo_server.problem_understanding.wire import components
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    problem_domain_family_catalog,
)


def gold(case):
    return json.loads((NOTATION_FIXTURES / (case + ".json")).read_text())


def candidate(root):
    return {
        "root": root,
        "family_id": None,
        "match_status": "unmatched",
        "match_reason": "独立测试",
    }


def parse_candidate_for_test(payload):
    return parse_candidate(
        json.dumps(payload),
        problem_id="test",
        source_sha256="0" * 64,
        registry_snapshot="0" * 64,
        registered_families=[f["family_id"] for f in problem_domain_family_catalog()],
    )


@pytest.mark.parametrize("case", CASES)
def test_gold_compiles_without_model_side_entities(case):
    payload = gold(case)
    report = NotationValidator().validate(payload)
    assert report.ok, report.issues
    assert compare(payload, payload)["ok"]
    assert parse_candidate_for_test(payload)["contract_valid"]
    assert report.objects
    assert all("entities" not in unit for unit in report.normalized["root"])


def test_contract_annotations_and_no_old_fact_schema_in_actual_request(tmp_path):
    Draft202012Validator.check_schema(schema())
    fixture = prepare_fixture(CASES[0], tmp_path)
    request = build_request(fixture, ExtractionArtifactStore(tmp_path / "request"), [])
    payload = json.loads(request.prompt.user_prefix)
    assert request.contract_version == CONTRACT
    assert payload["response_schema"] == schema() == request.contract_schema
    assert payload["math_expression_catalog"] == json.loads(
        EXPRESSIONS_PATH.read_text()
    )
    assert payload["response_schema"]["$defs"]["Scope"]["properties"]["facts"][
        "items"
    ] == {"type": "string", "minLength": 1, "maxLength": 4096, "description": NOTATION}
    properties = payload["response_schema"]["$defs"]["Scope"]["properties"]
    assert not {"entities", "source_text"} & properties.keys()
    assert "Fact" not in payload["response_schema"]["$defs"]
    assert "goal_plans" not in payload
    assert request.prompt.system == SYSTEM_PATH.read_text().strip()
    assert "不将“(1)图甲”“(1)图乙”平铺" in request.prompt.system
    assert "提供图甲不能代替题面引用的图乙" in request.prompt.system
    assert "示例五：同一分问的两幅图，仅提供其中一幅" in request.prompt.system
    assert request.prompt.user_suffix == USER_PATH.read_text().strip()
    examples = re.findall(r"```json\n(.*?)\n```", request.prompt.system, re.DOTALL)
    assert len(examples) == 6
    for raw in examples:
        example = json.loads(raw)
        assert NotationValidator().validate(example).ok
        assert compare(example, example)["ok"]
    assert "independent_example" not in payload
    for case in CASES:
        assert case not in request.prompt.user_prefix
        assert case not in request.prompt.system


def test_schema_documents_each_goal_and_uncertainty_kind():
    value = schema()
    fields = value["$defs"]["Scope"]["properties"]
    goals = fields["goals"]["items"]["oneOf"]
    assert {g["properties"]["kind"]["const"] for g in goals} == {
        "find_value",
        "find_coordinates",
        "find_equation",
        "find_minimum",
        "find_maximum",
        "find_range",
    }
    for goal in goals:
        assert goal["description"]
        assert all(field.get("description") for field in goal["properties"].values())
    kinds = fields["uncertainties"]["items"]["properties"]["kind"]
    assert all(kind in kinds["description"] for kind in kinds["enum"])
    assert "registered_families" in value["properties"]["family_id"]["description"]


def test_external_prompt_files_are_frozen_with_request(tmp_path):
    fixture = prepare_fixture("function-quantifiers", tmp_path)
    result = run(
        fixture,
        tmp_path / "run",
        Recorded((fixture / "gold.json").read_text()),
        list(problem_domain_family_catalog()),
    )
    assert result["passed"]
    frozen = json.loads((tmp_path / "run/frozen.json").read_text())
    assert len(frozen["template_files"]) == 4
    assert sorted(frozen["template_files"].values()) == sorted(
        sha256(path.read_bytes()).hexdigest() for path in TEMPLATE_FILES
    )


def test_expression_catalog_examples_use_supported_notation():
    from shuxueshuo_server.problem_understanding.notation_parser import definition

    entries = expression_catalog()["expressions"]
    assert len({entry["id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert entry["syntax"] and entry["meaning"] and entry["examples"]
        for example in entry["examples"]:
            assert definition(example), (entry["id"], example)


def test_optional_fields_defaults_and_extremum_hints():
    expected = gold("tj-2026-nankai-yimo-25")
    actual = deepcopy(expected)

    def strip(scope):
        scope["facts"] = [
            x.replace("min_{E,G}", "min")
            for x in scope.get("facts", [])
            if "∈ ℝ" not in x
        ]
        for g in scope.get("goals", []):
            g.pop("variables", None)
        for c in scope.get("children", []):
            strip(c)
        if not scope["facts"]:
            scope.pop("facts")

    strip(actual["root"])
    assert compare(expected, actual)["ok"]
    compiled = NotationValidator().validate(actual)
    assert all(x["origin"] == "code_default" for x in compiled.defaults)
    assert "variables" not in actual["root"]["children"][1]["children"][0]["goals"][1]


def test_function_calls_expand_only_in_code_and_quantifier_binding_is_local():
    expected = gold("function-quantifiers")
    actual = deepcopy(expected)
    actual["root"]["children"][0]["facts"] = ["∀t∈ℝ: t^2+b*t+c ≥ 2*t-1"]
    actual["root"]["children"][1]["facts"] = ["∃u∈[1,3]: u^2+b*u+c ≤ 2*u-1"]
    assert compare(expected, actual)["ok"]
    objects = NotationValidator().validate(actual).objects
    assert not {"t", "u", "x", "x0"} & {x["name"] for x in objects}


def test_aliases_fact_order_and_basic_algebra():
    expected = gold("tj-2026-nankai-yimo-25")
    actual = json.loads(json.dumps(expected, ensure_ascii=False).replace("Γ", "Q"))
    actual["root"]["facts"] = list(reversed(actual["root"]["facts"]))
    actual["root"]["facts"] = [
        f.replace("2*a+b = 0", "b = -2*a") for f in actual["root"]["facts"]
    ]
    assert compare(expected, actual)["ok"]


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("collection", ["definitions", "facts"])
def test_collection_placement_does_not_change_math_objects(case, collection):
    expected = gold(case)
    actual = deepcopy(expected)

    def move(scope):
        expressions = scope.pop("definitions", []) + scope.pop("facts", [])
        scope[collection] = expressions
        for child in scope.get("children", []):
            move(child)

    move(actual["root"])
    before, after = (NotationValidator().validate(p) for p in (expected, actual))
    assert after.ok, after.issues
    assert before.objects == after.objects
    assert compare(expected, actual)["ok"]


def test_mixed_function_values_and_coordinate_relations_are_not_definitions():
    expected = candidate(
        {
            "definitions": ["f(x)=x^2", "P=(1,2)"],
            "facts": ["f(t)=4", "x(P)=1"],
        }
    )
    actual = candidate(
        {
            "facts": ["f(x)=x^2", "P=(1,2)", "f(t)=4", "x(P)=1"],
        }
    )
    assert compare(expected, actual)["ok"]
    report = NotationValidator().validate(actual)
    assert (
        len([x for x in report.semantic["facts"] if x[0] == "function_definition"]) == 1
    )
    assert any(obj["name"] == "t" and obj["kind"] == "scalar" for obj in report.objects)
    actual["root"] = {"definitions": actual["root"]["facts"]}
    assert compare(expected, actual)["ok"]


@pytest.mark.parametrize("collection", ["definitions", "facts"])
def test_array_compatibility_does_not_accept_natural_language_object_references(
    collection,
):
    report = NotationValidator().validate(candidate({collection: ["P ∈ 该抛物线"]}))
    assert not report.ok
    assert report.issues[0]["source"] == "P ∈ 该抛物线"


@pytest.mark.parametrize(
    "old,new",
    [
        ("∀x∈ℝ", "∃x∈ℝ"),
        ("[1,3]", "(1,3]"),
        ("f(x) ≥ g(x)", "f(x) > g(x)"),
    ],
)
def test_quantifier_domain_and_relation_mutations_fail(old, new):
    expected = gold("function-quantifiers")
    actual = json.loads(json.dumps(expected, ensure_ascii=False).replace(old, new))
    assert not compare(expected, actual)["ok"]


def test_ray_and_state_condition_mutations_fail():
    expected = gold("tj-2026-heping-yimo-25")
    actual = json.loads(json.dumps(expected).replace("ray(C,D)", "line(C,D)"))
    assert not compare(expected, actual)["ok"]
    expected = gold("tj-2026-heping-ermo-25")
    actual = deepcopy(expected)
    actual["root"]["children"][1]["facts"].remove("HF+FM+MG = min(HF+FM+MG)")
    assert not compare(expected, actual)["ok"]


def test_ratio_direction_and_definition_branch_mutations_fail():
    expected = candidate({"facts": ["quadrilateral(A,B,C,D)", "cut_ratio(BD,AC) = k"]})
    reversed_ratio = candidate(
        {"facts": ["quadrilateral(A,B,C,D)", "cut_ratio(DB,AC) = k"]}
    )
    reversed_line = candidate(
        {"facts": ["quadrilateral(A,B,C,D)", "cut_ratio(BD,CA) = k"]}
    )
    assert not compare(expected, reversed_ratio)["ok"]
    assert compare(expected, reversed_line)["ok"]
    expected = gold("k-quad")
    actual = deepcopy(expected)
    actual["root"]["children"][0]["children"][0]["facts"][-1] = (
        "bisects(ED,AC) ∧ (cut_ratio(ED,AC)=k ∨ cut_ratio(ED,AC)=1/k)"
    )
    assert not compare(expected, actual)["ok"]


def test_sibling_points_invisible_and_independent_same_names_local():
    payload = candidate(
        {
            "children": [
                {"facts": ["A = (0,0)"]},
                {"facts": ["B = A+(1,0)"]},
            ]
        }
    )
    report = NotationValidator().validate(payload)
    assert not report.ok and any(
        x["reason_code"] == "binding.unknown_or_invisible"
        and x["source"] == "B = A+(1,0)"
        for x in report.issues
    )
    payload["root"]["children"][1]["facts"] = ["A = (2,0)"]
    report = NotationValidator().validate(payload)
    assert report.ok
    points = [x for x in report.objects if x["name"] == "A"]
    assert len({p["ref"] for p in points}) == 2


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "a.__class__ = 1",
        "sum([1,2]) = 3",
        "x = 1/0",
        "a = sqrt(-1)",
        "a = 2^99999",
        "a = ((b+c)^12)^12",
        "A = midpoint(B)",
        "a = " + "(" * 50 + "1" + ")" * 50,
    ],
)
def test_invalid_or_unsafe_math_never_becomes_valid_candidate(expression):
    payload = candidate({"facts": [expression]})
    parsed = parse_candidate_for_test(payload)
    assert not parsed["contract_valid"]
    assert parsed["continuation"]["blocked"]


def test_unknown_mathematics_reports_source_and_path():
    report = NotationValidator().validate(candidate({"facts": ["P lies somewhere"]}))
    assert not report.ok
    assert report.issues[0]["path"] == "r.facts[0]"
    assert report.issues[0]["source"] == "P lies somewhere"


def test_real_domain_conflict_is_not_ignored():
    report = NotationValidator().validate(candidate({"facts": ["A = (0,0)", "A ∈ ℝ"]}))
    assert not report.ok


@pytest.mark.parametrize(
    "compact,explicit",
    [
        ("2a+b=0", "2*a+b=0"),
        ("t=√34", "t=sqrt(34)"),
        ("t=√(2+3)", "t=sqrt(2+3)"),
        ("t=min_N(√2*MN+AN)", "t=min_{N}(sqrt(2)*MN+AN)"),
        ("∠BDC=2∠ABD", "∠BDC=2*∠ABD"),
    ],
)
def test_recorded_notation_variants_have_identical_syntax(compact, explicit):
    from shuxueshuo_server.problem_understanding.notation_parser import parse

    assert parse(compact) == parse(explicit)


def test_named_new_definition_is_audit_prose_not_hidden_execution():
    from shuxueshuo_server.problem_understanding.notation_parser import (
        clean,
        definition,
    )

    text = "特殊四边形：若两条边相等，则称为特殊四边形。"
    assert definition(text) == ["definition_prose", clean(text)]
    result = NotationValidator().validate(candidate({"definitions": [text]}))
    assert result.ok and not result.objects


def test_invalid_math_still_preserves_missing_figure_gate_and_artifacts(tmp_path):
    payload = candidate(
        {
            "facts": ["P lies somewhere"],
            "uncertainties": [{"kind": "missing_figure", "text": "图示缺失"}],
        }
    )
    parsed = parse_candidate(
        json.dumps(payload),
        problem_id="test",
        source_sha256="0" * 64,
        registry_snapshot="0" * 64,
        registered_families=[],
        store=ExtractionArtifactStore(tmp_path),
    )
    assert not parsed["contract_valid"]
    assert parsed["continuation"]["error_code"] == "extraction.missing_figure"
    assert {"normalized", "compiled", "validation", "raw"} <= parsed["artifacts"].keys()
    assert "ir" not in parsed["objects"]


def test_uncertainty_scope_and_missing_figure_policy_preserved():
    expected = gold("k-quad")
    result = parse_candidate_for_test(expected)
    assert result["contract_valid"] and result["continuation"]["blocked"]
    assert len(result["continuation"]["missing_figures"]) == 4
    assert not result["solver_ready"]
    actual = deepcopy(expected)
    actual["root"]["children"][0]["children"][0].pop("uncertainties")
    assert not compare(expected, actual)["ok"]
    policy = json.loads(
        (NOTATION_FIXTURES / "k-quad.acceptance-policy.json").read_text()
    )
    actual = deepcopy(expected)
    for path in ([0, 0], [0, 1], [1]):
        scope = actual["root"]
        for i in path:
            scope = scope["children"][i]
        scope["facts"].remove("k ≥ 1")
    assert not compare(expected, actual)["ok"]
    assert evaluate(expected, actual, policy)["ok"]


def test_definition_prose_retained_and_not_executed():
    expected = gold("k-quad")
    report = NotationValidator().validate(expected)
    assert report.semantic["facts"][0][0] == "definition_prose"
    assert expected["root"]["definitions"][0] in render(expected)
    # A string that is not recognized as definition prose cannot hide a fact.
    assert (
        not NotationValidator()
        .validate(candidate({"definitions": ["点A满足未知关系"]}))
        .ok
    )


def test_no_shape_based_contract_fallback():
    with pytest.raises(ValueError, match="unsupported extraction contract"):
        components("guess")
    legacy = {
        "schema_version": "problem-domain/v2",
        "root": {},
        "family_id": None,
        "match_status": "unmatched",
        "match_reason": "old",
    }
    assert not parse_candidate_for_test(legacy)["contract_valid"]
