"""Shared declarative binding rules used by multiple solver families."""

from __future__ import annotations

from shuxueshuo_server.solver.family.models import (
    MethodBindingRuleSpec,
    MethodInputBindingSpec,
)


def parameter_from_curve_point_on_quadratic_rule() -> MethodBindingRuleSpec:
    """Bind a curve point on the current quadratic to solve the parameter."""
    return MethodBindingRuleSpec(
        method_id="parameter_from_curve_point_on_quadratic",
        input_bindings=(
            MethodInputBindingSpec("quadratic", "read_type:Parabola"),
            MethodInputBindingSpec("x", "symbol:x"),
            MethodInputBindingSpec("point", "read_type:Point"),
            MethodInputBindingSpec("parameter", "parameter_symbol"),
            MethodInputBindingSpec("parameter_constraint", "parameter_constraint", required=False),
        ),
    )


def evaluate_expression_at_parameter_rule() -> MethodBindingRuleSpec:
    """Bind an expression/minimum expression and a resolved parameter value."""
    return MethodBindingRuleSpec(
        method_id="evaluate_expression_at_parameter",
        input_bindings=(
            MethodInputBindingSpec("expression", "read_type:Expression|MinimumExpression"),
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
            MethodInputBindingSpec("parameter", "parameter_symbol"),
            MethodInputBindingSpec("constraint", "parameter_constraint", required=False),
        ),
    )
