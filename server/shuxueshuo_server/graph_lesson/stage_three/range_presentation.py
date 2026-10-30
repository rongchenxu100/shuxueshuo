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


def _source_definition(description, variable):
    """Keep an input relation as f(ax+b), rather than relabelling its RHS f(x)."""
    from ..range_syntax import range_expression

    argument = description.get('relation_input_ast')
    input_latex = latex(range_expression(argument, variable)) if argument else latex(variable)
    return rf'{description["function_name"]}({input_latex})={description["expression_latex"]}'


def _function_context(view, definition, label='当前函数'):
    # A formula already shown as a premise need not be repeated. Never take it
    # from the answer side: the current step's output is still hidden there.
    if definition not in view['question'] and definition not in view['derivation']['items'][0]['math']:
        view['question'] = f'{label} ${definition}$。{view["question"]}'
    return view


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
    elif isinstance(answer, sp.FiniteSet):
        point = next(iter(answer))
        candidates += [sp.Interval(point, sp.oo), sp.S.Reals]
    elif isinstance(answer, sp.Union):
        candidates += [*answer.args, answer.complement(sp.S.Reals)]
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
        title=f'{"被开方数" if values["description"].get("radical") else values["description"]["function_name"]} 在 {drawing.plain(domain)} 上的图像',
        description=drawing.endpoint_story(drawn, variable, domain),
        caption='深色曲线表示本题范围，浅色曲线仅作参考；实心点可取，空心端点不取')


def phase_view(values):
    phase, desc = values['phase'], values['description']
    if phase.startswith('substitution_'):
        view = substitution_view(values)
        if phase == 'substitution_borrow':
            return view  # The rewritten function is already the left-hand premise.
        return _function_context(view, _source_definition(desc, values['variable']), '题设函数关系')
    view = _range_view(values)
    definition = _source_definition(desc, values['variable'])
    label = '当前函数'
    if desc.get('radical') and phase not in ('root', 'affine', 'domain'):
        definition = rf'P({latex(values["variable"])})={latex(values["function"])}'
        label = '当前被开方数'
    return _function_context(view, definition, label)


def _range_view(values):
    phase, desc = values['phase'], values['description']
    name, x, f, domain = desc['function_name'], values['variable'], values['function'], values['domain']
    original_call = f'{name}({latex(x)})'
    original_definition = f'{original_call}={desc["expression_latex"]}'
    if desc.get('radical'):
        name = 'P'
    call = f'{name}({latex(x)})'
    definition = f'{call}={latex(f)}' if desc.get('radical') else original_definition
    input_math = f'{latex(x)}\\in{_set_latex(domain)}'
    if phase == 'domain':
        return _card('确定定义域', '先确认本次求值域使用的输入范围。', '原函数', definition,
                     '定义域', input_math, _math(input_math))
    if phase == 'square':
        square = values['square']
        interaction, expected = _choice(f'${call}={latex(square)}$',
                                        [f'${call}={latex(square + 1)}$', f'${call}={latex(square - 1)}$'])
        return _card('配方', '把被开方数写成顶点式。' if desc.get('radical') else '把函数式写成顶点式。',
                     '被开方数' if desc.get('radical') else '原函数', definition,
                     '顶点式', f'{call}={latex(square)}', _math(f'{definition}={latex(square)}'),
                     interaction, expected)
    if phase == 'position':
        vertex, height, coefficient = values['vertex'], values['value'], values['coefficient']
        if isinstance(domain, (sp.FiniteSet, sp.Union)):
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
    if phase in ('root', 'affine'):
        from .function_range import polynomial_image, transform_function_range
        inner_image = polynomial_image(f, x, domain)['outputs']['feasible_set']
        transformed = transform_function_range(desc, inner_image)['outputs']
        rescale = (desc['scale'], desc['shift']) != ('1', '0')
        source = inner_image if phase == 'root' else transformed['root_range']['set']
        source_formula = call if phase == 'root' else rf'\sqrt{{{call}}}'
        output_formula = rf'\sqrt{{{call}}}' if phase == 'root' and rescale else original_call
        title = '开平方，确定基本范围' if phase == 'root' and rescale else '写出原函数值域'
        if phase == 'affine':
            title = '比例和平移，写出值域'
        interaction, expected = _image_choices(image, source)
        explanation = _math(rf'{source_formula}\in{_set_latex(source)}',
                            rf'{output_formula}\in{_set_latex(image)}')
        question = ('被开方数的范围已确定。开平方后能取到哪些值？' if phase == 'root' else
                    f'回到 ${original_definition}$，比例和平移后的值域是什么？')
        return _card(title, question, '被开方数范围' if phase == 'root' else '平方根的范围',
                     rf'{source_formula}\in{_set_latex(source)}',
                     '平方根的范围' if phase == 'root' and rescale else '原函数值域',
                     _set_latex(image), explanation, interaction, expected)
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
    title = '确定被开方数范围' if desc.get('radical') else '写出值域'
    question = ('各个合法区间上的范围取并集，得到哪些值？' if isinstance(domain, sp.Union) else
                '结合图像和边界能否取到，确定全部取值。')
    return _card(title, question,
                 '函数值的边界', _lines(equations), '被开方数范围' if desc.get('radical') else '值域', _set_latex(image),
                 _math(rf'{call}\in{_set_latex(image)}'), interaction, expected)


