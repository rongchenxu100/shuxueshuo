"""Typed authority and prompt projection for Functional runtime diagnostics.

Methods report exact execution facts through :class:`StatelessMethodError`.
Only :class:`FunctionalPromptDiagnosticProjector` may turn those internal facts
into Planner-visible retry guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator


FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT = (
    "functional-diagnostic-authority/v1"
)
FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT = "functional-prompt-diagnostic/v1"

FunctionalDiagnosticCategory = Literal[
    "input",
    "precondition",
    "result",
    "ambiguity",
    "inconsistency",
    "check",
    "binding",
    "configuration",
]
FunctionalDiagnosticRetryability = Literal[
    "planner_repairable",
    "problem_semantics",
    "configuration",
]

_CONFIGURATION_CODES = frozenset(
    {
        "planner.macro_contract_invalid",
        "planner.method_contract_invalid",
        "planner.method_relation_contract_invalid",
        "planner.transactional_configuration_error",
        "planner.contract_runtime_symbol_drift",
        "planner.symbolic_closure_spec_invalid",
    }
)

_REPAIR_MESSAGES = {
    "provide_visible_point_producer": (
        "Add or repair a visible step that materializes the required Point."
    ),
    "provide_visible_state_producer": (
        "Add or repair a visible producer for the required object state."
    ),
    "align_call_with_goal_scope": (
        "Keep the call inside a scope visible to every listed Goal, or remove "
        "the foreign Goal dependency."
    ),
    "provide_required_input": "Provide the missing typed input.",
    "provide_macro_input": (
        "Provide the listed public Macro argument; internal Method wiring is "
        "owned by the compiler."
    ),
    "repair_input_binding": "Bind the argument to a compatible visible source.",
    "provide_visible_curve_relation": (
        "Use a Point and curve pair proved by a visible point-on-curve Fact, "
        "or place the step where that Fact is visible."
    ),
    "place_step_in_relation_scope": (
        "Move or rewrite the step inside the listed relation scope; do not "
        "consume a child or sibling curve Fact from this scope."
    ),
    "align_curve_relation_arguments": (
        "Bind the Point and curve arguments to the same visible "
        "point-on-curve Fact."
    ),
    "supply_disambiguating_constraint": (
        "Add the missing condition needed to select one unique result."
    ),
    "revise_inconsistent_constraints": (
        "Revise the failed Goal steps so their mathematical constraints agree."
    ),
    "choose_applicable_capability": (
        "Choose a capability whose preconditions match the available state."
    ),
    "remove_unknown_capability_arg": (
        "Remove the listed argument names that are not declared by this "
        "capability; keep the valid declared arguments unchanged."
    ),
    "repair_capability_arguments": (
        "Make the call arguments match the capability contract: provide all "
        "required arguments and remove or rename undeclared arguments."
    ),
    "repair_return_role": (
        "Replace the observed return role with exactly one compatible public "
        "return role listed in expected_roles."
    ),
    "choose_visible_output_target": (
        "Bind the return to one of expected_targets whose visible source Fact "
        "satisfies required_fact_kind and required_fields."
    ),
    "choose_applicable_point_construction_capability": (
        "Use an existing complete Point state directly, or choose a Point "
        "construction capability whose required source Fact matches the target."
    ),
    "repair_failed_step": "Replace the failed Goal steps with a valid strategy.",
    "refresh_derived_input_states": (
        "Recompute or close the listed derived Math Entity states after their "
        "upstream state changed, then retry the failed step."
    ),
    "align_symbolic_state_basis": (
        "Align the declared free parameters with the symbols in the current "
        "quadratic state and its visible relations."
    ),
    "provide_or_align_symbolic_state_basis": (
        "For an open symbolic state, provide one complete non-empty independent "
        "free-parameter basis from allowed_free_parameter_bases. For a closed "
        "state, use an empty array or omit free_parameters."
    ),
    "revise_quadratic_constraints": (
        "Revise the quadratic constraints so they retain at least one "
        "consistent solution branch."
    ),
    "provide_additional_quadratic_constraint": (
        "Provide a visible quadratic constraint that selects one unique branch."
    ),
    "separate_target_and_free_parameters": (
        "Do not declare the target parameter as a preserved free parameter."
    ),
    "separate_distinct_arguments": (
        "Bind each listed argument role to a different compatible Math Entity."
    ),
    "remove_redundant_free_parameters": (
        "Remove free parameters that are already closed by the visible state."
    ),
    "use_named_entity_source_ref": (
        "Use the named Math Entity reference shown in expected_ref; the compiler "
        "will select its latest visible state and retain the producer dependency."
    ),
    "fix_runtime_contract": (
        "This is a runtime contract or configuration failure; do not repair the Plan."
    ),
}


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        frozen = tuple(_freeze(item) for item in value)
        return tuple(
            sorted(
                frozen,
                key=lambda item: json.dumps(
                    _thaw(item),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            )
        )
    if hasattr(value, "to_payload") and callable(value.to_payload):
        return _freeze(value.to_payload())
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class FunctionalDiagnosticSubject:
    role: str | None = None
    arg_name: str | None = None
    item_index: int | None = None
    internal_ref: str | None = None
    expected_type: str | None = None
    expected_state: str | None = None
    observed_type: str | None = None
    observed_state: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "role": self.role,
                "arg_name": self.arg_name,
                "item_index": self.item_index,
                "internal_ref": self.internal_ref,
                "expected_type": self.expected_type,
                "expected_state": self.expected_state,
                "observed_type": self.observed_type,
                "observed_state": self.observed_state,
            }.items()
            if value is not None
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalDiagnosticSubject":
        return cls(
            role=_optional_string(payload.get("role")),
            arg_name=_optional_string(payload.get("arg_name")),
            item_index=_optional_nonnegative_int(payload.get("item_index")),
            internal_ref=_optional_string(payload.get("internal_ref")),
            expected_type=_optional_string(payload.get("expected_type")),
            expected_state=_optional_string(payload.get("expected_state")),
            observed_type=_optional_string(payload.get("observed_type")),
            observed_state=_optional_string(payload.get("observed_state")),
        )


@dataclass(frozen=True)
class FunctionalDiagnosticAuthority:
    code: str
    category: FunctionalDiagnosticCategory
    stage: str
    retryability: FunctionalDiagnosticRetryability
    method_id: str | None = None
    capability_id: str | None = None
    scope_id: str | None = None
    step_id: str | None = None
    subjects: tuple[FunctionalDiagnosticSubject, ...] = ()
    expected: Mapping[str, Any] = field(default_factory=dict)
    observed: Mapping[str, Any] = field(default_factory=dict)
    repair_action: str = "repair_failed_step"
    repair_call_ids: tuple[str, ...] = ()
    original_message: str = ""
    authority_details: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT

    def __post_init__(self) -> None:
        if self.schema_version != FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT:
            raise ValueError("unsupported Functional diagnostic authority contract")
        if not self.code or not self.stage or not self.repair_action:
            raise ValueError("Functional diagnostic authority is incomplete")
        object.__setattr__(self, "subjects", tuple(self.subjects))
        object.__setattr__(self, "expected", _freeze(self.expected))
        object.__setattr__(self, "observed", _freeze(self.observed))
        object.__setattr__(
            self,
            "repair_call_ids",
            tuple(sorted(set(self.repair_call_ids))),
        )
        object.__setattr__(self, "authority_details", _freeze(self.authority_details))

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "code": self.code,
            "category": self.category,
            "stage": self.stage,
            "retryability": self.retryability,
            "subjects": [item.to_payload() for item in self.subjects],
            "expected": _thaw(self.expected),
            "observed": _thaw(self.observed),
            "repair_action": self.repair_action,
            "repair_call_ids": list(self.repair_call_ids),
            "original_message": self.original_message,
            "authority_details": _thaw(self.authority_details),
        }
        for key, value in (
            ("method_id", self.method_id),
            ("capability_id", self.capability_id),
            ("scope_id", self.scope_id),
            ("step_id", self.step_id),
        ):
            if value is not None:
                payload[key] = value
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalDiagnosticAuthority":
        candidate = dict(payload)
        _validate_payload(candidate, functional_diagnostic_authority_schema())
        return cls(
            schema_version=str(candidate["schema_version"]),
            code=str(candidate["code"]),
            category=str(candidate["category"]),  # type: ignore[arg-type]
            stage=str(candidate["stage"]),
            retryability=str(candidate["retryability"]),  # type: ignore[arg-type]
            method_id=_optional_string(candidate.get("method_id")),
            capability_id=_optional_string(candidate.get("capability_id")),
            scope_id=_optional_string(candidate.get("scope_id")),
            step_id=_optional_string(candidate.get("step_id")),
            subjects=tuple(
                FunctionalDiagnosticSubject.from_payload(_mapping(item))
                for item in _sequence(candidate["subjects"])
            ),
            expected=_mapping(candidate["expected"]),
            observed=_mapping(candidate["observed"]),
            repair_action=str(candidate["repair_action"]),
            repair_call_ids=tuple(
                str(item) for item in _sequence(candidate["repair_call_ids"])
            ),
            original_message=str(candidate["original_message"]),
            authority_details=_mapping(candidate["authority_details"]),
        )


class StatelessMethodError(ValueError):
    """Typed failure reported by a stateless Method or its shared helpers."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        category: FunctionalDiagnosticCategory,
        retryability: FunctionalDiagnosticRetryability,
        method_id: str | None = None,
        capability_id: str | None = None,
        scope_id: str | None = None,
        step_id: str | None = None,
        subjects: Sequence[FunctionalDiagnosticSubject] = (),
        arg_name: str | None = None,
        item_index: int | None = None,
        role: str | None = None,
        internal_ref: Any | None = None,
        expected: Mapping[str, Any] | None = None,
        observed: Mapping[str, Any] | None = None,
        repair_action: str = "repair_failed_step",
        repair_call_ids: Sequence[str] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        subject_items = tuple(subjects)
        if not subject_items and any(
            item is not None for item in (arg_name, role, internal_ref)
        ):
            expected_map = dict(expected or {})
            observed_map = dict(observed or {})
            subject_items = (
                FunctionalDiagnosticSubject(
                    role=role,
                    arg_name=arg_name,
                    item_index=item_index,
                    internal_ref=(
                        _identity_string(internal_ref)
                        if internal_ref is not None
                        else None
                    ),
                    expected_type=_optional_string(expected_map.get("type")),
                    expected_state=_optional_string(expected_map.get("state")),
                    observed_type=_optional_string(observed_map.get("type")),
                    observed_state=_optional_string(observed_map.get("state")),
                ),
            )
        self.authority = FunctionalDiagnosticAuthority(
            code=code,
            category=category,
            stage="method",
            retryability=retryability,
            method_id=method_id,
            capability_id=capability_id,
            scope_id=scope_id,
            step_id=step_id,
            subjects=subject_items,
            expected=expected or {},
            observed=observed or {},
            repair_action=repair_action,
            repair_call_ids=tuple(repair_call_ids),
            original_message=message,
            authority_details=details or {},
        )
        self.code = code
        self.retryability = retryability
        super().__init__(message)

    def with_context(
        self,
        *,
        method_id: str | None = None,
        capability_id: str | None = None,
        scope_id: str | None = None,
        step_id: str | None = None,
    ) -> "StatelessMethodError":
        updated = replace(
            self.authority,
            method_id=method_id or self.authority.method_id,
            capability_id=capability_id or self.authority.capability_id,
            scope_id=scope_id or self.authority.scope_id,
            step_id=step_id or self.authority.step_id,
        )
        result = StatelessMethodError(
            updated.code,
            updated.original_message,
            category=updated.category,
            retryability=updated.retryability,
            method_id=updated.method_id,
            capability_id=updated.capability_id,
            scope_id=updated.scope_id,
            step_id=updated.step_id,
            subjects=updated.subjects,
            expected=_thaw(updated.expected),
            observed=_thaw(updated.observed),
            repair_action=updated.repair_action,
            repair_call_ids=updated.repair_call_ids,
            details=_thaw(updated.authority_details),
        )
        return result

    def with_input_read_authorities(
        self,
        authorities: Mapping[str, Sequence[Any]],
    ) -> "StatelessMethodError":
        """Attach prompt-projectable entity identity to Method subjects.

        A Method only sees runtime values, so its typed failure can name an
        input role but cannot safely recover the originating Math Entity.
        The invocation's read authority is the single owner of that mapping.
        Enrichment happens before prompt projection and never parses error
        prose or runtime paths to infer identity.
        """

        subjects: list[FunctionalDiagnosticSubject] = []
        for subject in self.authority.subjects:
            if subject.internal_ref is not None or subject.arg_name is None:
                subjects.append(subject)
                continue
            candidates = tuple(authorities.get(subject.arg_name, ()))
            if subject.item_index is not None:
                candidates = tuple(
                    item
                    for item in candidates
                    if getattr(item, "item_index", None) == subject.item_index
                )
            if len(candidates) != 1:
                subjects.append(subject)
                continue
            internal_ref = _diagnostic_identity_from_read_authority(
                candidates[0]
            )
            subjects.append(
                replace(subject, internal_ref=internal_ref)
                if internal_ref is not None
                else subject
            )
        updated = replace(self.authority, subjects=tuple(subjects))
        return StatelessMethodError(
            updated.code,
            updated.original_message,
            category=updated.category,
            retryability=updated.retryability,
            method_id=updated.method_id,
            capability_id=updated.capability_id,
            scope_id=updated.scope_id,
            step_id=updated.step_id,
            subjects=updated.subjects,
            expected=_thaw(updated.expected),
            observed=_thaw(updated.observed),
            repair_action=updated.repair_action,
            repair_call_ids=updated.repair_call_ids,
            details=_thaw(updated.authority_details),
        )


