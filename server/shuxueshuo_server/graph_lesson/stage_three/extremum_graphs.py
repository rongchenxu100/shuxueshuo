"""Declarative extrema pictures. Sampling chooses the viewport, never the answer."""
from copy import deepcopy

import sympy as sp

from ..function_monotonicity import components
from .absolute_graph_presentation import ends, segment
from .domain_visuals import exact_math
from .interaction_graph_contract import validate_graph
from .interaction_graphs import short_label
from .math_values import latex
from .monotonicity_presentation import _interval_mark


def _numeric(values):
    return all(v.is_finite and not v.free_symbols for v in values)


def _range_set(vals):
    if len(vals) == 2:
        return sp.FiniteSet(vals[0]) if vals[0] == vals[1] else sp.Interval(vals[0], vals[1])
    return sp.FiniteSet(vals[0])


def _range_label(name, vals, *, quantity=None):
    body = latex(_range_set(vals)) if len(vals) == 2 else latex(vals[0])
    if quantity in ('最大值', '最小值'):
        mark = r'\max' if quantity == '最大值' else r'\min'
        return rf'\text{{{name} 的{quantity}}}:\quad {mark}={body}'
    if len(vals) == 1:
        return rf'\text{{{name} 的最值}}:\quad {body}'
    return rf'\text{{{name} 的值域}}:\quad {body}'


def _line_from_set(label, value):
    from . import interaction_graphs as drawing
    intervals, points = drawing._pieces(value)
    ends = sorted({*points, *(v for interval in intervals for v in (interval.start, interval.end) if v.is_finite)})
    low, high = (drawing._float(ends[0]), drawing._float(ends[-1])) if ends else (-1.0, 1.0)
    pad = max((high - low) * 0.25, 0.75)
    ticks = [{'at': drawing._float(p), 'label': short_label(p), 'exact': exact_math(p)} for p in ends]
    return {'variable': 'y', 'label': label, 'bounds': [low - pad, high + pad],
            'intervals': [{'left': drawing._float(p.start) if p.start.is_finite else None,
                           'right': drawing._float(p.end) if p.end.is_finite else None,
                           'left_closed': not p.left_open, 'right_closed': not p.right_open,
                           'exact': exact_math(p)} for p in intervals],
            'points': [{'at': drawing._float(p), 'label': short_label(p), 'exact': exact_math(p)} for p in points],
            'ticks': deepcopy(ticks), 'exact_set': exact_math(value)}


def _schematic_line(label, vals):
    """Independent axis for symbolic endpoints: labels keep the exact math."""
    if len(vals) == 1 or vals[0] == vals[1]:
        point = {'at': 0.0, 'label': short_label(vals[0]) if _numeric(vals[:1]) else latex(vals[0]),
                 'exact': exact_math(vals[0]) if _numeric(vals[:1]) else exact_math(sp.Integer(0))}
        # Symbolic exact_math needs a sympy object; use 0 placeholder geometry only.
        if not _numeric(vals[:1]):
            point = {'at': 0.0, 'label': latex(vals[0]), 'exact': exact_math(sp.Integer(0))}
        return {'variable': 'y', 'label': label, 'bounds': [-1.0, 1.0], 'intervals': [],
                'points': [point], 'ticks': [dict(point)], 'exact_set': exact_math(sp.Integer(0))}
    left_label, right_label = latex(vals[0]), latex(vals[1])
    return {'variable': 'y', 'label': label, 'bounds': [-1.0, 1.0],
            'intervals': [{'left': -0.55, 'right': 0.55, 'left_closed': True, 'right_closed': True,
                           'exact': exact_math(sp.Interval(-1, 1))}],
            'points': [],
            'ticks': [{'at': -0.55, 'label': left_label, 'exact': exact_math(sp.Integer(0))},
                      {'at': 0.55, 'label': right_label, 'exact': exact_math(sp.Integer(0))}],
            'exact_set': exact_math(sp.Integer(0))}


