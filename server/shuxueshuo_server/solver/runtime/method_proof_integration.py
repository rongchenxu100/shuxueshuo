"""Algebra Method adapters for the generic fact transaction service."""

from dataclasses import replace

from ..math_kernel.proof_algebra import digest
from .proof_fact_transactions import call_fingerprint
from .scoped_proof_facts import require


def method_search_service(overlay):
    """Expose only visible, producer-replayed fragments to the kernel service."""
    import json

    from ..math_kernel.method_proof_session import MethodProofSession

    records = {
        commit.call_id: json.loads(commit.records_json)
        for commit in overlay.owner.snapshot.commits
    }
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
        for record in records[fact.producer_call_id]:
            if digest(record) != fact.proof_ref:
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
    return MethodProofSession(
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
    )


def match_premise_fact(available, parsed, symbols, authority):
    """Match exact symbol identities and select stable provenance."""
    from ..math_kernel.expression_parser import parse_math_relation
    from ..math_kernel.proof_algebra import from_node

    bindings = dict(authority.symbol_bindings)
    matches = [
        f
        for f in available
        if all(
            n in symbols and bindings.get(n) == identity
            for n, identity in f.symbol_bindings
        )
        and authority.validity.includes(f.validity)
        and from_node(parse_math_relation(f.relation, symbols).ast)
        == from_node(parsed.ast)
    ]
    require(bool(matches), "rewrite premise has no authorized producer")
    return min(matches, key=lambda f: (f.producer_call_id or "", f.source, f.fact_id))


def publish_method_result(overlay, inputs, result):
    """Method evidence is replayed before entering the private publication delta."""
    import json
    from dataclasses import replace

    from ..math_kernel.expression_parser import parse_math_relation
    from ..math_kernel.proof_types import ProofContext, ProofLimits
    from .scoped_proof_facts import bindings_symbols

    method = result.method_id
    if method == "organize_expressions":
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
                available = (*overlay.view.facts, *overlay._candidates)
                imports = {}
                for key, parsed in premises.items():
                    imports[key] = match_premise_fact(
                        available, parsed, symbols, overlay.authority
                    ).fact_id
                overlay.admit_certificate(
                    proof,
                    ProofContext(
                        symbols, premises, ProofLimits(**raw["limits"]), raw["scope_id"]
                    ),
                    imports,
                    ("expression_rewrite", "verify_chain", "c{i}"),
                )
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
    overlay.admit_method(evidence, producer_refs=producers)


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
