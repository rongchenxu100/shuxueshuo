"""T5 boards use only given symmetries, exact input pairings and proved values."""
import sympy as sp

from ...problem_understanding.notation_parser import parse
from ..function_symmetry_iteration import Orbit
from ..parity_extension_math import ARGUMENT, _replace
from ..symmetry_relation_math import X, _equation, _substitute, domain_set, image, rational, solve
from .absolute_graph_presentation import choice_card
from .domain_visuals import exact_math
from .interaction_graph_contract import validate_graph
from .interaction_graphs import _pieces, short_label
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .symmetry_presentation import _source_latex


# The renderer accepts at most eight segments; bound the work before merging
# collinear samples, including when a tiny period crosses a large plot window.
MAX_EXAMPLE_SAMPLES = 64


def _plain(e):
    """SVG text cannot typeset LaTeX: 2 - x → 2-x."""
    return sp.sstr(e).replace('*', '').replace(' ', '')


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


def _example(d, m):
    """A zigzag f meeting every given condition: linear on the base interval, extended by the two reflections.

    Returns (f, breakpoints, step) or None when the relations do not close into a translation
    or a printed value cannot be met by one linear base piece."""
    ext = m['extension']
    if ext['kind'] != 'dihedral':
        return None
    orbit = Orbit(m['edges'], m['domain'])
    a, b = ext['base_interval'].start, ext['base_interval'].end
    known = {q: v for q, v in zip((a, b), ext['fixed_values']) if v is not None}
    equations = [_equation(r['ast'], [d['function']], X) for r in d['value_equations']]
    for terms, rhs in equations:
        if len(terms) == 1:
            ((_, q), k), = terms.items()
            r = orbit.reduce(rational(q))
            value = (rhs/k - r['offset'])/r['factor']
            if known.setdefault(r['base'], value) != value:
                return None
    if not known:
        known[a] = sp.S.Zero
    xs = sorted(known)
    known.setdefault(a, known[xs[0]] - (xs[0]-a))
    known.setdefault(b, known[xs[-1]] + (b-xs[-1]))
    xs = sorted(known)

    def base(t):
        for lo, hi in zip(xs, xs[1:]):
            if lo <= t <= hi:
                return known[lo] + (known[hi]-known[lo])*(t-lo)/(hi-lo)
        raise ValueError('symmetry.example_outside_base')

    def f(t):
        r = orbit.reduce(sp.nsimplify(t))
        return r['factor']*base(r['base']) + r['offset']
    for terms, rhs in equations:
        if sum(k*f(q) for (_, q), k in terms.items()) != rhs:
            return None
    return f, xs, ext['step']


def _edge_text(e, f):
    """(short name, how the pair's values relate) for f(2a-x) = sign·f(x) + offset."""
    a, c = e['a'], e['offset']
    if e['sign'] == 1:
        return rf'关于直线 $x={latex(a)}$ 对称', '函数值相同'
    name = '关于原点对称' if a == 0 and c == 0 else rf'关于点 $({latex(a)},{latex(c/2)})$ 对称'
    return name, '函数值互为相反数' if c == 0 else rf'两个函数值的和为 ${latex(c)}$'


def _marks(e):
    if e['sign'] == 1:
        return {'axes': [{'x': float(e['a']), 'label': 'x=' + short_label(e['a'])}]}
    return {'points': [{'x': float(e['a']), 'label': '对称中心', 'place': 'below-right'}]}


