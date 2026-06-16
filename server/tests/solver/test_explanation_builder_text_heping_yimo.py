from __future__ import annotations

import json
import os
from pathlib import Path
import inspect
import shutil
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver import load_expected_answers, load_problem_ir
from shuxueshuo_server.solver.explanation import (
    ExplanationBuilder,
    ExplanationSnapshotBuilder,
    LessonIRValidator,
    LLMLessonPlanner,
    write_explanation_debug_artifacts,
)
from shuxueshuo_server.solver.explanation import builder as explanation_builder
from shuxueshuo_server.solver.explanation.builder import LessonIRValidationError
from shuxueshuo_server.solver.explanation.few_shots import (
    select_lesson_few_shot_examples,
    validate_lesson_few_shot_entry,
)
from shuxueshuo_server.solver.explanation.llm import build_lesson_planner_payload
from shuxueshuo_server.solver.explanation.models import LessonCandidateGroup, LessonStep, TeachingTraceEntry
from shuxueshuo_server.solver.explanation.role_binders import RoleBinderRegistry, RoleBindingError
from shuxueshuo_server.solver.explanation.teaching_expansion import (
    explanation_payload_for_group,
)
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.recipes import EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC


ROOT = Path(__file__).resolve().parents[3]
HEPING_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-yimo-25.json"
HEPING_EXPECTED = "tests/solver/expected/tj-2026-heping-yimo-25.expected.json"
DEBUG_DIR = ROOT / "internal/solver-runs/explanation-builder-deepseek-heping"
RUN_DEEPSEEK_HEPING_EXPLANATION = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_EXPLANATION_BUILDER") == "1"
    and os.getenv("RUN_DEEPSEEK_HEPING_EXPLANATION") == "1"
)


def test_recorded_heping_success_artifacts_are_available_and_not_serialized() -> None:
    orchestrator, result = _solve_recorded_heping()

    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEPING_EXPECTED)
    assert orchestrator.last_success_artifacts is not None
    assert orchestrator.last_success_artifacts.context is not None
    assert orchestrator.last_success_artifacts.execution is not None
    assert orchestrator.last_success_artifacts.planner_output.step_plans

    payload = result.to_dict()
    assert "last_success_artifacts" not in payload
    assert "context" not in payload
    assert "planner_output" not in payload


def test_lesson_titles_come_from_capability_explanation_specs() -> None:
    source = inspect.getsource(explanation_builder._title_for_recipe)

    assert "if recipe ==" not in source
    assert explanation_builder._title_for_recipe(
        "quadratic_from_constraints",
        "derive_parabola",
    ) == "代入已知点求抛物线解析式"
    assert explanation_builder._title_for_recipe(
        "quadratic_from_constraints",
        "derive_parametric_parabola",
    ) == "用参数表示抛物线解析式"
    assert explanation_builder._title_for_recipe(
        "line_parabola_second_intersection_point",
        "derive_curve_intersection_point",
    ) == "联立直线与抛物线求交点"

    spec = MethodSpecRegistry.load_from_code().require("quadratic_from_constraints")
    assert spec.explanation is not None
    assert spec.explanation.student_title_templates_by_goal[
        "derive_parametric_parabola"
    ] == "用参数表示抛物线解析式"


def test_failed_or_unsupported_solve_does_not_keep_stale_success_artifacts() -> None:
    orchestrator, result = _solve_recorded_heping()
    assert result.status == "ok"
    assert orchestrator.last_success_artifacts is not None

    unsupported = ProblemIR(
        problem_id="unsupported-explanation-case",
        pattern="unsupported",
        problem_type="unsupported",
        symbols=[],
        original_text={"text": "unsupported"},
    )
    unsupported_result = orchestrator.solve(unsupported)

    assert unsupported_result.status == "unsupported"
    assert orchestrator.last_success_artifacts is None


