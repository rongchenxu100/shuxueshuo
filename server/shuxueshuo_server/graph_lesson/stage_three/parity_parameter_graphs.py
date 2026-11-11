"""Labelled parameter instances, sampled only inside exact original input cells.

These pictures illustrate a completed symbolic proof. Sampling is never used
to infer parity, close a hole, choose a branch or determine an answer.
"""
from copy import deepcopy
from itertools import pairwise
from math import isfinite

import sympy as sp

from .. import parameter_domain as domains
from .. import parity_parameter_original as math
from ..function_parity import reflect_set
from .domain_visuals import exact_math
from .interaction_graphs import GraphUnavailable, _float, _pieces, short_label, ticks
from .math_values import latex


def _instance(desc, model, value):
    x, p = math.symbols(desc)
    proof = model['comparison']
    if desc['analysis_mode'] == 'quartic':
        _, _, expression, _, _, _ = math.base.source(desc)
        return x, sp.S.Reals, [(sp.Interval(-sp.oo, sp.oo), expression.subs(p, value))], []
    if proof['kind'] == 'radical':
        a, b = (proof['source'][k].subs(p, value) for k in ('alpha', 'beta'))
        if a <= 0 and b < 0:
            domain = sp.S.EmptySet
        elif a < 0 and b == 0:
            domain = sp.FiniteSet(0)
        elif a < 0:
            radius = sp.sqrt(-b/a)
            domain = sp.Interval(-radius, radius)
        elif a > 0 and b < 0:
            radius = sp.sqrt(-b/a)
            domain = sp.Interval(-sp.oo, -radius) | sp.Interval(radius, sp.oo)
        else:
            domain = sp.S.Reals
        intervals, points = _pieces(domain)
        expr = sp.sqrt(a*x**2+b)
        return x, domain, [(i, expr) for i in intervals], [(q, expr.subs(x, q)) for q in points]
    row = next(r for r in proof['rows'] if r['parameter_cell'].contains(value) is sp.true)
    if not row['valid']:
        raise GraphUnavailable('invalid_declared_domain')
    parts, discrete, regions = [], [], []
    for atom in row['input_atoms']:
        if not atom['member'] or atom['branch'] is None:
            continue
        src = proof['source']['parts'][atom['branch']]
        expr = sp.cancel((src['numerator']/src['denominator']).subs(p, value))
        if atom['kind'] == 'point':
            q = atom['point'].subs(p, value)
            regions.append(sp.FiniteSet(q))
            discrete.append((q, sp.simplify(expr.subs(x, q))))
        else:
            a, b = [atom[k].subs(p, value) for k in ('left', 'right')]
            region = sp.Interval.open(a, b)
            regions.append(region)
            parts.append((region, expr))
    return x, sp.Union(*regions), parts, discrete


def _number_lines(desc, value, domain):
    sets = [domain, reflect_set(domain)]
    pieces = [_pieces(s) for s in sets]
    ends = sorted({sp.S.Zero, *(v for intervals, points in pieces for v in
                    [*points, *(e for part in intervals for e in (part.start, part.end) if e not in (-sp.oo, sp.oo))])})
    low, high = _float(ends[0]), _float(ends[-1])
    pad = max((high-low)*0.25, 1.0)
    marks = [{'at': _float(v), 'label': short_label(v), 'exact': exact_math(v)} for v in ends]
    result = []
    for name, region, (intervals, points) in zip(('D', '-D'), sets, pieces, strict=True):
        result.append({'variable': desc['variable'], 'label': desc['parameter']+'='+latex(value)
                       + r'\text{ 时}\quad '+name+'='+latex(region), 'bounds': [low-pad, high+pad],
                       'intervals': [{'left': None if s.start == -sp.oo else _float(s.start),
                                      'right': None if s.end == sp.oo else _float(s.end),
                                      'left_closed': not s.left_open, 'right_closed': not s.right_open,
                                      'exact': exact_math(s)} for s in intervals],
                       'points': [{'at': _float(v), 'label': short_label(v), 'exact': exact_math(v)} for v in points],
                       'ticks': deepcopy(marks), 'exact_set': exact_math(region)})
    return result


