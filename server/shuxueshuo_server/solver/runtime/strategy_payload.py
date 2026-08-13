"""Functional Strategy Planner prompt payload and debug artifacts."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    FamilyRegistry,
)
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
)
from shuxueshuo_server.solver.extraction.problem_planning_retry import (
    ProblemPlanningRetryProjector,
)
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventory
from shuxueshuo_server.solver.runtime.functional_plan import (
    FUNCTIONAL_PLAN_JSON_SCHEMA,
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_few_shots import (
    FunctionalFewShotSelectionMode,
    FunctionalFewShotSelectionRecord,
    select_functional_few_shot,
    split_functional_few_shot_asset,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    SEMANTIC_READ_KINDS,
    looks_like_canonical_ref,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
)
from shuxueshuo_server.solver.runtime.functional_plan_retry import (
    retry_state_from_attempt,
)
from shuxueshuo_server.solver.runtime.scoped_functional_few_shots import (
    select_scoped_functional_few_shot,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    SCOPED_FUNCTIONAL_PLAN_CONTRACT,
    scoped_functional_plan_schema,
)
from shuxueshuo_server.solver.runtime.semantic_reads import ContextSemanticReadSource
from shuxueshuo_server.solver.runtime.strategy_models import (
    FunctionalExecutionDiagnostic,
    StrategyPrompt,
)


class PlannerStateContextDebugSource(ContextSemanticReadSource, Protocol):
    """Planner context projection used by debug artifact writing."""

    def to_payload(self) -> dict[str, Any]:
        """Return full context snapshot payload."""

    @property
    def rewrite_ledger_payload(self) -> list[dict[str, str]]:
        """Return state rewrite ledger payload."""

    @property
    def events_payload(self) -> list[dict[str, Any]]:
        """Return context event payload."""

class StrategyPayloadBuilder:
    """把 PlannerInputs 压缩成 LLM 可读的 probe payload。

    题目语义仅通过 scope-native Planner Problem View 进入 prompt；完整
    PlannerStateContext 只作为内部绑定、执行和 debug authority。
    """

    def __init__(
        self,
        *,
        functional_few_shot_examples: list[dict[str, Any]] | None = None,
        functional_few_shot_dir: Path | str | None = None,
        functional_plan_fixture_dir: Path | str | None = None,
        allow_same_problem_few_shot: bool = True,
        functional_few_shot_mode: FunctionalFewShotSelectionMode | None = None,
        scoped_functional_few_shot_examples: list[dict[str, Any]] | None = None,
        scoped_functional_few_shot_dir: Path | str | None = None,
        problem_payload: dict[str, Any] | None = None,
    ) -> None:
        self.functional_few_shot_examples = functional_few_shot_examples
        self.functional_few_shot_dir = (
            Path(functional_few_shot_dir)
            if functional_few_shot_dir is not None
            else None
        )
        self.functional_plan_fixture_dir = (
            Path(functional_plan_fixture_dir)
            if functional_plan_fixture_dir is not None
            else None
        )
        self.allow_same_problem_few_shot = allow_same_problem_few_shot
        self.functional_few_shot_mode = functional_few_shot_mode
        self.scoped_functional_few_shot_examples = (
            scoped_functional_few_shot_examples
        )
        self.scoped_functional_few_shot_dir = (
            Path(scoped_functional_few_shot_dir)
            if scoped_functional_few_shot_dir is not None
            else None
        )
        self.problem_payload = problem_payload

    def build(
        self,
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any] | None = None,
        planner_state_context: ContextSemanticReadSource | None = None,
        problem_planning_context: ProblemPlanningContext | None = None,
        problem_binding_catalog: ProblemPlanningBindingCatalog | None = None,
        _include_v1_few_shot: bool = True,
    ) -> dict[str, Any]:
        """生成唯一的 FunctionalPlan prompt payload。"""
        if problem_planning_context is None or problem_binding_catalog is None:
            raise ValueError(
                "planner.problem_bundle_required: Strategy payload requires "
                "ProblemPlanningContext and ProblemPlanningBindingCatalog"
            )
        if (
            problem_binding_catalog.planning_context_id
            != problem_planning_context.planning_context_id
        ):
            raise ValueError(
                "planner.problem_revision_drift: planning Context and binding "
                "catalog differ"
            )
        problem_payload = problem_payload or self.problem_payload
        if problem_payload is None:
            if inputs.problem is not None:
                problem_payload = problem_to_llm_payload(inputs.problem)
            else:
                raise ValueError(
                    "StrategyPayloadBuilder requires canonical problem payload; "
                    "StrategyPlanner should provide it via RuntimeProjection"
                )
        # Canonical payload 只用于构造内部 handle registry；LLM 的题目事实源是下方
        # prompt-safe Planner Problem View，不会序列化这个 payload 或 PlannerStateContext。
        handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
        if planner_state_context is None:
            planner_state_context = initial_planner_state_context(
                inputs,
                problem_payload=problem_payload,
                handle_registry=handle_registry,
            )
        previous_attempts = list(inputs.previous_errors)
        semantic_index = FunctionalSemanticIndex.from_semantic_items(
            planner_state_context,
            problem_binding_catalog.semantic_read_items(),
            handle_registry=handle_registry,
        )
        functional_catalog = FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ).contextualized(semantic_index)
        if _include_v1_few_shot:
            few_shot_examples, few_shot_selection = (
                self._functional_few_shot_examples(
                    inputs,
                    functional_catalog=functional_catalog,
                )
            )
        else:
            few_shot_examples, few_shot_selection = [], None
        previous_attempt_state = _functional_previous_attempt_state(
            previous_attempts,
            problem_planning_context=problem_planning_context,
        )
        latest_retry_state = previous_attempt_state.get("latest_retry_state")
        retry_problem_context = (
            latest_retry_state.pop("problem_retry_context", None)
            if isinstance(latest_retry_state, dict)
            else None
        )
        prompt_problem_context = (
            retry_problem_context
            if isinstance(retry_problem_context, dict)
            else problem_planning_context.to_prompt_payload()
        )
        return {
            "planner_protocol": "functional_plan/v1",
            "problem_id": inputs.problem_id,
            "family_id": inputs.family_spec.family_id,
            "problem_planning_context": prompt_problem_context,
            "strategy_principles": list(inputs.family_spec.strategy_principles),
            "functional_capability_catalog": (
                functional_catalog.to_prompt_payload()
            ),
            "few_shot_examples": few_shot_examples,
            "functional_few_shot_selection": few_shot_selection,
            "previous_attempt_state": previous_attempt_state,
            "output_json_schema": FUNCTIONAL_PLAN_JSON_SCHEMA,
        }

    def build_scoped(
        self,
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any] | None = None,
        planner_state_context: ContextSemanticReadSource | None = None,
        problem_planning_context: ProblemPlanningContext,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
    ) -> dict[str, Any]:
        """Build the explicit F5-F1 prompt payload without switching v1."""

        payload = self.build(
            inputs,
            problem_payload=problem_payload,
            planner_state_context=planner_state_context,
            problem_planning_context=problem_planning_context,
            problem_binding_catalog=problem_binding_catalog,
            _include_v1_few_shot=False,
        )
        examples = self.scoped_functional_few_shot_examples
        selection = None
        if examples is None:
            catalog_payload = payload["functional_capability_catalog"]
            capability_ids = {
                item["capability_id"]
                for item in catalog_payload["capabilities"]
            }
            selected, selection = select_scoped_functional_few_shot(
                capability_ids,
                directory=self.scoped_functional_few_shot_dir,
            )
            examples = [selected] if selected is not None else []
        result = {
            **payload,
            "planner_protocol": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
            "problem_planning_context": (
                problem_planning_context.to_prompt_payload()
            ),
            "few_shot_examples": examples,
            "functional_few_shot_selection": selection,
            "output_json_schema": scoped_functional_plan_schema(),
        }
        result.pop("previous_attempt_state", None)
        return result

    def _functional_few_shot_examples(
        self,
        inputs: PlannerInputs,
        *,
        functional_catalog: FunctionalCapabilityCatalog,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Select one neutral mechanism graph supported by this Context."""
        if self.functional_few_shot_examples is not None:
            return self.functional_few_shot_examples, None
        locked_selection = _latest_functional_few_shot_selection(
            list(inputs.previous_errors)
        )
        result = select_functional_few_shot(
            capability_ids=functional_catalog.items,
            base_pack_ids=inputs.family_spec.base_packs,
            mechanism_pack_ids=inputs.family_spec.mechanism_packs,
            answer_value_types=(
                goal.value_type
                for goal in inputs.question_goals
                if goal.required
            ),
            family_id=inputs.family_spec.family_id,
            problem_id=inputs.problem_id,
            allow_same_problem=self.allow_same_problem_few_shot,
            mode=self.functional_few_shot_mode,
            locked_selection=locked_selection,
            top_k=1,
            few_shot_dir=self.functional_few_shot_dir,
            fixture_dir=self.functional_plan_fixture_dir,
        )
        return list(result.examples), result.selection.to_payload()


