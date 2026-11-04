"""FM-T1 teaching views shared by authored courses and photo lessons."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_monotonicity import components
from .absolute_graph_presentation import choice_card, ends, segment
from .evaluation_presentation import _lines
from .interaction_graph_contract import validate_graph
from .interaction_graphs import short_label
from .math_values import latex
from .monotonicity_runtime import interval_latex
from .trajectory import decode_value


def _sample_y(expr, x, v, transform):
    y = float(expr.subs(x, v))
    if transform == 'sqrt':
        return max(0, y)**.5
    if transform == 'reciprocal_sqrt':
        return None if y <= 0 else 1/y**.5
    return y


def _interval_mark(region, direction=None):
    bounds, closed = ends(region)
    label = ('(' if region.left_open else '[') + ', '.join(
        short_label(v) if v.is_finite else '-∞' if v < 0 else '+∞'
        for v in (region.inf, region.sup)) + (')' if region.right_open else ']')
    return {'from': bounds[0], 'to': bounds[1], 'left_closed': closed[0], 'right_closed': closed[1],
            'label': label, 'trend': {None: 'pending', 1: 'increasing', -1: 'decreasing', 0: 'constant'}[direction]}


def _layer_names(model):
    # A photographed function may use u or v as its independent variable.
    return [name for name in ('u', 'v', 'w', 'z')
            if name not in (str(model['variable']), model['function'])][:2]


def graph_for(model, *, inner=False, highlight=None, after_layer=None, directions=None, focus=None):
    """Draw the actual function on each connected component, never across a hole."""
    x, domain = model['variable'], model['effective_domain']
    name = model['function']
    anchors = {sp.S.Zero}
    anchors.update(v for row in model['partition'] for v in (row['interval'].inf, row['interval'].sup) if v.is_finite)
    anchors.update(b['axis'] for b in model['branches'] if b['axis'] is not None)
    low, high = float(min(anchors))-1, float(max(anchors))+1
    if high-low < 4:
        low, high = (low+high)/2-2, (low+high)/2+2
    segments, ys = [], [0.0]
    for branch in model['branches']:
        for region in components(domain & branch['domain']):
            item = segment(branch['expression'], region, x)
            transform = after_layer or (model['family'] if model['family'] in ('sqrt', 'reciprocal_sqrt') and not inner else 'identity')
            item['transform'] = transform
            segments.append(item)
            a, b = max(low, float(region.inf)), min(high, float(region.sup))
            # Interior probes set only a viewing window; all mathematical decisions use exact certificates.
            for v in [a+(b-a)*j/24 for j in range(1, 24)]:
                y = _sample_y(branch['expression'], x, v, transform)
                if y is not None:
                    ys.append(y)
            for v in anchors:
                if v in region and transform != 'reciprocal_sqrt':
                    y = _sample_y(branch['expression'], x, float(v), transform)
                    if y is not None:
                        ys.append(y)
    bottom, top = min(ys), max(ys)
    pad = max(1, (top-bottom)*.12)
    interval = [float(v) if v.is_finite else None for v in (domain.inf, domain.sup)]
    closed = [v.is_finite and v in domain for v in (domain.inf, domain.sup)]
    # Keep titles plain for SVG accessibility; KaTeX is reserved for boards.
    title = ('开方后的中间函数' if after_layer == 'sqrt' else
             '内层函数 '+_layer_names(model)[0] if inner and model['family'] in ('sqrt', 'reciprocal_sqrt') else
             f'原函数 {name}')
    params = {'segments': segments, 'bounds': [low, high, bottom-pad, top+pad],
              'interval': interval, 'interval_closed': closed, 'points': [],
              'xTicks': [[float(v), short_label(v)] for v in sorted(anchors)],
              'variable': str(x), 'title': title,
              'description': '只绘制允许输入范围内的曲线；实心端点取到，空心端点不取。'}
    if highlight is not None:
        params['highlights'] = [{'from': ends(r)[0][0], 'to': ends(r)[0][1],
                                'left_closed': not r.left_open, 'right_closed': not r.right_open} for r in highlight]
    marks = [_interval_mark(r, d) for r, d in (directions or [])]
    if focus is not None:
        marks.append(_interval_mark(focus))
    if marks:
        params['interval_marks'] = marks
        params['description'] += '区间标在图下方；问号对应当前待判断的一段，箭头表示已确认的增减。'
    caption = (title+'；着色区间是当前小问，问号处待判断。' if focus is not None else
               title+'；着色曲线对应当前讨论区间，箭头表示已确认的增减方向。' if highlight is not None and marks else
               title+'；图中箭头与区间对应前面已确认的增减方向。' if marks else
               title+'；曲线的截断不表示定义域有端点。')
    return validate_graph({'kind': 'piecewise_curve', 'params': params, 'caption': caption})


def arrow(direction):
    return {1: r'\uparrow', -1: r'\downarrow', 0: r'\text{常值}'}[direction]


def layer_rule(operation):
    return '开方保序' if operation == 'sqrt' else '正数取倒数反序'


def phase_views(values):
    m, phase = values['monotonicity_result'], values['phase']
    x, p, domain = m['variable'], m['expression'], m['effective_domain']
    variable, function = latex(x), m['function']
    u, v = _layer_names(m)
    formula = rf'{m["function"]}({latex(x)})={latex(p)}'
    views = []
    if phase == 'domain':
        view = choice_card('确定讨论范围', '这道题允许在哪些输入上讨论单调性？', '原函数', formula,
                           '有效定义域', latex(domain), [r'\varnothing', r'\{0\}'],
                           rf'D={latex(domain)}')
        views.append(view)
    elif phase == 'square':
        b = m['branches'][0]
        q, a, axis = b['expression'], b['coefficients'][0], b['axis']
        square = values['square']
        if axis is None or sp.expand(square-q) != 0:
            raise ValueError('monotonicity.square_identity_invalid')
        k = q.subs(x, axis)
        name = u if m['family'] in ('sqrt', 'reciprocal_sqrt') else rf'{function}({variable})'
        wrong = [a*(x+axis)**2+k, a*(x-axis)**2-k, -a*(x-axis)**2+k, a*(x-axis-1)**2+k]
        wrong = list(dict.fromkeys(latex(v) for v in wrong if sp.expand(v-q) != 0))[:3]
        view = choice_card('把二次函数配成顶点式',
                           f'把二次式配成 $a({variable}-h)^2+k$ 的形式，选择与原式相等的顶点式。',
                           '待配方的二次式', rf'{name}={latex(q)}', '顶点式', latex(square), wrong,
                           rf'{name}={latex(q)}={latex(square)}')
        view['completion_graph'] = graph_for(m, inner=True)
        views.append(view)
    elif phase == 'inner':
        name = u if m['family'] in ('sqrt', 'reciprocal_sqrt') else rf'{function}({variable})'
        confirmed = []
        for row in m['partition']:
            b, r = m['branches'][row['branch']], row['interval']
            q = b['expression']
            a = b['coefficients'][0]
            if b['axis'] is not None:
                kind = '二次函数'
                axis = b['axis']
                square = a*(x-axis)**2+q.subs(x, axis)
                left = _lines([rf'{name}={latex(square)}', rf'{variable}\in {latex(r)}', rf'\text{{对称轴 }}{variable}={latex(axis)}'])
                why = '结合开口方向、对称轴和当前输入区间，判断函数的增减。'
            else:
                kind = '一次函数' if b['coefficients'][1] != 0 else '常值函数'
                left = _lines([rf'{name}={latex(q)}', rf'{variable}\in {latex(r)}'])
                why = '根据一次项系数判断；系数为零时是常值。'
            direction = row['inner_direction']
            view = choice_card('判断'+kind+'的增减', why, kind+'与区间', left,
                               '从左向右', arrow(direction),
                               [arrow(d) for d in (1, -1, 0)],
                               _lines([left, rf'{name}\;{arrow(direction)}']))
            view['part_title'] = kind+rf'在 ${latex(r)}$ 上的增减'
            view['graph'] = graph_for(m, inner=True, focus=r, directions=confirmed)
            confirmed.append((r, direction))
            view['completion_graph'] = graph_for(m, inner=True, directions=confirmed)
            views.append(view)
    elif phase == 'composition':
        for row in m['partition']:
            if not row['layers']:
                continue
            r = row['interval']
            for layer in row['layers']:
                root = layer['operation'] == 'sqrt'
                rule = layer_rule(layer['operation'])
                operand = rf'{u}={latex(m["branches"][row["branch"]]["expression"])}' if root else rf'{v}=\sqrt{{{u}}}'
                condition = rf'{u}>0' if layer['input_sign'] == 'positive' else rf'{u}\geq0'
                if not root:
                    condition = rf'{v}>0'
                output = rf'{v}=\sqrt{{{u}}}' if root else rf'{function}({variable})=\frac1{v}'
                known = operand+rf'\;{arrow(layer["before"])}'
                # Stem keeps the already-confirmed input arrow and the domain premise only.
                # Do not name 保序／反序 or light the output arrow before the student answers.
                stem = _lines([rf'{variable}\in {latex(r)}', known, condition])
                chain = rf'{known}\xrightarrow{{\text{{{rule}}}}}{output}\;{arrow(layer["after"])}'
                view = choice_card('逐层传递增减性',
                                   '在当前合法输入范围内，'+('开方' if root else '取倒数')+'后，输出的增减方向是？',
                                   '这一层的输入', stem,
                                   '这一层的输出', arrow(layer['after']),
                                   [arrow(d) for d in (1, -1, 0)], chain)
                view['derivation']['items'][1]['math'] = chain
                # The operation is given; only its effect on direction is unanswered.
                operation = '开方' if root else '取倒数'
                view['derivation']['operation'] = {'label': operation, 'math': output}
                view['derivation']['items'][1]['label'] = '输出函数的增减'
                view['part_title'] = operation+rf'：${variable}\in {latex(r)}$'
                # This is the input curve, whose direction was confirmed earlier.
                view['graph'] = graph_for(m, inner=root, after_layer=None if root else 'sqrt',
                                          highlight=[r], directions=[(r, layer['before'])])
                done = graph_for(m, after_layer='sqrt', highlight=[r], directions=[(r, layer['after'])]) if root else \
                    graph_for(m, highlight=[r], directions=[(r, layer['after'])])
                view['completion_graph'] = done
                views.append(view)
        # The shared completed step gathers all parts' graphs before their boards.
        # Keep one before/after pair there; each active part still shows its own layer.
        if views:
            rows = [row for row in m['partition'] if row['layers']]
            views[-1]['completion_graphs'] = [
                graph_for(m, inner=True, directions=[(row['interval'], row['inner_direction']) for row in rows]),
                graph_for(m, directions=[(row['interval'], row['direction']) for row in rows])]
    elif phase == 'join':
        boundaries = {t for branch in m['branches'] for t in (branch['domain'].inf, branch['domain'].sup) if t.is_finite}
        junctions = [j for j in m['junctions'] if j['point'] in boundaries]
        if not junctions:
            view = choice_card('检查跨段单调性', '当前讨论范围是否跨过绝对值的分界点？', '有效范围', latex(domain),
                               '连接判断', r'\text{不跨分界点，无需合并}', [r'\text{需要跨段合并}'],
                               r'\text{当前范围只落在一侧，保留该侧已求出的单调区间。}')
            view['graph'] = graph_for(m)
            view['completion_graph'] = graph_for(m)
            views.append(view)
        for junction in junctions:
            t = junction['point']
            yes = junction['merge']
            view = choice_card('检查跨段单调性', '核对分界点两侧的增减方向、函数值和端点归属，能合成一个严格单调区间吗？',
                               '分界点', rf'{variable}={latex(t)},\quad {function}({latex(t)})={latex(junction["value"])}',
                               '连接判断', r'\text{可以合并}' if yes else r'\text{不能合并}',
                               [r'\text{不能合并}' if yes else r'\text{可以合并}'],
                               r'\text{两侧同向且在分界点衔接，可合并。}' if yes else r'\text{两侧方向不同，保留各自的单调区间。}')
            view['graph'] = graph_for(m)
            view['completion_graph'] = graph_for(m)
            views.append(view)
    elif phase == 'difference':
        a, b, _ = m['branches'][0]['coefficients']
        x1, x2 = sp.symbols(f'{x}_1 {x}_2')
        t1, t2 = f'{variable}_1', f'{variable}_2'
        factor = a*(x1+x2)+b
        for row in m['partition']:
            r, direction = row['interval'], row['direction']
            delta = rf'{function}({t2})-{function}({t1})'
            difference = rf'{delta}=({t2}-{t1})\left({latex(factor)}\right)'
            sign = {1: '>0', -1: '<0', 0: '=0'}[direction]
            view = choice_card('任取两点，作差判断', f'任意取当前区间内的两个点，且 ${t1}<{t2}$。利用区间限制判断差的符号。',
                               '两点与差式', _lines([rf'{t1},{t2}\in {latex(r)},\ {t1}<{t2}', difference]),
                               '函数值的次序', delta+sign,
                               [delta+sign for sign in ('>0', '<0', '=0')],
                               _lines([rf'{t1},{t2}\in {latex(r)},\ {t1}<{t2}', difference+sign,
                                       rf'{function}({variable})\;{arrow(direction)}']))
            view['graph'] = graph_for(m)
            view['completion_graph'] = graph_for(m, highlight=[r], directions=[(r, direction)])
            views.append(view)
    elif phase == 'answer':
        directions = ('increasing', 'decreasing') if m['requested_direction'] == 'both' else (m['requested_direction'],)
        for direction in directions:
            target = m[direction+'_intervals']
            opposite = m[('decreasing' if direction == 'increasing' else 'increasing')+'_intervals']
            label = '递增' if direction == 'increasing' else '递减'
            mark = arrow(1 if direction == 'increasing' else -1)
            right = interval_latex(target)
            wrong = [interval_latex(opposite), latex(domain), r'\text{无}']
            view = choice_card('写出'+label+'区间', '分别列出各个区间；不能把不相连的区间写成一个单调区间。',
                               '原函数与范围', _lines([formula, rf'{variable}\in {latex(domain)}']),
                               label+'区间', right, list(dict.fromkeys(wrong)),
                               rf'\text{{{label}区间：}}\quad {mark}\;{right}')
            view['graph'] = graph_for(m, directions=[(row['interval'], row['direction']) for row in m['partition']])
            view['completion_graph'] = graph_for(m, highlight=target,
                                               directions=[(row['interval'], row['direction']) for row in m['partition']])
            views.append(view)
    else:
        raise ValueError('monotonicity.unknown_phase')
    return views


def presentation(values):
    views = phase_views(values)
    view = views[-1]
    left, right = view['derivation']['items']
    return {'formula_title': view['title'], 'formula_explanation': '$$'+_lines([v['proof'] for v in views])+'$$',
            'derivation_caption': view['title'], 'derivation_left_label': left['label'], 'derivation_left_math': left['math'],
            'derivation_left_note': '', 'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_monotonicity(seeds, interaction_id):
    (seed,) = seeds
    parts = []
    values = decode_value(seed['values'])
    views = phase_views(values)
    shared_graphs = any(view.get('completion_graphs') for view in views)
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        interaction = deepcopy(view['interaction'])
        interaction['options'].sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        part = {'id': f'{interaction_id}#{index}', 'title': view.get('part_title', view['title']), 'question': view['question'],
                'interaction': interaction, 'expected_answer': view['expected_answer'], 'feedback': view['feedback'],
                'submit_label': '确认判断', 'stem_board': board, 'completion_board': view['derivation']}
        part.update({key: view[key] for key in ('graph', 'completion_graph', 'completion_graphs') if key in view})
        if shared_graphs or values['phase'] == 'inner' and index < len(views):
            part.pop('completion_graph', None)
        parts.append(part)
    return {'parts': parts, 'diagnostics': []}
