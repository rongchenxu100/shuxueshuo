"""Bounded, replayable elimination of one original scalar; no equation search."""

from copy import deepcopy
from dataclasses import replace

from .derivation_math import parse_derivation
from .expression_parser import parse_math_expression, parse_math_relation
from .proof_algebra import (
    Arithmetic,
    ProofFailure,
    digest,
    domains,
    from_node,
    names,
    substitute,
    walk,
)
from .proof_kernel import _Budget, _document, _replay, _run_request

CONTRACT = "constraint-elimination/v1"


def elimination_context(context):
    # One M08 transaction can contain 32 relations in addition to 16 original
    # conditions. Its fixed sequence budget also applies to downstream replay;
    # a caller-supplied smaller budget is never expanded after a failure.
    return replace(
        context,
        limits=replace(
            context.limits, premises=48, reductions=1024, attempts=2048, nodes=2048
        ),
    )


def has_elimination(bound):
    for _ in range(9):
        if not isinstance(bound, dict):
            return False
        if bound.get("elimination") is not None:
            return True
        bound = bound.get("previous_bound")
    raise ProofFailure("proof_limit", "at most eight bound dependencies")


def _verify_sequence(relations, context, *, certificates, budget):
    """Retain original facts and the latest form of equivalent derived equations.

    This only removes redundant premises; it never adds an unproved relation.
    Replay uses the same deterministic selection and never searches.
    """
    if not 1 <= len(relations) <= 32:
        raise ProofFailure("proof_limit", "1–32 elimination relations required")
    if certificates is not None and len(certificates) != len(relations):
        raise ProofFailure("invalid_proof", "elimination certificate count mismatch")
    derived = {}
    equation_keys = {}
    proofs = []
    arithmetic = Arithmetic(budget)
    for i, relation in enumerate(relations):
        current = replace(context, premises={**context.premises, **derived})
        request = {"kind": "relation", "candidate": _document(relation)}
        try:
            if certificates is None:
                proof = _run_request(current, request, budget=budget).proof
            else:
                proof = certificates[i]
                if proof.get("request") != request:
                    raise ProofFailure(
                        "invalid_proof", "elimination conclusion changed"
                    )
                _replay(proof, current, budget=budget)
            if any(n["rule_id"] == "math.two_term_amgm" for n in proof["nodes"]):
                raise ProofFailure(
                    "elimination_estimate_forbidden",
                    "submit equivalence and domain derivations; inequality estimation belongs to another Method",
                )
        except ProofFailure as exc:
            raise ProofFailure(
                exc.code,
                f"{relation.source_path or '/parameters/steps'}: {relation.source}: {exc}",
            ) from exc
        proofs.append(proof)
        if i == len(relations) - 1:
            continue
        value = from_node(relation.ast)
        if value in {from_node(p.ast) for p in current.premises.values()}:
            continue
        key = f"elimination:row:{i}"
        if relation.ast.op == "=":
            # A rational identity already implied by retained equations adds
            # no premise. Keep its certificate/source row, but avoid clearing
            # its denominators a second time for every later consistency check.
            if all(any(n[0] == "div" for n in walk(side)) for side in value[1:]):
                divisors = [
                    arithmetic.equation_divisor(from_node(p.ast))
                    for p in current.premises.values()
                    if p.ast.op == "="
                ]
                if not arithmetic.reduce(arithmetic.difference(value), divisors)[1]:
                    continue
            divisor = arithmetic.equation_divisor(value)
            if not divisor:
                continue
            leading = divisor[min(divisor)]
            normalized = tuple(sorted((m, c / leading) for m, c in divisor.items()))
            old = equation_keys.get(normalized)
            if old is not None:
                del derived[old]
            equation_keys[normalized] = key
        derived[key] = relation
    return proofs


