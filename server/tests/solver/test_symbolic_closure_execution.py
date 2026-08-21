from __future__ import annotations

from dataclasses import replace

import sympy as sp
import pytest

from shuxueshuo_server.solver.contracts import SymbolicClosureSpec
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.models import TypedValue
from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
    QuadraticFromConstraintsMethod,
)
from shuxueshuo_server.solver.runtime.methods.parameter_from_curve_point_on_quadratic import (
    SPEC as CURVE_POINT_PARAMETER_SPEC,
)
from shuxueshuo_server.solver.runtime.methods.parameter_from_expression_value import (
    SPEC as EXPRESSION_PARAMETER_SPEC,
)
from shuxueshuo_server.solver.runtime.methods.parameter_from_minimum_value import (
    SPEC as MINIMUM_PARAMETER_SPEC,
)
from shuxueshuo_server.solver.runtime.methods.parameter_from_segment_length import (
    SPEC as SEGMENT_PARAMETER_SPEC,
)
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    SymbolicClosureConfigurationError,
    SymbolicClosureRuntimeDriftError,
    SymbolicClosureExecutionResult,
    execute_symbolic_closure,
    require_unique_symbolic_closure,
    solve_symbolic_closure_math,
    substitute_symbolic_closure_output,
    validate_symbolic_closure_spec,
)


def _symbol_id(name: str) -> MathObjectId:
    return MathObjectId(name, "symbol", "problem")


def _quadratic_spec() -> SymbolicClosureSpec:
    return SymbolicClosureSpec(
        target_arg="target_parameter",
        equation_builder="quadratic_constraints",
        representation_mapper="polynomial_coefficient_template",
        known_substitutions=(("parameter", "parameter_value"),),
        known_mapping_args=("known_coefficients",),
        preserved_symbol_args=("free_parameter", "free_parameters"),
        substitution_outputs=("coefficients", "parabola", "parameter_value"),
        output_validator="quadratic_closure_outputs",
    )