def test_explanation_snapshot_from_recorded_heping_is_safe_and_invocation_level() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    payload = snapshot.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert snapshot.problem_id == "tj-2026-heping-yimo-25"
    assert snapshot.effective_steps
    assert snapshot.teaching_trace
    assert snapshot.fact_index
    assert snapshot.answers == load_expected_answers(HEPING_EXPECTED)
    assert "$problem." not in serialized
    assert "$question." not in serialized
    assert "$subquestion." not in serialized
    assert "raw_response" not in serialized
    assert "expected" not in serialized
    assert "<html" not in serialized.lower()

    method_ids = [entry.method_id for entry in snapshot.teaching_trace]
    duplicate_methods = {method_id for method_id in method_ids if method_ids.count(method_id) > 1}
    assert duplicate_methods
    assert len({entry.trace_id for entry in snapshot.teaching_trace}) == len(snapshot.teaching_trace)


def test_lesson_ir_from_recorded_heping_contains_answers_and_trace_refs() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    lesson = ExplanationBuilder().build_lesson(snapshot)
    payload = lesson.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert lesson.problem_id == snapshot.problem_id
    assert lesson.sections
    assert lesson.steps
    assert "$problem." not in serialized
    assert "<html" not in serialized.lower()
    for step in lesson.steps:
        assert step.source_step_ids
        assert step.capability_ids
        assert step.trace_refs
    assert "y=x²-2x-3" in serialized
    assert "E(-2/3,-11/9)" in serialized
    assert "a=3/4" in serialized
    assert "x**2 - 2*x - 3" not in serialized
    assert "i_1.parabola =" not in serialized
    assert "answer:" not in serialized
    assert "fact:" not in serialized


def test_lesson_ir_validator_rejects_machine_box_expression() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    lesson = ExplanationBuilder().build_lesson(snapshot)
    first_step = lesson.steps[0]
    bad_step = LessonStep(
        id=first_step.id,
        scope_id=first_step.scope_id,
        source_step_ids=first_step.source_step_ids,
        capability_ids=first_step.capability_ids,
        trace_refs=first_step.trace_refs,
        title=first_step.title,
        goal=first_step.goal,
        nav_title=first_step.nav_title,
        derive=first_step.derive,
        box=("i_1.parabola = x**2 - 2*x - 3",),
        gaps=first_step.gaps,
        teaching_substep_ids=first_step.teaching_substep_ids,
    )
    bad_lesson = type(lesson)(
        problem_id=lesson.problem_id,
        family_id=lesson.family_id,
        sections=lesson.sections,
        steps=(bad_step, *lesson.steps[1:]),
    )

    with pytest.raises(LessonIRValidationError, match="student-readable"):
        LessonIRValidator().validate(bad_lesson, snapshot)


def test_illegal_llm_text_output_falls_back_to_deterministic_template() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    lesson = ExplanationBuilder(text_planner=_IllegalHandleTextPlanner()).build_lesson(snapshot)

    assert lesson.steps
    assert any("lesson_text_planner_fallback" in step.gaps for step in lesson.steps)
    assert "point:fake:Z" not in json.dumps(lesson.to_payload(), ensure_ascii=False)


def test_llm_lesson_planner_can_group_steps_and_writes_debug_artifacts(tmp_path) -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    fake_client = _GroupingLessonClient()
    planner = LLMLessonPlanner(
        client=fake_client,
        debug_dir=tmp_path,
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    )

    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)

    assert lesson.steps
    assert any(len(step.source_step_ids) > 1 for step in lesson.steps)
    assert (tmp_path / "payload.explanation.json").exists()
    assert (tmp_path / "prompt.system.txt").exists()
    assert (tmp_path / "prompt.user.txt").exists()
    assert (tmp_path / "raw-response.txt").exists()
    assert (tmp_path / "parsed-lesson-draft.json").exists()
    assert (tmp_path / "payload.explanation_few_shots.json").exists()
    user_prompt = (tmp_path / "prompt.user.txt").read_text(encoding="utf-8")
    assert "讲解步骤分组策略" in user_prompt
    assert "不要把一个完整小问直接合并成一个 lesson step" in user_prompt
    assert "target_step_count_hint" in user_prompt
    assert "可分组的候选步骤" in user_prompt
    assert "示例讲解" in user_prompt
    assert "teaching_expansion_draft" in user_prompt
    assert "candidate_group_ids" in user_prompt
    assert "可以把一个 executable recipe 拆成多个 LessonIR steps" in user_prompt
    assert "先讲转化，再讲最值" in user_prompt
    assert "每个 derive item" in user_prompt
    assert "不要使用 `代入 / 化简 / 解 / 筛选`" in user_prompt
    assert "derive 标签" in user_prompt


