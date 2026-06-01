"""加权二次函数路径最值 SolverFamilySpec。

这里描述的是河西 25 所代表的“二次函数 + 加权路径最值”题型上下文。它只用于
RuntimeOrchestrator 匹配 family，并给 Planner 提供题型级参考，不保存具体答案。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import FamilyMatchRule, SolverFamilySpec


QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticWeightedPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("weighted-path-minimum",),
        problem_types=("quadratic_weighted_path_minimum",),
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_vertex_point",
        "derive_constructed_point",
        "derive_weighted_path_minimum",
        "derive_parameter",
    ),
    strategy_principles=(
        "先将每一问的已知系数与已知曲线点尽量代入，得到当前问最简抛物线表达式。",
        "几何构造点先列候选，再用点在抛物线上和参数约束筛选。",
        "加权路径最值优先寻找几何转化：用辅助直角三角形把加权段转成同倍率折线，再用折线拉直或等价最短路径处理。",
    ),
    method_ids=(
        "quadratic_from_constraints",
        "quadratic_vertex_point",
        "quadratic_y_axis_intercept_point",
        "right_angle_equal_length_candidates",
        "filter_point_candidates_by_quadratic_curve",
        "select_curve_point_candidate_and_solve_coefficients",
        "point_on_parabola_at_x",
        "weighted_axis_path_triangle_transform",
        "linked_broken_path_geometric_minimum",
    ),
    step_recipes=(),
    # 河西 25 是 weighted family 的第一道完整 golden case。后续至少再通过一道
    # 同 family 题后，再考虑移除这个 deterministic slice 门控。
    enabled_problem_ids=("tj-2026-hexi-yimo-25",),
)
