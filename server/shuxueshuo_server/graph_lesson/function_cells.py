"""Opt-in exact real-function cells, preserving original guards and branch rules.

This version accepts rational coefficients and real quadratic algebraic cut
points. Existing rational-only domain consumers retain their admission rules.
Domain production intersects original guards; verification evaluates the source
on a complete partition. Identity certificates cover every cell of the given
domain, including isolated points, and never infer equality from samples.
"""

from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from itertools import pairwise

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .function_equality import _rational_op, _rational_power
from .piecewise_evaluation import is_piecewise
from .stage_one.function_domain import (
    ARGUMENT,
    _coefficient_budget,
    _fixed_poly,
    _integer_exponent,
)
from .stage_three.function_domain import _evaluate
from .stage_three.verification import _rational_between

VERSION = 'original-function-cells/v1'
X = sp.Symbol('u', real=True)
MAX_CUTS = 48
MAX_BRANCHES = 6


def fail(reason):
    raise NotationError('function_cells.' + reason)


def same_set(a, b):
    return a - b == sp.S.EmptySet and b - a == sp.S.EmptySet


def reflect_set(value):
    """Reflect every component and its endpoint ownership in the origin."""
    if value in (sp.S.Reals, sp.S.EmptySet):
        return value
    if isinstance(value, sp.Interval):
        return sp.Interval(-value.end, -value.start, value.right_open, value.left_open)
    if isinstance(value, sp.FiniteSet):
        return sp.FiniteSet(*(-point for point in value))
    if isinstance(value, (sp.Union, sp.Intersection, sp.Complement)):
        return value.func(*(reflect_set(part) for part in value.args))
    fail('set_reflection_unsupported')


def exact_point(value):
    if value.is_real is not True or value.free_symbols or value.is_finite is not True:
        fail('real_finite_endpoint_required')
    if value.is_Rational:
        _coefficient_budget(Fraction(value))
    else:
        minimum = sp.Poly(sp.minpoly(value))
        if minimum.degree() > 2:
            fail('quadratic_endpoint_required')
        for coefficient in minimum.all_coeffs():
            _coefficient_budget(Fraction(coefficient))
    return value


def polynomial(ast, degree=6):
    coefficients = _fixed_poly(ast, max_degree=degree)
    return sp.Poly(sum((sp.Rational(c) * X**i for i, c in enumerate(coefficients)), sp.S.Zero), X)


@lru_cache(maxsize=256)
def roots(poly):
    if poly.is_zero or poly.degree() <= 0:
        return []
    points = sorted(set(poly.real_roots()))
    if len(points) > MAX_CUTS or poly.count_roots(-sp.oo, sp.oo) != len(points):
        fail('root_coverage')
    for point in points:
        exact_point(point)
        if sp.simplify(poly.eval(point)) != 0:
            fail('invalid_root')
    return points


def constant(ast):
    if ast == ['infinity']:
        return sp.oo
    if ast == ['neg', ['infinity']]:
        return -sp.oo
    if ast == ARGUMENT or ast[0] == 'ref':
        fail('fixed_endpoint_required')
    if any(node == ARGUMENT for node in walk(ast)):
        fail('fixed_endpoint_required')
    try:
        valid, value = _evaluate(ast, sp.S.Zero)
    except (KeyError, TypeError, IndexError):
        fail('fixed_endpoint_required')
    if not valid:
        fail('undefined_endpoint')
    return exact_point(sp.simplify(value))


def input_set(ast, *, budget=None):
    budget = budget if budget is not None else {'intervals': 0, 'points': 0}
    if ast == ['real']:
        return sp.S.Reals
    if ast[0] in ('∪', '∩', 'set_difference'):
        a, b = (input_set(part, budget=budget) for part in ast[1:])
        return {'∪': lambda: a | b, '∩': lambda: a & b, 'set_difference': lambda: a - b}[ast[0]]()
    if ast[0] == 'set':
        budget['points'] += len(ast) - 1
        if budget['points'] > 16:
            fail('point_budget')
        return sp.FiniteSet(*(constant(point) for point in ast[1:]))
    if ast[0] != 'interval':
        fail('explicit_set_required')
    budget['intervals'] += 1
    if budget['intervals'] > 8:
        fail('interval_budget')
    a, b = map(constant, ast[3:])
    if (a in (-sp.oo, sp.oo) and ast[1]) or (b in (-sp.oo, sp.oo) and ast[2]):
        fail('infinity_must_be_open')
    return sp.Interval(a, b, left_open=not ast[1], right_open=not ast[2])


def walk(ast):
    yield ast
    for child in ast[1:]:
        if isinstance(child, list):
            yield from walk(child)


