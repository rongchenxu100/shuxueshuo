"""One translation per card, followed by concrete landmarks and original options."""
from copy import deepcopy

import sympy as sp

from .absolute_graph_presentation import choice_card, segment
from .evaluation_presentation import _lines
from .interaction_graph_contract import validate_graph
from .interaction_graphs import short_label
from .math_values import latex
from .range_presentation import _card


def formula(state):
    c = state['offset']
    return rf'y=\left|{latex(state["polynomial"])}\right|'+('+'+latex(c) if c > 0 else latex(c) if c < 0 else '')


def segments(state, x):
    p, c = state['polynomial'], state['offset']
    l, _, r = state['landmarks']
    a = sp.Poly(p, x).nth(2)
    sign = 1 if a > 0 else -1
    return [segment(sign*p+c, sp.Interval.open(-sp.oo, l[0]), x),
            segment(-sign*p+c, sp.Interval.Ropen(l[0], r[0]), x),
            segment(sign*p+c, sp.Interval(r[0], sp.oo), x)]


def graph_for(model, index, reference=None):
    state, x = model['states'][index], model['variable']
    # Use the same viewport throughout, so a change of scale cannot look like a move.
    points = [p for s in model['states'] for p in s['landmarks']]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    bounds = list(map(float, (min(xs)-1, max(xs)+1, min([sp.S.Zero, *ys])-1, max([sp.S.Zero, *ys])+2)))
    params = {'segments': segments(state, x), 'bounds': bounds,
              'interval': [None, None], 'interval_closed': [False, False],
              'xTicks': [[float(v), short_label(v)] for v in sorted({sp.S.Zero, *[p[0] for p in state['landmarks']]})],
              'yTicks': [[float(v), short_label(v)] for v in sorted({sp.S.Zero, *[p[1] for p in state['landmarks']]})],
              'points': [{'x': float(p[0]), 'label': f'({short_label(p[0])}, {short_label(p[1])})', 'place': place}
                         for p, place in zip(state['landmarks'], ('below-left', 'above-right', 'below-right'), strict=True)],
              'variable': str(x), 'title': '绝对值二次函数的平移',
              'description': '按当前解析式绘制。三个标记点随图像一起平移。'}
    if reference is not None:
        params['reference'] = segments(model['states'][reference], x)
    return validate_graph({'kind': 'piecewise_curve', 'params': params,
                           'caption': '虚线：这一步移动前；实线：移动后。' if reference is not None else '当前图像与三个关键点。'})


def point_latex(point):
    return rf'({latex(point[0])},{latex(point[1])})'


def translation_views(values):
    model, views = values['graph_result'], []
    x = model['variable']
    direction_names = {'left': '左', 'right': '右', 'up': '上', 'down': '下'}
    before_graph = graph_for(model, 0)
    for index, move in enumerate(model['moves']):
        before, after = model['states'][index:index+2]
        direction, distance = direction_names[move['direction']], move['distance']
        horizontal = bool(move['dx'])
        action = rf'\text{{向{direction}平移}}\,{latex(distance)}\,\text{{个单位}}'
        old, new = formula(before), formula(after)
        wrong = deepcopy(after)
        if horizontal:
            wrong['polynomial'] = before['polynomial'].subs(x, x+move['dx'])
        else:
            wrong['offset'] = before['offset']-move['dy']
        wrong_formulas = [formula(wrong)]
        if not horizontal:
            wrong_formulas.append(formula({**before, 'polynomial':before['polynomial']+move['dy']}))
        question = f'{"先" if index == 0 else "接着"}向{direction}平移 ${latex(distance)}$ 个单位。${old}$ 变成哪个解析式？'
        label = '横坐标' if horizontal else '纵坐标'
        delta = move['dx'] if horizontal else move['dy']
        u, v = sp.symbols('u v', real=True)
        point_map = rf'(u,v)\longmapsto({latex(u+move["dx"])},{latex(v+move["dy"])})'
        proof = _lines([rf'{old}\xrightarrow{{{action}}}{new}', point_map])
        view = choice_card(f'向{direction}平移 {short_label(distance)} 个单位', question, '移动前的解析式', old,
                           '移动后的解析式', new, wrong_formulas, proof)
        view['feedback'] = {'answer': f'{label}{"加上" if delta > 0 else "减去"} {short_label(distance)}；'+(
            f'新解析式把原来的 ${latex(x)}$ 换成 ${latex(x-delta)}$。' if horizontal else '绝对值里面的式子不变。')}
        after_graph = graph_for(model, index+1, reference=index)
        view.update(graph=deepcopy(before_graph), completion_graph=after_graph, submit_label='确认这一步')
        views.append(view)
        before_graph = after_graph
    return views