def test_symbolic_closure_solves_target_and_substitutes_all_outputs() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = (symbols[name] for name in ("x", "b", "c"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}

    result = execute_symbolic_closure(
        _quadratic_spec(),
        args={
            "quadratic": -x**2 + b * x + c,
            "quadratic_template": -x**2 + b * x + c,
            "x": x,
            "all_coefficients": [b, c],
            "curve_point": (-c, 0),
            "free_parameter": c,
            "target_parameter": b,
        },
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
        target_binding="target_parameter",
    )

    assert result.status == "unique"
    assert sp.simplify(result.target_value - (1 - c)) == 0
    assert result.target_object_id == ids[b]
    assert result.residual_symbol_ids == (ids[c],)
    assert result.provenance is not None
    assert result.provenance.preserved_symbol_ids == (ids[c],)

    parabola = substitute_symbolic_closure_output(
        TypedValue("Parabola", -x**2 + b * x + c),
        result,
    )
    assert sp.simplify(parabola.value - (-x**2 + (1 - c) * x + c)) == 0
    parameter = substitute_symbolic_closure_output(
        TypedValue("ParameterValue", 1 - c),
        result,
    )
    assert sp.simplify(parameter.value - (1 - c)) == 0


def test_quadratic_closure_uses_open_input_as_implicit_template() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = (symbols[name] for name in ("x", "b", "c"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args={
            "quadratic": -x**2 + b * x + c,
            "x": x,
            "all_coefficients": [b, c],
            "curve_point": (-c, 0),
            "free_parameter": c,
            "target_parameter": b,
        },
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    parabola = substitute_symbolic_closure_output(
        TypedValue("Parabola", -x**2 + (1 - c) * x + c),
        closure,
        return_name="parabola",
    )
    assert sp.expand(parabola.value) == sp.expand(-x**2 + (1 - c) * x + c)

    with pytest.raises(
        SymbolicClosureRuntimeDriftError,
        match="companion output does not match closure",
    ):
        substitute_symbolic_closure_output(
            TypedValue("Parabola", -x**2 + (2 - c) * x + c),
            closure,
            return_name="parabola",
        )


def test_materialized_open_target_matches_quadratic_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (
        symbols[name] for name in ("x", "a", "b", "c")
    )
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": a * x**2 + (1 - c) * x + c,
        "quadratic_template": a * x**2 + b * x + c,
        "x": x,
        "all_coefficients": [a, b, c],
        "known_coefficients": {a: 1},
        "free_parameter": c,
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )
    method = QuadraticFromConstraintsMethod().run(args, kernel)

    assert closure.status == "unique"
    assert closure.residual_symbols == (c,)
    assert sp.simplify(closure.target_value - (1 - c)) == 0
    assert sp.simplify(
        closure.target_value - method.outputs["parameter_value"].value
    ) == 0


def test_symbolic_closure_applies_known_substitution_before_solving() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}

    result = execute_symbolic_closure(
        _quadratic_spec(),
        args={
            "quadratic": a * x**2 + b,
            "quadratic_template": a * x**2 + b,
            "x": x,
            "all_coefficients": [a, b],
            "curve_point": (1, 5),
            "parameter": a,
            "parameter_value": 2,
            "target_parameter": b,
        },
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert result.status == "unique"
    assert result.target_value == 3
    assert result.substitution[a] == 2
    assert result.substitution[b] == 3


def test_symbolic_closure_reports_runtime_solve_shapes() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    base = {
        "quadratic": a * x**2 + b,
        "quadratic_template": a * x**2 + b,
        "x": x,
        "all_coefficients": [a, b],
        "target_parameter": a,
    }

    underdetermined = execute_symbolic_closure(
        _quadratic_spec(),
        args={**base, "curve_point": (0, b)},
        target_object_id=ids[a],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )
    ambiguous = execute_symbolic_closure(
        _quadratic_spec(),
        args={**base, "extra_equation": sp.Eq(a**2, 1)},
        target_object_id=ids[a],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )
    inconsistent = execute_symbolic_closure(
        _quadratic_spec(),
        args={**base, "extra_equation": sp.S.false},
        target_object_id=ids[a],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert underdetermined.status in {"identity_unresolved", "underdetermined"}
    assert ambiguous.status == "ambiguous"
    assert inconsistent.status == "inconsistent"


def test_symbolic_closure_optional_target_is_not_applicable() -> None:
    result = execute_symbolic_closure(
        _quadratic_spec(),
        args={},
        target_object_id=None,
        runtime_symbol_bindings={},
        kernel=SympyKernel(),
    )

    assert result.status == "not_applicable"


def test_symbolic_closure_spec_preflight_accepts_registered_contract() -> None:
    validate_symbolic_closure_spec(
        _quadratic_spec(),
        input_types={
            "quadratic": "Expression",
            "x": "Symbol",
            "all_coefficients": "SymbolList",
            "target_parameter": "Symbol",
                "parameter": "Symbol",
                "parameter_value": "ParameterValue",
                "known_coefficients": "Coefficients",
                "free_parameter": "Symbol",
            "free_parameters": "SymbolList",
        },
        output_types={
            "coefficients": "Coefficients",
            "parabola": "Parabola",
            "parameter_value": "ParameterValue",
        },
    )


@pytest.mark.parametrize(
    ("spec", "message"),
    (
        (
            SymbolicClosureSpec(
                target_arg="target_parameter",
                equation_builder="missing",
            ),
            "unknown equation builder",
        ),
        (
            SymbolicClosureSpec(
                target_arg="target_parameter",
                equation_builder="quadratic_constraints",
                constraint_args=("constraint",),
            ),
            "constraint_args require constraint_filter",
        ),
        (
            SymbolicClosureSpec(
                target_arg="target_parameter",
                equation_builder="quadratic_constraints",
                substitution_outputs=("unsupported",),
            ),
            "unknown output substitution adapter",
        ),
        (
            SymbolicClosureSpec(
                target_arg="target_parameter",
                equation_builder="quadratic_constraints",
                require_unique_target=False,
            ),
            "requires a unique target",
        ),
        (
            _quadratic_spec(),
            "quadratic_constraints requires x:Symbol",
        ),
    ),
)
def test_symbolic_closure_spec_preflight_fails_closed(
    spec: SymbolicClosureSpec,
    message: str,
) -> None:
    with pytest.raises(SymbolicClosureConfigurationError, match=message):
        validate_symbolic_closure_spec(
            spec,
            input_types={
                "quadratic": "Expression",
                "x": (
                    "Expression"
                    if "requires x:Symbol" in message
                    else "Symbol"
                ),
                "all_coefficients": "SymbolList",
                "target_parameter": "Symbol",
                "constraint": "Condition",
            },
            output_types={"unsupported": "PathTransformation"},
        )


def test_symbolic_closure_rejects_typed_known_symbol_identity_drift() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}

    with pytest.raises(
        SymbolicClosureRuntimeDriftError,
        match="runtime Symbol identity drift: parameter",
    ):
        execute_symbolic_closure(
            _quadratic_spec(),
            args={
                "quadratic": a * x**2 + b,
                "quadratic_template": a * x**2 + b,
                "x": x,
                "curve_point": (1, 5),
                "parameter": a,
                "parameter_value": 2,
                "target_parameter": b,
            },
            target_object_id=ids[b],
            runtime_symbol_bindings=ids,
            arg_object_ids={
                "target_parameter": (ids[b],),
                "parameter": (ids[b],),
            },
            kernel=kernel,
        )


@pytest.mark.parametrize("known_source", ("coefficient", "parameter"))
def test_preclosed_target_matches_quadratic_method(
    known_source: str,
) -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": a * x**2 + b,
        "quadratic_template": a * x**2 + b,
        "x": x,
        "all_coefficients": [a, b],
        "known_coefficients": {a: 1},
        "target_parameter": b,
    }
    if known_source == "coefficient":
        args["known_coefficients"][b] = 2
    else:
        args["parameter"] = b
        args["parameter_value"] = 2

    method_result = QuadraticFromConstraintsMethod().run(args, kernel)
    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert closure.status == "unique"
    assert closure.target_value == 2
    assert method_result.outputs["parameter_value"].value == 2


def test_preclosed_target_still_rejects_conflicting_equations() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": a * x**2 + b,
        "quadratic_template": a * x**2 + b,
        "x": x,
        "all_coefficients": [a, b],
        "known_coefficients": {a: 1, b: 2},
        "extra_equation": sp.Eq(b, 3),
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert closure.status == "inconsistent"
    with pytest.raises(ValueError, match="constraints_inconsistent"):
        QuadraticFromConstraintsMethod().run(args, kernel)


def test_preclosed_ambiguous_equations_report_branch_count() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": a * x**2 + b,
        "quadratic_template": a * x**2 + b,
        "x": x,
        "all_coefficients": [a, b],
        "known_coefficients": {b: 2},
        "extra_equation": sp.Eq(a**2, 1),
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert closure.status == "ambiguous"
    assert closure.branch_count == 2
    assert closure.provenance is not None
    assert closure.provenance.branch_count == 2
    with pytest.raises(
        ValueError,
        match=r"constraints_ambiguous: branch_count=2",
    ):
        QuadraticFromConstraintsMethod().run(args, kernel)


def test_preclosed_rejects_equations_outside_declared_solve_domain() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "t"])
    x, b, t = (symbols[name] for name in ("x", "b", "t"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": x**2 + b,
        "quadratic_template": x**2 + b,
        "x": x,
        "all_coefficients": [b],
        "known_coefficients": {b: 2},
        "extra_equation": sp.Eq(t**2, 1),
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert closure.status == "inconsistent"
    assert closure.branch_count == 0
    with pytest.raises(ValueError, match="constraints_inconsistent"):
        QuadraticFromConstraintsMethod().run(args, kernel)


def test_preclosed_target_rejects_preserved_materialized_conflict() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (
        symbols[name] for name in ("x", "a", "b", "c")
    )
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": a * x**2 + (1 - c) * x + c,
        "quadratic_template": a * x**2 + b * x + c,
        "x": x,
        "all_coefficients": [a, b, c],
        "known_coefficients": {a: 1, b: 5},
        "free_parameter": c,
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert closure.status == "inconsistent"
    with pytest.raises(ValueError, match="constraints_inconsistent"):
        QuadraticFromConstraintsMethod().run(args, kernel)


def test_preclosed_target_reconciles_non_preserved_materialized_relation() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (
        symbols[name] for name in ("x", "a", "b", "c")
    )
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": a * x**2 + (1 - c) * x + c,
        "quadratic_template": a * x**2 + b * x + c,
        "x": x,
        "all_coefficients": [a, b, c],
        "known_coefficients": {a: 1, b: 5},
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )
    method = QuadraticFromConstraintsMethod().run(args, kernel)

    assert closure.status == "unique"
    assert closure.target_value == 5
    assert closure.substitution[c] == -4
    assert method.outputs["coefficients"].value == {a: 1, b: 5, c: -4}


def test_mapper_only_target_matches_quadratic_method() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = (symbols[name] for name in ("x", "b", "c"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": -x**2 - 2 * x + c,
        "quadratic_template": -x**2 + b * x + c,
        "x": x,
        "all_coefficients": [c],
        "curve_point": (0, 0),
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )
    method_result = QuadraticFromConstraintsMethod().run(args, kernel)

    assert closure.status == "unique"
    assert closure.target_value == -2
    assert method_result.outputs["parameter_value"].value == -2
    assert method_result.outputs["coefficients"].value[b] == -2


def test_conflicting_known_sources_are_inconsistent_for_both_paths() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = (symbols[name] for name in ("x", "b", "c"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    args = {
        "quadratic": x**2 + b * x + c,
        "quadratic_template": x**2 + b * x + c,
        "x": x,
        "all_coefficients": [b, c],
        "known_coefficients": {b: 2},
        "parameter": b,
        "parameter_value": 5,
        "target_parameter": b,
    }

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args=args,
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        arg_object_ids={
            "target_parameter": (ids[b],),
            "parameter": (ids[b],),
            "known_coefficients": (ids[b],),
        },
        kernel=kernel,
    )

    assert closure.status == "inconsistent"
    with pytest.raises(ValueError, match="constraints_inconsistent"):
        QuadraticFromConstraintsMethod().run(args, kernel)


def test_preclosed_residual_includes_preserved_symbol_basis() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = (symbols[name] for name in ("x", "b", "c"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}

    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args={
            "quadratic": -x**2 + b * x + c,
            "quadratic_template": -x**2 + b * x + c,
            "x": x,
            "all_coefficients": [b, c],
            "known_coefficients": {b: 2},
            "free_parameter": c,
            "target_parameter": b,
        },
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        arg_object_ids={
            "target_parameter": (ids[b],),
            "known_coefficients": (ids[b],),
            "free_parameter": (ids[c],),
        },
        kernel=kernel,
    )

    assert closure.status == "unique"
    assert closure.residual_symbols == (c,)
    assert closure.residual_symbol_ids == (ids[c],)


def test_known_mapping_keys_must_match_typed_arg_identities() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}

    with pytest.raises(
        SymbolicClosureRuntimeDriftError,
        match="known mapping identity drift",
    ):
        execute_symbolic_closure(
            _quadratic_spec(),
            args={
                "quadratic": a * x**2 + b,
                "quadratic_template": a * x**2 + b,
                "x": x,
                "all_coefficients": [a, b],
                "known_coefficients": {a: 1, b: 2},
                "target_parameter": b,
            },
            target_object_id=ids[b],
            runtime_symbol_bindings=ids,
            arg_object_ids={
                "target_parameter": (ids[b],),
                "known_coefficients": (ids[a],),
            },
            kernel=kernel,
        )


@pytest.mark.parametrize(
    ("runtime_type", "return_name", "wrong_value"),
    (
        ("Coefficients", "coefficients", lambda x, b, c: {b: 7}),
        (
            "Parabola",
            "parabola",
            lambda x, b, c: -x**2 + 7 * x + c,
        ),
        (
            "Parabola",
            "parabola",
            lambda x, b, c: -x**2 + (b + 1) * x + c,
        ),
    ),
)
def test_companion_outputs_must_encode_the_solved_target(
    runtime_type: str,
    return_name: str,
    wrong_value: object,
) -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "b", "c"])
    x, b, c = (symbols[name] for name in ("x", "b", "c"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    closure = execute_symbolic_closure(
        _quadratic_spec(),
        args={
            "quadratic": -x**2 + b * x + c,
            "quadratic_template": -x**2 + b * x + c,
            "x": x,
            "all_coefficients": [b, c],
            "curve_point": (-c, 0),
            "free_parameter": c,
            "target_parameter": b,
        },
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    with pytest.raises(
        SymbolicClosureRuntimeDriftError,
        match="companion output does not match closure",
    ):
        substitute_symbolic_closure_output(
            TypedValue(runtime_type, wrong_value(x, b, c)),
            closure,
            return_name=return_name,
        )


def test_unvalidated_closure_cannot_rewrite_symbolic_output() -> None:
    b = sp.Symbol("b")
    forged = SymbolicClosureExecutionResult(
        "unique",
        target=b,
        target_object_id=_symbol_id("b"),
        target_value=sp.Integer(99),
        substitutions=((b, sp.Integer(99)),),
    )

    with pytest.raises(
        SymbolicClosureRuntimeDriftError,
        match="validation context is not attached",
    ):
        substitute_symbolic_closure_output(
            TypedValue("Parabola", b * sp.Symbol("x")),
            forged,
        )


def test_declared_constraint_filter_requires_runtime_input() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}
    spec = replace(
        _quadratic_spec(),
        constraint_filter="parameter_value_constraint",
        constraint_args=("value_constraint",),
    )

    with pytest.raises(
        SymbolicClosureRuntimeDriftError,
        match="constraint filter inputs missing: value_constraint",
    ):
        execute_symbolic_closure(
            spec,
            args={
                "quadratic": a * x**2 + b,
                "quadratic_template": a * x**2 + b,
                "x": x,
                "all_coefficients": [a, b],
                "known_coefficients": {a: 1},
                "extra_equation": sp.Eq(b, 5),
                "target_parameter": b,
            },
            target_object_id=ids[b],
            runtime_symbol_bindings=ids,
            kernel=kernel,
        )


def test_optional_constraint_keeps_ambiguous_branches_until_filtered() -> None:
    kernel = SympyKernel()
    parameter = kernel.symbols(["m"])["m"]
    spec = SymbolicClosureSpec(
        target_arg="parameter",
        equation_builder="expression_equals_value",
        constraint_filter="parameter_value_constraint",
        constraint_args=("constraint",),
        constraint_args_optional=True,
        substitution_outputs=("parameter_value",),
        output_validator="parameter_value_closure_outputs",
    )

    ambiguous = solve_symbolic_closure_math(
        spec,
        args={
            "expression": parameter**2,
            "condition": {"value": "1"},
            "parameter": parameter,
        },
        kernel=kernel,
    )
    filtered = solve_symbolic_closure_math(
        spec,
        args={
            "expression": parameter**2,
            "condition": {"value": "1"},
            "parameter": parameter,
            "constraint": {"operator": ">", "value": 0},
        },
        kernel=kernel,
    )

    assert ambiguous.status == "ambiguous"
    assert ambiguous.branch_count == 2
    assert require_unique_symbolic_closure(filtered).target_value == 1


@pytest.mark.parametrize("relation", (False, True))
def test_segment_length_builder_substitutes_known_condition_values(
    relation: bool,
) -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["m", "k"])
    parameter, known_parameter = symbols["m"], symbols["k"]
    spec = replace(
        SEGMENT_PARAMETER_SPEC.symbolic_closure,
        known_substitutions=(
            ("known_parameter", "known_parameter_value"),
        ),
    )
    assert spec is not None
    args = {
        "p1": (parameter, 0),
        "p2": (0, 0),
        "parameter": parameter,
        "known_parameter": known_parameter,
        "known_parameter_value": 2 if relation else 4,
        "constraint": {"operator": ">", "value": 0},
    }
    if relation:
        args.update(
            {
                "reference_p1": (0, 0),
                "reference_p2": (1, 0),
                "condition": {
                    "type": "segment_length_relation",
                    "left_segment": "anonymous_left",
                    "right_segment": "anonymous_right",
                    "scale": known_parameter,
                },
            }
        )
    else:
        args["condition"] = {"value": known_parameter}

    result = solve_symbolic_closure_math(
        spec,
        args=args,
        kernel=kernel,
    )

    assert result.status == "unique"
    assert result.target_value == 2
    assert result.residual_symbols == ()


@pytest.mark.parametrize(
    ("spec", "args_factory", "expected"),
    (
        (
            CURVE_POINT_PARAMETER_SPEC.symbolic_closure,
            lambda x, m: {
                "quadratic": x**2 + m * x,
                "x": x,
                "point": (1, 2),
                "parameter": m,
            },
            1,
        ),
        (
            EXPRESSION_PARAMETER_SPEC.symbolic_closure,
            lambda _x, m: {
                "expression": m + 1,
                "condition": {"value": "5"},
                "parameter": m,
            },
            4,
        ),
        (
            MINIMUM_PARAMETER_SPEC.symbolic_closure,
            lambda _x, m: {
                "minimum_expression": m + 1,
                "condition": {"value": "5"},
                "parameter": m,
            },
            4,
        ),
        (
            SEGMENT_PARAMETER_SPEC.symbolic_closure,
            lambda _x, m: {
                "p1": (m, 0),
                "p2": (0, 0),
                "condition": {"value": "4"},
                "parameter": m,
                "constraint": {"operator": ">", "value": 0},
            },
            2,
        ),
    ),
)
def test_direct_and_typed_parameter_closure_share_math_core(
    spec,
    args_factory,
    expected,
) -> None:
    assert spec is not None
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "m"])
    x, parameter = symbols["x"], symbols["m"]
    args = args_factory(x, parameter)
    bindings = {
        symbol: _symbol_id(symbol.name) for symbol in symbols.values()
    }

    direct = solve_symbolic_closure_math(spec, args=args, kernel=kernel)
    typed = execute_symbolic_closure(
        spec,
        args=args,
        target_object_id=bindings[parameter],
        runtime_symbol_bindings=bindings,
        kernel=kernel,
    )

    assert direct.status == typed.status == "unique"
    assert sp.simplify(direct.target_value - expected) == 0
    assert sp.simplify(typed.target_value - expected) == 0
    assert direct.substitution == typed.substitution


def test_curve_points_are_recorded_as_equation_source() -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b"])
    x, a, b = (symbols[name] for name in ("x", "a", "b"))
    ids = {symbol: _symbol_id(symbol.name) for symbol in symbols.values()}

    result = execute_symbolic_closure(
        _quadratic_spec(),
        args={
            "quadratic": a * x**2 + b,
            "quadratic_template": a * x**2 + b,
            "x": x,
            "all_coefficients": [a, b],
            "curve_points": ((1, 5),),
            "free_parameter": a,
            "target_parameter": b,
        },
        target_object_id=ids[b],
        runtime_symbol_bindings=ids,
        kernel=kernel,
    )

    assert result.status == "unique"
    assert result.provenance is not None
    assert "curve_points" in result.provenance.equation_sources
