"""Source-bound FP-T2 execution; coefficient comparison is a public skill call."""
from copy import deepcopy

import sympy as sp

from ..parity_parameter_math import identities, solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .goals import _exact_math, finalize_goal_with_evidence
from .trajectory import decode_value, encode_value


def admitted(context):
    desc = context.get('parity_parameter_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression', 'ast')} for r in context.get('entries', [])]
    return bool(desc.get('structure_supported') and desc['source'] == context['goal']
                and desc['given_entries'] == entries)


def prepare(context):
    if not admitted(context):
        raise CapabilityGap('parity_param.unsupported_source')
    return result({'description': deepcopy(context['parity_parameter_goal'])}, [],
                  [{'kind': 'original_parameter_statement_bound', 'passed': True}])


def form_identities(description):
    if description.get('analysis_mode') == 'joint':
        from ..parity_parameter_joint import source
        x, ps, expr, domain, _, signs = source(description)
        return result({'identities': [sp.Eq(expr.subs(x, -x), s*expr, evaluate=False) for s in signs],
                       'variable': x, 'parameters': ps, 'domain': domain}, [],
                      [{'kind': 'joint_parameters_and_fixed_domain', 'passed': True}])
    if description.get('analysis_mode') == 'original':
        from ..parity_parameter_original import symbols
        x, p = symbols(description)
        return result({'identities': [], 'variable': x, 'parameters': [p], 'domain': None}, [],
                      [{'kind': 'original_domain_relation_required', 'passed': True}])
    if description.get('analysis_mode') == 'domain':
        from ..parity_parameter_domain import source
        x, p, expr, _, _, signs = source(description)
        relations = [sp.Eq(expr.subs(x, -x), sign*expr, evaluate=False) for sign in signs] if expr is not None else []
        return result({'identities': relations, 'variable': x, 'parameters': [p], 'domain': None}, [],
                      [{'kind': 'relation_restricted_to_given_domain', 'passed': True}])
    relations, variable, parameters, domain = identities(description)
    return result({'identities': relations, 'variable': variable, 'parameters': parameters, 'domain': domain},
                  ['function_formula_simplification'], [{'kind': 'unevaluated_parity_identities', 'passed': True}])


def analyze_domain(domain_ast, parameter, parameter_ref, source_refs):
    from ..parameter_domain import (
        solve_domain_symmetry_conditions,
        verify_domain_symmetry_conditions,
    )
    inputs = {'domain_ast': domain_ast, 'parameter': parameter, 'parameter_ref': parameter_ref, 'source_refs': source_refs}
    proof = solve_domain_symmetry_conditions(**inputs)
    if not verify_domain_symmetry_conditions(**inputs, proof=proof):
        raise LocalCheckFailed('parity_param.domain_certificate_failed')
    return result({'domain_evidence': proof}, [], [{'kind': 'complete_affine_domain_pairing', 'passed': True}])


def compare_domain(description, domain_evidence):
    from ..parity_parameter_domain import compare
    return result({'comparison': compare(description, domain_evidence)}, [],
                  [{'kind': 'parity_relations_on_complete_domain', 'passed': True}])


def compare_quartic(identities, variable, parameters, domain):
    from ..function_coefficients import compare_quartic_coefficients
    return result({'comparison': compare_quartic_coefficients(identities, variable, parameters, domain)},
                  ['polynomial_coefficient_identity'], [{'kind': 'all_degrees_through_four', 'passed': True}])


def compare_original(description):
    from ..parity_parameter_original import compare
    return result({'comparison': compare(description)}, [],
                  [{'kind': 'original_guards_and_complete_mirror_cells', 'passed': True}])


def compare_joint(description):
    from ..parity_parameter_joint import compare
    return result({'comparison': compare(description)}, [],
                  [{'kind': 'joint_affine_parity_obligations', 'passed': True}])


def solve_conditions(description, comparison):
    try:
        model = solve(description, comparison)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    if not verify(description, model):
        raise LocalCheckFailed('parity_param.certificate_failed')
    return result({'parity_parameter_result': model}, [],
                  [{'kind': 'complete_parameter_conditions', 'passed': True}])


def confirm(description, parity_parameter_result):
    if not verify(description, parity_parameter_result):
        raise LocalCheckFailed('parity_param.certificate_failed')
    return result({'parity_parameter_result': parity_parameter_result}, [],
                  [{'kind': 'necessary_and_sufficient_parameter_conditions', 'passed': True}])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = (current == context and admitted(current)
             and verify(current['parity_parameter_goal'], decode_value(encoded_result)))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_parity_parameter_statement', 'passed': valid}],
            'processing': [{'source_ref': r['source_ref'], 'kind': 'original_parity_parameter_condition',
                            'status': 'processed'} for r in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'parity_param.independent_verification_failed'}]}


