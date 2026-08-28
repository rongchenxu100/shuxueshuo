"""Independent scenario matrix for Functional Scope Retry vNext."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
from itertools import product
import json
from typing import Iterable, Literal


SCOPE_RETRY_GENERATOR_CONTRACT = "functional-scope-retry-generated/v1"

ScopeProfile = Literal["goal_local", "scope_owned"]
ScopeRepairMode = Literal[
    "valid",
    "stale_plan",
    "missing_scope",
    "foreign_scope",
    "missing_goal",
    "foreign_goal",
    "invalid_answer",
    "no_progress",
]


@dataclass(frozen=True)
class FunctionalScopeRetryScenario:
    scope_profile: ScopeProfile
    repair_mode: ScopeRepairMode
    reverse_mapping_order: bool
    retry_round: int
    variant: int
    schema_version: str = SCOPE_RETRY_GENERATOR_CONTRACT
    scenario_id: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCOPE_RETRY_GENERATOR_CONTRACT:
            raise ValueError("unsupported Functional Scope Retry scenario")
        if self.retry_round not in {1, 2}:
            raise ValueError("retry_round must be 1 or 2")
        if not 0 <= self.variant < 8:
            raise ValueError("variant must be in [0, 8)")
        if self.scenario_id:
            return
        digest = hashlib.sha256(
            json.dumps(
                self.to_payload(include_id=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        object.__setattr__(self, "scenario_id", f"fsr-{digest}")

    def to_payload(self, *, include_id: bool = True) -> dict[str, object]:
        payload = asdict(self)
        if not include_id:
            payload.pop("scenario_id", None)
        return payload


@dataclass(frozen=True)
class FunctionalScopeRetryExpectedOutcome:
    accepted: bool
    error_code: str | None
    no_progress: bool
    failed_candidate_ghost_write_count: int = 0
    open_scope_restore_leak_count: int = 0


class FunctionalScopeRetryReferenceModel:
    """Pure expected model; deliberately imports no production runtime."""

    _ERROR_CODES = {
        "stale_plan": "functional.scope_repair_stale_plan",
        "missing_scope": "functional.scope_repair_schema_invalid",
        "foreign_scope": "functional.scope_repair_schema_invalid",
        "missing_goal": "functional.scope_repair_schema_invalid",
        "foreign_goal": "functional.scope_repair_schema_invalid",
        "invalid_answer": "functional.scope_repair_answer_source_ambiguous",
    }

    def evaluate(
        self,
        scenario: FunctionalScopeRetryScenario,
    ) -> FunctionalScopeRetryExpectedOutcome:
        if scenario.repair_mode == "valid":
            return FunctionalScopeRetryExpectedOutcome(
                accepted=True,
                error_code=None,
                no_progress=False,
            )
        if scenario.repair_mode == "no_progress":
            return FunctionalScopeRetryExpectedOutcome(
                accepted=False,
                error_code=None,
                no_progress=True,
            )
        return FunctionalScopeRetryExpectedOutcome(
            accepted=False,
            error_code=self._ERROR_CODES[scenario.repair_mode],
            no_progress=False,
        )


def functional_scope_retry_scenarios(
) -> tuple[FunctionalScopeRetryScenario, ...]:
    scenarios = tuple(
        FunctionalScopeRetryScenario(
            scope_profile=scope_profile,
            repair_mode=repair_mode,
            reverse_mapping_order=reverse_mapping_order,
            retry_round=retry_round,
            variant=variant,
        )
        for (
            scope_profile,
            repair_mode,
            reverse_mapping_order,
            retry_round,
            variant,
        ) in product(
            ("goal_local", "scope_owned"),
            (
                "valid",
                "stale_plan",
                "missing_scope",
                "foreign_scope",
                "missing_goal",
                "foreign_goal",
                "invalid_answer",
                "no_progress",
            ),
            (False, True),
            (1, 2),
            range(8),
        )
    )
    if len(scenarios) != 512:
        raise AssertionError("Functional Scope Retry matrix is not 512 cases")
    if len({item.scenario_id for item in scenarios}) != len(scenarios):
        raise AssertionError("Functional Scope Retry scenario ids are not unique")
    return scenarios


def replay_functional_scope_retry_scenario(
    scenario_id: str,
) -> FunctionalScopeRetryScenario:
    return next(
        item
        for item in functional_scope_retry_scenarios()
        if item.scenario_id == scenario_id
    )


def functional_scope_retry_dimension_coverage(
    scenarios: Iterable[FunctionalScopeRetryScenario],
) -> dict[str, Counter[str]]:
    result: dict[str, Counter[str]] = {
        "scope_profile": Counter(),
        "repair_mode": Counter(),
        "reverse_mapping_order": Counter(),
        "retry_round": Counter(),
        "variant": Counter(),
    }
    for item in scenarios:
        result["scope_profile"][item.scope_profile] += 1
        result["repair_mode"][item.repair_mode] += 1
        result["reverse_mapping_order"][str(item.reverse_mapping_order)] += 1
        result["retry_round"][str(item.retry_round)] += 1
        result["variant"][str(item.variant)] += 1
    return result
