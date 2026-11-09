"""Shared FM-T1 admission, child-method bindings and frozen-goal verification."""
from copy import deepcopy

import sympy as sp

from ..function_monotonicity import (
    KINDS,
    PIECEWISE_FAMILIES,
    components,
    describe,
    effective_domain,
    solve,
    source,
    verify,
)
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .math_values import latex
from .premises import math_text
from .trajectory import decode_value, encode_value


def admitted(context, method=None):
    desc = context.get('monotonicity_goal', {})
    entries = [{k: row[k] for k in ('source_ref', 'expression')} for row in context.get('entries', [])]
    if (context.get('goal', {}).get('kind') not in KINDS or not desc.get('structure_supported')
            or entries != desc.get('given_definitions') or context['goal'] != desc['source']):
        return False
    if method == 'definition':
        return desc.get('family') == 'polynomial'
    if method == 'piecewise':
        return desc.get('family') in PIECEWISE_FAMILIES
    if method == 'structure':
        return desc.get('family') not in PIECEWISE_FAMILIES
    return True


def prepare(context):
    from .context import build_context
    if not admitted(context):
        raise CapabilityGap('monotonicity.input_class_unavailable')
    desc = deepcopy(context['monotonicity_goal'])
    spec = source(desc['source'])
    try:
        natural, domain = effective_domain(spec, desc['source'])
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc
    borrow = spec['family'] in ('sqrt', 'reciprocal_sqrt')
    nested = context.get('teaching_density') == 'nested_inequality'
    domain_context = None
    if borrow:
        name, variable = desc['source'].get('function', 'f'), desc['source']['variable']
        goal = {'kind': 'find_domain', 'object': name}
        if 'input_domain' in desc['source']:
            goal['input_domain'] = desc['source']['input_domain']
        candidate = {'original_text': '求当前函数的定义域', 'root': {
            'definitions': [f'{name}({variable})={desc["source"]["expression"]}'], 'goals': [goal]}}
        domain_context = build_context(candidate, '/root/goals/0')
    p = spec['polynomial']
    quadratic = p is not None and sp.Poly(p, spec['variable']).degree() == 2
    show_square = quadratic
    if nested and quadratic:
        # Skip completing-the-square when the piece direction is already obvious.
        if sp.expand(p) == spec['variable']**2:
            show_square = False
        else:
            coeffs = sp.Poly(p, spec['variable']).all_coeffs()
            axis = -coeffs[1] / (2 * coeffs[0])
            if isinstance(domain, sp.Interval) and axis not in sp.Interval.open(domain.start, domain.end):
                show_square = False
    return result({
        'description': desc, 'domain_context': domain_context, 'needs_domain': borrow,
        'plain_domain': (not borrow) and not nested,
        'show_square': show_square,
        'show_answer': not nested,
        'polynomial': p, 'variable': spec['variable'], 'quadratic': quadratic,
        'domain': domain, 'natural_domain': natural,
    }, ['monotonicity_domain'],
                  [{'kind': 'original_domain_constraints', 'passed': True}])


def analyze(description, method='structure', domain=None):
    try:
        model = solve(description, method)
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc
    if domain is not None and domain != model['effective_domain'] or not verify(description, model):
        raise LocalCheckFailed('monotonicity.analysis_failed')
    return result({'monotonicity_result': model}, ['monotonicity_structure'],
                  [{'kind': 'strict_order_and_complete_partition', 'passed': True}])


def transfer(description, monotonicity_result):
    if monotonicity_result['family'] not in ('sqrt', 'reciprocal_sqrt') or not verify(description, monotonicity_result):
        raise LocalCheckFailed('monotonicity.composition_conditions_failed')
    return result({'monotonicity_result': monotonicity_result}, ['monotonicity_structure'],
                  [{'kind': 'outer_domain_and_order_chain', 'passed': True}])


def confirm(description, monotonicity_result):
    if not verify(description, monotonicity_result):
        raise LocalCheckFailed('monotonicity.interval_family_invalid')
    return result({'monotonicity_result': monotonicity_result}, ['monotonicity_structure'])


