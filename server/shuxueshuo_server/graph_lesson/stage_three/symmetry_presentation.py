"""FP-T3 R2–R3 cards: rewrite opposite inputs by parity, use stated identities at opposite inputs, combine."""
import re
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..parity_extension_math import ARGUMENT, region
from ..stage_one.function_domain import expression_latex
from ..symmetry_value_math import _rows, _solve_linear, linear, names_of, rule_of, solve
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .parity_extension_presentation import _printed, _when, range_latex
from .parity_parameter_presentation import PROPERTY, _display_ast, board_lines
from .trajectory import decode_value


def _call(F, c):
    return f'{F}({latex(c)})'


def _source_latex(ast, x):
    """The printed combination with its own calls, signs and repeats."""
    op = ast[0]
    if ast == ARGUMENT:
        return x
    if op == 'ref':
        return ast[1].rsplit(':', 1)[-1]
    if op == 'function_call':
        return _source_latex(ast[1], x) + '(' + _source_latex(ast[2], x) + ')'
    if op == 'number':
        return ast[1]
    if ast[:2] == ['call', 'sqrt']:
        return r'\sqrt{' + _source_latex(ast[2], x) + '}'
    if ast[:2] == ['call', 'abs']:
        return r'\left|' + _source_latex(ast[2], x) + r'\right|'
    if op == 'interval':
        return ('[' if ast[1] else '(') + _source_latex(ast[3], x) + ',' + _source_latex(ast[4], x) + \
            (']' if ast[2] else ')')
    if op == 'set':
        return r'\{' + ','.join(_source_latex(a, x) for a in ast[1:]) + r'\}'
    if op == 'infinity':
        return r'+\infty' if ast[1] > 0 else r'-\infty'
    if op == 'real':
        return r'\mathbf{R}'
    if op in ('∪', '∩', 'set_difference'):
        symbol = {'∪': r'\cup ', '∩': r'\cap ', 'set_difference': r'\setminus '}[op]
        return _source_latex(ast[1], x) + symbol + _source_latex(ast[2], x)
    if op == 'neg':
        inner = _source_latex(ast[1], x)
        return '-' + (rf'\left({inner}\right)' if ast[1][0] in ('+', '-') else inner)
    if op in ('+', '-'):
        right = _source_latex(ast[2], x)
        if op == '-' and ast[2][0] in ('+', '-'):
            right = rf'\left({right}\right)'
        return _source_latex(ast[1], x) + op + right
    if op == '*':
        parts = [rf'\left({_source_latex(a, x)}\right)'
                 if a[0] in ('+', '-') or a[0] == 'neg' and (i or a[1][0] in ('+', '-')) else _source_latex(a, x)
                 for i, a in enumerate(ast[1:])]
        return parts[0] + (r'\cdot ' if ast[2][0] in ('number', 'neg') else '') + parts[1]
    if op == '/':
        return rf'\frac{{{_source_latex(ast[1], x)}}}{{{_source_latex(ast[2], x)}}}'
    if op == '^' and ast[2][0] == 'number':
        base = _source_latex(ast[1], x)
        return (base if ast[1][0] in ('number', 'ref') or ast[1] == ARGUMENT else rf'\left({base}\right)') + \
            '^{' + ast[2][1] + '}'
    raise ValueError('symmetry_value.display_unsupported')


def _combination(terms, constant):
    """Σ k·F(c) + d with textbook signs; an empty combination is 0."""
    text = ''
    for (F, c), k in terms:
        if k == 0:
            continue
        magnitude = '' if abs(k) == 1 else latex(abs(k))
        text += ('-' if k < 0 else ('+' if text else '')) + magnitude + _call(F, c)
    if constant != 0 or not text:
        text += ('-' if constant < 0 else ('+' if text else '')) + latex(abs(constant))
    return text


def _rewritten(model, signs=None, zero=None):
    """The target as a combination of the inputs it is rewritten to; signs/zero swap in a misconception."""
    signs = model['signs'] if signs is None else signs
    constant = model['target_constant'] - sum(
        (c['coefficient'] * c['value'] for c in model['calls'] if c['value'] is not None), sp.S.Zero)
    terms = {}
    for call in model['calls']:
        k = call['coefficient']
        if call['route'] == 'zero':
            constant += k * (sp.S.Zero if zero is None else zero)
            continue
        key = (call['function'], call['image'])
        factor = sp.S.One if call['image'] == call['input'] else sp.S(signs[call['function']])
        terms[key] = terms.get(key, 0) + k * factor
    return [(key, k) for key, k in terms.items() if k != 0], constant


