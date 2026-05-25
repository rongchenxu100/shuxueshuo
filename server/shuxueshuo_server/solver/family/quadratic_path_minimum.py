"""二次函数路径最值 SolverFamilySpec。

这里抽取的是“二次函数 + 构造点 + 路径最值”这类题的共性上下文，供后续通用
Planner 参考。它不包含南开 25 的固定 StepPlan，也不包含最终答案结构。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import FamilyMatchRule, SolverFamilySpec


QUADRATIC_PATH_MINIMUM_FAMILY = SolverFamilySpec(
    family_id="QuadraticPathMinimumSolver",
    match=FamilyMatchRule(
        patterns=("path-minimum",),
        problem_types=("quadratic_path_minimum",),
    ),
    common_goal_types=(
        "derive_parabola",
        "derive_constructed_point",
        "derive_parameter",
        "reduce_path_expression",
        "straighten_broken_path",
        "derive_minimum_value",
        "derive_extremal_point",
    ),
    strategy_principles=(
        "先解析题设中的函数、点、关系和参数约束。",
        "若构造点坐标未知，先由几何关系生成候选，再用题设约束筛选。",
        "能先确定未知参数时，优先先求参数再代入后续表达式。",
        "路径最值先做路径转化，再做折线拉直或等价最短路径处理。",
        "最短路径对应点通常来自约束轨迹与拉直线段的交点。",
    ),
    relation_patterns=(
        "coefficient_relation_on_quadratic",
        "point_on_parabola",
        "right_angle_equal_length",
        "moving_points_with_segment_binding",
        "point_on_segment_or_line_path",
    ),
    method_capability_hints=(
        "quadratic_coefficient_solving",
        "right_angle_or_rotation_point_construction",
        "parameter_solving",
        "path_reduction",
        "broken_path_straightening",
        "line_intersection",
    ),
    result_collection_policy=(
        "最终答案从 ProblemIR 的 question goals 及其 resolved target paths 收集。"
    ),
    # 临时兼容硬门控：当前 V1.5 deterministic planner 只实现 canonical 南开 25。
    # 退出条件：
    # 1. 至少两道同 family 的完整 E2E fixture 通过；
    # 2. planner 不再依赖 D/M/N/F/G、i/ii/ii_1/ii_2 等 canonical 命名；
    # 3. 去掉门控后，alt-label 同构题能通过，其他 family 题仍不会误路由。
    enabled_problem_ids=("tj-2026-nankai-yimo-25",),
)