def test_llm_mixed_reason_conclusion_derive_is_split() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    planner = LLMLessonPlanner(client=_MixedDeriveLessonClient())

    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)

    assert lesson.steps[0].derive[:2] == (
        ("∵", "抛物线y=ax²+bx-3中，令x=0得y=-3"),
        ("∴", "C(0,-3)"),
    )
    assert lesson.steps[0].derive[2:5] == (
        ("∵", "A(-1,0)和D(2,-3)在抛物线上，代入得方程组"),
        ("∴", "a·(-1)²+b·(-1)-3=0 → a-b=3"),
        ("∴", "a=1，b=-2"),
    )
    assert lesson.steps[0].derive[5:8] == (
        ("∵", "A(-1,0)在抛物线上"),
        ("∴", "代入得 a·(-1)²+b·(-1)-3=0 → a-b=3"),
        ("∴", "计算得 OG = 3√(2a²+1)/a"),
    )


def test_lesson_planner_repair_loop_fixes_unknown_candidate_id(tmp_path) -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    fake_client = _RepairingUnknownCandidateClient()
    planner = LLMLessonPlanner(client=fake_client, debug_dir=tmp_path, max_attempts=3)

    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)

    assert fake_client.calls == 2
    assert lesson.steps
    attempt_payload = json.loads(
        (tmp_path / "attempt-1.previous-attempt-payload.json").read_text(encoding="utf-8")
    )
    assert attempt_payload["repair_summary"]["current_blocker"]["code"] == "unknown_candidate_group_id"
    assert "repair_summary" in (tmp_path / "attempt-2.prompt.user.txt").read_text(encoding="utf-8")
    assert "$problem." not in json.dumps(attempt_payload, ensure_ascii=False)
    assert "Traceback" not in json.dumps(attempt_payload, ensure_ascii=False)
    assert "expected" not in json.dumps(attempt_payload, ensure_ascii=False).lower()


def test_lesson_planner_repair_loop_splits_path_reduction_and_minimum(tmp_path) -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    fake_client = _RepairingMergedSubstepClient()
    planner = LLMLessonPlanner(client=fake_client, debug_dir=tmp_path, max_attempts=3)

    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)

    assert fake_client.calls == 2
    assert lesson.steps
    attempt_payload = json.loads(
        (tmp_path / "attempt-1.previous-attempt-payload.json").read_text(encoding="utf-8")
    )
    summary = attempt_payload["repair_summary"]
    assert summary["current_blocker"]["code"] == "cognitive_action_merge_not_allowed"
    assert any("path_reduction" in action for action in summary["next_actions"])


def test_lesson_planner_repair_loop_falls_back_after_three_failures(tmp_path) -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    fake_client = _AlwaysInvalidLessonClient()
    planner = LLMLessonPlanner(client=fake_client, debug_dir=tmp_path, max_attempts=3)

    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)

    assert fake_client.calls == 3
    assert lesson.steps
    assert all(step.id != "bad_candidate_step" for step in lesson.steps)
    assert (tmp_path / "attempt-3.previous-attempt-payload.json").exists()
    assert (tmp_path / "payload.explanation.json").exists()


def test_recipe_explanation_spec_is_template_not_heping_specific() -> None:
    payload = EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)

    for forbidden in ("和平", "tj-2026-heping", "OM+BN", "BN", "MG", "OG"):
        assert forbidden not in serialized
    assert "{anchor}" in serialized
    assert "{original_path}" in serialized
    substeps = payload["explanation"]["teaching_substep_specs"]
    assert substeps[0]["title"] == "构造全等三角形，把两动点问题转化为单动点问题"
    assert substeps[0]["nav_title"] == "两动点转化单动点"
    assert substeps[1]["title"] == "将军饮马得到最小值表达式"
    assert substeps[1]["nav_title"] == "将军饮马取最小值"
    assert "最小值表达式" not in "\n".join(
        EQUAL_LENGTH_RAY_PATH_REDUCTION_SPEC.explanation.proof_outline_templates
    )


