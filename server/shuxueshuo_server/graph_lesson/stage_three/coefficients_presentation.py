"""Concrete, progressive choices for coefficient recovery and original goals."""
from copy import deepcopy

import sympy as sp

from ..function_coefficients import coefficient_source, compare_coefficients
from . import interaction_graphs as drawing
from .capabilities import solve_quadratic
from .coefficients_derivation import relation_rows
from .evaluation_presentation import _choice, _lines
from .math_values import latex
from .range_presentation import _card


def phase_view(values):
    desc, r, phase = (values[k] for k in ('description', 'formula_result', 'phase'))
    s = coefficient_source(desc)
    x, f = s.variable, desc['function_name']
    typename = '一次函数' if desc['function_type'] == 'linear' else '二次函数'
    template = rf'{f}({latex(x)})={latex(s.template)},\quad {latex(s.coefficients[0])}\ne0'
    comparison = compare_coefficients(s.relations, x, s.coefficients, sp.S.Reals)
    equations = _lines([latex(sp.Eq(sp.factor(row['left']), row['right'], evaluate=False))
                        for row in comparison['rows'] if sp.expand(row['left']-row['right']) != 0])
    conditions = relation_rows(desc, s)
    identities = _lines([latex(row['expanded']) for row in conditions])
    candidates = _lines([rf'{f}({latex(x)})={latex(p)}'+(r'\quad\text{或}' if i<len(r['candidates'])-1 else '')
                         for i,p in enumerate(r['candidates'])])
    tuples = _lines([r',\quad '.join(rf'{latex(c)}={latex(v)}' for c, v in zip(s.coefficients, row)) for row in r['coefficient_tuples']])
    if phase == 'template':
        wrong = rf'{f}({latex(x)})={latex(s.template-s.coefficients[-1])}'
        i, e = _choice(f'${template}$', [f'${wrong}$'])
        return _card('按函数类型设一般式', f'题目说明了是{typename}，应怎样设解析式？',
                     '题给类型', rf'\text{{{typename}}}', '设一般式', template,
                     '把各项系数设为未知数；最高次项的系数不能是 0，也不能漏掉常数项。', i, e)
    if phase == 'expand':
        wrong_rows = [row['expanded'] for row in conditions]
        eq = wrong_rows[-1]
        wrong_rows[-1] = sp.Eq(eq.lhs+1, eq.rhs, evaluate=False)
        wrong = _lines([latex(eq) for eq in wrong_rows])
        i, e = _choice(f'${identities}$', [f'${wrong}$'])
        question = (f'把已设的解析式分别代入下面 {len(conditions)} 个条件，哪组等式同时满足它们？'
                    if len(conditions) > 1 else '把已设的解析式代入下面的条件，展开后得到什么？')
        card = _card('把一般式代入题给关系', question,
                     '已设解析式', template, '代入并整理', identities,
                     '每个函数调用都按同一个一般式代入。题目给出的初值也要一起代入。', i, e)
        if len(conditions) == 2:
            card['derivation']['condition_groups'] = [
                {'label': f'条件 {index} · '+('函数关系' if row['original'].has(x) else '函数值'),
                 'math': latex(row['original'])} for index, row in enumerate(conditions, 1)]
        else:
            card['derivation']['items'][0]['math'] = _lines([
                template, *[latex(row['original']) for row in conditions]])
        return card
    if phase == 'compare':
        wrong = _lines([latex(sp.Eq(e+1, 0, evaluate=False)) for e in comparison['equations']])
        i, e = _choice(f'${equations}$', [f'${wrong}$'])
        table = r'\begin{array}{c|c|c}\text{次数}&\text{左边系数}&\text{右边系数}\\\hline '
        table += r'\\'.join(rf'{row["degree"]}&{latex(row["left"])}&{latex(row["right"])}' for row in comparison['rows'])+r'\end{array}'
        return _card('同次幂的系数分别相等',
                     rf'上一步得到 ${identities}$，且对任意实数 ${latex(x)}$ 都成立。比较同次幂的系数，应列出哪组方程？',
                     '比较系数（缺项记为 0）', table, '系数满足的方程', equations,
                     '分别比较二次项、一次项和常数项。只在某一个数处相等，不能这样比较系数。', i, e)
    if phase == 'solve':
        wrong = (_lines([r',\quad '.join(rf'{latex(c)}={latex(v)}' for c, v in zip(s.coefficients, r['coefficient_tuples'][0]))])
                 if len(r['coefficient_tuples']) > 1 else
                 _lines([r',\quad '.join(rf'{latex(c)}={latex(v+1)}' for c, v in zip(s.coefficients, r['coefficient_tuples'][0]))]))
        i, e = _choice(f'${tuples}$', [f'${wrong}$'])
        return _card('求出所有系数', '解这组方程，并保留所有符合函数类型的结果。',
                     '系数方程', equations, '全部系数组合', tuples,
                     '每组系数都要满足全部方程，且最高次项系数不为 0。如果有多组合法解，需全部保留。', i, e)
    if phase == 'verify':
        multiple = len(r['candidates']) > 1
        title = '把每个结果代回检查' if multiple else '把结果代回检查'
        question = ('已经求出这些解析式，怎样确认它们都符合题意？' if multiple else
                    '已经求出这个解析式，怎样确认它符合题意？')
        i, e = (_choice('逐个代回原关系，并检查函数类型', ['只检查其中一个解析式']) if multiple else
                _choice('代回原题的全部等式，并检查函数类型', ['只检查函数类型，不代回原题']))
        verified = _lines([rf'{f}({latex(x)})={latex(p)}:\quad '+r',\quad '.join(
            latex(sp.Eq(eq.lhs.subs(dict(zip(s.coefficients, row))), eq.rhs.subs(dict(zip(s.coefficients, row))), evaluate=False))
            for eq in s.relations) for p,row in zip(r['candidates'],r['coefficient_tuples'])])
        return _card(title, question,
                     '得到的解析式', candidates, '回验原题的每个等式', verified,
                     ('逐个' if multiple else '')+'代回原题的全部等式，左右两边恒等；最高次项系数也满足题给函数类型。', i, e)
    if phase != 'answer':
        raise ValueError('function_coefficients.unknown_phase')
    if s.kind == 'find_value':
        steps = _lines([rf'{f}({latex(x)})={latex(p)}\quad\Rightarrow\quad {f}({latex(s.requested)})={latex(v)}'
                        for p,v in zip(r['candidates'],r['values'])])
        if r['status'] == 'complete':
            i,e=_choice(rf'${latex(r["value"])}$', [rf'${latex(r["value"]+1)}$', '有多个解析式，所以函数值不能确定'])
            conclusion = rf'{f}({latex(s.requested)})={latex(r["value"])}'
            explanation = '将题目要求的输入分别代入所有解析式，得到的函数值相同，因此这一问有唯一答案。'
        else:
            i,e=_choice('不能唯一确定', [rf'${latex(r["values"][0])}$'])
            conclusion = r'\text{所求函数值不能唯一确定}'
            explanation = '不同的合法解析式给出了不同的函数值，不能只选其中一个。'
        return _card('回到原题，计算函数值', rf'题目问的是 ${f}({latex(s.requested)})$。将它代入每个解析式后，应怎样回答？',
                     '各个解析式的计算结果', steps, '原题答案', conclusion, explanation, i,e)
    if s.kind == 'find_range':
        op,rhs=s.requested
        if r['solution'] is None:
            i,e=_choice('不能唯一确定解集', [f'${latex(r["solution_sets"][0])}$'])
            conclusion=r'\text{解集不能唯一确定}'
        else:
            correct=r['solution'];wrong=sp.S.Reals-correct
            i,e=_choice(f'${latex(correct)}$', [f'${latex(wrong)}$'])
            conclusion=rf'{latex(x)}\in {latex(correct)}'
        inequalities=_lines([latex({'>' :sp.Gt, '>=':sp.Ge,'<':sp.Lt,'<=':sp.Le}[op](p,rhs,evaluate=False)) for p in r['candidates']])
        question = '求出解析式还没有结束。结合零点和开口方向，原不等式的解集是什么？'
        if len(r['candidates']) == 1 and desc['function_type'] == 'quadratic':
            side = '上方' if op in ('>', '>=') else '下方'
            side += '或轴上' if op in ('>=', '<=') else ''
            question = rf'图像在 ${latex(x)}$ 轴{side}时，不等式成立。对应的 ${latex(x)}$ 的取值范围是什么？'
        return _card('解原题的不等式', question,
                     '将解析式代入原不等式', inequalities, '原题解集', conclusion,
                     '先求零点，再按开口方向判断各段的正负。严格不等号不包含零点。', i,e)
    wrong = rf'{f}({latex(x)})={latex(r["candidates"][0])}' if len(r['candidates'])>1 else rf'{f}({latex(x)})={latex(r["candidates"][0]+1)}'
    i,e=_choice(f'${candidates}$', [f'${wrong}$'])
    return _card('写出全部解析式', '哪些解析式满足原题的全部条件？',
                 '已验证的系数组合', tuples, '全部答案', candidates,
                 '把各组系数代回一般式。多个解析式之间用“或”连接；一次、二次函数的定义域均为实数集。', i,e)


