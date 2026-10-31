"""Step-local teaching for linear fractional remainders and reciprocal-sum curves."""

import sympy as sp

from .abstract_domain_presentation import _set_latex as sets
from .evaluation_presentation import _choice, _lines, _math
from .math_values import latex


def _reciprocal_definition(call, shift, scale, q):
    if scale == 0:
        return rf'{call}={latex(shift)}'
    sign = '-' if scale < 0 else '+' if shift != 0 else ''
    constant = latex(shift) if shift != 0 else ''
    return rf'{call}={constant}{sign}\frac{{{latex(abs(scale))}}}{{{q}}}'


def current_definition(values):
    """Show the form already established at this step, on its valid branch."""
    from .range_presentation import _source_definition

    desc, x, phase = values['description'], values['variable'], values['phase']
    if phase == 'fraction_separate':
        return _source_definition(desc, x)
    m = desc['fraction_mapping']
    call = rf'{desc["function_name"]}({latex(x)})'
    if not m.get('linear'):
        if phase in ('fraction_reciprocal', 'fraction_return'):
            return _reciprocal_definition(call, m['shift'], m['scale'], rf'Q({latex(x)})')
        separated = sp.Add(m['shift'], sp.Mul(m['scale'], sp.Pow(m['function'], -1, evaluate=False),
                                            evaluate=False), evaluate=False)
        return rf'{call}={latex(separated)}'
    numerator, denominator = m['remainder'], m['denominator']
    restriction = ''
    if phase in ('fraction_divide', 'fraction_denominator', 'fraction_reciprocal', 'fraction_nonzero'):
        t, inverse = m['variable'], m['variable'] - m['offset']
        call = rf'{desc["function_name"]}({latex(inverse)})'
        restriction = rf',\quad {latex(t)}\ne0'
        if phase in ('fraction_reciprocal', 'fraction_nonzero'):
            return _reciprocal_definition(call, m['shift'], m['scale'], rf'Q({latex(t)})') + restriction
        if phase == 'fraction_divide':
            numerator, denominator = m['scale'] * t, sp.expand(denominator.subs(x, inverse))
        else:
            numerator, denominator = m['scale'], m['function'] + m['denominator_shift']
    return rf'{call}={latex(m["shift"])}+\frac{{{latex(numerator)}}}{{{latex(denominator)}}}{restriction}'


