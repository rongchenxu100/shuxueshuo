"""T5 boards use only given symmetries, exact input pairings and proved values."""
import sympy as sp

from ...problem_understanding.notation_parser import parse
from ..function_symmetry_iteration import Orbit
from ..parity_extension_math import ARGUMENT, _replace
from ..symmetry_relation_math import X, _equation, _substitute, domain_set, image, rational, solve
from ..symmetry_walk import teaching_plan
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


def _example_graph(d, m, example, caption, guides=(), edges=(), span=(), level=False,
                   points=(), reflections=(), level_at=None):
    f_ex, xs, step = example
    a = xs[0]
    anchors = [g[0] for g in guides] + [e['a'] for e in edges] + [a, *span] + [p for p, _ in points]
    pad = min(sp.S.One, step/2)
    lo, hi = sp.floor(min(anchors) - pad), sp.ceiling(max(anchors) + pad)
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
            if key == 'points' and (len(guides) > 2 or points):
                value = [{k: v for k, v in p.items() if k not in ('label', 'place')} for p in value
                         if all(float(q) != p['x'] for q, _ in points)]
            params[key] = params.get(key, []) + value
    if guides:
        params['guides'] = [{'x': float(g[0]), 'label': g[1],
                             'value_label': g[2] if len(g) > 2 else f'{d["function"]}({g[1]})'} for g in guides]
    if level:
        params['level'] = float(f_ex(guides[0][0]))
    if level_at is not None:
        params['level'] = float(f_ex(level_at))
    params['points'] += [{'x': float(p), **({'label': label, 'place': 'above' if f_ex(p) >= 0 else 'below'}
                                            if label else {})} for p, label in points]
    if reflections:
        params['reflections'] = [{'from': float(r['from']), 'to': float(r['to']), 'center': float(r['center']),
                                  'kind': r['kind']} for r in reflections]
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


def _tex(e):
    """2-x, not sympy's leading-negative -x+2."""
    e = sp.expand(e)
    if not e.free_symbols:
        return latex(e)
    terms = sorted(sp.Add.make_args(e), key=lambda t: (t.could_extract_minus_sign(), not t.free_symbols))
    out = ''
    for t in terms:
        piece = latex(t)
        out += piece if not out or piece.startswith('-') else '+' + piece
    return out.replace(' ', '')


def _paren(e):
    e = sp.expand(e)
    return rf'\left({_tex(e)}\right)' if e.could_extract_minus_sign() or isinstance(e, sp.Add) else _tex(e)


def _coord(p, v, plain=False):
    show = _plain if plain else _tex
    return '(' + show(p) + ',' + show(v) + ')'


def _reflection(s):
    e = s['edge']
    return {'from': s['from'], 'to': s['to'], 'center': e['a'], 'kind': 'axis' if e['sign'] == 1 else 'center'}


def _wrong_points(s):
    u, v, fv = s['from'], s['to'], s['value_to']
    out = []
    for p, q in [(v, -fv), (-u, fv), (u, fv), (v, fv+1), (-v, fv), (v, fv-1)]:
        key = (sp.expand(p), sp.expand(q))
        if key != (sp.expand(v), sp.expand(fv)) and key not in out:
            out.append(key)
    return [_coord(p, q) for p, q in out[:3]]


def _call(f, k, p, c):
    """k·f(p) + c with k = ±1."""
    return ('-' if k == -1 else '') + f + '(' + _tex(p) + ')' + ('' if c == 0 else ('+' if c > 0 else '') + latex(c))


def _chain(f, steps, start_value=None):
    """f(target) = … back along the reflections … = value at the start point."""
    k, p, c = sp.S.One, steps[-1]['to'], sp.S.Zero
    shown = [_call(f, k, p, c)]
    for s in reversed(steps):
        e = s['edge']
        k, p, c = k*e['sign'], s['from'], c + k*e['offset']
        shown.append(_call(f, k, p, c))
    if start_value is not None:
        shown.append(_tex(k*start_value + c))
    return '='.join(dict.fromkeys(shown))


