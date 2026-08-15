"""Independent cross-scope and StateVersion reference model.

This module intentionally uses only the Python standard library.  It must not
import planner runtime services: the generated gate needs an oracle that can
disagree with production.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Any, Iterable, Literal, Mapping, Sequence


DependencyKind = Literal[
    "call_result",
    "state_version",
    "condition",
    "hidden_semantic_role",
]
WriteMode = Literal["create", "transition", "value"]
ProjectionKind = Literal["object", "answer", "object+answer", "call_local"]
RetryMode = Literal[
    "none",
    "committed_restore",
    "provisional_replacement",
    "version_drift",
]
StateReadMode = Literal["exact", "latest", "identity_only", "call_result"]


@dataclass(frozen=True)
class ModelScope:
    scope_id: str
    parent_scope_id: str | None


@dataclass(frozen=True)
class ModelObject:
    object_id: str
    kind: str
    origin_scope_id: str


@dataclass(frozen=True, order=True)
class ModelStateKey:
    object_id: str
    state_kind: str
    runtime_type: str

    @property
    def token(self) -> str:
        return f"{self.object_id}.{self.state_kind}:{self.runtime_type}"


@dataclass(frozen=True)
class ModelVersion:
    version_id: str
    state_key: ModelStateKey
    storage_scope_id: str
    valid_scope_id: str
    ordinal: int
    producer_call_id: str | None
    previous_version_id: str | None = None
    source_version_ids: tuple[str, ...] = ()
    computation_token: str | None = None
    effect_token: str | None = None
    runtime_destination: str | None = None
    free_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelDependency:
    producer_call_id: str
    consumer_call_id: str
    kind: DependencyKind
    version_id: str | None = None
    condition_id: str | None = None
    arg_name: str | None = None


@dataclass(frozen=True)
class ModelStateRead:
    mode: StateReadMode
    state_key: ModelStateKey
    arg_name: str = "input"
    version_id: str | None = None
    source_call_id: str | None = None


@dataclass(frozen=True)
class ModelCall:
    call_id: str
    declared_scope_id: str
    capability_key: str
    input_version_ids: tuple[str, ...] = ()
    input_condition_ids: tuple[str, ...] = ()
    state_reads: tuple[ModelStateRead, ...] = ()
    output_state_key: ModelStateKey | None = None
    requested_write_mode: WriteMode = "create"
    storage_scope_id: str | None = None
    valid_scope_id: str | None = None
    free_symbols: tuple[str, ...] = ()
    is_pure: bool = True
    is_shareable: bool = True
    answer_scope_ids: tuple[str, ...] = ()
    explicit_consumer_scope_ids: tuple[str, ...] = ()
    projection: ProjectionKind = "object"
    runtime_destination: str | None = None
    dead: bool = False
    forced_failure: bool = False


@dataclass(frozen=True)
class ModelRetryCheckpoint:
    mode: RetryMode
    committed_call_ids: tuple[str, ...] = ()
    committed_version_ids: tuple[str, ...] = ()
    provisional_call_ids: tuple[str, ...] = ()
    replacement_call_ids: tuple[str, ...] = ()
    expected_free_symbol_refs: tuple[str, ...] = ()
    expected_free_symbol_ids: tuple[str, ...] = ()
    observed_free_symbol_refs: tuple[str, ...] = ()
    observed_free_symbol_ids: tuple[str, ...] = ()
    expected_closure: "ModelClosureCheckpoint | None" = None
    observed_closure: "ModelClosureCheckpoint | None" = None


@dataclass(frozen=True)
class ModelClosureCheckpoint:
    status: str = "unique"
    target_value: str = "1"
    branch_count: int = 1
    equation_sources: tuple[str, ...] = ("equation",)
    residual_symbols: tuple[str, ...] = ()

    def semantic_signature(self) -> tuple[Any, ...]:
        return (
            self.status,
            _model_expression_signature(self.target_value),
            self.branch_count,
            tuple(sorted(self.equation_sources)),
            tuple(sorted(self.residual_symbols)),
        )


def _model_expression_signature(value: str) -> tuple[tuple[int, str], ...] | str:
    """Normalize additive order without importing the production algebra."""
    try:
        expression = ast.parse(value, mode="eval").body
    except (SyntaxError, ValueError):
        return value.strip()

    terms: list[tuple[int, str]] = []

    def collect(node: ast.AST, sign: int = 1) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            collect(node.left, sign)
            collect(node.right, sign)
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
            collect(node.left, sign)
            collect(node.right, -sign)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            collect(node.operand, -sign)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
            collect(node.operand, sign)
            return
        terms.append((sign, ast.dump(node, include_attributes=False)))

    collect(expression)
    return tuple(sorted(terms))


def _closure_checkpoint_from_payload(
    payload: Mapping[str, Any] | None,
) -> ModelClosureCheckpoint | None:
    if payload is None:
        return None
    return ModelClosureCheckpoint(
        status=str(payload.get("status") or ""),
        target_value=str(payload.get("target_value") or ""),
        branch_count=int(payload.get("branch_count") or 0),
        equation_sources=tuple(payload.get("equation_sources", ())),
        residual_symbols=tuple(payload.get("residual_symbols", ())),
    )


@dataclass(frozen=True)
class CrossScopeVersionScenario:
    scopes: tuple[ModelScope, ...]
    objects: tuple[ModelObject, ...]
    initial_versions: tuple[ModelVersion, ...]
    calls: tuple[ModelCall, ...]
    wire_order: tuple[str, ...]
    dependency_edges: tuple[ModelDependency, ...] = ()
    retry_checkpoint: ModelRetryCheckpoint | None = None
    dimensions: tuple[tuple[str, str], ...] = ()
    seed: int | None = None
    scenario_id: str = ""

    def __post_init__(self) -> None:
        if self.scenario_id:
            return
        payload = self.to_payload(include_id=False)
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        object.__setattr__(self, "scenario_id", f"csv-{digest}")

    def to_payload(self, *, include_id: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        for call in payload.get("calls", ()):
            if not call.get("state_reads"):
                call.pop("state_reads", None)
        checkpoint = payload.get("retry_checkpoint")
        if isinstance(checkpoint, dict):
            if checkpoint.get("expected_closure") is None:
                checkpoint.pop("expected_closure", None)
            if checkpoint.get("observed_closure") is None:
                checkpoint.pop("observed_closure", None)
        if not include_id:
            payload.pop("scenario_id", None)
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "CrossScopeVersionScenario":
        state_keys: dict[tuple[str, str, str], ModelStateKey] = {}

        def state_key(value: Mapping[str, Any] | None) -> ModelStateKey | None:
            if value is None:
                return None
            key = (
                str(value["object_id"]),
                str(value["state_kind"]),
                str(value["runtime_type"]),
            )
            return state_keys.setdefault(key, ModelStateKey(*key))

        return cls(
            scopes=tuple(ModelScope(**item) for item in payload["scopes"]),
            objects=tuple(ModelObject(**item) for item in payload["objects"]),
            initial_versions=tuple(
                ModelVersion(
                    version_id=str(item["version_id"]),
                    state_key=state_key(item["state_key"]),  # type: ignore[arg-type]
                    storage_scope_id=str(item["storage_scope_id"]),
                    valid_scope_id=str(item["valid_scope_id"]),
                    ordinal=int(item["ordinal"]),
                    producer_call_id=item.get("producer_call_id"),
                    previous_version_id=item.get("previous_version_id"),
                    source_version_ids=tuple(
                        item.get("source_version_ids", ())
                    ),
                    computation_token=item.get("computation_token"),
                    effect_token=item.get("effect_token"),
                    runtime_destination=item.get("runtime_destination"),
                    free_symbols=tuple(item.get("free_symbols", ())),
                )
                for item in payload.get("initial_versions", ())
            ),
            calls=tuple(
                ModelCall(
                    call_id=str(item["call_id"]),
                    declared_scope_id=str(item["declared_scope_id"]),
                    capability_key=str(item["capability_key"]),
                    input_version_ids=tuple(
                        item.get("input_version_ids", ())
                    ),
                    input_condition_ids=tuple(
                        item.get("input_condition_ids", ())
                    ),
                    state_reads=tuple(
                        ModelStateRead(
                            mode=read["mode"],
                            state_key=state_key(read["state_key"]),  # type: ignore[arg-type]
                            arg_name=str(read.get("arg_name", "input")),
                            version_id=read.get("version_id"),
                            source_call_id=read.get("source_call_id"),
                        )
                        for read in item.get("state_reads", ())
                    ),
                    output_state_key=state_key(
                        item.get("output_state_key")
                    ),
                    requested_write_mode=item.get(
                        "requested_write_mode", "create"
                    ),
                    storage_scope_id=item.get("storage_scope_id"),
                    valid_scope_id=item.get("valid_scope_id"),
                    free_symbols=tuple(item.get("free_symbols", ())),
                    is_pure=bool(item.get("is_pure", True)),
                    is_shareable=bool(item.get("is_shareable", True)),
                    answer_scope_ids=tuple(
                        item.get("answer_scope_ids", ())
                    ),
                    explicit_consumer_scope_ids=tuple(
                        item.get("explicit_consumer_scope_ids", ())
                    ),
                    projection=item.get("projection", "object"),
                    runtime_destination=item.get("runtime_destination"),
                    dead=bool(item.get("dead", False)),
                    forced_failure=bool(
                        item.get("forced_failure", False)
                    ),
                )
                for item in payload.get("calls", ())
            ),
            wire_order=tuple(payload.get("wire_order", ())),
            dependency_edges=tuple(
                ModelDependency(
                    producer_call_id=str(item["producer_call_id"]),
                    consumer_call_id=str(item["consumer_call_id"]),
                    kind=item["kind"],
                    version_id=item.get("version_id"),
                    condition_id=item.get("condition_id"),
                    arg_name=item.get("arg_name"),
                )
                for item in payload.get("dependency_edges", ())
            ),
            retry_checkpoint=(
                ModelRetryCheckpoint(
                    mode=payload["retry_checkpoint"]["mode"],
                    committed_call_ids=tuple(
                        payload["retry_checkpoint"].get(
                            "committed_call_ids", ()
                        )
                    ),
                    committed_version_ids=tuple(
                        payload["retry_checkpoint"].get(
                            "committed_version_ids", ()
                        )
                    ),
                    provisional_call_ids=tuple(
                        payload["retry_checkpoint"].get(
                            "provisional_call_ids", ()
                        )
                    ),
                    replacement_call_ids=tuple(
                        payload["retry_checkpoint"].get(
                            "replacement_call_ids", ()
                        )
                    ),
                    expected_free_symbol_refs=tuple(
                        payload["retry_checkpoint"].get(
                            "expected_free_symbol_refs", ()
                        )
                    ),
                    expected_free_symbol_ids=tuple(
                        payload["retry_checkpoint"].get(
                            "expected_free_symbol_ids", ()
                        )
                    ),
                    observed_free_symbol_refs=tuple(
                        payload["retry_checkpoint"].get(
                            "observed_free_symbol_refs", ()
                        )
                    ),
                    observed_free_symbol_ids=tuple(
                        payload["retry_checkpoint"].get(
                            "observed_free_symbol_ids", ()
                        )
                    ),
                    expected_closure=_closure_checkpoint_from_payload(
                        payload["retry_checkpoint"].get(
                            "expected_closure"
                        )
                    ),
                    observed_closure=_closure_checkpoint_from_payload(
                        payload["retry_checkpoint"].get(
                            "observed_closure"
                        )
                    ),
                )
                if payload.get("retry_checkpoint")
                else None
            ),
            dimensions=tuple(
                (str(key), str(value))
                for key, value in payload.get("dimensions", ())
            ),
            seed=payload.get("seed"),
            scenario_id=str(payload.get("scenario_id", "")),
        )


@dataclass(frozen=True)
class ExpectedCallDecision:
    call_id: str
    canonical_call_id: str
    allocation_action: str
    execution_scope_id: str
    return_scope_id: str | None
    selected_version_id: str | None
    previous_version_id: str | None
    source_version_ids: tuple[str, ...]
    visible_read_version_ids: tuple[str, ...]
    provisional_allocation_action: str | None = None
    provisional_version_id: str | None = None
    provisional_previous_version_id: str | None = None
    provisional_canonical_call_id: str | None = None
    issue_code: str | None = None


@dataclass(frozen=True)
class ExpectedScopeVersionOutcome:
    canonical_order: tuple[str, ...]
    dependency_edges: tuple[tuple[str, str], ...]
    dependency_edge_kinds: tuple[tuple[str, str, str], ...]
    call_decisions: tuple[ExpectedCallDecision, ...]
    final_visible_versions: tuple[tuple[str, str, str | None], ...]
    committed_version_ids: tuple[str, ...]
    restored_call_ids: tuple[str, ...]
    provisional_call_ids: tuple[str, ...]
    repair_call_ids: tuple[str, ...]
    blocked_call_ids: tuple[str, ...]
    eliminated_call_ids: tuple[str, ...]
    alias_call_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]
    b3_issue_categories: tuple[str, ...]
    c0_issue_codes: tuple[str, ...]

    def decision(self, call_id: str) -> ExpectedCallDecision:
        return next(
            item for item in self.call_decisions if item.call_id == call_id
        )


class ReferenceScopeVersionModel:
    """Small executable specification for planner scope/version semantics."""

    def evaluate(
        self,
        scenario: CrossScopeVersionScenario,
    ) -> ExpectedScopeVersionOutcome:
        self._validate(scenario)
        scopes = {item.scope_id: item.parent_scope_id for item in scenario.scopes}
        object_origins = {
            item.object_id: item.origin_scope_id
            for item in scenario.objects
        }
        initial_state_keys = {
            item.state_key for item in scenario.initial_versions
        }
        calls = {item.call_id: item for item in scenario.calls}
        checkpoint = scenario.retry_checkpoint
        checkpoint_versions = (
            {
                call_id: version_id
                for call_id, version_id in zip(
                    checkpoint.committed_call_ids,
                    checkpoint.committed_version_ids,
                    strict=False,
                )
            }
            if checkpoint is not None
            else {}
        )

        def checkpoint_storage_scope(call_id: str) -> str | None:
            version_id = checkpoint_versions.get(call_id)
            if version_id is None or "@" not in version_id:
                return None
            return version_id.rsplit("@", 1)[-1].rsplit("#", 1)[0]
        serialized_order = self._serialized_call_order(scenario)
        wire_rank = {
            call_id: rank for rank, call_id in enumerate(serialized_order)
        }
        semantic_producers = self._semantic_read_producers(
            scenario,
            wire_rank=wire_rank,
        )
        dependencies = self._dependencies(
            scenario,
            semantic_producers=semantic_producers,
        )
        direct_consumers: dict[str, set[str]] = {}
        for consumer_id, producer_ids in dependencies.items():
            for producer_id in producer_ids:
                direct_consumers.setdefault(producer_id, set()).add(
                    consumer_id
                )
        dependency_consumers: dict[str, tuple[str, ...]] = {}
        for producer_id in calls:
            pending = list(direct_consumers.get(producer_id, ()))
            visited: set[str] = set()
            scopes_served: list[str] = []
            while pending:
                consumer_id = pending.pop()
                if consumer_id in visited:
                    continue
                visited.add(consumer_id)
                scopes_served.append(
                    calls[consumer_id].declared_scope_id
                )
                pending.extend(direct_consumers.get(consumer_id, ()))
            dependency_consumers[producer_id] = tuple(
                dict.fromkeys(scopes_served)
            )
        order, cyclic = self._topological_order(
            calls,
            dependencies,
            wire_rank,
        )
        versions = {item.version_id: item for item in scenario.initial_versions}
        provisional_versions = dict(versions)
        decisions: dict[str, ExpectedCallDecision] = {}
        identity_owner: dict[
            tuple[str, tuple[str, ...], tuple[str, ...], str, str | None],
            str,
        ] = {}
        blocked: set[str] = set()
        aliases: set[str] = set()
        issues: list[str] = [
            "logical_graph_cycle" for _ in cyclic
        ]
        produced_version_by_call: dict[str, str] = {}
        provisional_version_by_call: dict[str, str] = {}
        def resolved_source_ids(
            call: ModelCall,
            version_by_call: Mapping[str, str],
        ) -> tuple[str, ...]:
            result = [
                version_by_call.get(value, value)
                for value in call.input_version_ids
            ]
            for read in call.state_reads:
                if read.mode == "identity_only":
                    continue
                if read.mode == "exact" and read.version_id is not None:
                    result.append(
                        version_by_call.get(
                            read.version_id,
                            read.version_id,
                        )
                    )
                    continue
                if read.mode == "latest":
                    producer = semantic_producers.get(
                        (call.call_id, read.arg_name)
                    )
                    if producer is None:
                        continue
                else:
                    producer = read.source_call_id
                if producer is not None:
                    producer_decision = decisions.get(producer)
                    if (
                        producer_decision is not None
                        and producer_decision.allocation_action == "conflict"
                    ):
                        # Failed/provisional writes order their dependents but
                        # never become an exact readable StateVersion.
                        continue
                    if read.mode == "latest" and producer_decision is not None:
                        producer_is_reuse = (
                            producer_decision.allocation_action == "reuse"
                            or producer_decision.provisional_allocation_action
                            == "reuse"
                        )
                        candidate_version_id = version_by_call.get(producer)
                        candidate_version = (
                            versions.get(candidate_version_id or "")
                            or provisional_versions.get(
                                candidate_version_id or ""
                            )
                        )
                        if producer_is_reuse and (
                            candidate_version is None
                            or not self.is_visible(
                                candidate_version.valid_scope_id,
                                call.declared_scope_id,
                                scopes,
                            )
                        ):
                            # The edge orders the runtime probe, but an
                            # invisible selected StateVersion is not an
                            # authoritative read until C2 proves equality.
                            continue
                    result.append(
                        version_by_call.get(producer, producer)
                    )
            return tuple(dict.fromkeys(result))

        def publishable_scope(
            *,
            requested_scope: str,
            fallback_scope: str,
            source_ids: tuple[str, ...],
        ) -> str:
            if all(
                version_id in versions
                and self.is_visible(
                    versions[version_id].valid_scope_id,
                    requested_scope,
                    scopes,
                )
                for version_id in source_ids
            ):
                return requested_scope
            return fallback_scope

        for call_id in order:
            call = calls[call_id]
            failed_dependencies = tuple(
                item
                for item in dependencies.get(call_id, ())
                if item in blocked
                or (
                    item in decisions
                    and decisions[item].issue_code is not None
                )
            )
            if failed_dependencies:
                blocked.add(call_id)
                provisional_source_ids = resolved_source_ids(
                    call,
                    provisional_version_by_call,
                )
                (
                    provisional_action,
                    provisional,
                    provisional_previous,
                    provisional_issue,
                ) = self._allocate(
                    call,
                    source_ids=tuple(
                        item
                        for item in provisional_source_ids
                        if item in provisional_versions
                    ),
                    execution_scope=call.declared_scope_id,
                    storage_scope_id=(
                        call.storage_scope_id
                        or call.declared_scope_id
                    ),
                    valid_scope_id=(
                        call.valid_scope_id
                        or call.declared_scope_id
                    ),
                    versions=provisional_versions,
                    scopes=scopes,
                )
                if provisional is not None:
                    provisional_versions[provisional.version_id] = provisional
                    provisional_version_by_call[call.call_id] = (
                        provisional.version_id
                    )
                decisions[call_id] = ExpectedCallDecision(
                    call_id=call_id,
                    canonical_call_id=call_id,
                    allocation_action="blocked",
                    execution_scope_id=call.declared_scope_id,
                    return_scope_id=(
                        call.valid_scope_id
                        if provisional is not None
                        else None
                    ),
                    selected_version_id=None,
                    previous_version_id=None,
                    source_version_ids=tuple(
                        item
                        for item in provisional_source_ids
                        if item in provisional_versions
                    ),
                    visible_read_version_ids=(),
                    provisional_allocation_action=provisional_action,
                    provisional_version_id=(
                        provisional.version_id
                        if provisional is not None
                        else None
                    ),
                    provisional_previous_version_id=provisional_previous,
                    provisional_canonical_call_id=(
                        provisional.producer_call_id
                        if provisional_action == "reuse"
                        and provisional is not None
                        and provisional.producer_call_id is not None
                        else call_id
                    ),
                    issue_code="blocked_by_dependency",
                )
                continue
            if call.dead:
                decisions[call_id] = ExpectedCallDecision(
                    call_id=call_id,
                    canonical_call_id=call_id,
                    allocation_action="eliminated",
                    execution_scope_id=call.declared_scope_id,
                    return_scope_id=None,
                    selected_version_id=None,
                    previous_version_id=None,
                    source_version_ids=(),
                    visible_read_version_ids=(),
                )
                continue

            source_ids = resolved_source_ids(
                call,
                produced_version_by_call,
            )
            provisional_source_ids = resolved_source_ids(
                call,
                provisional_version_by_call,
            )
            visible_reads: list[str] = []
            input_issue: str | None = None
            for version_id in source_ids:
                version = versions.get(version_id)
                if version is None:
                    input_issue = "state.read_version_unresolved"
                    break
                if not self.is_visible(
                    version.valid_scope_id,
                    call.declared_scope_id,
                    scopes,
                ):
                    input_issue = "state.read_version_invisible"
                    break
                visible_reads.append(version_id)
            if input_issue is not None:
                blocked.add(call_id)
                issues.append(input_issue)
                (
                    provisional_action,
                    provisional,
                    provisional_previous,
                    provisional_issue,
                ) = self._allocate(
                    call,
                    source_ids=provisional_source_ids,
                    execution_scope=call.declared_scope_id,
                    storage_scope_id=(
                        call.storage_scope_id
                        or call.declared_scope_id
                    ),
                    valid_scope_id=(
                        call.valid_scope_id
                        or call.declared_scope_id
                    ),
                    versions=provisional_versions,
                    scopes=scopes,
                )
                if provisional is not None:
                    provisional_versions[provisional.version_id] = provisional
                    provisional_version_by_call[call.call_id] = (
                        provisional.version_id
                    )
                (
                    action,
                    selected,
                    previous,
                    final_allocation_issue,
                ) = self._allocate(
                    call,
                    source_ids=source_ids,
                    execution_scope=call.declared_scope_id,
                    storage_scope_id=(
                        call.storage_scope_id
                        or call.declared_scope_id
                    ),
                    valid_scope_id=(
                        call.valid_scope_id
                        or call.declared_scope_id
                    ),
                    versions=versions,
                    scopes=scopes,
                )
                if selected is not None:
                    versions[selected.version_id] = selected
                    produced_version_by_call[call.call_id] = (
                        selected.version_id
                    )
                decisions[call_id] = ExpectedCallDecision(
                    call_id=call_id,
                    canonical_call_id=call_id,
                    allocation_action=action,
                    execution_scope_id=call.declared_scope_id,
                    return_scope_id=(
                        call.valid_scope_id
                        if call.output_state_key is not None
                        else None
                    ),
                    selected_version_id=(
                        selected.version_id
                        if selected is not None
                        else None
                    ),
                    previous_version_id=previous,
                    source_version_ids=source_ids,
                    visible_read_version_ids=tuple(visible_reads),
                    provisional_allocation_action=provisional_action,
                    provisional_version_id=(
                        provisional.version_id
                        if provisional is not None
                        else None
                    ),
                    provisional_previous_version_id=provisional_previous,
                    provisional_canonical_call_id=(
                        provisional.producer_call_id
                        if provisional_action == "reuse"
                        and provisional is not None
                        and provisional.producer_call_id is not None
                        else call_id
                    ),
                    issue_code=(
                        provisional_issue
                        or final_allocation_issue
                        or input_issue
                    ),
                )
                continue

            effect = (
                call.output_state_key.token
                if call.output_state_key is not None
                else None
            )
            identity = (
                call.capability_key,
                source_ids,
                call.input_condition_ids,
                call.requested_write_mode,
                effect,
            )
            # C0.5 models authority only through placement. A matching typed
            # computation key nominates a reuse candidate, but cannot make one
            # call the canonical owner until C2 has compared actual runtime
            # values. Keep both calls canonical at this stage.
            owner = None
            owner_decision = (
                decisions.get(owner) if owner is not None else None
            )
            owner_isolated_visible = (
                owner_decision is None
                or owner_decision.allocation_action != "isolated"
                or (
                    owner_decision.return_scope_id is not None
                    and all(
                        self.is_visible(
                            owner_decision.return_scope_id,
                            service_scope,
                            scopes,
                        )
                        for service_scope in (
                            call.declared_scope_id,
                            *call.explicit_consumer_scope_ids,
                            *call.answer_scope_ids,
                        )
                    )
                )
            )
            if (
                owner is not None
                and decisions[owner].issue_code is None
                and owner_isolated_visible
                and call.is_pure
                and call.is_shareable
                and calls[owner].is_pure
                and calls[owner].is_shareable
            ):
                merge_scope = self.least_common_scope(
                    (
                        decisions[owner].execution_scope_id,
                        call.declared_scope_id,
                        *call.explicit_consumer_scope_ids,
                        *call.answer_scope_ids,
                    ),
                    scopes,
                )
                if all(
                    self.is_visible(
                        versions[item].valid_scope_id,
                        merge_scope,
                        scopes,
                    )
                    for item in source_ids
                ):
                    (
                        precanonical_action,
                        precanonical_version,
                        precanonical_previous,
                        precanonical_issue,
                    ) = self._allocate(
                        call,
                        source_ids=provisional_source_ids,
                        execution_scope=call.declared_scope_id,
                        storage_scope_id=(
                            call.storage_scope_id
                            or call.declared_scope_id
                        ),
                        valid_scope_id=(
                            call.valid_scope_id
                            or call.declared_scope_id
                        ),
                        versions=provisional_versions,
                        scopes=scopes,
                    )
                    if precanonical_version is not None:
                        provisional_versions[
                            precanonical_version.version_id
                        ] = precanonical_version
                        provisional_version_by_call[call.call_id] = (
                            precanonical_version.version_id
                        )
                    requested_execution_scope = self.least_common_scope(
                        (
                            merge_scope,
                            *dependency_consumers.get(
                                call.call_id,
                                (),
                            ),
                        ),
                        scopes,
                    )
                    execution_scope = (
                        requested_execution_scope
                        if all(
                            self.is_visible(
                                versions[item].valid_scope_id,
                                requested_execution_scope,
                                scopes,
                            )
                            for item in source_ids
                        )
                        else merge_scope
                    )
                    owner_decision = decisions[owner]
                    selected_version_id = owner_decision.selected_version_id
                    requested_publication_scope = self.least_common_scope(
                        (
                            owner_decision.return_scope_id
                            or execution_scope,
                            execution_scope,
                            call.declared_scope_id,
                            *call.explicit_consumer_scope_ids,
                            *call.answer_scope_ids,
                            *dependency_consumers.get(
                                call.call_id,
                                (),
                            ),
                        ),
                        scopes,
                    )
                    publication_scope = publishable_scope(
                        requested_scope=requested_publication_scope,
                        fallback_scope=(
                            owner_decision.return_scope_id
                            or execution_scope
                        ),
                        source_ids=source_ids,
                    )
                    if (
                        selected_version_id is not None
                        and owner_decision.return_scope_id
                        != publication_scope
                        and owner_decision.allocation_action != "isolated"
                    ):
                        previous_selected_version_id = selected_version_id
                        selected = versions.pop(previous_selected_version_id)
                        pinned_storage_scope = checkpoint_storage_scope(owner)
                        relocated_version_id = (
                            previous_selected_version_id
                            if pinned_storage_scope is not None
                            else (
                                f"{selected.state_key.token}"
                                f"@{publication_scope}#{selected.ordinal}"
                            )
                        )
                        selected = replace(
                            selected,
                            version_id=relocated_version_id,
                            storage_scope_id=(
                                pinned_storage_scope or publication_scope
                            ),
                            valid_scope_id=publication_scope,
                        )
                        versions[relocated_version_id] = selected
                        selected_version_id = relocated_version_id
                        produced_version_by_call[owner] = (
                            relocated_version_id
                        )
                        produced_version_by_call[call_id] = (
                            relocated_version_id
                        )
                        for existing_call_id, existing_decision in tuple(
                            decisions.items()
                        ):
                            decisions[existing_call_id] = replace(
                                existing_decision,
                                source_version_ids=tuple(
                                    relocated_version_id
                                    if item
                                    == previous_selected_version_id
                                    else item
                                    for item in (
                                        existing_decision.source_version_ids
                                    )
                                ),
                                visible_read_version_ids=tuple(
                                    relocated_version_id
                                    if item
                                    == previous_selected_version_id
                                    else item
                                    for item in (
                                        existing_decision.visible_read_version_ids
                                    )
                                ),
                                previous_version_id=(
                                    relocated_version_id
                                    if existing_decision.previous_version_id
                                    == previous_selected_version_id
                                    else existing_decision.previous_version_id
                                ),
                            )
                        owner_decision = replace(
                            decisions[owner],
                            selected_version_id=relocated_version_id,
                            return_scope_id=publication_scope,
                        )
                    aliases.add(call_id)
                    decisions[call_id] = ExpectedCallDecision(
                        call_id=call_id,
                        canonical_call_id=owner,
                        allocation_action=(
                            "call_local_value"
                            if call.output_state_key is None
                            else "reuse"
                        ),
                        execution_scope_id=execution_scope,
                        return_scope_id=owner_decision.return_scope_id,
                        selected_version_id=selected_version_id,
                        previous_version_id=None,
                        source_version_ids=source_ids,
                        visible_read_version_ids=tuple(visible_reads),
                        provisional_allocation_action=precanonical_action,
                        provisional_version_id=(
                            precanonical_version.version_id
                            if precanonical_version is not None
                            else None
                        ),
                        provisional_previous_version_id=(
                            precanonical_previous
                        ),
                        provisional_canonical_call_id=(
                            precanonical_version.producer_call_id
                            if precanonical_action == "reuse"
                            and precanonical_version is not None
                            and precanonical_version.producer_call_id
                            is not None
                            else call_id
                        ),
                        issue_code=precanonical_issue,
                    )
                    if owner_decision.execution_scope_id != execution_scope:
                        owner_decision = replace(
                            owner_decision,
                            execution_scope_id=execution_scope,
                            return_scope_id=(
                                owner_decision.return_scope_id
                                if owner_decision.allocation_action
                                == "isolated"
                                else publication_scope
                            ),
                        )
                    decisions[owner] = owner_decision
                    if selected_version_id:
                        produced_version_by_call[call_id] = (
                            selected_version_id
                        )
                    continue

            base_execution_scope = self._execution_scope(
                call,
                scopes,
                object_origins=object_origins,
                initial_state_keys=initial_state_keys,
            )
            if not all(
                version_id in versions
                and self.is_visible(
                    versions[version_id].valid_scope_id,
                    base_execution_scope,
                    scopes,
                )
                for version_id in source_ids
            ):
                base_execution_scope = call.declared_scope_id
            requested_execution_scope = self.least_common_scope(
                (
                    base_execution_scope,
                    *dependency_consumers.get(call.call_id, ()),
                ),
                scopes,
            )
            execution_scope = (
                requested_execution_scope
                if all(
                    version_id in versions
                    and self.is_visible(
                        versions[version_id].valid_scope_id,
                        requested_execution_scope,
                        scopes,
                    )
                    for version_id in source_ids
                )
                else base_execution_scope
            )
            requested_return_scope = self.least_common_scope(
                (
                    call.valid_scope_id or execution_scope,
                    *dependency_consumers.get(call.call_id, ()),
                ),
                scopes,
            )
            return_scope = publishable_scope(
                requested_scope=requested_return_scope,
                fallback_scope=call.valid_scope_id or execution_scope,
                source_ids=source_ids,
            )
            storage_scope = checkpoint_storage_scope(call.call_id) or (
                return_scope
                if dependency_consumers.get(call.call_id)
                else (call.storage_scope_id or execution_scope)
            )
            (
                _provisional_action,
                provisional,
                _provisional_previous,
                provisional_issue,
            ) = self._allocate(
                call,
                source_ids=provisional_source_ids,
                execution_scope=call.declared_scope_id,
                storage_scope_id=(
                    call.storage_scope_id or call.declared_scope_id
                ),
                valid_scope_id=(
                    call.valid_scope_id or call.declared_scope_id
                ),
                versions=provisional_versions,
                scopes=scopes,
            )
            if provisional is not None:
                provisional_versions[provisional.version_id] = provisional
                provisional_version_by_call[call.call_id] = (
                    provisional.version_id
                )
            if provisional_issue is not None:
                action = "conflict"
                selected = None
                previous = _provisional_previous
                issue = provisional_issue
                return_scope = call.valid_scope_id or execution_scope
            elif _provisional_action == "isolated":
                action = "isolated"
                selected = provisional
                previous = _provisional_previous
                issue = None
                execution_scope = call.declared_scope_id
                return_scope = (
                    call.valid_scope_id or call.declared_scope_id
                )
            else:
                (
                    action,
                    selected,
                    previous,
                    issue,
                ) = self._allocate(
                    call,
                    source_ids=source_ids,
                    execution_scope=execution_scope,
                    storage_scope_id=storage_scope,
                    valid_scope_id=return_scope,
                    versions=versions,
                    scopes=scopes,
                )
            if issue:
                blocked.add(call_id)
                issues.append(issue)
            if selected is not None:
                produced_version_by_call[call_id] = selected.version_id
                versions[selected.version_id] = selected
            decisions[call_id] = ExpectedCallDecision(
                call_id=call_id,
                canonical_call_id=call_id,
                allocation_action=action,
                execution_scope_id=execution_scope,
                return_scope_id=(
                    return_scope
                    if call.output_state_key is not None
                    else None
                ),
                selected_version_id=(
                    selected.version_id if selected is not None else None
                ),
                previous_version_id=previous,
                source_version_ids=source_ids,
                visible_read_version_ids=tuple(visible_reads),
                provisional_allocation_action=_provisional_action,
                provisional_version_id=(
                    provisional.version_id
                    if provisional is not None
                    else None
                ),
                provisional_previous_version_id=_provisional_previous,
                provisional_canonical_call_id=(
                    provisional.producer_call_id
                    if _provisional_action == "reuse"
                    and provisional is not None
                    and provisional.producer_call_id is not None
                    else call_id
                ),
                issue_code=issue,
            )
            if issue is None:
                identity_owner.setdefault(identity, call_id)

        for consumer_id, producer_ids in dependencies.items():
            if consumer_id not in decisions:
                continue
            consumer_owner = decisions[consumer_id].canonical_call_id
            consumer_scope = decisions[consumer_owner].execution_scope_id
            for producer_id in producer_ids:
                if producer_id not in decisions:
                    continue
                producer_owner = decisions[producer_id].canonical_call_id
                producer_decision = decisions[producer_owner]
                execution_scope = self.least_common_scope(
                    (
                        producer_decision.execution_scope_id,
                        consumer_scope,
                    ),
                    scopes,
                )
                inputs_visible = all(
                    version_id in versions
                    and self.is_visible(
                        versions[version_id].valid_scope_id,
                        execution_scope,
                        scopes,
                    )
                    for version_id in producer_decision.source_version_ids
                )
                if (
                    inputs_visible
                    and execution_scope
                    != producer_decision.execution_scope_id
                ):
                    decisions[producer_owner] = replace(
                        producer_decision,
                        execution_scope_id=execution_scope,
                    )

        committed, restored, provisional, retry_issues = self._retry(
            scenario,
            decisions,
        )
        issues.extend(retry_issues)
        repair = self._repair_cone(
            decisions,
            dependencies,
            committed=set(restored),
        )
        final_visible = self._final_visible(
            versions.values(),
            scenario.scopes,
        )
        canonical_edges = tuple(
            sorted(
                {
                    (
                        decisions[producer].canonical_call_id,
                        decisions[consumer].canonical_call_id,
                    )
                    for consumer, producers in dependencies.items()
                    for producer in producers
                    if producer in decisions
                    and consumer in decisions
                    and decisions[producer].canonical_call_id
                    != decisions[consumer].canonical_call_id
                }
            )
        )
        dependency_kinds = {
            (edge.producer_call_id, edge.consumer_call_id): {
                "hidden_semantic_role": "semantic_object",
            }.get(edge.kind, edge.kind)
            for edge in scenario.dependency_edges
        }
        for call in scenario.calls:
            dependency_kinds.update(
                {
                    (value, call.call_id): "call_result"
                    for value in call.input_version_ids
                    if value in calls
                }
            )
            dependency_kinds.update(
                {
                    (read.source_call_id, call.call_id): "call_result"
                    for read in call.state_reads
                    if read.mode == "call_result"
                    and read.source_call_id is not None
                }
            )
        for (consumer, _arg_name), producer in semantic_producers.items():
            producer_decision = decisions.get(producer)
            selected_version = (
                versions.get(producer_decision.selected_version_id or "")
                if producer_decision is not None
                else None
            )
            kind = "state_version"
            if producer_decision is not None and (
                producer_decision.allocation_action == "reuse"
                or producer_decision.provisional_allocation_action == "reuse"
            ) and (
                selected_version is None
                or not self.is_visible(
                    selected_version.valid_scope_id,
                    calls[consumer].declared_scope_id,
                    scopes,
                )
            ):
                kind = "semantic_object"
            dependency_kinds.setdefault(
                (producer, consumer),
                kind,
            )
        canonical_edge_kind_set: set[tuple[str, str, str]] = set()
        for raw_consumer, raw_producers in dependencies.items():
            if raw_consumer not in decisions:
                continue
            consumer = decisions[raw_consumer].canonical_call_id
            for raw_producer in raw_producers:
                if raw_producer not in decisions:
                    continue
                producer = decisions[raw_producer].canonical_call_id
                if producer == consumer:
                    continue
                canonical_edge_kind_set.add(
                    (
                        producer,
                        consumer,
                        dependency_kinds.get(
                            (raw_producer, raw_consumer),
                            "unknown",
                        ),
                    )
                )
        canonical_edge_kinds = tuple(sorted(canonical_edge_kind_set))
        runtime_failed = {
            call.call_id for call in scenario.calls if call.forced_failure
        }
        runtime_blocked: set[str] = set()
        for call_id in order:
            if any(
                dependency in runtime_failed | runtime_blocked
                for dependency in dependencies.get(call_id, ())
            ):
                runtime_blocked.add(call_id)
        canonical_runtime_failed = {
            decisions[call_id].canonical_call_id
            for call_id in runtime_failed
            if call_id in decisions
        }
        canonical_runtime_blocked = {
            decisions[call_id].canonical_call_id
            for call_id in runtime_blocked
            if call_id in decisions
            and not calls[call_id].dead
        } - canonical_runtime_failed
        return ExpectedScopeVersionOutcome(
            canonical_order=tuple(
                item
                for item in order
                if item not in aliases and not calls[item].dead
            ),
            dependency_edges=canonical_edges,
            dependency_edge_kinds=canonical_edge_kinds,
            call_decisions=tuple(
                decisions[item]
                for item in scenario.wire_order
                if item in decisions
            ),
            final_visible_versions=final_visible,
            committed_version_ids=committed,
            restored_call_ids=restored,
            provisional_call_ids=provisional,
            repair_call_ids=repair,
            blocked_call_ids=tuple(sorted(canonical_runtime_blocked)),
            eliminated_call_ids=tuple(
                sorted(
                    decision.call_id
                    for decision in decisions.values()
                    if decision.allocation_action == "eliminated"
                )
            ),
            alias_call_ids=tuple(sorted(aliases)),
            issue_codes=tuple(dict.fromkeys(issues)),
            b3_issue_categories=(
                ("state.version_visibility_or_resolution",)
                if "state.read_version_invisible" in issues
                else ()
            ),
            c0_issue_codes=tuple(
                "logical_graph_cycle" for _ in cyclic
            ),
        )

    @staticmethod
    def _serialized_call_order(
        scenario: CrossScopeVersionScenario,
    ) -> tuple[str, ...]:
        """Mirror FunctionalPlan's scope-grouped wire representation."""

        call_scope = {
            call.call_id: call.declared_scope_id for call in scenario.calls
        }
        wire_rank = {
            call_id: index
            for index, call_id in enumerate(scenario.wire_order)
        }
        calls_by_scope = {
            scope.scope_id: tuple(
                call_id
                for call_id in scenario.wire_order
                if call_scope[call_id] == scope.scope_id
            )
            for scope in scenario.scopes
        }
        ordered_scopes = sorted(
            scenario.scopes,
            key=lambda scope: min(
                (
                    wire_rank[call_id]
                    for call_id in calls_by_scope[scope.scope_id]
                ),
                default=len(scenario.wire_order),
            ),
        )
        return tuple(
            call_id
            for scope in ordered_scopes
            for call_id in calls_by_scope[scope.scope_id]
        )

    @staticmethod
    def is_visible(
        valid_scope_id: str,
        consumer_scope_id: str,
        scopes: Mapping[str, str | None],
    ) -> bool:
        current: str | None = consumer_scope_id
        visited: set[str] = set()
        while current is not None:
            if current == valid_scope_id:
                return True
            if current in visited:
                raise ValueError("scope cycle")
            visited.add(current)
            current = scopes[current]
        return False

    @classmethod
    def least_common_scope(
        cls,
        scope_ids: Sequence[str],
        scopes: Mapping[str, str | None],
    ) -> str:
        values = tuple(dict.fromkeys(scope_ids))
        if not values:
            raise ValueError("least_common_scope needs a scope")
        chains = [cls._ancestor_chain(item, scopes) for item in values]
        for candidate in chains[0]:
            if all(candidate in chain for chain in chains[1:]):
                return candidate
        raise ValueError("scope tree has no common root")

    @classmethod
    def latest_visible(
        cls,
        state_key: ModelStateKey,
        versions: Iterable[ModelVersion],
        *,
        consumer_scope_id: str,
        scopes: Mapping[str, str | None],
    ) -> ModelVersion | None:
        visible = tuple(
            item
            for item in versions
            if item.state_key == state_key
            and cls.is_visible(
                item.valid_scope_id,
                consumer_scope_id,
                scopes,
            )
        )
        if not visible:
            return None
        chain = cls._ancestor_chain(consumer_scope_id, scopes)
        closest_rank = min(chain.index(item.valid_scope_id) for item in visible)
        closest = tuple(
            item
            for item in visible
            if chain.index(item.valid_scope_id) == closest_rank
        )
        latest_by_slot: dict[tuple[ModelStateKey, str], ModelVersion] = {}
        for item in closest:
            key = (item.state_key, item.storage_scope_id)
            previous = latest_by_slot.get(key)
            if previous is None or item.ordinal > previous.ordinal:
                latest_by_slot[key] = item
        maximal = tuple(
            candidate
            for candidate in latest_by_slot.values()
            if not any(
                other.version_id != candidate.version_id
                and cls._descends(
                    other.version_id,
                    candidate.version_id,
                    {item.version_id: item for item in visible},
                )
                for other in latest_by_slot.values()
            )
        )
        if len(maximal) != 1:
            raise ValueError("ambiguous_latest_visible")
        return maximal[0]

    def _allocate(
        self,
        call: ModelCall,
        *,
        source_ids: tuple[str, ...],
        execution_scope: str,
        storage_scope_id: str,
        valid_scope_id: str,
        versions: Mapping[str, ModelVersion],
        scopes: Mapping[str, str | None],
    ) -> tuple[str, ModelVersion | None, str | None, str | None]:
        if call.output_state_key is None:
            return "call_local_value", None, None, None
        storage_scope = storage_scope_id
        valid_scope = valid_scope_id
        all_same = tuple(
            item
            for item in versions.values()
            if item.state_key == call.output_state_key
        )
        visible = self.latest_visible(
            call.output_state_key,
            all_same,
            consumer_scope_id=storage_scope,
            scopes=scopes,
        )
        same_sources = tuple(
            versions[item]
            for item in source_ids
            if item in versions
            and versions[item].state_key == call.output_state_key
        )
        source_previous = self._maximal_source_version(
            same_sources,
            versions=versions,
        )
        computation = self._computation_token(call, source_ids)
        effect = self._effect_token(call)
        reusable = next(
            (
                item
                for item in reversed(all_same)
                if call.is_shareable
                and item.computation_token == computation
                and item.effect_token == effect
                and self.is_visible(
                    item.valid_scope_id,
                    storage_scope,
                    scopes,
                )
            ),
            None,
        )
        if reusable is not None:
            return "reuse", reusable, None, None
        previous = source_previous or visible
        if call.requested_write_mode == "transition":
            action = "transition" if previous is not None else "create"
        elif source_previous is not None and set(call.free_symbols).issubset(
            source_previous.free_symbols
        ):
            action = "transition"
            previous = source_previous
        elif (
            visible is not None
            and storage_scope != visible.storage_scope_id
            and (
                not set(call.free_symbols).issubset(
                    visible.free_symbols
                )
                or set(call.free_symbols) == set(visible.free_symbols)
            )
        ):
            action = "isolated"
            previous = None
        elif visible is not None:
            return (
                "conflict",
                None,
                visible.version_id,
                "state.transition_dependency_unproven",
            )
        elif all_same:
            action = "isolated"
            previous = None
        else:
            action = "create"
            previous = None
        ordinal = (
            max(
                (
                    item.ordinal
                    for item in all_same
                    if item.storage_scope_id == storage_scope
                ),
                default=0,
            )
            + 1
        )
        version_id = (
            f"{call.output_state_key.token}@{storage_scope}#{ordinal}"
        )
        return (
            action,
            ModelVersion(
                version_id=version_id,
                state_key=call.output_state_key,
                storage_scope_id=storage_scope,
                valid_scope_id=valid_scope,
                ordinal=ordinal,
                producer_call_id=call.call_id,
                previous_version_id=(
                    previous.version_id if previous is not None else None
                ),
                source_version_ids=source_ids,
                computation_token=computation,
                effect_token=effect,
                runtime_destination=call.runtime_destination,
                free_symbols=call.free_symbols,
            ),
            previous.version_id if previous is not None else None,
            None,
        )

    @classmethod
    def _maximal_source_version(
        cls,
        candidates: Sequence[ModelVersion],
        *,
        versions: Mapping[str, ModelVersion],
    ) -> ModelVersion | None:
        unique = tuple(
            {
                item.version_id: item for item in candidates
            }.values()
        )
        maximal = tuple(
            candidate
            for candidate in unique
            if not any(
                other.version_id != candidate.version_id
                and cls._descends(
                    other.version_id,
                    candidate.version_id,
                    versions,
                )
                for other in unique
            )
        )
        return maximal[0] if len(maximal) == 1 else None

    @staticmethod
    def _computation_token(
        call: ModelCall,
        source_ids: tuple[str, ...],
    ) -> str:
        return json.dumps(
            (
                call.capability_key,
                source_ids,
                call.input_condition_ids,
            ),
            separators=(",", ":"),
        )

    @staticmethod
    def _effect_token(call: ModelCall) -> str:
        return json.dumps(
            (
                call.output_state_key.token
                if call.output_state_key is not None
                else None,
                call.requested_write_mode,
            ),
            separators=(",", ":"),
        )

    def _execution_scope(
        self,
        call: ModelCall,
        scopes: Mapping[str, str | None],
        *,
        object_origins: Mapping[str, str],
        initial_state_keys: set[ModelStateKey],
    ) -> str:
        service_scopes = (
            call.declared_scope_id,
            *call.explicit_consumer_scope_ids,
            *call.answer_scope_ids,
        )
        if call.output_state_key is not None:
            target_scope = object_origins.get(
                call.output_state_key.object_id,
            )
            if (
                target_scope is not None
                and target_scope != "problem"
                and call.output_state_key not in initial_state_keys
                and self.is_visible(
                    call.declared_scope_id,
                    target_scope,
                    scopes,
                )
                and all(
                    self.is_visible(target_scope, scope, scopes)
                    for scope in (
                        *call.explicit_consumer_scope_ids,
                        *call.answer_scope_ids,
                    )
                )
            ):
                return target_scope
        return self.least_common_scope(service_scopes, scopes)

    @staticmethod
    def _dependencies(
        scenario: CrossScopeVersionScenario,
        *,
        semantic_producers: Mapping[tuple[str, str], str],
    ) -> dict[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {
            item.call_id: [] for item in scenario.calls
        }
        producers = {
            item.version_id: item.producer_call_id
            for item in scenario.initial_versions
            if item.producer_call_id is not None
        }
        for edge in scenario.dependency_edges:
            result.setdefault(edge.consumer_call_id, []).append(
                edge.producer_call_id
            )
        for call in scenario.calls:
            for version_id in call.input_version_ids:
                producer = producers.get(version_id)
                if producer is not None:
                    result[call.call_id].append(producer)
            result[call.call_id].extend(
                read.source_call_id
                for read in call.state_reads
                if read.mode == "call_result"
                and read.source_call_id is not None
            )
            result[call.call_id].extend(
                producer
                for (consumer, _arg_name), producer
                in semantic_producers.items()
                if consumer == call.call_id
            )
        return {
            key: tuple(dict.fromkeys(value))
            for key, value in result.items()
        }

    @classmethod
    def _semantic_read_producers(
        cls,
        scenario: CrossScopeVersionScenario,
        *,
        wire_rank: Mapping[str, int],
    ) -> dict[tuple[str, str], str]:
        call_ids = {call.call_id for call in scenario.calls}
        base_dependencies: dict[str, set[str]] = {
            call_id: set() for call_id in call_ids
        }
        for edge in scenario.dependency_edges:
            base_dependencies[edge.consumer_call_id].add(
                edge.producer_call_id
            )
        for call in scenario.calls:
            base_dependencies[call.call_id].update(
                value
                for value in call.input_version_ids
                if value in call_ids
            )
            base_dependencies[call.call_id].update(
                read.source_call_id
                for read in call.state_reads
                if read.mode == "call_result"
                and read.source_call_id is not None
            )

        def depends_on(start: str, target: str) -> bool:
            pending = [start]
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == target:
                    return True
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(base_dependencies.get(current, ()))
            return False

        result: dict[tuple[str, str], str] = {}
        scopes = {
            item.scope_id: item.parent_scope_id for item in scenario.scopes
        }
        for consumer in scenario.calls:
            for read in consumer.state_reads:
                if read.mode != "latest":
                    continue
                viable_candidates = tuple(
                    candidate
                    for candidate in scenario.calls
                    if candidate.call_id != consumer.call_id
                    and candidate.output_state_key == read.state_key
                    and cls._can_materialize_state_from_initial_context(
                        candidate,
                        scenario=scenario,
                    )
                    and cls._can_publish_state_to_consumer(
                        candidate,
                        consumer_scope_id=consumer.declared_scope_id,
                        scenario=scenario,
                    )
                )
                visible_candidates = tuple(
                    candidate
                    for candidate in viable_candidates
                    if cls.is_visible(
                        candidate.valid_scope_id
                        or candidate.declared_scope_id,
                        consumer.declared_scope_id,
                        scopes,
                    )
                )
                chain = cls._ancestor_chain(
                    consumer.declared_scope_id,
                    scopes,
                )
                closest_rank = min(
                    (
                        chain.index(
                            candidate.valid_scope_id
                            or candidate.declared_scope_id
                        )
                        for candidate in visible_candidates
                    ),
                    default=None,
                )
                all_candidates = tuple(
                    candidate
                    for candidate in (
                        visible_candidates or viable_candidates
                    )
                    if (
                        not visible_candidates
                        or (
                            closest_rank is not None
                            and chain.index(
                                candidate.valid_scope_id
                                or candidate.declared_scope_id
                            )
                            == closest_rank
                        )
                    )
                )
                maximal_candidates = tuple(
                    candidate
                    for candidate in all_candidates
                    if not any(
                        other.call_id != candidate.call_id
                        and depends_on(
                            other.call_id,
                            candidate.call_id,
                        )
                        for other in all_candidates
                    )
                )
                if len(maximal_candidates) > 1:
                    prior_candidates = tuple(
                        candidate
                        for candidate in maximal_candidates
                        if wire_rank.get(
                            candidate.call_id,
                            len(wire_rank),
                        )
                        < wire_rank.get(
                            consumer.call_id,
                            len(wire_rank),
                        )
                    )
                    identity_groups = {
                        cls._semantic_candidate_identity(candidate)
                        for candidate in prior_candidates
                    }
                    if (
                        visible_candidates
                        and prior_candidates
                        and len(identity_groups) == 1
                    ):
                        # This chooses the candidate that must execute before a
                        # latest read; it does not alias or delete any call.
                        # A runtime mismatch blocks the consumer at C2.
                        maximal_candidates = (
                            max(
                                prior_candidates,
                                key=lambda item: wire_rank[item.call_id],
                            ),
                        )
                # A transition chain can contain several writers while still
                # having one unique maximal state. Independent maximal writers
                # remain ambiguous. Matching semantic/input fingerprints and
                # wire order are not runtime-equivalence proofs.
                if (
                    len(maximal_candidates) == 1
                    and not depends_on(
                        maximal_candidates[0].call_id,
                        consumer.call_id,
                    )
                ):
                    result[(consumer.call_id, read.arg_name)] = (
                        maximal_candidates[0].call_id
                    )
        return result

    @classmethod
    def _can_publish_state_to_consumer(
        cls,
        call: ModelCall,
        *,
        consumer_scope_id: str,
        scenario: CrossScopeVersionScenario,
    ) -> bool:
        scopes = {
            item.scope_id: item.parent_scope_id for item in scenario.scopes
        }
        valid_scope = call.valid_scope_id or call.declared_scope_id
        if cls.is_visible(valid_scope, consumer_scope_id, scopes):
            return True
        initial_versions = {
            item.version_id: item for item in scenario.initial_versions
        }
        publication_scope = cls.least_common_scope(
            (valid_scope, consumer_scope_id),
            scopes,
        )
        calls = {item.call_id: item for item in scenario.calls}
        dependency_producers = {
            item.producer_call_id
            for item in scenario.dependency_edges
            if item.consumer_call_id == call.call_id
        }

        def producer_publishable(
            producer: ModelCall,
            *,
            visited: set[str],
        ) -> bool:
            if producer.call_id in visited:
                return False
            visited = {*visited, producer.call_id}
            for source in (
                *producer.input_version_ids,
                *(
                    item.producer_call_id
                    for item in scenario.dependency_edges
                    if item.consumer_call_id == producer.call_id
                ),
            ):
                initial = initial_versions.get(source)
                if initial is not None:
                    if not cls.is_visible(
                        initial.valid_scope_id,
                        publication_scope,
                        scopes,
                    ):
                        return False
                    continue
                source_call = calls.get(source)
                if source_call is not None and not producer_publishable(
                    source_call,
                    visited=visited,
                ):
                    return False
            producer_valid_scope = (
                producer.valid_scope_id or producer.declared_scope_id
            )
            if cls.is_visible(
                producer_valid_scope,
                publication_scope,
                scopes,
            ):
                return True
            has_transition_source = bool(
                producer.input_version_ids
                or any(
                    item.consumer_call_id == producer.call_id
                    for item in scenario.dependency_edges
                )
            )
            if (
                producer.requested_write_mode == "create"
                and not has_transition_source
            ):
                producer_initial = cls.latest_visible(
                    producer.output_state_key,
                    initial_versions.values(),
                    consumer_scope_id=producer.declared_scope_id,
                    scopes=scopes,
                )
                if producer_initial is None:
                    return producer.is_pure
                return cls._has_materializable_equivalent_predecessor(
                    producer,
                    scenario=scenario,
                )
            # Pure producers may execute at the LCA once every real input is
            # visible there. The probe output remains isolated until C2 has
            # established runtime equivalence, so this does not publish a
            # duplicate authoritative state.
            return producer.is_pure

        return producer_publishable(
            replace(
                call,
                input_version_ids=tuple(
                    dict.fromkeys(
                        (*call.input_version_ids, *dependency_producers)
                    )
                ),
            ),
            visited=set(),
        )

    @staticmethod
    def _semantic_candidate_identity(call: ModelCall) -> tuple[object, ...]:
        """Reference projection of the typed computation/effect identity."""

        return (
            call.capability_key,
            call.input_version_ids,
            call.input_condition_ids,
            call.output_state_key,
            call.requested_write_mode,
            call.free_symbols,
        )

    @classmethod
    def _has_materializable_equivalent_predecessor(
        cls,
        call: ModelCall,
        *,
        scenario: CrossScopeVersionScenario,
    ) -> bool:
        serialized_order = cls._serialized_call_order(scenario)
        call_index = serialized_order.index(call.call_id)
        prior_call_ids = frozenset(serialized_order[:call_index])
        return any(
            cls._semantic_candidate_identity(candidate)
            == cls._semantic_candidate_identity(call)
            and cls._can_materialize_state_from_initial_context(
                candidate,
                scenario=scenario,
            )
            for candidate in scenario.calls
            if candidate.call_id in prior_call_ids
        )

    @classmethod
    def _can_materialize_state_from_initial_context(
        cls,
        call: ModelCall,
        *,
        scenario: CrossScopeVersionScenario,
    ) -> bool:
        """Exclude statically impossible writers from semantic-latest edges.

        The production semantic dependency pass runs after B1 allocation and
        therefore only sees returns with a selected StateVersion. The
        reference model performs graph construction first, so it must apply
        the same initial-context fact without using production allocation.
        """

        if (
            call.output_state_key is None
            or call.requested_write_mode == "value"
            or call.dead
        ):
            return False
        initial_versions = {
            item.version_id: item for item in scenario.initial_versions
        }
        scopes = {
            item.scope_id: item.parent_scope_id for item in scenario.scopes
        }
        visible = cls.latest_visible(
            call.output_state_key,
            initial_versions.values(),
            consumer_scope_id=call.declared_scope_id,
            scopes=scopes,
        )
        storage_scope = call.storage_scope_id or call.declared_scope_id
        if (
            call.requested_write_mode == "create"
            and visible is not None
            and visible.storage_scope_id == storage_scope
        ):
            if not cls._has_materializable_equivalent_predecessor(
                call,
                scenario=scenario,
            ):
                return False
            # The later create is a runtime-reuse probe. It remains a viable
            # dependency candidate, but C0.5 does not alias or delete it; C2
            # must compare the actual typed result first.
        if call.requested_write_mode == "transition":
            explicit_sources = tuple(
                item
                for item in call.input_version_ids
                if item in initial_versions
                or any(
                    candidate.call_id == item
                    and candidate.output_state_key
                    == call.output_state_key
                    for candidate in scenario.calls
                )
            )
            if not explicit_sources and visible is not None:
                return False
        return True

    @staticmethod
    def _topological_order(
        calls: Mapping[str, ModelCall],
        dependencies: Mapping[str, tuple[str, ...]],
        wire_rank: Mapping[str, int],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        remaining = set(calls)
        emitted: list[str] = []
        while remaining:
            ready = sorted(
                (
                    call_id
                    for call_id in remaining
                    if set(dependencies.get(call_id, ())) <= set(emitted)
                ),
                key=lambda item: wire_rank.get(item, len(wire_rank)),
            )
            if not ready:
                return tuple(emitted), tuple(sorted(remaining))
            call_id = ready[0]
            remaining.remove(call_id)
            emitted.append(call_id)
        return tuple(emitted), ()

    @staticmethod
    def _retry(
        scenario: CrossScopeVersionScenario,
        decisions: Mapping[str, ExpectedCallDecision],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        checkpoint = scenario.retry_checkpoint
        if checkpoint is None or checkpoint.mode == "none":
            return (), (), (), ()
        committed = tuple(
            item
            for item in checkpoint.committed_version_ids
            if any(
                decision.selected_version_id == item
                for decision in decisions.values()
            )
        )
        candidate_call_ids = tuple(
            dict.fromkeys(
                decision.canonical_call_id
                for decision in decisions.values()
                if decision.allocation_action != "eliminated"
            )
        )
        if checkpoint.mode == "version_drift":
            restored = tuple(
                decisions[item].canonical_call_id
                for item in checkpoint.committed_call_ids
                if item in decisions
                and decisions[item].selected_version_id is not None
                and decisions[item].issue_code is None
            )
            provisional = tuple(
                item
                for item in candidate_call_ids
                if item not in restored
            )
            return (
                committed,
                restored,
                provisional,
                ("planner.retry_state_version_drift",),
            )
        restored = tuple(
            decisions[item].canonical_call_id
            for item in checkpoint.committed_call_ids
            if item in decisions
            and decisions[item].selected_version_id is not None
            and decisions[item].issue_code is None
        )
        restored = tuple(dict.fromkeys(restored))
        provisional = tuple(
            item
            for item in candidate_call_ids
            if item not in restored
        )
        if (
            checkpoint.expected_free_symbol_ids
            != checkpoint.observed_free_symbol_ids
        ):
            return (
                committed,
                restored,
                provisional,
                ("planner.retry_state_version_drift",),
            )
        expected_closure = checkpoint.expected_closure
        observed_closure = checkpoint.observed_closure
        if (
            (expected_closure is None) != (observed_closure is None)
            or (
                expected_closure is not None
                and observed_closure is not None
                and expected_closure.semantic_signature()
                != observed_closure.semantic_signature()
            )
        ):
            return (
                committed,
                restored,
                provisional,
                ("planner.retry_symbolic_closure_drift",),
            )
        if checkpoint.mode == "provisional_replacement":
            provisional = tuple(
                item
                for item in provisional
                if item not in checkpoint.replacement_call_ids
            )
        return committed, restored, provisional, ()

    @staticmethod
    def _repair_cone(
        decisions: Mapping[str, ExpectedCallDecision],
        dependencies: Mapping[str, tuple[str, ...]],
        *,
        committed: set[str],
    ) -> tuple[str, ...]:
        roots = {
            call_id
            for call_id, decision in decisions.items()
            if decision.issue_code is not None
        }
        reverse: dict[str, set[str]] = {}
        for consumer, producers in dependencies.items():
            for producer in producers:
                reverse.setdefault(producer, set()).add(consumer)
        result = set(roots)
        pending = list(roots)
        while pending:
            current = pending.pop()
            for dependent in reverse.get(current, ()):
                if dependent not in result and dependent not in committed:
                    result.add(dependent)
                    pending.append(dependent)
        return tuple(sorted(result))

    def _final_visible(
        self,
        versions: Iterable[ModelVersion],
        scopes: Sequence[ModelScope],
    ) -> tuple[tuple[str, str, str | None], ...]:
        scope_map = {
            item.scope_id: item.parent_scope_id for item in scopes
        }
        state_keys = sorted({item.state_key for item in versions})
        result: list[tuple[str, str, str | None]] = []
        version_list = tuple(versions)
        for scope in scopes:
            for key in state_keys:
                try:
                    selected = self.latest_visible(
                        key,
                        version_list,
                        consumer_scope_id=scope.scope_id,
                        scopes=scope_map,
                    )
                except ValueError:
                    result.append(
                        (scope.scope_id, key.token, "<ambiguous>")
                    )
                    continue
                if selected is not None:
                    result.append(
                        (scope.scope_id, key.token, selected.version_id)
                    )
                else:
                    result.append((scope.scope_id, key.token, None))
        return tuple(result)

    @staticmethod
    def _ancestor_chain(
        scope_id: str,
        scopes: Mapping[str, str | None],
    ) -> tuple[str, ...]:
        result: list[str] = []
        current: str | None = scope_id
        while current is not None:
            if current in result:
                raise ValueError("scope cycle")
            result.append(current)
            current = scopes[current]
        return tuple(result)

    @staticmethod
    def _descends(
        candidate_id: str,
        ancestor_id: str,
        versions: Mapping[str, ModelVersion],
    ) -> bool:
        pending = [candidate_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == ancestor_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            item = versions.get(current)
            if item is not None:
                if item.previous_version_id is not None:
                    pending.append(item.previous_version_id)
                pending.extend(item.source_version_ids)
        return False

    @staticmethod
    def _validate(scenario: CrossScopeVersionScenario) -> None:
        scopes = {item.scope_id for item in scenario.scopes}
        calls = {item.call_id for item in scenario.calls}
        if "problem" not in scopes:
            raise ValueError("scenario requires problem root")
        if calls != set(scenario.wire_order):
            raise ValueError("wire_order must contain every call exactly once")
        if len(calls) != len(scenario.wire_order):
            raise ValueError("duplicate call in wire_order")
        if any(item.declared_scope_id not in scopes for item in scenario.calls):
            raise ValueError("call uses unknown scope")
        if any(
            item.parent_scope_id is not None
            and item.parent_scope_id not in scopes
            for item in scenario.scopes
        ):
            raise ValueError("scope uses unknown parent")


def rename_scenario(
    scenario: CrossScopeVersionScenario,
    *,
    prefix: str,
) -> CrossScopeVersionScenario:
    """Return an isomorphic scenario with every anonymous token renamed."""

    scope_map = {
        item.scope_id: (
            "problem" if item.scope_id == "problem" else f"{prefix}_{item.scope_id}"
        )
        for item in scenario.scopes
    }
    object_map = {
        item.object_id: f"{prefix}_{item.object_id}"
        for item in scenario.objects
    }
    call_map = {
        item.call_id: f"{prefix}_{item.call_id}"
        for item in scenario.calls
    }
    version_map = {
        item.version_id: f"{prefix}_{item.version_id}"
        for item in scenario.initial_versions
    }

    def key(value: ModelStateKey | None) -> ModelStateKey | None:
        if value is None:
            return None
        return replace(value, object_id=object_map[value.object_id])

    return CrossScopeVersionScenario(
        scopes=tuple(
            ModelScope(
                scope_id=scope_map[item.scope_id],
                parent_scope_id=(
                    scope_map[item.parent_scope_id]
                    if item.parent_scope_id is not None
                    else None
                ),
            )
            for item in scenario.scopes
        ),
        objects=tuple(
            replace(
                item,
                object_id=object_map[item.object_id],
                origin_scope_id=scope_map[item.origin_scope_id],
            )
            for item in scenario.objects
        ),
        initial_versions=tuple(
            replace(
                item,
                version_id=version_map[item.version_id],
                state_key=key(item.state_key),  # type: ignore[arg-type]
                storage_scope_id=scope_map[item.storage_scope_id],
                valid_scope_id=scope_map[item.valid_scope_id],
                producer_call_id=(
                    call_map[item.producer_call_id]
                    if item.producer_call_id is not None
                    else None
                ),
                previous_version_id=(
                    version_map.get(
                        item.previous_version_id,
                        item.previous_version_id,
                    )
                    if item.previous_version_id is not None
                    else None
                ),
                source_version_ids=tuple(
                    version_map.get(value, value)
                    for value in item.source_version_ids
                ),
            )
            for item in scenario.initial_versions
        ),
        calls=tuple(
            replace(
                item,
                call_id=call_map[item.call_id],
                declared_scope_id=scope_map[item.declared_scope_id],
                input_version_ids=tuple(
                    call_map.get(value, version_map.get(value, value))
                    for value in item.input_version_ids
                ),
                state_reads=tuple(
                    replace(
                        read,
                        state_key=key(read.state_key),  # type: ignore[arg-type]
                        version_id=(
                            call_map.get(
                                read.version_id,
                                version_map.get(
                                    read.version_id,
                                    read.version_id,
                                ),
                            )
                            if read.version_id is not None
                            else None
                        ),
                        source_call_id=(
                            call_map[read.source_call_id]
                            if read.source_call_id is not None
                            else None
                        ),
                    )
                    for read in item.state_reads
                ),
                output_state_key=key(item.output_state_key),
                storage_scope_id=(
                    scope_map[item.storage_scope_id]
                    if item.storage_scope_id is not None
                    else None
                ),
                valid_scope_id=(
                    scope_map[item.valid_scope_id]
                    if item.valid_scope_id is not None
                    else None
                ),
                answer_scope_ids=tuple(
                    scope_map[value] for value in item.answer_scope_ids
                ),
                explicit_consumer_scope_ids=tuple(
                    scope_map[value]
                    for value in item.explicit_consumer_scope_ids
                ),
            )
            for item in scenario.calls
        ),
        wire_order=tuple(call_map[item] for item in scenario.wire_order),
        dependency_edges=tuple(
            replace(
                item,
                producer_call_id=call_map[item.producer_call_id],
                consumer_call_id=call_map[item.consumer_call_id],
                version_id=(
                    version_map.get(item.version_id, item.version_id)
                    if item.version_id is not None
                    else None
                ),
            )
            for item in scenario.dependency_edges
        ),
        retry_checkpoint=(
            replace(
                scenario.retry_checkpoint,
                committed_call_ids=tuple(
                    call_map[item]
                    for item in scenario.retry_checkpoint.committed_call_ids
                ),
                committed_version_ids=tuple(
                    version_map.get(item, item)
                    for item in scenario.retry_checkpoint.committed_version_ids
                ),
                provisional_call_ids=tuple(
                    call_map[item]
                    for item in scenario.retry_checkpoint.provisional_call_ids
                ),
                replacement_call_ids=tuple(
                    call_map[item]
                    for item in scenario.retry_checkpoint.replacement_call_ids
                ),
            )
            if scenario.retry_checkpoint is not None
            else None
        ),
        dimensions=scenario.dimensions,
        seed=scenario.seed,
    )