def _functional_previous_attempt_state(
    previous_attempts: list[Any],
    *,
    problem_planning_context: ProblemPlanningContext | None = None,
) -> dict[str, Any]:
    """Project only formal call-level retry memory into the Functional prompt."""
    latest_attempt = next(
        (
            item
            for item in reversed(previous_attempts)
            if isinstance(item, dict)
            and retry_state_from_attempt(item) is not None
        ),
        None,
    )
    retry_state = (
        retry_state_from_attempt(latest_attempt)
        if latest_attempt is not None
        else None
    )
    if not isinstance(retry_state, dict):
        return {"attempt_count": len(previous_attempts), "latest_retry_state": None}
    selected = {
        key: retry_state[key]
        for key in (
            "attempt",
            "baseline_candidate",
            "repair_call_ids",
            "runtime_verified_calls",
            "call_memory",
            "validated_call_ids",
            "issues",
            "recovered_issues",
            "preserve_policy",
            "repair_instruction",
            "replay_depth",
            "selected_repair_layer",
            "source",
            "source_context_id",
        )
        if key in retry_state
    }
    checkpoint_payload = retry_state.get(
        "functional_retry_graph_checkpoint"
    )
    checkpoint = (
        FunctionalRetryGraphCheckpoint.from_payload(checkpoint_payload)
        if isinstance(checkpoint_payload, dict)
        else None
    )
    has_typed_checkpoint = checkpoint is not None
    if checkpoint is not None and checkpoint.problem_authority is not None:
        if problem_planning_context is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.retry_problem_revision_drift: "
                "authoritative retry requires ProblemPlanningContext"
            )
        repair_call_ids = selected.get("repair_call_ids")
        if isinstance(repair_call_ids, list) and repair_call_ids:
            projection = ProblemPlanningRetryProjector().project(
                problem_planning_context,
                checkpoint,
                tuple(
                    item
                    for item in repair_call_ids
                    if isinstance(item, str) and item
                ),
            )
            selected["problem_retry_context"] = (
                projection.to_prompt_payload()
            )
    selected["locked_call_ids"] = (
        list(checkpoint.committed_call_ids)
        if has_typed_checkpoint
        else []
    )
    call_memory = selected.pop("call_memory", [])
    runtime_verified_calls = selected.pop("runtime_verified_calls", [])
    if not has_typed_checkpoint and isinstance(call_memory, list):
        runtime_verified_calls = [
            *(
                runtime_verified_calls
                if isinstance(runtime_verified_calls, list)
                else []
            ),
            *(
                item
                for item in call_memory
                if isinstance(item, dict)
                and item.get("execution_status") == "runtime_verified"
                and (
                    item.get("commit_status") == "goal_committed"
                    or item.get("status") == "goal_committed"
                )
            ),
        ]
    selected["runtime_verified"] = _compact_functional_runtime_verified(
        runtime_verified_calls,
        issues=selected.get("issues"),
    )
    selected["issues"] = _functional_issue_tickets(selected.get("issues"))
    selected["recovered_issues"] = _functional_issue_tickets(
        selected.get("recovered_issues")
    )
    selected["locked_context_call_ids"] = _functional_locked_context_call_ids(
        selected.get("issues"),
        locked_call_ids=selected["locked_call_ids"],
    )
    selected["locked_context_results"] = _compact_functional_locked_results(
        call_memory,
        call_ids=selected["locked_context_call_ids"],
        issues=selected.get("issues"),
    )
    return {
        "attempt_count": len(previous_attempts),
        "latest_retry_state": selected,
    }


