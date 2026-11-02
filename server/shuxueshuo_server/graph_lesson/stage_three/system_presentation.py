"""Show the swap, second equation and elimination before the final rule."""
import sympy as sp

from ..function_system import system_source, interchange
from .evaluation_presentation import _choice, _lines
from .formula_presentation import _condition
from .math_values import latex
from .range_presentation import _card


def _linear_sum(a, first, b, second, *, substitute=False):
    """Keep the two function values in source order, including negative substitutions."""
    def term(coefficient, value):
        if substitute:
            value = rf'\left({value}\right)'
        factor = '' if abs(coefficient) == 1 else latex(abs(coefficient))+(r'\cdot ' if substitute else ' ')
        return factor+value
    return ('-' if a < 0 else '')+term(a, first)+(' - ' if b < 0 else ' + ')+term(b, second)


def _substitution(expression, variable, value):
    # A held input keeps the substitution visible before SymPy simplifies it.
    return latex(expression.xreplace({variable: sp.Symbol('Z')})).replace('Z', rf'\left({latex(value)}\right)')


def phase_view(values):
    desc, r, phase = (values[k] for k in ('description', 'formula_result', 'phase'))
    s = system_source(desc)
    x, phi, f = s.variable, s.transform, sp.Function(desc['function_name'])
    fx, fp = f(x), f(phi)
    swapped = interchange(s)
    second = sp.Eq(s.a*fp+s.b*fx, swapped, evaluate=False)
    left = _linear_sum(s.a, latex(fx), s.b, latex(fp))
    original = left+'='+latex(s.rhs)
    new = _linear_sum(s.a, latex(fp), s.b, latex(fx))+'='+latex(swapped)
    condition = _condition(s.domain, x)
    rule = rf'{latex(fx)}={latex(sp.factor_terms(r["expression"]))}'
    if phase == 'swap':
        i, e = _choice(rf'把 ${latex(x)}$ 换成 ${latex(phi)}$', ['只把一个函数括号里的输入换掉'])
        table = (r'\begin{array}{c|c}\text{原来的函数值}&\text{替换后的函数值}\\\hline '
                 +rf'{latex(fx)}&{latex(fp)}\\{latex(fp)}&{latex(fx)}'+r'\end{array}')
        note = (rf'原题中 ${condition}$，${latex(phi)}$ 也在这个范围内。' if s.transform_kind == 'reciprocal'
                else rf'原关系对所有实数成立，${latex(phi)}$ 仍是实数。')
        return _card('让两个函数值交换位置', '怎样替换原关系中的变量，能让这两个函数值互换？',
                     '题给关系', original, '整条等式一起替换', table,
                     note+rf' 把整条等式中的 ${latex(x)}$ 都换成 ${latex(phi)}$，两个函数值正好交换位置。', i, e)
    if phase == 'second':
        wrong = sp.Eq(s.a*fp+s.b*fx, s.rhs, evaluate=False)
        if wrong == second:
            wrong = sp.Eq(s.a*fp+s.b*fx, swapped+1, evaluate=False)
        i, e = _choice(rf'${new}$', [rf'${latex(wrong)}$'])
        return _card('写出第二个方程', rf'已决定把 ${latex(x)}$ 换成 ${latex(phi)}$。等号右边也一起替换，得到什么？',
                     '原方程 (1)', original, '新方程 (2)', new,
                     '替换要遍及整条等式，不能只改函数括号。两个方程在同一个合法输入范围内同时成立。', i, e)
    if phase == 'eliminate':
        reduced = sp.Eq(s.determinant*fx, sp.expand(s.a*s.rhs-s.b*swapped), evaluate=False)
        wrong = sp.Eq(s.determinant*fx, sp.expand(s.a*s.rhs-s.b*swapped)+1, evaluate=False)
        i, e = _choice(rf'${latex(reduced)}$', [rf'${latex(wrong)}$'])
        combination = rf'方程 (1) 乘 ${latex(s.a)}$，方程 (2) 乘 ${latex(-s.b)}$，再相加'
        return _card('联立消去另一个函数值', combination+rf'。消去 ${latex(fp)}$ 后得到什么？',
                     '两个方程', _lines([r'\text{(1) }'+original, r'\text{(2) }'+new]),
                     '消元后的等式', latex(reduced),
                     rf'相加后 ${latex(fp)}$ 的系数为 $0$，只剩 ${latex(fx)}$。其系数 ${latex(s.determinant)}\ne0$，可以相除求解。', i, e)
    if phase == 'verify':
        expression = r['expression']
        check = sp.simplify(s.a*expression+s.b*expression.subs(x, phi))
        other = sp.factor_terms(expression.subs(x, phi))
        substitution = _linear_sum(s.a, latex(sp.factor_terms(expression)), s.b, latex(other), substitute=True)
        i, e = _choice(rf'${latex(check)}$', [rf'${latex(check+1)}$'])
        return _card('把解析式代回原关系',
                     rf'原关系是 ${original}$。把下面两个函数值代入左边 ${left}$，化简后得到什么？',
                     '把已求的函数值代入左边', _lines([rule, rf'{latex(fp)}={latex(other)}', left+'='+substitution]),
                     '原等式左边化简为', latex(check),
                     rf'化简结果为 ${latex(check)}$，与原题右边相同；原输入条件 ${condition}$ 也保留。', i, e)
    if phase == 'answer':
        final = rule+rf',\quad {condition}'
        wrong = (rule+rf',\quad {latex(x)}\in\mathbb{{R}}' if s.transform_kind == 'reciprocal'
                 else rf'{latex(fx)}={latex(r["expression"]+1)},\quad {condition}')
        i, e = _choice(rf'${final}$', [rf'${wrong}$'])
        note = ('倒数要求输入非零，最终答案仍须写明这一点。' if s.transform_kind == 'reciprocal'
                else '对任意实数都能作这个替换，因此得到整个实数范围上的解析式。')
        if r['status'] == 'insufficient_information':
            note += '题目要求的范围更大；这个解析式只确定了上述范围，其他输入的信息仍不足。'
        return _card('写出完整答案', '结合原题的输入条件，完整答案是哪一项？',
                     '已得到的解析式', rule, '完整答案', final, note, i, e)
    raise ValueError('function_system.unknown_phase')


