"""Verified, scoped definitional extensions with bounded inverse branches."""

import re
from copy import deepcopy
from dataclasses import replace
from itertools import product

import sympy as sp

from .constraint_elimination import _verify_sequence
from .derivation_math import parse_derivation
from .expression_parser import parse_math_expression, parse_math_relation
from .proof_algebra import ProofFailure, digest, from_node, names
from .proof_kernel import _Budget, verify_relation_sequence

CONTRACT = "expression-substitution/v1"


def substitution_context(context):
    return replace(
        context,
        limits=replace(
            context.limits,
            variables=8,
            premises=64,
            equations=8,
            reductions=2048,
            attempts=4096,
            nodes=4096,
        ),
    )


def find_substitution(bound):
    for _ in range(9):
        if not isinstance(bound, dict):
            return None
        if bound.get("substitution") is not None:
            return bound["substitution"]
        if (
            isinstance(bound.get("elimination"), dict)
            and bound["elimination"].get("substitution") is not None
        ):
            return bound["elimination"]["substitution"]
        bound = bound.get("previous_bound")
    raise ProofFailure("proof_limit", "at most eight bound dependencies")


def verify_substitution(target, parameters, *, certificates=None, budget=None):
    from .inequality_evidence import target_context

    base, _ = target_context(target)
    base = substitution_context(base)
    budget = budget or _Budget(base.limits)
    definitions = parameters["definitions"]
    if not isinstance(definitions, dict) or not 1 <= len(definitions) <= 2:
        raise ProofFailure(
            "substitution_definition_invalid", "one or two fresh definitions required"
        )
    if any(
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,15}", n) or n in base.symbols
        for n in definitions
    ):
        raise ProofFailure(
            "substitution_symbol_collision",
            "new symbols must be fresh and distinct from original symbols",
        )
    symbols = {**base.symbols, **{n: sp.Symbol(n, real=True) for n in definitions}}
    inverses, domains, used = [], [], set()
    for new, source in definitions.items():
        parsed = parse_math_expression(source, base.symbols)
        variables = names(from_node(parsed.ast))
        if len(variables) != 1 or used & variables:
            raise ProofFailure(
                "substitution_definition_invalid",
                "each definition must use a distinct original variable",
            )
        used.update(variables)
        old = next(iter(variables))
        value = parsed.to_sympy(base.symbols)
        try:
            poly = sp.Poly(value, base.symbols[old])
        except sp.PolynomialError as exc:
            raise ProofFailure(
                "substitution_unsupported", "use an affine expression or a square"
            ) from exc
        if poly.degree() == 1 and all(c.is_Rational for c in poly.all_coeffs()):
            a, b = poly.all_coeffs()
            inverse = str((symbols[new] - b) / a)
            inverses.append([{old: inverse}])
        elif value == base.symbols[old] ** 2:
            inverses.append([{old: f"sqrt({new})"}, {old: f"-sqrt({new})"}])
        else:
            raise ProofFailure(
                "substitution_unsupported",
                "only rational affine or original-variable square definitions supported",
            )
        domains.append(parse_math_relation(f"({source})=({source})", base.symbols))
    domain_proofs = verify_relation_sequence(
        domains,
        base,
        certificates=certificates["domains"] if certificates is not None else None,
        budget=budget,
    )
    # A fresh name denotes exactly the checked original expression. These
    # equations are conservative definitions, never candidate-derived facts.
    defining = {
        f"substitution:definition:{n}": parse_math_relation(f"{n}=({s})", symbols)
        for n, s in definitions.items()
    }
    context = replace(base, symbols=symbols, premises={**base.premises, **defining})
    chain = parse_derivation(parameters["steps"], symbols)
    expression = parse_math_expression(parameters["expression"], symbols)
    if not names(from_node(expression.ast)) <= definitions.keys():
        raise ProofFailure(
            "substitution_expression_invalid",
            "transformed target must use only the new symbols",
        )
    equation = replace(
        parse_math_relation(
            f"({target['target_math']})=({parameters['expression']})", symbols
        ),
        source_path="/parameters/expression",
    )
    relations = [r.parsed for r in chain] + [equation]
    saved = certificates["relations"] if certificates is not None else None
    if saved is not None and len(saved) != len(relations):
        raise ProofFailure("invalid_proof", "substitution certificate count mismatch")
    proofs = _verify_sequence(
        relations[:-1],
        context,
        certificates=saved[:-1] if saved is not None else None,
        budget=budget,
    )
    # Conditions may prove domains; they cannot change the target during M07.
    # Only conservative definitions authorize its algebraic rewrite.
    rewrite_context = replace(
        context,
        premises={
            **{k: v for k, v in context.premises.items() if v.ast.op != "="},
            **defining,
            **{
                f"substitution:domain:{i}": r
                for i, r in enumerate(relations[:-1])
                if r.ast.op != "="
            },
        },
    )
    try:
        proofs += _verify_sequence(
            [equation],
            rewrite_context,
            certificates=saved[-1:] if saved is not None else None,
            budget=budget,
        )
    except ProofFailure as exc:
        if certificates is not None:
            raise
        raise ProofFailure(
            "substitution_requires_elimination",
            "expression must be the definition-only transformed target; use eliminate_by_constraint with this substitution result to remove a variable using conditions",
        ) from exc
    restoration = [
        dict(item for branch in choices for item in branch.items())
        for choices in product(*inverses)
    ]
    evidence = {
        "schema_version": CONTRACT,
        "target_hash": digest(target),
        "scope_id": target["scope_id"],
        "target_math": target["target_math"],
        "parameters": deepcopy(parameters),
        "definitions": deepcopy(definitions),
        "expression": parameters["expression"],
        "restoration_branches": restoration,
        "original_conditions": deepcopy(target["source_conditions"]),
        "relations": [r.parsed.source for r in chain],
        "origins": [r.origin for r in chain],
        "certificates": {"domains": domain_proofs, "relations": proofs},
    }
    working = replace(
        context,
        premises={
            **context.premises,
            **{f"substitution:verified:{i}": r for i, r in enumerate(relations)},
        },
    )
    if certificates is None:
        # Fail at M07 before committing a definitional extension that downstream
        # methods cannot replay. The replay branch never searches or recurses.
        replay_substitution(target, evidence, budget=_Budget(base.limits))
    return evidence, working


def replay_substitution(target, evidence, *, budget=None):
    if evidence.get("schema_version") != CONTRACT or evidence.get(
        "target_hash"
    ) != digest(target):
        raise ProofFailure(
            "invalid_proof", "substitution belongs to a different target or scope"
        )
    if not isinstance(evidence.get("certificates"), dict):
        raise ProofFailure("invalid_proof", "substitution certificates required")
    rebuilt, context = verify_substitution(
        target,
        evidence["parameters"],
        certificates=evidence["certificates"],
        budget=budget,
    )
    if rebuilt != evidence:
        raise ProofFailure(
            "invalid_proof", "substitution evidence or restoration branches changed"
        )
    return context
