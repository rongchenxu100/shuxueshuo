"""Concrete point maps, exact vertices and original-picture choices."""
from copy import deepcopy
from hashlib import sha256

import sympy as sp

from ..function_graph import rational, source
from .evaluation_presentation import _choice, _lines
from .interaction_graph_contract import validate_graph
from .interaction_graphs import short_label, window
from .math_values import latex
from .range_presentation import _card
from .trajectory import decode_value


def translation_label(dx, dy):
    moves = []
    if dx:
        moves.append(f'向{"右" if dx > 0 else "左"}平移 ${latex(abs(dx))}$ 个单位')
    if dy:
        moves.append(f'向{"上" if dy > 0 else "下"}平移 ${latex(abs(dy))}$ 个单位')
    return '，'.join(moves) if moves else '图像不移动'


def graph_for(a, b, c, domain, *, vertex=True, base=False, reference=None):
    h = -b/a
    radius = max(sp.S(2), 3/abs(a))
    low, high = h-radius, h+radius
    if isinstance(domain, sp.Interval):
        if domain.start.is_finite:
            low = min(low, domain.start)
        if domain.end.is_finite:
            high = max(high, domain.end)
    bounds = window(list(map(float, (low, h, high))), list(map(float, (c, c+abs(a)*radius))))
    ends = [None, None] if domain == sp.S.Reals else [float(v) if v.is_finite else None for v in (domain.start, domain.end)]
    closed = [False, False] if domain == sp.S.Reals else [not domain.left_open and ends[0] is not None, not domain.right_open and ends[1] is not None]
    marks = []
    if vertex and h in domain:
        marks.append({'x': float(h), 'label': f'({short_label(h)}, {short_label(c)})'})
    for end, included in zip(ends, closed, strict=True):
        if end is not None:
            marks.append({'x': end, 'open': not included})
    graph = {'kind': 'absolute_affine', 'caption': '虚线是基本图像，实线是变换后的图像。' if base else '按已知条件绘制的教学图',
             'params': {'a': float(a), 'b': float(b), 'c': float(c), 'showBase': base,
                        'bounds': bounds, 'interval': ends, 'interval_closed': closed,
                        'xTicks': [[float(v), short_label(v)] for v in sorted({sp.S.Zero, h})],
                        'points': marks, 'variable': 'x', 'title': '绝对值函数的图像',
                        'description': '根据当前步骤的已知表达式绘制；空心端点不取，实心端点可取。'}}
    if reference:
        previous = reference['params']
        graph['params']['reference'] = {key: deepcopy(previous[key])
                                         for key in ('a', 'b', 'c', 'interval', 'interval_closed')}
        graph['params']['showBase'] = True
        graph['caption'] = '虚线是这一步移动前的图像，实线是移动后的图像。'
        old = previous['bounds']
        graph['params']['bounds'] = [min(bounds[0], old[0]), max(bounds[1], old[1]),
                                    min(bounds[2], old[2]), max(bounds[3], old[3])]
    return validate_graph(graph)


def translated_formula(b, c):
    x = sp.Symbol('x', real=True)
    return rf'y=\left|{latex(x+b)}\right|'+('+'+latex(c) if c > 0 else latex(c) if c < 0 else '')


def translation_views(values):
    """One action per part; the next part starts from the confirmed previous picture."""
    if 'source_graph' in values['description']['source']:
        from .schematic_transform_presentation import transform_views
        return transform_views(values)
    if 'transformations' in values['description']['source']:
        from .quadratic_translation_presentation import translation_views as translated
        return translated(values)
    a, b, c, domain = source(values['description']['source'])
    if a != 1 or (b == 0 and c == 0):
        return []
    base_domain = values['graph_result']['base_domain']
    before = graph_for(sp.S.One, sp.S.Zero, sp.S.Zero, base_domain)
    views = []
    for horizontal, amount in ((True, -b), (False, c)):
        if amount == 0:
            continue
        dx, dy = (amount, sp.S.Zero) if horizontal else (sp.S.Zero, amount)
        label = translation_label(dx, dy)
        i, expected = _choice(label, [translation_label(-dx, -dy), translation_label(2*dx, 2*dy)])
        old_formula = translated_formula(0 if horizontal else b, 0)
        new_formula = translated_formula(b, 0 if horizontal else c)
        title = '左右移动' if horizontal else '上下移动'
        direction = ('右' if amount > 0 else '左') if horizontal else ('上' if amount > 0 else '下')
        action = rf'\text{{向{direction}平移}}\,{latex(abs(amount))}\,\text{{个单位}}'
        question = (rf'先只改变绝对值里面：从 ${old_formula}$ 到 ${new_formula}$，应怎样平移？'
                    if horizontal else rf'{"接着" if views else "只需"}在绝对值外面{"加上" if c > 0 else "减去"} ${latex(abs(c))}$：'
                    rf'从 ${old_formula}$ 到 ${new_formula}$，应怎样平移？')
        view = _card(title, question, '移动前', old_formula, '这一步的移动',
                     _lines([action, new_formula]),
                     '横坐标向右加、向左减。' if horizontal else '纵坐标向上加、向下减。', i, expected)
        after = graph_for(a, b, sp.S.Zero if horizontal else c, domain, reference=before)
        after['caption'] = label+'。虚线：移动前；实线：移动后。'
        view.update(graph=deepcopy(before), completion_graph=after, submit_label='确认这一步')
        view['proof'] = rf'{old_formula}\xrightarrow{{{action}}}{new_formula}'
        if domain != sp.S.Reals:
            view['question'] += rf' 此时的输入范围是 ${latex(base_domain if horizontal else domain)}$。'
        views.append(view)
        before = after
    return views