def phase_view(values):
    model, goal, phase = values['graph_result'], values['description']['source'], values['phase']
    first, last = model['states'][0], model['states'][-1]
    if phase == 'transform':
        return translation_views(values)[0]
    points = last['landmarks']
    if phase == 'vertex':
        answer = r'\quad'.join(point_latex(p) for p in points)
        wrong = r'\quad'.join(point_latex([p[0], p[1]+1]) for p in points)
        old_points = r'\quad'.join(point_latex(p) for p in first['landmarks'])
        proof = _lines([rf'{point_latex(p)}\longmapsto {point_latex(q)}' for p, q in zip(first['landmarks'], points, strict=True)])
        view = choice_card('总结平移后的关键点', '两个折点和中间的最高点一起移动。完成这些平移后，三个点分别在哪里？',
                           '原图的三个关键点', old_points, '移动后的三个点', answer, [wrong], proof)
        view['completion_graph'] = graph_for(model, len(model['moves']), reference=0)
        view['completion_graph']['caption'] = '虚线：原图；实线：完成全部平移后的图像。'
        return view
    if phase != 'options':
        raise ValueError('function_graph.unknown_phase')
    options = [{'value': o['option_id'], 'label': o['label']} for o in goal['options']]
    selected = next(row['label'] for row in model['option_verdicts'] if row['matches'])
    features = _lines([formula(last), rf'\text{{最低点}}\ {point_latex(points[0])},\ {point_latex(points[2])}',
                       rf'\text{{中间的最高点}}\ {point_latex(points[1])},\quad\text{{两端向上}}'])
    view = _card('对照原图，选择图像', '核对最低点的位置、中间的最高点和两端方向。哪幅原图符合？',
                 '平移后的图像特征', features, '原题选择', r'\text{'+selected+'}',
                 '先核对上下位置，再看横坐标和两端方向。',
                 {'type': 'choice', 'field': 'answer', 'options': options}, {'one_of': [model['correct_option_id']]})
    names = {'outer_direction': '两端方向不符', 'symmetry': '左右不对称', 'left_corner_x': '左折点横坐标不符', 'left_corner_y': '左折点纵坐标不符',
             'right_corner_x': '右折点横坐标不符', 'right_corner_y': '右折点纵坐标不符',
             'center_x': '中间转折点横坐标不符', 'center_y': '中间转折点纵坐标不符'}
    proof = []
    for option, verdict in zip(goal['options'], model['option_verdicts'], strict=True):
        facts = []
        for p in option['facts']['landmarks']:
            role = {'left_corner': '左折点', 'right_corner': '右折点', 'center': '中间转折点'}[p['role']]
            coords = ','.join(f'{key}={p[key]}' for key in ('x', 'y') if key in p)
            facts.append(rf'\text{{{role}}}:\ {coords}')
        if option['facts']['outer_direction'] != 'unknown':
            facts.append(r'\text{两端向'+('上' if option['facts']['outer_direction'] == 'up' else '下')+'}')
        if option['facts']['symmetry'] == 'symmetric':
            facts.append(r'\text{左右对称}')
        reason = '已标坐标、对称性和两端方向均符合' if verdict['matches'] else '、'.join(names[d] for d in verdict['differences'])
        proof.append(rf'\text{{{option["label"]}}}:\ '+r',\ '.join(facts)+rf'\quad\text{{{reason}}}')
    view['proof'] = _lines(proof)
    view['figure_choices'] = [o['option_id'] for o in goal['options']]
    view['graph'] = graph_for(model, len(model['moves']))
    view['completion_graph'] = deepcopy(view['graph'])
    return view