def _known_values(model):
    """F at each input the rule was substituted at."""
    return {(c['function'], c['image']): c['value'] / c['factor'] for c in model['calls']
            if c['route'] in ('rule', 'mirrored_rule')}


def _keys(model):
    return [tuple(k) for k in model['keys']]


def _vector(model, terms):
    """Coefficients over the unknown representatives, plus the known part; None if a value is outside them."""
    known, keys = _known_values(model), _keys(model)
    vector, d = [sp.S.Zero] * len(keys), sp.S.Zero
    for (F, c), k in terms:
        if (F, c) in known:
            d += k * known[(F, c)]
        elif (F, c) in keys:
            vector[keys.index((F, c))] += k
        elif (F, -c) in keys:
            vector[keys.index((F, -c))] += k * model['signs'][F]
        else:
            return None, None
    return vector, d


def _value(model, terms, constant, equations=None):
    """The value of a combination under the given equations, or None when they do not determine it."""
    equations = model['equations'] if equations is None else equations
    vector, d = _vector(model, terms)
    if vector is None:
        return None
    if not any(vector):
        return sp.nsimplify(d + constant)
    rows = [e['coefficients'] for e in equations]
    m = _solve_linear(sp.Matrix(rows).T.tolist(), len(rows), vector) if rows else None
    if m is None:
        return None
    return sp.nsimplify(sum((mi * e['constant'] for mi, e in zip(m, equations)), sp.S.Zero) + d + constant)


def _implied(model, vector, constant):
    rows = [e['coefficients'] for e in model['equations']]
    m = _solve_linear(sp.Matrix(rows).T.tolist(), len(rows), vector) if rows else None
    return m is not None and sp.simplify(sum((mi * e['constant'] for mi, e in zip(m, model['equations'])),
                                             sp.S.Zero) - constant) == 0


def _substitution(rule_text, x, c):
    shown = latex(c) if c >= 0 and c.is_Integer else rf'\left({latex(c)}\right)'
    text = re.sub(rf'(?<=[0-9}}])\s*{re.escape(x)}(?![A-Za-z])', lambda _: r'\cdot ' + shown, rule_text)
    return re.sub(rf'(?<![A-Za-z\\]){re.escape(x)}(?![A-Za-z])', lambda _: shown, text)


def _source(d):
    rule = d['rule_ast']
    x = d['variable']
    identities = []
    for identity in d['identities']:
        left, right = identity['ast'][1:3]
        free = [side for side in (left, right) if 'function_call' not in str(side)]
        identities.append({'text': _source_latex(left, x) + '=' + _source_latex(right, x),
                           'range': None if identity['domain_ast'] is None else region(identity['domain_ast']),
                           'h': _source_latex(free[0], x) if len(free) == 1 else None})
    parities = [(F['name'], PROPERTY[F['property']]) for F in d['functions']]
    return {'x': x, 'f': d['function'], 'parities': parities,
            'parity': '，'.join(f'${F}$ 是{word}' for F, word in parities),
            'target': _source_latex(d['target_ast'], x),
            'rule': None if rule is None else _printed(expression_latex(_display_ast(d['rule_ast']), x), x),
            'printed_known': None if rule is None else region(d['rule_domain_ast']),
            'equations': [_source_latex(r['ast'][1], x) + '=' + _source_latex(r['ast'][2], x)
                          for r in d['value_equations']],
            'identities': identities}


def _given_rows(s):
    rows = [] if s['rule'] is None else [_when(s['printed_known'], s['x']) + rf"{s['f']}({s['x']})=" + s['rule']]
    rows += [*s['equations'], *((_when(i['range'], s['x']) if i['range'] is not None else '') + i['text']
                               for i in s['identities'])]
    return [*rows, *(rf'{F}\text{{ 是{word}}}' + (rf'\text{{，}}{F}(0)=0' if F in s.get('zero', ()) else '')
                     for F, word in s['parities'])]


