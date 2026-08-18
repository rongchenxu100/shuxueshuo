from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.family.models import MacroSearchSpec
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroCandidateEvaluation,
    MacroExecutionCandidate,
    MacroRuntimeSearchError,
    MacroRuntimeSearchReport,
    MacroRuntimeSearchService,
    macro_runtime_search_report_schema,
)


SPEC = MacroSearchSpec(
    searchable_roles=("moving_point",),
    candidate_builder_id="path_role_assignments",
    validation_policy_id="path_equivalence_and_provenance",
    max_candidates=4,
)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _candidate(
    candidate_id: str,
    point: str,
    *,
    call_count: int = 1,
    complexity: int = 1,
) -> MacroExecutionCandidate:
    return MacroExecutionCandidate(
        candidate_id,
        {"moving_point": point},
        call_count=call_count,
        symbolic_complexity=complexity,
    )


def _evaluator(
    outcomes: dict[str, tuple[bool, str | None]],
    observed: list[str] | None = None,
):
    def evaluate(candidate: MacroExecutionCandidate) -> MacroCandidateEvaluation:
        if observed is not None:
            observed.append(candidate.candidate_id)
        passed, signature = outcomes[candidate.candidate_id]
        return MacroCandidateEvaluation(
            candidate.candidate_id,
            passed,
            signature,
            ("method_checks", "macro_postcondition"),
        )

    return evaluate


def test_authored_role_is_tried_first_and_kept_when_runtime_valid() -> None:
    observed: list[str] = []
    winner, report = MacroRuntimeSearchService().search(
        macro_id="path_macro",
        spec=SPEC,
        candidates=(_candidate("candidate-g", "G"), _candidate("candidate-e", "E")),
        authored_roles={"moving_point": "G"},
        evaluator=_evaluator(
            {
                "candidate-g": (True, "same-result"),
                "candidate-e": (False, None),
            },
            observed,
        ),
    )

    assert observed[0] == "candidate-g"
    assert winner.candidate_id == "candidate-g"
    assert report.role_resolutions[0].corrected is False
    assert report.role_resolutions[0].chosen_ref == "G"


def test_unique_runtime_valid_candidate_corrects_llm_role_hint() -> None:
    winner, report = MacroRuntimeSearchService().search(
        macro_id="path_macro",
        spec=SPEC,
        candidates=(_candidate("candidate-e", "E"), _candidate("candidate-g", "G")),
        authored_roles={"moving_point": "E"},
        evaluator=_evaluator(
            {
                "candidate-e": (False, None),
                "candidate-g": (True, "verified-G"),
            }
        ),
    )

    assert winner.roles == {"moving_point": "G"}
    assert report.role_resolutions[0].authored_ref == "E"
    assert report.role_resolutions[0].chosen_ref == "G"
    assert report.role_resolutions[0].corrected is True


def test_equivalent_runtime_candidates_choose_smallest_verified_graph() -> None:
    winner, report = MacroRuntimeSearchService().search(
        macro_id="path_macro",
        spec=SPEC,
        candidates=(
            _candidate("large", "E", call_count=3, complexity=8),
            _candidate("small", "G", call_count=2, complexity=5),
            _candidate("complex", "H", call_count=2, complexity=9),
        ),
        authored_roles={},
        evaluator=_evaluator(
            {
                "large": (True, "equivalent-output"),
                "small": (True, "equivalent-output"),
                "complex": (True, "equivalent-output"),
            }
        ),
    )

    assert winner.candidate_id == "small"
    assert len(report.evaluations) == 3


def test_non_equivalent_runtime_candidates_fail_loud() -> None:
    with pytest.raises(MacroRuntimeSearchError) as exc_info:
        MacroRuntimeSearchService().search(
            macro_id="path_macro",
            spec=SPEC,
            candidates=(_candidate("candidate-e", "E"), _candidate("candidate-g", "G")),
            authored_roles={},
            evaluator=_evaluator(
                {
                    "candidate-e": (True, "result-E"),
                    "candidate-g": (True, "result-G"),
                }
            ),
        )

    assert exc_info.value.code == "functional.macro_search_ambiguous"
    assert exc_info.value.retryability == "planner_repairable"


