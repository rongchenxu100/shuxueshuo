"""Teaching projection for FM-T4 monotonicity-condition parameter finding (R0–R3)."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..monotonicity_parameter_math import _basis_ast
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .trajectory import decode_value

DIR = {'increasing': '递增', 'decreasing': '递减'}
FLIP = {sp.StrictGreaterThan: sp.StrictLessThan, sp.StrictLessThan: sp.StrictGreaterThan,
        sp.GreaterThan: sp.LessThan, sp.LessThan: sp.GreaterThan}
TOGGLE = {sp.StrictGreaterThan: sp.GreaterThan, sp.GreaterThan: sp.StrictGreaterThan,
          sp.StrictLessThan: sp.LessThan, sp.LessThan: sp.StrictLessThan}
REL_TEX = {sp.StrictGreaterThan: '>', sp.GreaterThan: r'\ge ', sp.StrictLessThan: '<',
           sp.LessThan: r'\le ', sp.Equality: '='}


def _poly_tex(expr, x):
    """Descending powers of x with each coefficient kept together, e.g. (2a+4)x-5."""
    expanded = sp.expand(expr)
    if expanded == 0:
        return '0'
    if not expanded.is_polynomial(x):
        return latex(expr)
    poly = sp.Poly(expanded, x, domain=sp.EX)
    terms = []
    for degree in range(poly.degree(), -1, -1):
        coeff = sp.simplify(poly.nth(degree))
        if coeff == 0:
            continue
        power = '' if degree == 0 else (latex(x) if degree == 1 else rf'{latex(x)}^{{{degree}}}')
        if not power and isinstance(coeff, sp.Add):
            text = sp.latex(coeff, order='lex')
            negative = text.startswith('-')
            body = text[1:] if negative else text
        elif not power:
            body, negative = latex(-coeff) if coeff.could_extract_minus_sign() else latex(coeff), coeff.could_extract_minus_sign()
        elif coeff == 1 or coeff == -1:
            body, negative = power, coeff == -1
        elif isinstance(coeff, sp.Add):
            body, negative = rf'\left({latex(coeff)}\right){power}', False
        else:
            negative = coeff.could_extract_minus_sign()
            body = rf'{latex(-coeff if negative else coeff)}{power}'
        terms.append(('-' if negative else '+', body))
    if not terms:
        return '0'
    text = ('-' if terms[0][0] == '-' else '') + terms[0][1]
    return text + ''.join(sign + body for sign, body in terms[1:])


def _signed(coeff, body):
    """(sign, text) for coeff*body with the coefficient kept together."""
    coeff = sp.simplify(coeff)
    negative = coeff.could_extract_minus_sign()
    magnitude = -coeff if negative else coeff
    if body is None:
        return ('-' if negative else '+'), latex(magnitude)
    if magnitude == 1:
        return ('-' if negative else '+'), body
    if isinstance(magnitude, sp.Add):
        return '+', rf'\left({latex(coeff)}\right){body}'
    return ('-' if negative else '+'), rf'{latex(magnitude)}{body}'


def _reciprocal_tex(expr, x):
    """s*x + c/x + d in reading order, e.g. x-\\dfrac{a}{x}-2."""
    scaled = sp.expand(sp.cancel(expr * x))
    if not scaled.is_polynomial(x) or sp.Poly(scaled, x).degree() > 2:
        return latex(expr)
    slope, offset, numerator = scaled.coeff(x, 2), scaled.coeff(x, 1), scaled.coeff(x, 0)
    terms = []
    if slope != 0:
        terms.append(_signed(slope, latex(x)))
    if numerator != 0:
        negative = sp.simplify(numerator).could_extract_minus_sign()
        magnitude = -numerator if negative else numerator
        terms.append(('-' if negative else '+', rf'\dfrac{{{latex(magnitude)}}}{{{latex(x)}}}'))
    if offset != 0:
        terms.append(_signed(offset, None))
    if not terms:
        return '0'
    text = ('-' if terms[0][0] == '-' else '') + terms[0][1]
    return text + ''.join(sign + body for sign, body in terms[1:])


def _expr_tex(expr, x):
    if isinstance(expr, sp.Pow) and expr.exp == sp.Rational(1, 2):
        return rf'\sqrt{{{_expr_tex(expr.base, x)}}}'
    return _poly_tex(expr, x) if sp.expand(expr).is_polynomial(x) else _reciprocal_tex(expr, x)


def _set_latex(value):
    if value == sp.S.Reals:
        return r'\mathbb{R}'
    if value == sp.S.EmptySet:
        return r'\varnothing'
    return latex(value).replace(r', \infty\right', r', +\infty\right')


def _membership(var, value):
    return rf'{var}\in {_set_latex(value)}'


def _load(value, *keys):
    if isinstance(value, dict) and any(key in value for key in keys):
        return value
    return decode_value(value)


GATHER = (r'\begin{gathered}', r'\end{gathered}')


def _gathered_rows(item):
    """Top-level rows of a whole gathered block, or None; rows of inner environments stay intact."""
    if not (item.startswith(GATHER[0]) and item.endswith(GATHER[1])):
        return None
    body = item[len(GATHER[0]):-len(GATHER[1])]
    rows, depth, start, i = [], 0, 0, 0
    while i < len(body):
        if body.startswith(r'\begin{', i):
            depth += 1
        elif body.startswith(r'\end{', i):
            depth -= 1
            if depth < 0:
                return None
        elif body.startswith(r'\\', i):
            if depth == 0:
                rows.append(body[start:i])
                start = i + 2
            i += 2
            continue
        i += 1
    return rows + [body[start:]] if depth == 0 else None


def _lines(items):
    """One flat gathered block: nested blocks are unwrapped and repeated lines dropped."""
    flat = []
    for item in items:
        if not item:
            continue
        rows = _gathered_rows(item) or [item]
        for row in rows:
            row = row.removeprefix('{}')
            if row not in flat:
                flat.append(row)
    if len(flat) <= 1:
        return flat[0] if flat else ''
    # A row opening with "[" would be read as the optional spacing argument of "\\".
    return GATHER[0] + r'\\'.join('{}' + row if row.startswith('[') else row for row in flat) + GATHER[1]


def _wrong_memberships(var, answer):
    candidates = [sp.S.EmptySet, sp.S.Reals]
    if isinstance(answer, sp.Interval):
        candidates += [
            sp.Interval(answer.start, answer.end,
                        left_open=not answer.left_open, right_open=answer.right_open),
            sp.Interval(answer.start, answer.end,
                        left_open=answer.left_open, right_open=not answer.right_open),
        ]
    wrong = []
    for candidate in candidates:
        text = _membership(var, candidate)
        if text != _membership(var, answer) and text not in wrong:
            wrong.append(text)
        if len(wrong) >= 3:
            break
    return wrong or [_membership(var, sp.S.EmptySet), _membership(var, sp.S.Reals)]


def _relation_tex(rel):
    return rf'{latex(rel.lhs)}{REL_TEX[type(rel)]}{latex(rel.rhs)}'


def _solve_relation(rel, parameter):
    from ..extremum_math import condition_set
    return sp.simplify(condition_set(sp.simplify(rel), parameter))


def _condition_options(rel, parameter, var):
    """Correct ``condition ⇒ set`` with flipped / strictness-toggled distractors."""
    if not rel.free_symbols:
        feasible = _solve_relation(rel, parameter)
        # Flipping a constant relation can produce another true statement, not a distractor.
        return _membership(var, feasible), _wrong_memberships(var, feasible)
    correct = rf'{_relation_tex(rel)}\Rightarrow {_membership(var, _solve_relation(rel, parameter))}'
    wrong = []
    for builder in (FLIP, TOGGLE):
        other = builder[type(rel)](rel.lhs, rel.rhs, evaluate=False)
        text = rf'{_relation_tex(other)}\Rightarrow {_membership(var, _solve_relation(other, parameter))}'
        if text != correct and text not in wrong:
            wrong.append(text)
    flipped_toggled = TOGGLE[FLIP[type(rel)]](rel.lhs, rel.rhs, evaluate=False)
    text = rf'{_relation_tex(flipped_toggled)}\Rightarrow {_membership(var, _solve_relation(flipped_toggled, parameter))}'
    if text != correct and text not in wrong:
        wrong.append(text)
    return correct, wrong


def _fx(compiled):
    """The function as the problem names it: f(x), or y when no name is given."""
    fn = compiled.get('function')
    return rf'{fn}\!\left({compiled["variable"]}\right)' if fn else 'y'


def _requirement_tex(compiled, region_tex):
    subject = _fx(compiled)
    return rf'{subject}\ \text{{在}}\ {region_tex}\ \text{{上严格{DIR[compiled["direction"]]}}}'


def _basis_tex(compiled):
    basis = compiled.get('basis') or {'kind': 'stated'}
    if basis['kind'] == 'stated':
        return None
    ast, _, _ = _basis_ast(basis)
    values, inputs = ast[1][1], ast[1][2]
    fn = values[1][1]
    u, v = (latex(sp.Symbol(call[2][1])) for call in values[1:])
    s, t = (latex(sp.Symbol(item[1])) for item in inputs[1:])
    num = rf'{fn}({u})-{fn}({v})'
    den = rf'{s}-{t}'
    sign = '<' if ast[0] == '<' else '>'
    if basis['kind'] == 'difference_quotient':
        return rf'\dfrac{{{num}}}{{{den}}}{sign}0'
    return rf'\left[{num}\right]\left({den}\right){sign}0'


def _basis_input_tex(basis):
    ast, _, _ = _basis_ast(basis)
    return [latex(sp.Symbol(call[2][1])) for call in ast[1][1][1:]]


def _axis_condition(compiled, model):
    """Student-facing axis relation for the kept quadratic case (single expression)."""
    region = compiled['interval']
    direction = compiled['direction']
    leading = compiled['leading']
    axis = compiled.get('axis')
    if axis is None:
        return None
    left, right = region.inf, region.sup
    sign = None
    for case in model['cases']:
        if case['kind'] == 'quadratic' and case['kept']:
            sign = case['meta'].get('leading_sign')
            axis = case['meta'].get('axis', axis)
            break
    if sign is None:
        if leading.free_symbols:
            return None
        sign = 1 if leading > 0 else -1
    if direction == 'increasing':
        bound, op = (left, r'\le') if sign > 0 else (right, r'\ge')
    else:
        bound, op = (right, r'\ge') if sign > 0 else (left, r'\le')
    if bound in (-sp.oo, sp.oo):
        return None
    return rf'{latex(axis)}{op}{latex(bound)}'


def _axis_graphs(function, x, p, region, direction, feasible):
    """Draggable-axis picture for one quadratic piece, plus a completion picture limited to ``feasible``.

    Returns ``{}`` when the family cannot move by its axis (e.g. the parameter sits in the leading term).
    """
    from . import interaction_graphs as drawing
    word = DIR[direction]
    poly = sp.Poly(sp.expand(function), x, domain=sp.EX)
    leading, linear = poly.nth(2), poly.nth(1)
    if leading == 0 or leading.free_symbols:
        return {}
    axis = sp.cancel(-linear / (2 * leading))
    if axis.free_symbols != {p}:
        return {}
    low, high = region.inf, region.sup
    if low.is_finite and high.is_finite:
        target = (low + high) / 2
    elif low.is_finite:
        target = low + 1
    elif high.is_finite:
        target = high - 1
    else:
        return {}
    roots = sp.solve(sp.Eq(axis, target), p)
    if len(roots) != 1:
        return {}
    region_text, region_tex = drawing.plain(region), _set_latex(region)
    ends = [end for end in (low, high) if end.is_finite]
    span = max(2, *(abs(end) for end in ends)) if ends else 2
    common = {'breakpoints': [], 'target': direction, 'min_span': float(span)}
    try:
        graph = drawing.axis_explorer(
            function, x, p, region, start=roots[0],
            title=f'y={drawing.plain(function)} 的对称轴与区间 {region_text}',
            description=f'拖动对称轴，观察区间 {region_text} 上的曲线是否整段严格{word}',
            caption=f'拖动对称轴，观察 ${region_tex}$ 上的曲线是否整段严格{word}（图像只示意开口与对称轴，上下平移不改变增减）',
            **common)
    except drawing.GraphUnavailable:
        return {}
    views = {'graph': graph}
    if isinstance(feasible, sp.Interval):
        try:
            views['completion_graph'] = drawing.axis_explorer(
                function, x, p, region, start=None, within=feasible,
                title=f'{drawing.plain(p)} 在 {drawing.plain(feasible)} 内时的对称轴',
                description=f'对称轴只在可行范围内移动；区间 {region_text} 上整段严格{word}',
                caption=f'${_membership(latex(p), feasible)}$ 时，${region_tex}$ 上整段严格{word}', **common)
        except drawing.GraphUnavailable:
            pass
    return views


def _parameter_graphs(function, x, P, p, region, direction, feasible, shape='直线'):
    """Slide the parameter of a linear, c/x or s·x+c/x+d piece, starting where the trend is wrong."""
    from . import interaction_graphs as drawing
    word = DIR[direction]
    expression = sp.expand(function)
    if P not in expression.free_symbols:
        if not expression.is_polynomial(x):
            return {}
        graph = _line_graph(expression, x, region, '这一段的函数图像')
        return {'graph': graph, 'completion_graph': graph} if graph else {}
    ends = [end for end in (feasible.inf, feasible.sup) if end.is_finite] if feasible != sp.S.EmptySet else []
    center = ends[0] if ends else sp.Integer(0)
    low, high = sp.floor(center), sp.ceiling(center)
    window = sp.Interval(low - 2, high + 2)
    region_tex = _set_latex(region)
    candidates = [low - 1, high + 1, center]
    start = next((value for value in candidates if feasible.contains(value) is not sp.true), center)
    common = {'target': direction, 'title': f'拖动 {p}，观察这一段的{shape}',
              'description': f'拖动 {p}，观察{shape}在 {drawing.plain(region)} 上是否严格{word}'}
    try:
        graph = drawing.coefficient_explorer(
            expression, x, P, region, within=window, start=start,
            caption=f'拖动 ${p}$，观察 ${region_tex}$ 上的{shape}是否严格{word}', **common)
    except drawing.GraphUnavailable:
        return {}
    views = {'graph': graph, 'completion_graph': graph}
    allowed = sp.Intersection(feasible, window)
    if isinstance(allowed, sp.Interval) and allowed.measure > 0:
        try:
            views['completion_graph'] = drawing.coefficient_explorer(
                expression, x, P, region, within=allowed,
                start=drawing.representative_parameter(allowed),
                caption=f'${_membership(p, feasible)}$ 时，${region_tex}$ 上严格{word}', **common)
        except drawing.GraphUnavailable:
            pass
    return views


def _case_option(parameter, case):
    if case['premise'] == 'zero':
        premise = r'\text{二次项系数为 }0'
    elif case['premise'] == 'positive':
        premise = r'\text{二次项系数}>0'
    else:
        premise = r'\text{二次项系数}<0'
    return rf'{premise}\Rightarrow {_membership(parameter, case["feasible"])}'


SPLIT_ORDER = {'zero': 0, 'positive': 1, 'negative': 2}


def _split_order(cases):
    return sorted(cases, key=lambda case: SPLIT_ORDER.get(case['premise'], 3))


def _with_feedback(view, notes):
    for option in view['interaction']['options']:
        note = notes.get(option['label'][1:-1])
        if note:
            option['feedback'] = note
    return view


def _verdict(premise, kept):
    return rf'{premise}\ \text{{{"成立" if kept else "舍去"}}}'


def _line_graph(reduced, x, region, title):
    from jsonschema import ValidationError

    from . import interaction_graphs as drawing
    slope, intercept = (drawing._float(reduced.coeff(x, k)) for k in (1, 0))
    ends = [end for end in (region.inf, region.sup) if end.is_finite]
    anchors = [drawing._float(end) for end in ends] + [0.0]
    low, high = min(anchors) - 1.5, max(anchors) + 1.5
    if not region.sup.is_finite:
        high += 4
    if not region.inf.is_finite:
        low -= 4
    ys = [0.0, slope * low + intercept, slope * high + intercept]
    span = max(max(ys) - min(ys), 1.0)
    graph = {'kind': 'linear', 'params': {
        'bounds': [low, high, min(ys) - span * 0.12, max(ys) + span * 0.12],
        'xTicks': drawing.ticks(ends, low, high), 'variable': str(x),
        'interval': [drawing._float(region.inf) if region.inf.is_finite else None,
                     drawing._float(region.sup) if region.sup.is_finite else None],
        'interval_closed': [not region.left_open and bool(region.inf.is_finite),
                            not region.right_open and bool(region.sup.is_finite)],
        'points': [], 'title': title, 'description': f'{title}，区间部分加粗', 'slope': slope, 'intercept': intercept}}
    try:
        from .interaction_graph_contract import validate_graph
        return validate_graph(graph)
    except (ValueError, ValidationError):
        return None


def _quadratic_case_facts(case, compiled):
    """Monotone part, the needed axis relation and the classic mistakes for one sign of the leading term."""
    from . import interaction_graphs as drawing
    P, direction, region = compiled['p'], compiled['direction'], compiled['interval']
    sign = 1 if case['premise'] == 'positive' else -1
    lead_set = condition_values(compiled, case['premise'])
    axis = case['meta'].get('axis')
    if axis is None or lead_set == sp.S.EmptySet or not isinstance(lead_set, sp.Interval):
        return None
    beyond = (sign > 0) == (direction == 'increasing')  # the wanted part is x ≥ axis
    bound, other_end = (region.inf, region.sup) if beyond else (region.sup, region.inf)
    op, flip = (sp.Le, sp.Ge) if beyond else (sp.Ge, sp.Le)
    facts = {'sign': sign, 'lead_set': lead_set, 'axis': axis, 'beyond': beyond, 'bound': bound,
             'relation': op(axis, bound, evaluate=False) if bound.is_finite else None, 'traps': []}
    if not bound.is_finite and other_end.is_finite:
        trap = op(axis, other_end, evaluate=False)
        facts['traps'].append(('unbounded', trap, sp.simplify(_solve_relation(trap, P) & lead_set)))
    if bound.is_finite:
        num, den = sp.fraction(sp.together(axis))
        if den.free_symbols:
            sample = drawing.representative_parameter(lead_set)
            if den.subs(P, sample) < 0:
                crossed = op(num, sp.expand(bound * den), evaluate=False)
                facts['traps'].append(('unflipped', crossed, sp.simplify(_solve_relation(crossed, P) & lead_set),
                                       den))
        flipped = flip(axis, bound, evaluate=False)
        facts['traps'].append(('side', flipped, sp.simplify(_solve_relation(flipped, P) & lead_set)))
    return facts


def _split_case_card(case, compiled, p):
    """One card per sign of the leading coefficient; None falls back to the merged card."""
    from . import interaction_graphs as drawing
    X, P, x = compiled['x'], compiled['p'], compiled['variable']
    direction = compiled['direction']
    word, other = DIR[direction], DIR['decreasing' if direction == 'increasing' else 'increasing']
    region = compiled['interval']
    interval = _set_latex(region)
    premise = _premise_tex(case, compiled, p)
    lhs = _fx(compiled)
    feasible, kept = case['feasible'], case['kept']
    notes = {}

    if case['premise'] == 'zero':
        zeros = condition_values(compiled, 'zero')
        if not (isinstance(zeros, sp.FiniteSet) and len(zeros) == 1):
            return None
        reduced = sp.expand(compiled['expression'].subs(P, next(iter(zeros))))
        if reduced.free_symbols - {X}:
            return None
        slope = reduced.coeff(X, 1)
        rule = rf'{lhs}={_poly_tex(reduced, X)}'
        if slope == 0:
            right = rf'\text{{常值函数，不严格单调}}\Rightarrow {_verdict(premise, False)}'
            wrong = [rf'\text{{常值函数，严格{word}}}\Rightarrow {_verdict(premise, True)}']
            notes[wrong[0]] = '常值函数的函数值不变，既不严格递增也不严格递减。'
        else:
            rel = '>' if slope > 0 else '<'
            actual = DIR['increasing' if slope > 0 else 'decreasing']
            flipped = DIR['decreasing' if slope > 0 else 'increasing']
            right = rf'\text{{斜率}}\ {latex(slope)}{rel}0,\ \text{{严格{actual}}}\Rightarrow {_verdict(premise, kept)}'
            wrong = [rf'\text{{斜率}}\ {latex(slope)}{rel}0,\ \text{{严格{flipped}}}\Rightarrow {_verdict(premise, not kept)}']
            notes[wrong[0]] = f'一次函数斜率{"为正时严格递增" if slope > 0 else "为负时严格递减"}。'
        if kept:
            trap = rf'\text{{不是二次函数}}\Rightarrow {_verdict(premise, False)}'
            wrong.insert(0, trap)
            notes[trap] = f'题目没有说它是二次函数。${premise}$ 时函数仍然有意义，这一类必须单独判断。'
        view = choice_card(
            f'${premise}$',
            f'当 ${premise}$ 时二次项消失，${rule}$。它在 ${interval}$ 上是否严格{word}？',
            '代入后的函数', _lines([premise, rule]), '本类结论', right, wrong,
            _lines([premise, rule, right]))
        graph = _line_graph(reduced, X, region, f'{premise.replace(chr(92), "")} 时的函数图像')
        if graph is not None:
            view['graph'] = graph
            view['completion_graph'] = graph
        view['part_title'] = f'${premise}$'
        return _with_feedback(view, notes)

    facts = _quadratic_case_facts(case, compiled)
    if facts is None:
        return None
    h = latex(facts['axis'])
    opening = '开口向上' if facts['sign'] > 0 else '开口向下'
    part = rf'{x}\ge {h}' if facts['beyond'] else rf'{x}\le {h}'
    lead_set = facts['lead_set']
    if facts['relation'] is None:
        if kept:
            return None
        side = '下' if facts['beyond'] else '上'
        right = (rf'\text{{区间无{side}界，越过}}\ {x}={h}\ \text{{后严格{other}}}'
                 rf'\Rightarrow {premise}\ \text{{全部舍去}}')
    else:
        always = r'\ \text{恒成立}' if feasible == lead_set else ''
        right = rf'{_relation_tex(facts["relation"])}{always}\Rightarrow {_membership(p, feasible)}'
        reason = None
        if always:
            from sympy.calculus.util import function_range
            try:
                reason = rf'{premise}\Rightarrow {h}\in {_set_latex(function_range(facts["axis"], P, lead_set))}'
            except (NotImplementedError, ValueError, TypeError):
                reason = None
    wrong = []

    def add(text, note):
        if text != right and text not in wrong:
            wrong.append(text)
            notes[text] = note

    for kind, relation, value, *extra in facts['traps']:
        if value == feasible:
            continue
        text = rf'{_relation_tex(relation)}\Rightarrow {_membership(p, value)}'
        if kind == 'unbounded':
            add(text, f'这只保证区间开头一段落在 ${part}$ 内。区间一直延伸，越过对称轴后函数严格{other}。')
        elif kind == 'unflipped' and value != feasible:
            den = latex(extra[0])
            add(text, f'${premise}$，两边同乘负数 ${den}$ 后不等号要变向。' if extra[0] == P
                else f'${premise}$ 时 ${den}<0$，两边同乘它后不等号要变向。')
        elif kind == 'side':
            add(text, f'{opening}时，函数在 ${part}$ 这部分严格{word}，整个区间要落在这部分里。')
    if feasible == lead_set:
        add(rf'{premise}\ \text{{全部舍去}}', '这一类里有满足要求的值，拖动滑块看看。')
    else:
        add(rf'{premise}\ \text{{全部成立}}', '这一类里并非每个值都满足要求，拖动滑块找一个反例。')
    wrong = wrong[:3]
    view = choice_card(
        f'${premise}$',
        (f'当 ${premise}$ 时{opening}，对称轴 ${x}={h}$，函数在 ${part}$ 这部分严格{word}。'
         f'要使它在 ${interval}$ 上严格{word}，${p}$ 的取值是？'),
        '这一类', _lines([rf'{premise}:\ \text{{{opening}}}', rf'\text{{严格{word}的部分}}:\ {part}']),
        '本类结论', right, wrong,
        _lines([rf'{premise}:\ \text{{{opening}，对称轴}}\ {x}={h}', rf'\text{{严格{word}的部分}}:\ {part}',
                reason if facts['relation'] is not None else None,
                right if facts['relation'] is not None else
                rf'{interval}\not\subseteq \left\{{{x}\mid {part}\right\}}\Rightarrow {premise}\ \text{{舍去}}']))
    trap_values = [value for _kind, _rel, value, *_ in facts['traps']
                   if isinstance(value, sp.Interval) and value.measure > 0]
    try:
        start = drawing.representative_parameter(trap_values[0] if trap_values else lead_set)
        graph = drawing.coefficient_explorer(
            compiled['expression'], X, P, region, within=lead_set, start=start, target=direction,
            title=f'{premise} 时拖动 {p}', description=f'只在 {premise} 内拖动 {p}，观察区间上的曲线是否整段严格{word}',
            caption=f'拖动 ${p}$（只在 ${premise}$ 内），观察 ${interval}$ 上的曲线是否整段严格{word}')
        view['graph'] = graph
        view['completion_graph'] = graph
    except drawing.GraphUnavailable:
        pass
    view['part_title'] = f'${premise}$'
    return _with_feedback(view, notes)


def _split_conclusion(compiled, model, p, goal=''):
    cases = _split_order(model['cases'])
    rows, kept = [], []
    for case in cases:
        premise = _premise_tex(case, compiled, p)
        if not case['kept']:
            rows.append(rf'{premise}:\ \text{{舍去}}')
        elif case['premise'] == 'zero':
            rows.append(rf'{premise}:\ \text{{成立}}')
        else:
            rows.append(rf'{premise}:\ {_membership(p, case["feasible"])}')
        kept.append((case, premise))
    rows += _parameter_lines(compiled, p)
    restrict = model['parameter_set']
    feasible = sp.simplify(model['feasible_set'] & restrict)
    answer = _membership(p, feasible)
    wrong, notes = [], {}

    def add(value, note):
        text = _membership(p, sp.simplify(value & restrict))
        if text != answer and text not in wrong:
            wrong.append(text)
            notes[text] = note

    for case, premise in kept:
        if case['kept']:
            others = [row['feasible'] for row, _ in kept if row is not case]
            add(sp.Union(*others), f'漏掉了 ${premise}$ 这一类。')
    for case, premise in kept:
        if case['premise'] == 'zero':
            continue
        facts = _quadratic_case_facts(case, compiled)
        for _kind, _relation, value, *_ in (facts or {}).get('traps', []):
            others = [row['feasible'] for row, _ in kept if row is not case]
            add(sp.Union(value, *others), f'${premise}$ 这一类的结论不对，回到那张卡再看看。')
    for text in _wrong_memberships(p, feasible):
        if text != answer and text not in wrong:
            wrong.append(text)
    view = choice_card(
        '汇总三类',
        f'三类情况各自的结论如下。合并后，{goal}${p}$ 的取值范围是？',
        '分类结论', _lines(rows), '参数范围', answer, wrong[:3], _lines([*rows, rf'\text{{各类合并}}:\ {answer}']))
    from . import interaction_graphs as drawing
    try:
        line, = drawing.number_lines([feasible], p, title=f'{p} 的取值范围')
        view['completion_graph'] = line
    except drawing.GraphUnavailable:
        pass
    return _with_feedback(view, notes)


def _piece_relation(piece, direction, x):
    """The single parameter relation that makes one branch strictly monotone, if any."""
    expr = piece['expression']
    increasing = direction == 'increasing'
    if piece['kind'] == 'reciprocal':
        c = sp.expand(sp.cancel(expr * x)).coeff(x, 0)
        return (sp.Lt if increasing else sp.Gt)(c, 0, evaluate=False), 'reciprocal'
    if piece['kind'] == 'reciprocal_sum':
        from ..monotonicity_parameter_math import _reciprocal_sum_bound
        slope = piece['slope']
        rule = _reciprocal_sum_bound(slope, piece['region'], direction)
        if rule is None:
            return None, 'reciprocal_sum'
        # Divide c op s*b by s: the relation is stated on k=c/s against the squared end point.
        k = sp.cancel(piece['numerator'] / slope)
        op = sp.Le if (rule[0] == '<=') == bool(slope > 0) else sp.Ge
        return op(k, sp.simplify(rule[1] / slope), evaluate=False), 'reciprocal_sum'
    poly = sp.Poly(sp.expand(expr), x, domain=sp.EX)
    a, b = poly.nth(2), poly.nth(1)
    if a == 0:
        return (sp.Gt if increasing else sp.Lt)(b, 0, evaluate=False), 'constant' if b == 0 else 'linear'
    if a.free_symbols:
        return None, 'quadratic'
    axis = sp.cancel(-b / (2 * a))
    region = piece['region']
    if increasing:
        bound, op = (region.inf, sp.Le) if a > 0 else (region.sup, sp.Ge)
    else:
        bound, op = (region.sup, sp.Ge) if a > 0 else (region.inf, sp.Le)
    if bound in (-sp.oo, sp.oo):
        return None, 'quadratic'
    return op(axis, bound, evaluate=False), 'quadratic'


def _reciprocal_sum_hint(piece, direction, x):
    """Turning-point wording for s*x+c/x+d; the sum of opposite trends is never read off directly."""
    slope = piece['slope']
    k = sp.cancel(piece['numerator'] / slope)
    k_tex = latex(k)
    positive_side = bool(piece['region'].inf >= 0)
    turning = rf'\sqrt{{{k_tex}}}' if positive_side else rf'-\sqrt{{{k_tex}}}'
    ends = [end for end in (piece['region'].inf, piece['region'].sup) if end.is_finite and end != 0]
    end_text = '、'.join(f'${latex(end)}$' for end in ends)
    shape = (rf'形如 ${latex(x)}+\dfrac{{k}}{{{latex(x)}}}$ 的对勾型' if slope == 1
             else rf'形如 ${latex(slope)}\left({latex(x)}+\dfrac{{k}}{{{latex(x)}}}\right)$ 的对勾型')
    side = '只有一个方向' if not ends else f'要把转折点和端点 {end_text} 比较'
    return (f'{shape}，这里 $k={k_tex}$。${latex(x)}$ 与 $\\dfrac{{k}}{{{latex(x)}}}$ 的增减可能相反，不能直接相加判断；'
            f'$k>0$ 时转折点为 ${latex(x)}={turning}$，整段要落在转折点严格{DIR[direction]}的一侧，{side}。')


def _shape_line(expression, x, kind, direction, piece=None):
    """The facts a piece's condition is read from: opening, axis and monotone part, or k of s(x+k/x)."""
    word = DIR[direction]
    if kind == 'quadratic':
        poly = sp.Poly(sp.expand(expression), x, domain=sp.EX)
        lead = poly.nth(2)
        if lead == 0 or lead.free_symbols:
            return None
        axis = latex(sp.cancel(-poly.nth(1) / (2 * lead)))
        part = r'\ge' if (lead > 0) == (direction == 'increasing') else r'\le'
        return _lines([rf'\text{{开口向{"上" if lead > 0 else "下"}，对称轴}}\ {latex(x)}={axis}',
                       rf'\text{{严格{word}的部分}}:\ {latex(x)}{part} {axis}'])
    if kind == 'reciprocal_sum' and piece is not None:
        k = latex(sp.cancel(piece['numerator'] / piece['slope']))
        region = piece['region']
        b = region.inf
        body = rf'{latex(x)}+\dfrac{{k}}{{{latex(x)}}}'
        slope = piece['slope']
        shape = (body if slope == 1 else rf'{latex(slope)}\left({body}\right)') + rf',\ k={k}'
        # s(x+k/x) with s>0 on x>b≥0 rises past the turning point √k (none when k≤0).
        if (direction == 'increasing' and bool(piece['slope'] > 0) and b.is_finite and bool(b > 0)
                and not region.sup.is_finite):
            return _lines([shape, rf'k\le 0\ \text{{或}}\ \sqrt{{k}}\le {latex(b)}\Leftrightarrow k\le {latex(b**2)}'])
        return shape
    return None


