"""Exact image specs for step interactions.

The interaction rules say what to draw; this module works out how, from exact
values only: the function family, a representative parameter strictly inside
its case, the window, short tick labels, and whether option pictures can be
told apart. Whatever cannot be drawn faithfully raises ``GraphUnavailable`` and
the question keeps its text options. The page draws these specs without any
mathematics of its own.
"""

from dataclasses import dataclass
from itertools import combinations, pairwise
from math import ceil, floor, hypot, isfinite

import sympy as sp

KINDS = ("quadratic", "reciprocal_sum", "linear", "number_line", "axis_explorer")
# Plot widths in SVG units, as drawn by site/assets/practice/components.js.
PLOT_WIDTH, PLOT_HEIGHT, LINE_WIDTH = 270, 174, 288
# Marks closer than this read as one mark; labels closer than LABEL_GAP collide.
MARK_GAP, LABEL_GAP = 6, 22
# Number-line endpoints have radius 6 and a 2.6-wide stroke. Distinct exact
# marks need this much room so a later hollow point cannot cover a filled one.
LINE_MARK_GAP = 15
# Function marks have radius 5 with a stroke; distinct endpoint markers must
# not let a later filled dot paint over an earlier hollow dot.
FUNCTION_MARK_GAP = 13


class GraphUnavailable(Exception):
    """No faithful picture; the question falls back to text, for the stated reason."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _finite(value):
    return isinstance(value, sp.Expr) and not value.free_symbols and value.is_finite is True and value.is_real is True


def _svg_plain_math(text):
    """SVG text cannot render LaTeX; prefer unicode powers over ``^2``."""
    return (str(text).replace("sqrt", "√").replace("**", "^")
            .replace("^2", "²").replace("^3", "³").replace("*", ""))


def short_label(value):
    """Plain tick text such as ``-5/2``; the SVG renders no LaTeX."""
    value = sp.nsimplify(value) if isinstance(value, float) else sp.sympify(value)
    if value.is_Rational:
        return str(value.p) if value.q == 1 else f"{value.p}/{value.q}"
    return _svg_plain_math(sp.sstr(value))


def plain(value):
    """Plain text for SVG titles and descriptions."""
    if isinstance(value, sp.Interval):
        left = "(" if value.left_open or not _finite(value.start) else "["
        right = ")" if value.right_open or not _finite(value.end) else "]"
        start = "-∞" if value.start == -sp.oo else short_label(value.start)
        end = "+∞" if value.end == sp.oo else short_label(value.end)
        return f"{left}{start}, {end}{right}"
    if isinstance(value, sp.Union):
        return " ∪ ".join(plain(piece) for piece in value.args)
    if isinstance(value, sp.FiniteSet):
        return "{" + ", ".join(short_label(point) for point in value) + "}"
    if value == sp.S.EmptySet:
        return "空集"
    if value == sp.S.Reals:
        return "(-∞, +∞)"
    return _svg_plain_math(sp.sstr(value))


def _float(value):
    return float(sp.N(value, 30))


# --- Families and representatives ---------------------------------------------------

def family(function, variable):
    """The drawing component and its exact parameters, or GraphUnavailable."""
    expression = sp.cancel(sp.together(function))
    if expression.free_symbols - {variable}:
        raise GraphUnavailable("parameter_not_substituted")
    if expression.is_polynomial(variable):
        poly = sp.Poly(expression, variable)
        if poly.degree() == 2:
            leading, slope = poly.nth(2), poly.nth(1)
            axis = -slope / (2 * leading)
            return {"kind": "quadratic", "function": expression, "coefficient": leading,
                    "vertex": (axis, sp.simplify(expression.subs(variable, axis)))}
        if poly.degree() <= 1:
            return {"kind": "linear", "function": expression, "slope": poly.nth(1), "intercept": poly.nth(0)}
        raise GraphUnavailable("family_unknown")
    if not expression.is_rational_function(variable):
        raise GraphUnavailable("family_unknown")
    linear = reciprocal = constant = sp.S.Zero
    for term in sp.Add.make_args(sp.expand(sp.apart(expression, variable))):
        if not term.has(variable):
            constant += term
        elif not (term / variable).has(variable):
            linear += term / variable
        elif not (term * variable).has(variable):
            reciprocal += term * variable
        else:
            raise GraphUnavailable("family_unknown")
    if reciprocal == 0:
        raise GraphUnavailable("family_unknown")
    return {"kind": "reciprocal_sum", "function": expression, "a": linear, "b": reciprocal, "c": constant}


def _nice_inside(low, high):
    """A short rational in the middle half of a bounded interval."""
    width = high - low
    inner_low, inner_high = low + width / 4, high - width / 4
    middle = (low + high) / 2
    for denominator in (1, 2, 4):
        first, last = int(sp.ceiling(inner_low * denominator)), int(sp.floor(inner_high * denominator))
        if first > last:
            continue
        # The nearest lattice point is adjacent to the midpoint; do not
        # enumerate an interval whose width may be arbitrarily large.
        numerators = {max(first, min(last, int(nearest))) for nearest in
                      (sp.floor(middle * denominator), sp.ceiling(middle * denominator))}
        candidates = [sp.Rational(numerator, denominator) for numerator in numerators]
        return min(candidates, key=lambda value: (abs(value - middle), abs(value)))
    return middle


def representative_parameter(region):
    """A simple value strictly inside ``region`` and away from its boundary.

    Case pictures must look typical: a half-line ``a <= -1`` gives ``-2``, an
    interval ``-1 < a < 0`` gives ``-1/2``.
    """
    pieces = region.args if isinstance(region, sp.Union) else (region,)
    for piece in pieces:
        if not isinstance(piece, sp.Interval) or piece.measure == 0:
            continue
        low, high = piece.start, piece.end
        if low == -sp.oo and high == sp.oo:
            value = sp.Integer(0)
        elif high == sp.oo:
            value = sp.floor(low) + 1
        elif low == -sp.oo:
            value = sp.ceiling(high) - 1
        else:
            value = _nice_inside(low, high)
        if piece.contains(value) is sp.true and value not in piece.boundary:
            return value
    raise GraphUnavailable("representative_missing")


# --- Window and ticks -------------------------------------------------------------

def _step(span):
    return 0.25 if span <= 4 else 0.5 if span <= 10 else 1.0 if span <= 25 else 5.0


def window(xs, ys, *, padding=0.18):
    """Bounds that keep the axes and every key point visible with room around them."""
    xs, ys = [0.0, *xs], [0.0, *ys]
    bounds = []
    for values in (xs, ys):
        low, high = min(values), max(values)
        span = max(high - low, 1.0)
        step = _step(span)
        low -= span * padding
        high += span * padding
        bounds.extend((step * int(low // step), step * -int(-high // step)))
    return bounds


def grid(low, high):
    """Nonzero round values across a window, as exact numbers for ``ticks``."""
    step = sp.nsimplify(2 * _step(high - low))
    first, last = int(sp.ceiling(sp.nsimplify(low) / step)), int(sp.floor(sp.nsimplify(high) / step))
    return [step * index for index in range(first, last + 1) if index]


def ticks(values, low, high, width=PLOT_WIDTH):
    """Exact tick values in priority order; a later tick too close to an earlier one is dropped."""
    chosen = []
    for value in values:
        if not _finite(value):
            continue
        number = _float(value)
        if not low <= number <= high:
            continue
        position = (number - low) / (high - low) * width
        if any(abs(position - (other - low) / (high - low) * width) < LABEL_GAP for other, _ in chosen):
            continue
        chosen.append((number, short_label(value)))
    return [[number, label] for number, label in chosen]


def _pixel(value, low, high, width):
    return round((value - low) / (high - low) * width / MARK_GAP)


@dataclass(frozen=True)
class _PointSignature:
    x: float
    y: float
    attained: bool


def require_distinct(signatures):
    """Each option picture must differ from every other at drawing resolution."""
    if len(set(signatures)) != len(signatures):
        raise GraphUnavailable("options_indistinct")
    for left, right in combinations(signatures, 2):
        if isinstance(left, _PointSignature) and isinstance(right, _PointSignature) and \
                left.attained == right.attained and hypot(left.x - right.x, left.y - right.y) < MARK_GAP:
            raise GraphUnavailable("options_indistinct")


# --- Function pictures ------------------------------------------------------------

def value_at(drawn, point, variable):
    """The exact function value at ``point``, or None at a pole."""
    value = sp.simplify(drawn["function"].subs(variable, point))
    return value if _finite(value) else None


def drawable(drawn, variable, marks):
    """Marks that sit on the curve; an end at a pole has no point to draw."""
    return [(point, attained) for point, attained in marks if value_at(drawn, point, variable) is not None]


def endpoint_story(drawn, variable, domain):
    """Plain description of each finite end, for screen readers."""
    lines = []
    for point, attained in domain_points(domain):
        value, where = value_at(drawn, point, variable), f"{variable}={short_label(point)}"
        if value is None:
            lines.append(f"{where} 附近函数值无界")
        elif attained:
            lines.append(f"{where} 处函数值为 {short_label(value)}（实心点）")
        else:
            lines.append(f"{where} 取不到，函数值趋近 {short_label(value)}（空心点）")
    return "；".join(lines) or f"{variable} 取遍 {plain(domain)}，曲线没有端点"


def domain_points(domain):
    """Finite domain endpoints as ``(point, attained)``; an open end is drawn hollow."""
    if not isinstance(domain, sp.Interval):
        raise GraphUnavailable("domain_unsupported")
    return [(point, not open_) for point, open_ in ((domain.start, domain.left_open), (domain.end, domain.right_open))
            if _finite(point)]


def _reciprocal_turns(drawn, domain):
    """Stationary points of ax+b/x that belong to the requested branch."""
    if drawn["a"] == 0:
        return []
    ratio = sp.cancel(drawn["b"] / drawn["a"])
    if ratio.is_positive is False:
        return []
    if ratio.is_positive is not True:
        raise GraphUnavailable("critical_points_unknown")
    root = sp.sqrt(ratio)
    return [point for point in (-root, root) if domain.contains(point) is sp.true]


def _check_reciprocal_turn_window(turns, bounds):
    """A visible turn needs room beyond the component's skipped pole samples."""
    low, high = bounds[:2]
    span = high - low
    # reciprocalSumGraph avoids |x| < (xmax-xmin)/400. Merely including a
    # tiny turn in the window can still draw a monotone curve, so leave a
    # visible margin on both sides of it within the sampled branch.
    gap = span / 400
    for point in turns:
        value = _float(point)
        left, right = (low, min(high, -gap)) if value < 0 else (max(low, gap), high)
        if min(value - left, right - value) / span * PLOT_WIDTH < MARK_GAP:
            raise GraphUnavailable("turn_not_visible")