def coverage_range_lines(uname, u_vals, vname, v_vals, *, coverage_label, quantity=None):
    """Two premise tracks plus a completion track that names the coverage relation."""
    rows = []
    for name, vals in ((uname, u_vals), (vname, v_vals)):
        label = _range_label(name, vals, quantity=quantity if len(vals) == 1 else None)
        if _numeric(vals):
            rows.append(_line_from_set(label, _range_set(vals)))
        else:
            rows.append(_schematic_line(label, vals))
    completion = deepcopy(rows[1])
    completion['label'] = coverage_label
    return rows, completion


def _direction_marks(bounds, direction):
    region = sp.Interval(bounds['low'], bounds['high'], not bounds['left_closed'], not bounds['right_closed'])
    return [_interval_mark(region, direction)]


def proof_monotone_direction(proof):
    """Constant monotone direction on the proof interval, or None if parameter-dependent."""
    x, expr = proof['variable'], proof['expression']
    if expr.free_symbols - {x} or not expr.is_polynomial(x):
        return None
    poly = sp.Poly(expr, x)
    deg = poly.degree()
    if deg <= 0:
        return 0
    if deg == 1:
        slope = poly.nth(1)
        return None if slope.free_symbols else int(sp.sign(slope))
    # Pure cubic Ax^3+C (A18-style): sign(A) is the direction.
    if deg == 3 and poly.nth(2) == 0 and poly.nth(1) == 0:
        leading = poly.nth(3)
        return None if leading.free_symbols else int(sp.sign(leading))
    return None


def _region_from_bounds(b):
    return sp.Interval(b['low'], b['high'], not b['left_closed'], not b['right_closed'])


def _poly_curve_graph(segments, *, x, anchors, title, caption, interval_marks=None):
    """Build a piecewise_curve viewport around the given polynomial segments."""
    finite = [v for v in anchors if getattr(v, 'is_finite', False)]
    if not finite:
        return None
    low, high = float(min(finite) - 1), float(max(finite) + 1)
    if high - low < 4:
        mid = (low + high) / 2
        low, high = mid - 2, mid + 2
    ys = [0.]
    for row in segments:
        lo = row['interval'][0] if row['interval'][0] is not None else low
        hi = row['interval'][1] if row['interval'][1] is not None else high
        for j in range(41):
            t = lo + (hi - lo) * j / 40
            q = row['coefficients'][0]
            for c in row['coefficients'][1:]:
                q = q * t + c
            if abs(q) < 1e100:
                ys.append(float(q))
    bottom, top = min(ys), max(ys)
    margin = max(1., (top - bottom) * .12)
    domain_low = min((s['interval'][0] for s in segments if s['interval'][0] is not None), default=low)
    domain_high = max((s['interval'][1] for s in segments if s['interval'][1] is not None), default=high)
    left_closed = any(s['interval'][0] == domain_low and s['interval_closed'][0] for s in segments)
    right_closed = any(s['interval'][1] == domain_high and s['interval_closed'][1] for s in segments)
    params = {
        'segments': segments,
        'bounds': [low, high, bottom - margin, top + margin],
        'interval': [domain_low, domain_high],
        'interval_closed': [left_closed, right_closed],
        'variable': str(x),
        'title': title,
        'description': '箭头是已确认的方向。实心端点可以取到，空心端点不能取到。',
        'xTicks': [[float(v), short_label(v)] for v in sorted({sp.S.Zero, *finite})],
        'points': [],
        'interval_marks': list(interval_marks or []),
    }
    return validate_graph({'kind': 'piecewise_curve', 'params': deepcopy(params), 'caption': caption})


