"""R2 teaching follows original guards and exhaustive mirror-cell evidence."""
from itertools import pairwise

import sympy as sp

from .. import parameter_domain as domains
from .. import parity_parameter_original as math
from ..function_parity import reflect_ast
from ..stage_one.function_domain import expression_latex
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .parity_domain_presentation import _choice, domain_latex
from .parity_parameter_presentation import condition_value_latex


def source_lines(desc, domain=None):
    """`domain` replaces the natural-domain reminder once it has been computed."""
    from .parity_parameter_presentation import PROPERTY, _display_ast
    x, f = desc['variable'], desc['function']
    lines = [f'{f}({x})=' + expression_latex(_display_ast(desc['expression_ast']), x)]
    if desc.get('domain_role') == 'declared':
        lines.append('D=' + domain_latex(desc['domain_ast'], x))
    elif domain:
        lines += domain
    elif desc['expression_ast'][:2] == ['call', 'sqrt']:
        lines.append(r'\text{定义域由根号内非负确定}')
    elif any(n[0] == '/' for n in math.fixed.walk(desc['expression_ast'])):
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


def _holes_latex(holes, x):
    if not holes:
        return r'\mathbb R'
    return r'\{' + x + r'\mid ' + r',\ '.join(x + r'\ne ' + latex(h) for h in holes) + r'\}'


def _range_latex(p, region):
    """A parameter range as a student writes it: p>=0, p<0, p=1."""
    p = str(p)
    if isinstance(region, sp.FiniteSet) and len(region) == 1:
        return p + '=' + latex(next(iter(region)))
    if isinstance(region, sp.Interval):
        low, high = region.start, region.end
        if low == -sp.oo and high != sp.oo:
            return p + (r'<' if region.right_open else r'\le ') + latex(high)
        if high == sp.oo and low != -sp.oo:
            return p + (r'>' if region.left_open else r'\ge ') + latex(low)
        if low != -sp.oo:
            return (latex(low) + (r'<' if region.left_open else r'\le ') + p
                    + (r'<' if region.right_open else r'\le ') + latex(high))
    return p + r'\in ' + latex(region)


def _radical_cases(d, proof):
    """Format the domain submethod's exhaustive cases; do not solve again here."""
    a, b = proof['source']['alpha'], proof['source']['beta']
    grouped = {}
    for case in proof['cases']:
        region, kind = case['parameter_cell'], case['domain_kind']
        if region == sp.S.EmptySet:
            continue
        valid = d['domain_role'] != 'declared' or kind == 'real'
        if d['domain_role'] == 'declared':
            text = r'\mathbb R'
        elif kind.startswith('closed_'):
            radius = sp.sqrt(-b/a)
            text = ('[' + latex(-radius) + ',' + latex(radius) + ']' if kind == 'closed_bounded' else
                    r'(-\infty,' + latex(-radius) + r']\cup[' + latex(radius) + r',+\infty)')
        else:
            text = {'empty': r'\varnothing', 'singleton_zero': r'\{0\}', 'real': r'\mathbb R'}[kind]
        key = (text, valid)
        grouped[key] = grouped.get(key, sp.S.EmptySet) | region
    return sorted([(region, text, valid) for (text, valid), region in grouped.items()],
                  key=lambda c: (c[0].contains(0) is not sp.true, sp.default_sort_key(c[0])))


def _radical_results(d, comparison):
    """Each parameter range with its own conclusion; the answer is their union."""
    _, p = math.symbols(d)
    feasible = math.aggregate(d, comparison)['feasible_set']
    odd = any(-1 in math.base.PROPERTIES[f['property']] for f in d['parity_facts'])
    discussion, results = [], []
    for region, text, valid in _radical_cases(d, comparison):
        case = _range_latex(p, region) + r'\text{ 时：}'
        accepted = feasible & region
        fx = d['function'] + '(' + d['variable'] + ')'
        if not valid:
            reason = r'D=' + text + r'\text{，原式在给定范围内无意义，排除}'
        elif text == r'\varnothing':
            reason = r'D=\varnothing\text{，不满足}'
        elif text == r'\{0\}':
            reason = r'D=\{0\}\text{，}' + d['function'] + '(0)=0'
        elif odd:
            reason = r'D=' + text + r'\text{，需 }' + fx + r'=0\text{ 恒成立}'
        else:
            reason = r'D=' + text + r'\text{，}' + d['function'] + '(-' + d['variable'] + ')=' + fx + r'\text{ 恒成立}'
        discussion.append(case + reason)
        single = isinstance(region, sp.FiniteSet)
        results.append(case + (r'\text{无解}' if accepted == sp.S.EmptySet else
                               (r'\text{满足}' if single else r'\text{都满足}') if accepted == region
                               else _range_latex(p, accepted)))
    return discussion, results, feasible


