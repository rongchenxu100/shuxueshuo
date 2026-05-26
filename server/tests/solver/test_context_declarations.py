"""Planner ContextDeclaration 校验与应用测试。"""

from __future__ import annotations

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.executor import DeclarationValidator
from shuxueshuo_server.solver.runtime.models import ContextDeclaration, PointRef


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


@pytest.fixture()
def context():
    return ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))


@pytest.fixture()
def validator() -> DeclarationValidator:
    return DeclarationValidator()


def _declaration(
    *,
    path: str = "$question.ii.points.G",
    name: str = "G",
    scope_id: str = "ii",
    definition: dict[str, object] | None = None,
    type: str = "PointRef",
    source: str = "planner",
) -> ContextDeclaration:
    """构造测试用声明。"""
    return ContextDeclaration(
        path=path,
        type=type,
        name=name,
        definition=definition or {"definition": "line_intersection"},
        scope_id=scope_id,
        source=source,
    )


def test_valid_point_ref_declaration_can_be_applied(context, validator) -> None:
    declaration = _declaration()

    validator.validate_declaration(context, declaration)
    context.apply_declaration(declaration)

    value = context.read_path(
        "$question.ii.points.G",
        from_scope_id="ii_2",
        expected_type="PointRef",
    ).value
    assert isinstance(value, PointRef)
    assert value.name == "G"
    assert value.definition["definition"] == "line_intersection"


def test_duplicate_same_point_ref_declaration_is_idempotent(context, validator) -> None:
    declaration = _declaration()

    validator.validate_declaration(context, declaration)
    context.apply_declaration(declaration)
    validator.validate_declaration(context, declaration)
    context.apply_declaration(declaration)

    value = context.get_scope("ii").container("points")["G"]
    assert value.type == "PointRef"


def test_conflicting_duplicate_declaration_fails(context, validator) -> None:
    declaration = _declaration()
    context.apply_declaration(declaration)

    with pytest.raises(PermissionError, match="conflicts"):
        validator.validate_declaration(
            context,
            _declaration(definition={"definition": "other_auxiliary_point"}),
        )


def test_declaration_cannot_overwrite_locked_fact(context, validator) -> None:
    with pytest.raises(PermissionError, match="locked"):
        validator.validate_declaration(
            context,
            _declaration(
                path="$question.ii.points.M",
                name="M",
                scope_id="ii",
            ),
        )


def test_declaration_must_write_points_container(context, validator) -> None:
    with pytest.raises(PermissionError, match="points container"):
        validator.validate_declaration(
            context,
            _declaration(
                path="$question.ii.outputs.G",
                name="G",
                scope_id="ii",
            ),
        )


def test_declaration_rejects_coordinates_or_answer_values(context, validator) -> None:
    with pytest.raises(ValueError, match="coordinates"):
        validator.validate_declaration(
            context,
            _declaration(definition={"definition": "line_intersection", "value": [1, 2]}),
        )


def test_declaration_unknown_scope_fails(context, validator) -> None:
    with pytest.raises(KeyError, match="scope not found"):
        validator.validate_declaration(
            context,
            _declaration(
                path="$question.unknown.points.G",
                name="G",
                scope_id="unknown",
            ),
        )