@dataclass(frozen=True)
class FunctionalPromptDiagnosticSubject:
    ref: str | Mapping[str, str] | None = None
    role: str | None = None
    arg_name: str | None = None
    item_index: int | None = None
    expected_type: str | None = None
    expected_state: str | None = None
    observed_type: str | None = None
    observed_state: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "ref": self.ref,
                "role": self.role,
                "arg_name": self.arg_name,
                "item_index": self.item_index,
                "expected_type": self.expected_type,
                "expected_state": self.expected_state,
                "observed_type": self.observed_type,
                "observed_state": self.observed_state,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class FunctionalPromptDiagnostic:
    code: str
    category: FunctionalDiagnosticCategory
    stage: str
    retryability: FunctionalDiagnosticRetryability
    subjects: tuple[FunctionalPromptDiagnosticSubject, ...]
    expected: Mapping[str, Any]
    observed: Mapping[str, Any]
    repair_action: str
    message: str
    method_id: str | None = None
    capability_id: str | None = None
    scope_id: str | None = None
    step_id: str | None = None
    repair_call_ids: tuple[str, ...] = ()
    schema_version: str = FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT

    def __post_init__(self) -> None:
        object.__setattr__(self, "subjects", tuple(self.subjects))
        object.__setattr__(self, "expected", _freeze(self.expected))
        object.__setattr__(self, "observed", _freeze(self.observed))
        object.__setattr__(
            self,
            "repair_call_ids",
            tuple(sorted(set(self.repair_call_ids))),
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "code": self.code,
            "category": self.category,
            "stage": self.stage,
            "retryability": self.retryability,
            "subjects": [item.to_payload() for item in self.subjects],
            "expected": _thaw(self.expected),
            "observed": _thaw(self.observed),
            "repair_action": self.repair_action,
            "repair_call_ids": list(self.repair_call_ids),
            "message": self.message,
        }
        for key, value in (
            ("method_id", self.method_id),
            ("capability_id", self.capability_id),
            ("scope_id", self.scope_id),
            ("step_id", self.step_id),
        ):
            if value is not None:
                payload[key] = value
        return payload

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "FunctionalPromptDiagnostic":
        candidate = dict(payload)
        _validate_payload(candidate, functional_prompt_diagnostic_schema())
        return cls(
            schema_version=str(candidate["schema_version"]),
            code=str(candidate["code"]),
            category=str(candidate["category"]),  # type: ignore[arg-type]
            stage=str(candidate["stage"]),
            retryability=str(candidate["retryability"]),  # type: ignore[arg-type]
            subjects=tuple(
                FunctionalPromptDiagnosticSubject(
                    ref=(
                        {
                            "step_id": str(_mapping(item["ref"])["step_id"]),
                            "return": str(_mapping(item["ref"])["return"]),
                        }
                        if isinstance(item.get("ref"), Mapping)
                        else _optional_string(item.get("ref"))
                    ),
                    role=_optional_string(item.get("role")),
                    arg_name=_optional_string(item.get("arg_name")),
                    item_index=_optional_nonnegative_int(
                        item.get("item_index")
                    ),
                    expected_type=_optional_string(item.get("expected_type")),
                    expected_state=_optional_string(item.get("expected_state")),
                    observed_type=_optional_string(item.get("observed_type")),
                    observed_state=_optional_string(item.get("observed_state")),
                )
                for item in (
                    _mapping(raw) for raw in _sequence(candidate["subjects"])
                )
            ),
            expected=_mapping(candidate["expected"]),
            observed=_mapping(candidate["observed"]),
            repair_action=str(candidate["repair_action"]),
            repair_call_ids=tuple(
                str(item) for item in _sequence(candidate["repair_call_ids"])
            ),
            message=str(candidate["message"]),
            method_id=_optional_string(candidate.get("method_id")),
            capability_id=_optional_string(candidate.get("capability_id")),
            scope_id=_optional_string(candidate.get("scope_id")),
            step_id=_optional_string(candidate.get("step_id")),
        )


