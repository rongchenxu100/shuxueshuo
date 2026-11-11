"""Step interactions compiled from frozen exact seeds.

The Q13 gold runs the real recording offline and compiles the seeds actually
committed with each card; unit cases build seeds from the real capabilities.
"""

from copy import deepcopy
from pathlib import Path

import pytest
import sympy as sp
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three import goals, interaction, runner
from shuxueshuo_server.graph_lesson.stage_three.capabilities import (
    select_quantifier_policy,
)
from shuxueshuo_server.graph_lesson.stage_three.capabilities.parametric import (
    partition_interval_cases,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.presentation import (
    append_goal_finalization,
    record_seed,
)
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.graph_stage_three_faults import offline_dispatch
from tests.solver.test_graph_stage_three_batch_six import _source
from tests.solver.test_graph_stage_three_execution import store
from tests.solver.test_graph_stage_three_goal_presentation import state_with_boundary
from tests.solver.test_graph_stage_three_recorded import (
    forbid_live_providers_and_network,  # noqa: F401 — shared autouse fixture
)

x, a = sp.Symbol("x", real=True), sp.Symbol("a", real=True)
TARGET = "/root/goals/0"


@pytest.fixture(scope="module")
def registry():
    return interaction.load_registry()


@pytest.fixture(scope="module")
def q13(tmp_path_factory):
    directory = tmp_path_factory.mktemp("interactions") / "q13"
    source, _, _ = _source(directory)
    output = directory / "stage-three"
    result = runner.run_sample(source, output, hooks={"calculation_dispatch": offline_dispatch})
    assert result["status"] == "completed"
    durable = store(output)
    cards = {}
    for card in durable.export()["math_steps"]:
        cards.setdefault(card["route_id"], []).append(card)
    seeds = {route: durable.checkpoint(TARGET, route)["driver_state"]["interaction_seeds"] for route in cards}
    return {"cards": cards, "seeds": seeds}


def _compiled(q13, registry, route):
    results, pending = interaction.compile_route(q13["seeds"][route], registry)
    assert pending == []
    for chunk, _ in results:
        interaction.validate_chunk(chunk)
    return results


def _labels(part):
    return [option["label"] for option in part["interaction"]["options"]]


def _correct(part):
    expected = part["expected_answer"]["one_of"]
    return [option["label"] for option in part["interaction"]["options"] if option["value"] in expected]


def _diagnostic(diagnostics, generator, text=None):
    return [row for row in diagnostics if row.get("generator") == generator
            and (text is None or text in row["label"])]


def _boundary_goal_rule(registry):
    return next(rule for rule in registry["merges"] if rule["id"] == "boundary-goal")


# --- Rules --------------------------------------------------------------------------

def test_registry_validates_and_rejects_unknown_or_ambiguous_rules(registry):
    assert interaction.registry_revision(registry) == interaction.registry_revision(deepcopy(registry))
    broken = deepcopy(registry)
    broken["templates"]["policy"]["parts"][0]["distractors"].append({"generator": "made_up"})
    with pytest.raises(ValueError, match="generator_not_allowed"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["generators"].append("made_up")
    with pytest.raises(ValueError, match="unimplemented_generator"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["policy"]["parts"][0]["distractors"].append({"generator": "drop_piece"})
    with pytest.raises(ValueError, match="generator_not_allowed"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["merges"].append({**deepcopy(broken["merges"][0]), "id": "duplicate"})
    with pytest.raises(ValueError, match="ambiguous_merge"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["policy"]["repeat"] = "sometimes"
    with pytest.raises(ValidationError):
        interaction.validate_registry(broken)


def test_overrides_and_merge_rows_are_checked_as_complete_rules(registry):
    broken = deepcopy(registry)
    broken["overrides"]["method-separation#quantifier"]["policy"]["parts"][0]["title"] = 17
    with pytest.raises(ValidationError):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    _boundary_goal_rule(broken)["parts"][0]["rows"][1]["seed"] = 2
    with pytest.raises(ValueError, match="seed_index_out_of_range"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["boundary_only"] = {"repeat": "always", "parts": deepcopy(_boundary_goal_rule(registry)["parts"])}
    with pytest.raises(ValueError, match="seed_index_out_of_range"):
        interaction.validate_registry(broken)


@pytest.mark.parametrize("location", ["template", "merge", "override"])
@pytest.mark.parametrize("limits", [{"min_options": 3, "max_options": 2}, {"min_options": 5}])
def test_registry_rejects_conflicting_option_limits(registry, location, limits):
    broken = deepcopy(registry)
    if location == "template":
        part = broken["templates"]["variable_reorder"]["parts"][0]
    elif location == "merge":
        part = _boundary_goal_rule(broken)["parts"][0]
    else:
        broken["overrides"]["method-test#step"] = {"variable_reorder": {"parts": [{}]}}
        part = broken["overrides"]["method-test#step"]["variable_reorder"]["parts"][0]
    part.update(limits)
    with pytest.raises(ValueError, match="interaction.option_limits_conflict"):
        interaction.validate_registry(broken)


def test_registry_checks_default_choice_minimum_against_explicit_limit(registry):
    broken = deepcopy(registry)
    part = broken["templates"]["policy"]["parts"][0]
    del part["min_options"]
    part["max_options"] = 2
    with pytest.raises(ValueError, match="interaction.option_limits_conflict"):
        interaction.validate_registry(broken)


def test_interaction_code_and_rules_stay_out_of_the_mathematical_fingerprint():
    paths = runner.fingerprint()
    assert not any(path.endswith("stage_three/interaction.py") or "interactions/" in path
                   or "interaction" in path.rsplit("/", 1)[-1] for path in paths)
    assert any(path.endswith("stage_three/presentation.py") for path in paths)
    assert len(interaction.engine_revision()) == 64


def test_borrow_card_changes_only_the_interaction_engine_revision(monkeypatch):
    from shuxueshuo_server.graph_lesson.stage_three import domain_borrow

    source = Path(domain_borrow.__file__).resolve()
    math_before, interaction_before = runner.fingerprint(), interaction.engine_revision()
    read_bytes = Path.read_bytes

    def changed_card(path):
        content = read_bytes(path)
        return content + b"\n# revised borrow card wording\n" if path.resolve() == source else content

    monkeypatch.setattr(Path, "read_bytes", changed_card)
    assert runner.fingerprint() == math_before
    assert interaction.engine_revision() != interaction_before


def test_override_replaces_fields_for_one_method_step(registry):
    seed = {"template": "policy", "method_ref": "method-separation#quantifier", "display_unit": "policy"}
    rule = interaction.select_rule(registry, [seed])
    names = [row["generator"] for row in rule["parts"][0]["distractors"]]
    assert "flip_direction" in names and "endpoint_only" not in names
    assert rule["parts"][0]["question"] == registry["templates"]["policy"]["parts"][0]["question"]
    default = interaction.select_rule(registry, [{**seed, "method_ref": "method-interval-extremum#quantifier"}])
    assert default == registry["templates"]["policy"]


# --- Q13 gold ---------------------------------------------------------------------

def test_every_card_freezes_a_seed_bound_to_its_final_hash(q13):
    for route, cards in q13["cards"].items():
        seeds = q13["seeds"][route]
        assert [seed["step_id"] for seed in seeds] == [card["step_id"] for card in cards]
        assert [seed["math_step_sha256"] for seed in seeds] == [card["math_step_sha256"] for card in cards]
        assert all(seed["status"] == "ready" and seed["contract"] == "graph-interaction-seed/v1" for seed in seeds)
        assert [seed["display_unit"] for seed in seeds[-2:]] == ["boundary", "goal_finalization"]
        assert seeds[-1]["template"] == "goal_minimum"
        assert all(seed["constraint_context"]["goal_ast"]["kind"] == "find_minimum" for seed in seeds)


def test_q13_interval_route_matches_the_designed_table(q13, registry):
    results = _compiled(q13, registry, "interval")
    chunks = [chunk for chunk, _ in results]
    assert [len(chunk["steps"]) for chunk in chunks] == [1] * 9 + [2]
    assert [chunk["status"] for chunk in chunks] == ["interactive", "interactive", *["readonly"] * 6,
                                                     "interactive", "interactive"]
    # The case card already states every extreme and the merge asks the union: per-case cards fold away.
    assert {chunks[index]["reason"] for index in range(2, 8)} == {"folded"}

    policy, diagnostics = results[0]
    part, = policy["parts"]
    assert part["interaction"]["type"] == "choice" and len(part["interaction"]["options"]) == 4
    assert part["question"].startswith(r"记 $g(x)=x^{2} + a x + 1$，对所有 $x \in")
    assert _correct(part) == [r"$x \in \left(0, \frac{1}{2}\right]$ 时，$g(x)_{\text{下端}} \geq 0$"]
    assert any(r"g(x)_{\text{上端}}" in label for label in _labels(part))
    assert any(r"$g(x)_{\min}$ 存在" in label for label in _labels(part))
    assert _diagnostic(diagnostics, "swap_bound")[0]["result"] == "witness"
    assert _diagnostic(diagnostics, "require_attained")[0] == {**_diagnostic(diagnostics, "require_attained")[0],
                                                               "result": "witness", "witness": "1"}
    assert _diagnostic(diagnostics, "swap_quantifier")[0]["result"] == "duplicate"
    assert _diagnostic(diagnostics, "endpoint_only")[0]["result"] == "unproven"
    # The current polynomial's endpoint threshold supplies an exact equality
    # witness, even though the original constant grid did not include it.
    assert _diagnostic(diagnostics, "flip_strictness")[0]["result"] == "witness"
    assert _diagnostic(diagnostics, "flip_strictness")[0]["witness"] == r"- \frac{5}{2}"

    cases, diagnostics = results[1]
    basis, locations = cases["parts"]
    assert basis["question"].startswith(r"求 $g(x)$ 在 $\left(0, \frac{1}{2}\right]$ 上的值域下端时")
    assert "对称轴" in _correct(basis)[0]
    assert {label for label in _labels(basis)} - set(_correct(basis)) == {
        r"判别式 $\Delta=a^{2} - 4$ 的正负", "参数 $a$ 的正负"}
    sign_feedback = next(option["feedback"] for option in basis["interaction"]["options"]
                         if option["label"] == "参数 $a$ 的正负")
    assert "$0$" in sign_feedback and "$-1$" in sign_feedback

    checklist = locations["interaction"]
    assert checklist["type"] == "checklist" and locations["title"] == "判断各情况的最值位置"
    rows = [(slot["label"], {option["value"]: option["label"] for option in slot["options"]})
            for slot in checklist["slots"]]
    chosen = [options[term] for (_, options), term in zip(rows, locations["expected_answer"]["terms"], strict=True)]
    assert [label for label, _ in rows] == [
        r"对称轴在区间右侧（$a \leq -1$）时，最小值", r"对称轴在区间内（$-1 < a < 0$）时，最小值",
        r"对称轴在区间左侧（$a \geq 0$）时，值域下端"]
    assert chosen == [r"在右端点 $x=\frac{1}{2}$ 处取到", r"在顶点 $x=- \frac{a}{2}$ 处取到",
                      r"当 $x\to 0^{+}$ 时趋近，取不到"]
    assert set(rows[0][1].values()) == {r"在右端点 $x=\frac{1}{2}$ 处取到", r"在顶点 $x=- \frac{a}{2}$ 处取到",
                                        r"当 $x\to 0^{+}$ 时趋近，取不到"}
    # The hollow end is the whole lesson: the same end drawn as attained is the distractor.
    assert "在左端点 $x=0$ 处取到" in rows[2][1].values()

    merged = chunks[8]["parts"][0]
    assert merged["title"] == "求参数范围"
    assert merged["question"] == r"三种情况下，都要求区间上的值域下端不小于 $0$。$a$ 的取值范围是什么？"
    assert merged["stem_board"] == {"caption": "各情况各自要满足", "lines": [
        r"① $a \leq -1$：$g(x)_{\min}=g\left(\frac{1}{2}\right)=\frac{a}{2} + \frac{5}{4} \geq 0$",
        r"② $-1 < a < 0$：$g(x)_{\min}=g\left(- \frac{a}{2}\right)=1 - \frac{a^{2}}{4} \geq 0$",
        r"③ $a \geq 0$：$g(x) > g\left(0\right)=1 \geq 0$"]}
    assert _correct(merged) == [r"$a \geq - \frac{5}{2}$"]
    assert len(merged["interaction"]["options"]) == 4
    assert not any("graph" in option for option in merged["interaction"]["options"])
    # Solving 1-a^2/4>=0 over every a instead of only -1<a<0 swallows the whole line.
    assert r"$a \in \mathbb{R}$" in _labels(merged)

    closing = chunks[9]
    assert [step["step_id"] for step in closing["steps"]] == [
        card["step_id"] for card in q13["cards"]["interval"][-2:]]
    checklist = closing["parts"][0]
    assert checklist["interaction"]["type"] == "checklist"
    keep, minimum = checklist["interaction"]["slots"]
    chosen = dict(zip(("keep", "minimum"), checklist["expected_answer"]["terms"], strict=True))
    assert next(o["label"] for o in keep["options"] if o["value"] == chosen["keep"]).startswith("成立，保留")
    assert next(o["label"] for o in minimum["options"] if o["value"] == chosen["minimum"]) == r"$- \frac{5}{2}$"
    assert "不存在" in [option["label"] for option in minimum["options"]]


def test_q13_separation_route_merges_boundary_and_goal(q13, registry):
    chunks = [chunk for chunk, _ in _compiled(q13, registry, "extremum")]
    assert [len(chunk["steps"]) for chunk in chunks] == [1, 1, 1, 1, 2]
    assert chunks[1]["status"] == "interactive"
    assert r"h(x)_{\text{上端}}" in _correct(chunks[1]["parts"][0])[0]
    assert chunks[-1]["status"] == "interactive"
    assert chunks[-1]["parts"][0]["interaction"]["type"] == "checklist"


def _option_graphs(part):
    expected = set(part["expected_answer"]["one_of"])
    return [(option["value"] in expected, option["label"], option.get("graph")) for option in part["interaction"]["options"]]


def test_q13_interval_route_draws_stems_options_and_the_closing_picture(q13, registry):
    chunks = [chunk for chunk, _ in _compiled(q13, registry, "interval")]
    assert "graph" not in chunks[0]["parts"][0]

    basis, locations = chunks[1]["parts"]
    explorer = basis["graph"]
    assert explorer == locations["graph"]
    assert explorer["kind"] == "axis_explorer"
    assert explorer["caption"] == r"拖动对称轴 $x=- \frac{a}{2}$，观察区间上的最低点在哪里"
    params = explorer["params"]
    # x^2+ax+1 = (x-h)^2 + 1 - h^2 with h=-a/2.
    assert (params["coefficient"], params["constant"], params["target"]) == (1.0, 1.0, "min")
    assert params["parameter"] == {"name": "a", "scale": -2.0, "offset": 0.0}
    assert "constant_by_axis" not in params
    assert params["interval"] == [0.0, 0.5] and params["interval_closed"] == [False, True]
    assert params["xTicks"] == [[0.0, "0"], [0.5, "1/2"]]
    axis = params["axis"]
    # The track crosses both case boundaries (a=0 and a=-1) and starts with the axis inside the interval.
    assert axis["min"] < 0 and axis["max"] > 0.5 and axis["value"] == 0.25

    # The finished step shows each case in the same window, its axis held inside that case.
    cases = locations["completion_graphs"]
    assert [graph["caption"] for graph in cases] == [
        r"情况①：$a \leq -1$，最小值在右端点 $x=\frac{1}{2}$ 处取到",
        r"情况②：$-1 < a < 0$，最小值在顶点 $x=- \frac{a}{2}$ 处取到",
        r"情况③：$a \geq 0$，当 $x\to 0^{+}$ 时趋近，最小值不存在"]
    assert "最小值不存在" in cases[-1]["params"]["description"]
    assert {json_key(graph["params"]["bounds"]) for graph in cases} == {json_key(params["bounds"])}
    tracks = [(graph["params"]["axis"]["min"], graph["params"]["axis"]["max"]) for graph in cases]
    # a=-1 (axis 1/2) belongs to case 1, a=0 (axis 0) to case 3; the open case 2 stops one step short.
    assert tracks[0][0] == 0.5 and tracks[2][1] == 0.0
    assert 0 < tracks[1][0] < tracks[1][1] < 0.5
    assert all(low <= graph["params"]["axis"]["value"] <= high for graph, (low, high) in zip(cases, tracks, strict=True))

    closing = chunks[9]["parts"][0]["completion_graph"]
    params = closing["params"]
    assert closing["kind"] == "quadratic" and params["coefficient"] == 1.0
    assert params["vertex"] == [1.25, -0.5625] and params["markSign"] == "below"
    # The vertex lies outside the interval: its dip stays in view, faded and unmarked.
    assert params["showVertex"] is False and [1.25, "5/4"] in params["xTicks"]
    assert params["bounds"][2] < -0.5625 < 0 < params["bounds"][3]
    assert params["interval_closed"] == [False, True] and params["points"] == [{"x": 0.0, "open": True}, {"x": 0.5}]
    assert "x=1/2 处函数值为 0" in params["description"] and "导数为 -3/2" in params["description"]
    assert "顶点 (5/4, -9/16)" in params["description"]
    assert closing["caption"].startswith(r"$a=- \frac{5}{2}$ 时")


def json_key(value):
    return repr(value)


def test_q13_interval_cards_read_as_case_derivations(q13):
    cards = {(card["display_unit"], tuple(card["case_path"])): card for card in q13["cards"]["interval"]}
    cases = cards[("interval_cases", ())]
    assert cases["explanation"].startswith(r"$g(x)$ 的图像开口向上，对称轴为 $x=- \frac{a}{2}$，")
    assert cases["title"] == "分类讨论最值"
    assert (r"① 当 $- \frac{a}{2} \geq \frac{1}{2}$，即 $a \leq -1$ 时，"
            r"$g(x)_{\min}=g\left(\frac{1}{2}\right)=\frac{a}{2} + \frac{5}{4}$；" in cases["explanation"])
    assert cases["explanation"].endswith(r"即 $a \geq 0$ 时，$g(x) > g\left(0\right)=1$，最小值不存在，只能趋近上述值。")
    # Case pictures are the conclusion; this card only carries the open derivation.
    assert "highlight" not in cases and cases["derivation"] is True
    right = cards[("classified_range", ("interval-case-1",))]["explanation"]
    assert right == ("$\\because\\ a \\leq -1$，$\\therefore\\ - \\frac{a}{2} \\geq \\frac{1}{2}$，\n"
                     "$g(x)$ 在 $\\left(0, \\frac{1}{2}\\right]$ 上单调递减，\n"
                     "$\\therefore\\ g(x)_{\\min}=g\\left(\\frac{1}{2}\\right)=\\frac{a}{2} + \\frac{5}{4}$。")
    left = cards[("classified_range", ("interval-case-3",))]
    assert left["explanation"].endswith(r"$\therefore\ g(x) > g\left(0\right)=1$，最小值不存在，只能趋近上述值。")
    solved = cards[("conditions", ("interval-case-1",))]["explanation"]
    assert solved == (r"由 $\begin{cases}a \leq -1,\\ \frac{a}{2} + \frac{5}{4} \geq 0\end{cases}$ "
                      r"得 $- \frac{5}{2} \leq a \leq -1$。")
    merged = cards[("interval_merge", ())]
    assert merged["title"] == "求参数范围"
    assert merged["explanation"] == (
        r"① 由 $\begin{cases}a \leq -1,\\ \frac{a}{2} + \frac{5}{4} \geq 0\end{cases}$ 得 $- \frac{5}{2} \leq a \leq -1$；" "\n"
        r"② 由 $\begin{cases}-1 < a < 0,\\ 1 - \frac{a^{2}}{4} \geq 0\end{cases}$ 得 $-1 < a < 0$；" "\n"
        r"③ 由 $\begin{cases}a \geq 0,\\ 1 \geq 0\end{cases}$ 得 $a \geq 0$。" "\n"
        r"综上，取并集得 $a \geq - \frac{5}{2}$。")
    assert merged["highlight"] == {"caption": "取并集", "layout": "merge", "result": r"$a \geq - \frac{5}{2}$", "items": [
        {"label": r"情况①（$a \leq -1$）", "math": r"- \frac{5}{2} \leq a \leq -1"},
        {"label": r"情况②（$-1 < a < 0$）", "math": r"-1 < a < 0"},
        {"label": r"情况③（$a \geq 0$）", "math": r"a \geq 0"}]}


def test_q13_separation_route_states_the_policy_without_a_picture_and_draws_the_closing_one(q13, registry):
    chunks = [chunk for chunk, _ in _compiled(q13, registry, "extremum")]
    policy = chunks[1]["parts"][0]
    assert policy["title"] == "转化为最值条件" and "graph" not in policy
    assert "h(x)$ 成立" in policy["question"]
    assert any(r"h(x)_{\text{上端}}" in label for label in _labels(policy))
    named = q13["cards"]["extremum"][0]["highlight"]["result"]
    assert "h(x)$，其中 $h(x)=" in named
    assert r"h(x)_{\text{上端}}" in q13["cards"]["extremum"][1]["highlight"]["result"]
    ranges = q13["cards"]["extremum"][2]
    assert "h(x)" in ranges["explanation"]
    assert "h(x)" in chunks[2]["parts"][0]["question"]
    assert chunks[-1]["parts"][0]["completion_graph"]["params"]["vertex"] == [1.25, -0.5625]


def test_pictures_fall_back_to_the_same_text_question(q13, registry, monkeypatch):
    drawn = _compiled(q13, registry, "interval")

    def unknown(*_, **__):
        raise interaction.GraphUnavailable("family_unknown")
    monkeypatch.setattr(interaction.drawing, "family", unknown)
    monkeypatch.setattr(interaction.drawing, "number_lines", unknown)
    monkeypatch.setattr(interaction.drawing, "axis_explorer", unknown)
    plain = interaction.compile_route(q13["seeds"]["interval"], registry)[0]

    def strip(part):
        part = deepcopy(part)
        part.pop("graph", None)
        part.pop("completion_graph", None)
        part.pop("completion_graphs", None)
        part["question"] = part["question"].split("图中取")[0]
        for option in part["interaction"].get("options", []):
            option.pop("graph", None)
        return part
    for (with_graphs, _), (without, diagnostics) in zip(drawn, plain, strict=True):
        assert [strip(part) for part in with_graphs["parts"]] == without["parts"]
        assert not any("graph" in option for part in without["parts"]
                       for option in part["interaction"].get("options", []))
        if with_graphs["status"] == "interactive" and any(
                "graph" in part or "completion_graph" in part or "completion_graphs" in part or any(
                    "graph" in option for option in part["interaction"].get("options", []))
                for part in with_graphs["parts"]):
            assert any(row.get("result") == "graph_fallback" for row in diagnostics)


def test_graph_rules_are_checked_against_their_answers(registry):
    broken = deepcopy(registry)
    broken["templates"]["policy"]["parts"][0]["graphs"] = {"options": "location_marks"}
    with pytest.raises(ValueError, match="graph_not_allowed:options"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["interval_cases"]["parts"][1]["graphs"] = {"stem": "case_sample"}
    with pytest.raises(ValueError, match="graph_not_allowed:stem"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    _boundary_goal_rule(broken)["parts"][0]["graphs"] = {"completion": "made_up"}
    with pytest.raises(ValueError, match="graph_not_allowed:completion"):
        interaction.validate_registry(broken)
    broken = deepcopy(registry)
    broken["templates"]["policy"]["parts"][0]["graphs"] = {"stem": "function_sample", "colour": "red"}
    with pytest.raises(ValidationError):
        interaction.validate_registry(broken)


def test_function_families_and_representatives():
    drawing = interaction.drawing
    quadratic = drawing.family(x**2 - sp.Rational(5, 2) * x + 1, x)
    assert quadratic["kind"] == "quadratic"
    assert quadratic["vertex"] == (sp.Rational(5, 4), -sp.Rational(9, 16))
    assert drawing.family((-x**2 - 1) / x, x) | {"function": None} == {
        "kind": "reciprocal_sum", "function": None, "a": -1, "b": -1, "c": 0}
    assert drawing.family(x + 3 + 4 / x, x) | {"function": None} == {
        "kind": "reciprocal_sum", "function": None, "a": 1, "b": 4, "c": 3}
    assert drawing.family(3 * x - 2, x)["kind"] == "linear"
    for unsupported in (1 / (x + 1), sp.sqrt(x), x**3, a * x):
        with pytest.raises(drawing.GraphUnavailable):
            drawing.family(unsupported, x)
    assert drawing.representative_parameter(sp.Interval(-sp.oo, -1)) == -2
    assert drawing.representative_parameter(sp.Interval.open(-1, 0)) == -sp.Rational(1, 2)
    assert drawing.representative_parameter(sp.Interval(0, sp.oo)) == 1
    assert drawing.representative_parameter(sp.S.Reals) == 0
    assert drawing.representative_parameter(sp.Interval(-sp.Rational(5, 2), -1)) in (-2, -sp.Rational(3, 2))
    with pytest.raises(drawing.GraphUnavailable):
        drawing.representative_parameter(sp.FiniteSet(1))
    assert [drawing.short_label(value) for value in (-sp.Rational(5, 2), sp.Integer(3), sp.Rational(1, 4))] == [
        "-5/2", "3", "1/4"]
    assert drawing.endpoint_story(quadratic, x, sp.S.Reals)
    whole = drawing.family(-x**2 + 2 * x + 3, x)
    (left, right, low, high), _ = drawing.function_frame(whole, x, sp.S.Reals)
    assert left <= -1 and right >= 3 and low <= 0 and high >= 4


def test_number_lines_share_an_axis_and_must_be_told_apart():
    drawing = interaction.drawing
    sets = [sp.Interval(-sp.Rational(5, 2), sp.oo), sp.Complement(sp.Interval(-sp.Rational(5, 2), sp.oo),
                                                                   sp.FiniteSet(-1)), sp.Interval.open(-1, 0)]
    graphs = drawing.number_lines(sets, a, title="a 的取值范围")
    assert {repr(graph["params"]["bounds"]) for graph in graphs} == {repr(graphs[0]["params"]["bounds"])}
    assert [len(graph["params"]["pieces"]) for graph in graphs] == [1, 2, 1]
    assert graphs[1]["params"]["pieces"][0]["right_closed"] is False
    close = [sp.Interval(0, 100), sp.Interval(sp.Rational(1, 1000), 100)]
    with pytest.raises(drawing.GraphUnavailable, match="options_indistinct"):
        drawing.number_lines(close, a, title="a")
    with pytest.raises(drawing.GraphUnavailable, match="set_unsupported"):
        drawing.number_lines([sp.ImageSet(sp.Lambda(x, x**2), sp.S.Integers)], a, title="a")


def test_first_card_compiles_from_its_own_seed_only(q13, registry):
    seeds = q13["seeds"]["interval"]
    alone, = interaction.compile_route(seeds[:1], registry, final=False)[0]
    route = interaction.compile_route(seeds, registry)[0][0]
    assert alone == route
    values = interaction.decode_value(seeds[0]["values"])
    context = interaction.decode_value(seeds[0]["context"])
    assert values["domain"] == context["domain"]
    assert not any(isinstance(value, sp.Set) for key, value in values.items() if key != "domain")


def test_known_conditions_restrict_witnesses_and_set_comparisons(q13, registry):
    known = _known("∀x∈(0,1/2]:x^2+a*x+1>=0", "a>=0")
    seeds = [{**seed, "constraint_context": known} for seed in q13["seeds"]["interval"]]
    unfolded = deepcopy(registry)
    del unfolded["overrides"]["method-interval-extremum#conditions"]
    results = interaction.compile_route(seeds, unfolded)[0]
    diagnostics = results[0][1]
    assert _diagnostic(diagnostics, "swap_bound")[0]["result"] != "witness"
    witnesses = [row["witness"] for row in diagnostics if row.get("result") == "witness"]
    assert witnesses and not any(witness.startswith("-") for witness in witnesses)
    # Case a<=-1 lies outside a>=0: these candidates agree with [-5/2,-1] on every allowed value.
    conditions, records = results[3]
    assert conditions["status"] == "readonly"
    assert {row["result"] for row in records if row.get("generator") in ("case_only", "flip_endpoint")} == {"unproven"}
    assert _diagnostic(records, "skip_intersection")[0]["result"] == "witness"

    unknown = [{**seed, "constraint_context": None} for seed in q13["seeds"]["interval"][:1]]
    chunk, _ = interaction.compile_route(unknown, registry)[0][0]
    assert chunk["status"] == "readonly" and chunk["reason"] == "known_conditions_unknown"


def _policy_seed(function, domain, quantifier, operator):
    policy = select_quantifier_policy(quantifier, operator, domain)["outputs"]["policy"]
    values = {"before": [function], "after": [], "function": function, "parameter_expression": sp.S.Zero,
              "policy": policy, "has_case": False, "x": x}
    return _seed("policy", values, {"x": x, "domain": domain, "parameter": a, "quantifier": quantifier},
                 method="method-interval-extremum#quantifier")


def test_strict_relation_distractors_are_checked_as_displayed(registry):
    # ∀x∈(0,1): ax²>0, i.e. 0 < f with an infimum that is never attained.
    seed = _policy_seed(a * x**2, sp.Interval.open(0, 1), "∀", "<")
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    swap, = _diagnostic(diagnostics, "swap_bound")
    assert swap["result"] != "witness"
    assert not any(r"_{\text{上端}}" in label for part in chunk["parts"] for label in _labels(part))
    strictness, = _diagnostic(diagnostics, "flip_strictness")
    assert strictness == {**strictness, "result": "witness", "witness": "0"}


def test_existential_policy_words_attainment_instead_of_claiming_universality(registry):
    seed = _policy_seed(x**2 + a, sp.Interval.open(0, 2), "∃", "<=")
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "interactive", diagnostics
    part, = chunk["parts"]
    assert "至少存在一个" in part["question"]
    assert "恒成立" not in part["question"]
    assert "等号成立时值域上端必须能取到" in _correct(part)[0]


@pytest.mark.parametrize("quantifier,operator,goal,swapped,feedback", [
    ("∃", "<", "至少有一个", "对所有 $x \\in \\left(0, 2\\right)$，$x^{2} + a > 0$ 都成立", "不要求每个"),
    ("∀", "<=", "对所有", "存在 $x \\in \\left(0, 2\\right)$，使 $x^{2} + a \\geq 0$", "不是找到一个就行"),
])
def test_policy_feedback_follows_the_question_quantifier(registry, quantifier, operator, goal, swapped, feedback):
    seed = _policy_seed(x**2 + a, sp.Interval.open(0, 2), quantifier, operator)
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 0})
    part, = chunk["parts"]
    assert part["feedback"]["answer"].startswith(f"把“{goal}")
    option, = (option for option in part["interaction"]["options"] if option["label"] == swapped)
    assert feedback in option["feedback"]


def test_extensions_see_only_the_reviewed_api():
    assert set(vars(interaction.EXTENSION_API)) == {
        "Candidate", "NotInteractive", "GraphUnavailable", "drawing", "BOUND_NAMES", "MIRROR", "FLIP_STRICTNESS",
        "decode_value", "known_set", "representatives", "range_at", "exact_set_equal",
        "latex", "math", "cmp", "finite", "attempt", "set_candidate", "set_check", "case_solution_answer",
        "flip_endpoint", "drop_piece", "skip_intersection", "flip_keep", "conditions_facts", "merge_facts",
        "goal_facts", "boundary_facts", "boundary_answer", "function_stem", "set_options", "named_function"}


def test_checklist_rows_respect_the_option_limit(monkeypatch):
    many = [interaction.Candidate(f"c{index}", f"选项 {index}", index) for index in range(6)]
    monkeypatch.setitem(interaction.ANSWERS, "test_many", {
        "kind": "fixed", "facts": lambda values, context: {"display": {}},
        "answer": lambda facts: [{"label": "一行", "answer": many[0]}],
        "generators": {"many": lambda facts, item: many[1:]}})
    part = {"component": "checklist", "title": "t", "max_options": 3,
            "rows": [{"seed": 0, "answer": {"from": "test_many"}, "distractors": [{"generator": "many"}]}]}
    seed = {"values": encode_value({}), "context": encode_value({})}
    body, _, _ = interaction._checklist_part(part, 1, "p1", [seed])
    slot, = body["interaction"]["slots"]
    assert len(slot["options"]) == 3
    assert "选项 0" in [option["label"] for option in slot["options"]]
    del part["max_options"]
    body, _, _ = interaction._checklist_part(part, 1, "p1", [seed])
    assert len(body["interaction"]["slots"][0]["options"]) == 4
    # Direct compilation also checks the final count, even if registry validation
    # was bypassed by a caller supplying a rule.
    part.update(min_options=3, max_options=2)
    with pytest.raises(interaction.NotInteractive, match="insufficient_options"):
        interaction._checklist_part(part, 1, "p1", [seed])


def test_compilation_is_stable_and_identity_tracks_the_rules(q13, registry):
    first = _compiled(q13, registry, "interval")
    assert first == _compiled(q13, registry, "interval")
    changed = deepcopy(registry)
    changed["templates"]["policy"]["parts"][0]["title"] = "换一个标题"
    revised = interaction.compile_route(q13["seeds"]["interval"], changed)[0]
    assert revised[0][0]["interaction_id"] != first[0][0]["interaction_id"]
    assert revised[1][0]["interaction_revision"] != first[1][0]["interaction_revision"]


# --- Unit cases built from the real capabilities -----------------------------------

POLICY = {"bound": "inf", "strict": False, "quantifier": "∀", "operator": "<="}


def _known(*facts):
    """The route context of a problem with these facts, as frozen in real seeds."""
    candidate = {"original_text": " ".join(facts),
                 "root": {"facts": list(facts), "goals": [{"kind": "find_range", "symbol": "a"}]}}
    return build_context(candidate, TARGET)


FREE = _known("∀x∈ℝ:x^2+a^2+1>=0")


def _seed(template, values, context, *, ordinal=1, unit=None, case_path=(), method="method-interval-extremum#select",
          known=FREE):
    return {"contract": "graph-interaction-seed/v1", "run_id": "run", "lesson_version": "lesson",
            "target_ref": TARGET, "route_id": "interval", "step_id": f"step-{ordinal:03d}-{unit or template}",
            "math_step_sha256": f"{ordinal:064x}", "ordinal": ordinal, "display_unit": unit or template,
            "method_ref": method, "case_path": list(case_path), "template": template, "status": "ready",
            "values": encode_value(values), "context": encode_value(context), "constraint_context": known}


def _cases(function, domain):
    return partition_interval_cases(function, x, a, domain, POLICY)["outputs"]["cases"]


def test_discriminant_is_not_called_wrong_when_it_is_a_sufficient_basis(registry):
    function, domain = (x + a)**2 - a, sp.Interval(0, sp.oo)
    cases = _cases(function, domain)
    seed = _seed("interval_cases", {"before": [function], "after": [], "cases": cases, "parameter": a},
                 {"x": x, "domain": domain, "parameter": a})
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    discriminant, = _diagnostic(diagnostics, "case_basis_alternatives", "判别式")
    assert discriminant["result"] == "unproven"
    assert not any("判别式" in label for part in chunk["parts"] if part["interaction"]["type"] == "choice"
                   for label in _labels(part))


def test_case_checklist_names_the_opening_when_the_parameter_flips_it(registry):
    function, domain = a * x**2 - a * x - 1, sp.Interval(1, 3)
    cases = _cases(function, domain)
    seed = _seed("interval_cases", {"before": [function], "after": [], "cases": cases, "parameter": a},
                 {"x": x, "domain": domain, "parameter": a})
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 0})
    locations = chunk["parts"][-1]
    slots = locations["interaction"]["slots"]
    # The constant case a=0 has no place to find; the axis x=1/2 does not move, so only the opening is named.
    assert [slot["label"] for slot in slots] == ["开口向下（$a < 0$）时，最小值", "开口向上（$a > 0$）时，最小值"]
    chosen = [next(option["label"] for option in slot["options"] if option["value"] == term)
              for slot, term in zip(slots, locations["expected_answer"]["terms"], strict=True)]
    assert chosen == ["在右端点 $x=3$ 处取到", "在左端点 $x=1$ 处取到"]
    # Dragging the axis cannot show a parabola that turns over: the picture stays a sample.
    assert locations.get("graph", {}).get("kind") != "axis_explorer"
    interaction.validate_chunk(chunk)


def test_axis_explorer_requires_an_invertible_affine_axis():
    drawing = interaction.drawing
    domain = sp.Interval(1, 2)
    common = {"breakpoints": [sp.Integer(-3)], "start": sp.Integer(-2), "target": "max", "title": "t",
              "description": "d"}
    graph = drawing.axis_explorer(x**2 + a * x + 4, x, a, domain, **common)
    params = graph["params"]
    assert (params["coefficient"], params["constant"]) == (1.0, 4.0)
    assert params["parameter"] == {"name": "a", "scale": -2.0, "offset": 0.0}
    assert params["marks"] == [{"x": 1.5, "label": "3/2"}] and params["axis"]["value"] == 1.0
    for moving in (a * x**2 + x, x**2 + x + a, x**2 + a**2 * x):
        with pytest.raises(interaction.GraphUnavailable, match="axis_not_movable"):
            drawing.axis_explorer(moving, x, a, domain, **common)
    # Only parameters the problem allows: a > -4 keeps the axis left of x=2.
    limited = drawing.axis_explorer(x**2 + a * x + 4, x, a, domain, **common, allowed=sp.Interval.open(-4, sp.oo))
    assert limited["params"]["axis"]["max"] <= 2


def _tie_seed():
    function, domain = -x**2 + x + a, sp.Interval(0, 1)
    case, = _cases(function, domain)
    assert case["range"]["candidates"][0]["location"] == "left_endpoint"
    values = {"before": [function], "after": [], "range": case["range"], "condition": case["condition"],
              "vertex": case["vertex"], "coefficient": case["coefficient"], "x": x, "domain": domain,
              "bound_value": case["range"]["inf"], "bound_attained": True, "case": case}
    return _seed("classified_range", values, {"x": x, "domain": domain, "parameter": a})


def _asking(registry):
    """The registry with the per-case location question enabled (the case checklist normally asks it)."""
    asking = deepcopy(registry)
    asking["templates"]["classified_range"]["repeat"] = "first"
    return asking


def test_tied_bound_positions_never_offer_a_correct_position_as_wrong(registry):
    seed = _tie_seed()
    registry = _asking(registry)
    chunk, diagnostics = interaction.build_chunk([seed], registry, {"previous": 0})
    right, = _diagnostic(diagnostics, "location_alternatives", "右端点")
    assert right["result"] == "also_correct"
    vertex, = _diagnostic(diagnostics, "location_alternatives", "顶点")
    assert vertex["result"] == "witness"
    assert not any("右端点" in label for part in chunk["parts"] for label in _labels(part))

    rule = deepcopy(registry["templates"]["classified_range"])
    rule["parts"][0]["component"] = "multi"
    compiled = interaction.compile_interaction([seed], rule, {"previous": 0}, interaction_id="0" * 24)
    part, = compiled["parts"]
    options = {option["value"]: option["label"] for option in part["interaction"]["options"]}
    required = {options[value] for value in part["expected_answer"]["required"]}
    assert required == {"在左端点 $x=0$ 处取到", "在右端点 $x=1$ 处取到"}


def test_insufficient_options_and_repeat_fall_back_to_readonly(registry):
    seed = _tie_seed()
    registry = _asking(registry)
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "insufficient_options" and chunk["parts"] == []
    chunk, _ = interaction.build_chunk([seed], registry, {"previous": 1})
    assert chunk["reason"] == "repeat"
    missing = {**seed, "status": "missing", "reason": "seed_encode_failed"}
    chunk, _ = interaction.build_chunk([missing], registry, {"previous": 0})
    assert chunk["reason"] == "seed_encode_failed"
    chunk, _ = interaction.build_chunk([{**seed, "template": "unknown"}], registry, {"previous": 0})
    assert chunk["reason"] == "no_rule"
    for result in (chunk,):
        interaction.validate_chunk(result)


def test_compiler_errors_become_readonly_results(registry):
    seed = _tie_seed()
    broken = {**seed, "values": encode_value({"before": [x]})}
    chunk, diagnostics = interaction.build_chunk([broken], _asking(registry), {"previous": 0})
    assert chunk["status"] == "readonly" and chunk["reason"] == "compile_error"
    assert diagnostics[0]["result"] == "compile_error"


def test_representatives_use_only_seed_data_and_include_set_endpoints():
    values = {"after": [sp.Interval(-sp.Rational(5, 2), sp.oo)], "x": x}
    points = interaction.representatives(values, {"domain": sp.Interval.Lopen(0, sp.Rational(1, 2))})
    assert -sp.Rational(5, 2) in points and len(points) <= interaction.MAX_REPRESENTATIVES
    restricted = interaction.representatives(values, {}, sp.Interval(-sp.oo, -1))
    assert all(point <= -1 for point in restricted)


# --- Merge planning ---------------------------------------------------------------

def _closing_pair():
    boundary = _seed("boundary", {"feasible_set": sp.Interval(-1, sp.oo),
                                  "checks": [{"point": sp.Integer(-1), "included": True, "holds": True}]},
                     {"parameter": a}, ordinal=4)
    goal = _seed("goal_minimum", {"goal_kind": "find_minimum", "status": "attained", "bound": sp.Integer(-1),
                                  "feasible_set": sp.Interval(-1, sp.oo), "attained": True},
                 {"parameter": a}, ordinal=5, unit="goal_finalization")
    return boundary, goal


def test_merge_prefix_waits_for_its_follower_until_the_route_ends(registry):
    boundary, goal = _closing_pair()
    groups, pending = interaction.plan_groups([boundary], registry, final=False)
    assert groups == [] and pending == [boundary]
    groups, pending = interaction.plan_groups([boundary], registry, final=True)
    assert groups == [[boundary]] and pending == []
    groups, _ = interaction.plan_groups([boundary, goal], registry, final=False)
    assert groups == [[boundary, goal]]
    other_case = {**goal, "case_path": ["case-1"]}
    assert interaction.plan_groups([boundary, other_case], registry, final=True)[0] == [[boundary], [other_case]]
    readonly_follower = {**goal, "status": "missing", "reason": "seed_encode_failed"}
    assert interaction.plan_groups([boundary, readonly_follower], registry, final=True)[0] == [
        [boundary], [readonly_follower]]
    chunk, _ = interaction.build_chunk([boundary, goal], registry, {"previous": 0})
    assert chunk["status"] == "interactive"
    assert [step["step_id"] for step in chunk["steps"]] == [boundary["step_id"], goal["step_id"]]


# --- Seed entry points -------------------------------------------------------------

def test_goal_seed_is_frozen_after_exact_values_change_the_hash():
    feasible = sp.Interval(-sp.Rational(5, 2), sp.oo)
    state = state_with_boundary(feasible)
    boundary_seed, = state["interaction_seeds"]
    assert boundary_seed["display_unit"] == "boundary"
    assert boundary_seed["math_step_sha256"] == state["fragments"][-1]["math_step_sha256"]
    answer = goals.finalize_goal({"kind": "find_minimum"}, feasible)
    evidence = goals.verify_goal_answer({"kind": "find_minimum"}, feasible, answer)
    updated = append_goal_finalization(state, answer, evidence)
    seed = updated["interaction_seeds"][-1]
    assert seed["display_unit"] == "goal_finalization" and seed["template"] == "goal_minimum"
    assert seed["math_step_sha256"] == updated["fragments"][-1]["math_step_sha256"]
    assert interaction.decode_value(seed["values"])["bound"] == -sp.Rational(5, 2)


def test_unencodable_seed_is_recorded_missing_without_touching_the_card():
    state = state_with_boundary(sp.Interval(0, 1))
    card = deepcopy(state["fragments"][-1])
    seed = record_seed(state, card, template="boundary", values={"value": sp.Lambda(x, x)})
    assert seed["status"] == "missing" and seed["reason"] == "seed_encode_failed"
    assert "values" not in seed and state["fragments"][-1] == card