def _region_tex(compiled_piece, x):
    from ..extremum_math import condition_set
    if compiled_piece['kind'] == 'point':
        return rf'{latex(x)}={latex(next(iter(compiled_piece["region"])))}'
    condition = compiled_piece['condition']
    if condition_set(condition, x) == compiled_piece['region']:
        return latex(condition)
    return _membership(latex(x), compiled_piece['region'])


def _parameter_lines(compiled, p):
    if not compiled['parameter_conditions']:
        return []
    return [rf'\text{{题设参数条件}}:\ {_membership(p, compiled["parameter_set"])}']


def _branch_card(piece, row, compiled, p, label, *, standalone=False):
    """The same function property is used inside a piecewise function and on its own."""
    x, direction = compiled['x'], compiled['direction']
    word = DIR[direction]
    fx = _fx(compiled)
    expr = _expr_tex(piece['expression'], x)
    if piece['kind'] == 'point':
        point = latex(next(iter(piece['region'])))
        fn = compiled.get('function') or 'f'
        actual = rf'{fn}({point})={latex(piece["value"])}'
        answer = r'\text{保留这个点的实际函数值，与相邻区间比较}'
        view = choice_card(
            '检查单点的实际值',
            f'在指定区间里，这一段只剩 ${label}$ 一个点。已知 ${actual}$，应怎样检查？',
            '这个点的实际值', actual, '检查方式', answer,
            [r'\text{单点就是常值区间，不能严格单调，所以无解}',
             r'\text{只有一个点，可以直接忽略它的函数值}'],
            _lines([actual, r'\text{单点内部没有两个输入可比较，需检查它与相邻区间的次序}']))
        view['part_title'] = f'单点 ${label}$'
        return view
    rel, kind = _piece_relation(piece, direction, x)
    what = (_reciprocal_sum_hint(piece, direction, x) if kind == 'reciprocal_sum' else
            {'linear': '一次函数：看斜率的符号。', 'constant': '函数值恒定，不能严格递增或严格递减。',
             'reciprocal': r'形如 $\dfrac{c}{x}+d$：看倒数项系数 $c$ 的符号。',
             'quadratic': '二次函数：整个区间要落在对称轴同一侧。'}[kind])
    if rel is None:
        answer, wrong = _membership(p, row['feasible']), _wrong_memberships(p, row['feasible'])
    else:
        answer, wrong = _condition_options(rel, compiled['p'], p)
    title = ({'linear': '斜率与增减', 'constant': '检查常值函数',
              'reciprocal': '倒数项与增减', 'reciprocal_sum': '转折点与指定区间',
              'quadratic': '对称轴与指定区间'}[kind] if standalone else f'${label}$ 这一段')
    subject = '函数' if standalone else '这一段'
    view = choice_card(
        title,
        f'在 ${label}$ 上 ${fx}={expr}$，{what}要使{subject}严格{word}，${p}$ 应满足什么？',
        '函数与区间' if standalone else '这一段', rf'{fx}={expr},\ {label}',
        '参数条件' if standalone else '本段条件', answer, wrong,
        _lines([rf'{fx}={expr},\ {label}', _shape_line(piece['expression'], x, kind, direction, piece),
                {'linear': r'\text{斜率}\ ', 'reciprocal': r'\text{倒数项系数}\ '}.get(kind, '') + answer
                if rel is not None else answer]))
    if not standalone:
        view['part_title'] = f'${label}$ 段'
    if kind == 'quadratic':
        view.update(_axis_graphs(piece['expression'], x, compiled['p'], piece['region'], direction, row['feasible']))
    else:
        shape = '直线' if kind in ('linear', 'constant') else '曲线'
        view.update(_parameter_graphs(piece['expression'], x, compiled['p'], p, piece['region'],
                                      direction, row['feasible'], shape))
    return view


