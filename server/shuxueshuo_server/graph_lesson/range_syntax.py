"""Bounded original-syntax families and exact domains shared by T5 stages."""

from copy import deepcopy
from fractions import Fraction

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .stage_one.function_domain import ARGUMENT, _coefficient_budget, _fixed_poly


def _expansion_degree(ast, atom):
    if ast == ARGUMENT or (atom is not None and ast == atom):
        return 1
    if ast[0] == 'number':
        return 0
    if ast[0] == '^':
        (exponent,) = _fixed_poly(ast[2], max_degree=0)
        if exponent.denominator != 1 or not 1 <= exponent <= 4:
            raise NotationError('range.positive_bounded_power_required')
        degree = _expansion_degree(ast[1], atom)*int(exponent)
    elif ast[0] == '*':
        degree = sum(_expansion_degree(child, atom) for child in ast[1:])
    else:
        degree = max((_expansion_degree(child, atom) for child in ast[1:] if isinstance(child, list)), default=0)
    if degree > 4:
        raise NotationError('range.expression_budget')
    return degree


def range_expression(ast, variable, *, atom=None, replacement=None, depth=0):
    """Bounded arithmetic with a single root/absolute-value atom; no cancellation of poles."""
    if depth > 24:
        raise NotationError('range.expression_budget')
    if ast == ARGUMENT:
        return variable
    if atom is not None and ast == atom:
        return replacement
    read = lambda item: range_expression(item, variable, atom=atom, replacement=replacement, depth=depth+1)
    if ast[0] == 'number':
        value = Fraction(ast[1])
        _coefficient_budget(value)
        return sp.Rational(value.numerator, value.denominator)
    if ast[0] == 'neg':
        return -read(ast[1])
    if ast[:2] in (['call', 'sqrt'], ['call', 'abs']):
        return (sp.sqrt if ast[1] == 'sqrt' else sp.Abs)(read(ast[2]))
    if ast[0] == '^':
        (power,) = _fixed_poly(ast[2], max_degree=0)
        if power.denominator != 1 or not 1 <= power <= 4:
            raise NotationError('range.positive_bounded_power_required')
        result = read(ast[1]) ** int(power)
    elif ast[0] in ('+', '-', '*', '/'):
        left, right = read(ast[1]), read(ast[2])
        if ast[0] == '/':
            (divisor,) = _fixed_poly(ast[2], max_degree=0)
            if not divisor:
                raise NotationError('range.undefined_expression')
        result = {'+': lambda: left+right, '-': lambda: left-right,
                  '*': lambda: left*right, '/': lambda: left/right}[ast[0]]()
    else:
        raise NotationError('range.polynomial_substitution_required')
    if sp.count_ops(result) > 256:
        raise NotationError('range.expression_budget')
    return result


def polynomial_coefficients(expression, variable, maximum=2):
    try:
        polynomial = sp.Poly(expression, variable)
    except sp.PolynomialError as exc:
        raise NotationError('range.polynomial_substitution_required') from exc
    if polynomial.degree() > maximum or any(not c.is_Rational for c in polynomial.all_coeffs()):
        raise NotationError('range.quadratic_substitution_required')
    for coefficient in polynomial.all_coeffs():
        _coefficient_budget(Fraction(int(coefficient.p), int(coefficient.q)))
    return [str(polynomial.nth(i)) for i in range(int(max(0, polynomial.degree()))+1)]


def coefficients_ast(coefficients):
    terms = []
    for degree, coefficient in enumerate(coefficients):
        if sp.Rational(coefficient) == 0:
            continue
        term = ['number', coefficient]
        if degree:
            term = ['*', term, deepcopy(ARGUMENT) if degree == 1 else ['^', deepcopy(ARGUMENT), ['number', str(degree)]]]
        terms.append(term)
    value = terms[0] if terms else ['number', '0']
    for term in terms[1:]:
        value = ['+', value, term]
    return value


