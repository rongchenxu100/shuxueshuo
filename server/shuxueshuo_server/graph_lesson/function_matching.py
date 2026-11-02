"""Bounded matching identities, including the non-injective input x-c/x.

Admission keeps original denominator restrictions. Recovery matches polynomial
coefficients; verification checks the submitted identity and a separate coverage
certificate. A scalar request is evaluated in the original relation, independently
of formula recovery.
"""

from dataclasses import dataclass

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .function_formula import FormulaSource, _bounded, _rational, _rational_parts, source_values
from .range_syntax import range_domain


@dataclass(frozen=True)
class DifferenceSource(FormulaSource):
    reciprocal_constant: sp.Expr = sp.S.One

    def input_at(self, coordinate):
        return coordinate-self.reciprocal_constant/coordinate


def matching_source(desc):
    try:
        source = source_values(desc)
    except NotationError:
        source = None
    if source is not None:
        if source.rational_input:
            raise NotationError('function_matching.fractional_input_not_in_matching_batch')
        return source
    relation, target = desc['relation_ast'], desc['target_ast']
    if (relation[0] != '=' or relation[1][:2] != ['function_call', target[1]]
            or desc.get('extra_source_refs') or desc.get('function_type')
            or desc.get('additional_relations_ast')):
        raise NotationError('function_matching.single_relation_required')

    def budget(node, depth=0):
        if depth > 16:
            raise NotationError('function_formula.expression_budget')
        return 1+sum(budget(child, depth+1) for child in node[1:] if isinstance(child, list))
    if budget(relation) > 128:
        raise NotationError('function_formula.expression_budget')
    g, s, gh = _rational(relation[1][2], target[2])
    h, _, hh = _rational(relation[2], target[2])
    numerator, denominator = _rational_parts(g, s, degree=2)
    if denominator.degree() != 1 or denominator.nth(0) != 0:
        raise NotationError('function_matching.reciprocal_difference_required')
    c = sp.cancel((s-g)*s)
    if c.is_Rational is not True or c <= 0 or gh | hh != {sp.S.Zero}:
        raise NotationError('function_matching.positive_reciprocal_constant_required')
    _bounded(c)
    # h must be a Laurent polynomial of degree at most two in either direction.
    # The paired coefficients are the equal-output condition on both preimages.
    p = sp.Poly(sp.cancel(h*s**2), s)
    if p.degree() > 4 or p.nth(0) != c**2*p.nth(4) or p.nth(1) != -c*p.nth(3):
        raise NotationError('function_matching.inconsistent_fibers_or_unsupported_degree')
    for coefficient in p.all_coeffs():
        _bounded(coefficient)
    domain = sp.S.Reals-sp.FiniteSet(0)
    if desc.get('relation_domain_ast') is not None and range_domain(desc['relation_domain_ast']) != domain:
        raise NotationError('function_matching.additional_source_restriction_unsupported')
    declared = range_domain(desc['declared_domain_ast']) if desc.get('declared_domain_ast') else None
    requested = range_domain(desc['requested_domain_ast']) if desc.get('requested_domain_ast') else None
    if any(value is not None and value != sp.S.Reals for value in (declared, requested)):
        raise NotationError('function_matching.domain_conflict')
    return DifferenceSource(1, 0, h, sp.S.Reals, declared, requested, False, s,
                            excluded_inputs=frozenset({sp.S.Zero}), reciprocal_constant=c)


def available(desc):
    try:
        matching_source(desc)
        return True
    except (NotationError, KeyError, TypeError, ValueError, sp.PolynomialError):
        return False


def coverage_certificate(source, t):
    if isinstance(source, DifferenceSource):
        # x²-tx-c=0 has real roots because Δ>0, and neither is zero because
        # their product is -c. Thus every real t has a legal preimage.
        return {'kind': 'quadratic_preimages', 'discriminant': t**2+4*source.reciprocal_constant,
                'root_product': -source.reciprocal_constant}
    return {'kind': 'affine_coordinate', 'slope': source.a, 'offset': source.b,
            'coordinate_domain': sp.Interval(0, sp.oo) if source.root_input else sp.S.Reals}


