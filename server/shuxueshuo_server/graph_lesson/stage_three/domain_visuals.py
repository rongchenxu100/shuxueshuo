"""Exact solved sets projected to comparable number lines; no equation solving."""

from copy import deepcopy

import sympy as sp

from .interaction_graphs import _float, _pieces, short_label
from .math_values import latex, math_value
from .trajectory import encode_value


def exact_math(value):
    return {**math_value(value), "exact": encode_value(value)}


def number_lines(values, *, include_result=False):
    solutions, constraints = list(values["solutions"]), values["constraints"]
    if constraints:
        if len(solutions) != len(constraints):
            raise ValueError("domain.condition_solution_count_mismatch")
        bindings = [("condition", value, constraint)
                    for value, constraint in zip(solutions, constraints, strict=True)]
    else:
        # The solver has one true condition for an unrestricted expression.
        # Do not label arbitrary extra/misaligned values as the real line.
        if len(solutions) != 1 or solutions[0] != sp.S.Reals:
            raise ValueError("domain.unrestricted_solution_required")
        bindings = [("unrestricted", solutions[0], None)]
    if values["description"]["input_domain_source_ref"]:
        bindings.append(("input", values["input_domain"], None))
    if include_result:
        bindings.append(("result", values["domain"], None))
    decomposed = [_pieces(value) for _, value, _ in bindings]
    ends = sorted(
        {
            point
            for intervals, points in decomposed
            for point in [
                *points,
                *(
                    endpoint
                    for piece in intervals
                    for endpoint in (piece.start, piece.end)
                    if endpoint not in (-sp.oo, sp.oo)
                ),
            ]
        }
    )
    if ends:
        low, high = _float(ends[0]), _float(ends[-1])
        pad = max((high - low) * 0.25, 0.75)
        bounds = [low - pad, high + pad]
    else:
        bounds = [-1.0, 1.0]
    ticks = [
        {"at": _float(point), "label": short_label(point), "exact": exact_math(point)}
        for point in ends
    ]
    result = []
    variable = values["description"]["variable"]
    for (role, value, constraint), (intervals, points) in zip(bindings, decomposed, strict=True):
        row = {
            "variable": variable,
            "label": latex(value),
            "bounds": list(bounds),
            "intervals": [
                {
                    "left": None if piece.start == -sp.oo else _float(piece.start),
                    "right": None if piece.end == sp.oo else _float(piece.end),
                    "left_closed": not piece.left_open,
                    "right_closed": not piece.right_open,
                    "exact": exact_math(piece),
                }
                for piece in intervals
            ],
            "points": [
                {"at": _float(point), "label": short_label(point), "exact": exact_math(point)}
                for point in points
            ],
            "ticks": deepcopy(ticks),
            "exact_set": exact_math(value),
        }
        if role == "condition":
            row.update(
                {
                    key: deepcopy(constraint[key])
                    for key in ("condition_id", "source_ref", "ast_path", "basis_refs")
                }
            )
            row["label"] = (
                latex(constraint["condition"])
                + r"\quad\Longrightarrow\quad "
                + latex(value)
            )
        elif role == "input":
            row.update(condition_id='input-domain', source_ref=values['description']['input_domain_source_ref'],
                       ast_path=[], basis_refs=['function-concept#elements'])
            row['label'] = variable + r'\in ' + latex(value)
        elif role == "result":
            row["label"] = (
                r"D_{" + values["description"]["function_name"] + "}=" + latex(value)
            )
        result.append(row)
    return result


def endpoint_checks(rows, variable):
    result = []
    for row in rows:
        # The exact point is carried by the independent endpoint operation.
        # Decoded seed values have already restored its inert math codec.
        point = row["point"]["exact"]
        if not isinstance(point, sp.Expr):
            raise TypeError("domain.endpoint_exact_point_required")
        evidence = row["evidence"]
        reason = (
            "原式有意义且满足题给范围，保留该点。"
            if row["included"]
            else "该点不在题给输入范围内，排除该点。"
            if not evidence["input_domain_member"]
            else "代入原式无意义，排除该点。"
        )
        if not row['included'] and evidence['input_domain_member']:
            causes = []
            for kind, numeric_failure, undefined, unknown in (
                ('radicand_nonnegative', '被开方数为负', '被开方数无意义', '被开方数非负条件不满足'),
                ('denominator_nonzero', '分母为 0', '分母无意义', '分母非零条件不满足'),
                ('zero_power_base_nonzero', '零次幂的底数为 0，出现 $0^0$',
                 '零次幂的底数无意义', '零次幂的底数非零条件不满足'),
            ):
                for source in evidence['sources']:
                    if source['kind'] != kind or source['holds']:
                        continue
                    defined = source.get('expression_defined')
                    # Older seeds have no definedness evidence. Keep them
                    # readable without inferring that an undefined divisor is 0.
                    cause = numeric_failure if defined is True else undefined if defined is False else unknown
                    if cause not in causes:
                        causes.append(cause)
            if causes:
                reason = '代入后' + '；'.join(causes) + '，原式无意义，排除该点。'
        result.append(
            {
                "at": _float(point),
                "label": variable + "=" + latex(point),
                "exact": exact_math(point),
                "included": row["included"],
                "holds": row["holds"],
                "passed": row["passed"],
                "reason": reason,
                "sources": deepcopy(evidence["sources"]),
            }
        )
    return result
