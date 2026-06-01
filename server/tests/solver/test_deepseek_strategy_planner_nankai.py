"""真实 DeepSeek StepIntent 输出校验。

默认跳过。需要本地 ``server/.env`` 配置 DeepSeek，并显式开启：

    cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
      uv run pytest tests/solver/test_deepseek_strategy_planner_nankai.py -q -s
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil

import pytest
import sympy as sp

from shuxueshuo_server.solver import load_expected_answers
from shuxueshuo_server.solver.family import QUADRATIC_PATH_MINIMUM_FAMILY
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    RecipeTrialExecutor,
    StepIntentValidator,
    StepIntentDraft,
    StepIntentValidationReport,
    StepIntentCandidateResolver,
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    write_strategy_debug_artifacts,
)


RUN_DEEPSEEK_STRATEGY_PLANNER = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_STRATEGY_PLANNER") == "1"
)
NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"
NANKAI_LLM_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-fixtures"
    / "tj-2026-nankai-yimo-25.llm.json"
)
RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-fixtures"
    / "tj-2026-nankai-yimo-25.executable-step-intents.json"
)
DEFAULT_DEBUG_DIR = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-runs"
    / "strategy-planner-deepseek-nankai"
)
MAX_DEEPSEEK_ATTEMPTS = int(os.getenv("DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS", "3"))
EXPECTED_RECIPE_IDS = {
    "right_angle_equal_length_construct_and_select",
    "two_moving_points_path_reduction",
    "broken_path_straightening_and_select",
    "path_minimum_by_straightened_distance",
}


def test_recorded_strategy_step_intents_gate_code_solved_nankai_result(
    tmp_path: Path,
) -> None:
    """用固定 StepIntent fixture 作为输入，跑出代码验算答案。

    这是 Strategy Planner 到 Method Solver 的第一条集成桥：测试要求 StepIntent
    能通过 canonical handle、recipe alignment 和 executable candidate 解析，再由
    RecipeTrialExecutor 直接编译成 PlannerOutput。这里不再调用南开 deterministic
    template，也不依赖 solver-runs 里的某次 DeepSeek 调试输出。
    """
    step_intent_payload = json.loads(
        RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8")
    )
    result, captured = _solve_nankai_from_step_intent_payload(step_intent_payload)
    expected = load_expected_answers(NANKAI_EXPECTED)

    result_path = tmp_path / "nankai-solved-from-recorded-step-intents.json"
    result_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    _assert_nankai_result_matches_expected(result, expected)
    assert captured["resolution_report"].ok is True
    assert len(captured["draft"].steps) >= 10


def test_execution_feedback_reports_missing_midpoint_step() -> None:
    """缺少 F 中点求解 step 时，应生成可回传给 LLM 的执行反馈。

    这个测试模拟真实 DeepSeek 失败形态：后续路径最值步骤读取了 F 的坐标，
    但 StepIntent 里没有 ``midpoint_point``。此时策略层的 JSON 可能看起来
    合法，但 runtime 不能执行，loop 必须把缺失能力反馈回下一轮。
    """
    step_intent_payload = json.loads(
        RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8")
    )
    broken_payload = _without_recipe_hint(step_intent_payload, "midpoint_point")
    expected = load_expected_answers(NANKAI_EXPECTED)

    failures, result, _captured = _execution_failures_from_step_intent_payload(
        broken_payload,
        expected,
    )

    assert result.status == "failed"
    assert any("missing_capability: midpoint_point" in failure for failure in failures)
    assert any("fact:ii:F_coordinate_expr" in failure for failure in failures)


def test_recorded_strategy_step_intents_allow_descriptive_auxiliary_point_name() -> None:
    """辅助点不应强依赖 Aux 固定命名，DeepSeek 常会写 Aux_symmetric_D。"""
    step_intent_payload = json.loads(
        RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8")
    )
    renamed_payload = _replace_string_values(
        step_intent_payload,
        "point:ii:Aux",
        "point:ii:Aux_symmetric_D",
    )
    result, _captured = _solve_nankai_from_step_intent_payload(renamed_payload)

    _assert_nankai_result_matches_expected(
        result,
        load_expected_answers(NANKAI_EXPECTED),
    )


def test_execution_feedback_summarizes_missing_distance_points() -> None:
    """距离端点缺失时，previous_attempts 应得到短错误码和补充建议。"""
    error = (
        "recipe_trial_step_failed: step=compute_minimum_expr, "
        "errors=['path_minimum_by_straightened_distance: "
        "distance_points_not_found: compute_minimum_expr']"
    )

    assert _short_execution_error(error) == (
        "execution_failed: recipe_trial_step_failed:compute_minimum_expr"
    )
    hints = _execution_error_hints(error)
    assert any("missing_required_runtime_fact: distance_points" in hint for hint in hints)


def test_execution_feedback_summarizes_duplicate_fact_scope_errors() -> None:
    """重复 fact / valid_scope 错误应压成 LLM 能直接修复的提示。"""
    error = (
        "recipe_trial_step_failed: step=derive_F, errors=['midpoint_point: "
        "duplicate_point_coordinate_fact: signature=point_coordinate:F'] "
        "common_fact_after_narrow_fact invalid_valid_scope"
    )

    hints = _execution_error_hints(error)

    assert any("duplicate_point_coordinate_fact" in hint for hint in hints)
    assert any("common_fact_after_narrow_fact" in hint for hint in hints)
    assert any("invalid_valid_scope" in hint for hint in hints)


def test_execution_feedback_summarizes_missing_minimum_expression() -> None:
    """缺少公共最小值表达式时，应提示不要读取 sibling 的最终答案。"""
    error = (
        "recipe_trial_step_failed: step=solve_m_from_minimum, errors=["
        "'parameter_from_minimum_value: missing_required_runtime_fact: minimum_expression; "
        "path $subquestion.ii_1.outputs.min_value is not visible from scope solve_m_from_minimum']"
    )

    assert _short_execution_error(error) == (
        "execution_failed: recipe_trial_step_failed:solve_m_from_minimum"
    )
    hints = _execution_error_hints(error)
    assert any("missing_required_runtime_fact: minimum_expression" in hint for hint in hints)
    assert any("sibling_scope_output_not_visible" in hint for hint in hints)
    assert any("fact:ii:path_minimum_expression" in hint for hint in hints)


def _replace_string_values(value, old: str, new: str):
    """递归替换测试 payload 中的字符串值。"""
    if isinstance(value, str):
        return new if value == old else value
    if isinstance(value, list):
        return [_replace_string_values(item, old, new) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_string_values(item, old, new)
            for key, item in value.items()
        }
    return value


def _without_recipe_hint(payload: dict, recipe_hint: str) -> dict:
    """返回删除指定 recipe_hint step 后的新 payload，避免测试污染 fixture。"""
    cloned = deepcopy(payload)
    for scope in cloned.get("scopes", []):
        scope["steps"] = [
            step
            for step in scope.get("steps", [])
            if step.get("recipe_hint") != recipe_hint
        ]
    return cloned


def _solve_nankai_from_step_intent_payload(step_intent_payload: dict):
    """把 StepIntent payload 接入 RuntimeOrchestrator 并返回 SolverResult。"""
    llm_problem = json.loads(NANKAI_LLM_FIXTURE.read_text(encoding="utf-8"))
    handle_registry = CanonicalHandleRegistry.from_problem_payload(llm_problem)
    problem = load_problem_ir(NANKAI_FIXTURE)

    captured = {}

    def provider(context):
        class StepIntentGatedNankaiPlanner:
            def plan(self, inputs):
                draft = StepIntentValidator().validate(
                    step_intent_payload,
                    question_goals=inputs.question_goals,
                    handle_registry=handle_registry,
                    family_spec=inputs.family_spec,
                )
                resolution_report = StepIntentCandidateResolver().resolve(
                    draft,
                    family_spec=inputs.family_spec,
                    method_specs=inputs.method_specs,
                    handle_registry=handle_registry,
                )
                captured["draft"] = draft
                captured["resolution_report"] = resolution_report
                _assert_strategy_attempt_can_gate_runtime(resolution_report)
                return RecipeTrialExecutor().compile(
                    draft,
                    family_spec=inputs.family_spec,
                    method_specs=inputs.method_specs,
                    handle_registry=handle_registry,
                    context=context,
                    question_goals=inputs.question_goals,
                )

        return StepIntentGatedNankaiPlanner()

    result = RuntimeOrchestrator(
        planner_providers={QUADRATIC_PATH_MINIMUM_FAMILY.family_id: provider},
    ).solve(problem)

    return result, captured


def _assert_nankai_result_matches_expected(result, expected: dict) -> None:
    """断言 Strategy path 求出的南开答案与 expected JSON 等价。"""
    assert result.status == "ok", result.errors
    assert all(check.ok for check in result.checks)
    assert result.answers["i"]["D"] == expected["i"]["D"]
    assert (
        sp.simplify(
            sp.sympify(result.answers["i"]["parabola"])
            - sp.sympify(expected["i"]["parabola"])
        )
        == 0
    )
    assert (
        sp.simplify(
            sp.sympify(result.answers["ii_1"]["parabola"])
            - sp.sympify(expected["ii_1"]["parabola"])
        )
        == 0
    )
    assert result.answers["ii_1"]["min_value"] == expected["ii_1"]["min_value"]
    assert (
        sp.simplify(
            sp.sympify(result.answers["ii_2"]["parabola"])
            - sp.sympify(expected["ii_2"]["parabola"])
        )
        == 0
    )
    assert result.answers["ii_2"]["G"] == expected["ii_2"]["G"]


def _execution_failures_from_step_intent_payload(
    step_intent_payload: dict,
    expected: dict,
):
    """执行 StepIntent payload，并返回可写入 previous_attempts 的失败摘要。"""
    result, captured = _solve_nankai_from_step_intent_payload(step_intent_payload)
    return _solver_result_failures(result, expected, captured), result, captured


def _solver_result_failures(result, expected: dict, captured: dict) -> list[str]:
    """把 runtime 执行结果压缩成 LLM repair 能理解的错误。

    这里刻意使用 StepIntent 的语义语言，比如 missing_capability 和 canonical
    handle，而不是 Python traceback 或 ContextPath。下一轮 LLM 看到这些错误后，
    应补齐对应推导步骤。
    """
    failures: list[str] = []
    failures.extend(_runtime_gate_failures(captured.get("resolution_report")))
    if result.status != "ok":
        failures.append(f"solver_status: {result.status}")
    for error in result.errors:
        failures.append(_short_execution_error(str(error)))
        failures.extend(_execution_error_hints(str(error)))
    for check in result.checks:
        if not check.ok:
            failures.append(f"check_failed: {check.name}")
    if result.status == "ok":
        failures.extend(_answer_mismatch_failures(result.answers, expected))
    return _dedupe(failures)


def _execution_error_hints(error: str) -> list[str]:
    """把底层错误翻译成更接近 StepIntent 的修复建议。"""
    hints: list[str] = []
    if "missing_required_runtime_fact: minimum_expression" in error:
        hints.extend(
            [
                "missing_required_runtime_fact: minimum_expression",
                (
                    "add_or_read_common_minimum_expression_fact before parameter_from_minimum_value; "
                    "ii_2 cannot read ii_1.minimum_value. The path minimum step should produce "
                    "a parent-scope MinimumExpression fact such as fact:ii:path_minimum_expression, "
                    "and solve_m_from_minimum should read that fact plus fact:ii_2:path_minimum_value_given."
                ),
            ]
        )
    if "ii_1.outputs.min_value" in error or "$subquestion.ii_1.outputs.min_value" in error:
        hints.append(
            "sibling_scope_output_not_visible: ii_1.minimum_value; do not use a sibling final "
            "answer as the minimum expression for ii_2."
        )
    if "fact:ii:F_coordinate_expr" in error:
        hints.extend(
            [
                "missing_capability: midpoint_point",
                (
                    "missing_required_runtime_fact: fact:ii:F_coordinate_expr; "
                    "later path-minimum steps read point:ii:F / fact:ii:F_midpoint_of_DN, "
                    "but no midpoint_point step produced F's coordinate. Add a step before "
                    "path reduction that reads point:problem:D, fact:problem:D_coordinate, "
                    "point:ii:N, fact:ii:N_coordinate_expr and fact:ii:F_midpoint_of_DN, "
                    "then produces fact:ii:F_coordinate_expr."
                ),
            ]
        )
    if "expected PointRef, got Point" in error:
        hints.append(
            "capability_input_type_mismatch: a construction recipe/method expected an "
            "unresolved target PointRef, but the referenced point has already become a "
            "computed Point. Do not call right_angle_equal_length_construct_and_select "
            "again just to substitute a parameter value. If a previous step has already "
            "produced a coordinate-expression fact for that point, later steps should read "
            "that fact plus the parameter value; only use midpoint/parameter/quadratic/"
            "distance methods for the next mathematical action."
        )
    if "duplicate_point_coordinate_fact" in error:
        hints.append(
            "duplicate_point_coordinate_fact: the plan tries to derive an entity coordinate "
            "or equivalent fact more than once. Remove the later duplicate step and let later "
            "steps read the existing fact."
        )
    if "common_fact_after_narrow_fact" in error:
        hints.append(
            "common_fact_after_narrow_fact: a narrow subquestion fact was produced before a "
            "broader reusable fact for the same conclusion. Produce the broader common fact "
            "first with the correct valid_scope, then let subquestions read it."
        )
    if "invalid_valid_scope" in error:
        hints.append(
            "invalid_valid_scope: a produced fact claims a broader valid_scope than its reads "
            "support. If it reads child-only facts, shrink valid_scope; if it should be common, "
            "derive it from parent-scope facts only."
        )
    if "output_type_not_supported" in error:
        hints.append(
            "capability_output_type_mismatch: recipe_hint and produces do not match. "
            "Keep one step aligned to one recipe/method, or change produces to the "
            "fact/answer type supported by that capability."
        )
    if "distance_points_not_found" in error:
        hints.append(
            "missing_required_runtime_fact: distance_points; distance/minimum step needs "
            "a readable auxiliary or straightening point plus the other computed endpoint "
            "point, usually midpoint F with its coordinate fact. Add the missing reads or "
            "ensure earlier straightening/midpoint steps produce those handles."
        )
    return hints


def _short_execution_error(error: str) -> str:
    """把 runtime/pytest 错误压成 previous_attempts 可读的一行。"""
    if "recipe_trial_step_failed" in error:
        match = re.search(r"step=([^,\s]+)", error)
        step_id = match.group(1) if match else "unknown"
        return f"execution_failed: recipe_trial_step_failed:{step_id}"
    if "unknown_read_handle" in error:
        match = re.search(r"handle=([^,\s]+)", error)
        handle = match.group(1) if match else "unknown"
        return f"execution_failed: unknown_read_handle:{handle}"
    if "missing_capability:" in error:
        match = re.search(r"missing_capability: ([A-Za-z0-9_]+)", error)
        if match:
            return f"execution_failed: missing_capability:{match.group(1)}"
    return "execution_failed: " + error[:500]


def _answer_mismatch_failures(actual_answers: dict, expected: dict) -> list[str]:
    """返回答案差异；测试 gate 使用 expected，但不会把 expected 写进 prompt。"""
    failures: list[str] = []
    for question_id, expected_group in expected.items():
        actual_group = actual_answers.get(question_id)
        if not isinstance(actual_group, dict):
            failures.append(f"missing_answer_group: {question_id}")
            continue
        for key, expected_value in expected_group.items():
            if key not in actual_group:
                failures.append(f"missing_answer: {question_id}.{key}")
                continue
            actual_value = actual_group[key]
            if not _answer_value_equal(actual_value, expected_value):
                failures.append(
                    "answer_mismatch: "
                    f"{question_id}.{key}; actual={actual_value}; expected={expected_value}"
                )
    return failures


def _answer_value_equal(actual, expected) -> bool:
    """用 SymPy 等价判断表达式，其余 JSON 值保持精确比较。"""
    if actual == expected:
        return True
    if isinstance(actual, str) and isinstance(expected, str):
        try:
            return sp.simplify(sp.sympify(actual) - sp.sympify(expected)) == 0
        except Exception:
            return False
    return False


def _dedupe(items: list[str]) -> list[str]:
    """保持顺序去重，避免 previous_attempts 里重复刷屏。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


