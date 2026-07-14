"""Capability Pack registry for solver families."""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    CapabilityCardinality,
    CapabilityExecutionStatus,
    CapabilityPackRegistry,
    CapabilityPackSpec,
    ConditionPattern,
    MethodBindingRuleSpec,
    MethodInputBindingSpec,
    RecipeExecutionSpec,
    recipe_output_alias,
    StateSlotPattern,
    StateWriteMode,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.family.common_binding_rules import (
    distance_between_points_rule,
    evaluate_expression_at_parameter_rule,
    evaluate_point_at_parameter_rule,
    line_intersection_point_rule,
    line_parabola_second_intersection_point_rule,
    midpoint_point_rule,
    parameter_from_expression_value_rule,
    quadratic_from_constraints_rule,
    quadratic_vertex_point_rule,
    quadratic_x_axis_intercept_point_rule,
    quadratic_y_axis_intercept_point_rule,
    translated_point_rule,
)
from shuxueshuo_server.solver.output_type_policy import TRANSIENT_OUTPUT_TYPES


def _slot(
    state_kind: str,
    runtime_type: str,
    *,
    object_kind: str | None = None,
    cardinality: CapabilityCardinality = "one",
    required: bool | None = None,
    write_mode: StateWriteMode | None = None,
) -> StateSlotPattern:
    resolved_required = (
        runtime_type not in TRANSIENT_OUTPUT_TYPES
        if required is None
        else required
    )
    return StateSlotPattern(
        state_kind=state_kind,
        runtime_type=runtime_type,
        object_kind=object_kind,
        cardinality=cardinality,
        required=resolved_required,
        write_mode=(
            write_mode
            if write_mode is not None
            else ("create" if runtime_type in {"Point", "PointList"} else "value")
        ),
    )


def _condition(
    condition_kind: str,
    *,
    runtime_type: str = "Condition",
    required: bool = True,
) -> ConditionPattern:
    return ConditionPattern(
        condition_kind=condition_kind,
        runtime_type=runtime_type,
        required=required,
    )


def _method_contract(
    capability_id: str,
    *,
    slot_reads: tuple[StateSlotPattern, ...] = (),
    condition_reads: tuple[ConditionPattern, ...] = (),
    slot_writes: tuple[StateSlotPattern, ...] = (),
    condition_writes: tuple[ConditionPattern, ...] = (),
    execution_status: CapabilityExecutionStatus = "executable",
    exposes_to_llm: bool = True,
    constraint_analyzer: str | None = None,
) -> CapabilityContractSpec:
    return CapabilityContractSpec(
        capability_id=capability_id,
        kind="method",
        execution_status=execution_status,
        slot_reads=slot_reads,
        condition_reads=condition_reads,
        slot_writes=slot_writes,
        condition_writes=condition_writes,
        exposes_to_llm=exposes_to_llm,
        constraint_analyzer=constraint_analyzer,
    )


def _recipe_contract(
    capability_id: str,
    *,
    slot_reads: tuple[StateSlotPattern, ...] = (),
    condition_reads: tuple[ConditionPattern, ...] = (),
    slot_writes: tuple[StateSlotPattern, ...] = (),
    condition_writes: tuple[ConditionPattern, ...] = (),
    execution_status: CapabilityExecutionStatus = "executable",
    exposes_to_llm: bool = True,
) -> CapabilityContractSpec:
    return CapabilityContractSpec(
        capability_id=capability_id,
        kind="recipe",
        execution_status=execution_status,
        slot_reads=slot_reads,
        condition_reads=condition_reads,
        slot_writes=slot_writes,
        condition_writes=condition_writes,
        exposes_to_llm=exposes_to_llm,
    )


