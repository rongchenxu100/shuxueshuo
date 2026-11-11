"""M1 parity-by-definition operations, shared by photo and topic routes."""

from copy import deepcopy

from ...problem_understanding.notation_parser import NotationError
from .. import function_cells
from ..function_parity import (
    _same_set,
    collect,
    domain_symmetry,
    reflect_ast,
    reflected_descriptor,
    relation,
    repeats_goal_definition,
    verify,
)
from .capabilities import CapabilityGap, LocalCheckFailed
from .trajectory import decode_value, encode_value

LABELS = {'odd_only': '奇函数', 'even_only': '偶函数', 'both': '既是奇函数又是偶函数', 'neither': '既不是奇函数也不是偶函数'}


def admitted(context):
    goal = context.get('parity_goal') or {}
    return (context.get('goal', {}).get('kind') == 'determine_function_parity'
            and goal.get('structure_supported') is True
            and all(repeats_goal_definition(row['ast'], row['expression'], goal['function'])
                    for row in context.get('entries', [])))


def _result(outputs, operation, checks=()):
    return {'outputs': outputs, 'operations': [operation],
            'checks': [{'kind': operation, 'passed': True}, *checks]}


def prepare_function_parity(context):
    if not admitted(context):
        raise CapabilityGap((context.get('parity_goal') or {}).get('reason') or 'function_parity.input_class_unavailable')
    goal = deepcopy(context['parity_goal'])
    return _result({'parity_goal': goal, 'function': goal['function']}, 'parity_scope')


def check_domain_symmetry(parity_goal, solved):
    try:
        domain, natural = function_cells.source_domain(parity_goal['function'])
        if not _same_set(solved['domain'], domain) or not _same_set(solved['natural_domain'], natural):
            raise LocalCheckFailed('function_parity.child_domain_mismatch')
        symmetry = domain_symmetry(parity_goal['function'], solved['domain'])
    except NotationError as exc:
        raise CapabilityGap(getattr(exc, 'code', 'function_parity.domain_unavailable')) from exc
    evidence = {'solved': solved, 'symmetry': symmetry}
    return _result({'domain_evidence': evidence, 'symmetric': symmetry['status'] == 'proved'},
                   'domain_reflection_symmetry')


def reflect_function_input(parity_goal):
    function = parity_goal['function']
    reflected = reflected_descriptor(function)
    if reflect_ast(function['expression_ast']) != reflected['expression_ast']:
        raise LocalCheckFailed('function_parity.substitution_mismatch')
    return _result({'reflected': {'expression_ast': reflected['expression_ast'],
                                  'input_domain_ast': reflected['input_domain_ast'],
                                  'derivation': reflected['derivation']}}, 'whole_input_substitution')


def compare_parity_relations(parity_goal, domain_evidence, reflected):
    function = parity_goal['function']
    if reflected['expression_ast'] != reflect_ast(function['expression_ast']):
        raise LocalCheckFailed('function_parity.substitution_mismatch')
    symmetry = domain_evidence['symmetry']
    rows = {prop: relation(function, symmetry, prop) for prop in ('odd', 'even')}
    gaps = [row['reason'] for row in rows.values() if row['status'] == 'unresolved']
    if gaps:
        raise CapabilityGap(gaps[0])
    result = _result({'relations': rows}, 'parity_relation_comparison')
    if any(row['status'] == 'refuted' and row['reason'] == 'output_counterexample' for row in rows.values()):
        result['operations'].append('parity_value_counterexample')
    return result


def collect_function_parity(parity_goal, domain_evidence, relations):
    result = collect(parity_goal, domain_evidence['solved'], domain_evidence['symmetry'],
                     relations['odd'], relations['even'])
    if result['classification'] is None:
        raise CapabilityGap('function_parity.relation_unresolved')
    return _result({'parity_result': result}, 'parity_classification')


def answer_for(result):
    return {'kind': 'determine_function_parity', 'status': 'complete',
            'classification': result['classification'],
            'odd': result['odd']['status'], 'even': result['even']['status'],
            'latex': rf"\text{{{LABELS[result['classification']]}}}"}


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context

    current = build_context(candidate, target_ref)
    if current != context or not admitted(current):
        raise LocalCheckFailed('function_parity.original_context_mismatch')
    verified = verify(current['parity_goal'], decode_value(encoded_result))
    return {**verified, 'checks': [{'kind': 'domain_symmetry_and_both_relations', 'passed': verified['status'] == 'verified'}],
            'processing': [{'source_ref': row['source_ref'], 'kind': 'identical_function_definition',
                            'status': 'processed'} for row in current['entries']]
                          if verified['status'] == 'verified' else []}


def finish(state, context, previous):
    result = decode_value(state['parity_result_exact'])
    if verify(context['parity_goal'], result)['status'] != 'verified':
        raise LocalCheckFailed('function_parity.finalization_failed')
    answer = answer_for(result)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer,
            'parity_result_exact': encode_value(result), 'consistency': consistency}
