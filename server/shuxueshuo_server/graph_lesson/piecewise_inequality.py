"""Piecewise inequalities: constant threshold, or two same-function composite inputs.

Threshold mode keeps f(x)□c / f(x)□f(c). Two-input mode classifies each left/right
branch pair, solves the local comparison, and unions the accepted cells.
"""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from . import piecewise_equation as equations
from .function_evaluation import _body_value, _relation_set
from .piecewise_evaluation import _constant, branches, is_piecewise, select_branch

VERSION = 'piecewise-inequality/v1'
METHOD = 'method-piecewise-inequality'
RELATIONS = {'>': sp.Gt, '>=': sp.Ge, '<': sp.Lt, '<=': sp.Le}
REVERSED = {'>': '<', '>=': '<=', '<': '>', '<=': '>='}


def _fail(reason):
    raise NotationError('piecewise_inequality.' + reason)


def _threshold_data(description, definition, op, level_ast, x, rows):
    data = {'mode': 'threshold', 'variable': x, 'function': definition[1][1].rsplit(':', 1)[-1],
            'op': op, 'rows': rows, 'level_ast': level_ast, 'level_input': None, 'level_branch': None}
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


def _ref_value(ast, variable_ast, x):
    """Evaluate a goal-variable polynomial AST that uses scalar refs, not ARGUMENT."""
    if ast == variable_ast:
        return x
    if not isinstance(ast, list) or not ast:
        _fail('input_ast_required')
    kind = ast[0]
    if kind == 'number':
        return sp.Rational(ast[1])
    if kind == 'neg':
        return -_ref_value(ast[1], variable_ast, x)
    if kind in ('+', '-', '*', '/', '^'):
        left, right = _ref_value(ast[1], variable_ast, x), _ref_value(ast[2], variable_ast, x)
        if kind == '/':
            if right.free_symbols or right == 0:
                _fail('input_polynomial_required')
            return left / right
        if kind == '^':
            if right not in (0, 1, 2) and not (right.is_Integer and 0 <= right <= 2):
                _fail('input_degree_budget')
            return left ** int(right)
        return {'+': left + right, '-': left - right, '*': left * right}[kind]
    _fail('input_structure')


def _input_expr(ast, x, variable_ast):
    value = sp.expand(_ref_value(ast, variable_ast, x))
    if value.free_symbols - {x}:
        _fail('single_variable_input_required')
    if value.free_symbols:
        poly = sp.Poly(value, x, domain=sp.QQ)
        if poly.degree() > 2:
            _fail('input_degree_budget')
    return value


def _piece_rows(definition, t):
    rows = []
    for row in branches(definition[2]):
        body = equations._polynomial(row['expression_ast'], t).as_expr()
        rows.append({**row, 'body': body, 'expression': body})
    return rows


def _two_input_data(description, definition, relation, x):
    left_ast, right_ast = relation[1], relation[2]
    if (left_ast[0] != 'function_call' or right_ast[0] != 'function_call'
            or left_ast[1] != definition[1] or right_ast[1] != definition[1]):
        _fail('two_same_function_calls_required')
    variable_ast = description['variable_ast']
    left = _input_expr(left_ast[2], x, variable_ast)
    right = _input_expr(right_ast[2], x, variable_ast)
    # Stable piece symbol so rebuilt certificates compare equal across source().
    t = sp.Symbol(f"{description['variable']}__piece", real=True)
    rows = _piece_rows(definition, t)
    return {
        'mode': 'two_inputs', 'variable': x, 'piece_variable': t,
        'function': definition[1][1].rsplit(':', 1)[-1], 'op': relation[0],
        'rows': rows, 'left': left, 'right': right,
        'left_ast': deepcopy(left_ast[2]), 'right_ast': deepcopy(right_ast[2]),
        'level_ast': None, 'level_input': None, 'level_branch': None,
    }


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
    x = sp.Symbol(description['variable'], real=True)
    direct = ['function_call', definition[1], variable_ast]
    if relation[1] == direct or relation[2] == direct:
        if relation[1] == direct:
            op, level_ast = relation[0], relation[2]
        else:
            op, level_ast = REVERSED[relation[0]], relation[1]
        threshold_rows = [{**r, 'expression': equations._polynomial(r['expression_ast'], x).as_expr()}
                          for r in branches(definition[2])]
        try:
            return _threshold_data(description, definition, op, level_ast, x, threshold_rows)
        except NotationError as exc:
            # f(x)□f(poly(x)) is not a numeric threshold; undefined f(c) stays refused.
            code = getattr(exc, 'code', None) or str(exc)
            if level_ast[0] != 'function_call' or level_ast[1] != definition[1]:
                raise
            if 'undefined_threshold' in code:
                raise
            if ('constant_threshold_required' not in code and 'branch_endpoint' not in code):
                raise
    return _two_input_data(description, definition, relation, x)


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
    if data.get('mode') == 'two_inputs':
        _fail('threshold_unavailable_for_two_inputs')
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
    if data.get('mode') == 'two_inputs':
        raise CapabilityGap('piecewise_inequality.two_inputs_use_case_solver')
    computed = simplify_expression(threshold(data, raw=True).doit())
    value = sp.cancel(computed['outputs']['expression'])
    return result({'description': desc, 'level': value}, ['function_evaluation', *computed['operations']],
                  [*computed['checks'], {'kind': 'original_threshold_branch', 'passed': value == threshold(data),
                                        'branch_index': data['level_branch']}])


