"""Three local cards: translation identity, exact input cover, image union."""

import sympy as sp

from .abstract_domain_presentation import _set_latex
from .evaluation_presentation import _choice, _lines, _math
from .math_values import latex
from .range_presentation import _card, _image_choices
from .translation_range import solve


def formulas(desc):
    f, g, v = desc['function_name'], desc['periodic_name'], desc['variable']
    x, k = sp.Symbol(v), sp.Symbol('n' if v == 'k' else 'k', integer=True)
    p, a = sp.Rational(desc['period']), sp.Rational(desc['slope'])
    rule = rf'{f}({v})={latex(a*x+sp.Function(g)(x))}'
    periodic = rf'{g}({latex(x+p)})={g}({v})'
    shifted = rf'{f}({latex(x+k*p)})={latex(sp.Function(f)(x)+a*k*p)}'
    return rule, periodic, shifted


def indexes(rows, symbol='k'):
    nums = [row['k'] for row in rows]
    if len(nums) > 4 and nums == list(range(int(nums[0]), int(nums[-1])+1)):
        return rf'{symbol}={latex(nums[0])},{latex(nums[0]+1)},\ldots,{latex(nums[-1])}'
    return symbol + r'\in\{' + ','.join(latex(k) for k in nums) + r'\}'


def _unit_shift_phrase(period, index, direction):
    """Student-facing wording for a one-period left/right example with k."""
    p = sp.Rational(period)
    k = latex(-1 if direction < 0 else 1)
    side = '向左' if direction < 0 else '向右'
    if p == 1:
        return rf'${index}={k}$ 时{side}平移 $1$ 个单位'
    return rf'${index}={k}$ 时{side}平移 $1$ 个周期（每个周期长 ${latex(p)}$）'


def _unit_shift_math(period, index, direction):
    """Same idea as `_unit_shift_phrase`, safe inside a gathered math block."""
    p = sp.Rational(period)
    k = latex(-1 if direction < 0 else 1)
    side = '向左' if direction < 0 else '向右'
    if p == 1:
        return rf'{index}={k}\ \text{{时{side}平移 }}1\text{{ 个单位}}'
    return rf'{index}={k}\ \text{{时{side}平移 }}1\text{{ 个周期（周期长 }}{latex(p)}\text{{）}}'


def phase_view(values):
    from .translation_range import translate

    desc, data = values['description'], values['description']['translation']
    f, v = desc['function_name'], desc['variable']
    rule, periodic, shifted = formulas(desc)
    rows = data['rows']
    base, target, image = (_set_latex(data[key]) for key in ('base', 'domain', 'known_image'))
    index = 'n' if v == 'k' else 'k'
    ks = indexes(rows, index)
    period = data['period']
    if values['phase'] == 'translation_relation':
        wrong = rf'{f}({latex(sp.Symbol(v)+sp.Symbol(index)*period)})={f}({v})'
        if data['slope'] == 0:
            wrong += '+' + index
        interaction, answer = _choice(f'${shifted}$', [f'${wrong}$'])
        return _card(
            '写出平移后的函数值',
            (rf'已知 ${rule}$，且 ${periodic}$。'
             rf'把输入从 ${v}$ 挪到 ${latex(sp.Symbol(v)+sp.Symbol(index)*period)}$'
             rf'（${index}\in\mathbb Z$）后，${f}$ 的值变成？'),
            '已知条件', _lines([rule, periodic, index + r'\in\mathbb Z']),
            '平移后的函数值', shifted,
            _math(rf'{desc["periodic_name"]}({latex(sp.Symbol(v)+sp.Symbol(index)*period)})={desc["periodic_name"]}({v})',
                  shifted),
            interaction, answer)
    if values['phase'] == 'translation_coverage':
        wrong = indexes([{'k': row['k']+1} for row in rows], index)
        interaction, answer = _choice(f'${ks}$', [f'${wrong}$'])
        left, right = translate(data['base'], -period), translate(data['base'], period)
        left_tex, right_tex = _set_latex(left), _set_latex(right)
        samples = rows if len(rows) <= 3 else [rows[0], rows[-1]]
        shifted_inputs = [
            rf'{index}={latex(row["k"])}\ \text{{时的输入段}}:\ {_set_latex(row["input"])}'
            for row in samples
        ]
        if len(rows) > 3:
            shifted_inputs.insert(1, r'\vdots')
        return _card(
            '用平移盖住输入范围',
            (rf'我们已经知道区间 ${base}$ 上的情况。'
             rf'例如：{_unit_shift_phrase(period, index, -1)}得到 ${left_tex}$，'
             rf'{_unit_shift_phrase(period, index, 1)}得到 ${right_tex}$。'
             rf'要刚好盖住要求的输入范围 ${target}$，需要哪些整数 ${index}$？'),
            '已知区间与平移例子',
            _lines([
                rf'\text{{已知区间}}={base}',
                rf'{_unit_shift_math(period, index, -1)}={left_tex}',
                rf'{_unit_shift_math(period, index, 1)}={right_tex}',
                rf'\text{{要求盖住}}={target}',
            ]),
            '需要的平移次数', _lines([ks, *shifted_inputs]),
            _math(ks, *(rf'{index}={latex(row["k"])}:\ {_set_latex(row["input"])}' for row in rows),
                  rf'\text{{这些输入段合起来}}={target}'),
            interaction, answer)
    if values['phase'] == 'translation_union':
        computed = data['feasible_set']
        interaction, answer = _image_choices(computed, data['known_image'])
        samples = rows if len(rows) <= 3 else [rows[0], rows[-1]]
        output_rows = [
            rf'{index}={latex(row["k"])}\ \text{{时的值域}}:\ {_set_latex(row["output"])}'
            for row in samples
        ]
        if len(rows) > 3:
            output_rows.insert(1, r'\vdots')
        return _card(
            '把各段值域合起来',
            (rf'区间 ${base}$ 上的值域是 ${image}$，且 ${shifted}$。'
             rf'每个平移次数 ${index}$ 对应一段值域。'
             rf'这些值域段全部合起来，${f}$ 的值域是？'),
            '已知值域与各次平移后的值域',
            _lines([rf'{base}\ \text{{上的值域}}={image}', ks, *output_rows]),
            '合起来的值域', _set_latex(computed),
            _math(*(rf'{index}={latex(row["k"])}:\ {_set_latex(row["output"])}' for row in rows),
                  rf'\text{{合起来}}={_set_latex(computed)}'),
            interaction, answer)
    raise ValueError('translation_range.unknown_phase')


def domain_prerequisite(desc):
    data = solve(desc)
    rule, _, _ = formulas(desc)
    domain = rf'{desc["variable"]}\in{_set_latex(data["domain"])}'
    return {'id': 'D3-domain', 'title': '确定本次求值区间',
            'question': (rf'${desc["periodic_name"]}$ 在 $\mathbb R$ 上有定义，因此 ${rule}$ 也在 $\mathbb R$ 上有定义。'
                         rf'本次要求的输入范围为 ${domain}$。'),
            'summary': f'${domain}$', 'interaction': {'type': 'read'}, 'expected_answer': {},
            'submit_label': '在这个范围内选择方法', 'source_refs': desc['source_refs'],
            'effects': {'nodes': [], 'edges': [], 'calls': [], 'results': [],
                        'log': '已确定本次求值域的输入范围。'}}
