"""Scope-native FunctionalPlan v2 authoring and authority lowering."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.contracts import FunctionalResultForm
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
    ProblemPlanningBindingError,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    PLANNER_PROBLEM_VIEW_CONTRACT,
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCall,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalScope,
    FunctionalTypedInputSourcePin,
    PublishedGoalCallResultRef,
)
from shuxueshuo_server.solver.runtime.planner_public_types import (
    planner_input_domain_type,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.return_object_authority import (
    ReturnObjectAuthorityResolver,
    ReturnRoleAuthorityResolver,
    identity_constraint_return_targets,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef
from shuxueshuo_server.solver.state_semantics import (
    runtime_type_for_object_semantic_kind,
)


SCOPED_FUNCTIONAL_PLAN_CONTRACT = "functional_plan/v2"
SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH = 4
_RESULT_FORMS = (
    "open_expression",
    "closed_value",
    "open_state",
    "closed_state",
)
_STEP_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"


def scoped_functional_plan_schema() -> dict[str, Any]:
    """Return the strict four-level FunctionalPlan v2 authoring schema."""

    nonempty = {"type": "string", "minLength": 1}
    step_result = {
        "type": "object",
        "description": (
            "Read one named return from an earlier visible step. Use this for "
            "anonymous results only. A named Math Entity must use its SourceRef; "
            "the compiler obtains the exact input required by the capability."
        ),
        "required": ["step_id", "return"],
        "properties": {
            "step_id": {"type": "string", "pattern": _STEP_ID_PATTERN},
            "return": {
                **nonempty,
                "description": (
                    "Copy the producer capability's public return name exactly; "
                    "its type must be accepted by the consuming argument."
                ),
            },
        },
        "additionalProperties": False,
    }
    source_ref = {
        "type": "string",
        "minLength": 1,
        "description": (
            "Copy a scope-local visible Entity or Fact ref from Planner Problem "
            "View exactly, without adding a scope prefix. This is the only wire "
            "form for a named Entity. The compiler selects its identity or latest "
            "visible state and establishes producer dependencies; a Fact remains "
            "the verified problem snapshot."
        ),
    }
    functional_ref = {
        "description": (
            "Use a SourceRef string for every named Entity or visible Fact. Use "
            "StepResultRef only for a return without a named Math Entity identity."
        ),
        "oneOf": [
            {"$ref": "#/$defs/source_ref"},
            {"$ref": "#/$defs/step_result_ref"},
        ],
    }
    step = {
        "type": "object",
        "required": ["step_id", "capability_id", "args"],
        "properties": {
            "step_id": {"type": "string", "pattern": _STEP_ID_PATTERN},
            "capability_id": nonempty,
            "args": {
                "type": "object",
                "description": (
                    "Capability inputs keyed by public catalog arg names; values "
                    "are exact visible SourceRefs or earlier StepResultRefs. "
                    "Never invent a string name for an anonymous step result."
                ),
                "additionalProperties": {
                    "oneOf": [
                        {"$ref": "#/$defs/functional_ref"},
                        {
                            "type": "array",
                            "minItems": 1,
                            "items": {"$ref": "#/$defs/functional_ref"},
                        },
                    ]
                },
            },
            "output_targets": {
                "type": "object",
                "minProperties": 1,
                "description": (
                    "Bind non-answer returns to existing visible Problem objects; "
                    "keys are public capability return roles."
                ),
                "additionalProperties": nonempty,
            },
            "return_expectations": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"enum": list(_RESULT_FORMS)},
            },
            "intent": nonempty,
        },
        "additionalProperties": False,
    }
    answer_from = {
        "type": "object",
        "description": (
            "The single step return that produces this Goal answer. Its public "
            "return name must be copied exactly and its type must match the "
            "Goal answer_type."
        ),
        "required": ["step_id", "return"],
        "properties": {
            "step_id": {"type": "string", "pattern": _STEP_ID_PATTERN},
            "return": {
                **nonempty,
                "description": (
                    "Copy the producer capability's public return name exactly; "
                    "its type must match this Goal's answer_type."
                ),
            },
        },
        "additionalProperties": False,
    }
    goal = {
        "type": "object",
        "required": ["goal_ref", "answer_from"],
        "properties": {
            "goal_ref": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Copy the owning Goal's goal_ref from Planner Problem "
                    "View exactly. Do not use its scope id, target, or a new "
                    "name. A scope may own multiple Goals."
                ),
            },
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/step"},
            },
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
    scope_properties = {
        "scope_ref": nonempty,
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/step"},
        },
        "goals": {
            "type": "array",
            "minItems": 1,
            "items": {"$ref": "#/$defs/goal"},
        },
    }
    scope_definitions: dict[str, Any] = {}
    for level in range(SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH):
        properties = dict(scope_properties)
        if level + 1 < SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH:
            properties["children"] = {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": f"#/$defs/scope_level_{level + 1}"},
            }
        scope_definitions[f"scope_level_{level}"] = {
            "type": "object",
            "required": ["scope_ref"],
            "properties": properties,
            "additionalProperties": False,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "functional-plan-v2.schema.json",
        "title": "Scope-native FunctionalPlan v2",
        "type": "object",
        "required": ["format", "root_scope"],
        "properties": {
            "format": {"const": SCOPED_FUNCTIONAL_PLAN_CONTRACT},
            "root_scope": {"$ref": "#/$defs/scope_level_0"},
        },
        "$defs": {
            "source_ref": source_ref,
            "step_result_ref": step_result,
            "functional_ref": functional_ref,
            "step": step,
            "answer_from": answer_from,
            "goal": goal,
            **scope_definitions,
        },
        "additionalProperties": False,
    }


class ScopedFunctionalPlanError(ValueError):
    """A retryable v2 authoring error or non-retryable authority drift."""

    def __init__(
        self,
        code: str,
        path: str,
        message: str,
        *,
        retryable: bool = True,
        issues: tuple["ScopedFunctionalPlanIssue", ...] = (),
        normalizations: tuple["ScopedFunctionalPlanNormalization", ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        self.retryable = retryable
        self.issues = issues or (
            ScopedFunctionalPlanIssue(code, path, message, details or {}),
        )
        self.normalizations = tuple(normalizations)
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class ScopedFunctionalPlanIssue:
    code: str
    path: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "details",
            MappingProxyType(dict(sorted(self.details.items()))),
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass(frozen=True)
class ScopedFunctionalPlanValidationReport:
    issues: tuple[ScopedFunctionalPlanIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [item.to_payload() for item in self.issues],
        }


@dataclass(frozen=True)
class ScopedFunctionalPlanAuthorityReport:
    issues: tuple[ScopedFunctionalPlanIssue, ...] = ()
    normalizations: tuple[ScopedFunctionalPlanNormalization, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def first_issue(self) -> ScopedFunctionalPlanIssue | None:
        return self.issues[0] if self.issues else None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "first_issue": (
                self.first_issue.to_payload()
                if self.first_issue is not None
                else None
            ),
            "issues": [item.to_payload() for item in self.issues],
            "normalizations": [
                item.to_payload() for item in self.normalizations
            ],
        }


@dataclass(frozen=True)
class ScopedFunctionalStructureReport:
    """Prompt-safe comparison of authored and expected Scope/Goal trees."""

    expected_scope_parents: tuple[tuple[str, str | None], ...]
    actual_scope_parents: tuple[tuple[str, str | None], ...]
    expected_goal_owners: tuple[tuple[str, str], ...]
    actual_goal_owners: tuple[tuple[str, str], ...]
    missing_scope_refs: tuple[str, ...] = ()
    unexpected_scope_refs: tuple[str, ...] = ()
    duplicate_scope_refs: tuple[str, ...] = ()
    moved_scope_refs: tuple[str, ...] = ()
    missing_goal_refs: tuple[str, ...] = ()
    unexpected_goal_refs: tuple[str, ...] = ()
    duplicate_goal_refs: tuple[str, ...] = ()
    moved_goal_refs: tuple[str, ...] = ()
    issues: tuple[ScopedFunctionalPlanIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def first_issue(self) -> ScopedFunctionalPlanIssue | None:
        return self.issues[0] if self.issues else None

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "expected_scope_parents": [
                {"scope_ref": scope_ref, "parent_scope_ref": parent_scope_ref}
                for scope_ref, parent_scope_ref in self.expected_scope_parents
            ],
            "actual_scope_parents": [
                {"scope_ref": scope_ref, "parent_scope_ref": parent_scope_ref}
                for scope_ref, parent_scope_ref in self.actual_scope_parents
            ],
            "expected_goal_owners": [
                {"goal_ref": goal_ref, "owner_scope_ref": owner_scope_ref}
                for goal_ref, owner_scope_ref in self.expected_goal_owners
            ],
            "actual_goal_owners": [
                {"goal_ref": goal_ref, "owner_scope_ref": owner_scope_ref}
                for goal_ref, owner_scope_ref in self.actual_goal_owners
            ],
            "missing_scope_refs": list(self.missing_scope_refs),
            "unexpected_scope_refs": list(self.unexpected_scope_refs),
            "duplicate_scope_refs": list(self.duplicate_scope_refs),
            "moved_scope_refs": list(self.moved_scope_refs),
            "missing_goal_refs": list(self.missing_goal_refs),
            "unexpected_goal_refs": list(self.unexpected_goal_refs),
            "duplicate_goal_refs": list(self.duplicate_goal_refs),
            "moved_goal_refs": list(self.moved_goal_refs),
            "first_issue": (
                self.first_issue.to_payload()
                if self.first_issue is not None
                else None
            ),
            "issues": [item.to_payload() for item in self.issues],
        }


@dataclass(frozen=True)
class ScopedStepResultRef:
    step_id: str
    return_name: str

    def to_payload(self) -> dict[str, str]:
        return {"step_id": self.step_id, "return": self.return_name}


@dataclass(frozen=True)
class ScopedPublishedGoalResultRef(ScopedStepResultRef):
    """A trusted retry-only reference to one solved Goal's final answer."""

    published_goal_ref: str
    semantic_ref: str | None = None

    def to_payload(self) -> str | dict[str, str]:
        if self.semantic_ref is not None:
            return self.semantic_ref
        return super().to_payload()

    def authority_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "published_goal_ref": self.published_goal_ref,
            "producer": super().to_payload(),
        }
        if self.semantic_ref is not None:
            payload["semantic_ref"] = self.semantic_ref
        return payload


@dataclass(frozen=True)
class ScopedPublishedGoalBinding:
    consumer_step_id: str
    arg_name: str
    item_index: int
    published_goal_ref: str
    producer_step_id: str
    return_name: str
    semantic_ref: str | None = None


ScopedFunctionalRef = str | ScopedStepResultRef


def _scoped_ref_authority_payload(value: ScopedFunctionalRef) -> Any:
    if isinstance(value, ScopedPublishedGoalResultRef):
        return value.authority_payload()
    if isinstance(value, ScopedStepResultRef):
        return value.to_payload()
    return value


@dataclass(frozen=True)
class ScopedFunctionalStep:
    step_id: str
    capability_id: str
    args: Mapping[str, tuple[ScopedFunctionalRef, ...]]
    output_targets: Mapping[str, str]
    return_expectations: Mapping[str, FunctionalResultForm]
    intent: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "args",
            MappingProxyType(
                {
                    key: tuple(value)
                    for key, value in sorted(self.args.items())
                }
            ),
        )
        object.__setattr__(
            self,
            "output_targets",
            MappingProxyType(dict(sorted(self.output_targets.items()))),
        )
        object.__setattr__(
            self,
            "return_expectations",
            MappingProxyType(dict(sorted(self.return_expectations.items()))),
        )

    def to_payload(self) -> dict[str, Any]:
        args: dict[str, Any] = {}
        for name, values in self.args.items():
            encoded = [
                value.to_payload()
                if isinstance(value, ScopedStepResultRef)
                else value
                for value in values
            ]
            args[name] = encoded[0] if len(encoded) == 1 else encoded
        payload: dict[str, Any] = {
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "args": args,
        }
        if self.output_targets:
            payload["output_targets"] = dict(self.output_targets)
        if self.return_expectations:
            payload["return_expectations"] = dict(
                self.return_expectations
            )
        if self.intent:
            payload["intent"] = self.intent
        return payload


@dataclass(frozen=True)
class ScopedFunctionalAnswerSource:
    step_id: str
    return_name: str

    def to_payload(self) -> dict[str, str]:
        return {"step_id": self.step_id, "return": self.return_name}


@dataclass(frozen=True)
class ScopedFunctionalGoalPlan:
    goal_ref: str
    steps: tuple[ScopedFunctionalStep, ...]
    answer_from: ScopedFunctionalAnswerSource

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "goal_ref": self.goal_ref,
            "answer_from": self.answer_from.to_payload(),
        }
        if self.steps:
            payload["steps"] = [item.to_payload() for item in self.steps]
        return payload