def test_equal_length_ray_recipe_teaching_draft_binds_heping_roles(tmp_path) -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    planner = LLMLessonPlanner(client=_GroupingLessonClient(), debug_dir=tmp_path)

    ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)
    payload = json.loads((tmp_path / "payload.explanation.json").read_text(encoding="utf-8"))
    groups = [
        item
        for item in payload["candidate_groups"]
        if item["source_step_id"] == "reduce_ii_equal_length_ray_path"
    ]

    assert [group["teaching_substep_id"] for group in groups] == [
        "path_reduction",
        "minimum_by_segment",
    ]

    group = groups[0]
    draft = group["teaching_expansion_draft"]
    serialized = json.dumps(draft, ensure_ascii=False)
    compact = serialized.replace(" ", "")

    assert group["candidate_group_id"] == "reduce_ii_equal_length_ray_path.path_reduction"
    assert group["recipe_explanation"]["recipe_id"] == "equal_length_ray_path_reduction"
    assert draft["confidence"] in {"complete", "partial"}
    assert draft["bound_roles"]["auxiliary_point"]["explanation_only_label"] is True
    assert "共线" in serialized
    assert "BN=MG" in compact
    assert "OM+BN=OM+MG" in compact
    assert "OG" in compact
    assert "最小值表达式" not in serialized
    assert "$problem." not in serialized
    assert "$question." not in serialized

    minimum_group = groups[1]
    minimum_draft = minimum_group["teaching_expansion_draft"]
    minimum_serialized = json.dumps(minimum_draft, ensure_ascii=False)

    assert minimum_group["candidate_group_id"] == "reduce_ii_equal_length_ray_path.minimum_by_segment"
    assert "两点之间线段最短" in minimum_serialized
    assert "G(3√(a²+1)/|a|,-3)" in minimum_serialized
    assert "OG=√((3√(a²+1)/|a|)²+(-3)²)=3√(2a²+1)/|a|" in minimum_serialized


def test_recorded_heping_lesson_splits_equal_length_reduction() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    lesson = ExplanationBuilder().build_lesson(snapshot)

    reduction_steps = [
        step
        for step in lesson.steps
        if "reduce_ii_equal_length_ray_path" in step.source_step_ids
    ]

    assert [step.teaching_substep_ids for step in reduction_steps] == [
        ("path_reduction",),
        ("minimum_by_segment",),
    ]
    assert reduction_steps[0].title == "构造全等三角形，把两动点问题转化为单动点问题"
    assert reduction_steps[0].nav_title == "两动点转化单动点"
    assert reduction_steps[1].title == "将军饮马得到最小值表达式"
    assert reduction_steps[1].nav_title == "将军饮马取最小值"


def test_line_parabola_method_keeps_single_step_with_intermediate_box() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    groups = tuple(__import__(
        "shuxueshuo_server.solver.explanation.builder",
        fromlist=["_build_lesson_groups"],
    )._build_lesson_groups(snapshot))
    line_groups = [
        group
        for group in groups
        if group.step_id == "derive_i_2_E_coordinate"
    ]

    assert len(line_groups) == 1
    assert line_groups[0].teaching_substep_id is None

    payload = explanation_payload_for_group(line_groups[0], snapshot)

    assert payload["teaching_expansion_draft"]["box"] == [
        "BE: y=(1/3)x-1",
        "E(-2/3,-11/9)",
    ]

    lesson = ExplanationBuilder().build_lesson(snapshot)
    split_steps = [
        step
        for step in lesson.steps
        if "derive_i_2_E_coordinate" in step.source_step_ids
    ]

    assert len(split_steps) == 1
    assert split_steps[0].teaching_substep_ids == ()
    assert split_steps[0].box == ("BE: y=(1/3)x-1", "E(-2/3,-11/9)")


def test_method_explanation_templates_support_placeholders() -> None:
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("distance_between_points")

    assert spec.explanation is not None
    assert spec.explanation.role_schema["p1"] == "第一个点或线段端点。"
    assert "{p1}" in spec.explanation.student_goal_template
    assert "{distance}" in "\n".join(spec.explanation.derive_templates)