def _sqrt_latex(inside):
    return '0' if inside == 0 else r'\sqrt{' + latex(inside) + '}'


def _radical_verify(d, comparison, relations):
    x, p = math.symbols(d)
    f, name = d['function'], d['variable']
    src = comparison['source']
    feasible = math.aggregate(d, comparison)['feasible_set']
    given, checks = [], []
    for region, text, valid in _radical_cases(d, comparison):
        accepted = feasible & region
        if not valid or accepted == sp.S.EmptySet:
            continue
        case = _range_latex(p, accepted) + r'\text{ 时，}'
        given.append(case + 'D=' + text)
        if text == r'\{0\}':
            checks.append(case + f'{f}(0)=0')
        elif isinstance(accepted, sp.FiniteSet) and len(accepted) == 1:
            inside = sp.expand((src['alpha']*x**2 + src['beta']).subs(p, next(iter(accepted))))
            given.append(case + f'{f}({name})=' + _sqrt_latex(inside))
            checks.append(case + f'{f}(-{name})=' + _sqrt_latex(inside.subs(x, -x)))
        else:
            return None
    checks.append(r'\Rightarrow\ ' + r'\text{、}'.join(relations))
    return given, checks, feasible


def _components_latex(components, x):
    if not components:
        return r'\varnothing'
    if all(c['left'] == c['right'] for c in components):
        return latex(sp.FiniteSet(*(c['left'] for c in components)))
    if (components[0]['left'] == -sp.oo and components[-1]['right'] == sp.oo
            and all(a['right'] == b['left'] and not a['right_closed'] and not b['left_closed']
                    for a, b in pairwise(components))):
        return _holes_latex(sorted({c['right'] for c in components[:-1]}, key=sp.default_sort_key), x)
    return r'\cup '.join(latex(sp.FiniteSet(c['left'])) if c['left'] == c['right'] else
                        ('[' if c['left_closed'] else '(') + latex(c['left']) + ',' + latex(c['right'])
                        + (']' if c['right_closed'] else ')') for c in components)


def _domain_results(d, proof, *, reflected=False):
    _, p = math.symbols(d)
    if proof['kind'] == 'radical':
        cases = _radical_cases(d, proof)
    else:
        grouped = {}
        for row in proof['rows']:
            shown = ({**row, 'input_atoms': [{**a, 'member': a['reflected_member']} for a in row['input_atoms']]}
                     if reflected else row)
            text = _components_latex(math.domain_components(shown, p), d['variable'])
            key = (text, row['valid'])
            grouped[key] = grouped.get(key, sp.S.EmptySet) | row['parameter_cell']
        cases = [(region, text, valid) for (text, valid), region in grouped.items()]
    name = '-D=' if reflected else 'D='
    return [('' if len(cases) == 1 else _range_latex(p, region) + r'\text{ 时，}') + name + text
            + ('' if valid else r'\text{，原式在要求范围内无意义或区间不成立，排除}')
            for region, text, valid in cases]


def _domain_lines(d, proof):
    src = proof['source']
    lines = _domain_results(d, proof)
    if src['kind'] == 'radical':
        x, _ = math.symbols(d)
        return [latex(src['alpha']*x**2 + src['beta']) + r'\ge0', *lines]
    # A guard may only be stated globally when every input branch has it.
    guards = set.intersection(*(set(row['guards']) for row in src['parts'])) if src['parts'] else set()
    return ([r',\ '.join(latex(g) + r'\ne0' for g in sorted(guards, key=sp.default_sort_key))] if guards else []) + lines


