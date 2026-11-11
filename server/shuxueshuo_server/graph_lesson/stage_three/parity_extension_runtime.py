"""Source-bound FP-T3 R0 execution: map the input, substitute, apply parity."""
from copy import deepcopy

import sympy as sp

from ..parity_extension_math import (
    SIGNS,
    _agree,
    combined_rule,
    ranges,
    reflect,
    solve,
    symbols,
    verify,
)
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .formula_runtime import answer_for as formula_answer
from .math_values import math_value
from .trajectory import decode_value, encode_value


def admitted(context):
    desc = context.get('parity_extension_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context.get('entries', [])]
    return bool(desc.get('structure_supported') and desc['source'] == context['goal']
                and desc['given_entries'] == entries)


def prepare(context):
    if not admitted(context):
        raise CapabilityGap('parity_ext.unsupported_source')
    return result({'description': deepcopy(context['parity_extension_goal'])}, [],
                  [{'kind': 'original_rule_range_and_target_bound', 'passed': True}])


def map_input(description):
    """S2 input half: the mirrored part of the request has -x inside the given rule's range."""
    _, known, requested, mirrored = ranges(description)
    mapped = reflect(mirrored)
    if (mirrored == sp.S.EmptySet and description['property'] != 'both') or not mapped.is_subset(known):
        raise CapabilityGap('parity_ext.requested_range_not_mirrored')
    return result({'mapping': {'known': known, 'requested': requested, 'mirrored': mirrored, 'mapped': mapped}}, [],
                  [{'kind': 'opposite_inputs_inside_rule_range', 'passed': True}])


def substitute(description, mapping):
    x = symbols(description)
    rule, _ = combined_rule(description)
    raw = rule.xreplace({x: -x})
    return result({'substitution': {'argument': -x, 'rule': rule, 'substituted': sp.expand(raw)}},
                  ['function_formula_simplification'], [{'kind': 'whole_opposite_input_substituted', 'passed': True}])


def write_back(description, substitution):
    """S2 value half: f(x)=s*f(-x), with the outer sign applied to the whole value."""
    sign = SIGNS[description['property']]
    return result({'write_back': {'sign': sign, 'substituted': substitution['substituted'],
                                  'expression': sp.expand(sign * substitution['substituted'])}}, [],
                  [{'kind': 'parity_relation_applied_to_whole_value', 'passed': True}])


def confirm(description, mapping, substitution, write_back):
    try:
        model = solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    x, mirror = symbols(description), reflect(model['rule_domain'])
    if (model['mapped_domain'] != mapping['mapped']
            or not _agree(model['substituted'], substitution['substituted'], mirror, x)
            or not _agree(model['expression'], write_back['expression'], mirror, x)
            or not verify(description, model)):
        raise LocalCheckFailed('parity_ext.certificate_failed')
    return result({'parity_extension_result': model}, [],
                  [{'kind': 'formula_determined_on_requested_range', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = (current == context and admitted(current)
             and verify(current['parity_extension_goal'], decode_value(encoded_result)))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_parity_extension_statement', 'passed': valid}],
            'processing': [{'source_ref': r['source_ref'], 'kind': 'original_parity_extension_condition',
                            'status': 'processed'} for r in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'parity_ext.independent_verification_failed'}]}


def answer_for(desc, model):
    """The determined domain is where the expression holds: the requested range minus its free part.

    A free part is part of the answer (a rule family), so it is stated, not dropped.
    """
    free = model['free_domain']
    extra = {} if free == sp.S.EmptySet else {'free_domain': {**math_value(free), 'exact': encode_value(free)}}
    if model['domain_identity'] == 'explicit':
        return {**formula_answer({'status': model['status'], 'function_name': desc['function'],
                                  'variable': model['variable'], 'expression': model['answer_expression'],
                                  'source_domain': model['rule_domain'],
                                  'determined_domain': model['requested_domain'] - free,
                                  'declared_domain': model['domain'], 'requested_domain': model['requested_domain']}),
                **extra}
    # Abstract D: ranges are the printed conditions, each read inside D; no complete domain is invented.
    requested = desc['requested_domain_ast']
    return {**formula_answer({'status': model['status'], 'function_name': desc['function'],
                              'variable': model['variable'], 'expression': model['answer_expression'],
                              'source_domain': model['rule_domain'], 'determined_domain': None,
                              'declared_domain': None,
                              'requested_domain': None if requested is None else model['requested_domain']}),
            'domain_identity': model['domain_identity'], **extra}


def finish(state, context, previous):
    model = decode_value(state['parity_extension_result_exact'])
    desc = context['parity_extension_goal']
    if not verify(desc, model):
        raise LocalCheckFailed('parity_ext.finalization_failed')
    answer = answer_for(desc, model)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer,
            'parity_extension_result_exact': encode_value(model), 'consistency': consistency}