def split(context):
    if not admitted(context, 'piecewise'):
        raise CapabilityGap('monotonicity.piecewise_required')
    desc = context['monotonicity_goal']
    spec = source(desc['source'])
    _, domain = effective_domain(spec, desc['source'])
    cases = []
    for i, piece in enumerate(spec['pieces']):
        for interval in components(domain & piece['domain']):
            domain_text = ('(' if interval.left_open else '[') + ','.join(
                str(v).replace('oo', '∞') for v in (interval.inf, interval.sup)) + (')' if interval.right_open else ']')
            goal = {'kind': 'find_monotonic_intervals', 'variable': str(spec['variable']),
                    'expression': math_text(piece['expression']), 'direction': 'both',
                    'input_domain': domain_text, 'domain_role': 'restriction',
                    'function': f'f_{i+1}'}
            child = describe(goal, desc['target_ref'])
            child_context = {
                'goal': goal, 'target_ref': desc['target_ref'], 'entries': [],
                'monotonicity_goal': child,
            }
            if context.get('teaching_density'):
                child_context['teaching_density'] = context['teaching_density']
            cases.append({'id': f'piece-{i+1}', 'condition': interval.as_relational(spec['variable']),
                          'domain': interval, 'context': child_context})
    evidence = 'equivalent_absolute_branches' if spec['family'] == 'absolute' else 'equivalent_explicit_branches'
    return result({'description': deepcopy(desc), 'branch_cases': cases}, ['absolute_sign_split'],
                  [{'kind': evidence, 'passed': True}])


def bind(branch_case):
    return result({'child_context': branch_case['context']}, ['absolute_sign_split'])


def join(context, branch_results):
    cases = split(context)['outputs']['branch_cases']
    if len(cases) != len(branch_results):
        raise LocalCheckFailed('monotonicity.branch_missing')
    for case, returned in zip(cases, branch_results, strict=True):
        if (returned['case_id'] != case['id'] or returned['domain'] != case['domain']
                or returned['condition'] != case['condition']
                or not verify(case['context']['monotonicity_goal'], returned['outputs']['model'])):
            raise LocalCheckFailed('monotonicity.child_proof_invalid')
    answer = analyze(context['monotonicity_goal'], 'piecewise')
    answer['operations'] = ['monotonicity_junction']
    answer['outputs']['show_piecewise_answer'] = context.get('teaching_density') != 'nested_inequality'
    return answer


def prepare_difference(description, monotonicity_result):
    if monotonicity_result['family'] != 'polynomial' or not verify(description, monotonicity_result):
        raise LocalCheckFailed('monotonicity.difference_source_invalid')
    x = monotonicity_result['variable']
    x1, x2 = sp.symbols('x_1 x_2', real=True)
    expr = monotonicity_result['expression']
    actual = expr.subs(x, x2)-expr.subs(x, x1)
    return result({'difference': actual, 'variable': x, 'use_square': False}, ['monotonicity_difference'])


def factor_difference(expression):
    from ...problem_understanding.notation_semantics import bounded_expand
    value = sp.factor(bounded_expand(expression))
    return result({'expression': value}, ['identity'],
                  [{'kind': 'factor_identity', 'passed': bounded_expand(value-expression) == 0}])


def difference_proof(description, monotonicity_result, difference):
    if monotonicity_result['family'] != 'polynomial' or not verify(description, monotonicity_result):
        raise LocalCheckFailed('monotonicity.difference_source_invalid')
    x = monotonicity_result['variable']
    x1, x2 = sp.symbols('x_1 x_2', real=True)
    expr = monotonicity_result['expression']
    p = sp.Poly(expr, x)
    factored = (x2-x1)*(p.nth(2)*(x1+x2)+p.nth(1))
    if sp.expand(difference-factored) != 0:
        raise LocalCheckFailed('monotonicity.difference_identity')
    return result({'monotonicity_result': monotonicity_result}, ['monotonicity_difference'],
                  [{'kind': 'arbitrary_ordered_pair_identity_and_sign', 'passed': True, 'difference': factored}])


def interval_latex(intervals):
    return r'\text{无}' if not intervals else r'\quad\text{和}\quad'.join(latex(v) for v in intervals)


def answer(model):
    selected = ('increasing', 'decreasing') if model['requested_direction'] == 'both' else (model['requested_direction'],)
    labels = {'increasing': r'\uparrow\;', 'decreasing': r'\downarrow\;'}
    return {'kind': model['kind'], 'status': 'complete', 'direction': model['requested_direction'],
            'latex': r'\quad;\quad'.join(labels[d]+interval_latex(model[d+'_intervals']) for d in selected),
            'interval_families': {d: [encode_value(v) for v in model[d+'_intervals']] for d in selected}}


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = current == context and admitted(current) and verify(current['monotonicity_goal'], decode_value(encoded_result))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'strict_order_domain_coverage_and_maximality', 'passed': valid}],
            'processing': [{'source_ref': row['source_ref'], 'kind': 'identical_function_definition', 'status': 'processed'}
                           for row in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'monotonicity.independent_verification_failed'}]}


