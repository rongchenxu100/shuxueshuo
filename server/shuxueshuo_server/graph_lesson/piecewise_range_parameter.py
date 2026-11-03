"""Source-bound range equality for two controlled parametric piecewise families.

The executable reciprocal-maximum route and the independent original-quadratic
minimum/maximum verifier use different proofs. No parameter sampling is used.
"""

from copy import deepcopy

import sympy as sp

from ..problem_understanding.notation_parser import NotationError, definition
from . import piecewise_equation as equations
from .piecewise_evaluation import branches
from .range_syntax import range_domain
from .stage_one.function_domain_parameter import _param_affine

VERSION = 'piecewise-range-parameter/v1'
METHOD = 'method-piecewise-range-parameter'
RULE = 'rule-piecewise-range-parameter'


def _fail(reason):
    raise NotationError('piecewise_range_parameter.' + reason)


def source(description):
    goal, records = description['goal_ast'], description['sources']
    p_ast = description['variable_ast']
    if (goal.get('kind') != 'match_range' or goal['target'] != p_ast
            or p_ast[:1] != ['ref'] or p_ast[2] != 'scalar'):
        _fail('parameter_goal_required')
    definitions = [r for r in records if r['ast'][:2] == ['function_definition', goal['function']]]
    if len(definitions) != 1 or any(r not in definitions and r['ast'] not in (
            ['∈', p_ast, ['real']], ['default_domain', p_ast, 'real']) for r in records):
        _fail('single_original_definition_required')
    original = definitions[0]
    name, argument = definition(original['expression'])[1:3]
    if argument == description['variable']:
        _fail('distinct_parameter_required')
    x, p = sp.symbols(f'{argument} {description["variable"]}', real=True)
    rows = []
    for i, row in enumerate(branches(original['ast'][2]), 1):
        coeffs = _param_affine(row['expression_ast'], p_ast[1])
        if len(coeffs) > 3:
            _fail('quadratic_required')
        expr = sum((sp.Rational(c)+sp.Rational(k)*p)*x**j for j, (c, k) in enumerate(coeffs))
        rows.append({**row, 'index': i, 'expression': expr})
    fixed = [r for r in rows if not r['expression'].has(p)]
    varying = [r for r in rows if r['expression'].has(p)]
    if len(fixed) != 1 or len(varying) != 1:
        _fail('one_fixed_one_parametric_piece_required')
    fixed, varying = fixed[0], varying[0]
    poly = sp.Poly(varying['expression'], x)
    if poly.degree() != 2 or poly.nth(2) != p or poly.nth(1).is_negative is not True or poly.nth(0).has(p):
        _fail('leading_parameter_fixed_negative_linear_coefficient_required')
    b, c, domain = poly.nth(1), poly.nth(0), varying['domain']
    target = range_domain(goal['range'])
    h = domain.start if domain.end == sp.oo else domain.end
    if h.is_positive is not True:
        _fail('positive_fixed_split_required')
    if domain == sp.Interval.open(h, sp.oo) and fixed['domain'] == sp.Interval(-sp.oo, h):
        if not isinstance(target, sp.Interval) or target.end != sp.oo or target.left_open:
            _fail('closed_lower_target_required')
        if not (c > target.start and -2*(c-target.start)/b > h):
            _fail('interior_reciprocal_maximum_required')
        family = 'contained'
    elif domain == sp.Interval(-sp.oo, h) and fixed['domain'] == sp.Interval.open(h, sp.oo) and target == sp.S.Reals:
        fpoly = sp.Poly(fixed['expression'], x)
        if fpoly.degree() != 1 or fpoly.nth(1).is_positive is not True or fixed['expression'].subs(x, h) <= c:
            _fail('increasing_fixed_halfline_required')
        family = 'cover'
    else:
        _fail('unsupported_range_parameter_family')
    return {'x': x, 'parameter': p, 'function': name, 'fixed': fixed, 'varying': varying,
            'b': b, 'c': c, 'split': h, 'target': target, 'family': family}


def describe(report, scope, ancestors, index):
    return equations.describe(report, scope, ancestors, index, source_validator=source, version=VERSION)


def inspect_target(candidate, target_ref):
    return equations.inspect_target(candidate, target_ref, describe_goal=describe)


def admitted(context):
    desc = context.get('piecewise_range_parameter', {})
    return (desc.get('structure_supported') is True and desc['goal_ast'] == context['goal_ast']
            and desc['sources'] == [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context['entries']])