def poly_proof_graph(proof, *, title='根据增减读出值域', caption=None, direction=None):
    """Degree ≤ 3 polynomial piece as piecewise_curve (supports A18 cubics)."""
    expr, x, b = proof['expression'], proof['variable'], proof['bounds']
    if b['low'].free_symbols or b['high'].free_symbols or expr.free_symbols - {x}:
        return None
    if not expr.is_polynomial(x) or sp.degree(expr, x) > 3:
        return None
    region = _region_from_bounds(b)
    marks = _direction_marks(b, direction) if direction is not None else []
    return _poly_curve_graph(
        [segment(expr, region, x)],
        x=x, anchors={b['low'], b['high'], sp.S.Zero},
        title=title,
        caption=caption or '图中标出增减方向；根据箭头直接读出值域或最值。',
        interval_marks=marks)


def _competition_sample(b, parameter, allowed, axis):
    """Pick a concrete endpoint past the vertex so both ends are visibly distinct."""
    from .interaction_graphs import GraphUnavailable, representative_parameter
    fixed = b['high'] if b['low'].free_symbols else b['low']
    # Prefer samples on the far side of the vertex relative to the fixed end.
    # Skip the first integer past the vertex (often the competition boundary).
    if fixed.is_number and axis.is_number:
        prefer = (sp.Interval.open(axis, sp.oo) if fixed < axis
                  else sp.Interval.open(-sp.oo, axis))
        narrowed = allowed & prefer
        if narrowed != sp.S.EmptySet:
            if fixed < axis:
                guesses = (sp.floor(axis) + 2, sp.floor(axis) + 3, sp.ceiling(axis) + 2)
            else:
                guesses = (sp.ceiling(axis) - 2, sp.ceiling(axis) - 3, sp.floor(axis) - 2)
            for guess in guesses:
                if narrowed.contains(guess) is sp.true:
                    return guess
            try:
                return representative_parameter(narrowed)
            except GraphUnavailable:
                pass
    return representative_parameter(allowed)


def endpoint_competition_graph(proof, *, name, parameter, allowed,
                               title='比较两端的高低'):
    """Static schematic for a fixed quadratic on an interval with one moving end.

    Pins the symbolic endpoint to a sample value for drawing only; ticks still
    label that end with the parameter name (e.g. a), not the sample number.
    """
    from .interaction_graphs import GraphUnavailable
    expr, x, b = proof['expression'], proof['variable'], proof['bounds']
    if not expr.is_polynomial(x) or sp.degree(expr, x) != 2:
        return None
    if expr.free_symbols - {x}:
        return None
    low_sym, high_sym = bool(b['low'].free_symbols), bool(b['high'].free_symbols)
    if low_sym == high_sym or (b['low'].free_symbols | b['high'].free_symbols) - {parameter}:
        return None
    poly = sp.Poly(expr, x)
    axis = sp.cancel(-poly.nth(1) / (2 * poly.nth(2)))
    if axis.free_symbols or not axis.is_finite:
        return None
    try:
        sample = _competition_sample(b, parameter, allowed, axis)
    except GraphUnavailable:
        return None
    drawn = {
        **proof,
        'bounds': {
            **b,
            'low': sp.simplify(b['low'].subs(parameter, sample)) if low_sym else b['low'],
            'high': sp.simplify(b['high'].subs(parameter, sample)) if high_sym else b['high'],
        },
    }
    db = drawn['bounds']
    if db['low'].free_symbols or db['high'].free_symbols:
        return None
    region = _region_from_bounds(db)
    graph = _poly_curve_graph(
        [segment(expr, region, x)],
        x=x, anchors={db['low'], db['high'], axis, sp.S.Zero},
        title=title,
        caption=(rf'示意图（取 ${latex(parameter)}={latex(sample)}$）；'
                 rf'标出两端与顶点，用来对照 ${name}({latex(b["low"])})$ 与 '
                 rf'${name}({latex(b["high"])})$ 的高低；分类结论靠代数。'),
    )
    if not graph:
        return None
    # Replace numeric tick at the sample end with the parameter letter.
    ticks = []
    for value, label in graph['params']['xTicks']:
        if high_sym and abs(value - float(db['high'])) < 1e-9:
            ticks.append([value, str(parameter)])
        elif low_sym and abs(value - float(db['low'])) < 1e-9:
            ticks.append([value, str(parameter)])
        else:
            ticks.append([value, label])
    # Ensure the vertex is labelled even if it coincides with no prior tick merge.
    if all(abs(value - float(axis)) > 1e-9 for value, _ in ticks):
        ticks.append([float(axis), short_label(axis)])
        ticks.sort(key=lambda row: row[0])
    left_label = (str(parameter) if low_sym else short_label(b['low']))
    right_label = (str(parameter) if high_sym else short_label(b['high']))
    fixed_end = b['high'] if low_sym else b['low']
    fixed_label = right_label if low_sym else left_label
    fixed_val = sp.expand(expr.subs(x, fixed_end))
    graph['params']['xTicks'] = ticks
    graph['params']['points'] = [
        {'x': float(db['low']), 'label': f'{name}({left_label})', 'place': 'above-left'},
        {'x': float(db['high']), 'label': f'{name}({right_label})', 'place': 'above-right'},
    ]
    # Horizontal reference at the fixed endpoint value: compare the moving end to this line.
    if fixed_val.is_number and fixed_val.is_finite:
        level = float(fixed_val)
        graph['params']['level'] = level
        graph['params']['yTicks'] = [[level, f'{name}({fixed_label})']]
        graph['caption'] = (
            rf'示意图（取 ${latex(parameter)}={latex(sample)}$）；'
            rf'虚线是 $y={name}({latex(fixed_end)})$，用来对照另一端的高低；'
            rf'分类结论靠代数。')
        graph['params']['description'] = (
            f'示意抛物线；虚线 y={name}({fixed_label})；'
            f'两端是 {name}({left_label}) 与 {name}({right_label})。')
    else:
        graph['params']['description'] = (
            f'示意抛物线；左端点是 {name}({left_label})，右端点是 {name}({right_label})。')
    return validate_graph(graph)