def function_frame(drawn, variable, domain, *, marks=(), show_vertex=False, extra=()):
    """Window and ticks for one function, covering its interval and every mark."""
    points = [point for point, _ in domain_points(domain)]
    points += [point for point, _ in marks] + list(extra)
    unbounded = not (_finite(domain.start) and _finite(domain.end))
    if drawn["kind"] == "quadratic" and (show_vertex or (unbounded and drawn["vertex"][0] in domain)):
        points.append(drawn["vertex"][0])
    elif drawn["kind"] == "reciprocal_sum":
        points.extend(_reciprocal_turns(drawn, domain))
    # Inner samples keep the curve's shape on screen, e.g. the climb out of a pole at an open end.
    if not unbounded:
        inner = [(domain.start + domain.end) / 2]
    else:
        # Reach beyond any finite end or turn, so both sides of a turning
        # curve remain visible even when the domain itself is unbounded.
        anchors = points or [sp.Integer(0)]
        inner = [*([min(anchors) - 2] if not _finite(domain.start) else []),
                 *([max(anchors) + 2] if not _finite(domain.end) else [])]
    xs = [_float(point) for point in points] + ([_float(point) for point in inner] if unbounded else [])
    ys = [_float(value) for value in (value_at(drawn, point, variable) for point in [*points, *inner])
          if value is not None]
    if drawn["kind"] == "quadratic" and show_vertex:
        ys.append(_float(drawn["vertex"][1]))
    bounds = window(xs, ys)
    if drawn["kind"] == "reciprocal_sum":
        _check_reciprocal_turn_window(_reciprocal_turns(drawn, domain), bounds)
    return bounds, ticks(points, bounds[0], bounds[1])