@dataclass(frozen=True)
class ScopedFunctionalScope:
    scope_ref: str
    steps: tuple[ScopedFunctionalStep, ...] = ()
    goals: tuple[ScopedFunctionalGoalPlan, ...] = ()
    children: tuple["ScopedFunctionalScope", ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": self.scope_ref}
        if self.steps:
            payload["steps"] = [item.to_payload() for item in self.steps]
        if self.goals:
            payload["goals"] = [item.to_payload() for item in self.goals]
        if self.children:
            payload["children"] = [
                item.to_payload() for item in self.children
            ]
        return payload


@dataclass(frozen=True)
class ScopedFunctionalPlan:
    root_scope: ScopedFunctionalScope
    format: str = SCOPED_FUNCTIONAL_PLAN_CONTRACT

    @property
    def steps(self) -> tuple[ScopedFunctionalStep, ...]:
        return tuple(
            step
            for scope in _iter_scopes(self.root_scope)
            for step in (
                *scope.steps,
                *(step for goal in scope.goals for step in goal.steps),
            )
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "root_scope": self.root_scope.to_payload(),
        }


def scoped_functional_plan_authority_payload(
    plan: ScopedFunctionalPlan,
) -> dict[str, Any]:
    """Serialize internal publication authority without changing the v2 wire."""

    def step_payload(step: ScopedFunctionalStep) -> dict[str, Any]:
        payload = step.to_payload()
        args: dict[str, Any] = {}
        for name, values in step.args.items():
            encoded = [_scoped_ref_authority_payload(value) for value in values]
            args[name] = encoded[0] if len(encoded) == 1 else encoded
        payload["args"] = args
        return payload

    def scope_payload(scope: ScopedFunctionalScope) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": scope.scope_ref}
        if scope.steps:
            payload["steps"] = [step_payload(item) for item in scope.steps]
        if scope.goals:
            payload["goals"] = [
                {
                    "goal_ref": goal.goal_ref,
                    **(
                        {"steps": [step_payload(item) for item in goal.steps]}
                        if goal.steps
                        else {}
                    ),
                    "answer_from": goal.answer_from.to_payload(),
                }
                for goal in scope.goals
            ]
        if scope.children:
            payload["children"] = [scope_payload(item) for item in scope.children]
        return payload

    return {"format": plan.format, "root_scope": scope_payload(plan.root_scope)}


def scoped_published_goal_bindings(
    plan: ScopedFunctionalPlan,
) -> tuple[ScopedPublishedGoalBinding, ...]:
    """Return the trusted publication sidecar carried by an in-memory Plan."""

    return tuple(
        ScopedPublishedGoalBinding(
            consumer_step_id=step.step_id,
            arg_name=arg_name,
            item_index=index,
            published_goal_ref=value.published_goal_ref,
            producer_step_id=value.step_id,
            return_name=value.return_name,
            semantic_ref=value.semantic_ref,
        )
        for step in plan.steps
        for arg_name, values in step.args.items()
        for index, value in enumerate(values)
        if isinstance(value, ScopedPublishedGoalResultRef)
    )


def apply_scoped_published_goal_bindings(
    plan: ScopedFunctionalPlan,
    bindings: Sequence[ScopedPublishedGoalBinding],
) -> ScopedFunctionalPlan:
    """Reattach validated retry-only publication markers to a parsed Plan."""

    by_step: dict[str, list[ScopedPublishedGoalBinding]] = {}
    identities: set[tuple[str, str, int]] = set()
    for binding in bindings:
        identity = (
            binding.consumer_step_id,
            binding.arg_name,
            binding.item_index,
        )
        if identity in identities:
            raise ValueError(f"duplicate published Goal binding: {identity!r}")
        identities.add(identity)
        by_step.setdefault(binding.consumer_step_id, []).append(binding)

    seen: set[tuple[str, str, int]] = set()

    def rebuild_step(step: ScopedFunctionalStep) -> ScopedFunctionalStep:
        step_bindings = by_step.get(step.step_id, ())
        if not step_bindings:
            return step
        args = {name: list(values) for name, values in step.args.items()}
        for binding in step_bindings:
            values = args.get(binding.arg_name)
            if values is None or binding.item_index >= len(values):
                raise ValueError(
                    "published Goal binding does not resolve to a Plan argument"
                )
            current = values[binding.item_index]
            exact_result_matches = (
                isinstance(current, ScopedStepResultRef)
                and (current.step_id, current.return_name)
                == (binding.producer_step_id, binding.return_name)
            )
            semantic_ref_matches = (
                binding.semantic_ref is not None
                and current == binding.semantic_ref
            )
            if not exact_result_matches and not semantic_ref_matches:
                raise ValueError(
                    "published Goal binding disagrees with the validated Plan edge"
                )
            values[binding.item_index] = ScopedPublishedGoalResultRef(
                step_id=binding.producer_step_id,
                return_name=binding.return_name,
                published_goal_ref=binding.published_goal_ref,
                semantic_ref=binding.semantic_ref,
            )
            seen.add(
                (binding.consumer_step_id, binding.arg_name, binding.item_index)
            )
        return replace(
            step,
            args={name: tuple(values) for name, values in args.items()},
        )

    def rebuild_scope(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            steps=tuple(rebuild_step(item) for item in scope.steps),
            goals=tuple(
                replace(
                    goal,
                    steps=tuple(rebuild_step(item) for item in goal.steps),
                )
                for goal in scope.goals
            ),
            children=tuple(rebuild_scope(item) for item in scope.children),
        )

    result = replace(plan, root_scope=rebuild_scope(plan.root_scope))
    if seen != identities:
        raise ValueError("published Goal binding references an unknown consumer step")
    return result


class ScopedFunctionalPlanValidator:
    """Strict JSON Schema parser for FunctionalPlan v2."""

    def validate_json_with_report(
        self,
        raw: str,
    ) -> tuple[
        ScopedFunctionalPlan | None,
        ScopedFunctionalPlanValidationReport,
    ]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            issue = ScopedFunctionalPlanIssue(
                "functional.v2_invalid_json",
                "$",
                str(exc),
            )
            return None, ScopedFunctionalPlanValidationReport((issue,))
        return self.validate_payload_with_report(payload)

    def validate_payload_with_report(
        self,
        payload: object,
    ) -> tuple[
        ScopedFunctionalPlan | None,
        ScopedFunctionalPlanValidationReport,
    ]:
        payload = normalize_scoped_functional_plan_wire(payload)
        validator = Draft202012Validator(scoped_functional_plan_schema())
        errors = sorted(
            validator.iter_errors(payload),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            issues = tuple(
                ScopedFunctionalPlanIssue(
                    "functional.v2_schema_invalid",
                    _json_path(error.absolute_path),
                    error.message,
                )
                for error in errors
            )
            return None, ScopedFunctionalPlanValidationReport(issues)
        assert isinstance(payload, dict)
        plan = ScopedFunctionalPlan(
            root_scope=_parse_scope(payload["root_scope"]),
        )
        return plan, ScopedFunctionalPlanValidationReport()


def normalize_scoped_functional_plan_wire(payload: object) -> object:
    """Remove optional empty v2 collections without changing plan semantics."""

    if not isinstance(payload, dict) or payload.get("format") != (
        SCOPED_FUNCTIONAL_PLAN_CONTRACT
    ):
        return payload

    def normalize_goal(value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if key == "steps" and item == []:
                continue
            normalized[key] = (
                [normalize_step(step) for step in item]
                if key == "steps" and isinstance(item, list)
                else item
            )
        return normalized

    def normalize_step(value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        args = normalized.get("args")
        if isinstance(args, dict):
            normalized["args"] = {
                key: item for key, item in args.items() if item != []
            }
        for key in ("output_targets", "return_expectations"):
            if normalized.get(key) == {}:
                normalized.pop(key)
        return normalized

    def normalize_scope(value: object) -> object:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if key in {"steps", "goals", "children"} and item == []:
                continue
            if key == "steps" and isinstance(item, list):
                normalized[key] = [normalize_step(step) for step in item]
            elif key == "goals" and isinstance(item, list):
                normalized[key] = [normalize_goal(goal) for goal in item]
            elif key == "children" and isinstance(item, list):
                normalized[key] = [normalize_scope(child) for child in item]
            else:
                normalized[key] = item
        return normalized

    return {
        key: (
            normalize_scope(value)
            if key == "root_scope"
            else value
        )
        for key, value in payload.items()
    }


@dataclass(frozen=True)
class FunctionalStepScopeAuthority:
    step_id: str
    canonical_call_id: str
    plan_scope_id: str
    authored_goal_ref: str | None
    authored_goal_unit_id: str | None
    consumer_goal_unit_ids: tuple[str, ...]
    semantic_owner_scope_id: str
    execution_scope_id: str | None
    binding_signature: str

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalStepScopeAuthority":
        expected = {
            "step_id",
            "canonical_call_id",
            "plan_scope_id",
            "authored_goal_ref",
            "authored_goal_unit_id",
            "consumer_goal_unit_ids",
            "semantic_owner_scope_id",
            "execution_scope_id",
            "binding_signature",
        }
        if set(payload) != expected:
            raise ValueError(
                "FunctionalStepScopeAuthority payload fields do not match "
                "the current authority contract"
            )
        optional_strings = (
            "authored_goal_ref",
            "authored_goal_unit_id",
            "execution_scope_id",
        )
        required_strings = (
            "step_id",
            "canonical_call_id",
            "plan_scope_id",
            "semantic_owner_scope_id",
            "binding_signature",
        )
        if any(
            not isinstance(payload[key], str) or not payload[key]
            for key in required_strings
        ):
            raise ValueError(
                "FunctionalStepScopeAuthority required identities must be "
                "non-empty strings"
            )
        if any(
            payload[key] is not None
            and (not isinstance(payload[key], str) or not payload[key])
            for key in optional_strings
        ):
            raise ValueError(
                "FunctionalStepScopeAuthority optional identities must be "
                "null or non-empty strings"
            )
        goal_ids = payload["consumer_goal_unit_ids"]
        if not isinstance(goal_ids, list) or any(
            not isinstance(item, str) or not item for item in goal_ids
        ):
            raise ValueError(
                "FunctionalStepScopeAuthority consumer Goal ids must be an array "
                "of non-empty strings"
            )
        return cls(
            step_id=payload["step_id"],
            canonical_call_id=payload["canonical_call_id"],
            plan_scope_id=payload["plan_scope_id"],
            authored_goal_ref=payload["authored_goal_ref"],
            authored_goal_unit_id=payload["authored_goal_unit_id"],
            consumer_goal_unit_ids=tuple(goal_ids),
            semantic_owner_scope_id=payload["semantic_owner_scope_id"],
            execution_scope_id=payload["execution_scope_id"],
            binding_signature=payload["binding_signature"],
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "canonical_call_id": self.canonical_call_id,
            "plan_scope_id": self.plan_scope_id,
            "authored_goal_ref": self.authored_goal_ref,
            "authored_goal_unit_id": self.authored_goal_unit_id,
            "consumer_goal_unit_ids": list(self.consumer_goal_unit_ids),
            "semantic_owner_scope_id": self.semantic_owner_scope_id,
            "execution_scope_id": self.execution_scope_id,
            "binding_signature": self.binding_signature,
        }


@dataclass(frozen=True)
class ScopedFunctionalPlanNormalization:
    action: str
    reason: str
    step_id: str | None = None
    capability_id: str | None = None
    scope_ref: str | None = None
    from_goal_ref: str | None = None
    to_goal_ref: str | None = None
    from_arg: str | None = None
    to_arg: str | None = None
    return_name: str | None = None
    target_ref: str | None = None
    arg_name: str | None = None
    from_ref: str | None = None
    to_ref: str | None = None
    goal_ref: str | None = None
    from_form: str | None = None
    fact_type: str | None = None

    def to_payload(self) -> dict[str, str]:
        payload = {
            "action": self.action,
            "reason": self.reason,
        }
        if self.step_id is not None:
            payload["step_id"] = self.step_id
        if self.capability_id is not None:
            payload["capability_id"] = self.capability_id
        if self.scope_ref is not None:
            payload["scope_ref"] = self.scope_ref
        if self.from_goal_ref is not None:
            payload["from_goal_ref"] = self.from_goal_ref
        if self.to_goal_ref is not None:
            payload["to_goal_ref"] = self.to_goal_ref
        if self.from_arg is not None:
            payload["from_arg"] = self.from_arg
        if self.to_arg is not None:
            payload["to_arg"] = self.to_arg
        if self.return_name is not None:
            payload["return_name"] = self.return_name
        if self.target_ref is not None:
            payload["target_ref"] = self.target_ref
        if self.arg_name is not None:
            payload["arg_name"] = self.arg_name
        if self.from_ref is not None:
            payload["from_ref"] = self.from_ref
        if self.to_ref is not None:
            payload["to_ref"] = self.to_ref
        if self.goal_ref is not None:
            payload["goal_ref"] = self.goal_ref
        if self.from_form is not None:
            payload["from_form"] = self.from_form
        if self.fact_type is not None:
            payload["fact_type"] = self.fact_type
        return payload


@dataclass(frozen=True)
class ScopedFunctionalPlanAuthority:
    scoped_plan: ScopedFunctionalPlan
    lowered_plan: FunctionalPlan
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    plan_id: str
    plan_semantic_hash: str
    step_authorities: Mapping[str, FunctionalStepScopeAuthority]
    normalizations: tuple[ScopedFunctionalPlanNormalization, ...] = ()
    pruned_step_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "step_authorities",
            MappingProxyType(dict(sorted(self.step_authorities.items()))),
        )
        object.__setattr__(self, "normalizations", tuple(self.normalizations))
        object.__setattr__(
            self,
            "pruned_step_ids",
            tuple(sorted(set(self.pruned_step_ids))),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "plan_id": self.plan_id,
            "plan_semantic_hash": self.plan_semantic_hash,
            "plan": self.scoped_plan.to_payload(),
            "step_authorities": {
                key: value.to_payload()
                for key, value in self.step_authorities.items()
            },
            "normalizations": [
                item.to_payload() for item in self.normalizations
            ],
            "effective_execution_plan": self.lowered_plan.to_payload(),
            "pruned_step_ids": list(self.pruned_step_ids),
        }

    def finalize_reconciliation(
        self,
        reconciliation: FunctionalPlanReconciliationResult,
    ) -> tuple[
        "ScopedFunctionalPlanAuthority | None",
        ScopedFunctionalPlanAuthorityReport,
    ]:
        issues: list[ScopedFunctionalPlanIssue] = []
        if not reconciliation.ok:
            issues.extend(
                ScopedFunctionalPlanIssue(
                    issue.code,
                    (
                        f"$.steps[{issue.call_id!r}]"
                        if issue.call_id is not None
                        else "$.reconciliation"
                    ),
                    issue.message,
                )
                for issue in reconciliation.issues
            )
        placements = {
            item.canonical_call_id: item
            for item in reconciliation.call_placements
        }
        aliases = reconciliation.call_aliases
        if aliases:
            issues.append(
                ScopedFunctionalPlanIssue(
                    "functional.scoped_step_identity_drift",
                    "$.reconciliation.call_aliases",
                    "FunctionalPlan v2 forbids call aliases; step_id is canonical",
                )
            )
        problem_sidecar = reconciliation.functional_problem_binding_context
        if problem_sidecar is None:
            issues.append(
                ScopedFunctionalPlanIssue(
                    "functional.step_scope_authority_drift",
                    "$.reconciliation.functional_problem_binding_context",
                    "F5-C Goal authority is required to finalize v2 steps",
                )
            )
        pruned_step_ids = frozenset(
            str(item)
            for item in (reconciliation.elaboration or {}).get(
                "scoped_pruned_step_ids",
                (),
            )
        ) | frozenset(self.pruned_step_ids)
        scoped_steps = {
            step.step_id: step for step in self.scoped_plan.steps
        }
        finalized: dict[str, FunctionalStepScopeAuthority] = {}
        automatic_scope_promotions: dict[str, str] = {}
        for step_id, authority in self.step_authorities.items():
            if step_id in pruned_step_ids:
                finalized[step_id] = authority
                continue
            canonical_id = step_id
            if authority.canonical_call_id != canonical_id:
                issues.append(
                    ScopedFunctionalPlanIssue(
                        "functional.scoped_step_identity_drift",
                        f"$.steps[{step_id!r}]",
                        "step authority canonical id differs from its v2 step id",
                    )
                )
                continue
            placement = placements.get(canonical_id)
            if placement is None:
                issues.append(
                    ScopedFunctionalPlanIssue(
                        "functional.step_scope_authority_drift",
                        f"$.steps[{step_id!r}]",
                        "reconciliation omitted the canonical step placement",
                    )
                )
                continue
            actual_goals = tuple(
                sorted(
                    (
                        problem_sidecar.call_goal_bindings.get(
                            canonical_id,
                            (),
                        )
                        if problem_sidecar is not None
                        else ()
                    )
                )
            )
            if not actual_goals:
                issues.append(
                    ScopedFunctionalPlanIssue(
                        "functional.step_goal_mismatch",
                        f"$.steps[{step_id!r}]",
                        "typed Goal closure is empty for an executable step",
                    )
                )
                continue
            if authority.authored_goal_unit_id is not None and actual_goals != (
                authority.authored_goal_unit_id,
            ):
                if authority.authored_goal_unit_id in actual_goals:
                    # The LLM placed a genuinely shared producer in one Goal.
                    # B2 has already proven the execution LCA from the complete
                    # typed consumer DAG, so ownership is a mechanical tree
                    # normalization rather than a semantic repair request.
                    automatic_scope_promotions[step_id] = (
                        placement.execution_scope_id
                    )
                    finalized[step_id] = replace(
                        authority,
                        plan_scope_id=placement.execution_scope_id,
                        authored_goal_ref=None,
                        authored_goal_unit_id=None,
                        consumer_goal_unit_ids=actual_goals,
                        semantic_owner_scope_id=(
                            placement.execution_scope_id
                        ),
                        execution_scope_id=placement.execution_scope_id,
                        binding_signature=stable_hash(
                            {
                                "authoring_binding_signature": (
                                    authority.binding_signature
                                ),
                                "canonical_call_id": canonical_id,
                                "plan_scope_id": (
                                    placement.execution_scope_id
                                ),
                                "semantic_owner_scope_id": (
                                    placement.execution_scope_id
                                ),
                                "consumer_goal_unit_ids": list(
                                    actual_goals
                                ),
                                "execution_scope_id": (
                                    placement.execution_scope_id
                                ),
                                "normalization": (
                                    "promote_shared_goal_step_to_scope"
                                ),
                            }
                        ),
                    )
                    continue
                issues.append(
                    ScopedFunctionalPlanIssue(
                        "functional.step_goal_mismatch",
                        f"$.steps[{step_id!r}]",
                        (
                            "Goal-owned step does not serve its owning Goal: "
                            f"expected={authority.authored_goal_unit_id!r}, "
                            f"actual={actual_goals!r}"
                        ),
                        {
                            "expected_goal_unit_id": (
                                authority.authored_goal_unit_id
                            ),
                            "actual_goal_unit_ids": list(actual_goals),
                            "execution_scope_id": (
                                placement.execution_scope_id
                            ),
                        },
                    )
                )
                continue
            if authority.execution_scope_id is not None:
                if (
                    authority.execution_scope_id
                    != placement.execution_scope_id
                    or authority.consumer_goal_unit_ids != actual_goals
                ):
                    issues.append(
                        ScopedFunctionalPlanIssue(
                            "functional.step_scope_authority_drift",
                            f"$.steps[{step_id!r}]",
                            "re-finalization changed an established execution authority",
                        )
                    )
                    continue
                finalized[step_id] = authority
                continue
            finalized[step_id] = replace(
                authority,
                canonical_call_id=canonical_id,
                consumer_goal_unit_ids=actual_goals,
                execution_scope_id=placement.execution_scope_id,
                binding_signature=stable_hash(
                    {
                        "authoring_binding_signature": (
                            authority.binding_signature
                        ),
                        "canonical_call_id": canonical_id,
                        "plan_scope_id": authority.plan_scope_id,
                        "semantic_owner_scope_id": (
                            authority.semantic_owner_scope_id
                        ),
                        "consumer_goal_unit_ids": list(actual_goals),
                        "execution_scope_id": placement.execution_scope_id,
                    }
                ),
            )
        if issues:
            deduplicated = {
                (item.code, item.path, item.message): item for item in issues
            }
            return None, ScopedFunctionalPlanAuthorityReport(
                issues=tuple(
                    deduplicated[key] for key in sorted(deduplicated)
                ),
                normalizations=self.normalizations,
            )
        pruning_records = tuple(
            ScopedFunctionalPlanNormalization(
                action="drop_dead_pure_goal_unreachable_branch",
                reason="typed_liveness_no_required_goal_path",
                step_id=step_id,
                capability_id=(
                    scoped_steps[step_id].capability_id
                    if step_id in scoped_steps
                    else None
                ),
            )
            for step_id in sorted(pruned_step_ids)
            if step_id not in self.pruned_step_ids
        )
        promotion_records = tuple(
            ScopedFunctionalPlanNormalization(
                action="promote_shared_goal_step_to_scope",
                reason="typed_consumer_goal_lca",
                step_id=step_id,
                capability_id=(
                    scoped_steps[step_id].capability_id
                    if step_id in scoped_steps
                    else None
                ),
                scope_ref=scope_ref,
                from_goal_ref=self.step_authorities[step_id].authored_goal_ref,
            )
            for step_id, scope_ref in sorted(
                automatic_scope_promotions.items()
            )
        )
        normalized_scoped_plan = _promote_goal_steps_to_scopes(
            self.scoped_plan,
            automatic_scope_promotions,
        )
        normalizations = (
            *self.normalizations,
            *promotion_records,
            *pruning_records,
        )
        finalized_authority = replace(
            self,
            scoped_plan=normalized_scoped_plan,
            lowered_plan=reconciliation.effective_plan,
            step_authorities=finalized,
            plan_id=(
                stable_hash(
                    scoped_functional_plan_authority_payload(
                        normalized_scoped_plan
                    )
                )
                if automatic_scope_promotions
                else self.plan_id
            ),
            plan_semantic_hash=(
                stable_hash(_semantic_plan_payload(normalized_scoped_plan))
                if automatic_scope_promotions
                else self.plan_semantic_hash
            ),
            normalizations=normalizations,
            pruned_step_ids=tuple(
                sorted((*self.pruned_step_ids, *pruned_step_ids))
            ),
        )
        return finalized_authority, ScopedFunctionalPlanAuthorityReport(
            normalizations=finalized_authority.normalizations,
        )


def _promote_goal_steps_to_scopes(
    plan: ScopedFunctionalPlan,
    promotions: Mapping[str, str],
) -> ScopedFunctionalPlan:
    """Move typed shared producers from Goal blocks to their LCA scopes."""

    if not promotions:
        return plan
    known_scope_refs = {
        scope.scope_ref for scope in _iter_scopes(plan.root_scope)
    }
    unknown = sorted(set(promotions.values()) - known_scope_refs)
    if unknown:
        raise ValueError(
            "planner_configuration_error: "
            "functional.step_scope_authority_drift: "
            f"promotion targets unknown scopes {unknown}"
        )
    steps_by_id = {step.step_id: step for step in plan.steps}
    missing = sorted(set(promotions) - set(steps_by_id))
    if missing:
        raise ValueError(
            "planner_configuration_error: "
            "functional.step_scope_authority_drift: "
            f"promotion references unknown steps {missing}"
        )
    promoted_ids = frozenset(promotions)
    by_target: dict[str, list[ScopedFunctionalStep]] = {}
    for step in plan.steps:
        target = promotions.get(step.step_id)
        if target is not None:
            by_target.setdefault(target, []).append(step)

    def rebuild(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            steps=(
                *(
                    step
                    for step in scope.steps
                    if step.step_id not in promoted_ids
                ),
                *by_target.get(scope.scope_ref, ()),
            ),
            goals=tuple(
                replace(
                    goal,
                    steps=tuple(
                        step
                        for step in goal.steps
                        if step.step_id not in promoted_ids
                    ),
                )
                for goal in scope.goals
            ),
            children=tuple(rebuild(child) for child in scope.children),
        )

    return replace(plan, root_scope=rebuild(plan.root_scope))


@dataclass(frozen=True)
class _StepLocation:
    step: ScopedFunctionalStep
    scope_id: str
    goal_ref: str | None
    order: int


class ScopedFunctionalPlanAuthorityAdapter:
    """Validate v2 authoring authority and lower it to the v1 runtime graph."""

    def analyze(
        self,
        plan: ScopedFunctionalPlan,
        *,
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> tuple[
        ScopedFunctionalPlanAuthority | None,
        ScopedFunctionalPlanAuthorityReport,
    ]:
        _, goal_normalizations = normalize_unique_scoped_goal_refs(
            plan,
            planning_context,
        )
        try:
            authority = self.lower(
                plan,
                planning_context=planning_context,
                binding_catalog=binding_catalog,
                capability_catalog=capability_catalog,
            )
        except ScopedFunctionalPlanError as exc:
            return None, ScopedFunctionalPlanAuthorityReport(
                issues=exc.issues,
                normalizations=(exc.normalizations or goal_normalizations),
            )
        return authority, ScopedFunctionalPlanAuthorityReport(
            normalizations=authority.normalizations,
        )

    def lower(
        self,
        plan: ScopedFunctionalPlan,
        *,
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> ScopedFunctionalPlanAuthority:
        canonical_plan, normalizations = self.canonicalize(
            plan,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
        )
        return self._lower_canonical(
            canonical_plan,
            normalizations=normalizations,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
        )

    def canonicalize(
        self,
        plan: ScopedFunctionalPlan,
        *,
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> tuple[
        ScopedFunctionalPlan,
        tuple[ScopedFunctionalPlanNormalization, ...],
    ]:
        """Apply only structure-preserving, authority-proven normalizations."""

        _audit_context_authority(planning_context, binding_catalog)
        normalized_plan, goal_normalizations = normalize_unique_scoped_goal_refs(
            plan,
            planning_context,
        )
        structure_report = audit_scoped_functional_structure(
            normalized_plan,
            planning_context,
        )
        if structure_report.first_issue is not None:
            first = structure_report.first_issue
            raise _error(
                first.code,
                first.path,
                first.message,
                issues=structure_report.issues,
                normalizations=goal_normalizations,
            )
        canonical_plan = _canonicalize_structure(
            normalized_plan,
            planning_context,
        )
        canonical_plan, capability_normalizations = _normalize_capability_wire(
            canonical_plan,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
        )
        canonical_plan, placement_normalizations = (
            _normalize_shared_step_placement(
                canonical_plan,
                planning_context=planning_context,
                binding_catalog=binding_catalog,
                capability_catalog=capability_catalog,
            )
        )
        normalizations = (
            *goal_normalizations,
            *capability_normalizations,
            *placement_normalizations,
        )
        return canonical_plan, normalizations

    def _lower_canonical(
        self,
        canonical_plan: ScopedFunctionalPlan,
        *,
        normalizations: tuple[ScopedFunctionalPlanNormalization, ...],
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> ScopedFunctionalPlanAuthority:
        locations = _step_locations(canonical_plan)
        by_id = _unique_steps(locations)
        preflight_issues = _collect_independent_authority_issues(
            canonical_plan,
            locations=locations,
            by_id=by_id,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
            planning_context=planning_context,
        )
        if preflight_issues:
            first = preflight_issues[0]
            raise _error(
                first.code,
                first.path,
                first.message,
                issues=preflight_issues,
                normalizations=normalizations,
            )
        goal_views = {
            item.answer_ref.ref: item
            for item in planning_context.goal_views
        }
        scope_parents = {
            item.scope_id: item.parent_scope_id
            for item in planning_context.scopes
        }
        published_answer_sources = _goal_answer_sources(canonical_plan)
        answer_by_step: dict[str, dict[str, str]] = {
            step_id: {} for step_id in by_id
        }
        goal_seed: dict[str, set[str]] = {step_id: set() for step_id in by_id}
        answer_target_refs: dict[str, set[str]] = {
            step_id: set() for step_id in by_id
        }
        for scope in _iter_scopes(canonical_plan.root_scope):
            for goal in scope.goals:
                view = goal_views[goal.goal_ref]
                producer = by_id.get(goal.answer_from.step_id)
                if producer is None:
                    raise _error(
                        "functional.answer_producer_invalid",
                        f"$.goals[{goal.goal_ref!r}].answer_from",
                        "answer producer step does not exist",
                    )
                _audit_answer_producer_visibility(
                    producer,
                    goal_scope_id=scope.scope_ref,
                    goal_ref=goal.goal_ref,
                    scope_parents=scope_parents,
                )
                _audit_return_role(
                    producer.step,
                    goal.answer_from.return_name,
                    capability_catalog,
                    path=f"$.goals[{goal.goal_ref!r}].answer_from",
                )
                existing = answer_by_step[producer.step.step_id].get(
                    goal.answer_from.return_name
                )
                if existing is not None:
                    raise _error(
                        "functional.answer_producer_invalid",
                        f"$.goals[{goal.goal_ref!r}].answer_from",
                        "one return role cannot bind multiple Goal answers",
                    )
                answer_by_step[producer.step.step_id][
                    goal.answer_from.return_name
                ] = goal.goal_ref
                goal_seed[producer.step.step_id].add(view.goal_unit_id)
                answer_target_refs[producer.step.step_id].update(
                    _answer_existing_object_refs(
                        view.goal_unit_id,
                        binding_catalog=binding_catalog,
                    )
                )
        dependencies: dict[str, set[str]] = {
            step_id: set() for step_id in by_id
        }
        answer_object_refs = _answer_object_refs_by_return(
            canonical_plan,
            goal_views=goal_views,
            binding_catalog=binding_catalog,
        )
        producers_by_target = _entity_state_producers(
            locations,
            by_id=by_id,
            capability_catalog=capability_catalog,
            answer_object_refs=answer_object_refs,
            binding_catalog=binding_catalog,
        )
        non_propagating_dependencies: set[tuple[str, str]] = set()
        typed_input_source_pins: dict[
            tuple[str, str, int], FunctionalTypedInputSourcePin
        ] = {}
        lowered_args: dict[
            str, dict[str, tuple[str | ScopedStepResultRef, ...]]
        ] = {}

        for location in locations:
            capability = capability_catalog.get(location.step.capability_id)
            if capability is None:
                raise _error(
                    "functional.capability_unknown",
                    f"$.steps[{location.step.step_id!r}].capability_id",
                    f"unknown capability {location.step.capability_id!r}",
                )
            _audit_step_contract(location.step, capability)
            lowered_args[location.step.step_id] = {}
            for arg_name, values in location.step.args.items():
                normalized: list[str | ScopedStepResultRef] = []
                for item_index, value in enumerate(values):
                    if isinstance(value, ScopedStepResultRef):
                        producer = by_id.get(value.step_id)
                        if producer is None:
                            raise _error(
                                "functional.step_ref_unresolved",
                                _arg_path(location, arg_name),
                                f"unknown producer step {value.step_id!r}",
                            )
                        _audit_explicit_dependency(
                            producer,
                            location,
                            ref=value,
                            published_answer_sources=published_answer_sources,
                            scope_parents=scope_parents,
                        )
                        _audit_return_role(
                            producer.step,
                            value.return_name,
                            capability_catalog,
                            path=_arg_path(location, arg_name),
                        )
                        if producer.order >= location.order:
                            raise _error(
                                "functional.step_ref_unresolved",
                                _arg_path(location, arg_name),
                                "step result references must point backward",
                            )
                        dependencies[location.step.step_id].add(value.step_id)
                        if isinstance(value, ScopedPublishedGoalResultRef):
                            non_propagating_dependencies.add(
                                (location.step.step_id, value.step_id)
                            )
                        normalized.append(value)
                        continue
                    binding = _input_binding(
                        binding_catalog,
                        value,
                        scope_id=location.scope_id,
                        goal_unit_ids=(
                            (goal_views[location.goal_ref].goal_unit_id,)
                            if location.goal_ref is not None
                            else ()
                        ),
                        path=_arg_path(location, arg_name),
                    )
                    if not _scope_visible(
                        binding.owner_scope_id,
                        location.scope_id,
                        scope_parents,
                    ):
                        raise _error(
                            "functional.step_scope_visibility_drift",
                            _arg_path(location, arg_name),
                            f"SemanticRef {value!r} is outside the step scope",
                        )
                    argument = next(
                        (
                            item
                            for item in capability.args
                            if item.name == arg_name
                        ),
                        None,
                    )
                    if (
                        argument is not None
                        and argument.input_view_mode == "latest_state"
                    ):
                        object_ids = _binding_math_object_ids(binding)
                        producer = (
                            _nearest_target_producer(
                                next(iter(object_ids)),
                                location,
                                producers_by_target,
                                argument=argument,
                                scope_parents=scope_parents,
                                capability_catalog=capability_catalog,
                                binding_catalog=binding_catalog,
                                by_id=by_id,
                                dependencies=dependencies,
                            )
                            if len(object_ids) == 1
                            else None
                        )
                        if producer is not None:
                            producer_location, return_name = producer
                            dependencies[location.step.step_id].add(
                                producer_location.step.step_id
                            )
                            typed_input_source_pins[
                                (location.step.step_id, arg_name, item_index)
                            ] = FunctionalTypedInputSourcePin(
                                consumer_call_id=location.step.step_id,
                                arg_name=arg_name,
                                item_index=item_index,
                                semantic_ref=value,
                                producer_call_id=producer_location.step.step_id,
                                return_name=return_name,
                            )
                            # The typed graph owns the dependency. Named
                            # entities remain SourceRef on the canonical wire;
                            # call preparation pins the producer's exact state.
                    normalized.append(value)
                lowered_args[location.step.step_id][arg_name] = tuple(
                    normalized
                )
        consumer_goals = _propagate_goal_consumers(
            locations,
            dependencies,
            goal_seed,
            non_propagating_dependencies=non_propagating_dependencies,
        )
        pruned_step_ids: set[str] = set()
        for location in locations:
            goals = consumer_goals[location.step.step_id]
            if location.goal_ref is None:
                if not goals:
                    capability = capability_catalog.get(
                        location.step.capability_id
                    )
                    if capability is None or not _dead_pure_step_is_prunable(
                        location.step,
                        capability=capability,
                        answer_bindings=answer_by_step[
                            location.step.step_id
                        ],
                    ):
                        raise _error(
                            "functional.step_goal_unresolved",
                            f"$.steps[{location.step.step_id!r}]",
                            "scope step has no descendant required Goal",
                        )
            if location.goal_ref is not None:
                expected = goal_views[location.goal_ref].goal_unit_id
                capability = capability_catalog.get(
                    location.step.capability_id
                )
                dead_pure_candidate = (
                    not goals
                    and capability is not None
                    and _dead_pure_step_is_prunable(
                        location.step,
                        capability=capability,
                        answer_bindings=answer_by_step[
                            location.step.step_id
                        ],
                    )
                )
                if goals != {expected} and not dead_pure_candidate:
                    raise _error(
                        "functional.step_goal_mismatch",
                        f"$.steps[{location.step.step_id!r}]",
                        "Goal-owned step serves a different Goal",
                    )
        semantic_owner_scopes = _semantic_owner_scopes(
            locations,
            consumer_goals=consumer_goals,
            dependencies=dependencies,
            lowered_args=lowered_args,
            answer_target_refs=answer_target_refs,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
            scope_parents=scope_parents,
        )
        for location in locations:
            goals = consumer_goals[location.step.step_id]
            owner_scope_id = semantic_owner_scopes[location.step.step_id]
            if location.goal_ref is None and any(
                not _scope_visible(
                    owner_scope_id,
                    _goal_owner(goal_id, planning_context),
                    scope_parents,
                )
                for goal_id in goals
            ):
                raise _error(
                    "functional.step_goal_mismatch",
                    f"$.steps[{location.step.step_id!r}]",
                    (
                        "scope-owned step serves a Goal outside its subtree: "
                        f"owner={owner_scope_id!r}, goals={sorted(goals)!r}"
                    ),
                )

        lowered_calls: dict[str, FunctionalCall] = {}
        step_authorities: dict[str, FunctionalStepScopeAuthority] = {}
        for location in locations:
            step = location.step
            capability = capability_catalog.get(step.capability_id)
            assert capability is not None
            args = {
                name: tuple(
                    PublishedGoalCallResultRef(
                        value.step_id,
                        value.return_name,
                        value.published_goal_ref,
                        value.semantic_ref,
                    )
                    if isinstance(value, ScopedPublishedGoalResultRef)
                    else CallResultRef(value.step_id, value.return_name)
                    if isinstance(value, ScopedStepResultRef)
                    else _input_binding(
                        binding_catalog,
                        value,
                        scope_id=semantic_owner_scopes[step.step_id],
                        goal_unit_ids=tuple(
                            sorted(consumer_goals[step.step_id])
                        ),
                        path=_arg_path(location, name),
                    ).semantic_ref
                    for value in values
                )
                for name, values in lowered_args[step.step_id].items()
            }
            args = {
                name: tuple(
                    _runtime_input_ref(value)
                    if isinstance(value, SemanticRef)
                    else value
                    for value in values
                )
                for name, values in args.items()
            }
            return_bindings: dict[str, SemanticRef] = {}
            effective_output_targets = _effective_output_target_refs(
                location,
                capability=capability,
                answer_return_names=frozenset(
                    answer_by_step[step.step_id]
                ),
                by_id=by_id,
                capability_catalog=capability_catalog,
                answer_object_refs=answer_object_refs,
                binding_catalog=binding_catalog,
            )
            for name, target in effective_output_targets.items():
                target_path = (
                    f"$.steps[{step.step_id!r}].output_targets[{name!r}]"
                )
                binding = _input_binding(
                    binding_catalog,
                    target,
                    scope_id=semantic_owner_scopes[step.step_id],
                    goal_unit_ids=tuple(
                        sorted(consumer_goals[step.step_id])
                    ),
                    path=target_path,
                )
                if not _scope_visible(
                    binding.owner_scope_id,
                    semantic_owner_scopes[step.step_id],
                    scope_parents,
                ):
                    raise _error(
                        "functional.output_target_invalid",
                        target_path,
                        "output target is outside the step scope",
                    )
                return_bindings[name] = binding.semantic_ref
            for return_name, goal_ref in answer_by_step[step.step_id].items():
                if return_name in return_bindings:
                    raise _error(
                        "functional.output_target_invalid",
                        f"$.steps[{step.step_id!r}].output_targets",
                        "answer return must not also declare output_targets",
                    )
                goal_id = goal_views[goal_ref].goal_unit_id
                try:
                    answer_binding = binding_catalog.answer_binding_for_goal(
                        goal_id
                    )
                except ProblemPlanningBindingError:
                    raise _error(
                        "planner.problem_source_binding_drift",
                        f"$.goals[{goal_ref!r}].answer_from",
                        "Goal answer authority is missing",
                        retryable=False,
                    )
                return_bindings[return_name] = answer_binding.semantic_ref
            _audit_return_bindings(
                step,
                capability,
                return_bindings=return_bindings,
                binding_catalog=binding_catalog,
                scope_id=semantic_owner_scopes[step.step_id],
                goal_unit_ids=tuple(
                    sorted(consumer_goals[step.step_id])
                ),
            )
            intent = step.intent or ""
            lowered_calls[step.step_id] = FunctionalCall(
                call_id=step.step_id,
                capability_id=step.capability_id,
                args=args,
                return_bindings=return_bindings,
                strategy=intent,
                reason=intent,
                return_expectations=dict(step.return_expectations),
            )
            binding_payload = {
                "step_id": step.step_id,
                "plan_scope_id": location.scope_id,
                "semantic_owner_scope_id": semantic_owner_scopes[step.step_id],
                "authored_goal_ref": location.goal_ref,
                "authored_goal_unit_id": (
                    goal_views[location.goal_ref].goal_unit_id
                    if location.goal_ref is not None
                    else None
                ),
                "consumer_goal_unit_ids": sorted(
                    consumer_goals[step.step_id]
                ),
                "args": {
                    name: [
                        _scoped_ref_authority_payload(value)
                        for value in values
                    ]
                    for name, values in lowered_args[step.step_id].items()
                },
                "output_targets": effective_output_targets,
                "answers": answer_by_step[step.step_id],
            }
            step_authorities[step.step_id] = FunctionalStepScopeAuthority(
                step_id=step.step_id,
                canonical_call_id=step.step_id,
                plan_scope_id=location.scope_id,
                authored_goal_ref=location.goal_ref,
                authored_goal_unit_id=(
                    goal_views[location.goal_ref].goal_unit_id
                    if location.goal_ref is not None
                    else None
                ),
                consumer_goal_unit_ids=tuple(
                    sorted(consumer_goals[step.step_id])
                ),
                semantic_owner_scope_id=semantic_owner_scopes[step.step_id],
                execution_scope_id=None,
                binding_signature=stable_hash(binding_payload),
            )

        calls_by_scope: dict[str, list[FunctionalCall]] = {}
        for location in locations:
            calls_by_scope.setdefault(
                semantic_owner_scopes[location.step.step_id],
                [],
            ).append(lowered_calls[location.step.step_id])
        lowered_scopes = tuple(
            FunctionalScope(
                scope_id=scope.scope_ref,
                label=_scope_label(scope.scope_ref, planning_context),
                calls=tuple(calls_by_scope.get(scope.scope_ref, ())),
            )
            for scope in _iter_scopes(canonical_plan.root_scope)
            if calls_by_scope.get(scope.scope_ref)
        )
        lowered_plan = FunctionalPlan(
            lowered_scopes,
            typed_dependency_graph={
                step_id: tuple(sorted(producer_ids))
                for step_id, producer_ids in dependencies.items()
                if producer_ids
            },
            typed_input_source_pins=typed_input_source_pins,
        )
        return ScopedFunctionalPlanAuthority(
            scoped_plan=canonical_plan,
            lowered_plan=lowered_plan,
            planning_context_id=planning_context.planning_context_id,
            problem_revision_id=planning_context.problem_revision_id,
            problem_semantic_hash=planning_context.problem_semantic_hash,
            plan_id=stable_hash(
                scoped_functional_plan_authority_payload(canonical_plan)
            ),
            plan_semantic_hash=stable_hash(
                {
                    "plan": _semantic_plan_payload(canonical_plan),
                    "normalizations": [
                        item.to_payload()
                        for item in normalizations
                        if item.action
                        not in {
                            "canonicalize_goal_target_input_ref",
                            "drop_fixed_form_return_expectation",
                            "drop_dead_pure_goal_unreachable_branch",
                        }
                    ],
                }
            ),
            step_authorities=step_authorities,
            normalizations=normalizations,
            pruned_step_ids=tuple(sorted(pruned_step_ids)),
        )

    def lower_executable_subset(
        self,
        plan: ScopedFunctionalPlan,
        *,
        excluded_step_ids: Sequence[str],
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> ScopedFunctionalPlanAuthority:
        """Lower locally valid v2 steps without claiming complete Goal answers."""

        canonical_plan, normalizations = self.canonicalize(
            plan,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
        )
        excluded = frozenset(excluded_step_ids)
        all_locations = _step_locations(canonical_plan)
        locations = tuple(
            item for item in all_locations if item.step.step_id not in excluded
        )
        if not locations:
            raise _error(
                "functional.call_goal_unresolved",
                "$.steps",
                "no authority-valid step remains for provisional execution",
            )
        by_id = _unique_steps(all_locations)
        goal_views = {
            item.answer_ref.ref: item for item in planning_context.goal_views
        }
        scope_parents = {
            item.scope_id: item.parent_scope_id
            for item in planning_context.scopes
        }
        published_answer_sources = _goal_answer_sources(canonical_plan)
        dependencies: dict[str, set[str]] = {
            item.step.step_id: set() for item in locations
        }
        answer_object_refs = _answer_object_refs_by_return(
            canonical_plan,
            goal_views=goal_views,
            binding_catalog=binding_catalog,
        )
        producers_by_target = _entity_state_producers(
            locations,
            by_id=by_id,
            capability_catalog=capability_catalog,
            answer_object_refs=answer_object_refs,
            binding_catalog=binding_catalog,
        )
        non_propagating_dependencies: set[tuple[str, str]] = set()
        typed_input_source_pins: dict[
            tuple[str, str, int], FunctionalTypedInputSourcePin
        ] = {}
        lowered_args: dict[
            str, dict[str, tuple[str | ScopedStepResultRef, ...]]
        ] = {}
        for location in locations:
            capability = capability_catalog.get(location.step.capability_id)
            if capability is None:
                raise _error(
                    "functional.capability_unknown",
                    f"$.steps[{location.step.step_id!r}].capability_id",
                    f"unknown capability {location.step.capability_id!r}",
                )
            _audit_step_contract(location.step, capability)
            lowered_args[location.step.step_id] = {}
            for arg_name, values in location.step.args.items():
                normalized: list[str | ScopedStepResultRef] = []
                for item_index, value in enumerate(values):
                    if isinstance(value, ScopedStepResultRef):
                        if value.step_id in excluded:
                            raise _error(
                                "functional.step_ref_unresolved",
                                _arg_path(location, arg_name),
                                "retained step depends on an excluded step",
                            )
                        producer = by_id.get(value.step_id)
                        if producer is None:
                            raise _error(
                                "functional.step_ref_unresolved",
                                _arg_path(location, arg_name),
                                f"unknown producer step {value.step_id!r}",
                            )
                        _audit_explicit_dependency(
                            producer,
                            location,
                            ref=value,
                            published_answer_sources=published_answer_sources,
                            scope_parents=scope_parents,
                        )
                        dependencies[location.step.step_id].add(value.step_id)
                        if isinstance(value, ScopedPublishedGoalResultRef):
                            non_propagating_dependencies.add(
                                (location.step.step_id, value.step_id)
                            )
                    else:
                        binding = _input_binding(
                            binding_catalog,
                            value,
                            scope_id=location.scope_id,
                            goal_unit_ids=(
                                (
                                    goal_views[
                                        location.goal_ref
                                    ].goal_unit_id,
                                )
                                if location.goal_ref is not None
                                else ()
                            ),
                            path=_arg_path(location, arg_name),
                        )
                        if not _scope_visible(
                            binding.owner_scope_id,
                            location.scope_id,
                            scope_parents,
                        ):
                            raise _error(
                                "functional.step_scope_visibility_drift",
                                _arg_path(location, arg_name),
                                f"SourceRef {value!r} is outside the step scope",
                            )
                        argument = next(
                            (
                                item
                                for item in capability.args
                                if item.name == arg_name
                            ),
                            None,
                        )
                        if (
                            argument is not None
                            and argument.input_view_mode == "latest_state"
                        ):
                            object_ids = _binding_math_object_ids(binding)
                            producer = (
                                _nearest_target_producer(
                                    next(iter(object_ids)),
                                    location,
                                    producers_by_target,
                                    argument=argument,
                                    scope_parents=scope_parents,
                                    capability_catalog=capability_catalog,
                                    binding_catalog=binding_catalog,
                                    by_id=by_id,
                                    dependencies=dependencies,
                                )
                                if len(object_ids) == 1
                                else None
                            )
                            if producer is not None:
                                producer_location, return_name = producer
                                dependencies[location.step.step_id].add(
                                    producer_location.step.step_id
                                )
                                typed_input_source_pins[
                                    (
                                        location.step.step_id,
                                        arg_name,
                                        item_index,
                                    )
                                ] = FunctionalTypedInputSourcePin(
                                    consumer_call_id=location.step.step_id,
                                    arg_name=arg_name,
                                    item_index=item_index,
                                    semantic_ref=value,
                                    producer_call_id=(
                                        producer_location.step.step_id
                                    ),
                                    return_name=return_name,
                                )
                                # Preserve the named SourceRef. The producer
                                # edge is sufficient to authorize latest-state
                                # selection at execution time.
                    normalized.append(value)
                lowered_args[location.step.step_id][arg_name] = tuple(normalized)

        answer_by_step: dict[str, dict[str, str]] = {
            item.step.step_id: {} for item in locations
        }
        answer_target_refs: dict[str, set[str]] = {
            item.step.step_id: set() for item in locations
        }
        goal_seed: dict[str, set[str]] = {
            item.step.step_id: set() for item in locations
        }
        for location in locations:
            if location.goal_ref is not None:
                goal_seed[location.step.step_id].add(
                    goal_views[location.goal_ref].goal_unit_id
                )
        for scope in _iter_scopes(canonical_plan.root_scope):
            for goal in scope.goals:
                if goal.answer_from.step_id in excluded:
                    continue
                producer = by_id.get(goal.answer_from.step_id)
                if producer is None or producer.step.step_id not in answer_by_step:
                    continue
                view = goal_views[goal.goal_ref]
                answer_by_step[producer.step.step_id][
                    goal.answer_from.return_name
                ] = goal.goal_ref
                goal_seed[producer.step.step_id].add(view.goal_unit_id)
                answer_target_refs[producer.step.step_id].update(
                    _answer_existing_object_refs(
                        view.goal_unit_id,
                        binding_catalog=binding_catalog,
                    )
                )
        consumer_goals = _propagate_goal_consumers(
            locations,
            dependencies,
            goal_seed,
            non_propagating_dependencies=non_propagating_dependencies,
        )
        for location in locations:
            if location.goal_ref is None and not consumer_goals[location.step.step_id]:
                consumer_goals[location.step.step_id].update(
                    goal.goal_unit_id
                    for goal in planning_context.goal_views
                    if _scope_visible(
                        location.scope_id,
                        goal.owner_scope_id,
                        scope_parents,
                    )
                )
        semantic_owner_scopes = _semantic_owner_scopes(
            locations,
            consumer_goals=consumer_goals,
            dependencies=dependencies,
            lowered_args=lowered_args,
            answer_target_refs=answer_target_refs,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
            scope_parents=scope_parents,
        )
        lowered_calls: dict[str, FunctionalCall] = {}
        step_authorities: dict[str, FunctionalStepScopeAuthority] = {}
        for location in locations:
            step = location.step
            capability = capability_catalog.get(step.capability_id)
            assert capability is not None
            args = {
                name: tuple(
                    PublishedGoalCallResultRef(
                        value.step_id,
                        value.return_name,
                        value.published_goal_ref,
                        value.semantic_ref,
                    )
                    if isinstance(value, ScopedPublishedGoalResultRef)
                    else CallResultRef(value.step_id, value.return_name)
                    if isinstance(value, ScopedStepResultRef)
                    else _runtime_input_ref(
                        _input_binding(
                            binding_catalog,
                            value,
                            scope_id=semantic_owner_scopes[step.step_id],
                            goal_unit_ids=tuple(
                                sorted(consumer_goals[step.step_id])
                            ),
                            path=_arg_path(location, name),
                        ).semantic_ref
                    )
                    for value in values
                )
                for name, values in lowered_args[step.step_id].items()
            }
            return_bindings: dict[str, SemanticRef] = {}
            effective_output_targets = _effective_output_target_refs(
                location,
                capability=capability,
                answer_return_names=frozenset(
                    answer_by_step[step.step_id]
                ),
                by_id=by_id,
                capability_catalog=capability_catalog,
                answer_object_refs=answer_object_refs,
                binding_catalog=binding_catalog,
            )
            for return_name, target in effective_output_targets.items():
                return_bindings[return_name] = _input_binding(
                    binding_catalog,
                    target,
                    scope_id=semantic_owner_scopes[step.step_id],
                    goal_unit_ids=tuple(
                        sorted(consumer_goals[step.step_id])
                    ),
                    path=f"$.steps[{step.step_id!r}].output_targets[{return_name!r}]",
                ).semantic_ref
            for return_name, goal_ref in answer_by_step[step.step_id].items():
                goal_id = goal_views[goal_ref].goal_unit_id
                answer_binding = binding_catalog.answer_binding_for_goal(
                    goal_id
                )
                return_bindings[return_name] = answer_binding.semantic_ref
            _audit_return_bindings(
                step,
                capability,
                return_bindings=return_bindings,
                binding_catalog=binding_catalog,
                scope_id=semantic_owner_scopes[step.step_id],
                goal_unit_ids=tuple(
                    sorted(consumer_goals[step.step_id])
                ),
            )
            intent = step.intent or ""
            lowered_calls[step.step_id] = FunctionalCall(
                call_id=step.step_id,
                capability_id=step.capability_id,
                args=args,
                return_bindings=return_bindings,
                strategy=intent,
                reason=intent,
                return_expectations=dict(step.return_expectations),
            )
            binding_payload = {
                "step_id": step.step_id,
                "plan_scope_id": location.scope_id,
                "semantic_owner_scope_id": semantic_owner_scopes[step.step_id],
                "authored_goal_ref": location.goal_ref,
                "authored_goal_unit_id": (
                    goal_views[location.goal_ref].goal_unit_id
                    if location.goal_ref is not None
                    else None
                ),
                "consumer_goal_unit_ids": sorted(consumer_goals[step.step_id]),
                "args": {
                    name: [
                        _scoped_ref_authority_payload(value)
                        for value in values
                    ]
                    for name, values in lowered_args[step.step_id].items()
                },
                "output_targets": effective_output_targets,
            }
            step_authorities[step.step_id] = FunctionalStepScopeAuthority(
                step_id=step.step_id,
                canonical_call_id=step.step_id,
                plan_scope_id=location.scope_id,
                authored_goal_ref=location.goal_ref,
                authored_goal_unit_id=(
                    goal_views[location.goal_ref].goal_unit_id
                    if location.goal_ref is not None
                    else None
                ),
                consumer_goal_unit_ids=tuple(
                    sorted(consumer_goals[step.step_id])
                ),
                semantic_owner_scope_id=semantic_owner_scopes[step.step_id],
                execution_scope_id=None,
                binding_signature=stable_hash(binding_payload),
            )
        calls_by_scope: dict[str, list[FunctionalCall]] = {}
        for location in locations:
            calls_by_scope.setdefault(
                semantic_owner_scopes[location.step.step_id],
                [],
            ).append(lowered_calls[location.step.step_id])
        lowered_plan = FunctionalPlan(
            tuple(
                FunctionalScope(
                    scope_id=scope.scope_ref,
                    label=_scope_label(scope.scope_ref, planning_context),
                    calls=tuple(calls_by_scope.get(scope.scope_ref, ())),
                )
                for scope in _iter_scopes(canonical_plan.root_scope)
                if calls_by_scope.get(scope.scope_ref)
            ),
            typed_dependency_graph={
                step_id: tuple(sorted(producer_ids))
                for step_id, producer_ids in dependencies.items()
                if producer_ids
            },
            typed_input_source_pins=typed_input_source_pins,
        )
        return ScopedFunctionalPlanAuthority(
            scoped_plan=canonical_plan,
            lowered_plan=lowered_plan,
            planning_context_id=planning_context.planning_context_id,
            problem_revision_id=planning_context.problem_revision_id,
            problem_semantic_hash=planning_context.problem_semantic_hash,
            plan_id=stable_hash(
                scoped_functional_plan_authority_payload(canonical_plan)
            ),
            plan_semantic_hash=stable_hash(_semantic_plan_payload(canonical_plan)),
            step_authorities=step_authorities,
            normalizations=normalizations,
        )


def _parse_scope(value: object) -> ScopedFunctionalScope:
    assert isinstance(value, dict)
    return ScopedFunctionalScope(
        scope_ref=str(value["scope_ref"]),
        steps=tuple(_parse_step(item) for item in value.get("steps", ())),
        goals=tuple(_parse_goal(item) for item in value.get("goals", ())),
        children=tuple(
            _parse_scope(item) for item in value.get("children", ())
        ),
    )


def _parse_goal(value: object) -> ScopedFunctionalGoalPlan:
    assert isinstance(value, dict)
    answer = value["answer_from"]
    assert isinstance(answer, dict)
    return ScopedFunctionalGoalPlan(
        goal_ref=str(value["goal_ref"]),
        steps=tuple(_parse_step(item) for item in value.get("steps", ())),
        answer_from=ScopedFunctionalAnswerSource(
            step_id=str(answer["step_id"]),
            return_name=str(answer["return"]),
        ),
    )


def _parse_step(value: object) -> ScopedFunctionalStep:
    assert isinstance(value, dict)
    args: dict[str, tuple[ScopedFunctionalRef, ...]] = {}
    raw_args = value["args"]
    assert isinstance(raw_args, dict)
    for name, raw in raw_args.items():
        values = raw if isinstance(raw, list) else [raw]
        args[str(name)] = tuple(_parse_ref(item) for item in values)
    return ScopedFunctionalStep(
        step_id=str(value["step_id"]),
        capability_id=str(value["capability_id"]),
        args=args,
        output_targets={
            str(key): str(target)
            for key, target in value.get("output_targets", {}).items()
        },
        return_expectations={
            str(key): form
            for key, form in value.get("return_expectations", {}).items()
        },
        intent=str(value["intent"]) if "intent" in value else None,
    )


def _parse_ref(value: object) -> ScopedFunctionalRef:
    if isinstance(value, str):
        return value
    assert isinstance(value, dict)
    return ScopedStepResultRef(
        step_id=str(value["step_id"]),
        return_name=str(value["return"]),
    )


def _iter_scopes(root: ScopedFunctionalScope) -> tuple[ScopedFunctionalScope, ...]:
    result: list[ScopedFunctionalScope] = []

    def visit(scope: ScopedFunctionalScope) -> None:
        result.append(scope)
        for child in scope.children:
            visit(child)

    visit(root)
    return tuple(result)


def _canonicalize_structure(
    plan: ScopedFunctionalPlan,
    context: ProblemPlanningContext,
) -> ScopedFunctionalPlan:
    expected_scopes = {scope.scope_id: scope for scope in context.scopes}
    expected_roots = [
        scope.scope_id
        for scope in context.scopes
        if scope.parent_scope_id is None
    ]
    if len(expected_roots) != 1:
        raise _error(
            "planner.problem_scope_visibility_drift",
            "$.planning_context.scopes",
            "planning Context must contain exactly one root scope",
            retryable=False,
        )
    structure_report = audit_scoped_functional_structure(plan, context)
    if structure_report.first_issue is not None:
        issue = structure_report.first_issue
        raise _error(issue.code, issue.path, issue.message)

    actual_scopes = list(_iter_scopes(plan.root_scope))
    actual_by_id = {scope.scope_ref: scope for scope in actual_scopes}
    actual_parent = dict(structure_report.actual_scope_parents)

    scope_order = {scope.scope_id: index for index, scope in enumerate(context.scopes)}
    goal_order = {
        goal.answer_ref.ref: index
        for index, goal in enumerate(context.goal_views)
    }

    def canonical(scope_id: str) -> ScopedFunctionalScope:
        source = actual_by_id[scope_id]
        children = sorted(
            (
                child_id
                for child_id, parent in actual_parent.items()
                if parent == scope_id
            ),
            key=scope_order.__getitem__,
        )
        return ScopedFunctionalScope(
            scope_ref=scope_id,
            steps=source.steps,
            goals=tuple(
                sorted(
                    source.goals,
                    key=lambda item: goal_order[item.goal_ref],
                )
            ),
            children=tuple(canonical(child_id) for child_id in children),
        )

    return ScopedFunctionalPlan(root_scope=canonical(expected_roots[0]))


def _normalize_shared_step_placement(
    plan: ScopedFunctionalPlan,
    *,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[
    ScopedFunctionalPlan,
    tuple[ScopedFunctionalPlanNormalization, ...],
]:
    """Promote mechanically safe cross-Goal producers to their scope LCA."""

    locations = _step_locations(plan)
    by_id = _unique_steps(locations)
    parents = {
        item.scope_id: item.parent_scope_id
        for item in planning_context.scopes
    }
    consumers: dict[str, list[tuple[str, str | None]]] = {
        step_id: [] for step_id in by_id
    }
    for consumer in locations:
        for values in consumer.step.args.values():
            for value in values:
                if (
                    isinstance(value, ScopedStepResultRef)
                    and value.step_id in consumers
                ):
                    consumers[value.step_id].append(
                        (consumer.scope_id, consumer.goal_ref)
                    )
    for scope in _iter_scopes(plan.root_scope):
        for goal in scope.goals:
            if goal.answer_from.step_id in consumers:
                consumers[goal.answer_from.step_id].append(
                    (scope.scope_ref, goal.goal_ref)
                )

    seed_targets: dict[str, str] = {}
    for step_id, step_consumers in consumers.items():
        location = by_id[step_id]
        crosses_authority = any(
            (
                location.goal_ref is not None
                and consumer_goal_ref != location.goal_ref
            )
            or (
                location.goal_ref is None
                and not _scope_visible(
                    location.scope_id,
                    consumer_scope_id,
                    parents,
                )
            )
            for consumer_scope_id, consumer_goal_ref in step_consumers
        )
        if not crosses_authority:
            continue
        seed_targets[step_id] = _lowest_common_ancestor(
            (
                location.scope_id,
                *(scope_id for scope_id, _goal_ref in step_consumers),
            ),
            parents,
        )

    promotions: dict[str, str] = {}
    for seed_id in sorted(
        seed_targets,
        key=lambda step_id: by_id[step_id].order,
    ):
        group = _shared_step_promotion_group(
            seed_id,
            target_scope_id=seed_targets[seed_id],
            by_id=by_id,
            parents=parents,
        )
        candidate = dict(promotions)
        for step_id, target_scope_id in group.items():
            existing = candidate.get(step_id)
            candidate[step_id] = (
                target_scope_id
                if existing is None
                else _lowest_common_ancestor(
                    (existing, target_scope_id),
                    parents,
                )
            )
        if _shared_step_promotions_are_safe(
            candidate,
            by_id=by_id,
            parents=parents,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
        ):
            promotions = candidate

    if not promotions:
        return plan, ()

    promoted_steps: dict[str, list[ScopedFunctionalStep]] = {}
    for step_id, target_scope_id in promotions.items():
        promoted_steps.setdefault(target_scope_id, []).append(
            by_id[step_id].step
        )
    for values in promoted_steps.values():
        values.sort(key=lambda item: by_id[item.step_id].order)
    promoted_ids = frozenset(promotions)

    def rebuild(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            steps=(
                *(
                    step
                    for step in scope.steps
                    if step.step_id not in promoted_ids
                ),
                *promoted_steps.get(scope.scope_ref, ()),
            ),
            goals=tuple(
                replace(
                    goal,
                    steps=tuple(
                        step
                        for step in goal.steps
                        if step.step_id not in promoted_ids
                    ),
                )
                for goal in scope.goals
            ),
            children=tuple(rebuild(child) for child in scope.children),
        )

    normalized = ScopedFunctionalPlan(root_scope=rebuild(plan.root_scope))
    records = tuple(
        ScopedFunctionalPlanNormalization(
            action="promote_shared_step_to_scope",
            reason="cross_goal_consumers_share_visible_authority",
            step_id=step_id,
            capability_id=by_id[step_id].step.capability_id,
            scope_ref=target_scope_id,
            from_goal_ref=by_id[step_id].goal_ref,
        )
        for step_id, target_scope_id in sorted(
            promotions.items(),
            key=lambda item: by_id[item[0]].order,
        )
    )
    return normalized, records


def _shared_step_promotion_group(
    seed_id: str,
    *,
    target_scope_id: str,
    by_id: Mapping[str, _StepLocation],
    parents: Mapping[str, str | None],
) -> dict[str, str]:
    proposals: dict[str, str] = {}
    pending = [(seed_id, target_scope_id)]
    while pending:
        step_id, requested_scope_id = pending.pop()
        location = by_id[step_id]
        target = _lowest_common_ancestor(
            (location.scope_id, requested_scope_id),
            parents,
        )
        existing = proposals.get(step_id)
        if existing is not None:
            target = _lowest_common_ancestor(
                (existing, target),
                parents,
            )
            if target == existing:
                continue
        proposals[step_id] = target
        for values in location.step.args.values():
            for value in values:
                if not isinstance(value, ScopedStepResultRef):
                    continue
                dependency = by_id.get(value.step_id)
                if dependency is None:
                    continue
                if dependency.goal_ref is not None or not _scope_visible(
                    dependency.scope_id,
                    target,
                    parents,
                ):
                    pending.append((dependency.step.step_id, target))
    return proposals


def _shared_step_promotions_are_safe(
    promotions: Mapping[str, str],
    *,
    by_id: Mapping[str, _StepLocation],
    parents: Mapping[str, str | None],
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
) -> bool:
    for step_id, target_scope_id in promotions.items():
        location = by_id[step_id]
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None or not capability.is_pure:
            return False
        for values in location.step.args.values():
            for value in values:
                if isinstance(value, ScopedStepResultRef):
                    dependency = by_id.get(value.step_id)
                    if dependency is None:
                        return False
                    dependency_scope = promotions.get(
                        dependency.step.step_id,
                        dependency.scope_id,
                    )
                    if (
                        dependency.goal_ref is not None
                        and dependency.step.step_id not in promotions
                    ) or not _scope_visible(
                        dependency_scope,
                        target_scope_id,
                        parents,
                    ):
                        return False
                    continue
                try:
                    binding_catalog.resolve_input_binding(
                        scope_id=target_scope_id,
                        local_ref=value,
                    )
                except ProblemPlanningBindingError:
                    return False
        for target_ref in location.step.output_targets.values():
            try:
                binding_catalog.resolve_input_binding(
                    scope_id=target_scope_id,
                    local_ref=target_ref,
                )
            except ProblemPlanningBindingError:
                return False
    return True


def _normalize_capability_wire(
    plan: ScopedFunctionalPlan,
    *,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[
    ScopedFunctionalPlan,
    tuple[ScopedFunctionalPlanNormalization, ...],
]:
    """Apply only one-to-one argument and answer-target normalizations."""

    locations = _step_locations(plan)
    by_id = _unique_steps(locations)
    replacements: dict[str, ScopedFunctionalStep] = {}
    normalizations: list[ScopedFunctionalPlanNormalization] = []
    for location in locations:
        step = location.step
        capability = capability_catalog.get(step.capability_id)
        if capability is None:
            continue
        declared = {item.name: item for item in capability.args}
        args = dict(step.args)

        for unknown_name in sorted(set(args) - set(declared)):
            matches = [
                item
                for item in capability.args
                if unknown_name in item.aliases and item.name not in args
            ]
            if len(matches) != 1:
                continue
            target = matches[0]
            args[target.name] = args.pop(unknown_name)
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="canonicalize_capability_arg_name",
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    from_arg=unknown_name,
                    to_arg=target.name,
                    reason="explicit_alias",
                )
            )

        unknown = sorted(set(args) - set(declared))
        missing_required = [
            item
            for item in capability.args
            if item.required and item.name not in args
        ]
        if len(unknown) == 1 and len(missing_required) == 1:
            unknown_name = unknown[0]
            target = missing_required[0]
            values = args[unknown_name]
            if _values_uniquely_match_required_arg(
                values,
                target,
                scope_id=location.scope_id,
                by_id=by_id,
                binding_catalog=binding_catalog,
                capability_catalog=capability_catalog,
            ):
                args[target.name] = args.pop(unknown_name)
                normalizations.append(
                    ScopedFunctionalPlanNormalization(
                        action="canonicalize_capability_arg_name",
                        step_id=step.step_id,
                        capability_id=step.capability_id,
                        from_arg=unknown_name,
                        to_arg=target.name,
                        reason="unique_required_type_match",
                    )
                )

        unknown = sorted(set(args) - set(declared))
        missing_required = [
            item
            for item in capability.args
            if item.required and item.name not in args
        ]
        invalid_cardinality = [
            name
            for name, values in args.items()
            if name in declared
            and declared[name].cardinality == "one"
            and len(values) != 1
        ]
        if unknown and not missing_required and not invalid_cardinality:
            for unknown_name in unknown:
                args.pop(unknown_name)
                normalizations.append(
                    ScopedFunctionalPlanNormalization(
                        action="drop_unknown_capability_arg",
                        step_id=step.step_id,
                        capability_id=step.capability_id,
                        arg_name=unknown_name,
                        reason="declared_call_contract_complete",
                    )
                )
        if args != dict(step.args):
            replacements[step.step_id] = replace(step, args=args)

    def rebuild(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            steps=tuple(
                replacements.get(step.step_id, step) for step in scope.steps
            ),
            goals=tuple(
                replace(
                    goal,
                    steps=tuple(
                        replacements.get(step.step_id, step)
                        for step in goal.steps
                    ),
                )
                for goal in scope.goals
            ),
            children=tuple(rebuild(child) for child in scope.children),
        )

    normalized_plan = (
        ScopedFunctionalPlan(root_scope=rebuild(plan.root_scope))
        if replacements
        else plan
    )
    normalized_plan, return_role_normalizations = (
        _normalize_unique_return_roles(
            normalized_plan,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=capability_catalog,
        )
    )
    normalizations.extend(return_role_normalizations)

    answer_roles = {
        (goal.answer_from.step_id, goal.answer_from.return_name)
        for scope in _iter_scopes(normalized_plan.root_scope)
        for goal in scope.goals
    }
    anonymous_target_replacements: dict[str, ScopedFunctionalStep] = {}
    for location in _step_locations(normalized_plan):
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        returns = {item.name: item for item in capability.returns}
        output_targets = dict(location.step.output_targets)
        for return_name, target_ref in tuple(output_targets.items()):
            returned = returns.get(return_name)
            if (
                returned is None
                or returned.binding_mode
                != "call_result_or_answer_or_existing_object"
                or returned.output_target_selector is not None
                or (location.step.step_id, return_name) in answer_roles
                or _has_visible_input_binding(
                    binding_catalog,
                    scope_id=location.scope_id,
                    local_ref=target_ref,
                )
                or _input_ref_exists_elsewhere(
                    binding_catalog,
                    local_ref=target_ref,
                )
            ):
                continue
            output_targets.pop(return_name)
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="drop_unknown_anonymous_output_target",
                    reason="call_result_has_no_named_object_authority",
                    step_id=location.step.step_id,
                    capability_id=location.step.capability_id,
                    scope_ref=location.scope_id,
                    return_name=return_name,
                    target_ref=target_ref,
                )
            )
        if output_targets != dict(location.step.output_targets):
            anonymous_target_replacements[location.step.step_id] = replace(
                location.step,
                output_targets=output_targets,
            )
    if anonymous_target_replacements:
        replacements = anonymous_target_replacements
        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild(normalized_plan.root_scope)
        )

    fact_ref_replacements: dict[str, ScopedFunctionalStep] = {}
    for location in _step_locations(normalized_plan):
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        declared = {item.name: item for item in capability.args}
        args = dict(location.step.args)
        for arg_name, values in location.step.args.items():
            argument = declared.get(arg_name)
            if (
                argument is None
                or not argument.accepted_condition_kinds
                or len(values) != 1
                or not isinstance(values[0], str)
                or _has_visible_input_binding(
                    binding_catalog,
                    scope_id=location.scope_id,
                    local_ref=values[0],
                )
                or values[0]
                not in {arg_name, *argument.accepted_condition_kinds}
            ):
                continue
            candidates = _unique_fact_ref_candidates(
                location,
                argument=argument,
                planning_context=planning_context,
                binding_catalog=binding_catalog,
            )
            if len(candidates) != 1:
                continue
            target_ref, fact_type = candidates[0]
            args[arg_name] = (target_ref,)
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="canonicalize_unique_fact_ref",
                    reason="unique_visible_fact_authority",
                    step_id=location.step.step_id,
                    capability_id=location.step.capability_id,
                    scope_ref=location.scope_id,
                    arg_name=arg_name,
                    from_ref=values[0],
                    to_ref=target_ref,
                    goal_ref=location.goal_ref,
                    fact_type=fact_type,
                )
            )
        if args != dict(location.step.args):
            fact_ref_replacements[location.step.step_id] = replace(
                location.step,
                args=args,
            )
    if fact_ref_replacements:
        replacements = fact_ref_replacements
        plan = normalized_plan
        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild(normalized_plan.root_scope)
        )

    locations = _step_locations(normalized_plan)
    goal_views = {
        item.answer_ref.ref: item for item in planning_context.goal_views
    }
    scope_parents = {
        item.scope_id: item.parent_scope_id
        for item in planning_context.scopes
    }
    identity_replacements: dict[str, ScopedFunctionalStep] = {}
    for location in locations:
        if location.goal_ref is None:
            continue
        goal_view = goal_views.get(location.goal_ref)
        capability = capability_catalog.get(location.step.capability_id)
        if goal_view is None or capability is None:
            continue
        declared = {item.name: item for item in capability.args}
        args = dict(location.step.args)
        for arg_name, values in location.step.args.items():
            argument = declared.get(arg_name)
            if (
                argument is None
                or argument.input_view_mode not in {"identity", "latest_state"}
                or argument.cardinality != "one"
                or len(values) != 1
                or not isinstance(values[0], str)
                or values[0] != location.goal_ref
            ):
                continue
            candidates = _goal_target_input_ref_candidates(
                location,
                goal_view=goal_view,
                argument=argument,
                binding_catalog=binding_catalog,
                scope_parents=scope_parents,
            )
            if len(candidates) != 1:
                continue
            target_ref = candidates[0]
            args[arg_name] = (target_ref,)
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="canonicalize_goal_target_input_ref",
                    reason="exact_math_object_identity",
                    step_id=location.step.step_id,
                    capability_id=location.step.capability_id,
                    arg_name=arg_name,
                    from_ref=values[0],
                    to_ref=target_ref,
                    goal_ref=location.goal_ref,
                )
            )
        if args != dict(location.step.args):
            identity_replacements[location.step.step_id] = replace(
                location.step,
                args=args,
            )
    if identity_replacements:
        replacements = identity_replacements
        plan = normalized_plan
        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild(normalized_plan.root_scope)
        )

    locations = _step_locations(normalized_plan)
    by_id = _unique_steps(locations)
    answer_replacements: dict[str, ScopedFunctionalStep] = {}
    goal_unit_by_ref = {
        view.answer_ref.ref: view.goal_unit_id
        for view in planning_context.goal_views
    }
    for scope in _iter_scopes(normalized_plan.root_scope):
        for goal in scope.goals:
            producer = by_id.get(goal.answer_from.step_id)
            goal_unit_id = goal_unit_by_ref.get(goal.goal_ref)
            if producer is None or goal_unit_id is None:
                continue
            step = answer_replacements.get(
                producer.step.step_id,
                producer.step,
            )
            target_ref = step.output_targets.get(
                goal.answer_from.return_name
            )
            if target_ref is None or target_ref not in set(
                _answer_existing_object_refs(
                    goal_unit_id,
                    binding_catalog=binding_catalog,
                )
            ):
                continue
            output_targets = dict(step.output_targets)
            output_targets.pop(goal.answer_from.return_name)
            answer_replacements[step.step_id] = replace(
                step,
                output_targets=output_targets,
            )
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="drop_redundant_answer_output_target",
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    return_name=goal.answer_from.return_name,
                    target_ref=target_ref,
                    reason="answer_from_precedence",
                )
            )
    if answer_replacements:
        replacements = answer_replacements
        plan = normalized_plan
        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild(normalized_plan.root_scope)
        )

    locations = _step_locations(normalized_plan)
    by_id = _unique_steps(locations)
    goal_unit_by_ref = {
        view.answer_ref.ref: view.goal_unit_id
        for view in planning_context.goal_views
    }
    answer_roles = {
        (goal.answer_from.step_id, goal.answer_from.return_name)
        for scope in _iter_scopes(normalized_plan.root_scope)
        for goal in scope.goals
    }
    answer_object_refs: dict[tuple[str, str], tuple[str, ...]] = {}
    for scope in _iter_scopes(normalized_plan.root_scope):
        for goal in scope.goals:
            goal_unit_id = goal_unit_by_ref.get(goal.goal_ref)
            if goal_unit_id is not None:
                answer_object_refs[
                    (goal.answer_from.step_id, goal.answer_from.return_name)
                ] = _answer_existing_object_refs(
                    goal_unit_id,
                    binding_catalog=binding_catalog,
                )
    target_replacements: dict[str, ScopedFunctionalStep] = {}
    for location in locations:
        step = location.step
        capability = capability_catalog.get(step.capability_id)
        if capability is None:
            continue
        output_targets = dict(step.output_targets)
        for returned in capability.returns:
            selector = returned.output_target_selector
            if (
                selector is None
                or returned.name in output_targets
                or (step.step_id, returned.name) in answer_roles
            ):
                continue
            target_ref = _select_unique_source_output_target(
                location,
                returned=returned,
                selector=selector,
                planning_context=planning_context,
                binding_catalog=binding_catalog,
                capability_catalog=capability_catalog,
                by_id=by_id,
                answer_object_refs=answer_object_refs,
            )
            if target_ref is None:
                continue
            output_targets[returned.name] = target_ref
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="infer_unique_output_target",
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    return_name=returned.name,
                    target_ref=target_ref,
                    reason="capability_selector_source_authority",
                )
            )
        if output_targets != dict(step.output_targets):
            target_replacements[step.step_id] = replace(
                step,
                output_targets=output_targets,
            )
    if target_replacements:
        replacements = target_replacements
        plan = normalized_plan
        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild(normalized_plan.root_scope)
        )

    expectation_replacements: dict[str, ScopedFunctionalStep] = {}
    for location in _step_locations(normalized_plan):
        step = location.step
        capability = capability_catalog.get(step.capability_id)
        if capability is None:
            continue
        returns = {item.name: item for item in capability.returns}
        expectations = dict(step.return_expectations)
        for return_name, form in sorted(step.return_expectations.items()):
            returned = returns.get(return_name)
            if returned is None or returned.return_expectation_policy != "omit":
                continue
            expectations.pop(return_name)
            normalizations.append(
                ScopedFunctionalPlanNormalization(
                    action="drop_fixed_form_return_expectation",
                    reason="return_expectation_policy_omit",
                    step_id=step.step_id,
                    capability_id=step.capability_id,
                    return_name=return_name,
                    from_form=form,
                )
            )
        if expectations != dict(step.return_expectations):
            expectation_replacements[step.step_id] = replace(
                step,
                return_expectations=expectations,
            )
    if expectation_replacements:
        replacements = expectation_replacements
        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild(normalized_plan.root_scope)
        )

    return (
        normalized_plan,
        tuple(
            sorted(
                normalizations,
                key=lambda item: (
                    item.step_id,
                    item.action,
                    item.from_arg or "",
                    item.to_arg or "",
                    item.arg_name or "",
                    item.from_ref or "",
                    item.to_ref or "",
                    item.return_name or "",
                    item.from_form or "",
                    item.fact_type or "",
                ),
            )
        ),
    )


