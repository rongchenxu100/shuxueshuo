"""Mathematical working for the coefficient method, separate from interaction hints."""
import sympy as sp

from ..function_coefficients import coefficient_source, compare_coefficients
from .capabilities import solve_quadratic
from .evaluation_presentation import _lines
from .math_values import latex


def _read(node, description, source, polynomial=None):
    if node == description['target_ast'][2]:
        return source.variable
    if node[0] == 'number':
        return sp.Rational(node[1])
    if node[0] == 'function_call':
        argument = _read(node[2], description, source, polynomial)
        return (sp.Function(description['function_name'])(argument) if polynomial is None else
                polynomial.subs(source.variable, argument))
    if node[0] == 'neg':
        return -_read(node[1], description, source, polynomial)
    left, right = [_read(child, description, source, polynomial) for child in node[1:]]
    return {'+': lambda: left+right, '-': lambda: left-right, '*': lambda: left*right,
            '/': lambda: left/right, '^': lambda: left**right,
            '=': lambda: sp.Eq(left, right, evaluate=False)}[node[0]]()


def relation_rows(description, source, polynomial=None):
    """Keep each source condition beside its own substitution; fixed values come first."""
    polynomial = source.template if polynomial is None else polynomial
    rows = [{'original': _read(ast, description, source),
             'substitution': _read(ast, description, source, polynomial)}
            for ast in [description['relation_ast'], *description.get('additional_relations_ast', [])]]
    for row in rows:
        eq = row['substitution']
        row['expanded'] = sp.Eq(sp.expand(eq.lhs), sp.expand(eq.rhs), evaluate=False)
    return sorted(rows, key=lambda row: row['original'].has(source.variable))


def _chain(*expressions):
    return '$'+ '='.join(dict.fromkeys(latex(value) for value in expressions))+'$'


def _equations(equations):
    return _lines([latex(sp.Eq(eq, 0, evaluate=False)) for eq in equations])


def _substitution_lines(rows):
    lines = []
    for index, row in enumerate(rows, 1):
        original, substituted, expanded = (row[key] for key in ('original', 'substitution', 'expanded'))
        lines.append(rf'条件 {index}：${latex(original)}$。')
        lines.append(_chain(original.lhs, substituted.lhs, expanded.lhs))
        if original.rhs != substituted.rhs or substituted.rhs != expanded.rhs:
            lines.append(_chain(original.rhs, substituted.rhs, expanded.rhs))
        lines.append(rf'因此 ${latex(expanded)}$。')
    return lines


def _coefficient_steps(source, result, equations):
    cs = source.coefficients
    lines = [rf'由上一步的方程组 ${_equations(equations)}$：']
    leading = next((eq for eq in equations if eq.free_symbols == {cs[0]}), None)
    if leading is not None:
        choices = sorted({row[0] for row in result['coefficient_tuples']}, key=sp.default_sort_key)
        roots = ' 或 '.join(rf'${latex(cs[0])}={latex(value)}$' for value in choices)
        lines.append(rf'由 ${latex(sp.Eq(leading, 0, evaluate=False))}$，结合 ${latex(cs[0])}\ne0$，得{roots}。')
    for row in result['coefficient_tuples']:
        known = {cs[0]: row[0]} if leading is not None else {}
        if len(result['coefficient_tuples']) > 1:
            lines.append(rf'当 ${latex(cs[0])}={latex(row[0])}$ 时：')
        for coefficient, value in zip(cs, row):
            if coefficient in known:
                continue
            reduced = [sp.expand(eq.subs(known)) for eq in equations]
            simple = next((eq for eq in reduced if eq.free_symbols == {coefficient}), None)
            if simple is not None:
                lines.append(rf'${latex(sp.Eq(simple, 0, evaluate=False))}'
                             rf'\quad\Longrightarrow\quad {latex(coefficient)}={latex(value)}$')
                known[coefficient] = value
        # Some admitted systems are not triangular; retain their full concrete result.
        assignments = r',\quad '.join(rf'{latex(c)}={latex(v)}' for c, v in zip(cs, row))
        lines.append(rf'得到 ${assignments}$。')
        rule = source.template.subs(dict(zip(cs, row)))
        lines.append(rf'故 ${result["function_name"]}({latex(source.variable)})={latex(sp.expand(rule))}$。')
    return lines


def _sign_table(expression, variable, roots):
    positions, signs = [], []
    ends = [-sp.oo, *roots, sp.oo]
    for index, (left, right) in enumerate(zip(ends, ends[1:])):
        sample = (right-1 if left == -sp.oo and right != sp.oo else
                  left+1 if right == sp.oo and left != -sp.oo else
                  sp.S.Zero if left == -sp.oo else (left+right)/2)
        positions.append(latex(sp.Interval.open(left, right)))
        signs.append('+' if expression.subs(variable, sample) > 0 else '-')
        if index < len(roots):
            positions.append(latex(roots[index]))
            signs.append('0')
    return (r'\begin{array}{c|'+'c'*len(positions)+'}'+latex(variable)+'&'+'&'.join(positions)
            +r'\\\hline y&'+'&'.join(signs)+r'\end{array}')


