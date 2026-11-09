"""FM-T3 execution for known-monotonicity order inequalities.

R1 nests piecewise monotonicity when the authored basis is a proved certificate
backed by an explicit piecewise definition.
"""
from copy import deepcopy

import sympy as sp

from ...problem_understanding.notation_parser import NotationError, definition
from ..function_monotonicity import describe as describe_mono
from ..function_monotonicity import verify as verify_mono
from ..monotonicity_inequality_math import basis_from_proof, convert_relation, solve, verify
from ..piecewise_evaluation import is_piecewise
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .trajectory import decode_value, encode_value

METHOD = 'method-monotonicity-inequality'
LABEL = '单调性解不等式法'


def admitted(context):
    d = context.get('mono_inequality_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression')} for r in context.get('entries', [])]
    return bool(d.get('structure_supported') and d['source'] == context['goal']
                and d['given_definitions'] == entries)


def analyze(context):
    if not admitted(context):
        raise CapabilityGap('mono_inequality.unsupported_source')
    d = context['mono_inequality_goal']
    try:
        model = solve(d)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    if not verify(d, model):
        raise LocalCheckFailed('mono_inequality.certificate_failed')
    return result({
        'mono_inequality_result': model,
        'description': deepcopy(d),
        'inputs_interactive': model['usable_set'] != sp.S.Reals,
    },
                  ['mono_inequality_inputs', 'mono_inequality_order'],
                  [{'kind': 'known_monotonicity_order_certificate', 'passed': True}])


def _piecewise_definition(context, function):
    for row in context.get('entries', []):
        if '/definitions/' not in row.get('source_ref', ''):
            continue
        try:
            ast = definition(row['expression'])
        except (NotationError, ValueError, TypeError, IndexError):
            continue
        if ast[0] == 'function_definition' and ast[1] == function and is_piecewise(ast[3]):
            return row, ast
    return None, None


def prepare_basis(context, description):
    """Open a piecewise prove child only when M5's mono basis must be proved."""
    if not admitted(context) or description != context.get('mono_inequality_goal'):
        raise CapabilityGap('mono_inequality.unsupported_source')
    needs = description.get('mono_basis') == 'proved_monotonicity'
    child_context = None
    if needs:
        row, ast = _piecewise_definition(context, description['function'])
        if row is None:
            raise CapabilityGap('mono_inequality.piecewise_definition_required')
        body = row['expression'].split('=', 1)[1].strip()
        goal = {
            'kind': 'prove_monotonicity_on_interval',
            'expression': body,
            'variable': ast[2],
            'direction': description['direction'],
            'input_domain': description['mono_domain'],
            'function': description['function'],
        }
        child = describe_mono(goal, description['target_ref'])
        if not child.get('structure_supported') or child.get('family') != 'explicit_piecewise':
            raise CapabilityGap(child.get('reason') or 'mono_inequality.piecewise_proof_unavailable')
        child_context = {
            'goal': goal, 'target_ref': description['target_ref'], 'entries': [],
            'monotonicity_goal': child,
            'teaching_density': 'nested_inequality',
        }
    return result({'needs_mono_proof': needs, 'child_context': child_context,
                   'description': deepcopy(description)},
                  ['mono_inequality_inputs'],
                  [{'kind': 'monotonicity_basis_plan', 'passed': True,
                    'needs_mono_proof': needs}])


def confirm_basis(context, description, mono_inequality_result, monotonicity_proof):
    plan = prepare_basis(context, description)['outputs']
    if not plan['needs_mono_proof'] or plan['child_context'] is None:
        raise LocalCheckFailed('mono_inequality.basis_not_required')
    child = plan['child_context']['monotonicity_goal']
    if not verify_mono(child, monotonicity_proof):
        raise LocalCheckFailed('mono_inequality.basis_proof_invalid')
    try:
        basis = basis_from_proof(monotonicity_proof)
    except ValueError as exc:
        raise LocalCheckFailed(str(exc)) from exc
    if (basis['function'] != description['function']
            or basis['direction'] != description['direction']
            or basis['domain'] != description['mono_domain']
            or basis['strict'] is not True):
        raise LocalCheckFailed('mono_inequality.basis_mismatch')
    if not verify(description, mono_inequality_result):
        raise LocalCheckFailed('mono_inequality.basis_order_invalid')
    return result({'monotonicity_basis': basis},
                  ['mono_inequality_inputs'],
                  [{'kind': 'proved_monotonicity_basis', 'passed': True,
                    'direction': basis['direction'], 'domain': basis['domain']}])


