from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

from shuxueshuo_server.solver import load_expected_answers, load_problem_ir
from shuxueshuo_server.solver.explanation import (
    ExplanationBuilder,
    ExplanationSnapshotBuilder,
    LLMLessonPlanner,
    LessonIRValidator,
    builder as explanation_builder,
    lesson_ir_from_payload,
    write_explanation_debug_artifacts,
)
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonIR
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.visual import (
    LLMVisualStepOptimizer,
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)


ROOT = Path(__file__).resolve().parents[3]
HEPING_ERMO_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-ermo-25.json"
HEPING_ERMO_EXPECTED = "tests/solver/expected/tj-2026-heping-ermo-25.expected.json"
HEPING_ERMO_RECORDED_LESSON_IR = (
    ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.lesson-ir.json"
)
DEBUG_DIR = ROOT / "internal/solver-runs/visual-builder-deepseek-heping-ermo"
RECORDED_LESSON_DEBUG_DIR = (
    ROOT / "internal/solver-runs/visual-builder-deepseek-heping-ermo-recorded-lesson"
)
RUN_DEEPSEEK_HEPING_ERMO_VISUAL = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_VISUAL_BUILDER") == "1"
    and os.getenv("RUN_DEEPSEEK_HEPING_ERMO_VISUAL") == "1"
)


@dataclass(frozen=True)
class HepingErmoPage:
    snapshot: ExplanationSnapshot
    lesson: LessonIR
    visual_ir: Any
    compiled: Any


