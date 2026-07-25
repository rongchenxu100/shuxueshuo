"""Strict FunctionalPlan wire validation and parsing."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence, cast

from shuxueshuo_server.solver.contracts import FunctionalResultForm
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCall,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalPlanValidationReport,
    FunctionalRef,
    FunctionalScope,
    _issue,
    _text,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    SEMANTIC_READ_KINDS,
    looks_like_canonical_ref,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef

class FunctionalPlanValidator:
    """Parse the strict FunctionalPlan wire shape and collect all errors."""

    def validate_json_with_report(
        self,
        raw: str,
        *,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
    ) -> tuple[FunctionalPlan | None, FunctionalPlanValidationReport]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            issue = _issue(
                "functional_validation",
                "functional.invalid_json",
                f"invalid FunctionalPlan JSON: {exc}",
            )
            return None, FunctionalPlanValidationReport((issue,))
        return self.validate_payload_with_report(
            payload,
            handle_registry=handle_registry,
            question_goals=question_goals,
        )

    def validate_payload_with_report(
        self,
        payload: object,
        *,
        handle_registry: CanonicalHandleRegistry,
        question_goals: Sequence[QuestionGoal],
    ) -> tuple[FunctionalPlan | None, FunctionalPlanValidationReport]:
        issues: list[FunctionalPlanIssue] = []
        deterministic_repairs: list[dict[str, Any]] = []
        if not isinstance(payload, dict):
            issues.append(
                _issue(
                    "functional_validation",
                    "functional.root_type",
                    "FunctionalPlan must be an object",
                )
            )
            return None, FunctionalPlanValidationReport(tuple(issues))
        _check_fields(
            payload,
            {"format", "scopes"},
            {"format", "scopes"},
            issues,
            "plan",
        )
        if payload.get("format") != "functional_plan/v1":
            issues.append(
                _issue(
                    "functional_validation",
                    "functional.format",
                    "format must equal functional_plan/v1",
                )
            )
        raw_scopes = payload.get("scopes")
        if not isinstance(raw_scopes, list) or not raw_scopes:
            issues.append(
                _issue(
                    "functional_validation",
                    "functional.scopes",
                    "scopes must be a non-empty array",
                )
            )
            return None, FunctionalPlanValidationReport(tuple(issues), dict(payload))
        scopes: list[FunctionalScope] = []
        seen_scopes: set[str] = set()
        seen_calls: set[str] = set()
        for scope_index, raw_scope in enumerate(raw_scopes):
            if not isinstance(raw_scope, dict):
                issues.append(
                    _issue(
                        "functional_validation",
                        "functional.scope_type",
                        f"scopes[{scope_index}] must be an object",
                    )
                )
                continue
            _check_fields(
                raw_scope,
                {"scope_id", "label", "calls"},
                {"scope_id", "label", "calls"},
                issues,
                f"scopes[{scope_index}]",
            )
            scope_id = _text(raw_scope.get("scope_id"))
            label = _text(raw_scope.get("label"))
            if scope_id is None:
                issues.append(
                    _issue(
                        "functional_validation",
                        "functional.scope_id",
                        f"scopes[{scope_index}].scope_id must be a non-empty string",
                    )
                )
                continue
            if scope_id not in handle_registry.scope_ids:
                issues.append(
                    _issue(
                        "functional_validation",
                        "functional.scope_unknown",
                        f"unknown scope: {scope_id}",
                        scope_id=scope_id,
                    )
                )
            if scope_id in seen_scopes:
                issues.append(
                    _issue(
                        "functional_validation",
                        "functional.duplicate_scope_id",
                        f"duplicate scope_id: {scope_id}",
                        scope_id=scope_id,
                    )
                )
            seen_scopes.add(scope_id)
            raw_calls = raw_scope.get("calls")
            if not isinstance(raw_calls, list) or not raw_calls:
                issues.append(
                    _issue(
                        "functional_validation",
                        "functional.calls",
                        f"scope {scope_id} calls must be a non-empty array",
                        scope_id=scope_id,
                    )
                )
                continue
            calls: list[FunctionalCall] = []
            for call_index, raw_call in enumerate(raw_calls):
                call = _parse_call(
                    raw_call,
                    scope_id,
                    call_index,
                    issues,
                    deterministic_repairs,
                    handle_registry=handle_registry,
                )
                if call is None:
                    continue
                if call.call_id in seen_calls:
                    issues.append(
                        _issue(
                            "functional_validation",
                            "functional.duplicate_call_id",
                            f"duplicate call_id: {call.call_id}",
                            call_id=call.call_id,
                            scope_id=scope_id,
                        )
                    )
                else:
                    seen_calls.add(call.call_id)
                calls.append(call)
            if calls:
                scopes.append(FunctionalScope(scope_id, label or scope_id, tuple(calls)))
        plan = FunctionalPlan(tuple(scopes)) if scopes else None
        return (
            plan if plan is not None and not issues else None,
            FunctionalPlanValidationReport(
                tuple(issues),
                plan.to_payload() if plan is not None else dict(payload),
                tuple(deterministic_repairs),
            ),
        )

FUNCTIONAL_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$defs": {
        "semantic_ref": {
            "type": "object",
            "description": "引用 ProblemIR 中已有的 semantic_ref。",
            "additionalProperties": False,
            "required": ["ref", "kind"],
            "properties": {
                "ref": {
                    "type": "string",
                    "description": "ProblemIR 中原样出现的 semantic_ref。",
                    "minLength": 1,
                    "pattern": (
                        r"^(?!(?:point|line|segment|ray|function|symbol|angle|"
                        r"circle|polygon|fact|answer):).+$"
                    ),
                },
                "kind": {
                    "description": (
                        "entity 使用 entity_type，fact 使用 fact，"
                        "question goal 使用 answer。"
                    ),
                    "enum": sorted(SEMANTIC_READ_KINDS),
                },
                "value_type": {
                    "type": "string",
                    "minLength": 1,
                    "description": "可选；通常省略。",
                },
            },
        },
        "call_result_ref": {
            "type": "object",
            "description": "引用当前计划中更早 call 的已声明 return。",
            "additionalProperties": False,
            "required": ["from_call", "return"],
            "properties": {
                "from_call": {
                    "type": "string",
                    "minLength": 1,
                    "description": "更早出现的 call_id。",
                },
                "return": {
                    "type": "string",
                    "minLength": 1,
                    "description": "该 capability catalog 中声明的 return name。",
                },
            },
        },
        "functional_ref": {
            "oneOf": [
                {"$ref": "#/$defs/semantic_ref"},
                {"$ref": "#/$defs/call_result_ref"},
            ]
        },
    },
    "type": "object",
    "description": "用 capability 调用图表示的完整数学解法。",
    "additionalProperties": False,
    "required": ["format", "scopes"],
    "properties": {
        "format": {"const": "functional_plan/v1"},
        "scopes": {
            "type": "array",
            "description": "按 ProblemIR scope 组织调用。",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scope_id", "label", "calls"],
                "properties": {
                    "scope_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": (
                            "把调用放在它直接服务的小问 scope 下；可被多个小问"
                            "复用的计算无需移动到父问。scope_id 必须来自 ProblemIR。"
                        ),
                    },
                    "label": {
                        "type": "string",
                        "minLength": 1,
                        "description": "该题问的简短名称。",
                    },
                    "calls": {
                        "type": "array",
                        "description": "按依赖顺序排列的数学能力调用。",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "call_id", "capability_id",
                                "args", "return_bindings", "strategy", "reason",
                            ],
                            "properties": {
                                "call_id": {
                                    "type": "string",
                                    "description": "全计划唯一的语义化调用名称。",
                                    "pattern": r"^[A-Za-z][A-Za-z0-9_]*$",
                                },
                                "capability_id": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": (
                                        "Functional Capability Catalog 中已有的 id。"
                                    ),
                                },
                                "args": {
                                    "type": "object",
                                    "description": (
                                        "key 必须是 capability catalog 展示的 arg name；"
                                        "value 引用题面信息或更早 call 的结果。"
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
                                "return_bindings": {
                                    "type": "object",
                                    "description": (
                                        "只绑定最终答案或 ProblemIR 中已有对象；"
                                        "普通中间结果保持为空。"
                                    ),
                                    "additionalProperties": {
                                        "$ref": "#/$defs/semantic_ref"
                                    },
                                },
                                "return_expectations": {
                                    "type": "object",
                                    "description": (
                                        "仅用于 return 声明 possible_forms 的结果。"
                                        "有意保留未定参数时写 open_expression；准备直接绑定"
                                        "数值答案时写 closed_value；对象状态仍含自由符号时写"
                                        "open_state，已完全确定时写 closed_state。该字段只是预期，代码会"
                                        "按实际自由符号验证。"
                                    ),
                                    "additionalProperties": {
                                        "type": "string",
                                        "enum": [
                                            "open_expression",
                                            "closed_value",
                                            "open_state",
                                            "closed_state",
                                        ],
                                    },
                                },
                                "strategy": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": "本调用采用的数学方法。",
                                },
                                "reason": {
                                    "type": "string",
                                    "minLength": 1,
                                    "description": "该调用在完整解法中的必要性。",
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}



def _parse_call(
    value: object,
    scope_id: str,
    call_index: int,
    issues: list[FunctionalPlanIssue],
    deterministic_repairs: list[dict[str, Any]],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> FunctionalCall | None:
    if not isinstance(value, dict):
        issues.append(
            _issue(
                "functional_validation",
                "functional.call_type",
                f"call {call_index} must be an object",
                scope_id=scope_id,
            )
        )
        return None
    required = {
        "call_id",
        "capability_id",
        "args",
        "return_bindings",
        "strategy",
        "reason",
    }
    _check_fields(
        value,
        {*required, "return_expectations"},
        required,
        issues,
        f"call[{call_index}]",
        scope_id=scope_id,
    )
    call_id = _text(value.get("call_id"))
    capability_id = _text(value.get("capability_id"))
    strategy = _text(value.get("strategy"))
    reason = _text(value.get("reason"))
    if call_id is not None and strategy is None and reason is not None:
        strategy = reason
        deterministic_repairs.append(
            {
                "call_id": call_id,
                "action": "fill_missing_call_text",
                "from": "strategy=empty",
                "to": "strategy=reason",
            }
        )
    if call_id is not None and reason is None and strategy is not None:
        reason = strategy
        deterministic_repairs.append(
            {
                "call_id": call_id,
                "action": "fill_missing_call_text",
                "from": "reason=empty",
                "to": "reason=strategy",
            }
        )
    if not all((call_id, capability_id, strategy, reason)):
        issues.append(
            _issue(
                "functional_validation",
                "functional.call_required",
                f"call {call_index} has missing string fields",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", call_id) is None:
        issues.append(
            _issue(
                "functional_validation",
                "functional.call_id_format",
                f"call_id must be a stable identifier: {call_id}",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
    raw_args = value.get("args")
    raw_bindings = value.get("return_bindings")
    raw_expectations = value.get("return_expectations", {})
    if (
        not isinstance(raw_args, dict)
        or not isinstance(raw_bindings, dict)
        or not isinstance(raw_expectations, dict)
    ):
        issues.append(
            _issue(
                "functional_validation",
                "functional.call_maps",
                "args, return_bindings and return_expectations must be objects",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    args: dict[str, tuple[FunctionalRef, ...]] = {}
    for name, raw_ref in raw_args.items():
        if not isinstance(name, str) or not name:
            issues.append(
                _issue(
                    "functional_validation",
                    "functional.arg_name",
                    "argument names must be non-empty strings",
                    call_id=call_id,
                    scope_id=scope_id,
                )
            )
            continue
        raw_values = raw_ref if isinstance(raw_ref, list) else [raw_ref]
        parsed: list[FunctionalRef] = []
        dropped_null = False
        for item in raw_values:
            if item is None:
                dropped_null = True
                continue
            ref = _parse_functional_ref(
                item,
                call_id,
                scope_id,
                issues,
                deterministic_repairs,
                handle_registry=handle_registry,
            )
            if ref is not None:
                parsed.append(ref)
        if dropped_null:
            deterministic_repairs.append(
                {
                    "call_id": call_id,
                    "action": "drop_null_functional_arg",
                    "arg": name,
                    "from": "null",
                    "to": "omitted" if not parsed else "non_null_items",
                }
            )
        if parsed:
            args[name] = tuple(parsed)
    bindings: dict[str, SemanticRef] = {}
    for name, raw_ref in raw_bindings.items():
        ref = _parse_semantic_ref(
            raw_ref,
            call_id,
            scope_id,
            issues,
            deterministic_repairs,
            handle_registry=handle_registry,
        )
        if ref is not None:
            bindings[str(name)] = ref
    expectations: dict[str, FunctionalResultForm] = {}
    allowed_forms = {
        "open_expression",
        "closed_value",
        "open_state",
        "closed_state",
    }
    for name, raw_form in raw_expectations.items():
        if not isinstance(name, str) or not name or raw_form not in allowed_forms:
            issues.append(
                _issue(
                    "functional_validation",
                    "functional.return_expectation_value",
                    (
                        "return expectations require a non-empty return name and "
                        "open_expression, closed_value, open_state or closed_state"
                    ),
                    call_id=call_id,
                    scope_id=scope_id,
                )
            )
            continue
        expectations[name] = cast(FunctionalResultForm, raw_form)
    return FunctionalCall(
        call_id,
        capability_id,
        args,
        bindings,
        strategy,
        reason,
        expectations,
    )


def _parse_functional_ref(
    value: object,
    call_id: str,
    scope_id: str,
    issues: list[FunctionalPlanIssue],
    deterministic_repairs: list[dict[str, Any]],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> FunctionalRef | None:
    if isinstance(value, dict) and ("from_call" in value or "return" in value):
        if set(value) != {"from_call", "return"}:
            issues.append(
                _issue(
                    "functional_validation",
                    "functional.call_result_shape",
                    "CallResultRef requires exactly from_call and return",
                    call_id=call_id,
                    scope_id=scope_id,
                )
            )
            return None
        source = _text(value.get("from_call"))
        return_name = _text(value.get("return"))
        if source and return_name:
            return CallResultRef(source, return_name)
        issues.append(
            _issue(
                "functional_validation",
                "functional.call_result_required",
                "CallResultRef fields must be non-empty strings",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    return _parse_semantic_ref(
        value,
        call_id,
        scope_id,
        issues,
        deterministic_repairs,
        handle_registry=handle_registry,
    )


def _parse_semantic_ref(
    value: object,
    call_id: str,
    scope_id: str,
    issues: list[FunctionalPlanIssue],
    deterministic_repairs: list[dict[str, Any]],
    *,
    handle_registry: CanonicalHandleRegistry,
) -> SemanticRef | None:
    if not isinstance(value, dict):
        issues.append(
            _issue(
                "functional_validation",
                "functional.semantic_ref_type",
                "SemanticRef must be an object",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    if not {"ref", "kind"} <= set(value) or not set(value) <= {"ref", "kind", "value_type"}:
        issues.append(
            _issue(
                "functional_validation",
                "functional.semantic_ref_shape",
                "SemanticRef requires ref/kind and optional value_type only",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    ref = _text(value.get("ref"))
    kind = _text(value.get("kind"))
    value_type = _text(value.get("value_type"))
    if ref is not None and kind == "entity":
        normalized_kind = _unique_entity_kind_for_ref(
            ref,
            scope_id=scope_id,
            handle_registry=handle_registry,
        )
        if normalized_kind is not None:
            deterministic_repairs.append(
                {
                    "call_id": call_id,
                    "action": "normalize_unique_entity_kind",
                    "from": f"entity:{ref}",
                    "to": f"{normalized_kind}:{ref}",
                }
            )
            kind = normalized_kind
    if ref is None or kind is None or kind not in SEMANTIC_READ_KINDS:
        issues.append(
            _issue(
                "functional_validation",
                "functional.semantic_ref_required",
                "SemanticRef ref/kind is invalid",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    if looks_like_canonical_ref(ref, allowed_kinds=SEMANTIC_READ_KINDS):
        issues.append(
            _issue(
                "functional_validation",
                "functional.canonical_ref_forbidden",
                f"FunctionalPlan requires a short semantic ref, got {ref}",
                call_id=call_id,
                scope_id=scope_id,
            )
        )
        return None
    return SemanticRef(ref, kind, value_type=value_type)


def _unique_entity_kind_for_ref(
    ref: str,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> str | None:
    """Resolve the generic ``entity`` label only when identity is exact.

    This is a wire representation repair, not a semantic guess: the short ref
    must identify one visible ProblemIR entity kind in the current scope chain.
    """

    visible_scopes = set(handle_registry.ancestor_scopes(scope_id))
    kinds = {
        str(payload.get("entity_type", "")).strip()
        for handle, payload in handle_registry.entity_payloads.items()
        if str(payload.get("scope_id", "")) in visible_scopes
        and ref
        in {
            str(payload.get("semantic_ref", "")),
            str(payload.get("name", "")),
            (
                f"{payload.get('scope_id')}."
                f"{payload.get('semantic_ref') or payload.get('name')}"
            ),
        }
        and handle in handle_registry.entity_handles
    }
    kinds.discard("")
    return next(iter(kinds)) if len(kinds) == 1 else None



def _check_fields(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    issues: list[FunctionalPlanIssue],
    location: str,
    *,
    scope_id: str | None = None,
) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        issues.append(
            _issue(
                "functional_validation",
                "functional.fields_missing",
                f"{location} missing fields: {missing}",
                scope_id=scope_id,
            )
        )
    if extra:
        issues.append(
            _issue(
                "functional_validation",
                "functional.fields_extra",
                f"{location} has unknown fields: {extra}",
                scope_id=scope_id,
            )
        )
