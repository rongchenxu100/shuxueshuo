from __future__ import annotations

from dataclasses import replace

import sympy as sp

from shuxueshuo_server.solver.contracts import SymbolicClosureSpec
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    execute_symbolic_closure,
)


def _base_spec() -> SymbolicClosureSpec:
    return SymbolicClosureSpec(
        target_arg="target_parameter",
        equation_builder="quadratic_constraints",
        known_substitutions=(("parameter", "parameter_value"),),
        known_mapping_args=("known_coefficients",),
        representation_mapper="polynomial_coefficient_template",
        preserved_symbol_args=("free_parameter", "free_parameters"),
        output_validator="quadratic_closure_outputs",
    )


def test_generated_production_quadratic_symbolic_closure_gate() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (
        symbols[name] for name in ("x", "a", "b", "c")
    )
    identities = {
        symbol: MathObjectId(symbol.name, "symbol", "problem")
        for symbol in symbols.values()
    }
    scenarios = (
        "direct",
        "mapped",
        "mapped_open",
        "known_coefficient",
        "known_parameter",
        "ambiguous",
        "inconsistent",
        "underdetermined",
        "filter_accept",
        "filter_reject",
    )

    for scenario_index in range(2048):
        scenario = scenarios[scenario_index % len(scenarios)]
        offset = sp.Integer(scenario_index % 11 + 1)
        spec = _base_spec()
        args = {
            "quadratic": a * x**2 + b,
            "quadratic_template": a * x**2 + b,
            "x": x,
            "all_coefficients": [a, b],
            "known_coefficients": {a: 1},
            "target_parameter": b,
        }
        expected = "unique"

        if scenario == "direct":
            args["curve_point"] = (1, offset)
        elif scenario == "mapped":
            args.update(
                {
                    "quadratic": a * x**2 + (1 - c) * x + c,
                    "quadratic_template": a * x**2 + b * x + c,
                    "all_coefficients": [a, b, c],
                    "extra_equation": sp.Eq(c, offset),
                }
            )
        elif scenario == "mapped_open":
            args.update(
                {
                    "quadratic": a * x**2 + (1 - c) * x + c,
                    "quadratic_template": a * x**2 + b * x + c,
                    "all_coefficients": [a, b, c],
                    "free_parameter": c,
                }
            )
        elif scenario == "known_coefficient":
            args["known_coefficients"][b] = offset
        elif scenario == "known_parameter":
            args["parameter"] = b
            args["parameter_value"] = offset
        elif scenario == "ambiguous":
            args["extra_equation"] = sp.Eq(b**2, 1)
            expected = "ambiguous"
        elif scenario == "inconsistent":
            args["extra_equation"] = sp.S.false
            expected = "inconsistent"
        elif scenario == "underdetermined":
            expected = "identity_unresolved"
        else:
            candidate = offset if scenario == "filter_accept" else -offset
            args["extra_equation"] = sp.Eq(b, candidate)
            args["value_constraint"] = {
                "operator": ">",
                "value": sp.Integer(0),
            }
            spec = replace(
                spec,
                constraint_filter="parameter_value_constraint",
                constraint_args=("value_constraint",),
            )
            if scenario == "filter_reject":
                expected = "underdetermined"

        result = execute_symbolic_closure(
            spec,
            args=args,
            target_object_id=identities[b],
            runtime_symbol_bindings=identities,
            kernel=kernel,
        )

        assert result.status == expected, (
            scenario_index,
            scenario,
            result,
        )
        assert result.target_object_id == identities[b]
        assert result.validation_context_attached
        if expected == "unique":
            assert result.target_value is not None
            assert b in result.substitution
        if scenario == "mapped_open":
            assert sp.simplify(result.target_value - (1 - c)) == 0
            assert result.residual_symbols == (c,)
