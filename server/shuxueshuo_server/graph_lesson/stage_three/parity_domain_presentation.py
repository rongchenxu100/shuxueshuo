"""Source-domain cards for verified FP-T2 R1 evidence."""
import sympy as sp

from .. import parameter_domain as domains
from ..function_parity import reflect_domain_ast
from ..stage_one.function_domain import expression_latex
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .parity_parameter_runtime import domain_only


def domain_latex(ast, variable='x'):
    """Keep symbolic source endpoints; do not construct a fixed SymPy interval."""
    op = ast[0]
    if op == 'real':
        return r'\mathbb R'
    if op == 'empty_set':
        return r'\varnothing'
    if op == 'interval':
        return ('[' if ast[1] else '(') + domain_latex(ast[3], variable) + ',' + domain_latex(ast[4], variable) + (']' if ast[2] else ')')
    if op == 'set':
        return r'\{' + ','.join(domain_latex(v, variable) for v in ast[1:]) + r'\}'
    if op in ('∪', '∩', 'set_difference'):
        return '(' + domain_latex(ast[1], variable) + ')' + {'∪': r'\cup ', '∩': r'\cap ', 'set_difference': r'\setminus '}[op] + '(' + domain_latex(ast[2], variable) + ')'
    if op == 'infinity':
        return ('-' if ast[1] < 0 else '+') + r'\infty'
    if op == 'neg' and ast[1][0] == 'infinity':
        return r'-\infty' if ast[1][1] > 0 else r'+\infty'
    return expression_latex(ast, variable)


def source_lines(desc):
    from .parity_parameter_presentation import PROPERTY, _display_ast
    x, f = desc['variable'], desc['function']
    lines = []
    if desc['expression_ast'] is not None:
        lines.append(f'{f}({x})=' + expression_latex(_display_ast(desc['expression_ast']), x))
    lines += ['D=' + domain_latex(desc['domain_ast'], x),
              r'\text{' + '、'.join(PROPERTY[k] for k in sorted({r['property'] for r in desc['parity_facts']})) + '}']
    for rule in desc['local_rules']:
        lines.append(x + r'\in D\cap ' + domain_latex(rule['mask_ast'], x) + r':\quad '
                     + f'{f}({x})=' + expression_latex(_display_ast(rule['expression_ast']), x))
    for region in desc['defined_regions']:
        lines.append(x + r'\in ' + domain_latex(region['domain_ast'], x) + r'\text{ 时原式有意义}')
    return lines


def _choice(title, question, left, correct, alternatives, proof, parameter, left_label='已得到的条件'):
    from .parity_parameter_presentation import membership_options
    unique = []
    for item in alternatives:
        if item != correct and item not in unique:
            unique.append(item)
    right, wrong = membership_options(parameter, latex(correct), [latex(v) for v in unique[:3]])
    return choice_card(title, question, left_label, left, '参数范围', right, wrong, proof)


def _value_conditions(comparison, p):
    rows = comparison['rows']
    if not rows:
        return [r'\text{没有参数使定义域关于原点对称}']
    lines = []
    for row in rows:
        condition = (r',\ '.join(latex(e) + '=0' for e in row['equations']) if row['equations']
                     else r'\text{没有新的限制}')
        prefix = (r'\text{由函数值关系：}' if len(rows) == 1
                  else r'\text{当 }' + p + r'\in ' + latex(row['parameter_cell']) + r'\text{ 时，由函数值关系：}')
        lines.append(prefix + condition)
    return lines


def _wrapped(text):
    return '(' + text + ')' if any(sign in text[1:] for sign in '+-') else text


def _endpoint_equation(d, symmetric):
    """For [L, R] (or (L, R)), symmetry about 0 means L+R=0 with L<R."""
    ast = d['domain_ast']
    if ast[0] != 'interval' or ast[1] != ast[2]:
        return None
    p = sp.Symbol(d['parameter'], real=True)
    tree = domains.compile_domain(ast, p, d['parameter_ref'])
    low, high = tree[3:]
    if sp.oo in (abs(low), abs(high)):
        return None
    values = sp.solve(sp.Eq(low + high, 0), p, dict=True)
    if len(values) != 1 or sp.FiniteSet(values[0][p]) != symmetric:
        return None
    value = values[0][p]
    texts = [domain_latex(node, d['variable']) for node in ast[3:]]
    correct = _wrapped(texts[0]) + '+' + _wrapped(texts[1]) + r'=0\ \Rightarrow\ ' + d['parameter'] + '=' + latex(value)
    wrong = []
    for left, right, text in ((low, high, texts[0] + '=' + texts[1]),
                              (low, 0, texts[0] + '=0'), (high, 0, texts[1] + '=0')):
        found = sp.solve(sp.Eq(left, right), p, dict=True)
        if len(found) == 1 and found[0][p] != value:
            wrong.append(text + r'\ \Rightarrow\ ' + d['parameter'] + '=' + latex(found[0][p]))
    if not wrong:
        return None
    order = (texts[0] + '<' + texts[1] + r'\text{，即 }' + latex(low.subs(p, value)) + '<' + latex(high.subs(p, value)))
    return correct, wrong, [correct, d['parameter'] + '=' + latex(value) + r'\text{ 时，}' + order]


