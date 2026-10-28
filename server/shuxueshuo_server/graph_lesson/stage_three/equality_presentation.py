"""M8 teaching projections from independently checked pair certificates."""

from copy import deepcopy

from .math_values import latex
from .trajectory import decode_value


def _formula(descriptor):
    return descriptor.get('expression_latex') or descriptor.get('expression') or descriptor['function_name']


def pair_text(option):
    return '；'.join(f"${side['function_name']}({side['variable']})={_formula(side)}$"
                    for side in (option['left'], option['right']))


def reason_text(comparison):
    if comparison['reason'] == 'domains_differ':
        point = latex(comparison['counterexample']['point'])
        return f'定义域不同。例如输入 ${point}$ 只属于其中一个函数的定义域；化简不能补回原式不允许的输入。'
    if comparison['reason'] == 'outputs_differ':
        witness = comparison['counterexample']
        return (f"输入 ${latex(witness['point'])}$ 时，两个输出分别为 "
                f"${latex(witness['left_value'])}$、${latex(witness['right_value'])}$，因此对应关系不同。")
    return '定义域相同，并且对这个定义域内的每一个输入，两式的输出都相同。自变量使用什么字母不影响对应关系。'


# Teaching surface: one token for the full real line. SymPy may latex Reals as
# \mathbb{R} and Interval(-oo, oo) as (-\infty, \infty); both must grade the same.
_REAL_LINE_LATEX = frozenset({
    r'\mathbb{R}',
    r'\left(-\infty, \infty\right)',
    r'(-\infty, \infty)',
})


def _domain_latex(domain):
    text = latex(domain)
    return r'\mathbb{R}' if text in _REAL_LINE_LATEX else text


def _domain_pair_text(comparison):
    return (f"两个定义域分别为 ${_domain_latex(comparison['left']['domain'])}$、"
            f"${_domain_latex(comparison['right']['domain'])}$")


def _correspondence_stem(option, comparison):
    if comparison['relation'] == 'different':
        return reason_text(comparison)
    cells = comparison['proof']['cells']
    left_variable, right_variable = (option[side]['variable'] for side in ('left', 'right'))
    introduction = ('用 $u$ 表示共同定义域内的同一个输入。' if left_variable == right_variable else
                    f'将两边的自变量 ${left_variable}$、${right_variable}$ 统一记为 $u$，比较同一个输入对应的函数值。')
    parts = [f"当 $u\\in {_domain_latex(cell['domain'])}$ 时，两式都等于 ${latex(cell['left_polynomial'])}$"
             for cell in cells]
    return introduction + '；'.join(parts) + '。这些范围覆盖整个共同定义域。'


_DOMAIN_DISTRACTORS = (
    r'\mathbb{R}',
    r'\left[0, \infty\right)',
    r'\left(0, \infty\right)',
    r'\left(-\infty, 0\right]',
    r'\varnothing',
)


def _domain_slot(correct):
    labels = []
    for item in (correct, *_DOMAIN_DISTRACTORS):
        if item not in labels:
            labels.append(item)
    options = [{'value': f'o{index}', 'label': f'${label}$'} for index, label in enumerate(labels)]
    answer = next(option['value'] for option, label in zip(options, labels) if label == correct)
    return options, answer


def view(values):
    option, phase = values['option'], values['phase']
    comparison = values.get('comparison')
    left, right = option['left'], option['right']
    left_name = f"{left['function_name']}({left['variable']})"
    right_name = f"{right['function_name']}({right['variable']})"
    prepared = {
        'option_label': option['label'],
        'left_name': left_name,
        'right_name': right_name,
        'left_math': f"{left_name}={_formula(left)}",
        'right_math': f"{right_name}={_formula(right)}",
        'left_domain': '',
        'right_domain': '',
        'domain_connector': '',
        'correspondence_connector': '',
        'left_value_math': '',
        'right_value_math': '',
        'correspondence_caption': '对应关系',
        'relation_connector': '',
        'verdict_result': '',
        'domain_relation_result': '',
    }
    if phase == 'entry':
        text = pair_text(option)
    elif phase == 'borrow':
        text = '先用列条件求交集法确定有输入限制的函数的定义域，再回到本项比较。'
    elif phase == 'domains':
        prepared['left_domain'] = _domain_latex(comparison['left']['domain'])
        prepared['right_domain'] = _domain_latex(comparison['right']['domain'])
        same = comparison['left']['domain'] == comparison['right']['domain']
        prepared['domain_connector'] = '=' if same else '≠'
        prepared['domain_relation_result'] = '定义域相同' if same else '定义域不同'
        text = _domain_pair_text(comparison)
    elif phase == 'correspondence':
        prepared['left_domain'] = _domain_latex(comparison['left']['domain'])
        prepared['right_domain'] = _domain_latex(comparison['right']['domain'])
        prepared['domain_connector'] = '='
        if comparison['reason'] == 'outputs_differ':
            # Counterexample board: name the shared input, show the two outputs.
            witness = comparison['counterexample']
            point = latex(witness['point'])
            prepared['correspondence_caption'] = f'输入 {point} 时的输出'
            prepared['left_name'] = f"{left['function_name']}({point})"
            prepared['right_name'] = f"{right['function_name']}({point})"
            prepared['left_value_math'] = latex(witness['left_value'])
            prepared['right_value_math'] = latex(witness['right_value'])
            prepared['correspondence_connector'] = '≠'
        else:
            # Equal board: show the two original rules, not a cryptic proof piece.
            prepared['correspondence_caption'] = '对应关系等价'
            prepared['left_value_math'] = _formula(left)
            prepared['right_value_math'] = _formula(right)
            prepared['correspondence_connector'] = '='
        text = _correspondence_stem(option, comparison)
    else:
        text = '结合本项已经完成的定义域与对应关系比较，判断两个函数是否相同。'
        if comparison is not None:
            prepared['relation_connector'] = '=' if comparison['relation'] == 'equal' else '≠'
            prepared['verdict_result'] = (
                '本项结论：相同' if comparison['relation'] == 'equal' else '本项结论：不同')
    return {'equality_explanation': text, **prepared}


