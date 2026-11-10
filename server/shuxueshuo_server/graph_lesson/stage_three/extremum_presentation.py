"""Goal-oriented extrema cards; generated from verified certificates, never IDs."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from .absolute_graph_presentation import choice_card
from .evaluation_presentation import _lines
from .math_values import latex
from .range_presentation import _card
from .trajectory import decode_value
from .extremum_graphs import (
    certificate_graph, coverage_range_lines, endpoint_competition_graph,
    graph_for, illustrated_proof_graph, proof_graph, proof_monotone_direction,
)
from .interaction_graphs import GraphUnavailable, representative_parameter
from ..extremum_math import parameter_inputs, condition_set


def arrow(d):
    return {1: r'\uparrow', -1: r'\downarrow', 0: r'\rightarrow\;\text{常值}'}[d]


def card(title, question, left, right, wrong=(), *, left_label='已知与当前范围', right_label='本步结论'):
    return choice_card(title, question, left_label, left, right_label, right, list(wrong), _lines([left, right]))


def _tag(view, key, title):
    """Mark a view so walk can split one compiled interaction into student-facing cards."""
    view['card_group'] = key
    view['card_group_title'] = title
    return view


def interval_text(b):
    return ('[' if b['left_closed'] else '(')+latex(b['low'])+','+latex(b['high'])+(']' if b['right_closed'] else ')')


def _source_name(cert):
    source = cert['function'].get('source') or ''
    return source.split('(')[0].strip() if source else ''


def side_names(u_cert, v_cert):
    """Bind student-facing names: prefer stem names; otherwise invent g / f."""
    uname, vname = _source_name(u_cert), _source_name(v_cert)
    taken = {n for n in (uname, vname) if n}

    def invent(preferred, fallbacks):
        for candidate in (preferred, *fallbacks):
            if candidate not in taken:
                taken.add(candidate)
                return candidate
        raise ValueError('extremum.side_alias_exhausted')

    # Match common stem order: ∀-side as g, ∃-side as f (A07-style).
    if not uname:
        uname = invent('g', 'hfk')
    if not vname:
        vname = invent('f', 'hgk')
    return uname, vname


def side_name(cert, role):
    name = _source_name(cert)
    if name:
        return name
    return 'g' if role == 'universal' else 'f'


def name_tex(name):
    return name if name.isascii() and name.replace('_', '').isalnum() else rf'\text{{{name}}}'


def values_tex(vals):
    if len(vals) == 2:
        return (r'\{'+latex(vals[0])+r'\}' if vals[0] == vals[1]
                else '['+latex(vals[0])+','+latex(vals[1])+']')
    return latex(vals[0])


def function_text(cert, *, role=None, alias=None):
    fn = cert['function']
    x = sp.Symbol(fn['variable'], real=True)
    source = (fn.get('source') or '').split('(')[0].strip()
    if source:
        name = source
    elif alias:
        name = alias
    elif role in ('universal', 'existential'):
        name = side_name(cert, role)
    else:
        name = 'H'
    rows = cert['proofs']
    if len(rows) == 1:
        expr = latex(sp.expand(rows[0]['expression']))
    else:
        expr = r'\begin{cases}' + r'\\'.join(
            latex(sp.expand(r['expression']))+r',&'+latex(x)+r'\in'+interval_text(r['bounds']) for r in rows) + r'\end{cases}'
    return rf'{name_tex(name)}({latex(x)})={expr}'


def proof_lines(proof, name=None):
    """Expression + domain; name prefixes as f(x)=… so the bare formula is not repeated."""
    x, expr = proof['variable'], latex(sp.expand(proof['expression']))
    head = rf'{name_tex(name)}({latex(x)})={expr}' if name else expr
    return [head, latex(x)+r'\in'+interval_text(proof['bounds'])]


def proof_text(proof, name=None):
    return _lines(proof_lines(proof, name))


def _vertex_tex(a, h, k, x):
    """Vertex form without a leading 1 or a trailing +0."""
    coefficient = '' if a == 1 else '-' if a == -1 else latex(a)
    form = coefficient+r'\left('+latex(x-h)+r'\right)^2'
    if k != 0:
        form += ('+' if not k.could_extract_minus_sign() else '')+latex(k)
    return form


def square_view(proof, title, name=None):
    x, expr = proof['variable'], proof['expression']
    if not expr.is_polynomial(x) or sp.degree(expr, x) != 2:
        return None
    poly = sp.Poly(expr, x)
    a, b, c = (poly.nth(i) for i in (2, 1, 0))
    h, k = -b/(2*a), sp.cancel(c-b*b/(4*a))
    form = _vertex_tex(a, h, k, x)
    # Plausible wrong shapes; still omit bare coefficient 1 / trailing +0.
    wrong = [_vertex_tex(a, -h, k + 1 if k + 1 != 0 else sp.Integer(1), x), latex(sp.expand(expr + 1))]
    if name:
        call = rf'{name_tex(name)}({latex(x)})='
        form = call + form
        wrong = [call + item for item in wrong]
    return card(title+'：配成顶点式', '先配方，确认对称轴与开口，再讨论题目允许的输入范围。',
                proof_text(proof, name), form, wrong, right_label='顶点式')


def _endpoint_diff_tex(name, low, high, left_val, right_val):
    fn = name_tex(name)
    return rf'{fn}({latex(high)})-{fn}({latex(low)})={latex(sp.factor(right_val - left_val))}'


def _endpoint_compare_card(title, name, proof, left_val, right_val, low, high, *, graph=None):
    """Name both endpoint values before asking for their difference."""
    fn = name_tex(name)
    left_pt, right_pt = latex(low), latex(high)
    answer = _endpoint_diff_tex(name, low, high, left_val, right_val)
    premises = _lines([
        *proof_lines(proof, name),
        rf'{fn}({left_pt})={latex(left_val)}',
        rf'{fn}({right_pt})={latex(right_val)}',
    ])
    wrong = [
        rf'{fn}({right_pt})-{fn}({left_pt})={latex(right_val + left_val)}',
        rf'{fn}({left_pt})-{fn}({right_pt})={latex(sp.factor(left_val - right_val))}',
    ]
    view = card(
        title+'：比较二次函数两端',
        '开口向上时，先写出两端的函数值再相减；差的符号决定最大值落在哪一侧。',
        premises, answer, wrong, right_label='两端函数值之差')
    return _attach_range_graphs(view, graph)


def _coverage_case(m):
    for case in m['cases']:
        if case['answer'] != sp.S.EmptySet:
            return case
    return m['cases'][0]


def _range_kind(m):
    if m['operator'] == '=':
        return '值域'
    return '最大值' if m['operator'] in ('<', '<=') else '最小值'


def _range_answer(vals, kind):
    return values_tex(vals) if kind == '值域' else latex(vals[0])


def _piece_extremum_vals(cert, proof_index, kind):
    """Attained extremum on one proof piece (open endpoints that are not attained are dropped)."""
    attained = [c for c in cert['candidates']
                if c['proof'] == proof_index and c['attained'] != sp.S.EmptySet]
    pool = attained or [c for c in cert['candidates'] if c['proof'] == proof_index]
    if not pool:
        raise ValueError('extremum.piece_candidates')
    values = [c['value'] for c in pool]

    def sort_key(value):
        if value.is_number:
            return (0, float(value))
        return (1, sp.default_sort_key(value))

    best = max(values, key=sort_key) if kind == '最大值' else min(values, key=sort_key)
    return [best]


def _param_case_tex(p, region):
    """Compact student-facing condition for one parameter branch."""
    if region is None or region == sp.S.Reals:
        return ''
    if isinstance(region, sp.FiniteSet) and len(region) == 1:
        return rf'{latex(p)}={latex(next(iter(region)))}'
    return rf'{latex(p)}\in {latex(region)}'


def _param_relation_tex(p, region):
    """Inequality / equality form on p (prefer a>0 over a\\in(0,∞))."""
    if region == sp.S.EmptySet:
        return r'\varnothing'
    if region == sp.S.Reals:
        return rf'{latex(p)}\in \mathbb R'
    if isinstance(region, sp.FiniteSet) and len(region) == 1:
        return rf'{latex(p)}={latex(next(iter(region)))}'
    try:
        return latex(region.as_relational(p))
    except (AttributeError, ValueError, TypeError):
        return rf'{latex(p)}\in {latex(region)}'


def _param_answer_tex(p, region):
    """Student-facing parameter answer: always name p (bare ∅ when empty)."""
    return _param_relation_tex(p, region)


def _param_answer_wrongs(p, *regions):
    """Common bare-set distractors rewritten with the parameter name."""
    seen, out = set(), []
    for region in regions:
        text = _param_answer_tex(p, region) if not isinstance(region, str) else region
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _slope_param_option(coeff, direction, p, active):
    """Option for slope→parameter; cell names p even when coeff is e.g. a-2."""
    rel = {1: '>', 0: '=', -1: '<'}[direction]
    solved = _param_relation_tex(p, active)
    # Bare parameter as slope: just a>0 / a=0 / a<0.
    if sp.simplify(sp.expand(coeff - p)) == 0:
        return solved
    return rf'{latex(coeff)}{rel}0\Rightarrow {solved}'


def _slope_param_wrongs(coeff, direction, p, active, allowed):
    wrong = []
    for other_dir, comparison in ((1, sp.Gt), (0, sp.Eq), (-1, sp.Lt)):
        if other_dir == direction:
            continue
        other = condition_set(comparison(coeff, 0), p) & allowed
        if other == sp.S.EmptySet:
            continue
        text = _slope_param_option(coeff, other_dir, p, other)
        if text != _slope_param_option(coeff, direction, p, active):
            wrong.append(text)
    for extra in (_param_relation_tex(p, allowed), r'\varnothing', rf'{latex(p)}\in \mathbb R'):
        if extra not in wrong and extra != _slope_param_option(coeff, direction, p, active):
            wrong.append(extra)
    return wrong


def _case_suffix(p, region):
    # Prefer a≥0 over a∈[0,∞) so path chrome and titles stay compact.
    if region is None or region == sp.S.Reals:
        return ''
    tex = _param_relation_tex(p, region)
    if not tex or tex == r'\varnothing':
        return ''
    return rf'（${tex}$）'

def _specialize_bounds(vals, branch, p):
    """When the branch fixes the parameter, substitute so a=0 shows {{-1}} not {{-a-1}}."""
    if isinstance(branch, sp.FiniteSet) and len(branch) == 1:
        point = next(iter(branch))
        return [sp.simplify(value.subs(p, point)) for value in vals]
    return list(vals)


def _range_distractors(vals, kind):
    """Keep at most two clear distractors: swapped ends, or a singleton endpoint."""
    answer = _range_answer(vals, kind)
    wrong = []
    if kind == '值域' and len(vals) == 2 and vals[0] != vals[1]:
        swapped = '['+latex(vals[1])+','+latex(vals[0])+']'
        if swapped != answer:
            wrong.append(swapped)
        singleton = r'\{'+latex(vals[0])+r'\}'
        if singleton != answer:
            wrong.append(singleton)
    elif len(vals) >= 1:
        alt = latex(vals[0] + 1) if vals[0].is_number else latex(-vals[0])
        if alt != answer:
            wrong.append(alt)
    return wrong[:2]


def _bounds_for_branch(m, role, branch):
    key = 'u_bounds' if role == 'universal' else 'v_bounds'
    for case in m['cases']:
        if case['branch'] == branch or case['branch'] & branch == case['branch']:
            return case[key]
    for case in m['cases']:
        if case['branch'] & branch != sp.S.EmptySet:
            return case[key]
    return m['cases'][0][key]


def _cases_range_tex(rows, p, kind):
    lines = []
    for branch, vals in rows:
        answer = _range_answer(_specialize_bounds(vals, branch, p), kind)
        if answer.lstrip().startswith('['):
            answer = '{'+answer+'}'
        lines.append(rf'{answer},& {_param_case_tex(p, branch)}')
    return r'\begin{cases}' + r'\\'.join(lines) + r'\end{cases}'


def _bounds_vary(rows):
    """True when case bounds are not the same expression across branches."""
    if len(rows) <= 1:
        return False
    first = rows[0][1]
    for _, vals in rows[1:]:
        if len(vals) != len(first):
            return True
        if any(sp.simplify(a - b) != 0 for a, b in zip(vals, first)):
            return True
    return False


def _range_line_for_side(name_tex_value, kind, rows, p):
    """One line if bounds are shared; otherwise a cases brace keyed by the parameter branch."""
    label = name_tex_value+r'\text{ 的'+kind+'}='
    if not rows:
        return label+r'\varnothing'
    if not _bounds_vary(rows):
        branch, vals = rows[0]
        return label+_range_answer(_specialize_bounds(vals, branch, p), kind)
    return label+_cases_range_tex(rows, p, kind)


def _range_cases_distractors(rows, p, kind):
    """Wrong piecewise ranges: drop a branch or swap values across branches.

    Do not use row-order reversal alone: the same cases in another order are
    mathematically identical and look like duplicate options.
    """
    wrong = []
    if len(rows) > 1:
        wrong.append(_cases_range_tex(rows[:-1], p, kind))
        swapped = list(rows)
        (b0, v0), (bn, vn) = swapped[0], swapped[-1]
        swapped[0], swapped[-1] = (b0, vn), (bn, v0)
        wrong.append(_cases_range_tex(swapped, p, kind))
    if len(rows) > 2:
        wrong.append(_cases_range_tex(rows[1:], p, kind))
    return wrong


def _range_cases_summary(label, cert, role, kind, rows, p, *, reason='斜率'):
    """Brace together each branch's range after the case-by-case reads."""
    cases = _cases_range_tex(rows, p, kind)
    premises = _lines([
        function_text(cert, role=role, alias=label),
        *[rf'{_param_case_tex(p, branch)}\Rightarrow {_range_answer(_specialize_bounds(vals, branch, p), kind)}'
          for branch, vals in rows],
    ])
    return card(f'汇总 {label} 在各{reason}下的{kind}',
                f'把刚才分情况得到的{kind}写在一起。',
                premises, cases, _range_cases_distractors(rows, p, kind),
                right_label=f'{label} 的{kind}')


