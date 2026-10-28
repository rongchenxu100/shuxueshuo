"""Existential parameter ranges for common domains of rational affine calls.

Execution eliminates x by comparing all lower/upper bounds. Verification reads
original call ASTs, partitions parameter space at boundary-line intersections,
and solves the original one-variable conditions at each cell and boundary.
"""

from copy import deepcopy
from fractions import Fraction
from itertools import combinations, pairwise

import sympy as sp

from ...problem_understanding.notation_parser import NotationError
from ..stage_one.function_domain import MAX_COEFFICIENT_BITS, MAX_INTEGER_EXPONENT
from .abstract_function_domain import _verification_set
from .capabilities.cases import exact_set_equal
from .function_domain import input_set
from .math_values import math_value


def _known_set(description):
    value = input_set({'variable': description['variable'],
                       'input_domain_ast': description['known_domain_ast']})
    if isinstance(value, sp.FiniteSet) and len(value) == 1:
        point, = value
        return value, point, point, False, False
    if (not isinstance(value, sp.Interval) or value.start.is_Rational is not True
            or value.end.is_Rational is not True):
        raise NotationError('abstract_domain_parameter.finite_interval_required')
    return value, value.start, value.end, bool(value.left_open), bool(value.right_open)


def admitted(context):
    description = context.get('abstract_domain_parameter_goal', {})
    if (context.get('goal', {}).get('kind') != 'find_abstract_domain_parameter'
            or description.get('structure_supported') is not True
            or description.get('known_form') != 'identity'
            or description.get('known_strength') not in ('exact', 'meaningful_only')
            or description.get('quantifier') != 'exists'
            or description.get('variable') == description.get('parameter')
            or context.get('entries')):
        return False
    try:
        _known_set(description)
        if not description['calls']:
            return False
        for call in description['calls']:
            for field in ('x_coefficient', 'parameter_coefficient', 'constant'):
                Fraction(call[field])
    except (NotationError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
    return True


def _relation(left, right, strict):
    return (sp.Lt if strict else sp.Le)(left, right, evaluate=False)


def solve_abstract_domain_parameter(context):
    from .abstract_domain_overlap import overlap_strategy
    from .capabilities import CapabilityGap, result, solve_conditions

    if not admitted(context):
        raise CapabilityGap('abstract_domain_parameter.not_admitted')
    description = context['abstract_domain_parameter_goal']
    known, lo, hi, lo_open, hi_open = _known_set(description)
    variable = sp.Symbol(description['variable'], real=True)
    parameter = sp.Symbol(description['parameter'], real=True)
    call_conditions, call_ranges, lower_bounds, upper_bounds, conditions, causes = [], [], [], [], [], []
    for index, call in enumerate(description['calls']):
        call_id = f'call{index + 1}'
        a, b, c = (sp.Rational(call[field]) for field in
                   ('x_coefficient', 'parameter_coefficient', 'constant'))
        offset = b * parameter + c
        argument = a * variable + offset
        original_conditions = [_relation(lo, argument, lo_open), _relation(argument, hi, hi_open)]
        source = {'call_id': call_id, 'source_ref': description['target_call_source_ref'],
                  'ast_path': deepcopy(call['ast_path'])}
        call_conditions.append({**source, 'argument': argument, 'conditions': original_conditions})
        guards = []
        if a == 0:
            guards = original_conditions
            lower, upper, left_open, right_open = -sp.oo, sp.oo, True, True
            conditions.extend(guards)
            causes.extend({'kind': 'constant_in_x_call', **source, 'condition': condition}
                          for condition in guards)
        else:
            first, last = (lo - offset) / a, (hi - offset) / a
            lower, upper = (first, last) if a > 0 else (last, first)
            left_open, right_open = (lo_open, hi_open) if a > 0 else (hi_open, lo_open)
            lower_bounds.append((lower, left_open, call_id))
            upper_bounds.append((upper, right_open, call_id))
        call_ranges.append({**source, 'argument': argument, 'lower': lower, 'upper': upper,
                            'left_open': left_open, 'right_open': right_open,
                            'parameter_conditions': guards})
    # Nonempty intersection of finitely many real intervals is equivalent to
    # every lower <= every upper; equality requires BOTH ends to be included.
    for lower, left_open, lower_id in lower_bounds:
        for upper, right_open, upper_id in upper_bounds:
            condition = _relation(lower, upper, left_open or right_open)
            conditions.append(condition)
            causes.append({'kind': 'overlapping_call_bounds', 'lower_call_id': lower_id,
                           'upper_call_id': upper_id, 'strict': left_open or right_open,
                           'condition': condition})
    solved = solve_conditions(conditions or [sp.true], 'all', parameter, purpose='domain')
    candidate_set = solved['outputs']['solution']
    meaning = ('exact_parameter_range' if description['known_strength'] == 'exact'
               else 'guaranteed_parameter_range')
    strategy, diagram = overlap_strategy(call_ranges, conditions, parameter, candidate_set, variable, description)
    return result({
        'candidate_set': candidate_set, 'variable': variable, 'parameter': parameter,
        'description': description, 'known_domain': known, 'input_range': known,
        'call_conditions': call_conditions, 'call_ranges': call_ranges,
        'overlap_conditions': conditions, 'overlap_evidence': causes,
        'use_complement': strategy['recommended'] == 'complement',
        'parameter_result': {'kind': 'find_abstract_domain_parameter', 'strength': description['known_strength'],
                             'meaning': meaning, 'quantifier': 'exists', 'parameter_set': candidate_set,
                             'condition_solutions': solved['outputs']['solutions'], 'causes': causes,
                             'overlap_strategy': strategy, 'overlap_diagram': diagram},
    }, ['abstract_common_domain', 'abstract_exists_linear_elimination', *solved['operations']], [
        {'kind': 'original_call_membership_conditions', 'passed': True,
         'known_domain': math_value(known), 'calls': call_conditions,
         'known_strength': description['known_strength'], 'meaning': meaning},
        {'kind': 'interval_intersection_nonempty', 'passed': True, 'call_ranges': call_ranges,
         'criterion': 'all lower bounds <= all upper bounds; equality only when both are closed',
         'conditions': conditions, 'causes': causes}, *solved['checks'],
    ])


def _read_expression(ast, refs, symbols, depth=0):
    if depth > 24:
        raise NotationError('abstract_domain_parameter.verification_structure_limit')
    read = lambda child: _read_expression(child, refs, symbols, depth + 1)
    kind = ast[0]
    if kind == 'number':
        value = sp.Rational(ast[1])
    elif kind == 'ref' and ast in refs:
        value = symbols[refs.index(ast)]
    elif kind == 'neg':
        value = -read(ast[1])
    elif kind in ('+', '-', '*', '/'):
        left, right = read(ast[1]), read(ast[2])
        if kind == '/':
            if right.is_Rational is not True or right == 0:
                raise NotationError('abstract_domain_parameter.verification_constant_divisor_required')
            value = left / right
        else:
            value = {'+': lambda: left + right, '-': lambda: left - right, '*': lambda: left * right}[kind]()
    elif kind == '^' and ast[2][0] == 'number':
        exponent = sp.Rational(ast[2][1])
        if exponent.is_Integer is not True or not 1 <= exponent <= MAX_INTEGER_EXPONENT:
            raise NotationError('abstract_domain_parameter.verification_power_unsupported')
        value = read(ast[1]) ** exponent
    else:
        raise NotationError('abstract_domain_parameter.verification_expression_unsupported')
    poly = sp.Poly(value, *symbols, domain=sp.QQ)
    if poly.total_degree() > 1:
        raise NotationError('abstract_domain_parameter.verification_linear_required')
    for coefficient in poly.coeffs():
        n, d = coefficient.as_numer_denom()
        if max(int(n).bit_length(), int(d).bit_length()) > MAX_COEFFICIENT_BITS:
            raise NotationError('abstract_domain_parameter.verification_coefficient_limit')
    return poly.as_expr()


def _source(candidate, target_ref):
    from ..stage_one.abstract_domain_parameter import (
        inspect_abstract_domain_parameter_target,
    )

    description = inspect_abstract_domain_parameter_target(candidate, target_ref)
    if description.get('structure_supported') is not True:
        raise NotationError('abstract_domain_parameter.verification_source_unsupported')
    x, parameter = (sp.Symbol(description[name], real=True) for name in ('variable', 'parameter'))
    refs = [description['variable_ref'], description['parameter_ref']]
    known = _verification_set(description['known_domain_ast'])
    if isinstance(known, sp.FiniteSet) and len(known) == 1:
        lo = hi = next(iter(known))
        lo_open = hi_open = False
    elif isinstance(known, sp.Interval) and known.start.is_Rational and known.end.is_Rational:
        lo, hi, lo_open, hi_open = known.start, known.end, known.left_open, known.right_open
    else:
        raise NotationError('abstract_domain_parameter.verification_finite_interval_required')
    calls = []

    def visit(ast, path=()):
        if not isinstance(ast, list) or not ast:
            return
        if ast[0] == 'function_call':
            if ast[1] != description['known_call_ast'][1]:
                raise NotationError('abstract_domain_parameter.verification_function_mismatch')
            expression = _read_expression(ast[2], refs, [x, parameter])
            calls.append({'argument': expression, 'ast_path': list(path)})
            return
        for index, child in enumerate(ast[1:], 1):
            visit(child, (*path, index))

    visit(description['target_call_ast'])
    if not calls:
        raise NotationError('abstract_domain_parameter.verification_calls_required')
    return {'description': description, 'variable': x, 'parameter': parameter, 'known': known,
            'lower': lo, 'upper': hi, 'left_open': lo_open, 'right_open': hi_open, 'calls': calls}


def _critical_parameters(source):
    """Only vertical boundaries and isolated intersections can change feasibility."""
    x, parameter = source['variable'], source['parameter']
    equations = [call['argument'] - endpoint for call in source['calls']
                 for endpoint in (source['lower'], source['upper'])]
    cuts = set()
    for equation in equations:
        if x not in equation.free_symbols:
            roots = sp.solveset(equation, parameter, domain=sp.S.Reals)
            if isinstance(roots, sp.FiniteSet):
                cuts.update(roots)
            elif roots not in (sp.S.Reals, sp.S.EmptySet):
                raise NotationError('abstract_domain_parameter.verification_vertical_roots_unknown')
    for first, second in combinations(equations, 2):
        intersections = sp.linsolve([first, second], (x, parameter))
        for point in intersections:
            if all(coordinate.is_Rational is True for coordinate in point):
                cuts.add(point[1])
    return sorted(cuts)


def _witness(domain):
    if domain == sp.S.Reals:
        return sp.S.Zero
    if isinstance(domain, sp.FiniteSet):
        return next(iter(domain))
    if isinstance(domain, sp.Interval):
        if domain.start == -sp.oo:
            return domain.end - 1
        if domain.end == sp.oo:
            return domain.start + 1
        return (domain.start + domain.end) / 2
    raise NotationError('abstract_domain_parameter.verification_witness_unsupported')


def _at_parameter(source, point):
    x, parameter = source['variable'], source['parameter']
    call_sets = []
    for call in source['calls']:
        argument = call['argument'].subs(parameter, point)
        relations = [(sp.Gt if source['left_open'] else sp.Ge)(argument, source['lower']),
                     (sp.Lt if source['right_open'] else sp.Le)(argument, source['upper'])]
        solved = []
        for relation in relations:
            if relation in (sp.true, sp.false):
                solved.append(sp.S.Reals if relation is sp.true else sp.S.EmptySet)
            else:
                solved.append(sp.solve_univariate_inequality(relation, x, relational=False))
        call_sets.append({'ast_path': call['ast_path'], 'argument': math_value(argument),
                          'domain': sp.Intersection(*solved)})
    common = sp.Intersection(*(row['domain'] for row in call_sets))
    holds = common != sp.S.EmptySet
    witness = _witness(common) if holds else None
    if holds and any(source['known'].contains(call['argument'].subs({parameter: point, x: witness})) is not sp.true
                     for call in source['calls']):
        raise NotationError('abstract_domain_parameter.verification_witness_failed')
    return holds, {'kind': 'original_calls_have_common_input', 'passed': True,
                   'parameter_value': math_value(point), 'common_domain': math_value(common),
                   'witness': math_value(witness) if witness is not None else None,
                   'calls': [{**row, 'domain': math_value(row['domain'])} for row in call_sets]}


def independent_verify(candidate, target_ref, candidate_set):
    source = _source(candidate, target_ref)
    cuts = _critical_parameters(source)
    accepted, cells = [], []
    for left, right in pairwise([-sp.oo, *cuts, sp.oo]):
        sample = (sp.S.Zero if left == -sp.oo and right == sp.oo else right - 1 if left == -sp.oo
                  else left + 1 if right == sp.oo else (left + right) / 2)
        holds, evidence = _at_parameter(source, sample)
        interval = sp.Interval.open(left, right)
        cells.append({'cell': math_value(interval), 'sample': math_value(sample), 'holds': holds, 'evidence': evidence})
        if holds:
            accepted.append(interval)
    for point in cuts:
        holds, evidence = _at_parameter(source, point)
        cells.append({'point': math_value(point), 'holds': holds, 'evidence': evidence})
        if holds:
            accepted.append(sp.FiniteSet(point))
    expected = sp.Union(*accepted) if accepted else sp.S.EmptySet
    passed = isinstance(candidate_set, sp.Set) and exact_set_equal(candidate_set, expected)
    return {'status': 'verified' if passed else 'verification_failed',
            'expected': math_value(expected), 'actual': math_value(candidate_set),
            'checks': [{'kind': 'original_common_domain_projection', 'passed': passed,
                        'critical_parameters': [math_value(point) for point in cuts],
                        'partition_complete': True, 'cells': cells,
                        'strength': source['description']['known_strength']}],
            'diagnostics': [] if passed else [{'code': 'abstract_domain_parameter.answer_mismatch'}]}


def parameter_endpoints(candidate, target_ref, candidate_set):
    source = _source(candidate, target_ref)
    boundary = candidate_set.boundary
    if boundary != sp.S.EmptySet and not isinstance(boundary, sp.FiniteSet):
        raise NotationError('abstract_domain_parameter.verification_finite_boundary_required')
    rows = []
    for point in sorted(boundary):
        included = candidate_set.contains(point) is sp.true
        holds, evidence = _at_parameter(source, point)
        rows.append({'point': math_value(point), 'included': included, 'holds': holds,
                     'passed': included == holds, 'evidence': evidence})
    verified = independent_verify(candidate, target_ref, candidate_set)
    passed = verified['status'] == 'verified' and all(row['passed'] for row in rows)
    return {'status': 'passed' if passed else 'failed', 'points': rows,
            'diagnostics': verified['diagnostics']}
