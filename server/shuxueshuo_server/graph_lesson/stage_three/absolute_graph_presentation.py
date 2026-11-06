"""G2: build |p(x)| one region at a time, then read a horizontal comparison."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..absolute_graph import VERSION
from . import interaction_graphs as drawing
from .absolute_graph_runtime import formula
from .evaluation_presentation import _choice, _lines
from .interaction_graph_contract import validate_graph
from .math_values import latex
from .range_presentation import _card


def set_latex(value):
    if isinstance(value, sp.FiniteSet):
        return r'\{' + ','.join(latex(v) for v in sorted(value)) + r'\}'
    return latex(value)


def ends(region):
    if region == sp.S.Reals:
        return [None, None], [False, False]
    values = [float(v) if v.is_finite else None for v in (region.inf, region.sup)]
    return values, [v is not None and not opened for v, opened in zip(values, (region.left_open, region.right_open), strict=True)]


def segment(expr, domain, variable):
    """Polynomial piece; degree ≤ 3 (quadratic pad to 3 coeffs, cubic uses 4)."""
    poly = sp.Poly(expr, variable)
    deg = poly.degree()
    if deg > 3:
        raise ValueError('segment_degree')
    # SymPy assigns degree -oo to the zero polynomial; it still draws as y = 0.
    top = 3 if deg == 3 else 2
    interval, closed = ends(domain)
    return {'coefficients': [float(poly.nth(i)) for i in range(top, -1, -1)],
            'interval': interval, 'interval_closed': closed}


def graph_for(model, *, count=None, original=False, reference=False, level=False, crossings=False, solution=None):
    x, p, domain = (model[k] for k in ('variable', 'polynomial', 'domain'))
    pieces = model['pieces'] if count is None else model['pieces'][:count]
    anchors = [sp.S.Zero, *model['roots']]
    poly = sp.Poly(p, x)
    if poly.degree() == 2:
        anchors.append(-poly.nth(1)/(2*poly.nth(2)))
    anchors += [v for v in (domain.inf, domain.sup) if v.is_finite]
    if level and isinstance(model['crossings'], sp.FiniteSet):
        anchors += list(model['crossings'])
    low, high = min(anchors)-1, max(anchors)+1
    if high-low < 4:
        low, high = (low+high)/2-2, (low+high)/2+2
    ys = [sp.S.Zero, *[abs(p.subs(x, v)) for v in [*anchors, low, high]]]
    if original or reference:
        ys += [p.subs(x, v) for v in anchors]
    if level:
        ys.append(model['level'])
    bottom, top = min(ys)-1, max(ys)+1
    interval, closed = ends(domain)
    params = {'segments': [segment(p, domain, x)] if original else [segment(row['expression'], row['domain'], x) for row in pieces],
              'bounds': list(map(float, (low, high, bottom, top))), 'interval': interval, 'interval_closed': closed,
              'xTicks': [[float(v), drawing.short_label(v)] for v in sorted({sp.S.Zero, *model['roots']})],
              'points': [], 'variable': str(x), 'title': '逐段画出函数图像',
              'description': '实线表示已确认的曲线，虚线用作比较；空心端点不取，实心端点可取。'}
    # Zero confirmed pieces still needs a nonempty schema; draw the original as reference instead.
    if not params['segments']:
        params['segments'] = [segment(p, domain, x)]
    if reference:
        params['reference'] = [segment(p, domain, x)]
    if level:
        params['level'] = float(model['level'])
        params['yTicks'] = [[float(model['level']), drawing.short_label(model['level'])]]
    if crossings and isinstance(model['crossings'], sp.FiniteSet):
        params['points'] = [{'x': float(v), 'open': solution is not None and v not in solution} for v in sorted(model['crossings'])]
        params['xTicks'] = [[float(v), drawing.short_label(v)] for v in sorted(model['crossings'])]
    if solution is not None:
        rows = solution.args if isinstance(solution, sp.Union) else [solution]
        params['highlights'] = []
        for region in rows:
            if region == sp.S.EmptySet or isinstance(region, sp.FiniteSet):
                continue
            values, shut = ends(region)
            params['highlights'].append({'from': values[0], 'to': values[1], 'left_closed': shut[0], 'right_closed': shut[1]})
    return validate_graph({'kind': 'piecewise_curve', 'params': params,
                           'caption': '虚线：去掉绝对值前的图像；实线：已确认的各段。' if reference else
                                      '有色曲线对应满足不等式的区间；端点是否取到另看空实点。' if solution is not None else
                                      '根据解析式和区间绘制的教学图。'})


def choice_card(title, question, left_label, left, right_label, right, wrong, proof):
    i, expected = _choice('$'+right+'$', ['$'+v+'$' for v in wrong if v != right])
    view = _card(title, question, left_label, left, right_label, right,
                 '结合卡片中的式子和范围，再核对一次。', i, expected)
    view['proof'] = proof
    return view


def phase_views(values):
    model, phase = values['graph_result'], values['phase']
    x, p, domain = (model[k] for k in ('variable', 'polynomial', 'domain'))
    f = rf'f({latex(x)})=\left|{latex(p)}\right|'
    roots = sp.FiniteSet(*model['roots'])
    if phase == 'zeros':
        answer = latex(roots)
        proof = _lines([rf'{latex(sp.factor(p))}=0', rf'{latex(x)}\in {answer}'])
        if p == 0:
            answer, proof = latex(domain), rf'{latex(p)}=0\quad({latex(x)}\in {latex(domain)})'
        view = choice_card('找出分段的位置', rf'先看绝对值里的 ${latex(p)}$。令它等于 $0$，哪些横坐标需要标出来？',
                           '绝对值内的式子', rf'{latex(p)}=0', '零点的横坐标', answer,
                           [latex(roots | sp.FiniteSet(1)), r'\varnothing', r'\mathbb R'], proof)
        view['graph'] = graph_for(model, original=True)
        view['completion_graph'] = graph_for(model, original=True)
        return [view]
    if phase == 'segments':
        views = []
        for index, piece in enumerate(model['pieces']):
            region, expr, sign = (piece[k] for k in ('domain', 'expression', 'sign'))
            action = '保留这一段' if sign == 1 else '把这一段翻到横轴上方'
            relation = r'\ge' if sign == 1 else r'\le'
            # Closed internal zero belongs to exactly one piece. At zero, both rules agree.
            output = rf'f({latex(x)})={latex(expr)}'
            right = rf'\text{{{action}}},\quad {output}'
            wrong = rf'\text{{{"翻到横轴下方" if sign == 1 else "保留这一段"}}},\quad f({latex(x)})={latex(-expr)}'
            view = choice_card(f'画第 {index+1} 段', rf'当 ${latex(x)}\in {latex(region)}$ 时，${latex(p)}{relation}0$。这一段该怎样画？',
                               '当前区间与原函数', _lines([f, rf'{latex(x)}\in {latex(region)}']), '这一段的画法', right, [wrong],
                               _lines([rf'{latex(x)}\in {latex(region)}\Longrightarrow {latex(p)}{relation}0',
                                       rf'\left|{latex(p)}\right|={latex(expr)}', output]))
            view['graph'] = graph_for(model, count=index, original=index == 0, reference=index > 0)
            view['completion_graph'] = graph_for(model, count=index+1, reference=True)
            view['submit_label'] = '画上这一段'
            views.append(view)
        return views
    if phase == 'assemble':
        rows = [
            ('分段式', '$'+formula(model)+'$', rf'$f({latex(x)})={latex(p+1)}$'),
            ('区间', rf'各段合起来是 ${latex(domain)}$', rf'只保留零点 ${latex(roots)}$'),
            ('图像方向', '各段都在横轴上方或横轴上', '各段都在横轴下方'),
            ('边界', '区间相接处不断开，定义域内的零点取到', '所有分段交界点都不取'),
        ]
        if not model['roots']:
            rows[-1] = ('边界', '保留原定义域的端点和开闭', '把原定义域的端点全部删去')
        slots = [{'label': label, 'options': [{'value': 'correct', 'label': correct}, {'value': 'wrong', 'label': wrong}]} for label, correct, wrong in rows]
        view = _card('合成图像，检查四件事', '各段已经画好。核对下面四项，完成这幅图。', '各段的表达式', formula(model),
                     '作图完成', rf'{f},\quad {latex(x)}\in {latex(domain)}', '各段规则、范围、方向和边界需要同时符合。',
                     {'type': 'checklist', 'title': '检查作图结果', 'slots': slots}, {'terms': ['correct']*4})
        view['proof'] = _lines([formula(model), rf'\bigcup I_i={latex(domain)},\quad f({latex(x)})\ge0',
                                rf'f({latex(x)})=0\Longleftrightarrow {latex(p)}=0'])
        view['graph'] = graph_for(model)
        view['completion_graph'] = deepcopy(view['graph'])
        view['guided_plot'] = {'mode': 'guided', 'checks': ['pieces', 'intervals', 'direction', 'boundaries'], 'model_version': VERSION}
        return [view]
    level, op = model['level'], model['operator']
    sign = {'>=': r'\ge', '<=': r'\le', '>': '>', '<': '<'}[op]
    if phase == 'intersections':
        answer = set_latex(model['crossings'])
        proof = _lines([rf'\left|{latex(p)}\right|={latex(level)}',
                        rf'{latex(p)}={latex(level)}\quad\text{{或}}\quad {latex(p)}={latex(-level)}' if level >= 0 else
                        rf'\left|{latex(p)}\right|\ge0>{latex(level)}', rf'{latex(x)}\in {answer}'])
        view = choice_card('找图像与水平线的交点', rf'在 ${f}$ 的图像中画水平线 $y={latex(level)}$。交点的横坐标有哪些？',
                           '求交点', rf'\left|{latex(p)}\right|={latex(level)}', '交点的横坐标', answer,
                           [latex(roots), r'\varnothing', r'\mathbb R'], proof)
        view['graph'] = graph_for(model, level=True)
        view['completion_graph'] = graph_for(model, level=True, crossings=True)
    elif phase == 'regions':
        strict = model['solution'] - model['crossings']
        direction = '上方' if op in ('>', '>=') else '下方'
        answer = latex(strict)
        view = choice_card('先选水平线上下的区间', rf'原题要求 $f({latex(x)}){sign}{latex(level)}$。先不取交点，哪些横坐标对应的曲线在 $y={latex(level)}$ 的{direction}？',
                           '原不等式与交点', _lines([rf'f({latex(x)}){sign}{latex(level)}', rf'\text{{交点横坐标：}}{set_latex(model["crossings"])}']),
                           '先选出的区间', answer, [latex(domain-strict), latex(domain)],
                           _lines([rf'\left|{latex(p)}\right|{">" if direction == "上方" else "<"}{latex(level)}',
                                   rf'{latex(p)}{">" if direction == "上方" else "<"}{latex(level)}\quad\text{{{"或" if direction == "上方" else "且"}}}\quad {latex(p)}{"<" if direction == "上方" else ">"}{latex(-level)}',
                                   rf'{latex(x)}\in {answer}']))
        view['graph'] = graph_for(model, level=True, crossings=True)
        view['completion_graph'] = graph_for(model, level=True, crossings=True, solution=strict)
    elif phase == 'endpoints':
        strict = model['solution'] - model['crossings']
        included = op in ('>=', '<=')
        answer = latex(model['solution'])
        view = choice_card('判断端点，写出解集', rf'原题是 $f({latex(x)}){sign}{latex(level)}$。交点处恰好 $f({latex(x)})={latex(level)}$，这些点能取吗？选择完整解集。',
                           '交点处的函数值', rf'f({latex(x)})={latex(level)}', '原不等式的解集', answer,
                           [latex(strict if included else model['solution'] | model['crossings']), latex(domain-model['solution'])],
                           _lines([rf'{latex(level)}{sign}{latex(level)}\quad\text{{{"成立，取等号处" if included else "不成立，不取等号处"}}}',
                                   rf'{latex(x)}\in {answer}']))
        view['graph'] = graph_for(model, level=True, crossings=True, solution=strict)
        view['completion_graphs'] = [graph_for(model, level=True, crossings=True, solution=model['solution']),
                                    drawing.number_lines([model['solution']], x, title='不等式的解集')[0]]
    else:
        raise ValueError('absolute_graph.unknown_phase')
    return [view]


def presentation(values):
    views = phase_views(values)
    view = views[-1]
    left, right = view['derivation']['items']
    return {'formula_title': '分区间画出各段图像' if values['phase'] == 'segments' else view['title'], 'formula_explanation': '$$'+_lines([v['proof'] for v in views])+'$$',
            'derivation_caption': '分区间画出各段图像' if values['phase'] == 'segments' else view['title'], 'derivation_left_label': left['label'], 'derivation_left_math': left['math'],
            'derivation_left_note': '', 'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_absolute(values, interaction_id):
    parts = []
    for index, view in enumerate(phase_views(values), 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        i = deepcopy(view['interaction'])
        for options in ([i['options']] if i['type'] == 'choice' else [slot['options'] for slot in i['slots']]):
            options.sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        part = {'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                'interaction': i, 'expected_answer': view['expected_answer'], 'feedback': view['feedback'],
                'submit_label': view.get('submit_label', '确认判断'), 'stem_board': board, 'completion_board': view['derivation']}
        part.update({key: view[key] for key in ('graph', 'completion_graph', 'completion_graphs', 'guided_plot') if key in view})
        parts.append(part)
    return {'parts': parts, 'diagnostics': []}