def _example_graph(d, m, example, caption, guides=(), edges=(), span=(), level=False):
    f_ex, xs, step = example
    a = xs[0]
    anchors = [g[0] for g in guides] + [e['a'] for e in edges] + [a, *span]
    lo, hi = sp.floor(min(anchors)) - 1, sp.ceiling(max(anchors)) + 1
    if hi - lo < 2*step:
        hi = lo + 2*step
    spans, samples = [], 2
    for base in sorted({t for q in xs for t in (q, 2*a - q)}):
        first, last = int(sp.ceiling((lo-base)/step)), int(sp.floor((hi-base)/step))
        samples += max(0, last-first+1)
        if samples > MAX_EXAMPLE_SAMPLES:
            return None
        spans.append((base, first, last))
    cuts = {lo, hi}
    for base, first, last in spans:
        cuts.update(base + k*step for k in range(first, last+1))
    cuts = sorted(cuts)
    values = [f_ex(t) for t in cuts]
    pieces = []
    for (x0, y0), (x1, y1) in zip(zip(cuts, values), zip(cuts[1:], values[1:])):
        slope = (y1-y0)/(x1-x0)
        if pieces and pieces[-1][2] == slope:
            pieces[-1][1] = x1
        else:
            pieces.append([x0, x1, slope, y0 - slope*x0])
    if len(pieces) > 8:
        return None
    ys = [float(v) for v in values] + [0.0]
    pad = max(1.0, (max(ys) - min(ys))*.15)
    params = {'segments': [{'coefficients': [0, float(k), float(c)], 'interval': [float(p), float(q)],
                            'interval_closed': [True, True]} for p, q, k, c in pieces],
              'bounds': [float(lo), float(hi), min(ys) - pad, max(ys) + pad],
              'interval': [float(lo), float(hi)], 'interval_closed': [True, True], 'points': [],
              'xTicks': [[float(v), short_label(v)] for v in sorted({sp.S.Zero, *(e['a'] for e in edges)})],
              'variable': 'x', 'title': f'{d["function"]}(x) 的示意图像',
              'description': '折线是满足题设的一个示意函数；虚线标出配对的输入和它们的函数值。'}
    for e in edges:
        for key, value in _marks(e).items():
            if key == 'points' and len(guides) > 2:
                value = [{k: v for k, v in p.items() if k not in ('label', 'place')} for p in value]
            params[key] = params.get(key, []) + value
    if guides:
        params['guides'] = [{'x': float(g[0]), 'label': g[1],
                             'value_label': g[2] if len(g) > 2 else f'{d["function"]}({g[1]})'} for g in guides]
    if level:
        params['level'] = float(f_ex(guides[0][0]))
    caption = (rf'示意图：取一个满足题设的折线函数（在 ${latex(sp.Interval(*xs[::len(xs)-1]))}$ 上是一次函数，'
               '再按对称关系延拓），只用来看对称，不代表 $' + d['function'] + '$ 的解析式；' + caption + '。')
    try:
        return validate_graph({'kind': 'piecewise_curve', 'params': params, 'caption': caption})
    except ValueError:
        return None


def _period_lines(f, x, ext):
    """A period is claimed only after f(x+T)=f(x) is written out."""
    p, c = ext['step'], ext['offset']
    if ext['period'] is None:
        return []
    if ext['sign'] == 1:
        return [f+'('+latex(x+p)+')='+f+r'(x)\Rightarrow \text{周期为 }'+latex(p)]
    tail = '' if c == 0 else ('+' if c > 0 else '')+latex(c)
    return [f+'('+latex(x+2*p)+')='+_value(f, x+p, -1, c)
            + r'=-\left('+_value(f, x, -1, c)+r'\right)'+tail+'='+f+'(x)',
            r'\Rightarrow \text{周期为 }'+latex(2*p)]


