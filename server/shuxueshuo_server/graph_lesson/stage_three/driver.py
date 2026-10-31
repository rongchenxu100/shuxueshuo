"""One deterministic, JSON-checkpointable graph operation per advance call."""

import traceback
from copy import deepcopy
from time import perf_counter

from . import capabilities, execution_contracts, judgments, method_admission
from .capabilities import CapabilityGap, LocalCheckFailed
from .premises import UnknownPremise
from .presentation import omit_unchanged_unit, record_seed, render_unit
from .revision_manifest import manifest_ref
from .trajectory import decode_value, encode_value, trace_value


def initial_bindings(method, features, context, *, contracts=None):
    contracts = execution_contracts.load_contracts() if contracts is None else contracts
    if method not in contracts:
        raise ValueError("execution.unknown_method:" + method)
    return method_admission.initial_bindings(contracts[method], features, context)


def can_execute(method, features, context, *, contracts=None, values=None):
    contracts = execution_contracts.load_contracts() if contracts is None else contracts
    if method not in contracts:
        raise ValueError("execution.unknown_method:" + method)
    try:
        if values is None:
            values = initial_bindings(method, features, context, contracts=contracts)
        return method_admission.can_execute(contracts[method], values)
    except (CapabilityGap, UnknownPremise):
        return False


def empty_state(
    *,
    features,
    context,
    method,
    route_id,
    branch,
    target_ref,
    run_id,
    lesson_version,
    revisions=None,
    solve_budget_seconds=10,
):
    state = {
        "run_id": run_id,
        "lesson_version": lesson_version,
        "target_ref": target_ref,
        "method": method,
        "route_id": route_id,
        "branch": branch,
        "revisions_ref": manifest_ref(revisions or execution_contracts.revisions()),
        "status": "running",
        "frames": [],
        "fragments": [],
        "result": None,
        "diagnostics": [],
        "compute_seconds": 0.0,
        "solve_budget_seconds": solve_budget_seconds,
        "next_call_seq": 1,
        "trajectory": {
            "contract": "graph-stage-three-route/v2",
            "run_id": run_id,
            "lesson_version": lesson_version,
            "target_ref": target_ref,
            "route_id": route_id,
            "branch": branch,
            "method": method,
            "status": "capability_gap",
            "steps": [],
            "math_steps": [],
            "constraint_context": deepcopy(context),
            "finalization": [],
            "result": None,
            "diagnostics": [],
        },
    }
    state["trajectory"]["revisions_ref"] = state["revisions_ref"]
    return state


def create_state(*, contracts=None, **arguments):
    """Prepare all mathematical bindings inside the calculation worker."""
    state = empty_state(**arguments)
    method, features, context = (
        arguments[key] for key in ("method", "features", "context")
    )
    contracts = execution_contracts.load_contracts() if contracts is None else contracts
    try:
        values = initial_bindings(method, features, context, contracts=contracts)
        if not can_execute(method, features, context, contracts=contracts, values=values):
            raise CapabilityGap("method_input_class_unavailable")
        state["frames"] = [_frame(method, values, None)]
        state["input_values"] = encode_value(values)
    except (CapabilityGap, UnknownPremise) as exc:
        _fail(state, "capability_gap", exc)
    return state


def _frame(method, bindings, parent_call):
    return {
        "method": method,
        "step_index": 0,
        "call_index": 0,
        "bindings": encode_value(bindings),
        "binding_sources": {},
        "case_source_refs": [],
        "parent_call": parent_call,
        "case_path": [],
        "step_trace": None,
        "pending_child": None,
    }


def _resolve(value, bindings):
    if isinstance(value, str) and value.startswith("$"):
        pieces = value[1:].split(".")
        output = bindings[pieces[0]]
        for part in pieces[1:]:
            output = output[part]
        return output
    if isinstance(value, dict):
        return {key: _resolve(v, bindings) for key, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, bindings) for v in value]
    return value


