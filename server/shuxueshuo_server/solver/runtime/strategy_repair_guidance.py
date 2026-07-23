"""Contract-driven, conservative method guidance for planner retry tickets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.strategy_models import StepIntent, StepIntentDraft


@dataclass(frozen=True)
class RepairMethodGuidance:
    """A method suggestion emitted only after a unique contract preflight."""

    capability_id: str
    missing_runtime_type: str

    def to_payload(self) -> dict[str, str]:
        return {
            "capability_id": self.capability_id,
            "missing_runtime_type": self.missing_runtime_type,
            "status": "unique_applicable_candidate",
        }


class RepairGuidanceResolver:
    """Find one applicable producer without prescribing a method chain."""

    def __init__(
        self,
        family_spec: SolverFamilySpec,
        method_specs: MethodSpecRegistry,
        handle_registry: CanonicalHandleRegistry,
    ) -> None:
        self.functions = FunctionSpecRegistry.from_family_spec(
            family_spec,
            method_specs,
        )
        self.handle_registry = handle_registry

    def resolve(
        self,
        *,
        missing_runtime_type: str | None,
        step: StepIntent | None,
        draft: StepIntentDraft | None,
    ) -> RepairMethodGuidance | None:
        if missing_runtime_type is None or step is None:
            return None
        available = _available_runtime_types(
            step,
            draft=draft,
            handle_registry=self.handle_registry,
        )
        candidates = []
        for function in self.functions.specs.values():
            matching_returns = [
                item
                for item in function.returns
                if missing_runtime_type in _split_types(item.runtime_type)
            ]
            if not matching_returns:
                continue
            if not _args_are_available(function.args, available, step):
                continue
            if any(item.write_mode == "transition" for item in matching_returns):
                # A transition recommendation requires identity lineage. The
                # lightweight retry preflight cannot prove transitive object
                # identity from type availability alone, so it stays silent.
                continue
            candidates.append(function.method_id)
        candidates = list(dict.fromkeys(candidates))
        if len(candidates) != 1:
            return None
        return RepairMethodGuidance(candidates[0], missing_runtime_type)


def _available_runtime_types(
    step: StepIntent,
    *,
    draft: StepIntentDraft | None,
    handle_registry: CanonicalHandleRegistry,
) -> set[str]:
    produced = {
        item.handle: item.output_type
        for current in (draft.steps if draft is not None else ())
        for item in current.produces
        if item.output_type is not None
    }
    result: set[str] = set()
    for handle in step.reads:
        if handle in produced:
            result.update(_split_types(str(produced[handle])))
            continue
        if handle.startswith("point:"):
            result.update({"Point", "PointRef"})
        elif handle.startswith("symbol:"):
            result.add("Symbol")
        elif handle in handle_registry.answer_value_types:
            result.add(handle_registry.answer_value_types[handle])
        elif handle in handle_registry.fact_types:
            result.add("Condition")
    return result


def _args_are_available(
    args: tuple[Any, ...],
    available: set[str],
    step: StepIntent,
) -> bool:
    for arg in args:
        if not arg.required or arg.kind in {"auto", "symbol"}:
            continue
        if arg.kind == "point_ref":
            if step.target or {"Point", "PointRef"} & available:
                continue
            return False
        required_types = _split_types(arg.runtime_type)
        if required_types & available:
            continue
        if arg.kind == "condition_read" and "Condition" in available:
            continue
        return False
    return True


def _split_types(value: str) -> set[str]:
    return set(split_runtime_types(value))


__all__ = ["RepairGuidanceResolver", "RepairMethodGuidance"]
