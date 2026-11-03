"""Exact piecewise models for |p(x)|, deg p <= 2; sampling never decides truth."""
from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, parse
from .function_formula import _bounded, _polynomial
from .function_graph import rational
from .range_syntax import range_domain

KINDS = ('draw_function_graph', 'solve_graph_inequality')
VERSION = 'function-graph-absolute-polynomial/v1'


def source(goal):
    variable = parse(goal['variable'])
    ast = parse(goal['expression'])
    if variable[0] != 'name' or ast[:2] != ['call', 'abs'] or len(ast) != 3:
        raise ValueError('absolute_graph.polynomial_absolute_required')
    poly = _polynomial(ast[2], variable, root_input=False)
    poly = sp.Poly(poly.as_expr().subs(poly.gens[0], sp.Symbol(variable[1], real=True)), sp.Symbol(variable[1], real=True))
    if poly.degree() > 2:
        raise ValueError('absolute_graph.degree_above_two')
    domain = range_domain(parse(goal.get('input_domain', 'ℝ')))
    if domain != sp.S.Reals and not isinstance(domain, sp.Interval):
        raise ValueError('absolute_graph.interval_required')
    for end in (domain.inf, domain.sup):
        if end.is_finite:
            _bounded(end)
    if goal['kind'] == 'solve_graph_inequality':
        rational(goal['level'])
        if goal['operator'] not in ('>', '>=', '<', '<='):
            raise ValueError('absolute_graph.order_relation_required')
    return poly, domain


def describe(goal, target_ref, extra_refs=(), *, given_definitions=()):
    desc = {'source': deepcopy(goal), 'target_ref': target_ref, 'source_refs': [target_ref],
            'extra_source_refs': list(extra_refs), 'structure_version': VERSION,
            'structure_supported': False, 'reason': ''}
    if given_definitions:
        desc['given_definitions'] = deepcopy(list(given_definitions))
        desc['source_refs'].extend(row['source_ref'] for row in given_definitions)
    try:
        if extra_refs or goal['kind'] not in KINDS:
            raise ValueError('absolute_graph.extra_conditions_unsupported')
        source(goal)
        # A photo may retain the shared f(x) definition above its two subquestions.
        # Accept only that exact source rule, never a conflicting rule or a new condition.
        expected = ['=', ['call', 'f', parse(goal['variable'])], parse(goal['expression'])]
        if len(given_definitions) > 1 or any(parse(row['expression']) != expected for row in given_definitions):
            raise ValueError('absolute_graph.shared_definition_mismatch')
        desc['structure_supported'] = True
    except (ValueError, NotationError, TypeError, KeyError) as exc:
        desc['reason'] = getattr(exc, 'code', str(exc))
    return desc


def polynomial_set(poly, operator):
    if poly.degree() <= 0:
        return sp.S.Reals if bool(sp.Rel(poly.nth(0), 0, operator)) else sp.S.EmptySet
    return sp.Union(*sp.solve_poly_inequality(poly, operator))


def midpoint(low, high):
    if low == -sp.oo:
        return high-1 if high != sp.oo else sp.S.Zero
    return low+1 if high == sp.oo else (low+high)/2


def solve(desc):
    if not desc['structure_supported']:
        raise ValueError(desc['reason'])
    goal = desc['source']
    poly, domain = source(goal)
    x = poly.gens[0]
    roots = sorted(set(poly.real_roots())) if poly.degree() > 0 else []
    cuts = [domain.inf, *[r for r in roots if domain.inf < r < domain.sup], domain.sup]
    pieces = []
    for index, (low, high) in enumerate(pairwise(cuts)):
        sign = -1 if poly.eval(midpoint(low, high)) < 0 else 1
        region = sp.Interval(low, high, left_open=(low == -sp.oo or index == 0 and low not in domain),
                             right_open=(high == sp.oo or index < len(cuts)-2 or high not in domain))
        pieces.append({'expression': sp.expand(sign*poly.as_expr()), 'domain': region, 'sign': sign})
    result = {'kind': goal['kind'], 'variable': x, 'polynomial': poly.as_expr(), 'domain': domain,
              'roots': [r for r in roots if r in domain], 'pieces': pieces}
    if goal['kind'] == 'solve_graph_inequality':
        level = rational(goal['level'])
        result.update(level=level, operator=goal['operator'],
                      crossings=sp.Union(*(polynomial_set(sp.Poly(p['expression']-level, x), '==') & p['domain'] for p in pieces)),
                      solution=sp.Union(*(polynomial_set(sp.Poly(p['expression']-level, x), goal['operator']) & p['domain'] for p in pieces)))
    return result


def verify(desc, result):
    """Check full domains and polynomial identities; do not call solve or inspect pixels."""
    try:
        goal = desc['source']
        if (describe(goal, desc['target_ref'], desc['extra_source_refs'],
                     given_definitions=desc.get('given_definitions', ())) != desc or not desc['structure_supported']):
            return False
        poly, domain = source(goal)
        x = poly.gens[0]
        required = {'kind', 'variable', 'polynomial', 'domain', 'roots', 'pieces'}
        if goal['kind'] == 'solve_graph_inequality':
            required |= {'level', 'operator', 'crossings', 'solution'}
        if set(result) != required or (result['kind'], result['variable'], result['polynomial'], result['domain']) != (goal['kind'], x, poly.as_expr(), domain):
            return False
        roots = sp.solveset(poly.as_expr(), x, domain=domain) if poly.degree() > 0 else sp.S.EmptySet
        if sp.FiniteSet(*result['roots']) != roots:
            return False
        covered = sp.S.EmptySet
        for piece in result['pieces']:
            region, sign, expr = piece['domain'], piece['sign'], piece['expression']
            if not isinstance(region, sp.Interval) or sign not in (-1, 1) or region & covered != sp.S.EmptySet:
                return False
            if sp.expand(expr-sign*poly.as_expr()) != 0 or region - polynomial_set(sp.Poly(expr, x), '>=') != sp.S.EmptySet:
                return False
            covered |= region
        if covered != domain:
            return False
        if goal['kind'] == 'solve_graph_inequality':
            level, op = rational(goal['level']), goal['operator']
            if (result['level'], result['operator']) != (level, op):
                return False
            # Independent absolute-value identity: |p| >= k iff p>=k or p<=-k
            # (and analogous < / <= intersection); negative levels work too.
            upper = polynomial_set(sp.Poly(poly.as_expr()-level, x), op)
            reverse = {'>': '<', '>=': '<=', '<': '>', '<=': '>='}[op]
            lower = polynomial_set(sp.Poly(poly.as_expr()+level, x), reverse)
            expected = (upper | lower if op in ('>', '>=') else upper & lower) & domain
            crossings = (sp.solveset(poly.as_expr()-level, x, domain=domain) | sp.solveset(poly.as_expr()+level, x, domain=domain)) if level >= 0 else sp.S.EmptySet
            return result['solution'] == expected and result['crossings'] == crossings
        return True
    except (ValueError, NotationError, TypeError, KeyError, AttributeError):
        return False
