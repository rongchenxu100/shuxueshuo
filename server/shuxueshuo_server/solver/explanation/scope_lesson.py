"""F5-F5B3 Scope-owned Lesson authoring and validation.

The module consumes the B2 annotated teaching request without changing it.  It
keeps the LLM response deliberately small: the model writes student-facing
Scope bodies, while material provenance, answers, and runtime authority remain
code-owned.

The B4 ``LessonAuthoringPipeline`` consumes its accepted/fallback result and
assembles the recursive production ``LessonIR`` without a second LLM contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from time import perf_counter, sleep
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from shuxueshuo_server.solver.runtime.llm_clients import (
    LLMClientConfigurationError,
    LLMPlannerClient,
    LLMProviderResponseError,
)
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.student_display import find_internal_math_tokens

from .annotated_teaching import (
    DERIVE_MARKERS,
    LESSON_SCOPE_CONTENT_CONTRACT,
    AnnotatedTeachingGoal,
    AnnotatedTeachingMaterial,
    AnnotatedTeachingPlan,
    AnnotatedTeachingPlanProjector,
    AnnotatedTeachingProjection,
    AnnotatedTeachingPrompt,
    AnnotatedTeachingScope,
    build_projection_audit,
    find_forbidden_llm_tokens,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from .models import ExplanationSnapshot


SCOPE_LESSON_VALIDATION_CONTRACT = "lesson-scope-validation/v1"
SCOPE_LESSON_GENERATION_CONTRACT = "lesson-scope-generation-result/v1"
SCOPE_LESSON_EVALUATION_CONTRACT = "lesson-scope-evaluation/v1"
SCOPE_LESSON_REASONING_DEBUG_CONTRACT = "lesson-provider-reasoning-debug/v1"

ScopeLessonSource = Literal["llm", "deterministic_fallback"]

_TITLE_MAX = 80
_NAV_TITLE_MAX = 40
_GOAL_MAX = 240
_DERIVE_MAX_ITEMS = 32
_DERIVE_TEXT_MAX = 500

_HTML_OR_CODE_PATTERN = re.compile(
    r"```|<\s*(?:script|style|svg|iframe|html|body)\b|javascript\s*:",
    re.IGNORECASE,
)
_LONG_HEX_PATTERN = re.compile(r"(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])", re.I)
_UPPER_OBJECT_PATTERN = re.compile(r"[A-Z](?:[′'][′']?)?")
_TRANSIENT_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "InternalServerError",
    "RateLimitError",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
}


class ScopeLessonConfigurationError(RuntimeError):
    """The B2 authority cannot produce a complete, safe B3 result."""


@dataclass(frozen=True)
class ScopeLessonDiagnostic:
    code: str
    stage: str
    path: str
    message: str
    scope_ref: str | None = None
    severity: Literal["error", "warning"] = "error"

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "stage": self.stage,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }
        if self.scope_ref is not None:
            payload["scope_ref"] = self.scope_ref
        return payload


@dataclass(frozen=True)
class BoundLessonStep:
    """One accepted presentation step bound to code-owned material authority."""

    container_ref: str
    material_positions: tuple[int, ...]
    teaching_step_refs: tuple[str, ...]
    source_step_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    unit_keys: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    title: str
    nav_title: str
    goal: str
    derive: tuple[tuple[str, str], ...]
    box: tuple[str, ...]

    @property
    def material_count(self) -> int:
        """Internal metric retained for review aggregation, not LLM wire."""

        return len(self.teaching_step_refs)

    def content_payload(self) -> dict[str, Any]:
        return {
            "source_steps": list(self.teaching_step_refs),
            "title": self.title,
            "nav_title": self.nav_title,
            "goal": self.goal,
            "derive": [list(item) for item in self.derive],
            "box": list(self.box),
        }

    def review_payload(self) -> dict[str, Any]:
        return {
            **self.content_payload(),
            "container_ref": self.container_ref,
            "material_positions": list(self.material_positions),
            "source_step_ids": list(self.source_step_ids),
            "capability_ids": list(self.capability_ids),
            "unit_keys": list(self.unit_keys),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ScopeLessonValidationResult:
    accepted_content: Mapping[str, Any]
    parsed_response: Mapping[str, Any] | None
    bound_steps: Mapping[str, tuple[BoundLessonStep, ...]]
    scope_sources: Mapping[str, ScopeLessonSource]
    diagnostics: tuple[ScopeLessonDiagnostic, ...]
    whole_fallback: bool
    syntax_repaired: bool = False
    repaired_response: str | None = None
    appended_suffix: str = ""
    removed_suffix: str = ""

    @property
    def fallback_used(self) -> bool:
        return self.independent_material_merge_repaired or any(
            source == "deterministic_fallback"
            for source in self.scope_sources.values()
        )

    @property
    def direct_acceptance(self) -> bool:
        return not self.fallback_used

    @property
    def source_step_completion_repaired(self) -> bool:
        """Whether one omitted local teaching step was filled deterministically."""

        return any(
            item.code == "lesson_scope_single_source_step_completed"
            for item in self.diagnostics
        )

    @property
    def independent_material_merge_repaired(self) -> bool:
        """Whether an LLM row crossed a code-owned visual teaching boundary."""

        return any(
            item.code == "lesson_scope_independent_material_merge_repaired"
            for item in self.diagnostics
        )

    @property
    def contract_pass(self) -> bool:
        return not any(
            item.severity == "error"
            and item.stage in {"parse", "root", "scope", "coverage", "text"}
            for item in self.diagnostics
        )

    @property
    def authority_pass(self) -> bool:
        return not any(
            item.severity == "error" and item.stage == "authority"
            for item in self.diagnostics
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCOPE_LESSON_VALIDATION_CONTRACT,
            "direct_acceptance": self.direct_acceptance,
            "contract_pass": self.contract_pass,
            "authority_pass": self.authority_pass,
            "whole_fallback": self.whole_fallback,
            "fallback_used": self.fallback_used,
            "syntax_repaired": self.syntax_repaired,
            "source_step_completion_repaired": (
                self.source_step_completion_repaired
            ),
            "independent_material_merge_repaired": (
                self.independent_material_merge_repaired
            ),
            "appended_suffix": self.appended_suffix,
            "removed_suffix": self.removed_suffix,
            "repaired_response_hash": (
                _stable_hash(self.repaired_response)
                if self.repaired_response is not None
                else None
            ),
            "scope_sources": dict(self.scope_sources),
            "diagnostics": [item.to_payload() for item in self.diagnostics],
            "bound_steps": {
                key: [item.review_payload() for item in items]
                for key, items in self.bound_steps.items()
            },
        }


@dataclass(frozen=True)
class ScopeLessonTransportAttempt:
    transport_attempt: int
    duration_seconds: float
    prompt_hash: str
    raw_response: str
    visible_response: bool
    error: str | None
    retryable: bool
    usage: Mapping[str, Any]
    provider: str | None
    request_model: str | None
    response_model: str | None
    provider_attempts: tuple[Mapping[str, Any], ...]
    provider_reasoning: tuple[Mapping[str, Any], ...]
    reasoning_available: bool
    reasoning_chars: int

    @property
    def reasoning_debug_filename(self) -> str:
        return f"transport-attempt-{self.transport_attempt:02d}.reasoning.json"

    def reasoning_debug_payload(self) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        captured_chars = 0
        for index, item in enumerate(self.provider_reasoning, start=1):
            content = item.get("reasoning_content")
            text = "" if content is None else str(content)
            captured_chars += len(text)
            provider_attempt = item.get("provider_attempt")
            attempts.append(
                {
                    "provider_attempt": (
                        provider_attempt
                        if isinstance(provider_attempt, int)
                        and not isinstance(provider_attempt, bool)
                        else index
                    ),
                    "reasoning_content": text,
                    "reasoning_content_chars": len(text),
                    "reasoning_content_hash": (
                        _stable_hash(text) if text else None
                    ),
                }
            )
        return {
            "schema_version": SCOPE_LESSON_REASONING_DEBUG_CONTRACT,
            "debug_only": True,
            "transport_attempt": self.transport_attempt,
            "prompt_hash": self.prompt_hash,
            "provider": self.provider,
            "request_model": self.request_model,
            "response_model": self.response_model,
            "reasoning_content_available": self.reasoning_available,
            "reasoning_content_chars": self.reasoning_chars,
            "captured_reasoning_content_chars": captured_chars,
            "capture_complete": captured_chars == self.reasoning_chars,
            "provider_attempts": attempts,
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "transport_attempt": self.transport_attempt,
            "duration_seconds": self.duration_seconds,
            "prompt_hash": self.prompt_hash,
            "visible_response": self.visible_response,
            "error": self.error,
            "retryable": self.retryable,
            "usage": dict(self.usage),
            "provider": self.provider,
            "request_model": self.request_model,
            "response_model": self.response_model,
            "provider_attempts": [dict(item) for item in self.provider_attempts],
            "reasoning_content_available": self.reasoning_available,
            "reasoning_content_chars": self.reasoning_chars,
            "reasoning_debug_artifact": self.reasoning_debug_filename,
            "reasoning_content_hashes": [
                item["reasoning_content_hash"]
                for item in self.reasoning_debug_payload()["provider_attempts"]
            ],
            "first_token_seconds": None,
            "first_token_unavailable_reason": (
                "provider_client_uses_non_streaming_chat_completions"
            ),
            "raw_response_hash": (
                _stable_hash(self.raw_response) if self.raw_response else None
            ),
        }


@dataclass(frozen=True)
class ScopeLessonGenerationResult:
    projection: AnnotatedTeachingProjection
    output_schema: Mapping[str, Any]
    prompt: AnnotatedTeachingPrompt
    projection_audit: Mapping[str, Any]
    raw_response: str
    validation: ScopeLessonValidationResult
    deterministic_fallback: Mapping[str, Any]
    transport_attempts: tuple[ScopeLessonTransportAttempt, ...]
    semantic_attempt_count: int = 1

    @property
    def usage(self) -> dict[str, int]:
        result = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for attempt in self.transport_attempts:
            for key in tuple(result):
                value = attempt.usage.get(key)
                if isinstance(value, int):
                    result[key] += value
        return result

    def metadata_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SCOPE_LESSON_GENERATION_CONTRACT,
            "semantic_attempt_count": self.semantic_attempt_count,
            "transport_request_count": len(self.transport_attempts),
            "raw_response_received": bool(self.raw_response.strip()),
            "direct_acceptance": self.validation.direct_acceptance,
            "fallback_used": self.validation.fallback_used,
            "syntax_repaired": self.validation.syntax_repaired,
            "source_step_completion_repaired": (
                self.validation.source_step_completion_repaired
            ),
            "independent_material_merge_repaired": (
                self.validation.independent_material_merge_repaired
            ),
            "appended_suffix": self.validation.appended_suffix,
            "removed_suffix": self.validation.removed_suffix,
            "scope_sources": dict(self.validation.scope_sources),
            "hashes": dict(self.projection_audit["hashes"]),
            "usage": self.usage,
            "provider_duration_seconds": round(
                sum(item.duration_seconds for item in self.transport_attempts),
                6,
            ),
            "first_token_seconds": None,
            "first_token_unavailable_reason": (
                "provider_client_uses_non_streaming_chat_completions"
                if self.transport_attempts
                else "provider_not_invoked"
            ),
            "transport_attempts": [
                item.to_payload() for item in self.transport_attempts
            ],
        }


@dataclass(frozen=True)
class _ContainerContract:
    container_ref: str
    scope_ref: str
    materials: tuple[AnnotatedTeachingMaterial, ...]
    material_contexts: tuple[str, ...]
    authority: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _ScopeContract:
    scope: AnnotatedTeachingScope
    scope_container: _ContainerContract
    goal_containers: tuple[_ContainerContract, ...]


@dataclass(frozen=True)
class _ParsedJSONResponse:
    payload: Mapping[str, Any]
    syntax_repaired: bool
    repaired_text: str | None = None
    appended_suffix: str = ""
    removed_suffix: str = ""


class LessonScopeContentValidator:
    """Validate one B3 response and atomically fill invalid Scope bodies."""

    def __init__(
        self,
        *,
        plan: AnnotatedTeachingPlan,
        authority: Mapping[str, Any],
    ) -> None:
        self.plan = plan
        self.authority = authority
        self._contracts = _scope_contracts(plan, authority)
        self._expected_scopes = tuple(item.scope.scope_ref for item in self._contracts)
        self._fallback = build_deterministic_scope_content(plan)
        self._allowed_objects = _student_object_tokens(plan.to_payload())
        self._answer_obligations = _answer_obligations(plan)
        self._verified_result_owners = _verified_result_owners(self._contracts)
        self._scope_lineage_refs = _scope_lineage_refs(plan.root_scope)
        self._verify_authority_binding()

    @property
    def deterministic_fallback(self) -> Mapping[str, Any]:
        return _json_clone(self._fallback)

    def validate_raw(self, raw_response: str) -> ScopeLessonValidationResult:
        diagnostics: list[ScopeLessonDiagnostic] = []
        try:
            parsed = _parse_json_object_with_eof_repair(raw_response)
        except Exception as exc:
            diagnostics.append(
                ScopeLessonDiagnostic(
                    code="lesson_scope_json_invalid",
                    stage="parse",
                    path="$",
                    message=str(exc),
                )
            )
            return self._whole_fallback_result(diagnostics, parsed=None)
        if parsed.syntax_repaired:
            repair_code = (
                "lesson_scope_json_trailing_closers_repaired"
                if parsed.removed_suffix
                else "lesson_scope_json_closers_repaired"
            )
            repair_message = (
                "provider response contained only redundant JSON closing "
                f"delimiters after one complete root object; removed "
                f"{parsed.removed_suffix!r}"
                if parsed.removed_suffix
                else (
                    "provider response ended with unclosed JSON containers; "
                    f"appended {parsed.appended_suffix!r}"
                )
            )
            diagnostics.append(
                ScopeLessonDiagnostic(
                    code=repair_code,
                    stage="parse",
                    path="$",
                    message=repair_message,
                    severity="warning",
                )
            )
        return self.validate_payload(
            parsed.payload,
            initial_diagnostics=diagnostics,
            syntax_repaired=parsed.syntax_repaired,
            repaired_response=parsed.repaired_text,
            appended_suffix=parsed.appended_suffix,
            removed_suffix=parsed.removed_suffix,
        )

    def validate_payload(
        self,
        payload: Mapping[str, Any],
        *,
        initial_diagnostics: Sequence[ScopeLessonDiagnostic] = (),
        syntax_repaired: bool = False,
        repaired_response: str | None = None,
        appended_suffix: str = "",
        removed_suffix: str = "",
    ) -> ScopeLessonValidationResult:
        parsed = _json_clone(payload)
        diagnostics = list(initial_diagnostics)
        if not isinstance(parsed, Mapping):
            diagnostics.append(
                ScopeLessonDiagnostic(
                    code="lesson_scope_root_invalid",
                    stage="root",
                    path="$",
                    message="response root must be an object keyed by Scope",
                )
            )
            return self._whole_fallback_result(diagnostics, parsed=parsed)
        bodies = parsed
        unknown = sorted(set(bodies) - set(self._expected_scopes))
        if unknown:
            diagnostics.append(
                ScopeLessonDiagnostic(
                    code="lesson_scope_unknown_scope",
                    stage="root",
                    path="$",
                    message=f"unknown Scope keys: {unknown}",
                )
            )
            return self._whole_fallback_result(diagnostics, parsed=parsed)

        accepted_bodies: dict[str, Any] = {}
        bound_steps: dict[str, tuple[BoundLessonStep, ...]] = {}
        scope_sources: dict[str, ScopeLessonSource] = {}
        for contract in self._contracts:
            scope_ref = contract.scope.scope_ref
            raw_body = bodies.get(scope_ref)
            if raw_body is None:
                diagnostics.append(
                    ScopeLessonDiagnostic(
                        code="lesson_scope_required_scope_missing",
                        stage="scope",
                        path=f"$[{scope_ref!r}]",
                        message="required Scope body is missing",
                        scope_ref=scope_ref,
                    )
                )
                fallback_body = self._fallback[scope_ref]
                body, scope_bound, fallback_diagnostics = self._validate_scope(
                    contract, fallback_body, fallback_mode=True
                )
                if fallback_diagnostics:
                    raise ScopeLessonConfigurationError(
                        "lesson_scope_fallback_invalid: deterministic fallback "
                        "must pass without diagnostics"
                    )
                accepted_bodies[scope_ref] = body
                bound_steps.update(scope_bound)
                scope_sources[scope_ref] = "deterministic_fallback"
                continue
            try:
                body, scope_bound, scope_diagnostics = (
                    self._validate_scope(contract, raw_body, fallback_mode=False)
                )
            except _ScopeRejected as exc:
                diagnostics.extend(exc.diagnostics)
                fallback_body = self._fallback[scope_ref]
                try:
                    body, scope_bound, fallback_diagnostics = (
                        self._validate_scope(
                            contract,
                            fallback_body,
                            fallback_mode=True,
                        )
                    )
                except _ScopeRejected as fallback_exc:
                    raise ScopeLessonConfigurationError(
                        "lesson_scope_fallback_invalid: "
                        + "; ".join(
                            item.message for item in fallback_exc.diagnostics
                        )
                    ) from fallback_exc
                if fallback_diagnostics:
                    raise ScopeLessonConfigurationError(
                        "lesson_scope_fallback_invalid: deterministic fallback "
                        "must pass without diagnostics"
                    )
                accepted_bodies[scope_ref] = body
                bound_steps.update(scope_bound)
                scope_sources[scope_ref] = "deterministic_fallback"
                continue
            diagnostics.extend(scope_diagnostics)
            accepted_bodies[scope_ref] = body
            bound_steps.update(scope_bound)
            scope_sources[scope_ref] = "llm"
        return ScopeLessonValidationResult(
            accepted_content=accepted_bodies,
            parsed_response=parsed,
            bound_steps=bound_steps,
            scope_sources=scope_sources,
            diagnostics=tuple(diagnostics),
            whole_fallback=False,
            syntax_repaired=syntax_repaired,
            repaired_response=repaired_response,
            appended_suffix=appended_suffix,
            removed_suffix=removed_suffix,
        )

    def fallback_for_transport(
        self,
        diagnostic: ScopeLessonDiagnostic,
    ) -> ScopeLessonValidationResult:
        return self._whole_fallback_result([diagnostic], parsed=None)

    def _whole_fallback_result(
        self,
        diagnostics: Sequence[ScopeLessonDiagnostic],
        *,
        parsed: Mapping[str, Any] | None,
    ) -> ScopeLessonValidationResult:
        accepted_bodies: dict[str, Any] = {}
        bound_steps: dict[str, tuple[BoundLessonStep, ...]] = {}
        for contract in self._contracts:
            scope_ref = contract.scope.scope_ref
            body = self._fallback[scope_ref]
            try:
                accepted, scope_bound, scope_diagnostics = (
                    self._validate_scope(contract, body, fallback_mode=True)
                )
            except _ScopeRejected as exc:
                raise ScopeLessonConfigurationError(
                    "lesson_scope_fallback_invalid: "
                    + "; ".join(item.message for item in exc.diagnostics)
                ) from exc
            if scope_diagnostics:
                raise ScopeLessonConfigurationError(
                    "lesson_scope_fallback_invalid: deterministic fallback "
                    "must pass without diagnostics"
                )
            accepted_bodies[scope_ref] = accepted
            bound_steps.update(scope_bound)
        return ScopeLessonValidationResult(
            accepted_content=accepted_bodies,
            parsed_response=parsed,
            bound_steps=bound_steps,
            scope_sources={
                scope_ref: "deterministic_fallback"
                for scope_ref in self._expected_scopes
            },
            diagnostics=tuple(diagnostics),
            whole_fallback=True,
        )

    def _validate_scope(
        self,
        contract: _ScopeContract,
        raw_body: Any,
        *,
        fallback_mode: bool,
    ) -> tuple[
        Mapping[str, Any],
        Mapping[str, tuple[BoundLessonStep, ...]],
        tuple[ScopeLessonDiagnostic, ...],
    ]:
        scope_ref = contract.scope.scope_ref
        path = f"$[{scope_ref!r}]"
        errors: list[ScopeLessonDiagnostic] = []
        warnings: list[ScopeLessonDiagnostic] = []
        if not isinstance(raw_body, Mapping):
            raise _ScopeRejected(
                (_diag("lesson_scope_body_invalid", "scope", path, "Scope body must be an object", scope_ref),)
            )
        expected_fields: set[str] = set()
        if contract.scope_container.materials:
            expected_fields.add("steps")
        if contract.goal_containers:
            expected_fields.add("goals")
        normalized_raw_body = dict(raw_body)
        if not fallback_mode:
            ignorable_empty_fields = {
                "steps": isinstance(normalized_raw_body.get("steps"), list)
                and not normalized_raw_body.get("steps"),
                "goals": isinstance(normalized_raw_body.get("goals"), Mapping)
                and not normalized_raw_body.get("goals"),
            }
            for field, is_empty in ignorable_empty_fields.items():
                if (
                    field not in expected_fields
                    and field in normalized_raw_body
                    and is_empty
                ):
                    normalized_raw_body.pop(field)
                    warnings.append(
                        _diag(
                            "lesson_scope_empty_container_field_ignored",
                            "scope",
                            f"{path}.{field}",
                            f"ignored empty inapplicable Scope field {field!r}",
                            scope_ref,
                            severity="warning",
                        )
                    )
        if set(normalized_raw_body) != expected_fields:
            raise _ScopeRejected(
                (_diag("lesson_scope_body_fields_invalid", "scope", path, f"Scope body fields must be exactly {sorted(expected_fields)}", scope_ref),)
            )
        raw_goals = normalized_raw_body.get("goals", {})
        expected_goals = tuple(
            item.container_ref.removeprefix("goal:")
            for item in contract.goal_containers
        )
        if not isinstance(raw_goals, Mapping) or set(raw_goals) != set(expected_goals):
            raise _ScopeRejected(
                (
                    _diag(
                        "lesson_scope_goal_keys_invalid",
                        "scope",
                        f"{path}.goals",
                        f"Goal keys must be exactly {list(expected_goals)}",
                        scope_ref,
                    ),
                )
            )

        body: dict[str, Any] = {}
        bound: dict[str, tuple[BoundLessonStep, ...]] = {}
        try:
            if contract.scope_container.materials:
                steps, bound_scope, step_warnings = self._validate_container_steps(
                    contract.scope_container,
                    normalized_raw_body.get("steps"),
                    path=f"{path}.steps",
                    fallback_mode=fallback_mode,
                )
                body["steps"] = steps
                bound[contract.scope_container.container_ref] = bound_scope
                warnings.extend(step_warnings)
            if contract.goal_containers:
                body["goals"] = {}
            for goal_contract in contract.goal_containers:
                goal_ref = goal_contract.container_ref.removeprefix("goal:")
                raw_goal = raw_goals[goal_ref]
                goal_path = f"{path}.goals[{goal_ref!r}]"
                if not isinstance(raw_goal, list):
                    errors.append(
                        _diag(
                            "lesson_scope_goal_body_invalid",
                            "scope",
                            goal_path,
                            "Goal body must be a Lesson Step array",
                            scope_ref,
                        )
                    )
                    continue
                goal_steps, bound_goal, goal_warnings = (
                    self._validate_container_steps(
                        goal_contract,
                        raw_goal,
                        path=goal_path,
                        fallback_mode=fallback_mode,
                    )
                )
                body["goals"][goal_ref] = goal_steps
                bound[goal_contract.container_ref] = bound_goal
                warnings.extend(goal_warnings)
        except _ScopeRejected as exc:
            errors.extend(exc.diagnostics)
        if errors:
            raise _ScopeRejected(tuple(errors))

        authority_errors = self._scope_authority_errors(contract, bound)
        if authority_errors:
            raise _ScopeRejected(authority_errors)
        return body, bound, tuple(warnings)

    def _validate_container_steps(
        self,
        contract: _ContainerContract,
        raw_steps: Any,
        *,
        path: str,
        fallback_mode: bool,
    ) -> tuple[
        list[dict[str, Any]],
        tuple[BoundLessonStep, ...],
        tuple[ScopeLessonDiagnostic, ...],
    ]:
        scope_ref = contract.scope_ref
        if not isinstance(raw_steps, list):
            raise _ScopeRejected(
                (_diag("lesson_scope_steps_invalid", "scope", path, "steps must be an array", scope_ref),)
            )
        if not contract.materials and raw_steps:
            raise _ScopeRejected(
                (_diag("lesson_scope_empty_container_has_steps", "coverage", path, "container has no teaching materials", scope_ref),)
            )
        accepted_rows: list[tuple[int, dict[str, Any], BoundLessonStep]] = []
        consumed_positions: list[int] = []
        warnings: list[ScopeLessonDiagnostic] = []
        next_position = 0
        for index, raw_step in enumerate(raw_steps):
            step_path = f"{path}[{index}]"
            normalized, teaching_step_refs = _validate_step_shape(
                raw_step,
                path=step_path,
                scope_ref=scope_ref,
            )
            positions = tuple(
                int(teaching_step_ref[1:]) - 1
                for teaching_step_ref in teaching_step_refs
            )
            if any(position >= len(contract.materials) for position in positions):
                raise _ScopeRejected(
                    (
                        _diag(
                            "lesson_scope_source_steps_overflow",
                            "coverage",
                            f"{step_path}.source_steps",
                            (
                                "source_steps contains a position past "
                                f"{len(contract.materials)} available materials"
                            ),
                            scope_ref,
                        ),
                    )
                )
            expected_refs = tuple(
                _teaching_step_ref(position)
                for position in range(
                    positions[0],
                    positions[0] + len(positions),
                )
            )
            if teaching_step_refs != expected_refs:
                raise _ScopeRejected(
                    (
                        _diag(
                            "lesson_scope_source_steps_order_invalid",
                            "coverage",
                            f"{step_path}.source_steps",
                            (
                                "source_steps must be the next adjacent teaching "
                                f"steps in order; expected {list(expected_refs)}, "
                            f"observed {list(teaching_step_refs)}"
                        ),
                        scope_ref,
                        ),
                    )
                )
            if positions[0] < next_position:
                raise _ScopeRejected(
                    (
                        _diag(
                            "lesson_scope_source_steps_order_invalid",
                            "coverage",
                            f"{step_path}.source_steps",
                            (
                                "source_steps must be strictly ordered and "
                                "must not overlap an earlier Lesson Step"
                            ),
                            scope_ref,
                        ),
                    )
                )
            independent_refs = tuple(
                _teaching_step_ref(position)
                for position in positions
                if contract.authority[position].get(
                    "requires_independent_lesson_step"
                )
                is True
            )
            if len(positions) > 1 and independent_refs and not fallback_mode:
                # The row's prose cannot be split safely: its sentences no
                # longer have an authoritative one-to-one relationship with
                # the covered materials.  Replace only this row with the
                # complete deterministic material bodies and preserve every
                # other valid LLM row in the container.
                for position in positions:
                    teaching_step_ref = _teaching_step_ref(position)
                    fallback_raw = _fallback_step(
                        contract.materials[position],
                        teaching_step_ref=teaching_step_ref,
                    )
                    fallback_normalized, fallback_refs = _validate_step_shape(
                        fallback_raw,
                        path=(
                            f"{step_path}[deterministic:{teaching_step_ref}]"
                        ),
                        scope_ref=scope_ref,
                    )
                    fallback_bound = self._bind_container_step(
                        contract,
                        normalized=fallback_normalized,
                        teaching_step_refs=fallback_refs,
                        positions=(position,),
                        path=(
                            f"{step_path}[deterministic:{teaching_step_ref}]"
                        ),
                    )
                    accepted_rows.append(
                        (
                            position,
                            fallback_bound.content_payload(),
                            fallback_bound,
                        )
                    )
                consumed_positions.extend(positions)
                next_position = positions[-1] + 1
                warnings.append(
                    ScopeLessonDiagnostic(
                        code=(
                            "lesson_scope_independent_material_merge_repaired"
                        ),
                        stage="coverage",
                        path=f"{step_path}.source_steps",
                        message=(
                            f"{contract.container_ref} merged "
                            f"{list(teaching_step_refs)} across independent "
                            f"teaching material(s) {list(independent_refs)}; "
                            "replaced only that row with one deterministic "
                            "Lesson Step per covered material"
                        ),
                        scope_ref=scope_ref,
                        severity="warning",
                    )
                )
                continue
            bound_step = self._bind_container_step(
                contract,
                normalized=normalized,
                teaching_step_refs=teaching_step_refs,
                positions=positions,
                path=step_path,
            )
            accepted_rows.append(
                (positions[0], bound_step.content_payload(), bound_step)
            )
            consumed_positions.extend(positions)
            next_position = positions[-1] + 1

        missing_positions = tuple(
            position
            for position in range(len(contract.materials))
            if position not in set(consumed_positions)
        )
        if missing_positions:
            can_complete_one = (
                not fallback_mode
                and bool(raw_steps)
                and len(missing_positions) == 1
            )
            if can_complete_one:
                missing_position = missing_positions[0]
                missing_ref = _teaching_step_ref(missing_position)
                fallback_raw = _fallback_step(
                    contract.materials[missing_position],
                    teaching_step_ref=missing_ref,
                )
                normalized, teaching_step_refs = _validate_step_shape(
                    fallback_raw,
                    path=f"{path}[deterministic:{missing_ref}]",
                    scope_ref=scope_ref,
                )
                completed_step = self._bind_container_step(
                    contract,
                    normalized=normalized,
                    teaching_step_refs=teaching_step_refs,
                    positions=(missing_position,),
                    path=f"{path}[deterministic:{missing_ref}]",
                )
                accepted_rows.append(
                    (
                        missing_position,
                        completed_step.content_payload(),
                        completed_step,
                    )
                )
                warnings.append(
                    ScopeLessonDiagnostic(
                        code="lesson_scope_single_source_step_completed",
                        stage="coverage",
                        path=path,
                        message=(
                            f"{contract.container_ref} omitted {missing_ref}; "
                            "inserted its deterministic teaching material at "
                            f"Canonical position {missing_position + 1}"
                        ),
                        scope_ref=scope_ref,
                        severity="warning",
                    )
                )
            else:
                missing_refs = [
                    _teaching_step_ref(position)
                    for position in missing_positions
                ]
                raise _ScopeRejected(
                    (
                        _diag(
                            "lesson_scope_source_steps_coverage_incomplete",
                            "coverage",
                            path,
                            (
                                f"used {len(consumed_positions)} of "
                                f"{len(contract.materials)} teaching step refs; "
                                f"missing {missing_refs}"
                            ),
                            scope_ref,
                        ),
                    )
                )

        accepted_rows.sort(key=lambda item: item[0])
        return (
            [item[1] for item in accepted_rows],
            tuple(item[2] for item in accepted_rows),
            tuple(warnings),
        )

    def _bind_container_step(
        self,
        contract: _ContainerContract,
        *,
        normalized: Mapping[str, Any],
        teaching_step_refs: tuple[str, ...],
        positions: tuple[int, ...],
        path: str,
    ) -> BoundLessonStep:
        records = tuple(contract.authority[position] for position in positions)
        bound_step = BoundLessonStep(
            container_ref=contract.container_ref,
            material_positions=positions,
            teaching_step_refs=teaching_step_refs,
            source_step_ids=_dedupe(
                str(item["source_step_id"]) for item in records
            ),
            capability_ids=_dedupe(
                str(item["capability_id"]) for item in records
            ),
            unit_keys=tuple(str(item["unit_key"]) for item in records),
            evidence_refs=_dedupe(
                str(ref)
                for item in records
                for ref in item.get("evidence_refs", ())
            ),
            title=str(normalized["title"]),
            nav_title=str(normalized["nav_title"]),
            goal=str(normalized["goal"]),
            derive=tuple(
                (str(item[0]), str(item[1]))
                for item in normalized["derive"]
            ),
            box=_deterministic_conclusions(
                contract.materials[position] for position in positions
            ),
        )
        safety = self._text_authority_errors(
            bound_step,
            path=path,
            scope_ref=contract.scope_ref,
        )
        if safety:
            raise _ScopeRejected(
                safety
            )
        return bound_step

    def _text_authority_errors(
        self,
        step: BoundLessonStep,
        *,
        path: str,
        scope_ref: str,
    ) -> tuple[ScopeLessonDiagnostic, ...]:
        text_payload = [
            step.title,
            step.nav_title,
            step.goal,
            *(part for row in step.derive for part in row),
            *step.box,
        ]
        serialized = json.dumps(text_payload, ensure_ascii=False)
        errors: list[ScopeLessonDiagnostic] = []
        hits = find_forbidden_llm_tokens(text_payload)
        if (
            hits
            or contains_private_path_projection_marker(text_payload)
            or _LONG_HEX_PATTERN.search(serialized)
        ):
            errors.append(
                _diag(
                    "lesson_scope_private_identity_leak",
                    "authority",
                    path,
                    f"student text contains internal identity: {hits}",
                    scope_ref,
                )
            )
        if _HTML_OR_CODE_PATTERN.search(serialized):
            errors.append(
                _diag(
                    "lesson_scope_markup_forbidden",
                    "authority",
                    path,
                    "student text must not contain HTML, script, or code fences",
                    scope_ref,
                )
            )
        internal_math_hits = find_internal_math_tokens(text_payload)
        if internal_math_hits:
            errors.append(
                _diag(
                    "lesson_scope_internal_math_syntax",
                    "authority",
                    path,
                    "student text contains internal math syntax: "
                    f"{internal_math_hits}",
                    scope_ref,
                )
            )
        unexpected = sorted(
            token
            for token in _student_object_tokens(text_payload)
            if token not in self._allowed_objects
        )
        if unexpected:
            errors.append(
                _diag(
                    "lesson_scope_unexpected_object",
                    "authority",
                    path,
                    f"student text introduces unknown objects: {unexpected}",
                    scope_ref,
                )
            )
        return tuple(errors)

    def _scope_authority_errors(
        self,
        contract: _ScopeContract,
        bound: Mapping[str, tuple[BoundLessonStep, ...]],
    ) -> tuple[ScopeLessonDiagnostic, ...]:
        errors: list[ScopeLessonDiagnostic] = []
        for container in (contract.scope_container, *contract.goal_containers):
            steps = bound.get(container.container_ref, ())
            errors.extend(_future_result_errors(container, steps))
            errors.extend(
                _cross_container_result_errors(
                    container,
                    steps,
                    verified_result_owners=self._verified_result_owners,
                    scope_lineage_refs=self._scope_lineage_refs,
                )
            )
        errors.extend(self._answer_coverage_errors(contract, bound))
        return tuple(errors)

    def _answer_coverage_errors(
        self,
        contract: _ScopeContract,
        bound: Mapping[str, tuple[BoundLessonStep, ...]],
    ) -> tuple[ScopeLessonDiagnostic, ...]:
        errors: list[ScopeLessonDiagnostic] = []
        all_steps = [
            step
            for items in bound.values()
            for step in items
        ]
        local_producers = {
            producer
            for step in all_steps
            for producer in step.source_step_ids
            if producer in self._answer_obligations
        }
        for producer in sorted(local_producers):
            candidates = [
                item for item in all_steps if producer in item.source_step_ids
            ]
            target = candidates[-1]
            for goal_ref, display in self._answer_obligations[producer]:
                if not display or not answer_display_is_covered(
                    display,
                    "\n".join(target.box),
                ):
                    errors.append(
                        _diag(
                            "lesson_scope_verified_answer_missing",
                            "authority",
                            f"$[{contract.scope.scope_ref!r}]",
                            (
                                f"answer_from producer {producer!r} for Goal "
                                f"{goal_ref!r} must expose verified answer "
                                f"{display!r} in its final box"
                            ),
                            contract.scope.scope_ref,
                        )
                    )
        return tuple(errors)

    def _verify_authority_binding(self) -> None:
        plan_hash = _stable_hash(self.plan.to_payload())
        if self.authority.get("annotated_plan_hash") != plan_hash:
            raise ScopeLessonConfigurationError(
                "lesson_scope_authority_drift: annotated Plan hash mismatch"
            )
        raw_independent = self.authority.get("independent_step_refs")
        if not isinstance(raw_independent, Mapping):
            raise ScopeLessonConfigurationError(
                "lesson_scope_authority_drift: independent_step_refs must be an object"
            )
        raw_containers = self.authority.get("containers")
        if not isinstance(raw_containers, Mapping) or set(raw_independent) != set(
            raw_containers
        ):
            raise ScopeLessonConfigurationError(
                "lesson_scope_authority_drift: independent_step_refs container keys "
                "do not match the teaching material containers"
            )
        for contract in self._contracts:
            for container in (
                contract.scope_container,
                *contract.goal_containers,
            ):
                if not (
                    len(container.materials)
                    == len(container.material_contexts)
                    == len(container.authority)
                ):
                    raise ScopeLessonConfigurationError(
                        "lesson_scope_authority_drift: material/context/authority count "
                        f"mismatch for {container.container_ref}"
                    )
                for position, (material, record) in enumerate(
                    zip(container.materials, container.authority, strict=True)
                ):
                    if (
                        record.get("position") != position
                        or record.get("teaching_step_ref")
                        != _teaching_step_ref(position)
                        or record.get("suggestion_hash")
                        != _stable_hash(material.to_payload())
                    ):
                        raise ScopeLessonConfigurationError(
                            "lesson_scope_authority_drift: material signature "
                            f"mismatch for {container.container_ref}[{position}]"
                        )
                    if not isinstance(
                        record.get("requires_independent_lesson_step"), bool
                    ):
                        raise ScopeLessonConfigurationError(
                            "lesson_scope_authority_drift: independent boundary must "
                            f"be boolean for {container.container_ref}[{position}]"
                        )
                expected_independent = [
                    str(record["teaching_step_ref"])
                    for record in container.authority
                    if record["requires_independent_lesson_step"]
                ]
                observed_independent = raw_independent.get(
                    container.container_ref,
                    [],
                )
                if (
                    not isinstance(observed_independent, list)
                    or observed_independent != expected_independent
                ):
                    raise ScopeLessonConfigurationError(
                        "lesson_scope_authority_drift: independent boundary refs "
                        f"mismatch for {container.container_ref}"
                    )


class ScopeLessonAuthoringService:
    """Make one semantic Lesson call with bounded transport-only retry."""

    def __init__(
        self,
        *,
        client: LLMPlannerClient,
        max_transport_attempts: int = 2,
        thinking_effort: Literal["disabled", "low"] = "disabled",
        retry_backoff_seconds: float = 0.5,
        sleep_fn: Callable[[float], None] = sleep,
        reviewed_prompt_hash: str | None = None,
    ) -> None:
        if max_transport_attempts < 1:
            raise ValueError("max_transport_attempts must be positive")
        if thinking_effort not in {"disabled", "low"}:
            raise ValueError("thinking_effort must be 'disabled' or 'low'")
        self.client = client
        self.max_transport_attempts = int(max_transport_attempts)
        self.thinking_effort = thinking_effort
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.sleep_fn = sleep_fn
        self.reviewed_prompt_hash = reviewed_prompt_hash

    def generate(
        self,
        snapshot: ExplanationSnapshot,
    ) -> ScopeLessonGenerationResult:
        projection = AnnotatedTeachingPlanProjector().project(snapshot)
        output_schema = lesson_scope_content_schema(projection.plan)
        prompt = render_annotated_teaching_prompt(
            projection.plan,
            authority=projection.authority,
            output_schema=output_schema,
        )
        audit = build_projection_audit(
            projection,
            prompt=prompt,
            output_schema=output_schema,
        )
        prompt_hash = str(audit["hashes"]["prompt"])
        if (
            self.reviewed_prompt_hash is not None
            and self.reviewed_prompt_hash != prompt_hash
        ):
            raise ScopeLessonConfigurationError(
                "lesson_scope_reviewed_prompt_drift: B3 request no longer matches "
                "the human-reviewed B2 Prompt"
            )
        validator = LessonScopeContentValidator(
            plan=projection.plan,
            authority=projection.authority,
        )
        request_payload = {
            "messages": prompt.messages,
            "planner_attempt": 1,
            "lesson_protocol": LESSON_SCOPE_CONTENT_CONTRACT,
            "thinking_effort": self.thinking_effort,
            "reasoning_only_empty_response_retry": False,
        }
        request_hash = _stable_hash(request_payload["messages"])
        if request_hash != prompt_hash:
            raise ScopeLessonConfigurationError(
                "lesson_scope_prompt_hash_drift: provider messages differ from audit"
            )

        attempts: list[ScopeLessonTransportAttempt] = []
        raw_response = ""
        terminal_error: Exception | None = None
        for attempt_number in range(1, self.max_transport_attempts + 1):
            started = perf_counter()
            error: Exception | None = None
            try:
                raw_response = self.client.complete(request_payload)
            except Exception as exc:  # classified immediately below
                error = exc
                terminal_error = exc
            duration = round(perf_counter() - started, 6)
            retryable = bool(error is not None and _is_retryable_transport_error(error))
            attempts.append(
                _transport_attempt(
                    self.client,
                    attempt_number=attempt_number,
                    duration_seconds=duration,
                    prompt_hash=prompt_hash,
                    raw_response=raw_response,
                    error=error,
                    retryable=retryable,
                )
            )
            if error is None:
                terminal_error = None
                break
            if not retryable or attempt_number >= self.max_transport_attempts:
                break
            self.sleep_fn(self.retry_backoff_seconds * (2 ** (attempt_number - 1)))

        if terminal_error is None:
            validation = validator.validate_raw(raw_response)
        else:
            validation = validator.fallback_for_transport(
                ScopeLessonDiagnostic(
                    code=(
                        "lesson_scope_transport_retry_exhausted"
                        if _is_retryable_transport_error(terminal_error)
                        else "lesson_scope_transport_nonretryable"
                    ),
                    stage="transport",
                    path="$",
                    message=f"{terminal_error.__class__.__name__}: {terminal_error}",
                )
            )
        return ScopeLessonGenerationResult(
            projection=projection,
            output_schema=output_schema,
            prompt=prompt,
            projection_audit=audit,
            raw_response=raw_response,
            validation=validation,
            deterministic_fallback=validator.deterministic_fallback,
            transport_attempts=tuple(attempts),
        )


class _ScopeRejected(ValueError):
    def __init__(self, diagnostics: tuple[ScopeLessonDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


def build_deterministic_scope_content(
    plan: AnnotatedTeachingPlan,
) -> dict[str, Any]:
    """Build the complete B3 fallback using only B2 public materials."""

    bodies: dict[str, Any] = {}
    for scope in _iter_scopes(plan.root_scope):
        scope_materials = tuple(
            material
            for step in scope.steps
            for material in step.teaching_materials
        )
        goal_materials = {
            goal.goal_ref: tuple(
                material
                for step in goal.steps
                for material in step.teaching_materials
            )
            for goal in scope.goals
        }
        if not scope_materials and not any(goal_materials.values()):
            continue
        body: dict[str, Any] = {}
        if scope_materials:
            body["steps"] = _fallback_steps(scope_materials)
        nonempty_goals = {
            goal.goal_ref: _fallback_steps(goal_materials[goal.goal_ref])
            for goal in scope.goals
            if goal_materials[goal.goal_ref]
        }
        if nonempty_goals:
            body["goals"] = nonempty_goals
        bodies[scope.scope_ref] = body
    return bodies


def evaluate_scope_lesson_content(
    result: ScopeLessonValidationResult,
    *,
    problem_id: str,
    rubric: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate B3 content without converting it into the old flat LessonIR."""

    from shuxueshuo_server.solver.lesson_authoring_support import (
        evaluate_teaching_rows,
        validate_teaching_rubric,
    )

    rubric_payload = validate_teaching_rubric(rubric)
    if rubric_payload["problem_id"] != problem_id:
        raise ScopeLessonConfigurationError(
            "lesson_scope_evaluation_problem_mismatch"
        )
    rows = [
        {
            "id": f"{container_ref}:{index}",
            "source_step_ids": list(step.source_step_ids),
            "title": step.title,
            "nav_title": step.nav_title,
            "goal": step.goal,
            "derive": [list(item) for item in step.derive],
            "box": list(step.box),
        }
        for container_ref, steps in result.bound_steps.items()
        for index, step in enumerate(steps)
    ]
    teaching = evaluate_teaching_rows(
        rows,
        rubric_payload,
        problem_id=problem_id,
    )
    repeated_lines = _repeated_student_lines(rows)
    answer_diagnostics = [
        item.to_payload()
        for item in result.diagnostics
        if item.code == "lesson_scope_verified_answer_missing"
    ]
    contract_diagnostics = [
        item.to_payload()
        for item in result.diagnostics
        if item.stage in {"parse", "root", "scope", "coverage", "text"}
    ]
    authority_diagnostics = [
        item.to_payload()
        for item in result.diagnostics
        if item.stage == "authority"
    ]
    unexpected = sorted(
        {
            token
            for item in result.diagnostics
            if item.code == "lesson_scope_unexpected_object"
            for token in _objects_from_diagnostic(item.message)
        }
    )
    future = [
        item.to_payload()
        for item in result.diagnostics
        if item.code
        in {
            "lesson_scope_future_result_leak",
            "lesson_scope_cross_container_result_leak",
        }
    ]
    return {
        "schema_version": SCOPE_LESSON_EVALUATION_CONTRACT,
        "problem_id": problem_id,
        "contract": {
            "pass": result.contract_pass,
            "diagnostics": contract_diagnostics,
        },
        "authority": {
            "pass": result.authority_pass,
            "diagnostics": authority_diagnostics,
            "unexpected_objects": unexpected,
            "future_result_leaks": future,
            "answer_coverage": {
                "pass": not answer_diagnostics,
                "diagnostics": answer_diagnostics,
            },
        },
        "teaching_quality": {
            "required_points": {
                "covered": teaching["covered"],
                "missing": teaching["missing"],
                "evidence_by_point": teaching["evidence_by_point"],
            },
            "coverage_rate": teaching["coverage_rate"],
            "presentation_review": {
                "derivation_order": (
                    "pass" if result.contract_pass else "review"
                ),
                "box_completeness": (
                    "pass" if not answer_diagnostics else "review"
                ),
                "conciseness": "pass" if not repeated_lines else "review",
                "repeated_lines": repeated_lines,
            },
        },
        "fallback_used": result.fallback_used,
        "syntax_repaired": result.syntax_repaired,
        "source_step_completion_repaired": (
            result.source_step_completion_repaired
        ),
    }


