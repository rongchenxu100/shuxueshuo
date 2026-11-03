"""Native execution, method selection and finalization for G2 graph tasks."""
from copy import deepcopy

from ..absolute_graph import KINDS, solve, verify
from .capabilities import CapabilityGap, LocalCheckFailed, result
from .math_values import latex
from .trajectory import encode_value


def construct(context, *, inequality=False):
    from .graph_transform_runtime import admitted
    kind = 'solve_graph_inequality' if inequality else 'draw_function_graph'
    desc = context.get('graph_goal', {})
    if context['goal']['kind'] != kind or not admitted(context):
        raise CapabilityGap('absolute_graph.input_class_unavailable')
    model = solve(desc)
    if not verify(desc, model):
        raise LocalCheckFailed('absolute_graph.model_verification_failed')
    return result({'description': deepcopy(desc), 'graph_result': model}, ['absolute_sign_split'],
                  [{'kind': 'piecewise_coverage_identities_and_boundaries', 'passed': True}])


def formula(model):
    x = latex(model['variable'])
    rows = [rf'{latex(p["expression"])},& {x}\in {latex(p["domain"])}' for p in model['pieces']]
    return rf'f({x})=\begin{{cases}}'+r'\\'.join(rows)+r'\end{cases}'


def finish_absolute(state, context, previous, model):
    answer = {'kind': model['kind'], 'status': 'complete',
              'latex': formula(model) if model['kind'] == KINDS[0] else latex(model['solution'])}
    consistency = 'conflict' if any(r['status'] == 'verified' and r.get('answer') != answer for r in previous) else 'consistent'
    return {'state': deepcopy(state), 'answer': answer, 'graph_result_exact': encode_value(model), 'consistency': consistency}


def select_absolute(context, contract, primary):
    inequality = context['goal']['kind'] == KINDS[1]
    branch_id = 'inequality' if inequality else 'piecewise'
    method = 'method-piecewise-graph-inequality' if inequality else 'method-absolute-piecewise-graph'
    label = '分段图像解不等式法' if inequality else '分段作图法'
    refs = context['graph_goal']['source_refs']
    branch = {'branch': branch_id, 'target': method, 'route_id': method.removeprefix('method-'),
              'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': 'preferred',
              'route_plan': 'capability_gap', 'missing_capabilities': ['execution:'+method],
              'checks': [{'check_id': 'absolute_polynomial_graph', 'status': 'holds', 'source_refs': refs}]}
    return {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [branch],
                          'recommendation_rule': 'source_graph_task', 'recommendation_checks': []},
            'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '沿着题目线索，选择一种方法。',
                   'query': {'op': 'methods', 'from': primary},
                   'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                       'checks': [{'id': 'source_structure', 'question': '这一问要求什么？',
                           'options': [{'value': 'piecewise', 'label': '画出含绝对值函数的图像', 'note': '按绝对值内的正负分段。'},
                                       {'value': 'inequality', 'label': '比较函数图像与水平线', 'note': '找交点、选区间，再判断端点。'}],
                           'resolved': label, 'feedback': '先看本问是作图，还是求满足不等式的横坐标。'}],
                       'method_notes': {}, 'method_choices': [{'value': 'piecewise', 'label': '分段作图法'},
                                                              {'value': 'inequality', 'label': '分段图像解不等式法'}],
                       'connections': [{'cue': v, 'method': v} for v in ('piecewise', 'inequality')], 'source_refs': refs},
                   'expected_answer': {'checks': {'source_structure': branch_id}},
                   'verdicts': {v: {'value': 'fit' if v == branch_id else 'unfit',
                                   'message': ('按本问目标展开各步。' if v == branch_id else '本问的目标与这条方法对应的任务不同。')}
                                for v in ('piecewise', 'inequality')}, 'submit_label': '确认选法'},
            'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [{'branch': branch_id, 'method': method,
                   'route_id': branch['route_id'], 'recommendation': 'preferred', 'route_plan': 'capability_gap', 'message': label}]},
            'diagnostics': []}
