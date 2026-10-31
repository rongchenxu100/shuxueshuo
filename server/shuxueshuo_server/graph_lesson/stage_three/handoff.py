"""Freeze verified mathematical routes, then append separately bound QA evidence.

The caller supplies independently checked mathematics. This module enforces
publication identity and atomically checks the latest target availability; it
does not solve a problem or call a language model.
"""

import json
from copy import deepcopy

from shuxueshuo_server.problem_understanding.identity import revision

from .events import _dump, goal_unavailable


def verified_route_hash(*, route, verification, feasible_set, answer, math_steps, revisions,
                        original_choice=None):
    """One canonical publication identity for live and offline typed results."""
    choice_fields = {"original_choice": original_choice} if original_choice is not None else {}
    return revision({"route": route, "verification": verification, "feasible_set": feasible_set,
                     "answer": answer, "math_steps": math_steps, "revisions": revisions,
                     **choice_fields})


def validate_original_choice(choice, target):
    if choice is None:
        return
    if not isinstance(choice, dict) or choice.get("target_ref") != target:
        raise ValueError("handoff.invalid_original_choice")
    if choice.get("matching") == "set_equality":
        _validate_set_choice(choice)
        return
    if choice.get('selection_mode') in ('multiple', 'single', 'unspecified'):
        _validate_comparison_choice(choice)
        return
    if choice.get("status") == "unavailable":
        if (set(choice) != {"status", "target_ref", "reason"}
                or not isinstance(choice.get("reason"), str) or not choice["reason"].strip()):
            raise ValueError("handoff.invalid_original_choice")
        return
    if set(choice) != {"status", "kind", "target_ref", "options", "correct_labels"}:
        raise ValueError("handoff.invalid_original_choice")
    options = choice.get("options")
    labels = []
    if isinstance(options, list):
        for option in options:
            if (not isinstance(option, dict) or set(option) != {"label", "text"}
                    or not isinstance(option.get("label"), str) or not option["label"].strip()
                    or not isinstance(option.get("text"), str) or not option["text"].strip()):
                raise ValueError("handoff.invalid_original_choice")
            labels.append(option["label"])
    correct = choice.get("correct_labels")
    if (choice.get("status") != "matched" or choice.get("kind") != "single_choice"
            or len(labels) < 2 or len(set(labels)) != len(labels)
            or not isinstance(correct, list) or len(correct) != 1 or correct[0] not in labels):
        raise ValueError("handoff.invalid_original_choice")


def _validate_set_choice(choice):
    expected = {"status", "kind", "matching", "selection_mode", "target_ref", "options", "correct_labels"}
    mode = choice.get("selection_mode")
    if (set(choice) != expected or choice["status"] != "matched"
            or mode not in ("single", "multiple", "unspecified")
            or choice["kind"] != ("single_choice" if mode == "single" else "multiple_choice")):
        raise ValueError("handoff.invalid_original_choice")
    options, correct = choice["options"], choice["correct_labels"]
    if not isinstance(options, list) or not 2 <= len(options) <= 32 or not isinstance(correct, list):
        raise ValueError("handoff.invalid_original_choice")
    labels = []
    for option in options:
        if (not isinstance(option, dict) or set(option) != {"label", "text"}
                or any(not isinstance(value, str) or not value.strip() for value in option.values())):
            raise ValueError("handoff.invalid_original_choice")
        labels.append(option["label"])
    if (len(set(labels)) != len(labels) or any(not isinstance(label, str) for label in correct)
            or len(set(correct)) != len(correct) or any(label not in labels for label in correct)
            or mode == "single" and len(correct) != 1):
        raise ValueError("handoff.invalid_original_choice")


