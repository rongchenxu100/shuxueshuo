"""Evaluate the comparison value, solve each branch, intersect, then unite."""

from copy import deepcopy
from hashlib import sha256
from itertools import pairwise

import sympy as sp

from ..function_evaluation import _substitution_latex
from ..function_monotonicity import _direction
from ..piecewise_inequality import RELATIONS, REVERSED, source
from . import interaction_graphs as drawing
from .evaluation_presentation import _choice, _condition_latex, _lines
from .interaction_graph_contract import validate_graph
from .math_values import latex
from .monotonicity_presentation import graph_for
from .piecewise_equation_presentation import _choices
from .range_presentation import _card
from .trajectory import decode_value


def _inequality(left, op, right):
    return latex(RELATIONS[op](left, right, evaluate=False))


def _function_model(data):
    """Build a piecewise-curve model for the defining function of f."""
    t = sp.Symbol('t', real=True)
    piece = data['piece_variable']
    branches, partition, directions, domains = [], [], [], []
    for index, row in enumerate(data['rows']):
        expr = sp.simplify(row['expression'].subs(piece, t))
        domain = row['domain']
        poly = sp.Poly(expr, t)
        axis = None if poly.degree() < 2 else -poly.nth(1)/(2*poly.nth(2))
        branches.append({
            'expression': expr, 'domain': domain, 'axis': axis,
            'coefficients': [poly.nth(i) for i in (2, 1, 0)],
        })
        cuts = [domain.inf, *([axis] if axis is not None and domain.inf < axis < domain.sup else []), domain.sup]
        for low, high in pairwise(cuts):
            interval = sp.Interval(low, high, left_open=low not in domain, right_open=high not in domain)
            direction = _direction(poly, interval)
            partition.append({
                'interval': interval, 'direction': direction, 'inner_direction': direction,
                'branch': index, 'layers': [], 'strict': direction != 0,
                'difference_factor': [poly.nth(2), poly.nth(1)],
            })
            directions.append((interval, direction))
        domains.append(domain)
    model = {
        'function': data['function'], 'variable': t, 'family': 'explicit_piecewise',
        'effective_domain': sp.Union(*domains), 'branches': branches, 'partition': partition,
    }
    return model, directions, domains


def _display_expr(expr):
    """Canonicalize for plain SVG labels (``1 - x²``)."""
    return sp.expand(expr)


def _pref_latex(expr):
    """Prefer ``1 - x^{2}`` over SymPy's ``- x^{2} + 1`` so text matches the problem."""
    import re
    text = latex(sp.expand(expr))
    match = re.fullmatch(r'-\s*(.+)\s*\+\s*(.+)', text)
    if match:
        return f'{match.group(2).strip()} - {match.group(1).strip()}'
    return text


def _piece_sub_latex(body, piece, arg):
    """Substitute an input into a piece formula while keeping preferred latex for the input."""
    dummy = sp.Symbol('ARG')
    return latex(body.xreplace({piece: dummy})).replace('ARG', rf'\left({_pref_latex(arg)}\right)')


def _membership(expr, domain):
    """State that an input expression falls in a piece domain, without “第 n 段”."""
    shown = _pref_latex(expr)
    parts = []
    if domain.inf.is_finite:
        op = r'\ge' if not domain.left_open else '>'
        parts.append(rf'{shown}{op}{latex(domain.inf)}')
    if domain.sup.is_finite:
        op = r'\le' if not domain.right_open else '<'
        parts.append(rf'{shown}{op}{latex(domain.sup)}')
    return r',\ '.join(parts) if parts else rf'{shown}\in\mathbb{{R}}'


def _overview_graphs(data):
    """Draw actual branch ranges and directions, including quadratic turns."""
    model, directions, _ = _function_model(data)
    pending = graph_for(model, focus=sp.S.Reals)
    pending['caption'] = (
        rf'原函数 ${data["function"]}$ 的分段图像：观察各段的范围、增减和分界点。')
    pending['params']['description'] = (
        '水平段表示常值；若整条曲线上有平台，就不是严格单调。')
    done = graph_for(model, directions=directions)
    done['caption'] = (
        rf'原函数 ${data["function"]}$：按图中各段范围，分别确定两个输入应代入的表达式。')
    done['params']['description'] = (
        '箭头标出已确认的段内方向；水平段上不同输入可以对应同一个函数值。')
    return {'graph': pending, 'completion_graph': done}


