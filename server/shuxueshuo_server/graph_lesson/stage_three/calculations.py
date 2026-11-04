"""Pure JSON entry point for isolated route mathematics.

All symbolic decoding, calculation, rendering and exact-object encoding stay in
the mathematical worker. The parent persists and publishes JSON only.
"""

from functools import lru_cache

from . import driver, execution_contracts, route_constraints, verification
from .goals import equivalent_answers, finalize_goal_with_evidence, verify_goal_answer
from .presentation import append_goal_finalization
from .revision_manifest import manifest_ref, revision_ref
from .trajectory import decode_value, encode_value


@lru_cache(maxsize=1)
def _session_contracts(expected_ref):
    """Validate once in this worker; a new process or revision loads afresh.

    Only immutable configuration is shared. Capability and judgment dispatch
    stay live; neither this cache nor its key is persisted in checkpoints.
    """
    read_revisions = execution_contracts.revisions
    current = read_revisions()
    if manifest_ref(current) != expected_ref:
        # Recorded runs freeze the entire pipeline under relative file paths;
        # direct driver sessions use the named execution-only revision map.
        # Preserve either complete identity, rather than reducing to a subset.
        from .runner import fingerprint

        read_revisions = fingerprint
        current = read_revisions()
    if manifest_ref(current) != expected_ref:
        raise ValueError("execution.contract_revisions_changed")
    contracts = execution_contracts.load_contracts()
    # Validation reads several files. Refuse a snapshot changed during those
    # reads instead of publishing it under the checkpoint's earlier revision.
    if manifest_ref(read_revisions()) != expected_ref:
        raise ValueError("execution.contract_revisions_changed")
    return contracts


def _contracts(value):
    return _session_contracts(revision_ref(value))


def consistency(feasible, answer, previous):
    for route in previous:
        if route["status"] != "verified":
            continue
        earlier = decode_value(route["feasible_set_exact"])
        try:
            mismatch = verification._set_mismatch(feasible, earlier)
        except verification.VerificationGap:
            return "unknown"
        earlier_answer = route["answer"]
        if mismatch is not None:
            return "conflict"
        try:
            if not equivalent_answers(answer, earlier_answer):
                return "conflict"
        except verification.VerificationGap:
            return "unknown"
    return "consistent"


def _advance_visible(state, contracts):
    """Commit a folded M1 child as one bounded operation, retaining its proof.

    Only an explicitly folded domain child inside an option is eligible. Each
    ordinary driver action still checks its budget and records its full trace;
    the surrounding calculation worker bounds the whole batch. A visible card,
    child return or failure always ends the batch before another option action.
    """
    updated = driver.advance(state, contracts=contracts)
    for _ in range(64):
        frames = updated.get('frames') or []
        frame = frames[-1] if frames else {}
        context = frame.get('bindings', {}).get('context', {})
        if (updated['status'] != 'running' or len(updated['fragments']) != len(state['fragments'])
                or frame.get('method') != 'method-domain-intersection'
                or not frame.get('option_context') or context.get('suppress_domain_display') is not True):
            break
        updated = driver.advance(updated, contracts=contracts)
    return updated


def dispatch(payload):
    operation = payload["operation"]
    if operation == 'verify_function_monotonicity':
        from .monotonicity_runtime import verify_frozen
        return verify_frozen(payload['candidate'], payload['target_ref'], payload['context'], payload['monotonicity_result_exact'])
    if operation == 'finish_function_monotonicity':
        from .monotonicity_runtime import finish
        return finish(payload['state'], payload['context'], payload['previous'])
    if operation == 'verify_function_graph':
        from .graph_transform_runtime import verify_frozen
        return verify_frozen(payload['candidate'], payload['target_ref'], payload['context'], payload['graph_result_exact'])
    if operation == 'finish_function_graph':
        from .graph_transform_runtime import finish
        return finish(payload['state'], payload['context'], payload['previous'])
    if operation == 'verify_model':
        from ..piecewise_modeling import verify_frozen
        return verify_frozen(payload['candidate'], payload['target_ref'], payload['context'], payload['model_result_exact'])
    if operation == 'finish_model':
        from ..piecewise_modeling import finish
        return finish(payload['state'], payload['context'], payload['previous'])
    if operation == 'verify_formula':
        from .formula_runtime import verify_frozen
        return verify_frozen(payload['candidate'], payload['target_ref'], payload['context'],
                             payload['formula_result_exact'])
    if operation == 'finish_formula':
        from .formula_runtime import finish
        return finish(payload['state'], payload['context'], payload['previous'])
    if operation == 'verify_evaluation':
        from .evaluation_runtime import verify_frozen
        return verify_frozen(payload['candidate'], payload['target_ref'], payload['context'],
                             payload['evaluation_result_exact'])
    if operation == 'finish_evaluation':
        from .evaluation_runtime import finish
        return finish(payload['state'], payload['context'], payload['previous'])
    if operation == 'verify_comparisons':
        from .equality_runtime import verify_frozen
        return verify_frozen(payload['candidate'], payload['target_ref'], payload['context'],
                             payload['comparison_result_exact'])
    if operation == 'finish_comparisons':
        from .equality_runtime import finish
        return finish(payload['state'], payload['previous'])
    if operation == "initialize":
        arguments = payload["arguments"]
        revisions = arguments.get("revisions") or execution_contracts.revisions()
        return driver.create_state(contracts=_contracts({"revisions": revisions}), **arguments)
    if operation == "advance":
        return _advance_visible(payload["state"], _contracts(payload["state"]))
    if operation == "interaction":
        from . import interaction

        chunk, diagnostics = interaction.build_chunk(payload["seeds"], payload["registry"], payload["repeat_context"],
                                                     revision=payload["revision"])
        return {"chunk": chunk, "diagnostics": diagnostics}
    if operation == "constraints":
        candidate_set = driver.export_values(payload["state"])["feasible_set"]
        feasible, processing = route_constraints.apply_visible_constraints(
            payload["context"], candidate_set,
        )
        return {"feasible_set_exact": encode_value(feasible), "processing": processing,
                "feasible_set": verification.math_value(feasible)}
    feasible = decode_value(payload["feasible_set_exact"])
    if operation == "verify":
        return verification.verify(payload["candidate"], payload["target_ref"], payload["context"], feasible)
    if operation == "endpoints":
        evidence = verification.endpoint_check(payload["candidate"], payload["target_ref"], feasible)
        # Boundary rendering calls SymPy too; do not move it back to the parent.
        state = driver.append_endpoint(payload["state"], feasible, evidence)
        return {"state": state, "evidence": evidence}
    if operation == "finish":
        answer, _ = finalize_goal_with_evidence(payload["goal"], feasible)
        evidence = verify_goal_answer(payload["goal"], feasible, answer)
        state = append_goal_finalization(payload["state"], answer, evidence)
        return {"answer": answer, "feasible_set": verification.math_value(feasible),
                "state": state, "consistency": consistency(feasible, answer, payload["previous"])}
    raise ValueError("calculation.unknown_operation:" + operation)