def _check_function_marks(drawn, variable, bounds, marks):
    for point, _ in marks:
        if value_at(drawn, point, variable) is None:
            raise GraphUnavailable("mark_undefined")
    for (left, _), (right, _) in combinations(marks, 2):
        if sp.simplify(left - right) == 0:
            continue
        first = mark_signature(drawn, variable, bounds, left, True)
        second = mark_signature(drawn, variable, bounds, right, True)
        if hypot(first.x - second.x, first.y - second.y) < FUNCTION_MARK_GAP:
            raise GraphUnavailable("marks_overlap")


def function_graph(drawn, variable, domain, *, bounds, x_ticks, marks=(), show_vertex=False, mark_sign=None,
                   strict=False, title, description, caption=None):
    """One ``{kind, params}`` spec; ``marks`` are ``(point, attained)`` pairs on the curve."""
    if not isinstance(domain, sp.Interval):
        raise GraphUnavailable("domain_unsupported")
    _check_function_marks(drawn, variable, bounds, marks)
    params = {
        "bounds": bounds, "xTicks": x_ticks, "variable": str(variable),
        "interval": [_float(domain.start) if _finite(domain.start) else None,
                     _float(domain.end) if _finite(domain.end) else None],
        "interval_closed": [not domain.left_open, not domain.right_open],
        "points": [{"x": _float(point), **({"open": True} if not attained else {})} for point, attained in marks],
        "title": title, "description": description,
    }
    if drawn["kind"] == "quadratic":
        axis, lowest = drawn["vertex"]
        # The axis position is read from its tick; a "P(h, k)" label would crowd the interval's end points.
        params.update(coefficient=_float(drawn["coefficient"]), vertex=[_float(axis), _float(lowest)],
                      yLabel=short_label(lowest), showVertex=show_vertex, vertexLabel="")
    elif drawn["kind"] == "linear":
        params.update(slope=_float(drawn["slope"]), intercept=_float(drawn["intercept"]))
    else:
        if domain.start < 0 < domain.end:
            raise GraphUnavailable("domain_crosses_pole")
        params.update(a=_float(drawn["a"]), b=_float(drawn["b"]), negative=bool(domain.end <= 0))
        if drawn.get("c"):
            params["c"] = _float(drawn["c"])
    if mark_sign:
        if drawn["kind"] == "reciprocal_sum":
            raise GraphUnavailable("sign_marking_unsupported")
        params.update(markSign=mark_sign, strict=strict)
    graph = {"kind": drawn["kind"], "params": params}
    if caption:
        graph["caption"] = caption
    return graph


