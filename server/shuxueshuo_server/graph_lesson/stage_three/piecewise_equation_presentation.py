"""Solve, filter against the displayed source condition, then merge the inputs."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..piecewise_equation import source
from .evaluation_presentation import _choice, _condition_latex, _lines
from .math_values import latex
from .range_presentation import _card
from .trajectory import decode_value


def _choices(answer, others):
    values = [answer]
    for value in [*others, sp.S.EmptySet, sp.S.Reals]:
        if value not in values:
            values.append(value)
        if len(values) == 3:
            break
    return _choice('$'+latex(answer)+'$', ['$'+latex(v)+'$' for v in values[1:]])


def _root_proof(expression, level, x, candidates):
    poly = sp.Poly(expression-level, x)
    chain = [rf'{latex(expression)}={latex(level)}']
    if poly.degree() == 1:
        a, b = poly.nth(1), poly.nth(0)
        chain.extend([rf'{latex(a*x)}={latex(-b)}', rf'{latex(x)}={latex(-b/a)}'])
    elif poly.degree() == 2:
        a, b, c = (poly.nth(i) for i in (2, 1, 0))
        if b == 0:
            chain.append(rf'{latex(x)}^2={latex(-c/a)}')
        else:
            discriminant = b*b-4*a*c
            chain.extend([rf'{latex(poly.as_expr())}=0', rf'\Delta={latex(discriminant)}'])
            if discriminant >= 0:
                chain.append(rf'{latex(x)}=\frac{{-({latex(b)})\pm\sqrt{{{latex(discriminant)}}}}}{{2\cdot({latex(a)})}}')
    else:
        chain.append(rf'{latex(poly.as_expr())}=0')
    chain.append(rf'{latex(x)}\in {latex(candidates)}')
    return _lines(chain)


def phase_views(values):
    desc, rows = values['description'], values['branch_results']
    x, level, _ = source(desc)
    name = next(r['ast'][1][1].rsplit(':', 1)[-1] for r in desc['sources'] if r['ast'][0] == 'function_definition')
    pricing = desc.get('pricing_source', {}).get('goal_ast')
    value_label = pricing['pricing']['amount'] if pricing else rf'{name}({latex(x)})'
    views = []
    if values['phase'] == 'branches':
        if pricing:
            from .piecewise_modeling_presentation import cases
            formula = cases(pricing)
            v = _card('先看费用关系，再反求用量',
                      rf'按题目的阶梯单价累计，费用关系如下。已知电费 ${pricing["bill"]}$ 元，接下来分别在三档中令总费用等于这个数，再检查用量范围。',
                      '核对后的费用关系（元）', formula, '本问已知的电费', value_label+'='+latex(level),
                      '', {'type': 'read'}, {})
            v['proof'] = formula
            views.append(v)
        for index, row in enumerate(rows, 1):
            condition = _condition_latex(row['condition_ast'], desc['variable'])
            expression, candidates, accepted = row['expression'], row['candidates'], row['accepted']
            equation = rf'{latex(expression)}={latex(level)}'
            i, expected = _choices(candidates, [sp.FiniteSet(*list(candidates)[:1]) if isinstance(candidates, sp.FiniteSet) else sp.S.EmptySet])
            view = _card(f'第{index}段：解方程',
                         rf'当 ${condition}$ 时，${value_label}={latex(expression)}$。由 ${value_label}={latex(level)}$ 列出下面的方程，先求出它的全部实数解。',
                         '本段范围与方程', _lines([condition, equation]), '方程的解（下一步检查范围）',
                         rf'{latex(x)}\in {latex(candidates)}', '先求方程的全部实数解，再检查这一段的范围。', i, expected)
            view['proof'] = _root_proof(expression, level, x, candidates)
            views.append(view)
            i, expected = _choices(accepted, [candidates, row['rejected']])
            view = _card(f'第{index}段：检查范围',
                         rf'刚才解的是 ${equation}$，但这一段只适用于 ${condition}$。哪些解可以保留？',
                         '方程的解与本段范围', _lines([rf'{latex(x)}\in {latex(candidates)}', condition]),
                         '本段保留的解', rf'{latex(x)}\in {latex(accepted)}',
                         '只有同时满足方程和本段范围的解才能保留。', i, expected)
            proof = []
            if isinstance(candidates, sp.FiniteSet):
                for root in sorted(candidates):
                    member = root in row['domain']
                    proof.append(rf'{latex(root)}'+(r'\in' if member else r'\notin')+latex(row['domain'])
                                 +rf'\quad\text{{{"保留" if member else "舍去"}}}')
            proof.append(rf'{latex(candidates)}\cap {latex(row["domain"])}={latex(accepted)}')
            view['proof'] = _lines(proof)
            views.append(view)
    elif values['phase'] == 'merge':
        answer = values['feasible_set']
        i, expected = _choices(answer, [*(r['accepted'] for r in rows), sp.Union(*(r['candidates'] for r in rows))])
        view = _card('合并各段保留的解', rf'满足任意一段的条件即可。把各段保留的解合起来，${latex(x)}$ 的全部取值是什么？',
                     '每段保留的解', _lines([rf'\text{{第{n}段}}:\ {latex(r["accepted"])}' for n, r in enumerate(rows, 1)]),
                     '原方程的全部解', rf'{latex(x)}\in {latex(answer)}',
                     '段内同时满足条件，段间合并全部合法解。', i, expected)
        view['proof'] = r'\cup'.join(latex(r['accepted']) for r in rows)+'='+latex(answer)
        views.append(view)
        if pricing and isinstance(answer, sp.FiniteSet) and len(answer) == 1:
            from ..piecewise_modeling import model
            from .piecewise_modeling_presentation import decimal
            root = next(iter(answer))
            r = next(r for r in model(pricing)['rows'] if root in r['domain'])
            proof = rf'{decimal(r["prior"])}+{decimal(r["rate"])}({latex(root)}-{latex(r["lower"])})={latex(level)}'
            v = _card('代回计费规则，写出用电量',
                      rf'用电量为 ${latex(root)}$ 千瓦时时，按对应档位累计计算电费。结果是否等于题给的 ${latex(level)}$ 元？',
                      '前档费用＋本档新增费用', proof, '该月用电量', latex(root)+r'\text{ 千瓦时}',
                      '', {'type': 'read'}, {})
            v['proof'] = proof+r'\quad\text{（元）}'
            views.append(v)
    else:
        raise ValueError('piecewise_equation.unknown_phase')
    return views


def presentation(values):
    views = phase_views(values)
    view = views[0]
    left, right = view['derivation']['items']
    return {'formula_title': '逐段解方程并检查范围' if values['phase'] == 'branches' else view['title'],
            'formula_explanation': '\n\n'.join('$$'+v['proof']+'$$' for v in views),
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_piecewise(seeds, interaction_id):
    (seed,) = seeds
    views = phase_views(decode_value(seed['values']))
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        if view['interaction']['type'] != 'read':
            board['items'][1]['math'] = None
        else:
            board = {'caption': view['title'], 'lines': ['$$'+r['math']+'$$' for r in board['items']]}
        interaction = deepcopy(view['interaction'])
        if 'options' in interaction:
            interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        parts.append({'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                      'interaction': interaction, 'expected_answer': view['expected_answer'],
                      'feedback': {**view['feedback'], 'answer': '$$'+view['proof']+'$$'}, 'submit_label': '确认这一步',
                      'stem_board': board, 'completion_board': view['derivation']})
    return {'parts': parts, 'diagnostics': []}
