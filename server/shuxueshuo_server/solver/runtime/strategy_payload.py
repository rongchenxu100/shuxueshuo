"""Strategy Planner prompt payload 与 debug artifact。

本模块负责把 LLM ProblemIR、FamilySpec、method/recipe catalog 与 schema 渲染成
DeepSeek probe 使用的 prompt，并写出调试文件。
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    FamilyRegistry,
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventory
from shuxueshuo_server.solver.runtime.capability_contracts import (
    contract_is_prompt_executable,
    effective_contract_by_id,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.semantic_reads import (
    ContextSemanticReadSource,
    build_semantic_read_catalog_payload,
)
from shuxueshuo_server.solver.runtime.strategy_few_shots import (
    goal_types_from_scopes,
    query_goal_types_from_problem,
    select_few_shot_examples,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutablePlanResolutionReport,
    STEP_INTENT_JSON_SCHEMA,
    StepIntentExecutionDiagnostic,
    StepIntentDraft,
    StepIntentNormalizationReport,
    StepIntentValidationReport,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import (
    _method_capability_summary,
)
from shuxueshuo_server.solver.runtime.strategy_retry_state import (
    retry_state_from_attempt,
)


class PlannerStateContextDebugSource(ContextSemanticReadSource, Protocol):
    """Planner context projection used by debug artifact writing."""

    def to_payload(self) -> dict[str, Any]:
        """Return full context snapshot payload."""

    @property
    def rewrite_ledger_payload(self) -> list[dict[str, str]]:
        """Return state rewrite ledger payload."""

    @property
    def events_payload(self) -> list[dict[str, Any]]:
        """Return context event payload."""

class StrategyPayloadBuilder:
    """把 PlannerInputs 压缩成 LLM 可读的 probe payload。

    Phase 1 不再把 RuntimeContext 拆成 scope/relation/signal 多张工程表，而是把
    结构化 ProblemIR 作为主要读题材料直接交给 LLM。这样模型更像在读题，而不是
    在做 ContextPath 查表。
    """

    def __init__(
        self,
        *,
        few_shot_examples: list[dict[str, Any]] | None = None,
        few_shot_dir: Path | str | None = None,
        allow_same_problem_few_shot: bool = True,
        problem_payload: dict[str, Any] | None = None,
    ) -> None:
        self.few_shot_examples = few_shot_examples
        self.few_shot_dir = Path(few_shot_dir) if few_shot_dir is not None else None
        self.allow_same_problem_few_shot = allow_same_problem_few_shot
        self.problem_payload = problem_payload

    def build(
        self,
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any] | None = None,
        planner_state_context: ContextSemanticReadSource | None = None,
    ) -> dict[str, Any]:
        """生成 prompt payload；每个顶层字段都对应一个可独立 fake 的来源。"""
        problem_payload = problem_payload or self.problem_payload
        if problem_payload is None:
            if inputs.problem is not None:
                problem_payload = problem_to_llm_payload(inputs.problem)
            else:
                raise ValueError(
                    "StrategyPayloadBuilder requires canonical problem payload; "
                    "StrategyPlanner should provide it via RuntimeProjection"
                )
        method_ids = inputs.family_spec.method_ids or tuple(
            sorted(inputs.method_specs.specs)
        )
        prompt_method_ids = _prompt_exposed_direct_method_ids(
            inputs.family_spec,
            method_ids,
            inputs.method_specs,
        )
        # 显式传入的 LLM ProblemIR 是 prompt 的唯一题目事实源。这里在 payload 边界
        # 校验，避免旧 solver fixture 的 relations/target_path 等字段混入 LLM 链路。
        handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
        if planner_state_context is None:
            planner_state_context = initial_planner_state_context(
                inputs,
                problem_payload=problem_payload,
                handle_registry=handle_registry,
            )
        previous_attempts = list(inputs.previous_errors)
        return {
            "problem_id": inputs.problem_id,
            "family_id": inputs.family_spec.family_id,
            "problem_ir": dict(problem_payload),
            "semantic_read_catalog": build_semantic_read_catalog_payload(
                handle_registry,
                planner_state_context=planner_state_context,
            ),
            "naming_conventions": _naming_conventions_payload(),
            "prompt_flags": _prompt_flags(inputs.family_spec),
            "family_spec": _family_spec_payload(inputs.family_spec),
            "method_catalog": _method_catalog_payload(
                inputs.method_specs,
                prompt_method_ids,
            ),
            "recipe_catalog": _recipe_catalog_payload(inputs.family_spec),
            "few_shot_examples": self._few_shot_examples(inputs, problem_payload),
            "previous_attempt_state": _previous_attempt_state(previous_attempts),
            "previous_attempts": previous_attempts,
            "output_json_schema": STEP_INTENT_JSON_SCHEMA,
        }

    def _few_shot_examples(
        self,
        inputs: PlannerInputs,
        problem_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """选择 few-shot；显式注入优先，目录无命中则回退虚构示例。"""
        if self.few_shot_examples is not None:
            return self.few_shot_examples
        query_goal_types = query_goal_types_from_problem(
            problem_payload=problem_payload,
            question_goals=inputs.question_goals,
        )
        selected = select_few_shot_examples(
            family_id=inputs.family_spec.family_id,
            goal_types=query_goal_types,
            problem_id=inputs.problem_id,
            allow_same_problem=self.allow_same_problem_few_shot,
            top_k=1,
            few_shot_dir=self.few_shot_dir,
        )
        if selected:
            return selected
        return _default_few_shot_examples(inputs.family_spec.family_id)


def _previous_attempt_state(previous_attempts: list[Any]) -> dict[str, Any]:
    """为 prompt 提供上一轮失败历史的稳定索引。

    ``previous_attempts`` 继续保留完整历史；这里额外抽出 LLM 最需要的两条线：
    已通过 runtime dry-run 的稳定前缀，以及最新 semantic_reads 失败的局部修复信息。
    """
    latest_retry_attempt = _latest_retry_state_attempt_payload(previous_attempts)
    latest_retry_state = (
        retry_state_from_attempt(latest_retry_attempt)
        if latest_retry_attempt is not None
        else None
    )
    if latest_retry_state is not None:
        latest_stable_runtime = _stable_runtime_from_retry_state(
            latest_retry_state,
            retry_attempt=latest_retry_attempt,
        )
        latest_semantic_failure = _semantic_failure_from_retry_state(
            latest_retry_state,
            retry_attempt=latest_retry_attempt,
        )
    else:
        latest_stable_runtime = _latest_stable_runtime_attempt(previous_attempts)
        latest_semantic_failure = _latest_semantic_failure_attempt(previous_attempts)
    return {
        "attempt_count": len(previous_attempts),
        "latest_retry_state": latest_retry_state,
        "latest_stable_runtime": latest_stable_runtime,
        "latest_semantic_failure": latest_semantic_failure,
    }


def _latest_retry_state_attempt(
    previous_attempts: list[Any],
) -> dict[str, Any] | None:
    """返回最近一个正式 PlannerRetryState payload。"""
    attempt = _latest_retry_state_attempt_payload(previous_attempts)
    return retry_state_from_attempt(attempt) if attempt is not None else None


def _latest_retry_state_attempt_payload(
    previous_attempts: list[Any],
) -> dict[str, Any] | None:
    """返回最近一个携带正式 PlannerRetryState 的 attempt payload。"""
    for item in reversed(previous_attempts):
        if not isinstance(item, dict):
            continue
        if retry_state_from_attempt(item) is not None:
            return item
    return None


def _latest_stable_runtime_attempt(
    previous_attempts: list[Any],
) -> dict[str, Any] | None:
    """返回最近一个包含 effective draft 和 diagnostic 的 runtime 修复上下文。"""
    for item in reversed(previous_attempts):
        if not isinstance(item, dict):
            continue
        if not (
            isinstance(item.get("effective_draft"), dict)
            and isinstance(item.get("diagnostic"), dict)
        ):
            continue
        payload = _select_attempt_fields(
            item,
            (
                "attempt",
                "repair_summary",
                "effective_draft",
                "diagnostic",
                "repair_instruction",
                "errors",
            ),
        )
        state = retry_state_from_attempt(item)
        if state is not None:
            payload["planner_retry_state"] = state
            if state.get("baseline_draft") is not None:
                payload["effective_draft"] = state["baseline_draft"]
            if state.get("repair_instruction") is not None:
                payload["repair_instruction"] = state["repair_instruction"]
        return payload
    return None


def _stable_runtime_from_retry_state(
    retry_state: dict[str, Any],
    *,
    retry_attempt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从正式 PlannerRetryState 派生旧 latest_stable_runtime 兼容镜像。"""
    attempt_repair_summary = (
        retry_attempt.get("repair_summary")
        if isinstance(retry_attempt, dict)
        else None
    )
    attempt_errors = (
        retry_attempt.get("errors")
        if isinstance(retry_attempt, dict)
        else None
    )
    return {
        "attempt": retry_state.get("attempt"),
        "repair_summary": attempt_repair_summary,
        "effective_draft": retry_state.get("baseline_draft"),
        "diagnostic": _retry_state_replay_report(retry_state, "trial_execution"),
        "repair_instruction": retry_state.get("repair_instruction"),
        "errors": (
            attempt_errors
            if isinstance(attempt_errors, list)
            else _retry_state_issue_messages(retry_state)
        ),
        "planner_retry_state": retry_state,
    }


