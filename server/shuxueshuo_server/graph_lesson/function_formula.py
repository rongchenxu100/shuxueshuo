"""Bounded A0–A2 mathematics: root, affine and linear fractional inputs.

Only inert bound ASTs are read. Admission inspects original syntax before any
cancellation. Verification re-reads those ASTs and proves polynomial identity
and surjectivity, independently of the recovering substitution algorithm.
"""

from dataclasses import dataclass

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .range_syntax import range_domain

VERSION = 'function-formula-substitution/v3'
SOURCE_DOMAIN = sp.Interval(0, sp.oo)


def _bounded(value, bits=64):
    if (value.is_Rational is not True or
            max(abs(int(value.p)).bit_length(), int(value.q).bit_length()) > bits):
        raise NotationError('function_formula.coefficient_budget')
    return value


def _polynomial(ast, variable, *, root_input):
    """Read inert polynomial syntax before cancellation can erase domain holes."""
    s = sp.Symbol('_root', nonnegative=True) if root_input else sp.Symbol('_input', real=True)
    count = 0

    def read(node, depth=0):
        nonlocal count
        count += 1
        if count > 128 or depth > 16:
            raise NotationError('function_formula.expression_budget')
        if node == variable:
            return s**2 if root_input else s
        if root_input and node == ['call', 'sqrt', variable]:
            return s
        if node[0] == 'number':
            # Check text size before constructing a potentially huge integer.
            if len(node[1]) > 80:
                raise NotationError('function_formula.coefficient_budget')
            return _bounded(sp.Rational(node[1]))
        if node[0] == 'neg':
            return -read(node[1], depth+1)
        if node[0] not in ('+', '-', '*', '/', '^') or len(node) != 3:
            raise NotationError('function_formula.root_polynomial_required')
        a, b = (read(child, depth+1) for child in node[1:])
        if node[0] == '/':
            if b.free_symbols or b == 0:
                raise NotationError('function_formula.constant_nonzero_denominator_required')
            value = a/b
        elif node[0] == '^':
            if b not in (1, 2) and not (b == 0 and a.is_nonzero is True):
                raise NotationError('function_formula.power_unsupported')
            value = a**b
        else:
            value = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b}[node[0]]()
        value = sp.Poly(value, s)
        if value.degree() > 4:
            raise NotationError('function_formula.degree_budget')
        for coefficient in value.all_coeffs():
            _bounded(coefficient)
        return value.as_expr()

    return sp.Poly(read(ast), s)


def _rational_parts(value, variable, degree=4):
    numerator, denominator = sp.cancel(value).as_numer_denom()
    parts = [sp.Poly(part, variable) for part in (numerator, denominator)]
    for part in parts:
        if part.degree() > degree:
            raise NotationError('function_formula.degree_budget')
        for coefficient in part.all_coeffs():
            _bounded(coefficient)
    return parts


def _real_zeros(value, variable):
    """A2 admits rational holes only; never approximate an excluded input."""
    polynomial = sp.Poly(value, variable)
    if polynomial.is_zero or polynomial.degree() > 2:
        raise NotationError('function_formula.divisor_unsupported')
    zeros = set()
    for root in sp.roots(polynomial):
        if root.is_real is False:
            continue
        if root.is_real is not True or root.is_Rational is not True:
            raise NotationError('function_formula.irrational_exclusion_unsupported')
        zeros.add(_bounded(root))
    return zeros


def _rational(ast, variable):
    """Track every original divisor, including factors later cancelled out."""
    s, excluded = sp.Symbol('_input', real=True), set()

    def read(node):
        if node == variable:
            return s
        if node[0] == 'number':
            if len(node[1]) > 80:
                raise NotationError('function_formula.coefficient_budget')
            return _bounded(sp.Rational(node[1]))
        if node[0] == 'neg':
            return -read(node[1])
        if node[0] not in ('+', '-', '*', '/', '^') or len(node) != 3:
            raise NotationError('function_formula.rational_required')
        a, b = (read(child) for child in node[1:])
        if node[0] == '/':
            excluded.update(_real_zeros(b.as_numer_denom()[0], s))
            if len(excluded) > 4:
                raise NotationError('function_formula.exclusion_budget')
            value = a/b
        elif node[0] == '^':
            if b not in (1, 2) and not (b == 0 and a.is_nonzero is True):
                raise NotationError('function_formula.power_unsupported')
            value = a**b
        else:
            value = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b}[node[0]]()
        numerator, denominator = _rational_parts(value, s)
        return numerator.as_expr()/denominator.as_expr()

    return read(ast), s, excluded


