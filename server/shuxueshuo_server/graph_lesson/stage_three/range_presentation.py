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
    if phase.startswith('translation_'):
        from .translation_presentation import phase_view as translation_view
        return translation_view(values)
    if phase.startswith('finite_'):
        from .finite_range import phase_view as finite_view
        return _function_context(finite_view(values), _source_definition(desc, values['variable']))
    if phase.startswith('abstract_'):
        from .abstract_range_presentation import phase_view as abstract_view
        return abstract_view(values)
    if phase.startswith('equation_'):
        return equation_view(values)
    if phase.startswith('fraction_'):
        if phase in ('fraction_zero', 'fraction_hook'):
            return fraction_view(values)
        from .fraction_range_presentation import current_definition
        return _function_context(fraction_view(values), current_definition(values))
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


def equation_view(values):
    desc, x = values['description'], values['variable']
    mapping = desc['equation_mapping']
    y, special = mapping['output_variable'], mapping['special_value']
    grouped = sp.Add(sp.Mul(mapping['a'], x**2, evaluate=False),
                     sp.Mul(mapping['b'], x, evaluate=False), mapping['c'], evaluate=False)
    eq = rf'{latex(grouped)}=0'
    equation_context = rf'当前关于 ${latex(x)}$ 的方程为 ${eq}$。'
    if values['phase'] == 'equation_rearrange':
        answer = rf'{eq}\text{{ 有实根}}'
        interaction, expected = _choice(f'${answer}$', [rf'${eq}\text{{ 对一切实数恒成立}}$'])
        return _card('转为输入方程', f'输出 ${latex(y)}$ 能取到，关于 ${latex(x)}$ 的方程需要满足什么条件？',
                     '原函数及输入范围', _lines([_source_definition(desc, x), rf'{latex(x)}\in\mathbb R']),
                     '输出可达的条件', answer,
                     _math(rf'{latex(y)}={latex(values["function"])}\Longleftrightarrow {eq}',
                           rf'\exists {latex(x)}\in\mathbb R:\ {eq}'), interaction, expected)
    if values['phase'] == 'equation_degenerate':
        reduced = sp.expand(mapping['degenerate_b']*x+mapping['degenerate_c'])
        kind = mapping['degenerate_kind']
        answer = (rf'{latex(x)}={latex(mapping["degenerate_witness"])}' if kind == 'linear'
                  else r'\text{任意实数均为解}' if kind == 'identity' else r'\text{无解}')
        output = rf'{latex(y)}={latex(special)}'
        verdict = '不能取到' if kind == 'inconsistent' else '可以取到'
        conclusion = rf'{output}\text{{{verdict}}}'
        no_root = rf'方程无解，${output}$ 不能取到'
        all_roots = rf'任意实数均为解，${output}$ 可以取到'
        choice = (rf'${answer}$ 是方程的解，${output}$ 可以取到' if kind == 'linear'
                  else all_roots if kind == 'identity' else no_root)
        interaction, expected = _choice(choice, [no_root, all_roots])
        return _card('检查二次项系数为零的情况',
                     equation_context + rf'当 ${output}$ 时，方程有实根吗？这个输出值能否取到？',
                     '退化后的方程', _lines([output, rf'{latex(reduced)}=0']),
                     '输出值能否取到', _lines([answer, conclusion]),
                     _math(rf'{output}:\ {latex(reduced)}=0', answer, conclusion), interaction, expected)
    if values['phase'] == 'equation_discriminant':
        image = mapping['quadratic_image']
        interaction, expected = _image_choices(image, sp.S.Reals)
        delta = mapping['discriminant']
        view = _card('用判别式求二次分支',
                     equation_context + rf'当 ${latex(y)}\ne{latex(special)}$ 时，哪些输出值使方程有实根？',
                     '二次方程及实根条件', _lines([eq, rf'\Delta={latex(delta)}\ge0']),
                     '本分支输出范围', rf'{latex(y)}\in{_set_latex(image)}',
                     _math(rf'\Delta={latex(delta)}\ge0\Longleftrightarrow {latex(y)}\in{_set_latex(mapping["discriminant_image"])}',
                           rf'{latex(y)}\ne{latex(special)}\Longrightarrow {latex(y)}\in{_set_latex(image)}'),
                     interaction, expected)
        graph_values = {**values, 'function': delta, 'variable': y, 'domain': sp.S.Reals,
                        'description': {**desc, 'function_name': r'\Delta'}}
        graph = _graph(graph_values)
        if graph: view['graph'] = graph
        return view
    image = values['range']['set']
    interaction, expected = _image_choices(image, sp.S.Reals)
    left = _lines([rf'{latex(y)}={latex(special)}:\ {_set_latex(mapping["degenerate_image"])}',
                   rf'{latex(y)}\ne{latex(special)}:\ {_set_latex(mapping["quadratic_image"])}'])
    return _card('合并得到原函数值域', equation_context + '合并两种次数下能取得的输出，原函数的值域是什么？',
                 '两个分支的输出范围', left, '原函数值域', _set_latex(image),
                 _math(rf'{_set_latex(mapping["degenerate_image"])}\cup{_set_latex(mapping["quadratic_image"])}={_set_latex(image)}'),
                 interaction, expected)


