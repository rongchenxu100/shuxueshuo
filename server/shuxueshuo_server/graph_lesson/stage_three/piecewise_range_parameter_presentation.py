"""Small mathematical steps and output-number-line decisions for FR-T3 P4."""

from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..piecewise_range_parameter import source
from . import interaction_graphs as drawing
from .evaluation_presentation import _choice, _lines
from .math_values import latex as tex
from .piecewise_range_presentation import _output_lines
from .range_presentation import _card, _image_choices
from .trajectory import decode_value


def _branch_context(description, role):
    """Keep the original branch number, formula and input boundary together."""
    branch = description[role]
    name = f'第 {branch["index"]} 段函数'
    qualifier = '不含参数' if role == 'fixed' else f'含参数 ${tex(description["parameter"])}$'
    formula = rf'{description["function"]}({tex(description["x"])})={tex(branch["expression"])}'
    condition = tex(branch['domain'].as_relational(description['x']))
    return {'name': name, 'label': f'{name}（{qualifier}）',
            'formula': formula, 'condition': condition,
            'math': _lines([formula, condition]), 'range': rf'R_{{{branch["index"]}}}',
            'caption': f'{name}（{qualifier}）：${formula}$，${condition}$。'}


def view(v):
    d = source(v['description'])
    phase, fixed = v['phase'], v['fixed_range']
    calc = v.get('calculation') or {}
    x, p, b, c, h = (d[k] for k in ('x', 'parameter', 'b', 'c', 'split'))
    X, P = tex(x), tex(p)
    q = d['varying']['expression']
    fixed_branch, varying_branch = (_branch_context(d, role) for role in ('fixed', 'varying'))
    fixed_context, varying_context = fixed_branch['math'], varying_branch['math']
    F, A = fixed_branch['name'], varying_branch['name']
    RF, RA = fixed_branch['range'], varying_branch['range']

    def card(title, question, left_label, left, right_label, right, proof, correct=None, wrong=()):
        interaction, expected = _choice(correct, list(wrong)) if correct else (None, None)
        out = _card(title, question, left_label, left, right_label, right,
                    '$$'+_lines(proof)+'$$', interaction, expected)
        branch = fixed_branch if phase in {'fixed', 'impossible'} else varying_branch
        out['derivation']['caption'] = branch['caption']
        if phase in {'decision', 'impossible', 'zero', 'sign', 'join', 'verify'}:
            out['derivation']['items'][0]['note'] = (
                f'${RF}$ 是{F} ${fixed_branch["formula"]}$（${fixed_branch["condition"]}$）的值域。')
        return out

    if phase == 'fixed':
        expr = d['fixed']['expression']
        if sp.degree(expr, x) == 2:
            poly = sp.Poly(expr, x); a, bb, cc = poly.all_coeffs()
            vertex, low = -bb/(2*a), cc-bb**2/(4*a)
            witness = vertex if vertex in d['fixed']['domain'] else d['fixed']['domain'].end
            proof = [rf'{tex(expr)}={tex(a)}({X}-({tex(vertex)}))^2+({tex(low)})',
                     (rf'{tex(vertex)}\in{tex(d["fixed"]["domain"])}' if witness == vertex else
                      rf'{X}\le{tex(witness)}<{tex(vertex)}\Rightarrow {d["function"]}({X})\ge {d["function"]}({tex(witness)})'),
                     rf'{d["function"]}({tex(witness)})={tex(expr.subs(x,witness))}',
                     rf'{X}\to-\infty\Rightarrow {d["function"]}({X})\to+\infty', rf'{RF}={tex(fixed)}']
        else:
            proof = [rf'{X}>{tex(h)}\Rightarrow {tex(expr)}>{tex(expr.subs(x,h))}', rf'{RF}={tex(fixed)}']
        out = card('先求不含参数那一段函数的值域',
                   f'当 ${fixed_branch["condition"]}$ 时，${fixed_branch["formula"]}$。这段函数的值域是什么？',
                   fixed_branch['label'], fixed_context, f'{F}的值域', rf'{RF}={tex(fixed)}', proof)
        out['interaction'], out['expected_answer'] = _image_choices(fixed, d['fixed']['domain'])
        return out
    if phase == 'decision':
        missing = d['target']-fixed
        if fixed.is_subset(d['target']) is False:
            return card('判断含参数这一段函数需要满足什么条件', f'{F}已经取到了题目要求的值域以外的值，改变{A}中的参数能把这些值去掉吗？',
                        f'{F}的值域与题目要求', _lines([rf'{RF}={tex(fixed)}', rf'V={tex(d["target"])}']),
                        '判断结果', r'\varnothing',
                        [rf'{RF}\not\subseteq V,\quad {RF}\subseteq {RF}\cup {RA}\Rightarrow {RF}\cup {RA}\ne V'],
                        '不能，参数无解', [f'能，只要限制{A}的值域就可以'])
        contained = missing == sp.S.EmptySet
        right = (rf'{RA}\subseteq {tex(d["target"])}' if contained else rf'{tex(missing)}\subseteq {RA}')
        return card('判断含参数这一段函数需要满足什么条件',
                    f'已知{F}的值域是 ${RF}$，题目要求整个函数的值域为 $V$。{A}的值域 ${RA}$ 应满足什么条件？',
                    f'{F}的值域与整个函数的目标值域', _lines([rf'{RF}={tex(fixed)}', rf'V={tex(d["target"])}']),
                    f'{A}的值域要求（含参数 ${P}$）', right,
                    [rf'{RF}={tex(fixed)},\quad V={tex(d["target"])}',
                     (rf'{RF}=V\Rightarrow ({RF}\cup {RA}=V\iff {RA}\subseteq V)' if contained else
                      rf'V\setminus {RF}={tex(missing)}\Rightarrow {right}')],
                    f'{A}的值都在 $V$ 内即可，无须再补充函数值' if contained else f'{A}必须取到{F}未取到的值，且不能超出 $V$',
                    [f'{A}的值域也必须恰好等于 $V$' if contained else f'{A}的值都在 $V$ 内即可，无须补齐'])
    if phase == 'impossible':
        return card('不含参数那一段函数已超出目标值域，参数无解', f'{F}不随参数改变，它已经取到了题目要求的值域以外的值。',
                    f'{F}的值域与整个函数的目标值域', _lines([rf'{RF}={tex(fixed)}', rf'V={tex(d["target"])}']),
                    '参数解集', r'\varnothing',
                    [rf'{RF}\setminus V={tex(fixed-d["target"])}\ne\varnothing', rf'\{{{P}:{RF}\cup {RA}=V\}}=\varnothing'])
    if phase == 'constraint':
        L = d['target'].start
        condition = rf'{tex(q)}\ge {tex(L)},\quad\forall {X}>{tex(h)}'
        return card('把这段函数的值域要求写成不等式', f'{A}不能取到 ${tex(L)}$ 以下的值。因此，对每个 ${varying_branch["condition"]}$，解析式应满足什么不等式？',
                    varying_branch['label'], varying_context, f'对每个 ${varying_branch["condition"]}$ 都成立', condition,
                    [rf'{RA}\subseteq{tex(d["target"])}\iff {condition}'],
                    '$'+condition+'$', ['$'+rf'{tex(q)}\le {tex(L)},\quad\forall {X}>{tex(h)}'+'$'])
    if phase == 'zero':
        zero_expr = q.subs(p, 0)
        return card('先检查参数等于零', f'当 ${P}=0$ 时，{A}的解析式变为 ${d["function"]}({X})={tex(zero_expr)}$，仍只取 ${varying_branch["condition"]}$。与{F}合起来，能取到任意实数吗？',
                    f'{F}的值域与参数为零时的{A}', _lines([rf'{RF}={tex(fixed)}', rf'{d["function"]}({X})={tex(zero_expr)},\quad {X}\le{tex(h)}']),
                    '这时的整个值域', tex(fixed | calc['zero_range']),
                    [rf'{X}\le{tex(h)}\Rightarrow {tex(zero_expr)}\ge{tex(zero_expr.subs(x,h))}',
                     rf'{P}=0:\quad {RA}={tex(calc["zero_range"])}',
                     rf'{RF}\cup {RA}={tex(fixed | calc["zero_range"])}\ne\mathbb R'],
                    '不能；两段都取不到足够小的负数', ['能；一次函数也能取到所有实数'])
    if phase == 'sign':
        return card('判断含参数那一段抛物线的开口方向', f'{F}的值域为 ${tex(fixed)}$。要使整个函数能取到任意小的值，{A}对应的抛物线应怎样开口？',
                    f'{F}的值域与{A}', _lines([rf'{RF}={tex(fixed)}', varying_context, rf'{P}\ne0']),
                    '参数的符号', rf'{P}<0',
                    [rf'{P}>0:\quad {tex(q)}={P}({X}+\frac{{{tex(b)}}}{{2{P}}})^2+{tex(c)}-\frac{{{tex(b*b)}}}{{4{P}}}',
                     rf'{P}>0\Rightarrow {RA}\text{{有下界，不能取到任意小的值}}',
                     rf'{P}<0,\quad {X}\to-\infty\Rightarrow {d["function"]}({X})\to-\infty'],
                    '向下开口，参数小于零', ['向上开口，参数大于零'])
    if phase == 'vertex':
        return card('检查顶点横坐标是否满足这段函数的条件', rf'已知 ${P}<0$，{A}只取 ${varying_branch["condition"]}$。顶点横坐标是否在这个范围内？',
                    f'{A}与参数条件', _lines([varying_context, rf'{P}<0']),
                    '顶点横坐标', rf'x_0={tex(calc["vertex"])}<0<{tex(h)}',
                    [rf'x_0=-\frac{{{tex(b)}}}{{2{P}}}={tex(calc["vertex"])}',
                     rf'{P}<0\Rightarrow x_0<0<{tex(h)}'],
                    f'满足{A}的条件，最大值在顶点取得', [f'不满足{A}的条件，只能看分界点'])
    if phase == 'image':
        right = rf'{RA}=(-\infty,{tex(calc["top"])}]'
        return card('写出含参数那一段函数的值域', f'{A}对应的抛物线向下开口，顶点横坐标满足 ${varying_branch["condition"]}$。这段函数的值域是什么？',
                    '已确定的顶点与开口', _lines([rf'{P}<0', rf'x_0={tex(calc["vertex"])}\le{tex(h)}', tex(q)]),
                    f'{A}的值域', right,
                    [rf'{tex(q)}={P}({X}-({tex(calc["vertex"])}))^2+({tex(calc["top"])})',
                     rf'M={tex(calc["top"])},\quad {X}\to-\infty\Rightarrow {d["function"]}({X})\to-\infty', right],
                    '$'+right+'$', ['$'+rf'{RA}=(-\infty,{tex(calc["top"])} )'+'$'])
    if phase == 'join':
        return card('让两段函数的值域合起来没有遗漏', rf'{F}的值域为 ${tex(fixed)}$，取不到 ${tex(calc["threshold"])}$。{A}的最大值至少是多少，合起来才能取到所有实数？',
                    f'{F}与{A}的值域', _lines([rf'{RF}={tex(fixed)}', rf'{RA}=(-\infty,{tex(calc["top"])}]']),
                    '没有遗漏的条件', rf'{tex(calc["top"])}\ge{tex(calc["threshold"])}',
                    [rf'(-\infty,{tex(calc["top"])}]\cup{tex(fixed)}=\mathbb R',
                     rf'\iff {tex(calc["top"])}\ge{tex(calc["threshold"])}'],
                    '$'+rf'{tex(calc["top"])}\ge{tex(calc["threshold"])}'+'$', ['$'+rf'{tex(calc["top"])}>{tex(calc["threshold"])}'+'$', '$'+rf'{tex(calc["top"])}\le{tex(calc["threshold"])}'+'$'])
    if phase == 'answer':
        answer = v['feasible_set']
        if calc['route'] == 'contained':
            premise = rf'{P}\in{tex(answer)}'
            proof = [rf'{P}\in{tex(answer)}\Rightarrow {RA}\subseteq{tex(d["target"])}',
                     rf'{RF}={tex(fixed)}\Rightarrow {RF}\cup {RA}={tex(d["target"])}']
            return card('回到原题，合并两段函数的值域',
                        rf'恒成立子问题已求得 ${P}\in{tex(answer)}$。回到原分段式，两段函数的值域并集是什么？',
                        '恒成立子问题返回的参数范围', premise, '原分段函数的值域',
                        rf'{RF}\cup {RA}={tex(d["target"])}', proof,
                        '$'+tex(d['target'])+'$', ['$'+tex(sp.S.Reals)+'$'])
        else:
            premise = _lines([rf'{P}<0', rf'{tex(calc["top"])}\ge{tex(calc["threshold"])}'])
            proof = [rf'{tex(calc["top"])}\ge{tex(calc["threshold"])}',
                     rf'{P}<0\Rightarrow -{tex(b*b/4)}\le {tex((calc["threshold"]-c)*p)}',
                     rf'{P}\ge{tex(calc["bound"])}', rf'{P}\in{tex(answer)}']
        out = card('求出参数范围', '把前面得到的条件合在一起，参数可以取哪些值？',
                   '已经得到的条件', premise, '参数范围', rf'{P}\in{tex(answer)}', proof)
        out['interaction'], out['expected_answer'] = _image_choices(answer, sp.S.Reals)
        return out
    if phase == 'verify':
        k = calc['bound']
        if calc['route'] == 'contained':
            residual = sp.factor(q.subs(p, k)-d['target'].start)
            proof = [rf'{P}={tex(k)}:\quad {tex(q.subs(p,k))}={tex(residual)}+({tex(d["target"].start)})\ge{tex(d["target"].start)}',
                     rf'{X}={tex(calc["witness"])}\Rightarrow {d["function"]}({X})={tex(d["target"].start)}',
                     rf'{P}>{tex(k)}:\quad {tex(q)}=({P}-{tex(k)}){X}^2+{tex(q.subs(p,k))}\ge{tex(d["target"].start)}',
                     rf'{RF}\cup {RA}={tex(d["target"])}']
            question = rf'将参数边界 ${P}={tex(k)}$ 代入{A}，仍只取 ${varying_branch["condition"]}$。函数值会不会小于 ${tex(d["target"].start)}$？'
            correct, wrong = '不会，等号可以保留', ['会，必须去掉这个端点']
        else:
            vx = calc['vertex'].subs(p, k)
            proof = [rf'{P}={tex(k)}:\quad x_0={tex(vx)}\le{tex(h)},\quad {d["function"]}({tex(vx)})={tex(calc["threshold"])}',
                     rf'{RA}=(-\infty,{tex(calc["threshold"])}],\quad {RF}\cup {RA}=\mathbb R',
                     rf'{P}=0:\quad R={tex(fixed | calc["zero_range"])}\ne\mathbb R', rf'{P}\in{tex(v["feasible_set"])}']
            question = rf'将 ${P}={tex(k)}$ 和 ${P}=0$ 分别代入{A}，再与{F}的值域合并。参数范围的两个端点分别能保留吗？'
            correct, wrong = f'保留 ${tex(k)}$，不保留 $0$', ['两个端点都保留', '两个端点都不保留']
        return card('代回原分段式检查参数范围的端点', question, f'{A}与已求出的参数范围',
                    _lines([varying_context, rf'{P}\in{tex(v["feasible_set"])}']), '核对结果',
                    rf'{P}\in{tex(v["feasible_set"])}', proof, correct, wrong)
    raise ValueError('piecewise_range_parameter.unknown_phase')