@pytest.fixture(scope="module")
def heping_ermo_page() -> HepingErmoPage:
    snapshot = _solve_heping_ermo_snapshot()
    lesson = ExplanationBuilder().build_lesson(snapshot)

    LessonIRValidator().validate(lesson, snapshot)
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir)

    return HepingErmoPage(
        snapshot=snapshot,
        lesson=lesson,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


def test_vs1_recorded_heping_ermo_builds_valid_generated_page(heping_ermo_page: HepingErmoPage) -> None:
    page = heping_ermo_page

    assert page.visual_ir.metadata["base_source"] == "generated"
    assert len(page.visual_ir.steps) == len(page.lesson.steps)
    assert len(page.lesson.steps) >= 9
    assert page.snapshot.answers == load_expected_answers(HEPING_ERMO_EXPECTED)
    assert len(page.compiled.lesson_data["steps"]) == len(page.lesson.steps)


def test_vs1_heping_ermo_lesson_steps_are_grouped_by_reusable_capabilities(
    heping_ermo_page: HepingErmoPage,
) -> None:
    lesson = heping_ermo_page.lesson

    first_step = lesson.steps[0]
    assert first_step.source_step_ids == (
        "determine_quadratic_i",
        "derive_vertex_P",
        "derive_x_intercept_A",
    )
    assert first_step.capability_ids == (
        "quadratic_from_constraints",
        "quadratic_vertex_point",
        "quadratic_x_axis_intercept_point",
    )
    assert first_step.title == "代入已知条件，求解析式、顶点和 x 轴交点"
    assert first_step.nav_title == "求解析式、顶点和交点"
    assert first_step.box == ("y＝－x²－2x＋3", "P(-1,4)", "A(-3,0)")

    axis_square_step = _lesson_step(
        lesson,
        "explain_parameterize_axis_point_E_i2_derive_square_vertex_G_i2",
    )
    assert axis_square_step.capability_ids == (
        "quadratic_axis_parameterized_point",
        "square_adjacent_vertex_from_side",
    )
    assert axis_square_step.title == "由正方形求相邻顶点G"
    assert axis_square_step.nav_title == "正方形求顶点G"
    assert axis_square_step.box == ("E(－1,t)", "G(t－3,－2)")
    assert any(text == "G(t－3,－2)" for _, text in axis_square_step.derive)

    candidate_step = _lesson_step(lesson, "explain_solve_E_candidates_from_G_on_parabola")
    assert candidate_step.title == "代入抛物线求点E候选"
    assert candidate_step.nav_title == "求点E候选"
    assert candidate_step.box == ("E(－1,2＋√6) 或 E(－1,2－√6)",)

    reduce_step = _lesson_step(lesson, "explain_reduce_square_path_dimension")
    assert reduce_step.title == "由斜边中线和中位线转化线段"
    assert reduce_step.nav_title == "多动点转化为单动点问题"
    assert reduce_step.box == ("FM＝AE/2", "HF＝AG/2", "HF＋FM＝AG", "HF＋FM＋MG＝AG＋MG")

    simplify_step = _lesson_step(lesson, "explain_simplify_quadratic_with_A_derive_axis_point_M")
    assert simplify_step.capability_ids == (
        "quadratic_from_constraints",
        "quadratic_axis_x_intercept_point",
    )
    assert simplify_step.title == "化简函数解析式，求对称轴与X轴交点M"
    assert simplify_step.nav_title == "化简解析式求M"
    assert simplify_step.box == ("y＝－x²＋(1－c)x＋c", "M(1/2－c/2,0)")

    axis_square_ii_step = _lesson_step(
        lesson,
        "explain_parameterize_axis_point_E_ii_derive_square_vertex_G_ii_derive_G_locus_line",
    )
    assert axis_square_ii_step.capability_ids == (
        "quadratic_axis_parameterized_point",
        "square_adjacent_vertex_from_side",
        "parameterized_point_locus_line",
    )
    assert axis_square_ii_step.title == "正方形求顶点G轨迹"
    assert axis_square_ii_step.box == (
        "E(1/2－c/2,t)",
        "G(－c＋t,－c/2－1/2)",
        "y＝－(c＋1)/2",
    )

    minimum_step = _lesson_step(lesson, "explain_derive_path_minimum_expr")
    assert minimum_step.capability_ids == ("broken_path_straightening_minimum_expression",)
    assert minimum_step.title == "将军饮马计算最小值表达式"
    assert minimum_step.nav_title == "将军饮马算最小值"
    assert minimum_step.box == (
        "A′(-c,-c-1)",
        "A′M＝√(((c＋1)/2)²＋(c＋1)²)＝√5|c＋1|/2",
    )

    parameter_step = _lesson_step(
        lesson,
        "explain_derive_parameter_c_evaluate_A_at_c_derive_minimum_G_point",
    )
    assert parameter_step.capability_ids == (
        "parameter_from_expression_value",
        "evaluate_point_at_parameter",
        "line_locus_minimum_point",
    )
    assert parameter_step.title == "由最小值反求参数，并求A、G坐标"
    assert parameter_step.nav_title == "反求参数求A、G"
    assert parameter_step.box == ("c＝5", "A(－5,0)", "G(－7/2,－3)")


def test_vs1_heping_ermo_geometry_shell_has_scope_safe_points_and_answers(
    heping_ermo_page: HepingErmoPage,
) -> None:
    page = heping_ermo_page
    geometry = page.compiled.geometry_spec
    lesson_data = page.compiled.lesson_data

    group_titles = lesson_data["ui"]["groupTitles"]
    assert group_titles["i_1"] == "第（Ⅰ）①问：求点 P 和点 A 的坐标"
    assert group_titles["i_2"] == "第（Ⅰ）②问：求点 E 的坐标"
    assert group_titles["ii"] == "第（Ⅱ）问：求点 E 的坐标"
    assert lesson_data["steps"][0]["section"] == group_titles["i_1"]
    assert lesson_data["steps"][1]["section"] == group_titles["i_2"]

    assert geometry["id"] == page.snapshot.problem_id
    assert geometry["domain"]["maxX"] > 1
    assert geometry["fixedPoints"]["A1"] == ["-3", "0"]
    assert geometry["fixedPoints"]["P1"] == ["-1", "4"]
    assert geometry["fixedPoints"]["E_axis_i_2_candidate_1"] == ["-1", "2+sqrt(6)"]
    assert geometry["fixedPoints"]["E_axis_i_2_candidate_2"] == ["-1", "2-sqrt(6)"]
    assert "A" not in geometry["fixedPoints"]
    assert geometry["movingPoints"]["A"] == ["-c", "0"]
    assert geometry["movingPoints"]["G_axis_ii"] == ["3/2-c", "-c/2-1/2"]
    assert geometry["movingPoints"]["A_prime"] == ["-c", "-c-1"]
    assert geometry["pointMeta"]["A_prime"]["label"] == "A′"

    problem_lines = lesson_data["problem"]["lines"]
    assert "answerId" not in problem_lines[0]
    assert problem_lines[1]["answer"] == "P(－1, 4)，A(－3, 0)"
    assert problem_lines[2]["answer"] == "E(－1, 2＋√6) 或 E(－1, 2－√6)"
    assert problem_lines[3]["answer"] == "E(－2, 3/2)"
    assert "internal/lesson-specs" not in json.dumps(
        {
            "geometry": geometry,
            "lesson": lesson_data,
            "decorations": page.compiled.step_decorations,
        },
        ensure_ascii=False,
    )


def test_vs1_heping_ermo_square_candidate_and_path_decorations_are_bound(
    heping_ermo_page: HepingErmoPage,
) -> None:
    page = heping_ermo_page
    lesson = page.lesson

    axis_square_step = _lesson_step(
        lesson,
        "explain_parameterize_axis_point_E_i2_derive_square_vertex_G_i2",
    )
    square_decorations = _step_decorations(page, axis_square_step.id)
    assert {"type": "point", "at": "E_axis_i_2", "labelText": "E", "color": "#dc2626", "dx": 14, "dy": -18} in square_decorations
    assert {"type": "coordinateLabel", "at": "G_axis_i_2", "text": "G(t-3,-2)", "dx": 14, "dy": 34} in square_decorations
    assert any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == ["A1", "E_axis_i_2", "K_axis_i_2", "G_axis_i_2"]
        for item in square_decorations
    )
    assert any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == ["A1", "E_axis_i_2", "M1"]
        for item in square_decorations
    )
    assert any(item.get("type") == "rightAngle" for item in square_decorations)

    candidate_step = _lesson_step(lesson, "explain_solve_E_candidates_from_G_on_parabola")
    candidate_decorations = _step_decorations(page, candidate_step.id)
    assert not any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == ["A1", "E_axis_i_2", "K_axis_i_2", "G_axis_i_2"]
        for item in candidate_decorations
    )
    assert any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == [
            "A1",
            "E_axis_i_2_candidate_1",
            "K_axis_i_2_candidate_1",
            "G_axis_i_2_candidate_1",
        ]
        for item in candidate_decorations
    )
    assert {
        "type": "coordinateLabel",
        "at": "E_axis_i_2_candidate_1",
        "text": "E(-1,2+√6)",
        "dx": 14,
        "dy": 34,
    } in candidate_decorations

    reduce_step = _lesson_step(lesson, "explain_reduce_square_path_dimension")
    reduce_decorations = _step_decorations(page, reduce_step.id)
    assert any(
        item.get("type") == "outlineRegion"
        and item.get("vertices") == ["A", "E_axis_ii", "K_axis_ii", "G_axis_ii"]
        and str(item.get("fill") or "").startswith("rgba(15, 118, 110")
        for item in reduce_decorations
    )
    assert {"type": "coloredLine", "from": "H", "to": "F", "color": "#7c3aed", "width": 2.0} in reduce_decorations
    assert {"type": "coloredLine", "from": "A", "to": "G_axis_ii", "color": "#b45309", "width": 2.4} in reduce_decorations
    assert not any(
        item.get("type") == "segment"
        and str(item.get("label") or "") in {"HF=AG/2", "FM=AE/2"}
        for item in reduce_decorations
    )


