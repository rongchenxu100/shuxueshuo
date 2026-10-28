"""Authored Q19 comparison/notation cases; these are not live model recordings."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.graph_lesson.stage_one.extraction import validate_candidate
from shuxueshuo_server.graph_lesson.stage_one.function_domain import _input_domain
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding import notation_compile
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.notation_compile import (
    NotationValidator,
    Report,
    Scope,
    typecheck,
)
from shuxueshuo_server.problem_understanding.notation_parser import NotationError, parse
from shuxueshuo_server.search.extraction import SearchStageOneContract
from shuxueshuo_server.search.identity import build_identity
from tests.solver.test_graph_function_equality_ir import identity
from tests.solver.test_graph_function_equality_recognition import envelope

FIXTURES = Path(__file__).parent / "fixtures/function-equality"
SOURCE = contracts.ROOT / "internal/senior-high/source-images/function-concepts-q19"


def candidate(public=False):
    return json.loads((FIXTURES / ("q19-public-candidate.json" if public else "q19-candidate.json")).read_text())


def compiled(value):
    report = NotationValidator().validate_root(value["root"], contracts.schema()["$defs"])
    assert report.ok, report.issues
    return report.semantic["goals"][0]


def test_q19_archived_source_is_the_recovered_attachment_and_one_rectangle():
    manifest = json.loads((SOURCE / "manifest.json").read_text())
    assert manifest["source_attachment_index"] == 1
    assert manifest["source_message"] == "msg_01a16d08-d6da-78c1-85ca-2c36c45d03e2"
    for key in ("page", "crop"):
        record = manifest[key]
        assert sha256((SOURCE / record["file"]).read_bytes()).hexdigest() == record["sha256"]
    with Image.open(SOURCE / manifest["page"]["file"]) as page, Image.open(SOURCE / manifest["crop"]["file"]) as crop:
        assert list(page.size) == manifest["page"]["size"]
        rectangle = page.convert("RGB").crop(manifest["crop"]["xyxy"])
        assert rectangle.size == crop.size and rectangle.tobytes() == crop.tobytes()


def test_q19_shared_baseline_has_one_identity_and_four_local_aliases():
    value = candidate()
    original = deepcopy(value)
    assert validate_candidate(value)["contract_valid"]
    goal = compiled(value)
    assert (goal["mode"], goal["select_relation"], goal["selection_mode"]) == ("shared_baseline", "equal", "multiple")
    assert len({o["left"]["function_ref"] for o in goal["options"]}) == 1
    assert len({o["right"]["function_ref"] for o in goal["options"]}) == 4
    assert all(o["left"]["function_ref"] != o["right"]["function_ref"] for o in goal["options"])
    assert all(o[side]["function_name"] == "f" and o[side]["variable"] == "x"
               for o in goal["options"] for side in ("left", "right"))
    assert not any(value["root"].get(key) for key in ("definitions", "facts", "children"))
    a, b, c, d = (option["right"] for option in goal["options"])
    assert a["expression_ast"][0] == "+" and a["expression_ast"][2][:2] == ["call", "abs"]
    assert b["expression_ast"][:2] == ["call", "sqrt"] and b["expression_ast"][2][0] == "^"
    assert c["expression_ast"][:2] == ["call", "abs"]
    assert d["expression_ast"][0] == "/" and d["expression_ast"][2][0] == "+"
    assert not any(o[side]["explicit_domain"] for o in goal["options"] for side in ("left", "right"))
    assert value == original


def test_q19_public_y_notation_is_separate_from_internal_function_aliases():
    public = candidate(public=True)
    report = SearchStageOneContract().parse(json.dumps(public), problem_id="q19-authored", source_hash="fixture", registry=None, store=None)
    assert report["contract_valid"], report
    statement = build_identity({"status": "reviewed_candidate", "source_reviewed": True,
                                "output_contract": "search-problem-extraction/v1",
                                "public_candidate": public, "candidate": candidate(),
                                "reviewed_candidate_revision": revision(public)})["statement"]
    assert "【例5】" not in statement
    assert "f(" not in statement and "g(" not in statement
    assert statement.count("y=") == 5
    assert all(f"{label}. " in statement for label in "ABCD")
    assert r"\sqrt{(2x^2+1)^2}" in statement
    assert "shared_functions 和各选项 functions" in contracts.SOURCE_RULES


def test_q19_reordered_options_keep_shared_and_local_object_identities():
    value = candidate()
    before = {option["label"]: option for option in compiled(value)["options"]}
    value["root"]["goals"][0]["options"].reverse()
    after = {option["label"]: option for option in compiled(value)["options"]}
    for label in "ABCD":
        for side in ("left", "right"):
            assert before[label][side]["function_ref"] == after[label][side]["function_ref"]
            assert before[label][side]["expression_ast"] == after[label][side]["expression_ast"]


@pytest.mark.parametrize("source", ["ℝ∖{-1,1/2}", "ℝ setminus {-1,1/2}"])
def test_set_difference_has_an_explicit_typed_operator(source):
    ast = Scope(Report(), "$.root").bind(parse(source))
    assert ast == ["set_difference", ["real"], ["set", ["neg", ["number", "1"]], ["/", ["number", "1"], ["number", "2"]]]]
    assert typecheck(ast) == "domain"


@pytest.mark.parametrize("domain", ["(0,2)∖{1}", "[0,2]∖{1,1,3}", "{0}∖{0}"])
def test_explicit_removed_points_preserve_source_structure_through_comparison(domain):
    value = candidate()
    function = value["root"]["goals"][0]["options"][0]["functions"][0]
    function["domain"] = domain
    result = compiled(value)["options"][0]["right"]
    assert result["explicit_domain"]
    assert result["input_domain_source_ref"] == "/root/goals/0/options/0/functions/0/domain"
    ast = result["input_domain_ast"]
    assert ast[0] == "set_difference" and ast[2][0] == "set"
    if domain.startswith("("):
        assert ast[1][:3] == ["interval", False, False]
    if domain == "[0,2]∖{1,1,3}":
        assert ast[2][1:] == [["number", "1"], ["number", "1"], ["number", "3"]]
    assert function["domain"] == domain


@pytest.mark.parametrize("domain", ["ℝ-{1}", "1∖{1}", "ℝ∖1", r"ℝ\setminus{1}"])
def test_domain_difference_does_not_coerce_arithmetic_or_latex(domain):
    value = candidate()
    value["root"]["goals"][0]["options"][0]["functions"][0]["domain"] = domain
    report = validate_candidate(value)
    assert not report["contract_valid"]
    assert report["reports"]["ir"]["issues"][0]["path"] == "/root/goals/0/options/0/functions/0/domain"


def test_set_difference_identity_keeps_the_declared_excluded_point():
    public = candidate(public=True)
    first = deepcopy(public)
    second = deepcopy(public)
    first["root"]["goals"][0]["shared_functions"][0]["domain"] = "ℝ∖{-1}"
    second["root"]["goals"][0]["shared_functions"][0]["domain"] = "ℝ∖{1}"
    assert len({identity(public), identity(first), identity(second)}) == 3
    first["root"]["goals"][0]["shared_functions"][0]["domain"] = "ℝ setminus {1}"
    assert identity(first) == identity(second)


def test_set_difference_does_not_enable_differences_in_scalar_bodies():
    with pytest.raises(NotationError, match="type.set_difference"):
        typecheck(["set_difference", ["number", "2"], ["set", ["number", "1"]]])


def test_nested_set_difference_typechecking_is_linear_before_domain_admission(monkeypatch):
    depth = 32
    ast = Scope(Report(), "$.root").bind(parse("ℝ" + "∖{0}" * depth))
    original_typecheck = notation_compile.typecheck
    calls = 0

    def counted(value):
        nonlocal calls
        calls += 1
        # Bound the regression itself: a repeated subtree walk must fail fast
        # rather than letting this small, syntactically valid source hang CI.
        assert calls <= 4 * depth + 1
        return original_typecheck(value)

    monkeypatch.setattr(notation_compile, "typecheck", counted)
    assert notation_compile.typecheck(ast) == "domain"
    assert calls == 3 * depth + 1  # difference, singleton set, number; one real base
    with pytest.raises(NotationError, match="domain.explicit_interval_required"):
        _input_domain(ast)


def test_q19_shared_baseline_reaches_the_existing_recognition_flow(tmp_path):
    value = envelope(candidate())
    result = run_result(value, tmp_path / "q19", verify=True)
    assert result["status"] == "completed"
    goal, = result["goals"]
    assert goal["primary"] == "type-function-equality"
    assert goal["supported"] == ["type-function-equality"]
    assert goal["primary_source"] == "program"
    assert result["llm"]["new_semantic_calls"] == 0
    assert not goal["d1"]["diagnostics"]