def _piecewise_views(phase, compiled, model, p):
    x = compiled['x']
    direction = compiled['direction']
    word = DIR[direction]
    pieces = compiled['pieces']
    fn = compiled.get('function') or 'f'
    region = _set_latex(compiled['interval'])
    labels = [_region_tex(piece, x) for piece in pieces]

    if phase == 'pieces':
        return [_branch_card(piece, row, compiled, p, label)
                for piece, row, label in zip(pieces, model['pieces'], labels)]

    if phase == 'join':
        views = []
        for index, (join, row) in enumerate(zip(compiled['joins'], model['joins'])):
            b = latex(join['point'])
            before, after = labels[index], labels[index + 1]
            owner_label = after if join['owner'] == 'right' else before
            left_value, right_value = row['left_value'], row['right_value']
            left_expr = _expr_tex(pieces[index]['expression'], x)
            right_expr = _expr_tex(pieces[index + 1]['expression'], x)
            if row.get('zero_terms'):
                zeros = [rf'{latex(term)}=0' for term in row['zero_terms']]
                stem = _lines([
                    rf'\text{{分界点}}\ {x}=0\ \text{{有实际函数值}}',
                    r'\text{倒数项系数不为零时，靠近分界点的无界变化与整体严格单调矛盾}',
                    *[rf'\text{{因此需要}}\ {term}' for term in zeros],
                    rf'\text{{系数为零后，接缝两侧的值为}}\ {latex(left_value)},\ {latex(right_value)}',
                    _relation_tex((sp.Le if direction == 'increasing' else sp.Ge)(
                        left_value, right_value, evaluate=False)),
                ])
                answer = _membership(p, row['feasible'])
                view = choice_card(
                    f'检查分界点 ${x}=0$',
                    f'分界点 ${x}=0$ 属于 ${owner_label}$。先处理倒数项，再检查接缝处的大小关系，${p}$ 应满足什么？',
                    '接缝处需要满足的条件', stem, '跨段条件', answer,
                    _wrong_memberships(p, row['feasible']), _lines([stem, answer]))
                view['part_title'] = f'分界点 ${x}=0$'
                views.append(view)
                continue
            if join['owner'] == 'right':
                left_line = rf'{left_expr}\ \text{{在}}\ {x}\to {b}\ \text{{时趋近}}\ {latex(left_value)}\ (\text{{取不到}})'
                right_line = rf'{fn}({b})={latex(right_value)}'
            else:
                left_line = rf'{fn}({b})={latex(left_value)}'
                right_line = rf'{right_expr}\ \text{{在}}\ {x}\to {b}\ \text{{时趋近}}\ {latex(right_value)}\ (\text{{取不到}})'
            rel = (sp.Le if direction == 'increasing' else sp.Ge)(left_value, right_value, evaluate=False)
            answer, wrong = _condition_options(rel, compiled['p'], p)
            continuity = sp.Eq(left_value, right_value, evaluate=False)
            joint = rf'{_relation_tex(continuity)}\Rightarrow {_membership(p, _solve_relation(continuity, compiled["p"]))}'
            if (_solve_relation(continuity, compiled['p']) != _solve_relation(rel, compiled['p'])
                    and joint != answer and joint not in wrong):
                wrong = [joint, *wrong][:3]
            stem = _lines([left_line, right_line])
            side, open_value = (('^-', left_value) if join['owner'] == 'right' else ('^+', right_value))
            value_line = (rf'{fn}({b})={latex(right_value)}' if join['owner'] == 'right'
                          else rf'{fn}({b})={latex(left_value)}')
            proof = _lines([rf'{x}\to {b}{side}:\ {fn}({x})\to {latex(open_value)}', value_line, answer])
            view = choice_card(
                f'分界点 ${x}={b}$ 两侧',
                (f'${x}={b}$ 属于 ${owner_label}$ 这一段。检查完各区间内的增减后，'
                 f'从 ${before}$ 走到 ${after}$ 时函数值的大小关系也不能反过来。两侧的值应满足什么？'),
                '两侧的值', stem,
                '跨段条件', answer, wrong,
                proof,
            )
            view['part_title'] = f'分界点 ${x}={b}$'
            views.append(view)
        return views

    if phase == 'conclude':
        sources = [rf'{label}\ \text{{段}}:\ {_membership(p, row["feasible"])}'
                   for label, row in zip(labels, model['pieces'])]
        sources += [rf'\text{{分界点 }}{latex(x)}={latex(join["point"])}:\ {_membership(p, join["feasible"])}'
                    for join in model['joins']]
        sources += _parameter_lines(compiled, p)
        answer = _membership(p, model['feasible_set'])
        # Each distractor drops exactly one confirmed condition: all breakpoints, then one branch.
        conditions = [row['feasible'] for row in model['pieces']]
        omissions = [sp.Intersection(*conditions)]
        omissions += [sp.Intersection(sp.S.Reals, *conditions[:i], *conditions[i + 1:],
                                      *(join['feasible'] for join in model['joins']))
                      for i in range(len(conditions))]
        wrong = []
        for candidate in omissions:
            text = _membership(p, sp.simplify(candidate))
            if text != answer and text not in wrong:
                wrong.append(text)
        wrong += [w for w in _wrong_memberships(p, model['feasible_set']) if w not in wrong]
        return [choice_card(
            '合并全部条件',
            f'这些条件要同时成立，才能保证 ${fn}$ 在 ${region}$ 上严格{word}。${p}$ 的取值范围是？',
            '已确认条件', _lines(sources),
            '参数范围', answer, wrong[:3],
            _lines([*sources, rf'\text{{取交集}}:\ {answer}']),
        )]
    return []


