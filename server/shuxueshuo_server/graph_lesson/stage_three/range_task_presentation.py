"""Show how a verified image answers the original endpoint or extremum task."""

from copy import deepcopy

import sympy as sp

from .abstract_domain_presentation import _set_latex
from .evaluation_presentation import _choice, _lines, _math
from .math_values import latex
from .range_presentation import _card
from .trajectory import decode_value


def phase_view(values):
    phase, data = values['phase'], values['range']
    if phase == 'task_option_compare':
        label, image, expected = (data[key] for key in ('label', 'image', 'expected'))
        correct, wrong = ('一致', '不一致') if data['matches'] else ('不一致', '一致')
        relation = '=' if data['matches'] else r'\ne'
        interaction, answer = _choice(correct, [wrong])
        return _card(f'核对选项 {label} 的值域',
                     f'选项 {label} 的定义域为 ${_set_latex(data["domain"])}$。算出的完整值域与题给值域是否一致？',
                     '实际值域与题给值域', _lines([rf'V_{{{label}}}={_set_latex(image)}', rf'V={_set_latex(expected)}']),
                     '比较结果', rf'V_{{{label}}}{relation}V',
                     _math(rf'V_{{{label}}}={_set_latex(image)}', rf'V={_set_latex(expected)}'), interaction, answer)
    task = values['description']['range_task']
    if phase == 'task_options_return':
        labels = data['answer']['correct_labels']
        requested = '可能' if task['select_relation'] == 'matches' else '不可能'
        selected = r'\text{' + ('、'.join(labels) or '无') + '}'
        return _card('回答原题', f'题目要求选择“{requested}”的端点组合。根据各项值域的核对结果，返回原题选项。',
                     '选择要求', rf'\text{{定义域}}={task["domain_template"]},\quad V={task["expected_range"]}',
                     '符合要求的选项', selected, _math(selected))
    extrema = data['extrema']
    bindings = [rf'{row["symbol"]}={latex(row["value"])}' for row in extrema if row['attained']]
    if phase == 'task_extrema':
        descriptions = '，'.join(f'${row["symbol"]}$ 为' + ('最大值' if row['kind'] == 'maximum' else '最小值')
                                for row in extrema)
        if not all(row['attained'] for row in extrema):
            missing = '、'.join(row['symbol'] for row in extrema if not row['attained'])
            conclusion = rf'\text{{{missing} 对应的最值不存在}}'
            return _card('核对最值能否取到', descriptions + '。值域边界能取到时才是最值。',
                         '已验证的值域', _set_latex(data['image']), '最值结论', conclusion, _math(conclusion))
        result = _lines(bindings)
        # Distinct alternatives remain mathematical role swaps, not changed endpoints.
        wrong = []
        if len(extrema) == 2 and extrema[0]['value'] != extrema[1]['value']:
            wrong.append('$' + _lines([rf'{row["symbol"]}={latex(other["value"])}'
                                       for row, other in zip(extrema, reversed(extrema), strict=True)]) + '$')
        interaction, expected = _choice(f'${result}$', wrong) if wrong else (None, None)
        return _card('由值域确定最值', descriptions + '。根据已验证的值域，分别是多少？',
                     '值域与最值可达性', _lines([_set_latex(data['image']), r'\text{题设所需最值均能取到}']),
                     '题设最值', result, _math(result), interaction, expected)
    expression = task['expression']
    answer = data['answer']
    if answer['status'] == 'undefined':
        conclusion = r'\text{所求式无定义}'
        return _card('核对所求式', f'题目要求计算 ${expression}$。', '最值条件',
                     _lines(bindings) or r'\text{所需最值不存在}', '结论', conclusion, _math(conclusion))
    value = data['value']
    interaction, expected = _choice(f'${latex(value)}$', [f'${latex(value+1)}$', f'${latex(value-1)}$'])
    return _card('计算原题所求值', f'将已求出的最值代入 ${expression}$，结果是什么？',
                 '最值与所求式', _lines([*bindings, expression]), '所求值', rf'{expression}={latex(value)}',
                 _math(*bindings, rf'{expression}={latex(value)}'), interaction, expected)


def append_finalization(state, answer, evidence):
    from .execution_contracts import read
    from .goals import verify_goal_answer
    from .presentation import make_fragment, record_seed
    from .presentation_templates import render_highlight, render_template, render_title

    updated = deepcopy(state)
    context = updated['trajectory']['constraint_context']
    if updated.get('verification', {}).get('status') != 'verified':
        raise ValueError('presentation.goal_unverified')
    image = decode_value(updated['feasible_set_exact'])
    checked = verify_goal_answer(context['goal'], image, answer)
    if evidence != checked:
        raise ValueError('presentation.goal_evidence_mismatch')
    records = updated.setdefault('finalization', deepcopy(updated['trajectory']['finalization']))
    if any(row.get('capability') == 'finalize_goal' for row in records):
        raise ValueError('presentation.goal_already_finalized')
    index = len(records)
    records.append({'capability': 'finalize_goal', 'answer': deepcopy(answer),
                    'outputs': {'answer': deepcopy(answer), 'evidence': deepcopy(checked)},
                    'operations': ['goal_finalization'], 'postconditions': deepcopy(checked['checks'])})
    updated['trajectory']['finalization'] = deepcopy(records)
    data = {'answer': answer, 'image': image}
    groups = None
    if answer['kind'] == 'derived_answer':
        from .answer_conversion_presentation import display_groups
        groups = display_groups(checked['conversion'], image)
        phases = [f'answer_conversion_{i}' for i in range(len(groups))]
    elif answer['kind'] == 'select_range_domain':
        phases = ['task_options_return']
    else:
        data['extrema'] = [{'symbol': row['symbol'], 'kind': row['kind'],
                           'attained': row['answer']['status'] == 'attained',
                           'value': decode_value(row['answer']['value']['exact']) if row['answer']['status'] == 'attained' else None}
                          for row in checked['extrema']]
        if answer['status'] == 'value':
            data['value'] = decode_value(answer['value']['exact'])
        phases = ['task_extrema', 'task_expression']
    registry = read('presentation-registry')
    spec = registry['templates']['function_range_derivation']
    for number, phase in enumerate(phases):
        bindings = {key: None for key in spec['required_bindings']}
        bindings.update(before=[], after=[], description=context['range_goal'], phase=phase, range=groups[number] if groups is not None else data,
                        variable=sp.Symbol(context['range_goal']['variable'], real=True))
        _, _, explanation = render_template(spec, bindings)
        fragment = make_fragment(updated, unit_id=phase,
                                 method_ref=updated['method']+'#'+registry['boundary_steps'][updated['method']],
                                 template='function_range_derivation', source_refs=[f'/finalization/{index}'],
                                 explanation=explanation, title=render_title(spec, bindings),
                                 highlight=render_highlight(spec, bindings))
        updated['fragments'].append(fragment)
        updated['trajectory']['math_steps'].append({
            'step_id': fragment['step_id'], 'math_step_sha256': fragment['math_step_sha256'],
            'source_refs': fragment['source_refs'],
            'file': f'math-steps/{updated["route_id"]}/{fragment["step_id"]}.json'})
        record_seed(updated, fragment, template='function_range_derivation', values=bindings)
    return updated
