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
    known_call = f'{function_name}({known_variable})'
    target = f'{function_name}({complete})'
    condition = f'{complete}\\in {known}'
    if phase == 'align':
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
        wrong_input = (f'完整输入是 ${target}$ 的函数值'
                       if _identity_input(values, variable, complete) else
                       f'完整输入是 ${variable}$，须有 ${variable}\\in {known}$')
        return {
            'domain_explanation': f'目标函数 ${target}$ 有意义，需要完整输入 ${complete}$ '
                                  f'属于 ${function_name}$ 的输入范围。',
            'title': '列出目标函数的输入条件',
            'question': f'要使目标函数 ${target}$ 有意义，完整输入及其须满足的范围是？',
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
                                      '完整输入须满足', condition, note=f'目标函数 ${target}$'),
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
