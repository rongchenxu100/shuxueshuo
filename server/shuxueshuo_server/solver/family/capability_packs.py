"""Capability Pack registry for solver families."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import (
    ScalarResultFormSpec,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityContractSpec,
    CapabilityContextRoleBindingSpec,
    CapabilityInputClosureRequirement,
    CapabilityCardinality,
    CapabilityDependencyPolicy,
    CapabilityExecutionStatus,
    FunctionalReturnBindingPolicy,
    FunctionalSemanticRefRole,
    CapabilityPackRegistry,
    CapabilityPackSpec,
    CapabilityStateClosurePolicy,
    CONDITION_OBJECT_ROLES_RESOLVER,
    COUPLED_SEGMENT_PATH_ROLES_RESOLVER,
    EQUAL_LENGTH_RAY_PATH_ROLES_RESOLVER,
    ConditionPattern,
    GoalEvidencePolicySpec,
    MethodBindingRuleSpec,
    MacroSearchSpec,
    QUADRATIC_SQUARE_PATH_ROLES_RESOLVER,
    WEIGHTED_AXIS_PATH_MINIMUM_ROLES_RESOLVER,
    RecipeExecutionSpec,
    recipe_output_alias,
    StateSlotPattern,
    StateIdentityConstraintSpec,
    StateLineageClosureSpec,
    StateObjectRoleProjectionSpec,
    StateWriteMode,
    StepRecipeSpec,
)
from shuxueshuo_server.solver.family.common_binding_rules import (
    condition_arg_binding,
    distance_between_points_rule,
    evaluate_expression_at_parameter_rule,
    evaluate_point_at_parameter_rule,
    line_intersection_point_rule,
    line_parabola_second_intersection_point_rule,
    latest_state_binding,
    point_on_parabola_at_x_rule,
    midpoint_point_rule,
    parameter_from_curve_point_on_quadratic_rule,
    parameter_from_expression_value_rule,
    public_arg_binding,
    quadratic_from_constraints_rule,
    quadratic_vertex_point_rule,
    quadratic_x_axis_intercept_point_rule,
    quadratic_y_axis_intercept_point_rule,
    translated_point_rule,
)
from shuxueshuo_server.solver.output_type_policy import TRANSIENT_OUTPUT_TYPES


RIGHT_ANGLE_EQUAL_LENGTH_DO_NOT_USE_WHEN = (
    "只有直角或等长中的单个条件，无法确定构造点所需的完整对象角色和约束。",
    (
        "只有完整直角等长关系、曲线归属和参数正负条件，但没有明确的象限、"
        "方向或唯一几何筛选条件；此时应先列出全部几何候选，再使用曲线和参数"
        "条件筛选，不能假定默认旋转方向。"
    ),
)
EQUAL_LENGTH_RAY_PATH_REDUCTION_DESCRIPTION = (
    "仅用于一个动点在线段上、另一个动点在射线上，并且题设给出二者相对"
    "同一端点的等长关系。该能力在内部完成辅助点构造，把两动点距离和直接"
    "化为一个固定点到辅助点的单距离最小值表达式；它返回 "
    "MinimumExpression，而不是供后续普通折线拉直的内部路径中间值。"
    "结果仍含参数时为开放表达式，不含自由参数时为闭合值。"
)
EQUAL_LENGTH_RAY_PATH_REDUCTION_DO_NOT_USE_WHEN = (
    "缺少“一个点在线段、一个点在射线、相对同一端点等长”中的任一结构化条件。",
    (
        "原路径只是普通两段等长/比例替换、三段正方形路径或带权距离；"
        "这些结构应使用各自的路径降维能力。"
    ),
)




def _slot(
    state_kind: str,
    runtime_type: str,
    *,
    object_kind: str | None = None,
    semantic_role: str | None = None,
    output_key: str | None = None,
    cardinality: CapabilityCardinality = "one",
    required: bool | None = None,
    identity_policy: StateIdentityPolicy | None = None,
    identity_arg: str | None = None,
    write_mode: StateWriteMode | None = None,
    description: str = "",
    provides_semantic_roles: tuple[str, ...] = (),
    result_form: ScalarResultFormSpec | None = None,
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = (),
    lineage_closures: tuple[StateLineageClosureSpec, ...] = (),
    input_closure_policy: CapabilityStateClosurePolicy = "any",
    return_binding: FunctionalReturnBindingPolicy = "auto",
    semantic_ref_role: FunctionalSemanticRefRole = "value",
    allows_anonymous_result: bool = False,
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
        semantic_role=semantic_role,
        output_key=output_key,
        cardinality=cardinality,
        required=resolved_required,
        identity_policy=identity_policy,
        identity_arg=identity_arg,
        write_mode=(
            write_mode
            if write_mode is not None
            else ("create" if runtime_type in {"Point", "PointList"} else "value")
        ),
        description=description,
        provides_semantic_roles=provides_semantic_roles,
        result_form=result_form,
        object_role_projections=object_role_projections,
        lineage_closures=lineage_closures,
        input_closure_policy=input_closure_policy,
        return_binding=return_binding,
        semantic_ref_role=semantic_ref_role,
        allows_anonymous_result=allows_anonymous_result,
    )


def _parabola_read(*, semantic_role: str | None = None) -> StateSlotPattern:
    return _slot(
        "expression",
        "Parabola",
        object_kind="function",
        semantic_role=semantic_role,
        input_closure_policy="closed_or_single_free",
        description=(
            "读取当前函数对象已计算出的抛物线状态。允许 closed_state，或只依赖"
            "一个独立自由参数的 open_state；题面 Function 模板仅在代码能由可见"
            "系数值确定性物化到该边界时可直接引用。"
        ),
    )


def _condition(
    condition_kind: str,
    *,
    runtime_type: str = "Condition",
    required: bool = True,
    semantic_role: str | None = None,
    accepted_condition_kinds: tuple[str, ...] = (),
    description: str = "",
) -> ConditionPattern:
    return ConditionPattern(
        condition_kind=condition_kind,
        runtime_type=runtime_type,
        required=required,
        semantic_role=semantic_role,
        accepted_condition_kinds=accepted_condition_kinds,
        description=description,
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
    dependency_policy: CapabilityDependencyPolicy = "explicit_args",
    context_resolvers: tuple[CapabilityContextResolver, ...] = (),
    context_role_bindings: tuple[
        CapabilityContextRoleBindingSpec, ...
    ] = (),
    input_closure_requirements: tuple[
        CapabilityInputClosureRequirement, ...
    ] = (),
    identity_constraints: tuple[StateIdentityConstraintSpec, ...] = (),
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
        dependency_policy=dependency_policy,
        context_resolvers=context_resolvers,
        context_role_bindings=context_role_bindings,
        input_closure_requirements=input_closure_requirements,
        identity_constraints=identity_constraints,
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
    dependency_policy: CapabilityDependencyPolicy = "explicit_args",
    context_resolvers: tuple[CapabilityContextResolver, ...] = (),
    context_role_bindings: tuple[
        CapabilityContextRoleBindingSpec, ...
    ] = (),
    input_closure_requirements: tuple[
        CapabilityInputClosureRequirement, ...
    ] = (),
    identity_constraints: tuple[StateIdentityConstraintSpec, ...] = (),
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
        dependency_policy=dependency_policy,
        context_resolvers=context_resolvers,
        context_role_bindings=context_role_bindings,
        input_closure_requirements=input_closure_requirements,
        identity_constraints=identity_constraints,
    )


QUADRATIC_CORE_CONTRACTS = (
    _method_contract(
        "quadratic_axis_from_relation",
        condition_reads=(_condition("coefficient_relation", runtime_type="Equation"),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="axis_point",
            ),
        ),
    ),
    _method_contract(
        "quadratic_from_constraints",
        slot_reads=(
            _slot("expression", "Function", object_kind="function"),
            _slot(
                "coefficients",
                "Coefficients",
                object_kind="function",
                semantic_role="known_coefficients",
                required=False,
                description=(
                    "零个或多个已经求得的二次函数系数值。多个系数统一放在这里，"
                    "不要再重复写入 parameter_value。"
                ),
            ),
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="curve_point",
                required=False,
                description=(
                    "单个已知坐标的曲线点；多个曲线点请改用 curve_points，"
                    "不要在两个参数中重复同一点。"
                ),
            ),
            _slot(
                "coordinate",
                "PointList",
                object_kind="point",
                semantic_role="curve_points",
                required=False,
                description=(
                    "零个或多个已知坐标的曲线点；每个点都会作为独立曲线约束。"
                ),
            ),
            _slot(
                "symbol",
                "SymbolList",
                object_kind="symbol",
                semantic_role="free_parameters",
                required=False,
                description=(
                    "应用当前scope约束后仍未确定的一组完整独立参数基底。开放状态"
                    "必须填写非空基底；闭合状态可填写[]或省略。可使用runtime可证明"
                    "等价的任一基底，不得按下游Goal目标人为收窄。"
                ),
            ),
            _slot(
                "value",
                "ParameterValue",
                object_kind="symbol",
                semantic_role="parameter_value",
                required=False,
                description=(
                    "单个需要代入当前抛物线状态的已求参数值。它不是多个已知系数的"
                    "容器；多个系数请使用 known_coefficients。"
                ),
            ),
            _slot(
                "symbol",
                "Symbol",
                object_kind="symbol",
                semantic_role="target_parameter",
                required=False,
                description="本轮希望明确求出的二次函数系数。",
            ),
        ),
        condition_reads=(
            _condition(
                "coefficient_relation",
                runtime_type="Equation",
                required=False,
                description="题面给出的二次函数系数等式关系。",
            ),
            _condition(
                "extra_equation",
                runtime_type="Equation",
                required=False,
                description=(
                    "用于求系数的额外等式。参数范围、不等式和定义域条件不能填入这里。"
                ),
            ),
            _condition("point_on_curve", required=False),
        ),
        slot_writes=(
            _slot(
                "expression",
                "Parabola",
                object_kind="function",
                output_key="parabola",
            ),
            _slot(
                "coefficients",
                "Coefficients",
                object_kind="function",
                output_key="coefficients",
            ),
            _slot(
                "value",
                "ParameterValue",
                object_kind="symbol",
                semantic_role="target_parameter",
                output_key="parameter_value",
                required=False,
                description=(
                    "target_parameter 的当前值；仍依赖明确保留的参数时是开放 Symbol 状态。"
                ),
                result_form=ScalarResultFormSpec(
                    possible_forms=("open_state", "closed_state"),
                    description=(
                        "仍依赖 free_parameters 时为 open_state；不存在自由符号时为 "
                        "closed_state。"
                    ),
                ),
            ),
        ),
        constraint_analyzer="quadratic_coefficients",
    ),
    _method_contract(
        "quadratic_vertex_point",
        slot_reads=(_parabola_read(),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="vertex",
            ),
        ),
    ),
    _method_contract(
        "quadratic_x_axis_intercept_point",
        slot_reads=(
            _parabola_read(),
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="known_point",
                required=False,
                description=(
                    "可选的另一个 x 轴交点，必须已经具有坐标。不能填写当前正在求解"
                    "的目标点；若没有另一个已知坐标的交点则直接省略。"
                ),
            ),
        ),
        condition_reads=(_condition("x_axis_known_point", required=False),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="x_axis_intercept",
            ),
        ),
    ),
    _method_contract(
        "quadratic_y_axis_intercept_point",
        slot_reads=(
            _slot(
                "expression",
                "Expression",
                object_kind="function",
                semantic_role="quadratic",
                description=(
                    "读取题面函数模板或当前抛物线表达式。本能力只取 x=0，"
                    "因此不要求先闭合与常数项无关的其它系数。"
                ),
            ),
        ),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="y_axis_intercept",
            ),
        ),
    ),
    _method_contract(
        "point_on_parabola_at_x",
        slot_reads=(_parabola_read(semantic_role="parabola"),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                output_key="point",
                description=(
                    "返回 return binding 指向的同一个 Point 对象。该已有对象必须"
                    "已经在题面结构化定义中直接给出 x 或 x_coordinate；代码读取"
                    "该横坐标并用抛物线计算纵坐标。坐标仍含未确定参数时为"
                    " open_state。"
                ),
                lineage_closures=(
                    StateLineageClosureSpec(
                        source_args=("parabola", "target"),
                        add_evidence_tags=("curve_membership",),
                        description=(
                            "目标点的横坐标必须来自结构化定义；代入抛物线后，"
                            "输出才获得曲线成员证据。"
                        ),
                    ),
                ),
            ),
        ),
    ),
    _method_contract(
        "quadratic_axis_x_intercept_point",
        slot_reads=(_parabola_read(),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="axis_x_intercept",
            ),
        ),
    ),
    _method_contract(
        "line_parabola_second_intersection_point",
        slot_reads=(
            _parabola_read(),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        condition_reads=(_condition("line_relation", required=False),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="curve_intersection_point",
                provides_semantic_roles=("curve_intersection_point",),
                lineage_closures=(
                    StateLineageClosureSpec(
                        source_args=(
                            "parabola",
                            "line_p1",
                            "line_p2",
                            "known_point",
                        ),
                        add_evidence_tags=("curve_membership",),
                        description=(
                            "输出由已知直线与抛物线的另一个交点推出，"
                            "因此携带曲线成员证据。"
                        ),
                    ),
                ),
            ),
        ),
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
        "parameter_from_segment_length",
        slot_reads=(
            _slot("coordinate", "Point", object_kind="point"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        condition_reads=(_condition("length_squared"),),
        slot_writes=(_slot("value", "ParameterValue", object_kind="symbol"),),
        identity_constraints=(
            StateIdentityConstraintSpec(
                left="args:p1,p2.object_ref",
                right="arg:length_squared.object_role:endpoint",
                relation="same_object_set",
                description=(
                    "p1、p2 必须是长度条件所声明线段的两个端点；"
                    "端点顺序可以交换。"
                ),
            ),
            StateIdentityConstraintSpec(
                left="args:reference_p1,reference_p2.object_ref",
                right=(
                    "arg:length_squared.object_role:reference_endpoint"
                ),
                relation="same_object_set",
                applicability="when_all_present",
                description=(
                    "比例长度条件的 reference_p1、reference_p2 必须是"
                    "参照线段的两个端点；端点顺序可以交换。"
                ),
            ),
        ),
    ),
    _method_contract(
        "parameter_from_minimum_value",
        slot_reads=(_slot("expression", "MinimumExpression"),),
        condition_reads=(_condition("minimum_value"),),
        slot_writes=(_slot("value", "ParameterValue", object_kind="symbol"),),
    ),
    _method_contract(
        "parameter_from_curve_point_on_quadratic",
        execution_status="internal",
        exposes_to_llm=False,
        slot_reads=(
            _slot("expression", "Parabola", object_kind="function"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        condition_reads=(_condition("parameter_constraint", required=False),),
        slot_writes=(
            _slot(
                "value",
                "ParameterValue",
                object_kind="symbol",
                description=(
                    "曲线点条件唯一确定的目标 Symbol 值；若条件先确定另一二次函数"
                    "系数，代码会沿当前系数表达式闭包到所绑定的目标 Symbol。"
                ),
            ),
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                required=False,
                write_mode="transition",
                description="代入本次求得参数后的同一曲线点状态。",
            ),
            _slot(
                "expression",
                "Parabola",
                object_kind="function",
                required=False,
                write_mode="transition",
                description="代入当前所有已知参数后的同一抛物线状态。",
            ),
        ),
    ),
    _method_contract(
        "evaluate_expression_at_parameter",
        slot_reads=(
            _slot("expression", "Expression"),
            _slot("expression", "MinimumExpression"),
            _slot(
                "expression",
                "Parabola",
                object_kind="function",
                description=(
                    "需要代入一个已知参数值的当前 Expression、MinimumExpression 或 "
                    "Parabola 状态。题面 Function 模板不是已经得到的 Parabola 状态；"
                    "输入类型会确定唯一的同类型 return。"
                ),
            ),
            _slot("value", "ParameterValue", object_kind="symbol"),
        ),
        slot_writes=(
            _slot(
                "expression",
                "Expression",
                output_key="evaluated_expression",
                required=False,
                cardinality="optional",
                description=(
                    "仅当输入是 Expression 状态时产生；不能作为 Parabola 传给曲线"
                    "顶点、交点或对称轴能力。"
                ),
            ),
            _slot(
                "expression",
                "MinimumExpression",
                output_key="evaluated_minimum_expression",
                required=False,
                cardinality="optional",
                description="仅当输入是 MinimumExpression 状态时产生。",
            ),
            _slot(
                "expression",
                "Parabola",
                object_kind="function",
                output_key="evaluated_parabola",
                required=False,
                cardinality="optional",
                write_mode="transition",
                description=(
                    "仅当输入已经是 Parabola 状态时产生，表示代入参数后的同一"
                    "抛物线状态；普通 Expression 输入不会产生该 return。"
                ),
            ),
        ),
    ),
    _method_contract(
        "evaluate_point_at_parameter",
        slot_reads=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                description="同一对象当前已有的含参坐标状态。",
            ),
            _slot(
                "value",
                "ParameterValue",
                object_kind="symbol",
                description=(
                    "用于消去点坐标中同一 Symbol 身份自由参数的已求值；不能用"
                    "曲线系数值代替动点独立的位置参数。"
                ),
            ),
        ),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                write_mode="transition",
                description="代入参数后的同一 Point 坐标状态，不产生新的几何对象。",
            ),
        ),
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
            _slot(
                "expression",
                "MinimumExpression",
                output_key="distance",
            ),
            _slot(
                "expression",
                "MinimumExpression",
                output_key="evaluated_distance",
                required=False,
            ),
        ),
    ),
    _method_contract(
        "midpoint_point",
        condition_reads=(_condition("midpoint_definition"),),
        slot_writes=(_slot("coordinate", "Point", object_kind="point"),),
        dependency_policy="context_closure",
        context_resolvers=(CONDITION_OBJECT_ROLES_RESOLVER,),
        context_role_bindings=(
            CapabilityContextRoleBindingSpec(
                CONDITION_OBJECT_ROLES_RESOLVER,
                "p1",
                "p1",
            ),
            CapabilityContextRoleBindingSpec(
                CONDITION_OBJECT_ROLES_RESOLVER,
                "p2",
                "p2",
            ),
        ),
    ),
    _method_contract(
        "translated_point",
        slot_reads=(_slot("coordinate", "Point", object_kind="point"),),
        condition_reads=(_condition("translation"),),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                semantic_role="translated_point",
            ),
        ),
    ),
    _method_contract(
        "line_intersection_point",
        slot_reads=(
            _slot("coordinate", "Point", object_kind="point"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
            ),
        ),
    ),
)


RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT = StepRecipeSpec(
    recipe_id="right_angle_equal_length_construct_and_select",
    goal_type="derive_constructed_point",
    title="直角等腰构造并筛选点",
    description=(
        "仅在直角等腰关系之外，还存在能够直接唯一选择旋转分支的象限、方向"
        "或同类几何筛选条件时，生成候选并立即选出目标点。若分支只能通过"
        "“点在曲线上”和参数正负条件确定，应使用候选生成能力后再进行曲线筛选。"
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
        execution_mode="direct",
        execution_strategy="right_angle_construct_select",
        strategy_input_targets=(
            "right_angle_equal_length_candidates.anchor",
            "right_angle_equal_length_candidates.reference",
            "right_angle_equal_length_candidates.target",
            "select_point_by_quadrant_constraint.target",
            "select_point_by_quadrant_constraint.quadrant",
            "select_point_by_quadrant_constraint.parameter",
            "select_point_by_quadrant_constraint.parameter_constraint",
        ),
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
    do_not_use_when=RIGHT_ANGLE_EQUAL_LENGTH_DO_NOT_USE_WHEN,
)





EQUAL_LENGTH_RAY_PATH_REDUCTION = StepRecipeSpec(
    recipe_id="equal_length_ray_path_reduction",
    goal_type="derive_path_minimum_expression",
    title="等长射线路径降维为单距离最值",
    description=EQUAL_LENGTH_RAY_PATH_REDUCTION_DESCRIPTION,
    method_ids=("equal_length_ray_point", "distance_between_points"),
    execution=RecipeExecutionSpec(
        recipe_id="equal_length_ray_path_reduction",
        method_sequence=("equal_length_ray_point", "distance_between_points"),
        execution_mode="runtime_search",
        search=MacroSearchSpec(
            searchable_roles=(
                "anchor",
                "reference_point",
                "ray_point",
                "fixed_point",
            ),
            candidate_builder_id="equal_length_ray_role_assignments",
            validation_policy_id="distance_equivalence_and_provenance",
            lowerer_id="equal_length_ray_path_reduction",
            postcondition_id="equal_length_ray_path_postcondition",
            evidence_builder_id="equal_length_ray_path_witness",
        ),
        execution_strategy="equal_length_ray_path_reduction",
        creates=("point",),
        strategy_input_targets=(
            "equal_length_ray_point.anchor",
            "equal_length_ray_point.reference_point",
            "equal_length_ray_point.ray_point",
            "equal_length_ray_point.target",
            "distance_between_points.p1",
        ),
        intermediate_wiring=(
            (
                "equal_length_ray_point.point",
                "distance_between_points.p2",
            ),
        ),
        output_aliases=(
            recipe_output_alias(
                "distance_between_points.distance",
                "MinimumExpression",
                "minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
            ),
        ),
    ),
    priority="preferred",
    do_not_use_when=EQUAL_LENGTH_RAY_PATH_REDUCTION_DO_NOT_USE_WHEN,
)


QUADRATIC_SQUARE_PATH_MINIMUM = StepRecipeSpec(
    recipe_id="quadratic_square_path_minimum",
    goal_type="derive_path_minimum_expression",
    title="二次函数正方形路径最值",
    description=(
        "当二次函数确定正方形相关点的参数化状态，且题面路径可由正方形的"
        "中点、中心和旋转关系降为单动点直线轨迹时，原子地求出最小值表达式"
        "和取等号时的降维后正方形动点。Planner 只选择当前抛物线、路径目标和"
        "正方形；相关中点、中心、轴成员关系及几何角色由代码解析并验证。"
        "attainment_point 的对象身份也由代码绑定，不是当前 Goal 的最终答案点；"
        "后续应通过 StepResultRef 消费，不要为它设置 output_targets。"
    ),
    method_ids=("quadratic_square_path_minimum_kernel",),
    execution=RecipeExecutionSpec(
        recipe_id="quadratic_square_path_minimum",
        method_sequence=("quadratic_square_path_minimum_kernel",),
        execution_mode="runtime_search",
        search=MacroSearchSpec(
            searchable_roles=(
                "midpoint_definition",
                "square_center",
                "axis_membership",
                "side_start",
                "axis_point",
                "moving_point",
                "fixed_endpoint",
            ),
            candidate_builder_id="quadratic_square_path_role_assignments",
            validation_policy_id="path_equivalence_and_attainment",
            lowerer_id="quadratic_square_path_minimum",
            postcondition_id="quadratic_square_path_postcondition",
            evidence_builder_id="quadratic_square_path_witness",
        ),
        execution_strategy="quadratic_square_path_minimum",
        input_aliases=(
            ("parabola", "quadratic_square_path_minimum_kernel.parabola"),
            (
                "path_minimum_target",
                "quadratic_square_path_minimum_kernel.path_condition",
            ),
            ("square", "quadratic_square_path_minimum_kernel.square_condition"),
        ),
        strategy_input_targets=(
            "quadratic_square_path_minimum_kernel.midpoint_definition",
            "quadratic_square_path_minimum_kernel.square_center",
            "quadratic_square_path_minimum_kernel.axis_membership",
            "quadratic_square_path_minimum_kernel.side_start",
            "quadratic_square_path_minimum_kernel.side_start_ref",
            "quadratic_square_path_minimum_kernel.axis_point",
            "quadratic_square_path_minimum_kernel.moving_point",
            "quadratic_square_path_minimum_kernel.fixed_endpoint",
        ),
        output_aliases=(
            recipe_output_alias(
                "quadratic_square_path_minimum_kernel.minimum_expression",
                "MinimumExpression",
                "minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
                result_form=ScalarResultFormSpec(
                    possible_forms=("open_expression", "closed_value"),
                    description=(
                        "仍依赖二次函数主参数时为 open_expression；参数已确定"
                        "且表达式无自由符号时为 closed_value。"
                    ),
                ),
            ),
            recipe_output_alias(
                "quadratic_square_path_minimum_kernel.attainment_point",
                "Point",
                "attainment_point",
                identity_policy="target_object",
                identity_arg="moving_point",
                reference_mode="exact_result",
                goal_evidence_tags=("path_minimum_extremal_point",),
                description=(
                    "正方形关系降维后唯一动点的取等坐标；对象身份由代码从"
                    "结构化路径和正方形中解析。不要把它绑定为当前 Goal 的"
                    "最终答案点，后续直接用 StepResultRef 消费。"
                ),
            ),
        ),
    ),
    priority="preferred",
    do_not_use_when=(
        "正方形不参与路径降维或轨迹传播。",
        "路径含有无法消除的两个独立动点。",
        "有效动点轨迹不是直线，或目标是加权距离。",
        "当前函数状态不是二次函数。",
    ),
)


WEIGHTED_AXIS_PATH_MINIMUM = StepRecipeSpec(
    recipe_id="weighted_axis_path_minimum",
    goal_type="derive_path_minimum_expression",
    title="加权轴上路径最值",
    description=(
        "当路径目标恰由一个非单位权重线段和一个普通线段组成、两项共享同一"
        "轴上动点，且加权端点已有单参数坐标状态时，原子完成辅助三角形、"
        "轨迹、折线拉直、合法域和取等可达性验证。Planner 只选择完整的 "
        "path_minimum_target；曲线端点、轴上固定端点、动点、两个参数及其"
        "定义域全部由代码从 typed path terms 和可见状态唯一解析。该 Macro "
        "只返回最小值表达式；题设给定最小值后，继续用普通参数求解能力。"
    ),
    method_ids=("weighted_axis_path_minimum_kernel",),
    execution=RecipeExecutionSpec(
        recipe_id="weighted_axis_path_minimum",
        method_sequence=("weighted_axis_path_minimum_kernel",),
        execution_mode="runtime_search",
        search=MacroSearchSpec(
            searchable_roles=(
                "fixed_point",
                "curve_point",
                "moving_point",
                "parameter",
                "dynamic_parameter",
                "parameter_constraint",
                "dynamic_constraint",
            ),
            candidate_builder_id="weighted_axis_path_role_assignments",
            validation_policy_id="path_equivalence_and_attainment",
            lowerer_id="weighted_axis_path_minimum",
            postcondition_id="weighted_axis_path_postcondition",
            evidence_builder_id="weighted_axis_path_witness",
        ),
        execution_strategy="weighted_axis_path_minimum",
        input_aliases=(
            (
                "path_minimum_target",
                "weighted_axis_path_minimum_kernel.path_condition",
            ),
        ),
        strategy_input_targets=tuple(
            f"weighted_axis_path_minimum_kernel.{name}"
            for name in (
                "fixed_point",
                "curve_point",
                "moving_point",
                "moving_point_ref",
                "parameter",
                "dynamic_parameter",
                "parameter_constraint",
                "dynamic_constraint",
            )
        ),
        output_aliases=(
            recipe_output_alias(
                "weighted_axis_path_minimum_kernel.minimum_expression",
                "MinimumExpression",
                "minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
                result_form=ScalarResultFormSpec(
                    possible_forms=("open_expression", "closed_value"),
                    description=(
                        "仍依赖主参数时为 open_expression；参数已确定且结果"
                        "无自由符号时为 closed_value。定义域边界会由内核"
                        "直接表示为 Piecewise，不增加 Planner 步骤。"
                    ),
                ),
            ),
        ),
    ),
    priority="preferred",
    do_not_use_when=(
        "路径没有非单位权重，或两项不共享同一个轴上动点。",
        "加权系数没有登记对应的辅助三角形几何 profile。",
        "加权端点尚未物化为只含一个主参数的 Point 状态。",
        "目标需要正方形降维、两动点端点替换或等长射线构造。",
    ),
)


COUPLED_SEGMENT_ENDPOINT_REPLACEMENT_PATH_MINIMUM = StepRecipeSpec(
    recipe_id="coupled_segment_endpoint_replacement_path_minimum",
    goal_type="derive_path_minimum_expression",
    title="耦合线段端点替换路径最值",
    description=(
        "当两动点分别位于两条相接线段，且题面比例/等长关系能够把两动点"
        "之间的距离替换为已有固定端点到保留动点的距离时，原子完成端点"
        "替换、单动点轨迹、折线拉直、最小值和取等点。Planner 只选择路径"
        "目标与负责耦合的线段关系；成员关系、端点和保留动点由代码解析。"
        "若其中的固定端点由中点等题面构造定义，先用对应普通 Function 物化"
        "该点坐标；这只是准备输入，不是展开 Macro。"
    ),
    method_ids=("coupled_segment_endpoint_replacement_path_minimum_kernel",),
    execution=RecipeExecutionSpec(
        recipe_id="coupled_segment_endpoint_replacement_path_minimum",
        method_sequence=(
            "coupled_segment_endpoint_replacement_path_minimum_kernel",
        ),
        execution_mode="runtime_search",
        search=MacroSearchSpec(
            searchable_roles=(
                "first_membership",
                "second_membership",
                "first_segment_start",
                "joint_point",
                "second_segment_end",
                "transformed_fixed_endpoint",
                "moving_point",
            ),
            candidate_builder_id="coupled_segment_path_role_assignments",
            validation_policy_id="path_equivalence_and_attainment",
            lowerer_id="coupled_segment_path_minimum",
            postcondition_id="coupled_segment_path_postcondition",
            evidence_builder_id="coupled_segment_path_witness",
        ),
        execution_strategy="coupled_segment_path_minimum",
        input_aliases=(
            (
                "path_minimum_target",
                "coupled_segment_endpoint_replacement_path_minimum_kernel.path_condition",
            ),
            (
                "segment_binding_relation",
                "coupled_segment_endpoint_replacement_path_minimum_kernel.segment_binding_relation",
            ),
        ),
        strategy_input_targets=tuple(
            "coupled_segment_endpoint_replacement_path_minimum_kernel."
            + role
            for role in (
                "first_membership",
                "second_membership",
                "first_segment_start",
                "joint_point",
                "second_segment_end",
                "transformed_fixed_endpoint",
                "moving_point",
            )
        ),
        output_aliases=(
            recipe_output_alias(
                "coupled_segment_endpoint_replacement_path_minimum_kernel.minimum_expression",
                "MinimumExpression",
                "minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
                result_form=ScalarResultFormSpec(
                    possible_forms=("open_expression", "closed_value"),
                    description=(
                        "仍依赖题面参数时为 open_expression；参数确定后为 closed_value。"
                    ),
                ),
            ),
            recipe_output_alias(
                "coupled_segment_endpoint_replacement_path_minimum_kernel.attainment_point",
                "Point",
                "attainment_point",
                identity_policy="target_object",
                identity_arg="moving_point",
                reference_mode="exact_result",
                goal_evidence_tags=("path_minimum_extremal_point",),
                description=(
                    "端点替换后保留动点的取等状态；身份由代码从路径和线段关系"
                    "中确定，后续通过 StepResultRef 消费。"
                ),
            ),
        ),
    ),
    priority="preferred",
    do_not_use_when=(
        "路径本身已经只有一个动点，不需要耦合端点替换。",
        "比例关系要求创建新的辅助点、射线、正方形变换或非1权重构造。",
        "两动点的成员关系与耦合线段不能形成唯一连通结构。",
        "保留动点的轨迹不是直线。",
    ),
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
            point_on_parabola_at_x_rule(),
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
            parameter_from_curve_point_on_quadratic_rule(),
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
                context_resolvers=(CONDITION_OBJECT_ROLES_RESOLVER,),
            ),
            _method_contract(
                "right_angle_equal_length_candidates",
                condition_reads=(_condition("right_angle_equal_length"),),
                slot_writes=(
                    _slot(
                        "candidate",
                        "PointList",
                        object_kind="point",
                        return_binding="internal_only",
                    ),
                ),
                context_resolvers=(CONDITION_OBJECT_ROLES_RESOLVER,),
                context_role_bindings=tuple(
                    CapabilityContextRoleBindingSpec(
                        CONDITION_OBJECT_ROLES_RESOLVER,
                        role,
                        role,
                    )
                    for role in ("anchor", "reference", "target")
                ),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="weighted_axis_path_minimum_core",
        kind="mechanism",
        method_ids=("weighted_axis_path_minimum_kernel",),
        step_recipes=(WEIGHTED_AXIS_PATH_MINIMUM,),
        contracts=(
            _recipe_contract(
                "weighted_axis_path_minimum",
                slot_reads=(
                    *tuple(
                        _slot(
                            "coordinate",
                            "Point",
                            object_kind="point",
                            semantic_role=role,
                        )
                        for role in (
                            "fixed_point",
                            "curve_point",
                            "moving_point",
                        )
                    ),
                    _slot(
                        "symbol",
                        "Symbol",
                        object_kind="symbol",
                        semantic_role="parameter",
                    ),
                    _slot(
                        "symbol",
                        "Symbol",
                        object_kind="symbol",
                        semantic_role="dynamic_parameter",
                    ),
                ),
                condition_reads=(
                    _condition("path_minimum_target"),
                    _condition(
                        "symbol_constraint",
                        semantic_role="parameter_constraint",
                    ),
                    _condition(
                        "symbol_constraint",
                        semantic_role="dynamic_constraint",
                    ),
                ),
                slot_writes=(
                    _slot(
                        "expression",
                        "MinimumExpression",
                        output_key=(
                            "weighted_axis_path_minimum_kernel.minimum_expression"
                        ),
                        result_form=ScalarResultFormSpec(
                            possible_forms=("open_expression", "closed_value"),
                            description=(
                                "仍依赖主参数时为 open_expression；定义域边界"
                                "由同一个表达式中的 Piecewise 分支表示。"
                            ),
                        ),
                    ),
                ),
                dependency_policy="context_closure",
                context_resolvers=(
                    WEIGHTED_AXIS_PATH_MINIMUM_ROLES_RESOLVER,
                ),
                context_role_bindings=tuple(
                    CapabilityContextRoleBindingSpec(
                        WEIGHTED_AXIS_PATH_MINIMUM_ROLES_RESOLVER,
                        role,
                        role,
                    )
                    for role in (
                        "fixed_point",
                        "curve_point",
                        "moving_point",
                        "parameter",
                        "dynamic_parameter",
                        "parameter_constraint",
                        "dynamic_constraint",
                    )
                ),
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
                slot_reads=tuple(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role=role,
                    )
                    for role in (
                        "anchor",
                        "reference_point",
                        "ray_point",
                        "fixed_point",
                    )
                ),
                condition_reads=(
                    _condition("path_minimum_target"),
                    _condition("equal_length_condition"),
                    _condition("point_on_segment"),
                    _condition("point_on_ray"),
                ),
                slot_writes=(_slot("expression", "MinimumExpression"),),
                dependency_policy="context_closure",
                context_resolvers=(EQUAL_LENGTH_RAY_PATH_ROLES_RESOLVER,),
                context_role_bindings=tuple(
                    CapabilityContextRoleBindingSpec(
                        EQUAL_LENGTH_RAY_PATH_ROLES_RESOLVER,
                        role,
                        role,
                    )
                    for role in (
                        "anchor",
                        "reference_point",
                        "ray_point",
                        "fixed_point",
                    )
                ),
            ),
            _method_contract(
                "equal_length_ray_point",
                condition_reads=(_condition("equal_length_ray"),),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        description=(
                            "射线上的等长构造点。作为中间辅助点时可不绑定"
                            "题面对象，后续调用直接引用本 call 的 point 结果；"
                            "作为题面对象或答案时仍应显式绑定。"
                        ),
                        return_binding="call_local_allowed",
                    ),
                ),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="coupled_segment_path_minimum_core",
        kind="mechanism",
        method_ids=(
            "coupled_segment_endpoint_replacement_path_minimum_kernel",
        ),
        step_recipes=(COUPLED_SEGMENT_ENDPOINT_REPLACEMENT_PATH_MINIMUM,),
        contracts=(
            _recipe_contract(
                "coupled_segment_endpoint_replacement_path_minimum",
                slot_reads=tuple(
                        _slot(
                            "coordinate",
                            "Point",
                            object_kind="point",
                            semantic_role=role,
                        )
                        for role in (
                            "first_segment_start",
                            "joint_point",
                            "second_segment_end",
                            "transformed_fixed_endpoint",
                            "moving_point",
                        )
                ),
                condition_reads=(
                    _condition("path_minimum_target"),
                    _condition(
                        "segment_length_relation",
                        semantic_role="segment_binding_relation",
                        accepted_condition_kinds=(
                            "segment_relation",
                            "segment_length_relation",
                        ),
                    ),
                    _condition("first_membership"),
                    _condition("second_membership"),
                ),
                slot_writes=(
                    _slot(
                        "expression",
                        "MinimumExpression",
                        output_key=(
                            "coupled_segment_endpoint_replacement_path_minimum_kernel."
                            "minimum_expression"
                        ),
                        result_form=ScalarResultFormSpec(
                            possible_forms=("open_expression", "closed_value"),
                            description=(
                                "仍依赖题面参数时为 open_expression；参数确定后为 closed_value。"
                            ),
                        ),
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="attainment_point",
                        output_key=(
                            "coupled_segment_endpoint_replacement_path_minimum_kernel."
                            "attainment_point"
                        ),
                        identity_policy="target_object",
                        identity_arg="moving_point",
                        write_mode="transition",
                        return_binding="explicit_external_required",
                    ),
                ),
                dependency_policy="context_closure",
                context_resolvers=(COUPLED_SEGMENT_PATH_ROLES_RESOLVER,),
                context_role_bindings=tuple(
                    CapabilityContextRoleBindingSpec(
                        COUPLED_SEGMENT_PATH_ROLES_RESOLVER,
                        role,
                        role,
                    )
                    for role in (
                        "first_membership",
                        "second_membership",
                        "first_segment_start",
                        "joint_point",
                        "second_segment_end",
                        "transformed_fixed_endpoint",
                        "moving_point",
                    )
                ),
            ),
        ),
    ),
    CapabilityPackSpec(
        pack_id="quadratic_square_path_minimum_core",
        kind="mechanism",
        method_ids=(
            "quadratic_square_path_minimum_kernel",
            "quadratic_axis_parameterized_point",
            "square_adjacent_vertex_from_side",
            "point_candidates_from_curve_point_condition",
        ),
        step_recipes=(QUADRATIC_SQUARE_PATH_MINIMUM,),
        contracts=(
            _recipe_contract(
                "quadratic_square_path_minimum",
                slot_reads=(
                    _parabola_read(semantic_role="parabola"),
                    *tuple(
                        _slot(
                            "coordinate",
                            "Point",
                            object_kind="point",
                            semantic_role=role,
                        )
                        for role in (
                            "side_start",
                            "axis_point",
                            "moving_point",
                            "fixed_endpoint",
                        )
                    ),
                ),
                condition_reads=(
                    _condition("path_minimum_target"),
                    _condition("square"),
                    _condition("midpoint_definition"),
                    _condition("square_center"),
                    _condition("axis_membership"),
                ),
                slot_writes=(
                    _slot(
                        "expression",
                        "MinimumExpression",
                        output_key=(
                            "quadratic_square_path_minimum_kernel."
                            "minimum_expression"
                        ),
                        result_form=ScalarResultFormSpec(
                            possible_forms=(
                                "open_expression",
                                "closed_value",
                            ),
                            description=(
                                "仍依赖二次函数主参数时为 open_expression；"
                                "参数已确定且表达式无自由符号时为 closed_value。"
                            ),
                        ),
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="attainment_point",
                        output_key=(
                            "quadratic_square_path_minimum_kernel."
                            "attainment_point"
                        ),
                        identity_policy="target_object",
                        identity_arg="moving_point",
                        write_mode="transition",
                        return_binding="explicit_external_required",
                    ),
                ),
                dependency_policy="context_closure",
                context_resolvers=(QUADRATIC_SQUARE_PATH_ROLES_RESOLVER,),
                context_role_bindings=tuple(
                    CapabilityContextRoleBindingSpec(
                        QUADRATIC_SQUARE_PATH_ROLES_RESOLVER,
                        role,
                        role,
                    )
                    for role in (
                        "midpoint_definition",
                        "square_center",
                        "axis_membership",
                        "side_start",
                        "axis_point",
                        "moving_point",
                        "fixed_endpoint",
                    )
                ),
            ),
            _method_contract(
                "quadratic_axis_parameterized_point",
                slot_reads=(_parabola_read(),),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="axis_point",
                        output_key="point",
                        write_mode="create",
                    ),
                    _slot(
                        "parameter",
                        "Symbol",
                        object_kind="symbol",
                        semantic_role="axis_parameter",
                        output_key="parameter",
                        write_mode="value",
                    ),
                ),
            ),
            _method_contract(
                "square_adjacent_vertex_from_side",
                slot_reads=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="side_start",
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="side_end",
                    ),
                ),
                condition_reads=(_condition("square"),),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="square_adjacent_vertex",
                        output_key="point",
                        write_mode="transition",
                        return_binding="explicit_external_required",
                        description=(
                            "由正方形的一条有向边恢复相邻顶点；返回必须绑定"
                            "本次实际求出的题面对象。"
                        ),
                    ),
                ),
            ),
            _method_contract(
                "point_candidates_from_curve_point_condition",
                slot_reads=(
                    _parabola_read(semantic_role="parabola"),
                    _slot(
                        "parameter",
                        "Symbol",
                        object_kind="symbol",
                        semantic_role="parameter",
                    ),
                ),
                condition_reads=(_condition("point_on_curve"),),
                slot_writes=(
                    _slot(
                        "candidate",
                        "PointList",
                        object_kind="point",
                        identity_policy="preserve_input_object",
                        identity_arg="target_point",
                    ),
                ),
            ),
        ),
    ),
))


__all__ = [
    "DEFAULT_CAPABILITY_PACK_REGISTRY",
    "RIGHT_ANGLE_EQUAL_LENGTH_CONSTRUCT_AND_SELECT",
    "EQUAL_LENGTH_RAY_PATH_REDUCTION",
    "WEIGHTED_AXIS_PATH_MINIMUM",
]
