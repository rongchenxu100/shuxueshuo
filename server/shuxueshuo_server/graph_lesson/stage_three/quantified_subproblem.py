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


def _independent_select(values, interaction_id):
    """Param-free piece: no separation / interval-extremum plane; verify the inequality."""
    x, p = latex(values['x']), latex(values['parameter'])
    domain, relation = latex(values['domain']), latex(values['universal_statement'])
    question = (
        rf'当前子问题为 $\forall {x}\in {domain},\ {relation}$。'
        f'式子中不含参数 ${p}$，应怎样处理这一段？'
    )
    options = [
        {'value': 'verify',
         'label': rf'本段不含 ${p}$，直接验证不等式是否在定义域上恒成立；成立则对 ${p}$ 无额外限制'},
        {'value': 'separate', 'label': '仍按分离参数求参'},
        {'value': 'interval', 'label': '仍按区间最值求参'},
        {'value': 'skip', 'label': '本段可以跳过，不必检查'},
    ]
    return {'parts': [{
        'id': interaction_id + '#1', 'title': '选择恒成立问题的解题方法',
        'question': question, 'submit_label': '确认处理方式',
        'interaction': {'type': 'choice', 'field': 'answer', 'options': options},
        'expected_answer': {'one_of': ['verify']},
        'feedback': {
            'answer': rf'不含 ${p}$ 时不能再分离或求参；验证恒成立后，该段贡献 $\mathbb{{R}}$ 或空集。',
        },
        'effects': {'log': '本段不含参数，改为直接验证恒成立。'},
    }], 'diagnostics': [{'kind': 'checked_independent_piece_select', 'passed': True}]}


def compile_step(seeds, interaction_id):
    values = decode_value(seeds[0]['values'])
    if values['phase'] == 'select':
        # Param-free pieces cannot place separation / interval-extremum for a.
        if values['parameter'] not in values['universal_statement'].free_symbols:
            return _independent_select(values, interaction_id)
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
