"""Trusted loading boundary between extraction and the Solver runtime."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ProblemExtractionContext,
    SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
    validate_problem_extraction_context,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDomainError,
    ProblemValidationReport,
    VerifiedProblem,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    RuntimeProjectionManifest,
    SolverProblemProjection,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    freeze_json,
    stable_hash,
    thaw_json,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY, FamilyRegistry
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input


class BundleArtifactReader(Protocol):
    def read_bytes(self, artifact: ExtractionArtifactRef) -> bytes: ...


class ProblemBundleAuthorityError(ValueError):
    """A non-retryable failure while authenticating an accepted problem."""

    retryable = False

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class ProblemBundleAuthorityToken:
    extraction_context_id: str
    dependency_hash: str
    problem_revision_id: str
    problem_semantic_hash: str
    bundle_id: str

    def to_payload(self) -> dict[str, str]:
        return {
            "extraction_context_id": self.extraction_context_id,
            "dependency_hash": self.dependency_hash,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "bundle_id": self.bundle_id,
        }


@dataclass(frozen=True)
class ProblemBundleArtifactRefs:
    verified_problem: ExtractionArtifactRef
    solver_problem_projection: ExtractionArtifactRef
    validation_report: ExtractionArtifactRef

    def authority_payload(self) -> dict[str, Any]:
        return {
            "verified_problem": self.verified_problem.authority_payload(),
            "solver_problem_projection": (
                self.solver_problem_projection.authority_payload()
            ),
            "validation_report": self.validation_report.authority_payload(),
        }


@dataclass(frozen=True)
class RuntimeProjectionIndex:
    runtime_node_source_units: Mapping[str, tuple[str, ...]]
    source_unit_runtime_nodes: Mapping[str, tuple[str, ...]]
    scope_runtime_id_by_unit: Mapping[str, str]
    goal_answer_handle_by_unit: Mapping[str, str]
    value_object_handles: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "runtime_node_source_units",
            _freeze_tuple_mapping(self.runtime_node_source_units),
        )
        object.__setattr__(
            self,
            "source_unit_runtime_nodes",
            _freeze_tuple_mapping(self.source_unit_runtime_nodes),
        )
        object.__setattr__(
            self,
            "scope_runtime_id_by_unit",
            MappingProxyType(dict(sorted(self.scope_runtime_id_by_unit.items()))),
        )
        object.__setattr__(
            self,
            "goal_answer_handle_by_unit",
            MappingProxyType(dict(sorted(self.goal_answer_handle_by_unit.items()))),
        )
        object.__setattr__(
            self,
            "value_object_handles",
            tuple(sorted(set(self.value_object_handles))),
        )


@dataclass(frozen=True)
class VerifiedSolverProblemBundle:
    authority_token: ProblemBundleAuthorityToken
    verified_problem: VerifiedProblem
    canonical_solver_input: Mapping[str, Any]
    validation_report: ProblemValidationReport
    projection_manifest: RuntimeProjectionManifest
    projection_index: RuntimeProjectionIndex
    artifact_refs: ProblemBundleArtifactRefs

    def __post_init__(self) -> None:
        frozen = freeze_json(self.canonical_solver_input)
        if not isinstance(frozen, Mapping):
            raise TypeError("canonical Solver input must be an object")
        object.__setattr__(self, "canonical_solver_input", frozen)

    def build_solver_problem(self) -> ProblemIR:
        """Materialize a fresh runtime object; bundle state remains immutable."""

        payload = thaw_json(self.canonical_solver_input)
        assert isinstance(payload, Mapping)
        return problem_from_canonical_input(payload)

    def authority_payload(self) -> dict[str, Any]:
        return {
            **self.authority_token.to_payload(),
            "family_id": self.verified_problem.family_id,
            "artifacts": self.artifact_refs.authority_payload(),
        }


class VerifiedSolverProblemBundleLoader:
    def __init__(self, *, family_registry: FamilyRegistry = DEFAULT_FAMILY_REGISTRY) -> None:
        self.family_registry = family_registry

    def load(
        self,
        context: ProblemExtractionContext,
        artifact_reader: BundleArtifactReader,
        *,
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
        expected_token: ProblemBundleAuthorityToken | None = None,
    ) -> VerifiedSolverProblemBundle:
        self._validate_context(context, ancestor_contexts)
        refs = self._artifact_refs(context)
        verified_payload = _read_json_artifact(
            artifact_reader,
            refs.verified_problem,
            expected_kind="verified_problem",
            path="$.projection.verified_problem_artifact_id",
        )
        projection_payload = _read_json_artifact(
            artifact_reader,
            refs.solver_problem_projection,
            expected_kind=SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
            path="$.projection.solver_problem_ir_artifact_id",
        )
        validation_payload = _read_json_artifact(
            artifact_reader,
            refs.validation_report,
            expected_kind="problem_validation_report",
            path="$.projection.validation_artifact_id",
        )

        verified = self._hydrate_verified(verified_payload)
        projection = self._hydrate_projection(projection_payload)
        validation = self._hydrate_validation(validation_payload)
        self._validate_cross_artifact_authority(
            context,
            verified=verified,
            projection=projection,
            validation=validation,
        )
        projection_index = _audit_projection_manifest(verified, projection)
        self._validate_family(verified, projection)

        bundle_authority = {
            "extraction_context_id": context.manifest.context_id,
            "dependency_hash": context.dependency.dependency_hash,
            "problem_revision_id": verified.revision_id,
            "problem_semantic_hash": verified.semantic_hash,
            "family_id": verified.family_id,
            "artifacts": refs.authority_payload(),
        }
        token = ProblemBundleAuthorityToken(
            extraction_context_id=context.manifest.context_id,
            dependency_hash=context.dependency.dependency_hash,
            problem_revision_id=verified.revision_id,
            problem_semantic_hash=verified.semantic_hash,
            bundle_id="verified-solver-problem-bundle:" + stable_hash(bundle_authority),
        )
        if expected_token is not None and token != expected_token:
            raise _error(
                "planner.problem_revision_drift",
                "$.authority_token",
                "accepted problem authority differs from the expected bundle token",
            )
        return VerifiedSolverProblemBundle(
            authority_token=token,
            verified_problem=verified,
            canonical_solver_input=projection.canonical_input,
            validation_report=validation,
            projection_manifest=projection.manifest,
            projection_index=projection_index,
            artifact_refs=refs,
        )

    @staticmethod
    def _validate_context(
        context: ProblemExtractionContext,
        ancestor_contexts: Sequence[ProblemExtractionContext],
    ) -> None:
        try:
            validate_problem_extraction_context(
                context,
                ancestor_contexts=ancestor_contexts,
            )
        except ProblemExtractionContextError as exc:
            raise _error(
                "planner.problem_bundle_invalid",
                exc.path,
                exc.message,
            ) from exc
        if context.projection.status != "accepted":
            raise _error(
                "planner.problem_bundle_invalid",
                "$.projection.status",
                "only an accepted extraction Context can form a Solver bundle",
            )
        if context.retry.status != "complete":
            raise _error(
                "planner.problem_bundle_invalid",
                "$.retry.status",
                "accepted extraction Context must have complete retry state",
            )
        acceptance_events = tuple(
            item
            for item in context.events
            if item.event == "problem_domain_accepted"
        )
        if len(acceptance_events) != 1:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.events",
                "accepted extraction Context must contain exactly one acceptance event",
            )
        expected_event = {
            "problem_revision_id": context.projection.problem_revision_id,
            "problem_semantic_hash": context.projection.problem_semantic_hash,
            "family_id": context.projection.family_id,
        }
        if thaw_json(acceptance_events[0].payload) != expected_event:
            raise _error(
                "planner.problem_revision_drift",
                "$.events[problem_domain_accepted].payload",
                "acceptance event authority differs from Context projection",
            )

    @staticmethod
    def _artifact_refs(context: ProblemExtractionContext) -> ProblemBundleArtifactRefs:
        by_id = {item.artifact_id: item for item in context.state.artifacts}
        projection = context.projection
        assert projection.verified_problem_artifact_id is not None
        assert projection.solver_problem_projection_artifact_id is not None
        assert projection.validation_artifact_id is not None
        try:
            return ProblemBundleArtifactRefs(
                verified_problem=by_id[projection.verified_problem_artifact_id],
                solver_problem_projection=by_id[
                    projection.solver_problem_projection_artifact_id
                ],
                validation_report=by_id[projection.validation_artifact_id],
            )
        except KeyError as exc:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.state.artifacts",
                f"accepted bundle artifact is missing: {exc.args[0]}",
            ) from exc

    @staticmethod
    def _hydrate_verified(payload: Mapping[str, Any]) -> VerifiedProblem:
        _require_exact_keys(
            payload,
            {
                "schema_version",
                "graph",
                "revision_id",
                "parent_revision_id",
                "semantic_hash",
                "family_id",
                "unit_registry",
                "verification_proof",
            },
            "$.verified_problem",
        )
        try:
            verified = VerifiedProblem.from_payload(payload)
        except ProblemDomainError as exc:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.verified_problem" + exc.path.removeprefix("$"),
                exc.message,
            ) from exc
        if verified.to_payload() != payload:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.verified_problem",
                "VerifiedProblem artifact is not canonical",
            )
        return verified

    @staticmethod
    def _hydrate_projection(payload: Mapping[str, Any]) -> SolverProblemProjection:
        try:
            projection = SolverProblemProjection.from_payload(payload)
        except ProblemDomainError as exc:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.solver_problem_projection" + exc.path.removeprefix("$"),
                exc.message,
            ) from exc
        if projection.to_payload() != payload:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.solver_problem_projection",
                "Solver projection artifact is not canonical",
            )
        return projection

    @staticmethod
    def _hydrate_validation(payload: Mapping[str, Any]) -> ProblemValidationReport:
        _require_exact_keys(
            payload,
            {"ok", "validator_ids", "issue_signature", "issues"},
            "$.validation_report",
        )
        try:
            report = ProblemValidationReport.from_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.validation_report",
                str(exc),
            ) from exc
        if report.to_payload() != payload or not report.ok:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.validation_report",
                "accepted validation report is invalid, non-canonical, or unsuccessful",
            )
        return report

    @staticmethod
    def _validate_cross_artifact_authority(
        context: ProblemExtractionContext,
        *,
        verified: VerifiedProblem,
        projection: SolverProblemProjection,
        validation: ProblemValidationReport,
    ) -> None:
        manifest = projection.manifest
        context_projection = context.projection
        authority_values = {
            "problem_revision_id": {
                str(context_projection.problem_revision_id),
                verified.revision_id,
                manifest.problem_revision_id,
            },
            "problem_semantic_hash": {
                str(context_projection.problem_semantic_hash),
                verified.semantic_hash,
                manifest.problem_semantic_hash,
            },
            "family_id": {
                str(context_projection.family_id),
                verified.family_id,
                manifest.family_id,
            },
            "problem_id": {
                verified.graph.problem_id,
                manifest.problem_id,
                str(projection.canonical_input["problem_id"]),
            },
        }
        for field, values in authority_values.items():
            if len(values) != 1:
                raise _error(
                    "planner.problem_revision_drift",
                    f"$.{field}",
                    f"{field} differs across accepted bundle artifacts",
                )
        proof = thaw_json(verified.verification_proof)
        if not isinstance(proof, Mapping) or proof.get("validation_report") != validation.to_payload():
            raise _error(
                "planner.problem_bundle_invalid",
                "$.validation_report",
                "validation artifact differs from VerifiedProblem proof",
            )

    def _validate_family(
        self,
        verified: VerifiedProblem,
        projection: SolverProblemProjection,
    ) -> None:
        selected = next(
            (
                family
                for family in self.family_registry.families
                if family.family_id == verified.family_id
            ),
            None,
        )
        if selected is None or not selected.supports(projection.problem):
            raise _error(
                "planner.problem_bundle_invalid",
                "$.family_id",
                "selected family is unknown or does not support canonical Solver input",
            )
        try:
            matched = self.family_registry.match(projection.problem)
        except ValueError as exc:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.family_id",
                str(exc),
            ) from exc
        if matched is None or matched.family_id != selected.family_id:
            raise _error(
                "planner.problem_bundle_invalid",
                "$.family_id",
                "canonical Solver input does not uniquely admit the selected family",
            )


def _audit_projection_manifest(
    verified: VerifiedProblem,
    projection: SolverProblemProjection,
) -> RuntimeProjectionIndex:
    canonical = projection.canonical_input
    manifest = projection.manifest
    runtime_nodes: dict[str, tuple[str, Mapping[str, Any]]] = {}

    for scope in _mapping_sequence(canonical.get("scopes"), "$.canonical_input.scopes"):
        scope_id = str(scope["scope_id"])
        _add_runtime_node(runtime_nodes, f"scope:{scope_id}", "scope", scope)
    for collection, kind in (
        ("entities", "entity"),
        ("facts", "fact"),
        ("question_goals", "goal"),
    ):
        for item in _mapping_sequence(
            canonical.get(collection),
            f"$.canonical_input.{collection}",
        ):
            _add_runtime_node(runtime_nodes, str(item["handle"]), kind, item)

    manifest_nodes = set(manifest.runtime_node_sources)
    expected_nodes = set(runtime_nodes)
    if manifest_nodes != expected_nodes:
        missing = sorted(expected_nodes - manifest_nodes)
        unexpected = sorted(manifest_nodes - expected_nodes)
        detail = f"missing={missing[:1]}, unexpected={unexpected[:1]}"
        raise _error(
            "planner.problem_projection_manifest_drift",
            "$.manifest.runtime_node_sources",
            "manifest runtime node set differs from canonical input: " + detail,
        )

    verified_payload = verified.to_payload()
    unit_registry = {
        str(item["unit_id"]): item
        for item in _mapping_sequence(
            verified_payload.get("unit_registry"),
            "$.verified_problem.unit_registry",
        )
    }
    required_unit_ids = {
        unit_id
        for unit_id, record in unit_registry.items()
        if record.get("unit_kind") != "family"
    }
    reverse: dict[str, set[str]] = {unit_id: set() for unit_id in required_unit_ids}
    scope_ids: dict[str, str] = {}
    goal_handles: dict[str, str] = {}
    value_handles = set(manifest.value_object_sources)
    entity_handles = {
        runtime_id
        for runtime_id, (kind, _) in runtime_nodes.items()
        if kind == "entity"
    }
    for runtime_id, source_ids in manifest.runtime_node_sources.items():
        unknown = sorted(set(source_ids) - set(unit_registry))
        if unknown:
            raise _error(
                "planner.problem_projection_manifest_drift",
                f"$.manifest.runtime_node_sources[{runtime_id!r}]",
                f"manifest references unknown source unit {unknown[0]!r}",
            )
    synthesized_value_handles = {
        runtime_id
        for runtime_id, (kind, _) in runtime_nodes.items()
        if kind == "entity"
        and {
            str(unit_registry[source_id]["unit_kind"])
            for source_id in manifest.runtime_node_sources[runtime_id]
        }.issubset({"fact", "goal"})
    }
    if value_handles != synthesized_value_handles:
        raise _error(
            "planner.problem_projection_manifest_drift",
            "$.manifest.value_object_sources",
            "value-object mapping differs from synthesized canonical entities",
        )

    for runtime_id, source_ids in manifest.runtime_node_sources.items():
        if not source_ids or tuple(source_ids) != tuple(sorted(set(source_ids))):
            raise _error(
                "planner.problem_projection_manifest_drift",
                f"$.manifest.runtime_node_sources[{runtime_id!r}]",
                "source ids must be non-empty, unique, and sorted",
            )
        node_kind, node = runtime_nodes[runtime_id]
        source_kinds = [str(unit_registry[item]["unit_kind"]) for item in source_ids]
        _validate_node_source_kinds(
            runtime_id,
            node_kind,
            source_kinds,
            value_object=runtime_id in synthesized_value_handles,
        )
        for source_id in source_ids:
            if source_id in reverse:
                reverse[source_id].add(runtime_id)
        if node_kind == "scope":
            scope_unit = source_ids[0]
            if scope_unit in scope_ids:
                raise _error(
                    "planner.problem_projection_manifest_drift",
                    f"$.manifest.runtime_node_sources[{runtime_id!r}]",
                    f"scope unit {scope_unit!r} maps to multiple runtime scopes",
                )
            scope_ids[scope_unit] = str(node["scope_id"])
        elif node_kind == "goal":
            goal_unit = source_ids[0]
            if goal_unit in goal_handles:
                raise _error(
                    "planner.problem_projection_manifest_drift",
                    f"$.manifest.runtime_node_sources[{runtime_id!r}]",
                    f"Goal unit {goal_unit!r} maps to multiple answer handles",
                )
            goal_handles[goal_unit] = runtime_id

    missing_units = sorted(
        unit_id for unit_id, runtime_ids in reverse.items() if not runtime_ids
    )
    if missing_units:
        raise _error(
            "planner.problem_projection_manifest_drift",
            "$.manifest.runtime_node_sources",
            f"source unit has no runtime projection {missing_units[0]!r}",
        )

    if not value_handles.issubset(entity_handles):
        raise _error(
            "planner.problem_projection_manifest_drift",
            "$.manifest.value_object_sources",
            "value-object mapping references a non-entity runtime node",
        )
    for runtime_id, source_ids in manifest.value_object_sources.items():
        if tuple(source_ids) != manifest.runtime_node_sources[runtime_id]:
            raise _error(
                "planner.problem_projection_manifest_drift",
                f"$.manifest.value_object_sources[{runtime_id!r}]",
                "value-object sources differ from runtime node sources",
            )
        kinds = {str(unit_registry[item]["unit_kind"]) for item in source_ids}
        if not kinds.issubset({"fact", "goal"}):
            raise _error(
                "planner.problem_projection_manifest_drift",
                f"$.manifest.value_object_sources[{runtime_id!r}]",
                "value-object sources must be Fact or Goal units",
            )

    return RuntimeProjectionIndex(
        runtime_node_source_units=manifest.runtime_node_sources,
        source_unit_runtime_nodes={
            key: tuple(sorted(value)) for key, value in reverse.items()
        },
        scope_runtime_id_by_unit=scope_ids,
        goal_answer_handle_by_unit=goal_handles,
        value_object_handles=tuple(sorted(value_handles)),
    )


def _validate_node_source_kinds(
    runtime_id: str,
    node_kind: str,
    source_kinds: Sequence[str],
    *,
    value_object: bool,
) -> None:
    kinds = set(source_kinds)
    valid = False
    if node_kind == "scope":
        valid = source_kinds == ["scope"]
    elif node_kind == "goal":
        valid = source_kinds == ["goal"]
    elif node_kind == "fact":
        valid = bool(kinds) and kinds.issubset({"fact"})
    elif node_kind == "entity":
        if value_object:
            valid = bool(kinds) and kinds.issubset({"fact", "goal"})
        else:
            valid = (
                source_kinds.count("entity") == 1
                and kinds.issubset({"entity", "fact"})
            )
    if not valid:
        raise _error(
            "planner.problem_projection_manifest_drift",
            f"$.manifest.runtime_node_sources[{runtime_id!r}]",
            f"{node_kind} runtime node has incompatible source kinds {source_kinds!r}",
        )


def _read_json_artifact(
    reader: BundleArtifactReader,
    artifact: ExtractionArtifactRef,
    *,
    expected_kind: str,
    path: str,
) -> Mapping[str, Any]:
    try:
        artifact.validate(path)
    except ProblemExtractionContextError as exc:
        raise _error("planner.problem_bundle_invalid", exc.path, exc.message) from exc
    if artifact.kind != expected_kind or artifact.media_type != "application/json":
        raise _error(
            "planner.problem_bundle_invalid",
            path,
            f"expected application/json artifact kind {expected_kind!r}",
        )
    try:
        content = reader.read_bytes(artifact)
    except (OSError, RuntimeError, ValueError) as exc:
        raise _error("planner.problem_bundle_invalid", path, str(exc)) from exc
    if sha256(content).hexdigest() != artifact.sha256:
        raise _error(
            "planner.problem_bundle_invalid",
            path,
            "artifact content hash mismatch",
        )
    if artifact.byte_size is not None and len(content) != artifact.byte_size:
        raise _error(
            "planner.problem_bundle_invalid",
            path,
            "artifact byte size mismatch",
        )
    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"unsupported JSON constant {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _error("planner.problem_bundle_invalid", path, f"invalid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise _error(
            "planner.problem_bundle_invalid",
            path,
            "artifact JSON must be an object",
        )
    return payload


def _unique_json_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _require_exact_keys(
    payload: Mapping[str, Any],
    expected: set[str],
    path: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise _error(
            "planner.problem_bundle_invalid",
            path,
            f"artifact fields differ: missing={sorted(expected - actual)}, "
            f"unexpected={sorted(actual - expected)}",
        )


def _mapping_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise _error(
            "planner.problem_projection_manifest_drift",
            path,
            "expected an array of objects",
        )
    return tuple(value)


def _add_runtime_node(
    result: dict[str, tuple[str, Mapping[str, Any]]],
    runtime_id: str,
    node_kind: str,
    payload: Mapping[str, Any],
) -> None:
    if runtime_id in result:
        raise _error(
            "planner.problem_projection_manifest_drift",
            "$.canonical_input",
            f"duplicate runtime node id {runtime_id!r}",
        )
    result[runtime_id] = (node_kind, payload)


def _freeze_tuple_mapping(
    value: Mapping[str, Sequence[str]],
) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType(
        {
            str(key): tuple(sorted({str(item) for item in values}))
            for key, values in sorted(value.items())
        }
    )


def _error(code: str, path: str, message: str) -> ProblemBundleAuthorityError:
    return ProblemBundleAuthorityError(code, path, message)