def _normalize_unique_return_roles(
    plan: ScopedFunctionalPlan,
    *,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[
    ScopedFunctionalPlan,
    tuple[ScopedFunctionalPlanNormalization, ...],
]:
    """Canonicalize return roles from one unique typed global assignment."""

    locations = _step_locations(plan)
    by_id = _unique_steps(locations)
    returned_by_step = {
        step_id: tuple(capability.returns)
        for step_id, location in by_id.items()
        if (
            capability := capability_catalog.get(location.step.capability_id)
        )
        is not None
    }
    referenced_roles: dict[str, set[str]] = {
        step_id: set() for step_id in by_id
    }
    for step_id, location in by_id.items():
        declared = {item.name for item in returned_by_step.get(step_id, ())}
        referenced_roles[step_id].update(
            set(location.step.output_targets).intersection(declared)
        )
        referenced_roles[step_id].update(
            set(location.step.return_expectations).intersection(declared)
        )
        for values in location.step.args.values():
            for value in values:
                if (
                    isinstance(value, ScopedStepResultRef)
                    and value.return_name
                    in {
                        item.name
                        for item in returned_by_step.get(value.step_id, ())
                    }
                ):
                    referenced_roles.setdefault(value.step_id, set()).add(
                        value.return_name
                    )
    for scope in _iter_scopes(plan.root_scope):
        for goal in scope.goals:
            if goal.answer_from.return_name in {
                item.name
                for item in returned_by_step.get(
                    goal.answer_from.step_id, ()
                )
            }:
                referenced_roles.setdefault(
                    goal.answer_from.step_id, set()
                ).add(goal.answer_from.return_name)

    constraints: dict[tuple[str, str], set[str]] = {}

    def constrain(
        producer_step_id: str,
        authored_role: str,
        candidates: set[str],
    ) -> None:
        key = (producer_step_id, authored_role)
        if key in constraints:
            constraints[key].intersection_update(candidates)
        else:
            constraints[key] = set(candidates)

    def contextual_candidates(
        producer_step_id: str,
        candidates: Sequence[Any],
    ) -> set[str]:
        names = {item.name for item in candidates}
        used = names.intersection(referenced_roles.get(producer_step_id, set()))
        return used if len(used) == 1 else names

    for step_id, location in by_id.items():
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        returned = {item.name: item for item in capability.returns}
        for role, target_ref in location.step.output_targets.items():
            candidates = []
            try:
                target_binding = binding_catalog.resolve_input_binding(
                    scope_id=location.scope_id,
                    local_ref=target_ref,
                )
            except ProblemPlanningBindingError:
                target_binding = None
            declared_return = returned.get(role)
            if (
                declared_return is not None
                and declared_return.binding_mode != "internal_only"
                and (
                    target_binding is None
                    or _binding_accepts_runtime_type(
                        target_binding, declared_return.runtime_type
                    )
                )
            ):
                continue
            for item in capability.returns:
                if item.binding_mode == "internal_only":
                    continue
                existing = location.step.output_targets.get(item.name)
                if existing is not None and existing != target_ref:
                    continue
                if target_binding is not None and not _binding_accepts_runtime_type(
                    target_binding, item.runtime_type
                ):
                    continue
                candidates.append(item)
            if declared_return is not None and not candidates:
                continue
            constrain(
                step_id,
                role,
                contextual_candidates(step_id, candidates),
            )
        for role, form in location.step.return_expectations.items():
            declared_return = returned.get(role)
            if (
                declared_return is not None
                and (
                    declared_return.return_expectation_policy == "omit"
                    or form in declared_return.possible_forms
                )
            ):
                continue
            candidates = tuple(
                item
                for item in capability.returns
                if item.return_expectation_policy != "omit"
                if form in item.possible_forms
                and location.step.return_expectations.get(item.name)
                in (None, form)
            )
            if declared_return is not None and not candidates:
                continue
            constrain(
                step_id,
                role,
                contextual_candidates(step_id, candidates),
            )

    for location in locations:
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        args = {item.name: item for item in capability.args}
        for arg_name, values in location.step.args.items():
            argument = args.get(arg_name)
            accepted_types = (
                argument.accepted_item_types or (argument.runtime_type,)
                if argument is not None
                else ()
            )
            for value in values:
                if not isinstance(value, ScopedStepResultRef):
                    continue
                returned = returned_by_step.get(value.step_id, ())
                declared_return = next(
                    (
                        item
                        for item in returned
                        if item.name == value.return_name
                    ),
                    None,
                )
                if declared_return is not None and (
                    not accepted_types
                    or any(
                        runtime_type_compatible(
                            expected, declared_return.runtime_type
                        )
                        for expected in accepted_types
                    )
                ):
                    continue
                candidates = tuple(
                    item
                    for item in returned
                    if not accepted_types
                    or any(
                        runtime_type_compatible(expected, item.runtime_type)
                        for expected in accepted_types
                    )
                )
                if declared_return is not None and not candidates:
                    continue
                constrain(
                    value.step_id,
                    value.return_name,
                    contextual_candidates(value.step_id, candidates),
                )

    goal_views = {
        item.answer_ref.ref: item for item in planning_context.goal_views
    }
    for scope in _iter_scopes(plan.root_scope):
        for goal in scope.goals:
            returned = returned_by_step.get(goal.answer_from.step_id, ())
            producer = by_id.get(goal.answer_from.step_id)
            goal_view = goal_views.get(goal.goal_ref)
            answer_type = (
                goal_view.answer_ref.value_type
                if goal_view is not None
                else None
            )
            answer_targets = (
                set(
                    _answer_existing_object_refs(
                        goal_view.goal_unit_id,
                        binding_catalog=binding_catalog,
                    )
                )
                if goal_view is not None
                else set()
            )

            def target_compatible(item: Any) -> bool:
                if producer is None or not answer_targets:
                    return True
                targets = _return_object_target_refs(
                    producer,
                    returned=item,
                    by_id=by_id,
                    capability_catalog=capability_catalog,
                    answer_object_refs={},
                    binding_catalog=binding_catalog,
                )
                return not targets or bool(answer_targets.intersection(targets))

            declared_return = next(
                (
                    item
                    for item in returned
                    if item.name == goal.answer_from.return_name
                ),
                None,
            )
            if (
                declared_return is not None
                and declared_return.binding_mode != "internal_only"
                and (
                    answer_type is None
                    or runtime_type_compatible(
                        answer_type, declared_return.runtime_type
                    )
                )
                and target_compatible(declared_return)
            ):
                continue
            candidates = tuple(
                item
                for item in returned
                if item.binding_mode != "internal_only"
                and (
                    answer_type is None
                    or runtime_type_compatible(answer_type, item.runtime_type)
                )
                and target_compatible(item)
            )
            if declared_return is not None and not candidates:
                continue
            constrain(
                goal.answer_from.step_id,
                goal.answer_from.return_name,
                contextual_candidates(goal.answer_from.step_id, candidates),
            )

    assignments: dict[tuple[str, str], str] = {}
    by_producer: dict[str, set[str]] = {}
    for producer_step_id, authored_role in constraints:
        by_producer.setdefault(producer_step_id, set()).add(authored_role)
    for producer_step_id, authored_roles in sorted(by_producer.items()):
        remaining = set(authored_roles)
        while remaining:
            seed = min(remaining)
            component = {seed}
            public_roles = set(constraints[(producer_step_id, seed)])
            changed = True
            while changed:
                changed = False
                for authored_role in sorted(remaining - component):
                    candidate_set = constraints[(producer_step_id, authored_role)]
                    if public_roles.intersection(candidate_set):
                        component.add(authored_role)
                        public_roles.update(candidate_set)
                        changed = True
            remaining.difference_update(component)
            resolution = ReturnRoleAuthorityResolver.resolve(
                {
                    authored_role: constraints[
                        (producer_step_id, authored_role)
                    ]
                    for authored_role in component
                }
            )
            if resolution.unique:
                assignments.update(
                    {
                        (producer_step_id, authored_role): public_role
                        for authored_role, public_role in (
                            resolution.assignments.items()
                        )
                    }
                )

    replacements: dict[str, ScopedFunctionalStep] = {}
    normalizations: list[ScopedFunctionalPlanNormalization] = []

    for location in locations:
        args = dict(location.step.args)
        changed = False
        for arg_name, values in location.step.args.items():
            normalized_values: list[ScopedFunctionalRef] = []
            for value in values:
                if not isinstance(value, ScopedStepResultRef):
                    normalized_values.append(value)
                    continue
                return_name = assignments.get(
                    (value.step_id, value.return_name)
                )
                if return_name is None:
                    normalized_values.append(value)
                    continue
                normalized_values.append(replace(value, return_name=return_name))
                changed = True
                normalizations.append(
                    ScopedFunctionalPlanNormalization(
                        action="canonicalize_unique_return_role",
                        reason="unique_typed_return_assignment",
                        step_id=location.step.step_id,
                        capability_id=location.step.capability_id,
                        arg_name=arg_name,
                        from_ref=value.return_name,
                        to_ref=return_name,
                        return_name=return_name,
                    )
                )
            args[arg_name] = tuple(normalized_values)
        output_targets = dict(location.step.output_targets)
        return_expectations = dict(location.step.return_expectations)
        for field_name, values in (
            ("output_targets", output_targets),
            ("return_expectations", return_expectations),
        ):
            for authored_role in tuple(values):
                public_role = assignments.get(
                    (location.step.step_id, authored_role)
                )
                if public_role is None:
                    continue
                authored_value = values[authored_role]
                if public_role in values and values[public_role] != authored_value:
                    continue
                values[public_role] = authored_value
                values.pop(authored_role)
                changed = True
                normalizations.append(
                    ScopedFunctionalPlanNormalization(
                        action="canonicalize_unique_return_role",
                        reason="unique_typed_return_assignment",
                        step_id=location.step.step_id,
                        capability_id=location.step.capability_id,
                        arg_name=field_name,
                        from_ref=authored_role,
                        to_ref=public_role,
                        return_name=public_role,
                    )
                )
        if changed:
            replacements[location.step.step_id] = replace(
                location.step,
                args=args,
                output_targets=output_targets,
                return_expectations=return_expectations,
            )

    def rebuild_steps(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            steps=tuple(
                replacements.get(step.step_id, step) for step in scope.steps
            ),
            goals=tuple(
                replace(
                    goal,
                    steps=tuple(
                        replacements.get(step.step_id, step)
                        for step in goal.steps
                    ),
                )
                for goal in scope.goals
            ),
            children=tuple(rebuild_steps(child) for child in scope.children),
        )

    normalized_plan = (
        ScopedFunctionalPlan(root_scope=rebuild_steps(plan.root_scope))
        if replacements
        else plan
    )
    def rebuild_goals(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        goals: list[ScopedFunctionalGoalPlan] = []
        for goal in scope.goals:
            answer_from = goal.answer_from
            return_name = assignments.get(
                (answer_from.step_id, answer_from.return_name)
            )
            if return_name is not None:
                producer = by_id.get(answer_from.step_id)
                answer_from = ScopedFunctionalAnswerSource(
                    answer_from.step_id,
                    return_name,
                )
                normalizations.append(
                    ScopedFunctionalPlanNormalization(
                        action="canonicalize_unique_return_role",
                        reason="unique_typed_return_assignment",
                        step_id=answer_from.step_id,
                        capability_id=(
                            producer.step.capability_id
                            if producer is not None
                            else None
                        ),
                        from_ref=goal.answer_from.return_name,
                        to_ref=return_name,
                        return_name=return_name,
                        goal_ref=goal.goal_ref,
                    )
                )
            goals.append(replace(goal, answer_from=answer_from))
        return replace(
            scope,
            goals=tuple(goals),
            children=tuple(rebuild_goals(child) for child in scope.children),
        )

    normalized_plan = ScopedFunctionalPlan(
        root_scope=rebuild_goals(normalized_plan.root_scope)
    )

    locations = _step_locations(normalized_plan)
    by_id = _unique_steps(locations)
    goal_unit_by_ref = {
        view.answer_ref.ref: view.goal_unit_id
        for view in planning_context.goal_views
    }
    answer_object_refs: dict[tuple[str, str], tuple[str, ...]] = {}
    for scope in _iter_scopes(normalized_plan.root_scope):
        for goal in scope.goals:
            goal_unit_id = goal_unit_by_ref.get(goal.goal_ref)
            if goal_unit_id is not None:
                answer_object_refs[
                    (goal.answer_from.step_id, goal.answer_from.return_name)
                ] = _answer_existing_object_refs(
                    goal_unit_id,
                    binding_catalog=binding_catalog,
                )
    scope_parents = {
        item.scope_id: item.parent_scope_id
        for item in planning_context.scopes
    }
    producers_by_target = _entity_state_producers(
        locations,
        by_id=by_id,
        capability_catalog=capability_catalog,
        answer_object_refs=answer_object_refs,
        binding_catalog=binding_catalog,
    )
    dependency_scratch: dict[str, set[str]] = {
        item.step.step_id: set() for item in locations
    }
    named_ref_replacements: dict[str, ScopedFunctionalStep] = {}
    for location in locations:
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        declared_args = {item.name: item for item in capability.args}
        args = dict(location.step.args)
        changed = False
        for arg_name, values in location.step.args.items():
            argument = declared_args.get(arg_name)
            if argument is None or argument.input_view_mode not in {
                "identity",
                "latest_state",
            }:
                continue
            accepted_types = (
                argument.accepted_item_types or (argument.runtime_type,)
            )
            normalized_values: list[ScopedFunctionalRef] = []
            for value in values:
                if isinstance(value, ScopedPublishedGoalResultRef):
                    producer = by_id.get(value.step_id)
                    producer_capability = (
                        capability_catalog.get(producer.step.capability_id)
                        if producer is not None
                        else None
                    )
                    returned = next(
                        (
                            item
                            for item in (
                                producer_capability.returns
                                if producer_capability is not None
                                else ()
                            )
                            if item.name == value.return_name
                        ),
                        None,
                    )
                    targets = (
                        _return_object_target_refs(
                            producer,
                            returned=returned,
                            by_id=by_id,
                            capability_catalog=capability_catalog,
                            answer_object_refs=answer_object_refs,
                            binding_catalog=binding_catalog,
                        )
                        if producer is not None and returned is not None
                        else frozenset()
                    )
                    target_ref = next(iter(targets)) if len(targets) == 1 else None
                    if target_ref is None:
                        normalized_values.append(value)
                        continue
                    try:
                        target_binding = binding_catalog.resolve_input_binding(
                            scope_id=location.scope_id,
                            local_ref=target_ref,
                        )
                    except ProblemPlanningBindingError:
                        normalized_values.append(value)
                        continue
                    if not _binding_accepts_runtime_type(
                        target_binding,
                        returned.runtime_type,
                    ):
                        normalized_values.append(value)
                        continue
                    normalized_values.append(
                        replace(value, semantic_ref=target_ref)
                    )
                    if value.semantic_ref != target_ref:
                        changed = True
                        normalizations.append(
                            ScopedFunctionalPlanNormalization(
                                action=(
                                    "canonicalize_published_goal_entity_ref"
                                ),
                                reason="unique_return_object_authority",
                                step_id=location.step.step_id,
                                capability_id=location.step.capability_id,
                                arg_name=arg_name,
                                from_ref=(
                                    f"published_goal:{value.published_goal_ref}"
                                ),
                                to_ref=target_ref,
                            )
                        )
                    continue
                if not isinstance(value, ScopedStepResultRef):
                    normalized_values.append(value)
                    continue
                producer = by_id.get(value.step_id)
                producer_capability = (
                    capability_catalog.get(producer.step.capability_id)
                    if producer is not None
                    else None
                )
                returned = next(
                    (
                        item
                        for item in (
                            producer_capability.returns
                            if producer_capability is not None
                            else ()
                        )
                        if item.name == value.return_name
                    ),
                    None,
                )
                if (
                    producer is None
                    or returned is None
                    or returned.binding_mode == "internal_only"
                    or (
                        accepted_types
                        and not any(
                            runtime_type_compatible(
                                expected, returned.runtime_type
                            )
                            for expected in accepted_types
                        )
                    )
                ):
                    normalized_values.append(value)
                    continue
                targets = _return_object_target_refs(
                    producer,
                    returned=returned,
                    by_id=by_id,
                    capability_catalog=capability_catalog,
                    answer_object_refs=answer_object_refs,
                    binding_catalog=binding_catalog,
                )
                if len(targets) != 1:
                    normalized_values.append(value)
                    continue
                target_ref = next(iter(targets))
                try:
                    target_binding = binding_catalog.resolve_input_binding(
                        scope_id=location.scope_id,
                        local_ref=target_ref,
                    )
                except ProblemPlanningBindingError:
                    normalized_values.append(value)
                    continue
                if not _binding_accepts_runtime_type(
                    target_binding, returned.runtime_type
                ):
                    normalized_values.append(value)
                    continue
                object_ids = _binding_math_object_ids(target_binding)
                if len(object_ids) != 1:
                    normalized_values.append(value)
                    continue
                nearest = _nearest_target_producer(
                    next(iter(object_ids)),
                    location,
                    producers_by_target,
                    argument=argument,
                    scope_parents=scope_parents,
                    capability_catalog=capability_catalog,
                    binding_catalog=binding_catalog,
                    by_id=by_id,
                    dependencies=dependency_scratch,
                )
                if nearest is None or (
                    nearest[0].step.step_id,
                    nearest[1],
                ) != (value.step_id, value.return_name):
                    normalized_values.append(value)
                    continue
                normalized_values.append(target_ref)
                changed = True
                normalizations.append(
                    ScopedFunctionalPlanNormalization(
                        action="canonicalize_named_entity_result_ref",
                        reason="unique_return_object_authority",
                        step_id=location.step.step_id,
                        capability_id=location.step.capability_id,
                        arg_name=arg_name,
                        from_ref=(
                            f"{value.step_id}.{value.return_name}"
                        ),
                        to_ref=target_ref,
                    )
                )
            args[arg_name] = tuple(normalized_values)
        if changed:
            named_ref_replacements[location.step.step_id] = replace(
                location.step,
                args=args,
            )

    if named_ref_replacements:
        def rebuild_named(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
            return replace(
                scope,
                steps=tuple(
                    named_ref_replacements.get(step.step_id, step)
                    for step in scope.steps
                ),
                goals=tuple(
                    replace(
                        goal,
                        steps=tuple(
                            named_ref_replacements.get(step.step_id, step)
                            for step in goal.steps
                        ),
                    )
                    for goal in scope.goals
                ),
                children=tuple(rebuild_named(child) for child in scope.children),
            )

        normalized_plan = ScopedFunctionalPlan(
            root_scope=rebuild_named(normalized_plan.root_scope)
        )
    return normalized_plan, tuple(normalizations)


def _values_uniquely_match_required_arg(
    values: tuple[ScopedFunctionalRef, ...],
    target: Any,
    *,
    scope_id: str,
    by_id: Mapping[str, _StepLocation],
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
) -> bool:
    if target.cardinality == "one" and len(values) != 1:
        return False
    accepted_types = target.accepted_item_types or (target.runtime_type,)
    for value in values:
        actual_types: set[str] = set()
        if isinstance(value, ScopedStepResultRef):
            producer = by_id.get(value.step_id)
            producer_capability = (
                capability_catalog.get(producer.step.capability_id)
                if producer is not None
                else None
            )
            returned = next(
                (
                    item
                    for item in (
                        producer_capability.returns
                        if producer_capability is not None
                        else ()
                    )
                    if item.name == value.return_name
                ),
                None,
            )
            if returned is not None:
                actual_types.add(returned.runtime_type)
        else:
            try:
                binding = binding_catalog.resolve_input_binding(
                    scope_id=scope_id,
                    local_ref=value,
                )
            except ProblemPlanningBindingError:
                binding = None
            if binding is not None:
                if binding.semantic_ref.value_type is not None:
                    actual_types.add(binding.semantic_ref.value_type)
                actual_types.update(
                    source.runtime_type
                    for source in binding.typed_sources
                    if source.runtime_type is not None
                )
        if not actual_types or not any(
            runtime_type_compatible(expected, actual)
            for expected in accepted_types
            for actual in actual_types
        ):
            return False
    return True


def _dead_pure_step_is_prunable(
    step: ScopedFunctionalStep,
    *,
    capability: Any,
    answer_bindings: Mapping[str, str],
) -> bool:
    """Allow dead-code elimination only for observationally pure branches."""

    if not capability.is_pure or answer_bindings:
        return False
    return not any(
        "Condition" in split_runtime_types(returned.runtime_type)
        for returned in capability.returns
    )


def _unique_fact_ref_candidates(
    location: _StepLocation,
    *,
    argument: Any,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> tuple[tuple[str, str], ...]:
    """Return the sole fact authority that can mechanically fill one arg."""

    scope_parents = {
        scope.scope_id: scope.parent_scope_id
        for scope in planning_context.scopes
    }
    goal_ids = (
        {
            goal.goal_unit_id
            for goal in planning_context.goal_views
            if goal.answer_ref.ref == location.goal_ref
        }
        if location.goal_ref is not None
        else {
            goal.goal_unit_id
            for goal in planning_context.goal_views
            if _scope_visible(
                location.scope_id,
                goal.owner_scope_id,
                scope_parents,
            )
        }
    )
    candidates: list[tuple[str, str]] = []
    for ref_key, binding in sorted(
        binding_catalog.bindings.items(),
        key=lambda item: item[0].sort_key(),
    ):
        fact_type = binding.semantic_ref.value_type
        if (
            binding.usage != "input"
            or binding.semantic_ref.kind != "fact"
            or not isinstance(fact_type, str)
            or not _scope_visible(
                binding.owner_scope_id,
                location.scope_id,
                scope_parents,
            )
        ):
            continue
        if fact_type not in argument.accepted_condition_kinds:
            continue
        if (
            not goal_ids
            or not goal_ids <= set(binding.visible_goal_unit_ids)
            or not any(
                source.kind == "condition"
                for source in binding.typed_sources
            )
        ):
            continue
        candidates.append((ref_key.local_ref, fact_type))
    return tuple(candidates)


def _select_unique_source_output_target(
    location: _StepLocation,
    *,
    returned: Any,
    selector: Any,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
    by_id: Mapping[str, _StepLocation],
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
) -> str | None:
    """Resolve one declared output target from visible source-fact authority."""

    if selector.selector_id != "unique_visible_fact_target":
        return None
    scope_parents = {
        scope.scope_id: scope.parent_scope_id
        for scope in planning_context.scopes
    }
    related_refs = _declared_related_object_refs(
        location.step,
        arg_name=selector.related_arg,
        by_id=by_id,
        answer_object_refs=answer_object_refs,
    )
    related_arg = next(
        (
            item
            for item in capability_catalog.get(
                location.step.capability_id
            ).args
            if item.name == selector.related_arg
        ),
        None,
    )
    candidates: set[str] = set()
    for scope in planning_context.scopes:
        if not _scope_visible(
            scope.scope_id,
            location.scope_id,
            scope_parents,
        ):
            continue
        for fact in scope.facts:
            payload = fact.to_prompt_payload()
            if payload.get("kind") != selector.fact_kind:
                continue
            if any(
                payload.get(field) != expected
                for field, expected in selector.required_field_values
            ):
                continue
            related_ref = (
                payload.get(selector.related_field)
                if selector.related_field is not None
                else None
            )
            if related_refs and related_ref not in related_refs:
                continue
            if (
                related_arg is not None
                and isinstance(related_ref, str)
            ):
                try:
                    related_binding = binding_catalog.resolve_input_binding(
                        scope_id=location.scope_id,
                        local_ref=related_ref,
                    )
                except ProblemPlanningBindingError:
                    continue
                if not _binding_accepts_arg(related_binding, related_arg):
                    continue
            target_ref = payload.get(selector.target_field)
            if not isinstance(target_ref, str):
                continue
            try:
                binding = binding_catalog.resolve_input_binding(
                    scope_id=location.scope_id,
                    local_ref=target_ref,
                )
            except ProblemPlanningBindingError:
                continue
            if (
                not _scope_visible(
                    binding.owner_scope_id,
                    location.scope_id,
                    scope_parents,
                )
                or not _binding_accepts_runtime_type(
                    binding,
                    returned.runtime_type,
                )
            ):
                continue
            candidates.add(target_ref)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _declared_related_object_refs(
    step: ScopedFunctionalStep,
    *,
    arg_name: str | None,
    by_id: Mapping[str, _StepLocation],
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
) -> frozenset[str]:
    if arg_name is None:
        return frozenset()
    result: set[str] = set()
    for value in step.args.get(arg_name, ()):
        if isinstance(value, str):
            result.add(value)
            continue
        producer = by_id.get(value.step_id)
        if producer is None:
            continue
        explicit = producer.step.output_targets.get(value.return_name)
        if explicit is not None:
            result.add(explicit)
        result.update(
            answer_object_refs.get(
                (value.step_id, value.return_name),
                (),
            )
        )
    return frozenset(result)


def _effective_output_target_refs(
    producer: _StepLocation,
    *,
    capability: Any,
    answer_return_names: frozenset[str],
    by_id: Mapping[str, _StepLocation],
    capability_catalog: FunctionalCapabilityCatalog,
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
    binding_catalog: ProblemPlanningBindingCatalog,
) -> dict[str, str]:
    """Complete mechanical named-return bindings before v1 reconciliation."""

    result = dict(producer.step.output_targets)
    for returned in capability.returns:
        if returned.name in result or returned.name in answer_return_names:
            continue
        targets = _return_object_target_refs(
            producer,
            returned=returned,
            by_id=by_id,
            capability_catalog=capability_catalog,
            answer_object_refs=answer_object_refs,
            binding_catalog=binding_catalog,
        )
        if len(targets) == 1:
            result[returned.name] = next(iter(targets))
    return dict(sorted(result.items()))


def _return_object_target_refs(
    producer: _StepLocation,
    *,
    returned: Any,
    by_id: Mapping[str, _StepLocation],
    capability_catalog: FunctionalCapabilityCatalog,
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
    binding_catalog: ProblemPlanningBindingCatalog,
    seen: frozenset[tuple[str, str]] = frozenset(),
) -> frozenset[str]:
    """Resolve the Problem object written by one public return.

    Explicit output and answer authority take precedence. Declarative identity
    constraints and transition contracts may then prove the same named object
    without requiring the LLM to repeat compiler-owned wiring.
    """

    key = (producer.step.step_id, returned.name)
    if key in seen:
        return frozenset()
    capability = capability_catalog.get(producer.step.capability_id)
    if capability is None:
        return frozenset()
    constrained = _constraint_return_object_target_refs(
        producer,
        returned=returned,
        capability=capability,
        by_id=by_id,
        capability_catalog=capability_catalog,
        answer_object_refs=answer_object_refs,
        binding_catalog=binding_catalog,
        seen=seen | {key},
    )
    declared = frozenset()
    selected = frozenset()
    if (
        returned.identity_policy != "preserve_input_object"
        or returned.identity_arg is None
    ):
        pass
    else:
        declared = frozenset(
            target
            for value in producer.step.args.get(returned.identity_arg, ())
            for target in _functional_ref_object_targets(
                value,
                by_id=by_id,
                capability_catalog=capability_catalog,
                answer_object_refs=answer_object_refs,
                binding_catalog=binding_catalog,
                seen=seen | {key},
            )
        )
        auto_arg = next(
            (
                item
                for item in capability.auto_args
                if item.name == returned.identity_arg
            ),
            None,
        )
        if auto_arg is not None:
            selected = _auto_selector_object_refs(
                auto_arg.selector,
                producer=producer,
                binding_catalog=binding_catalog,
            )
    return ReturnObjectAuthorityResolver.resolve(
        explicit_output_targets=(
            (producer.step.output_targets[returned.name],)
            if returned.name in producer.step.output_targets
            else ()
        ),
        goal_answer_targets=answer_object_refs.get(key, ()),
        identity_constraint_targets=constrained,
        declared_identity_targets=declared,
        compiler_selector_targets=selected,
    ).target_refs


def _constraint_return_object_target_refs(
    producer: _StepLocation,
    *,
    returned: Any,
    capability: Any,
    by_id: Mapping[str, _StepLocation],
    capability_catalog: FunctionalCapabilityCatalog,
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
    binding_catalog: ProblemPlanningBindingCatalog,
    seen: frozenset[tuple[str, str]],
) -> frozenset[str]:
    """Resolve a return object from declarative same-object constraints."""

    def resolve_arg_targets(
        arg_name: str,
        object_role: str | None,
    ) -> frozenset[str]:
        return frozenset(
            target
            for value in producer.step.args.get(arg_name, ())
            for target in (
                _functional_ref_object_role_targets(
                    value,
                    role=object_role,
                    by_id=by_id,
                    capability_catalog=capability_catalog,
                    answer_object_refs=answer_object_refs,
                    binding_catalog=binding_catalog,
                    seen=seen,
                )
                if object_role is not None
                else _functional_ref_object_targets(
                    value,
                    by_id=by_id,
                    capability_catalog=capability_catalog,
                    answer_object_refs=answer_object_refs,
                    binding_catalog=binding_catalog,
                    seen=seen,
                )
            )
        )

    return identity_constraint_return_targets(
        capability.identity_constraints,
        return_name=returned.name,
        resolve_arg_targets=resolve_arg_targets,
    )


def _functional_ref_object_role_targets(
    value: ScopedFunctionalRef,
    *,
    role: str,
    by_id: Mapping[str, _StepLocation],
    capability_catalog: FunctionalCapabilityCatalog,
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
    binding_catalog: ProblemPlanningBindingCatalog,
    seen: frozenset[tuple[str, str]],
) -> frozenset[str]:
    """Project one declared object role through an earlier public return."""

    if isinstance(value, str):
        return frozenset()
    producer = by_id.get(value.step_id)
    if producer is None:
        return frozenset()
    key = (value.step_id, f"{value.return_name}#role:{role}")
    if key in seen:
        return frozenset()
    capability = capability_catalog.get(producer.step.capability_id)
    if capability is None:
        return frozenset()
    returned = next(
        (item for item in capability.returns if item.name == value.return_name),
        None,
    )
    if returned is None:
        return frozenset()
    result: set[str] = set()
    for projection in returned.object_role_projections:
        if projection.role != role:
            continue
        if projection.source_arg is not None:
            for source in producer.step.args.get(projection.source_arg, ()):
                if projection.source_object_role is None:
                    result.update(
                        _functional_ref_object_targets(
                            source,
                            by_id=by_id,
                            capability_catalog=capability_catalog,
                            answer_object_refs=answer_object_refs,
                            binding_catalog=binding_catalog,
                            seen=seen | {key},
                        )
                    )
                else:
                    result.update(
                        _functional_ref_object_role_targets(
                            source,
                            role=projection.source_object_role,
                            by_id=by_id,
                            capability_catalog=capability_catalog,
                            answer_object_refs=answer_object_refs,
                            binding_catalog=binding_catalog,
                            seen=seen | {key},
                        )
                    )
            continue
        source_return = next(
            (
                item
                for item in capability.returns
                if item.name == projection.source_return
            ),
            None,
        )
        if source_return is None:
            continue
        source_ref = ScopedStepResultRef(
            producer.step.step_id,
            source_return.name,
        )
        if projection.source_object_role is None:
            result.update(
                _functional_ref_object_targets(
                    source_ref,
                    by_id=by_id,
                    capability_catalog=capability_catalog,
                    answer_object_refs=answer_object_refs,
                    binding_catalog=binding_catalog,
                    seen=seen | {key},
                )
            )
        else:
            result.update(
                _functional_ref_object_role_targets(
                    source_ref,
                    role=projection.source_object_role,
                    by_id=by_id,
                    capability_catalog=capability_catalog,
                    answer_object_refs=answer_object_refs,
                    binding_catalog=binding_catalog,
                    seen=seen | {key},
                )
            )
    return frozenset(result)


def _auto_selector_object_refs(
    selector: str,
    *,
    producer: _StepLocation,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> frozenset[str]:
    """Resolve entity selectors used by hidden identity-preserving inputs."""

    selector_kind, separator, local_ref = selector.partition(":")
    if not separator or selector_kind not in {
        "function",
        "point",
        "symbol",
        "line",
        "ray",
        "polygon",
    }:
        return frozenset()
    try:
        binding = binding_catalog.resolve_input_binding(
            scope_id=producer.scope_id,
            local_ref=local_ref,
        )
    except ProblemPlanningBindingError:
        return frozenset()
    if (
        binding.usage != "input"
        or binding.semantic_ref.kind != selector_kind
        or not _binding_math_object_ids(binding)
    ):
        return frozenset()
    return frozenset((binding.semantic_ref.ref,))


def _functional_ref_object_targets(
    value: ScopedFunctionalRef,
    *,
    by_id: Mapping[str, _StepLocation],
    capability_catalog: FunctionalCapabilityCatalog,
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
    binding_catalog: ProblemPlanningBindingCatalog,
    seen: frozenset[tuple[str, str]],
) -> frozenset[str]:
    if isinstance(value, str):
        return frozenset((value,))
    producer = by_id.get(value.step_id)
    if producer is None:
        return frozenset()
    capability = capability_catalog.get(producer.step.capability_id)
    if capability is None:
        return frozenset()
    returned = next(
        (
            item
            for item in capability.returns
            if item.name == value.return_name
        ),
        None,
    )
    if returned is None:
        return frozenset()
    return _return_object_target_refs(
        producer,
        returned=returned,
        by_id=by_id,
        capability_catalog=capability_catalog,
        answer_object_refs=answer_object_refs,
        binding_catalog=binding_catalog,
        seen=seen,
    )


def _binding_accepts_arg(binding: Any | None, arg: Any) -> bool:
    if binding is None or binding.usage != "input":
        return False
    accepted = arg.accepted_item_types or (arg.runtime_type,)
    return any(
        runtime_type_compatible(expected, actual)
        for expected in accepted
        for actual in _binding_runtime_types(binding)
    )


def _binding_accepts_runtime_type(binding: Any, runtime_type: str) -> bool:
    return any(
        runtime_type_compatible(runtime_type, actual)
        for actual in _binding_runtime_types(binding)
    )


def _binding_runtime_types(binding: Any) -> frozenset[str]:
    result = {
        source.runtime_type
        for source in binding.typed_sources
        if source.runtime_type is not None
    }
    if binding.semantic_ref.value_type is not None:
        result.add(binding.semantic_ref.value_type)
    object_runtime_type = runtime_type_for_object_semantic_kind(
        binding.semantic_ref.kind
    )
    if object_runtime_type is not None:
        result.update(split_runtime_types(object_runtime_type))
    return frozenset(result)


def audit_scoped_functional_structure(
    plan: ScopedFunctionalPlan,
    context: ProblemPlanningContext,
) -> ScopedFunctionalStructureReport:
    """Compare a v2 plan tree with authenticated PlanningContext authority."""

    return _audit_scoped_functional_structure_maps(
        plan,
        expected_scope_parents=tuple(
            (scope.scope_id, scope.parent_scope_id)
            for scope in context.scopes
        ),
        expected_goal_owners=tuple(
            (goal.answer_ref.ref, goal.owner_scope_id)
            for goal in context.goal_views
        ),
    )


def normalize_unique_scoped_goal_refs(
    plan: ScopedFunctionalPlan,
    context: ProblemPlanningContext,
) -> tuple[
    ScopedFunctionalPlan,
    tuple[ScopedFunctionalPlanNormalization, ...],
]:
    """Repair only an unknown Goal id with one-to-one owner authority.

    Scope identity is validated first. A Goal id that already belongs to any
    authenticated Goal is never moved or reinterpreted, even when it appears
    under the wrong scope.
    """

    report = audit_scoped_functional_structure(plan, context)
    if any(
        (
            report.missing_scope_refs,
            report.unexpected_scope_refs,
            report.duplicate_scope_refs,
            report.moved_scope_refs,
            report.duplicate_goal_refs,
        )
    ):
        return plan, ()

    expected_by_scope: dict[str, list[str]] = {
        scope.scope_id: [] for scope in context.scopes
    }
    known_goal_refs: set[str] = set()
    for goal in context.goal_views:
        expected_by_scope.setdefault(goal.owner_scope_id, []).append(
            goal.answer_ref.ref
        )
        known_goal_refs.add(goal.answer_ref.ref)

    actual_by_scope = {
        scope.scope_ref: scope for scope in _iter_scopes(plan.root_scope)
    }
    replacements: dict[tuple[str, str], str] = {}
    normalizations: list[ScopedFunctionalPlanNormalization] = []
    for scope_ref in sorted(expected_by_scope):
        expected = expected_by_scope[scope_ref]
        scope = actual_by_scope.get(scope_ref)
        if scope is None or len(expected) != 1 or len(scope.goals) != 1:
            continue
        actual_ref = scope.goals[0].goal_ref
        expected_ref = expected[0]
        if actual_ref == expected_ref or actual_ref in known_goal_refs:
            continue
        replacements[(scope_ref, actual_ref)] = expected_ref
        normalizations.append(
            ScopedFunctionalPlanNormalization(
                action="canonicalize_unique_goal_ref",
                reason="single_goal_owner_authority",
                scope_ref=scope_ref,
                from_goal_ref=actual_ref,
                to_goal_ref=expected_ref,
            )
        )

    if not replacements:
        return plan, ()

    def rebuild(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            goals=tuple(
                replace(
                    goal,
                    goal_ref=replacements.get(
                        (scope.scope_ref, goal.goal_ref),
                        goal.goal_ref,
                    ),
                )
                for goal in scope.goals
            ),
            children=tuple(rebuild(child) for child in scope.children),
        )

    return (
        replace(plan, root_scope=rebuild(plan.root_scope)),
        tuple(normalizations),
    )


def audit_scoped_functional_structure_prompt_payload(
    plan: ScopedFunctionalPlan,
    problem_view_payload: Mapping[str, Any],
) -> ScopedFunctionalStructureReport:
    """Compare a plan with the exact prompt-safe Problem View sent to the LLM."""

    if problem_view_payload.get("schema_version") != PLANNER_PROBLEM_VIEW_CONTRACT:
        raise TypeError(
            "Planner Problem View schema_version must be "
            f"{PLANNER_PROBLEM_VIEW_CONTRACT!r}"
        )
    root = problem_view_payload.get("root_scope")
    if not isinstance(root, Mapping):
        raise TypeError("Planner Problem View root_scope must be an object")
    expected_scope_parents: list[tuple[str, str | None]] = []
    expected_goal_owners: list[tuple[str, str]] = []

    def visit(scope: Mapping[str, Any], parent: str | None) -> None:
        scope_ref = scope.get("id")
        if not isinstance(scope_ref, str) or not scope_ref:
            raise TypeError("Planner Problem View scope id must be a nonempty string")
        expected_scope_parents.append((scope_ref, parent))
        goals = scope.get("goals", ())
        if not isinstance(goals, Sequence) or isinstance(goals, (str, bytes)):
            raise TypeError("Planner Problem View goals must be an array")
        for goal in goals:
            if not isinstance(goal, Mapping):
                raise TypeError("Planner Problem View Goal must be an object")
            goal_ref = goal.get("goal_ref")
            if not isinstance(goal_ref, str) or not goal_ref:
                raise TypeError(
                    "Planner Problem View goal_ref must be a nonempty string"
                )
            expected_goal_owners.append((goal_ref, scope_ref))
        children = scope.get("children", ())
        if not isinstance(children, Sequence) or isinstance(
            children, (str, bytes)
        ):
            raise TypeError("Planner Problem View children must be an array")
        for child in children:
            if not isinstance(child, Mapping):
                raise TypeError("Planner Problem View child scope must be an object")
            visit(child, scope_ref)

    visit(root, None)
    return _audit_scoped_functional_structure_maps(
        plan,
        expected_scope_parents=tuple(expected_scope_parents),
        expected_goal_owners=tuple(expected_goal_owners),
    )


def _audit_scoped_functional_structure_maps(
    plan: ScopedFunctionalPlan,
    *,
    expected_scope_parents: tuple[tuple[str, str | None], ...],
    expected_goal_owners: tuple[tuple[str, str], ...],
) -> ScopedFunctionalStructureReport:
    actual_scope_parents: list[tuple[str, str | None]] = []
    actual_goal_owners: list[tuple[str, str]] = []

    def visit(scope: ScopedFunctionalScope, parent: str | None) -> None:
        actual_scope_parents.append((scope.scope_ref, parent))
        actual_goal_owners.extend(
            (goal.goal_ref, scope.scope_ref) for goal in scope.goals
        )
        for child in scope.children:
            visit(child, scope.scope_ref)

    visit(plan.root_scope, None)
    expected_scope_map = dict(expected_scope_parents)
    expected_goal_map = dict(expected_goal_owners)
    actual_scope_map = dict(actual_scope_parents)
    actual_goal_map = dict(actual_goal_owners)
    scope_counts = Counter(scope_ref for scope_ref, _ in actual_scope_parents)
    goal_counts = Counter(goal_ref for goal_ref, _ in actual_goal_owners)

    duplicate_scopes = tuple(
        sorted(scope_ref for scope_ref, count in scope_counts.items() if count > 1)
    )
    missing_scopes = tuple(sorted(set(expected_scope_map) - set(actual_scope_map)))
    unexpected_scopes = tuple(
        sorted(set(actual_scope_map) - set(expected_scope_map))
    )
    moved_scopes = tuple(
        sorted(
            scope_ref
            for scope_ref in set(expected_scope_map) & set(actual_scope_map)
            if expected_scope_map[scope_ref] != actual_scope_map[scope_ref]
        )
    )
    duplicate_goals = tuple(
        sorted(goal_ref for goal_ref, count in goal_counts.items() if count > 1)
    )
    missing_goals = tuple(sorted(set(expected_goal_map) - set(actual_goal_map)))
    unexpected_goals = tuple(sorted(set(actual_goal_map) - set(expected_goal_map)))
    moved_goals = tuple(
        sorted(
            goal_ref
            for goal_ref in set(expected_goal_map) & set(actual_goal_map)
            if expected_goal_map[goal_ref] != actual_goal_map[goal_ref]
        )
    )

    issues: list[ScopedFunctionalPlanIssue] = []
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.scope_tree_drift",
            f"$.scopes[{scope_ref!r}]",
            "scope appears more than once",
        )
        for scope_ref in duplicate_scopes
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.scope_tree_drift",
            f"$.scopes[{scope_ref!r}]",
            "scope is missing from the Plan",
        )
        for scope_ref in missing_scopes
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.scope_tree_drift",
            f"$.scopes[{scope_ref!r}]",
            "scope is not present in the Planner Problem View",
        )
        for scope_ref in unexpected_scopes
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.scope_tree_drift",
            f"$.scopes[{scope_ref!r}].parent",
            "scope parent differs from the Planner Problem View",
        )
        for scope_ref in moved_scopes
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.goal_tree_drift",
            f"$.goals[{goal_ref!r}]",
            "Goal appears more than once",
        )
        for goal_ref in duplicate_goals
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.goal_tree_drift",
            f"$.goals[{goal_ref!r}]",
            "Goal is missing from the Plan",
        )
        for goal_ref in missing_goals
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.goal_tree_drift",
            f"$.goals[{goal_ref!r}]",
            "Goal is not present in the Planner Problem View",
        )
        for goal_ref in unexpected_goals
    )
    issues.extend(
        ScopedFunctionalPlanIssue(
            "functional.goal_tree_drift",
            f"$.goals[{goal_ref!r}].owner_scope",
            "Goal is not nested in its owner scope",
        )
        for goal_ref in moved_goals
    )

    return ScopedFunctionalStructureReport(
        expected_scope_parents=expected_scope_parents,
        actual_scope_parents=tuple(actual_scope_parents),
        expected_goal_owners=expected_goal_owners,
        actual_goal_owners=tuple(actual_goal_owners),
        missing_scope_refs=missing_scopes,
        unexpected_scope_refs=unexpected_scopes,
        duplicate_scope_refs=duplicate_scopes,
        moved_scope_refs=moved_scopes,
        missing_goal_refs=missing_goals,
        unexpected_goal_refs=unexpected_goals,
        duplicate_goal_refs=duplicate_goals,
        moved_goal_refs=moved_goals,
        issues=tuple(issues),
    )


