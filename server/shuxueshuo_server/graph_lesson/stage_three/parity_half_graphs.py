"""A function given on one half-axis, its parity image on the other, drawn as polynomial pieces."""
import sympy as sp

from .absolute_graph_presentation import ends, segment
from .interaction_graph_contract import validate_graph
from .interaction_graphs import short_label
from .math_values import latex


def intervals(s):
    rows = s.args if isinstance(s, sp.Union) else [s]
    return [r for r in rows if isinstance(r, sp.Interval)]


def range_text(s, x):
    from .parity_extension_presentation import range_latex
    return range_latex(s, x)


def symmetry_text(sign, known, mirrored, x):
    """How the mirrored piece is obtained from the known one."""
    if sign == -1:
        return (rf'奇函数图像关于原点对称：${range_text(mirrored, x)}$ 的一段由 ${range_text(known, x)}$ 的一段'
                r'绕原点旋转 $180^\circ$ 得到')
    return (rf'偶函数图像关于 $y$ 轴对称：${range_text(mirrored, x)}$ 的一段由 ${range_text(known, x)}$ 的一段'
            '沿 $y$ 轴翻折得到')


def half_graph(f, variable, rule, known, mirrored, sign, caption, *, mirror=True,
               highlights=(), level=None, zero=False, marks=()):
    """Known piece (and its image) as solid curves; nothing outside f's own pieces is drawn.

    `zero` marks f(0)=0 as an actual value when the rule itself passes through the origin.
    Returns None when a piece is not a polynomial of degree ≤ 3 or the picture is not representable."""
    image = sp.expand(sign * rule.xreplace({variable: -variable}))
    halves = [(rule, known), *([(image, mirrored)] if mirror else [])]
    try:
        segments = [segment(e, piece, variable) for e, r in halves for piece in intervals(r)]
    except (ValueError, sp.PolynomialError):
        return None
    if not segments:
        return None
    if zero and rule.subs(variable, 0) == 0:
        for item in segments:
            item['interval_closed'] = [c or e == 0 for e, c in zip(item['interval'], item['interval_closed'])]
    anchors = {sp.S.Zero, *(v for _, r in halves for v in (r.inf, r.sup) if v.is_finite),
               *(v for r in [*highlights, *marks] for v in (r.inf, r.sup) if v.is_finite)}
    low, high = float(min(anchors)) - 1, float(max(anchors)) + 1
    if high - low < 4:
        low, high = (low + high) / 2 - 2, (low + high) / 2 + 2
    ys = [0.0, *([float(level)] if level is not None else [])]
    for e, r in halves:
        a, b = max(low, float(r.inf)), min(high, float(r.sup))
        if a < b:
            ys += [float(e.subs(variable, a + (b - a) * j / 24)) for j in range(25)]
    pad = max(1.0, (max(ys) - min(ys)) * .12)
    domain = sp.Union(*(r for _, r in halves))
    # The plot envelope may span a hole; each segment retains its own endpoints.
    interval = [float(v) if v.is_finite else None for v in (domain.inf, domain.sup)]
    closed = [v.is_finite is True and domain.contains(v) is sp.true for v in (domain.inf, domain.sup)]
    x = str(variable)
    params = {'segments': segments, 'bounds': [low, high, min(ys) - pad, max(ys) + pad],
              'interval': interval, 'interval_closed': closed, 'points': [],
              'xTicks': [[float(v), short_label(v)] for v in sorted(anchors)], 'variable': x,
              'title': f'{f}({x}) 的图像',
              'description': '实线是函数图像；有色曲线是需要关注的部分，空心端点不取。'}
    if level is not None:
        params['level'] = float(level)
        params['yTicks'] = [[float(level), short_label(level)]]
    if highlights:
        params['highlights'] = [{'from': v[0], 'to': v[1], 'left_closed': c[0], 'right_closed': c[1]}
                                for r in highlights for v, c in [ends(r)]]
    try:
        return validate_graph({'kind': 'piecewise_curve', 'params': params, 'caption': caption})
    except ValueError:
        return None


SCHEMATIC = '示意图：取一个满足题设的一次函数，只用来看增减与对称，不代表 ${f}$ 的解析式'


def example_graph(f, x, interval, direction, sign, mirrored, *, mirror=True, zero=sp.S.Zero, note='', highlights=()):
    """An abstract f drawn through a linear instance that meets every stated condition.

    Slope ±1 carries the stated direction; the line passes through the stated zero (0 when none is
    printed), so an odd instance through the origin stays odd and an even one stays continuous at 0."""
    variable = sp.Symbol(x, real=True)
    rule = (1 if direction == 'increasing' else -1) * (variable - zero)
    shown = mirror and mirrored != sp.S.EmptySet
    caption = SCHEMATIC.format(f=f) + ('；' + symmetry_text(sign, interval, mirrored, x) if shown else '') + note + '。'
    return half_graph(f, variable, rule, interval, mirrored, sign, caption, mirror=shown, zero=zero == 0,
                      marks=[sp.FiniteSet(zero, -zero)], highlights=highlights)


def vertex_lines(rule, variable, known, x, f):
    """Why a degree ≤ 2 rule is strictly monotone on `known`: the axis and the opening, or the slope."""
    poly = sp.Poly(rule, variable)
    where = f + r'\text{ 在 }' + latex(known) + r'\text{ 上}'
    if poly.degree() == 1:
        k = poly.nth(1)
        return [r'\text{一次项系数 }' + latex(k) + ('>0' if k > 0 else '<0') + r'\Rightarrow '
                + where + (r'\text{严格递增}' if k > 0 else r'\text{严格递减}')]
    a, b = poly.nth(2), poly.nth(1)
    h = -b / (2 * a)
    c = sp.expand(rule.subs(variable, h))
    square = latex((variable - h) ** 2)
    head = '' if a == 1 else '-' if a == -1 else latex(a)
    tail = '' if c == 0 else ('+' if c > 0 else '') + latex(c)
    above = known.inf >= h
    increasing = (a > 0) == above
    word = r'\text{严格递增}' if increasing else r'\text{严格递减}'
    half = sp.Interval(h, sp.oo) if above else sp.Interval(-sp.oo, h)
    return [latex(rule) + '=' + head + square + tail,
            r'\text{对称轴 }' + x + '=' + latex(h) + r'\text{，开口' + ('向上' if a > 0 else '向下')
            + r'，在 }' + latex(half) + r'\text{ 上}' + word,
            latex(known) + r'\subseteq ' + latex(half) + r'\Rightarrow ' + where + word]
