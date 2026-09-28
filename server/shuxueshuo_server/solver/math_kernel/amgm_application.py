"""Method-owned application anchors, independent of search dependency nodes."""

from copy import deepcopy

from .expression_parser import parse_math_expression, parse_math_relation
from .local_amgm import candidates
from .local_bound_contract import verify_local_application
from .proof_algebra import (
    ProofFailure,
    commutative_key,
    digest,
    domains,
    freeze,
    from_node,
    walk,
)
from .proof_checker import _document, _Environment, _replay
from .proof_types import _Budget


def verify_upper_effect(context, source, bound, u, v, *, budget, certificates=None):
    from .inequality_bound_v2 import math_text
    from .proof_kernel import verify_relation_sequence

    relations = [
        f"({source})=({math_text(u)})*({math_text(v)})",
        f"({bound})=(({math_text(u)})+({math_text(v)}))^2/4",
    ]
    if certificates is not None and certificates["relations"] != relations:
        raise ProofFailure("invalid_proof", "upper-bound application changed")
    proofs = verify_relation_sequence(
        [parse_math_relation(r, context.symbols) for r in relations],
        context,
        budget=budget,
        certificates=certificates["proofs"] if certificates else None,
    )
    return {"relations": relations, "proofs": proofs}


def copy_nodes(proof, env):
    """Reconstruct a checked DAG in the destination context, never copy authority."""
    mapping = {}
    for node in proof["nodes"]:
        mapping[node["node_id"]] = env.add(
            node["rule_id"].removeprefix("math."),
            freeze(node["conclusion"]),
            [mapping[c] for c in node["children"]],
            deepcopy(node["certificate"]),
        )
    return [mapping[r] for r in proof["roots"]]


def candidate_pairs(tree):
    for node in walk(tree):
        if node[0] in {"add", "sub"}:
            yield from ((u, v) for u, v, _, _ in candidates(node))
        elif node[0] == "mul":
            yield node[1:]


def application_candidates(source, chain, symbols):
    # Only current input/submitted mathematics proposes this operation.
    seen = set()
    trees = [from_node(parse_math_expression(source, symbols).ast)]
    trees.extend(from_node(row.parsed.ast) for row in chain)
    for tree in trees:
        for u, v in candidate_pairs(tree):
            key = commutative_key(("add", u, v))
            if key not in seen:
                seen.add(key)
                if len(seen) > 128:
                    raise ProofFailure("proof_limit", "application candidate limit")
                yield u, v


def local_rule_origin(source, chain, u, v):
    """Locate the submitted pair, preferring an inequality over setup identities.

    The rule root itself is constructed by the Method. This records the source
    of its operands, not a claim that arbitrary row text proves the rule.
    """
    key = commutative_key(("add", u, v))
    for row in sorted(chain, key=lambda r: r.parsed.ast.op not in {"<=", ">="}):
        if any(
            commutative_key(("add", a, b)) == key
            for a, b in candidate_pairs(from_node(row.parsed.ast))
        ):
            return {"kind": "submitted_relation", "origin": row.origin}
    return {"kind": "source_expression", "math": source}


