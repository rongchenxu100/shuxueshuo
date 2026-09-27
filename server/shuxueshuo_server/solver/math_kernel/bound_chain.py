"""Replay exact predecessor evidence without conflating different bound methods."""

from .proof_algebra import ProofFailure, digest


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