def finish(state, context, previous):
    model = decode_value(state['parity_parameter_result_exact'])
    if not verify(context['parity_parameter_goal'], model):
        raise LocalCheckFailed('parity_param.finalization_failed')
    joint = context['parity_parameter_goal'].get('analysis_mode') == 'joint'
    solution = None if joint else model['feasible_set']
    if joint:
        from .parity_joint_presentation import answer_for
        answer = answer_for(context['parity_parameter_goal'], model)
    elif context['goal']['kind'] == 'find_range':
        answer, _ = finalize_goal_with_evidence(context['goal'], solution)
    else:
        single = isinstance(solution, sp.FiniteSet) and len(solution) == 1
        answer = {'kind': 'find_value', 'status': 'complete', 'result_type': 'parameter_value',
                  'parameter': context['parity_parameter_goal']['parameter'],
                  'value': _exact_math(next(iter(solution))) if single else None,
                  'parameter_set': _exact_math(solution)}
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer,
            'parity_parameter_result_exact': encode_value(model), 'consistency': consistency,
            **({'feasible_set': _exact_math(solution)} if context['goal']['kind'] == 'find_range' and not joint else {})}


def _subtask_description(context, parameter_ref, source_refs):
    from ..parity_parameter_domain import populate
    selected = set(source_refs)
    entries = [r for r in context['entries'] if r['source_ref'] in selected]
    if (not selected or len(selected) != len(source_refs) or len(entries) != len(selected)
            or not any(s['ref'] == parameter_ref and s['kind'] == 'scalar' for s in context['symbols'])):
        raise CapabilityGap('parity_param.subtask_source_binding')
    facts = [r for r in entries if r['ast'][0] == 'function_parity']
    refs = {r['ast'][1][1] for r in facts}
    if len(refs) != 1:
        raise CapabilityGap('parity_param.single_function_required')
    function_ref, = refs
    definitions = [r for r in entries if r['ast'][:2] == ['function_definition', ['ref', function_ref, 'function']]]
    description = {'source': {'kind': 'derived_parameter_conditions', 'parameter_ref': parameter_ref},
                   'parent_target_ref': context['target_ref'], 'parent_goal': deepcopy(context['goal']),
                   'target_ref': context['target_ref'] + '#parity-parameter',
                   'parameter_ref': parameter_ref, 'parameter': parameter_ref.rsplit(':', 1)[-1],
                   'source_refs': list(source_refs),
                   'given_entries': [{k: deepcopy(r[k]) for k in ('source_ref', 'expression', 'ast')} for r in entries],
                   'structure_supported': False, 'reason': ''}
    try:
        populate(description, entries, facts, definitions, function_ref)
        description['structure_supported'] = True
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    return description


def borrow_domain_parameter(context, parameter_ref, source_refs):
    """A T3/T4 child obligation; this never completes or rewrites a parent goal.

    The parent selects the original facts this child is responsible for. Every
    other fact is returned as outstanding, and the original target remains open.
    """
    description = _subtask_description(context, parameter_ref, source_refs)
    model = solve(description)
    if not verify(description, model):
        raise LocalCheckFailed('parity_param.subtask_verification_failed')
    output = {'status': 'verified_subtask', 'parent_target_ref': context['target_ref'],
              'parent_goal': deepcopy(context['goal']), 'parameter_ref': parameter_ref,
              'parameter_set': model['feasible_set'], 'proof': model,
              'processed_source_refs': list(source_refs),
              'remaining_source_refs': [r['source_ref'] for r in context['entries'] if r['source_ref'] not in source_refs],
              'parent_target_pending': True, 'instantiated_domain': None}
    if isinstance(model['feasible_set'], sp.FiniteSet) and len(model['feasible_set']) == 1:
        from ..parameter_domain import compile_domain, fixed_set
        p = sp.Symbol(description['parameter'], real=True)
        output['instantiated_domain'] = fixed_set(compile_domain(description['domain_ast'], p, parameter_ref),
                                                   p, next(iter(model['feasible_set'])))
    return output


def verify_borrowed_parameter(context, output):
    """Bind a returned certificate to the still-open original parent and facts."""
    try:
        desc = output['proof']['description']
        selected = output['processed_source_refs']
        if desc != _subtask_description(context, output['parameter_ref'], selected):
            return False
        entries = [{k: r[k] for k in ('source_ref', 'expression', 'ast')}
                   for r in context['entries'] if r['source_ref'] in selected]
        if (output['status'] != 'verified_subtask' or output['parent_target_pending'] is not True
                or output['parent_target_ref'] != context['target_ref'] or output['parent_goal'] != context['goal']
                or desc['parent_target_ref'] != context['target_ref'] or desc['parent_goal'] != context['goal']
                or output['parameter_ref'] != desc['parameter_ref'] or entries != desc['given_entries']
                or selected != desc['source_refs'] or len(selected) != len(set(selected)) or len(entries) != len(selected)
                or output['remaining_source_refs'] != [r['source_ref'] for r in context['entries'] if r['source_ref'] not in selected]
                or output['parameter_set'] != output['proof']['feasible_set'] or not verify(desc, output['proof'])):
            return False
        from ..parameter_domain import compile_domain, fixed_set
        parameters = output['parameter_set']
        p = sp.Symbol(desc['parameter'], real=True)
        expected = (fixed_set(compile_domain(desc['domain_ast'], p, desc['parameter_ref']), p, next(iter(parameters)))
                    if isinstance(parameters, sp.FiniteSet) and len(parameters) == 1 else None)
        return output['instantiated_domain'] == expected
    except (ValueError, TypeError, KeyError, IndexError, NotImplementedError, CapabilityGap):
        return False
