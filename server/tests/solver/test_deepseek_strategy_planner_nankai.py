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
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    PlannerRetryReplayService,
    RecipeTrialExecutor,
    StepIntentValidator,
    StepIntentDraft,
    StepIntentValidationReport,
    StepIntentCandidateResolver,
    StepIntentNormalizer,
    StrategyDraftValidationError,
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    repair_attempt_payload_from_replay,
    write_strategy_debug_artifacts,
)


RUN_DEEPSEEK_STRATEGY_PLANNER = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_STRATEGY_PLANNER") == "1"
)
NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"
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
    assert _method_ids_by_step(captured["planner_output"])["compute_ii_1_minimum"] == [
        "distance_between_points"
    ]


def test_recorded_executable_step_intents_are_method_or_recipe_grained() -> None:
    """执行黄金 fixture 必须是 method/recipe 最小颗粒度。

    网页讲解 step 可以合并多个数学动作，但 Method Solver 的 executable
    StepIntent 需要能直接映射到一个 recipe 或 method，因此不能出现空 hint。
    """
    step_intent_payload = json.loads(
        RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8")
    )
    recipe_ids = {recipe.recipe_id for recipe in QUADRATIC_PATH_MINIMUM_FAMILY.step_recipes}
    method_ids = set(QUADRATIC_PATH_MINIMUM_FAMILY.method_ids)
    allowed_hints = recipe_ids | method_ids
    hints_by_step: dict[str, str | None] = {}

    for scope in step_intent_payload["scopes"]:
        for step in scope["steps"]:
            hint = step.get("recipe_hint")
            hints_by_step[step["step_id"]] = hint
            assert hint, f"{step['step_id']} must have recipe_hint"
            assert hint in allowed_hints, f"{step['step_id']} has unknown hint {hint}"
            produced_types = {
                _produced_handle_kind(item["handle"])
                for item in step.get("produces", [])
            }
            assert (
                len(produced_types) <= 1
            ), f"{step['step_id']} produces unrelated output kinds: {produced_types}"

    assert hints_by_step["compute_ii_1_minimum"] == "distance_between_points"


def test_execution_feedback_reports_structured_missing_midpoint_state() -> None:
    """缺少中点坐标状态时，测试侧只回传结构化执行错误。

    生产 retry 的修复建议来自 PlannerRetryState / RepairFeedbackBuilder；
    opt-in 测试不能额外注入南开专用“教练文本”。
    """
    step_intent_payload = json.loads(
        RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8")
    )
    broken_payload = _without_recipe_hint(step_intent_payload, "midpoint_point")
    expected = load_expected_answers(NANKAI_EXPECTED)

    failures, result, captured = _execution_failures_from_step_intent_payload(
        broken_payload,
        expected,
    )

    assert result.status == "failed"
    assert "execution_failed: unknown_read_handle:fact:ii:F_coordinate_expr" in failures
    joined = "\n".join(failures)
    assert "later path-minimum steps read" not in joined
    assert "fact:problem:D_coordinate" not in joined
    assert "fact:ii:F_midpoint_of_DN" not in joined


def test_runtime_feedback_payload_populates_latest_stable_runtime_state() -> None:
    """runtime blocker 应进入 rich previous_attempt_state，供下一轮增量修复。"""
    step_intent_payload = json.loads(
        RECORDED_NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8")
    )
    broken_payload = _replace_step_read(
        step_intent_payload,
        step_id="compute_G_coordinate",
        old="fact:ii_2:m_value",
        new="fact:ii_1:m_value",
    )
    expected = load_expected_answers(NANKAI_EXPECTED)

    failures, result, captured = _execution_failures_from_step_intent_payload(
        broken_payload,
        expected,
    )

    assert result.status == "failed"
    assert captured["execution_diagnostic"].ok is False
    assert captured["execution_diagnostic"].first_blocker.step_id == (
        "compute_G_coordinate"
    )
    assert captured["effective_draft"].to_payload()["scopes"]

    replay = PlannerRetryReplayService().replay_from_artifacts(
        attempt=1,
        errors=tuple(failures),
        validation_report=StepIntentValidationReport(ok=True),
        normalized_draft=captured["draft"],
        normalization_report=captured["normalization_report"],
        resolution_report=captured["resolution_report"],
        effective_draft=captured["effective_draft"],
        diagnostic=captured["execution_diagnostic"],
    )
    retry_attempt = repair_attempt_payload_from_replay(replay)
    assert retry_attempt is not None
    problem = load_problem_ir(NANKAI_FIXTURE)
    llm_problem = problem_to_llm_payload(problem)
    retry_inputs = replace(
        build_strategy_probe_inputs(problem),
        previous_errors=[retry_attempt],
    )
    payload = StrategyPayloadBuilder().build(
        retry_inputs,
        problem_payload=llm_problem,
    )
    latest_runtime = payload["previous_attempt_state"]["latest_stable_runtime"]
    latest_retry_state = payload["previous_attempt_state"]["latest_retry_state"]

    assert latest_retry_state is not None
    assert latest_retry_state["attempt"] == 1
    assert latest_retry_state["preserve_policy"] == "preserve_prefix"
    assert latest_retry_state["stable_prefix"]
    assert latest_retry_state["issues"][0]["layer"] == "trial_execution"
    assert latest_retry_state["baseline_draft"]["scopes"]
    assert latest_runtime is not None
    assert latest_runtime["attempt"] == 1
    assert latest_runtime["planner_retry_state"]["attempt"] == 1
    assert latest_runtime["diagnostic"]["blockers"]
    assert latest_runtime["repair_summary"]["current_blocker"]["step_id"] == (
        "compute_G_coordinate"
    )
    assert latest_runtime["effective_draft"]["scopes"]
    assert "repair_summary" in latest_runtime


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


