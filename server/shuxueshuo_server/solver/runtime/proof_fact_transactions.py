"""Sequential proof publication, dependency tracking and checkpoint recovery.

The module name is retained for historical imports and checkpoint compatibility.
"""

from dataclasses import replace

from ..math_kernel.proof_algebra import digest
from .functional_logical_graph import FunctionalDependencyEdge
from .scoped_proof_facts import require


class ProofKernelServices:
    """Internal Method kernel facade; no RuntimeContext or handle resolution."""

    def __init__(self, kernel, session):
        self._kernel = kernel
        self.proof_session = session
        self.proof_view = session.view

    def __getattr__(self, name):
        return getattr(self._kernel, name)


def call_fingerprint(compiled):
    invocations = [inv for plan in compiled.plans for inv in plan.invocations]
    return digest(
        [
            {
                "method_id": i.method_id,
                "scope": i.scope,
                "inputs": i.inputs,
                "parameters": i.parameters,
                "reads": {
                    k: [a.authority_payload() for a in v]
                    for k, v in i.input_read_authorities.items()
                },
                "supporting_reads": {
                    k: [a.authority_payload() for a in v]
                    for k, v in i.supporting_input_read_authorities.items()
                },
            }
            for i in invocations
        ]
    )


def begin_call(branch, call_id, compiled, graph):
    if branch.proof_protocol == "scoped-facts/v2":
        from .method_proof_integration import prepare_scoped_call
        prepare_scoped_call(branch, call_id, compiled, graph)
    if branch.proof_facts is None:
        return
    store = branch.proof_facts
    if call_id not in {c.call_id for c in store.calls}:
        return
    node = next(c for c in graph.calls if c.call_id == call_id)
    grant = store.authority(call_id)
    require(grant.scope_id == node.declared_scope_id, "call publication Scope changed")
    require(
        grant.input_fingerprint == call_fingerprint(compiled),
        "exact call inputs changed",
    )
    require(
        tuple(c.call_id for c in store.calls)
        == tuple(
            c for c in graph.canonical_order if c in {g.call_id for g in store.calls}
        ),
        "canonical call order changed",
    )
    methods = {i.method_id for p in compiled.plans for i in p.invocations}
    require(methods == {grant.method_id}, "producer Method authority changed")
    branch.proof_fact_overlay = store.begin(call_id)


def proof_output_hash(runtime_results, writes):
    """Bind values and immutable provenance, not Retry's consumer re-stamping.

    rebase_restored_call_seed separately validates source reads, destinations and
    publication authority before changing goal consumers/call binding signatures.
    Keep every value, version, destination and immutable provenance field here.
    """

    def payload(item):
        result = item.to_payload()
        source = result.get("problem_source_provenance")
        if isinstance(source, dict):
            result = {
                **result,
                "problem_source_provenance": {
                    key: value
                    for key, value in source.items()
                    if key not in {"goal_unit_ids", "call_binding_signature"}
                },
            }
        return result

    return digest(
        {
            "runtime_results": [payload(r) for r in runtime_results],
            "state_writes": [payload(w) for w in writes],
        }
    )


def finalize_call(branch, runtime_results, writes):
    overlay = branch.proof_fact_overlay
    if overlay is None:
        return None
    # Records were independently checked on admission. Publish without a second
    # branch or replay; failed calls rebuild from previously verified outputs.
    output_hash = proof_output_hash(runtime_results, writes)
    receipt = branch.proof_facts.publish(overlay, output_hash)
    branch.proof_fact_overlay = None
    return receipt


def validate_dependencies(graph, working, receipt):
    if receipt is None:
        return
    call_id = receipt.call_id
    dependencies = set(receipt.dependencies)
    order = {c: i for i, c in enumerate(graph.canonical_order)}
    require(
        all(c in order and order[c] < order[call_id] for c in dependencies),
        "proof dependency is not a canonical predecessor",
    )
    require(
        all(working.call_states[c].status == "verified" for c in dependencies),
        "proof producer not committed",
    )