def full_derivation(values):
    """Concrete replacement, scaled equations, elimination and original-identity check."""
    desc, r, phase = (values[key] for key in ('description', 'formula_result', 'phase'))
    s = system_source(desc)
    x, phi, f = s.variable, s.transform, sp.Function(desc['function_name'])
    fx, fp = latex(f(x)), latex(f(phi))
    first = _linear_sum(s.a, fx, s.b, fp)+'='+latex(s.rhs)
    swapped = interchange(s)
    second = _linear_sum(s.a, fp, s.b, fx)+'='+latex(swapped)
    expression = sp.factor_terms(r['expression'])
    rule = fx+'='+latex(expression)
    condition = _condition(s.domain, x)
    double_input = _substitution(phi, x, phi)
    repeated = rf'{desc["function_name"]}\left({double_input}\right)'
    if phase == 'swap':
        return '\n'.join([
            rf'原条件为 ${condition}$，替换后的输入 ${latex(phi)}$ 仍满足该条件。',
            rf'${double_input}={latex(x)}$',
            rf'${fx}\longmapsto {fp}$',
            rf'${fp}\longmapsto {repeated}={fx}$'])
    if phase == 'second':
        substituted = _linear_sum(s.a, fp, s.b, repeated)+'='+_substitution(s.rhs, x, phi)
        return '\n'.join([
            rf'原方程 (1)：${first}$。',
            rf'将 ${latex(x)}$ 替换为 ${latex(phi)}$：',
            '$'+substituted+'$',
            rf'由 ${double_input}={latex(x)}$，化简得方程 (2)：',
            '$'+second+'$'])
    if phase == 'eliminate':
        first_scaled = _linear_sum(s.a**2, fx, s.a*s.b, fp)+'='+latex(sp.expand(s.a*s.rhs))
        second_scaled = _linear_sum(-s.a*s.b, fp, -s.b**2, fx)+'='+latex(sp.expand(-s.b*swapped))
        numerator = sp.expand(s.a*s.rhs-s.b*swapped)
        reduced = latex(sp.Eq(s.determinant*f(x), numerator, evaluate=False))
        quotient = rf'\frac{{{latex(numerator)}}}{{{latex(s.determinant)}}}'
        solution = fx+'='+quotient
        if quotient != latex(expression):
            solution += '='+latex(expression)
        return '\n'.join([
            rf'方程 (1) 乘 ${latex(s.a)}$：', '$'+first_scaled+'$',
            rf'方程 (2) 乘 ${latex(-s.b)}$：', '$'+second_scaled+'$',
            rf'两式相加，${fp}$ 的项相消：', '$'+reduced+'$',
            rf'两边同除以 ${latex(s.determinant)}\ne0$：',
            '$'+solution+'$'])
    if phase == 'verify':
        other = sp.factor_terms(expression.subs(x, phi))
        substituted = _linear_sum(s.a, latex(expression), s.b, latex(other), substitute=True)
        check = sp.simplify(s.a*expression+s.b*other)
        left = _linear_sum(s.a, fx, s.b, fp)
        return '\n'.join([
            rf'原关系：${first}$。',
            '$'+rule+'$',
            rf'${fp}={_substitution(expression, x, phi)}={latex(other)}$',
            rf'代回原等式左边：${left}={substituted}={latex(check)}$。',
            rf'与右边 ${latex(s.rhs)}$ 相同，且 ${condition}$，原关系成立。'])
    if phase == 'answer':
        note = (rf'${condition}\Longrightarrow {latex(phi)}\ne0$，所以替换在原范围内始终成立。'
                if s.transform_kind == 'reciprocal' else
                rf'${latex(x)}\in\mathbb{{R}}\Longrightarrow {latex(phi)}\in\mathbb{{R}}$。')
        if r['status'] == 'insufficient_information':
            note += '题目要求的范围更大，范围外的函数值仍不能确定。'
        return '\n'.join([rf'由消元与回验，得到 ${rule}$。', note, rf'故 ${rule},\quad {condition}$。'])
    raise ValueError('function_system.unknown_derivation_phase')