def _side_bound_rows(m, role):
    """Merge parameter cases that share the same extremum / range expression on one side."""
    key = 'u_bounds' if role == 'universal' else 'v_bounds'
    rows = []
    for case in m['cases']:
        vals = case[key]
        for index, (branch, existing) in enumerate(rows):
            if len(existing) == len(vals) and all(sp.simplify(a - b) == 0 for a, b in zip(existing, vals)):
                rows[index] = (branch | case['branch'], existing)
                break
        else:
            rows.append((case['branch'], list(vals)))
    return rows


def _param_partition_tex(p, branches):
    return r'\begin{cases}' + r'\\'.join(_param_case_tex(p, branch) for branch in branches) + r'\end{cases}'


def _endpoint_max_tex(name, low, high, left_val, right_val, bound_val):
    """Say which endpoint wins the max, matching the branch's attained bound."""
    fn = name_tex(name)
    if sp.simplify(sp.expand(bound_val - left_val)) == 0:
        return rf'{fn}_{{\max}}={fn}({latex(low)})'
    if sp.simplify(sp.expand(bound_val - right_val)) == 0:
        return rf'{fn}_{{\max}}={fn}({latex(high)})'
    return rf'{fn}_{{\max}}={latex(bound_val)}'


def _endpoint_partition_answer(name, low, high, left, right, p, bound_rows):
    lines = []
    for branch, vals in bound_rows:
        max_tex = _endpoint_max_tex(name, low, high, left, right, vals[0])
        lines.append(rf'{max_tex},& {_param_case_tex(p, branch)}')
    return r'\begin{cases}' + r'\\'.join(lines) + r'\end{cases}'


def _endpoint_partition_card(title, name, proof, left, right, low, high, p, bound_rows, allowed,
                             *, graph=None):
    """After comparing endpoints, classify a by which end is larger—and name that max."""
    fn = name_tex(name)
    branches = [branch for branch, _ in bound_rows]
    answer = _endpoint_partition_answer(name, low, high, left, right, p, bound_rows)
    swapped = list(bound_rows)
    if len(swapped) > 1:
        (b0, v0), (bn, vn) = swapped[0], swapped[-1]
        swapped[0], swapped[-1] = (b0, vn), (bn, v0)
    wrong = [
        _endpoint_partition_answer(name, low, high, left, right, p, swapped) if len(swapped) > 1 else '',
        _param_partition_tex(p, branches),
        _param_case_tex(p, branches[0]) if branches else '',
        _param_answer_tex(p, allowed),
    ]
    seen, distractors = {answer}, []
    for item in wrong:
        if not item or item in seen:
            continue
        seen.add(item)
        distractors.append(item)
        if len(distractors) == 2:
            break
    view = card(
        title+'：按端点高低分成两类',
        rf'对照虚线 $y={fn}({latex(low if not low.free_symbols else high)})$，'
        rf'看另一端是更高还是更低，把参数一次分成两类，并写出每类的最大值。',
        _endpoint_diff_tex(name, low, high, left, right),
        answer, distractors, right_label=rf'${latex(p)}$ 的分类')
    return _attach_range_graphs(view, graph)


def _specialize_proof_bounds(proof, parameter, sample):
    """Pin a moving endpoint so a schematic graph can be drawn for one branch."""
    if sample is None:
        return proof
    b = proof['bounds']
    low = sp.simplify(b['low'].subs(parameter, sample)) if b['low'].free_symbols else b['low']
    high = sp.simplify(b['high'].subs(parameter, sample)) if b['high'].free_symbols else b['high']
    if low == b['low'] and high == b['high']:
        return proof
    return {**proof, 'bounds': {**b, 'low': low, 'high': high}}


def _piece_extrema_summary(label, cert, role, kind, piece_rows, global_vals, *, graph=None):
    """After per-piece reads, ask for the side extremum; hang the full certificate graph."""
    left = _lines([
        function_text(cert, role=role, alias=label),
        *[rf'\text{{第 {i+1} 段的{kind} }}={_range_answer(vals, kind)}' for i, vals in piece_rows],
    ])
    answer = _range_answer(global_vals, kind)
    wrong = []
    for _, vals in piece_rows:
        text = _range_answer(vals, kind)
        if text != answer and text not in wrong:
            wrong.append(text)
    wrong.extend(v for v in _range_distractors(global_vals, kind) if v != answer and v not in wrong)
    view = card(f'汇总 {label} 的{kind}',
                f'各段的{kind}都求出来后，再取整段上真正的{kind}。',
                left, answer, wrong[:3], right_label=f'{label} 的{kind}')
    return _attach_range_graphs(view, graph)


def _sample_parameter(active):
    try:
        return representative_parameter(active)
    except GraphUnavailable:
        pass
    for guess in (sp.Integer(1), sp.Integer(2), sp.Rational(1, 2), sp.Integer(-1), sp.Integer(-2)):
        if active.contains(guess) is True:
            return guess
    return None


def _attach_range_graphs(view, graph):
    if not graph:
        return view
    view['graph'] = graph
    view['completion_graph'] = deepcopy(graph)
    return view


def _read_range_card(name, cert, role, proof, vals, kind, *, graph=None, branch=None,
                     parameter=None, piece=None, piece_count=1):
    if branch is not None and parameter is not None:
        vals = _specialize_bounds(vals, branch, parameter)
    suffix = _case_suffix(parameter, branch) if branch is not None and parameter is not None else ''
    multi = piece is not None and piece_count > 1
    piece_note = f'：第 {piece+1} 段' if multi else ''
    scope = '本段' if multi else '本区间'
    right = f'{name} 第 {piece+1} 段的{kind}' if multi else f'{name} 的{kind}'
    answer = _range_answer(vals, kind)
    # Focus the active piece only (title already says 第 N 段). Full cases belong
    # on the later summary card—not a lone domain under the whole piecewise.
    left = proof_lines(proof, name)
    if suffix:
        left.append(_param_case_tex(parameter, branch))
    view = card(f'由图像读出 {name} 的{kind}'+piece_note+suffix,
                f'看图中标出的增减方向，直接读出 {name} 在{scope}上的{kind}。',
                _lines(left),
                answer, _range_distractors(vals, kind), right_label=right)
    return _attach_range_graphs(view, graph)