def _substituted(src, x, p, value, sign=1):
    n, den = (sp.expand(src['parts'][0][k].subs({p: value, x: sign*x})) for k in ('numerator', 'denominator'))
    shown = latex(n) if den == 1 else r'\frac{' + latex(n) + '}{' + latex(den) + '}'
    simple = latex(sp.cancel(n/den))
    return shown + ('' if simple == shown else '=' + simple)


def _scope_latex(scope, x):
    if isinstance(scope, sp.FiniteSet):
        return x + '=' + latex(next(iter(scope)))
    low, high = scope.start, scope.end
    if low == -sp.oo:
        return x + '<' + latex(high)
    if high == sp.oo:
        return x + '>' + latex(low)
    return latex(low) + '<' + x + '<' + latex(high)


def _reflected_scope(scope):
    if isinstance(scope, sp.FiniteSet):
        return sp.FiniteSet(*(-v for v in scope))
    return sp.Interval.open(-scope.end, -scope.start)


def _signed(sign, value):
    if sign == 1:
        return latex(value)
    return '-' + (latex(value) if value.is_Atom else '(' + latex(value) + ')')


def _parameter_conditions(equations, p):
    lines = []
    for e in equations:
        roots = sp.solve(e, p)
        lines.append(r'\text{ 或 }'.join(f'{p}=' + latex(r) for r in roots) if roots and e.is_polynomial(p)
                     else latex(e) + '=0')
    return lines or [r'\text{对所有参数都成立}']


def _segment_comparison(d, proof):
    """Per input segment f(-x) against ±f(x) when no parameter case is excluded."""
    if proof['kind'] != 'rational_cells':
        return None
    rows = proof['rows']
    if not all(r['valid'] and r['nonempty'] and r['symmetric'] for r in rows):
        return None
    if len({tuple(r['equations']) for r in rows}) != 1:
        return None
    x, p = math.symbols(d)
    atoms = rows[0]['input_atoms']
    if any(atom[k].has(p) for atom in atoms for k in ('point', 'left', 'right') if k in atom):
        return None
    parts, name, f = proof['source']['parts'], d['variable'], d['function']
    signs = sorted({s for fact in d['parity_facts'] for s in math.base.PROPERTIES[fact['property']]})
    lines = []
    for atom in sorted(atoms, key=lambda a: a['kind'] == 'point'):
        if not atom['member'] or atom['branch'] is None or atom['reflected_branch'] is None:
            continue
        own, other = (parts[atom[k]]['numerator'] / parts[atom[k]]['denominator']
                      for k in ('branch', 'reflected_branch'))
        q = domains.atom_point(atom, p, rows[0]['sample'])
        if q < 0:
            continue
        for sign in signs:
            target = ('' if sign == 1 else '-') + f
            if atom['kind'] == 'point':
                if q == 0 and sign == 1:
                    continue
                left, right = sp.cancel(other.subs(x, -q)), sp.cancel(own.subs(x, q))
                if q == 0:
                    line = (f'{name}=0' + r'\text{：}' + f'{f}(0)=-{f}(0)' + r'\Rightarrow ' + f'{f}(0)=0'
                            + r'\Rightarrow ' + latex(right) + '=0')
                else:
                    residual = sp.cancel(left - sign*right)
                    line = (f'{f}({latex(-q)})={target}({latex(q)})' + r'\text{：}' + latex(left) + '='
                            + _signed(sign, right)
                            + (r'\ \text{恒成立}' if residual == 0 else r'\Rightarrow ' + latex(residual) + '=0'))
            else:
                scope = sp.Interval.open(atom['left'], atom['right'])
                left, right = sp.cancel(other.subs(x, -x)), sp.cancel(own)
                lines.append(_scope_latex(scope, name) + r'\text{ 时，}'
                             + _scope_latex(_reflected_scope(scope), '-' + name) + r'\text{：}')
                head = f'{f}(-{name})=' + latex(left)
                if sp.cancel(left - sign*right) == 0:
                    line = head + ('' if left == sign*right and sign == 1 else '=' + _signed(sign, right)) \
                        + f'={target}({name})'
                else:
                    line = head + r',\ ' + f'{target}({name})=' + _signed(sign, right)
            lines.append(line)
    return lines, _parameter_conditions(rows[0]['equations'], p)


