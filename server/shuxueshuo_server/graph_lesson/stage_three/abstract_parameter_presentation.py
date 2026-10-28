"""Local derivation cards for common-input existence and parameter ranges."""

from copy import deepcopy

import sympy as sp

from .abstract_domain_presentation import _answer_options, _derivation, _set_latex
from .math_values import latex
from .trajectory import decode_value


def _lines(items):
    items = list(dict.fromkeys(items))
    return (r'\begin{gathered}' + r'\\'.join(items) + r'\end{gathered}') if len(items) > 1 else (items[0] if items else r'\mathrm{True}')


def _relations(items):
    active = [item for item in items if item.doit() is not sp.true]
    return _lines([latex(item) for item in active]) if active else r'\text{恒成立}'


def _interval(row, shift=0):
    low, high = row['lower'], row['upper']
    left = '(' if row['left_open'] or low == -sp.oo else '['
    right = ')' if row['right_open'] or high == sp.oo else ']'
    return rf'\left{left}{latex(low + shift)},\,{latex(high + shift)}\right{right}'


def _explorer(result, mode):
    diagram = result.get('overlap_diagram')
    # A two-track diagram cannot represent a third, parameter-only call.
    # Keep the complete conditions on the derivation card in that case.
    if (not diagram or len(diagram.get('intervals', [])) != 2
            or result['overlap_strategy']['constant_guard_conditions']):
        return None
    fields = ('parameter', 'variable', 'parameter_min', 'parameter_max', 'initial', 'critical_values')
    value = {key: deepcopy(diagram[key]) for key in fields}
    if 'critical_exact_values' in diagram:
        value['critical_exact_values'] = deepcopy(diagram['critical_exact_values'])
    interval_fields = ('label', 'call_latex', 'lower', 'upper', 'lower_latex', 'upper_latex',
                       'left_open', 'right_open')
    value['intervals'] = [{key: deepcopy(row[key]) for key in interval_fields if key in row}
                          for row in diagram['intervals']]
    value.update(mode=mode, strategy=result['overlap_strategy']['recommended'])
    return value


def _separation_math(strategy):
    return r'\quad\text{或}\quad '.join(latex(row['condition']) for row in strategy['separation_cases'])


