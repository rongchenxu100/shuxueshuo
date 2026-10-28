"""Student read model, separate from resumable execution and debug evidence.

Call positions and step sequence numbers are identities in card source_refs.
Projection must never filter or reorder those arrays, including unchecked calls.
"""

from copy import deepcopy

from .revision_manifest import manifest_ref

_ROUTE_FIELDS = ("target_ref", "route_id", "status", "phase", "commit_id", "last_seq")
_STEP_FIELDS = ("seq", "method", "step", "case_path", 'option_context')
_CALL_FIELDS = ("public_ref", "rule_ref", "branch", "used_basis", "case_path")


def _fields(value, names):
    return {name: deepcopy(value[name]) for name in names if name in value}


def source_evidence(value):
    """Keep exactly the evidence read by the knowledge-graph consumer."""
    result = _fields(value, _CALL_FIELDS)
    if "postconditions" in value:
        # Missing/non-boolean passed values stay unproved, never coerce to true.
        result["postconditions"] = [
            _fields(check, ("passed",)) if isinstance(check, dict) else {}
            for check in value["postconditions"]
        ] if isinstance(value["postconditions"], list) else []
    return result


def trajectory_evidence(checkpoint):
    trajectory = checkpoint.get("driver_state", {}).get("trajectory", {})
    steps = []
    for step in trajectory.get("steps", []):
        row = _fields(step, _STEP_FIELDS)
        row["calls"] = [source_evidence(call) for call in step.get("calls", [])]
        steps.append(row)
    return {
        "target_ref": checkpoint["target_ref"], "route_id": checkpoint["route_id"],
        "steps": steps,
        "finalization": [{"index": index, "record": source_evidence(record)}
                         for index, record in enumerate(trajectory.get("finalization", []))],
    }


def project_snapshot(snapshot):
    """Project a single database read snapshot without exposing driver_state."""
    result = _fields(snapshot, (
        "run_id", "lesson_version", "input_sha256", "stream_id", "last_seq", "minimum_seq",
        "math_steps", "goals", "handoffs", "qa", "selection_chunks", "interaction_protocol", "interaction_states",
    ))
    result.update(
        contract="graph-stage-three-snapshot/v2",
        revisions_ref=manifest_ref(snapshot["revisions"]),
        checkpoints=[_fields(checkpoint, _ROUTE_FIELDS) for checkpoint in snapshot["checkpoints"]],
        trajectories=[trajectory_evidence(checkpoint) for checkpoint in snapshot["checkpoints"]],
    )
    if "interactions" in snapshot:
        # Compiler diagnostics and witnesses stay in the internal snapshot.
        result["interactions"] = [deepcopy(row["chunk"]) for row in snapshot["interactions"]]
    return result