@dataclass(frozen=True)
class FormulaSource:
    a: sp.Expr
    b: sp.Expr
    rhs: sp.Expr
    image: sp.Set
    declared: sp.Set | None
    requested: sp.Set | None
    root_input: bool
    coordinate: sp.Symbol
    c: sp.Expr = sp.S.Zero
    d: sp.Expr = sp.S.One
    excluded_inputs: frozenset = frozenset()

    @property
    def rational_input(self):
        return self.c != 0

    @property
    def domain(self):
        return SOURCE_DOMAIN if self.root_input else sp.S.Reals - sp.FiniteSet(*self.excluded_inputs)

    @property
    def status(self):
        return ('insufficient_information' if self.requested is not None
                and self.requested.is_subset(self.image) is not True else 'determined_on_domain')

    def expressions(self, x):
        coordinate = sp.sqrt(x) if self.root_input else x
        return self.input_at(coordinate), self.rhs.subs(self.coordinate, coordinate)

    def input_at(self, coordinate):
        return (self.a*coordinate+self.b)/(self.c*coordinate+self.d)

    def inverse_coordinate(self, t):
        return (self.d*t-self.b)/(self.a-self.c*t)

    def inverse_input(self, t):
        inverse = self.inverse_coordinate(t)
        return inverse**2 if self.root_input else inverse

    def rewrite(self, t):
        value = self.rhs.subs(self.coordinate, self.inverse_coordinate(t))
        if not self.rational_input:
            return sp.expand(value)
        numerator, denominator = sp.cancel(value).as_numer_denom()
        # Prefer a positive constant term in a fractional denominator, e.g. 1-t.
        if denominator.subs(t, 0) < 0:
            numerator, denominator = -numerator, -denominator
        return numerator/denominator


def source_values(description):
    relation, target = description['relation_ast'], description['target_ast']
    if (relation[0] != '=' or len(relation) != 3 or relation[1][0] != 'function_call'
            or len(relation[1]) != 3 or relation[1][1] != target[1]):
        raise NotationError('function_formula.single_composite_input_required')
    if description.get('extra_source_refs') or description.get('function_type') or description.get('additional_relations_ast'):
        raise NotationError('function_formula.extra_conditions_unsupported')
    # One combined AST budget, including call/ref nodes.
    def budget(node, depth=0):
        if depth > 16:
            raise NotationError('function_formula.expression_budget')
        return 1 + sum(budget(x, depth+1) for x in node[1:] if isinstance(x, list))
    if budget(relation) > 128:
        raise NotationError('function_formula.expression_budget')
    def contains_root(node):
        return (node[:2] == ['call', 'sqrt'] or
                any(contains_root(child) for child in node[1:] if isinstance(child, list)))
    root_input = contains_root(relation[1][2])
    c, d, excluded = sp.S.Zero, sp.S.One, set()
    try:
        inner = _polynomial(relation[1][2], target[2], root_input=root_input)
    except NotationError as exc:
        if root_input or exc.code != 'function_formula.constant_nonzero_denominator_required':
            raise
        inner = None
    if inner is not None:
        rhs = _polynomial(relation[2], target[2], root_input=root_input)
        if inner.degree() > 1 or rhs.degree() > 2:
            raise NotationError('function_formula.affine_input_required')
        a, b = inner.nth(1), inner.nth(0)
        if a == 0:
            reason = 'inconsistent_constant_input' if rhs.degree() > 0 else 'only_one_function_value_determined'
            raise NotationError('function_formula.' + reason)
        coordinate, rhs = rhs.gen, rhs.as_expr()
        image = (sp.Interval(b, sp.oo) if a > 0 else sp.Interval(-sp.oo, b)) if root_input else sp.S.Reals
    else:
        inner, coordinate, input_holes = _rational(relation[1][2], target[2])
        rhs, _, rhs_holes = _rational(relation[2], target[2])
        numerator, denominator = _rational_parts(inner, coordinate, degree=1)
        a, b, c, d = numerator.nth(1), numerator.nth(0), denominator.nth(1), denominator.nth(0)
        if c == 0 or a*d-b*c == 0:
            raise NotationError('function_formula.nondegenerate_fractional_input_required')
        _rational_parts(rhs, coordinate, degree=2)
        excluded = input_holes | rhs_holes
        if len(excluded) > 4:
            raise NotationError('function_formula.exclusion_budget')
        omitted = {a/c} | {inner.subs(coordinate, value) for value in excluded if c*value+d != 0}
        for value in omitted:
            _bounded(value)
        image = sp.S.Reals - sp.FiniteSet(*omitted)
    domain = SOURCE_DOMAIN if root_input else sp.S.Reals - sp.FiniteSet(*excluded)
    domain_ast = description.get('relation_domain_ast')
    if domain_ast is not None and range_domain(domain_ast) != domain:
        raise NotationError('function_formula.additional_source_restriction_unsupported')
    declared_ast = description.get('declared_domain_ast')
    declared = range_domain(declared_ast) if declared_ast else None
    requested_ast = description.get('requested_domain_ast')
    requested = range_domain(requested_ast) if requested_ast else None
    if declared is not None and image.is_subset(declared) is not True:
        raise NotationError('function_formula.declared_domain_conflict')
    if requested is not None and declared is not None and requested.is_subset(declared) is not True:
        raise NotationError('function_formula.requested_domain_conflict')
    if requested is not None and requested != image and requested != sp.S.Reals:
        raise NotationError('function_formula.requested_domain_unsupported')
    return FormulaSource(a, b, rhs, image, declared, requested, root_input, coordinate, c, d, frozenset(excluded))