class FunctionalPromptDiagnosticProjector:
    """Project internal diagnostic identity through F5-B/C authority only."""

    def project(
        self,
        authority: FunctionalDiagnosticAuthority,
        binding_catalog: Any,
        planning_context: Any,
        *,
        exact_result_refs: Mapping[str, Mapping[str, str]] | None = None,
    ) -> FunctionalPromptDiagnostic:
        if binding_catalog.planning_context_id != planning_context.planning_context_id:
            return self._configuration_failure(
                authority,
                "diagnostic binding authority belongs to another PlanningContext",
            )
        input_identities = _binding_identity_index(
            binding_catalog,
            usage="input",
        )
        input_runtime_nodes = _binding_runtime_node_index(
            binding_catalog,
            usage="input",
        )
        answer_identities = _binding_identity_index(
            binding_catalog,
            usage="answer",
            owner_scope_id=authority.scope_id,
        )
        answer_runtime_nodes = _binding_runtime_node_index(
            binding_catalog,
            usage="answer",
            owner_scope_id=authority.scope_id,
        )
        identities = _merge_identity_indexes(
            input_identities,
            answer_identities,
        )
        public_refs = {
            str(binding.semantic_ref.ref)
            for binding in binding_catalog.bindings.values()
        }
        prompt_subjects: list[FunctionalPromptDiagnosticSubject] = []
        unresolved: list[str] = []
        result_refs = dict(exact_result_refs or {})
        for subject in authority.subjects:
            public_ref: str | Mapping[str, str] | None = None
            if subject.internal_ref is not None:
                if subject.internal_ref in result_refs:
                    public_ref = dict(result_refs[subject.internal_ref])
                elif subject.internal_ref in public_refs:
                    public_ref = subject.internal_ref
                else:
                    matches = _preferred_identity_matches(
                        subject.internal_ref,
                        input_runtime_nodes=input_runtime_nodes,
                        answer_runtime_nodes=answer_runtime_nodes,
                        input_identities=input_identities,
                        answer_identities=answer_identities,
                    )
                    if len(matches) == 1:
                        public_ref = next(iter(matches))
                    else:
                        unresolved.append(subject.internal_ref)
            prompt_subjects.append(
                FunctionalPromptDiagnosticSubject(
                    ref=public_ref,
                    role=subject.role,
                    arg_name=subject.arg_name,
                    item_index=subject.item_index,
                    expected_type=subject.expected_type,
                    expected_state=subject.expected_state,
                    observed_type=subject.observed_type,
                    observed_state=subject.observed_state,
                )
            )
        if unresolved and authority.retryability == "planner_repairable":
            return self._configuration_failure(
                authority,
                "planner-repairable diagnostic contains unmapped internal identity",
            )
        try:
            projected_expected = _project_prompt_value(
                authority.expected,
                input_runtime_nodes=input_runtime_nodes,
                answer_runtime_nodes=answer_runtime_nodes,
                input_identities=input_identities,
                answer_identities=answer_identities,
                exact_result_refs=result_refs,
            )
            projected_observed = _project_prompt_value(
                authority.observed,
                input_runtime_nodes=input_runtime_nodes,
                answer_runtime_nodes=answer_runtime_nodes,
                input_identities=input_identities,
                answer_identities=answer_identities,
                exact_result_refs=result_refs,
            )
        except ValueError as error:
            return self._configuration_failure(authority, str(error))
        prompt = FunctionalPromptDiagnostic(
            code=authority.code,
            category=authority.category,
            stage=authority.stage,
            retryability=authority.retryability,
            method_id=authority.method_id,
            capability_id=authority.capability_id,
            scope_id=authority.scope_id,
            step_id=authority.step_id,
            subjects=tuple(prompt_subjects),
            expected=_prompt_safe_mapping(_mapping(projected_expected)),
            observed=_prompt_safe_mapping(_mapping(projected_observed)),
            repair_action=authority.repair_action,
            repair_call_ids=authority.repair_call_ids,
            message=_REPAIR_MESSAGES.get(
                authority.repair_action,
                _REPAIR_MESSAGES["repair_failed_step"],
            ),
        )
        _audit_projected_diagnostic(
            prompt.to_payload(),
            forbidden_values=frozenset(set(identities) - public_refs),
        )
        return prompt

    @staticmethod
    def _configuration_failure(
        authority: FunctionalDiagnosticAuthority,
        reason: str,
    ) -> FunctionalPromptDiagnostic:
        return FunctionalPromptDiagnostic(
            code="planner.method_contract_invalid",
            category="configuration",
            stage=authority.stage,
            retryability="configuration",
            method_id=authority.method_id,
            capability_id=authority.capability_id,
            scope_id=authority.scope_id,
            step_id=authority.step_id,
            subjects=tuple(
                FunctionalPromptDiagnosticSubject(
                    role=item.role,
                    arg_name=item.arg_name,
                    item_index=item.item_index,
                    expected_type=item.expected_type,
                    expected_state=item.expected_state,
                    observed_type=item.observed_type,
                    observed_state=item.observed_state,
                )
                for item in authority.subjects
            ),
            expected={},
            observed={"projection_failure": reason, "source_code": authority.code},
            repair_action="fix_runtime_contract",
            repair_call_ids=authority.repair_call_ids,
            message=_REPAIR_MESSAGES["fix_runtime_contract"],
        )


