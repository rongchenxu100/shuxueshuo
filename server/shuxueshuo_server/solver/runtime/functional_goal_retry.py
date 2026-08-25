"""Goal-scoped replacement authority for FunctionalPlan v2 retries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingError,
    ProblemPlanningBindingCatalog,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionCheckpoint,
    FunctionalGoalExecutionCheckpointError,
    FunctionalGoalExecutionGoal,
    FunctionalGoalExecutionScope,
    FunctionalGoalExecutionStep,
    ScopedFunctionalGoalExecutionResult,
    VerifiedFunctionalPlanExecution,
    _internal_prompt_values,
    _prompt_safe_value,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
    family_capability_bundle_for_inputs,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalFinalPlanContractValidation,
    FunctionalGoalAnswerBindingError,
    FunctionalGoalAnswerRequirement,
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContent,
    FunctionalPlanContentCompiler,
    FunctionalPlanContentNormalization,
    capability_bound_step_schema,
    capability_bound_base_step_schema,
    decode_single_json_object,
    derive_goal_answer_bindings,
    functional_plan_content_from_plan,
    normalize_empty_optional_capability_args,
    normalize_empty_optional_step_maps,
    normalize_interchangeable_capability_args,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalRestoredCallSeed,
    FunctionalRestoredCallBindingError,
    functional_restored_call_authority_signatures,
)
from shuxueshuo_server.solver.runtime.macro_plan_materialization import (
    rebase_macro_expansion_records,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedPublishedGoalBinding,
    ScopedFunctionalPlan,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanIssue,
    ScopedFunctionalPlanValidationReport,
    ScopedFunctionalPlanValidator,
    ScopedFunctionalScope,
    apply_scoped_published_goal_bindings,
    scoped_functional_plan_id,
    scoped_published_goal_bindings,
    scoped_functional_plan_schema,
)
FUNCTIONAL_GOAL_REPAIR_CONTRACT = "functional-goal-repair/v5"
PLANNER_GOAL_RETRY_CONTEXT_CONTRACT = "planner-goal-retry-context/v4"

GoalRetryStatus = Literal["solved", "failed", "blocked", "pending"]
ScopeRetryStatus = Literal["frozen", "editable", "open", "context"]
ScopeExecutionStatus = Literal[
    "context_only",
    "fully_verified",
    "authority_failed",
    "runtime_failed",
    "dependency_blocked",
    "awaiting_execution",
]
RepairPermission = Literal[
    "editable",
    "partially_editable",
    "answer_only",
    "frozen",
    "read_only",
    "context",
]


class FunctionalGoalRetryError(ValueError):
    """A retryable repair error or non-retryable authority drift."""

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
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }
        if self.details:
            payload["details"] = _thaw(self.details)
        return payload


def functional_goal_repair_schema() -> dict[str, Any]:
    """Return the strict full-Goal replacement response schema."""

    plan_defs = deepcopy(scoped_functional_plan_schema()["$defs"])
    nonempty = {"type": "string", "minLength": 1}
    published_ref = {
        "type": "object",
        "description": (
            "Read the final verified answer of one solved Goal. Intermediate "
            "step returns cannot be published across Goals."
        ),
        "required": ["published_goal_ref"],
        "properties": {"published_goal_ref": nonempty},
        "additionalProperties": False,
    }
    repair_ref = {
        "oneOf": [
            {"$ref": "#/$defs/source_ref"},
            {"$ref": "#/$defs/step_result_ref"},
            {"$ref": "#/$defs/published_goal_result_ref"},
        ]
    }
    repair_step = deepcopy(plan_defs["step"])
    repair_step["properties"]["step_id"]["description"] = (
        "A globally unique step id. This complete step object must be owned by "
        "exactly one goal_replacements.*.steps or "
        "scope_step_replacements.*.steps container."
    )
    repair_step["properties"]["args"] = {
        "type": "object",
        "additionalProperties": {
            "oneOf": [
                {"$ref": "#/$defs/repair_functional_ref"},
                {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/repair_functional_ref"},
                },
            ]
        },
    }
    goal_replacement = {
        "type": "object",
        "required": ["steps", "answer_from"],
        "properties": {
            "steps": {
                "type": "array",
                "description": (
                    "Complete Goal-local replacement steps used only for this "
                    "Goal answer. Do not copy Scope-owned steps here."
                ),
                "items": {"$ref": "#/$defs/repair_step"},
            },
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
    scope_replacement = {
        "type": "object",
        "required": ["steps"],
        "properties": {
            "steps": {
                "type": "array",
                "description": (
                    "Complete replacement for this Scope's editable step subset. "
                    "Do not repeat frozen steps; code preserves and merges them "
                    "from the authenticated previous Plan."
                ),
                "items": {"$ref": "#/$defs/repair_step"},
            },
        },
        "additionalProperties": False,
    }
    answer_binding_replacement = {
        "type": "object",
        "description": (
            "Replace only a blocked Goal's answer producer after an editable "
            "Scope replacement changed that producer. Goal-local steps remain "
            "read-only."
        ),
        "required": ["answer_from"],
        "properties": {
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "functional-goal-repair.schema.json",
        "title": "Functional Goal Replacement Repair v5",
        "type": "object",
        "required": [
            "schema_version",
            "base_plan_id",
            "base_retry_context_id",
            "goal_replacements",
            "scope_step_replacements",
        ],
        "properties": {
            "schema_version": {"const": FUNCTIONAL_GOAL_REPAIR_CONTRACT},
            "base_plan_id": nonempty,
            "base_retry_context_id": nonempty,
            "goal_replacements": {
                "type": "object",
                "description": (
                    "Goal-owned replacement blocks. Their steps are local to "
                    "one Goal and mutually exclusive with Scope-owned steps."
                ),
                "additionalProperties": {
                    "$ref": "#/$defs/goal_replacement"
                },
            },
            "scope_step_replacements": {
                "type": "object",
                "description": (
                    "Scope-owned replacement blocks for the editable step ids "
                    "declared by retry authority. Frozen producers are omitted "
                    "and retained by code. Never repeat a frozen step in a "
                    "replacement."
                ),
                "additionalProperties": {
                    "$ref": "#/$defs/scope_step_replacement"
                },
            },
            "answer_binding_replacements": {
                "type": "object",
                "description": (
                    "Optional answer-only updates for the authority-listed "
                    "blocked Goals affected by an editable Scope. Never place "
                    "Goal steps here."
                ),
                "additionalProperties": {
                    "$ref": "#/$defs/answer_binding_replacement"
                },
            },
        },
        "anyOf": [
            {
                "properties": {
                    "goal_replacements": {"minProperties": 1},
                }
            },
            {
                "properties": {
                    "scope_step_replacements": {"minProperties": 1},
                }
            },
            {
                "required": ["answer_binding_replacements"],
                "properties": {
                    "answer_binding_replacements": {"minProperties": 1},
                },
            },
        ],
        "$defs": {
            "source_ref": plan_defs["source_ref"],
            "step_result_ref": plan_defs["step_result_ref"],
            "return_binding": plan_defs["return_binding"],
            "published_goal_result_ref": published_ref,
            "repair_functional_ref": repair_ref,
            "repair_step": repair_step,
            "answer_from": plan_defs["answer_from"],
            "goal_replacement": goal_replacement,
            "scope_step_replacement": scope_replacement,
            "answer_binding_replacement": answer_binding_replacement,
        },
        "additionalProperties": False,
    }


def functional_goal_repair_schema_for_authority(
    authority: FunctionalGoalRetryAuthority,
    *,
    capability_catalog: FunctionalCapabilityCatalog | None = None,
    authority_frame: FunctionalPlanAuthorityFrame | None = None,
) -> dict[str, Any]:
    """Bind the repair response schema to one exact retry authority."""

    schema = deepcopy(functional_goal_repair_schema())
    properties = schema["properties"]
    properties["base_plan_id"] = {"const": authority.base_plan_id}
    properties["base_retry_context_id"] = {
        "const": authority.retry_context_id
    }
    goal_refs = tuple(sorted(authority.editable_goal_refs))
    scope_refs = tuple(sorted(authority.editable_scope_refs))
    goal_map = properties["goal_replacements"]
    scope_map = properties["scope_step_replacements"]
    answer_map = properties["answer_binding_replacements"]
    prior_step_owners = authority.repair_step_owners
    published_goal_refs = tuple(
        sorted(item.goal_ref for item in authority.published_goal_results)
    )
    repair_ref_variants = schema["$defs"]["repair_functional_ref"]["oneOf"]
    if published_goal_refs:
        schema["$defs"]["published_goal_result_ref"]["properties"][
            "published_goal_ref"
        ] = {"enum": list(published_goal_refs)}
    else:
        schema["$defs"]["repair_functional_ref"]["oneOf"] = [
            item
            for item in repair_ref_variants
            if item.get("$ref")
            != "#/$defs/published_goal_result_ref"
        ]
    if capability_catalog is not None:
        schema["$defs"]["repair_step_base"] = (
            capability_bound_base_step_schema(
                schema["$defs"]["repair_step"]
            )
        )
        exact_result_ref: dict[str, Any]
        if published_goal_refs:
            exact_result_ref = {
                "oneOf": [
                    {"$ref": "#/$defs/source_ref"},
                    {"$ref": "#/$defs/step_result_ref"},
                    {"$ref": "#/$defs/published_goal_result_ref"},
                ]
            }
        else:
            exact_result_ref = {
                "oneOf": [
                    {"$ref": "#/$defs/source_ref"},
                    {"$ref": "#/$defs/step_result_ref"},
                ]
            }
        schema["$defs"]["repair_step"] = capability_bound_step_schema(
            base_step_ref="#/$defs/repair_step_base",
            capability_catalog=capability_catalog,
            source_ref_schema={"$ref": "#/$defs/source_ref"},
            exact_result_ref_schema=exact_result_ref,
            authority_frame=authority_frame,
        )
    goal_map.update(
        {
            "required": list(goal_refs),
            "properties": {
                goal_ref: _owned_replacement_schema(
                    definition="goal_replacement",
                    owner_key=f"goal:{goal_ref}",
                    prior_step_owners=prior_step_owners,
                )
                for goal_ref in goal_refs
            },
            "additionalProperties": False,
        }
    )
    scope_map.update(
        {
            "required": list(scope_refs),
            "properties": {
                scope_ref: _owned_replacement_schema(
                    definition="scope_step_replacement",
                    owner_key=f"scope:{scope_ref}",
                    prior_step_owners=prior_step_owners,
                    reusable_step_ids=authority.editable_scope_step_ids.get(
                        scope_ref,
                        (),
                    ),
                )
                for scope_ref in scope_refs
            },
            "additionalProperties": False,
        }
    )
    answer_refs = tuple(sorted(authority.editable_answer_goal_refs))
    answer_map.update(
        {
            "properties": {
                goal_ref: {"$ref": "#/$defs/answer_binding_replacement"}
                for goal_ref in answer_refs
            },
            "additionalProperties": False,
        }
    )
    return schema


def _owned_replacement_schema(
    *,
    definition: str,
    owner_key: str,
    prior_step_owners: Mapping[str, str],
    reusable_step_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    all_owned = tuple(
        sorted(
            step_id
            for step_id, owner in prior_step_owners.items()
            if owner == owner_key
        )
    )
    owned = (
        all_owned
        if reusable_step_ids is None
        else tuple(sorted(set(reusable_step_ids)))
    )
    foreign = tuple(
        sorted(
            step_id
            for step_id, owner in prior_step_owners.items()
            if owner != owner_key or step_id not in owned
        )
    )
    step_id_schema: dict[str, Any] = {
        "type": "string",
        "minLength": 1,
        "description": (
            f"Prior step_ids owned by {owner_key}: {list(owned)}. "
            "Only these editable ids may be reused here; frozen ids are "
            "retained by code. Otherwise choose a new globally "
            "unique step_id. Never copy a prior step_id from another Goal "
            "or scope replacement."
        ),
    }
    if foreign:
        step_id_schema["not"] = {"enum": list(foreign)}
    return {
        "allOf": [
            {"$ref": f"#/$defs/{definition}"},
            {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "allOf": [
                                {"$ref": "#/$defs/repair_step"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "step_id": step_id_schema,
                                    },
                                },
                            ]
                        },
                    },
                },
            },
        ]
    }


def planner_goal_retry_context_schema() -> dict[str, Any]:
    """Return the prompt-safe scope/Goal execution authority schema."""

    nonempty = {"type": "string", "minLength": 1}
    execution_step = {
        "type": "object",
        "required": ["step_id", "status", "repair_permission"],
        "properties": {
            "step_id": nonempty,
            "status": {
                "enum": [
                    "valid",
                    "authority_invalid",
                    "ready",
                    "runtime_verified",
                    "runtime_failed",
                    "blocked_by_dependency",
                    "pruned_dead",
                ]
            },
            "repair_permission": {
                "enum": ["editable", "frozen", "read_only"]
            },
            "repair_reason": nonempty,
            "resolved_inputs": {"type": "array", "items": {"type": "object"}},
            "actual_outputs": {"type": "array", "items": {"type": "object"}},
            "typed_issue": {"type": "object"},
            "blocked_by": {"type": "array", "items": nonempty},
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "repair_permission": {"const": "editable"}
                    },
                    "required": ["repair_permission"],
                },
                "else": {"required": ["repair_reason"]},
            }
        ],
        "additionalProperties": False,
    }
    goal = {
        "type": "object",
        "required": [
            "goal_ref",
            "status",
            "editable",
            "repair_permission",
            "required_answer",
        ],
        "properties": {
            "goal_ref": nonempty,
            "status": {"enum": ["solved", "failed", "blocked", "pending"]},
            "editable": {"type": "boolean"},
            "repair_permission": {
                "enum": ["editable", "answer_only", "frozen", "read_only"]
            },
            "repair_reason": nonempty,
            "required_answer": {
                "type": "object",
                "required": [
                    "target_ref",
                    "answer_type",
                ],
                "properties": {
                    "target_ref": nonempty,
                    "answer_type": nonempty,
                },
                "additionalProperties": False,
            },
            "steps": {"type": "array", "items": {"$ref": "#/$defs/step"}},
            "issues": {"type": "array", "items": {"type": "object"}},
            "answer_binding_editable": {"const": True},
            "current_answer_from": {
                "type": "object",
                "required": ["step_id", "return"],
                "properties": {
                    "step_id": nonempty,
                    "return": nonempty,
                },
                "additionalProperties": False,
            },
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "repair_permission": {"const": "editable"}
                    },
                    "required": ["repair_permission"],
                },
                "else": {"required": ["repair_reason"]},
            }
        ],
        "additionalProperties": False,
    }
    scope_defs: dict[str, Any] = {}
    for level in range(4):
        properties: dict[str, Any] = {
            "scope_ref": nonempty,
            "execution_status": {
                "enum": [
                    "context_only",
                    "fully_verified",
                    "authority_failed",
                    "runtime_failed",
                    "dependency_blocked",
                    "awaiting_execution",
                ]
            },
            "repair_permission": {
                "enum": [
                    "editable",
                    "partially_editable",
                    "frozen",
                    "read_only",
                    "context",
                ]
            },
            "repair_reason": nonempty,
            "step_status_summary": {
                "type": "object",
                "properties": {
                    status: {"type": "integer", "minimum": 0}
                    for status in (
                        "valid",
                        "authority_invalid",
                        "ready",
                        "runtime_verified",
                        "runtime_failed",
                        "blocked_by_dependency",
                        "pruned_dead",
                    )
                },
                "additionalProperties": False,
            },
            "editable_step_ids": {
                "type": "array",
                "items": nonempty,
                "uniqueItems": True,
            },
            "frozen_step_ids": {
                "type": "array",
                "items": nonempty,
                "uniqueItems": True,
            },
            "promoted_step_ids": {
                "type": "array",
                "items": nonempty,
                "uniqueItems": True,
            },
            "scope_steps": {
                "type": "array",
                "items": {"$ref": "#/$defs/step"},
            },
            "goals": {
                "type": "array",
                "items": {"$ref": "#/$defs/goal"},
            },
        }
        if level < 3:
            properties["children"] = {
                "type": "array",
                "items": {"$ref": f"#/$defs/scope_{level + 1}"},
            }
        scope_defs[f"scope_{level}"] = {
            "type": "object",
            "required": [
                "scope_ref",
                "execution_status",
                "repair_permission",
                "step_status_summary",
            ],
            "properties": properties,
            "allOf": [
                {
                    "if": {
                        "properties": {
                            "repair_permission": {
                                "enum": ["editable", "partially_editable"]
                            }
                        },
                        "required": ["repair_permission"],
                    },
                    "else": {"required": ["repair_reason"]},
                }
            ],
            "additionalProperties": False,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "planner-goal-retry-context.schema.json",
        "title": "Planner Goal Retry Context v4",
        "type": "object",
        "required": [
            "schema_version",
            "base_plan_id",
            "base_retry_context_id",
            "root_scope",
            "published_goal_results",
            "metrics",
        ],
        "properties": {
            "schema_version": {"const": PLANNER_GOAL_RETRY_CONTEXT_CONTRACT},
            "base_plan_id": nonempty,
            "base_retry_context_id": nonempty,
            "root_scope": {"$ref": "#/$defs/scope_0"},
            "published_goal_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["published_goal_ref", "runtime_type"],
                    "properties": {
                        "published_goal_ref": nonempty,
                        "runtime_type": nonempty,
                        "value": {},
                        "value_omitted_reason": nonempty,
                    },
                    "additionalProperties": False,
                },
            },
            "metrics": {
                "type": "object",
                "required": [
                    "solved_goal_count",
                    "failed_goal_count",
                    "blocked_goal_count",
                    "editable_goal_count",
                    "editable_scope_count",
                ],
                "properties": {
                    key: {"type": "integer", "minimum": 0}
                    for key in (
                        "solved_goal_count",
                        "failed_goal_count",
                        "blocked_goal_count",
                        "editable_goal_count",
                        "editable_scope_count",
                    )
                },
                "additionalProperties": False,
            },
            "previous_repair_issue": {
                "type": "object",
                "required": ["code", "path", "message"],
                "properties": {
                    "code": nonempty,
                    "path": nonempty,
                    "message": nonempty,
                    "details": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
        "$defs": {
            "step": execution_step,
            "goal": goal,
            **scope_defs,
        },
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class PublishedGoalResult:
    goal_ref: str
    producer_step_id: str
    return_name: str
    runtime_type: str
    value: Any = None
    value_omitted_reason: str | None = None

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "published_goal_ref": self.goal_ref,
            "runtime_type": self.runtime_type,
        }
        if self.value is not None:
            payload["value"] = _json_safe(self.value)
        elif self.value_omitted_reason:
            payload["value_omitted_reason"] = self.value_omitted_reason
        return payload

    def authority_payload(self) -> dict[str, Any]:
        return {
            **self.to_prompt_payload(),
            "producer_step_id": self.producer_step_id,
            "return": self.return_name,
        }


@dataclass(frozen=True)
class FunctionalGoalRetryGoalAuthority:
    goal_ref: str
    goal_unit_id: str
    status: GoalRetryStatus
    editable: bool
    answer_producer_step_id: str
    answer_return_name: str
    answer_target_ref: str
    answer_type: str
    closure_step_ids: tuple[str, ...]
    issue_signature: str
    issues: tuple[Mapping[str, Any], ...]
    checks: Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "closure_step_ids", tuple(self.closure_step_ids))
        object.__setattr__(
            self,
            "issues",
            tuple(MappingProxyType(dict(item)) for item in self.issues),
        )
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))

    def authority_payload(self) -> dict[str, Any]:
        return {
            "goal_ref": self.goal_ref,
            "goal_unit_id": self.goal_unit_id,
            "status": self.status,
            "editable": self.editable,
            "answer_producer_step_id": self.answer_producer_step_id,
            "answer_return_name": self.answer_return_name,
            "answer_target_ref": self.answer_target_ref,
            "answer_type": self.answer_type,
            "closure_step_ids": list(self.closure_step_ids),
            "issue_signature": self.issue_signature,
            "issues": [dict(item) for item in self.issues],
            "checks": dict(self.checks),
        }


@dataclass(frozen=True)
class PlannerGoalRetryContext:
    base_plan_id: str
    base_retry_context_id: str
    root_scope: Mapping[str, Any]
    published_goal_results: tuple[PublishedGoalResult, ...]
    metrics: Mapping[str, int]
    schema_version: str = PLANNER_GOAL_RETRY_CONTEXT_CONTRACT

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_scope", _freeze_mapping(self.root_scope))
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))

    def to_prompt_payload(
        self,
        *,
        previous_repair_issue: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "base_plan_id": self.base_plan_id,
            "base_retry_context_id": self.base_retry_context_id,
            "root_scope": _thaw(self.root_scope),
            "published_goal_results": [
                item.to_prompt_payload() for item in self.published_goal_results
            ],
            "metrics": dict(self.metrics),
        }
        if previous_repair_issue is not None:
            payload["previous_repair_issue"] = dict(previous_repair_issue)
        errors = tuple(
            Draft202012Validator(planner_goal_retry_context_schema()).iter_errors(
                payload
            )
        )
        if errors:
            first = sorted(errors, key=lambda item: tuple(item.absolute_path))[0]
            raise FunctionalGoalRetryError(
                "functional.goal_retry_context_invalid",
                _json_path(first.absolute_path),
                first.message,
                retryable=False,
            )
        return payload


@dataclass(frozen=True)
class FunctionalGoalRetryAuthority:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    problem_binding_catalog_signature: str
    functional_problem_binding_signature: str
    base_plan: ScopedFunctionalPlan
    base_plan_id: str
    base_plan_hash: str
    goal_execution_checkpoint_id: str
    typed_checkpoint_hash: str
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority]
    editable_scope_refs: tuple[str, ...]
    frozen_scope_refs: tuple[str, ...]
    editable_scope_step_ids: Mapping[str, tuple[str, ...]]
    frozen_scope_step_ids: Mapping[str, tuple[str, ...]]
    editable_answer_goal_refs: tuple[str, ...]
    repair_step_owners: Mapping[str, str]
    published_goal_results: tuple[PublishedGoalResult, ...]
    retry_context: PlannerGoalRetryContext
    retry_context_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "goal_authorities",
            MappingProxyType(dict(sorted(self.goal_authorities.items()))),
        )
        object.__setattr__(self, "editable_scope_refs", tuple(self.editable_scope_refs))
        object.__setattr__(self, "frozen_scope_refs", tuple(self.frozen_scope_refs))
        object.__setattr__(
            self,
            "editable_scope_step_ids",
            MappingProxyType(
                {
                    key: tuple(values)
                    for key, values in sorted(
                        self.editable_scope_step_ids.items()
                    )
                }
            ),
        )
        object.__setattr__(
            self,
            "frozen_scope_step_ids",
            MappingProxyType(
                {
                    key: tuple(values)
                    for key, values in sorted(
                        self.frozen_scope_step_ids.items()
                    )
                }
            ),
        )
        object.__setattr__(
            self,
            "repair_step_owners",
            MappingProxyType(dict(sorted(self.repair_step_owners.items()))),
        )
        object.__setattr__(
            self,
            "editable_answer_goal_refs",
            tuple(sorted(self.editable_answer_goal_refs)),
        )
        expected_plan_hash = scoped_functional_plan_id(self.base_plan)
        if (
            self.base_plan_id != expected_plan_hash
            or self.base_plan_hash != expected_plan_hash
        ):
            raise FunctionalGoalRetryError(
                "functional.goal_retry_authority_drift",
                "$.base_plan",
                "retry base Plan does not match its authority identity",
                retryable=False,
            )
        if self.retry_context.base_plan_id != self.base_plan_id:
            raise FunctionalGoalRetryError(
                "functional.goal_retry_authority_drift",
                "$.retry_context.base_plan_id",
                "retry Context does not target the authority base Plan",
                retryable=False,
            )
        if self.retry_context.base_retry_context_id != self.retry_context_id:
            raise FunctionalGoalRetryError(
                "functional.goal_retry_authority_drift",
                "$.retry_context.base_retry_context_id",
                "retry Context does not expose its current authority id",
                retryable=False,
            )

    @property
    def editable_goal_refs(self) -> tuple[str, ...]:
        return tuple(
            item.goal_ref
            for item in self.goal_authorities.values()
            if item.editable
        )

    @property
    def solved_goal_refs(self) -> tuple[str, ...]:
        return tuple(
            item.goal_ref
            for item in self.goal_authorities.values()
            if item.status == "solved"
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "problem_binding_catalog_signature": (
                self.problem_binding_catalog_signature
            ),
            "functional_problem_binding_signature": (
                self.functional_problem_binding_signature
            ),
            "base_plan_id": self.base_plan_id,
            "base_plan_hash": self.base_plan_hash,
            "goal_execution_checkpoint_id": self.goal_execution_checkpoint_id,
            "typed_checkpoint_hash": self.typed_checkpoint_hash,
            "goal_authorities": {
                key: value.authority_payload()
                for key, value in self.goal_authorities.items()
            },
            "editable_scope_refs": list(self.editable_scope_refs),
            "frozen_scope_refs": list(self.frozen_scope_refs),
            "editable_scope_step_ids": {
                key: list(values)
                for key, values in self.editable_scope_step_ids.items()
            },
            "frozen_scope_step_ids": {
                key: list(values)
                for key, values in self.frozen_scope_step_ids.items()
            },
            "editable_answer_goal_refs": list(
                self.editable_answer_goal_refs
            ),
            "repair_step_owners": dict(self.repair_step_owners),
            "published_goal_results": [
                item.authority_payload() for item in self.published_goal_results
            ],
            "retry_context_id": self.retry_context_id,
        }


@dataclass(frozen=True)
class FunctionalGoalReplacement:
    goal_ref: str
    steps: tuple[Mapping[str, Any], ...]
    answer_from: Mapping[str, str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "steps": [_thaw(item) for item in self.steps],
            "answer_from": dict(self.answer_from),
        }


@dataclass(frozen=True)
class FunctionalScopeStepReplacement:
    scope_ref: str
    steps: tuple[Mapping[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "steps": [_thaw(item) for item in self.steps],
        }


@dataclass(frozen=True)
class FunctionalAnswerBindingReplacement:
    goal_ref: str
    answer_from: Mapping[str, str]

    def to_payload(self) -> dict[str, Any]:
        return {"answer_from": dict(self.answer_from)}


@dataclass(frozen=True)
class FunctionalGoalRepair:
    base_plan_id: str
    base_retry_context_id: str
    goal_replacements: tuple[FunctionalGoalReplacement, ...]
    scope_step_replacements: tuple[FunctionalScopeStepReplacement, ...]
    answer_binding_replacements: tuple[
        FunctionalAnswerBindingReplacement, ...
    ] = ()
    schema_version: str = FUNCTIONAL_GOAL_REPAIR_CONTRACT
    normalizations: tuple[FunctionalPlanContentNormalization, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "base_plan_id": self.base_plan_id,
            "base_retry_context_id": self.base_retry_context_id,
            "goal_replacements": {
                item.goal_ref: item.to_payload()
                for item in self.goal_replacements
            },
            "scope_step_replacements": {
                item.scope_ref: item.to_payload()
                for item in self.scope_step_replacements
            },
        }
        if self.answer_binding_replacements:
            payload["answer_binding_replacements"] = {
                item.goal_ref: item.to_payload()
                for item in self.answer_binding_replacements
            }
        return payload


@dataclass(frozen=True)
class FunctionalGoalRepairApplication:
    repair: FunctionalGoalRepair
    plan: ScopedFunctionalPlan
    plan_hash: str
    validation_report: ScopedFunctionalPlanValidationReport
    published_goal_bindings: tuple[ScopedPublishedGoalBinding, ...] = ()
    answer_rebindings: tuple["FunctionalGoalAnswerRebinding", ...] = ()
    normalizations: tuple[FunctionalPlanContentNormalization, ...] = ()


@dataclass(frozen=True)
class FunctionalGoalAnswerRebinding:
    """Deterministic repair of one stale Goal answer producer identity."""

    goal_ref: str
    previous_step_id: str
    previous_return_name: str
    selected_step_id: str
    selected_return_name: str
    answer_target_ref: str
    answer_type: str
    match_basis: str

    def to_payload(self) -> dict[str, str]:
        return {
            "goal_ref": self.goal_ref,
            "previous_step_id": self.previous_step_id,
            "previous_return_name": self.previous_return_name,
            "selected_step_id": self.selected_step_id,
            "selected_return_name": self.selected_return_name,
            "answer_target_ref": self.answer_target_ref,
            "answer_type": self.answer_type,
            "match_basis": self.match_basis,
        }


@dataclass(frozen=True)
class ScopedFunctionalGoalRetryAttempt:
    semantic_attempt: int
    planner_protocol: str
    payload: Mapping[str, Any]
    prompt: Any
    raw_response: str
    plan: ScopedFunctionalPlan | None
    execution: ScopedFunctionalGoalExecutionResult | None
    merged_plan: ScopedFunctionalPlan | None = None
    retry_authority: FunctionalGoalRetryAuthority | None = None
    result_retry_authority: FunctionalGoalRetryAuthority | None = None
    repair: FunctionalGoalRepair | None = None
    error: FunctionalGoalRetryError | None = None
    plan_content: FunctionalPlanContent | None = None
    content_normalizations: tuple[FunctionalPlanContentNormalization, ...] = ()
    content_validation_report: ScopedFunctionalPlanValidationReport | None = None
    final_plan_contract_validation: (
        FunctionalFinalPlanContractValidation | None
    ) = None


@dataclass(frozen=True)
class ScopedFunctionalGoalRetryRunResult:
    status: Literal["accepted", "blocked"]
    attempts: tuple[ScopedFunctionalGoalRetryAttempt, ...]
    final_plan: ScopedFunctionalPlan | None
    final_execution: ScopedFunctionalGoalExecutionResult | None
    solved_goal_restore_count: int
    no_progress: bool = False
    verified_execution: VerifiedFunctionalPlanExecution | None = None


class ScopedFunctionalGoalRetryService:
    """Author once, then repair failed Goals with an independent protocol."""

    def __init__(
        self,
        client: LLMPlannerClient,
        *,
        payload_builder: Any | None = None,
        prompt_renderer: Any | None = None,
        execution_service: Any | None = None,
    ) -> None:
        # Lazy imports avoid a strategy_payload -> retry module import cycle.
        if payload_builder is None or prompt_renderer is None:
            from shuxueshuo_server.solver.runtime.strategy_payload import (
                StrategyPayloadBuilder,
                StrategyPromptRenderer,
            )

            payload_builder = payload_builder or StrategyPayloadBuilder()
            prompt_renderer = prompt_renderer or StrategyPromptRenderer()
        if execution_service is None:
            from shuxueshuo_server.solver.runtime.functional_goal_execution import (
                ScopedFunctionalGoalExecutionService,
            )

            execution_service = ScopedFunctionalGoalExecutionService()
        self.client = client
        self.payload_builder = payload_builder
        self.prompt_renderer = prompt_renderer
        self.execution_service = execution_service

    def run(
        self,
        *,
        inputs: PlannerInputs,
        planning_context: ProblemPlanningContext,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
        handle_registry: CanonicalHandleRegistry,
        runtime_context: Any,
        planner_state_context: PlannerStateContext,
        problem_payload: dict[str, Any],
        max_attempts: int = 3,
    ) -> ScopedFunctionalGoalRetryRunResult:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        attempts: list[ScopedFunctionalGoalRetryAttempt] = []
        current_plan: ScopedFunctionalPlan | None = None
        current_execution: ScopedFunctionalGoalExecutionResult | None = None
        retry_authority: FunctionalGoalRetryAuthority | None = None
        attempt_signatures: list[tuple[str, str]] = []
        restore_execution: ScopedFunctionalGoalExecutionResult | None = None
        solved_restore_count = 0
        no_progress = False
        previous_repair_issue: dict[str, Any] | None = None
        authoring_feedback: tuple[dict[str, Any], ...] = ()
        previous_invalid_content: dict[str, Any] | None = None
        plan_frame = FunctionalPlanAuthorityFrame.from_planning_context(
            planning_context
        )
        capability_catalog = family_capability_bundle_for_inputs(inputs).catalog

        for semantic_attempt in range(1, max_attempts + 1):
            if current_plan is None or retry_authority is None:
                payload = self.payload_builder.build_scoped(
                    inputs,
                    problem_payload=problem_payload,
                    planner_state_context=planner_state_context,
                    problem_planning_context=planning_context,
                    problem_binding_catalog=problem_binding_catalog,
                    authoring_feedback=authoring_feedback,
                    previous_invalid_content=previous_invalid_content,
                )
                prompt = self.prompt_renderer.render_scoped(payload)
                protocol = FUNCTIONAL_PLAN_CONTENT_CONTRACT
            else:
                payload = self.payload_builder.build_goal_repair(
                    inputs,
                    previous_plan=current_plan,
                    retry_authority=retry_authority,
                    problem_payload=problem_payload,
                    planner_state_context=planner_state_context,
                    problem_planning_context=planning_context,
                    problem_binding_catalog=problem_binding_catalog,
                    previous_repair_issue=previous_repair_issue,
                )
                prompt = self.prompt_renderer.render_goal_repair(payload)
                protocol = FUNCTIONAL_GOAL_REPAIR_CONTRACT
            raw_response = self.client.complete(
                {
                    "messages": prompt.messages,
                    "family_id": inputs.family_spec.family_id,
                    "problem_id": inputs.problem_id,
                    "planner_protocol": protocol,
                    "planner_attempt": semantic_attempt,
                    "planner_payload": payload,
                }
            )
            repair: FunctionalGoalRepair | None = None
            next_plan: ScopedFunctionalPlan | None = None
            plan_content: FunctionalPlanContent | None = None
            content_normalizations: tuple[
                FunctionalPlanContentNormalization, ...
            ] = ()
            content_validation_report: (
                ScopedFunctionalPlanValidationReport | None
            ) = None
            attempt_execution: ScopedFunctionalGoalExecutionResult | None = None
            final_plan_contract_validation: (
                FunctionalFinalPlanContractValidation | None
            ) = None
            try:
                if protocol == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                    compilation = FunctionalPlanContentCompiler().compile_json(
                        raw_response,
                        frame=plan_frame,
                        capability_catalog=capability_catalog,
                    )
                    plan = compilation.plan
                    validation = compilation.report
                    content_validation_report = validation
                    plan_content = compilation.content
                    content_normalizations = compilation.normalizations
                    if plan is None:
                        if compilation.answer_binding_error is not None:
                            authoring_feedback = (
                                compilation.answer_binding_error.to_feedback_payload(),
                            )
                        else:
                            authoring_feedback = tuple(
                                item.to_payload() for item in validation.issues
                            )
                        previous_invalid_content = (
                            _normalized_content_candidate(raw_response)
                        )
                        first = validation.issues[0]
                        raise FunctionalGoalRetryError(
                            first.code,
                            first.path,
                            first.message,
                        )
                    next_plan = plan
                    authoring_feedback = ()
                    previous_invalid_content = None
                else:
                    assert current_plan is not None
                    assert retry_authority is not None
                    repair_service = FunctionalGoalRepairService()
                    repair = repair_service.parse_json(
                        raw_response,
                        capability_catalog=capability_catalog,
                    )
                    content_normalizations = repair.normalizations
                    application = repair_service.apply(
                        repair,
                        base_plan=current_plan,
                        authority=retry_authority,
                        capability_catalog=capability_catalog,
                    )
                    next_plan = application.plan

                restored_seed = None
                if retry_authority is not None and restore_execution is not None:
                    restored_seed = _restored_seed(
                        retry_authority,
                        restore_execution,
                        next_plan=next_plan,
                    )
                    solved_restore_count += len(restored_seed.call_ids)
                execution = self.execution_service.execute_raw_json(
                    json.dumps(next_plan.to_payload(), ensure_ascii=False),
                    inputs=inputs,
                    planning_context=planning_context,
                    problem_binding_catalog=problem_binding_catalog,
                    handle_registry=handle_registry,
                    context=runtime_context,
                    planner_state_context=planner_state_context,
                    problem_payload=problem_payload,
                    attempt=semantic_attempt - 1,
                    restored_seed=restored_seed,
                    published_goal_bindings=scoped_published_goal_bindings(
                        next_plan
                    ),
                    macro_expansions=(
                        rebase_macro_expansion_records(
                            current_execution.macro_expansions,
                            next_plan,
                        )
                        if current_execution is not None
                        else ()
                    ),
                )
                attempt_execution = execution
                current_plan = execution.canonical_plan or next_plan
                current_execution = execution
                final_plan_contract_validation = (
                    FunctionalPlanContentCompiler().validate_final_plan(
                        current_plan,
                        frame=plan_frame,
                        capability_catalog=capability_catalog,
                    )
                )
                previous_repair_issue = None
                attempt_record = ScopedFunctionalGoalRetryAttempt(
                    semantic_attempt=semantic_attempt,
                    planner_protocol=protocol,
                    payload=payload,
                    prompt=prompt,
                    raw_response=raw_response,
                    plan=current_plan,
                    execution=execution,
                    merged_plan=next_plan,
                    retry_authority=retry_authority,
                    repair=repair,
                    plan_content=plan_content,
                    content_normalizations=content_normalizations,
                    content_validation_report=content_validation_report,
                    final_plan_contract_validation=(
                        final_plan_contract_validation
                    ),
                )
                if _requires_complete_plan_retry(execution):
                    attempts.append(attempt_record)
                    authoring_feedback = _complete_plan_retry_feedback(execution)
                    previous_invalid_content = functional_plan_content_from_plan(
                        next_plan,
                        frame=plan_frame,
                    ).to_payload()
                    current_plan = None
                    retry_authority = None
                    restore_execution = None
                    continue

                authoring_feedback = ()
                previous_invalid_content = None
                if not final_plan_contract_validation.ok:
                    localized_contract_issues = (
                        _final_plan_contract_root_issues(
                            final_plan_contract_validation
                        )
                    )
                    if not localized_contract_issues:
                        attempts.append(attempt_record)
                        authoring_feedback = (
                            _final_plan_contract_feedback(
                                final_plan_contract_validation
                            )
                        )
                        previous_invalid_content = (
                            final_plan_contract_validation.content.to_payload()
                            if final_plan_contract_validation.content is not None
                            else functional_plan_content_from_plan(
                                current_plan,
                                frame=plan_frame,
                            ).to_payload()
                        )
                        current_plan = None
                        retry_authority = None
                        restore_execution = None
                        continue
                checkpoint = execution.checkpoint
                if (
                    checkpoint is not None
                    and checkpoint.all_required_goals_verified
                    and execution.replay is not None
                    and execution.replay.output is not None
                    and final_plan_contract_validation.ok
                ):
                    attempts.append(attempt_record)
                    return ScopedFunctionalGoalRetryRunResult(
                        status="accepted",
                        attempts=tuple(attempts),
                        final_plan=current_plan,
                        final_execution=execution,
                        solved_goal_restore_count=solved_restore_count,
                        verified_execution=execution.verified_execution,
                    )
                next_retry_authority = FunctionalGoalRetryProjector().project(
                    plan=current_plan,
                    execution=execution,
                    planning_context=planning_context,
                    binding_catalog=problem_binding_catalog,
                    previous_authority=retry_authority,
                    final_plan_contract=final_plan_contract_validation,
                )
                attempt_record = replace(
                    attempt_record,
                    result_retry_authority=next_retry_authority,
                )
                attempt_signature = (
                    scoped_functional_plan_id(current_plan),
                    _retry_issue_signature(next_retry_authority),
                )
                if (
                    attempt_signatures
                    and attempt_signatures[-1] == attempt_signature
                ):
                    attempts.append(attempt_record)
                    retry_authority = next_retry_authority
                    current_plan = retry_authority.base_plan
                    no_progress = True
                    break
                attempt_signatures.append(attempt_signature)
                if (
                    execution.replay is not None
                    and execution.replay.transactional_attempt_result is not None
                ):
                    restore_execution = execution
                retry_authority = next_retry_authority
                current_plan = retry_authority.base_plan
                attempts.append(attempt_record)
            except FunctionalGoalRetryError as exc:
                attempts.append(
                    ScopedFunctionalGoalRetryAttempt(
                        semantic_attempt=semantic_attempt,
                        planner_protocol=protocol,
                        payload=payload,
                        prompt=prompt,
                        raw_response=raw_response,
                        plan=current_plan,
                        execution=attempt_execution,
                        merged_plan=next_plan,
                        retry_authority=retry_authority,
                        repair=repair,
                        error=exc,
                        plan_content=plan_content,
                        content_normalizations=content_normalizations,
                        content_validation_report=content_validation_report,
                        final_plan_contract_validation=(
                            final_plan_contract_validation
                        ),
                    )
                )
                if exc.code == "functional.goal_repair_no_progress":
                    no_progress = True
                    break
                if not exc.retryable:
                    break
                if protocol == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                    if not authoring_feedback:
                        authoring_feedback = (
                            {
                                "code": exc.code,
                                "path": exc.path,
                                "message": exc.message,
                            },
                        )
                    if previous_invalid_content is None:
                        previous_invalid_content = (
                            _normalized_content_candidate(raw_response)
                        )
                elif (
                    protocol == FUNCTIONAL_GOAL_REPAIR_CONTRACT
                    and exc.retryable
                ):
                    previous_repair_issue = exc.to_prompt_payload()
            except ScopedFunctionalPlanError as exc:
                wrapped = FunctionalGoalRetryError(
                    exc.code,
                    exc.path,
                    exc.message,
                    retryable=exc.retryable,
                    details=(
                        dict(exc.issues[0].details)
                        if exc.issues and exc.issues[0].details
                        else None
                    ),
                )
                attempts.append(
                    ScopedFunctionalGoalRetryAttempt(
                        semantic_attempt=semantic_attempt,
                        planner_protocol=protocol,
                        payload=payload,
                        prompt=prompt,
                        raw_response=raw_response,
                        plan=next_plan or current_plan,
                        execution=attempt_execution,
                        merged_plan=next_plan,
                        retry_authority=retry_authority,
                        repair=repair,
                        error=wrapped,
                        plan_content=plan_content,
                        content_normalizations=content_normalizations,
                        content_validation_report=(
                            ScopedFunctionalPlanValidationReport(exc.issues)
                        ),
                        final_plan_contract_validation=(
                            final_plan_contract_validation
                        ),
                    )
                )
                if not exc.retryable:
                    break
                if protocol == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                    authoring_feedback = tuple(
                        issue.to_payload() for issue in exc.issues
                    )
                    previous_invalid_content = (
                        _normalized_content_candidate(raw_response)
                    )
                    current_plan = None
                    retry_authority = None
                    restore_execution = None
                else:
                    previous_repair_issue = wrapped.to_prompt_payload()
            except ProblemPlanningBindingError as exc:
                wrapped = FunctionalGoalRetryError(
                    exc.code,
                    exc.path,
                    exc.message,
                    retryable=False,
                    details=exc.details,
                )
                attempts.append(
                    ScopedFunctionalGoalRetryAttempt(
                        semantic_attempt=semantic_attempt,
                        planner_protocol=protocol,
                        payload=payload,
                        prompt=prompt,
                        raw_response=raw_response,
                        plan=next_plan or current_plan,
                        execution=attempt_execution,
                        merged_plan=next_plan,
                        retry_authority=retry_authority,
                        repair=repair,
                        error=wrapped,
                        plan_content=plan_content,
                        content_normalizations=content_normalizations,
                        content_validation_report=content_validation_report,
                        final_plan_contract_validation=(
                            final_plan_contract_validation
                        ),
                    )
                )
                break
            except FunctionalRestoredCallBindingError as exc:
                wrapped = FunctionalGoalRetryError(
                    exc.code,
                    exc.path,
                    exc.message,
                    retryable=False,
                    details=exc.details,
                )
                attempts.append(
                    ScopedFunctionalGoalRetryAttempt(
                        semantic_attempt=semantic_attempt,
                        planner_protocol=protocol,
                        payload=payload,
                        prompt=prompt,
                        raw_response=raw_response,
                        plan=next_plan or current_plan,
                        execution=attempt_execution,
                        merged_plan=next_plan,
                        retry_authority=retry_authority,
                        repair=repair,
                        error=wrapped,
                        plan_content=plan_content,
                        content_normalizations=content_normalizations,
                        content_validation_report=content_validation_report,
                        final_plan_contract_validation=(
                            final_plan_contract_validation
                        ),
                    )
                )
                break
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                wrapped = FunctionalGoalRetryError(
                    (
                        "planner.transactional_configuration_error"
                        if "planner_configuration_error" in str(exc)
                        else "planner.unclassified_implementation_error"
                    ),
                    "$.execution",
                    message,
                    retryable=False,
                    details={
                        "exception_type": type(exc).__name__,
                        "original_message": str(exc),
                    },
                )
                attempts.append(
                    ScopedFunctionalGoalRetryAttempt(
                        semantic_attempt=semantic_attempt,
                        planner_protocol=protocol,
                        payload=payload,
                        prompt=prompt,
                        raw_response=raw_response,
                        plan=next_plan or current_plan,
                        execution=attempt_execution,
                        merged_plan=next_plan,
                        retry_authority=retry_authority,
                        repair=repair,
                        error=wrapped,
                        plan_content=plan_content,
                        content_normalizations=content_normalizations,
                        content_validation_report=content_validation_report,
                        final_plan_contract_validation=(
                            final_plan_contract_validation
                        ),
                    )
                )
                break

        return ScopedFunctionalGoalRetryRunResult(
            status="blocked",
            attempts=tuple(attempts),
            final_plan=current_plan,
            final_execution=current_execution,
            solved_goal_restore_count=solved_restore_count,
            no_progress=no_progress,
        )


_COMPLETE_PLAN_RETRY_CODES = frozenset(
    {
        "functional.scope_tree_drift",
        "functional.goal_tree_drift",
    }
)


def _requires_complete_plan_retry(
    execution: ScopedFunctionalGoalExecutionResult,
) -> bool:
    """Return whether Goal replacement lacks a stable scope/Goal authority."""

    checkpoint = execution.checkpoint
    if checkpoint is None:
        return True
    return any(
        str(issue.get("code", "")) in _COMPLETE_PLAN_RETRY_CODES
        for issue in checkpoint.root_issues
    )


def _complete_plan_retry_feedback(
    execution: ScopedFunctionalGoalExecutionResult,
) -> tuple[dict[str, str], ...]:
    checkpoint = execution.checkpoint
    if checkpoint is None:
        return (
            {
                "code": "functional.goal_retry_authority_unavailable",
                "path": "$.root_scope",
                "message": "the previous full Plan did not establish a canonical scope/Goal checkpoint",
            },
        )
    return tuple(
        {
            "code": str(issue.get("code", "functional.plan_invalid")),
            "path": str(issue.get("path", "$.root_scope")),
            "message": str(issue.get("message", "full Plan authority is invalid")),
        }
        for issue in checkpoint.root_issues
        if str(issue.get("code", "")) in _COMPLETE_PLAN_RETRY_CODES
    )


def _normalized_content_candidate(raw_response: str) -> dict[str, Any] | None:
    """Retain parseable content wire for the next authoring prompt."""

    try:
        payload, _ = decode_single_json_object(raw_response)
    except (json.JSONDecodeError, ValueError):
        return None
    if payload.get("format") != FUNCTIONAL_PLAN_CONTENT_CONTRACT:
        return None
    return payload


def _final_plan_contract_feedback(
    validation: FunctionalFinalPlanContractValidation,
) -> tuple[dict[str, Any], ...]:
    """Return compact full-Plan feedback without embedding provider schemas."""

    return tuple(
        {
            "code": issue.code,
            "path": issue.path,
            "message": issue.message,
        }
        for issue in validation.report.issues
    )


def _final_plan_contract_root_issues(
    validation: FunctionalFinalPlanContractValidation,
) -> tuple[dict[str, Any], ...]:
    """Localize final contract issues to authored Goal or Scope blocks.

    A parseable PlanDraft is useful execution evidence.  Once execution has
    established the current canonical Plan, contract failures are projected
    onto that exact Plan's owner blocks so Goal replacement can repair them.
    Issues at the document root cannot be localized safely and stay on the
    complete-Plan authoring path.
    """

    content = validation.content
    if content is None:
        return ()
    payload = content.to_payload()
    goal_plans = payload.get("goal_plans", {})
    scope_steps = payload.get("scope_steps", {})
    if not isinstance(goal_plans, Mapping) or not isinstance(
        scope_steps, Mapping
    ):
        return ()

    localized: list[dict[str, Any]] = []
    for issue in validation.report.issues:
        owner_kind: str | None = None
        owner_ref: str | None = None
        step: Mapping[str, Any] | None = None

        for goal_ref, goal_payload in sorted(
            goal_plans.items(), key=lambda item: len(str(item[0])), reverse=True
        ):
            prefixes = (
                f"$.goal_plans.{goal_ref}",
                f"$.goal_plans['{goal_ref}']",
            )
            prefix = next(
                (
                    candidate
                    for candidate in prefixes
                    if issue.path.startswith(candidate)
                ),
                None,
            )
            if prefix is None:
                continue
            owner_kind = "goal"
            owner_ref = str(goal_ref)
            if isinstance(goal_payload, Mapping):
                step = _contract_issue_step(
                    issue.path,
                    prefix=f"{prefix}.steps[",
                    steps=goal_payload.get("steps", ()),
                )
            break

        if owner_kind is None:
            for scope_ref, steps in sorted(
                scope_steps.items(),
                key=lambda item: len(str(item[0])),
                reverse=True,
            ):
                prefixes = (
                    f"$.scope_steps.{scope_ref}",
                    f"$.scope_steps['{scope_ref}']",
                )
                prefix = next(
                    (
                        candidate
                        for candidate in prefixes
                        if issue.path.startswith(candidate)
                    ),
                    None,
                )
                if prefix is None:
                    continue
                owner_kind = "scope"
                owner_ref = str(scope_ref)
                step = _contract_issue_step(
                    issue.path,
                    prefix=f"{prefix}[",
                    steps=steps,
                )
                break

        if owner_kind is None or owner_ref is None:
            return ()

        issue_details = dict(issue.details)
        public_details = {
            key: _thaw(issue_details[key])
            for key in (
                "capability_id",
                "observed_role",
                "observed_form",
                "expected_roles",
                "expected_forms",
            )
            if key in issue_details
        }
        capability_id = (
            str(step.get("capability_id"))
            if step is not None and step.get("capability_id") is not None
            else public_details.get("capability_id")
        )
        item: dict[str, Any] = {
            "code": issue.code,
            "path": issue.path,
            "message": (
                f"The authored {owner_kind} block does not satisfy the final "
                "public capability contract. Replace the complete editable "
                f"{owner_kind} block."
            ),
            "stage": "authoring_contract",
            "retryability": "planner_repairable",
            "repair_action": (
                "replace_goal" if owner_kind == "goal" else "replace_scope_steps"
            ),
            **public_details,
        }
        item[f"{owner_kind}_ref"] = owner_ref
        if step is not None and step.get("step_id") is not None:
            item["step_id"] = str(step["step_id"])
        if capability_id is not None:
            item["capability_id"] = capability_id
        localized.append(item)
    return tuple(localized)


def _contract_issue_step(
    path: str,
    *,
    prefix: str,
    steps: object,
) -> Mapping[str, Any] | None:
    if not path.startswith(prefix) or not isinstance(steps, Sequence) or isinstance(
        steps, (str, bytes)
    ):
        return None
    suffix = path[len(prefix) :]
    index_text, separator, _remainder = suffix.partition("]")
    if not separator or not index_text.isdigit():
        return None
    index = int(index_text)
    if index >= len(steps):
        return None
    step = steps[index]
    return step if isinstance(step, Mapping) else None


class FunctionalGoalRetryProjector:
    """Derive strict solved/failed Goal authority from F5-F2 and F5-D."""

    def project(
        self,
        *,
        plan: ScopedFunctionalPlan,
        execution: ScopedFunctionalGoalExecutionResult,
        planning_context: ProblemPlanningContext,
        binding_catalog: ProblemPlanningBindingCatalog,
        previous_authority: FunctionalGoalRetryAuthority | None = None,
        final_plan_contract: (
            FunctionalFinalPlanContractValidation | None
        ) = None,
    ) -> FunctionalGoalRetryAuthority:
        plan = execution.canonical_plan or plan
        checkpoint = execution.checkpoint
        authority = execution.authority
        if checkpoint is None:
            raise FunctionalGoalRetryError(
                "functional.goal_retry_authority_unavailable",
                "$.checkpoint",
                "Goal replacement retry requires a canonical Plan checkpoint",
                retryable=False,
            )
        try:
            checkpoint.verify_authority(
                planning_context=planning_context,
                binding_catalog=binding_catalog,
                authority=authority,
                goal_authority=execution.authoring_authority,
                dependency_graph=(
                    execution.replay.functional_reconciliation.dependency_graph
                    if execution.replay is not None
                    and execution.replay.functional_reconciliation is not None
                    else None
                ),
                binding_context=(
                    execution.replay.functional_reconciliation
                    .functional_problem_binding_context
                    if execution.replay is not None
                    and execution.replay.functional_reconciliation is not None
                    else None
                ),
            )
        except FunctionalGoalExecutionCheckpointError as exc:
            raise FunctionalGoalRetryError(
                "planner.goal_checkpoint_authority_invalid",
                exc.path,
                exc.message,
                retryable=False,
                details={
                    "checkpoint_error_code": exc.code,
                    "root_issues": [dict(item) for item in checkpoint.root_issues],
                },
            ) from exc
        configuration_diagnostics = _configuration_diagnostics(checkpoint)
        if configuration_diagnostics:
            first = configuration_diagnostics[0]
            raise FunctionalGoalRetryError(
                str(first.get("code") or "planner.method_contract_invalid"),
                "$.checkpoint.diagnostics",
                str(
                    first.get("message")
                    or "runtime configuration failure cannot be repaired by Planner"
                ),
                retryable=False,
                details={"diagnostic": first},
            )
        binding_context = (
            execution.replay.functional_reconciliation
            .functional_problem_binding_context
            if execution.replay is not None
            and execution.replay.functional_reconciliation is not None
            else None
        )
        functional_binding_signature = (
            binding_context.binding_signature
            if binding_context is not None
            else checkpoint.functional_problem_binding_signature
        )
        goal_plans = _goal_plans(plan)
        execution_goals = _execution_goals(checkpoint.root_scope)
        execution_steps = _execution_steps(checkpoint.root_scope)
        goal_views = {
            item.answer_ref.ref: item for item in planning_context.goal_views
        }
        goal_report = _goal_report(execution)
        forbidden_prompt_values = _internal_prompt_values(
            planning_context,
            binding_catalog,
        )
        call_states = _call_states(execution)
        call_results = _call_results(execution)
        restore_seed = checkpoint.restore_state.runtime_seed
        committed = {
            item.call_id: item
            for item in (
                restore_seed.compiled_calls
                if restore_seed is not None
                else ()
            )
        }
        provenance = {
            item.call_id: item.problem_source_provenance
            for item in committed.values()
            if item.problem_source_provenance is not None
        }
        successful_restore_authorities = (
            _successful_execution_restore_authorities(execution)
            if not committed
            and checkpoint.all_required_goals_verified
            else {}
        )
        checkpoint_root_issues = tuple(
            dict(item) for item in checkpoint.root_issues
        )
        if final_plan_contract is not None and not final_plan_contract.ok:
            contract_issues = _final_plan_contract_root_issues(
                final_plan_contract
            )
            if not contract_issues:
                raise FunctionalGoalRetryError(
                    "functional.final_plan_contract_unlocalized",
                    "$",
                    "final Plan contract failure has no safe Goal or Scope owner",
                )
            checkpoint_root_issues = (
                *checkpoint_root_issues,
                *contract_issues,
            )
        goal_authorities: dict[str, FunctionalGoalRetryGoalAuthority] = {}
        published: list[PublishedGoalResult] = []
        failed_scope_step_ids = _failed_scope_step_ids(
            checkpoint.root_scope,
            checkpoint_root_issues,
        )
        for goal_ref, goal_plan in sorted(goal_plans.items()):
            goal_view = goal_views.get(goal_ref)
            execution_goal = execution_goals.get(goal_ref)
            if goal_view is None or execution_goal is None:
                raise FunctionalGoalRetryError(
                    "functional.goal_retry_authority_drift",
                    f"$.goals[{goal_ref!r}]",
                    "Plan Goal is missing from planning or execution authority",
                    retryable=False,
                )
            closure = tuple(
                sorted(
                    step_id
                    for step_id, goal_ids in checkpoint.goal_unit_ids.items()
                    if goal_view.goal_unit_id in goal_ids
                )
            )
            answer = goal_report.get(goal_ref)
            direct_step_ids = {item.step_id for item in execution_goal.steps}
            direct_root_issues = tuple(
                item
                for item in checkpoint_root_issues
                if item.get("step_id") in direct_step_ids
                or item.get("goal_ref") == goal_ref
            )
            dependency_root_issues = tuple(
                item
                for item in checkpoint_root_issues
                if item.get("step_id") in closure
                and item.get("step_id") not in direct_step_ids
                and item.get("goal_ref") != goal_ref
            )
            checks = {
                "runtime_closure_verified": bool(closure)
                and all(call_states.get(step_id) == "verified" for step_id in closure),
                "answer_verification_passed": answer is not None
                and answer.get("status") == "passed",
                "symbolic_closure_passed": _symbolic_closure_passed(
                    closure,
                    call_results,
                ),
                "provenance_complete": bool(closure)
                and all(
                    step_id in provenance
                    or step_id in successful_restore_authorities
                    for step_id in closure
                ),
                "typed_checkpoint_restorable": bool(closure)
                and all(
                    (
                        step_id in committed
                        and committed[step_id].problem_call_binding is not None
                        and bool(
                            committed[
                                step_id
                            ].problem_call_binding.binding_signature
                        )
                        and committed[
                            step_id
                        ].problem_source_provenance is not None
                        and step_id in provenance
                        and committed[
                            step_id
                        ].problem_source_provenance.semantic_signature()
                        == provenance[step_id].semantic_signature()
                    )
                    or step_id in successful_restore_authorities
                    for step_id in closure
                ),
                "final_plan_contract_valid": not any(
                    item.get("goal_ref") == goal_ref
                    or item.get("step_id") in closure
                    for item in checkpoint_root_issues
                    if item.get("stage") == "authoring_contract"
                ),
            }
            solved = all(checks.values())
            scope_dependency_failure = bool(
                set(closure).intersection(failed_scope_step_ids)
            )
            answer_producer_step_id = goal_plan.answer_from.step_id
            answer_producer = execution_steps.get(answer_producer_step_id)
            answer_producer_has_root_issue = any(
                item.get("step_id") == answer_producer_step_id
                for item in checkpoint_root_issues
            )
            answer_producer_failed = (
                answer_producer is not None
                and answer_producer.status
                in {"authority_invalid", "runtime_failed"}
            ) or answer_producer_has_root_issue
            answer_failed_locally = (
                answer is not None
                and answer.get("status") == "failed"
                and goal_plan.answer_from.step_id in direct_step_ids
            )
            direct_failure = any(
                item.status in {"authority_invalid", "runtime_failed"}
                for item in execution_goal.steps
            ) or bool(direct_root_issues) or answer_failed_locally or (
                answer_producer_failed
            )
            blocked = any(
                item.status == "blocked_by_dependency"
                for item in execution_goal.steps
            ) or bool(dependency_root_issues) or scope_dependency_failure
            blocked = blocked and not direct_failure
            status: GoalRetryStatus
            if solved:
                status = "solved"
            elif direct_failure:
                status = "failed"
            elif blocked:
                status = "blocked"
            else:
                status = "failed" if answer is not None else "pending"
            issues = _goal_issue_payloads(
                execution_goal,
                answer,
                root_issues=(*direct_root_issues, *dependency_root_issues),
                forbidden_values=forbidden_prompt_values,
            )
            item = FunctionalGoalRetryGoalAuthority(
                goal_ref=goal_ref,
                goal_unit_id=goal_view.goal_unit_id,
                status=status,
                editable=status == "failed",
                answer_producer_step_id=answer_producer_step_id,
                answer_return_name=goal_plan.answer_from.return_name,
                answer_target_ref=(
                    str(goal_view.goal_payload.get("target"))
                    if isinstance(goal_view.goal_payload.get("target"), str)
                    else goal_view.answer_ref.ref
                ),
                answer_type=goal_view.answer_ref.value_type or "Unknown",
                closure_step_ids=closure,
                issue_signature=stable_hash(issues),
                issues=tuple(issues),
                checks=checks,
            )
            goal_authorities[goal_ref] = item
            if solved:
                published.append(
                    _published_goal_result(
                        goal_plan,
                        execution_steps,
                        call_results,
                    )
                )

        inherited_goal_refs = _inherit_solved_goal_authority(
            plan,
            goal_authorities=goal_authorities,
            published=published,
            previous_authority=previous_authority,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
        )

        (
            relation_scope_refs,
            relation_blocked_goal_refs,
        ) = _relation_scope_repair_authority(
            plan,
            checkpoint=checkpoint,
            goal_authorities=goal_authorities,
        )
        for goal_ref in relation_blocked_goal_refs:
            current = goal_authorities[goal_ref]
            goal_authorities[goal_ref] = replace(current, editable=True)

        step_promotions = _cross_scope_repair_promotions(
            plan,
            checkpoint.root_scope,
            goal_authorities,
        )
        repair_base_plan = _apply_step_promotions(plan, step_promotions)
        repair_base_plan_id = scoped_functional_plan_id(repair_base_plan)
        editable_scopes, frozen_scopes, scope_statuses = _scope_authority(
            checkpoint.root_scope,
            goal_authorities=goal_authorities,
            checkpoint=checkpoint,
            root_issues=checkpoint_root_issues,
            promoted_scope_refs=frozenset(
                (*step_promotions.values(), *relation_scope_refs)
            ),
        )
        (
            editable_scope_step_ids,
            frozen_scope_step_ids,
        ) = _scope_step_authority(
            repair_base_plan,
            goal_authorities=goal_authorities,
            editable_scope_refs=editable_scopes,
            frozen_scope_refs=frozen_scopes,
            failed_scope_step_ids=failed_scope_step_ids,
        )
        editable_answer_goal_refs = _editable_answer_binding_goal_refs(
            repair_base_plan,
            goal_authorities=goal_authorities,
            editable_scope_step_ids=editable_scope_step_ids,
        )
        if (
            not editable_scopes
            and not any(item.editable for item in goal_authorities.values())
            and not all(
                item.status == "solved" for item in goal_authorities.values()
            )
        ):
            raise FunctionalGoalRetryError(
                "functional.goal_retry_target_unresolved",
                "$.checkpoint.root_issues",
                "incomplete execution has no Goal or scope replacement authority",
                retryable=False,
            )
        prompt_root = _retry_scope_prompt(
            checkpoint.root_scope,
            planning_context=planning_context,
            goal_authorities=goal_authorities,
            scope_statuses=scope_statuses,
            step_promotions=step_promotions,
            editable_scope_step_ids=editable_scope_step_ids,
            frozen_scope_step_ids=frozen_scope_step_ids,
            editable_answer_goal_refs=editable_answer_goal_refs,
        )
        metrics = {
            "solved_goal_count": sum(
                item.status == "solved" for item in goal_authorities.values()
            ),
            "failed_goal_count": sum(
                item.status == "failed" for item in goal_authorities.values()
            ),
            "blocked_goal_count": sum(
                item.status == "blocked" for item in goal_authorities.values()
            ),
            "editable_goal_count": sum(
                item.editable for item in goal_authorities.values()
            ),
            "editable_scope_count": len(editable_scopes),
        }
        retry_context = PlannerGoalRetryContext(
            base_plan_id=repair_base_plan_id,
            base_retry_context_id="pending",
            root_scope=prompt_root,
            published_goal_results=tuple(published),
            metrics=metrics,
        )
        retry_context_payload = retry_context.to_prompt_payload()
        typed_checkpoint_hash = (
            checkpoint.restore_state.restore_signature
            if committed
            else (
                stable_hash(successful_restore_authorities)
                if successful_restore_authorities
                else (
                    previous_authority.typed_checkpoint_hash
                    if previous_authority is not None and inherited_goal_refs
                    else stable_hash(None)
                )
            )
        )
        retry_context_id = stable_hash(
            {
                "prompt": {
                    **retry_context_payload,
                    "base_retry_context_id": None,
                },
                "checkpoint_id": checkpoint.checkpoint_id,
                "typed_checkpoint_hash": typed_checkpoint_hash,
                "goals": {
                    key: value.authority_payload()
                    for key, value in sorted(goal_authorities.items())
                },
            }
        )
        retry_context = replace(
            retry_context,
            base_retry_context_id=retry_context_id,
        )
        return FunctionalGoalRetryAuthority(
            planning_context_id=planning_context.planning_context_id,
            problem_revision_id=planning_context.problem_revision_id,
            problem_semantic_hash=planning_context.problem_semantic_hash,
            problem_binding_catalog_signature=binding_catalog.binding_signature,
            functional_problem_binding_signature=functional_binding_signature,
            base_plan=repair_base_plan,
            base_plan_id=repair_base_plan_id,
            base_plan_hash=repair_base_plan_id,
            goal_execution_checkpoint_id=checkpoint.checkpoint_id,
            typed_checkpoint_hash=typed_checkpoint_hash,
            goal_authorities=goal_authorities,
            editable_scope_refs=editable_scopes,
            frozen_scope_refs=frozen_scopes,
            editable_scope_step_ids=editable_scope_step_ids,
            frozen_scope_step_ids=frozen_scope_step_ids,
            editable_answer_goal_refs=editable_answer_goal_refs,
            repair_step_owners={
                **_plan_step_owners(repair_base_plan),
            },
            published_goal_results=tuple(published),
            retry_context=retry_context,
            retry_context_id=retry_context_id,
        )


def _validate_goal_repair_payload(payload: object) -> None:
    errors = sorted(
        Draft202012Validator(functional_goal_repair_schema()).iter_errors(
            payload
        ),
        key=lambda item: tuple(item.absolute_path),
    )
    if not errors:
        return
    first = errors[0]
    raise FunctionalGoalRetryError(
        "functional.goal_repair_schema_invalid",
        _json_path(first.absolute_path),
        first.message,
    )


def _goal_repair_from_payload(
    payload: Mapping[str, Any],
    *,
    normalizations: Sequence[FunctionalPlanContentNormalization] = (),
) -> FunctionalGoalRepair:
    return FunctionalGoalRepair(
        base_plan_id=str(payload["base_plan_id"]),
        base_retry_context_id=str(payload["base_retry_context_id"]),
        goal_replacements=tuple(
            FunctionalGoalReplacement(
                goal_ref=str(goal_ref),
                steps=tuple(
                    _freeze_mapping(step) for step in item["steps"]
                ),
                answer_from=MappingProxyType(
                    {
                        "step_id": str(item["answer_from"]["step_id"]),
                        "return": str(item["answer_from"]["return"]),
                    }
                ),
            )
            for goal_ref, item in payload["goal_replacements"].items()
        ),
        scope_step_replacements=tuple(
            FunctionalScopeStepReplacement(
                scope_ref=str(scope_ref),
                steps=tuple(
                    _freeze_mapping(step) for step in item["steps"]
                ),
            )
            for scope_ref, item in payload["scope_step_replacements"].items()
        ),
        answer_binding_replacements=tuple(
            FunctionalAnswerBindingReplacement(
                goal_ref=str(goal_ref),
                answer_from=MappingProxyType(
                    {
                        "step_id": str(item["answer_from"]["step_id"]),
                        "return": str(item["answer_from"]["return"]),
                    }
                ),
            )
            for goal_ref, item in payload.get(
                "answer_binding_replacements", {}
            ).items()
        ),
        normalizations=tuple(normalizations),
    )


def _normalize_empty_optional_repair_maps(
    payload: object,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Canonicalize optional repair-level maps before strict validation."""

    normalized = deepcopy(payload)
    if (
        not isinstance(normalized, dict)
        or normalized.get("schema_version") != FUNCTIONAL_GOAL_REPAIR_CONTRACT
        or normalized.get("answer_binding_replacements") != {}
    ):
        return normalized, ()
    normalized.pop("answer_binding_replacements")
    return normalized, (
        FunctionalPlanContentNormalization(
            code="functional.empty_optional_repair_map_omitted",
            path="$.answer_binding_replacements",
            message=(
                "omitted empty optional answer_binding_replacements"
            ),
        ),
    )


