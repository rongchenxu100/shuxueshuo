"""V1.5 RuntimeContext 多层作用域测试。

重点验证 problem/question/subquestion/step 的读取边界和写回隔离，避免不同小问
之间互相污染，也避免 step 临时结果自动泄露到上层。
"""

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.models import TypedValue


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


@pytest.fixture()
def context():
    return ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))


def test_builds_problem_question_subquestion_tree(context) -> None:
    assert context.get_scope("problem").scope_type == "problem"
    assert context.get_scope("ii").scope_type == "question"
    assert context.get_scope("ii_1").scope_type == "subquestion"
    assert context.get_scope("ii_2").parent_id == "ii"


def test_problem_point_is_visible_to_subquestions(context) -> None:
    point = context.read_path(
        "$problem.points.D",
        from_scope_id="ii_1",
        expected_type="Point",
    ).value

    assert point[0] == 1
    assert point[1] == 0


def test_subquestion_output_does_not_pollute_sibling(context) -> None:
    context.write_path(
        "$subquestion.ii_1.outputs.m",
        TypedValue("ParameterValue", "3", source="test"),
        from_scope_id="ii_1",
    )

    assert context.find_visible_path("outputs", "m", from_scope_id="ii_2") is None
    with pytest.raises(PermissionError):
        context.read_path("$subquestion.ii_1.outputs.m", from_scope_id="ii_2")


def test_step_temp_is_not_visible_to_parent_or_sibling(context) -> None:
    context.ensure_step_scope("derive_N", "ii")
    context.write_path(
        "$step.derive_N.temp.candidates",
        TypedValue("Point", ("2", "1-m"), source="test"),
        from_scope_id="derive_N",
    )

    with pytest.raises(PermissionError):
        context.read_path("$step.derive_N.temp.candidates", from_scope_id="ii")
    assert context.find_visible_path("temp", "candidates", from_scope_id="ii_1") is None


def test_promoted_output_is_visible_from_descendant(context) -> None:
    context.ensure_step_scope("derive_N", "ii")
    context.write_path(
        "$step.derive_N.temp.derived_point",
        TypedValue("Point", ("2", "1-m"), source="test"),
        from_scope_id="derive_N",
    )
    context.write_path(
        "$question.ii.outputs.derived_point",
        context.read_path("$step.derive_N.temp.derived_point", from_scope_id="derive_N"),
        from_scope_id="derive_N",
        allow_ancestor_write=True,
    )

    value = context.read_path("$question.ii.outputs.derived_point", from_scope_id="ii_1")
    assert value.value == ("2", "1-m")
