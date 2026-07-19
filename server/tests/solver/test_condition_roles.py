from __future__ import annotations

from dataclasses import dataclass

import pytest

from shuxueshuo_server.solver.runtime.condition_roles import (
    ConditionRoleResolver,
    resolve_read_closed_right_angle_inputs,
    resolve_read_closed_right_angle_method_roles,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StrategyDraftValidationError,
)


@dataclass(frozen=True)
class _Binding:
    value_type: str
    path: str


class _Index:
    def __init__(
        self,
        *,
        payloads: dict[str, dict],
        fact_types: dict[str, str],
        bindings: dict[str, str],
        binding_paths: dict[str, str] | None = None,
    ) -> None:
        self.payloads = payloads
        self.fact_types = fact_types
        self.bindings = {
            handle: _Binding(
                value_type,
                (binding_paths or {}).get(handle, f"runtime:{handle}"),
            )
            for handle, value_type in bindings.items()
        }

    def binding_for(self, handle: str) -> _Binding:
        try:
            return self.bindings[handle]
        except KeyError as exc:
            raise StrategyDraftValidationError(
                f"binding_not_found: {handle}"
            ) from exc

    def fact_payload(self, handle: str) -> dict:
        return self.payloads[handle]


def _step(*reads: str) -> StepIntent:
    return StepIntent(
        scope_id="part",
        step_id="construct_target",
        goal_type="derive_constructed_point",
        target="fact:part:target_coordinate",
        recipe_hint="right_angle_equal_length_construct_and_select",
        strategy="construct and select",
        reads=reads,
        produces=(),
        reason="exercise structured roles",
    )


def _index(*, duplicate_constraint: bool = False) -> _Index:
    relation = "fact:part:relation_17"
    orientation = "fact:part:target_region"
    constraint = "fact:problem:parameter_domain"
    payloads = {
        relation: {
            "type": "right_angle_equal_length",
            "angle": [
                "point:part:Known_Point_12",
                "point:problem:Anchor_Main",
                "point:part:Target_Prime",
            ],
        },
        orientation: {
            "type": "orientation_constraint",
            "subject": "point:part:Target_Prime",
        },
        constraint: {
            "type": "symbol_constraint",
            "subject": "symbol:problem:t",
        },
    }
    fact_types = {
        relation: "right_angle_equal_length",
        orientation: "orientation_constraint",
        constraint: "symbol_constraint",
    }
    if duplicate_constraint:
        payloads["fact:part:second_parameter_domain"] = {
            "type": "symbol_constraint",
            "subject": "symbol:problem:t",
        }
        fact_types["fact:part:second_parameter_domain"] = "symbol_constraint"
    return _Index(
        payloads=payloads,
        fact_types=fact_types,
        bindings={
            "point:problem:Anchor_Main": "Point",
            "point:part:Known_Point_12": "Point",
            "point:part:Target_Prime": "PointRef",
        },
    )


def test_condition_roles_use_structured_payload_with_multichar_point_names() -> None:
    roles = ConditionRoleResolver.object_roles(
        "right_angle_equal_length",
        _index().fact_payload("fact:part:relation_17"),
    )

    resolved = ConditionRoleResolver.resolve_constructed_point_roles(
        roles,
        target_hints=("point:part:Target_Prime",),
        materialized_points=("point:part:Known_Point_12",),
    )

    assert resolved.anchor == "point:problem:Anchor_Main"
    assert resolved.reference == "point:part:Known_Point_12"
    assert resolved.target == "point:part:Target_Prime"


def test_read_closed_condition_inputs_do_not_search_outside_step_reads() -> None:
    with pytest.raises(
        StrategyDraftValidationError,
        match="right_angle_role_state_unavailable.*Target_Prime",
    ):
        resolve_read_closed_right_angle_inputs(
            _step(
                "fact:part:relation_17",
                "point:problem:Anchor_Main",
                "point:part:Known_Point_12",
                "fact:part:target_region",
                "symbol:problem:t",
                "fact:problem:parameter_domain",
            ),
            _index(),
        )


def test_read_closed_condition_inputs_reject_ambiguous_constraints() -> None:
    with pytest.raises(
        StrategyDraftValidationError,
        match="right_angle_parameter_constraint_read_ambiguous",
    ):
        resolve_read_closed_right_angle_inputs(
            _step(
                "fact:part:relation_17",
                "point:problem:Anchor_Main",
                "point:part:Known_Point_12",
                "point:part:Target_Prime",
                "fact:part:target_region",
                "symbol:problem:t",
                "fact:problem:parameter_domain",
                "fact:part:second_parameter_domain",
            ),
            _index(duplicate_constraint=True),
        )


def test_direct_method_roles_require_structured_relation() -> None:
    with pytest.raises(
        StrategyDraftValidationError,
        match="right_angle_relation_read_missing",
    ):
        resolve_read_closed_right_angle_method_roles(
            _step(
                "point:problem:Anchor_Main",
                "point:part:Known_Point_12",
                "point:part:Target_Prime",
            ),
            _index(),
        )


@pytest.mark.parametrize(
    "point_reads",
    (
        (
            "point:problem:Anchor_Main",
            "point:part:Known_Point_12",
            "point:part:Target_Prime",
        ),
        (
            "point:part:Known_Point_12",
            "point:part:Target_Prime",
            "point:problem:Anchor_Main",
        ),
    ),
)
def test_direct_method_roles_are_invariant_to_read_order(
    point_reads: tuple[str, ...],
) -> None:
    roles = resolve_read_closed_right_angle_method_roles(
        _step(
            "fact:part:relation_17",
            *point_reads,
        ),
        _index(),
    )

    assert roles.anchor == "point:problem:Anchor_Main"
    assert roles.reference == "point:part:Known_Point_12"
    assert roles.target == "point:part:Target_Prime"


def test_direct_method_roles_select_read_aliases_by_object_identity() -> None:
    relation = "fact:part:relation"
    anchor = "point:part:Anchor"
    reference = "point:part:Reference"
    target = "point:part:Target"
    anchor_state = "fact:part:Anchor_coordinate"
    reference_state = "fact:part:Reference_coordinate"
    index = _Index(
        payloads={
            relation: {
                "angle": [reference, anchor, target],
            },
            anchor_state: {"subject": anchor},
            reference_state: {"subject": reference},
        },
        fact_types={
            relation: "right_angle_equal_length",
            anchor_state: "point_coordinate",
            reference_state: "point_coordinate",
        },
        bindings={
            anchor: "PointRef",
            reference: "PointRef",
            target: "PointRef",
            anchor_state: "Point",
            reference_state: "Point",
        },
        binding_paths={
            anchor: "runtime:points.Anchor",
            anchor_state: "runtime:points.Anchor",
            reference: "runtime:points.Reference",
            reference_state: "runtime:points.Reference",
        },
    )

    roles = resolve_read_closed_right_angle_method_roles(
        _step(relation, reference_state, target, anchor_state),
        index,
    )

    assert roles == type(roles)(
        anchor=anchor_state,
        reference=reference_state,
        target=target,
    )
