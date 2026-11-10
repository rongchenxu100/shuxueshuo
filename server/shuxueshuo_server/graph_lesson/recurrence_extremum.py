"""Exact certificates for positive shift/scale recurrences and prefix lower bounds.

The admitted base is a positive quadratic vanishing at both ends of one
left-open/right-closed period. Global scaling is proved for all integer shifts;
finite block enumeration is never used as a proof of the infinite prefix.
"""
from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import parse
from .extremum_math import domain, scalar


def relevant(goal, entries):
    maximum = goal.get('kind') == 'find_maximum' or (
        goal.get('kind') == 'find_range' and goal.get('answer_request', {}).get('quantity') == 'maximum')
    if not maximum:
        return False
    for row in entries:
        ast = parse(row['expression'])
        body = ast[4] if ast[0] == 'quantifier' else ast
        if body[0] != '=' or body[1][0] != 'call' or body[2][0] != '*':
            continue
        name = body[1][1]
        if name in ('Dom', 'sqrt', 'abs'):
            continue
        for call in body[2][1:]:
            if _call(call, name) and body[1][2] != call[2]:
                return True
    return False


def _body(ast):
    if ast[0] == 'quantifier':
        if ast[1] != '∀':
            raise ValueError('recurrence.universal_required')
        return ast[2], domain(ast[3]), ast[4]
    return None, None, ast


def _call(ast, name):
    return isinstance(ast, list) and ast[:2] == ['call', name] and len(ast) == 3


def _rational(value):
    if not value.is_Rational or max(abs(value.p), value.q) > 10**6:
        raise ValueError('recurrence.rational_budget')
    return value


def read_sources(goal, entries):
    requested = goal.get('expression') if goal.get('kind') == 'find_maximum' else goal.get('symbol')
    p_ast = parse(requested or '')
    if p_ast[0] != 'name':
        raise ValueError('recurrence.parameter_maximum_required')
    parameter = sp.Symbol(p_ast[1], real=True)
    rows = [parse(r['expression']) for r in entries]
    domains = [a for a in rows if a[0] == '=' and a[1][:2] == ['call', 'Dom'] and a[2] == ['real']]
    if len(domains) != 1 or domains[0][1][2][0] != 'name':
        raise ValueError('recurrence.real_function_domain_required')
    name = domains[0][1][2][1]
    recurrence, base, prefix = [], [], []
    for ast in rows:
        if ast == domains[0] or ast == ['∈', ['name', str(parameter)], ['real']]:
            continue
        bound, region, body = _body(ast)
        if body[0] == '>=' and _call(body[1], name) and bound:
            if body[1][2] != ['name', bound] or region != sp.Interval(-sp.oo, parameter):
                raise ValueError('recurrence.prefix_domain_required')
            prefix.append(_rational(scalar(body[2])))
            continue
        if body[0] != '=' or not _call(body[1], name):
            raise ValueError('recurrence.unconsumed_condition')
        rhs, argument = body[2], body[1][2]
        if isinstance(region, sp.Interval) and region.inf.is_finite and region.sup.is_finite:
            if argument != ['name', bound] or not region.left_open or region.right_open:
                raise ValueError('recurrence.base_interval_required')
            x = sp.Symbol(bound, real=True)
            expr = scalar(rhs)
            if expr.free_symbols - {x} or not expr.is_polynomial(x) or sp.degree(expr, x) != 2:
                raise ValueError('recurrence.base_quadratic_required')
            origin, length = _rational(region.inf), _rational(region.sup - region.inf)
            coefficient = _rational(sp.Poly(expr, x).nth(2))
            if coefficient <= 0 or sp.expand(expr - coefficient*(x-origin)*(x-origin-length)) != 0:
                raise ValueError('recurrence.base_zero_endpoints_required')
            base.append((origin, length, coefficient))
            continue
        if region is not None and region != sp.S.Reals:
            raise ValueError('recurrence.global_identity_required')
        if rhs[0] != '*':
            raise ValueError('recurrence.scale_identity_required')
        factor, call = rhs[1:]
        if _call(factor, name):
            factor, call = call, factor
        if not _call(call, name) or call[2][0] != 'name':
            raise ValueError('recurrence.scale_identity_required')
        variable = call[2][1]
        if bound is not None and bound != variable:
            raise ValueError('recurrence.bound_variable_mismatch')
        x = sp.Symbol(variable, real=True)
        step, scale = _rational(sp.expand(scalar(argument)-x)), _rational(scalar(factor))
        if step <= 0 or scale <= 1:
            raise ValueError('recurrence.positive_step_expanding_scale_required')
        recurrence.append((variable, step, scale))
    if len(recurrence) != 1 or len(base) != 1 or len(prefix) != 1:
        raise ValueError('recurrence.complete_unique_sources_required')
    variable, step, scale = recurrence[0]
    origin, length, coefficient = base[0]
    if step != length or prefix[0] >= 0 or str(parameter) == variable:
        raise ValueError('recurrence.incompatible_source_conditions')
    return {'function': name, 'variable': sp.Symbol(variable, real=True), 'parameter': parameter,
            'origin': origin, 'length': length, 'scale': scale, 'coefficient': coefficient,
            'threshold': prefix[0]}