class FunctionalGoalRepairService:
    """Parse and atomically apply one full-Goal replacement response."""

    def parse_json(
        self,
        raw: str,
        *,
        capability_catalog: FunctionalCapabilityCatalog | None = None,
    ) -> FunctionalGoalRepair:
        try:
            payload, normalizations = decode_single_json_object(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_invalid_json",
                "$",
                str(exc),
            ) from exc
        payload, step_map_normalizations = normalize_empty_optional_step_maps(
            payload
        )
        payload, repair_map_normalizations = (
            _normalize_empty_optional_repair_maps(payload)
        )
        normalizations = (
            *normalizations,
            *step_map_normalizations,
            *repair_map_normalizations,
        )
        if capability_catalog is not None:
            payload, arg_normalizations = (
                normalize_empty_optional_capability_args(
                    payload,
                    capability_catalog=capability_catalog,
                )
            )
            payload, interchangeable_normalizations = (
                normalize_interchangeable_capability_args(
                    payload,
                    capability_catalog=capability_catalog,
                )
            )
            normalizations = (
                *normalizations,
                *arg_normalizations,
                *interchangeable_normalizations,
            )
        _validate_goal_repair_payload(payload)
        assert isinstance(payload, dict)
        return _goal_repair_from_payload(
            payload,
            normalizations=normalizations,
        )

    def apply_json(
        self,
        raw: str,
        *,
        base_plan: ScopedFunctionalPlan,
        authority: FunctionalGoalRetryAuthority,
        capability_catalog: FunctionalCapabilityCatalog | None = None,
    ) -> FunctionalGoalRepairApplication:
        return self.apply(
            self.parse_json(
                raw,
                capability_catalog=capability_catalog,
            ),
            base_plan=base_plan,
            authority=authority,
            capability_catalog=capability_catalog,
        )

    def apply(
        self,
        repair: FunctionalGoalRepair,
        *,
        base_plan: ScopedFunctionalPlan,
        authority: FunctionalGoalRetryAuthority,
        capability_catalog: FunctionalCapabilityCatalog | None = None,
    ) -> FunctionalGoalRepairApplication:
        payload, step_map_normalizations = (
            normalize_empty_optional_step_maps(repair.to_payload())
        )
        payload, repair_map_normalizations = (
            _normalize_empty_optional_repair_maps(payload)
        )
        arg_normalizations: tuple[
            FunctionalPlanContentNormalization, ...
        ] = ()
        interchangeable_normalizations: tuple[
            FunctionalPlanContentNormalization, ...
        ] = ()
        if capability_catalog is not None:
            payload, arg_normalizations = (
                normalize_empty_optional_capability_args(
                    payload,
                    capability_catalog=capability_catalog,
                )
            )
            payload, interchangeable_normalizations = (
                normalize_interchangeable_capability_args(
                    payload,
                    capability_catalog=capability_catalog,
                )
            )
        _validate_goal_repair_payload(payload)
        assert isinstance(payload, dict)
        repair = _goal_repair_from_payload(
            payload,
            normalizations=(
                *repair.normalizations,
                *step_map_normalizations,
                *repair_map_normalizations,
                *arg_normalizations,
                *interchangeable_normalizations,
            ),
        )
        if repair.base_plan_id != authority.base_plan_id:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_stale_plan",
                "$.base_plan_id",
                "repair does not target the current canonical Plan",
                retryable=False,
            )
        if repair.base_retry_context_id != authority.retry_context_id:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_authority_drift",
                "$.base_retry_context_id",
                "repair does not target the current Goal retry authority",
                retryable=False,
            )
        if scoped_functional_plan_id(base_plan) != authority.base_plan_hash:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_stale_plan",
                "$.previous_plan",
                "base Plan content no longer matches repair authority",
                retryable=False,
            )

        goal_refs = tuple(item.goal_ref for item in repair.goal_replacements)
        scope_refs = tuple(item.scope_ref for item in repair.scope_step_replacements)
        answer_refs = tuple(
            item.goal_ref for item in repair.answer_binding_replacements
        )
        _require_unique(goal_refs, "$.goal_replacements", "Goal")
        _require_unique(scope_refs, "$.scope_step_replacements", "scope")
        _require_unique(
            answer_refs,
            "$.answer_binding_replacements",
            "Goal answer binding",
        )
        if set(goal_refs) != set(authority.editable_goal_refs):
            expected = sorted(authority.editable_goal_refs)
            actual = sorted(goal_refs)
            raise FunctionalGoalRetryError(
                "functional.goal_repair_boundary_violation",
                "$.goal_replacements",
                "repair must replace every and only directly failed editable "
                f"Goal; expected {expected}, got {actual}",
            )
        if set(scope_refs) != set(authority.editable_scope_refs):
            expected = sorted(authority.editable_scope_refs)
            actual = sorted(scope_refs)
            raise FunctionalGoalRetryError(
                "functional.goal_repair_boundary_violation",
                "$.scope_step_replacements",
                "repair must replace every and only directly failed scope "
                f"block; expected {expected}, got {actual}",
            )
        unauthorized_answer_refs = sorted(
            set(answer_refs) - set(authority.editable_answer_goal_refs)
        )
        if unauthorized_answer_refs:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_boundary_violation",
                "$.answer_binding_replacements",
                "answer-only replacement is allowed only for blocked Goals "
                "whose producer belongs to an editable Scope; unauthorized "
                f"Goals {unauthorized_answer_refs}",
            )

        publications = {
            item.goal_ref: item for item in authority.published_goal_results
        }
        goal_replacements = {
            item.goal_ref: item for item in repair.goal_replacements
        }
        scope_replacements = {
            item.scope_ref: item for item in repair.scope_step_replacements
        }
        answer_replacements = {
            item.goal_ref: item
            for item in repair.answer_binding_replacements
        }
        replaced_step_ids = {
            step_id
            for scope_ref in scope_replacements
            for step_id in authority.editable_scope_step_ids.get(
                scope_ref,
                (),
            )
        } | {
            step.step_id
            for scope in _iter_scopes(base_plan.root_scope)
            for goal in scope.goals
            if goal.goal_ref in goal_replacements
            for step in goal.steps
        }
        retained_step_ids = {
            step.step_id for step in base_plan.steps
        } - replaced_step_ids
        replacement_step_ids = [
            str(step.get("step_id", ""))
            for item in repair.goal_replacements
            for step in item.steps
        ] + [
            str(step.get("step_id", ""))
            for item in repair.scope_step_replacements
            for step in item.steps
        ]
        prior_step_owners = authority.repair_step_owners
        ownership_violations = sorted(
            (
                step_id,
                prior_step_owners[step_id],
                owner,
            )
            for owner, replacement_steps in (
                *(
                    (f"goal:{item.goal_ref}", item.steps)
                    for item in repair.goal_replacements
                ),
                *(
                    (f"scope:{item.scope_ref}", item.steps)
                    for item in repair.scope_step_replacements
                ),
            )
            for step in replacement_steps
            for step_id in (str(step.get("step_id", "")),)
            if step_id in prior_step_owners
            and prior_step_owners[step_id] != owner
        )
        if ownership_violations:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_step_owner_drift",
                "$.goal_replacements",
                "a prior step_id may only be reused in its original Goal or "
                f"scope replacement; violations {ownership_violations}",
            )
        repeated_replacement_ids = sorted(
            {
                step_id
                for step_id in replacement_step_ids
                if replacement_step_ids.count(step_id) > 1
            }
        )
        retained_collisions = sorted(
            set(replacement_step_ids).intersection(retained_step_ids)
        )
        if repeated_replacement_ids or retained_collisions:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_step_id_conflict",
                "$.goal_replacements",
                "replacement step_id values must be globally unique and may "
                "not collide with retained Plan steps; duplicate replacements "
                f"{repeated_replacement_ids}, retained collisions "
                f"{retained_collisions}",
            )
        publication_bindings = [
            item
            for item in scoped_published_goal_bindings(base_plan)
            if item.consumer_step_id not in replaced_step_ids
        ]
        def rebuild(scope: ScopedFunctionalScope) -> dict[str, Any]:
            payload = scope.to_payload()
            if scope.scope_ref in scope_replacements:
                replacement_steps = [
                    _resolve_published_step(
                        _thaw(item),
                        publications,
                        publication_bindings,
                    )
                    for item in scope_replacements[scope.scope_ref].steps
                ]
                merged_steps = _merge_scope_step_replacement(
                    scope.steps,
                    editable_step_ids=authority.editable_scope_step_ids.get(
                        scope.scope_ref,
                        (),
                    ),
                    replacement_steps=replacement_steps,
                )
                if merged_steps:
                    payload["steps"] = merged_steps
                else:
                    payload.pop("steps", None)
            goals: list[dict[str, Any]] = []
            for goal in scope.goals:
                replacement = goal_replacements.get(goal.goal_ref)
                if replacement is None:
                    goal_payload = goal.to_payload()
                    answer_replacement = answer_replacements.get(
                        goal.goal_ref
                    )
                    if answer_replacement is not None:
                        goal_payload["answer_from"] = dict(
                            answer_replacement.answer_from
                        )
                    goals.append(goal_payload)
                    continue
                replacement_payload: dict[str, Any] = {
                    "goal_ref": replacement.goal_ref,
                    "answer_from": dict(replacement.answer_from),
                }
                replacement_steps = [
                    _resolve_published_step(
                        _thaw(item),
                        publications,
                        publication_bindings,
                    )
                    for item in replacement.steps
                ]
                if replacement_steps:
                    replacement_payload["steps"] = replacement_steps
                goals.append(replacement_payload)
            if goals:
                payload["goals"] = goals
            elif "goals" in payload:
                payload.pop("goals")
            children = [rebuild(child) for child in scope.children]
            if children:
                payload["children"] = children
            elif "children" in payload:
                payload.pop("children")
            return payload

        candidate_payload = {
            "format": base_plan.format,
            "root_scope": rebuild(base_plan.root_scope),
        }
        goal_requirements: dict[str, FunctionalGoalAnswerRequirement] = {}
        locked_answers: dict[str, Mapping[str, str]] = {}
        previous_answers: dict[str, Mapping[str, str]] = {}
        authored_answers: dict[str, Mapping[str, str]] = {}
        goal_owner_scopes: dict[str, str] = {}
        for scope in _iter_scopes(base_plan.root_scope):
            for goal in scope.goals:
                goal_owner_scopes[goal.goal_ref] = scope.scope_ref
                previous_answers[goal.goal_ref] = goal.answer_from.to_payload()
                authored_answers[goal.goal_ref] = goal.answer_from.to_payload()
        authored_answers.update(
            {
                item.goal_ref: dict(item.answer_from)
                for item in repair.goal_replacements
            }
        )
        authored_answers.update(
            {
                item.goal_ref: dict(item.answer_from)
                for item in repair.answer_binding_replacements
            }
        )
        for goal_ref, goal_authority in authority.goal_authorities.items():
            owner_scope = goal_owner_scopes.get(goal_ref)
            if owner_scope is None:
                raise FunctionalGoalRetryError(
                    "functional.goal_repair_answer_source_invalid",
                    f"$.goals[{goal_ref!r}]",
                    "Goal retry authority references no canonical Plan Goal",
                    retryable=False,
                )
            goal_requirements[goal_ref] = FunctionalGoalAnswerRequirement(
                goal_ref=goal_ref,
                owner_scope_id=owner_scope,
                target_ref=goal_authority.answer_target_ref,
                answer_type=goal_authority.answer_type,
            )
            if goal_authority.status == "solved":
                locked_answers[goal_ref] = previous_answers[goal_ref]
        scope_parents = {
            scope.scope_ref: parent
            for scope, parent in _scopes_with_parent(base_plan.root_scope)
        }
        if capability_catalog is None:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_answer_source_invalid",
                "$.goal_replacements",
                "typed Goal answer derivation requires a capability catalog",
            )
        try:
            candidate_payload, answer_bindings = derive_goal_answer_bindings(
                candidate_payload,
                requirements=goal_requirements,
                scope_parents=scope_parents,
                capability_catalog=capability_catalog,
                locked_answers=locked_answers,
                authored_answers=authored_answers,
            )
        except FunctionalGoalAnswerBindingError as exc:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_answer_source_invalid",
                exc.path,
                exc.message,
                details=exc.to_feedback_payload()["details"],
            ) from exc
        plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
            candidate_payload
        )
        if plan is None:
            first = report.issues[0]
            raise FunctionalGoalRetryError(first.code, first.path, first.message)
        answer_rebindings = tuple(
            FunctionalGoalAnswerRebinding(
                goal_ref=item.goal_ref,
                previous_step_id=str(
                    previous_answers[item.goal_ref]["step_id"]
                ),
                previous_return_name=str(
                    previous_answers[item.goal_ref]["return"]
                ),
                selected_step_id=item.step_id,
                selected_return_name=item.return_name,
                answer_target_ref=item.target_ref,
                answer_type=item.answer_type,
                match_basis=item.match_basis,
            )
            for item in answer_bindings
            if previous_answers[item.goal_ref]
            != {"step_id": item.step_id, "return": item.return_name}
        )
        try:
            plan = apply_scoped_published_goal_bindings(
                plan,
                publication_bindings,
            )
        except ValueError as exc:
            raise FunctionalGoalRetryError(
                "functional.published_goal_result_invalid",
                "$.goal_replacements",
                str(exc),
            ) from exc
        plan_hash = scoped_functional_plan_id(plan)
        return FunctionalGoalRepairApplication(
            repair=repair,
            plan=plan,
            plan_hash=plan_hash,
            validation_report=report,
            published_goal_bindings=tuple(publication_bindings),
            answer_rebindings=answer_rebindings,
            normalizations=repair.normalizations,
        )