PREMISE_TEX = {'zero': '{p}=0', 'negative': '{p}<0', 'positive': '{p}>0'}


def _premise_tex(case, compiled, p):
    """Premise on the inner leading coefficient, named by the coefficient itself."""
    leading = compiled['leading']
    if leading == compiled['p']:
        return PREMISE_TEX[case['premise']].format(p=p)
    rel = {'zero': '=', 'negative': '<', 'positive': '>'}[case['premise']]
    return rf'{latex(leading)}{rel}0'


def _radical_views(phase, compiled, model, p):
    x = compiled['x']
    word = DIR[compiled['direction']]
    other = DIR['decreasing' if compiled['direction'] == 'increasing' else 'increasing']
    fn = compiled.get('function') or 'f'
    inner_fn = 'g' if fn != 'g' else 'h'
    gx, fx = rf'{inner_fn}({latex(x)})', rf'{fn}({latex(x)})'
    interval = _set_latex(compiled['interval'])
    inner = _expr_tex(compiled['inner'], x)
    g_def = rf'{gx}={inner}'

    if phase == 'outer':
        answer = rf'{inner_fn}\ \text{{在}}\ {interval}\ \text{{上严格{word}，且}}\ {gx}\ge 0'
        wrong = [rf'{inner_fn}\ \text{{在}}\ {interval}\ \text{{上严格{other}，且}}\ {gx}\ge 0',
                 rf'{inner_fn}\ \text{{在}}\ {interval}\ \text{{上严格{word}即可}}',
                 rf'\text{{只需区间端点处}}\ {gx}\ge 0']
        stem = _lines([rf'{fx}=\sqrt{{{gx}}}', g_def])
        return [choice_card(
            '转化为内层条件',
            (f'$\\sqrt{{u}}$ 在 $[0,+\\infty)$ 上严格递增，而且区间内每个数都要能代入。'
             f'要使 ${fx}$ 在 ${interval}$ 上严格{word}，内层 ${gx}$ 应满足什么？参数 ${p}$ 尚未求出。'),
            '内外两层', stem, '内层要求', answer, wrong,
            _lines([stem, r'\sqrt{u}\ \text{在}\ [0,+\infty)\ \text{上严格递增}', rf'\Rightarrow {answer}']))]

    if phase == 'inner' and compiled['needs_leading_split']:
        inner_compiled = dict(compiled, expression=compiled['inner'], function=inner_fn)
        cards = [_split_case_card(case, inner_compiled, p) for case in _split_order(model['cases'])]
        if all(cards):
            summary = _split_conclusion(inner_compiled, dict(model, feasible_set=model['monotone_set']), p,
                                        f'使内层 ${inner_fn}$ 在 ${interval}$ 上严格{word}的')
            summary['part_title'] = '汇总三类'
            for card in [*cards, summary]:
                card['title'] = '内层按二次项系数分类'
            return [*cards, summary]

    if phase == 'inner':
        views = []
        for case in model['cases']:
            premise = _premise_tex(case, compiled, p)
            if case['premise'] == 'zero':
                hint = ('内层为常值函数，不能严格递增或严格递减。' if case['kind'] == 'constant'
                        else '内层为一次函数，看斜率的符号。')
                region = condition_values(compiled, 'zero')
            elif case['premise'] == 'positive':
                hint = '开口向上，整个区间要落在对称轴严格' + word + '的一侧。'
                region = condition_values(compiled, 'positive')
            else:
                hint = '开口向下，整个区间要落在对称轴严格' + word + '的一侧。'
                region = condition_values(compiled, 'negative')
            answer = _membership(p, case['feasible'])
            wrong = []
            for candidate in (region, sp.S.EmptySet, sp.S.Reals, *_interval_neighbours(case['feasible'])):
                text = _membership(p, candidate)
                if text != answer and text not in wrong:
                    wrong.append(text)
            relation = None
            if case['kind'] == 'quadratic' and 'axis' in case['meta']:
                region_ = compiled['interval']
                sign = case['meta']['leading_sign']
                increasing = compiled['direction'] == 'increasing'
                bound, op = ((region_.inf, r'\le') if sign > 0 else (region_.sup, r'\ge')) if increasing \
                    else ((region_.sup, r'\ge') if sign > 0 else (region_.inf, r'\le'))
                if bound.is_finite:
                    relation = rf'{latex(case["meta"]["axis"])}{op}{latex(bound)}'
            split = compiled['needs_leading_split']
            title = f'${premise}$' if split else '判断内层函数的增减条件'
            prefix = f'当 ${premise}$ 时，' if split else ''
            stem = _lines([g_def, premise if split else None])
            view = choice_card(
                title,
                f'{prefix}{hint}要使 ${inner_fn}$ 在 ${interval}$ 上严格{word}，${p}$ 的取值是？',
                '这一类', stem, '本类条件', answer, wrong[:3],
                _lines([stem, relation, answer]))
            view['part_title'] = title
            views.append(view)
        return views

    if phase == 'domain':
        candidate = sp.simplify(model['monotone_set'] & model['parameter_set'])
        end = model['minimum_end']
        if model['minimum_value'] is None:
            return []
        value = latex(model['minimum_value'])
        rel = sp.Ge(model['minimum_value'], 0, evaluate=False)
        answer, wrong = _condition_options(rel, compiled['p'], p)
        where = (f'最小值在 ${x}={latex(end)}$ 处取得' if model['minimum_attained']
                 else f'函数值在 ${x}\\to {latex(end)}$ 时趋近最小的值（取不到）')
        stem = _lines([g_def, _membership(p, candidate), rf'{inner_fn}({latex(end)})={value}'])
        return [choice_card(
            '整段能开方',
            (f'当 ${_membership(p, candidate)}$ 时，${inner_fn}$ 在 ${interval}$ 上严格{word}，{where}。'
             f'要使整段 ${gx}\\ge 0$，${p}$ 应满足什么？'),
            '最小的函数值', stem, '定义条件', answer, wrong,
            _lines([g_def, rf'{_membership(p, candidate)}:\ {inner_fn}\ \text{{严格{word}}}',
                    (rf'\min {inner_fn}={inner_fn}({latex(end)})={value}' if model['minimum_attained']
                     else rf'{inner_fn}(x)>{inner_fn}({latex(end)})={value}'), answer]))]

    if phase == 'conclude':
        sources = [rf'\text{{内层严格{word}}}:\ {_membership(p, model["monotone_set"])}',
                   rf'\text{{整段}}\ {gx}\ge 0:\ {_membership(p, model["nonnegative_set"])}']
        sources += _parameter_lines(compiled, p)
        answer = _membership(p, model['feasible_set'])
        wrong = []
        for candidate in (model['monotone_set'], model['nonnegative_set']):
            text = _membership(p, candidate)
            if text != answer and text not in wrong:
                wrong.append(text)
        wrong += [w for w in _wrong_memberships(p, model['feasible_set']) if w not in wrong]
        return [choice_card(
            '合并全部条件',
            f'这些条件要同时成立，才能保证 ${fn}$ 在 ${interval}$ 上严格{word}。${p}$ 的取值范围是？',
            '已确认条件', _lines(sources),
            '参数范围', answer, wrong[:3],
            _lines([*sources, rf'\text{{取交集}}:\ {answer}']))]
    return []