def test_vs1_heping_ermo_locus_minimum_and_parameter_interactions_are_bound(
    heping_ermo_page: HepingErmoPage,
) -> None:
    page = heping_ermo_page
    lesson = page.lesson

    axis_square_ii_step = _lesson_step(
        lesson,
        "explain_parameterize_axis_point_E_ii_derive_square_vertex_G_ii_derive_G_locus_line",
    )
    axis_square_ii_decorations = _step_decorations(page, axis_square_ii_step.id)
    assert {
        "type": "dashedLine",
        "from": "G_locus_ii_start",
        "to": "G_locus_ii_end",
        "color": "#0f766e",
        "width": 2.0,
        "dash": "7 5",
    } in axis_square_ii_decorations
    assert not any(
        item.get("type") == "point" and item.get("at") in {"F", "H"}
        for item in axis_square_ii_decorations
    )
    axis_square_ii_data = _lesson_data_step(page, axis_square_ii_step.id)
    assert axis_square_ii_data["localControls"]["values"]["u"] == 1.5
    axis_square_ii_overrides = page.compiled.step_decorations["steps"][axis_square_ii_step.id]["pointOverrides"]
    assert axis_square_ii_overrides["E_axis_ii"] == ["1/2-c/2", "u"]
    assert axis_square_ii_overrides["G_axis_ii"] == ["-c+u", "-c/2-1/2"]

    minimum_step = _lesson_step(lesson, "explain_derive_path_minimum_expr")
    minimum_decorations = _step_decorations(page, minimum_step.id)
    assert {
        "type": "coordinateLabel",
        "at": "A_prime",
        "text": "A′(-c,-c-1)",
        "dx": 14,
        "dy": 34,
    } in minimum_decorations
    assert {
        "type": "segment",
        "from": "A_prime",
        "to": "M",
        "label": "A′M",
        "color": "#b45309",
        "width": 2.8,
        "offsetPx": 16,
    } in minimum_decorations
    minimum_data = _lesson_data_step(page, minimum_step.id)
    assert minimum_data["localControls"]["controls"][0]["var"] == "u"
    assert minimum_data["localControls"]["controls"][0]["label"].startswith("动点 G")
    minimum_overrides = page.compiled.step_decorations["steps"][minimum_step.id]["pointOverrides"]
    assert minimum_overrides["G_axis_ii"] == ["12.049*u-6.8", "-c/2-1/2"]
    assert "G" not in minimum_overrides

    parameter_step = _lesson_step(
        lesson,
        "explain_derive_parameter_c_evaluate_A_at_c_derive_minimum_G_point",
    )
    parameter_decorations = _step_decorations(page, parameter_step.id)
    assert {"type": "coordinateLabel", "at": "A", "text": "A(－5,0)", "dx": 14, "dy": -28} in parameter_decorations
    assert {"type": "coordinateLabel", "at": "G", "text": "G(－7/2,－3)", "dx": 14, "dy": 34} in parameter_decorations
    assert not any(
        item.get("type") == "point"
        and item.get("at") == "G_axis_ii"
        and item.get("color") == "#b45309"
        for item in parameter_decorations
    )