def _rewrite_lines(model, s):
    lines = [] if s.get('instance') is None else [s['target'] + '=' + s['instance']]
    for call in model['calls']:
        F, c = call['function'], call['input']
        if call['route'] == 'zero':
            both = any(f['name'] == F and f['property'] == 'both' for f in model['description']['functions'])
            if both:
                lines.append(rf'{_call(F, -c)}={_call(F, c)},\quad {_call(F, -c)}=-{_call(F, c)}')
            lines.append(rf'{_call(F, c)}=0')
        elif call['image'] == -c:
            lines.append(rf'{_call(F, c)}={"" if call["factor"] == 1 else "-"}{_call(F, -c)}')
    terms, constant = _rewritten(model)
    lines.append(s['target'] + '=' + _combination(terms, constant))
    return lines


def _reduced(model, equation):
    return _combination([(k, a) for k, a in zip(_keys(model), equation['coefficients']) if a != 0], 0) + \
        '=' + latex(equation['constant'])


def _instances(model, s):
    """(row index, printed instance, reduced form) for each use of a stated identity."""
    rows = _rows(model['description'])
    out = []
    for index, ((source_ref, at, terms, b), equation) in enumerate(zip(rows, model['equations'])):
        if at is None:
            continue
        identity = s['identities'][[i['source_ref'] for i in model['description']['identities']].index(source_ref)]
        value = latex(sp.nsimplify(b))
        shown = (_substitution(identity['h'], s['x'], at) + '=' if identity['h'] is not None else '') + value
        out.append((index, _combination(list(terms.items()), 0) + '=' + shown, _reduced(model, equation)))
    return out


def _instance_lines(model, s):
    lines = []
    for _, printed, reduced in _instances(model, s):
        lines.append(printed if printed.split('=', 1)[0] == reduced.split('=', 1)[0]
                     else printed + r'\Rightarrow ' + reduced)
    return lines


def _evaluation_lines(model, s):
    lines = []
    for (F, c), v in _known_values(model).items():
        lines.append(_call(F, c) + '=' + _substitution(s['rule'], s['x'], c) + '=' + latex(v))
    return lines


def _combine_line(model, s):
    """Rewritten target → known values filled in → the given combinations → the value."""
    terms, constant = _rewritten(model)
    chain = [s['target'], *([] if s.get('instance') is None else [s['instance']]), _combination(terms, constant)]
    known = _known_values(model)
    rest = [(c, k) for c, k in terms if c not in known]
    filled = constant + sum((k * known[c] for c, k in terms if c in known), sp.S.Zero)
    if len(rest) < len(terms):
        chain.append(_combination(rest, filled))
    used = [(m, e) for m, e in zip(model['multipliers'] or [], model['equations']) if m != 0]
    if used and rest:
        pieces = ''
        for m, e in used:
            row = [(k, a) for k, a in zip(_keys(model), e['coefficients']) if a != 0]
            if len(row) == 1:
                given, m = _call(*row[0][0]), m * row[0][1]
            else:
                given = rf'\left({_combination(row, 0)}\right)'
            prefix = '' if m == 1 else '-' if m == -1 else latex(m)
            pieces += ('' if not pieces or prefix.startswith('-') else '+') + prefix + given
        chain.append(pieces + ('' if filled == 0 else ('+' if filled > 0 else '-') + latex(abs(filled))))
    chain.append(latex(model['value']))
    return '='.join(dict.fromkeys(chain))


def _answer(model, s):
    if model['value'] is not None:
        return s['target'] + '=' + latex(model['value'])
    return s['target'] + r'\text{ 不能唯一确定}'


def _misreadings(model, s, rule):
    """Opposite parity signs, the whole value negated, and an odd f(0) read from the one-sided rule."""
    terms, constant = _rewritten(model)
    rows = [_rewritten(model, signs={F: -v for F, v in model['signs'].items()}),
            ([(c, -k) for c, k in terms], -constant)]
    if rule is not None and any(c['route'] == 'zero' for c in model['calls']):
        at_zero = rule.subs(sp.Symbol(s['x'], real=True), 0)
        if at_zero != 0:
            rows.append(_rewritten(model, zero=at_zero))
    return rows