def _guard(guard, bindings):
    if not guard:
        return True
    if "constant" in guard:
        return guard["constant"]
    if "all" in guard:
        # A conjunction is independent of declaration order. A branch-local
        # binding may be absent outside its case, but a known false condition
        # still proves that the action is skipped. Preserve missing-binding
        # errors when no condition can prove that the action is inapplicable.
        missing = None
        for item in guard["all"]:
            try:
                if not _guard(item, bindings):
                    return False
            except KeyError as exc:
                if missing is None:
                    missing = exc
        if missing is not None:
            raise missing
        return True
    return _resolve("$" + guard["ref"], bindings) == guard["equals"]


def _fail(state, status, exc):
    state["status"] = status
    state["trajectory"]["status"] = status
    frame = state["frames"][-1] if state["frames"] else {}
    evidence = {
        "code": str(exc),
        "exception_type": type(exc).__name__,
        "method": frame.get("method"),
        "step_index": frame.get("step_index"),
        "call_index": frame.get("call_index"),
    }
    if status == "execution_error":
        evidence["traceback"] = traceback.format_exc()
    state["trajectory"]["gap" if status == "capability_gap" else "error"] = evidence
    state["trajectory"]["diagnostics"].append(evidence)
    state["diagnostics"].append(evidence)


def _binding_sources(frame, names):
    return {frame["binding_sources"][name] for name in names if name in frame["binding_sources"]}


def _operation_sources(frame, step, action):
    names = (set(execution_contracts.references(action.get("inputs", {})))
             | execution_contracts.guard_references(action.get("guard"))
             | execution_contracts.guard_references(step.get("guard")))
    return _binding_sources(frame, names) | set(frame.get("case_source_refs", []))


def _dependency_premises(state, sources):
    """Follow explicit producers, never the chronological history of judgments."""
    found, visited = set(), set()

    def visit(reference):
        if reference in visited:
            return
        visited.add(reference)
        value = state["trajectory"]
        try:
            for part in reference.lstrip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
        except (KeyError, IndexError, ValueError, TypeError):
            raise ValueError("execution.missing_dependency_source:" + reference) from None
        if "/judgments/" in reference:
            found.add(reference)
        records = value if isinstance(value, list) else [value]
        for record in records:
            if not isinstance(record, dict):
                continue
            for key in ("source_refs", "evidence_refs", "output_source_refs"):
                for dependency in record.get(key, []):
                    visit(dependency)

    for source in sources:
        visit(source)
    return sorted(found)


def _display_sources(state, frame, *, start=0, scope=None, exclude=()):
    source_steps = set(scope.get("steps", [scope.get("step")])) if scope else None
    sources, basis = [], []
    for trace_index, trace in enumerate(state["trajectory"]["steps"][start:], start):
        if trace["case_path"] != frame["case_path"]:
            continue
        if scope and (trace["method"] != frame["method"] or trace["step"] not in source_steps):
            continue
        for category in ("calls", "skipped_calls", "judgments", "merges"):
            for item_index, item in enumerate(trace[category]):
                reference = f"/steps/{trace_index}/{category}/{item_index}"
                if reference in exclude:
                    continue
                if scope and scope.get("actions") and item.get("action_id", item.get("id")) not in scope["actions"]:
                    continue
                sources.append(reference)
                basis.extend(item.get("used_basis", []))
    return sources, basis


