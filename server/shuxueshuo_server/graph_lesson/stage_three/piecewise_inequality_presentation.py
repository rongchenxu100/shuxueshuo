"""Evaluate the comparison value, solve each branch, intersect, then unite."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_evaluation import _substitution_latex
from ..piecewise_inequality import RELATIONS, source
from . import interaction_graphs as drawing
from .evaluation_presentation import _choice, _condition_latex, _lines
from .math_values import latex
from .piecewise_equation_presentation import _choices
from .range_presentation import _card
from .trajectory import decode_value


def _inequality(left, op, right):
    return latex(RELATIONS[op](left, right, evaluate=False))


def _graphs(row, x, op):
    """Show the zero-normalized polynomial; highlight its solution after answering."""
    expression = row['positive_expression']
    if sp.Poly(expression, x).degree() != 2:
        return {}
    drawn = drawing.family(expression, x)
    anchors = [drawn['vertex'][0], *row['roots']]
    margin = max(max(anchors)-min(anchors), sp.S.One)/3
    frame = sp.Interval(min(anchors)-margin, max(anchors)+margin)
    bounds, _ = drawing.function_frame(drawn, x, frame, show_vertex=True)
    graph = drawing.function_graph(drawn, x, sp.Interval(-sp.oo, sp.oo), bounds=bounds,
                                   x_ticks=drawing.ticks(row['roots'], *bounds[:2]),
                                   marks=[(root, True) for root in row['roots']],
                                   title=f'y={drawing.plain(expression)} 的图像',
                                   description='找到零点，再观察曲线在哪些区间位于横轴上方。',
                                   caption=rf'图中 $y={latex(expression)}$。先解 ${_inequality(expression, ">" if op in (">", "<") else ">=", 0)}$，下一步再与本段范围取交。')
    complete = deepcopy(graph)
    strict = op in ('>', '<')
    complete['params'].update(markSign='above', strict=strict,
                              points=[{'x': float(root), 'open': strict} for root in row['roots']])
    complete['params']['description'] = f'这个多项式不等式的解集为 {drawing.plain(row["candidates"])}。'
    complete['caption'] = rf'图中 $y={latex(expression)}$。高亮部分满足本步不等式；'+('零点不取。' if strict else '零点也取。')
    return {'graph': graph, 'completion_graph': complete}


def phase_views(values):
    desc, level = values['description'], values['level']
    data = source(desc)
    x, f, op = data['variable'], data['function'], data['op']
    target = rf'{f}({latex(x)})'+{'>' :'>', '>=':r'\ge', '<':'<', '<=':r'\le'}[op]+latex(level)
    views = []
    if values['phase'] == 'level':
        value, index = data['level_input'], data['level_branch']
        if value is not None:
            row = data['rows'][index]
            condition = _condition_latex(row['condition_ast'], desc['variable'])
            choices = [rf'第{n+1}段：${_condition_latex(r["condition_ast"], desc["variable"])}$，代入 ${latex(r["expression"])}$'
                       for n, r in enumerate(data['rows'])]
            interaction, expected = _choice(choices[index], [c for n, c in enumerate(choices) if n != index])
            definitions = _lines([rf'\text{{第{n+1}段}}:\quad {latex(r["expression"])},\quad {_condition_latex(r["condition_ast"], desc["variable"])}'
                                  for n, r in enumerate(data['rows'])])
            view = _card('先确定比较值用哪一段', rf'原题要比较 ${f}({latex(x)})$ 与 ${f}({latex(value)})$。输入 ${latex(value)}$ 落在哪一段？',
                         '原函数的各段', definitions, '计算比较值所用的解析式',
                         rf'{latex(value)}\in {latex(row["domain"])}\quad\Rightarrow\quad {f}({latex(value)})={_substitution_latex(row["expression_ast"], value)}',
                         '用括号里的输入选段。这里要判断的是固定输入，而不是未知的自变量。', interaction, expected)
            view['proof'] = view['derivation']['items'][1]['math']
            views.append(view)
            calculation = _substitution_latex(row['expression_ast'], value)
            call = rf'{f}({latex(value)})'
            premise = _lines([condition, rf'{call}={calculation}'])
        else:
            call = r'c'
            calculation = latex(level)
            premise = rf'c={calculation}'
        interaction, expected = _choice(rf'${latex(level)}$', [rf'${latex(level+1)}$', rf'${latex(level-1)}$'])
        view = _card('算出比较值', rf'先算出 ${call}$，再将原题改写成与这个数比较的不等式。',
                     '代入计算', premise, '比较值与目标不等式', _lines([rf'{call}={latex(level)}', target]),
                     '比较值确定后，各段都要与同一个数比较。', interaction, expected)
        view['proof'] = _lines([rf'{call}={calculation}={latex(level)}', target])
        views.append(view)
    elif values['phase'] == 'branches':
        for index, row in enumerate(values['branch_results'], 1):
            condition = _condition_latex(row['condition_ast'], desc['variable'])
            expression, candidates, accepted = row['expression'], row['candidates'], row['accepted']
            inequality = _inequality(expression, op, level)
            interaction, expected = _choices(candidates, [sp.S.Reals-candidates, accepted])
            view = _card(f'第{index}段：解不等式',
                         rf'当 ${condition}$ 时，${f}({latex(x)})={latex(expression)}$。由 ${target}$ 得到下面的不等式，先求它的解集。',
                         '本段范围与不等式', _lines([condition, inequality]), '不等式的解（下一步检查范围）',
                         rf'{latex(x)}\in {latex(candidates)}',
                         '先解这个多项式不等式，再检查本段范围；严格不等号不包含零点。', interaction, expected)
            normalized_op = '>' if op in ('>', '<') else '>='
            positive = row['positive_expression']
            proof = [inequality, _inequality(positive, normalized_op, 0)]
            factored = sp.factor(positive)
            if factored != positive:
                proof.append(_inequality(factored, normalized_op, 0))
            proof.append(rf'{latex(x)}\in {latex(candidates)}')
            view['proof'] = _lines(proof)
            view.update(_graphs(row, x, op))
            views.append(view)
            interaction, expected = _choices(accepted, [candidates, row['rejected']])
            view = _card(f'第{index}段：与本段范围取交',
                         rf'刚解出 ${inequality}$ 的解集，但这一段只适用于 ${condition}$。应保留哪个范围？',
                         '刚求出的解集与本段范围', _lines([rf'{latex(x)}\in {latex(candidates)}', condition]),
                         '本段保留的解', rf'{latex(x)}\in {latex(accepted)}',
                         '同时满足不等式和本段条件才保留。注意分界点属于哪一段。', interaction, expected)
            candidate_set = latex(candidates)
            if isinstance(candidates, sp.Union):
                candidate_set = rf'\left({candidate_set}\right)'
            view['proof'] = rf'{candidate_set}\cap {latex(row["domain"])}={latex(accepted)}'
            view['completion_graphs'] = drawing.number_lines([accepted], x, title=f'第{index}段保留的解')
            views.append(view)
    elif values['phase'] == 'merge':
        rows, answer = values['branch_results'], values['feasible_set']
        interaction, expected = _choices(answer, [*(r['accepted'] for r in rows), sp.Union(*(r['candidates'] for r in rows))])
        view = _card('合并各段的解集', '把各段保留的范围合起来。连接处只要有一段包含该点，就要把它保留。',
                     '各段保留的解集', _lines([rf'\text{{第{n}段}}:\quad {latex(r["accepted"])}' for n, r in enumerate(rows, 1)]),
                     '原不等式的解集', rf'{latex(x)}\in {latex(answer)}',
                     '各段结果取并集；不能把属于其中一段的分界点漏掉。', interaction, expected)
        view['proof'] = r'\cup'.join(latex(r['accepted']) for r in rows)+'='+latex(answer)
        view['completion_graphs'] = drawing.number_lines([answer], x, title='原不等式的解集')
        views.append(view)
    else:
        raise ValueError('piecewise_inequality.unknown_phase')
    return views


def presentation(values):
    views = phase_views(values)
    view = views[0]
    left, right = view['derivation']['items']
    return {'formula_title': {'level': '求出比较值', 'branches': '逐段解不等式并检查范围', 'merge': '合并各段的解集'}[values['phase']],
            'formula_explanation': '\n\n'.join('$$'+v['proof']+'$$' for v in views),
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_piecewise(seeds, interaction_id):
    (seed,) = seeds
    views = phase_views(decode_value(seed['values']))
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        interaction = deepcopy(view['interaction'])
        interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        graphs = {k: deepcopy(view[k]) for k in ('graph', 'completion_graph', 'completion_graphs') if k in view}
        if len(graphs.get('completion_graphs', [])) == 1:
            graphs['completion_graph'] = graphs.pop('completion_graphs')[0]
        parts.append({'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                      'interaction': interaction, 'expected_answer': view['expected_answer'],
                      'feedback': view['feedback'], 'submit_label': '确认这一步',
                      'stem_board': board, 'completion_board': view['derivation'],
                      **graphs})
    return {'parts': parts, 'diagnostics': []}
