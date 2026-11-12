"""Route orchestration: atomic progress, independent verification and handoff.

The driver interprets methods; this layer owns lifecycle and finalization. It
never selects mathematical operations by question identifier or source formula.
"""

import json
import traceback
from copy import deepcopy

from jsonschema import Draft202012Validator

from . import driver, verification
from .checkpoint import export_json, make_checkpoint
from .choice_completion import normalize_original_choice, resolve_original_choice
from .contracts import ROOT
from .goals import GoalClosureMismatch
from .handoff import complete_route
from .revision_manifest import revision_ref
from .route_calculations import RouteCalculations

TERMINAL = {"verified", "capability_gap", "math_failed", "execution_error"}


def _event(kind, state, payload):
    return {"type": kind, "target_ref": state["target_ref"], "route_id": state["route_id"], "payload": payload}


def _trajectory_changes(previous, current):
    """Send every changed record, including parents resumed after a child.

    A child return can complete an earlier call; finishing a case span also
    attaches collected results to its original degree record. The streaming
    consumer upserts by seq, so sending only the last record loses those sources.
    """
    prior = {record["seq"]: record for record in previous}
    return [record for record in current if prior.get(record["seq"]) != record]


def _checkpoint(store, state, *, phase="method", status="running"):
    return make_checkpoint(
        store.identity, state["target_ref"], state["route_id"], driver_state=state,
        status=status, phase=phase, next_instance=len(state["fragments"]),
        compute_seconds={"solve": state["compute_seconds"], "verification": state.get("verification_seconds", 0)},
    )


def _commit(store, state, suffix, *, events=(), phase="method", status="running", hooks=None):
    commit_id = f"{state['target_ref']}:{state['route_id']}:{suffix}"
    previous_cursor = state.get("publication_cursor")
    # Keep the previous boundary in this commit's cursor so retrying the same
    # logical commit submits exactly the same delta, including after recovery.
    # Legacy checkpoints lack the cursor: their first commit rechecks the old
    # prefix once, then uses the same incremental publication contract.
    start = (previous_cursor["from"] if previous_cursor["commit_id"] == commit_id
             else previous_cursor["through"]) if previous_cursor else 0
    end = len(state["fragments"])
    if type(start) is not int or not 0 <= start <= end:
        raise ValueError("events.invalid_publication_cursor")
    state["publication_cursor"] = {"commit_id": commit_id, "from": start, "through": end}
    hooks = hooks or {}
    # Hooks are observer/fault-injection seams, outside the measured arithmetic.
    def callback(name):
        function = hooks.get(name)
        return (lambda: function(state, store)) if function else None

    try:
        checkpoint = _checkpoint(store, state, phase=phase, status=status)
        store.commit_route(checkpoint, commit_id=commit_id, math_steps=state["fragments"][start:], events=events,
                           before_commit=callback("before_commit"), after_commit=callback("after_commit"))
    except BaseException:
        # A failed publication must not advance the caller's in-memory cursor.
        # If the commit actually succeeded before a fault, PostgreSQL retains the
        # authoritative cursor for resume and duplicate steps stay immutable.
        if previous_cursor is None:
            state.pop("publication_cursor", None)
        else:
            state["publication_cursor"] = previous_cursor
        raise
    if hooks.get("committed"):
        hooks["committed"](state, store)


def _accept_state(previous, updated):
    """Workers may append cards, never rewrite the already published prefix."""
    prefix = previous["fragments"]
    if (updated["fragments"][:len(prefix)] != prefix
            or updated.get("publication_cursor") != previous.get("publication_cursor")):
        raise ValueError("events.immutable_step")
    return updated