def prepare(context):
    from .stage_three.capabilities import CapabilityGap, result
    from .stage_three.function_range import polynomial_image
    if not admitted(context):
        raise CapabilityGap('piecewise_range_parameter.input_class_unavailable')
    desc = deepcopy(context['piecewise_range_parameter'])
    d = source(desc)
    image = polynomial_image(d['fixed']['expression'], d['x'], d['fixed']['domain'])
    fixed_range = image['outputs']['feasible_set']
    if d['family'] == 'contained' and fixed_range != d['target'] and fixed_range.is_subset(d['target']) is True:
        raise CapabilityGap('piecewise_range_parameter.fixed_range_not_target')
    missing = d['target'] - fixed_range
    return result({'description': desc, 'fixed_range': fixed_range, 'missing': missing},
                  ['piecewise_range_union'], image['checks'])


def classify(fixed_range, target):
    """J2 compares output sets, never input domains."""
    if fixed_range.is_subset(target) is not True:
        return 'impossible'
    return 'contained' if fixed_range == target else 'cover'


def choose_route(description, fixed_range):
    from .stage_three.function_range import original_image
    d = source(description)
    if fixed_range != original_image(d['fixed']['expression'], d['x'], d['fixed']['domain'])[0]:
        _fail('fixed_range_mismatch')
    route = classify(fixed_range, d['target'])
    return {'selected': route, 'route': route,
            'evidence': {'reason': 'compare_exact_output_sets', 'fixed_range': fixed_range, 'target': d['target']}}


def reduce_to_universal(description, fixed_range):
    """The host derives a subproblem; its solver and teaching belong to the child."""
    from .stage_three.capabilities import LocalCheckFailed, result
    from .stage_three.math_values import latex
    d = source(description)
    if choose_route(description, fixed_range)['selected'] != 'contained':
        raise LocalCheckFailed('piecewise_range_parameter.not_contained')
    x, p = d['x'], d['parameter']
    relation = sp.Ge(d['varying']['expression'], d['target'].start, evaluate=False)
    normalized = sp.Ge(sp.expand(relation.lhs-relation.rhs), 0, evaluate=False)
    branch = d['varying']
    caption = (f'本步条件来自第 {branch["index"]} 段函数（含参数 ${latex(p)}$）：'
               f'${d["function"]}({latex(x)})={latex(branch["expression"])}$，'
               f'${latex(branch["domain"].as_relational(x))}$。')
    return result({
        'relation': normalized, 'expression': normalized.lhs, 'x': x, 'parameter': p,
        'domain': branch['domain'], 'quantifier': '∀', 'strict': False,
        'goal': {'kind': 'find_range', 'symbol': str(p)}, 'constraint_context': {},
        'universal_statement': relation, 'borrowed_method': 'method-separation',
        'subproblem_context': caption,
    }, ['piecewise_range_parameter'], [
        {'kind': 'fixed_piece_already_covers_target', 'passed': fixed_range == d['target']},
        {'kind': 'remaining_piece_universal_lower_bound', 'passed':
         d['target'] == sp.Interval(d['target'].start, sp.oo), 'domain': branch['domain']},
    ])


def accept_subproblem(description, fixed_range, candidate_set):
    """Return the child's answer, without recomputing its separation/maximum."""
    from .stage_three.capabilities import LocalCheckFailed, result
    d = source(description)
    if (choose_route(description, fixed_range)['selected'] != 'contained'
            or not isinstance(candidate_set, sp.Interval) or candidate_set.end != sp.oo):
        raise LocalCheckFailed('piecewise_range_parameter.invalid_subproblem_answer')
    k = candidate_set.start
    q = d['varying']['expression'].subs(d['parameter'], k)
    witness = -sp.Poly(q, d['x']).nth(1)/(2*sp.Poly(q, d['x']).nth(2))
    return result({'feasible_set': candidate_set, 'calculation': {
        'route': 'contained', 'bound': k, 'witness': witness,
    }}, ['piecewise_range_parameter'], [
        {'kind': 'child_parameter_answer_returned', 'passed': True},
        {'kind': 'boundary_witness_in_original_piece', 'passed':
         witness in d['varying']['domain'] and sp.simplify(q.subs(d['x'], witness)) == d['target'].start},
    ])