def _verify_lines(d, solution):
    p = sp.Symbol(d['parameter'], real=True)
    if not isinstance(solution, sp.FiniteSet):
        return [d['parameter'] + r'\in ' + latex(solution) + r'\text{ 时，定义域关于原点对称}']
    tree = domains.compile_domain(d['domain_ast'], p, d['parameter_ref'])
    return [d['parameter'] + '=' + latex(v) + r'\text{ 时，}D=' + latex(domains.fixed_set(tree, p, v))
            + r'\text{，关于原点对称}' for v in sorted(solution)]


def phase_views(values):
    from .parity_parameter_presentation import _read, condition_value_latex
    d, phase = values['description'], values['phase']
    x, p, f = d['variable'], d['parameter'], d['function']
    original = _lines(source_lines(d))
    signs = sorted({s for fact in d['parity_facts'] for s in
                    ({-1, 1} if fact['property'] == 'both' else {-1} if fact['property'].startswith('odd') else {1})})
    relations = [f'{f}(-{x})=' + ('-' if sign < 0 else '') + f'{f}({x})' for sign in signs]
    if phase == 'domain':
        proof = values['evidence']
        symmetric = proof['symmetric_parameters']
        given = _lines([*source_lines(d), r'\Rightarrow\ \text{定义域关于原点对称}'])
        title, domain = '检查定义域是否关于原点对称', 'D=' + domain_latex(d['domain_ast'], x)
        if equation := _endpoint_equation(d, symmetric):
            correct, wrong, steps = equation
            return [choice_card(title, f'奇函数和偶函数的定义域都关于原点对称。要使 ${domain}$ 关于原点对称，${p}$ 应满足什么？',
                                '原题条件', given, '对称条件', correct, wrong, _lines([domain, *steps]))]
        reflected_domain = d['domain_ast'] if d['domain_ast'] == ['empty_set'] else reflect_domain_ast(d['domain_ast'])
        conditions = _lines([domain, '-D=' + domain_latex(reflected_domain, x),
                             r'\text{定义域非空，且 }D=-D', p + r'\in ' + latex(symmetric)])
        return [_choice(title, f'奇函数和偶函数的定义域都关于原点对称。哪些 ${p}$ 能使 ${domain}$ 非空且关于原点对称？',
                        given, symmetric, [proof['valid_parameters'], sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0)],
                        conditions, p, '原题条件')]
    if phase == 'identity':
        note = r'\text{关系只要求在完整定义域内成立}'
        if d['local_rules']:
            note = r'\text{局部公式只用于题给范围；重叠处和零点必须相容}'
        return [_read('写出函数值的关系', '题目只给出部分范围内的解析式，奇偶关系要在整个定义域上成立。'
                      if d['expression_ast'] is None else f'奇偶关系要对定义域内的每个 ${x}$ 都成立。',
                      '原题条件', original, '奇偶关系', _lines(relations), _lines([*relations, note]))]
    if phase == 'compare':
        lines = _value_conditions(values['evidence'], p)
        return [_read('检查函数值关系', f'把 ${relations[0]}$ 代入解析式，比较两边，得到参数要满足的条件。',
                      '原式与定义域', original, '函数值条件', _lines(lines), _lines(lines))]
    model = values['evidence']
    solution = model['feasible_set']
    restrictions = [condition_value_latex(c) for c in model['conditions']]
    proof = _lines([p + r'\in ' + latex(model['parity_set']),
                    *restrictions,
                    *([r'\text{还须能取到非零函数值}'] if model['exclusive'] else []),
                    p + r'\in ' + latex(solution)])
    if phase == 'solve':
        domain = model['comparison']['domain_evidence']
        known = [r'\text{由定义域关于原点对称：}' + p + r'\in ' + latex(domain['symmetric_parameters']),
                 *(_value_conditions(model['comparison'], p) if not domain_only(d) else []), *restrictions,
                 *([r'\text{还须能取到非零函数值}'] if model['exclusive'] else [])]
        return [_choice('合并全部参数条件', '把定义域、函数值关系和题目对参数的其他要求放在一起，同时满足。', _lines(known), solution,
                        [sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0), model['parity_set']], proof, p)]
    if isinstance(solution, sp.FiniteSet) and solution != sp.S.EmptySet:
        from ..parity_parameter_domain import source
        from .parity_parameter_presentation import substitution_view
        variable, parameter, expr, _, _, _ = source(d)
        tree = domains.compile_domain(d['domain_ast'], parameter, d['parameter_ref'])
        given, checks = [], []
        for value in sorted(solution):
            prefix = p + '=' + latex(value) + r'\text{ 时，}' if len(solution) > 1 else ''
            domain = latex(domains.fixed_set(tree, parameter, value))
            given.append(prefix + 'D=' + domain)
            checks.append(prefix + '-D=' + domain + '=D')
            if expr is not None and not d['local_rules']:
                value_expr = sp.expand(expr.subs(parameter, value))
                given.append(prefix + f'{f}({x})=' + latex(value_expr))
                checks.append(prefix + f'{f}(-{x})=' + latex(sp.expand(value_expr.subs(variable, -variable))))
        checks.append(r'\Rightarrow\ ' + (r'\text{定义域关于原点对称}' if domain_only(d)
                                          else r'\text{、}'.join(relations)))
        return [substitution_view(d, solution, given, checks)]
    if solution == sp.S.EmptySet:
        check = [r'\text{没有参数同时满足全部条件}']
    else:
        check = _verify_lines(d, solution)
        if not domain_only(d):
            check.append(r'\text{且满足 }' + r'\text{、}'.join(relations))
    return [_read('代回核验', '把求出的参数代回原题检查。', '原题条件', original, '最终参数集合', latex(solution),
                  _lines([*check, p + r'\in ' + latex(solution)]))]
