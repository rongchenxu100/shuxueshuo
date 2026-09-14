"""Conservative, code-owned repair destinations for explicit producer reads.

These diagnostics authorize rewriting, never move a step or publish a result.
Implicit reads without an unambiguous producer are deliberately not guessed.
"""

from collections import defaultdict
from typing import Any

from .functional_diagnostics import validation_diagnostic_id
from .functional_plan_capabilities import FunctionalCapabilityCatalog
from .functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    _argument_accepts_return_type,
    _content_step_locations,
    _content_steps_and_scopes,
    _visible_scope_ids,
    _wire_return_object_resolution,
    functional_plan_content_from_plan,
)
from .scoped_functional_plan import ScopedFunctionalPlan


def shared_producer_placement_issues(
    plan: ScopedFunctionalPlan,
    *,
    frame: FunctionalPlanAuthorityFrame,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[dict[str, Any], ...]:
    """Find common-owner repairs only where the producer loses no local context.

    The proof uses the authority frame, not authored intent or suggested scope
    names. All local facts/entities are treated as potentially required. Any
    earlier local producer also prevents lifting: it might feed an implicit
    latest-state/context read. Unproven dependency relocation stays local.
    """
    content = functional_plan_content_from_plan(plan, frame=frame).to_payload()
    bodies, owners = _content_steps_and_scopes(content, frame=frame)
    locations = _content_step_locations(content, frame=frame)
    typed = {step.step_id: step for step in plan.steps}
    answers: dict[tuple[str, str], set[str]] = defaultdict(set)
    for goal, body in content["goal_plans"].items():
        answer = body["answer_from"]
        answers[(answer["step_id"], answer["return"])].add(frame.goal_answers[goal].target_ref)
    consumers: dict[str, set[str]] = defaultdict(set)
    invalid: set[str] = set()
    for consumer_id, consumer in typed.items():
        consumer_cap = catalog.get(consumer.capability_id)
        if consumer_cap is None:
            continue
        for arg in consumer_cap.args:
            for ref in consumer.args.get(arg.name, ()):
                producer_id, role = getattr(ref, "step_id", None), getattr(ref, "return_name", None)
                if producer_id not in locations or producer_id not in typed:
                    continue
                producer = typed[producer_id]
                cap = catalog.get(producer.capability_id)
                returned = next((item for item in cap.returns if item.name == role), None) if cap else None
                if returned is None or returned.binding_mode == "internal_only" or not _argument_accepts_return_type(arg, returned.runtime_type):
                    continue
                consumers[producer_id].add(consumer_id)
                before, after = locations[producer_id], locations[consumer_id]
                named = returned.reference_mode != "exact_result" and _wire_return_object_resolution(
                    producer_id, role, steps=bodies, step_scopes=owners,
                    frame=frame, capability_catalog=catalog, goal_answer_targets=answers,
                ).unique_target_ref is not None
                scope_visible = before.scope_id in _visible_scope_ids(after.scope_id, frame.scope_parents)
                goal_visible = before.goal_ref is None or before.goal_ref == after.goal_ref
                if (not named or arg.allows_anonymous_result) and (producer_id, role) in answers:
                    goal_visible = True
                if not (scope_visible and goal_visible):
                    invalid.add(producer_id)

    issues = []
    for producer_id in sorted(invalid):
        producer = locations[producer_id]
        consumer_ids = sorted(consumers[producer_id])
        scopes = {producer.scope_id, *(locations[item].scope_id for item in consumer_ids)}
        common = set.intersection(*(_visible_scope_ids(scope, frame.scope_parents) for scope in scopes))
        if not common:
            continue
        target = max(common, key=lambda scope: len(_visible_scope_ids(scope, frame.scope_parents)))
        removed_context = _visible_scope_ids(producer.scope_id, frame.scope_parents) - _visible_scope_ids(target, frame.scope_parents)
        if any(frame.source_facts.get(scope) or frame.source_ref_domain_types.get(scope) for scope in removed_context):
            continue
        visible_at_target = _visible_scope_ids(target, frame.scope_parents)
        source_refs = {
            ref for scope in visible_at_target
            for ref in frame.source_ref_domain_types.get(scope, {})
        } | {
            str(fact["ref"]) for scope in visible_at_target
            for fact in frame.source_facts.get(scope, ()) if "ref" in fact
        }
        named_inputs = {
            ref for values in typed[producer_id].args.values() for ref in values
            if isinstance(ref, str)
        }
        named_outputs = set(typed[producer_id].output_targets.values())
        if not (named_inputs | named_outputs) <= source_refs:
            continue
        # A previous Goal-local writer may be consumed implicitly even when no
        # StepResultRef names it. Do not promise its state survives relocation.
        if any(
            other.order < producer.order
            and (other.goal_ref == producer.goal_ref or other.goal_ref is None)
            and other.scope_id in _visible_scope_ids(producer.scope_id, frame.scope_parents)
            and (other.scope_id in removed_context or (
                other.goal_ref is not None and other.goal_ref == producer.goal_ref
            ))
            for other in locations.values()
        ):
            continue
        # Explicit dependencies must already be available as shared producers
        # at the proposed destination; relocation of a chain is not inferred.
        dependencies = [
            getattr(ref, "step_id", None)
            for values in typed[producer_id].args.values() for ref in values
            if getattr(ref, "step_id", None) is not None
        ]
        if any(
            dependency not in locations
            or locations[dependency].order >= producer.order
            or locations[dependency].goal_ref is not None
            or locations[dependency].scope_id not in _visible_scope_ids(target, frame.scope_parents)
            for dependency in dependencies
        ):
            continue
        def owner(item):
            return {
                "step_id": item.step_id, "scope_ref": item.scope_id,
                "goal_ref": item.goal_ref,
                "kind": "scope_steps" if item.goal_ref is None else "goal_steps",
            }
        issues.append({
            "code": "functional.shared_producer_scope_required",
            "stage": "placement", "retryability": "planner_repairable",
            "step_id": producer_id,
            "scope_ref": producer.scope_id,
            "consumer_step_ids": consumer_ids,
            "producer": owner(producer),
            "consumers": [owner(locations[item]) for item in consumer_ids],
            "allowed_actions": ["rewrite_authorized_scopes_and_relocate_shared_producer"],
            "reference_policy": "Do not change reference syntax to bypass ownership; do not lift local conditions.",
            "required_scope_refs": sorted(scopes | {target}),
            "expected": {"producer_scope_ref": target, "producer_owner": "scope_steps"},
            "message": "Rewrite the producer in the shared Scope and update its consumers and answer_from. Do not retain the old Goal-local copy. All opened Scopes are rewritten and re-executed.",
        })
    for issue in issues:
        issue["diagnostic_id"] = validation_diagnostic_id({"code": issue["code"], "path": issue["step_id"], "details": issue})
    return tuple(issues)