def sign_set(poly, operator):
    checks = {'=': lambda v: v == 0, '!=': lambda v: v != 0,
              '>': lambda v: v > 0, '>=': lambda v: v >= 0,
              '<': lambda v: v < 0, '<=': lambda v: v <= 0}
    return sp.Union(*(cell for cell, sample in cells(sp.S.Reals, roots(poly))
                      if checks[operator](sp.simplify(poly.eval(sample))) == True))


def condition_set(ast):
    if ast[0] in ('and', 'or'):
        a, b = (condition_set(part) for part in ast[1:])
        return a & b if ast[0] == 'and' else a | b
    if ast[0] in ('=', '!=', '<', '<=', '>', '>='):
        return sign_set(polynomial(['-', ast[1], ast[2]], 2), ast[0])
    if ast[0] == '∈':
        if ast[1] == ARGUMENT:
            return input_set(ast[2])
        if ast[1] == ['neg', ARGUMENT]:
            return reflect_set(input_set(ast[2]))
    fail('branch_condition_unsupported')


def branches(ast):
    if not is_piecewise(ast) or len(ast) % 2 or not 1 <= (len(ast) - 2) // 2 <= MAX_BRANCHES:
        fail('branch_budget')
    rows, covered = [], sp.S.EmptySet
    for index in range(2, len(ast), 2):
        domain = condition_set(ast[index + 1])
        if domain == sp.S.EmptySet or domain & covered != sp.S.EmptySet:
            fail('empty_or_overlapping_branches')
        covered |= domain
        rows.append((ast[index], domain))
    return rows


def zero_polynomials(ast):
    """All possible zeroes of an admitted divisor, before cancellation."""
    if ast[0] == 'neg':
        return zero_polynomials(ast[1])
    if ast[:2] in (['call', 'sqrt'], ['call', 'abs']):
        return [polynomial(ast[2])]
    if ast[0] in ('*', '/'):
        return zero_polynomials(ast[1]) + zero_polynomials(ast[2])
    if ast[0] == '^':
        return zero_polynomials(ast[1])
    return [polynomial(ast)]


def inspect(ast):
    count = 0

    def visit(node, depth=0, in_branch=False, power_weight=1):
        nonlocal count
        count += 1
        if count > 256 or depth > 24 or power_weight > 24:
            fail('structure_budget')
        if node == ARGUMENT:
            return
        kind = node[0]
        if kind == 'number':
            _coefficient_budget(Fraction(node[1]))
            return
        if is_piecewise(node):
            if in_branch:
                fail('nested_piecewise_unsupported')
            for body, _ in branches(node):
                visit(body, depth + 1, True, power_weight)
            return
        if kind == 'call':
            if node[1] not in ('abs', 'sqrt'):
                fail('call_unsupported')
            base = node[2]
            if node[1] == 'sqrt' and base[0] == '^' and _integer_exponent(base[2]) == 2:
                roots(polynomial(base[1], 2))
            else:
                roots(polynomial(base, 2))
            visit(base, depth + 1, in_branch, power_weight)
            return
        if kind == '/':
            for poly in zero_polynomials(node[2]):
                roots(poly)
        if kind == '^':
            exponent = _integer_exponent(node[2])
            if exponent == 0:
                for poly in zero_polynomials(node[1]):
                    roots(poly)
            visit(node[1], depth + 1, in_branch, power_weight * max(1, exponent))
            return
        if kind not in ('neg', '+', '-', '*', '/'):
            fail('expression_unsupported')
        for child in node[1:]:
            visit(child, depth + 1, in_branch, power_weight)

    visit(ast)


def boundaries(domain):
    boundary = domain.boundary
    if not isinstance(boundary, sp.FiniteSet) and boundary != sp.S.EmptySet:
        fail('finite_boundary_required')
    return list(boundary)


def cuts(ast):
    points = set()
    for node in walk(ast):
        if is_piecewise(node):
            for _, domain in branches(node):
                points.update(boundaries(domain))
        if node[:2] in (['call', 'sqrt'], ['call', 'abs']):
            points.update(roots(polynomial(node[2])))
        if node[0] == '/':
            for poly in zero_polynomials(node[2]):
                points.update(roots(poly))
        if node[0] == '^' and _integer_exponent(node[2]) == 0:
            for poly in zero_polynomials(node[1]):
                points.update(roots(poly))
    if len(points) > MAX_CUTS:
        fail('cell_budget')
    return points


def cells(domain, points=()):
    points = sorted({*points, *boundaries(domain)})
    if len(points) > MAX_CUTS:
        fail('cell_budget')
    result = []
    for i, (a, b) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        cell = sp.Interval.open(a, b) & domain
        if cell != sp.S.EmptySet:
            if not isinstance(cell, sp.Interval):
                fail('incomplete_partition')
            result.append((cell, _rational_between(cell.start, cell.end)))
        if i < len(points) and domain.contains(points[i]) is sp.true:
            result.append((sp.FiniteSet(points[i]), points[i]))
    if not same_set(sp.Union(*(cell for cell, _ in result)), domain):
        fail('incomplete_partition')
    return result