def test_execution_feedback_keeps_runtime_errors_structured() -> None:
    """测试侧 retry errors 只保留结构化错误码，不注入题目专用教练文本。"""
    error = (
        "recipe_trial_step_failed: step=solve_m_from_minimum, errors=["
        "'parameter_from_minimum_value: missing_required_runtime_fact: minimum_expression; "
        "path $subquestion.ii_1.outputs.min_value is not visible from scope solve_m_from_minimum']"
    )

    assert _short_execution_error(error) == (
        "execution_failed: recipe_trial_step_failed:solve_m_from_minimum"
    )


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


def _replace_step_read(
    payload: dict,
    *,
    step_id: str,
    old: str,
    new: str,
) -> dict:
    """只替换指定 step 的一个 read handle，保持 fixture 其他部分不变。"""
    cloned = deepcopy(payload)
    replaced = False
    for scope in cloned.get("scopes", []):
        for step in scope.get("steps", []):
            if step.get("step_id") != step_id:
                continue
            reads = step.get("reads", [])
            step["reads"] = [new if item == old else item for item in reads]
            replaced = replaced or old in reads
    assert replaced, f"{step_id} did not read {old}"
    return cloned


def _solve_nankai_from_step_intent_payload(step_intent_payload: dict):
    """把 StepIntent payload 接入 RuntimeOrchestrator 并返回 SolverResult。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    llm_problem = problem_to_llm_payload(problem)
    handle_registry = CanonicalHandleRegistry.from_problem_payload(llm_problem)

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
                planner_output, execution_diagnostic, effective_draft = (
                    RecipeTrialExecutor().diagnose(
                        draft,
                        family_spec=inputs.family_spec,
                        method_specs=inputs.method_specs,
                        handle_registry=handle_registry,
                        context=context,
                        question_goals=inputs.question_goals,
                    )
                )
                captured["execution_diagnostic"] = execution_diagnostic
                captured["effective_draft"] = effective_draft
                if planner_output is None:
                    blocker = execution_diagnostic.first_blocker
                    if blocker is not None:
                        raise StrategyDraftValidationError(
                            f"recipe_trial_step_failed: step={blocker.step_id}, "
                            f"errors={list(blocker.capability_errors)}"
                        )
                    raise StrategyDraftValidationError(
                        "recipe_trial_candidate_resolution_failed: "
                        + json.dumps(
                            execution_diagnostic.candidate_errors,
                            ensure_ascii=False,
                        )
                    )
                captured["planner_output"] = planner_output
                return planner_output

        return StepIntentGatedNankaiPlanner()

    result = RuntimeOrchestrator(
        planner_providers={QUADRATIC_PATH_MINIMUM_FAMILY.family_id: provider},
    ).solve(problem)

    return result, captured


def _method_ids_by_step(planner_output) -> dict[str, list[str]]:
    """按 step_id 汇总 PlannerOutput 中实际调用的 method。"""
    return {
        step.step_id: [invocation.method_id for invocation in step.invocations]
        for step in planner_output.step_plans
    }


def _produced_handle_kind(handle: str) -> str:
    """用 handle 的结构化语义粗分 produces 类型，避免同一步跨无关产物。"""
    if handle.startswith("answer:"):
        name = handle.split(".", 1)[1] if "." in handle else handle
    else:
        name = handle.rsplit(":", 1)[-1]
    if "parabola" in name:
        return "parabola"
    if "minimum" in name or "min_value" in name:
        return "minimum"
    if (
        name.endswith("_coordinate")
        or "coordinate" in name
        or name in {"axis_point", "intersection"}
    ):
        return "point"
    if name.endswith("_value") or "parameter" in name:
        return "parameter"
    if "path" in name:
        return "path"
    return name


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

    这里刻意使用 StepIntent 的语义语言和 canonical handle，而不是 Python
    traceback 或 ContextPath。具体 repair guidance 由生产
    PlannerRetryState/RepairFeedbackBuilder 生成，测试侧不注入黄金路径提示。
    """
    failures: list[str] = []
    if result.status != "ok":
        failures.append(f"solver_status: {result.status}")
    for error in result.errors:
        failures.append(_short_execution_error(str(error)))
    for check in result.checks:
        if not check.ok:
            failures.append(f"check_failed: {check.name}")
    if result.status == "ok":
        failures.extend(_answer_mismatch_failures(result.answers, expected))
    return _dedupe(failures)


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