def _publish(state, frame, step, action, bindings):
    if frame.get('fold_display'):
        return
    if frame['method'] == 'method-domain-intersection' and bindings.get('context', {}).get('suppress_domain_display'):
        return
    action_trace = None
    for unit in step["display_units"]:
        if unit["after"] != action["id"] or not _guard(unit.get("guard"), bindings):
            continue
        execution_contracts.validate_dependencies(
            unit["depends_on"],
            execution_contracts.references(unit["bindings"]),
            set(bindings),
        )
        display_bindings = _resolve(unit["bindings"], bindings)
        if omit_unchanged_unit(unit, display_bindings):
            # The computation remains auditable. Carry its calls to the next
            # visible card in this frame instead of inventing an identity quiz.
            frame.setdefault("pending_display_trace", frame["step_trace"])
            sources, basis = _display_sources(
                state, frame, start=0 if unit.get("source_scope") else frame["step_trace"],
                scope=unit.get("source_scope"), exclude=set(frame.get("published_sources", [])),
            )
            # Freeze exact pointers now: a later scoped display must not lose
            # them or absorb unrelated calls appended after this boundary.
            pending = frame.setdefault("pending_display_evidence", {"sources": [], "basis": []})
            pending["sources"] = list(dict.fromkeys([*pending["sources"], *sources]))
            pending["basis"] = sorted(set(pending["basis"]) | set(basis))
            continue
        index = frame.pop("pending_display_trace", frame["step_trace"])
        pending = frame.pop("pending_display_evidence", None)
        # Exact call pointers freeze the source boundary even when later calls
        # append to the same method step (opening and discriminant, for example).
        scope = unit.get("source_scope")
        if scope:
            sources, basis = _display_sources(state, frame, scope=scope)
            if not sources:
                raise ValueError("execution.display_source_unavailable")
        elif action_trace is None:
            sources, basis = _display_sources(
                state, frame, start=index, exclude=set(frame.get("published_sources", [])),
            )
            action_trace = sources, basis
        # A single certified operation may expose several branch cards. Each
        # card retains that operation's evidence; the first must not drain it.
        if not scope:
            sources, basis = action_trace
        if pending:
            sources = list(dict.fromkeys([*pending["sources"], *sources]))
            basis = [*pending["basis"], *basis]
            if not scope:
                action_trace = sources, basis
        frame["published_sources"] = sorted(set(frame.get("published_sources", [])) | set(sources))
        dependencies = _binding_sources(
            frame, set(execution_contracts.references(unit["bindings"]))
            | execution_contracts.guard_references(unit.get("guard")),
        ) | _operation_sources(frame, step, action)
        premise_refs = _dependency_premises(state, dependencies)
        fragment, seed_values = render_unit(
            state, frame, step, unit, display_bindings, sources, basis, premise_refs
        )
        state["fragments"].append(fragment)
        record_seed(
            state, fragment, template=unit["template"], values=seed_values, frame_bindings=bindings
        )
        state["trajectory"]["math_steps"].append(
            {
                "step_id": fragment["step_id"],
                "math_step_sha256": fragment["math_step_sha256"],
                "source_refs": sources,
                "file": f"math-steps/{state['route_id']}/{fragment['step_id']}.json",
            }
        )


def _case_frame(parent, descriptor, specification, step_index, end_index):
    bindings = decode_value(parent["bindings"])
    bindings[specification["binding"]] = descriptor
    child = _frame(parent["method"], bindings, None)
    child.update(
        step_index=step_index,
        case_start=step_index,
        case_end=end_index,
        case_specification=deepcopy(specification),
        descriptor=encode_value(descriptor),
        fold_display=parent.get('fold_display', False),
        binding_sources=deepcopy(parent["binding_sources"]),
        case_source_refs=sorted(set(parent.get("case_source_refs", []))
                                | _binding_sources(parent, {specification["source"]})),
        case_path=parent["case_path"]
        + ([descriptor["id"]] if parent["pending_cases"]["branched"] else []),
    )
    child["binding_sources"][specification["binding"]] = parent["binding_sources"][
        specification["source"]
    ]
    if parent.get('option_context'):
        child['option_context'] = deepcopy(parent['option_context'])
    return child


def _finish_case(state, frame, bindings, contracts):
    specification = frame["case_specification"]
    outputs = _resolve(specification["outputs"], bindings)
    descriptor = decode_value(frame["descriptor"])
    refs = sorted(
        {
            frame["binding_sources"][name]
            for name in execution_contracts.references(specification["outputs"])
        }
    )
    state["frames"].pop()
    parent = state["frames"][-1]
    pending = parent["pending_cases"]
    pending["results"].append(
        encode_value(
            {
                "case_id": descriptor["id"],
                "case_path": frame["case_path"],
                "condition": descriptor["condition"],
                "domain": descriptor["domain"],
                "outputs": outputs,
                "source_refs": refs,
            }
        )
    )
    pending["index"] += 1
    if pending["index"] < len(pending["descriptors"]):
        descriptor = decode_value(pending["descriptors"][pending["index"]])
        state["frames"].append(
            _case_frame(
                parent, descriptor, specification, pending["start"], pending["end"]
            )
        )
        return
    values = decode_value(parent["bindings"])
    values[specification["collect"]] = [
        decode_value(item) for item in pending["results"]
    ]
    parent["bindings"] = encode_value(values)
    # The collection itself is an explicit trace record; consumers also retain
    # each case's exact source pointers and never read the child binding table.
    trace = state["trajectory"]["steps"][parent["step_trace"]]
    trace["case_results"] = trace_value(values[specification["collect"]])
    parent["binding_sources"][specification["collect"]] = (
        f"/steps/{parent['step_trace']}/case_results"
    )
    parent.update(
        step_index=pending["end"] + 1, call_index=0, step_trace=None, pending_cases=None
    )


