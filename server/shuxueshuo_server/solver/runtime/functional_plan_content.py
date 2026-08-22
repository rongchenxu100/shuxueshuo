"""Code-owned Scope/Goal frame for LLM-authored FunctionalPlan content."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    EntityIdentitySourceSpec,
    LatestStateSourceSpec,
    PublicArgSourceSpec,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    FrozenJson,
    freeze_json,
    stable_hash,
    thaw_json,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanIssue,
    ScopedFunctionalPlanValidationReport,
    ScopedFunctionalPlanValidator,
    apply_scoped_published_goal_bindings,
    scoped_published_goal_bindings,
    scoped_functional_plan_id,
    scoped_functional_plan_schema,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
    referenced_functional_step_returns,
    unconsumed_duplicate_identity_arg_omissions,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCapability,
    FunctionalCapabilityReturn,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    normalize_runtime_type,
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)
from shuxueshuo_server.solver.runtime.return_object_authority import (
    ReturnObjectAuthorityResolution,
    ReturnObjectAuthorityResolver,
    ReturnRoleAuthorityResolver,
    identity_constraint_return_targets,
)
from shuxueshuo_server.solver.state_semantics import (
    object_kind_for_runtime_type,
)


FUNCTIONAL_PLAN_CONTENT_CONTRACT = "functional-plan-content/v2"


@dataclass(frozen=True)
class FunctionalPlanContentNormalization:
    code: str
    path: str
    message: str

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class FunctionalGoalAnswerRequirement:
    goal_ref: str
    owner_scope_id: str
    target_ref: str
    answer_type: str

    def to_payload(self) -> dict[str, str]:
        return {
            "goal_ref": self.goal_ref,
            "owner_scope_id": self.owner_scope_id,
            "target_ref": self.target_ref,
            "answer_type": self.answer_type,
        }


@dataclass(frozen=True)
class FunctionalGoalAnswerCandidate:
    step_id: str
    return_name: str
    runtime_type: str
    owner: str
    basis: str
    consumed: bool
    rank: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "return": self.return_name,
            "runtime_type": self.runtime_type,
            "owner": self.owner,
            "basis": self.basis,
            "consumed": self.consumed,
            "authority_rank": self.rank,
        }


@dataclass(frozen=True)
class FunctionalGoalAnswerBinding:
    goal_ref: str
    step_id: str
    return_name: str
    target_ref: str
    answer_type: str
    match_basis: str

    def to_payload(self) -> dict[str, str]:
        return {
            "goal_ref": self.goal_ref,
            "step_id": self.step_id,
            "return": self.return_name,
            "target_ref": self.target_ref,
            "answer_type": self.answer_type,
            "match_basis": self.match_basis,
        }


class FunctionalGoalAnswerBindingError(ValueError):
    """A prompt-safe failure to derive one unique Goal answer producer."""

    def __init__(
        self,
        *,
        goal_ref: str,
        target_ref: str,
        answer_type: str,
        candidates: Sequence[FunctionalGoalAnswerCandidate],
        reason: str,
        authored_answer: Mapping[str, str] | None = None,
    ) -> None:
        self.code = "functional.goal_answer_source_unresolved"
        self.path = f"$.goal_plans[{goal_ref!r}]"
        self.goal_ref = goal_ref
        self.target_ref = target_ref
        self.answer_type = answer_type
        self.candidates = tuple(candidates)
        self.reason = reason
        self.authored_answer = (
            MappingProxyType(dict(authored_answer))
            if authored_answer is not None
            else None
        )
        self.message = (
            f"Goal {goal_ref!r} requires one {answer_type} producer for "
            f"target {target_ref!r}, but {reason}"
        )
        super().__init__(self.message)

    def to_feedback_payload(self) -> dict[str, Any]:
        details: dict[str, Any] = {
            "goal_ref": self.goal_ref,
            "target_ref": self.target_ref,
            "answer_type": self.answer_type,
            "candidate_count": len(self.candidates),
            "candidates": [item.to_payload() for item in self.candidates],
        }
        if self.authored_answer is not None:
            details["authored_answer_from"] = dict(self.authored_answer)
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "details": details,
        }


@dataclass(frozen=True)
class FunctionalPlanAuthorityFrame:
    planning_context_id: str
    root_scope: Mapping[str, FrozenJson]
    scope_parents: Mapping[str, str | None]
    source_ref_domain_types: Mapping[str, Mapping[str, str]]
    source_facts: Mapping[str, tuple[Mapping[str, FrozenJson], ...]]
    goal_owners: Mapping[str, str]
    goal_answers: Mapping[str, FunctionalGoalAnswerRequirement]
    frame_id: str

    def __post_init__(self) -> None:
        frozen_root = freeze_json(self.root_scope)
        if not isinstance(frozen_root, Mapping):
            raise TypeError("FunctionalPlan authority root must be an object")
        object.__setattr__(self, "root_scope", frozen_root)
        object.__setattr__(
            self,
            "scope_parents",
            MappingProxyType(dict(self.scope_parents)),
        )
        object.__setattr__(
            self,
            "source_ref_domain_types",
            MappingProxyType(
                {
                    scope_id: MappingProxyType(dict(values))
                    for scope_id, values in self.source_ref_domain_types.items()
                }
            ),
        )
        frozen_facts: dict[str, tuple[Mapping[str, FrozenJson], ...]] = {}
        for scope_id, facts in self.source_facts.items():
            items: list[Mapping[str, FrozenJson]] = []
            for fact in facts:
                frozen = freeze_json(fact)
                if not isinstance(frozen, Mapping):
                    raise TypeError("FunctionalPlan source fact must be an object")
                items.append(frozen)
            frozen_facts[scope_id] = tuple(items)
        object.__setattr__(
            self,
            "source_facts",
            MappingProxyType(frozen_facts),
        )
        object.__setattr__(
            self,
            "goal_owners",
            MappingProxyType(dict(self.goal_owners)),
        )
        object.__setattr__(
            self,
            "goal_answers",
            MappingProxyType(dict(self.goal_answers)),
        )

    @classmethod
    def from_planning_context(
        cls,
        planning_context: ProblemPlanningContext,
    ) -> "FunctionalPlanAuthorityFrame":
        scopes = {item.scope_id: item for item in planning_context.scopes}
        if len(scopes) != len(planning_context.scopes):
            raise ValueError("duplicate scope in ProblemPlanningContext")
        roots = [
            item.scope_id
            for item in planning_context.scopes
            if item.parent_scope_id is None
        ]
        if len(roots) != 1:
            raise ValueError("ProblemPlanningContext must have exactly one root")
        children: dict[str, list[str]] = {scope_id: [] for scope_id in scopes}
        for item in planning_context.scopes:
            if item.parent_scope_id is None:
                continue
            if item.parent_scope_id not in children:
                raise ValueError("planning scope references an unknown parent")
            children[item.parent_scope_id].append(item.scope_id)

        goals: dict[str, list[str]] = {scope_id: [] for scope_id in scopes}
        goal_owners: dict[str, str] = {}
        goal_answers: dict[str, FunctionalGoalAnswerRequirement] = {}
        for goal in planning_context.goal_views:
            goal_ref = goal.answer_ref.ref
            if goal_ref in goal_owners:
                raise ValueError(f"duplicate prompt Goal ref {goal_ref!r}")
            if goal.owner_scope_id not in goals:
                raise ValueError("planning Goal references an unknown owner scope")
            goal_owners[goal_ref] = goal.owner_scope_id
            goals[goal.owner_scope_id].append(goal_ref)
            goal_payload = thaw_json(goal.goal_payload)
            assert isinstance(goal_payload, Mapping)
            target_ref = goal_payload.get("target", goal.answer_key)
            if not isinstance(target_ref, str) or not target_ref:
                raise ValueError(
                    f"planning Goal {goal_ref!r} has no scalar answer target"
                )
            answer_type = goal.answer_ref.value_type
            if not answer_type:
                raise ValueError(
                    f"planning Goal {goal_ref!r} has no answer value type"
                )
            goal_answers[goal_ref] = FunctionalGoalAnswerRequirement(
                goal_ref=goal_ref,
                owner_scope_id=goal.owner_scope_id,
                target_ref=target_ref,
                answer_type=answer_type,
            )

        def build(scope_id: str) -> dict[str, Any]:
            payload: dict[str, Any] = {"scope_ref": scope_id}
            if goals[scope_id]:
                payload["goal_refs"] = list(goals[scope_id])
            if children[scope_id]:
                payload["children"] = [build(item) for item in children[scope_id]]
            return payload

        root_scope = build(roots[0])
        scope_parents = {
            item.scope_id: item.parent_scope_id
            for item in planning_context.scopes
        }
        source_ref_domain_types = {
            item.scope_id: {
                str(payload["id"]): _entity_kind_domain_type(
                    str(payload["kind"])
                )
                for entity in item.entities
                if isinstance((payload := thaw_json(entity.payload)), Mapping)
                and isinstance(payload.get("id"), str)
                and isinstance(payload.get("kind"), str)
            }
            for item in planning_context.scopes
        }
        source_facts = {
            item.scope_id: tuple(
                fact.to_prompt_payload() for fact in item.facts
            )
            for item in planning_context.scopes
        }
        authority = {
            "planning_context_id": planning_context.planning_context_id,
            "root_scope": root_scope,
            "scope_parents": scope_parents,
            "source_ref_domain_types": source_ref_domain_types,
            "source_facts": source_facts,
            "goal_owners": goal_owners,
            "goal_answers": {
                key: value.to_payload()
                for key, value in sorted(goal_answers.items())
            },
        }
        return cls(
            planning_context_id=planning_context.planning_context_id,
            root_scope=root_scope,
            scope_parents=scope_parents,
            source_ref_domain_types=source_ref_domain_types,
            source_facts=source_facts,
            goal_owners=goal_owners,
            goal_answers=goal_answers,
            frame_id=stable_hash(authority),
        )

    @property
    def scope_refs(self) -> tuple[str, ...]:
        return tuple(self.scope_parents)

    @property
    def goal_refs(self) -> tuple[str, ...]:
        return tuple(self.goal_owners)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "root_scope": thaw_json(self.root_scope),
            "goal_answers": {
                key: {
                    "target_ref": value.target_ref,
                    "answer_type": value.answer_type,
                }
                for key, value in sorted(self.goal_answers.items())
            },
        }

    def authority_payload(self) -> dict[str, Any]:
        return {
            "planning_context_id": self.planning_context_id,
            "root_scope": thaw_json(self.root_scope),
            "scope_parents": dict(self.scope_parents),
            "source_ref_domain_types": {
                scope_id: dict(values)
                for scope_id, values in self.source_ref_domain_types.items()
            },
            "source_facts": {
                scope_id: [thaw_json(item) for item in facts]
                for scope_id, facts in self.source_facts.items()
            },
            "goal_owners": dict(self.goal_owners),
            "goal_answers": {
                key: value.to_payload()
                for key, value in self.goal_answers.items()
            },
            "frame_id": self.frame_id,
        }


@dataclass(frozen=True)
class FunctionalPlanContent:
    scope_steps: Mapping[str, FrozenJson]
    goal_plans: Mapping[str, FrozenJson]
    format: str = FUNCTIONAL_PLAN_CONTENT_CONTRACT

    def __post_init__(self) -> None:
        frozen_scope_steps = freeze_json(self.scope_steps)
        frozen_goal_plans = freeze_json(self.goal_plans)
        if not isinstance(frozen_scope_steps, Mapping) or not isinstance(
            frozen_goal_plans, Mapping
        ):
            raise TypeError("FunctionalPlan content collections must be objects")
        object.__setattr__(self, "scope_steps", frozen_scope_steps)
        object.__setattr__(self, "goal_plans", frozen_goal_plans)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "format": self.format,
            "goal_plans": thaw_json(self.goal_plans),
        }
        if self.scope_steps:
            payload["scope_steps"] = thaw_json(self.scope_steps)
        return payload


@dataclass(frozen=True)
class FunctionalPlanContentCompilation:
    content: FunctionalPlanContent | None
    plan: ScopedFunctionalPlan | None
    report: ScopedFunctionalPlanValidationReport
    normalizations: tuple[FunctionalPlanContentNormalization, ...] = ()
    answer_bindings: tuple[FunctionalGoalAnswerBinding, ...] = ()
    answer_binding_error: FunctionalGoalAnswerBindingError | None = None
    draft_only: bool = False


@dataclass(frozen=True)
class FunctionalFinalPlanContractValidation:
    """Bind a canonical final Plan audit to one exact Plan identity."""

    report: ScopedFunctionalPlanValidationReport
    final_plan_id: str | None
    round_trip_plan_id: str | None
    content: FunctionalPlanContent | None = None
    normalizations: tuple[FunctionalPlanContentNormalization, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.report.ok
            and self.final_plan_id is not None
            and self.final_plan_id == self.round_trip_plan_id
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": "functional-final-plan-contract-validation/v1",
            "ok": self.ok,
            "final_plan_id": self.final_plan_id,
            "round_trip_plan_id": self.round_trip_plan_id,
            "report": self.report.to_payload(),
            "normalizations": [
                item.to_payload() for item in self.normalizations
            ],
        }


def capability_bound_step_schema(
    *,
    base_step_ref: str,
    capability_catalog: FunctionalCapabilityCatalog,
    source_ref_schema: Mapping[str, Any],
    exact_result_ref_schema: Mapping[str, Any],
    authority_frame: FunctionalPlanAuthorityFrame | None = None,
) -> dict[str, Any]:
    """Bind every public argument to its declared Method input view.

    Named entities and verified source facts use SourceRef. A capability input
    may consume an anonymous step result only when its public contract opts in
    via ``allows_anonymous_result``. This wire choice is orthogonal to the
    Method view used to materialize a named SourceRef at runtime.
    """

    variants: list[dict[str, Any]] = []
    for capability_id, capability in sorted(capability_catalog.items.items()):
        arg_properties: dict[str, Any] = {}
        required_args: list[str] = []
        for arg in capability.args:
            if arg.input_view_mode is None:
                raise ValueError(
                    "planner_configuration_error: capability argument has no "
                    f"input view: {capability_id}.{arg.name}"
                )
            item_schema = deepcopy(
                exact_result_ref_schema
                if arg.allows_anonymous_result
                else source_ref_schema
            )
            if arg.allowed_refs:
                item_schema = {
                    "allOf": [item_schema],
                    "enum": list(arg.allowed_refs),
                }
            if arg.cardinality == "one":
                value_schema = item_schema
            else:
                value_schema = {
                    "oneOf": [
                        item_schema,
                        {
                            "type": "array",
                            "minItems": (
                                0 if arg.allows_empty_collection else 1
                            ),
                            "items": deepcopy(item_schema),
                        },
                    ]
                }
            arg_properties[arg.name] = value_schema
            if arg.required:
                required_args.append(arg.name)
        args_schema: dict[str, Any] = {
            "type": "object",
            "properties": arg_properties,
            "additionalProperties": False,
        }
        if required_args:
            args_schema["required"] = required_args
        if authority_frame is not None and capability.distinct_arg_groups:
            distinct_constraints: list[dict[str, Any]] = []
            source_refs = tuple(
                sorted(
                    {
                        ref
                        for values in authority_frame.source_ref_domain_types.values()
                        for ref in values
                    }
                )
            )
            args_by_name = {item.name: item for item in capability.args}
            for group in capability.distinct_arg_groups:
                public_names = tuple(
                    name for name in group if name in arg_properties
                )
                for index, left in enumerate(public_names):
                    for right in public_names[index + 1 :]:
                        for source_ref in source_refs:
                            properties: dict[str, Any] = {}
                            for name in (left, right):
                                occurrence: dict[str, Any] = {"const": source_ref}
                                if args_by_name[name].cardinality == "many":
                                    occurrence = {
                                        "anyOf": [
                                            occurrence,
                                            {
                                                "type": "array",
                                                "contains": {"const": source_ref},
                                            },
                                        ]
                                    }
                                properties[name] = occurrence
                            distinct_constraints.append(
                                {
                                    "not": {
                                        "required": [left, right],
                                        "properties": properties,
                                    }
                                }
                            )
            if distinct_constraints:
                args_schema["allOf"] = distinct_constraints
        target_returns = tuple(
            item
            for item in capability.returns
            if item.binding_mode != "internal_only"
        )
        target_properties: dict[str, Any] = {}
        for returned in target_returns:
            candidates = (
                _compatible_output_target_refs(
                    authority_frame,
                    return_runtime_type=returned.runtime_type,
                    selector=returned.output_target_selector,
                )
                if authority_frame is not None
                else ()
            )
            if authority_frame is not None and not candidates:
                continue
            target_schema: dict[str, Any] = deepcopy(source_ref_schema)
            if candidates:
                target_schema = {
                    "allOf": [target_schema],
                    "enum": list(candidates),
                }
            target_properties[returned.name] = target_schema
        expectation_returns = tuple(
            item
            for item in capability.returns
            if item.possible_forms
            and item.return_expectation_policy != "omit"
        )
        variants.append(
            {
                "allOf": [
                    {"$ref": base_step_ref},
                    {
                        "type": "object",
                        "properties": {
                            "capability_id": {"const": capability_id},
                            "args": args_schema,
                            "output_targets": (
                                {
                                    "type": "object",
                                    "minProperties": 1,
                                    "description": (
                                        "Optional bindings from produced return "
                                        "roles to visible existing named objects. "
                                        "This does not declare a return; anonymous "
                                        "returns are consumed directly as exact "
                                        "step results."
                                    ),
                                    "properties": target_properties,
                                    "additionalProperties": False,
                                }
                                if target_properties
                                else False
                            ),
                            "return_expectations": {
                                "type": "object",
                                "minProperties": 1,
                                "properties": {
                                    item.name: {
                                        "enum": list(item.possible_forms)
                                    }
                                    for item in expectation_returns
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                ]
            }
        )
    if not variants:
        raise ValueError(
            "planner_configuration_error: response schema capability catalog "
            "is empty"
        )
    return {
        "description": (
            "A capability-bound step. Named Math Entities and source Facts use "
            "string SourceRefs; object StepResultRefs are accepted only by "
            "arguments declared as exact anonymous results."
        ),
        "oneOf": variants,
    }


def capability_bound_base_step_schema(
    step_schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Relax only the generic array floor owned by a capability variant.

    The base Scope/Goal step schema cannot know which optional collection
    inputs accept ``[]``. Capability-bound variants do know, so the base must
    not reject the value before the specific argument contract is evaluated.
    """

    result = deepcopy(step_schema)
    result["properties"]["args"]["additionalProperties"]["oneOf"][1][
        "minItems"
    ] = 0
    return result


