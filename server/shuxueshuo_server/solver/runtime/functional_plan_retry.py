"""Call-level retry merge for strict FunctionalPlan candidates."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

def prepare_functional_plan_raw_response(
    raw_response: str,
    *,
    previous_attempts: Sequence[Any],
) -> str:
    """Apply only formal FunctionalPlan retry memory to a new candidate.

    This function deliberately does not inspect legacy StepIntent diagnostics or
    accepted prefixes.  Once the selected protocol is FunctionalPlan, call-level
    retry memory is the only merge authority.
    """
    raw_response = _strip_single_json_fence(raw_response)
    try:
        candidate = json.loads(raw_response)
    except json.JSONDecodeError:
        return raw_response
    if not isinstance(candidate, dict):
        return raw_response
    candidate = _drop_empty_return_bindings(candidate)
    candidate = _drop_redundant_semantic_ref_scopes(candidate)
    retry_state = latest_functional_retry_state(previous_attempts)
    if retry_state is None:
        return json.dumps(candidate, ensure_ascii=False)
    merged = _overlay_functional_retry_state(candidate, retry_state)
    return json.dumps(merged, ensure_ascii=False)


def _strip_single_json_fence(raw_response: str) -> str:
    """Remove one whole-response JSON fence without extracting surrounding text."""
    match = re.fullmatch(
        r"\s*```(?:json)?\s*(\{.*\})\s*```\s*",
        raw_response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match is not None else raw_response


def _drop_empty_return_bindings(candidate: dict[str, Any]) -> dict[str, Any]:
    """Treat an empty return binding as an unbound, auto-allocated return.

    FunctionalPlan already materializes a return when a later ``CallResultRef``
    consumes it. An empty object therefore carries no identity or destination
    information and can be removed without inventing mathematical structure.
    """
    result = json.loads(json.dumps(candidate))
    scopes = result.get("scopes")
    if not isinstance(scopes, list):
        return result
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        calls = scope.get("calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            bindings = call.get("return_bindings")
            if not isinstance(bindings, dict):
                continue
            call["return_bindings"] = {
                name: binding
                for name, binding in bindings.items()
                if binding != {}
            }
    return result


def _drop_redundant_semantic_ref_scopes(
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Remove a redundant legacy ``scope`` hint from short semantic refs.

    Functional calls already establish the lookup scope. A repeated scope is
    mechanical wire noise when it equals the call scope, or when the ref is
    already explicitly prefixed with that scope. Conflicting hints remain in
    place so strict wire validation reports them instead of changing meaning.
    """
    result = json.loads(json.dumps(candidate))
    scopes = result.get("scopes")
    if not isinstance(scopes, list):
        return result
    for scope in scopes:
        if not isinstance(scope, dict):
            continue
        scope_id = scope.get("scope_id")
        calls = scope.get("calls")
        if not isinstance(scope_id, str) or not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            refs: list[Any] = []
            args = call.get("args")
            if isinstance(args, dict):
                for value in args.values():
                    refs.extend(value if isinstance(value, list) else [value])
            bindings = call.get("return_bindings")
            if isinstance(bindings, dict):
                refs.extend(bindings.values())
            for ref in refs:
                if not isinstance(ref, dict) or "from_call" in ref:
                    continue
                ref_scope = ref.get("scope")
                ref_name = ref.get("ref")
                if not isinstance(ref_scope, str) or not isinstance(ref_name, str):
                    continue
                if ref_scope == scope_id or ref_name.startswith(f"{ref_scope}."):
                    ref.pop("scope", None)
    return result


def latest_functional_retry_state(
    previous_attempts: Sequence[Any],
) -> dict[str, Any] | None:
    """Return the newest formal FunctionalPlan retry payload, if any."""
    for attempt in reversed(previous_attempts):
        if not isinstance(attempt, dict):
            continue
        for key in (
            "context_derived_retry_state",
            "planner_retry_state",
        ):
            state = attempt.get(key)
            if (
                isinstance(state, dict)
                and state.get("candidate_format") == "functional_plan"
            ):
                return state
    return None


