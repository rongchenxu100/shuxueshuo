"""河西 25 的 Strategy Planner 竖切测试。

默认测试只使用 recorded executable StepIntent，不访问网络。真实 DeepSeek 联调需显式开启：

    cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
      RUN_DEEPSEEK_HEXI_STRATEGY_PLANNER=1 \
      uv run pytest tests/solver/test_deepseek_strategy_planner_hexi.py -q -s
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from dataclasses import replace
import shutil

import pytest

from shuxueshuo_server.solver.family import QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.strategy_planner import (
    RecipeTrialExecutor,
    StepIntentCandidateResolver,
    StepIntentNormalizer,
    StepIntentValidator,
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    write_strategy_debug_artifacts,
)


RUN_DEEPSEEK_HEXI_STRATEGY_PLANNER = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_STRATEGY_PLANNER") == "1"
    and os.getenv("RUN_DEEPSEEK_HEXI_STRATEGY_PLANNER") == "1"
)
ROOT = Path(__file__).resolve().parents[3]
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
HEXI_LLM_FIXTURE = ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.llm.json"
RECORDED_HEXI_EXECUTABLE_STEP_INTENTS = (
    ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.executable-step-intents.json"
)
DEEPSEEK_HEXI_ATTEMPT_3_STEP_INTENTS = (
    ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.deepseek-attempt-3-step-intents.json"
)
DEEPSEEK_HEXI_RUNTIME_FILL_STEP_INTENTS = (
    ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.deepseek-runtime-fill-step-intents.json"
)
DEBUG_DIR = ROOT / "internal/solver-runs/strategy-planner-deepseek-hexi"
MAX_DEEPSEEK_ATTEMPTS = int(os.getenv("DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS", "3"))


def test_hexi_strategy_probe_uses_weighted_family() -> None:
    """河西 Strategy probe 的 family 仍由 ProblemIR metadata 命中。"""
    problem = load_problem_ir(HEXI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)

    assert inputs.family_spec.family_id == QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id
    assert inputs.family_spec.match.patterns == ("weighted-path-minimum",)
    recipe_ids = {recipe.recipe_id for recipe in inputs.family_spec.step_recipes}
    assert "curve_candidate_parameter_solve" in recipe_ids
    assert "weighted_axis_path_geometric_minimum" not in recipe_ids


def test_hexi_strategy_payload_contains_weighted_capability_catalog() -> None:
    """河西 prompt payload 应只展示 weighted family 的 method/recipe 摘要。"""
    problem = load_problem_ir(HEXI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = _hexi_llm_problem()
    payload = StrategyPayloadBuilder().build(inputs, problem_payload=llm_problem)
    prompt = StrategyPromptRenderer().render(payload)

    method_ids = {
        method["method_id"]
        for method in payload["method_catalog"]["methods"]
    }
    recipe_ids = {
        recipe["recipe_id"]
        for recipe in payload["recipe_catalog"]["recipes"]
    }

    assert "weighted_axis_path_triangle_transform" in method_ids
    assert "linked_broken_path_minimum_expression" in method_ids
    assert "parameter_from_expression_value" in method_ids
    assert "evaluate_expression_at_parameter" in method_ids
    assert "parameter_from_curve_point_on_quadratic" in method_ids
    assert "linked_broken_path_geometric_minimum" not in method_ids
    assert "select_curve_point_candidate_and_solve_coefficients" not in method_ids
    assert "curve_candidate_parameter_solve" in recipe_ids
    assert "right_angle_curve_candidate_solve" not in recipe_ids
    assert "weighted_axis_path_geometric_minimum" not in recipe_ids
    assert "$question" not in prompt.user
    assert "target_path" not in prompt.user
    assert "expected" not in prompt.user


def test_recorded_hexi_step_intents_solve_expected_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """河西 recorded StepIntent 应经 RecipeTrialExecutor 求出题面答案。"""
    # 如果 Strategy 路径意外回退 deterministic Hexi planner，这里会直接失败。
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(AssertionError("deterministic Hexi planner must not run")),
    )
    result, captured = _solve_hexi_from_step_intent_payload(_recorded_hexi_payload())

    assert result.status == "ok", result.errors
    assert result.answers == {
        "i": {"P": ["1", "2"]},
        "ii": {"D": ["sqrt(2)", "1"]},
        "iii": {"b": "2"},
    }
    assert captured["resolution_report"].ok is True
    methods_used = result.methods_used
    assert "weighted_axis_path_triangle_transform" in methods_used
    assert "linked_broken_path_minimum_expression" in methods_used
    assert "parameter_from_expression_value" in methods_used
    methods_by_step = _method_ids_by_step(captured["planner_output"])
    assert methods_by_step["derive_ii_D_candidates"] == [
        "right_angle_equal_length_candidates",
    ]
    assert methods_by_step["solve_ii_D_from_curve_candidate"] == [
        "filter_point_candidates_by_quadratic_curve",
        "parameter_from_curve_point_on_quadratic",
    ]
    assert methods_by_step["transform_iii_weighted_path"] == [
        "weighted_axis_path_triangle_transform",
    ]
    assert methods_by_step["derive_iii_minimum_expression"] == [
        "linked_broken_path_minimum_expression",
    ]
    assert methods_by_step["solve_iii_b_from_expression_value"] == [
        "parameter_from_expression_value",
    ]


def test_deepseek_attempt_3_step_intents_are_normalized_and_solve(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 DeepSeek 第三轮输出应被 normalizer/recipe compiler 吸收并求解。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(AssertionError("deterministic Hexi planner must not run")),
    )
    result, captured = _solve_hexi_from_step_intent_payload(_deepseek_attempt_3_payload())

    assert result.status == "ok", result.errors
    assert result.answers == {
        "i": {"P": ["1", "2"]},
        "ii": {"D": ["sqrt(2)", "1"]},
        "iii": {"b": "2"},
    }
    normalization = captured["normalization_report"]
    assert normalization.changed is False
    methods_by_step = _method_ids_by_step(captured["planner_output"])
    assert methods_by_step["derive_ii_D_candidates"] == [
        "right_angle_equal_length_candidates",
    ]
    assert methods_by_step["solve_ii_D_from_curve_candidate"] == [
        "filter_point_candidates_by_quadratic_curve",
        "parameter_from_curve_point_on_quadratic",
    ]
    assert "solve_b_from_minimum_condition" not in methods_by_step
    assert methods_by_step["transform_weighted_path_iii"] == [
        "weighted_axis_path_triangle_transform",
    ]
    assert methods_by_step["derive_weighted_path_minimum_expression"] == [
        "linked_broken_path_minimum_expression",
    ]
    assert methods_by_step["solve_b_from_expression_value"] == [
        "parameter_from_expression_value",
    ]


def test_hexi_compiler_fills_vertex_parabola(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少显式顶点前置抛物线时，代码层应确定性补位。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(AssertionError("deterministic Hexi planner must not run")),
    )
    payload = _deepseek_attempt_3_payload_without_explicit_vertex_parabola()
    result, captured = _solve_hexi_from_step_intent_payload(payload)

    assert result.status == "ok", result.errors
    assert result.answers == {
        "i": {"P": ["1", "2"]},
        "ii": {"D": ["sqrt(2)", "1"]},
        "iii": {"b": "2"},
    }
    methods_by_step = _method_ids_by_step(captured["planner_output"])
    assert methods_by_step["compute_vertex_i"] == [
        "quadratic_from_constraints",
        "quadratic_vertex_point",
    ]
    assert any(
        declaration.path == "$question.iii.points.Aux"
        for declaration in captured["planner_output"].context_declarations
    )


def test_deepseek_runtime_fill_step_intents_solve(monkeypatch: pytest.MonkeyPatch) -> None:
    """最新真实输出形态应由代码补齐顶点、系数复用和 weighted 辅助点。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(AssertionError("deterministic Hexi planner must not run")),
    )
    result, captured = _solve_hexi_from_step_intent_payload(_deepseek_runtime_fill_payload())

    assert result.status == "ok", result.errors
    assert result.answers == {
        "i": {"P": ["1", "2"]},
        "ii": {"D": ["sqrt(2)", "1"]},
        "iii": {"b": "2"},
    }
    methods_by_step = _method_ids_by_step(captured["planner_output"])
    assert methods_by_step["derive_vertex_i"] == ["quadratic_vertex_point"]
    assert methods_by_step["derive_ii_D_candidates"] == [
        "right_angle_equal_length_candidates",
    ]
    assert methods_by_step["solve_ii_D_from_curve_candidate"] == [
        "filter_point_candidates_by_quadratic_curve",
        "parameter_from_curve_point_on_quadratic",
    ]
    assert methods_by_step["transform_iii_weighted_path"] == [
        "weighted_axis_path_triangle_transform",
    ]
    assert methods_by_step["derive_iii_minimum_expression"] == [
        "linked_broken_path_minimum_expression",
    ]
    assert methods_by_step["solve_iii_b_from_expression_value"] == [
        "parameter_from_expression_value",
    ]
    assert any(
        declaration.path == "$question.iii.points.Aux"
        for declaration in captured["planner_output"].context_declarations
    )