def _cases(rows, x):
    if len({e for _, e in rows}) == 1:
        return latex(rows[0][1])
    return (r'\begin{cases}' + r'\\'.join(latex(e) + ',&' + _scope_latex(s, x) for s, e in rows)
            + r'\end{cases}')


def _substitution_lines(d, comparison, solution, relations):
    """Substituted function and domain, then the checked relation."""
    x, p = math.symbols(d)
    f, name = d['function'], d['variable']
    src = comparison['source']
    parts = src['parts']
    single = all(row['numerator'] == parts[0]['numerator'] and row['denominator'] == parts[0]['denominator']
                 for row in parts)
    many = len(solution) > 1
    given, checks = [], []
    for value in sorted(solution):
        prefix = d['parameter'] + '=' + latex(value) + r'\text{ 时，}' if many else ''
        if single:
            own, mirrored = _substituted(src, x, p, value), _substituted(src, x, p, value, -1)
        else:
            body = {row['scope']: sp.cancel((row['numerator']/row['denominator']).subs(p, value)) for row in parts}
            if any(_reflected_scope(s) not in body for s in body):
                return None
            own = _cases([(s, sp.expand(e)) for s, e in body.items()], name)
            own_mirror = [(s, sp.expand(body[_reflected_scope(s)].subs(x, -x))) for s in body]
            mirrored = _cases(own_mirror, name)
        given += [prefix + f'{f}({name})=' + own]
        given.append(prefix + 'D=' + latex(math.domain_at(d, comparison, value)))
        checks.append(prefix + f'{f}(-{name})=' + mirrored)
    checks.append(r'\Rightarrow\ ' + r'\text{、}'.join(relations))
    return given, checks