def add_dependency_edges(graph, working, receipt):
    if receipt is None:
        return graph
    validate_dependencies(graph, working, receipt)
    call_id = receipt.call_id
    dependencies = set(receipt.dependencies)
    calls = []
    for call in graph.calls:
        if call.call_id == call_id:
            call = replace(
                call,
                dependency_call_ids=tuple(
                    sorted(set(call.dependency_call_ids) | dependencies)
                ),
            )
        if call.call_id in dependencies:
            call = replace(
                call,
                consumer_call_ids=tuple(
                    sorted(set(call.consumer_call_ids) | {call_id})
                ),
            )
        calls.append(call)
    state = working.call_states[call_id]
    working.call_states[call_id] = replace(
        state,
        dependency_call_ids=tuple(
            sorted(set(state.dependency_call_ids) | dependencies)
        ),
    )
    existing = {
        (e.producer_call_id, e.consumer_call_id, e.kind) for e in graph.dependencies
    }
    edges = tuple(
        FunctionalDependencyEdge(p, call_id, "proof_read")
        for p in sorted(dependencies)
        if (p, call_id, "proof_read") not in existing
    )
    return replace(
        graph, calls=tuple(calls), dependencies=(*graph.dependencies, *edges)
    )


def retained_proof_prefix(payload, selected, call_order):
    """Retain a safe runtime prefix; discarded calls are executed again.

    Do not merely trim the fact sidecar while retaining those calls' outputs.
    With no fact commits, existing sparse restore behavior stays unchanged.
    """
    if payload is None or not payload["commits"]:
        return frozenset(selected)
    retained = []
    for call_id in call_order:
        if call_id not in selected:
            break
        retained.append(call_id)
    return frozenset(retained)


def select_checkpoint(payload, selected):
    if payload is None:
        return None
    commits = payload["commits"]
    kept = [c for c in commits if c["call_id"] in selected]
    require(kept == commits[: len(kept)], "Retry must retain an exact committed prefix")
    require(
        all(set(c["dependencies"]) <= set(selected) for c in kept),
        "Retry omitted an auxiliary producer",
    )
    return {
        **payload,
        "commits": kept,
        "committed_manifest_hash": digest((payload["source_hash"], kept)),
    }


def restore_facts(context, seed, graph=None):
    if seed is None or seed.proof_fact_checkpoint is None:
        require(
            seed is None or not any(c.proof_commit for c in seed.call_results),
            "proof checkpoint missing",
        )
        return
    require(seed.proof_fact_checkpoint.get("condition_protocol", "bound-conditions/v1") == context.proof_protocol, "checkpoint condition protocol changed")
    if (context.proof_protocol == "scoped-facts/v2" and context.proof_facts is None
            and seed.proof_fact_checkpoint["commits"] == []):
        require(not any(c.proof_commit for c in seed.call_results), "empty checkpoint lost proof evidence")
        require(seed.proof_fact_checkpoint["committed_manifest_hash"] == digest((seed.proof_fact_checkpoint["source_hash"], [])), "checkpoint manifest mismatch")
        return
    restored_prefix = False
    hashes = {
        c.call_id: proof_output_hash(c.runtime_results, c.state_writes)
        for c in seed.call_results
        if c.proof_commit is not None
    }
    if context.proof_facts is None and context.proof_protocol == "scoped-facts/v2":
        require(graph is not None, "restore requires authenticated call graph")
        compiled = {c.call_id: c for c in seed.compiled_calls}
        retained = set()
        for commit in seed.proof_fact_checkpoint["commits"]:
            call_id = commit["call_id"]
            require(call_id in compiled, "restored proof has no authenticated compiled call")
            from .method_proof_integration import prepare_scoped_call
            prepare_scoped_call(context, call_id, compiled[call_id], graph)
            retained.add(call_id)
            context.proof_facts.restore(select_checkpoint(seed.proof_fact_checkpoint, retained), hashes)
        restored_prefix = True
    require(context.proof_facts is not None, "proof restore requires external source authority")
    if not restored_prefix:
        context.proof_facts.restore(seed.proof_fact_checkpoint, hashes)
    for commit in context.proof_facts.snapshot.commits:
        result = next(c for c in seed.call_results if c.call_id == commit.call_id)
        require(
            result.proof_commit == commit.to_payload(),
            "restored call lost proof evidence",
        )
