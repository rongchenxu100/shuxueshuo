"""Faithful interaction pictures, bounded sampling, and whole-option fallback."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import interaction
from shuxueshuo_server.graph_lesson.stage_three import interaction_graphs as drawing
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value

x, a = sp.symbols("x a", real=True)


@pytest.mark.parametrize('domain,vertex_visible,closed,marks', [
    (sp.Interval(-sp.oo, 1), True, [False, True], [{'x': 1.0}]),
    (sp.Interval.open(0, 1), False, [False, False], [{'x': 0.0, 'open': True}, {'x': 1.0, 'open': True}]),
    (sp.Interval(1, 2), False, [True, True], [{'x': 1.0}, {'x': 2.0}]),
])
def test_interval_quadratic_keeps_branch_domain_and_only_marks_attainable_vertex(domain, vertex_visible, closed, marks):
    graph = drawing.interval_function_graph(x**2-2, x, domain, title='当前段函数')
    interaction.graph_contract.validate_graph(graph)
    assert graph['kind'] == 'quadratic'
    assert graph['params']['vertex'] == [0, -2]
    assert graph['params']['showVertex'] is vertex_visible
    assert graph['params']['interval_closed'] == closed
    assert graph['params']['points'] == marks


def test_interval_quadratic_does_not_invent_an_unknown_parameter_value():
    with pytest.raises(drawing.GraphUnavailable, match='parameter_not_substituted'):
        drawing.interval_function_graph(a*x**2-x+2, x, sp.Interval.open(1, sp.oo), title='含参段')


@pytest.mark.parametrize(("low", "high", "expected"), [
    (0, 3, 1), (-3, 0, -1), (-1, 0, -sp.Rational(1, 2)),
    (0, sp.Rational(1, 2), sp.Rational(1, 4)),
    (sp.Rational(1, 10), sp.Rational(1, 5), sp.Rational(3, 20)),
])
@pytest.mark.parametrize(("left_open", "right_open"), [(False, False), (True, True), (True, False), (False, True)])
def test_representatives_stay_inside_and_keep_short_value_tiebreaks(low, high, expected, left_open, right_open):
    region = sp.Interval(low, high, left_open=left_open, right_open=right_open)
    point = drawing.representative_parameter(region)
    assert point == expected
    assert region.interior.contains(point) is sp.true


def test_huge_parameter_regions_do_not_enumerate_lattice_points(monkeypatch):
    def forbidden_range(*_):
        pytest.fail("representative selection must not enumerate the parameter interval")

    monkeypatch.setattr(drawing, "range", forbidden_range, raising=False)
    size = sp.Integer(10)**100
    assert drawing.representative_parameter(sp.Interval(-size, size)) == 0
    assert drawing.representative_parameter(sp.Interval(size, 3 * size)) == 2 * size


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("branch", [-1, 1])
def test_hook_halfline_frame_includes_the_turn_and_both_sides(sign, branch):
    domain = sp.Interval.open(0, sp.oo) if branch > 0 else sp.Interval.open(-sp.oo, 0)
    function, point = sign * (x + 9 / x), sp.Integer(3 * branch)
    drawn = drawing.family(function, x)
    bounds, ticks = drawing.function_frame(drawn, x, domain)
    left, right, low, high = bounds
    assert left < float(point) < right
    assert low < float(function.subs(x, point)) < high
    assert [float(point), str(point)] in ticks
    if branch > 0:
        assert right > float(point + 2)
    else:
        assert left < float(point - 2)


@pytest.mark.parametrize("domain", [sp.Interval(1, 8), sp.Interval.open(1, 8),
                                    sp.Interval(-8, -1), sp.Interval.open(-8, -1)])
def test_finite_hook_frame_includes_its_internal_turn(domain):
    point = sp.Integer(3 if domain.start > 0 else -3)
    drawn = drawing.family(x + 9 / x, x)
    bounds, ticks = drawing.function_frame(drawn, x, domain)
    assert bounds[0] < float(point) < bounds[1]
    assert bounds[2] < float(drawn["function"].subs(x, point)) < bounds[3]
    assert [float(point), str(point)] in ticks


@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("branch", [-1, 1])
def test_turn_at_finite_endpoint_preserves_open_or_closed_mark(branch, closed):
    domain = sp.Interval(0, 3, left_open=True, right_open=not closed) if branch > 0 else \
        sp.Interval(-3, 0, left_open=not closed, right_open=True)
    drawn = drawing.family(x + 9 / x, x)
    marks = drawing.drawable(drawn, x, drawing.domain_points(domain))
    bounds, ticks = drawing.function_frame(drawn, x, domain, marks=marks)
    graph = drawing.function_graph(drawn, x, domain, bounds=bounds, x_ticks=ticks, marks=marks,
                                   title="endpoint", description="endpoint")
    expected = {"x": float(3 * branch), **({} if closed else {"open": True})}
    assert graph["params"]["points"] == [expected]
    assert graph["params"]["interval_closed"] == ([False, closed] if branch > 0 else [closed, False])


@pytest.mark.parametrize("function", [1 / x, x - 9 / x])
def test_monotone_reciprocal_families_do_not_invent_turns(function):
    drawn = drawing.family(function, x)
    _, ticks = drawing.function_frame(drawn, x, sp.Interval.open(0, sp.oo))
    assert ticks == [[0.0, "0"]]


def test_stationary_point_outside_domain_is_not_added_as_an_interval_tick():
    drawn = drawing.family(x + 9 / x, x)
    _, ticks = drawing.function_frame(drawn, x, sp.Interval(4, 8))
    assert [3.0, "3"] not in ticks


@pytest.mark.parametrize("branch", [-1, 1])
@pytest.mark.parametrize("scale", ["small_turn", "large_domain"])
def test_hook_turn_lost_at_sampling_resolution_falls_back_to_text(branch, scale):
    if scale == "small_turn":
        function = x + sp.Rational(1, 10**12) / x
        domain = sp.Interval.open(0, sp.oo) if branch > 0 else sp.Interval.open(-sp.oo, 0)
    else:
        function = x + 1 / x
        domain = sp.Interval.Lopen(0, 10**12) if branch > 0 else sp.Interval.Ropen(-10**12, 0)
    drawn = drawing.family(function, x)
    with pytest.raises(drawing.GraphUnavailable, match="turn_not_visible"):
        drawing.function_frame(drawn, x, domain)
    diagnostics = []
    assert interaction._picture(lambda: drawing.function_frame(drawn, x, domain), diagnostics, 1) is None
    assert diagnostics == [{"part": 1, "result": "graph_fallback", "reason": "turn_not_visible"}]


def test_number_lines_keep_separated_holes_and_endpoint_closure():
    sets = [sp.Interval(0, 20), sp.Complement(sp.Interval(0, 20), sp.FiniteSet(10)),
            sp.Interval.open(0, 20)]
    graphs = drawing.number_lines(sets, a, title="range")
    assert len(graphs) == 3
    assert graphs[0]["params"]["pieces"][0]["left_closed"] is True
    assert graphs[2]["params"]["pieces"][0]["left_closed"] is False
    hole = graphs[1]["params"]["pieces"]
    assert hole[0]["to"] == hole[1]["from"] == 10
    assert hole[0]["right_closed"] is hole[1]["left_closed"] is False


epsilon = sp.Rational(1, 10**10)


@pytest.mark.parametrize("sets", [
    [sp.Complement(sp.Interval(0, 100), sp.FiniteSet(epsilon)),
     sp.Complement(sp.Interval.Lopen(0, 100), sp.FiniteSet(epsilon))],
    [sp.Union(sp.FiniteSet(-epsilon), sp.Interval(0, 100)), sp.Interval(0, 100)],
    [sp.FiniteSet(0, epsilon, 100), sp.FiniteSet(0, 100)],
    [sp.Interval(0, epsilon), sp.Interval(0, 100)],
])
def test_number_lines_reject_overlapping_distinct_ends_holes_and_singletons(sets):
    with pytest.raises(drawing.GraphUnavailable, match="marks_overlap"):
        drawing.number_lines(sets, a, title="range")


def test_nearby_endpoints_in_different_options_cannot_escape_at_pixel_bucket_boundary():
    boundary, shift = sp.Rational(125, 16), sp.Rational(1, 10**8)
    sets = [sp.Interval(boundary - shift, 100), sp.Interval(boundary + shift, 100), sp.Interval(0, 100)]
    with pytest.raises(drawing.GraphUnavailable, match="options_indistinct"):
        drawing.number_lines(sets, a, title="range")


def test_same_exact_number_line_endpoint_can_differ_only_in_open_or_closed_state():
    graphs = drawing.number_lines([sp.Interval(0, 100), sp.Interval.Lopen(0, 100),
                                   sp.Interval.Ropen(0, 100)], a, title="range")
    assert len(graphs) == 3
    assert [(graph["params"]["pieces"][0]["left_closed"], graph["params"]["pieces"][0]["right_closed"])
            for graph in graphs] == [(True, True), (False, True), (True, False)]


def test_nearby_function_marks_cannot_escape_at_pixel_bucket_boundary():
    drawn = drawing.family(x**2, x)
    bounds = [0, 100, 0, 10000]
    boundary, shift = sp.Rational(70, 3), sp.Rational(1, 10**8)
    marks = [drawing.mark_signature(drawn, x, bounds, point, True)
             for point in (boundary - shift, boundary + shift)]
    with pytest.raises(drawing.GraphUnavailable, match="options_indistinct"):
        drawing.require_distinct(marks)


def test_function_marks_allow_clear_position_or_attainment_difference():
    drawn = drawing.family(x**2, x)
    bounds = [0, 100, 0, 10000]
    drawing.require_distinct([drawing.mark_signature(drawn, x, bounds, point, attained)
                              for point, attained in [(10, True), (10, False), (50, True)]])


@pytest.mark.parametrize("endpoint", [sp.Rational(1, 10000), -sp.Rational(1, 10000)])
def test_same_function_picture_rejects_overlapping_open_and_closed_endpoints(endpoint):
    domain = sp.Interval.Lopen(0, endpoint) if endpoint > 0 else sp.Interval.Ropen(endpoint, 0)
    drawn = drawing.family(x*x + 1, x)
    marks = drawing.domain_points(domain)
    bounds, ticks = drawing.function_frame(drawn, x, domain, marks=marks)
    with pytest.raises(drawing.GraphUnavailable, match="marks_overlap"):
        drawing.function_graph(drawn, x, domain, bounds=bounds, x_ticks=ticks, marks=marks,
                               title="区间端点", description="一个空心点、一个实心点")
    facts = {"function": x*x + a*x + 1, "parameter": a, "known": sp.S.Reals, "x": x, "domain": domain}
    diagnostics = []
    assert interaction._picture(interaction._function_stem, diagnostics, 1, facts, {}, {}) is None
    assert diagnostics == [{"part": 1, "result": "graph_fallback", "reason": "marks_overlap"}]


def test_q13_half_interval_keeps_distinct_open_and_closed_function_endpoints():
    domain = sp.Interval.Lopen(0, sp.Rational(1, 2))
    drawn = drawing.family(x*x + 1, x)
    marks = drawing.domain_points(domain)
    bounds, ticks = drawing.function_frame(drawn, x, domain, marks=marks)
    graph = drawing.function_graph(drawn, x, domain, bounds=bounds, x_ticks=ticks, marks=marks,
                                   title="区间端点", description="一个空心点、一个实心点")
    assert graph["params"]["points"] == [{"x": 0.0, "open": True}, {"x": 0.5}]


def test_repeated_same_exact_function_mark_is_not_a_distinct_endpoint_collision():
    domain = sp.Interval(0, 1)
    drawn = drawing.family(x*x, x)
    marks = [(sp.sqrt(8) / 2, True), (sp.sqrt(2), True)]
    bounds, ticks = drawing.function_frame(drawn, x, domain, marks=marks)
    graph = drawing.function_graph(drawn, x, domain, bounds=bounds, x_ticks=ticks, marks=marks,
                                   title="同一点", description="同一精确坐标的重复标记")
    assert graph["params"]["points"][0] == graph["params"]["points"][1]


def test_unreadable_set_picture_keeps_the_entire_original_text_question(monkeypatch):
    answer = sp.Complement(sp.Interval(0, 100), sp.FiniteSet(epsilon))
    pieces = list(answer.args)
    values = {"before": [x], "after": [answer], "x": x, "solutions": pieces,
              "cases": [{"parameter": a, "condition": piece.contains(a), "domain": piece} for piece in pieces],
              "results": [{"outputs": {"conditions": [a >= 0, a <= 100], "combiner": "all"}} for _ in pieces]}
    seed = {"values": encode_value(values),
            "context": encode_value({"parameter": a})}
    monkeypatch.setattr(interaction, "known_set", lambda _: sp.S.Reals)
    plain = deepcopy(interaction.load_registry()["templates"]["interval_merge"]["parts"][0])
    plain.pop("graphs", None)
    part = {**plain, "graphs": {"options": "parameter_sets"}}
    expected, _, _ = interaction._choice_part(plain, 0, "set-options", seed)
    actual, diagnostics, _ = interaction._choice_part(part, 0, "set-options", seed)
    assert actual == expected
    assert len(actual["interaction"]["options"]) >= 3
    assert all("graph" not in option for option in actual["interaction"]["options"])
    assert {"part": 0, "result": "graph_fallback", "reason": "marks_overlap"} in diagnostics