def _case_scope(left_mem, right_mem, x, cell, relation=None):
    """Show case conditions, the induced x-range, and an optional converted comparison."""
    lines = [left_mem, right_mem, rf'\Rightarrow {latex(x)}\in {latex(cell)}']
    if relation:
        lines.append(relation)
    return _lines(lines)


def _case_sample(region):
    if region == sp.S.EmptySet:
        return None
    if isinstance(region, sp.Union):
        region = min(region.args, key=lambda item: item.inf)
    if not isinstance(region, sp.Interval):
        return None
    lo, hi = region.inf, region.sup
    if lo.is_finite and hi.is_finite:
        return (lo + hi) / 2
    if lo.is_finite:
        return lo + (1 if region.left_open else sp.Rational(1, 2))
    if hi.is_finite:
        return hi - (1 if region.right_open else sp.Rational(1, 2))
    return sp.S.Zero


def _model_value(model, at):
    """Exact piece value of f at a real abscissa, used only to frame the view."""
    t = model['variable']
    point = sp.sympify(at)
    for branch in model['branches']:
        # SymPy may return BooleanTrue; do not compare with ``is True``.
        if branch['domain'].contains(point):
            return float(sp.N(branch['expression'].subs(t, point)))
    return None


def _case_piece_graph(data, row):
    """Highlight used piece(s); mark sample positions of the two inputs on the curve."""
    model, _, domains = _function_model(data)
    x, u, v = data['variable'], data['left'], data['right']
    left_dom = domains[row['left_branch']]
    right_dom = domains[row['right_branch']]
    highlight = []
    for domain in (left_dom, right_dom):
        if all(domain != seen for seen in highlight):
            highlight.append(domain)
    pending = graph_for(model, highlight=highlight)
    pending['params']['interval_marks'] = []
    # Keep only branch breakpoints on the axis; do not stamp sample abscissae as ticks.
    points = []
    sample = _case_sample(row['accepted'] if row['accepted'] != sp.S.EmptySet else row['cell'])
    if sample is not None:
        # Left input above, right input below — vertical callouts, not diagonal.
        for expr, place in ((u, 'above'), (v, 'below')):
            value = sp.simplify(expr.subs(x, sample))
            if value.is_real and value.is_finite:
                points.append({'x': float(value), 'label': drawing.plain(_display_expr(expr)), 'place': place})
    if points:
        xs = [point['x'] for point in points]
        ys = [y for point in points if (y := _model_value(model, point['x'])) is not None]
        lo, hi, bottom, top = pending['params']['bounds']
        x_pad = max(1.0, (max(xs) - min(xs)) * 0.25 if max(xs) > min(xs) else 1.0)
        y_pad = max(1.0, (max(ys) - min(ys)) * 0.25 if ys and max(ys) > min(ys) else 1.0)
        pending['params']['bounds'] = [
            min(lo, min(xs) - x_pad), max(hi, max(xs) + x_pad),
            min(bottom, *(ys or [bottom])) - y_pad, max(top, *(ys or [top])) + y_pad,
        ]
    pending['params']['points'] = points
    pending['params']['description'] = '上方／下方标注分别对应两个输入在曲线上的示意位置。'
    left_note = _membership(u, left_dom)
    right_note = _membership(v, right_dom)
    pending['caption'] = (
        rf'原函数 ${data["function"]}$：本情况要求 ${left_note}$，且 ${right_note}$。')
    return validate_graph(pending)


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


def _op_tex(op):
    return {'>': '>', '>=': r'\ge', '<': '<', '<=': r'\le'}[op]