def _successful_execution_restore_authorities(
    execution: ScopedFunctionalGoalExecutionResult,
) -> dict[str, dict[str, str]]:
    """Bind contract-only retry locks to a successful typed transaction.

    The ordinary success path intentionally does not emit a retry checkpoint.
    A final authoring-contract failure can nevertheless require one Goal
    replacement after every runtime Goal passed.  In that case the committed
    transaction itself is the restore authority: exact compiled call, exact
    runtime result, problem provenance, and the three C3 restore signatures
    must all be present.
    """

    replay = execution.replay
    transaction = (
        replay.transactional_attempt_result if replay is not None else None
    )
    reconciliation = (
        replay.functional_reconciliation if replay is not None else None
    )
    if (
        transaction is None
        or reconciliation is None
        or transaction.failed_call_ids
        or transaction.blocked_call_ids
        or transaction.root_issues
    ):
        return {}
    report = transaction.execution_report
    compiled_by_call = {item.call_id: item for item in report.compiled_calls}
    results_by_call = {item.call_id: item for item in report.call_results}
    reconciled_ids = {item.call_id for item in reconciliation.calls}
    result: dict[str, dict[str, str]] = {}
    for call_id in sorted(transaction.verified_call_ids):
        compiled = compiled_by_call.get(call_id)
        call_result = results_by_call.get(call_id)
        if (
            compiled is None
            or call_result is None
            or call_result.status != "verified"
            or call_id not in reconciled_ids
            or compiled.problem_source_provenance is None
        ):
            continue
        signatures = functional_restored_call_authority_signatures(
            reconciliation,
            call_id,
        )
        result[call_id] = {
            "problem_source": (
                compiled.problem_source_provenance.semantic_signature()
            ),
            "source_read": signatures["source_read"],
            "runtime_write": signatures["runtime_write"],
            "answer_publication": signatures["answer_publication"],
        }
    return result


