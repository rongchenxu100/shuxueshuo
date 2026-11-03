"""Bounded branch predicates for numeric function evaluation; no first-match defaults."""

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .stage_one.function_domain import ARGUMENT


def is_piecewise(ast):
    return isinstance(ast, list) and ast[:2] == ['call', 'piecewise']


def _fail(reason):
    raise NotationError('function_evaluation.' + reason)


def _constant(ast):
    if not isinstance(ast, list) or not ast:
        _fail('branch_endpoint')
    if ast[0] == 'number' and len(ast) == 2:
        value = sp.Rational(ast[1])
        if max(int(value.p).bit_length(), int(value.q).bit_length()) > 128:
            _fail('branch_endpoint')
        return value
    if ast[0] == 'neg' and len(ast) == 2 and ast[1][0] == 'number':
        return -_constant(ast[1])
    if ast[0] == '/' and len(ast) == 3 and ast[1][0] == ast[2][0] == 'number':
        denominator = _constant(ast[2])
        if denominator != 0:
            return _constant(ast[1]) / denominator
    _fail('branch_endpoint')


def condition_domain(ast):
    if not isinstance(ast, list) or not ast:
        _fail('branch_condition')
    if ast[0] == 'and' and len(ast) == 3:
        return condition_domain(ast[1]) & condition_domain(ast[2])
    if len(ast) != 3 or ast[0] not in ('<', '<=', '>', '>=', '='):
        _fail('branch_condition')
    op, left, right = ast
    if right == ARGUMENT:
        left, right = right, left
        op = {'<': '>', '<=': '>=', '>': '<', '>=': '<=', '=': '='}[op]
    if left != ARGUMENT:
        _fail('branch_condition')
    endpoint = _constant(right)
    return {
        '<': lambda: sp.Interval.open(-sp.oo, endpoint),
        '<=': lambda: sp.Interval(-sp.oo, endpoint),
        '>': lambda: sp.Interval.open(endpoint, sp.oo),
        '>=': lambda: sp.Interval(endpoint, sp.oo),
        '=': lambda: sp.FiniteSet(endpoint),
    }[op]()


def branches(ast):
    if not is_piecewise(ast) or len(ast) not in (6, 8, 10):
        _fail('branch_budget')
    result, covered = [], sp.S.EmptySet
    for index in range(2, len(ast), 2):
        condition = ast[index + 1]
        domain = condition_domain(condition)
        if domain == sp.S.EmptySet:
            _fail('empty_branch')
        if domain & covered != sp.S.EmptySet:
            _fail('overlapping_branches')
        covered |= domain
        result.append({'expression_ast': ast[index], 'condition_ast': condition, 'domain': domain})
    return result


def select_branch(rows, value):
    if value.free_symbols or value.is_real is not True:
        _fail('numeric_branch_input_required')
    selected = []
    for index, row in enumerate(rows):
        match = row['domain'].contains(value)
        if match not in (sp.S.true, sp.S.false):
            _fail('unresolved_branch')
        if match is sp.S.true:
            selected.append(index)
    if len(selected) > 1:
        _fail('overlapping_branches')
    return selected[0] if selected else None