def _coverage_relationship(m, uname, vname):
    u_tex, v_tex = name_tex(uname), name_tex(vname)
    if m['operator'] == '=':
        return rf'{u_tex}\text{{ 的值域 }}\subseteq {v_tex}\text{{ 的值域 }}'
    use_max = m['operator'] in ('<', '<=')
    left_q = r'\max ' if use_max else r'\min '
    rel = {'<': '<', '<=': r'\leq', '>': '>', '>=': r'\geq'}[m['operator']]
    return left_q+u_tex+rel+left_q+v_tex


def _quantified_ranges_full_derivation(m, uname, vname):
    """M7 ranges：读值域／最值的学生 ∵∴ 书写（一张卡组一份）。"""
    kind = _range_kind(m)
    p = m['parameter']
    lines = []
    if m['existential']['nonempty'] != sp.S.Reals:
        lines.append(
            rf'\text{{先使 }}{name_tex(vname)}\text{{ 的输入区间非空：}}'
            + _param_answer_tex(p, m['existential']['nonempty']))
    if m['operator'] != '=':
        lines.append(rf'\text{{需 }}{_coverage_relationship(m, uname, vname)}')
        lines.append(rf'\text{{因此先读出两边的{kind}}}')
    for role, cert, label in (('universal', m['universal'], uname),
                              ('existential', m['existential'], vname)):
        for proof in cert['proofs']:
            xv = proof['variable']
            lines.append(
                rf'{name_tex(label)}({latex(xv)})={_piece_expr_tex(proof)},\ '
                + latex(xv) + r'\in' + interval_text(proof['bounds']))
        rows = _side_bound_rows(m, role)
        if _bounds_vary(rows):
            for branch, vals in rows:
                case_tex = _param_case_tex(p, branch) or rf'{latex(p)}\in {latex(branch)}'
                ans = _range_answer(_specialize_bounds(vals, branch, p), kind)
                lines.append(
                    rf'\because\ {case_tex},\ \therefore\ '
                    + name_tex(label) + r'\text{ 的' + kind + '}=' + ans)
        else:
            branch, vals = rows[0]
            ans = _range_answer(_specialize_bounds(vals, branch, p), kind)
            lines.append(rf'\therefore\ {name_tex(label)}\text{{ 的{kind}}}={ans}')
    return lines


def _quantified_conditions_full_derivation(m, uname, vname):
    """M7 conditions：覆盖关系 → 不等式 → 保留参数。"""
    kind = _range_kind(m)
    p = m['parameter']
    lines = [rf'\because\ \text{{需 }}{_coverage_relationship(m, uname, vname)}']
    multi = len(m['cases']) > 1
    for index, case in enumerate(m['cases'], 1):
        branch_set = case['branch']
        branch = _param_case_tex(p, branch_set) or rf'{latex(p)}\in {latex(branch_set)}'
        ub = _specialize_bounds(case['u_bounds'], branch_set, p)
        vb = _specialize_bounds(case['v_bounds'], branch_set, p)
        cond = sp.And(*case['conditions'])
        if multi:
            lines.append(rf'\text{{情况 }}{index}\ ({branch}):')
        elif branch:
            lines.append(rf'\text{{在 }}{branch}\text{{ 下}}')
        lines.append(name_tex(uname) + r'\text{ 的' + kind + '}=' + _range_answer(ub, kind))
        lines.append(name_tex(vname) + r'\text{ 的' + kind + '}=' + _range_answer(vb, kind))
        cond_tex = _branch_condition_tex(cond, branch_set, p)
        lines.append(rf'\therefore\ {cond_tex}')
        lines.append(rf'\therefore\ {_param_answer_tex(p, case["answer"])}')
    return lines


def _direct_prepare_full_derivation(m, name, x, expr, domain, original):
    if m['family'] == 'fraction':
        op = m['operation']
        sign = '-' if op['scale'] < 0 else '+'
        formula = (
            latex(op['offset']) + sign + r'\frac{'
            + latex(abs(op['scale'])) + '}{' + latex(op['denominator']) + '}')
        return [
            rf'{name_tex(name)}({latex(x)})={latex(expr)},\ {latex(x)}\in {latex(domain)}',
            rf'\text{{分离常数与倒数项}}',
            rf'\therefore\ {name_tex(name)}({latex(x)})={formula}',
        ]
    return [
        rf'{name_tex(name)}({latex(x)})={latex(expr)}',
        rf'\text{{先保留原式有意义的条件}}',
        rf'\therefore\ {latex(x)}\in {latex(domain)}',
    ]


def _direct_children_full_derivation(m, name, x):
    lines = []
    aliases = [n for n in ('g', 'h', 'p', 'q', 'r', 's') if n not in (name, str(x))]
    dir_words = {1: '递增', -1: '递减', 0: '常值'}
    for index, child in enumerate(m['children']):
        alias = aliases[index]
        model = child['model']
        for row in model['partition']:
            branch = model['branches'][row['branch']]
            expr = branch['expression']
            direction = row['direction']
            inner_dir = row.get('inner_direction', direction)
            layers = row.get('layers') or []
            lines.append(
                rf'{name_tex(alias)}({latex(x)})={latex(expr)},\ '
                + latex(x) + r'\in' + latex(row['interval']))
            if expr.is_polynomial(x) and sp.degree(expr, x) == 1:
                slope = sp.Poly(expr, x).nth(1)
                cmp = '>0' if slope > 0 else ('<0' if slope < 0 else '=0')
                lines.append(
                    rf'\because\ \text{{一次项系数 }}{latex(slope)}{cmp}')
                lines.append(
                    rf'\therefore\ {latex(expr)}\;'
                    + arrow(inner_dir) + rf'\text{{（{dir_words[inner_dir]}）}}')
            else:
                lines.append(
                    rf'\therefore\ {latex(expr)}\;'
                    + arrow(inner_dir) + rf'\text{{（{dir_words[inner_dir]}）}}')
            for layer in layers:
                if layer.get('operation') == 'sqrt':
                    lines.append(r'\text{开方在定义域上保序，方向不变}')
                    lines.append(
                        rf'\therefore\ \sqrt{{{latex(expr)}}}\;'
                        + arrow(direction) + rf'\text{{（{dir_words[direction]}）}}')
            if not layers:
                # Rename the inner conclusion to the alias used on the card.
                lines[-1] = (
                    rf'\therefore\ {name_tex(alias)}({latex(x)})\;'
                    + arrow(direction) + rf'\text{{（{dir_words[direction]}）}}')
    return lines


def _direct_operations_full_derivation(m, name, x):
    lines = []
    for cell in m['interval_steps']:
        interval = latex(cell['interval'])
        lines.append(rf'{latex(x)}\in {interval}')
        if m['family'] == 'fraction':
            op = m['operation']
            current = op['denominator']
            for step in cell['operations']:
                before, after = arrow(step['before']), arrow(step['after'])
                if step['operation'] == 'reciprocal':
                    sign = '>0' if step['sign'] == 'positive' else '<0'
                    lines.append(
                        rf'\because\ {latex(current)}{sign}\text{{，取倒数变号}}'
                        + rf'（{before}\to {after}）')
                    current = 1 / current
                elif step['operation'] == 'scale':
                    coef = step['coefficient']
                    flip = '变号' if coef < 0 else '不变号'
                    lines.append(
                        rf'\because\ \text{{乘 }}{latex(coef)}\text{{（{flip}）}}'
                        + rf'（{before}\to {after}）')
                    current *= coef
                else:
                    lines.append(
                        rf'\text{{加常数不改变增减}}（{before}\to {after}）')
                    current += step['coefficient']
                lines.append(rf'\therefore\ {after}')
            lines.append(
                rf'\therefore\ {name_tex(name)}({latex(x)})\;'
                + arrow(cell['direction']) + rf'\text{{ 于 }}{interval}')
        elif m['family'] == 'root_sum':
            a, b = cell['operations'][0]['inputs']
            lines.append(
                rf'\because\ \text{{两项同向 }}{arrow(a)}\text{{ 与 }}{arrow(b)}')
            lines.append(
                rf'\therefore\ \text{{和 }}{arrow(cell["direction"])}'
                + rf'\text{{ 于 }}{interval}')
        else:
            lines.append(
                rf'\therefore\ {name_tex(name)}({latex(x)})\;'
                + arrow(cell['direction']) + rf'\text{{ 于 }}{interval}')
    return lines


def _direct_conclude_full_derivation(m, name, x, expr, domain):
    label = '最大值' if m['quantity'] == 'maximum' else '最小值'
    lines = [
        rf'{name_tex(name)}({latex(x)})={latex(expr)},\ {latex(x)}\in {latex(domain)}']
    for row in m['interval_steps']:
        dir_word = {1: '递增', -1: '递减', 0: '常值'}[row['direction']]
        lines.append(
            rf'\because\ {name_tex(name)}\text{{ 在 }}{latex(row["interval"])}'
            + rf'\text{{ 上{dir_word}}}')
    if m['attained']:
        points = sp.FiniteSet(*m['witnesses'])
        lines.append(rf'\therefore\ {label}\text{{在 }}{latex(points)}\text{{ 取得}}')
        witness = next(iter(m['witnesses']))
        mid = None
        if m['family'] == 'fraction':
            op = m['operation']
            plugged = op['offset'] + op['scale'] / op['denominator'].subs(x, witness)
            mid = latex(plugged)
        value_tex = latex(m['value'])
        call = rf'{name_tex(name)}({latex(witness)})'
        if mid and mid != value_tex:
            lines.append(rf'\therefore\ {call}={mid}={value_tex}')
        else:
            lines.append(rf'\therefore\ {call}={value_tex}')
    else:
        lines.append(rf'\therefore\ \text{{{label}不存在}}')
    return lines