def interval_function_graph(function, variable, domain, *, title, caption=None):
    """Draw an exact numeric curve on its domain; never choose unknown parameters."""
    if not isinstance(domain, sp.Interval):
        raise GraphUnavailable("domain_unsupported")
    drawn = family(function, variable)
    marks = drawable(drawn, variable, domain_points(domain))
    vertex = drawn['kind'] == 'quadratic'
    bounds, x_ticks = function_frame(drawn, variable, domain, marks=marks, show_vertex=vertex)
    return function_graph(
        drawn, variable, domain, bounds=bounds, x_ticks=x_ticks, marks=marks,
        show_vertex=vertex and drawn['vertex'][0] in domain,
        title=title, description=endpoint_story(drawn, variable, domain), caption=caption)


def reciprocal_image_graph(domain, *, source):
    """One v=1/u picture, with every allowed denominator interval kept separate."""
    if domain.contains(0) is not sp.false:
        raise GraphUnavailable("reciprocal_input_contains_zero")
    intervals, isolated = _pieces(domain)
    marks = {point: True for point in isolated}
    anchors = list(isolated)
    for interval in intervals:
        anchors.append(representative_parameter(interval))
        for point, attained in domain_points(interval):
            if point != 0:
                marks[point] = marks.get(point, False) or attained
                anchors.append(point)
    if not anchors:
        raise GraphUnavailable("reciprocal_input_empty")
    # Reference samples on both sides keep the two branches recognisable even
    # when this question uses just one of them. Do not bridge input holes.
    reference = min(abs(value) for value in anchors)
    anchors.extend([-2 * reference, 2 * reference])
    bounds = window([_float(value) for value in anchors], [_float(1 / value) for value in anchors])
    u = sp.Symbol('u', real=True)
    drawn = family(1/u, u)
    points = sorted(marks.items())
    _check_function_marks(drawn, u, bounds, points)
    if any(abs(_float(point)) < (bounds[1] - bounds[0]) / 400 for point in marks):
        raise GraphUnavailable("reciprocal_endpoint_not_visible")
    pieces = [{"from": _float(part.start) if _finite(part.start) else None,
               "to": _float(part.end) if _finite(part.end) else None,
               "left_closed": not part.left_open and _finite(part.start),
               "right_closed": not part.right_open and _finite(part.end)} for part in intervals]
    return {"kind": "reciprocal_sum", "params": {
        "a": 0, "b": 1, "negative": False, "bounds": bounds,
        "variable": "u", "outputVariable": "v", "interval": [None, None],
        "interval_closed": [False, False], "pieces": pieces,
        "points": [{"x": _float(point), **({"open": True} if not attained else {})}
                   for point, attained in points],
        "xTicks": ticks([sp.S.Zero, *marks], *bounds[:2]),
        "yTicks": ticks([1/point for point in marks], *bounds[2:], width=PLOT_HEIGHT),
        "title": "反比例函数 v=1/u", "description": f"u={source}，输入范围为 {plain(domain)}；深色曲线对应本题范围"},
        "caption": rf'$u={source}$，$v=\frac{{1}}{{u}}$。深色为本题范围，浅色为参考；实心点可取，空心点不取。'}


