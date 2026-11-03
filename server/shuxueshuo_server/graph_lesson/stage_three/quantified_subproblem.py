"""Shared entry to a quantified subproblem, independent of its host topic."""

from copy import deepcopy

from .domain_borrow import compile_borrow_plane
from .math_values import latex
from .trajectory import decode_value


def presentation(values):
    x, p = latex(values['x']), latex(values['parameter'])
    domain, relation = latex(values['domain']), latex(values['universal_statement'])
    statement = rf'\forall {x}\in{domain},\quad {relation}'
    return {'subproblem_statement': statement,
            'subproblem_title': '判断转化后的问题' if values['phase'] == 'recognize' else '选择恒成立问题的解题方法',
            'subproblem_explanation': rf'求使 ${statement}$ 成立的 ${p}$。',
            'subproblem_caption': '转化后的不等式'}


def compile_step(seeds, interaction_id):
    values = decode_value(seeds[0]['values'])
    if values['phase'] == 'select':
        result = compile_borrow_plane(values, interaction_id)
        result['parts'][0]['title'] = '选择恒成立问题的解题方法'
        return result
    view = presentation(values)
    x, p = latex(values['x']), latex(values['parameter'])
    domain = latex(values['domain'].as_relational(values['x']))
    options = [
        {'value': 'universal', 'label': f'求使不等式对所有 ${domain}$ 都成立的 ${p}$（一元二次不等式恒成立问题）'},
        {'value': 'existential', 'label': f'求使不等式至少对一个满足 ${domain}$ 的 ${x}$ 成立的 ${p}$（一元二次不等式存在问题）'},
    ]
    board = {'layout': 'derivation', 'caption': view['subproblem_caption'], 'items': [
        {'label': '刚得到的条件', 'math': view['subproblem_statement']},
        {'label': '现在要解决的问题', 'math': None},
    ], 'connector': '⇒'}
    completed = deepcopy(board)
    completed['items'][1]['math'] = r'\text{一元二次不等式恒成立问题}'
    context = values.get('subproblem_context', '')
    question = '注意“对所有”这一条件：现在要解决的是哪一种问题？'
    return {'parts': [{
        'id': interaction_id+'#1', 'title': view['subproblem_title'],
        'question': context + '\n\n' + question if context else question,
        **({'source_context': context} if context else {}),
        'interaction': {'type': 'choice', 'field': 'answer', 'options': options},
        'expected_answer': {'one_of': ['universal']},
        'feedback': {'answer': f'条件要求每个满足 ${domain}$ 的 ${x}$ 都成立，因此求的是恒成立时的参数范围。'},
        'submit_label': '确认问题类型', 'stem_board': board, 'completion_board': completed,
        'effects': {'nodes': ['type-quantified-quadratic'], 'log': '识别恒成立子问题。'},
    }], 'diagnostics': []}
