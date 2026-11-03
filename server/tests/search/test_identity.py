"""Public identity is stricter than the existing mathematical admission."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.identity import (
    EXTRACTION_CONTRACT,
    IdentityUnavailable,
    build_identity,
    mathematical_candidate,
)

CORPUS = Path(__file__).parents[1] / "solver/fixtures/graph-guided-stage-one/quadratic-always"


def public_candidate(case="q01"):
    candidate = json.loads((CORPUS / case / "notation.gold.json").read_text(encoding="utf-8"))
    candidate["public_content"] = {
        "completeness": "complete", "privacy": "separated", "figure": "not_required",
        "figure_detection": {"status": "none", "regions": []},
        "scopes": [{"scope_ref": "/root", "statement": candidate["original_text"],
                    "choices": [{"target_ref": "/root/goals/0", "status": "none", "selection_mode": "none", "options": []}]}],
    }
    return candidate


def reviewed_result(candidate):
    return {"status": "reviewed_candidate", "source_reviewed": True, "output_contract": EXTRACTION_CONTRACT,
            "candidate": mathematical_candidate(candidate), "public_candidate": deepcopy(candidate),
            "reviewed_candidate_revision": revision(candidate)}


def identity(candidate):
    return build_identity(reviewed_result(candidate))


def choices(candidate):
    choice = candidate["public_content"]["scopes"][0]["choices"][0]
    choice.update(status="complete", selection_mode="single",
                  options=[{"label": label, "text": text} for label, text in zip("ABC", ("$a≤0$", "$a>0$", "不存在"), strict=True)])
    return choice


def test_identity_is_deterministic_and_excludes_private_source_fields():
    candidate = public_candidate()
    result = reviewed_result(candidate)
    expected = build_identity(result)
    result.update(search_id="another-upload", run_id="another-run", features_ok=False,
                  question_sha256="another-image", elapsed_seconds=99)
    assert build_identity(result) == expected
    assert expected["fingerprint"] == revision(expected["identity"])
    assert expected["fingerprint"] == "34b4b650fe610ac447d6a3003ef21c06795d40a71bb629b1bd5c354212775edf"
    assert expected["identity_version"] == expected["identity"]["identity_version"] == 1
    assert expected["structured_problem"] == expected["identity"]
    assert "original_text" not in json.dumps(expected)
    candidate["original_text"] = "不同照片的私有转录和明确分离的试卷题号 13。" + candidate["original_text"]
    candidate["root"]["label"] = "13."
    candidate["public_content"]["root_label_role"] = "source"
    assert identity(candidate) == expected


def test_supported_notation_and_whitespace_match_without_semantic_rewriting():
    candidate = public_candidate()
    changed = deepcopy(candidate)
    changed["public_content"]["scopes"][0]["statement"] = changed["public_content"]["scopes"][0]["statement"].replace(r"\le", "≤").replace("求实数", "求\n实数").replace("a^2-3a", "a^2 - 3a")
    changed["root"]["facts"][1] = changed["root"]["facts"][1].replace(" ≤ ", "<=").replace("∀x", "∀ x")
    assert identity(changed) == identity(candidate)


@pytest.mark.parametrize("before,after", [("∀", "∃"), ("≤", "<"), ("a^2-3*a", "a^2-4*a")])
def test_mathematical_differences_never_merge(before, after):
    candidate = public_candidate()
    changed = deepcopy(candidate)
    changed["root"]["facts"][1] = changed["root"]["facts"][1].replace(before, after)
    assert identity(changed)["fingerprint"] != identity(candidate)["fingerprint"]


def test_expansion_variable_rename_and_goal_qualifiers_are_not_rewritten():
    candidate = public_candidate()
    for update in (
        lambda value: value["root"]["facts"].__setitem__(1, "∀x∈ℝ: -x^2+2*x+3≤a*(a-3)"),
        lambda value: value["root"]["goals"][0].update(kind="find_minimum", expression="a"),
        lambda value: value["root"]["goals"][0].update(in_terms_of=["a"]),
    ):
        changed = deepcopy(candidate)
        update(changed)
        if "expression" in changed["root"]["goals"][0]:
            changed["root"]["goals"][0].pop("symbol")
        assert identity(changed)["fingerprint"] != identity(candidate)["fingerprint"]
    changed = deepcopy(candidate)
    changed["root"]["facts"] = [text.replace("a", "b") for text in changed["root"]["facts"]]
    changed["root"]["goals"][0]["symbol"] = "b"
    assert identity(changed)["fingerprint"] != identity(candidate)["fingerprint"]


def test_complete_three_choices_modes_and_order_are_preserved():
    candidate = public_candidate()
    choice = choices(candidate)
    original = identity(candidate)
    assert len(original["identity"]["scopes"][0]["choices"][0]["options"]) == 3
    choice["options"][0]["text"], choice["options"][1]["text"] = choice["options"][1]["text"], choice["options"][0]["text"]
    assert identity(candidate)["fingerprint"] != original["fingerprint"]
    choice["selection_mode"] = "multiple"
    assert identity(candidate)["fingerprint"] != original["fingerprint"]


@pytest.mark.parametrize("field,value,code", [
    ("completeness", "incomplete", "incomplete_problem"),
    ("completeness", "unknown", "incomplete_problem"),
    ("privacy", "uncertain", "private_content_unseparated"),
    ("figure", "unrepresented", "unrepresented_figure"),
])
def test_public_admission_requires_explicit_completeness(field, value, code):
    candidate = public_candidate()
    candidate["public_content"][field] = value
    with pytest.raises(IdentityUnavailable, match="identity." + code):
        identity(candidate)


@pytest.mark.parametrize("status", ["incomplete", "unknown"])
def test_missing_choices_are_not_no_choices(status):
    candidate = public_candidate()
    candidate["public_content"]["scopes"][0]["choices"][0]["status"] = status
    with pytest.raises(IdentityUnavailable, match="identity.incomplete_choices"):
        identity(candidate)


def test_unknown_fields_missing_goals_and_ambiguous_scope_are_rejected():
    candidate = public_candidate()
    for update in (
        lambda value: value["public_content"].update(student_name="private"),
        lambda value: value["public_content"]["scopes"][0].update(scope_ref="/root/children/0"),
        lambda value: value["public_content"]["scopes"][0].update(choices=[]),
        lambda value: value["public_content"]["scopes"][0].update(statement=" "),
    ):
        changed = deepcopy(candidate)
        update(changed)
        with pytest.raises(IdentityUnavailable):
            identity(changed)


def test_old_confirmed_result_and_changed_public_content_cannot_be_published():
    result = reviewed_result(public_candidate())
    legacy = {key: value for key, value in result.items() if key not in {"public_candidate", "output_contract", "reviewed_candidate_revision"}}
    with pytest.raises(IdentityUnavailable, match="identity.missing_public_contract"):
        build_identity(legacy)
    result["public_candidate"]["public_content"]["scopes"][0]["statement"] += "修改题意"
    with pytest.raises(IdentityUnavailable, match="identity.review_revision_mismatch"):
        build_identity(result)


def test_real_legacy_crop_recording_does_not_claim_new_public_review():
    source = Path(__file__).parent / "fixtures/parameter-extremum/recorded-20261018/historical-result.json"
    recorded = json.loads(source.read_text(encoding="utf-8"))
    assert recorded["source_reviewed"] and recorded["status"] == "reviewed_candidate"
    with pytest.raises(IdentityUnavailable, match="identity.missing_public_contract"):
        build_identity(recorded)


def test_partial_question_tree_and_interval_endpoints_do_not_merge():
    candidate = public_candidate("q11")
    candidate["public_content"]["scopes"] = [
        {"scope_ref": "/root", "statement": "已知函数 $f(x)=mx^2-mx-1$。", "choices": []},
        {"scope_ref": "/root/children/0", "statement": "当 $m=1$ 时，解不等式 $f(x)<0$。", "choices": [
            {"target_ref": "/root/children/0/goals/0", "status": "none", "selection_mode": "none", "options": []}]},
        {"scope_ref": "/root/children/1", "statement": "若对任意 $x∈[1,3]$，$f(x)<-m+5$ 恒成立，求实数 $m$ 的取值范围。", "choices": [
            {"target_ref": "/root/children/1/goals/0", "status": "none", "selection_mode": "none", "options": []}]},
    ]
    original = identity(candidate)
    changed = deepcopy(candidate)
    changed["root"]["children"][1]["facts"][0] = changed["root"]["children"][1]["facts"][0].replace("[1,3]", "(1,3)")
    assert identity(changed)["fingerprint"] != original["fingerprint"]
    candidate["root"]["children"].pop()
    with pytest.raises(IdentityUnavailable, match="identity.invalid_public_structure"):
        identity(candidate)


def test_normalization_preserves_separated_identifiers_and_unknown_commands():
    candidate = public_candidate()
    first, second = deepcopy(candidate), deepcopy(candidate)
    first["public_content"]["scopes"][0]["statement"] = "求 $a b$。"
    second["public_content"]["scopes"][0]["statement"] = "求 $ab$。"
    assert identity(first)["fingerprint"] != identity(second)["fingerprint"]
    first["public_content"]["scopes"][0]["statement"] = "求 $α β$。"
    second["public_content"]["scopes"][0]["statement"] = "求 $αβ$。"
    assert identity(first)["fingerprint"] != identity(second)["fingerprint"]
    first["public_content"]["scopes"][0]["statement"] = r"求 $\unknown x$。"
    second["public_content"]["scopes"][0]["statement"] = "求 $x$。"
    assert identity(first)["fingerprint"] != identity(second)["fingerprint"]


@pytest.mark.parametrize("first,second", [
    (r"$(-\infty,0)\times(0,1)$", r"$(-\infty,0)\cdot(0,1)$"),
    (r"$a*b$", r"$a\times b$"),
    (r"$\text{1 . 2}$", r"$\text{1.2}$"),
    (r"$\text{a!=b}$", r"$\text{a≠b}$"),
    ("$1% note\n+2$", "$1% note+2$"),
    (r"$\unknown{a b}$", r"$\unknown{ab}$"),
    ("$K$", "$K$"),
    ("$Ω$", "$Ω$"),
    ("temperature K", "temperature K"),
    ("resistance Ω", "resistance Ω"),
    ("rate 1 . 2", "rate 1.2"),
    ("not - equal", "not-equal"),
    ("$а$", "$a$"),
    ("$x₂$", "$x2$"),
])
def test_public_option_formulas_never_rewrite_untyped_semantics(first, second):
    candidate = public_candidate()
    choices(candidate)["options"][0]["text"] = first
    changed = deepcopy(candidate)
    changed["public_content"]["scopes"][0]["choices"][0]["options"][0]["text"] = second
    assert identity(candidate)["fingerprint"] != identity(changed)["fingerprint"]


@pytest.mark.parametrize("formula", [r"$\quad$", r"$\qquad$", r"$\left\right$"])
def test_formatting_only_formula_is_not_a_complete_option(formula):
    candidate = public_candidate()
    choices(candidate)["options"][0]["text"] = formula
    with pytest.raises(IdentityUnavailable, match="identity.empty_formula"):
        identity(candidate)


def test_unclassified_top_labels_are_content_not_discarded_source():
    candidate = public_candidate()
    candidate["root"]["label"] = "甲方案"
    first = identity(candidate)
    candidate["root"]["label"] = "乙方案"
    assert identity(candidate)["fingerprint"] != first["fingerprint"]
    assert first["identity"]["root"]["label"] == "甲方案"
    assert first["statement"].startswith("甲方案")
    candidate["public_content"]["root_label_role"] = "content"
    assert identity(candidate)["identity"]["root"]["label"] == "乙方案"
    candidate["root"].pop("label")
    with pytest.raises(IdentityUnavailable, match="identity.invalid_public_structure"):
        identity(candidate)


def test_new_concept_audit_prose_is_not_scalar_operator_notation():
    candidate = public_candidate()
    candidate["root"]["definitions"] = ["定义：称 a×b 为组合记号。"]
    first = identity(candidate)
    candidate["root"]["definitions"] = ["定义：称 a*b 为组合记号。"]
    assert identity(candidate)["fingerprint"] != first["fingerprint"]


@pytest.mark.parametrize("first,second", [("K", "K"), ("Ω", "Ω")])
def test_compiler_unicode_aliases_do_not_rename_identity_variables(first, second):
    candidate = public_candidate()
    candidate["root"]["facts"] = [text.replace("a", first) for text in candidate["root"]["facts"]]
    candidate["root"]["goals"][0]["symbol"] = first
    changed = deepcopy(candidate)
    changed["root"]["facts"] = [text.replace(first, second) for text in changed["root"]["facts"]]
    changed["root"]["goals"][0]["symbol"] = second
    assert identity(candidate)["fingerprint"] != identity(changed)["fingerprint"]


def test_finite_sum_identity_retains_bounds_order_and_duplicate_occurrences():
    fixture = Path(__file__).parents[1] / 'solver/fixtures/function-evaluation/q29b-candidate.json'
    candidate = json.loads(fixture.read_text())
    baseline = identity(candidate)
    terms = baseline['identity']['root']['goals'][1]['terms']
    assert terms[0]['lower'] == 1 and terms[0]['upper'] == 101
    for mutate in (
        lambda rows: rows[0].update(upper=100),
        lambda rows: rows.append(deepcopy(rows[0])),
        lambda rows: rows.reverse(),
        lambda rows: rows[0].update(expression='f(n+1)'),
    ):
        changed = deepcopy(candidate)
        mutate(changed['root']['goals'][1]['terms'])
        assert identity(changed)['fingerprint'] != baseline['fingerprint']
    spaced = deepcopy(candidate)
    spaced['root']['goals'][1]['terms'][0]['expression'] = ' f( n ) '
    assert identity(spaced)['fingerprint'] == baseline['fingerprint']