def _functional_locked_call_ids(
    value: Any,
    *,
    allowed_call_ids: set[str] | None = None,
) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            call_id
            for entry in value
            if isinstance(entry, dict)
            for call in (entry.get("call"),)
            if isinstance(call, dict)
            for call_id in (call.get("call_id"),)
            if isinstance(call_id, str) and call_id
            and (
                allowed_call_ids is None
                or call_id in allowed_call_ids
            )
        )
    )


def _functional_locked_context_call_ids(
    issues: Any,
    *,
    locked_call_ids: list[str],
) -> list[str]:
    """List locked producers that remain usable as repair context."""
    if not isinstance(issues, list):
        return []
    locked = set(locked_call_ids)
    return list(
        dict.fromkeys(
            call_id
            for issue in issues
            if isinstance(issue, dict)
            for details in (issue.get("details"),)
            if isinstance(details, dict)
            for call_id in (
                *(
                    ref.rsplit(".", 1)[0]
                    for ref in details.get("locked_result_refs", ())
                    if isinstance(ref, str) and "." in ref
                ),
                *(
                    ref.rsplit(".", 1)[0]
                    for ref in details.get("compatible_refs", ())
                    if isinstance(ref, str) and "." in ref
                ),
                *(
                    item
                    for item in details.get("locked_context_call_ids", ())
                    if isinstance(item, str)
                ),
                *(
                    item
                    for item in details.get("context_call_ids", ())
                    if isinstance(item, str)
                ),
            )
            if call_id in locked
        )
    )


