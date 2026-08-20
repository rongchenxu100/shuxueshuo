"""Pre-binding authority for bounded runtime-search Macros."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from shuxueshuo_server.solver.contracts import MacroSearchSpec
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroCandidateEvaluation,
    MacroExecutionCandidate,
    MacroRuntimeSearchError,
    MacroRuntimeSearchReport,
    MacroRuntimeSearchService,
)


@dataclass(frozen=True)
class MacroRoleAssignmentCandidate:
    """One scope-safe public-role assignment before Method lowering."""

    candidate_id: str
    roles: Mapping[str, str]
    dependency_handles: tuple[str, ...]
    fact_handles: Mapping[str, str] = field(default_factory=dict)
    call_count: int = 0
    symbolic_complexity: int = 0

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("Macro candidate_id must be non-empty")
        roles = dict(sorted(self.roles.items()))
        if not roles or any(not key or not value for key, value in roles.items()):
            raise ValueError("Macro role assignment must be complete")
        object.__setattr__(self, "roles", MappingProxyType(roles))
        object.__setattr__(
            self,
            "dependency_handles",
            tuple(sorted(set(self.dependency_handles))),
        )
        object.__setattr__(
            self,
            "fact_handles",
            MappingProxyType(dict(sorted(self.fact_handles.items()))),
        )

    def execution_candidate(self) -> MacroExecutionCandidate:
        return MacroExecutionCandidate(
            candidate_id=self.candidate_id,
            roles=self.roles,
            call_count=self.call_count,
            symbolic_complexity=self.symbolic_complexity,
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "roles": dict(self.roles),
            "dependency_handles": list(self.dependency_handles),
            "fact_handles": dict(self.fact_handles),
            "call_count": self.call_count,
            "symbolic_complexity": self.symbolic_complexity,
        }


@dataclass(frozen=True)
class MacroPreparationEnvironment:
    """Generic runtime inputs; each registered Macro projects its own view."""

    prepared_call: Any = field(repr=False, compare=False)
    handle_registry: Any = field(repr=False, compare=False)
    max_candidates: int

    def __post_init__(self) -> None:
        if self.max_candidates <= 0:
            raise ValueError("Macro max_candidates must be positive")


@dataclass(frozen=True)
class MacroImplementationPreparationContext:
    """Implementation-owned candidate input and its scope-safe envelope."""

    payload: Any = field(repr=False, compare=False)
    candidate_dependency_envelope: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_dependency_envelope",
            tuple(sorted(set(self.candidate_dependency_envelope))),
        )


@dataclass(frozen=True)
class MacroPreparationRequest:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    plan_id: str
    call_id: str
    goal_unit_ids: tuple[str, ...]
    scope_id: str
    macro_id: str
    catalog_signature: str
    authored_roles: Mapping[str, str]
    candidate_dependency_envelope: tuple[str, ...]
    upstream_exact_state_signature: str
    environment: Any = field(default=None, repr=False, compare=False)
    builder_context: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "planning_context_id",
            "problem_revision_id",
            "problem_semantic_hash",
            "plan_id",
            "call_id",
            "scope_id",
            "macro_id",
            "catalog_signature",
            "upstream_exact_state_signature",
        ):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        object.__setattr__(
            self,
            "goal_unit_ids",
            tuple(sorted(set(self.goal_unit_ids))),
        )
        object.__setattr__(
            self,
            "authored_roles",
            MappingProxyType(dict(sorted(self.authored_roles.items()))),
        )
        object.__setattr__(
            self,
            "candidate_dependency_envelope",
            tuple(sorted(set(self.candidate_dependency_envelope))),
        )


@dataclass(frozen=True)
class MacroCandidateBindingAuthority:
    macro_id: str
    call_id: str
    scope_id: str
    candidate: MacroRoleAssignmentCandidate
    allowed_source_handles: tuple[str, ...]
    upstream_exact_state_signature: str
    binding_signature: str = field(init=False)

    def __post_init__(self) -> None:
        allowed = tuple(sorted(set(self.allowed_source_handles)))
        object.__setattr__(self, "allowed_source_handles", allowed)
        payload = self.authority_payload(include_signature=False)
        object.__setattr__(self, "binding_signature", stable_hash(payload))

    def authority_payload(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload = {
            "macro_id": self.macro_id,
            "call_id": self.call_id,
            "scope_id": self.scope_id,
            "candidate": self.candidate.authority_payload(),
            "allowed_source_handles": list(self.allowed_source_handles),
            "upstream_exact_state_signature": self.upstream_exact_state_signature,
        }
        if include_signature:
            payload["binding_signature"] = self.binding_signature
        return payload


@dataclass(frozen=True)
class MacroPreparationAuthority:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    plan_id: str
    call_id: str
    goal_unit_ids: tuple[str, ...]
    scope_id: str
    macro_id: str
    implementation_id: str
    catalog_signature: str
    authored_roles: Mapping[str, str]
    candidate_dependency_envelope: tuple[str, ...]
    upstream_exact_state_signature: str
    winner: MacroCandidateBindingAuthority
    search_report: MacroRuntimeSearchReport
    preparation_signature: str = field(init=False)
    schema_version: str = "macro-preparation-authority/v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "goal_unit_ids",
            tuple(sorted(set(self.goal_unit_ids))),
        )
        object.__setattr__(
            self,
            "authored_roles",
            MappingProxyType(dict(sorted(self.authored_roles.items()))),
        )
        object.__setattr__(
            self,
            "candidate_dependency_envelope",
            tuple(sorted(set(self.candidate_dependency_envelope))),
        )
        if self.search_report.winner_candidate_id != self.winner.candidate.candidate_id:
            raise ValueError("Macro preparation winner/report drift")
        object.__setattr__(
            self,
            "preparation_signature",
            stable_hash(self.authority_payload(include_signature=False)),
        )

    def authority_payload(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "plan_id": self.plan_id,
            "call_id": self.call_id,
            "goal_unit_ids": list(self.goal_unit_ids),
            "scope_id": self.scope_id,
            "macro_id": self.macro_id,
            "implementation_id": self.implementation_id,
            "catalog_signature": self.catalog_signature,
            "authored_roles": dict(self.authored_roles),
            "candidate_dependency_envelope": list(
                self.candidate_dependency_envelope
            ),
            "upstream_exact_state_signature": self.upstream_exact_state_signature,
            "winner": self.winner.authority_payload(),
            "search_report": self.search_report.to_payload(),
        }
        if include_signature:
            payload["preparation_signature"] = self.preparation_signature
        return payload


@dataclass(frozen=True)
class PreparedMacroInvocation:
    implementation_id: str
    authority: MacroPreparationAuthority
    debug_only: bool = False


MacroCandidateBuilder = Callable[
    [MacroPreparationRequest], Sequence[MacroRoleAssignmentCandidate]
]
MacroPreparationContextBuilder = Callable[
    [MacroPreparationRequest], MacroImplementationPreparationContext
]
MacroCandidateLowerer = Callable[[Any, MacroCandidateBindingAuthority], Any]
MacroPostcondition = Callable[[Any], Sequence[str]]
MacroEvidenceBuilder = Callable[..., Any]


@dataclass(frozen=True)
class MacroImplementation:
    implementation_id: str
    macro_id: str
    candidate_builder_id: str
    validation_policy_id: str
    lowerer_id: str
    postcondition_id: str
    evidence_builder_id: str
    preparation_context_builder: MacroPreparationContextBuilder
    candidate_builder: MacroCandidateBuilder
    lowerer: MacroCandidateLowerer
    postcondition: MacroPostcondition
    evidence_builder: MacroEvidenceBuilder


class MacroImplementationRegistry:
    """Runtime-owned executable implementations for search-capable Macros."""

    def __init__(self, implementations: Iterable[MacroImplementation] = ()) -> None:
        self._items: dict[str, MacroImplementation] = {}
        for implementation in implementations:
            self.register(implementation)

    def register(self, implementation: MacroImplementation) -> None:
        if implementation.macro_id in self._items:
            raise ValueError(
                f"duplicate Macro implementation {implementation.macro_id}"
            )
        self._items[implementation.macro_id] = implementation

    def require(
        self,
        macro_id: str,
        search_spec: MacroSearchSpec,
    ) -> MacroImplementation:
        implementation = self._items.get(macro_id)
        if implementation is None:
            raise ValueError(
                "planner.macro_contract_invalid: runtime_search Macro has no "
                f"implementation: {macro_id}"
            )
        expected = {
            "candidate_builder_id": search_spec.candidate_builder_id,
            "validation_policy_id": search_spec.validation_policy_id,
            "lowerer_id": search_spec.lowerer_id,
            "postcondition_id": search_spec.postcondition_id,
            "evidence_builder_id": search_spec.evidence_builder_id,
        }
        actual = {
            name: getattr(implementation, name) for name in expected
        }
        if any(value is None for value in expected.values()) or actual != expected:
            raise ValueError(
                "planner.macro_contract_invalid: Macro search spec and "
                f"implementation differ for {macro_id}"
            )
        return implementation


MacroPreparationEvaluator = Callable[
    [MacroCandidateBindingAuthority], MacroCandidateEvaluation
]


class MacroPreparationService:
    def __init__(self, registry: MacroImplementationRegistry) -> None:
        self._registry = registry

    def prepare(
        self,
        request: MacroPreparationRequest,
        *,
        search_spec: MacroSearchSpec,
        evaluator: MacroPreparationEvaluator,
    ) -> PreparedMacroInvocation:
        implementation = self._registry.require(request.macro_id, search_spec)
        preparation_context = implementation.preparation_context_builder(request)
        if not isinstance(
            preparation_context,
            MacroImplementationPreparationContext,
        ):
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                "Macro preparation context builder returned an invalid contract",
                retryability="configuration",
                details={"macro_id": request.macro_id},
            )
        request = replace(
            request,
            builder_context=preparation_context.payload,
            candidate_dependency_envelope=(
                preparation_context.candidate_dependency_envelope
            ),
        )
        candidates = tuple(implementation.candidate_builder(request))
        dependency_envelope = frozenset(
            request.candidate_dependency_envelope
        )
        for candidate in candidates:
            candidate_sources = {
                *candidate.dependency_handles,
                *candidate.fact_handles.values(),
            }
            outside = tuple(sorted(candidate_sources - dependency_envelope))
            if outside:
                raise MacroRuntimeSearchError(
                    "planner.macro_contract_invalid",
                    "Macro candidate escaped its scope-safe dependency envelope",
                    retryability="configuration",
                    details={
                        "macro_id": request.macro_id,
                        "candidate_id": candidate.candidate_id,
                        "outside_dependency_handles": list(outside),
                    },
                )
        authorities = {
            item.candidate_id: MacroCandidateBindingAuthority(
                macro_id=request.macro_id,
                call_id=request.call_id,
                scope_id=request.scope_id,
                candidate=item,
                allowed_source_handles=tuple(
                    sorted(
                        {
                            *item.dependency_handles,
                            *item.fact_handles.values(),
                        }
                    )
                ),
                upstream_exact_state_signature=(
                    request.upstream_exact_state_signature
                ),
            )
            for item in candidates
        }

        def evaluate(candidate: MacroExecutionCandidate) -> MacroCandidateEvaluation:
            return evaluator(authorities[candidate.candidate_id])

        winner, report = MacroRuntimeSearchService().search(
            macro_id=request.macro_id,
            spec=search_spec,
            candidates=tuple(item.execution_candidate() for item in candidates),
            authored_roles=request.authored_roles,
            evaluator=evaluate,
        )
        winner_authority = authorities[winner.candidate_id]
        authority = MacroPreparationAuthority(
            planning_context_id=request.planning_context_id,
            problem_revision_id=request.problem_revision_id,
            problem_semantic_hash=request.problem_semantic_hash,
            plan_id=request.plan_id,
            call_id=request.call_id,
            goal_unit_ids=request.goal_unit_ids,
            scope_id=request.scope_id,
            macro_id=request.macro_id,
            implementation_id=implementation.implementation_id,
            catalog_signature=request.catalog_signature,
            authored_roles=request.authored_roles,
            candidate_dependency_envelope=(
                request.candidate_dependency_envelope
            ),
            upstream_exact_state_signature=(
                request.upstream_exact_state_signature
            ),
            winner=winner_authority,
            search_report=report,
        )
        return PreparedMacroInvocation(
            implementation_id=implementation.implementation_id,
            authority=authority,
        )


def default_macro_implementation_registry() -> MacroImplementationRegistry:
    """Return the production registry; only implemented search Macros live here."""

    return MacroImplementationRegistry(
        (
            MacroImplementation(
                implementation_id="equal-length-ray-path/v1",
                macro_id="equal_length_ray_path_reduction",
                candidate_builder_id="equal_length_ray_role_assignments",
                validation_policy_id="distance_equivalence_and_provenance",
                lowerer_id="equal_length_ray_path_reduction",
                postcondition_id="equal_length_ray_path_postcondition",
                evidence_builder_id="equal_length_ray_path_witness",
                preparation_context_builder=(
                    _build_equal_length_ray_preparation_context
                ),
                candidate_builder=_build_equal_length_ray_candidates,
                lowerer=_lower_equal_length_ray_candidate,
                postcondition=_equal_length_ray_postcondition,
                evidence_builder=_equal_length_ray_evidence,
            ),
        )
    )


def _build_equal_length_ray_preparation_context(
    request: MacroPreparationRequest,
) -> MacroImplementationPreparationContext:
    """Project generic execution state into this Macro's private context."""

    environment = request.environment
    prepared = getattr(environment, "prepared_call", None)
    handle_registry = getattr(environment, "handle_registry", None)
    max_candidates = getattr(environment, "max_candidates", None)
    if (
        prepared is None
        or handle_registry is None
        or not isinstance(max_candidates, int)
        or max_candidates <= 0
    ):
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "equal-length Macro preparation requires a typed execution environment",
            retryability="configuration",
        )

    fact_args = {
        "ray_facts": "point_on_ray",
        "segment_facts": "point_on_segment",
        "equal_facts": "equal_length_condition",
        "target_facts": "path_minimum_target",
    }
    context: dict[str, Any] = {
        "entity_payloads": dict(handle_registry.entity_payloads),
        "max_candidates": max_candidates,
    }
    resolved_args = getattr(prepared.reconciliation, "resolved_args", {})
    for output_name, arg_name in fact_args.items():
        items: list[tuple[str, Mapping[str, Any]]] = []
        for value in resolved_args.get(arg_name, ()):
            handle = value.handle
            payload = handle_registry.fact_payloads.get(handle)
            if payload is not None:
                items.append((handle, payload))
        context[output_name] = tuple(items)

    visible_scopes = set(
        handle_registry.ancestor_scopes(prepared.execution_scope_id)
    )
    point_handles = tuple(
        sorted(
            handle
            for handle in handle_registry.entity_handles
            if handle.startswith("point:")
            and handle_registry.handle_valid_scopes.get(handle) in visible_scopes
        )
    )
    by_name: dict[str, list[str]] = {}
    for handle in point_handles:
        payload = handle_registry.entity_payloads.get(handle, {})
        name = str(payload.get("name", "")).strip() or handle.rsplit(":", 1)[-1]
        by_name.setdefault(name, []).append(handle)
    context["point_names"] = {
        name: handles[0]
        for name, handles in sorted(by_name.items())
        if len(handles) == 1
    }
    dependency_envelope = {
        *point_handles,
        *(
            str(item[0])
            for group_name in fact_args
            for item in context[group_name]
        ),
    }
    return MacroImplementationPreparationContext(
        payload=MappingProxyType(context),
        candidate_dependency_envelope=tuple(sorted(dependency_envelope)),
    )


