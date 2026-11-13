"""Labelled parameter instances, sampled only inside exact original input cells.

These pictures illustrate a completed symbolic proof. Sampling is never used
to infer parity, close a hole, choose a branch or determine an answer.
"""
from itertools import pairwise
from math import isfinite

import sympy as sp

from .. import parameter_domain as domains
from .. import parity_parameter_original as math
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


def solution_graph(desc, model):
    """One accepted parameter value, whose curve and mirror coincide."""
    solution = model['feasible_set']
    if solution == sp.S.EmptySet:
        return None
    pieces = sorted(solution.args, key=sp.default_sort_key) if isinstance(solution, sp.Union) else [solution]
    value = domains.representative(pieces[0])
    try:
        x, domain, parts, discrete = _instance(desc, model, value)
        if domain == sp.S.EmptySet:
            return None
        graph = _graph(desc, value, x, domain, parts, discrete)
    except GraphUnavailable:
        return None  # The exact text proof remains the authoritative view.
    label = graph['params']['traces'][1]['label']
    graph['caption'] = ('$'+desc['parameter']+'='+latex(value)+'$ 时，实线 $'+desc['function']+'('+desc['variable']
                        + ')$ 与虚线 $'+label+'$ 重合。')
    return graph
