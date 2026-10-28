"""Choose a checked interval-overlap explanation from mathematical structure."""

from itertools import combinations, pairwise

import sympy as sp

from .capabilities.cases import exact_set_equal
from .math_values import math_value


def _endpoint(expression, parameter):
    poly = sp.Poly(expression, parameter, domain=sp.QQ)
    slope, intercept = poly.nth(1), poly.nth(0)
    return {'slope': float(slope), 'intercept': float(intercept),
            'slope_exact': str(slope), 'intercept_exact': str(intercept)}


def _critical(intervals, guards, parameter):
    endpoints = [row[key] for row in intervals for key in ('lower', 'upper')]
    differences = [first - second for first, second in combinations(endpoints, 2)]
    differences.extend(condition.lhs - condition.rhs for condition in guards
                       if hasattr(condition, 'lhs'))
    points = set()
    for difference in differences:
        poly = sp.Poly(difference, parameter, domain=sp.QQ)
        if poly.nth(1) != 0:
            points.add(-poly.nth(0) / poly.nth(1))
    return sorted(points)


def _diagram(intervals, guards, parameter, variable, description):
    cuts = _critical(intervals, guards, parameter)
    margin = max(sp.S.One, (cuts[-1] - cuts[0]) / 2) if cuts else sp.Integer(2)
    low, high = (cuts[0] - margin, cuts[-1] + margin) if cuts else (-margin, margin)
    initial = sp.S.Zero if low <= 0 <= high else (low + high) / 2
    samples = sorted({low, high, initial, *cuts,
                      *((left + right) / 2 for left, right in pairwise(cuts))})
    # Source evidence remains exact; avoid generating hundreds of display
    # snapshots for a many-call route that is deliberately taught directly.
    if len(samples) > 15:
        samples = [samples[index * (len(samples) - 1) // 14] for index in range(15)]
    snapshots = []
    for sample in samples:
        ends = [(sp.simplify(row['lower'].subs(parameter, sample)),
                 sp.simplify(row['upper'].subs(parameter, sample))) for row in intervals]
        sets = [sp.Interval(lower, upper, left_open=row['left_open'], right_open=row['right_open'])
                for row, (lower, upper) in zip(intervals, ends, strict=True)]
        common = sp.Intersection(*sets) if sets else sp.S.Reals
        guards_hold = all(condition.subs(parameter, sample).doit() is sp.true for condition in guards)
        touches = (len(ends) == 2 and (ends[0][1] == ends[1][0] or ends[1][1] == ends[0][0]))
        relation = ('touching' if touches else 'separated' if common == sp.S.EmptySet else 'overlapping')
        snapshots.append({
            'parameter_value': math_value(sample), 'relation': relation,
            'intervals': [{'label': chr(65 + index), 'lower': math_value(lower), 'upper': math_value(upper),
                           'left_open': bool(row['left_open']), 'right_open': bool(row['right_open'])}
                          for index, (row, (lower, upper)) in enumerate(zip(intervals, ends, strict=True))],
            'common_domain': math_value(common if guards_hold else sp.S.EmptySet),
            'guards_hold': bool(guards_hold), 'holds': bool(guards_hold and common != sp.S.EmptySet),
        })
    calls = {f'call{index + 1}': call for index, call in enumerate(description['calls'])}
    return {
        'parameter': str(parameter), 'variable': str(variable),
        'parameter_min': float(low), 'parameter_max': float(high), 'initial': float(initial),
        'critical_values': [float(point) for point in cuts],
        'critical_exact_values': [str(point) for point in cuts],
        'critical_parameters': [math_value(point) for point in cuts],
        'intervals': [{
            'id': row['call_id'], 'label': chr(65 + index),
            'call_latex': f"{description['function_name']}({calls[row['call_id']]['argument_latex']})",
            'lower': _endpoint(row['lower'], parameter), 'upper': _endpoint(row['upper'], parameter),
            'lower_latex': sp.latex(row['lower']), 'upper_latex': sp.latex(row['upper']),
            'left_open': bool(row['left_open']), 'right_open': bool(row['right_open']),
        } for index, row in enumerate(intervals)],
        'snapshots': snapshots,
    }


def overlap_strategy(call_ranges, nonempty_conditions, parameter, candidate_set, variable, description):
    """Return a recommendation and independently checked complement calculation.

    Interval disjointness uses <= at a contact excluded by either interval,
    and < when both touching ends are included. Parameter-only guards are
    intersected after complementing the geometric bad set in all real numbers.
    """
    from .capabilities import LocalCheckFailed, solve_conditions

    intervals = [row for row in call_ranges if row['lower'] != -sp.oo and row['upper'] != sp.oo]
    guards = [condition for row in call_ranges for condition in row['parameter_conditions']]
    guard_set = solve_conditions(guards or [sp.true], 'all', parameter, purpose='domain')['outputs']['solution']
    if guards:
        reason, reason_text = 'parameter_guards', '存在不含自变量的参数限制，直接合并所有条件更清楚。'
    elif len(intervals) < 2:
        reason, reason_text = 'one_interval', '没有两个需要比较位置的有限区间，直接判断合法条件。'
    elif len(intervals) > 2:
        reason, reason_text = 'multiple_intervals', '涉及多个区间，直接比较所有上下界，避免遗漏某个调用。'
    elif any(sp.expand(row['upper'] - row['lower']) == 0 for row in intervals):
        reason, reason_text = 'point_domains', '包含单点范围，直接判断共同点条件更清楚。'
    elif sp.Poly(intervals[0]['lower'] - intervals[1]['lower'], parameter).nth(1) == 0:
        reason, reason_text = 'fixed_order', '两个区间的相对顺序不随参数变化，可以直接比较边界。'
    else:
        reason, reason_text = 'changing_order', '两个区间始终非空，但相对位置随参数变化；先找完全错开的情况再取补集更直观。'
    recommended = 'complement' if reason == 'changing_order' else 'direct'
    separation_conditions, cases = [], []
    empty_overlap, complement_legal, agrees = None, None, None
    if len(intervals) == 2:
        for left_index, right_index in ((0, 1), (1, 0)):
            left, right = intervals[left_index], intervals[right_index]
            contact_excluded = bool(left['right_open'] or right['left_open'])
            condition = (sp.Le if contact_excluded else sp.Lt)(left['upper'], right['lower'], evaluate=False)
            solved = solve_conditions([condition], 'all', parameter, purpose='domain')
            separation_conditions.append(condition)
            cases.append({'left_interval': chr(65 + left_index), 'right_interval': chr(65 + right_index),
                          'condition': condition, 'contact_excluded': contact_excluded,
                          'parameter_set': solved['outputs']['solution'], 'checks': solved['checks']})
        empty_overlap = sp.Union(*(case['parameter_set'] for case in cases))
        complement_legal = sp.Intersection(sp.Complement(sp.S.Reals, empty_overlap), guard_set)
        agrees = bool(exact_set_equal(complement_legal, candidate_set))
        if not agrees:
            raise LocalCheckFailed('abstract_domain_parameter.complement_disagrees_with_direct')
    strategy = {
        'recommended': recommended, 'reason': reason, 'reason_text': reason_text,
        'nonempty_conditions': nonempty_conditions, 'separation_conditions': separation_conditions,
        'separation_cases': cases, 'empty_overlap_parameters': empty_overlap,
        'constant_guard_conditions': guards, 'constant_guard_set': guard_set,
        'complement_base': sp.S.Reals, 'complement_parameters': complement_legal,
        'legal_parameters': candidate_set, 'agrees_with_direct': agrees,
    }
    return strategy, _diagram(intervals, guards, parameter, variable, description)