def substitution_family(ast, *, relation_input=None):
    x, t = sp.symbols('_range_x _range_t', real=True)
    if relation_input is not None:
        # This route assumes the original relation holds on all real inputs.
        # Check its unsimplified RHS first: sqrt(x)^2 or 0*sqrt(x) must
        # not become an unrestricted polynomial through symbolic cancellation.
        try:
            _fixed_poly(ast, max_degree=2)
        except NotationError as exc:
            raise NotationError('range.full_real_polynomial_relation_required') from exc
        argument = relation_input
        kind, atom = 'affine', None
    else:
        atoms = []
        def visit(node):
            if node[:2] in (['call', 'sqrt'], ['call', 'abs']):
                atoms.append(node)
                return
            for child in node[1:]:
                if isinstance(child, list):
                    visit(child)
        visit(ast)
        if not atoms or any(node != atoms[0] for node in atoms):
            raise NotationError('range.single_substitution_atom_required')
        atom = atoms[0]
        kind, argument = atom[1], atom[2]
    coefficients = _fixed_poly(argument, max_degree=1)
    b = sp.Rational(str(coefficients[0]))
    a = sp.Rational(str(coefficients[1])) if len(coefficients) > 1 else sp.S.Zero
    _expansion_degree(ast, atom)
    original = range_expression(ast, x, atom=atom, replacement=t)
    if not a:
        if kind == 'affine':
            raise NotationError('range.constant_call_does_not_define_function')
        constant = sp.sqrt(b) if kind == 'sqrt' else abs(b)
        rewritten = original.subs(t, constant).subs(x, t)
        kind = 'constant'
    elif kind == 'sqrt':
        rewritten = original.subs(x, (t**2-b)/a)
    elif kind == 'abs':
        positive = sp.expand(original.subs(x, (t-b)/a))
        negative = sp.expand(original.subs(x, (-t-b)/a))
        if positive != negative:
            raise NotationError('range.absolute_preimages_disagree')
        rewritten = positive
    else:
        rewritten = original.subs(x, (t-b)/a)
    coeffs = polynomial_coefficients(sp.expand(rewritten), t)
    return {'radical': False, 'inner_ast': deepcopy(ast), 'scale': '1', 'shift': '0',
            'degree': len(coeffs)-1, 'substitution': {
                'kind': kind, 'atom_kind': atom[1] if atom is not None else 'affine',
                'argument_ast': deepcopy(argument), 'coefficients': coeffs,
                'slope': str(a), 'intercept': str(b)}}


def expression_family(ast):
    roots = []

    def visit(node):
        if node[:2] == ['call', 'sqrt']:
            roots.append(node)
            return
        for child in node[1:]:
            if isinstance(child, list):
                visit(child)

    visit(ast)
    if not roots:
        coeffs = _fixed_poly(ast, max_degree=2)
        return {'radical': False, 'inner_ast': deepcopy(ast), 'degree': len(coeffs)-1,
                'scale': '1', 'shift': '0'}
    if any(root != roots[0] for root in roots):
        raise NotationError('range.single_radical_required')
    inner = roots[0][2]
    coeffs = _fixed_poly(inner, max_degree=2)

    def replace(node):
        if node == roots[0]:
            return ARGUMENT
        if node == ARGUMENT:
            raise NotationError('range.variable_outside_radical')
        return [replace(child) if isinstance(child, list) else child for child in node]

    outer = _fixed_poly(replace(ast), max_degree=1)
    return {'radical': True, 'inner_ast': deepcopy(inner), 'degree': len(coeffs)-1,
            'scale': str(outer[1] if len(outer) > 1 else 0), 'shift': str(outer[0])}


def exact_endpoint(ast):
    """Rational arithmetic, or arithmetic in one rational square-root extension."""
    radicals = set()
    count = 0

    def read(node, depth=0):
        nonlocal count
        count += 1
        if count > 256 or depth > 24:
            raise NotationError('range.endpoint_budget')
        if node[:2] == ['call', 'sqrt']:
            (value,) = _fixed_poly(node[2], max_degree=0)
            if value < 0:
                raise NotationError('range.real_endpoint_required')
            radicals.add(value)
            if len(radicals) > 1:
                raise NotationError('range.single_surd_endpoint_required')
            return sp.sqrt(sp.Rational(value.numerator, value.denominator))
        if node[0] == 'neg':
            return -read(node[1], depth+1)
        if node[0] in ('+', '-', '*', '/'):
            left, right = read(node[1], depth+1), read(node[2], depth+1)
            if node[0] == '/' and right == 0:
                raise NotationError('range.undefined_endpoint')
            return {'+': lambda: left+right, '-': lambda: left-right,
                    '*': lambda: left*right, '/': lambda: left/right}[node[0]]()
        (value,) = _fixed_poly(node, max_degree=0)
        return sp.Rational(value.numerator, value.denominator)

    value = sp.simplify(read(ast))
    if value.is_real is not True or value.is_finite is not True or value.is_algebraic is not True:
        raise NotationError('range.real_endpoint_required')
    return value


def range_domain(ast):
    if ast == ['real']:
        return sp.S.Reals
    if ast[0] == 'set' and len(ast) == 2:
        return sp.FiniteSet(exact_endpoint(ast[1]))
    if ast[0] != 'interval' or len(ast) != 5:
        raise NotationError('range.single_interval_required')

    def endpoint(node, closed):
        if node[0] == 'infinity' or node == ['neg', ['infinity']]:
            if closed:
                raise NotationError('range.infinity_must_be_open')
            return -sp.oo if node[0] == 'neg' else sp.oo * (node[1] if len(node) > 1 else 1)
        return exact_endpoint(node)

    low, high = (endpoint(node, closed) for node, closed in zip(ast[3:], ast[1:3], strict=True))
    if low > high or low == sp.oo or high == -sp.oo:
        raise NotationError('range.invalid_interval')
    return sp.Interval(low, high, left_open=not ast[1], right_open=not ast[2])