def _restored_seed(
    authority: FunctionalGoalRetryAuthority,
    execution: ScopedFunctionalGoalExecutionResult,
    *,
    next_plan: ScopedFunctionalPlan,
) -> FunctionalRestoredCallSeed:
    solved_calls = {
        step_id
        for item in authority.goal_authorities.values()
        if item.status == "solved"
        for step_id in item.closure_step_ids
    }
    if not solved_calls:
        return FunctionalRestoredCallSeed()
    checkpoint = execution.checkpoint
    if checkpoint is None:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_typed_checkpoint_missing",
            "$.checkpoint",
            "solved Goal restore has no Goal checkpoint v3",
            retryable=False,
        )
    next_step_ids = {item.step_id for item in next_plan.steps}
    if not solved_calls <= next_step_ids:
        raise FunctionalGoalRetryError(
            "functional.goal_repair_boundary_violation",
            "$.goal_replacements",
            "repair removed a call required by a solved Goal",
            retryable=False,
        )
    try:
        return checkpoint.restore_state.seed_for_calls(
            frozenset(solved_calls),
            mutable_publication_goal_unit_ids=(
                _repair_affected_goal_unit_ids(authority)
            ),
        )
    except Exception as exc:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_restore_drift",
            "$.checkpoint.restore_state",
            str(exc),
            retryable=False,
        ) from exc


