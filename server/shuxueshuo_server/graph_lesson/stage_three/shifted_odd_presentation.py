"""Source formulas, opposite inputs and restored function values; no invented curve."""

import sympy as sp

from ..shifted_odd_math import name, parse_sources, solve
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .symmetry_presentation import _source_latex
from .symmetry_relation_presentation import _pair_lines, _read, target_math


def source_math(d):
    """Render the original conditions for reading, without solving or cancelling."""
    source = []
    for row in d["given_entries"]:
        a = row["ast"]
        if a[0] == "function_definition":
            source.append(name(a[1][1]) + "(x)=" + _source_latex(a[2], "x"))
        elif a[0] == "function_parity":
            source.append(name(a[1][1]) + r"\text{ 是奇函数}")
        elif a[0] == "default_domain" and a[2] == "real":
            source.append(name(a[1][1]) + r"\in\mathbb R")
        elif a[0] == "=" and a[1][:2] == ["call", "Dom"]:
            label = r"x\in " if row.get("input_restriction") else "D_{" + name(a[1][2][1]) + "}="
            source.append(label + _source_latex(a[2], "x"))
        elif a[0] == "=" and a[2][0] == "extremum":
            source.append(_source_latex(a[1], "x") + "=" + "\\" + a[2][1] + " "
                          + _source_latex(a[2][3], "x"))
        elif a[0] == "=":
            source.append(_source_latex(a[1], "x") + "=" + _source_latex(a[2], "x"))
        elif a[0] == "quantifier":
            from ..parity_extension_math import ARGUMENT, _replace

            body = _replace(a[4], ["bound", a[2]], ARGUMENT)
            scope = parse_sources(d)["relation_scope_ast"]
            source.append(r"\forall x\in " + _source_latex(scope, "x") + r",\quad "
                          + _source_latex(body[1], "x") + "=" + _source_latex(body[2], "x"))
    return source


def _latex(value):
    if isinstance(value, sp.Basic):
        value = value.xreplace(
            {s: sp.Symbol(name(str(s)), real=True) for s in value.free_symbols}
        )
    return latex(value)


def _visual(view, m):
    numeric = [r["input"] for r in m["maps"] if not r["input"].free_symbols]
    if numeric:
        q = numeric[0]
        scope = m.get("relation_scope")
        if scope is None:
            scope = m["domain"] if m["domain"] is not None else sp.FiniteSet(q, -q)
        view["condition_number_lines"] = _pair_lines(
            {"a": sp.S.Zero, "scope": scope}, q
        )
        if m["domain"] is None:
            for line in view["condition_number_lines"]:
                line["label"] = r"已知合法的一对相反输入"
    elif m["extrema"]:
        view["condition_number_lines"] = _pair_lines(
            {"a": sp.S.Zero, "scope": m["domain"]}, m["domain"].end
        )
        for line in view["condition_number_lines"]:
            line["label"] = r"最值所在的同一范围"
    elif m["identity"] and m["domain"] is not None:
        line = _pair_lines({"a": sp.S.Zero, "scope": m["domain"]}, sp.S.Zero)[0]
        line["label"] = r"原函数的对称定义域"
        line["points"] = [
            p
            for p in line["points"]
            if m["domain"].contains(sp.Rational(str(p["at"]))) is sp.true
        ]
        view["condition_number_lines"] = [line]
    return view


