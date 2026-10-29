"""Local M9 cards projected only from the verified evaluation evidence."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_evaluation import _check_source, _set as evaluation_set
from ..stage_one.function_domain import expression_latex
from .abstract_domain_presentation import _answer_options, _derivation, _set_latex
from .evaluation_algebra import rational_sum_derivation
from .math_values import latex
from .trajectory import decode_value


PHASES = ('input', 'inner', 'substitute', 'domain', 'conclusion',
          'trial', 'constant', 'pairing', 'leftovers', 'sum')


def phase_flags(description, result):
    kind, defined = result['kind'], result.get('defined', True)
    value = kind in ('scalar_value', 'expression_with_domain')
    return {
        'has_input': kind != 'finite_sum',
        'has_inner': value and defined and len(result.get('calls', [])) > 1,
        'has_substitute': value and defined and bool(result.get('calls')),
        'has_domain': kind == 'expression_with_domain' or not defined and kind != 'finite_sum',
        'has_conclusion': value,
        'has_trial': kind == 'constant_check' and defined and len(result.get('trials', [])) > 1
                     and not isinstance(result['domain'], sp.FiniteSet),
        'has_constant': kind == 'constant_check',
        'has_pairing': kind == 'finite_sum' and defined and result.get('pair_count', 0) > 0,
        'has_leftovers': kind == 'finite_sum' and defined and bool(result.get('leftovers')),
        'has_sum': kind == 'finite_sum',
    }


def _ast(ast, description, variable='u'):
    names = {row['function_ref']: row['function_name'] for row in description['functions']}
    if description.get('variable_ref'):
        names[description['variable_ref']] = description['variable']

    def replace(node):
        if not isinstance(node, list):
            return node
        if node[:1] == ['function_call']:
            rendered = names.get(node[1][1], node[1][1].rsplit(':', 1)[-1])
            rendered += r'\left(' + _ast(node[2], description, variable) + r'\right)'
            return ['ref', rendered, 'scalar']
        return [replace(child) for child in node]
    return expression_latex(replace(ast), variable, names=names)


def _lines(items):
    items = list(dict.fromkeys(items))
    return (r'\begin{gathered}' + r'\\'.join(items) + r'\end{gathered}') if len(items) > 1 else (items[0] if items else r'\text{无限制}')


def _math(*lines):
    return '\n'.join(f'${line}$' for line in lines if line)


def _call_equation(call):
    return (rf'{call["function_name"]}\left({latex(call["input"])}\right)='
            f'{call.get("substitution_latex", latex(call["substitution"]))}={latex(call["output"])}')


def _choice(answer, alternatives=()):
    answers = [answer]
    for value in alternatives:
        if value != answer and value not in answers:
            answers.append(value)
    return {'type': 'choice', 'field': 'answer', 'options': [
        {'value': f'o{index}', 'label': value} for index, value in enumerate(answers, 1)]}, {'one_of': ['o1']}


def _value_choices(value):
    # Nonzero constant offsets stay unequal on every nonempty legal domain.
    # Negating a symbolic value may instead be equivalent on a finite domain.
    candidates = [value + 1, value - 1]
    unique = [value]
    for item in candidates:
        if all(sp.cancel(item - prior) != 0 for prior in unique):
            unique.append(item)
        if len(unique) == 3:
            break
    return _choice(f'${latex(unique[0])}$', [f'${latex(item)}$' for item in unique[1:]])


def _card(title, question, left_label, left, right_label, right, explanation,
          interaction=None, expected=None, *, note='', feedback=None):
    return {'title': title, 'question': question,
            'interaction': interaction or {'type': 'read'}, 'expected_answer': expected or {},
            'feedback': {'answer': feedback if feedback is not None else explanation}, 'explanation': explanation,
            'derivation': _derivation(title, left_label, left, right_label, right, note=note)}


def _term_math(term, description):
    if term.get('function_ref') and term.get('input') is not None:
        name = next(row['function_name'] for row in description['functions']
                    if row['function_ref'] == term['function_ref'])
        return rf'{name}\left({latex(term["input"])}\right)'

    def indices(ast):
        if not isinstance(ast, list):
            return ast
        if ast[:1] == ['ref'] and ast[2] == 'scalar' and term.get('index') is not None:
            return ['number', str(term['index'])]
        return [indices(child) for child in ast]
    return _ast(indices(term['input_ast']), description)


def _pairing_diagram(result, description, focus):
    """Project verified occurrence identities; both phases keep the same layout."""
    if not result.get('pair_count'):
        return None

    def sample(rows):
        return rows if len(rows) <= 3 else rows[:2] + rows[-1:]

    pairing = result['pairing']
    pairs = [{
        'left_id': pair['left_id'], 'right_id': pair['right_id'],
        'left_math': _term_math({'function_ref': pairing['function_ref'], 'input': pair['left_input']}, description),
        'right_math': _term_math({'function_ref': pairing['function_ref'], 'input': pair['right_input']}, description),
    } for pair in sample(result['pairs'])]
    by_id = {term['occurrence_id']: term for term in result['terms']}
    leftovers = [{'id': ident, 'math': _term_math(by_id[ident], description)}
                 for ident in sample(result['leftovers'])]
    return {'focus': focus, 'pair_value': latex(pairing['constant']),
            'pairs': pairs, 'omitted_pairs': len(result['pairs']) - len(pairs),
            'leftovers': leftovers, 'omitted_leftovers': len(result['leftovers']) - len(leftovers)}


def _call_card(call, description, *, inner=False):
    name = call['function_name']
    function = next(row for row in description['functions'] if row['function_ref'] == call['function_ref'])
    variable = function.get('variable', 'u')
    input_math = latex(call['input'])
    rule = _ast(call['rule_ast'], description, variable)
    title = (f'先计算内层 {name}' if call.get('depth', 0) > 0 else f'先计算 {name}') if inner else f'整体代入 {name}'
    interaction, expected = _value_choices(call['output'])
    return _card(title, f'把完整输入 ${input_math}$ 放进 ${name}$ 的对应规则，计算输出。',
                 '完整输入与对应规则', _lines([rf'\text{{输入：}}{input_math}', rf'{name}({variable})={rule}']),
                 '本层输出', rf'{name}\left({input_math}\right)={latex(call["output"])}',
                 _math(_call_equation(call)), interaction, expected,
                 feedback='把完整输入替换规则中的每个自变量位置；保留括号后，再按运算顺序计算。')


def _constraints(result, description=None):
    rows = []
    if description and description.get('input_domain_ast', ['real']) != ['real']:
        rows.append(latex(result.get('variable', sp.Symbol('x'))) + r'\in '
                    + _domain_latex(evaluation_set(description['input_domain_ast'])))
    for row in result.get('constraints', []):
        expression = latex(row['expression'])
        rows.append(rf'{expression}\ne0' if row['kind'] == 'nonzero'
                    else rf'{expression}\in {_set_latex(row["allowed"])}')
    return _lines(rows)


def _domain_latex(domain):
    excluded = sp.S.Reals - domain
    if isinstance(excluded, sp.FiniteSet) and excluded:
        return r'\mathbb{R}\setminus' + latex(excluded)
    return _set_latex(domain)


def _domain_card(description, result, target, variable, domain):
    calls = result.get('calls', [])
    # The outer input already includes the restrictions of every nested call.
    outer = [call for call in calls if not any(
        call['call_id'].startswith(parent['call_id'] + '/input')
        for parent in calls if parent is not call)]
    functions = {row['function_ref']: row for row in description['functions']}
    inputs, memberships = [], []
    guards = result.get('constraints', [])
    for call in outer:
        input_math = _ast(call['input_ast'], description)
        inputs.append(input_math + r'\text{ 有意义}')
        input_guards = [row for row in guards if row['path'].startswith(call['call_id'] + '/input/')]
        if input_guards:
            inputs.append(_constraints({'constraints': input_guards}))
        function = functions[call['function_ref']]
        bound = sp.Symbol('_function_input', real=True)
        _, natural = _check_source(function['expression_ast'], functions, {}, bound, argument=bound)
        allowed = natural & evaluation_set(function.get('input_domain_ast', ['real']))
        name = call['function_name']
        memberships.append(rf'D_{{{name}}}={_domain_latex(allowed)}')
        excluded = sp.S.Reals - allowed
        condition = (rf'{input_math}\ne {latex(next(iter(excluded)))}'
                     if isinstance(excluded, sp.FiniteSet) and len(excluded) == 1
                     else rf'{input_math}\in D_{{{name}}}')
        memberships.append(condition)
    # These are conditions on the whole target, not the original function's domain.
    extra = []
    if description.get('input_domain_ast', ['real']) != ['real']:
        extra.append(('题设范围', rf'{variable}\in {_domain_latex(evaluation_set(description["input_domain_ast"]))}'))
    outside = [row for row in guards if not any(
        row['path'] == call['call_id'] + '/declared-domain'
        or row['path'].startswith(call['call_id'] + '/input/')
        or row['path'].startswith(call['call_id'] + '/body/') for call in outer)]
    if outside:
        extra.append(('目标式限制', _constraints({'constraints': outside})))
    options = _answer_options(result['domain'], sp.S.Reals, {})
    options[0]['label'] = f'${domain}$'
    proof = [*inputs, *memberships, *(math for _, math in extra)]
    card = _card('确定定义域', f'同时满足这两个条件时，${variable}$ 的取值范围是什么？',
                 '目标函数' if description['expression_ast'][0] == 'function_call' else '目标表达式', target,
                 f'定义域（${variable}$ 的取值范围）', domain,
                 _math(_lines(proof) + rf'\Longrightarrow {variable}\in {domain}'),
                 {'type': 'choice', 'field': 'answer', 'options': options}, {'one_of': ['o1']},
                 note='；'.join(f'{label}：${math}$' for label, math in extra),
                 feedback='输入表达式本身有意义，并且属于原函数的定义域，这两个条件必须同时满足；约分不能删去原有限制。')
    card['derivation']['condition_groups'] = [
        {'label': '输入表达式有意义', 'math': _lines(inputs)},
        {'label': f'输入属于 ${outer[0]["function_name"]}$ 的定义域' if len(outer) == 1 else '输入属于各自函数的定义域',
         'math': _lines(memberships)},
    ]
    return card


def _target_substitution(description, calls, *, input_value=None, output=None):
    """Render the original operator tree, preserving every call occurrence."""
    by_path = {call['call_id']: call for call in calls}

    def has_call(ast):
        return isinstance(ast, list) and (ast[:1] == ['function_call'] or any(has_call(child) for child in ast[1:]))

    def project(ast, path='target', *, expanded=False):
        if not isinstance(ast, list):
            return ast
        if ast[:1] == ['function_call']:
            call = by_path[path]
            if expanded:
                body = call.get('substitution_latex', latex(call['substitution']))
                return ['ref', rf'\left({body}\right)', 'scalar']
            argument = project(ast[2], path + '/input')
            if input_value is not None and not has_call(ast[2]):
                argument = ['ref', latex(call['input']), 'scalar']
            return [ast[0], ast[1], argument]
        if ast[:2] == ['ref', description.get('variable_ref')] and input_value is not None:
            return ['ref', rf'\left({latex(input_value)}\right)', 'scalar']
        return [ast[0], *(project(child, path + '/' + str(index), expanded=expanded)
                         for index, child in enumerate(ast[1:], 1))]

    original = _ast(project(description['expression_ast']), description)
    substituted = _ast(project(description['expression_ast'], expanded=True), description)
    return _lines([original, '=' + substituted, *(['=' + latex(output)] if output is not None else [])])


def _composite_input_card(description, target):
    """Describe syntactic input dependencies, without evaluated intermediate values."""
    ast = description['expression_ast']
    calls = []

    def collect(node):
        if not isinstance(node, list):
            return False
        child_call = False
        for child in node[1:]:
            child_call = collect(child) or child_call
        if node[:1] == ['function_call']:
            calls.append((node, child_call))
            return True
        return child_call

    collect(ast)
    if not any(nested for _, nested in calls):
        return None
    names = {row['function_ref']: row['function_name'] for row in description['functions']}
    chain, leaf = [], ast
    while isinstance(leaf, list) and leaf[:1] == ['function_call']:
        chain.insert(0, leaf)
        leaf = leaf[2]
    if len(chain) == len(calls):
        def order_label(nodes):
            current, phrases = leaf, []
            for index, node in enumerate(nodes):
                name = names[node[1][1]]
                phrases.append((f'先把 ${_ast(current, description)}$ 代入 ${name}$' if index == 0 else
                                f'再把 ${_ast(current, description)}$ 的结果代入 ${name}$'))
                current = ['function_call', node[1], current]
            return '，'.join(phrases)

        correct = order_label(chain)
        reversed_order = order_label(chain[::-1])
        wrong = (reversed_order if reversed_order != correct else
                 f'每一层都直接代入 ${_ast(leaf, description)}$，不使用上一层的结果')
        right = _ast(leaf, description) + ''.join(
            rf'\xrightarrow{{{names[node[1][1]]}}}' + _ast(node, description) for node in chain)
    else:
        correct = '先计算内层函数，再按原式组合结果，作为外层函数的完整输入'
        wrong = '先把原来的自变量直接代入外层函数，再计算内层函数'
        # An input such as g(x)+1 is not a direct g→f chain: keep the +1.
        right = _lines([_ast(node[2], description) + rf'\xrightarrow{{{names[node[1][1]]}}}'
                        + _ast(node, description) for node, _ in calls])
    interaction, expected = _choice(correct, [wrong])
    return _card('确定代入顺序', f'求 ${target}$，应按什么顺序代入？',
                 '本目标', target, '由内向外的代入关系', right,
                 _math(right),
                 interaction, expected,
                 feedback='先看最里面的函数括号：先算内层，再用它的结果组成外层的完整输入。')


def phase_views(values):
    description, result, phase = values['description'], values['evaluation_result'], values['phase']
    calls, defined = result.get('calls', []), result.get('defined', True)
    target = _ast(description['expression_ast'], description) if description['kind'] != 'finite_sum' else ''
    domain = _domain_latex(result['domain'])
    variable = latex(result.get('variable', sp.Symbol('x')))
    if phase == 'input':
        composite = _composite_input_card(description, target)
        if composite:
            return [composite]
        interaction, expected = _choice('把括号内的完整输入，代入对应函数的全部自变量位置',
                                       ['把括号内的内容当作函数值，反过来求自变量'])
        first = calls[0] if calls else None
        right = (_lines([rf'\text{{先算 }}{first["function_name"]}', _ast(first['input_ast'], description)])
                 if first else target)
        flow = (_ast(first['input_ast'], description) + rf'\xrightarrow{{{first["function_name"]}}}'
                + _ast(['function_call', ['ref', first['function_ref'], 'function'], first['input_ast']], description)
                if first else target)
        return [_card('明确完整输入', '观察函数调用：代入时应该替换什么？',
                      '本目标', target, '首先处理的完整输入', right,
                      _math(flow), interaction, expected,
                      feedback='括号里的内容是输入；把完整输入代入对应函数的全部自变量位置。')]
    if phase in ('inner', 'substitute'):
        selected = calls[:-1] if phase == 'inner' else calls[-1:]
        return [_call_card(call, description, inner=phase == 'inner') for call in selected]
    if phase == 'domain':
        return [_domain_card(description, result, target, variable, domain)]
    if phase == 'conclusion':
        if not defined:
            return [_card('说明无定义的原因', '这些原式限制能同时满足吗？', '原式限制', _constraints(result, description),
                          '结论', r'\text{无合法输入，原目标无定义}',
                          _math(_constraints(result, description) + r'\Longrightarrow D=\varnothing',
                                target + r'\text{ 无定义}'))]
        answer = result['expression']
        right = latex(answer)
        if result['kind'] == 'expression_with_domain':
            right = _lines([right, rf'{variable}\in {domain}'])
        interaction, expected = _choice('写出代入后的表达式，并注明自变量的取值范围', ['只写化简后的式子，原限制可以删除']) if result['kind'] == 'expression_with_domain' else _value_choices(answer)
        return [_card('返回本目标结果', '确认本目标的结果。', '本目标', target, '结果', right,
                      _math(rf'{target}={latex(answer)}',
                            rf'{variable}\in {domain}' if result['kind'] == 'expression_with_domain' else ''),
                      interaction, expected, feedback='核对原目标的函数调用顺序与输入限制。')]
    if phase == 'trial':
        rows = result.get('trials', [])
        trial_cards = []
        for index, row in enumerate(rows, 1):
            substituted = _target_substitution(description, row['calls'], input_value=row['input'])
            interaction, expected = _value_choices(row['total'])
            trial_cards.append(_card('代入试算', f'取合法输入 ${variable}={latex(row["input"])}$，代入各项后得到多少？',
                                     f'试算 {index}：整体代入', substituted, '本次试算结果', latex(row['total']),
                                     _math(_target_substitution(description, row['calls'], input_value=row['input'], output=row['total'])),
                                     interaction, expected, feedback='依次代入每个函数，再按原目标中的运算合并结果。'))
        evidence = _lines([rf'{variable}={latex(row["input"])}\Rightarrow {latex(row["total"])}' for row in rows])
        unequal = len({row['total'] for row in rows}) > 1
        answer = '两个合法输入得到不同输出，已经反证不是定值' if unequal else '只能提出猜想，还要在完整合法范围内验证'
        interaction, expected = _choice(answer, ['仅凭这几个输入就断言恒为定值'])
        return trial_cards + [_card('观察试算结果', '试算这些合法输入后，能得到什么结论？',
                      '已验证的试算', evidence, '下一步', r'\text{整理反例证据}' if unequal else r'\text{验证一般输入}',
                      _math(evidence, r'\Longrightarrow\text{不是定值}' if unequal else r'\text{尚需恒等验证}'),
                      interaction, expected, feedback='有限试算不能替代完整合法范围上的证明；不同输出则可以反证不是定值。')]
    if phase == 'constant':
        if not defined:
            right, label = r'\text{没有合法输入}', '不能确定唯一的定值'
        elif result.get('is_constant'):
            right, label = latex(result['value']), '是定值'
        else:
            right = _lines([rf'{variable}={latex(row["input"])}\Rightarrow {latex(row["output"])}' for row in result['witness']])
            label = '不是定值'
        interaction, expected = _choice(label, ['不是定值' if label == '是定值' else '是定值']) if defined else ({'type': 'read'}, {})
        substitutions = _target_substitution(description, calls) if defined else rf'{variable}\in {domain}'
        proof = [rf'{variable}\in {domain}']
        if not defined:
            proof.append(r'\text{无定义}')
        elif result.get('is_constant'):
            if result.get('proof', {}).get('kind') == 'complete_finite_domain':
                proof.extend(rf'\left.{target}\right|_{{{variable}={latex(point)}}}={latex(result["value"])}'
                             for point in result['proof']['inputs'])
            else:
                expanded = (rational_sum_derivation(description, calls, result['value'])
                            if result.get('proof', {}).get('kind') == 'rational_identity' else None)
                proof.append(expanded or _target_substitution(description, calls, output=result['value']))
        else:
            proof.extend(rf'\left.{target}\right|_{{{variable}={latex(row["input"])}}}={latex(row["output"])}'
                         for row in result['witness'])
            a, b = result['witness']
            proof.append(rf'{latex(a["output"])}\ne {latex(b["output"])}\Longrightarrow\text{{不是定值}}')
        return [_card('验证定值', '在完整合法范围内进行恒等变形，或用两个合法输入给出不同输出。结论是什么？',
                      '一般输入的代入式', substitutions, '判断结果', _lines([rf'\text{{{label}}}', right]),
                      _math(*proof), interaction, expected,
                      feedback='在完整合法范围内化简一般输入的表达式；若要否定恒定，需要两个合法输入给出不同输出。')]
    if phase == 'pairing':
        pairing = result['pairing']
        pair, count = result['pairs'][0], result['pair_count']
        name = next(row['function_name'] for row in description['functions'] if row['function_ref'] == pairing['function_ref'])
        example = rf'{latex(pair["left_input"])}\longleftrightarrow {latex(pair["right_input"])}'
        interaction, expected = _choice(f'{count} 对；每个出现项只计一次', [f'{count + 1} 对；把剩余单项也当作一对'])
        card = _card('配对计数', '按互为倒数的输入配对，核对所有出现项恰好使用一次。共有多少对？',
                      '配对依据', _lines([example, rf'\text{{每对和}}={latex(pairing["constant"])}']),
                      '配对与单列项', rf'{result["term_count"]}=2\times {count}+{result["leftover_count"]}',
                      _math(rf'{name}(t)+{name}\left(\frac{{1}}{{t}}\right)={latex(pairing["constant"])},\quad t\in {_domain_latex(pairing["domain"])}',
                            rf'{result["term_count"]}=2\times {count}+{result["leftover_count"]}'), interaction, expected,
                      feedback='每个出现项只能使用一次；先找互为倒数的输入，再留下没有配对的项。')
        card['derivation']['pairing_diagram'] = _pairing_diagram(result, description, 'pairs')
        return [card]
    if phase == 'leftovers':
        ids = set(result['leftovers'])
        terms = [term for term in result['terms'] if term['occurrence_id'] in ids]
        total = sum((term['value'] for term in terms), sp.S.Zero)
        # The displayed source terms retain multiplicity. Large lists use the
        # verified occurrence count rather than an unreadable formula wall.
        left = '+'.join(_term_math(term, description) for term in terms[:4])
        if len(terms) > 4:
            left += rf'+\cdots\quad\text{{共 {len(terms)} 个单列项}}'
        proof = []
        for term in terms[:4]:
            substitution = ''
            if term.get('function_ref') and term.get('input') is not None:
                function = next(row for row in description['functions'] if row['function_ref'] == term['function_ref'])
                substitution = _ast(function['expression_ast'], description, rf'\left({latex(term["input"])}\right)') + '='
            proof.append(f'{_term_math(term, description)}={substitution}{latex(term["value"])}')
        if len(terms) > 1:
            proof.append((('+'.join(rf'\left({latex(term["value"])}\right)' for term in terms) + '=' + latex(total))
                          if len(terms) <= 4 else rf'\text{{单列项之和}}={latex(total)}'))
        interaction, expected = _value_choices(total)
        card = _card('计算剩余项', '没有进入二元配对的项各算一次，它们的和是多少？',
                      '单列项的输入与输出', left, '单列项之和', latex(total),
                      _math(*proof), interaction, expected,
                      feedback='没有计入配对和的出现项各算一次，再把它们相加。')
        if diagram := _pairing_diagram(result, description, 'leftovers'):
            card['derivation']['pairing_diagram'] = diagram
        return [card]
    if phase == 'sum':
        if not defined:
            return [_card('说明原和无定义', '原和的每一个出现项都有定义吗？', '要求', r'\text{所有出现项均有定义}',
                          '结论', r'\text{原和无定义}', _math(r'\exists\,\text{无定义项}\Longrightarrow S\text{ 无定义}'))]
        leftovers = set(result.get('leftovers', []))
        remainder = sum((row['value'] for row in result['terms'] if row['occurrence_id'] in leftovers), sp.S.Zero)
        if result.get('pair_count'):
            formula = rf'{result["pair_count"]}\times {latex(result["pairing"]["constant"])}+{latex(remainder)}'
        else:
            # Group equal numerical values by count, without dropping occurrences.
            counts = {}
            term_values = ([row[3] for row in result['occurrence_certificate']]
                           if 'occurrence_certificate' in result else [row['value'] for row in result['terms']])
            for value in term_values:
                counts[value] = counts.get(value, 0) + 1
            formula = ('+'.join((rf'{count}\times ' if count > 1 else '') + rf'\left({latex(value)}\right)'
                                for value, count in counts.items()) or '0')
        interaction, expected = _value_choices(result['total'])
        return [_card('合计', '把配对的贡献和剩余项相加，得到原和。', '已经核对的各部分', formula,
                      '原和', latex(result['total']), _math(rf'S={formula}={latex(result["total"])}'),
                      interaction, expected, feedback='将各对的贡献和单列项相加，每个出现项恰好计入一次。')]
    raise ValueError('evaluation.unknown_phase:' + str(phase))


def presentation(values):
    views = phase_views(values)
    if not views:
        raise ValueError('evaluation.empty_phase')
    board = views[-1]['derivation']
    left, right = board['items']
    return {'evaluation_title': views[0]['title'],
            'evaluation_explanation': '\n'.join(view['explanation'] for view in views),
            'derivation_caption': board['caption'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': left.get('note', ''),
            'derivation_right_label': right['label'], 'derivation_right_math': right['math'],
            'condition_groups': board.get('condition_groups'),
            'pairing_diagram': board.get('pairing_diagram')}


def compile_evaluation(seeds, interaction_id):
    (seed,) = seeds
    views = phase_views(decode_value(seed['values']))
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        interaction = deepcopy(view['interaction'])
        if interaction['type'] == 'choice':
            interaction['options'].sort(key=lambda option: sha256(
                f'{interaction_id}:{index}:{option["value"]}'.encode()).digest())
        parts.append({'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                      'interaction': interaction, 'expected_answer': view['expected_answer'],
                      'feedback': view['feedback'], 'submit_label': '确认判断', 'stem_board': board,
                      'completion_board': deepcopy(view['derivation'])})
    return {'parts': parts, 'diagnostics': []}
