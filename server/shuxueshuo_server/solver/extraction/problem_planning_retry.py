"""Goal-scoped retry view derived from authenticated planning authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    FrozenJson,
    freeze_json,
    stable_hash,
    thaw_json,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
)


@dataclass(frozen=True)
class ProblemPlanningRetryProjection:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    repair_call_ids: tuple[str, ...]
    goal_unit_ids: tuple[str, ...]
    input_source_unit_ids: tuple[str, ...]
    projection_signature: str
    prompt_payload: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        frozen = freeze_json(self.prompt_payload)
        if not isinstance(frozen, Mapping):
            raise TypeError("Problem retry prompt payload must be an object")
        object.__setattr__(self, "prompt_payload", frozen)

    def authority_payload(self) -> dict[str, Any]:
        return {
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "repair_call_ids": list(self.repair_call_ids),
            "goal_unit_ids": list(self.goal_unit_ids),
            "input_source_unit_ids": list(self.input_source_unit_ids),
            "projection_signature": self.projection_signature,
        }

    def to_prompt_payload(self) -> dict[str, Any]:
        return thaw_json(self.prompt_payload)


class ProblemPlanningRetryProjector:
    def project(
        self,
        planning_context: ProblemPlanningContext,
        checkpoint: FunctionalRetryGraphCheckpoint,
        repair_call_ids: Sequence[str],
    ) -> ProblemPlanningRetryProjection:
        authority = checkpoint.problem_authority
        if authority is None:
            raise _error(
                "planner.retry_problem_source_binding_drift",
                "retry checkpoint has no Problem authority",
            )
        if (
            authority.planning_context_id
            != planning_context.planning_context_id
            or authority.problem_revision_id
            != planning_context.problem_revision_id
            or authority.problem_semantic_hash
            != planning_context.problem_semantic_hash
        ):
            raise _error(
                "planner.retry_problem_revision_drift",
                "retry checkpoint and PlanningContext revisions differ",
            )
        ordered_calls = tuple(dict.fromkeys(repair_call_ids))
        if not ordered_calls:
            raise _error(
                "planner.problem_planning_context_invalid",
                "repair cone has no calls",
            )
        authorities_by_call = {
            item.canonical_call_id: item
            for item in checkpoint.problem_call_authorities
        }
        missing = tuple(
            call_id
            for call_id in ordered_calls
            if call_id not in authorities_by_call
        )
        if missing:
            raise _error(
                "planner.retry_problem_source_binding_drift",
                "repair calls have no authenticated Problem authority: "
                f"{', '.join(missing)}",
            )
        goal_ids = tuple(
            dict.fromkeys(
                goal_id
                for call_id in ordered_calls
                for goal_id in authorities_by_call[call_id].goal_unit_ids
            )
        )
        source_ids = tuple(
            sorted(
                {
                    source_id
                    for call_id in ordered_calls
                    for source_id in authorities_by_call[
                        call_id
                    ].input_source_unit_ids
                }
            )
        )
        prompt_payload = planning_context.to_prompt_payload(
            goal_unit_ids=goal_ids,
        )
        _audit_prompt_payload(prompt_payload, planning_context=planning_context)
        signature_payload = {
            "planning_context_id": planning_context.planning_context_id,
            "problem_revision_id": planning_context.problem_revision_id,
            "problem_semantic_hash": planning_context.problem_semantic_hash,
            "repair_call_ids": list(ordered_calls),
            "goal_unit_ids": list(goal_ids),
            "input_source_unit_ids": list(source_ids),
            "prompt_payload": prompt_payload,
        }
        return ProblemPlanningRetryProjection(
            planning_context_id=planning_context.planning_context_id,
            problem_revision_id=planning_context.problem_revision_id,
            problem_semantic_hash=planning_context.problem_semantic_hash,
            repair_call_ids=ordered_calls,
            goal_unit_ids=goal_ids,
            input_source_unit_ids=source_ids,
            projection_signature=stable_hash(signature_payload),
            prompt_payload=prompt_payload,
        )


class ProblemPlanningRetryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"planner_configuration_error: {code}: {message}")


def _audit_prompt_payload(
    payload: Mapping[str, Any],
    *,
    planning_context: ProblemPlanningContext,
) -> None:
    stable_hash(payload)
    forbidden_keys = {
        "artifact_id",
        "authority_token",
        "bundle_authority_token",
        "math_object_id",
        "planning_context_id",
        "problem_revision_id",
        "problem_semantic_hash",
        "runtime_node_id",
        "source_unit_id",
        "source_unit_ids",
        "state_version_id",
    }
    forbidden_key_tokens = {
        key.replace("_", "") for key in forbidden_keys
    }
    forbidden_values = {
        planning_context.planning_context_id,
        planning_context.problem_revision_id,
        planning_context.problem_semantic_hash,
        *(
            unit_id
            for authority in planning_context.ref_authorities.values()
            for unit_id in authority.source_unit_ids
        ),
        *(
            authority.runtime_node_id
            for authority in planning_context.ref_authorities.values()
        ),
    }

    def visit(
        value: Any,
        path: str,
        *,
        authored_source_text: bool = False,
    ) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).lower()
                key_token = "".join(
                    character
                    for character in normalized
                    if character.isalnum()
                )
                if key_token in forbidden_key_tokens:
                    raise _error(
                        "planner.problem_scope_visibility_drift",
                        "Goal retry prompt exposes internal field "
                        f"{path}.{key}",
                    )
                visit(
                    item,
                    f"{path}.{key}",
                    authored_source_text=(normalized == "source_text"),
                )
            return
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes),
        ):
            for index, item in enumerate(value):
                visit(
                    item,
                    f"{path}[{index}]",
                    authored_source_text=authored_source_text,
                )
            return
        if (
            isinstance(value, str)
            and not authored_source_text
            and value in forbidden_values
        ):
            raise _error(
                "planner.problem_scope_visibility_drift",
                "Goal retry prompt exposes internal authority value at "
                f"{path}",
            )

    visit(payload, "$")


def _error(code: str, message: str) -> ProblemPlanningRetryError:
    return ProblemPlanningRetryError(code, message)


__all__ = [
    "ProblemPlanningRetryError",
    "ProblemPlanningRetryProjection",
    "ProblemPlanningRetryProjector",
]