def test_lesson_candidate_group_public_model_filters_preferred_traces() -> None:
    traces = (
        TeachingTraceEntry(
            trace_id="trace:one",
            source_step_id="step_one",
            scope_id="ii",
            capability_id="demo_capability",
            method_id="method_one",
        ),
        TeachingTraceEntry(
            trace_id="trace:two",
            source_step_id="step_one",
            scope_id="ii",
            capability_id="demo_capability",
            method_id="method_two",
        ),
    )
    group = LessonCandidateGroup(
        {"step_id": "step_one", "scope_id": "ii", "recipe_hint": "demo_capability"},
        traces,
        teaching_substep_id="substep",
        preferred_method_ids=("method_two",),
    )

    assert group.candidate_group_id == "step_one.substep"
    assert group.step_id == "step_one"
    assert group.scope_id == "ii"
    assert group.capability_id == "demo_capability"
    assert group.method_ids == ("method_two",)
    assert group.trace_refs == ("trace:two",)


def test_role_binder_registry_hits_registered_binders_and_fails_fast() -> None:
    registry = RoleBinderRegistry.default()

    assert registry.require_method("distance_between_points") is not None
    assert registry.require_recipe("equal_length_ray_path_reduction") is not None
    with pytest.raises(RoleBindingError, match="unknown method role_binder_id"):
        registry.require_method("missing_method_binder")
    with pytest.raises(RoleBindingError, match="unknown recipe role_binder_id"):
        registry.require_recipe("missing_recipe_binder")


def test_method_teaching_draft_binds_distance_roles() -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    group = SimpleNamespace(
        capability_id="distance_between_points",
        method_ids=("distance_between_points",),
        traces=(
            SimpleNamespace(
                trace_fragments=(
                    {
                        "goal": "把折线路径转为最短线段距离",
                        "reason": "路径转化后，折线最短值等于两个固定端点之间的距离。",
                        "calculation": "d=3*sqrt(2*a**2 + 1)/a",
                        "conclusion": "最小值表达式为 3*sqrt(2*a**2 + 1)/a",
                    },
                )
            ),
        ),
        step={
            "step_id": "mock_distance",
            "scope_id": "ii",
            "target": "fact:ii:path_minimum_expression",
            "reads": [],
            "produces": [
                {
                    "handle": "fact:ii:path_minimum_expression",
                    "description": "OG 的最小值表达式",
                    "output_type": "MinimumExpression",
                }
            ],
        },
    )

    payload = explanation_payload_for_group(group, snapshot)
    draft = payload["teaching_expansion_draft"]
    serialized = json.dumps(draft, ensure_ascii=False)

    assert draft["bound_roles"]["p1"] == "O"
    assert draft["bound_roles"]["p2"] == "G"
    assert "3*sqrt" in draft["bound_roles"]["distance"]
    assert "{p1}" not in serialized
    assert "$problem." not in serialized


