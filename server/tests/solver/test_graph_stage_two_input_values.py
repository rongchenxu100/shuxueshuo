"""Input value shapes are checked before recognition, without recomputing features."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import (
    FEATURE_REGISTRY,
    extract_features,
)
from shuxueshuo_server.graph_lesson.stage_two.contracts import (
    FEATURE_VALUES_PATH,
    validate_input,
)
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result

RECORDED = Path(__file__).parent / "fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"


def accepted(case="q01", sample="sample-01"):
    return json.loads((RECORDED / case / sample / "stage-one-result.json").read_text())


@pytest.mark.parametrize("case,sample", [(f"q{i:02}", s) for i in range(1, 12) for s in ("sample-01", "sample-02")])
def test_all_actual_stage_one_value_shapes_remain_accepted(case, sample):
    checked = validate_input(accepted(case, sample))
    assert checked["ok"], checked


def test_legacy_goals_accept_absent_new_domain_feature_but_keep_existing_requirements():
    value = accepted()
    assert not any(row["feature_id"] == "function_domain" for row in value["features"])
    assert validate_input(value)["ok"]
    value["features"] = [row for row in value["features"] if row["feature_id"] != "relation"]
    checked = validate_input(value)
    assert any(row["code"] == "input.features_incomplete" and "relation" in row["message"]
               for row in checked["diagnostics"])


def test_find_domain_requires_its_new_feature_even_in_saved_result_envelope():
    candidate = {"original_text": "求函数 f(x)=sqrt(x-1)/(x-2) 的定义域。", "root": {
        "definitions": ["f(x)=sqrt(x-1)/(x-2)"], "goals": [{"kind": "find_domain", "object": "f"}],
    }}
    value = accepted()
    value.update(candidate=candidate, features=extract_features(candidate)["features"])
    assert validate_input(value)["ok"]
    value["features"] = [row for row in value["features"] if row["feature_id"] != "function_domain"]
    checked = validate_input(value)
    assert any(row["code"] == "input.features_incomplete" and "function_domain" in row["message"]
               for row in checked["diagnostics"])


def student_upload(value):
    value["statuses"] = {key: value["statuses"][key] for key in ("extraction", "source_reviewed", "features")}
    value["statuses"]["admission"] = "student_upload"
    return value


def test_student_upload_is_admitted_without_gold_evaluation():
    value = student_upload(accepted())
    assert validate_input(value, "student_upload")["ok"]
    # The same gold-free input never passes as an acceptance-batch result.
    codes = {d["path"] for d in validate_input(value)["diagnostics"]}
    assert {"/statuses/evaluation", "/statuses/passed"} <= codes


@pytest.mark.parametrize("change,path", [
    (lambda s: s.pop("admission"), "/statuses/admission"),
    (lambda s: s.update(source_reviewed=False), "/statuses/source_reviewed"),
    (lambda s: s.update(features=False), "/statuses/features"),
    (lambda s: s.update(extraction="needs_confirmation"), "/statuses/extraction"),
])
def test_student_upload_still_requires_review_and_features(change, path):
    value = student_upload(accepted())
    change(value["statuses"])
    checked = validate_input(value, "student_upload")
    assert not checked["ok"] and path in {d["path"] for d in checked["diagnostics"]}


def test_student_upload_run_records_its_admission(tmp_path):
    result = run_result(student_upload(accepted()), tmp_path / "run", admission="student_upload")
    assert result["status"] == "completed" and result["options"]["admission"] == "student_upload"
    assert result["goals"][0]["primary"] == "type-quantified-quadratic"


@pytest.mark.parametrize("feature,value", [
    ("quantifier", "forall"), ("quantifier", None),
    ("bound_vars", "x"), ("bound_vars", []), ("free_vars", [3]),
    ("goal", {"kind": "find_value", "symbol": "a"}),
    ("domain", {"expression": "ℝ"}), ("domain_kind", "closed"),
    ("relation", {"operator": "==", "strict": False, "lhs": "x", "rhs": "a"}),
    ("normal_form", None),
    ("degree_in_bound", {"variable": "x", "degree": 2, "degree_kind": "unknown", "expression": "x^2"}),
    ("degree_in_goal", {"variable": "a", "degree": None, "degree_kind": "exact", "expression": "a"}),
    ("leading_coeff_in_bound", {"variable": "x", "expression": "1", "contains_parameters": False, "may_be_zero": 0}),
    ("coefficients", {"variable": "x", "expression": "x", "items": [0]}),
    ("range_var_is_principal", 1),
])
@pytest.mark.parametrize("status", ["known", "conditional"])
def test_invalid_values_are_input_errors(feature, value, status):
    original = accepted()
    row = next(f for f in original["features"] if f["feature_id"] == feature)
    row.update(value=value, status=status)
    if status == "conditional":
        row["conditions"] = [{"expression": "a", "operator": "!=", "rhs": "0"}]
    checked = validate_input(original)
    assert not checked["ok"]
    assert any(d["code"] == "input.feature_value" and "/value" in d["path"] for d in checked["diagnostics"])


def test_corrupt_coefficients_cannot_crash_runner_or_reach_recognition(tmp_path, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_two import recognition

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid feature value reached recognition/provider")

    original = accepted()
    next(f for f in original["features"] if f["feature_id"] == "coefficients")["value"] = {"items": [0]}
    monkeypatch.setattr(recognition, "evaluate_types", forbidden)
    output = tmp_path / "run"
    result = run_result(original, output, provider=forbidden, unsupported_root=tmp_path / "pending")
    assert result["status"] == "input_error" and result["goals"] == []
    assert result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 0
    assert (output / "stage-two-result.json").is_file()
    assert (output / "index.html").is_file()
    assert not (tmp_path / "pending").exists()


def test_schema_covers_registry_and_real_conditional_shapes():
    schema = json.loads(FEATURE_VALUES_PATH.read_text())
    assert set(schema["$defs"]) == {s.feature_id for s in FEATURE_REGISTRY}
    # A deterministic unit-test candidate exercises the extractor's conditional
    # data shape. This is not presented as a fresh image-reviewed/live result.
    candidate = {"original_text": "∀x∈[1/a,2]:x²≥a，求a。", "root": {
        "facts": ["∀x∈[1/a,2]:x^2>=a"], "goals": [{"kind": "find_range", "symbol": "a"}],
    }}
    original = accepted()
    original.update(candidate=candidate, features=extract_features(candidate)["features"])
    assert any(f["status"] == "conditional" for f in original["features"])
    checked = validate_input(original)
    assert checked["ok"], checked


def test_real_unknown_values_are_not_forced_to_known_shapes():
    original = accepted("q11")
    rows = [f for f in original["features"] if f["status"] == "unknown"]
    assert rows and all(f["value"] is None and f["diagnostics"] for f in rows)
    assert validate_input(deepcopy(original))["ok"]


@pytest.mark.parametrize("ref", [
    0, None, {}, [], "root/facts/0", "/root/facts/999", "/root/facts/-1",
    "/root/facts/00", "/root/facts/~2",
])
def test_source_refs_must_be_resolvable_json_pointers(ref):
    original = accepted()
    row = next(f for f in original["features"] if f["feature_id"] == "quantifier")
    row["source_refs"] = [ref]
    checked = validate_input(original)
    assert not checked["ok"]
    assert any(d["code"] == "input.feature_source_ref" and d["path"].endswith("/source_refs/0")
               for d in checked["diagnostics"])


@pytest.mark.parametrize("ref", [
    "", "/root", "/original_text", "/root/facts", "/root/goals/0/symbol",
])
def test_sources_reference_concrete_evidence_not_enclosing_containers(ref):
    original = accepted()
    original["features"][0]["source_refs"] = [ref]
    checked = validate_input(original)
    assert not checked["ok"]
    assert any(d["code"] == "input.feature_source_scope" for d in checked["diagnostics"])


@pytest.mark.parametrize("ref", ["/root/children/1/facts/0", "/root/children/1/goals/0"])
def test_sibling_sources_are_not_visible_to_another_goal(ref):
    original = accepted("q10")
    row = next(f for f in original["features"] if f["target_ref"] == "/root/children/0/goals/0")
    row["source_refs"] = [ref]
    checked = validate_input(original)
    assert not checked["ok"]
    assert any(d["code"] == "input.feature_source_scope" for d in checked["diagnostics"])


def scoped_result():
    # Constructed structural fixture, not a new image-reviewed/live result.
    candidate = {"original_text": "求 a、b 的范围。", "root": {
        "definitions": ["f(x)=x^2"],
        "facts": ["∀x∈ℝ:f(x)>=a"],
        "goals": [{"kind": "find_range", "symbol": "a"},
                  {"kind": "find_range", "symbol": "a"}],
        "children": [{"facts": ["b∈ℝ"], "goals": [{"kind": "find_range", "symbol": "b"}]}],
    }}
    original = accepted()
    original.update(candidate=candidate, features=extract_features(candidate)["features"])
    assert validate_input(original)["ok"]
    return original


@pytest.mark.parametrize("target,ref", [
    ("/root/goals/0", "/root/goals/1"),
    ("/root/goals/0", "/root/children/0/facts/0"),
    ("/root/goals/0", "/root/children/0/goals/0"),
    ("/root/children/0/goals/0", "/root/goals/0"),
])
def test_descendants_and_other_goals_are_not_feature_sources(target, ref):
    original = scoped_result()
    row = next(f for f in original["features"] if f["target_ref"] == target)
    row["source_refs"] = [ref]
    checked = validate_input(original)
    assert not checked["ok"]
    assert any(d["code"] == "input.feature_source_scope" for d in checked["diagnostics"])


def test_local_and_ancestor_facts_definitions_and_own_goal_are_valid_sources():
    original = scoped_result()
    target = "/root/children/0/goals/0"
    row = next(f for f in original["features"] if f["target_ref"] == target)
    row["source_refs"] = ["/root/facts/0", "/root/definitions/0", "/root/children/0/facts/0", target]
    assert validate_input(original)["ok"]


def test_unknown_feature_sources_are_checked_too():
    original = accepted("q11")
    row = next(f for f in original["features"] if f["status"] == "unknown")
    row["source_refs"] = [None]
    assert not validate_input(original)["ok"]


@pytest.mark.parametrize("name,entries", [
    ("conditions", "a!=0"), ("conditions", [0]),
    ("diagnostics", "unknown"), ("diagnostics", [None]),
])
def test_feature_reasons_are_object_lists(name, entries):
    original = accepted()
    original["features"][0][name] = entries
    checked = validate_input(original)
    assert not checked["ok"]
    assert any(d["code"] == "input.feature_reason" and d["path"].endswith("/" + name)
               for d in checked["diagnostics"])


def test_mixed_source_ref_types_cannot_reach_d1_or_provider(tmp_path, monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_two import fragments

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid source ref reached D1/provider")

    original = accepted()
    row = next(f for f in original["features"] if f["feature_id"] == "quantifier")
    row["source_refs"].append(0)
    monkeypatch.setattr(fragments, "build_d1", forbidden)
    output = tmp_path / "run"
    result = run_result(original, output, provider=forbidden, unsupported_root=tmp_path / "pending")
    assert result["status"] == "input_error" and result["goals"] == []
    assert result["llm"]["new_semantic_calls"] == result["llm"]["new_network_attempts"] == 0
    assert (output / "stage-two-result.json").is_file()
    assert (output / "index.html").is_file()
    assert not (tmp_path / "pending").exists()
