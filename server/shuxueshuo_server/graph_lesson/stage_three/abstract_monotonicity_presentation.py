"""Abstract monotonicity cards, driven by the checked symbolic construction."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ...problem_understanding.notation_parser import parse
from ..abstract_monotonicity_math import _structure, construction
from .absolute_graph_presentation import choice_card
from .math_values import latex
from .monotonicity_parameter_presentation import _lines, _with_feedback
from .trajectory import decode_value

WORD = {'increasing': '严格递增', 'decreasing': '严格递减'}
CONSTRUCT = '用函数关系构造差式'


def _set_tex(value):
    return r'\mathbb{R}' if value == sp.S.Reals else latex(value).replace(r', \infty\right', r', +\infty\right')


def _range_tex(name, value):
    if value.sup == sp.oo and value.left_open:
        return rf'{name}>{latex(value.inf)}'
    if value.inf == -sp.oo and value.right_open:
        return rf'{name}<{latex(value.sup)}'
    return rf'{name}\in {_set_tex(value)}'


def _source_tex(ast, parent=0):
    """Small source-preserving renderer for the admitted relation grammar."""
    tag = ast[0]
    if tag in ('name', 'number'):
        return latex(sp.Symbol(ast[1])) if tag == 'name' else ast[1]
    if tag == 'call':
        return rf'{ast[1]}\left({_source_tex(ast[2])}\right)'
    if tag == 'and':
        return r',\quad '.join(_source_tex(t) for t in ast[1:])
    if tag in ('=', '<', '>', '<=', '>='):
        return _source_tex(ast[1])+{'<=': r'\le ', '>=': r'\ge '}.get(tag, tag)+_source_tex(ast[2])
    if tag == '/':
        return rf'\frac{{{_source_tex(ast[1])}}}{{{_source_tex(ast[2])}}}'
    if tag == 'neg':
        body, prec = '-'+_source_tex(ast[1], 3), 2
    else:
        prec = 1 if tag in ('+', '-') else 2
        body = _source_tex(ast[1], prec)+({ '*': r'\cdot '}.get(tag, tag))+_source_tex(ast[2], prec+(tag != '+'))
    return rf'\left({body}\right)' if parent > prec else body


def _context(values):
    description = values['description']
    if not isinstance(description, dict) or 'source' not in description:
        description = decode_value(description)
    s = _structure(description['source'])
    proof = construction(description)
    x1, x2 = map(latex, proof['pair'])
    anchor, target = (x1, x2) if s['orientation'] == 1 else (x2, x1)
    f = description['function']
    used = set(description['relation_variables']) | {f}
    u, v = next(pair for pair in [('u', 'v'), ('s', 't'), ('p', 'q')] if not used.intersection(pair))
    call = lambda arg: rf'{f}\left({arg}\right)'
    joint = f'{u}+{v}' if s['input'] == 'sum' else rf'{u}\cdot {v}'
    output = call(u)+('+' if s['output'] == 'sum' else r'\cdot ')+call(v)
    key = latex(proof['key'])
    fk, fa = call(key), call(anchor)
    delta = call(x2)+'-'+call(x1)
    if s['output'] == 'sum':
        rhs = fk if s['orientation'] == 1 else '-'+fk
    else:
        rhs = fa+rf'\left({fk}-1\right)' if s['orientation'] == 1 else fa+rf'\left(1-{fk}\right)'
    return {
        **s, 'f': f, 'u': u, 'v': v, 'x1': x1, 'x2': x2, 'anchor': anchor, 'target': target,
        'call': call, 'proof': proof, 'key': key, 'fkey': fk, 'fa': fa, 'delta': delta, 'rhs': rhs,
        'interval': _set_tex(s['interval']), 'relation_domain': _set_tex(s['relation_domain']),
        'relation_tex': _source_tex(parse(description['relation'])),
        'canonical': call(joint)+'='+output, 'joint': joint,
        'scope': _range_tex(latex(sp.Symbol(description['sign_variable'])), s['sign_domain']),
        'sign_rule': _source_tex(parse(description['sign_statement'])),
        'instance': call(target)+'='+fa+('+' if s['output'] == 'sum' else r'\cdot ')+fk,
    }


def _pair_view(c):
    pair = rf'\text{{任取}}\ {c["x1"]},{c["x2"]}\in {c["interval"]},\ {c["x1"]}<{c["x2"]}'
    wrong = [pair.replace(r'\text{任取}', r'\text{只取一组}'),
             rf'\text{{先假设}}\ {c["call"](c["x1"])}<{c["call"](c["x2"])}']
    return _with_feedback(choice_card(
        '任取两点', '要判断整个考察区间上的单调性，比较的两个输入应怎样选？',
        '考察区间', rf'{c["f"]}\ \text{{在}}\ {c["interval"]}', '两个输入', pair, wrong,
        _lines([pair, rf'\Delta={c["delta"]}'])), {
        wrong[0]: '只比较一组输入不能代表区间内任意两点。',
        wrong[1]: '函数值的大小是需要证明的结论，不能事先假设。'})


def _normalize_view(c):
    # Reverse difference/quotient relations become the direct relation by a
    # reversible substitution of universally quantified variables.
    n = c['normalization']
    note = f'把题给关系中的两个全称变量重新记作 ${c["u"]},{c["v"]}$，整理等式。'
    proof = [c['relation_tex']]
    if n['variant'] == 'inverse':
        source = c['proof']['normalization']
        # The names here come from the original, not the fresh arbitrary pair.
        names = c['source_variables'][::-1] if source['swapped'] else c['source_variables']
        substitutions = rf'{latex(sp.Symbol(names[0]))}={c["joint"]},\ {latex(sp.Symbol(names[1]))}={c["u"]}'
        note = rf'在题给关系中令 ${substitutions}$，再整理成输入相加或相乘的形式。'
        proof.append(rf'\text{{令}}\ {substitutions}')
    wrong = [c['call'](c['joint'])+'='+c['call'](c['u'])+'-'+c['call'](c['v'])]
    view = choice_card(CONSTRUCT, note, '题给关系', c['relation_tex'], '整理后的关系', c['canonical'], wrong,
                       _lines(proof+[c['canonical']]))
    view['part_title'] = '整理函数关系'
    return _with_feedback(view, {wrong[0]: '移项时检查符号；重新命名全称变量不会改变运算关系。'})


def _substitute_view(c):
    key, anchor, target, v = c['key'], c['anchor'], c['target'], c['v']
    join = anchor+'+'+v if c['input'] == 'sum' else anchor+r'\cdot '+v
    wrong_key = latex(-c['proof']['key']) if c['input'] == 'sum' else latex(1/c['proof']['key'])
    right = rf'{v}={key}'
    wrong = [rf'{v}={wrong_key}', rf'{v}={target}']
    view = choice_card(CONSTRUCT,
        rf'令 ${c["u"]}={anchor}$。要使输入 ${join}$ 等于 ${target}$，${v}$ 应取什么？',
        '函数关系与目标', _lines([c['canonical'], rf'{join}={target}']), '代入的值', right, wrong,
        _lines([rf'{c["u"]}={anchor},\ {right}', c['instance']]))
    view['part_title'] = '选择代入'
    return _with_feedback(view, {w: '代入后检查输入的组合是否等于目标；不能交换差或商的方向。' for w in wrong})


def _check_view(c):
    right = rf'{c["anchor"]}>0,\ {c["key"]}>0'
    wrong = [rf'{c["anchor"]}\ne0', rf'{c["target"]}-{c["anchor"]}\ne0']
    view = choice_card(CONSTRUCT, '题给关系只对正数输入成立。代入前要完整核对什么？',
                       '关系成立的范围', rf'{c["u"]},{c["v"]}\in {c["relation_domain"]}',
                       '输入条件', right, wrong, _lines([right, c['instance']]))
    view['part_title'] = '检查代入'
    return _with_feedback(view, {w: '不仅分母不能为零，代入关系的两个输入还必须都是正数。' for w in wrong})


def _positive_view(c):
    f, call = c['f'], c['call']
    unit = latex(c['unit'])
    preimage = latex(c['proof']['positive_certificate']['square_input'])
    t = 't' if f != 't' else 'z'
    inverse = '-'+t if c['input'] == 'sum' else rf'\frac{{1}}{{{t}}}'
    witness = (rf'{c["scope"]}\Rightarrow {c["sign_rule"]}' if c['positive_witness'] == 'sign'
               else rf'\text{{题给等式中的分母}}\ {f}({t})\ne0')
    right = c['fa']+'>0'
    wrong = [c['fa']+'<0', c['fa']+'=0']
    proof = [witness, rf'{f}\not\equiv0\Rightarrow {call(unit)}=1',
             rf'1={f}({t}){call(inverse)}\Rightarrow {f}({t})\ne0',
             rf'{c["fa"]}={call(preimage)}^2>0']
    view = choice_card(CONSTRUCT, '差式里会出现一个函数值因子。利用题给关系和非零依据，先判断它的符号。',
                       '函数关系与依据', _lines([c['canonical'], witness]), '函数值因子', right, wrong, _lines(proof))
    view['part_title'] = '证明函数值为正'
    return _with_feedback(view, {w: '先得到中性输入处函数值为 1，再排除零值；每个函数值都可写成一个非零函数值的平方。' for w in wrong})


def _difference_view(c):
    right = c['delta']+'='+c['rhs']
    wrong = [c['delta']+rf'=-\left({c["rhs"]}\right)', c['delta']+'=0']
    view = choice_card(CONSTRUCT, rf'整理代入后的等式，${c["delta"]}$ 等于什么？',
                       '代入后的等式', c['instance'], '函数值之差', right, wrong,
                       _lines([c['instance'], right]))
    view['part_title'] = '写出差'
    return _with_feedback(view, {wrong[0]: '统一计算第二个函数值减第一个函数值，移项时保持差的方向。',
                                wrong[1]: '两个输入不同，不能把两个函数值直接消去。'})


def _sign_view(c):
    sign = c['delta_sign']
    flip = '<' if sign == '>' else '>'
    right = c['delta']+sign+'0'
    wrong = [c['delta']+flip+'0', c['delta']+'=0']
    threshold = '0' if c['output'] == 'sum' else '1'
    bounds = _range_tex(c['key'], c['key_range'])
    proof = [bounds, c['fkey']+c['sign_relation']+threshold]
    if c['output'] == 'product':
        proof.append(c['fa']+'>0')
    proof.append(c['delta']+'='+c['rhs']+sign+'0')
    return _with_feedback(choice_card(
        '利用题给条件判断差的正负', '先检查新输入是否落在题给条件的范围内，再结合差式判断正负。',
        '差式与题给条件', _lines([c['delta']+'='+c['rhs'], rf'{c["scope"]}\Rightarrow {c["sign_rule"]}']),
        '差的符号', right, wrong, _lines(proof)), {w: '把新输入代入题给条件后，还要检查差式前的负号和各因子的符号。' for w in wrong})


def _conclude_view(c):
    direction = c['direction']
    other = 'decreasing' if direction == 'increasing' else 'increasing'
    right = rf'{c["f"]}\ \text{{在}}\ {c["interval"]}\ \text{{上{WORD[direction]}}}'
    wrong = [rf'{c["f"]}\ \text{{在}}\ {c["interval"]}\ \text{{上{WORD[other]}}}',
             rf'{c["f"]}\ \text{{在}}\ {c["interval"]}\ \text{{上为常函数}}']
    comparison = c['call'](c['x1'])+('<' if direction == 'increasing' else '>')+c['call'](c['x2'])
    all_pairs = rf'\forall {c["x1"]},{c["x2"]}\in {c["interval"]},\ {c["x1"]}<{c["x2"]}\Rightarrow {comparison}'
    return _with_feedback(choice_card('回到单调性的定义', '比较结果对考察区间内任意两点都成立，由定义可得什么结论？',
        '任意两点的比较', all_pairs, '单调性', right, wrong, _lines([all_pairs, right])), {
        w: '函数值的严格大小关系决定了增减方向，也排除了常函数。' for w in wrong})


def phase_views(values):
    c = _context(values)
    description = values['description']
    if 'source' not in description:
        description = decode_value(description)
    c['source_variables'] = description['relation_variables']
    phase = values.get('phase')
    if phase == 'pair':
        return [_pair_view(c)]
    if phase == 'construct':
        views = [_normalize_view(c), _substitute_view(c)]
        if c['input'] == 'product':
            views.append(_check_view(c))
        if c['output'] == 'product':
            views.append(_positive_view(c))
        return views+[_difference_view(c)]
    if phase == 'sign':
        return [_sign_view(c)]
    if phase == 'conclude':
        return [_conclude_view(c)]
    return []


def presentation(values):
    views = phase_views(values)
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


def compile_abstract_monotonicity(seeds, interaction_id):
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
