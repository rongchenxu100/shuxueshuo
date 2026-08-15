"""Scope-shaped provisional execution and checkpointing for FunctionalPlan v2."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    FunctionalProblemBindingContext,
    ProblemPlanningBindingCatalog,
    ProblemPlanningBindingError,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FunctionalDiagnosticAuthority,
    FunctionalPromptDiagnosticProjector,
    diagnostic_authority_from_issue,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedPublishedGoalBinding,
    ScopedPublishedGoalResultRef,
    ScopedFunctionalPlan,
    ScopedFunctionalPlanAuthority,
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanAuthorityReport,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanIssue,
    ScopedFunctionalPlanValidationReport,
    ScopedFunctionalPlanValidator,
    ScopedFunctionalScope,
    ScopedStepResultRef,
    apply_scoped_published_goal_bindings,
    scoped_functional_plan_schema,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalRuntimeEquivalentCallAlias,
    FunctionalRestoredCallSeed,
    rebase_restored_call_seed,
)


FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT = (
    "functional-goal-execution-checkpoint/v1"
)
FunctionalGoalStepStatus = Literal[
    "valid",
    "authority_invalid",
    "ready",
    "runtime_verified",
    "runtime_failed",
    "blocked_by_dependency",
    "pruned_dead",
]


class FunctionalGoalExecutionCheckpointError(ValueError):
    def __init__(self, path: str, message: str) -> None:
        self.code = "functional.goal_execution_checkpoint_invalid"
        self.path = path
        self.message = message
        super().__init__(f"{self.code} at {path}: {message}")


def functional_goal_execution_checkpoint_schema() -> dict[str, Any]:
    """Return the strict scope-shaped provisional checkpoint schema."""

    nonempty = {"type": "string", "minLength": 1}
    plan_defs = scoped_functional_plan_schema()["$defs"]
    step_statuses = [
        "valid",
        "authority_invalid",
        "ready",
        "runtime_verified",
        "runtime_failed",
        "blocked_by_dependency",
        "pruned_dead",
    ]
    execution_step = {
        "type": "object",
        "required": ["step_id", "status", "authored_step"],
        "properties": {
            "step_id": nonempty,
            "status": {"enum": step_statuses},
            "authored_step": {"$ref": "#/$defs/authored_step"},
            "resolved_inputs": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["arg", "index", "source"],
                    "properties": {
                        "arg": nonempty,
                        "index": {"type": "integer", "minimum": 0},
                        "source": {"$ref": "#/$defs/functional_ref"},
                        "resolution": {
                            "enum": [
                                "source_snapshot",
                                "step_result",
                                "unresolved",
                            ]
                        },
                        "runtime_type": nonempty,
                        "value": {},
                        "value_omitted_reason": nonempty,
                    },
                    "additionalProperties": False,
                },
            },
            "actual_outputs": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["return", "runtime_type"],
                    "properties": {
                        "return": nonempty,
                        "runtime_type": nonempty,
                        "value": {},
                        "value_omitted_reason": nonempty,
                    },
                    "additionalProperties": False,
                },
            },
            "typed_issue": {"type": "object"},
            "blocked_by": {
                "type": "array",
                "minItems": 1,
                "items": nonempty,
                "uniqueItems": True,
            },
        },
        "additionalProperties": False,
    }
    goal = {
        "type": "object",
        "required": ["goal_ref", "status"],
        "properties": {
            "goal_ref": nonempty,
            "status": nonempty,
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/execution_step"},
            },
        },
        "additionalProperties": False,
    }
    scope_defs: dict[str, Any] = {}
    for level in range(4):
        properties: dict[str, Any] = {
            "scope_ref": nonempty,
            "scope_steps": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/execution_step"},
            },
            "goals": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/execution_goal"},
            },
        }
        if level < 3:
            properties["children"] = {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": f"#/$defs/execution_scope_{level + 1}"},
            }
        scope_defs[f"execution_scope_{level}"] = {
            "type": "object",
            "required": ["scope_ref"],
            "properties": properties,
            "additionalProperties": False,
        }
    string_tuple_map = {
        "type": "object",
        "additionalProperties": {
            "type": "array",
            "items": nonempty,
            "uniqueItems": True,
        },
    }
    metrics = {
        "type": "object",
        "required": [
            "authority_valid_step_count",
            "authority_invalid_step_count",
            "pruned_dead_step_count",
            "provisional_executed_step_count",
            "blocked_by_dependency_step_count",
            "transaction_attempted",
            "transaction_ok",
            "all_required_goals_verified",
            "blocked_stage",
        ],
        "properties": {
            "authority_valid_step_count": {"type": "integer", "minimum": 0},
            "authority_invalid_step_count": {"type": "integer", "minimum": 0},
            "pruned_dead_step_count": {"type": "integer", "minimum": 0},
            "provisional_executed_step_count": {"type": "integer", "minimum": 0},
            "blocked_by_dependency_step_count": {"type": "integer", "minimum": 0},
            "transaction_attempted": {"type": "boolean"},
            "transaction_ok": {"type": "boolean"},
            "all_required_goals_verified": {"type": "boolean"},
            "blocked_stage": {
                "anyOf": [nonempty, {"type": "null"}],
            },
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "functional-goal-execution-checkpoint.schema.json",
        "title": "Functional Goal Execution Checkpoint v1",
        "type": "object",
        "required": [
            "schema_version",
            "root_scope",
            "root_issues",
            "metrics",
            "planning_context_id",
            "problem_revision_id",
            "problem_semantic_hash",
            "plan_id",
            "functional_problem_binding_signature",
            "step_binding_signatures",
            "goal_unit_ids",
            "source_unit_ids",
            "provisional_state_signature",
            "checkpoint_id",
        ],
        "properties": {
            "schema_version": {
                "const": FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT,
            },
            "root_scope": {"$ref": "#/$defs/execution_scope_0"},
            "root_issues": {
                "type": "array",
                "items": {"type": "object"},
            },
            "diagnostic_authorities": {
                "type": "array",
                "items": {"type": "object"},
            },
            "metrics": {"$ref": "#/$defs/metrics"},
            "planning_context_id": nonempty,
            "problem_revision_id": nonempty,
            "problem_semantic_hash": nonempty,
            "plan_id": nonempty,
            "functional_problem_binding_signature": nonempty,
            "step_binding_signatures": {
                "type": "object",
                "additionalProperties": nonempty,
            },
            "goal_unit_ids": string_tuple_map,
            "source_unit_ids": string_tuple_map,
            "provisional_state_signature": nonempty,
            "checkpoint_id": nonempty,
        },
        "$defs": {
            "source_ref": plan_defs["source_ref"],
            "step_result_ref": plan_defs["step_result_ref"],
            "functional_ref": plan_defs["functional_ref"],
            "authored_step": plan_defs["step"],
            "execution_step": execution_step,
            "execution_goal": goal,
            "metrics": metrics,
            **scope_defs,
        },
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class FunctionalGoalExecutionStep:
    step_id: str
    status: FunctionalGoalStepStatus
    authored_step: Mapping[str, Any]
    resolved_inputs: tuple[Mapping[str, Any], ...] = ()
    actual_outputs: tuple[Mapping[str, Any], ...] = ()
    typed_issue: Mapping[str, Any] | None = None
    blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "authored_step", MappingProxyType(dict(self.authored_step)))
        object.__setattr__(
            self,
            "resolved_inputs",
            tuple(MappingProxyType(dict(item)) for item in self.resolved_inputs),
        )
        object.__setattr__(
            self,
            "actual_outputs",
            tuple(MappingProxyType(dict(item)) for item in self.actual_outputs),
        )
        if self.typed_issue is not None:
            object.__setattr__(
                self,
                "typed_issue",
                MappingProxyType(dict(self.typed_issue)),
            )
        object.__setattr__(self, "blocked_by", tuple(sorted(set(self.blocked_by))))

    def to_prompt_payload(
        self,
        *,
        include_authored_step: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "status": self.status,
        }
        if include_authored_step:
            payload["authored_step"] = dict(self.authored_step)
        if self.resolved_inputs:
            payload["resolved_inputs"] = [dict(item) for item in self.resolved_inputs]
        if self.actual_outputs:
            payload["actual_outputs"] = [dict(item) for item in self.actual_outputs]
        if self.typed_issue is not None:
            payload["typed_issue"] = dict(self.typed_issue)
        if self.blocked_by:
            payload["blocked_by"] = list(self.blocked_by)
        return payload

    def to_retry_prompt_payload(self) -> dict[str, Any]:
        """Project execution delta; Previous Canonical Plan owns authored wire."""

        return self.to_prompt_payload(include_authored_step=False)


@dataclass(frozen=True)
class FunctionalGoalExecutionGoal:
    goal_ref: str
    status: str
    steps: tuple[FunctionalGoalExecutionStep, ...]

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "goal_ref": self.goal_ref,
            "status": self.status,
        }
        if self.steps:
            payload["steps"] = [item.to_prompt_payload() for item in self.steps]
        return payload


@dataclass(frozen=True)
class FunctionalGoalExecutionScope:
    scope_ref: str
    scope_steps: tuple[FunctionalGoalExecutionStep, ...] = ()
    goals: tuple[FunctionalGoalExecutionGoal, ...] = ()
    children: tuple["FunctionalGoalExecutionScope", ...] = ()

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": self.scope_ref}
        if self.scope_steps:
            payload["scope_steps"] = [
                item.to_prompt_payload() for item in self.scope_steps
            ]
        if self.goals:
            payload["goals"] = [item.to_prompt_payload() for item in self.goals]
        if self.children:
            payload["children"] = [
                item.to_prompt_payload() for item in self.children
            ]
        return payload


@dataclass(frozen=True)
class FunctionalGoalExecutionCheckpoint:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    plan_id: str
    functional_problem_binding_signature: str
    root_scope: FunctionalGoalExecutionScope
    root_issues: tuple[Mapping[str, Any], ...]
    step_binding_signatures: Mapping[str, str]
    goal_unit_ids: Mapping[str, tuple[str, ...]]
    source_unit_ids: Mapping[str, tuple[str, ...]]
    provisional_state_signature: str
    transaction_attempted: bool
    transaction_ok: bool
    all_required_goals_verified: bool
    blocked_stage: str | None
    checkpoint_id: str
    diagnostic_authorities: tuple[Mapping[str, Any], ...] = ()
    schema_version: str = FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "root_issues",
            tuple(MappingProxyType(dict(item)) for item in self.root_issues),
        )
        object.__setattr__(
            self,
            "diagnostic_authorities",
            tuple(
                MappingProxyType(dict(item))
                for item in self.diagnostic_authorities
            ),
        )
        object.__setattr__(
            self,
            "step_binding_signatures",
            MappingProxyType(dict(sorted(self.step_binding_signatures.items()))),
        )
        object.__setattr__(
            self,
            "goal_unit_ids",
            MappingProxyType(
                {
                    key: tuple(sorted(set(value)))
                    for key, value in sorted(self.goal_unit_ids.items())
                }
            ),
        )
        object.__setattr__(
            self,
            "source_unit_ids",
            MappingProxyType(
                {
                    key: tuple(sorted(set(value)))
                    for key, value in sorted(self.source_unit_ids.items())
                }
            ),
        )

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root_scope": self.root_scope.to_prompt_payload(),
            "root_issues": [dict(item) for item in self.root_issues],
            "metrics": {
                **_checkpoint_metrics(self.root_scope),
                "transaction_attempted": self.transaction_attempted,
                "transaction_ok": self.transaction_ok,
                "all_required_goals_verified": (
                    self.all_required_goals_verified
                ),
                "blocked_stage": self.blocked_stage,
            },
        }

    def authority_payload(self) -> dict[str, Any]:
        return {
            **self.to_prompt_payload(),
            "diagnostic_authorities": [
                dict(item) for item in self.diagnostic_authorities
            ],
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "plan_id": self.plan_id,
            "functional_problem_binding_signature": (
                self.functional_problem_binding_signature
            ),
            "step_binding_signatures": dict(self.step_binding_signatures),
            "goal_unit_ids": {
                key: list(value) for key, value in self.goal_unit_ids.items()
            },
            "source_unit_ids": {
                key: list(value) for key, value in self.source_unit_ids.items()
            },
            "provisional_state_signature": self.provisional_state_signature,
            "checkpoint_id": self.checkpoint_id,
        }

    def verify_authority(
        self,
        *,
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        authority: ScopedFunctionalPlanAuthority | None = None,
        goal_authority: ScopedFunctionalPlanAuthority | None = None,
        dependency_graph: Mapping[str, Sequence[str]] | None = None,
        binding_context: FunctionalProblemBindingContext | None = None,
    ) -> None:
        mismatches: list[str] = []
        expected_scalars = {
            "planning_context_id": planning_context.planning_context_id,
            "problem_revision_id": planning_context.problem_revision_id,
            "problem_semantic_hash": planning_context.problem_semantic_hash,
            "functional_problem_binding_signature": (
                binding_catalog.binding_signature
            ),
        }
        for field_name, expected in expected_scalars.items():
            if getattr(self, field_name) != expected:
                mismatches.append(field_name)
        if binding_catalog.planning_context_id != planning_context.planning_context_id:
            mismatches.append("binding_catalog.planning_context_id")
        if binding_catalog.problem_revision_id != planning_context.problem_revision_id:
            mismatches.append("binding_catalog.problem_revision_id")
        if (
            binding_catalog.problem_semantic_hash
            != planning_context.problem_semantic_hash
        ):
            mismatches.append("binding_catalog.problem_semantic_hash")
        known_goal_ids = {
            item.goal_unit_id for item in planning_context.goal_views
        }
        if any(
            goal_id not in known_goal_ids
            for values in self.goal_unit_ids.values()
            for goal_id in values
        ):
            mismatches.append("goal_unit_ids")
        known_source_ids = {
            source_id
            for binding in binding_catalog.bindings.values()
            for source_id in binding.source_unit_ids
        }
        if any(
            source_id not in known_source_ids
            for values in self.source_unit_ids.values()
            for source_id in values
        ):
            mismatches.append("source_unit_ids")
        if authority is not None:
            expected_step_signatures = {
                step_id: item.binding_signature
                for step_id, item in authority.step_authorities.items()
            }
            if self.plan_id != authority.plan_id:
                mismatches.append("plan_id")
            if dict(self.step_binding_signatures) != expected_step_signatures:
                mismatches.append("step_binding_signatures")
        if goal_authority is not None:
            expected_goal_ids = _complete_goal_unit_ids(
                goal_authority.scoped_plan,
                planning_context=planning_context,
                goal_authority=goal_authority,
                blocked_by=_checkpoint_blocked_by(self.root_scope),
                runtime_dependency_graph=dependency_graph or {},
            )
            if self.plan_id != goal_authority.plan_id:
                mismatches.append("plan_id")
            if dict(self.goal_unit_ids) != expected_goal_ids:
                mismatches.append("goal_unit_ids")
        if binding_context is not None:
            expected_source_ids = {
                step_id: tuple(
                    sorted(
                        {
                            source_id
                            for item in binding_context.inputs_for_call(step_id)
                            if item.source_kind == "problem_source"
                            for source_id in item.source_unit_ids
                        }
                    )
                )
                for step_id in self.step_binding_signatures
            }
            if dict(self.source_unit_ids) != expected_source_ids:
                mismatches.append("source_unit_ids")
        if mismatches:
            raise FunctionalGoalExecutionCheckpointError(
                "$.authority",
                "checkpoint authority drift: "
                + ", ".join(sorted(set(mismatches))),
            )

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalGoalExecutionCheckpoint":
        candidate = dict(payload)
        errors = sorted(
            Draft202012Validator(
                functional_goal_execution_checkpoint_schema()
            ).iter_errors(candidate),
            key=lambda item: tuple(item.absolute_path),
        )
        if errors:
            first = errors[0]
            path = "$" + "".join(
                f"[{item}]" if isinstance(item, int) else f".{item}"
                for item in first.absolute_path
            )
            raise FunctionalGoalExecutionCheckpointError(path, first.message)
        metrics = _mapping(candidate["metrics"])
        checkpoint = cls(
            planning_context_id=str(candidate["planning_context_id"]),
            problem_revision_id=str(candidate["problem_revision_id"]),
            problem_semantic_hash=str(candidate["problem_semantic_hash"]),
            plan_id=str(candidate["plan_id"]),
            functional_problem_binding_signature=str(
                candidate["functional_problem_binding_signature"]
            ),
            root_scope=_scope_from_payload(_mapping(candidate["root_scope"])),
            root_issues=tuple(
                _mapping(item)
                for item in _sequence(candidate.get("root_issues", ()))
            ),
            diagnostic_authorities=tuple(
                _mapping(item)
                for item in _sequence(
                    candidate.get("diagnostic_authorities", ())
                )
            ),
            step_binding_signatures={
                str(key): str(value)
                for key, value in _mapping(
                    candidate["step_binding_signatures"]
                ).items()
            },
            goal_unit_ids=_string_tuple_mapping(candidate["goal_unit_ids"]),
            source_unit_ids=_string_tuple_mapping(
                candidate["source_unit_ids"]
            ),
            provisional_state_signature=str(
                candidate["provisional_state_signature"]
            ),
            transaction_attempted=bool(metrics["transaction_attempted"]),
            transaction_ok=bool(metrics["transaction_ok"]),
            all_required_goals_verified=bool(
                metrics["all_required_goals_verified"]
            ),
            blocked_stage=(
                str(metrics["blocked_stage"])
                if metrics["blocked_stage"] is not None
                else None
            ),
            checkpoint_id=str(candidate["checkpoint_id"]),
        )
        expected = stable_hash(_checkpoint_identity_payload(checkpoint))
        if checkpoint.checkpoint_id != expected:
            raise FunctionalGoalExecutionCheckpointError(
                "$.checkpoint_id",
                "checkpoint content hash does not match its authority payload",
            )
        return checkpoint


@dataclass(frozen=True)
class ScopedFunctionalGoalExecutionResult:
    validation_report: ScopedFunctionalPlanValidationReport
    authority_report: ScopedFunctionalPlanAuthorityReport
    authoring_authority: ScopedFunctionalPlanAuthority | None
    authority: ScopedFunctionalPlanAuthority | None
    replay: PlannerRetryReplayResult | None
    checkpoint: FunctionalGoalExecutionCheckpoint | None
    canonical_plan: ScopedFunctionalPlan | None = None
    runtime_equivalent_aliases: tuple[
        FunctionalRuntimeEquivalentCallAlias, ...
    ] = ()


def _normalize_runtime_equivalent_reuses(
    plan: ScopedFunctionalPlan,
    *,
    authority: ScopedFunctionalPlanAuthority,
    runtime_aliases: Sequence[FunctionalRuntimeEquivalentCallAlias],
    restored_seed: FunctionalRestoredCallSeed | None,
    published_goal_bindings: Sequence[ScopedPublishedGoalBinding],
) -> ScopedFunctionalPlan | None:
    """Remove duplicate steps only after actual typed runtime equivalence."""

    step_order = {
        step.step_id: index for index, step in enumerate(plan.steps)
    }
    scope_parents: dict[str, str | None] = {}

    def index_scopes(
        scope: ScopedFunctionalScope,
        parent_scope_id: str | None,
    ) -> None:
        scope_parents[scope.scope_ref] = parent_scope_id
        for child in scope.children:
            index_scopes(child, scope.scope_ref)

    index_scopes(plan.root_scope, None)

    def is_visible_ancestor(
        ancestor_scope_id: str,
        descendant_scope_id: str,
    ) -> bool:
        current: str | None = descendant_scope_id
        while current is not None:
            if current == ancestor_scope_id:
                return True
            current = scope_parents.get(current)
        return False

    answer_step_ids = {
        goal.answer_from.step_id
        for scope in _walk_scopes(plan.root_scope)
        for goal in scope.goals
    }
    protected_step_ids = {
        item.consumer_step_id for item in published_goal_bindings
    } | {
        item.producer_step_id for item in published_goal_bindings
    }
    if restored_seed is not None:
        protected_step_ids.update(restored_seed.call_ids)

    aliases: dict[str, tuple[str, Mapping[str, str]]] = {}
    step_authorities = authority.step_authorities
    for alias in runtime_aliases:
        call_id = alias.duplicate_call_id
        if (
            call_id in answer_step_ids
            or call_id in protected_step_ids
        ):
            continue
        producer_id = alias.canonical_call_id
        if producer_id == call_id:
            continue
        call_authority = step_authorities.get(call_id)
        producer_authority = step_authorities.get(producer_id)
        if call_authority is None or producer_authority is None:
            continue
        if (
            producer_authority.authored_goal_unit_id is not None
            and producer_authority.authored_goal_unit_id
            != call_authority.authored_goal_unit_id
        ):
            continue
        if not is_visible_ancestor(
            producer_authority.plan_scope_id,
            call_authority.plan_scope_id,
        ):
            continue
        if step_order.get(producer_id, -1) >= step_order.get(call_id, -1):
            continue
        aliases[call_id] = (
            producer_id,
            dict(alias.return_aliases),
        )

    if not aliases:
        return None

    def canonical_result_ref(
        step_id: str,
        return_name: str,
    ) -> tuple[str, str]:
        seen: set[str] = set()
        while step_id in aliases and step_id not in seen:
            seen.add(step_id)
            producer_id, return_aliases = aliases[step_id]
            return_name = return_aliases.get(return_name, return_name)
            step_id = producer_id
        return step_id, return_name

    def rewrite(value: Any) -> Any:
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        normalized = {key: rewrite(item) for key, item in value.items()}
        if "step_id" in normalized and "return" in normalized:
            step_id, return_name = canonical_result_ref(
                str(normalized["step_id"]),
                str(normalized["return"]),
            )
            normalized["step_id"] = step_id
            normalized["return"] = return_name
        return normalized

    def rewrite_scope(scope_payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(scope_payload)
        if isinstance(normalized.get("steps"), list):
            steps = [
                rewrite(step)
                for step in normalized["steps"]
                if str(step.get("step_id", "")) not in aliases
            ]
            if steps:
                normalized["steps"] = steps
            else:
                normalized.pop("steps", None)
        if isinstance(normalized.get("goals"), list):
            goals: list[dict[str, Any]] = []
            for goal in normalized["goals"]:
                rewritten_goal = rewrite(goal)
                goal_steps = rewritten_goal.get("steps")
                if isinstance(goal_steps, list):
                    goal_steps = [
                        step
                        for step in goal_steps
                        if str(step.get("step_id", "")) not in aliases
                    ]
                    if goal_steps:
                        rewritten_goal["steps"] = goal_steps
                    else:
                        rewritten_goal.pop("steps", None)
                goals.append(rewritten_goal)
            normalized["goals"] = goals
        if isinstance(normalized.get("children"), list):
            normalized["children"] = [
                rewrite_scope(child) for child in normalized["children"]
            ]
        return normalized

    payload = plan.to_payload()
    payload["root_scope"] = rewrite_scope(payload["root_scope"])
    normalized_plan, report = (
        ScopedFunctionalPlanValidator().validate_payload_with_report(payload)
    )
    if normalized_plan is None:
        first = report.issues[0]
        raise ScopedFunctionalPlanError(
            "functional.runtime_equivalent_reuse_invalid",
            first.path,
            first.message,
            retryable=False,
        )
    return normalized_plan


def _walk_scopes(root: ScopedFunctionalScope) -> tuple[ScopedFunctionalScope, ...]:
    scopes: list[ScopedFunctionalScope] = []

    def visit(scope: ScopedFunctionalScope) -> None:
        scopes.append(scope)
        for child in scope.children:
            visit(child)

    visit(root)
    return tuple(scopes)


def _checkpoint_identity_payload(
    checkpoint: FunctionalGoalExecutionCheckpoint,
) -> dict[str, Any]:
    payload = checkpoint.authority_payload()
    payload.pop("checkpoint_id", None)
    return payload


def _scope_from_payload(
    payload: Mapping[str, Any],
) -> FunctionalGoalExecutionScope:
    return FunctionalGoalExecutionScope(
        scope_ref=str(payload["scope_ref"]),
        scope_steps=tuple(
            _step_from_payload(_mapping(item))
            for item in _sequence(payload.get("scope_steps", ()))
        ),
        goals=tuple(
            _goal_from_payload(_mapping(item))
            for item in _sequence(payload.get("goals", ()))
        ),
        children=tuple(
            _scope_from_payload(_mapping(item))
            for item in _sequence(payload.get("children", ()))
        ),
    )


def _goal_from_payload(
    payload: Mapping[str, Any],
) -> FunctionalGoalExecutionGoal:
    return FunctionalGoalExecutionGoal(
        goal_ref=str(payload["goal_ref"]),
        status=str(payload["status"]),
        steps=tuple(
            _step_from_payload(_mapping(item))
            for item in _sequence(payload.get("steps", ()))
        ),
    )


def _step_from_payload(
    payload: Mapping[str, Any],
) -> FunctionalGoalExecutionStep:
    typed_issue = payload.get("typed_issue")
    return FunctionalGoalExecutionStep(
        step_id=str(payload["step_id"]),
        status=str(payload["status"]),  # type: ignore[arg-type]
        authored_step=_mapping(payload["authored_step"]),
        resolved_inputs=tuple(
            _mapping(item)
            for item in _sequence(payload.get("resolved_inputs", ()))
        ),
        actual_outputs=tuple(
            _mapping(item)
            for item in _sequence(payload.get("actual_outputs", ()))
        ),
        typed_issue=(
            _mapping(typed_issue) if typed_issue is not None else None
        ),
        blocked_by=tuple(
            str(item)
            for item in _sequence(payload.get("blocked_by", ()))
        ),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FunctionalGoalExecutionCheckpointError(
            "$",
            "expected an object",
        )
    return value


def _sequence(value: object) -> Sequence[Any]:
    if not isinstance(value, (tuple, list)):
        raise FunctionalGoalExecutionCheckpointError(
            "$",
            "expected an array",
        )
    return value


def _string_tuple_mapping(value: object) -> dict[str, tuple[str, ...]]:
    return {
        str(key): tuple(str(item) for item in _sequence(items))
        for key, items in _mapping(value).items()
    }


class ScopedFunctionalGoalExecutionService:
    """Execute every authority-valid v2 prefix in one provisional attempt."""

    def execute_raw_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        planning_context: ProblemPlanningContext,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        planner_state_context: PlannerStateContext,
        problem_payload: dict[str, Any],
        attempt: int = 0,
        retry_checkpoint: FunctionalRetryGraphCheckpoint | None = None,
        restored_seed: FunctionalRestoredCallSeed | None = None,
        published_goal_bindings: Sequence[ScopedPublishedGoalBinding] = (),
    ) -> ScopedFunctionalGoalExecutionResult:
        plan, validation = ScopedFunctionalPlanValidator().validate_json_with_report(
            raw_response
        )
        if plan is None:
            return ScopedFunctionalGoalExecutionResult(
                validation,
                ScopedFunctionalPlanAuthorityReport(issues=validation.issues),
                None,
                None,
                None,
                None,
                None,
            )
        if published_goal_bindings:
            plan = apply_scoped_published_goal_bindings(
                plan,
                published_goal_bindings,
            )
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
        adapter = ScopedFunctionalPlanAuthorityAdapter()
        try:
            canonical_plan, normalizations = adapter.canonicalize(
                plan,
                planning_context=planning_context,
                binding_catalog=problem_binding_catalog,
                capability_catalog=catalog,
            )
        except ScopedFunctionalPlanError as exc:
            if not exc.retryable:
                raise
            report = ScopedFunctionalPlanAuthorityReport(
                issues=exc.issues,
                normalizations=exc.normalizations,
            )
            step_issues = _scoped_step_issue_payloads(
                plan,
                report.issues,
                stage="authoring_authority",
            )
            root_issues = _scoped_root_issue_payloads(
                plan,
                report.issues,
                stage="authoring_authority",
            )
            blocked_by = _blocked_step_ids(plan, tuple(step_issues))
            checkpoint = _build_checkpoint(
                plan,
                canonical_plan=plan,
                planning_context=planning_context,
                binding_catalog=problem_binding_catalog,
                report=report,
                authority=None,
                goal_authority=None,
                replay=None,
                blocked_by=blocked_by,
                step_issues=step_issues,
                root_issues=root_issues,
                blocked_stage="authoring_authority",
            )
            return ScopedFunctionalGoalExecutionResult(
                validation,
                report,
                None,
                None,
                None,
                checkpoint,
                plan,
            )

        authority, report = adapter.analyze(
            canonical_plan,
            planning_context=planning_context,
            binding_catalog=problem_binding_catalog,
            capability_catalog=catalog,
        )
        if authority is not None:
            authority = replace(
                authority,
                normalizations=tuple(normalizations),
            )
        report = ScopedFunctionalPlanAuthorityReport(
            issues=report.issues,
            normalizations=normalizations,
        )
        authoring_authority = authority
        step_issues = _scoped_step_issue_payloads(
            canonical_plan,
            report.issues,
            stage="authoring_authority",
        )
        root_issues = list(
            _scoped_root_issue_payloads(
                canonical_plan,
                report.issues,
                stage="authoring_authority",
            )
        )
        invalid = set(step_issues)
        blocked_by: dict[str, tuple[str, ...]] = {}
        implicit_blocked_by: dict[str, tuple[str, ...]] = {}
        working_authority = authority
        replay: PlannerRetryReplayResult | None = None
        replay_service = PlannerRetryReplayService(
            functional_transaction_mode="context_authoritative",
            functional_symbolic_closure_mode="authoritative",
        )
        blocked_stage: str | None = (
            "authoring_authority" if report.issues else None
        )
        for _iteration in range(len(canonical_plan.steps) + 1):
            blocked_by = _blocked_step_ids(
                canonical_plan,
                tuple((*invalid, *implicit_blocked_by)),
            )
            blocked_by.update(implicit_blocked_by)
            excluded = frozenset((*invalid, *blocked_by))
            if excluded or working_authority is None:
                if len(excluded) >= len(canonical_plan.steps):
                    working_authority = None
                    break
                try:
                    working_authority = adapter.lower_executable_subset(
                        canonical_plan,
                        excluded_step_ids=tuple(excluded),
                        planning_context=planning_context,
                        binding_catalog=problem_binding_catalog,
                        capability_catalog=catalog,
                    )
                except ScopedFunctionalPlanError as exc:
                    new_step_issues = _scoped_step_issue_payloads(
                        canonical_plan,
                        exc.issues,
                        stage="authoring_authority",
                    )
                    new_ids = set(new_step_issues) - invalid
                    if new_ids:
                        step_issues.update(new_step_issues)
                        invalid.update(new_ids)
                        report = _merge_authority_report(
                            report,
                            exc.issues,
                        )
                        blocked_stage = "authoring_authority"
                        continue
                    root_issues.extend(
                        _scoped_root_issue_payloads(
                            canonical_plan,
                            exc.issues,
                            stage="authoring_authority",
                        )
                    )
                    blocked_stage = "authoring_authority"
                    working_authority = None
                    break

            if working_authority is None or not working_authority.lowered_plan.calls:
                break
            prepared = replay_service.reconcile_functional_plan(
                working_authority.lowered_plan,
                inputs=inputs,
                handle_registry=handle_registry,
                context=context,
                attempt=attempt,
                problem_payload=problem_payload,
                planner_state_context=planner_state_context,
                problem_binding_catalog=problem_binding_catalog,
                preserve_scoped_step_identity=True,
                scoped_call_goal_bindings={
                    step_id: item.consumer_goal_unit_ids
                    for step_id, item in (
                        working_authority.step_authorities.items()
                    )
                },
                allow_incomplete_goals=bool(excluded),
                retry_checkpoint=retry_checkpoint,
            )
            replay = prepared
            reconciliation = prepared.functional_reconciliation
            if reconciliation is None:
                root_issues.append(
                    {
                        "stage": "reconciliation_binding",
                        "code": "functional.reconciliation_missing",
                        "message": "reconciliation did not return a typed report",
                    }
                )
                blocked_stage = "reconciliation_binding"
                break
            localizable = tuple(
                issue
                for issue in reconciliation.issues
                if _localizable_reconciliation_issue(issue)
            )
            direct_localizable = tuple(
                issue
                for issue in localizable
                if not _implicit_state_dependency_issue(issue)
            )
            new_ids = {
                issue.call_id
                for issue in direct_localizable
                if issue.call_id is not None and issue.call_id not in invalid
            }
            if direct_localizable and new_ids:
                for issue in direct_localizable:
                    if issue.call_id is None:
                        continue
                    step_issues[issue.call_id] = (
                        _reconciliation_issue_payload(
                            issue,
                            binding_catalog=problem_binding_catalog,
                            planning_context=planning_context,
                        )
                    )
                invalid.update(new_ids)
                blocked_stage = "reconciliation_binding"
                continue
            dependency_blocks = _reconciliation_dependency_blocks(
                canonical_plan,
                reconciliation.issues,
                binding_catalog=problem_binding_catalog,
                invalid_step_ids=invalid,
                blocked_by=blocked_by,
            )
            changed_dependency_blocks = {
                step_id: roots
                for step_id, roots in dependency_blocks.items()
                if implicit_blocked_by.get(step_id) != roots
            }
            if changed_dependency_blocks:
                implicit_blocked_by.update(changed_dependency_blocks)
                blocked_stage = "reconciliation_binding"
                continue
            remaining_localizable = tuple(
                issue
                for issue in localizable
                if issue.call_id not in implicit_blocked_by
            )
            remaining_new_ids = {
                issue.call_id
                for issue in remaining_localizable
                if issue.call_id is not None and issue.call_id not in invalid
            }
            if remaining_new_ids:
                for issue in remaining_localizable:
                    if issue.call_id in remaining_new_ids:
                        step_issues[issue.call_id] = (
                            _reconciliation_issue_payload(
                                issue,
                                binding_catalog=problem_binding_catalog,
                                planning_context=planning_context,
                            )
                        )
                invalid.update(remaining_new_ids)
                blocked_stage = "reconciliation_binding"
                continue
            if localizable:
                root_issues.append(
                    {
                        "stage": "reconciliation_binding",
                        "code": "functional.incremental_reconciliation_no_progress",
                        "message": "reconciliation repeated the same local step issues",
                    }
                )
                blocked_stage = "reconciliation_binding"
                break
            if reconciliation.issues:
                root_issues.extend(
                    _reconciliation_root_issue_payloads(
                        reconciliation.issues,
                        binding_catalog=problem_binding_catalog,
                        planning_context=planning_context,
                    )
                )
                blocked_stage = "reconciliation_binding"
                break

            finalized, finalization_report = (
                working_authority.finalize_reconciliation(reconciliation)
            )
            if finalized is None:
                final_step_issues = _scoped_step_issue_payloads(
                    canonical_plan,
                    finalization_report.issues,
                    stage="placement_finalize",
                )
                step_issues.update(final_step_issues)
                invalid.update(final_step_issues)
                root_issues.extend(
                    _scoped_root_issue_payloads(
                        canonical_plan,
                        finalization_report.issues,
                        stage="placement_finalize",
                    )
                )
                blocked_stage = "placement_finalize"
                break
            working_authority = finalized
            restored_seed = rebase_restored_call_seed(
                restored_seed,
                reconciliation,
            )
            replay = replay_service.execute_reconciled_functional_plan(
                prepared,
                raw_plan=finalized.lowered_plan,
                parent_context=planner_state_context,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
                runtime_context=context,
                finalized_authority=finalized,
                restored_seed=restored_seed,
            )
            transaction = replay.transactional_attempt_result
            runtime_aliases = (
                transaction.execution_report.runtime_equivalent_aliases
                if transaction is not None
                else ()
            )
            normalized_reuse_plan = _normalize_runtime_equivalent_reuses(
                canonical_plan,
                authority=working_authority,
                runtime_aliases=runtime_aliases,
                restored_seed=restored_seed,
                published_goal_bindings=published_goal_bindings,
            )
            if normalized_reuse_plan is not None:
                normalized_result = self.execute_raw_json(
                    json.dumps(
                        normalized_reuse_plan.to_payload(),
                        ensure_ascii=False,
                    ),
                    inputs=inputs,
                    planning_context=planning_context,
                    problem_binding_catalog=problem_binding_catalog,
                    handle_registry=handle_registry,
                    context=context,
                    planner_state_context=planner_state_context,
                    problem_payload=problem_payload,
                    attempt=attempt,
                    retry_checkpoint=retry_checkpoint,
                    restored_seed=restored_seed,
                    published_goal_bindings=published_goal_bindings,
                )
                return replace(
                    normalized_result,
                    runtime_equivalent_aliases=(
                        *runtime_aliases,
                        *normalized_result.runtime_equivalent_aliases,
                    ),
                )
            if transaction is not None and transaction.root_issues:
                blocked_stage = "runtime"
            break
        else:
            root_issues.append(
                {
                    "stage": "reconciliation_binding",
                    "code": "functional.incremental_reconciliation_no_progress",
                    "message": "incremental reconciliation exceeded its bounded iterations",
                }
            )
            blocked_stage = "reconciliation_binding"

        checkpoint = _build_checkpoint(
            plan,
            canonical_plan=canonical_plan,
            planning_context=planning_context,
            binding_catalog=problem_binding_catalog,
            report=report,
            authority=working_authority,
            goal_authority=authoring_authority,
            replay=replay,
            blocked_by=blocked_by,
            step_issues=step_issues,
            root_issues=tuple(root_issues),
            blocked_stage=blocked_stage,
        )
        return ScopedFunctionalGoalExecutionResult(
            validation,
            report,
            authoring_authority,
            working_authority,
            replay,
            checkpoint,
            canonical_plan,
        )


def _merge_authority_report(
    report: ScopedFunctionalPlanAuthorityReport,
    issues: Sequence[ScopedFunctionalPlanIssue],
) -> ScopedFunctionalPlanAuthorityReport:
    merged = {
        (item.code, item.path, item.message): item
        for item in (*report.issues, *issues)
    }
    return ScopedFunctionalPlanAuthorityReport(
        issues=tuple(merged[key] for key in sorted(merged)),
        normalizations=report.normalizations,
    )


def _scoped_step_issue_payloads(
    plan: ScopedFunctionalPlan,
    issues: Sequence[ScopedFunctionalPlanIssue],
    *,
    stage: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for issue in issues:
        for step_id in sorted(_issue_step_ids(plan, (issue,))):
            result.setdefault(
                step_id,
                {
                    "stage": stage,
                    **issue.to_payload(),
                },
            )
    return result


def _scoped_root_issue_payloads(
    plan: ScopedFunctionalPlan,
    issues: Sequence[ScopedFunctionalPlanIssue],
    *,
    stage: str,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            "stage": stage,
            **issue.to_payload(),
        }
        for issue in issues
        if not _issue_step_ids(plan, (issue,))
    )


def _localizable_reconciliation_issue(issue: Any) -> bool:
    details = issue.details or {}
    if issue.call_id is None:
        return False
    authority = diagnostic_authority_from_issue(
        issue,
        stage=str(details.get("stage") or "reconciliation_binding"),
    )
    return authority.retryability == "planner_repairable"


_IMPLICIT_STATE_DEPENDENCY_CODES = frozenset(
    {
        "functional.arg_state_unavailable",
        "functional.condition_role_state_unavailable",
        "functional.equal_length_ray_point_state_unavailable",
        "functional.path_reduction_point_state_unavailable",
        "functional.square_path_point_state_unavailable",
    }
)


def _implicit_state_dependency_issue(issue: Any) -> bool:
    details = issue.details or {}
    return (
        issue.code in _IMPLICIT_STATE_DEPENDENCY_CODES
        and isinstance(details.get("object_ref"), str)
    )


def _reconciliation_issue_payload(
    issue: Any,
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
    planning_context: ProblemPlanningContext,
) -> Mapping[str, Any]:
    details = issue.details or {}
    stage = str(details.get("stage") or "reconciliation_binding")
    authority = diagnostic_authority_from_issue(issue, stage=stage)
    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        binding_catalog,
        planning_context,
    )
    return {
        **prompt.to_payload(),
        "_diagnostic_authority": authority.to_payload(),
    }


def _reconciliation_root_issue_payloads(
    issues: Sequence[Any],
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
    planning_context: ProblemPlanningContext,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(
        {
            **_reconciliation_issue_payload(
                issue,
                binding_catalog=binding_catalog,
                planning_context=planning_context,
            ),
            **(
                {"step_id": issue.call_id}
                if issue.call_id is not None
                else {}
            ),
        }
        for issue in issues
    )


def _public_semantic_refs_for_object_refs(
    value: object,
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list, set, frozenset)):
        return ()
    object_refs = {str(item) for item in value}
    return tuple(
        sorted(
            {
                binding.semantic_ref.ref
                for binding in binding_catalog.bindings.values()
                if binding.usage == "input"
                and any(
                    source.math_object_id is not None
                    and source.math_object_id.value in object_refs
                    for source in binding.typed_sources
                )
            }
        )
    )


def _reconciliation_dependency_blocks(
    plan: ScopedFunctionalPlan,
    issues: Sequence[Any],
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
    invalid_step_ids: set[str],
    blocked_by: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Recover hidden object-state dependencies without changing the plan."""

    producer_index, step_scope_ids = _step_output_object_producers(
        plan,
        binding_catalog=binding_catalog,
    )
    result: dict[str, tuple[str, ...]] = {}
    for issue in issues:
        if issue.call_id is None:
            continue
        details = issue.details or {}
        object_ref = details.get("object_ref")
        consumer_scope_id = issue.scope_id or step_scope_ids.get(issue.call_id)
        if not isinstance(object_ref, str) or consumer_scope_id is None:
            continue
        roots: set[str] = set()
        for producer_id in producer_index.get(object_ref, ()):
            producer_scope_id = step_scope_ids.get(producer_id)
            if producer_scope_id is None or not _scope_is_ancestor(
                producer_scope_id,
                consumer_scope_id,
                binding_catalog.scope_parent_ids,
            ):
                continue
            if producer_id in invalid_step_ids:
                roots.add(producer_id)
            elif producer_id in blocked_by:
                roots.update(blocked_by[producer_id])
        if roots:
            result[issue.call_id] = tuple(sorted(roots))
    return dict(sorted(result.items()))


