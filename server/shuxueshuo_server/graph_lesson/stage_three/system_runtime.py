"""Public equality/substitution, elimination and simplification operations for C."""
from copy import deepcopy

import sympy as sp

from ..function_system import available, system_source, interchange, eliminate, result_for, verify_system
from .capabilities import CapabilityGap, LocalCheckFailed, result


def admitted(context):
    return (context.get('goal', {}).get('kind') == 'find_function_formula'
            and not context.get('entries') and available(context.get('formula_goal', {})))


def prepare_function_system(context):
    if not admitted(context):
        raise CapabilityGap('function_system.input_class_unavailable')
    return result({'description': deepcopy(context['formula_goal'])}, [],
                  [{'kind': 'two_related_function_inputs', 'passed': True}])


def interchange_function_inputs(description):
    s = system_source(description)
    return result({'rhs_swapped': interchange(s)}, ['function_system_substitution'],
                  [{'kind': 'domain_closed_under_involution', 'passed': True}])


def eliminate_function_values(description, rhs_swapped):
    s = system_source(description)
    try:
        expression = eliminate(s, rhs_swapped)
    except ValueError as exc:
        raise CapabilityGap(getattr(exc, 'code', 'function_system.elimination_unavailable')) from exc
    return result({'raw_expression': expression}, ['function_system_elimination'],
                  [{'kind': 'nonzero_determinant', 'passed': s.determinant != 0}])


def simplify_system_formula(description, raw_expression):
    s = system_source(description)
    proposed = result_for(description, s, sp.cancel(raw_expression))
    return result({'formula_result': proposed}, ['function_formula_simplification'],
                  [{'kind': 'simplified_function_rule', 'passed': True}])


def verify_system_formula(description, formula_result):
    if not verify_system(description, formula_result):
        raise LocalCheckFailed('function_system.original_identity_or_uniqueness_failed')
    return result({'formula_result': deepcopy(formula_result)}, ['function_system_identity'],
                  [{'kind': 'original_identity_and_unique_solution', 'passed': True}])