def full_derivation(values):
    desc, r, phase = (values[key] for key in ('description', 'formula_result', 'phase'))
    s = coefficient_source(desc)
    x, f = s.variable, desc['function_name']
    rows = relation_rows(desc, s)
    comparison = compare_coefficients(s.relations, x, s.coefficients, sp.S.Reals)
    if phase == 'template':
        typename = '一次函数' if len(s.coefficients) == 2 else '二次函数'
        names = ','.join(latex(c) for c in s.coefficients)
        return '\n'.join([
            rf'题给 ${f}$ 是{typename}，因此可设',
            rf'${f}({latex(x)})={latex(s.template)}$',
            rf'其中 ${names}\in\mathbb{{R}}$，${latex(s.coefficients[0])}\ne0$。'
            '最高次项系数不为零，保证它是题给类型的函数。'])
    if phase == 'expand':
        return '\n'.join(_substitution_lines(rows))
    if phase == 'compare':
        lines = []
        for index, row in enumerate(rows, 1):
            eq = row['expanded']
            lines.append(rf'条件 {index} 化为 ${latex(eq)}$。')
            if not eq.has(x):
                continue
            lines.append(rf'此等式对任意实数 ${latex(x)}$ 成立，故同次幂系数相等：')
            terms = compare_coefficients([eq], x, s.coefficients, sp.S.Reals)['rows']
            for term in terms:
                name = {2: '二次项', 1: '一次项', 0: '常数项'}[term['degree']]
                lines.append(rf'{name}：${latex(sp.Eq(term["left"], term["right"], evaluate=False))}$。')
        lines.append(rf'移项并合并同类项，得到 ${_equations(comparison["equations"])}$。')
        return '\n'.join(lines)
    if phase == 'solve':
        return '\n'.join(_coefficient_steps(s, r, comparison['equations']))
    if phase == 'verify':
        lines = []
        for polynomial in r['candidates']:
            lines.append(rf'将 ${f}({latex(x)})={latex(polynomial)}$ 代回原条件：')
            lines.extend(_substitution_lines(relation_rows(desc, s, polynomial)))
            leading = sp.Poly(polynomial, x).LC()
            lines.append(rf'以上等式左右两边相同，且最高次项系数 ${latex(leading)}\ne0$，符合题意。')
        return '\n'.join(lines)
    if phase != 'answer':
        raise ValueError('function_coefficients.unknown_derivation_phase')
    lines = []
    if s.kind == 'find_range':
        op, rhs = s.requested
        for polynomial, solution in zip(r['candidates'], r['solution_sets']):
            expression = sp.expand(polynomial-rhs)
            roots = solve_quadratic(expression, x)['outputs']['roots']
            lines.append(rf'由 ${f}({latex(x)})={latex(polynomial)}$，原不等式等价于 '
                         rf'${latex({">": sp.Gt, ">=": sp.Ge, "<": sp.Lt, "<=": sp.Le}[op](expression, 0, evaluate=False))}$。')
            lines.append(_chain(expression, sp.factor(expression)))
            root_text = ' 或 '.join(rf'${latex(x)}={latex(root)}$' for root in roots)
            lines.append(rf'令 ${latex(expression)}=0$，'+('得'+root_text+'。' if roots else '无实数解。'))
            lines.append(rf'记 $y={latex(expression)}$，各段的符号为：')
            lines.append('$'+_sign_table(expression, x, roots)+'$')
            lines.append(rf'所以 ${latex(x)}\in {latex(solution)}$。')
        if r['solution'] is None:
            lines.append('不同的合法解析式对应不同解集，因此原题不能唯一确定解集。')
        return '\n'.join(lines)
    for row, polynomial in zip(r['coefficient_tuples'], r['candidates']):
        assignments = r',\quad '.join(rf'{latex(c)}={latex(v)}' for c, v in zip(s.coefficients, row))
        lines.append(rf'由 ${assignments}$，得 ${f}({latex(x)})={latex(polynomial)}$。')
        if s.kind == 'find_value':
            argument = sp.Symbol('u')
            substitution = latex(polynomial.subs(x, argument)).replace('u', rf'\left({latex(s.requested)}\right)')
            value = sp.simplify(polynomial.subs(x, s.requested))
            lines.append(rf'${f}({latex(s.requested)})={substitution}={latex(value)}$')
    if s.kind == 'find_value':
        lines.append(rf'所以 ${f}({latex(s.requested)})={latex(r["value"])}$。' if r['value'] is not None else
                     '不同的合法解析式给出了不同的函数值，因此不能唯一确定答案。')
    else:
        rules = ' 或 '.join(rf'${f}({latex(x)})={latex(p)}$' for p in r['candidates'])
        lines.append(rf'综上，{rules}，${latex(x)}\in\mathbb{{R}}$。')
    return '\n'.join(lines)