def _step_card(d, f, s, question, title, known_lines, picture, shown, labels, caption_tail=''):
    e = s['edge']
    name, change = _edge_text(e, f)
    img = _coord(s['to'], s['value_to'])
    proof = [rf'\dfrac{{{_tex(s["from"])}+{_paren(s["to"])}}}{{2}}={latex(e["a"])}', _chain(f, [s], s['value_from'])]
    view = choice_card(title, question, '已知', _lines([_relation(e, f), *known_lines]), '对称点', img,
                       _wrong_points(s), _lines(proof))
    stem = picture(shown | {s['from']}, labels | {s['from']}, [], [e], rf'图像{name}')
    done = picture(shown | {s['from'], s['to']}, {s['from'], s['to']}, [_reflection(s)], [e],
                   rf'${latex(s["from"])}$ 与 ${latex(s["to"])}$ 的中点是 ${latex(e["a"])}$，{change}，'
                   rf'得到点 ${img}$' + caption_tail)
    if stem is not None and done is not None:
        view['graph'], view['completion_graph'] = stem, done
    elif not sp.sympify(s['from']).free_symbols:
        view['condition_number_lines'] = _pair_lines(e, s['from'])
    return view


def _group(views, key, title):
    for view in views:
        view.update(card_group=key, card_group_title=title)
    return views


def _walk_views(d, m, plan, example, source):
    f, known = d['function'], plan['known']
    values = {k: v['value'] for k, v in known.items()}
    for w in plan['walks']:
        values[w['target']] = w['value']
        for s in w['steps']:
            values.setdefault(s['to'], s['value_to'])
    span = sorted({*values, *(e['a'] for e in m['edges'])})

    def picture(marked, labelled, reflections, edges, caption, level_at=None):
        if example is None:
            return None
        return _example_graph(d, m, example, caption, edges=edges, span=span, level_at=level_at,
                              points=[(p, _coord(p, values[p], True) if p in labelled else None) for p in sorted(marked)],
                              reflections=reflections)

    views, shown = [], {k for k, v in known.items() if v['reason'] == 'given'}
    used = set(plan['inputs']) | {w['steps'][0]['from'] for w in plan['walks'] if w['steps']}
    for k in [k for k, v in known.items() if v['reason'] == 'center' and k in used]:
        e, b = known[k]['edge'], known[k]['value']
        if e['a'] == 0 and e['offset'] == 0:
            lead = rf'${f}(x)$ 是奇函数，且 $0$ 在定义域内'
            proof = [rf'{f}(-0)=-{f}(0)', rf'{f}(0)=-{f}(0)', rf'2{f}(0)=0', rf'{f}(0)=0']
        else:
            lead = rf'图像关于点 $({latex(e["a"])},{latex(b)})$ 对称，且 ${latex(e["a"])}$ 在定义域内'
            proof = [f + '(' + latex(k) + ')=' + _value(f, k, -1, e['offset']), f + '(' + latex(k) + ')=' + latex(b)]
        wrong = [f'{f}({latex(k)})={latex(v)}' for v in dict.fromkeys([b+1, b-1, -b-2]) if v != b][:2]
        view = choice_card('先找出图像上确定的点', lead + rf'。${f}({latex(k)})$ 等于多少？', '已知条件', _lines(source),
                           '函数值', f'{f}({latex(k)})={latex(b)}', [*wrong, rf'{f}({latex(k)})\text{{ 不能确定}}'],
                           _lines(proof))
        given = '、'.join(rf'$({latex(p)},{latex(values[p])})$' for p in sorted(shown))
        stem = picture(shown, shown, [], [], rf'已知图像上的点 {given}' if given else '还没有确定的点')
        shown.add(k)
        done = picture(shown, shown, [], [], rf'图像过点 $({latex(k)},{latex(b)})$')
        if stem is not None and done is not None:
            view['graph'], view['completion_graph'] = stem, done
        views += _group([view], f'known-{k}', '先找出图像上确定的点')
    for i, w in enumerate(plan['walks']):
        t = w['target']
        if not w['steps']:
            view = _read(rf'记 ${f}({latex(t)})={latex(w["value"])}$', '这个值由已知条件求不出，先用字母表示，再看最后能否消去。',
                         source, f'{f}({latex(t)})={latex(w["value"])}', [f'{f}({latex(t)})={latex(w["value"])}'])
            shown.add(t)
            views += _group([view], f'walk-{i}', rf'记 ${f}({latex(t)})={latex(w["value"])}$')
            continue
        steps, cards = w['steps'], []
        for j, s in enumerate(steps):
            name, _ = _edge_text(s['edge'], f)
            src = _coord(s['from'], s['value_from'])
            if len(steps) == 1:
                question = rf'图像{name}，点 ${src}$ 的对称点是哪个点？'
            elif j == 0:
                last = steps[-1]
                question = (rf'由图像{_edge_text(last["edge"], f)[0]}，${latex(t)}$ 与 ${latex(last["from"])}$ 配对，'
                            rf'先求 ${f}({latex(last["from"])})$。图像{name}，点 ${src}$ 的对称点是哪个点？')
            else:
                question = rf'再由图像{name}，点 ${src}$ 的对称点是哪个点？'
            tail = rf'，即 ${f}({latex(t)})={latex(w["value"])}$' if j == len(steps)-1 else ''
            cards.append(_step_card(d, f, s, question, '利用图像' + name, [rf'{f}({latex(s["from"])})={latex(s["value_from"])}'],
                                    picture, shown, set(), tail))
            shown |= {s['from'], s['to']}
        cards[-1]['proof'] = _lines([c['proof'] for c in cards])
        views += _group(cards, f'walk-{i}', rf'求 ${f}({latex(t)})$')
    return views