def _overlay_functional_retry_state(
    candidate: dict[str, Any],
    retry_state: dict[str, Any],
) -> dict[str, Any]:
    policy = retry_state.get("preserve_policy", "none")
    baseline = retry_state.get("baseline_candidate")
    if policy == "none" or not isinstance(baseline, dict):
        return candidate
    if policy == "preserve_all":
        return baseline
    if policy == "preserve_graph":
        stable = retry_state.get("stable_candidate_calls")
        return _overlay_stable_functional_calls(
            candidate,
            stable if isinstance(stable, list) else [],
            baseline=baseline,
        )
    if policy == "preserve_prefix":
        stable = retry_state.get("stable_candidate_prefix")
        return _overlay_stable_functional_calls(
            candidate,
            stable if isinstance(stable, list) else [],
            baseline=baseline,
        )
    if policy == "preserve_handles":
        return _overlay_functional_call_fields(
            candidate,
            baseline,
            fields=(
                "capability_id",
                "args",
                "return_bindings",
                "return_expectations",
            ),
        )
    if policy == "preserve_step":
        repair = retry_state.get("repair_suffix_start")
        call_id = repair.get("call_id") if isinstance(repair, dict) else None
        if isinstance(call_id, str):
            return _overlay_functional_call_fields(
                candidate,
                baseline,
                fields=(
                    "capability_id",
                    "args",
                    "return_bindings",
                    "return_expectations",
                    "strategy",
                    "reason",
                ),
                call_ids={call_id},
            )
    return candidate


def functional_repair_instruction(
    *,
    stable_candidate_calls: Sequence[Mapping[str, Any]],
    repair_call_ids: Sequence[str],
    issue_count: int,
) -> str:
    """Build the FunctionalPlan-only repair work order summary."""
    stable_ids = [
        call_id
        for entry in stable_candidate_calls
        if isinstance(entry, Mapping)
        for call in (entry.get("call"),)
        if isinstance(call, Mapping)
        if isinstance((call_id := call.get("call_id")), str)
    ]
    parts = [
        "Use baseline_candidate as the candidate graph and output one complete "
        "FunctionalPlan.",
    ]
    if stable_ids:
        parts.append(
            "Keep these verified calls unchanged; code restores them if omitted "
            f"or modified: {', '.join(stable_ids)}."
        )
    if repair_call_ids:
        parts.append(
            "Repair these root calls and any calls blocked by them: "
            f"{', '.join(repair_call_ids)}."
        )
    parts.append(
        "A repair may insert prerequisite calls before a root call or replace "
        "that call's capability, but it must not modify the verified graph. "
        "When a ticket marks unchanged_binding_rejected, do not resubmit the "
        "same capability with the same args."
    )
    parts.append(
        f"Resolve all {issue_count} structured repair tickets; deterministic "
        "repairs already listed in each ticket must not be undone."
    )
    return " ".join(parts)