def _scope_contracts(
    plan: AnnotatedTeachingPlan,
    authority: Mapping[str, Any],
) -> tuple[_ScopeContract, ...]:
    raw_containers = authority.get("containers")
    if not isinstance(raw_containers, Mapping):
        raise ScopeLessonConfigurationError(
            "lesson_scope_authority_invalid: containers must be an object"
        )
    result: list[_ScopeContract] = []
    for scope in _iter_scopes(plan.root_scope):
        scope_materials, scope_contexts = _container_material_projection(
            scope.steps
        )
        goal_contract_rows: list[_ContainerContract] = []
        for goal in scope.goals:
            goal_materials, goal_contexts = _container_material_projection(
                goal.steps
            )
            if not goal_materials:
                continue
            goal_contract_rows.append(
                _ContainerContract(
                    container_ref=f"goal:{goal.goal_ref}",
                    scope_ref=scope.scope_ref,
                    materials=goal_materials,
                    material_contexts=goal_contexts,
                    authority=_authority_records(
                        raw_containers,
                        f"goal:{goal.goal_ref}",
                    ),
                )
            )
        goal_contracts = tuple(goal_contract_rows)
        if not scope_materials and not any(item.materials for item in goal_contracts):
            continue
        result.append(
            _ScopeContract(
                scope=scope,
                scope_container=_ContainerContract(
                    container_ref=f"scope:{scope.scope_ref}",
                    scope_ref=scope.scope_ref,
                    materials=scope_materials,
                    material_contexts=scope_contexts,
                    authority=_authority_records(
                        raw_containers,
                        f"scope:{scope.scope_ref}",
                    ),
                ),
                goal_containers=goal_contracts,
            )
        )
    return tuple(result)


