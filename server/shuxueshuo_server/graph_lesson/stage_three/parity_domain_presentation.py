"""Source-domain cards and paired number lines for verified FP-T2 R1 evidence."""
from copy import deepcopy

import sympy as sp

from .. import parameter_domain as domains
from ..function_parity import reflect_domain_ast, reflect_set
from ..stage_one.function_domain import expression_latex
from .absolute_graph_presentation import choice_card
from .domain_visuals import exact_math
from .interaction_graphs import _float, _pieces, short_label
from .math_values import latex
from .monotonicity_parameter_presentation import _lines


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
    lines = []
    for row in comparison['rows']:
        condition = _lines([latex(e) + '=0' for e in row['equations']]) if row['equations'] else r'\text{函数值关系不增加参数限制}'
        lines.append(p + r'\in ' + latex(row['parameter_cell']) + r':\quad ' + condition)
    return lines or [r'\text{没有参数使完整定义域非空且对称}']


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
        reflected_domain = d['domain_ast'] if d['domain_ast'] == ['empty_set'] else reflect_domain_ast(d['domain_ast'])
        conditions = _lines(['D=' + domain_latex(d['domain_ast'], x),
                             '-D=' + domain_latex(reflected_domain, x),
                             r'\text{原区间端点严格有序，且整个定义域非空、对称}',
                             p + r'\in ' + latex(proof['symmetric_parameters'])])
        return [_choice('检查定义域的配对', '保留每个端点的开闭和所有孔洞。哪些参数使完整定义域非空，且每个输入都有相反数与它配对？',
                        original, proof['symmetric_parameters'],
                        [proof['valid_parameters'], sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0)], conditions, p, '原题条件')]
    if phase == 'identity':
        note = r'\text{关系只要求在完整定义域内成立}'
        if d['local_rules']:
            note = r'\text{局部公式只用于题给范围；重叠处和零点必须相容}'
        return [_read('写出函数值的关系', '定义域中的每个输入，都要满足题给的奇偶关系。已知的局部公式不能直接用于整个定义域。'
                      if d['expression_ast'] is None else '把相反数整体代入原式，关系须对每个合法输入成立。',
                      '原题条件', original, '奇偶关系', _lines(relations), _lines([*relations, note]))]
    if phase == 'compare':
        lines = _value_conditions(values['evidence'], p)
        return [_read('检查函数值关系', '有区间时检查多项式恒等条件；有限集逐点检查。只有局部规则时，检查它与反射后的规则能否同时成立。',
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
        known = [r'\text{定义域非空且对称：}' + p + r'\in ' + latex(domain['symmetric_parameters']),
                 *_value_conditions(model['comparison'], p), *restrictions,
                 *([r'\text{还须能取到非零函数值}'] if model['exclusive'] else [])]
        return [_choice('合并全部参数条件', '定义域、函数值关系、原参数限制及排他要求必须同时满足。', _lines(known), solution,
                        [sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0), model['parity_set']], proof, p)]
    return [_read('代回核验', '已逐类核对全部参数，包括临界值、孔洞、开闭端点和局部规则的相容性。',
                  '原题条件', original, '最终参数集合', latex(solution), proof)]


def pairing_lines(desc, parameter_value):
    """A new domain/reflection pairing view using the shared number-line renderer."""
    p = sp.Symbol(desc['parameter'], real=True)
    tree = domains.compile_domain(desc['domain_ast'], p, desc['parameter_ref'])
    original = domains.fixed_set(tree, p, parameter_value)
    sets = [original, reflect_set(original)]
    pieces = [_pieces(s) for s in sets]
    ends = sorted({sp.S.Zero, *(v for intervals, points in pieces for v in
                   [*points, *(e for part in intervals for e in (part.start, part.end) if e not in (-sp.oo, sp.oo))])})
    low, high = _float(ends[0]), _float(ends[-1])
    pad = max((high-low)*0.25, 0.75)
    ticks = [{'at': _float(v), 'label': short_label(v), 'exact': exact_math(v)} for v in ends]
    result = []
    for name, region, (intervals, points) in zip(('D', '-D'), sets, pieces, strict=True):
        result.append({'variable': desc['variable'], 'label': desc['parameter'] + '=' + latex(parameter_value)
                       + r'\text{ 时}\quad ' + name + '=' + latex(region), 'bounds': [low-pad, high+pad],
                       'intervals': [{'left': None if s.start == -sp.oo else _float(s.start),
                                      'right': None if s.end == sp.oo else _float(s.end),
                                      'left_closed': not s.left_open, 'right_closed': not s.right_open,
                                      'exact': exact_math(s)} for s in intervals],
                       'points': [{'at': _float(v), 'label': short_label(v), 'exact': exact_math(v)} for v in points],
                       'ticks': deepcopy(ticks), 'exact_set': exact_math(region)})
    return result


def attach_pairing(part, values):
    phase = values['phase']
    if phase != 'verify':
        return
    solution = values['evidence']['feasible_set']
    # This is an explicitly labelled instance after the full symbolic answer;
    # it never replaces the parameter-cell proof or reveals the pending choice.
    selected = []
    if isinstance(solution, sp.FiniteSet):
        selected.append(min(solution))
    elif solution != sp.S.EmptySet:
        pieces = sorted(solution.args, key=sp.default_sort_key) if isinstance(solution, sp.Union) else [solution]
        selected.append(domains.representative(pieces[0]))
    domain = values['evidence']['comparison']['domain_evidence']
    # Show a rejected domain pairing as well when one exists. No invalid
    # interval is drawn as a point, and domain symmetry is never a parity proof.
    # Interaction seeds deliberately omit full proof cells. Use their checked
    # aggregate sets to choose labelled examples without copying the certificate.
    examples = domain['valid_parameters'] - domain['symmetric_parameters']
    if examples == sp.S.EmptySet and not selected:
        examples = domain['valid_parameters']
    if examples != sp.S.EmptySet:
        pieces = sorted(examples.args, key=sp.default_sort_key) if isinstance(examples, sp.Union) else [examples]
        selected.append(domains.representative(pieces[0]))
    lines = []
    for value in selected:
        pair = pairing_lines(values['description'], value)
        matches = pair[0]['exact_set'] == pair[1]['exact_set']
        for line in pair:
            line['label'] += r'\quad\text{域配对' + ('相同' if matches else '不同') + '}'
        lines.extend(pair)
    if lines:
        part['condition_number_lines'] = lines