def _option_frame(parent, descriptor, specification, step_index, end_index):
    bindings = decode_value(parent['bindings'])
    bindings[specification['binding']] = descriptor
    child = _frame(parent['method'], bindings, None)
    child.update(step_index=step_index, option_start=step_index, option_end=end_index,
                 option_specification=deepcopy(specification), descriptor=encode_value(descriptor),
                 binding_sources=deepcopy(parent['binding_sources']),
                 case_path=deepcopy(parent['case_path']),
                 case_source_refs=sorted(_binding_sources(parent, {specification['source']})))
    child['binding_sources'][specification['binding']] = parent['binding_sources'][specification['source']]
    child['option_context'] = {
        'option_id': descriptor['option_id'], 'label': descriptor['label'],
        'target_ref': bindings['comparison_goal']['target_ref'],
        'left_ref': descriptor['left']['function_ref'], 'right_ref': descriptor['right']['function_ref'],
        'phase': 'evidence',
    }
    return child


def _finish_option(state, frame, bindings):
    specification = frame['option_specification']
    descriptor = decode_value(frame['descriptor'])
    outputs = _resolve(specification['outputs'], bindings)
    refs = sorted(_binding_sources(frame, execution_contracts.references(specification['outputs'])))
    state['frames'].pop()
    parent = state['frames'][-1]
    pending = parent['pending_options']
    pending['results'].append(encode_value({'option_id': descriptor['option_id'],
                                            'outputs': outputs, 'source_refs': refs}))
    pending['index'] += 1
    if pending['index'] < len(pending['descriptors']):
        descriptor = decode_value(pending['descriptors'][pending['index']])
        state['frames'].append(_option_frame(parent, descriptor, specification, pending['start'], pending['end']))
        return
    values = decode_value(parent['bindings'])
    values[specification['collect']] = [decode_value(item) for item in pending['results']]
    parent['bindings'] = encode_value(values)
    trace = state['trajectory']['steps'][parent['step_trace']]
    trace['option_results'] = trace_value(values[specification['collect']])
    parent['binding_sources'][specification['collect']] = f"/steps/{parent['step_trace']}/option_results"
    parent.update(step_index=pending['end'] + 1, call_index=0, step_trace=None, pending_options=None)


