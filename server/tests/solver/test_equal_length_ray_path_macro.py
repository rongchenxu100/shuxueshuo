from __future__ import annotations

import sympy as sp
import pytest

from shuxueshuo_server.solver.runtime.equal_length_ray_path_search import (
    EqualLengthRayPathSearchError,
    search_segment_path_minimum,
)
from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
    EqualLengthRayRoleError,
    build_equal_length_ray_role_candidates,
)


@pytest.mark.parametrize(
    ("fixed", "auxiliary", "start", "end", "strategy", "minimum"),
    (
        ((-1, 0), (1, 0), (0, -1), (0, 1), "direct_intersection", 2),
        (
            (0, 1),
            (2, 1),
            (0, 0),
            (2, 0),
            "reflection_straightening",
            2 * sp.sqrt(2),
        ),
        (
            (2, 1),
            (3, 1),
            (0, 0),
            (1, 0),
            "segment_endpoint_1",
            sp.sqrt(2) + sp.sqrt(5),
        ),
    ),
)
def test_path_search_proves_direct_reflection_and_endpoint_winners(
    fixed,
    auxiliary,
    start,
    end,
    strategy,
    minimum,
) -> None:
    result = search_segment_path_minimum(
        fixed_point=fixed,
        auxiliary_point=auxiliary,
        segment_start=start,
        segment_end=end,
    )

    assert result.winner.strategy == strategy
    assert sp.simplify(result.winner.expression - minimum) == 0
    assert result.winner.feasible is True


def test_equivalent_endpoint_winners_use_stable_candidate_id() -> None:
    first = search_segment_path_minimum(
        fixed_point=(0, 0),
        auxiliary_point=(1, 0),
        segment_start=(0, 0),
        segment_end=(1, 0),
    )
    second = search_segment_path_minimum(
        fixed_point=(0, 0),
        auxiliary_point=(1, 0),
        segment_start=(0, 0),
        segment_end=(1, 0),
    )

    assert first.winner.expression == 1
    assert first.winner.candidate_id == second.winner.candidate_id


def test_parameter_branch_without_proved_attainment_fails_loud() -> None:
    parameter = sp.Symbol("p", real=True)

    with pytest.raises(EqualLengthRayPathSearchError) as caught:
        search_segment_path_minimum(
            fixed_point=(parameter, 1),
            auxiliary_point=(parameter + 1, 1),
            segment_start=(0, 0),
            segment_end=(1, 0),
        )

    assert caught.value.code == "functional.path_minimum_attainment_unproven"
    assert caught.value.retryability == "planner_repairable"


def test_non_equivalent_proved_winners_are_reported_as_ambiguous(
    monkeypatch,
) -> None:
    import shuxueshuo_server.solver.runtime.equal_length_ray_path_search as search

    monkeypatch.setattr(search, "_prove_nonnegative", lambda *_args, **_kwargs: True)

    with pytest.raises(EqualLengthRayPathSearchError) as caught:
        search_segment_path_minimum(
            fixed_point=(0, 1),
            auxiliary_point=(2, 1),
            segment_start=(0, 0),
            segment_end=(2, 0),
        )

    assert caught.value.code == "functional.macro_search_ambiguous"


def test_role_candidate_builder_enforces_declared_budget() -> None:
    facts = tuple((f"fact:{index}", {}) for index in range(3))

    with pytest.raises(EqualLengthRayRoleError) as caught:
        build_equal_length_ray_role_candidates(
            ray_facts=facts,
            segment_facts=facts,
            equal_facts=facts,
            target_facts=facts,
            entity_payload=lambda _handle: {},
            visible_point_handles=(),
            resolve_point_name=lambda name: name,
            max_candidates=32,
        )

    assert caught.value.code == "equal_length_role_candidate_budget_exceeded"
