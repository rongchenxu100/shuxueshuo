"""FP-T4 cards: the half-axis route (R0), the comparison route (R1–R2) and the sign route (R3)."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from .. import parity_order_math as order
from ..function_parity import reflect_ast
from ..parity_extension_math import reflect
from ..parity_inequality_math import FLIP, OPS, _same, solve, symbols
from ..stage_one.function_domain import expression_latex
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .parity_extension_presentation import _number_line, _printed, range_latex
from .parity_parameter_presentation import PROPERTY, _display_ast, board_lines
from .trajectory import decode_value

SYMBOL = {'<': '<', '<=': r'\le ', '>': '>', '>=': r'\ge '}


def _set(s, x):
    if s == sp.S.EmptySet:
        return x + r'\in\varnothing'
    if isinstance(s, sp.Interval) and s.start == -sp.oo and s.end == sp.oo:
        return x + r'\in\mathbb R'
    return range_latex(s, x) if isinstance(s, (sp.Interval, sp.FiniteSet)) else x + r'\in ' + latex(s)


def _when(s, x):
    return range_latex(s, x) + r'\text{ 时，}'


def _distinct(correct, candidates):
    kept = []
    for s in candidates:
        if not _same(s, correct) and all(not _same(s, t) for t in kept):
            kept.append(s)
    return kept


def _restriction_lines(d, x):
    from .. import parity_inequality_inputs as algebra
    lines = []
    requested = algebra.requested(d, x)
    if requested != sp.S.Reals:
        lines.append(r'\text{题给范围：}' + _set(requested, str(x)))
    asts = ([a for _, a in d['terms']] if d.get('route') == 'order' else
            [order._bound(a, str(x)) for a in (d.get('input_ast'), d.get('factor_ast')) if a is not None])
    if asts:
        guard = algebra.guard(asts, x)
        if guard != sp.S.Reals:
            lines.append(r'\text{原式有意义：}' + _set(guard, str(x)))
    return lines


def _source(d, model):
    x, f = d['variable'], d['function']
    ast = _display_ast(d['extension']['rule_ast'])
    op, k = model['operator'], model['threshold']
    return {'x': x, 'f': f, 'fx': rf'{f}({x})', 'fneg': rf'{f}(-{x})',
            'rule': _printed(expression_latex(ast, x), x),
            'reflected': _printed(expression_latex(reflect_ast(ast), x), x),
            'property': PROPERTY[d['property']], 'sign': model['sign'],
            'inequality': rf'{f}({x}){SYMBOL[op]}{latex(k)}',
            'mirror_inequality': rf'{f}(-{x}){SYMBOL[model["mirror_operator"]]}{latex(model["mirror_threshold"])}'}


def _given(s, model):
    return _lines([_when(model['rule_domain'], s['x']) + s['fx'] + '=' + s['rule'],
                   r'\text{' + s['property'] + '}', s['inequality']])


def _known_view(d, model, s):
    x, K, S = s['x'], model['rule_domain'], model['known_solution']
    variable, rule = symbols(d), model['rule']
    op, k = model['operator'], model['threshold']
    wrong = _distinct(S, [sp.solveset(OPS[FLIP[op]](rule, k), variable, K),
                          sp.solveset(OPS[op](rule, k), variable, sp.S.Reals),
                          K - S])
    proof = _lines([s['fx'] + '=' + s['rule'] + r'\ (' + range_latex(K, x) + ')',
                    s['rule'] + SYMBOL[op] + latex(k) + r'\Rightarrow ' + _set(S, x)])
    return choice_card('先在已知范围内解不等式', rf'${range_latex(K, x)}$ 时 ${s["fx"]}={s["rule"]}$。'
                       rf'在这一范围内，${s["inequality"]}$ 的解是什么？',
                       '已知条件', _given(s, model), '已知范围内的解', _when(K, x) + _set(S, x),
                       [_when(K, x) + _set(w, x) for w in wrong[:3]], proof)


def _mirror_view(d, model, s):
    x, M = s['x'], model['mirrored_domain']
    variable, rule, K = symbols(d), model['rule'], model['rule_domain']
    neg = lambda t: sp.imageset(sp.Lambda(variable, -variable), t)
    op, k = model['operator'], model['threshold']
    correct = model['mirrored_solution']
    candidates = [model['known_solution'] & M, neg(model['known_solution']) & M,
                  neg(sp.solveset(OPS[FLIP[op]](rule, k), variable, K)) & M, M - correct]
    wrong = _distinct(correct, candidates)
    relation = (s['fx'] + '=' + s['fneg'] if s['sign'] == 1 else s['fx'] + '=-' + s['fneg'])
    steps = [range_latex(M, x) + r'\Rightarrow ' + range_latex(neg(M), '-' + x), relation]
    if s['sign'] == 1:
        steps.append(s['inequality'] + r'\Leftrightarrow ' + s['mirror_inequality'])
    else:
        steps.append(s['inequality'] + r'\Leftrightarrow -' + s['fneg'] + SYMBOL[op] + latex(k)
                     + r'\Leftrightarrow ' + s['mirror_inequality'])
        steps.append(s['rule'] + SYMBOL[model['mirror_operator']] + latex(model['mirror_threshold'])
                     + r'\ (' + range_latex(K, x) + r')\Rightarrow ' + _set(model['mirror_solution'], x))
    steps.append(_set(model['mirror_solution'], '-' + x) + r'\Rightarrow ' + _set(correct, x))
    question = (rf'${range_latex(M, x)}$ 时，$-{x}$ 落在已知范围内。题给 ${s["f"]}$ 是{s["property"]}，'
                rf'${range_latex(M, x)}$ 时 ${s["inequality"]}$ 的解是什么？')
    left = _lines([_when(K, x) + _set(model['known_solution'], x), r'\text{' + s['property'] + '}'])
    return choice_card('用奇偶性得到另一侧的解', question, '已求出的结果', left, '对称范围内的解',
                       _when(M, x) + _set(correct, x), [_when(M, x) + _set(w, x) for w in wrong[:3]],
                       _lines(steps))


def _zero_line(model, s):
    case = model['cases'][-1]
    if case['zero_status'] != 'forced_zero':
        return []
    verdict = r'\text{，是解}' if case['zero_included'] else r'\text{，不是解}'
    prefix = r'0\in D\Rightarrow ' if model['domain_identity'] == 'zero_membership_open' else ''
    return [prefix + s['f'] + '(0)=0' + r',\ 0' + SYMBOL[model['operator']] + latex(model['threshold'])
            + (r'\text{ 成立}' if case['zero_included'] else r'\text{ 不成立}') + verdict]


def _conclude_view(d, model, s):
    x = s['x']
    variable = symbols(d)
    neg = lambda t: sp.imageset(sp.Lambda(variable, -variable), t)
    S, known, mirrored = model['solution'], model['known_solution'], model['mirrored_solution']
    zero = _zero_line(model, s)
    candidates = [known, mirrored, known | (neg(known) & model['mirrored_domain']),
                  S - sp.FiniteSet(0) if S.contains(0) is sp.true else S | sp.FiniteSet(0)]
    if not zero:
        candidates.pop()
    wrong = _distinct(S, candidates)
    lines = [_when(model['rule_domain'], x) + _set(known, x), _when(model['mirrored_domain'], x) + _set(mirrored, x),
             *zero, *_restriction_lines(d, variable), s['inequality'] + r'\text{ 的解集为 }' + latex(S)]
    if model['domain_identity'] == 'zero_membership_open':
        lines.insert(2, r'0\notin D\text{ 时 }' + s['f'] + r'(0)\text{ 无意义}')
    asked = rf'不等式 ${s["inequality"]}$ 的解集是什么？'
    if zero:
        question = (rf'$x=0$ 不在已知范围内，也不在它的对称范围内。题给 ${s["f"]}$ 是{s["property"]}，'
                    + ('若 $0$ 在定义域内，' if model['domain_identity'] == 'zero_membership_open' else '')
                    + '要单独检查 $x=0$。把各部分合并，' + asked)
    else:
        question = '把两部分的解合并，' + asked
    left = _lines([_when(model['rule_domain'], x) + _set(known, x), _when(model['mirrored_domain'], x) + _set(mirrored, x)])
    return choice_card('合并各部分，写出解集', question, '各部分的解', left, '解集', _set(S, x),
                       [_set(w, x) for w in wrong[:3]], _lines(lines))


DIRECTION = {'increasing': '严格递增', 'decreasing': '严格递减'}


def _input_latex(ast, x):
    return _printed(expression_latex(_display_ast(order._bound(ast, x)), x), x)


def _side_latex(ast, f, x):
    if ast[:1] == ['function_call']:
        return rf'{f}({_input_latex(ast[2], x)})'
    if ast[:1] == ['neg']:
        return '-' + _side_latex(ast[1], f, x)
    if ast[:1] in (['+'], ['-']):
        right = _side_latex(ast[2], f, x)
        if ast[0] == '+' and right.startswith('-'):
            return _side_latex(ast[1], f, x) + right
        return _side_latex(ast[1], f, x) + ast[0] + right
    return _printed(expression_latex(ast, x), x)


def _order_source(d, model):
    x, f = d['variable'], d['function']
    rel = d['relation_ast']
    return {'x': x, 'f': f, 'property': PROPERTY[d['property']],
            'inequality': _side_latex(rel[1], f, x) + SYMBOL[rel[0]] + _side_latex(rel[2], f, x),
            'domain': model['certificate']['domain']}


def _compare(a, op, w):
    return latex(a) + SYMBOL[op] + latex(w)


def _values(f, a, op, w):
    return rf'{f}({latex(a)}){SYMBOL[op]}{f}({latex(w)})'


def _solution_of(model, op, a, w):
    """Solution set that a candidate comparison f(a) □ f(w) would give under the certified direction."""
    converted = op if model['certificate']['direction'] == 'increasing' else FLIP[op]
    return model['legal_set'] & order._ordered(converted, a, w, model['variable'])


def _domain_text(D, x):
    return latex(D) if D != sp.Interval(-sp.oo, sp.oo) else r'\mathbb R'


def _rewrite_view(d, model, s):
    f = s['f']
    op, a, w = model['operator'], model['left_input'], model['right_input']
    correct = _values(f, a, op, w)
    rows = [(_values(f, a, op, -w), _solution_of(model, op, a, -w)),
            (_values(f, a, FLIP[op], w), _solution_of(model, FLIP[op], a, w)),
            (_values(f, -a, op, w), _solution_of(model, op, -a, w))]
    kept = _distinct(model['solution'], [t for _, t in rows])
    wrong = [text for text, t in rows if any(t is k for k in kept)]
    lone = len(d['terms']) == 1
    steps = ([rf'{f}(0)=0', s['inequality'] + r'\Leftrightarrow ' + correct] if lone else
             [*_rewrite_steps(d, model, s), s['inequality'] + r'\Leftrightarrow ' + correct])
    question = (rf'题给 ${f}$ 是{s["property"]}。把不等式 ${s["inequality"]}$ 写成同一个函数两个值的比较，'
                '是下面哪一个？')
    left = _lines([r'\text{' + s['property'] + '}', s['inequality']])
    return choice_card('改写成两个函数值的比较', question, '已知条件', left, '等价的比较', correct, wrong, _lines(steps))


def _rewrite_steps(d, model, s):
    """s1·f(u1) + s2·f(u2) □ 0 ⇔ s1·f(u1) □ −s2·f(u2); oddness writes each signed value as f(±u)."""
    f = s['f']
    (s1, u1), (s2, u2) = [(sg, latex(order.read_input(t, model['variable']))) for sg, t in d['terms']]
    left = rf'{f}({u1})' if s1 == 1 else rf'-{f}({u1})'
    right = rf'-{f}({u2})' if s2 == 1 else rf'{f}({u2})'
    lines = [left + SYMBOL[model['operator']] + right]
    if s1 == -1:
        lines.append(left + rf'={f}({latex(model["left_input"])})')
    if s2 == 1:
        lines.append(right + rf'={f}({latex(model["right_input"])})')
    return lines


def _direction_view(d, model, s):
    f, x, D = s['f'], s['x'], s['domain']
    cert = model['certificate']
    dom = _domain_text(D, x)
    answer = rf'{f}\text{{ 在 }}{dom}\text{{ 上{DIRECTION[cert["direction"]]}}}'
    other = 'decreasing' if cert['direction'] == 'increasing' else 'increasing'
    wrong = [rf'{f}\text{{ 在 }}{dom}\text{{ 上{DIRECTION[other]}}}', rf'{f}\text{{ 在 }}{dom}\text{{ 上不单调}}']
    source = d['direction_source']
    if cert['kind'] == 'rule':
        ext = source['extension']
        rule = _printed(expression_latex(_display_ast(ext['rule_ast']), x), x)
        K, R = cert['known'], cert['reflected']
        given = _when(K, x) + rf'{f}({x})=' + rule
        steps = [given + r'\text{，' + DIRECTION[cert['direction']] + '}',
                 r'\text{奇函数在对称两侧单调方向相同}\Rightarrow ' + _when(R, x)
                 + r'\text{' + DIRECTION[cert['direction']] + '}']
        if cert['zero'] == 'forced_zero':
            sign = '>' if cert['known_sign'] == 1 else '<'
            steps.append(rf'{f}(0)=0,\ ' + _when(K, x) + rf'{f}({x}){sign}0')
        question = (rf'题给 ${f}$ 是{s["property"]}，${given}$。${f}$ 在定义域 ${dom}$ 上的单调性是什么？')
        left = _lines([given, r'\text{' + s['property'] + r'，定义域 }' + dom])
    else:
        interval = cert['interval']
        statement = source['basis'].get('statement')
        text = (_printed(expression_latex(statement, x), x) if isinstance(statement, list) else
                _statement_latex(statement) if statement else
                rf'{f}\text{{ 在 }}{latex(interval)}\text{{ 上{DIRECTION[cert["direction"]]}}}')
        steps = [text + r'\Rightarrow ' + rf'{f}\text{{ 在 }}{latex(interval)}\text{{ 上{DIRECTION[cert["direction"]]}}}']
        if cert['kind'] == 'given_half':
            steps.append(r'\text{奇函数在对称两侧单调方向相同}\Rightarrow ' + rf'{f}\text{{ 在 }}{latex(cert["reflected"])}'
                         + r'\text{ 上' + DIRECTION[cert['direction']] + '}')
        question = rf'题给 ${f}$ 是{s["property"]}，定义域为 ${dom}$，且 ${text}$。${f}$ 在 ${dom}$ 上的单调性是什么？'
        left = _lines([text, r'\text{' + s['property'] + r'，定义域 }' + dom])
    if cert['kind'] != 'given':
        steps.append(r'\Rightarrow ' + answer)
    return choice_card('确定整个定义域上的单调方向', question, '已知条件', left, '单调性', answer, wrong, _lines(steps))


def _statement_latex(statement):
    return statement.replace('(f(x_1)-f(x_2))/(x_1-x_2)', r'\frac{f(x_1)-f(x_2)}{x_1-x_2}') \
        .replace('<=', r'\le ').replace('>=', r'\ge ')


def _compare_view(d, model, s):
    f, x = s['f'], s['x']
    cert, a, w = model['certificate'], model['left_input'], model['right_input']
    op, conv = model['operator'], model['converted_operator']
    legal = model['legal_set']
    correct = _compare(a, conv, w)
    rows = [(_compare(a, FLIP[conv], w), legal & order._ordered(FLIP[conv], a, w, model['variable'])),
            (_compare(a, conv, -w), legal & order._ordered(conv, a, -w, model['variable']))]
    kept = _distinct(model['solution'], [t for _, t in rows])
    wrong = [text for text, t in rows if any(t is k for k in kept)]
    mono = rf'{f}\text{{ 在 }}{_domain_text(s["domain"], x)}\text{{ 上{DIRECTION[cert["direction"]]}}}'
    keep = '不等号方向不变' if cert['direction'] == 'increasing' else '不等号方向改变'
    question = (rf'${mono}$，两个输入都在定义域内时，${_values(f, a, op, w)}$ 等价于下面哪一个输入之间的关系？')
    proof = _lines([mono + r'\text{，' + keep + '}', _values(f, a, op, w) + r'\Leftrightarrow ' + correct])
    return choice_card('去掉函数符号比较输入', question, '已知条件', _lines([mono, _values(f, a, op, w)]),
                       '输入之间的关系', correct, wrong, proof)


def _order_conclude_view(d, model, s):
    x, D = s['x'], s['domain']
    variable = model['variable']
    S, legal, ordered = model['solution'], model['legal_set'], model['ordered_set']
    flipped = order._ordered(FLIP[model['converted_operator']], model['left_input'], model['right_input'], variable)
    wrong = _distinct(S, [ordered, legal, legal & flipped, legal - S])
    compare = _compare(model['left_input'], model['converted_operator'], model['right_input'])
    dom = _domain_text(D, x)
    member = [expression_latex(_display_ast(ast), x) + r'\in ' + dom for _, ast in d['terms']]
    member.extend(_restriction_lines(d, variable))
    lines = [*member, r'\Rightarrow ' + _set(legal, x), compare + r'\Rightarrow ' + _set(ordered, x),
             r'\text{求交得 }' + _set(S, x)]
    question = (rf'每个输入都要在定义域 ${dom}$ 内，再与 ${compare}$ 的解求交。'
                rf'满足不等式 ${s["inequality"]}$ 的 ${x}$ 的取值范围是什么？')
    left = _lines([*member, compare])
    return choice_card('合法输入求交，写出解集', question, '要同时满足', left, '解集', _set(S, x),
                       [_set(t, x) for t in wrong[:3]], _lines(lines))


def _abs(e):
    return r'\left|' + latex(e) + r'\right|'


def _nonnegative(model):
    return model['certificate']['domain'] & sp.Interval(0, sp.oo)


def _even_rewrite_view(d, model, s):
    f, op = s['f'], model['operator']
    a, w = model['left_input'], model['right_input']
    correct = rf'{f}({_abs(a)}){SYMBOL[op]}{f}({_abs(w)})'
    wrong = [rf'{f}({_abs(a)}){SYMBOL[FLIP[op]]}{f}({_abs(w)})',
             rf'{f}({_abs(a)}){SYMBOL[op]}-{f}({_abs(w)})']
    question = (rf'题给 ${f}$ 是{s["property"]}。把两个输入都换到非负一侧，不等式 ${s["inequality"]}$ '
                '等价于下面哪一个？')
    proof = _lines([r'\text{偶函数 }' + rf'{f}(u)={f}(-u)={f}(|u|)',
                    s['inequality'] + r'\Leftrightarrow ' + correct])
    return choice_card('把两个输入换到非负一侧', question, '已知条件',
                       _lines([r'\text{' + s['property'] + '}', s['inequality']]), '等价的比较', correct, wrong, proof)


def _even_direction_view(d, model, s):
    f, x = s['f'], s['x']
    cert = model['certificate']
    half = latex(_nonnegative(model))
    word = DIRECTION[cert['positive_direction']]
    answer = rf'{f}\text{{ 在 }}{half}\text{{ 上{word}}}'
    wrong = [rf'{f}\text{{ 在 }}{half}\text{{ 上{DIRECTION[order._other(cert["positive_direction"])]}}}',
             rf'{f}\text{{ 在 }}{half}\text{{ 上不单调}}']
    if cert['kind'] == 'even_rule':
        rule = _printed(expression_latex(_display_ast(d['direction_source']['extension']['rule_ast']), x), x)
        given = _when(cert['known'], x) + rf'{f}({x})=' + rule
        known = given + r'\text{，' + DIRECTION[cert['direction']] + '}'
    else:
        given = rf'{f}\text{{ 在 }}{latex(cert["interval"])}\text{{ 上{DIRECTION[cert["direction"]]}}}'
        known = given
    steps = [known]
    if cert['positive_direction'] != cert['direction']:
        steps.append(r'\text{偶函数在对称两侧单调方向相反}\Rightarrow ' + answer)
    else:
        steps.append(r'\Rightarrow ' + answer)
    question = (rf'题给 ${f}$ 是{s["property"]}，定义域为 ${_domain_text(s["domain"], x)}$，且 ${given}$。'
                rf'${f}$ 在非负一侧 ${half}$ 上的单调性是什么？')
    left = _lines([given, r'\text{' + s['property'] + r'，定义域 }' + _domain_text(s['domain'], x)])
    return choice_card('确定非负一侧的单调方向', question, '已知条件', left, '单调性', answer, wrong, _lines(steps))


def _even_compare_view(d, model, s):
    f = s['f']
    a, w, op, conv = model['left_input'], model['right_input'], model['operator'], model['converted_operator']
    legal, variable = model['legal_set'], model['variable']
    correct = _abs(a) + SYMBOL[conv] + _abs(w)
    rows = [(_abs(a) + SYMBOL[FLIP[conv]] + _abs(w), legal & order.ordered_inputs(FLIP[conv], a, w, variable, True)),
            (_compare(a, conv, w), legal & order.ordered_inputs(conv, a, w, variable, False))]
    kept = _distinct(model['solution'], [t for _, t in rows])
    wrong = [text for text, t in rows if any(t is k for k in kept)]
    half = latex(_nonnegative(model))
    mono = rf'{f}\text{{ 在 }}{half}\text{{ 上{DIRECTION[model["certificate"]["positive_direction"]]}}}'
    values = rf'{f}({_abs(a)}){SYMBOL[op]}{f}({_abs(w)})'
    keep = '不等号方向不变' if conv == op else '不等号方向改变'
    question = (rf'${mono}$，两个输入都在定义域内时 ${_abs(a)}$、${_abs(w)}$ 都在 ${half}$ 内，'
                rf'${values}$ 等价于下面哪一个输入之间的关系？')
    proof = _lines([mono + r'\text{，' + keep + '}', values + r'\Leftrightarrow ' + correct])
    return choice_card('去掉函数符号比较输入', question, '已知条件', _lines([mono, values]),
                       '输入之间的关系', correct, wrong, proof)


def _even_conclude_view(d, model, s):
    x, D = s['x'], s['domain']
    variable = model['variable']
    a, w, conv = model['left_input'], model['right_input'], model['converted_operator']
    S, legal, ordered = model['solution'], model['legal_set'], model['ordered_set']
    flipped = order.ordered_inputs(FLIP[conv], a, w, variable, True)
    wrong = _distinct(S, [ordered, legal, legal & flipped, legal - S])
    compare = _abs(a) + SYMBOL[conv] + _abs(w)
    dom = _domain_text(D, x)
    member = [expression_latex(_display_ast(ast), x) + r'\in ' + dom for _, ast in d['terms']]
    member.extend(_restriction_lines(d, variable))
    squared = sp.expand((a - w) * (a + w))
    lines = [*member, r'\Rightarrow ' + _set(legal, x),
             compare + r'\Leftrightarrow ' + rf'\left({latex(a)}\right)^2{SYMBOL[conv]}\left({latex(w)}\right)^2',
             r'\Leftrightarrow ' + latex(squared) + SYMBOL[conv] + r'0\Rightarrow ' + _set(ordered, x),
             r'\text{求交得 }' + _set(S, x)]
    question = (rf'每个输入都要在定义域 ${dom}$ 内，再与 ${compare}$ 的解求交。'
                rf'满足不等式 ${s["inequality"]}$ 的 ${x}$ 的取值范围是什么？')
    return choice_card('合法输入求交，写出解集', question, '要同时满足', _lines([*member, compare]), '解集', _set(S, x),
                       [_set(t, x) for t in wrong[:3]], _lines(lines))


def _borrow_card(base, model, s):
    """The domain parameter returned by the T2 subtask; the domain and the monotonic interval then become numeric."""
    from .symmetry_presentation import _source_latex
    p, value = base['parameter']['name'], model['borrow']['parameter_value']
    x, f = s['x'], s['f']
    domain = _source_latex(base['domain_ast'], x)
    shown = f'{p}={latex(value)}'
    wrong = ([f'{p}={latex(-value)}'] if value != 0 else []) + [p + r'\text{ 的值不能唯一确定}']
    question = (f'${f}$ 是{s["property"]}，它的定义域 ${domain}$ 必须关于原点对称。'
                f'由此先确定定义域中的参数，${p}$ 的值是多少？')
    lines = []
    if base['domain_ast'][0] == 'interval':
        lo, hi = (_source_latex(end, x) for end in base['domain_ast'][3:5])
        lines.append(rf'\left({lo}\right)+\left({hi}\right)=0')
    lines += [shown, r'\text{定义域为 }' + latex(model['borrow']['output']['instantiated_domain'])]
    interval = model['certificate'].get('interval')
    if interval is not None:
        lines.append(r'\text{单调区间为 }' + latex(interval))
    left = _lines([r'\text{' + s['property'] + '}', r'\text{定义域 }' + domain])
    return choice_card('先确定定义域中的参数', question, '已知条件', left, '参数', shown, wrong, _lines(lines))


def _order_views(d, phase):
    model = order.solve(d)
    instance = model['description']
    s = _order_source(instance, model)
    even = instance['property'] == 'even'
    views = ({'rewrite': _even_rewrite_view, 'direction': _even_direction_view, 'compare': _even_compare_view,
              'conclude': _even_conclude_view} if even else
             {'rewrite': _rewrite_view, 'direction': _direction_view, 'compare': _compare_view,
              'conclude': _order_conclude_view})
    view = views[phase](instance, model, s)
    if d.get('parameter') and phase == 'rewrite':
        return [_borrow_card(d, model, s), view]
    return [view]


REL = {-1: '<', 0: '=', 1: '>'}


def sign_inequality_latex(d):
    f, x = d['function'], d['variable']
    value = rf'{f}({_input_latex(d["input_ast"], x)})'
    if d['factor_kind'] == 'quotient':
        side = rf'\frac{{{value}}}{{{_input_latex(d["factor_ast"], x)}}}'
    elif d['factor_kind'] == 'product':
        q = _input_latex(d['factor_ast'], x)
        side = (q if d['factor_ast'][:1] in (['ref'], ['number']) else rf'\left({q}\right)') + value
    else:
        side = value
    return side + SYMBOL[d['operator']] + '0'


def _sign_statement(part, value, f, x):
    if isinstance(part, sp.FiniteSet):
        return r'\text{，}'.join(rf'{f}({latex(p)})=0' for p in part) if value == 0 else None
    return _when(part, x) + rf'{f}({x}){REL[value]}0'


def _sign_table(cells, f, x):
    return r'\text{；}'.join(t for t in (_sign_statement(p, v, f, x) for p, v in cells) if t)


def _uniform(cells, value):
    return [(p, value if not isinstance(p, sp.FiniteSet) else v) for p, v in cells]


def _sign_choices(cells, f, x):
    """Correct sign table and statements that disagree with it on some open part."""
    open_cells = [(p, v) for p, v in cells if not isinstance(p, sp.FiniteSet)]
    correct = _sign_table(cells, f, x)
    candidates = [[(p, -v if not isinstance(p, sp.FiniteSet) else v) for p, v in cells]]
    for value in (1, -1):
        if any(v != value for _, v in open_cells):
            candidates.append(_uniform(cells, value))
    wrong = []
    for cand in candidates:
        text = _sign_table(cand, f, x)
        if text != correct and text not in wrong:
            wrong.append(text)
    return correct, wrong[:2] or [rf'{f}({x})\text{{ 的符号不能确定}}']


def _sign_source(d, model):
    f, x = d['function'], d['variable']
    cert = model['certificate']
    interval = cert['interval']
    mono = rf'{f}\text{{ 在 }}{latex(interval)}\text{{ 上{DIRECTION[cert["direction"]]}}}'
    zeros = [rf'{f}({latex(p)})=0' for p in cert['printed_zeros']]
    return {'f': f, 'x': x, 'mono': mono, 'zeros': zeros, 'property': PROPERTY[d['property']],
            'inequality': sign_inequality_latex(d), 'input': latex(model['input']), 'factor': latex(model['factor'])}


def _sign_known_view(d, model, s):
    f, x, cert = s['f'], s['x'], model['certificate']
    z = cert['zero']
    correct, wrong = _sign_choices(cert['known'], f, x)
    steps = []
    if z not in cert['printed_zeros']:
        steps.append(rf'{f}({latex(z)})=' + (rf'-{f}({latex(-z)})' if d['property'] == 'odd' else rf'{f}({latex(-z)})')
                     + '=0' if z != 0 else rf'\text{{奇函数且 }}0\in{latex(cert["interval"])}\Rightarrow {f}(0)=0')
    for part, value in cert['known']:
        if isinstance(part, sp.FiniteSet):
            continue
        rel = REL[value]
        steps.append(_when(part, x) + rf'{f}({x}){rel}{f}({latex(z)})=0')
    known = [s['mono'], *s['zeros']]
    question = (f'题给 ${s["mono"]}$，且 ${"，".join(s["zeros"])}$。'
                rf'在 ${latex(cert["interval"])}$ 上，${f}({x})$ 的符号是什么？')
    return choice_card('确定已知区间上函数值的符号', question, '已知条件', _lines(known), '已知区间上的符号',
                       correct, wrong, _lines([*known, *steps]))


def _sign_mirror_view(d, model, s):
    f, x, cert = s['f'], s['x'], model['certificate']
    mirrored = cert['mirrored']
    correct, wrong = _sign_choices(mirrored, f, x)
    relation = rf'{f}({x})=-{f}(-{x})' if d['property'] == 'odd' else rf'{f}({x})={f}(-{x})'
    steps = [relation]
    for part, value in mirrored:
        if isinstance(part, sp.FiniteSet):
            steps.append(r'\text{，}'.join(rf'{f}({latex(p)})=' + ('-' if d['property'] == 'odd' else '')
                                          + rf'{f}({latex(-p)})=0' for p in part))
        else:
            steps.append(range_latex(part, x) + r'\Rightarrow ' + range_latex(reflect(part), '-' + x)
                         + r'\Rightarrow ' + rf'{f}({x}){REL[value]}0')
    whole = sp.Union(*(p for p, _ in mirrored))
    question = (rf'题给 ${f}$ 是{s["property"]}。在对称一侧 ${latex(whole)}$ 上，${f}({x})$ 的符号是什么？')
    return choice_card('用奇偶性得到另一侧的符号', question, '已求出的结果',
                       _lines([_sign_table(cert['known'], f, x), r'\text{' + s['property'] + '}']),
                       '对称一侧的符号', correct, wrong, _lines(steps))


def _conditions(d, s, op):
    """The relation as sign conditions on the factor and on f(input)."""
    f, u, q = s['f'], s['input'], s['factor']
    value = rf'{f}({u})'
    kind = d['factor_kind']
    if kind is None:
        return value + SYMBOL[op] + '0'
    rows = [q + r'>0\text{ 且 }' + value + SYMBOL[op] + '0', q + r'<0\text{ 且 }' + value + SYMBOL[FLIP[op]] + '0']
    if kind == 'product' and op in ('<=', '>='):
        rows.append(q + '=0')
    return r'\text{，或 }'.join(rows)


def _branch_solution(model, op, branches):
    from .. import parity_sign_math as sign
    d, x = model['description'], model['variable']
    row = model['cases'][0]
    cells = sign.sign_cells(model['certificate'], row['zero_sign'])
    qs = sign.factor_sets(model['factor'], x, d['factor_kind'])
    pieces = [sign.preimage(model['input'], x, p) & qs[t] for p, v in cells for t in branches
              if t in qs and bool(OPS[op](v * t, 0))]
    return sp.simplify(sp.Union(*pieces) & row['legal_set']) if pieces else sp.S.EmptySet


def _sign_solve_view(d, model, s):
    from .. import parity_sign_math as sign
    f, x, op = s['f'], s['x'], model['operator']
    correct = _conditions(d, s, op)
    if d['factor_kind'] is None:
        tables = [sign.sign_cells(model['certificate'], row['zero_sign']) for row in model['cases']]
        targets = [sp.Union(*(p for p, v in table if bool(OPS[op](v, 0)))) for table in tables]
        target = sp.Intersection(*targets)
        correct = s['input'] + r'\in ' + latex(target)
        candidates = _distinct(target, [sp.S.Reals - target, model['certificate']['interval']])
        # Different input sets can have the same preimage (especially a constant
        # input); distractors must differ on this question's actual legal inputs.
        wrong, solutions = [], []
        for candidate in candidates:
            answer = sign.preimage(model['input'], model['variable'], candidate) & model['cases'][0]['legal_set']
            if not _same(answer, model['solution']) and all(not _same(answer, old) for old in solutions):
                wrong.append(s['input'] + r'\in ' + latex(candidate))
                solutions.append(answer)
        question = (rf'在原式有意义且满足题给范围时，由 ${f}$ 的符号，'
                    rf'不等式 ${s["inequality"]}$ 等价于输入 ${s["input"]}$ 落在哪里？')
        title = '写出输入应在的范围'
    else:
        target = model['solution']
        rows = [(_conditions(d, s, FLIP[op]), _branch_solution(model, FLIP[op], (1, -1, 0))),
                (s['factor'] + r'>0\text{ 且 }' + rf'{f}({s["input"]})' + SYMBOL[op] + '0',
                 _branch_solution(model, op, (1,)))]
        kept = _distinct(target, [t for _, t in rows])
        wrong = [text for text, t in rows if any(t is k for k in kept)]
        question = rf'按 ${s["factor"]}$ 的正负分开讨论，不等式 ${s["inequality"]}$ 等价于下面哪一组条件？'
        title = '结合分母列出符号条件' if d['factor_kind'] == 'quotient' else '结合因式列出符号条件'
    proof = [*_restriction_lines(d, model['variable']), s['inequality'] + r'\Leftrightarrow ' + correct]
    if d['factor_kind'] == 'quotient':
        proof.append(r'\text{分母 }' + s['factor'] + r'\ne 0')
    zero = 0 if all(row['zero_sign'] == 0 for row in model['cases']) else None
    cells = sign.sign_cells(model['certificate'], zero)
    left = _lines([_sign_table(cells, f, x), *_restriction_lines(d, model['variable']), s['inequality']])
    return choice_card(title, question, '已知条件', left, '等价条件', correct, wrong, _lines(proof))


def _sign_conclude_view(d, model, s):
    from .. import parity_sign_math as sign
    f, x, op = s['f'], s['x'], model['operator']
    variable = model['variable']
    S, row = model['solution'], model['cases'][0]
    u = model['input']
    wrong = _distinct(S, [_branch_solution(model, FLIP[op], (1, -1, 0)),
                          _branch_solution({**model, 'factor': sp.S.One,
                                            'description': {**d, 'factor_kind': None}}, op, (1,)),
                          row['legal_set'] - S])
    lines = []
    kinds = ((1, -1, 0) if d['factor_kind'] == 'product' and op in ('<=', '>=')
             else (1, -1) if d['factor_kind'] else (1,))
    for t in kinds:
        part = _branch_solution(model, op, (t,))
        if t == 0:
            lines.append(s['factor'] + '=0' + r'\Rightarrow ' + _set(part, x))
            continue
        head = (s['factor'] + ('>0' if t == 1 else '<0') + r',\ ') if d['factor_kind'] else ''
        rel = op if t == 1 else FLIP[op]
        lines.append(head + rf'{f}({s["input"]}){SYMBOL[rel]}0\Rightarrow ' + _set(part, x))
    origin = sign.preimage(u, variable, sp.FiniteSet(0)) & model['cases'][-1]['legal_set']
    covered = model['certificate']['interval'] | reflect(model['certificate']['interval'])
    open_zero = covered.contains(0) is not sp.true and origin != sp.S.EmptySet
    if open_zero:
        verdict = r'\text{，是解}' if origin.is_subset(S) else r'\text{，不是解}'
        states = []
        if model['certificate']['domain_identity'] == 'zero_membership_open':
            states.append(r'0\notin D\text{ 时 }' + rf'{f}(0)\text{{ 无意义}}')
        if any(r['zero_sign'] == 0 for r in model['cases']):
            states.append((r'0\in D\text{ 时 }' if states else '') + rf'{f}(0)=0')
        lines.append(rf'{s["input"]}=0\Rightarrow ' + _set(origin, x) + r':\ ' + r'\text{；}'.join(states) + verdict)
    lines.extend(_restriction_lines(d, variable))
    lines.append(s['inequality'] + r'\text{ 的解集为 }' + latex(S))
    note = ('题目没有说明 $0$ 是否在定义域内，两种情况都要检查。'
            if model['certificate']['domain_identity'] == 'zero_membership_open' and open_zero else '')
    question = rf'按符号条件解出 ${x}$，再合并。{note}不等式 ${s["inequality"]}$ 的解集是什么？'
    left = _lines([_conditions(d, s, op), _sign_table([*model['certificate']['known'],
                                                       *model['certificate']['mirrored']], f, x)])
    return choice_card('解出各种情况，写出解集', question, '要同时满足', left, '解集', _set(S, x),
                       [_set(t, x) for t in wrong[:3]], _lines(lines))


def _sign_views(d, phase):
    from .. import parity_sign_math as sign
    model = sign.solve(d)
    s = _sign_source(d, model)
    views = {'sign_known': _sign_known_view, 'sign_mirror': _sign_mirror_view, 'sign_solve': _sign_solve_view,
             'conclude': _sign_conclude_view}
    return [views[phase](d, model, s)]


def phase_views(values):
    d, phase = values['description'], values['phase']
    if d.get('route') == 'order':
        return _order_views(d, phase)
    if d.get('route') == 'sign':
        return _sign_views(d, phase)
    model = solve(d)
    s = _source(d, model)
    if phase == 'known':
        return [_known_view(d, model, s)]
    if phase == 'mirror':
        return [_mirror_view(d, model, s)]
    return [_conclude_view(d, model, s)]


def presentation(values):
    view = phase_views(decode_value(values))[0]
    left, right = view['derivation']['items']
    return {'formula_title': view['title'], 'formula_explanation': '$$' + view['proof'] + '$$',
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def _attach_lines(part, values):
    model = solve(values['description'])
    x = values['description']['variable']
    phase = values['phase']
    if values['description'].get('route') in ('order', 'sign'):
        if phase == 'conclude' and isinstance(model['solution'], sp.Interval):
            part['completion_number_line'] = _number_line(x, r'\text{解集}', model['solution'])
        return
    if phase == 'known' and isinstance(model['known_solution'], sp.Interval):
        part['completion_number_line'] = _number_line(x, r'\text{已知范围内的解}', model['known_solution'])
    elif phase == 'mirror' and isinstance(model['mirrored_solution'], sp.Interval):
        part['completion_number_line'] = _number_line(x, r'\text{对称范围内的解}', model['mirrored_solution'])
    elif phase == 'conclude' and isinstance(model['solution'], sp.Interval):
        part['completion_number_line'] = _number_line(x, r'\text{解集}', model['solution'])


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
        _attach_lines(parts[-1], values)
    return {'parts': parts, 'diagnostics': []}
