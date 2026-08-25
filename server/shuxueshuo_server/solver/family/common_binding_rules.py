"""Shared declarative binding rules used by multiple solver families."""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    CoefficientExtractionDerivationSpec,
    ConditionSourceSpec,
    EntityIdentitySourceSpec,
    ExactCallResultSourceSpec,
    ExactParameterSubstitutionSourceSpec,
    FreeSymbolBasisDerivationSpec,
    LatestStateSourceSpec,
    MacroPreparedRoleSourceSpec,
    MethodInputBindingSpec,
    PreviousOutputIdentityDerivationSpec,
    ProducerLinkedSourceSpec,
    PublicArgSourceSpec,
    SourceObjectIdentityDerivationSpec,
)
from shuxueshuo_server.solver.family.models import (
    FunctionalOutputTargetSelectorSpec,
    MethodAggregateInputBindingSpec,
    MethodBindingRuleSpec,
    MethodPrepInvocationSpec,
    MethodScalarAggregateLoweringSpec,
)


def quadratic_state_prep_invocations(
    source_input: str,
) -> tuple[MethodPrepInvocationSpec, ...]:
    return (
        MethodPrepInvocationSpec(
            method_id="quadratic_from_constraints",
            source_input=source_input,
            produced_runtime_type="Parabola",
            output_aliases=(
                ("coefficients", "__local_only__"),
                ("parabola", "__local_only__"),
            ),
            local_output_aliases=(
                ("type:Coefficients", "coefficients"),
                ("type:Parabola", "parabola"),
            ),
        ),
    )


def quadratic_latest_state_binding(
    input_name: str,
    *,
    entity_arg: str | None = None,
) -> MethodInputBindingSpec:
    return latest_state_binding(
        input_name,
        entity_arg=entity_arg or "parabola",
    )


def latest_state_binding(
    input_name: str,
    *,
    entity_arg: str | None = None,
    required: bool = True,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=LatestStateSourceSpec(entity_arg or input_name),
    )


def quadratic_public_state_binding(
    input_name: str,
    *,
    public_arg: str | None = None,
) -> MethodInputBindingSpec:
    return public_arg_binding(input_name, public_arg=public_arg)


def public_arg_binding(
    input_name: str,
    *,
    public_arg: str | None = None,
    required: bool = True,
) -> MethodInputBindingSpec:
    """Bind an explicitly authored Entity/value without selecting by type."""
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=PublicArgSourceSpec(public_arg or input_name),
    )


def exact_call_result_binding(
    input_name: str,
    *,
    public_arg: str | None = None,
    required: bool = True,
    semantic_roles: tuple[str, ...] = (),
) -> MethodInputBindingSpec:
    """Bind an anonymous intermediate to its exact producer return."""
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=ExactCallResultSourceSpec(
            public_arg or input_name,
            semantic_roles,
        ),
    )


def exact_parameter_substitution_binding(
    input_name: str,
    *,
    source_inputs: tuple[str, ...],
    target_input: str,
    required: bool = False,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=ExactParameterSubstitutionSourceSpec(
            source_inputs=source_inputs,
            target_input=target_input,
        ),
    )


def previous_output_identity_binding(
    input_name: str,
    *,
    output_name: str,
    required: bool = True,
) -> MethodInputBindingSpec:
    """Bind an identity input to this call's canonical return allocation."""
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        derivation=PreviousOutputIdentityDerivationSpec(output_name),
    )


def macro_prepared_role_binding(
    input_name: str,
    *,
    role: str | None = None,
    required: bool = True,
) -> MethodInputBindingSpec:
    """Bind one internal Method input to a verified Macro winner role."""
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=MacroPreparedRoleSourceSpec(role or input_name),
    )


def condition_arg_binding(
    input_name: str,
    *,
    public_arg: str | None = None,
    required: bool = True,
) -> MethodInputBindingSpec:
    """Bind one exact Fact/Condition selected by the public call contract."""
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=ConditionSourceSpec(arg_name=public_arg or input_name),
    )