def _period_walk(d, m, example, law):
    """f(x+p) = c - f(x) used twice, drawn as a point walked x → x+p → x+2p back to its own height."""
    if example is None:
        return []
    f, ext = d['function'], m['extension']
    p, c = ext['step'], ext['offset']
    a, b = ext['base_interval'].start, ext['base_interval'].end
    x, t = sp.Symbol('x', real=True), (a + b)/2
    flip = '-m' if c == 0 else _plain(c) + '-m'
    at = [(t + k*p, _plain(x + k*p), v) for k, v in enumerate(['m', flip, 'm'])]
    there = lambda k, v: f+'('+latex(x + k*p)+')='+v
    flip_tex = '-m' if c == 0 else latex(c) + '-m'
    group = '再用一次关系，看出周期'
    shown = rf'在示意图上取横坐标为 $x$ 的点（取 $x={latex(t)}$），记 ${f}(x)=m$'
    graphs = [_example_graph(d, m, example, caption, at[:n], span=[at[-1][0]], level=n == 3)
              for n, caption in [(1, shown), (2, rf'由 ${law}$，横坐标为 ${latex(x + p)}$ 的点函数值是 ${flip_tex}$'),
                                 (3, rf'横坐标为 $x$ 与 ${latex(x + 2*p)}$ 的两点一样高（水平虚线），'
                                     rf'即 ${f}({latex(x + 2*p)})={f}(x)$；对每个 $x$ 都成立，所以周期为 ${latex(2*p)}$')]]
    if None in graphs:
        return []
    wrong1 = [v for v in dict.fromkeys(['m', '0', '-2m', '-m']) if v != flip_tex]
    wrong2 = [v for v in dict.fromkeys(['-m', flip_tex, '0', '2m']) if v != 'm']
    cards = [choice_card(rf'从 $x$ 走到 ${latex(x + p)}$', shown + rf'。由 ${law}$，横坐标为 ${latex(x + p)}$ 的点函数值是多少？',
                         '已知条件', _lines([law]), '函数值', there(1, flip_tex), [there(1, v) for v in wrong1[:3]],
                         _lines([there(1, _value(f, x, -1, c)) + '=' + flip_tex])),
             choice_card(rf'从 ${latex(x + p)}$ 再走到 ${latex(x + 2*p)}$',
                         rf'把 ${law}$ 中的 $x$ 换成 ${latex(x + p)}$ 再用一次，横坐标为 ${latex(x + 2*p)}$ 的点函数值是多少？',
                         '已知条件', _lines([law, there(1, flip_tex)]), '函数值', there(2, 'm'),
                         [there(2, v) for v in wrong2[:3]], _lines(_period_lines(f, x, ext)))]
    for card, (stem, done) in zip(cards, zip(graphs, graphs[1:])):
        card.update(graph=stem, completion_graph=done, card_group='period', card_group_title=group)
    return cards


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
        example = _example(d, m)
        x = sp.Symbol('x', real=True)
        ext = m['extension']
        span = [e['a'] for e in m['edges']]
        for e in m['edges']:
            inputs = [r['input'] for r in m['maps'] if e['scope'].contains(r['input']) is sp.true]
            if inputs:
                u = next((q for q in inputs if q != e['a']), inputs[0])
                span += [u, 2*e['a']-u]
        if ext['kind'] == 'dihedral':
            lo, hi = ext['base_interval'].start, ext['base_interval'].end
            span += [lo - (hi-lo)/2, (lo+hi)/2 + ext['step']]
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
            name, change = _edge_text(e, f)
            paired = ('-x' if e['a'] == 0 else latex(2*e['a']) + '-x')
            question = (rf'图像{name}：输入 $x$ 与 ${paired}$ 的中点是 ${latex(e["a"])}$，{change}。'
                        rf'输入为 ${latex(u)}$ 时，配对的输入是多少？')
            view = choice_card(f'利用{name}找配对的输入', question, '已知条件', _lines(source),
                               '输入配对', pair, [rf'{latex(u)}\mapsto {latex(q)}' for q in wrong[:3]], _lines(proof))
            stem = done = None
            if example is not None:
                stem = _example_graph(d, m, example, rf'图像{name}', [(u, short_label(u))], [e], span)
                done = _example_graph(d, m, example, rf'${latex(u)}$ 与 ${latex(v)}$ 的中点是 ${latex(e["a"])}$，{change}',
                                      [(u, short_label(u)), (v, short_label(v))], [e], span)
            if stem is not None and done is not None:
                view['graph'], view['completion_graph'] = stem, done
            else:
                view['condition_number_lines'] = _pair_lines(e, u)
            views.append(view)
        if ext['kind'] == 'dihedral':
            a, b = ext['base_interval'].start, ext['base_interval'].end
            input_path = ('x'+r'\xrightarrow{\text{第一次对称}}'+latex(2*a-x)
                          + r'\xrightarrow{\text{第二次对称}}'+latex(x+2*(b-a)))
            law = f+'('+latex(x+ext['step'])+')='+_value(f, x, ext['sign'], ext['offset'])
            period = _period_lines(f, x, ext)
            walk = _period_walk(d, m, example, law) if ext['sign'] == -1 and ext['period'] is not None else []
            view = _read('连续使用两次对称关系', '按顺序使用两条关系，同时记录输入的变化和函数值的变化。',
                         [*laws, input_path], law, [input_path, *laws, law, *([] if walk else period)])
            first = next(e for e in m['edges'] if e['a'] == a)
            second = next(e for e in m['edges'] if e['a'] == b)
            if example is not None:
                t = (a + b)/2
                steps = [(t, 'x'), (2*a - t, _plain(2*a - x)), (t + ext['step'], _plain(x + ext['step']))]
                (n1, c1), (n2, c2) = _edge_text(first, f), _edge_text(second, f)
                text = (rf'取 $x={latex(t)}$：先{n1}，到 ${latex(2*a - t)}$，{c1}；'
                        rf'再{n2}，到 ${latex(t + ext["step"])}$，{c2}；所以 ${law}$')
                graph = _example_graph(d, m, example, text, steps, [first, second], span)
                if graph is not None:
                    view['graph'] = graph
            views += [view, *walk]
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
