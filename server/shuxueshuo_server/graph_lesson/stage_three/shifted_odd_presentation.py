"""Substitute -x, add f(x)+f(-x), then use the source values; the only curve is a labelled sketch."""

import sympy as sp

from ..parity_extension_math import ARGUMENT
from ..shifted_odd_identity import X, scalar
from ..shifted_odd_math import combine, name, parse_sources, solve
from ..symmetry_value_math import _function_calls
from .absolute_graph_presentation import choice_card
from .interaction_graph_contract import validate_graph
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .symmetry_presentation import _source_latex
from .symmetry_relation_presentation import _group, _read, target_math

BECAUSE, THEREFORE = r"\because\ ", r"\therefore\ "


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


def _same(a, b):
    return sp.cancel(a - b) == 0


def _terms(e):
    """Additive terms, highest power of x first and the constant last."""
    def key(t):
        power = t.as_coeff_exponent(X)[1]
        return (power == 0, -power if power.is_number else 0)
    return sorted(sp.Add.make_args(sp.expand(e)), key=key)


def _join(parts):
    text = "+".join(parts) or "0"
    return text.replace("+-", "-")


def _poly(e):
    return _join([_latex(t) for t in _terms(e)])


def _show(e):
    """A fraction keeps one numerator over the source denominator."""
    n, d = sp.fraction(sp.together(e))
    if d == 1 or not d.has(X):
        return _poly(e)
    return r"\frac{" + _poly(n) + "}{" + _poly(d) + "}"


def _unique_wrong(right, candidates, limit=3):
    out = []
    for c in candidates:
        if not _same(c, right) and all(not _same(c, o) for o in out):
            out.append(c)
    return out[:limit]


def _forgotten_substitutions(e, fraction):
    """Each wrong form leaves one term at x, or negates every term."""
    n, d = sp.fraction(sp.together(e))
    flip = lambda t: t.subs(X, -X)
    if fraction:
        terms = _terms(n)
        rows = [(sum(flip(u) for u in terms if u is not t) + t) / flip(d) for t in terms]
    else:
        terms = _terms(e)
        rows = [sum(flip(u) for u in terms if u is not t) + t for t in terms]
    return [*rows, e, -e]


def _lin(k, b, call):
    head = call if k == 1 else "-" + call if k == -1 else _latex(k) + call
    return head if b == 0 else _join([head, _latex(b)])


def _odd_part(m, c):
    expression = m["identity"]["expression"] if m.get("identity") else None
    if expression is None:
        return None
    h = sp.cancel(expression - c)
    return h if _same(h.subs(X, -X), -h) else None


SYMMETRIC = r"\text{定义域关于原点对称，}x\text{ 与 }-x\text{ 都能代入}"


def _given(source, m):
    domain = m.get("domain")
    return [*source, SYMMETRIC] if domain is not None and domain != sp.S.Reals else source


def _paren(v):
    text = _latex(v)
    return r"\left(" + text + r"\right)" if text.startswith("-") or isinstance(v, sp.Add) else text


def _times(c, inner):
    body = r"\left(" + inner + r"\right)"
    return body if c == 1 else "-" + body if c == -1 else _latex(c) + body


def _negated(e):
    """h(-x) as substituted, before collecting signs."""
    n, d = sp.fraction(sp.together(e))

    def term(t):
        k, power = t.as_coeff_exponent(X)
        if power == 0:
            return _latex(t)
        base = "(-x)" if power == 1 else "(-x)^{" + _latex(power) + "}"
        return ("" if k == 1 else "-" if k == -1 else _latex(k)) + base

    flip = lambda p: _join([term(t) for t in _terms(p)])
    return r"\frac{" + flip(n) + "}{" + flip(d) + "}"


def _whole(cards, key, title):
    """The completed card shows every part's derivation, not only its last answer."""
    cards[-1]["proof"] = _lines([c["proof"] for c in cards])
    return _group(cards, key, title)


def _sum_card(f, known, law, wrong, proof, question):
    return choice_card("求 $" + f + "(x)+" + f + "(-x)$", question, "已知", _lines(known),
                       f + "(x)+" + f + "(-x)", law, wrong, _lines(proof))