def _instance_misreadings(model, index):
    """For one identity instance: parity ignored, parities swapped, or the right side left at the opposite input."""
    source_ref, at, terms, _b = _rows(model['description'])[index]
    keys = _keys(model)
    out = []
    for flip in ('ignore', 'swap'):
        vector = [sp.S.Zero] * len(keys)
        for (F, c), k in terms.items():
            if (F, c) in keys:
                vector[keys.index((F, c))] += k
            elif (F, -c) in keys:
                vector[keys.index((F, -c))] += k * (1 if flip == 'ignore' else -model['signs'][F])
            else:
                return out
        out.append((vector, model['equations'][index]['constant']))
    twin = next((e for e in model['equations'] if e['source_ref'] == source_ref and e['instance'] == -at), None)
    if twin is not None:
        out.append((model['equations'][index]['coefficients'], twin['constant']))
    return out


def _identity_card(model, s):
    """The identity at an opposite input, rewritten to the representative inputs."""
    rows = _rows(model['description'])
    keys = _keys(model)
    chosen = next(((i, printed, reduced) for i, printed, reduced in _instances(model, s)
                   if any((F, c) not in keys for (F, c) in rows[i][2])), None)
    if chosen is None:
        return None, []
    index, printed, reduced = chosen
    at = rows[index][1]
    equation = model['equations'][index]
    wrong, swaps = [], []
    for vector, constant in _instance_misreadings(model, index):
        text = _combination([(k, a) for k, a in zip(keys, vector) if a != 0], 0) + '=' + latex(constant)
        if text == reduced or text in wrong or _implied(model, vector, constant):
            continue
        wrong.append(text)
        swaps.append((index, vector, constant))
    identity = s['identities'][[i['source_ref'] for i in model['description']['identities']]
                               .index(equation['source_ref'])]
    inputs = sorted({abs(c) for (F, c) in rows[index][2]})
    shown = '或'.join(f'${latex(c)}$' for c in inputs)
    others = [p for i, p, r in _instances(model, s) if i != index and p.split('=', 1)[0] == r.split('=', 1)[0]]
    question = (f'已知 ${identity["text"]}$，且 {s["parity"]}。把 ${s["x"]}={latex(at)}$ 代入已知关系，'
                f'再用奇偶性把其中的函数值都改写成输入为 {shown} 的函数值，得到什么等式？')
    view = choice_card(f'代入 ${s["x"]}={latex(at)}$，再用奇偶性改写', question, '已知条件',
                       _lines([*_given_rows(s), *others]),
                       '$' + printed.split('=', 1)[0] + '$ 改写后的等式', reduced, wrong[:3], _lines(_instance_lines(model, s)))
    return view, swaps


def _parameter(base, model):
    candidates = model['borrow']['candidates']
    return base['parameter']['name'], [row['parameter_value'] for row in candidates]


def _borrow_card(base, model, s):
    """The domain parameter returned by the subtask, and where the printed rule then applies."""
    p, values = _parameter(base, model)
    x, output = s['x'], model['borrow']['output']
    domain = _source_latex(base['domain_ast'], x)
    shown = lambda vs: r'\text{ 或 }'.join(f'{p}={latex(v)}' for v in sorted(vs))
    if len(values) == 1:
        wrong = ([shown([-values[0]])] if values[0] != 0 else []) + [p + r'\text{ 的值不能唯一确定}']
    else:
        # Several values are all valid; a wrong option misses one of them.
        wrong = [shown([v for v in values if v != left]) for left in values]
    F, word = s['parities'][0]
    question = (f'${F}$ 是{word}，它的定义域 ${domain}$ 必须关于原点对称。'
                f'由此先确定定义域中的参数，${p}$ 的值是多少？')
    lines = []
    if base['domain_ast'][0] == 'interval':
        a, b = (_source_latex(end, x) for end in base['domain_ast'][3:5])
        lines.append(rf'\left({a}\right)+\left({b}\right)=0')
    lines.append(shown(values))
    if output['instantiated_domain'] is not None:
        lines.append(r'\text{定义域为 }' + latex(output['instantiated_domain']))
    _, known = rule_of(model['description'])
    if s['rule'] is not None and len(values) == 1:
        lines.append(_when(known, x) + rf"{s['f']}({x})=" + s['rule'])
    return choice_card('先确定定义域中的参数', question, '已知条件', _lines(_given_rows({**s, 'printed_known': None, 'rule': None})
                                                                   + [r'\text{定义域 }' + domain]),
                       '参数', shown(values), wrong[:3], _lines(lines))


def _instance_target(model):
    """The target after the parameter value is put in, with each input computed."""
    d = model['description']
    terms, constant = linear(d['target_ast'], names_of(d), sp.Symbol(d['variable'], real=True))
    return _combination(list(terms.items()), constant)


