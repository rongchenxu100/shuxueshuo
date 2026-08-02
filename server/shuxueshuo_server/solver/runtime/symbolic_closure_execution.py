"""Runtime-grounded symbolic target closure for Functional transactions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

import sympy as sp

from shuxueshuo_server.solver.contracts import CheckResult, SymbolicClosureSpec
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.models import TypedValue
from shuxueshuo_server.solver.runtime.quadratic_constraint_solver import (
    QuadraticConstraintSolveRequest,
    build_quadratic_constraint_system,
    quadratic_coefficient_expression,
    quadratic_target_expression,
    value_satisfies_constraint,
)
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.strategy_models import (
    SymbolicClosureProvenance,
)
from shuxueshuo_server.solver.runtime.symbolic_target_closure import (
    solve_target_symbol_closure,
)


FunctionalSymbolicClosureMode = Literal[
    "disabled",
    "shadow",
    "authoritative",
]
SymbolicClosureExecutionStatus = Literal[
    "not_applicable",
    "unique",
    "identity_unresolved",
    "underdetermined",
    "ambiguous",
    "inconsistent",
]


class SymbolicClosureConfigurationError(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            "planner_configuration_error: "
            f"planner.symbolic_closure_spec_invalid: {detail}"
        )


class SymbolicClosureRuntimeDriftError(ValueError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            "planner_configuration_error: "
            f"planner.contract_runtime_symbol_drift: {detail}"
        )


@dataclass(frozen=True)
class SymbolicEquationBuildResult:
    equations: tuple[Any, ...]
    equation_sources: tuple[str, ...] = ()
    mapper_context: Mapping[str, Any] | None = None
    # ``None`` keeps a generic builder unrestricted. Domain-specific builders
    # declare the Symbols this closure is allowed to solve so unrelated free
    # Symbols cannot silently expand the method contract.
    solvable_symbols: tuple[sp.Symbol, ...] | None = None


class SymbolicEquationBuilder(Protocol):
    def __call__(
        self,
        args: Mapping[str, Any],
        known_substitutions: Mapping[sp.Symbol, sp.Expr],
    ) -> SymbolicEquationBuildResult: ...


class SymbolicRepresentationMapper(Protocol):
    def __call__(
        self,
        *,
        target: sp.Symbol,
        args: Mapping[str, Any],
        build: SymbolicEquationBuildResult,
        known_substitutions: Mapping[sp.Symbol, sp.Expr],
    ) -> sp.Expr | None: ...


class SymbolicConstraintFilter(Protocol):
    def __call__(
        self,
        value: sp.Expr,
        constraints: Sequence[Any],
    ) -> bool: ...


class SymbolicOutputValidator(Protocol):
    def __call__(
        self,
        *,
        outputs: Mapping[str, TypedValue],
        args: Mapping[str, Any],
        build: SymbolicEquationBuildResult,
        result: "SymbolicClosureExecutionResult",
    ) -> tuple[CheckResult, ...]: ...


@dataclass(frozen=True)
class SymbolicClosureExecutionResult:
    status: SymbolicClosureExecutionStatus
    target: sp.Symbol | None = None
    target_object_id: MathObjectId | None = None
    target_value: sp.Expr | None = None
    substitutions: tuple[tuple[sp.Symbol, sp.Expr], ...] = ()
    residual_symbols: tuple[sp.Symbol, ...] = ()
    residual_symbol_ids: tuple[MathObjectId, ...] = ()
    branch_count: int = 0
    affected_returns: tuple[str, ...] = ()
    provenance: SymbolicClosureProvenance | None = None
    runtime_validated: bool = False
    output_validator: str | None = None
    validation_args: Mapping[str, Any] | None = None
    validation_build: SymbolicEquationBuildResult | None = None

    @property
    def substitution(self) -> dict[sp.Symbol, sp.Expr]:
        return dict(self.substitutions)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "target_object_id": (
                self.target_object_id.to_payload()
                if self.target_object_id is not None
                else None
            ),
            "target_value": (
                sp.sstr(self.target_value)
                if self.target_value is not None
                else None
            ),
            "residual_symbol_ids": [
                item.to_payload() for item in self.residual_symbol_ids
            ],
            "branch_count": self.branch_count,
            "affected_returns": list(self.affected_returns),
            "runtime_validated": self.runtime_validated,
            "provenance": (
                self.provenance.to_payload()
                if self.provenance is not None
                else None
            ),
        }


class _Registry:
    def __init__(self, label: str) -> None:
        self._label = label
        self._items: dict[str, Any] = {}
        self._input_requirements: dict[
            str,
            dict[str, frozenset[str]],
        ] = {}
        self._accepted_types: dict[str, frozenset[str]] = {}

    def register(
        self,
        adapter_id: str,
        adapter: Any,
        *,
        input_requirements: Mapping[str, str | Sequence[str]] | None = None,
        accepted_types: Sequence[str] = (),
    ) -> None:
        if not adapter_id or adapter_id in self._items:
            raise SymbolicClosureConfigurationError(
                f"duplicate or empty {self._label}: {adapter_id!r}"
            )
        self._items[adapter_id] = adapter
        self._input_requirements[adapter_id] = {
            name: frozenset(
                (runtime_types,)
                if isinstance(runtime_types, str)
                else runtime_types
            )
            for name, runtime_types in (input_requirements or {}).items()
        }
        self._accepted_types[adapter_id] = frozenset(accepted_types)

    def require(self, adapter_id: str) -> Any:
        adapter = self._items.get(adapter_id)
        if adapter is None:
            raise SymbolicClosureConfigurationError(
                f"unknown {self._label}: {adapter_id}"
            )
        return adapter

    def validate_inputs(
        self,
        adapter_id: str,
        input_types: Mapping[str, str],
    ) -> None:
        self.require(adapter_id)
        for arg_name, expected_types in self._input_requirements.get(
            adapter_id,
            {},
        ).items():
            actual = input_types.get(arg_name)
            if actual not in expected_types:
                raise SymbolicClosureConfigurationError(
                    f"{self._label} {adapter_id} requires "
                    f"{arg_name}:{'/'.join(sorted(expected_types))}, "
                    f"got {actual or '<missing>'}"
                )

    def validate_arg_types(
        self,
        adapter_id: str,
        arg_names: Sequence[str],
        input_types: Mapping[str, str],
    ) -> None:
        self.require(adapter_id)
        accepted = self._accepted_types.get(adapter_id, frozenset())
        if not accepted:
            return
        for arg_name in arg_names:
            actual = input_types.get(arg_name)
            if actual not in accepted:
                raise SymbolicClosureConfigurationError(
                    f"{self._label} {adapter_id} requires "
                    f"{arg_name}:{'/'.join(sorted(accepted))}, "
                    f"got {actual or '<missing>'}"
                )


class SymbolicEquationBuilderRegistry(_Registry):
    def __init__(self) -> None:
        super().__init__("equation builder")


class SymbolicRepresentationMapperRegistry(_Registry):
    def __init__(self) -> None:
        super().__init__("representation mapper")


class SymbolicConstraintFilterRegistry(_Registry):
    def __init__(self) -> None:
        super().__init__("constraint filter")


class SymbolicOutputSubstitutionRegistry(_Registry):
    def __init__(self) -> None:
        super().__init__("output substitution adapter")


class SymbolicOutputValidatorRegistry(_Registry):
    def __init__(self) -> None:
        super().__init__("output validator")


@dataclass(frozen=True)
class SymbolicClosureRegistries:
    equation_builders: SymbolicEquationBuilderRegistry
    representation_mappers: SymbolicRepresentationMapperRegistry
    constraint_filters: SymbolicConstraintFilterRegistry
    output_substitutions: SymbolicOutputSubstitutionRegistry
    output_validators: SymbolicOutputValidatorRegistry


def default_symbolic_closure_registries() -> SymbolicClosureRegistries:
    builders = SymbolicEquationBuilderRegistry()
    builders.register(
        "quadratic_constraints",
        _quadratic_constraints,
        input_requirements={
            "quadratic": "Expression",
            "x": "Symbol",
            "all_coefficients": "SymbolList",
        },
    )
    mappers = SymbolicRepresentationMapperRegistry()
    mappers.register(
        "polynomial_coefficient_template",
        _polynomial_coefficient_template,
    )
    filters = SymbolicConstraintFilterRegistry()
    filters.register(
        "parameter_value_constraint",
        _parameter_constraint,
        accepted_types=("Constraint",),
    )
    outputs = SymbolicOutputSubstitutionRegistry()
    for runtime_type, adapter in {
        "Coefficients": _substitute_coefficients,
        "Parabola": _substitute_expression,
        "Expression": _substitute_expression,
        "MinimumExpression": _substitute_expression,
        "Point": _substitute_point,
        "Line": _substitute_sequence,
        "ParameterValue": _substitute_expression,
    }.items():
        outputs.register(runtime_type, adapter)
    validators = SymbolicOutputValidatorRegistry()
    validators.register(
        "quadratic_closure_outputs",
        _validate_quadratic_closure_outputs,
    )
    return SymbolicClosureRegistries(
        builders,
        mappers,
        filters,
        outputs,
        validators,
    )


def validate_symbolic_closure_spec(
    spec: SymbolicClosureSpec,
    *,
    input_types: Mapping[str, str],
    output_types: Mapping[str, str],
    registries: SymbolicClosureRegistries | None = None,
) -> None:
    registries = registries or default_symbolic_closure_registries()
    if input_types.get(spec.target_arg) != "Symbol":
        raise SymbolicClosureConfigurationError(
            f"target_arg must be Symbol: {spec.target_arg}"
        )
    if not spec.require_unique_target:
        raise SymbolicClosureConfigurationError(
            "runtime closure currently requires a unique target"
        )
    registries.equation_builders.validate_inputs(
        spec.equation_builder,
        input_types,
    )
    if spec.representation_mapper is not None:
        registries.representation_mappers.require(
            spec.representation_mapper
        )
    if spec.constraint_filter is not None:
        if not spec.constraint_args:
            raise SymbolicClosureConfigurationError(
                "constraint_filter requires constraint_args"
            )
        registries.constraint_filters.validate_arg_types(
            spec.constraint_filter,
            spec.constraint_args,
            input_types,
        )
    elif spec.constraint_args:
        raise SymbolicClosureConfigurationError(
            "constraint_args require constraint_filter"
        )
    for symbol_arg, value_arg in spec.known_substitutions:
        if input_types.get(symbol_arg) != "Symbol":
            raise SymbolicClosureConfigurationError(
                f"known substitution symbol must be Symbol: {symbol_arg}"
            )
        if input_types.get(value_arg) != "ParameterValue":
            raise SymbolicClosureConfigurationError(
                "known substitution value must be ParameterValue: "
                f"{value_arg}"
            )
    for arg_name in spec.known_mapping_args:
        if input_types.get(arg_name) != "Coefficients":
            raise SymbolicClosureConfigurationError(
                "known mapping input must be Coefficients: "
                f"{arg_name}"
            )
    for arg_name in spec.preserved_symbol_args:
        if input_types.get(arg_name) not in {"Symbol", "SymbolList"}:
            raise SymbolicClosureConfigurationError(
                "preserved symbol input must be Symbol or SymbolList: "
                f"{arg_name}"
            )
    for output_name in spec.substitution_outputs:
        runtime_type = output_types.get(output_name)
        if runtime_type is None:
            raise SymbolicClosureConfigurationError(
                f"unknown substitution output: {output_name}"
            )
        registries.output_substitutions.require(runtime_type)
    if spec.substitution_outputs and not spec.output_validator:
        raise SymbolicClosureConfigurationError(
            "substitution_outputs require output_validator"
        )
    if spec.output_validator is not None:
        registries.output_validators.require(spec.output_validator)


def execute_symbolic_closure(
    spec: SymbolicClosureSpec,
    *,
    args: Mapping[str, Any],
    target_object_id: MathObjectId | None,
    runtime_symbol_bindings: Mapping[sp.Symbol, MathObjectId],
    kernel: SympyKernel,
    target_binding: str | None = None,
    arg_object_ids: Mapping[str, tuple[MathObjectId, ...]] | None = None,
    registries: SymbolicClosureRegistries | None = None,
) -> SymbolicClosureExecutionResult:
    registries = registries or default_symbolic_closure_registries()
    raw_target = args.get(spec.target_arg)
    if raw_target is None:
        return SymbolicClosureExecutionResult("not_applicable")
    if not isinstance(raw_target, sp.Symbol) or target_object_id is None:
        raise SymbolicClosureRuntimeDriftError(
            f"target identity is incomplete: {spec.target_arg}"
        )
    if runtime_symbol_bindings.get(raw_target) != target_object_id:
        raise SymbolicClosureRuntimeDriftError(
            f"target runtime identity drift: {spec.target_arg}"
        )
    expected_target_ids = (arg_object_ids or {}).get(spec.target_arg, ())
    if expected_target_ids and expected_target_ids != (target_object_id,):
        raise SymbolicClosureRuntimeDriftError(
            f"target binding identity drift: {spec.target_arg}"
        )
    known: dict[sp.Symbol, sp.Expr] = {}
    known_sources: list[str] = []
    known_conflict = False
    for symbol_arg, value_arg in spec.known_substitutions:
        symbol = args.get(symbol_arg)
        value = args.get(value_arg)
        if symbol is None and value is None:
            continue
        if not isinstance(symbol, sp.Symbol) or value is None:
            raise SymbolicClosureRuntimeDriftError(
                f"incomplete known substitution: {symbol_arg}/{value_arg}"
            )
        _require_bound_symbol_id(
            symbol,
            arg_name=symbol_arg,
            expected_ids=(arg_object_ids or {}).get(symbol_arg, ()),
            runtime_symbol_bindings=runtime_symbol_bindings,
        )
        known_conflict = (
            _merge_known_substitution(known, symbol, value)
            or known_conflict
        )
        known_sources.append(f"{symbol_arg}+{value_arg}")
    for mapping_arg in spec.known_mapping_args:
        raw_mapping = args.get(mapping_arg)
        if raw_mapping is None:
            continue
        if not isinstance(raw_mapping, Mapping):
            raise SymbolicClosureRuntimeDriftError(
                f"known mapping is not a mapping: {mapping_arg}"
            )
        actual_mapping_ids: list[MathObjectId] = []
        for symbol, value in raw_mapping.items():
            if not isinstance(symbol, sp.Symbol):
                raise SymbolicClosureRuntimeDriftError(
                    f"known mapping key is not Symbol: {mapping_arg}"
                )
            actual_mapping_ids.append(
                _require_bound_symbol_id(
                    symbol,
                    arg_name=mapping_arg,
                    expected_ids=(),
                    runtime_symbol_bindings=runtime_symbol_bindings,
                )
            )
            known_conflict = (
                _merge_known_substitution(known, symbol, value)
                or known_conflict
            )
        expected_mapping_ids = (arg_object_ids or {}).get(mapping_arg, ())
        if expected_mapping_ids and (
            len(expected_mapping_ids) != len(actual_mapping_ids)
            or frozenset(expected_mapping_ids)
            != frozenset(actual_mapping_ids)
        ):
            raise SymbolicClosureRuntimeDriftError(
                f"known mapping identity drift: {mapping_arg}"
            )
        known_sources.append(mapping_arg)
    preserve_symbols = tuple(
        dict.fromkeys(
            symbol
            for arg_name in spec.preserved_symbol_args
            for symbol in _symbols_from_arg(args.get(arg_name))
        )
    )
    for arg_name in spec.preserved_symbol_args:
        symbols = _symbols_from_arg(args.get(arg_name))
        expected_ids = (arg_object_ids or {}).get(arg_name, ())
        if expected_ids and len(expected_ids) != len(symbols):
            raise SymbolicClosureRuntimeDriftError(
                "preserved symbol cardinality drift: "
                f"{arg_name}, expected={len(expected_ids)}, "
                f"runtime={len(symbols)}"
            )
        for index, symbol in enumerate(symbols):
            _require_bound_symbol_id(
                symbol,
                arg_name=arg_name,
                expected_ids=(
                    (expected_ids[index],)
                    if expected_ids
                    else ()
                ),
                runtime_symbol_bindings=runtime_symbol_bindings,
            )
    constraint_values, constraint_filter = _constraint_filter_inputs(
        spec,
        args=args,
        registries=registries,
    )
    builder = registries.equation_builders.require(spec.equation_builder)
    build = builder(args, known)
    preclosed = dict(known)
    if known_conflict:
        return _with_output_validation(
            _preclosed_result(
                spec,
                status="inconsistent",
                target=raw_target,
                target_object_id=target_object_id,
                substitutions=preclosed,
                target_value=None,
                runtime_symbol_bindings=runtime_symbol_bindings,
                target_binding=target_binding,
                known_sources=tuple(known_sources),
                preserve_symbols=preserve_symbols,
                equation_sources=(
                    "known_substitution_conflict",
                    *build.equation_sources,
                ),
                branch_count=0,
            ),
            spec,
            args=args,
            build=build,
        )
    if raw_target in preclosed:
        (
            preclosed_status,
            preclosed,
            preclosed_branch_count,
        ) = _resolve_preclosed_equations(
            build.equations,
            substitutions=preclosed,
            preserve_symbols=preserve_symbols,
            solvable_symbols=build.solvable_symbols,
            kernel=kernel,
        )
        target_value = sp.simplify(
            preclosed[raw_target].subs(preclosed)
        )
        if (
            preclosed_status != "unique"
            or (
                constraint_filter is not None
                and not constraint_filter(target_value, constraint_values)
            )
        ):
            return _with_output_validation(
                _preclosed_result(
                    spec,
                    status=(
                        preclosed_status
                        if preclosed_status != "unique"
                        else "inconsistent"
                    ),
                    target=raw_target,
                    target_object_id=target_object_id,
                    substitutions=preclosed,
                    target_value=None,
                    runtime_symbol_bindings=runtime_symbol_bindings,
                    target_binding=target_binding,
                    known_sources=tuple(known_sources),
                    preserve_symbols=preserve_symbols,
                    equation_sources=build.equation_sources,
                    branch_count=(
                        preclosed_branch_count
                        if preclosed_status != "unique"
                        else 1
                    ),
                ),
                spec,
                args=args,
                build=build,
            )
        return _with_output_validation(
            _preclosed_result(
                spec,
                status="unique",
                target=raw_target,
                target_object_id=target_object_id,
                substitutions=preclosed,
                target_value=target_value,
                runtime_symbol_bindings=runtime_symbol_bindings,
                target_binding=target_binding,
                known_sources=tuple(known_sources),
                preserve_symbols=preserve_symbols,
                equation_sources=build.equation_sources,
                branch_count=preclosed_branch_count,
            ),
            spec,
            args=args,
            build=build,
        )
    mapper = (
        registries.representation_mappers.require(
            spec.representation_mapper
        )
        if spec.representation_mapper is not None
        else None
    )
    target_expression = (
        mapper(
            target=raw_target,
            args=args,
            build=build,
            known_substitutions=known,
        )
        if mapper is not None
        else None
    )
    solved = solve_target_symbol_closure(
        build.equations,
        target=raw_target,
        target_expression=target_expression,
        kernel=kernel,
        accept_target=(
            (lambda value: constraint_filter(value, constraint_values))
            if constraint_filter is not None
            else None
        ),
        preserve_symbols=preserve_symbols,
    )
    status: SymbolicClosureExecutionStatus = solved.status
    all_substitutions = dict(known)
    all_substitutions.update(solved.substitution)
    if solved.target_value is not None:
        all_substitutions[raw_target] = solved.target_value
    residual_symbols = (
        _resolved_residual_symbols(
            solved.residual_symbols,
            all_substitutions,
        )
        if status == "unique"
        else solved.residual_symbols
    )
    residual_ids = _symbol_ids(
        residual_symbols,
        runtime_symbol_bindings,
    )
    preserved_ids = _symbol_ids(
        preserve_symbols,
        runtime_symbol_bindings,
    )
    substitution_provenance = tuple(
        (runtime_symbol_bindings[symbol], sp.sstr(value))
        for symbol, value in all_substitutions.items()
        if symbol in runtime_symbol_bindings
    )
    provenance = SymbolicClosureProvenance(
        status=status,
        target_object_id=target_object_id,
        target_value=(
            sp.sstr(solved.target_value)
            if solved.target_value is not None
            else None
        ),
        substitutions=substitution_provenance,
        residual_symbol_ids=residual_ids,
        branch_count=solved.branch_count,
        equation_builder=spec.equation_builder,
        representation_mapper=spec.representation_mapper,
        constraint_filter=spec.constraint_filter,
        target_binding=target_binding,
        equation_sources=build.equation_sources,
        known_substitution_sources=tuple(known_sources),
        preserved_symbol_ids=preserved_ids,
        affected_returns=spec.substitution_outputs,
    )
    return _with_output_validation(
        SymbolicClosureExecutionResult(
            status=status,
            target=raw_target,
            target_object_id=target_object_id,
            target_value=solved.target_value,
            substitutions=tuple(all_substitutions.items()),
            residual_symbols=residual_symbols,
            residual_symbol_ids=residual_ids,
            branch_count=solved.branch_count,
            affected_returns=spec.substitution_outputs,
            provenance=provenance,
            runtime_validated=True,
        ),
        spec,
        args=args,
        build=build,
    )


def _resolved_residual_symbols(
    equation_symbols: tuple[sp.Symbol, ...],
    substitutions: Mapping[sp.Symbol, sp.Expr],
) -> tuple[sp.Symbol, ...]:
    residual: set[sp.Symbol] = set()
    for symbol in equation_symbols:
        if symbol not in substitutions:
            residual.add(symbol)
            continue
        resolved = sp.simplify(
            sp.sympify(substitutions[symbol]).subs(substitutions)
        )
        residual.update(resolved.free_symbols)
    return tuple(sorted(residual, key=lambda symbol: symbol.sort_key()))


def _merge_known_substitution(
    known: dict[sp.Symbol, sp.Expr],
    symbol: sp.Symbol,
    value: Any,
) -> bool:
    normalized = sp.sympify(value)
    previous = known.get(symbol)
    if previous is None:
        known[symbol] = normalized
        return False
    return not _expressions_equivalent(previous, normalized)


def _resolve_preclosed_equations(
    equations: Sequence[Any],
    *,
    substitutions: Mapping[sp.Symbol, sp.Expr],
    preserve_symbols: Sequence[sp.Symbol],
    solvable_symbols: Sequence[sp.Symbol] | None,
    kernel: SympyKernel,
) -> tuple[
    SymbolicClosureExecutionStatus,
    dict[sp.Symbol, sp.Expr],
    int,
]:
    normalized: list[sp.Equality] = []
    for equation in equations:
        resolved = equation
        if hasattr(resolved, "subs"):
            resolved = resolved.subs(substitutions)
        if resolved is sp.S.false:
            return "inconsistent", dict(substitutions), 0
        if resolved is sp.S.true:
            continue
        if isinstance(resolved, sp.Equality):
            residual = sp.simplify(resolved.lhs - resolved.rhs)
            if residual == 0:
                continue
            if not residual.free_symbols:
                return "inconsistent", dict(substitutions), 0
            normalized.append(sp.Eq(residual, 0))
    if not normalized:
        return "unique", dict(substitutions), 1

    preserved = set(preserve_symbols)
    residual_symbols = {
        symbol
        for equation in normalized
        for symbol in (equation.lhs - equation.rhs).free_symbols
    }
    if solvable_symbols is not None and not (
        residual_symbols - preserved
    ).issubset(set(solvable_symbols)):
        return "inconsistent", dict(substitutions), 0
    solve_symbols = tuple(
        sorted(
            residual_symbols - preserved,
            key=lambda symbol: symbol.name,
        )
    )
    if not solve_symbols:
        return "inconsistent", dict(substitutions), 0

    branches = kernel.solve_equations(normalized, solve_symbols)
    if not branches:
        return "inconsistent", dict(substitutions), 0
    complete = tuple(
        {
            symbol: sp.simplify(branch[symbol])
            for symbol in solve_symbols
            if symbol in branch
        }
        for branch in branches
        if all(symbol in branch for symbol in solve_symbols)
    )
    if not complete:
        return "underdetermined", dict(substitutions), len(branches)
    if len(complete) != 1:
        return "ambiguous", dict(substitutions), len(complete)

    resolved_substitutions = {
        **substitutions,
        **complete[0],
    }
    for equation in normalized:
        residual = sp.simplify(
            (equation.lhs - equation.rhs).subs(resolved_substitutions)
        )
        if residual != 0:
            return "inconsistent", dict(substitutions), 0
    return "unique", resolved_substitutions, 1


def _with_output_validation(
    result: SymbolicClosureExecutionResult,
    spec: SymbolicClosureSpec,
    *,
    args: Mapping[str, Any],
    build: SymbolicEquationBuildResult,
) -> SymbolicClosureExecutionResult:
    return replace(
        result,
        output_validator=spec.output_validator,
        validation_args=dict(args),
        validation_build=build,
    )


def _constraint_filter_inputs(
    spec: SymbolicClosureSpec,
    *,
    args: Mapping[str, Any],
    registries: SymbolicClosureRegistries,
) -> tuple[tuple[Any, ...], SymbolicConstraintFilter | None]:
    if spec.constraint_filter is None:
        return (), None
    missing = tuple(
        name
        for name in spec.constraint_args
        if name not in args or args[name] is None
    )
    if missing:
        raise SymbolicClosureRuntimeDriftError(
            "constraint filter inputs missing: " + ", ".join(missing)
        )
    return (
        tuple(args[name] for name in spec.constraint_args),
        registries.constraint_filters.require(spec.constraint_filter),
    )


def _preclosed_result(
    spec: SymbolicClosureSpec,
    *,
    status: SymbolicClosureExecutionStatus,
    target: sp.Symbol,
    target_object_id: MathObjectId,
    substitutions: Mapping[sp.Symbol, sp.Expr],
    target_value: sp.Expr | None,
    runtime_symbol_bindings: Mapping[sp.Symbol, MathObjectId],
    target_binding: str | None,
    known_sources: tuple[str, ...],
    preserve_symbols: tuple[sp.Symbol, ...],
    equation_sources: tuple[str, ...],
    branch_count: int,
) -> SymbolicClosureExecutionResult:
    residual_symbols = tuple(
        sorted(
            {
                *(
                    target_value.free_symbols
                    if target_value is not None
                    else ()
                ),
                *preserve_symbols,
            }
            - {target},
            key=lambda symbol: symbol.name,
        )
    )
    residual_ids = _symbol_ids(
        residual_symbols,
        runtime_symbol_bindings,
    )
    preserved_ids = _symbol_ids(
        preserve_symbols,
        runtime_symbol_bindings,
    )
    provenance = SymbolicClosureProvenance(
        status=status,
        target_object_id=target_object_id,
        target_value=(
            sp.sstr(target_value) if target_value is not None else None
        ),
        substitutions=tuple(
            (runtime_symbol_bindings[symbol], sp.sstr(value))
            for symbol, value in substitutions.items()
            if symbol in runtime_symbol_bindings
        ),
        residual_symbol_ids=residual_ids,
        branch_count=branch_count,
        equation_builder=spec.equation_builder,
        representation_mapper=spec.representation_mapper,
        constraint_filter=spec.constraint_filter,
        target_binding=target_binding,
        equation_sources=tuple(
            dict.fromkeys(("known_target_value", *equation_sources))
        ),
        known_substitution_sources=known_sources,
        preserved_symbol_ids=preserved_ids,
        affected_returns=spec.substitution_outputs,
    )
    return SymbolicClosureExecutionResult(
        status=status,
        target=target,
        target_object_id=target_object_id,
        target_value=target_value,
        substitutions=tuple(substitutions.items()),
        residual_symbols=residual_symbols,
        residual_symbol_ids=residual_ids,
        branch_count=branch_count,
        affected_returns=spec.substitution_outputs,
        provenance=provenance,
        runtime_validated=True,
    )


def substitute_symbolic_closure_output(
    value: TypedValue,
    result: SymbolicClosureExecutionResult,
    *,
    return_name: str | None = None,
    validate_output: bool = True,
    registries: SymbolicClosureRegistries | None = None,
) -> TypedValue:
    if result.status != "unique":
        return value
    if not result.runtime_validated:
        raise SymbolicClosureRuntimeDriftError(
            "symbolic closure result was not runtime validated"
        )
    registries = registries or default_symbolic_closure_registries()
    adapter: Callable[[Any, Mapping[sp.Symbol, sp.Expr]], Any] = (
        registries.output_substitutions.require(value.type)
    )
    resolved = adapter(value.value, result.substitution)
    if value.type == "ParameterValue" and result.target_value is not None:
        if sp.simplify(sp.sympify(resolved) - result.target_value) != 0:
            raise SymbolicClosureRuntimeDriftError(
                "ParameterValue does not equal closure target"
            )
        resolved = sp.simplify(result.target_value)
    normalized = TypedValue(
        value.type,
        resolved,
        locked=value.locked,
        source=value.source,
    )
    effective_return_name = return_name or {
        "Coefficients": "coefficients",
        "Parabola": "parabola",
        "ParameterValue": "parameter_value",
    }.get(value.type)
    if validate_output and effective_return_name is not None:
        checks = validate_symbolic_closure_outputs(
            {effective_return_name: normalized},
            result,
            registries=registries,
        )
        failed = tuple(check.name for check in checks if not check.ok)
        if failed:
            raise SymbolicClosureRuntimeDriftError(
                "companion output does not match closure: "
                + ", ".join(failed)
            )
    return normalized


def validate_symbolic_closure_outputs(
    outputs: Mapping[str, TypedValue],
    result: SymbolicClosureExecutionResult,
    *,
    registries: SymbolicClosureRegistries | None = None,
) -> tuple[CheckResult, ...]:
    if result.status != "unique":
        return ()
    if not result.runtime_validated:
        raise SymbolicClosureRuntimeDriftError(
            "symbolic closure result was not runtime validated"
        )
    if result.output_validator is None:
        raise SymbolicClosureRuntimeDriftError(
            "symbolic closure output validator is missing"
        )
    if result.validation_args is None or result.validation_build is None:
        raise SymbolicClosureRuntimeDriftError(
            "symbolic closure validation context is missing"
        )
    registries = registries or default_symbolic_closure_registries()
    validator: SymbolicOutputValidator = (
        registries.output_validators.require(result.output_validator)
    )
    return validator(
        outputs=outputs,
        args=result.validation_args,
        build=result.validation_build,
        result=result,
    )


def closure_failure_code(status: SymbolicClosureExecutionStatus) -> str:
    return {
        "identity_unresolved": "function.symbolic_closure_identity_unresolved",
        "underdetermined": "function.symbolic_closure_underdetermined",
        "ambiguous": "function.symbolic_closure_ambiguous",
        "inconsistent": "function.symbolic_closure_inconsistent",
    }.get(status, "function.symbolic_closure_failed")


def _quadratic_constraints(
    args: Mapping[str, Any],
    known_substitutions: Mapping[sp.Symbol, sp.Expr],
) -> SymbolicEquationBuildResult:
    sources: list[str] = []
    equations: list[Any] = []
    for arg_name in ("coefficient_relation", "extra_equation"):
        equation = args.get(arg_name)
        if equation is not None:
            equations.append(equation)
            sources.append(arg_name)
    points: list[Any] = []
    curve_points = tuple(args.get("curve_points", ()))
    if curve_points:
        points.extend(curve_points)
        sources.append("curve_points")
    for arg_name in ("curve_point", "p1", "p2"):
        if args.get(arg_name) is not None:
            points.append(args[arg_name])
            sources.append(arg_name)
    request = QuadraticConstraintSolveRequest(
        base_expression=sp.sympify(args["quadratic"]),
        independent_symbol=args["x"],
        coefficient_symbols=tuple(args.get("all_coefficients", ())),
        coefficient_template=args.get("quadratic_template"),
        known_coefficients=dict(args.get("known_coefficients", {})),
        curve_points=tuple(points),
        equations=tuple(equations),
        parameter_substitutions=dict(known_substitutions),
        preserve_symbols=tuple(
            symbol
            for arg_name in ("free_parameter", "free_parameters")
            for symbol in _symbols_from_arg(args.get(arg_name))
        ),
        target_symbol=args.get("target_parameter"),
    )
    system = build_quadratic_constraint_system(request)
    if system.contradictory:
        normalized_equations: tuple[Any, ...] = (sp.S.false,)
    else:
        normalized_equations = system.equations
    return SymbolicEquationBuildResult(
        normalized_equations,
        tuple(dict.fromkeys(sources)),
        {
            "quadratic": system.expression,
            "quadratic_request": request,
            "quadratic_system": system,
        },
        tuple(request.coefficient_symbols),
    )


def _polynomial_coefficient_template(
    *,
    target: sp.Symbol,
    args: Mapping[str, Any],
    build: SymbolicEquationBuildResult,
    known_substitutions: Mapping[sp.Symbol, sp.Expr],
) -> sp.Expr | None:
    context = build.mapper_context or {}
    request = context.get("quadratic_request")
    system = context.get("quadratic_system")
    if not isinstance(request, QuadraticConstraintSolveRequest):
        return None
    return quadratic_target_expression(
        replace(request, target_symbol=target),
        system=system,
    )


def _parameter_constraint(value: sp.Expr, constraints: Sequence[Any]) -> bool:
    return all(value_satisfies_constraint(value, item) for item in constraints)


def _symbols_from_arg(value: Any) -> tuple[sp.Symbol, ...]:
    if value is None:
        return ()
    if isinstance(value, sp.Symbol):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, sp.Symbol))
    return ()


def _symbol_ids(
    symbols: Sequence[sp.Symbol],
    bindings: Mapping[sp.Symbol, MathObjectId],
) -> tuple[MathObjectId, ...]:
    missing = tuple(symbol for symbol in symbols if symbol not in bindings)
    if missing:
        raise SymbolicClosureRuntimeDriftError(
            "runtime Symbol identity missing: "
            + ", ".join(sp.sstr(item) for item in missing)
        )
    return tuple(dict.fromkeys(bindings[symbol] for symbol in symbols))


def _require_bound_symbol_id(
    symbol: sp.Symbol,
    *,
    arg_name: str,
    expected_ids: tuple[MathObjectId, ...],
    runtime_symbol_bindings: Mapping[sp.Symbol, MathObjectId],
) -> MathObjectId:
    object_id = runtime_symbol_bindings.get(symbol)
    if object_id is None:
        raise SymbolicClosureRuntimeDriftError(
            f"runtime Symbol identity missing: {arg_name}"
        )
    if expected_ids and expected_ids != (object_id,):
        raise SymbolicClosureRuntimeDriftError(
            f"runtime Symbol identity drift: {arg_name}"
        )
    return object_id


def _substitute_expression(
    value: Any,
    substitutions: Mapping[sp.Symbol, sp.Expr],
) -> sp.Expr:
    return sp.simplify(sp.sympify(value).subs(substitutions))


def _substitute_coefficients(
    value: Any,
    substitutions: Mapping[sp.Symbol, sp.Expr],
) -> dict[Any, sp.Expr]:
    return {
        key: sp.simplify(sp.sympify(item).subs(substitutions))
        for key, item in dict(value).items()
    }


def _substitute_point(
    value: Any,
    substitutions: Mapping[sp.Symbol, sp.Expr],
) -> tuple[sp.Expr, sp.Expr]:
    return tuple(
        sp.simplify(sp.sympify(item).subs(substitutions)) for item in value
    )  # type: ignore[return-value]


def _substitute_sequence(
    value: Any,
    substitutions: Mapping[sp.Symbol, sp.Expr],
) -> Any:
    if isinstance(value, tuple):
        return tuple(
            sp.simplify(sp.sympify(item).subs(substitutions))
            for item in value
        )
    return _substitute_expression(value, substitutions)


def _validate_quadratic_closure_outputs(
    *,
    outputs: Mapping[str, TypedValue],
    args: Mapping[str, Any],
    build: SymbolicEquationBuildResult,
    result: SymbolicClosureExecutionResult,
) -> tuple[CheckResult, ...]:
    target = result.target
    target_value = result.target_value
    if target is None or target_value is None:
        raise SymbolicClosureRuntimeDriftError(
            "quadratic output validation requires target value"
        )
    checks: list[CheckResult] = []
    coefficient_values: dict[sp.Symbol, sp.Expr] = {}
    coefficients = outputs.get("coefficients")
    if coefficients is not None:
        coefficient_values = {
            symbol: sp.sympify(value)
            for symbol, value in dict(coefficients.value).items()
            if isinstance(symbol, sp.Symbol)
        }
        checks.append(
            _closure_check(
                "closure_target_coefficient_matches",
                target in coefficient_values
                and _expressions_equivalent(
                    coefficient_values[target],
                    target_value,
                ),
                "目标系数输出与 symbolic closure 一致",
            )
        )
    parameter_value = outputs.get("parameter_value")
    if parameter_value is not None:
        checks.append(
            _closure_check(
                "closure_parameter_value_matches",
                _expressions_equivalent(
                    parameter_value.value,
                    target_value,
                ),
                "参数值输出与 symbolic closure 一致",
            )
        )
    parabola_value: sp.Expr | None = None
    parabola = outputs.get("parabola")
    if parabola is not None:
        parabola_value = sp.expand(sp.sympify(parabola.value))
        target_coefficient = quadratic_coefficient_expression(
            parabola_value,
            independent_symbol=args["x"],
            target_symbol=target,
            template_expression=args.get("quadratic_template"),
        )
        checks.append(
            _closure_check(
                "closure_parabola_target_matches",
                target_coefficient is not None
                and _expressions_equivalent(
                    target_coefficient,
                    target_value,
                ),
                "抛物线中的目标系数与 symbolic closure 一致",
            )
        )
        for symbol, value in coefficient_values.items():
            represented = quadratic_coefficient_expression(
                parabola_value,
                independent_symbol=args["x"],
                target_symbol=symbol,
                template_expression=args.get("quadratic_template"),
            )
            checks.append(
                _closure_check(
                    f"closure_parabola_coefficient_{symbol.name}_matches",
                    represented is not None
                    and _expressions_equivalent(represented, value),
                    "抛物线与系数输出一致",
                )
            )
        points = [*tuple(args.get("curve_points", ()))]
        for name in ("curve_point", "p1", "p2"):
            if args.get(name) is not None:
                points.append(args[name])
        for index, point in enumerate(points):
            point_x = sp.sympify(point[0]).subs(result.substitution)
            point_y = sp.sympify(point[1]).subs(result.substitution)
            checks.append(
                _closure_check(
                    f"closure_curve_point_{index}_satisfied",
                    _expressions_equivalent(
                        parabola_value.subs(args["x"], point_x),
                        point_y,
                    ),
                    "改写后的抛物线仍满足曲线点约束",
                )
            )
    if "coefficients" in outputs and "parabola" in outputs:
        equation_substitutions = {
            **result.substitution,
            **coefficient_values,
        }
        for index, equation in enumerate(build.equations):
            resolved = equation
            if hasattr(resolved, "subs"):
                resolved = resolved.subs(equation_substitutions)
            passed = resolved is sp.S.true
            if isinstance(resolved, sp.Equality):
                passed = _expressions_equivalent(
                    resolved.lhs,
                    resolved.rhs,
                )
            elif resolved is sp.S.false:
                passed = False
            checks.append(
                _closure_check(
                    f"closure_equation_{index}_satisfied",
                    passed,
                    "改写后的输出仍满足 closure 方程",
                )
            )
    return tuple(checks)


def _closure_check(name: str, passed: bool, detail: str) -> CheckResult:
    return CheckResult(
        name=name,
        status="passed" if bool(passed) else "failed",
        detail=detail,
    )


def _expressions_equivalent(left: Any, right: Any) -> bool:
    try:
        return sp.simplify(sp.sympify(left) - sp.sympify(right)) == 0
    except (TypeError, ValueError, sp.SympifyError):
        return left == right


__all__ = [
    "FunctionalSymbolicClosureMode",
    "SymbolicClosureConfigurationError",
    "SymbolicClosureExecutionResult",
    "SymbolicClosureRegistries",
    "SymbolicClosureRuntimeDriftError",
    "SymbolicConstraintFilterRegistry",
    "SymbolicEquationBuildResult",
    "SymbolicEquationBuilderRegistry",
    "SymbolicOutputSubstitutionRegistry",
    "SymbolicOutputValidatorRegistry",
    "SymbolicRepresentationMapperRegistry",
    "closure_failure_code",
    "default_symbolic_closure_registries",
    "execute_symbolic_closure",
    "substitute_symbolic_closure_output",
    "validate_symbolic_closure_outputs",
    "validate_symbolic_closure_spec",
]
