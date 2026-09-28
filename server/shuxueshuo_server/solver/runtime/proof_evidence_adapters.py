"""Method-owned admission adapters; shared storage never interprets Method rules.

Constructor policies mirror the stage A audit. Names identify construction
sites, never confer authority on arbitrary context keys with the same prefix.
"""

from dataclasses import dataclass

from ..math_kernel.proof_algebra import ZERO, freeze
from ..math_kernel.proof_checker import _relation, _text

# (module, function, namespace): admission policy. Unknown sites fail closed.
PREMISE_POLICIES = {
    ("inequality_bound_v2", "verify", "bound:previous"): "verified",
    ("quadratic_bound", "verify_quadratic", "bound:previous"): "verified",
    ("substitution", "verify_substitution", "substitution:definition:"): "definition",
    ("substitution", "verify_substitution", "substitution:verified:"): "verified",
    ("substitution", "verify_substitution", "substitution:domain:"): "verified",
    ("constraint_elimination", "_verify_sequence", "elimination:row:"): "prefix",
    ("constraint_elimination", "verify_elimination", "elimination:"): "verified",
    ("quadratic_bound", "verify_quadratic", "quadratic:verified:"): "verified",
    (
        "inequality_bound_v2",
        "verify_equality_references",
        "attainment:reference",
    ): "requirement",
    ("inequality_bound_v2", "verify_equality_derivation", "attainment:"): "branch",
    ("inequality_bound_v2", "close", "solution_case"): "branch",
    ("inequality_bound_v2", "close", "shared_solution:"): "branch",
    (
        "inequality_bound_v2",
        "verify_equality_derivation",
        "equality_derivation:",
    ): "branch",
    ("proof_kernel", "verify_relation_sequence", "derivation:"): "prefix",
    ("inequality_bound_v2", "verify", "bound:row:"): "prefix",
    ("expression_rewrite", "verify_chain", "c{i}"): "source",
}


def premise_policy(module, function, namespace):
    try:
        return PREMISE_POLICIES[module, function, namespace]
    except KeyError as exc:
        raise ValueError("unknown premise constructor") from exc


@dataclass(frozen=True)
class FactCandidate:
    relation: str
    semantic_kind: str
    proof_path: str


def necessary_relations(proof, path):
    """Only accepted roots and their necessary domain nodes, not search debris."""
    by_id = {n["node_id"]: n for n in proof["nodes"]}
    roots = set(proof["roots"])
    pending, used = list(roots), set()
    while pending:
        key = pending.pop()
        if key in used:
            continue
        used.add(key)
        pending.extend(by_id[key]["children"])
    for key in sorted(used):
        relation = freeze(by_id[key]["conclusion"])
        if not _relation(relation):
            continue
        domain = relation[0] in (">", ">=", "!=") and relation[2] == ZERO
        # Internal identities are not automatically published. Only explicit
        # accepted roots or necessary positivity/nonzero facts are selected.
        if key in roots or domain:
            kind = (
                "domain" if domain else "identity" if relation[0] == "=" else "relation"
            )
            yield FactCandidate(_text(relation), kind, f"{path}/nodes/{key}")


def replay_method(method_id, target, evidence):
    """Replay existing Method evidence, then project only certified operations.

    target is supplied by Runtime admission, never trusted from the evidence.
    Return names of definitions separately so Runtime gives them fresh identity.
    M13 witness/attainment hypotheses intentionally have no publication adapter.
    """
    certificates = []
    definitions = {}
    requirements = ()
    certified_bounds = []
    if method_id == "substitute_expressions":
        from ..math_kernel.substitution import replay_substitution

        replay_substitution(target, evidence)
        definitions = evidence["definitions"]
        certificates = [
            (f"certificates/relations/{i}", p)
            for i, p in enumerate(evidence["certificates"]["relations"])
        ]
    elif method_id == "eliminate_by_constraint":
        from ..math_kernel.constraint_elimination import replay_elimination

        replay_elimination(target, evidence)
        certificates = [(f"proofs/{i}", p) for i, p in enumerate(evidence["proofs"])]
    elif method_id in ("apply_two_term_amgm", "bound_univariate_quadratic"):
        from ..math_kernel.bound_chain import replay_bound
        from ..math_kernel.inequality_bound_v2 import public

        rebuilt = replay_bound(target, evidence)
        expected = (
            "quadratic-bound/v1"
            if method_id == "bound_univariate_quadratic"
            else "amgm-bound/v2"
        )
        if public(rebuilt)["schema_version"] != expected:
            raise ValueError("evidence does not match producer Method")
        requirements = ((rebuilt["equality"], "applications/current"),)
        certified_bounds = [
            FactCandidate(
                f"({rebuilt['target_math']}){rebuilt['direction']}({rebuilt['bound']})",
                "bound",
                "certified_bound",
            )
        ]
        certificates = [(f"proofs/{i}", p) for i, p in enumerate(rebuilt["proofs"])]
        certificates += [
            (f"derivation/proofs/{i}", p)
            for i, p in enumerate(rebuilt["derivation"]["proofs"])
        ]
    else:
        raise ValueError("unregistered Method fact adapter")
    candidates = [
        FactCandidate(f"{n}=({s})", "definition", f"definitions/{n}")
        for n, s in definitions.items()
    ]
    candidates.extend(certified_bounds)
    for path, proof in certificates:
        candidates.extend(necessary_relations(proof, path))
    # Stable source identity remains separate even for equal statements.
    return tuple(candidates), tuple(definitions), requirements


METHOD_PUBLISHERS = (
    "substitute_expressions",
    "eliminate_by_constraint",
    "apply_two_term_amgm",
    "bound_univariate_quadratic",
    "organize_expressions",
    "verified_relation",
)


def validate_application_binding(evidence, call, manifest):
    """Current operation uses the producer's exact input authority, not a consumer's."""
    from ..math_kernel.proof_algebra import ProofFailure
    bundle = evidence.get("certificate_bundle", evidence)
    app = bundle.get("method_application")
    if app is None and isinstance(bundle.get("reciprocal_bound"), dict):
        return validate_application_binding(bundle["reciprocal_bound"], call, manifest)
    if call.method_id == "apply_two_term_amgm" and app is None:
        raise ProofFailure("invalid_proof", "new Method execution requires current application evidence")
    if app is not None and app.get("binding") != {
        "producer_call_id": call.call_id,
        "source_binding_fingerprint": call.input_fingerprint,
        "scope_id": call.scope_id,
        "committed_manifest_hash": manifest,
    }:
        raise ProofFailure("invalid_proof", "current application input authority changed")
