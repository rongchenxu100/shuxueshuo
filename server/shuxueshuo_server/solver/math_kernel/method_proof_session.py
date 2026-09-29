"""Execution-scoped search and checked-result handoff to Runtime publication.

Runtime installs a read-only service for exactly one Method invocation. The
kernel depends on this protocol, never on RuntimeContext or a global fact store.
The independent checker and explicit certificate replay never consult receipts.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
from functools import wraps

from .proof_algebra import ZERO, ProofFailure, freeze, from_node, names
from .proof_search import default_search_configuration, run_scheduled_request

_ACTIVE = ContextVar("method_proof_session", default=None)


def active_session():
    return _ACTIVE.get()


def record_checked_bound(verify):
    """Pass a successful kernel result to this invocation's publication step."""
    @wraps(verify)
    def checked(target, *args, **kwargs):
        result = verify(target, *args, **kwargs)
        session = active_session()
        if session is not None and kwargs.get("certificates") is None:
            session.remember_bound(target, result)
        return result
    return checked


@contextmanager
def use_proof_session(session):
    token = _ACTIVE.set(session)
    try:
        yield session
    finally:
        _ACTIVE.reset(token)


class MethodProofSession:
    """Per-call search with verified fragments and explicit actual-read callback."""

    def __init__(
        self,
        *,
        fragments=(),
        on_read=None,
        manifest_hash="local/v1",
        policy=None,
        application_binding=None,
        resolve_bound=None,
    ):
        self.fragments = {}
        for fragment in fragments:
            _, proof, root = fragment
            node = next(n for n in proof["nodes"] if n["node_id"] == root)
            self.fragments.setdefault(freeze(node["conclusion"]), []).append(fragment)
        self.application_binding = application_binding or {}
        self.local_fragments = {}
        self.on_read = on_read
        self.manifest_hash = manifest_hash
        self.policy = policy or replace(
            default_search_configuration()[2],
            version="layered-method-search/v2",
            branch_attempts=256,
            branch_reductions=256,
            branch_nodes=512,
        )
        self.runs = []
        self.recorded_reads = set()
        self.resolve_bound = resolve_bound
        self._checked_certificates = {}
        self._checked_bounds = []

    def remember_bound(self, target, result):
        from .inequality_bound_v2 import public

        self._checked_bounds.append((deepcopy(target), public(result)))

    def checked_bound(self, target, evidence):
        from .bound_chain import unpack_bound

        for original, checked in self._checked_bounds:
            if original == target and checked == evidence:
                return unpack_bound(checked)
        return None

    def accepts_certificate(self, proof, context):
        return any(
            proof == checked and context == original
            for checked, original in self._checked_certificates.get(proof.get("context_hash"), ())
        )

    def seed(self, engine, goal):
        from .proof_algebra import names
        from .proof_checker import fact_key

        current = {fact_key(p): key for key, p in engine.premises.items()}
        candidates = []
        for fact_id, proof, root in (
            *self.fragments.get(goal, ()),
            *self.local_fragments.get(goal, ()),
        ):
            nodes = {n["node_id"]: n for n in proof["nodes"]}
            if root not in nodes or freeze(nodes[root]["conclusion"]) != goal:
                continue
            used, pending = set(), [root]
            while pending:
                key = pending.pop()
                if key in used:
                    continue
                used.add(key)
                pending.extend(nodes[key]["children"])
            candidates.append((len(used), fact_id, proof, root, nodes, used))
        # A store can contain several certificates for one relation. Prefer
        # the smallest reachable graph, not the first historical producer.
        # Stable sorting preserves publication order for equal costs.
        for _, fact_id, proof, root, nodes, used in sorted(candidates, key=lambda c: c[0]):
            from .expression_parser import parse_math_relation

            imports = {}
            for source, document in proof["sources"].items():
                if not source.startswith("premise:"):
                    continue
                try:
                    relation = (
                        freeze(document["expression"])
                        if "expression" in document
                        else from_node(
                            parse_math_relation(document["source"], engine.symbols).ast
                        )
                    )
                except ValueError:
                    continue
                mapped = current.get(fact_key(relation))
                if mapped is not None:
                    imports[source.removeprefix("premise:")] = mapped
            for key in used:
                node = nodes[key]
                if not names(freeze(node["conclusion"])) <= engine.symbols.keys():
                    break
                cert = node["certificate"]
                references = [
                    cert[f]
                    for f in (
                        "premise_id",
                        "sum_premise",
                        "amgm_premise",
                        "lower",
                        "upper",
                    )
                    if f in cert
                ]
                references += cert.get("equations", [])
                references += [b["premise_id"] for b in cert.get("bindings", ())]
                # A given of a derived relation can be replaced by a checked
                # proof in the destination. Other rules' named-premise fields
                # still require exact original-premise mappings.
                if node["rule_id"] == "math.given":
                    conclusion = freeze(node["conclusion"])
                    if cert["premise_id"] not in imports and (
                        conclusion == goal
                        or conclusion in getattr(engine, "active", ())
                        or (conclusion not in self.fragments
                            and conclusion not in self.local_fragments)
                    ):
                        break
                    references = []
                if not set(references) <= imports.keys():
                    break
            else:
                saved = engine.checkpoint()
                mapping = {}
                try:
                    for node in proof["nodes"]:
                        if node["node_id"] not in used:
                            continue
                        certificate = deepcopy(node["certificate"])
                        if (node["rule_id"] == "math.given"
                                and certificate["premise_id"] not in imports):
                            checked = engine.need(freeze(node["conclusion"]))
                            # Historical given nodes are unguarded cores; the
                            # historical guard is imported separately below.
                            mapping[node["node_id"]] = engine.by_id[checked].children[0]
                            continue
                        for field in (
                            "premise_id",
                            "sum_premise",
                            "amgm_premise",
                            "lower",
                            "upper",
                        ):
                            if field in certificate:
                                certificate[field] = imports[certificate[field]]
                        if "equations" in certificate:
                            certificate["equations"] = [
                                imports[k] for k in certificate["equations"]
                            ]
                        for entry in certificate.get("bindings", ()):
                            entry["premise_id"] = imports[entry["premise_id"]]
                        mapping[node["node_id"]] = engine.add(
                            node["rule_id"].removeprefix("math."),
                            freeze(node["conclusion"]),
                            [mapping[c] for c in node["children"]],
                            certificate,
                        )
                    core = (
                        nodes[root]["children"][0]
                        if nodes[root]["rule_id"] == "math.guard"
                        else root
                    )
                    result = mapping[core]
                    # The fragment was rechecked against the destination's
                    # actual source premises; it never becomes a trusted given.
                    if fact_id is not None:
                        engine.seed_reads[result] = fact_id
                    return result
                except ProofFailure as exc:
                    engine.rollback(saved)
                    if exc.code in {"proof_missing", "strategy_not_applicable"} or exc.is_structure_limit:
                        continue
                    # Shared/ancestor leases cannot be reset by trying another
                    # fragment; malformed checked evidence must also surface.
                    raise
                except KeyError:
                    engine.rollback(saved)
                    raise
        return None

    def run_request(self, context, request, *, budget=None):
        from dataclasses import replace

        from .amgm_application import copy_nodes
        from .proof_checker import _Environment, _replay, _roots_for_request
        from .proof_fact_index import ProofFactIndex
        from .proof_facts import FactValidity, VerifiedMathFact
        from .proof_types import _Budget

        budget = budget or _Budget(context.limits)
        # Existing Method-local premises keep their semantics and source IDs.
        # The D index selects small views; it grants no new premise authority.
        bindings = tuple((n, n) for n in context.symbols)
        local = [
            VerifiedMathFact(
                p.source, bindings, FactValidity(context.scope_id), "relation", key
            )
            for key, p in context.premises.items()
        ]
        index = ProofFactIndex(local, context.symbols, limit=self.policy.fact_limit)
        roots = _roots_for_request(_Environment(context, request))
        ids = []
        for root in roots:
            goals = root[1:] if root[0] == "all" else (root,)
            for goal in goals:
                queried, _ = index.query(
                    goal, bindings, limit=self.policy.retrieval_limit
                )
                # An existing bound is a better transport premise than a large
                # unrelated equation basis. Keep its sign/domain prerequisites
                # next, using the index's deterministic order.
                transport = [
                    ref
                    for ref in queried
                    if goal[0] in {"<", "<=", ">", ">="}
                    and index.trees[ref][0] == goal[0]
                    and index.trees[ref][2] != ZERO
                    and names(index.trees[ref]) <= names(goal)
                ]
                ids.extend(ref for ref in (*transport, *queried) if ref not in ids)
        # Preserve original constant premises and eventually every admissible
        # local premise, including assumptions with no adjacent goal symbols.
        ids.extend(ref for ref in index.facts if ref not in ids)
        sizes = sorted({min(n, len(ids)) for n in (4, 8, len(ids))})
        # Small retrieval views must retain the local scalar order/sign basis.
        # A retrieved bound does not replace a>b, b>c, c>0 when proving the
        # original denominator guards. Losing that basis makes each widening
        # retry search an impossible sign problem before it sees the premises.
        sign_basis = {
            key for key, parsed in context.premises.items()
            if (tree := from_node(parsed.ast))[0] != "="
            and all(side[0] in {"symbol", "rat"} for side in tree[1:])
        }
        # Keep complete already-submitted order paths together. Selecting only
        # F>=G while dropping G>=k makes even a two-edge transitivity request
        # repeat its domain proof in every widening view.
        from .proof_checker import _ordered

        edges = [(key, _ordered(from_node(p.ast))) for key, p in context.premises.items()]
        for root in roots:
            ordered = _ordered(root) if root[0] != "all" else None
            if not ordered:
                continue
            compatible = [(key, p) for key, p in edges if p and p[0] == ordered[0]]
            forward, backward = {ordered[1]}, {ordered[2]}
            for _ in range(len(compatible)):
                before = len(forward), len(backward)
                for _, p in compatible:
                    if p[1] in forward:
                        forward.add(p[2])
                    if p[2] in backward:
                        backward.add(p[1])
                if before == (len(forward), len(backward)):
                    break
            sign_basis.update(key for key, p in compatible
                              if p[1] in forward and p[2] in backward)
        selections = []
        for size in sizes:
            keys = sign_basis | {index.facts[ref].source for ref in ids[:size]}
            if keys not in selections:
                selections.append(keys)
        for position, keys in enumerate(selections):
            selected = replace(
                context,
                premises={k: p for k, p in context.premises.items() if k in keys},
            )
            run = run_scheduled_request(
                selected,
                request,
                budget=budget,
                policy=self.policy,
                manifest_hash=self.manifest_hash,
                seed_provider=self.seed,
                request_quota={
                    r: max(
                        1,
                        (getattr(budget.limits, r) - budget.counts.get(r, 0))
                        // (len(selections) - position),
                    )
                    # Split speculative search work, not the certificate's
                    # minimum footprint: a valid DAG may need more than 1/N
                    # of the remaining nodes in every view. Global node and
                    # per-candidate node limits still apply without refunds.
                    for r in ("attempts", "reductions")
                }
                if position < len(selections) - 1
                else None,
            )
            self.runs.append(run.diagnostics)
            if run.result.status == "proved":
                # The scheduler independently checked this exact context. Only
                # a changed premise set needs certificate rebinding and replay.
                if selected == context:
                    proof = run.result.proof
                else:
                    env = _Environment(context, request)
                    proof = env.payload(copy_nodes(run.result.proof, env))
                    _replay(proof, context)
                for root_id in proof["roots"]:
                    node = next(n for n in proof["nodes"] if n["node_id"] == root_id)
                    conclusion = freeze(node["conclusion"])
                    if conclusion[0] != "all":
                        if len(self.local_fragments) >= 64:
                            self.local_fragments.pop(next(iter(self.local_fragments)))
                        # A prior request recorded its shared producer reads
                        # in this call's overlay before entering this cache.
                        self.local_fragments[conclusion] = [(None, proof, root_id)]
                if self.on_read and run.diagnostics.get("fact_reads"):
                    fresh_reads = tuple(
                        sorted(set(run.diagnostics["fact_reads"]) - self.recorded_reads)
                    )
                    if fresh_reads:
                        self.on_read(fresh_reads)
                        self.recorded_reads.update(fresh_reads)
                self._checked_certificates.setdefault(proof.get("context_hash"), []).append(
                    (deepcopy(proof), deepcopy(context))
                )
                return replace(run.result, proof=proof)
            if run.result.code not in {"proof_missing", "strategy_budget_exhausted"}:
                break
        raise ProofFailure(run.result.code, run.result.diagnostic)