def _advance(state, contracts):
    frame = state["frames"][-1]
    contract = contracts[frame["method"]]
    bindings = decode_value(frame["bindings"])
    if 'option_end' in frame and frame['step_index'] > frame['option_end']:
        _finish_option(state, frame, bindings)
        return
    if "case_end" in frame and frame["step_index"] > frame["case_end"]:
        _finish_case(state, frame, bindings, contracts)
        return
    if frame["step_index"] >= len(contract["steps"]):
        outputs = _resolve(contract["outputs"], bindings)
        output_sources = _binding_sources(frame, execution_contracts.references(contract["outputs"]))
        state["frames"].pop()
        if not state["frames"]:
            state["result"] = encode_value(outputs)
            state["status"] = "method_complete"
            return
        parent = state["frames"][-1]
        pending = parent["pending_child"]
        target_bindings = decode_value(parent["bindings"])
        for dest, source in pending["action"]["outputs"].items():
            target_bindings[dest] = outputs[source]
            parent["binding_sources"][dest] = (
                f"/steps/{parent['step_trace']}/calls/{pending['call_index']}"
            )
        parent["bindings"] = encode_value(target_bindings)
        call = state["trajectory"]["steps"][parent["step_trace"]]["calls"][
            pending["call_index"]
        ]
        call["outputs"] = trace_value(outputs)
        call["output_source_refs"] = sorted(output_sources)
        call["postconditions"] = [{"kind": "child_completed", "passed": True}]
        parent["pending_child"] = None
        step = contracts[parent["method"]]["steps"][parent["step_index"]]
        _publish(state, parent, step, pending["action"], target_bindings)
        parent["call_index"] += 1
        return
    step = contract["steps"][frame["step_index"]]
    if frame.get("case_start") == frame["step_index"]:
        step = dict(step["cases"]["entry"], id=step["id"])
    if frame.get('option_start') == frame['step_index']:
        step = dict(step['options']['entry'], id=step['id'])
    if frame["step_trace"] is None:
        frame["step_trace"] = len(state["trajectory"]["steps"])
        state["trajectory"]["steps"].append(
            {
                "seq": frame["step_trace"] + 1,
                "method": frame["method"],
                "step": step["id"],
                "depth": len(state["frames"]) - 1,
                "parent_call": frame["parent_call"],
                "case_path": deepcopy(frame["case_path"]),
                "calls": [],
                "skipped_calls": [],
                "judgments": [],
                "merges": [],
            }
        )
        if frame.get('option_context'):
            state['trajectory']['steps'][-1]['option_context'] = deepcopy(frame['option_context'])
    if not _guard(step.get("guard"), bindings):
        guard_refs = execution_contracts.guard_references(step.get("guard"))
        trace = state["trajectory"]["steps"][frame["step_trace"]]
        trace["step_skip"] = {
            "reason": "guard_false",
            "guard": deepcopy(step["guard"]),
            "guard_bindings": trace_value(
                {ref: bindings[ref] for ref in guard_refs if ref in bindings}
            ),
            "source_refs": sorted(
                {
                    frame["binding_sources"][ref]
                    for ref in guard_refs
                    if ref in frame["binding_sources"]
                }
            ),
            "case_path": deepcopy(frame["case_path"]),
        }
        # Skipping is one atomic checkpoint transition, with no fabricated call
        # or display unit. Resuming this checkpoint starts at the following step.
        frame.update(step_index=frame["step_index"] + 1, call_index=0, step_trace=None)
        return
    actions = execution_contracts.actions(step)
    if frame["call_index"] >= len(actions):
        if step.get('options'):
            specification = step['options']
            descriptors = bindings[specification['source']]
            if not descriptors or len({item['option_id'] for item in descriptors}) != len(descriptors):
                raise ValueError('execution.invalid_option_manifest')
            end = next(i for i, item in enumerate(contract['steps']) if item['id'] == specification['through'])
            frame['pending_options'] = {'descriptors': encode_value(descriptors), 'index': 0,
                                        'results': [], 'start': frame['step_index'], 'end': end}
            state['frames'].append(_option_frame(frame, descriptors[0], specification, frame['step_index'], end))
            return True
        if step.get("cases"):
            specification = step["cases"]
            descriptors = bindings[specification["source"]]
            if not descriptors or len({item["id"] for item in descriptors}) != len(
                descriptors
            ):
                raise ValueError("execution.invalid_case_manifest")
            end = next(
                i
                for i, item in enumerate(contract["steps"])
                if item["id"] == specification["through"]
            )
            frame["pending_cases"] = {
                "descriptors": encode_value(descriptors),
                "index": 0,
                "results": [],
                "start": frame["step_index"],
                "end": end,
                "branched": len(descriptors) > 1,
            }
            state["frames"].append(
                _case_frame(
                    frame, descriptors[0], specification, frame["step_index"], end
                )
            )
            # Entering a previously computed case only moves the cursor. Keep
            # it with the next real action instead of transferring a complete
            # checkpoint for an otherwise empty transition.
            return True
        frame["step_index"] += 1
        frame["call_index"] = 0
        frame["step_trace"] = None
        # No calculation or card was produced. Actual calls, judgments and
        # cards still stop advance immediately and retain their commit boundary.
        return True
    action = actions[frame["call_index"]]
    trace = state["trajectory"]["steps"][frame["step_trace"]]
    if not _guard(action.get("guard"), bindings):
        guard_refs = execution_contracts.guard_references(action.get("guard"))
        sources = sorted(
            {
                frame["binding_sources"][ref]
                for ref in guard_refs
                if ref in frame["binding_sources"]
            }
        )
        trace["skipped_calls"].append(
            {
                "public_ref": action.get("public_ref"),
                "reason": action.get("skip_reason", "guard_false"),
                "guard": deepcopy(action.get("guard")),
                "guard_bindings": trace_value(
                    {ref: bindings[ref] for ref in guard_refs if ref in bindings}
                ),
                "evidence_refs": sources,
                "case_path": deepcopy(frame["case_path"]),
                "action_id": action["id"],
            }
        )
        if action.get("rule_ref"):
            trace["skipped_calls"][-1].update(rule_ref=action["rule_ref"], branch=action.get("branch"))
        fragment_count = len(state["fragments"])
        if not action.get("outputs"):
            _publish(state, frame, step, action, bindings)
        frame["call_index"] += 1
        # An unselected call with no visible output needs a trace entry, but
        # not its own round trip of the entire growing checkpoint. A skipped
        # call that publishes a card still ends this atomic transition.
        return len(state["fragments"]) == fragment_count
    if action["kind"] == "merge":
        selected = [
            branch for branch in action["branches"] if _guard(branch["guard"], bindings)
        ]
        if len(selected) != 1:
            raise CapabilityGap("execution.merge_choice_incomplete")
        branch = selected[0]
        outputs = _resolve(branch["bindings"], bindings)
        refs = sorted(_binding_sources(frame, set(execution_contracts.references(branch["bindings"]))
                                       | execution_contracts.guard_references(branch["guard"]))
                      | _operation_sources(frame, step, action))
        trace["merges"].append(
            {
                "id": action["id"],
                "guard": deepcopy(branch["guard"]),
                "source_refs": refs,
                "outputs": trace_value(outputs),
                "case_path": deepcopy(frame["case_path"]),
            }
        )
        source = f"/steps/{frame['step_trace']}/merges/{len(trace['merges']) - 1}"
        bindings.update(outputs)
        frame["binding_sources"].update({name: source for name in outputs})
        frame["bindings"] = encode_value(bindings)
        _publish(state, frame, step, action, bindings)
        frame["call_index"] += 1
        return
    inputs = _resolve(action["inputs"], bindings)
    if action["kind"] == "judgment":
        execution_contracts.validate_dependencies(
            action["depends_on"],
            set(execution_contracts.references(action["inputs"]))
            | execution_contracts.guard_references(action.get("guard")),
            set(bindings),
        )
        if action.get("decided_by", "program") != "program":
            raise CapabilityGap("llm_judgment_unavailable")
        output = judgments.REGISTRY[action["function"]](**inputs)
        if output["selected"] not in {option["id"] for option in action["options"]}:
            raise ValueError("judgment.invalid_choice")
        trace["judgments"].append(
            {
                "id": action["id"],
                "inputs": trace_value(inputs),
                "options": action["options"],
                "selected": output["selected"],
                "decided_by": "program",
                "evidence": trace_value(output),
                "source_refs": sorted(_operation_sources(frame, step, action)),
                "case_path": deepcopy(frame["case_path"]),
            }
        )
        if action.get("rule_ref"):
            trace["judgments"][-1]["rule_ref"] = action["rule_ref"]
        binding_source = f"/steps/{frame['step_trace']}/judgments/{len(trace['judgments']) - 1}"
    else:
        seq = state["next_call_seq"]
        state["next_call_seq"] += 1
        call = {
            "action_id": action["id"],
            "seq": seq,
            "capability": action["capability"],
            "public_ref": action["public_ref"],
            "inputs": trace_value(inputs),
            "outputs": {},
            "operations": [],
            "used_basis": [],
            "postconditions": [],
            "case_path": deepcopy(frame["case_path"]),
            "source_refs": sorted(_operation_sources(frame, step, action)),
        }
        if action.get("rule_ref"):
            call.update(rule_ref=action["rule_ref"], branch=action["branch"])
        if action["capability"] == "submethod":
            trace["calls"].append(call)
            frame["pending_child"] = {
                "action": deepcopy(action),
                "call_index": len(trace["calls"]) - 1,
            }
            child = _frame(action["public_ref"], inputs, seq)
            child['fold_display'] = frame.get('fold_display', False) or action.get('presentation') == 'fold'
            child["case_path"] = deepcopy(frame["case_path"])
            child["case_source_refs"] = deepcopy(frame.get("case_source_refs", []))
            if frame.get('option_context'):
                child['option_context'] = deepcopy(frame['option_context'])
            for name, value in action["inputs"].items():
                input_sources = _binding_sources(frame, execution_contracts.references(value))
                if input_sources:
                    call.setdefault("input_sources", {})[name] = {"source_refs": sorted(input_sources)}
                    child["binding_sources"][name] = (
                        f"/steps/{frame['step_trace']}/calls/{len(trace['calls']) - 1}/input_sources/{name}"
                    )
            state["frames"].append(child)
            return
        trace["calls"].append(call)
        try:
            computed = capabilities.execute(action["capability"], inputs)
        except LocalCheckFailed as exc:
            if exc.evidence is not None:
                call.update(
                    outputs=trace_value(exc.evidence["outputs"]),
                    operations=exc.evidence["operations"],
                    postconditions=trace_value(exc.evidence["checks"]),
                )
            else:
                call["postconditions"] = [
                    {
                        "kind": "local_check_exception",
                        "passed": False,
                        "reason": str(exc),
                    }
                ]
            raise
        except (
            Exception
        ) as exc:  # Record the attempted input, then propagate route failure.
            call["error"] = {"exception_type": type(exc).__name__, "message": str(exc)}
            raise
        output = computed["outputs"]
        basis = execution_contracts.read("basis-operations")["operations"]
        call.update(
            outputs=trace_value(output),
            operations=computed["operations"],
            used_basis=sorted(
                {ref for op in computed["operations"] for ref in basis[op]}
            ),
            postconditions=trace_value(computed["checks"]),
        )
        if not computed["checks"]:
            call["postconditions"] = [
                {"kind": "missing_local_evidence", "passed": False}
            ]
            raise LocalCheckFailed("capability.missing_local_evidence")
        if any(c.get("passed") is not True for c in computed["checks"]):
            raise LocalCheckFailed("capability.postcondition_failed")
        binding_source = f"/steps/{frame['step_trace']}/calls/{len(trace['calls']) - 1}"
    for destination, source in action.get("outputs", {}).items():
        bindings[destination] = output[source]
        frame["binding_sources"][destination] = binding_source
    frame["bindings"] = encode_value(bindings)
    _publish(state, frame, step, action, bindings)
    frame["call_index"] += 1