def phase_views(values):
    d = values["description"]
    m, s = solve(d), parse_sources(d)
    definition = s["definition"]["ast"]
    f = name(definition[1][1])
    source = [f + "(x)=" + _source_latex(definition[2], "x")]
    source += [name(r) + r"\text{ 是奇函数}" for r in s["odd"]]
    source += [
        _source_latex(r["ast"][1], "x") + "=" + _source_latex(r["ast"][2], "x")
        for r in s["values"]
    ]
    if m["domain"] is not None:
        source.append(r"D=" + latex(m["domain"]))
    if not s["explicit"]:
        f = name(next(r for r in s["refs"] if r not in s["odd"]))
    K = m["K"]
    parameter = m.get("parameter")
    if parameter:
        symbol = _latex(parameter["symbol"])
        statement = symbol + r"\in " + _latex(parameter["allowed"])
        conditions = [_latex(e) + "=0" for e in parameter["equations"]]
        for case in parameter["cases"]:
            if case["equations"]:
                conditions.append(
                    symbol
                    + r"\in "
                    + _latex(case["scope"])
                    + r":\quad "
                    + r",\quad ".join(_latex(e) + "=0" for e in case["equations"])
                )
        if parameter["is_parameter_target"] or values["phase"] == "rewrite":
            return [
                _read(
                    "求参数并检查零系数",
                    "先列不含除法的等式，再分别检查两个函数的系数为零时有哪些条件保留。",
                    source,
                    statement,
                    [*conditions, statement],
                )
            ]
        target = target_math(d)
        result = m["proof"]["value"]
        answer = (
            target + "=" + _latex(result)
            if result is not None
            else target + r"\text{ 不能唯一确定}"
        )
        alternatives = (
            [result + 1, result - 1]
            if result is not None
            else [w["value"] for w in m["proof"]["witnesses"]]
        )
        return [
            choice_card(
                "回答原题所求",
                "把各个参数情况代回原目标，检查结论是否一致。",
                "已知条件",
                _lines(source),
                "结论",
                answer,
                [target + "=" + _latex(v) for v in alternatives],
                _lines([statement, answer]),
            )
        ]
    law = (
        f + "(x)+" + f + "(-x)=" + _latex(K)
        if K is not None
        else r"\text{该关系不限制原函数的值}"
    )
    if s["relation_scope_ast"] is not None:
        from ..function_parity import reflect_set

        scope = m["relation_scope"]
        scope = scope & reflect_set(scope)
        law = (
            law + r"\quad(x\in " + _latex(scope) + ")"
            if scope != sp.S.EmptySet and K is not None
            else r"\text{当前范围不能同时代入一对相反数}"
        )
    if values["phase"] == "rewrite":
        if K is None or s["relation_scope_ast"] is not None:
            return [
                _read(
                    "检查关系的适用范围"
                    if s["relation_scope_ast"] is not None
                    else "检查零系数",
                    "检查原关系能否同时用于一对相反输入。"
                    if s["relation_scope_ast"] is not None
                    else "系数为零时，重新检查哪些条件仍约束原函数。",
                    source,
                    law,
                    [law],
                )
            ]
        choices = [K + 1, K - 1, -K, K / 2]
        wrong = [
            f + "(x)+" + f + "(-x)=" + latex(v)
            for v in dict.fromkeys(choices)
            if v != K
        ]
        proof = [*source, law]
        if s["explicit"]:
            expression = m["identity"]["expression"]
            odd_part = (
                _latex(expression - K / 2)
                if expression is not None
                else _source_latex(["-", definition[2], ["number", str(K / 2)]], "x")
            )
            proof.insert(
                -1,
                f
                + r"(x)=\left("
                + odd_part
                + r"\right)"
                + ("+" if K >= 0 else "")
                + _latex(K / 2),
            )
        else:
            odd = name(s["odd"][0])
            proof.insert(-1, odd + "(x)+" + odd + "(-x)=0")
        proof.append(r"\frac{" + f + "(x)+" + f + r"(-x)}{2}=" + _latex(K / 2))
        return [
            _visual(
                choice_card(
                    "求相反输入的函数值之和",
                    "先明确奇函数，再将结论还原到所求的函数。",
                    "原式与条件",
                    _lines(source),
                    "对称和值",
                    law,
                    wrong[:3],
                    _lines(proof),
                ),
                m,
            )
        ]
    target = target_math(d)
    p = m["proof"]
    if p["status"] == "determined":
        result = p["value"]
        answer = target + "=" + latex(result)
        wrong = [
            target + "=" + latex(v)
            for v in dict.fromkeys([result + 1, result - 1, -result])
            if v != result
        ]
    else:
        answer = target + r"\text{ 不能唯一确定}"
        wrong = [
            target
            + "="
            + latex(sum((a * b for a, b in zip(m["target"], w)), m["constant"]))
            for w in p["witnesses"]
        ]
    lines = [law]
    if m["extrema"]:
        lines += [
            r"x\in D\Longleftrightarrow -x\in D",
            f + "(t)=M",
            f + "(-t)=" + latex(K) + "-M=m",
        ]
    else:
        for r in m["maps"][:12]:
            if not r["terms"]:
                lines.append(
                    name(r["function"])
                    + "("
                    + _latex(r["input"])
                    + ")="
                    + _latex(r["constant"])
                )
    return [
        _visual(
            choice_card(
                "回答原题所求",
                "使用对称和值，检查每项的系数、出现次数及取值范围。",
                "已知条件",
                _lines(source),
                "结论",
                answer,
                wrong[:3],
                _lines([*lines, answer]),
            ),
            m,
        )
    ]
