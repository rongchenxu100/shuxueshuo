"""Positive reciprocal AM-GM transport; no alternative-target search."""

from copy import deepcopy
from dataclasses import replace

import sympy as sp

from .constraint_elimination import elimination_context, replay_elimination
from .derivation_math import parse_derivation
from .expression_parser import parse_math_expression, parse_math_relation
from .proof_algebra import Arithmetic, ProofFailure, digest, from_node, names
from .proof_kernel import _Budget, verify_relation_sequence


def verify_reciprocal(target, steps, elimination, *, certificates=None, budget=None):
    from .inequality_bound_v2 import public, verify
    from .inequality_evidence import target_context

    if target.get("goal_kind") != "find_maximum" or elimination is None:
        raise ProofFailure(
            "reciprocal_target_invalid",
            "positive reciprocal maximum requires same-target M08 elimination",
        )
    context, _ = target_context(target)
    context = elimination_context(context)
    budget = budget or _Budget(context.limits)
    context = replay_elimination(target, elimination, budget=budget)
    context = replace(
        context,
        premises={
            k: p
            for k, p in context.premises.items()
            if p.source_path != "/parameters/expression"
        },
    )
    original = target["target_math"]
    source = f"1/({elimination['expression']})"
    inverse = source
    reduced = elimination["expression"]
    inner_target = {
        **target,
        "goal_kind": "find_minimum",
        "target_math": inverse,
        "source_conditions": [
            {
                "handle": k,
                "math": p.source,
                "source_path": p.source_path or "/elimination",
            }
            for k, p in context.premises.items()
        ],
    }
    supplied = (
        certificates.get("reciprocal_bound") if certificates is not None else None
    )
    if certificates is not None and not isinstance(supplied, dict):
        raise ProofFailure(
            "invalid_proof", "reciprocal lower-bound certificates missing"
        )
    # Locate the submitted bound by its mathematical role, not the last row:
    # authors may finish with its positivity or the reciprocal conclusion.
    arithmetic = Arithmetic(budget)
    inverse_ast = from_node(parse_math_expression(inverse, context.symbols).ast)
    candidates = []
    for i, row in enumerate(parse_derivation(steps, context.symbols)):
        relation = from_node(row.parsed.ast)
        if relation[0] not in {">=", "<="}:
            continue
        left, right = relation[1:] if relation[0] == ">=" else relation[:0:-1]
        if not names(right) and not arithmetic.difference(("=", inverse_ast, left)):
            candidates.append(i)
    if not candidates:
        raise ProofFailure(
            "target_bound_mismatch",
            "submit a constant lower bound for the reduced target's reciprocal",
        )
    lower = verify(
        inner_target,
        steps,
        bound_relation_index=candidates[-1],
        certificates=supplied["certificate_bundle"] if supplied else None,
        budget=budget,
    )
    if supplied is not None and public(lower) != supplied:
        raise ProofFailure("invalid_proof", "reciprocal lower-bound evidence changed")
    value = parse_math_expression(lower["bound"], context.symbols)
    if names(from_node(value.ast)):
        raise ProofFailure(
            "target_bound_mismatch",
            "reciprocal closure needs a strictly positive constant lower bound",
        )
    upper = str(sp.radsimp(1 / value.to_sympy(context.symbols)))
    lower_relation = parse_math_relation(
        f"({inverse})>=({lower['bound']})", context.symbols
    )
    working = replace(
        context,
        premises={**context.premises, "reciprocal:verified_lower": lower_relation},
    )
    relations = [
        parse_math_relation(s, context.symbols)
        for s in [
            f"({original})>0",
            f"({reduced})>0",
            f"({inverse})>0",
            f"({lower['bound']})>0",
            f"1/({inverse})<=1/({lower['bound']})",
            f"({reduced})<=({upper})",
            f"({original})<=({upper})",
        ]
    ]
    proofs = verify_relation_sequence(
        relations,
        working,
        certificates=certificates["proofs"] if certificates is not None else None,
        budget=budget,
    )
    if certificates is None:
        verify_relation_sequence(relations, working, certificates=proofs)
    if (
        certificates is not None
        and certificates.get("derivation") != lower["derivation"]
    ):
        raise ProofFailure("invalid_proof", "reciprocal derivation source changed")
    return {
        "schema_version": "amgm-bound/v2",
        "target_hash": digest(target),
        "target_math": original,
        "steps": deepcopy(steps),
        "direction": "<=",
        "source_math": source,
        "expression": None,
        "elimination": deepcopy(elimination),
        "previous_bound": None,
        "reciprocal": True,
        "reciprocal_lower_value": lower["bound"],
        "reciprocal_bound": public(lower),
        "bound": upper,
        "equality": lower["equality"],
        "equalities": lower["equalities"],
        "applications": lower["applications"],
        "proofs": proofs,
        "derivation": lower["derivation"],
    }