def phase_views(values):
    from .parity_parameter_presentation import _display_ast, _read
    from .parity_parameter_runtime import domain_decides
    d, phase = values['description'], values['phase']
    x, p, f = d['variable'], d['parameter'], d['function']
    original = _lines(source_lines(d))
    evidence = values['evidence']
    proof = evidence if phase in ('domain', 'compare') else evidence['comparison'] if phase in ('solve', 'verify') else None
    computed = _domain_results(d, proof) if proof is not None else None
    known = _lines(source_lines(d, computed))
    decided = domain_decides(d)
    signs = sorted({s for fact in d['parity_facts'] for s in math.base.PROPERTIES[fact['property']]})
    relations = [f'{f}(-{x})=' + ('-' if s < 0 else '') + f'{f}({x})' for s in signs]
    if phase == 'domain':
        lines = _domain_lines(d, evidence)
        cards = [_read('求定义域', f'先求 ${f}({x})$ 的定义域。', '原题条件', original, '定义域',
                       _lines(lines), _lines(lines))]
        if decided:
            model = math.solve(d)
            symmetric = model['domain_parameters']
            given = _lines([*source_lines(d, computed), r'\Rightarrow\ \text{定义域关于原点对称}'])
            cards.append(_choice('检查定义域是否关于原点对称',
                                 f'奇函数和偶函数的定义域都关于原点对称。要使这个定义域关于原点对称，${p}$ 应满足什么？',
                                 given, symmetric, [sp.S.Reals, sp.S.Reals-symmetric, sp.S.EmptySet],
                                 _lines([*computed, *_domain_results(d, evidence, reflected=True),
                                         r'D=-D\ \Rightarrow\ ' + p + r'\in ' + latex(symmetric)]),
                                 p, '原题条件'))
        return cards
    if phase == 'identity':
        signs = sorted({s for fact in d['parity_facts'] for s in math.base.PROPERTIES[fact['property']]})
        relations = [f'{f}(-{x})=' + ('-' if s < 0 else '') + f'{f}({x})' for s in signs]
        substituted = f'{f}(-{x})=' + expression_latex(reflect_ast(_display_ast(d['expression_ast'])), x)
        src = math.source(d)
        if src['kind'] == 'radical':
            variable, _ = math.symbols(d)
            same = substituted + '=' + _sqrt_latex(src['alpha']*variable**2 + src['beta']) + f'={f}({x})'
            return [_read('把相反数代入原式', f'把 $-{x}$ 代入根式，和 ${f}({x})$ 比较。', '原题条件', known,
                          '代入结果', same, _lines([same, *relations]))]
        return [_read('按原式配对函数值', '把相反数作为整体代入；分段函数要重新判断相反输入落在哪一段。',
                      '原题条件', known, '完整定义域内的关系', _lines(relations),
                      _lines([substituted, *relations, r'\text{只在两个输入都合法时比较，零点也要单独核对}']))]
    if phase == 'compare' and values['evidence']['kind'] == 'radical':
        from .parity_parameter_presentation import compare_view
        discussion, results, _ = _radical_results(d, values['evidence'])
        return [compare_view('分情况讨论', f'按定义域分情况，检查每种情况下 ${relations[0]}$ 能否成立。',
                             known, discussion, '各情况的结论', _lines(results),
                             relation_label='原题条件', rows_label='分情况讨论')]
    if phase == 'compare' and (segments := _segment_comparison(d, values['evidence'])):
        from .parity_parameter_presentation import compare_view
        rows, conditions = segments
        return [compare_view('分类检查函数值关系',
                             f'按输入所在的段，把 ${relations[0]}$ 两边逐段比较；单独的点直接代入。',
                             _lines(rows), rows, '参数条件', _lines(conditions),
                             relation_label='逐段比较', rows_label='逐段比较')]
    if phase == 'compare':
        lines = _comparison_lines(d, values['evidence'])
        return [_read('分类检查函数值关系', '先检查域，再在每一段比较完整恒等条件；临界参数、孤立点和分段端点分别核对。',
                      '原题条件', known, '全部分类条件', _lines(lines), _lines(lines))]
    model = values['evidence']
    solution = model['feasible_set']
    conditions = [condition_value_latex(c) for c in model['conditions']]
    if model['exclusive']:
        conditions.append(p + r'\notin ' + latex(model['zero_set']) + r'\quad\text{排除恒为零的情形}')
    proof = _lines([p + r'\in ' + latex(model['parity_set']), *conditions, p + r'\in ' + latex(solution)])
    radical = model['comparison']['kind'] == 'radical'
    if phase == 'solve' and radical:
        _, results, _ = _radical_results(d, model['comparison'])
        restrictions = [condition_value_latex(c) for c in model['conditions'] if c is not sp.true]
        pieces = list(solution.args) if isinstance(solution, sp.Union) else []
        return [_choice('取并集', '把各种情况得到的参数合在一起。', _lines([*results, *restrictions]), solution,
                        [sp.FiniteSet(0), *pieces, sp.Interval.open(-sp.oo, 0), sp.S.Reals, sp.S.EmptySet],
                        _lines([*results, p + r'\in ' + latex(solution)]), p, '各情况的结论')]
    if radical and solution != sp.S.EmptySet and (checked := _radical_verify(d, model['comparison'], relations)):
        from .parity_parameter_presentation import _read as read_card
        given, checks, _ = checked
        return [read_card('代回核验', '把各种情况的参数分别代回原式检查。', '代入参数', _lines(given),
                          '检验', _lines(checks), _lines([*given, *checks, p + r'\in ' + latex(solution)]))]
    if phase == 'solve':
        segments = _segment_comparison(d, model['comparison'])
        found = segments[1] if segments else _comparison_lines(d, model['comparison'])
        return [_choice('合并全部参数条件', '把域、各段函数值关系、原参数限制及排他要求同时满足的参数保留下来。',
                        _lines([*found, *conditions]), solution,
                        [sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0), model['domain_parameters'], model['zero_set']], proof, p)]
    if (isinstance(solution, sp.FiniteSet) and solution != sp.S.EmptySet
            and model['comparison']['kind'] == 'rational_cells'):
        from .parity_parameter_presentation import substitution_view
        if lines := _substitution_lines(d, model['comparison'], solution, relations):
            given, checks = lines
            if model['exclusive']:
                checks.insert(-1, f'{f}({x})' + r'\text{ 不恒为零}')
            return [substitution_view(d, solution, given, checks)]
    return [_read('按原式代回核验', '把求出的参数代回原式检查。',
                  '原题条件', known, '最终参数集合', latex(solution), proof)]


def attach_graphs(part, values):
    if values['phase'] != 'verify':
        return
    from .parity_parameter_graphs import solution_graph
    graph = solution_graph(values['description'], values['evidence'])
    if graph:
        part['completion_graph'] = graph