def diagnostic_authority_from_issue(
    issue: Any,
    *,
    stage: str,
    method_id: str | None = None,
    capability_id: str | None = None,
    scope_id: str | None = None,
    step_id: str | None = None,
) -> FunctionalDiagnosticAuthority:
    """Normalize resolver/compiler/runtime issues before prompt projection."""

    if isinstance(issue, Mapping):
        code = str(issue.get("code", "planner.method_contract_invalid"))
        message = str(issue.get("message", code))
        details = dict(issue.get("details") or {})
        if issue.get("path") is not None:
            details.setdefault("path", str(issue["path"]))
        issue_scope_id = _optional_string(issue.get("scope_id"))
        issue_step_id = _optional_string(
            issue.get("call_id") or issue.get("step_id")
        )
    else:
        code = str(getattr(issue, "code", "planner.method_contract_invalid"))
        message = str(getattr(issue, "message", str(issue)))
        details = dict(getattr(issue, "details", None) or {})
        if getattr(issue, "path", None) is not None:
            details.setdefault("path", str(issue.path))
        issue_scope_id = _optional_string(getattr(issue, "scope_id", None))
        issue_step_id = _optional_string(
            getattr(issue, "call_id", None) or getattr(issue, "step_id", None)
        )
    retryability = _retryability_for_code(code, details)
    category = _category_for_code(code)
    subjects = _subjects_from_details(details)
    expected = _prefixed_details(
        details,
        (
            "expected",
            "required",
            "requirement",
            "relation",
            "allowed",
            "legal",
            "repair_options",
        ),
    )
    observed = _prefixed_details(
        details,
        (
            "actual",
            "observed",
            "candidate",
            "available",
            "current",
            "duplicate",
            "existing",
            "missing",
            "unknown",
            "status",
            "branch_count",
            "compatible",
            "constraint_symbols",
            "declared",
            "free_symbol",
            "object_candidates",
            "remaining_free",
            "requested",
            "residual",
            "unchanged_binding",
        ),
        suffixes=("_candidates",),
        exact_keys=(
            "conditions",
            "endpoints",
            "materialized_points",
        ),
    )
    accepted_types = _string_sequence(details.get("accepted_item_types"))
    if accepted_types:
        expected.setdefault("accepted_types", list(accepted_types))
    accepted_condition_kinds = _string_sequence(
        details.get("accepted_condition_kinds")
    )
    if accepted_condition_kinds:
        expected.setdefault(
            "accepted_condition_kinds",
            list(accepted_condition_kinds),
        )
    accepted_semantic_roles = _string_sequence(
        details.get("accepted_semantic_roles")
    )
    if accepted_semantic_roles:
        expected.setdefault(
            "accepted_semantic_roles",
            list(accepted_semantic_roles),
        )
    available_types = _string_sequence(details.get("available_value_types"))
    if available_types:
        observed.setdefault("available_types", list(available_types))
    actual_type = _optional_string(
        details.get("actual_type") or details.get("observed_type")
    )
    if actual_type is not None:
        observed.pop("actual_type", None)
        observed.pop("observed_type", None)
        observed.setdefault("type", actual_type)
    if code.startswith("function.symbolic_closure_"):
        expected.setdefault("status", "unique")
        expected.setdefault("branch_count", 1)
        for key in (
            "status",
            "branch_count",
            "remaining_free",
            "equation_sources",
            "constraint_used",
        ):
            if key in details:
                observed.setdefault(key, _thaw(_freeze(details[key])))
        target = _optional_string(details.get("target"))
        if target is not None and not subjects:
            subjects = (
                FunctionalDiagnosticSubject(
                    role="target_parameter",
                    arg_name="target_parameter",
                    internal_ref=target,
                    expected_type="Symbol",
                    expected_state="uniquely_solved",
                    observed_state=str(details.get("status") or "unresolved"),
                ),
            )
    repair_action = _repair_action_for(code, category, details)
    return FunctionalDiagnosticAuthority(
        code=code,
        category=category,
        stage=stage,
        retryability=retryability,
        method_id=method_id or _optional_string(details.get("method_id")),
        capability_id=(
            capability_id or _optional_string(details.get("capability_id"))
        ),
        scope_id=(scope_id or issue_scope_id),
        step_id=(
            step_id
            or issue_step_id
        ),
        subjects=subjects,
        expected=expected,
        observed=observed,
        repair_action=repair_action,
        repair_call_ids=tuple(
            str(item) for item in details.get("repair_call_ids", ())
        ),
        original_message=message,
        authority_details=details,
    )