def _artifact(state, context, folder):
    refs = []
    for step in state["fragments"]:
        path = folder / "math-steps" / state["route_id"] / (step["step_id"] + ".json")
        export_json(path, step)
        refs.append({"step_id": step["step_id"], "math_step_sha256": step["math_step_sha256"],
                     "source_refs": step["source_refs"], "file": str(path.relative_to(folder.parents[1]))})
    resolved_context = deepcopy(context)
    applied = next((item for item in state.get("finalization", [])
                    if item.get("capability") == "apply_visible_constraints"), None)
    if applied:
        for entry in resolved_context["entries"]:
            evidence = [row for row in applied["processing"] if row["source_ref"] == entry["source_ref"]]
            if evidence:
                entry["processing"] = {"status": "processed", "evidence": evidence}
        pending = [entry["source_ref"] for entry in resolved_context["entries"]
                   if entry["processing"]["status"] == "pending"]
        resolved_context["processing"] = {"status": "complete" if not pending else "pending",
                                           "unprocessed_source_refs": pending}
    route = {
        "contract": "graph-stage-three-route/v2",
        **{key: state[key] for key in ("run_id", "lesson_version", "target_ref", "route_id", "branch", "method")},
        "revisions_ref": revision_ref(state),
        "status": state["status"], "steps": state["trajectory"]["steps"], "math_steps": refs,
        "constraint_context": resolved_context, "finalization": state.get("finalization", []),
        "result": state.get("verified_result"), "diagnostics": state.get("diagnostics", []),
        "verification_timing": {
            "budget_seconds": state.get("verification_budget_seconds"),
            "elapsed_seconds": state.get("verification_seconds", 0),
            "operations": state.get("verification_timing", []),
        },
        "solve_timing": {
            "budget_seconds": state.get("solve_budget_seconds"),
            "elapsed_seconds": state.get("compute_seconds", 0),
            "operations": state.get("solve_timing", []),
        },
        "budget_accounting": state.get("budget_accounting", {}),
    }
    route.update({key: state["trajectory"][key] for key in ("gap", "error") if key in state["trajectory"]})
    schema = json.loads((ROOT / "internal/schemas/graph-stage-three-route-v2.schema.json").read_text())
    Draft202012Validator(schema).validate(route)
    return route


def _mark_failure(state, exc):
    if isinstance(exc, GoalClosureMismatch):
        state["status"] = "math_failed"
        diagnostic = {"code": "goal_finalize.answer_mismatch", "message": str(exc)}
    elif isinstance(exc, verification.ContextMismatch):
        state["status"] = "math_failed"
        diagnostic = {"code": "constraint_context_mismatch", "message": str(exc)}
    elif isinstance(exc, verification.VerificationGap):
        state["status"] = "capability_gap"
        diagnostic = {"code": str(exc)}
    else:
        state["status"] = "execution_error"
        diagnostic = {"code": "execution.route_error", "message": str(exc),
                      "exception_type": type(exc).__name__, "traceback": traceback.format_exc()}
    state.setdefault("diagnostics", []).append(diagnostic)


def prepare_route(goal, branch, store, calculator):
    """Bound admission and initial bindings before publishing the D4 plan."""
    arguments = {
        "features": goal["features"], "context": goal["constraint_context"], "method": branch["target"],
        "route_id": branch["route_id"], "branch": branch["branch"], "target_ref": goal["target_ref"],
        "run_id": store.identity["run_id"], "lesson_version": store.identity["lesson_version"],
        "revisions": store.identity["revisions"], "solve_budget_seconds": calculator.limits["solve"],
    }
    state = driver.empty_state(**arguments)
    try:
        state = calculator.call("initialize", {"operation": "initialize", "arguments": arguments})
    except Exception as exc:  # noqa: BLE001 -- isolate admission failures without hiding their diagnostics.
        _mark_failure(state, exc)
    return calculator.sync_state(state)