def _repair_affected_goal_unit_ids(
    authority: FunctionalGoalRetryAuthority,
) -> tuple[str, ...]:
    """Return unsolved Goals whose consumer DAG may change during repair."""

    parents = {
        scope.scope_ref: parent
        for scope, parent in _scopes_with_parent(
            authority.base_plan.root_scope
        )
    }
    goal_scopes = {
        goal.goal_ref: scope.scope_ref
        for scope in _iter_scopes(authority.base_plan.root_scope)
        for goal in scope.goals
    }
    editable_scopes = set(authority.editable_scope_refs)
    affected: set[str] = set()
    for item in authority.goal_authorities.values():
        if item.status == "solved":
            continue
        owner_scope = goal_scopes.get(item.goal_ref)
        if item.editable or (
            owner_scope is not None
            and any(
                _scope_is_descendant_of(
                    owner_scope,
                    editable_scope,
                    parents,
                )
                for editable_scope in editable_scopes
            )
        ):
            affected.add(item.goal_unit_id)
    return tuple(sorted(affected))


def _scope_is_descendant_of(
    scope_ref: str,
    ancestor_ref: str,
    parents: Mapping[str, str | None],
) -> bool:
    current: str | None = scope_ref
    while current is not None:
        if current == ancestor_ref:
            return True
        current = parents.get(current)
    return False


