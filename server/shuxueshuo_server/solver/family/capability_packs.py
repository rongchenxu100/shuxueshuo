"""Capability Pack registry for solver families."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import ScalarResultFormSpec
from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CapabilityContractSpec,
    CapabilityContextRoleBindingSpec,
    CapabilityInputClosureRequirement,
    CapabilityCardinality,
    CapabilityDependencyPolicy,
    CapabilityExecutionStatus,
    FunctionalReturnBindingPolicy,
    CapabilityPackRegistry,
    CapabilityPackSpec,
    CapabilityStateClosurePolicy,
    CONDITION_OBJECT_ROLES_RESOLVER,
    ConditionPattern,
    EvidenceInputGroupSpec,
    GoalEvidencePolicySpec,
    MethodBindingRuleSpec,
    MethodInputBindingSpec,
    PATH_REDUCTION_ROLES_RESOLVER,
    PathTransformationConsumerSpec,
    SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER,
    WEIGHTED_PATH_TRANSFORMATION_ROLES_RESOLVER,
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
    distance_between_points_rule,
    evaluate_expression_at_parameter_rule,
    evaluate_point_at_parameter_rule,
    line_intersection_point_rule,
    line_parabola_second_intersection_point_rule,
    point_on_parabola_at_x_rule,
    midpoint_point_rule,
    parameter_from_curve_point_on_quadratic_rule,
    parameter_from_expression_value_rule,
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
TWO_MOVING_POINTS_PATH_REDUCTION_DESCRIPTION = (
    "仅用于原目标路径恰好由两段组成、两段涉及两个相关动点，且题设的"
    "共线、所属、等长或定比例关系能够把其中一段替换为题面已有固定端点"
    "到另一动点的线段；输出等价的单动点两段折线路径。"
    "调用前，变换所需的每个固定端点都必须已有可读取的 Point 坐标状态；"
    "定义、构造或中点 Condition 只说明对象关系，不等于已经计算出坐标。"
    "本 recipe 不创建辅助点、补算固定端点或生成辅助轨迹。"
)
TWO_MOVING_POINTS_REDUCTION_DO_NOT_USE_WHEN = (
    "目标是直接求路径最小值、最小值表达式或极值点坐标；本能力只产生后续路径处理所需的等价变换。",
    (
        "原路径包含三段或更多线段，或必须利用正方形中点/中心、"
        "线段与射线等长、加权距离辅助构造才能降维。"
    ),
    (
        "变换所需的任一固定端点尚无可读取的 Point 坐标状态；"
        "仅有定义、构造或中点关系时，应先得到对应对象的坐标状态。"
    ),
)
EQUAL_LENGTH_RAY_PATH_REDUCTION_DESCRIPTION = (
    "仅用于一个动点在线段上、另一个动点在射线上，并且题设给出二者相对"
    "同一端点的等长关系。该能力在内部完成辅助点构造，把两动点距离和直接"
    "化为一个固定点到辅助点的单距离最小值表达式；它返回 "
    "MinimumExpression，而不是供后续普通折线拉直的 PathTransformation。"
    "结果仍含参数时为开放表达式，不含自由参数时为闭合值。"
)
EQUAL_LENGTH_RAY_PATH_REDUCTION_DO_NOT_USE_WHEN = (
    "缺少“一个点在线段、一个点在射线、相对同一端点等长”中的任一结构化条件。",
    (
        "原路径只是普通两段等长/比例替换、三段正方形路径或带权距离；"
        "这些结构应使用各自的路径降维能力。"
    ),
)
BROKEN_PATH_SELECT_DO_NOT_USE_WHEN = (
    "目标是直接得到最小值表达式、最小值或原路径动点坐标；本能力只选择拉直方案及其内部端点。",
)
STRAIGHTENED_DISTANCE_DO_NOT_USE_WHEN = (
    "尚未得到两个确定的拉直端点，或仍需完成路径降维、反射构造与候选选择。",
)
BROKEN_PATH_MINIMUM_EXPRESSION_DO_NOT_USE_WHEN = (
    (
        "不要把 straightened_endpoint_1、straightened_endpoint_2 或 "
        "straightening_auxiliary_point 直接绑定为原路径动点、极值点或 "
        "Point 答案；它们只是构造最短距离表达式所使用的内部拉直端点。"
    ),
    (
        "不要认为 parameter_value 会同时求值内部拉直端点；它只用于生成 "
        "evaluated_path_minimum_expression。若后续确实需要内部端点的具体坐标，"
        "应分别对相应 Point 状态执行参数代入。"
    ),
)
STRAIGHTENED_ENDPOINT_RESULT_FORM = ScalarResultFormSpec(
    possible_forms=("open_state", "closed_state"),
    description=(
        "端点坐标本身仍含未定参数时为 open_state；只有端点实际不存在自由"
        "符号时才是 closed_state。Macro 的 parameter_value 只求值标量最小值"
        "表达式，不改变这些 Point 返回。"
    ),
    ignored_symbol_input_args=("parameter_value",),
)
PATH_TRANSFORMATION_LOCUS_IDENTITY_CONSTRAINTS = (
    StateIdentityConstraintSpec(
        left="arg:moving_locus.object_role:subject",
        right="arg:path_transformation.object_role:moving_object",
        description=(
            "显式轨迹所属动点必须与 PathTransformation 声明的 moving object 相同。"
        ),
        applicability="when_all_present",
    ),
)
TWO_MOVING_PATH_TRANSFORMATION_OBJECT_ROLES = (
    StateObjectRoleProjectionSpec(
        role="moving_object",
        source_arg="second_moving_membership",
        source_object_role="moving_object",
    ),
    StateObjectRoleProjectionSpec(
        role="fixed_endpoint_1",
        source_arg="first_segment_start",
        state_requirement="materialized",
    ),
    StateObjectRoleProjectionSpec(
        role="fixed_endpoint_2",
        source_arg="transformed_fixed_endpoint",
        state_requirement="materialized",
    ),
    StateObjectRoleProjectionSpec(
        role="moving_locus",
        source_arg="second_moving_membership",
        source_object_role="moving_locus",
    ),
    StateObjectRoleProjectionSpec(
        role="moving_locus_endpoint_1",
        source_arg="moving_locus_endpoint_1",
        state_requirement="materialized",
    ),
    StateObjectRoleProjectionSpec(
        role="moving_locus_endpoint_2",
        source_arg="moving_locus_endpoint_2",
        state_requirement="materialized",
    ),
)
STANDARD_BROKEN_PATH_CONSUMER = PathTransformationConsumerSpec(
    transformation_arg="path_transformation",
    required_roles=(
        "moving_object",
        "fixed_endpoint_1",
        "fixed_endpoint_2",
    ),
    profile="standard_broken_path",
)
LINKED_AUXILIARY_PATH_CONSUMER = PathTransformationConsumerSpec(
    transformation_arg="path_transformation",
    required_roles=(
        "moving_object",
        "fixed_endpoint_1",
        "auxiliary_object",
    ),
    profile="linked_auxiliary",
)
LINKED_AUXILIARY_IDENTITY_CONSTRAINTS = (
    StateIdentityConstraintSpec(
        left="arg:moving_point.object_ref",
        right="arg:path_transformation.object_role:moving_object",
    ),
    StateIdentityConstraintSpec(
        left="arg:curve_point.object_ref",
        right="arg:path_transformation.object_role:fixed_endpoint_1",
    ),
    StateIdentityConstraintSpec(
        left="arg:auxiliary_point.object_ref",
        right="arg:path_transformation.object_role:auxiliary_object",
    ),
    StateIdentityConstraintSpec(
        left="arg:auxiliary_locus.object_role:subject",
        right="arg:path_transformation.object_role:auxiliary_object",
    ),
)
PATH_MINIMUM_DISTANCE_LINEAGE_CLOSURES = (
    StateLineageClosureSpec(
        source_args=("p1", "p2"),
        required_semantic_roles=(
            "straightened_endpoint_1",
            "straightened_endpoint_2",
        ),
        required_evidence_tags=("path_minimum_witness",),
        require_same_source_call=True,
        add_semantic_roles=("path_minimum_expression",),
        add_evidence_tags=("path_minimum_expression",),
        description=(
            "两个端点必须分别来自同一次路径拉直 witness 的两个角色；"
            "满足后它们的距离才可作为路径最小值表达式。"
        ),
    ),
)

PATH_MINIMUM_INTERSECTION_LINEAGE_CLOSURES = (
    StateLineageClosureSpec(
        source_args=("line1_p1", "line1_p2", "line2_p1", "line2_p2"),
        input_groups=(
            EvidenceInputGroupSpec(
                source_args=("line1_p1", "line1_p2"),
                required_semantic_roles=(
                    "straightened_endpoint_1",
                    "straightened_endpoint_2",
                ),
                required_evidence_tags=("path_minimum_witness",),
                witness_role_aliases=(
                    ("straightened_endpoint_2", "fixed_endpoint_2"),
                ),
                require_same_witness=True,
            ),
            EvidenceInputGroupSpec(
                source_args=("line2_p1", "line2_p2"),
                required_witness_object_roles=(
                    "moving_locus_endpoint_1",
                    "moving_locus_endpoint_2",
                ),
                require_same_witness=True,
            ),
        ),
        output_object_role="moving_object",
        add_evidence_tags=("path_minimum_extremal_point",),
        description=(
            "极值点必须是同一次拉直 witness 的等价最短线段与其声明的"
            "动点轨迹的交点，且返回对象必须是该 witness 的 moving object。"
        ),
    ),
)

STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS = tuple(
    StateObjectRoleProjectionSpec(
        role=role,
        source_arg="path_transformation",
        source_object_role=role,
    )
    for role in (
        "moving_object",
        "fixed_endpoint_1",
        "fixed_endpoint_2",
        "moving_locus_endpoint_1",
        "moving_locus_endpoint_2",
    )
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
    write_mode: StateWriteMode | None = None,
    description: str = "",
    provides_semantic_roles: tuple[str, ...] = (),
    result_form: ScalarResultFormSpec | None = None,
    object_role_projections: tuple[StateObjectRoleProjectionSpec, ...] = (),
    lineage_closures: tuple[StateLineageClosureSpec, ...] = (),
    input_closure_policy: CapabilityStateClosurePolicy = "any",
    return_binding: FunctionalReturnBindingPolicy = "auto",
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
    description: str = "",
) -> ConditionPattern:
    return ConditionPattern(
        condition_kind=condition_kind,
        runtime_type=runtime_type,
        required=required,
        description=description,
    )


def _straightening_fixed_endpoint_reads() -> tuple[StateSlotPattern, ...]:
    return (
        _slot(
            "coordinate",
            "Point",
            object_kind="point",
            semantic_role="fixed_endpoint_1",
            required=True,
        ),
        _slot(
            "coordinate",
            "Point",
            object_kind="point",
            semantic_role="fixed_endpoint_2",
            required=True,
        ),
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
    path_transformation_consumer: PathTransformationConsumerSpec | None = None,
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
        path_transformation_consumer=path_transformation_consumer,
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
    path_transformation_consumer: PathTransformationConsumerSpec | None = None,
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
        path_transformation_consumer=path_transformation_consumer,
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
                    "本轮有意保留、供后续条件继续求解的独立参数。"
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
                    "的目标点，也不能只提供 PointRef；未知时直接省略。"
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
        "parameter_from_segment_length",
        slot_reads=(
            _slot("coordinate", "Point", object_kind="point"),
            _slot("coordinate", "Point", object_kind="point"),
        ),
        condition_reads=(_condition("length_squared"),),
        slot_writes=(_slot("value", "ParameterValue", object_kind="symbol"),),
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
                description="用于消去点坐标中自由符号的已求参数值。",
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
                lineage_closures=PATH_MINIMUM_DISTANCE_LINEAGE_CLOSURES,
            ),
            _slot(
                "expression",
                "MinimumExpression",
                output_key="evaluated_distance",
                required=False,
                lineage_closures=PATH_MINIMUM_DISTANCE_LINEAGE_CLOSURES,
            ),
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
        slot_writes=(
            _slot(
                "coordinate",
                "Point",
                object_kind="point",
                lineage_closures=PATH_MINIMUM_INTERSECTION_LINEAGE_CLOSURES,
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
    do_not_use_when=RIGHT_ANGLE_EQUAL_LENGTH_DO_NOT_USE_WHEN,
)

TWO_MOVING_POINTS_PATH_REDUCTION = StepRecipeSpec(
    recipe_id="two_moving_points_path_reduction",
    goal_type="reduce_path_expression",
    title="两动点路径降维：已有固定点替换",
    description=TWO_MOVING_POINTS_PATH_REDUCTION_DESCRIPTION,
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
                description=(
                    "包含降维后的动点、两个固定端点，以及由题面线段归属条件"
                    "提供的动点轨迹证据；后续路径拉直可据此省略 moving_locus。"
                ),
                provides_semantic_roles=("moving_locus",),
                object_role_projections=(
                    TWO_MOVING_PATH_TRANSFORMATION_OBJECT_ROLES
                ),
            ),
        ),
    ),
    priority="preferred",
    do_not_use_when=TWO_MOVING_POINTS_REDUCTION_DO_NOT_USE_WHEN,
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
                goal_evidence_tags=(
                    "path_minimum_witness",
                    "path_minimum_extremal_point",
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "select_straightening_candidate.auxiliary_point",
                "Point",
                "straightening_auxiliary_point",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
                equivalent_to="straightened_endpoint_1",
                description=(
                    "选中候选的反射辅助点，与 straightened_endpoint_1 是同一"
                    "几何状态；不能把二者作为一条直线的两个不同端点。"
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_1",
                "Point",
                "straightened_endpoint_1",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
                result_form=STRAIGHTENED_ENDPOINT_RESULT_FORM,
                description=(
                    "拉直后最短等价线段的第一个端点，通常是由反射构造得到的"
                    "辅助点；它不是原路径动点、极值点或答案点。"
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_2",
                "Point",
                "straightened_endpoint_2",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
                result_form=STRAIGHTENED_ENDPOINT_RESULT_FORM,
                description=(
                    "拉直后最短等价线段的第二个端点，通常是未被反射的另一"
                    "固定端点；它不是原路径动点、极值点或答案点。"
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
        ),
    ),
    priority="preferred",
    do_not_use_when=BROKEN_PATH_SELECT_DO_NOT_USE_WHEN,
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
        input_aliases=(
            ("endpoint_1", "distance_between_points.p1"),
            ("endpoint_2", "distance_between_points.p2"),
            ("parameter_value", "distance_between_points.parameter_value"),
        ),
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
    do_not_use_when=STRAIGHTENED_DISTANCE_DO_NOT_USE_WHEN,
)

BROKEN_PATH_STRAIGHTENING_MINIMUM_EXPRESSION = StepRecipeSpec(
    recipe_id="broken_path_straightening_minimum_expression",
    goal_type="derive_path_minimum_expression",
    title="折线拉直并求最小值表达式",
    description=(
        "对单动点两段折线路径，生成将军饮马拉直候选，选择最适合计算的方案，"
        "再计算对应两端点距离。端点仍含未定参数时输出开放表达式；端点全部确定时"
        "输出闭合值。本能力不猜测动点轨迹：PathTransformation 未携带轨迹依据时，"
        "必须显式提供同一动点的 Line 轨迹。"
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
        input_aliases=(
            (
                "parameter_value",
                "distance_between_points.parameter_value",
            ),
        ),
        output_aliases=(
            recipe_output_alias(
                "select_straightening_candidate.selected_candidate",
                "StraighteningCandidate",
                "straightened_scheme",
                required=False,
                cardinality="optional",
                goal_evidence_tags=(
                    "path_minimum_witness",
                    "path_minimum_extremal_point",
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "select_straightening_candidate.auxiliary_point",
                "Point",
                "straightening_auxiliary_point",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
                equivalent_to="straightened_endpoint_1",
                description=(
                    "选中候选的反射辅助点，与 straightened_endpoint_1 是同一"
                    "几何状态；该名称仅作为兼容别名。"
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_1",
                "Point",
                "straightened_endpoint_1",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
                result_form=STRAIGHTENED_ENDPOINT_RESULT_FORM,
                description=(
                    "拉直后最短等价线段的第一个端点，通常是由反射构造得到的"
                    "辅助点；它不是原路径动点、极值点或答案点。"
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "select_straightening_candidate.minimum_point_2",
                "Point",
                "straightened_endpoint_2",
                required=False,
                cardinality="optional",
                identity_policy="derived_role",
                goal_evidence_tags=("path_minimum_witness",),
                result_form=STRAIGHTENED_ENDPOINT_RESULT_FORM,
                description=(
                    "拉直后最短等价线段的第二个端点，通常是未被反射的另一"
                    "固定端点；它不是原路径动点、极值点或答案点。"
                ),
                object_role_projections=(
                    STRAIGHTENING_WITNESS_OBJECT_ROLE_PROJECTIONS
                ),
            ),
            recipe_output_alias(
                "distance_between_points.distance",
                "MinimumExpression",
                "path_minimum_expression",
                goal_evidence_tags=("path_minimum_expression",),
                description=(
                    "两个拉直端点之间的距离表达式，即原折线路径的最小值表达式；"
                    "含未定参数时供后续参数求解，不含自由参数时可直接绑定数值答案。"
                ),
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
    do_not_use_when=BROKEN_PATH_MINIMUM_EXPRESSION_DO_NOT_USE_WHEN,
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
    do_not_use_when=EQUAL_LENGTH_RAY_PATH_REDUCTION_DO_NOT_USE_WHEN,
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
                dependency_policy="context_closure",
                context_resolvers=(PATH_REDUCTION_ROLES_RESOLVER,),
                context_role_bindings=(
                    CapabilityContextRoleBindingSpec(
                        PATH_REDUCTION_ROLES_RESOLVER,
                        "transformed_fixed_endpoint",
                        "transformed_fixed_endpoint",
                    ),
                    CapabilityContextRoleBindingSpec(
                        PATH_REDUCTION_ROLES_RESOLVER,
                        "moving_locus_endpoint_1",
                        "moving_locus_endpoint_1",
                    ),
                    CapabilityContextRoleBindingSpec(
                        PATH_REDUCTION_ROLES_RESOLVER,
                        "moving_locus_endpoint_2",
                        "moving_locus_endpoint_2",
                    ),
                ),
            ),
            _recipe_contract(
                "broken_path_straightening_and_select",
                slot_reads=(
                    _slot(
                        "transformation",
                        "PathTransformation",
                        semantic_role="path_transformation",
                        description=(
                            "前序调用已证明的路径等价变换，例如把双动点路径"
                            "降为单动点折线路径。"
                        ),
                        provides_semantic_roles=("moving_locus",),
                    ),
                    _slot(
                        "locus",
                        "Line",
                        object_kind="line",
                        semantic_role="moving_locus",
                        required=False,
                        cardinality="optional",
                        description=(
                            "动点所在的已求出 Line 轨迹。仅当 path_transformation 的"
                            "结构化 provenance 已包含同一动点的轨迹时才可省略；不能从"
                            "可见的任意 Line 自动选择。"
                        ),
                    ),
                ),
                slot_writes=(
                    _slot("candidate", "StraighteningCandidate"),
                    _slot("coordinate", "Point", object_kind="point", required=False),
                ),
                input_closure_requirements=(
                    CapabilityInputClosureRequirement(
                        semantic_role="moving_locus",
                        provider_arg_roles=("path_transformation",),
                        description=(
                            "路径变换必须包含对应运动轨迹，或显式提供该轨迹。"
                        ),
                    ),
                ),
                identity_constraints=(
                    PATH_TRANSFORMATION_LOCUS_IDENTITY_CONSTRAINTS
                ),
                path_transformation_consumer=STANDARD_BROKEN_PATH_CONSUMER,
                exposes_to_llm=False,
            ),
            _recipe_contract(
                "path_minimum_by_straightened_distance",
                slot_reads=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="endpoint_1",
                        required=True,
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="endpoint_2",
                        required=True,
                    ),
                    _slot(
                        "value",
                        "ParameterValue",
                        object_kind="symbol",
                        semantic_role="parameter_value",
                        required=False,
                        cardinality="optional",
                        description=(
                            "若端点距离仍含参数，可提供该参数的已知值；其 Symbol "
                            "身份由状态账本确定，不需要另行填写参数名。"
                        ),
                    ),
                ),
                slot_writes=(_slot("expression", "MinimumExpression"),),
            ),
            _recipe_contract(
                "broken_path_straightening_minimum_expression",
                slot_reads=(
                    _slot(
                        "transformation",
                        "PathTransformation",
                        semantic_role="path_transformation",
                        description=(
                            "前序调用已证明的路径等价变换，例如把双动点路径"
                            "降为单动点折线路径。"
                        ),
                        provides_semantic_roles=("moving_locus",),
                    ),
                    _slot(
                        "locus",
                        "Line",
                        object_kind="line",
                        semantic_role="moving_locus",
                        required=False,
                        cardinality="optional",
                        description=(
                            "动点所在的已求出 Line 轨迹。仅当 path_transformation 的"
                            "结构化 provenance 已包含同一动点的轨迹时才可省略；不能从"
                            "可见的任意 Line 自动选择。"
                        ),
                    ),
                    _slot(
                        "value",
                        "ParameterValue",
                        object_kind="symbol",
                        semantic_role="parameter_value",
                        required=False,
                        cardinality="optional",
                        description=(
                            "若拉直端点仍含参数，可提供该参数的已知值，直接"
                            "得到 evaluated_path_minimum_expression。该参数只"
                            "求值标量表达式，不会把两个内部辅助端点改写为 "
                            "closed_state；下游若需要端点，可继续传递原端点并"
                            "同时提供参数值。"
                        ),
                    ),
                ),
                slot_writes=(
                    _slot("candidate", "StraighteningCandidate", required=False),
                    _slot("coordinate", "Point", object_kind="point", cardinality="many"),
                    _slot("expression", "MinimumExpression"),
                ),
                input_closure_requirements=(
                    CapabilityInputClosureRequirement(
                        semantic_role="moving_locus",
                        provider_arg_roles=("path_transformation",),
                        description=(
                            "路径变换必须包含对应运动轨迹，或显式提供该轨迹。"
                        ),
                    ),
                ),
                identity_constraints=(
                    PATH_TRANSFORMATION_LOCUS_IDENTITY_CONSTRAINTS
                ),
                path_transformation_consumer=STANDARD_BROKEN_PATH_CONSUMER,
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
        goal_evidence_policies=(
            GoalEvidencePolicySpec(
                goal_types=("derive_line_intersection_point",),
                value_types=("Point",),
                required_evidence_tags=(
                    "path_minimum_extremal_point",
                ),
                mechanism_pack_id="broken_path_minimum_core",
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
                slot_reads=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="fixed_point",
                        description=(
                            "原路径中不带权线段的固定端点，必须已有坐标并与 "
                            "moving_point 同在 x 轴上。"
                        ),
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="moving_point",
                        description=(
                            "加权线段和普通线段共享的 x 轴动点，必须已有含动点"
                            "参数的坐标状态。"
                        ),
                    ),
                ),
                condition_reads=(
                    _condition(
                        "minimum_value",
                        description=(
                            "必须引用 type=minimum_value、同时携带原加权路径文本"
                            "的题面已知最小值条件。不要引用只有求最值目标语义的 "
                            "path_minimum_target；本能力只读取其中的路径结构，"
                            "数值最小值不由本能力计算，也不会在这里消费该答案。"
                        ),
                    ),
                ),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        output_key="auxiliary_point",
                        description=(
                            "直角三角形构造产生的内部辅助点；供后续路径最值能力"
                            "消费，不是原动点、极值点或 Point 答案。"
                        ),
                    ),
                    _slot(
                        "transformation",
                        "PathTransformation",
                        output_key="path_transformation",
                        description=(
                            "原加权路径到普通折线路径的结构化等价变换；它不是"
                            "最小值表达式或最终数值。"
                        ),
                        object_role_projections=(
                            StateObjectRoleProjectionSpec(
                                role="moving_object",
                                source_arg="moving_point",
                                state_requirement="materialized",
                            ),
                            StateObjectRoleProjectionSpec(
                                role="fixed_endpoint_1",
                                source_arg="linked_fixed_endpoint_ref",
                                state_requirement="materialized",
                            ),
                            StateObjectRoleProjectionSpec(
                                role="auxiliary_object",
                                source_return="auxiliary_point",
                                state_requirement="materialized",
                            ),
                        ),
                    ),
                    _slot(
                        "locus",
                        "Line",
                        object_kind="line",
                        output_key="auxiliary_locus",
                        description=(
                            "辅助点随轴上动点运动形成的射线/直线轨迹，供后续 "
                            "linked-path 最值能力使用。"
                        ),
                        object_role_projections=(
                            StateObjectRoleProjectionSpec(
                                role="subject",
                                source_return="auxiliary_point",
                                state_requirement="materialized",
                            ),
                        ),
                    ),
                ),
                dependency_policy="context_closure",
                context_resolvers=(
                    WEIGHTED_PATH_TRANSFORMATION_ROLES_RESOLVER,
                ),
                context_role_bindings=(
                    CapabilityContextRoleBindingSpec(
                        WEIGHTED_PATH_TRANSFORMATION_ROLES_RESOLVER,
                        "linked_fixed_endpoint",
                        "linked_fixed_endpoint_ref",
                    ),
                ),
            ),
            _method_contract(
                "linked_broken_path_minimum_expression",
                slot_reads=(
                    _slot("transformation", "PathTransformation"),
                    _slot("locus", "Line", object_kind="line"),
                ),
                condition_reads=(
                    _condition(
                        "dynamic_constraint",
                        runtime_type="Constraint",
                        description=(
                            "动点参数的取值范围条件，例如参数大于、"
                            "小于或属于某区间；不是点坐标或点在曲线上的关系。"
                        ),
                    ),
                ),
                slot_writes=(_slot("expression", "MinimumExpression"),),
                identity_constraints=LINKED_AUXILIARY_IDENTITY_CONSTRAINTS,
                path_transformation_consumer=LINKED_AUXILIARY_PATH_CONSUMER,
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
                condition_reads=(
                    _condition("path_minimum_target"),
                    _condition("equal_length_condition"),
                    _condition("point_on_segment"),
                    _condition("point_on_ray"),
                ),
                slot_writes=(_slot("expression", "MinimumExpression"),),
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
                    _condition("midpoint_definition"),
                    _condition("square_center"),
                ),
                slot_writes=(
                    _slot(
                        "transformation",
                        "PathTransformation",
                        description=(
                            "包含降维后的动点和固定端点，但不包含动点轨迹证据；"
                            "后续路径拉直必须显式提供属于同一动点的 Line。"
                        ),
                        object_role_projections=(
                            StateObjectRoleProjectionSpec(
                                role="moving_object",
                                source_arg="square_condition",
                                source_object_role="vertex_4",
                            ),
                            StateObjectRoleProjectionSpec(
                                role="fixed_endpoint_1",
                                source_arg="fixed_endpoint_1_ref",
                                state_requirement="materialized",
                            ),
                            StateObjectRoleProjectionSpec(
                                role="fixed_endpoint_2",
                                source_arg="fixed_endpoint_2_ref",
                                state_requirement="materialized",
                            ),
                        ),
                    ),
                ),
                dependency_policy="context_closure",
                context_resolvers=(
                    SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER,
                ),
                context_role_bindings=(
                    CapabilityContextRoleBindingSpec(
                        SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER,
                        "fixed_endpoint_1",
                        "fixed_endpoint_1_ref",
                    ),
                    CapabilityContextRoleBindingSpec(
                        SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER,
                        "fixed_endpoint_2",
                        "fixed_endpoint_2_ref",
                    ),
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
                        description=(
                            "对称轴上的同一目标 Point 状态。除对称轴横坐标外，"
                            "另一坐标使用该 Point 专属的新参数表示；它默认不等于"
                            "抛物线系数或其他可见参数。"
                        ),
                    ),
                    _slot(
                        "parameter",
                        "Symbol",
                        object_kind="symbol",
                        semantic_role="axis_parameter",
                        output_key="parameter",
                        write_mode="value",
                        description=(
                            "代码为目标 Point 创建的专属坐标参数。该 Symbol 的身份"
                            "绑定到这个 Point；只有同身份 ParameterValue 才能代入，"
                            "不能用抛物线系数或其他参数值替代。"
                        ),
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
                        description=(
                            "正方形已知边的第一个端点，必须引用已经求出坐标的 Point 状态。"
                        ),
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="side_end",
                        description=(
                            "正方形已知边的第二个端点，必须引用已经求出坐标的 Point 状态；"
                            "不能只填写尚未计算坐标的对象引用。"
                        ),
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
                        description=(
                            "必须绑定本次实际求出的正方形顶点。若有序顶点为 "
                            "V1,V2,V3,V4，先由边 V1V2 求 V3、再由边 V2V3 "
                            "求 V4 时，两次返回应分别绑定 V3、V4；不要把中间"
                            "顶点和最终顶点绑定成同一对象。"
                        ),
                    ),
                ),
            ),
            _method_contract(
                "point_candidates_from_curve_point_condition",
                slot_reads=(
                    _parabola_read(semantic_role="parabola"),
                ),
                condition_reads=(_condition("point_on_curve"),),
                slot_writes=(_slot("candidate", "PointList", object_kind="point"),),
            ),
            _method_contract(
                "parameterized_point_locus_line",
                slot_reads=(_slot("coordinate", "Point", object_kind="point"),),
                slot_writes=(
                    _slot(
                        "locus",
                        "Line",
                        object_kind="line",
                        object_role_projections=(
                            StateObjectRoleProjectionSpec(
                                role="subject",
                                source_arg="point",
                            ),
                        ),
                    ),
                ),
            ),
            _method_contract(
                "line_locus_minimum_point",
                slot_reads=(
                    _slot(
                        "locus",
                        "Line",
                        object_kind="line",
                        semantic_role="moving_locus",
                        description=(
                            "当前路径动点已经求出的 Line 轨迹；不能用 Point、坐标轴上的点"
                            "或属于另一个对象的轨迹代替。"
                        ),
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="minimum_point_1",
                        description=(
                            "前序拉直能力产生的第一个内部端点，必须使用其已计算坐标状态。"
                        ),
                    ),
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        semantic_role="minimum_point_2",
                        description=(
                            "前序拉直能力产生的第二个内部端点，必须使用其已计算坐标状态。"
                        ),
                    ),
                    _slot(
                        "value",
                        "ParameterValue",
                        object_kind="symbol",
                        semantic_role="parameter_value",
                        required=False,
                        description="计算轨迹或端点时需要代入的单个已求参数值。",
                    ),
                ),
                slot_writes=(
                    _slot(
                        "coordinate",
                        "Point",
                        object_kind="point",
                        write_mode="transition",
                        description=(
                            "当前路径动点在最短状态下的坐标。若最终答案是与它相关的"
                            "另一个几何点，还需按题设关系继续恢复，不能直接改名绑定。"
                        ),
                    ),
                ),
                identity_constraints=(
                    StateIdentityConstraintSpec(
                        left="arg:moving_locus.object_role:subject",
                        right=(
                            "arg:minimum_point_1.object_role:moving_object"
                        ),
                        description=(
                            "动点轨迹、拉直端点所依据的路径动点必须是同一对象。"
                        ),
                    ),
                    StateIdentityConstraintSpec(
                        left="arg:moving_locus.object_role:subject",
                        right=(
                            "arg:minimum_point_2.object_role:moving_object"
                        ),
                    ),
                    StateIdentityConstraintSpec(
                        left="arg:moving_locus.object_role:subject",
                        right="return:point.object_ref",
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