def phase_view(values):
    description = values['description']
    phase = values['phase']
    variable, parameter = description['variable'], description['parameter']
    function = description['function_name']
    input_range = _set_latex(values['input_range'])
    conditions = values['call_conditions']
    ranges = values['call_ranges']
    known_note = ('在题设给定的输入范围内求解。'
                  if description['known_strength'] == 'meaningful_only' else '')
    known = values['input_range']
    if isinstance(known, sp.Interval):
        left = '<' if known.left_open else r'\leq'
        right = '<' if known.right_open else r'\leq'
        condition_math = _lines([f"{latex(known.start)} {left} {latex(row['argument'])} {right} {latex(known.end)}"
                                 for row in conditions])
    else:
        condition_math = _lines([rf"{latex(row['argument'])}\in {input_range}" for row in conditions])
    range_lines = []
    slots = []
    for index, row in enumerate(ranges):
        call = description['calls'][index]
        call_name = f"{function}({call['argument_latex']})"
        if row['parameter_conditions']:
            range_lines.append(_relations(row['parameter_conditions']))
        if row['lower'] == -sp.oo and row['upper'] == sp.oo:
            continue
        range_lines.append(rf'{variable}\in {_interval(row)}')
        slots.append({'label': f'${call_name}$ 允许的 ${variable}$ 范围', 'options': [
            {'value': 'o1', 'label': f'${_interval(row)}$'},
            {'value': 'o2', 'label': f'${_interval(row, 1)}$'},
        ]})
    ranges_math = _lines(range_lines)
    overlap_math = _relations(values['overlap_conditions'])
    result = values['parameter_result']
    strategy = result['overlap_strategy']
    complement = strategy['recommended'] == 'complement'
    range_names = [chr(65 + index) for index in range(len(slots))]
    common_math = (r'\cap '.join(range_names) + r'\ne\varnothing') if range_names else overlap_math
    shared = {'feedback': {'answer': '同一个自变量必须满足所有调用的输入限制。'}}
    if phase == 'conditions':
        view = {
            'title': '分别列出输入条件',
            'question': f'在已知输入范围 ${input_range}$ 内，要保证目标函数有意义，应该怎样约束各个调用？',
            'interaction': {'type': 'choice', 'field': 'input_conditions', 'options': [
                {'value': 'o1', 'label': f'每个调用的完整输入都属于 ${input_range}$'},
                {'value': 'o2', 'label': f'要求各调用的函数值属于 ${input_range}$'},
            ]},
            'expected_answer': {'one_of': ['o1']},
            'domain_explanation': f'分别约束传给 ${function}$ 的输入；所有条件要同时满足。' + known_note,
            'derivation': _derivation('各调用的输入条件', '题设给定的输入范围', input_range,
                                      '需要同时满足', condition_math, note=known_note),
        }
    elif phase == 'ranges':
        interaction = ({'type': 'checklist', 'title': '分别解输入条件', 'slots': slots}
                       if slots else {'type': 'read'})
        view = {
            'title': '求各调用允许的范围',
            'question': f'把 ${parameter}$ 暂看作常数，分别解关于 ${variable}$ 的输入条件。',
            'interaction': interaction,
            'expected_answer': {'terms': ['o1'] * len(slots)} if slots else {},
            'domain_explanation': f'逐个求出允许的 ${variable}$ 范围；不含 ${variable}$ 的条件直接保留为参数限制。',
            'derivation': _derivation('分别求范围', '各调用的输入条件', condition_math,
                                      '各调用允许的范围', ranges_math),
        }
    elif phase == 'overlap':
        explorer = _explorer(result, 'explore')
        guarded = bool(strategy['constant_guard_conditions'])
        view = {
            'title': '观察范围的公共部分',
            'question': f'移动参数，观察数轴。能否找到同一个 ${variable}$，同时落在所有范围里？题目要求下面哪一种情况？'
                        if explorer else ('除了各范围有共同取值，不含自变量的参数限制还需要满足吗？'
                                          if guarded else '要让目标函数有意义，这些输入条件应该怎样满足？'),
            'interaction': {'type': 'choice', 'field': 'common_input', 'options': [
                {'value': 'o1', 'label': '所有输入条件同时成立，包括不含自变量的参数限制'
                 if guarded else '有共同的取值：重叠一段，或有一个所有范围都包含的公共点'
                 if len(slots) >= 2 else '所有输入条件同时成立'},
                {'value': 'o2', 'label': '只要这些范围有共同取值，就可以忽略参数限制'
                 if guarded else '各自有取值就够了，可以没有共同取值'},
            ]},
            'expected_answer': {'one_of': ['o1']},
            'domain_explanation': ('共同取值必须满足每个调用的输入条件；不含自变量的参数限制也必须成立，不能只看区间重叠。'
                                   if guarded else '同一个自变量必须落在所有区间里。重叠一段有公共取值；两个闭端点接触时，这一个点也可以取。'
                                   if len(slots) >= 2 else '所有输入条件同时成立。')
                                  + ('这两个区间的左右位置会随参数变化，接下来先找完全错开的情况，再排除它们。'
                                     if complement else '本题直接列出同时成立的条件，再求参数范围。'),
            'derivation': _derivation('共同输入', '各调用允许的范围', ranges_math,
                                      '至少有一个共同取值' if complement else '需要同时满足的条件',
                                      common_math if complement else overlap_math),
        }
        if explorer:
            view['derivation']['interval_explorer'] = explorer
    elif phase == 'separation':
        cases = strategy['separation_cases']
        options = []
        for index, case in enumerate(cases):
            condition = case['condition']
            opposite = sp.Ge(condition.lhs, condition.rhs, evaluate=False) if condition.rel_op == '<' else sp.Gt(condition.lhs, condition.rhs, evaluate=False)
            left, right = ('A', 'B') if index == 0 else ('B', 'A')
            options.append({'label': f'${left}$ 完全在 ${right}$ 的左边', 'options': [
                {'value': 'o1', 'label': f'${latex(condition)}$'},
                {'value': 'o2', 'label': f'${latex(opposite)}$'},
            ]})
        view = {
            'title': '找出两个区间完全错开的条件',
            'question': '先找没有公共取值的情况。看两幅图，分别比较左边区间的右端点与右边区间的左端点。',
            'interaction': {'type': 'checklist', 'title': '两种分离情况', 'slots': options},
            'expected_answer': {'terms': ['o1'] * len(options)},
            'domain_explanation': '两个区间不相交，只有 A 完全在 B 左边，或 B 完全在 A 左边。'
                                  '若相接的两个端点都包含，接触时仍有公共点，所以分离条件用严格不等式；只要有一个不包含，接触也算交集为空。',
            'derivation': _derivation('先求交集为空', '两个区间完全错开', r'A\cap B=\varnothing',
                                      '两种情况满足其一', _separation_math(strategy)),
        }
        if explorer := _explorer(result, 'separation'):
            view['derivation']['interval_explorer'] = explorer
    elif phase == 'excluded':
        excluded = strategy['empty_overlap_parameters']
        view = {
            'title': '求交集为空时的参数范围',
            'question': f'分别解两种分离条件，再取并集：哪些 ${parameter}$ 会让两个区间没有公共取值？',
            'interaction': {'type': 'choice', 'field': 'excluded_parameter_range',
                            'options': _answer_options(excluded, values['candidate_set'], {})},
            'expected_answer': {'one_of': ['o1']},
            'domain_explanation': '两种分离情况满足任意一种，交集就为空，因此把它们的参数范围取并集。',
            'derivation': _derivation('空交集对应的参数', '两种分离条件', _separation_math(strategy),
                                      '没有公共取值时', _set_latex(excluded)),
        }
    elif phase == 'parameter':
        answer = values['candidate_set']
        view = {
            'title': '取补集，得到参数范围' if complement else '求参数范围',
            'question': f'排除刚才交集为空的参数，剩下哪些 ${parameter}$ 能让两个区间有公共取值？'
                        if complement else f'解上述同时成立的条件，${parameter}$ 的取值范围是？',
            'interaction': {'type': 'choice', 'field': 'parameter_range',
                            'options': _answer_options(answer, values['input_range'], {})},
            'expected_answer': {'one_of': ['o1']},
            'domain_explanation': ('从全体实数中排除使交集为空的参数，取补集得到交集非空的参数。'
                                   if complement else f'解交集非空对应的全部条件，得到 ${parameter}$ 的范围。') + known_note,
            'derivation': _derivation('参数范围', '从全体实数中排除' if complement else '共同输入存在的条件',
                                      rf'\mathbb{{R}}\setminus\left({_set_latex(strategy["empty_overlap_parameters"])}\right)'
                                      if complement else overlap_math,
                                      f'${parameter}$ 的范围', _set_latex(answer)),
        }
    else:
        raise ValueError('abstract_parameter.unknown_phase:' + str(phase))
    return {**shared, **view}


def presentation(values):
    view = phase_view(values)
    board = view['derivation']
    left, right = board['items']
    return {
        'domain_explanation': view['domain_explanation'],
        'derivation_caption': board['caption'],
        'derivation_left_label': left['label'],
        'derivation_left_math': left['math'],
        'derivation_left_note': left.get('note', ''),
        'derivation_right_label': right['label'],
        'derivation_right_math': right['math'],
        'interval_explorer': deepcopy(board.get('interval_explorer')),
    }


def compile_parameter(seeds, interaction_id):
    (seed,) = seeds
    view = phase_view(decode_value(seed['values']))
    board = deepcopy(view['derivation'])
    board['items'][1]['math'] = None
    return {'parts': [{
        'id': interaction_id + '#1', 'title': view['title'], 'question': view['question'],
        'interaction': deepcopy(view['interaction']), 'expected_answer': deepcopy(view['expected_answer']),
        'feedback': deepcopy(view['feedback']), 'submit_label': '确认判断', 'stem_board': board,
    }], 'diagnostics': []}
