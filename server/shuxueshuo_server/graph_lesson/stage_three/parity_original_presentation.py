"""R2 teaching follows original guards and exhaustive mirror-cell evidence."""
import sympy as sp

from .. import parity_parameter_original as math
from ..function_parity import reflect_ast
from ..stage_one.function_domain import expression_latex
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .parity_domain_presentation import _choice, domain_latex
from .parity_parameter_presentation import condition_value_latex


def source_lines(desc):
    from .parity_parameter_presentation import PROPERTY, _display_ast
    x, f = desc['variable'], desc['function']
    lines = [f'{f}({x})=' + expression_latex(_display_ast(desc['expression_ast']), x)]
    if desc.get('domain_role') == 'declared':
        lines.append('D=' + domain_latex(desc['domain_ast'], x))
    else:
        lines.append(r'\text{定义域由未约分的原式确定}')
    lines.append(r'\text{' + '、'.join(PROPERTY[k] for k in sorted({v['property'] for v in desc['parity_facts']})) + '}')
    for region in desc['defined_regions']:
        lines.append(x + r'\in ' + domain_latex(region['domain_ast'], x) + r'\text{ 时原式有意义}')
    return lines


def _comparison_lines(desc, proof):
    p = desc['parameter']
    if proof['kind'] == 'radical':
        a, b = proof['source']['alpha'], proof['source']['beta']
        lines = [r'\alpha=' + latex(a) + r',\quad\beta=' + latex(b),
                 r'\text{先要求根号内非负，并使完整定义域非空}',
                 *[condition_value_latex(c) for c in proof['domain_conditions']],
                 r'\alpha<0,\ \beta>0:\quad D=[-\sqrt{-\beta/\alpha},\sqrt{-\beta/\alpha}]',
                 r'\alpha>0,\ \beta<0:\quad D=(-\infty,-\sqrt{-\beta/\alpha}]\cup[\sqrt{-\beta/\alpha},+\infty)',
                 r'\alpha<0,\ \beta=0:\quad D=\{0\}',
                 r'\alpha\le0,\ \beta<0:\quad D=\varnothing',
                 r'\text{其余符号情形的自然定义域为实数集}',
                 r'\text{非空自然定义域都对称，开方后的函数为偶函数}']
        if any(-1 in math.base.PROPERTIES[f['property']] for f in desc['parity_facts']):
            lines += [r'\text{函数值非负；若还要求奇性，必须在整个定义域恒为零}',
                      *[condition_value_latex(c) for c in proof['zero_conditions']]]
        return lines
    # Merge identical conditions to keep a long exact certificate readable.
    grouped = {}
    for row in proof['rows']:
        reason = ('原式在要求范围内无意义或区间不成立' if not row['valid'] else
                  '定义域为空' if not row['nonempty'] else
                  '完整定义域不对称' if not row['symmetric'] else '')
        equations = tuple(row['equations']) if not reason else ()
        key = (reason, equations)
        grouped[key] = grouped.get(key, sp.S.EmptySet) | row['parameter_cell']
    lines = []
    for (reason, equations), region in grouped.items():
        prefix = p + r'\in ' + latex(region) + r':\quad '
        if reason:
            lines.append(prefix + r'\text{' + reason + '，排除}')
        elif equations:
            lines.append(prefix + r'\text{域非空且对称，仍须满足}')
            lines.extend(latex(e) + '=0' for e in equations)
        else:
            lines.append(prefix + r'\text{域非空且对称，函数值关系恒成立}')
    return lines


def phase_views(values):
    from .parity_parameter_presentation import _display_ast, _read
    d, phase = values['description'], values['phase']
    x, p, f = d['variable'], d['parameter'], d['function']
    original = _lines(source_lines(d))
    if phase == 'domain':
        src = math.source(d)
        if src['kind'] == 'radical':
            variable, _ = math.symbols(d)
            checks = [latex(src['alpha']*variable**2 + src['beta']) + r'\ge0',
                      r'\text{按系数符号分类，保留根号等于零的端点}']
        else:
            guards = sorted({g for row in src['parts'] for g in row['guards']}, key=sp.default_sort_key)
            checks = [latex(g) + r'\ne0' for g in guards]
            checks += [r'\text{保留原分段范围，再检查每个输入的相反数是否也在域内}']
        checks += [r'\text{约分或分子变零都不能补回原式缺失的输入}',
                   r'\text{若题给完整定义域，原式必须在该域处处有意义}']
        return [_read('检查原式的定义域', '先按未约分的原式确定合法输入；完整定义域必须非空且关于原点对称。',
                      '原题条件', original, '需要检查的条件', _lines(checks), _lines(checks))]
    if phase == 'identity':
        signs = sorted({s for fact in d['parity_facts'] for s in math.base.PROPERTIES[fact['property']]})
        relations = [f'{f}(-{x})=' + ('-' if s < 0 else '') + f'{f}({x})' for s in signs]
        substituted = f'{f}(-{x})=' + expression_latex(reflect_ast(_display_ast(d['expression_ast'])), x)
        return [_read('按原式配对函数值', '把相反数作为整体代入；分段函数要重新判断相反输入落在哪一段。',
                      '原函数', original, '完整定义域内的关系', _lines(relations),
                      _lines([substituted, *relations, r'\text{只在两个输入都合法时比较，零点也要单独核对}']))]
    if phase == 'compare':
        lines = _comparison_lines(d, values['evidence'])
        return [_read('分类检查函数值关系', '先检查域，再在每一段比较完整恒等条件；临界参数、孤立点和分段端点分别核对。',
                      '原函数与要求', original, '全部分类条件', _lines(lines), _lines(lines))]
    model = values['evidence']
    solution = model['feasible_set']
    conditions = [condition_value_latex(c) for c in model['conditions']]
    if model['exclusive']:
        conditions.append(p + r'\notin ' + latex(model['zero_set']) + r'\quad\text{排除恒为零的情形}')
    proof = _lines([p + r'\in ' + latex(model['parity_set']), *conditions, p + r'\in ' + latex(solution)])
    if phase == 'solve':
        return [_choice('合并全部参数条件', '把域、各段函数值关系、原参数限制及排他要求同时满足的参数保留下来。',
                        _lines([*_comparison_lines(d, model['comparison']), *conditions]), solution,
                        [sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0), model['domain_parameters'], model['zero_set']], proof, p)]
    return [_read('按原式代回核验', '核验覆盖全部参数分类。下图只展示已标注参数的实例，结论以完整分类和恒等条件为依据。',
                  '未约分的原式', original, '最终参数集合', latex(solution), proof)]


def attach_graphs(part, values):
    if values['phase'] != 'verify':
        return
    from .parity_parameter_graphs import examples
    lines, graphs = examples(values['description'], values['evidence'])
    if lines:
        part['condition_number_lines'] = lines
    if len(graphs) == 1:
        part['completion_graph'] = graphs[0]
    elif graphs:
        part['completion_graphs'] = graphs
