"""Algebra Method adapters for the generic fact transaction service."""

from dataclasses import replace

from ..math_kernel.proof_algebra import digest
from .proof_fact_transactions import call_fingerprint
from .scoped_proof_facts import require


def method_search_service(overlay):
    """Expose only visible, producer-replayed fragments to the kernel service."""
    import json

    from ..math_kernel.method_proof_session import MethodProofSession

    # Index each immutable producer record once per invocation. Fact count must
    # not multiply serialization of the entire nested evidence chain.
    records = {
        commit.call_id: {digest(record): record for record in json.loads(commit.records_json)}
        for commit in overlay.owner.snapshot.commits
    }

    def resolve_bound(target, evidence):
        from ..math_kernel.bound_chain import unpack_bound
        from ..math_kernel.proof_facts import canonical

        if canonical(target) != overlay.authority.target_json:
            return None
        for commit in overlay.owner.snapshot.commits:
            grant = overlay.owner.authority(commit.call_id)
            if grant.target_json != overlay.authority.target_json:
                continue
            matching = {ref for ref, record in records[commit.call_id].items()
                        if record.get("kind") == "method" and record["evidence"] == evidence}
            if not matching:
                continue
            # Reading a checked result still requires this call's visibility,
            # symbol identity and validity, and records the proof dependency.
            symbols = dict(overlay.authority.symbol_bindings)
            if any(symbols.get(n) != identity for n, identity in grant.symbol_bindings
                   if n in target["scalar_symbols"]):
                return None
            # The certified bound is the dependency being consumed. Reading all
            # intermediate proof nodes would inflate checkpoints unnecessarily.
            refs = tuple(f.fact_id for f in commit.facts
                         if f.source == f"{commit.call_id}/certified_bound"
                         and f.proof_ref in matching)
            require(bool(refs), "predecessor has no published evidence")
            # M13 may return to original variables without carrying substitution
            # definitions. Such evidence needs the existing full replay path.
            if not set(refs) <= {f.fact_id for f in overlay.view.facts}:
                return None
            facts = overlay._selected(refs)
            if not all(overlay.authority.validity.includes(f.validity) for f in facts):
                return None
            fresh = sorted(set(refs) - service.recorded_reads)
            if fresh:
                overlay.replay_record({"kind": "reuse", "fact_ids": fresh})
                service.recorded_reads.update(fresh)
            return unpack_bound(evidence)
        return None

    fragments = []
    for fact in overlay.view.facts:
        if not fact.producer_call_id or not overlay.authority.validity.includes(
            fact.validity
        ):
            continue
        path = fact.source.removeprefix(fact.producer_call_id + "/")
        if "/nodes/" not in path:
            continue
        path, node = path.rsplit("/nodes/", 1)
        record = records[fact.producer_call_id].get(fact.proof_ref)
        if record is None:
            continue
        document = record.get("evidence", record)
        document = {**document, **document.get("certificate_bundle", {})}
        try:
            for part in path.split("/"):
                document = (
                    document[int(part)]
                    if isinstance(document, list)
                    else document[part]
                )
        except (KeyError, IndexError, ValueError):
            continue
        if isinstance(document, dict) and "nodes" in document:
            fragments.append((fact.fact_id, document, node))
    service = MethodProofSession(
        fragments=fragments,
        application_binding={
            "producer_call_id": overlay.authority.call_id,
            "source_binding_fingerprint": overlay.authority.input_fingerprint,
            "scope_id": overlay.authority.scope_id,
            "committed_manifest_hash": overlay.view.committed_manifest_hash,
        },
        manifest_hash=overlay.view.committed_manifest_hash,
        on_read=lambda refs: overlay.replay_record(
            {"kind": "reuse", "fact_ids": list(refs)}
        ),
        resolve_bound=resolve_bound,
    )
    return service


