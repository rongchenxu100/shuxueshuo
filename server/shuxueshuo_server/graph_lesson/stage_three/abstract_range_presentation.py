"""Step-local input maps for transferring an unknown function's known image."""

from copy import deepcopy

import sympy as sp

from .abstract_domain_presentation import _derivation, _set_latex
from .abstract_function_range import transfer
from .evaluation_presentation import _choice, _lines, _math
from .range_presentation import _card, _image_choices


def phase_view(values):
    desc, data = values['description'], values['description']['transfer']
    fn, variable = desc['function_name'], desc['variable']
    target = desc['target_latex']
    argument = desc['target_argument_latex']
    known = f"{fn}({desc['known_argument_latex']})"
    inputs, domain = _set_latex(data['input_range']), _set_latex(data['domain'])
    # Avoid capturing an outer variable already named t.
    new = 'u' if variable == 't' else 't'
    if values['phase'] == 'abstract_inputs':
        interaction, answer = _image_choices(data['covered'], data['image'])
        return _card('求新变量的范围', f'对于目标函数 ${target}$，令 ${new}={argument}$。${new}$ 的范围是什么？',
                     '目标函数的定义域与换元', _lines([rf'{variable}\in{domain}', rf'{new}={argument}']),
                     '新变量范围', rf'{new}\in{inputs}',
                     _math(rf'{variable}\in{domain}\Longrightarrow {new}={argument}\in{inputs}'),
                     interaction, answer)
    if values['phase'] == 'abstract_coverage':
        interaction, answer = _choice(f'新输入取遍 ${fn}$ 的输入范围，可以沿用已知值域',
                                      [f'新输入只覆盖 ${fn}$ 输入范围的一部分，不能直接沿用已知值域'])
        return _card('判断是否完整覆盖', f'目标函数 ${target}$ 的完整输入 ${argument}$，能否取遍 ${fn}$ 的输入范围？',
                     f'${fn}$ 的输入范围与新输入范围',
                     _lines([rf'D_{{{fn}}}={inputs}', rf'{new}\in{_set_latex(data["covered"])}']),
                     '覆盖关系', rf'\{{{argument}:{variable}\in{domain}\}}=D_{{{fn}}}',
                     _math(rf'\{{{argument}:{variable}\in{domain}\}}={inputs}=D_{{{fn}}}'),
                     interaction, answer)
    if values['phase'] == 'abstract_return':
        interaction, answer = _image_choices(data['image'], data['domain'])
        image = _set_latex(data['image'])
        return _card('得到目标函数的值域', f'新输入已完整覆盖 ${fn}$ 的输入范围。${target}$ 的值域是什么？',
                     '题设已知值域', rf'{known}\in{image}',
                     '目标函数值域', rf'{target}\in{image}',
                     _math(rf'\{{{target}:{variable}\in{domain}\}}={image}'), interaction, answer)
    raise ValueError('abstract_range.unknown_presentation_phase')


def domain_prerequisite(description):
    data = transfer(description)
    variable, target = description['variable'], description['target_latex']
    fn, argument = description['function_name'], description['target_argument_latex']
    inputs = _set_latex(data['input_range'])
    conditions = [rf'D_{{{fn}}}={inputs}', rf'{argument}\in{inputs}']
    recovery = []
    label = f'${fn}$ 的输入范围与目标输入条件'
    if description['known_form'] == 'affine':
        known_variable = description.get('known_variable', variable)
        known_argument = description['known_argument_latex']
        known_domain = _set_latex(data['known_domain'])
        recovery = [rf'{known_variable}\in{known_domain}',
                    rf'{known_argument}\in D_{{{fn}}}={inputs}']
        label = f'由 ${fn}({known_argument})$ 的定义域换算输入范围'
    if description['has_outer_domain']:
        conditions.append(rf'{variable}\in{_set_latex(data["outer_domain"])}')
    domain = rf'{variable}\in{_set_latex(data["domain"])}'
    premises = [recovery[0], r'\Downarrow', recovery[1], *conditions[1:]] if recovery else conditions
    board = _derivation('确定定义域', label, _lines(premises), '目标函数定义域', domain)
    stem = deepcopy(board)
    stem['items'][1]['math'] = None
    interaction, answer = _image_choices(data['domain'], sp.S.Reals)
    return {'id': 'D3-domain', 'title': '确定定义域',
            'question': f'先求目标函数 ${target}$ 的定义域：完整输入 ${argument}$ 必须落在 ${fn}$ 的输入范围内。',
            'summary': f'${domain}$', 'interaction': interaction, 'expected_answer': answer,
            'stem_board': stem, 'completion_board': board,
            'feedback': {'answer': _math(*([r'\Longrightarrow '.join(recovery)] if recovery else []),
                                         *conditions, domain)},
            'submit_label': '在这个范围内选择方法',
            'source_refs': [description['source_ref'], description['known_call_source_ref'], description['known_domain_source_ref'],
                            description['target_call_source_ref']]
                           + ([description['source_ref'] + '/input_domain'] if description['has_outer_domain'] else []),
            'effects': {'nodes': [], 'edges': [], 'calls': [], 'results': [], 'log': '已确定目标函数的定义域。'}}