def recover_matching(desc):
    source = matching_source(desc)
    t = sp.Symbol('t' if desc['variable'] != 't' else 'z', real=True)
    a, b, c = sp.symbols('_a _b _c')
    s, g = source.coordinate, source.input_at(source.coordinate)
    coefficients = sp.Poly(sp.together(a*g**2+b*g+c-source.rhs).as_numer_denom()[0], s).all_coeffs()
    solutions = list(sp.linsolve(coefficients, (a, b, c)))
    if len(solutions) != 1 or any(value.free_symbols for value in solutions[0]):
        raise NotationError('function_matching.unique_identity_required')
    aa, bb, cc = map(_bounded, solutions[0])
    return {'kind': 'function_formula', 'derivation': 'matching', 'function_name': desc['function_name'],
            'variable': t, 'expression': aa*t**2+bb*t+cc, 'source_domain': source.domain,
            'determined_domain': source.image, 'declared_domain': source.declared, 'requested_domain': source.requested,
            'coverage': coverage_certificate(source, t), 'status': source.status}


def verify_matching(desc, proposed):
    try:
        source = matching_source(desc)
        if set(proposed) != {'kind', 'derivation', 'function_name', 'variable', 'expression', 'source_domain',
                             'determined_domain', 'declared_domain', 'requested_domain', 'coverage', 'status'}:
            return False
        t, expression = proposed['variable'], proposed['expression']
        if (not isinstance(t, sp.Symbol) or not isinstance(expression, sp.Expr)
                or expression.free_symbols-{t} or expression.has(sp.Float) or sp.count_ops(expression) > 128
                or any(part.is_Pow and part.exp.is_negative for part in sp.preorder_traversal(expression))):
            return False
        p = sp.Poly(expression, t)
        if p.degree() > 2:
            return False
        for coefficient in p.all_coeffs():
            _bounded(coefficient)
        identity = sp.cancel(expression.subs(t, source.input_at(source.coordinate))-source.rhs) == 0
        return bool(identity and proposed['coverage'] == coverage_certificate(source, t)
                    and proposed['source_domain'] == source.domain and proposed['determined_domain'] == source.image
                    and proposed['declared_domain'] == source.declared and proposed['requested_domain'] == source.requested
                    and proposed['kind'] == 'function_formula' and proposed['derivation'] == 'matching'
                    and proposed['function_name'] == desc['function_name'] and proposed['status'] == source.status)
    except (KeyError, TypeError, ValueError, NotationError, sp.PolynomialError):
        return False


def requested_value(desc):
    ast = desc['value_ast']
    if ast[:2] != ['function_call', desc['target_ast'][1]]:
        raise NotationError('function_value.single_call_required')
    value, _, holes = _rational(ast[2], desc['target_ast'][2])
    if value.free_symbols or holes:
        raise NotationError('function_value.constant_input_required')
    return _bounded(value)


def evaluate_relation(desc):
    source, target = matching_source(desc), requested_value(desc)
    if source.image.contains(target) is not sp.S.true:
        raise NotationError('function_value.input_not_determined')
    if isinstance(source, DifferenceSource):
        witness = (target+sp.sqrt(target**2+4*source.reciprocal_constant))/2
    else:
        witness = source.inverse_input(target)
    x = sp.Symbol(desc['variable'], real=True)
    _, h = source.expressions(x)
    return {'kind': 'scalar_value', 'certificate_encoding': 'relation-value/v1', 'defined': True,
            'input': target, 'source_input': witness, 'source_domain': source.domain,
            'value': sp.simplify(h.subs(x, witness)), 'variable': x, 'domain': source.image}


def verify_value(desc, proposed):
    try:
        source, target = matching_source(desc), requested_value(desc)
        x, witness = proposed['variable'], proposed['source_input']
        if (set(proposed) != {'kind', 'certificate_encoding', 'defined', 'input', 'source_input',
                             'source_domain', 'value', 'variable', 'domain'}
                or not isinstance(x, sp.Symbol) or not isinstance(witness, sp.Expr)
                or witness.free_symbols or witness.has(sp.Float) or sp.count_ops(witness) > 64):
            return False
        g, h = source.expressions(x)
        return bool(proposed['input'] == target and source.domain.contains(witness) is sp.S.true
                    and sp.simplify(g.subs(x, witness)-target) == 0
                    and sp.simplify(h.subs(x, witness)-proposed['value']) == 0
                    and proposed['source_domain'] == source.domain and proposed['domain'] == source.image
                    and proposed['kind'] == 'scalar_value' and proposed['defined'] is True
                    and proposed['certificate_encoding'] == 'relation-value/v1')
    except (KeyError, TypeError, ValueError, NotationError, sp.PolynomialError):
        return False