def _semantic_failure_from_retry_state(
    retry_state: dict[str, Any],
    *,
    retry_attempt: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """从正式 PlannerRetryState 派生旧 latest_semantic_failure 兼容镜像。"""
    semantic_issues = [
        issue for issue in retry_state.get("issues", [])
        if isinstance(issue, dict) and issue.get("layer") == "semantic_reads"
    ]
    if not semantic_issues:
        return None
    attempt_errors = (
        retry_attempt.get("errors")
        if isinstance(retry_attempt, dict)
        else None
    )
    payload: dict[str, Any] = {
        "attempt": retry_state.get("attempt"),
        "errors": (
            attempt_errors
            if isinstance(attempt_errors, list)
            else _retry_state_issue_messages(retry_state, layer="semantic_reads")
        ),
    }
    if isinstance(retry_attempt, dict) and retry_attempt.get("raw_preview") is not None:
        payload["raw_preview"] = retry_attempt["raw_preview"]
    validation_report = _retry_state_replay_report(retry_state, "validation")
    if isinstance(validation_report, dict):
        validation_errors = validation_report.get("errors")
        if isinstance(validation_errors, list):
            payload["validation_errors"] = validation_errors
        semantic_report = validation_report.get("semantic_read_resolution")
        if isinstance(semantic_report, dict):
            payload["semantic_read_resolution"] = semantic_report
            return payload
    payload["semantic_read_resolution"] = {
        "ok": False,
        "errors": semantic_issues,
    }
    return payload


def _latest_semantic_failure_attempt(
    previous_attempts: list[Any],
) -> dict[str, Any] | None:
    """返回最近一个 semantic_reads 解析失败上下文。"""
    for item in reversed(previous_attempts):
        if not isinstance(item, dict):
            continue
        semantic_report = _semantic_read_resolution_from_attempt(item)
        if not semantic_report or not semantic_report.get("errors"):
            continue
        payload = _select_attempt_fields(
            item,
            (
                "attempt",
                "errors",
                "raw_preview",
            ),
        )
        validation_report = _validation_report_payload(item)
        if isinstance(validation_report, dict) and "errors" in validation_report:
            payload["validation_errors"] = validation_report["errors"]
        payload["semantic_read_resolution"] = semantic_report
        return payload
    return None


def _retry_state_replay_report(
    retry_state: dict[str, Any],
    layer: str,
) -> dict[str, Any] | None:
    reports = retry_state.get("replay_reports")
    if not isinstance(reports, dict):
        return None
    report = reports.get(layer)
    return report if isinstance(report, dict) else None


def _retry_state_issue_messages(
    retry_state: dict[str, Any],
    *,
    layer: str | None = None,
) -> list[str]:
    messages: list[str] = []
    for issue in retry_state.get("issues", []):
        if not isinstance(issue, dict):
            continue
        if layer is not None and issue.get("layer") != layer:
            continue
        message = issue.get("message")
        if isinstance(message, str) and message:
            messages.append(message)
    return messages


def _select_attempt_fields(
    item: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    """复制 attempt 中存在且非空的 prompt 相关字段。"""
    return {
        field: item[field]
        for field in fields
        if field in item and item[field] is not None
    }


def _semantic_read_resolution_from_attempt(
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """从 previous attempt payload 中取 semantic read report。"""
    validation_report = _validation_report_payload(item)
    if not isinstance(validation_report, dict):
        return None
    semantic_report = validation_report.get("semantic_read_resolution")
    if isinstance(semantic_report, dict):
        return semantic_report
    return None


def _validation_report_payload(item: dict[str, Any]) -> dict[str, Any] | None:
    """兼容 dict 或少量测试中可能传入的 report 对象。"""
    validation_report = item.get("validation_report")
    if isinstance(validation_report, dict):
        return validation_report
    if hasattr(validation_report, "to_payload"):
        payload = validation_report.to_payload()
        if isinstance(payload, dict):
            return payload
    return None


class StrategyPromptRenderer:
    """渲染 Strategy Planner 的 system/user prompt。"""

    def __init__(self, template_dir: Path | str | None = None) -> None:
        self.template_dir = Path(template_dir) if template_dir else _default_template_dir()
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["pretty_json"] = _pretty_json

    def render(self, payload: dict[str, Any]) -> StrategyPrompt:
        """把分来源 payload 渲染成 Chat messages。"""
        system = self.env.get_template("strategy-system.jinja").render(
            output_json_schema=STEP_INTENT_JSON_SCHEMA,
        )
        user = self.env.get_template("strategy-user.jinja").render(payload=payload)
        return StrategyPrompt(system=system.strip(), user=user.strip())

def build_strategy_probe_inputs(
    problem: ProblemIR,
    *,
    family_registry: FamilyRegistry = DEFAULT_FAMILY_REGISTRY,
) -> PlannerInputs:
    """构建 Phase 1 DeepSeek probe 所需的 PlannerInputs。

    Strategy prompt 消费 canonical ProblemIR 投影后的 LLM payload，因此这里不再
    构建 ``ContextInventory`` 的 visible paths / planning signals；保留空 inventory
    只是为了复用 ``PlannerInputs`` 这个输入包。
    """
    family = family_registry.match(problem)
    if family is None:
        raise ValueError(
            f"no solver family for pattern={problem.pattern}, type={problem.problem_type}"
        )
    specs = MethodSpecRegistry.load_from_code()
    question_goals = extract_question_goals(problem)
    return PlannerInputs(
        problem_id=problem.problem_id,
        family_spec=family,
        question_goals=question_goals,
        context_inventory=ContextInventory(),
        method_specs=specs,
        problem=problem,
        original_text=dict(problem.original_text),
        previous_errors=[],
    )

def write_strategy_debug_artifacts(
    debug_dir: Path | str,
    *,
    payload: dict[str, Any],
    prompt: StrategyPrompt,
    raw_response: str,
    draft: StepIntentDraft | None,
    report: StepIntentValidationReport,
    normalization_report: StepIntentNormalizationReport | None = None,
    resolution_report: ExecutablePlanResolutionReport | None = None,
    execution_diagnostic: StepIntentExecutionDiagnostic | None = None,
    effective_draft: StepIntentDraft | None = None,
    planner_retry_state: Any | None = None,
    planner_state_context: PlannerStateContextDebugSource | None = None,
    llm_metadata: dict[str, Any] | None = None,
) -> None:
    """把 DeepSeek probe 的输入输出按来源落盘，方便人工 review prompt。"""
    target = Path(debug_dir)
    target.mkdir(parents=True, exist_ok=True)
    _clear_previous_debug_artifacts(target)
    (target / "prompt.system.md").write_text(prompt.system, encoding="utf-8")
    (target / "prompt.user.md").write_text(prompt.user, encoding="utf-8")
    source_keys = [
        "problem_ir",
        "semantic_read_catalog",
        "naming_conventions",
        "prompt_flags",
        "family_spec",
        "method_catalog",
        "recipe_catalog",
        "few_shot_examples",
        "previous_attempt_state",
        "previous_attempts",
    ]
    for key in source_keys:
        _write_json(target / f"payload.{key}.json", payload.get(key))
    _write_json(
        target / "semantic-read-catalog.json",
        payload.get("semantic_read_catalog"),
    )
    context_catalog = (
        planner_state_context.semantic_read_catalog_payload()
        if planner_state_context is not None
        else None
    )
    _write_json(
        target / "context-semantic-read-catalog.json",
        context_catalog,
    )
    retry_payload = _retry_state_payload(planner_retry_state)
    _write_json(target / "planner-retry-state.json", retry_payload)
    _write_json(
        target / "baseline-draft.json",
        retry_payload.get("baseline_draft") if retry_payload else None,
    )
    _write_json(
        target / "stable-prefix.json",
        retry_payload.get("stable_prefix") if retry_payload else None,
    )
    _write_json(
        target / "repair-suffix.json",
        retry_payload.get("repair_suffix_start") if retry_payload else None,
    )
    _write_json(
        target / "replay-reports.json",
        retry_payload.get("replay_reports") if retry_payload else None,
    )
    context_payload = _planner_state_context_payload(planner_state_context)
    _write_json(target / "planner-state-context.json", context_payload)
    _write_json(
        target / "state-rewrite-ledger.json",
        (
            planner_state_context.rewrite_ledger_payload
            if planner_state_context is not None
            else None
        ),
    )
    _write_json(
        target / "context-events.json",
        (
            planner_state_context.events_payload
            if planner_state_context is not None
            else None
        ),
    )
    _write_json(target / "output.schema.json", STEP_INTENT_JSON_SCHEMA)
    (target / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    _write_json(
        target / "parsed-step-intents.json",
        draft.to_payload() if draft else None,
    )
    _write_json(target / "validation-report.json", report.to_payload())
    if normalization_report is not None:
        _write_json(target / "normalization-report.json", normalization_report)
        _write_json(
            target / "normalized-step-intents.json",
            draft.to_payload() if draft else None,
        )
    if effective_draft is not None:
        _write_json(
            target / "effective-step-intents.json",
            effective_draft.to_payload(),
        )
    if report.handle_resolution is not None:
        _write_json(target / "handle-resolution-report.json", report.handle_resolution)
    if report.semantic_read_resolution is not None:
        _write_json(
            target / "semantic-read-resolution-report.json",
            report.semantic_read_resolution,
        )
        _write_json(
            target / "context-semantic-read-resolution-report.json",
            _context_semantic_read_resolution_payload(
                report.semantic_read_resolution
            ),
        )
    if report.recipe_alignment is not None:
        _write_json(target / "recipe-alignment.json", report.recipe_alignment)
    if resolution_report is not None:
        _write_json(
            target / "candidate-resolution-report.json",
            resolution_report,
        )
    if execution_diagnostic is not None:
        _write_json(
            target / "execution-diagnostic.json",
            execution_diagnostic,
        )
    if llm_metadata is not None:
        _write_json(target / "llm-call.json", llm_metadata)


def _clear_previous_debug_artifacts(target: Path) -> None:
    """清理同一 probe 目录里的旧版 payload，避免人工 review 看到过期文件。"""
    for pattern in ("payload.*.json",):
        for path in target.glob(pattern):
            path.unlink()
    for name in (
        "prompt.system.md",
        "prompt.user.md",
        "output.schema.json",
        "semantic-read-catalog.json",
        "context-semantic-read-catalog.json",
        "semantic-read-resolution-report.json",
        "context-semantic-read-resolution-report.json",
        "raw-response.txt",
        "parsed-step-intents.json",
        "validation-report.json",
        "normalization-report.json",
        "normalized-step-intents.json",
        "handle-resolution-report.json",
        "recipe-alignment.json",
        "candidate-resolution-report.json",
        "effective-step-intents.json",
        "execution-diagnostic.json",
        "planner-retry-state.json",
        "planner-state-context.json",
        "state-rewrite-ledger.json",
        "context-events.json",
        "baseline-draft.json",
        "stable-prefix.json",
        "repair-suffix.json",
        "replay-reports.json",
        "llm-call.json",
    ):
        path = target / name
        if path.exists():
            path.unlink()


def _retry_state_payload(value: Any | None) -> dict[str, Any] | None:
    """兼容 dataclass 或 dict 形态的 PlannerRetryState。"""
    if value is None:
        return None
    payload = _to_jsonable(value)
    return payload if isinstance(payload, dict) else None


def _planner_state_context_payload(value: Any | None) -> dict[str, Any] | None:
    """兼容 dataclass 或 dict 形态的 PlannerStateContext。"""
    if value is None:
        return None
    if hasattr(value, "to_payload"):
        payload = value.to_payload()
        return payload if isinstance(payload, dict) else None
    if isinstance(value, dict):
        return value
    return None


def _context_semantic_read_resolution_payload(value: Any) -> dict[str, Any]:
    """Mark the context-specific debug file as a compatibility mirror."""
    return {
        "mirror_of": "semantic-read-resolution-report.json",
        "note": (
            "Phase 3 uses the same SemanticReadResolutionReport object; "
            "context-specific fields live inside each resolution item."
        ),
        "report": value,
    }


def _family_spec_payload(family: SolverFamilySpec) -> dict[str, Any]:
    """把 FamilySpec 中的题型策略字段压成 prompt payload。"""
    return {
        "family_id": family.family_id,
        "common_goal_types": list(family.common_goal_types),
        "strategy_principles": list(family.strategy_principles),
        "method_ids": list(family.method_ids),
    }


def _method_catalog_payload(
    specs: MethodSpecRegistry,
    method_ids: tuple[str, ...],
) -> dict[str, Any]:
    """生成当前 family 可见的 method 能力摘要。

    StepIntent 阶段不要求 LLM 绑定 method input slot，因此这里只给“这项能力能做
    什么”的短摘要，不给完整 MethodSpec schema。完整输入输出槽位仍由后续 resolver
    和 PlanValidator 在代码层使用。
    """
    methods: list[dict[str, Any]] = []
    missing: list[str] = []
    for method_id in method_ids:
        try:
            spec = specs.require(method_id)
        except KeyError:
            missing.append(method_id)
            continue
        methods.append(
            {
                "method_id": spec.method_id,
                "title": spec.title,
                "solves": list(spec.solves),
                "summary": _method_capability_summary(spec),
            }
        )
    return {
        "methods": methods,
        "missing_method_ids": missing,
    }


def _prompt_exposed_direct_method_ids(
    family: SolverFamilySpec,
    method_ids: tuple[str, ...],
    method_specs: MethodSpecRegistry,
) -> tuple[str, ...]:
    """Only expose direct methods with executable contracts and binding rules.

    Pack expansion may bring extra method_ids for recipe internals or future
    family additions. The LLM-facing direct Method Catalog should stay aligned
    with executable binding rules and contract status so a copied method_id can
    actually run.
    """
    binding_rule_ids = {rule.method_id for rule in family.method_binding_rules}
    contracts_by_id = effective_contract_by_id(family, method_specs)
    return tuple(
        method_id
        for method_id in method_ids
        if method_id in binding_rule_ids
        and contract_is_prompt_executable(contracts_by_id.get(method_id))
    )


def _recipe_catalog_payload(family: SolverFamilySpec) -> dict[str, Any]:
    """生成当前 family 的 recipe 菜单摘要。

    这里完整输出 family 配置的 recipe，不做题内 top-k。LLM 需要看到的是“这类题
    推荐有哪些标准动作”，具体某一步最终能否执行由后续 resolver/trial 验算。
    """
    return {
        "recipes": [
            {
                "recipe_id": recipe.recipe_id,
                "goal_type": recipe.goal_type,
                "title": recipe.title,
                "description": recipe.description,
                "method_ids": list(recipe.method_ids),
                **({"priority": recipe.priority} if recipe.priority else {}),
            }
            for recipe in family.step_recipes
        ]
    }

def _default_few_shot_examples(family_id: str) -> list[dict[str, Any]]:
    """提供虚构 few-shot，只展示 recipe 范式，不给当前题完整答案。"""
    builder = _FALLBACK_FEW_SHOT_BUILDERS.get(
        family_id,
        _generic_fallback_few_shot,
    )
    return [builder(family_id)]


def _generic_fallback_few_shot(family_id: str) -> dict[str, Any]:
    """提供通用虚构 few-shot，只展示路径 recipe 范式。"""
    scopes = [
        {
            "scope_id": "demo_i",
            "label": "虚构示例：先产生全题公共结论",
            "steps": [
                {
                    "step_id": "derive_anchor_coordinate",
                    "recipe_hint": "quadratic_axis_from_relation",
                    "goal_type": "derive_constructed_point",
                    "target": "fact:problem:anchor_coordinate",
                    "strategy": "先求出后续全题都会用到的公共点坐标。",
                    "reads": [
                        "point:problem:Anchor",
                        "fact:problem:coefficient_relation",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:problem:anchor_coordinate",
                            "valid_scope": "problem",
                            "description": "公共点 Anchor 的坐标结论，后续 scope 只 reads 复用",
                            "output_type": "Point",
                        }
                    ],
                    "reason": (
                        "公共结论只 produces 一次；后续步骤需要时直接 reads "
                        "fact:problem:anchor_coordinate。"
                    ),
                }
            ],
        },
        {
            "scope_id": "demo",
            "label": "虚构示例：路径最值公共步骤",
            "steps": [
                {
                    "step_id": "reduce_two_moving_points_path",
                    "recipe_hint": "two_moving_points_path_reduction",
                    "goal_type": "reduce_path_expression",
                    "target": "fact:demo:single_moving_path_equivalence",
                    "strategy": "利用两个动点之间的线段比例和所在轨迹，把双动点路径转化为等价单动点折线路径。",
                    "reads": [
                        "point:problem:Anchor",
                        "fact:problem:anchor_coordinate",
                        "fact:demo:path_target",
                        "fact:demo:first_moving_point_on_segment",
                        "fact:demo:second_moving_point_on_segment",
                        "fact:demo:segment_ratio_relation",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo:single_moving_path_equivalence",
                            "valid_scope": "demo",
                            "description": "双动点路径已经转化成只含一个动点的等价折线路径",
                            "output_type": "PathTransformation",
                        }
                    ],
                    "reason": (
                        "路径最值先降维，避免直接把两个动点都参数化。示例中"
                        " point:problem:Anchor 虽在 demo scope 使用，也必须原样引用"
                        " problem scope 的 canonical handle。"
                    ),
                },
                {
                    "step_id": "straighten_reduced_path",
                    "recipe_hint": "broken_path_straightening_and_select",
                    "goal_type": "straighten_broken_path",
                    "target": "fact:demo:straightened_path_choice",
                    "strategy": "对等价折线路径构造拉直候选，并选择最方便计算的拉直方案。",
                    "reads": [
                        "fact:demo:single_moving_path_equivalence",
                        "segment:demo:motion_segment",
                    ],
                    "creates": [
                        {
                            "handle": "point:demo:Aux",
                            "entity_type": "point",
                            "valid_scope": "demo",
                            "description": "用于折线拉直的辅助点",
                        }
                    ],
                    "produces": [
                        {
                            "handle": "fact:demo:straightened_path_choice",
                            "valid_scope": "demo",
                            "description": "已经选定可计算的折线拉直方案",
                            "output_type": "StraighteningCandidate",
                        }
                    ],
                    "reason": "单动点折线最短路径通常通过拉直处理。",
                },
                {
                    "step_id": "compute_straightened_minimum",
                    "recipe_hint": "path_minimum_by_straightened_distance",
                    "goal_type": "derive_minimum_value",
                    "target": "fact:demo:path_minimum_value_expr",
                    "strategy": "在拉直方案确定后，用对应端点间距离得到路径最小值表达式。",
                    "reads": [
                        "fact:demo:straightened_path_choice",
                        "point:demo:Aux",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo:path_minimum_value_expr",
                            "valid_scope": "demo",
                            "description": "路径最小值表达式",
                            "output_type": "MinimumExpression",
                        }
                    ],
                    "reason": "拉直后的最短路径转化为端点间距离。",
                },
            ],
        },
    ]
    return {
        "problem_id": f"fallback-{family_id}",
        "family_id": family_id,
        "title": "fallback strategy demo",
        "original_text": [
            "这是通用兜底示例，不是当前题，也不包含当前题答案。"
        ],
        "retrieval": {
            "goal_types": goal_types_from_scopes(scopes),
        },
        "note": (
            "这是虚构简化场景，只展示路径最值 recipe 的意图格式；不要照抄"
            "题号、点名、handle 或答案。"
        ),
        "example": {"scopes": scopes},
    }


def _equal_length_ray_path_fallback_few_shot(family_id: str) -> dict[str, Any]:
    """为等长射线路径 family 提供抽象辅助线 few-shot。

    这个示例只表达“等长射线路径降维为单距离最值 -> 由最小值反求参数”
    的 recipe/method 粒度，不使用和平题的点名、路径名或题面事实。
    """
    scopes = [
        {
            "scope_id": "demo",
            "label": "虚构示例：等长射线转化为单距离最值",
            "steps": [
                {
                    "step_id": "reduce_equal_length_ray_path",
                    "recipe_hint": "equal_length_ray_path_reduction",
                    "goal_type": "derive_path_minimum_expression",
                    "target": "fact:demo:path_minimum_expression",
                    "strategy": (
                        "利用同端点等长条件，把 Moving 与 RayMover 的两动点路径"
                        "转化为一个固定点到内部辅助点的单距离最值。辅助点由 recipe"
                        "内部构造，StepIntent 不需要 creates 辅助点。"
                    ),
                    "reads": [
                        "point:demo:Anchor",
                        "point:demo:Reference",
                        "point:demo:Moving",
                        "point:demo:RayMover",
                        "point:demo:RayGuide",
                        "fact:demo:moving_on_segment",
                        "fact:demo:ray_mover_on_ray",
                        "fact:demo:equal_length_condition",
                        "fact:demo:path_minimum_target",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo:path_minimum_expression",
                            "valid_scope": "demo",
                            "description": "等长射线路径降维后的单距离最小值表达式",
                            "output_type": "MinimumExpression",
                        }
                    ],
                    "reason": "先用高层 recipe 完成几何转化和单距离最值，不把辅助点创建拆成 LLM step。",
                },
                {
                    "step_id": "solve_parameter_from_minimum",
                    "recipe_hint": "parameter_from_expression_value",
                    "goal_type": "derive_parameter",
                    "target": "answer:demo.parameter",
                    "strategy": "用题设给定的路径最小值等于上一步的最小值表达式，反求参数。",
                    "reads": [
                        "fact:demo:path_minimum_expression",
                        "fact:demo:path_minimum_value_given",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "answer:demo.parameter",
                            "valid_scope": "demo",
                            "description": "由路径最小值条件反求出的参数答案",
                            "output_type": "ParameterValue",
                        }
                    ],
                    "reason": "先完成几何转化和距离最值，再用给定最小值反求参数。",
                },
            ],
        }
    ]
    return {
        "problem_id": "fallback-equal-length-ray-path-minimum",
        "family_id": family_id,
        "title": "equal-length ray path minimum fallback demo",
        "original_text": [
            "点 Moving 在一条线段上，点 RayMover 在一条射线上，满足同端点等长，求 Fixed 到 Moving 与 Anchor 到 RayMover 的路径最小值。"
        ],
        "retrieval": {
            "goal_types": goal_types_from_scopes(scopes),
        },
        "note": (
            "这是虚构简化场景，只展示等长射线路径降维为单距离最值的"
            "可执行步骤粒度；不要照抄示例题 handle、点名、题号或答案。"
        ),
        "example": {"scopes": scopes},
    }


