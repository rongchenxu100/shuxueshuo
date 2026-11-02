"""Admit stage-two artifacts, select methods, and durably execute supported routes."""

import json
import math
import shutil
from contextlib import ExitStack
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save

from ..stage_two import runner as stage_two_runner
from ..stage_two.contracts import ROOT, targets
from . import interaction, interaction_jobs
from .budget import BudgetConflict
from .checkpoint import identity_from_seed
from .contracts import (
    INPUT_MANIFEST_CONTRACT,
    RESULT_CONTRACT,
    aggregate_status,
    validate_result,
)
from .execution_contracts import allowed_methods, default_milestone, milestones
from .preparation import (
    ADMISSION_BUDGET_SECONDS,
    SELECTION_BUDGET_SECONDS,
    TargetPreparation,
    admit,
    error_detail,
)
from .route_calculations import PreparationTimeout

MILESTONE = default_milestone()
MILESTONES = milestones()


def fingerprint():
    # Interaction compilation and scheduling have their own revisions; editing
    # them must not invalidate mathematical resumption.
    excluded = {*interaction.ENGINE_FILES, *interaction_jobs.ORCHESTRATION_FILES}
    paths = [
        *(path for path in Path(__file__).parent.rglob("*.py") if path.resolve() not in excluded),
        *Path(__file__).parents[2].joinpath("problem_understanding").glob("notation_*.py"),
        *Path(__file__).parent.parent.joinpath("stage_one").glob("*.py"),
        *Path(__file__).parent.parent.joinpath("stage_two").glob("*.py"),
        Path(__file__).parent.parent / "domain_expression.py",
        Path(__file__).parent.parent / "range_syntax.py",
        Path(__file__).parent.parent / 'function_equality.py',
        Path(__file__).parent.parent / 'function_evaluation.py',
        Path(__file__).parent.parent / 'function_formula.py',
        Path(__file__).parent.parent / 'function_matching.py',
        Path(__file__).parent.parent / 'function_coefficients.py',
        Path(__file__).parent.parent / 'function_system.py',
        Path(__file__).parent.parent / 'function_assignment.py',
        Path(__file__).parent / 'equality_presentation.py',
        *(ROOT / "site/data/knowledge-next/selection").glob("*.json"),
        *(ROOT / "site/data/knowledge-next/execution").glob("*.json"),
        *(ROOT / "site/data/knowledge-next/nodes").glob("*.json"),
        *(ROOT / "internal/schemas").glob("graph-stage-three-*.json"),
        *(ROOT / "internal/schemas").glob("graph-method-*.json"),
        *(ROOT / "internal/schemas").glob("graph-math-step-*.schema.json"),
        ROOT / "site/data/graph-walk/quadratic-always-q01.source.json",
    ]
    return {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(paths)) if path.is_file()}


def zero_calls():
    return {key: 0 for key in ("semantic_calls", "network_attempts", "new_semantic_calls", "new_network_attempts")}


def _provenance(value, reference):
    return {"reference": str(reference) if reference is not None else None,
            "sha256": revision(value) if value is not None else None,
            "run_id": value.get("run_id") if isinstance(value, dict) else None}


def _target_failure(goal, exc, phase, store, *, status="execution_error", code="execution.target_error"):
    """Record an isolated failure and revoke any completion from an earlier resume."""
    if phase == "execute_goal":
        goal["execution_evidence"] = {"routes": goal["routes"], "selection": goal["selection"]}
    published = {}
    if store:
        from .handoff import invalidate_goal

        published = {event["payload"]["kind"].lower(): event["payload"]["chunk"]
                     for event in store.committed_events(goal["target_ref"] + ":selection")
                     if event["type"] == "lesson.chunk_ready" and event["payload"].get("kind") in ("D3", "D4")}
        # A repeated failure has the same invalidation payload and commit key.
        # The durable stream, final result and QA availability must agree even
        # when the failure occurs before method selection can run again.
        invalidate_goal(store, goal["target_ref"], status="no_verified_route", reason=code,
                        commit_id=goal["target_ref"] + ":" + code)
    # Published selection cards are immutable history, not a completed answer.
    # Read them from the committed transaction, not partially rebuilt values.
    goal.update(status=status, selection=goal["selection"] if published else None,
                d3=published.get("d3"), d4=published.get("d4"),
                routes=[], answer=None, feasible_set=None)
    goal["diagnostics"].append({
        "code": code, "path": goal["target_ref"], "phase": phase, **error_detail(exc),
    })