def _alias_confirm_card(u, v, uname, vname):
    """When the stem has no names, just tell the student the aliases—no choice."""
    # lines boards render via data-math-text, so each line needs $…$ / $$…$$.
    # Avoid nested $ inside \\text{…$g$…}.
    formulas = [
        rf'\text{{可以设 }}{name_tex(uname)}\text{{ 和 }}{name_tex(vname)}',
        function_text(u, role='universal', alias=uname),
        function_text(v, role='existential', alias=vname),
    ]
    # lines board (not derivation): inform-only, no blank「下一步 ?」result cell.
    # Inline $…$ stays compact; $$…$$ would open katex-display scrollbars on short lines.
    board = {'caption': '记号', 'lines': ['$'+line+'$' for line in formulas]}
    explanation = _lines(formulas)
    return {
        'title': '先给两边的式子取名',
        'question': '题面没有函数名，先设两个函数，后面用名字讨论。',
        'explanation': explanation,
        'interaction': {'type': 'read'},
        'expected_answer': {},
        'feedback': {'answer': explanation},
        'derivation': board,
        'submit_label': '记下了，继续',
    }


def _inequality_reduce_card(m, uname, vname):
    """Before reading extrema, turn the quantified inequality into a max/min comparison."""
    op = m['operator']
    u_tex, v_tex = name_tex(uname), name_tex(vname)
    sense = {
        '<': f'{uname} 取到的每个值，都要有某个 {vname} 的值比它大',
        '<=': f'{uname} 取到的每个值，都要有某个 {vname} 的值不比它小',
        '>': f'{uname} 取到的每个值，都要有某个 {vname} 的值比它小',
        '>=': f'{uname} 取到的每个值，都要有某个 {vname} 的值不比它大',
    }[op]
    use_max = op in ('<', '<=')
    left_q = r'\max ' if use_max else r'\min '
    other_q = r'\min ' if use_max else r'\max '
    rel = {'<': '<', '<=': r'\leq', '>': '>', '>=': r'\geq'}[op]
    relationship = _coverage_relationship(m, uname, vname)
    wrong = [
        left_q+v_tex+rel+left_q+u_tex,
        other_q+u_tex+rel+other_q+v_tex,
        rf'{u_tex}\text{{ 的值域 }}\subseteq {v_tex}\text{{ 的值域 }}',
    ]
    return card('先把量词关系化成最值比较',
                '原命题要保证什么？先化成对最值的比较，再去读图。',
                rf'\text{{{sense}}}', relationship, wrong,
                right_label='等价的最值关系')


def _inequality_plug_card(m, uname, vname, case):
    """After extrema are known, cite the prior max/min relation and write the concrete inequality."""
    kind = _range_kind(m)
    ub = _specialize_bounds(case['u_bounds'], case['branch'], m['parameter'])
    vb = _specialize_bounds(case['v_bounds'], case['branch'], m['parameter'])
    relationship = _coverage_relationship(m, uname, vname)
    cond = sp.And(*case['conditions'])
    if cond == sp.S.true:
        condition = r'\text{条件恒成立}'
    elif cond == sp.S.false:
        condition = r'\text{条件不成立}'
    else:
        condition = latex(cond)
    u_tex, v_tex = name_tex(uname), name_tex(vname)
    left = _lines([
        rf'\text{{已有 }}{relationship}',
        u_tex+r'\text{ 的'+kind+'}='+_range_answer(ub, kind),
        v_tex+r'\text{ 的'+kind+'}='+_range_answer(vb, kind),
    ])
    flipped = {
        '<': sp.Gt, '<=': sp.Ge, '>': sp.Lt, '>=': sp.Le,
    }[m['operator']](ub[0], vb[0])
    wrong = [latex(flipped),
             rf'{u_tex}\text{{ 的值域 }}\subseteq {v_tex}\text{{ 的值域 }}']
    p = m['parameter']
    return card('代入最值，写出参数条件',
                '沿用前面的最值关系，把两边的最值代进去。',
                left, condition, wrong, right_label=rf'关于 ${latex(p)}$ 的不等式')


def _branch_condition_tex(cond, branch_set, p):
    shown = cond
    if isinstance(branch_set, sp.FiniteSet) and len(branch_set) == 1:
        shown = sp.simplify(cond.subs(p, next(iter(branch_set))))
    if shown == sp.S.true:
        return r'\text{本支覆盖条件恒成立}'
    if shown == sp.S.false:
        return r'\text{本支覆盖条件不成立}'
    return latex(shown)


def _piece_expr_tex(proof):
    """Prefer vertex / cancelled form so B08 keeps (x-a)^2 and a+x+1/x."""
    x, expr = proof['variable'], proof['expression']
    if proof.get('family') == 'reciprocal_sum':
        return latex(sp.apart(sp.cancel(expr), x))
    if expr.is_polynomial(x) and sp.degree(expr, x) == 2:
        poly = sp.Poly(expr, x)
        a_coef, b_coef, c_coef = (poly.nth(i) for i in (2, 1, 0))
        h = sp.cancel(-b_coef / (2 * a_coef))
        k = sp.cancel(c_coef - b_coef * b_coef / (4 * a_coef))
        return _vertex_tex(a_coef, h, k, x)
    return latex(sp.expand(expr))


def _specified_proof_lines(proof, name=None):
    x = proof['variable']
    head = (rf'{name_tex(name)}({latex(x)})={_piece_expr_tex(proof)}'
            if name else _piece_expr_tex(proof))
    return [head, latex(x) + r'\in' + interval_text(proof['bounds'])]


def _specified_function_text(cert):
    fn = cert['function']
    x = sp.Symbol(fn['variable'], real=True)
    name = (fn.get('source') or '').split('(')[0].strip() or 'f'
    rows = cert['proofs']
    if len(rows) == 1:
        expr = _piece_expr_tex(rows[0])
    else:
        expr = (r'\begin{cases}'
                + r'\\'.join(
                    _piece_expr_tex(row) + r',&' + latex(x) + r'\in' + interval_text(row['bounds'])
                    for row in rows)
                + r'\end{cases}')
    return rf'{name_tex(name)}({latex(x)})={expr}'


def _specified_condition_tex(cond, branch_set, p):
    shown = cond
    if isinstance(branch_set, sp.FiniteSet) and len(branch_set) == 1:
        shown = sp.simplify(cond.subs(p, next(iter(branch_set))))
    if shown == sp.S.true:
        return r'\text{本段已满足}'
    if shown == sp.S.false:
        return r'\text{本段不满足}'
    return latex(shown)


def _specified_piece_graph(proof, *, title, parameter, branch, quantity):
    picture = proof_graph(proof, parameter=parameter, branch=branch, quantity=quantity)
    if picture:
        picture = deepcopy(picture)
        if picture.get('params') is not None and title:
            picture['params']['title'] = title
        return picture
    sample = None
    if branch not in (None, sp.S.Reals):
        sample = _sample_parameter(branch)
    if sample is None:
        sample = _sample_parameter(sp.S.Reals)
    if sample is None:
        return None
    return illustrated_proof_graph(proof, title=title, parameter=parameter, sample=sample)


def _specified_plug_mid(proof, point):
    """Visible plug-in before collapsing, e.g. (0-a)^2 or -1/2+1."""
    x, expr = proof['variable'], proof['expression']
    if not expr.is_polynomial(x):
        return None
    degree = sp.degree(expr, x)
    poly = sp.Poly(expr, x)
    if degree == 1:
        slope, intercept = poly.nth(1), poly.nth(0)
        if point == 1:
            mid = latex(slope)
        elif point == -1:
            mid = latex(-slope)
        else:
            mid = latex(slope) + r'\cdot ' + latex(point)
        if intercept != 0:
            mid += ('+' if not intercept.could_extract_minus_sign() else '') + latex(intercept)
        return mid
    if degree != 2:
        return None
    a_coef, b_coef, c_coef = (poly.nth(i) for i in (2, 1, 0))
    h = sp.cancel(-b_coef / (2 * a_coef))
    k = sp.cancel(c_coef - b_coef * b_coef / (4 * a_coef))
    coefficient = '' if a_coef == 1 else '-' if a_coef == -1 else latex(a_coef)
    mid = coefficient + r'\left(' + latex(point) + '-' + latex(h) + r'\right)^2'
    if k != 0:
        mid += ('+' if not k.could_extract_minus_sign() else '') + latex(k)
    return mid


def _specified_point_choice(name, proof, point, value):
    """Highlight which piece is used, then derive f(c): f(x)=… ⇒ f(c)=…."""
    x = proof['variable']
    line1 = (rf'{name_tex(name)}({latex(x)})={_piece_expr_tex(proof)},\ '
             + latex(x) + r'\in' + interval_text(proof['bounds']))
    call = rf'{name_tex(name)}({latex(point)})'
    mid = _specified_plug_mid(proof, point)
    if mid and mid != latex(value):
        line2 = rf'{call}={mid}={latex(value)}'
    else:
        line2 = rf'{call}={latex(value)}'
    return r'\begin{gathered}' + line1 + r'\\' + line2 + r'\end{gathered}'


def _proof_contains_point(proof, point):
    b = proof['bounds']
    return sp.Interval(
        b['low'], b['high'], not b['left_closed'], not b['right_closed']
    ).contains(point) == True


def _active_specified_proof(cert, point):
    proofs = cert['proofs']
    return next((proof for proof in proofs if _proof_contains_point(proof, point)), proofs[0])


def _specified_plug_line(name, proof, point, value):
    """f(c)=… or f(c)=mid=… for the student write-up."""
    call = rf'{name_tex(name)}({latex(point)})'
    mid = _specified_plug_mid(proof, point)
    value_tex = latex(value)
    if mid and mid != value_tex:
        return rf'{call}={mid}={value_tex}'
    return rf'{call}={value_tex}'


