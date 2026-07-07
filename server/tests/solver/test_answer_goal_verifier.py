from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver import load_problem_ir
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.answer_goal_verifier import AnswerGoalVerifier
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    ProducedFact,
    StepIntent,
    StepIntentAcceptedStep,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
    StepIntentScope,
)
from shuxueshuo_server.solver.runtime.strategy_retry_state import (
    build_planner_retry_state,
)
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator


REPO_ROOT = Path(__file__).resolve().parents[3]
NANKAI_FIXTURE = REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_RECORDED = (
    REPO_ROOT
    / "internal/solver-fixtures/tj-2026-nankai-yimo-25.executable-step-intents.json"
)


def test_goal_verifier_flags_path_minimum_answer_without_witness_chain() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="第（Ⅱ）①问",
                steps=(
                    StepIntent(
                        scope_id="ii_1",
                        step_id="straighten_path",
                        recipe_hint="broken_path_straightening_and_select",
                        goal_type="straighten_broken_path",
                        target="fact:ii:straightened_candidate",
                        strategy="选择拉直方案。",
                        reads=("fact:ii:path_minimum_target",),
                        produces=(
                            ProducedFact(
                                handle="fact:ii:straightened_candidate",
                                valid_scope="ii",
                                output_type="StraighteningCandidate",
                            ),
                        ),
                    ),
                    StepIntent(
                        scope_id="ii_1",
                        step_id="compute_path_expression",
                        recipe_hint="path_minimum_by_straightened_distance",
                        goal_type="derive_minimum_value",
                        target="fact:ii:path_minimum_expression",
                        strategy="计算路径最小值表达式。",
                        reads=("fact:ii:straightened_candidate",),
                        produces=(
                            ProducedFact(
                                handle="fact:ii:path_minimum_expression",
                                valid_scope="ii",
                                output_type="MinimumExpression",
                            ),
                        ),
                    ),
                    StepIntent(
                        scope_id="ii_1",
                        step_id="evaluate_minimum_i1",
                        recipe_hint="evaluate_expression_at_parameter",
                        goal_type="evaluate_expression_at_parameter",
                        target="answer:ii_1.minimum_value",
                        strategy="直接代入参数求最小值。",
                        reads=(
                            "fact:ii:path_minimum_expression",
                            "fact:ii_1:m_value",
                        ),
                        produces=(
                            ProducedFact(
                                handle="answer:ii_1.minimum_value",
                                valid_scope="ii_1",
                                output_type="MinimumExpression",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    issue = _issue_by_code(issues, "minimum_goal_lineage_incomplete")
    assert issue.step_id == "evaluate_minimum_i1"
    assert issue.repair_target == "answer:ii_1.minimum_value"
    assert "fact:ii:path_minimum_target" in issue.related_handles
    assert "fact:ii:straightened_candidate" in issue.related_handles


def test_goal_verifier_flags_point_answer_without_target_identity() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_2",
                label="第（Ⅱ）②问",
                steps=(
                    StepIntent(
                        scope_id="ii_2",
                        step_id="find_G_coordinate_i2",
                        recipe_hint="line_intersection_point",
                        goal_type="derive_line_intersection_point",
                        target="answer:ii_2.intersection",
                        strategy="求一个交点作为 G。",
                        reads=(
                            "fact:ii_2:m_value",
                            "point:ii:M",
                            "point:ii:N",
                        ),
                        produces=(
                            ProducedFact(
                                handle="answer:ii_2.intersection",
                                valid_scope="ii_2",
                                output_type="Point",
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    issue = _issue_by_code(issues, "point_goal_identity_unproven")
    assert issue.step_id == "find_G_coordinate_i2"
    assert issue.repair_target == "answer:ii_2.intersection"
    assert "point:ii:G" in issue.related_handles
    assert "fact:ii:segment_G_on_MN" in issue.related_handles


def test_goal_verifier_accepts_recorded_nankai_goal_witnesses() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    raw = json.loads(NANKAI_RECORDED.read_text(encoding="utf-8"))
    draft = StepIntentValidator().validate(
        raw,
        question_goals=extract_question_goals(problem),
        handle_registry=registry,
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    assert issues == ()


def test_goal_verification_retry_state_truncates_prefix_before_issue_step() -> None:
    issue = PlannerRetryIssue(
        layer="goal_verification",
        code="minimum_goal_lineage_incomplete",
        step_id="evaluate_minimum_i1",
        scope_id="ii_1",
        repair_target="answer:ii_1.minimum_value",
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="compute_path_expression",
                scope_id="ii_1",
                capability_id="path_minimum_by_straightened_distance",
            ),
            StepIntentAcceptedStep(
                step_id="evaluate_minimum_i1",
                scope_id="ii_1",
                capability_id="evaluate_expression_at_parameter",
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=(),
        diagnostic=diagnostic,
        goal_verification_issues=(issue,),
    )

    assert state is not None
    assert state.preserve_policy == "preserve_prefix"
    assert state.repair_suffix_start == {
        "step_id": "evaluate_minimum_i1",
        "scope_id": "ii_1",
    }
    assert [item["step_id"] for item in state.stable_prefix] == [
        "compute_path_expression"
    ]
    assert state.issues[0].layer == "goal_verification"

    with_answer_check = build_planner_retry_state(
        attempt=1,
        errors=("answer_mismatch: ii_1.minimum_value; actual=sqrt(5); expected=5/2",),
        diagnostic=diagnostic,
        goal_verification_issues=(issue,),
    )

    assert with_answer_check is not None
    assert with_answer_check.selected_repair_layer == "goal_verification"
    assert with_answer_check.preserve_policy == "preserve_prefix"
    assert [item["step_id"] for item in with_answer_check.stable_prefix] == [
        "compute_path_expression"
    ]


def _nankai_problem_payload_and_registry() -> tuple[dict, CanonicalHandleRegistry]:
    problem = load_problem_ir(NANKAI_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    return problem_payload, CanonicalHandleRegistry.from_problem_payload(problem_payload)


def _issue_by_code(issues, code: str):
    for issue in issues:
        if issue.code == code:
            return issue
    raise AssertionError(f"issue not found: {code}; got={[issue.code for issue in issues]}")