def _step_locations(plan: ScopedFunctionalPlan) -> tuple[_StepLocation, ...]:
    result: list[_StepLocation] = []
    order = 0
    for scope in _iter_scopes(plan.root_scope):
        for step in scope.steps:
            result.append(_StepLocation(step, scope.scope_ref, None, order))
            order += 1
        for goal in scope.goals:
            for step in goal.steps:
                result.append(
                    _StepLocation(
                        step,
                        scope.scope_ref,
                        goal.goal_ref,
                        order,
                    )
                )
                order += 1
    return tuple(result)


def _unique_steps(
    locations: Sequence[_StepLocation],
) -> dict[str, _StepLocation]:
    result: dict[str, _StepLocation] = {}
    for location in locations:
        if location.step.step_id in result:
            raise _error(
                "functional.step_id_duplicate",
                f"$.steps[{location.step.step_id!r}]",
                "step_id must be unique across the whole plan",
            )
        result[location.step.step_id] = location
    return result


def _audit_context_authority(
    context: ProblemPlanningContext,
    catalog: ProblemPlanningBindingCatalog,
) -> None:
    if (
        catalog.planning_context_id != context.planning_context_id
        or catalog.problem_revision_id != context.problem_revision_id
        or catalog.problem_semantic_hash != context.problem_semantic_hash
        or catalog.problem_id != context.problem_id
        or catalog.family_id != context.family_id
    ):
        raise _error(
            "planner.problem_revision_drift",
            "$.problem_authority",
            "planning Context and binding catalog differ",
            retryable=False,
        )


