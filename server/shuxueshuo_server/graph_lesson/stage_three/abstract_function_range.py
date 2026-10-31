"""Transfer a known image only after proving complete coverage of its inputs."""

import sympy as sp

from ..stage_one.abstract_function_range import inspect_abstract_range_target
from .abstract_function_domain import (
    _domain_set,
    _verification_set,
    _verification_source,
    _verify_partition,
    affine_image,
    solve_abstract_domain,
)
from .capabilities import CapabilityGap, result
from .capabilities.cases import exact_set_equal
from .math_values import math_value


def transfer(description):
    if (description.get('kind') != 'find_abstract_range'
            or description.get('target_form') != 'plain'
            or not description.get('known_range_ast')):
        raise CapabilityGap('abstract_range.original_known_range_required')
    solved = solve_abstract_domain(description)['outputs']
    domain = solved['candidate_set']
    if domain == sp.S.EmptySet:
        raise CapabilityGap('abstract_range.empty_target_domain')
    slope, intercept = sp.Rational(description['target_slope']), sp.Rational(description['target_intercept'])
    covered = affine_image(domain, slope, intercept) if slope != 0 else sp.FiniteSet(intercept)
    if not exact_set_equal(covered, solved['input_range']):
        raise CapabilityGap('abstract_range.partial_input_coverage')
    image = _domain_set(description, 'known_range_ast')
    if image == sp.S.EmptySet:
        raise CapabilityGap('abstract_range.empty_known_range')
    if (isinstance(solved['input_range'], sp.FiniteSet) and len(solved['input_range']) == 1
            and (not isinstance(image, sp.FiniteSet) or len(image) != 1)):
        raise CapabilityGap('abstract_range.inconsistent_singleton_image')
    return {**solved, 'domain': domain, 'covered': covered, 'image': image}


def admitted(context):
    if context.get('goal', {}).get('kind') != 'find_abstract_range' or context.get('entries'):
        return False
    try:
        transfer(context.get('abstract_range_goal') or {})
        return True
    except (CapabilityGap, ValueError, KeyError, TypeError):
        return False


def transfer_abstract_range(context):
    if not admitted(context):
        raise CapabilityGap('abstract_range.not_admitted')
    values = transfer(context['abstract_range_goal'])
    description = {**values['description'], 'transfer': {
        key: values[key] for key in ('domain', 'input_range', 'covered', 'known_domain', 'image')
    }}
    checks = [{'kind': 'abstract_range_full_input_coverage', 'passed': True,
               'target_domain': math_value(values['domain']),
               'covered': math_value(values['covered']),
               'original_inputs': math_value(values['input_range']),
               'source_refs': [description[key] for key in
                               ('known_call_source_ref', 'known_domain_source_ref', 'known_range_source_ref',
                                'target_call_source_ref')]
               + ([description['source_ref'] + '/input_domain'] if description['has_outer_domain'] else [])}]
    return result({'description': description, 'function': values['complete_input'],
                   'variable': values['variable'], 'domain': values['domain'],
                   'feasible_set': values['image']}, ['abstract_range_full_input_coverage'], checks)


def independent_verify(candidate, target_ref, feasible_set):
    """Rebuild domain by truth-cell verification, then image by source substitution.

    This path does not use the solver's affine image/preimage or cached output.
    Coverage is compared in the original known call's own variable coordinates.
    """
    description = inspect_abstract_range_target(candidate, target_ref)
    if not description['structure_supported']:
        raise CapabilityGap('abstract_range.verification_source_unsupported')
    source = _verification_source(candidate, target_ref, range_goal=True)
    domain, cells = _verify_partition(source)
    expression, variable = source['membership_expression'], source['variable']
    covered = (sp.imageset(sp.Lambda(variable, expression), domain)
               if domain != sp.S.EmptySet else sp.S.EmptySet)
    full = domain != sp.S.EmptySet and exact_set_equal(covered, source['known'])
    expected = _verification_set(description['known_range_ast'])
    consistent = expected != sp.S.EmptySet
    if isinstance(source['known'], sp.FiniteSet) and len(source['known']) == 1:
        consistent = isinstance(expected, sp.FiniteSet) and len(expected) == 1
    matches = isinstance(feasible_set, sp.Set) and exact_set_equal(expected, feasible_set)
    checks = [{'kind': 'target_domain_from_original_constraints', 'passed': True,
               'domain': math_value(domain), 'cells': cells},
              {'kind': 'complete_known_input_coverage', 'passed': full,
               'covered': math_value(covered), 'required': math_value(source['known'])},
              {'kind': 'known_output_range_consistent', 'passed': consistent},
              {'kind': 'known_output_range_preserved', 'passed': matches,
               'source_ref': description['known_range_source_ref']}]
    passed = full and matches and consistent
    return {'status': 'verified' if passed else 'math_failed',
            'proof': {'kind': 'abstract_range_full_input_coverage', 'passed': passed, 'checks': checks,
                      'expected': math_value(expected), 'actual': math_value(feasible_set)},
            'diagnostics': [] if passed else [{'code': 'abstract_range.coverage_or_image_mismatch'}]}


def image_endpoints(candidate, target_ref, feasible_set):
    verification = independent_verify(candidate, target_ref, feasible_set)
    if verification['status'] != 'verified':
        raise CapabilityGap('abstract_range.unverified_image')
    # Endpoint attainment is inherited from an exact known range after full
    # coverage. No formula or input witness for the unknown function is invented.
    checks = [{'point': math_value(point), 'included': point in feasible_set,
               'holds': point in feasible_set, 'passed': True,
               'evidence': {'kind': 'known_range_under_full_input_coverage'}}
              for point in sorted(feasible_set.boundary)]
    return {'status': 'passed', 'checks': checks}