def _base_part(interaction_id, number, seed):
    return {'id': f'{interaction_id}#{number}', 'title': f"选项 {seed['option_context']['label']}",
            'option_context': deepcopy(seed['option_context']), 'submit_label': '确认判断'}


def _domains_checklist(part, option, comparison):
    left = _domain_latex(comparison['left']['domain'])
    right = _domain_latex(comparison['right']['domain'])
    left_options, left_answer = _domain_slot(left)
    right_options, right_answer = _domain_slot(right)
    left_name = f"{option['left']['function_name']}({option['left']['variable']})"
    right_name = f"{option['right']['function_name']}({option['right']['variable']})"
    part.update(
        title='① 两边的定义域',
        question=f"{pair_text(option)}。分别选出两边的定义域。",
        interaction={'type': 'checklist', 'title': '两边的定义域', 'slots': [
            {'label': left_name, 'options': left_options},
            {'label': right_name, 'options': right_options},
        ]},
        expected_answer={'terms': [left_answer, right_answer]},
        feedback={'answer': reason_text(comparison) if comparison['reason'] == 'domains_differ'
                  else '比较的是全部允许输入的集合，不能只比较化简后的式子。'},
        submit_label='确认定义域')
    return part


def _correspondence_part(part, option, comparison, values):
    equivalent = comparison['relation'] == 'equal'
    part.update(
        title='② 对应关系',
        question='两边定义域相同。对应关系是否等价？',
        interaction={'type': 'choice', 'field': 'correspondence', 'options': [
            {'value': 'equal', 'label': '等价'}, {'value': 'different', 'label': '不等价'}]},
        expected_answer={'one_of': ['equal' if equivalent else 'different']},
        # Interaction seeds omit proof cells; prefer the prepared stem.
        feedback={'answer': values.get('equality_explanation') or _correspondence_stem(option, comparison)},
        submit_label='确认对应关系')
    return part


def _verdict_part(part, option, comparison, *, same_domain):
    stem = ('结合已经比较的定义域与对应关系' if same_domain else '结合已经比较的定义域')
    part.update(title=f"选项 {option['label']}",
                question=f"{pair_text(option)}。{stem}，本项两个函数是否相同？",
                interaction={'type': 'choice', 'field': 'function_relation', 'options': [
                    {'value': 'equal', 'label': '相同'}, {'value': 'different', 'label': '不同'}]},
                expected_answer={'one_of': [comparison['relation']]},
                feedback={'answer': reason_text(comparison)}, submit_label='确认本项结论')
    return part


def compile_equality(seeds, interaction_id):
    if len(seeds) == 2:
        domains_seed, correspondence_seed = seeds
        domains_values = decode_value(domains_seed['values'])
        correspondence_values = decode_value(correspondence_seed['values'])
        option, comparison = domains_values['option'], domains_values['comparison']
        assert correspondence_values['phase'] == 'correspondence'
        assert domains_values['phase'] == 'domains'
        domains = _domains_checklist(_base_part(interaction_id, 1, domains_seed), option, comparison)
        correspondence = _correspondence_part(
            _base_part(interaction_id, 2, correspondence_seed), option, comparison, correspondence_values)
        return {'parts': [domains, correspondence], 'diagnostics': []}

    (seed,) = seeds
    values = decode_value(seed['values'])
    option, phase = values['option'], values['phase']
    comparison = values.get('comparison')
    part = _base_part(interaction_id, 1, seed)
    if phase in ('entry', 'borrow'):
        part.update(question=view(values)['equality_explanation'], interaction={'type': 'read'},
                    expected_answer={}, feedback={'answer': ''}, submit_label='继续本项')
    elif phase == 'domains':
        _domains_checklist(part, option, comparison)
    elif phase == 'correspondence':
        _correspondence_part(part, option, comparison, values)
    elif phase == 'verdict':
        same = comparison['left']['domain'] == comparison['right']['domain']
        _verdict_part(part, option, comparison, same_domain=same)
    else:
        raise ValueError('function_equality.unknown_teaching_phase')
    return {'parts': [part], 'diagnostics': []}
