"""V1.5 ContextPath 解析和读写校验测试。"""

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.models import ContextPath, TypedValue


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


@pytest.fixture()
def context():
    return ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))


def test_parses_supported_context_paths() -> None:
    assert ContextPath.parse("$problem.points.D").scope_id == "problem"
    assert ContextPath.parse("$question.ii.points.M").scope_id == "ii"
    assert ContextPath.parse("$subquestion.ii_1.conditions.length_squared").container == "conditions"
    assert ContextPath.parse("$step.derive_N.temp.candidates").scope_type == "step"


def test_rejects_invalid_context_path() -> None:
    with pytest.raises(ValueError):
        ContextPath.parse("not-a-path")


def test_reads_question_point(context) -> None:
    value = context.read_path(
        "$question.ii.points.M",
        from_scope_id="ii_1",
        expected_type="Point",
    )

    assert str(value.value[0]) == "m"
    assert value.value[1] == 1


def test_missing_path_fails(context) -> None:
    with pytest.raises(KeyError):
        context.read_path("$question.ii.points.Z", from_scope_id="ii")


def test_type_mismatch_fails(context) -> None:
    with pytest.raises(TypeError):
        context.read_path("$question.ii.points.M", from_scope_id="ii", expected_type="Condition")


def test_cannot_overwrite_locked_fact(context) -> None:
    with pytest.raises(PermissionError):
        context.write_path(
            "$question.ii.points.M",
            TypedValue("Point", ("0", "0"), source="test"),
            from_scope_id="ii",
        )
