"""Code-owned Scope/Goal frame for LLM-authored FunctionalPlan content."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

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
    scoped_functional_plan_schema,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
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
        authority = {
            "planning_context_id": planning_context.planning_context_id,
            "root_scope": root_scope,
            "scope_parents": scope_parents,
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
        return {"root_scope": thaw_json(self.root_scope)}

    def authority_payload(self) -> dict[str, Any]:
        return {
            "planning_context_id": self.planning_context_id,
            "root_scope": thaw_json(self.root_scope),
            "scope_parents": dict(self.scope_parents),
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


def functional_plan_content_schema(
    frame: FunctionalPlanAuthorityFrame,
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
        "items": {"$ref": "#/$defs/step"},
    }
    goal_plan = {
        "type": "object",
        "required": ["answer_from"],
        "properties": {
            "steps": step_array,
            "answer_from": {"$ref": "#/$defs/answer_from"},
        },
        "additionalProperties": False,
    }
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
                "properties": {
                    scope_ref: deepcopy(step_array)
                    for scope_ref in frame.scope_refs
                },
                "additionalProperties": False,
            },
            "goal_plans": {
                "type": "object",
                "required": list(frame.goal_refs),
                "properties": {
                    goal_ref: deepcopy(goal_plan)
                    for goal_ref in frame.goal_refs
                },
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
        payload, wire_normalizations = _normalize_content_wire(
            payload,
            capability_catalog=capability_catalog,
        )
        normalizations = (*normalizations, *wire_normalizations)
        errors = sorted(
            Draft202012Validator(
                functional_plan_content_schema(frame)
            ).iter_errors(payload),
            key=lambda error: tuple(str(item) for item in error.absolute_path),
        )
        if errors:
            issues = tuple(
                ScopedFunctionalPlanIssue(
                    "functional.plan_content_schema_invalid",
                    _json_path(error.absolute_path),
                    error.message,
                )
                for error in errors
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
                capability_catalog=capability_catalog,
                authored_answers=authored_answers,
            )
        except FunctionalGoalAnswerBindingError as exc:
            issue = ScopedFunctionalPlanIssue(
                exc.code,
                exc.path,
                exc.message,
            )
            return FunctionalPlanContentCompilation(
                content,
                None,
                ScopedFunctionalPlanValidationReport((issue,)),
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
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    if not isinstance(payload, dict) or payload.get("format") != (
        FUNCTIONAL_PLAN_CONTENT_CONTRACT
    ):
        return payload, ()
    normalized = deepcopy(payload)
    records: list[FunctionalPlanContentNormalization] = []

    def normalize_steps(value: object, path: tuple[Any, ...]) -> None:
        if not isinstance(value, list):
            return
        for index, step in enumerate(value):
            if not isinstance(step, dict):
                continue
            for field_name in ("output_targets", "return_expectations"):
                if step.get(field_name) != {}:
                    continue
                step.pop(field_name)
                records.append(
                    FunctionalPlanContentNormalization(
                        code="functional.empty_optional_step_map_omitted",
                        path=_json_path((*path, index, field_name)),
                        message=f"omitted empty optional {field_name}",
                    )
                )

    scope_steps = normalized.get("scope_steps")
    if isinstance(scope_steps, dict):
        for scope_ref, steps in scope_steps.items():
            normalize_steps(steps, ("scope_steps", scope_ref))
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
            elif isinstance(goal, dict):
                normalize_steps(
                    goal.get("steps"),
                    ("goal_plans", goal_ref, "steps"),
                )
    normalized, arg_records = normalize_empty_optional_capability_args(
        normalized,
        capability_catalog=capability_catalog,
    )
    return normalized, (*records, *arg_records)


def normalize_empty_optional_capability_args(
    payload: object,
    *,
    capability_catalog: FunctionalCapabilityCatalog,
) -> tuple[object, tuple[FunctionalPlanContentNormalization, ...]]:
    """Omit only capability-declared optional empty collection arguments.

    The generic wire schema intentionally keeps arrays non-empty. This
    pre-schema pass tolerates a model spelling an optional many-valued input as
    ``[]`` while leaving required, scalar, and unknown empty arguments intact
    so the normal contract rejects them.
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
    capability_catalog: FunctionalCapabilityCatalog,
    locked_answers: Mapping[str, Mapping[str, str]] | None = None,
    authored_answers: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[dict[str, Any], tuple[FunctionalGoalAnswerBinding, ...]]:
    """Derive canonical answer sources from typed Goal and return authority.

    The resolver never uses step names, array order, or textual similarity. A
    valid authored ``answer_from`` is authoritative. Candidate ranking is only
    a deterministic fallback when that pointer is absent or invalid.
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
            allowed_step_ids=allowed_step_ids,
            consumed_refs=consumed_refs,
            capability_catalog=capability_catalog,
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
            if not candidates:
                raise FunctionalGoalAnswerBindingError(
                    goal_ref=goal_ref,
                    target_ref=requirement.target_ref,
                    answer_type=requirement.answer_type,
                    candidates=(),
                    reason="no visible type-compatible return was found",
                    authored_answer=authored_answers.get(goal_ref),
                )
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
                best_rank = min(item.rank for item in candidates)
                best = tuple(
                    item for item in candidates if item.rank == best_rank
                )
                if len(best) != 1:
                    raise FunctionalGoalAnswerBindingError(
                        goal_ref=goal_ref,
                        target_ref=requirement.target_ref,
                        answer_type=requirement.answer_type,
                        candidates=best,
                        reason=(
                            "the authored answer_from did not identify one of "
                            f"{len(best)} equally authoritative returns"
                            if authored is not None
                            else (
                                f"{len(best)} equally authoritative returns "
                                "were found"
                            )
                        ),
                        authored_answer=authored,
                    )
                selected = best[0]
                if authored is not None:
                    match_basis = f"fallback_from_invalid_authored:{selected.basis}"
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
    allowed_step_ids: set[str],
    consumed_refs: set[tuple[str, str]],
    capability_catalog: FunctionalCapabilityCatalog,
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
) -> set[str]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return {
            runtime_type
            for item in value
            for runtime_type in _wire_result_runtime_types(
                item,
                steps=steps,
                capability_catalog=capability_catalog,
            )
        }
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
    "FunctionalGoalAnswerBinding",
    "FunctionalGoalAnswerBindingError",
    "FunctionalGoalAnswerCandidate",
    "FunctionalGoalAnswerRequirement",
    "decode_single_json_object",
    "derive_goal_answer_bindings",
    "functional_plan_content_from_plan",
    "functional_plan_prompt_payload",
    "functional_plan_content_schema",
    "normalize_empty_optional_capability_args",
]
