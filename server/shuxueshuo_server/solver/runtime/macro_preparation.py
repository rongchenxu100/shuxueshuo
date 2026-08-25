"""Pre-binding authority for bounded runtime-search Macros."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Mapping

from shuxueshuo_server.solver.contracts import MacroSearchSpec
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSearchReport,
    GenericCandidateSearchService,
    SearchCandidate,
    VerifiedSubplanSearchError,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    MacroDefinitionPreparationContext,
    MacroDefinitionRegistry,
    MacroDefinitionError,
    MacroExpansionRequest,
    build_point_name_candidates,
    default_macro_definition_registry,
)
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRuntimeSearchError,
)


@dataclass(frozen=True)
class MacroPreparationEnvironment:
    """Generic runtime inputs; each registered Macro projects its own view."""

    prepared_call: Any = field(repr=False, compare=False)
    handle_registry: Any = field(repr=False, compare=False)
    binding_catalog: Any = field(repr=False, compare=False)
    max_candidates: int

    def __post_init__(self) -> None:
        if self.max_candidates <= 0:
            raise ValueError("Macro max_candidates must be positive")


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
    candidate: SearchCandidate
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
            "candidate": self.candidate.to_payload(),
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
    search_report: CandidateSearchReport
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


MacroPreparationEvaluator = Callable[
    [MacroCandidateBindingAuthority], CandidateEvaluation
]


class MacroPreparationService:
    def __init__(
        self,
        definitions: MacroDefinitionRegistry | None = None,
    ) -> None:
        self._definitions = definitions or default_macro_definition_registry()

    def prepare(
        self,
        request: MacroPreparationRequest,
        *,
        search_spec: MacroSearchSpec,
        evaluator: MacroPreparationEvaluator,
    ) -> PreparedMacroInvocation:
        definition = self._definitions.require(request.macro_id)
        if not definition.accepts_search_contract(search_spec):
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                "Macro catalog search contract differs from its Definition",
                retryability="configuration",
                details={"macro_id": request.macro_id},
            )
        preparation_context = definition.preparation_context_builder(request)
        if not isinstance(
            preparation_context,
            MacroDefinitionPreparationContext,
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
        try:
            candidates = tuple(
                definition.expander(
                    MacroExpansionRequest(
                        macro_id=request.macro_id,
                        call_id=request.call_id,
                        scope_id=request.scope_id,
                        authored_roles=request.authored_roles,
                        builder_context=request.builder_context,
                        max_candidates=search_spec.max_candidates,
                    )
                )
            )
        except MacroDefinitionError as exc:
            raise MacroRuntimeSearchError(
                exc.code,
                str(exc),
                retryability=(
                    "planner_repairable" if exc.retryable else "configuration"
                ),
                details={"macro_id": request.macro_id, **exc.details},
            ) from exc
        dependency_envelope = frozenset(
            request.candidate_dependency_envelope
        )
        for candidate in candidates:
            candidate_sources = set(candidate.dependency_envelope)
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
                allowed_source_handles=item.dependency_envelope,
                upstream_exact_state_signature=(
                    request.upstream_exact_state_signature
                ),
            )
            for item in candidates
        }

        def evaluate(candidate: SearchCandidate) -> CandidateEvaluation:
            return evaluator(authorities[candidate.candidate_id])

        try:
            winner, report, _shadow_winner = (
                GenericCandidateSearchService().search(
                    macro_id=request.macro_id,
                    candidates=candidates,
                    evaluator=evaluate,
                    max_candidates=search_spec.max_candidates,
                    selection=definition.selection,
                    authored_roles=request.authored_roles,
                )
            )
        except VerifiedSubplanSearchError as exc:
            raise MacroRuntimeSearchError(
                exc.code,
                str(exc),
                retryability=(
                    "planner_repairable" if exc.retryable else "configuration"
                ),
                details={"macro_id": request.macro_id, **exc.details},
            ) from exc
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
            implementation_id=definition.implementation_id,
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
            implementation_id=definition.implementation_id,
            authority=authority,
        )


def _build_equal_length_ray_preparation_context(
    request: MacroPreparationRequest,
) -> MacroDefinitionPreparationContext:
    """Project generic execution state into this Macro's private context."""

    environment = request.environment
    prepared = getattr(environment, "prepared_call", None)
    handle_registry = getattr(environment, "handle_registry", None)
    binding_catalog = getattr(environment, "binding_catalog", None)
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
    context["domain_facts"] = tuple(
        sorted(
            (
                handle,
                payload,
            )
            for handle, payload in handle_registry.fact_payloads.items()
            if payload.get("type") == "symbol_constraint"
            and handle_registry.handle_valid_scopes.get(handle)
            in visible_scopes
        )
    )
    point_handles = tuple(
        sorted(
            handle
            for handle in handle_registry.entity_handles
            if handle.startswith("point:")
            and handle_registry.handle_valid_scopes.get(handle) in visible_scopes
        )
    )
    context["point_name_candidates"] = build_point_name_candidates(
        point_handles=point_handles,
        entity_payloads=handle_registry.entity_payloads,
    )
    visible_scopes = frozenset(
        handle_registry.ancestor_scopes(prepared.execution_scope_id)
    )
    source_refs_by_handle: dict[str, str] = {}
    if binding_catalog is None:
        source_refs_by_handle.update(
            {
                handle: handle.rsplit(":", 1)[-1]
                for handle in (*handle_registry.entity_handles, *handle_registry.fact_handles)
            }
        )
    else:
        for source in binding_catalog.bindings.values():
            if source.usage != "input" or source.owner_scope_id not in visible_scopes:
                continue
            handle = source.runtime_node_id
            ref = source.semantic_ref.ref
            previous = source_refs_by_handle.get(handle)
            if previous is not None and previous != ref:
                raise MacroRuntimeSearchError(
                    "planner.macro_contract_invalid",
                    "one runtime source has multiple visible SemanticRefs",
                    retryability="configuration",
                    details={"runtime_node_id": handle},
                )
            source_refs_by_handle[handle] = ref
    context["source_refs_by_handle"] = MappingProxyType(
        dict(sorted(source_refs_by_handle.items()))
    )
    dependency_envelope = {
        *point_handles,
        *(str(item[0]) for item in context["domain_facts"]),
        *(
            str(item[0])
            for group_name in fact_args
            for item in context[group_name]
        ),
    }
    return MacroDefinitionPreparationContext(
        payload=MappingProxyType(context),
        candidate_dependency_envelope=tuple(sorted(dependency_envelope)),
    )


__all__ = [
    "MacroCandidateBindingAuthority",
    "MacroPreparationEnvironment",
    "MacroPreparationAuthority",
    "MacroPreparationRequest",
    "MacroPreparationService",
    "PreparedMacroInvocation",
]
