from __future__ import annotations

import pytest

from shuxueshuo_server.solver.contracts import TypedValue
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.predicate_condition_publication import (
    PredicateConditionPublicationService,
    derived_condition_id,
)

from _problem_planning_support import planning_binding_fixture


pytestmark = pytest.mark.solver_contract


class _PredicateBranch:
    def __init__(self, passed: bool) -> None:
        self.passed = passed
        self.writes = []

    def read_path(self, *_args, **_kwargs):
        return TypedValue("Boolean", self.passed, source="predicate")

    def write_path(self, path, value, **_kwargs):
        self.writes.append((path, value))


def _publication_inputs(tmp_path, *, passed: bool):
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    capability = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    ).get("verify_distance_equality")
    assert capability is not None
    function_return = next(
        item for item in capability.source.returns if item.output_key == "verified"
    )
    invocation = MethodInvocation(
        invocation_id="verify_distance.equal",
        method_id="verify_distance_equality",
        scope="ii",
        outputs={"verified": "$step.verify_distance.temp.verified"},
    )
    plan = StepPlan(
        step_id="verify_distance",
        goal=StepGoal("verify", "Condition", "condition", "ii"),
        scope="ii",
        invocations=[invocation],
        promote_outputs={
            "$step.verify_distance.temp.verified": (
                "$question.ii.conditions.distance_equality"
            )
        },
    )
    allocation = FunctionalReturnAllocation(
        call_id="verify_distance",
        return_name=function_return.name,
        handle="condition:verify_distance:distance_equality",
        runtime_type="Condition",
        valid_scope="ii",
        state_slot_id="condition:verify_distance:distance_equality",
        object_ref=None,
        identity_policy="fresh_result",
        write_mode="create",
    )
    resolved = {
        role: (
            ResolvedFunctionalValue(
                handle=f"point:{ref}",
                runtime_type="Point",
                valid_scope="problem",
                object_ref=ref,
            ),
        )
        for role, ref in {
            "first_start": "A",
            "first_end": "B",
            "second_start": "C",
            "second_end": "D",
        }.items()
    }
    return fixture, capability, plan, allocation, resolved, _PredicateBranch(passed)


def test_true_predicate_publishes_exact_scope_local_condition(tmp_path) -> None:
    fixture, capability, plan, allocation, resolved, branch = (
        _publication_inputs(tmp_path, passed=True)
    )

    result = PredicateConditionPublicationService().materialize(
        call_id="verify_distance",
        capability=capability,
        plans=(plan,),
        allocations=(allocation,),
        resolved_args=resolved,
        branch=branch,
        method_specs=fixture[3].method_specs,
    )

    assert result.outcomes[0].passed
    assert len(result.conditions) == 1
    assert result.conditions[0].scope_id == "ii"
    assert result.conditions[0].condition_id == derived_condition_id(
        call_id="verify_distance",
        return_name=allocation.return_name,
        condition_kind="distance_equality",
        scope_id="ii",
    )
    assert branch.writes[0][1].type == "Condition"


def test_false_predicate_never_publishes_declared_condition(tmp_path) -> None:
    fixture, capability, plan, allocation, resolved, branch = (
        _publication_inputs(tmp_path, passed=False)
    )

    with pytest.raises(StatelessMethodError) as error:
        PredicateConditionPublicationService().materialize(
            call_id="verify_distance",
            capability=capability,
            plans=(plan,),
            allocations=(allocation,),
            resolved_args=resolved,
            branch=branch,
            method_specs=fixture[3].method_specs,
        )

    assert error.value.code == "functional.predicate_false"
    assert branch.writes == []