def phase_view(values):
    if 'source_graph' in values['description']['source']:
        from .schematic_transform_presentation import phase_view as schematic_view
        return schematic_view(values)
    if 'transformations' in values['description']['source']:
        from .quadratic_translation_presentation import phase_view as translated
        return translated(values)
    desc, result, phase = (values[key] for key in ('description', 'graph_result', 'phase'))
    goal = desc['source']
    a, b, c, domain = source(goal)
    u, v, x = sp.symbols('u v x', real=True)
    h, k = result['vertex']
    expression = rf'y=\left|{latex(a*x+b)}\right|'+('+'+latex(c) if c > 0 else latex(c) if c < 0 else '')
    point_map = rf'(u,v)\longmapsto\left({latex((u-b)/a)},{latex(v+c)}\right)'
    if phase == 'transform':
        # The active graph contains only y=|u|. The result appears on confirmation.
        correct = point_map
        wrong = [rf'(u,v)\longmapsto\left({latex((u+b)/a)},{latex(v-c)}\right)',
                 rf'(u,v)\longmapsto\left({latex((u-b)/a+1)},{latex(v+c)}\right)']
        wrong = [row for row in wrong if row != correct]
        i, expected = _choice('$'+correct+'$', ['$'+row+'$' for row in wrong])
        question = rf'由 $y=|u|$ 得到 ${expression}$。令 $u={latex(a*x+b)}$，原来的点 $(u,v)$ 移到哪里？'
        if a == 1:
            i, expected = _choice(translation_label(-b, c), [translation_label(b, c), translation_label(-b, c+1)])
            question = rf'从基本图像 $y=|x|$ 得到 ${expression}$，应怎样平移？'
        view = _card('确定图像怎样变换', question, '基本图像与新输入', _lines(['v=|u|', rf'u={latex(a*x+b)}']),
                     '点的对应', correct, '先从新输入关系解出横坐标；纵坐标加上绝对值外的常数。', i, expected)
        proof = [rf'u={latex(a*x+b)}\Longrightarrow x={latex((u-b)/a)}', rf'y=v+({latex(c)})', point_map]
        if domain != sp.S.Reals:
            view['question'] += rf' 原题限制 $x\in {latex(domain)}$，端点和开闭也随点移动。'
            proof.append(rf'x\in {latex(domain)}\Longleftrightarrow u\in {latex(result["base_domain"])}')
        view['proof'] = _lines(proof)
        view['graph'] = graph_for(sp.S.One, sp.S.Zero, sp.S.Zero, result['base_domain'])
        # Keep the next card's vertex answer hidden even after this card completes.
        view['completion_graph'] = graph_for(a, b, c, domain, vertex=False, base=True)
    elif phase == 'vertex':
        answer = rf'({latex(h)},{latex(k)})'
        choices = [rf'({latex(h+1)},{latex(k)})', rf'({latex(h)},{latex(k-2)})']
        i, expected = _choice('$'+answer+'$', ['$'+row+'$' for row in choices])
        view = _card('找到变换后的顶点', '基本图像的顶点是 $(0,0)$。按下面的对应关系，新顶点是什么？',
                     '已知顶点与点的对应', _lines(['(0,0)', point_map]), '新顶点', answer,
                     '把 u=0、v=0 分别代入横、纵坐标。', i, expected)
        view['proof'] = _lines([rf'x=\frac{{0-({latex(b)})}}{{{latex(a)}}}={latex(h)}', rf'y=0+({latex(c)})={latex(k)}', rf'(0,0)\longmapsto{answer}'])
        view['completion_graph'] = graph_for(a, b, c, domain, base=True)
        if a == 1 and (b != 0 or c != 0):
            moves = [translation_label(-b, 0)] if b else []
            if c:
                moves.append(translation_label(0, c))
            view['title'] = view['derivation']['caption'] = '总结图像变换'
            view['question'] = '，再'.join(moves)+'。顶点从 $(0,0)$ 最后移到了哪里？'
            path = ['(0,0)']
            if b:
                path.append(rf'({latex(h)},0)')
            if c:
                path.append(answer)
            view['derivation']['items'][0] = {'label': '已经完成的移动', 'math': _lines([
                rf'{translated_formula(0, 0)}\longrightarrow {translated_formula(b, 0)}' if b else translated_formula(0, 0),
                rf'{translated_formula(b, 0)}\longrightarrow {expression}' if c else expression,
            ])}
            view['proof'] = r'\longrightarrow'.join(path)
            view['completion_graph'] = graph_for(a, b, c, domain)
    elif phase == 'options':
        options = [{'value': option['option_id'], 'label': option['label'], 'figure_id': option['option_id']}
                   for option in goal['options']]
        # No shuffle: labels and stable IDs refer to the actual uploaded pictures.
        i = {'type': 'choice', 'field': 'answer', 'options': [{k: v for k, v in o.items() if k != 'figure_id'} for o in options]}
        expected = {'one_of': [result['correct_option_id']]}
        selected = next(row['label'] for row in result['option_verdicts'] if row['matches'])
        view = _card('对照原图，选择图像', '顶点和两侧方向都要符合。下面哪幅原图与刚得到的图像一致？',
                     '已知图像特征', _lines([rf'\text{{顶点}}\ ({latex(h)},{latex(k)})', r'\text{左侧递减，右侧递增}']),
                     '原题选择', r'\text{'+selected+'}', '依次核对顶点的横、纵坐标和左右分支方向。', i, expected)
        proofs = []
        names = {'vertex_x': '顶点横坐标不符', 'vertex_y': '顶点纵坐标不符', 'left_direction': '左侧方向不符',
                 'right_direction': '右侧方向不符', 'domain': '输入范围不符'}
        for option, verdict in zip(goal['options'], result['option_verdicts'], strict=True):
            point = option['facts']['vertex']
            reason = '顶点和两侧方向符合' if verdict['matches'] else '、'.join(names[d] for d in verdict['differences'])
            proofs.append(rf'\text{{{option["label"]}}}:\ ({latex(rational(point["x"]))},{latex(rational(point["y"]))})\quad\text{{{reason}}}')
        view['proof'] = _lines(proofs)
        if domain != sp.S.Reals:
            view['question'] += rf' 还要核对 $x\in {latex(domain)}$ 的端点和开闭。'
            view['derivation']['items'][0]['math'] = _lines([
                view['derivation']['items'][0]['math'], rf'x\in {latex(domain)}'])
        view['figure_choices'] = [o['option_id'] for o in goal['options']]
        view['graph'] = graph_for(a, b, c, domain)
        view['completion_graph'] = deepcopy(view['graph'])
    else:
        raise ValueError('function_graph.unknown_phase')
    return view