def _goal_plans(plan: ScopedFunctionalPlan) -> dict[str, Any]:
    return {
        goal.goal_ref: goal
        for scope in _iter_scopes(plan.root_scope)
        for goal in scope.goals
    }


def _execution_goals(
    root: FunctionalGoalExecutionScope,
) -> dict[str, FunctionalGoalExecutionGoal]:
    return {
        goal.goal_ref: goal
        for scope in _iter_execution_scopes(root)
        for goal in scope.goals
    }


def _goal_report(
    execution: ScopedFunctionalGoalExecutionResult,
) -> dict[str, dict[str, Any]]:
    transaction = (
        execution.replay.transactional_attempt_result
        if execution.replay is not None
        else None
    )
    if transaction is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in transaction.goal_report.goals:
        goal_ref = item.goal_handle.removeprefix("answer:")
        result[goal_ref] = item.to_payload()
    return result


def _call_states(
    execution: ScopedFunctionalGoalExecutionResult,
) -> dict[str, str]:
    transaction = (
        execution.replay.transactional_attempt_result
        if execution.replay is not None
        else None
    )
    return {
        item.call_id: item.status
        for item in (
            transaction.execution_report.call_states
            if transaction is not None
            else ()
        )
    }


def _call_results(
    execution: ScopedFunctionalGoalExecutionResult,
) -> dict[str, Any]:
    transaction = (
        execution.replay.transactional_attempt_result
        if execution.replay is not None
        else None
    )
    return {
        item.call_id: item
        for item in (
            transaction.execution_report.call_results
            if transaction is not None
            else ()
        )
    }


def _symbolic_closure_passed(
    call_ids: Sequence[str],
    results: Mapping[str, Any],
) -> bool:
    for call_id in call_ids:
        item = results.get(call_id)
        if item is None:
            return False
        closure = item.symbolic_closure
        if closure is not None and closure.status not in {"not_applicable", "unique"}:
            return False
    return True


def _goal_issue_payloads(
    goal: FunctionalGoalExecutionGoal,
    answer: Mapping[str, Any] | None,
    *,
    root_issues: Sequence[Mapping[str, Any]] = (),
    forbidden_values: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    issues = [
        dict(step.typed_issue)
        for step in goal.steps
        if step.typed_issue is not None
    ]
    if answer is not None:
        issues.extend(dict(item) for item in answer.get("issues", ()))
        if answer.get("status") != "passed" and not answer.get("issues"):
            issues.append(
                {
                    "code": "functional.goal_answer_not_verified",
                    "message": f"answer status is {answer.get('status')}",
                }
            )
    issues.extend(dict(item) for item in root_issues)
    return [
        _prompt_safe_value(item, forbidden_values=forbidden_values)
        for item in issues
    ]


def _configuration_diagnostics(
    checkpoint: FunctionalGoalExecutionCheckpoint,
) -> tuple[dict[str, Any], ...]:
    diagnostics: list[dict[str, Any]] = []

    def consider(value: Mapping[str, Any] | None) -> None:
        if value is None:
            return
        payload = dict(value)
        if payload.get("retryability") == "configuration":
            diagnostics.append(payload)

    def visit(scope: FunctionalGoalExecutionScope) -> None:
        for step in scope.scope_steps:
            consider(step.typed_issue)
        for goal in scope.goals:
            for step in goal.steps:
                consider(step.typed_issue)
        for child in scope.children:
            visit(child)

    visit(checkpoint.root_scope)
    for item in checkpoint.root_issues:
        consider(item)
    return tuple(diagnostics)


def _retry_issue_signature(
    authority: FunctionalGoalRetryAuthority,
) -> str:
    """Hash only the typed failure state paired with one attempted Plan."""

    step_issues: list[dict[str, Any]] = []

    def visit(scope: Mapping[str, Any]) -> None:
        for step in scope.get("scope_steps", ()):
            if not isinstance(step, Mapping):
                continue
            typed_issue = step.get("typed_issue")
            if typed_issue is not None:
                step_issues.append(
                    {
                        "step_id": step.get("step_id"),
                        "status": step.get("status"),
                        "typed_issue": _thaw(typed_issue),
                    }
                )
        for goal in scope.get("goals", ()):
            if not isinstance(goal, Mapping):
                continue
            for step in goal.get("steps", ()):
                if not isinstance(step, Mapping):
                    continue
                typed_issue = step.get("typed_issue")
                if typed_issue is not None:
                    step_issues.append(
                        {
                            "step_id": step.get("step_id"),
                            "status": step.get("status"),
                            "typed_issue": _thaw(typed_issue),
                        }
                    )
        for child in scope.get("children", ()):
            if isinstance(child, Mapping):
                visit(child)

    visit(authority.retry_context.root_scope)
    return stable_hash(
        {
            "goals": {
                goal_ref: {
                    "status": item.status,
                    "issue_signature": item.issue_signature,
                }
                for goal_ref, item in sorted(
                    authority.goal_authorities.items()
                )
            },
            "scope_step_issues": sorted(
                step_issues,
                key=lambda item: (
                    str(item.get("step_id", "")),
                    str(item.get("status", "")),
                ),
            ),
        }
    )


def _published_goal_result(
    goal_plan: Any,
    execution_steps: Mapping[str, FunctionalGoalExecutionStep],
    call_results: Mapping[str, Any],
) -> PublishedGoalResult:
    producer = execution_steps.get(goal_plan.answer_from.step_id)
    if producer is None:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_publication_missing",
            f"$.goals[{goal_plan.goal_ref!r}]",
            "solved Goal has no answer producer in execution tree",
            retryable=False,
        )
    result = call_results.get(goal_plan.answer_from.step_id)
    write = next(
        (
            item
            for item in (
                result.state_writes if result is not None else ()
            )
            if item.return_name == goal_plan.answer_from.return_name
        ),
        None,
    )
    outputs = tuple(
        item
        for item in (
            result.runtime_results if result is not None else ()
        )
        if write is not None
        and item.produced_handle == write.produced_handle
    )
    if len(outputs) != 1:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_publication_missing",
            f"$.goals[{goal_plan.goal_ref!r}].answer_from",
            "solved Goal answer_from does not resolve to exactly one "
            "prompt-safe runtime output",
            retryable=False,
        )
    output = outputs[0]
    return PublishedGoalResult(
        goal_ref=goal_plan.goal_ref,
        producer_step_id=goal_plan.answer_from.step_id,
        return_name=goal_plan.answer_from.return_name,
        runtime_type=str(output.runtime_type or "Unknown"),
        value=output.value,
        value_omitted_reason=(
            str(output.value_omitted_reason)
            if output.value_omitted_reason is not None
            else None
        ),
    )


def _inherit_solved_goal_authority(
    plan: ScopedFunctionalPlan,
    *,
    goal_authorities: dict[str, FunctionalGoalRetryGoalAuthority],
    published: list[PublishedGoalResult],
    previous_authority: FunctionalGoalRetryAuthority | None,
    planning_context: ProblemPlanningContext,
    binding_catalog: ProblemPlanningBindingCatalog,
) -> frozenset[str]:
    """Carry forward unchanged solved Goals when this round never transacted."""

    if previous_authority is None:
        return frozenset()
    expected = (
        planning_context.planning_context_id,
        planning_context.problem_revision_id,
        planning_context.problem_semantic_hash,
        binding_catalog.binding_signature,
    )
    actual = (
        previous_authority.planning_context_id,
        previous_authority.problem_revision_id,
        previous_authority.problem_semantic_hash,
        previous_authority.problem_binding_catalog_signature,
    )
    if actual != expected:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_authority_drift",
            "$.previous_authority",
            "prior solved Goal authority belongs to another Problem revision",
            retryable=False,
        )

    current_goals = _goal_plans(plan)
    previous_goals = _goal_plans(previous_authority.base_plan)
    current_steps = {item.step_id: item for item in plan.steps}
    previous_steps = {
        item.step_id: item for item in previous_authority.base_plan.steps
    }
    publication_by_goal = {item.goal_ref: item for item in published}
    previous_publications = {
        item.goal_ref: item
        for item in previous_authority.published_goal_results
    }
    inherited: set[str] = set()
    for goal_ref, prior in previous_authority.goal_authorities.items():
        if prior.status != "solved":
            continue
        current_goal = current_goals.get(goal_ref)
        previous_goal = previous_goals.get(goal_ref)
        if current_goal is None or previous_goal is None:
            raise FunctionalGoalRetryError(
                "functional.goal_repair_boundary_violation",
                f"$.goals[{goal_ref!r}]",
                "repair removed a solved Goal",
                retryable=False,
            )
        changed_steps = tuple(
            sorted(
                step_id
                for step_id in prior.closure_step_ids
                if _frozen_step_payload(current_steps.get(step_id))
                != _frozen_step_payload(previous_steps.get(step_id))
            )
        )
        if (
            current_goal.answer_from != previous_goal.answer_from
            or tuple(
                _frozen_step_payload(item) for item in current_goal.steps
            )
            != tuple(
                _frozen_step_payload(item) for item in previous_goal.steps
            )
            or changed_steps
        ):
            raise FunctionalGoalRetryError(
                "functional.goal_repair_boundary_violation",
                f"$.goals[{goal_ref!r}]",
                "repair changed the answer or dependency closure of a solved Goal",
                retryable=False,
            )
        if goal_authorities[goal_ref].status == "solved":
            continue
        publication = previous_publications.get(goal_ref)
        if publication is None:
            raise FunctionalGoalRetryError(
                "functional.goal_retry_publication_missing",
                f"$.goals[{goal_ref!r}]",
                "prior solved Goal has no published final answer",
                retryable=False,
            )
        goal_authorities[goal_ref] = prior
        publication_by_goal[goal_ref] = publication
        inherited.add(goal_ref)

    published[:] = [
        publication_by_goal[key]
        for key in sorted(publication_by_goal)
    ]
    return frozenset(inherited)


def _frozen_step_payload(step: Any | None) -> Mapping[str, Any] | None:
    """Return the execution-semantic step wire used by solved boundaries."""

    if step is None:
        return None
    payload = step.to_payload()
    payload.pop("intent", None)
    return payload


def _scope_authority(
    root: FunctionalGoalExecutionScope,
    *,
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority],
    checkpoint: FunctionalGoalExecutionCheckpoint,
    root_issues: Sequence[Mapping[str, Any]] = (),
    promoted_scope_refs: frozenset[str] = frozenset(),
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, ScopeRetryStatus]]:
    editable: list[str] = []
    frozen: list[str] = []
    statuses: dict[str, ScopeRetryStatus] = {}
    root_issue_step_ids = {
        str(item["step_id"])
        for item in root_issues
        if item.get("step_id") is not None
    }
    for scope in _iter_execution_scopes(root):
        raw_direct_failure = any(
            step.status in {"authority_invalid", "runtime_failed"}
            or step.step_id in root_issue_step_ids
            for step in scope.scope_steps
        )
        consumers = {
            goal_id
            for step in scope.scope_steps
            for goal_id in checkpoint.goal_unit_ids.get(step.step_id, ())
        }
        consumer_states = {
            item.status
            for item in goal_authorities.values()
            if item.goal_unit_id in consumers
        }
        unsolved_consumers = {
            item.goal_unit_id
            for item in goal_authorities.values()
            if item.goal_unit_id in consumers and item.status != "solved"
        }
        direct_failure = raw_direct_failure and bool(unsolved_consumers)
        goal_relevant_steps = tuple(
            step
            for step in scope.scope_steps
            if checkpoint.goal_unit_ids.get(step.step_id)
        )
        is_frozen = (
            bool(scope.scope_steps)
            and consumer_states == {"solved"}
            and bool(goal_relevant_steps)
            and all(
                step.status == "runtime_verified"
                for step in goal_relevant_steps
            )
        )
        if direct_failure:
            statuses[scope.scope_ref] = "editable"
            editable.append(scope.scope_ref)
        elif is_frozen:
            statuses[scope.scope_ref] = "frozen"
            frozen.append(scope.scope_ref)
        elif scope.scope_steps:
            statuses[scope.scope_ref] = "open"
        else:
            statuses[scope.scope_ref] = "context"
    for scope_ref in promoted_scope_refs:
        statuses[scope_ref] = "editable"
        editable.append(scope_ref)
        if scope_ref in frozen:
            frozen.remove(scope_ref)
    return tuple(sorted(set(editable))), tuple(sorted(set(frozen))), statuses


