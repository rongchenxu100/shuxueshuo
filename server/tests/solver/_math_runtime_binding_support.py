"""Frozen-input replay support; never imported by the production adapter."""

import json
from copy import deepcopy
from pathlib import Path

from shuxueshuo_server.problem_understanding.runtime_binding import (
    AdmissionEvidence,
    authorize_binding,
    bind_notation,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner

ROOT = Path(__file__).resolve().parents[3]
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
)


def candidate(case, authored=False):
    origin = "authored" if authored else "recorded"
    path = (
        ROOT
        / "server/tests/solver/fixtures/math-runtime-binding-stage-two"
        / f"{case}.{origin}.json"
    )
    return json.loads(path.read_text())


def binding(case, authored=False, payload=None):
    return bind_notation(
        payload or candidate(case, authored),
        problem_id=case,
        candidate_id="offline-fixture",
        source_version_id="frozen-source",
        source_hash="test-source-hash",
    )


def reviewed_authority(bound):
    # Synthetic admission evidence tests the gate; this is NOT a promotion of
    # a historical recorded review to the current product configuration.
    evidence = AdmissionEvidence(
        **{k: v for k, v in bound.source_identity.items() if k != "problem_id"},
        review_run_id="synthetic-current-review",
        review_current=True,
    )
    return authorize_binding(bound, evidence)


def trusted_plan(case, bound):
    payload = json.loads(
        (
            ROOT
            / "internal/functional-plan-v2-fixtures"
            / f"{case}.functional-plan.json"
        ).read_text()
    )
    # A historical shared optimization step used a parent-level target.
    # Mathematical notation keeps that target in each actual question. Replay
    # the same method in each child instead of promoting a local source fact.
    available = {
        (a.owner_scope_id, a.semantic_ref.ref)
        for a in bound.planning_context.ref_authorities.values()
    }

    def localize(scope):
        for step in list(scope.get("steps", [])):
            target = step.get("args", {}).get("path_minimum_target")
            if not isinstance(target, str) or (scope["scope_ref"], target) in available:
                continue
            children = scope.get("children", [])
            if not children or not all(
                (c["scope_ref"], mapping.get((c["scope_ref"], target), target))
                in available
                for c in children
            ):
                continue
            scope["steps"].remove(step)
            for child in children:
                clone = deepcopy(step)
                clone["step_id"] = step["step_id"] + "__" + child["scope_ref"]
                clone["args"]["path_minimum_target"] = mapping.get(
                    (child["scope_ref"], target), target
                )

                def rewrite(value, old_id=step["step_id"], new_id=clone["step_id"]):
                    if isinstance(value, dict):
                        return {
                            k: new_id if k == "step_id" and v == old_id else rewrite(v)
                            for k, v in value.items()
                        }
                    if isinstance(value, list):
                        return [rewrite(v) for v in value]
                    return value

                rewritten = rewrite(child)
                child.clear()
                child.update(rewritten)
                child.setdefault("steps", []).insert(0, clone)
        for child in scope.get("children", []):
            localize(child)

    # Rebind source references by their scope, source pointers and typed role.
    # Only identities are taken from the baseline; never runtime input values.
    baseline = binding(case)

    def signature(authority, bundle):
        return (
            authority.owner_scope_id,
            authority.semantic_ref.kind,
            authority.semantic_ref.value_type,
            tuple(
                sorted(
                    (bundle.provenance[u]["path"], bundle.provenance[u]["rule"])
                    for u in authority.source_unit_ids
                )
            ),
        )

    mapping = {}
    for old in baseline.planning_context.ref_authorities.values():
        if any(
            (new.owner_scope_id, new.semantic_ref.ref, new.semantic_ref.kind)
            == (old.owner_scope_id, old.semantic_ref.ref, old.semantic_ref.kind)
            for new in bound.planning_context.ref_authorities.values()
        ):
            mapping[(old.owner_scope_id, old.semantic_ref.ref)] = old.semantic_ref.ref
            continue
        matches = [
            new
            for new in bound.planning_context.ref_authorities.values()
            if signature(old, baseline.bundle) == signature(new, bound.bundle)
        ]
        exact = [m for m in matches if m.semantic_ref.ref == old.semantic_ref.ref]
        if exact:
            matches = exact
        if len(matches) == 1:
            mapping[(old.owner_scope_id, old.semantic_ref.ref)] = matches[
                0
            ].semantic_ref.ref

    def rebind(scope, ancestors=()):
        visible = (scope["scope_ref"], *ancestors)

        def rewrite(value):
            if isinstance(value, str):
                return next(
                    (mapping[(s, value)] for s in visible if (s, value) in mapping),
                    value,
                )
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if isinstance(value, dict):
                return {
                    k: rewrite(v) if k not in ("step_id", "method", "return") else v
                    for k, v in value.items()
                }
            return value

        for key in ("steps", "goals"):
            if key in scope:
                scope[key] = rewrite(scope[key])
        for child in scope.get("children", []):
            rebind(child, visible)

    localize(payload["root_scope"])
    rebind(payload["root_scope"])
    return payload


