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
from shuxueshuo_server.solver.runtime.auxiliary_points import (
    fresh_auxiliary_point_handle,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    MethodBindingRuleRegistry,
)
from shuxueshuo_server.solver.runtime.condition_binding_authority import (
    ConditionBindingAuthorityError,
    ConditionBindingAuthorityIndex,
)
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventory
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
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.state_identity import MathObjectRegistry
from shuxueshuo_server.solver.runtime.strategy_models import (
    CreatedEntity,
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
        planner_state_context = initial_planner_state_context(
            PlannerInputs(
                problem_id=problem.problem_id,
                family_spec=family,
                question_goals=question_goals,
                context_inventory=ContextInventory(),
                method_specs=method_specs,
                problem=problem,
                original_text=dict(problem.original_text),
                previous_errors=[],
            ),
            problem_payload=problem_payload,
            handle_registry=handle_registry,
        )
        condition_authority_index = ConditionBindingAuthorityIndex.from_context(
            planner_state_context,
            object_registry=MathObjectRegistry.from_sources(
                handle_registry,
                math_objects=planner_state_context.state.math_objects,
            ),
        )
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
                    condition_authority_index=condition_authority_index,
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
        condition_authority_index: ConditionBindingAuthorityIndex,
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
        exact_inputs: dict[str, str] = {}
        try:
            exact_inputs.update(
                _typed_preflight_exact_inputs(
                    preflight.method_id,
                    trigger=trigger,
                    visible_facts=visible_required_facts,
                    scope_id=scope_id,
                    call=call,
                    index=index,
                    context=context,
                    handle_registry=handle_registry,
                    condition_authority_index=condition_authority_index,
                )
            )
        except (
            ConditionBindingAuthorityError,
            KeyError,
            PathTermParseError,
            PermissionError,
            TypeError,
            ValueError,
        ) as exc:
            return ProblemIRRuntimeReadinessIssue(
                "extraction.problem_ir_runtime_preflight_failed",
                trigger_path,
                _preflight_failure_message(preflight, exc),
                retryable=False,
            )
        try:
            bound_inputs = binding_rules.bind(
                preflight.method_id,
                call,
                index,
                include_expansion_selectors=False,
                exact_inputs=exact_inputs,
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


def _typed_preflight_exact_inputs(
    method_id: str,
    *,
    trigger: Mapping[str, Any],
    visible_facts: tuple[Mapping[str, Any], ...],
    scope_id: str,
    call: FunctionalCapabilityCompileCall,
    index: CanonicalRuntimeBindingIndex,
    context: RuntimeContext,
    handle_registry: CanonicalHandleRegistry,
    condition_authority_index: ConditionBindingAuthorityIndex,
) -> dict[str, str]:
    """Lower migrated preflight inputs from exact typed source authority."""

    if method_id != "weighted_axis_path_triangle_transform":
        return {}
    trigger_handle = str(trigger.get("handle", ""))
    authority = condition_authority_index.resolve_runtime_handle(
        trigger_handle,
        condition_kinds=("minimum_value",),
        scope_id=scope_id,
    )
    fixed, moving, curve = _weighted_preflight_point_roles(
        trigger,
        visible_facts=visible_facts,
        scope_id=scope_id,
        handle_registry=handle_registry,
    )
    moving_path = index.path_for(moving, expected_type="Point")
    dynamic_parameter = _point_dynamic_symbol_path(
        moving_path,
        scope_id=scope_id,
        call=call,
        index=index,
        context=context,
    )
    auxiliary_point_ref = _preflight_output_point_identity(
        output_name="auxiliary_point",
        scope_id=scope_id,
        call=call,
        index=index,
    )
    return {
        "condition": index.path_for(
            authority.runtime_handle,
            expected_type="Condition",
        ),
        "fixed_point": index.path_for(fixed, expected_type="Point"),
        "moving_point": moving_path,
        "moving_point_ref": index.point_identity_path_for(moving),
        "linked_fixed_endpoint_ref": index.point_identity_path_for(curve),
        "dynamic_parameter": dynamic_parameter,
        "auxiliary_point_ref": auxiliary_point_ref,
    }


def _preflight_output_point_identity(
    *,
    output_name: str,
    scope_id: str,
    call: FunctionalCapabilityCompileCall,
    index: CanonicalRuntimeBindingIndex,
) -> str:
    """Allocate an isolated typed output identity for a source-only dry run.

    Extraction preflight intentionally has no FunctionalPlan return allocation.
    Its debug authority adapter therefore allocates a deterministic throwaway
    Point identity and passes it as an exact input. Production compilation must
    instead resolve PreviousOutputIdentityDerivationSpec from the finalized
    FunctionalReturnAllocation.
    """

    handle = fresh_auxiliary_point_handle(
        scope_id,
        set(index.bindings) | set(index.handle_registry.entity_handles),
        prefix=f"Preflight{output_name.title().replace('_', '')}",
    )
    if handle is None:
        raise ValueError(
            f"typed preflight cannot allocate output identity for {output_name!r}"
        )
    index.register_created_entity(
        CreatedEntity(
            handle=handle,
            entity_type="point",
            valid_scope=scope_id,
            description=(
                f"typed extraction preflight identity for {call.step_id}."
                f"{output_name}"
            ),
        )
    )
    return index.path_for(handle, expected_type="PointRef")


def _weighted_preflight_point_roles(
    trigger: Mapping[str, Any],
    *,
    visible_facts: tuple[Mapping[str, Any], ...],
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, str, str]:
    targets = _matching_required_facts(
        "path_minimum_target",
        trigger=trigger,
        visible_facts=visible_facts,
    )
    if len(targets) != 1:
        raise ValueError(
            "typed weighted preflight requires one matching path_minimum_target"
        )
    visible_scopes = set(handle_registry.ancestor_scopes(scope_id))
    point_by_name: dict[str, list[str]] = {}
    for handle, payload in handle_registry.entity_payloads.items():
        if not handle.startswith("point:"):
            continue
        if handle_registry.handle_valid_scopes.get(handle, "problem") not in visible_scopes:
            continue
        name = str(payload.get("name", ""))
        if name:
            point_by_name.setdefault(name, []).append(handle)

    def resolve_point(name: str) -> str:
        candidates = point_by_name.get(name, ())
        if len(candidates) != 1:
            raise PathTermParseError(
                "path_terms.point_unresolved",
                f"weighted path point is not unique in scope: {name}",
            )
        return candidates[0]

    point_names = tuple(sorted(point_by_name))
    display_terms = parse_path_terms(
        trigger,
        point_names=point_names,
        resolve_point=resolve_point,
    )
    target_terms = parse_path_terms(
        targets[0],
        point_names=point_names,
        resolve_point=resolve_point,
    )
    if len(display_terms) != 2 or len(target_terms) != 2:
        raise ValueError("weighted path requires exactly two path terms")
    display_pairs = tuple(
        frozenset((item.start, item.end)) for item in display_terms
    )
    target_pairs = tuple(
        frozenset((item.start, item.end)) for item in target_terms
    )
    if set(display_pairs) != set(target_pairs):
        raise ValueError(
            "minimum_value path roles differ from path_minimum_target authority"
        )
    weighted_indexes = tuple(
        index
        for index, item in enumerate(display_terms)
        if not _unit_scale(item.scale)
    )
    if len(weighted_indexes) != 1:
        raise ValueError("weighted path must have exactly one weighted term")
    weighted_pair = display_pairs[weighted_indexes[0]]
    unit_pair = display_pairs[1 - weighted_indexes[0]]
    shared = tuple(sorted(weighted_pair & unit_pair))
    if len(shared) != 1:
        raise ValueError("weighted path terms must share one moving point")
    moving = shared[0]
    fixed = next(iter(unit_pair - {moving}))
    curve = next(iter(weighted_pair - {moving}))
    return fixed, moving, curve


def _point_dynamic_symbol_path(
    moving_path: str,
    *,
    scope_id: str,
    call: FunctionalCapabilityCompileCall,
    index: CanonicalRuntimeBindingIndex,
    context: RuntimeContext,
) -> str:
    point = context.read_path(
        moving_path,
        from_scope_id=scope_id,
        expected_type="Point",
    ).value
    symbols = {
        str(symbol)
        for coordinate in point
        for symbol in getattr(coordinate, "free_symbols", ())
    }
    if len(symbols) != 1:
        raise ValueError(
            "weighted moving Point must expose one dynamic parameter Symbol"
        )
    symbol_name = next(iter(symbols))
    handles = tuple(
        handle
        for handle in index.entity_handles("symbol", step=call)
        if index.entity_semantic_name(handle) == symbol_name
    )
    if len(handles) != 1:
        raise ValueError(
            "weighted dynamic parameter has no unique canonical Symbol authority"
        )
    return index.path_for(handles[0], expected_type="Symbol")


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
