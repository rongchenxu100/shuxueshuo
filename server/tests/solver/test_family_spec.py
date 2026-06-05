from dataclasses import fields

from shuxueshuo_server.solver.family import (
    FamilyRegistry,
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
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


def test_quadratic_weighted_path_family_supports_hexi_fixture() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)

    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.supports(problem)
    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id == "QuadraticWeightedPathMinimumSolver"


def test_quadratic_weighted_path_family_uses_structural_match_without_problem_gate() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)

    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.match.matches(problem)
    assert not QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.enabled_problem_ids
    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.supports(problem)


def test_family_spec_keeps_planner_and_answer_shape_out_of_spec() -> None:
    field_names = {field.name for field in fields(QUADRATIC_PATH_MINIMUM_FAMILY)}

    assert "answer_schema" not in field_names
    assert "planner_id" not in field_names
    assert "method_capability_hints" not in field_names
    assert "result_collection_policy" not in field_names
    assert not hasattr(QUADRATIC_PATH_MINIMUM_FAMILY, "answer_schema")
    assert not hasattr(QUADRATIC_PATH_MINIMUM_FAMILY, "planner_id")


def test_family_spec_contains_only_family_level_context() -> None:
    spec = QUADRATIC_PATH_MINIMUM_FAMILY

    assert "derive_parabola" in spec.common_goal_types
    assert "derive_parameter" in spec.common_goal_types
    assert spec.strategy_principles
    assert "quadratic_from_constraints" in spec.method_ids
    recipe_ids = {recipe.recipe_id for recipe in spec.step_recipes}
    assert "right_angle_equal_length_construct_and_select" in recipe_ids
    assert "two_moving_points_path_reduction" in recipe_ids
    assert any(recipe.priority == "preferred" for recipe in spec.step_recipes)
    assert spec.method_binding_rules


def test_path_family_recipes_include_execution_specs() -> None:
    """Recipe 执行序列应跟随 FamilySpec，而不是只存在 runtime default 表里。"""
    recipes = {
        recipe.recipe_id: recipe
        for recipe in QUADRATIC_PATH_MINIMUM_FAMILY.step_recipes
    }

    right_angle = recipes["right_angle_equal_length_construct_and_select"]
    assert right_angle.execution is not None
    assert right_angle.execution.method_sequence == (
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    )
    assert right_angle.execution.execution_strategy == "right_angle_construct_select"

    straightening = recipes["broken_path_straightening_and_select"]
    assert straightening.execution is not None
    assert straightening.execution.execution_strategy == "straightening_candidates_select"


def test_path_family_binding_rules_are_declared_in_spec() -> None:
    """南开相关 method 的 slot 绑定规则应由 FamilySpec 提供。"""
    rules = {
        rule.method_id: rule
        for rule in QUADRATIC_PATH_MINIMUM_FAMILY.method_binding_rules
    }

    assert "quadratic_axis_from_relation" in rules
    assert "two_moving_points_path_reduction" in rules
    axis_selectors = {
        binding.input_name: binding.selector
        for binding in rules["quadratic_axis_from_relation"].input_bindings
    }
    assert axis_selectors["target"] == "point_output_ref"
    assert axis_selectors["coefficient_relation"] == "fact:coefficient_relation:Equation"


def test_family_registry_matches_supported_problem_only() -> None:
    registry = FamilyRegistry((
        QUADRATIC_PATH_MINIMUM_FAMILY,
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    ))

    supported = load_problem_ir(NANKAI_FIXTURE)
    hexi = load_problem_ir(HEXI_FIXTURE)
    unsupported = load_problem_ir(ALT_LABEL_FIXTURE)

    assert registry.match(supported) is QUADRATIC_PATH_MINIMUM_FAMILY
    assert registry.match(hexi) is QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
    assert registry.match(unsupported) is None
