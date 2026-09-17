"""Pure, version-pinned runtime binding and separate Solver admission."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityToken,
    audit_runtime_projection,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    freeze_json,
    stable_hash,
    thaw_json,
)
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input

from .runtime_lowering import BindingError, NotationRuntimeLowerer

# Registered per mathematical family, never per problem id or frozen example.
NOTATION_RUNTIME_ADAPTERS = MappingProxyType(
    {
        "QuadraticPathMinimumSolver": NotationRuntimeLowerer,
        "QuadraticEqualLengthRayPathMinimumSolver": NotationRuntimeLowerer,
        "QuadraticSquareReflectionPathMinimumSolver": NotationRuntimeLowerer,
        "QuadraticWeightedPathMinimumSolver": NotationRuntimeLowerer,
    }
)


@dataclass(frozen=True)
class NotationRuntimeBundle:
    """Code-owned projection. Only admission may expose it to solve_verified."""

    authority_token: ProblemBundleAuthorityToken
    source_graph: Any
    source_unit_registry: Mapping
    canonical_solver_input: Mapping
    projection_manifest: Any
    projection_index: Any
    candidate: Mapping
    provenance: Mapping
    motion_bindings: tuple = ()
    source_artifact_ids: tuple = ()
    admission_evidence: Mapping | None = None

    def assert_solver_ready(self):
        if self.admission_evidence is None:
            raise BindingError(
                "admission.source_review_required",
                "/source_review",
                "binding alone does not authorize Solver execution",
            )

    @property
    def problem_id(self):
        return self.source_graph.problem_id

    @property
    def family_id(self):
        return self.source_graph.family_id

    def build_solver_problem(self):
        return problem_from_canonical_input(thaw_json(self.canonical_solver_input))

    def authority_payload(self):
        return {
            **self.authority_token.to_payload(),
            "family_id": self.family_id,
            "source_contract": "problem-math-notation/v1",
            "admission_evidence": thaw_json(self.admission_evidence),
        }


@dataclass(frozen=True)
class RuntimeBinding:
    bundle: NotationRuntimeBundle
    planning_context: Any
    planner_state_context: Any
    binding_catalog: Any
    handle_registry: Any
    inputs: Any
    source_identity: Mapping
    compiled_objects: tuple
    compiled_tree: Mapping

    def artifacts(self):
        initial = self.planner_state_context.to_payload()
        index = self.bundle.projection_index.runtime_node_source_units
        state_sources = []
        for kind, records in (
            ("state", initial["state"]["state_slots"]),
            ("condition", initial["state"]["conditions"]),
        ):
            for record in records:
                units = index.get(record["canonical_handle"], ())
                rule = "canonical_projection"
                if (
                    not units
                    and kind == "condition"
                    and record["kind"] == "point_on_curve"
                ):
                    points = record.get("object_roles", {}).get("point", [])
                    curves = record.get("object_roles", {}).get("curve", [])
                    definition = next(
                        (
                            e
                            for e in self.bundle.canonical_solver_input["entities"]
                            if e["handle"] in points
                            and e.get("of") in curves
                            and e.get("definition")
                            in (
                                "vertex",
                                "y_axis_intercept",
                                "x_axis_intercept",
                                "point_on_parabola_at_x",
                            )
                        ),
                        None,
                    )
                    if definition is not None:
                        units = tuple(
                            sorted(
                                set(index[definition["handle"]])
                                | set(index[definition["of"]])
                            )
                        )
                        rule = "point_definition_implies_curve_membership"
                if not units:
                    raise BindingError(
                        "binding.initial_state_source_missing",
                        "/root",
                        record["canonical_handle"],
                    )
                state_sources.append(
                    {
                        "kind": kind,
                        "id": record.get("slot_id", record.get("condition_id")),
                        "rule": rule,
                        "scope_id": record["scope_id"],
                        "source_unit_ids": list(units),
                        "source_paths": sorted(
                            {self.bundle.provenance[u]["path"] for u in units}
                        ),
                    }
                )
        return {
            "canonical-input.json": thaw_json(self.bundle.canonical_solver_input),
            "projection-manifest.json": self.bundle.projection_manifest.to_payload(),
            "source-map.json": thaw_json(self.bundle.provenance),
            "motion-bindings.json": thaw_json(self.bundle.motion_bindings),
            "candidate-identity.json": thaw_json(self.source_identity),
            "compiled-objects.json": thaw_json(self.compiled_objects),
            "compiled-relations.json": thaw_json(self.compiled_tree),
            "initial-state.json": initial,
            "initial-state-source-map.json": {
                "source_identity": thaw_json(self.source_identity),
                "entries": state_sources,
            },
            "planning-context.json": self.planning_context.authority_payload(),
            "binding-catalog.json": self.binding_catalog.authority_payload(),
        }


def bind_notation(
    candidate, *, problem_id, candidate_id, source_version_id, source_hash
):
    from shuxueshuo_server.solver.extraction.problem_domain import ProblemDomainError
    from shuxueshuo_server.solver.extraction.problem_planning_binding import (
        ProblemPlanningBindingError,
    )
    from shuxueshuo_server.solver.extraction.problem_planning_context import (
        ProblemPlanningContextError,
    )
    from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
        ProblemBundleAuthorityError,
    )

    try:
        return _bind_notation(
            candidate,
            problem_id=problem_id,
            candidate_id=candidate_id,
            source_version_id=source_version_id,
            source_hash=source_hash,
        )
    except (
        ProblemDomainError,
        ProblemPlanningBindingError,
        ProblemPlanningContextError,
        ProblemBundleAuthorityError,
    ) as error:
        raise BindingError(error.code, "/root", str(error)) from error


def _bind_notation(
    candidate, *, problem_id, candidate_id, source_version_id, source_hash
):
    """Deterministic adaptation, also usable offline without claiming review."""
    from shuxueshuo_server.solver.extraction.problem_ir_runtime_preflight import (
        ProblemIRRuntimeReadinessValidator,
    )
    from shuxueshuo_server.solver.extraction.problem_planning_binding import (
        ProblemPlanningBindingCatalogBuilder,
    )
    from shuxueshuo_server.solver.extraction.problem_planning_context import (
        ProblemPlanningContextProjector,
    )
    from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
    from shuxueshuo_server.solver.runtime.binding_index import (
        CanonicalRuntimeBindingIndex,
    )
    from shuxueshuo_server.solver.runtime.context import ContextBuilder
    from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
    from shuxueshuo_server.solver.runtime.planner_state_context import (
        initial_planner_state_context,
    )
    from shuxueshuo_server.solver.runtime.strategy_models import (
        StrategyDraftValidationError,
    )
    from shuxueshuo_server.solver.runtime.strategy_payload import (
        build_strategy_probe_inputs,
    )

    if candidate.get("match_status") != "matched":
        raise BindingError(
            "admission.family_unmatched",
            "/family_id",
            "candidate has no supported family",
        )
    family = next(
        (
            f
            for f in DEFAULT_FAMILY_REGISTRY.families
            if f.family_id == candidate.get("family_id")
        ),
        None,
    )
    if family is None:
        raise BindingError("admission.family_unmatched", "/family_id", "unknown family")
    adapter = NOTATION_RUNTIME_ADAPTERS.get(family.family_id)
    if adapter is None:
        raise BindingError(
            "admission.adapter_missing",
            "/family_id",
            "no mathematical runtime adapter registered for this family",
        )
    lower = adapter().lower(candidate, problem_id=problem_id)

    # Missing images/uncertainties block regardless of whether their AST compiled.
    def check(scope, path):
        if scope.get("uncertainties"):
            raise BindingError(
                "admission.unresolved_source",
                path + "/uncertainties",
                "source uncertainties require resolution",
            )
        for i, c in enumerate(scope.get("children", [])):
            check(c, f"{path}/children/{i}")

    check(candidate["root"], "/root")
    identity = {
        "problem_id": problem_id,
        "candidate_id": candidate_id,
        "candidate_hash": stable_hash(candidate),
        "source_version_id": source_version_id,
        "source_hash": source_hash,
    }
    for provenance in lower.provenance.values():
        provenance["source_identity"] = identity
    revision = "problem-revision:" + stable_hash(identity)
    semantic_hash = stable_hash(lower.report.semantic)
    projection = ProblemDomainProjector().project_graph(
        lower.graph, revision_id=revision, semantic_hash=semantic_hash
    )
    index = audit_runtime_projection(
        projection, {k: v.to_payload() for k, v in lower.units.items()}
    )
    token = ProblemBundleAuthorityToken(
        "notation-binding:" + stable_hash(identity),
        stable_hash(identity),
        revision,
        semantic_hash,
        "notation-bundle:" + stable_hash([identity, projection.to_payload()]),
    )
    bundle = NotationRuntimeBundle(
        token,
        lower.graph,
        MappingProxyType(dict(lower.units)),
        freeze_json(projection.canonical_input),
        projection.manifest,
        index,
        freeze_json(candidate),
        freeze_json(lower.provenance),
        freeze_json(lower.motion_bindings),
    )
    problem = bundle.build_solver_problem()
    if DEFAULT_FAMILY_REGISTRY.match(problem) != family:
        raise BindingError(
            "admission.family_mismatch",
            "/family_id",
            "runtime family differs from candidate",
        )
    for requirement in family.required_source_requirements:
        collection = projection.canonical_input[
            "entities" if requirement.primitive_kind == "entity_type" else "facts"
        ]
        key = "entity_type" if requirement.primitive_kind == "entity_type" else "type"
        if (
            sum(item.get(key) in requirement.primitive_types for item in collection)
            < requirement.min_count
        ):
            raise BindingError(
                "admission.family_source_missing", "/root", requirement.description
            )
    inputs = build_strategy_probe_inputs(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(projection.canonical_input)
    context = ContextBuilder().build(problem)
    try:
        CanonicalRuntimeBindingIndex.from_context(
            context, handle_registry=registry, question_goals=inputs.question_goals
        )
    except StrategyDraftValidationError as error:
        raise BindingError(
            "binding.source_input_unavailable", "/root", str(error)
        ) from error
    state = initial_planner_state_context(
        inputs, problem_payload=projection.canonical_input, handle_registry=registry
    )
    planning = ProblemPlanningContextProjector().project(bundle)
    catalog = ProblemPlanningBindingCatalogBuilder().build(
        bundle, planning, state, registry
    )
    issues = ProblemIRRuntimeReadinessValidator().validate(
        projection.canonical_input, problem=problem, family=family, context=context
    )
    if issues:
        issue = issues[0]
        raise BindingError(issue.code, issue.path, issue.message)
    return RuntimeBinding(
        bundle,
        planning,
        state,
        catalog,
        registry,
        inputs,
        freeze_json(identity),
        freeze_json(lower.report.objects),
        freeze_json(lower.report.semantic),
    )


@dataclass(frozen=True)
class AdmissionEvidence:
    candidate_id: str
    candidate_hash: str
    source_version_id: str
    source_hash: str
    review_run_id: str
    review_current: bool


def authorize_binding(binding, evidence):
    """Admission evidence must come from the product's owned current snapshot."""
    from shuxueshuo_server.solver.extraction.problem_planner_authority import (
        VerifiedPlannerProblemAuthority,
    )

    expected = binding.source_identity
    for key in ("candidate_id", "candidate_hash", "source_version_id", "source_hash"):
        if str(getattr(evidence, key)) != str(expected[key]):
            raise BindingError(
                "admission.version_changed",
                "/" + key,
                "review and binding identify different inputs",
            )
    if not evidence.review_current or not evidence.review_run_id:
        raise BindingError(
            "admission.source_review_required",
            "/source_review",
            "a current confirmed source review is required",
        )
    return VerifiedPlannerProblemAuthority(
        bundle=replace(binding.bundle, admission_evidence=freeze_json(vars(evidence))),
        planning_context=binding.planning_context,
    )
