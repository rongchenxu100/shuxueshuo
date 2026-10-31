"""Student cards driven by conversion operations, not individual questions."""

from ..stage_two.range_task_surface import QUANTITY_WORDS
from .abstract_domain_presentation import _set_latex
from .evaluation_presentation import _choice, _lines, _math
from .math_values import latex
from .range_presentation import _card, _function_context, _source_definition
from .trajectory import decode_value

_OPERATIONS = {'extract_quantity', 'evaluate_expression', 'compare_set', 'return_set'}


def _check_operation(operation):
    if operation not in _OPERATIONS:
        raise ValueError('answer_conversion_presentation.unsupported_operation:' + operation)


def phase_view(values):
    data = values['range']
    steps, image = data['steps'], data['image']
    step, output = steps[-1]['step'], decode_value(steps[-1]['output'])
    operation = step['operation']
    _check_operation(operation)
    left, prompt, result = _set_latex(image), '', ''
    interaction, expected = None, None
    if operation == 'extract_quantity':
        names, results = [], []
        for row in steps:
            value = decode_value(row['output'])
            name = QUANTITY_WORDS[value['quantity']]
            symbol = row['step'].get('symbol')
            names.append((f'${symbol}$ 表示' if symbol else '') + name)
            if value['available']:
                results.append((symbol + '=' if symbol else '') + latex(value['value']))
            else:
                results.append(r'\text{' + name + '不存在}')
        title = '由结果确定所需的量'
        prompt = '，'.join(names) + '。根据已验证的完整值域，分别能确定什么？'
        result = _lines(results)
        if len(steps) == 2:
            first, second = [decode_value(row['output']) for row in steps]
            if first['available'] and second['available'] and first['value'] != second['value']:
                wrong = _lines([row['step']['symbol'] + '=' + latex(other['value'])
                                for row, other in zip(steps, (second, first), strict=True)])
                interaction, expected = _choice(f'${result}$', [f'${wrong}$'])
        elif len(steps) == 1 and not output['available'] and output['bound'] is not None:
            interaction, expected = _choice(f'${result}$', [f'${latex(output["bound"])}$'])
    elif operation == 'evaluate_expression':
        title, prompt = '计算原题所求值', f'根据前面确定的量，计算 ${step["expression"]}$。'
        left = _lines([*data['bindings'], step['expression']])
        if output['type'] == 'undefined':
            result = r'\text{所需量不存在，所求式无定义}' if output['reason'] == 'quantity_unavailable' else r'\text{所求式无定义}'
        else:
            value = output['value']
            result = rf'{step["expression"]}={latex(value)}'
            interaction, expected = _choice(f'${latex(value)}$', [f'${latex(value+1)}$', f'${latex(value-1)}$'])
    elif operation == 'compare_set':
        title = '核对原题条件'
        relation = '等于' if step['relation'] == 'equal' else '不等于'
        prompt = f'已求出的完整值域是否{relation} ${_set_latex(output["expected"])}$？'
        left = _lines([rf'V={_set_latex(image)}', rf'S={_set_latex(output["expected"])}'])
        result = r'\text{是}' if output['value'] else r'\text{否}'
        interaction, expected = _choice('是' if output['value'] else '否', ['否' if output['value'] else '是'])
    elif operation == 'return_set':
        title, prompt, result = '回答原题', '返回已经验证的完整值域。', _set_latex(image)
    view = _card(title, prompt, '已验证的结果', left, '原题所求', result, _math(left, result), interaction, expected)
    return _function_context(view, _source_definition(values['description'], values['variable']))


def display_groups(trace, image):
    """Group adjacent quantity bindings; retain the operation evidence per card."""
    groups, pending, bindings = [], [], []
    for row in trace['steps']:
        _check_operation(row['step']['operation'])
        if row['step']['operation'] == 'extract_quantity':
            pending.append(row)
            value = decode_value(row['output'])
            if row['step'].get('symbol'):
                symbol = row['step']['symbol']
                bindings.append(symbol + '=' + latex(value['value']) if value['available'] else rf'\text{{{symbol} 不存在}}')
            continue
        if pending:
            groups.append({'steps': pending, 'image': image, 'bindings': []})
            pending = []
        groups.append({'steps': [row], 'image': image, 'bindings': list(bindings)})
    if pending:
        groups.append({'steps': pending, 'image': image, 'bindings': []})
    return groups