def phase_views(values):
    desc = values['description']
    data = source(desc)
    x, f, op = data['variable'], data['function'], data['op']
    views = []
    if values['phase'] == 'applicability':
        constant = [row for row in data['rows'] if not row['expression'].has(data['piece_variable'])]
        if not constant:
            interaction, expected = _choice(
                '分别确定两个输入所在分支，再代入对应表达式比较',
                ['忽略分支条件，两边都代入同一个表达式', '只代入一边的输入就能得到原不等式的解集'])
            view = _card(
                '确定两个输入的分支',
                '使用分段法比较两个函数值时，应怎样选择两边的表达式？',
                '原比较', rf'{f}({latex(data["left"])})\,{_op_tex(op)}\,{f}({latex(data["right"])})',
                '分段比较', r'\text{分别确定两个输入的分支，再代入比较}',
                '每一边都使用其输入所在分支的表达式，并保留对应条件。', interaction, expected)
            view['proof'] = r'\text{两输入分别确定分支，代入比较后与分支条件取交集。}'
            view.update(_overview_graphs(data))
            return [view]
        wrong = [r'整体严格递增，可直接把函数值比较改成输入比较', r'把常值段也当成严格递增']
        interaction, expected = _choice(
            r'不严格单调，改为按两个输入各自所在分支分类比较',
            wrong)
        view = _card(
            '先看整体图像：是否严格单调',
            rf'观察 ${f}$ 的整体图像。它在整个定义域上是否严格单调？',
            '观察整体图像',
            _lines([rf't\in {latex(row["domain"])}:\quad {f}(t)={latex(row["expression"])}'
                    for row in constant]),
            '下一步',
            r'按两个输入各自所在分支分类比较',
            '有常值平台时，不同输入可以有相同函数值，不能用严格单调性做等价转化。',
            interaction, expected)
        view['proof'] = _lines([rf'{f}\text{{ 含常值段}}', rf'{f}\text{{ 整体不严格单调}}'])
        view.update(_overview_graphs(data))
        views.append(view)
        return views
    if values['phase'] in ('cases', 'merge') and data.get('mode') == 'two_inputs':
        cases = values.get('case_results') or values.get('branch_results') or []
        u, v = data['left'], data['right']
        u_tex, v_tex = _pref_latex(u), _pref_latex(v)
        original = rf'{f}\!\left({u_tex}\right)\,{_op_tex(op)}\,{f}\!\left({v_tex}\right)'
        if values['phase'] == 'cases':
            for index, row in enumerate(cases, 1):
                if row['cell'] == sp.S.EmptySet:
                    continue
                left_mem = _membership(u, row['left_domain'])
                right_mem = _membership(v, row['right_domain'])
                title = rf'情况{index}：当 ${left_mem}$ 且 ${right_mem}$'
                piece_graph = _case_piece_graph(data, row)
                reason = row.get('reason')
                if row['accepted'] == sp.S.EmptySet:
                    scope = _case_scope(left_mem, right_mem, x, row['cell'], relation=original)
                    interaction, expected = _choices(sp.S.EmptySet, [row['cell'], sp.S.Reals])
                    view = _card(
                        title + '（无解）',
                        rf'结合图像：当 ${left_mem}$、${right_mem}$ 时，原不等式能否成立？',
                        '本情况条件', scope,
                        '本情况的解', r'\varnothing',
                        '常值段或交叉组合可能使不等式恒不成立。', interaction, expected)
                    view['proof'] = rf'{latex(x)}\in {latex(row["cell"])}\Rightarrow\varnothing'
                    view['graph'] = piece_graph
                    view['completion_graph'] = piece_graph
                    views.append(view)
                    continue
                if reason == 'strict_mono_input_order':
                    _, directions, domains = _function_model(data)
                    piece_domain = domains[row['left_branch']]
                    direction = next(d for domain, d in directions if domain == piece_domain)
                    converted = op if direction == 1 else REVERSED[op]
                    mono = '严格递增' if direction == 1 else '严格递减'
                    # Match the definition's independent variable wording, e.g. “当 x≥0 时”.
                    piece_when = _membership(sp.Symbol('x', real=True), piece_domain)
                    relation = rf'{u_tex}\,{_op_tex(converted)}\,{v_tex}'
                    scope = _case_scope(left_mem, right_mem, x, row['cell'], relation=relation)
                    interaction, expected = _choices(
                        row['accepted'], [row['cell'], row['rejected'], sp.S.Reals])
                    view = _card(
                        title,
                        rf'结合图像：当 ${piece_when}$ 时，${f}$ {mono}，故 ${original}\Leftrightarrow {relation}$。'
                        rf'再与本情况范围取交，求 ${latex(x)}$。',
                        '本情况条件', scope,
                        '本情况解集', rf'{latex(x)}\in {latex(row["accepted"])}',
                        r'同段严格单调时优先用单调性转化，再与条件范围取交。',
                        interaction, expected)
                    view['proof'] = _lines([
                        original, rf'\Leftrightarrow {relation}',
                        rf'{latex(x)}\in {latex(row["accepted"])}'])
                else:
                    piece = data['piece_variable']
                    left_body = _piece_sub_latex(row['left_body'], piece, u)
                    right_body = _piece_sub_latex(row['right_body'], piece, v)
                    relation = rf'{left_body}\,{_op_tex(op)}\,{right_body}'
                    interaction, expected = _choices(
                        row['accepted'], [row['cell'], row['rejected'], sp.S.Reals])
                    if reason == 'left_body_vs_constant':
                        prompt = (
                            rf'结合图像：${v_tex}$ 落在常值段，将 ${u_tex}$ 代入对应段表达式，'
                            rf'得 ${relation}$。求使它成立的 ${latex(x)}$。')
                    elif reason == 'constant_vs_right_body':
                        prompt = (
                            rf'结合图像：${u_tex}$ 落在常值段，将 ${v_tex}$ 代入对应段表达式，'
                            rf'得 ${relation}$。求使它成立的 ${latex(x)}$。')
                    else:
                        prompt = (
                            rf'结合图像：当 ${left_mem}$、${right_mem}$ 时，'
                            rf'比较得 ${relation}$。求使它成立的 ${latex(x)}$。')
                    scope = _case_scope(left_mem, right_mem, x, row['cell'], relation=relation)
                    view = _card(
                        title, prompt,
                        '本情况条件', scope,
                        '本情况解集', rf'{latex(x)}\in {latex(row["accepted"])}',
                        '只在当前输入分支组合内求解，再与该情况的输入范围取交。',
                        interaction, expected)
                    view['proof'] = _lines([
                        original, relation, rf'{latex(x)}\in {latex(row["accepted"])}'])
                view['graph'] = piece_graph
                view['completion_graphs'] = [
                    piece_graph,
                    *drawing.number_lines([row['accepted']], x, title=title),
                ]
                views.append(view)
            return views
        answer = values['feasible_set']
        nonempty = [row for row in cases if row['accepted'] != sp.S.EmptySet]
        interaction, expected = _choices(answer, [*(row['accepted'] for row in nonempty), sp.S.Reals])
        view = _card(
            '合并各情况的解集',
            '把所有左右分支组合下保留的范围合起来。',
            '各情况保留的解集',
            _lines([rf'\text{{情况{n}}}:\quad {latex(row["accepted"])}' for n, row in enumerate(nonempty, 1)]),
            '原不等式的解集', rf'{latex(x)}\in {latex(answer)}',
            '各情况结果取并集；空情况不必再占篇幅。', interaction, expected)
        view['proof'] = r'\cup'.join(latex(row['accepted']) for row in nonempty)+'='+latex(answer)
        view['completion_graphs'] = drawing.number_lines([answer], x, title='原不等式的解集')
        views.append(view)
        return views
    level = values['level']
    target = rf'{f}({latex(x)})'+_op_tex(op)+latex(level)
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
    titles = {
        'applicability': '先看整体图像判断是否严格单调',
        'level': '求出比较值',
        'branches': '逐段解不等式并检查范围',
        'cases': '按两个输入各自所在分支分类比较',
        'merge': '合并各情况的解集',
    }
    return {'formula_title': titles[values['phase']],
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
