from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from shuxueshuo_server.solver.contracts import VerificationOutcome
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    verified_subplan_execution_schema,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSearchReport,
    FunctionalPlanFragment,
    MacroSearchSelection,
    SingleFragmentSelection,
    VerifiedSubplanCleanExecution,
    VerifiedSubplanExecution,
    VerifiedSubplanWitness,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalStep,
)


pytestmark = pytest.mark.solver_contract


def _execution() -> VerifiedSubplanExecution:
    step = ScopedFunctionalStep(
        step_id="distance",
        capability_id="distance_between_points",
        args={"p1": ("A",), "p2": ("B",)},
        return_bindings={},
        return_expectations={},
    )
    fragment = FunctionalPlanFragment(
        source="macro",
        scope_id="ii",
        steps=(step,),
        exports={"minimum_expression": ("distance", "distance")},
        blueprint_id="blueprint/v1",
    )
    evaluation = CandidateEvaluation(
        "candidate",
        True,
        standard_outputs={"minimum_expression": "sqrt(5)"},
        verification=(
            VerificationOutcome(
                passed=True,
                check_code="path_attainment",
                expected=True,
                observed=True,
            ),
        ),
        shadow_execution_signature="fragment:verified",
    )
    report = CandidateSearchReport(
        macro_id="path_macro",
        winner_candidate_id="candidate",
        evaluations=(evaluation,),
        equivalent_candidate_ids=("candidate",),
    )
    witness = VerifiedSubplanWitness(
        standard_entities={"fixed_point": "O"},
        standard_conditions={"attainment": "distance.path_attainment"},
        standard_results={"minimum_expression": "sqrt(5)"},
        provenance=({"step_id": "distance", "return": "distance"},),
    )
    clean = VerifiedSubplanCleanExecution(
        member_step_ids=("distance",),
        fragment_execution_signature="fragment:verified",
        exported_results={"minimum_expression": "sqrt(5)"},
        verification=evaluation.verification,
        provenance=({"step_id": "distance", "return": "distance"},),
    )
    return VerifiedSubplanExecution(
        plan_id="plan:v3",
        scope_id="ii",
        selected_fragment=fragment,
        selection=MacroSearchSelection(
            macro_id="path_macro",
            preparation_signature="preparation:v1",
            search_report=report,
        ),
        clean_execution=clean,
        witness=witness,
    )


def test_verified_subplan_round_trip_and_schema() -> None:
    execution = _execution()
    payload = execution.to_payload()

    assert not tuple(
        Draft202012Validator(
            verified_subplan_execution_schema()
        ).iter_errors(payload)
    )
    assert VerifiedSubplanExecution.from_payload(payload) == execution


def test_verified_subplan_signature_rejects_fragment_or_witness_drift() -> None:
    payload = deepcopy(_execution().to_payload())
    payload["witness"]["standard_results"]["minimum_expression"] = "3"

    with pytest.raises(ValueError, match="witness.*drift"):
        VerifiedSubplanExecution.from_payload(payload)


def test_llm_fragment_uses_single_selection_without_fake_search_report() -> None:
    macro_execution = _execution()
    fragment = FunctionalPlanFragment(
        source="llm",
        scope_id="ii",
        steps=macro_execution.selected_fragment.steps,
        exports=macro_execution.selected_fragment.exports,
        blueprint_id=macro_execution.selected_fragment.blueprint_id,
    )
    execution = VerifiedSubplanExecution(
        plan_id="plan:v3",
        scope_id="ii",
        selected_fragment=fragment,
        selection=SingleFragmentSelection(owner_ref="ii.minimum"),
        clean_execution=macro_execution.clean_execution,
        witness=macro_execution.witness,
    )

    payload = execution.to_payload()
    assert payload["selection"] == {
        "kind": "single_fragment",
        "source": "llm",
        "owner_ref": "ii.minimum",
    }
    assert "search_report" not in payload["selection"]
    assert VerifiedSubplanExecution.from_payload(payload) == execution
