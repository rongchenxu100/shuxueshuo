from __future__ import annotations

from shuxueshuo_server.solver.runtime.return_object_authority import (
    ReturnObjectAuthorityResolver,
    ReturnRoleAuthorityResolver,
)


def test_return_object_authority_uses_first_nonempty_basis() -> None:
    result = ReturnObjectAuthorityResolver.resolve(
        explicit_return_bindings=("M",),
        goal_answer_targets=("E",),
        declared_identity_targets=("G",),
    )

    assert result.target_refs == frozenset(("M",))
    assert result.unique_target_ref == "M"
    assert result.basis == "explicit_return_binding"


def test_return_role_authority_solves_global_multi_return_constraints() -> None:
    result = ReturnRoleAuthorityResolver.resolve(
        {
            "point": ("axis_point", "curve_point"),
            "point_on_curve": ("curve_point",),
        }
    )

    assert result.unique
    assert dict(result.assignments) == {
        "point": "axis_point",
        "point_on_curve": "curve_point",
    }
    assert result.solution_count == 1


def test_return_role_authority_never_guesses_ambiguous_assignment() -> None:
    result = ReturnRoleAuthorityResolver.resolve(
        {
            "first": ("axis_point", "curve_point"),
            "second": ("axis_point", "curve_point"),
        }
    )

    assert not result.unique
    assert dict(result.assignments) == {}
    assert result.solution_count == 2


def test_return_role_authority_rejects_empty_candidate_set() -> None:
    result = ReturnRoleAuthorityResolver.resolve(
        {
            "point": (),
            "other": ("axis_point",),
        }
    )

    assert not result.unique
    assert result.solution_count == 0
    assert dict(result.assignments) == {}