def _checked_source(description, level):
    from .stage_three.capabilities import LocalCheckFailed
    data = source(description)
    if data.get('mode') == 'two_inputs':
        raise LocalCheckFailed('piecewise_inequality.two_inputs_not_threshold')
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


def _preimage(domain, expr, x):
    """Exact {x : expr(x) ∈ domain} for polynomial expr of degree ≤ 2."""
    if domain == sp.S.Reals:
        return sp.S.Reals
    if domain == sp.S.EmptySet:
        return sp.S.EmptySet
    if isinstance(domain, sp.Union):
        return sp.Union(*(_preimage(part, expr, x) for part in domain.args))
    if isinstance(domain, sp.FiniteSet):
        parts = []
        for point in domain:
            parts.append(_relation_set(expr - point, '=', x))
        return sp.Union(*parts) if parts else sp.S.EmptySet
    if isinstance(domain, sp.Complement):
        # Complement(universe, excluded)
        universe, excluded = domain.args
        return _preimage(universe, expr, x) - _preimage(excluded, expr, x)
    if not isinstance(domain, sp.Interval):
        _fail('interval_branch_domain_required')
    result = sp.S.Reals
    if domain.start != -sp.oo:
        result &= _relation_set(expr - domain.start, '>' if domain.left_open else '>=', x)
    if domain.end != sp.oo:
        result &= _relation_set(expr - domain.end, '<' if domain.right_open else '<=', x)
    return sp.simplify(result)


def _strict_mono_on(body, t, domain):
    """Return 1 / -1 / 0 when body is strictly mono / constant on an interval domain."""
    if not isinstance(domain, sp.Interval) or domain == sp.S.EmptySet:
        return None
    if body.free_symbols <= set():
        return 0
    deriv = sp.cancel(sp.diff(body, t))
    if deriv == 0:
        return 0
    try:
        positive = _relation_set(deriv, '>', t)
        negative = _relation_set(deriv, '<', t)
    except (NotationError, ValueError, TypeError):
        return None
    interior = domain.interior if hasattr(domain, 'interior') else (
        sp.Interval.open(domain.start, domain.end) if isinstance(domain, sp.Interval) else domain)
    if interior == sp.S.EmptySet:
        interior = domain
    if sp.simplify(interior - positive) == sp.S.EmptySet:
        return 1
    if sp.simplify(interior - negative) == sp.S.EmptySet:
        return -1
    return None


def _pull_body_relation(body, expr, op, level, x, t, cell):
    """Solve body(t)□level for t, then pull the t-set back through expr(x)."""
    t_set = _relation_set(body - level, op, t)
    return _preimage(t_set, expr, x) & cell


def _compare_with_mono(body_i, body_j, u, v, op, x, t, cell, domain_i, domain_j):
    from .stage_three.capabilities import CapabilityGap
    if cell == sp.S.EmptySet:
        return sp.S.EmptySet, 'empty'
    left = sp.expand(body_i.subs(t, u))
    right = sp.expand(body_j.subs(t, v))
    if left.free_symbols <= set() and right.free_symbols <= set():
        holds = bool(RELATIONS[op](left, right))
        return (cell if holds else sp.S.EmptySet), ('constant_true' if holds else 'constant_false')
    if body_j.free_symbols <= set() and left.free_symbols:
        return _pull_body_relation(body_i, u, op, body_j, x, t, cell), 'left_body_vs_constant'
    if body_i.free_symbols <= set() and right.free_symbols:
        return _pull_body_relation(body_j, v, REVERSED[op], body_i, x, t, cell), 'constant_vs_right_body'
    if sp.expand(body_i - body_j) == 0 and domain_i == domain_j:
        direction = _strict_mono_on(body_i, t, domain_i)
        if direction in (1, -1):
            converted = op if direction == 1 else REVERSED[op]
            local = _relation_set(u - v, converted, x) & cell
            return local, 'strict_mono_input_order'
    residual = sp.expand(left - right)
    try:
        poly = sp.Poly(sp.together(residual), x, domain=sp.QQ)
    except (sp.PolynomialError, ValueError, TypeError) as exc:
        raise CapabilityGap('piecewise_inequality.polynomial_required') from exc
    if poly.degree() <= 2:
        return _solution(residual, x, op) & cell, 'polynomial'
    raise CapabilityGap('piecewise_inequality.degree_budget')