def replay(case, bound, tmp_path):
    folder = tmp_path / case
    folder.mkdir(parents=True, exist_ok=True)
    payload = trusted_plan(case, bound)
    (folder / f"{bound.bundle.problem_id}.functional-plan.json").write_text(
        json.dumps(payload, ensure_ascii=False)
    )
    planner = StrategyPlanner(
        ContextBuilder().build(bound.bundle.build_solver_problem()),
        problem_authority=reviewed_authority(bound),
        scoped_functional_plan_fixture_dir=folder,
    )
    return planner.run_scoped(bound.inputs, max_attempts=1)


def replay_errors(result):
    output = []
    for attempt in result.attempts:
        if attempt.error:
            output.append(str(attempt.error))
        if not attempt.execution or not attempt.execution.checkpoint:
            continue

        def visit(scope):
            for step in (
                *scope.scope_steps,
                *(s for g in scope.goals for s in g.steps),
            ):
                if step.typed_issue:
                    output.append((step.step_id, dict(step.typed_issue)))
            for child in scope.children:
                visit(child)

        output.extend(result.attempts[-1].execution.checkpoint.root_issues)
        visit(attempt.execution.checkpoint.root_scope)
    return output


def answers(bound, result):
    from shuxueshuo_server.solver.runtime.orchestrator import (
        _verified_goal_runtime_results,
    )
    from shuxueshuo_server.solver.runtime.result_builder import ResultBuilder

    report = result.final_execution.replay.transactional_attempt_result.execution_report
    return ResultBuilder().build_from_verified_goal_results(
        report.runtime_context,
        bound.inputs.question_goals,
        _verified_goal_runtime_results(result, report),
    )


def assert_expected(case, bound, result):
    from _functional_opt_in_support import assert_answers_semantically_equal

    expected = json.loads(
        (ROOT / "server/tests/solver/expected" / f"{case}.expected.json").read_text()
    )
    expected = expected.get("expected", expected)
    assert_answers_semantically_equal(answers(bound, result), expected)


def execution_audit(bound, result):
    """Actual Method inputs, committed versions and source authorities together."""
    from shuxueshuo_server.solver.extraction.source_identity import thaw_json

    report = result.final_execution.replay.transactional_attempt_result.execution_report
    assert report.ok, report.compatibility_mismatches
    payload = report.to_payload()
    for version in report.committed_versions:
        visible = set(bound.handle_registry.ancestor_scopes(version.valid_scope_id))
        for source in version.source_version_ids:
            assert source.slot_id.storage_scope_id in visible, (version, source)
    steps = []

    def visit(scope):
        for step in (
            *scope.scope_steps,
            *(s for goal in scope.goals for s in goal.steps),
        ):
            if step.status != "runtime_verified":
                continue
            steps.append(
                {
                    "step_id": step.step_id,
                    "scope_id": scope.scope_ref,
                    "authored_step": thaw_json(step.authored_step),
                    "resolved_inputs": thaw_json(step.resolved_inputs),
                    "actual_outputs": thaw_json(step.actual_outputs),
                }
            )
        for child in scope.children:
            visit(child)

    visit(result.verified_execution.root_scope)
    return {
        "source_identity": thaw_json(bound.source_identity),
        "steps": steps,
        "committed_versions": payload["committed_versions"],
        "input_bindings": payload["functional_problem_binding_ledger"],
        "goal_verification": payload["goal_verification"],
        "answers": answers(bound, result),
    }