def evaluate(ast, point):
    if is_piecewise(ast):
        selected = [body for body, domain in branches(ast) if domain.contains(point) is sp.true]
        return evaluate(selected[0], point) if len(selected) == 1 else (False, None)
    if ast[0] == 'neg':
        valid, value = evaluate(ast[1], point)
        return valid, -value if valid else None
    if ast[0] == '^':
        valid, value = evaluate(ast[1], point)
        exponent = _integer_exponent(ast[2])
        if not valid or (exponent == 0 and sp.simplify(value) == 0):
            return False, None
        return True, value**exponent
    if ast[0] in ('+', '-', '*', '/'):
        ok_a, a = evaluate(ast[1], point)
        ok_b, b = evaluate(ast[2], point)
        if not ok_a or not ok_b or (ast[0] == '/' and sp.simplify(b) == 0):
            return False, None
        return True, {'+': lambda: a + b, '-': lambda: a - b,
                      '*': lambda: a * b, '/': lambda: a / b}[ast[0]]()
    return _evaluate(ast, point)


def _nonzero_domain(ast):
    # A reciprocal of a reciprocal still retains both original guards.
    if ast[0] == 'neg':
        return _nonzero_domain(ast[1])
    if ast[:2] in (['call', 'sqrt'], ['call', 'abs']):
        return sign_set(polynomial(ast[2]), '!=')
    if ast[0] in ('*', '/'):
        return _nonzero_domain(ast[1]) & _nonzero_domain(ast[2])
    if ast[0] == '^':
        return _nonzero_domain(ast[1])
    return sign_set(polynomial(ast), '!=')


def natural_domain(ast):
    if is_piecewise(ast):
        return sp.Union(*(condition & natural_domain(body) for body, condition in branches(ast)))
    if ast == ARGUMENT or ast[0] == 'number':
        return sp.S.Reals
    if ast[0] == 'neg':
        return natural_domain(ast[1])
    if ast[:2] == ['call', 'sqrt']:
        return natural_domain(ast[2]) & sign_set(polynomial(ast[2]), '>=')
    if ast[:2] == ['call', 'abs']:
        return natural_domain(ast[2])
    if ast[0] == '^':
        return natural_domain(ast[1]) & (_nonzero_domain(ast[1]) if _integer_exponent(ast[2]) == 0 else sp.S.Reals)
    domain = natural_domain(ast[1]) & natural_domain(ast[2])
    return domain & _nonzero_domain(ast[2]) if ast[0] == '/' else domain


def _effective(function, natural):
    given = input_set(function.get('input_domain_ast', ['real']))
    if function.get('domain_role', 'declared') == 'declared' and function.get('explicit_domain') and given - natural != sp.S.EmptySet:
        fail('declared_domain_conflict')
    domain = given & natural
    if domain == sp.S.EmptySet:
        fail('empty_function_domain')
    return domain


def source_domain(function):
    """Verifier: original point evaluation on every sign-invariant cell."""
    ast = function['expression_ast']
    inspect(ast)
    rows = [(cell, sample, evaluate(ast, sample)[0]) for cell, sample in cells(sp.S.Reals, cuts(ast))]
    natural = sp.Union(*(cell for cell, _, valid in rows if valid))
    return _effective(function, natural), natural


def solve_domain(function):
    ast = function['expression_ast']
    inspect(ast)
    natural = natural_domain(ast)
    domain = _effective(function, natural)
    checked, checked_natural = source_domain(function)
    if not same_set(checked, domain) or not same_set(natural, checked_natural):
        fail('domain_verification_failed')
    return {'version': VERSION, 'function_ref': function['function_ref'], 'source_ref': function['source_ref'],
            'expression_ast': deepcopy(ast), 'input_domain_ast': deepcopy(function.get('input_domain_ast', ['real'])),
            'domain': domain, 'natural_domain': natural}


def _signed(poly, cell, sample, *, verifying):
    # Independent root isolation checks that no sign change was omitted.
    if verifying and not poly.is_zero and any(cell.contains(root) is sp.true for root in poly.real_roots()):
        fail('sign_not_invariant')
    sign = sp.sign(sp.simplify(poly.eval(sample)))
    if sign not in (-1, 0, 1) or (sign == 0 and not poly.is_zero):
        fail('sign_unknown')
    return sign * poly.as_expr()