def _container_material_projection(
    steps: Sequence[Any],
) -> tuple[tuple[AnnotatedTeachingMaterial, ...], tuple[str, ...]]:
    """Flatten materials and retain each material's verified local context."""

    materials: list[AnnotatedTeachingMaterial] = []
    contexts: list[str] = []
    for step in steps:
        shared = {
            "inputs": _json_clone(step.inputs),
            "outputs": _json_clone(step.outputs),
            "calculations": _json_clone(step.calculations),
        }
        for material in step.teaching_materials:
            materials.append(material)
            contexts.append(
                json.dumps(
                    {**shared, "material": material.to_payload()},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
    return tuple(materials), tuple(contexts)


def _authority_records(
    containers: Mapping[str, Any],
    container_ref: str,
) -> tuple[Mapping[str, Any], ...]:
    raw = containers.get(container_ref, [])
    if not isinstance(raw, list):
        raise ScopeLessonConfigurationError(
            f"lesson_scope_authority_invalid: {container_ref} must be an array"
        )
    if any(not isinstance(item, Mapping) for item in raw):
        raise ScopeLessonConfigurationError(
            f"lesson_scope_authority_invalid: {container_ref} records must be objects"
        )
    return tuple(_json_clone(item) for item in raw)


def _validate_step_shape(
    raw: Any,
    *,
    path: str,
    scope_ref: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    expected = {
        "source_steps",
        "title",
        "nav_title",
        "goal",
        "derive",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected:
        raise _ScopeRejected(
            (_diag("lesson_scope_step_fields_invalid", "text", path, f"Lesson Step fields must be exactly {sorted(expected)}", scope_ref),)
        )
    source_steps = raw.get("source_steps")
    if (
        not isinstance(source_steps, list)
        or not source_steps
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"s[1-9][0-9]*", item) is None
            for item in source_steps
        )
        or len(set(source_steps)) != len(source_steps)
    ):
        raise _ScopeRejected(
            (
                _diag(
                    "lesson_scope_source_steps_invalid",
                    "coverage",
                    f"{path}.source_steps",
                    "source_steps must be a non-empty unique list like ['s1', 's2']",
                    scope_ref,
                ),
            )
        )
    for name, maximum in (
        ("title", _TITLE_MAX),
        ("nav_title", _NAV_TITLE_MAX),
        ("goal", _GOAL_MAX),
    ):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise _ScopeRejected(
                (_diag("lesson_scope_text_invalid", "text", f"{path}.{name}", f"{name} must contain 1..{maximum} characters", scope_ref),)
            )
    derive = raw.get("derive")
    if (
        not isinstance(derive, list)
        or not derive
        or len(derive) > _DERIVE_MAX_ITEMS
    ):
        raise _ScopeRejected(
            (_diag("lesson_scope_derive_invalid", "text", f"{path}.derive", f"derive must contain 1..{_DERIVE_MAX_ITEMS} rows", scope_ref),)
        )
    for index, item in enumerate(derive):
        if not isinstance(item, str):
            raise _ScopeRejected(
                (_diag("lesson_scope_derive_row_invalid", "text", f"{path}.derive[{index}]", "derive row must be one marker-prefixed string", scope_ref),)
            )
        marker, text = _split_derive_line(item)
        if marker not in DERIVE_MARKERS or not text or len(text) > _DERIVE_TEXT_MAX:
            raise _ScopeRejected(
                (_diag("lesson_scope_derive_row_invalid", "text", f"{path}.derive[{index}]", "derive row must start with 作/设/∵/∴/计算 plus non-empty text", scope_ref),)
            )
    normalized = {
        "source_steps": list(source_steps),
        "title": raw["title"],
        "nav_title": raw["nav_title"],
        "goal": raw["goal"],
        "derive": [list(_split_derive_line(item)) for item in derive],
    }
    return normalized, tuple(source_steps)


def _future_result_errors(
    contract: _ContainerContract,
    steps: Sequence[BoundLessonStep],
) -> tuple[ScopeLessonDiagnostic, ...]:
    errors: list[ScopeLessonDiagnostic] = []
    for step_index, step in enumerate(steps):
        end = step.material_positions[-1] if step.material_positions else -1
        prior_text = "\n".join(
            _material_student_text(material)
            for material in contract.materials[: end + 1]
        )
        step_text = _bound_step_student_text(step)
        for later_position, material in enumerate(
            contract.materials[end + 1 :],
            start=end + 1,
        ):
            for fingerprint in material.suggested_box:
                normalized = _normalize_math_text(fingerprint)
                if len(normalized) < 3:
                    continue
                if normalized in _normalize_math_text(prior_text):
                    continue
                if normalized in _normalize_math_text(step_text):
                    errors.append(
                        _diag(
                            "lesson_scope_future_result_leak",
                            "authority",
                            f"$.{contract.container_ref}.steps[{step_index}]",
                            f"text uses later material {later_position} result {fingerprint!r}",
                            contract.scope_ref,
                        )
                    )
    return tuple(errors)


def _verified_result_owners(
    contracts: Sequence[_ScopeContract],
) -> Mapping[str, tuple[tuple[str, int, str], ...]]:
    """Index exact verified conclusions by their owning teaching container."""

    mutable: dict[str, list[tuple[str, int, str]]] = {}
    for scope_contract in contracts:
        for container in (
            scope_contract.scope_container,
            *scope_contract.goal_containers,
        ):
            for position, material in enumerate(container.materials):
                for conclusion in material.suggested_box:
                    normalized = _normalize_math_text(conclusion)
                    if len(normalized) < 3:
                        continue
                    mutable.setdefault(normalized, []).append(
                        (container.container_ref, position, conclusion)
                    )
    return {
        fingerprint: tuple(owners)
        for fingerprint, owners in mutable.items()
    }


def _cross_container_result_errors(
    contract: _ContainerContract,
    steps: Sequence[BoundLessonStep],
    *,
    verified_result_owners: Mapping[
        str,
        tuple[tuple[str, int, str], ...],
    ],
    scope_lineage_refs: Mapping[str, tuple[str, ...]],
) -> tuple[ScopeLessonDiagnostic, ...]:
    """Reject exact results imported from another Scope/Goal without an input.

    The LLM sees the whole recursive teaching Plan for coherence, but it may
    only write verified results available to the current container.  A result
    from an ancestor Scope is legal because recursive Scope execution inherits
    its ancestor state. A child/sibling result such as ``P(-1,4)`` in its
    parent is not. Explicit cross-Goal inputs remain covered by the material's
    verified local context.
    """

    errors: list[ScopeLessonDiagnostic] = []
    visible_scope_owners = {
        f"scope:{scope_ref}"
        for scope_ref in scope_lineage_refs.get(contract.scope_ref, ())
    }
    for step_index, step in enumerate(steps):
        end = step.material_positions[-1] if step.material_positions else -1
        allowed_text = _normalize_math_text(
            "\n".join(contract.material_contexts[: end + 1])
        )
        observed_text = _normalize_math_text(_bound_step_student_text(step))
        for fingerprint, owners in verified_result_owners.items():
            if fingerprint in allowed_text or fingerprint not in observed_text:
                continue
            foreign = tuple(
                item for item in owners if item[0] != contract.container_ref
            )
            if not foreign:
                continue
            if any(item[0] in visible_scope_owners for item in foreign):
                continue
            owner_refs = sorted({item[0] for item in foreign})
            display = foreign[0][2]
            errors.append(
                _diag(
                    "lesson_scope_cross_container_result_leak",
                    "authority",
                    f"$.{contract.container_ref}.steps[{step_index}]",
                    (
                        f"text uses verified result {display!r} from "
                        f"another container {owner_refs} without a local input"
                    ),
                    contract.scope_ref,
                )
            )
    return tuple(errors)


def _transport_attempt(
    client: LLMPlannerClient,
    *,
    attempt_number: int,
    duration_seconds: float,
    prompt_hash: str,
    raw_response: str,
    error: Exception | None,
    retryable: bool,
) -> ScopeLessonTransportAttempt:
    provider_attempts = tuple(
        dict(item)
        for item in (getattr(client, "last_provider_attempts", ()) or ())
        if isinstance(item, Mapping)
    )
    provider_reasoning = tuple(
        {
            "provider_attempt": item.get("provider_attempt"),
            "reasoning_content": (
                ""
                if item.get("reasoning_content") is None
                else str(item.get("reasoning_content"))
            ),
        }
        for item in (getattr(client, "last_provider_reasoning", ()) or ())
        if isinstance(item, Mapping)
    )
    reasoning_available = any(
        bool(item.get("reasoning_content_available"))
        for item in provider_attempts
    )
    reasoning_chars = sum(
        int(item.get("reasoning_content_chars") or 0)
        for item in provider_attempts
    )
    return ScopeLessonTransportAttempt(
        transport_attempt=attempt_number,
        duration_seconds=duration_seconds,
        prompt_hash=prompt_hash,
        raw_response=raw_response,
        visible_response=bool(raw_response.strip()),
        error=(
            f"{error.__class__.__name__}: {error}" if error is not None else None
        ),
        retryable=retryable,
        usage=dict(getattr(client, "last_usage", None) or {}),
        provider=(
            str(getattr(client, "provider_name"))
            if getattr(client, "provider_name", None)
            else None
        ),
        request_model=(
            str(getattr(client, "model"))
            if getattr(client, "model", None)
            else None
        ),
        response_model=(
            str(getattr(client, "last_response_model"))
            if getattr(client, "last_response_model", None)
            else None
        ),
        provider_attempts=provider_attempts,
        provider_reasoning=provider_reasoning,
        reasoning_available=reasoning_available,
        reasoning_chars=reasoning_chars,
    )


def _is_retryable_transport_error(error: Exception) -> bool:
    if isinstance(error, (LLMClientConfigurationError, LLMProviderResponseError)):
        return False
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    if error.__class__.__name__ in _TRANSIENT_ERROR_NAMES:
        return True
    status = getattr(error, "status_code", None)
    return isinstance(status, int) and (status in {408, 409, 429} or status >= 500)


def _fallback_step(
    material: AnnotatedTeachingMaterial,
    *,
    teaching_step_ref: str,
) -> dict[str, Any]:
    return {
        "source_steps": [teaching_step_ref],
        "title": material.suggested_title,
        "nav_title": material.suggested_nav_title,
        "goal": material.suggested_goal,
        "derive": [
            f"{marker} {text}" for marker, text in material.suggested_derive
        ],
    }


def _fallback_steps(
    materials: Sequence[AnnotatedTeachingMaterial],
) -> list[dict[str, Any]]:
    return [
        _fallback_step(
            material,
            teaching_step_ref=_teaching_step_ref(position),
        )
        for position, material in enumerate(materials)
    ]


def _parse_json_object_with_eof_repair(raw: str) -> _ParsedJSONResponse:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("provider returned an empty response")
    if "```" in raw:
        raise ValueError("Markdown code fences are not accepted")
    text = raw.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        if exc.msg == "Extra data":
            decoder = json.JSONDecoder()
            try:
                prefix_payload, prefix_end = decoder.raw_decode(text)
            except json.JSONDecodeError as prefix_exc:
                raise ValueError(
                    "JSON has no complete root object before trailing data"
                ) from prefix_exc
            removed_suffix = text[prefix_end:].strip()
            non_whitespace_suffix = "".join(
                character
                for character in removed_suffix
                if not character.isspace()
            )
            if (
                isinstance(prefix_payload, dict)
                and removed_suffix
                and len(non_whitespace_suffix) <= 8
                and set(non_whitespace_suffix) <= {"}", "]"}
            ):
                repaired = text[:prefix_end].rstrip()
                return _ParsedJSONResponse(
                    payload=prefix_payload,
                    syntax_repaired=True,
                    repaired_text=repaired,
                    removed_suffix=removed_suffix,
                )
            raise ValueError(
                "JSON trailing data is not solely redundant closing delimiters"
            ) from exc
        if exc.pos != len(text):
            raise ValueError(
                "JSON syntax error is not an EOF-only missing closer"
            ) from exc
        suffix = _missing_json_closer_suffix(text)
        if not suffix:
            raise ValueError("JSON has no safely repairable missing closer") from exc
        repaired = text + suffix
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError as repaired_exc:
            raise ValueError(
                "appending missing EOF closers did not produce valid JSON"
            ) from repaired_exc
        if not isinstance(payload, dict):
            raise ValueError("Lesson response must be a JSON object")
        return _ParsedJSONResponse(
            payload=payload,
            syntax_repaired=True,
            repaired_text=repaired,
            appended_suffix=suffix,
        )
    if not isinstance(payload, dict):
        raise ValueError("Lesson response must be a JSON object")
    return _ParsedJSONResponse(payload=payload, syntax_repaired=False)


def _missing_json_closer_suffix(text: str) -> str:
    stack: list[str] = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    closers = {"{": "}", "[": "]"}
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in closers:
            stack.append(character)
        elif character in pairs:
            if not stack or stack[-1] != pairs[character]:
                raise ValueError("JSON contains a mismatched closing delimiter")
            stack.pop()
    if in_string or escaped:
        raise ValueError("JSON ends inside a string or escape sequence")
    if not stack:
        return ""
    if text[-1] in {",", ":"}:
        raise ValueError("JSON ends after an incomplete member or value")
    return "".join(closers[item] for item in reversed(stack))


def _parse_strict_json_object(raw: str) -> dict[str, Any]:
    """Compatibility helper returning the safely parsed/repaired object."""

    return dict(_parse_json_object_with_eof_repair(raw).payload)


def _split_derive_line(value: str) -> tuple[str, str]:
    stripped = value.strip()
    if stripped.startswith(("解方程", "解不等式", "解得")):
        return "计算", stripped
    marker, separator, text = stripped.partition(" ")
    if not separator:
        return "", ""
    return marker, text.strip()


def _deterministic_conclusions(
    materials: Iterable[AnnotatedTeachingMaterial],
) -> tuple[str, ...]:
    result: list[str] = []
    for material in materials:
        for conclusion in material.suggested_box:
            value = str(conclusion).strip()
            if value and value not in result:
                result.append(value)
    return tuple(result)


def _student_object_tokens(value: Any) -> set[str]:
    text = json.dumps(value, ensure_ascii=False)
    return {
        _normalize_prime_token(item.group(0))
        for item in _UPPER_OBJECT_PATTERN.finditer(text)
    }


def _normalize_prime_token(value: str) -> str:
    return value.replace("′", "'").replace("’", "'")


def _normalize_math_text(value: str) -> str:
    text = str(value).lower()
    for source, target in (
        ("−", "-"),
        ("－", "-"),
        ("—", "-"),
        ("＋", "+"),
        ("＝", "="),
        ("（", "("),
        ("）", ")"),
        ("，", ","),
        ("｜", "|"),
        ("′", "'"),
        ("’", "'"),
        ("‘", "'"),
        ("`", "'"),
    ):
        text = text.replace(source, target)
    removable = " \t\r\n,。；;：:、"
    return text.translate(str.maketrans("", "", removable))


def answer_display_is_covered(display: str, student_box: str) -> bool:
    """Return whether student text contains the verified answer losslessly.

    This is shared by the B3 authority validator and the B4 recursive
    assembler.  Keeping one matcher prevents an accepted Scope body from
    acquiring a weaker answer check when it is committed to LessonIR.
    """

    expected = _normalize_math_text(display)
    observed = _normalize_math_text(student_box)
    if expected in observed:
        return True
    # Point and PointList answers are commonly rendered without a point label
    # in the verified answer map but with the problem's label in student text.
    # Compare every coordinate tuple instead of requiring one exact sentence.
    coordinate_tuples = re.findall(r"\([^()]+\)", expected)
    return bool(coordinate_tuples) and all(item in observed for item in coordinate_tuples)


def _material_student_text(material: AnnotatedTeachingMaterial) -> str:
    return "\n".join(
        (
            material.suggested_title,
            material.suggested_nav_title,
            material.suggested_goal,
            *(part for row in material.suggested_derive for part in row),
            *material.suggested_box,
        )
    )


def _bound_step_student_text(step: BoundLessonStep) -> str:
    return "\n".join(
        (
            step.title,
            step.nav_title,
            step.goal,
            *(part for row in step.derive for part in row),
            *step.box,
        )
    )


def _repeated_student_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    originals: dict[str, str] = {}
    for row in rows:
        for derive in row.get("derive", ()):
            if not isinstance(derive, Sequence) or isinstance(derive, str | bytes):
                continue
            if len(derive) != 2:
                continue
            text = str(derive[1])
            normalized = _normalize_math_text(text)
            if len(normalized) < 4:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1
            originals.setdefault(normalized, text)
    return sorted(originals[key] for key, count in counts.items() if count > 1)


def _objects_from_diagnostic(message: str) -> tuple[str, ...]:
    marker = "unknown objects:"
    if marker not in message:
        return ()
    return tuple(sorted(_student_object_tokens(message.split(marker, 1)[1])))


def _iter_scopes(root: AnnotatedTeachingScope) -> tuple[AnnotatedTeachingScope, ...]:
    result: list[AnnotatedTeachingScope] = []

    def visit(scope: AnnotatedTeachingScope) -> None:
        result.append(scope)
        for child in scope.children:
            visit(child)

    visit(root)
    return tuple(result)


def _scope_lineage_refs(
    root: AnnotatedTeachingScope,
) -> Mapping[str, tuple[str, ...]]:
    """Return each Scope's visible ancestor chain, including itself."""

    result: dict[str, tuple[str, ...]] = {}

    def visit(scope: AnnotatedTeachingScope, ancestors: tuple[str, ...]) -> None:
        lineage = (*ancestors, scope.scope_ref)
        result[scope.scope_ref] = lineage
        for child in scope.children:
            visit(child, lineage)

    visit(root, ())
    return result


def _answer_obligations(
    plan: AnnotatedTeachingPlan,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Index every verified Goal answer by its actual producer Step.

    A child Goal may deliberately publish an answer produced by a Step owned by
    an ancestor Scope.  Indexing the complete recursive tree ensures the box
    obligation follows the producer instead of being lost at the Goal boundary.
    """

    mutable: dict[str, list[tuple[str, str]]] = {}
    for scope in _iter_scopes(plan.root_scope):
        for goal in scope.goals:
            producer = str(goal.answer_from.get("step_id") or "")
            answer = plan.answers.get(goal.goal_ref)
            if not producer or not isinstance(answer, Mapping):
                raise ScopeLessonConfigurationError(
                    "lesson_scope_answer_authority_invalid: "
                    f"Goal {goal.goal_ref!r} has no verified producer answer"
                )
            display = str(answer.get("display") or "")
            if not display:
                raise ScopeLessonConfigurationError(
                    "lesson_scope_answer_authority_invalid: "
                    f"Goal {goal.goal_ref!r} has an empty verified answer"
                )
            mutable.setdefault(producer, []).append((goal.goal_ref, display))
    return {key: tuple(values) for key, values in mutable.items()}


def _diag(
    code: str,
    stage: str,
    path: str,
    message: str,
    scope_ref: str,
    *,
    severity: Literal["error", "warning"] = "error",
) -> ScopeLessonDiagnostic:
    return ScopeLessonDiagnostic(
        code=code,
        stage=stage,
        path=path,
        message=message,
        scope_ref=scope_ref,
        severity=severity,
    )


def _dedupe(values: Sequence[str] | Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values))


def _teaching_step_ref(position: int) -> str:
    return f"s{position + 1}"


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _stable_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "BoundLessonStep",
    "LessonScopeContentValidator",
    "SCOPE_LESSON_EVALUATION_CONTRACT",
    "SCOPE_LESSON_GENERATION_CONTRACT",
    "SCOPE_LESSON_VALIDATION_CONTRACT",
    "ScopeLessonAuthoringService",
    "ScopeLessonConfigurationError",
    "ScopeLessonDiagnostic",
    "ScopeLessonGenerationResult",
    "ScopeLessonTransportAttempt",
    "ScopeLessonValidationResult",
    "answer_display_is_covered",
    "build_deterministic_scope_content",
    "evaluate_scope_lesson_content",
]
