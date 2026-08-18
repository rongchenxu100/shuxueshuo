"""Cheap runtime-readiness checks for extracted ProblemIR.

The preflight deliberately stops below planning. A family may declare a pure
stateless method whose inputs must bind from source state. We resolve those
inputs through the production binding registry, read them from a forked
RuntimeContext, and discard the method result without committing any writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Any, Mapping

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    MethodBindingRuleRegistry,
)
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.functional_direct_compiler import (
    FunctionalCapabilityCompileCall,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
    method_check_failed,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.path_term_parsing import (
    PathTermParseError,
    parse_path_terms,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_models import (
    StrategyDraftValidationError,
)


@dataclass(frozen=True)
class ProblemIRRuntimeReadinessIssue:
    code: str
    path: str
    message: str
    retryable: bool = True


class ProblemIRRuntimeReadinessValidator:
    """Dry-run family-declared source methods without invoking a planner."""

    def validate(
        self,
        payload: Mapping[str, Any],
        *,
        problem: ProblemIR,
        family: SolverFamilySpec,
        context: RuntimeContext,
    ) -> tuple[ProblemIRRuntimeReadinessIssue, ...]:
        if not family.runtime_preflights:
            return ()
        problem_payload = problem_to_llm_payload(problem)
        handle_registry = CanonicalHandleRegistry.from_problem_payload(
            problem_payload
        )
        question_goals = extract_question_goals(problem)
        method_specs = _method_specs()
        methods = _methods()
        binding_rules = MethodBindingRuleRegistry.from_family_spec(family)

        for preflight in family.runtime_preflights:
            trigger_selector = _TRIGGER_SELECTORS.get(
                preflight.trigger_selector_id
            )
            if trigger_selector is None:
                return (
                    ProblemIRRuntimeReadinessIssue(
                        "extraction.problem_ir_runtime_preflight_failed",
                        "$.problem_type",
                        "runtime preflight trigger selector is not registered: "
                        f"{preflight.trigger_selector_id!r}",
                        retryable=False,
                    ),
                )
            try:
                method_spec = method_specs.require(preflight.method_id)
                method = methods.require(preflight.method_id)
            except KeyError as exc:
                return (
                    ProblemIRRuntimeReadinessIssue(
                        "extraction.problem_ir_runtime_preflight_failed",
                        "$.problem_type",
                        f"runtime preflight contract is incomplete: {exc}",
                        retryable=False,
                    ),
                )
            if not method_spec.is_pure:
                return (
                    ProblemIRRuntimeReadinessIssue(
                        "extraction.problem_ir_runtime_preflight_failed",
                        "$.problem_type",
                        f"runtime preflight method {preflight.method_id!r} must be pure",
                        retryable=False,
                    ),
                )
            unknown_inputs = tuple(
                name
                for name in preflight.source_input_names
                if name not in method_spec.inputs
            )
            if unknown_inputs:
                return (
                    ProblemIRRuntimeReadinessIssue(
                        "extraction.problem_ir_runtime_preflight_failed",
                        "$.problem_type",
                        f"runtime preflight references unknown method inputs: {unknown_inputs}",
                        retryable=False,
                    ),
                )

            trigger_candidates = tuple(
                (index, fact)
                for index, fact in enumerate(payload.get("facts", ()))
                if isinstance(fact, Mapping)
                and str(fact.get("type", "")) in preflight.trigger_fact_types
            )
            triggers = tuple(
                (index, fact)
                for index, fact in trigger_candidates
                if trigger_selector(fact, handle_registry)
            )
            if trigger_candidates and not triggers:
                return (
                    ProblemIRRuntimeReadinessIssue(
                        "extraction.problem_ir_runtime_preflight_failed",
                        "$.problem_type",
                        (
                            f"family {family.family_id!r} declares source runtime preflight "
                            f"{preflight.method_id!r}, but no {list(preflight.trigger_fact_types)} "
                            f"fact matches trigger {preflight.trigger_selector_id!r}. "
                            f"{preflight.description} A relation in a sibling scope cannot make "
                            "an unrelated target satisfy this mechanism."
                        ),
                    ),
                )
            for fact_index, trigger in triggers:
                issue = self._run_one(
                    payload,
                    context=context,
                    handle_registry=handle_registry,
                    question_goals=question_goals,
                    binding_rules=binding_rules,
                    method_spec=method_spec,
                    method=method,
                    preflight=preflight,
                    trigger=trigger,
                    trigger_path=f"$.facts[{fact_index}]",
                )
                if issue is not None:
                    return (issue,)
        return ()

    @staticmethod
    def _run_one(
        payload: Mapping[str, Any],
        *,
        context: RuntimeContext,
        handle_registry: CanonicalHandleRegistry,
        question_goals: list[Any],
        binding_rules: MethodBindingRuleRegistry,
        method_spec: Any,
        method: Any,
        preflight: Any,
        trigger: Mapping[str, Any],
        trigger_path: str,
    ) -> ProblemIRRuntimeReadinessIssue | None:
        scope_id = str(trigger.get("scope_id", ""))
        trigger_handle = str(trigger.get("handle", ""))
        ancestors = set(handle_registry.ancestor_scopes(scope_id))
        visible_required_facts = tuple(
            fact
            for fact in payload.get("facts", ())
            if isinstance(fact, Mapping)
            and str(fact.get("valid_scope", fact.get("scope_id", "problem")))
            in ancestors
        )
        missing_required_facts = tuple(
            fact_type
            for fact_type in preflight.required_fact_types
            if not _matching_required_facts(
                fact_type,
                trigger=trigger,
                visible_facts=visible_required_facts,
            )
        )
        if missing_required_facts:
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                trigger_path,
                (
                    f"family source runtime preflight {preflight.method_id!r} requires "
                    f"visible facts {list(missing_required_facts)!r} in scope {scope_id!r}. "
                    "Declare the source-visible prerequisite in this scope or an ancestor; "
                    "a fact in a sibling scope cannot satisfy the target. "
                    f"{preflight.description}"
                ),
            )
        if preflight.execution_mode == "source_structure_only":
            return _source_structure_preflight_issue(
                trigger,
                trigger_path=trigger_path,
                scope_id=scope_id,
                handle_registry=handle_registry,
                preflight=preflight,
            )
        visible_handles = tuple(
            sorted(
                handle
                for handle in handle_registry.initial_handles
                if handle_registry.handle_valid_scopes.get(handle, "problem")
                in ancestors
                and handle != trigger_handle
            )
        )
        input_handles = (trigger_handle, *visible_handles)
        call = FunctionalCapabilityCompileCall(
            scope_id=scope_id,
            step_id=(
                f"extraction_preflight_{preflight.method_id}_{fact_index_key(trigger_path)}"
            ),
            capability_id=preflight.method_id,
            goal_type="extraction_runtime_preflight",
            target_handle=trigger_handle,
            input_handles=input_handles,
            created_entities=(),
            return_outputs=(),
        )
        index = CanonicalRuntimeBindingIndex.from_context(
            context,
            handle_registry=handle_registry,
            question_goals=question_goals,
        )
        try:
            bound_inputs = binding_rules.bind(
                preflight.method_id,
                call,
                index,
                include_expansion_selectors=False,
                apply_constraint_analyzer=False,
            )
        except StrategyDraftValidationError as exc:
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                trigger_path,
                _preflight_failure_message(preflight, exc),
            )

        runtime_context = context.fork()
        applied_paths: set[str] = set()
        try:
            for declaration in index.declarations.values():
                if declaration.path in applied_paths:
                    continue
                runtime_context.apply_declaration(declaration)
                applied_paths.add(declaration.path)
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                trigger_path,
                _preflight_failure_message(preflight, exc),
                retryable=False,
            )

        for input_name in preflight.source_input_names:
            input_path = bound_inputs.get(input_name)
            if input_path is None:
                return ProblemIRRuntimeReadinessIssue(
                    "extraction.problem_ir_runtime_preflight_failed",
                    trigger_path,
                    f"{preflight.method_id} did not bind required source input {input_name!r}",
                    retryable=False,
                )
            expected_type = method_spec.inputs[input_name].type
            raw_value = None
            try:
                raw_value = runtime_context.read_path(
                    input_path,
                    from_scope_id=scope_id,
                )
                runtime_context.read_path(
                    input_path,
                    from_scope_id=scope_id,
                    expected_type=expected_type,
                )
            except (KeyError, PermissionError, TypeError, ValueError) as exc:
                handle = _handle_for_path(index, input_path)
                if expected_type == "Point" and getattr(
                    raw_value, "type", None
                ) == "PointRef":
                    return ProblemIRRuntimeReadinessIssue(
                        "extraction.problem_ir_state_unmaterialized",
                        _entity_coordinate_path(payload, handle),
                        (
                            f"{preflight.method_id} input {input_name!r} requires a materialized "
                            f"Point, but {handle or input_path} is only an unresolved PointRef. "
                            "When the source prints coordinates such as M(m,0), put them in "
                            "point.coordinate; description, side, x_symbol, and membership facts "
                            f"do not create runtime coordinates. Runtime detail: {exc}"
                        ),
                    )
                return ProblemIRRuntimeReadinessIssue(
                    "extraction.problem_ir_runtime_preflight_failed",
                    _entity_path(payload, handle) if handle else trigger_path,
                    (
                        f"{preflight.method_id} source input {input_name!r} cannot be read as "
                        f"{expected_type}: {exc}"
                    ),
                )

        values: dict[str, Any] = {}
        try:
            for input_name, input_path in bound_inputs.items():
                input_spec = method_spec.inputs.get(input_name)
                if input_spec is None:
                    raise ValueError(
                        f"method input {input_name!r} is absent from MethodSpec"
                    )
                values[input_name] = runtime_context.read_path(
                    input_path,
                    from_scope_id=scope_id,
                    expected_type=input_spec.type,
                ).value
            result = method.run(values, runtime_context.kernel)
        except StatelessMethodError as exc:
            authority = exc.with_context(
                method_id=preflight.method_id,
                capability_id=preflight.method_id,
                scope_id=scope_id,
            ).authority
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                f"{trigger_path}.path",
                _preflight_failure_message(preflight, exc),
                retryable=authority.retryability != "configuration",
            )
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                f"{trigger_path}.path",
                _preflight_failure_message(preflight, exc),
            )
        failed_checks = tuple(
            check.name
            for check in result.checks
            if getattr(check, "status", None) != "passed"
        )
        if failed_checks:
            check_error = method_check_failed(
                tuple(
                    check
                    for check in result.checks
                    if getattr(check, "status", None) != "passed"
                ),
                method_id=preflight.method_id,
            )
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                f"{trigger_path}.path",
                _preflight_failure_message(
                    preflight,
                    check_error,
                ),
                retryable=check_error.retryability != "configuration",
            )
        return None


def _preflight_failure_message(preflight: Any, error: Exception) -> str:
    return (
        f"family source runtime preflight {preflight.method_id!r} cannot execute: "
        f"{error}. {preflight.description} Check the selected family's use_when, "
        "required_source_primitives, and do_not_use_when rules before changing family."
    )


def _source_structure_preflight_issue(
    trigger: Mapping[str, Any],
    *,
    trigger_path: str,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
    preflight: Any,
) -> ProblemIRRuntimeReadinessIssue | None:
    """Validate source syntax without choosing planner-authored roles."""

    if str(trigger.get("type", "")) != "path_minimum_target":
        return None
    visible_scopes = set(handle_registry.ancestor_scopes(scope_id))
    point_names = tuple(
        sorted(
            {
                str(payload.get("name", ""))
                for handle, payload in handle_registry.entity_payloads.items()
                if handle.startswith("point:")
                and handle_registry.handle_valid_scopes.get(handle, "problem")
                in visible_scopes
                and str(payload.get("name", ""))
            }
        )
    )
    try:
        parse_path_terms(
            trigger,
            point_names=point_names,
            resolve_point=lambda name: name,
        )
    except PathTermParseError as exc:
        return ProblemIRRuntimeReadinessIssue(
            "extraction.problem_ir_runtime_preflight_failed",
            f"{trigger_path}.path",
            (
                f"family source structure preflight {preflight.method_id!r} "
                f"cannot parse the path target: {exc}. {preflight.description}"
            ),
        )
    return None


def _handle_for_path(
    index: CanonicalRuntimeBindingIndex,
    runtime_path: str,
) -> str | None:
    candidates = tuple(
        handle
        for handle, binding in index.bindings.items()
        if binding.path == runtime_path and handle.startswith("point:")
    )
    return sorted(candidates)[0] if candidates else None


def _entity_path(payload: Mapping[str, Any], handle: str | None) -> str:
    for index, entity in enumerate(payload.get("entities", ())):
        if isinstance(entity, Mapping) and entity.get("handle") == handle:
            return f"$.entities[{index}]"
    return "$.entities"


def _entity_coordinate_path(
    payload: Mapping[str, Any],
    handle: str | None,
) -> str:
    return f"{_entity_path(payload, handle)}.coordinate"


def fact_index_key(path: str) -> str:
    return path.removeprefix("$.facts[").removesuffix("]")


def _matching_required_facts(
    fact_type: str,
    *,
    trigger: Mapping[str, Any],
    visible_facts: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    matches = tuple(
        fact for fact in visible_facts if str(fact.get("type", "")) == fact_type
    )
    if fact_type != "path_minimum_target" or trigger.get("path") is None:
        return matches
    trigger_path = _normalized_path(str(trigger["path"]))
    return tuple(
        fact
        for fact in matches
        if _normalized_path(str(fact.get("path", ""))) == trigger_path
    )


def _normalized_path(value: str) -> str:
    return "".join(value.split())


def _all_trigger(
    fact: Mapping[str, Any],
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    del fact, handle_registry
    return True


def _weighted_path_minimum_trigger(
    fact: Mapping[str, Any],
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    scope_id = str(fact.get("scope_id", ""))
    visible_scopes = set(handle_registry.ancestor_scopes(scope_id))
    point_names = tuple(
        sorted(
            {
                str(payload.get("name", ""))
                for handle, payload in handle_registry.entity_payloads.items()
                if handle.startswith("point:")
                and handle_registry.handle_valid_scopes.get(handle, "problem")
                in visible_scopes
                and str(payload.get("name", ""))
            }
        )
    )
    try:
        terms = parse_path_terms(
            fact,
            point_names=point_names,
            resolve_point=lambda name: name,
        )
    except PathTermParseError:
        return bool(
            re.search(
                r"(?:^|\+)\s*(?:sqrt\s*\([^)]*\)|\d+(?:\.\d+)?)\s*\*?\s*[A-Za-z]",
                str(fact.get("path", "")),
            )
        )
    return any(not _unit_scale(term.scale) for term in terms)


def _unit_scale(value: str) -> bool:
    compact = "".join(value.split())
    return compact in {"1", "1.0", "(1)"}


_TRIGGER_SELECTORS = {
    "all": _all_trigger,
    "weighted_path_minimum": _weighted_path_minimum_trigger,
}


@lru_cache(maxsize=1)
def _method_specs() -> MethodSpecRegistry:
    return MethodSpecRegistry.load_from_code()


@lru_cache(maxsize=1)
def _methods() -> Any:
    return default_stateless_registry()


__all__ = [
    "ProblemIRRuntimeReadinessIssue",
    "ProblemIRRuntimeReadinessValidator",
]
