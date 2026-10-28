"""Teaching projection for M2 input-domain correspondence."""

from copy import deepcopy

import sympy as sp

from .capabilities.cases import exact_set_equal
from .math_values import latex
from .trajectory import decode_value

_REAL_LINE = frozenset({
    r'\mathbb{R}',
    r'\left(-\infty, \infty\right)',
    r'(-\infty, \infty)',
})


def _set_latex(value):
    if value is None:
        return ''
    if isinstance(value, dict) and 'latex' in value:
        text = value['latex']
    else:
        text = latex(value)
    return r'\mathbb{R}' if text in _REAL_LINE else text


def _set_value(values, field, board_field):
    value = values.get(field)
    if isinstance(value, sp.Set):
        return value
    value = values['board'][board_field]
    if isinstance(value, dict) and 'exact' in value:
        value = decode_value(value['exact'])
    if not isinstance(value, sp.Set):
        raise TypeError('abstract_domain.presentation_set_required:' + field)
    return value


def _answer_options(answer, known, values):
    # A reflection or identity may leave the known domain unchanged. Every
    # displayed alternative must denote a provably different set.
    choices = [answer]
    candidates = [known, values.get('preimage'), values.get('outer_domain'),
                  sp.S.Reals, sp.S.EmptySet, sp.FiniteSet(0), sp.FiniteSet(1)]
    for candidate in candidates:
        if not isinstance(candidate, sp.Set):
            continue
        if any(exact_set_equal(candidate, previous) for previous in choices):
            continue
        choices.append(candidate)
        if len(choices) == 3:
            break
    return [{'value': f'o{index}', 'label': f'${_set_latex(value)}$'}
            for index, value in enumerate(choices, 1)]


def _identity_input(values, variable, complete):
    argument = values.get('complete_input')
    return argument == sp.Symbol(variable, real=True) or complete == variable


def _derivation(caption, left_label, left_math, right_label, right_math, *, note=''):
    left = {'label': left_label, 'math': left_math}
    if note:
        left['note'] = note
    return {'layout': 'derivation', 'caption': caption,
            'items': [left, {'label': right_label, 'math': right_math}], 'connector': '⇒'}