def finish(state, context, previous):
    model = decode_value(state['monotonicity_result_exact'])
    if not verify(context['monotonicity_goal'], model):
        raise LocalCheckFailed('monotonicity.finalization_failed')
    final = answer(model)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != final for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': final,
            'monotonicity_result_exact': encode_value(model), 'consistency': consistency}


def select(context, contract, primary):
    if not admitted(context):
        return {'status': 'no_applicable_method', 'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [],
                'recommendation_rule': None, 'recommendation_checks': []}, 'd3': None, 'd4': None,
                'diagnostics': [{'code': context.get('monotonicity_goal', {}).get('reason', 'monotonicity.unsupported')}]}
    family = context['monotonicity_goal']['family']
    preferred = 'piecewise' if family in PIECEWISE_FAMILIES else 'structure'
    if context['goal']['kind'] == 'prove_monotonicity_on_interval' and family == 'polynomial':
        preferred = 'definition'
    labels = {'structure': '基本函数与复合法', 'piecewise': '分段单调性法', 'definition': '定义法'}
    # Keep the general method map, but only open routes suited to this task.
    # Recognizable concrete interval questions do not need a second definition proof.
    eligible = {name for name in labels if admitted(context, name)
                and (name != 'definition' or context['goal']['kind'] == 'prove_monotonicity_on_interval')}
    piecewise_note = (
        '例如 $|x|$：$x<0$ 时写成 $-x$，$x\\geq0$ 时写成 $x$；分别判断，再检查分界处。'
        if family == 'absolute' else
        '按原定义的各段分别判断增减，再检查跨段像的次序；同向箭头不能直接拼成整体结论。')
    cues = [
        {'value': 'structure', 'label': '一次、二次、反比例等常见函数及其复合函数',
         'note': '先用已知的增减规律；复合函数逐层判断。例如先看 $u=x^2$，再看 $y=\\sqrt{u}$。'},
        {'value': 'piecewise', 'label': '分段给出或含绝对值，需要分段判断',
         'note': piecewise_note},
        {'value': 'definition', 'label': '题目要求用定义证明单调性',
         'note': '任取 $x_1<x_2$，判断 $f(x_2)-f(x_1)$ 的正负。例如对 $f(x)=2x+1$，差为 $2(x_2-x_1)>0$。'},
    ]
    branches = []
    for name in (preferred, *[n for n in labels if n != preferred]):
        if name not in eligible:
            continue
        method = 'method-piecewise-monotonicity' if name == 'piecewise' else 'method-monotonicity-'+name
        branches.append({'branch': name, 'target': method, 'route_id': method.removeprefix('method-'),
            'trigger': 'triggered', 'applicability': 'applicable',
            'recommendation': 'preferred' if name == preferred else 'optional',
            'route_plan': 'capability_gap', 'missing_capabilities': ['execution:'+method],
            'checks': [{'check_id': 'original_monotonicity_structure', 'status': 'holds',
                        'source_refs': context['monotonicity_goal']['source_refs']}]})
    return {'status': 'no_verified_route',
        'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': branches,
                      'recommendation_rule': 'monotonicity_structure', 'recommendation_checks': []},
        'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '结合函数结构，选择一种解题方法。',
               'query': {'op': 'methods', 'from': primary},
               'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                    'checks': [{'id': 'structure', 'question': '这道题最直接的结构线索是什么？',
                        'options': cues,
                        'resolved': labels[preferred], 'feedback': '先确定定义域，再选择适用的判断方法。'}],
                    'method_notes': {} if 'definition' in eligible else {'definition': '本题不展开，优先利用函数性质'},
                    'method_choices': [{'value': k, 'label': v} for k, v in labels.items()],
                    'connections': [{'cue': k, 'method': k} for k in labels],
                    'source_refs': context['monotonicity_goal']['source_refs']},
               'expected_answer': {'checks': {'structure': preferred}},
               'verdicts': {k: {'value': 'fit' if k in eligible or k == 'definition' else 'unfit',
                        'message': '可沿此方法逐步判断并核对完整区间。' if k in eligible else
                                   '定义法也能论证，但本题求具体函数的单调区间，利用函数性质更直接。本题不展开定义法，请选择基本函数与复合法。' if k == 'definition' and preferred == 'structure' else
                                   '定义法也能论证，但本题含绝对值，先分段更清楚。本题不展开定义法，请选择分段单调性法。' if k == 'definition' else
                                   '需要先按函数结构选择对应的方法。'} for k in labels},
               'submit_label': '确认选法'},
        'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [
            {'branch': b['branch'], 'method': b['target'], 'route_id': b['route_id'],
             'recommendation': b['recommendation'], 'route_plan': 'capability_gap', 'message': labels[b['branch']]} for b in branches]},
        'diagnostics': []}
