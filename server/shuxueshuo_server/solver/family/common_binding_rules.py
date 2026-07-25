"""Shared declarative binding rules used by multiple solver families."""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    MethodAggregateInputBindingSpec,
    MethodBindingRuleSpec,
    MethodCompanionOutputSpec,
    MethodInputBindingSpec,
    MethodPrepInvocationSpec,
)


QUADRATIC_STATE_PREP_INVOCATIONS = (
    MethodPrepInvocationSpec(
        trigger_selector=(
            "missing_readable_type_with_quadratic_source:Parabola"
        ),
        method_id="quadratic_from_constraints",
        output_aliases=(
            ("coefficients", "__local_only__"),
            ("parabola", "__local_only__"),
        ),
        local_output_aliases=(
            ("type:Coefficients", "coefficients"),
            ("type:Parabola", "parabola"),
        ),
        expansion_selectors=(
            "known_coefficients_if_read",
            "free_quadratic_parameter_if_read",
        ),
    ),
)


def quadratic_from_constraints_rule() -> MethodBindingRuleSpec:
    """Bind common quadratic constraints into a reusable parabola state."""
    return MethodBindingRuleSpec(
        method_id="quadratic_from_constraints",
        input_bindings=(
            MethodInputBindingSpec("quadratic", "function:parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("all_coefficients", "quadratic_coefficients"),
        ),
        aggregate_input_bindings=(
            MethodAggregateInputBindingSpec("curve_points", ("p1", "p2")),
        ),
        expansion_selectors=(
            "known_coefficients_if_read",
            "free_quadratic_parameter_if_read",
            "curve_point_if_read",
            "parameter_value_if_read",
        ),
        always_emit_outputs=("coefficients",),
        companion_outputs=(
            MethodCompanionOutputSpec(
                "coefficients",
                "answer_scope_output:coefficients",
                "runtime_step_output:coefficients",
            ),
        ),
        constraint_analyzer="quadratic_coefficients",
    )


def quadratic_vertex_point_rule() -> MethodBindingRuleSpec:
    """Bind a solved parabola to its vertex point."""
    return MethodBindingRuleSpec(
        method_id="quadratic_vertex_point",
        input_bindings=(
            MethodInputBindingSpec("parabola", "read_type:Parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("target", "point_output_ref"),
        ),
        prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
    )


def quadratic_x_axis_intercept_point_rule() -> MethodBindingRuleSpec:
    """Bind a solved parabola to an x-axis intercept point."""
    return MethodBindingRuleSpec(
        method_id="quadratic_x_axis_intercept_point",
        input_bindings=(
            MethodInputBindingSpec("quadratic", "read_type:Parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("target", "point_output_ref"),
            MethodInputBindingSpec("known_point", "x_axis_known_point", required=False),
        ),
        prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
    )


def quadratic_y_axis_intercept_point_rule() -> MethodBindingRuleSpec:
    """Bind a solved parabola to its y-axis intercept point."""
    return MethodBindingRuleSpec(
        method_id="quadratic_y_axis_intercept_point",
        input_bindings=(
            MethodInputBindingSpec("quadratic", "function:parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("target", "point_output_ref"),
        ),
    )


def point_on_parabola_at_x_rule() -> MethodBindingRuleSpec:
    """Bind a closed or single-free parabola to a point at a known x value."""
    return MethodBindingRuleSpec(
        method_id="point_on_parabola_at_x",
        input_bindings=(
            MethodInputBindingSpec("parabola", "read_type:Parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("target", "point_output_ref"),
        ),
        prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
    )


def line_parabola_second_intersection_point_rule() -> MethodBindingRuleSpec:
    """Bind a line and known curve point to the second parabola intersection."""
    return MethodBindingRuleSpec(
        method_id="line_parabola_second_intersection_point",
        input_bindings=(
            MethodInputBindingSpec("parabola", "read_type:Parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("line_p1", "line_parabola:line_p1"),
            MethodInputBindingSpec("line_p2", "line_parabola:line_p2"),
            MethodInputBindingSpec("known_point", "line_parabola:known_point"),
            MethodInputBindingSpec("target", "line_parabola:target"),
        ),
        prep_invocations=QUADRATIC_STATE_PREP_INVOCATIONS,
    )


def distance_between_points_rule() -> MethodBindingRuleSpec:
    """Bind two point-like reads to a distance expression."""
    return MethodBindingRuleSpec(
        method_id="distance_between_points",
        input_bindings=(
            MethodInputBindingSpec("p1", "distance:p1"),
            MethodInputBindingSpec("p2", "distance:p2"),
        ),
        expansion_selectors=("distance_parameter_value_if_read",),
    )


def midpoint_point_rule() -> MethodBindingRuleSpec:
    """Bind a midpoint definition to the midpoint point output."""
    return MethodBindingRuleSpec(
        method_id="midpoint_point",
        input_bindings=(
            MethodInputBindingSpec("p1", "midpoint:p1"),
            MethodInputBindingSpec("p2", "midpoint:p2"),
            MethodInputBindingSpec("target", "midpoint:target"),
        ),
    )


def translated_point_rule() -> MethodBindingRuleSpec:
    """Bind a translation source and target point reference."""
    return MethodBindingRuleSpec(
        method_id="translated_point",
        input_bindings=(
            MethodInputBindingSpec("source", "translated_point:source"),
            MethodInputBindingSpec("target", "translated_point:target"),
        ),
    )


def line_intersection_point_rule() -> MethodBindingRuleSpec:
    """Bind two lines to their intersection point."""
    return MethodBindingRuleSpec(
        method_id="line_intersection_point",
        input_bindings=(
            MethodInputBindingSpec("line1_p1", "intersection:line1_p1"),
            MethodInputBindingSpec("line1_p2", "intersection:line1_p2"),
            MethodInputBindingSpec("line2_p1", "intersection:line2_p1"),
            MethodInputBindingSpec("line2_p2", "intersection:line2_p2"),
            MethodInputBindingSpec("target", "intersection:target"),
        ),
        expansion_selectors=("intersection_parameter_value_if_read",),
    )


def parameter_from_curve_point_on_quadratic_rule() -> MethodBindingRuleSpec:
    """Bind a curve point on the current quadratic to solve the parameter."""
    return MethodBindingRuleSpec(
        method_id="parameter_from_curve_point_on_quadratic",
        input_bindings=(
            MethodInputBindingSpec("quadratic", "read_type:Parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("point", "read_type:Point"),
            MethodInputBindingSpec("parameter", "parameter_symbol_from_reads"),
            MethodInputBindingSpec("quadratic_template", "quadratic_template"),
            MethodInputBindingSpec(
                "parameter_constraint",
                "parameter_constraint",
                required=False,
            ),
            MethodInputBindingSpec(
                "known_parameter",
                "known_parameter_symbol_from_reads",
                required=False,
            ),
            MethodInputBindingSpec(
                "known_parameter_value",
                "known_parameter_value_from_reads",
                required=False,
            ),
        ),
    )


def evaluate_expression_at_parameter_rule() -> MethodBindingRuleSpec:
    """Bind a substitutable symbolic state and a resolved parameter value."""
    return MethodBindingRuleSpec(
        method_id="evaluate_expression_at_parameter",
        input_bindings=(
            MethodInputBindingSpec(
                "expression",
                "read_type:Expression|MinimumExpression|Parabola",
            ),
            MethodInputBindingSpec("parameter", "parameter_symbol"),
        ),
        expansion_selectors=("parameter_value_if_read",),
    )


def evaluate_point_at_parameter_rule() -> MethodBindingRuleSpec:
    """Bind a point expression and a resolved parameter value."""
    return MethodBindingRuleSpec(
        method_id="evaluate_point_at_parameter",
        input_bindings=(
            MethodInputBindingSpec("point", "read_type:Point"),
        ),
        expansion_selectors=("parameter_value_if_read",),
    )


def parameter_from_expression_value_rule() -> MethodBindingRuleSpec:
    """Bind a minimum expression and its target value condition."""
    return MethodBindingRuleSpec(
        method_id="parameter_from_expression_value",
        input_bindings=(
            MethodInputBindingSpec("expression", "read_type:MinimumExpression"),
            MethodInputBindingSpec("condition", "fact:minimum_value:Condition"),
            MethodInputBindingSpec("parameter", "parameter_symbol_from_reads_or_expression"),
            MethodInputBindingSpec("constraint", "parameter_constraint", required=False),
        ),
    )
