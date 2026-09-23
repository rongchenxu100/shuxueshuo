"""Stage 2 syntax tests: no proof, dispatch, fixture mutation or LLM calls."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.math_kernel.expression_parser import (
    MathParseError,
    parse_math_expression,
    parse_math_relation,
    parse_math_steps,
)
from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    RewriteError,
    parse_expression,
    parse_relation,
    verify_chain,
)

SYMBOLS = {
    name: sp.Symbol(name, real=True)
    for name in ("a", "b", "c", "d", "s", "x", "y", "u", "v", "T", "xy", "α")
}
FIXTURES = Path(__file__).parent / "fixtures/basic-inequality-problem-ir/v1"
CASES = ("q01", "q03", "q07", "q08", "q12", "q17", "q20", "q25", "q30", "q31")


def shape(node):
    if node.op in {"integer", "symbol", "binding"}:
        return (node.op, node.text)
    return (node.op, *(shape(child) for child in node.children))


def steps(*sources, symbols=SYMBOLS):
    return parse_math_steps([{"math": text} for text in sources], symbols)


@pytest.mark.parametrize(
    "source",
    [
        "a+b≥2√(a*b)",
        "3x+4y≥2√(12x*y)",
        "u=x²",
        "T=√(x*y+4/(x*y))",
    ],
)
def test_acceptance_relations(source):
    parsed = parse_math_relation(source, SYMBOLS)
    assert parsed.to_sympy(SYMBOLS).rel_op == {"=": "=="}.get(
        parsed.ast.op, parsed.ast.op
    )
    assert parsed.source == source
    assert not hasattr(parsed, "proof")


@pytest.mark.parametrize(
    ("source", "equivalent"),
    [
        ("3x+2√(a*b)", "3*x+2*sqrt(a*b)"),
        ("√u+√2", "sqrt(u)+sqrt(2)"),
        ("√2*x", "sqrt(2)*x"),
        ("√x^2", "sqrt(x)^2"),
        ("-x^2", "-(x^2)"),
        ("(-x)^2", "(-x)^2"),
        ("x⁻²", "x^(-2)"),
        ("x¹²", "x**12"),
        ("3（x−y）÷2", "3*(x-y)/2"),
        (r"\frac{x+1}{2*\sqrt{y}}", "(x+1)/(2*sqrt(y))"),
        ("2/3*x", "(2/3)*x"),
        ("x/2/3", "(x/2)/3"),
        ("α²", "α^2"),
    ],
)
def test_scalar_syntax_equivalence(source, equivalent):
    parsed = parse_math_expression(source, SYMBOLS)
    reference = parse_math_expression(equivalent, SYMBOLS)
    assert shape(parsed.ast) == shape(reference.ast)
    assert parsed.to_sympy(SYMBOLS) == reference.to_sympy(SYMBOLS)
    replayed = parse_math_expression(parsed.normalized_source, SYMBOLS)
    assert shape(replayed.ast) == shape(parsed.ast)


@pytest.mark.parametrize(
    ("source", "operator"),
    [
        ("x≥y", ">="),
        ("x≤y", "<="),
        ("x≠y", "!="),
        ("x=y", "="),
        ("x>y", ">"),
        ("x<y", "<"),
        ("x>=y", ">="),
        ("x<=y", "<="),
        ("x!=y", "!="),
    ],
)
def test_relation_direction(source, operator):
    parsed = parse_math_relation(source, SYMBOLS)
    assert parsed.ast.op == operator
    assert [n.text for n in parsed.ast.children] == ["x", "y"]
    relation = parsed.to_sympy(SYMBOLS)
    assert relation.lhs is SYMBOLS["x"]
    assert relation.rhs is SYMBOLS["y"]
    assert not isinstance(parse_math_relation("x=x", SYMBOLS).to_sympy(SYMBOLS), bool)


def test_xy_is_one_symbol_and_never_split():
    assert parse_math_expression("xy", SYMBOLS).to_sympy(SYMBOLS) is SYMBOLS["xy"]
    assert parse_math_expression("x*y", SYMBOLS).to_sympy(SYMBOLS) != SYMBOLS["xy"]
    with pytest.raises(MathParseError, match="unknown_symbol"):
        parse_math_expression("xy", {k: SYMBOLS[k] for k in ("x", "y")})


@pytest.mark.parametrize(
    "source", [" 3x + y² ≥ 2√(x*y) ", r"\frac{x}{y} <= \sqrt{x}", "（x−y）≠0"]
)
def test_all_nodes_and_normalized_characters_point_into_original_source(source):
    parsed = parse_math_relation(source, SYMBOLS)
    for root in (parsed.tree, parsed.ast):
        nodes = list(root.walk())
        assert len({n.path for n in nodes}) == len(nodes)
        for node in nodes:
            a, b = node.span
            assert 0 <= a < b <= len(source)
            assert source[a:b].strip()
            if node.operator_span:
                a, b = node.operator_span
                assert node.span[0] <= a <= b <= node.span[1]
    assert len(parsed.source_map) == len(parsed.normalized_source)
    assert all(0 <= a <= b <= len(source) for a, b in parsed.source_map)
    assert parsed.source_map == parse_math_relation(source, SYMBOLS).source_map
    assert shape(parse_math_relation(parsed.normalized_source, SYMBOLS).ast) == shape(
        parsed.ast
    )


def test_exact_unicode_and_synthetic_spans():
    parsed = parse_math_relation(" 3x ≥ y²", SYMBOLS)
    relation = parsed.tree
    assert relation.operator_span == (4, 5)
    mul = relation.children[0]
    assert mul.synthetic and mul.operator_span == (2, 2)
    power = relation.children[1]
    assert power.operator_span == (7, 8)
    assert parsed.source[power.children[1].span[0] : power.children[1].span[1]] == "²"


def test_display_is_immutable_and_preserves_order_and_grouping():
    parsed = parse_math_expression("3*a+(a+b)", SYMBOLS)
    assert parsed.tree.children[1].op == "group"
    original = shape(parsed.tree)
    assert str(parsed.to_sympy(SYMBOLS)) == "4*a + b"
    assert shape(parsed.tree) == original
    assert parsed.ast.children[1].op == "add"
    with pytest.raises(FrozenInstanceError):
        parsed.tree.op = "sub"


@pytest.mark.parametrize("source", ["u:=x²", "u≔x²"])
def test_definition_is_pending_and_does_not_change_visibility(source):
    symbols = {"x": SYMBOLS["x"]}
    (parsed,) = steps(source, symbols=symbols)
    assert parsed.ast.op == "definition"
    assert parsed.ast.children[0].op == "binding"
    assert set(symbols) == {"x"}
    with pytest.raises(MathParseError, match="not_single_value"):
        parsed.to_sympy(symbols)
    with pytest.raises(MathParseError, match="unknown_symbol") as failure:
        steps(source, "u+1", symbols=symbols)
    assert failure.value.step == 1
    assert failure.value.source_path == "/1/math"
    assert failure.value.span == (0, 1)
    assert steps("u=x²")[0].ast.op == "="


@pytest.mark.parametrize(
    ("source", "plus", "minus"),
    [
        ("x=±√u", "x=+sqrt(u)", "x=-sqrt(u)"),
        ("x=2±√3", "x=2+sqrt(3)", "x=2-sqrt(3)"),
        ("x=(s±√d)/2", "x=(s+sqrt(d))/2", "x=(s-sqrt(d))/2"),
        ("(x=±√u)", "x=+sqrt(u)", "x=-sqrt(u)"),
    ],
)
def test_branches_preserve_shared_origin_without_solving(source, plus, minus):
    (parsed,) = steps(source)
    assert parsed.ast.op == "branches"
    assert [n.branch_id for n in parsed.ast.children] == ["positive", "negative"]
    for branch, reference in zip(parsed.ast.children, (plus, minus), strict=True):
        assert shape(branch) == shape(parse_math_relation(reference, SYMBOLS).ast)
        signed = [
            n
            for n in branch.walk()
            if n.operator_span and source[slice(*n.operator_span)] == "±"
        ]
        assert len(signed) == 1
    assert [o.status for o in parsed.obligations] == ["unverified"] * len(
        parsed.obligations
    )
    with pytest.raises(MathParseError, match="not_single_value"):
        parsed.to_sympy(SYMBOLS)


def test_logic_pairs_only_associate_syntax():
    rows = steps("∵ x>0，y>0", "∴ x+y≥2√(x*y)", "x+y")
    assert [r.ast.op for r in rows] == ["premise", "conclusion", "add"]
    assert [r.related_step for r in rows] == [1, 0, None]
    assert len(rows[0].ast.children) == 2
    for row in rows[:2]:
        with pytest.raises(MathParseError, match="not_single_value"):
            row.to_sympy(SYMBOLS)
    # Mathematical falsehood is still syntax, never an automatically proved fact.
    assert steps("∵ x>0", "∴ x<0")[1].ast.op == "conclusion"


@pytest.mark.parametrize(
    "sources",
    [
        ("∵ x>0",),
        ("∴ x>0",),
        ("∵ x>0", "x+1"),
        ("∵ x>0", "∵ y>0"),
        ("∵ x>0", "∴ x>0,y>0"),
        ("∵ sqrt(x,y)>0", "∴ x>0"),
        ("∵ x+1", "∴ x>0"),
        ("u:=u+1",),
        ("2:=x",),
        ("sqrt:=x",),
        ("x=±√u±1",),
        ("±x=y",),
        ("x≥±√u",),
        ("x=∓√u",),
    ],
)
def test_invalid_steps(sources):
    symbols = (
        {k: v for k, v in SYMBOLS.items() if k != "u"}
        if sources == ("u:=u+1",)
        else SYMBOLS
    )
    with pytest.raises(MathParseError):
        steps(*sources, symbols=symbols)


def test_domain_obligations_survive_cancellation():
    parsed = parse_math_expression("x/x+x^-2+sqrt(y)", SYMBOLS)
    assert [(o.operator, o.expression.text, o.status) for o in parsed.obligations] == [
        ("!=", "x", "unverified"),
        ("!=", "x", "unverified"),
        (">=", "y", "unverified"),
    ]
    before = parsed.obligations
    assert parsed.to_sympy(SYMBOLS) == 1 + SYMBOLS["x"] ** -2 + sp.sqrt(SYMBOLS["y"])
    assert parsed.obligations == before
    for obligation in before:
        node = next(n for n in parsed.ast.walk() if n.path == obligation.node_path)
        assert obligation.span == node.span


@pytest.mark.parametrize("source", (
    "1/(2-2)", "1/(2+(-2))", "1/(2*2-4)",
    "sqrt(1-2)", "√(1+(-2))", "sqrt(-(1+2))", "(2-2)^(-1)",
    "1/(0^1)", "1/(2/2-1)", "1/(2^0-1)",
    "sqrt((-1)^1)", "sqrt(1^1-2)",
    "1/(1/3+1/6-1/2)", "sqrt(1/3-1/2)", "sqrt((-2)^(-1))",
    "(2/2-1)^(-1)", "1/(2^(-1)-1/2)", "1/sqrt(0)",
    "1/(sqrt(4/9)-2/3)", "sqrt(sqrt(1/4)-1)",
))
@pytest.mark.parametrize("entrypoint", ("expression", "relation", "steps"))
def test_undefined_integer_arithmetic_is_rejected_before_lowering(source, entrypoint):
    text = source if entrypoint == "expression" else f"x={source}"
    with pytest.raises(MathParseError) as failure:
        if entrypoint == "expression":
            parse_math_expression(text, SYMBOLS)
        elif entrypoint == "relation":
            parse_math_relation(text, SYMBOLS)
        else:
            steps("x", text)
    error = failure.value
    assert error.code == "undefined_expression"
    assert error.source == text
    assert text[slice(*error.span)]
    assert error.path.startswith("n")
    if entrypoint == "steps":
        assert error.step == 1
        assert error.source_path == "/1/math"


@pytest.mark.parametrize("source", (
    "x=1/(2±2)", "x=√(1±2)", "x=(2±2)^(-1)", "x=1/(2±(-2))",
    "x=1/(2^0±1)", "x=1/((2/2)±1)",
    "x=sqrt(1^1±2)", "x=sqrt((1/2)±1)", "x=(2/2±1)^(-1)",
))
def test_undefined_plus_minus_branch_rejects_whole_row(source):
    with pytest.raises(MathParseError) as failure:
        steps("x", source)
    error = failure.value
    assert error.code == "undefined_expression"
    assert error.step == 1 and error.source_path == "/1/math"
    assert error.source == source
    # The guard runs on expanded canonical branches and retains source offsets.
    branch = "n.0" if "(-2)" in source else "n.1"
    assert error.path.startswith(branch + ".")
    assert "±" in source[slice(*error.span)]


@pytest.mark.parametrize("source,expected", (
    ("1/(3-2)", sp.Integer(1)),
    ("sqrt(2-1)", sp.Integer(1)),
    ("sqrt(2-2)", sp.Integer(0)),
    ("(3-2)^(-1)", sp.Integer(1)),
    ("1/(2^1-1)", sp.Integer(1)),
    ("1/(3/2-1)", sp.Integer(2)),
    ("sqrt(2^1-1)", sp.Integer(1)),
    ("sqrt(3/2-1)", sp.sqrt(sp.Rational(1, 2))),
    ("1/(2^(-1)-1/3)", sp.Integer(6)),
    ("sqrt((-1)^2-1)", sp.Integer(0)),
    ("(3/2-1)^(-1)", sp.Integer(2)),
))
def test_defined_integer_arithmetic_keeps_source_tree(source, expected):
    parsed = parse_math_expression(source, SYMBOLS)
    assert parsed.to_sympy(SYMBOLS) == expected
    assert any(node.op == "sub" for node in parsed.ast.walk())
    assert parsed.source == source


def test_defined_plus_minus_branches_remain_available():
    for source in ("x=1/(3±2)", "x=√(3±2)", "x=1/(2^1±1)", "x=sqrt((3/2)±1)"):
        parsed, = steps(source)
        assert parsed.ast.op == "branches"
        assert [branch.branch_id for branch in parsed.ast.children] == ["positive", "negative"]
        assert len(parsed.obligations) >= 2


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').system('true')",
        "x.__class__",
        "x[0]",
        "lambda:x",
        "[x for x in y]",
        "sin(x)",
        "abs(x)",
        "min(x,y)",
        "sqrt()",
        "sqrt(x,y)",
        "sqrt(x=1)",
        "a<b<c",
        "a=b=c",
        "x(y+1)",
        "x y",
        "x²y",
        "x^2y",
        "x^-2y",
        "1.2*x",
        "x^0.5",
        "x^(1/2)",
        "x^13",
        "x^(2+1)",
        "(x^2)^2",
        "(9^12)^12",
        "(x+y)^12",
        "sqrt(-1)",
        "1/0",
        "0^-1",
        "x^1000000000000000",
        "1000000001",
        "√-1",
        r"\sin{x}",
        r"\frac{x}",
        "(x>y)+1",
        "x+(y>0)",
        "x∈ℝ",
        "x≡y",
        "x=±√u",
        "±x",
        "x:=y",
        "∵x>0",
    ],
)
def test_invalid_expression(source):
    with pytest.raises(MathParseError) as failure:
        parse_math_expression(source, SYMBOLS)
    assert failure.value.source == source
    assert failure.value.span is not None
    assert failure.value.path


@pytest.mark.parametrize(
    "source", ["a<b<c", "a=b=c", "(a<b)<c", "(a=b)=c", "x=±√u", "x:=y", "x+1"]
)
def test_single_relation_boundary(source):
    with pytest.raises(MathParseError):
        parse_math_relation(source, SYMBOLS)


def balanced_sum(count):
    if count == 1:
        return "x"
    return f"({balanced_sum(count // 2)}+{balanced_sum(count - count // 2)})"


def test_limits_checked_before_any_sympy_construction(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SymPy construction during parsing")

    monkeypatch.setattr(sp, "Integer", forbidden)
    monkeypatch.setattr(sp, "sqrt", forbidden)
    assert parse_math_expression("sqrt(x)+2", SYMBOLS).ast.op == "add"
    assert parse_math_expression("sqrt(1/2)+2^(-1)", SYMBOLS).ast.op == "add"
    for source in ("1/(2^0-1)", "1/(1/3+1/6-1/2)", "sqrt((-1)^1)"):
        with pytest.raises(MathParseError, match="undefined_expression"):
            parse_math_expression(source, SYMBOLS)
    with pytest.raises(MathParseError, match="undefined_expression"):
        steps("x=1/((2/2)±1)")
    for source in (
        "x" * 1025,
        "(" * 40 + "x" + ")" * 40,
        "+".join(["x"] * 150),
        "(x+y)^12",
        "x^999999999",
    ):
        with pytest.raises(MathParseError):
            parse_math_expression(source, SYMBOLS)
    # Individually small sides still count against the duplicated branch budget.
    with pytest.raises(MathParseError, match="expression_too_large"):
        steps("x=" + balanced_sum(64) + "±1")


@pytest.mark.parametrize(
    "source", ["sqrt(x)", "√x", "x²", "3x", r"\frac{x}{y}", "x:=y", "x=±√u", "∵x>0"]
)
def test_legacy_parser_and_m01_do_not_enable_new_syntax(source):
    with pytest.raises(RewriteError):
        parse_expression(source, SYMBOLS)
    with pytest.raises(RewriteError):
        verify_chain(SYMBOLS["x"], [], [{"math": "x"}, {"math": source}], SYMBOLS)


def test_legacy_relation_and_tree_contracts():
    assert parse_relation("x<=y", SYMBOLS).rel_op == "<="
    for source in ("x≥y", "x=sqrt(y)", "x:=y", "x=±y", "x=y=z"):
        with pytest.raises(RewriteError):
            parse_relation(source, SYMBOLS)
    parsed = parse_expression("3*a+(a+b)", SYMBOLS)
    assert parsed.tree["id"] == "n"
    assert parsed.tree["children"][1]["id"] == "n.1"
    assert parsed.tree["children"][1]["op"] == "add"
    with pytest.raises(RewriteError) as failure:
        parse_expression("x+z", SYMBOLS)
    assert failure.value.span == (2, 3)


@pytest.mark.parametrize("parse,source", (
    (parse_math_expression, "x+z"),
    (parse_expression, "x+z"),
    (parse_relation, "x=z"),
))
def test_parser_error_bridge_keeps_plain_message_and_location(parse, source):
    with pytest.raises((MathParseError, RewriteError)) as failure:
        parse(source, SYMBOLS)
    error = failure.value
    assert error.code == "unknown_symbol"
    assert error.message == "未知标量 z"
    assert str(error) == "unknown_symbol: 未知标量 z"
    assert error.source == source and error.span == (2, 3)
    assert error.path


@pytest.mark.parametrize("row", (0, 1))
def test_verify_chain_adds_row_without_rewrapping_formatted_error(row):
    chain = [{"math": "x"}] * row + [{"math": "x+z"}]
    with pytest.raises(RewriteError) as failure:
        verify_chain(SYMBOLS["x"], [], chain, SYMBOLS)
    error = failure.value
    assert error.code == "unknown_symbol" and error.row == row
    assert error.message == "未知标量 z"
    assert str(error) == f"unknown_symbol at steps[{row}]: 未知标量 z"
    assert error.source == "x+z" and error.span == (2, 3)
    assert error.path
    assert isinstance(error.__cause__, RewriteError)
    assert isinstance(error.__cause__.__cause__, MathParseError)


def test_verify_chain_own_errors_also_keep_plain_message():
    with pytest.raises(RewriteError) as failure:
        verify_chain(SYMBOLS["x"], [], [{"math": "x+1"}], SYMBOLS)
    error = failure.value
    assert error.code == "input_mismatch" and error.row == 0
    assert str(error) == f"input_mismatch at steps[0]: {error.message}"
    assert str(error).count("input_mismatch") == 1


@pytest.mark.parametrize("source", (
    "1/(2-2)", "(2-2)^(-1)", "1/(0^1)", "1/(2/2-1)",
    "1/(2^0-1)", "1/(1/3+1/6-1/2)", "(2/2-1)^(-1)",
))
def test_legacy_bridge_rejects_undefined_integer_arithmetic(source):
    for parse, text in ((parse_expression, source), (parse_relation, f"x={source}")):
        with pytest.raises(RewriteError) as failure:
            parse(text, SYMBOLS)
        assert failure.value.code == "undefined_expression"
        assert str(failure.value).count("undefined_expression") == 1
    with pytest.raises(RewriteError) as failure:
        verify_chain(SYMBOLS["x"], [], [{"math": "x"}, {"math": source}], SYMBOLS)
    assert failure.value.row == 1
    assert str(failure.value) == f"undefined_expression at steps[1]: {failure.value.message}"


def notation_shape(ast, names):
    if ast[0] == "ref":
        return ("symbol", names[ast[1]])
    if ast[0] == "number":
        return ("integer", ast[1])
    if ast[:2] == ["call", "sqrt"]:
        return ("sqrt", notation_shape(ast[2], names))
    op = {"+": "add", "-": "sub", "*": "mul", "/": "div", "^": "pow"}.get(
        ast[0], ast[0]
    )
    return (op, *(notation_shape(c, names) for c in ast[1:]))


@pytest.mark.parametrize("case", CASES)
def test_ten_frozen_inputs_match_bound_notation_without_rewriting(case):
    data = json.loads((FIXTURES / case / "problem-ir.json").read_text())["input"]
    names = {e["notation_ref"]: e["name"] for e in data["entities"]}
    symbols = {n: sp.Symbol(n, real=True) for n in names.values()}
    count = 0
    for row in data["facts"] + data["question_goals"]:
        bound = row["bound_expression"]
        if bound[0] in {"default_domain", "∈"}:
            continue
        parse = (
            parse_math_relation
            if bound[0] in {"=", "!=", ">", "<", ">=", "<="}
            else parse_math_expression
        )
        parsed = parse(row["normalized_expression"], symbols)
        assert shape(parsed.ast) == notation_shape(bound, names)
        count += 1
    assert count >= 2


def test_legacy_preserves_computational_power_limit_and_denominator_order():
    with pytest.raises(RewriteError, match="expression_too_large"):
        parse_expression("(1/x)^2", SYMBOLS)
    assert parse_expression("(x/2)^2", SYMBOLS).value == SYMBOLS["x"] ** 2 / 4
    parsed = parse_expression("1/(x/y)", SYMBOLS)
    assert parsed.denominators == (SYMBOLS["y"], SYMBOLS["x"] / SYMBOLS["y"])


def test_definition_and_branch_normalized_forms_replay():
    for source in ("u≔x²", "x=2±√3"):
        (parsed,) = steps(source)
        (replayed,) = steps(parsed.normalized_source)
        assert shape(parsed.ast) == shape(replayed.ast)


@pytest.mark.parametrize(
    "rows",
    [[], [{"math": "x"}] * 13, [{"math": "x", "using": []}], ["x"], [{"math": None}]],
)
def test_step_envelope_has_structured_errors(rows):
    with pytest.raises(MathParseError):
        parse_math_steps(rows, SYMBOLS)


def test_syntax_types_and_symbol_identity():
    with pytest.raises(MathParseError, match="unknown_symbol"):
        parse_math_expression("x", {"x": sp.Integer(1)})
    x = sp.Dummy("x", real=True)
    parsed = parse_math_expression("x", {"x": x})
    assert parsed.to_sympy({"x": x}) is x
    with pytest.raises(MathParseError, match="unknown_symbol"):
        parsed.to_sympy({})