def _collect_independent_authority_issues(
    plan: ScopedFunctionalPlan,
    *,
    locations: Sequence[_StepLocation],
    by_id: Mapping[str, _StepLocation],
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
    planning_context: ProblemPlanningContext,
) -> tuple[ScopedFunctionalPlanIssue, ...]:
    """Collect independent contract, identity, and visibility roots."""

    scope_parents = {
        item.scope_id: item.parent_scope_id for item in planning_context.scopes
    }
    goal_views = {item.answer_ref.ref: item for item in planning_context.goal_views}
    published_answer_sources = _goal_answer_sources(plan)
    answer_object_refs = _answer_object_refs_by_return(
        plan,
        goal_views=goal_views,
        binding_catalog=binding_catalog,
    )
    answer_roles: dict[str, set[str]] = {step_id: set() for step_id in by_id}
    records: list[tuple[tuple[Any, ...], ScopedFunctionalPlanIssue]] = []

    def add(
        stage: int,
        scope_id: str,
        step_id: str,
        code: str,
        path: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        records.append(
            (
                (stage, _scope_path(scope_id, scope_parents), step_id, path),
                ScopedFunctionalPlanIssue(code, path, message, details or {}),
            )
        )

    for scope in _iter_scopes(plan.root_scope):
        for goal in scope.goals:
            path = f"$.goals[{goal.goal_ref!r}].answer_from"
            producer = by_id.get(goal.answer_from.step_id)
            if producer is None:
                add(
                    2,
                    scope.scope_ref,
                    goal.answer_from.step_id,
                    "functional.answer_producer_invalid",
                    path,
                    "answer producer step does not exist",
                )
                continue
            capability = capability_catalog.get(producer.step.capability_id)
            if capability is None or goal.answer_from.return_name not in {
                item.name for item in capability.returns
            }:
                goal_view = goal_views.get(goal.goal_ref)
                answer_type = (
                    goal_view.answer_ref.value_type
                    if goal_view is not None
                    else None
                )
                expected_roles = (
                    tuple(
                        item.name
                        for item in capability.returns
                        if item.binding_mode != "internal_only"
                        and (
                            answer_type is None
                            or runtime_type_compatible(
                                answer_type, item.runtime_type
                            )
                        )
                    )
                    if capability is not None
                    else ()
                )
                add(
                    2,
                    scope.scope_ref,
                    producer.step.step_id,
                    "functional.step_ref_unresolved",
                    path,
                    (
                        f"step {producer.step.step_id!r} does not declare return "
                        f"{goal.answer_from.return_name!r}"
                    ),
                    {
                        "capability_id": producer.step.capability_id,
                        "observed_role": goal.answer_from.return_name,
                        "expected_roles": list(expected_roles),
                        "return_context": "answer_from",
                        "retryability": "planner_repairable",
                        "repair_action": "repair_return_role",
                    },
                )
            else:
                answer_roles[producer.step.step_id].add(
                    goal.answer_from.return_name
                )
            if producer.goal_ref is not None and producer.goal_ref != goal.goal_ref:
                add(
                    3,
                    scope.scope_ref,
                    producer.step.step_id,
                    "functional.answer_producer_invalid",
                    path,
                    "Goal cannot use another Goal's private step as answer producer",
                )
            elif producer.goal_ref is None and not _scope_visible(
                producer.scope_id,
                scope.scope_ref,
                scope_parents,
            ):
                add(
                    3,
                    scope.scope_ref,
                    producer.step.step_id,
                    "functional.answer_producer_invalid",
                    path,
                    "answer producer is outside the Goal's visible scope path",
                )
            if goal.goal_ref not in goal_views:
                add(
                    3,
                    scope.scope_ref,
                    producer.step.step_id,
                    "functional.goal_tree_drift",
                    f"$.goals[{goal.goal_ref!r}]",
                    "Goal is not present in PlanningContext authority",
                )

    locally_valid: set[str] = set()
    for location in locations:
        step = location.step
        capability = capability_catalog.get(step.capability_id)
        if capability is None:
            add(
                0,
                location.scope_id,
                step.step_id,
                "functional.capability_unknown",
                f"$.steps[{step.step_id!r}].capability_id",
                f"unknown capability {step.capability_id!r}",
            )
            continue
        args = {item.name: item for item in capability.args}
        unknown_args = tuple(sorted(set(step.args) - set(args)))
        missing_required_args = tuple(
            sorted(
                name
                for name, item in args.items()
                if item.required and name not in step.args
            )
        )
        invalid_cardinality_args = tuple(
            sorted(
                name
                for name, values in step.args.items()
                if name in args
                and args[name].cardinality == "one"
                and len(values) != 1
            )
        )
        argument_contract_details = {
            "capability_id": step.capability_id,
            "expected_allowed_args": tuple(sorted(args)),
            "expected_required_args": tuple(
                sorted(name for name, item in args.items() if item.required)
            ),
            "observed_args": tuple(sorted(step.args)),
            "observed_unknown_args": unknown_args,
            "observed_missing_required_args": missing_required_args,
            "observed_invalid_cardinality_args": invalid_cardinality_args,
            "retryability": "planner_repairable",
        }
        local_issue_count = len(records)
        for name in unknown_args:
            add(
                0,
                location.scope_id,
                step.step_id,
                "functional.step_contract_invalid",
                f"$.steps[{step.step_id!r}].args[{name!r}]",
                f"unknown capability args: {[name]!r}",
                {
                    **argument_contract_details,
                    "arg_name": name,
                    "repair_action": (
                        "remove_unknown_capability_arg"
                        if not missing_required_args
                        and not invalid_cardinality_args
                        else "repair_capability_arguments"
                    ),
                },
            )
        for name in missing_required_args:
            add(
                0,
                location.scope_id,
                step.step_id,
                "functional.step_contract_invalid",
                f"$.steps[{step.step_id!r}].args[{name!r}]",
                f"missing required capability args: {[name]!r}",
                {
                    **argument_contract_details,
                    "arg_name": name,
                    "repair_action": (
                        "repair_capability_arguments"
                        if unknown_args
                        else "provide_required_input"
                    ),
                },
            )
        for name, values in sorted(step.args.items()):
            item = args.get(name)
            if item is not None and item.cardinality == "one" and len(values) != 1:
                add(
                    0,
                    location.scope_id,
                    step.step_id,
                    "functional.step_contract_invalid",
                    f"$.steps[{step.step_id!r}].args[{name!r}]",
                    "argument requires exactly one value",
                    {
                        **argument_contract_details,
                        "arg_name": name,
                        "expected_cardinality": "one",
                        "observed_count": len(values),
                        "repair_action": "repair_input_binding",
                    },
                )
        returns = {item.name: item for item in capability.returns}
        for role, form in sorted(step.return_expectations.items()):
            returned = returns.get(role)
            if returned is None or form not in returned.possible_forms:
                compatible_roles = tuple(
                    item.name
                    for item in capability.returns
                    if item.return_expectation_policy != "omit"
                    if form in item.possible_forms
                )
                add(
                    0,
                    location.scope_id,
                    step.step_id,
                    "functional.step_contract_invalid",
                    f"$.steps[{step.step_id!r}].return_expectations[{role!r}]",
                    "return expectation is not declared by the capability",
                    {
                        "capability_id": capability.capability_id,
                        "observed_role": role,
                        "observed_form": form,
                        "expected_roles": list(
                            compatible_roles
                            or tuple(
                                item.name
                                for item in capability.returns
                                if item.possible_forms
                                and item.return_expectation_policy != "omit"
                            )
                        ),
                        "expected_forms": {
                            item.name: list(item.possible_forms)
                            for item in capability.returns
                            if item.possible_forms
                            and item.return_expectation_policy != "omit"
                        },
                        "retryability": "planner_repairable",
                        "repair_action": "repair_return_role",
                    },
                )
        for role, target in sorted(step.output_targets.items()):
            returned = returns.get(role)
            path = f"$.steps[{step.step_id!r}].output_targets[{role!r}]"
            if returned is None or returned.binding_mode == "internal_only":
                expected_roles = tuple(
                    item.name
                    for item in capability.returns
                    if item.binding_mode != "internal_only"
                )
                add(
                    1,
                    location.scope_id,
                    step.step_id,
                    "functional.output_target_invalid",
                    path,
                    "return cannot target an external Problem object",
                    {
                        "capability_id": capability.capability_id,
                        "observed_role": role,
                        "expected_roles": list(expected_roles),
                        "return_context": "output_targets",
                        "retryability": "planner_repairable",
                        "repair_action": "repair_return_role",
                    },
                )
                continue
            try:
                binding = binding_catalog.resolve_input_binding(
                    scope_id=location.scope_id,
                    local_ref=target,
                )
            except ProblemPlanningBindingError:
                binding = None
            if binding is None:
                outside_scope = _input_ref_exists_elsewhere(
                    binding_catalog,
                    local_ref=target,
                )
                expected_targets = _visible_compatible_output_target_refs(
                    binding_catalog,
                    scope_id=location.scope_id,
                    runtime_type=returned.runtime_type,
                    scope_parents=scope_parents,
                )
                add(
                    1,
                    location.scope_id,
                    step.step_id,
                    "functional.output_target_invalid",
                    path,
                    (
                        "output target is outside the step scope"
                        if outside_scope
                        else f"unknown existing-object target {target!r}"
                    ),
                    {
                        "capability_id": capability.capability_id,
                        "observed_role": role,
                        "observed_target": target,
                        "expected_targets": list(expected_targets),
                        "retryability": "planner_repairable",
                        "repair_action": (
                            "remove_unknown_output_target"
                            if returned.binding_mode
                            == "call_result_or_answer_or_existing_object"
                            else "choose_visible_output_target"
                        ),
                    },
                )
        bound_roles = set(step.output_targets) | answer_roles[step.step_id]
        for returned in capability.returns:
            if (
                returned.required
                and returned.binding_mode == "explicit_answer_or_existing_object"
                and returned.name not in bound_roles
            ):
                add(
                    1,
                    location.scope_id,
                    step.step_id,
                    "functional.output_target_invalid",
                    f"$.steps[{step.step_id!r}].output_targets",
                    f"return {returned.name!r} requires an external target",
                )
            if (
                returned.output_target_selector is not None
                and returned.name not in bound_roles
            ):
                add(
                    1,
                    location.scope_id,
                    location.step.step_id,
                    "functional.output_target_invalid",
                    f"$.steps[{location.step.step_id!r}].output_targets",
                    (
                        f"return {returned.name!r} has no unique target from "
                        "its declared source-fact selector; provide an explicit "
                        "output_targets binding"
                    ),
                )
        if len(records) == local_issue_count:
            locally_valid.add(step.step_id)

    for location in locations:
        if location.step.step_id not in locally_valid:
            continue
        capability = capability_catalog.get(location.step.capability_id)
        declared_args = {
            item.name: item
            for item in (capability.args if capability is not None else ())
        }
        for arg_name, values in location.step.args.items():
            for value in values:
                path = _arg_path(location, arg_name)
                if isinstance(value, ScopedStepResultRef):
                    producer = by_id.get(value.step_id)
                    if producer is None:
                        add(
                            2,
                            location.scope_id,
                            location.step.step_id,
                            "functional.step_ref_unresolved",
                            path,
                            f"unknown producer step {value.step_id!r}",
                        )
                        continue
                    producer_capability = capability_catalog.get(
                        producer.step.capability_id
                    )
                    returned = next(
                        (
                            item
                            for item in (
                                producer_capability.returns
                                if producer_capability is not None
                                else ()
                            )
                            if item.name == value.return_name
                        ),
                        None,
                    )
                    named_targets = (
                        _return_object_target_refs(
                            producer,
                            returned=returned,
                            by_id=by_id,
                            capability_catalog=capability_catalog,
                            answer_object_refs=answer_object_refs,
                            binding_catalog=binding_catalog,
                        )
                        if returned is not None
                        else frozenset()
                    )
                    if named_targets:
                        expected_ref = (
                            next(iter(named_targets))
                            if len(named_targets) == 1
                            else None
                        )
                        if isinstance(value, ScopedPublishedGoalResultRef):
                            if value.semantic_ref != expected_ref:
                                add(
                                    2,
                                    location.scope_id,
                                    location.step.step_id,
                                    "functional.published_goal_result_invalid",
                                    path,
                                    (
                                        "published Goal result does not resolve "
                                        "to one canonical named Entity"
                                    ),
                                    {
                                        "published_goal_ref": (
                                            value.published_goal_ref
                                        ),
                                        "producer": {
                                            "step_id": value.step_id,
                                            "return": value.return_name,
                                        },
                                        "observed_ref": value.semantic_ref,
                                        "expected_refs": sorted(named_targets),
                                        "repair_action": (
                                            "use_published_goal_result"
                                        ),
                                    },
                                )
                        else:
                            add(
                                2,
                                location.scope_id,
                                location.step.step_id,
                                "functional.named_entity_requires_source_ref",
                                path,
                                (
                                    f"return {value.return_name!r} updates named "
                                    f"Entity {sorted(named_targets)!r}; use that "
                                    "Entity ref and let the Method view select "
                                    "its state"
                                ),
                                {
                                    "named_entity_refs": sorted(named_targets),
                                    "arg_name": arg_name,
                                    "expected_ref": expected_ref,
                                    "expected_object_ref": expected_ref,
                                    "producer": {
                                        "step_id": value.step_id,
                                        "return": value.return_name,
                                    },
                                    "target": expected_ref,
                                    "repair_action": (
                                        "use_named_entity_source_ref"
                                    ),
                                },
                            )
                    if producer_capability is None or value.return_name not in {
                        item.name for item in producer_capability.returns
                    }:
                        argument = declared_args.get(arg_name)
                        accepted_types = (
                            argument.accepted_item_types
                            or (argument.runtime_type,)
                            if argument is not None
                            else ()
                        )
                        expected_roles = (
                            tuple(
                                item.name
                                for item in producer_capability.returns
                                if item.binding_mode != "internal_only"
                                and (
                                    not accepted_types
                                    or any(
                                        runtime_type_compatible(
                                            expected,
                                            item.runtime_type,
                                        )
                                        for expected in accepted_types
                                    )
                                )
                            )
                            if producer_capability is not None
                            else ()
                        )
                        add(
                            2,
                            location.scope_id,
                            location.step.step_id,
                            "functional.step_ref_unresolved",
                            path,
                            f"producer does not declare return {value.return_name!r}",
                            {
                                "capability_id": (
                                    producer.step.capability_id
                                ),
                                "observed_role": value.return_name,
                                "expected_roles": list(expected_roles),
                                "return_context": "step_result_ref",
                                "arg_name": arg_name,
                                "retryability": "planner_repairable",
                                "repair_action": "repair_return_role",
                            },
                        )
                    if producer.order >= location.order:
                        add(
                            2,
                            location.scope_id,
                            location.step.step_id,
                            "functional.step_ref_unresolved",
                            path,
                            "step result references must point backward",
                        )
                    if isinstance(value, ScopedPublishedGoalResultRef):
                        if not _published_dependency_valid(
                            value,
                            producer,
                            published_answer_sources,
                        ):
                            add(
                                3,
                                location.scope_id,
                                location.step.step_id,
                                "functional.published_goal_result_invalid",
                                path,
                                (
                                    "published Goal ref must name the exact final "
                                    "answer source of that Goal"
                                ),
                            )
                    elif producer.goal_ref is not None and (
                        producer.goal_ref != location.goal_ref
                    ):
                        add(
                            3,
                            location.scope_id,
                            location.step.step_id,
                            "functional.step_scope_visibility_drift",
                            path,
                            "a Goal-owned result cannot be read outside that Goal",
                        )
                    elif producer.goal_ref is None and not _scope_visible(
                        producer.scope_id,
                        location.scope_id,
                        scope_parents,
                    ):
                        add(
                            3,
                            location.scope_id,
                            location.step.step_id,
                            "functional.step_scope_visibility_drift",
                            path,
                            "step result crosses sibling or descendant scope authority",
                        )
                    continue
                try:
                    binding = binding_catalog.resolve_input_binding(
                        scope_id=location.scope_id,
                        local_ref=value,
                    )
                except ProblemPlanningBindingError:
                    binding = None
                answer_goal_ids = tuple(
                    goal_id
                    for goal_id, answer_key in (
                        binding_catalog.goal_answer_refs.items()
                    )
                    if answer_key.local_ref == value
                )
                if binding is None and not answer_goal_ids:
                    code = (
                        "functional.step_scope_visibility_drift"
                        if _input_ref_exists_elsewhere(
                            binding_catalog,
                            local_ref=value,
                        )
                        else "functional.semantic_ref_unresolved"
                    )
                    add(
                        2,
                        location.scope_id,
                        location.step.step_id,
                        code,
                        path,
                        (
                            _scope_visibility_message(
                                binding_catalog,
                                local_ref=value,
                                step_scope_id=location.scope_id,
                                state_producing=_capability_produces_object_state(
                                    capability_catalog.get(
                                        location.step.capability_id
                                    )
                                ),
                            )
                            if code
                            == "functional.step_scope_visibility_drift"
                            else f"unknown input SemanticRef {value!r}"
                        ),
                    )
                elif answer_goal_ids:
                    capability = capability_catalog.get(
                        location.step.capability_id
                    )
                    argument = next(
                        (
                            item
                            for item in (
                                capability.args
                                if capability is not None
                                else ()
                            )
                            if item.name == arg_name
                        ),
                        None,
                    )
                    goal_view = goal_views.get(location.goal_ref or "")
                    target_ref = (
                        goal_view.goal_payload.get("target")
                        if goal_view is not None
                        else None
                    )
                    if value != location.goal_ref:
                        guidance = (
                            "the answer ref belongs to another Goal; use a "
                            "visible Problem input or an earlier step result"
                        )
                    elif (
                        argument is not None
                        and argument.input_view_mode == "identity"
                        and isinstance(target_ref, str)
                    ):
                        guidance = (
                            f"use this Goal's target_ref {target_ref!r}; "
                            "automatic canonicalization was unsafe because "
                            "there was not exactly one visible, type-compatible "
                            "input binding for the same object"
                        )
                    else:
                        guidance = (
                            "answer authority is not a computed input; use a "
                            "visible Problem input or an earlier step result"
                        )
                    add(
                        2,
                        location.scope_id,
                        location.step.step_id,
                        "functional.answer_ref_used_as_input",
                        path,
                        f"Goal answer ref {value!r} cannot be used as input; {guidance}",
                    )
                elif binding is not None and (
                    binding.semantic_ref.kind == "fact"
                    and declared_args.get(arg_name) is not None
                    and declared_args[arg_name].accepted_condition_kinds
                    and binding.semantic_ref.value_type
                    not in declared_args[arg_name].accepted_condition_kinds
                ):
                    accepted = sorted(
                        declared_args[arg_name].accepted_condition_kinds
                    )
                    add(
                        0,
                        location.scope_id,
                        location.step.step_id,
                        "functional.step_contract_invalid",
                        path,
                        (
                            f"Fact ref {value!r} has kind "
                            f"{binding.semantic_ref.value_type!r}; argument "
                            f"{arg_name!r} accepts {accepted!r}"
                        ),
                    )

    deduplicated: dict[tuple[str, str, str], tuple[tuple[Any, ...], ScopedFunctionalPlanIssue]] = {}
    for key, issue in records:
        deduplicated.setdefault((issue.code, issue.path, issue.message), (key, issue))
    return tuple(
        issue
        for _key, issue in sorted(
            deduplicated.values(),
            key=lambda item: item[0],
        )
    )


def _audit_step_contract(step: ScopedFunctionalStep, capability: Any) -> None:
    args = {item.name: item for item in capability.args}
    unknown = sorted(set(step.args) - set(args))
    missing = sorted(
        name for name, item in args.items() if item.required and name not in step.args
    )
    contract_details = {
        "capability_id": step.capability_id,
        "expected_allowed_args": tuple(sorted(args)),
        "expected_required_args": tuple(
            sorted(name for name, item in args.items() if item.required)
        ),
        "observed_args": tuple(sorted(step.args)),
        "observed_unknown_args": tuple(unknown),
        "observed_missing_required_args": tuple(missing),
        "retryability": "planner_repairable",
    }
    if unknown:
        raise _error(
            "functional.step_contract_invalid",
            f"$.steps[{step.step_id!r}].args",
            f"unknown capability args: {unknown}",
            details={
                **contract_details,
                "arg_name": unknown[0],
                "repair_action": (
                    "repair_capability_arguments"
                    if missing
                    else "remove_unknown_capability_arg"
                ),
            },
        )
    if missing:
        raise _error(
            "functional.step_contract_invalid",
            f"$.steps[{step.step_id!r}].args",
            f"missing required capability args: {missing}",
            details={
                **contract_details,
                "arg_name": missing[0],
                "repair_action": "provide_required_input",
            },
        )
    for name, values in step.args.items():
        cardinality = args[name].cardinality
        if cardinality == "one" and len(values) != 1:
            raise _error(
                "functional.step_contract_invalid",
                f"$.steps[{step.step_id!r}].args[{name!r}]",
                "argument requires exactly one value",
                details={
                    **contract_details,
                    "arg_name": name,
                    "expected_cardinality": "one",
                    "observed_count": len(values),
                    "repair_action": "repair_input_binding",
                },
            )
    returns = {item.name: item for item in capability.returns}
    for role, form in step.return_expectations.items():
        returned = returns.get(role)
        if returned is None or form not in returned.possible_forms:
            raise _error(
                "functional.step_contract_invalid",
                f"$.steps[{step.step_id!r}].return_expectations[{role!r}]",
                "return expectation is not declared by the capability",
            )


def _audit_return_role(
    step: ScopedFunctionalStep,
    return_name: str,
    catalog: FunctionalCapabilityCatalog,
    *,
    path: str,
) -> None:
    capability = catalog.get(step.capability_id)
    if capability is None or return_name not in {
        item.name for item in capability.returns
    }:
        expected_roles = (
            [
                item.name
                for item in capability.returns
                if item.binding_mode != "internal_only"
            ]
            if capability is not None
            else []
        )
        raise _error(
            "functional.step_ref_unresolved",
            path,
            f"step {step.step_id!r} does not declare return {return_name!r}",
            details={
                "capability_id": step.capability_id,
                "observed_role": return_name,
                "expected_roles": expected_roles,
                "retryability": "planner_repairable",
                "repair_action": "repair_return_role",
            },
        )


def _goal_answer_sources(
    plan: ScopedFunctionalPlan,
) -> dict[str, tuple[str, str]]:
    return {
        goal.goal_ref: (
            goal.answer_from.step_id,
            goal.answer_from.return_name,
        )
        for scope in _iter_scopes(plan.root_scope)
        for goal in scope.goals
    }


def _published_dependency_valid(
    ref: ScopedPublishedGoalResultRef,
    producer: _StepLocation,
    answer_sources: Mapping[str, tuple[str, str]],
) -> bool:
    return answer_sources.get(ref.published_goal_ref) == (
        producer.step.step_id,
        ref.return_name,
    )


def _audit_explicit_dependency(
    producer: _StepLocation,
    consumer: _StepLocation,
    *,
    ref: ScopedStepResultRef,
    published_answer_sources: Mapping[str, tuple[str, str]],
    scope_parents: Mapping[str, str | None],
) -> None:
    if isinstance(ref, ScopedPublishedGoalResultRef):
        if _published_dependency_valid(ref, producer, published_answer_sources):
            return
        raise _error(
            "functional.published_goal_result_invalid",
            f"$.steps[{consumer.step.step_id!r}]",
            "published Goal ref is not that Goal's exact final answer source",
        )
    if producer.goal_ref is not None and producer.goal_ref != consumer.goal_ref:
        raise _error(
            "functional.step_scope_visibility_drift",
            f"$.steps[{consumer.step.step_id!r}]",
            "a Goal-owned result cannot be read outside that Goal",
        )
    if producer.goal_ref is None and not _scope_visible(
        producer.scope_id,
        consumer.scope_id,
        scope_parents,
    ):
        raise _error(
            "functional.step_scope_visibility_drift",
            f"$.steps[{consumer.step.step_id!r}]",
            "step result crosses sibling or descendant scope authority",
        )


def _audit_answer_producer_visibility(
    producer: _StepLocation,
    *,
    goal_scope_id: str,
    goal_ref: str,
    scope_parents: Mapping[str, str | None],
) -> None:
    if producer.goal_ref is not None and producer.goal_ref != goal_ref:
        raise _error(
            "functional.answer_producer_invalid",
            f"$.goals[{goal_ref!r}].answer_from",
            "Goal cannot use another Goal's private step as answer producer",
        )
    if producer.goal_ref is None and not _scope_visible(
        producer.scope_id,
        goal_scope_id,
        scope_parents,
    ):
        raise _error(
            "functional.answer_producer_invalid",
            f"$.goals[{goal_ref!r}].answer_from",
            "answer producer is outside the Goal's visible scope path",
        )


def _input_binding(
    catalog: ProblemPlanningBindingCatalog,
    semantic_ref: str,
    *,
    scope_id: str,
    goal_unit_ids: Sequence[str] = (),
    path: str,
) -> Any:
    answer_matches = tuple(
        binding
        for binding in catalog.bindings.values()
        if binding.usage == "answer"
        and binding.semantic_ref.ref == semantic_ref
        and (
            not goal_unit_ids
            or set(goal_unit_ids).issubset(binding.visible_goal_unit_ids)
        )
    )
    if answer_matches:
        raise _error(
            "functional.answer_ref_used_as_input",
            path,
            f"Goal answer ref {semantic_ref!r} cannot be used as input",
        )
    try:
        binding = catalog.resolve_input_binding(
            scope_id=scope_id,
            local_ref=semantic_ref,
            goal_unit_ids=goal_unit_ids,
        )
    except ProblemPlanningBindingError:
        exists_elsewhere = _input_ref_exists_elsewhere(
            catalog,
            local_ref=semantic_ref,
        )
        raise _error(
            (
                "functional.step_scope_visibility_drift"
                if exists_elsewhere
                else "functional.semantic_ref_unresolved"
            ),
            path,
            (
                _scope_visibility_message(
                    catalog,
                    local_ref=semantic_ref,
                    step_scope_id=scope_id,
                )
                if exists_elsewhere
                else f"unknown input SemanticRef {semantic_ref!r}"
            ),
        )
    return binding


def _has_visible_input_binding(
    catalog: ProblemPlanningBindingCatalog,
    *,
    scope_id: str,
    local_ref: str,
) -> bool:
    try:
        catalog.resolve_input_binding(
            scope_id=scope_id,
            local_ref=local_ref,
        )
    except ProblemPlanningBindingError:
        return False
    return True


def _input_ref_exists_elsewhere(
    catalog: ProblemPlanningBindingCatalog,
    *,
    local_ref: str,
) -> bool:
    return any(
        binding.usage == "input"
        and binding.semantic_ref.ref == local_ref
        for binding in catalog.bindings.values()
    )


def _input_ref_owner_scopes(
    catalog: ProblemPlanningBindingCatalog,
    *,
    local_ref: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                binding.owner_scope_id
                for binding in catalog.bindings.values()
                if binding.usage == "input"
                and binding.semantic_ref.ref == local_ref
            }
        )
    )