def _substitution_card(title, question, known, label, right, wrong, proof):
    # A zero expression has no distinct sign/substitution distractor.
    if not wrong:
        return _read(title, question, known, right, proof)
    return choice_card(title, question, "已知", _lines(known), label, right, wrong, _lines(proof))


def _explicit_cards(s, m, f, given, law, wrong):
    """A hidden constant is split out first; a visible one is substituted directly."""
    K, expression = m["K"], (m.get("identity") or {}).get("expression")
    if expression is None or K.free_symbols:
        return None
    c, source = K / 2, s["definition"]["ast"][2]
    total = rf"{f}(x)+{f}(-x)"
    if source[0] == "/" and c != 0:
        h = _odd_part(m, c)
        if h is None:
            return None
        n, den = sp.fraction(sp.together(expression))
        rest = sp.expand(n - c * den)
        source_rest = scalar(source[1], guards=[]) - c * scalar(source[2], guards=[])
        constant_only = n - c * den.subs(X, 0)
        splits = [(c, constant_only), (c, n), (-c, rest)]
        wrong_splits = [(k, r) for k, r in splits if not _same(k + r / den, expression)]
        option = lambda k, r: f"{f}(x)=" + _join([_latex(k), _show(r / den)])
        right = option(c, rest)
        split = choice_card(
            "拆出常数项",
            rf"把分子凑出分母的倍数，将 ${f}(x)$ 拆成「常数 + 分式」。哪一种拆法正确？",
            "已知", _lines(given), "拆分结果", right,
            list(dict.fromkeys(option(k, r) for k, r in wrong_splits if option(k, r) != right))[:3],
            _lines([BECAUSE + _source_latex(source[1], "x") + "=" + _times(c, _source_latex(source[2], "x"))
                    + "+" + r"\left(" + _show(source_rest) + r"\right)", THEREFORE + right]))
        hx, hneg = _show(h), sp.cancel(h.subs(X, -X))
        odd = _substitution_card(
            "判断剩余部分是奇函数",
            rf"记 $h(x)={hx}$。把 $x$ 换成 $-x$，$h(-x)$ 等于什么？",
            [f"{f}(x)=" + _join([_latex(c), "h(x)"]), f"h(x)={hx}"], "h(-x)",
            "h(-x)=" + _show(hneg),
            ["h(-x)=" + _show(w) for w in _unique_wrong(hneg, _forgotten_substitutions(h, True))],
            ["h(-x)=" + _negated(h), "h(-x)=" + _show(hneg) + "=-h(x)",
             THEREFORE + r"h(x)\text{ 是奇函数}"])
        add = _sum_card(
            f, [f"{f}(x)=" + _join([_latex(c), "h(x)"]), "h(-x)=-h(x)"], law, wrong,
            [THEREFORE + total + r"=\left(" + _join([_latex(c), "h(x)"]) + r"\right)+\left("
             + _join([_latex(c), "-h(x)"]) + r"\right)=" + _latex(K)],
            rf"由 ${f}(x)=" + _join([_latex(c), "h(x)"]) + rf"$，${total}$ 等于多少？")
        return [split, odd, add]
    negative = sp.expand(expression.subs(X, -X))
    if not _same(expression + negative, K):
        return None
    written = _substitution_card(
        "写出 $" + f + "(-x)$",
        rf"把 ${f}(x)$ 中的 $x$ 换成 $-x$，${f}(-x)$ 等于什么？",
        given, f + "(-x)", f"{f}(-x)=" + _poly(negative),
        [f"{f}(-x)=" + _poly(w) for w in _unique_wrong(negative, _forgotten_substitutions(expression, False))],
        [f"{f}(-x)=" + _source_latex(source, "(-x)"), f"{f}(-x)=" + _poly(negative)])
    add = _sum_card(
        f, [f"{f}(x)=" + _source_latex(source, "x"), f"{f}(-x)=" + _poly(negative)], law, wrong,
        [THEREFORE + total + r"=\left(" + _source_latex(source, "x") + r"\right)+\left(" + _poly(negative)
         + r"\right)=" + _latex(K)],
        rf"把 ${f}(x)$ 与 ${f}(-x)$ 相加，${total}$ 等于多少？")
    return [written, add]