def unexpected_method_error(
    error: Exception,
    *,
    method_id: str,
    scope_id: str,
    step_id: str | None = None,
    capability_id: str | None = None,
) -> StatelessMethodError:
    """Wrap an untyped Method failure as a non-retryable contract bug."""

    return StatelessMethodError(
        "planner.method_contract_invalid",
        f"{type(error).__name__}: {error}",
        category="configuration",
        retryability="configuration",
        method_id=method_id,
        capability_id=capability_id,
        scope_id=scope_id,
        step_id=step_id,
        expected={"contract": "typed StatelessMethodError"},
        observed={"exception_type": type(error).__name__},
        repair_action="fix_runtime_contract",
        details={"raw_error": str(error)},
    )


def method_input_missing(
    message: str,
    **kwargs: Any,
) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_input_missing",
        message,
        category="input",
        retryability="planner_repairable",
        repair_action=kwargs.pop("repair_action", "provide_required_input"),
        **kwargs,
    )


def method_input_invalid(message: str, **kwargs: Any) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_input_invalid",
        message,
        category="input",
        retryability="planner_repairable",
        repair_action=kwargs.pop("repair_action", "repair_input_binding"),
        **kwargs,
    )


def macro_contract_invalid(message: str, **kwargs: Any) -> StatelessMethodError:
    """Report public-to-internal Macro lowering drift as configuration."""

    return StatelessMethodError(
        "planner.macro_contract_invalid",
        message,
        category="configuration",
        retryability="configuration",
        repair_action="fix_runtime_contract",
        **kwargs,
    )


def normalize_macro_diagnostic_authority(
    authority: FunctionalDiagnosticAuthority,
    *,
    macro_spec: Any,
    provided_arg_names: Sequence[str],
) -> FunctionalDiagnosticAuthority:
    """Translate an inner Method failure to the public Macro boundary.

    Internal Method facts remain in ``authority_details`` for debug.  Planner
    repair sees only public Macro arguments.  If a public argument was already
    supplied but could not reach the Method, the failure is compiler
    configuration drift and must not consume another semantic attempt.
    """

    adapter = getattr(macro_spec, "adapter", None)
    if adapter is None:
        return authority
    target_to_source = {
        target: source
        for source, target in getattr(adapter, "input_aliases", ())
    }
    target_to_source.update(
        {
            item.target: item.source_arg
            for item in getattr(adapter, "input_derivations", ())
        }
    )
    provided = frozenset(str(item) for item in provided_arg_names)
    method_id = authority.method_id

    def public_arg(input_name: str) -> str | None:
        if method_id is None:
            return None
        return target_to_source.get(f"{method_id}.{input_name}")

    missing_inputs = tuple(
        dict.fromkeys(
            str(item)
            for item in (
                authority.observed.get("missing_inputs")
                or authority.expected.get("required_inputs")
                or ()
            )
        )
    )
    mapped_missing = tuple(
        dict.fromkeys(
            source
            for item in missing_inputs
            if (source := public_arg(item)) is not None
        )
    )
    absent_public = tuple(
        item for item in mapped_missing if item not in provided
    )
    inner_details = {
        **dict(authority.authority_details),
        "inner_diagnostic": authority.to_payload(),
    }
    if missing_inputs:
        if absent_public:
            return replace(
                authority,
                code="functional.macro_input_missing",
                category="input",
                retryability="planner_repairable",
                method_id=None,
                subjects=tuple(
                    FunctionalDiagnosticSubject(
                        role=item,
                        arg_name=item,
                        expected_state="provided",
                    )
                    for item in absent_public
                ),
                expected={"required_args": absent_public},
                observed={"provided_args": tuple(sorted(provided))},
                repair_action="provide_macro_input",
                authority_details=inner_details,
            )
        return replace(
            authority,
            code="planner.macro_contract_invalid",
            category="configuration",
            retryability="configuration",
            method_id=None,
            subjects=(),
            expected={"public_args": tuple(sorted(provided))},
            observed={"lowering": "incomplete"},
            repair_action="fix_runtime_contract",
            authority_details=inner_details,
        )

    subjects = tuple(
        replace(
            subject,
            role=(public_arg(subject.arg_name) or subject.role),
            # An inner Method input name is compiler-owned. Keep the semantic
            # object role/ref, but only expose arg_name when it maps to a
            # public Macro argument.
            arg_name=public_arg(subject.arg_name),
        )
        if subject.arg_name is not None
        else subject
        for subject in authority.subjects
    )
    return replace(
        authority,
        method_id=None,
        subjects=subjects,
        authority_details=inner_details,
    )


def method_input_state_unavailable(
    message: str,
    **kwargs: Any,
) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_input_state_unavailable",
        message,
        category="input",
        retryability="planner_repairable",
        repair_action=kwargs.pop(
            "repair_action", "provide_visible_state_producer"
        ),
        **kwargs,
    )


def method_precondition_failed(
    message: str,
    **kwargs: Any,
) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_precondition_failed",
        message,
        category="precondition",
        retryability=kwargs.pop("retryability", "planner_repairable"),
        repair_action=kwargs.pop(
            "repair_action", "choose_applicable_capability"
        ),
        **kwargs,
    )


def method_result_empty(message: str, **kwargs: Any) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_result_empty",
        message,
        category="result",
        retryability="planner_repairable",
        repair_action=kwargs.pop("repair_action", "repair_failed_step"),
        **kwargs,
    )


def method_result_ambiguous(message: str, **kwargs: Any) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_result_ambiguous",
        message,
        category="ambiguity",
        retryability="planner_repairable",
        repair_action=kwargs.pop(
            "repair_action", "supply_disambiguating_constraint"
        ),
        **kwargs,
    )


def method_result_inconsistent(
    message: str,
    **kwargs: Any,
) -> StatelessMethodError:
    return StatelessMethodError(
        "functional.method_result_inconsistent",
        message,
        category="inconsistency",
        retryability=kwargs.pop("retryability", "problem_semantics"),
        repair_action=kwargs.pop(
            "repair_action", "revise_inconsistent_constraints"
        ),
        **kwargs,
    )


