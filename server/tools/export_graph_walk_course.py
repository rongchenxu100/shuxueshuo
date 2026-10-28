"""Export a static course from a completed, hash-bound stage-three recording.

Read-only: no database, model or solver is opened. The public stream projection
and present_lesson are the same adapters used by the photo-learning endpoint.
"""

import argparse
import fcntl
import json
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_three.checkpoint import (
    identity_from_seed,
    validate_checkpoint,
)
from shuxueshuo_server.graph_lesson.stage_three.handoff import verified_route_hash
from shuxueshuo_server.graph_lesson.stage_three.public_snapshot import project_snapshot
from shuxueshuo_server.graph_lesson.stage_three.revision_manifest import math_step_hash
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.lesson import present_lesson


def _require(ok, code):
    if not ok:
        raise ValueError("course_export." + code)


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _bound_file(directory, item):
    relative = Path(item["path"])
    path = (directory / relative).resolve()
    _require(not relative.is_absolute() and path.is_relative_to(directory), "export_path")
    content = path.read_bytes()
    _require(sha256(content).hexdigest() == item["sha256"], "export_hash")
    return content


def export_course(directory, problem_id):
    directory = Path(directory).resolve()
    # The exporter uses a shared lock, matching EventStore.export's publication
    # contract, so it never reads a pruned generation or a mismatched file pair.
    with (directory / ".export.lock").open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        manifest = _read(directory / "export-manifest.json")
        _require(manifest.get("contract") == "graph-stage-three-debug-export/v1", "export_contract")
        snapshot = json.loads(_bound_file(directory, manifest["checkpoint"]))
        _bound_file(directory, manifest["events"])
        seed = _read(directory / "run.json")
        result = _read(directory / "stage-three-result.json")
        inputs = {name: _read(directory / f"{name.replace('_', '-')}-input.json")
                  for name in ("stage_one", "stage_two")}
        identity = identity_from_seed(seed)
        _require(all(snapshot.get(key) == value and result.get(key) == value
                     for key, value in identity.items() if key != "input_sha256"), "run_identity")
        _require(snapshot.get("input_sha256") == identity["input_sha256"], "input_identity")
        _require(manifest["stream_id"] == snapshot.get("stream_id") == identity["run_id"]
                 and manifest["last_seq"] == snapshot["last_seq"]
                 and manifest["minimum_seq"] == snapshot["minimum_seq"], "cursor_identity")
        for name, value in inputs.items():
            _require(revision(value) == seed[name]["sha256"] == result[name]["sha256"], "input_hash")
            _require(value["run_id"] == seed[name]["run_id"], "upstream_identity")
        _require(inputs["stage_two"]["stage_one"]["sha256"] == revision(inputs["stage_one"]), "upstream_hash")
        frozen = _read(directory / "frozen.json")["implementation"]
        _require(snapshot["revisions"] == frozen, "frozen_identity")
        checkpoints = snapshot.get("checkpoints", [])
        _require(result.get("status") == "completed" and checkpoints, "incomplete_run")
        expected = {(goal["target_ref"], route["route_id"]): route
                    for goal in result["goals"] for route in goal["routes"]}
        actual = {(row["target_ref"], row["route_id"]): row for row in checkpoints}
        _require(len(actual) == len(checkpoints) and set(actual) == set(expected), "route_identity")
        for key, row in actual.items():
            validate_checkpoint(row, {**identity, "revisions": frozen})
            _require(row["status"] == expected[key]["status"] == "verified"
                     and row["phase"] == "complete", "unverified_route")
        _require({(row["target_ref"], row["route_id"]) for row in snapshot["handoffs"]} == set(actual), "handoff_identity")
        for handoff in snapshot["handoffs"]:
            key = handoff["target_ref"], handoff["route_id"]
            checkpoint = actual[key]
            route_path = (directory / expected[key]["trajectory"]).resolve()
            _require(route_path.is_relative_to(directory), "route_path")
            final = checkpoint["finalization"]
            frozen_steps = [{name: step[name] for name in ("step_id", "ordinal", "math_step_sha256")}
                            for step in snapshot["math_steps"] if (step["target_ref"], step["route_id"]) == key]
            route_hash = verified_route_hash(
                route=_read(route_path), verification=final["verification"],
                feasible_set=final.get("feasible_set"), answer=final["answer"],
                math_steps=frozen_steps, revisions=frozen, original_choice=final.get("original_choice"))
            _require(handoff.get("available") is True and handoff["run_id"] == identity["run_id"]
                     and handoff["lesson_version"] == identity["lesson_version"]
                     and handoff["verified_route_sha256"] == checkpoint["verified_route_sha256"] == route_hash
                     and handoff["math_steps"] == frozen_steps, "verified_route_hash")
        for step in snapshot["math_steps"]:
            _require(step["run_id"] == identity["run_id"] and step["lesson_version"] == identity["lesson_version"]
                     and step["math_step_sha256"] == math_step_hash(step, frozen), "math_identity")
        _require(snapshot.get("interaction_protocol") == "graph-step-interaction/v1"
                 and snapshot.get("interactions")
                 and all(row["status"] == "interactive" for row in snapshot["interaction_states"]), "incomplete_interactions")
        public = project_snapshot(snapshot)
        stage_one = inputs["stage_one"]
        lesson = present_lesson(inputs["stage_two"], stage_one["features"],
                                stage_one["candidate"]["original_text"], problem_id,
                                candidate=stage_one["candidate"], display_text=stage_one.get("public_statement"))
        return {"schemaVersion": 1, "provenance": {
            **identity, "checkpoint_sha256": manifest["checkpoint"]["sha256"],
            "result_sha256": revision(result),
            "stage_one_sha256": revision(stage_one), "stage_two_sha256": revision(inputs["stage_two"]),
        }, "lesson": lesson, "stream": public}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--problem-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = export_course(args.recording, args.problem_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "run_id": evidence["provenance"]["run_id"]}))


if __name__ == "__main__":
    main()
