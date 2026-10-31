"""Structural admission for a linear term plus a named periodic function."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.notation_compile import NotationValidator
from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_translation_range import FIELDS
from ..range_syntax import range_domain
from . import contracts
from .function_domain import source_pointer

VERSION = 'translation-range/v1'


def coefficient(ast, variable, periodic):
    x, g = sp.symbols('input periodic')

    def read(node, depth=0):
        if depth > 12:
            raise NotationError('translation_range.expression_budget')
        if node == variable:
            return x
        if node == ['function_call', periodic, variable]:
            return g
        if node[0] == 'number':
            value = sp.Rational(node[1])
            if max(abs(int(value.p)).bit_length(), int(value.q).bit_length()) > 64:
                raise NotationError('translation_range.coefficient_budget')
            return value
        if node[0] == 'neg':
            return -read(node[1], depth+1)
        if node[0] in ('+', '-', '*', '/') and len(node) == 3:
            a, b = (read(child, depth+1) for child in node[1:])
            if node[0] == '/':
                if b.free_symbols or b == 0:
                    raise NotationError('translation_range.constant_denominator_required')
                return a/b
            return {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b}[node[0]]()
        raise NotationError('translation_range.linear_plus_periodic_required')

    expr = sp.expand(read(ast))
    slope = expr.coeff(x)
    if not slope.is_Rational or sp.expand(expr-slope*x-g) != 0:
        raise NotationError('translation_range.linear_plus_periodic_required')
    return str(slope)


def describe_translation_range(report, scope, ancestors, goal_index):
    goal = scope['goals'][goal_index]
    ref = source_pointer(scope['scope']) + f'/goals/{goal_index}'
    value = {'kind': goal['kind'], 'source_ref': ref, 'target_ref': ref,
             'function_name': goal['target'][1][1].rsplit(':', 1)[-1],
             'periodic_name': goal['periodic_ref'][1].rsplit(':', 1)[-1],
             'variable': goal['target'][2][1].rsplit(':', 1)[-1],
             'relation_ast': deepcopy(goal['relation']), 'slope': None, 'period': None,
             'source_refs': [ref+'/'+field for field in FIELDS],
             'structure_version': VERSION, 'structure_supported': False, 'reason': ''}
    value.update({key+'_ast': deepcopy(goal[key])
                  for key in ('periodic_domain', 'known_domain', 'known_range', 'input_domain')})
    try:
        # Additional visible statements cannot be silently discarded.
        if any(item.get('facts') for item in [*ancestors, scope]):
            raise NotationError('translation_range.extra_conditions_unsupported')
        if goal['periodic_domain'] != ['real']:
            raise NotationError('translation_range.real_periodic_domain_required')
        value['slope'] = coefficient(goal['relation'], goal['target'][2], goal['periodic_ref'])
        from ...problem_understanding.notation_semantics import Canonical
        period = Canonical().expr(goal['period'])
        if period.is_Rational is not True or period <= 0 or max(abs(int(period.p)).bit_length(), int(period.q).bit_length()) > 64:
            raise NotationError('translation_range.positive_rational_period_required')
        value['period'] = str(period)
        for key in ('known_domain', 'known_range', 'input_domain'):
            range_domain(goal[key])
        value['structure_supported'] = True
    except (NotationError, ValueError, TypeError) as exc:
        value['reason'] = getattr(exc, 'code', 'translation_range.unsupported_source')
    return value


def inspect_translation_target(candidate, target_ref):
    report = NotationValidator().validate_root(candidate['root'], contracts.schema()['$defs'])
    if not report.ok:
        raise ValueError('translation_range.invalid_source')
    scope = report.semantic
    ancestors = []
    parts = target_ref.removeprefix('/root').split('/children/')
    for part in parts[1:]:
        ancestors.append(scope)
        scope = scope['children'][int(part.split('/')[0])]
    return describe_translation_range(report, scope, ancestors, int(target_ref.rsplit('/', 1)[-1]))
