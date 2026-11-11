"""Exact, bounded input algebra for parity inequalities.

Inputs may be quadratic polynomials, their absolute values, or rational
expressions with numerator/denominator degree at most two on each sign cell.
Original syntax supplies guards, so cancellation never fills a denominator hole.
All signs are decided on a complete exact partition, including isolated points.
"""
from functools import lru_cache
import json

import sympy as sp

from . import function_cells as cells
from .extremum_math import domain as parse_domain

OPS = {'<': sp.Lt, '<=': sp.Le, '>': sp.Gt, '>=': sp.Ge, '=': sp.Eq, '!=': sp.Ne}


def _expression(ast, x):
    if ast == ['bound', 'function_argument']:
        return x
    if ast[0] == 'number':
        return sp.Rational(ast[1])
    if ast[0] == 'neg':
        return -_expression(ast[1], x)
    if ast[:2] == ['call', 'abs']:
        return sp.Abs(_expression(ast[2], x))
    if ast[0] == '^':
        return _expression(ast[1], x) ** cells.constant(ast[2])
    if ast[0] in ('+', '-', '*', '/'):
        a, b = (_expression(v, x) for v in ast[1:])
        return {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b, '/': lambda: a/b}[ast[0]]()
    raise ValueError('parity_ineq.input_form_unsupported')


def _polynomial_points(expr, x, degree=8):
    poly = sp.Poly(expr, x)
    if poly.degree() > degree:
        raise ValueError('parity_ineq.degree_budget')
    return set(cells.roots(poly))


def _absolute_cuts(expr, x):
    return set().union(*(_polynomial_points(a.args[0], x, 2) for a in expr.atoms(sp.Abs)))


def _rational(expr, x, sample):
    replace = {a: sp.sign(a.args[0].subs(x, sample)) * a.args[0] for a in expr.atoms(sp.Abs)}
    return sp.cancel(expr.xreplace(replace))


@lru_cache(maxsize=512)
def cut_points(expr, x):
    points = _absolute_cuts(expr, x)
    for cell, sample in cells.cells(sp.S.Reals, points):
        if isinstance(cell, sp.FiniteSet):
            continue
        value = _rational(expr, x, sample)
        for part in sp.fraction(value):
            points |= _polynomial_points(part, x)
    if len(points) > cells.MAX_CUTS:
        raise ValueError('parity_ineq.cell_budget')
    return frozenset(points)


def read(ast, x):
    return _read(json.dumps(ast), x)


@lru_cache(maxsize=512)
def _read(serialized, x):
    ast = json.loads(serialized)
    for node in cells.walk(ast):
        if node[0] not in ('bound', 'number', 'neg', '+', '-', '*', '/', '^', 'call'):
            raise ValueError('parity_ineq.input_form_unsupported')
        if node[0] == 'call' and node[1] != 'abs':
            raise ValueError('parity_ineq.input_form_unsupported')
    cells.inspect(ast)
    expr = _expression(ast, x)
    if expr.has(sp.nan, sp.zoo, sp.oo, -sp.oo):
        raise ValueError('parity_ineq.undefined_input')
    for cell, sample in cells.cells(cells.natural_domain(ast), cells.cuts(ast)):
        if isinstance(cell, sp.Interval):
            for part in sp.fraction(_rational(expr, x, sample)):
                if sp.Poly(part, x).degree() > 2:
                    raise ValueError('parity_ineq.degree_budget')
    cut_points(expr, x)
    return sp.cancel(sp.expand(expr))


@lru_cache(maxsize=1024)
def condition(expr, op, x):
    pieces = []
    for cell, sample in cells.cells(sp.S.Reals, cut_points(expr, x)):
        value = sp.simplify(expr.subs(x, sample))
        if value.is_real is True and value.is_finite is True and bool(OPS[op](value, 0)):
            pieces.append(cell)
    return sp.Union(*pieces)


def preimage(expr, x, target):
    if target == sp.S.EmptySet:
        return target
    if target == sp.S.Reals:
        return condition(expr, '>=', x) | condition(expr, '<', x)
    if isinstance(target, sp.FiniteSet):
        return sp.Union(*(condition(expr-p, '=', x) for p in target))
    if isinstance(target, sp.Union):
        return sp.Union(*(preimage(expr, x, p) for p in target.args))
    if not isinstance(target, sp.Interval):
        raise ValueError('parity_ineq.input_set_unsupported')
    result = preimage(expr, x, sp.S.Reals)
    if target.start != -sp.oo:
        result &= condition(expr-target.start, '>' if target.left_open else '>=', x)
    if target.end != sp.oo:
        result &= condition(expr-target.end, '<' if target.right_open else '<=', x)
    return result


def guard(asts, x):
    result = sp.S.Reals
    for ast in asts:
        read(ast, x)
        result &= cells.natural_domain(ast)
    return result


def constraint_rows(entries, variable):
    from .parity_order_math import _calls, _scalars
    return [r for r in entries if (r['ast'][0] in (*OPS, 'and', 'or', '∈')
                                  or r['ast'][0] == 'default_domain' and r['ast'][2] == 'real')
            and not _calls(r['ast']) and _scalars(r['ast'])
            and all(ref.rsplit(':', 1)[-1] == variable for ref in _scalars(r['ast']))]


def _constraint(ast, x):
    from .parity_order_math import _bound
    if ast[0] == 'default_domain' and ast[2] == 'real':
        _bound(ast[1], str(x))
        return sp.S.Reals
    if ast[0] in ('and', 'or'):
        a, b = (_constraint(p, x) for p in ast[1:])
        return a & b if ast[0] == 'and' else a | b
    if ast[0] == '∈':
        bound = _bound(ast[1], str(x))
        return guard([bound], x) & preimage(read(bound, x), x, parse_domain(ast[2]))
    if ast[0] not in OPS:
        raise ValueError('parity_ineq.input_condition_unsupported')
    a, b = (_bound(p, str(x)) for p in ast[1:])
    return guard([a, b], x) & condition(read(a, x)-read(b, x), ast[0], x)


def requested(desc, x):
    from ..problem_understanding.notation_parser import parse
    source = parse(desc['source'].get('input_domain', 'ℝ'))
    # Interval notation denotes an interval of positive length; a set literal
    # may still describe isolated points.
    if source[0] in ('interval', 'tuple'):
        lo, hi = source[-2:]
        if cells.constant(lo) >= cells.constant(hi):
            raise ValueError('parity_ineq.invalid_input_interval')
    result = parse_domain(source)
    for row in constraint_rows(desc['given_entries'], str(x)):
        result &= _constraint(row['ast'], x)
    return result


def allowed(desc, asts, x):
    return requested(desc, x) & guard(asts, x)


def source_points(asts):
    return set().union(*(cells.cuts(ast) for ast in asts))


def matches(claimed, cell, truth):
    return cell.is_subset(claimed) is True if truth else (cell & claimed) == sp.S.EmptySet