def test_explanation_lesson_few_shot_selector_and_mock_fallback(tmp_path) -> None:
    current = _heping_lesson_few_shot_entry()
    other = {
        **current,
        "problem_id": "different-equal-length-lesson",
        "title": "different",
    }
    (tmp_path / "tj-2026-heping-yimo-25.lesson-few-shot.json").write_text(
        json.dumps(current, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "different-equal-length-lesson.lesson-few-shot.json").write_text(
        json.dumps(other, ensure_ascii=False),
        encoding="utf-8",
    )

    selected = select_lesson_few_shot_examples(
        family_id="QuadraticEqualLengthRayPathMinimumSolver",
        goal_types=["derive_path_minimum_expression"],
        capability_ids=["equal_length_ray_path_reduction"],
        problem_id="tj-2026-heping-yimo-25",
        allow_same_problem=False,
        few_shot_dir=tmp_path,
    )

    assert selected[0]["problem_id"] == "different-equal-length-lesson"
    validate_lesson_few_shot_entry(selected[0])


def test_explanation_payload_uses_equal_length_mock_when_same_problem_excluded(tmp_path) -> None:
    orchestrator, _ = _solve_recorded_heping()
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    groups = tuple(__import__(
        "shuxueshuo_server.solver.explanation.builder",
        fromlist=["_build_lesson_groups"],
    )._build_lesson_groups(snapshot))

    payload = build_lesson_planner_payload(
        snapshot,
        groups,
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    )
    few_shot = payload["explanation_few_shots"][0]
    serialized = json.dumps(few_shot, ensure_ascii=False)

    assert few_shot["problem_id"] == "fallback-equal-length-ray-lesson"
    for forbidden in ("tj-2026-heping-yimo-25", "OM+BN", "BN", "MG", "√34", "3/4"):
        assert forbidden not in serialized
    assert "作" in serialized
    assert "∵" in serialized
    assert "∴" in serialized


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_EXPLANATION,
    reason="DeepSeek Heping explanation builder integration is opt-in",
)
def test_deepseek_explanation_builder_heping_lesson_loop() -> None:
    """真实 DeepSeek 只做讲解 step 分组与文字优化，不参与解题。"""
    _reset_debug_dir(DEBUG_DIR)
    orchestrator, result = _solve_recorded_heping()
    assert result.status == "ok", result.errors
    snapshot = ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    planner = LLMLessonPlanner(
        client=config.build_llm_client(),
        debug_dir=DEBUG_DIR,
        allow_same_problem_few_shot=False,
    )

    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)
    assert planner.last_parsed is not None
    assert lesson.steps
    assert lesson.steps[0].id == planner.last_parsed["steps"][0]["id"]
    write_explanation_debug_artifacts(
        DEBUG_DIR,
        payload=planner.last_payload or {},
        prompt=planner.last_prompt,
        raw_response=planner.last_raw_response or "",
        parsed=planner.last_parsed,
        lesson=lesson,
    )

    print("DeepSeek Heping explanation LessonIR:")
    print(json.dumps(lesson.to_payload(), ensure_ascii=False, indent=2))
    assert (DEBUG_DIR / "payload.explanation.json").exists()
    assert (DEBUG_DIR / "lesson-ir.json").exists()


class _IllegalHandleTextPlanner:
    def plan_text(self, *, group, snapshot):
        return {
            "title": "错误引用 point:fake:Z",
            "goal": "伪造不存在对象",
            "derive": [["错误", "引用 point:fake:Z"]],
            "box": ["point:fake:Z"],
        }


class _GroupingLessonClient:
    provider_name = "fake-explanation"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        groups = payload["explanation_payload"]["candidate_groups"]
        steps = []
        index = 0
        while index < len(groups):
            current = groups[index]
            candidate_ids = [current["candidate_group_id"]]
            if (
                index + 1 < len(groups)
                and groups[index + 1]["scope_id"] == current["scope_id"]
                and groups[index + 1]["source_step_id"] != current["source_step_id"]
            ):
                candidate_ids.append(groups[index + 1]["candidate_group_id"])
                index += 1
            steps.append(
                {
                    "id": f"llm_step_{len(steps) + 1}",
                    "candidate_group_ids": candidate_ids,
                    "title": f"合并讲解 {len(steps) + 1}",
                    "goal": "把相邻的可执行步骤合并成学生可读的一步",
                    "derive": [["说明", "根据已验证的 method 结果整理讲解。"]],
                    "box": [f"完成 {', '.join(candidate_ids)}"],
                }
            )
            index += 1
        return json.dumps({"steps": steps}, ensure_ascii=False)


class _MixedDeriveLessonClient:
    provider_name = "fake-explanation"
    model = "fake"

    def __init__(self) -> None:
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        groups = payload["explanation_payload"]["candidate_groups"]
        first = groups[0]
        steps = [
            {
                "id": "mixed_derive_step",
                "candidate_group_ids": [first["candidate_group_id"]],
                "title": "第1步：求C点坐标",
                "goal": "由 y 轴交点求 C 点坐标",
                "derive": [
                    [
                        "解",
                        "抛物线y=ax²+bx-3中，令x=0得y=-3，所以C(0,-3)",
                    ],
                    [
                        "∵",
                        "A(-1,0)和D(2,-3)在抛物线上，代入得方程组",
                    ],
                    [
                        "代入",
                        "a·(-1)²+b·(-1)-3=0 → a-b=3",
                    ],
                    [
                        "解",
                        "a=1，b=-2",
                    ],
                    [
                        "∵",
                        "A(-1,0)在抛物线上，代入得 a·(-1)²+b·(-1)-3=0 → a-b=3",
                    ],
                    [
                        "∵",
                        "计算得 OG = 3√(2a²+1)/a",
                    ],
                ],
                "box": ["C(0,-3)"],
            }
        ]
        steps.extend(_valid_lesson_steps_for_groups(groups[1:], start_index=2))
        return json.dumps(
            {"steps": steps},
            ensure_ascii=False,
        )


