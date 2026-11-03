"""Teach point transport with original pixels, never a fitted substitute curve."""
import sympy as sp

from .absolute_graph_presentation import choice_card
from .evaluation_presentation import _lines
from .math_values import latex
from .range_presentation import _card


def phase_view(values):
    model, goal, phase = values['graph_result'], values['description']['source'], values['phase']
    a, b, u = model['a'], model['b'], sp.Symbol('u')
    x, name = sp.Symbol(goal['variable']), goal['source_graph']['function']
    target = rf'y={name}({latex(a*x+b)})'
    old, new = model['source_zero'], model['target_zero']
    direction = {'increasing': '上升', 'decreasing': '下降'}
    if phase == 'transform':
        result = rf'({latex((u-b)/a)},v)'
        proof = _lines([rf'v={name}(u),\quad u={latex(a*x+b)}',
                        rf'{latex(x)}={latex((u-b)/a)},\quad (u,v)\longmapsto{result}'])
        view = choice_card('原图上的点会移到哪里',
                           rf'原图上的点是 $(u,v)$。在 ${target}$ 中，令 ${latex(a*x+b)}=u$。对应点的坐标是什么？',
                           '原图与目标图的同一个函数值', _lines([rf'v={name}(u)', rf'{latex(a*x+b)}=u']),
                           '对应点', result, [rf'({latex(a*u+b)},-v)', rf'({latex(a*u-b)},v)'], proof)
    elif phase == 'vertex':
        answer = rf'({latex(new)},0)'
        proof = _lines([rf'{name}({latex(old)})=0', rf'{latex(a*x+b)}={latex(old)}',
                        rf'{latex(x)}={latex(new)},\quad({latex(old)},0)\longmapsto{answer}'])
        view = choice_card('横轴交点移到哪里',
                           rf'原图与横轴交于 $({latex(old)},0)$。${target}$ 的对应交点在哪里？',
                           '原图的横轴交点', rf'({latex(old)},0)', '新图的横轴交点', answer,
                           [rf'({latex(new+1)},0)', rf'(0,{latex(new)})'], proof)
    elif phase == 'options':
        chosen = next(row['label'] for row in model['option_verdicts'] if row['matches'])
        feature = _lines([target, rf'\text{{横轴交点}}\ ({latex(new)},0)',
                          rf'\text{{从左往右{direction[model["target_direction"]]}}}'])
        view = _card('对照原图，选择图像', '同时核对横轴交点和从左往右的方向，哪幅图符合？',
                     '变换后的两个特征', feature, '原题选择', rf'\text{{{chosen}}}',
                     '两个特征都要符合，不能只看其中一个。',
                     {'type': 'choice', 'field': 'answer', 'options': [{'value': o['option_id'], 'label': o['label']} for o in goal['options']]},
                     {'one_of': [model['correct_option_id']]})
        rows = []
        for option, verdict in zip(goal['options'], model['option_verdicts'], strict=True):
            facts = option['facts']
            labels = {'shown_direction': '方向不符', 'x_intercept': '交点位置不符'}
            reason = '两项均符合' if verdict['matches'] else '、'.join(labels[d] for d in verdict['differences'])
            rows.append(rf'\text{{{option["label"]}}}:\ ({facts["x_intercept"]["x"]},0),\ '
                        rf'\text{{{direction[facts["direction"]]}，{reason}}}')
        view['proof'] = _lines(rows)
        view['figure_choices'] = [o['option_id'] for o in goal['options']]
    else:
        raise ValueError('function_graph.unknown_phase')
    view['show_source_graph'] = True
    return view


def transform_views(values):
    m, g = values['graph_result'], values['description']['source']
    a, b = m['a'], m['b']
    x, u = sp.Symbol(g['variable']), sp.Symbol('u')
    name = g['source_graph']['function']
    views = []
    if a < 0:
        proof = _lines([rf'u=-{latex(x)}\Longrightarrow {latex(x)}=-u',
                        r'(u,v)\longmapsto(-u,v)'])
        views.append(choice_card('先关于 y 轴对称',
            rf'先从 $y={name}({latex(x)})$ 得到 $y={name}(-{latex(x)})$。关于 $y$ 轴对称后，原图上的点 $(u,v)$ 移到哪里？',
            '原图上的点', '(u,v)', '对称后的点', '(-u,v)', ['(u,-v)', '(-u,-v)'], proof))
    shift = -b/a
    if shift:
        direction = '右' if shift > 0 else '左'
        before, after = rf'({latex(a*u)},v)', rf'({latex(a*u+shift)},v)'
        previous = rf'{name}({latex(a*x)})'
        target = rf'{name}({latex(a*x+b)})'
        # Substitute into the entire previous input: f(a(x-h)), not f(ax-h).
        shifted_input = rf'-({latex(x-shift)})' if a < 0 else latex(x-shift)
        proof = _lines([rf'y={previous}\ \xrightarrow{{\text{{向{direction}平移 }}{latex(abs(shift))}}}\ y={name}({shifted_input})={target}',
                        rf'{before}\longmapsto{after}'])
        views.append(choice_card(f'{"再" if views else ""}向{direction}平移 {latex(abs(shift))} 个单位',
            rf'从 $y={previous}$ 向{direction}平移 ${latex(abs(shift))}$ 个单位，得到 $y={target}$。点 ${before}$ 移到哪里？',
            '平移前的点', before, '平移后的点', after,
            [rf'({latex(a*u-shift)},v)', rf'({latex(a*u)},v+({latex(shift)}))'], proof))
    if not views:
        views.append(phase_view({**values, 'phase': 'transform'}))
    direction = {'increasing': '上升', 'decreasing': '下降'}
    before, after = direction[m['source_direction']], direction[m['target_direction']]
    target = rf'y={g["source_graph"]["function"]}({latex(a*x+b)})'
    relation = '<' if a > 0 else '>'
    x1, x2 = sp.Symbol(g['variable']+'_1'), sp.Symbol(g['variable']+'_2')
    proof = _lines([rf'{latex(x1)}<{latex(x2)}\Longrightarrow {latex(a*x1+b)}{relation}{latex(a*x2+b)}',
                    rf'\text{{原图从左往右{before}}}\Longrightarrow\text{{新图从左往右{after}}}'])
    summary = choice_card('总结点的移动与图像方向',
                         rf'原图所示部分从左往右{before}。在 ${target}$ 中，${latex(x)}$ 增大时括号里的数{"增大" if a > 0 else "减小"}，新图对应部分从左往右怎样变化？',
                         '点的移动与原图方向', _lines([rf'(u,v)\longmapsto({latex((u-b)/a)},v)', rf'\text{{原图从左往右{before}}}']),
                         '新图的方向', rf'\text{{从左往右{after}}}',
                         [rf'\text{{从左往右{"下降" if after == "上升" else "上升"}}}'], proof)
    views.append(summary)
    for view in views:
        view['show_source_graph'] = True
    return views