_FUNCTIONAL_PROMPT_RESULT_VALUE_MAX_CHARS = 768
# Locked results are duplicated from committed call memory solely to make an
# active ticket actionable. Keep a small explicit prompt budget, selecting the
# calls most directly referenced by the ticket before broader context.
_FUNCTIONAL_LOCKED_CONTEXT_CALL_BUDGET = 4


def _compact_functional_runtime_verified(
    value: Any,
    *,
    issues: Any,
) -> list[dict[str, Any]]:
    """Keep retry evidence useful without repeating baseline call definitions."""
    if not isinstance(value, list):
        return []
    identity_calls = _functional_identity_issue_calls(issues)
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            continue
        compact: dict[str, Any] = {"call_id": call_id}
        if bool(item.get("repair_required")):
            compact["repair_required"] = True
        snapshots = item.get("results")
        if isinstance(snapshots, list):
            compact_results = [
                projected
                for snapshot in snapshots
                if isinstance(snapshot, dict)
                for projected in (
                    _compact_functional_result_snapshot(
                        snapshot,
                        include_identity=call_id in identity_calls,
                    ),
                )
                if projected is not None
            ]
            closures = [
                closure
                for projected in compact_results
                if isinstance(
                    closure := projected.pop("closure", None),
                    dict,
                )
            ]
            if closures:
                closure = closures[0]
                closure_value = closure.get("value")
                parameter_values = [
                    _parameter_assignment_value(
                        str(projected.get("value"))
                    )
                    for projected in compact_results
                    if projected.get("type") == "ParameterValue"
                    and projected.get("value") is not None
                ]
                if (
                    isinstance(closure_value, str)
                    and closure_value in parameter_values
                ):
                    closure.pop("value", None)
                compact["closure"] = closure
            if compact_results:
                compact["results"] = compact_results
        result.append(compact)
    return result


def _parameter_assignment_value(value: str) -> str:
    """Return the RHS only for a plain ``name=value`` assignment."""
    stripped = value.strip()
    if (
        stripped.count("=") != 1
        or any(operator in stripped for operator in ("<=", ">=", "!=", "=="))
    ):
        return stripped
    name, assigned = stripped.split("=", 1)
    if not name.strip() or not assigned.strip():
        return stripped
    return assigned.strip()


def _compact_functional_locked_results(
    value: Any,
    *,
    call_ids: list[str],
    issues: Any,
) -> list[dict[str, Any]]:
    """Project only locked results explicitly relevant to active tickets."""

    if not isinstance(value, list) or not call_ids:
        return []
    selected = set(
        _rank_functional_locked_context_calls(
            call_ids,
            issues=issues,
        )[:_FUNCTIONAL_LOCKED_CONTEXT_CALL_BUDGET]
    )
    return _compact_functional_runtime_verified(
        [
            item
            for item in value
            if isinstance(item, dict)
            and item.get("call_id") in selected
            and (
                item.get("commit_status") == "goal_committed"
                or item.get("status") == "goal_committed"
            )
        ],
        issues=issues,
    )


def _rank_functional_locked_context_calls(
    call_ids: list[str],
    *,
    issues: Any,
) -> list[str]:
    """Order locked context by direct ticket relevance before prompt capping."""

    allowed = set(call_ids)
    ranked: list[str] = []
    if isinstance(issues, list):
        for detail_key, refs_are_results in (
            ("locked_result_refs", True),
            ("compatible_refs", True),
            ("locked_context_call_ids", False),
            ("context_call_ids", False),
        ):
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                details = issue.get("details")
                if not isinstance(details, dict):
                    continue
                values = details.get(detail_key, ())
                if not isinstance(values, (list, tuple)):
                    continue
                for value in values:
                    if not isinstance(value, str):
                        continue
                    call_id = (
                        value.rsplit(".", 1)[0]
                        if refs_are_results and "." in value
                        else value
                    )
                    if call_id in allowed:
                        ranked.append(call_id)
    return list(dict.fromkeys((*ranked, *call_ids)))