def presentation(values):
    card = view(values)
    left, right = card['derivation']['items']
    return {'formula_title': card['title'], 'formula_explanation': card['explanation'],
            'derivation_caption': card['derivation']['caption'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': left.get('note', ''),
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def _branch_graph(description, role, *, parameter_value=None, example=False):
    """Keep the source interval on exact curves and explicitly named examples."""
    branch = description[role]
    x, p = description['x'], description['parameter']
    expression = branch['expression']
    label = f'第 {branch["index"]} 段函数'
    if parameter_value is not None:
        expression = expression.subs(p, parameter_value)
        label += (f'示意：取 ${tex(p)}={tex(parameter_value)}$' if example
                  else f'（${tex(p)}={tex(parameter_value)}$）')
    condition = tex(branch['domain'].as_relational(x))
    caption = (f'{label}：$y={tex(expression)}$，${condition}$。'
               '深色为本段，浅色仅作参考；实心点可取，空心端点不取')
    title = f'第 {branch["index"]} 段函数'
    if parameter_value is not None:
        title += f'{"示意" if example else ""}（{p}={drawing.plain(parameter_value)}）'
    graph = drawing.interval_function_graph(
        expression, x, branch['domain'],
        title=f'{title} y={drawing.plain(expression)}，{x}∈{drawing.plain(branch["domain"])}',
        caption=caption)
    if graph['kind'] == 'linear':
        for mark, (point, _) in zip(graph['params']['points'], drawing.domain_points(branch['domain']), strict=True):
            mark['label'] = f'({drawing.short_label(point)}, {drawing.short_label(expression.subs(x, point))})'
    return graph


def _attach_graphs(part, values):
    phase = values['phase']
    if phase not in {'fixed', 'zero', 'sign', 'vertex', 'image'}:
        return
    d = source(values['description'])
    if phase == 'fixed':
        picture = _branch_graph(d, 'fixed')
    elif phase == 'zero':
        picture = _branch_graph(d, 'varying', parameter_value=sp.S.Zero)
    else:
        # Choose visible example axes at -h and h/2. These samples illustrate
        # the sign cases; neither the answer nor its proof uses their values.
        negative = d['b'] / (2*d['split'])
        if phase == 'sign':
            positive = -d['b'] / d['split']
            correct = part['expected_answer']['one_of'][0]
            for option in part['interaction']['options']:
                value = negative if option['value'] == correct else positive
                option['graph'] = _branch_graph(d, 'varying', parameter_value=value, example=True)
            part['completion_graphs'] = [deepcopy(option['graph']) for option in part['interaction']['options']]
            return
        picture = _branch_graph(d, 'varying', parameter_value=negative, example=True)
    part.update(graph=picture, completion_graph=deepcopy(picture))


def compile_step(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed['values'])
    card = view(values)
    board = deepcopy(card['derivation']); board['items'][1]['math'] = None
    interaction = deepcopy(card['interaction'])
    if 'options' in interaction:
        interaction['options'].sort(key=lambda r: sha256(f'{interaction_id}:{r["value"]}'.encode()).digest())
    part = {'id': interaction_id+'#1', 'title': card['title'], 'question': card['question'],
            'interaction': interaction, 'expected_answer': card['expected_answer'], 'feedback': card['feedback'],
            'submit_label': '确认这一步', 'stem_board': board, 'completion_board': card['derivation']}
    diagnostics = []
    try:
        _attach_graphs(part, values)
    except drawing.GraphUnavailable as exc:
        for option in interaction.get('options', []):
            option.pop('graph', None)
        diagnostics.append({'kind': 'graph_unavailable', 'reason': exc.reason})
    if values['phase'] == 'decision':
        d = source(values['description'])
        target = d['target']
        fixed_branch = _branch_context(d, 'fixed')
        varying_branch = _branch_context(d, 'varying')
        lines = _output_lines([{'branch': d['fixed'], 'image': values['fixed_range']}], target)
        lines[0]['label'] = _lines([
            rf'\text{{{fixed_branch["name"]}（不含参数）}}:\quad {fixed_branch["formula"]},\ {fixed_branch["condition"]}',
            rf'\text{{已求得的值域}}:\quad {fixed_branch["range"]}={tex(values["fixed_range"])}'])
        lines[1]['label'] = rf'\text{{题目要求整个函数的值域}}:\quad V={tex(target)}'
        part['condition_number_lines'] = lines
        missing = target-values['fixed_range']
        if missing != sp.S.EmptySet:
            extra = _output_lines([{'branch': {'index': 0}, 'image': missing}], target)[0]
            extra.update(bounds=lines[0]['bounds'], ticks=deepcopy(lines[0]['ticks']))
            extra['label'] = rf'\text{{{varying_branch["name"]}必须补齐的函数值}}:\quad {tex(missing)}'
            part['completion_number_line'] = extra
    return {'parts': [part], 'diagnostics': diagnostics}