def solve(description, fixed_range, route):
    from .stage_three.capabilities import CapabilityGap, LocalCheckFailed, result
    d = source(description)
    if choose_route(description, fixed_range)['selected'] != route or route not in (d['family'], 'impossible'):
        raise LocalCheckFailed('piecewise_range_parameter.route_mismatch')
    x, p, b, c, h = (d[k] for k in ('x', 'parameter', 'b', 'c', 'split'))
    info = {'route': route, 'fixed_range': fixed_range, 'target': d['target'], 'missing': d['target']-fixed_range}
    if route == 'impossible':
        return result({'calculation': info, 'feasible_set': sp.S.EmptySet}, ['piecewise_range_parameter'],
                      [{'kind': 'fixed_outputs_outside_target', 'passed': fixed_range.is_subset(d['target']) is False}])
    if route == 'contained':
        raise CapabilityGap('piecewise_range_parameter.shared_submethod_required')
    else:
        top = c-b**2/(4*p)
        threshold = fixed_range.start
        # p<0, so multiplication reverses the inequality.
        bound = -b**2/(4*(threshold-c))
        answer = sp.Interval.Ropen(bound, 0)
        info.update(bound=bound, threshold=threshold, vertex=-b/(2*p), top=top,
                    zero_range=sp.Interval(b*h+c, sp.oo))
        checks = [{'kind': 'quadratic_square_identity', 'passed': sp.expand(
            d['varying']['expression'] - (p*(x+b/(2*p))**2+top)) == 0},
                  {'kind': 'negative_parameter_vertex_in_left_piece', 'passed': bool(b < 0 and h > 0)},
                  {'kind': 'all_parameter_cases', 'passed': True, 'cases': ['negative', 'zero', 'positive']}]
    return result({'calculation': info, 'feasible_set': answer}, ['piecewise_range_parameter'], checks)


def _solve_condition(condition, parameter):
    return sp.solve_univariate_inequality(condition, parameter, relational=False)


def original_parameter_set(description):
    """Independent minimum/maximum of the ORIGINAL quadratic on its source domain."""
    from .stage_three.function_range import original_image
    d = source(description)
    x, p, b, c, h = (d[k] for k in ('x', 'parameter', 'b', 'c', 'split'))
    fixed = original_image(d['fixed']['expression'], x, d['fixed']['domain'])[0]
    if fixed.is_subset(d['target']) is False:
        return sp.S.EmptySet
    positive, negative = sp.Interval.open(0, sp.oo), sp.Interval.open(-sp.oo, 0)
    if d['family'] == 'contained':
        if fixed != d['target']:
            _fail('fixed_range_not_target')
        lower = d['target'].start
        inside = positive & _solve_condition(-b/(2*p) > h, p)
        outside = positive - inside
        expected = (inside & _solve_condition(c-b**2/(4*p) >= lower, p)) | (
            outside & _solve_condition(p*h**2+b*h+c >= lower, p))
    else:
        # p>0 is bounded below. p=0 has range [b*h+c,+infinity).
        # p<0 has vertex -b/(2p)<0<h and exact range (-infinity,c-b^2/(4p)].
        expected = negative & _solve_condition(c-b**2/(4*p) >= fixed.start, p)
    return expected


def process_context(context, feasible_set):
    from .stage_three.verification import VerificationGap
    if not admitted(context):
        raise VerificationGap('piecewise_range_parameter.context_not_admitted')
    return feasible_set, [{'source_ref': r['source_ref'], 'status': 'original_range_parameter_source'}
                          for r in context['entries']]


def independent_verify(candidate, target_ref, context, proposed):
    from .stage_three.context import build_context
    from .stage_three.math_values import math_value
    rebuilt = build_context(candidate, target_ref)
    valid, expected = False, sp.S.EmptySet
    if rebuilt == context and admitted(rebuilt):
        expected = original_parameter_set(rebuilt['piecewise_range_parameter'])
        valid = proposed == expected
    return {'status': 'verified' if valid else 'math_failed',
            'proof': {'kind': 'all_parameter_cases_original_piece_images', 'passed': valid,
                      'expected': math_value(expected), 'actual': math_value(proposed)},
            'diagnostics': [] if valid else [{'code': 'piecewise_range_parameter.verification_failed'}]}


def endpoints(candidate, target_ref, proposed):
    from .stage_three.function_range import original_image
    from .stage_three.math_values import math_value
    d = source(inspect_target(candidate, target_ref))
    fixed = original_image(d['fixed']['expression'], d['x'], d['fixed']['domain'])[0]
    checks = []
    for point in sorted(proposed.boundary):
        varying = original_image(d['varying']['expression'].subs(d['parameter'], point),
                                 d['x'], d['varying']['domain'])[0]
        holds = (fixed | varying) == d['target']
        checks.append({'point': math_value(point), 'included': point in proposed, 'holds': holds,
                       'passed': (point in proposed) == holds,
                       'evidence': {'complete_original_image': math_value(fixed | varying)}})
    return {'status': 'passed' if all(c['passed'] for c in checks) else 'failed', 'points': checks}