def _scope_step_authority(
    plan: ScopedFunctionalPlan,
    *,
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority],
    editable_scope_refs: Sequence[str],
    frozen_scope_refs: Sequence[str],
    failed_scope_step_ids: frozenset[str],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    """Split mixed Scope blocks into editable and retained step authority.

    Goal-local blocks remain all-or-nothing. This split applies only to
    Scope-owned producers, where one physical Scope may serve both solved and
    unsolved Goals.
    """

    solved_closure = {
        step_id
        for authority in goal_authorities.values()
        if authority.status == "solved"
        for step_id in authority.closure_step_ids
    }
    repair_cone = {
        step_id
        for authority in goal_authorities.values()
        if authority.status != "solved"
        for step_id in authority.closure_step_ids
    } | set(failed_scope_step_ids)
    editable_scopes = set(editable_scope_refs)
    frozen_scopes = set(frozen_scope_refs)
    editable: dict[str, tuple[str, ...]] = {}
    frozen: dict[str, tuple[str, ...]] = {}
    for scope in _iter_scopes(plan.root_scope):
        owned = tuple(step.step_id for step in scope.steps)
        if not owned:
            if scope.scope_ref in editable_scopes:
                # An exact descendant relation may require the repair to add
                # the first scope-local producer.  Preserve the empty tuple as
                # explicit whole-block replacement authority.
                editable[scope.scope_ref] = ()
            continue
        owned_set = set(owned)
        if scope.scope_ref in editable_scopes:
            solved_owned = owned_set.intersection(solved_closure)
            if solved_owned:
                editable_ids = tuple(
                    step_id
                    for step_id in owned
                    if step_id in repair_cone and step_id not in solved_owned
                )
            else:
                # Preserve the original whole-block behavior when no solved
                # Goal depends on this Scope.
                editable_ids = owned
            frozen_ids = tuple(
                step_id for step_id in owned if step_id not in editable_ids
            )
            if not editable_ids and owned:
                raise FunctionalGoalRetryError(
                    "functional.goal_repair_group_expansion_required",
                    f"$.scopes[{scope.scope_ref!r}]",
                    "the failed Scope only contains producers frozen by solved "
                    "Goals; expand the repair group before changing them",
                    retryable=False,
                    details={"frozen_step_ids": list(frozen_ids)},
                )
            editable[scope.scope_ref] = editable_ids
            frozen[scope.scope_ref] = frozen_ids
        elif scope.scope_ref in frozen_scopes:
            frozen[scope.scope_ref] = owned
    return editable, frozen


def _editable_answer_binding_goal_refs(
    plan: ScopedFunctionalPlan,
    *,
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority],
    editable_scope_step_ids: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Allow only answer pointers invalidated by editable Scope producers."""

    editable_steps = {
        step_id
        for step_ids in editable_scope_step_ids.values()
        for step_id in step_ids
    }
    canonical_goals = _goal_plans(plan)
    return tuple(
        sorted(
            goal_ref
            for goal_ref, authority in goal_authorities.items()
            if authority.status in {"blocked", "pending"}
            and not authority.editable
            and goal_ref in canonical_goals
            and canonical_goals[goal_ref].answer_from.step_id
            in editable_steps
        )
    )


def _failed_scope_step_ids(
    root: FunctionalGoalExecutionScope,
    root_issues: Sequence[Mapping[str, Any]],
) -> frozenset[str]:
    root_issue_step_ids = {
        str(item["step_id"])
        for item in root_issues
        if item.get("step_id") is not None
    }
    return frozenset(
        step.step_id
        for scope in _iter_execution_scopes(root)
        for step in scope.scope_steps
        if step.status in {"authority_invalid", "runtime_failed"}
        or step.step_id in root_issue_step_ids
    )


def _cross_scope_repair_promotions(
    plan: ScopedFunctionalPlan,
    execution_root: FunctionalGoalExecutionScope,
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority],
) -> dict[str, str]:
    step_scopes = {
        step.step_id: scope.scope_ref
        for scope in _iter_scopes(plan.root_scope)
        for step in (
            *scope.steps,
            *(item for goal in scope.goals for item in goal.steps),
        )
    }
    parents = {
        scope.scope_ref: parent
        for scope, parent in _scopes_with_parent(plan.root_scope)
    }
    solved_steps = {
        step_id
        for authority in goal_authorities.values()
        if authority.status == "solved"
        for step_id in authority.closure_step_ids
    }
    destinations: dict[str, str] = {}
    for step in _execution_steps(execution_root).values():
        issue = step.typed_issue or {}
        if issue.get("code") != "functional.step_scope_visibility_drift":
            continue
        consumer_scope = step_scopes.get(step.step_id)
        if consumer_scope is None:
            continue
        for producer_step_id in _wire_step_result_ids(step.authored_step):
            if producer_step_id in solved_steps:
                continue
            producer_scope = step_scopes.get(producer_step_id)
            if producer_scope is None:
                continue
            destination = destinations.get(producer_step_id, producer_scope)
            lca = _scope_lca(destination, consumer_scope, parents)
            if lca != destination:
                destinations[producer_step_id] = lca
    return dict(sorted(destinations.items()))


def _relation_scope_repair_authority(
    plan: ScopedFunctionalPlan,
    *,
    checkpoint: FunctionalGoalExecutionCheckpoint,
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Open only the descendant scope that owns an exact missing relation.

    The diagnostic authority is produced by the relation resolver from the
    full scope tree.  This projector never infers an owner from Point names or
    error text, and never crosses into a sibling scope.
    """

    scope_parents = {
        scope.scope_ref: parent
        for scope, parent in _scopes_with_parent(plan.root_scope)
    }
    step_scopes = {
        step.step_id: scope.scope_ref
        for scope in _iter_scopes(plan.root_scope)
        for step in (
            *scope.steps,
            *(item for goal in scope.goals for item in goal.steps),
        )
    }
    goal_scopes = {
        goal.goal_ref: scope.scope_ref
        for scope in _iter_scopes(plan.root_scope)
        for goal in scope.goals
    }
    opened_scopes: set[str] = set()
    opened_goals: set[str] = set()
    known_scopes = frozenset(scope_parents)

    for diagnostic_index, payload in enumerate(
        checkpoint.diagnostic_authorities
    ):
        if (
            payload.get("retryability") != "planner_repairable"
            or payload.get("repair_action") != "place_step_in_relation_scope"
        ):
            continue
        diagnostic_path = (
            f"$.diagnostic_authorities[{diagnostic_index}]"
        )

        def authority_drift(
            reason: str,
            *,
            owner_scopes: tuple[str, ...] = (),
        ) -> None:
            raise FunctionalGoalRetryError(
                "functional.goal_retry_authority_drift",
                diagnostic_path,
                "relation repair diagnostic has no unique legal owner scope",
                retryable=False,
                details={
                    "reason": reason,
                    "diagnostic_code": payload.get("code"),
                    "step_id": payload.get("step_id"),
                    "relation_owner_scopes": list(owner_scopes),
                },
            )

        details = payload.get("authority_details")
        if not isinstance(details, Mapping):
            authority_drift("authority_details_missing")
        owner_values: list[str] = []
        singular = details.get("relation_owner_scope")
        if isinstance(singular, str):
            owner_values.append(singular)
        plural = details.get("relation_owner_scopes")
        if isinstance(plural, (tuple, list)):
            owner_values.extend(
                item for item in plural if isinstance(item, str)
            )
        observed = details.get("observed_relation")
        if isinstance(observed, Mapping):
            nested = observed.get("relation_owner_scopes")
            if isinstance(nested, (tuple, list)):
                owner_values.extend(
                    item for item in nested if isinstance(item, str)
                )
        owner_scopes = tuple(sorted(set(owner_values)))
        if len(owner_scopes) != 1:
            authority_drift(
                "relation_owner_scope_not_unique",
                owner_scopes=owner_scopes,
            )
        if owner_scopes[0] not in known_scopes:
            authority_drift(
                "relation_owner_scope_unknown",
                owner_scopes=owner_scopes,
            )

        step_id = payload.get("step_id")
        if not isinstance(step_id, str):
            authority_drift(
                "consumer_step_missing",
                owner_scopes=owner_scopes,
            )
        authored_scope = step_scopes.get(step_id)
        owner_scope = owner_scopes[0]
        if authored_scope is None:
            authority_drift(
                "consumer_step_scope_unknown",
                owner_scopes=owner_scopes,
            )
        if (
            _scope_lca(authored_scope, owner_scope, scope_parents)
            != authored_scope
        ):
            authority_drift(
                "relation_owner_is_not_consumer_descendant",
                owner_scopes=owner_scopes,
            )
        opened_scopes.add(owner_scope)
        consumer_goal_ids = frozenset(
            checkpoint.goal_unit_ids.get(step_id, ())
        )
        for goal_ref, authority in goal_authorities.items():
            goal_scope = goal_scopes.get(goal_ref)
            if (
                authority.status != "blocked"
                or authority.goal_unit_id not in consumer_goal_ids
                or goal_scope is None
                or _scope_lca(owner_scope, goal_scope, scope_parents)
                != owner_scope
            ):
                continue
            opened_goals.add(goal_ref)

    return tuple(sorted(opened_scopes)), tuple(sorted(opened_goals))


def _apply_step_promotions(
    plan: ScopedFunctionalPlan,
    promotions: Mapping[str, str],
) -> ScopedFunctionalPlan:
    """Materialize projector-approved owner changes in the repair base Plan."""

    if not promotions:
        return plan
    steps_by_target: dict[str, list[Any]] = {}
    for step in plan.steps:
        target_scope = promotions.get(step.step_id)
        if target_scope is not None:
            steps_by_target.setdefault(target_scope, []).append(step)

    known_scope_refs = {
        scope.scope_ref for scope in _iter_scopes(plan.root_scope)
    }
    unknown_targets = sorted(set(steps_by_target) - known_scope_refs)
    if unknown_targets:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_authority_drift",
            "$.step_promotions",
            f"repair promotion targets unknown scopes {unknown_targets}",
            retryable=False,
        )

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
                *steps_by_target.get(scope.scope_ref, ()),
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

    promoted_plan = ScopedFunctionalPlan(root_scope=rebuild(plan.root_scope))
    parsed, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        promoted_plan.to_payload()
    )
    if parsed is None:
        first = report.issues[0]
        raise FunctionalGoalRetryError(
            "functional.goal_retry_authority_drift",
            first.path,
            f"repair promotion produced an invalid Plan: {first.message}",
            retryable=False,
        )
    return promoted_plan


def _scopes_with_parent(
    scope: ScopedFunctionalScope,
    parent: str | None = None,
) -> tuple[tuple[ScopedFunctionalScope, str | None], ...]:
    return (
        (scope, parent),
        *(
            item
            for child in scope.children
            for item in _scopes_with_parent(child, scope.scope_ref)
        ),
    )


def _scope_lca(
    left: str,
    right: str,
    parents: Mapping[str, str | None],
) -> str:
    left_path: list[str] = []
    current: str | None = left
    while current is not None:
        left_path.append(current)
        current = parents.get(current)
    right_ancestors: set[str] = set()
    current = right
    while current is not None:
        right_ancestors.add(current)
        current = parents.get(current)
    common = next(
        (item for item in left_path if item in right_ancestors),
        None,
    )
    if common is None:
        raise FunctionalGoalRetryError(
            "functional.goal_retry_authority_drift",
            "$.scope_tree",
            "scope references do not belong to one connected authority tree",
            retryable=False,
            details={"left_scope": left, "right_scope": right},
        )
    return common


def _wire_step_result_ids(value: Any) -> frozenset[str]:
    if isinstance(value, Mapping):
        result = {
            str(value["step_id"])
            if set(value) == {"step_id", "return"}
            else ""
        }
        for item in value.values():
            result.update(_wire_step_result_ids(item))
        return frozenset(item for item in result if item)
    if isinstance(value, (tuple, list)):
        return frozenset(
            item
            for child in value
            for item in _wire_step_result_ids(child)
        )
    return frozenset()


_STEP_EXECUTION_STATUSES = (
    "valid",
    "authority_invalid",
    "ready",
    "runtime_verified",
    "runtime_failed",
    "blocked_by_dependency",
    "pruned_dead",
)


def _scope_step_status_summary(
    scope: FunctionalGoalExecutionScope,
) -> dict[str, int]:
    steps = (
        *scope.scope_steps,
        *(step for goal in scope.goals for step in goal.steps),
    )
    return {
        status: sum(step.status == status for step in steps)
        for status in _STEP_EXECUTION_STATUSES
    }


def _scope_execution_status(
    summary: Mapping[str, int],
) -> ScopeExecutionStatus:
    if not any(summary.values()):
        return "context_only"
    if summary["authority_invalid"]:
        return "authority_failed"
    if summary["runtime_failed"]:
        return "runtime_failed"
    if summary["blocked_by_dependency"]:
        return "dependency_blocked"
    if summary["ready"] or summary["valid"]:
        return "awaiting_execution"
    return "fully_verified"


def _scope_repair_permission(
    scope_ref: str,
    *,
    scope_status: ScopeRetryStatus,
    execution_status: ScopeExecutionStatus,
    editable_scope_step_ids: Mapping[str, tuple[str, ...]],
    frozen_scope_step_ids: Mapping[str, tuple[str, ...]],
) -> tuple[RepairPermission, str | None]:
    if scope_ref in editable_scope_step_ids or scope_status == "editable":
        if frozen_scope_step_ids.get(scope_ref):
            return "partially_editable", None
        return "editable", None
    if scope_status == "frozen":
        return "frozen", "solved_goal_closure"
    if execution_status == "context_only":
        return "context", "context_only"
    reasons = {
        "fully_verified": "outside_repair_cone",
        "authority_failed": "failure_outside_current_repair_authority",
        "runtime_failed": "failure_outside_current_repair_authority",
        "dependency_blocked": "upstream_dependency_failed",
        "awaiting_execution": "no_direct_failure",
    }
    return "read_only", reasons[execution_status]


def _goal_repair_permission(
    authority: FunctionalGoalRetryGoalAuthority,
    *,
    answer_binding_editable: bool,
) -> tuple[RepairPermission, str | None]:
    if authority.editable:
        return "editable", None
    if answer_binding_editable:
        return "answer_only", "only_answer_binding_is_editable"
    if authority.status == "solved":
        return "frozen", "solved_goal_verified"
    if authority.status == "blocked":
        return "read_only", "upstream_dependency_failed"
    if authority.status == "pending":
        return "read_only", "no_direct_failure"
    return "read_only", "outside_current_repair_authority"


def _step_retry_prompt_payload(
    step: FunctionalGoalExecutionStep,
    *,
    planning_context: ProblemPlanningContext,
    repair_permission: Literal["editable", "frozen", "read_only"],
    repair_reason: str | None = None,
) -> dict[str, Any]:
    payload = step.to_retry_prompt_payload(planning_context=planning_context)
    payload["repair_permission"] = repair_permission
    if repair_permission != "editable":
        payload["repair_reason"] = repair_reason or _step_repair_reason(step)
    return payload


def _step_repair_reason(step: FunctionalGoalExecutionStep) -> str:
    if step.status == "blocked_by_dependency":
        return "upstream_dependency_failed"
    if step.status == "runtime_verified":
        return "runtime_verified_outside_repair_cone"
    if step.status == "pruned_dead":
        return "pruned_dead"
    if step.status in {"authority_invalid", "runtime_failed"}:
        return "failure_outside_current_repair_authority"
    return "no_direct_failure"


