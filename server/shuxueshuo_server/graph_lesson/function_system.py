"""C: two function values interchanged by a domain-preserving involution.

Only bounded, inert source ASTs are accepted. Admission never solves the system.
An independent check substitutes the proposed expression in the original identity
and proves uniqueness through the nonzero constant determinant.
"""
from dataclasses import dataclass

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .function_formula import _bounded, _rational
from .range_syntax import range_domain

VERSION = 'function-formula-system/v1'


@dataclass(frozen=True)
class SystemSource:
    variable: sp.Symbol
    transform: sp.Expr
    a: sp.Expr
    b: sp.Expr
    rhs: sp.Expr
    domain: sp.Set
    declared: object
    requested: object
    transform_kind: str

    @property
    def determinant(self):
        return self.a**2-self.b**2

    @property
    def status(self):
        return ('insufficient_information' if self.requested is not None
                and self.requested.is_subset(self.domain) is not True else 'determined_on_domain')


def system_source(desc):
    if (desc.get('kind') != 'find_function_formula' or desc.get('function_type')
            or desc.get('extra_source_refs') or desc.get('additional_relations_ast')):
        raise NotationError('function_system.single_untyped_relation_required')
    target, relation = desc['target_ast'], desc['relation_ast']
    x = sp.Symbol(desc['variable'], real=True)
    calls = []
    visited = 0

    def collect(node, depth=0):
        nonlocal visited
        visited += 1
        if visited > 128 or depth > 16:
            raise NotationError('function_system.expression_budget')
        if node[0] == 'function_call':
            if len(node) != 3 or node[1] != target[1]:
                raise NotationError('function_system.single_unknown_function_required')
            if node not in calls:
                calls.append(node)
        for child in node[1:]:
            if isinstance(child, list):
                collect(child, depth+1)
    collect(relation)
    if relation[0] != '=' or len(calls) != 2 or target not in calls:
        raise NotationError('function_system.two_related_inputs_required')
    other = next(call for call in calls if call != target)
    phi, coordinate, holes = _rational(other[2], target[2])
    phi = sp.cancel(phi.subs(coordinate, x))
    shift = sp.cancel(phi+x)
    scale = sp.cancel(phi*x)
    if shift.is_Rational and not holes:
        _bounded(shift)
        kind, domain = 'reflection', sp.S.Reals
    elif scale.is_Rational and scale != 0 and holes == {sp.S.Zero}:
        _bounded(scale)
        kind, domain = 'reciprocal', sp.S.Reals-sp.FiniteSet(0)
    else:
        raise NotationError('function_system.involution_unsupported')
    if sp.cancel(phi.subs(x, phi)-x) != 0:
        raise NotationError('function_system.involution_required')
    if desc.get('relation_domain_ast') is not None and range_domain(desc['relation_domain_ast']) != domain:
        raise NotationError('function_system.domain_not_supported_or_not_closed')
    declared = range_domain(desc['declared_domain_ast']) if desc.get('declared_domain_ast') is not None else None
    requested = range_domain(desc['requested_domain_ast']) if desc.get('requested_domain_ast') is not None else None
    if declared is not None and domain.is_subset(declared) is not True:
        raise NotationError('function_system.declared_domain_conflict')
    if any(d is not None and d not in (domain, sp.S.Reals) for d in (declared, requested)):
        raise NotationError('function_system.extra_domain_unsupported')
    u, v = sp.symbols('_function_u _function_v', real=True)
    exponentials = {}

    def read(node):
        if node == target:
            return u
        if node == other:
            return v
        if node == target[2]:
            return x
        if node[0] == 'number' and len(node[1]) <= 80:
            return _bounded(sp.Rational(node[1]))
        if node[0] == 'neg':
            return -read(node[1])
        if node[0] not in ('+', '-', '*', '/', '^') or len(node) != 3:
            raise NotationError('function_system.expression_unsupported')
        a, b = (read(child) for child in node[1:])
        if node[0] == '/':
            if b == 0 or b.has(u, v):
                raise NotationError('function_system.divisor_unsupported')
            if b.free_symbols:
                # Original divisors may only vanish at zero, which is already
                # excluded in the reciprocal family. Do this before cancelling.
                if kind != 'reciprocal' or b.has(sp.Pow) and any(p.exp.has(x) for p in b.atoms(sp.Pow)):
                    raise NotationError('function_system.divisor_unsupported')
                num = sp.Poly(sp.cancel(b).as_numer_denom()[0], x)
                if len(num.terms()) != 1 or num.degree() > 2:
                    raise NotationError('function_system.additional_exclusion_unsupported')
            value = a/b
        elif node[0] == '^':
            if b in (1, 2):
                value = a**b
            elif a.is_Rational and 0 < a <= 100 and b.has(x) and not b.has(u, v):
                # Positive fixed base, affine or reciprocal exponent only.
                poly = sp.Poly(sp.cancel(b*x), x)
                if poly.degree() > 2 or (kind == 'reflection' and poly.nth(0) != 0):
                    raise NotationError('function_system.exponent_unsupported')
                if poly.nth(0) != 0 and poly.nth(2) != 0:
                    raise NotationError('function_system.exponent_unsupported')
                atom = sp.Pow(a, b, evaluate=False)
                if atom not in exponentials:
                    exponentials[atom] = sp.Symbol(f'_exponential{len(exponentials)}')
                if len(exponentials) > 2:
                    raise NotationError('function_system.exponential_budget')
                value = exponentials[atom]
            else:
                raise NotationError('function_system.power_unsupported')
        else:
            value = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b}[node[0]]()
        if sp.count_ops(value) > 96:
            raise NotationError('function_system.expression_budget')
        for number in value.atoms(sp.Rational):
            _bounded(number)
        return value

    residual = sp.expand(read(relation[1])-read(relation[2]))
    polynomial = sp.Poly(residual, u, v)
    a, b = polynomial.coeff_monomial(u), polynomial.coeff_monomial(v)
    if polynomial.total_degree() != 1 or not a.is_Rational or not b.is_Rational or a*b == 0:
        raise NotationError('function_system.nonzero_constant_coefficients_required')
    rhs = -polynomial.coeff_monomial(1)
    # H is a bounded Laurent polynomial plus linear positive-base exponential
    # terms. Products, fractions or nested exponentials are outside this batch.
    z = tuple(exponentials.values())
    try:
        p = sp.Poly(sp.cancel(rhs*x**2), x, *z)
        if p.degree(x) > 4 or len(p.terms()) > 24:
            raise ValueError()
        if any(sum(m[1:]) > 1 or (sum(m[1:]) and m[0] != 2) for m, _ in p.terms()):
            raise ValueError()
        for coefficient in p.coeffs():
            _bounded(coefficient)
    except (ValueError, sp.PolynomialError) as exc:
        raise NotationError('function_system.right_side_unsupported') from exc
    rhs = rhs.xreplace({symbol: expression for expression, symbol in exponentials.items()})
    return SystemSource(x, phi, _bounded(a), _bounded(b), rhs, domain, declared, requested, kind)


