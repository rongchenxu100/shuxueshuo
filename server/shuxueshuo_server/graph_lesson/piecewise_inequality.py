"""Single-layer piecewise inequalities with a source-bound constant threshold.

Numeric f(c) is evaluated in its original branch. Roots/signs reuse the existing
capabilities; independent verification solves original polynomial inequalities.
"""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from . import piecewise_equation as equations
from .function_evaluation import _body_value
from .piecewise_evaluation import _constant, branches, is_piecewise, select_branch

VERSION = 'piecewise-inequality/v1'
METHOD = 'method-piecewise-inequality'
RELATIONS = {'>': sp.Gt, '>=': sp.Ge, '<': sp.Lt, '<=': sp.Le}
REVERSED = {'>': '<', '>=': '<=', '<': '>', '<=': '>='}


def _fail(reason):
    raise NotationError('piecewise_inequality.' + reason)


def source(description):
    goal, records = description['goal_ast'], description['sources']
    variable_ast = description['variable_ast']
    if goal != {'kind': 'find_range', 'target': variable_ast} or variable_ast[0] != 'ref' or variable_ast[2] != 'scalar':
        _fail('scalar_input_range_required')
    definitions = [r['ast'] for r in records if r['ast'][0] == 'function_definition']
    relations = [r['ast'] for r in records if r['ast'][0] in RELATIONS]
    if len(records) != 2 or len(definitions) != 1 or len(relations) != 1:
        _fail('one_definition_and_inequality_required')
    definition, relation = definitions[0], relations[0]
    if not is_piecewise(definition[2]):
        _fail('piecewise_definition_required')
    call = ['function_call', definition[1], variable_ast]
    if relation[1] == call:
        op, level_ast = relation[0], relation[2]
    elif relation[2] == call:
        op, level_ast = REVERSED[relation[0]], relation[1]
    else:
        _fail('single_direct_call_required')
    x = sp.Symbol(description['variable'], real=True)
    rows = [{**r, 'expression': equations._polynomial(r['expression_ast'], x).as_expr()}
            for r in branches(definition[2])]
    data = {'variable': x, 'function': definition[1][1].rsplit(':', 1)[-1], 'op': op,
            'rows': rows, 'level_ast': level_ast, 'level_input': None, 'level_branch': None}
    if level_ast[0] == 'function_call':
        if level_ast[1] != definition[1]:
            _fail('same_function_threshold_required')
        value = _constant(level_ast[2])
        index = select_branch(rows, value)
        if index is None:
            _fail('undefined_threshold')
        data.update(level_input=value, level_branch=index)
    else:
        poly = equations._polynomial(level_ast, x)
        if poly.degree() > 0:
            _fail('constant_threshold_required')
    return data


def describe(report, scope, ancestors, index):
    return equations.describe(report, scope, ancestors, index, source_validator=source, version=VERSION)


def inspect_target(candidate, target_ref):
    return equations.inspect_target(candidate, target_ref, describe_goal=describe)


def relevant(goal, records):
    return equations.relevant(goal, records) and any(r['value'][0] in RELATIONS for r in records)


def admitted(context):
    desc = context.get('piecewise_inequality', {})
    return (desc.get('structure_supported') is True and desc['goal_ast'] == context['goal_ast']
            and desc['sources'] == [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context['entries']])


def threshold(data, *, raw=False):
    if data['level_input'] is None:
        return _body_value(data['level_ast'], data['variable'], raw=raw)
    row = data['rows'][data['level_branch']]
    return _body_value(row['expression_ast'], data['level_input'], raw=raw)


def evaluate_level(context):
    from .stage_three.capabilities import CapabilityGap, result, simplify_expression
    if not admitted(context):
        raise CapabilityGap('piecewise_inequality.input_class_unavailable')
    desc = deepcopy(context['piecewise_inequality'])
    data = source(desc)
    computed = simplify_expression(threshold(data, raw=True).doit())
    value = sp.cancel(computed['outputs']['expression'])
    return result({'description': desc, 'level': value}, ['function_evaluation', *computed['operations']],
                  [*computed['checks'], {'kind': 'original_threshold_branch', 'passed': value == threshold(data),
                                        'branch_index': data['level_branch']}])


def _checked_source(description, level):
    from .stage_three.capabilities import LocalCheckFailed
    data = source(description)
    if description['structure_supported'] is not True or threshold(data) != level:
        raise LocalCheckFailed('piecewise_inequality.threshold_mismatch')
    return data


def solve_roots(description, level):
    from .stage_three.capabilities import result, solve_quadratic
    data = _checked_source(description, level)
    checks, rows = [], deepcopy(data['rows'])
    for index, row in enumerate(rows):
        residual = sp.expand(row['expression'] - level)
        row['positive_expression'] = residual if data['op'] in ('>', '>=') else -residual
        solved = solve_quadratic(row['positive_expression'], data['variable'])
        row.update(solved['outputs'])
        checks.extend({**check, 'branch_index': index} for check in solved['checks'])
    return result({'branch_roots': rows}, ['quadratic_roots'], checks)