def presentation(values):
    view = phase_view(values)
    left, right = view['derivation']['items']
    moves = translation_views(values) if values['phase'] == 'transform' else []
    return {'formula_title': '分步移动图像' if moves else view['title'],
            'formula_explanation': '$$'+(_lines([part['proof'] for part in moves]) if moves else view['proof'])+'$$',
            'derivation_caption': view['title'], 'derivation_left_label': left['label'],
            'derivation_left_math': left['math'], 'derivation_left_note': '',
            'derivation_right_label': right['label'], 'derivation_right_math': right['math']}


def compile_graph(seeds, interaction_id):
    (seed,) = seeds
    values = decode_value(seed['values'])
    if values['description']['source']['kind'] != 'select_function_graph':
        from .absolute_graph_presentation import compile_absolute
        return compile_absolute(values, interaction_id)
    views = translation_views(values) if values['phase'] == 'transform' else []
    views = views or [phase_view(values)]
    parts = []
    for index, view in enumerate(views, 1):
        board = deepcopy(view['derivation'])
        board['items'][1]['math'] = None
        i = deepcopy(view['interaction'])
        if 'figure_choices' not in view:
            i['options'].sort(key=lambda row: sha256(f'{interaction_id}:{index}:{row["value"]}'.encode()).digest())
        part = {'id': f'{interaction_id}#{index}', 'title': view['title'], 'question': view['question'],
                'interaction': i, 'expected_answer': view['expected_answer'], 'feedback': view['feedback'],
                'submit_label': view.get('submit_label', '确认选择'), 'stem_board': board, 'completion_board': view['derivation']}
        part.update({key: view[key] for key in ('graph', 'completion_graph', 'figure_choices', 'show_source_graph') if key in view})
        parts.append(part)
    return {'parts': parts, 'diagnostics': []}
