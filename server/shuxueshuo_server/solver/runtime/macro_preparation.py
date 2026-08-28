"""Pre-binding authority for bounded runtime-search Macros."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from shuxueshuo_server.solver.contracts import (
    ExactCallResultSourceSpec,
    MacroPreparedRoleSourceSpec,
    MacroSearchSpec,
    MethodInputBindingSpec,
    PreviousOutputIdentityDerivationSpec,
)
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


@dataclass(frozen=True)
class MacroMethodInputBindingSpec:
    """Registry-owned source contract for one internal Method input."""

    method_id: str
    input_name: str
    binding: MethodInputBindingSpec

    def __post_init__(self) -> None:
        if not self.method_id or not self.input_name:
            raise ValueError("Macro Method input binding names must be non-empty")
        source = self.binding.source
        derivation = self.binding.derivation
        if not (
            isinstance(
                source,
                (MacroPreparedRoleSourceSpec, ExactCallResultSourceSpec),
            )
            or isinstance(
                derivation,
                PreviousOutputIdentityDerivationSpec,
            )
        ):
            raise ValueError(
                "planner.macro_contract_invalid: internal Method input must "
                "come from a prepared role, exact invocation result, or "
                "output identity"
            )
        if self.binding.input_name != self.input_name:
            raise ValueError(
                "planner.macro_contract_invalid: internal Method input name "
                "differs from its typed binding"
            )

    @property
    def target(self) -> str:
        return f"{self.method_id}.{self.input_name}"


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
    method_input_bindings: tuple[MacroMethodInputBindingSpec, ...] = ()


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
        targets = tuple(
            item.target for item in implementation.method_input_bindings
        )
        if len(set(targets)) != len(targets):
            raise ValueError(
                "planner.macro_contract_invalid: duplicate internal Method "
                f"input binding for {implementation.macro_id}"
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

    def require_lowering_contract(
        self,
        macro_id: str,
        search_spec: MacroSearchSpec,
        *,
        macro_spec: Any,
        method_specs: Any,
    ) -> MacroImplementation:
        implementation = self.require(macro_id, search_spec)
        prepared_roles = {
            item.binding.source.role
            for item in implementation.method_input_bindings
            if isinstance(
                item.binding.source,
                MacroPreparedRoleSourceSpec,
            )
        }
        if prepared_roles != set(search_spec.searchable_roles):
            raise ValueError(
                "planner.macro_contract_invalid: prepared Method role wiring "
                f"differs for {macro_id}: expected="
                f"{sorted(search_spec.searchable_roles)}, observed="
                f"{sorted(prepared_roles)}"
            )
        internal_order = {
            item.capability_id: item.order
            for item in macro_spec.internal_calls
        }
        by_target = {
            item.target: item for item in implementation.method_input_bindings
        }
        missing_strategy_targets = set(
            macro_spec.adapter.strategy_input_targets
        ) - set(by_target)
        if missing_strategy_targets:
            raise ValueError(
                "planner.macro_contract_invalid: Registry does not own all "
                f"strategy inputs for {macro_id}: "
                f"{sorted(missing_strategy_targets)}"
            )
        for item in implementation.method_input_bindings:
            if item.method_id not in internal_order:
                raise ValueError(
                    "planner.macro_contract_invalid: Registry references a "
                    f"non-internal Method: {macro_id}.{item.method_id}"
                )
            method = method_specs.require(item.method_id)
            input_spec = method.inputs.get(item.input_name)
            if input_spec is None:
                raise ValueError(
                    "planner.macro_contract_invalid: Registry references an "
                    f"unknown Method input: {macro_id}.{item.target}"
                )
            source = item.binding.source
            derivation = item.binding.derivation
            if isinstance(source, ExactCallResultSourceSpec):
                source_method, separator, return_name = (
                    source.arg_name.partition(".")
                )
                if (
                    not separator
                    or source_method not in internal_order
                    or return_name
                    not in method_specs.require(source_method).outputs
                    or internal_order[source_method] >= internal_order[item.method_id]
                ):
                    raise ValueError(
                        "planner.macro_contract_invalid: invalid internal "
                        f"result wiring {source.arg_name!r} -> {item.target}"
                    )
            if isinstance(
                derivation,
                PreviousOutputIdentityDerivationSpec,
            ) and derivation.output_name not in method.outputs:
                raise ValueError(
                    "planner.macro_contract_invalid: output identity wiring "
                    f"references {item.method_id}.{derivation.output_name}"
                )
        for source, target in macro_spec.adapter.intermediate_wiring:
            binding = by_target.get(target)
            if not (
                binding is not None
                and isinstance(
                    binding.binding.source,
                    ExactCallResultSourceSpec,
                )
                and binding.binding.source.arg_name == source
            ):
                raise ValueError(
                    "planner.macro_contract_invalid: intermediate wiring is "
                    f"not Registry-owned: {source} -> {target}"
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
                method_input_bindings=(
                    MacroMethodInputBindingSpec(
                        "equal_length_ray_point",
                        "anchor",
                        MethodInputBindingSpec(
                            input_name="anchor",
                            source=MacroPreparedRoleSourceSpec("anchor"),
                        ),
                    ),
                    MacroMethodInputBindingSpec(
                        "equal_length_ray_point",
                        "reference_point",
                        MethodInputBindingSpec(
                            input_name="reference_point",
                            source=MacroPreparedRoleSourceSpec(
                                "reference_point"
                            ),
                        ),
                    ),
                    MacroMethodInputBindingSpec(
                        "equal_length_ray_point",
                        "ray_point",
                        MethodInputBindingSpec(
                            input_name="ray_point",
                            source=MacroPreparedRoleSourceSpec("ray_point"),
                        ),
                    ),
                    MacroMethodInputBindingSpec(
                        "equal_length_ray_point",
                        "target",
                        MethodInputBindingSpec(
                            input_name="target",
                            derivation=PreviousOutputIdentityDerivationSpec(
                                "point"
                            ),
                        ),
                    ),
                    MacroMethodInputBindingSpec(
                        "distance_between_points",
                        "p1",
                        MethodInputBindingSpec(
                            input_name="p1",
                            source=MacroPreparedRoleSourceSpec("fixed_point"),
                        ),
                    ),
                    MacroMethodInputBindingSpec(
                        "distance_between_points",
                        "p2",
                        MethodInputBindingSpec(
                            input_name="p2",
                            source=ExactCallResultSourceSpec(
                                "equal_length_ray_point.point"
                            ),
                        ),
                    ),
                ),
            ),
            MacroImplementation(
                implementation_id="coupled-segment-path/v1",
                macro_id=(
                    "coupled_segment_endpoint_replacement_path_minimum"
                ),
                candidate_builder_id="coupled_segment_path_role_assignments",
                validation_policy_id="path_equivalence_and_attainment",
                lowerer_id="coupled_segment_path_minimum",
                postcondition_id="coupled_segment_path_postcondition",
                evidence_builder_id="coupled_segment_path_witness",
                preparation_context_builder=(
                    _build_coupled_segment_path_preparation_context
                ),
                candidate_builder=_build_coupled_segment_path_candidates,
                lowerer=_lower_coupled_segment_path_candidate,
                postcondition=_coupled_segment_path_postcondition,
                evidence_builder=_coupled_segment_path_evidence,
                method_input_bindings=tuple(
                    MacroMethodInputBindingSpec(
                        (
                            "coupled_segment_endpoint_replacement_"
                            "path_minimum_kernel"
                        ),
                        input_name,
                        MethodInputBindingSpec(
                            input_name=input_name,
                            source=MacroPreparedRoleSourceSpec(role),
                        ),
                    )
                    for input_name, role in (
                        ("first_membership", "first_membership"),
                        ("second_membership", "second_membership"),
                        ("first_segment_start", "first_segment_start"),
                        ("joint_point", "joint_point"),
                        ("second_segment_end", "second_segment_end"),
                        (
                            "transformed_fixed_endpoint",
                            "transformed_fixed_endpoint",
                        ),
                        ("moving_point", "moving_point"),
                    )
                ),
            ),
            MacroImplementation(
                implementation_id="quadratic-square-path/v1",
                macro_id="quadratic_square_path_minimum",
                candidate_builder_id="quadratic_square_path_role_assignments",
                validation_policy_id="path_equivalence_and_attainment",
                lowerer_id="quadratic_square_path_minimum",
                postcondition_id="quadratic_square_path_postcondition",
                evidence_builder_id="quadratic_square_path_witness",
                preparation_context_builder=(
                    _build_quadratic_square_path_preparation_context
                ),
                candidate_builder=_build_quadratic_square_path_candidates,
                lowerer=_lower_quadratic_square_path_candidate,
                postcondition=_quadratic_square_path_postcondition,
                evidence_builder=_quadratic_square_path_evidence,
                method_input_bindings=tuple(
                    MacroMethodInputBindingSpec(
                        "quadratic_square_path_minimum_kernel",
                        input_name,
                        MethodInputBindingSpec(
                            input_name=input_name,
                            source=MacroPreparedRoleSourceSpec(role),
                        ),
                    )
                    for input_name, role in (
                        ("midpoint_definition", "midpoint_definition"),
                        ("square_center", "square_center"),
                        ("axis_membership", "axis_membership"),
                        ("side_start", "side_start"),
                        ("side_start_ref", "side_start"),
                        ("axis_point", "axis_point"),
                        ("moving_point", "moving_point"),
                        ("fixed_endpoint", "fixed_endpoint"),
                    )
                ),
            ),
        )
    )


def _build_coupled_segment_path_preparation_context(
    request: MacroPreparationRequest,
) -> MacroImplementationPreparationContext:
    environment = request.environment
    prepared = getattr(environment, "prepared_call", None)
    handle_registry = getattr(environment, "handle_registry", None)
    if prepared is None or handle_registry is None:
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "coupled-segment Macro requires a typed execution environment",
            retryability="configuration",
        )
    resolved_args = getattr(prepared.reconciliation, "resolved_args", {})

    def one_handle(arg_name: str) -> str:
        values = tuple(resolved_args.get(arg_name, ()))
        if len(values) != 1:
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                f"coupled-segment Macro requires one {arg_name}",
                retryability="configuration",
                details={"arg": arg_name, "count": len(values)},
            )
        return str(values[0].handle)

    context = MappingProxyType(
        {
            "path_minimum_target": one_handle("path_minimum_target"),
            "segment_binding_relation": one_handle(
                "segment_binding_relation"
            ),
            "scope_id": request.scope_id,
            "handle_registry": handle_registry,
        }
    )
    dependency_envelope = {
        context["path_minimum_target"],
        context["segment_binding_relation"],
    }
    for values in resolved_args.values():
        dependency_envelope.update(
            value.handle for value in values if getattr(value, "handle", None)
        )
        dependency_envelope.update(
            value.object_ref
            for value in values
            if getattr(value, "object_ref", None)
        )
    return MacroImplementationPreparationContext(
        payload=context,
        candidate_dependency_envelope=tuple(sorted(dependency_envelope)),
    )


def _build_coupled_segment_path_candidates(
    request: MacroPreparationRequest,
) -> Sequence[MacroRoleAssignmentCandidate]:
    from shuxueshuo_server.solver.runtime.coupled_segment_path_roles import (
        CoupledSegmentPathRoleError,
        build_coupled_segment_path_role_candidates,
    )

    context = request.builder_context
    if not isinstance(context, Mapping):
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "coupled-segment candidate builder requires structured Context",
            retryability="configuration",
        )
    macro_id = "coupled_segment_endpoint_replacement_path_minimum"
    try:
        candidates = build_coupled_segment_path_role_candidates(
            path_minimum_target=str(context["path_minimum_target"]),
            segment_binding_relation=str(context["segment_binding_relation"]),
            scope_id=str(context["scope_id"]),
            registry=context["handle_registry"],
        )
    except (CoupledSegmentPathRoleError, KeyError) as exc:
        raise MacroRuntimeSearchError(
            "functional.macro_search_no_structural_candidate",
            str(exc),
            retryability="planner_repairable",
            details={
                "macro_id": macro_id,
                "repair_action": "select_compatible_path_and_segment_relation",
                **(
                    exc.details
                    if isinstance(exc, CoupledSegmentPathRoleError)
                    else {}
                ),
            },
        ) from exc
    if not candidates:
        raise MacroRuntimeSearchError(
            "functional.macro_search_no_structural_candidate",
            "the selected path and segment relation do not form one endpoint-replacement mechanism",
            retryability="planner_repairable",
            details={
                "macro_id": macro_id,
                "public_args": [
                    "path_minimum_target",
                    "segment_binding_relation",
                ],
                "repair_action": "select_compatible_path_and_segment_relation",
            },
        )
    return tuple(
        MacroRoleAssignmentCandidate(
            candidate_id=item.candidate_id,
            roles={
                role: getattr(item, role)
                for role in (
                    "first_membership",
                    "second_membership",
                    "first_segment_start",
                    "joint_point",
                    "second_segment_end",
                    "transformed_fixed_endpoint",
                    "moving_point",
                )
            },
            dependency_handles=tuple(
                getattr(item, role)
                for role in (
                    "path_minimum_target",
                    "segment_binding_relation",
                    "first_membership",
                    "second_membership",
                    "first_segment_start",
                    "joint_point",
                    "second_segment_end",
                    "transformed_fixed_endpoint",
                    "moving_point",
                )
            ),
            fact_handles={
                role: getattr(item, role)
                for role in ("first_membership", "second_membership")
            },
        )
        for item in candidates
    )


def _lower_coupled_segment_path_candidate(
    value: Any,
    authority: MacroCandidateBindingAuthority,
) -> Any:
    lower = getattr(value, "with_macro_roles", None)
    return lower(dict(authority.candidate.roles)) if callable(lower) else value


def _coupled_segment_path_postcondition(value: Any) -> Sequence[str]:
    return tuple(
        str(getattr(item, "name", item))
        for item in getattr(value, "checks", ())
        if bool(getattr(item, "ok", True))
    )


def _coupled_segment_path_evidence(*args: Any, **kwargs: Any) -> Any:
    from shuxueshuo_server.solver.runtime.coupled_segment_path_evidence import (
        build_coupled_segment_path_execution_witness,
    )

    return build_coupled_segment_path_execution_witness(*args, **kwargs)


def _build_quadratic_square_path_preparation_context(
    request: MacroPreparationRequest,
) -> MacroImplementationPreparationContext:
    environment = request.environment
    prepared = getattr(environment, "prepared_call", None)
    handle_registry = getattr(environment, "handle_registry", None)
    if prepared is None or handle_registry is None:
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "quadratic-square Macro preparation requires a typed execution environment",
            retryability="configuration",
        )
    resolved_args = getattr(prepared.reconciliation, "resolved_args", {})

    def one_handle(arg_name: str) -> str:
        values = tuple(resolved_args.get(arg_name, ()))
        if len(values) != 1:
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                f"quadratic-square Macro requires one {arg_name}",
                retryability="configuration",
                details={"arg": arg_name, "count": len(values)},
            )
        return str(values[0].handle)

    parabola_values = tuple(resolved_args.get("parabola", ()))
    parabola_refs = tuple(
        dict.fromkeys(
            str(value.object_ref)
            for value in parabola_values
            if value.object_ref is not None
        )
    )
    if len(parabola_refs) != 1:
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "quadratic-square Macro requires one parabola object identity",
            retryability="configuration",
            details={"candidate_count": len(parabola_refs)},
        )
    context = MappingProxyType(
        {
            "path_minimum_target": one_handle("path_minimum_target"),
            "square": one_handle("square"),
            "parabola_ref": parabola_refs[0],
            "scope_id": request.scope_id,
            "handle_registry": handle_registry,
        }
    )
    dependency_envelope = {
        context["path_minimum_target"],
        context["square"],
        context["parabola_ref"],
    }
    for values in resolved_args.values():
        dependency_envelope.update(
            value.handle for value in values if getattr(value, "handle", None)
        )
        dependency_envelope.update(
            value.object_ref
            for value in values
            if getattr(value, "object_ref", None)
        )
    return MacroImplementationPreparationContext(
        payload=context,
        candidate_dependency_envelope=tuple(sorted(dependency_envelope)),
    )


def _build_quadratic_square_path_candidates(
    request: MacroPreparationRequest,
) -> Sequence[MacroRoleAssignmentCandidate]:
    from shuxueshuo_server.solver.runtime.quadratic_square_path_roles import (
        QuadraticSquarePathRoleError,
        build_quadratic_square_path_role_candidates,
    )

    context = request.builder_context
    if not isinstance(context, Mapping):
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "quadratic-square candidate builder requires structured Context",
            retryability="configuration",
        )
    try:
        candidates = build_quadratic_square_path_role_candidates(
            path_minimum_target=str(context["path_minimum_target"]),
            square=str(context["square"]),
            parabola_ref=str(context["parabola_ref"]),
            scope_id=str(context["scope_id"]),
            registry=context["handle_registry"],
        )
    except (QuadraticSquarePathRoleError, KeyError) as exc:
        raise MacroRuntimeSearchError(
            "functional.macro_search_no_structural_candidate",
            str(exc),
            retryability="planner_repairable",
            details={
                "macro_id": "quadratic_square_path_minimum",
                "repair_action": (
                    "select_a_compatible_quadratic_path_and_square_or_choose_"
                    "another_capability"
                ),
                **(exc.details if isinstance(exc, QuadraticSquarePathRoleError) else {}),
            },
        ) from exc
    if not candidates:
        raise MacroRuntimeSearchError(
            "functional.macro_search_no_structural_candidate",
            (
                "the selected quadratic state, path target and square do not "
                "form a supported square path-minimum mechanism"
            ),
            retryability="planner_repairable",
            details={
                "macro_id": "quadratic_square_path_minimum",
                "public_args": ["parabola", "path_minimum_target", "square"],
                "repair_action": (
                    "select_a_compatible_quadratic_path_and_square_or_choose_"
                    "another_capability"
                ),
            },
        )
    return tuple(
        MacroRoleAssignmentCandidate(
            candidate_id=item.candidate_id,
            roles={
                role: getattr(item, role)
                for role in (
                    "midpoint_definition",
                    "square_center",
                    "axis_membership",
                    "side_start",
                    "axis_point",
                    "moving_point",
                    "fixed_endpoint",
                )
            },
            dependency_handles=tuple(item.to_payload().values()),
            fact_handles={
                role: getattr(item, role)
                for role in (
                    "midpoint_definition",
                    "square_center",
                    "axis_membership",
                )
            },
        )
        for item in candidates
    )


def _lower_quadratic_square_path_candidate(
    value: Any,
    authority: MacroCandidateBindingAuthority,
) -> Any:
    lower = getattr(value, "with_macro_roles", None)
    return lower(dict(authority.candidate.roles)) if callable(lower) else value


def _quadratic_square_path_postcondition(value: Any) -> Sequence[str]:
    return tuple(
        str(getattr(item, "name", item))
        for item in getattr(value, "checks", ())
        if bool(getattr(item, "ok", True))
    )


def _quadratic_square_path_evidence(*args: Any, **kwargs: Any) -> Any:
    from shuxueshuo_server.solver.runtime.quadratic_square_path_evidence import (
        build_quadratic_square_path_execution_witness,
    )

    return build_quadratic_square_path_execution_witness(*args, **kwargs)


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
    context["point_name_candidates"] = (
        build_equal_length_ray_point_name_candidates(
            point_handles=point_handles,
            entity_payloads=handle_registry.entity_payloads,
        )
    )
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
    return build_equal_length_ray_macro_role_candidates(
        request.builder_context,
    )


def build_equal_length_ray_macro_role_candidates(
    context: Mapping[str, Any] | object,
) -> tuple[MacroRoleAssignmentCandidate, ...]:
    """Build structured role candidates through the Macro-owned entrypoint."""

    from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
        EqualLengthRayRoleError,
        build_equal_length_ray_role_candidates,
    )

    if not isinstance(context, Mapping):
        raise ValueError(
            "planner.macro_contract_invalid: equal-length candidate builder "
            "requires structured Context"
        )
    entity_payloads = context.get("entity_payloads")
    point_name_candidates = context.get("point_name_candidates")
    if not isinstance(entity_payloads, Mapping) or not isinstance(
        point_name_candidates,
        Mapping,
    ):
        raise ValueError(
            "planner.macro_contract_invalid: incomplete equal-length builder Context"
        )

    normalized_names: dict[str, tuple[str, ...]] = {}
    for raw_name, raw_handles in point_name_candidates.items():
        if (
            not isinstance(raw_name, str)
            or not raw_name
            or not isinstance(raw_handles, Sequence)
            or isinstance(raw_handles, (str, bytes))
        ):
            raise ValueError(
                "planner.macro_contract_invalid: invalid point-name authority"
            )
        handles = tuple(
            sorted(
                {
                    str(handle)
                    for handle in raw_handles
                    if isinstance(handle, str) and handle
                }
            )
        )
        if len(handles) != len(raw_handles) or not handles:
            raise ValueError(
                "planner.macro_contract_invalid: invalid point-name candidates"
            )
        normalized_names[raw_name] = handles

    def resolve_point_name(name: str) -> str:
        matches = normalized_names.get(name, ())
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise EqualLengthRayRoleError(
                "point_name_unresolved",
                "structured role point name is not visible",
                details={"name": name, "candidate_count": 0},
            )
        raise EqualLengthRayRoleError(
            "point_name_ambiguous",
            "structured role point name resolves to multiple visible objects",
            details={
                "name": name,
                "candidate_count": len(matches),
                "candidates": matches,
            },
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

    try:
        candidates = build_equal_length_ray_role_candidates(
            ray_facts=fact_group("ray_facts"),
            segment_facts=fact_group("segment_facts"),
            equal_facts=fact_group("equal_facts"),
            target_facts=fact_group("target_facts"),
            entity_payload=lambda handle: entity_payloads[handle],
            visible_point_handles=tuple(
                handle
                for handles in normalized_names.values()
                for handle in handles
            ),
            resolve_point_name=resolve_point_name,
            max_candidates=int(context.get("max_candidates", 32)),
        )
    except EqualLengthRayRoleError as exc:
        code = {
            "point_name_ambiguous": "planner.macro_point_name_ambiguous",
            "point_name_unresolved": "planner.macro_point_name_unresolved",
        }.get(exc.code, "planner.macro_contract_invalid")
        raise MacroRuntimeSearchError(
            code,
            str(exc),
            retryability="configuration",
            details={
                "macro_id": "equal_length_ray_path_reduction",
                **exc.details,
            },
        ) from exc
    if not candidates:
        raise MacroRuntimeSearchError(
            "functional.macro_search_no_structural_candidate",
            (
                "The selected path target, equal-length condition, segment "
                "membership, and ray membership do not form a valid "
                "equal-length ray path reduction"
            ),
            retryability="planner_repairable",
            details={
                "macro_id": "equal_length_ray_path_reduction",
                "public_args": [
                    "path_minimum_target",
                    "equal_length_condition",
                    "point_on_segment",
                    "point_on_ray",
                ],
                "repair_action": (
                    "select_four_compatible_structured_facts_or_choose_"
                    "another_capability"
                ),
            },
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


def build_equal_length_ray_point_name_candidates(
    *,
    point_handles: Iterable[str],
    entity_payloads: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, tuple[str, ...]]:
    """Preserve every visible object behind a student-facing point label."""

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
    "MacroMethodInputBindingSpec",
    "MacroPreparationEnvironment",
    "MacroPreparationAuthority",
    "MacroPreparationRequest",
    "MacroPreparationService",
    "MacroRoleAssignmentCandidate",
    "PreparedMacroInvocation",
    "build_equal_length_ray_macro_role_candidates",
    "build_equal_length_ray_point_name_candidates",
    "default_macro_implementation_registry",
]