def inequality_graphs(values):
    """Reuse the parabola and number line, revealing the solution only on completion."""
    desc, r = values['description'], values['formula_result']
    if values['phase'] != 'answer' or len(r['candidates']) != 1 or desc['function_type'] != 'quadratic':
        return {}
    s = coefficient_source(desc)
    if s.kind != 'find_range' or r['solution'] is None:
        return {}
    x, (op, rhs) = s.variable, s.requested
    residual = r['candidates'][0] - rhs
    drawn = drawing.family(residual, x)
    roots = solve_quadratic(residual, x)['outputs']['roots']
    anchors = [drawn['vertex'][0], *roots]
    margin = max(max(anchors)-min(anchors), sp.S.One)/4
    # Fit the roots and turning point closely enough to read the sign of y.
    frame = sp.Interval(min(anchors)-margin, max(anchors)+margin)
    bounds, _ = drawing.function_frame(drawn, x, frame, show_vertex=True)
    ticks = drawing.ticks(roots, *bounds[:2])
    relation = rf'{desc["function_name"]}({latex(x)})'
    if rhs != 0:
        relation += rf'-\left({latex(rhs)}\right)'
    graph = drawing.function_graph(
        drawn, x, sp.Interval(-sp.oo, sp.oo), bounds=bounds, x_ticks=ticks,
        marks=[(root, True) for root in roots],
        title=f'y={drawing.plain(residual)} 的图像',
        description='观察抛物线与横轴的位置，判断不等式成立的范围。',
        caption=rf'$y={relation}={latex(residual)}$。先找到零点，再观察曲线与横轴的位置。')
    completed = deepcopy(graph)
    strict = op in ('>', '<')
    completed['params'].update(
        markSign='above' if op in ('>', '>=') else 'below', strict=strict,
        points=[{'x': float(root), 'open': strict} for root in roots])
    completed['caption'] = '高亮曲线对应不等式成立的部分；'+('零点不取。' if strict else '零点也取。')
    completed['params']['description'] = f'解集为 {drawing.plain(r["solution"])}。'
    return {'graph': graph, 'completion_graphs': [completed, *drawing.number_lines(
        [r['solution']], x, title='原不等式的解集')]}