def verify_application(
    context, target, source, bound, chain, *, budget, certificate=None
):
    from .inequality_bound_v2 import math_text
    from .method_proof_session import active_session
    from .proof_algebra import Arithmetic
    from .proof_kernel import _run_request

    session = active_session()
    binding = (
        certificate.get("binding", {})
        if certificate is not None
        else (session.application_binding if session else {})
    )
    arithmetic = Arithmetic(_Budget(budget.limits))
    lhs = from_node(parse_math_expression(source, context.symbols).ast)
    rhs = from_node(parse_math_expression(bound, context.symbols).ast)
    if not arithmetic.difference(("=", lhs, rhs)):
        raise ProofFailure(
            "inequality_template_unmatched",
            "unchanged old bound is not a current application",
        )
    options = list(application_candidates(source, chain, context.symbols))
    if certificate is not None:
        pair = tuple(freeze(t) for t in certificate["terms_ast"])
        if pair not in options:
            raise ProofFailure("invalid_proof", "application terms not submitted")
        options = [pair]
    accepted = []
    for u, v in options:
        try:
            try:
                effect_verifier = (
                    verify_upper_effect
                    if target["goal_kind"] == "find_maximum"
                    else verify_local_application
                )
                effect = effect_verifier(
                    context,
                    source,
                    bound,
                    u,
                    v,
                    budget=budget,
                    certificates=certificate["effect"] if certificate else None,
                )
            except ProofFailure as exc:
                # A speculative effect outside the finite algebra profile is
                # unavailable. This does not enlarge search or replay budgets.
                if certificate is None and exc.code == "proof_limit":
                    continue
                raise
            relation = f"({math_text(u)})+({math_text(v)})>=2*sqrt(({math_text(u)})*({math_text(v)}))"
            parsed = parse_math_relation(relation, context.symbols)
            if certificate is None:
                env = _Environment(
                    context,
                    {"kind": "relation", "candidate": _document(parsed)},
                    budget=_Budget(budget.limits),
                )
                children = []
                for term in (u, v):
                    positive = parse_math_relation(
                        f"({math_text(term)})>0", context.symbols
                    )
                    proof = _run_request(
                        context,
                        {"kind": "relation", "candidate": _document(positive)},
                        budget=budget,
                    ).proof
                    _replay(proof, context)
                    children.extend(copy_nodes(proof, env))
                root = env.add("two_term_amgm", from_node(parsed.ast), children)
                guards = []
                from .proof_checker import _text

                for obligation in domains(from_node(parsed.ast)):
                    assertion = parse_math_relation(_text(obligation), context.symbols)
                    checked = _run_request(
                        context,
                        {"kind": "relation", "candidate": _document(assertion)},
                        budget=budget,
                    ).proof
                    _replay(checked, context)
                    guards.extend(copy_nodes(checked, env))
                guarded = env.add("guard", from_node(parsed.ast), [root, *guards])
                proof = env.payload([guarded])
            else:
                proof = certificate["local_proof"]
                root = certificate["local_rule_root_ref"]
                if proof["request"] != {
                    "kind": "relation",
                    "candidate": _document(parsed),
                }:
                    raise ProofFailure("invalid_proof", "application rule changed")
            _replay(proof, context)
            roots = {n["node_id"]: n for n in proof["nodes"]}
            if (
                root not in roots[proof["roots"][0]]["children"]
                or roots[root]["rule_id"] != "math.two_term_amgm"
            ):
                raise ProofFailure(
                    "invalid_proof",
                    "current application requires a checked local rule root",
                )
            body = {
                "schema_version": "verified-amgm-application/v1",
                "target_hash": digest(target),
                "source_math": source,
                "bound": bound,
                "binding": binding,
                "submitted_relation_origins": [r.origin for r in chain],
                "terms_ast": [u, v],
                "terms": [math_text(u), math_text(v)],
                "local_rule_relation": relation,
                "local_rule_root_ref": root,
                "local_proof": proof,
                "effect": effect,
                "equality": f"({math_text(u)})=({math_text(v)})",
            }
            # Older application/v1 records remain replayable without this
            # optional provenance refinement. New records always include it.
            if certificate is None or "local_rule_origin" in certificate:
                body["local_rule_origin"] = local_rule_origin(source, chain, u, v)
            # JSON normal form is part of the recorded application identity.
            import json

            body = json.loads(json.dumps(body))
            body["application_id"] = digest(body)
            if certificate is not None and body != certificate:
                raise ProofFailure(
                    "invalid_proof", "application anchor or effect changed"
                )
            accepted.append(body)
            # Commit one canonical effect and one explicit rule root. Other
            # spellings/templates may prove the same full-expression change;
            # they do not become additional applications.
            break
        except ProofFailure as exc:
            if certificate is not None or exc.code not in {
                "amgm_remainder_changed",
                "proof_missing",
                "strategy_budget_exhausted",
            }:
                raise
    if not accepted:
        raise ProofFailure(
            "amgm_remainder_changed",
            "one local AM-GM application must preserve the complete remainder; use M12 for a separate square bound",
        )
    return accepted[0]
