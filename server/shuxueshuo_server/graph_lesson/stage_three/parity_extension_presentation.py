"""FP-T3 cards: map the input, substitute -x, apply parity, then join, check zero and state the range."""
import re
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_parity import reflect_ast
from ..parity_extension_math import (
    SIGNS,
    _agree,
    points,
    radicands,
    ranges,
    reflect,
    region,
    rule_expression,
    rule_rows,
    rules,
    solve,
    symbols,
)
from ..stage_one.function_domain import expression_latex
from .absolute_graph_presentation import choice_card
from .domain_visuals import exact_math
from .interaction_graphs import _float, short_label
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .parity_parameter_presentation import PROPERTY, _display_ast, _read, board_lines
from .trajectory import decode_value


def range_latex(s, x, abstract=False):
    """With an abstract domain D every printed range is read inside D; all of it is x∈D."""
    if isinstance(s, sp.FiniteSet) and len(s) == 1:
        return x + '=' + latex(next(iter(s)))
    if isinstance(s, sp.Interval):
        lower = '<' if s.left_open else r'\le '
        upper = '<' if s.right_open else r'\le '
        if s.start == -sp.oo and s.end == sp.oo:
            return x + (r'\in D' if abstract else r'\in\mathbb R')
        if s.start == -sp.oo:
            return x + upper + latex(s.end)
        if s.end == sp.oo:
            return x + ('>' if s.left_open else r'\ge ') + latex(s.start)
        return latex(s.start) + lower + x + upper + latex(s.end)
    return x + r'\in ' + latex(s)


def _when(s, x, abstract=False):
    return range_latex(s, x, abstract) + r'\text{ 时，}'


def _distinct(correct, candidates, domain, variable):
    """Distractors differ mathematically on the range actually being discussed."""
    kept = []
    for value in candidates:
        if not _agree(value, correct, domain, variable) and all(not _agree(value, v, domain, variable) for v in kept):
            kept.append(value)
    return kept


def _number_line(variable, label, s):
    ends = sorted({sp.S.Zero, *(e for e in (s.start, s.end) if e not in (-sp.oo, sp.oo))})
    low, high = _float(ends[0]), _float(ends[-1])
    pad = max((high - low) * 0.25, 1.0)
    return {'variable': variable, 'label': label, 'bounds': [low - pad, high + pad],
            'intervals': [{'left': None if s.start == -sp.oo else _float(s.start),
                           'right': None if s.end == sp.oo else _float(s.end),
                           'left_closed': not s.left_open, 'right_closed': not s.right_open,
                           'exact': exact_math(s)}],
            'points': [],
            'ticks': [{'at': _float(v), 'label': short_label(v), 'exact': exact_math(v)} for v in ends],
            'exact_set': exact_math(s)}


def _printed(text, x):
    """Textbook spelling: 3x and x(1+x); a substituted -x stays parenthesized."""
    text = re.sub(r'(?<=[0-9A-Za-z)}])\s*\\cdot\s*(?=[A-Za-z(\\])', '', text)
    return re.sub(rf'(?<=[+\-])\s*-{re.escape(x)}(?![0-9A-Za-z^])', f'(-{x})', text)


def _source(d):
    x, f = d['variable'], d['function']
    ast = _display_ast(d['rule_ast'])
    domain, known, requested, mirrored = ranges(d)
    return {'x': x, 'f': f, 'fx': rf'{f}({x})', 'fneg': rf'{f}(-{x})',
            'rule': _printed(expression_latex(ast, x), x),
            'reflected': _printed(expression_latex(reflect_ast(ast), x), x),
            'printed_known': region(d['rule_domain_ast']), 'domain': domain,
            'known': known, 'requested': requested, 'mirrored': mirrored, 'mapped': reflect(mirrored),
            'property': PROPERTY[d['property']], 'sign': SIGNS[d['property']],
            'abstract': d['domain_ast'] is None, 'points': points(d)}


def _map_proof(s):
    return _lines([range_latex(s['mirrored'], s['x']) + r'\Rightarrow ' + range_latex(s['mapped'], '-' + s['x']),
                   latex(s['mapped']) + r'\subseteq ' + latex(s['known'])])