def _candidate_views(base, model, s, phase):
    """Several returned parameter values: each one is substituted and evaluated, then the results compared."""
    p, _ = _parameter(base, model)
    lines, wrong = [], []
    for row in model['borrow']['candidates']:
        cm = row['model']
        cs = _source(cm['description'])
        cs['target'] = _instance_target(cm)
        lines.append(rf'{p}={latex(row["parameter_value"])}\text{{ 时，}}{s["target"]}=' + _combine_line(cm, cs))
        for t, k in _misreadings(cm, cs, rule_of(cm['description'])[0]):
            v = _value(cm, t, k)
            if v is not None and v != model['value'] and v not in wrong:
                wrong.append(v)
    given = _lines(_given_rows({**s, 'rule': None}))
    if phase == 'rewrite':
        count = len(model['borrow']['candidates'])
        view = choice_card('逐个代入参数的值', f'参数 ${p}$ 有 ${count}$ 个可能的值，每个值都要代入所求式，'
                           '分别用奇偶性求值，再比较结果。', '已知条件', given, '各个参数值', _lines(lines), [],
                           _lines(lines))
        view.update(interaction={'type': 'read'}, expected_answer={})
        return [_borrow_card(base, model, s), view]
    answer = s['target'] + '=' + latex(model['value'])
    options = [s['target'] + '=' + latex(v) for v in wrong] + [s['target'] + r'\text{ 不能唯一确定}']
    question = f'把 ${p}$ 的每个可能值分别代入并求值后，所求的结论是什么？'
    return [choice_card('求出所求的值', question, '已知条件', given, '结论', answer, options[:3],
                        _lines([*lines, answer]))]


