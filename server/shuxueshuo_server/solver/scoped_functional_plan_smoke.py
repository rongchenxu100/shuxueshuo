"""Run the isolated live DeepSeek FunctionalPlan v2 authoring smoke."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
)
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemPromotionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_context import (
    ProblemDomainContextTransitionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _load_domain_gold,
    _load_f2_context,
    _repo_root,
    _resolve_repo_path,
    _selected_cases,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
    ProblemPlanningBindingCatalogBuilder,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
    ProblemPlanningContextProjector,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    VerifiedSolverProblemBundle,
    VerifiedSolverProblemBundleLoader,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionCheckpoint,
    ScopedFunctionalGoalExecutionResult,
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    LLMPlannerClient,
    LLMProviderResponseError,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanAuthority,
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanError,
    ScopedFunctionalStructureReport,
    ScopedFunctionalPlanValidationReport,
    ScopedFunctionalPlanValidator,
    audit_scoped_functional_structure,
    audit_scoped_functional_structure_prompt_payload,
    normalize_unique_scoped_goal_refs,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
)


DEFAULT_OUTPUT_ROOT = (
    "internal/solver-runs/strategy-planner-deepseek-functional-v2"
)
PLANNER_PROTOCOL = "functional_plan/v2"
SmokeThinkingProfile = Literal["disabled", "low"]


@dataclass(frozen=True)
class _PlannerAuthorityFixture:
    bundle: VerifiedSolverProblemBundle
    planning_context: ProblemPlanningContext
    inputs: PlannerInputs
    problem_payload: dict[str, Any]
    handle_registry: CanonicalHandleRegistry
    planner_state_context: PlannerStateContext
    binding_catalog: ProblemPlanningBindingCatalog
    runtime_context: Any


@dataclass(frozen=True)
class ScopedV2SmokeSampleResult:
    problem_id: str
    sample_id: str
    provider_response_received: bool
    provider_sub_attempt_count: int
    schema_valid: bool
    scope_goal_tree_ok: bool
    plan_authority_ok: bool
    prompt_identity_leaks: tuple[str, ...]
    reconciliation_ok: bool
    compile_ok: bool
    transaction_ok: bool
    transaction_attempted: bool
    authority_valid_step_count: int
    authority_invalid_step_count: int
    pruned_dead_step_count: int
    provisional_executed_step_count: int
    blocked_by_dependency_step_count: int
    blocked_stage: str | None
    passed_goal_count: int
    goal_count: int
    output_ok: bool
    configuration_error_count: int
    unclassified_error_count: int
    usage: Mapping[str, int]
    duration_seconds: float
    error_code: str | None
    error_message: str | None
    sample_dir: str

    @property
    def primary_ok(self) -> bool:
        return (
            self.provider_response_received
            and self.schema_valid
            and self.scope_goal_tree_ok
            and self.plan_authority_ok
            and not self.prompt_identity_leaks
            and self.configuration_error_count == 0
            and self.unclassified_error_count == 0
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "sample_id": self.sample_id,
            "primary_ok": self.primary_ok,
            "provider_response_received": self.provider_response_received,
            "provider_sub_attempt_count": self.provider_sub_attempt_count,
            "schema_valid": self.schema_valid,
            "scope_goal_tree_ok": self.scope_goal_tree_ok,
            "plan_authority_ok": self.plan_authority_ok,
            "prompt_identity_leaks": list(self.prompt_identity_leaks),
            "reconciliation_ok": self.reconciliation_ok,
            "compile_ok": self.compile_ok,
            "transaction_ok": self.transaction_ok,
            "transaction_attempted": self.transaction_attempted,
            "authority_valid_step_count": self.authority_valid_step_count,
            "authority_invalid_step_count": self.authority_invalid_step_count,
            "pruned_dead_step_count": self.pruned_dead_step_count,
            "provisional_executed_step_count": (
                self.provisional_executed_step_count
            ),
            "blocked_by_dependency_step_count": (
                self.blocked_by_dependency_step_count
            ),
            "blocked_stage": self.blocked_stage,
            "passed_goal_count": self.passed_goal_count,
            "goal_count": self.goal_count,
            "output_ok": self.output_ok,
            "configuration_error_count": self.configuration_error_count,
            "unclassified_error_count": self.unclassified_error_count,
            "usage": dict(self.usage),
            "duration_seconds": self.duration_seconds,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "sample_dir": self.sample_dir,
        }


class _RecordingClient:
    def __init__(self, client: LLMPlannerClient) -> None:
        self.client = client
        self.request: dict[str, Any] | None = None
        self.raw_response: str = ""

    def complete(self, payload: dict[str, Any]) -> str:
        self.request = payload
        self.raw_response = self.client.complete(payload)
        return self.raw_response


class _SmokeDeepSeekPlannerClient(DeepSeekPlannerClient):
    """Apply an explicit Pass 1 thinking profile only for this live smoke."""

    def __init__(self, *, thinking_profile: SmokeThinkingProfile, **kwargs: Any) -> None:
        self.thinking_profile = thinking_profile
        super().__init__(**kwargs)

    def _completion_request_options(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if payload.get("planner_attempt") != 1:
            raise ValueError("v2 smoke only supports planner_attempt=1")
        return _smoke_completion_request_options(
            self.thinking_profile,
            temperature=self.temperature,
        )


def _smoke_completion_request_options(
    thinking_profile: SmokeThinkingProfile,
    *,
    temperature: float,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    if thinking_profile == "low":
        options.update(
            {
                "reasoning_effort": "low",
                "extra_body": {"thinking": {"type": "enabled"}},
            }
        )
    return options


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if os.environ.get("RUN_LLM_INTEGRATION") != "1" and not args.dry_run:
        parser.error("live v2 smoke requires RUN_LLM_INTEGRATION=1")
    if min(
        args.samples_per_case,
        args.concurrency,
        args.request_timeout_seconds,
    ) < 1:
        parser.error("sample, concurrency, and timeout values must be positive")

    repo_root = _repo_root()
    output_root = _resolve_repo_path(repo_root, args.output_root)
    f2_root = _resolve_repo_path(repo_root, args.f2_input_dir)
    batch_dir = output_root / args.batch_id
    cases = _selected_cases(load_gold_corpus().cases, args.case, parser)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        max_llm_attempts=1,
        env_file=repo_root / "server/.env",
    )
    if not config.deepseek_api_key:
        parser.error("DEEPSEEK_API_KEY is required")
    jobs = [
        (case, f"sample-{index:02d}")
        for case in cases
        for index in range(1, args.samples_per_case + 1)
    ]
    batch_config = {
        "schema_version": "scoped-functional-plan-smoke-config/v1",
        "batch_id": args.batch_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "planner_protocol": PLANNER_PROTOCOL,
        "case_ids": [item.problem_id for item in cases],
        "samples_per_case": args.samples_per_case,
        "concurrency": min(args.concurrency, len(jobs)),
        "semantic_attempts": 1,
        "thinking": "enabled" if args.thinking == "low" else "disabled",
        "reasoning_effort": "low" if args.thinking == "low" else None,
        "thinking_profile": args.thinking,
        "temperature": 0,
        "provider": "deepseek",
        "model": config.llm_model or config.deepseek_model,
        "request_timeout_seconds": args.request_timeout_seconds,
        "f2_input_dir": str(f2_root),
        "output_dir": str(batch_dir),
    }
    if args.dry_run:
        print(json.dumps(batch_config, ensure_ascii=False, indent=2))
        return 0
    if batch_dir.exists():
        parser.error(f"batch output already exists: {batch_dir}")
    batch_dir.mkdir(parents=True)
    _write_json(batch_dir / "batch-config.json", batch_config)

    results: list[ScopedV2SmokeSampleResult] = []
    with ThreadPoolExecutor(max_workers=batch_config["concurrency"]) as executor:
        futures = {
            executor.submit(
                _run_sample,
                case,
                sample_id,
                batch_dir=batch_dir,
                f2_root=f2_root,
                config=config,
                request_timeout=args.request_timeout_seconds,
                thinking_profile=args.thinking,
            ): (case.problem_id, sample_id)
            for case, sample_id in jobs
        }
        for future in as_completed(futures):
            problem_id, sample_id = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # preserve every unexpected sample
                sample_dir = batch_dir / problem_id / sample_id
                sample_dir.mkdir(parents=True, exist_ok=True)
                result = _unclassified_result(
                    problem_id,
                    sample_id,
                    sample_dir,
                    exc,
                )
                _write_json(sample_dir / "sample-result.json", result.to_payload())
            results.append(result)
            print(
                f"{problem_id}/{sample_id}: primary_ok={result.primary_ok} "
                f"schema={result.schema_valid} "
                f"tree={result.scope_goal_tree_ok} "
                f"authority={result.plan_authority_ok} "
                f"transaction={result.transaction_ok}",
                flush=True,
            )

    results.sort(key=lambda item: (item.problem_id, item.sample_id))
    summary = _batch_summary(batch_config, results)
    _write_json(batch_dir / "batch-summary.json", summary)
    _write_batch_index(batch_dir, results, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["primary_gate_ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all")
    parser.add_argument("--samples-per-case", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--request-timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--thinking",
        choices=("disabled", "low"),
        default="disabled",
        help="Pass 1 thinking profile for this smoke only",
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--f2-input-dir", default=DEFAULT_F2_INPUT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _run_sample(
    case: GoldCorpusCase,
    sample_id: str,
    *,
    batch_dir: Path,
    f2_root: Path,
    config: SolverRuntimeConfig,
    request_timeout: float,
    thinking_profile: SmokeThinkingProfile,
) -> ScopedV2SmokeSampleResult:
    started = perf_counter()
    sample_dir = batch_dir / case.problem_id / sample_id
    sample_dir.mkdir(parents=True)
    fixture = _build_planner_authority(case, sample_dir, f2_root)
    base_client = _SmokeDeepSeekPlannerClient(
        api_key=config.deepseek_api_key or "",
        base_url=config.deepseek_base_url,
        model=config.llm_model or config.deepseek_model,
        request_timeout=request_timeout,
        thinking_profile=thinking_profile,
    )
    client = _RecordingClient(base_client)
    builder = StrategyPayloadBuilder()
    renderer = StrategyPromptRenderer()
    expected_payload = builder.build_scoped(
        fixture.inputs,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    expected_prompt = renderer.render_scoped(expected_payload)
    leaks = _prompt_identity_leaks(
        expected_prompt.system + "\n" + expected_prompt.user,
        bundle=fixture.bundle,
        planning_context=fixture.planning_context,
    )
    goal_execution: ScopedFunctionalGoalExecutionResult | None = None
    error: Exception | None = None
    try:
        raw_response = client.complete(
            {
                "messages": expected_prompt.messages,
                "family_id": fixture.inputs.family_spec.family_id,
                "problem_id": fixture.inputs.problem_id,
                "planner_protocol": PLANNER_PROTOCOL,
                "planner_attempt": 1,
                "planner_payload": expected_payload,
            }
        )
        goal_execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
            raw_response,
            inputs=fixture.inputs,
            planning_context=fixture.planning_context,
            problem_binding_catalog=fixture.binding_catalog,
            handle_registry=fixture.handle_registry,
            context=fixture.runtime_context,
            planner_state_context=fixture.planner_state_context,
            problem_payload=fixture.problem_payload,
        )
        if not goal_execution.authority_report.ok:
            first = goal_execution.authority_report.first_issue
            if first is not None:
                error = ScopedFunctionalPlanError(
                    first.code,
                    first.path,
                    first.message,
                    issues=goal_execution.authority_report.issues,
                    normalizations=goal_execution.authority_report.normalizations,
                )
    except Exception as exc:
        error = exc

    raw_response = client.raw_response
    parsed, validation = ScopedFunctionalPlanValidator().validate_json_with_report(
        raw_response
    )
    raw_structure_report = (
        audit_scoped_functional_structure(parsed, fixture.planning_context)
        if parsed is not None
        else None
    )
    structurally_normalized_plan = parsed
    goal_normalizations = ()
    if parsed is not None:
        (
            structurally_normalized_plan,
            goal_normalizations,
        ) = normalize_unique_scoped_goal_refs(
            parsed,
            fixture.planning_context,
        )
    structure_report = (
        audit_scoped_functional_structure(
            structurally_normalized_plan,
            fixture.planning_context,
        )
        if structurally_normalized_plan is not None
        else None
    )
    execution_authority = (
        goal_execution.authority if goal_execution is not None else None
    )
    authoring_authority = (
        goal_execution.authoring_authority
        if goal_execution is not None
        else None
    )
    authority_error: Exception | None = None
    if parsed is not None and goal_execution is None:
        try:
            authoring_authority = _lower_authority(parsed, fixture)
        except Exception as exc:
            authority_error = exc
            if error is None:
                error = exc
    replay = goal_execution.replay if goal_execution is not None else None
    sample_result = _sample_result(
        problem_id=case.problem_id,
        sample_id=sample_id,
        sample_dir=sample_dir,
        validation=validation,
        structure_report=structure_report,
        authority=authoring_authority,
        replay=replay,
        checkpoint=(
            goal_execution.checkpoint if goal_execution is not None else None
        ),
        leaks=leaks,
        raw_response=raw_response,
        client=base_client,
        duration_seconds=perf_counter() - started,
        error=error,
    )
    _write_sample_artifacts(
        sample_dir,
        fixture=fixture,
        payload=expected_payload,
        prompt=expected_prompt,
        raw_response=raw_response,
        validation=validation,
        raw_structure_report=raw_structure_report,
        structure_report=structure_report,
        parsed=parsed,
        structurally_normalized_plan=structurally_normalized_plan,
        goal_normalizations=goal_normalizations,
        authoring_authority=authoring_authority,
        execution_authority=execution_authority,
        authority_error=authority_error,
        goal_execution=goal_execution,
        client=base_client,
        request=client.request,
        error=error,
        sample_result=sample_result,
        thinking_profile=thinking_profile,
    )
    return sample_result


def _build_planner_authority(
    case: GoldCorpusCase,
    sample_dir: Path,
    f2_root: Path,
) -> _PlannerAuthorityFixture:
    root_context, f2_context = _load_f2_context(case, f2_root)
    store = ExtractionArtifactStore(sample_dir / "bundle-artifacts")
    validation = ProblemDomainValidator().validate(
        ProblemDraft.create(_load_domain_gold(case.problem_id))
    )
    if not validation.report.ok or validation.projection is None:
        raise ValueError("planner.problem_bundle_invalid: domain fixture failed validation")
    verified = ProblemPromotionService().promote(validation.draft)
    projection = validation.projection
    verified_ref = store.put_json(
        kind="verified_problem",
        payload=verified.to_payload(),
    )
    projection_ref = store.put_json(
        kind=SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
        payload=projection.to_payload(),
    )
    validation_ref = store.put_json(
        kind="problem_validation_report",
        payload=validation.report.to_payload(),
    )
    accepted = ProblemDomainContextTransitionService().accepted(
        f2_context,
        verified_problem=verified,
        solver_projection=projection,
        verified_artifact=verified_ref,
        solver_problem_projection_artifact=projection_ref,
        validation_artifact=validation_ref,
        attempt_ledger=ExtractionAttemptLedger.for_context(f2_context),
        ancestor_contexts=(root_context,),
    )
    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root_context, f2_context),
    )
    planning_context = ProblemPlanningContextProjector().project(bundle)
    problem = bundle.build_solver_problem()
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    planner_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    binding_catalog = ProblemPlanningBindingCatalogBuilder().build(
        bundle,
        planning_context,
        planner_context,
        registry,
        expected_token=bundle.authority_token,
    )
    return _PlannerAuthorityFixture(
        bundle=bundle,
        planning_context=planning_context,
        inputs=inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
        planner_state_context=planner_context,
        binding_catalog=binding_catalog,
        runtime_context=ContextBuilder().build(problem),
    )


def _lower_authority(
    plan: ScopedFunctionalPlan,
    fixture: _PlannerAuthorityFixture,
) -> ScopedFunctionalPlanAuthority:
    from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
        FunctionalCapabilityCatalog,
    )

    authority, report = ScopedFunctionalPlanAuthorityAdapter().analyze(
        plan,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            fixture.inputs.family_spec,
            fixture.inputs.method_specs,
        ),
    )
    if authority is None:
        first = report.first_issue
        assert first is not None
        raise ScopedFunctionalPlanError(
            first.code,
            first.path,
            first.message,
            issues=report.issues,
            normalizations=report.normalizations,
        )
    return authority


def _sample_result(
    *,
    problem_id: str,
    sample_id: str,
    sample_dir: Path,
    validation: ScopedFunctionalPlanValidationReport,
    structure_report: ScopedFunctionalStructureReport | None,
    authority: ScopedFunctionalPlanAuthority | None,
    replay: Any | None,
    checkpoint: FunctionalGoalExecutionCheckpoint | None,
    leaks: tuple[str, ...],
    raw_response: str,
    client: DeepSeekPlannerClient,
    duration_seconds: float,
    error: Exception | None,
) -> ScopedV2SmokeSampleResult:
    reconciliation = replay.functional_reconciliation if replay is not None else None
    attempt = replay.transactional_attempt_result if replay is not None else None
    goal_report = attempt.goal_report if attempt is not None else None
    goals = tuple(goal_report.goals) if goal_report is not None else ()
    compiled = attempt.compiled_output if attempt is not None else None
    checkpoint_metrics = (
        checkpoint.to_prompt_payload()["metrics"]
        if checkpoint is not None
        else {}
    )
    transaction_ok = bool(
        checkpoint_metrics.get(
            "transaction_ok",
            attempt is not None and not attempt.root_issues,
        )
    )
    error_code, error_message = _error_details(error)
    if error_code is None and checkpoint is not None:
        checkpoint_issue = _first_checkpoint_issue(checkpoint)
        if checkpoint_issue is not None:
            error_code = str(checkpoint_issue.get("code") or "functional.execution_blocked")
            error_message = str(
                checkpoint_issue.get("message") or "incremental execution was blocked"
            )
    configuration_error_count = int(
        bool(error_code and "configuration" in error_code)
        or bool(error_message and "planner_configuration_error" in error_message)
    )
    unclassified_error_count = int(
        error is not None
        and error_code == "unclassified_error"
    )
    return ScopedV2SmokeSampleResult(
        problem_id=problem_id,
        sample_id=sample_id,
        provider_response_received=bool(raw_response.strip()),
        provider_sub_attempt_count=len(client.last_provider_attempts),
        schema_valid=validation.ok,
        scope_goal_tree_ok=bool(
            structure_report is not None and structure_report.ok
        ),
        plan_authority_ok=authority is not None,
        prompt_identity_leaks=leaks,
        reconciliation_ok=bool(reconciliation is not None and reconciliation.ok),
        compile_ok=compiled is not None,
        transaction_ok=transaction_ok,
        transaction_attempted=bool(
            checkpoint_metrics.get("transaction_attempted", attempt is not None)
        ),
        authority_valid_step_count=int(
            checkpoint_metrics.get("authority_valid_step_count", 0)
        ),
        authority_invalid_step_count=int(
            checkpoint_metrics.get("authority_invalid_step_count", 0)
        ),
        pruned_dead_step_count=int(
            checkpoint_metrics.get("pruned_dead_step_count", 0)
        ),
        provisional_executed_step_count=int(
            checkpoint_metrics.get("provisional_executed_step_count", 0)
        ),
        blocked_by_dependency_step_count=int(
            checkpoint_metrics.get("blocked_by_dependency_step_count", 0)
        ),
        blocked_stage=(
            str(checkpoint_metrics["blocked_stage"])
            if checkpoint_metrics.get("blocked_stage") is not None
            else None
        ),
        passed_goal_count=sum(item.status == "passed" for item in goals),
        goal_count=len(goals),
        output_ok=bool(replay is not None and replay.output is not None),
        configuration_error_count=configuration_error_count,
        unclassified_error_count=unclassified_error_count,
        usage={
            key: int(value)
            for key, value in (client.last_usage or {}).items()
            if isinstance(value, int)
        },
        duration_seconds=round(duration_seconds, 3),
        error_code=error_code,
        error_message=error_message,
        sample_dir=str(sample_dir),
    )


def _prompt_identity_leaks(
    text: str,
    *,
    bundle: VerifiedSolverProblemBundle,
    planning_context: ProblemPlanningContext,
) -> tuple[str, ...]:
    forbidden = {
        "source_unit_id",
        "runtime_node_id",
        "MathObjectId",
        "StateVersionId",
        bundle.authority_token.bundle_id,
        bundle.authority_token.extraction_context_id,
        bundle.authority_token.problem_revision_id,
        bundle.authority_token.problem_semantic_hash,
        planning_context.planning_context_id,
    }
    for authority in planning_context.ref_authorities.values():
        forbidden.add(authority.runtime_node_id)
        forbidden.update(authority.source_unit_ids)
    return tuple(sorted(item for item in forbidden if item and item in text))


def _write_sample_artifacts(
    sample_dir: Path,
    *,
    fixture: _PlannerAuthorityFixture,
    payload: Mapping[str, Any],
    prompt: Any,
    raw_response: str,
    validation: ScopedFunctionalPlanValidationReport,
    raw_structure_report: ScopedFunctionalStructureReport | None,
    structure_report: ScopedFunctionalStructureReport | None,
    parsed: ScopedFunctionalPlan | None,
    structurally_normalized_plan: ScopedFunctionalPlan | None,
    goal_normalizations: Sequence[Any],
    authoring_authority: ScopedFunctionalPlanAuthority | None,
    execution_authority: ScopedFunctionalPlanAuthority | None,
    authority_error: Exception | None,
    goal_execution: ScopedFunctionalGoalExecutionResult | None,
    client: DeepSeekPlannerClient,
    request: Mapping[str, Any] | None,
    error: Exception | None,
    sample_result: ScopedV2SmokeSampleResult,
    thinking_profile: SmokeThinkingProfile,
) -> None:
    replay = goal_execution.replay if goal_execution is not None else None
    checkpoint = (
        goal_execution.checkpoint if goal_execution is not None else None
    )
    canonical_plan_payload = (
        authoring_authority.scoped_plan.to_payload()
        if authoring_authority is not None
        else (
            structurally_normalized_plan.to_payload()
            if structurally_normalized_plan is not None
            else None
        )
    )
    (sample_dir / "prompt.system.md").write_text(prompt.system, encoding="utf-8")
    (sample_dir / "prompt.user.md").write_text(prompt.user, encoding="utf-8")
    (sample_dir / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    _write_json(sample_dir / "payload.json", payload)
    for key in (
        "problem_planning_context",
        "functional_capability_catalog",
        "few_shot_examples",
        "output_json_schema",
    ):
        _write_json(sample_dir / f"payload.{key}.json", payload.get(key))
    _write_json(
        sample_dir / "provider-request.redacted.json",
        {
            key: value
            for key, value in (request or {}).items()
            if key not in {"messages", "planner_payload"}
        },
    )
    llm_metadata = {
        "request_model": client.model,
        "response_model": client.last_response_model,
        "thinking": "enabled" if thinking_profile == "low" else "disabled",
        "reasoning_effort": "low" if thinking_profile == "low" else None,
        "thinking_profile": thinking_profile,
        "temperature": client.temperature,
        "usage": client.last_usage,
        "provider_attempts": list(client.last_provider_attempts),
    }
    _write_json(sample_dir / "llm-metadata.json", llm_metadata)
    _write_json(sample_dir / "contract-validation.json", validation.to_payload())
    _write_json(
        sample_dir / "scope-goal-structure-input-report.json",
        (
            raw_structure_report.to_payload()
            if raw_structure_report is not None
            else None
        ),
    )
    _write_json(
        sample_dir / "scope-goal-normalizations.json",
        [item.to_payload() for item in goal_normalizations],
    )
    _write_json(
        sample_dir / "scope-goal-structure-report.json",
        structure_report.to_payload() if structure_report is not None else None,
    )
    _write_json(
        sample_dir / "scoped-functional-plan.json",
        parsed.to_payload() if parsed is not None else None,
    )
    _write_json(
        sample_dir / "normalized-scoped-functional-plan.json",
        canonical_plan_payload,
    )
    _write_json(
        sample_dir / "scoped-plan-authority.json",
        (
            authoring_authority.authority_payload()
            if authoring_authority is not None
            else None
        ),
    )
    authority_report_payload = (
        goal_execution.authority_report.to_payload()
        if goal_execution is not None
        else _authority_report_payload(
            authoring_authority,
            authority_error,
            fallback_normalizations=goal_normalizations,
        )
    )
    _write_json(
        sample_dir / "scoped-plan-authority-report.json",
        authority_report_payload,
    )
    _write_json(sample_dir / "problem-bundle-authority.json", fixture.bundle.authority_payload())
    _write_json(
        sample_dir / "problem-binding-catalog.json",
        fixture.binding_catalog.authority_payload(),
    )
    _write_json(
        sample_dir / "functional-replay.json",
        replay.to_payload() if replay is not None else None,
    )
    _write_json(
        sample_dir / "effective-execution-plan.json",
        (
            execution_authority.lowered_plan.to_payload()
            if execution_authority is not None
            else None
        ),
    )
    _write_json(
        sample_dir / "functional-goal-execution-checkpoint.json",
        checkpoint.authority_payload() if checkpoint is not None else None,
    )
    _write_json(
        sample_dir / "functional-goal-execution-checkpoint.prompt.json",
        checkpoint.to_prompt_payload() if checkpoint is not None else None,
    )
    _write_json(
        sample_dir / "functional-reconciliation.json",
        (
            replay.functional_reconciliation.to_payload()
            if replay is not None and replay.functional_reconciliation is not None
            else None
        ),
    )
    _write_json(
        sample_dir / "transaction.json",
        (
            replay.transactional_attempt_result.to_payload()
            if replay is not None and replay.transactional_attempt_result is not None
            else None
        ),
    )
    _write_json(
        sample_dir / "structured-error.json",
        (
            {
                "code": sample_result.error_code,
                "message": sample_result.error_message,
            }
            if sample_result.error_code is not None
            else None
        ),
    )
    _write_json(sample_dir / "sample-result.json", sample_result.to_payload())
    _write_sample_review(
        sample_dir,
        result_payload=sample_result.to_payload(),
        raw_response=raw_response,
        validation_payload=validation.to_payload(),
        problem_view_payload=payload["problem_planning_context"],
        plan_payload=parsed.to_payload() if parsed is not None else None,
        normalized_plan_payload=canonical_plan_payload,
        raw_structure_report_payload=(
            raw_structure_report.to_payload()
            if raw_structure_report is not None
            else None
        ),
        goal_normalizations_payload=[
            item.to_payload() for item in goal_normalizations
        ],
        structure_report_payload=(
            structure_report.to_payload()
            if structure_report is not None
            else None
        ),
        authority_report_payload=authority_report_payload,
        llm_metadata=llm_metadata,
        return_expectation_policies_payload=(
            _used_return_expectation_policies(
                payload.get("functional_capability_catalog"),
                parsed.to_payload() if parsed is not None else None,
            )
        ),
        checkpoint_payload=(
            checkpoint.to_prompt_payload() if checkpoint is not None else None
        ),
    )


def _authority_report_payload(
    authority: ScopedFunctionalPlanAuthority | None,
    error: Exception | None,
    *,
    fallback_normalizations: Sequence[Any] = (),
) -> dict[str, Any]:
    issues = (
        [item.to_payload() for item in error.issues]
        if isinstance(error, ScopedFunctionalPlanError)
        else []
    )
    code, message = _error_details(error)
    return {
        "ok": authority is not None,
        "first_issue": issues[0] if issues else (
            {"code": code, "message": message}
            if error is not None
            else None
        ),
        "issues": issues,
        "normalizations": (
            [item.to_payload() for item in authority.normalizations]
            if authority is not None
            else [
                item.to_payload()
                for item in (
                    error.normalizations
                    if isinstance(error, ScopedFunctionalPlanError)
                    and error.normalizations
                    else fallback_normalizations
                )
            ]
        ),
    }


def _batch_summary(
    config: Mapping[str, Any],
    results: Sequence[ScopedV2SmokeSampleResult],
) -> dict[str, Any]:
    total = len(results)
    usage: dict[str, int] = {}
    for result in results:
        for key, value in result.usage.items():
            usage[key] = usage.get(key, 0) + value
    summary = {
        **dict(config),
        "finished_at": datetime.now().astimezone().isoformat(),
        "sample_count": total,
        "primary_passed": sum(item.primary_ok for item in results),
        "schema_valid_count": sum(item.schema_valid for item in results),
        "scope_goal_tree_ok_count": sum(
            item.scope_goal_tree_ok for item in results
        ),
        "plan_authority_ok_count": sum(
            item.plan_authority_ok for item in results
        ),
        "prompt_identity_leak_count": sum(
            len(item.prompt_identity_leaks) for item in results
        ),
        "configuration_error_count": sum(
            item.configuration_error_count for item in results
        ),
        "unclassified_error_count": sum(
            item.unclassified_error_count for item in results
        ),
        "reconciliation_ok_count": sum(item.reconciliation_ok for item in results),
        "compile_ok_count": sum(item.compile_ok for item in results),
        "transaction_ok_count": sum(item.transaction_ok for item in results),
        "transaction_attempted_count": sum(
            item.transaction_attempted for item in results
        ),
        "authority_valid_step_count": sum(
            item.authority_valid_step_count for item in results
        ),
        "authority_invalid_step_count": sum(
            item.authority_invalid_step_count for item in results
        ),
        "pruned_dead_step_count": sum(
            item.pruned_dead_step_count for item in results
        ),
        "provisional_executed_step_count": sum(
            item.provisional_executed_step_count for item in results
        ),
        "blocked_by_dependency_step_count": sum(
            item.blocked_by_dependency_step_count for item in results
        ),
        "output_ok_count": sum(item.output_ok for item in results),
        "usage": usage,
        "samples": [item.to_payload() for item in results],
    }
    summary["primary_gate_ok"] = (
        summary["primary_passed"] == total
        and summary["prompt_identity_leak_count"] == 0
        and summary["configuration_error_count"] == 0
        and summary["unclassified_error_count"] == 0
    )
    return summary


def _unclassified_result(
    problem_id: str,
    sample_id: str,
    sample_dir: Path,
    error: Exception,
) -> ScopedV2SmokeSampleResult:
    return ScopedV2SmokeSampleResult(
        problem_id=problem_id,
        sample_id=sample_id,
        provider_response_received=False,
        provider_sub_attempt_count=0,
        schema_valid=False,
        scope_goal_tree_ok=False,
        plan_authority_ok=False,
        prompt_identity_leaks=(),
        reconciliation_ok=False,
        compile_ok=False,
        transaction_ok=False,
        transaction_attempted=False,
        authority_valid_step_count=0,
        authority_invalid_step_count=0,
        pruned_dead_step_count=0,
        provisional_executed_step_count=0,
        blocked_by_dependency_step_count=0,
        blocked_stage="provider",
        passed_goal_count=0,
        goal_count=0,
        output_ok=False,
        configuration_error_count=0,
        unclassified_error_count=1,
        usage={},
        duration_seconds=0.0,
        error_code="unclassified_error",
        error_message=f"{error.__class__.__name__}: {error}",
        sample_dir=str(sample_dir),
    )


def _error_details(error: Exception | None) -> tuple[str | None, str | None]:
    if error is None:
        return None, None
    if isinstance(error, ScopedFunctionalPlanError):
        return error.code, str(error)
    if isinstance(error, LLMProviderResponseError):
        return error.code, str(error)
    if "planner_configuration_error" in str(error):
        return "planner_configuration_error", str(error)
    return "unclassified_error", f"{error.__class__.__name__}: {error}"


def _first_checkpoint_issue(
    checkpoint: FunctionalGoalExecutionCheckpoint,
) -> Mapping[str, Any] | None:
    if checkpoint.root_issues:
        return checkpoint.root_issues[0]

    def visit(scope: Any) -> Mapping[str, Any] | None:
        for step in scope.scope_steps:
            if step.typed_issue is not None:
                return step.typed_issue
        for goal in scope.goals:
            for step in goal.steps:
                if step.typed_issue is not None:
                    return step.typed_issue
        for child in scope.children:
            issue = visit(child)
            if issue is not None:
                return issue
        return None

    return visit(checkpoint.root_scope)


def _write_sample_review(
    sample_dir: Path,
    *,
    result_payload: Mapping[str, Any],
    raw_response: str,
    validation_payload: Mapping[str, Any],
    problem_view_payload: Mapping[str, Any],
    plan_payload: Mapping[str, Any] | None,
    normalized_plan_payload: Mapping[str, Any] | None,
    raw_structure_report_payload: Mapping[str, Any] | None,
    goal_normalizations_payload: Sequence[Mapping[str, Any]],
    structure_report_payload: Mapping[str, Any] | None,
    authority_report_payload: Mapping[str, Any],
    llm_metadata: Mapping[str, Any],
    return_expectation_policies_payload: Sequence[Mapping[str, Any]] = (),
    checkpoint_payload: Mapping[str, Any] | None = None,
) -> None:
    problem_id = str(result_payload.get("problem_id", "unknown-problem"))
    sample_id = str(result_payload.get("sample_id", "sample"))
    llm_config = _pretty_json(
        {
            key: llm_metadata.get(key)
            for key in (
                "request_model",
                "response_model",
                "thinking",
                "reasoning_effort",
                "thinking_profile",
                "temperature",
            )
        }
    )
    execution_summary = {
        key: result_payload.get(key)
        for key in (
            "primary_ok",
            "schema_valid",
            "scope_goal_tree_ok",
            "plan_authority_ok",
            "reconciliation_ok",
            "compile_ok",
            "transaction_ok",
            "transaction_attempted",
            "authority_valid_step_count",
            "authority_invalid_step_count",
            "pruned_dead_step_count",
            "provisional_executed_step_count",
            "blocked_by_dependency_step_count",
            "blocked_stage",
            "passed_goal_count",
            "goal_count",
            "output_ok",
            "error_code",
        )
    }
    plan_display = plan_payload if plan_payload is not None else {"raw": raw_response}
    html = f"""<!doctype html>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>{escape(problem_id)} · {escape(sample_id)}</title>