def _build_equal_length_ray_candidates(
    request: MacroPreparationRequest,
) -> Sequence[MacroRoleAssignmentCandidate]:
    from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
        build_equal_length_ray_role_candidates,
    )

    context = request.builder_context
    if not isinstance(context, Mapping):
        raise ValueError(
            "planner.macro_contract_invalid: equal-length candidate builder "
            "requires structured Context"
        )
    entity_payloads = context.get("entity_payloads")
    point_names = context.get("point_names")
    if not isinstance(entity_payloads, Mapping) or not isinstance(
        point_names,
        Mapping,
    ):
        raise ValueError(
            "planner.macro_contract_invalid: incomplete equal-length builder Context"
        )

    def fact_group(name: str) -> tuple[tuple[str, Mapping[str, Any]], ...]:
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

    candidates = build_equal_length_ray_role_candidates(
        ray_facts=fact_group("ray_facts"),
        segment_facts=fact_group("segment_facts"),
        equal_facts=fact_group("equal_facts"),
        target_facts=fact_group("target_facts"),
        entity_payload=lambda handle: entity_payloads[handle],
        visible_point_handles=tuple(str(item) for item in point_names.values()),
        resolve_point_name=lambda name: str(point_names[name]),
        max_candidates=int(context.get("max_candidates", 32)),
    )
    return tuple(
        MacroRoleAssignmentCandidate(
            candidate_id=item.candidate_id,
            roles=item.roles.to_payload(),
            dependency_handles=tuple(
                sorted(
                    {
                        *item.roles.to_payload().values(),
                        *dict(item.fact_handles).values(),
                    }
                )
            ),
            fact_handles=dict(item.fact_handles),
        )
        for item in candidates
    )