def solve_signs(description, level, branch_roots):
    from .stage_three.capabilities import (
        LocalCheckFailed,
        quadratic_sign_pattern,
        result,
    )
    data = _checked_source(description, level)
    if len(branch_roots) != len(data['rows']):
        raise LocalCheckFailed('piecewise_inequality.branch_count_mismatch')
    rows, checks = deepcopy(branch_roots), []
    for index, (row, original) in enumerate(zip(rows, data['rows'], strict=True)):
        expression = sp.expand(original['expression'] - level) * (1 if data['op'] in ('>', '>=') else -1)
        if any(row[k] != v for k, v in original.items()) or row['positive_expression'] != expression:
            raise LocalCheckFailed('piecewise_inequality.branch_source_mismatch')
        solved = quadratic_sign_pattern(expression, data['variable'], row['roots'],
                                        data['op'] in ('>', '<'), row['all_zero'])
        row['candidates'] = solved['outputs']['solution']
        checks.extend({**check, 'branch_index': index} for check in solved['checks'])
    return result({'branch_solutions': rows}, ['quadratic_signs'], checks)


def _solution(expression, x, op):
    return sp.Union(*sp.solve_poly_inequality(sp.Poly(expression, x, domain=sp.QQ), op))


def verify_rows(description, level, rows):
    try:
        data = source(description)
        if not description['structure_supported'] or threshold(data) != level or len(rows) != len(data['rows']):
            return False
        x = data['variable']
        for row, original in zip(rows, data['rows'], strict=True):
            residual = sp.expand(original['expression'] - level)
            candidates = _solution(residual, x, data['op'])
            roots = equations._zero_set(residual, x)
            expected = {**original, 'positive_expression': residual if data['op'] in ('>', '>=') else -residual,
                        'roots': [] if roots == sp.S.Reals else sorted(roots), 'all_zero': residual == 0,
                        'candidates': candidates, 'accepted': candidates & original['domain'],
                        'rejected': candidates - original['domain']}
            if row != expected:
                return False
        return True
    except (NotationError, ValueError, TypeError, KeyError):
        return False


def filter_branches(description, level, branch_solutions):
    from .stage_three.capabilities import LocalCheckFailed, result
    rows = [{**deepcopy(r), 'accepted': r['candidates'] & r['domain'],
             'rejected': r['candidates'] - r['domain']} for r in branch_solutions]
    if not verify_rows(description, level, rows):
        raise LocalCheckFailed('piecewise_inequality.branch_evidence_mismatch')
    return result({'branch_results': rows, 'feasible_set': sp.Union(*(r['accepted'] for r in rows))},
                  ['piecewise_inequality_intersection_union'],
                  [{'kind': 'original_branch_inequalities_intersection_union', 'passed': True}])


def process_context(context, feasible_set):
    from .stage_three.verification import VerificationGap
    if not admitted(context):
        raise VerificationGap('piecewise_inequality.context_not_admitted')
    return feasible_set, [{'source_ref': r['source_ref'], 'status': 'piecewise_inequality_source'} for r in context['entries']]


def independent_verify(candidate, target_ref, context, feasible_set):
    from .stage_three.context import build_context
    from .stage_three.math_values import math_value
    rebuilt = build_context(candidate, target_ref)
    valid, expected = False, sp.S.EmptySet
    if rebuilt == context and admitted(rebuilt):
        data = source(rebuilt['piecewise_inequality'])
        level = threshold(data)
        expected = sp.Union(*(_solution(r['expression']-level, data['variable'], data['op']) & r['domain']
                              for r in data['rows']))
        valid = expected == feasible_set
    return {'status': 'verified' if valid else 'math_failed',
            'proof': {'kind': 'piecewise_inequality_all_original_branches', 'passed': valid,
                      'expected': math_value(expected), 'actual': math_value(feasible_set)},
            'diagnostics': [] if valid else [{'code': 'piecewise_inequality.independent_verification_failed'}]}


def endpoints(candidate, target_ref, proposed):
    from .stage_three.math_values import math_value
    data = source(inspect_target(candidate, target_ref))
    x, rows, level = data['variable'], data['rows'], threshold(data)
    points = set(proposed.boundary)
    for row in rows:
        points.update(row['domain'].boundary)
        points.update(_solution(row['expression']-level, x, data['op']).boundary)
    evidence = []
    for point in sorted(points):
        index = select_branch(rows, point)
        holds = index is not None and bool(RELATIONS[data['op']](rows[index]['expression'].subs(x, point), level))
        included = point in proposed
        evidence.append({'point': math_value(point), 'included': included, 'holds': holds,
                         'passed': included == holds, 'evidence': {'branch_index': index}})
    return {'status': 'passed' if all(r['passed'] for r in evidence) else 'failed', 'points': evidence}
