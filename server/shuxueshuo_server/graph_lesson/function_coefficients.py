"""Bounded polynomial identities for a stated linear/quadratic unknown function.

Admission expands source syntax only. It never solves for coefficients. Recovery
solves a finite polynomial system; the verifier independently rebuilds every
source equality and uses a second set solver to check completeness, not samples.
"""
from dataclasses import dataclass

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .function_formula import _bounded
from .range_syntax import range_domain


@dataclass(frozen=True)
class CoefficientSource:
    variable: sp.Symbol
    coefficients: tuple
    template: sp.Expr
    relations: tuple
    requested: object
    kind: str


def coefficient_source(desc):
    if desc.get('function_type') not in ('linear', 'quadratic') or desc.get('extra_source_refs'):
        raise NotationError('function_coefficients.stated_type_required')
    for key in ('relation_domain_ast', 'declared_domain_ast', 'requested_domain_ast'):
        if desc.get(key) is not None and range_domain(desc[key]) != sp.S.Reals:
            raise NotationError('function_coefficients.real_identity_required')
    target = desc['target_ast']
    x = sp.Symbol(desc['variable'], real=True)
    # Avoid collisions with the student's variable/function names.
    names = [n for n in ('a', 'b', 'c', 'k', 'm') if n not in (desc['variable'], desc['function_name'])]
    count = 2 if desc['function_type'] == 'linear' else 3
    coefficients = tuple(sp.Symbol(n, real=True) for n in names[:count])
    template = sum(c*x**(count-i-1) for i, c in enumerate(coefficients))
    visited = 0

    def read(node, depth=0, calls=0):
        nonlocal visited
        visited += 1
        if visited > 256 or depth > 16:
            raise NotationError('function_coefficients.expression_budget')
        if node == target[2]:
            return x
        if node[0] == 'number' and len(node[1]) <= 80:
            return _bounded(sp.Rational(node[1]))
        if node[0] == 'function_call' and len(node) == 3 and node[1] == target[1] and calls < 2:
            value = template.subs(x, read(node[2], depth+1, calls+1))
        elif node[0] == 'neg':
            value = -read(node[1], depth+1, calls)
        elif node[0] in ('+', '-', '*', '/', '^') and len(node) == 3:
            a, b = [read(v, depth+1, calls) for v in node[1:]]
            if node[0] == '/':
                if b.free_symbols or b == 0:
                    raise NotationError('function_coefficients.constant_divisor_required')
                value = a/b
            elif node[0] == '^':
                if b not in (1, 2):
                    raise NotationError('function_coefficients.power_unsupported')
                value = a**b
            else:
                value = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b}[node[0]]()
        else:
            raise NotationError('function_coefficients.polynomial_syntax_required')
        poly = sp.Poly(value, x, *coefficients)
        if poly.degree(x) > 2 or max(sum(p[1:]) for p, _ in poly.terms()) > 2 or len(poly.terms()) > 32:
            raise NotationError('function_coefficients.degree_budget')
        for c in poly.coeffs():
            _bounded(c)
        return poly.as_expr()

    relations = []
    for ast in [desc['relation_ast'], *desc.get('additional_relations_ast', [])]:
        if ast[0] != '=' or len(ast) != 3:
            raise NotationError('function_coefficients.identity_required')
        relations.append(sp.Eq(read(ast[1]), read(ast[2]), evaluate=False))
    requested = None
    if desc['kind'] == 'find_value':
        ast = desc['value_ast']
        if ast[0] != 'function_call' or ast[1] != target[1]:
            raise NotationError('function_coefficients.single_value_required')
        requested = read(ast[2])
        if requested.free_symbols:
            raise NotationError('function_coefficients.fixed_input_required')
    elif desc['kind'] == 'find_range':
        ast = desc['value_ast']
        if ast[0] not in ('>', '>=', '<', '<=') or ast[1] != target:
            raise NotationError('function_coefficients.function_inequality_required')
        rhs = read(ast[2])
        if rhs.free_symbols:
            raise NotationError('function_coefficients.constant_comparison_required')
        requested = (ast[0], rhs)
    elif desc['kind'] != 'find_function_formula':
        raise NotationError('function_coefficients.goal_unsupported')
    return CoefficientSource(x, coefficients, template, tuple(relations), requested, desc['kind'])


