"""Teaching projection for FM-T3 known-monotonicity inequality (R0)."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _lines
from .trajectory import decode_value

OPS = {'<': '<', '<=': r'\le', '>': '>', '>=': r'\ge'}


def _set_latex(value):
    if value == sp.S.Reals:
        return r'\mathbb{R}'
    if value == sp.S.EmptySet:
        return r'\varnothing'
    return latex(value).replace(r', \infty\right', r', +\infty\right')


def _load(value, *keys):
    if isinstance(value, dict) and any(key in value for key in keys):
        return value
    return decode_value(value)


def _membership(var, value):
    """Name the object in set answers: $x\\in(0,\\infty)$, never a bare interval."""
    return rf'{var}\in {_set_latex(value)}'


def _wrong_memberships(var, answer):
    candidates = [sp.S.EmptySet, sp.S.Reals]
    if isinstance(answer, sp.Interval):
        candidates += [
            sp.Interval(answer.start, answer.end,
                        left_open=not answer.left_open, right_open=answer.right_open),
            sp.Interval(answer.start, answer.end,
                        left_open=answer.left_open, right_open=not answer.right_open),
            answer.closure if hasattr(answer, 'closure') else answer,
        ]
        if answer.start.is_finite:
            candidates.append(sp.Interval(answer.start, answer.end,
                                          left_open=False, right_open=answer.right_open))
        if answer.end.is_finite:
            candidates.append(sp.Interval(answer.start, answer.end,
                                          left_open=answer.left_open, right_open=False))
    wrong = []
    for candidate in candidates:
        text = _membership(var, candidate)
        if text != _membership(var, answer) and text not in wrong:
            wrong.append(text)
        if len(wrong) >= 3:
            break
    return wrong or [_membership(var, sp.S.EmptySet), _membership(var, sp.S.Reals)]


def _wrong_ops(answer):
    return [OPS[op] for op in ('<', '<=', '>', '>=') if OPS[op] != answer]


def _fold_phase(description, model, phase):
    """Hide telegraph / redundant cards; keep math stream via empty compile."""
    proved = description.get('mono_basis') == 'proved_monotonicity'
    if phase == 'prepare' and proved:
        # Prove pieces first; do not ask students to name the overall direction up front.
        return True
    if phase == 'basis':
        # Cross-piece join already states the overall strict monotonicity.
        return True
    if phase == 'inputs' and model.get('usable_set') == sp.S.Reals:
        return True
    return False


def phase_views(values):
    description = _load(values['description'], 'source', 'function')
    model = _load(values['mono_inequality_result'], 'feasible_set', 'converted_op')
    phase = values.get('phase', 'conclude')
    fn = description['function']
    var = description['variable']
    direction = description['direction']
    arrow = r'\uparrow' if direction == 'increasing' else r'\downarrow'
    direction_text = '递增' if direction == 'increasing' else '递减'
    u, v = model['left_input'], model['right_input']
    original = rf'{fn}\!\left({latex(u)}\right)\,{OPS[model["relation_op"]]}\,{fn}\!\left({latex(v)}\right)'
    converted = rf'{latex(u)}\,{OPS[model["converted_op"]]}\,{latex(v)}'
    mono = _set_latex(model['mono_interval'])
    usable = _set_latex(model['usable_set'])
    feasible = _set_latex(model['feasible_set'])

    if _fold_phase(description, model, phase):
        return []

    if phase == 'prepare':
        wrong = [r'\downarrow' if direction == 'increasing' else r'\uparrow', r'\text{非严格}']
        return [choice_card(
            '核对比较对象与单调性',
            f'本题比较的是同一个函数的两个函数值。已知 ${fn}$ 在 ${mono}$ 上怎样变化？',
            '原比较', original,
            '题给单调性', rf'{fn}\text{{ 在 }}{mono}\text{{ 上 }}{arrow}',
            wrong,
            _lines([original, rf'{fn}\ \text{{在}}\ {mono}\ \text{{上}}\ {arrow}']),
        )]

    if phase == 'inputs':
        left = _lines([
            rf'{latex(u)},{latex(v)}\in {mono}',
            rf'{var}\text{{ 的合法范围 }}',
        ])
        answer = _membership(var, model['usable_set'])
        return [choice_card(
            '两个输入的合法条件',
            f'要使单调性可用来比较，两个输入都必须落在 ${mono}$。${var}$ 需要满足什么？',
            '输入条件', left,
            '合法域', answer,
            _wrong_memberships(var, model['usable_set']),
            _lines([rf'{latex(u)},{latex(v)}\in {mono}', answer]),
        )]

    if phase == 'order':
        stem = _lines([
            original,
            rf'{fn}\ {arrow}\text{{（严格{direction_text}）}}',
            rf'{latex(u)},{latex(v)}\in {mono}',
        ])
        # Stem right cell stays null (schema); options hold the relation; completion shows it.
        return [choice_card(
            '利用单调性转化比较',
            f'在同一严格{direction_text}区间上，原函数值比较等价于怎样的输入比较？',
            '已确认的条件', stem,
            '输入比较', converted,
            [rf'{latex(u)}\,{op}\,{latex(v)}' for op in _wrong_ops(OPS[model['converted_op']])],
            _lines([stem, rf'\Rightarrow {converted}']),
        )]

    if phase == 'conclude':
        left = _lines([
            converted,
            rf'{var}\in {usable}',
        ])
        answer = _membership(var, model['feasible_set'])
        return [choice_card(
            '回到原目标',
            f'把转化后的不等式与合法域求交，${var}$ 的取值范围是？',
            '转化后 ∩ 合法域', left,
            '解集', answer,
            _wrong_memberships(var, model['feasible_set']),
            _lines([converted, rf'{var}\in {usable}', answer]),
        )]

    return []


def presentation(values):
    views = phase_views(values)
    if not views:
        # Folded cards still need non-empty derivation fields for highlight schema.
        phase = values.get('phase', 'conclude')
        return {
            'formula_title': phase,
            'formula_explanation': r'\text{（本步折叠）}',
            'derivation_caption': phase,
            'derivation_left_label': '—',
            'derivation_left_math': r'\text{（折叠）}',
            'derivation_left_note': '',
            'derivation_right_label': '—',
            'derivation_right_math': r'\text{（折叠）}',
        }
    view = views[0]
    left, right = view['derivation']['items']
    return {
        'formula_title': view['title'],
        'formula_explanation': '\n\n'.join('$$'+v['proof']+'$$' for v in views),
        'derivation_caption': view['title'],
        'derivation_left_label': left['label'],
        'derivation_left_math': left['math'],
        'derivation_left_note': '',
        'derivation_right_label': right['label'],
        'derivation_right_math': right['math'],
    }


def compile_mono_inequality(seeds, interaction_id):
    from .interaction import NotInteractive

    seed, = seeds
    views = phase_views(decode_value(seed['values']))
    if not views:
        raise NotInteractive('folded')
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        interaction = deepcopy(view['interaction'])
        interaction['options'].sort(
            key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        parts.append({
            'id': f'{interaction_id}#{index}',
            'title': view.get('part_title', view['title']),
            'question': view['question'],
            'interaction': interaction,
            'expected_answer': view['expected_answer'],
            'feedback': view['feedback'],
            'submit_label': '确认判断',
            'stem_board': board,
            'completion_board': view['derivation'],
        })
    return {'parts': parts, 'diagnostics': []}
