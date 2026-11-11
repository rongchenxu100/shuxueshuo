"""Exact affine families with reversible row-operation certificates.

Nonzero constraints cut hyperplanes out of a solution space; they never turn
two related parameters into independent intervals. All arithmetic is exact.
"""
from copy import deepcopy

import sympy as sp

from .function_cells import exact_point

LIMITS = {'parameters': 2, 'branches': 8, 'conditions': 32, 'operations': 256}


def vector(expression, parameters):
    poly = sp.Poly(sp.expand(expression), *parameters)
    if poly.total_degree() > 1:
        raise ValueError('parameter_family.affine_conditions_required')
    values = [poly.coeff_monomial(p) for p in parameters] + [poly.coeff_monomial(1)]
    return [exact_point(sp.simplify(v)) for v in values]


def canonical(expression, parameters):
    values = vector(expression, parameters)
    first = next((v for v in values if v != 0), None)
    if first is None:
        return sp.S.Zero
    return sp.expand(sum((sp.simplify(v/first)*p for v, p in
                          zip(values, [*parameters, sp.S.One], strict=True)), sp.S.Zero))


def _matrix(equations, parameters):
    if len(parameters) != 2 or len(set(parameters)) != 2 or len(equations) > LIMITS['conditions']:
        raise ValueError('parameter_family.budget')
    return [vector(e, parameters) for e in equations]


def _apply(rows, operation):
    kind, i = operation['kind'], operation['row']
    if type(i) is not int or not 0 <= i < len(rows):
        raise ValueError('parameter_family.row_index')
    if kind == 'swap':
        j = operation['other']
        if type(j) is not int or not 0 <= j < len(rows):
            raise ValueError('parameter_family.row_index')
        rows[i], rows[j] = rows[j], rows[i]
    elif kind in ('scale', 'add'):
        factor = exact_point(operation['factor'])
        if kind == 'scale':
            if factor == 0:
                raise ValueError('parameter_family.noninvertible_operation')
            rows[i] = [sp.simplify(factor*v) for v in rows[i]]
        else:
            j = operation['other']
            if type(j) is not int or not 0 <= j < len(rows) or j == i:
                raise ValueError('parameter_family.row_index')
            rows[i] = [sp.simplify(a+factor*b) for a, b in zip(rows[i], rows[j], strict=True)]
    else:
        raise ValueError('parameter_family.operation')
    for row in rows:
        for value in row:
            exact_point(value)


def reduce_rows(equations, parameters):
    rows = _matrix(equations, parameters)
    operations, lead = [], 0
    for col in range(2):
        pivot = next((i for i in range(lead, len(rows)) if rows[i][col] != 0), None)
        if pivot is None:
            continue
        pending = [{'kind': 'swap', 'row': lead, 'other': pivot}]
        for op in pending:
            _apply(rows, op); operations.append(op)
        op = {'kind': 'scale', 'row': lead, 'factor': 1/rows[lead][col]}
        _apply(rows, op); operations.append(op)
        for i in range(len(rows)):
            if i != lead and rows[i][col] != 0:
                op = {'kind': 'add', 'row': i, 'other': lead, 'factor': -rows[i][col]}
                _apply(rows, op); operations.append(op)
        lead += 1
    if len(operations) > LIMITS['operations']:
        raise ValueError('parameter_family.operation_budget')
    return {'rows': rows, 'operations': operations}


def family_from_rows(rows, nonzero, parameters):
    if any(row[:2] == [0, 0] and row[2] != 0 for row in rows):
        return None
    active = [r for r in rows if r != [0, 0, 0]]
    pivots = [next(i for i, v in enumerate(row[:2]) if v != 0) for row in active]
    if pivots != sorted(set(pivots)) or any(row[c] != 1 for row, c in zip(active, pivots, strict=True)):
        raise ValueError('parameter_family.not_reduced')
    if any(row[c] != 0 for i, row in enumerate(active) for j, c in enumerate(pivots) if i != j):
        raise ValueError('parameter_family.not_reduced')
    free = [i for i in range(2) if i not in pivots]
    values = list(parameters)
    for row, pivot in zip(active, pivots, strict=True):
        values[pivot] = sp.expand(-row[2]-sum(row[j]*parameters[j] for j in free))
    substitutions = dict(zip(parameters, values, strict=True))
    exclusions = []
    for restriction in nonzero:
        value = canonical(restriction.subs(substitutions, simultaneous=True), parameters)
        if value == 0:
            return None
        if value.free_symbols and value not in exclusions:
            exclusions.append(value)
    # A finite union of proper hyperplanes cannot cover a real affine space.
    return {'equations': [sp.expand(sum(row[i]*parameters[i] for i in range(2))+row[2]) for row in active],
            'nonzero': sorted(exclusions, key=sp.default_sort_key), 'values': values,
            'free_parameters': [parameters[i] for i in free], 'rank': len(pivots)}


def solve(branches, parameters):
    if len(branches) > LIMITS['branches']:
        raise ValueError('parameter_family.branch_budget')
    records, families = [], []
    for branch in branches:
        if len(branch['equations']) + len(branch['nonzero']) > LIMITS['conditions']:
            raise ValueError('parameter_family.condition_budget')
        reduction = reduce_rows(branch['equations'], parameters)
        family = family_from_rows(reduction['rows'], branch['nonzero'], parameters)
        records.append({'input': deepcopy(branch), **reduction, 'family': family})
        if family is not None and family not in families:
            families.append(family)
    return {'records': records, 'families': families}


def verify(branches, parameters, certificate):
    """Replay only invertible operations; never invoke the production reduction."""
    try:
        if set(certificate) != {'records', 'families'} or len(branches) > LIMITS['branches']:
            return False
        if len(certificate['records']) != len(branches):
            return False
        expected = []
        for branch, record in zip(branches, certificate['records'], strict=True):
            if record['input'] != branch or len(record['operations']) > LIMITS['operations']:
                return False
            if len(branch['equations']) + len(branch['nonzero']) > LIMITS['conditions']:
                return False
            rows = _matrix(branch['equations'], parameters)
            for operation in record['operations']:
                _apply(rows, operation)
            if rows != record['rows']:
                return False
            family = family_from_rows(rows, branch['nonzero'], parameters)
            if family != record['family']:
                return False
            if family is not None and family not in expected:
                expected.append(family)
        return certificate['families'] == expected
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, sp.PolynomialError):
        return False