def describe(goal, target_ref, entries):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'given_definitions': deepcopy(entries),
            'source_refs': [target_ref, *[r['source_ref'] for r in entries]], 'task': 'recurrence',
            'structure_supported': False, 'reason': ''}
    try:
        inputs = read_sources(goal, entries)
        desc.update(function=inputs['function'], parameter=str(inputs['parameter']), structure_supported=True, quantity='maximum')
    except (ValueError, KeyError, TypeError, IndexError, sp.PolynomialError) as exc:
        desc['reason'] = str(exc)
    return desc


def _base_description(inputs, target_ref):
    from .function_monotonicity import describe as describe_monotonicity
    from .stage_three.premises import math_text
    x, origin, length, coefficient = (inputs[k] for k in ('variable', 'origin', 'length', 'coefficient'))
    expr = sp.expand(coefficient*(x-origin)*(x-origin-length))
    goal = {'kind': 'find_monotonic_intervals', 'expression': math_text(expr),
            'variable': str(x), 'direction': 'both', 'domain_role': 'restriction',
            'input_domain': '('+math_text(origin)+','+math_text(origin+length)+']'}
    return expr, describe_monotonicity(goal, target_ref)


def solve(description):
    from .function_monotonicity import solve as solve_monotonicity
    inputs = read_sources(description['source'], description['given_definitions'])
    a, length, scale, threshold = (inputs[k] for k in ('coefficient', 'length', 'scale', 'threshold'))
    minimum = -a*length**2/4
    n = 0
    while minimum*scale**n >= threshold:
        n += 1
        if abs(n) > 128:
            raise ValueError('recurrence.block_budget')
    while minimum*scale**(n-1) < threshold:
        n -= 1
        if abs(n) > 128:
            raise ValueError('recurrence.block_budget')
    offset = sp.simplify((length-sp.sqrt(length**2+4*threshold/(a*scale**n)))/2)
    value = sp.simplify(inputs['origin']+n*length+offset)
    expr, child = _base_description(inputs, description['target_ref'])
    return {**inputs, 'task': 'recurrence', 'quantity': 'maximum', 'attained': True,
            'block': n, 'base_minimum': minimum, 'offset': offset, 'value': value,
            'children': [{'description': child, 'expression': expr, 'model': solve_monotonicity(child)}]}


def verify(description, model):
    try:
        from .function_monotonicity import verify as verify_monotonicity
        inputs = read_sources(description['source'], description['given_definitions'])
        if any(model.get(k) != v for k, v in inputs.items()):
            return False
        if model.get('task') != 'recurrence' or model.get('quantity') != 'maximum' or model.get('attained') is not True:
            return False
        n, t, m = model['block'], model['offset'], model['value']
        if type(n) is not int or abs(n) > 128:
            return False
        a, length, scale, bound = (inputs[k] for k in ('coefficient', 'length', 'scale', 'threshold'))
        minimum = -a*length**2/4
        # The minimum gets strictly lower with n. Thus these adjacent inequalities
        # certify every earlier block, including the infinitely many negative ones.
        if model['base_minimum'] != minimum or not (minimum*scale**n < bound <= minimum*scale**(n-1)):
            return False
        if not (0 < t < length/2) or sp.simplify(scale**n*a*t*(t-length)-bound) != 0:
            return False
        if sp.simplify(m-inputs['origin']-n*length-t) != 0:
            return False
        # Positive curvature makes this quadratic strictly decreasing up to L/2.
        # Every larger prefix contains a point between t and L/2 below the bound.
        expr, child = _base_description(inputs, description['target_ref'])
        children = model.get('children', [])
        return bool(a > 0 and scale > 1 and len(children) == 1
                    and children[0]['description'] == child and children[0]['expression'] == expr
                    and verify_monotonicity(child, children[0]['model']))
    except (ValueError, KeyError, TypeError, IndexError, sp.PolynomialError):
        return False