def method_check_failed(
    checks: Sequence[Any],
    *,
    method_id: str | None = None,
) -> StatelessMethodError:
    names = tuple(str(getattr(item, "name", item)) for item in checks)
    subjects = tuple(
        FunctionalDiagnosticSubject(
            role=_optional_string(subject.get("role")),
            arg_name=_optional_string(subject.get("arg_name")),
            item_index=_optional_nonnegative_int(subject.get("item_index")),
            internal_ref=_optional_string(subject.get("internal_ref")),
            expected_type=_optional_string(subject.get("expected_type")),
            expected_state=_optional_string(subject.get("expected_state")),
            observed_type=_optional_string(subject.get("observed_type")),
            observed_state=_optional_string(subject.get("observed_state")),
        )
        for item in checks
        for subject in getattr(item, "subjects", ())
        if isinstance(subject, Mapping)
    )
    details = [
        {
            "name": str(getattr(item, "name", item)),
            "detail": str(getattr(item, "detail", "")),
            "code": getattr(item, "code", None),
            "expected": dict(getattr(item, "expected", {}) or {}),
            "observed": dict(getattr(item, "observed", {}) or {}),
            "subjects": [
                dict(subject)
                for subject in getattr(item, "subjects", ())
                if isinstance(subject, Mapping)
            ],
            "repair_action": getattr(
                item,
                "repair_action",
                "repair_failed_step",
            ),
        }
        for item in checks
    ]
    retryabilities = {
        str(getattr(item, "retryability", "planner_repairable"))
        for item in checks
    }
    retryability: FunctionalDiagnosticRetryability = (
        "configuration"
        if "configuration" in retryabilities
        else (
            "problem_semantics"
            if "problem_semantics" in retryabilities
            else "planner_repairable"
        )
    )
    return StatelessMethodError(
        "functional.method_check_failed",
        "method runtime checks failed: " + ", ".join(names),
        category="check",
        retryability=retryability,
        method_id=method_id,
        subjects=subjects,
        expected={"status": "passed"},
        observed={"failed_checks": details},
        repair_action=(
            "fix_runtime_contract"
            if retryability == "configuration"
            else "repair_failed_step"
        ),
        details={"failed_checks": details},
    )


def functional_diagnostic_authority_schema() -> dict[str, Any]:
    return _diagnostic_schema(prompt=False)


def functional_prompt_diagnostic_schema() -> dict[str, Any]:
    return _diagnostic_schema(prompt=True)


def _diagnostic_schema(*, prompt: bool) -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    subject_properties: dict[str, Any] = {
        "role": nonempty,
        "arg_name": nonempty,
        "item_index": {"type": "integer", "minimum": 0},
        "expected_type": nonempty,
        "expected_state": nonempty,
        "observed_type": nonempty,
        "observed_state": nonempty,
    }
    subject_properties["ref" if prompt else "internal_ref"] = (
        {
            "oneOf": [
                nonempty,
                {
                    "type": "object",
                    "required": ["step_id", "return"],
                    "properties": {
                        "step_id": nonempty,
                        "return": nonempty,
                    },
                    "additionalProperties": False,
                },
            ]
        }
        if prompt
        else nonempty
    )
    required = [
        "schema_version",
        "code",
        "category",
        "stage",
        "retryability",
        "subjects",
        "expected",
        "observed",
        "repair_action",
        "repair_call_ids",
        "message" if prompt else "original_message",
    ]
    if not prompt:
        required.append("authority_details")
    properties: dict[str, Any] = {
        "schema_version": {
            "const": (
                FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT
                if prompt
                else FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT
            )
        },
        "code": nonempty,
        "category": {
            "enum": [
                "input",
                "precondition",
                "result",
                "ambiguity",
                "inconsistency",
                "check",
                "binding",
                "configuration",
            ]
        },
        "stage": nonempty,
        "retryability": {
            "enum": [
                "planner_repairable",
                "problem_semantics",
                "configuration",
            ]
        },
        "method_id": nonempty,
        "capability_id": nonempty,
        "scope_id": nonempty,
        "step_id": nonempty,
        "subjects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": subject_properties,
                "additionalProperties": False,
            },
        },
        "expected": {"type": "object"},
        "observed": {"type": "object"},
        "repair_action": nonempty,
        "repair_call_ids": {
            "type": "array",
            "uniqueItems": True,
            "items": nonempty,
        },
        "message" if prompt else "original_message": {"type": "string"},
    }
    if not prompt:
        properties["authority_details"] = {"type": "object"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "functional-prompt-diagnostic.schema.json"
            if prompt
            else "functional-diagnostic-authority.schema.json"
        ),
        "title": (
            "Functional Prompt Diagnostic v1"
            if prompt
            else "Functional Diagnostic Authority v1"
        ),
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _binding_identity_index(
    binding_catalog: Any,
    *,
    usage: str,
    owner_scope_id: str | None = None,
) -> dict[str, frozenset[str]]:
    values: dict[str, set[str]] = {}
    for binding in binding_catalog.bindings.values():
        if binding.usage != usage:
            continue
        if owner_scope_id is not None and binding.owner_scope_id != owner_scope_id:
            continue
        ref = str(binding.semantic_ref.ref)
        identities = {str(binding.runtime_node_id), *map(str, binding.source_unit_ids)}
        identities.add(ref)
        identities.update(_binding_context_path_aliases(binding))
        for source in binding.typed_sources:
            if source.math_object_id is not None:
                identities.add(str(source.math_object_id.value))
            if source.condition_id is not None:
                identities.add(str(source.condition_id))
            if source.state_slot_id is not None:
                identities.add(str(source.state_slot_id))
            if source.state_version_id is not None:
                identities.add(_identity_string(source.state_version_id))
        for identity in identities:
            values.setdefault(identity, set()).add(ref)
    return {key: frozenset(item) for key, item in values.items()}


_SEMANTIC_KIND_CONTEXT_CONTAINERS: Mapping[str, str] = {
    "point": "points",
    "symbol": "symbols",
    "quadratic_function": "expressions",
    "segment": "segments",
    "named_line": "lines",
    "named_ray": "rays",
    "polygon": "polygons",
    "scalar_expression": "expressions",
}


def _binding_context_path_aliases(binding: Any) -> frozenset[str]:
    """Index runtime paths by source identity without parsing error prose.

    Runtime diagnostics may originate after a typed binding has been lowered to
    a ContextPath.  The path's scope, container, and key are still mechanical
    projections of the F5-B/C source binding, so they are safe aliases for
    prompt projection.  Step-local paths are intentionally never synthesized.
    """

    semantic_ref = binding.semantic_ref
    container = _SEMANTIC_KIND_CONTEXT_CONTAINERS.get(str(semantic_ref.kind))
    owner_scope_id = str(binding.owner_scope_id)
    local_ref = str(semantic_ref.ref)
    if container is None or not owner_scope_id or not local_ref:
        return frozenset()
    if owner_scope_id == "problem":
        return frozenset({f"$problem.{container}.{local_ref}"})
    return frozenset(
        {
            f"$question.{owner_scope_id}.{container}.{local_ref}",
            f"$subquestion.{owner_scope_id}.{container}.{local_ref}",
        }
    )


