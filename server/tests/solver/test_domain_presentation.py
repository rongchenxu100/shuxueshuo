"""Domain card wording shows mathematical conclusions, not teaching tips."""

from tests.solver.test_graph_stage_three_function_domain import candidate, execute


def test_domain_cards_show_conclusions_and_math_derivation():
    _, state = execute(candidate())
    by_unit = {fragment["display_unit"]: fragment for fragment in state["fragments"]}

    locations = by_unit["domain_locations"]
    assert [item["label"] for item in locations["highlight"]["items"]] == ["被开方数", "分母"]
    assert [item["math"] for item in locations["highlight"]["items"]] == ["x - 1", "x - 2"]
    assert "原式为 $" in locations["explanation"]
    assert "须检查 $x - 1$" in locations["explanation"]
    assert "须检查 $x - 2$" in locations["explanation"]
    assert "逐层检查" not in locations["explanation"]

    conditions = by_unit["domain_conditions"]
    assert [item["label"] for item in conditions["highlight"]["items"]] == ["被开方数", "分母"]
    assert conditions["highlight"]["items"][0]["math"] == r"x - 1 \geq 0"
    assert conditions["highlight"]["items"][1]["math"] == r"x - 2 \neq 0"
    assert r"须非负，即 $x - 1 \geq 0$" in conditions["explanation"]
    assert r"须非零，即 $x - 2 \neq 0$" in conditions["explanation"]
    assert "所有条件要同时成立" not in conditions["explanation"]

    solutions = by_unit["domain_solutions"]
    assert all(item["label"] == "解集" for item in solutions["highlight"]["items"])
    assert r"由 $x - 1 \geq 0$ 得" in solutions["explanation"]
    assert "不能误写成大于零" not in solutions["explanation"]

    intersection = by_unit["domain_intersection"]
    assert intersection["highlight"]["items"][0]["label"] == "定义域"
    assert intersection["highlight"]["items"][0]["math"] == (
        r"\left[1, 2\right) \cup \left(2, \infty\right)"
    )
    assert r"\cap" not in intersection["highlight"]["items"][0]["math"]
    assert r"\cap" in intersection["explanation"]
    assert r"得定义域 $" in intersection["explanation"]
    assert "回看原式限制并确定端点" not in intersection["explanation"]