def related_condition_binding(
    input_name: str,
    *,
    condition_kinds: tuple[str, ...],
    related_args: tuple[str, ...],
    required: bool = True,
) -> MethodInputBindingSpec:
    """Resolve one lexical Condition by canonical related-object identity."""
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=ConditionSourceSpec(
            condition_kinds=condition_kinds,
            related_args=related_args,
        ),
    )


def entity_identity_binding(
    input_name: str,
    *,
    source_arg: str | None = None,
    required: bool = True,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=EntityIdentitySourceSpec(arg_name=source_arg or input_name),
    )


def canonical_x_binding(input_name: str = "x") -> MethodInputBindingSpec:
    return canonical_symbol_binding(input_name, symbol_name="x")


def canonical_symbol_binding(
    input_name: str,
    *,
    symbol_name: str,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        derivation=CanonicalSymbolDerivationSpec(symbol_name),
    )


def quadratic_coefficients_binding(
    *,
    input_name: str = "all_coefficients",
    source_input: str = "quadratic",
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        derivation=CoefficientExtractionDerivationSpec(source_input),
    )


def parameter_basis_binding(
    source_inputs: tuple[str, ...],
    *,
    input_name: str = "parameter",
    required: bool = True,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        derivation=FreeSymbolBasisDerivationSpec(source_inputs),
    )


def source_parameter_identity_binding(
    source_input: str,
    *,
    input_name: str,
    required: bool = False,
) -> MethodInputBindingSpec:
    return source_object_identity_binding(
        source_input,
        input_name=input_name,
        required=required,
    )


def source_object_identity_binding(
    source_input: str,
    *,
    input_name: str,
    required: bool = False,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        derivation=SourceObjectIdentityDerivationSpec(source_input),
    )


def producer_parameter_binding(
    source_input: str,
    *,
    input_name: str = "parameter",
    producer_input: str = "parameter",
) -> MethodInputBindingSpec:
    return producer_linked_binding(
        source_input,
        input_name=input_name,
        producer_input=producer_input,
    )


def producer_linked_binding(
    source_input: str,
    *,
    input_name: str,
    producer_input: str,
    required: bool = True,
) -> MethodInputBindingSpec:
    return MethodInputBindingSpec(
        input_name=input_name,
        required=required,
        source=ProducerLinkedSourceSpec(source_input, producer_input),
    )


def quadratic_from_constraints_rule() -> MethodBindingRuleSpec:
    """Bind common quadratic constraints into a reusable parabola state."""
    return MethodBindingRuleSpec(
        method_id="quadratic_from_constraints",
        input_bindings=(
            quadratic_latest_state_binding("quadratic"),
            canonical_x_binding(),
            quadratic_coefficients_binding(),
            public_arg_binding("parameter_value", required=False),
            source_parameter_identity_binding(
                "parameter_value",
                input_name="parameter",
                required=False,
            ),
        ),
        scalar_aggregate_lowerings=(
            MethodScalarAggregateLoweringSpec(
                source_input="known_coefficients",
                item_runtime_type="ParameterValue",
                identity_input="parameter",
                value_input="parameter_value",
            ),
        ),
        aggregate_input_bindings=(
            MethodAggregateInputBindingSpec(
                source_input="curve_points",
                item_inputs=(),
                singleton_input="curve_point",
            ),
            MethodAggregateInputBindingSpec(
                source_input="free_parameters",
                item_inputs=(),
                singleton_input="free_parameter",
            ),
        ),
        constraint_analyzer="quadratic_coefficients",
    )


def quadratic_vertex_point_rule() -> MethodBindingRuleSpec:
    """Bind a solved parabola to its vertex point."""
    return MethodBindingRuleSpec(
        method_id="quadratic_vertex_point",
        input_bindings=(
            quadratic_public_state_binding("parabola"),
            canonical_x_binding(),
            previous_output_identity_binding("target", output_name="point"),
        ),
        prep_invocations=quadratic_state_prep_invocations("parabola"),
    )