def _phase_view(values):
    description = values['description']
    phase = values['phase']
    function_name = description['function_name']
    variable = description['variable']
    known_variable = description.get('known_variable', variable)
    complete = description['target_argument_latex']
    known_set = _set_value(values, 'input_range', 'lower_set')
    answer_set = _set_value(values, 'candidate_set', 'upper_set')
    known, answer = _set_latex(known_set), _set_latex(answer_set)
    known_argument = description['known_argument_latex']
    known_call = f'{function_name}({known_argument})'
    target = f'{function_name}({complete})'
    mixed = description.get('target_form', 'plain') != 'plain'
    full_target = description.get('target_latex', target)
    condition = f'{complete}\\in {known}'
    if phase == 'align':
        if description['known_form'] == 'affine':
            declared_set = values['known_domain']
            declared = _set_latex(declared_set)
            options = _answer_options(known_set, declared_set, {})
            # Keep the correct choice distinct even when a reflection happens
            # to preserve the given interval. No future domain answer is used.
            options[0], options[1] = options[1], options[0]
            options = [{**option, 'value': f'o{index}'}
                       for index, option in enumerate(options, 1)]
            explanation = (
                f'当 ${known_variable}\\in {declared}$ 时，完整输入 '
                f'${known_argument}$ 取遍 ${known}$。'
                '题设给出完整定义域，且这个一次式能取遍所有实数，'
                f'因此 ${known}$ 就是 ${function_name}$ 的全部输入范围。'
            )
            return {
                'domain_explanation': explanation,
                'title': f'求 {function_name} 的输入范围',
                'question': f'由「${known_call}$ 的定义域为 ${declared}$」，'
                            f'得到 ${function_name}$ 的输入范围是？',
                'interaction': {'type': 'choice', 'field': 'known_object', 'options': options},
                'expected_answer': {'one_of': ['o2']},
                'feedback': {'answer': f'先让 ${known_variable}$ 遍历 ${declared}$，'
                            f'求完整输入 ${known_argument}$ 的取值范围。'},
                'derivation': _derivation('输入范围', f'${known_call}$ 的定义域', declared,
                                          f'${function_name}$ 的输入范围', known,
                                          note=f'完整输入 ${known_argument}$'),
            }
        return {
            'domain_explanation': f'由 ${known_call}$ 的定义域，得到 ${function_name}$ 的输入范围。',
            'title': f'求 {function_name} 的输入范围',
            'question': f'由「${known_call}$ 的定义域为 ${known}$」，得到什么？',
            'interaction': {
                'type': 'choice', 'field': 'known_object',
                'options': [
                    {'value': 'o1', 'label': f'${function_name}$ 的函数值范围是 ${known}$'},
                    {'value': 'o2', 'label': f'${function_name}$ 的输入范围是 ${known}$'
                     f'（对 ${known_call}$ 而言，这也是 ${known_variable}$ 的范围）'},
                ],
            },
            'expected_answer': {'one_of': ['o2']},
            'feedback': {'answer': f'对 ${known_call}$，定义域与输入范围是一回事，都是 ${known}$。'},
            'derivation': _derivation('输入范围', f'${known_call}$ 的定义域', known,
                                      f'${function_name}$ 的输入范围', known),
        }
    if phase == 'condition':
        subject = '抽象调用' if mixed else '目标函数'
        wrong_input = (f'完整输入是 ${target}$ 的函数值'
                       if _identity_input(values, variable, complete) else
                       f'完整输入是 ${variable}$，须有 ${variable}\\in {known}$')
        return {
            'domain_explanation': f'{subject} ${target}$ 有意义，需要完整输入 ${complete}$ '
                                  f'属于 ${function_name}$ 的输入范围。',
            'title': f'列出{subject}的输入条件',
            'question': f'要使{subject} ${target}$ 有意义，完整输入及其须满足的范围是？',
            'interaction': {
                'type': 'choice', 'field': 'input_condition',
                'options': [
                    {'value': 'o1', 'label': f'完整输入是 ${complete}$，须有 ${condition}$'},
                    {'value': 'o2', 'label': wrong_input},
                    {'value': 'o3', 'label': f'完整输入是 ${complete}$，须有 ${complete}\\notin {known}$'},
                ],
            },
            'expected_answer': {'one_of': ['o1']},
            'feedback': {'answer': f'完整输入是 ${complete}$，须有 ${condition}$。'},
            'derivation': _derivation('输入条件', f'${function_name}$ 的输入范围', known,
                                      '完整输入须满足', condition,
                                      note=f'抽象调用 ${target}$' if mixed else f'目标函数 ${target}$'),
        }
    if phase == 'abstract_range':
        domain = values['abstract_domain']
        text = _set_latex(domain)
        outer = values['outer_domain']
        note = (f'题设另限 ${variable}\\in {_set_latex(outer)}$'
                if outer != sp.S.Reals else '')
        return {
            'domain_explanation': f'先解 ${condition}$，得到抽象调用允许的范围 ${text}$。'
                                  '接下来还需检查原分母的限制。',
            'title': '求抽象调用允许的范围',
            'question': f'由 ${condition}$，抽象调用 ${target}$ 允许 ${variable}$ 取哪些值？',
            'interaction': {'type': 'choice', 'field': 'abstract_domain_answer',
                            'options': _answer_options(domain, known_set, {'outer_domain': outer})},
            'expected_answer': {'one_of': ['o1']},
            'feedback': {'answer': f'先求 ${target}$ 有意义的范围，分母条件随后处理。'},
            'derivation': _derivation('抽象调用的范围', '输入条件', condition,
                                      f'${target}$ 允许的范围', text, note=note),
        }
    if phase == 'concrete_range':
        domain = values['concrete_domain']
        text = _set_latex(domain)
        conditions = [latex(row['condition']) for row in values['concrete_constraints']]
        note = ' 且 '.join(f'${item}$' for item in conditions)
        return {
            'domain_explanation': f'原分母要求 {note}，解得 ${variable}\\in {text}$。',
            'title': '求分母允许的范围',
            'question': f'同时满足原分母的限制，${variable}$ 应取哪些值？',
            'interaction': {'type': 'choice', 'field': 'concrete_domain_answer',
                            'options': _answer_options(domain, known_set, {})},
            'expected_answer': {'one_of': ['o1']},
            'feedback': {'answer': '分母不能为零；有根式时，还必须满足根式有意义的条件。'},
            'derivation': _derivation('分母的限制', '原分母',
                                      description['concrete_denominator_latex'],
                                      f'${variable}$ 允许的范围', text, note=note),
        }
    if phase == 'intersection':
        abstract_domain = values['abstract_domain']
        concrete_domain = values['concrete_domain']
        combined = f'{_set_latex(abstract_domain)}\\cap {_set_latex(concrete_domain)}'
        return {
            'domain_explanation': '抽象调用与原分母必须同时有意义，因此取两者允许范围的交集。',
            'title': '取交集，写出定义域',
            'question': f'两部分的限制必须同时满足，目标函数 ${full_target}$ 的定义域是？',
            'interaction': {'type': 'choice', 'field': 'domain_answer',
                            'options': _answer_options(answer_set, abstract_domain,
                                                      {'preimage': concrete_domain})},
            'expected_answer': {'one_of': ['o1']},
            'feedback': {'answer': '定义域必须同时满足抽象调用的输入条件、原分母限制和题设范围。'},
            'derivation': _derivation('目标函数的定义域', '两部分允许的范围', combined,
                                      '目标函数的定义域', answer),
        }
    if phase == 'conclusion':
        options = _answer_options(answer_set, known_set, values)
        relation = ('两者的集合恰好相同，但分别表示目标函数的定义域与输入范围。'
                    if exact_set_equal(answer_set, known_set)
                    else f'${known}$ 是 ${function_name}$ 的输入范围，不是本题最终答案。')
        outer = values.get('outer_domain')
        outer_note = (f'题设另限 ${variable}\\in {_set_latex(outer)}$'
                      if isinstance(outer, sp.Set) and outer != sp.S.Reals else '')
        return {
            'domain_explanation': '解输入条件，并同时满足题设另限的范围。' if outer_note else
                                  f'解输入条件，得到目标函数关于 ${variable}$ 的定义域。',
            'title': '求目标函数的定义域',
            'question': f'由 ${condition}$，目标函数 ${target}$ 关于 ${variable}$ 的定义域是？',
            'interaction': {'type': 'choice', 'field': 'domain_answer', 'options': options},
            'expected_answer': {'one_of': ['o1']},
            'feedback': {'answer': f'定义域是 ${answer}$。{relation}'},
            'derivation': _derivation('目标函数的定义域', '输入条件', condition,
                                      f'${target}$ 的定义域', answer, note=outer_note),
        }
    raise ValueError('abstract_domain.unknown_presentation_phase:' + str(phase))


def presentation(values):
    """Prepare the completed step's two-item derivation; no solving."""
    view = _phase_view(values)
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
    }


def compile_abstract(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed['values'])
    view = _phase_view(values)
    board = deepcopy(view['derivation'])
    # Every beat shows exactly its own premise and one unknown conclusion.
    board['items'][1]['math'] = None
    part = {
        'id': interaction_id + '#1',
        'title': view['title'],
        'question': view['question'],
        'interaction': deepcopy(view['interaction']),
        'expected_answer': deepcopy(view['expected_answer']),
        'feedback': deepcopy(view['feedback']),
        'submit_label': '确认判断',
        'stem_board': board,
    }
    return {'parts': [part], 'diagnostics': []}