def _step_output_object_producers(
    plan: ScopedFunctionalPlan,
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    producers: dict[str, set[str]] = {}
    step_scope_ids: dict[str, str] = {}
    for scope in _iter_scopes(plan.root_scope):
        scoped_steps = (
            *scope.steps,
            *(step for goal in scope.goals for step in goal.steps),
        )
        for step in scoped_steps:
            step_scope_ids[step.step_id] = scope.scope_ref
            for target_ref in step.output_targets.values():
                try:
                    binding = binding_catalog.resolve_input_binding(
                        scope_id=scope.scope_ref,
                        local_ref=target_ref,
                    )
                except ProblemPlanningBindingError:
                    continue
                for source in binding.typed_sources:
                    if source.math_object_id is not None:
                        producers.setdefault(
                            source.math_object_id.value,
                            set(),
                        ).add(step.step_id)
    return (
        {
            object_id: tuple(sorted(step_ids))
            for object_id, step_ids in sorted(producers.items())
        },
        step_scope_ids,
    )


def _scope_is_ancestor(
    ancestor_scope_id: str,
    scope_id: str,
    scope_parent_ids: Mapping[str, str | None],
) -> bool:
    current: str | None = scope_id
    while current is not None:
        if current == ancestor_scope_id:
            return True
        current = scope_parent_ids.get(current)
    return False


def _complete_goal_unit_ids(
    plan: ScopedFunctionalPlan,
    *,
    planning_context: ProblemPlanningContext,
    goal_authority: ScopedFunctionalPlanAuthority | None,
    blocked_by: Mapping[str, tuple[str, ...]],
    runtime_dependency_graph: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Preserve the complete authored Goal DAG when execution uses a subset."""

    steps = {item.step_id: item for item in plan.steps}
    runtime_dependencies = runtime_dependency_graph or {}
    goal_units = {
        item.answer_ref.ref: item.goal_unit_id
        for item in planning_context.goal_views
    }
    goal_owners = {
        item.goal_unit_id: item.owner_scope_id
        for item in planning_context.goal_views
    }
    scope_parents = {
        item.scope_id: item.parent_scope_id
        for item in planning_context.scopes
    }
    step_scopes: dict[str, str] = {}
    scope_owned_steps: set[str] = set()
    dependencies: dict[str, set[str]] = {
        step_id: set() for step_id in steps
    }
    non_propagating: set[tuple[str, str]] = set()
    consumers: dict[str, set[str]] = {
        step_id: set(
            goal_authority.step_authorities[step_id].consumer_goal_unit_ids
        )
        if goal_authority is not None
        and step_id in goal_authority.step_authorities
        else set()
        for step_id in steps
    }

    for scope in _iter_scopes(plan.root_scope):
        for step in scope.steps:
            step_scopes[step.step_id] = scope.scope_ref
            scope_owned_steps.add(step.step_id)
        for goal in scope.goals:
            goal_unit_id = goal_units.get(goal.goal_ref)
            if (
                goal_authority is None
                and goal_unit_id is not None
                and goal.answer_from.step_id in consumers
            ):
                consumers[goal.answer_from.step_id].add(goal_unit_id)
            for step in goal.steps:
                step_scopes[step.step_id] = scope.scope_ref

    for step in steps.values():
        for values in step.args.values():
            for value in values:
                if not isinstance(value, ScopedStepResultRef):
                    continue
                if value.step_id not in steps:
                    continue
                dependencies[step.step_id].add(value.step_id)
                if isinstance(value, ScopedPublishedGoalResultRef):
                    non_propagating.add((step.step_id, value.step_id))
        for root in blocked_by.get(step.step_id, ()):
            if root in steps:
                dependencies[step.step_id].add(root)
        dependencies[step.step_id].update(
            dependency
            for dependency in runtime_dependencies.get(step.step_id, ())
            if dependency in steps
        )

    changed = True
    while changed:
        changed = False
        for consumer_id, producer_ids in dependencies.items():
            for producer_id in producer_ids:
                if (consumer_id, producer_id) in non_propagating:
                    continue
                before = len(consumers[producer_id])
                consumers[producer_id].update(consumers[consumer_id])
                changed = changed or len(consumers[producer_id]) != before

    # An invalid scope-owned step may be disconnected before lowering can prove
    # its exact consumers. Keep it attached to descendant Goals so retry repairs
    # the shared scope block instead of losing the step from Goal authority.
    for step_id in scope_owned_steps if goal_authority is None else ():
        if consumers[step_id]:
            continue
        owner_scope_id = step_scopes[step_id]
        consumers[step_id].update(
            goal_id
            for goal_id, goal_scope_id in goal_owners.items()
            if _scope_is_ancestor(
                owner_scope_id,
                goal_scope_id,
                scope_parents,
            )
        )

    return {
        step_id: tuple(sorted(consumers[step_id]))
        for step_id in sorted(steps)
    }


def _checkpoint_blocked_by(
    root: FunctionalGoalExecutionScope,
) -> dict[str, tuple[str, ...]]:
    return {
        step.step_id: step.blocked_by
        for scope in _iter_execution_scopes(root)
        for step in (
            *scope.scope_steps,
            *(item for goal in scope.goals for item in goal.steps),
        )
        if step.blocked_by
    }


def _build_checkpoint(
    plan: ScopedFunctionalPlan,
    *,
    canonical_plan: ScopedFunctionalPlan,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    report: ScopedFunctionalPlanAuthorityReport,
    authority: ScopedFunctionalPlanAuthority | None,
    goal_authority: ScopedFunctionalPlanAuthority | None = None,
    replay: PlannerRetryReplayResult | None,
    blocked_by: Mapping[str, tuple[str, ...]],
    step_issues: Mapping[str, Mapping[str, Any]],
    root_issues: Sequence[Mapping[str, Any]],
    blocked_stage: str | None,
) -> FunctionalGoalExecutionCheckpoint:
    invalid_issues = dict(step_issues)
    transaction = replay.transactional_attempt_result if replay is not None else None
    call_states = {
        item.call_id: item
        for item in (
            transaction.execution_report.call_states if transaction is not None else ()
        )
    }
    call_results = {
        item.call_id: item
        for item in (
            transaction.execution_report.call_results if transaction is not None else ()
        )
    }
    pruned = frozenset(authority.pruned_step_ids if authority is not None else ())
    forbidden_prompt_values = _internal_prompt_values(
        planning_context,
        binding_catalog,
    )
    diagnostic_authorities: list[Mapping[str, Any]] = []
    diagnostic_signatures: set[str] = set()

    def prompt_diagnostic(issue_payload: Mapping[str, Any]) -> dict[str, Any]:
        candidate = dict(issue_payload)
        authority_payload = candidate.pop("_diagnostic_authority", None)
        if authority_payload is None:
            authority_payload = candidate.pop("diagnostic_authority", None)
        if authority_payload is not None:
            authority = FunctionalDiagnosticAuthority.from_payload(
                _mapping(authority_payload)
            )
        else:
            authority = diagnostic_authority_from_issue(
                candidate,
                stage=str(candidate.get("stage") or "execution"),
                step_id=(
                    str(candidate["step_id"])
                    if candidate.get("step_id") is not None
                    else None
                ),
            )
        authority_wire = authority.to_payload()
        signature = stable_hash(authority_wire)
        if signature not in diagnostic_signatures:
            diagnostic_signatures.add(signature)
            diagnostic_authorities.append(authority_wire)
        projected = FunctionalPromptDiagnosticProjector().project(
            authority,
            binding_catalog,
            planning_context,
        )
        return projected.to_payload()
    canonical_steps = {
        item.step_id: item for item in canonical_plan.steps
    }
    step_scopes = {
        step.step_id: scope.scope_ref
        for scope in _iter_scopes(canonical_plan.root_scope)
        for step in (
            *scope.steps,
            *(item for goal in scope.goals for item in goal.steps),
        )
    }

    def step_item(step: Any) -> FunctionalGoalExecutionStep:
        issue = invalid_issues.get(step.step_id)
        state = call_states.get(step.step_id)
        if issue is not None:
            status: FunctionalGoalStepStatus = "authority_invalid"
        elif step.step_id in blocked_by:
            status = "blocked_by_dependency"
        elif step.step_id in pruned:
            status = "pruned_dead"
        elif state is not None and state.status == "verified":
            status = "runtime_verified"
        elif state is not None and state.status == "failed":
            status = "runtime_failed"
        elif state is not None and state.status == "blocked_by_dependency":
            status = "blocked_by_dependency"
        elif authority is not None and step.step_id in authority.step_authorities:
            status = "ready"
        else:
            status = "valid"
        result = call_results.get(step.step_id)
        outputs = tuple(
            {
                "return": _public_runtime_result_name(result, item),
                "runtime_type": item.runtime_type,
                **(
                    {
                        "value": _prompt_safe_value(
                            item.value,
                            forbidden_values=forbidden_prompt_values,
                        )
                    }
                    if item.value is not None
                    else {}
                ),
                **(
                    {"value_omitted_reason": item.value_omitted_reason}
                    if item.value_omitted_reason is not None
                    else {}
                ),
            }
            for item in (result.runtime_results if result is not None else ())
        )
        runtime_issue = (
            prompt_diagnostic(
                {
                    "stage": "runtime",
                    **result.root_issues[0].to_authority_payload(),
                }
            )
            if result is not None and result.root_issues
            else None
        )
        return FunctionalGoalExecutionStep(
            step_id=step.step_id,
            status=status,
            authored_step=step.to_payload(),
            resolved_inputs=_prompt_safe_inputs(
                canonical_steps.get(step.step_id, step),
                binding_catalog=binding_catalog,
                scope_id=step_scopes[step.step_id],
                call_results=call_results,
                forbidden_values=forbidden_prompt_values,
            ),
            actual_outputs=outputs,
            typed_issue=(
                prompt_diagnostic(dict(issue))
                if issue is not None
                else runtime_issue
            ),
            blocked_by=(
                blocked_by[step.step_id]
                if step.step_id in blocked_by
                else (
                    tuple(state.dependency_call_ids)
                    if state is not None
                    and state.status == "blocked_by_dependency"
                    else ()
                )
            ),
        )

    def scope_item(scope: ScopedFunctionalScope) -> FunctionalGoalExecutionScope:
        goals = tuple(
            FunctionalGoalExecutionGoal(
                goal_ref=goal.goal_ref,
                status=_goal_status(goal, call_states, invalid_issues, blocked_by),
                steps=tuple(step_item(step) for step in goal.steps),
            )
            for goal in scope.goals
        )
        return FunctionalGoalExecutionScope(
            scope_ref=scope.scope_ref,
            scope_steps=tuple(step_item(step) for step in scope.steps),
            goals=goals,
            children=tuple(scope_item(child) for child in scope.children),
        )

    root_scope = scope_item(canonical_plan.root_scope)
    sidecar = (
        replay.functional_reconciliation.functional_problem_binding_context
        if replay is not None
        and replay.functional_reconciliation is not None
        else None
    )
    reconciliation = (
        replay.functional_reconciliation if replay is not None else None
    )
    step_signatures = {
        step_id: item.binding_signature
        for step_id, item in (
            authority.step_authorities.items() if authority is not None else ()
        )
    }
    goal_ids = _complete_goal_unit_ids(
        canonical_plan,
        planning_context=planning_context,
        goal_authority=goal_authority,
        blocked_by=blocked_by,
        runtime_dependency_graph=(
            reconciliation.dependency_graph
            if reconciliation is not None
            else {}
        ),
    )
    source_ids = {
        step_id: tuple(
            sorted(
                {
                    source_id
                    for item in sidecar.inputs_for_call(step_id)
                    if item.source_kind == "problem_source"
                    for source_id in item.source_unit_ids
                }
            )
        )
        for step_id in step_signatures
    } if sidecar is not None else {}
    provisional_payload = _provisional_state_payload(transaction)
    transaction_attempted = transaction is not None
    transaction_ok = bool(transaction is not None and not transaction.root_issues)
    all_goal_statuses = tuple(
        goal.status
        for scope in _iter_execution_scopes(root_scope)
        for goal in scope.goals
    )
    safe_root_issues = tuple(prompt_diagnostic(item) for item in root_issues)
    all_required_goals_verified = (
        bool(all_goal_statuses)
        and all(
            status == "provisionally_solved"
            for status in all_goal_statuses
        )
        and not safe_root_issues
    )
    checkpoint = FunctionalGoalExecutionCheckpoint(
        planning_context_id=planning_context.planning_context_id,
        problem_revision_id=planning_context.problem_revision_id,
        problem_semantic_hash=planning_context.problem_semantic_hash,
        plan_id=(
            authority.plan_id
            if authority is not None
            else stable_hash(canonical_plan.to_payload())
        ),
        functional_problem_binding_signature=(
            binding_catalog.binding_signature
        ),
        root_scope=root_scope,
        root_issues=safe_root_issues,
        diagnostic_authorities=tuple(diagnostic_authorities),
        step_binding_signatures=step_signatures,
        goal_unit_ids=goal_ids,
        source_unit_ids=source_ids,
        provisional_state_signature=stable_hash(provisional_payload),
        transaction_attempted=transaction_attempted,
        transaction_ok=transaction_ok,
        all_required_goals_verified=all_required_goals_verified,
        blocked_stage=blocked_stage,
        checkpoint_id="pending",
    )
    checkpoint = replace(
        checkpoint,
        checkpoint_id=stable_hash(_checkpoint_identity_payload(checkpoint)),
    )
    _audit_prompt_checkpoint(
        checkpoint.to_prompt_payload(),
        forbidden_values=forbidden_prompt_values,
    )
    return checkpoint


def _prompt_safe_inputs(
    step: Any,
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
    scope_id: str,
    call_results: Mapping[str, Any],
    forbidden_values: frozenset[str],
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for arg_name, values in step.args.items():
        for index, value in enumerate(values):
            item: dict[str, Any] = {
                "arg": arg_name,
                "index": index,
                "source": (
                    value.to_payload()
                    if isinstance(value, ScopedStepResultRef)
                    else value
                ),
            }
            if isinstance(value, ScopedStepResultRef):
                producer = call_results.get(value.step_id)
                runtime_result = _runtime_result_for_return(
                    producer,
                    value.return_name,
                )
                if runtime_result is None:
                    item.update(
                        {
                            "resolution": "unresolved",
                            "value_omitted_reason": (
                                "producer_result_not_available"
                            ),
                        }
                    )
                else:
                    item.update(
                        {
                            "resolution": "step_result",
                            "runtime_type": runtime_result.runtime_type,
                        }
                    )
                    if runtime_result.value is not None:
                        item["value"] = _prompt_safe_value(
                            runtime_result.value,
                            forbidden_values=forbidden_values,
                        )
                    elif runtime_result.value_omitted_reason is not None:
                        item["value_omitted_reason"] = (
                            runtime_result.value_omitted_reason
                        )
            else:
                try:
                    binding = binding_catalog.resolve_input_binding(
                        scope_id=scope_id,
                        local_ref=value,
                    )
                except ProblemPlanningBindingError:
                    binding = None
                item["resolution"] = (
                    "source_snapshot" if binding is not None else "unresolved"
                )
                runtime_types = tuple(
                    sorted(
                        {
                            source.runtime_type
                            for source in (
                                binding.typed_sources
                                if binding is not None
                                else ()
                            )
                            if source.runtime_type is not None
                        }
                    )
                )
                if len(runtime_types) == 1:
                    item["runtime_type"] = runtime_types[0]
                if binding is None:
                    item["value_omitted_reason"] = (
                        "source_authority_not_resolved"
                    )
            result.append(
                item
            )
    return tuple(result)


def _public_runtime_output_name(output_key: str) -> str:
    return output_key.rsplit(".", 1)[-1]


def _public_runtime_result_name(result: Any, runtime_result: Any) -> str:
    write = next(
        (
            item
            for item in (result.state_writes if result is not None else ())
            if item.return_name is not None
            and (
                item.output_key == runtime_result.output_key
                or item.produced_handle == runtime_result.produced_handle
            )
        ),
        None,
    )
    return (
        str(write.return_name)
        if write is not None
        else _public_runtime_output_name(runtime_result.output_key)
    )


def _runtime_result_for_return(result: Any, return_name: str) -> Any | None:
    if result is None:
        return None
    writes = tuple(
        item
        for item in result.state_writes
        if item.return_name == return_name
    )
    if len(writes) == 1:
        write = writes[0]
        matches = tuple(
            item
            for item in result.runtime_results
            if item.output_key == write.output_key
            or item.produced_handle == write.produced_handle
        )
        if len(matches) == 1:
            return matches[0]
    matches = tuple(
        item
        for item in result.runtime_results
        if _runtime_output_matches_return(item.output_key, return_name)
    )
    return matches[0] if len(matches) == 1 else None


def _runtime_output_matches_return(
    output_key: str,
    return_name: str,
) -> bool:
    return output_key == return_name or (
        _public_runtime_output_name(output_key) == return_name
    )


def _issue_step_ids(
    plan: ScopedFunctionalPlan,
    issues: Sequence[ScopedFunctionalPlanIssue],
) -> frozenset[str]:
    result = {
        step.step_id
        for step in plan.steps
        if any(f"$.steps[{step.step_id!r}]" in issue.path for issue in issues)
    }
    answer_producers = {
        goal.answer_from.step_id: goal.goal_ref
        for scope in _iter_scopes(plan.root_scope)
        for goal in scope.goals
    }
    for issue in issues:
        for step_id, goal_ref in answer_producers.items():
            if f"$.goals[{goal_ref!r}]" in issue.path:
                result.add(step_id)
    return frozenset(result)


def _blocked_step_ids(
    plan: ScopedFunctionalPlan,
    invalid_step_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    blocked: dict[str, set[str]] = {}
    invalid = set(invalid_step_ids)
    changed = True
    while changed:
        changed = False
        for step in plan.steps:
            if step.step_id in invalid:
                continue
            roots = {
                value.step_id
                for values in step.args.values()
                for value in values
                if isinstance(value, ScopedStepResultRef)
                and (value.step_id in invalid or value.step_id in blocked)
            }
            roots.update(
                root
                for dependency in tuple(roots)
                for root in blocked.get(dependency, ())
            )
            if roots and blocked.get(step.step_id) != roots:
                blocked[step.step_id] = roots
                changed = True
    return {key: tuple(sorted(value)) for key, value in sorted(blocked.items())}


def _goal_status(
    goal: Any,
    call_states: Mapping[str, Any],
    invalid_issues: Mapping[str, ScopedFunctionalPlanIssue],
    blocked_by: Mapping[str, tuple[str, ...]],
) -> str:
    producer = goal.answer_from.step_id
    if producer in invalid_issues:
        return "authority_invalid"
    if producer in blocked_by:
        return "blocked_by_dependency"
    state = call_states.get(producer)
    if state is None:
        return "pending"
    if state.status == "verified":
        return "provisionally_solved"
    if state.status == "failed":
        return "runtime_failed"
    return state.status


def _checkpoint_metrics(root: FunctionalGoalExecutionScope) -> dict[str, int]:
    counts = {status: 0 for status in (
        "authority_invalid",
        "pruned_dead",
        "runtime_verified",
        "runtime_failed",
        "blocked_by_dependency",
        "ready",
        "valid",
    )}

    def visit(scope: FunctionalGoalExecutionScope) -> None:
        for step in scope.scope_steps:
            counts[step.status] += 1
        for goal in scope.goals:
            for step in goal.steps:
                counts[step.status] += 1
        for child in scope.children:
            visit(child)

    visit(root)
    return {
        "authority_valid_step_count": (
            counts["valid"] + counts["ready"] + counts["runtime_verified"]
            + counts["runtime_failed"] + counts["pruned_dead"]
        ),
        "authority_invalid_step_count": counts["authority_invalid"],
        "pruned_dead_step_count": counts["pruned_dead"],
        "provisional_executed_step_count": (
            counts["runtime_verified"] + counts["runtime_failed"]
        ),
        "blocked_by_dependency_step_count": counts["blocked_by_dependency"],
    }


def _provisional_state_payload(transaction: Any | None) -> dict[str, Any]:
    if transaction is None:
        return {}
    report = transaction.execution_report
    return {
        "call_states": [
            {
                "call_id": item.call_id,
                "status": item.status,
                "dependency_call_ids": list(item.dependency_call_ids),
                "issue_codes": list(item.root_issue_codes),
            }
            for item in report.call_states
        ],
        "call_results": [
            {
                "call_id": item.call_id,
                "status": item.status,
                "runtime_results": [
                    _json_safe_value(result.to_payload())
                    for result in item.runtime_results
                ],
                "root_issues": [issue.to_payload() for issue in item.root_issues],
            }
            for item in report.call_results
        ],
    }


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_safe_value(item) for item in value]
    if hasattr(value, "to_payload"):
        return _json_safe_value(value.to_payload())
    return str(value)


_INTERNAL_PROMPT_KEY_PARTS = (
    "artifact",
    "bundle",
    "canonical_handle",
    "condition_id",
    "math_object",
    "object_ref",
    "problem_revision",
    "problem_semantic_hash",
    "runtime_node",
    "source_unit",
    "state_slot",
    "state_version",
)


def _internal_prompt_values(
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> frozenset[str]:
    values = {
        planning_context.planning_context_id,
        planning_context.problem_revision_id,
        planning_context.problem_semantic_hash,
        binding_catalog.binding_signature,
        binding_catalog.bundle_authority_token.bundle_id,
        binding_catalog.bundle_authority_token.extraction_context_id,
    }
    for binding in binding_catalog.bindings.values():
        values.add(binding.runtime_node_id)
        values.update(binding.source_unit_ids)
        for source in binding.typed_sources:
            if source.condition_id is not None:
                values.add(source.condition_id)
            if source.state_slot_id is not None:
                values.add(source.state_slot_id)
            if source.math_object_id is not None:
                values.add(source.math_object_id.value)
    return frozenset(item for item in values if item)


def _prompt_safe_value(
    value: Any,
    *,
    forbidden_values: frozenset[str],
) -> Any:
    safe = _json_safe_value(value)
    if isinstance(safe, Mapping):
        return {
            str(key): _prompt_safe_value(
                item,
                forbidden_values=forbidden_values,
            )
            for key, item in sorted(safe.items(), key=lambda pair: str(pair[0]))
            if not any(
                fragment in str(key).lower()
                for fragment in _INTERNAL_PROMPT_KEY_PARTS
            )
        }
    if isinstance(safe, list):
        return [
            _prompt_safe_value(item, forbidden_values=forbidden_values)
            for item in safe
        ]
    if isinstance(safe, str) and any(
        forbidden in safe for forbidden in forbidden_values
    ):
        return "<internal-identity-omitted>"
    return safe


def _audit_prompt_checkpoint(
    payload: Mapping[str, Any],
    *,
    forbidden_values: frozenset[str],
) -> None:
    text = str(payload)
    leaks = tuple(
        sorted(value for value in forbidden_values if value in text)
    )
    if leaks:
        raise FunctionalGoalExecutionCheckpointError(
            "$.prompt_payload",
            "prompt-safe checkpoint leaked internal authority",
        )


def _iter_scopes(scope: ScopedFunctionalScope) -> tuple[ScopedFunctionalScope, ...]:
    return (scope, *(item for child in scope.children for item in _iter_scopes(child)))


def _iter_execution_scopes(
    scope: FunctionalGoalExecutionScope,
) -> tuple[FunctionalGoalExecutionScope, ...]:
    return (
        scope,
        *(
            item
            for child in scope.children
            for item in _iter_execution_scopes(child)
        ),
    )


__all__ = [
    "FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT",
    "FunctionalGoalExecutionCheckpoint",
    "FunctionalGoalExecutionCheckpointError",
    "FunctionalGoalExecutionGoal",
    "FunctionalGoalExecutionScope",
    "FunctionalGoalExecutionStep",
    "ScopedFunctionalGoalExecutionResult",
    "ScopedFunctionalGoalExecutionService",
    "functional_goal_execution_checkpoint_schema",
]