class _RepairingUnknownCandidateClient:
    provider_name = "fake-explanation"
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        self.calls += 1
        groups = payload["explanation_payload"]["candidate_groups"]
        previous_attempts = payload["explanation_payload"].get("previous_attempts", [])
        if not previous_attempts:
            return json.dumps(
                {
                    "steps": [
                        {
                            "id": "bad_candidate_step",
                            "candidate_group_ids": ["not_a_candidate"],
                            "title": "错误候选",
                            "goal": "触发 repair",
                            "derive": [["∵", "使用不存在的候选"]],
                            "box": ["错误候选"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps({"steps": _valid_lesson_steps_for_groups(groups)}, ensure_ascii=False)


class _RepairingMergedSubstepClient:
    provider_name = "fake-explanation"
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        self.calls += 1
        groups = payload["explanation_payload"]["candidate_groups"]
        previous_attempts = payload["explanation_payload"].get("previous_attempts", [])
        if previous_attempts:
            return json.dumps({"steps": _valid_lesson_steps_for_groups(groups)}, ensure_ascii=False)
        reduction_groups = [
            group
            for group in groups
            if group["source_step_id"] == "reduce_ii_equal_length_ray_path"
        ]
        return json.dumps(
            {
                "steps": [
                    {
                        "id": "merged_reduction_step",
                        "candidate_group_ids": [
                            group["candidate_group_id"]
                            for group in reduction_groups
                        ],
                        "title": "第7步：构造辅助点并求最小值",
                        "goal": "故意把路径转化和求最值合并",
                        "derive": [["∵", "构造辅助点后直接求最小值"]],
                        "box": ["合并错误"],
                    }
                ]
            },
            ensure_ascii=False,
        )


class _AlwaysInvalidLessonClient:
    provider_name = "fake-explanation"
    model = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage = None
        self.last_response_model = "fake"

    def complete(self, payload: dict) -> str:
        self.calls += 1
        return json.dumps(
            {
                "steps": [
                    {
                        "id": "bad_candidate_step",
                        "candidate_group_ids": ["still_missing"],
                        "title": "持续错误",
                        "goal": "触发 fallback",
                        "derive": [["∵", "仍然引用不存在的候选"]],
                        "box": ["持续错误"],
                    }
                ]
            },
            ensure_ascii=False,
        )


def _valid_lesson_steps_for_groups(
    groups: list[dict],
    *,
    start_index: int = 1,
) -> list[dict]:
    steps = []
    for offset, group in enumerate(groups):
        index = start_index + offset
        steps.append(
            {
                "id": f"valid_lesson_step_{index}",
                "candidate_group_ids": [group["candidate_group_id"]],
                "title": f"第{index}步：讲解 {group['candidate_group_id']}",
                "goal": str(group.get("teaching_focus") or group.get("target") or "讲解当前步骤"),
                "derive": [["∵", "使用已验证的解题步骤"], ["∴", f"完成 {group['candidate_group_id']}"]],
                "box": [f"完成 {group['candidate_group_id']}"],
            }
        )
    return steps


def _solve_recorded_heping() -> tuple[RuntimeOrchestrator, object]:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    result = orchestrator.solve(load_problem_ir(HEPING_FIXTURE))
    return orchestrator, result


def _reset_debug_dir(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _heping_lesson_few_shot_entry() -> dict:
    path = ROOT / "internal/explanation-few-shots/tj-2026-heping-yimo-25.lesson-few-shot.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _answer_text(value) -> str:
    if isinstance(value, list):
        return "(" + ", ".join(_answer_text(item) for item in value) + ")"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {_answer_text(child)}" for key, child in value.items()) + "}"
    return str(value)
