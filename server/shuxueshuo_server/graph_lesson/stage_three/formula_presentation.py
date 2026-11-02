"""Four local decisions: input range, legal inverse, rule, complete coverage."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_formula import source_values
from . import interaction_graphs as drawing
from .abstract_domain_presentation import _set_latex
from .evaluation_presentation import _choice, _lines, _math
from .math_values import latex
from .range_presentation import _card, _image_choices
from .trajectory import decode_value


def _excluded(domain):
    holes = sp.S.Reals-domain
    return sorted(holes) if isinstance(holes, sp.FiniteSet) else []


def _condition(domain, variable):
    if domain == sp.S.Reals:
        return rf'{latex(variable)}\in\mathbb{{R}}'
    holes = _excluded(domain)
    if len(holes) == 1:
        return rf'{latex(variable)}\ne{latex(holes[0])}'
    if holes:
        return rf'{latex(variable)}\notin\left\{{{",".join(latex(value) for value in holes)}\right\}}'
    return rf'{latex(variable)}\in{_set_latex(domain)}'


def phase_view(values):
    desc, result, phase = (values[key] for key in ('description', 'formula_result', 'phase'))
    if result.get('derivation') == 'assignment':
        from .assignment_presentation import phase_view as assignment_view
        return assignment_view(values)
    if result.get('derivation') == 'equation_system':
        from .system_presentation import phase_view as system_view
        return system_view(values)
    if result.get('derivation') == 'coefficients':
        from .coefficients_presentation import phase_view as coefficients_view
        return coefficients_view(values)
    if result.get('derivation') == 'matching':
        from .matching_presentation import phase_view as matching_view
        return matching_view(values)
    source = source_values(desc)
    x, t, f = sp.Symbol(desc['variable'], real=True), result['variable'], desc['function_name']
    g, h = source.expressions(x)
    original = rf'{f}({latex(g)})={latex(h)}'
    substitution = rf'{latex(t)}={latex(g)}'
    t_range = _condition(result['determined_domain'], t)
    inverse = rf'{latex(x)}={latex(result["inverse_input"])}'
    inverse_root = (rf'\sqrt{{{latex(x)}}}={latex(result["inverse_root"])}\geq0'
                    if source.root_input else None)
    rule = rf'{f}({latex(t)})={latex(result["expression"])}'
    if phase == 'input_range':
        if source.rational_input:
            wrong_domains = [source.domain, sp.S.Reals]
            wrong = list(dict.fromkeys(_condition(domain, t) for domain in wrong_domains if domain != source.image))
            interaction, expected = _choice(f'${t_range}$', [f'${item}$' for item in wrong])
            omitted = source.a/source.c
            remainder = (source.b*source.c-source.a*source.d)/(source.c*(source.c*x+source.d))
            split = sp.Add(omitted, remainder, evaluate=False)
            explanation = rf'将分式改写成 ${latex(t)}={latex(split)}$，分数部分不可能等于 $0$，所以 ${latex(t)}\ne{latex(omitted)}$。'
            extra = [value for value in sorted(source.excluded_inputs) if source.c*value+source.d != 0]
            for value in extra:
                explanation += rf' 原题还排除了 ${latex(x)}={latex(value)}$，对应的 ${latex(t)}={latex(g.subs(x, value))}$ 也不能取。'
            return _card('换元后，哪些数不能取',
                         rf'原题中 ${_condition(source.domain, x)}$。令 ${substitution}$，${latex(t)}$ 不能取哪些值？',
                         '原关系与换元', _lines([original, substitution]), '新变量的限制', t_range,
                         explanation, interaction, expected)
        if not source.root_input:
            wrong = h if sp.expand(h-g) != 0 else g+1
            interaction, expected = _choice(f'${substitution}$', [rf'${latex(t)}={latex(wrong)}$'])
            return _card('把函数的输入换成新变量',
                         rf'要把 ${f}({latex(g)})$ 写成 ${f}({latex(t)})$，应该令什么等于 ${latex(t)}$？',
                         '原关系', original, '选取新变量', _lines([substitution, t_range]),
                         rf'把 ${latex(g)}$ 整体设为 ${latex(t)}$。原变量能取任意实数，${latex(t)}$ 也能取任意实数。',
                         interaction, expected)
        interaction, expected = _image_choices(result['determined_domain'], sp.S.Reals)
        return _card('整体换元，确定新变量范围',
                     rf'根式要求原变量 ${latex(x)}\geq0$。令 ${substitution}$，新变量 ${latex(t)}$ 能取哪些值？',
                     '原关系与换元', _lines([original, substitution]), '整体输入的范围', t_range,
                     _math(rf'{latex(x)}\geq0', rf'\sqrt{{{latex(x)}}}\geq0', t_range), interaction, expected)
    if phase == 'inverse':
        if source.root_input:
            wrong = result['inverse_root']
            question = '先利用新变量的范围确认根式非负，再平方。原变量可以怎样表示？'
        else:
            wrong = g.subs(x, t)
            if sp.cancel(wrong-result['inverse_input']) == 0:
                wrong += 1
            question = rf'由 ${substitution}$ 解出 ${latex(x)}$，应该得到哪个式子？'
        wrong = rf'{latex(x)}={latex(wrong)}'
        interaction, expected = _choice(f'${inverse}$', [f'${wrong}$'])
        algebra = [substitution, inverse]
        if source.rational_input:
            algebra = [substitution,
                       rf'{latex(t)}\left({latex(source.c*x+source.d)}\right)={latex(source.a*x+source.b)}',
                       rf'\left({latex(source.c*t-source.a)}\right){latex(x)}={latex(source.b-source.d*t)}', inverse]
        return _card('合法反解原变量' if source.root_input else '用新变量表示原变量', question,
                     '换元与范围', _lines([substitution, t_range]), '原变量', inverse,
                     _math(*([inverse_root, inverse] if source.root_input else algebra)), interaction, expected)
    if phase == 'rewrite':
        # A common error is to rename the original variable without inverse
        # substitution. A constant RHS needs a distinct fallback distractor.
        unchanged = h.subs(x, t)
        wrong = unchanged if sp.cancel(unchanged-result['expression']) != 0 else result['expression']+1
        interaction, expected = _choice(f'${rule}$',
                                       [rf'${f}({latex(t)})={latex(wrong)}$'])
        return _card('把右式全部改写为新变量', rf'将已得到的反解代入原关系，${f}({latex(t)})$ 等于什么？',
                     '原式与反解', _lines([original, *([inverse_root] if source.root_input else []), inverse]), '恢复的规则', rule,
                     _math(rule, t_range), interaction, expected)
    if phase != 'coverage':
        raise ValueError('function_formula.unknown_phase')
    return answer_view(desc, result, source)


def answer_view(desc, result, source, *, coverage_override=None):
    x, t, f = sp.Symbol(desc['variable'], real=True), result['variable'], desc['function_name']
    g, _ = source.expressions(x)
    substitution = rf'{latex(t)}={latex(g)}'
    t_range = _condition(result['determined_domain'], t)
    inverse = rf'{latex(x)}={latex(result["inverse_input"])}' if 'inverse_input' in result else ''
    rule = rf'{f}({latex(t)})={latex(result["expression"])}'
    requested = result['status'] == 'insufficient_information'
    determined = result['determined_domain']
    endpoint = (determined.start if determined.start.is_finite else determined.end) if source.root_input else source.b
    reminder = '换元后得到的范围，要随解析式一起保留。'
    if requested:
        reminder += ' 题目要求全体实数上的解析式，现有条件还不足以确定范围外的情况。'
    if source.rational_input:
        alternatives = [
            (determined, reminder),
            (result['source_domain'], rf'这是原题中 ${latex(x)}$ 的限制。答案里应保留换元后 ${latex(t)}$ 的限制：${t_range}$。'),
            (sp.S.Reals, '化简后的式子不代表任意实数都能取。原关系没有确定被排除位置的函数值。'),
        ]
        if len(_excluded(determined)) > 1:
            alternatives.append((sp.S.Reals-sp.FiniteSet(source.a/source.c), '原式中其他分母带来的限制也要保留，约分不能补回这些函数值。'))
    elif source.root_input:
        opened = sp.Interval(determined.start, determined.end, left_open=True, right_open=True)
        alternatives = [
            (determined, reminder),
            (sp.S.Reals, '算出的式子虽然可以代入任意实数，但题目只确定了新变量取值范围内的函数值。'),
            (result['source_domain'], rf'这是原题根号下变量的范围；换元后的范围应由 ${substitution}$ 确定。'),
            (opened, rf'端点 ${latex(endpoint)}$ 也能取到：原题中令 ${latex(x)}=0$，就有 ${latex(g)}={latex(endpoint)}$。'),
        ]
    else:
        reminder = '新变量能取任意实数，所以完整答案的范围是全体实数。'
        alternatives = [
            (determined, reminder),
            (sp.Interval(source.b, sp.oo), rf'原变量没有非负限制。由 ${substitution}$ 可知，${latex(t)}$ 也能取小于 ${latex(source.b)}$ 的数。'),
            (sp.Interval(-sp.oo, source.b), rf'原变量没有非正限制。由 ${substitution}$ 可知，${latex(t)}$ 也能取大于 ${latex(source.b)}$ 的数。'),
        ]
    options, ranges, seen = [], [], []
    for interval, feedback in alternatives:
        if interval in seen:
            continue
        seen.append(interval)
        value = f'o{len(options)+1}'
        holes = _excluded(interval)
        if interval == sp.S.Reals or holes:
            condition = _condition(interval, x)
            left, right, left_closed, right_closed = None, None, False, False
        else:
            left = float(interval.start) if interval.start.is_finite else None
            right = float(interval.end) if interval.end.is_finite else None
            left_closed, right_closed = not interval.left_open, not interval.right_open
            op = (r'\geq' if left_closed else '>') if left is not None else (r'\leq' if right_closed else '<')
            condition = rf'{latex(x)}{op}{latex(interval.start if left is not None else interval.end)}'
        options.append({'value': value, 'label': f'${condition}$', 'feedback': feedback})
        ranges.append({'value': value, 'condition': condition, 'left': left, 'right': right,
                       'left_closed': left_closed, 'right_closed': right_closed,
                       **({'excluded': [float(point) for point in holes]} if holes else {})})
    points = ({sp.S.Zero} | {point for interval, _ in alternatives for point in _excluded(interval)}
              if source.rational_input else {sp.S.Zero, endpoint})
    points = sorted(points)
    marks = list(map(float, points))
    pad = max(1, (marks[-1]-marks[0])/2)
    final_rule = rf'{f}({latex(x)})={latex(result["expression"].subs(t, x))}'
    coverage = (rf'任取 ${t_range}$ 中的一个数，取原变量 ${inverse}$，就能使 ${substitution}$。'
                '因此，这个范围里的每个数都能取到。')
    if source.root_input or source.rational_input:
        coverage += '范围外的函数值，题目没有告诉我们。'
    if coverage_override is not None:
        coverage = coverage_override
    view = _card('写出完整答案',
                 rf'把字母 ${latex(t)}$ 换成 ${latex(x)}$，取值范围也要保留。请补全答案。',
                 '前面已经得到', _lines([rule, t_range]), '完整答案',
                 _lines([final_rule, _condition(determined, x)]), reminder,
                 {'type': 'choice', 'field': 'answer', 'options': options}, {'one_of': ['o1']})
    view['answer_completion'] = {
        'given': _math(rule, t_range), 'formula': final_rule, 'variable': latex(x),
        'reminder': reminder, 'coverage': coverage, 'ranges': ranges,
        'bounds': [marks[0]-pad, marks[-1]+pad],
        'ticks': [{'at': float(point), 'label': latex(point)} for point in points],
    }
    return view


def presentation(values):
    view = phase_view(values)
    left, right = view['derivation']['items']
    explanation = view['explanation']
    if values['formula_result'].get('derivation') == 'coefficients':
        from .coefficients_derivation import full_derivation
        explanation = full_derivation(values)
    elif values['formula_result'].get('derivation') == 'equation_system':
        from .system_presentation import full_derivation
        explanation = full_derivation(values)
    elif values['formula_result'].get('derivation') == 'assignment':
        from .assignment_derivation import full_derivation
        explanation = full_derivation(values)
    return {'formula_title': view['title'], 'formula_explanation': explanation,
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_formula(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed['values'])
    view = phase_view(values)
    board = deepcopy(view['derivation'])
    board['items'][1]['math'] = None
    interaction = deepcopy(view['interaction'])
    interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{row["value"]}'.encode()).digest())
    part = {'id': interaction_id+'#1', 'title': view['title'], 'question': view['question'],
                       'interaction': interaction, 'expected_answer': view['expected_answer'],
                       'feedback': view['feedback'], 'submit_label': '确认答案' if 'answer_completion' in view else '确认判断',
                       **({'answer_completion': deepcopy(view['answer_completion'])} if 'answer_completion' in view else {}),
                       'stem_board': board, 'completion_board': deepcopy(view['derivation'])}
    diagnostics = []
    if values['formula_result'].get('derivation') == 'coefficients':
        from .coefficients_presentation import inequality_graphs
        try:
            part.update(inequality_graphs(values))
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
            part['question'] = '结合零点和开口方向，原不等式的解集是什么？'
    return {'parts': [part], 'diagnostics': diagnostics}
