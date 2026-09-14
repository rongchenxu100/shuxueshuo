"""Verified coordinate geometry for right-angle equal-length candidates.

The candidate Method deliberately returns both 90-degree rotations.  This
module can certify either the construction of *all* candidates or the geometry
of one downstream-selected branch by projecting endpoints to one
coordinate-parallel line through the right-angle vertex.

The witness is expressed entirely in semantic roles and coordinates.  Point
letters for the two perpendicular feet belong to the teaching projection
layer, where collisions with authored point names can be avoided.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.runtime.methods._common import (
    is_definitely_negative,
    is_definitely_negative_under_lower_bound,
    is_definitely_positive,
    is_definitely_positive_under_lower_bound,
)


def build_axis_projection_candidate_construction_witness(
    construction: Mapping[str, Any],
    constraint_context: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return one projection/congruence witness covering every candidate.

    ``constraint_context`` may supply a verified strict parameter lower bound
    so symbolic coordinate differences can be interpreted as ordinary segment
    lengths.  The selected point, if present in that context, is deliberately
    ignored: candidate construction must not depend on a later branch choice.
    """

    if construction.get("kind") != "right_angle_equal_length_rotation":
        return None
    try:
        anchor = _point(construction.get("anchor"))
        reference = _point(construction.get("reference"))
        candidates = tuple(
            _point(item) for item in _sequence(construction.get("candidates"))
        )
    except (TypeError, ValueError, sp.SympifyError):
        return None
    if len(candidates) < 2:
        return None

    known = tuple(sp.simplify(b - a) for a, b in zip(anchor, reference))
    for candidate in candidates:
        candidate_vector = tuple(
            sp.simplify(b - a) for a, b in zip(anchor, candidate)
        )
        if (
            sp.simplify(
                known[0] * candidate_vector[0]
                + known[1] * candidate_vector[1]
            )
            != 0
            or sp.simplify(
                known[0] ** 2
                + known[1] ** 2
                - candidate_vector[0] ** 2
                - candidate_vector[1] ** 2
            )
            != 0
        ):
            return None

    parameter, lower_bound = _strict_lower_bound_context(constraint_context)
    axes = ("x", "y") if sp.simplify(anchor[1]) == 0 else ("y", "x")
    for axis in axes:
        branch_witnesses = tuple(
            _witness_for_axis(
                axis=axis,
                anchor=anchor,
                reference=reference,
                selected=candidate,
                parameter=parameter,
                lower_bound=lower_bound,
            )
            for candidate in candidates
        )
        if any(item is None for item in branch_witnesses):
            continue
        verified = tuple(item for item in branch_witnesses if item is not None)
        first = verified[0]
        reference_lengths = {
            "anchor_to_projection": first["lengths"][
                "anchor_to_reference_projection"
            ],
            "reference_to_projection": first["lengths"][
                "reference_to_reference_projection"
            ],
        }
        return {
            "kind": "axis_projection_candidate_construction",
            "axis": axis,
            "projection_line": _projection_line(axis, anchor),
            "anchor": _string_point(anchor),
            "reference": _string_point(reference),
            "reference_projection": first["reference_projection"],
            "reference_lengths": reference_lengths,
            "candidate_branches": tuple(
                {
                    "point": _string_point(candidate),
                    "projection": item["selected_projection"],
                    "lengths": {
                        "anchor_to_projection": item["lengths"][
                            "anchor_to_selected_projection"
                        ],
                        "candidate_to_projection": item["lengths"][
                            "selected_to_selected_projection"
                        ],
                    },
                }
                for candidate, item in zip(candidates, verified, strict=True)
            ),
        }
    return None