def solve_two_input_cases(description):
    """Classify every left/right branch pair and union local solutions."""
    from .stage_three.capabilities import CapabilityGap, LocalCheckFailed, result
    if description.get('structure_supported') is not True:
        raise LocalCheckFailed('piecewise_inequality.unsupported')
    data = source(description)
    if data.get('mode') != 'two_inputs':
        raise LocalCheckFailed('piecewise_inequality.two_inputs_required')
    x, t, u, v, op = data['variable'], data['piece_variable'], data['left'], data['right'], data['op']
    cases, checks = [], []
    for i, row_i in enumerate(data['rows']):
        for j, row_j in enumerate(data['rows']):
            cell = _preimage(row_i['domain'], u, x) & _preimage(row_j['domain'], v, x)
            accepted, reason = _compare_with_mono(
                row_i['body'], row_j['body'], u, v, op, x, t, cell, row_i['domain'], row_j['domain'])
            cases.append({
                'left_branch': i, 'right_branch': j,
                'left_domain': row_i['domain'], 'right_domain': row_j['domain'],
                'cell': cell, 'accepted': accepted, 'rejected': cell - accepted,
                'reason': reason,
                'left_body': row_i['body'], 'right_body': row_j['body'],
            })
            checks.append({'kind': 'two_input_case', 'passed': True,
                           'left_branch': i, 'right_branch': j, 'reason': reason})
    feasible = sp.Union(*(row['accepted'] for row in cases)) if cases else sp.S.EmptySet
    if not _verify_two_input_cases(description, cases, feasible):
        raise LocalCheckFailed('piecewise_inequality.two_input_evidence_mismatch')
    return result({'description': description, 'case_results': cases, 'branch_results': cases,
                   'feasible_set': feasible, 'level': None},
                  [], checks)


def analyze_route(context):
    """Admit and expose threshold vs two-input mode for guarded execution."""
    from .stage_three.capabilities import CapabilityGap, result
    if not admitted(context):
        raise CapabilityGap('piecewise_inequality.input_class_unavailable')
    desc = deepcopy(context['piecewise_inequality'])
    data = source(desc)
    return result({'description': desc, 'mode': data['mode'],
                   'needs_threshold': data['mode'] == 'threshold',
                   'needs_two_inputs': data['mode'] == 'two_inputs'},
                  [],
                  [{'kind': 'piecewise_inequality_mode', 'passed': True, 'mode': data['mode']}])


def _eval_original(data, point):
    """Evaluate f(u(point)) □ f(v(point)) from original branches."""
    x, u, v = data['variable'], data['left'], data['right']
    left_val = sp.simplify(u.subs(x, point))
    right_val = sp.simplify(v.subs(x, point))
    if left_val.free_symbols or right_val.free_symbols:
        return None
    i = select_branch(data['rows'], left_val)
    j = select_branch(data['rows'], right_val)
    if i is None or j is None:
        return False
    left = _body_value(data['rows'][i]['expression_ast'], left_val)
    right = _body_value(data['rows'][j]['expression_ast'], right_val)
    return bool(RELATIONS[data['op']](left, right))


def _verify_two_input_cases(description, cases, feasible):
    try:
        data = source(description)
        if data.get('mode') != 'two_inputs' or not description['structure_supported']:
            return False
        x, t, u, v, op = data['variable'], data['piece_variable'], data['left'], data['right'], data['op']
        if len(cases) != len(data['rows']) ** 2:
            return False
        rebuilt = []
        for i, row_i in enumerate(data['rows']):
            for j, row_j in enumerate(data['rows']):
                cell = _preimage(row_i['domain'], u, x) & _preimage(row_j['domain'], v, x)
                accepted, reason = _compare_with_mono(
                    row_i['body'], row_j['body'], u, v, op, x, t, cell, row_i['domain'], row_j['domain'])
                rebuilt.append({
                    'left_branch': i, 'right_branch': j,
                    'left_domain': row_i['domain'], 'right_domain': row_j['domain'],
                    'cell': cell, 'accepted': accepted, 'rejected': cell - accepted,
                    'reason': reason, 'left_body': row_i['body'], 'right_body': row_j['body'],
                })
        if cases != rebuilt:
            return False
        expected = sp.Union(*(row['accepted'] for row in rebuilt)) if rebuilt else sp.S.EmptySet
        return expected == feasible
    except (NotationError, ValueError, TypeError, KeyError):
        return False


def verify_rows(description, level, rows):
    try:
        data = source(description)
        if data.get('mode') == 'two_inputs':
            return False
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
        if data.get('mode') == 'two_inputs':
            solved = solve_two_input_cases(rebuilt['piecewise_inequality'])['outputs']
            expected = solved['feasible_set']
            valid = expected == feasible_set
        else:
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
    x, rows = data['variable'], data['rows']
    points = set(proposed.boundary)
    if data.get('mode') == 'two_inputs':
        solved = solve_two_input_cases(inspect_target(candidate, target_ref))['outputs']
        for row in solved['case_results']:
            points.update(sp.Union(row['cell'], row['accepted']).boundary)
        evidence = []
        for point in sorted(points):
            holds = _eval_original(data, point)
            included = point in proposed
            evidence.append({'point': math_value(point), 'included': included, 'holds': holds,
                             'passed': holds is not None and included == holds,
                             'evidence': {'mode': 'two_inputs'}})
        return {'status': 'passed' if all(r['passed'] for r in evidence) else 'failed', 'points': evidence}
    level = threshold(data)
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
