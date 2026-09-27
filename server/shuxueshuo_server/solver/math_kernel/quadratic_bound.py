"""Verify a submitted parameter quadratic lower bound and replay its certificates."""

from copy import deepcopy
from dataclasses import replace

import sympy as sp

from .bound_chain import replay_bound
from .derivation_math import parse_derivation
from .expression_parser import parse_math_expression, parse_math_relation
from .inequality_bound_v2 import math_text
from .inequality_evidence import target_context
from .proof_algebra import ProofFailure, digest, domains, from_node
from .proof_kernel import _Budget, verify_relation_sequence


def verify_quadratic(
    target,
    steps,
    *,
    variable,
    expression=None,
    previous_bound=None,
    certificates=None,
    depth=0,
    budget=None,
):
    if depth > 8:
        raise ProofFailure("proof_limit", "at most eight bound dependencies")
    if target.get("goal_kind") != "find_minimum" or (
        expression is not None and previous_bound is not None
    ):
        raise ProofFailure(
            "invalid_input", "quadratic lower bound needs one source and a minimum goal"
        )
    expression = str(expression) if expression is not None else None
    context, _ = target_context(target)
    budget = budget or _Budget(context.limits)
    predecessor = None
    if previous_bound is not None:
        predecessor = replay_bound(
            target, previous_bound, depth=depth + 1, budget=budget
        )
        if predecessor["direction"] != ">=":
            raise ProofFailure(
                "target_bound_mismatch", "lower-bound predecessor required"
            )
        from .constraint_elimination import replay_elimination
        from .substitution import find_substitution, replay_substitution

        ancestor = previous_bound
        while ancestor.get("previous_bound") is not None:
            ancestor = ancestor["previous_bound"]
        if ancestor.get("elimination") is not None:
            context = replay_elimination(target, ancestor["elimination"], budget=budget)
        elif find_substitution(previous_bound) is not None:
            context = replay_substitution(
                target, find_substitution(previous_bound), budget=budget
            )
    if variable not in context.symbols:
        raise ProofFailure(
            "invalid_input", "quadratic variable must already be declared"
        )
    source = (
        predecessor["bound"] if predecessor else expression or target["target_math"]
    )
    z = context.symbols[variable]
    parsed_source = parse_math_expression(source, context.symbols)
    try:
        poly = sp.Poly(sp.cancel(parsed_source.to_sympy(context.symbols)), z)
        if poly.degree() != 2:
            raise ValueError("not quadratic")
        coefficient, linear, constant = poly.all_coeffs()
    except (sp.PolynomialError, ValueError) as exc:
        raise ProofFailure(
            "quadratic_template_unmatched",
            "source must be quadratic in the selected variable",
        ) from exc
    center = sp.cancel(-linear / (2 * coefficient))
    remainder = sp.cancel(constant - linear**2 / (4 * coefficient))
    square = str(sp.factor(coefficient * (z - center) ** 2))
    completed = f"({square})+({remainder})"
    equality = f"{variable}=({center})"
    chain = parse_derivation(steps, context.symbols)
    if not chain or chain[-1].parsed.ast.op != ">=":
        raise ProofFailure(
            "target_bound_mismatch", "quadratic conclusion must be a lower bound"
        )
    last = chain[-1].parsed
    left, right = last.ast.children
    bound = last.source[slice(*right.span)]
    lhs = parse_math_expression(
        last.source[slice(*left.span)], context.symbols
    ).to_sympy(context.symbols)
    value = parse_math_expression(bound, context.symbols).to_sympy(context.symbols)
    if (
        sp.cancel(value - remainder) != 0
        or sp.cancel(lhs - parsed_source.to_sympy(context.symbols)) != 0
    ):
        raise ProofFailure(
            "quadratic_template_unmatched",
            "conclusion must remove exactly the completed square",
        )
    completed = f"({square})+({bound})"
    if not any(
        row.parsed.ast.op == "=" and any(n.op == "pow" for n in _walk(row.parsed.ast))
        for row in chain
    ):
        raise ProofFailure(
            "quadratic_template_unmatched", "submit the square-completion identity"
        )
    premises = dict(context.premises)
    working = replace(context, premises=premises)
    # Certificate-backed checks, including source domains, precede submitted rows.
    requirements = [
        *[
            math_text(d)
            for d in dict.fromkeys(
                (
                    *domains(
                        from_node(
                            parse_math_expression(
                                target["target_math"], context.symbols
                            ).ast
                        )
                    ),
                    *domains(from_node(parsed_source.ast)),
                )
            )
        ],
        f"({coefficient})>0",
        *[
            f"({p})>=0"
            for p in sp.preorder_traversal(sp.factor(coefficient * (z - center) ** 2))
            if p.is_Pow and p.exp == 2
        ],
        f"({square})>=0",
        f"({source})=({completed})",
        f"({completed})>=({bound})",
    ]
    if expression is not None:
        requirements.append(f"({target['target_math']})=({source})")
    required = [parse_math_relation(v, context.symbols) for v in requirements]
    proofs = verify_relation_sequence(
        required,
        working,
        budget=budget,
        certificates=certificates["proofs"] if certificates is not None else None,
    )
    for i, row in enumerate(required):
        premises[f"quadratic:verified:{i}"] = row
    if predecessor:
        premises["bound:previous"] = parse_math_relation(
            f"({target['target_math']})>=({source})", context.symbols
        )
    working = replace(context, premises=premises)
    origins = [row.origin for row in chain]
    if certificates is not None and certificates["derivation"]["origins"] != origins:
        raise ProofFailure("invalid_proof", "quadratic origins changed")
    relations = [r.parsed for r in chain] + [
        parse_math_relation(f"({target['target_math']})>=({bound})", context.symbols)
    ]
    sequence = verify_relation_sequence(
        relations,
        working,
        budget=budget,
        certificates=certificates["derivation"]["proofs"]
        if certificates is not None
        else None,
    )
    result = {
        "schema_version": "quadratic-bound/v1",
        "target_hash": digest(target),
        "target_math": target["target_math"],
        "direction": ">=",
        "variable": variable,
        "source_math": source,
        "expression": expression,
        "previous_bound": deepcopy(previous_bound),
        "steps": deepcopy(steps),
        "bound": bound,
        "equality": equality,
        "equalities": [*(predecessor["equalities"] if predecessor else []), equality],
        "applications": [
            *(predecessor["applications"] if predecessor else []),
            {
                "kind": "quadratic",
                "variable": variable,
                "square": square,
                "equality": equality,
            },
        ],
        "square": square,
        "coefficient": str(coefficient),
        "center": str(center),
        "proofs": proofs,
        "derivation": {"origins": origins, "proofs": sequence},
    }
    if certificates is None:
        from .inequality_bound_v2 import public

        replay_bound(
            target, public(result), depth=depth, budget=_Budget(context.limits)
        )
    return result


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)