def fraction_view(values):
    from .function_range import _bounds, monotone_cover
    desc, x, domain = values['description'], values['variable'], values['domain']
    mapping = desc['fraction_mapping']
    if mapping.get('linear'):
        from .fraction_range_presentation import phase_view as linear_fraction_view
        return linear_fraction_view(values)
    denominator, shift, scale = (mapping[key] for key in ('function', 'shift', 'scale'))
    call = rf'{desc["function_name"]}({latex(x)})'
    q = rf'Q({latex(x)})'
    separated = sp.Add(shift, sp.Mul(scale, sp.Pow(denominator, -1, evaluate=False), evaluate=False), evaluate=False)
    if values['phase'] == 'fraction_separate':
        answer = rf'{call}={latex(separated)}'
        interaction, expected = _choice(f'${answer}$', [rf'${call}={latex(separated+1)}$', rf'${call}={latex(separated-1)}$'])
        return _card('分离分式', '将原式写成常数与倒数项之和，结果是什么？',
                     '原函数及定义域', _lines([_source_definition(desc, x), rf'{latex(x)}\in{_set_latex(domain)}']),
                     '分离结果', answer, _math(rf'{_source_definition(desc,x)}={latex(separated)}'), interaction, expected)
    if values['phase'] == 'fraction_borrow':
        return _card('求分母的范围', '先在原定义域内求分母的完整范围。',
                     '分离后的函数', rf'{call}={latex(separated)}', '本次求值域的函数与输入',
                     _lines([rf'{q}={latex(denominator)}', rf'{latex(x)}\in{_set_latex(domain)}']),
                     _math(rf'{q}={latex(denominator)}', rf'{latex(x)}\in{_set_latex(domain)}'))
    image = values['range']['set']
    denominator_image, _ = monotone_cover(denominator, x, domain)
    if values['phase'] == 'fraction_reciprocal':
        interaction, expected = _image_choices(image, denominator_image)
        rows = []
        from .capabilities.reciprocal import reciprocal_of_range
        from .function_range import components
        for part in components(denominator_image):
            reciprocal = reciprocal_of_range(_bounds(part))['outputs']['range']['set']
            rows.append(rf'{q}\in{_set_latex(part)}\Longrightarrow\frac1{{{q}}}\in{_set_latex(reciprocal)}')
        return _card('分段取倒数', '在零的两侧分别取倒数，端点次序交换。倒数项能取到哪些值？',
                     '分母的范围', rf'{q}\in{_set_latex(denominator_image)}', '倒数的范围',
                     rf'\frac1{{{q}}}\in{_set_latex(image)}', _math(*rows), interaction, expected)
    # The preceding reciprocal card supplies the source range; recompute from
    # verified inputs, never infer it from the final output interval's hull.
    from .capabilities.reciprocal import reciprocal_of_range
    from .function_range import components
    reciprocal = sp.Union(*(reciprocal_of_range(_bounds(part))['outputs']['range']['set']
                            for part in components(denominator_image)))
    interaction, expected = _image_choices(image, reciprocal)
    from .fraction_range_presentation import current_definition
    return _card('还原原函数值域', '根据分离后的表达式，写出原函数的值域。',
                 '倒数范围与原函数', _lines([rf'\frac1{{{q}}}\in{_set_latex(reciprocal)}', current_definition(values)]),
                 '原函数值域', _set_latex(image),
                 _math(rf'\frac1{{{q}}}\in{_set_latex(reciprocal)}', rf'{call}\in{_set_latex(image)}'), interaction, expected)


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
    from .function_range import needs_value_comparison
    if not needs_value_comparison(f, x, domain):
        return _card(title, rf'在给定输入范围内，${call}$ 能取到哪些值？',
                     '当前函数与输入范围', _lines([definition, input_math]),
                     '被开方数范围' if desc.get('radical') else '值域', _set_latex(image),
                     _math(rf'{call}\in{_set_latex(image)}'), interaction, expected)
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
    if values['phase'] == 'fraction_hook':
        compiled = [_compile_range_values({**values, 'hook_piece': row}, interaction_id)
                    for row in values['description']['fraction_mapping']['pieces']]
        parts = [part for entry in compiled for part in entry['parts']]
        for index, part in enumerate(parts):
            part['id'] = f'{interaction_id}#{index+1}'
        return {'parts': parts,
                'diagnostics': [item for entry in compiled for item in entry['diagnostics']]}
    return _compile_range_values(values, interaction_id)