def _specified_point_choices(name, cert, point, value):
    """Correct piece + value; distractors: wrong piece, and right piece with wrong value."""
    proofs = cert['proofs']
    active = _active_specified_proof(cert, point)
    answer = _specified_point_choice(name, active, point, value)
    wrongs = []
    for other in proofs:
        if other is active:
            continue
        # Wrong piece: still write an f(c)=… claim so the contrast is the expression chosen.
        try:
            plugged = sp.simplify(sp.cancel(other['expression'].subs(other['variable'], point)))
        except (ValueError, TypeError, ZeroDivisionError):
            plugged = None
        if plugged is None or plugged.has(sp.zoo, sp.oo, -sp.oo) or plugged.is_real is False:
            # Inactive piece may be undefined at the point (e.g. 1/x at 0);
            # still contrast the chosen expression with a plausible wrong reading.
            extras = [s for s in other['expression'].free_symbols if s != other['variable']]
            plugged = extras[0] if len(extras) == 1 else value + 1
        wrongs.append(_specified_point_choice(name, other, point, plugged))
        break
    wrongs.append(_specified_point_choice(name, active, point, value + 1))
    if len(wrongs) < 2:
        wrongs.append(_specified_point_choice(name, active, point, -value))
    return answer, wrongs[:2]


def _branch_outcome_tex(condition_tex, answer_tex):
    """Pair the coverage judgment with the retained parameter set for one choice."""
    return condition_tex + r'\Rightarrow ' + answer_tex


def _coverage_card(m, uname, vname, premises, case):
    """Ask the coverage / comparison after both sides' ranges are known."""
    op, p = m['operator'], m['parameter']
    ub, vb = case['u_bounds'], case['v_bounds']
    u_tex, v_tex = name_tex(uname), name_tex(vname)
    relationship = _coverage_relationship(m, uname, vname)
    if op == '=':
        wrong = [rf'{v_tex}\text{{ 的值域 }}\subseteq {u_tex}\text{{ 的值域 }}',
                 rf'{u_tex}\text{{ 的值域 }}={v_tex}\text{{ 的值域 }}']
        question = (f'正确的包含关系是什么？'
                    f'{uname} 的值域必须被 {vname} 的值域盖住，才能保证 {uname} 取到的每个值，{vname} 都能取到。')
        right_label = '值域覆盖关系'
        quantity = None
    else:
        use_max = op in ('<', '<=')
        left_q = r'\max ' if use_max else r'\min '
        rel = {'<': '<', '<=': r'\leq', '>': '>', '>=': r'\geq'}[op]
        wrong = [left_q+v_tex+rel+left_q+u_tex,
                 rf'{u_tex}\text{{ 的值域 }}\subseteq {v_tex}\text{{ 的值域 }}']
        kind = '最大值' if use_max else '最小值'
        question = f'正确的比较关系是什么？比较两边的{kind}。'
        right_label = f'{kind}比较关系'
        quantity = kind
    # Prefer cases braces when a side's range expression changes with the parameter branch.
    kind_u = '值域' if len(ub) == 2 else quantity
    kind_v = '值域' if len(vb) == 2 else quantity
    u_rows = [(c['branch'], c['u_bounds']) for c in m['cases']]
    v_rows = [(c['branch'], c['v_bounds']) for c in m['cases']]
    left = _lines([
        _range_line_for_side(u_tex, kind_u, u_rows, p),
        _range_line_for_side(v_tex, kind_v, v_rows, p),
        rf'\text{{{uname} 取到的每个值，{vname} 都要能取到}}' if op == '=' else
        rf'\text{{比较两边的{quantity}}}',
    ])
    view = card(f'讨论 {uname} 与 {vname} 的取值关系', question, left, relationship, wrong,
                right_label=right_label)
    # Number lines live on the single-branch setup card only.
    return view


