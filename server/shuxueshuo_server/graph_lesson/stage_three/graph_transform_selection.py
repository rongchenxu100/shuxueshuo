"""Pre-connected method choices using the task, before solving it."""


def select_graph(context, contract, primary):
    from .graph_transform_runtime import admitted
    if not admitted(context):
        return {'status': 'no_verified_route', 'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': []},
                'd3': None, 'd4': None, 'diagnostics': [{'code': context.get('graph_goal', {}).get('reason', 'function_graph.unsupported')}]}
    if context['goal']['kind'] != 'select_function_graph':
        from .absolute_graph_runtime import select_absolute
        return select_absolute(context, contract, primary)
    refs = context['graph_goal']['source_refs']
    branch = {'branch': 'transform', 'target': 'method-function-graph-transform', 'route_id': 'function-graph-transform',
              'trigger': 'triggered', 'applicability': 'applicable', 'recommendation': 'preferred',
              'route_plan': 'capability_gap', 'missing_capabilities': ['execution:method-function-graph-transform'],
              'checks': [{'check_id': 'affine_absolute_graph', 'status': 'holds', 'source_refs': refs}]}
    selection = {'status': 'no_verified_route',
            'selection': {'kind': 'method_cards', 'rule': contract['rule'], 'branches': [branch],
                          'recommendation_rule': 'source_graph_task', 'recommendation_checks': []},
            'd3': {'id': 'D3', 'title': '选择解题方法', 'question': '沿着题目线索，选择一种方法。',
                   'query': {'op': 'methods', 'from': primary},
                   'interaction': {'type': 'method_cards', 'layout': 'connections', 'facts': [],
                       'checks': [{'id': 'source_structure', 'question': '题目给了什么？',
                           'options': [{'value': 'absolute', 'label': '绝对值内是一次式', 'note': '如 $|ax+b|+c$，可由基本图像变换得到。'},
                                       {'value': 'quadratic', 'label': '绝对值内是二次式', 'note': '如 $|x^2-2x-3|$，可先找零点，再分段作图。'}],
                           'resolved': '由含绝对值的解析式判断图像。', 'feedback': '可以先看基本图像经过了哪些变换。'}],
                       'method_notes': {}, 'method_choices': [{'value': 'transform', 'label': '图像变换法'}, {'value': 'piecewise', 'label': '分段作图法'}],
                       'connections': [{'cue': 'absolute', 'method': 'transform'}, {'cue': 'absolute', 'method': 'piecewise'},
                                       {'cue': 'quadratic', 'method': 'piecewise'}], 'source_refs': refs},
                   'expected_answer': {'checks': {'source_structure': 'absolute'}},
                   'verdicts': {'transform': {'value': 'fit', 'message': '从基本图像出发，确定点怎样移动，再对照原图选项。'},
                                'piecewise': {'value': 'fit', 'message': '分段作图法也适用；这条路线尚未展开，可用图像变换法继续。'}},
                   'submit_label': '确认选法'},
            'd4': {'id': 'D4', 'title': '按所选方法解题', 'options': [{'branch': 'transform', 'method': branch['target'],
                   'route_id': branch['route_id'], 'recommendation': 'preferred', 'route_plan': 'capability_gap',
                   'message': '从基本图像出发，确定点的对应关系。'}]}, 'diagnostics': []}
    if 'transformations' in context['goal']:
        branch['checks'][0]['check_id'] = 'ordered_quadratic_translations'
        interaction = selection['d3']['interaction']
        interaction['checks'][0]['options'].insert(0, {
            'value': 'translation', 'label': '已给出平移方向和距离', 'note': '按题给顺序，一次完成一个移动。'})
        interaction['checks'][0]['options'] = [o for o in interaction['checks'][0]['options'] if o['value'] != 'absolute']
        interaction['connections'] = [{'cue': 'translation', 'method': 'transform'}, {'cue': 'quadratic', 'method': 'piecewise'}]
        selection['d3']['expected_answer']['checks']['source_structure'] = 'translation'
        selection['d3']['verdicts']['transform']['message'] = '从原图出发，分别平移，再核对关键点和原图选项。'
        selection['d4']['options'][0]['message'] = '按题给的方向与距离，分步移动图像。'
    if 'source_graph' in context['goal']:
        branch['checks'][0]['check_id'] = 'source_schematic_transform'
        card = selection['d3']
        card['interaction']['checks'][0].update(
            options=[{'value': 'source_graph', 'label': '已知原图，函数自变量发生变化', 'note': '例如从 $y=f(x)$ 到 $y=f(2-x)$。'},
                     {'value': 'formula', 'label': '给出绝对值解析式，需要分段画图', 'note': '先判断绝对值里面的正负。'}],
            resolved='根据原图上的点和方向判断变换。', feedback='题目给出了原图，可以先看自变量怎样变化。')
        card['interaction']['connections'] = [{'cue': 'source_graph', 'method': 'transform'}, {'cue': 'formula', 'method': 'piecewise'}]
        card['expected_answer']['checks']['source_structure'] = 'source_graph'
        card['verdicts']['transform']['message'] = '先判断点移到哪里，再判断方向，最后核对原选项。'
        card['verdicts']['piecewise'] = {'value': 'unfit', 'message': '本题没有给出具体解析式，用原图的点和方向判断变换。'}
        selection['d4']['options'][0]['message'] = '根据原图的可见事实判断点的对应关系。'
    return selection
