"""Source-bound FP-T3 R2 execution: rewrite opposite inputs, substitute the rule, combine."""
from copy import deepcopy

import sympy as sp

from ..parity_extension_math import SIGNS
from ..symmetry_value_math import rule_of, solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .math_values import math_value
from .trajectory import decode_value, encode_value


def admitted(context):
    desc = context.get('symmetry_value_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context.get('entries', [])]
    return bool(desc.get('structure_supported') and desc['source'] == context['goal']
                and desc['given_entries'] == entries)


def _borrow(context):
    """Call the T2 domain-parameter subtask on the facts it owns; the original target stays open."""
    from .parity_parameter_runtime import borrow_domain_parameter, verify_borrowed_parameter
    parameter = context['symmetry_value_goal']['parameter']
    output = borrow_domain_parameter(context, parameter['ref'], parameter['source_refs'])
    if not verify_borrowed_parameter(context, output):
        raise LocalCheckFailed('symmetry_value.borrowed_parameter_failed')
    return output


def _borrow_bound(context, model):
    """A parameter result is published only with a subtask that still verifies against the frozen context."""
    from .parity_parameter_runtime import verify_borrowed_parameter
    if not context['symmetry_value_goal'].get('parameter'):
        return model.get('borrow') is None
    return model.get('borrow') is not None and verify_borrowed_parameter(context, model['borrow']['output'])


def prepare(context):
    if not admitted(context):
        raise CapabilityGap('symmetry_value.unsupported_source')
    description = deepcopy(context['symmetry_value_goal'])
    checks = [{'kind': 'parity_value_target_and_conditions_bound', 'passed': True}]
    if description.get('parameter'):
        description['borrowed'] = _borrow(context)
        checks.append({'kind': 'borrowed_domain_parameter_verified', 'passed': True})
    return result({'description': description}, [], checks)


def _model(description):
    try:
        return solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc


def rewrite(description):
    """S2: F(c) = ±F(-c) for each input not used as written; stated identities at each input and its opposite."""
    model = _model(description)
    signs = {F['name']: SIGNS[F['property']] for F in description['functions']}
    calls = []
    for call in model['calls']:
        if call['route'] in ('mirrored_rule', 'unknown') and call['image'] == -call['input']:
            if call['factor'] != signs[call['function']]:
                raise LocalCheckFailed('symmetry_value.relation_sign')
        calls.append({k: call[k] for k in ('function', 'input', 'coefficient', 'route', 'image', 'factor')})
    instances = [{'source_ref': e['source_ref'], 'instance': e['instance']}
                 for e in model['equations'] if e['instance'] is not None]
    return result({'rewrite': {'signs': signs, 'calls': calls, 'instances': instances}}, [],
                  [{'kind': 'opposite_inputs_rewritten_by_parity', 'passed': True}])


def evaluate(description, rewrite):
    """Substitute the printed rule at inputs inside its range; odd f(0)=0 needs no rule."""
    if description.get('parameter'):
        description = _model(description)['description']
    rule, known = rule_of(description)
    x = sp.Symbol(description['variable'], real=True)
    values = {}
    for call in rewrite['calls']:
        if call['route'] in ('rule', 'mirrored_rule'):
            if known.contains(call['image']) is not sp.true:
                raise LocalCheckFailed('symmetry_value.input_outside_rule_range')
            values[call['image']] = rule.subs(x, call['image'])
    return result({'rule_values': {'values': [{'input': c, 'value': v} for c, v in values.items()]}},
                  ['function_formula_simplification'] if values else [],
                  [{'kind': 'rule_used_inside_its_range', 'passed': True}])


def confirm(description, rewrite, rule_values):
    model = _model(description)
    signs = {F['name']: SIGNS[F['property']] for F in description['functions']}
    used = {row['input']: row['value'] for row in rule_values['values']}
    for call in model['calls']:
        if call['route'] in ('rule', 'mirrored_rule') and sp.simplify(call['factor'] * used[call['image']] - call['value']) != 0:
            raise LocalCheckFailed('symmetry_value.certificate_failed')
    instances = [e['instance'] for e in model['equations'] if e['instance'] is not None]
    if [c['route'] for c in model['calls']] != [c['route'] for c in rewrite['calls']] or \
            [row['instance'] for row in rewrite['instances']] != instances or \
            rewrite['signs'] != signs or not verify(description, model):
        raise LocalCheckFailed('symmetry_value.certificate_failed')
    return result({'symmetry_result': model}, [],
                  [{'kind': 'value_target_certified', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    model = decode_value(encoded_result)
    valid = (current == context and admitted(current)
             and verify(current['symmetry_value_goal'], model) and _borrow_bound(current, model))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_symmetry_value_statement', 'passed': valid}],
            'processing': [{'source_ref': r['source_ref'], 'kind': 'original_symmetry_value_condition',
                            'status': 'processed'} for r in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'symmetry_value.independent_verification_failed'}]}


def answer_for(desc, model):
    """A value proved not unique is the answer itself (insufficient information), never a guessed number."""
    determined = model['status'] == 'determined'
    return {'kind': 'find_value', 'status': 'complete' if determined else 'insufficient_information',
            'result_type': 'scalar_value', 'defined': True, 'domain': math_value(sp.S.Reals),
            'value': math_value(model['value']) if determined else None, 'expression': None, 'is_constant': None}


def finish(state, context, previous):
    model = decode_value(state['symmetry_result_exact'])
    desc = context['symmetry_value_goal']
    if not verify(desc, model) or not _borrow_bound(context, model):
        raise LocalCheckFailed('symmetry_value.finalization_failed')
    answer = answer_for(desc, model)
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer,
            'symmetry_result_exact': encode_value(model), 'consistency': consistency}