def phase_views(values):
    d, phase = values['description'], values['phase']
    if d['structure_version'] == 'function-symmetry/shifted-odd-v1':
        from .shifted_odd_presentation import phase_views as shifted_views
        return shifted_views(values)
    if d['structure_version'] == 'function-symmetry/general-v1':
        from .symmetry_relation_presentation import phase_views as general_views
        return general_views(values)
    model = solve(d)
    base = None
    if d.get('parameter'):
        base, d = d, model['description']
    s = _source(d)
    s['zero'] = {c['function'] for c in model['calls'] if c['route'] == 'zero' and c['input'] == 0}
    shown_parameter = None
    if base is not None:
        p, candidates = _parameter(base, model)
        shown_parameter = r'\text{ 或 }'.join(f'{p}={latex(v)}' for v in candidates)
        # After the parameter is fixed, the rule applies only inside the instantiated domain.
        s.update(instance=_instance_target(model), target=_source_latex(base['target_ast'], s['x']),
                 printed_known=rule_of(d)[1])
        if len(candidates) > 1:
            return _candidate_views(base, model, s, phase)
    rule = rule_of(d)[0]
    terms, constant = _rewritten(model)
    changed = any(c['route'] == 'zero' or c['image'] != c['input'] for c in model['calls'])
    head = s['target'] + ('' if s.get('instance') is None else '=' + s['instance'])
    rewritten = head + '=' + _combination(terms, constant) if changed else head
    correct = _value(model, terms, constant)
    identity_view, swaps = _identity_card(model, s) if d['identities'] else (None, [])
    if phase == 'rewrite':
        views = []
        if base is not None:
            views.append(_borrow_card(base, model, s))
        if changed:
            wrong = []
            for t, k in _misreadings(model, s, rule):
                text = head + '=' + _combination(t, k)
                v = _value(model, t, k)
                # Equal under the givens (e.g. differs only by f(0)=0) is not a wrong option.
                if v is not None and v == correct or text == rewritten or text in wrong:
                    continue
                if v is None and correct is None and sorted(t) == sorted(terms) and k == constant:
                    continue
                wrong.append(text)
            if s['rule'] is not None:
                where = rf'已知的是 ${range_latex(s["printed_known"], s["x"])}$ 时的解析式'
            else:
                facts = [*s['equations'], *(i['text'] for i in s['identities'])]
                where = '已知 $' + '$，$'.join(facts) + '$' if facts else '两种奇偶关系同时成立'
            zero = '输入为 $0$ 的函数值要单独判断；' if any(c['route'] == 'zero' and c['input'] == 0 for c in model['calls']) else ''
            usable = '输入在已知范围内' if s['rule'] is not None else '题给等式中出现'
            known = '' if base is None else rf'由 ${shown_parameter}$，所求 ${s["target"]}={s["instance"]}$。'
            question = (f'{known}题给 {s["parity"]}，{where}。{zero}'
                        f'利用奇偶性，把所求式中的函数值都改写成{usable}的函数值，所求式可以改写成什么？')
            views.append(choice_card('把输入换成相反数', question, '已知条件', _lines(_given_rows(s)), '改写所求式',
                                     rewritten, wrong[:3], _lines(_rewrite_lines(model, s))))
        if identity_view is not None:
            views.append(identity_view)
        if len(views) == (base is not None):
            zero = '$0$ 的相反数仍是 $0$，' if any(c['input'] == 0 for c in model['calls']) else ''
            view = choice_card('把输入换成相反数', f'{zero}所求式中的函数值不需要改写，直接与已知条件对照。',
                               '已知条件', _lines(_given_rows(s)), '所求式', s['target'], [], s['target'])
            view.update(interaction={'type': 'read'}, expected_answer={})
            views.append(view)
        return views
    answer = _answer(model, s)
    proof_head = [*_instance_lines(model, s), *_evaluation_lines(model, s)]
    if model['value'] is not None:
        values_seen = []
        for t, k in _misreadings(model, s, rule):
            v = _value(model, t, k)
            if v is not None and v != model['value'] and v not in values_seen:
                values_seen.append(v)
        for index, vector, c in swaps:
            equations = [dict(e) for e in model['equations']]
            equations[index] = {**equations[index], 'coefficients': vector, 'constant': c}
            v = _value(model, terms, constant, equations)
            if v is not None and v != model['value'] and v not in values_seen:
                values_seen.append(v)
        wrong = [s['target'] + '=' + latex(v) for v in values_seen] + [s['target'] + r'\text{ 不能唯一确定}']
        proof = _lines([*proof_head, _combine_line(model, s)])
    else:
        target = lambda w: sp.nsimplify(sum((a * z for a, z in zip(model['target_coefficients'], w)), sp.S.Zero)
                                        + model['target_constant'])
        wrong = [s['target'] + '=' + latex(target(w)) for w in model['witnesses']]
        proof = _lines([*proof_head, *([rewritten] if changed else []), answer])
    # Same hint whether or not the givens determine the value.
    shown = '改写后的式子' if changed else '所求式'
    if d['identities']:
        method = f'把得到的等式联立，看{shown}能否由它们求出。'
    elif not model['keys']:
        method = '用已知解析式求出需要的函数值，再代回改写后的式子。'
    else:
        method = f'对照已知条件，看{shown}能否由已知整体得到。'
    question = (rf'由上一步，${rewritten}$。' if changed else rf'所求式为 ${rewritten}$。') + f'{method}所求的结论是什么？'
    known_rows = [r for _, _, r in _instances(model, s)] if d['identities'] else _given_rows(s)
    return [choice_card('求出所求的值', question, '已知与改写', _lines([rewritten, *known_rows]),
                        '结论', answer, list(dict.fromkeys(wrong))[:3], proof)]


def presentation(values):
    view = phase_views(decode_value(values))[-1]
    left, right = view['derivation']['items']
    return {'formula_title': view['title'], 'formula_explanation': '$$' + view['proof'] + '$$',
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_cards(seeds, interaction_id):
    seed, = seeds
    values = decode_value(seed['values'])
    parts = []
    for index, view in enumerate(phase_views(values), 1):
        board, interaction = deepcopy(view['derivation']), deepcopy(view['interaction'])
        if interaction['type'] == 'read':
            board = {'caption': view['title'], 'lines': board_lines(view['proof'])}
        else:
            board['items'][1]['math'] = None
            interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        parts.append({'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                      'interaction': interaction, 'expected_answer': view['expected_answer'],
                      'feedback': view['feedback'], 'submit_label': '继续' if interaction['type'] == 'read' else '确认判断',
                      'stem_board': board, 'completion_board': view['derivation']})
        for key in ('condition_number_lines', 'graph', 'completion_graph', 'card_group', 'card_group_title'):
            if view.get(key):
                parts[-1][key] = deepcopy(view[key])
    return {'parts': parts, 'diagnostics': []}