def recover(description):
    source = source_values(description)
    t = sp.Symbol('t' if description['variable'] != 't' else 'z', real=True)
    inverse = source.inverse_coordinate(t)
    formula = source.rewrite(t)
    return {'kind': 'function_formula', 'function_name': description['function_name'],
            'variable': t, 'expression': formula, 'source_domain': source.domain,
            'determined_domain': source.image, 'declared_domain': source.declared, 'requested_domain': source.requested,
            'inverse_root': inverse if source.root_input else None, 'inverse_input': source.inverse_input(t),
            'status': source.status}


def verify(description, proposed):
    """Rebuild source identity and image; never call recover or trust its inverse."""
    try:
        source = source_values(description)
        if set(proposed) != {'kind', 'function_name', 'variable', 'expression', 'source_domain',
                             'determined_domain', 'declared_domain', 'requested_domain',
                             'inverse_root', 'inverse_input', 'status'}:
            return False
        t, expression = proposed['variable'], proposed['expression']
        if (not isinstance(t, sp.Symbol) or not isinstance(expression, sp.Expr)
                or expression.free_symbols - {t} or expression.has(sp.Float)
                or sp.count_ops(expression) > 256):
            return False
        # Both the formula and the proposed coverage witness must exist at every
        # determined input, including factors that could cancel algebraically.
        for observed in (expression, proposed['inverse_input'], proposed['inverse_root']):
            if observed is None:
                continue
            if (not isinstance(observed, sp.Expr) or observed.free_symbols - {t}
                    or observed.has(sp.Float) or sp.count_ops(observed) > 256):
                return False
            _rational_parts(observed, t, degree=2)
            for part in sp.preorder_traversal(observed):
                if part.is_Pow and part.exp.is_negative:
                    zeros = _real_zeros(part.base.as_numer_denom()[0], t)
                    if any(source.image.contains(zero) is not sp.S.false for zero in zeros):
                        return False
        s = source.coordinate
        identity = sp.cancel(expression.subs(t, source.input_at(s))-source.rhs) == 0
        inverse = proposed['inverse_root'] if source.root_input else proposed['inverse_input']
        original = inverse**2 if source.root_input else inverse
        coverage = (sp.cancel(source.input_at(inverse)-t) == 0
                    and sp.cancel(proposed['inverse_input']-original) == 0
                    and sp.cancel(inverse-source.inverse_coordinate(t)) == 0
                    and (source.root_input or proposed['inverse_root'] is None))
        range_correct = proposed['determined_domain'] == source.image
        return bool(identity and coverage and range_correct
                    and proposed['source_domain'] == source.domain
                    and proposed['declared_domain'] == source.declared and proposed['requested_domain'] == source.requested
                    and proposed['kind'] == 'function_formula'
                    and proposed['function_name'] == description['function_name']
                    and proposed['status'] == source.status)
    except (KeyError, TypeError, ValueError, NotationError, sp.PolynomialError):
        return False
