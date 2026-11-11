"""Independent authored expectations plus structural counterexamples."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import (
    FEATURE_REGISTRY,
    extract_features,
    registry,
)
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_semantics import (
    Canonical,
    bounded_expand,
)

FIXTURES = Path(__file__).parent / "fixtures/graph-guided-stage-one/quadratic-always"
REPO = Path(__file__).resolve().parents[3]
FUNCTION_GOAL_FEATURES = {'parity_extension', 'symmetry_evaluation', 'parity_parameter', 'function_parity', 'abstract_monotonicity', 'monotonicity_parameter',
                          'monotonicity_inequality', 'function_extremum',
                          'function_monotonicity', 'function_domain', 'function_comparison', 'abstract_function_domain',
                          'function_evaluation', 'function_range', 'abstract_function_range',
                          'translation_range', 'function_formula', 'function_graph',
                          'piecewise_modeling', 'piecewise_range_parameter',
                          'piecewise_equation', 'piecewise_inequality'}


def goal_features(candidate):
    result = extract_features(candidate)
    assert result["ok"], result
    return {(item["target_ref"], item["feature_id"]): item for item in result["features"]}


def feature_values(candidate):
    return {
        feature_id: item
        for (target_ref, feature_id), item in goal_features(candidate).items()
        if target_ref == "/root/goals/0"
    }


def _same_math(expected, actual):
    if expected.replace(" ", "") == actual.replace(" ", ""):
        return True
    report = NotationValidator().validate_root({"facts": [f"({expected})=({actual})"]})
    if not report.ok:
        return False
    lhs, rhs = report.semantic["facts"][0][1:]
    algebra = Canonical()
    return bounded_expand(algebra.expr(lhs) - algebra.expr(rhs)) == 0


def assert_subset(expected, actual, key=""):
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        for name, value in expected.items():
            assert name in actual
            assert_subset(value, actual[name], name)
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(expected) == len(actual)
        for left, right in zip(expected, actual, strict=True):
            assert_subset(left, right, key)
    elif (
        isinstance(expected, str)
        and isinstance(actual, str)
        and key in ("expression", "lhs", "rhs", "lower", "upper")
    ):
        assert _same_math(expected, actual), (expected, actual)
    else:
        assert expected == actual, (key, expected, actual)


@pytest.mark.parametrize("case_id", [f"q{number:02}" for number in range(1, 10)])
def test_authored_nine_problem_feature_expectations(case_id):
    candidate = json.loads((FIXTURES / case_id / "notation.gold.json").read_text())
    frozen = deepcopy(candidate)
    actual = goal_features(candidate)
    expected = json.loads((FIXTURES / case_id / "features.gold.json").read_text())
    for feature in expected["features"]:
        assert_subset(feature, actual[feature["target_ref"], feature["feature_id"]])
    assert candidate == frozen
    for item in actual.values():
        assert item["source_refs"]
        for path in item["source_refs"]:
            assert path.startswith("/root/")
        assert item["target_ref"] == "/root/goals/0"
        assert item["scope"] == "/root"
        assert item["knowledge_refs"]


def test_registry_dependencies_and_public_knowledge_references_exist():
    entries = registry()["features"]
    assert len({entry["feature_id"] for entry in entries}) == len(entries)
    assert registry()["categories"] == ["structural", "method_precondition"]
    ids = {entry["feature_id"] for entry in entries}
    for entry in FEATURE_REGISTRY:
        assert entry.category == "structural"
        assert set(entry.dependencies) <= ids
        assert entry.feature_id not in entry.dependencies
        for reference in entry.knowledge_refs:
            node_id, entry_id = reference.split("#")
            node = json.loads(
                (
                    REPO / "site/data/knowledge-next/nodes" / f"{node_id}.json"
                ).read_text()
            )
            assert entry_id in {item["id"] for item in node["entries"]}


@pytest.mark.parametrize("bound,goal", [("t", "p"), ("z", "b"), ("m", "x")])
def test_variable_roles_follow_bindings_not_letters(bound, goal):
    candidate = {
        "root": {
            "facts": [f"∀{bound}∈[1,3]:{bound}*({goal}^2-{goal}+1)-6<0"],
            "goals": [{"kind": "find_range", "symbol": goal}],
        }
    }
    features = feature_values(candidate)
    assert features["bound_vars"]["value"] == [bound]
    assert features["free_vars"]["value"] == [goal]
    assert features["degree_in_bound"]["value"]["degree"] == 1
    assert features["degree_in_goal"]["value"]["degree"] == 2
    assert features["range_var_is_principal"]["value"] is False


@pytest.mark.parametrize(
    "kind,relation,coefficient",
    [
        ("find_minimum", "x^2+a*x+1>=0", "a"),
        ("find_maximum", "x^2-a*x+1>=0", "-a"),
    ],
)
def test_scalar_parameter_extrema_keep_goal_kind_and_quantified_structure(
    kind, relation, coefficient
):
    candidate = {
        "root": {
            "facts": [f"∀x∈(0,1/2]:{relation}"],
            "goals": [{"kind": kind, "expression": "a"}],
        }
    }
    frozen = deepcopy(candidate)
    features = feature_values(candidate)
    assert candidate == frozen
    assert all(item["status"] == "known" for key, item in features.items()
                   if key not in FUNCTION_GOAL_FEATURES)
    assert features["function_domain"]["status"] == "unknown"
    assert features["function_comparison"]["status"] == "unknown"
    assert features["goal"]["value"] == {"kind": kind, "symbol": "a"}
    assert features["goal"]["source_refs"] == ["/root/goals/0"]
    assert features["quantifier"]["value"] == "∀"
    assert features["bound_vars"]["value"] == ["x"]
    assert features["free_vars"]["value"] == ["a"]
    assert features["domain"]["value"] == {
        "expression": "(0,1/2]",
        "lower": "0",
        "upper": "1/2",
        "left_closed": False,
        "right_closed": True,
        "bounded": True,
    }
    assert features["domain_kind"]["value"] == "bounded_interval"
    assert features["relation"]["value"]["operator"] == ">="
    assert features["normal_form"]["value"]["operator"] == ">="
    assert features["degree_in_bound"]["value"]["degree"] == 2
    assert features["degree_in_goal"]["value"]["degree"] == 1
    assert features["leading_coeff_in_bound"]["value"]["expression"] == "1"
    assert features["coefficients"]["value"]["items"] == [
        {"power": 2, "expression": "1", "contains_parameters": False},
        {"power": 1, "expression": coefficient, "contains_parameters": True},
        {"power": 0, "expression": "1", "contains_parameters": False},
    ]
    assert features["range_var_is_principal"]["value"] is True


@pytest.mark.parametrize("kind", ["find_minimum", "find_maximum"])
def test_composite_extremum_is_not_rewritten_as_a_single_parameter_goal(kind):
    features = feature_values(
        {
            "root": {
                "facts": ["∀x∈(0,1/2]:x^2+a*x+b>=0"],
                "goals": [{"kind": kind, "expression": "a+b"}],
            }
        }
    )
    assert features["goal"]["status"] == "unknown"
    assert features["goal"]["value"] is None
    assert features["goal"]["diagnostics"][0]["code"] == "feature.unsupported_goal"
    assert features["degree_in_goal"]["status"] == "unknown"


def test_extremum_sub_questions_keep_goals_and_quantifiers_in_their_own_scope():
    features = goal_features(
        {
            "root": {
                "facts": ["a∈ℝ", "b∈ℝ"],
                "children": [
                    {
                        "facts": ["∀x∈(0,1/2]:x^2+a*x+1>=0"],
                        "goals": [{"kind": "find_minimum", "expression": "a"}],
                    },
                    {
                        "facts": ["∀t∈[1,2):t^2-b*t+1>=0"],
                        "goals": [{"kind": "find_maximum", "expression": "b"}],
                    },
                ],
            }
        }
    )
    for index, kind, parameter, bound, domain in (
        (0, "find_minimum", "a", "x", "(0,1/2]"),
        (1, "find_maximum", "b", "t", "[1,2)"),
    ):
        scope = f"/root/children/{index}"
        target = f"{scope}/goals/0"
        assert features[target, "goal"]["value"] == {"kind": kind, "symbol": parameter}
        assert features[target, "bound_vars"]["value"] == [bound]
        assert features[target, "free_vars"]["value"] == [parameter]
        assert features[target, "domain"]["value"]["expression"] == domain
        for (target_ref, feature_id), feature in features.items():
            if target_ref == target:
                assert feature["status"] == ("unknown" if feature_id in FUNCTION_GOAL_FEATURES else "known")
                assert feature["scope"] == scope
                assert feature["source_refs"]
                assert all(ref.startswith(scope + "/") for ref in feature["source_refs"])


def test_parameter_leading_coefficient_is_not_assumed_nonzero():
    features = feature_values(
        {
            "root": {
                "facts": ["∀t∈ℝ:(p^2-1)*t^2+(p-1)*t<0"],
                "goals": [{"kind": "find_range", "symbol": "p"}],
            }
        }
    )
    assert features["degree_in_bound"]["value"]["degree_kind"] == "upper_bound"
    assert features["leading_coeff_in_bound"]["value"]["may_be_zero"] is True
    assert features["leading_coeff_in_bound"]["value"]["contains_parameters"] is True
    assert not any(
        item in features
        for item in ("divisor_sign", "degenerate_branches", "param_separable")
    )
    assert features["degree_in_bound"]["conditions"] == []


def test_zero_polynomial_is_distinct_from_constant_polynomial():
    values = feature_values(
        {
            "root": {
                "facts": ["∀t∈ℝ:t^2-t^2>=0"],
                "goals": [{"kind": "find_range", "symbol": "a"}],
            }
        }
    )
    assert values["degree_in_bound"]["value"]["degree"] is None
    assert values["degree_in_bound"]["value"]["degree_kind"] == "zero_polynomial"
    assert values["leading_coeff_in_bound"]["value"]["expression"] == "0"
    assert values["range_var_is_principal"]["status"] == "unknown"


def test_cancellation_keeps_denominator_obligation():
    values = feature_values(
        {
            "root": {
                "facts": ["∀t∈ℝ:(p*t^2)/p+1>0"],
                "goals": [{"kind": "find_range", "symbol": "p"}],
            }
        }
    )
    assert values["degree_in_bound"]["value"]["degree"] == 2
    assert values["normal_form"]["status"] == "conditional"
    assert values["normal_form"]["conditions"] == [
        {"expression": "p", "operator": "!=", "rhs": "0", "origin": "well_definedness"}
    ]


def test_nonpolynomial_and_unexpanded_definitions_are_unknown():
    candidate = {
        "root": {
            "facts": ["∀t∈ℝ:1/t+p>0"],
            "goals": [{"kind": "find_range", "symbol": "p"}],
        }
    }
    features = feature_values(candidate)
    assert features["degree_in_bound"]["status"] == "unknown"
    assert (
        features["degree_in_bound"]["diagnostics"][0]["code"]
        == "feature.not_polynomial"
    )
    unexpanded = {
        "root": {
            "definitions": ["y=m*x^2-m*x-6+m"],
            "facts": ["∀m∈[1,3]:y<0"],
            "goals": [{"kind": "find_range", "symbol": "x"}],
        }
    }
    features = feature_values(unexpanded)
    assert features["normal_form"]["status"] == "unknown"
    assert (
        features["normal_form"]["diagnostics"][0]["code"]
        == "feature.bound_variable_absent"
    )


def test_equivalent_relation_normalizes_without_losing_strictness():
    goal = [{"kind": "find_range", "symbol": "a"}]
    first = feature_values(
        {"root": {"facts": ["∀x∈ℝ:-(x-1)^2+4<a^2-3*a"], "goals": goal}}
    )
    second = feature_values(
        {"root": {"facts": ["∀x∈ℝ:x^2-2*x+a^2-3*a-3>0"], "goals": goal}}
    )
    assert first["normal_form"]["value"] == second["normal_form"]["value"]
    assert first["normal_form"]["value"]["operator"] == ">"


def test_invalid_root_or_child_scope_never_yields_successful_features():
    assert not extract_features({"root": {"facts": ["__import__('os')"]}})["ok"]
    child = extract_features({"root": {"children": [{"facts": ["__import__('os')"]}]}})
    assert not child["ok"]
    no_goal = extract_features({"root": {"children": [{"facts": ["a>0"]}]}})
    assert not no_goal["ok"]
    assert no_goal["diagnostics"][0]["code"] == "feature.goal_required"


SUB_QUESTIONS = {
    "definitions": ["f(x)=m*x^2-m*x-1"],
    "children": [
        {
            "label": "（1）",
            "facts": ["m=1", "f(x)<0"],
            "goals": [{"kind": "find_range", "symbol": "x"}],
        },
        {
            "label": "（2）",
            "facts": ["∀x∈[1,3]: f(x)<-m+5"],
            "goals": [{"kind": "find_range", "symbol": "m"}],
        },
    ],
}


def test_sub_questions_see_ancestors_but_not_siblings():
    features = goal_features({"root": SUB_QUESTIONS})
    first, second = "/root/children/0/goals/0", "/root/children/1/goals/0"
    assert features[first, "goal"]["value"] == {"kind": "find_range", "symbol": "x"}
    assert features[first, "quantifier"]["status"] == "unknown"
    assert features[first, "quantifier"]["diagnostics"][0]["count"] == 0
    assert features[second, "quantifier"]["value"] == "∀"
    assert features[second, "quantifier"]["scope"] == "/root/children/1"
    assert features[second, "free_vars"]["value"] == ["m"]
    # m=1 belongs to the first sub-question only.
    assert features[second, "leading_coeff_in_bound"]["value"]["expression"] == "-m"
    assert features[second, "degree_in_goal"]["value"]["degree"] == 1


def test_function_definitions_are_inlined_with_their_source():
    relation = goal_features({"root": SUB_QUESTIONS})[
        "/root/children/1/goals/0", "relation"
    ]
    assert relation["source_refs"] == ["/root/children/1/facts/0", "/root/definitions/0"]
    assert relation["calculation"]["inlined_functions"] == ["f"]
    assert _same_math(relation["value"]["lhs"], "m*x^2-m*x-1")


def test_equal_bound_facts_in_siblings_keep_their_own_names_and_sources():
    goal = [{"kind": "find_range", "symbol": "a"}]
    features = goal_features(
        {
            "root": {
                "facts": ["a∈ℝ"],
                "children": [
                    {"facts": ["∀x∈ℝ:x^2+a>0"], "goals": goal},
                    {"facts": ["∀t∈ℝ:t^2+a>0"], "goals": goal},
                ],
            }
        }
    )
    for index, name in ((0, "x"), (1, "t")):
        row = features[f"/root/children/{index}/goals/0", "bound_vars"]
        assert row["value"] == [name]
        assert row["source_refs"] == [f"/root/children/{index}/facts/0"]


def test_outer_variable_sharing_the_bound_name_is_unknown_not_merged():
    features = goal_features(
        {
            "root": {
                "definitions": ["f(t)=x*t^2+a"],
                "children": [
                    {
                        "facts": ["∀x∈ℝ:f(x)>0"],
                        "goals": [{"kind": "find_range", "symbol": "a"}],
                    }
                ],
            }
        }
    )
    degree = features["/root/children/0/goals/0", "degree_in_bound"]
    assert degree["status"] == "unknown"
    assert degree["diagnostics"][0]["code"] == "feature.ambiguous_variable_name"


def test_unused_function_argument_keeps_its_domain_condition():
    values = feature_values(
        {
            "root": {
                "definitions": ["f(t)=1"],
                "facts": ["∀x∈ℝ:f(1/x)+x^2+a>0"],
                "goals": [{"kind": "find_range", "symbol": "a"}],
            }
        }
    )
    condition = {"expression": "x", "operator": "!=", "rhs": "0", "origin": "well_definedness"}
    assert values["domain"]["status"] == "known"
    for feature_id in ("relation", "normal_form", "degree_in_bound"):
        assert values[feature_id]["status"] == "conditional"
        assert values[feature_id]["conditions"] == [condition]


def test_function_call_in_domain_checks_its_argument_before_the_domain():
    goal = [{"kind": "find_range", "symbol": "b"}]
    values = feature_values(
        {"root": {"definitions": ["f(t)=1"], "facts": ["∀x∈(f(1/a),2):x^2+b>0"], "goals": goal}}
    )
    condition = {"expression": "a", "operator": "!=", "rhs": "0", "origin": "well_definedness"}
    assert values["domain"]["status"] == "conditional"
    assert values["domain"]["conditions"] == [condition]
    assert values["domain"]["value"]["expression"] == "(1,2)"
    assert values["free_vars"]["value"] == ["a", "b"]
    undefined = feature_values(
        {"root": {"definitions": ["f(t)=1"], "facts": ["∀x∈(f(1/0),2):x^2+b>0"], "goals": goal}}
    )
    for feature_id in ("domain", "relation", "normal_form"):
        assert undefined[feature_id]["status"] == "unknown"


def test_nonreal_domain_makes_structural_features_unknown():
    values = feature_values(
        {
            "root": {
                "definitions": ["f(t)=1"],
                "facts": ["∀x∈(f(sqrt(-1)),2):x^2+b>0"],
                "goals": [{"kind": "find_range", "symbol": "b"}],
            }
        }
    )
    for feature_id in ("domain", "relation", "normal_form", "degree_in_bound"):
        assert values[feature_id]["status"] == "unknown"
        assert values[feature_id]["diagnostics"][0]["code"] == "algebra.nonreal"


def test_conditions_inherited_from_the_domain_carry_its_evidence():
    values = feature_values(
        {
            "root": {
                "definitions": ["f(t)=1/t"],
                "facts": ["∀x∈(0,f(a)):x^2+b>0"],
                "goals": [{"kind": "find_range", "symbol": "b"}],
            }
        }
    )
    for feature_id in ("relation", "normal_form", "degree_in_bound"):
        assert values[feature_id]["conditions"][0]["expression"] == "a"
        assert "/root/definitions/0" in values[feature_id]["source_refs"]
        assert "domain" in values[feature_id]["dependencies"]


def test_expanded_domain_cites_the_function_definition():
    features = goal_features(
        {
            "root": {
                "definitions": ["f(t)=t^2+c"],
                "children": [
                    {
                        "facts": ["∀x∈(0,f(a)):x^2+b>0"],
                        "goals": [{"kind": "find_range", "symbol": "b"}],
                    }
                ],
            }
        }
    )
    target = "/root/children/0/goals/0"
    domain = features[target, "domain"]
    assert domain["value"]["upper"] == "a^2 + c"
    assert "/root/definitions/0" in domain["source_refs"]
    assert domain["calculation"]["inlined_functions"] == ["f"]
    assert "/root/definitions/0" in features[target, "free_vars"]["source_refs"]
    assert "/root/definitions/0" not in features[target, "relation"]["source_refs"]


def test_identical_sibling_facts_keep_their_own_source_pointer():
    part = {
        "facts": ["∀x∈ℝ: x^2+a>0"],
        "goals": [{"kind": "find_range", "symbol": "a"}],
    }
    features = goal_features({"root": {"children": [part, deepcopy(part)]}})
    for index in (0, 1):
        assert features[f"/root/children/{index}/goals/0", "quantifier"][
            "source_refs"
        ] == [f"/root/children/{index}/facts/0"]
