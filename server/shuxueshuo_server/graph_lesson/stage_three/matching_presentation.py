"""Student-facing matching steps and an independent original-relation value."""

import sympy as sp

from ..function_matching import DifferenceSource, matching_source
from .evaluation_presentation import _choice, _lines, _math
from .formula_presentation import _condition, answer_view
from .math_values import latex
from .range_presentation import _card


def phase_view(values):
    desc, result, phase = (values[key] for key in ('description', 'formula_result', 'phase'))
    source = matching_source(desc)
    x, t, f = sp.Symbol(desc['variable'], real=True), result['variable'], desc['function_name']
    g, h = source.expressions(x)
    h = sp.expand(h)
    original = rf'{f}\left({latex(g)}\right)={latex(h)}'
    bracket = rf'\left({latex(g)}\right)'
    rule = rf'{f}({latex(t)})={latex(result["expression"])}'
    if phase == 'square':
        square = sp.expand(g**2)
        wrong = h if sp.simplify(h-square) != 0 else square+1
        interaction, expected = _choice(rf'${latex(square)}$', [rf'${latex(wrong)}$'])
        return _card('展开平方，寻找相同的项',
                     rf'先观察 ${f}$ 括号里的式子：${bracket}^2$ 展开后等于什么？',
                     '题目给出的关系', original, '平方展开', rf'{bracket}^2={latex(square)}',
                     rf'用完全平方公式展开，注意中间的乘积项。得到 ${bracket}^2={latex(square)}$。', interaction, expected)
    if phase == 'match':
        # Keep g intact in the displayed identity rather than immediately
        # expanding it back to the original right side.
        symbol = sp.Symbol('G')
        matched = latex(result['expression'].subs(t, symbol)).replace('G', bracket)
        wrong = latex((result['expression']+1).subs(t, symbol)).replace('G', bracket)
        interaction, expected = _choice(rf'${matched}$', [rf'${wrong}$'])
        return _card('把右边配成同一个式子',
                     rf'利用刚才的平方展开，右边的 ${latex(h)}$ 可以写成哪一个式子？',
                     '可利用的恒等式', rf'{bracket}^2={latex(sp.expand(g**2))}',
                     '配凑后的关系', rf'{f}\left({latex(g)}\right)={matched}',
                     '把函数括号里的式子看作一个整体，右边也用这个整体来表示。展开右边即可检查等式是否成立。', interaction, expected)
    if phase == 'rename':
        wrong = result['expression']+t+1
        interaction, expected = _choice(rf'${rule}$', [rf'${f}({latex(t)})={latex(wrong)}$'])
        return _card('读出函数的解析式',
                     rf'将 ${latex(g)}$ 简记为 ${latex(t)}$，刚才的关系可以写成什么？',
                     '把相同的式子整体替换', rf'{latex(t)}={latex(g)}', '得到解析式', rule,
                     rf'左右两边的 ${latex(g)}$ 都换成 ${latex(t)}$，得到 ${rule}$。', interaction, expected)
    if phase != 'coverage':
        raise ValueError('function_matching.unknown_phase')
    if isinstance(source, DifferenceSource):
        c = source.reciprocal_constant
        coverage = (rf'${latex(g)}$ 能取任意实数。想让它等于任意给定的 ${latex(t)}$，'
                    rf'只需解 ${latex(x**2-t*x-c)}=0$。'
                    rf'判别式 ${latex(t**2+4*c)}>0$，两个根的乘积为 ${latex(-c)}\ne0$，'
                    '所以总能找到非零的原变量。原题的变量不能取 0，但函数的输入可以等于 0，也可以是任何实数。')
    else:
        coordinate = source.inverse_coordinate(t)
        coverage = (rf'由 ${latex(t)}={latex(g)}$，得到 '
                    + (rf'$\sqrt{{{latex(x)}}}={latex(coordinate)}\geq0$。' if source.root_input
                       else rf'${latex(x)}={latex(coordinate)}$。')
                    + rf'因此，${_condition(source.image, t)}$ 中每个数都能取到。'
                    + ('范围外的函数值，题目没有告诉我们。' if source.root_input else ''))
    return answer_view(desc, result, source, coverage_override=coverage)


def value_view(desc, result, phase):
    source = matching_source(desc)
    x, f, target, witness = result['variable'], desc['function_name'], result['input'], result['source_input']
    g, h = source.expressions(x)
    h = sp.expand(h)
    target_call = rf'{f}({latex(target)})'
    if phase == 'input':
        wrong = sp.S.Zero if not source.domain.contains(0) else witness+1
        if wrong == witness:
            wrong += 1
        interaction, expected = _choice(rf'${latex(x)}={latex(witness)}$', [rf'${latex(x)}={latex(wrong)}$'])
        return _card('先让括号里的值等于目标输入',
                     rf'求 ${target_call}$，不必先求解析式。原关系中选哪一个 ${latex(x)}$，能让 ${latex(g)}={latex(target)}$？',
                     '题给关系', rf'{f}\left({latex(g)}\right)={latex(h)}',
                     '选一个合法的原变量', rf'{latex(x)}={latex(witness)}\quad\Longrightarrow\quad {latex(g)}={latex(target)}',
                     rf'取 ${latex(x)}={latex(witness)}$ 满足 ${_condition(source.domain, x)}$，函数括号里的值就是 ${latex(target)}$。',
                     interaction, expected)
    if phase == 'conclusion':
        interaction, expected = _choice(rf'${latex(result["value"])}$', [rf'${latex(result["value"]+1)}$'])
        return _card('代入原关系，算出函数值',
                     rf'将 ${latex(x)}={latex(witness)}$ 代入题目右边，${target_call}$ 等于多少？',
                     '在原关系中代入', _lines([rf'{f}\left({latex(g)}\right)={latex(h)}', rf'{latex(x)}={latex(witness)}']),
                     '这一问的答案', rf'{target_call}={latex(result["value"])}',
                     _math(rf'{target_call}={latex(result["value"])}'), interaction, expected)
    raise ValueError('function_value.unknown_phase')