def certificate_graph(cert, *, title='分段函数的完整图像', directions=None):
    """One piecewise_curve covering every proof segment of a certificate."""
    proofs = cert.get('proofs') or []
    if len(proofs) < 2:
        return None
    x = proofs[0]['variable']
    segments, marks, anchors = [], [], {sp.S.Zero}
    for i, proof in enumerate(proofs):
        expr, b = proof['expression'], proof['bounds']
        if b['low'].free_symbols or b['high'].free_symbols or expr.free_symbols - {x}:
            return None
        if not expr.is_polynomial(x) or sp.degree(expr, x) > 3:
            return None
        region = _region_from_bounds(b)
        segments.append(segment(expr, region, x))
        anchors.update(v for v in (b['low'], b['high']) if v.is_finite)
        direction = (directions[i] if directions and i < len(directions)
                     else proof_monotone_direction(proof))
        if direction is not None:
            marks.extend(_direction_marks(b, direction))
    return _poly_curve_graph(
        segments, x=x, anchors=anchors, title=title,
        caption='各段画在同一坐标系；箭头表示本段增减，用来核对整函数的最值。',
        interval_marks=marks)


def illustrated_proof_graph(proof, *, title='根据增减读出值域', direction=None, parameter=None, sample=None):
    """Curve with monotonicity marks for reading the range; sample substitutes parameters."""
    if direction is None:
        direction = proof_monotone_direction(proof)
    picture = poly_proof_graph(proof, title=title, direction=direction)
    if picture is not None:
        return picture
    picture = proof_graph(proof)
    if picture is not None:
        picture = deepcopy(picture)
        picture['params']['title'] = title
        picture['caption'] = '图中标出增减方向；根据箭头直接读出值域或最值。'
        if (direction is not None and picture['kind'] == 'piecewise_curve'
                and not picture['params'].get('interval_marks')):
            picture['params']['interval_marks'] = _direction_marks(proof['bounds'], direction)
        return validate_graph(picture)
    if sample is None or parameter is None:
        return None
    from .interaction_graphs import GraphUnavailable, interval_function_graph
    from ..extremum_math import describe, numeric_model
    expr, x, b = proof['expression'], proof['variable'], proof['bounds']
    try:
        if b['low'].free_symbols or b['high'].free_symbols:
            return None
        drawn = sp.simplify(expr.subs(parameter, sample))
        if drawn.free_symbols - {x}:
            return None
        region = sp.Interval(b['low'], b['high'], not b['left_closed'], not b['right_closed'])
        # Prefer piecewise_curve so monotonicity marks are schema-valid.
        if drawn.is_polynomial(x) and sp.degree(drawn, x) <= 3:
            graph = poly_proof_graph(
                {**proof, 'expression': drawn, 'family': 'polynomial'},
                title=title, direction=direction,
                caption=rf'示意图（取 ${latex(parameter)}={latex(sample)}$）；箭头表示增减，用来读值域。')
            if graph:
                return graph
            if sp.degree(drawn, x) <= 2:
                source = {'kind': 'find_range', 'object': 'H',
                          'input_domain': ('(' if region.left_open else '[')+str(region.inf).replace('-oo', '-∞')+','
                                           +str(region.sup).replace('oo', '∞')+(')' if region.right_open else ']'),
                          'answer_request': {'kind': 'extremum', 'quantity': 'minimum'}}
                d = describe(source, '/root/goals/0',
                             [{'source_ref': '/root/definitions/0',
                               'expression': f'H({x})={str(drawn).replace("**", "^")}'}])
                graph = graph_for(numeric_model(d))
                if graph:
                    graph = deepcopy(graph)
                    graph['params']['title'] = title
                    graph['caption'] = rf'示意图（取 ${latex(parameter)}={latex(sample)}$）；箭头表示增减，用来读值域。'
                    if direction is not None:
                        graph['params']['interval_marks'] = _direction_marks(b, direction)
                    return validate_graph(graph)
        return validate_graph(interval_function_graph(
            drawn, x, region, title=title,
            caption=rf'示意图（取 ${latex(parameter)}={latex(sample)}$）；看斜率方向读出值域。'))
    except (GraphUnavailable, ValueError, NotImplementedError):
        return None


