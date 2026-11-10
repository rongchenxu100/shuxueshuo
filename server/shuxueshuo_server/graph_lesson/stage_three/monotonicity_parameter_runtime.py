"""FM-T4 R0 execution for monotonicity-condition parameter finding."""
from copy import deepcopy

from ..monotonicity_parameter_math import solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .trajectory import decode_value, encode_value

METHOD = 'method-monotonicity-parameter'
LABEL = '单调性条件求参法'


def admitted(context):
    d = context.get('mono_parameter_goal', {})
    entries = [{k: r[k] for k in ('source_ref', 'expression')} for r in context.get('entries', [])]
    return bool(d.get('structure_supported') and d['source'] == context['goal']
                and d['given_definitions'] == entries)


def analyze(context):
    if not admitted(context):
        raise CapabilityGap('mono_param.unsupported_source')
    d = context['mono_parameter_goal']
    try:
        model = solve(d)
    except (ValueError, NotImplementedError) as exc:
        raise CapabilityGap(str(exc)) from exc
    if not verify(d, model):
        raise LocalCheckFailed('mono_param.certificate_failed')
    layout = (model['structure'] if model.get('structure') in ('piecewise', 'radical')
              else 'split' if d.get('needs_leading_split') else 'axis')
    return result({
        'mono_parameter_result': model,
        'description': deepcopy(d),
        'needs_leading_split': bool(d.get('needs_leading_split')),
        'layout': layout,
    },
                  ['mono_parameter_axis', 'mono_parameter_merge'],
                  [{'kind': 'monotonicity_parameter_certificate', 'passed': True}])


def confirm(description, mono_parameter_result):
    if not verify(description, mono_parameter_result):
        raise LocalCheckFailed('mono_param.statement_invalid')
    return result({'mono_parameter_result': mono_parameter_result}, ['mono_parameter_merge'])


def verify_frozen(candidate, target_ref, context, encoded_result):
    from .context import build_context
    current = build_context(candidate, target_ref)
    valid = (current == context and admitted(current)
             and verify(current['mono_parameter_goal'], decode_value(encoded_result)))
    return {'status': 'verified' if valid else 'math_failed',
            'checks': [{'kind': 'original_mono_parameter_statement', 'passed': valid}],
            'processing': [{'source_ref': row['source_ref'], 'kind': 'original_mono_parameter_condition',
                            'status': 'processed'} for row in current['entries']] if valid else [],
            'diagnostics': [] if valid else [{'code': 'mono_param.independent_verification_failed'}]}


def finish(state, context, previous):
    from .goals import _exact_math, finalize_goal_with_evidence
    m = decode_value(state['mono_parameter_result_exact'])
    if not verify(context['mono_parameter_goal'], m):
        raise LocalCheckFailed('mono_param.finalization_failed')
    final, _evidence = finalize_goal_with_evidence({'kind': 'find_range'}, m['feasible_set'])
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != final for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': final,
            'mono_parameter_result_exact': encode_value(m),
            'feasible_set': _exact_math(m['feasible_set']), 'consistency': consistency}


def select(context, contract, primary):
    if not admitted(context):
        return {'status': 'no_applicable_method',
                'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [],
                              'recommendation_rule': None, 'recommendation_checks': []},
                'd3': None, 'd4': None,
                'diagnostics': [{'code': context.get('mono_parameter_goal', {}).get('reason', 'mono_param.unsupported')}]}
    desc = context['mono_parameter_goal']
    note = '先看参数怎样改变斜率、开口或对称轴，再保证整个指定区间都符合增减要求。'
    cues = [
        {'value': 'parameter', 'label': '已知指定区间上的增减性，求函数参数',
         'note': r'如 $f(x)=x^{2}-mx+5$ 在 $[1,2]$ 上递增，求 $m$。'},
        {'value': 'intervals', 'label': '求函数本身的单调区间',
         'note': '原目标是写出增减区间，不是求使某性质成立的参数。'},
    ]
    labels = {'parameter': LABEL, 'intervals': '基本函数与复合法'}
    branch = {'branch': 'parameter', 'target': METHOD, 'route_id': 'monotonicity-parameter',
              'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': 'preferred',
              'route_plan': 'capability_gap', 'missing_capabilities': ['execution:' + METHOD],
              'checks': [{'check_id': 'original_mono_parameter_goal', 'status': 'holds',
                          'source_refs': desc['source_refs']}]}
    return {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [branch],
                          'recommendation_rule': 'mono_parameter_goal', 'recommendation_checks': []},
            'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '结合本题的目标，选择解题方法。',
                   'query': {'op': 'methods', 'from': primary},
                   'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                                   'method_notes': {
                                       'intervals': '本题不是求单调区间，而是求使给定单调性成立的参数。'},
                                   'checks': [{'id': 'goal', 'question': '这道题需要完成什么？',
                                               'options': cues, 'resolved': LABEL, 'feedback': note}],
                                   'method_choices': [{'value': key, 'label': labels[key]} for key in labels],
                                   'connections': [{'cue': key, 'method': key} for key in labels],
                                   'source_refs': desc['source_refs']},
                   'expected_answer': {'checks': {'goal': 'parameter'}},
                   'verdicts': {
                       'parameter': {'value': 'fit', 'message': note},
                       'intervals': {'value': 'unfit',
                                     'message': '本题要求参数使指定区间上的单调性成立，不是求单调区间。'},
                   },
                   'submit_label': '确认选法'},
            'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [
                {'branch': 'parameter', 'method': METHOD, 'route_id': 'monotonicity-parameter',
                 'recommendation': 'preferred', 'route_plan': 'capability_gap', 'message': LABEL}]},
            'diagnostics': []}
