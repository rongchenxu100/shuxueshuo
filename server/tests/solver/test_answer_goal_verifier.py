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
    StateWriteProvenance,
)
from shuxueshuo_server.solver.runtime.strategy_retry_state import (
    build_planner_retry_state,
)
from shuxueshuo_server.solver.runtime.strategy_planner import build_strategy_probe_inputs
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator


REPO_ROOT = Path(__file__).resolve().parents[3]
NANKAI_FIXTURE = REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_RECORDED = (
    REPO_ROOT
    / "internal/solver-fixtures/tj-2026-nankai-yimo-25.executable-step-intents.json"
)
HEPING_ERMO_FIXTURE = (
    REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.json"
)


def test_goal_verifier_flags_path_minimum_answer_without_witness_chain() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    inputs = build_strategy_probe_inputs(load_problem_ir(NANKAI_FIXTURE))
    evidence_outputs = tuple(
        output
        for recipe in inputs.family_spec.step_recipes
        if recipe.execution is not None
        for output in recipe.execution.output_aliases
    )
    witness_role = next(
        output.semantic_role
        for output in evidence_outputs
        if "path_minimum_witness" in output.goal_evidence_tags
        and output.runtime_type == "StraighteningCandidate"
    )
    expression_role = next(
        output.semantic_role
        for output in evidence_outputs
        if "path_minimum_expression" in output.goal_evidence_tags
        and output.required
    )
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
        family_spec=inputs.family_spec,
        diagnostic=StepIntentExecutionDiagnostic(
            ok=True,
            state_write_provenance=(
                StateWriteProvenance(
                    step_id="straighten_path",
                    scope_id="ii_1",
                    capability_id="broken_path_straightening_and_select",
                    produced_handle="fact:ii:straightened_candidate",
                    output_key="selected_candidate",
                    runtime_type="StraighteningCandidate",
                    identity_policy="value_only",
                    identity_role=witness_role,
                ),
                StateWriteProvenance(
                    step_id="compute_path_expression",
                    scope_id="ii_1",
                    capability_id="path_minimum_by_straightened_distance",
                    produced_handle="fact:ii:path_minimum_expression",
                    output_key="distance",
                    runtime_type="MinimumExpression",
                    identity_policy="value_only",
                    identity_role=expression_role,
                ),
            ),
        ),
    )

    issue = _issue_by_code(issues, "minimum_goal_lineage_incomplete")
    assert issue.step_id == "evaluate_minimum_i1"
    assert issue.repair_target == "answer:ii_1.minimum_value"
    assert "fact:ii:path_minimum_target" in issue.related_handles
    assert "fact:ii:straightened_candidate" in issue.related_handles


