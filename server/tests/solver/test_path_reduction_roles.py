from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.path_reduction_roles import (
    PathReductionRoleError,
    PathReductionRoleResolver,
)


def _registry(
    *,
    duplicate_relation: bool = False,
    legacy_text: bool = False,
) -> CanonicalHandleRegistry:
    points = {
        "point:part:Anchor_Main",
        "point:part:Moving_Left",
        "point:part:Joint_12",
        "point:part:Moving_Right",
        "point:part:Fixed_End",
        "point:part:Fixed_Path",
    }
    segments = {
        "segment:part:Track_Left",
        "segment:part:Track_Right",
    }
    path_target = "fact:part:path_goal"
    first_membership = "fact:part:left_membership"
    second_membership = "fact:part:right_membership"
    relation = "fact:part:coupled_lengths"
    fact_types = {
        path_target: "path_minimum_target",
        first_membership: "segment_membership",
        second_membership: "segment_membership",
        relation: "segment_relation",
    }
    fact_payloads = {
        path_target: {
            "terms": [
                [
                    "point:part:Moving_Left",
                    "point:part:Moving_Right",
                ],
                [
                    "point:part:Fixed_Path",
                    "point:part:Moving_Right",
                ],
            ]
        },
        first_membership: {
            "point": "point:part:Moving_Left",
            "segment": "segment:part:Track_Left",
        },
        second_membership: {
            "point": "point:part:Moving_Right",
            "segment": "segment:part:Track_Right",
        },
        relation: {
            "left_term": {
                "scale": "1",
                "segment": [
                    "point:part:Anchor_Main",
                    "point:part:Moving_Left",
                ],
            },
            "right_term": {
                "scale": "sqrt(3)",
                "segment": [
                    "point:part:Fixed_End",
                    "point:part:Moving_Right",
                ],
            },
        },
    }
    if legacy_text:
        fact_payloads[path_target] = {
            "path": (
                "Moving_LeftMoving_Right+"
                "Fixed_PathMoving_Right"
            )
        }
        fact_payloads[relation] = {
            "left": "Anchor_MainMoving_Left",
            "right": "sqrt(3)*Fixed_EndMoving_Right",
        }
    if duplicate_relation:
        duplicate = "fact:part:second_coupled_lengths"
        fact_types[duplicate] = "segment_relation"
        fact_payloads[duplicate] = dict(fact_payloads[relation])
    handles = set(fact_types)
    return CanonicalHandleRegistry(
        scope_ids=frozenset({"problem", "part"}),
        entity_handles=frozenset((*points, *segments)),
        fact_handles=frozenset(handles),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "part": "problem"},
        fact_types=fact_types,
        handle_valid_scopes={
            **{handle: "part" for handle in points | segments},
            **{handle: "part" for handle in handles},
        },
        entity_payloads={
            "segment:part:Track_Left": {
                "endpoints": [
                    "point:part:Anchor_Main",
                    "point:part:Joint_12",
                ]
            },
            "segment:part:Track_Right": {
                "endpoints": [
                    "point:part:Joint_12",
                    "point:part:Fixed_End",
                ]
            },
        },
        fact_payloads=fact_payloads,
    )


def test_path_reduction_roles_use_structured_graph_with_multichar_names() -> None:
    roles = PathReductionRoleResolver.resolve(
        path_target="fact:part:path_goal",
        scope_id="part",
        registry=_registry(),
    )

    assert roles.first_moving_point == "point:part:Moving_Left"
    assert roles.second_moving_point == "point:part:Moving_Right"
    assert roles.first_segment_start == "point:part:Anchor_Main"
    assert roles.joint_point == "point:part:Joint_12"
    assert roles.second_segment_end == "point:part:Fixed_End"
    assert roles.transformed_fixed_endpoint == "point:part:Fixed_Path"
    assert roles.first_track == "segment:part:Track_Left"
    assert roles.second_track == "segment:part:Track_Right"


def test_path_reduction_legacy_text_uses_visible_multichar_point_names() -> None:
    roles = PathReductionRoleResolver.resolve(
        path_target="fact:part:path_goal",
        scope_id="part",
        registry=_registry(legacy_text=True),
    )

    assert roles.first_moving_point == "point:part:Moving_Left"
    assert roles.second_moving_point == "point:part:Moving_Right"
    assert roles.first_segment_start == "point:part:Anchor_Main"
    assert roles.second_segment_end == "point:part:Fixed_End"


def test_path_reduction_roles_reject_ambiguous_binding_relations() -> None:
    with pytest.raises(PathReductionRoleError) as exc_info:
        PathReductionRoleResolver.resolve(
            path_target="fact:part:path_goal",
            scope_id="part",
            registry=_registry(duplicate_relation=True),
        )

    assert exc_info.value.code == "path_reduction.binding_relation_ambiguous"
