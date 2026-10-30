"""M3 polynomial images with an independent monotone-cover verification."""

from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..stage_one.function_domain import _fixed_poly
from ..stage_one.function_range import inspect_range_target
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .capabilities.ranges import quadratic_interval_range
from .function_domain import input_set
from .math_values import math_value

METHOD_ID = 'method-quadratic-interval-range'


def inputs(description):
    if not description.get('structure_supported'):
        raise CapabilityGap(description.get('reason') or 'range.input_class_unavailable')
    variable = sp.Symbol(description['variable'], real=True)
    coefficients = [sp.Rational(v.numerator, v.denominator)
                    for v in _fixed_poly(description['expression_ast'], max_degree=2)]
    expression = sum((v * variable**i for i, v in enumerate(coefficients)), sp.S.Zero)
    declared = input_set({**description, 'input_domain_ast': description['declared_domain_ast']})
    domain = declared & input_set(description)
    for row in description['restriction_facts']:
        domain &= input_set({**description, 'input_domain_ast': row['domain_ast']})
    if domain is sp.S.EmptySet:
        raise CapabilityGap('range.empty_input')
    if domain is sp.S.Reals:
        domain = sp.Interval(-sp.oo, sp.oo)
    if not isinstance(domain, sp.Interval) and not (isinstance(domain, sp.FiniteSet) and len(domain) == 1):
        raise CapabilityGap('range.single_interval_required')
    return expression, variable, domain


def admitted(context):
    if not (context.get('goal', {}).get('kind') == 'find_range'
            and 'object' in context['goal']
            and context.get('range_goal', {}).get('structure_supported') is True):
        return False
    try:
        inputs(context['range_goal'])
    except (CapabilityGap, ValueError):
        return False
    return True


def prepare_function_range(context):
    if not admitted(context):
        raise CapabilityGap('range.input_class_unavailable')
    description = deepcopy(context['range_goal'])
    expression, variable, domain = inputs(description)
    degree = int(max(0, sp.degree(expression, variable)))
    return result({'description': description, 'function': expression, 'variable': variable,
                   'domain': domain, 'degree': degree, 'quadratic': degree == 2,
                   'natural_domain': sp.S.Reals}, [],
                  [{'kind': 'original_polynomial_domain', 'passed': True,
                    'natural_domain': sp.S.Reals,
                    'declared_domain': input_set({**description, 'input_domain_ast': description['declared_domain_ast']}),
                    'effective_domain': domain}])


def polynomial_image(expression, variable, domain):
    if isinstance(domain, sp.FiniteSet) and len(domain) == 1:
        point = next(iter(domain))
        value = expression.subs(variable, point)
        bounds = {'inf': value, 'sup': value, 'inf_attained': True,
                  'sup_attained': True, 'set': sp.FiniteSet(value)}
        computed = result({'range': bounds, 'endpoint_values': [
            {'point': point, 'value': value, 'attained': True}], 'critical_points': []},
            ['interval_extrema'], [{'kind': 'singleton_image', 'passed': True}])
    else:
        computed = quadratic_interval_range(expression, variable, domain)
    expected, _ = monotone_cover(expression, variable, domain)
    if computed['outputs']['range']['set'] != expected:
        raise LocalCheckFailed('range.local_image_mismatch')
    computed['outputs']['feasible_set'] = expected
    return computed


def _limit(expression, variable, endpoint):
    if endpoint not in (-sp.oo, sp.oo):
        return expression.subs(variable, endpoint)
    return sp.limit(expression, variable, endpoint)