def available(desc):
    try:
        system_source(desc)
        return True
    except (ValueError, KeyError, TypeError, sp.PolynomialError):
        return False


def interchange(source):
    return sp.expand(source.rhs.subs(source.variable, source.transform))


def eliminate(source, rhs_swapped):
    if rhs_swapped != interchange(source):
        raise NotationError('function_system.substituted_equation_mismatch')
    if source.determinant == 0:
        consistency = sp.simplify(source.a*rhs_swapped-source.b*source.rhs)
        if consistency == 0:
            raise NotationError('function_system.insufficient_information')
        # One exact counterexample disproves a universal relation. Sampling
        # never establishes consistency or a recovered function.
        for point in (2, 3, -1, 0):
            if point in source.domain:
                value = sp.simplify(consistency.subs(source.variable, point))
                if value.is_finite is True and value.is_zero is False:
                    raise NotationError('function_system.no_solution')
        raise NotationError('function_system.degenerate_consistency_unproved')
    return sp.cancel((source.a*source.rhs-source.b*rhs_swapped)/source.determinant)


def recover_system(desc):
    s = system_source(desc)
    return result_for(desc, s, eliminate(s, interchange(s)))


def result_for(desc, s, expression):
    return {'kind': 'function_formula', 'derivation': 'equation_system', 'function_name': desc['function_name'],
            'variable': s.variable, 'expression': expression, 'source_domain': s.domain, 'determined_domain': s.domain,
            'declared_domain': s.declared, 'requested_domain': s.requested, 'status': s.status,
            'transform': s.transform, 'determinant': s.determinant}


def verify_system(desc, proposed):
    try:
        s = system_source(desc)
        p, x = proposed['expression'], s.variable
        if (not isinstance(p, sp.Expr) or p.free_symbols-{x} or p.has(sp.Float)
                or sp.count_ops(p) > 256 or s.determinant == 0):
            return False
        # Only original denominators may remain. Reject cancelled holes supplied
        # in an unevaluated candidate before testing the identity.
        for term in sp.preorder_traversal(p):
            if term.is_Pow and term.exp.is_negative:
                denom = term.base
                if denom.has(x):
                    poly = sp.Poly(denom, x)
                    if s.domain == sp.S.Reals or len(poly.terms()) != 1:
                        return False
        if sp.simplify(s.a*p+s.b*p.subs(x, s.transform)-s.rhs) != 0:
            return False
        # The closed involution gives the second equation at every input.
        # Its nonzero determinant proves uniqueness, including fixed points.
        return proposed == result_for(desc, s, p)
    except (ValueError, KeyError, TypeError, sp.PolynomialError):
        return False
