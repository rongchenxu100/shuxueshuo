"""Legal specialization, linear elimination, simplification and full recheck."""
from copy import deepcopy

import sympy as sp

from ..function_assignment import (available, assignment_source, plan_assignment, specialized_equations,
                                    solve_specialized, result_for, valid_derivation, full_identity)
from .capabilities import CapabilityGap, LocalCheckFailed, result


def admitted(context):
    return (context.get('goal', {}).get('kind') == 'find_function_formula'
            and not context.get('entries') and available(context.get('formula_goal', {})))


def prepare_function_assignment(context):
    if not admitted(context):
        raise CapabilityGap('function_assignment.input_class_unavailable')
    desc = deepcopy(context['formula_goal'])
    try:
        plan = plan_assignment(desc)
    except ValueError as exc:
        raise CapabilityGap(getattr(exc, 'code', 'function_assignment.plan_unavailable')) from exc
    return result({'description': desc, 'assignment_plan': plan}, [],
                  [{'kind': 'two_universal_real_variables', 'passed': True}])


def specialize_function_relation(description, assignment_plan):
    s = assignment_source(description)
    equations = specialized_equations(s, assignment_plan)
    return result({'specialized': equations}, ['function_assignment_specialization'],
                  [{'kind': 'all_assigned_values_are_in_original_domain', 'passed': True}])


def solve_assignment_equations(description, assignment_plan, specialized):
    s = assignment_source(description)
    expression, zero = solve_specialized(s, assignment_plan, specialized)
    return result({'raw_expression': expression, 'zero_value': zero}, ['function_assignment_elimination'],
                  [{'kind': 'necessary_unique_candidate_from_specializations', 'passed': True}])


def simplify_assignment_formula(description, assignment_plan, raw_expression, zero_value):
    s = assignment_source(description)
    r = result_for(description, s, assignment_plan, sp.expand(raw_expression), zero_value)
    return result({'formula_result': r}, ['function_formula_simplification'],
                  [{'kind': 'simplified_function_rule', 'passed': True}])


def verify_assignment_formula(description, formula_result):
    if not valid_derivation(description, formula_result):
        raise LocalCheckFailed('function_assignment.specialization_derivation_failed')
    if not full_identity(assignment_source(description), formula_result['expression']):
        raise CapabilityGap('function_assignment.no_solution')
    return result({'formula_result': deepcopy(formula_result)}, ['function_assignment_identity'],
                  [{'kind': 'full_two_variable_identity_and_unique_solution', 'passed': True}])