def quadratic_x_axis_intercept_point_rule() -> MethodBindingRuleSpec:
    """Bind a solved parabola to an x-axis intercept point."""
    return MethodBindingRuleSpec(
        method_id="quadratic_x_axis_intercept_point",
        functional_input_names=(("quadratic", "parabola"),),
        input_bindings=(
            quadratic_public_state_binding(
                "quadratic",
                public_arg="parabola",
            ),
            canonical_x_binding(),
            previous_output_identity_binding("target", output_name="point"),
            latest_state_binding(
                "target_state",
                entity_arg="target",
                required=False,
            ),
            public_arg_binding("known_point", required=False),
        ),
        prep_invocations=quadratic_state_prep_invocations("quadratic"),
    )


def quadratic_y_axis_intercept_point_rule() -> MethodBindingRuleSpec:
    """Bind a solved parabola to its y-axis intercept point."""
    return MethodBindingRuleSpec(
        method_id="quadratic_y_axis_intercept_point",
        input_bindings=(
            quadratic_latest_state_binding("quadratic"),
            canonical_x_binding(),
            previous_output_identity_binding("target", output_name="point"),
        ),
    )


def point_on_parabola_at_x_rule() -> MethodBindingRuleSpec:
    """Bind a closed or single-free parabola to a point at a known x value."""
    return MethodBindingRuleSpec(
        method_id="point_on_parabola_at_x",
        functional_output_target_selectors=(
            FunctionalOutputTargetSelectorSpec(
                output_name="point",
                selector_id="unique_visible_fact_target",
                fact_kind="point_construction",
                prompt_fact_kind="point_on_curve",
                target_field="point",
                related_arg="parabola",
                related_field="owner",
                required_field_values=(("construction", "curve_at_x"),),
                description=(
                    "若可见 point_on_curve 事实唯一声明了当前抛物线上、"
                    "具有结构化横坐标的 Point，则代码绑定该已有对象；"
                    "存在多个候选时必须显式 return_bindings。"
                ),
            ),
        ),
        input_bindings=(
            quadratic_public_state_binding("parabola"),
            canonical_x_binding(),
            previous_output_identity_binding("target", output_name="point"),
        ),
        prep_invocations=quadratic_state_prep_invocations("parabola"),
    )


def line_parabola_second_intersection_point_rule() -> MethodBindingRuleSpec:
    """Bind a line and known curve point to the second parabola intersection."""
    return MethodBindingRuleSpec(
        method_id="line_parabola_second_intersection_point",
        input_bindings=(
            quadratic_public_state_binding("parabola"),
            canonical_x_binding(),
            public_arg_binding("line_p1"),
            public_arg_binding("line_p2"),
            public_arg_binding("known_point"),
            previous_output_identity_binding("target", output_name="point"),
        ),
        prep_invocations=quadratic_state_prep_invocations("parabola"),
    )


def distance_between_points_rule() -> MethodBindingRuleSpec:
    """Bind two point-like reads to a distance expression."""
    return MethodBindingRuleSpec(
        method_id="distance_between_points",
        input_bindings=(
            public_arg_binding("p1"),
            public_arg_binding("p2"),
            source_object_identity_binding(
                "parameter_value",
                input_name="parameter",
                required=False,
            ),
        ),
    )


def midpoint_point_rule() -> MethodBindingRuleSpec:
    """Bind a midpoint definition to the midpoint point output."""
    return MethodBindingRuleSpec(
        method_id="midpoint_point",
        input_bindings=(
            entity_identity_binding("p1"),
            entity_identity_binding("p2"),
            previous_output_identity_binding("target", output_name="midpoint"),
        ),
    )


def translated_point_rule() -> MethodBindingRuleSpec:
    """Bind a translation source and target point reference."""
    return MethodBindingRuleSpec(
        method_id="translated_point",
        input_bindings=(
            public_arg_binding("source"),
            previous_output_identity_binding("target", output_name="point"),
        ),
    )


