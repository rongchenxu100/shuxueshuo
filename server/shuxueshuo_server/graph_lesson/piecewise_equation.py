"""Source-bound, single-layer piecewise equations; candidates are never answers.

The route delegates degree <= 2 equations to the existing root capability.
The verifier independently reconstructs each polynomial zero set and intersects
the original branch predicate. Neither uses sampled graph points.
"""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_compile import NotationValidator
from ..problem_understanding.notation_parser import NotationError
from .function_evaluation import _body_value, _bounded, _growth, _syntax
from .piecewise_evaluation import branches, is_piecewise, select_branch
from .stage_one.function_domain import ARGUMENT, source_pointer

VERSION = 'piecewise-equation/v1'
METHOD = 'method-piecewise-equation'


def _fail(reason):
    raise NotationError('piecewise_equation.' + reason)


def _polynomial(ast, variable):
    _syntax(ast, body=True)
    _growth(ast)

    def constant_denominators(node):
        if node == ARGUMENT:
            return True
        if node[0] == '/':
            den = _body_value(node[2], variable)
            # Do not cancel a variable denominator or silently turn 1/0 into 0.
            if den.free_symbols or den.is_Rational is not True or den == 0:
                _fail('polynomial_required')
        return all(constant_denominators(v) for v in node[1:] if isinstance(v, list))

    constant_denominators(ast)
    value = _bounded(_body_value(ast, variable), variable, numerator_degree=2, denominator_degree=0)
    return sp.Poly(value, variable, domain=sp.QQ)


def source(description):
    """Structural admission only: no root solving or candidate filtering."""
    if 'pricing_source' in description:
        from .piecewise_modeling import equation_description
        origin = description['pricing_source']
        ctx = {'piecewise_modeling': origin, 'goal': origin['goal_ast'], 'goal_ast': origin['goal_ast'], 'entries': []}
        if description != equation_description(ctx):
            _fail('derived_pricing_model_mismatch')
    goal, records = description['goal_ast'], description['sources']
    if goal != {'kind': 'find_range', 'target': description['variable_ast']}:
        _fail('scalar_range_goal_required')
    variable_ast = goal['target']
    if variable_ast[0] != 'ref' or variable_ast[2] != 'scalar':
        _fail('scalar_input_required')
    definitions = [r for r in records if r['ast'][0] == 'function_definition']
    equations = [r for r in records if r['ast'][0] == '=']
    if len(records) != 2 or len(definitions) != 1 or len(equations) != 1:
        _fail('one_definition_and_equation_required')
    definition, equation = definitions[0]['ast'], equations[0]['ast']
    if not is_piecewise(definition[2]):
        _fail('piecewise_definition_required')
    call = ['function_call', definition[1], variable_ast]
    if equation[1] == call:
        level_ast = equation[2]
    elif equation[2] == call:
        level_ast = equation[1]
    else:
        _fail('single_direct_call_required')
    x = sp.Symbol(description['variable'], real=True)
    level_poly = _polynomial(level_ast, x)
    if level_poly.degree() > 0:
        _fail('constant_level_required')
    level = level_poly.as_expr()
    rows = [{**r, 'expression': _polynomial(r['expression_ast'], x).as_expr()}
            for r in branches(definition[2])]
    return x, level, rows


def describe(report, scope, ancestors, index, *, source_validator=source, version=VERSION):
    goal = deepcopy(scope['goals'][index])
    records = [{'source_ref': source_pointer(r['path']), 'expression': r['source'], 'ast': deepcopy(r['value'])}
               for item in (*ancestors, scope) for r in report.scope_facts.get(item['scope'], [])]
    target = f"{source_pointer(scope['scope'])}/goals/{index}"
    variable_ast = goal['target']
    desc = {'structure_version': version, 'structure_supported': False, 'reason': '',
            'target_ref': target, 'goal_ast': goal, 'variable_ast': variable_ast,
            'variable': variable_ast[1].rsplit(':', 1)[-1] if variable_ast[0] == 'ref' else '',
            'sources': records, 'source_refs': [target, *(r['source_ref'] for r in records)]}
    try:
        if any(item.get('uncertainties') for item in (*ancestors, scope)):
            _fail('unresolved_source')
        source_validator(desc)
        desc['structure_supported'] = True
    except (NotationError, ValueError, TypeError, KeyError) as exc:
        desc['reason'] = getattr(exc, 'code', str(exc))
    return desc


def inspect_target(candidate, target_ref, *, describe_goal=describe):
    from .stage_one.contracts import schema
    report = NotationValidator().validate_root(candidate.get('root'), schema()['$defs'])
    if not report.ok:
        _fail('invalid_candidate')

    def visit(scope, ancestors=()):
        for index in range(len(scope['goals'])):
            if f"{source_pointer(scope['scope'])}/goals/{index}" == target_ref:
                return describe_goal(report, scope, ancestors, index)
        for child in scope['children']:
            if found := visit(child, (*ancestors, scope)):
                return found
        return None

    found = visit(report.semantic)
    if found is None:
        _fail('unknown_target')
    return found