def _conclusion(branches, s):
    """Branches with expression None are the free part: stated, never filled in."""
    fx, x = s['fx'], s['x']
    fixed = [(d, e) for d, e in branches if e is not None]
    free = sp.Union(*(d for d, e in branches if e is None))
    if len(fixed) == 1:
        (domain, expr), = fixed
        text = _when(domain, x, s['abstract']) + fx + '=' + latex(expr)
    else:
        rows = r'\\'.join(latex(expr) + ',&' + range_latex(domain, x, s['abstract']) for domain, expr in fixed)
        text = fx + r'=\begin{cases}' + rows + r'\end{cases}'
    if free == sp.S.EmptySet:
        return text
    if free == sp.FiniteSet(0):
        return text + rf'\text{{；}}{s["f"]}(0)=c\ (c\in\mathbb R)\text{{，不能唯一确定}}'
    return text + r'\text{；}' + range_latex(free, x, s['abstract']) + r'\text{ 时不能唯一确定}'


def _same_rule(a, b, x):
    if sp.Union(*(d for d, _ in a)) != sp.Union(*(d for d, _ in b)):
        return False
    for da, ea in a:
        for db, eb in b:
            both = da & db
            if both == sp.S.EmptySet:
                continue
            if (ea is None) != (eb is None) or (ea is not None and not _agree(ea, eb, both, x)):
                return False
    return True


def _substitute_proof(s, substituted):
    shown = latex(substituted)
    if re.sub(r'\s+', '', shown) == re.sub(r'\s+', '', s['reflected']):
        return s['fneg'] + '=' + shown
    return s['fneg'] + '=' + s['reflected'] + '=' + shown


def _write_back_proof(s, substituted, expression):
    if s['sign'] == 1:
        return s['fx'] + '=' + s['fneg'] + '=' + latex(expression)
    return s['fx'] + '=-' + s['fneg'] + r'=-\left(' + latex(substituted) + r'\right)=' + latex(expression)


def _multiple_views(values):
    d, phase = values['description'], values['phase']
    s, x = _source(d), d['variable']
    if d['property'] == 'both':
        proof = _lines([s['fneg'] + '=' + s['fx'], s['fneg'] + '=-' + s['fx'],
                        '2' + s['fx'] + '=0', _when(s['requested'], x, s['abstract']) + s['fx'] + '=0'])
        return [_read('既奇又偶时函数值为零', '对定义域内任意输入，两种关系同时成立。',
                      '已知性质', r'\text{既是奇函数又是偶函数}', '函数值', s['fx'] + '=0', proof)]
    if phase in ('map', 'substitute', 'write_back'):
        views = []
        for row, (known, _, _) in zip(rule_rows(d), rules(d)):
            mirrored = s['mirrored'] & reflect(known)
            if mirrored == sp.S.EmptySet:
                continue
            leaf = {k: deepcopy(v) for k, v in d.items() if k != 'local_rules'}
            leaf.update(rule_ast=row['rule_ast'], rule_domain_ast=row['domain_ast'])
            # Preserve the exact requested slice without converting algebraic endpoints to decimals.
            leaf['_presentation_range'] = mirrored
            views.extend(phase_views({**values, 'description': leaf}))
        return views
    model = solve(d)
    fixed = [(b['set'], b['expression']) for b in model['branches']]
    branches = fixed + ([(model['free_domain'], None)] if model['free_domain'] != sp.S.EmptySet else [])
    given, reflected = [], []
    for row, (known, _, _) in zip(rule_rows(d), rules(d)):
        source = _printed(expression_latex(_display_ast(row['rule_ast']), x), x)
        given.append(_when(known, x, s['abstract']) + s['fx'] + '=' + source)
        mirror = s['mirrored'] & reflect(known)
        if mirror != sp.S.EmptySet:
            reflected.append(_when(mirror, x, s['abstract']) + s['fx'] + '='
                             + ('' if s['sign'] == 1 else '-') + r'\left('
                             + _printed(expression_latex(reflect_ast(_display_ast(row['rule_ast'])), x), x)
                             + r'\right)')
    conclusion = _conclusion(branches, s)
    proof = _lines([*given, *reflected,
                    *([s['f'] + '(0)=0'] if model['zero_status'] == 'forced_zero' else []), conclusion])
    return [_read('合并各段并写出结论', '每条解析式都要注明适用范围，端点按原题条件处理。',
                  '已知各段', _lines(given), '结论', conclusion, proof)]