def advance(state, *, contracts=None):
    """Return a new checkpoint. Caller atomically commits it with fragment deltas."""
    if state["status"] != "running":
        return deepcopy(state)
    updated = deepcopy(state)
    started = perf_counter()
    try:
        # Direct callers validate afresh; the isolated session supplies its
        # already validated configuration pinned to these route revisions.
        contracts = execution_contracts.load_contracts() if contracts is None else contracts
        started = perf_counter()
        if updated["compute_seconds"] >= updated["solve_budget_seconds"]:
            raise TimeoutError("solve_budget_exhausted")
        while _advance(updated, contracts) is True:
            if updated["compute_seconds"] + perf_counter() - started > updated["solve_budget_seconds"]:
                updated = deepcopy(state)
                raise TimeoutError("solve_budget_exhausted")
        elapsed = perf_counter() - started
        if updated["compute_seconds"] + elapsed > updated["solve_budget_seconds"]:
            # The uncommitted operation (including fragments) is discarded on timeout.
            updated = deepcopy(state)
            raise TimeoutError("solve_budget_exhausted")
    except (CapabilityGap, UnknownPremise) as exc:
        _fail(updated, "capability_gap", exc)
    except LocalCheckFailed as exc:
        _fail(updated, "math_failed", exc)
    except Exception as exc:  # noqa: BLE001 -- explicit route failure with diagnostic, never unknown.
        _fail(updated, "execution_error", exc)
    updated["compute_seconds"] += perf_counter() - started
    return updated


def export_values(state):
    values = decode_value(state.get("input_values", {}))
    values.update(decode_value(state.get("result") or {}))
    if "candidate_set" in values:
        values["feasible_set"] = values["candidate_set"]
    return values


def append_endpoint(state, feasible_set, evidence):
    from .presentation import append_boundary

    return append_boundary(state, evidence, feasible_set=feasible_set)