def confirm_order(description, mono_inequality_result):
    expected = convert_relation(description['direction'], description['relation_op'])
    if mono_inequality_result.get('converted_op') != expected:
        raise LocalCheckFailed('mono_inequality.order_mismatch')
    if not verify(description, mono_inequality_result):
        raise LocalCheckFailed('mono_inequality.order_invalid')
    return result({'mono_inequality_result': mono_inequality_result}, ['mono_inequality_order'],
                  [{'kind': 'monotonicity_order_conversion', 'passed': True,
                    'direction': description['direction'], 'converted_op': expected}])


def confirm(description, mono_inequality_result):
    if not verify(description, mono_inequality_result):
        raise LocalCheckFailed('mono_inequality.statement_invalid')
    return result({'mono_inequality_result': mono_inequality_result}, ['mono_inequality_inputs'])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = (current == context and admitted(current)
             and verify(current['mono_inequality_goal'], decode_value(encoded_result)))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_mono_inequality_statement', 'passed': valid}],
            'processing': [{'source_ref': row['source_ref'], 'kind': 'original_mono_inequality_condition',
                            'status': 'processed'} for row in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'mono_inequality.independent_verification_failed'}]}


def finish(state, context, previous):
    from .goals import _exact_math, finalize_goal_with_evidence
    m = decode_value(state['mono_inequality_result_exact'])
    if not verify(context['mono_inequality_goal'], m):
        raise LocalCheckFailed('mono_inequality.finalization_failed')
    final, _evidence = finalize_goal_with_evidence({'kind': 'find_range'}, m['feasible_set'])
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != final for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': final,
            'mono_inequality_result_exact': encode_value(m),
            'feasible_set': _exact_math(m['feasible_set']), 'consistency': consistency}


def select(context, contract, primary):
    if not admitted(context):
        return {'status': 'no_applicable_method',
                'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [],
                              'recommendation_rule': None, 'recommendation_checks': []},
                'd3': None, 'd4': None,
                'diagnostics': [{'code': context.get('mono_inequality_goal', {}).get('reason', 'mono_inequality.unsupported')}]}
    desc = context['mono_inequality_goal']
    proved = desc.get('mono_basis') == 'proved_monotonicity'
    note = ('先证明分段函数在比较区间上整体严格单调，再检查两个输入并转化比较。'
            if proved else '先检查两个输入，再利用递增或递减比较它们的大小。')
    cues = [
        {'value': 'order', 'label': '同一个函数的两个函数值比大小',
         'note': (r'如分段给出的 $f$，先证整体严格递增，再比较 $f(u)$ 与 $f(v)$。'
                  if proved else r'如 $f(2x)<f(x+1)$。先检查两个输入，再利用递增或递减比较它们的大小。')},
        {'value': 'piecewise', 'label': '函数分段给出，需要分别代入比较',
         'note': '先看两个输入各落在哪一段，再代入对应式子；有常值段时，不能直接去掉 $f$。'},
    ]
    labels = {'order': LABEL, 'piecewise': '分段解不等式法'}
    piecewise_note = ('本题可先证明整体严格单调，再转化比较；不必一开始就按分支分别代入。'
                      if proved else '本题未给出分段定义，优先利用已知单调性。')
    piecewise_verdict = ('本题虽有分段定义，但整体严格单调成立时应先转化比较，而不是直接分支代入。'
                         if proved else '本题没有分段表达式，不能按分支分别代入。')
    branch = {'branch': 'order', 'target': METHOD, 'route_id': 'monotonicity-inequality',
              'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': 'preferred',
              'route_plan': 'capability_gap', 'missing_capabilities': ['execution:' + METHOD],
              'checks': [{'check_id': 'original_mono_inequality_goal', 'status': 'holds',
                          'source_refs': desc['source_refs']}]}
    return {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [branch],
                          'recommendation_rule': 'mono_inequality_goal', 'recommendation_checks': []},
            'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '结合本题的目标，选择解题方法。',
                   'query': {'op': 'methods', 'from': primary},
                   'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                                   'method_notes': {'piecewise': piecewise_note},
                                   'checks': [{'id': 'goal', 'question': '这道题需要完成什么？',
                                               'options': cues, 'resolved': LABEL, 'feedback': note}],
                                   'method_choices': [{'value': key, 'label': labels[key]} for key in labels],
                                   'connections': [{'cue': key, 'method': key} for key in labels],
                                   'source_refs': desc['source_refs']},
                   'expected_answer': {'checks': {'goal': 'order'}},
                   'verdicts': {
                       'order': {'value': 'fit', 'message': note},
                       'piecewise': {'value': 'unfit', 'message': piecewise_verdict},
                   },
                   'submit_label': '确认选法'},
            'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [
                {'branch': 'order', 'method': METHOD, 'route_id': 'monotonicity-inequality',
                 'recommendation': 'preferred', 'route_plan': 'capability_gap', 'message': LABEL}]},
            'diagnostics': []}