def _relation_cards(s, m, f, given, law, wrong):
    """g(-x)=-g(x), written through the source relation between f and the odd g."""
    if m["K"] is None or len(s["odd"]) != 1:
        return None
    a, odd_ref = s["definition"]["ast"], s["odd"][0]
    f_ref = next(r for r in s["refs"] if r != odd_ref)
    coeffs, C = combine(["-", ["function_call", a[1], ARGUMENT], a[2]], symbolic_coefficients=True)
    A, B = coeffs.get((f_ref, X), sp.S.Zero), coeffs.get((odd_ref, X), sp.S.Zero)
    if A == 0 or B == 0 or any(v.free_symbols for v in (A, B, C)):
        return None
    k, b, g = -A / B, -C / B, name(odd_ref)
    u, v = f"{f}(-x)", f"{f}(x)"
    gx, gneg = _lin(k, b, v), _lin(k, b, u)
    # A source written as f(x)=g(x)+c is first solved for g(x).
    solved = [] if a[1][1] == odd_ref else [f"{g}(x)={gx}"]
    stated = f"{name(a[1][1])}(x)={_source_latex(a[2], 'x')}"
    lead = f"由 ${stated}$ 得 ${solved[0]}$。" if solved else ""
    middles = list(dict.fromkeys(t for t in (_lin(-k, b, v), _lin(k, b, v), _lin(-k, b, u)) if t != gneg))
    substituted = choice_card(
        "代入 $-x$",
        lead + rf"把 $x$ 换成 $-x$，再由 ${g}$ 是奇函数，${g}(-x)$ 等于什么？",
        "已知", _lines([*given, *solved]), f"{g}(-x)", f"{g}(-x)={gneg}=-{g}(x)",
        [f"{g}(-x)={t}=-{g}(x)" for t in middles][:3],
        _lines([BECAUSE + stated, *(THEREFORE + t for t in solved), THEREFORE + f"{g}(-x)={gneg}",
                BECAUSE + g + r"\text{ 是奇函数}", THEREFORE + f"{g}(-x)={gneg}=-{g}(x)"]))
    U, V = sp.symbols("u v")
    opposite = _lin(-k, -b, v)
    right = (gneg + "=" + opposite, k * U + b + k * V + b)
    candidates = [(gneg + "=" + _lin(-k, b, v), k * U + k * V),
                  (gneg + "=" + gx, k * U - k * V),
                  (gneg + "=" + _lin(-k, 0, v), k * U + b + k * V)]
    same = lambda p, q: not (sp.cancel(p / q).free_symbols & {U, V})
    chosen = []
    for text, e in candidates:
        if e != 0 and not same(e, right[1]) and all(not same(e, o) for _, o in chosen):
            chosen.append((text, e))
    equation = choice_card(
        "由奇函数列出等式",
        rf"由 ${g}(-x)=-{g}(x)$，把等号两边都用 ${f}$ 表示，得到哪个等式？",
        "已知", _lines([f"{g}(-x)={gneg}", f"-{g}(x)={opposite}"]), "等式", right[0], [t for t, _ in chosen][:3],
        _lines([THEREFORE + f"{gneg}=-\\left({gx}\\right)", THEREFORE + right[0]]))
    total = f"{v}+{u}"
    collected = [] if k == 1 else [THEREFORE + _lin(k, 0, r"\left(" + total + r"\right)") + "=" + _latex(-2 * b)]
    add = _sum_card(f, [right[0]], law, wrong, [*collected, THEREFORE + total + "=" + _latex(m["K"])],
                    rf"移项整理，${f}(x)+{f}(-x)$ 等于多少？")
    return [substituted, equation, add]