def test_zero_valid_candidate_is_repairable_but_empty_or_over_budget_is_configuration() -> None:
    with pytest.raises(MacroRuntimeSearchError) as no_valid:
        MacroRuntimeSearchService().search(
            macro_id="path_macro",
            spec=SPEC,
            candidates=(_candidate("candidate-e", "E"),),
            authored_roles={"moving_point": "E"},
            evaluator=_evaluator({"candidate-e": (False, None)}),
        )
    assert no_valid.value.code == "functional.macro_search_no_valid_candidate"
    assert no_valid.value.retryability == "planner_repairable"

    with pytest.raises(MacroRuntimeSearchError) as empty:
        MacroRuntimeSearchService().search(
            macro_id="path_macro",
            spec=SPEC,
            candidates=(),
            authored_roles={},
            evaluator=_evaluator({}),
        )
    assert empty.value.code == "planner.macro_contract_invalid"
    assert empty.value.retryability == "configuration"

    with pytest.raises(MacroRuntimeSearchError) as over_budget:
        MacroRuntimeSearchService().search(
            macro_id="path_macro",
            spec=replace(SPEC, max_candidates=1),
            candidates=(_candidate("candidate-e", "E"), _candidate("candidate-g", "G")),
            authored_roles={},
            evaluator=_evaluator({}),
        )
    assert over_budget.value.code == "planner.macro_contract_invalid"
    assert over_budget.value.retryability == "configuration"


def test_candidate_must_cover_every_declared_searchable_role() -> None:
    spec = replace(SPEC, searchable_roles=("moving_point", "fixed_point"))

    with pytest.raises(MacroRuntimeSearchError) as exc_info:
        MacroRuntimeSearchService().search(
            macro_id="path_macro",
            spec=spec,
            candidates=(_candidate("candidate-g", "G"),),
            authored_roles={"moving_point": "G"},
            evaluator=_evaluator({"candidate-g": (True, "verified")}),
        )

    assert exc_info.value.code == "planner.macro_contract_invalid"
    assert exc_info.value.retryability == "configuration"
    assert exc_info.value.details["missing_roles"] == ["fixed_point"]


def test_search_report_round_trip_detects_authority_drift() -> None:
    _, report = MacroRuntimeSearchService().search(
        macro_id="path_macro",
        spec=SPEC,
        candidates=(_candidate("candidate-g", "G"),),
        authored_roles={"moving_point": "G"},
        evaluator=_evaluator({"candidate-g": (True, "verified")}),
    )

    assert MacroRuntimeSearchReport.from_payload(report.to_payload()) == report
    drifted = report.to_payload()
    drifted["macro_id"] = "different"
    with pytest.raises(ValueError, match="signature drift"):
        MacroRuntimeSearchReport.from_payload(drifted)


def test_search_report_schema_snapshot_matches_runtime_contract() -> None:
    snapshot = json.loads(
        (
            REPO_ROOT
            / "internal/schemas/macro-runtime-search-report.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert snapshot == macro_runtime_search_report_schema()


def test_candidate_evaluator_is_responsible_for_disposable_shadow_state() -> None:
    committed_state: list[str] = []
    branch_snapshots: list[tuple[str, ...]] = []

    def isolated(candidate: MacroExecutionCandidate) -> MacroCandidateEvaluation:
        branch = list(committed_state)
        branch.append(candidate.candidate_id)
        branch_snapshots.append(tuple(branch))
        return MacroCandidateEvaluation(
            candidate.candidate_id,
            True,
            "equivalent",
        )

    winner, _ = MacroRuntimeSearchService().search(
        macro_id="path_macro",
        spec=SPEC,
        candidates=(
            _candidate("candidate-a", "A", call_count=2),
            _candidate("candidate-b", "B", call_count=1),
        ),
        authored_roles={},
        evaluator=isolated,
    )

    assert committed_state == []
    assert branch_snapshots == [("candidate-a",), ("candidate-b",)]
    assert winner.candidate_id == "candidate-b"