def parameter_views(values):
    m, phase, desc = values['extremum_result'], values['phase'], values['description']
    p = m['parameter']
    quantified = m['task'] == 'quantified'
    views = []
    if quantified:
        _, q, _, _, _ = parameter_inputs(desc)
        uvar, vvar = sp.Symbol(q[2]), sp.Symbol(q[4][2])
        u, v = m['universal'], m['existential']
        uname, vname = side_names(u, v)
        # When the stem has no named functions, these aliases define them for later steps.
        premises = _lines([function_text(u, role='universal', alias=uname),
                           rf'{latex(uvar)}\in'+interval_text(u['bounds']),
                           function_text(v, role='existential', alias=vname),
                           rf'{latex(vvar)}\in'+interval_text(v['bounds'])])
    else:
        cert = m['certificate']
        name = cert['function']['source'].split('(')[0]
        premises = _specified_function_text(cert)
    if phase == 'prepare':
        if quantified:
            # Role-binding cards removed; nonempty checks move to ranges.
            pass
        else:
            point = m['point']
            call = rf'{name_tex(name)}({latex(point)})'
            answer, wrongs = _specified_point_choices(
                name, cert, point, m['specified_value'])
            # 代入求值靠板书分段式，不挂可拖对称轴的探索图。
            views.append(_tag(card(
                '求指定点的函数值',
                '先确定指定最值点落在哪一段，再代入该段表达式；保留原分段端点。',
                _lines([premises, rf'{call}=?']), answer, wrongs,
                right_label='选用的表达式与取值'),
                'prepare', '确定指定最值'))
            op = r'\leq' if m['quantity'] == 'max' else r'\geq'
            x = latex(cert['proofs'][0]['variable'])
            kind = '最大值' if m['quantity'] == 'max' else '最小值'
            views.append(_tag(card(
                '把指定最值写成全域条件',
                f'指定最值等价于定义域上的恒成立：每一点都不比它更'
                + ('大' if m['quantity'] == 'max' else '小')
                + '。后面按段分别求解，再取交集；不必要求只在这一点取到。',
                rf'{name}({latex(m["point"])})={latex(m["specified_value"])}',
                rf'\forall {x}\in D_{{{name}}},\quad {name}({x}){op} {latex(m["specified_value"])}',
                [rf'\exists {x}\in D_{{{name}}},\quad {name}({x}){op} {latex(m["specified_value"])}']),
                'prepare', '确定指定最值'))
            # 完整推导：一张卡组一份 ∵∴ 书写（结论卡仍用上面两卡的短板书）。
            active = _active_specified_proof(cert, point)
            call = rf'{name_tex(name)}({latex(point)})'
            xv = active['variable']
            views[-1]['full_derivation'] = [
                rf'\because\ {latex(point)}\in {interval_text(active["bounds"])}',
                (rf'\therefore\ {name_tex(name)}({latex(xv)})={_piece_expr_tex(active)},\ '
                 + latex(xv) + r'\in' + interval_text(active['bounds'])),
                rf'\therefore\ {_specified_plug_line(name, active, point, m["specified_value"])}',
                rf'\text{{又 }}{call}\text{{ 是函数的{kind}}}',
                (rf'\therefore\ \forall {x}\in D_{{{name}}},\ '
                 + rf'{name_tex(name)}({x}){op} {call}={latex(m["specified_value"])}'),
            ]
    elif phase == 'ranges':
        if quantified:
            kind = _range_kind(m)
            need_piece_extrema = kind in ('最大值', '最小值')

            def side_group(label):
                return f'side_{label}', f'求 {label} 的{kind}'

            def push(view, key, title):
                views.append(_tag(view, key, title))

            if not _source_name(u) or not _source_name(v):
                push(_alias_confirm_card(u, v, uname, vname), 'alias', '先给两边取名')
            if v['nonempty'] != sp.S.Reals:
                nonempty = v['nonempty']
                push(card(f'先保证 {vname} 有输入',
                          f'{vname} 必须能选到输入；先判断其区间什么时候非空。',
                          latex(vvar)+r'\in'+interval_text(v['bounds']),
                          _param_answer_tex(p, nonempty),
                          _param_answer_wrongs(p, sp.S.Reals, sp.S.EmptySet),
                          right_label=rf'使区间非空的 ${latex(p)}$'),
                     'nonempty', '存在域非空')
            # Inequality path: name the max/min comparison before reading extrema.
            if m['operator'] != '=':
                push(_inequality_reduce_card(m, uname, vname), 'reduce', '化归最值比较')
            asked = set()
            for role, cert, label in [('universal', m['universal'], uname),
                                      ('existential', m['existential'], vname)]:
                group_key, group_title = side_group(label)
                piece_count = len(cert['proofs'])
                piece_rows = []
                for i, proof in enumerate(cert['proofs']):
                    piece = f'：第 {i+1} 段' if piece_count > 1 else ''
                    title = f'求 {label} 的{kind}'+piece
                    square = square_view(proof, title, label)
                    if square:
                        push(square, group_key, group_title)
                    x, expr, b = proof['variable'], proof['expression'], proof['bounds']
                    case_split = False
                    if expr.is_polynomial(x):
                        poly = sp.Poly(expr, x)
                        if poly.degree() == 1 and poly.nth(1).has(p):
                            slope_rows = []
                            for direction, comparison in [(1, sp.Gt), (0, sp.Eq), (-1, sp.Lt)]:
                                active = condition_set(comparison(poly.nth(1), 0), p) & m['allowed']
                                if active in (sp.S.EmptySet, m['allowed']):
                                    continue
                                case_split = True
                                # Right cell names the parameter (a); options are inequalities
                                # (a>0, or a-2>0⇒a>2 when the slope coeff is not bare a).
                                dir_note = {1: '（↑）', -1: '（↓）', 0: '（常值）'}[direction]
                                case_note = _case_suffix(p, active)
                                slope_coeff = poly.nth(1)
                                answer = _slope_param_option(slope_coeff, direction, p, active)
                                push(card(title+'：按斜率分类'+dir_note,
                                          f'一次函数看斜率的正、零、负，图像方向不同，值域也不同。',
                                          _lines([*proof_lines(proof, label), r'\text{要使方向为 }'+arrow(direction)]),
                                          answer,
                                          _slope_param_wrongs(slope_coeff, direction, p, active, m['allowed']),
                                          right_label=latex(p)),
                                     group_key, group_title)
                                vals = _bounds_for_branch(m, role, active)
                                slope_rows.append((active, vals))
                                token = (role, i, tuple(_specialize_bounds(vals, active, p)))
                                if token in asked:
                                    continue
                                asked.add(token)
                                sample = _sample_parameter(active)
                                graph = illustrated_proof_graph(
                                    proof, title=f'{label} 的图像'+case_note, direction=direction,
                                    parameter=p, sample=sample)
                                push(_read_range_card(
                                    label, cert, role, proof, vals, kind, graph=graph,
                                    branch=active, parameter=p, piece=i, piece_count=piece_count),
                                     group_key, group_title)
                            if len(slope_rows) > 1:
                                push(_range_cases_summary(label, cert, role, kind, slope_rows, p),
                                     group_key, group_title)
                        if poly.degree() == 2:
                            axis = sp.cancel(-poly.nth(1)/(2*poly.nth(2)))
                            if axis.has(p):
                                inside = condition_set(sp.And(axis > b['low'] if not b['left_closed'] else axis >= b['low'],
                                                              axis < b['high'] if not b['right_closed'] else axis <= b['high']), p)
                                push(card(title+'：判断顶点是否在本段',
                                          '对称轴的位置决定图像在本区间上的形状。',
                                          _lines([*proof_lines(proof, label), latex(x)+'='+latex(axis)]),
                                          _param_answer_tex(p, inside),
                                          _param_answer_wrongs(p, sp.S.Reals, sp.S.EmptySet, sp.S.Reals - inside),
                                          right_label=rf'顶点在本段时的 ${latex(p)}$'),
                                     group_key, group_title)
                            if b['low'].has(p) or b['high'].has(p):
                                left, right = (sp.expand(expr.subs(x, v)) for v in (b['low'], b['high']))
                                compare_graph = endpoint_competition_graph(
                                    proof, name=label, parameter=p, allowed=m['allowed'],
                                    title=f'{label}：两端比较示意')
                                push(_endpoint_compare_card(
                                    title, label, proof, left, right, b['low'], b['high'],
                                    graph=compare_graph),
                                     group_key, group_title)
                                bound_rows = _side_bound_rows(m, role)
                                if len(bound_rows) > 1:
                                    # Classify only; each 求参 branch card carries this side's max
                                    # and plugs the coverage relation—no separate read/summary.
                                    case_split = True
                                    push(_endpoint_partition_card(
                                        title, label, proof, left, right, b['low'], b['high'], p,
                                        bound_rows, m['allowed'],
                                        graph=compare_graph),
                                         group_key, group_title)
                                else:
                                    left_wins = condition_set(sp.Le(right, left), p) & m['allowed']
                                    push(card(title+'：确定左端值不小的情况',
                                              '把端点值的比较与存在域非空条件合并。',
                                              _lines([latex(right-left)+r'\leq 0',
                                                      _param_answer_tex(p, m['allowed'])]),
                                              _param_answer_tex(p, left_wins),
                                              _param_answer_wrongs(p, m['allowed'], sp.S.EmptySet),
                                              right_label=rf'左端更大时的 ${latex(p)}$'),
                                         group_key, group_title)
                    # Concise path: no standalone cubic-direction card; arrows live on the piece graph.
                    if case_split:
                        continue
                    # Single-piece max/min under a fixed parameter region must use the
                    # model's branch bounds (e.g. m<0 ⇒ max(mx+1)=m+1). Constraint-free
                    # max of symbolic candidates picks 3m+1 by expression order.
                    if need_piece_extrema and piece_count > 1:
                        vals = _piece_extremum_vals(cert, i, kind)
                    else:
                        vals = _bounds_for_branch(m, role, m['allowed'])
                    token = (role, i, tuple(vals))
                    if token in asked:
                        continue
                    asked.add(token)
                    direction = proof_monotone_direction(proof)
                    sample = None
                    if expr.is_polynomial(x) and sp.degree(expr, x) == 1 and expr.has(p):
                        for d, comparison in [(1, sp.Gt), (0, sp.Eq), (-1, sp.Lt)]:
                            active = condition_set(comparison(sp.Poly(expr, x).nth(1), 0), p) & m['allowed']
                            if active == m['allowed']:
                                direction, sample = d, _sample_parameter(active)
                                break
                    graph_title = (f'{label} 第 {i+1} 段的图像' if piece_count > 1
                                   else f'{label} 的图像')
                    graph = illustrated_proof_graph(
                        proof, title=graph_title, direction=direction, parameter=p, sample=sample)
                    push(_read_range_card(
                        label, cert, role, proof, vals, kind, graph=graph,
                        piece=i, piece_count=piece_count),
                         group_key, group_title)
                    if need_piece_extrema and piece_count > 1:
                        piece_rows.append((i, vals))
                if need_piece_extrema and len(piece_rows) > 1:
                    global_vals = _bounds_for_branch(m, role, m['allowed'])
                    full = certificate_graph(
                        cert, title=f'{label} 的完整图像',
                        directions=[proof_monotone_direction(pr) for pr in cert['proofs']])
                    push(_piece_extrema_summary(
                        label, cert, role, kind, piece_rows, global_vals, graph=full),
                         group_key, group_title)
            if views:
                views[-1]['full_derivation'] = _quantified_ranges_full_derivation(
                    m, uname, vname)
        else:
            # M8：顶点分类不再作为进子方法前的必答主线；各段经「转化恒成立 → 选解法」进入子方法。
            pass
    elif phase == 'conditions':
        single_branch = quantified and len(m['cases']) == 1
        if quantified and m['operator'] == '=':
            views.append(_coverage_card(m, uname, vname, premises, _coverage_case(m)))
        elif quantified and single_branch:
            # Inequality single-branch: cite prior max/min relation; do not re-ask it.
            views.append(_inequality_plug_card(m, uname, vname, _coverage_case(m)))
        # Multi-branch inequality skips the discussion card; each branch card carries the relation.
        for case in m['cases']:
            branch_set = case['branch']
            branch = _param_case_tex(p, branch_set) or rf'{latex(p)}\in {latex(branch_set)}'
            cond = sp.And(*case['conditions'])
            if quantified and m['operator'] != '=' and single_branch:
                # Plug card already wrote the inequality; only intersect with the ambient restriction.
                condition = latex(cond) if cond not in (sp.S.true, sp.S.false) else (
                    r'\text{全部符合}' if cond == sp.S.true else r'\text{不符合}')
                views.append(card('解参数条件', '与题目原有的参数限制求交，检查等号是否允许。',
                                  _lines([_coverage_relationship(m, uname, vname), condition]),
                                  _param_answer_tex(p, case['answer']),
                                  _param_answer_wrongs(p, branch_set, sp.S.EmptySet, sp.S.Reals),
                                  right_label=rf'保留的 ${latex(p)}$'))
                continue
            if quantified and not single_branch:
                # One card per branch: name this branch's extrema, then plug the relation.
                kind = _range_kind(m)
                ub = _specialize_bounds(case['u_bounds'], branch_set, p)
                vb = _specialize_bounds(case['v_bounds'], branch_set, p)
                condition = _branch_condition_tex(cond, branch_set, p)
                answer = _param_answer_tex(p, case['answer'])
                right = _branch_outcome_tex(condition, answer)
                wrong = []
                for other in m['cases']:
                    if other is case:
                        continue
                    other_cond = _branch_condition_tex(sp.And(*other['conditions']), other['branch'], p)
                    wrong.append(_branch_outcome_tex(other_cond, _param_answer_tex(p, other['answer'])))
                    wrong.append(_branch_outcome_tex(condition, _param_answer_tex(p, other['answer'])))
                wrong.append(_branch_outcome_tex(condition, _param_answer_tex(p, branch_set)))
                if case['answer'] != sp.S.EmptySet:
                    wrong.append(_branch_outcome_tex(condition, r'\varnothing'))
                # Drop duplicates / the correct option; keep two distractors.
                seen, distractors = {right}, []
                for item in wrong:
                    if item in seen:
                        continue
                    seen.add(item)
                    distractors.append(item)
                    if len(distractors) == 2:
                        break
                # Inequality path: this card is the first place the branch max is stated.
                if m['operator'] != '=':
                    question = (f'本支先确认两边的{kind}，再代入比较关系，'
                                f'选出判断并搭配保留的 ${latex(p)}$。')
                else:
                    question = '根据覆盖关系，选出本支的判断，并搭配求交后保留的参数。'
                left = _lines([
                    branch,
                    name_tex(uname)+r'\text{ 的'+kind+'}='+_range_answer(ub, kind),
                    name_tex(vname)+r'\text{ 的'+kind+'}='+_range_answer(vb, kind),
                    _coverage_relationship(m, uname, vname),
                ])
                views.append(card(
                    '求参数'+_case_suffix(p, branch_set),
                    question, left, right, distractors,
                    right_label=rf'本支条件与 ${latex(p)}$'))
                continue
            if not quantified:
                # M8：各段恒成立／分离参数子方法已 expanded；父侧 conditions 不再重复出卡。
                continue
            left = []
            axis_lines = None
            ub, vb = case['u_bounds'], case['v_bounds']
            kind = _range_kind(m)
            left.append(name_tex(uname)+r'\text{ 的'+kind+'}='+_range_answer(ub, kind))
            left.append(name_tex(vname)+r'\text{ 的'+kind+'}='+_range_answer(vb, kind))
            left.append(_coverage_relationship(m, uname, vname))
            axis_lines, _ = coverage_range_lines(
                uname, ub, vname, vb, coverage_label=rf'\text{{对照两端列出不等式}}',
                quantity=None if kind == '值域' else kind)
            setup_title, setup_question = '建立参数条件', '根据覆盖关系，对照数轴上的两端，写出参数应满足的不等式。'
            fit, unfit = r'\text{全部符合}', r'\text{不符合}'
            solve_title, solve_question = '解参数条件', '与题目原有的参数限制求交，检查等号是否允许。'
            solve_label = rf'保留的 ${latex(p)}$'
            default_fit = r'\text{全部符合}' if cond == sp.S.true else r'\text{不符合}'
            condition = latex(cond) if cond not in (sp.S.true, sp.S.false) else default_fit
            setup = card(setup_title, setup_question, _lines(left), condition, [fit, unfit])
            if axis_lines:
                # Two axes only (g and f); no third “coverage” duplicate.
                setup['condition_number_lines'] = axis_lines
            views.append(setup)
            views.append(card(solve_title, solve_question,
                              _lines([_param_answer_tex(p, branch_set), condition]),
                              _param_answer_tex(p, case['answer']),
                              _param_answer_wrongs(p, branch_set, sp.S.EmptySet, sp.S.Reals),
                              right_label=solve_label))
        # Fold into one student-facing 求参数 card with the conclude merge.
        for view in views:
            _tag(view, 'solve', '求参数')
        if quantified and views:
            views[-1]['full_derivation'] = _quantified_conditions_full_derivation(
                m, uname, vname)
    elif phase == 'conclude':
        if quantified:
            left = _lines([_param_answer_tex(p, c['answer']) for c in m['cases']])
            question = '分类结果取并集，再保留题目原有的参数限制。'
        else:
            # Label each piece by its expression／domain, never「第 N 段／左／右侧」.
            proofs = m['certificate']['proofs']
            left_lines = []
            for proof, solution in zip(proofs, m['piece_solutions'], strict=True):
                domain = sp.Interval(
                    proof['bounds']['low'], proof['bounds']['high'],
                    not proof['bounds']['left_closed'], not proof['bounds']['right_closed'])
                label = (rf'{latex(proof["variable"])}\in {latex(domain)}:\ '
                         + latex(proof['expression']))
                left_lines.append(label + r'\Rightarrow ' + _param_answer_tex(p, solution))
            left = _lines(left_lines)
            question = '各段恒成立求出的参数集合取交集；不要求最值点唯一。'
        views.append(card('回到原题，汇总参数范围', question, left,
                          _param_answer_tex(p, m['feasible_set']),
                          _param_answer_wrongs(p, m['allowed'], sp.S.EmptySet, sp.S.Reals),
                          right_label=rf'${latex(p)}$ 的取值范围'))
        # 完整推导：各段结论 → 交/并 → 最终范围；结论卡只留最终答案。
        if quantified:
            merge_lines = []
            for index, case in enumerate(m['cases'], 1):
                branch = _param_case_tex(p, case['branch']) or (
                    rf'{latex(p)}\in {latex(case["branch"])}')
                merge_lines.append(
                    rf'\text{{情况 }}{index}\ ({branch}):\ {_param_answer_tex(p, case["answer"])}')
            merge_lines.append(r'\text{分类结果取并集，再保留题目原有的参数限制}')
            merge_lines.append(rf'\therefore\ {_param_answer_tex(p, m["feasible_set"])}')
        else:
            name = m['certificate']['function']['source'].split('(')[0]
            merge_lines = []
            for proof, solution in zip(m['certificate']['proofs'], m['piece_solutions'], strict=True):
                domain = sp.Interval(
                    proof['bounds']['low'], proof['bounds']['high'],
                    not proof['bounds']['left_closed'], not proof['bounds']['right_closed'])
                xv = proof['variable']
                merge_lines.append(
                    rf'{latex(xv)}\in {latex(domain)}:\ '
                    + rf'{name_tex(name)}({latex(xv)})={_piece_expr_tex(proof)}')
                if solution == sp.S.Reals:
                    merge_lines.append(rf'\therefore\ \text{{对 }}{latex(p)}\text{{ 无额外限制}}')
                elif solution == sp.S.EmptySet:
                    merge_lines.append(r'\therefore\ \text{本段无解}')
                else:
                    merge_lines.append(rf'\therefore\ {_param_answer_tex(p, solution)}')
            if len(m['piece_solutions']) > 1:
                merge_lines.append(r'\text{各段结果取交集}')
            merge_lines.append(rf'\therefore\ {_param_answer_tex(p, m["feasible_set"])}')
        views[-1]['full_derivation'] = merge_lines
        for view in views:
            _tag(view, 'solve', '求参数')
    elif phase == 'independent':
        # Param-free piece (B14 right):
        # 结论卡 = short highlight / completion_board; 完整推导 = ∵/∴ explanation.
        expression = values['independent_expression']
        bound = values['independent_bound']
        operator = values['independent_operator']
        holds = values['independent_holds']
        domain = values['piece_domain']
        variable = values['piece_variable']
        slope = values['independent_slope']
        range_info = values['independent_range']
        key = values['independent_bound_key']
        op_tex = {'<=': r'\leq', '<': '<', '>=': r'\geq', '>': '>'}[operator]
        bound_value = range_info[key]
        name = m['certificate']['function']['source'].split('(')[0]
        call = rf'{name_tex(name)}({latex(variable)})'
        premise = _lines([
            rf'{latex(variable)}\in {latex(domain)}:\ {call}={latex(expression)}',
            rf'\text{{需 }}{call}{op_tex}{latex(bound)}',
        ])
        if holds:
            answer = rf'\text{{对 }}{latex(p)}\text{{ 无额外限制}}'
            wrongs = [
                rf'\text{{整题无解}}',
                rf'\text{{仍需求 }}{latex(p)}\text{{ 的范围}}',
                _param_answer_tex(p, sp.S.EmptySet),
            ]
        else:
            answer = rf'\text{{整题无解}}'
            wrongs = [
                rf'\text{{对 }}{latex(p)}\text{{ 无额外限制}}',
                rf'\text{{仍需求 }}{latex(p)}\text{{ 的范围}}',
                _param_answer_tex(p, sp.S.Reals),
            ]
        view = _tag(card(
            '快速验证本段',
            rf'本段不含 ${latex(p)}$，验证不等式是否恒成立即可。',
            premise, answer, wrongs, right_label='本段结论'),
            'independent', '无参段快速验证')
        view['stem_board'] = {
            'layout': 'derivation', 'caption': '快速验证本段', 'connector': '⇒',
            'items': [
                {'label': '本段条件', 'math': premise},
                {'label': '本段结论', 'math': None},
            ],
        }
        # 结论卡：只保留最重要的结论。
        view['completion_board'] = {
            'layout': 'derivation', 'caption': '本段结论', 'connector': '⇒',
            'items': [
                {'label': '本段条件', 'math': (
                    rf'{call}={latex(expression)}\ ({latex(variable)}\in {latex(domain)})'
                )},
                {'label': '本段结论', 'math': answer},
            ],
        }
        direction = '递减' if slope is not None and slope < 0 else (
            '递增' if slope is not None and slope > 0 else '常值')
        if key == 'sup' and slope is not None and slope < 0 and domain.left.is_finite:
            compare = rf'{call}\le {name_tex(name)}({latex(domain.left)})={latex(bound_value)}'
        elif key == 'inf' and slope is not None and slope > 0 and domain.left.is_finite:
            compare = rf'{call}\ge {name_tex(name)}({latex(domain.left)})={latex(bound_value)}'
        else:
            compare = (
                rf'{call}_{{\text{{上端}}}}={latex(bound_value)}' if key == 'sup'
                else rf'{call}_{{\text{{下端}}}}={latex(bound_value)}'
            )
        if slope is not None and slope != 0:
            mono = (
                rf'\because\ \text{{一次项系数 }}{latex(slope)}'
                + (r'<0' if slope < 0 else r'>0')
                + rf',\ {call}\text{{ 在 }}{latex(domain)}\text{{ 上{direction}}}'
            )
        else:
            mono = rf'{call}={latex(expression)}\quad ({latex(variable)}\in {latex(domain)})'
        verdict = (
            rf'\text{{又需 }}{call}{op_tex}{latex(bound)},\ \text{{该段恒成立}}'
            if holds else
            rf'\text{{又需 }}{call}{op_tex}{latex(bound)},\ \text{{该段不成立}}'
        )
        result_line = (
            rf'\therefore\ \text{{对 }}{latex(p)}\text{{ 无额外限制}}'
            if holds else
            rf'\therefore\ \text{{整题无解}}'
        )
        # 完整推导：学生书写的 ∵/∴ 链（进入 math_step.explanation）。
        view['full_derivation'] = [
            rf'{latex(variable)}\in {latex(domain)}:\ {call}={latex(expression)}',
            mono,
            rf'\therefore\ {compare}',
            verdict,
            result_line,
        ]
        views.append(view)
    else:
        raise ValueError('extremum.unknown_phase')
    return views