def _pair_proof(d, s, f, K, value):
    """f(q)+f(-q)=K with one printed value, or the printed pair itself."""
    if d["source"]["kind"] == "finite_sum" or K is None:
        return None
    t = d["goal_ast"]["target"]
    calls = _function_calls(t)
    if any(name(c[1][1]) != f for c in calls):
        return None
    if t[0] == "function_call":
        q = scalar(t[2])
        for r in s["values"]:
            left, right = r["ast"][1], r["ast"][2]
            if left[0] == "function_call" and left[1] == t[1] and not _function_calls(right) \
                    and _same(scalar(left[2]), -q):
                known, p = scalar(right), _latex(q)
                n = _latex(-q)
                if not _same(K - known, value):
                    return None
                return [rf"\text{{取 }}x={p}\text{{，得 }}{f}({p})+{f}({n})={_latex(K)}",
                        BECAUSE + f"{f}({n})={_latex(known)}",
                        THEREFORE + f"{f}({p})={_latex(K)}-{_paren(known)}={_latex(value)}"]
    if t[0] == "+" and len(calls) == 2 and t[1:] == calls \
            and _same(scalar(calls[0][2]), -scalar(calls[1][2])) and _same(K, value):
        q = _latex(scalar(calls[0][2]))
        return [rf"\text{{取 }}x={q}", THEREFORE + target_math(d) + "=" + _latex(K)]
    return None


def _extrema_graph(m, h):
    """Sketch of the odd part h for one sample parameter: (t, G) reflects through the origin."""
    domain = m["domain"]
    params = sorted(h.free_symbols - {X}, key=str)
    lo, hi = float(domain.start), float(domain.end)
    xs = [lo + (hi - lo) * i / 128 for i in range(129)]
    for trial in (-3, 3, -2, 2, -1, 1):
        sample = h.subs({p: trial for p in params})
        fn = sp.lambdify(X, sample)
        try:
            ys = [float(fn(x)) for x in xs]
        except (ZeroDivisionError, ValueError, TypeError, OverflowError):
            continue
        top = max(range(len(ys)), key=ys.__getitem__)
        if 0 < top < len(ys) - 1 or trial == 1:
            break
    else:
        return None
    t, G = xs[top], ys[top]
    pad = 0.25 * max(abs(v) for v in ys)
    chosen = ", ".join(f"{_latex(p)}={trial}" for p in params)
    graph = {"kind": "sampled_curve", "params": {
        "bounds": [lo - 0.3, hi + 0.3, min(ys) - pad, max(ys) + pad], "title": "奇函数的最值关于原点对称",
        "description": "实线为 h(x) 的图像；最高点 (t, G) 与最低点 (-t, -G) 关于原点对称。",
        "variable": "x", "interval": [lo, hi], "interval_closed": [True, True], "points": [],
        "xTicks": [[lo, short(lo)], [0, "0"], [hi, short(hi)]], "dividers": [],
        "traces": [{"label": "h(x)", "segments": [[[x, y] for x, y in zip(xs, ys)]],
                    "markers": [{"x": -t, "y": float(fn(-t)), "closed": True, "label": "(−t, −G)"},
                                {"x": 0, "y": 0.0, "closed": True},
                                {"x": t, "y": G, "closed": True, "label": "(t, G)"}]}]},
        "caption": ("示意图：取 $" + chosen + "$ 时 $h(x)$ 的图像。参数取其他值时形状不同，但 "
                    if params else "示意图：$h(x)$ 的图像。")
                   + "$h$ 是奇函数，最高点 $(t,G)$ 与最低点 $(-t,-G)$ 总关于原点对称。"}
    try:
        validate_graph(graph)
    except (ValueError, TypeError, KeyError):
        return None
    return graph


