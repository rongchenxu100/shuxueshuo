"""M3 cards: input interval, vertex, bounds, then the complete output image."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from . import interaction_graphs as drawing
from .abstract_domain_presentation import _derivation, _set_latex
from .evaluation_presentation import _choice, _lines, _math
from .math_values import latex
from .trajectory import decode_value


def _card(title, question, left_label, left, right_label, right, explanation,
          interaction=None, expected=None):
    return {'title': title, 'question': question, 'explanation': explanation,
            'interaction': interaction or {'type': 'read'}, 'expected_answer': expected or {},
            'feedback': {'answer': explanation},
            'derivation': _derivation(title, left_label, left, right_label, right)}


def _image_choices(answer, domain):
    candidates = []
    if isinstance(answer, sp.Interval):
        candidates += [sp.Interval(answer.start, answer.end, left_open=not answer.left_open,
                                   right_open=answer.right_open),
                       sp.Interval(answer.start, answer.end, left_open=answer.left_open,
                                   right_open=not answer.right_open)]
        if answer.start.is_finite:
            candidates += [sp.FiniteSet(answer.start), sp.Interval(answer.start - 1, answer.end)]
        if answer.end.is_finite:
            candidates += [sp.FiniteSet(answer.end)]
    else:
        point = next(iter(answer))
        candidates += [sp.Interval(point, sp.oo), sp.S.Reals]
    candidates += [domain, sp.S.EmptySet, sp.S.Reals]
    choices = [answer]
    for candidate in candidates:
        if candidate not in choices:
            choices.append(candidate)
        if len(choices) == 3:
            break
    return _choice(f'${_set_latex(answer)}$', [f'${_set_latex(v)}$' for v in choices[1:]])


def _graph(values):
    expression, variable, domain = (values[key] for key in ('function', 'variable', 'domain'))
    if not isinstance(domain, sp.Interval):
        return None
    drawn = drawing.family(expression, variable)
    marks = drawing.drawable(drawn, variable, drawing.domain_points(domain))
    vertex = drawn['kind'] == 'quadratic'
    # Keep the reference curve in frame, but only mark an attainable vertex.
    bounds, ticks = drawing.function_frame(drawn, variable, domain, marks=marks, show_vertex=vertex)
    return drawing.function_graph(
        drawn, variable, domain, bounds=bounds, x_ticks=ticks, marks=marks,
        show_vertex=vertex and drawn['vertex'][0] in domain,
        title=f'{values["description"]["function_name"]} 在 {drawing.plain(domain)} 上的图像',
        description=drawing.endpoint_story(drawn, variable, domain),
        caption='深色曲线表示本题范围，浅色曲线仅作参考；实心点可取，空心端点不取')


def phase_view(values):
    phase, desc = values['phase'], values['description']
    name, x, f, domain = desc['function_name'], values['variable'], values['function'], values['domain']
    call = f'{name}({latex(x)})'
    definition = f'{call}={desc["expression_latex"]}'
    input_math = f'{latex(x)}\\in{_set_latex(domain)}'
    if phase == 'domain':
        return _card('确定定义域', '先确认本次求值域使用的输入范围。', '原函数', definition,
                     '定义域', input_math, _math(input_math))
    if phase == 'square':
        square = values['square']
        interaction, expected = _choice(f'${call}={latex(square)}$',
                                        [f'${call}={latex(square + 1)}$', f'${call}={latex(square - 1)}$'])
        return _card('配方', '把函数式写成顶点式。', '原函数', definition,
                     '顶点式', f'{call}={latex(square)}', _math(f'{definition}={latex(square)}'),
                     interaction, expected)
    if phase == 'position':
        vertex, height, coefficient = values['vertex'], values['value'], values['coefficient']
        if isinstance(domain, sp.FiniteSet):
            relation = '顶点在定义域中' if vertex in domain else '顶点不在定义域中'
            alternatives = ['顶点不在定义域中' if vertex in domain else '顶点在定义域中']
        else:
            location = ('inside' if vertex in domain else 'left' if vertex <= domain.start else 'right')
            labels = {'inside': '顶点在定义域中，可以取到顶点值',
                      'left': '顶点在区间左侧或左侧开端点处',
                      'right': '顶点在区间右侧或右侧开端点处'}
            relation, alternatives = labels[location], [label for key, label in labels.items() if key != location]
        interaction, expected = _choice(relation, alternatives)
        opening = '向上' if coefficient > 0 else '向下'
        return _card('判断顶点位置', f'抛物线开口{opening}。结合定义域，顶点能否取到？',
                     '输入范围与顶点', _lines([input_math, rf'P\left({latex(vertex)},{latex(height)}\right)']),
                     '顶点位置', rf'{latex(vertex)}' + (r'\in' if vertex in domain else r'\notin') + _set_latex(domain),
                     _math(rf'{latex(vertex)}' + (r'\in' if vertex in domain else r'\notin') + _set_latex(domain)),
                     interaction, expected)
    bounds = values['range']
    low, high, image = bounds['inf'], bounds['sup'], bounds['set']
    rows = list(dict.fromkeys((row['point'], row['value'], row['attained'])
                             for row in [*values['endpoint_values'], *values['critical_points']]))
    equations = []
    for point, value, attained in rows:
        if point.is_finite and attained:
            equations.append(rf'{name}({latex(point)})={latex(value)}')
        else:
            direction = '+' if isinstance(domain, sp.Interval) and point == domain.start else '-'
            approach = latex(point) + ('^' + direction if point.is_finite else '')
            equations.append(rf'\lim_{{{latex(x)}\to{approach}}}{call}={latex(value)}')
    if not equations:
        equations = [f'{call}={latex(f)}', input_math]
    if phase == 'values':
        if low == high:
            return _card('确定函数值', '在这个非空定义域内，函数值保持不变。' if not f.has(x)
                         else '定义域只有一个输入，计算它对应的函数值。',
                         '输入范围', input_math, '函数值', _lines(equations), _math(*equations))
        def labels(lower, upper):
            low_label = '最小值' if bounds['inf_attained'] else '下界（取不到）'
            high_label = '最大值' if bounds['sup_attained'] else '上界（取不到）'
            lower_text = f'{low_label}：${latex(lower)}$' if lower.is_finite else '向下无界'
            upper_text = f'{high_label}：${latex(upper)}$' if upper.is_finite else '向上无界'
            return f'{lower_text}；{upper_text}'

        text = labels(low, high)
        alternatives = [labels(low + 1 if low.is_finite else high - 1 if high.is_finite else sp.S.Zero, high),
                        labels(low, high + 1 if high.is_finite else low + 1 if low.is_finite else sp.S.Zero)]
        interaction, expected = _choice(text, alternatives)
        question = ('比较区间端点的值或极限，以及区间内的顶点值。' if sp.degree(f, x) == 2 else
                    '根据函数的增减情况，比较区间端点的值或极限。')
        return _card('比较函数值', question,
                     '输入范围', input_math, '端点与顶点', _lines(equations), _math(*equations), interaction, expected)
    interaction, expected = _image_choices(image, domain)
    return _card('写出值域', '结合连续的图像和边界能否取到，值域是什么？' if isinstance(domain, sp.Interval)
                 else '由这个输入对应的函数值，写出值域。',
                 '函数值的边界', _lines(equations), '值域', _set_latex(image),
                 _math(rf'{call}\in{_set_latex(image)}'), interaction, expected)


def presentation(values):
    view = phase_view(values)
    left, right = view['derivation']['items']
    return {'range_title': view['title'], 'range_explanation': view['explanation'],
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_range(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed['values'])
    view = phase_view(values)
    board = deepcopy(view['derivation'])
    if view['interaction']['type'] == 'read':
        board = {'caption': view['title'], 'lines': [f'${item["math"]}$' for item in board['items']]}
    else:
        board['items'][1]['math'] = None
    interaction = deepcopy(view['interaction'])
    if interaction['type'] == 'choice':
        interaction['options'].sort(key=lambda option: sha256(
            f'{interaction_id}:{option["value"]}'.encode()).digest())
    part = {'id': interaction_id + '#1', 'title': view['title'], 'question': view['question'],
            'interaction': interaction, 'expected_answer': view['expected_answer'],
            'feedback': view['feedback'], 'submit_label': '继续' if interaction['type'] == 'read' else '确认判断',
            'stem_board': board, 'completion_board': deepcopy(view['derivation'])}
    diagnostics = []
    if values['phase'] in ('position', 'values', 'image'):
        try:
            graph = _graph(values)
            if graph:
                part['graph'] = graph
                part['completion_graph'] = deepcopy(graph)
            if values['phase'] == 'image':
                line = drawing.number_lines([values['range']['set']], sp.Symbol('y'), title='值域')[0]
                if graph:
                    part.pop('completion_graph', None)
                    part['completion_graphs'] = [graph, line]
                else:
                    part['completion_graph'] = line
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
    return {'parts': [part], 'diagnostics': diagnostics}
