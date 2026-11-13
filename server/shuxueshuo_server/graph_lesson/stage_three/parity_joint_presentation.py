"""Joint conditions remain joint in cards, grading and the final handoff."""
import sympy as sp

from ..function_parity import reflect_ast
from ..parity_parameter_joint import source, symbols
from ..stage_one.function_domain import expression_latex
from .absolute_graph_presentation import choice_card
from .math_values import latex, math_value
from .monotonicity_parameter_presentation import _lines
from .parity_parameter_presentation import (
    PROPERTY,
    _display_ast,
    _read,
    compare_view,
    condition_latex,
)


def source_lines(desc):
    return [desc['function']+'('+desc['variable']+')='+expression_latex(_display_ast(desc['expression_ast']), desc['variable']),
            'D='+latex(source(desc)[3]),
            r'\text{'+'、'.join(PROPERTY[f['property']] for f in desc['parity_facts'])+'}']


def family_latex(parameters, families):
    if not families:
        return r'\varnothing'
    alternatives = []
    for family in families:
        rows = [latex(p)+'='+latex(v) for p, v in zip(parameters, family['values'], strict=True) if p != v]
        if family['free_parameters']:
            rows += [','.join(latex(p) for p in family['free_parameters'])+r'\in\mathbb R']
        rows += [latex(e)+r'\ne 0' for e in family['nonzero']]
        alternatives.append(r'\left\{\begin{gathered}'+r'\\'.join(rows)+r'\end{gathered}\right.')
    return r'\quad\text{或}\quad'.join(alternatives)


def answer_for(desc, model):
    _, parameters = symbols(desc)
    families = model['solution']
    condition = sp.Or(*(sp.And(*(sp.Eq(e, 0) for e in f['equations']),
                              *(sp.Ne(e, 0) for e in f['nonzero'])) for f in families))
    return {'kind': desc['source']['kind'], 'status': 'complete', 'result_type': 'parameter_family',
            'parameters': desc['parameters'],
            'conditions': {'expression': sp.sstr(condition), 'latex': family_latex(parameters, families)},
            'families': [{'assignments': [{'parameter': p.name, 'value': math_value(v)}
                                         for p, v in zip(parameters, f['values'], strict=True)],
                          'free_parameters': [p.name for p in f['free_parameters']],
                          'equations': [math_value(e) for e in f['equations']],
                          'nonzero': [math_value(e) for e in f['nonzero']]} for f in families]}


def _point_rows(desc, proof):
    """One row per pair ±q: f(-q)=±f(q) with both sides evaluated."""
    x, _, expression, _, _, _ = source(desc)
    f = desc['function']
    rows = []
    for row in proof['rows']:
        q, sign = row['point'], row['sign']
        if q < 0 and any(r['point'] == -q and r['sign'] == sign for r in proof['rows']):
            continue
        left, right = (sp.expand(expression.subs(x, v)) for v in (-q, q))
        shown = latex(right) if sign == 1 else ('-' + (latex(right) if right.is_Atom else '('+latex(right)+')'))
        rows += [f+'('+latex(-q)+')='+('' if sign == 1 else '-')+f+'('+latex(q)+')',
                 latex(left)+'='+shown]
    return rows