def test_vs1_heping_ermo_compiled_artifacts_validate(
    heping_ermo_page: HepingErmoPage,
    tmp_path: Path,
) -> None:
    lesson_data = copy.deepcopy(heping_ermo_page.compiled.lesson_data)
    html_path = tmp_path / "heping-ermo-vs1.html"
    lesson_data["meta"]["outputPath"] = str(html_path)
    _write_compiled_artifacts(
        tmp_path,
        geometry_spec=heping_ermo_page.compiled.geometry_spec,
        step_decorations=heping_ermo_page.compiled.step_decorations,
        lesson_data=lesson_data,
    )

    subprocess.run(
        ["node", str(ROOT / "tools/validate-geometry-spec.mjs"), str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/build-lesson-page.mjs"), str(tmp_path)],
        cwd=ROOT,
        check=True,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "STEPS" in html
    assert "第（Ⅰ）①问" in html
    assert "第（Ⅰ）②问" in html
    assert "第（Ⅱ）问" in html
    assert "E(－2, 3/2)" in html or "E(-2,3/2)" in html


def _lesson_step(lesson: LessonIR, step_id: str):
    return next(step for step in lesson.steps if step.id == step_id)


def _step_decorations(page: HepingErmoPage, step_id: str) -> list[dict[str, Any]]:
    return page.compiled.step_decorations["steps"][step_id]["add"]


def _lesson_data_step(page: HepingErmoPage, step_id: str) -> dict[str, Any]:
    return next(step for step in page.compiled.lesson_data["steps"] if step["id"] == step_id)


def test_lesson_draft_final_step_does_not_collect_prior_answers_with_display_variants() -> None:
    snapshot = _solve_heping_ermo_snapshot()
    groups = tuple(explanation_builder._build_lesson_groups(snapshot))
    raw_steps = []
    for index, group in enumerate(groups, start=1):
        answer_boxes = explanation_builder._answer_boxes_for_step(group.step, snapshot.answers)
        raw_steps.append(
            {
                "id": f"draft_step_{index}",
                "candidate_group_ids": [group.candidate_group_id],
                "title": group.teaching_substep_title or f"第{index}步：讲解 {group.candidate_group_id}",
                "nav_title": group.teaching_substep_nav_title or f"讲解 {index}",
                "goal": "按已验证结果整理讲解",
                "derive": [["∵", "使用已验证的解题步骤"], ["∴", "得到当前步骤结论"]],
                "box": [_fullwidth_answer_variant(item) for item in answer_boxes],
            }
        )

    result = explanation_builder.validate_lesson_draft({"steps": raw_steps}, groups, snapshot)

    assert result.lesson is not None, result.diagnostic.to_payload()
    final_step = next(
        step
        for step in result.lesson.steps
        if "derive_extremal_E_from_square_side" in step.source_step_ids
    )
    final_box = json.dumps(final_step.box, ensure_ascii=False).replace(" ", "")
    assert "E(－2,3/2)" in final_box or "E(-2,3/2)" in final_box
    assert "P(" not in final_box
    assert "A(-3,0)" not in final_box
    assert "A(－3,0)" not in final_box
    assert "2+√6" not in final_box
    assert "2＋√6" not in final_box


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_ERMO_VISUAL,
    reason="DeepSeek Heping ermo visual optimizer integration is opt-in",
)
def test_deepseek_explanation_and_visual_optimizer_heping_ermo_loop() -> None:
    """产品级链路：DeepSeek 先优化和平二模 LessonIR，再优化 VisualStepIR。"""
    _reset_debug_dir(DEBUG_DIR)
    snapshot = _solve_heping_ermo_snapshot()
    lesson = _build_heping_ermo_lesson_with_deepseek(snapshot, DEBUG_DIR)

    assert lesson.steps
    assert len(lesson.steps) <= 20

    _optimize_and_write_visual_page(
        snapshot=snapshot,
        lesson=lesson,
        debug_dir=DEBUG_DIR,
        html_name="heping-ermo-visual-optimized.html",
    )

    assert (DEBUG_DIR / "explanation" / "payload.explanation.json").exists()
    assert (DEBUG_DIR / "payload.visual.json").exists()
    assert (DEBUG_DIR / "lesson-ir.json").exists()
    assert (DEBUG_DIR / "visual-step-ir.before-optimization.json").exists()
    assert (DEBUG_DIR / "visual-step-ir.after-optimization.json").exists()
    assert (DEBUG_DIR / "heping-ermo-visual-optimized.html").exists()
    _assert_debug_page_group_titles_have_targets(
        DEBUG_DIR,
        html_name="heping-ermo-visual-optimized.html",
    )
    _assert_debug_page_final_e_box_is_scoped(DEBUG_DIR)


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_ERMO_VISUAL,
    reason="DeepSeek Heping ermo visual optimizer integration is opt-in",
)
def test_deepseek_visual_optimizer_with_heping_ermo_recorded_lesson_ir_fixture() -> None:
    """Visual-only 链路：读取和平二模 recorded LessonIR fixture，只调用视觉 DeepSeek。"""
    _reset_debug_dir(RECORDED_LESSON_DEBUG_DIR)
    snapshot = _solve_heping_ermo_snapshot()
    lesson = _load_recorded_heping_ermo_lesson_ir()

    LessonIRValidator().validate(lesson, snapshot)
    assert lesson.steps

    _optimize_and_write_visual_page(
        snapshot=snapshot,
        lesson=lesson,
        debug_dir=RECORDED_LESSON_DEBUG_DIR,
        html_name="heping-ermo-visual-recorded-lesson.html",
    )

    assert not (RECORDED_LESSON_DEBUG_DIR / "explanation").exists()
    assert (RECORDED_LESSON_DEBUG_DIR / "lesson-ir.json").exists()
    assert (RECORDED_LESSON_DEBUG_DIR / "payload.visual.json").exists()
    assert (RECORDED_LESSON_DEBUG_DIR / "heping-ermo-visual-recorded-lesson.html").exists()
    _assert_debug_page_group_titles_have_targets(
        RECORDED_LESSON_DEBUG_DIR,
        html_name="heping-ermo-visual-recorded-lesson.html",
    )