def test_hexi_weighted_transform_companion_outputs_are_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """weighted 转化 step 即使未显式 produces 轨迹线，也应注册 method 伴随输出。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(AssertionError("deterministic Hexi planner must not run")),
    )
    payload = _hexi_payload_without_explicit_auxiliary_locus()
    result, captured = _solve_hexi_from_step_intent_payload(payload)

    assert result.status == "ok", result.errors
    assert result.answers == {
        "i": {"P": ["1", "2"]},
        "ii": {"D": ["sqrt(2)", "1"]},
        "iii": {"b": "2"},
    }
    transform_plan = next(
        step
        for step in captured["planner_output"].step_plans
        if step.step_id == "transform_iii_weighted_path"
    )
    assert "$step.transform_iii_weighted_path.temp.auxiliary_locus" in transform_plan.promote_outputs


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEXI_STRATEGY_PLANNER,
    reason="DeepSeek strategy planner integration is opt-in",
)
def test_deepseek_strategy_planner_hexi_full_loop() -> None:
    """真实 DeepSeek 输出 StepIntent 后，必须完整执行出河西答案。"""
    problem = load_problem_ir(HEXI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = _hexi_llm_problem()
    handle_registry = CanonicalHandleRegistry.from_problem_payload(llm_problem)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="llm",
        llm_provider="deepseek",
    )
    client = config.build_llm_client()
    previous_attempts: list[str] = []
    last_result = None
    _reset_debug_dir(DEBUG_DIR)

    for attempt_index in range(1, MAX_DEEPSEEK_ATTEMPTS + 1):
        current_inputs = replace(inputs, previous_errors=list(previous_attempts))
        payload = StrategyPayloadBuilder().build(
            current_inputs,
            problem_payload=llm_problem,
        )
        prompt = StrategyPromptRenderer().render(payload)
        raw_response = client.complete(
            {
                "messages": [
                    {"role": "system", "content": prompt.system},
                    {"role": "user", "content": prompt.user},
                ],
                "family_id": current_inputs.family_spec.family_id,
                "planner_payload": payload,
            }
        )
        draft, report = StepIntentValidator().validate_json_with_report(
            raw_response,
            question_goals=current_inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=current_inputs.family_spec,
        )
        normalization_report = None
        if draft is not None:
            draft, normalization_report = StepIntentNormalizer().normalize(
                draft,
                family_spec=current_inputs.family_spec,
                question_goals=current_inputs.question_goals,
                handle_registry=handle_registry,
            )
        resolution_report = (
            StepIntentCandidateResolver().resolve(
                draft,
                family_spec=current_inputs.family_spec,
                method_specs=current_inputs.method_specs,
                handle_registry=handle_registry,
            )
            if draft is not None
            else None
        )
        attempt_dir = DEBUG_DIR / f"attempt-{attempt_index}"
        write_strategy_debug_artifacts(
            attempt_dir,
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            report=report,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            llm_metadata={
                "attempt": attempt_index,
                "configured_model": config.llm_model or config.deepseek_model,
                "response_model": getattr(client, "last_response_model", None),
                "usage": getattr(client, "last_usage", None),
            },
        )
        if draft is None:
            previous_attempts = list(report.errors)
            continue
        try:
            result, _captured = _solve_hexi_from_step_intent_payload(draft.to_payload())
        except Exception as exc:  # pragma: no cover - opt-in debug path
            previous_attempts = [f"execution_failed: {exc}"]
            continue
        last_result = result
        if result.status == "ok" and result.answers == {
            "i": {"P": ["1", "2"]},
            "ii": {"D": ["sqrt(2)", "1"]},
            "iii": {"b": "2"},
        }:
            print(f"DeepSeek Hexi strategy solved in attempt {attempt_index}/{MAX_DEEPSEEK_ATTEMPTS}")
            print(json.dumps(result.answers, ensure_ascii=False, indent=2))
            return
        previous_attempts = [f"solver_status: {result.status}", *map(str, result.errors)]

    raise AssertionError(f"DeepSeek Hexi strategy did not solve; last_result={last_result}")


def _solve_hexi_from_step_intent_payload(step_intent_payload: dict):
    """把河西 StepIntent payload 接入 RuntimeOrchestrator。"""
    llm_problem = _hexi_llm_problem()
    handle_registry = CanonicalHandleRegistry.from_problem_payload(llm_problem)
    problem = load_problem_ir(HEXI_FIXTURE)
    captured = {}

    def provider(context):
        class StepIntentGatedHexiPlanner:
            def plan(self, inputs):
                draft = StepIntentValidator().validate(
                    step_intent_payload,
                    question_goals=inputs.question_goals,
                    handle_registry=handle_registry,
                    family_spec=inputs.family_spec,
                )
                draft, normalization_report = StepIntentNormalizer().normalize(
                    draft,
                    family_spec=inputs.family_spec,
                    question_goals=inputs.question_goals,
                    handle_registry=handle_registry,
                )
                resolution_report = StepIntentCandidateResolver().resolve(
                    draft,
                    family_spec=inputs.family_spec,
                    method_specs=inputs.method_specs,
                    handle_registry=handle_registry,
                )
                captured["draft"] = draft
                captured["normalization_report"] = normalization_report
                captured["resolution_report"] = resolution_report
                planner_output = RecipeTrialExecutor().compile(
                    draft,
                    family_spec=inputs.family_spec,
                    method_specs=inputs.method_specs,
                    handle_registry=handle_registry,
                    context=context,
                    question_goals=inputs.question_goals,
                )
                captured["planner_output"] = planner_output
                return planner_output

        return StepIntentGatedHexiPlanner()

    result = RuntimeOrchestrator(
        planner_providers={QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id: provider},
    ).solve(problem)
    return result, captured


def _hexi_llm_problem() -> dict:
    """读取河西 LLM ProblemIR。"""
    return json.loads(HEXI_LLM_FIXTURE.read_text(encoding="utf-8"))


def _reset_debug_dir(path: Path) -> None:
    """真实 LLM 测试开始前清空 debug 目录，避免旧 attempt 混入本轮结果。"""
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _recorded_hexi_payload() -> dict:
    """读取 recorded executable StepIntent。"""
    return json.loads(RECORDED_HEXI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))


def _deepseek_attempt_3_payload() -> dict:
    """读取固定的真实 DeepSeek attempt-3 StepIntent。"""
    return json.loads(DEEPSEEK_HEXI_ATTEMPT_3_STEP_INTENTS.read_text(encoding="utf-8"))


def _deepseek_runtime_fill_payload() -> dict:
    """读取固定的真实 DeepSeek runtime-fill StepIntent。"""
    return json.loads(DEEPSEEK_HEXI_RUNTIME_FILL_STEP_INTENTS.read_text(encoding="utf-8"))


def _deepseek_attempt_3_payload_without_explicit_vertex_parabola() -> dict:
    """构造缺少顶点可补位 utility step 的 attempt-3 变体。"""
    payload = deepcopy(_deepseek_attempt_3_payload())
    for scope in payload["scopes"]:
        if scope["scope_id"] == "i":
            scope["steps"] = [
                step
                for step in scope["steps"]
                if step["step_id"] != "derive_parabola_i"
            ]
            for step in scope["steps"]:
                if step["step_id"] == "compute_vertex_i":
                    step["reads"] = [
                        "function:problem:parabola",
                        "fact:i:a_value",
                        "fact:i:b_value",
                        "fact:i:c_value",
                    ]
    return payload


def _hexi_payload_without_explicit_auxiliary_locus() -> dict:
    """构造 DeepSeek 常见变体：只表达路径转化，不显式暴露辅助点轨迹线。"""
    payload = deepcopy(_recorded_hexi_payload())
    for scope in payload["scopes"]:
        if scope["scope_id"] != "iii":
            continue
        for step in scope["steps"]:
            if step["step_id"] == "transform_iii_weighted_path":
                step["produces"] = [
                    produced
                    for produced in step["produces"]
                    if produced["handle"] != "fact:iii:auxiliary_locus"
                ]
            if step["step_id"] == "derive_iii_minimum_expression":
                step["reads"] = [
                    handle
                    for handle in step["reads"]
                    if handle != "fact:iii:auxiliary_locus"
                ]
    return payload


def _method_ids_by_step(planner_output) -> dict[str, list[str]]:
    """按 step_id 汇总实际 method 调用。"""
    return {
        step.step_id: [invocation.method_id for invocation in step.invocations]
        for step in planner_output.step_plans
    }
