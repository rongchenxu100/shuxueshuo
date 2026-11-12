"""T5 boards use only given symmetries, exact input pairings and proved values."""
import sympy as sp

from ...problem_understanding.notation_parser import parse
from ..parity_extension_math import ARGUMENT, _replace
from ..symmetry_relation_math import _substitute, domain_set, image, solve
from .absolute_graph_presentation import choice_card
from .domain_visuals import exact_math
from .interaction_graphs import _pieces, short_label
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .symmetry_presentation import _source_latex


def _value(f, x, a=1, b=0):
    return ('' if a == 1 else '-') + f + '('+latex(x)+')' + ('+' if b > 0 else '') + (latex(b) if b else '')


def target_math(d):
    if d['source']['kind'] != 'finite_sum':
        return _source_latex(d['goal_ast']['target'], 'x')
    return '+'.join(_sum_term(term) for term in d['goal_ast']['terms'])


def _sum_term(term):
    body = _source_latex(term['target'], 'x')
    if 'index' not in term:
        return body
    # A sum binds the entire original summand, not just its first addend.
    if term['target'][0] in ('+', '-'):
        body = rf'\left({body}\right)'
    k = term['index'][1].rsplit(':', 1)[-1]
    return rf'\sum_{{{k}={term["lower"]}}}^{{{term["upper"]}}}' + body


def _relation(e, f):
    x = sp.Symbol('x', real=True)
    return (f+'('+latex(2*e['a']-x)+')='+_value(f, x, e['sign'], e['offset'])
            + rf'\quad(x\in {latex(e["scope"])})')


def _read(title, question, given, answer, proof):
    view = choice_card(title, question, '已知条件', _lines(given), '关系', answer, [], _lines(proof))
    view.update(interaction={'type': 'read'}, expected_answer={})
    return view


def _pair_lines(e, u):
    v = 2*e['a']-u
    marks = sorted({e['a'], u, v})
    pad = max(float(marks[-1]-marks[0])*.25, 1.)
    result = []
    for label, scope, point in [('原输入范围', e['scope'], u),
                                ('配对后的范围', image(e['scope'], -1, 2*e['a']), v)]:
        intervals, points = _pieces(scope)
        result.append({'variable': 'x', 'label': label + r'\quad x=' + latex(point),
                       'bounds': [float(marks[0])-pad, float(marks[-1])+pad],
                       'ticks': [{'at': float(c), 'label': short_label(c), 'exact': exact_math(c)} for c in marks],
                       'intervals': [{'left': None if i.start == -sp.oo else float(i.start),
                                      'right': None if i.end == sp.oo else float(i.end),
                                      'left_closed': not i.left_open, 'right_closed': not i.right_open,
                                      'exact': exact_math(i)} for i in intervals],
                       'points': [{'at': float(c), 'label': short_label(c), 'exact': exact_math(c)}
                                  for c in sorted(set(points) | {point})],
                       'exact_set': exact_math(scope)})
    return result


def source_math(d):
    """Source AST only: shared by reading and teaching, without solving the goal."""
    f = d['function']
    source = []
    for r in d['relations']:
        ast = r['ast']
        if ast[0] == 'function_graph_symmetry':
            coords = [_source_latex(c, 'x') for c in ast[3:]]
            source.append(r'\text{图像关于 }' + ('x='+coords[0] if ast[2] == 'axis' else '('+','.join(coords)+')') + r'\text{ 对称}')
        elif ast[0] == 'function_parity':
            source.append(f+r'\text{ 为'+{'odd':'奇函数','even':'偶函数','both':'既奇又偶的函数'}[ast[2]]+'}')
        else:
            body = _replace(ast[4], ['bound', ast[2]], ARGUMENT)
            variable = parse(r['expression'])[2]
            scope = d['domain_ast'] if ast[3][:2] == ['call', 'Dom'] else ast[3]
            source.append(_source_latex(body[1], variable)+'='+_source_latex(body[2], variable)
                          + r'\quad('+variable+r'\in '+_source_latex(scope, variable)+')')
    source += [_source_latex(r['ast'][1], 'x')+'='+_source_latex(r['ast'][2], 'x') for r in d['value_equations']]
    source.insert(0, r'D='+latex(domain_set(d['domain_ast'])))
    return source