def _overlay_stable_functional_calls(
    candidate: dict[str, Any],
    stable: list[Any],
    *,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    stable_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for entry in stable:
        if not isinstance(entry, dict):
            continue
        scope_id = entry.get("scope_id")
        call = entry.get("call")
        call_id = call.get("call_id") if isinstance(call, dict) else None
        if isinstance(scope_id, str) and isinstance(call_id, str):
            stable_by_id[call_id] = (scope_id, dict(call))
    if not stable_by_id:
        return candidate

    result = json.loads(json.dumps(candidate))
    raw_scopes = result.get("scopes")
    if not isinstance(raw_scopes, list):
        return candidate
    present: set[str] = set()
    by_scope: dict[str, dict[str, Any]] = {}
    for scope in raw_scopes:
        if not isinstance(scope, dict):
            continue
        scope_id = scope.get("scope_id")
        calls = scope.get("calls")
        if not isinstance(scope_id, str) or not isinstance(calls, list):
            continue
        by_scope[scope_id] = scope
        for index, call in enumerate(calls):
            call_id = call.get("call_id") if isinstance(call, dict) else None
            if call_id in stable_by_id:
                calls[index] = stable_by_id[call_id][1]
                present.add(call_id)

    # A model may preserve a verified call semantically while renaming its
    # call_id. Restoring the old call by id alone would then create two writers
    # for the same state. Collapse exact semantic equivalents back to the
    # stable identity and redirect their downstream CallResultRef edges.
    renamed_call_ids: dict[str, str] = {}
    for stable_call_id, (scope_id, stable_call) in stable_by_id.items():
        if stable_call_id in present:
            continue
        scope = by_scope.get(scope_id)
        calls = scope.get("calls") if isinstance(scope, dict) else None
        if not isinstance(calls, list):
            continue
        stable_key = _functional_call_semantic_key(stable_call)
        if stable_key is None:
            continue
        matching_indexes = [
            index
            for index, call in enumerate(calls)
            if isinstance(call, dict)
            and _functional_call_semantic_key(call) == stable_key
        ]
        if not matching_indexes:
            continue
        first_index = matching_indexes[0]
        for index in matching_indexes:
            candidate_call_id = calls[index].get("call_id")
            if isinstance(candidate_call_id, str):
                renamed_call_ids[candidate_call_id] = stable_call_id
        calls[first_index] = stable_call
        for index in reversed(matching_indexes[1:]):
            del calls[index]
        present.add(stable_call_id)

    if renamed_call_ids:
        _rewrite_functional_call_result_refs(result, renamed_call_ids)

    baseline_labels = {
        scope.get("scope_id"): scope.get("label")
        for scope in baseline.get("scopes", [])
        if isinstance(scope, dict) and isinstance(scope.get("scope_id"), str)
    }
    for call_id, (scope_id, call) in reversed(tuple(stable_by_id.items())):
        if call_id in present:
            continue
        scope = by_scope.get(scope_id)
        if scope is None:
            scope = {
                "scope_id": scope_id,
                "label": baseline_labels.get(scope_id, scope_id),
                "calls": [],
            }
            raw_scopes.insert(0, scope)
            by_scope[scope_id] = scope
        calls = scope.get("calls")
        if isinstance(calls, list):
            calls.insert(0, call)
    return result


def _functional_call_semantic_key(call: Mapping[str, Any]) -> str | None:
    """Return the wire-level identity of a call, excluding narration and id."""
    capability_id = call.get("capability_id")
    args = call.get("args")
    return_bindings = call.get("return_bindings")
    if (
        not isinstance(capability_id, str)
        or not isinstance(args, dict)
        or not isinstance(return_bindings, dict)
    ):
        return None
    return json.dumps(
        {
            "capability_id": capability_id,
            "args": args,
            "return_bindings": return_bindings,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _rewrite_functional_call_result_refs(
    value: Any,
    renamed_call_ids: Mapping[str, str],
) -> None:
    """Rewrite downstream graph edges after stable call identity restoration."""
    if isinstance(value, dict):
        from_call = value.get("from_call")
        if isinstance(from_call, str) and from_call in renamed_call_ids:
            value["from_call"] = renamed_call_ids[from_call]
        for item in value.values():
            _rewrite_functional_call_result_refs(item, renamed_call_ids)
    elif isinstance(value, list):
        for item in value:
            _rewrite_functional_call_result_refs(item, renamed_call_ids)


def _overlay_functional_call_fields(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    *,
    fields: tuple[str, ...],
    call_ids: set[str] | None = None,
) -> dict[str, Any]:
    baseline_calls = {
        call.get("call_id"): call
        for scope in baseline.get("scopes", [])
        if isinstance(scope, dict)
        for call in scope.get("calls", [])
        if isinstance(call, dict) and isinstance(call.get("call_id"), str)
    }
    result = json.loads(json.dumps(candidate))
    for scope in result.get("scopes", []):
        if not isinstance(scope, dict):
            continue
        for call in scope.get("calls", []):
            if not isinstance(call, dict):
                continue
            call_id = call.get("call_id")
            if call_ids is not None and call_id not in call_ids:
                continue
            source = baseline_calls.get(call_id)
            if source is None:
                continue
            for field_name in fields:
                if field_name in source:
                    call[field_name] = source[field_name]
    return result