def substitution_view(values):
    desc, phase = values['description'], values['phase']
    mapping = desc['mapping']
    x, t = mapping['original_variable'], mapping['variable']
    forward, polynomial = mapping['forward'], mapping['function']
    domain, new_domain = mapping['original_domain'], mapping['domain']
    xt, tt = latex(x), latex(t)
    definition = rf'{tt}={latex(forward)}'
    old_range = rf'{xt}\in{_set_latex(domain)}'
    new_range = rf'{tt}\in{_set_latex(new_domain)}'
    name = desc['function_name'] if mapping['kind'] == 'affine' else 'h'
    call = rf'{name}({tt})'
    rewritten = rf'{call}={latex(polynomial)}'
    original = _source_definition(desc, x)
    inverses = [rf'{xt}={latex(v)}' for v in mapping['preimages']]
    if mapping['kind'] == 'abs':
        inverses = [r'\quad\text{或}\quad '.join(inverses)]
    if phase == 'substitution_define':
        if mapping['kind'] == 'constant':
            return _card('化简常量后改写', '这一部分为常量，先化简，再沿用原输入范围。',
                         '原函数', original, '改写后的函数', rewritten,
                         _math(definition, rewritten), {'type': 'read'})
        from ..range_syntax import range_expression
        argument = range_expression(desc['substitution']['argument_ast'], x)
        kind = mapping['kind']
        target = {'sqrt': '根式', 'abs': '绝对值', 'affine': '函数的完整输入'}[kind]
        alternative = argument if kind in ('sqrt', 'abs') else x
        # Ask for this route's exact substitution, not the only possible method.
        # A missing root/sign is wrong only if it changes some legal input.
        if kind == 'sqrt':
            distinct = new_domain.is_subset(sp.FiniteSet(0, 1)) is False
        elif kind == 'abs':
            distinct = any(row['argument_domain'].inf < 0 for row in mapping['coverage'])
        else:
            distinct = sp.simplify(forward - alternative) != 0  # affine relation on R
        if distinct:
            interaction, expected = _choice(f'${definition}$', [f'${tt}={latex(alternative)}$'])
            question = f'将{target} ${latex(forward)}$ 整体设为新变量 ${tt}$，应怎样写？'
        else:
            interaction, expected = {'type': 'read'}, {}
            question = f'本路线令 ${definition}$，继续确定新变量的范围。'
        return _card('设新变量', question,
                     '原函数关系' if mapping['kind'] == 'affine' else '原函数', original,
                     '新变量', definition, _math(definition), interaction, expected)
    if phase == 'substitution_domain':
        interaction, expected = _image_choices(new_domain, domain)
        explanation = _math(old_range, definition, new_range)
        return _card('确定新变量范围', '在原输入范围内，新变量能取遍哪个集合？',
                     '原输入与换元关系', _lines([old_range, definition]),
                     '新变量范围', new_range, explanation, interaction, expected)
    if phase == 'substitution_rewrite':
        interaction, expected = _choice(f'${rewritten}$',
                                        [f'${call}={latex(polynomial+1)}$', f'${call}={latex(polynomial-1)}$'])
        relation = _lines([definition, *inverses])
        return _card('改写为新变量的函数', '用新变量表示整个函数，结果是什么？',
                     '换元与回代', relation, '新函数', rewritten,
                     _math(*inverses, rewritten, new_range), interaction, expected)
    if phase == 'substitution_borrow':
        return _card('求新函数的值域', '新变量范围已确定，接下来结合顶点和区间边界求全部输出。',
                     '新函数', rewritten, '输入范围', new_range,
                     _math(rewritten, new_range))
    image = values['range']['set']
    return _card('回到原函数值域', '新变量取遍上述范围，两种表示产生相同的全部函数值。',
                 '新函数的完整范围', rf'{call}\in{_set_latex(image)}',
                 '原函数值域', _set_latex(image), _math(definition, new_range,
                  rf'{desc["function_name"]}({xt})\in{_set_latex(image)}'))


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
    if values['phase'] in ('position', 'values', 'image', 'root', 'affine'):
        try:
            # Each disconnected input component gets its own restricted curve.
            # Never connect across a forbidden input gap.
            domains = values['domain'].args if isinstance(values['domain'], sp.Union) else [values['domain']]
            graphs = [] if values['phase'] in ('root', 'affine') else [
                graph for domain in domains if (graph := _graph({**values, 'domain': domain}))]
            if graphs:
                part['completion_graphs'] = deepcopy(graphs)
                if len(graphs) == 1:
                    part['graph'] = graphs[0]
                    part['completion_graph'] = part.pop('completion_graphs')[0]
                else:
                    part['graph'] = drawing.number_lines([values['domain']], values['variable'], title='定义域的各个分量')[0]
            if values['phase'] in ('image', 'root', 'affine'):
                label = '被开方数范围' if values['phase'] == 'image' and values['description'].get('radical') else '输出范围'
                lines = drawing.number_lines([values['range']['set']], sp.Symbol('y'), title=label)
                part.pop('completion_graph', None)
                part['completion_graphs'] = [*graphs, *lines]
                if len(part['completion_graphs']) == 1:
                    part['completion_graph'] = part.pop('completion_graphs')[0]
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
    return {'parts': [part], 'diagnostics': diagnostics}