def _visible_compatible_output_target_refs(
    catalog: ProblemPlanningBindingCatalog,
    *,
    scope_id: str,
    runtime_type: str,
    scope_parents: Mapping[str, str | None],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                binding.semantic_ref.ref
                for binding in catalog.bindings.values()
                if binding.usage == "input"
                and _scope_visible(
                    binding.owner_scope_id,
                    scope_id,
                    scope_parents,
                )
                and _binding_accepts_runtime_type(binding, runtime_type)
            }
        )
    )


def _capability_produces_object_state(capability: Any | None) -> bool:
    return capability is not None and any(
        item.identity_policy == "preserve_input_object"
        for item in capability.returns
    )


def _scope_visibility_message(
    catalog: ProblemPlanningBindingCatalog,
    *,
    local_ref: str,
    step_scope_id: str,
    state_producing: bool = False,
) -> str:
    owner_scopes = _input_ref_owner_scopes(
        catalog,
        local_ref=local_ref,
    )
    message = (
        f"SemanticRef {local_ref!r} is outside step scope "
        f"{step_scope_id!r}; candidate owner scopes: "
        f"{list(owner_scopes)!r}"
    )
    if state_producing:
        message += (
            "; shared MathObject identity does not share scope-local state "
            "or StateVersion; place the state-producing step in the scope "
            "whose local constraints it consumes"
        )
    return message