def _finish_comparison(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('comparison_result_exact', deepcopy(state['result']['comparison_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_comparison_verification', {
            'operation': 'verify_comparisons', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'comparison_result_exact': state['comparison_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_comparison_verification', **state['verification']})
        calculator.sync_state(state)
        _commit(store, state, 'comparison-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('comparison_goal_finalize', {
            'operation': 'finish_comparisons', 'state': state, 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'comparison_result': result['comparison_result_exact'], 'answer': result['answer']}
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'comparison-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_evaluation(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('evaluation_result_exact', deepcopy(state['result']['evaluation_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_evaluation_verification', {
            'operation': 'verify_evaluation', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'evaluation_result_exact': state['evaluation_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_evaluation_verification', **state['verification']})
        calculator.sync_state(state)
        _commit(store, state, 'evaluation-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('evaluation_goal_finalize', {
            'operation': 'finish_evaluation', 'state': state, 'context': goal['constraint_context'],
            'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'evaluation_result': result['evaluation_result_exact'], 'answer': result['answer']}
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'evaluation-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_graph(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('graph_result_exact', deepcopy(state['result']['graph_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_graph_verification', {
            'operation': 'verify_function_graph', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'graph_result_exact': state['graph_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_graph_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'graph-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('graph_goal_finalize', {
            'operation': 'finish_function_graph', 'state': state, 'context': goal['constraint_context'],
            'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'graph_result': result['graph_result_exact'], 'answer': result['answer']}
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'graph-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_extremum(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('extremum_result_exact', deepcopy(state['result']['extremum_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_extremum_verification', {
            'operation': 'verify_function_extremum', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'extremum_result_exact': state['extremum_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_extremum_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'extremum-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('extremum_goal_finalize', {
            'operation': 'finish_function_extremum', 'state': state, 'context': goal['constraint_context'],
            'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'extremum_result': result['extremum_result_exact'], 'answer': result['answer']}
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'extremum-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_mono_inequality(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('mono_inequality_result_exact', deepcopy(state['result']['mono_inequality_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_mono_inequality_verification', {
            'operation': 'verify_monotonicity_inequality', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'],
            'mono_inequality_result_exact': state['mono_inequality_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_monotonicity_inequality_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'mono-inequality-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('mono_inequality_goal_finalize', {
            'operation': 'finish_monotonicity_inequality', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {
            'mono_inequality_result': result['mono_inequality_result_exact'],
            'answer': result['answer'],
        }
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'mono-inequality-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_mono_parameter(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('mono_parameter_result_exact', deepcopy(state['result']['mono_parameter_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_mono_parameter_verification', {
            'operation': 'verify_monotonicity_parameter', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'],
            'mono_parameter_result_exact': state['mono_parameter_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_monotonicity_parameter_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'mono-parameter-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('mono_parameter_goal_finalize', {
            'operation': 'finish_monotonicity_parameter', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {
            'mono_parameter_result': result['mono_parameter_result_exact'],
            'answer': result['answer'],
        }
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'mono-parameter-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_parity_parameter(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('parity_parameter_result_exact', deepcopy(state['result']['parity_parameter_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_parity_parameter_verification', {
            'operation': 'verify_parity_parameter', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'],
            'parity_parameter_result_exact': state['parity_parameter_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_parity_parameter_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'parity-parameter-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('parity_parameter_goal_finalize', {
            'operation': 'finish_parity_parameter', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {
            'parity_parameter_result': result['parity_parameter_result_exact'],
            'answer': result['answer'],
        }
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'parity-parameter-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_parity_extension(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('parity_extension_result_exact', deepcopy(state['result']['parity_extension_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_parity_extension_verification', {
            'operation': 'verify_parity_extension', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'],
            'parity_extension_result_exact': state['parity_extension_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_parity_extension_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'parity-extension-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('parity_extension_goal_finalize', {
            'operation': 'finish_parity_extension', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {
            'parity_extension_result': result['parity_extension_result_exact'],
            'answer': result['answer'],
        }
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'parity-extension-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_parity_inequality(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('parity_inequality_result_exact', deepcopy(state['result']['parity_inequality_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_parity_inequality_verification', {
            'operation': 'verify_parity_inequality', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'],
            'parity_inequality_result_exact': state['parity_inequality_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_parity_inequality_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'parity-inequality-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('parity_inequality_goal_finalize', {
            'operation': 'finish_parity_inequality', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {
            'parity_inequality_result': result['parity_inequality_result_exact'],
            'answer': result['answer'],
            'feasible_set': result['feasible_set'],
        }
        state['feasible_set_exact'] = result['feasible_set']['exact']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'parity-inequality-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_function_symmetry(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('symmetry_result_exact', deepcopy(state['result']['symmetry_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_function_symmetry_verification', {
            'operation': 'verify_function_symmetry', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'symmetry_result_exact': state['symmetry_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_symmetry_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'function-symmetry-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('function_symmetry_goal_finalize', {
            'operation': 'finish_function_symmetry', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'symmetry_result': result['symmetry_result_exact'], 'answer': result['answer']}
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'function-symmetry-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_parity(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('parity_result_exact', deepcopy(state['result']['parity_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_parity_verification', {
            'operation': 'verify_function_parity', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'parity_result_exact': state['parity_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_parity_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints',
                                 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'parity-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('parity_goal_finalize', {
            'operation': 'finish_function_parity', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'parity_result': result['parity_result_exact'], 'answer': result['answer']}
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'parity-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_abstract_monotonicity(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('monotonicity_result_exact', deepcopy(state['result']['monotonicity_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_abstract_monotonicity_verification', {
            'operation': 'verify_abstract_monotonicity', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'monotonicity_result_exact': state['monotonicity_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_abstract_monotonicity_verification', **state['verification']})
        calculator.sync_state(state)
        _commit(store, state, 'abstract-monotonicity-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('abstract_monotonicity_goal_finalize', {
            'operation': 'finish_abstract_monotonicity', 'state': state,
            'context': goal['constraint_context'], 'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'monotonicity_result': result['monotonicity_result_exact'], 'answer': result['answer']}
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'abstract-monotonicity-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_monotonicity(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('monotonicity_result_exact', deepcopy(state['result']['monotonicity_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_monotonicity_verification', {
            'operation': 'verify_function_monotonicity', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'monotonicity_result_exact': state['monotonicity_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_monotonicity_verification', **state['verification']})
        if state['verification']['status'] == 'verified' and state['verification'].get('processing'):
            finalization.append({'capability': 'apply_visible_constraints', 'processing': state['verification']['processing']})
        calculator.sync_state(state)
        _commit(store, state, 'monotonicity-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('monotonicity_goal_finalize', {
            'operation': 'finish_function_monotonicity', 'state': state, 'context': goal['constraint_context'],
            'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'monotonicity_result': result['monotonicity_result_exact'], 'answer': result['answer']}
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'monotonicity-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_formula(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('formula_result_exact', deepcopy(state['result']['formula_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_formula_verification', {
            'operation': 'verify_formula', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'formula_result_exact': state['formula_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_formula_verification', **state['verification']})
        calculator.sync_state(state)
        _commit(store, state, 'formula-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('formula_goal_finalize', {
            'operation': 'finish_formula', 'state': state, 'context': goal['constraint_context'],
            'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'formula_result': result['formula_result_exact'], 'answer': result['answer']}
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'formula-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def _finish_model(state, candidate, goal, store, calculator, previous, hooks):
    state.setdefault('model_result_exact', deepcopy(state['result']['model_result']))
    finalization = state.setdefault('finalization', [])
    if 'verification' not in state:
        if hooks and hooks.get('before_verification'):
            hooks['before_verification'](state, store)
        state['verification'] = calculator.call('independent_model_verification', {
            'operation': 'verify_model', 'candidate': candidate, 'target_ref': goal['target_ref'],
            'context': goal['constraint_context'], 'model_result_exact': state['model_result_exact'],
        }, bucket='verification')
        finalization.append({'capability': 'independent_function_model_verification', **state['verification']})
        calculator.sync_state(state)
        _commit(store, state, 'model-verification', phase='verification', hooks=hooks)
    if state['verification']['status'] != 'verified':
        state['status'] = state['verification']['status']
        state.setdefault('diagnostics', []).extend(state['verification'].get('diagnostics', []))
        return state
    if not state.get('goal_finalized'):
        result = calculator.call('model_goal_finalize', {
            'operation': 'finish_model', 'state': state, 'context': goal['constraint_context'],
            'previous': list(previous),
        }, bucket='verification')
        state = _accept_state(state, result['state'])
        state['verified_result'] = {'model_result': result['model_result_exact'], 'answer': result['answer']}
        if 'feasible_set' in result:
            state['feasible_set_exact'] = result['feasible_set']['exact']
            state['verified_result']['feasible_set'] = result['feasible_set']
        state['consistency'] = result['consistency']
        state['goal_finalized'] = True
        calculator.sync_state(state)
        _commit(store, state, 'model-goal-finalization', phase='finalization', hooks=hooks)
    state['status'] = 'verified'
    return state


def execute_route(candidate, goal, branch, folder, store, *, previous=(), hooks=None,
                  solve_budget_seconds=10, verification_budget_seconds=20, calculator=None, prepared=None):
    """Resume at a durable boundary, reusing receipts for completed computations."""
    ref, route_id = goal["target_ref"], branch["route_id"]
    if calculator is None:
        with RouteCalculations(store, ref, route_id, solve_budget_seconds=solve_budget_seconds,
                               verification_budget_seconds=verification_budget_seconds, hooks=hooks) as owned:
            return execute_route(candidate, goal, branch, folder, store, previous=previous, hooks=hooks,
                                 solve_budget_seconds=solve_budget_seconds,
                                 verification_budget_seconds=verification_budget_seconds, calculator=owned,
                                 prepared=prepare_route(goal, branch, store, owned))
    checkpoint = store.checkpoint(ref, route_id)
    if checkpoint:
        state = checkpoint["driver_state"]
    else:
        state = deepcopy(prepared)
        _commit(store, state, "start", events=[_event("lesson.route_status", state, {"status": "running"})], hooks=hooks)
    calculator.sync_state(state)
    if state["status"] not in TERMINAL:
        try:
            while state["status"] == "running":
                index = state.get("commit_index", 0) + 1
                previous_trajectory = state["trajectory"]["steps"]
                state = _accept_state(state, calculator.call(
                    f"advance:{index}", {"operation": "advance", "state": state},
                ))
                state["commit_index"] = index
                calculator.sync_state(state)
                _commit(store, state, f"operation-{index}",
                        events=[_event("solver.step_completed", state, {
                            "operation": index, "status": state["status"],
                            "trajectory": _trajectory_changes(
                                previous_trajectory, state["trajectory"]["steps"],
                            )})], hooks=hooks)
            if state['status'] == 'method_complete' and 'extremum_result' in state.get('result', {}):
                state = _finish_extremum(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'mono_inequality_result' in state.get('result', {}):
                state = _finish_mono_inequality(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'mono_parameter_result' in state.get('result', {}):
                state = _finish_mono_parameter(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'parity_parameter_result' in state.get('result', {}):
                state = _finish_parity_parameter(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'parity_extension_result' in state.get('result', {}):
                state = _finish_parity_extension(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'parity_inequality_result' in state.get('result', {}):
                state = _finish_parity_inequality(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'symmetry_result' in state.get('result', {}):
                state = _finish_function_symmetry(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'parity_result' in state.get('result', {}):
                state = _finish_parity(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'abstract_monotonicity_goal' in goal['constraint_context']:
                state = _finish_abstract_monotonicity(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and goal['goal']['kind'] in ('find_monotonic_intervals', 'prove_monotonicity_on_interval'):
                state = _finish_monotonicity(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and goal['goal']['kind'] in ('select_function_graph', 'draw_function_graph', 'solve_graph_inequality'):
                state = _finish_graph(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'model_result' in state.get('result', {}):
                state = _finish_model(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and 'formula_result' in state.get('result', {}):
                state = _finish_formula(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and goal['goal']['kind'] in ('find_value', 'check_constant', 'finite_sum'):
                state = _finish_evaluation(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and goal['goal']['kind'] == 'find_function_formula':
                state = _finish_formula(state, candidate, goal, store, calculator, previous, hooks)
            if state['status'] == 'method_complete' and goal['goal']['kind'] == 'compare_functions':
                state = _finish_comparison(state, candidate, goal, store, calculator, previous, hooks)
            if state["status"] == "method_complete":
                finalization = state.setdefault("finalization", [])
                common = {"candidate": candidate, "target_ref": ref, "context": goal["constraint_context"]}
                if not state.get("constraints_applied"):
                    result = calculator.call("apply_visible_constraints", {
                        **common, "operation": "constraints", "state": state,
                    }, bucket="verification")
                    state["feasible_set_exact"] = result["feasible_set_exact"]
                    state["constraints_applied"] = True
                    finalization.append({"capability": "apply_visible_constraints", "processing": result["processing"],
                                         "feasible_set": result["feasible_set"]})
                    calculator.sync_state(state)
                    _commit(store, state, "constraints", phase="verification", hooks=hooks)
                common["feasible_set_exact"] = state["feasible_set_exact"]
                if "verification" not in state:
                    if hooks and hooks.get("before_verification"):
                        hooks["before_verification"](state, store)
                    state["verification"] = calculator.call("independent_verification", {
                        **common, "operation": "verify",
                    }, bucket="verification")
                    finalization.append({"capability": "independent_verification", **state["verification"]})
                    calculator.sync_state(state)
                    _commit(store, state, "verification", phase="verification", hooks=hooks)
                if state["verification"]["status"] != "verified":
                    state["status"] = state["verification"]["status"]
                    state.setdefault("diagnostics", []).extend(state["verification"].get("diagnostics", []))
                else:
                    if "endpoint_evidence" not in state:
                        result = calculator.call("endpoint_check", {
                            **common, "operation": "endpoints", "state": state,
                        }, bucket="verification")
                        state = _accept_state(state, result["state"])
                        state["endpoint_evidence"] = result["evidence"]
                        calculator.sync_state(state)
                        # Publish the checked source in the same transaction,
                        # before the boundary card that references it. Sparse
                        # indices keep /finalization/N stable without sending
                        # the full independent proof on every update.
                        boundary_index = len(state["finalization"]) - 1
                        _commit(store, state, "endpoints", phase="finalization",
                                events=[_event("solver.step_completed", state, {
                                    "operation": "endpoint_check", "status": state["status"],
                                    "trajectory": [], "finalization": [{
                                        "index": boundary_index,
                                        "record": state["finalization"][boundary_index],
                                    }],
                                })], hooks=hooks)
                    if state["endpoint_evidence"]["status"] != "passed":
                        state["status"] = "math_failed"
                        state.setdefault("diagnostics", []).append({"code": "verification.endpoint_failed"})
                    else:
                        if not state.get("goal_finalized"):
                            result = calculator.call("goal_finalize_and_consistency", {
                                "operation": "finish", "goal": goal["goal"], "state": state,
                                "feasible_set_exact": state["feasible_set_exact"], "previous": list(previous),
                            }, bucket="verification")
                            state = _accept_state(state, result["state"])
                            state["verified_result"] = {"feasible_set": result["feasible_set"], "answer": result["answer"]}
                            state["consistency"] = result["consistency"]
                            state["goal_finalized"] = True
                            calculator.sync_state(state)
                            # Persist the final mathematical card and its source
                            # before the terminal publication/handoff boundary.
                            index = len(state["finalization"]) - 1
                            _commit(store, state, "goal-finalization", phase="finalization",
                                    events=[_event("solver.step_completed", state, {
                                        "operation": "finalize_goal", "status": state["status"],
                                        "trajectory": [], "finalization": [{
                                            "index": index, "record": state["finalization"][index],
                                        }],
                                    })], hooks=hooks)
                        state["status"] = "verified"
        except Exception as exc:  # noqa: BLE001 -- retain route evidence, never turn bugs into unknown.
            _mark_failure(state, exc)
        finally:
            calculator.sync_state(state)
    # Mathematical receipts and publication commits have independent durability.
    # A crash between them reuses the receipt and completes this boundary once.
    if store.checkpoint(ref, route_id)["status"] not in TERMINAL:
        route = _artifact(state, goal["constraint_context"], folder)
        if state["status"] == "verified":
            if 'symmetry_result' in state['verified_result'] or 'parity_extension_result' in state['verified_result'] or 'parity_inequality_result' in state['verified_result'] or 'parity_parameter_result' in state['verified_result'] or 'parity_result' in state['verified_result'] or 'extremum_result' in state['verified_result'] or 'mono_inequality_result' in state['verified_result'] or 'mono_parameter_result' in state['verified_result'] or 'monotonicity_result' in state['verified_result'] or 'model_result' in state['verified_result'] or 'graph_result' in state['verified_result'] or 'formula_result' in state['verified_result'] or goal['goal']['kind'] in ('find_value', 'check_constant', 'finite_sum', 'find_function_formula'):
                original_choice = None
            elif goal['goal']['kind'] == 'compare_functions':
                from .equality_runtime import original_choice as comparison_choice
                original_choice = comparison_choice(goal['constraint_context'], state['verified_result']['answer'])
                # This is the primary goal, so invalid closure is never an
                # optional unavailable matching enhancement.
                from .handoff import validate_original_choice
                validate_original_choice(original_choice, ref)
            else:
                original_choice = resolve_original_choice(
                    store, candidate, ref, route_id, state["verified_result"]["answer"], state["feasible_set_exact"],
                )
            original_choice = normalize_original_choice(original_choice, ref)
            complete_route(store, _checkpoint(store, state, phase="complete", status="verified"), route=route,
                           verification=state["verification"], feasible_set=state["verified_result"].get("feasible_set"),
                           answer=state["verified_result"]["answer"], commit_id=f"{ref}:{route_id}:complete",
                           consistency=state["consistency"], original_choice=original_choice)
        else:
            _commit(store, state, "terminal", status=state["status"], phase="complete",
                    events=[_event("lesson.route_status", state, {"status": state["status"], "diagnostics": state["diagnostics"]})],
                    hooks=hooks)
    route = _artifact(state, goal["constraint_context"], folder)
    path = folder / "routes" / (route_id + ".json")
    export_json(path, route)
    snapshot = store.export()
    for handoff in snapshot["handoffs"]:
        if handoff["target_ref"] == ref:
            export_json(folder / "handoff" / (handoff["route_id"] + ".json"), handoff)
    return {
        "route_id": route_id, "branch": branch["branch"], "method": branch["target"],
        "status": state["status"], "trajectory": str(path.relative_to(folder.parents[1])),
        "answer": state.get("verified_result", {}).get("answer"),
        "feasible_set": state.get("verified_result", {}).get("feasible_set"),
        "feasible_set_exact": deepcopy(state.get("feasible_set_exact")),
        "consistency": state.get("consistency"), "diagnostics": state.get("diagnostics", []),
    }