@pytest.mark.skipif(
    not RUN_DEEPSEEK_STRATEGY_PLANNER,
    reason="set RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 to call DeepSeek",
)
def test_deepseek_strategy_planner_outputs_valid_step_intents_and_solves_nankai() -> None:
    """DeepSeek 应输出合法 StepIntent[]，并经代码执行得到南开答案。"""
    config = SolverRuntimeConfig.from_sources(
        planner_mode="llm",
        llm_provider="deepseek",
    )
    if not config.deepseek_api_key:
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    configured_model = config.llm_model or config.deepseek_model
    client = config.build_llm_client()

    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = json.loads(NANKAI_LLM_FIXTURE.read_text(encoding="utf-8"))
    handle_registry = CanonicalHandleRegistry.from_problem_payload(llm_problem)
    debug_dir = Path(
        os.getenv("STRATEGY_PLANNER_DEBUG_DIR")
        or config.llm_debug_dir
        or DEFAULT_DEBUG_DIR
    )
    for old_attempt_dir in debug_dir.glob("attempt-*"):
        if old_attempt_dir.is_dir():
            shutil.rmtree(old_attempt_dir)

    previous_attempts: list[dict[str, object]] = []
    attempt_summaries: list[dict[str, object]] = []
    final_payload: dict[str, object] | None = None
    final_prompt = None
    final_raw = ""
    final_draft: StepIntentDraft | None = None
    final_report: StepIntentValidationReport | None = None
    final_resolution_report = None
    final_metadata: dict[str, object] | None = None
    final_failures: list[str] = []
    final_result = None
    final_captured: dict | None = None
    expected = load_expected_answers(NANKAI_EXPECTED)

    for attempt in range(1, MAX_DEEPSEEK_ATTEMPTS + 1):
        attempt_inputs = replace(inputs, previous_errors=list(previous_attempts))
        payload = StrategyPayloadBuilder().build(
            attempt_inputs,
            problem_payload=llm_problem,
        )
        prompt = StrategyPromptRenderer().render(payload)
        raw = client.complete(
            {
                "messages": prompt.messages,
                "family_id": inputs.family_spec.family_id,
                "problem_id": inputs.problem_id,
                "planner_payload": payload,
            }
        )
        draft, report = StepIntentValidator().validate_json_with_report(
            raw,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
        resolution_report = (
            StepIntentCandidateResolver().resolve(
                draft,
                family_spec=inputs.family_spec,
                method_specs=inputs.method_specs,
                handle_registry=handle_registry,
            )
            if draft is not None
            else None
        )
        failures = _strategy_acceptance_failures(draft, report, resolution_report)
        execution_failures: list[str] = []
        solver_result = None
        solver_captured: dict | None = None
        if not failures and draft is not None:
            execution_failures, solver_result, solver_captured = (
                _execution_failures_from_step_intent_payload(
                    draft.to_payload(),
                    expected,
                )
            )
            failures.extend(execution_failures)
        metadata = {
            "provider": "deepseek",
            "configured_model": configured_model,
            "response_model": getattr(client, "last_response_model", None),
            "usage": getattr(client, "last_usage", None),
            "attempt": attempt,
            "max_attempts": MAX_DEEPSEEK_ATTEMPTS,
        }
        write_strategy_debug_artifacts(
            debug_dir / f"attempt-{attempt}",
            payload=payload,
            prompt=prompt,
            raw_response=raw,
            draft=draft,
            report=report,
            resolution_report=resolution_report,
            llm_metadata=metadata,
        )
        _write_execution_debug_artifacts(
            debug_dir / f"attempt-{attempt}",
            result=solver_result,
            execution_failures=execution_failures,
        )
        attempt_summary = {
            "attempt": attempt,
            "ok": not failures,
            "failures": failures,
            "execution_failures": execution_failures,
            "solver_status": solver_result.status if solver_result is not None else None,
            "validation_report": report.to_payload(),
            "candidate_resolution_report": (
                resolution_report.to_payload()
                if resolution_report is not None
                else None
            ),
            "response_model": metadata["response_model"],
            "usage": metadata["usage"],
            "raw_preview": raw[:1200],
        }
        attempt_summaries.append(attempt_summary)

        final_payload = payload
        final_prompt = prompt
        final_raw = raw
        final_draft = draft
        final_report = report
        final_resolution_report = resolution_report
        final_metadata = metadata
        final_failures = failures
        final_result = solver_result
        final_captured = solver_captured
        if not failures:
            break
        previous_attempts.append(
            {
                "attempt": attempt,
                "errors": failures,
                "execution_failures": execution_failures,
                "validation_report": report.to_payload(),
                "candidate_resolution_report": (
                    resolution_report.to_payload()
                    if resolution_report is not None
                    else None
                ),
                "solver_result": (
                    _solver_result_summary(solver_result)
                    if solver_result is not None
                    else None
                ),
                "raw_preview": raw[:2000],
            }
        )

    assert final_payload is not None
    assert final_prompt is not None
    assert final_report is not None
    assert final_metadata is not None
    write_strategy_debug_artifacts(
        debug_dir,
        payload=final_payload,
        prompt=final_prompt,
        raw_response=final_raw,
        draft=final_draft,
        report=final_report,
        resolution_report=final_resolution_report,
        llm_metadata={
            **final_metadata,
            "attempt_summaries": attempt_summaries,
        },
    )
    _write_execution_debug_artifacts(
        debug_dir,
        result=final_result,
        execution_failures=final_failures,
    )
    (debug_dir / "loop-summary.json").write_text(
        json.dumps(attempt_summaries, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    raw_preview = final_raw[:1200].replace("\n", "\\n")
    print(
        "\n"
        "DeepSeek Strategy Planner probe\n"
        f"configured_model={configured_model}\n"
        f"attempts={len(attempt_summaries)}/{MAX_DEEPSEEK_ATTEMPTS}\n"
        f"response_model={final_metadata['response_model']}\n"
        f"usage={json.dumps(final_metadata['usage'], ensure_ascii=False, sort_keys=True)}\n"
        f"debug_dir={debug_dir}\n"
        f"final_failures={json.dumps(final_failures, ensure_ascii=False)}\n"
        f"raw_preview={raw_preview}"
    )
    assert not final_failures, {
        "attempt_summaries": attempt_summaries,
        "final_report": final_report.to_payload(),
    }
    assert final_draft is not None
    assert final_result is not None
    assert final_captured is not None
    result = final_result
    captured = final_captured
    _assert_nankai_result_matches_expected(result, expected)
    (debug_dir / "solved-result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "DeepSeek Strategy Planner solved Nankai result\n"
        f"steps={len(captured['draft'].steps)}\n"
        f"methods_used={json.dumps(result.methods_used, ensure_ascii=False)}\n"
        f"result_path={debug_dir / 'solved-result.json'}"
    )


def _assert_strategy_attempt_can_gate_runtime(resolution_report) -> None:
    """确认 StepIntent 已经覆盖南开 runtime 需要的关键能力。"""
    failures = _runtime_gate_failures(resolution_report)
    if failures:
        raise AssertionError("; ".join(failures))


def _runtime_gate_failures(resolution_report) -> list[str]:
    """返回 Strategy 结果进入 runtime 前缺失的关键能力。

    这些错误会被喂回 DeepSeek。尤其是 ``midpoint_point``：策略层可能只在
    reads 中引用 F，却没有给出求 F 坐标的 step；runtime 必须明确指出需要补
    一个中点求解动作。
    """
    if resolution_report is None:
        return ["candidate_resolution_report_missing"]
    failures: list[str] = []
    if not resolution_report.ok:
        failures.append(
            "executable_resolution_errors:"
            + json.dumps(resolution_report.errors, ensure_ascii=False, sort_keys=True)
        )
    selected = {
        report.selected_capability_id
        for report in resolution_report.step_reports
        if report.selected_capability_id
    }
    required = {
        "quadratic_axis_from_relation",
        "quadratic_from_constraints",
        "right_angle_equal_length_construct_and_select",
        "midpoint_point",
        "two_moving_points_path_reduction",
        "broken_path_straightening_and_select",
        "parameter_from_segment_length",
        "parameter_from_minimum_value",
        "line_intersection_point",
    }
    missing = sorted(required - selected)
    failures.extend(f"missing_capability: {capability}" for capability in missing)
    if "midpoint_point" in missing:
        failures.append(
            "missing_required_runtime_fact: fact:ii:F_coordinate_expr; "
            "later path-minimum steps read point:ii:F / fact:ii:F_midpoint_of_DN, "
            "but no midpoint_point step produced F's coordinate. Add a step before "
            "path reduction that reads point:problem:D, fact:problem:D_coordinate, "
            "point:ii:N, fact:ii:N_coordinate_expr and fact:ii:F_midpoint_of_DN, "
            "then produces fact:ii:F_coordinate_expr."
        )
    return failures


def _write_execution_debug_artifacts(
    target_dir: Path,
    *,
    result,
    execution_failures: list[str],
) -> None:
    """给每轮 attempt 额外写 runtime 执行结果，便于看 LLM loop 为什么没过。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    if result is not None:
        (target_dir / "solver-result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    error_path = target_dir / "execution-error.json"
    if execution_failures:
        error_path.write_text(
            json.dumps(
                {
                    "execution_failures": execution_failures,
                    "solver_result": (
                        _solver_result_summary(result) if result is not None else None
                    ),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    elif error_path.exists():
        error_path.unlink()


def _solver_result_summary(result) -> dict[str, object]:
    """只保留可发给 LLM 的安全执行摘要，不包含 traceback 或 expected answer。"""
    return {
        "status": result.status,
        "solver_family": result.solver_family,
        "methods_used": list(result.methods_used),
        "errors": list(result.errors),
        "failed_checks": [check.name for check in result.checks if not check.ok],
    }


def _strategy_acceptance_failures(
    draft: StepIntentDraft | None,
    report: StepIntentValidationReport,
    resolution_report,
) -> list[str]:
    """把 validator report 和 recipe alignment 转成可回传给 LLM 的错误列表。"""
    failures: list[str] = []
    if not report.ok:
        failures.extend(report.errors or ("validation_report_not_ok",))
        failures.extend(f"missing_goal:{goal}" for goal in report.missing_goals)
        return failures
    if draft is None:
        return ["draft_missing_after_validation"]
    if len(draft.steps) < 3:
        failures.append(f"too_few_steps:{len(draft.steps)}")
    alignment = report.recipe_alignment
    if alignment is None:
        failures.append("recipe_alignment_missing")
        return failures
    if alignment.non_empty_hint_count < max(1, len(draft.steps) // 2):
        failures.append(
            "too_few_recipe_hints:"
            f"{alignment.non_empty_hint_count}/{len(draft.steps)}"
        )
    if alignment.matched_hint_count < 3:
        failures.append(f"too_few_matched_hints:{alignment.matched_hint_count}")
    missing_recipes = sorted(EXPECTED_RECIPE_IDS - set(alignment.matched_recipes))
    if missing_recipes:
        failures.append("missing_expected_recipes:" + ",".join(missing_recipes))
    if alignment.avoid_pattern_hits:
        failures.append(
            "avoid_pattern_hits:"
            + json.dumps(alignment.avoid_pattern_hits, ensure_ascii=False, sort_keys=True)
        )
    if alignment.capability_errors:
        failures.append(
            "capability_errors:"
            + json.dumps(alignment.capability_errors, ensure_ascii=False, sort_keys=True)
        )
    if resolution_report is None:
        failures.append("candidate_resolution_report_missing")
        return failures
    if not resolution_report.ok:
        failures.append(
            "executable_resolution_errors:"
            + json.dumps(resolution_report.errors, ensure_ascii=False, sort_keys=True)
        )
    return failures