def _sum_groups(d, m):
    """Group only an exact repeating coefficient pattern already proved for every index."""
    if d['source']['kind'] != 'finite_sum':
        return []
    views = []
    for block, term in enumerate(d['goal_ast']['terms']):
        if 'index' not in term:
            continue
        rows = [r for r in m['groups'] if r['block'] == block]
        signatures = [(*r['coefficients'], r['constant']) for r in rows]
        size = next((p for p in range(1, min(16, len(rows)//2)+1)
                     if all(s == signatures[i % p] for i, s in enumerate(signatures))), None)
        if size is None:
            continue
        count, remainder = divmod(len(rows), size)
        first = [r['index'] for r in rows[:size]]
        tail = [r['index'] for r in rows[count*size:]]
        def written(indices, term=term):
            return '+'.join(_source_latex(_substitute(term['target'], term['index'], sp.Integer(i)), 'x') for i in indices)
        group = written(first)
        grouped = rf'{count}\left({group}\right)' + ('+'+written(tail) if tail else '')
        k = term['index'][1].rsplit(':', 1)[-1]
        expression = _sum_term(term)
        grouping = rf'{len(rows)}={count}\times{size}+{remainder}'
        view = _read('分组并保留余项', '按已证明的函数值关系分组，完整组之后的项仍要计入。',
                     [expression, grouping], grouped, [grouping, expression+'='+grouped])
        lines = []
        for label, indices in [(rf'每组 {size} 项，共 {count} 组', first), (rf'剩余 {remainder} 项', tail)]:
            if not indices:
                continue
            points = [{'at': i, 'label': str(i), 'exact': exact_math(sp.Integer(i))} for i in indices]
            lines.append({'variable': k, 'label': label,
                          'bounds': [min(indices)-1, max(indices)+1], 'ticks': points,
                          'intervals': [], 'points': points, 'exact_set': exact_math(sp.FiniteSet(*indices))})
        view['condition_number_lines'] = lines
        views.append(view)
    return views


def phase_views(values):
    d, phase = values['description'], values['phase']
    m, f = solve(d), d['function']
    source = source_math(d)
    laws = [_relation(e, f) for e in m['edges']]
    if phase == 'rewrite':
        views = []
        for e in m['edges']:
            inputs = [r['input'] for r in m['maps'] if e['scope'].contains(r['input']) is sp.true]
            if not inputs:
                continue
            u = next((q for q in inputs if q != e['a']), inputs[0])
            v = 2*e['a']-u
            wrong = list(dict.fromkeys(q for q in [u, -u, e['a']-u, v+1] if q != v))
            pair = rf'{latex(u)}\mapsto {latex(v)}'
            proof = [rf'{latex(2*e["a"])}-({latex(u)})={latex(v)}', _relation(e, f),
                     f+'('+latex(v)+')='+_value(f, u, e['sign'], e['offset'])]
            view = choice_card('找出配对的输入', rf'这条对称关系把输入 $x$ 变为 ${latex(2*e["a"])}-x$。'
                               rf'输入为 ${latex(u)}$ 时，配对的输入是多少？', '已知条件', _lines(source),
                               '输入配对', pair, [rf'{latex(u)}\mapsto {latex(q)}' for q in wrong[:3]], _lines(proof))
            view['condition_number_lines'] = _pair_lines(e, u)
            views.append(view)
        if m['extension']['kind'] == 'dihedral':
            ext, x = m['extension'], sp.Symbol('x', real=True)
            a, b = ext['base_interval'].start, ext['base_interval'].end
            input_path = ('x'+r'\xrightarrow{\text{第一次对称}}'+latex(2*a-x)
                          + r'\xrightarrow{\text{第二次对称}}'+latex(x+2*(b-a)))
            law = f+'('+latex(x+ext['step'])+')='+_value(f, x, ext['sign'], ext['offset'])
            views.append(_read('连续使用两次对称关系', '按顺序使用两条关系，同时记录输入的变化和函数值的变化。',
                               [*laws, input_path], law, [input_path, *laws, law,
                               *([r'\text{一个周期为 }'+latex(ext['period'])] if ext['period'] is not None else [])]))
        return views or [_read('写出对称关系', '先明确关系适用的范围。', source, _lines(laws), laws)]
    target, proof = target_math(d), m['proof']
    rewritten = []
    for row in m['maps'][:12]:
        if row['input'] != row['base'] or row['factor'] != 1 or row['offset']:
            rewritten.append(f+'('+latex(row['input'])+')='+_value(f, row['base'], row['factor'], row['offset']))
    for row, b in zip(m['rows'], m['rhs']):
        if any(row):
            expr = sum((a*sp.Function(f)(q) for a, q in zip(row, m['bases'])), sp.S.Zero)
            rewritten.append(latex(expr)+'='+latex(b))
    reduced = sum((a*sp.Function(f)(q) for a, q in zip(m['target'], m['bases'])), m['constant'])
    reduction = target+'='+latex(reduced)
    answer = target + ('='+latex(proof['value']) if proof['status'] == 'determined' else r'\text{ 不能唯一确定}')
    if proof['status'] == 'determined':
        candidates = [proof['value']+1, proof['value']-1, -proof['value']]
        wrong = [target+'='+latex(v) for v in dict.fromkeys(candidates) if v != proof['value']]
    else:
        wrong = [target+'='+latex(sum((a*z for a, z in zip(m['target'], w)), m['constant'])) for w in proof['witnesses']]
    return [*_sum_groups(d, m), choice_card('求出函数值之和' if d['source']['kind'] == 'finite_sum' else '求出所求的值',
                        '把每一项换成对应的基准函数值，再合并系数和常数；所求结果是什么？',
                        '已知与改写', _lines([*source, *rewritten]), '结论', answer, wrong[:3],
                        _lines([*laws, *rewritten, reduction, answer]))]