def build_axis_projection_congruence_witness(
    construction: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a verified projection/congruence witness when applicable.

    A missing witness does not invalidate the rotation or selection.  It only
    means that this particular coordinate-projection teaching profile is not
    available, so callers may keep the ordinary rotation explanation.
    """

    if construction.get("kind") != "right_angle_equal_length_rotation":
        return None
    if selection.get("kind") != "quadrant_candidate_selection":
        return None
    try:
        anchor = _point(construction.get("anchor"))
        reference = _point(construction.get("reference"))
        selected = _point(selection.get("selected_point"))
        candidates = tuple(
            _point(item) for item in _sequence(construction.get("candidates"))
        )
    except (TypeError, ValueError, sp.SympifyError):
        return None
    if selected not in candidates and not any(
        _same_point(selected, item) for item in candidates
    ):
        return None

    known = tuple(sp.simplify(b - a) for a, b in zip(anchor, reference))
    chosen = tuple(sp.simplify(b - a) for a, b in zip(anchor, selected))
    if (
        sp.simplify(known[0] * chosen[0] + known[1] * chosen[1]) != 0
        or sp.simplify(
            known[0] ** 2
            + known[1] ** 2
            - chosen[0] ** 2
            - chosen[1] ** 2
        )
        != 0
    ):
        return None

    constraint = selection.get("parameter_constraint")
    if not isinstance(constraint, Mapping):
        constraint = {}
    parameter_name = str(selection.get("parameter") or "")
    parameter = sp.Symbol(parameter_name) if parameter_name else None
    lower_bound = _optional_expr(constraint.get("value"))
    strict_lower_bound = (
        parameter is not None
        and lower_bound is not None
        and str(constraint.get("operator") or "") == ">"
    )

    axes = ("x", "y") if sp.simplify(anchor[1]) == 0 else ("y", "x")
    for axis in axes:
        witness = _witness_for_axis(
            axis=axis,
            anchor=anchor,
            reference=reference,
            selected=selected,
            parameter=parameter if strict_lower_bound else None,
            lower_bound=lower_bound if strict_lower_bound else None,
        )
        if witness is not None:
            return {
                "kind": "axis_projection_congruence",
                "axis": axis,
                "projection_line": _projection_line(axis, anchor),
                "anchor": _string_point(anchor),
                "reference": _string_point(reference),
                "selected_point": _string_point(selected),
                "reference_projection": witness["reference_projection"],
                "selected_projection": witness["selected_projection"],
                "lengths": witness["lengths"],
                "equal_leg_pairs": (
                    {
                        "left": ("anchor", "reference_projection"),
                        "right": ("selected_point", "selected_projection"),
                        "length": witness["lengths"][
                            "anchor_to_reference_projection"
                        ],
                    },
                    {
                        "left": ("reference", "reference_projection"),
                        "right": ("anchor", "selected_projection"),
                        "length": witness["lengths"][
                            "reference_to_reference_projection"
                        ],
                    },
                ),
            }
    return None


def _witness_for_axis(
    *,
    axis: str,
    anchor: tuple[sp.Expr, sp.Expr],
    reference: tuple[sp.Expr, sp.Expr],
    selected: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol | None,
    lower_bound: sp.Expr | None,
) -> dict[str, Any] | None:
    if axis == "x":
        reference_projection = (reference[0], anchor[1])
        selected_projection = (selected[0], anchor[1])
        raw = {
            "anchor_to_reference_projection": reference[0] - anchor[0],
            "reference_to_reference_projection": reference[1] - anchor[1],
            "anchor_to_selected_projection": selected[0] - anchor[0],
            "selected_to_selected_projection": selected[1] - anchor[1],
        }
    else:
        reference_projection = (anchor[0], reference[1])
        selected_projection = (anchor[0], selected[1])
        raw = {
            "anchor_to_reference_projection": reference[1] - anchor[1],
            "reference_to_reference_projection": reference[0] - anchor[0],
            "anchor_to_selected_projection": selected[1] - anchor[1],
            "selected_to_selected_projection": selected[0] - anchor[0],
        }
    lengths = {
        key: _positive_length(value, parameter=parameter, lower_bound=lower_bound)
        for key, value in raw.items()
    }
    if any(value is None or sp.simplify(value) == 0 for value in lengths.values()):
        return None
    assert all(value is not None for value in lengths.values())
    if (
        sp.simplify(
            lengths["anchor_to_reference_projection"]
            - lengths["selected_to_selected_projection"]
        )
        != 0
        or sp.simplify(
            lengths["reference_to_reference_projection"]
            - lengths["anchor_to_selected_projection"]
        )
        != 0
    ):
        return None
    return {
        "reference_projection": _string_point(reference_projection),
        "selected_projection": _string_point(selected_projection),
        "lengths": {
            key: sp.sstr(value) for key, value in lengths.items() if value is not None
        },
    }


def _positive_length(
    value: sp.Expr,
    *,
    parameter: sp.Symbol | None,
    lower_bound: sp.Expr | None,
) -> sp.Expr | None:
    value = sp.simplify(value)
    if is_definitely_positive(value):
        return value
    if is_definitely_negative(value):
        return sp.simplify(-value)
    if parameter is not None and lower_bound is not None:
        if is_definitely_positive_under_lower_bound(value, parameter, lower_bound):
            return value
        if is_definitely_negative_under_lower_bound(value, parameter, lower_bound):
            return sp.simplify(-value)
    return None


def _strict_lower_bound_context(
    value: Mapping[str, Any] | None,
) -> tuple[sp.Symbol | None, sp.Expr | None]:
    if not isinstance(value, Mapping):
        return None, None
    constraint = value.get("parameter_constraint")
    if not isinstance(constraint, Mapping):
        return None, None
    parameter_name = str(value.get("parameter") or "")
    if not parameter_name or str(constraint.get("operator") or "") != ">":
        return None, None
    lower_bound = _optional_expr(constraint.get("value"))
    if lower_bound is None:
        return None, None
    return sp.Symbol(parameter_name), lower_bound


def _projection_line(
    axis: str,
    anchor: tuple[sp.Expr, sp.Expr],
) -> dict[str, str]:
    offset = anchor[1] if axis == "x" else anchor[0]
    return {
        "kind": "coordinate_axis" if sp.simplify(offset) == 0 else "axis_parallel",
        "axis": axis,
        "offset": sp.sstr(offset),
    }


def _point(value: Any) -> tuple[sp.Expr, sp.Expr]:
    values = _sequence(value)
    if len(values) != 2:
        raise ValueError("point must contain two coordinates")
    return (sp.sympify(str(values[0])), sp.sympify(str(values[1])))


def _sequence(value: Any) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise TypeError("value must be a sequence")
    return value


def _same_point(
    left: tuple[sp.Expr, sp.Expr],
    right: tuple[sp.Expr, sp.Expr],
) -> bool:
    return all(
        sp.simplify(a - b) == 0 for a, b in zip(left, right, strict=True)
    )


def _string_point(value: tuple[sp.Expr, sp.Expr]) -> tuple[str, str]:
    return tuple(sp.sstr(sp.simplify(item)) for item in value)  # type: ignore[return-value]


def _optional_expr(value: Any) -> sp.Expr | None:
    if value in (None, ""):
        return None
    try:
        return sp.sympify(str(value))
    except (TypeError, ValueError, sp.SympifyError):
        return None


__all__ = [
    "build_axis_projection_candidate_construction_witness",
    "build_axis_projection_congruence_witness",
]
