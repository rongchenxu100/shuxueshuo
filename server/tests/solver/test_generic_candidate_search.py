from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSelectionSpec,
    FunctionalPlanFragment,
    GenericCandidateSearchService,
    SearchCandidate,
    VerifiedSubplanSearchError,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalStep,
)


pytestmark = pytest.mark.solver_contract


def _candidate(
    candidate_id: str,
    *,
    step_count: int = 1,
    complexity: int = 0,
) -> SearchCandidate:
    steps = tuple(
        ScopedFunctionalStep(
            step_id=f"{candidate_id}_{index}",
            capability_id="distance_between_points",
            args={"p1": ("A",), "p2": ("B",)},
            return_bindings={},
            return_expectations={},
        )
        for index in range(step_count)
    )
    return SearchCandidate(
        candidate_id=candidate_id,
        fragment=FunctionalPlanFragment(
            source="macro",
            scope_id="ii",
            steps=steps,
            exports={"value": (steps[-1].step_id, "distance")},
        ),
        role_bindings={"moving_point": candidate_id},
        strategy_id="test",
        symbolic_complexity=complexity,
    )


def _passed(candidate: SearchCandidate, value: str = "same") -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate.candidate_id,
        True,
        standard_outputs={"value": value},
        shadow_execution_signature=f"shadow:{candidate.candidate_id}",
    )


def test_unique_runtime_valid_fragment_wins_without_search_clean_replay() -> None:
    candidates = (_candidate("invalid"), _candidate("valid"))

    def evaluate(candidate):
        if candidate.candidate_id == "invalid":
            return CandidateEvaluation(
                "invalid",
                False,
                failure_code="predicate_false",
            )
        return _passed(candidate)

    winner, report, shadow_winner = GenericCandidateSearchService().search(
        macro_id="macro",
        candidates=candidates,
        evaluator=evaluate,
        max_candidates=4,
    )

    assert winner.candidate_id == "valid"
    assert report.winner_candidate_id == "valid"
    assert shadow_winner.output_signature == report.evaluations[1].output_signature


def test_equivalent_fragments_use_step_count_then_complexity_tie_break() -> None:
    candidates = (
        _candidate("long", step_count=2),
        _candidate("complex", complexity=3),
        _candidate("simple", complexity=0),
    )

    winner, report, _shadow_winner = GenericCandidateSearchService().search(
        macro_id="macro",
        candidates=candidates,
        evaluator=_passed,
        max_candidates=4,
    )

    assert winner.candidate_id == "simple"
    assert set(report.equivalent_candidate_ids) == {
        "long",
        "complex",
        "simple",
    }


def test_non_equivalent_valid_fragments_fail_loud() -> None:
    candidates = (_candidate("first"), _candidate("second"))

    with pytest.raises(VerifiedSubplanSearchError) as error:
        GenericCandidateSearchService().search(
            macro_id="macro",
            candidates=candidates,
            evaluator=lambda item: _passed(item, item.candidate_id),
            max_candidates=4,
        )

    assert error.value.code == "functional.macro_search_ambiguous"
    assert error.value.retryable


def test_configuration_exception_is_not_a_math_failure() -> None:
    candidate = _candidate("candidate")

    with pytest.raises(VerifiedSubplanSearchError) as configuration:
        GenericCandidateSearchService().search(
            macro_id="macro",
            candidates=(candidate,),
            evaluator=lambda _item: (_ for _ in ()).throw(KeyError("broken")),
            max_candidates=4,
        )
    assert configuration.value.code == "planner.macro_candidate_configuration_error"
    assert not configuration.value.retryable



def test_minimize_uses_fragment_export_and_keeps_equal_minima_equivalent() -> None:
    candidates = (
        _candidate("large"),
        _candidate("small-a", complexity=2),
        _candidate("small-b", complexity=1),
    )
    outputs = {"large": "5", "small-a": "3", "small-b": "3"}

    winner, report, shadow_winner = GenericCandidateSearchService().search(
        macro_id="macro",
        candidates=candidates,
        evaluator=lambda item: _passed(item, outputs[item.candidate_id]),
        max_candidates=4,
        selection=CandidateSelectionSpec("minimize", "value"),
    )

    assert winner.candidate_id == "small-b"
    assert shadow_winner.standard_outputs["value"] == "3"
    assert set(report.equivalent_candidate_ids) == {"small-a", "small-b"}