QUADRATIC_CORE_CONTRACTS = (
    _method_contract(
        "quadratic_axis_from_relation",
        condition_reads=(_condition("coefficient_relation", runtime_type="Equation"),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
    _method_contract(
        "quadratic_from_constraints",
        slot_reads=(_slot("expression", "Function", object_kind="function"),),
        condition_reads=(
            _condition("coefficient_relation", runtime_type="Equation", required=False),
            _condition("point_on_curve", required=False),
        ),
        slot_writes=(
            _slot("expression", "Parabola", object_kind="function"),
            _slot("coefficients", "Coefficients", object_kind="function"),
        ),
        constraint_analyzer="quadratic_coefficients",
    ),
    _method_contract(
        "quadratic_vertex_point",
        slot_reads=(_slot("expression", "Parabola", object_kind="function"),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
    _method_contract(
        "quadratic_x_axis_intercept_point",
        slot_reads=(_slot("expression", "Parabola", object_kind="function"),),
        condition_reads=(_condition("x_axis_known_point", required=False),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
    _method_contract(
        "quadratic_y_axis_intercept_point",
        slot_reads=(_slot("expression", "Parabola", object_kind="function"),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
    _method_contract(
        "line_parabola_second_intersection_point",
        slot_reads=(
            _slot("expression", "Parabola", object_kind="function"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        condition_reads=(_condition("line_relation", required=False),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
)

PARAMETER_SOLVING_CONTRACTS = (
    _method_contract(
        "parameter_from_expression_value",
        slot_reads=(_slot("expression", "MinimumExpression"),),
        condition_reads=(_condition("minimum_value"),),
        slot_writes=(_slot("value", "ParameterValue", object_kind="symbol"),),
    ),
    _method_contract(
        "evaluate_expression_at_parameter",
        slot_reads=(
            _slot("expression", "Expression"),
            _slot("value", "ParameterValue", object_kind="symbol"),
        ),
        slot_writes=(_slot("expression", "Expression"),),
    ),
    _method_contract(
        "evaluate_point_at_parameter",
        slot_reads=(
            _slot("coordinate", "Point", object_kind="point"),
            _slot("value", "ParameterValue", object_kind="symbol"),
        ),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
)

COORDINATE_GEOMETRY_CONTRACTS = (
    _method_contract(
        "distance_between_points",
        slot_reads=(
            _slot("coordinate", "Point", object_kind="point"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        slot_writes=(
            _slot("expression", "MinimumExpression"),
            _slot("expression", "Expression", required=False),
        ),
    ),
    _method_contract(
        "midpoint_point",
        condition_reads=(_condition("midpoint_definition"),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
    _method_contract(
        "translated_point",
        slot_reads=(_slot("coordinate", "Point", object_kind="point"),),
        condition_reads=(_condition("translation"),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
    _method_contract(
        "line_intersection_point",
        slot_reads=(
            _slot("coordinate", "Point", object_kind="point"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
    ),
)


RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT = StepRecipeSpec(
    recipe_id="right_angle_equal_length_construct_and_select",
    goal_type="derive_constructed_point",
    title="直角等腰构造并筛选点",
    description=(
        "由直角等腰/旋转关系先列出候选点，再结合象限、参数范围或曲线条件"
        "筛选出符合题设的点。"
    ),
    method_ids=(
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    ),
    execution=RecipeExecutionSpec(
        recipe_id="right_angle_equal_length_construct_and_select",
        method_sequence=(
            "right_angle_equal_length_candidates",
            "select_point_by_quadrant_constraint",
        ),
        execution_strategy="right_angle_construct_select",
        intermediate_wiring=(
            (
                "right_angle_equal_length_candidates.candidates",
                "select_point_by_quadrant_constraint.candidates",
            ),
        ),
        output_aliases=(
            recipe_output_alias(
                "select_point_by_quadrant_constraint.selected_point",
                "Point",
                "selected_target_point",
                identity_policy="target_object",
                identity_arg="target",
            ),
        ),
    ),
)

TWO_MOVING_POINTS_PATH_REDUCTION = StepRecipeSpec(
    recipe_id="two_moving_points_path_reduction",
    goal_type="reduce_path_expression",
    title="两动点路径降维：已有固定点替换",
    description=(
        "利用线段比例、共线或绑定关系，把原路径中的两动点线段替换为"
        "题面已有固定点到动点的等长线段，从而转化为单动点折线路径；"
        "本 recipe 不创建辅助点或辅助轨迹。"
    ),
    method_ids=("two_moving_points_path_reduction",),
    execution=RecipeExecutionSpec(
        recipe_id="two_moving_points_path_reduction",
        method_sequence=("two_moving_points_path_reduction",),
        execution_strategy="single_method",
        output_aliases=(
            recipe_output_alias(
                "two_moving_points_path_reduction.path_transformation",
                "PathTransformation",
                "path_transformation",
            ),
        ),
    ),
    priority="preferred",
)

BROKEN_PATH_STRAIGHTENING_AND_SELECT = StepRecipeSpec(
    recipe_id="broken_path_straightening_and_select",
    goal_type="straighten_broken_path",
    title="折线拉直并选择方案",
    description=(
        "为单动点折线路径构造拉直候选方案，再选择最方便计算且符合题设"
        "结构的方案；本 recipe 只产出拉直方案，不直接产出最小值表达式。"
    ),
    method_ids=(
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
    ),
    execution=RecipeExecutionSpec(
        recipe_id="broken_path_straightening_and_select",
        method_sequence=(
            "broken_path_straightening_candidates",
            "select_straightening_candidate",
        ),
        execution_strategy="straightening_candidates_select",
        creates=("point",),
        intermediate_wiring=(
            (
                "broken_path_straightening_candidates.candidates",
                "select_straightening_candidate.candidates",
            ),
        ),
        output_aliases=(
            recipe_output_alias(
                "select_straightening_candidate.selected_candidate",
                "StraighteningCandidate",
                "straightened_scheme",
                goal_evidence_tags=("path_minimum_witness",),
            ),
            recipe_output_alias(
                "select_straightening_candidate.auxiliary_point",
                "Point",
                "straightening_auxiliary_point",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_1",
                "Point",
                "path_minimum_point_1",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_2",
                "Point",
                "path_minimum_point_2",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
            ),
        ),
    ),
    priority="preferred",
)

PATH_MINIMUM_BY_STRAIGHTENED_DISTANCE = StepRecipeSpec(
    recipe_id="path_minimum_by_straightened_distance",
    goal_type="derive_minimum_value",
    title="拉直后距离求最小值",
    description=(
        "在折线已经拉直或等价路径已经确定后，单独用端点间距离或垂线距离"
        "求路径最小值表达式；不要并入折线拉直步骤。"
    ),
    method_ids=("distance_between_points",),
    execution=RecipeExecutionSpec(
        recipe_id="path_minimum_by_straightened_distance",
        method_sequence=("distance_between_points",),
        execution_strategy="straightened_distance_minimum",
        output_aliases=(
            recipe_output_alias(
                "distance_between_points.distance",
                "MinimumExpression",
                "path_minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
            ),
            recipe_output_alias(
                "distance_between_points.evaluated_distance",
                "MinimumExpression",
                "evaluated_path_minimum_expression",
                required=False,
                cardinality="optional",
                goal_evidence_tags=("path_minimum_expression",),
            ),
        ),
    ),
    priority="preferred",
)

BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION = StepRecipeSpec(
    recipe_id="broken_path_straightening_minimum_expression",
    goal_type="derive_path_minimum_expression",
    title="折线拉直并求最小值表达式",
    description=(
        "对单动点两段折线路径，生成将军饮马拉直候选，选择最适合计算的方案，"
        "再计算对应两端点距离得到最小值表达式。"
    ),
    method_ids=(
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
        "distance_between_points",
    ),
    execution=RecipeExecutionSpec(
        recipe_id="broken_path_straightening_minimum_expression",
        method_sequence=(
            "broken_path_straightening_candidates",
            "select_straightening_candidate",
            "distance_between_points",
        ),
        execution_strategy="broken_path_straightening_minimum_expression",
        creates=("point",),
        output_aliases=(
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_1",
                "Point",
                "path_minimum_point_1",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_2",
                "Point",
                "path_minimum_point_2",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
            ),
            recipe_output_alias(
                "distance_between_points.distance",
                "MinimumExpression",
                "path_minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
            ),
            recipe_output_alias(
                "distance_between_points.evaluated_distance",
                "MinimumExpression",
                "evaluated_path_minimum_expression",
                required=False,
                cardinality="optional",
                goal_evidence_tags=("path_minimum_expression",),
            ),
        ),
    ),
    priority="preferred",
)

EQUAL_LENGTH_RAY_PATH_REDUCTION = StepRecipeSpec(
    recipe_id="equal_length_ray_path_reduction",
    goal_type="derive_path_minimum_expression",
    title="等长射线路径降维为单距离最值",
    description=(
        "当一个动点在线段上、另一个动点在射线上，且二者满足同端点等长关系时，"
        "把原来的两动点线段距离和转化为一个固定点到内部构造辅助点的单距离"
        "最小值表达式。辅助点由系统在 recipe 内部创建，LLM 不需要在 creates 中"
        "声明辅助点，也不要拆成单独的 equal_length_ray_point step。"
    ),
    method_ids=("equal_length_ray_point", "distance_between_points"),
    execution=RecipeExecutionSpec(
        recipe_id="equal_length_ray_path_reduction",
        method_sequence=("equal_length_ray_point", "distance_between_points"),
        execution_strategy="equal_length_ray_path_reduction",
        creates=("point",),
        output_aliases=(
            recipe_output_alias(
                "distance_between_points.distance",
                "MinimumExpression",
                "path_minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
            ),
            recipe_output_alias(
                "distance_between_points.evaluated_distance",
                "MinimumExpression",
                "evaluated_path_minimum_expression",
                required=False,
                cardinality="optional",
                goal_evidence_tags=("path_minimum_expression",),
            ),
        ),
    ),
    priority="preferred",
)


DEFAULT_CAPABILITY_PACK_REGISTRY = CapabilityPackRegistry((
    CapabilityPackSpec(
        pack_id="quadratic_core",
        kind="base",
        method_ids=(
            "quadratic_axis_from_relation",
            "quadratic_from_constraints",
            "quadratic_vertex_point",
            "quadratic_x_axis_intercept_point",
            "quadratic_y_axis_intercept_point",
            "quadratic_axis_x_intercept_point",
            "point_on_parabola_at_x",
            "line_parabola_second_intersection_point",
        ),
        contracts=QUADRATIC_CORE_CONTRACTS,
        method_binding_rules=(
            quadratic_from_constraints_rule(),
            quadratic_vertex_point_rule(),
            quadratic_x_axis_intercept_point_rule(),
            quadratic_y_axis_intercept_point_rule(),
            line_parabola_second_intersection_point_rule(),
        ),
    ),
    CapabilityPackSpec(
        pack_id="parameter_solving_core",
        kind="base",
        method_ids=(
            "parameter_from_expression_value",
            "parameter_from_segment_length",
            "parameter_from_minimum_value",
            "parameter_from_curve_point_on_quadratic",
            "evaluate_expression_at_parameter",
            "evaluate_point_at_parameter",
        ),
        contracts=PARAMETER_SOLVING_CONTRACTS,
        method_binding_rules=(
            parameter_from_expression_value_rule(),
            evaluate_expression_at_parameter_rule(),
            evaluate_point_at_parameter_rule(),
        ),
    ),
    CapabilityPackSpec(
        pack_id="coordinate_geometry_core",
        kind="base",
        method_ids=(
            "distance_between_points",
            "line_intersection_point",
            "translated_point",
            "midpoint_point",
        ),
        contracts=COORDINATE_GEOMETRY_CONTRACTS,
        method_binding_rules=(
            distance_between_points_rule(),
            midpoint_point_rule(),
            translated_point_rule(),
            line_intersection_point_rule(),
        ),
    ),
    CapabilityPackSpec(
        # Base for path-minimum families, not a universal base for all
        # quadratic families.
        pack_id="broken_path_minimum_core",
        kind="base",
        method_ids=(
            "two_moving_points_path_reduction",
            "broken_path_straightening_candidates",
            "select_straightening_candidate",
            "distance_between_points",
        ),
        step_recipes=(
            TWO_MOVING_POINTS_PATH_REDUCTION,
            BROKEN_PATH_STRAIGHTENING_AND_SELECT,
            PATH_MINIMUM_BY_STRAIGHTENED_DISTANCE,
            BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION,
        ),
        contracts=(
            _recipe_contract(
                "two_moving_points_path_reduction",
                condition_reads=(_condition("path_minimum_target"),),
                slot_writes=(_slot("transformation", "PathTransformation"),),
            ),
            _recipe_contract(
                "broken_path_straightening_and_select",
                condition_reads=(_condition("path_minimum_target"),),
                slot_writes=(
                    _slot("candidate", "StraighteningCandidate"),
                    _slot("coordinate", "Point", object_kind="point", required=False),
                ),
            ),
            _recipe_contract(
                "path_minimum_by_straightened_distance",
                slot_reads=(
                    _slot("coordinate", "Point", object_kind="point"),
                    _slot("coordinate", "Point", object_kind="point"),
                ),
                slot_writes=(_slot("expression", "MinimumExpression"),),
            ),
            _recipe_contract(
                "broken_path_straightening_minimum_expression",
                condition_reads=(_condition("path_minimum_target"),),
                slot_writes=(
                    _slot("coordinate", "Point", object_kind="point", cardinality="many"),
                    _slot("expression", "MinimumExpression"),
                ),
            ),
        ),
        method_binding_rules=(
            MethodBindingRuleSpec(
                method_id="two_moving_points_path_reduction",
                input_bindings=(
                    MethodInputBindingSpec(
                        "original_path",
                        "fact:path_minimum_target:Condition",
                    ),
                    MethodInputBindingSpec(
                        "first_moving_membership",
                        "path_reduction:first_membership",
                    ),
                    MethodInputBindingSpec(
                        "second_moving_membership",
                        "path_reduction:second_membership",
                    ),
                    MethodInputBindingSpec(
                        "binding_relation",
                        "path_reduction:relation",
                    ),
                    MethodInputBindingSpec(
                        "first_segment_start",
                        "path_reduction:first_segment_start",
                    ),
                    MethodInputBindingSpec(
                        "joint_point",
                        "path_reduction:joint_point",
                    ),
                    MethodInputBindingSpec(
                        "second_segment_end",
                        "path_reduction:second_segment_end",
                    ),
                ),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="right_angle_equal_length_core",
        kind="mechanism",
        method_ids=(
            "right_angle_equal_length_candidates",
            "select_point_by_quadrant_constraint",
        ),
        step_recipes=(RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT,),
        contracts=(
            _recipe_contract(
                "right_angle_equal_length_construct_and_select",
                condition_reads=(_condition("right_angle_equal_length"),),
                slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
            ),
            _method_contract(
                "right_angle_equal_length_candidates",
                condition_reads=(_condition("right_angle_equal_length"),),
                slot_writes=(_slot("candidate", "PointList", object_kind="point"),),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="weighted_path_transform_core",
        kind="mechanism",
        method_ids=(
            "weighted_axis_path_triangle_transform",
            "linked_broken_path_minimum_expression",
        ),
        contracts=(
            _method_contract(
                "weighted_axis_path_triangle_transform",
                condition_reads=(_condition("weighted_path_relation"),),
                slot_writes=(
                    _slot("coordinate", "Point", object_kind="point"),
                    _slot("locus", "Line", object_kind="line"),
                ),
            ),
            _method_contract(
                "linked_broken_path_minimum_expression",
                slot_reads=(
                    _slot("transformation", "PathTransformation"),
                    _slot("locus", "Line", object_kind="line"),
                ),
                slot_writes=(_slot("expression", "MinimumExpression"),),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="equal_length_ray_reduction_core",
        kind="mechanism",
        method_ids=(
            "equal_length_ray_point",
            "distance_between_points",
        ),
        step_recipes=(EQUAL_LENGTH_RAY_PATH_REDUCTION,),
        contracts=(
            _recipe_contract(
                "equal_length_ray_path_reduction",
                condition_reads=(_condition("equal_length_ray"),),
                slot_writes=(_slot("expression", "MinimumExpression"),),
            ),
            _method_contract(
                "equal_length_ray_point",
                condition_reads=(_condition("equal_length_ray"),),
                slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="square_path_reduction_core",
        kind="mechanism",
        method_ids=(
            "square_path_dimension_reduction",
            "quadratic_axis_parameterized_point",
            "square_adjacent_vertex_from_side",
            "point_candidates_from_curve_point_condition",
            "parameterized_point_locus_line",
            "line_locus_minimum_point",
        ),
        contracts=(
            _method_contract(
                "square_path_dimension_reduction",
                condition_reads=(
                    _condition("path_minimum_target"),
                    _condition("square"),
                ),
                slot_writes=(_slot("transformation", "PathTransformation"),),
            ),
            _method_contract(
                "quadratic_axis_parameterized_point",
                slot_reads=(_slot("expression", "Parabola", object_kind="function"),),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        write_mode="create",
                    ),
                    _slot(
                        "parameter",
                        "Symbol",
                        object_kind="symbol",
                        write_mode="value",
                    ),
                ),
            ),
            _method_contract(
                "square_adjacent_vertex_from_side",
                condition_reads=(_condition("square"),),
                slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
            ),
            _method_contract(
                "point_candidates_from_curve_point_condition",
                condition_reads=(_condition("point_on_curve"),),
                slot_writes=(_slot("candidate", "PointList", object_kind="point"),),
            ),
            _method_contract(
                "parameterized_point_locus_line",
                slot_reads=(_slot("coordinate", "Point", object_kind="point"),),
                slot_writes=(_slot("locus", "Line", object_kind="line"),),
            ),
            _method_contract(
                "line_locus_minimum_point",
                slot_reads=(_slot("locus", "Line", object_kind="line"),),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        write_mode="transition",
                    ),
                ),
            ),
        ),
    ),
))


__all__ = [
    "DEFAULT_CAPABILITY_PACK_REGISTRY",
    "RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT",
    "TWO_MOVING_POINTS_PATH_REDUCTION",
    "BROKEN_PATH_STRAIGHTENING_AND_SELECT",
    "PATH_MINIMUM_BY_STRAIGHTENED_DISTANCE",
    "BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION",
    "EQUAL_LENGTH_RAY_PATH_REDUCTION",
]