def line_intersection_point_rule() -> MethodBindingRuleSpec:
    """Bind two lines to their intersection point."""
    return MethodBindingRuleSpec(
        method_id="line_intersection_point",
        input_bindings=(
            public_arg_binding("line1_p1"),
            public_arg_binding("line1_p2"),
            public_arg_binding("line2_p1"),
            public_arg_binding("line2_p2"),
            previous_output_identity_binding(
                "target",
                output_name="intersection",
            ),
            source_object_identity_binding(
                "parameter_value",
                input_name="parameter",
                required=False,
            ),
        ),
    )


def construct_point_on_ray_at_reference_distance_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="construct_point_on_ray_at_reference_distance",
        input_bindings=(
            public_arg_binding("anchor"),
            public_arg_binding("ray_point"),
            public_arg_binding("reference_point"),
            previous_output_identity_binding("target", output_name="point"),
        ),
    )


def verify_point_on_ray_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="verify_point_on_ray",
        functional_output_names=(("verified", "point_on_ray"),),
        input_bindings=tuple(
            public_arg_binding(name)
            for name in ("point", "anchor", "ray_point")
        ),
    )


def verify_distance_equality_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="verify_distance_equality",
        functional_output_names=(("verified", "distance_equality"),),
        input_bindings=tuple(
            public_arg_binding(name)
            for name in (
                "first_start",
                "first_end",
                "second_start",
                "second_end",
            )
        ),
    )


def prove_distance_equality_from_conditions_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="prove_distance_equality_from_conditions",
        functional_output_names=(("verified", "distance_equality"),),
        input_bindings=(
            condition_arg_binding("equal_length_condition"),
            condition_arg_binding("linking_condition"),
            condition_arg_binding("ray_membership_condition"),
            condition_arg_binding("constructed_equal_length_condition"),
            condition_arg_binding("constructed_ray_condition"),
            *(public_arg_binding(name) for name in (
                "common_vertex",
                "first_start",
                "first_end",
                "second_start",
                "second_end",
            )),
        ),
    )


def rewrite_expression_by_condition_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="rewrite_expression_by_condition",
        input_bindings=(
            exact_call_result_binding("original_expression"),
            exact_call_result_binding("rewritten_expression"),
            condition_arg_binding("condition"),
        ),
    )


def certify_minimum_expression_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="certify_minimum_expression",
        input_bindings=(
            exact_call_result_binding("expression"),
            condition_arg_binding("attainment_condition"),
        ),
    )


def reflect_point_across_line_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="reflect_point_across_line",
        input_bindings=(
            public_arg_binding("point"),
            public_arg_binding("line_p1"),
            public_arg_binding("line_p2"),
            previous_output_identity_binding(
                "target",
                output_name="reflected_point",
            ),
        ),
    )


def verify_point_on_closed_segment_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="verify_point_on_closed_segment",
        functional_output_names=(("verified", "point_on_segment"),),
        input_bindings=(
            *(public_arg_binding(name) for name in (
                "point",
                "segment_start",
                "segment_end",
            )),
            condition_arg_binding("domain_condition", required=False),
        ),
    )


def distance_sum_expression_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="distance_sum_expression",
        input_bindings=tuple(
            public_arg_binding(name) for name in ("start", "via", "end")
        ),
    )


def verify_two_segment_path_attainment_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="verify_two_segment_path_attainment",
        functional_output_names=(("verified", "path_attainment"),),
        input_bindings=(
            exact_call_result_binding("objective"),
            exact_call_result_binding("candidate"),
            *(public_arg_binding(name) for name in (
                "candidate_point",
                "path_start",
                "path_end",
                "segment_start",
                "segment_end",
            )),
            condition_arg_binding("domain_condition", required=False),
        ),
    )