def functional_plan_content_schema(
    frame: FunctionalPlanAuthorityFrame,
    *,
    capability_catalog: FunctionalCapabilityCatalog | None = None,
) -> dict[str, Any]:
    """Return a strict schema bound to one exact Scope/Goal authority frame."""

    all_plan_defs = scoped_functional_plan_schema()["$defs"]
    plan_defs = {
        key: deepcopy(all_plan_defs[key])
        for key in (
            "source_ref",
            "step_result_ref",
            "functional_ref",
            "step",
            "answer_from",
        )
    }
    step_array = {
        "type": "array",
        "minItems": 1,
        "description": (
            "Steps owned by exactly one Scope or Goal container. A step object "
            "must never be copied between scope_steps and goal_plans.*.steps."
        ),
        "items": {"$ref": "#/$defs/step"},
    }
    goal_plan = {
        "type": "object",
        "required": ["answer_from"],
        "properties": {
            "steps": {
                **deepcopy(step_array),
                "description": (
                    "Goal-local steps used only to produce this Goal. Do not "
                    "repeat a Scope-owned shared or contextual step here."
                ),
            },
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
    plan_defs["step"]["properties"]["step_id"]["description"] = (
        "A globally unique step id. The complete step object must appear in "
        "exactly one ownership container: one scope_steps array or one "
        "goal_plans.*.steps array."
    )
    if capability_catalog is not None:
        plan_defs["step_base"] = capability_bound_base_step_schema(
            plan_defs["step"]
        )
        plan_defs["step"] = capability_bound_step_schema(
            base_step_ref="#/$defs/step_base",
            capability_catalog=capability_catalog,
            source_ref_schema={"$ref": "#/$defs/source_ref"},
            exact_result_ref_schema={
                "oneOf": [
                    {"$ref": "#/$defs/source_ref"},
                    {"$ref": "#/$defs/step_result_ref"},
                ]
            },
            authority_frame=frame,
        )
    goal_plan_properties: dict[str, Any] = {}
    for goal_ref in frame.goal_refs:
        requirement = frame.goal_answers[goal_ref]
        bound_goal_plan = deepcopy(goal_plan)
        bound_goal_plan["description"] = (
            f"Goal {goal_ref!r} targets {requirement.target_ref!r} and requires "
            f"one visible return of canonical type {requirement.answer_type!r}."
        )
        bound_goal_plan["properties"]["answer_from"]["description"] = (
            f"Select the producer for target {requirement.target_ref!r}; its "
            f"public return type must be {requirement.answer_type!r}."
        )
        goal_plan_properties[goal_ref] = bound_goal_plan
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "functional-plan-content.schema.json",
        "title": "Code-owned FunctionalPlan content v2",
        "type": "object",
        "required": ["format", "goal_plans"],
        "properties": {
            "format": {"const": FUNCTIONAL_PLAN_CONTENT_CONTRACT},
            "scope_steps": {
                "type": "object",
                "description": (
                    "Scope-owned steps: shared producers or contextual work "
                    "that belongs to the Scope rather than one Goal. A Scope "
                    "step is visible to descendant Goals and must not be copied "
                    "into a Goal steps array."
                ),
                "properties": {
                    scope_ref: {
                        **deepcopy(step_array),
                        "description": (
                            f"Steps owned by Scope {scope_ref!r}; these may be "
                            "consumed by its descendant Goals."
                        ),
                    }
                    for scope_ref in frame.scope_refs
                },
                "additionalProperties": False,
            },
            "goal_plans": {
                "type": "object",
                "description": (
                    "One answer binding and optional Goal-local steps for every "
                    "required Goal. Goal-local steps serve only that Goal and "
                    "are mutually exclusive with Scope-owned steps."
                ),
                "required": list(frame.goal_refs),
                "properties": goal_plan_properties,
                "additionalProperties": False,
            },
        },
        "$defs": plan_defs,
        "additionalProperties": False,
    }


def decode_single_json_object(
    raw: str,
) -> tuple[dict[str, Any], tuple[FunctionalPlanContentNormalization, ...]]:
    """Decode one JSON object, tolerating one redundant trailing closer."""

    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("expected a JSON object")
        return value, ()
    except json.JSONDecodeError as original:
        stripped = raw.strip()
        try:
            value, end = json.JSONDecoder().raw_decode(stripped)
        except json.JSONDecodeError:
            raise original
        suffix = stripped[end:]
        if not isinstance(value, dict) or suffix not in {"}", "]"}:
            raise original
        return value, (
            FunctionalPlanContentNormalization(
                code="functional.trailing_json_delimiter_removed",
                path="$",
                message=f"removed one redundant trailing {suffix!r}",
            ),
        )


class FunctionalPlanContentCompiler:
    """Validate LLM content and assemble the code-owned canonical Plan tree."""

    def compile_json(
        self,
        raw: str,
        *,
        frame: FunctionalPlanAuthorityFrame,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> FunctionalPlanContentCompilation:
        try:
            payload, normalizations = decode_single_json_object(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            issue = ScopedFunctionalPlanIssue(
                "functional.plan_content_invalid_json",
                "$",
                str(exc),
            )
            return FunctionalPlanContentCompilation(
                None,
                None,
                ScopedFunctionalPlanValidationReport((issue,)),
            )
        return self.compile_payload(
            payload,
            frame=frame,
            capability_catalog=capability_catalog,
            normalizations=normalizations,
        )

    def compile_payload(
        self,
        payload: object,
        *,
        frame: FunctionalPlanAuthorityFrame,
        capability_catalog: FunctionalCapabilityCatalog,
        normalizations: tuple[FunctionalPlanContentNormalization, ...] = (),
    ) -> FunctionalPlanContentCompilation:
        payload, wire_normalizations, wire_issues = _normalize_content_wire(
            payload,
            frame=frame,
            capability_catalog=capability_catalog,
        )
        normalizations = (*normalizations, *wire_normalizations)
        if wire_issues:
            draft = _structural_content_draft(payload, frame=frame)
            if draft is not None:
                content, plan = draft
                return FunctionalPlanContentCompilation(
                    content,
                    plan,
                    ScopedFunctionalPlanValidationReport(wire_issues),
                    normalizations,
                    draft_only=True,
                )
        errors = sorted(
            Draft202012Validator(
                functional_plan_content_schema(
                    frame,
                    capability_catalog=capability_catalog,
                )
            ).iter_errors(payload),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            issues = (
                *wire_issues,
                *tuple(
                ScopedFunctionalPlanIssue(
                    "functional.plan_content_schema_invalid",
                    _json_path(error.absolute_path),
                    error.message,
                    {
                        "validator": str(error.validator),
                        "validator_value": error.validator_value,
                        "repair_action": "repair_capability_arguments",
                    },
                )
                for error in errors
                ),
            )
            draft = _structural_content_draft(
                payload,
                frame=frame,
            )
            if draft is not None:
                content, plan = draft
                return FunctionalPlanContentCompilation(
                    content,
                    plan,
                    ScopedFunctionalPlanValidationReport(issues),
                    normalizations,
                    draft_only=True,
                )
            return FunctionalPlanContentCompilation(
                None,
                None,
                ScopedFunctionalPlanValidationReport(issues),
                normalizations,
            )
        assert isinstance(payload, dict)
        content = FunctionalPlanContent(
            scope_steps=payload.get("scope_steps", {}),
            goal_plans=payload["goal_plans"],
        )
        ownership_issues = _content_step_ownership_issues(payload)
        if ownership_issues:
            return FunctionalPlanContentCompilation(
                content,
                None,
                ScopedFunctionalPlanValidationReport(ownership_issues),
                normalizations,
            )
        authored_answers = {
            str(goal_ref): dict(goal_plan["answer_from"])
            for goal_ref, goal_plan in payload["goal_plans"].items()
        }
        plan_payload = _assemble_plan_payload(content, frame=frame)
        try:
            plan_payload, answer_bindings = derive_goal_answer_bindings(
                plan_payload,
                requirements=frame.goal_answers,
                scope_parents=frame.scope_parents,
                source_ref_domain_types=frame.source_ref_domain_types,
                capability_catalog=capability_catalog,
                authored_answers=authored_answers,
            )
        except FunctionalGoalAnswerBindingError as exc:
            issue = ScopedFunctionalPlanIssue(
                exc.code,
                exc.path,
                exc.message,
            )
            draft_plan, draft_report = (
                ScopedFunctionalPlanValidator().validate_payload_with_report(
                    plan_payload
                )
            )
            if draft_plan is not None:
                return FunctionalPlanContentCompilation(
                    content,
                    draft_plan,
                    ScopedFunctionalPlanValidationReport((issue,)),
                    normalizations,
                    answer_binding_error=exc,
                )
            return FunctionalPlanContentCompilation(
                content,
                None,
                ScopedFunctionalPlanValidationReport(
                    (
                        issue,
                        *(
                            ScopedFunctionalPlanIssue(
                                "functional.plan_content_assembly_failed",
                                item.path,
                                item.message,
                            )
                            for item in draft_report.issues
                        ),
                    )
                ),
                normalizations,
                answer_binding_error=exc,
            )
        normalizations = (
            *normalizations,
            *_answer_binding_normalizations(
                authored_answers=authored_answers,
                answer_bindings=answer_bindings,
            ),
        )
        plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
            plan_payload
        )
        if plan is None:
            issues = tuple(
                ScopedFunctionalPlanIssue(
                    "functional.plan_content_assembly_failed",
                    item.path,
                    item.message,
                )
                for item in report.issues
            )
            report = ScopedFunctionalPlanValidationReport(issues)
        return FunctionalPlanContentCompilation(
            content,
            plan,
            report,
            normalizations,
            answer_bindings,
        )

    def validate_final_plan(
        self,
        plan: ScopedFunctionalPlan | None,
        *,
        frame: FunctionalPlanAuthorityFrame,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> FunctionalFinalPlanContractValidation:
        """Round-trip one final Plan through the public content contract."""

        if plan is None:
            return FunctionalFinalPlanContractValidation(
                report=ScopedFunctionalPlanValidationReport(
                    (
                        ScopedFunctionalPlanIssue(
                            "functional.final_plan_missing",
                            "$",
                            "no canonical final Plan is available",
                        ),
                    )
                ),
                final_plan_id=None,
                round_trip_plan_id=None,
            )

        final_plan_id = scoped_functional_plan_id(plan)
        try:
            content = functional_plan_content_from_plan(plan, frame=frame)
        except (TypeError, ValueError) as exc:
            return FunctionalFinalPlanContractValidation(
                report=ScopedFunctionalPlanValidationReport(
                    (
                        ScopedFunctionalPlanIssue(
                            "functional.final_plan_projection_invalid",
                            "$",
                            str(exc),
                        ),
                    )
                ),
                final_plan_id=final_plan_id,
                round_trip_plan_id=None,
            )

        compilation = self.compile_payload(
            content.to_payload(),
            frame=frame,
            capability_catalog=capability_catalog,
        )
        issues = list(compilation.report.issues)
        round_trip_plan = compilation.plan
        publication_bindings = scoped_published_goal_bindings(plan)
        if round_trip_plan is not None and publication_bindings:
            try:
                round_trip_plan = apply_scoped_published_goal_bindings(
                    round_trip_plan,
                    publication_bindings,
                )
            except ValueError as exc:
                issues.append(
                    ScopedFunctionalPlanIssue(
                        "functional.final_plan_publication_drift",
                        "$",
                        str(exc),
                    )
                )
                round_trip_plan = None
        round_trip_plan_id = (
            scoped_functional_plan_id(round_trip_plan)
            if round_trip_plan is not None
            else None
        )
        if (
            round_trip_plan_id is not None
            and round_trip_plan_id != final_plan_id
        ):
            issues.append(
                ScopedFunctionalPlanIssue(
                    "functional.final_plan_contract_drift",
                    "$",
                    "canonical Plan changed while round-tripping its content contract",
                    {
                        "final_plan_id": final_plan_id,
                        "round_trip_plan_id": round_trip_plan_id,
                    },
                )
            )
        return FunctionalFinalPlanContractValidation(
            report=ScopedFunctionalPlanValidationReport(tuple(issues)),
            final_plan_id=final_plan_id,
            round_trip_plan_id=round_trip_plan_id,
            content=content,
            normalizations=compilation.normalizations,
        )


def _structural_content_draft(
    payload: object,
    *,
    frame: FunctionalPlanAuthorityFrame,
) -> tuple[FunctionalPlanContent, ScopedFunctionalPlan] | None:
    """Keep a parseable Scope/Goal tree when only capability schema is wrong.

    The base content schema accepts both SourceRef and StepResultRef and still
    enforces the exact Scope/Goal frame.  A payload that passes it is a useful
    PlanDraft: execution authority can localize the invalid step and Goal retry
    can replace that Goal without asking the model to regenerate siblings.
    """

    base_errors = tuple(
        Draft202012Validator(functional_plan_content_schema(frame)).iter_errors(
            payload
        )
    )
    if base_errors or not isinstance(payload, dict):
        return None
    ownership_issues = _content_step_ownership_issues(payload)
    if ownership_issues:
        return None
    content = FunctionalPlanContent(
        scope_steps=payload.get("scope_steps", {}),
        goal_plans=payload["goal_plans"],
    )
    plan_payload = _assemble_plan_payload(content, frame=frame)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        plan_payload
    )
    if plan is None or not report.ok:
        return None
    return content, plan


def functional_plan_content_from_plan(
    plan: ScopedFunctionalPlan,
    *,
    frame: FunctionalPlanAuthorityFrame,
) -> FunctionalPlanContent:
    """Project one canonical Plan back to its content-only authoring wire."""

    scope_steps: dict[str, Any] = {}
    goal_plans: dict[str, Any] = {}
    actual_scopes: set[str] = set()

    def visit(scope: Any) -> None:
        if scope.scope_ref in actual_scopes:
            raise ValueError(f"duplicate Plan scope {scope.scope_ref!r}")
        actual_scopes.add(scope.scope_ref)
        if scope.steps:
            scope_steps[scope.scope_ref] = [item.to_payload() for item in scope.steps]
        for goal in scope.goals:
            if goal.goal_ref in goal_plans:
                raise ValueError(f"duplicate Plan Goal {goal.goal_ref!r}")
            payload: dict[str, Any] = {}
            if goal.steps:
                payload["steps"] = [item.to_payload() for item in goal.steps]
            payload["answer_from"] = goal.answer_from.to_payload()
            goal_plans[goal.goal_ref] = payload
        for child in scope.children:
            visit(child)

    visit(plan.root_scope)
    if actual_scopes != set(frame.scope_refs):
        raise ValueError("Plan scope tree differs from its authority frame")
    if set(goal_plans) != set(frame.goal_refs):
        raise ValueError("Plan Goal set differs from its authority frame")
    for goal_ref, owner_scope in frame.goal_owners.items():
        if _goal_owner(plan, goal_ref) != owner_scope:
            raise ValueError("Plan Goal owner differs from its authority frame")
    return FunctionalPlanContent(
        scope_steps=scope_steps,
        goal_plans=goal_plans,
    )


def functional_plan_prompt_payload(plan: ScopedFunctionalPlan) -> dict[str, Any]:
    """Return the complete nested prior Plan for Goal-repair diagnosis."""

    return plan.to_payload()


def _normalize_content_wire(
    payload: object,
    *,
    frame: FunctionalPlanAuthorityFrame,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[
    object,
    tuple[FunctionalPlanContentNormalization, ...],
    tuple[ScopedFunctionalPlanIssue, ...],
]:
    if not isinstance(payload, dict) or payload.get("format") != (
        FUNCTIONAL_PLAN_CONTENT_CONTRACT
    ):
        return payload, (), ()
    normalized = deepcopy(payload)
    records: list[FunctionalPlanContentNormalization] = []
    normalized, step_map_records = normalize_empty_optional_step_maps(
        normalized
    )
    records.extend(step_map_records)

    scope_steps = normalized.get("scope_steps")
    if isinstance(scope_steps, dict):
        normalized["scope_steps"] = {
            key: value for key, value in scope_steps.items() if value != []
        }
        if not normalized["scope_steps"]:
            normalized.pop("scope_steps")
    goal_plans = normalized.get("goal_plans")
    if isinstance(goal_plans, dict):
        for goal_ref, goal in goal_plans.items():
            if isinstance(goal, dict) and goal.get("steps") == []:
                goal.pop("steps")
    normalized, arg_records = normalize_empty_optional_capability_args(
        normalized,
        capability_catalog=capability_catalog,
    )
    normalized, unknown_arg_records = normalize_unknown_capability_args(
        normalized,
        capability_catalog=capability_catalog,
    )
    normalized, interchangeable_arg_records = (
        normalize_interchangeable_capability_args(
            normalized,
            capability_catalog=capability_catalog,
        )
    )
    normalized, duplicate_identity_records = (
        normalize_unconsumed_duplicate_identity_args(
            normalized,
            frame=frame,
            capability_catalog=capability_catalog,
        )
    )
    normalized, role_records, role_issues = normalize_capability_return_roles(
        normalized,
        frame=frame,
        capability_catalog=capability_catalog,
    )
    normalized, named_ref_records = _normalize_named_entity_result_refs(
        normalized,
        frame=frame,
        capability_catalog=capability_catalog,
    )
    normalized, ownership_records = (
        _normalize_exact_cross_container_step_duplicates(
            normalized,
            frame=frame,
        )
    )
    return normalized, (
        *records,
        *arg_records,
        *unknown_arg_records,
        *interchangeable_arg_records,
        *duplicate_identity_records,
        *role_records,
        *named_ref_records,
        *ownership_records,
    ), role_issues


def normalize_empty_optional_step_maps(
    payload: object,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Drop empty optional maps from any authored step before schema checks.

    Pass 1 and Goal repair embed the same step wire in different containers.
    Recognizing the step by its public fields keeps this normalization shared
    while leaving malformed non-step mappings untouched for strict validation.
    """

    normalized = deepcopy(payload)
    records: list[FunctionalPlanContentNormalization] = []

    def visit(value: object, path: tuple[Any, ...]) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*path, index))
            return
        if not isinstance(value, dict):
            return
        is_step = isinstance(value.get("step_id"), str) and isinstance(
            value.get("capability_id"), str
        )
        if is_step:
            for field_name in ("output_targets", "return_expectations"):
                if value.get(field_name) != {}:
                    continue
                value.pop(field_name)
                records.append(
                    FunctionalPlanContentNormalization(
                        code="functional.empty_optional_step_map_omitted",
                        path=_json_path((*path, field_name)),
                        message=f"omitted empty optional {field_name}",
                    )
                )
        for key, item in tuple(value.items()):
            visit(item, (*path, key))

    visit(normalized, ())
    return normalized, tuple(records)


def normalize_unconsumed_duplicate_identity_args(
    payload: object,
    *,
    frame: FunctionalPlanAuthorityFrame,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Apply the shared optional identity-input omission contract."""

    if not isinstance(payload, dict):
        return payload, ()
    normalized = deepcopy(payload)
    steps, _step_scopes = _content_steps_and_scopes(normalized, frame=frame)
    consumers = referenced_functional_step_returns(normalized)
    records: list[FunctionalPlanContentNormalization] = []
    for step_id, step in steps.items():
        capability = capability_catalog.get(str(step.get("capability_id", "")))
        args = step.get("args")
        if capability is None or not isinstance(args, dict):
            continue
        output_targets = step.get("output_targets")
        omissions = unconsumed_duplicate_identity_arg_omissions(
            step_id=step_id,
            capability=capability,
            args=args,
            output_targets=(
                output_targets if isinstance(output_targets, Mapping) else {}
            ),
            consumed_returns=consumers,
        )
        for omission in omissions:
            step_path = _content_step_path(normalized, step_id)
            if step_path is None:
                continue
            args.pop(omission.arg_name, None)
            records.append(
                FunctionalPlanContentNormalization(
                    code="functional.unconsumed_duplicate_identity_arg_omitted",
                    path=_json_path((*step_path, "args", omission.arg_name)),
                    message=(
                        f"omitted optional identity arg {omission.arg_name} "
                        "because it duplicates a distinct input and none of "
                        "its identity-bound returns is consumed"
                    ),
                )
            )
            expectations = step.get("return_expectations")
            if not isinstance(expectations, dict):
                continue
            for return_name in omission.return_names:
                if return_name not in expectations:
                    continue
                expectations.pop(return_name)
                records.append(
                    FunctionalPlanContentNormalization(
                        code="functional.inactive_return_expectation_omitted",
                        path=_json_path(
                            (*step_path, "return_expectations", return_name)
                        ),
                        message=(
                            f"omitted {return_name} expectation after its "
                            "optional identity input was removed"
                        ),
                    )
                )
            if expectations == {}:
                step.pop("return_expectations", None)
    return normalized, tuple(records)


def normalize_capability_return_roles(
    payload: object,
    *,
    frame: FunctionalPlanAuthorityFrame,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[
    object,
    tuple[FunctionalPlanContentNormalization, ...],
    tuple[ScopedFunctionalPlanIssue, ...],
]:
    """Canonicalize public return roles only when typed constraints are unique."""

    if not isinstance(payload, dict):
        return payload, (), ()
    normalized = deepcopy(payload)
    steps, step_scopes = _content_steps_and_scopes(normalized, frame=frame)
    step_paths = {
        step_id: _content_step_path(normalized, step_id)
        for step_id in steps
    }
    capabilities = {
        step_id: capability_catalog.get(str(step.get("capability_id", "")))
        for step_id, step in steps.items()
    }
    active_returns: dict[str, tuple[FunctionalCapabilityReturn, ...]] = {}
    for step_id, step in steps.items():
        capability = capabilities[step_id]
        owner_scope_id = step_scopes.get(step_id)
        if capability is None or owner_scope_id is None:
            continue
        active_returns[step_id] = _active_returns_for_authored_step(
            step,
            steps=steps,
            capability=capability,
            capability_catalog=capability_catalog,
            owner_scope_id=owner_scope_id,
            scope_parents=frame.scope_parents,
            source_ref_domain_types=frame.source_ref_domain_types,
        )

    referenced_roles: dict[str, set[str]] = {
        step_id: set() for step_id in steps
    }
    for step_id, step in steps.items():
        declared = {item.name for item in active_returns.get(step_id, ())}
        for field_name in ("output_targets", "return_expectations"):
            value = step.get(field_name)
            if isinstance(value, Mapping):
                referenced_roles[step_id].update(set(value).intersection(declared))
        for producer_id, return_name in _step_result_refs(step.get("args", {})):
            if return_name in {
                item.name for item in active_returns.get(producer_id, ())
            }:
                referenced_roles.setdefault(producer_id, set()).add(return_name)
    goal_plans = normalized.get("goal_plans", {})
    if isinstance(goal_plans, Mapping):
        for goal in goal_plans.values():
            if not isinstance(goal, Mapping):
                continue
            answer = goal.get("answer_from")
            if not isinstance(answer, Mapping):
                continue
            producer_id = answer.get("step_id")
            return_name = answer.get("return")
            if not isinstance(producer_id, str) or not isinstance(
                return_name, str
            ):
                continue
            if return_name in {
                item.name for item in active_returns.get(producer_id, ())
            }:
                referenced_roles.setdefault(producer_id, set()).add(return_name)

    constraints: dict[tuple[str, str], set[str]] = {}
    paths: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    contexts: dict[tuple[str, str], set[str]] = {}
    observed_forms: dict[tuple[str, str], set[str]] = {}
    issues: list[ScopedFunctionalPlanIssue] = []

    def constrain(
        producer_id: str,
        authored_role: str,
        candidates: set[str],
        *,
        path: tuple[Any, ...],
        context: str,
        observed_form: str | None = None,
    ) -> None:
        key = (producer_id, authored_role)
        if key in constraints:
            constraints[key].intersection_update(candidates)
        else:
            constraints[key] = set(candidates)
        paths.setdefault(key, []).append(path)
        contexts.setdefault(key, set()).add(context)
        if observed_form is not None:
            observed_forms.setdefault(key, set()).add(observed_form)

    def candidate_names(
        producer_id: str,
        returned: Sequence[FunctionalCapabilityReturn],
    ) -> set[str]:
        result = {item.name for item in returned}
        used = result.intersection(referenced_roles.get(producer_id, set()))
        return used if len(used) == 1 else result

    for step_id, step in steps.items():
        capability = capabilities[step_id]
        owner_scope_id = step_scopes.get(step_id)
        base_path = step_paths.get(step_id)
        returned_items = active_returns.get(step_id, ())
        if capability is None or owner_scope_id is None or base_path is None:
            continue
        returned_by_name = {item.name: item for item in returned_items}
        output_targets = step.get("output_targets")
        if isinstance(output_targets, Mapping):
            for role, target in output_targets.items():
                if not isinstance(role, str):
                    continue
                target_types = (
                    _source_ref_runtime_types(
                        target,
                        owner_scope_id=owner_scope_id,
                        scope_parents=frame.scope_parents,
                        source_ref_domain_types=frame.source_ref_domain_types,
                    )
                    if isinstance(target, str)
                    else set()
                )
                declared = returned_by_name.get(role)
                if (
                    declared is not None
                    and declared.binding_mode != "internal_only"
                    and (
                        not isinstance(target, str)
                        or _source_ref_accepts_return_type(
                            target,
                            declared.runtime_type,
                            owner_scope_id=owner_scope_id,
                            scope_parents=frame.scope_parents,
                            source_ref_domain_types=(
                                frame.source_ref_domain_types
                            ),
                        )
                    )
                ):
                    continue
                candidates = tuple(
                    item
                    for item in returned_items
                    if item.binding_mode != "internal_only"
                )
                if target_types:
                    candidates = tuple(
                        item
                        for item in candidates
                        if not isinstance(target, str)
                        or _source_ref_accepts_return_type(
                            target,
                            item.runtime_type,
                            owner_scope_id=owner_scope_id,
                            scope_parents=frame.scope_parents,
                            source_ref_domain_types=(
                                frame.source_ref_domain_types
                            ),
                        )
                    )
                candidates = tuple(
                    item
                    for item in candidates
                    if not isinstance(output_targets.get(item.name), str)
                    or output_targets[item.name] == target
                )
                if declared is not None and not candidates:
                    continue
                constrain(
                    step_id,
                    role,
                    candidate_names(step_id, candidates),
                    path=(*base_path, "output_targets", role),
                    context="output_targets",
                )
        expectations = step.get("return_expectations")
        if isinstance(expectations, Mapping):
            for role, form in expectations.items():
                if not isinstance(role, str) or not isinstance(form, str):
                    continue
                declared = returned_by_name.get(role)
                if declared is not None and (
                    declared.return_expectation_policy == "omit"
                    or form in declared.possible_forms
                ):
                    continue
                candidates = tuple(
                    item
                    for item in returned_items
                    if item.return_expectation_policy != "omit"
                    if form in item.possible_forms
                    and (
                        expectations.get(item.name) in (None, form)
                    )
                )
                if declared is not None and not candidates:
                    continue
                constrain(
                    step_id,
                    role,
                    candidate_names(step_id, candidates),
                    path=(*base_path, "return_expectations", role),
                    context="return_expectations",
                    observed_form=form,
                )

    for consumer_id, consumer in steps.items():
        capability = capabilities[consumer_id]
        base_path = step_paths.get(consumer_id)
        if capability is None or base_path is None:
            continue
        args = consumer.get("args")
        if not isinstance(args, Mapping):
            continue
        declared_args = {item.name: item for item in capability.args}
        for arg_name, value in args.items():
            argument = declared_args.get(str(arg_name))
            accepted_types = (
                argument.accepted_item_types or (argument.runtime_type,)
                if argument is not None
                else ()
            )
            for producer_id, role in _step_result_refs(value):
                returned_items = active_returns.get(producer_id, ())
                declared = next(
                    (item for item in returned_items if item.name == role),
                    None,
                )
                if declared is not None and (
                    not accepted_types
                    or any(
                        runtime_type_compatible(expected, declared.runtime_type)
                        for expected in accepted_types
                    )
                ):
                    continue
                candidates = tuple(
                    item
                    for item in returned_items
                    if not accepted_types
                    or any(
                        runtime_type_compatible(expected, item.runtime_type)
                        for expected in accepted_types
                    )
                )
                if declared is not None and not candidates:
                    continue
                constrain(
                    producer_id,
                    role,
                    candidate_names(producer_id, candidates),
                    path=(*base_path, "args", arg_name),
                    context="step_result_ref",
                )

    if isinstance(goal_plans, Mapping):
        for goal_ref, goal in goal_plans.items():
            if not isinstance(goal, Mapping):
                continue
            answer = goal.get("answer_from")
            requirement = frame.goal_answers.get(str(goal_ref))
            if not isinstance(answer, Mapping) or requirement is None:
                continue
            producer_id = answer.get("step_id")
            role = answer.get("return")
            if not isinstance(producer_id, str) or not isinstance(role, str):
                continue
            returned_items = active_returns.get(producer_id, ())
            declared = next(
                (item for item in returned_items if item.name == role),
                None,
            )
            if (
                declared is not None
                and declared.binding_mode != "internal_only"
                and runtime_type_compatible(
                    requirement.answer_type, declared.runtime_type
                )
                and (
                    (target := _return_target_ref(
                        producer_id,
                        declared.name,
                        steps=steps,
                        capability_catalog=capability_catalog,
                    ))
                    in (None, requirement.target_ref)
                )
            ):
                continue
            candidates = tuple(
                item
                for item in returned_items
                if item.binding_mode != "internal_only"
                and runtime_type_compatible(
                    requirement.answer_type, item.runtime_type
                )
                and (
                    (target := _return_target_ref(
                        producer_id,
                        item.name,
                        steps=steps,
                        capability_catalog=capability_catalog,
                    ))
                    in (None, requirement.target_ref)
                )
            )
            if declared is not None and not candidates:
                continue
            constrain(
                producer_id,
                role,
                candidate_names(producer_id, candidates),
                path=("goal_plans", goal_ref, "answer_from", "return"),
                context="answer_from",
            )

    assignments: dict[tuple[str, str], str] = {}
    unresolved: set[tuple[str, str]] = set()
    by_producer: dict[str, set[str]] = {}
    for producer_id, authored_role in constraints:
        by_producer.setdefault(producer_id, set()).add(authored_role)
    for producer_id, authored_roles in sorted(by_producer.items()):
        remaining = set(authored_roles)
        while remaining:
            seed = min(remaining)
            component = {seed}
            component_roles = set(constraints[(producer_id, seed)])
            changed = True
            while changed:
                changed = False
                for authored_role in sorted(remaining - component):
                    candidate_set = constraints[(producer_id, authored_role)]
                    if component_roles.intersection(candidate_set):
                        component.add(authored_role)
                        component_roles.update(candidate_set)
                        changed = True
            remaining.difference_update(component)
            resolution = ReturnRoleAuthorityResolver.resolve(
                {
                    authored_role: constraints[(producer_id, authored_role)]
                    for authored_role in component
                }
            )
            if resolution.unique:
                assignments.update(
                    {
                        (producer_id, authored_role): public_role
                        for authored_role, public_role in (
                            resolution.assignments.items()
                        )
                    }
                )
            else:
                unresolved.update((producer_id, item) for item in component)

    records: list[FunctionalPlanContentNormalization] = []

    def rename_map(
        step_id: str,
        field_name: str,
        value: object,
        *,
        base_path: tuple[Any, ...],
    ) -> None:
        if not isinstance(value, dict):
            return
        for authored_role in tuple(value):
            public_role = assignments.get((step_id, str(authored_role)))
            if public_role is None or public_role == authored_role:
                continue
            authored_value = value[authored_role]
            if public_role in value and value[public_role] != authored_value:
                unresolved.add((step_id, str(authored_role)))
                continue
            value[public_role] = authored_value
            value.pop(authored_role)
            records.append(
                FunctionalPlanContentNormalization(
                    code="functional.return_role_normalized",
                    path=_json_path((*base_path, field_name, authored_role)),
                    message=(
                        f"replaced authored return role {authored_role!r} with "
                        f"the uniquely compatible public role {public_role!r}"
                    ),
                )
            )

    for step_id, step in steps.items():
        base_path = step_paths.get(step_id)
        if base_path is None:
            continue
        rename_map(
            step_id,
            "output_targets",
            step.get("output_targets"),
            base_path=base_path,
        )
        rename_map(
            step_id,
            "return_expectations",
            step.get("return_expectations"),
            base_path=base_path,
        )

    def rewrite_result_refs(value: object, path: tuple[Any, ...]) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                rewrite_result_refs(item, (*path, index))
            return
        if not isinstance(value, dict):
            return
        if set(value) == {"step_id", "return"}:
            producer_id = value.get("step_id")
            authored_role = value.get("return")
            if isinstance(producer_id, str) and isinstance(authored_role, str):
                public_role = assignments.get((producer_id, authored_role))
                if public_role is not None and public_role != authored_role:
                    value["return"] = public_role
                    records.append(
                        FunctionalPlanContentNormalization(
                            code="functional.return_role_normalized",
                            path=_json_path((*path, "return")),
                            message=(
                                f"replaced authored return role {authored_role!r} "
                                f"with the uniquely compatible public role "
                                f"{public_role!r}"
                            ),
                        )
                    )
            return
        for key, item in tuple(value.items()):
            rewrite_result_refs(item, (*path, key))

    rewrite_result_refs(normalized, ())

    for producer_id, authored_role in sorted(unresolved):
        capability = capabilities.get(producer_id)
        if capability is None:
            continue
        key = (producer_id, authored_role)
        candidate_roles = tuple(sorted(constraints.get(key, ())))
        relevant_returns = active_returns.get(producer_id, ())
        role_contexts = contexts.get(key, set())

        def legal_for_context(item: FunctionalCapabilityReturn) -> bool:
            if role_contexts.intersection(
                {"output_targets", "answer_from", "step_result_ref"}
            ) and item.binding_mode == "internal_only":
                return False
            if "return_expectations" in role_contexts and (
                not item.possible_forms
                or item.return_expectation_policy == "omit"
            ):
                return False
            return True

        fallback_roles = tuple(
            item.name
            for item in relevant_returns
            if legal_for_context(item)
        )
        forms = tuple(sorted(observed_forms.get(key, ())))
        issues.append(
            _return_role_issue(
                capability_id=capability.capability_id,
                step_id=producer_id,
                path=(paths.get(key) or [("steps", producer_id)])[0],
                observed_role=authored_role,
                expected_roles=candidate_roles or fallback_roles,
                context="/".join(sorted(contexts.get(key, ()))) or "return",
                observed_form=forms[0] if len(forms) == 1 else None,
                expected_forms={
                    item.name: item.possible_forms
                    for item in relevant_returns
                    if item.return_expectation_policy != "omit"
                },
            )
        )
    return normalized, tuple(records), tuple(issues)


def _return_role_issue(
    *,
    capability_id: str,
    step_id: str,
    path: tuple[Any, ...],
    observed_role: str,
    expected_roles: Sequence[str],
    context: str,
    observed_form: str | None = None,
    expected_forms: Mapping[str, Sequence[str]] | None = None,
) -> ScopedFunctionalPlanIssue:
    details: dict[str, Any] = {
        "capability_id": capability_id,
        "observed_role": observed_role,
        "expected_roles": sorted(set(expected_roles)),
        "return_context": context,
        "retryability": "planner_repairable",
        "repair_action": "repair_return_role",
    }
    if observed_form is not None:
        details["observed_form"] = observed_form
    if expected_forms:
        details["expected_forms"] = {
            role: list(forms)
            for role, forms in sorted(expected_forms.items())
            if forms
        }
    return ScopedFunctionalPlanIssue(
        "functional.step_contract_invalid",
        _json_path(path),
        (
            f"return role {observed_role!r} is not uniquely compatible with "
            f"capability {capability_id!r}; expected one of "
            f"{sorted(set(expected_roles))!r}"
        ),
        details,
    )


def _normalize_named_entity_result_refs(
    payload: object,
    *,
    frame: FunctionalPlanAuthorityFrame,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Replace a result ref with its unique named-Entity SourceRef.

    A return bound through ``output_targets`` or ``identity_arg`` already has a
    stable Problem identity.  Referring to that return as an anonymous step
    result asks the model to choose an implementation view that the compiler
    owns.  Normalize the wire before its capability-bound schema runs; later
    latest-state binding recreates the producer edge from the same object.
    """

    if not isinstance(payload, dict):
        return payload, ()
    normalized = deepcopy(payload)
    steps, step_scopes = _content_steps_and_scopes(normalized, frame=frame)
    step_locations = _content_step_locations(normalized, frame=frame)
    goal_answer_targets: dict[tuple[str, str], set[str]] = {}
    goal_plans = normalized.get("goal_plans", {})
    if isinstance(goal_plans, Mapping):
        for goal_ref, goal in goal_plans.items():
            requirement = frame.goal_answers.get(str(goal_ref))
            answer = goal.get("answer_from") if isinstance(goal, Mapping) else None
            if requirement is None or not isinstance(answer, Mapping):
                continue
            step_id = answer.get("step_id")
            return_name = answer.get("return")
            if isinstance(step_id, str) and isinstance(return_name, str):
                goal_answer_targets.setdefault(
                    (step_id, return_name), set()
                ).add(requirement.target_ref)
    writers_by_target: dict[
        str,
        list[tuple[_ContentStepLocation, str, str]],
    ] = {}
    for producer_step_id, producer in steps.items():
        location = step_locations.get(producer_step_id)
        capability = capability_catalog.get(
            str(producer.get("capability_id", ""))
        )
        if location is None or capability is None:
            continue
        active_returns = _active_returns_for_authored_step(
            producer,
            steps=steps,
            capability=capability,
            capability_catalog=capability_catalog,
            owner_scope_id=location.scope_id,
            scope_parents=frame.scope_parents,
            source_ref_domain_types=frame.source_ref_domain_types,
        )
        for returned in active_returns:
            target_ref = _wire_return_object_resolution(
                producer_step_id,
                returned.name,
                steps=steps,
                step_scopes=step_scopes,
                frame=frame,
                capability_catalog=capability_catalog,
                goal_answer_targets=goal_answer_targets,
            ).unique_target_ref
            if target_ref is not None:
                writers_by_target.setdefault(target_ref, []).append(
                    (location, returned.name, returned.runtime_type)
                )
    records: list[FunctionalPlanContentNormalization] = []

    def normalize_value(
        value: object,
        *,
        consumer_scope_id: str,
        consumer_step_id: str,
        accepted_runtime_types: Sequence[str],
        path: tuple[Any, ...],
    ) -> object:
        if isinstance(value, list):
            return [
                normalize_value(
                    item,
                    consumer_scope_id=consumer_scope_id,
                    consumer_step_id=consumer_step_id,
                    accepted_runtime_types=accepted_runtime_types,
                    path=(*path, index),
                )
                for index, item in enumerate(value)
            ]
        if not isinstance(value, dict) or set(value) != {"step_id", "return"}:
            return value
        producer_step_id = value.get("step_id")
        return_name = value.get("return")
        if not isinstance(producer_step_id, str) or not isinstance(
            return_name, str
        ):
            return value
        producer = steps.get(producer_step_id)
        capability = (
            capability_catalog.get(str(producer.get("capability_id", "")))
            if producer is not None
            else None
        )
        returned = (
            next(
                (
                    item
                    for item in capability.returns
                    if item.name == return_name
                ),
                None,
            )
            if capability is not None
            else None
        )
        if returned is None or returned.binding_mode == "internal_only":
            return value
        target_ref = _wire_return_object_resolution(
            producer_step_id,
            return_name,
            steps=steps,
            step_scopes=step_scopes,
            frame=frame,
            capability_catalog=capability_catalog,
            goal_answer_targets=goal_answer_targets,
        ).unique_target_ref
        if target_ref is None or not _source_ref_visible_from_scope(
            target_ref,
            owner_scope_id=consumer_scope_id,
            scope_parents=frame.scope_parents,
            source_ref_domain_types=frame.source_ref_domain_types,
        ):
            return value
        if not _source_ref_accepts_return_type(
            target_ref,
            returned.runtime_type,
            owner_scope_id=consumer_scope_id,
            scope_parents=frame.scope_parents,
            source_ref_domain_types=frame.source_ref_domain_types,
        ):
            return value
        consumer_location = step_locations.get(consumer_step_id)
        if consumer_location is None:
            return value
        compatible_writers = [
            (location, role)
            for location, role, runtime_type in writers_by_target.get(
                target_ref, ()
            )
            if _content_writer_visible_to_consumer(
                location,
                consumer_location,
                scope_parents=frame.scope_parents,
            )
            and (
                not accepted_runtime_types
                or any(
                    runtime_type_compatible(expected, runtime_type)
                    for expected in accepted_runtime_types
                )
            )
        ]
        if not compatible_writers:
            return value
        latest_order = max(item[0].order for item in compatible_writers)
        latest = {
            (item.step_id, role)
            for item, role in compatible_writers
            if item.order == latest_order
        }
        if latest != {(producer_step_id, return_name)}:
            return value
        records.append(
            FunctionalPlanContentNormalization(
                code="functional.named_entity_result_ref_normalized",
                path=_json_path(path),
                message=(
                    f"replaced {producer_step_id}.{return_name} with named "
                    f"Entity SourceRef {target_ref!r}; latest-state binding "
                    "preserves the producer dependency"
                ),
            )
        )
        return target_ref

    for step_id in sorted(steps):
        step = steps[step_id]
        args = step.get("args")
        scope_id = step_scopes[step_id]
        if not isinstance(args, dict):
            continue
        base_path = _content_step_path(normalized, step_id)
        if base_path is None:
            continue
        capability = capability_catalog.get(str(step.get("capability_id", "")))
        declared_args = {
            item.name: item
            for item in (capability.args if capability is not None else ())
        }
        for arg_name, value in tuple(args.items()):
            argument = declared_args.get(str(arg_name))
            if argument is None or argument.input_view_mode != "latest_state":
                continue
            accepted_runtime_types = (
                argument.accepted_item_types or (argument.runtime_type,)
            )
            args[arg_name] = normalize_value(
                value,
                consumer_scope_id=scope_id,
                consumer_step_id=step_id,
                accepted_runtime_types=accepted_runtime_types,
                path=(*base_path, "args", arg_name),
            )
    return normalized, tuple(records)


def _wire_return_object_resolution(
    step_id: str,
    return_name: str,
    *,
    steps: Mapping[str, Mapping[str, Any]],
    step_scopes: Mapping[str, str],
    frame: FunctionalPlanAuthorityFrame,
    capability_catalog: FunctionalCapabilityCatalog,
    goal_answer_targets: Mapping[tuple[str, str], set[str]] | None = None,
) -> ReturnObjectAuthorityResolution:
    """Resolve raw-wire return identity with the shared authority precedence."""

    step = steps.get(step_id)
    owner_scope_id = step_scopes.get(step_id)
    if step is None or owner_scope_id is None:
        return ReturnObjectAuthorityResolver.resolve()
    capability = capability_catalog.get(str(step.get("capability_id", "")))
    if capability is None:
        return ReturnObjectAuthorityResolver.resolve()
    returned = next(
        (item for item in capability.returns if item.name == return_name),
        None,
    )
    if returned is None:
        return ReturnObjectAuthorityResolver.resolve()
    output_targets = step.get("output_targets", {})
    explicit = (
        (str(output_targets[return_name]),)
        if isinstance(output_targets, Mapping)
        and isinstance(output_targets.get(return_name), str)
        and output_targets[return_name]
        else ()
    )
    args = step.get("args", {})
    declared: set[str] = set()
    selected: set[str] = set()
    if (
        returned.identity_policy == "preserve_input_object"
        and returned.identity_arg is not None
    ):
        if isinstance(args, Mapping) and returned.identity_arg in args:
            declared.update(
                _value_target_refs(
                    args[returned.identity_arg],
                    steps=steps,
                    capability_catalog=capability_catalog,
                    seen=frozenset({(step_id, return_name)}),
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
            selected.update(
                _wire_auto_input_object_refs(
                    auto_arg,
                    args=args,
                    steps=steps,
                    capability_catalog=capability_catalog,
                    owner_scope_id=owner_scope_id,
                    frame=frame,
                    seen=frozenset({(step_id, return_name)}),
                )
            )
    constrained = identity_constraint_return_targets(
        capability.identity_constraints,
        return_name=return_name,
        resolve_arg_targets=lambda arg_name, object_role: (
            {
                target
                for value in _wire_arg_values(args, arg_name)
                for target in (
                    _wire_value_object_role_targets(
                        value,
                        role=object_role,
                        steps=steps,
                        capability_catalog=capability_catalog,
                        seen=frozenset({(step_id, return_name)}),
                    )
                    if object_role is not None
                    else _value_target_refs(
                        value,
                        steps=steps,
                        capability_catalog=capability_catalog,
                        seen=frozenset({(step_id, return_name)}),
                    )
                )
            }
        ),
    )
    return ReturnObjectAuthorityResolver.resolve(
        explicit_output_targets=explicit,
        goal_answer_targets=(goal_answer_targets or {}).get(
            (step_id, return_name), ()
        ),
        identity_constraint_targets=constrained,
        declared_identity_targets=declared,
        code_selected_targets=selected,
    )


def _wire_arg_values(
    args: object,
    arg_name: str,
) -> tuple[Any, ...]:
    if not isinstance(args, Mapping) or arg_name not in args:
        return ()
    value = args[arg_name]
    return tuple(value) if isinstance(value, list) else (value,)


def _wire_value_object_role_targets(
    value: Any,
    *,
    role: str,
    steps: Mapping[str, Mapping[str, Any]],
    capability_catalog: FunctionalCapabilityCatalog,
    seen: frozenset[tuple[str, str]],
) -> set[str]:
    """Project one object role through raw StepResult wire deterministically."""

    if not isinstance(value, Mapping) or set(value) != {"step_id", "return"}:
        return set()
    producer_step_id = str(value["step_id"])
    return_name = str(value["return"])
    key = (producer_step_id, f"{return_name}#role:{role}")
    if key in seen:
        return set()
    producer = steps.get(producer_step_id)
    if producer is None:
        return set()
    capability = capability_catalog.get(
        str(producer.get("capability_id", ""))
    )
    if capability is None:
        return set()
    returned = next(
        (item for item in capability.returns if item.name == return_name),
        None,
    )
    if returned is None:
        return set()
    args = producer.get("args", {})
    if not isinstance(args, Mapping):
        args = {}
    result: set[str] = set()
    for projection in returned.object_role_projections:
        if projection.role != role:
            continue
        if projection.source_arg is not None:
            values = args.get(projection.source_arg, ())
            values = values if isinstance(values, list) else (values,)
            for source in values:
                if projection.source_object_role is None:
                    result.update(
                        _value_target_refs(
                            source,
                            steps=steps,
                            capability_catalog=capability_catalog,
                            seen=seen | {key},
                        )
                    )
                else:
                    result.update(
                        _wire_value_object_role_targets(
                            source,
                            role=projection.source_object_role,
                            steps=steps,
                            capability_catalog=capability_catalog,
                            seen=seen | {key},
                        )
                    )
            continue
        if projection.source_return is None:
            continue
        source_ref = {
            "step_id": producer_step_id,
            "return": projection.source_return,
        }
        if projection.source_object_role is None:
            result.update(
                _value_target_refs(
                    source_ref,
                    steps=steps,
                    capability_catalog=capability_catalog,
                    seen=seen | {key},
                )
            )
        else:
            result.update(
                _wire_value_object_role_targets(
                    source_ref,
                    role=projection.source_object_role,
                    steps=steps,
                    capability_catalog=capability_catalog,
                    seen=seen | {key},
                )
            )
    return result


def _wire_auto_input_object_refs(
    auto_arg: Any,
    *,
    args: object,
    steps: Mapping[str, Mapping[str, Any]],
    capability_catalog: FunctionalCapabilityCatalog,
    owner_scope_id: str,
    frame: FunctionalPlanAuthorityFrame,
    seen: frozenset[tuple[str, str]],
) -> frozenset[str]:
    """Resolve a hidden identity input from its typed contract."""

    declaration = auto_arg.input_binding
    source = declaration.source
    derivation = declaration.derivation
    source_arg: str | None = None
    declared_entity_ref: str | None = None
    if isinstance(source, LatestStateSourceSpec):
        source_arg = source.entity_arg
        declared_entity_ref = source.entity_arg
    elif isinstance(source, PublicArgSourceSpec):
        source_arg = source.arg_name
    elif isinstance(source, EntityIdentitySourceSpec):
        source_arg = source.arg_name
    if source_arg is not None:
        targets = frozenset(
            target
            for value in _wire_arg_values(args, source_arg)
            for target in _value_target_refs(
                value,
                steps=steps,
                capability_catalog=capability_catalog,
                seen=seen,
            )
        )
        if targets:
            return targets
    if declared_entity_ref is not None:
        current: str | None = owner_scope_id
        while current is not None:
            if declared_entity_ref in frame.source_ref_domain_types.get(
                current, {}
            ):
                return frozenset((declared_entity_ref,))
            current = frame.scope_parents.get(current)
        return frozenset()
    if isinstance(derivation, CanonicalSymbolDerivationSpec):
        return _wire_auto_selector_object_refs(
            f"symbol:{derivation.symbol_name}",
            owner_scope_id=owner_scope_id,
            frame=frame,
        )
    return frozenset()


def _wire_auto_selector_object_refs(
    selector: str,
    *,
    owner_scope_id: str,
    frame: FunctionalPlanAuthorityFrame,
) -> frozenset[str]:
    selector_kind, separator, local_ref = selector.partition(":")
    expected_domain_type = {
        "function": "QuadraticFunction",
        "point": "Point",
        "symbol": "Symbol",
        "line": "Line",
        "ray": "Ray",
        "polygon": "Polygon",
    }.get(selector_kind)
    if not separator or expected_domain_type is None or not local_ref:
        return frozenset()
    current: str | None = owner_scope_id
    while current is not None:
        actual = frame.source_ref_domain_types.get(current, {}).get(local_ref)
        if actual is not None:
            return (
                frozenset((local_ref,))
                if actual == expected_domain_type
                else frozenset()
            )
        current = frame.scope_parents.get(current)
    return frozenset()


def _content_steps_and_scopes(
    payload: Mapping[str, Any],
    *,
    frame: FunctionalPlanAuthorityFrame,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    steps: dict[str, dict[str, Any]] = {}
    scopes: dict[str, str] = {}
    scope_steps = payload.get("scope_steps", {})
    if isinstance(scope_steps, Mapping):
        for scope_ref, items in scope_steps.items():
            if not isinstance(items, list):
                continue
            for step in items:
                if not isinstance(step, dict) or not isinstance(
                    step.get("step_id"), str
                ):
                    continue
                steps[step["step_id"]] = step
                scopes[step["step_id"]] = str(scope_ref)
    goal_plans = payload.get("goal_plans", {})
    if isinstance(goal_plans, Mapping):
        for goal_ref, goal in goal_plans.items():
            if not isinstance(goal, Mapping) or not isinstance(
                goal.get("steps"), list
            ):
                continue
            owner_scope_id = frame.goal_owners.get(str(goal_ref))
            if owner_scope_id is None:
                continue
            for step in goal["steps"]:
                if not isinstance(step, dict) or not isinstance(
                    step.get("step_id"), str
                ):
                    continue
                steps[step["step_id"]] = step
                scopes[step["step_id"]] = owner_scope_id
    return steps, scopes


@dataclass(frozen=True)
class _ContentStepLocation:
    step_id: str
    scope_id: str
    goal_ref: str | None
    order: int


def _content_step_locations(
    payload: Mapping[str, Any],
    *,
    frame: FunctionalPlanAuthorityFrame,
) -> dict[str, _ContentStepLocation]:
    """Index wire steps in the exact order used by Plan assembly."""

    scope_steps = payload.get("scope_steps", {})
    goal_plans = payload.get("goal_plans", {})
    locations: dict[str, _ContentStepLocation] = {}
    duplicates: set[str] = set()
    order = 0

    def add(step: object, *, scope_id: str, goal_ref: str | None) -> None:
        nonlocal order
        if not isinstance(step, Mapping) or not isinstance(
            step.get("step_id"), str
        ):
            return
        step_id = str(step["step_id"])
        location = _ContentStepLocation(step_id, scope_id, goal_ref, order)
        order += 1
        if step_id in locations:
            duplicates.add(step_id)
        else:
            locations[step_id] = location

    def visit(scope: Mapping[str, Any]) -> None:
        scope_id = str(scope["scope_ref"])
        if isinstance(scope_steps, Mapping):
            authored_scope_steps = scope_steps.get(scope_id, ())
            if isinstance(authored_scope_steps, list):
                for step in authored_scope_steps:
                    add(step, scope_id=scope_id, goal_ref=None)
        if isinstance(goal_plans, Mapping):
            for goal_ref in scope.get("goal_refs", ()):
                goal = goal_plans.get(str(goal_ref), {})
                if not isinstance(goal, Mapping):
                    continue
                authored_goal_steps = goal.get("steps", ())
                if isinstance(authored_goal_steps, list):
                    for step in authored_goal_steps:
                        add(step, scope_id=scope_id, goal_ref=str(goal_ref))
        for child in scope.get("children", ()):
            if isinstance(child, Mapping):
                visit(child)

    root = thaw_json(frame.root_scope)
    if isinstance(root, Mapping):
        visit(root)
    for step_id in duplicates:
        locations.pop(step_id, None)
    return locations


def _content_writer_visible_to_consumer(
    producer: _ContentStepLocation,
    consumer: _ContentStepLocation,
    *,
    scope_parents: Mapping[str, str | None],
) -> bool:
    if producer.order >= consumer.order:
        return False
    if producer.goal_ref is not None:
        return producer.goal_ref == consumer.goal_ref
    return producer.scope_id in _visible_scope_ids(
        consumer.scope_id,
        scope_parents,
    )


def _content_step_path(
    payload: Mapping[str, Any],
    step_id: str,
) -> tuple[Any, ...] | None:
    scope_steps = payload.get("scope_steps", {})
    if isinstance(scope_steps, Mapping):
        for scope_ref, items in scope_steps.items():
            if not isinstance(items, list):
                continue
            for index, step in enumerate(items):
                if isinstance(step, Mapping) and step.get("step_id") == step_id:
                    return ("scope_steps", scope_ref, index)
    goal_plans = payload.get("goal_plans", {})
    if isinstance(goal_plans, Mapping):
        for goal_ref, goal in goal_plans.items():
            if not isinstance(goal, Mapping) or not isinstance(
                goal.get("steps"), list
            ):
                continue
            for index, step in enumerate(goal["steps"]):
                if isinstance(step, Mapping) and step.get("step_id") == step_id:
                    return ("goal_plans", goal_ref, "steps", index)
    return None


def _source_ref_visible_from_scope(
    ref: str,
    *,
    owner_scope_id: str,
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]],
) -> bool:
    current: str | None = owner_scope_id
    while current is not None:
        if ref in source_ref_domain_types.get(current, {}):
            return True
        current = scope_parents.get(current)
    return False


def _normalize_exact_cross_container_step_duplicates(
    payload: object,
    *,
    frame: FunctionalPlanAuthorityFrame,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Remove only exact Scope/Goal copies with the same owner Scope.

    Keeping the Scope-owned copy preserves visibility for every descendant
    consumer. Duplicates inside one container, across siblings, or with any
    content drift remain intact so the ownership audit can fail loudly.
    """

    if not isinstance(payload, dict):
        return payload, ()
    normalized = deepcopy(payload)
    locations: dict[str, list[dict[str, Any]]] = {}
    scope_steps = normalized.get("scope_steps")
    if isinstance(scope_steps, dict):
        for scope_ref in sorted(scope_steps):
            steps = scope_steps[scope_ref]
            if not isinstance(steps, list):
                continue
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                step_id = step.get("step_id")
                if not isinstance(step_id, str) or not step_id:
                    continue
                locations.setdefault(step_id, []).append(
                    {
                        "kind": "scope",
                        "container": f"scope:{scope_ref}",
                        "scope_ref": scope_ref,
                        "goal_ref": None,
                        "index": index,
                        "step": step,
                        "path": _json_path(
                            ("scope_steps", scope_ref, index)
                        ),
                    }
                )
    goal_plans = normalized.get("goal_plans")
    if isinstance(goal_plans, dict):
        for goal_ref in sorted(goal_plans):
            goal = goal_plans[goal_ref]
            if not isinstance(goal, dict):
                continue
            steps = goal.get("steps")
            if not isinstance(steps, list):
                continue
            for index, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                step_id = step.get("step_id")
                if not isinstance(step_id, str) or not step_id:
                    continue
                locations.setdefault(step_id, []).append(
                    {
                        "kind": "goal",
                        "container": f"goal:{goal_ref}",
                        "scope_ref": frame.goal_owners.get(goal_ref),
                        "goal_ref": goal_ref,
                        "index": index,
                        "step": step,
                        "path": _json_path(
                            ("goal_plans", goal_ref, "steps", index)
                        ),
                    }
                )

    removals: dict[str, set[int]] = {}
    records: list[FunctionalPlanContentNormalization] = []
    for step_id in sorted(locations):
        entries = locations[step_id]
        if len(entries) < 2:
            continue
        scope_entries = [item for item in entries if item["kind"] == "scope"]
        goal_entries = [item for item in entries if item["kind"] == "goal"]
        if len(scope_entries) != 1 or not goal_entries:
            continue
        if len({item["container"] for item in entries}) != len(entries):
            continue
        scope_entry = scope_entries[0]
        if any(
            item["scope_ref"] != scope_entry["scope_ref"]
            or item["step"] != scope_entry["step"]
            for item in goal_entries
        ):
            continue
        for item in goal_entries:
            goal_ref = str(item["goal_ref"])
            removals.setdefault(goal_ref, set()).add(int(item["index"]))
            records.append(
                FunctionalPlanContentNormalization(
                    code=(
                        "functional.cross_container_step_duplicate_removed"
                    ),
                    path=str(item["path"]),
                    message=(
                        f"removed exact duplicate step {step_id!r}; retained "
                        f"the copy owned by Scope {scope_entry['scope_ref']!r}"
                    ),
                )
            )

    if isinstance(goal_plans, dict):
        for goal_ref in sorted(removals):
            goal = goal_plans.get(goal_ref)
            if not isinstance(goal, dict) or not isinstance(
                goal.get("steps"), list
            ):
                continue
            goal["steps"] = [
                step
                for index, step in enumerate(goal["steps"])
                if index not in removals[goal_ref]
            ]
            if not goal["steps"]:
                goal.pop("steps")
    return normalized, tuple(records)


def _content_step_ownership_issues(
    payload: Mapping[str, Any],
) -> tuple[ScopedFunctionalPlanIssue, ...]:
    """Report every remaining global step-id collision before assembly."""

    locations: dict[str, list[tuple[str, str, Mapping[str, Any]]]] = {}
    scope_steps = payload.get("scope_steps", {})
    if isinstance(scope_steps, Mapping):
        for scope_ref, steps in scope_steps.items():
            if not isinstance(steps, Sequence):
                continue
            for index, step in enumerate(steps):
                if not isinstance(step, Mapping):
                    continue
                step_id = step.get("step_id")
                if isinstance(step_id, str):
                    locations.setdefault(step_id, []).append(
                        (
                            f"scope:{scope_ref}",
                            _json_path(("scope_steps", scope_ref, index)),
                            step,
                        )
                    )
    goal_plans = payload.get("goal_plans", {})
    if isinstance(goal_plans, Mapping):
        for goal_ref, goal in goal_plans.items():
            if not isinstance(goal, Mapping):
                continue
            steps = goal.get("steps", ())
            if not isinstance(steps, Sequence):
                continue
            for index, step in enumerate(steps):
                if not isinstance(step, Mapping):
                    continue
                step_id = step.get("step_id")
                if isinstance(step_id, str):
                    locations.setdefault(step_id, []).append(
                        (
                            f"goal:{goal_ref}",
                            _json_path(
                                ("goal_plans", goal_ref, "steps", index)
                            ),
                            step,
                        )
                    )

    issues: list[ScopedFunctionalPlanIssue] = []
    for step_id in sorted(locations):
        entries = locations[step_id]
        if len(entries) < 2:
            continue
        signatures = {stable_hash(item[2]) for item in entries}
        owners = [item[0] for item in entries]
        paths = [item[1] for item in entries]
        conflict = len(signatures) > 1
        issues.append(
            ScopedFunctionalPlanIssue(
                (
                    "functional.step_id_conflict"
                    if conflict
                    else "functional.step_id_duplicate"
                ),
                paths[1],
                (
                    f"step_id {step_id!r} has different definitions in "
                    f"{', '.join(owners)}; author one definition in exactly "
                    "one Scope or Goal container"
                    if conflict
                    else (
                        f"step_id {step_id!r} appears more than once in "
                        f"{', '.join(owners)}; every step must belong to "
                        "exactly one Scope or Goal container"
                    )
                ),
                {
                    "step_id": step_id,
                    "owners": owners,
                    "paths": paths,
                },
            )
        )
    return tuple(issues)


def normalize_empty_optional_capability_args(
    payload: object,
    *,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Canonicalize capability-declared optional empty collections to omission.

    A Method may explicitly allow ``[]`` in the wire schema when an empty
    collection is a useful authored spelling, such as a closed symbolic state.
    The canonical Plan still collapses ``[]`` and omission to one representation.
    Required, scalar, and unknown empty arguments remain untouched so the
    normal contract rejects them.
    """

    normalized = deepcopy(payload)
    records: list[FunctionalPlanContentNormalization] = []

    def visit(value: object, path: tuple[Any, ...]) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*path, index))
            return
        if not isinstance(value, dict):
            return
        capability_id = value.get("capability_id")
        args = value.get("args")
        capability = (
            capability_catalog.get(capability_id)
            if isinstance(capability_id, str)
            else None
        )
        if capability is not None and isinstance(args, dict):
            arg_specs = {item.name: item for item in capability.args}
            for arg_name in tuple(args):
                if args[arg_name] != []:
                    continue
                arg_spec = arg_specs.get(arg_name)
                if (
                    arg_spec is None
                    or arg_spec.required
                    or arg_spec.cardinality != "many"
                ):
                    continue
                args.pop(arg_name)
                records.append(
                    FunctionalPlanContentNormalization(
                        code=(
                            "functional.empty_optional_capability_arg_omitted"
                        ),
                        path=_json_path((*path, "args", arg_name)),
                        message=(
                            "omitted empty optional many-valued capability "
                            f"argument {capability_id}.{arg_name}"
                        ),
                    )
                )
        for key, item in tuple(value.items()):
            visit(item, (*path, key))

    visit(normalized, ())
    return normalized, tuple(records)


def normalize_unknown_capability_args(
    payload: object,
    *,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Drop surplus arguments only after the public contract is complete.

    This is the content-wire counterpart of the canonical Plan normalizer. An
    unknown field cannot affect execution once every required public argument
    is present with a valid cardinality. Moving the rule before strict schema
    validation prevents a harmless extra field from forcing an LLM retry.
    """

    normalized = deepcopy(payload)
    records: list[FunctionalPlanContentNormalization] = []

    def cardinality_is_valid(value: object, cardinality: str) -> bool:
        if cardinality == "one":
            return not isinstance(value, list) and value is not None
        if isinstance(value, list):
            return bool(value)
        return value is not None

    def visit(value: object, path: tuple[Any, ...]) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*path, index))
            return
        if not isinstance(value, dict):
            return
        capability_id = value.get("capability_id")
        args = value.get("args")
        capability = (
            capability_catalog.get(capability_id)
            if isinstance(capability_id, str)
            else None
        )
        if capability is not None and isinstance(args, dict):
            declared = {item.name: item for item in capability.args}
            required_complete = all(
                item.name in args
                and cardinality_is_valid(args[item.name], item.cardinality)
                for item in capability.args
                if item.required
            )
            declared_cardinalities_valid = all(
                name not in declared
                or cardinality_is_valid(item, declared[name].cardinality)
                for name, item in args.items()
            )
            if required_complete and declared_cardinalities_valid:
                for arg_name in sorted(set(args) - set(declared)):
                    args.pop(arg_name)
                    records.append(
                        FunctionalPlanContentNormalization(
                            code="functional.unknown_capability_arg_omitted",
                            path=_json_path((*path, "args", arg_name)),
                            message=(
                                "omitted surplus capability argument "
                                f"{capability_id}.{arg_name} after the "
                                "declared call contract was complete"
                            ),
                        )
                    )
        for key, item in tuple(value.items()):
            visit(item, (*path, key))

    visit(normalized, ())
    return normalized, tuple(records)


def normalize_interchangeable_capability_args(
    payload: object,
    *,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Canonicalize mathematically interchangeable public input slots.

    The MethodSpec is the only authority that may declare a permutation safe.
    Within such a group, named entity refs are placed before published/exact
    results while preserving authored order inside each source class. Runtime
    execution still verifies the resulting mathematical call.
    """

    normalized = deepcopy(payload)
    records: list[FunctionalPlanContentNormalization] = []

    def visit(value: object, path: tuple[Any, ...]) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, (*path, index))
            return
        if not isinstance(value, dict):
            return
        capability_id = value.get("capability_id")
        args = value.get("args")
        capability = (
            capability_catalog.get(capability_id)
            if isinstance(capability_id, str)
            else None
        )
        if capability is not None and isinstance(args, dict):
            for group in capability.interchangeable_arg_groups:
                if not group or any(name not in args for name in group):
                    continue
                authored = [args[name] for name in group]
                ranks = [_interchangeable_arg_source_rank(item) for item in authored]
                if any(rank is None for rank in ranks):
                    continue
                order = sorted(range(len(group)), key=lambda index: (ranks[index], index))
                canonical = [authored[index] for index in order]
                if canonical == authored:
                    continue
                for name, item in zip(group, canonical, strict=True):
                    args[name] = item
                records.append(
                    FunctionalPlanContentNormalization(
                        code="functional.interchangeable_args_permuted",
                        path=_json_path((*path, "args")),
                        message=(
                            "canonicalized interchangeable capability inputs "
                            f"{capability_id}.{'/'.join(group)} using the "
                            "MethodSpec permutation contract"
                        ),
                    )
                )
        for key, item in tuple(value.items()):
            visit(item, (*path, key))

    visit(normalized, ())
    return normalized, tuple(records)


def _interchangeable_arg_source_rank(value: object) -> int | None:
    if isinstance(value, str):
        return 0
    if not isinstance(value, Mapping):
        return None
    if set(value) == {"published_goal_ref"}:
        return 1
    if set(value) == {"step_id", "return"}:
        return 2
    return None


def _assemble_plan_payload(
    content: FunctionalPlanContent,
    *,
    frame: FunctionalPlanAuthorityFrame,
) -> dict[str, Any]:
    scope_steps = thaw_json(content.scope_steps)
    goal_plans = thaw_json(content.goal_plans)

    def build(scope: Mapping[str, Any]) -> dict[str, Any]:
        scope_ref = str(scope["scope_ref"])
        result: dict[str, Any] = {"scope_ref": scope_ref}
        steps = scope_steps.get(scope_ref)
        if steps:
            result["steps"] = steps
        goals: list[dict[str, Any]] = []
        for goal_ref in scope.get("goal_refs", ()):
            goal = dict(goal_plans[goal_ref])
            goal["goal_ref"] = goal_ref
            goals.append(goal)
        if goals:
            result["goals"] = goals
        children = [build(item) for item in scope.get("children", ())]
        if children:
            result["children"] = children
        return result

    return {
        "format": "functional_plan/v2",
        "root_scope": build(thaw_json(frame.root_scope)),
    }


def derive_goal_answer_bindings(
    plan_payload: Mapping[str, Any],
    *,
    requirements: Mapping[str, FunctionalGoalAnswerRequirement],
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]] | None = None,
    capability_catalog: FunctionalCapabilityCatalog,
    locked_answers: Mapping[str, Mapping[str, str]] | None = None,
    authored_answers: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[dict[str, Any], tuple[FunctionalGoalAnswerBinding, ...]]:
    """Derive canonical answer sources from typed Goal and return authority.

    The resolver never chooses a different mathematical producer on the LLM's
    behalf. A valid authored ``answer_from`` is authoritative. If its step is
    valid and that step has exactly one active target/type-compatible return,
    code may normalize only the public return name. Every other mismatch stays
    a Goal-level authoring error.
    """

    payload = deepcopy(plan_payload)
    locked_answers = dict(locked_answers or {})
    authored_answers = dict(authored_answers or {})
    steps: dict[str, Mapping[str, Any]] = {}
    step_owners: dict[str, str] = {}
    step_scopes: dict[str, str] = {}
    goals: dict[str, dict[str, Any]] = {}

    def index_scope(scope: dict[str, Any]) -> None:
        scope_ref = str(scope["scope_ref"])
        for step in scope.get("steps", ()):
            step_id = str(step.get("step_id", ""))
            steps[step_id] = step
            step_owners[step_id] = f"scope:{scope_ref}"
            step_scopes[step_id] = scope_ref
        for goal in scope.get("goals", ()):
            goal_ref = str(goal.get("goal_ref", ""))
            goals[goal_ref] = goal
            for step in goal.get("steps", ()):
                step_id = str(step.get("step_id", ""))
                steps[step_id] = step
                step_owners[step_id] = f"goal:{goal_ref}"
                step_scopes[step_id] = scope_ref
        for child in scope.get("children", ()):
            index_scope(child)

    root = payload.get("root_scope")
    if not isinstance(root, dict):
        raise ValueError("Plan payload has no root_scope object")
    index_scope(root)

    if set(goals) != set(requirements):
        missing = sorted(set(requirements) - set(goals))
        unexpected = sorted(set(goals) - set(requirements))
        raise ValueError(
            f"Plan Goal authority mismatch: missing={missing}, "
            f"unexpected={unexpected}"
        )

    bindings: list[FunctionalGoalAnswerBinding] = []
    for goal_ref, requirement in requirements.items():
        visible_scopes = _visible_scope_ids(
            requirement.owner_scope_id,
            scope_parents,
        )
        allowed_step_ids = {
            step_id
            for step_id, owner in step_owners.items()
            if owner == f"goal:{goal_ref}"
            or (
                owner.startswith("scope:")
                and step_scopes[step_id] in visible_scopes
            )
        }
        consumed_refs = {
            item
            for step_id in allowed_step_ids
            for item in _step_result_refs(steps[step_id].get("args", {}))
        }
        candidates = _goal_answer_candidates(
            requirement,
            steps=steps,
            step_owners=step_owners,
            step_scopes=step_scopes,
            allowed_step_ids=allowed_step_ids,
            consumed_refs=consumed_refs,
            capability_catalog=capability_catalog,
            scope_parents=scope_parents,
            source_ref_domain_types=source_ref_domain_types or {},
        )
        match_basis: str | None = None
        locked = locked_answers.get(goal_ref)
        if locked is not None:
            exact = [
                item
                for item in candidates
                if item.step_id == locked.get("step_id")
                and item.return_name == locked.get("return")
            ]
            if len(exact) != 1:
                raise FunctionalGoalAnswerBindingError(
                    goal_ref=goal_ref,
                    target_ref=requirement.target_ref,
                    answer_type=requirement.answer_type,
                    candidates=candidates,
                    reason="its frozen answer producer is no longer valid",
                )
            selected = exact[0]
        else:
            authored = authored_answers.get(goal_ref)
            authored_match = (
                [
                    item
                    for item in candidates
                    if item.step_id == authored.get("step_id")
                    and item.return_name == authored.get("return")
                ]
                if authored is not None
                else []
            )
            if len(authored_match) == 1:
                selected = authored_match[0]
                match_basis = f"authored_answer_from:{selected.basis}"
            else:
                same_step = tuple(
                    item
                    for item in candidates
                    if authored is not None
                    and item.step_id == authored.get("step_id")
                )
                if authored is not None and len(same_step) == 1:
                    selected = same_step[0]
                    match_basis = (
                        "normalize_public_return_name:"
                        f"{selected.basis}"
                    )
                else:
                    diagnostic_candidates = same_step or candidates
                    if authored is None:
                        reason = "answer_from was not authored"
                    elif not same_step:
                        reason = (
                            "its authored step has no active return compatible "
                            "with the required target and answer type"
                        )
                    else:
                        reason = (
                            "its authored step has multiple active returns "
                            "compatible with the required target and answer type"
                        )
                    raise FunctionalGoalAnswerBindingError(
                        goal_ref=goal_ref,
                        target_ref=requirement.target_ref,
                        answer_type=requirement.answer_type,
                        candidates=diagnostic_candidates,
                        reason=reason,
                        authored_answer=authored,
                    )
        goals[goal_ref]["answer_from"] = {
            "step_id": selected.step_id,
            "return": selected.return_name,
        }
        bindings.append(
            FunctionalGoalAnswerBinding(
                goal_ref=goal_ref,
                step_id=selected.step_id,
                return_name=selected.return_name,
                target_ref=requirement.target_ref,
                answer_type=requirement.answer_type,
                match_basis=match_basis or selected.basis,
            )
        )
    return payload, tuple(bindings)


def _answer_binding_normalizations(
    *,
    authored_answers: Mapping[str, Mapping[str, str]],
    answer_bindings: Sequence[FunctionalGoalAnswerBinding],
) -> tuple[FunctionalPlanContentNormalization, ...]:
    records: list[FunctionalPlanContentNormalization] = []
    for binding in answer_bindings:
        authored = authored_answers[binding.goal_ref]
        canonical = {
            "step_id": binding.step_id,
            "return": binding.return_name,
        }
        if dict(authored) == canonical:
            continue
        records.append(
            FunctionalPlanContentNormalization(
                code="functional.goal_answer_source_normalized",
                path=(
                    f"$.goal_plans[{binding.goal_ref!r}].answer_from"
                ),
                message=(
                    "replaced an invalid authored answer_from with the only "
                    f"authority-compatible producer {binding.step_id}."
                    f"{binding.return_name}"
                ),
            )
        )
    return tuple(records)


def _goal_answer_candidates(
    requirement: FunctionalGoalAnswerRequirement,
    *,
    steps: Mapping[str, Mapping[str, Any]],
    step_owners: Mapping[str, str],
    step_scopes: Mapping[str, str],
    allowed_step_ids: set[str],
    consumed_refs: set[tuple[str, str]],
    capability_catalog: FunctionalCapabilityCatalog,
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]],
) -> tuple[FunctionalGoalAnswerCandidate, ...]:
    result: list[FunctionalGoalAnswerCandidate] = []
    for step_id in sorted(allowed_step_ids):
        step = steps[step_id]
        capability = capability_catalog.get(str(step.get("capability_id", "")))
        if capability is None:
            continue
        owner = step_owners[step_id]
        goal_local = owner == f"goal:{requirement.goal_ref}"
        for returned in _active_returns_for_authored_step(
            step,
            steps=steps,
            capability=capability,
            capability_catalog=capability_catalog,
            owner_scope_id=step_scopes[step_id],
            scope_parents=scope_parents,
            source_ref_domain_types=source_ref_domain_types,
        ):
            if returned.binding_mode == "internal_only" or not runtime_type_compatible(
                requirement.answer_type,
                returned.runtime_type,
            ):
                continue
            resolved_target = _return_target_ref(
                step_id,
                returned.name,
                steps=steps,
                capability_catalog=capability_catalog,
            )
            declared_target = resolved_target is not None
            target_match = resolved_target == requirement.target_ref
            if declared_target and not target_match:
                continue
            consumed = (step_id, returned.name) in consumed_refs
            if target_match and goal_local and not consumed:
                basis, rank = "target_identity_goal_terminal", 0
            elif goal_local and not consumed:
                basis, rank = "goal_local_terminal_return", 1
            elif target_match and not consumed:
                basis, rank = "target_identity_scope_terminal", 2
            elif not goal_local and not consumed:
                basis, rank = "visible_scope_terminal_return", 3
            elif target_match and goal_local:
                basis, rank = "target_identity_goal_consumed", 4
            elif target_match:
                basis, rank = "target_identity_scope_consumed", 5
            elif goal_local:
                basis, rank = "goal_local_typed_return", 6
            else:
                basis, rank = "visible_scope_typed_return", 7
            result.append(
                FunctionalGoalAnswerCandidate(
                    step_id=step_id,
                    return_name=returned.name,
                    runtime_type=returned.runtime_type,
                    owner=owner,
                    basis=basis,
                    consumed=consumed,
                    rank=rank,
                )
            )
    return tuple(result)


def _active_returns_for_authored_step(
    step: Mapping[str, Any],
    *,
    steps: Mapping[str, Mapping[str, Any]],
    capability: FunctionalCapability,
    capability_catalog: FunctionalCapabilityCatalog,
    owner_scope_id: str,
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]],
) -> tuple[FunctionalCapabilityReturn, ...]:
    """Filter input-type return variants when the wire proves the input type.

    This is intentionally narrower than runtime reconciliation. It only uses a
    typed ``StepResultRef`` whose producer return is declared in the same
    capability catalog. SourceRef values remain unresolved until F5-C binding.
    """

    active = tuple(capability.returns)
    return_types = {
        normalize_runtime_type(member)
        for returned in capability.returns
        for member in split_runtime_types(returned.runtime_type)
    }
    args = step.get("args", {})
    if not isinstance(args, Mapping):
        return active
    for arg in capability.args:
        accepted = {
            normalize_runtime_type(member)
            for declared in (
                arg.accepted_item_types or (arg.runtime_type,)
            )
            for member in split_runtime_types(declared)
        }
        variants = tuple(
            returned
            for returned in capability.returns
            if {
                normalize_runtime_type(member)
                for member in split_runtime_types(returned.runtime_type)
            }.intersection(accepted)
        )
        variant_types = {
            normalize_runtime_type(member)
            for returned in variants
            for member in split_runtime_types(returned.runtime_type)
        }
        if len(variant_types.intersection(return_types)) <= 1:
            continue
        actual_types = _wire_result_runtime_types(
            args.get(arg.name),
            steps=steps,
            capability_catalog=capability_catalog,
            owner_scope_id=owner_scope_id,
            scope_parents=scope_parents,
            source_ref_domain_types=source_ref_domain_types,
        )
        exact_types = actual_types.intersection(variant_types)
        if not exact_types:
            continue
        variant_names = {item.name for item in variants}
        active_variant_names = {
            item.name
            for item in variants
            if {
                normalize_runtime_type(member)
                for member in split_runtime_types(item.runtime_type)
            }.intersection(exact_types)
        }
        active = tuple(
            item
            for item in active
            if item.name not in variant_names or item.name in active_variant_names
        )
    return active


def _wire_result_runtime_types(
    value: object,
    *,
    steps: Mapping[str, Mapping[str, Any]],
    capability_catalog: FunctionalCapabilityCatalog,
    owner_scope_id: str,
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]],
) -> set[str]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return {
            runtime_type
            for item in value
            for runtime_type in _wire_result_runtime_types(
                item,
                steps=steps,
                capability_catalog=capability_catalog,
                owner_scope_id=owner_scope_id,
                scope_parents=scope_parents,
                source_ref_domain_types=source_ref_domain_types,
            )
        }
    if isinstance(value, str):
        return _source_ref_runtime_types(
            value,
            owner_scope_id=owner_scope_id,
            scope_parents=scope_parents,
            source_ref_domain_types=source_ref_domain_types,
        )
    if not isinstance(value, Mapping):
        return set()
    step_id = value.get("step_id")
    return_name = value.get("return")
    if not isinstance(step_id, str) or not isinstance(return_name, str):
        return set()
    producer = steps.get(step_id)
    if producer is None:
        return set()
    producer_capability = capability_catalog.get(
        str(producer.get("capability_id", ""))
    )
    if producer_capability is None:
        return set()
    return {
        normalize_runtime_type(member)
        for returned in producer_capability.returns
        if returned.name == return_name
        for member in split_runtime_types(returned.runtime_type)
    }


def _entity_kind_domain_type(kind: str) -> str:
    return {
        "symbol": "Symbol",
        "point": "Point",
        "quadratic_function": "QuadraticFunction",
        "named_line": "Line",
        "named_ray": "Ray",
        "polygon": "Polygon",
        "scalar_expression": "Expression",
    }.get(kind, kind)


def _source_ref_runtime_types(
    ref: str,
    *,
    owner_scope_id: str,
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]],
) -> set[str]:
    current: str | None = owner_scope_id
    while current is not None:
        domain_type = source_ref_domain_types.get(current, {}).get(ref)
        if domain_type is not None:
            return {
                {
                    "QuadraticFunction": "Parabola",
                    "PathWitness": "PathTransformation",
                    "PointCandidates": "PointList",
                }.get(domain_type, domain_type)
            }
        current = scope_parents.get(current)
    return set()


def _source_ref_accepts_return_type(
    ref: str,
    return_runtime_type: str,
    *,
    owner_scope_id: str,
    scope_parents: Mapping[str, str | None],
    source_ref_domain_types: Mapping[str, Mapping[str, str]],
) -> bool:
    """Check a return against both an Entity identity and its state types."""

    current: str | None = owner_scope_id
    domain_type: str | None = None
    while current is not None:
        domain_type = source_ref_domain_types.get(current, {}).get(ref)
        if domain_type is not None:
            break
        current = scope_parents.get(current)
    if domain_type is None:
        return False
    domain_object_kind = {
        "Point": "point",
        "QuadraticFunction": "function",
        "Symbol": "symbol",
        "Line": "line",
        "Ray": "ray",
        "Polygon": "polygon",
    }.get(domain_type)
    return_object_kind = object_kind_for_runtime_type(return_runtime_type)
    if (
        domain_object_kind is not None
        and return_object_kind == domain_object_kind
    ):
        return True
    return any(
        runtime_type_compatible(return_runtime_type, runtime_type)
        for runtime_type in _source_ref_runtime_types(
            ref,
            owner_scope_id=owner_scope_id,
            scope_parents=scope_parents,
            source_ref_domain_types=source_ref_domain_types,
        )
    )


def _compatible_output_target_refs(
    frame: FunctionalPlanAuthorityFrame,
    *,
    return_runtime_type: str,
    selector: Any | None = None,
) -> tuple[str, ...]:
    """Return every existing named object that is compatible in some scope.

    A step's exact owner is supplied by the authored Scope/Goal container, so
    the response schema exposes the union and the canonical Plan audit applies
    the final lexical-visibility check. Unknown free-form target names never
    enter the provider schema.
    """

    refs = {
        ref
        for owner_scope_id in frame.scope_refs
        for values in frame.source_ref_domain_types.values()
        for ref in values
        if _source_ref_accepts_return_type(
            ref,
            return_runtime_type,
            owner_scope_id=owner_scope_id,
            scope_parents=frame.scope_parents,
            source_ref_domain_types=frame.source_ref_domain_types,
        )
    }
    if selector is not None:
        refs &= _selector_output_target_refs(frame, selector=selector)
    return tuple(sorted(refs))


def _selector_output_target_refs(
    frame: FunctionalPlanAuthorityFrame,
    *,
    selector: Any,
) -> set[str]:
    """Project structural source-fact eligibility into the provider schema.

    The response schema cannot know the eventual step owner or the value of a
    related authored argument, so final lexical and relation checks remain in
    scoped-plan validation. It can still exclude objects that do not satisfy
    the selector's fact kind and required fields in any scope. This prevents a
    type-compatible Point from being offered for a construction capability
    whose source evidence describes a different role.
    """

    if selector.selector_id != "unique_visible_fact_target":
        return set()
    return {
        target_ref
        for facts in frame.source_facts.values()
        for fact in facts
        if fact.get("kind") == selector.fact_kind
        and not any(
            fact.get(field) != expected
            for field, expected in selector.required_field_values
        )
        and isinstance((target_ref := fact.get(selector.target_field)), str)
    }


def _visible_scope_ids(
    owner_scope_id: str,
    scope_parents: Mapping[str, str | None],
) -> set[str]:
    result: set[str] = set()
    current: str | None = owner_scope_id
    while current is not None:
        if current in result:
            raise ValueError("scope parent cycle in FunctionalPlan authority")
        result.add(current)
        current = scope_parents.get(current)
    return result


def _step_result_refs(value: Any) -> set[tuple[str, str]]:
    if isinstance(value, Mapping):
        if set(value) == {"step_id", "return"}:
            return {(str(value["step_id"]), str(value["return"]))}
        return {
            item
            for child in value.values()
            for item in _step_result_refs(child)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {
            item for child in value for item in _step_result_refs(child)
        }
    return set()


def _return_target_ref(
    step_id: str,
    return_name: str,
    *,
    steps: Mapping[str, Mapping[str, Any]],
    capability_catalog: FunctionalCapabilityCatalog,
    seen: frozenset[tuple[str, str]] = frozenset(),
) -> str | None:
    key = (step_id, return_name)
    if key in seen:
        return None
    step = steps.get(step_id)
    if step is None:
        return None
    output_targets = step.get("output_targets", {})
    if isinstance(output_targets, Mapping):
        explicit = output_targets.get(return_name)
        if isinstance(explicit, str) and explicit:
            return explicit
    capability = capability_catalog.get(str(step.get("capability_id", "")))
    if capability is None:
        return None
    returned = next(
        (item for item in capability.returns if item.name == return_name),
        None,
    )
    if returned is None or returned.identity_arg is None:
        return None
    args = step.get("args", {})
    if not isinstance(args, Mapping) or returned.identity_arg not in args:
        return None
    targets = _value_target_refs(
        args[returned.identity_arg],
        steps=steps,
        capability_catalog=capability_catalog,
        seen=seen | {key},
    )
    return next(iter(targets)) if len(targets) == 1 else None


def _value_target_refs(
    value: Any,
    *,
    steps: Mapping[str, Mapping[str, Any]],
    capability_catalog: FunctionalCapabilityCatalog,
    seen: frozenset[tuple[str, str]],
) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, Mapping):
        if set(value) == {"step_id", "return"}:
            target = _return_target_ref(
                str(value["step_id"]),
                str(value["return"]),
                steps=steps,
                capability_catalog=capability_catalog,
                seen=seen,
            )
            return {target} if target is not None else set()
        return {
            item
            for child in value.values()
            for item in _value_target_refs(
                child,
                steps=steps,
                capability_catalog=capability_catalog,
                seen=seen,
            )
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {
            item
            for child in value
            for item in _value_target_refs(
                child,
                steps=steps,
                capability_catalog=capability_catalog,
                seen=seen,
            )
        }
    return set()


def _goal_owner(plan: ScopedFunctionalPlan, goal_ref: str) -> str | None:
    def visit(scope: Any) -> str | None:
        if any(goal.goal_ref == goal_ref for goal in scope.goals):
            return scope.scope_ref
        for child in scope.children:
            result = visit(child)
            if result is not None:
                return result
        return None

    return visit(plan.root_scope)


def _json_path(path: Any) -> str:
    result = "$"
    for item in path:
        result += f"[{item}]" if isinstance(item, int) else f".{item}"
    return result


__all__ = [
    "FUNCTIONAL_PLAN_CONTENT_CONTRACT",
    "FunctionalPlanAuthorityFrame",
    "FunctionalPlanContent",
    "FunctionalPlanContentCompilation",
    "FunctionalPlanContentCompiler",
    "FunctionalPlanContentNormalization",
    "FunctionalFinalPlanContractValidation",
    "FunctionalGoalAnswerBinding",
    "FunctionalGoalAnswerBindingError",
    "FunctionalGoalAnswerCandidate",
    "FunctionalGoalAnswerRequirement",
    "capability_bound_step_schema",
    "decode_single_json_object",
    "derive_goal_answer_bindings",
    "functional_plan_content_from_plan",
    "functional_plan_prompt_payload",
    "functional_plan_content_schema",
    "normalize_empty_optional_capability_args",
    "normalize_empty_optional_step_maps",
    "normalize_interchangeable_capability_args",
    "normalize_unknown_capability_args",
]