def _validate_comparison_choice(choice):
    expected = {'status', 'kind', 'selection_mode', 'target_ref', 'select_relation',
                'options', 'correct_labels', 'option_verdicts'}
    if (set(choice) != expected or choice['status'] != 'matched'
            or choice['kind'] != ('single_choice' if choice['selection_mode'] == 'single' else 'multiple_choice')
            or choice['select_relation'] not in ('equal', 'different')):
        raise ValueError('handoff.invalid_original_choice')
    options, rows, correct = choice['options'], choice['option_verdicts'], choice['correct_labels']
    if (not isinstance(options, list) or not options or not isinstance(rows, list)
            or len(rows) != len(options) or not isinstance(correct, list)):
        raise ValueError('handoff.invalid_original_choice')
    ids, labels, expected_labels = [], [], []
    for option, row in zip(options, rows, strict=True):
        if (not isinstance(option, dict) or set(option) != {'option_id', 'label', 'text'}
                or any(not isinstance(value, str) or not value.strip() for value in option.values())
                or not isinstance(row, dict) or set(row) != {'option_id', 'label', 'verdict', 'reason'}
                or any(row[key] != option[key] for key in ('option_id', 'label'))
                or row['verdict'] not in ('equal', 'different')
                or not isinstance(row['reason'], str) or not row['reason']):
            raise ValueError('handoff.invalid_original_choice')
        ids.append(option['option_id'])
        labels.append(option['label'])
        if row['verdict'] == choice['select_relation']:
            expected_labels.append(row['label'])
    if (len(set(ids)) != len(ids) or len(set(labels)) != len(labels) or correct != expected_labels
            or (choice['selection_mode'] == 'single' and len(correct) != 1)):
        raise ValueError('handoff.invalid_original_choice')