def _answer_existing_object_refs(
    goal_unit_id: str,
    *,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> tuple[str, ...]:
    try:
        answer = binding_catalog.answer_binding_for_goal(goal_unit_id)
    except ProblemPlanningBindingError:
        return ()
    object_ids = _binding_math_object_ids(answer)
    if not object_ids:
        return ()
    return tuple(
        sorted(
            binding.semantic_ref.ref
            for binding in binding_catalog.bindings.values()
            if binding.usage == "input"
            and binding.semantic_ref.kind != "fact"
            and goal_unit_id in binding.visible_goal_unit_ids
            and bool(_binding_math_object_ids(binding) & object_ids)
        )
    )


def _goal_target_input_ref_candidates(
    location: _StepLocation,
    *,
    goal_view: Any,
    argument: Any,
    binding_catalog: ProblemPlanningBindingCatalog,
    scope_parents: Mapping[str, str | None],
) -> tuple[str, ...]:
    """Prove one Goal answer ref is the same visible Problem object input."""

    try:
        answer = binding_catalog.answer_binding_for_goal(
            goal_view.goal_unit_id
        )
    except ProblemPlanningBindingError:
        return ()
    answer_object_ids = _binding_math_object_ids(answer)
    if len(answer_object_ids) != 1:
        return ()
    target_ref = goal_view.goal_payload.get("target")
    if not isinstance(target_ref, str):
        return ()
    candidates = {
        binding.semantic_ref.ref
        for binding in binding_catalog.bindings.values()
        if binding.usage == "input"
        and binding.semantic_ref.kind != "fact"
        and goal_view.goal_unit_id in binding.visible_goal_unit_ids
        and _scope_visible(
            binding.owner_scope_id,
            location.scope_id,
            scope_parents,
        )
        and _binding_math_object_ids(binding) == answer_object_ids
        and _binding_accepts_arg(binding, argument)
    }
    if target_ref not in candidates:
        return ()
    return tuple(sorted(candidates))


def _binding_math_object_ids(binding: Any) -> frozenset[Any]:
    return frozenset(
        source.math_object_id
        for source in binding.typed_sources
        if source.math_object_id is not None
    )


def _runtime_input_ref(ref: SemanticRef) -> SemanticRef:
    """Lower source authority without leaking source-semantic fact types.

    F5-B fact ``value_type`` names the source primitive (for example
    ``angle_sum``), while the v1 reconciler interprets this field as a runtime
    type (for example ``Condition``). F5-C already pins the exact typed source,
    so the adapter carries only the authoritative ref/kind pair here.
    """

    return SemanticRef(ref=ref.ref, kind=ref.kind)


def _answer_object_refs_by_return(
    plan: ScopedFunctionalPlan,
    *,
    goal_views: Mapping[str, Any],
    binding_catalog: ProblemPlanningBindingCatalog,
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Map authored Goal returns to their existing Problem object refs."""

    result: dict[tuple[str, str], tuple[str, ...]] = {}
    for scope in _iter_scopes(plan.root_scope):
        for goal in scope.goals:
            view = goal_views.get(goal.goal_ref)
            if view is None:
                continue
            refs = _answer_existing_object_refs(
                view.goal_unit_id,
                binding_catalog=binding_catalog,
            )
            if refs:
                result[(
                    goal.answer_from.step_id,
                    goal.answer_from.return_name,
                )] = refs
    return result


def _entity_state_producers(
    locations: Sequence[_StepLocation],
    *,
    by_id: Mapping[str, _StepLocation],
    capability_catalog: FunctionalCapabilityCatalog,
    answer_object_refs: Mapping[tuple[str, str], tuple[str, ...]],
    binding_catalog: ProblemPlanningBindingCatalog,
) -> dict[Any, tuple[tuple[_StepLocation, str, str], ...]]:
    """Index named Math Entity state writers without rewriting the LLM wire."""

    indexed: dict[
        Any,
        dict[tuple[str, str], tuple[_StepLocation, str, str]],
    ] = {}
    for location in locations:
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        for returned in capability.returns:
            targets = _return_object_target_refs(
                location,
                returned=returned,
                by_id=by_id,
                capability_catalog=capability_catalog,
                answer_object_refs=answer_object_refs,
                binding_catalog=binding_catalog,
            )
            for target in targets:
                try:
                    binding = binding_catalog.resolve_input_binding(
                        scope_id=location.scope_id,
                        local_ref=target,
                    )
                except ProblemPlanningBindingError:
                    continue
                for object_id in _binding_math_object_ids(binding):
                    indexed.setdefault(object_id, {})[
                        (location.step.step_id, returned.name)
                    ] = (
                        location,
                        returned.name,
                        returned.runtime_type,
                    )
    return {
        object_id: tuple(
            sorted(
                producers.values(),
                key=lambda item: (item[0].order, item[1]),
            )
        )
        for object_id, producers in indexed.items()
    }


def scoped_entity_state_dependencies(
    plan: ScopedFunctionalPlan,
    *,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
) -> dict[str, tuple[str, ...]]:
    """Derive named-entity latest-state edges from the complete Plan."""

    locations = _step_locations(plan)
    by_id = _unique_steps(locations)
    goal_views = {
        item.answer_ref.ref: item for item in planning_context.goal_views
    }
    scope_parents = {
        item.scope_id: item.parent_scope_id
        for item in planning_context.scopes
    }
    answer_object_refs = _answer_object_refs_by_return(
        plan,
        goal_views=goal_views,
        binding_catalog=binding_catalog,
    )
    producers_by_target = _entity_state_producers(
        locations,
        by_id=by_id,
        capability_catalog=capability_catalog,
        answer_object_refs=answer_object_refs,
        binding_catalog=binding_catalog,
    )
    dependencies: dict[str, set[str]] = {
        item.step.step_id: set() for item in locations
    }
    for location in locations:
        capability = capability_catalog.get(location.step.capability_id)
        if capability is None:
            continue
        arguments = {item.name: item for item in capability.args}
        for arg_name, values in location.step.args.items():
            argument = arguments.get(arg_name)
            if argument is None or argument.input_view_mode != "latest_state":
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                try:
                    binding = _input_binding(
                        binding_catalog,
                        value,
                        scope_id=location.scope_id,
                        goal_unit_ids=(
                            (goal_views[location.goal_ref].goal_unit_id,)
                            if location.goal_ref in goal_views
                            else ()
                        ),
                        path=_arg_path(location, arg_name),
                    )
                except ScopedFunctionalPlanError:
                    continue
                object_ids = _binding_math_object_ids(binding)
                if len(object_ids) != 1:
                    continue
                producer = _nearest_target_producer(
                    next(iter(object_ids)),
                    location,
                    producers_by_target,
                    argument=argument,
                    scope_parents=scope_parents,
                    capability_catalog=capability_catalog,
                    binding_catalog=binding_catalog,
                    by_id=by_id,
                    dependencies=dependencies,
                )
                if producer is not None:
                    dependencies[location.step.step_id].add(
                        producer[0].step.step_id
                    )
    return {
        step_id: tuple(sorted(values))
        for step_id, values in sorted(dependencies.items())
        if values
    }


def _nearest_target_producer(
    object_id: Any,
    consumer: _StepLocation,
    producers_by_target: Mapping[
        Any,
        Sequence[tuple[_StepLocation, str, str]],
    ],
    *,
    argument: Any,
    scope_parents: Mapping[str, str | None],
    capability_catalog: FunctionalCapabilityCatalog,
    binding_catalog: ProblemPlanningBindingCatalog,
    by_id: Mapping[str, _StepLocation],
    dependencies: Mapping[str, set[str]],
) -> tuple[_StepLocation, str] | None:
    accepted = argument.accepted_item_types or (argument.runtime_type,)
    visible = [
        (item, return_name)
        for item, return_name, runtime_type in producers_by_target.get(
            object_id,
            (),
        )
        if item.order < consumer.order
        and any(
            runtime_type_compatible(expected, runtime_type)
            for expected in accepted
        )
        and (
            item.goal_ref == consumer.goal_ref
            if item.goal_ref is not None
            else _scope_visible(
                item.scope_id,
                consumer.scope_id,
                scope_parents,
            )
        )
    ]
    if visible:
        # A scope path plus plan order is a total state sequence. Runtime still
        # executes every retained writer and is the only authority allowed to
        # merge equivalent states.
        return max(visible, key=lambda item: item[0].order)
    # Scope-local state never migrates across sibling branches. A state that
    # should be shared must be produced in an already visible ancestor scope.
    return None


def _propagate_goal_consumers(
    locations: Sequence[_StepLocation],
    dependencies: Mapping[str, set[str]],
    seeds: Mapping[str, set[str]],
    *,
    non_propagating_dependencies: set[tuple[str, str]] | None = None,
) -> dict[str, set[str]]:
    non_propagating_dependencies = non_propagating_dependencies or set()
    result = {step_id: set(values) for step_id, values in seeds.items()}
    changed = True
    while changed:
        changed = False
        for consumer in reversed(locations):
            consumer_goals = result[consumer.step.step_id]
            for producer_id in dependencies[consumer.step.step_id]:
                if (
                    consumer.step.step_id,
                    producer_id,
                ) in non_propagating_dependencies:
                    continue
                before = len(result[producer_id])
                result[producer_id].update(consumer_goals)
                changed = changed or len(result[producer_id]) != before
    return result


def _semantic_owner_scopes(
    locations: Sequence[_StepLocation],
    *,
    consumer_goals: Mapping[str, set[str]],
    dependencies: Mapping[str, set[str]],
    lowered_args: Mapping[
        str,
        Mapping[str, tuple[str | ScopedStepResultRef, ...]],
    ],
    answer_target_refs: Mapping[str, set[str]],
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
    capability_catalog: FunctionalCapabilityCatalog,
    scope_parents: Mapping[str, str | None],
) -> dict[str, str]:
    # FunctionalPlan v2 uses the authored scope tree as its only sharing
    # mechanism. A step is never moved across scope boundaries while lowering:
    # shared work must already live in the nearest common ancestor's
    # ``scope.steps``. B2 may later choose a compatible execution scope, but it
    # cannot rewrite the authored semantic owner or merge branch-local steps.
    del (
        consumer_goals,
        dependencies,
        lowered_args,
        answer_target_refs,
        planning_context,
        binding_catalog,
        capability_catalog,
        scope_parents,
    )
    return {
        location.step.step_id: location.scope_id for location in locations
    }


def _scope_placement_is_safe(
    location: _StepLocation,
    *,
    candidate_scope_id: str,
    dependencies: Mapping[str, set[str]],
    dependency_owners: Mapping[str, str],
    lowered_args: Mapping[str, tuple[str | ScopedStepResultRef, ...]],
    answer_target_refs: set[str],
    binding_catalog: ProblemPlanningBindingCatalog,
    scope_parents: Mapping[str, str | None],
) -> bool:
    for values in lowered_args.values():
        for value in values:
            if isinstance(value, ScopedStepResultRef):
                producer_owner = dependency_owners.get(value.step_id)
                if producer_owner is None or not _scope_visible(
                    producer_owner,
                    candidate_scope_id,
                    scope_parents,
                ):
                    return False
                continue
            try:
                binding_catalog.resolve_input_binding(
                    scope_id=candidate_scope_id,
                    local_ref=value,
                )
            except ProblemPlanningBindingError:
                return False
    for producer_id in dependencies[location.step.step_id]:
        producer_owner = dependency_owners.get(producer_id)
        if producer_owner is None or not _scope_visible(
            producer_owner,
            candidate_scope_id,
            scope_parents,
        ):
            return False
    for target in (
        *location.step.output_targets.values(),
        *answer_target_refs,
    ):
        try:
            binding = binding_catalog.resolve_input_binding(
                scope_id=candidate_scope_id,
                local_ref=target,
            )
        except ProblemPlanningBindingError:
            return False
        if not _scope_visible(
            binding.owner_scope_id,
            candidate_scope_id,
            scope_parents,
        ):
            return False
    return True


def _lowest_common_ancestor(
    scope_ids: Sequence[str],
    parents: Mapping[str, str | None],
) -> str:
    paths = [_scope_path(scope_id, parents) for scope_id in scope_ids]
    result = paths[0][0]
    for level in zip(*paths, strict=False):
        if len(set(level)) != 1:
            break
        result = level[0]
    return result


def _scope_path(
    scope_id: str,
    parents: Mapping[str, str | None],
) -> tuple[str, ...]:
    result: list[str] = []
    cursor: str | None = scope_id
    while cursor is not None:
        result.append(cursor)
        cursor = parents.get(cursor)
    return tuple(reversed(result))


def _has_potential_later_consumer(
    producer: _StepLocation,
    locations: Sequence[_StepLocation],
    *,
    scope_parents: Mapping[str, str | None],
) -> bool:
    for consumer in locations:
        if consumer.order <= producer.order:
            continue
        if producer.goal_ref is not None:
            if consumer.goal_ref == producer.goal_ref:
                return True
            continue
        if _scope_visible(
            producer.scope_id,
            consumer.scope_id,
            scope_parents,
        ):
            return True
    return False


def _audit_return_bindings(
    step: ScopedFunctionalStep,
    capability: Any,
    *,
    return_bindings: Mapping[str, Any],
    binding_catalog: ProblemPlanningBindingCatalog,
    scope_id: str,
    goal_unit_ids: Sequence[str],
) -> None:
    returns = {item.name: item for item in capability.returns}
    for name, target in step.output_targets.items():
        returned = returns.get(name)
        if returned is None or returned.binding_mode == "internal_only":
            raise _error(
                "functional.output_target_invalid",
                f"$.steps[{step.step_id!r}].output_targets[{name!r}]",
                "return cannot target an external Problem object",
            )
        binding = _input_binding(
            binding_catalog,
            target,
            scope_id=scope_id,
            goal_unit_ids=goal_unit_ids,
            path=f"$.steps[{step.step_id!r}].output_targets[{name!r}]",
        )
        actual_types = _binding_runtime_types(binding)
        returned_domain_type = planner_input_domain_type(
            returned.runtime_type
        )
        if actual_types and not any(
            runtime_type_compatible(returned.runtime_type, actual)
            or actual == returned_domain_type
            for actual in actual_types
        ):
            raise _error(
                "functional.output_target_invalid",
                f"$.steps[{step.step_id!r}].output_targets[{name!r}]",
                "output target type differs from the capability return",
            )
    for returned in capability.returns:
        if (
            returned.required
            and returned.binding_mode
            == "explicit_answer_or_existing_object"
            and returned.name not in return_bindings
        ):
            raise _error(
                "functional.output_target_invalid",
                f"$.steps[{step.step_id!r}].output_targets",
                f"return {returned.name!r} requires an external target",
            )


def _scope_visible(
    owner_scope_id: str,
    consumer_scope_id: str,
    parents: Mapping[str, str | None],
) -> bool:
    cursor: str | None = consumer_scope_id
    while cursor is not None:
        if cursor == owner_scope_id:
            return True
        cursor = parents.get(cursor)
    return False


def _goal_owner(goal_id: str, context: ProblemPlanningContext) -> str:
    for goal in context.goal_views:
        if goal.goal_unit_id == goal_id:
            return goal.owner_scope_id
    raise _error(
        "planner.problem_revision_drift",
        "$.goal_views",
        f"unknown Goal authority {goal_id!r}",
        retryable=False,
    )


def _scope_label(scope_id: str, context: ProblemPlanningContext) -> str:
    for scope in context.scopes:
        if scope.scope_id == scope_id:
            return scope.label
    raise _error(
        "planner.problem_revision_drift",
        "$.scopes",
        f"unknown scope authority {scope_id!r}",
        retryable=False,
    )


def _semantic_plan_payload(plan: ScopedFunctionalPlan) -> dict[str, Any]:
    def step_payload(step: ScopedFunctionalStep) -> dict[str, Any]:
        payload = step.to_payload()
        payload["args"] = {
            name: (
                encoded[0]
                if len(encoded := [
                    _scoped_ref_authority_payload(value) for value in values
                ]) == 1
                else encoded
            )
            for name, values in step.args.items()
        }
        payload.pop("intent", None)
        return payload

    def scope_payload(scope: ScopedFunctionalScope) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": scope.scope_ref}
        if scope.steps:
            payload["steps"] = [step_payload(item) for item in scope.steps]
        if scope.goals:
            payload["goals"] = [
                {
                    "goal_ref": goal.goal_ref,
                    **(
                        {"steps": [step_payload(item) for item in goal.steps]}
                        if goal.steps
                        else {}
                    ),
                    "answer_from": goal.answer_from.to_payload(),
                }
                for goal in sorted(scope.goals, key=lambda item: item.goal_ref)
            ]
        if scope.children:
            payload["children"] = [
                scope_payload(item)
                for item in sorted(scope.children, key=lambda item: item.scope_ref)
            ]
        return payload

    return {
        "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
        "root_scope": scope_payload(plan.root_scope),
    }


def _arg_path(location: _StepLocation, arg_name: str) -> str:
    return f"$.steps[{location.step.step_id!r}].args[{arg_name!r}]"


def _json_path(parts: Sequence[Any]) -> str:
    result = "$"
    for item in parts:
        result += f"[{item}]" if isinstance(item, int) else f".{item}"
    return result


def _error(
    code: str,
    path: str,
    message: str,
    *,
    retryable: bool = True,
    issues: tuple[ScopedFunctionalPlanIssue, ...] = (),
    normalizations: tuple[ScopedFunctionalPlanNormalization, ...] = (),
    details: Mapping[str, Any] | None = None,
) -> ScopedFunctionalPlanError:
    return ScopedFunctionalPlanError(
        code,
        path,
        message,
        retryable=retryable,
        issues=issues,
        normalizations=normalizations,
        details=details,
    )


__all__ = [
    "SCOPED_FUNCTIONAL_PLAN_CONTRACT",
    "SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH",
    "FunctionalStepScopeAuthority",
    "ScopedFunctionalAnswerSource",
    "ScopedFunctionalGoalPlan",
    "ScopedFunctionalPlan",
    "ScopedFunctionalPlanAuthority",
    "ScopedFunctionalPlanAuthorityReport",
    "ScopedFunctionalPlanAuthorityAdapter",
    "ScopedFunctionalPlanError",
    "ScopedFunctionalPlanIssue",
    "ScopedFunctionalPlanNormalization",
    "ScopedFunctionalStructureReport",
    "ScopedFunctionalPlanValidationReport",
    "ScopedFunctionalPlanValidator",
    "ScopedFunctionalScope",
    "ScopedFunctionalStep",
    "ScopedPublishedGoalBinding",
    "ScopedPublishedGoalResultRef",
    "ScopedStepResultRef",
    "apply_scoped_published_goal_bindings",
    "audit_scoped_functional_structure",
    "audit_scoped_functional_structure_prompt_payload",
    "normalize_unique_scoped_goal_refs",
    "scoped_functional_plan_authority_payload",
    "scoped_published_goal_bindings",
    "scoped_functional_plan_schema",
]