def relevant(goal, records):
    """Route only scalar input questions with a visible piecewise definition."""
    return (goal['kind'] == 'find_range' and goal['target'][:1] == ['ref']
            and goal['target'][2] == 'scalar'
            and any(r['value'][0] == 'function_definition' and is_piecewise(r['value'][2]) for r in records))


def admitted(context):
    desc = context.get('piecewise_equation', {})
    if 'piecewise_modeling' in context:
        from .piecewise_modeling import admitted as pricing_admitted
        from .piecewise_modeling import equation_description
        return (pricing_admitted(context) and context['goal']['kind'] == 'find_range'
                and desc == equation_description(context))
    return (desc.get('structure_supported') is True and desc['goal_ast'] == context['goal_ast']
            and desc['sources'] == [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context['entries']])


def solve_branches(context):
    from .stage_three.capabilities import CapabilityGap, result, solve_quadratic
    if not admitted(context):
        raise CapabilityGap('piecewise_equation.input_class_unavailable')
    desc = deepcopy(context['piecewise_equation'])
    x, level, rows = source(desc)
    checks = []
    for index, row in enumerate(rows):
        roots = solve_quadratic(sp.expand(row['expression']-level), x)
        row['candidates'] = sp.S.Reals if roots['outputs']['all_zero'] else sp.FiniteSet(*roots['outputs']['roots'])
        checks.extend({**c, 'branch_index': index} for c in roots['checks'])
    return result({'description': desc, 'branch_roots': rows}, ['quadratic_roots'], checks)


def _zero_set(expression, x):
    poly = sp.Poly(expression, x, domain=sp.QQ)
    if poly.degree() <= 0:
        return sp.S.Reals if poly.is_zero else sp.S.EmptySet
    return sp.Union(*sp.solve_poly_inequality(poly, '=='))


def verify_rows(desc, rows):
    try:
        x, level, original = source(desc)
        if not desc['structure_supported'] or len(rows) != len(original):
            return False
        for row, expected in zip(rows, original, strict=True):
            candidates = _zero_set(expected['expression']-level, x)
            if row != {**expected, 'candidates': candidates, 'accepted': candidates & expected['domain'],
                       'rejected': candidates - expected['domain']}:
                return False
        return True
    except (NotationError, ValueError, TypeError, KeyError):
        return False


def filter_branches(description, branch_roots):
    from .stage_three.capabilities import LocalCheckFailed, result
    rows = [{**deepcopy(r), 'accepted': r['candidates'] & r['domain'],
             'rejected': r['candidates'] - r['domain']} for r in branch_roots]
    if not verify_rows(description, rows):
        raise LocalCheckFailed('piecewise_equation.branch_evidence_mismatch')
    solution = sp.Union(*(r['accepted'] for r in rows))
    return result({'branch_results': rows, 'feasible_set': solution}, ['piecewise_branch_intersection_union'],
                  [{'kind': 'original_branch_roots_intersection_union', 'passed': True}])


def process_context(context, feasible_set):
    from .stage_three.verification import VerificationGap
    if not admitted(context):
        raise VerificationGap('piecewise_equation.context_not_admitted')
    return feasible_set, [{'source_ref': r['source_ref'], 'status': 'piecewise_equation_source'}
                          for r in context['entries']]


def independent_verify(candidate, target_ref, context, feasible_set):
    from .stage_three.context import build_context
    from .stage_three.math_values import math_value
    rebuilt = build_context(candidate, target_ref)
    valid, expected = False, sp.S.EmptySet
    if rebuilt == context and admitted(rebuilt):
        x, level, rows = source(rebuilt['piecewise_equation'])
        expected = sp.Union(*(_zero_set(r['expression']-level, x) & r['domain'] for r in rows))
        valid = expected == feasible_set
    return {'status': 'verified' if valid else 'math_failed',
            'proof': {'kind': 'piecewise_equation_all_original_branches', 'passed': valid,
                      'expected': math_value(expected), 'actual': math_value(feasible_set)},
            'diagnostics': [] if valid else [{'code': 'piecewise_equation.independent_verification_failed'}]}


def endpoints(candidate, target_ref, proposed):
    from .stage_three.context import build_context
    from .stage_three.math_values import math_value
    ctx = build_context(candidate, target_ref)
    desc = ctx['piecewise_equation'] if 'piecewise_modeling' in ctx else inspect_target(candidate, target_ref)
    x, level, rows = source(desc)
    points = set(proposed.boundary)
    for row in rows:
        points.update(row['domain'].boundary)
    evidence = []
    for point in sorted(points):
        index = select_branch(rows, point)
        holds = index is not None and rows[index]['expression'].subs(x, point) == level
        included = point in proposed
        evidence.append({'point': math_value(point), 'included': included, 'holds': holds,
                         'passed': included == holds, 'evidence': {'branch_index': index}})
    return {'status': 'passed' if all(r['passed'] for r in evidence) else 'failed', 'points': evidence}
