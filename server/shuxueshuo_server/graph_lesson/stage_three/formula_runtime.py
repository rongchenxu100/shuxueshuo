"""FR-T1 execution and typed completion, shared by authored and photo lessons."""

from copy import deepcopy

import sympy as sp

from ...problem_understanding.notation_parser import NotationError
from ..function_formula import recover, source_values, verify
from ..function_matching import verify_matching
from ..function_system import verify_system
from ..function_assignment import verify_assignment
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .math_values import math_value
from .trajectory import decode_value, encode_value


def admitted(context):
    if context.get('goal', {}).get('kind') != 'find_function_formula' or context.get('entries'):
        return False
    desc = context.get('formula_goal', {})
    if desc.get('structure_supported') is not True:
        return False
    try:
        source_values(desc)
        return True
    except (NotationError, KeyError, TypeError, ValueError):
        return False


def solve_function_formula(context):
    if not admitted(context):
        raise CapabilityGap('function_formula.input_class_unavailable')
    desc = deepcopy(context['formula_goal'])
    recovered = recover(desc)
    return result({'description': desc, 'formula_result': recovered},
                  [],
                  [{'kind': 'original_identity_and_image_coverage', 'passed': verify(desc, recovered)}])


def extract_formula_conditions(description, formula_result):
    source = source_values(description)
    if formula_result['source_domain'] != source.domain or formula_result['determined_domain'] != source.image:
        raise LocalCheckFailed('function_formula.input_range_mismatch')
    return result({'conditions': {'source_domain': source.domain, 'image': source.image}},
                  ['function_formula_conditions'], [{'kind': 'source_and_image', 'passed': True}])


def substitute_formula_input(description, conditions, formula_result):
    source = source_values(description)
    if conditions != {'source_domain': source.domain, 'image': source.image}:
        raise LocalCheckFailed('function_formula.input_range_mismatch')
    t = formula_result['variable']
    inverse = source.inverse_coordinate(t)
    if (formula_result['inverse_root'] != (inverse if source.root_input else None)
            or sp.cancel(source.inverse_input(t)-formula_result['inverse_input']) != 0):
        raise LocalCheckFailed('function_formula.inverse_mismatch')
    return result({'substitution': {'variable': t, 'coordinate': inverse, 'input': source.inverse_input(t), 'image': source.image}},
                  ['function_formula_substitution'], [{'kind': 'legal_inverse', 'passed': True}])


def simplify_formula_expression(description, substitution, formula_result):
    source = source_values(description)
    t = formula_result['variable']
    inverse = source.inverse_coordinate(t)
    if substitution != {'variable': t, 'coordinate': inverse, 'input': source.inverse_input(t), 'image': source.image}:
        raise LocalCheckFailed('function_formula.substitution_mismatch')
    expression = source.rewrite(t)
    if sp.cancel(expression-formula_result['expression']) != 0:
        raise LocalCheckFailed('function_formula.rewrite_mismatch')
    return result({'formula_result': {**formula_result, 'expression': expression}},
                  ['function_formula_simplification'], [{'kind': 'rewrite_right_side', 'passed': True}])


def verify_formula_identity(description, formula_result):
    checker = verify_matching if formula_result.get('derivation') == 'matching' else verify
    if not checker(description, formula_result):
        raise LocalCheckFailed('function_formula.identity_or_coverage_mismatch')
    return result({'formula_result': deepcopy(formula_result)}, ['function_formula_identity'],
                  [{'kind': 'original_identity_and_image_coverage', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    if current != context:
        raise LocalCheckFailed('function_formula.original_context_mismatch')
    proposed = decode_value(encoded_result)
    if proposed.get('derivation') == 'assignment':
        from .assignment_runtime import admitted as assignment_admitted
        valid = assignment_admitted(current) and verify_assignment(current['formula_goal'], proposed)
    elif proposed.get('derivation') == 'equation_system':
        from .system_runtime import admitted as system_admitted
        valid = system_admitted(current) and verify_system(current['formula_goal'], proposed)
    elif proposed.get('derivation') == 'coefficients':
        from .coefficients_runtime import admitted as coefficients_admitted
        from ..function_coefficients import verify_coefficients
        valid = coefficients_admitted(current) and verify_coefficients(current['formula_goal'], proposed)
    elif proposed.get('derivation') == 'matching':
        from .matching_runtime import admitted as matching_admitted
        valid = matching_admitted(current) and verify_matching(current['formula_goal'], proposed)
    else:
        valid = admitted(current) and verify(current['formula_goal'], proposed)
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': name, 'passed': valid} for name in
                       ('original_relation_identity', 'source_domain', 'image_and_coverage', 'requested_scope')],
            'source_refs': current['formula_goal']['source_refs'],
            'diagnostics': [] if valid else [{'code': 'function_formula.independent_verification_failed'}]}


def answer_for(recovered):
    def present(field):
        value = recovered[field]
        return None if value is None else {**math_value(value), 'exact': encode_value(value)}
    return {'kind': 'find_function_formula', 'status': recovered['status'],
            'function': recovered['function_name'], 'variable': str(recovered['variable']),
            **{field: present(field) for field in ('expression', 'source_domain', 'determined_domain',
                                                  'declared_domain', 'requested_domain')}}


def finish(state, context, previous):
    recovered = decode_value(state['formula_result_exact'])
    if recovered.get('derivation') == 'coefficients':
        from .coefficients_runtime import finish_coefficients
        return finish_coefficients(state, context, previous)
    checker = (verify_assignment if recovered.get('derivation') == 'assignment' else
               verify_system if recovered.get('derivation') == 'equation_system' else
               verify_matching if recovered.get('derivation') == 'matching' else verify)
    if not checker(context['formula_goal'], recovered):
        raise LocalCheckFailed('function_formula.finalization_mismatch')
    answer = answer_for(recovered)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer,
            'formula_result_exact': encode_value(recovered), 'consistency': consistency}
