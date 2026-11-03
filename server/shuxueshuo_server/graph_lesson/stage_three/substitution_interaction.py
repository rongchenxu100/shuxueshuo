"""Interval transport card owned by the shared substitution capability."""

from copy import deepcopy

import sympy as sp

from .math_values import latex
from .trajectory import decode_value


def _function_label(values):
    x = latex(values['original_variable'])
    return (f'{values["function_name"]}({x})' if values['function_name']
            else latex(values['original_expression']))


def range_presentation(values):
    """Name the original function while using its certified substituted range."""
    t = latex(values['x'])
    expression, domain = values['function'], values['domain']
    label = _function_label(values)
    identity = f'{label}={latex(expression)}'
    result = rf'{label}\in{latex(values["range"]["set"])}'
    proof = [rf'{identity},\quad {t}\in{latex(domain)}']
    poly = sp.Poly(expression, values['x'])
    if poly.degree() == 2:
        a, b, c = poly.all_coeffs()
        vertex, extremum = -b/(2*a), c-b*b/(4*a)
        square = sp.Add(sp.Mul(a, sp.Pow(values['x']-vertex, 2, evaluate=False), evaluate=False),
                        extremum, evaluate=False)
        proof.append(f'{label}={latex(square)}')
    for point in values['points']:
        proof.append(rf'{t}={latex(point["point"])}\in{latex(domain)}'
                     rf'\Rightarrow {label}={latex(point["value"])}')
    for endpoint in values['endpoints']:
        point, value = endpoint['point'], endpoint['value']
        if endpoint['attained']:
            proof.append(rf'{t}={latex(point)}\Rightarrow {label}={latex(value)}')
        else:
            side = '' if point in (sp.oo, -sp.oo) else ('^+' if point == domain.start else '^-')
            proof.append(rf'{t}\to{latex(point)}{side}\Rightarrow {label}\to{latex(value)}')
    proof.append(result)
    return {'range_label': label, 'range_identity': identity,
            'range_title': f'求 ${label}$ 的值域', 'range_result': result,
            'range_explanation': '\n'.join('$$'+line+'$$' for line in proof)}


def compile_step(seeds, interaction_id):
    v = decode_value(seeds[0]['values'])
    if seeds[0]['template'] == 'reciprocal_restore':
        return restore(v, interaction_id)
    t, x = latex(v['new_variable']), latex(v['original_variable'])
    target = v['domain']
    alternatives = [target, sp.Interval(target.start, target.end), v['original_domain'], sp.S.Reals]
    distinct = list(dict.fromkeys(alternatives))
    options = [{'value': f'choice-{i}', 'label': rf'${t}\in{latex(value)}$'} for i, value in enumerate(distinct)]
    board = {'layout': 'derivation', 'caption': '换元时，表达式和变量范围一起变化', 'connector': '⇒', 'items': [
        {'label': '原变量与换元关系', 'math': rf'{x}\in{latex(v["original_domain"])},\quad {t}={latex(v["forward"])}'},
        {'label': '新变量的范围', 'math': None},
    ]}
    completed = deepcopy(board)
    completed['items'][1]['math'] = rf'{t}\in{latex(target)}'
    return {'parts': [{
        'id': interaction_id+'#1', 'title': '换元，并确定新变量的范围',
        'question': rf'令 ${t}={latex(v["forward"])}$，原来 ${x}\in{latex(v["original_domain"])}$。新变量 ${t}$ 能取哪些值？',
        'interaction': {'type': 'choice', 'field': 'answer', 'options': options}, 'expected_answer': {'one_of': ['choice-0']},
        'feedback': {'answer': rf'$$ {x}\in{latex(v["original_domain"])}\iff {t}\in{latex(target)},\qquad {x}={latex(v["inverse"])} $$'
                     + rf'$$ {latex(v["original_expression"])}={latex(v["expression"])} $$'},
        'submit_label': '确认换元范围', 'stem_board': board, 'completion_board': completed,
    }], 'diagnostics': []}


def restore(v, interaction_id):
    x, t = latex(v['original_variable']), latex(v['new_variable'])
    label = _function_label(v)
    # The checked range supplies the attained quadratic vertex and its exact
    # original input. This card asks for that input, not another range guess.
    if not v['points']:
        # A vertex outside the interval leaves only endpoint bounds. Values do
        # not change under a bijective substitution, even when neither is attained.
        target = v['range']['set']
        options = list(dict.fromkeys([target, sp.S.Reals, sp.S.EmptySet]))
        return {'parts': [{
            'id': interaction_id+'#1', 'title': '换回原变量，保留值域',
            'question': rf'由 ${x}={latex(v["inverse"])}$ 换回原变量后，${label}$ 的值与换元前逐一相同。它的值域是什么？',
            'interaction': {'type': 'choice', 'field': 'answer', 'options': [
                {'value': f'choice-{i}', 'label': rf'${latex(value)}$'} for i, value in enumerate(options)]},
            'expected_answer': {'one_of': ['choice-0']},
            'feedback': {'answer': rf'换元只改变输入的写法，${label}$ 的值域仍为 ${latex(target)}$。'},
            'submit_label': '确认值域',
        }], 'diagnostics': []}
    point = v['points'][0]
    original, transformed = point['point'], point['transformed_point']
    answers = list(dict.fromkeys([original, transformed, -original]))
    extremum = '最大值' if point['value'] == v['range']['sup'] else '最小值'
    board = {'layout': 'derivation', 'caption': f'把 ${label}$ 取到{extremum}时的新变量换回原变量', 'connector': '⇒', 'items': [
        {'label': '换元关系与取值点', 'math': rf'{t}={latex(transformed)},\quad {x}={latex(v["inverse"])}'},
        {'label': '原变量的取值', 'math': None},
    ]}
    completed = deepcopy(board)
    completed['items'][1]['math'] = rf'{x}={latex(original)}'
    return {'parts': [{
        'id': interaction_id+'#1', 'title': '把取值点换回原变量',
        'question': rf'在 ${t}={latex(transformed)}$ 时，${label}$ 取到{extremum}。由 ${x}={latex(v["inverse"])}$，此时 ${x}$ 等于多少？',
        'interaction': {'type': 'choice', 'field': 'answer', 'options': [
            {'value': f'choice-{i}', 'label': rf'${x}={latex(answer)}$'} for i, answer in enumerate(answers)]},
        'expected_answer': {'one_of': ['choice-0']},
        'feedback': {'answer': rf'$$ {t}={latex(transformed)}\Rightarrow {x}={latex(v["inverse"])}={latex(original)} $$'
                     + rf'此时 ${label}={latex(point["value"])}$。'},
        'submit_label': '确认原变量', 'stem_board': board, 'completion_board': completed,
    }], 'diagnostics': []}
