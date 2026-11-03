"""Exact marginal pricing, with a deliberately narrow, source-bound P5 contract.

No formula is inferred from an answer or solution. Pricing is admitted only
when the complete source statement matches the supported wording, including
units, marginal portions and both requests. Extra clauses fail closed.
"""
import re
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .stage_one.function_domain import source_pointer

VERSION = 'piecewise-modeling/v1'
METHOD = 'method-piecewise-modeling'


def number(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,6}(?:\.\d{1,4})?', value):
        raise NotationError('pricing.decimal_required')
    return sp.Rational(value)


def statement(pricing, cost):
    """The current approved source grammar; this is not a general OCR parser."""
    p = pricing
    a, b = p['thresholds']
    r, s, t = p['rates']
    x, y, unit, money = p['quantity'], p['amount'], p['quantity_unit'], p['amount_unit']
    return (f'某地居民用电采用阶梯电价，其标准如下：每户每月用电量不超过{a}{unit}的，每{unit}电费是{r}{money}；'
            f'每户每月用电量超过{a}{unit}，但不超过{b}{unit}的部分，每{unit}电费是{s}{money}；'
            f'每户每月用电量超过{b}{unit}的部分，每{unit}电费是{t}{money}。'
            f'设该户居民交电费{y}{money}，已知该户居民该月用电量为{x}{unit}。'
            f'（1）求{y}关于{x}的函数关系式；（2）若该户居民该月交电费{cost}{money}，求该户居民该月的用电量。')


def source(goal):
    p = goal['pricing']
    if (p['mode'] != 'marginal' or p['quantity_domain'] != 'nonnegative_real'
            or p['quantity_unit'] != '千瓦时' or p['amount_unit'] != '元'
            or len(p['thresholds']) != 2 or len(p['rates']) != 3):
        raise NotationError('pricing.unsupported_terms')
    thresholds, rates = list(map(number, p['thresholds'])), list(map(number, p['rates']))
    if not 0 < thresholds[0] < thresholds[1] or any(r <= 0 for r in rates):
        raise NotationError('pricing.ordered_positive_terms_required')
    cost = number(goal['bill'])
    compact = lambda text: re.sub(r'\s+', '', text)
    if compact(goal['source_text']) != compact(statement(p, goal['bill'])):
        raise NotationError('pricing.source_terms_not_bound')
    return thresholds, rates, cost


def describe(report, scope, ancestors, index, *, original_text):
    goal = deepcopy(scope['goals'][index])
    target = f"{source_pointer(scope['scope'])}/goals/{index}"
    records = [r for item in (*ancestors, scope) for r in report.scope_facts.get(item['scope'], [])]
    desc = {'structure_version': VERSION, 'structure_supported': False, 'reason': '',
            'target_ref': target, 'goal_ast': goal, 'variable_ast': goal['target'],
            'variable': goal['pricing']['quantity'], 'sources': [], 'source_refs': [target]}
    try:
        if records or any(s.get('uncertainties') for s in (*ancestors, scope)):
            raise NotationError('pricing.extra_source_conditions')
        if original_text != goal['source_text']:
            raise NotationError('pricing.original_text_mismatch')
        source(goal)
        desc['structure_supported'] = True
    except (NotationError, ValueError, KeyError, TypeError) as exc:
        desc['reason'] = getattr(exc, 'code', str(exc))
    return desc


def inspect_target(candidate, target_ref):
    from .piecewise_equation import inspect_target as inspect
    return inspect(candidate, target_ref, describe_goal=lambda *args: describe(*args, original_text=candidate['original_text']))


def admitted(context):
    desc = context.get('piecewise_modeling', {})
    return (desc.get('structure_supported') is True and not context['entries']
            and desc['goal_ast'] == context['goal_ast'])


def model(goal):
    thresholds, rates, _ = source(goal)
    x = sp.Symbol(goal['pricing']['quantity'], real=True)
    rows, prior, lower = [], sp.S.Zero, sp.S.Zero
    for index, (upper, rate) in enumerate(zip([*thresholds, sp.oo], rates, strict=True)):
        rows.append({'lower': lower, 'upper': upper, 'rate': rate, 'prior': prior,
                     'domain': sp.Interval(lower, upper, left_open=index > 0),
                     'expression': sp.expand(prior+rate*(x-lower))})
        if upper != sp.oo:
            prior += rate*(upper-lower)
        lower = upper
    return {'pricing': deepcopy(goal['pricing']), 'rows': rows}