def _lower_equal_length_ray_candidate(
    value: Any,
    authority: MacroCandidateBindingAuthority,
) -> Any:
    """Delegate immutable role replacement to the caller's lowering adapter."""

    lower = getattr(value, "with_macro_roles", None)
    return lower(dict(authority.candidate.roles)) if callable(lower) else value


def _equal_length_ray_postcondition(value: Any) -> Sequence[str]:
    checks = getattr(value, "checks", ())
    return tuple(
        str(getattr(item, "name", item))
        for item in checks
        if bool(getattr(item, "ok", True))
    )


def _equal_length_ray_evidence(*args: Any, **kwargs: Any) -> Any:
    from shuxueshuo_server.solver.runtime.equal_length_ray_path_search import (
        build_equal_length_ray_execution_witness,
    )

    return build_equal_length_ray_execution_witness(*args, **kwargs)


__all__ = [
    "MacroCandidateBindingAuthority",
    "MacroImplementation",
    "MacroImplementationPreparationContext",
    "MacroImplementationRegistry",
    "MacroPreparationEnvironment",
    "MacroPreparationAuthority",
    "MacroPreparationRequest",
    "MacroPreparationService",
    "MacroRoleAssignmentCandidate",
    "PreparedMacroInvocation",
    "default_macro_implementation_registry",
]