def complete_route(store, checkpoint, *, route, verification, feasible_set, answer, commit_id,
                   consistency="consistent", original_choice=None, before_commit=None, after_commit=None):
    if verification.get("status") != "verified" or route.get("status") != "verified":
        raise ValueError("handoff.route_not_verified")
    comparison = isinstance(answer, dict) and answer.get('kind') == 'compare_functions'
    evaluation = isinstance(answer, dict) and answer.get('kind') in ('find_value', 'check_constant', 'finite_sum')
    if (checkpoint["status"] != "verified" or answer is None
            or (feasible_set is None and not (comparison or evaluation))
            or (comparison and (feasible_set is not None or answer.get('status') != 'complete'
                                or 'comparison_result' not in (route.get('result') or {})))
            or (evaluation and (feasible_set is not None or answer.get('status') != 'complete'
                                or 'evaluation_result' not in (route.get('result') or {})))):
        raise ValueError("handoff.incomplete_finalization")
    if consistency not in {"consistent", "conflict", "unknown"}:
        raise ValueError("handoff.invalid_consistency")
    target, route_id = checkpoint["target_ref"], checkpoint["route_id"]
    validate_original_choice(original_choice, target)
    if (original_choice and original_choice.get("matching") == "set_equality"
            and (answer.get("kind") not in {"find_range", "find_domain", "match_domain", "find_abstract_domain", "find_abstract_domain_parameter", "find_abstract_range", "find_translation_range"}
                 or answer.get("status") != "set")):
        raise ValueError("handoff.invalid_original_choice_goal")
    choice_fields = {"original_choice": deepcopy(original_choice)} if original_choice is not None else {}
    for key, expected in (("target_ref", target), ("route_id", route_id)):
        if route.get(key, expected) != expected:
            raise ValueError("handoff.route_identity_mismatch")
    request = {"checkpoint": checkpoint, "route": route, "verification": verification,
               "feasible_set": feasible_set, "answer": answer, "consistency": consistency, **choice_fields}

    def mutate(db):
        current = store._goal(db, target)
        steps = store._steps(db, target, route_id)
        if store._checkpoint(db, target, route_id) is None or not steps:
            raise ValueError("handoff.missing_committed_math")
        frozen_steps = [{key: step[key] for key in ("step_id", "ordinal", "math_step_sha256")} for step in steps]
        route_hash = verified_route_hash(route=route, verification=verification, feasible_set=feasible_set,
                                        answer=answer, math_steps=frozen_steps, revisions=store.identity["revisions"],
                                        original_choice=original_choice)
        saved = store._execute(db, 'SELECT value FROM lesson_handoffs WHERE run_id=:run_id AND target=:target AND route=:route',
                               target=target, route=route_id).fetchone()
        if saved:
            previous = json.loads(saved[0])
            if previous["verified_route_sha256"] != route_hash:
                raise ValueError("handoff.immutable_route")
            return {"checkpoint": store._checkpoint(db, target, route_id), "handoff": previous}
        store._append_event(db, commit_id, {"type": "lesson.route_status", "target_ref": target,
                                            "route_id": route_id, "payload": {"status": "verified"}})
        final_checkpoint = deepcopy(checkpoint)
        final_checkpoint["verified_route_sha256"] = route_hash
        final_checkpoint["finalization"] = {"verification": verification, "feasible_set": feasible_set,
                                            "answer": answer, **choice_fields}
        if consistency != "consistent" or goal_unavailable(current):
            status = "conflict" if consistency == "conflict" or (current and current["status"] == "conflict") else "no_verified_route"
            reason = "route_conflict" if status == "conflict" else "route_consistency_undecidable"
            goal = {"status": status, "reason": reason, "available": False}
            store._put_goal(db, target, goal)
            store._append_event(db, commit_id, {"type": "lesson.goal_status", "target_ref": target,
                                                "route_id": None, "payload": goal})
            return {"checkpoint": store._put_checkpoint(db, final_checkpoint, commit_id), "handoff": None}
        task = {
            "contract": "graph-stage-four-handoff/v1", "lesson_version": store.identity["lesson_version"],
            "run_id": store.identity["run_id"], "target_ref": target, "route_id": route_id,
            "verified_route_sha256": route_hash, "math_steps": frozen_steps,
            "feasible_set": deepcopy(feasible_set), "answer": deepcopy(answer), "status": "pending", "available": True,
            **choice_fields,
        }
        task["task_id"] = revision({key: task[key] for key in (
            "lesson_version", "run_id", "target_ref", "route_id", "verified_route_sha256",
        )})
        store._execute(db, 'INSERT INTO lesson_handoffs (run_id,target,route,value) VALUES (:run_id,:target,:route,:value)',
                       target=target, route=route_id, value=_dump(task))
        goal = {"status": "solved", "available": True, "feasible_set": feasible_set, "answer": answer}
        store._put_goal(db, target, goal)
        store._append_event(db, commit_id, {"type": "lesson.goal_status", "target_ref": target,
                                            "route_id": None, "payload": goal})
        store._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target,
            "route_id": route_id, "payload": {"kind": "route_completion", "verified_route_sha256": route_hash,
                "answer": deepcopy(answer), "feasible_set": deepcopy(feasible_set), "status": "verified", **choice_fields}})
        store._append_event(db, commit_id, {"type": "lesson.enrichment_status", "target_ref": target,
                                            "route_id": route_id, "payload": {"status": "pending", "task_id": task["task_id"]}})
        return {"checkpoint": store._put_checkpoint(db, final_checkpoint, commit_id), "handoff": task}

    return store._transaction(commit_id, request, mutate, before_commit=before_commit, after_commit=after_commit)


def invalidate_goal(store, target_ref, *, status, reason, commit_id):
    if status not in {"conflict", "no_verified_route"}:
        raise ValueError("handoff.invalid_goal_status")
    return store.commit_events([{
        "type": "lesson.goal_status", "target_ref": target_ref, "route_id": None,
        "payload": {"status": status, "reason": reason, "available": False},
    }], commit_id=commit_id)