def compare_coefficients(relations, variable, parameters, domain):
    """A reusable skill: coefficients of identities on R, including zero terms.

    Does not solve equations, choose a function type or produce a function.
    """
    if domain != sp.S.Reals or not relations or len(relations) > 4:
        raise NotationError('coefficient_comparison.full_real_identity_required')
    rows, equations = [], []
    for identity in relations:
        if not isinstance(identity, sp.Equality):
            raise NotationError('coefficient_comparison.equality_required')
        lhs, rhs = sp.Poly(identity.lhs, variable), sp.Poly(identity.rhs, variable)
        if max(lhs.degree(), rhs.degree()) > 2 or (identity.free_symbols - {variable} - set(parameters)):
            raise NotationError('coefficient_comparison.unsupported_polynomial')
        for degree in range(int(max(0, lhs.degree(), rhs.degree())), -1, -1):
            a, b = lhs.nth(degree), rhs.nth(degree)
            rows.append({'degree': degree, 'left': a, 'right': b})
            residual = sp.expand(a-b)
            if residual != 0 and residual not in equations:
                equations.append(residual)
    return {'rows': rows, 'equations': equations, 'domain': domain}


def solve_coefficients(source, comparison):
    equations, cs = comparison['equations'], source.coefficients
    if not equations:
        raise NotationError('function_coefficients.infinite_candidates')
    try:
        solutions = sp.solve_poly_system(equations, *cs)
    except (NotImplementedError, sp.PolynomialError) as exc:
        raise NotationError('function_coefficients.nonfinite_or_unsupported_system') from exc
    tuples = []
    for row in solutions or []:
        if all(v.is_real is True and not v.free_symbols for v in row) and row[0] != 0:
            if row not in tuples:
                tuples.append(row)
    if not tuples:
        raise NotationError('function_coefficients.no_type_valid_candidate')
    if len(tuples) > 4:
        raise NotationError('function_coefficients.candidate_budget')
    return sorted(tuples, key=sp.default_sort_key)


def complete_result(desc, source, tuples):
    cs, x = source.coefficients, source.variable
    candidates = [sp.expand(source.template.subs(dict(zip(cs, row)))) for row in tuples]
    result = {'kind': 'function_candidates', 'derivation': 'coefficients', 'function_name': desc['function_name'],
              'variable': x, 'source_domain': sp.S.Reals, 'determined_domain': sp.S.Reals,
              'goal_kind': desc['kind'], 'coefficient_tuples': list(tuples), 'candidates': candidates,
              'status': 'determined_on_domain'}
    if desc['kind'] == 'find_value':
        values = [sp.simplify(p.subs(x, source.requested)) for p in candidates]
        result.update(input=source.requested, values=values,
                      value=values[0] if len(set(values)) == 1 else None,
                      status='complete' if len(set(values)) == 1 else 'insufficient_information')
    if desc['kind'] == 'find_range':
        op, rhs = source.requested
        relation = {'>': sp.Gt, '>=': sp.Ge, '<': sp.Lt, '<=': sp.Le}[op]
        sets = [sp.solve_univariate_inequality(relation(p, rhs), x, relational=False) for p in candidates]
        result.update(solution_sets=sets, solution=sets[0] if len(set(sets)) == 1 else None,
                      status='set' if len(set(sets)) == 1 else 'insufficient_information')
    return result


def recover_coefficients(desc):
    source = coefficient_source(desc)
    comparison = compare_coefficients(source.relations, source.variable, source.coefficients, sp.S.Reals)
    return complete_result(desc, source, solve_coefficients(source, comparison))


def verify_coefficients(desc, proposed):
    """Rebind source, check every coefficient and candidate, prove none omitted."""
    try:
        source = coefficient_source(desc)
        x, cs = source.variable, source.coefficients
        rows = proposed['coefficient_tuples']
        if not rows or len(rows) > 4 or any(len(row) != len(cs) for row in rows):
            return False
        for row in rows:
            if row[0] == 0 or any(v.is_real is not True or v.free_symbols for v in row):
                return False
            mapping = dict(zip(cs, row))
            if any(sp.expand((eq.lhs-eq.rhs).subs(mapping)) != 0 for eq in source.relations):
                return False
        # Independent coefficient extraction and set solver, not the recovering
        # solve_poly_system nor a handful of x samples.
        equations = [c for eq in source.relations for c in sp.Poly(eq.lhs-eq.rhs, x).all_coeffs() if c != 0]
        complete = sp.nonlinsolve(equations, cs)
        if not isinstance(complete, sp.FiniteSet):
            return False
        if any(any(v.free_symbols for v in row) for row in complete):
            return False
        valid = {tuple(row) for row in complete if row[0] != 0 and all(v.is_real is True for v in row)}
        if len(rows) != len(valid) or set(map(tuple, rows)) != valid:
            return False
        return proposed == complete_result(desc, source, rows)
    except (ValueError, KeyError, TypeError, NotImplementedError, sp.PolynomialError):
        return False
