"""General-reflection execution, sharing M5's protocol while preserving the T3 route."""
from copy import deepcopy

from ..symmetry_relation_math import domain_set, image, reflections, solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .math_values import math_value
from .trajectory import decode_value, encode_value


def model(description):
    try:
        return solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc


def check_domain(description):
    try:
        edges, domain = reflections(description), domain_set(description['domain_ast'])
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc
    pairs = [{'source_ref': e['source_ref'], 'source': e['scope'],
              'image': image(e['scope'], -1, 2*e['a']), 'whole': e['whole']} for e in edges]
    return result({'domain_evidence': {'domain': domain, 'pairs': pairs}}, [],
                  [{'kind': 'general_reflection_domain_pairing', 'passed': True}])


def rewrite(description):
    m = model(description)
    return result({'rewrite': {'edges': m['edges'], 'maps': m['maps'], 'domain': m['domain']}}, [],
                  [{'kind': 'original_reflections_and_scopes', 'passed': True}])


def evaluate(description, rewrite):
    m = model(description)
    if rewrite != {'edges': m['edges'], 'maps': m['maps'], 'domain': m['domain']}:
        raise LocalCheckFailed('symmetry.transport_changed')
    return result({'rule_values': {'groups': m['groups'], 'extension': m['extension']}}, [],
                  [{'kind': 'finite_sum_and_affine_transport', 'passed': True}])


def confirm(description, rewrite, rule_values):
    m = model(description)
    if (rewrite != {'edges': m['edges'], 'maps': m['maps'], 'domain': m['domain']}
            or rule_values != {'groups': m['groups'], 'extension': m['extension']} or not verify(description, m)):
        raise LocalCheckFailed('symmetry.certificate_failed')
    return result({'symmetry_result': m}, [], [{'kind': 'symmetry_target_certified', 'passed': True}])


def answer_for(desc, m):
    determined = m['proof']['status'] == 'determined'
    return {'kind': desc['source']['kind'], 'status': 'complete' if determined else 'insufficient_information',
            'result_type': 'finite_sum' if desc['source']['kind'] == 'finite_sum' else 'scalar_value',
            'defined': True, 'domain': math_value(m['domain']),
            'value': math_value(m['proof']['value']) if determined else None, 'expression': None, 'is_constant': None}


def finish(state, context, previous):
    m = decode_value(state['symmetry_result_exact'])
    desc = context['symmetry_relation_goal']
    if not verify(desc, m):
        raise LocalCheckFailed('symmetry.finalization_failed')
    answer = answer_for(desc, m)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer, 'symmetry_result_exact': encode_value(m), 'consistency': consistency}