def _retry_scope_prompt(
    scope: FunctionalGoalExecutionScope,
    *,
    planning_context: ProblemPlanningContext,
    goal_authorities: Mapping[str, FunctionalGoalRetryGoalAuthority],
    scope_statuses: Mapping[str, ScopeRetryStatus],
    step_promotions: Mapping[str, str],
    editable_scope_step_ids: Mapping[str, tuple[str, ...]],
    frozen_scope_step_ids: Mapping[str, tuple[str, ...]],
    editable_answer_goal_refs: Sequence[str] = (),
) -> dict[str, Any]:
    status_summary = _scope_step_status_summary(scope)
    execution_status = _scope_execution_status(status_summary)
    scope_permission, scope_reason = _scope_repair_permission(
        scope.scope_ref,
        scope_status=scope_statuses[scope.scope_ref],
        execution_status=execution_status,
        editable_scope_step_ids=editable_scope_step_ids,
        frozen_scope_step_ids=frozen_scope_step_ids,
    )
    payload: dict[str, Any] = {
        "scope_ref": scope.scope_ref,
        "execution_status": execution_status,
        "repair_permission": scope_permission,
        "step_status_summary": status_summary,
    }
    if scope_reason is not None:
        payload["repair_reason"] = scope_reason
    if scope.scope_ref in editable_scope_step_ids:
        payload["editable_step_ids"] = list(
            editable_scope_step_ids[scope.scope_ref]
        )
    if scope.scope_ref in frozen_scope_step_ids:
        payload["frozen_step_ids"] = list(
            frozen_scope_step_ids[scope.scope_ref]
        )
    promoted_step_ids = sorted(
        step_id
        for step_id, target_scope in step_promotions.items()
        if target_scope == scope.scope_ref
    )
    if promoted_step_ids:
        payload["promoted_step_ids"] = promoted_step_ids
    if scope.scope_steps:
        editable_ids = set(editable_scope_step_ids.get(scope.scope_ref, ()))
        frozen_ids = set(frozen_scope_step_ids.get(scope.scope_ref, ()))
        scope_steps: list[dict[str, Any]] = []
        for step in scope.scope_steps:
            if step.step_id in editable_ids:
                permission = "editable"
                reason = None
            elif step.step_id in frozen_ids or scope_permission == "frozen":
                permission = "frozen"
                reason = "retained_by_solved_goal_closure"
            else:
                permission = "read_only"
                reason = _step_repair_reason(step)
            scope_steps.append(
                _step_retry_prompt_payload(
                    step,
                    planning_context=planning_context,
                    repair_permission=permission,
                    repair_reason=reason,
                )
            )
        payload["scope_steps"] = scope_steps
    if scope.goals:
        goals: list[dict[str, Any]] = []
        for goal in scope.goals:
            authority = goal_authorities[goal.goal_ref]
            answer_binding_editable = (
                goal.goal_ref in editable_answer_goal_refs
            )
            goal_permission, goal_reason = _goal_repair_permission(
                authority,
                answer_binding_editable=answer_binding_editable,
            )
            item: dict[str, Any] = {
                "goal_ref": goal.goal_ref,
                "status": authority.status,
                "editable": authority.editable,
                "repair_permission": goal_permission,
                "required_answer": {
                    "target_ref": authority.answer_target_ref,
                    "answer_type": authority.answer_type,
                },
            }
            if goal_reason is not None:
                item["repair_reason"] = goal_reason
            if answer_binding_editable:
                item["answer_binding_editable"] = True
                item["current_answer_from"] = {
                    "step_id": authority.answer_producer_step_id,
                    "return": authority.answer_return_name,
                }
            if goal.steps:
                step_permission: Literal["editable", "frozen", "read_only"]
                if goal_permission == "editable":
                    step_permission = "editable"
                    step_reason = None
                elif goal_permission == "frozen":
                    step_permission = "frozen"
                    step_reason = "solved_goal_verified"
                else:
                    step_permission = "read_only"
                    step_reason = goal_reason
                item["steps"] = [
                    _step_retry_prompt_payload(
                        step,
                        planning_context=planning_context,
                        repair_permission=step_permission,
                        repair_reason=step_reason,
                    )
                    for step in goal.steps
                ]
            issues = [dict(issue) for issue in authority.issues]
            if issues:
                item["issues"] = issues
            goals.append(item)
        payload["goals"] = goals
    if scope.children:
        payload["children"] = [
            _retry_scope_prompt(
                child,
                planning_context=planning_context,
                goal_authorities=goal_authorities,
                scope_statuses=scope_statuses,
                step_promotions=step_promotions,
                editable_scope_step_ids=editable_scope_step_ids,
                frozen_scope_step_ids=frozen_scope_step_ids,
                editable_answer_goal_refs=editable_answer_goal_refs,
            )
            for child in scope.children
        ]
    return payload


def _resolve_published_step(
    value: Mapping[str, Any],
    publications: Mapping[str, PublishedGoalResult],
    bindings: list[ScopedPublishedGoalBinding],
) -> dict[str, Any]:
    payload = _thaw(value)
    step_id = str(payload.get("step_id", ""))
    raw_args = payload.get("args", {})
    if not isinstance(raw_args, dict):
        return payload
    args: dict[str, Any] = {}
    for arg_name, raw in raw_args.items():
        values = raw if isinstance(raw, list) else [raw]
        resolved: list[Any] = []
        for index, item in enumerate(values):
            if isinstance(item, dict) and set(item) == {"published_goal_ref"}:
                goal_ref = str(item["published_goal_ref"])
                publication = publications.get(goal_ref)
                if publication is None:
                    raise FunctionalGoalRetryError(
                        "functional.published_goal_result_unavailable",
                        (
                            f"$.steps[{step_id!r}].args[{str(arg_name)!r}]"
                            f"[{index}]"
                        ),
                        f"Goal {goal_ref!r} is not solved and published",
                    )
                resolved.append(
                    {
                        "step_id": publication.producer_step_id,
                        "return": publication.return_name,
                    }
                )
                bindings.append(
                    ScopedPublishedGoalBinding(
                        consumer_step_id=step_id,
                        arg_name=str(arg_name),
                        item_index=index,
                        published_goal_ref=goal_ref,
                        producer_step_id=publication.producer_step_id,
                        return_name=publication.return_name,
                    )
                )
            else:
                resolved.append(item)
        args[str(arg_name)] = resolved if isinstance(raw, list) else resolved[0]
    payload["args"] = args
    return payload


def _merge_scope_step_replacement(
    previous_steps: Sequence[Any],
    *,
    editable_step_ids: Sequence[str],
    replacement_steps: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge editable replacements around frozen steps by explicit order authority.

    A mixed scope can contain several editable runs separated by solved/frozen
    producers.  Treating the replacement as one block moves those producers to
    the end of the scope.  Instead, preserve both authored replacement order and
    frozen order, add every explicit StepResult dependency, and retain the old
    frozen anchors for replacement steps that reuse their prior id.
    """

    editable = set(editable_step_ids)
    previous = tuple(previous_steps)
    replacement = tuple(_thaw(item) for item in replacement_steps)
    frozen = tuple(step for step in previous if step.step_id not in editable)
    payloads = {
        **{step.step_id: step.to_payload() for step in frozen},
        **{str(step.get("step_id", "")): step for step in replacement},
    }
    if not replacement:
        return [step.to_payload() for step in frozen]
    replacement_ids = tuple(str(step.get("step_id", "")) for step in replacement)
    if any(not step_id for step_id in replacement_ids):
        raise FunctionalGoalRetryError(
            "functional.goal_repair_step_order_invalid",
            "$.scope_step_replacements",
            "scope replacement contains a step without step_id",
        )
    frozen_ids = tuple(step.step_id for step in frozen)
    if len(payloads) != len(frozen_ids) + len(replacement_ids):
        raise FunctionalGoalRetryError(
            "functional.goal_repair_step_order_invalid",
            "$.scope_step_replacements",
            "scope replacement step ids must remain unique during mixed merge",
        )

    successors: dict[str, set[str]] = {step_id: set() for step_id in payloads}
    indegree = {step_id: 0 for step_id in payloads}

    def precedes(before: str, after: str) -> None:
        if before == after or after in successors[before]:
            return
        successors[before].add(after)
        indegree[after] += 1

    for sequence in (replacement_ids, frozen_ids):
        for before, after in zip(sequence, sequence[1:]):
            precedes(before, after)

    previous_positions = {
        step.step_id: index for index, step in enumerate(previous)
    }
    editable_positions = tuple(
        index
        for index, step in enumerate(previous)
        if step.step_id in editable
    )
    if not editable_positions:
        raise FunctionalGoalRetryError(
            "functional.goal_repair_step_order_invalid",
            "$.scope_step_replacements",
            "scope replacement has no editable slot in the previous plan",
        )
    # Project the replacement sequence back onto the old editable slots when
    # that correspondence is provable. Frozen steps are semantic barriers. Two
    # editable islands have unambiguous endpoints, and equal-cardinality edits
    # have an ordinal one-to-one mapping. With three or more islands, however,
    # an added/removed and renamed step needs a retained old id to identify its
    # island; proportional placement would invent repair authority.
    replacement_slot_positions: dict[str, int] = {}
    if len(replacement_ids) == 1:
        replacement_id = replacement_ids[0]
        old_position = previous_positions.get(replacement_id)
        if old_position in editable_positions:
            replacement_slot_positions[replacement_id] = old_position
        else:
            first_slot = editable_positions[0]
            last_slot = editable_positions[-1]
            frozen_between = tuple(
                step.step_id
                for step in frozen
                if first_slot
                < previous_positions[step.step_id]
                < last_slot
            )
            if frozen_between:
                raise FunctionalGoalRetryError(
                    "functional.goal_repair_step_order_invalid",
                    "$.scope_step_replacements",
                    "single replacement step cannot be placed across frozen "
                    "editable intervals without preserving an old step id",
                    details={
                        "replacement_step_id": replacement_id,
                        "frozen_barrier_step_ids": list(frozen_between),
                    },
                )
            replacement_slot_positions[replacement_id] = first_slot
    elif (
        len(replacement_ids) != len(editable_positions)
        and sum(
            1
            for index, position in enumerate(editable_positions)
            if index == 0 or position != editable_positions[index - 1] + 1
        )
        >= 3
    ):
        editable_islands: list[tuple[int, ...]] = []
        for position in editable_positions:
            if not editable_islands or position != editable_islands[-1][-1] + 1:
                editable_islands.append((position,))
            else:
                editable_islands[-1] = (*editable_islands[-1], position)
        island_by_position = {
            position: island_index
            for island_index, island in enumerate(editable_islands)
            for position in island
        }
        retained_anchor_indices = {
            replacement_index: island_by_position[previous_positions[step_id]]
            for replacement_index, step_id in enumerate(replacement_ids)
            if previous_positions.get(step_id) in island_by_position
        }
        unresolved: list[str] = []
        for replacement_index, replacement_id in enumerate(replacement_ids):
            old_position = previous_positions.get(replacement_id)
            if old_position in island_by_position:
                replacement_slot_positions[replacement_id] = old_position
                continue
            previous_anchor = next(
                (
                    retained_anchor_indices[index]
                    for index in range(replacement_index - 1, -1, -1)
                    if index in retained_anchor_indices
                ),
                None,
            )
            next_anchor = next(
                (
                    retained_anchor_indices[index]
                    for index in range(
                        replacement_index + 1,
                        len(replacement_ids),
                    )
                    if index in retained_anchor_indices
                ),
                None,
            )
            if previous_anchor is not None and previous_anchor == next_anchor:
                island_index = previous_anchor
            elif previous_anchor is None and next_anchor == 0:
                island_index = 0
            elif (
                next_anchor is None
                and previous_anchor == len(editable_islands) - 1
            ):
                island_index = len(editable_islands) - 1
            else:
                unresolved.append(replacement_id)
                continue
            replacement_slot_positions[replacement_id] = editable_islands[
                island_index
            ][0]
        if unresolved:
            editable_island_ids = [
                [previous[position].step_id for position in island]
                for island in editable_islands
            ]
            frozen_barriers = [
                [
                    previous[position].step_id
                    for position in range(left[-1] + 1, right[0])
                ]
                for left, right in zip(editable_islands, editable_islands[1:])
            ]
            raise FunctionalGoalRetryError(
                "functional.goal_repair_step_order_invalid",
                "$.scope_step_replacements",
                "replacement cardinality changed across multiple frozen "
                "intervals, but renamed steps cannot be aligned to one prior "
                "editable interval",
                details={
                    "reason": "replacement_interval_alignment_ambiguous",
                    "replacement_step_ids": list(replacement_ids),
                    "unresolved_replacement_step_ids": unresolved,
                    "retained_step_ids": [
                        step_id
                        for step_id in replacement_ids
                        if step_id in previous_positions
                    ],
                    "editable_step_islands": editable_island_ids,
                    "frozen_barrier_step_ids": frozen_barriers,
                    "repair_action": (
                        "preserve_prior_step_id_in_each_changed_interval_or_"
                        "keep_replacement_cardinality"
                    ),
                },
            )
    else:
        old_span = len(editable_positions) - 1
        replacement_span = len(replacement_ids) - 1
        for replacement_index, replacement_id in enumerate(replacement_ids):
            # Integer half-up projection keeps both endpoints exact and
            # distributes inserted steps across the old editable intervals.
            projected_index = (
                replacement_index * old_span + replacement_span // 2
            ) // replacement_span
            replacement_slot_positions[replacement_id] = editable_positions[
                projected_index
            ]

    # Preserved ids retain their exact old slots. Reordering a preserved step
    # across a frozen barrier then becomes a cycle and fails the same audit.
    for replacement_id in replacement_ids:
        old_position = previous_positions.get(replacement_id)
        if old_position in editable_positions:
            replacement_slot_positions[replacement_id] = old_position

    slot_sequence = tuple(
        replacement_slot_positions[step_id] for step_id in replacement_ids
    )
    if any(left > right for left, right in zip(slot_sequence, slot_sequence[1:])):
        raise FunctionalGoalRetryError(
            "functional.goal_repair_step_order_invalid",
            "$.scope_step_replacements",
            "replacement order moves a preserved step across a frozen interval",
            details={
                "replacement_step_ids": list(replacement_ids),
                "projected_old_positions": list(slot_sequence),
            },
        )

    for replacement_id, old_position in replacement_slot_positions.items():
        for frozen_step in frozen:
            frozen_position = previous_positions[frozen_step.step_id]
            if frozen_position < old_position:
                precedes(frozen_step.step_id, replacement_id)
            elif frozen_position > old_position:
                precedes(replacement_id, frozen_step.step_id)

    for consumer_id, payload in payloads.items():
        for producer_id in _repair_step_result_dependencies(payload):
            if producer_id in payloads:
                precedes(producer_id, consumer_id)

    first_editable_position = next(
        (
            index
            for index, step in enumerate(previous)
            if step.step_id in editable
        ),
        len(previous),
    )
    replacement_positions = {
        step_id: index for index, step_id in enumerate(replacement_ids)
    }

    def stable_rank(step_id: str) -> tuple[int, int, int, str]:
        if step_id in previous_positions:
            return (previous_positions[step_id], 0, 0, step_id)
        return (
            first_editable_position,
            1,
            replacement_positions.get(step_id, len(replacement_ids)),
            step_id,
        )

    ready = sorted(
        (step_id for step_id, count in indegree.items() if count == 0),
        key=stable_rank,
    )
    ordered: list[str] = []
    while ready:
        step_id = ready.pop(0)
        ordered.append(step_id)
        for successor in sorted(successors[step_id], key=stable_rank):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
                ready.sort(key=stable_rank)
    if len(ordered) != len(payloads):
        blocked = sorted(
            (step_id for step_id, count in indegree.items() if count > 0)
        )
        raise FunctionalGoalRetryError(
            "functional.goal_repair_step_order_invalid",
            "$.scope_step_replacements",
            "replacement dependencies conflict with frozen scope order",
            details={"blocked_step_ids": blocked},
        )
    return [payloads[step_id] for step_id in ordered]


def _repair_step_result_dependencies(value: Any) -> frozenset[str]:
    """Collect explicit producer ids without inferring hidden object identity."""

    if isinstance(value, Mapping):
        if set(value) == {"step_id", "return"}:
            step_id = value.get("step_id")
            return frozenset((step_id,)) if isinstance(step_id, str) else frozenset()
        return frozenset(
            producer
            for child in value.values()
            for producer in _repair_step_result_dependencies(child)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return frozenset(
            producer
            for child in value
            for producer in _repair_step_result_dependencies(child)
        )
    return frozenset()


def _require_unique(values: Sequence[str], path: str, label: str) -> None:
    if len(set(values)) != len(values):
        raise FunctionalGoalRetryError(
            "functional.goal_repair_duplicate_target",
            path,
            f"{label} replacement targets must be unique",
        )


def _iter_scopes(root: ScopedFunctionalScope) -> tuple[ScopedFunctionalScope, ...]:
    return (root, *(item for child in root.children for item in _iter_scopes(child)))


def _plan_step_owners(plan: ScopedFunctionalPlan) -> dict[str, str]:
    owners: dict[str, str] = {}
    for scope in _iter_scopes(plan.root_scope):
        for step in scope.steps:
            owners[step.step_id] = f"scope:{scope.scope_ref}"
        for goal in scope.goals:
            for step in goal.steps:
                owners[step.step_id] = f"goal:{goal.goal_ref}"
    return dict(sorted(owners.items()))


def _iter_execution_scopes(
    root: FunctionalGoalExecutionScope,
) -> tuple[FunctionalGoalExecutionScope, ...]:
    return (
        root,
        *(item for child in root.children for item in _iter_execution_scopes(child)),
    )


def _execution_steps(
    root: FunctionalGoalExecutionScope,
) -> dict[str, FunctionalGoalExecutionStep]:
    return {
        step.step_id: step
        for scope in _iter_execution_scopes(root)
        for step in (
            *scope.scope_steps,
            *(item for goal in scope.goals for item in goal.steps),
        )
    }


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            str(key): _freeze(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "to_payload"):
        return _json_safe(value.to_payload())
    return str(value)


def _json_path(path: Sequence[Any]) -> str:
    return "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}" for item in path
    )


__all__ = [
    "FUNCTIONAL_GOAL_REPAIR_CONTRACT",
    "PLANNER_GOAL_RETRY_CONTEXT_CONTRACT",
    "FunctionalGoalRepair",
    "FunctionalGoalRepairApplication",
    "FunctionalGoalRepairService",
    "FunctionalGoalReplacement",
    "FunctionalGoalRetryAuthority",
    "FunctionalGoalRetryError",
    "FunctionalGoalRetryProjector",
    "FunctionalScopeStepReplacement",
    "PlannerGoalRetryContext",
    "PublishedGoalResult",
    "ScopedFunctionalGoalRetryAttempt",
    "ScopedFunctionalGoalRetryRunResult",
    "ScopedFunctionalGoalRetryService",
    "functional_goal_repair_schema",
    "functional_goal_repair_schema_for_authority",
    "planner_goal_retry_context_schema",
]