def condition_values(compiled, premise):
    """Parameter values satisfying one premise on the inner leading coefficient."""
    from ..extremum_math import condition_set
    leading, p = compiled['leading'], compiled['p']
    rel = {'zero': sp.Eq, 'negative': sp.Lt, 'positive': sp.Gt}[premise](leading, 0)
    return condition_set(rel, p)


def _interval_neighbours(value):
    if not isinstance(value, sp.Interval):
        return []
    return [sp.Interval(value.start, value.end, left_open=not value.left_open, right_open=value.right_open)]


def phase_views(values):
    from ..monotonicity_parameter_math import _model

    description = _load(values['description'], 'source', 'parameter')
    model = _load(values['mono_parameter_result'], 'feasible_set', 'cases')
    phase = values.get('phase', 'conclude')
    compiled = _model(description)
    p = compiled['parameter']
    direction = compiled['direction']
    direction_text = DIR[direction]
    interval = _set_latex(compiled['interval'])

    if phase == 'prepare':
        requirement = _requirement_tex(compiled, interval)
        opposite = 'decreasing' if direction == 'increasing' else 'increasing'
        subject = _fx(compiled)
        wrong = [
            _requirement_tex(dict(compiled, direction=opposite), interval),
            rf'{subject}\ \text{{的单调区间恰为}}\ {interval}',
        ]
        basis = _basis_tex(compiled)
        if compiled['structure'] != 'piecewise':
            definition = rf'{_fx(compiled)}={_expr_tex(compiled["expression"], compiled["x"])}'
        else:
            rows = r'\\'.join(rf'{_expr_tex(piece["expression"], compiled["x"])},&{latex(piece["condition"])}'
                              for piece in compiled['pieces'])
            definition = rf'{_fx(compiled)}=\begin{{cases}}{rows}\end{{cases}}'
        if basis is not None:
            u, v = _basis_input_tex(compiled['basis'])
            stem = _lines([definition, rf'\text{{任意 }}{u},{v}\in {interval},\ {u}\ne {v}:\ {basis}'])
            question = f'原题给出差式恒{"负" if "<0" in basis else "正"}。这说明函数在指定区间上怎样变化？参数 ${p}$ 尚未求出。'
        else:
            stem = definition
            question = f'本题要求函数在指定区间上怎样变化？参数 ${p}$ 尚未求出。'
        stem = _lines([stem, *_parameter_lines(compiled, p)])
        if compiled['p'] not in compiled['expression'].free_symbols:
            stem = _lines([stem, rf'\text{{指定区间内的表达式不含参数}}\ {p}'])
        return [choice_card('读清单调性要求', question, '题设', stem, '要求', requirement,
                            wrong, _lines([stem, (rf'\Rightarrow {requirement}' if basis else requirement)]))]

    if compiled['structure'] == 'piecewise':
        return _piecewise_views(phase, compiled, model, p)
    if compiled['structure'] == 'radical':
        return _radical_views(phase, compiled, model, p)

    x = compiled['variable']
    expr = _expr_tex(compiled['expression'], compiled['x'])
    if phase == 'classify' and compiled.get('needs_leading_split'):
        cards = [_split_case_card(case, compiled, p) for case in _split_order(model['cases'])]
        if all(cards):
            for card in cards:
                card['title'] = '按二次项系数分类'
            return cards
        answer = _membership(p, model['unrestricted_set'])
        stem = _lines([
            _requirement_tex(compiled, interval),
            r'\text{按二次项系数分类：}=0,\ <0,\ >0',
            *[_case_option(p, case) for case in model['cases']],
        ])
        return [choice_card(
            '参数分类',
            f'二次项系数可能为零。分别判断后，${p}$ 的取值范围是？',
            '分类讨论', stem,
            '合并', answer,
            _wrong_memberships(p, model['unrestricted_set']),
            _lines([stem, answer]),
        )]

    if phase == 'conclude' and compiled.get('needs_leading_split'):
        view = _split_conclusion(compiled, model, p)
        if view is not None:
            return [view]

    if phase == 'axis':
        piece = compiled['pieces'][0]
        if piece['kind'] != 'polynomial' or piece['leading'] == 0:
            return [_branch_card(piece, {'feasible': model['unrestricted_set']}, compiled, p,
                                 _membership(x, compiled['interval']), standalone=True)]
        relation = _axis_condition(compiled, model)
        if relation is None:
            return []
        quad = next((c for c in model['cases'] if c['kind'] == 'quadratic' and c['kept']), None)
        target = quad['feasible'] if quad else model['feasible_set']
        answer = rf'{relation}\Rightarrow {_membership(p, target)}'
        wrong = [
            rf'{relation}\Rightarrow {_membership(p, sp.S.EmptySet)}',
            *_wrong_memberships(p, target)[:2],
        ]
        view = choice_card(
            '对称轴与指定区间',
            f'要让函数 ${_fx(compiled)}={expr}$ 在整个 ${interval}$ 上严格{direction_text}，'
            f'对称轴应满足什么？由此得到 ${p}$ 的条件。',
            f'指定{direction_text}区间', interval,
            '参数条件', answer,
            wrong,
            _lines([rf'{_fx(compiled)}={expr}', _shape_line(compiled['expression'], compiled['x'], 'quadratic', direction),
                    answer]),
        )
        view.update(_axis_graphs(compiled['expression'], compiled['x'], compiled['p'],
                                 compiled['interval'], direction, target))
        return [view]

    if phase == 'conclude':
        parts = []
        for case in model['cases']:
            if case['kept']:
                parts.append(_case_option(p, case) if compiled.get('needs_leading_split')
                             else _membership(p, case['feasible']))
        parts += _parameter_lines(compiled, p)
        left = _lines(parts or [_requirement_tex(compiled, interval)])
        answer = _membership(p, model['feasible_set'])
        return [choice_card(
            '回到原目标',
            f'合并全部成立的参数条件，${p}$ 的取值范围是？',
            '已确认条件', left,
            '参数范围', answer,
            _wrong_memberships(p, model['feasible_set']),
            _lines([*parts, answer]),
        )]

    return []


