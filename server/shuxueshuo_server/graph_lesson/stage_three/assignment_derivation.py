"""Concrete substitutions, isolation and two-sided checks for assignment lessons."""
import sympy as sp
from sympy.core.function import AppliedUndef

from ..function_assignment import assignment_source, specialized_equations
from .math_values import latex


def formula_at(polynomial, variable, argument):
    """Keep an input such as x+y together until the expansion is displayed."""
    input_math = latex(argument)
    if not argument.is_Atom or argument.could_extract_minus_sign():
        input_math = rf'\left({input_math}\right)'
    marker = sp.Symbol('Z')
    return latex(polynomial.xreplace({variable: marker})).replace(latex(marker), input_math)


def _substituted_math(side, source, polynomial):
    if isinstance(side, AppliedUndef):
        return formula_at(polynomial, source.x, side.args[0])
    calls = sorted(side.atoms(AppliedUndef), key=str)
    markers = {call: sp.Symbol(f'Z{index}') for index, call in enumerate(calls)}
    rendered = latex(side.xreplace(markers))
    for call, marker in markers.items():
        value = formula_at(polynomial, source.x, call.args[0])
        rendered = rendered.replace(latex(marker), rf'\left({value}\right)')
    return rendered


def verification_rows(source, polynomial):
    rows = []
    for label, side in [('左边', source.left), ('右边', source.right)]:
        calls = sorted(side.atoms(AppliedUndef), key=str)
        replacements = {call: polynomial.subs(source.x, call.args[0]) for call in calls}
        rows.append({'label': label, 'original': latex(side),
                     'substitution': _substituted_math(side, source, polynomial),
                     'expanded': sp.expand(side.xreplace(replacements)),
                     'calls': [latex(call)+'='+formula_at(polynomial, source.x, call.args[0])
                               for call in calls]})
    return rows


def _equation(left, right):
    return latex(sp.Eq(left, right, evaluate=False))


def full_derivation(values):
    desc, result, phase = (values[key] for key in ('description', 'formula_result', 'phase'))
    s = assignment_source(desc)
    plan, polynomial = result['assignment_plan'], result['expression']
    sub = plan['substitution']
    equations = specialized_equations(s, plan)
    variable, f = equations['variable'], s.function
    left, right = s.apply(s.left, sub), s.apply(s.right, sub)
    original, specialized = _equation(s.left, s.right), _equation(left, right)
    local_rule = _equation(f(variable), polynomial.subs(s.x, variable))
    rule = _equation(f(s.x), polynomial)
    assignment = r',\quad '.join(key+'='+latex(value) for key, value in sub.items())
    if phase == 'choose':
        return '\n'.join([rf'原关系：${original}$。',
                          rf'令 ${assignment}$，代入等式两边：', '$'+specialized+'$'])
    if phase == 'special':
        if plan['needs_zero']:
            zero_sub = {str(s.x): sp.S.Zero, str(s.y): sp.S.Zero}
            zero_eq = equations['zero_equation']
            return '\n'.join([
                rf'令 ${latex(s.x)}={latex(s.y)}=0$：',
                '$'+_equation(s.apply(s.left, zero_sub), s.apply(s.right, zero_sub))+'$',
                '$'+_equation(zero_eq['coefficient']*f(0), zero_eq['rhs'])+'$',
                '$'+_equation(f(0), result['zero_value'])+'$'])
        return '\n'.join([
            '$'+specialized+'$',
            '移项，合并同类项：',
            '$'+_equation(equations['coefficient']*f(variable), equations['rhs'])+'$',
            '$'+local_rule+'$'])
    if phase == 'isolate':
        if plan['needs_zero']:
            zero = result['zero_value']
            rhs = sp.expand(equations['rhs']-equations['zero_coefficient']*zero)
            return '\n'.join([
                '$'+specialized+'$', rf'代入 ${_equation(f(0), zero)}$：',
                '$'+_equation(left.xreplace({f(0): zero}), right.xreplace({f(0): zero}))+'$',
                '$'+_equation(equations['coefficient']*f(variable), rhs)+'$',
                '$'+local_rule+'$',
                rf'故 ${rule},\quad {latex(s.x)}\in\mathbb{{R}}$。'])
        return '\n'.join([
            rf'$\forall {latex(variable)}\in\mathbb{{R}},\quad {local_rule}$',
            rf'将字母 ${latex(variable)}$ 改写成 ${latex(s.x)}$：',
            rf'$\forall {latex(s.x)}\in\mathbb{{R}},\quad {rule}$'])
    if phase == 'verify':
        lines = [rf'已求出 ${rule}$。', rf'原关系：${original}$。']
        for row in verification_rows(s, polynomial):
            lines.append(row['label']+'：')
            parts = list(dict.fromkeys([row['original'], row['substitution'], latex(row['expanded'])]))
            lines.append('$'+'='.join(parts)+'$')
        lines.append(rf'两边相同，对任意 ${latex(s.x)},{latex(s.y)}\in\mathbb{{R}}$，原等式成立。')
        return '\n'.join(lines)
    if phase == 'answer':
        return rf'${rule},\quad {latex(s.x)}\in\mathbb{{R}}$'
    raise ValueError('function_assignment.unknown_derivation_phase')
