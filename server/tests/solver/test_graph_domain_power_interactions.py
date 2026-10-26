"""Power restrictions keep their original positions through the shared lesson."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import driver, interaction
from tests.solver.test_graph_stage_three_function_domain import candidate, execute

Q01 = "(x+4)^0*(x^2-1)/(x-1)"


def projected(expression):
    context, state = execute(candidate(expression))
    assert state["status"] == "method_complete", state["diagnostics"]
    assert state["verification"]["status"] == "verified"
    chunks, pending = interaction.compile_route(
        state["interaction_seeds"], interaction.load_registry()
    )
    assert not pending and len(chunks) == 4
    for chunk, diagnostics in chunks:
        assert chunk["status"] == "interactive", diagnostics
        interaction.validate_chunk(chunk)
    return context, state, [chunk["parts"][0] for chunk, _ in chunks]


def test_q01_power_and_original_denominator_have_distinct_teaching_sources():
    context, state, parts = projected(Q01)
    location, conditions, solutions, final = parts
    regions = location["source_regions"]
    assert regions["expression_ast"] == context["domain_goal"]["expression_ast"]
    assert [(row["label"], row["ast_path"]) for row in regions["regions"]] == [
        ("零次幂的底数", [1, 1, 1]), ("分母", [2])
    ]
    assert all(row["source_ref"] == "/root/definitions/0" for row in regions["regions"])
    assert regions["regions"][0]["basis_refs"] == ["integer-power#zero-exponent"]
    assert set(location["expected_answer"]["required"]) == {
        row["option_value"] for row in regions["regions"]
    }
    assert len(conditions["interaction"]["slots"]) == 2, "the positive square adds no condition"
    assert "零次幂的底数" in conditions["interaction"]["slots"][0]["label"]
    chosen = [next(option["label"] for option in slot["options"] if option["value"] == value)
              for slot, value in zip(conditions["interaction"]["slots"], conditions["expected_answer"]["terms"], strict=True)]
    assert chosen == [r"$x + 4 \neq 0$", r"$x - 1 \neq 0$"]
    assert "零次幂的底数必须排除 0" in conditions["feedback"]["terms"]
    assert "分母必须排除 0" in conditions["feedback"]["terms"]
    assert len(solutions["condition_number_lines"]) == 2
    assert driver.export_values(state)["feasible_set"] == sp.S.Reals - sp.FiniteSet(-4, 1)
    assert "正整数次幂本身不增加输入限制" in state["fragments"][0]["explanation"]
    assert "零次幂要求底数不为零" in state["fragments"][0]["explanation"]
    assert "零次幂的底数" in state["fragments"][1]["explanation"]
    assert len(final["expected_answer"]["one_of"]) == 2
    checks = {row["at"]: row for row in final["endpoint_checks"]}
    assert set(checks) == {-4, 1}
    assert not checks[-4]["included"] and not checks[1]["included"]
    assert "零次幂的底数为 0" in checks[-4]["reason"] and "$0^0$" in checks[-4]["reason"]
    assert "分母为 0" in checks[1]["reason"]
    assert any(row["kind"] == "zero_power_base_nonzero" and row["ast_path"] == [1, 1, 1]
               and not row["holds"] for row in checks[-4]["sources"])
    lines = final["condition_number_lines"] + [final["completion_number_line"]]
    assert all(line["bounds"] == lines[0]["bounds"] and line["ticks"] == lines[0]["ticks"] for line in lines)


@pytest.mark.parametrize("expression,excluded", [
    ("(x-3)^0", {3}),
    ("((x+4)^0)^2", {-4}),
    ("(x+4)^0*(x-1)^2/(x-1)", {-4, 1}),
    ("(x-3)^2", set()),
    ("(-x)^2", set()),
    ("x^2.0", set()),
])
def test_power_variations_keep_only_original_input_restrictions(expression, excluded):
    _, state, parts = projected(expression)
    assert driver.export_values(state)["feasible_set"] == sp.S.Reals - sp.FiniteSet(*excluded)
    if not excluded:
        assert parts[0]["source_regions"]["regions"] == []
        assert "正整数次幂本身不增加输入限制" in state["fragments"][0]["explanation"]
    assert {row["at"] for row in parts[-1]["endpoint_checks"] if not row["included"]} == excluded


def test_overlapping_zero_power_and_denominator_sources_keep_both_reasons():
    _, _, parts = projected("(x+4)^0/(x+4)")
    assert len(parts[0]["source_regions"]["regions"]) == 2
    (endpoint,) = parts[-1]["endpoint_checks"]
    assert endpoint["at"] == -4
    assert "分母为 0" in endpoint["reason"] and "零次幂的底数为 0" in endpoint["reason"]
    assert {row["kind"] for row in endpoint["sources"] if not row["holds"]} == {
        "denominator_nonzero", "zero_power_base_nonzero"
    }
