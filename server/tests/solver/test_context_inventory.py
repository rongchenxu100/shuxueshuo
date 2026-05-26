"""ContextInventory 的规划摘要测试。

这些测试只验证 Phase 2 新增的只读索引，不参与 method 执行，也不改变当前南开
25 的 solver 主链路。真正执行时仍然以 RuntimeContext 为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import (
    ContextInventory,
    ContextInventoryBuilder,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


def _build_inventory() -> ContextInventory:
    """构建南开 fixture 的规划索引，供多个测试复用。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    return ContextInventoryBuilder().build(context, specs)


def test_context_inventory_contains_core_context_paths() -> None:
    """inventory 应列出后续 Planner 会引用的核心 ContextPath。"""
    inventory = _build_inventory()

    d = inventory.find_path("$problem.points.D")
    m = inventory.find_path("$question.ii.points.M")
    n_quadrant = inventory.find_path("$question.ii.constraints.N_quadrant")
    m_constraint = inventory.find_path("$problem.constraints.m")

    assert d is not None
    assert d.type == "PointRef"
    assert d.scope_id == "problem"
    assert d.container == "points"
    assert d.key == "D"
    assert d.source == "point:D"
    assert d.definition == {"definition": "axis_x_intercept", "of": "parabola"}
    assert {"ii_1", "ii_2"}.issubset(set(d.readable_from))

    assert m is not None
    assert m.type == "Point"
    assert m.scope_id == "ii"
    assert m.locked

    assert n_quadrant is not None
    assert n_quadrant.type == "OrientationHint"
    assert n_quadrant.scope_id == "ii"
    assert n_quadrant.locked

    assert m_constraint is not None
    assert m_constraint.type == "Constraint"
    assert m_constraint.scope_id == "problem"
    assert m_constraint.locked


def test_context_inventory_exposes_structured_pointref_definition() -> None:
    """PointRef 定义应有结构化摘要，避免 planner 解析 description 文案。"""
    inventory = _build_inventory()

    midpoint = inventory.find_path("$question.ii.points.F")

    assert midpoint is not None
    assert midpoint.definition == {"definition": "midpoint", "of": ["D", "N"]}


def test_context_inventory_preserves_scope_visibility() -> None:
    """同级小问不能互相读，problem scope 对所有下层 scope 可见。"""
    inventory = _build_inventory()

    length_condition = inventory.find_path("$subquestion.ii_1.conditions.length_squared")
    assert length_condition is not None
    assert "ii_1" in length_condition.readable_from
    assert "ii_2" not in length_condition.readable_from

    problem_symbol = inventory.find_path("$problem.symbols.m")
    assert problem_symbol is not None
    assert {"ii_1", "ii_2"}.issubset(set(problem_symbol.readable_from))


def test_context_inventory_indexes_relation_graph() -> None:
    """relation graph 应保留题面关系类型和可回溯来源。"""
    inventory = _build_inventory()

    relation_types = {entry.relation_type for entry in inventory.relation_graph}
    assert "right_angle_equal_length" in relation_types
    assert "segment_relation" in relation_types
    assert "segment_membership" in relation_types

    segment_relation = next(
        entry for entry in inventory.relation_graph
        if entry.relation_type == "segment_relation"
    )
    assert segment_relation.source_ref.startswith("ProblemIR.data.relations[")

    right_angle = next(
        entry for entry in inventory.relation_graph
        if entry.relation_type == "right_angle_equal_length"
    )
    assert {"D", "M", "N"}.issubset(set(right_angle.participants))
    assert right_angle.source_ref.startswith("ProblemIR.data.relations[")


def test_context_inventory_indexes_planning_signals() -> None:
    """planning signals 是确定性上下文索引，不是 planner 提前生成的目标。"""
    inventory = _build_inventory()

    unresolved = inventory.signals_by_type("unresolved_point_ref")
    constructible = inventory.signals_by_type("constructible_right_angle_equal_length_point")
    orientation = inventory.signals_by_type("orientation_constraint")

    n_unresolved = next(signal for signal in unresolved if signal.roles["point"] == "N")
    assert n_unresolved.path == "$question.ii.points.N"
    assert n_unresolved.reason == "点已声明但坐标未知"

    n_constructible = next(signal for signal in constructible if signal.roles["target"] == "N")
    assert n_constructible.path == "$question.ii.points.N"
    assert n_constructible.roles["anchor"] == "D"
    assert n_constructible.roles["reference"] == "M"
    assert n_constructible.source_ref.startswith("ProblemIR.data.relations[")

    n_orientation = next(signal for signal in orientation if signal.roles["point"] == "N")
    assert n_orientation.path == "$question.ii.constraints.N_quadrant"


def test_context_inventory_indexes_method_candidates() -> None:
    """method candidates 应能按 method_id 和 solves goal 查询。"""
    inventory = _build_inventory()

    candidate = inventory.find_method("right_angle_equal_length_candidates")
    assert candidate is not None
    assert candidate.input_slots["anchor"] == "Point"
    assert candidate.output_slots["candidates"] == "PointList"

    matches = inventory.methods_for_goal("derive_right_angle_equal_length_candidates")
    assert "right_angle_equal_length_candidates" in {
        item.method_id for item in matches
    }