def _compile_range_values(values, interaction_id):
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
    if values['phase'] == 'fraction_hook':
        from .fraction_range_presentation import hook_graph
        try:
            part['graph'] = hook_graph(values)
            part['completion_graph'] = deepcopy(part['graph'])
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
    if values['phase'] in ('translation_coverage', 'translation_union'):
        data = values['description']['translation']
        try:
            if values['phase'] == 'translation_coverage':
                # Stem shows what must be covered; completion also shows the known full segment.
                stem = drawing.number_lines(
                    [data['domain']], values['variable'], title='要求的输入范围')[0]
                part['graph'] = stem
                domains = [data['base']] if data['base'] == data['domain'] else [data['base'], data['domain']]
                titles = (['已知区间'] if data['base'] == data['domain']
                          else ['已知区间', '要求的输入范围'])
                graphs = []
                for domain, title in zip(domains, titles, strict=True):
                    graphs.extend(drawing.number_lines([domain], values['variable'], title=title))
            else:
                # Stem shows the known image only; the union appears after the answer.
                part['graph'] = drawing.number_lines(
                    [data['known_image']], sp.Symbol('y'), title='已知区间上的值域')[0]
                graphs = drawing.number_lines(
                    [data['feasible_set']], sp.Symbol('y'), title='各段值域合起来')
            part['completion_graphs'] = graphs
            if len(graphs) == 1:
                part['completion_graph'] = part.pop('completion_graphs')[0]
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
    if values['phase'] == 'finite_collect':
        try:
            part['completion_graph'] = drawing.number_lines(
                [values['range']['set']], sp.Symbol('y'), title='值域中的离散输出')[0]
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
    if values['phase'] == 'fraction_reciprocal':
        mapping = values['description']['fraction_mapping']
        if mapping.get('linear'):
            denominator_image, variable = mapping['denominator_image'], mapping['variable']
        else:
            from .function_range import monotone_cover
            variable = values['variable']
            denominator_image, _ = monotone_cover(mapping['function'], variable, values['domain'])
        try:
            part['graph'] = drawing.reciprocal_image_graph(denominator_image, source=rf'Q({latex(variable)})')
            part['completion_graph'] = deepcopy(part['graph'])
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
    if values['phase'] in ('fraction_return', 'fraction_nonzero', 'fraction_denominator'):
        mapping = values['description'].get('fraction_mapping', {})
        image = (mapping[{'fraction_return': 'image',
                          'fraction_nonzero': 'nonzero_image', 'fraction_denominator': 'denominator_image'}[values['phase']]]
                 if mapping.get('linear') else values['range']['set'])
        try:
            part['completion_graphs'] = drawing.number_lines([image], sp.Symbol('y'), title=view['title'])
            if len(part['completion_graphs']) == 1:
                part['completion_graph'] = part.pop('completion_graphs')[0]
        except drawing.GraphUnavailable as exc:
            diagnostics.append({'kind': 'graph_unavailable', 'reason': str(exc)})
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
    if description.get('radical') or substitution.get('atom_kind') == 'sqrt' or description.get('rational'):
        from ..range_syntax import range_expression
        radicand = (range_expression(substitution['argument_ast'], variable) if substitution else function)
        conditions = (list(dict.fromkeys(rf'{latex(range_expression(row["ast"], variable))}\ne0'
                                        for row in description['rational']['denominators']))
                      if description.get('rational') else [rf'{latex(radicand)}\ge0'])
        for field in ('declared_domain', 'input_domain'):
            if description[field + '_source_ref']:
                item['source_refs'].append(description[field + '_source_ref'])
                conditions.append(rf'{latex(variable)}\in{_set_latex(range_domain(description[field + "_ast"]))}')
        for row in description['restriction_facts']:
            item['source_refs'].append(row['source_ref'])
            conditions.append(rf'{latex(variable)}\in{_set_latex(range_domain(row["domain_ast"]))}')
        item['question'] = ('原式的每个分母都必须非零，约分前的限制也要保留。定义域是什么？'
                            if description.get('rational') else '被开方数必须非负。结合题给的输入限制，定义域是什么？')
        item['interaction'], item['expected_answer'] = _image_choices(domain, sp.S.Reals)
        item['completion_board'] = _derivation('确定定义域', '原式有意义的条件', _lines(conditions),
                                               '定义域', rf'{latex(variable)}\in{_set_latex(domain)}')
        item['stem_board'] = deepcopy(item['completion_board'])
        item['stem_board']['items'][1]['math'] = None
        item['feedback'] = {'answer': _math(*conditions, rf'{latex(variable)}\in{_set_latex(domain)}')}
    item['question'] = f'题设函数关系 ${_source_definition(description, variable)}$。{item["question"]}'
    return item