def normal_form(ast, cell, sample, *, verifying=False):
    if isinstance(cell, sp.FiniteSet):
        valid, value = evaluate(ast, sample)
        if not valid:
            fail('undefined_comparison_point')
        return sp.simplify(value)
    if is_piecewise(ast):
        selected = [body for body, domain in branches(ast) if cell - domain == sp.S.EmptySet]
        if len(selected) != 1:
            fail('branch_not_invariant')
        return normal_form(selected[0], cell, sample, verifying=verifying)
    if ast == ARGUMENT:
        return X
    kind = ast[0]
    if kind == 'number':
        return sp.Rational(ast[1])
    if kind == 'neg':
        return -normal_form(ast[1], cell, sample, verifying=verifying)
    if ast[:2] == ['call', 'abs']:
        return _signed(polynomial(ast[2]), cell, sample, verifying=verifying)
    if ast[:2] == ['call', 'sqrt']:
        radicand = polynomial(ast[2])
        # sqrt(Q²) is |Q|, including expanded perfect squares.
        root = sp.polys.polytools.sqf_list(radicand)
        coefficient, factors = root
        if coefficient >= 0 and all(power % 2 == 0 for _, power in factors):
            base = sp.Poly(sp.prod(p.as_expr() ** (n // 2) for p, n in factors), X)
            return sp.sqrt(coefficient) * _signed(base, cell, sample, verifying=verifying)
        return sp.sqrt(radicand.as_expr())
    left = normal_form(ast[1], cell, sample, verifying=verifying)
    if kind == '^':
        n = _integer_exponent(ast[2])
        return _rational_power(left, n) if _over_rationals(left) else left**n
    right = normal_form(ast[2], cell, sample, verifying=verifying)
    if _over_rationals(left) and _over_rationals(right):
        return _rational_op(left, right, kind)
    return {'+': lambda: left + right, '-': lambda: left - right,
            '*': lambda: left * right, '/': lambda: left / right}[kind]()


def _over_rationals(value):
    try:
        numerator, denominator = value.as_numer_denom()
        sp.Poly(numerator, X, domain=sp.QQ)
        sp.Poly(denominator, X, domain=sp.QQ)
    except (sp.PolynomialError, sp.CoercionFailed):
        return False
    return True


def compare_on_domain(left, right, domain):
    """Prove identity cell by cell, or return one exact counterexample."""
    inspect(left)
    inspect(right)
    partition = cells(domain, cuts(left) | cuts(right))
    proof = []
    for cell, sample in partition:
        a, b = normal_form(left, cell, sample), normal_form(right, cell, sample)
        if sp.simplify(a - b) == 0:
            proof.append({'domain': cell, 'sample': sample, 'left': a, 'right': b})
            continue
        for point in [sample, *([sample + sp.Rational(n, 7) for n in range(-12, 13)] if isinstance(cell, sp.Interval) else [])]:
            if cell.contains(point) is not sp.true:
                continue
            ok_a, av = evaluate(left, point)
            ok_b, bv = evaluate(right, point)
            if ok_a and ok_b and sp.simplify(av - bv).is_zero is False:
                return {'relation': 'different', 'point': point}
        return {'relation': 'unresolved'}
    return {'relation': 'equal', 'version': VERSION, 'domain': domain,
            'left_ast': deepcopy(left), 'right_ast': deepcopy(right), 'cells': proof}


def verify_identity(left, right, domain, certificate):
    """Consume coverage/identity evidence without invoking the producer."""
    if (certificate.get('relation') != 'equal' or certificate.get('version') != VERSION
            or certificate.get('left_ast') != left or certificate.get('right_ast') != right
            or not same_set(certificate['domain'], domain)):
        fail('identity_binding')
    for ast in (left, right):
        inspect(ast)
        if domain - natural_domain(ast) != sp.S.EmptySet:
            fail('identity_outside_domain')
    covered = sp.S.EmptySet
    required = cuts(left) | cuts(right)
    for row in certificate['cells']:
        cell, sample = row['domain'], row['sample']
        if cell == sp.S.EmptySet or cell - domain != sp.S.EmptySet or cell & covered != sp.S.EmptySet:
            fail('identity_coverage')
        if not isinstance(cell, (sp.Interval, sp.FiniteSet)) or cell.contains(sample) is not sp.true:
            fail('identity_cell')
        if isinstance(cell, sp.FiniteSet) and cell != sp.FiniteSet(sample):
            fail('identity_point_coverage')
        if isinstance(cell, sp.Interval) and any(cell.contains(point) is sp.true for point in required):
            fail('identity_missing_cut')
        a = normal_form(left, cell, sample, verifying=True)
        b = normal_form(right, cell, sample, verifying=True)
        if (sp.simplify(a - row['left']) != 0 or sp.simplify(b - row['right']) != 0 or sp.simplify(a - b) != 0):
            fail('identity_not_proved')
        covered |= cell
    if not same_set(covered, domain):
        fail('identity_coverage')
    return True