def verify_elimination(target, parameters, *, certificates=None, budget=None):
    from .inequality_bound_v2 import math_text
    from .inequality_evidence import target_context

    context, original = target_context(target)
    context = elimination_context(context)
    budget = budget or _Budget(context.limits)
    variable = parameters["eliminate"]
    if variable not in context.symbols or len(context.symbols) < 2:
        raise ProofFailure(
            "elimination_variable_invalid", "eliminate one declared original variable"
        )
    chain = parse_derivation(parameters["steps"], context.symbols)
    relations = [r.parsed for r in chain]
    # Require a unique explicitly submitted restoration formula. Never infer
    # a branch or select one root from an unverified equation.
    formulas = {}
    for relation in relations:
        if relation.ast.op != "=":
            continue
        left, right = relation.ast.children
        for lhs, rhs in ((left, right), (right, left)):
            if (
                lhs.op == "symbol"
                and lhs.text == variable
                and variable not in names(from_node(rhs))
            ):
                formulas[from_node(rhs)] = relation.source[slice(*rhs.span)]
    if len(formulas) != 1:
        raise ProofFailure(
            "elimination_restoration_invalid",
            "submit exactly one non-cyclic restoration formula",
        )
    replacement, restoration = next(iter(formulas.items()))
    reduced = parse_math_expression(parameters["expression"], context.symbols)
    if variable in names(from_node(reduced.ast)) or not names(
        from_node(reduced.ast)
    ) < names(from_node(original.ast)):
        raise ProofFailure(
            "elimination_not_reduced",
            "result must remove the selected variable without new variables",
        )
    equation = replace(
        parse_math_relation(
            f"({target['target_math']})=({parameters['expression']})", context.symbols
        ),
        source_path="/parameters/expression",
    )
    all_relations = [*relations, equation]
    proofs = _verify_sequence(
        all_relations, context, certificates=certificates, budget=budget
    )
    if certificates is None:
        _verify_sequence(
            all_relations, context, certificates=proofs, budget=_Budget(context.limits)
        )
    # Keep every original condition under the simultaneous substitution, not
    # merely whichever sign constraints happened to be useful in this proof.
    remaining = [
        math_text(substitute(from_node(p.ast), {variable: replacement}))
        for p in context.premises.values()
    ]
    evidence = {
        "schema_version": CONTRACT,
        "target_hash": digest(target),
        "target_math": target["target_math"],
        "parameters": deepcopy(parameters),
        "eliminated_variable": variable,
        "restoration": f"{variable}=({restoration})",
        "expression": parameters["expression"],
        "remaining_conditions": remaining,
        "origins": [r.origin for r in chain],
        "proofs": proofs,
    }
    # Downstream consumers need the proved signs, restoration and target
    # equivalence, not all intermediate equalities as polynomial divisors.
    exports = [
        r
        for r in relations
        if r.ast.op != "="
        or any(n.op == "symbol" and n.text == variable for n in r.ast.children)
    ] + [equation]
    # The final guarded equality already proves the original and reduced
    # denominators. Preserve those domain facts for downstream consumers.
    exports += [
        replace(
            parse_math_relation(math_text(g), context.symbols),
            source_path="/parameters/expression/domain",
        )
        for g in domains(from_node(equation.ast))
    ]
    working = replace(
        context,
        premises={
            **context.premises,
            **{
                f"elimination:{i}": relation
                for i, relation in enumerate(exports)
                if from_node(relation.ast)
                not in {from_node(p.ast) for p in context.premises.values()}
            },
        },
    )
    return evidence, working


def replay_elimination(target, evidence, *, budget=None):
    if evidence.get("schema_version") != CONTRACT or evidence.get(
        "target_hash"
    ) != digest(target):
        raise ProofFailure(
            "invalid_proof", "elimination belongs to another target or scope"
        )
    if not isinstance(evidence.get("proofs"), list):
        raise ProofFailure("invalid_proof", "elimination certificates missing")
    rebuilt, context = verify_elimination(
        target, evidence["parameters"], certificates=evidence["proofs"], budget=budget
    )
    if rebuilt != evidence:
        raise ProofFailure("invalid_proof", "elimination evidence changed")
    return context