class PremiseFactIndex:
    """One publication's parsed relations; new checked facts extend the index."""

    def __init__(self, authority):
        from .scoped_proof_facts import bindings_symbols

        self.authority = authority
        self.bindings = dict(authority.symbol_bindings)
        self.symbols = bindings_symbols(authority.symbol_bindings)
        self.relations = {}
        self.seen = set()

    def extend(self, facts):
        from ..math_kernel.expression_parser import parse_math_relation
        from ..math_kernel.proof_algebra import from_node

        for fact in facts:
            if fact.fact_id in self.seen:
                continue
            self.seen.add(fact.fact_id)
            if not all(self.bindings.get(n) == identity for n, identity in fact.symbol_bindings):
                continue
            if not self.authority.validity.includes(fact.validity):
                continue
            relation = from_node(parse_math_relation(fact.relation, self.symbols).ast)
            self.relations.setdefault(relation, []).append(fact)

    def match(self, parsed, symbols):
        from ..math_kernel.proof_algebra import from_node

        matches = [
            fact for fact in self.relations.get(from_node(parsed.ast), ())
            if all(n in symbols for n, _ in fact.symbol_bindings)
        ]
        require(bool(matches), "rewrite premise has no authorized producer")
        return min(matches, key=lambda f: (f.producer_call_id or "", f.source, f.fact_id))


def match_premise_fact(available, parsed, symbols, authority):
    """Match exact symbol identities and select stable provenance."""
    if isinstance(available, PremiseFactIndex):
        require(available.authority == authority, "premise index authority changed")
        return available.match(parsed, symbols)
    index = PremiseFactIndex(authority)
    index.extend(available)
    return index.match(parsed, symbols)


def publish_method_result(overlay, inputs, result, *, checked=None):
    """Project checked invocation results; external records still require replay."""
    import json
    from dataclasses import replace

    from ..math_kernel.expression_parser import parse_math_relation
    from ..math_kernel.proof_types import ProofContext, ProofLimits
    from .scoped_proof_facts import bindings_symbols

    method = result.method_id
    if method == "organize_expressions":
        premise_index = PremiseFactIndex(overlay.authority)
        premise_index.extend((*overlay.view.facts, *overlay._candidates))
        for trace in result.trace_fragments:
            for proof, raw in zip(
                trace.get("proofs", ()), trace.get("proof_contexts", ()), strict=True
            ):
                symbols = bindings_symbols(
                    tuple(
                        (n, dict(overlay.authority.symbol_bindings)[n])
                        for n in raw["symbols"]
                    )
                )
                premises = {
                    key: replace(
                        parse_math_relation(d["source"], symbols),
                        source_path=d["source_path"],
                        step=d["step"],
                    )
                    for key, d in raw["premises"].items()
                }
                imports = {}
                for key, parsed in premises.items():
                    imports[key] = match_premise_fact(
                        premise_index, parsed, symbols, overlay.authority
                    ).fact_id
                admitted = overlay.admit_certificate(
                    proof,
                    ProofContext(
                        symbols, premises, ProofLimits(**raw["limits"]), raw["scope_id"]
                    ),
                    imports,
                    ("expression_rewrite", "verify_chain", "c{i}"),
                    checked=checked,
                )
                premise_index.extend(admitted)
        return
    if method not in {
        "apply_two_term_amgm",
        "bound_univariate_quadratic",
        "substitute_expressions",
        "eliminate_by_constraint",
    }:
        return  # Witnesses and attainment requirements never publish facts.
    names = {
        "apply_two_term_amgm": "bound",
        "bound_univariate_quadratic": "bound",
        "substitute_expressions": "substitution",
        "eliminate_by_constraint": "elimination",
    }
    evidence = result.outputs[names[method]].value
    producers = {}
    for key in ("previous_bound", "elimination", "substitution"):
        if evidence.get(key) is None:
            continue
        matches = [
            commit.call_id
            for commit in overlay.owner.snapshot.commits
            if any(
                record.get("kind") == "method" and record["evidence"] == evidence[key]
                for record in json.loads(commit.records_json)
            )
        ]
        require(
            len(matches) == 1, "Method predecessor must identify one committed producer"
        )
        producers[key] = matches[0]
    overlay.admit_method(evidence, producer_refs=producers, checked=checked)