def phase_views(values):
    m, phase = values['extremum_result'], values['phase']
    if m['task'] == 'recurrence':
        from .recurrence_extremum_presentation import phase_views as recurrence_views
        return recurrence_views(values)
    views = []
    if m['task'] == 'direct':
        x, expr, domain = m['variable'], m['expression'], m['domain']
        name = values['description']['function']
        original = _lines([rf'{name}({latex(x)})={latex(expr)}', rf'{latex(x)}\in {latex(domain)}'])
        if phase == 'prepare':
            if m['family'] == 'fraction':
                op = m['operation']
                sign = '-' if op['scale'] < 0 else '+'
                formula = latex(op['offset'])+sign+r'\frac{'+latex(abs(op['scale']))+'}{'+latex(op['denominator'])+'}'
                views.append(card('分离分式', '将分式写成常数与一个倒数项，原分母的限制仍要保留。', original,
                                  formula, [latex(op['offset']-op['scale']/op['denominator']), latex(op['offset']+op['scale']*op['denominator'])],
                                  right_label='分离后的式子'))
            else:
                views.append(card('确定最值的研究范围', '先保留原式有意义的条件，再确定讨论最值的范围。', latex(expr), latex(domain),
                                  [r'\mathbb R', r'\varnothing'], right_label='有效输入范围'))
            views[-1]['full_derivation'] = _direct_prepare_full_derivation(
                m, name, x, expr, domain, original)
        elif phase == 'children':
            # Execute the complete M2 child, then reuse only its relevant
            # teaching judgments; extrema do not need a second interval answer.
            from .monotonicity_presentation import phase_views as monotonicity_views
            aliases = [n for n in ('g', 'h', 'p', 'q', 'r', 's') if n not in (name, str(x))]
            for index, child in enumerate(m['children']):
                model = deepcopy(child['model'])
                model['function'] = aliases[index]
                values = {'monotonicity_result': model}
                branch = model['branches'][0]
                child_views = []
                if branch['axis'] is not None:
                    axis, expression = branch['axis'], branch['expression']
                    values['square'] = branch['coefficients'][0]*(x-axis)**2+expression.subs(x, axis)
                    child_views.extend(monotonicity_views({**values, 'phase': 'square'}))
                for child_phase in ('inner', 'composition'):
                    child_views.extend(monotonicity_views({**values, 'phase': child_phase}))
                for view in child_views:
                    for field in ('graph', 'completion_graph'):
                        if view.get(field):
                            graph = view[field]
                            graph['caption'] = graph.get('caption', '').replace('原函数', '辅助函数')
                            graph['params']['title'] = graph['params'].get('title', '').replace('原函数', '辅助函数')
                views.extend(child_views)
            if views:
                views[-1]['full_derivation'] = _direct_children_full_derivation(m, name, x)
        elif phase == 'operations':
            for cell in m['interval_steps']:
                interval = rf'{latex(x)}\in {latex(cell["interval"])}'
                if m['family'] == 'fraction':
                    op = m['operation']
                    current = op['denominator']
                    incoming, outgoing = [sp.Symbol(n) for n in ('u', 'v', 'w', 't')
                                          if n not in (name, str(x))][:2]
                    for step in cell['operations']:
                        title = {'reciprocal': '取倒数后的增减', 'scale': '乘常数后的增减', 'shift': '加常数后的增减'}[step['operation']]
                        before = _lines([interval, latex(incoming)+'='+latex(current)+r'\;'+arrow(step['before'])])
                        if step['operation'] == 'reciprocal':
                            operation, operation_math = '取倒数', latex(outgoing)+'='+latex(1/incoming)
                            before = _lines([before, latex(current)+('>0' if step['sign'] == 'positive' else '<0')])
                            current = 1/current
                        elif step['operation'] == 'scale':
                            operation, operation_math = '乘常数', latex(outgoing)+'='+latex(step['coefficient']*incoming)
                            current *= step['coefficient']
                        else:
                            operation, operation_math = '加常数', latex(outgoing)+'='+latex(incoming+step['coefficient'])
                            current += step['coefficient']
                        view = card(title, '在图示区间和符号条件下，这次运算后增减方向怎样变化？', before,
                                    arrow(step['after']), [arrow(d) for d in (1, -1, 0)], right_label='运算后的方向')
                        view['derivation']['operation'] = {'label': operation, 'math': operation_math}
                        views.append(view)
                elif m['family'] == 'root_sum':
                    a, b = cell['operations'][0]['inputs']
                    terms = [c['expression'] for c in m['children']]
                    terms[0] *= m['operation']['root_scale']
                    left = _lines([interval, latex(terms[0])+r'\;'+arrow(a), latex(terms[-1])+r'\;'+arrow(b)])
                    views.append(card('判断和的增减', '两项使用同一个自变量、同一个区间；把已确认的方向合在一起。',
                                      left, arrow(cell['direction']), [arrow(d) for d in (1, -1, 0)], right_label='和的方向'))
                    views[-1]['derivation']['operation'] = {'label': '两项相加', 'math': arrow(a)+'+'+arrow(b)}
                else:
                    views.append(card('确认当前区间的增减', '结合刚才的基本函数判断，确认本段方向。', original,
                                      arrow(cell['direction']), [arrow(d) for d in (1, -1, 0)]))
            if views:
                views[-1]['full_derivation'] = _direct_operations_full_derivation(m, name, x)
        elif phase == 'conclude':
            label = '最大值' if m['quantity'] == 'maximum' else '最小值'
            directions = _lines([rf'{latex(x)}\in {latex(r["interval"])}\quad {arrow(r["direction"])}' for r in m['interval_steps']])
            points = sp.FiniteSet(*m['witnesses'])
            position = latex(points) if m['attained'] else r'\text{没有能取到该界的输入}'
            wrong = [latex(sp.FiniteSet(c['point'])) for c in m['candidates'] if c['point'].is_finite and c['point'] not in points]
            views.append(card('选择'+label+'的位置', '根据已确认的增减选择位置；先检查这个输入是否允许取到。',
                              _lines([original, directions]), position, [*wrong[:3], r'\text{没有能取到该界的输入}'], right_label='可取得的位置'))
            picture = graph_for(m)
            if picture:
                views[-1]['graph'] = picture
                views[-1]['completion_graph'] = graph_for(m, attained=True)
            output = latex(m['value']) if m['attained'] else r'\text{不存在}'
            views.append(card('求出'+label, '把合法位置代回原式；有限但取不到的界不能叫最值。',
                              _lines([original, rf'{latex(x)}\in {position}' if m['attained'] else position]), output,
                              [latex(m['value']+1), latex(-m['value']), r'\text{不存在}'] if m['value'].is_finite else [r'0', r'1'], right_label=label))
            if picture:
                views[-1]['graph'] = graph_for(m, attained=True)
            views[-1]['full_derivation'] = _direct_conclude_full_derivation(
                m, name, x, expr, domain)
        else:
            raise ValueError('extremum.unknown_phase')
    else:
        return parameter_views(values)
    return views