def attach_qa(store, chunk, *, commit_id, before_commit=None, after_commit=None):
    """Attach one immutable QA payload; never accept mathematical replacements."""
    required = {"lesson_version", "run_id", "target_ref", "route_id", "step_id",
                "math_step_sha256", "verified_route_sha256", "qa"}
    if set(chunk) != required or not isinstance(chunk.get("qa"), dict):
        raise ValueError("handoff.invalid_qa_shape")
    if not set(chunk["qa"]) <= {"questions", "possible_questions", "hints", "common_errors", "feedback"}:
        raise ValueError("handoff.invalid_qa_fields")
    for key in ("run_id", "lesson_version"):
        if chunk[key] != store.identity[key]:
            raise ValueError("handoff.qa_identity_mismatch")

    def mutate(db):
        target, route, step_id = chunk["target_ref"], chunk["route_id"], chunk["step_id"]
        goal = store._goal(db, target)
        if not goal or goal["status"] != "solved" or goal_unavailable(goal):
            raise ValueError("handoff.goal_unavailable")
        task_row = store._execute(db, 'SELECT value FROM lesson_handoffs WHERE run_id=:run_id AND target=:target AND route=:route',
                                  target=target, route=route).fetchone()
        if not task_row:
            raise ValueError("handoff.missing_task")
        task = json.loads(task_row[0])
        if not task["available"] or task["verified_route_sha256"] != chunk["verified_route_sha256"]:
            raise ValueError("handoff.route_hash_mismatch")
        step = next((value for value in task["math_steps"] if value["step_id"] == step_id), None)
        if step is None or step["math_step_sha256"] != chunk["math_step_sha256"]:
            raise ValueError("handoff.step_hash_mismatch")
        previous = store._execute(db, 'SELECT value FROM lesson_qa WHERE run_id=:run_id AND target=:target AND route=:route AND step=:step',
                                  target=target, route=route, step=step_id).fetchone()
        if previous:
            if json.loads(previous[0]) != chunk:
                raise ValueError("handoff.immutable_qa")
            return {"qa": deepcopy(chunk)}
        store._execute(db, 'INSERT INTO lesson_qa (run_id,target,route,step,value) VALUES (:run_id,:target,:route,:step,:value)',
                       target=target, route=route, step=step_id, value=_dump(chunk))
        store._append_event(db, commit_id, {"type": "lesson.chunk_ready", "target_ref": target,
            "route_id": route, "payload": {"kind": "step_qa", "step_id": step_id,
                "math_step_sha256": chunk["math_step_sha256"], "verified_route_sha256": chunk["verified_route_sha256"],
                "chunk": chunk}})
        return {"qa": deepcopy(chunk)}

    return store._transaction(commit_id, chunk, mutate, before_commit=before_commit, after_commit=after_commit)


def enrichment_status(store, target_ref, route_id, *, status, commit_id, diagnostic=None):
    if status not in {"pending", "running", "completed", "partial", "failed"}:
        raise ValueError("handoff.invalid_enrichment_status")
    request = {"target_ref": target_ref, "route_id": route_id, "status": status, "diagnostic": diagnostic}

    def mutate(db):
        if goal_unavailable(store._goal(db, target_ref)):
            raise ValueError("handoff.goal_unavailable")
        saved = store._execute(db, 'SELECT value FROM lesson_handoffs WHERE run_id=:run_id AND target=:target AND route=:route',
                               target=target_ref, route=route_id).fetchone()
        if not saved:
            raise ValueError("handoff.missing_task")
        task = json.loads(saved[0])
        if status == "completed":
            count = store._execute(db, 'SELECT COUNT(*) FROM lesson_qa WHERE run_id=:run_id AND target=:target AND route=:route',
                                   target=target_ref, route=route_id).fetchone()[0]
            if count != len(task["math_steps"]):
                raise ValueError("handoff.incomplete_qa")
        task.update(status=status, diagnostic=diagnostic)
        store._execute(db, 'UPDATE lesson_handoffs SET value=:value WHERE run_id=:run_id AND target=:target AND route=:route',
                       value=_dump(task), target=target_ref, route=route_id)
        store._append_event(db, commit_id, {"type": "lesson.enrichment_status", "target_ref": target_ref,
            "route_id": route_id, "payload": {"status": status, "diagnostic": diagnostic}})
        return {"handoff": task}

    return store._transaction(commit_id, request, mutate)