def test_goal_verifier_accepts_macro_declared_optional_witness_roles() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    inputs = build_strategy_probe_inputs(load_problem_ir(NANKAI_FIXTURE))
    expression_role = next(
        output.semantic_role
        for recipe in inputs.family_spec.step_recipes
        if recipe.execution is not None
        for output in recipe.execution.output_aliases
        if "path_minimum_expression" in output.goal_evidence_tags
    )
    witness_roles = tuple(
        dict.fromkeys(
            output.semantic_role
            for recipe in inputs.family_spec.step_recipes
            if recipe.execution is not None
            for output in recipe.execution.output_aliases
            if "path_minimum_witness" in output.goal_evidence_tags
        )
    )
    expression_handle = "fact:ii_1:path_minimum_expression"
    answer_handle = "answer:ii_1.minimum_value"
    answer_step = StepIntent(
        scope_id="ii_1",
        step_id="evaluate_minimum",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="evaluate_expression_at_parameter",
        target=answer_handle,
        strategy="evaluate the macro expression",
        reads=(expression_handle, "fact:ii_1:m_value"),
        produces=(
            ProducedFact(
                answer_handle,
                "ii_1",
                output_type="MinimumExpression",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="第（Ⅱ）①问",
                steps=(answer_step,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="straighten_path",
                scope_id="ii_1",
                capability_id="broken_path_straightening_minimum_expression",
                produced_handle=expression_handle,
                output_key="path_minimum_expression",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role=expression_role,
                evidence_roles=witness_roles,
                source_handles=("fact:ii:path_minimum_target",),
            ),
            StateWriteProvenance(
                step_id="evaluate_minimum",
                scope_id="ii_1",
                capability_id="evaluate_expression_at_parameter",
                produced_handle=answer_handle,
                output_key="evaluated_minimum_expression",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role="evaluated_minimum_expression",
                source_handles=(expression_handle, "fact:ii_1:m_value"),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        family_spec=inputs.family_spec,
        diagnostic=diagnostic,
    )

    assert not any(
        issue.code in {
            "minimum_goal_source_unproven",
            "minimum_goal_lineage_incomplete",
        }
        for issue in issues
    )


def test_goal_verifier_rejects_unrelated_distance_as_path_minimum_answer() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    inputs = build_strategy_probe_inputs(load_problem_ir(NANKAI_FIXTURE))
    witness_role = next(
        output.semantic_role
        for recipe in inputs.family_spec.step_recipes
        if recipe.execution is not None
        for output in recipe.execution.output_aliases
        if "path_minimum_witness" in output.goal_evidence_tags
    )
    answer_step = StepIntent(
        scope_id="ii_1",
        step_id="evaluate_unrelated_distance",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="evaluate_expression_at_parameter",
        target="answer:ii_1.minimum_value",
        strategy="evaluate an ordinary distance",
        reads=("fact:ii_1:ordinary_distance", "fact:ii_1:m_value"),
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                output_type="MinimumExpression",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="第（Ⅱ）①问",
                steps=(answer_step,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="unused_straightening",
                scope_id="ii_1",
                capability_id="broken_path_straightening_and_select",
                produced_handle="fact:ii_1:unused_witness",
                output_key="selected_candidate",
                runtime_type="StraighteningCandidate",
                identity_policy="value_only",
                identity_role=witness_role,
                source_handles=("fact:ii:path_minimum_target",),
            ),
            StateWriteProvenance(
                step_id="ordinary_distance",
                scope_id="ii_1",
                capability_id="distance_between_points",
                produced_handle="fact:ii_1:ordinary_distance",
                output_key="distance",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role="distance",
                source_handles=("point:problem:D", "point:ii:N"),
            ),
            StateWriteProvenance(
                step_id="evaluate_unrelated_distance",
                scope_id="ii_1",
                capability_id="evaluate_expression_at_parameter",
                produced_handle="answer:ii_1.minimum_value",
                output_key="evaluated_minimum_expression",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role="evaluated_minimum_expression",
                source_handles=(
                    "fact:ii_1:ordinary_distance",
                    "fact:ii_1:m_value",
                ),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=diagnostic,
        family_spec=inputs.family_spec,
    )

    issue = _issue_by_code(issues, "minimum_goal_source_unproven")
    assert issue.step_id == "evaluate_unrelated_distance"
    assert "fact:ii_1:ordinary_distance" in issue.related_handles
    assert "fact:ii_1:unused_witness" not in issue.related_handles


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


def test_point_goal_verifier_rejects_derived_role_renamed_as_target() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    answer_step = StepIntent(
        scope_id="ii_2",
        step_id="evaluate_target_point",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point_at_parameter",
        target="answer:ii_2.intersection",
        strategy="evaluate a prior point state",
        reads=("fact:ii:unrelated_endpoint", "point:ii:G"),
        produces=(
            ProducedFact(
                "answer:ii_2.intersection",
                "ii_2",
                output_type="Point",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_2",
                label="第（Ⅱ）②问",
                steps=(answer_step,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="evaluate_target_point",
                scope_id="ii_2",
                capability_id="evaluate_point_at_parameter",
                produced_handle="answer:ii_2.intersection",
                output_key="evaluated_point",
                runtime_type="Point",
                identity_policy="preserve_input_object",
                identity_role="evaluated_point",
                object_ref="role:path_endpoint@ii",
                source_handles=("fact:ii:unrelated_endpoint",),
                source_step_id="derive_unrelated_endpoint",
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=diagnostic,
    )

    issue = _issue_by_code(issues, "point_goal_source_mismatch")
    assert issue.step_id == "derive_unrelated_endpoint"
    assert "point:ii:G" in issue.related_handles


def test_goal_verifier_does_not_diagnose_unexecuted_answer_suffix() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    answer_step = StepIntent(
        scope_id="ii_2",
        step_id="evaluate_target_point",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point_at_parameter",
        target="answer:ii_2.intersection",
        strategy="evaluate a target point after an earlier runtime step",
        reads=("fact:ii:unrelated_endpoint", "point:ii:G"),
        produces=(
            ProducedFact(
                "answer:ii_2.intersection",
                "ii_2",
                output_type="Point",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_2",
                label="第（Ⅱ）②问",
                steps=(answer_step,),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=StepIntentExecutionDiagnostic(ok=False, accepted_prefix=()),
    )

    assert issues == ()


def test_goal_verifier_flags_answer_that_skips_visible_parameter_value() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    parameter_step = StepIntent(
        scope_id="ii_1",
        step_id="solve_parameter",
        recipe_hint="parameter_from_expression_value",
        goal_type="solve_parameter",
        target="fact:ii_1:m_value",
        strategy="solve a parameter value",
        produces=(
            ProducedFact(
                "fact:ii_1:m_value",
                "ii_1",
                output_type="ParameterValue",
            ),
        ),
    )
    answer_step = StepIntent(
        scope_id="ii_1",
        step_id="write_symbolic_minimum",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum_value",
        target="answer:ii_1.minimum_value",
        strategy="write a still-symbolic minimum expression",
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                output_type="MinimumExpression",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="第（Ⅱ）①问",
                steps=(parameter_step, answer_step),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="solve_parameter",
                scope_id="ii_1",
                capability_id="parameter_from_expression_value",
                produced_handle="fact:ii_1:m_value",
                output_key="parameter_value",
                runtime_type="ParameterValue",
                identity_policy="preserve_input_object",
                identity_role="parameter_value",
                object_ref="symbol:problem:m",
            ),
            StateWriteProvenance(
                step_id="write_symbolic_minimum",
                scope_id="ii_1",
                capability_id="broken_path_straightening_minimum_expression",
                produced_handle="answer:ii_1.minimum_value",
                output_key="path_minimum_expression",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role="path_minimum_expression",
                free_symbol_names=("m",),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=diagnostic,
    )

    issue = _issue_by_code(issues, "answer_unresolved_symbol_state")
    assert issue.step_id == "write_symbolic_minimum"
    assert issue.details == {
        "unresolved_symbols": ["m"],
        "allowed_free_symbols": [],
        "available_parameter_symbols": ["m"],
        "available_parameter_states": ["fact:ii_1:m_value"],
    }
    assert "symbol:problem:m" in issue.related_handles


def test_goal_verifier_rejects_parameterized_answer_without_available_value() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    answer_step = StepIntent(
        scope_id="ii_1",
        step_id="write_parameterized_minimum",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum_value",
        target="answer:ii_1.minimum_value",
        strategy="write a parameterized minimum expression",
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                output_type="MinimumExpression",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="第（Ⅱ）①问",
                steps=(answer_step,),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=StepIntentExecutionDiagnostic(
            ok=True,
            state_write_provenance=(
                StateWriteProvenance(
                    step_id="write_parameterized_minimum",
                    scope_id="ii_1",
                    capability_id="broken_path_straightening_minimum_expression",
                    produced_handle="answer:ii_1.minimum_value",
                    output_key="path_minimum_expression",
                    runtime_type="MinimumExpression",
                    identity_policy="value_only",
                    identity_role="path_minimum_expression",
                    free_symbol_names=("m",),
                ),
            ),
        ),
    )

    issue = _issue_by_code(issues, "answer_unresolved_symbol_state")
    assert issue.details == {
        "unresolved_symbols": ["m"],
        "allowed_free_symbols": [],
        "available_parameter_symbols": [],
        "available_parameter_states": [],
    }


def test_goal_verifier_rejects_symbol_not_closed_in_answer_scope() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    sibling_parameter_step = StepIntent(
        scope_id="ii_2",
        step_id="solve_parameter_in_sibling",
        recipe_hint="parameter_from_expression_value",
        goal_type="solve_parameter",
        target="fact:ii_2:m_value",
        strategy="solve a sibling parameter value",
        produces=(
            ProducedFact(
                "fact:ii_2:m_value",
                "ii_2",
                output_type="ParameterValue",
            ),
        ),
    )
    answer_step = StepIntent(
        scope_id="ii_1",
        step_id="write_parameterized_minimum",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum_value",
        target="answer:ii_1.minimum_value",
        strategy="write a parameterized minimum expression",
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                output_type="MinimumExpression",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_2",
                label="第（Ⅱ）②问",
                steps=(sibling_parameter_step,),
            ),
            StepIntentScope(
                scope_id="ii_1",
                label="第（Ⅱ）①问",
                steps=(answer_step,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="solve_parameter_in_sibling",
                scope_id="ii_2",
                capability_id="parameter_from_expression_value",
                produced_handle="fact:ii_2:m_value",
                output_key="parameter_value",
                runtime_type="ParameterValue",
                identity_policy="preserve_input_object",
                identity_role="parameter_value",
                object_ref="symbol:problem:m",
            ),
            StateWriteProvenance(
                step_id="write_parameterized_minimum",
                scope_id="ii_1",
                capability_id="broken_path_straightening_minimum_expression",
                produced_handle="answer:ii_1.minimum_value",
                output_key="path_minimum_expression",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role="path_minimum_expression",
                free_symbol_names=("m",),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=diagnostic,
    )

    issue = _issue_by_code(issues, "answer_unresolved_symbol_state")
    assert issue.details["unresolved_symbols"] == ["m"]
    assert issue.details["available_parameter_states"] == []


def test_goal_verifier_describes_companion_symbol_identity_mismatch() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    parameterized_point = StepIntent(
        scope_id="ii",
        step_id="parameterize_E",
        recipe_hint="quadratic_axis_parameterized_point",
        goal_type="parameterize_point_on_quadratic_axis",
        target="fact:ii:E_coordinate",
        strategy="parameterize E",
        produces=(
            ProducedFact(
                "fact:ii:E_coordinate",
                "ii",
                output_type="Point",
            ),
        ),
    )
    solve_coefficient = StepIntent(
        scope_id="ii",
        step_id="solve_c",
        recipe_hint="parameter_from_expression_value",
        goal_type="derive_parameter",
        target="fact:ii:c_value",
        strategy="solve c",
        produces=(
            ProducedFact(
                "fact:ii:c_value",
                "ii",
                output_type="ParameterValue",
            ),
        ),
    )
    answer = StepIntent(
        scope_id="ii",
        step_id="evaluate_E",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point",
        target="answer:ii.E",
        strategy="incorrectly substitute c into E",
        reads=("fact:ii:E_coordinate", "fact:ii:c_value"),
        produces=(
            ProducedFact(
                "answer:ii.E",
                "ii",
                output_type="Point",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                "ii",
                "第（Ⅱ）问",
                (parameterized_point, solve_coefficient, answer),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="parameterize_E",
                scope_id="ii",
                capability_id="quadratic_axis_parameterized_point",
                produced_handle="symbol:ii:E_axis_parameter",
                output_key="parameter",
                runtime_type="Symbol",
                identity_policy="derived_role",
                identity_role="axis_parameter",
                object_ref="symbol:ii:E_axis_parameter",
                source_handles=("point:ii:E",),
                free_symbol_names=("_axis_param_E",),
            ),
            StateWriteProvenance(
                step_id="solve_c",
                scope_id="ii",
                capability_id="parameter_from_expression_value",
                produced_handle="fact:ii:c_value",
                output_key="parameter_value",
                runtime_type="ParameterValue",
                identity_policy="preserve_input_object",
                identity_role="parameter_value",
                object_ref="symbol:problem:c",
            ),
            StateWriteProvenance(
                step_id="evaluate_E",
                scope_id="ii",
                capability_id="evaluate_point_at_parameter",
                produced_handle="answer:ii.E",
                output_key="evaluated_point",
                runtime_type="Point",
                identity_policy="preserve_input_object",
                identity_role="evaluated_point",
                object_ref="point:ii:E",
                source_handles=(
                    "fact:ii:E_coordinate",
                    "fact:ii:c_value",
                ),
                free_symbol_names=("_axis_param_E",),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=diagnostic,
    )

    issue = _issue_by_code(issues, "answer_unresolved_symbol_state")
    assert "点 E 的未定坐标参数" in issue.message
    assert "参数值 c 属于其他 Symbol" in issue.message
    assert issue.details["unresolved_symbol_states"] == [
        {
            "runtime_symbol": "_axis_param_E",
            "semantic_role": "axis_parameter",
            "description": "点 E 的未定坐标参数",
            "object_ref": "symbol:ii:E_axis_parameter",
            "semantic_ref": "E_axis_parameter",
            "source_object_ref": "point:ii:E",
        }
    ]
    assert issue.details["incompatible_parameter_states"] == [
        {
            "parameter": "c",
            "state": "fact:ii:c_value",
            "object_ref": "symbol:problem:c",
            "reason": "symbol_identity_mismatch",
        }
    ]
    assert any(
        "不能因为它是唯一可见参数值就强行代入" in hint
        for hint in issue.hints
    )


def test_goal_verifier_allows_function_variable_but_rejects_free_coefficient() -> None:
    problem_payload, registry = _nankai_problem_payload_and_registry()
    answer_step = StepIntent(
        scope_id="i",
        step_id="write_incomplete_parabola",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i.parabola",
        strategy="write a parabola with one unresolved coefficient",
        produces=(
            ProducedFact(
                "answer:i.parabola",
                "i",
                output_type="Parabola",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(StepIntentScope("i", "第（Ⅰ）问", (answer_step,)),)
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id=answer_step.step_id,
                scope_id="i",
                capability_id="quadratic_from_constraints",
                produced_handle="answer:i.parabola",
                output_key="parabola",
                runtime_type="Parabola",
                identity_policy="preserve_input_object",
                identity_role="parabola",
                free_symbol_names=("c", "x"),
            ),
        ),
    )

    issues = AnswerGoalVerifier().verify(
        draft,
        problem_payload=problem_payload,
        handle_registry=registry,
        diagnostic=diagnostic,
    )

    issue = _issue_by_code(issues, "answer_unresolved_symbol_state")
    assert issue.details["unresolved_symbols"] == ["c"]
    assert issue.details["allowed_free_symbols"] == ["x"]


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