def _period_views(d, m, plan, example, source):
    f, c = d['function'], plan['cycle']
    x, v, period = c['x'], c['m'], plan['period']
    ext = m['extension']
    t = (ext['base_interval'].start + ext['base_interval'].end)/2
    at = {x: v, **{s['to']: s['value_to'] for s in c['steps']}}
    span = [p.subs(x, t) for p in at]

    def picture(marked, labelled, reflections, edges, caption, level=False):
        if example is None:
            return None
        caption += rf'（图中取 $x={latex(t)}$，$x$ 取任意值都一样）'
        moved = [{**r, 'from': r['from'].subs(x, t), 'to': r['to'].subs(x, t)} for r in reflections]
        return _example_graph(d, m, example, caption, edges=edges, span=span, level_at=t if level else None,
                              points=[(p.subs(x, t), _coord(p, at[p], True) if p in labelled else None)
                                      for p in sorted(marked, key=lambda p: p.subs(x, t))],
                              reflections=moved)

    cards, shown = [], {x}
    for j, s in enumerate(c['steps']):
        name = _edge_text(s['edge'], f)[0]
        src = _coord(s['from'], s['value_from'])
        if j % 2 == 0:
            goal = c['steps'][j+1]['to']
            question = ('在图像上任取一点 $(x,m)$。' if j == 0 else '') + \
                rf'求横坐标为 ${_tex(goal)}$ 的点：先由图像{name}，点 ${src}$ 的对称点是哪个点？'
        else:
            question = rf'再由图像{name}，点 ${src}$ 的对称点是哪个点？'
        cards.append(_step_card(d, f, s, question, '利用图像' + name, [rf'{f}({latex(s["from"])})={latex(s["value_from"])}'],
                                picture, shown, set()))
        shown |= {s['from'], s['to']}
    end = x + period
    law = rf'{f}({_tex(end)})={f}(x)\text{{，周期为 }}{latex(period)}'
    half = period/2
    wrong = [rf'{f}({_tex(x+half)})={f}(x)\text{{，周期为 }}{latex(half)}', rf'{f}({_tex(end)})=-{f}(x)',
             rf'{f}({_tex(x+2*period)})=-{f}(x)']
    proof = [_chain(f, c['steps']), law]
    view = choice_card('两点一样高，得出周期', rf'点 $(x,m)$ 与点 $({_tex(end)},m)$ 一样高，而且 $x$ 取任意值都如此。由此得到什么？',
                       '已知', _lines([rf'{f}(x)=m', rf'{f}({_tex(end)})=m']), '结论', law, wrong, _lines(proof))
    stem = picture(shown, {x, end}, [], [], rf'点 $(x,m)$ 与点 $({_tex(end)},m)$')
    done = picture(shown, {x, end}, [], [], rf'水平虚线：两点一样高，${f}({_tex(end)})={f}(x)$', level=True)
    if stem is not None and done is not None:
        view['graph'], view['completion_graph'] = stem, done
    cards.append(view)
    views = _group(cards, 'period', '用对称找出周期')
    if plan['walks']:
        values = {k: w['value'] for k, w in plan['known'].items()}
        lines, steps = [], []
        for w in plan['walks']:
            if w['steps']:
                lines.append(_chain(f, w['steps'], values[w['steps'][0]['from']]))
                steps += w['steps']
                for s in w['steps']:
                    values.setdefault(s['to'], s['value_to'])
            else:
                lines.append(f'{f}({latex(w["target"])})={latex(w["value"])}')
            values[w['target']] = w['value']
        reps = ', '.join(f'{f}({latex(r)})' for r in plan['reps'])
        given = []
        for k, w in plan['known'].items():
            e = w.get('edge')
            why = ('' if e is None else r'\quad(\text{奇函数})' if e['a'] == 0 and e['offset'] == 0
                   else r'\quad(\text{对称中心})')
            given.append(rf'{f}({latex(k)})={latex(w["value"])}' + why)
        view = _read('求出一个周期内需要的函数值', rf'由周期 ${latex(period)}$，只需求出 ${reps}$；从已知点出发逐点找对称点。',
                     given, _lines(lines), lines)
        if example is not None:
            span2 = sorted({*values, *(e['a'] for e in m['edges'])})
            graph = _example_graph(d, m, example, '一个周期内需要的点', span=span2,
                                   points=[(p, _coord(p, values[p], True) if p in plan['reps'] else None) for p in sorted(values)])
            if graph is not None:
                view['graph'] = graph
        views += _group([view], 'values', '求出一个周期内需要的函数值')
    return views


