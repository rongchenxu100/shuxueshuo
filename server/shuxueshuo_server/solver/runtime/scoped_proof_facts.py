"""Execution-prefix fact snapshots, checked overlays and atomic publication.

Internal opt-in service. Authority is supplied by Runtime, never by a certificate
or a Planner parameter. The legacy Method/teaching path remains unchanged.
"""

import json
from dataclasses import asdict, dataclass, replace

import sympy as sp

from ..math_kernel.expression_parser import parse_math_relation
from ..math_kernel.proof_algebra import digest, from_node
from ..math_kernel.proof_checker import replay_proof
from ..math_kernel.proof_facts import (
    AttainmentRequirement,
    FactValidity,
    VerifiedMathFact,
    canonical,
    default_fact_kinds,
)
from ..math_kernel.proof_types import ProofContext, ProofLimits
from .proof_evidence_adapters import (
    METHOD_PUBLISHERS,
    necessary_relations,
    premise_policy,
    replay_method,
)

CONTRACT = "scoped-proof-facts/v1"


def require(condition, message):
    if not condition:
        raise ValueError("proof_facts: " + message)


def bindings_symbols(bindings):
    return {name: sp.Symbol(name, real=True) for name, _ in bindings}


@dataclass(frozen=True)
class ProofCallAuthority:
    call_id: str
    scope_id: str
    method_id: str
    symbol_bindings: tuple[tuple[str, str], ...]
    validity: FactValidity
    input_fingerprint: str
    dependencies: tuple[str, ...] = ()
    allowed_kinds: tuple[str, ...] = ("domain", "identity", "relation", "bound")
    target_json: str | None = None

    @property
    def fingerprint(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class FactCommit:
    call_id: str
    authority_hash: str
    predecessor_manifest: str
    output_hash: str
    records_json: str
    facts: tuple[VerifiedMathFact, ...]
    proof_reads: tuple[str, ...]
    dependencies: tuple[str, ...]
    requirements: tuple[AttainmentRequirement, ...] = ()

    @property
    def commit_id(self):
        return digest(
            (
                self.call_id,
                self.authority_hash,
                self.predecessor_manifest,
                self.output_hash,
                self.records_json,
            )
        )

    def to_payload(self):
        return {
            "call_id": self.call_id,
            "authority_hash": self.authority_hash,
            "predecessor_manifest": self.predecessor_manifest,
            "output_hash": self.output_hash,
            "records": json.loads(self.records_json),
            "facts": [f.to_payload() for f in self.facts],
            "proof_reads": list(self.proof_reads),
            "dependencies": list(self.dependencies),
            "commit_id": self.commit_id,
            "requirements": json.loads(
                canonical([asdict(r) for r in self.requirements])
            ),
        }


@dataclass(frozen=True)
class FactSnapshot:
    source_hash: str
    roots: tuple[VerifiedMathFact, ...]
    commits: tuple[FactCommit, ...] = ()

    @property
    def facts(self):
        return self.roots + tuple(f for c in self.commits for f in c.facts)

    @property
    def committed_manifest_hash(self):
        return digest((self.source_hash, [c.to_payload() for c in self.commits]))


@dataclass(frozen=True)
class ProofEnvironmentView:
    committed_manifest_hash: str
    call_id: str
    facts: tuple[VerifiedMathFact, ...]


class ScopedProofFacts:
    """Runtime-bound service; snapshots are immutable and branch forks share them.

    `source_context` and symbol identities must come from authenticated input
    binding (or explicit authoring fixtures). Never rebuild them from a saved
    proof bundle. `runtime_context.is_visible` is the existing Scope authority.
    """

    def __init__(
        self,
        runtime_context,
        source_context,
        symbol_bindings,
        calls,
        *,
        registry=None,
        snapshot=None,
    ):
        self.context = runtime_context
        self.source_context = source_context
        self.bindings = tuple(sorted(symbol_bindings))
        self.calls = tuple(calls)
        self.registry = registry or default_fact_kinds(METHOD_PUBLISHERS)
        self._verified_snapshots = set()
        self._verification_registry = self.registry
        require(
            len({c.call_id for c in calls}) == len(calls), "duplicate canonical call"
        )
        require(
            set(dict(self.bindings)) == set(source_context.symbols),
            "source symbol identities incomplete",
        )
        require(
            len({v for _, v in self.bindings}) == len(self.bindings),
            "duplicate source symbol identity",
        )
        source_scope = source_context.scope_id
        require(source_scope in runtime_context.scopes, "unknown source Scope")
        roots = tuple(
            VerifiedMathFact(
                p.source,
                self.bindings,
                FactValidity(source_scope),
                "relation",
                f"source:{key}",
            )
            for key, p in sorted(source_context.premises.items())
        )
        source_hash = digest(
            (
                [f.to_payload() for f in roots],
                [
                    (k, p.source_path, p.step)
                    for k, p in sorted(source_context.premises.items())
                ],
            )
        )
        self.snapshot = snapshot or FactSnapshot(source_hash, roots)
        require(
            self.snapshot.source_hash == source_hash and self.snapshot.roots == roots,
            "source authority changed",
        )
        order = {c.call_id: i for i, c in enumerate(calls)}
        for call in calls:
            require(
                call.scope_id == call.validity.scope_id,
                "publication Scope differs from call Scope",
            )
            require(call.scope_id in runtime_context.scopes, "unknown call Scope")
            require(
                len(dict(call.symbol_bindings)) == len(call.symbol_bindings),
                "duplicate symbol name",
            )
            require(
                len(set(dict(call.symbol_bindings).values()))
                == len(call.symbol_bindings),
                "duplicate symbol identity",
            )
            require(
                all(
                    d in order and order[d] < order[call.call_id]
                    for d in call.dependencies
                ),
                "future or cyclic explicit dependency",
            )

    def fork(self, runtime_context):
        forked = ScopedProofFacts(
            runtime_context,
            self.source_context,
            self.bindings,
            self.calls,
            registry=self.registry,
            snapshot=self.snapshot,
        )
        self._verification_key()  # Clear stale registry authority before sharing.
        forked._verified_snapshots = set(self._verified_snapshots)
        return forked

    def authority(self, call_id):
        return next(c for c in self.calls if c.call_id == call_id)

    def begin(self, call_id):
        authority = self.authority(call_id)
        order = {c.call_id: i for i, c in enumerate(self.calls)}
        committed = {c.call_id for c in self.snapshot.commits}
        require(call_id not in committed, "call already committed")
        require(
            all(order[c] < order[call_id] for c in committed), "non-prefix execution"
        )
        require(
            set(authority.dependencies) <= committed, "uncommitted explicit dependency"
        )
        # Replay every producer before exposing any of its relations. No search.
        self.verify_snapshot()
        symbols = dict(authority.symbol_bindings)
        facts = tuple(
            f
            for f in self.snapshot.facts
            if self.context.is_visible(authority.scope_id, f.validity.scope_id)
            and authority.validity.includes(f.validity)
            and all(symbols.get(n) == identity for n, identity in f.symbol_bindings)
        )
        return SessionFactOverlay(
            self,
            authority,
            ProofEnvironmentView(self.snapshot.committed_manifest_hash, call_id, facts),
        )

    def verify_snapshot(self):
        if not self.snapshot.commits:
            return
        cache_key = self._verification_key()
        if cache_key in self._verified_snapshots:
            return
        fresh = ScopedProofFacts(
            self.context,
            self.source_context,
            self.bindings,
            self.calls,
            registry=self.registry,
        )
        for saved in self.snapshot.commits:
            fresh._restore_one(saved.to_payload())
        require(fresh.snapshot == self.snapshot, "fact snapshot changed")
        self._remember_verified_snapshot()

    def _verification_key(self):
        # Retain the trusted registry itself: distinct callbacks with identical
        # qualified names must never share a memo, nor can recycled addresses.
        if self._verification_registry is not self.registry:
            self._verified_snapshots.clear()
            self._verification_registry = self.registry

        def qualified(value):
            return (value.__module__, value.__qualname__)

        registry_structure = (
            qualified(type(self.registry)),
            [
                (
                    k.kind,
                    k.publishers,
                    k.unconditional,
                    qualified(k.identity_key),
                    qualified(k.index_keys),
                    qualified(k.publishable),
                )
                for k in self.registry.kinds
            ],
        )
        # Full content plus current host authority, never just a claimed hash.
        return digest(
            (
                self.snapshot.committed_manifest_hash,
                self.snapshot.source_hash,
                self.bindings,
                [f.to_payload() for f in self.snapshot.roots],
                repr(self.source_context),
                [c.fingerprint for c in self.calls],
                repr(self.context.scopes),
                registry_structure,
            )
        )

    def _remember_verified_snapshot(self):
        if len(self._verified_snapshots) >= 64:
            self._verified_snapshots.clear()
        self._verified_snapshots.add(self._verification_key())

    def _restore_one(self, payload):
        authority = self.authority(payload["call_id"])
        order = {c.call_id: i for i, c in enumerate(self.calls)}
        committed = {c.call_id for c in self.snapshot.commits}
        require(
            authority.call_id not in committed
            and all(order[c] < order[authority.call_id] for c in committed),
            "non-prefix restored execution",
        )
        require(
            set(authority.dependencies) <= committed, "uncommitted restored dependency"
        )
        require(
            authority.fingerprint == payload["authority_hash"],
            "producer binding changed",
        )
        require(
            payload["predecessor_manifest"] == self.snapshot.committed_manifest_hash,
            "committed manifest changed",
        )
        # No recursive snapshot verification: previous producers already passed.
        symbols = dict(authority.symbol_bindings)
        facts = tuple(
            f
            for f in self.snapshot.facts
            if self.context.is_visible(authority.scope_id, f.validity.scope_id)
            and authority.validity.includes(f.validity)
            and all(symbols.get(n) == identity for n, identity in f.symbol_bindings)
        )
        overlay = SessionFactOverlay(
            self,
            authority,
            ProofEnvironmentView(
                self.snapshot.committed_manifest_hash, authority.call_id, facts
            ),
        )
        for record in payload["records"]:
            overlay.replay_record(record)
        restored = overlay.finish(payload["output_hash"])
        require(
            restored.to_payload() == payload, "commit evidence or dependencies changed"
        )
        self.snapshot = replace(
            self.snapshot, commits=(*self.snapshot.commits, restored)
        )

    def commit(self, overlay, output_hash):
        require(overlay.owner is self, "foreign transaction")
        require(
            overlay.view.committed_manifest_hash
            == self.snapshot.committed_manifest_hash,
            "stale transaction snapshot",
        )
        self.verify_snapshot()
        commit = overlay.finish(output_hash)
        verifier = self.fork(self.context)
        verifier._restore_one(commit.to_payload())
        self.snapshot = verifier.snapshot
        self._remember_verified_snapshot()
        overlay.closed = True
        return commit

    def to_payload(self):
        return {
            "schema_version": CONTRACT,
            "source_hash": self.snapshot.source_hash,
            "commits": [c.to_payload() for c in self.snapshot.commits],
            "committed_manifest_hash": self.snapshot.committed_manifest_hash,
        }

    def restore(self, payload, output_hashes):
        require(
            set(payload)
            == {"schema_version", "source_hash", "commits", "committed_manifest_hash"}
            and payload["schema_version"] == CONTRACT,
            "invalid checkpoint",
        )
        require(
            payload["source_hash"] == self.snapshot.source_hash,
            "checkpoint source changed",
        )
        fresh = ScopedProofFacts(
            self.context,
            self.source_context,
            self.bindings,
            self.calls,
            registry=self.registry,
        )
        for item in payload["commits"]:
            require(
                output_hashes.get(item["call_id"]) == item["output_hash"],
                "checkpoint outputs not authenticated",
            )
            fresh._restore_one(item)
        require(fresh.to_payload() == payload, "checkpoint manifest mismatch")
        self.snapshot = fresh.snapshot
        self._remember_verified_snapshot()

    def dependency_closure(self, call_ids):
        by_call = {c.call_id: c for c in self.snapshot.commits}
        pending, found = list(call_ids), set()
        while pending:
            call = pending.pop()
            if call in found:
                continue
            require(call in by_call, "uncommitted dependency")
            found.add(call)
            pending.extend(by_call[call].dependencies)
        return frozenset(found)

    def invalidate(self, call_ids):
        # Exact-prefix certificates bind the full manifest. Conservative first
        # implementation invalidates the suffix, including unaffected siblings;
        # it never relabels old certificates for a different snapshot.
        cut = next(
            (i for i, c in enumerate(self.snapshot.commits) if c.call_id in call_ids),
            len(self.snapshot.commits),
        )
        invalidated = tuple(c.call_id for c in self.snapshot.commits[cut:])
        self.snapshot = replace(self.snapshot, commits=self.snapshot.commits[:cut])
        return invalidated


class SessionFactOverlay:
    def __init__(self, owner, authority, view):
        self.owner, self.authority, self.view = owner, authority, view
        self._records = []
        self._candidates = []
        self._reads = set()
        self._requirements = []
        self.closed = False
        self._search_session = None

    def prove_scheduled(
        self, relation, *, semantic_kind="relation", limits=None, policy=None
    ):
        """Internal D entry: authorized retrieval, scheduled search, strict admission."""
        from ..math_kernel.proof_algebra import ProofFailure
        from ..math_kernel.proof_search_session import ProofSearchSession

        require(not self.closed, "closed transaction")
        if self._search_session is None:
            self._search_session = ProofSearchSession(policy=policy, limits=limits)
        else:
            require(
                limits is None or limits == self._search_session.limits,
                "search limits cannot change within a session",
            )
            require(
                policy is None or policy == self._search_session.policy,
                "search policy cannot change within a session",
            )
        session = self._search_session
        result = session.prove(
            relation,
            facts=tuple(
                fact
                for fact in (*self.view.facts, *self._candidates)
                if self.authority.validity.includes(fact.validity)
            ),
            symbols=bindings_symbols(self.authority.symbol_bindings),
            bindings=self.authority.symbol_bindings,
            scope_id=self.authority.scope_id,
            manifest_hash=self.view.committed_manifest_hash,
            authority_hash=self.authority.fingerprint,
        )
        if result.result.status != "proved":
            raise ProofFailure(result.result.code, result.result.diagnostic)
        return self.replay_record(
            {
                "kind": "relation",
                "relation": relation,
                "semantic_kind": semantic_kind,
                "fact_ids": list(result.context.premises),
                "limits": asdict(session.limits),
                "proof": result.result.proof,
                "search": {
                    "policy": asdict(session.policy),
                    "policy_hash": session.policy.fingerprint,
                    "manifest_hash": self.view.committed_manifest_hash,
                    "authority_hash": self.authority.fingerprint,
                },
            }
        )

    def _selected(self, ids):
        require(not self.closed, "closed transaction")
        available = {f.fact_id: f for f in self.view.facts}
        available.update((f.fact_id, f) for f in self._candidates)
        require(len(set(ids)) == len(ids), "duplicate premise import")
        require(set(ids) <= available.keys(), "fact invisible, stale or not committed")
        return tuple(available[k] for k in ids)

    def _context(self, facts, limits):
        symbols = bindings_symbols(self.authority.symbol_bindings)
        return ProofContext(
            symbols,
            {
                f.fact_id: replace(
                    parse_math_relation(f.relation, symbols),
                    source_path=f"fact:{f.fact_id}",
                )
                for f in facts
            },
            limits,
            self.authority.scope_id,
        )

    def prove(self, relation, fact_ids=(), *, semantic_kind="relation", limits=None):
        from ..math_kernel.proof_kernel import prove_relation

        facts = self._selected(tuple(fact_ids))
        limits = limits or ProofLimits()
        context = self._context(facts, limits)
        result = prove_relation(parse_math_relation(relation, context.symbols), context)
        require(result.status == "proved", result.diagnostic or "relation not proved")
        return self.replay_record(
            {
                "kind": "relation",
                "relation": relation,
                "semantic_kind": semantic_kind,
                "fact_ids": list(fact_ids),
                "limits": asdict(limits),
                "proof": result.proof,
            }
        )

    def admit_certificate(self, proof, context, premise_fact_refs, source_site):
        return self.replay_record(
            {
                "kind": "certificate",
                "proof": proof,
                "source_site": list(source_site),
                "imports": dict(premise_fact_refs),
                "context": {
                    "symbols": sorted(context.symbols),
                    "scope_id": context.scope_id,
                    "limits": asdict(context.limits),
                    "premises": {
                        k: {
                            "source": p.source,
                            "source_path": p.source_path,
                            "step": p.step,
                        }
                        for k, p in context.premises.items()
                    },
                },
            }
        )

    def admit_method(self, evidence, *, producer_refs=None):
        return self.replay_record(
            {
                "kind": "method",
                "evidence": evidence,
                "producer_refs": dict(producer_refs or {}),
            }
        )

    def replay_record(self, raw):
        # Freeze caller-owned mutable evidence before checking or storing it.
        record = json.loads(canonical(raw))
        require(not self.closed, "closed transaction")
        call = self.authority
        proof_ref = digest(record)
        requirements = ()
        if record["kind"] == "relation":
            require(
                set(record) - {"search"}
                == {"kind", "relation", "semantic_kind", "fact_ids", "limits", "proof"},
                "invalid relation record",
            )
            if "search" in record:
                metadata = record["search"]
                require(
                    set(metadata)
                    == {"policy", "policy_hash", "manifest_hash", "authority_hash"}
                    and digest(metadata["policy"]) == metadata["policy_hash"]
                    and metadata["manifest_hash"] == self.view.committed_manifest_hash
                    and metadata["authority_hash"] == call.fingerprint,
                    "search environment metadata changed",
                )
            selected = self._selected(tuple(record["fact_ids"]))
            context = self._context(selected, ProofLimits(**record["limits"]))
            result = replay_proof(record["proof"], context)
            require(
                result.status == "proved",
                result.diagnostic or "invalid producer certificate",
            )
            request = record["proof"]["request"]
            require(
                request["kind"] == "relation"
                and request["candidate"]["source"] == record["relation"],
                "proof root differs from published relation",
            )
            require(
                all(call.validity.includes(f.validity) for f in selected),
                "dependency validity lost",
            )
            candidates = [
                (
                    record["relation"],
                    record["semantic_kind"],
                    "root",
                    call.symbol_bindings,
                    call.validity,
                )
            ]
            dependencies = tuple(record["fact_ids"])
        elif record["kind"] == "certificate":
            require(
                set(record) == {"kind", "proof", "source_site", "imports", "context"},
                "invalid certificate record",
            )
            policy = premise_policy(*record["source_site"])
            require(
                policy in ("verified", "prefix", "source"),
                "conditional constructor cannot publish facts",
            )
            raw_context = record["context"]
            require(
                set(raw_context) == {"symbols", "scope_id", "limits", "premises"},
                "invalid local context",
            )
            require(
                set(raw_context["symbols"]) <= dict(call.symbol_bindings).keys(),
                "unbound local symbols",
            )
            require(
                set(record["imports"]) == set(raw_context["premises"]),
                "all premises need producer bindings",
            )
            imported = {
                k: self._selected((ref,))[0] for k, ref in record["imports"].items()
            }
            require(
                all(call.validity.includes(f.validity) for f in imported.values()),
                "dependency validity lost",
            )
            symbols = bindings_symbols(
                tuple(
                    (n, dict(call.symbol_bindings)[n]) for n in raw_context["symbols"]
                )
            )
            premises = {}
            for key, document in raw_context["premises"].items():
                parsed = parse_math_relation(document["source"], symbols)
                require(
                    from_node(parsed.ast)
                    == from_node(
                        parse_math_relation(imported[key].relation, symbols).ast
                    ),
                    "premise differs from authorized fact",
                )
                premises[key] = replace(
                    parsed, source_path=document["source_path"], step=document["step"]
                )
            context = ProofContext(
                symbols,
                premises,
                ProofLimits(**raw_context["limits"]),
                raw_context["scope_id"],
            )
            checked = replay_proof(record["proof"], context)
            require(
                checked.status == "proved", checked.diagnostic or "invalid certificate"
            )
            projected = necessary_relations(record["proof"], "proof")
            candidates = [
                (
                    p.relation,
                    p.semantic_kind,
                    p.proof_path,
                    call.symbol_bindings,
                    call.validity,
                )
                for p in projected
            ]
            dependencies = tuple(record["imports"].values())
        elif record["kind"] == "method":
            require(
                set(record) == {"kind", "evidence", "producer_refs"},
                "invalid Method record",
            )
            require(call.target_json is not None, "Method target authority required")
            target = json.loads(call.target_json)
            require(target["scope_id"] == call.scope_id, "target Scope mismatch")
            # Bind all original source conditions by exact relation and origin;
            # evidence cannot introduce its own root assumptions.
            originals = {
                f.source: f.relation
                for f in self.view.facts
                if f.producer_call_id is None
            }
            require(
                all(
                    originals.get("source:" + c["handle"]) == c["math"]
                    and self.owner.source_context.premises[c["handle"]].source_path
                    == c["source_path"]
                    for c in target["source_conditions"]
                ),
                "target source conditions not authenticated",
            )
            # Embedded historical evidence must identify its committed producer;
            # equality of formulas alone does not establish symbol/definition identity.
            historical = {
                k: v
                for k, v in record["evidence"].items()
                if k in ("substitution", "elimination", "previous_bound")
                and v is not None
            }
            require(
                set(historical) == set(record["producer_refs"]),
                "embedded predecessor needs exact producer reference",
            )
            predecessor_facts = []
            for key, evidence in historical.items():
                producer = next(
                    (
                        c
                        for c in self.owner.snapshot.commits
                        if c.call_id == record["producer_refs"][key]
                    ),
                    None,
                )
                require(producer is not None, "predecessor not committed")
                producer_grant = self.owner.authority(producer.call_id)
                require(
                    producer_grant.target_json == call.target_json,
                    "predecessor target identity changed",
                )
                require(
                    any(
                        r.get("kind") == "method" and r["evidence"] == evidence
                        for r in json.loads(producer.records_json)
                    ),
                    "predecessor evidence does not match producer",
                )
                require(bool(producer.facts), "predecessor has no published evidence")
                predecessor_facts.extend(
                    self._selected(tuple(f.fact_id for f in producer.facts))
                )
            projected, definitions, requirements = replay_method(
                call.method_id, target, record["evidence"]
            )
            definition_refs = tuple(
                f"{call.call_id}/definition/{n}" for n in definitions
            )
            validity = replace(
                call.validity,
                definition_refs=tuple(
                    sorted(set(call.validity.definition_refs) | set(definition_refs))
                ),
            )
            bindings = dict(call.symbol_bindings)
            for name in definitions:
                require(name not in bindings, "definition symbol collision")
                bindings[name] = (
                    f"{call.input_fingerprint}/{call.call_id}/definition/{name}"
                )
            candidates = [
                (
                    p.relation,
                    p.semantic_kind,
                    p.proof_path,
                    tuple(sorted(bindings.items())),
                    validity,
                )
                for p in projected
            ]
            source_handles = {
                "source:" + c["handle"] for c in target["source_conditions"]
            }
            dependencies = tuple(
                sorted(
                    {f.fact_id for f in self.view.facts if f.source in source_handles}
                    | {f.fact_id for f in predecessor_facts}
                )
            )
        else:
            raise ValueError("unknown publication evidence")
        facts = []
        for relation, kind, path, bindings, validity in candidates:
            require(kind in call.allowed_kinds, "Method cannot publish this fact kind")
            fact = VerifiedMathFact(
                relation,
                bindings,
                validity,
                kind,
                f"{call.call_id}/{path}",
                proof_ref,
                dependencies,
                call.call_id,
            )
            self.owner.registry.validate(fact, call.method_id)
            facts.append(fact)
        self._requirements.extend(
            AttainmentRequirement(
                "attainment",
                call.call_id,
                relation,
                call.validity,
                proof_ref,
                proof_ref,
                f"{call.call_id}/{path}",
            )
            for relation, path in requirements
        )
        self._records.append(canonical(record))
        self._candidates.extend(facts)
        self._reads.update(dependencies)
        return tuple(facts)

    def finish(self, output_hash):
        require(not self.closed, "closed transaction")
        call = self.authority
        records_json = "[" + ",".join(self._records) + "]"
        commit = FactCommit(
            call.call_id,
            call.fingerprint,
            self.view.committed_manifest_hash,
            output_hash,
            records_json,
            (),
            (),
            (),
        )
        # Overlay facts have temporary identities; remap their dependencies to
        # committed IDs in order, preserving local prefix proof references.
        mapping, facts = {}, []
        for fact in self._candidates:
            final = replace(
                fact,
                commit_id=commit.commit_id,
                dependency_fact_refs=tuple(
                    mapping.get(k, k) for k in fact.dependency_fact_refs
                ),
            )
            mapping[fact.fact_id] = final.fact_id
            facts.append(final)
        imported = tuple(sorted(self._reads - mapping.keys()))
        known = {f.fact_id: f for f in self.view.facts}
        require(set(imported) <= known.keys(), "unbound proof read")
        producers = {
            known[k].producer_call_id for k in imported if known[k].producer_call_id
        }
        deps = tuple(sorted(set(call.dependencies) | producers))
        return replace(
            commit,
            facts=tuple(facts),
            proof_reads=imported,
            dependencies=deps,
            requirements=tuple(self._requirements),
        )