def phase_views(values):
    d, phase = values['description'], values['phase']
    if d.get('local_rules') or d['property'] == 'both':
        return _multiple_views(values)
    s = _source(d)
    if '_presentation_range' in d:
        s.update(mirrored=d['_presentation_range'], mapped=reflect(d['_presentation_range']))
    x, fx, fneg = s['x'], s['fx'], s['fneg']
    relation = r'\text{' + s['property'] + '：}' + fx + '=' + ('' if s['sign'] == 1 else '-') + fneg
    given_rows = [_when(s['printed_known'], x) + fx + '=' + s['rule'],
                  *(rf'{s["f"]}({latex(c)})={latex(v)}' for c, v in sorted(s['points'].items())),
                  relation]
    given = _lines(given_rows)
    target = _when(s['mirrored'], x)
    if phase == 'map':
        wrong = [c for c in (s['mirrored'], reflect(s['known'])) if not s['mapped'].is_subset(c)]
        wrong = [c for i, c in enumerate(wrong) if c not in wrong[:i]]
        return [choice_card('把输入换到已知一侧', rf'要求 ${range_latex(s["mirrored"], x)}$ 时的 ${fx}$，'
                            rf'先看相反数 $-{x}$ 的范围。这时 $-{x}$ 满足什么？',
                            '已知与所求', given, '$-' + x + '$ 的范围',
                            target + range_latex(s['mapped'], '-' + x),
                            [target + range_latex(c, '-' + x) for c in wrong], _map_proof(s))]
    variable = symbols(d)
    rule = rule_expression(d['rule_ast'], variable)
    substituted = sp.expand(rule.xreplace({variable: -variable}))
    expression = sp.expand(s['sign'] * substituted)
    if phase == 'substitute':
        wrong = _distinct(substituted, [sp.expand(rule), -substituted, sp.expand(-rule)], s['mirrored'], variable)
        return [choice_card('代入相反输入', rf'$-{x}$ 在已知范围内，把 $-{x}$ 作为整体代入已知解析式中每一个 ${x}$。'
                            rf'${fneg}$ 等于什么？',
                            '已知解析式', _lines([_when(s['printed_known'], x) + fx + '=' + s['rule'],
                                                  target + range_latex(s['mapped'], '-' + x)]),
                            f'${fneg}$', target + fneg + '=' + latex(substituted),
                            [target + fneg + '=' + latex(v) for v in wrong[:3]],
                            _substitute_proof(s, substituted))]
    if phase == 'write_back':
        terms = sp.Add.make_args(substituted)
        partial = sp.expand(-terms[0] + sum(terms[1:], sp.S.Zero)) if len(terms) > 1 else substituted
        wrong = _distinct(expression, [-expression, partial, sp.expand(rule)], s['mirrored'], variable)
        return [choice_card('用奇偶性换回 f(x)', rf'题给 ${s["f"]}$ 是{s["property"]}，'
                            rf'奇偶性把 ${fx}$ 与 ${fneg}$ 联系起来。${range_latex(s["mirrored"], x)}$ 时 ${fx}$ 等于什么？',
                            '已求出的式子', _lines([target + fneg + '=' + latex(substituted), relation]),
                            f'${fx}$', target + fx + '=' + latex(expression),
                            [target + fx + '=' + latex(v) for v in wrong[:3]],
                            _write_back_proof(s, substituted, expression))]
    model = solve(d)
    free = model['free_domain']
    fixed = [(b['set'], b['expression']) for b in model['branches']]
    branches = fixed + ([(free, None)] if free != sp.S.EmptySet else [])
    values, f = s['points'], s['f']
    given_points = sp.FiniteSet(*values)
    lines = [range_latex(s['mirrored'], x) + r'\Rightarrow ' + range_latex(s['mapped'], '-' + x),
             _substitute_proof(s, substituted), _write_back_proof(s, substituted, expression)]
    extra = s['requested'] - s['mirrored']
    given_part = s['requested'] & s['known']
    if given_part != sp.S.EmptySet:
        lines.append(_when(given_part, x, s['abstract']) + fx + '=' + s['rule'])
    for c in sorted(values):
        if s['requested'].contains(c) is sp.true and s['known'].contains(c) is not sp.true:
            lines.append(rf'{f}({latex(c)})={latex(values[c])}')
        if (s['requested'].contains(-c) is sp.true and -c not in values
                and s['known'].contains(-c) is not sp.true and c != 0):
            outer = '' if s['sign'] == 1 else '-'
            lines.append(rf'{f}({latex(-c)})={outer}{f}({latex(c)})={latex(s["sign"] * values[c])}')
    zero = (extra - s['known'] - given_points).contains(0) is sp.true
    if zero and free.contains(0) is sp.true:
        lines.append(rf'{f}(-0)={f}(0)\Rightarrow {f}(0)\text{{ 不能唯一确定}}')
    elif zero:
        lines.append((r'0\in D\Rightarrow ' if s['abstract'] else '') + rf'{f}(0)=0')
        merged = next((e for dom, e in fixed if dom.contains(0) is sp.true and dom != sp.FiniteSet(0)), None)
        if merged is not None:
            lines.append(r'\left.\left(' + latex(merged) + r'\right)\right|_{' + x + '=0}=0')
    conclusion = _conclusion(branches, s)
    compact = model['answer_expression']
    folded = ([_when(s['requested'] - free, x, s['abstract']) + fx + '=' + latex(compact)]
              if len(fixed) > 1 and not isinstance(compact, sp.Piecewise) else [])
    proof = _lines([*lines, conclusion, *folded])
    if extra == sp.S.EmptySet:
        note = ('所求范围不含 $0$，不需要另求 ' + rf'${f}(0)$。') if s['requested'].contains(0) is not sp.true else ''
        return [_read('写出带范围的结论', '答案要写明适用的输入范围；' + note,
                      '原题条件', given, '结论', conclusion, proof)]
    at_zero = rule.subs(variable, 0) if s['known'].closure.contains(0) is sp.true or not radicands(rule) else None
    candidates = [[(s['requested'], expression)], [(s['mirrored'], expression)], [(s['requested'], rule)]]
    if zero and free.contains(0) is sp.true:
        rest = [(dom, e) for dom, e in fixed]
        candidates[:0] = [rest + [(sp.FiniteSet(0), sp.S.Zero)]]
        if at_zero is not None and at_zero.is_real:
            candidates.append(rest + [(sp.FiniteSet(0), at_zero)])
    elif zero and at_zero is not None and at_zero.is_real and at_zero != 0:
        candidates.append([(s['mirrored'], expression), (sp.FiniteSet(0), at_zero)])
    wrong = []
    for c in candidates:
        if not _same_rule(c, branches, variable) and all(not _same_rule(c, w, variable) for w in wrong):
            wrong.append(c)
    title = '检查零点并写出结论' if zero else '拼接已知部分并写出结论'
    whole = range_latex(s['requested'], x, s['abstract'])
    question = (('题目没有给出定义域，记为 $D$，它关于原点对称。' if s['abstract'] else '')
                + rf'所求范围 ${whole}$ 除了 ${range_latex(s["mirrored"], x)}$，'
                rf'还包含 ${range_latex(extra, x)}$。'
                + ((rf'题给 ${s["f"]}$ 是{s["property"]}，' + ('若 $0\\in D$，' if s['abstract'] else '且 $0$ 在定义域内，')
                    + '还要单独考虑 $x=0$。') if zero else
                   '这部分由已知解析式和题给函数值给出。' if (extra & given_points) != sp.S.EmptySet else
                   '这部分由已知解析式给出。')
                + rf'${whole}$ 时 ${fx}$ 的结论是什么？')
    return [choice_card(title, question, '已求出的式子',
                        _lines([target + fx + '=' + latex(expression), *given_rows]),
                        '结论', conclusion, [_conclusion(w, s) for w in wrong[:3]], proof)]


def presentation(values):
    views = phase_views(decode_value(values))
    view = views[0]
    left, right = view['derivation']['items']
    proof = view['proof'] if len(views) == 1 else _lines([v['proof'] for v in views])
    return {'formula_title': view['title'], 'formula_explanation': '$$' + proof + '$$',
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def _attach_lines(part, values):
    if values['phase'] != 'map':
        return
    s = _source(values['description'])
    x = s['x']
    if not all(isinstance(s[k], sp.Interval) for k in ('known', 'requested', 'mapped')):
        return
    part['condition_number_lines'] = [
        _number_line(x, r'\text{已知范围：}' + range_latex(s['known'], x), s['known']),
        _number_line(x, r'\text{所求范围：}' + range_latex(s['requested'], x, s['abstract']), s['requested'])]
    part['completion_number_line'] = _number_line(
        x, rf'-{x}\text{{ 的范围：}}' + range_latex(s['mapped'], '-' + x), s['mapped'])


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