def monotone_cover(expression, variable, domain):
    """Partition at the derivative's zero and map each whole monotone piece.

    This verifier does not use the solver's extrema candidates/attainment flags.
    Every piece is continuous and monotone, so its endpoint image is both an
    upper/lower containment bound and a proof that every intermediate value is
    attained. Union retains a boundary if any other legal preimage attains it.
    """
    if isinstance(domain, sp.FiniteSet):
        point = next(iter(domain))
        image = sp.FiniteSet(expression.subs(variable, point))
        return image, [{'domain': domain, 'image': image, 'reason': 'singleton'}]
    derivative = sp.diff(expression, variable)
    if derivative == 0:
        image = sp.FiniteSet(expression)
        return image, [{'domain': domain, 'image': image, 'reason': 'constant_on_nonempty_domain'}]
    cuts = [domain.start, domain.end]
    for point in sp.solve(derivative, variable):
        if point.is_real is True and domain.start < point < domain.end:
            cuts.append(point)
    cuts = sorted(set(cuts))
    pieces, images = [], []
    for left, right in pairwise(cuts):
        a, b = _limit(expression, variable, left), _limit(expression, variable, right)
        take_left = domain.contains(left) is sp.true and left not in (-sp.oo, sp.oo)
        take_right = domain.contains(right) is sp.true and right not in (-sp.oo, sp.oo)
        region = sp.Interval(left, right, left_open=not take_left, right_open=not take_right)
        image = (sp.Interval(a, b, left_open=not take_left, right_open=not take_right) if a < b else
                 sp.Interval(b, a, left_open=not take_right, right_open=not take_left))
        images.append(image)
        pieces.append({'domain': region, 'image': image, 'reason': 'continuous_strictly_monotone',
                       'direction': 'increasing' if a < b else 'decreasing'})
    return sp.Union(*images), pieces


def process_context(context, feasible_set):
    inputs(context['range_goal'])
    # Definition, declared domain and extra restrictions have all been read by
    # the structural contract. The result is an OUTPUT set, never intersect it
    # with an input constraint here.
    return feasible_set, [{'source_ref': row['source_ref'], 'status': 'function_image_source'}
                          for row in context['entries']]


def independent_verify(candidate, target_ref, context, proposed):
    description = inspect_range_target(candidate, target_ref)
    if description != context.get('range_goal'):
        return {'status': 'math_failed', 'proof': {},
                'diagnostics': [{'code': 'range.source_context_mismatch'}]}
    from .verification import check_context, collect_original
    check_context(collect_original(candidate, target_ref), context)
    expression, variable, domain = inputs(description)
    expected, pieces = monotone_cover(expression, variable, domain)
    passed = proposed == expected
    return {'status': 'verified' if passed else 'math_failed',
            'proof': {'kind': 'complete_function_image', 'passed': passed,
                      'effective_domain': math_value(domain), 'expected': math_value(expected),
                      'containment': passed, 'attainability': passed,
                      'cover': [{**row, 'domain': math_value(row['domain']), 'image': math_value(row['image'])}
                                for row in pieces]},
            'diagnostics': [] if passed else [{'code': 'range.image_mismatch'}]}


def image_endpoints(candidate, target_ref, image):
    expression, variable, domain = inputs(inspect_range_target(candidate, target_ref))
    rows = []
    for point in sorted(image.boundary):
        if sp.diff(expression, variable) == 0:
            witnesses = [next(iter(domain)) if isinstance(domain, sp.FiniteSet) else
                         (domain.start + domain.end)/2 if domain.start.is_finite and domain.end.is_finite else
                         domain.start+1 if domain.start.is_finite else domain.end-1 if domain.end.is_finite else sp.S.Zero]
            witnesses = [v for v in witnesses if expression == point]
        else:
            witnesses = [v for v in sp.solve(expression-point, variable)
                         if v.is_real is True and domain.contains(v) is sp.true]
        included = image.contains(point) is sp.true
        rows.append({'point': math_value(point), 'included': included, 'holds': bool(witnesses),
                     'passed': included == bool(witnesses),
                     'evidence': {'legal_preimages': [math_value(v) for v in witnesses]}})
    return {'status': 'passed' if all(row['passed'] for row in rows) else 'failed', 'points': rows}
