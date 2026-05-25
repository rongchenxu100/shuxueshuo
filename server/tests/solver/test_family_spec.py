from dataclasses import fields

from shuxueshuo_server.solver.family import (
    FamilyRegistry,
    QUADRATIC_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
ALT_LABEL_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"


def test_quadratic_path_family_supports_canonical_nankai_fixture() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)

    assert QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)
    assert QUADRATIC_PATH_MINIMUM_FAMILY.family_id == "QuadraticPathMinimumSolver"


def test_quadratic_path_family_rejects_alt_label_fixture_by_temporary_gate() -> None:
    problem = load_problem_ir(ALT_LABEL_FIXTURE)

    # enabled_problem_ids 是 V1.5 deterministic slice 的临时硬门控，所以同构题
    # 暂时仍不能进入 canonical 南开固定计划。
    assert not QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)


def test_enabled_problem_ids_is_a_hard_gate_after_family_match() -> None:
    problem = load_problem_ir(ALT_LABEL_FIXTURE)

    # 这个测试专门锁定“硬门控”语义：alt-label 题的 pattern/problem_type 已经命中
    # family，但 problem_id 不在 enabled_problem_ids 内，所以 registry 仍必须拒绝。
    assert QUADRATIC_PATH_MINIMUM_FAMILY.match.matches(problem)
    assert problem.problem_id not in QUADRATIC_PATH_MINIMUM_FAMILY.enabled_problem_ids
    assert not QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)


def test_quadratic_path_family_rejects_other_real_25_fixture() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)

    assert not QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)


def test_family_spec_keeps_planner_and_answer_shape_out_of_spec() -> None:
    field_names = {field.name for field in fields(QUADRATIC_PATH_MINIMUM_FAMILY)}

    assert "answer_schema" not in field_names
    assert "planner_id" not in field_names
    assert not hasattr(QUADRATIC_PATH_MINIMUM_FAMILY, "answer_schema")
    assert not hasattr(QUADRATIC_PATH_MINIMUM_FAMILY, "planner_id")


def test_family_spec_contains_only_family_level_context() -> None:
    spec = QUADRATIC_PATH_MINIMUM_FAMILY

    assert "derive_parabola" in spec.common_goal_types
    assert "derive_parameter" in spec.common_goal_types
    assert spec.strategy_principles
    assert "right_angle_equal_length" in spec.relation_patterns
    assert "path_reduction" in spec.method_capability_hints
    assert "question goals" in spec.result_collection_policy


def test_family_registry_matches_supported_problem_only() -> None:
    registry = FamilyRegistry((QUADRATIC_PATH_MINIMUM_FAMILY,))

    supported = load_problem_ir(NANKAI_FIXTURE)
    unsupported = load_problem_ir(ALT_LABEL_FIXTURE)

    assert registry.match(supported) is QUADRATIC_PATH_MINIMUM_FAMILY
    assert registry.match(unsupported) is None
