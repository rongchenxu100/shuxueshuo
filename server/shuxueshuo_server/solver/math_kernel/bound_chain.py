"""Replay exact predecessor evidence without conflating different bound methods."""

from .proof_algebra import ProofFailure, digest


def unpack_bound(evidence):
    """Decode an already checked public bound; this function grants no authority."""
    from copy import deepcopy

    return deepcopy({**{k: v for k, v in evidence.items() if k != "certificate_bundle"},
                     **evidence["certificate_bundle"]})


def consume_bound(target, evidence, *, depth=0, budget=None):
    """Execution uses an exact authorized predecessor; external replay stays strict."""
    from .method_proof_session import active_session

    ancestor, level = evidence, depth
    while ancestor is not None:
        if level > 8:
            raise ProofFailure("proof_limit", "at most eight bound dependencies")
        level += 1
        ancestor = ancestor.get("previous_bound")
    session = active_session()
    if session is not None and session.resolve_bound is not None:
        result = session.resolve_bound(target, evidence)
        if result is not None:
            return result
    return replay_bound(target, evidence, depth=depth, budget=budget)


def replay_bound(target, evidence, *, depth=0, budget=None):
    from .inequality_bound_v2 import public, verify

    if depth > 8:
        raise ProofFailure("proof_limit", "at most eight bound dependencies")
    if evidence.get("target_hash") != digest(target):
        raise ProofFailure(
            "invalid_proof", "bound belongs to another target or version"
        )
    certificates = evidence.get("certificate_bundle")
    if not isinstance(certificates, dict):
        raise ProofFailure("invalid_proof", "missing bound certificate bundle")
    common = {
        "expression": evidence.get("expression"),
        "previous_bound": evidence.get("previous_bound"),
        "certificates": certificates,
        "depth": depth,
        "budget": budget,
    }
    if evidence.get("schema_version") == "quadratic-bound/v1":
        from .quadratic_bound import verify_quadratic

        rebuilt = verify_quadratic(
            target, evidence["steps"], variable=evidence["variable"], **common
        )
    elif evidence.get("schema_version") == "amgm-bound/v2":
        rebuilt = verify(
            target,
            evidence["steps"],
            elimination=evidence.get("elimination"),
            substitution=evidence.get("substitution"),
            reciprocal=evidence.get("reciprocal", False),
            **common,
        )
    else:
        raise ProofFailure("invalid_proof", "unsupported bound evidence")
    if public(rebuilt) != evidence:
        raise ProofFailure("invalid_proof", "bound or dependency evidence altered")
    return rebuilt
