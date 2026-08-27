"""Scope-only FunctionalPlan retry contracts.

The module intentionally keeps the vNext prompt projection and response
application independent from the legacy Goal-repair protocol.  Production is
switched only after the complete contract is covered by tests.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionScope,
    FunctionalGoalExecutionStep,
    ScopedFunctionalGoalExecutionResult,
    _internal_prompt_values,
    _json_safe_value,
    _prompt_safe_value,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalGoalPlan,
    ScopedFunctionalPlan,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedFunctionalPlanValidator,
    scoped_functional_plan_id,
    scoped_functional_plan_schema,
)


FUNCTIONAL_ANNOTATED_PLAN_CONTRACT = "functional-annotated-plan/v1"
FUNCTIONAL_SCOPE_REPAIR_CONTRACT = "functional-scope-repair/v1"
FunctionalAnnotatedExecutionStatus = Literal["succeeded", "failed", "not_run"]


class FunctionalScopeRetryError(ValueError):
    """Typed vNext projection, authority, parsing, or application failure."""

    def __init__(
        self,
        code: str,
        path: str,
        message: str,
        *,
        retryable: bool = True,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        self.retryable = retryable
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code} at {path}: {message}")

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": "validation",
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = _thaw(self.details)
        return payload


@dataclass(frozen=True)
class FunctionalAnnotatedStepExecution:
    status: FunctionalAnnotatedExecutionStatus
    outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    partial_outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    error: Mapping[str, Any] | None = None
    blocked_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "not_run"}:
            raise ValueError(f"unsupported annotated status {self.status!r}")
        object.__setattr__(self, "outputs", _freeze_mapping(self.outputs))
        object.__setattr__(
            self,
            "partial_outputs",
            _freeze_mapping(self.partial_outputs),
        )
        if self.error is not None:
            object.__setattr__(self, "error", _freeze_mapping(self.error))
        object.__setattr__(
            self,
            "blocked_by",
            tuple(sorted(set(self.blocked_by))),
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.outputs:
            payload["outputs"] = _thaw(self.outputs)
        if self.partial_outputs:
            payload["partial_outputs"] = _thaw(self.partial_outputs)
        if self.error is not None:
            payload["error"] = _thaw(self.error)
        if self.blocked_by:
            payload["blocked_by"] = list(self.blocked_by)
        return payload


@dataclass(frozen=True)
class FunctionalAnnotatedStep:
    authored_step: Mapping[str, Any]
    execution: FunctionalAnnotatedStepExecution

    def __post_init__(self) -> None:
        object.__setattr__(self, "authored_step", _freeze_mapping(self.authored_step))

    @property
    def step_id(self) -> str:
        return str(self.authored_step["step_id"])

    def to_payload(self) -> dict[str, Any]:
        return {**_thaw(self.authored_step), "execution": self.execution.to_payload()}


@dataclass(frozen=True)
class FunctionalAnnotatedGoal:
    goal_ref: str
    required_answer: Mapping[str, Any]
    execution: Mapping[str, Any]
    steps: tuple[FunctionalAnnotatedStep, ...]
    answer_from: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_answer", _freeze_mapping(self.required_answer))
        object.__setattr__(self, "execution", _freeze_mapping(self.execution))
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "answer_from", MappingProxyType(dict(self.answer_from)))

    def to_payload(self) -> dict[str, Any]:
        return {
            "required_answer": _thaw(self.required_answer),
            "execution": _thaw(self.execution),
            "steps": [item.to_payload() for item in self.steps],
            "answer_from": dict(self.answer_from),
        }


@dataclass(frozen=True)
class FunctionalAnnotatedScope:
    scope_ref: str
    retry_editable: bool
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    scope_steps: tuple[FunctionalAnnotatedStep, ...] = ()
    goals: Mapping[str, FunctionalAnnotatedGoal] = field(default_factory=dict)
    children: tuple["FunctionalAnnotatedScope", ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "diagnostics",
            tuple(_freeze_mapping(item) for item in self.diagnostics),
        )
        object.__setattr__(self, "scope_steps", tuple(self.scope_steps))
        object.__setattr__(
            self,
            "goals",
            MappingProxyType(dict(sorted(self.goals.items()))),
        )
        object.__setattr__(self, "children", tuple(self.children))

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_ref": self.scope_ref,
            "retry_editable": self.retry_editable,
            "diagnostics": [_thaw(item) for item in self.diagnostics],
            "scope_steps": [item.to_payload() for item in self.scope_steps],
            "goals": {
                goal_ref: goal.to_payload()
                for goal_ref, goal in self.goals.items()
            },
            "children": [item.to_payload() for item in self.children],
        }


@dataclass(frozen=True)
class FunctionalAnnotatedPlan:
    root_scope: FunctionalAnnotatedScope
    previous_response_error: Mapping[str, Any] | None = None
    schema_version: str = FUNCTIONAL_ANNOTATED_PLAN_CONTRACT

    def __post_init__(self) -> None:
        if self.schema_version != FUNCTIONAL_ANNOTATED_PLAN_CONTRACT:
            raise ValueError("unsupported annotated Plan contract")
        if self.previous_response_error is not None:
            object.__setattr__(
                self,
                "previous_response_error",
                _freeze_mapping(self.previous_response_error),
            )

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "root_scope": self.root_scope.to_payload(),
        }
        if self.previous_response_error is not None:
            payload["previous_response_error"] = _thaw(
                self.previous_response_error
            )
        errors = tuple(
            Draft202012Validator(functional_annotated_plan_schema()).iter_errors(
                payload
            )
        )
        if errors:
            first = sorted(errors, key=lambda item: tuple(item.absolute_path))[0]
            raise FunctionalScopeRetryError(
                "functional.annotated_plan_invalid",
                _json_path(first.absolute_path),
                first.message,
                retryable=False,
            )
        return payload


@dataclass(frozen=True)
class FunctionalScopeRetryAuthority:
    base_plan: ScopedFunctionalPlan
    base_plan_hash: str
    checkpoint_id: str
    editable_scope_refs: tuple[str, ...]
    authority_id: str = field(init=False)

    def __post_init__(self) -> None:
        expected = scoped_functional_plan_id(self.base_plan)
        if self.base_plan_hash != expected:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_authority_drift",
                "$.base_plan",
                "base Plan hash does not match scope retry authority",
                retryable=False,
            )
        refs = tuple(sorted(set(self.editable_scope_refs)))
        object.__setattr__(self, "editable_scope_refs", refs)
        object.__setattr__(
            self,
            "authority_id",
            stable_hash(
                {
                    "base_plan_hash": self.base_plan_hash,
                    "checkpoint_id": self.checkpoint_id,
                    "editable_scope_refs": list(refs),
                }
            ),
        )

    def debug_payload(self) -> dict[str, Any]:
        return {
            "base_plan_hash": self.base_plan_hash,
            "checkpoint_id": self.checkpoint_id,
            "editable_scope_refs": list(self.editable_scope_refs),
            "authority_id": self.authority_id,
        }


@dataclass(frozen=True)
class FunctionalScopeGoalReplacement:
    goal_ref: str
    steps: tuple[Mapping[str, Any], ...]
    answer_from: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "steps",
            tuple(_freeze_mapping(item) for item in self.steps),
        )
        object.__setattr__(self, "answer_from", MappingProxyType(dict(self.answer_from)))

    def to_payload(self) -> dict[str, Any]:
        return {
            "steps": [_thaw(item) for item in self.steps],
            "answer_from": dict(self.answer_from),
        }


@dataclass(frozen=True)
class FunctionalScopeReplacement:
    scope_ref: str
    scope_steps: tuple[Mapping[str, Any], ...]
    goals: Mapping[str, FunctionalScopeGoalReplacement]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_steps",
            tuple(_freeze_mapping(item) for item in self.scope_steps),
        )
        object.__setattr__(
            self,
            "goals",
            MappingProxyType(dict(sorted(self.goals.items()))),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_steps": [_thaw(item) for item in self.scope_steps],
            "goals": {
                goal_ref: goal.to_payload()
                for goal_ref, goal in self.goals.items()
            },
        }


@dataclass(frozen=True)
class FunctionalScopeRepair:
    scope_replacements: Mapping[str, FunctionalScopeReplacement]
    schema_version: str = FUNCTIONAL_SCOPE_REPAIR_CONTRACT

    def __post_init__(self) -> None:
        if self.schema_version != FUNCTIONAL_SCOPE_REPAIR_CONTRACT:
            raise ValueError("unsupported scope repair contract")
        object.__setattr__(
            self,
            "scope_replacements",
            MappingProxyType(dict(sorted(self.scope_replacements.items()))),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scope_replacements": {
                scope_ref: replacement.to_payload()
                for scope_ref, replacement in self.scope_replacements.items()
            },
        }


@dataclass(frozen=True)
class FunctionalScopeRepairApplication:
    repair: FunctionalScopeRepair
    plan: ScopedFunctionalPlan
    plan_hash: str
    validation_report: Any


class FunctionalScopeRetryAuthorityProjector:
    """Compute the minimal Scope-level repair authority from direct failures."""

    def project(
        self,
        *,
        plan: ScopedFunctionalPlan,
        execution: ScopedFunctionalGoalExecutionResult,
    ) -> FunctionalScopeRetryAuthority:
        checkpoint = execution.checkpoint
        if checkpoint is None:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_authority_unavailable",
                "$.checkpoint",
                "scope retry requires a typed execution checkpoint",
                retryable=False,
            )
        canonical = execution.canonical_plan or plan
        scope_by_ref = {
            scope.scope_ref: scope for scope in _iter_scopes(canonical.root_scope)
        }
        parents = _scope_parent_map(canonical.root_scope)
        step_owners: dict[str, str] = {}
        goal_owners: dict[str, str] = {}
        goal_answers: dict[str, tuple[str, str]] = {}
        for scope in scope_by_ref.values():
            for step in scope.steps:
                step_owners[step.step_id] = scope.scope_ref
            for goal in scope.goals:
                goal_owners[goal.goal_ref] = scope.scope_ref
                goal_answers[goal.goal_ref] = (
                    goal.answer_from.step_id,
                    goal.answer_from.return_name,
                )
                for step in goal.steps:
                    step_owners[step.step_id] = scope.scope_ref

        editable: set[str] = set()
        for scope in _iter_execution_scopes(checkpoint.root_scope):
            for step in (
                *scope.scope_steps,
                *(item for goal in scope.goals for item in goal.steps),
            ):
                if step.status in {"authority_invalid", "runtime_failed"}:
                    owner = step_owners.get(step.step_id)
                    if owner is not None:
                        editable.add(owner)
        for issue in checkpoint.root_issues:
            retryability = str(issue.get("retryability") or "")
            category = str(issue.get("category") or "")
            if retryability in {"configuration", "nonretryable"} or category in {
                "configuration",
                "registry",
            }:
                raise FunctionalScopeRetryError(
                    str(issue.get("code") or "functional.retry_configuration_invalid"),
                    "$.checkpoint.root_issues",
                    str(issue.get("message") or "non-retryable runtime configuration failure"),
                    retryable=False,
                )
            step_id = str(issue.get("step_id") or "")
            goal_ref = str(issue.get("goal_ref") or "")
            scope_ref = str(issue.get("scope_ref") or "")
            if step_id and step_id in step_owners:
                editable.add(step_owners[step_id])
            elif goal_ref and goal_ref in goal_owners:
                editable.add(goal_owners[goal_ref])
            elif scope_ref in scope_by_ref:
                editable.add(scope_ref)
            elif _is_placement_issue(issue):
                candidate_refs = tuple(
                    str(item)
                    for item in issue.get("valid_scope_refs", ())
                    if str(item) in scope_by_ref
                )
                required_scope = str(issue.get("required_scope_ref") or "")
                if required_scope in scope_by_ref:
                    editable.add(required_scope)
                elif candidate_refs:
                    editable.add(_scope_lca(candidate_refs, parents))

        # Anonymous public answers are ordinary StepResultRefs.  When their
        # producer Scope is opened, open each cross-Scope consumer in the same
        # retry so the complete replacement remains self-consistent.
        changed = True
        while changed:
            changed = False
            opened_answer_sources = {
                source
                for goal_ref, source in goal_answers.items()
                if goal_owners[goal_ref] in editable
            }
            for scope in scope_by_ref.values():
                if scope.scope_ref in editable:
                    continue
                if any(
                    _step_reads_any_answer(step, opened_answer_sources)
                    for step in (
                        *scope.steps,
                        *(step for goal in scope.goals for step in goal.steps),
                    )
                ):
                    editable.add(scope.scope_ref)
                    changed = True

        if not editable:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_not_required",
                "$.checkpoint",
                "checkpoint contains no planner-repairable direct failure",
                retryable=False,
            )
        return FunctionalScopeRetryAuthority(
            base_plan=canonical,
            base_plan_hash=scoped_functional_plan_id(canonical),
            checkpoint_id=checkpoint.checkpoint_id,
            editable_scope_refs=tuple(sorted(editable)),
        )


class FunctionalScopeRepairCompiler:
    """Parse and atomically apply complete replacements for open Scopes."""

    def parse_json(
        self,
        raw: str,
        *,
        authority: FunctionalScopeRetryAuthority,
    ) -> FunctionalScopeRepair:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FunctionalScopeRetryError(
                "functional.repair_response_invalid_json",
                "$",
                "scope repair response must be one JSON object",
                details={"line": exc.lineno, "column": exc.colno},
            ) from exc
        schema = functional_scope_repair_schema_for_authority(authority)
        errors = tuple(Draft202012Validator(schema).iter_errors(payload))
        if errors:
            first = sorted(errors, key=lambda item: tuple(item.absolute_path))[0]
            raise FunctionalScopeRetryError(
                "functional.scope_repair_schema_invalid",
                _json_path(first.absolute_path),
                first.message,
            )
        replacements = {
            scope_ref: FunctionalScopeReplacement(
                scope_ref=scope_ref,
                scope_steps=tuple(value["scope_steps"]),
                goals={
                    goal_ref: FunctionalScopeGoalReplacement(
                        goal_ref=goal_ref,
                        steps=tuple(goal["steps"]),
                        answer_from=dict(goal["answer_from"]),
                    )
                    for goal_ref, goal in value["goals"].items()
                },
            )
            for scope_ref, value in payload["scope_replacements"].items()
        }
        return FunctionalScopeRepair(scope_replacements=replacements)

    def apply_json(
        self,
        raw: str,
        *,
        base_plan: ScopedFunctionalPlan,
        authority: FunctionalScopeRetryAuthority,
    ) -> FunctionalScopeRepairApplication:
        return self.apply(
            self.parse_json(raw, authority=authority),
            base_plan=base_plan,
            authority=authority,
        )

    def apply(
        self,
        repair: FunctionalScopeRepair,
        *,
        base_plan: ScopedFunctionalPlan,
        authority: FunctionalScopeRetryAuthority,
    ) -> FunctionalScopeRepairApplication:
        if scoped_functional_plan_id(base_plan) != authority.base_plan_hash:
            raise FunctionalScopeRetryError(
                "functional.scope_repair_stale_plan",
                "$.previous_plan",
                "base Plan no longer matches the internal retry envelope",
                retryable=False,
            )
        actual_refs = set(repair.scope_replacements)
        expected_refs = set(authority.editable_scope_refs)
        if actual_refs != expected_refs:
            raise FunctionalScopeRetryError(
                "functional.scope_repair_boundary_violation",
                "$.scope_replacements",
                f"expected exactly {sorted(expected_refs)}, got {sorted(actual_refs)}",
            )

        def rebuild(scope: ScopedFunctionalScope) -> dict[str, Any]:
            replacement = repair.scope_replacements.get(scope.scope_ref)
            if replacement is None:
                payload = scope.to_payload()
            else:
                payload = {
                    "scope_ref": scope.scope_ref,
                    "steps": [_thaw(item) for item in replacement.scope_steps],
                    "goals": [
                        {
                            "goal_ref": goal_ref,
                            "steps": [_thaw(item) for item in goal.steps],
                            "answer_from": dict(goal.answer_from),
                        }
                        for goal_ref, goal in replacement.goals.items()
                    ],
                }
                if not payload["steps"]:
                    payload.pop("steps")
                for goal in payload["goals"]:
                    if not goal["steps"]:
                        goal.pop("steps")
                if not payload["goals"]:
                    payload.pop("goals")
            children = [rebuild(child) for child in scope.children]
            if children:
                payload["children"] = children
            else:
                payload.pop("children", None)
            return payload

        candidate_payload = {
            "format": base_plan.format,
            "root_scope": rebuild(base_plan.root_scope),
        }
        candidate, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
            candidate_payload
        )
        if candidate is None or not validation.ok:
            first = validation.issues[0] if validation.issues else None
            raise FunctionalScopeRetryError(
                first.code if first is not None else "functional.scope_repair_plan_invalid",
                first.path if first is not None else "$.scope_replacements",
                first.message if first is not None else "replacement produced an invalid Plan",
            )
        return FunctionalScopeRepairApplication(
            repair=repair,
            plan=candidate,
            plan_hash=scoped_functional_plan_id(candidate),
            validation_report=validation,
        )


def functional_scope_repair_schema() -> dict[str, Any]:
    """Return the strict unbound scope-repair response schema."""

    plan_defs = deepcopy(scoped_functional_plan_schema()["$defs"])
    repair_step = deepcopy(plan_defs["step"])
    repair_step["properties"].pop("return_expectations", None)
    goal_body = {
        "type": "object",
        "required": ["steps", "answer_from"],
        "properties": {
            "steps": {
                "type": "array",
                "items": {"$ref": "#/$defs/repair_step"},
            },
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
    scope_body = {
        "type": "object",
        "required": ["scope_steps", "goals"],
        "properties": {
            "scope_steps": {
                "type": "array",
                "items": {"$ref": "#/$defs/repair_step"},
            },
            "goals": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/goal_body"},
            },
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://shuxueshuo.local/schemas/functional-scope-repair.schema.json",
        "title": "Functional Scope Repair v1",
        "type": "object",
        "required": ["schema_version", "scope_replacements"],
        "properties": {
            "schema_version": {"const": FUNCTIONAL_SCOPE_REPAIR_CONTRACT},
            "scope_replacements": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"$ref": "#/$defs/scope_body"},
            },
        },
        "$defs": {
            "source_ref": plan_defs["source_ref"],
            "step_result_ref": plan_defs["step_result_ref"],
            "functional_ref": plan_defs["functional_ref"],
            "answer_from": plan_defs["answer_from"],
            "repair_step": repair_step,
            "goal_body": goal_body,
            "scope_body": scope_body,
        },
        "additionalProperties": False,
    }


def functional_scope_repair_schema_for_authority(
    authority: FunctionalScopeRetryAuthority,
) -> dict[str, Any]:
    """Bind response keys to every and only open Scope and direct Goal."""

    schema = functional_scope_repair_schema()
    scopes = {scope.scope_ref: scope for scope in _iter_scopes(authority.base_plan.root_scope)}
    scope_properties: dict[str, Any] = {}
    for scope_ref in authority.editable_scope_refs:
        scope = scopes.get(scope_ref)
        if scope is None:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_authority_drift",
                "$.editable_scope_refs",
                f"authority names missing Scope {scope_ref!r}",
                retryable=False,
            )
        scope_body = deepcopy(schema["$defs"]["scope_body"])
        goal_refs = [goal.goal_ref for goal in scope.goals]
        scope_body["properties"]["goals"] = {
            "type": "object",
            "required": goal_refs,
            "properties": {
                goal_ref: {"$ref": "#/$defs/goal_body"}
                for goal_ref in goal_refs
            },
            "additionalProperties": False,
        }
        scope_properties[scope_ref] = scope_body
    schema["properties"]["scope_replacements"] = {
        "type": "object",
        "required": list(authority.editable_scope_refs),
        "properties": scope_properties,
        "additionalProperties": False,
    }
    return schema


class FunctionalAnnotatedPlanProjector:
    """Merge a canonical Plan and typed checkpoint into one prompt tree."""

    def project(
        self,
        *,
        plan: ScopedFunctionalPlan,
        execution: ScopedFunctionalGoalExecutionResult,
        editable_scope_refs: Sequence[str],
        planning_context: ProblemPlanningContext | None = None,
        binding_catalog: ProblemPlanningBindingCatalog | None = None,
        previous_response_error: Mapping[str, Any] | None = None,
    ) -> tuple[FunctionalAnnotatedPlan, FunctionalScopeRetryAuthority]:
        checkpoint = execution.checkpoint
        if checkpoint is None:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_authority_unavailable",
                "$.checkpoint",
                "scope retry requires a typed execution checkpoint",
                retryable=False,
            )
        canonical = execution.canonical_plan or plan
        plan_hash = scoped_functional_plan_id(canonical)
        if checkpoint.plan_id != plan_hash:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_authority_drift",
                "$.checkpoint.plan_id",
                "checkpoint does not target the canonical Plan",
                retryable=False,
            )
        scope_refs = {item.scope_ref for item in _iter_scopes(canonical.root_scope)}
        unknown = sorted(set(editable_scope_refs) - scope_refs)
        if unknown:
            raise FunctionalScopeRetryError(
                "functional.scope_retry_boundary_invalid",
                "$.editable_scope_refs",
                f"unknown editable Scope refs {unknown}",
                retryable=False,
            )
        execution_scopes = {
            item.scope_ref: item for item in _iter_execution_scopes(checkpoint.root_scope)
        }
        execution_steps = {
            item.step_id: item
            for scope in execution_scopes.values()
            for item in (
                *scope.scope_steps,
                *(step for goal in scope.goals for step in goal.steps),
            )
        }
        execution_goals = {
            goal.goal_ref: goal
            for scope in execution_scopes.values()
            for goal in scope.goals
        }
        forbidden_values = (
            _internal_prompt_values(planning_context, binding_catalog)
            if planning_context is not None and binding_catalog is not None
            else frozenset()
        )
        required_answers = _required_answer_contracts(planning_context)
        root_issues = tuple(dict(item) for item in checkpoint.root_issues)
        step_issue_ids = {
            str(item.get("step_id")) for item in root_issues if item.get("step_id")
        }
        goal_issue_refs = {
            str(item.get("goal_ref")) for item in root_issues if item.get("goal_ref")
        }
        scoped_issues: dict[str, list[Mapping[str, Any]]] = {}
        for issue in root_issues:
            if issue.get("step_id") or issue.get("goal_ref"):
                continue
            owner = str(issue.get("scope_ref") or canonical.root_scope.scope_ref)
            scoped_issues.setdefault(owner, []).append(
                _project_diagnostic(issue, forbidden_values=forbidden_values)
            )

        def annotated_step(step: ScopedFunctionalStep) -> FunctionalAnnotatedStep:
            executed = execution_steps.get(step.step_id)
            if executed is None:
                annotated_execution = FunctionalAnnotatedStepExecution(
                    status="failed" if step.step_id in step_issue_ids else "not_run",
                    error=(
                        _first_issue_for(
                            root_issues,
                            "step_id",
                            step.step_id,
                            forbidden_values=forbidden_values,
                        )
                        if step.step_id in step_issue_ids
                        else None
                    ),
                )
            else:
                annotated_execution = _project_step_execution(
                    executed,
                    forbidden_values=forbidden_values,
                    root_issue=_first_issue_for(
                        root_issues,
                        "step_id",
                        step.step_id,
                        forbidden_values=forbidden_values,
                    ),
                )
            return FunctionalAnnotatedStep(
                authored_step=step.to_payload(),
                execution=annotated_execution,
            )

        annotated_steps_by_id: dict[str, FunctionalAnnotatedStep] = {}

        def remember(step: FunctionalAnnotatedStep) -> FunctionalAnnotatedStep:
            annotated_steps_by_id[step.step_id] = step
            return step

        def annotated_goal(goal: ScopedFunctionalGoalPlan) -> FunctionalAnnotatedGoal:
            steps = tuple(remember(annotated_step(step)) for step in goal.steps)
            executed_goal = execution_goals.get(goal.goal_ref)
            answer_from = goal.answer_from.to_payload()
            answer = _answer_output(
                answer_from,
                execution_steps=execution_steps,
                forbidden_values=forbidden_values,
            )
            direct_failed = any(item.execution.status == "failed" for item in steps)
            goal_issue = _first_issue_for(
                root_issues,
                "goal_ref",
                goal.goal_ref,
                forbidden_values=forbidden_values,
            )
            if answer is not None and not direct_failed and goal_issue is None:
                goal_execution: dict[str, Any] = {
                    "status": "succeeded",
                    "answer": answer,
                }
            elif direct_failed or goal_issue is not None or (
                executed_goal is not None
                and executed_goal.status
                in {"failed", "blocked", "blocked_by_dependency", "runtime_failed"}
            ):
                goal_execution = {"status": "failed"}
                if goal_issue is not None:
                    goal_execution["error"] = goal_issue
            else:
                goal_execution = {"status": "not_run"}
            return FunctionalAnnotatedGoal(
                goal_ref=goal.goal_ref,
                required_answer=required_answers.get(
                    goal.goal_ref,
                    {"target_ref": goal.goal_ref, "answer_type": "Unknown"},
                ),
                execution=goal_execution,
                steps=steps,
                answer_from=answer_from,
            )

        editable = frozenset(editable_scope_refs)

        def annotated_scope(scope: ScopedFunctionalScope) -> FunctionalAnnotatedScope:
            return FunctionalAnnotatedScope(
                scope_ref=scope.scope_ref,
                retry_editable=scope.scope_ref in editable,
                diagnostics=tuple(scoped_issues.get(scope.scope_ref, ())),
                scope_steps=tuple(remember(annotated_step(step)) for step in scope.steps),
                goals={goal.goal_ref: annotated_goal(goal) for goal in scope.goals},
                children=tuple(annotated_scope(child) for child in scope.children),
            )

        annotated = FunctionalAnnotatedPlan(
            root_scope=annotated_scope(canonical.root_scope),
            previous_response_error=(
                _project_diagnostic(
                    previous_response_error,
                    forbidden_values=forbidden_values,
                )
                if previous_response_error is not None
                else None
            ),
        )
        annotated.to_prompt_payload()
        authority = FunctionalScopeRetryAuthority(
            base_plan=canonical,
            base_plan_hash=plan_hash,
            checkpoint_id=checkpoint.checkpoint_id,
            editable_scope_refs=tuple(editable_scope_refs),
        )
        return annotated, authority


def functional_annotated_plan_schema() -> dict[str, Any]:
    """Return the strict public Annotated Previous Plan schema."""

    plan_defs = deepcopy(scoped_functional_plan_schema()["$defs"])
    nonempty = {"type": "string", "minLength": 1}
    diagnostic = {
        "type": "object",
        "required": ["stage", "code", "message"],
        "properties": {
            "stage": {"enum": ["validation", "runtime"]},
            "code": nonempty,
            "message": nonempty,
            "suggestion": nonempty,
            "expected": {},
            "observed": {},
            "details": {"type": "object"},
        },
        "additionalProperties": False,
    }
    runtime_result = {
        "type": "object",
        "required": ["runtime_type", "value"],
        "properties": {"runtime_type": nonempty, "value": {}},
        "additionalProperties": False,
    }
    execution = {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"enum": ["succeeded", "failed", "not_run"]},
            "outputs": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"$ref": "#/$defs/runtime_result"},
            },
            "partial_outputs": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"$ref": "#/$defs/runtime_result"},
            },
            "error": {"$ref": "#/$defs/diagnostic"},
            "blocked_by": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty,
            },
        },
        "additionalProperties": False,
    }
    annotated_step = deepcopy(plan_defs["step"])
    annotated_step["required"] = [*annotated_step["required"], "execution"]
    annotated_step["properties"]["execution"] = {"$ref": "#/$defs/execution"}
    goal_execution = {
        "type": "object",
        "required": ["status"],
        "properties": {
            "status": {"enum": ["succeeded", "failed", "not_run"]},
            "answer": {"$ref": "#/$defs/runtime_result"},
            "error": {"$ref": "#/$defs/diagnostic"},
        },
        "additionalProperties": False,
    }
    goal = {
        "type": "object",
        "required": ["required_answer", "execution", "steps", "answer_from"],
        "properties": {
            "required_answer": {
                "type": "object",
                "required": ["target_ref", "answer_type"],
                "properties": {"target_ref": nonempty, "answer_type": nonempty},
                "additionalProperties": False,
            },
            "execution": {"$ref": "#/$defs/goal_execution"},
            "steps": {
                "type": "array",
                "items": {"$ref": "#/$defs/annotated_step"},
            },
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
    scope = {
        "type": "object",
        "required": [
            "scope_ref",
            "retry_editable",
            "diagnostics",
            "scope_steps",
            "goals",
            "children",
        ],
        "properties": {
            "scope_ref": nonempty,
            "retry_editable": {"type": "boolean"},
            "diagnostics": {
                "type": "array",
                "items": {"$ref": "#/$defs/diagnostic"},
            },
            "scope_steps": {
                "type": "array",
                "items": {"$ref": "#/$defs/annotated_step"},
            },
            "goals": {
                "type": "object",
                "additionalProperties": {"$ref": "#/$defs/annotated_goal"},
            },
            "children": {
                "type": "array",
                "items": {"$ref": "#/$defs/annotated_scope"},
            },
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://shuxueshuo.local/schemas/functional-annotated-plan.schema.json",
        "title": "Functional Annotated Previous Plan v1",
        "type": "object",
        "required": ["schema_version", "root_scope"],
        "properties": {
            "schema_version": {"const": FUNCTIONAL_ANNOTATED_PLAN_CONTRACT},
            "previous_response_error": {"$ref": "#/$defs/diagnostic"},
            "root_scope": {"$ref": "#/$defs/annotated_scope"},
        },
        "$defs": {
            "source_ref": plan_defs["source_ref"],
            "step_result_ref": plan_defs["step_result_ref"],
            "functional_ref": plan_defs["functional_ref"],
            "answer_from": plan_defs["answer_from"],
            "diagnostic": diagnostic,
            "runtime_result": runtime_result,
            "execution": execution,
            "goal_execution": goal_execution,
            "annotated_step": annotated_step,
            "annotated_goal": goal,
            "annotated_scope": scope,
        },
        "additionalProperties": False,
    }


def _project_step_execution(
    step: FunctionalGoalExecutionStep,
    *,
    forbidden_values: frozenset[str],
    root_issue: Mapping[str, Any] | None,
) -> FunctionalAnnotatedStepExecution:
    status = _annotated_status(step.status)
    projected_outputs = _project_runtime_outputs(
        step.actual_outputs,
        forbidden_values=forbidden_values,
        path=f"$.steps[{step.step_id!r}].actual_outputs",
    )
    if status == "succeeded":
        return FunctionalAnnotatedStepExecution(
            status=status,
            outputs=projected_outputs,
        )
    if status == "failed":
        issue = step.typed_issue or root_issue or {
            "code": "functional.step_execution_failed",
            "message": "The step failed without a more specific public diagnostic.",
        }
        return FunctionalAnnotatedStepExecution(
            status=status,
            partial_outputs=(
                projected_outputs if step.status == "runtime_failed" else {}
            ),
            error=_project_diagnostic(
                issue,
                forbidden_values=forbidden_values,
                default_stage=(
                    "runtime" if step.status == "runtime_failed" else "validation"
                ),
            ),
        )
    return FunctionalAnnotatedStepExecution(
        status=status,
        blocked_by=step.blocked_by,
    )


def _project_runtime_outputs(
    outputs: Sequence[Mapping[str, Any]],
    *,
    forbidden_values: frozenset[str],
    path: str,
) -> dict[str, Mapping[str, Any]]:
    projected: dict[str, Mapping[str, Any]] = {}
    for index, output in enumerate(outputs):
        return_name = str(output.get("return") or "")
        if not return_name or return_name in projected:
            raise FunctionalScopeRetryError(
                "functional.retry_runtime_output_projection_invalid",
                f"{path}[{index}]",
                "materialized runtime result has a missing or duplicate public return name",
                retryable=False,
            )
        if "value_omitted_reason" in output or "value" not in output:
            raise FunctionalScopeRetryError(
                "functional.retry_runtime_output_projection_invalid",
                f"{path}[{index}]",
                "materialized runtime result cannot be projected completely",
                retryable=False,
                details={"return": return_name},
            )
        runtime_type = str(output.get("runtime_type") or "")
        if not runtime_type:
            raise FunctionalScopeRetryError(
                "functional.retry_runtime_output_projection_invalid",
                f"{path}[{index}].runtime_type",
                "materialized runtime result has no public runtime type",
                retryable=False,
            )
        projected[return_name] = {
            "runtime_type": runtime_type,
            "value": _project_value_fail_loud(
                output["value"],
                forbidden_values=forbidden_values,
                path=f"{path}[{index}].value",
            ),
        }
    return projected


def _project_value_fail_loud(
    value: Any,
    *,
    forbidden_values: frozenset[str],
    path: str,
) -> Any:
    raw = _json_safe_value(value)
    safe = _prompt_safe_value(value, forbidden_values=forbidden_values)
    if safe != raw or _contains_internal_projection_marker(safe):
        raise FunctionalScopeRetryError(
            "functional.retry_runtime_output_projection_invalid",
            path,
            "runtime result contains internal identity or requires lossy projection",
            retryable=False,
        )
    return safe


def _project_diagnostic(
    issue: Mapping[str, Any],
    *,
    forbidden_values: frozenset[str],
    default_stage: str = "validation",
) -> dict[str, Any]:
    stage = str(issue.get("stage") or default_stage)
    if stage not in {"validation", "runtime"}:
        stage = "runtime" if "runtime" in stage else "validation"
    payload: dict[str, Any] = {
        "stage": stage,
        "code": str(issue.get("code") or "functional.retry_validation_failed"),
        "message": str(issue.get("message") or "The previous Plan failed validation."),
    }
    suggestion = issue.get("suggestion") or issue.get("repair_action")
    if suggestion:
        payload["suggestion"] = str(suggestion)
    for key in ("expected", "observed", "details"):
        if key in issue and issue[key] not in (None, {}, []):
            payload[key] = _project_value_fail_loud(
                issue[key],
                forbidden_values=forbidden_values,
                path=f"$.diagnostic.{key}",
            )
    return payload


def _answer_output(
    answer_from: Mapping[str, str],
    *,
    execution_steps: Mapping[str, FunctionalGoalExecutionStep],
    forbidden_values: frozenset[str],
) -> Mapping[str, Any] | None:
    producer = execution_steps.get(str(answer_from.get("step_id") or ""))
    if producer is None or producer.status != "runtime_verified":
        return None
    outputs = _project_runtime_outputs(
        producer.actual_outputs,
        forbidden_values=forbidden_values,
        path=f"$.steps[{producer.step_id!r}].actual_outputs",
    )
    return outputs.get(str(answer_from.get("return") or ""))


def _required_answer_contracts(
    planning_context: ProblemPlanningContext | None,
) -> dict[str, Mapping[str, str]]:
    if planning_context is None:
        return {}
    return {
        item.answer_ref.ref: {
            "target_ref": str(
                item.goal_payload.get("target") or item.answer_ref.ref
            ),
            "answer_type": item.answer_ref.value_type or "Unknown",
        }
        for item in planning_context.goal_views
    }


def _first_issue_for(
    issues: Sequence[Mapping[str, Any]],
    key: str,
    value: str,
    *,
    forbidden_values: frozenset[str],
) -> Mapping[str, Any] | None:
    return next(
        (
            _project_diagnostic(item, forbidden_values=forbidden_values)
            for item in issues
            if str(item.get(key) or "") == value
        ),
        None,
    )


def _annotated_status(status: str) -> FunctionalAnnotatedExecutionStatus:
    if status == "runtime_verified":
        return "succeeded"
    if status in {"authority_invalid", "runtime_failed"}:
        return "failed"
    return "not_run"


def _contains_internal_projection_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_internal_projection_marker(key)
            or _contains_internal_projection_marker(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_internal_projection_marker(item) for item in value)
    return isinstance(value, str) and value == "<internal-identity-omitted>"


def _scope_parent_map(root: ScopedFunctionalScope) -> dict[str, str | None]:
    parents: dict[str, str | None] = {}

    def visit(scope: ScopedFunctionalScope, parent: str | None) -> None:
        parents[scope.scope_ref] = parent
        for child in scope.children:
            visit(child, scope.scope_ref)

    visit(root, None)
    return parents


def _scope_lca(
    scope_refs: Sequence[str],
    parents: Mapping[str, str | None],
) -> str:
    if not scope_refs:
        raise ValueError("scope LCA requires at least one Scope")

    def lineage(scope_ref: str) -> tuple[str, ...]:
        values: list[str] = []
        current: str | None = scope_ref
        while current is not None:
            values.append(current)
            current = parents.get(current)
        return tuple(reversed(values))

    lineages = [lineage(item) for item in scope_refs]
    common = lineages[0][0]
    for values in zip(*lineages):
        if len(set(values)) != 1:
            break
        common = values[0]
    return common


def _is_placement_issue(issue: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(issue.get(key) or "")
        for key in ("code", "category", "stage", "message")
    ).lower()
    return "placement" in text or "visibility" in text


def _step_reads_any_answer(
    step: ScopedFunctionalStep,
    answer_sources: set[tuple[str, str]],
) -> bool:
    return any(
        (getattr(ref, "step_id", None), getattr(ref, "return_name", None))
        in answer_sources
        for values in step.args.values()
        for ref in values
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


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            str(key): _freeze_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_thaw(item) for item in value]
    return value


def _json_path(parts: Sequence[object]) -> str:
    path = "$"
    for item in parts:
        path += f"[{item}]" if isinstance(item, int) else f".{item}"
    return path


__all__ = [
    "FUNCTIONAL_ANNOTATED_PLAN_CONTRACT",
    "FUNCTIONAL_SCOPE_REPAIR_CONTRACT",
    "FunctionalAnnotatedGoal",
    "FunctionalAnnotatedPlan",
    "FunctionalAnnotatedPlanProjector",
    "FunctionalAnnotatedScope",
    "FunctionalAnnotatedStep",
    "FunctionalAnnotatedStepExecution",
    "FunctionalScopeGoalReplacement",
    "FunctionalScopeRepair",
    "FunctionalScopeRepairApplication",
    "FunctionalScopeRepairCompiler",
    "FunctionalScopeReplacement",
    "FunctionalScopeRetryAuthority",
    "FunctionalScopeRetryAuthorityProjector",
    "FunctionalScopeRetryError",
    "functional_annotated_plan_schema",
    "functional_scope_repair_schema",
    "functional_scope_repair_schema_for_authority",
]
