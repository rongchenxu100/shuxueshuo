"""A3 matching execution: coefficient identity, simplified rule and coverage."""

from copy import deepcopy

from ..function_matching import available, recover_matching, verify_matching
from .capabilities import CapabilityGap, LocalCheckFailed, result


def admitted(context):
    return (context.get('goal', {}).get('kind') == 'find_function_formula'
            and not context.get('entries') and available(context.get('formula_goal', {})))


def solve_function_matching(context):
    if not admitted(context):
        raise CapabilityGap('function_matching.input_class_unavailable')
    desc = deepcopy(context['formula_goal'])
    recovered = recover_matching(desc)
    return result({'description': desc, 'formula_result': recovered}, [],
                  [{'kind': 'matching_identity', 'passed': verify_matching(desc, recovered)}])


def complete_matching_identity(description, formula_result):
    if not verify_matching(description, formula_result):
        raise LocalCheckFailed('function_matching.identity_or_coverage_mismatch')
    return result({'formula_result': deepcopy(formula_result)}, ['function_matching_identity'],
                  [{'kind': 'whole_input_polynomial_identity', 'passed': True}])


def simplify_matching_expression(description, formula_result):
    if not verify_matching(description, formula_result):
        raise LocalCheckFailed('function_matching.expression_mismatch')
    return result({'formula_result': deepcopy(formula_result)}, ['function_formula_simplification'],
                  [{'kind': 'simplified_polynomial', 'passed': True}])