def domain_prerequisite(description):
    from ..range_syntax import range_domain
    from .function_range import inputs
    function, variable, domain = inputs(description)
    domain_math = f'${latex(variable)}\\in{_set_latex(domain)}$'
    item = {'id': 'D3-domain', 'title': '确定定义域',
            'question': f'先确定本次求值域使用的输入范围：{domain_math}',
            'summary': domain_math, 'interaction': {'type': 'read'},
            'expected_answer': {}, 'submit_label': '在这个范围内选择方法',
            'source_refs': [description['source_ref'], description['target_ref']],
            'effects': {'nodes': [], 'edges': [], 'calls': [], 'results': [], 'log': '已确定本题的有效输入范围。'}}
    substitution = description.get('substitution', {})
    if substitution.get('kind') == 'affine':
        from ..range_syntax import range_expression
        argument = range_expression(substitution['argument_ast'], variable)
        item['question'] = '题设关系对全体实数成立，非恒定的一次输入能取遍实数集。'
        item['stem_board'] = _derivation('确定定义域', '题设中的输入',
                                         _lines([rf'{latex(variable)}\in\mathbb{{R}}',
                                                 rf'{latex(argument)}\in\mathbb{{R}}']),
                                         '原函数定义域', rf'D_{{{description["function_name"]}}}=\mathbb{{R}}')
        item['completion_board'] = deepcopy(item['stem_board'])
    if description.get('radical') or substitution.get('atom_kind') == 'sqrt':
        from ..range_syntax import range_expression
        radicand = (range_expression(substitution['argument_ast'], variable) if substitution else function)
        conditions = [rf'{latex(radicand)}\ge0']
        for field in ('declared_domain', 'input_domain'):
            if description[field + '_source_ref']:
                item['source_refs'].append(description[field + '_source_ref'])
                conditions.append(rf'{latex(variable)}\in{_set_latex(range_domain(description[field + "_ast"]))}')
        for row in description['restriction_facts']:
            item['source_refs'].append(row['source_ref'])
            conditions.append(rf'{latex(variable)}\in{_set_latex(range_domain(row["domain_ast"]))}')
        item['question'] = '被开方数必须非负。结合题给的输入限制，定义域是什么？'
        item['interaction'], item['expected_answer'] = _image_choices(domain, sp.S.Reals)
        item['completion_board'] = _derivation('确定定义域', '原式有意义的条件', _lines(conditions),
                                               '定义域', rf'{latex(variable)}\in{_set_latex(domain)}')
        item['stem_board'] = deepcopy(item['completion_board'])
        item['stem_board']['items'][1]['math'] = None
        item['feedback'] = {'answer': _math(*conditions, rf'{latex(variable)}\in{_set_latex(domain)}')}
    item['question'] = f'题设函数关系 ${_source_definition(description, variable)}$。{item["question"]}'
    return item