def _solve_heping_ermo_snapshot() -> ExplanationSnapshot:
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    result = orchestrator.solve(load_problem_ir(HEPING_ERMO_FIXTURE))
    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEPING_ERMO_EXPECTED)
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def _build_heping_ermo_lesson_with_deepseek(
    snapshot: ExplanationSnapshot,
    debug_dir: Path,
) -> LessonIR:
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    explanation_debug_dir = debug_dir / "explanation"
    planner = LLMLessonPlanner(
        client=config.build_llm_client(),
        debug_dir=explanation_debug_dir,
        allow_same_problem_few_shot=False,
    )
    lesson = ExplanationBuilder(lesson_planner=planner).build_lesson(snapshot)
    assert planner.last_prompt is not None
    write_explanation_debug_artifacts(
        explanation_debug_dir,
        payload=planner.last_payload or {},
        prompt=planner.last_prompt,
        raw_response=planner.last_raw_response or "",
        parsed=planner.last_parsed,
        lesson=lesson,
    )
    _write_json(debug_dir / "lesson-ir.json", lesson.to_payload())
    return lesson


def _load_recorded_heping_ermo_lesson_ir() -> LessonIR:
    payload = json.loads(HEPING_ERMO_RECORDED_LESSON_IR.read_text(encoding="utf-8"))
    return lesson_ir_from_payload(payload)