def _binding_runtime_node_index(
    binding_catalog: Any,
    *,
    usage: str,
    owner_scope_id: str | None = None,
) -> dict[str, frozenset[str]]:
    values: dict[str, set[str]] = {}
    for binding in binding_catalog.bindings.values():
        if binding.usage != usage:
            continue
        if owner_scope_id is not None and binding.owner_scope_id != owner_scope_id:
            continue
        values.setdefault(str(binding.runtime_node_id), set()).add(
            str(binding.semantic_ref.ref)
        )
    return {key: frozenset(item) for key, item in values.items()}


def _preferred_identity_matches(
    identity: str,
    *,
    input_runtime_nodes: Mapping[str, frozenset[str]],
    answer_runtime_nodes: Mapping[str, frozenset[str]],
    input_identities: Mapping[str, frozenset[str]],
    answer_identities: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    for index in (
        input_runtime_nodes,
        answer_runtime_nodes,
        input_identities,
        answer_identities,
    ):
        matches = index.get(identity, frozenset())
        if matches:
            return matches
    return frozenset()


def _merge_identity_indexes(
    *indexes: Mapping[str, frozenset[str]],
) -> dict[str, frozenset[str]]:
    merged: dict[str, set[str]] = {}
    for index in indexes:
        for identity, refs in index.items():
            merged.setdefault(identity, set()).update(refs)
    return {key: frozenset(value) for key, value in merged.items()}


def _project_prompt_value(
    value: Any,
    *,
    input_runtime_nodes: Mapping[str, frozenset[str]],
    answer_runtime_nodes: Mapping[str, frozenset[str]],
    input_identities: Mapping[str, frozenset[str]],
    answer_identities: Mapping[str, frozenset[str]],
    exact_result_refs: Mapping[str, Mapping[str, str]],
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _project_prompt_value(
                item,
                input_runtime_nodes=input_runtime_nodes,
                answer_runtime_nodes=answer_runtime_nodes,
                input_identities=input_identities,
                answer_identities=answer_identities,
                exact_result_refs=exact_result_refs,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _project_prompt_value(
                item,
                input_runtime_nodes=input_runtime_nodes,
                answer_runtime_nodes=answer_runtime_nodes,
                input_identities=input_identities,
                answer_identities=answer_identities,
                exact_result_refs=exact_result_refs,
            )
            for item in value
        ]
    if not isinstance(value, str):
        return value
    if value in exact_result_refs:
        return dict(exact_result_refs[value])
    matches = _preferred_identity_matches(
        value,
        input_runtime_nodes=input_runtime_nodes,
        answer_runtime_nodes=answer_runtime_nodes,
        input_identities=input_identities,
        answer_identities=answer_identities,
    )
    if len(matches) == 1:
        return next(iter(matches))
    if matches:
        raise ValueError(
            "diagnostic identity maps to multiple prompt-visible references"
        )
    return value


def _subjects_from_details(
    details: Mapping[str, Any],
) -> tuple[FunctionalDiagnosticSubject, ...]:
    declared_result: list[FunctionalDiagnosticSubject] = []
    declared_subjects = details.get("subjects")
    if isinstance(declared_subjects, (list, tuple)):
        declared_result.extend(
            FunctionalDiagnosticSubject(
                role=_optional_string(item.get("role")),
                arg_name=_optional_string(item.get("arg_name")),
                item_index=_optional_nonnegative_int(item.get("item_index")),
                internal_ref=_optional_string(item.get("internal_ref")),
                expected_type=_optional_string(item.get("expected_type")),
                expected_state=_optional_string(item.get("expected_state")),
                observed_type=_optional_string(item.get("observed_type")),
                observed_state=_optional_string(item.get("observed_state")),
            )
            for item in declared_subjects
            if isinstance(item, Mapping)
        )
    current_bindings = details.get("current_bindings")
    if not declared_result and isinstance(current_bindings, (list, tuple)):
        for item in current_bindings:
            if not isinstance(item, Mapping):
                continue
            source_call_id = _optional_string(item.get("source_call_id"))
            return_name = _optional_string(item.get("return"))
            internal_ref = _optional_string(
                item.get("object_ref")
                or item.get("semantic_ref")
                or item.get("internal_ref")
            )
            if (
                internal_ref is None
                and source_call_id is not None
                and return_name is not None
            ):
                internal_ref = f"{source_call_id}.{return_name}"
            internal_ref = internal_ref or _optional_string(
                item.get("state_slot_id") or item.get("handle")
            )
            declared_result.append(
                FunctionalDiagnosticSubject(
                    role=_optional_string(
                        item.get("role")
                        or item.get("semantic_role")
                        or details.get("semantic_role")
                    ),
                    arg_name=_optional_string(
                        item.get("arg_name") or item.get("arg")
                    ),
                    item_index=_optional_nonnegative_int(
                        item.get("item_index")
                    ),
                    internal_ref=internal_ref,
                    expected_type=_optional_string(
                        item.get("expected_type")
                    ),
                    expected_state=_optional_string(
                        item.get("expected_state")
                    ),
                    observed_type=_optional_string(
                        item.get("observed_type")
                    ),
                    observed_state=_optional_string(
                        item.get("observed_state")
                    ),
                )
            )
    if declared_result:
        return tuple(dict.fromkeys(declared_result))
    candidate_subject_specs = (
        ("symbol_candidates", "parameter_candidate", "Symbol"),
        ("condition_candidates", "condition_candidate", "Condition"),
        ("target_candidates", "target_candidate", "Point"),
        ("object_candidates", "object_candidate", None),
    )
    for key, candidate_role, candidate_type in candidate_subject_specs:
        values = details.get(key)
        if not isinstance(values, (list, tuple, set, frozenset)):
            continue
        for value in values:
            declared_result.append(
                FunctionalDiagnosticSubject(
                    role=candidate_role,
                    internal_ref=_identity_string(value),
                    expected_type=(
                        candidate_type
                        or _optional_string(details.get("expected_type"))
                    ),
                    expected_state="candidate",
                )
            )
    if declared_result:
        return tuple(dict.fromkeys(declared_result))
    refs: list[str] = []
    source_call_id = _optional_string(details.get("source_call_id"))
    source_return_name = _optional_string(details.get("source_return_name"))
    if source_call_id is not None and source_return_name is not None:
        refs.append(f"{source_call_id}.{source_return_name}")
    for key in (
        "semantic_ref",
        "source_ref",
        "object_ref",
        "target_object_ref",
        "actual_object_ref",
        "expected_object_ref",
        "expected_ref",
        "moving_object",
        "unresolved_point_ref",
    ):
        value = details.get(key)
        if value is not None:
            refs.append(_identity_string(value))
    for key in (
        "object_refs",
        "actual_object_refs",
        "expected_object_refs",
    ):
        value = details.get(key)
        if isinstance(value, (list, tuple, set, frozenset)):
            refs.extend(_identity_string(item) for item in value)
    refs = list(dict.fromkeys(refs))
    role = _optional_string(details.get("role") or details.get("semantic_role"))
    arg_name = _optional_string(details.get("arg_name") or details.get("arg"))
    accepted_types = _string_sequence(details.get("accepted_item_types"))
    expected_type = _optional_string(
        details.get("expected_type") or details.get("runtime_type")
    )
    if expected_type is None and len(accepted_types) == 1:
        expected_type = accepted_types[0]
    expected_state = _optional_string(
        details.get("expected_state") or details.get("state_requirement")
    )
    observed_type = _optional_string(
        details.get("actual_type") or details.get("observed_type")
    )
    observed_state = _optional_string(
        details.get("actual_state") or details.get("observed_state")
    )
    item_index = _optional_nonnegative_int(details.get("item_index"))
    if not refs and any(
        item is not None
        for item in (role, arg_name, expected_type, expected_state, observed_type)
    ):
        refs.append("")
    return tuple(
        FunctionalDiagnosticSubject(
            role=role,
            arg_name=arg_name,
            item_index=item_index,
            internal_ref=ref or None,
            expected_type=expected_type,
            expected_state=expected_state,
            observed_type=observed_type,
            observed_state=observed_state,
        )
        for ref in refs
    )


def _category_for_code(code: str) -> FunctionalDiagnosticCategory:
    lowered = code.lower()
    if code in _CONFIGURATION_CODES or "configuration" in lowered:
        return "configuration"
    if "ambiguous" in lowered or "multiple" in lowered or "candidate" in lowered:
        return "ambiguity"
    if "conflict" in lowered or "inconsistent" in lowered or "drift" in lowered:
        return "inconsistency"
    if "check" in lowered:
        return "check"
    if "binding" in lowered or "ref_" in lowered:
        return "binding"
    if code.startswith("functional.method_relation_"):
        return "binding"
    if code.startswith("functional.arg_"):
        return "input"
    if "unavailable" in lowered or "missing" in lowered or "unresolved" in lowered:
        return "input"
    return "precondition"


def _retryability_for_code(
    code: str,
    details: Mapping[str, Any],
) -> FunctionalDiagnosticRetryability:
    explicit = details.get("retryability")
    if explicit in {"planner_repairable", "problem_semantics", "configuration"}:
        return explicit
    if code in _CONFIGURATION_CODES or "configuration" in code:
        return "configuration"
    if "source_semantics" in code or "problem_semantics" in code:
        return "problem_semantics"
    return "planner_repairable"


def _repair_action_for(
    code: str,
    category: FunctionalDiagnosticCategory,
    details: Mapping[str, Any],
) -> str:
    explicit = details.get("repair_action")
    if isinstance(explicit, str) and explicit:
        return explicit
    if category == "configuration":
        return "fix_runtime_contract"
    if "state_unavailable" in code:
        if str(details.get("runtime_type", "")) == "Point":
            return "provide_visible_point_producer"
        return "provide_visible_state_producer"
    if category == "ambiguity":
        return "supply_disambiguating_constraint"
    if category == "inconsistency":
        return "revise_inconsistent_constraints"
    if category in {"input", "binding"}:
        return "repair_input_binding"
    if category == "precondition":
        return "choose_applicable_capability"
    return "repair_failed_step"


def _prefixed_details(
    details: Mapping[str, Any],
    prefixes: Sequence[str],
    *,
    suffixes: Sequence[str] = (),
    exact_keys: Sequence[str] = (),
) -> dict[str, Any]:
    exact = frozenset(exact_keys)
    return {
        str(key): _thaw(_freeze(value))
        for key, value in details.items()
        if (
            any(str(key).startswith(prefix) for prefix in prefixes)
            or any(str(key).endswith(suffix) for suffix in suffixes)
            or str(key) in exact
        )
    }


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(item) for item in value if str(item))


def _prompt_safe_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    forbidden_fragments = (
        "artifact",
        "binding_signature",
        "condition_id",
        "math_object_id",
        "problem_revision",
        "runtime_node",
        "runtime_path",
        "source_unit",
        "state_slot",
        "state_version",
    )
    def project(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                str(key): project(nested)
                for key, nested in item.items()
                if not any(
                    fragment in str(key).lower()
                    for fragment in forbidden_fragments
                )
            }
        if isinstance(item, (list, tuple, set, frozenset)):
            return [project(nested) for nested in item]
        return _thaw(item)

    return project(value)


def _audit_projected_diagnostic(
    payload: Mapping[str, Any],
    *,
    forbidden_values: frozenset[str],
) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    leaks = tuple(
        sorted(value for value in forbidden_values if value and value in text)
    )
    if leaks:
        raise ValueError(
            "planner.method_contract_invalid: prompt diagnostic leaked internal "
            f"identity: {leaks[:3]}"
        )
    if "<internal-identity-omitted>" in text:
        raise ValueError(
            "planner.method_contract_invalid: prompt diagnostic used an identity "
            "placeholder"
        )


def _identity_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if hasattr(value, "to_payload") and callable(value.to_payload):
        return json.dumps(
            value.to_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return str(value)


def _diagnostic_identity_from_read_authority(authority: Any) -> str | None:
    """Return the semantic identity pinned by one Method read authority."""

    source = getattr(authority, "source", None)
    kind = getattr(source, "kind", None)
    if kind == "entity_identity":
        return _optional_string(getattr(source, "entity_handle", None))
    if kind == "state_version":
        version_id = getattr(source, "state_version_id", None)
        try:
            return str(
                version_id.slot_id.logical_key.object_id.value
            )
        except AttributeError:
            return None
    if kind == "condition":
        return _optional_string(getattr(source, "condition_id", None))
    if kind == "call_result":
        call_id = _optional_string(getattr(source, "call_id", None))
        return_name = _optional_string(getattr(source, "return_name", None))
        if call_id is not None and return_name is not None:
            return f"{call_id}.{return_name}"
    return None


def _validate_payload(payload: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(dict(payload)),
        key=lambda item: tuple(item.absolute_path),
    )
    if errors:
        first = errors[0]
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in first.absolute_path
        )
        raise ValueError(f"invalid Functional diagnostic at {path}: {first.message}")


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("diagnostic item_index must be a non-negative integer")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("expected mapping")
    return value


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError("expected sequence")
    return value


__all__ = [
    "FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT",
    "FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT",
    "FunctionalDiagnosticAuthority",
    "FunctionalDiagnosticSubject",
    "FunctionalPromptDiagnostic",
    "FunctionalPromptDiagnosticProjector",
    "StatelessMethodError",
    "diagnostic_authority_from_issue",
    "functional_diagnostic_authority_schema",
    "functional_prompt_diagnostic_schema",
    "macro_contract_invalid",
    "method_check_failed",
    "method_input_invalid",
    "method_input_missing",
    "method_input_state_unavailable",
    "method_precondition_failed",
    "method_result_ambiguous",
    "method_result_empty",
    "method_result_inconsistent",
    "normalize_macro_diagnostic_authority",
    "unexpected_method_error",
]