def proof_graph(proof, *, parameter=None, branch=None, quantity='min'):
    """Reuse numeric interval pictures and the classified quadratic explorer."""
    from .interaction_graphs import axis_explorer, interval_function_graph, GraphUnavailable
    from ..extremum_math import describe, numeric_model
    expr, x, b = proof['expression'], proof['variable'], proof['bounds']
    try:
        if b['low'].free_symbols or b['high'].free_symbols:
            return None
        region = sp.Interval(b['low'], b['high'], not b['left_closed'], not b['right_closed'])
        if parameter and expr.has(parameter):
            if not expr.is_polynomial(x) or sp.degree(expr, x) != 2 or branch is None:
                return None
            axis = sp.cancel(-sp.Poly(expr, x).nth(1)/(2*sp.Poly(expr, x).nth(2)))
            breaks = [s for end in (region.inf, region.sup) if end.is_finite
                      for s in sp.solve(axis-end, parameter)]
            return validate_graph(axis_explorer(expr, x, parameter, region, breakpoints=breaks,
                start=None, within=branch, target=quantity, title='本参数分类下的二次函数',
                description='图中只画本段的合法输入。参数分类与界由代数条件确定。',
                caption='可拖动查看本分类的形状；图像用于说明，参数结论依据配方和区间位置。'))
        if expr.free_symbols-{x}:
            return None
        if proof['family'] in ('polynomial', 'cubic') and expr.is_polynomial(x) and sp.degree(expr, x) <= 3:
            picture = poly_proof_graph(proof)
            if picture:
                return picture
            if proof['family'] == 'polynomial' and sp.degree(expr, x) <= 2:
                source = {'kind': 'find_range', 'object': 'H', 'input_domain': str(region).replace('Interval.open(', '('),
                          'answer_request': {'kind': 'extremum', 'quantity': 'minimum'}}
                # Use the exact source domain notation, including open endpoints.
                source['input_domain'] = ('(' if region.left_open else '[')+str(region.inf).replace('-oo','-∞')+','+str(region.sup).replace('oo','∞')+(')' if region.right_open else ']')
                expression = str(expr).replace('**', '^')
                d = describe(source, '/root/goals/0', [{'source_ref': '/root/definitions/0', 'expression': f'H({x})={expression}'}])
                model = numeric_model(d)
                picture = graph_for(model)
                if picture:
                    picture['params']['title'] = '根据增减读出值域'
                    picture['caption'] = '图中标出增减方向；根据箭头直接读出值域或最值。'
                return picture
        return validate_graph(interval_function_graph(expr, x, region, title='当前这一段的函数',
                    caption='只画原题允许的输入；开端点的界不一定能取到。'))
    except (GraphUnavailable, ValueError, NotImplementedError):
        return None