def _axis_reach(axis, parameter, allowed, step):
    """The axis positions reachable for parameters in ``allowed``, one step inside its open ends."""
    if allowed == sp.S.Reals:
        return [-float("inf"), float("inf")]
    if not isinstance(allowed, sp.Interval):
        raise GraphUnavailable("axis_parameter_domain_unsupported")
    rising = sp.diff(axis, parameter) > 0
    ends = [(allowed.start, bool(allowed.left_open)), (allowed.end, bool(allowed.right_open))]
    if not rising:
        ends.reverse()
    reach = []
    for side, (end, open_end) in enumerate(ends):
        if not _finite(end):
            reach.append(float("inf") * (1 if side else -1))
            continue
        image = _float(axis.subs(parameter, end))
        reach.append(image + (step if side == 0 else -step) * open_end)
    return reach


def _axis_extrema(expression, axis, low, high):
    """Exact extrema of a polynomial of degree at most two on a closed axis track."""
    if low > high:
        return []
    poly = sp.Poly(expression, axis)
    positions = [low, high]
    if poly.nth(2) != 0:
        stationary = -poly.nth(1) / (2 * poly.nth(2))
        if low <= stationary <= high:
            positions.append(stationary)
    return [poly.eval(position) for position in positions]


def axis_explorer(function, variable, parameter, domain, *, breakpoints, start, target, allowed=sp.S.Reals,
                  within=None, title, description, caption=None):
    """Move ``a x^2 + b(p) x + c(p)`` by its axis, with fixed ``a`` and affine ``b``.

    The inverse parameter map and quadratic-or-lower constant are expressed in ``h=-b/(2a)``,
    so the page draws the original family as ``a(x-h)^2 + c(h) - a h^2`` at every position.
    The track covers every case boundary; ``within``
    keeps the same window but lets the axis move only over that set of parameters.
    """
    if not isinstance(domain, sp.Interval) or parameter is None:
        raise GraphUnavailable("domain_unsupported")
    expression = sp.expand(function)
    if not expression.is_polynomial(variable) or sp.degree(expression, variable) != 2:
        raise GraphUnavailable("family_unsupported")
    poly = sp.Poly(expression, variable)
    leading, slope, constant = poly.nth(2), poly.nth(1), poly.nth(0)
    if (not _finite(leading) or slope.free_symbols != {parameter}
            or not slope.is_polynomial(parameter) or not constant.is_polynomial(parameter)):
        raise GraphUnavailable("axis_not_movable")
    slope_poly, constant_poly = sp.Poly(slope, parameter), sp.Poly(constant, parameter)
    if (slope_poly.degree() != 1 or constant_poly.degree() > 2
            or not all(_finite(value) for value in (*slope_poly.all_coeffs(), *constant_poly.all_coeffs()))):
        raise GraphUnavailable("axis_not_movable")
    axis = sp.expand(-slope / (2 * leading))
    offset, axis_slope = axis.subs(parameter, 0), sp.diff(axis, parameter)
    h = sp.Dummy("axis", real=True)
    parameter_scale, parameter_offset = 1 / axis_slope, -offset / axis_slope
    constant_by_axis = sp.Poly(sp.expand(constant.subs(parameter, parameter_scale * h + parameter_offset)), h)
    a, c, c1, c2, scale, parameter_zero = map(_float, (
        leading, constant_by_axis.nth(0), constant_by_axis.nth(1), constant_by_axis.nth(2),
        parameter_scale, parameter_offset))
    if not all(isfinite(number) for number in (a, c, c1, c2, scale, parameter_zero)) or a == 0 or scale == 0:
        raise GraphUnavailable("axis_not_movable")
    ends = [point for point in (domain.start, domain.end) if _finite(point)]
    turns = [sp.simplify(axis.subs(parameter, point)) for point in breakpoints]
    anchors = [_float(value) for value in (*ends, *turns)] or [0.0]
    low, high = min(anchors), max(anchors)
    span = max(high - low, 0.5)
    step = _step(span) / 25
    track = [low - span * 0.6, high + span * 0.6]
    reach = _axis_reach(axis, parameter, allowed, step)
    track = [max(track[0], reach[0]), min(track[1], reach[1])]
    track = [round(step * -int(-track[0] // step), 6), round(step * int(track[1] // step), 6)]
    if track[0] >= track[1]:
        raise GraphUnavailable("axis_track_empty")
    window_track = track
    if within is not None:
        reach = _axis_reach(axis, parameter, within, step)
        low_end, high_end = max(track[0], reach[0]), min(track[1], reach[1])
        track = [round(step * ceil(low_end / step - 1e-9), 6), round(step * floor(high_end / step + 1e-9), 6)]
        if track[0] >= track[1]:
            raise GraphUnavailable("axis_track_empty")
        start = None
    value = round(step * round((track[0] + track[1]) / 2 / step), 6) if start is None else \
        min(track[1], max(track[0], round(step * round(_float(axis.subs(parameter, start)) / step), 6)))
    # The slider is continuous.  Its endpoints must describe a whole interval
    # of allowed parameters, and rounding must not put an open endpoint back in.
    scope = allowed if within is None else sp.Intersection(allowed, within)
    for position in (*track, value):
        point = (sp.Rational(str(position)) - offset) / axis_slope
        if scope.contains(point) is not sp.true:
            raise GraphUnavailable("axis_parameter_outside_domain")
    margin = span * 0.3
    xs = [min(0.0, window_track[0]) - margin, max(0.0, window_track[1]) + margin]
    axis_low, axis_high = (sp.Rational(str(value)) for value in window_track)
    values = [sp.S.Zero]
    for end in ends:
        values.extend(_axis_extrema(leading * end**2 - 2 * leading * h * end + constant_by_axis.as_expr(),
                                    h, axis_low, axis_high))
    values.extend(_axis_extrema(constant_by_axis.as_expr() - leading * h**2, h,
                                max(axis_low, domain.start), min(axis_high, domain.end)))
    ys = list(map(_float, values))
    y_span = max(max(ys) - min(ys), 1.0)
    bounds = [xs[0], xs[1], min(ys) - y_span * 0.15, max(ys) + y_span * 0.15]
    marks = [{"x": _float(turn), "label": short_label(turn)} for turn in turns
             if _finite(turn) and all(sp.simplify(turn - end) != 0 for end in ends)]
    params = {
        "bounds": bounds, "xTicks": ticks(ends, bounds[0], bounds[1]), "variable": str(variable),
        "interval": [_float(domain.start) if _finite(domain.start) else None,
                     _float(domain.end) if _finite(domain.end) else None],
        "interval_closed": [not domain.left_open and _finite(domain.start), not domain.right_open and _finite(domain.end)],
        "points": [], "title": title, "description": description,
        "coefficient": a, "constant": c, "axis": {"min": track[0], "max": track[1], "step": step, "value": value},
        "parameter": {"name": str(parameter), "scale": scale, "offset": parameter_zero},
        "marks": marks, "target": target,
    }
    if c1 != 0 or c2 != 0:
        params["constant_by_axis"] = {"linear": c1, "quadratic": c2}
    graph = {"kind": "axis_explorer", "params": params}
    if caption:
        graph["caption"] = caption
    return graph


def mark_signature(drawn, variable, bounds, point, attained):
    value = value_at(drawn, point, variable)
    # Compare actual drawing distances, not rounded buckets: two almost
    # coincident points may lie on opposite sides of a bucket boundary.
    return _PointSignature((_float(point) - bounds[0]) / (bounds[1] - bounds[0]) * PLOT_WIDTH,
                           (_float(value) - bounds[2]) / (bounds[3] - bounds[2]) * PLOT_HEIGHT, attained)


# --- Parameter sets on a number line ----------------------------------------------

def _pieces(value):
    """Intervals and isolated points of a real set, or GraphUnavailable."""
    if value == sp.S.Reals:
        value = sp.Interval(-sp.oo, sp.oo)
    parts = value.args if isinstance(value, sp.Union) else (() if value == sp.S.EmptySet else (value,))
    intervals, points = [], []
    for piece in parts:
        if isinstance(piece, sp.Interval):
            intervals.append(piece)
        elif isinstance(piece, sp.FiniteSet) and all(_finite(point) for point in piece):
            points.extend(piece)
        else:
            raise GraphUnavailable("set_unsupported")
    return intervals, points


def _separated_line_marks(intervals, points, low, high, *, reason="marks_overlap"):
    """Different exact ends/isolated points must remain different visible marks."""
    marks = set(points)
    for piece in intervals:
        marks.update(point for point in (piece.start, piece.end) if _finite(point))
    ordered = sorted(marks, key=_float)
    for left, right in pairwise(ordered):
        if (_float(right) - _float(left)) / (high - low) * LINE_WIDTH < LINE_MARK_GAP:
            raise GraphUnavailable(reason)


def number_lines(sets, variable, *, title):
    """Specs for several parameter sets on one shared axis, so the pictures compare."""
    decomposed = [_pieces(value) for value in sets]
    ends = []
    for intervals, points in decomposed:
        for piece in intervals:
            ends.extend(point for point in (piece.start, piece.end) if _finite(point))
        ends.extend(points)
    ends = sorted(set(ends), key=_float)
    if ends:
        low, high = _float(ends[0]), _float(ends[-1])
        span = max(high - low, 1.0)
        low, high = low - max(span * 0.25, 0.75), high + max(span * 0.25, 0.75)
    else:
        low, high = -1.0, 1.0
    labels = [[_float(point), short_label(point)] for point in ends]
    graphs, signatures = [], []
    for value, (intervals, points) in zip(sets, decomposed, strict=True):
        _separated_line_marks(intervals, points, low, high)
        pieces = [{"from": _float(piece.start) if _finite(piece.start) else None,
                   "to": _float(piece.end) if _finite(piece.end) else None,
                   "left_closed": not piece.left_open and _finite(piece.start),
                   "right_closed": not piece.right_open and _finite(piece.end)} for piece in intervals]
        signatures.append((
            tuple((None if row["from"] is None else _pixel(row["from"], low, high, LINE_WIDTH), row["left_closed"],
                   None if row["to"] is None else _pixel(row["to"], low, high, LINE_WIDTH), row["right_closed"])
                  for row in pieces),
            tuple(_pixel(_float(point), low, high, LINE_WIDTH) for point in points)))
        graphs.append({"kind": "number_line", "params": {
            "bounds": [low, high], "pieces": pieces, "points": [{"x": _float(point)} for point in points],
            "ticks": labels, "variable": str(variable),
            "title": title, "description": f"{variable} 的取值集合：{plain(value)}"}})
    # Sibling options use one axis. A tiny endpoint change across pictures
    # is no more distinguishable than overlapping endpoints in one picture.
    _separated_line_marks([], ends, low, high, reason="options_indistinct")
    require_distinct(signatures)
    return graphs