def presentation(values):
    views = phase_views(values)
    result, phase = values['extremum_result'], values['phase']
    if phase == 'ranges' and result['task'] == 'quantified':
        ranges_title = '由图像读出两边的值域' if result['operator'] == '=' else '由图像读出两边需要的最值'
    elif phase == 'ranges':
        ranges_title = '确定各段的最值候选'
    else:
        ranges_title = None
    if not views:
        title = {'prepare': '准备', 'ranges': ranges_title or '求值域',
                 'conditions': '由覆盖关系求参数条件',
                 'conclude': '合并参数范围'}.get(phase, phase)
        return {'formula_title': title, 'formula_explanation': '$$$$',
                'derivation_caption': title, 'derivation_left_label': '', 'derivation_left_math': '',
                'derivation_left_note': '', 'derivation_right_label': '', 'derivation_right_math': ''}
    view = views[-1]
    title = {'children': '判断辅助函数的增减', 'operations': '判断运算后的增减',
             'ranges': ranges_title, 'conditions': '由覆盖关系求参数条件',
             'conclude': '确定最值与取得位置' if result['task'] == 'direct' else '合并参数范围',
             'independent': view['title']}.get(phase, view['title'])
    if result['task'] == 'recurrence':
        title = view['title']
    # Prefer an explicit student write-up when a view provides one
    # (prepare / conclude / 无参段快速验证).
    if view.get('full_derivation'):
        explanation = '\n'.join(f'${line}$' for line in view['full_derivation'])
    else:
        # Flatten to conclusions only; nesting each card's gathered proof made
        # "完整推导" unreadable. Brace lines that start with '[' so '\\' + '[...]'
        # is not read as \\[vspace].
        conclusions = []
        for v in views:
            board = v['derivation']
            if 'items' not in board:
                continue
            math = board['items'][1].get('math')
            if not math:
                continue
            conclusions.append('{'+math+'}' if math.lstrip().startswith('[') else math)
        explanation = '$$'+_lines(conclusions)+'$$' if conclusions else '$$$$'
    # 结论卡 highlight：无参段用简洁 completion 两侧，否则用最后一卡 derivation。
    board = view.get('completion_board') if phase == 'independent' else view.get('derivation')
    if board and 'items' in board:
        left, right = board['items']
        return {'formula_title': title, 'formula_explanation': explanation,
                'derivation_caption': board.get('caption', title),
                'derivation_left_label': left['label'],
                'derivation_left_math': left['math'], 'derivation_left_note': '',
                'derivation_right_label': right['label'], 'derivation_right_math': right['math']}
    return {'formula_title': title, 'formula_explanation': explanation,
            'derivation_caption': title, 'derivation_left_label': '', 'derivation_left_math': '',
            'derivation_left_note': '', 'derivation_right_label': '', 'derivation_right_math': ''}


def compile_extremum(seeds, interaction_id):
    seed, = seeds
    parts = []
    for index, view in enumerate(phase_views(decode_value(seed['values'])), 1):
        interaction = deepcopy(view['interaction'])
        if 'stem_board' in view and 'completion_board' in view:
            board, completion = deepcopy(view['stem_board']), deepcopy(view['completion_board'])
        else:
            board = deepcopy(view['derivation'])
            # Derivation stems hide the result; lines / inform boards stay as written.
            if board.get('layout') == 'derivation' or 'items' in board:
                board['items'][1]['math'] = None
                completion = view['derivation']
            else:
                completion = deepcopy(board)
        if interaction.get('options'):
            interaction['options'].sort(key=lambda r: sha256(f'{interaction_id}:{index}:{r["value"]}'.encode()).digest())
        submit = view.get('submit_label') or (
            '记下了，继续' if interaction.get('type') == 'read' else '确认判断')
        parts.append({'id': f'{interaction_id}#{index}', 'title': view.get('part_title', view['title']), 'question': view['question'],
                      'interaction': interaction, 'expected_answer': view['expected_answer'], 'feedback': view['feedback'],
                      'submit_label': submit, 'stem_board': board, 'completion_board': completion,
                      **{k: view[k] for k in ('graph', 'completion_graph', 'completion_graphs',
                                              'condition_number_lines', 'completion_number_line',
                                              'card_group', 'card_group_title') if k in view}})
    return {'parts': parts, 'diagnostics': []}