def _compact_functional_result_snapshot(
    snapshot: dict[str, Any],
    *,
    include_identity: bool,
) -> dict[str, Any] | None:
    return_name = snapshot.get("return")
    value_type = snapshot.get("type")
    if not isinstance(return_name, str) or not isinstance(value_type, str):
        return None
    result: dict[str, Any] = {
        "return": return_name,
        "type": value_type,
    }
    semantic_ref = snapshot.get("semantic_ref")
    if isinstance(semantic_ref, str) and semantic_ref:
        result["ref"] = semantic_ref
    if "value" in snapshot:
        value = _sanitize_functional_runtime_value(snapshot["value"])
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(encoded) <= _FUNCTIONAL_PROMPT_RESULT_VALUE_MAX_CHARS:
            result["value"] = value
        else:
            result["value_omitted_reason"] = "value_too_large_for_prompt"
    elif isinstance(snapshot.get("value_omitted_reason"), str):
        result["value_omitted_reason"] = snapshot["value_omitted_reason"]
    actual_form = snapshot.get("actual_form")
    if isinstance(actual_form, str) and actual_form:
        result["form"] = actual_form
    free_parameters = snapshot.get("free_parameters")
    if isinstance(free_parameters, list) and free_parameters:
        result["free"] = [
            item for item in free_parameters if isinstance(item, str)
        ]
    closure = snapshot.get("symbolic_closure")
    if isinstance(closure, dict):
        prompt_closure = _sanitize_functional_runtime_value({
            key: value
            for key, value in closure.items()
            if key
            in {
                "target",
                "status",
                "value",
                "branches",
                "remaining_free",
                "equation_sources",
                "constraint_used",
            }
        })
        if prompt_closure.get("value") == result.get("value"):
            prompt_closure.pop("value", None)
        if prompt_closure:
            result["closure"] = prompt_closure
    object_roles = snapshot.get("object_roles")
    if value_type == "PathTransformation" and isinstance(object_roles, dict):
        prompt_roles = _sanitize_functional_runtime_value(object_roles)
        result["structure"] = {
            **prompt_roles,
            "moving_locus_available": "moving_locus" in object_roles,
        }
    elif include_identity:
        semantic_roles = snapshot.get("semantic_roles")
        if isinstance(semantic_roles, list) and semantic_roles:
            result["roles"] = [
                item for item in semantic_roles if isinstance(item, str)
            ]
        if isinstance(object_roles, dict) and object_roles:
            result["identity"] = _sanitize_functional_runtime_value(object_roles)
    _audit_prompt_safe_runtime_result(result)
    return result