def _reset_debug_dir(path: Path) -> None:
    """真实 LLM 测试开始前清空 debug 目录，确保 artifacts 只属于本次运行。"""
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _semantic_read_count_from_raw(raw: str) -> int:
    """Best-effort count for DeepSeek raw semantic_reads usage."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    count = 0
    for scope in payload.get("scopes", []):
        if not isinstance(scope, dict):
            continue
        for step in scope.get("steps", []):
            if not isinstance(step, dict):
                continue
            semantic_reads = step.get("semantic_reads")
            if isinstance(semantic_reads, list):
                count += len(semantic_reads)
    return count


@pytest.mark.skipif(
    not RUN_DEEPSEEK_STRATEGY_PLANNER,
    reason="set RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 to call DeepSeek",
)
def test_deepseek_strategy_planner_outputs_valid_step_intents_and_solves_nankai() -> None:
    """DeepSeek 应输出合法 StepIntent[]，并经代码执行得到南开答案。"""
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    if not config.deepseek_api_key:
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    configured_model = config.llm_model or config.deepseek_model
    client = config.build_llm_client()

    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = problem_to_llm_payload(problem)
    handle_registry = CanonicalHandleRegistry.from_problem_payload(llm_problem)
    runtime_context = ContextBuilder().build(problem)
    debug_dir = Path(
        os.getenv("STRATEGY_PLANNER_DEBUG_DIR")
        or config.llm_debug_dir
        or DEFAULT_DEBUG_DIR
    )
    _reset_debug_dir(debug_dir)

    previous_attempts: list[dict[str, object]] = []
    attempt_summaries: list[dict[str, object]] = []
    final_payload: dict[str, object] | None = None
    final_prompt = None
    final_raw = ""
    final_draft: StepIntentDraft | None = None
    final_report: StepIntentValidationReport | None = None
    final_normalization_report = None
    final_resolution_report = None
    final_metadata: dict[str, object] | None = None
    final_failures: list[str] = []
    final_result = None
    final_captured: dict | None = None
    expected = load_expected_answers(NANKAI_EXPECTED)

    for attempt in range(1, MAX_DEEPSEEK_ATTEMPTS + 1):
        attempt_inputs = replace(inputs, previous_errors=list(previous_attempts))
        payload = StrategyPayloadBuilder(
            allow_same_problem_few_shot=False
        ).build(
            attempt_inputs,
            problem_payload=llm_problem,
        )
        latest_rich_attempt = next(
            (
                item
                for item in reversed(previous_attempts)
                if isinstance(item.get("planner_retry_state"), dict)
                or (
                    isinstance(item.get("effective_draft"), dict)
                    and isinstance(item.get("diagnostic"), dict)
                )
            ),
            None,
        )
        if latest_rich_attempt is not None:
            latest_retry_state = payload["previous_attempt_state"][
                "latest_retry_state"
            ]
            latest_runtime = payload["previous_attempt_state"][
                "latest_stable_runtime"
            ]
            if isinstance(latest_rich_attempt.get("planner_retry_state"), dict):
                assert latest_retry_state is not None
                assert latest_retry_state["attempt"] == latest_rich_attempt["attempt"]
            else:
                assert latest_runtime is not None
                assert latest_runtime["attempt"] == latest_rich_attempt["attempt"]
        prompt = StrategyPromptRenderer().render(payload)
        assert payload["semantic_read_catalog"]["item_count"] > 0
        assert "Semantic Read Catalog" in prompt.user
        assert "semantic_reads" in prompt.system + prompt.user
        raw = client.complete(
            {
                "messages": prompt.messages,
                "family_id": inputs.family_spec.family_id,
                "problem_id": inputs.problem_id,
                "planner_payload": payload,
            }
        )
        replay = PlannerRetryReplayService().replay_raw_json(
            raw,
            inputs=attempt_inputs,
            handle_registry=handle_registry,
            context=runtime_context,
            attempt=attempt,
            problem_payload=llm_problem,
        )
        draft = replay.normalized_draft
        report = replay.validation_report
        assert report is not None
        normalization_report = replay.normalization_report
        resolution_report = replay.resolution_report
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
        diagnostic = (
            solver_captured.get("execution_diagnostic")
            if solver_captured is not None
            else replay.diagnostic
        )
        effective_draft = (
            solver_captured.get("effective_draft")
            if solver_captured is not None
            else replay.effective_draft
        )
        current_replay = PlannerRetryReplayService().replay_from_artifacts(
            attempt=attempt,
            errors=tuple(failures),
            raw_draft=replay.raw_draft,
            validation_report=report,
            normalized_draft=draft,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            effective_draft=effective_draft,
            diagnostic=diagnostic,
            goal_verification_issues=replay.goal_verification_issues,
            output=replay.output,
            planner_state_context=replay.planner_state_context,
        )
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
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            execution_diagnostic=diagnostic,
            effective_draft=effective_draft,
            planner_retry_state=current_replay.retry_state,
            planner_state_context=current_replay.planner_state_context,
            llm_metadata=metadata,
        )
        _write_execution_debug_artifacts(
            debug_dir / f"attempt-{attempt}",
            result=solver_result,
            execution_failures=execution_failures,
            solver_captured=solver_captured,
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
            "semantic_read_count": _semantic_read_count_from_raw(raw),
            "semantic_read_resolution_report": (
                report.semantic_read_resolution.to_payload()
                if report.semantic_read_resolution is not None
                else None
            ),
            "planner_retry_state": (
                current_replay.retry_state.to_payload()
                if current_replay.retry_state is not None
                else None
            ),
            "previous_attempt_state": payload["previous_attempt_state"],
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
        final_normalization_report = normalization_report
        final_resolution_report = resolution_report
        final_metadata = metadata
        final_failures = failures
        final_result = solver_result
        final_captured = solver_captured
        if not failures:
            break
        retry_attempt = repair_attempt_payload_from_replay(current_replay)
        assert retry_attempt is not None
        retry_attempt.update(
            {
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
        previous_attempts.append(retry_attempt)

    assert final_payload is not None
    assert final_prompt is not None
    assert final_report is not None
    assert final_metadata is not None
    assert final_payload["semantic_read_catalog"]["item_count"] > 0
    assert "Semantic Read Catalog" in final_prompt.user
    write_strategy_debug_artifacts(
        debug_dir,
        payload=final_payload,
        prompt=final_prompt,
        raw_response=final_raw,
        draft=final_draft,
        report=final_report,
        normalization_report=final_normalization_report,
        resolution_report=final_resolution_report,
        execution_diagnostic=(
            final_captured.get("execution_diagnostic")
            if final_captured is not None
            else None
        ),
        effective_draft=(
            final_captured.get("effective_draft")
            if final_captured is not None
            else None
        ),
        planner_retry_state=(
            attempt_summaries[-1].get("planner_retry_state")
            if attempt_summaries
            else None
        ),
        llm_metadata={
            **final_metadata,
            "attempt_summaries": attempt_summaries,
        },
    )
    _write_execution_debug_artifacts(
        debug_dir,
        result=final_result,
        execution_failures=final_failures,
        solver_captured=final_captured,
    )
    (debug_dir / "loop-summary.json").write_text(
        json.dumps(attempt_summaries, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert (debug_dir / "semantic-read-catalog.json").exists()
    assert (debug_dir / "planner-retry-state.json").exists()
    assert (debug_dir / "baseline-draft.json").exists()
    assert (debug_dir / "stable-prefix.json").exists()
    assert (debug_dir / "repair-suffix.json").exists()
    assert (debug_dir / "replay-reports.json").exists()

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


def _write_execution_debug_artifacts(
    target_dir: Path,
    *,
    result,
    execution_failures: list[str],
    solver_captured: dict | None = None,
) -> None:
    """给每轮 attempt 额外写 runtime 执行结果，便于看 LLM loop 为什么没过。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    if result is not None:
        (target_dir / "solver-result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    diagnostic = (
        solver_captured.get("execution_diagnostic") if solver_captured else None
    )
    if diagnostic is not None:
        (target_dir / "execution-diagnostic.json").write_text(
            json.dumps(
                diagnostic.to_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    effective_draft = solver_captured.get("effective_draft") if solver_captured else None
    if effective_draft is not None:
        (target_dir / "effective-step-intents.json").write_text(
            json.dumps(
                effective_draft.to_payload(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
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
    """只把 schema/handle/candidate 真失败转成可回传给 LLM 的错误列表。"""
    failures: list[str] = []
    if not report.ok:
        failures.extend(report.errors or ("validation_report_not_ok",))
        failures.extend(f"missing_goal:{goal}" for goal in report.missing_goals)
        return failures
    if draft is None:
        return ["draft_missing_after_validation"]
    if resolution_report is None:
        failures.append("candidate_resolution_report_missing")
        return failures
    if not resolution_report.ok:
        failures.append(
            "executable_resolution_errors:"
            + json.dumps(resolution_report.errors, ensure_ascii=False, sort_keys=True)
        )
    return failures