def _open_store(output, result, frozen, *, create):
    from .events import EventStore

    return EventStore(output, {**identity_from_seed(result), "revisions": frozen}, create=create)


def _resume_admission_failure(output, saved, loaded, timing, frozen, started):
    """An unfinished recheck is not evidence of changed input or a valid answer."""
    from .report import render_result

    result = deepcopy(saved)
    result["goals"] = result.pop("retained_goals", result["goals"])
    result.setdefault("preparation", {"admission": [], "targets": {}})["admission"].append(timing)
    result.update(status="input_error", input_validation={"ok": False, "diagnostics": loaded["diagnostics"]},
                  input_diagnostics=loaded["diagnostics"])
    store = _open_store(output, saved, frozen, create=False)
    snapshot_targets = store.snapshot()["goals"]
    retained_folders = {}
    retained_goals = {}
    for folder in sorted((output / "goals").glob("goal-*")):
        try:
            retained = json.loads((folder / "goal.json").read_text())
            ref = retained["target_ref"]
        except (OSError, ValueError, KeyError, TypeError):
            continue  # The authoritative snapshot is still revoked below.
        if ref in snapshot_targets:
            retained_folders[ref], retained_goals[ref] = folder, retained
    # run.json deliberately has no completed goals. A killed parent may have
    # written per-target mirrors before the aggregate result ever existed.
    if not result["goals"]:
        result["goals"] = list(retained_goals.values())
    diagnostic = loaded["diagnostics"][0]
    for number, goal in enumerate(result["goals"], 1):
        if goal["stage_two_status"] != "resolved":
            continue
        _target_failure(goal, RuntimeError(diagnostic["message"]), "admission", store,
                        status="capability_gap" if diagnostic["code"] == "input.admission_timeout" else "execution_error",
                        code=diagnostic["code"])
        goal["diagnostics"][-1] = {**diagnostic, "path": goal["target_ref"]}
        folder = retained_folders.get(goal["target_ref"], output / "goals" / f"goal-{number:03}")
        save(folder / "goal.json", goal)
    # The parent may have died before ever writing its first result. Invalidate
    # snapshot targets too; a missing report must not leave earlier handoffs live.
    from .handoff import invalidate_goal

    for ref in snapshot_targets:
        invalidate_goal(store, ref, status="no_verified_route", reason=diagnostic["code"],
                        commit_id=ref + ":" + diagnostic["code"])
    snapshot = store.export()
    for number, goal in enumerate(result["goals"], 1):
        for task in snapshot["handoffs"]:
            if task["target_ref"] == goal["target_ref"]:
                folder = retained_folders.get(goal["target_ref"], output / "goals" / f"goal-{number:03}")
                save(folder / "handoff" / (task["route_id"] + ".json"), task)
    # A missing/damaged goal mirror must not prevent revoking a retained task
    # mirror. Never use these files to restore authoritative execution state.
    tasks = {(task["target_ref"], task["route_id"]): task for task in snapshot["handoffs"]}
    for path in (output / "goals").glob("goal-*/handoff/*.json"):
        try:
            task = json.loads(path.read_text())
            replacement = tasks.get((task["target_ref"], task["route_id"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if replacement is not None:
            save(path, replacement)
    # An unvalidated input has no current admitted goals. Keep the revoked
    # historical summaries separately, matching the input_error schema.
    result["retained_goals"], result["goals"] = result["goals"], []
    result["events"] = {"stream_id": result["run_id"], "last_seq": snapshot["last_seq"], "snapshot": "checkpoint.json"}
    result["elapsed_seconds"] = round(perf_counter() - started, 6)
    validate_result(result)
    save(output / "stage-three-result.json", result)
    render_result(output)
    return result


def _interaction_scheduler(store, hooks):
    """Start this run's interaction worker; runs recorded without the protocol have none."""
    hooks = hooks or {}
    if store is None or store.interaction_settings() is None or hooks.get("interaction_scheduler") is False:
        return None
    from .calculations import dispatch

    return interaction_jobs.InteractionScheduler(
        store, dispatch=hooks.get("interaction_dispatch") or dispatch,
        hooks=hooks,
    ).start()


def _finish_interactions(scheduler, output):
    if scheduler is not None:
        scheduler.finish()
        # A recoverable scheduling/storage failure does not revoke mathematics.
        # Keep its diagnostics while pending cards remain explicitly resumable.
        save(Path(output) / "interaction-diagnostics.json", {"errors": scheduler.errors})


def run_sample(source, output, *, reference_base=None, milestone=MILESTONE, resume=False, hooks=None,
               solve_budget_seconds=10, verification_budget_seconds=20,
               admission_budget_seconds=ADMISSION_BUDGET_SECONDS, selection_budget_seconds=SELECTION_BUDGET_SECONDS,
               interactions=True):
    """Read an external stage-two result; invalid input still gets a debug report.

    ``interactions`` applies to a new run only; a resumed run keeps the choice
    (and frozen rules) it was created with.
    """
    if milestone not in MILESTONES or any(not math.isfinite(value) or value <= 0
                                         for value in (solve_budget_seconds, verification_budget_seconds,
                                                       admission_budget_seconds, selection_budget_seconds)):
        raise ValueError("execution.invalid_options")
    output = Path(output)
    if not resume:
        output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    if resume:
        saved = json.loads((output / "run.json").read_text())
        previous_result = output / "stage-three-result.json"
        if previous_result.is_file():
            previous = json.loads(previous_result.read_text())
            if any(previous[key] != saved[key] for key in (
                "run_id", "lesson_version", "milestone", "options", "stage_one", "stage_two",
            )):
                raise ValueError("checkpoint.result_identity_changed")
            saved = previous
        source = output / "stage-two-input.json"
        milestone = saved["milestone"]
        if milestone == "1a":
            raise ValueError("checkpoint.selection_only_run")
        admission_budget_seconds = saved["options"].get("admission_budget_seconds", ADMISSION_BUDGET_SECONDS)
        selection_budget_seconds = saved["options"].get("selection_budget_seconds", SELECTION_BUDGET_SECONDS)
    loaded, admission_timing = admit(source, output=output, reference_base=reference_base,
                                     budget_seconds=admission_budget_seconds, hooks=hooks)
    stage_two, stage_one = loaded["stage_two"], loaded["stage_one"]
    frozen = fingerprint()
    run_id = uuid4().hex
    result = {
        "contract": RESULT_CONTRACT, "run_id": run_id, "milestone": milestone,
        "created_at": datetime.now(UTC).isoformat(),
        "lesson_version": revision({"stage_two": stage_two, "stage_one": stage_one, "implementation": frozen}),
        "stage_two": _provenance(stage_two, loaded["source"]),
        "stage_one": _provenance(stage_one, loaded["stage_one_source"]),
        "input_validation": {"ok": loaded["ok"], "diagnostics": loaded["diagnostics"]},
        "input_diagnostics": loaded["diagnostics"],
        "status": "completed" if loaded["ok"] else "input_error", "goals": [],
        "events": {"stream_id": run_id, "last_seq": 0, "snapshot": None},
        "llm": zero_calls(),
        "upstream_llm": stage_two.get("llm") if isinstance(stage_two, dict) else None,
        "options": {"solve_budget_seconds": solve_budget_seconds, "verification_budget_seconds": verification_budget_seconds,
                    "admission_budget_seconds": admission_budget_seconds, "selection_budget_seconds": selection_budget_seconds},
        "preparation": {"admission": [admission_timing], "targets": {}},
    }
    if resume:
        frozen_saved = json.loads((output / "frozen.json").read_text())
        if frozen_saved["implementation"] != frozen:
            raise ValueError("checkpoint.revisions_changed")
        if not loaded["ok"] and any(row["code"] in ("input.admission_timeout", "input.admission_error")
                                    for row in loaded["diagnostics"]):
            return _resume_admission_failure(output, saved, loaded, admission_timing, frozen, started)
        if not loaded["ok"] or any(result[name]["sha256"] != saved[name]["sha256"] for name in ("stage_one", "stage_two")):
            raise ValueError("checkpoint.input_changed")
        result = saved
        result["goals"] = []
        result.pop("retained_goals", None)
        result.update(status="completed", input_validation={"ok": True, "diagnostics": []}, input_diagnostics=[])
        result.setdefault("preparation", {"admission": [], "targets": {}})["admission"].append(admission_timing)
        solve_budget_seconds = result["options"]["solve_budget_seconds"]
        verification_budget_seconds = result["options"]["verification_budget_seconds"]
    # Store the actual checked values so reports remain inspectable after moving
    # the output directory or deleting the source run.
    if not resume:
        save(output / "stage-two-input.json", stage_two)
        save(output / "stage-one-input.json", stage_one)
        save(output / "input.json", {
            "contract": INPUT_MANIFEST_CONTRACT,
            "stage_two": {**result["stage_two"], "snapshot": "stage-two-input.json"},
            "stage_one": {**result["stage_one"], "snapshot": "stage-one-input.json"},
            "admission": loaded["admission"],
        })
        save(output / "frozen.json", {"milestone": milestone, "implementation": frozen})
        save(output / "run.json", result)
    image = Path(source).parent / "source.png"
    if image.is_file() and image.resolve() != (output / "source.png").resolve():
        shutil.copyfile(image, output / "source.png")
    store = preparation_store = None
    if loaded["ok"]:
        preparation_store = _open_store(output, result, frozen, create=not resume)
        if milestone != "1a":
            store = preparation_store
            if not resume and interactions:
                registry = interaction.load_registry()
                group_seconds, route_seconds = (hooks or {}).get(
                    "interaction_budget", (interaction_jobs.GROUP_SECONDS, interaction_jobs.ROUTE_SECONDS))
                store.enable_interactions(registry, revision=interaction.registry_revision(registry),
                                          engine_revision=interaction.engine_revision(),
                                          budget={"group_seconds": group_seconds, "route_seconds": route_seconds})
    scheduler = _interaction_scheduler(store, hooks)
    try:
        _run_goals(loaded, result, output, store, preparation_store, stage_one, stage_two, milestone, hooks,
                   solve_budget_seconds=solve_budget_seconds, verification_budget_seconds=verification_budget_seconds,
                   selection_budget_seconds=selection_budget_seconds)
    except BaseException:
        if scheduler is not None:
            scheduler.stop()
        raise
    _finish_interactions(scheduler, output)
    if store:
        snapshot = store.export()
        folders = {goal["target_ref"]: output / "goals" / f"goal-{index:03}"
                   for index, goal in enumerate(result["goals"], 1)}
        for task in snapshot["handoffs"]:
            save(folders[task["target_ref"]] / "handoff" / (task["route_id"] + ".json"), task)
        result["events"] = {"stream_id": result["run_id"], "last_seq": snapshot["last_seq"], "snapshot": "checkpoint.json"}
    result["elapsed_seconds"] = round(perf_counter() - started, 6)
    validate_result(result)
    save(output / "stage-three-result.json", result)
    from .report import render_result

    render_result(output)
    return result


def _run_goals(loaded, result, output, store, preparation_store, stage_one, stage_two, milestone, hooks, *,
               solve_budget_seconds, verification_budget_seconds, selection_budget_seconds):
    if loaded["ok"]:
        candidate = stage_one["candidate"]
        original_targets = {row["target_ref"]: row for row in targets(candidate)}
        for number, previous in enumerate(stage_two["goals"], 1):
            ref = previous["target_ref"]
            original = original_targets[ref]
            features = [row for row in stage_one["features"] if row["target_ref"] == ref]
            goal = {
                **original, "stage_two_status": previous["status"],
                "primary": previous["primary"], "primary_source": previous["primary_source"],
                "status": "skipped", "selection": None, "d3": None, "d4": None,
                "routes": [], "route_status": [], "feasible_set": None, "answer": None,
                "diagnostics": [], "constraint_context": None, "features": features,
            }
            if previous["status"] == "resolved":
                phase = "build_context"
                try:
                    with TargetPreparation(preparation_store, ref, budget_seconds=selection_budget_seconds,
                                           hooks=hooks) as preparation:
                        try:
                            goal["constraint_context"] = preparation.prepare("build_context", candidate=candidate,
                                                                              target_ref=ref)
                            phase = "evaluate_goal"
                            goal.update(preparation.prepare("evaluate_goal", candidate=candidate, target_ref=ref,
                                                            features=features, primary=previous["primary"]))
                        finally:
                            result["preparation"]["targets"][ref] = preparation.summary()
                except BudgetConflict:
                    raise
                except PreparationTimeout as exc:
                    _target_failure(goal, exc, phase, store, status="capability_gap", code="preparation.budget_exhausted")
                except Exception as exc:  # noqa: BLE001 — persist failure at the target isolation boundary
                    # This is the target isolation boundary, not a mathematical
                    # unknown: programming failures stay visible and fail the run.
                    _target_failure(goal, exc, phase, store)
            else:
                goal["diagnostics"].append({
                    "code": "input.target_skipped", "path": ref,
                    "message": "阶段②未确认本目标，保留其状态，不进行选法。",
                    "stage_two_status": previous["status"],
                })
            result["goals"].append(goal)
            folder = output / "goals" / f"goal-{number:03}"
            if store and goal["selection"] and goal["status"] not in ("execution_error", "capability_gap"):
                try:
                    _execute_goal(candidate, goal, folder, store, milestone=milestone, hooks=hooks,
                                  solve_budget_seconds=solve_budget_seconds,
                                  verification_budget_seconds=verification_budget_seconds)
                except BudgetConflict:
                    # A concurrent resume does not invalidate the live owner's
                    # already published route. It must retry after that lease.
                    raise
                except Exception as exc:  # noqa: BLE001 — preserve all other goals and the durable prefix
                    _target_failure(goal, exc, "execute_goal", store)
            for name, value in (("selection", goal["selection"]), ("d3", goal["d3"]),
                                ("d4", goal["d4"]), ("context", goal["constraint_context"]),
                                ("features", features), ("goal", goal)):
                save(folder / f"{name}.json", value)
        result["status"] = aggregate_status(result["goals"])


def _execute_goal(candidate, goal, folder, store, *, milestone, hooks, **budgets):
    with ExitStack() as stack:
        return _execute_goal_in_session(candidate, goal, folder, store, stack=stack,
                                        milestone=milestone, hooks=hooks, **budgets)


def _execute_goal_in_session(candidate, goal, folder, store, *, stack, milestone, hooks, **budgets):
    from .execution import execute_route, prepare_route
    from .route_calculations import RouteCalculations

    allowed = allowed_methods(milestone)
    prepared, calculators = {}, {}
    for branch in goal["selection"]["branches"]:
        if branch["route_plan"] == "not_planned":
            continue
        if branch["target"] in allowed:
            route_id = branch["route_id"]
            calculator = stack.enter_context(RouteCalculations(store, goal["target_ref"], route_id,
                                                               hooks=hooks, **budgets))
            prepared[route_id] = prepare_route(goal, branch, store, calculator)
            calculators[route_id] = calculator
            if prepared[route_id]["status"] != "capability_gap":
                branch.update(route_plan="planned", missing_capabilities=[])
    for option in goal["d4"]["options"]:
        branch = next(row for row in goal["selection"]["branches"] if row["route_id"] == option["route_id"])
        option["route_plan"] = branch["route_plan"]
        option["message"] = "开始解题" if branch["route_plan"] == "planned" else "详细步骤暂不支持"
    store.commit_events([{"type": "lesson.chunk_ready", "target_ref": goal["target_ref"], "route_id": None,
                          "payload": {"kind": kind, "chunk": goal[kind.lower()]}} for kind in ("D3", "D4")],
                        commit_id=goal["target_ref"] + ":selection")
    for branch in goal["selection"]["branches"]:
        if branch["route_plan"] == "planned":
            route = execute_route(candidate, goal, branch, folder, store, previous=goal["routes"], hooks=hooks,
                                  calculator=calculators[branch["route_id"]], prepared=prepared[branch["route_id"]], **budgets)
            goal["routes"].append(route)
    snapshot, retained_events = store.snapshot_with_events()
    status = snapshot["goals"].get(goal["target_ref"])
    if status:
        goal["status"] = status["status"]
        if status["status"] == "solved" and status.get("available"):
            goal["answer"], goal["feasible_set"] = status["answer"], status["feasible_set"]
        elif status.get("reason"):
            goal["diagnostics"].append({"code": status["reason"]})
    else:
        store.commit_events([{"type": "lesson.goal_status", "target_ref": goal["target_ref"], "route_id": None,
                              "payload": {"status": goal["status"]}}], commit_id=goal["target_ref"] + ":final-status")
    goal["route_status"] = [{"route_id": event["route_id"], "seq": event["seq"], **event["payload"]}
                            for event in retained_events
                            if event["type"] == "lesson.route_status" and event["target_ref"] == goal["target_ref"]]


def resume_sample(output, *, hooks=None):
    return run_sample(None, output, resume=True, hooks=hooks)


def resume_interactions(output, *, hooks=None):
    """Drain a completed run's interactions without admitting or rerunning mathematics.

    The product caller holds its run lock and validates the current attempt and
    frozen mathematical revision, just as it does for a mathematical resume.
    """
    from .preview import open_store

    output = Path(output)
    result = json.loads((output / "stage-three-result.json").read_text())
    store = open_store(output)
    if not store.has_pending_interactions():
        return result
    scheduler = _interaction_scheduler(store, hooks)
    _finish_interactions(scheduler, output)
    snapshot = store.export()
    result["events"]["last_seq"] = snapshot["last_seq"]
    validate_result(result)
    save(output / "stage-three-result.json", result)
    return result


def _no_provider(*args, **kwargs):
    raise RuntimeError("Stage-three offline acceptance cannot construct an LLM provider")


def run_recorded_batch(batch, output, *, cases=None, milestone=MILESTONE):
    """Reverify all stage-one records, run stage two offline, then admit its files."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    upstream = stage_two_runner.run_recorded_batch(
        batch, output / "stage-two", cases=cases, provider=_no_provider, verify=False,
    )
    rows = []
    for previous in upstream["results"]:
        relative = previous["sample_dir"]
        result = run_sample(output / "stage-two" / relative / "stage-two-result.json", output / relative, milestone=milestone)
        rows.append({key: previous[key] for key in ("case_id", "sample_id", "sample_dir")} | {
            "status": result["status"], "goals": len(result["goals"]),
            "eligible": sum(goal["stage_two_status"] == "resolved" for goal in result["goals"]),
            "skipped": sum(goal["status"] == "skipped" for goal in result["goals"]),
            "solved": sum(goal["status"] == "solved" for goal in result["goals"]),
            "verified_routes": sum(route["status"] == "verified" for goal in result["goals"] for route in goal["routes"]),
            "llm": result["llm"],
        })
    summary = {
        "contract": "graph-stage-three-batch/v1", "run_id": output.name, "milestone": milestone,
        "stage_one_recording": str(Path(batch).resolve()), "stage_two_batch": "stage-two/batch-summary.json",
        "completed": bool(rows) and upstream["completed"] and all(row["status"] == "completed" for row in rows),
        "results": rows, "llm": zero_calls(), "upstream_llm": upstream["llm"],
    }
    save(output / "batch-summary.json", summary)
    from .report import render_batch

    render_batch(output)
    return summary
