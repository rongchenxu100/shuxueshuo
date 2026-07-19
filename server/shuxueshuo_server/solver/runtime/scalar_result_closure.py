"""Deterministic closure of symbolic scalar results.

FunctionalPlan may mark a dual-form scalar return as ``closed_value``.  This
module discovers a compatible pure closure function from FunctionSpec type
signatures and appends the required substitutions to an existing StepPlan.
It never dispatches on the producer capability id or guesses variable names.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionArgSpec,
    FunctionReturnSpec,
    FunctionSpec,
    FunctionSpecRegistry,
)
from shuxueshuo_server.solver.runtime.models import MethodInvocation, StepPlan
from shuxueshuo_server.solver.runtime.strategy_models import (
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import split_runtime_types


@dataclass(frozen=True)
class ScalarClosureFunction:
    """A pure typed function capable of removing one known Symbol."""

    function_id: str
    method_id: str
    value_input: str
    symbol_input: str
    parameter_value_input: str
    output_name: str
    runtime_type: str


class ScalarResultClosureRegistry:
    """Discover scalar closure functions from the effective FunctionSpec set."""

    def __init__(self, functions: FunctionSpecRegistry) -> None:
        self.functions = functions

    def require(self, runtime_type: str) -> ScalarClosureFunction:
        candidates = tuple(
            binding
            for function in self.functions.specs.values()
            if (binding := _closure_binding(function, runtime_type)) is not None
        )
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise StrategyDraftValidationError(
                "planner_configuration_error: scalar closure function missing: "
                f"runtime_type={runtime_type}"
            )
        raise StrategyDraftValidationError(
            "planner_configuration_error: scalar closure function ambiguous: "
            f"runtime_type={runtime_type}, "
            f"functions={[item.function_id for item in candidates]}"
        )


def close_scalar_plan_output(
    plan: StepPlan,
    *,
    target_path: str,
    runtime_type: str,
    parameter_pairs: Sequence[tuple[str, str]],
    registry: ScalarResultClosureRegistry,
    return_name: str,
) -> StepPlan:
    """Append read-closed substitutions before promoting one scalar output."""
    if not parameter_pairs:
        return plan
    sources = tuple(
        source
        for source, target in plan.promote_outputs.items()
        if target == target_path
    )
    if len(sources) != 1:
        raise StrategyDraftValidationError(
            "planner_configuration_error: scalar closure target must have one "
            f"promotion source: target={target_path}, sources={list(sources)}"
        )
    closure = registry.require(runtime_type)
    original_source = sources[0]
    current_source = original_source
    invocations = list(plan.invocations)
    applied = 0
    for symbol_path, value_path in parameter_pairs:
        if _source_already_applies_pair(
            invocations,
            source=current_source,
            closure=closure,
            symbol_path=symbol_path,
            value_path=value_path,
        ):
            continue
        applied += 1
        output_path = (
            f"$step.{plan.step_id}.temp."
            f"closed_{_safe_name(return_name)}_{applied}"
        )
        invocations.append(
            MethodInvocation(
                invocation_id=f"{plan.step_id}.scalar_closure.{applied}",
                method_id=closure.method_id,
                scope=plan.step_id,
                inputs={
                    closure.value_input: current_source,
                    closure.symbol_input: symbol_path,
                    closure.parameter_value_input: value_path,
                },
                outputs={closure.output_name: output_path},
            )
        )
        current_source = output_path
    if current_source == original_source:
        return plan
    promote = dict(plan.promote_outputs)
    del promote[original_source]
    promote[current_source] = target_path
    return replace(
        plan,
        invocations=invocations,
        promote_outputs=promote,
    )


def _closure_binding(
    function: FunctionSpec,
    runtime_type: str,
) -> ScalarClosureFunction | None:
    if not function.is_pure:
        return None
    value_args = tuple(
        arg
        for arg in function.args
        if arg.required
        and runtime_type in split_runtime_types(arg.runtime_type)
        and runtime_type not in {"Symbol", "ParameterValue"}
    )
    symbol_args = _exact_args(function.args, "Symbol")
    parameter_value_args = _exact_args(function.args, "ParameterValue")
    returns = tuple(
        result
        for result in function.returns
        if result.runtime_type == runtime_type
        and result.scalar_result_form is not None
        and result.scalar_result_form.closure_policy == "no_free_symbols"
        and "closed_value" in result.scalar_result_form.possible_forms
    )
    if not (
        len(value_args) == 1
        and len(symbol_args) == 1
        and len(parameter_value_args) == 1
        and len(returns) == 1
    ):
        return None
    value_arg = value_args[0]
    symbol_arg = symbol_args[0]
    parameter_value_arg = parameter_value_args[0]
    result = returns[0]
    return ScalarClosureFunction(
        function_id=function.function_id,
        method_id=function.method_id,
        value_input=_method_input_name(value_arg),
        symbol_input=_method_input_name(symbol_arg),
        parameter_value_input=_method_input_name(parameter_value_arg),
        output_name=_output_name(result),
        runtime_type=runtime_type,
    )


def _exact_args(
    args: tuple[FunctionArgSpec, ...],
    runtime_type: str,
) -> tuple[FunctionArgSpec, ...]:
    return tuple(
        arg
        for arg in args
        if arg.required and split_runtime_types(arg.runtime_type) == (runtime_type,)
    )


def _method_input_name(arg: FunctionArgSpec) -> str:
    return arg.method_input or arg.name


def _output_name(result: FunctionReturnSpec) -> str:
    return result.output_key or result.name


def _source_already_applies_pair(
    invocations: Sequence[MethodInvocation],
    *,
    source: str,
    closure: ScalarClosureFunction,
    symbol_path: str,
    value_path: str,
) -> bool:
    return any(
        invocation.method_id == closure.method_id
        and invocation.outputs.get(closure.output_name) == source
        and invocation.inputs.get(closure.symbol_input) == symbol_path
        and invocation.inputs.get(closure.parameter_value_input) == value_path
        for invocation in invocations
    )


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


__all__ = [
    "ScalarClosureFunction",
    "ScalarResultClosureRegistry",
    "close_scalar_plan_output",
]