def _substituted(d, value_of):
    from ..symmetry_relation_math import target_terms
    rows = target_terms(d)
    if len(rows) != 1:
        return None
    row, text = rows[0], ''
    for (_, q), k in row['terms'].items():
        v = sp.expand(value_of(rational(q)))
        term = rf'\left({latex(v)}\right)' if v.could_extract_minus_sign() or isinstance(v, sp.Add) else latex(v)
        coef = '' if k == 1 else '-' if k == -1 else latex(k) + r'\cdot '
        text += ('' if not text or coef.startswith('-') else '+') + coef + term
    if row['constant']:
        text += ('+' if row['constant'] > 0 else '') + latex(row['constant'])
    return text


def _plan_conclusion(d, m, plan):
    from ..symmetry_walk import representative
    f, target, value = d['function'], target_math(d), m['proof']['value']
    values = {k: w['value'] for k, w in plan['known'].items()} | {w['target']: w['value'] for w in plan['walks']}
    if plan['mode'] == 'walk':
        value_of = values.__getitem__
        lines = [f'{f}({latex(k)})={latex(values[k])}' for k in plan['inputs']]
        label, question = '已求出的函数值', '把求出的函数值代入所求式，结果是什么？'
    else:
        low, period = plan['low'], plan['period']
        value_of = lambda k: values[representative(k, low, period)]
        moved = [f'{f}({latex(k)})={f}({latex(representative(k, low, period))})' for k in plan['inputs']
                 if representative(k, low, period) != k]
        if len(moved) > 4:
            moved = [moved[0], r'\cdots', *moved[-2:]]
        lines = [*moved, *(f'{f}({latex(r)})={latex(values[r])}' for r in plan['reps'])]
        label = rf'周期 ${latex(period)}$ 与一个周期内的值'
        question = rf'由周期 ${latex(period)}$ 把各项化到一个周期内，再代入函数值，结果是什么？'
    middle = _substituted(d, value_of)
    answer = target + '=' + latex(value)
    candidates = [value+1, value-1, -value, value+2]
    wrong = [target + '=' + latex(w) for w in dict.fromkeys(candidates) if w != value]
    proof = [*lines, target + ('=' + middle if middle else '') + '=' + latex(value)]
    return choice_card('求出函数值之和' if d['source']['kind'] == 'finite_sum' else '求出所求的值', question,
                       label, _lines(lines), '结论', answer, wrong[:3], _lines(proof))


def phase_views(values):
    d, phase = values['description'], values['phase']
    m, f = solve(d), d['function']
    source = source_math(d)
    laws = [_relation(e, f) for e in m['edges']]
    plan = teaching_plan(d, m)
    if plan is not None and phase == 'rewrite':
        build = _walk_views if plan['mode'] == 'walk' else _period_views
        views = build(d, m, plan, _example(d, m), source)
        return views or [_read('整理已知条件', '所求式中的函数值已经给出，可以直接代入。',
                              source, _lines(source), source)]
    if plan is not None:
        return [*(_sum_groups(d, m) if plan['mode'] == 'period' else []), _plan_conclusion(d, m, plan)]
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