def verify_model(goal, proposed):
    """Independent sum of charges over tier intersections, on every interval."""
    try:
        cuts, rates, _ = source(goal)
        p = goal['pricing']
        if proposed.get('pricing') != p or len(proposed['rows']) != 3:
            return False
        x = sp.Symbol(p['quantity'], real=True)
        bounds = [sp.S.Zero, *cuts, sp.oo]
        for i, row in enumerate(proposed['rows']):
            previous = sum(rates[j]*(bounds[j+1]-bounds[j]) for j in range(i))
            expected = previous + rates[i]*(x-bounds[i])
            if row != {'lower': bounds[i], 'upper': bounds[i+1], 'rate': rates[i],
                       'prior': previous, 'domain': sp.Interval(bounds[i], bounds[i+1], left_open=i > 0),
                       'expression': sp.expand(expected)}:
                return False
        return True
    except (NotationError, ValueError, TypeError, KeyError):
        return False


def build(context):
    from .stage_three.capabilities import CapabilityGap, LocalCheckFailed, result
    if not admitted(context) or context['goal']['kind'] != 'find_equation':
        raise CapabilityGap('pricing.model_not_admitted')
    built = model(context['goal_ast'])
    if not verify_model(context['goal_ast'], built):
        raise LocalCheckFailed('pricing.model_invalid')
    return result({'description': context['piecewise_modeling'], 'model_result': built},
                  ['marginal_tier_sum'], [{'kind': 'all_tier_charge_sums', 'passed': True}])


def equation_description(context):
    """A proven intermediate model passed to M1, not a fabricated given fact."""
    from ..problem_understanding.notation_compile import NotationValidator
    from .piecewise_equation import describe as describe_equation
    from .stage_one.contracts import schema
    if not admitted(context) or context['goal']['kind'] != 'find_range':
        raise NotationError('pricing.inverse_not_admitted')
    goal = context['goal_ast']
    built = model(goal)
    if not verify_model(goal, built):
        raise NotationError('pricing.model_invalid')
    x = goal['pricing']['quantity']
    function = 'h' if x == 'g' else 'g'
    a, b = goal['pricing']['thresholds']
    expressions = [str(r['expression']).replace('**', '^') for r in built['rows']]
    definition = f'{function}({x})=piecewise({expressions[0]},0<={x}<={a},{expressions[1]},{a}<{x}<={b},{expressions[2]},{x}>{b})'
    root = {'definitions': [definition], 'facts': [f'{function}({x})={goal["bill"]}'],
            'goals': [{'kind': 'find_range', 'symbol': x}]}
    report = NotationValidator().validate_root(root, schema()['$defs'])
    if not report.ok:
        raise NotationError('pricing.derived_model_invalid')
    desc = describe_equation(report, report.semantic, (), 0)
    # Both derived rows refer to the actual pricing goal. The temporary parser
    # scope is not part of the original question and must not invent pointers.
    desc['target_ref'] = context['piecewise_modeling']['target_ref']
    desc['source_refs'] = [desc['target_ref']]
    for row in desc['sources']:
        row['source_ref'] = desc['target_ref']
    desc['pricing_source'] = deepcopy(context['piecewise_modeling'])
    return desc


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .stage_three.context import build_context
    from .stage_three.trajectory import decode_value
    rebuilt = build_context(candidate, target_ref)
    valid = rebuilt == context and admitted(rebuilt) and verify_model(rebuilt['goal_ast'], decode_value(encoded_result))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'source_bound_marginal_charge_sum', 'passed': valid}],
            'diagnostics': [] if valid else [{'code': 'pricing.independent_model_verification_failed'}]}


def finish(state, context, previous):
    from .stage_three.capabilities import LocalCheckFailed
    from .stage_three.math_values import math_value
    from .stage_three.trajectory import decode_value
    built = decode_value(state['model_result_exact'])
    if not verify_model(context['goal_ast'], built):
        raise LocalCheckFailed('pricing.model_finalization_failed')
    answer = {'kind': 'find_equation', 'status': 'complete', 'pricing': built['pricing'],
              'pieces': [{'expression': math_value(r['expression']), 'domain': math_value(r['domain'])} for r in built['rows']]}
    return {'state': deepcopy(state), 'answer': answer, 'model_result_exact': state['model_result_exact'],
            'consistency': 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'}
