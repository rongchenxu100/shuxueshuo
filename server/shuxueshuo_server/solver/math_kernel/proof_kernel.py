"""Standalone bounded proof search and local certificate replay (no Runtime).

Premises are explicitly supplied by the caller. A successful conditional proof
never asserts feasibility, complete solution enumeration, or execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

import sympy as sp

from .expression_parser import (
    MathParseError,
    ParsedMath,
)
from .proof_algebra import (
    ProofFailure,
    from_node,
)
from .proof_checker import (
    RELATIONS,  # noqa: F401 - legacy compatibility export
    RULES,  # noqa: F401 - legacy compatibility export
    RULESET_HASH,  # noqa: F401 - legacy compatibility export
    RULESET_VERSION,  # noqa: F401 - legacy compatibility export
    _checked,
    _derived_source,  # noqa: F401 - legacy compatibility export
    _document,
    _Environment,
    _failure,
    _payload_depth,  # noqa: F401 - legacy compatibility export
    _read_document,  # noqa: F401 - legacy compatibility export
    _relation,  # noqa: F401 - legacy compatibility export
    _replay,
    _roots_for_request,  # noqa: F401 - legacy compatibility export
    _text,  # noqa: F401 - legacy compatibility export
    _validate_expression,  # noqa: F401 - legacy compatibility export
    _witness_problem,
    fact_key,
    freeze_json,  # noqa: F401 - legacy compatibility export
    replay_proof,  # noqa: F401 - legacy compatibility export
)
from .proof_types import (
    ProofContext,
    ProofLimits,  # noqa: F401 - legacy compatibility export
    ProofNode,  # noqa: F401 - legacy compatibility export
    ProofResult,
    Witness,
    _Budget,
)


def _run_request(context, request, *, budget=None):
    from .method_proof_session import MethodProofSession, active_session

    session = active_session()
    if session is None:
        # Standalone/v1 calls share only their explicit bounded-request lifetime.
        # Imported fragments are rechecked against each exact local context.
        session = budget.local_search_session if budget is not None else None
        if session is None:
            session = MethodProofSession()
            if budget is not None:
                budget.local_search_session = session
    return session.run_request(context, request, budget=budget)


def prove_relation(candidate: ParsedMath, context: ProofContext) -> ProofResult:
    try:
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        _checked(candidate, context.symbols)
        return _run_request(
            context, {"kind": "relation", "candidate": _document(candidate)}
        )
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        return _failure(exc)


def verify_relation_sequence(relations, context, *, certificates=None, budget=None, on_verified=None):
    """Prove/replay ordered relations; only verified predecessors become premises.

    A single construction/replay budget spans the whole sequence. Supplying
    certificates selects replay only: no search and no trusted success flags.
    The caller binds this sequence to its original teaching-row source map.
    """
    # Natural rows allow 32 authored relations. Monotone chains additionally
    # produce endpoint obligations; do not charge those as authored steps.
    if not 1 <= len(relations) <= 256 or len({fact_key(from_node(r.ast)) for r in relations}) > 64:
        raise ProofFailure("proof_limit", "derivation exceeds 64 distinct expanded relations or 256 records")
    if certificates is not None and len(certificates) != len(relations):
        raise ProofFailure("invalid_proof", "derivation certificate count mismatch")
    budget = budget or _Budget(context.limits)
    premises = dict(context.premises)
    known = {from_node(p.ast) for p in premises.values()}
    proofs = []
    for i, relation in enumerate(relations):
        _checked(relation, context.symbols)
        current = replace(context, premises=dict(premises))
        request = {"kind": "relation", "candidate": _document(relation)}
        if certificates is None:
            proof = _run_request(current, request, budget=budget).proof
        else:
            proof = certificates[i]
            if proof.get("request") != request:
                raise ProofFailure("invalid_proof", "derivation conclusion changed")
            _replay(proof, current, budget=budget)
        proofs.append(proof)
        if on_verified is not None:
            on_verified(proof)
        value = from_node(relation.ast)
        if value not in known:
            key = f"derivation:{i}"
            if key in premises:
                raise ProofFailure("invalid_input", "reserved derivation premise ID")
            premises[key] = relation
            known.add(value)
    return proofs


def prove_domain(expression: ParsedMath, context: ProofContext) -> ProofResult:
    try:
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        _checked(expression, context.symbols, relation=False)
        return _run_request(
            context, {"kind": "domain", "candidate": _document(expression)}
        )
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        return _failure(exc)


def verify_witnesses(
    assignments: Sequence[Witness | Mapping[str, ParsedMath]],
    requirements: Sequence[ParsedMath],
    context: ProofContext,
    *,
    mode="all",
    selected_branch=None,
    require_parameterized=False,
    _budget=None,
) -> ProofResult:
    """Verify every submitted branch, or one explicitly selected existential one.

    ``require_parameterized`` is the range-attainment gate: endpoints cannot
    satisfy it. Completeness of all solutions is never claimed by this API.
    """
    reports = []
    try:
        if not isinstance(context, ProofContext):
            raise ProofFailure("invalid_input", "ProofContext required")
        if (
            not 1 <= len(assignments) <= context.limits.branches
            or not requirements
            or len(requirements) > 16
        ):
            raise ProofFailure("proof_limit", "witness/requirement count limit")
        if (
            mode not in {"all", "exists"}
            or (
                mode == "exists"
                and (
                    type(selected_branch) is not int
                    or not 0 <= selected_branch < len(assignments)
                )
            )
            or (mode == "all" and selected_branch is not None)
        ):
            raise ProofFailure(
                "invalid_input", "explicit valid witness selection required"
            )
        witnesses = []
        for item in assignments:
            item = Witness(item) if isinstance(item, Mapping) else item
            if not isinstance(item, Witness):
                raise ProofFailure("invalid_input", "Witness required")
            if require_parameterized and item.parameter is None:
                raise ProofFailure(
                    "proof_missing",
                    "endpoint witnesses do not prove an entire interval",
                )
            witnesses.append(
                {
                    "assignments": {
                        k: _document(v) for k, v in sorted(item.assignments.items())
                    },
                    "parameter": item.parameter,
                    "interval": item.interval,
                }
            )
        for requirement in requirements:
            _checked(
                requirement,
                {
                    **context.symbols,
                    **{
                        w["parameter"]: sp.Symbol(w["parameter"], real=True)
                        for w in witnesses
                        if w["parameter"] is not None
                    },
                },
            )
        request = {
            "kind": "witness",
            "witnesses": witnesses,
            "requirements": [_document(r) for r in requirements],
            "mode": mode,
            "selected_branch": selected_branch,
            "require_parameterized": require_parameterized,
        }
        # Witness is a checker-owned constructor, not a search strategy.
        env = _Environment(context, request, budget=_budget)
        roots = []
        indices = range(len(witnesses)) if mode == "all" else [selected_branch]
        for i in indices:
            try:
                child_context, child_request = _witness_problem(env, i)
                result = _run_request(child_context, child_request, budget=env.budget)
                child = env.add(
                    "witness",
                    ("witness", i),
                    certificate={"index": i, "proof": result.proof},
                )
                root = (
                    env.add("exists", ("exists", i), [child], {"selected_branch": i})
                    if mode == "exists"
                    else child
                )
                roots.append(root)
                reports.append({"index": i, "status": "proved"})
            except (ProofFailure, MathParseError) as exc:
                reports.append(
                    {
                        "index": i,
                        "status": "not_proved",
                        "code": getattr(exc, "code", "invalid_input"),
                        "diagnostic": str(exc),
                    }
                )
                if isinstance(exc, ProofFailure) and exc.is_shared_budget_exhaustion:
                    # Shared budget is exhausted; retain an explicit result for
                    # every remaining branch without resetting it.
                    for remaining in indices:
                        if remaining > i:
                            reports.append(
                                {
                                    "index": remaining,
                                    "status": "not_proved",
                                    "code": exc.code,
                                }
                            )
                    break
        if any(r["status"] != "proved" for r in reports):
            first = next(r for r in reports if r["status"] != "proved")
            return ProofResult(
                "not_proved",
                first["code"],
                "one or more submitted witnesses failed",
                branches=tuple(reports),
            )
        return ProofResult("proved", proof=env.payload(roots), branches=tuple(reports))
    except (
        ProofFailure,
        MathParseError,
        TypeError,
        ValueError,
        KeyError,
        RecursionError,
        ArithmeticError,
    ) as exc:
        return _failure(exc, tuple(reports))
