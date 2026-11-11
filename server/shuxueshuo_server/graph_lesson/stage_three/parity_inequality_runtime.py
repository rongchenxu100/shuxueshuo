"""Source-bound FP-T4 execution: the half-axis route (R0), the one-comparison route (R1–R2) and the sign route (R3)."""
from copy import deepcopy

import sympy as sp

from .. import parity_order_math as order
from ..parity_inequality_math import FLIP, OPS, SIGNS, _rule, _same, reflect, solve, symbols, threshold, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .trajectory import decode_value, encode_value


def admitted(context):
    desc = context.get('parity_inequality_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context.get('entries', [])]
    return bool(desc.get('structure_supported') and desc['source'] == context['goal']
                and desc['given_entries'] == entries)


def _borrow(context):
    """The T2 domain-parameter subtask on the domain and parity facts it owns; the original target stays open."""
    from .parity_parameter_runtime import borrow_domain_parameter, verify_borrowed_parameter
    parameter = context['parity_inequality_goal']['parameter']
    output = borrow_domain_parameter(context, parameter['ref'], parameter['source_refs'])
    if not verify_borrowed_parameter(context, output):
        raise LocalCheckFailed('parity_ineq.borrowed_parameter_failed')
    return output


def _borrow_bound(context, model):
    """A parameter result is published only with a subtask that still verifies against the frozen context."""
    from .parity_parameter_runtime import verify_borrowed_parameter
    if not context['parity_inequality_goal'].get('parameter'):
        return model.get('borrow') is None
    return model.get('borrow') is not None and verify_borrowed_parameter(context, model['borrow']['output'])


def prepare(context):
    if not admitted(context):
        raise CapabilityGap('parity_ineq.unsupported_source')
    description = deepcopy(context['parity_inequality_goal'])
    checks = [{'kind': 'original_rule_range_and_inequality_bound', 'passed': True}]
    if description.get('parameter'):
        description['borrowed'] = _borrow(context)
        checks.append({'kind': 'borrowed_domain_parameter_verified', 'passed': True})
    return result({'description': description}, [], checks)


def instance(description):
    """The numeric statement after the borrowed parameter value is put in."""
    if not description.get('parameter'):
        return description
    try:
        return solve(description)['description']
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc


def rewrite(description):
    """S2 on values: odd s·f(u) = f(s·u) moves one call across; even f(u) = f(|u|) keeps both on one side."""
    description = instance(description)
    x = sp.Symbol(description['variable'], real=True)
    op, a, w = order.comparison(description['operator'], description['terms'], x)
    inputs = [order.read_input(t, x) for _, t in description['terms']]
    return result({'rewrite': {'operator': op, 'left': a, 'right': w, 'inputs': inputs,
                               'signs': [s for s, _ in description['terms']],
                               'absolute': description['property'] == 'even'}},
                  ['whole_input_substitution'], [{'kind': 'odd_values_rewritten_as_one_comparison', 'passed': True}])


def direction(description):
    """S3 with the junction across 0, a printed direction already covering D, or (even) the reversed reflection."""
    description = instance(description)
    try:
        cert = order.certificate(description)
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc
    source = description['direction_source']
    if cert['kind'] == 'rule':
        operations = ['monotonicity_structure', 'parity_monotonicity_transfer', 'monotonicity_junction']
    elif cert['kind'] == 'even_rule':
        operations = ['monotonicity_structure', 'parity_monotonicity_transfer']
    elif cert['kind'] == 'even_given':
        operations = ['parity_monotonicity_transfer']
    elif cert['kind'] == 'given_half':
        operations = ['parity_monotonicity_transfer', 'monotonicity_junction']
    else:
        operations = ['monotonicity_difference'] if source['basis']['kind'] != 'stated' else []
    return result({'direction': cert}, operations, [{'kind': 'strict_direction_on_whole_domain', 'passed': True}])


def compare(description, rewrite, direction):
    """Both inputs in D, where f is strictly monotone on the compared side: drop f, keeping or reversing the relation."""
    description = instance(description)
    x = sp.Symbol(description['variable'], real=True)
    if len(rewrite['inputs']) == 1 and direction['domain'].contains(0) is not sp.true:
        raise CapabilityGap('parity_ineq.zero_not_in_domain')
    legal = order.legal_set(rewrite['inputs'], x, direction['domain']) & order.source_allowed(description, x)
    turn = order.compare_direction(direction) != 'increasing'
    converted = order.FLIP[rewrite['operator']] if turn else rewrite['operator']
    return result({'comparison': {'legal_set': legal, 'converted_operator': converted}},
                  ['mono_inequality_inputs', 'mono_inequality_order', 'domain_intersection'],
                  [{'kind': 'inputs_compared_inside_monotone_domain', 'passed': True}])


def confirm_order(description, rewrite, direction, comparison):
    try:
        model = solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    if (sp.expand(model['left_input'] - rewrite['left']) != 0 or sp.expand(model['right_input'] - rewrite['right']) != 0
            or model['operator'] != rewrite['operator'] or model['certificate'] != direction
            or rewrite['absolute'] != (model['description']['property'] == 'even')
            or model['converted_operator'] != comparison['converted_operator']
            or not _same(model['legal_set'], comparison['legal_set'])
            or not verify(description, model)):
        raise LocalCheckFailed('parity_ineq.certificate_failed')
    return result({'parity_inequality_result': model}, [],
                  [{'kind': 'solution_set_verified_on_domain', 'passed': True}])


def _sign_certificate(description):
    from .. import parity_sign_math as sign
    try:
        return sign.certificate(description)
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc


def _same_cells(a, b):
    return len(a) == len(b) and all(_same(p, q) and v == w for (p, v), (q, w) in zip(a, b))


def sign_known(description):
    """Strict direction on I and the zero there: f is negative on one part of I and positive on the other."""
    cert = _sign_certificate(description)
    return result({'known_signs': {k: cert[k] for k in ('interval', 'direction', 'zero', 'known')}},
                  ['mono_inequality_order'], [{'kind': 'signs_on_monotone_interval_from_zero', 'passed': True}])


def sign_mirror(description, known_signs):
    """f(−t) = ∓f(t): the sign on −I is the reflected one, flipped for an odd f."""
    from .. import parity_sign_math as sign
    parity = sign.SIGNS[description['property']]
    mirrored = []
    for part, value in known_signs['known']:
        image = reflect(part) - known_signs['interval']
        if image != sp.S.EmptySet:
            mirrored.append((image, parity * value))
    if not mirrored:
        raise CapabilityGap('parity_ineq.requested_range_not_mirrored')
    return result({'mirrored_signs': {'parity': parity, 'mirrored': mirrored}}, ['parity_sign_reflection'],
                  [{'kind': 'signs_carried_by_parity', 'passed': True}])


def sign_solve(description, known_signs, mirrored_signs):
    """Each sign cell of f, pulled back through the input and met with the sign of the factor, in every D case."""
    from .. import parity_sign_math as sign
    x = sp.Symbol(description['variable'], real=True)
    cert = _sign_certificate(description)
    if not _same_cells(cert['known'], known_signs['known']) or not _same_cells(cert['mirrored'], mirrored_signs['mirrored']):
        raise LocalCheckFailed('parity_ineq.sign_table_mismatch')
    try:
        cases, identity = sign.domain_cases(description, cert)
        u, q = sign.input_of(description, x), sign.factor_of(description, x)
    except ValueError as exc:
        raise CapabilityGap(str(exc)) from exc
    rows = []
    for domain, zero_sign in cases:
        legal, solution = sign.solve_description_case(description, u, q, x, sign.sign_cells(cert, zero_sign))
        rows.append({'domain': domain, 'zero_sign': zero_sign, 'legal_set': legal, 'solution': solution})
    operations = ['intersect_case_conditions', 'union_disjoint_cases']
    if description['factor_kind'] == 'quotient':
        operations.insert(0, 'domain_denominator_conditions')
    return result({'sign_solution': {'identity': identity, 'cases': rows}}, operations,
                  [{'kind': 'sign_cells_cover_every_domain_case', 'passed': True}])


def confirm_sign(description, known_signs, mirrored_signs, sign_solution):
    try:
        model = solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    cert = model['certificate']
    rows = sign_solution['cases']
    if (not _same_cells(cert['known'], known_signs['known']) or not _same_cells(cert['mirrored'], mirrored_signs['mirrored'])
            or cert['domain_identity'] != sign_solution['identity'] or len(rows) != len(model['cases'])
            or any(not _same(a['solution'], b['solution']) or not _same(a['legal_set'], b['legal_set'])
                   for a, b in zip(rows, model['cases']))
            or not verify(description, model)):
        raise LocalCheckFailed('parity_ineq.certificate_failed')
    return result({'parity_inequality_result': model}, [],
                  [{'kind': 'solution_set_verified_on_domain', 'passed': True}])


def solve_known(description):
    """On the given range the printed rule is f itself."""
    x = symbols(description)
    rule, known = _rule(description)
    op, k = description['operator'], threshold(description)
    solution = sp.solveset(OPS[op](rule, k), x, known)
    shape = 'quadratic_signs' if sp.degree(rule, x) == 2 else 'degenerate_linear_or_constant'
    return result({'known_side': {'rule': rule, 'known': known, 'operator': op, 'threshold': k, 'solution': solution}},
                  [shape, 'domain_intersection'], [{'kind': 'inequality_solved_on_given_range', 'passed': True}])


def mirror(description, known_side):
    """S2: for x in −I, f(x)=s·f(−x); an odd sign flips the relation and the threshold."""
    x = symbols(description)
    sign = SIGNS[description['property']]
    op, k = known_side['operator'], known_side['threshold']
    mop, mk = (op, k) if sign == 1 else (FLIP[op], -k)
    condition = (known_side['solution'] if sign == 1
                 else sp.solveset(OPS[mop](known_side['rule'], mk), x, known_side['known']))
    mapped = reflect(known_side['known']) - known_side['known']
    if mapped == sp.S.EmptySet:
        raise CapabilityGap('parity_ineq.requested_range_not_mirrored')
    return result({'mirror': {'sign': sign, 'operator': mop, 'threshold': mk, 'condition_solution': condition,
                              'mirrored_domain': mapped, 'solution': reflect(condition) & mapped}},
                  ['whole_input_substitution', 'domain_intersection'],
                  [{'kind': 'parity_relation_carries_inequality', 'passed': True}])


def confirm(description, known_side, mirror):
    try:
        model = solve(description)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    if (not _same(model['known_solution'], known_side['solution'])
            or not _same(model['mirror_solution'], mirror['condition_solution'])
            or model['mirror_operator'] != mirror['operator'] or model['mirror_threshold'] != mirror['threshold']
            or not _same(model['mirrored_solution'], mirror['solution'] & model['mirrored_domain'])
            or not verify(description, model)):
        raise LocalCheckFailed('parity_ineq.certificate_failed')
    return result({'parity_inequality_result': model}, [],
                  [{'kind': 'solution_set_verified_on_domain', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    model = decode_value(encoded_result)
    valid = (current == context and admitted(current)
             and verify(current['parity_inequality_goal'], model) and _borrow_bound(current, model))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_parity_inequality_statement', 'passed': valid}],
            'processing': [{'source_ref': r['source_ref'], 'kind': 'original_parity_inequality_condition',
                            'status': 'processed'} for r in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'parity_ineq.independent_verification_failed'}]}


def finish(state, context, previous):
    from .goals import _exact_math, finalize_goal_with_evidence
    model = decode_value(state['parity_inequality_result_exact'])
    if not verify(context['parity_inequality_goal'], model) or not _borrow_bound(context, model):
        raise LocalCheckFailed('parity_ineq.finalization_failed')
    answer, _ = finalize_goal_with_evidence({'kind': 'find_range'}, model['solution'])
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer, 'parity_inequality_result_exact': encode_value(model),
            'feasible_set': _exact_math(model['solution']), 'consistency': consistency}
