"""One billing action at a time; completed cards retain the arithmetic proof."""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256

import sympy as sp

from ..piecewise_modeling import model
from .evaluation_presentation import _choice, _lines
from .math_values import latex
from .range_presentation import _card
from .trajectory import decode_value


def decimal(value):
    # All displayed billing coefficients are terminating source decimals.
    return format(Decimal(int(value.p))/Decimal(int(value.q)), 'f').rstrip('0').rstrip('.') if value.q != 1 else str(value)


def expression(row, x):
    constant = sp.expand(row['expression']).subs(x, 0)
    return decimal(row['rate'])+latex(x)+(('+' if constant > 0 else '-')+decimal(abs(constant)) if constant else '')


def cases(goal):
    built = model(goal)
    x = sp.Symbol(goal['pricing']['quantity'], real=True)
    rows = []
    for i, r in enumerate(built['rows']):
        condition = (rf'0\le {x}\le {latex(r["upper"])}' if i == 0 else
                     rf'{latex(r["lower"])}<{x}\le {latex(r["upper"])}' if i == 1 else rf'{x}>{latex(r["lower"])}')
        rows.append(expression(r, x)+',&'+condition)
    return goal['pricing']['amount']+r'=\begin{cases}'+r'\\'.join(rows)+r'\end{cases}'


def card(title, question, left_label, left, right_label, right, wrong, proof):
    interaction, expected = _choice('$'+right+'$', ['$'+w+'$' for w in wrong if w != right])
    view = _card(title, question, left_label, left, right_label, right, '', interaction, expected)
    view['proof'] = proof
    view['feedback']['answer'] = '$$'+proof+'$$'
    return view


def phase_views(values):
    goal = values['description']['goal_ast']
    built = values['model_result']
    p = goal['pricing']
    x = sp.Symbol(p['quantity'], real=True)
    a, b = p['thresholds']
    rates = p['rates']
    y = p['amount']
    rows = built['rows']
    views = [card('第一档：全部按第一档单价计费',
                  rf'用电量不超过 ${a}$ 千瓦时，每千瓦时 ${rates[0]}$ 元。${x}\ge0$，这时总电费是多少？',
                  '用量范围与单价', _lines([rf'0\le {x}\le{a}',rf'\text{{单价}}={rates[0]}\text{{ 元/千瓦时}}']),
                  '总电费（元）', rf'{y}={rates[0]}{x}', [rf'{y}={rates[1]}{x}', rf'{y}={rates[0]}({x}-{a})'],
                  rf'{y}={rates[0]}\times {x}={rates[0]}{x},\quad 0\le {x}\le{a}')]
    for i, row in enumerate(rows[1:], 1):
        lower = latex(row['lower'])
        condition = rf'{a}<{x}\le{b}' if i == 1 else rf'{x}>{b}'
        prior_sum = rates[0]+r'\times '+a
        if i == 2:
            prior_sum += '+'+rates[1]+rf'\times({b}-{a})'
        prior = decimal(row['prior'])
        add = rates[i]+rf'({x}-{lower})'
        views.append(card(f'第{i+1}档：先算前面各档的费用',
                          rf'当 ${condition}$ 时，前 ${lower}$ 千瓦时已经用完。前面各档合计收费多少元？',
                          '前面各档分别计费', prior_sum, '前档费用（元）', prior,
                          [rates[i]+r'\times '+lower, '0'], prior_sum+'='+prior))
        views.append(card(f'第{i+1}档：只给新增用量计费',
                          rf'现在只计算超过 ${lower}$ 千瓦时的部分。这部分用电量是 ${x}-{lower}$，每千瓦时 ${rates[i]}$ 元，新增费用是多少？',
                          '本档新增用量与单价', _lines([rf'{x}-{lower}', rates[i]+r'\text{ 元/千瓦时}']),
                          '本档费用（元）', add, [rates[i]+str(x), rates[i]+rf'({x}+{lower})'],
                          rf'\text{{新增费用}}=({x}-{lower})\times {rates[i]}={add}'))
        total = expression(row, x)
        views.append(card(f'第{i+1}档：把两部分费用相加',
                          rf'前面各档收费 ${prior}$ 元，本档新增费用为 ${add}$ 元。总电费怎样表示？',
                          '前档费用＋本档费用', prior+'+'+add, '总电费（元）', y+'='+total,
                          [y+'='+rates[i]+str(x), y+'='+add], y+'='+prior+'+'+add+'='+total))
    table = r'\begin{array}{c|c|c|c}\text{用量范围}&\text{前档费用}&\text{新增费用}&\text{总费用}\\'
    for i, row in enumerate(rows):
        domain = rf'0\le {x}\le{a}' if i == 0 else rf'{a}<{x}\le{b}' if i == 1 else rf'{x}>{b}'
        added = rates[i]+str(x) if i == 0 else rates[i]+rf'({x}-{latex(row["lower"])})'
        table += domain+'&'+decimal(row['prior'])+'&'+added+'&'+expression(row,x)+r'\\'
    table += r'\end{array}'
    formula = cases(goal)
    # Summary is a read card: no repeated artificial method selection.
    view = _card('汇总：按用量分段写出电费', '把三档结果合起来。注意：超过分界点后，前面各档仍按原单价收费。',
                 '各档累计费用（元）', table, '费用关系式', formula, '$$'+formula+'$$', {'type':'read'}, {})
    view['proof'] = formula
    views.append(view)
    endpoint_lines = [rf'{x}=0:\ {y}=0',rf'{x}={a}:\ {y}={rates[0]}\times {a}={decimal(rows[1]["prior"])}',
                      rf'{x}={b}:\ {y}={decimal(rows[1]["prior"])}+{rates[1]}({b}-{a})={decimal(rows[2]["prior"])}']
    view = _card('核对分界点', '用量恰好到分界点时，按截至这一档的累计费用计算；不重复收费，也不漏掉分界点。',
                 '分界点代入', _lines(endpoint_lines), '检查结果', r'\text{三档衔接一致}', '', {'type':'read'}, {})
    view['proof'] = _lines(endpoint_lines)
    views.append(view)
    return views


def presentation(values):
    views = phase_views(values)
    v = views[0]
    l, r = v['derivation']['items']
    return {'formula_title': '逐档累计费用，建立分段函数',
            'formula_explanation': '\n\n'.join('$$'+v['proof']+'$$' for v in views),
            'derivation_caption': v['title'], 'derivation_left_label': l['label'],
            'derivation_left_math': l['math'], 'derivation_left_note': '',
            'derivation_right_label': r['label'], 'derivation_right_math': r['math']}


def compile_step(seeds, interaction_id):
    (seed,) = seeds
    parts = []
    for index, v in enumerate(phase_views(decode_value(seed['values'])), 1):
        board = deepcopy(v['derivation'])
        interaction = deepcopy(v['interaction'])
        if interaction['type'] != 'read':
            board['items'][1]['math'] = None
            interaction['options'].sort(key=lambda r: sha256(f'{interaction_id}:{index}:{r["value"]}'.encode()).digest())
        else:
            board = {'caption': v['title'], 'lines': ['$$'+r['math']+'$$' for r in board['items']]}
        parts.append({'id': f'{interaction_id}#{index}', 'title': v['title'], 'question': v['question'],
                      'interaction': interaction, 'expected_answer': v['expected_answer'],
                      'feedback': {**v['feedback'], 'answer': '$$'+v['proof']+'$$'}, 'submit_label':'确认这一步',
                      'stem_board': board, 'completion_board':v['derivation']})
    return {'parts': parts, 'diagnostics': []}