def presentation(values):
    views = phase_views(values)
    if not views:
        phase = values.get('phase', 'conclude')
        return {
            'formula_title': phase,
            'formula_explanation': r'\text{（本步折叠）}',
            'derivation_caption': phase,
            'derivation_left_label': '—',
            'derivation_left_math': r'\text{（折叠）}',
            'derivation_left_note': '',
            'derivation_right_label': '—',
            'derivation_right_math': r'\text{（折叠）}',
        }
    view = views[0]
    left, right = view['derivation']['items']
    return {
        'formula_title': view['title'],
        'formula_explanation': '\n\n'.join('$$'+v['proof']+'$$' for v in views),
        'derivation_caption': view['title'],
        'derivation_left_label': left['label'],
        'derivation_left_math': left['math'],
        'derivation_left_note': '',
        'derivation_right_label': right['label'],
        'derivation_right_math': right['math'],
    }


def compile_mono_parameter(seeds, interaction_id):
    from .interaction import NotInteractive

    seed, = seeds
    views = phase_views(decode_value(seed['values']))
    if not views:
        raise NotInteractive('folded')
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        interaction = deepcopy(view['interaction'])
        interaction['options'].sort(
            key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        part = {
            'id': f'{interaction_id}#{index}',
            'title': view.get('part_title', view['title']),
            'question': view['question'],
            'interaction': interaction,
            'expected_answer': view['expected_answer'],
            'feedback': view['feedback'],
            'submit_label': '确认判断',
            'stem_board': board,
            'completion_board': view['derivation'],
        }
        part.update({key: view[key] for key in ('graph', 'completion_graph') if key in view})
        parts.append(part)
    return {'parts': parts, 'diagnostics': []}