def short(v):
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _extrema_views(d, m, f, answer, wrong):
    """Max of the odd part at t reflects to its min at -t; no monotonicity is assumed."""
    K = m["K"]
    c = K / 2
    h = _odd_part(m, c)
    if h is None or len(m["extrema"]) != 2:
        return None
    ordered = sorted(m["extrema"].items(), key=lambda row: row[1][1] != "max")
    big, small = name(ordered[0][0]), name(ordered[1][0])
    target = target_math(d)
    if h == 0:
        constant = f"{f}(x)=" + _latex(c)
        return [choice_card(
            "求 $" + target + "$",
            rf"${f}(x)$ 是常数函数，${target}$ 等于多少？",
            "已知", _lines([constant, r"x\in " + _latex(m["domain"])]), "结论", answer, wrong,
            _lines([BECAUSE + constant, THEREFORE + f"{big}={small}=" + _latex(c),
                    THEREFORE + answer]))]
    G = sp.Symbol("G")
    top, low = _poly(c + G), _poly(c - G)
    split = f"{f}(x)=" + _join([_latex(c), "h(x)"])
    hmax, hmin = r"h(x)_{\max}=G", r"h(x)_{\min}"
    first = choice_card(
        "$h(x)$ 的最值关于原点对称",
        r"设 $h(x)$ 在 $x=t$ 处取到最大值 $G$。由 $h$ 是奇函数，$h(x)$ 的最小值是多少？",
        "已知", _lines([f"h(x)={_show(h)}", "h(-x)=-h(x)", r"x\in " + _latex(m["domain"]), hmax]),
        "$h(x)$ 的最小值", hmin + "=-G", [hmin + "=" + w for w in ("G", "0", "-2G")],
        _lines([r"\text{设 }h(t)=G\text{ 是 }h(x)\text{ 的最大值}",
                BECAUSE + r"h\text{ 是奇函数}",
                THEREFORE + r"h(-x)=-h(x)\ge -G\text{，且 }h(-t)=-G",
                THEREFORE + hmin + "=-G"]))
    graph = _extrema_graph(m, h)
    if graph is not None:
        first["graph"], first["completion_graph"] = graph, dict(graph)
    second = choice_card(
        "求 $" + target + "$",
        rf"由 ${split}$，$h(x)$ 的最大值为 $G$、最小值为 $-G$，${target}$ 等于多少？",
        "已知", _lines([split, hmax, hmin + "=-G"]), "结论", answer, wrong,
        _lines([BECAUSE + split, THEREFORE + f"{big}={top}\\text{{，}}{small}={low}",
                THEREFORE + target + r"=\left(" + top + r"\right)+\left(" + low + r"\right)=" + _latex(K)]))
    return _whole([first, second], "extrema", "利用最值对称求 $" + target + "$")


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
        printed = {_source_latex(r["ast"][1], "x") + "=" + _source_latex(r["ast"][2], "x") for r in s["values"]}
        given = _given([line for line in source if line not in printed], m)
        build = _explicit_cards if s["explicit"] else _relation_cards
        cards = build(s, m, f, given, law, wrong[:3])
        if cards is None:
            cards = [choice_card(
                "求 $" + f + "(x)+" + f + "(-x)$",
                "把 $x$ 换成 $-x$，再与 $" + f + "(x)$ 相加，$" + f + "(x)+" + f + "(-x)$ 等于多少？",
                "已知", _lines(given), f + "(x)+" + f + "(-x)", law, wrong[:3], _lines(proof))]
        return _whole(cards, "opposite-sum", "代入 $-x$，求 $" + f + "(x)+" + f + "(-x)$")
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
    if m["extrema"]:
        views = _extrema_views(d, m, f, answer, wrong[:3])
        if views is not None:
            return views
    lines = [BECAUSE + law]
    for r in m["maps"][:12]:
        if not r["terms"]:
            lines.append(
                name(r["function"])
                + "("
                + _latex(r["input"])
                + ")="
                + _latex(r["constant"])
            )
    pair = _pair_proof(d, s, f, K, p["value"]) if p["status"] == "determined" else None
    lines = pair or [*lines, THEREFORE + answer]
    known = [_source_latex(r["ast"][1], "x") + "=" + _source_latex(r["ast"][2], "x") for r in s["values"]]
    question = ("已知" + "，".join("$" + t + "$" for t in known) + "，" if known else "") + "求 $" + target + "$ 的值。"
    return [
        choice_card(
            "代入题目中的数",
            question,
            "已知",
            _lines([law, *known]),
            "结论",
            answer,
            wrong[:3],
            _lines(lines),
        )
    ]