<style>
body{{font:14px/1.5 system-ui,-apple-system,sans-serif;margin:24px;max-width:1200px;color:#172033}}
nav{{position:sticky;top:0;background:#fff;padding:10px 0;border-bottom:1px solid #d7dce3}}
nav a{{margin-right:14px;color:#0759b8}}section{{padding:18px 0;border-bottom:1px solid #e3e6ea}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f6f7f8;border:1px solid #e0e3e7;padding:14px;overflow:auto}}
.note{{color:#536070}}.ok{{color:#117a37;font-weight:700}}.bad{{color:#b42318;font-weight:700}}
</style>
<h1>{escape(problem_id)} · {escape(sample_id)}</h1>
<nav>
  <a href=\"#config\">LLM配置</a>
  <a href=\"#problem-json\">Problem JSON</a>
  <a href=\"payload.problem_planning_context.json\">Problem JSON文件</a>
  <a href=\"#model-plan\">模型Plan</a>
  <a href=\"scoped-functional-plan.json\">Plan JSON文件</a>
  <a href=\"normalized-scoped-functional-plan.json\">归一Plan文件</a>
  <a href=\"#structure\">Scope/Goal</a>
  <a href=\"#authority\">Plan Authority</a>
  <a href=\"#execution\">执行诊断</a>
  <a href=\"functional-goal-execution-checkpoint.prompt.json\">Goal Checkpoint</a>
  <a href=\"prompt.system.md\">System</a>
  <a href=\"prompt.user.md\">User</a>
</nav>
<section id=\"config\"><h2>1. LLM配置</h2><pre>{escape(llm_config)}</pre></section>
<section id=\"problem-json\">
  <h2>2. Problem JSON sent to LLM</h2>
  <p class=\"note\">这是Prompt中实际发送给模型的 <code>planner-problem-view/v2</code> 题目权威；不是Bundle、canonical ProblemIR或BindingCatalog。</p>
  <pre>{escape(_pretty_json(problem_view_payload))}</pre>
</section>
<section id=\"model-plan\">
  <h2>3. 模型输出 FunctionalPlan v2</h2>
  <pre>{escape(_pretty_json(plan_display))}</pre>
  <details><summary>Schema / JSON contract validation</summary><pre>{escape(_pretty_json(validation_payload))}</pre></details>
  <details><summary>Provider raw response</summary><pre>{escape(raw_response)}</pre></details>
</section>
<section id=\"structure\">
  <h2>4. Scope / Goal结构对比</h2>
  <p class=\"{'ok' if result_payload.get('scope_goal_tree_ok') else 'bad'}\">scope_goal_tree_ok={escape(str(result_payload.get('scope_goal_tree_ok')))}</p>
  <h3>模型原始结构</h3>
  <pre>{escape(_pretty_json(raw_structure_report_payload))}</pre>
  <h3>确定性Goal归一</h3>
  <pre>{escape(_pretty_json(goal_normalizations_payload))}</pre>
  <h3>归一后的Plan</h3>
  <pre>{escape(_pretty_json(normalized_plan_payload))}</pre>
  <h3>归一后结构权威</h3>
  <pre>{escape(_pretty_json(structure_report_payload))}</pre>
</section>
<section id=\"authority\">
  <h2>5. 完整Plan Authority</h2>
  <p class=\"{'ok' if result_payload.get('plan_authority_ok') else 'bad'}\">plan_authority_ok={escape(str(result_payload.get('plan_authority_ok')))}</p>
  <h3>Capability / MathObject安全归一</h3>
  <pre>{escape(_pretty_json(authority_report_payload.get('normalizations', [])))}</pre>
  <h3>本Plan使用的Return expectation policy</h3>
  <pre>{escape(_pretty_json(return_expectation_policies_payload))}</pre>
  <h3>Authority issues</h3>
  <pre>{escape(_pretty_json(authority_report_payload))}</pre>
</section>
<section id=\"execution\">
  <h2>6. 增量Goal执行 / Transaction诊断</h2>
  <pre>{escape(_pretty_json(execution_summary))}</pre>
  <h3>Prompt-safe scope-shaped checkpoint</h3>
  <pre>{escape(_pretty_json(checkpoint_payload))}</pre>
  <p><a href=\"effective-execution-plan.json\">Effective Plan</a> · <a href=\"functional-goal-execution-checkpoint.json\">Checkpoint Authority</a> · <a href=\"functional-reconciliation.json\">Reconciliation JSON</a> · <a href=\"transaction.json\">Transaction JSON</a></p>
</section>"""
    _audit_review_html(html)
    (sample_dir / "review.html").write_text(html, encoding="utf-8")


def _used_return_expectation_policies(
    catalog_payload: object,
    plan_payload: object,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(catalog_payload, Mapping) or not isinstance(
        plan_payload, Mapping
    ):
        return ()
    used_capabilities = {
        str(item["capability_id"])
        for item in _walk_mapping_values(plan_payload)
        if isinstance(item.get("capability_id"), str)
    }
    capabilities = catalog_payload.get("capabilities")
    if not isinstance(capabilities, list):
        return ()
    result: list[dict[str, Any]] = []
    for capability in capabilities:
        if (
            not isinstance(capability, Mapping)
            or capability.get("capability_id") not in used_capabilities
        ):
            continue
        returns = capability.get("returns")
        if not isinstance(returns, list):
            continue
        result.append(
            {
                "capability_id": capability["capability_id"],
                "returns": [
                    {
                        key: returned[key]
                        for key in (
                            "name",
                            "type",
                            "return_expectation_policy",
                            "possible_forms",
                        )
                        if key in returned
                    }
                    for returned in returns
                    if isinstance(returned, Mapping)
                ],
            }
        )
    return tuple(sorted(result, key=lambda item: str(item["capability_id"])))


def _walk_mapping_values(value: object) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        result.append(value)
        for child in value.values():
            result.extend(_walk_mapping_values(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_walk_mapping_values(child))
    return tuple(result)


def _pretty_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )


def _audit_review_html(html: str) -> None:
    forbidden = (
        "source_unit_id",
        "runtime_node_id",
        "bundle_authority_token",
        "MathObjectId",
        "StateVersionId",
    )
    leaked = [item for item in forbidden if item in html]
    if leaked:
        raise ValueError(
            "review page contains internal authority identity: "
            + ", ".join(leaked)
        )


def _write_batch_index(
    batch_dir: Path,
    results: Sequence[ScopedV2SmokeSampleResult],
    summary: Mapping[str, Any],
) -> None:
    rows = "".join(
        "<tr>"
        f"<td><a href=\"{escape(Path(item.sample_dir).relative_to(batch_dir).as_posix())}/review.html\">{escape(item.problem_id)}</a></td>"
        f"<td>{escape(item.sample_id)}</td><td>{item.primary_ok}</td>"
        f"<td>{item.schema_valid}</td><td>{item.scope_goal_tree_ok}</td>"
        f"<td>{item.plan_authority_ok}</td>"
        f"<td>{item.transaction_ok}</td><td>{escape(item.error_code or '')}</td>"
        "</tr>"
        for item in results
    )
    html = f"""<!doctype html><meta charset=\"utf-8\"><title>FunctionalPlan v2 5x1</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:7px;text-align:left}}</style>
<h1>FunctionalPlan v2 5x1</h1><p>primary_gate_ok={summary['primary_gate_ok']} · primary_passed={summary['primary_passed']}/{summary['sample_count']} · thinking={escape(str(summary.get('thinking')))} · reasoning_effort={escape(str(summary.get('reasoning_effort')))}</p>
<table><thead><tr><th>Problem</th><th>Sample</th><th>Primary</th><th>Schema</th><th>Scope/Goal tree</th><th>Plan authority</th><th>Transaction</th><th>Error</th></tr></thead><tbody>{rows}</tbody></table>"""
    (batch_dir / "index.html").write_text(html, encoding="utf-8")


def rerender_existing_batch(batch_dir: Path) -> int:
    """Regenerate historical sample HTML without mutating recorded JSON."""

    rendered = 0
    validator = ScopedFunctionalPlanValidator()
    for result_path in sorted(batch_dir.glob("*/sample-*/sample-result.json")):
        sample_dir = result_path.parent
        result_payload = _read_json(result_path)
        if not isinstance(result_payload, dict):
            raise TypeError(f"sample result is not an object: {result_path}")
        old_authority_ok = bool(
            result_payload.pop(
                "scope_goal_authority_ok",
                result_payload.get("plan_authority_ok", False),
            )
        )
        problem_view_payload = _read_json(
            sample_dir / "payload.problem_planning_context.json"
        )
        if not isinstance(problem_view_payload, dict):
            raise TypeError(
                f"Planner Problem View is not an object: {sample_dir}"
            )
        plan_payload = _read_json(sample_dir / "scoped-functional-plan.json")
        parsed: ScopedFunctionalPlan | None = None
        if isinstance(plan_payload, dict):
            parsed, _ = validator.validate_payload_with_report(plan_payload)
        structure_report = (
            audit_scoped_functional_structure_prompt_payload(
                parsed,
                problem_view_payload,
            )
            if parsed is not None
            else None
        )
        result_payload["scope_goal_tree_ok"] = bool(
            structure_report is not None and structure_report.ok
        )
        result_payload["plan_authority_ok"] = old_authority_ok
        validation_payload = _read_json(sample_dir / "contract-validation.json")
        if not isinstance(validation_payload, dict):
            validation_payload = {"ok": False, "issues": []}
        llm_metadata = _read_json(sample_dir / "llm-metadata.json")
        if not isinstance(llm_metadata, dict):
            llm_metadata = {}
        structured_error = _read_json(sample_dir / "structured-error.json")
        authority_error = (
            structured_error
            if not old_authority_ok and isinstance(structured_error, dict)
            else None
        )
        raw_response = (sample_dir / "raw-response.txt").read_text(
            encoding="utf-8"
        )
        _write_sample_review(
            sample_dir,
            result_payload=result_payload,
            raw_response=raw_response,
            validation_payload=validation_payload,
            problem_view_payload=problem_view_payload,
            plan_payload=plan_payload if isinstance(plan_payload, dict) else None,
            normalized_plan_payload=(
                plan_payload if isinstance(plan_payload, dict) else None
            ),
            raw_structure_report_payload=(
                structure_report.to_payload()
                if structure_report is not None
                else None
            ),
            goal_normalizations_payload=(),
            structure_report_payload=(
                structure_report.to_payload()
                if structure_report is not None
                else None
            ),
            authority_report_payload={
                "ok": old_authority_ok,
                "error": authority_error,
            },
            llm_metadata=llm_metadata,
        )
        rendered += 1
    return rendered


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