def graph_for(model, *, attained=False):
    expr, x, domain = model['expression'], model['variable'], model['domain']
    intervals = list(components(domain))
    if not intervals:
        return None
    segments = []
    for interval in intervals:
        if model['family'] == 'fraction':
            num, den = sp.fraction(expr)
            row = segment(num, interval, x)
            row.update(transform='rational', denominator=[float(sp.Poly(den, x).nth(i)) for i in (1, 0)])
        elif model['family'] == 'root_sum':
            root, = [p for p in expr.atoms(sp.Pow) if p.exp == sp.S.Half]
            scale = expr.coeff(root)
            row = segment(sp.expand(expr-scale*root), interval, x)
            row.update(transform='root_sum', radicand=[float(sp.Poly(root.base, x).nth(i)) for i in (1, 0)],
                       root_scale=float(scale))
        else:
            row = segment(expr, interval, x)
        segments.append(row)
    anchors = {sp.S.Zero, *[v for r in intervals for v in (r.inf, r.sup) if v.is_finite]}
    anchors.update(v for c in model['interval_steps'] for v in (c['interval'].inf, c['interval'].sup) if v.is_finite)
    low, high = float(min(anchors)-1), float(max(anchors)+1)
    if high-low < 4:
        low, high = (low+high)/2-2, (low+high)/2+2
    ys = [0.]
    for i in range(81):
        point = sp.Rational(str(low+(high-low)*i/80))
        if point in domain:
            value = expr.subs(x, point)
            if value.is_real and value.is_finite:
                ys.append(float(value))
    bottom, top = min(ys), max(ys)
    margin = max(1., (top-bottom)*.12)
    region, closed = ends(sp.Interval(domain.inf, domain.sup, domain.inf not in domain, domain.sup not in domain))
    params = {
        'segments': segments, 'bounds': [low, high, bottom-margin, top+margin],
        'interval': region, 'interval_closed': closed, 'variable': str(x),
        'title': '根据增减寻找最值', 'description': '箭头是已确认的方向。实心端点可以取到，空心端点不能取到。',
        'xTicks': [[float(v), short_label(v)] for v in sorted(anchors)],
        'points': [], 'interval_marks': [_interval_mark(c['interval'], c['direction']) for c in model['interval_steps']],
    }
    if attained and model['attained']:
        params['points'] = [{'x': float(v), 'label': short_label(v), 'open': False} for v in model['witnesses']]
        params['level'] = float(model['value'])
        params['yTicks'] = [[float(model['value']), short_label(model['value'])]]
    return validate_graph({'kind': 'piecewise_curve', 'params': deepcopy(params),
                           'caption': '图中标出已确认的增减区间；最值还要检查取等位置。' if not attained else
                                      '取等位置已标出；虚线对应这个位置的函数值。'})