def _optimize_and_write_visual_page(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    debug_dir: Path,
    html_name: str,
) -> None:
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    _write_json(debug_dir / "lesson-ir.json", lesson.to_payload())
    _write_json(debug_dir / "visual-step-ir.before-optimization.json", visual_ir.to_payload())
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    optimizer = LLMVisualStepOptimizer(
        client=config.build_llm_client(),
        debug_dir=debug_dir,
    )
    optimized = optimizer.optimize(snapshot=snapshot, lesson=lesson, visual_ir=visual_ir)
    VisualStepIRValidator().validate(optimized)
    _write_json(debug_dir / "visual-step-ir.after-optimization.json", optimized.to_payload())
    compiled = forward_compile(optimized)
    lesson_data = copy.deepcopy(compiled.lesson_data)
    lesson_data["meta"]["outputPath"] = str(debug_dir / html_name)
    _write_compiled_artifacts(
        debug_dir,
        geometry_spec=compiled.geometry_spec,
        step_decorations=compiled.step_decorations,
        lesson_data=lesson_data,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/validate-geometry-spec.mjs"), str(debug_dir)],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        ["node", str(ROOT / "tools/build-lesson-page.mjs"), str(debug_dir)],
        cwd=ROOT,
        check=True,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_compiled_artifacts(
    path: Path,
    *,
    geometry_spec: dict,
    step_decorations: dict,
    lesson_data: dict,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "geometry-spec.json").write_text(
        json.dumps(geometry_spec, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / "step-decorations.json").write_text(
        json.dumps(step_decorations, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / "lesson-data.json").write_text(
        json.dumps(lesson_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _assert_debug_page_group_titles_have_targets(debug_dir: Path, *, html_name: str) -> None:
    lesson_data = json.loads((debug_dir / "lesson-data.json").read_text(encoding="utf-8"))
    group_titles = lesson_data["ui"]["groupTitles"]
    expected = {
        "i_1": "第（Ⅰ）①问：求点 P 和点 A 的坐标",
        "i_2": "第（Ⅰ）②问：求点 E 的坐标",
        "ii": "第（Ⅱ）问：求点 E 的坐标",
    }
    for key, value in expected.items():
        assert group_titles[key] == value
        assert any(step.get("section") == value for step in lesson_data["steps"])
    html = (debug_dir / html_name).read_text(encoding="utf-8")
    for value in expected.values():
        assert value in html


def _assert_debug_page_final_e_box_is_scoped(debug_dir: Path) -> None:
    lesson_data = json.loads((debug_dir / "lesson-data.json").read_text(encoding="utf-8"))
    matching_steps = [
        step
        for step in lesson_data["steps"]
        if "E(－2,3/2)" in json.dumps(step.get("box", ()), ensure_ascii=False).replace(" ", "")
        or "E(-2,3/2)" in json.dumps(step.get("box", ()), ensure_ascii=False).replace(" ", "")
    ]
    assert matching_steps
    final_box = json.dumps(matching_steps[-1].get("box", ()), ensure_ascii=False).replace(" ", "")
    assert "P(" not in final_box
    assert "A(-3,0)" not in final_box
    assert "A(－3,0)" not in final_box
    assert "2+√6" not in final_box
    assert "2＋√6" not in final_box


def _fullwidth_answer_variant(text: str) -> str:
    return (
        str(text)
        .replace("-", "－")
        .replace("+", "＋")
        .replace("=", "＝")
        .replace("或", " 或 ")
    )


def _reset_debug_dir(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)