def _graph(desc, value, x, domain, parts, discrete):
    anchors = sorted({sp.S.Zero, *(q for q, _ in discrete),
                      *(e for region, _ in parts for e in (region.start, region.end) if e not in (-sp.oo, sp.oo))})
    extent = max(2., *[abs(_float(q))*1.25 for q in anchors])
    # Keep distant/near-coincident holes in the exact number lines rather than
    # drawing indistinguishable marks or overflowing SVG coordinates.
    if not isfinite(extent) or extent > 1e6:
        raise GraphUnavailable('window_too_large')
    ordered = sorted({_float(q) for q in anchors})
    if any((b-a)/extent*135 < 8 for a, b in pairwise(ordered)):
        raise GraphUnavailable('distinct_boundaries_overlap')
    segments, points = [], [{'x': _float(q), 'y': _float(v), 'closed': True} for q, v in discrete]
    ys = [0.]
    for region, expr in parts:
        low, high = max(-extent, _float(region.start)), min(extent, _float(region.end))
        if low >= high:
            continue
        fn = sp.lambdify(x, expr, modules='math', cse=True)
        sample = []
        for i in range(65):
            # Actual endpoints are dealt with by exact limits below. The path
            # starts/ends just inside its original interval, never across a pole.
            q = low+(high-low)*(0.000001+0.999998*i/64)
            try:
                v = float(fn(q))
            except (ValueError, ZeroDivisionError, OverflowError):
                raise GraphUnavailable('sample_not_representable') from None
            if not isfinite(v):
                raise GraphUnavailable('sample_not_representable')
            sample.append([q, v])
        segments.append(sample)
        ys += [abs(v) for _, v in sample[2:-2]]
        for q, side in ((region.start, '+'), (region.end, '-')):
            if q in (-sp.oo, sp.oo) or abs(_float(q)) >= extent:
                continue
            limit = sp.limit(expr, x, q, dir=side)
            if limit.is_finite is True and limit.is_real is True:
                # A filled original point at the same value supersedes an open
                # boundary. Jump limits keep their own hollow points.
                closed = (not region.left_open if q == region.start else not region.right_open)
                closed = closed or any(q == at and sp.simplify(v-limit) == 0 for at, v in discrete)
                points.append({'x': _float(q), 'y': _float(limit), 'closed': bool(closed)})
                ys.append(abs(_float(limit)))
    ys += [abs(v['y']) for v in points]
    height = max(1., max(ys))*1.15
    if not isfinite(height) or height > 1e12 or len(segments) > 96:
        raise GraphUnavailable('window_too_large')
    # Identical endpoints from adjacent cells are shown once. Closed wins only
    # when it is an actual original value at that same input and output.
    unique = {}
    for point in points:
        key = point['x'], point['y']
        if key not in unique or point['closed']:
            unique[key] = point
    points = list(unique.values())
    sign = -1 if any(-1 in math.base.PROPERTIES[f['property']] for f in desc['parity_facts']) else 1
    mirror_segments = [[[-q, sign*v] for q, v in reversed(s)] for s in segments]
    mirror_points = [{'x': -v['x'], 'y': sign*v['y'], 'closed': v['closed']} for v in points]
    f = desc['function']
    label = ('-' if sign < 0 else '') + f+'(-'+desc['variable']+')'
    prefix = desc['parameter']+'='+short_label(value)
    return {'kind': 'sampled_curve', 'params': {'bounds': [-extent, extent, -height, height],
            'interval': [None, None], 'interval_closed': [False, False], 'points': [],
            'title': prefix+' 时的函数与镜像', 'description': '实线为原函数，虚线为镜像；空心点不取，实心点取到。图窗裁剪处不是定义域端点。',
            'variable': desc['variable'], 'xTicks': ticks(anchors, -extent, extent),
            'dividers': [_float(q) for q in anchors],
            'traces': [{'label': f+'('+desc['variable']+')', 'segments': segments, 'markers': points},
                       {'label': label, 'segments': mirror_segments, 'markers': mirror_points}]},
            'caption': '$'+desc['parameter']+'='+latex(value)+'$ 的实例；实线为原函数，虚线为 $'+label+'$。参数结论依据完整分类，图窗以外不表示无定义。'}


def examples(desc, model):
    solution = model['feasible_set']
    available = sp.S.Reals if desc['analysis_mode'] == 'quartic' else model['domain_parameters']
    # Valid but asymmetric domains remain useful rejected examples.
    if model['comparison'].get('kind') == 'rational_cells':
        available = sp.Union(*(r['parameter_cell'] for r in model['comparison']['rows'] if r['valid'] and r['nonempty']))
    selected = []
    for region in (solution, available-solution):
        if region == sp.S.EmptySet:
            continue
        pieces = sorted(region.args, key=sp.default_sort_key) if isinstance(region, sp.Union) else [region]
        selected.append(domains.representative(pieces[0]))
    if not selected and model['comparison'].get('kind') == 'radical' and desc['domain_role'] == 'natural':
        # An empty natural domain is labelled explicitly, never a paired curve.
        selected = [sp.S.Zero]
    lines, graphs = [], []
    for value in selected:
        try:
            x, domain, parts, discrete = _instance(desc, model, value)
            lines.extend(_number_lines(desc, value, domain))
            if domain != sp.S.EmptySet:
                graph = _graph(desc, value, x, domain, parts, discrete)
                traces = graph['params']['traces']
                markers = [{(m['x'], m['y']): m['closed'] for m in trace['markers']} for trace in traces]
                conflict = any(markers[0][q] != markers[1][q] for q in markers[0].keys() & markers[1].keys())
                if conflict:
                    # A filled mirror point must not paint over an original
                    # hole (or a discontinuous branch's hollow limit). Show
                    # the same coordinate window in separate labelled panels.
                    for index, trace in enumerate(traces):
                        separate = deepcopy(graph)
                        separate['params']['traces'] = [trace]
                        label = '原函数' if index == 0 else '镜像'
                        separate['params']['title'] = desc['parameter']+'='+short_label(value)+' 时的'+label
                        separate['params']['description'] = label+'；空心点不取，实心点取到。与另一幅图使用相同坐标范围。'
                        separate['caption'] = '$'+desc['parameter']+'='+latex(value)+'$ 时的'+label+' $'+trace['label']+'$。空心点不取，实心点取到；两图坐标范围相同。'
                        graphs.append(separate)
                else:
                    graphs.append(graph)
        except GraphUnavailable:
            continue  # Exact text proof/number lines remain the authoritative view.
    return lines, graphs