def prove_coupled_segment_endpoint_distance_equality_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="prove_coupled_segment_endpoint_distance_equality",
        functional_output_names=(("verified", "distance_equality"),),
        input_bindings=(
            condition_arg_binding("first_moving_membership"),
            condition_arg_binding("second_moving_membership"),
            condition_arg_binding("binding_relation"),
            public_arg_binding("first_moving_point"),
            public_arg_binding("second_moving_point"),
            public_arg_binding("first_track_fixed_endpoint"),
            source_object_identity_binding(
                "first_track_fixed_endpoint",
                input_name="first_track_fixed_endpoint_ref",
                required=True,
            ),
            public_arg_binding("joint_point"),
            source_object_identity_binding(
                "joint_point",
                input_name="joint_point_ref",
                required=True,
            ),
            public_arg_binding("second_track_fixed_endpoint"),
            source_object_identity_binding(
                "second_track_fixed_endpoint",
                input_name="second_track_fixed_endpoint_ref",
                required=True,
            ),
        ),
    )


def rewrite_path_target_by_distance_equality_rule() -> MethodBindingRuleSpec:
    return MethodBindingRuleSpec(
        method_id="rewrite_path_target_by_distance_equality",
        input_bindings=(
            condition_arg_binding("path_minimum_target"),
            condition_arg_binding("distance_equality"),
            public_arg_binding("replacement_start"),
            source_object_identity_binding(
                "replacement_start",
                input_name="replacement_start_ref",
                required=True,
            ),
            public_arg_binding("via"),
            source_object_identity_binding(
                "via",
                input_name="via_ref",
                required=True,
            ),
            public_arg_binding("end"),
            source_object_identity_binding(
                "end",
                input_name="end_ref",
                required=True,
            ),
        ),
    )


def parameter_from_curve_point_on_quadratic_rule() -> MethodBindingRuleSpec:
    """Bind a curve point on the current quadratic to solve the parameter."""
    return MethodBindingRuleSpec(
        method_id="parameter_from_curve_point_on_quadratic",
        input_bindings=(
            quadratic_public_state_binding("quadratic"),
            canonical_x_binding(),
            public_arg_binding("point"),
            parameter_basis_binding(
                (
                    "quadratic",
                    "point",
                    "parameter_constraint",
                    "known_parameter_value",
                )
            ),
            related_condition_binding(
                "parameter_constraint",
                condition_kinds=("symbol_constraint",),
                related_args=("parameter",),
                required=False,
            ),
            source_parameter_identity_binding(
                "known_parameter_value",
                input_name="known_parameter",
            ),
            exact_parameter_substitution_binding(
                "known_parameter_value",
                source_inputs=("quadratic", "point"),
                target_input="parameter",
            ),
        ),
    )


def evaluate_expression_at_parameter_rule() -> MethodBindingRuleSpec:
    """Bind a substitutable symbolic state and a resolved parameter value."""
    return MethodBindingRuleSpec(
        method_id="evaluate_expression_at_parameter",
        input_bindings=(
            exact_call_result_binding("expression"),
            parameter_basis_binding(("expression", "parameter_value")),
        ),
    )


def evaluate_point_at_parameter_rule() -> MethodBindingRuleSpec:
    """Bind a point expression and a resolved parameter value."""
    return MethodBindingRuleSpec(
        method_id="evaluate_point_at_parameter",
        input_bindings=(
            public_arg_binding("point"),
            source_object_identity_binding(
                "parameter_value",
                input_name="parameter",
                required=False,
            ),
        ),
    )


def parameter_from_expression_value_rule() -> MethodBindingRuleSpec:
    """Bind a minimum expression and its target value condition."""
    return MethodBindingRuleSpec(
        method_id="parameter_from_expression_value",
        input_bindings=(
            exact_call_result_binding("expression"),
            condition_arg_binding("condition", public_arg="minimum_value"),
            parameter_basis_binding(
                ("expression", "condition", "constraint")
            ),
            related_condition_binding(
                "constraint",
                condition_kinds=("symbol_constraint",),
                related_args=("parameter",),
                required=False,
            ),
        ),
    )