def phase_views(values):
    desc, phase = values['description'], values['phase']
    x, parameters, _, domain, _, signs = source(desc)
    original = source_lines(desc)
    f = desc['function']
    fneg = f+'(-'+desc['variable']+')'
    fx = f+'('+desc['variable']+')'
    relations = [fneg+('=' if s == 1 else '=-')+fx for s in signs]
    if phase == 'domain':
        from ..function_cells import reflect_set
        valid = domain != sp.S.EmptySet and domain == reflect_set(domain)
        proof = [*original, '-D='+latex(reflect_set(domain)),
                 r'\text{定义域非空且关于原点对称}' if valid else r'\text{定义域不满足奇偶性的前提}']
        return [_read('检查完整定义域', '先检查给定的完整定义域；有限个输入不能当成整个实数集。',
                      '原函数及性质', _lines(original), '定义域检查', proof[-1], _lines(proof))]
    if phase == 'identity':
        reflected = fneg+'='+expression_latex(reflect_ast(_display_ast(desc['expression_ast'])), desc['variable'])
        wrong = [fneg+('=-' if signs == [1] else '=')+fx] if len(signs) == 1 else []
        view = choice_card('写出相反输入的关系', '在完整定义域内整体代入相反数，再按已知性质建立关系。',
                           '原式及代入', _lines([original[0], original[1], reflected]), '要恒成立的关系',
                           _lines(relations), wrong, _lines([reflected, *relations]))
        if not wrong:
            view.update(interaction={'type': 'read'}, expected_answer={})
        return [view]
    if phase == 'compare':
        proof = values['evidence']
        finite = proof['mode'] == 'finite_points'
        if finite:
            rows = _point_rows(desc, proof)
        else:
            rows = [(r'\text{常数项：}' if r['degree'] == 0 else 'x^{'+str(r['degree'])+r'}\text{ 项：}')
                    + latex(r['residual'])+'=0' for r in proof['rows']]
        conditions = [latex(e)+'=0' for e in proof['equations']] or [r'\text{关系对所有参数都成立}']
        question = ('把定义域中的每一个输入都代入，保留两个参数之间的关系。' if finite else
                    '多项式在非退化区间上恒等，各次项的系数分别相等；不要补加另一种奇偶性。')
        return [compare_view('逐点列条件' if finite else '比较对应项的系数', question,
                             _lines(rows if finite else relations), rows, '联合条件', _lines(conditions),
                             relation_label='逐点代入' if finite else '需要满足的关系', rows_label='逐点代入' if finite else '逐项比较')]
    model = values['evidence']
    answer = family_latex(parameters, model['solution'])
    conditions = [latex(e)+'=0' for e in model['comparison']['equations']]
    conditions += [condition_latex(r['ast'], str(x)) for r in desc['constraints']]
    for row in desc['degrees']:
        conditions.append(r'\deg '+f+'='+str(row['degree']))
    if any(f['property'].endswith('_only') for f in desc['parity_facts']):
        conditions.append(r'\text{还须排除在整个实际域恒为零的情况}')
    if not model['comparison']['domain_valid']:
        conditions.append(r'\text{完整定义域不满足奇偶性的前提}')
    if not conditions:
        conditions = [r'\text{两个实参数都不受额外限制}']
    proof = _lines([*conditions, answer])
    if phase == 'solve':
        other = r'\varnothing' if model['solution'] else r'('+','.join(desc['parameters'])+r')\in\mathbb R^2'
        return [choice_card('合并联合参数条件', '解方程时保留自由参数，并将非零限制代回；答案可以是一族参数。',
                            '全部条件', _lines(conditions), '参数的联合取值', answer, [other], proof)]
    expression = source(desc)[2]
    if not model['solution']:
        return [_read('代回全部解族', '没有参数同时满足全部条件。', '原函数与完整域', _lines(original),
                      '最终联合条件', answer, proof)]
    many = len(model['solution']) > 1
    given, checks = [], []
    for index, family in enumerate(model['solution'], 1):
        prefix = r'\text{解族 '+str(index)+r'：}' if many else ''
        value = sp.expand(expression.subs(dict(zip(parameters, family['values'], strict=True)), simultaneous=True))
        given.append(prefix+fx+'='+latex(value))
        if isinstance(domain, sp.FiniteSet):
            checks.append(prefix+r',\ '.join(f+'('+latex(q)+')='+latex(sp.expand(value.subs(x, q)))
                                            for q in sorted(domain)))
        else:
            checks.append(prefix+fneg+'='+latex(sp.expand(value.subs(x, -x))))
        checks += [prefix+latex(e)+r'\ne 0' for e in family['nonzero']]
    given.append('D='+latex(domain))
    checks.append(r'\Rightarrow\ '+r'\text{、}'.join(relations))
    return [_read('代回核验', '把联合解代入原式检查；自由参数保留为字母。', '代入联合解', _lines(given),
                  '检验', _lines(checks), _lines([*given, *checks, answer]))]