def phase_view(values):
    from .range_presentation import _card, _image_choices, _source_definition

    desc, x, domain = values['description'], values['variable'], values['domain']
    m, phase = desc['fraction_mapping'], values['phase']
    t, core, shift, scale = (m[key] for key in ('variable', 'function', 'shift', 'scale'))
    name = desc['function_name']
    call = rf'{name}({latex(x)})'
    separated = rf'{latex(shift)}+\frac{{{latex(m["remainder"])}}}{{{latex(m["denominator"])}}}'
    intermediate = core + m['denominator_shift']
    inner = rf'h({latex(t)})'
    inner_definition = rf'{inner}={latex(core)}'
    q = rf'{latex(intermediate)}'
    q_call = rf'Q({latex(t)})'
    if phase == 'fraction_separate':
        correct = rf'{call}={separated}'
        interaction, expected = _choice(f'${correct}$', [rf'${call}={latex(shift+1)}+\frac{{{latex(m["remainder"])}}}{{{latex(m["denominator"])}}}$'])
        return _card('分离常数', '分离出常数项，得到什么表达式？',
                     '原函数及定义域', _lines([_source_definition(desc, x), rf'{latex(x)}\in{sets(domain)}']),
                     '分离结果', correct, _math(rf'{_source_definition(desc,x)}={separated}'), interaction, expected)
    if phase == 'fraction_zero':
        zero = rf'{latex(x)}={latex(m["zero_input"])}'
        zero_condition = (zero if m['remainder'] == x else
                          rf'{latex(m["remainder"])}=0\Longleftrightarrow {zero}')
        answer = (rf'${zero}$ 属于定义域，单独计算 ${name}({latex(m["zero_input"])})={latex(shift)}$'
                  if m['zero_allowed'] else rf'${zero}$ 不属于本题定义域，无需补入函数值')
        wrong = (rf'${zero}$ 使分子为零，所以没有意义' if m['zero_allowed'] else
                 rf'${zero}$ 虽不在定义域内，仍把输出 ${latex(shift)}$ 补入')
        interaction, expected = _choice(answer, [wrong])
        conclusion = (rf'{name}({latex(m["zero_input"])})={latex(shift)}' if m['zero_allowed'] else
                      rf'{latex(m["zero_input"])}\notin{sets(domain)}')
        divisor = latex(x + m['offset'])
        reciprocal_form = '倒数形式' if scale == 1 else '常数乘倒数的形式'
        question = (rf'分离常数后，${call}={separated}$。'
                    f'为把余项写成{reciprocal_form}，接下来将余项的分子、分母同除以 ${divisor}$。'
                    rf'同除的式子不能为零；当 ${zero}$ 时，对应输入应如何处理？')
        return _card('检查同除的条件', question,
                     '分子零点与原定义域', _lines([zero_condition, rf'{latex(x)}\in{sets(domain)}']),
                     '零点分支', conclusion, _math(conclusion), interaction, expected)
    if phase == 'fraction_substitution':
        inverse = t-m['offset']
        polynomial_q = sp.expand(m['denominator'].subs(x, inverse))
        transformed = sp.Add(shift, sp.Mul(scale*t, sp.Pow(polynomial_q,-1,evaluate=False),evaluate=False),evaluate=False)
        answer = rf'{name}({latex(inverse)})={latex(transformed)},\quad {latex(t)}\in{sets(m["transformed_domain"])}'
        interaction, expected = _choice(f'${answer}$', [rf'${name}({latex(inverse)})={latex(transformed+1)},\quad {latex(t)}\in{sets(m["transformed_domain"])}$'])
        return _card('换元整理一次分子', '将一次分子写成新变量的常数倍，函数与输入范围怎样改写？',
                     '分离结果与换元', _lines([rf'{call}={separated}', rf'{latex(t)}={latex(x+m["offset"])},\quad {latex(x)}\in{sets(domain)}']),
                     '换元后的函数与输入范围', answer, _math(answer), interaction, expected)
    if phase == 'fraction_divide':
        current_call = rf'{name}({latex(t-m["offset"])})'
        quotient = rf'\frac{{{latex(scale)}}}{{{q}}}'
        answer = rf'{current_call}={latex(shift)}+{quotient}'
        interaction, expected = _choice(f'${answer}$', [rf'${current_call}={latex(shift+1)}+{quotient}$'])
        return _card('分子分母同除', rf'在 ${latex(t)}\ne0$ 的分支，分子分母同除以 ${latex(t)}$ 后得到什么？',
                     '待改写的函数与当前输入', _lines([current_definition(values), rf'{latex(t)}\in{sets(m["domain"])}']),
                     '常数与倒数项', answer, _math(answer), interaction, expected)
    if phase == 'fraction_hook':
        row = values.get('hook_piece')
        region = row['domain'] if row else m['domain']
        image = row['range']['set'] if row else m['core_image']
        interaction, expected = _image_choices(image, region)
        hook = not core.is_polynomial(t) and sp.expand(core).coeff(t) != 0
        title = ('对勾函数' if hook else '中间函数') + rf'：${latex(t)}\in{sets(region)}$'
        known = [inner_definition, rf'{latex(t)}\in{sets(region)}']
        calculations = []
        if row:
            for point in row.get('endpoint_values', []):
                operator = '=' if point['attained'] else r'\longrightarrow'
                calculations.append(rf'{latex(t)}{operator}{latex(point["point"])}:\quad {inner}{operator}{latex(point["value"])}')
            turn = row.get('turning_point')
            if turn:
                known.append(rf'{latex(t)}_0={latex(turn["point"])}')
                calculations.append(rf'{latex(turn["point"])}' + (r'\in' if turn['point'] in region else r'\notin') + sets(region))
                if turn['point'] in region:
                    calculations.append(rf'h({latex(turn["point"])})={latex(turn["value"])}')
        return _card(title, rf'对 ${inner_definition}$，在 ${latex(t)}\in{sets(region)}$ 上，结合图像判断函数值的范围。',
                     '当前中间函数与输入范围', _lines(known), '本分支的范围', rf'{inner}\in{sets(image)}',
                     _math(*calculations, rf'{inner}\in{sets(image)}'), interaction, expected)
    if phase == 'fraction_denominator':
        image = m['denominator_image']
        interaction, expected = _image_choices(image, m['core_image'])
        return _card('求分母的范围', '合并各输入分支，再按分母中的常数项平移，得到什么范围？',
                     '中间函数范围与分母', _lines([rf'{inner_definition}\in{sets(m["core_image"])}', rf'{q_call}={inner}+({latex(m["denominator_shift"])})']),
                     '分母的完整范围', rf'{q_call}\in{sets(image)}', _math(rf'{q_call}={q}\in{sets(image)}'), interaction, expected)
    if phase == 'fraction_reciprocal':
        image = m['reciprocal_image']
        interaction, expected = _image_choices(image, m['denominator_image'])
        from .capabilities.reciprocal import reciprocal_of_range
        from .function_range import _bounds, components
        rows = [rf'{q_call}\in{sets(part)}\Longrightarrow\frac1{{{q_call}}}\in{sets(reciprocal_of_range(_bounds(part))["outputs"]["range"]["set"])}'
                for part in components(m['denominator_image'])]
        return _card('分段取倒数', '分别对分母的正、负范围取倒数，得到什么范围？',
                     '当前分母与范围', _lines([rf'{q_call}={q}', rf'{q_call}\in{sets(m["denominator_image"])}']),
                     '倒数范围', rf'\frac1{{{q_call}}}\in{sets(image)}', _math(*rows), interaction, expected)
    if phase == 'fraction_nonzero':
        image = m['nonzero_image']
        interaction, expected = _image_choices(image, m['reciprocal_image'])
        return _card('还原非零分支的值域', '根据比例和平移，当前输入分支的函数值范围是什么？',
                     '倒数范围与原函数', _lines([rf'\frac1{{{q_call}}}\in{sets(m["reciprocal_image"])}', current_definition(values)]),
                     '当前分支的值域', sets(image), _math(rf'{latex(t)}\ne0:\quad {call}\in{sets(image)}'), interaction, expected)
    image = m['image']
    interaction, expected = _image_choices(image, m['nonzero_image'])
    return _card('合并原函数值域', '合并各个合法输入分支，原函数的完整值域是什么？',
                 '非零分支与零点分支', _lines([rf'{latex(t)}\ne0:\ {sets(m["nonzero_image"])}',
                                                   rf'{latex(t)}=0:\ {sets(m["zero_image"])}']),
                 '原函数值域', sets(image),
                 _math(rf'{sets(m["nonzero_image"])}\cup{sets(m["zero_image"])}={sets(image)}'), interaction, expected)


def hook_graph(values):
    from . import interaction_graphs as drawing

    m, row = values['description']['fraction_mapping'], values['hook_piece']
    t, domain = m['variable'], row['domain']
    if not isinstance(domain, sp.Interval):
        return drawing.number_lines([domain], t, title='当前输入')[0]
    drawn = drawing.family(m['function'], t)
    points = [*drawing.domain_points(domain), *((r['point'], True) for r in row.get('critical_points', []))]
    marks = drawing.drawable(drawn, t, list(dict.fromkeys(points)))
    bounds, ticks = drawing.function_frame(drawn, t, domain, marks=marks)
    return drawing.function_graph(drawn, t, domain, bounds=bounds, x_ticks=ticks, marks=marks,
                                  title=f'当前输入范围：{drawing.plain(domain)}',
                                  description='深色曲线表示当前输入范围，实心点可取，空心端点不取',
                                  caption='结合当前输入范围，判断端点与转折点能否取到')
