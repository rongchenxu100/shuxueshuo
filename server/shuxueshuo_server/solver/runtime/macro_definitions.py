"""Registry-owned transparent Macro definitions and Function fragments."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from shuxueshuo_server.solver.contracts import MacroSearchSpec
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
    EqualLengthRayRoleCandidate,
    EqualLengthRayRoleError,
    build_equal_length_ray_role_candidates,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateSelectionSpec,
    FunctionalPlanFragment,
    SearchCandidate,
)
from shuxueshuo_server.solver.runtime.macro_blueprints import (
    EQUAL_LENGTH_RAY_PATH_BLUEPRINT,
    MacroSemanticBlueprint,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedDerivedResultRef,
    ScopedFunctionalStep,
    ScopedReturnBinding,
    ScopedStepResultRef,
)


@dataclass(frozen=True)
class MacroExpansionRequest:
    macro_id: str
    call_id: str
    scope_id: str
    authored_roles: Mapping[str, str]
    builder_context: Mapping[str, Any]
    max_candidates: int

    def __post_init__(self) -> None:
        if not self.macro_id or not self.call_id or not self.scope_id:
            raise ValueError("planner.macro_contract_invalid: incomplete expansion request")
        if self.max_candidates <= 0:
            raise ValueError("planner.macro_contract_invalid: invalid candidate budget")
        object.__setattr__(
            self,
            "authored_roles",
            MappingProxyType(dict(sorted(self.authored_roles.items()))),
        )
        object.__setattr__(
            self,
            "builder_context",
            MappingProxyType(dict(self.builder_context)),
        )


MacroFragmentExpander = Callable[[MacroExpansionRequest], Sequence[SearchCandidate]]
MacroRoleProjector = Callable[
    [Mapping[str, Any], int], Sequence[Mapping[str, str]]
]
MacroPreparationContextBuilder = Callable[[Any], "MacroDefinitionPreparationContext"]


class MacroDefinitionError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class MacroDefinitionPreparationContext:
    """Definition-owned candidate inputs and scope-safe dependency envelope."""

    payload: Any
    candidate_dependency_envelope: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_dependency_envelope",
            tuple(sorted(set(self.candidate_dependency_envelope))),
        )


@dataclass(frozen=True)
class MacroDefinition:
    macro_id: str
    implementation_id: str
    blueprint: MacroSemanticBlueprint
    search_contract: MacroSearchSpec
    preparation_context_builder: MacroPreparationContextBuilder
    expander: MacroFragmentExpander
    selection: CandidateSelectionSpec
    export_names: tuple[str, ...]
    role_projector: MacroRoleProjector | None = None

    def __post_init__(self) -> None:
        if not self.macro_id or not self.implementation_id:
            raise ValueError("planner.macro_contract_invalid: incomplete Macro definition")
        if self.blueprint.macro_id != self.macro_id:
            raise ValueError("planner.macro_contract_invalid: blueprint Macro drift")
        if not self.export_names or len(self.export_names) != len(
            set(self.export_names)
        ):
            raise ValueError(
                "planner.macro_contract_invalid: Macro exports must be unique"
            )
        if (
            self.selection.output_name is not None
            and self.selection.output_name not in self.export_names
        ):
            raise ValueError(
                "planner.macro_contract_invalid: selection output is not exported"
            )

    def accepts_search_contract(self, search_spec: MacroSearchSpec) -> bool:
        expected = self.search_contract.to_payload()
        observed = search_spec.to_payload()
        expected.pop("max_candidates", None)
        observed.pop("max_candidates", None)
        return (
            expected == observed
            and search_spec.max_candidates <= self.search_contract.max_candidates
        )

    @property
    def authority_signature(self) -> str:
        """Identify the sole executable semantics behind catalog projections."""

        return stable_hash(
            {
                "macro_id": self.macro_id,
                "implementation_id": self.implementation_id,
                "blueprint": self.blueprint.authority_payload(),
                "search_contract": self.search_contract.to_payload(),
                "selection": self.selection.to_payload(),
                "export_names": list(self.export_names),
                "has_role_projector": self.role_projector is not None,
            }
        )


class MacroDefinitionRegistry:
    """Single owner for transparent Macro semantics and fragment expansion."""

    def __init__(self, definitions: Iterable[MacroDefinition] = ()) -> None:
        self._definitions: dict[str, MacroDefinition] = {}
        for definition in definitions:
            if definition.macro_id in self._definitions:
                raise ValueError(f"duplicate Macro definition {definition.macro_id}")
            self._definitions[definition.macro_id] = definition

    def require(self, macro_id: str) -> MacroDefinition:
        try:
            return self._definitions[macro_id]
        except KeyError as exc:
            raise ValueError(
                "planner.macro_contract_invalid: runtime-search Macro has no "
                f"transparent definition: {macro_id}"
            ) from exc

    def require_catalog_contract(
        self,
        macro_id: str,
        search_spec: MacroSearchSpec,
        *,
        execution_strategy: str,
        internal_call_ids: Sequence[str],
        export_names: Sequence[str],
    ) -> MacroDefinition:
        """Audit catalog metadata against the one executable Definition."""

        definition = self.require(macro_id)
        if not definition.accepts_search_contract(search_spec):
            raise ValueError(
                "planner.macro_contract_invalid: Macro catalog search contract "
                f"differs from its Definition for {macro_id}"
            )
        if (
            execution_strategy != "functional_plan_fragment"
            or tuple(internal_call_ids)
            or tuple(export_names) != definition.export_names
        ):
            raise ValueError(
                "planner.macro_contract_invalid: Macro catalog execution "
                f"envelope differs from its Definition for {macro_id}"
            )
        return definition

    def project_role_bindings(
        self,
        macro_id: str,
        *,
        builder_context: Mapping[str, Any],
        max_candidates: int,
    ) -> tuple[Mapping[str, str], ...]:
        definition = self.require(macro_id)
        if definition.role_projector is None:
            return ()
        return tuple(
            MappingProxyType(dict(sorted(item.items())))
            for item in definition.role_projector(
                builder_context,
                max_candidates,
            )
        )

    @property
    def macro_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))


@lru_cache(maxsize=1)
def default_macro_definition_registry() -> MacroDefinitionRegistry:
    # Imported lazily to keep the generic preparation request independent from
    # the concrete execution environment while retaining one Definition object.
    from shuxueshuo_server.solver.runtime.macro_preparation import (
        _build_equal_length_ray_preparation_context,
    )

    search_contract = MacroSearchSpec(
        searchable_roles=("anchor", "reference_point", "ray_point", "fixed_point"),
        candidate_builder_id="equal_length_ray_role_assignments",
        validation_policy_id="verified_function_fragment",
        lowerer_id="functional_plan_fragment",
        postcondition_id="predicate_publication",
        evidence_builder_id="verified_subplan_execution",
        max_candidates=32,
    )
    return MacroDefinitionRegistry(
        (
            MacroDefinition(
                macro_id="equal_length_ray_path_reduction",
                implementation_id="equal-length-ray-transparent/v1",
                blueprint=EQUAL_LENGTH_RAY_PATH_BLUEPRINT,
                search_contract=search_contract,
                preparation_context_builder=(
                    _build_equal_length_ray_preparation_context
                ),
                expander=_expand_equal_length_ray_path,
                selection=CandidateSelectionSpec(
                    "minimize",
                    "minimum_expression",
                ),
                export_names=("minimum_expression",),
                role_projector=_project_equal_length_ray_roles,
            ),
        )
    )


def build_point_name_candidates(
    *,
    point_handles: Iterable[str],
    entity_payloads: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, tuple[str, ...]]:
    """Preserve every visible identity behind a student-facing label."""

    by_name: dict[str, set[str]] = {}
    for handle in point_handles:
        payload = entity_payloads.get(handle, {})
        name = str(payload.get("name", "")).strip() or handle.rsplit(":", 1)[-1]
        by_name.setdefault(name, set()).add(handle)
    return MappingProxyType(
        {
            name: tuple(sorted(handles))
            for name, handles in sorted(by_name.items())
        }
    )


def _expand_equal_length_ray_path(
    request: MacroExpansionRequest,
) -> tuple[SearchCandidate, ...]:
    context = request.builder_context
    source_refs = {
        str(key): str(value)
        for key, value in _required_mapping(
            context.get("source_refs_by_handle"),
            "source_refs_by_handle",
        ).items()
    }
    strategy_ids = (
        "direct_intersection",
        "reflection_straightening",
        "segment_endpoint_0",
        "segment_endpoint_1",
    )
    domain_facts = _fact_group(context, "domain_facts")
    domain_handles: tuple[str | None, ...] = (
        tuple(handle for handle, _payload in domain_facts) or (None,)
    )
    role_budget = max(
        1,
        request.max_candidates
        // (len(strategy_ids) * len(domain_handles)),
    )
    role_candidates = _equal_length_ray_role_candidates(
        context,
        max_candidates=role_budget,
    )
    fact_payloads = {
        handle: payload
        for group in (
            "ray_facts",
            "segment_facts",
            "equal_facts",
            "target_facts",
            "domain_facts",
        )
        for handle, payload in _fact_group(context, group)
    }

    result: list[SearchCandidate] = []
    for role_candidate in role_candidates:
        roles = role_candidate.roles.to_payload()
        fact_handles = dict(role_candidate.fact_handles)
        moving_point_handles = {
            str(fact_payloads[fact_handles[fact_role]]["point"])
            for fact_role in ("point_on_segment", "point_on_ray")
        }
        for domain_handle in domain_handles:
            dependencies = tuple(
                sorted(
                    {
                        *roles.values(),
                        *fact_handles.values(),
                        *moving_point_handles,
                        *((domain_handle,) if domain_handle is not None else ()),
                    }
                )
            )
            for strategy_id in strategy_ids:
                fragment = _equal_length_fragment(
                    call_id=request.call_id,
                    scope_id=request.scope_id,
                    role_handles=roles,
                    fact_handles=fact_handles,
                    fact_payloads=fact_payloads,
                    source_refs=source_refs,
                    strategy_id=strategy_id,
                    domain_condition_handle=domain_handle,
                    dependency_envelope=dependencies,
                )
                candidate_id = stable_hash(
                    {
                        "macro_id": request.macro_id,
                        "roles": roles,
                        "strategy_id": strategy_id,
                        "domain_condition": domain_handle,
                        "fragment": fragment.fragment_signature,
                    }
                )
                result.append(
                    SearchCandidate(
                        candidate_id=candidate_id,
                        fragment=fragment,
                        role_bindings=roles,
                        strategy_id=strategy_id,
                        symbolic_complexity={
                            "direct_intersection": 0,
                            "segment_endpoint_0": 1,
                            "segment_endpoint_1": 1,
                            "reflection_straightening": 2,
                        }[strategy_id],
                    )
                )
    if len(result) > request.max_candidates:
        raise ValueError(
            "functional.macro_search_budget_exceeded: transparent expansion "
            f"produced {len(result)} candidates for budget {request.max_candidates}"
        )
    return tuple(result)


def _project_equal_length_ray_roles(
    context: Mapping[str, Any],
    max_candidates: int,
) -> tuple[Mapping[str, str], ...]:
    return tuple(
        MappingProxyType(item.roles.to_payload())
        for item in _equal_length_ray_role_candidates(
            context,
            max_candidates=max_candidates,
        )
    )


def _equal_length_ray_role_candidates(
    context: Mapping[str, Any],
    *,
    max_candidates: int,
) -> tuple[EqualLengthRayRoleCandidate, ...]:
    entity_payloads = _required_mapping(
        context.get("entity_payloads"),
        "entity_payloads",
    )
    point_names = _point_name_candidates(context.get("point_name_candidates"))

    def resolve_point_name(name: str) -> str:
        matches = point_names.get(name, ())
        if len(matches) == 1:
            return matches[0]
        code = "point_name_unresolved" if not matches else "point_name_ambiguous"
        raise EqualLengthRayRoleError(
            code,
            "structured role point name is not uniquely visible",
            details={
                "name": name,
                "candidate_count": len(matches),
                "candidates": matches,
            },
        )

    try:
        return tuple(
            build_equal_length_ray_role_candidates(
                ray_facts=_fact_group(context, "ray_facts"),
                segment_facts=_fact_group(context, "segment_facts"),
                equal_facts=_fact_group(context, "equal_facts"),
                target_facts=_fact_group(context, "target_facts"),
                entity_payload=lambda handle: entity_payloads[handle],
                visible_point_handles=tuple(
                    handle
                    for handles in point_names.values()
                    for handle in handles
                ),
                resolve_point_name=resolve_point_name,
                max_candidates=max_candidates,
            )
        )
    except EqualLengthRayRoleError as exc:
        code = {
            "point_name_ambiguous": "planner.macro_point_name_ambiguous",
            "point_name_unresolved": "planner.macro_point_name_unresolved",
        }.get(exc.code, "planner.macro_contract_invalid")
        raise MacroDefinitionError(
            code,
            str(exc),
            retryable=False,
            details=exc.details,
        ) from exc


def _equal_length_fragment(
    *,
    call_id: str,
    scope_id: str,
    role_handles: Mapping[str, str],
    fact_handles: Mapping[str, str],
    fact_payloads: Mapping[str, Mapping[str, Any]],
    source_refs: Mapping[str, str],
    strategy_id: str,
    domain_condition_handle: str | None,
    dependency_envelope: tuple[str, ...],
) -> FunctionalPlanFragment:
    role_ref = {key: _source_ref(value, source_refs) for key, value in role_handles.items()}
    segment_moving = _source_ref(
        str(fact_payloads[fact_handles["point_on_segment"]]["point"]),
        source_refs,
    )
    ray_moving = _source_ref(
        str(fact_payloads[fact_handles["point_on_ray"]]["point"]),
        source_refs,
    )
    prefix = f"{call_id}__{stable_hash({'roles': dict(role_handles), 'strategy': strategy_id})[:10]}"
    steps: list[ScopedFunctionalStep] = []

    def add_step(
        suffix: str,
        capability_id: str,
        args: Mapping[str, Any],
        *,
        derived: Mapping[str, tuple[str, str, str]] = MappingProxyType({}),
    ) -> tuple[ScopedFunctionalStep, Mapping[str, ScopedDerivedResultRef]]:
        step_id = f"{prefix}__{suffix}"
        bindings = {
            return_name: ScopedReturnBinding(kind="derived", ref=local_ref)
            for return_name, (local_ref, _domain_type, _semantic_role) in derived.items()
        }
        step = ScopedFunctionalStep(
            step_id=step_id,
            capability_id=capability_id,
            args={
                name: tuple(value) if isinstance(value, (tuple, list)) else (value,)
                for name, value in args.items()
            },
            return_bindings=bindings,
            return_expectations={},
            intent=None,
        )
        refs = {
            return_name: ScopedDerivedResultRef(
                step_id=step_id,
                return_name=return_name,
                local_ref=local_ref,
                canonical_ref=f"{scope_id}::{local_ref}",
                domain_type=domain_type,
                semantic_role=semantic_role,
                owner_scope=scope_id,
            )
            for return_name, (local_ref, domain_type, semantic_role) in derived.items()
        }
        steps.append(step)
        return step, MappingProxyType(refs)

    construct, construct_refs = add_step(
        "construct_auxiliary",
        "construct_point_on_ray_at_reference_distance",
        {
            "anchor": role_ref["anchor"],
            "ray_point": role_ref["ray_point"],
            "reference_point": role_ref["reference_point"],
        },
        derived={"point": (f"{prefix}.auxiliary_point", "Point", "auxiliary_point")},
    )
    auxiliary = construct_refs["point"]
    _ray_check, ray_check_refs = add_step(
        "verify_auxiliary_ray",
        "verify_point_on_ray",
        {
            "point": auxiliary,
            "anchor": role_ref["anchor"],
            "ray_point": role_ref["ray_point"],
        },
        derived={"point_on_ray": (f"{prefix}.point_on_ray", "Condition", "point_on_ray")},
    )
    _distance_check, distance_check_refs = add_step(
        "verify_auxiliary_distance",
        "verify_distance_equality",
        {
            "first_start": role_ref["anchor"],
            "first_end": auxiliary,
            "second_start": role_ref["anchor"],
            "second_end": role_ref["reference_point"],
        },
        derived={
            "distance_equality": (
                f"{prefix}.distance_equality",
                "Condition",
                "distance_equality",
            )
        },
    )
    add_step(
        "prove_path_replacement",
        "prove_distance_equality_from_conditions",
        {
            "equal_length_condition": _source_ref(
                fact_handles["equal_length_condition"], source_refs
            ),
            "linking_condition": _source_ref(
                fact_handles["point_on_segment"], source_refs
            ),
            "ray_membership_condition": _source_ref(
                fact_handles["point_on_ray"], source_refs
            ),
            "constructed_equal_length_condition": distance_check_refs[
                "distance_equality"
            ],
            "constructed_ray_condition": ray_check_refs["point_on_ray"],
            "common_vertex": role_ref["anchor"],
            "first_start": role_ref["reference_point"],
            "first_end": ray_moving,
            "second_start": segment_moving,
            "second_end": auxiliary,
        },
        derived={
            "distance_equality": (
                f"{prefix}.path_replacement",
                "Condition",
                "distance_equality",
            )
        },
    )

    segment_start = role_ref["anchor"]
    segment_end = role_ref["reference_point"]
    fixed = role_ref["fixed_point"]
    candidate_result: ScopedStepResultRef
    candidate_point: Any
    if strategy_id == "reflection_straightening":
        _reflect, reflect_refs = add_step(
            "reflect_fixed",
            "reflect_point_across_line",
            {"point": fixed, "line_p1": segment_start, "line_p2": segment_end},
            derived={
                "reflected_point": (
                    f"{prefix}.reflected_point",
                    "Point",
                    "reflected_point",
                )
            },
        )
        reflected = reflect_refs["reflected_point"]
        intersection = _add_intersection(
            add_step,
            prefix=prefix,
            first_start=reflected,
            first_end=auxiliary,
            segment_start=segment_start,
            segment_end=segment_end,
        )
        verification_args: dict[str, Any] = {
            "point": intersection,
            "segment_start": segment_start,
            "segment_end": segment_end,
        }
        if domain_condition_handle is not None:
            verification_args["domain_condition"] = _source_ref(
                domain_condition_handle,
                source_refs,
            )
        add_step(
            "verify_intersection",
            "verify_point_on_closed_segment",
            verification_args,
            derived={
                "point_on_segment": (
                    f"{prefix}.point_on_segment",
                    "Condition",
                    "point_on_segment",
                )
            },
        )
        objective, _ = add_step(
            "original_path",
            "distance_sum_expression",
            {"start": fixed, "via": intersection, "end": auxiliary},
        )
        candidate_step, _ = add_step(
            "straightened_distance",
            "distance_between_points",
            {"p1": reflected, "p2": auxiliary},
        )
        candidate_result = ScopedStepResultRef(candidate_step.step_id, "distance")
        objective_result = ScopedStepResultRef(objective.step_id, "expression")
        candidate_point = intersection
    elif strategy_id == "direct_intersection":
        intersection = _add_intersection(
            add_step,
            prefix=prefix,
            first_start=fixed,
            first_end=auxiliary,
            segment_start=segment_start,
            segment_end=segment_end,
        )
        verification_args = {
            "point": intersection,
            "segment_start": segment_start,
            "segment_end": segment_end,
        }
        if domain_condition_handle is not None:
            verification_args["domain_condition"] = _source_ref(
                domain_condition_handle,
                source_refs,
            )
        add_step(
            "verify_intersection",
            "verify_point_on_closed_segment",
            verification_args,
            derived={
                "point_on_segment": (
                    f"{prefix}.point_on_segment",
                    "Condition",
                    "point_on_segment",
                )
            },
        )
        objective, _ = add_step(
            "original_path",
            "distance_sum_expression",
            {"start": fixed, "via": intersection, "end": auxiliary},
        )
        candidate_step, _ = add_step(
            "straightened_distance",
            "distance_between_points",
            {"p1": fixed, "p2": auxiliary},
        )
        candidate_result = ScopedStepResultRef(candidate_step.step_id, "distance")
        objective_result = ScopedStepResultRef(objective.step_id, "expression")
        candidate_point = intersection
    else:
        endpoint = segment_start if strategy_id.endswith("_0") else segment_end
        candidate_step, _ = add_step(
            "endpoint_path",
            "distance_sum_expression",
            {"start": fixed, "via": endpoint, "end": auxiliary},
        )
        candidate_result = ScopedStepResultRef(candidate_step.step_id, "expression")
        objective_result = candidate_result
        candidate_point = endpoint

    attainment_args: dict[str, Any] = {
        "objective": objective_result,
        "candidate": candidate_result,
        "candidate_point": candidate_point,
        "path_start": fixed,
        "path_end": auxiliary,
        "segment_start": segment_start,
        "segment_end": segment_end,
    }
    if domain_condition_handle is not None:
        attainment_args["domain_condition"] = _source_ref(
            domain_condition_handle,
            source_refs,
        )
    add_step(
        "verify_attainment",
        "verify_two_segment_path_attainment",
        attainment_args,
        derived={
            "path_attainment": (
                f"{prefix}.path_attainment",
                "Condition",
                "path_minimum_attained",
            )
        },
    )
    return FunctionalPlanFragment(
        source="macro",
        scope_id=scope_id,
        steps=tuple(steps),
        exports={
            "minimum_expression": (
                candidate_result.step_id,
                candidate_result.return_name,
            )
        },
        dependency_envelope=dependency_envelope,
        blueprint_id=EQUAL_LENGTH_RAY_PATH_BLUEPRINT.blueprint_version,
    )


def _add_intersection(
    add_step: Callable[..., tuple[ScopedFunctionalStep, Mapping[str, ScopedDerivedResultRef]]],
    *,
    prefix: str,
    first_start: Any,
    first_end: Any,
    segment_start: Any,
    segment_end: Any,
) -> ScopedDerivedResultRef:
    _step, refs = add_step(
        "intersection",
        "line_intersection_point",
        {
            "line1_p1": first_start,
            "line1_p2": first_end,
            "line2_p1": segment_start,
            "line2_p2": segment_end,
        },
        derived={
            "intersection": (
                f"{prefix}.intersection",
                "Point",
                "intersection",
            )
        },
    )
    return refs["intersection"]


def _source_ref(handle: str, source_refs: Mapping[str, str]) -> str:
    ref = source_refs.get(handle)
    if ref is None:
        raise ValueError(
            "planner.macro_contract_invalid: no scope-visible SourceRef for "
            f"{handle}"
        )
    return ref


def _point_name_candidates(value: Any) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise ValueError("planner.macro_contract_invalid: missing point-name authority")
    result: dict[str, tuple[str, ...]] = {}
    for name, raw_handles in value.items():
        if not isinstance(name, str) or not isinstance(raw_handles, Sequence) or isinstance(raw_handles, (str, bytes)):
            raise ValueError("planner.macro_contract_invalid: invalid point-name authority")
        handles = tuple(sorted({str(item) for item in raw_handles if item}))
        if not handles or len(handles) != len(raw_handles):
            raise ValueError("planner.macro_contract_invalid: invalid point-name candidates")
        result[name] = handles
    return MappingProxyType(result)


def _fact_group(
    context: Mapping[str, Any],
    name: str,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    value = context.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        (str(item[0]), item[1])
        for item in value
        if isinstance(item, Sequence)
        and not isinstance(item, (str, bytes))
        and len(item) == 2
        and isinstance(item[1], Mapping)
    )


def _required_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"planner.macro_contract_invalid: {name} must be an object")
    return value


__all__ = [
    "MacroDefinition",
    "MacroDefinitionPreparationContext",
    "MacroDefinitionError",
    "MacroDefinitionRegistry",
    "MacroExpansionRequest",
    "build_point_name_candidates",
    "default_macro_definition_registry",
]
