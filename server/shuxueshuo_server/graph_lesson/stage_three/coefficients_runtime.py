"""Stated type -> polynomial identity -> coefficients -> all candidates -> goal."""
from copy import deepcopy

import sympy as sp

from ..function_coefficients import (
    coefficient_source, compare_coefficients, solve_coefficients, complete_result, verify_coefficients,
)
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .math_values import math_value
from .trajectory import encode_value, decode_value


def admitted(context):
    if context.get('entries') or not context.get('goal', {}).get('function_type'):
        return False
    try:
        coefficient_source(context.get('formula_goal', {}))
        return True
    except (ValueError, KeyError, TypeError):
        return False


def prepare_function_coefficients(context):
    if not admitted(context):
        raise CapabilityGap('function_coefficients.input_class_unavailable')
    return result({'description': deepcopy(context['formula_goal']), 'has_inequality': context['goal']['kind'] == 'find_range'}, [],
                  [{'kind': 'stated_function_type', 'passed': True}])


def expand_coefficient_relations(description):
    s = coefficient_source(description)
    return result({'identities': list(s.relations), 'variable': s.variable, 'parameters': list(s.coefficients),
                   'domain': sp.S.Reals}, ['function_formula_simplification'],
                  [{'kind': 'original_calls_expanded', 'passed': True}])


def compare_polynomial_coefficients(identities, variable, parameters, domain):
    comparison = compare_coefficients(identities, variable, parameters, domain)
    return result({'comparison': comparison}, ['polynomial_coefficient_identity'],
                  [{'kind': 'all_degrees_including_missing_terms', 'passed': True}])


def solve_function_coefficient_system(description, comparison):
    s = coefficient_source(description)
    if comparison != compare_coefficients(s.relations, s.variable, s.coefficients, sp.S.Reals):
        raise LocalCheckFailed('function_coefficients.coefficient_system_mismatch')
    tuples = solve_coefficients(s, comparison)
    proposed = complete_result(description, s, tuples)
    return result({'formula_result': proposed}, ['solve_polynomial_coefficients'],
                  [{'kind': 'all_type_valid_candidates', 'passed': verify_coefficients(description, proposed)}])


def verify_function_coefficients(description, formula_result):
    if not verify_coefficients(description, formula_result):
        raise LocalCheckFailed('function_coefficients.identity_or_completeness_mismatch')
    return result({'formula_result': deepcopy(formula_result)}, ['function_formula_identity'],
                  [{'kind': 'all_original_relations_and_complete_candidates', 'passed': True}])


def answer_for(r):
    def present(v):
        return None if v is None else {**math_value(v), 'exact': encode_value(v)}
    common = {'kind': r['goal_kind'], 'status': r['status'], 'function': r['function_name'],
              'variable': str(r['variable']), 'candidates': [present(v) for v in r['candidates']],
              'determined_domain': present(sp.S.Reals)}
    if r['goal_kind'] == 'find_value':
        return {**common, 'value': present(r['value']), 'candidate_values': [present(v) for v in r['values']]}
    if r['goal_kind'] == 'find_range':
        return {**common, 'set': present(r['solution'])}
    return {**common, 'expression': present(r['candidates'][0]) if len(r['candidates']) == 1 else None,
            'source_domain': present(sp.S.Reals), 'declared_domain': present(sp.S.Reals), 'requested_domain': None}


def finish_coefficients(state, context, previous):
    r = decode_value(state['formula_result_exact'])
    if not verify_coefficients(context['formula_goal'], r):
        raise LocalCheckFailed('function_coefficients.finalization_mismatch')
    answer = answer_for(r)
    consistency = 'conflict' if any(p['status'] == 'verified' and p.get('answer') != answer for p in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer, 'formula_result_exact': encode_value(r), 'consistency': consistency,
            **({'feasible_set': {**math_value(r['solution']), 'exact': encode_value(r['solution'])}} if r['goal_kind'] == 'find_range' and r['solution'] is not None else {})}


def coefficient_target_roots(description, formula_result):
    from .capabilities import solve_quadratic
    s = coefficient_source(description)
    if s.kind != 'find_range' or not verify_coefficients(description, formula_result):
        raise LocalCheckFailed('function_coefficients.inequality_target_required')
    op, rhs = s.requested
    residuals = [(p-rhs)*(1 if op in ('>', '>=') else -1) for p in formula_result['candidates']]
    records = [solve_quadratic(p, s.variable) for p in residuals]
    return result({'root_records': [r['outputs'] for r in records]}, ['quadratic_roots'],
                  [check for r in records for check in r['checks']])


def coefficient_target_signs(description, formula_result, root_records):
    from .capabilities import quadratic_sign_pattern
    s = coefficient_source(description)
    op, rhs = s.requested
    records = [quadratic_sign_pattern((p-rhs)*(1 if op in ('>', '>=') else -1), s.variable,
                                     record['roots'], op in ('>', '<'), record['all_zero'])
               for p, record in zip(formula_result['candidates'], root_records, strict=True)]
    if [r['outputs']['solution'] for r in records] != formula_result['solution_sets']:
        raise LocalCheckFailed('function_coefficients.inequality_solution_mismatch')
    return result({'checked_solutions': formula_result['solution_sets']}, ['quadratic_signs'],
                  [check for r in records for check in r['checks']])