def _square_reflection_path_fallback_few_shot(family_id: str) -> dict[str, Any]:
    """为正方形反射路径 family 提供抽象 mock few-shot。"""
    scopes = [
        {
            "scope_id": "demo_part",
            "label": "虚构示例：正方形点约束与路径降维",
            "steps": [
                {
                    "step_id": "parameterize_axis_point",
                    "recipe_hint": "quadratic_axis_parameterized_point",
                    "goal_type": "derive_parameterized_point",
                    "target": "fact:demo_part:axis_point_parametric",
                    "strategy": "把位于二次函数对称轴上的目标点写成单参数点坐标。",
                    "reads": [
                        "function:demo:quadratic",
                        "point:demo_part:AxisPoint",
                        "fact:demo_part:axis_point_on_axis",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:axis_point_parametric",
                            "valid_scope": "demo_part",
                            "description": "轴上目标点的单参数坐标表达式",
                            "output_type": "Point",
                        }
                    ],
                    "reason": "先得到目标点的参数化表达式，再进入正方形构造。",
                },
                {
                    "step_id": "derive_square_mover",
                    "recipe_hint": "square_adjacent_vertex_from_side",
                    "goal_type": "derive_square_adjacent_vertex",
                    "target": "fact:demo_part:square_mover_parametric",
                    "strategy": "由已知正方形边端点和方向，推出另一个随参数变化的正方形顶点。",
                    "reads": [
                        "point:demo:SidePoint",
                        "fact:demo_part:axis_point_parametric",
                        "point:demo_part:SquareMover",
                        "fact:demo_part:square_side_relation",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:square_mover_parametric",
                            "valid_scope": "demo_part",
                            "description": "正方形动点的参数化坐标表达式",
                            "output_type": "Point",
                        }
                    ],
                    "reason": "曲线条件通常落在正方形的另一个顶点上，不要跳过这一动点。",
                },
                {
                    "step_id": "solve_axis_point_candidates",
                    "recipe_hint": "point_candidates_from_curve_point_condition",
                    "goal_type": "derive_point_candidates_from_curve_point_condition",
                    "target": "answer:demo_part.axis_point_candidates",
                    "strategy": "把正方形动点代入曲线，解出轴上目标点的候选。",
                    "reads": [
                        "fact:demo_part:axis_point_parametric",
                        "fact:demo_part:square_mover_parametric",
                        "fact:demo_part:current_parabola",
                        "fact:demo_part:square_mover_on_curve",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "answer:demo_part.axis_point_candidates",
                            "valid_scope": "demo_part",
                            "description": "由正方形动点在曲线上得到的目标点候选",
                            "output_type": "PointList",
                        }
                    ],
                    "reason": "curve point 和 target point 共享同一参数，代码负责联立曲线条件。",
                },
                {
                    "step_id": "reduce_square_path",
                    "recipe_hint": "square_path_dimension_reduction",
                    "goal_type": "reduce_square_path_dimension",
                    "target": "fact:demo_part:reduced_path",
                    "strategy": "先读取正方形、中点、中心和路径结构，让 method 揭示降维后的真实动点。",
                    "reads": [
                        "fact:demo_part:square_side_relation",
                        "fact:demo_part:side_midpoint_condition",
                        "fact:demo_part:square_center_condition",
                        "fact:demo_part:path_minimum_target",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:reduced_path",
                            "valid_scope": "demo_part",
                            "description": "正方形结构降维后的单动点折线路径",
                            "output_type": "PathTransformation",
                        }
                    ],
                    "reason": "不要在降维前猜测后续动点；执行反馈会给出 moving_point。",
                },
                {
                    "step_id": "derive_square_mover_locus",
                    "recipe_hint": "parameterized_point_locus_line",
                    "goal_type": "derive_locus_line",
                    "target": "fact:demo_part:square_mover_locus",
                    "strategy": "围绕降维 insight 指出的正方形动点，求它随参数变化的轨迹直线。",
                    "reads": [
                        "fact:demo_part:square_mover_parametric",
                        "fact:demo_part:reduced_path",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:square_mover_locus",
                            "valid_scope": "demo_part",
                            "description": "降维后真实动点的轨迹直线",
                            "output_type": "Line",
                        }
                    ],
                    "reason": "降维后，轨迹、拉直和最短状态点都围绕 moving_point 展开。",
                },
                {
                    "step_id": "compute_reduced_path_minimum",
                    "recipe_hint": "broken_path_straightening_minimum_expression",
                    "goal_type": "derive_path_minimum_expression",
                    "target": "fact:demo_part:path_minimum_expression",
                    "strategy": "对单动点折线路径使用将军饮马拉直，得到最小值表达式。",
                    "reads": [
                        "fact:demo_part:reduced_path",
                        "fact:demo_part:square_mover_locus",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:path_minimum_expression",
                            "valid_scope": "demo_part",
                            "description": "单动点折线路径的最小值表达式",
                            "output_type": "MinimumExpression",
                        },
                        {
                            "handle": "fact:demo_part:path_minimum_point_1",
                            "valid_scope": "demo_part",
                            "description": "拉直后最短线段的第一个端点",
                            "output_type": "Point",
                        },
                        {
                            "handle": "fact:demo_part:path_minimum_point_2",
                            "valid_scope": "demo_part",
                            "description": "拉直后最短线段的第二个端点",
                            "output_type": "Point",
                        },
                    ],
                    "reason": "拉直 recipe 同时提供最小值表达式和后续求最短状态动点所需端点。",
                },
                {
                    "step_id": "solve_parameter_from_minimum",
                    "recipe_hint": "parameter_from_expression_value",
                    "goal_type": "derive_parameter_from_expression_value",
                    "target": "fact:demo_part:parameter_value",
                    "strategy": "用题设给定最小值等于上一步表达式，反求参数。",
                    "reads": [
                        "fact:demo_part:path_minimum_expression",
                        "fact:demo_part:path_minimum_value_given",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:parameter_value",
                            "valid_scope": "demo_part",
                            "description": "由最小值条件反求出的参数",
                            "output_type": "ParameterValue",
                        }
                    ],
                    "reason": "先算路径最小值表达式，再和题设最小值比较。",
                },
                {
                    "step_id": "derive_optimal_square_mover",
                    "recipe_hint": "line_locus_minimum_point",
                    "goal_type": "derive_line_locus_minimum_point",
                    "target": "fact:demo_part:optimal_square_mover",
                    "strategy": "用动点轨迹和拉直后最短线段，求最短状态下的正方形动点。",
                    "reads": [
                        "fact:demo_part:square_mover_locus",
                        "fact:demo_part:path_minimum_point_1",
                        "fact:demo_part:path_minimum_point_2",
                        "fact:demo_part:parameter_value",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "fact:demo_part:optimal_square_mover",
                            "valid_scope": "demo_part",
                            "description": "最短状态下正方形动点的坐标",
                            "output_type": "Point",
                        }
                    ],
                    "reason": "路径最短时先确定 moving_point，而不是直接猜最终答案点。",
                },
                {
                    "step_id": "recover_axis_point_answer",
                    "recipe_hint": "square_adjacent_vertex_from_side",
                    "goal_type": "derive_square_adjacent_vertex",
                    "target": "answer:demo_part.axis_point",
                    "strategy": "由已知正方形边端点和最短状态动点，恢复最终要求的轴上点。",
                    "reads": [
                        "point:demo:SidePoint",
                        "fact:demo_part:optimal_square_mover",
                        "point:demo_part:AxisPoint",
                        "fact:demo_part:square_side_relation",
                    ],
                    "creates": [],
                    "produces": [
                        {
                            "handle": "answer:demo_part.axis_point",
                            "valid_scope": "demo_part",
                            "description": "由正方形关系恢复出的最终目标点",
                            "output_type": "Point",
                        }
                    ],
                    "reason": "最终答案点不一定是降维后的 moving_point，需要用正方形关系恢复。",
                },
            ],
        }
    ]
    return {
        "problem_id": "fallback-square-reflection-path-minimum",
        "family_id": family_id,
        "title": "square reflection path minimum fallback demo",
        "original_text": [
            "一个轴上点与固定点组成正方形，正方形另一个动点满足曲线条件；路径最值先由正方形结构降维，再对降维后的动点做轨迹和将军饮马。"
        ],
        "retrieval": {
            "goal_types": goal_types_from_scopes(scopes),
        },
        "note": (
            "这是虚构简化场景，只展示正方形反射路径 family 的可执行步骤粒度；"
            "不要照抄示例题 handle、点名、题号、路径名或答案。"
        ),
        "example": {"scopes": scopes},
    }