def _sanitize_functional_runtime_value(value: Any) -> Any:
    """Remove typed runtime addresses while preserving student-meaningful values."""

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            if (
                str(key).endswith("_ref")
                and isinstance(child, str)
                and _FUNCTIONAL_INTERNAL_REF_RE.search(child)
            ):
                continue
            result[str(key)] = _sanitize_functional_runtime_value(child)
        return result
    if isinstance(value, list):
        return [_sanitize_functional_runtime_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_functional_runtime_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_functional_ticket_value(value)
    return value


def _audit_prompt_safe_runtime_result(value: Mapping[str, Any]) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if _FUNCTIONAL_INTERNAL_REF_RE.search(serialized):
        raise ValueError(
            "planner.runtime_prompt_projection_drift: retry result exposes "
            "an internal runtime reference"
        )


def _functional_identity_issue_calls(issues: Any) -> set[str]:
    if not isinstance(issues, list):
        return set()
    result: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        code = str(issue.get("code", ""))
        details = issue.get("details")
        identity_related = (
            "identity" in code
            or "role" in code
            or (
                isinstance(details, dict)
                and any(
                    "identity" in str(key) or "role" in str(key)
                    for key in details
                )
            )
        )
        if not identity_related:
            continue
        step_id = issue.get("step_id")
        if isinstance(step_id, str):
            result.add(step_id)
        if isinstance(details, dict):
            for ref in details.get("actual_result_refs", ()):
                if isinstance(ref, str) and "." in ref:
                    result.add(ref.rsplit(".", 1)[0])
    return result


def _latest_functional_few_shot_selection(
    previous_attempts: list[Any],
) -> FunctionalFewShotSelectionRecord | None:
    """Restore the first attempt's internal selection without prompting it."""
    for attempt in reversed(previous_attempts):
        if not isinstance(attempt, dict):
            continue
        payload = attempt.get("functional_few_shot_selection")
        if payload is None:
            continue
        return FunctionalFewShotSelectionRecord.from_payload(payload)
    return None


def _functional_issue_tickets(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    symbol_labels = _functional_issue_symbol_labels(value)
    tickets: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        ticket = {
            key: child
            for key, child in item.items()
            if key not in {"step_id", "repair_target", "preserve_policy"}
        }
        details = ticket.get("details")
        if isinstance(details, dict):
            feedback = details.get("repair_feedback")
            if isinstance(feedback, dict):
                ticket["details"] = {
                    **details,
                    "repair_feedback": {
                        key: child
                        for key, child in feedback.items()
                        if key
                        not in {
                            "hints",
                            "compatible_refs",
                            "additional_repair_call_ids",
                        }
                    },
                }
        if isinstance(item.get("step_id"), str):
            ticket["call_id"] = item["step_id"]
        tickets.append(
            _sanitize_functional_ticket_value(
                ticket,
                symbol_labels=symbol_labels,
            )
        )
    return tickets


def _functional_issue_symbol_labels(
    issues: list[Any],
) -> dict[str, str]:
    """Collect prompt-safe labels emitted by the semantic state ledger."""
    result: dict[str, str] = {}
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        details = issue.get("details")
        if not isinstance(details, dict):
            continue
        states = details.get("unresolved_symbol_states")
        if not isinstance(states, list):
            continue
        for state in states:
            if not isinstance(state, dict):
                continue
            runtime_symbol = state.get("runtime_symbol")
            description = state.get("description")
            if (
                isinstance(runtime_symbol, str)
                and runtime_symbol
                and isinstance(description, str)
                and description
            ):
                result[runtime_symbol] = description
    return result


def _sanitize_functional_ticket_value(
    value: Any,
    *,
    symbol_labels: Mapping[str, str] | None = None,
) -> Any:
    """Project runtime handles in retry diagnostics back to short semantic refs."""
    if isinstance(value, dict):
        return {
            key: _sanitize_functional_ticket_value(
                child,
                symbol_labels=symbol_labels,
            )
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_functional_ticket_value(
                child,
                symbol_labels=symbol_labels,
            )
            for child in value
        ]
    if isinstance(value, str):
        for runtime_symbol, label in sorted(
            (symbol_labels or {}).items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            value = value.replace(runtime_symbol, label)
        if looks_like_canonical_ref(
            value,
            allowed_kinds=SEMANTIC_READ_KINDS,
        ):
            return value.rsplit(":", 1)[-1]
        return _FUNCTIONAL_INTERNAL_REF_RE.sub(
            _functional_internal_ref_replacement,
            value,
        )
    return value


_FUNCTIONAL_INTERNAL_REF_RE = re.compile(
    r"\b(?:point|line|segment|ray|function|symbol|angle|circle|polygon|fact|"
    r"answer|role):[A-Za-z0-9_@:-]+(?:\.[A-Za-z0-9_@:-]+)*"
)

def _functional_internal_ref_replacement(match: re.Match[str]) -> str:
    value = match.group(0)
    if value.startswith("role:"):
        return value.removeprefix("role:").split("@", 1)[0]
    return value.rsplit(":", 1)[-1]

def _functional_few_shot_plan(value: object) -> dict[str, Any]:
    _annotation, plan = split_functional_few_shot_asset(value)
    return plan


def _scoped_functional_few_shot_plan(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("plan"), dict):
        raise ValueError("scope-native FunctionalPlan example is malformed")
    return value["plan"]


class StrategyPromptRenderer:
    """Render the sole FunctionalPlan strategy prompt."""

    def __init__(self, template_dir: Path | str | None = None) -> None:
        self.template_dir = (
            Path(template_dir) if template_dir else _default_template_dir()
        )
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["pretty_json"] = _pretty_json
        self.env.filters["compact_json"] = _compact_json
        self.env.filters["functional_few_shot_plan"] = (
            _functional_few_shot_plan
        )
        self.env.filters["scoped_functional_few_shot_plan"] = (
            _scoped_functional_few_shot_plan
        )

    def render(self, payload: dict[str, Any]) -> StrategyPrompt:
        system = self.env.get_template("strategy-functional-system.jinja").render(
            output_json_schema=FUNCTIONAL_PLAN_JSON_SCHEMA,
        )
        user = self.env.get_template("strategy-functional-user.jinja").render(
            payload=payload,
        )
        return StrategyPrompt(system=system.strip(), user=user.strip())

    def render_scoped(self, payload: dict[str, Any]) -> StrategyPrompt:
        """Render the dedicated v2 authoring prompt for F5-F1 tests."""

        system = self.env.get_template(
            "strategy-functional-v2-system.jinja"
        ).render(output_json_schema=scoped_functional_plan_schema())
        user = self.env.get_template(
            "strategy-functional-v2-user.jinja"
        ).render(payload=payload)
        return StrategyPrompt(system=system.strip(), user=user.strip())


def build_strategy_probe_inputs(
    problem: ProblemIR,
    *,
    family_registry: FamilyRegistry = DEFAULT_FAMILY_REGISTRY,
) -> PlannerInputs:
    """构建 Phase 1 DeepSeek probe 所需的 PlannerInputs。

    Strategy prompt 消费 canonical ProblemIR 投影后的 LLM payload，因此这里不再
    构建 ``ContextInventory`` 的 visible paths / planning signals；保留空 inventory
    只是为了复用 ``PlannerInputs`` 这个输入包。
    """
    family = family_registry.match(problem)
    if family is None:
        raise ValueError(
            f"no solver family for pattern={problem.pattern}, type={problem.problem_type}"
        )
    specs = MethodSpecRegistry.load_from_code()
    question_goals = extract_question_goals(problem)
    return PlannerInputs(
        problem_id=problem.problem_id,
        family_spec=family,
        question_goals=question_goals,
        context_inventory=ContextInventory(),
        method_specs=specs,
        problem=problem,
        original_text=dict(problem.original_text),
        previous_errors=[],
    )

def write_strategy_debug_artifacts(
    debug_dir: Path | str,
    *,
    payload: dict[str, Any],
    prompt: StrategyPrompt,
    raw_response: str,
    report: Any | None,
    execution_diagnostic: FunctionalExecutionDiagnostic | None = None,
    planner_retry_state: Any | None = None,
    planner_state_context: PlannerStateContextDebugSource | None = None,
    llm_metadata: dict[str, Any] | None = None,
    functional_plan: Any | None = None,
    functional_reconciliation: Any | None = None,
    problem_authority: Any | None = None,
    problem_binding_catalog: ProblemPlanningBindingCatalog | None = None,
) -> None:
    """把 DeepSeek probe 的输入输出按来源落盘，方便人工 review prompt。"""
    target = Path(debug_dir)
    target.mkdir(parents=True, exist_ok=True)
    _clear_previous_debug_artifacts(target)
    (target / "prompt.system.md").write_text(prompt.system, encoding="utf-8")
    (target / "prompt.user.md").write_text(prompt.user, encoding="utf-8")
    source_keys = [
        "problem_planning_context",
        "strategy_principles",
        "functional_capability_catalog",
        "few_shot_examples",
        "functional_few_shot_selection",
        "previous_attempt_state",
    ]
    for key in source_keys:
        _write_json(target / f"payload.{key}.json", payload.get(key))
    _write_json(
        target / "problem-bundle-authority.json",
        (
            problem_authority.authority_payload()
            if problem_authority is not None
            else None
        ),
    )
    _write_json(
        target / "problem-planning-binding-catalog.json",
        (
            problem_binding_catalog.authority_payload()
            if problem_binding_catalog is not None
            else None
        ),
    )
    _write_json(
        target / "functional-plan.json",
        _to_jsonable(functional_plan),
    )
    context_payload = _planner_state_context_payload(planner_state_context)
    functional_reconciliation_payload = _to_jsonable(functional_reconciliation)
    context_state = (
        context_payload.get("state")
        if isinstance(context_payload, dict)
        else None
    )
    if isinstance(functional_reconciliation_payload, dict) and isinstance(
        context_state,
        dict,
    ):
        functional_reconciliation_payload = {
            **functional_reconciliation_payload,
            "student_step_placements": context_state.get(
                "student_step_placements",
                [],
            ),
            "student_scope_references": context_state.get(
                "student_scope_references",
                [],
            ),
        }
    _write_json(
        target / "functional-reconciliation-report.json",
        functional_reconciliation_payload,
    )
    retry_payload = _retry_state_payload(planner_retry_state)
    _write_json(target / "planner-retry-state.json", retry_payload)
    _write_json(
        target / "repair-suffix.json",
        retry_payload.get("repair_suffix_start") if retry_payload else None,
    )
    _write_json(
        target / "replay-reports.json",
        retry_payload.get("replay_reports") if retry_payload else None,
    )
    _write_json(target / "planner-state-context.json", context_payload)
    context_retry_memory = _context_retry_memory_payload(context_payload)
    # ``context-retry-memory`` is the context-owned source snapshot;
    # ``context-derived-retry-state`` is the LLM/debug compatibility projection
    # generated from that context plus the live stable prefix.
    _write_json(target / "context-retry-memory.json", context_retry_memory)
    _write_json(target / "context-derived-retry-state.json", retry_payload)
    _write_json(
        target / "state-rewrite-ledger.json",
        (
            planner_state_context.rewrite_ledger_payload
            if planner_state_context is not None
            else None
        ),
    )
    _write_json(
        target / "context-events.json",
        (
            planner_state_context.events_payload
            if planner_state_context is not None
            else None
        ),
    )
    _write_json(
        target / "output.schema.json",
        payload.get("output_json_schema", FUNCTIONAL_PLAN_JSON_SCHEMA),
    )
    (target / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    _write_json(target / "validation-report.json", _to_jsonable(report))
    function_binding_report: list[dict[str, Any]] | None = None
    macro_binding_report: list[dict[str, Any]] | None = None
    if execution_diagnostic is not None:
        _write_json(
            target / "execution-diagnostic.json",
            execution_diagnostic,
        )
        function_binding_report = _function_binding_report_payload(
            execution_diagnostic
        )
        macro_binding_report = _macro_binding_report_payload(
            execution_diagnostic
        )
    _write_json(
        target / "function-binding-report.json",
        function_binding_report,
    )
    _write_json(
        target / "function-adapter-failures.json",
        (
            [
                item for item in function_binding_report
                if item.get("status") == "failure"
            ]
            if function_binding_report is not None
            else None
        ),
    )
    _write_json(
        target / "macro-binding-report.json",
        macro_binding_report,
    )
    if llm_metadata is not None:
        _write_json(target / "llm-call.json", llm_metadata)


def _clear_previous_debug_artifacts(target: Path) -> None:
    """清理同一 probe 目录里的旧版 payload，避免人工 review 看到过期文件。"""
    for pattern in ("payload.*.json",):
        for path in target.glob(pattern):
            path.unlink()
    for name in (
        "prompt.system.md",
        "prompt.user.md",
        "output.schema.json",
        "context-semantic-read-catalog.json",
        "raw-response.txt",
        "validation-report.json",
        "execution-diagnostic.json",
        "function-binding-report.json",
        "function-adapter-failures.json",
        "function-adapter-fallbacks.json",
        "macro-binding-report.json",
        "macro-transform-report.json",
        "functional-plan.json",
        "functional-reconciliation-report.json",
        "planner-retry-state.json",
        "planner-state-context.json",
        "context-retry-memory.json",
        "context-derived-retry-state.json",
        "state-rewrite-ledger.json",
        "context-events.json",
        "repair-suffix.json",
        "replay-reports.json",
        "llm-call.json",
    ):
        path = target / name
        if path.exists():
            path.unlink()


def _retry_state_payload(value: Any | None) -> dict[str, Any] | None:
    """兼容 dataclass 或 dict 形态的 PlannerRetryState。"""
    if value is None:
        return None
    payload = _to_jsonable(value)
    return payload if isinstance(payload, dict) else None


def _planner_state_context_payload(value: Any | None) -> dict[str, Any] | None:
    """兼容 dataclass 或 dict 形态的 PlannerStateContext。"""
    if value is None:
        return None
    if hasattr(value, "to_payload"):
        payload = value.to_payload()
        return payload if isinstance(payload, dict) else None
    if isinstance(value, dict):
        return value
    return None


def _context_retry_memory_payload(
    context_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(context_payload, dict):
        return None
    state = context_payload.get("state")
    if not isinstance(state, dict):
        return None
    retry_memory = state.get("retry_memory")
    return retry_memory if isinstance(retry_memory, dict) else None


def _function_binding_report_payload(value: Any) -> list[dict[str, Any]] | None:
    """Return FunctionSpec adapter binding events from a diagnostic payload."""
    events = getattr(value, "function_binding_events", None)
    if events is None and isinstance(value, dict):
        events = value.get("function_binding_events")
    if events is None:
        return None
    payload = _to_jsonable(events)
    return payload if isinstance(payload, list) else None


def _macro_binding_report_payload(value: Any) -> list[dict[str, Any]] | None:
    """Return MacroSpec adapter binding events from a diagnostic payload."""
    events = getattr(value, "macro_binding_events", None)
    if events is None and isinstance(value, dict):
        events = value.get("macro_binding_events")
    if events is None:
        return None
    payload = _to_jsonable(events)
    return payload if isinstance(payload, list) else None


def _pretty_json(value: Any) -> str:
    """Jinja 过滤器：输出可读中文 JSON。"""
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _compact_json(value: Any) -> str:
    """Jinja 过滤器：为 LLM prompt 输出确定性的紧凑 JSON。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _write_json(path: Path, value: Any) -> None:
    """写入 pretty JSON。"""
    path.write_text(_pretty_json(_to_jsonable(value)) + "\n", encoding="utf-8")


def _to_jsonable(value: Any) -> Any:
    """把 dataclass/tuple 转成 JSON 友好对象。"""
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _default_template_dir() -> Path:
    """定位 internal/llm-prompts，避免硬编码固定 parents 层级。"""
    return repo_root(Path(__file__)) / "internal" / "llm-prompts"