def prepare_scoped_call(branch, call_id, compiled, graph):
    """Bind a new v2 call from compiled reads and authenticated Runtime values.

    Registration follows canonical execution order. No saved evidence or LLM
    claim can register a source condition or choose a symbol identity.
    """
    import json

    from ..math_kernel.inequality_evidence import target_context
    from ..math_kernel.proof_facts import FactValidity, canonical
    from ..math_kernel.substitution import find_substitution
    from .models import ContextPath
    from .scoped_proof_facts import ProofCallAuthority, ScopedProofFacts

    invocations = [i for p in compiled.plans for i in p.invocations]
    from .method_proof_backends import requires_scoped_proof

    needs_proof = [requires_scoped_proof(i.method_id) for i in invocations]
    require(
        bool(invocations),
        "scoped-facts/v2 requires a registered single-Method proof adapter",
    )
    if not any(needs_proof):
        return  # Native validation creates no shared proof grant or facts.
    require(
        len(invocations) == 1,
        "scoped-facts/v2 requires a registered single-Method proof adapter",
    )
    invocation = invocations[0]
    scope = next(c.declared_scope_id for c in graph.calls if c.call_id == call_id)

    def read(name):
        path = invocation.inputs.get(name)
        return (
            branch.read_path(path, from_scope_id=invocation.scope).value
            if isinstance(path, str)
            else None
        )

    target = read("target")
    if target is None:
        owner = ContextPath.parse(invocation.inputs["expression"]).key
        authorities = invocation.input_read_authorities.get("expression", ())
        if authorities:
            payload = authorities[0].authority_payload()
            owner = (
                payload.get("source", {})
                .get("state_version_id", {})
                .get("slot_id", {})
                .get("logical_key", {})
                .get("object_id", {})
                .get("value", owner)
            )
        targets = [
            item
            for item in branch.proof_source_catalog
            if item.get("type") == "extremum_target"
            and item.get("expression_owner") == owner
            and branch.is_visible(scope, item["scope_id"])
        ]
        require(
            len(targets) == 1,
            "rewrite needs an unambiguous authenticated target owner: " + owner,
        )
        target = targets[0]
    source, _ = target_context(target)
    bindings = tuple(
        (name, f"{target['scope_id']}/scalar/{name}") for name in source.symbols
    )
    store = branch.proof_facts
    validity = FactValidity(scope)
    inherited = find_substitution(
        {
            key: read(key)
            for key in ("substitution", "elimination", "previous_bound", "bound")
        }
    )
    if inherited and store is not None:
        producers = [
            c
            for c in store.snapshot.commits
            if any(
                r.get("kind") == "method" and r["evidence"] == inherited
                for r in json.loads(c.records_json)
            )
        ]
        require(len(producers) == 1, "definition producer must be committed")
        merged = dict(bindings)
        definitions = set()
        for fact in producers[0].facts:
            merged.update(fact.symbol_bindings)
            definitions.update(fact.validity.definition_refs)
        bindings = tuple(sorted(merged.items()))
        validity = replace(validity, definition_refs=tuple(sorted(definitions)))
    grant = ProofCallAuthority(
        call_id,
        scope,
        invocation.method_id,
        bindings,
        validity,
        call_fingerprint(compiled),
        allowed_kinds=("domain", "identity", "relation", "bound", "definition")
        if invocation.method_id == "substitute_expressions"
        else ("domain", "identity", "relation", "bound"),
        target_json=canonical(target) if "target" in invocation.inputs else None,
    )
    if store is None:
        branch.proof_facts = ScopedProofFacts(
            branch,
            source,
            tuple((n, f"{target['scope_id']}/scalar/{n}") for n in source.symbols),
            (grant,),
        )
    else:
        require(
            store.source_context == source,
            "new target source requires a separate proof session",
        )
        store.register_call(grant)