FallbackFewShotBuilder = Callable[[str], dict[str, Any]]


_FALLBACK_FEW_SHOT_BUILDERS: dict[str, FallbackFewShotBuilder] = {
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY.family_id: (
        _equal_length_ray_path_fallback_few_shot
    ),
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY.family_id: (
        _square_reflection_path_fallback_few_shot
    ),
}


def _pretty_json(value: Any) -> str:
    """Jinja 过滤器：输出可读中文 JSON。"""
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _write_json(path: Path, value: Any) -> None:
    """写入 pretty JSON。"""
    path.write_text(_pretty_json(_to_jsonable(value)) + "\n", encoding="utf-8")


def _to_jsonable(value: Any) -> Any:
    """把 dataclass/tuple 转成 JSON 友好对象。"""
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def _default_template_dir() -> Path:
    """定位 internal/llm-prompts，避免硬编码固定 parents 层级。"""
    return repo_root(Path(__file__)) / "internal" / "llm-prompts"

def _naming_conventions_payload() -> dict[str, Any]:
    """读取 LLM-facing StepIntent 命名约定。"""
    path = _default_template_dir() / "strategy-naming-conventions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"strategy naming conventions file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"strategy naming conventions file is invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"strategy naming conventions must be a JSON object: {path}")
    serialized = json.dumps(payload, ensure_ascii=False)
    forbidden_tokens = ("$problem", "$question", "$subquestion", "expected answer", "raw DeepSeek")
    for token in forbidden_tokens:
        if token in serialized:
            raise ValueError(
                f"strategy naming conventions contain forbidden runtime/test token: {token}"
            )
    return payload


def _prompt_flags(family_spec: SolverFamilySpec) -> dict[str, bool]:
    """Return coarse prompt feature flags derived from the effective family catalog."""
    recipe_text = " ".join(
        " ".join((
            recipe.recipe_id,
            recipe.goal_type,
            recipe.title,
            recipe.description,
            *recipe.method_ids,
        ))
        for recipe in family_spec.step_recipes
    ).lower()
    method_text = " ".join(family_spec.method_ids).lower()
    goal_text = " ".join(family_spec.common_goal_types).lower()
    combined = " ".join((recipe_text, method_text, goal_text))
    return {
        "supports_path_minimum": (
            "path_minimum" in combined
            or "straighten_broken_path" in combined
            or "broken_path" in combined
        ),
    }
