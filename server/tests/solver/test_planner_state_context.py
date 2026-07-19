from __future__ import annotations

from dataclasses import replace
from importlib import util
import json
from pathlib import Path

# Transitional domain split: shared fixtures/helpers still live in
# test_strategy_planner_phase1.py until the support module is extracted.
_base_path = Path(__file__).with_name("test_strategy_planner_phase1.py")
_spec = util.spec_from_file_location("_strategy_planner_phase1_base", _base_path)
assert _spec is not None and _spec.loader is not None
_base = util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
for _name in dir(_base):
    if _name.startswith("__") or _name.startswith("test_"):
        continue
    globals()[_name] = getattr(_base, _name)
del _name, _base, _base_path, _spec, util

from shuxueshuo_server.solver.runtime.planner_state_context import (  # noqa: E402
    ContextManifest,
    DraftSnapshots,
    PlannerStateContextBuilder,
    PlannerState,
    PlannerStateContext,
    RetryMemory,
    ScopeGraph,
    StableStep,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.family import (  # noqa: E402
    CapabilityContractSpec,
    StateSlotPattern,
)
from shuxueshuo_server.solver.runtime.strategy_models import (  # noqa: E402
    StepIntentAcceptedStep,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationReport,
    StepIntentValidationReport,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.strategy_output_types import (  # noqa: E402
    canonicalize_produced_output_types,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (  # noqa: E402
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.planner_retry_projection import (  # noqa: E402
    PlannerRetryStateProjector,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (  # noqa: E402
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
    _planner_state_context_from_replay,
)


def test_planner_state_context_initial_snapshot_is_json_serializable() -> None:
    """Initial context should snapshot registry-visible planner state."""
    ctx = initial_planner_state_context(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )
    payload = ctx.to_payload()

    assert payload["manifest"]["context_type"] == "planner"
    assert "problem" in payload["state"]["scope_graph"]["scope_ids"]
    assert payload["state"]["alias_index"]["by_handle"]["point:problem:D"].startswith(
        "point:D@problem"
    )
    m_coordinate_slots = [
        item
        for item in ctx.state.state_slots
        if item.object_ref == "point:ii:M" and item.runtime_type == "Point"
    ]
    assert any(
        item.free_symbol_refs == ("symbol:problem:m",)
        for item in m_coordinate_slots
    )
    assert any(
        item["kind"] == "coefficient_relation"
        for item in payload["state"]["conditions"]
    )
    right_angle = next(
        item
        for item in payload["state"]["conditions"]
        if item["kind"] == "right_angle_equal_length"
    )
    assert right_angle["object_roles"] == {
        "anchor": ["point:problem:D"],
        "endpoint": ["point:ii:M", "point:ii:N"],
    }
    contract_ids = {
        item["capability_id"]
        for item in payload["state"]["capability_contracts"]
    }
    assert "quadratic_from_constraints" in contract_ids
    assert "distance_between_points" in contract_ids
    sources = {
        item["capability_id"]: item["source"]
        for item in payload["state"]["capability_contracts"]
    }
    assert sources["quadratic_from_constraints"] == "explicit"
    assert "projected" in set(sources.values())
    point_d = next(
        item
        for item in payload["state"]["math_objects"]
        if item["canonical_handle"] == "point:problem:D"
    )
    assert point_d["valid_scope"] == "problem"
    assert "source_step_id" not in point_d
    json.dumps(payload, ensure_ascii=False)


def test_planner_state_context_scope_graph_and_valid_scope_are_explicit() -> None:
    """Context should expose scope ancestry and fact valid_scope metadata."""
    ctx = PlannerStateContextBuilder.initial_from_inputs(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )

    assert ctx.state.scope_graph.scope_parents["ii"] == "problem"
    assert ctx.state.scope_graph.scope_parents["ii_1"] == "ii"
    coefficient_relation = next(
        item
        for item in ctx.state.conditions
        if item.canonical_handle == "fact:problem:coefficient_relation"
    )
    assert coefficient_relation.scope_id == "problem"
    assert coefficient_relation.valid_scope == "problem"


def test_context_records_internal_symbol_and_ordered_point_transitions() -> None:
    """Companion Symbols and same-object Point transitions become Context memory."""
    root = Path(__file__).resolve().parents[3]
    problem = load_problem_ir(
        str(root / "internal/solver-fixtures/tj-2026-heping-ermo-25.json")
    )
    inputs = build_strategy_probe_inputs(problem)
    payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(payload)
    raw = (
        root
        / "internal/solver-fixtures/tj-2026-heping-ermo-25.executable-step-intents.json"
    ).read_text(encoding="utf-8")
    draft = StepIntentValidator().validate_json(
        raw,
        question_goals=inputs.question_goals,
        handle_registry=registry,
        family_spec=inputs.family_spec,
    )
    output, diagnostic, effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )
    assert output is not None
    assert diagnostic.ok

    replay = PlannerRetryReplayService().replay_from_artifacts(
        attempt=1,
        errors=(),
        raw_draft=draft,
        normalized_draft=effective,
        effective_draft=effective,
        diagnostic=diagnostic,
        output=output,
        inputs=inputs,
        handle_registry=registry,
        problem_payload=payload,
    )
    context = replay.planner_state_context
    assert context is not None
    symbol_slots = [
        item for item in context.state.state_slots
        if item.runtime_type == "Symbol" and item.produced_by is not None
    ]
    assert symbol_slots
    catalog = context.semantic_read_catalog()
    assert any(
        item.kind == "symbol"
        and item.source_step_id == symbol_slots[0].produced_by
        for item in catalog
    )
    transitioned = [
        item for item in context.state.state_slots
        if any(version.write_mode == "transition" for version in item.write_history)
    ]
    assert transitioned
    assert any(len(item.write_history) >= 2 for item in transitioned)


def test_context_semantic_catalog_preserves_hidden_aliases_for_scoped_entity_refs() -> None:
    """Scope-qualified prompt refs should keep hidden short-ref aliases."""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i", "ii")),
        entity_handles=frozenset(("point:i:A", "point:ii:A")),
        fact_handles=frozenset(),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "i": "problem", "ii": "problem"},
        handle_valid_scopes={
            "point:i:A": "i",
            "point:ii:A": "ii",
        },
    )
    ctx = PlannerStateContextBuilder.initial_from_inputs(
        _nankai_inputs(),
        problem_payload={"problem_id": "synthetic-duplicate-entities"},
        handle_registry=registry,
    )

    items = ctx.semantic_read_catalog()
    prompt_refs = {
        (item.handle, item.ref)
        for item in items
        if item.kind == "point" and item.prompt_visible
    }
    hidden_refs = {
        (item.handle, item.ref)
        for item in items
        if item.kind == "point" and not item.prompt_visible
    }

    assert prompt_refs == {
        ("point:i:A", "i.A"),
        ("point:ii:A", "ii.A"),
    }
    assert {
        ("point:i:A", "A"),
        ("point:ii:A", "A"),
        ("point:i:A", "point:i:A"),
        ("point:ii:A", "point:ii:A"),
    }.issubset(hidden_refs)


def test_planner_state_context_records_normalizer_promotion_rewrite() -> None:
    """Normalizer promotion should be represented as a StateSlot alias event."""
    raw_step = _step(
        scope_id="ii",
        step_id="derive_c_expr",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:c_expr_in_a_m",
        produces=(
            ProducedFact(
                "fact:ii:c_expr_in_a_m",
                "ii",
                "由曲线点得到 c 用 a,m 表示的解析式",
                output_type="Expression",
            ),
        ),
    )
    raw_draft = _single_scope_draft(raw_step, scope_id="ii")
    normalized, report = StepIntentNormalizer().normalize(
        raw_draft,
        family_spec=_nankai_inputs().family_spec,
        question_goals=[],
        handle_registry=_registry(),
    )
    normalized, output_type_actions = canonicalize_produced_output_types(
        normalized,
        family_spec=_nankai_inputs().family_spec,
        method_specs=_nankai_inputs().method_specs,
        handle_registry=_registry(),
    )
    report = StepIntentNormalizationReport(
        actions=(*report.actions, *output_type_actions),
        warnings=report.warnings,
    )
    replay = PlannerRetryReplayResult(
        attempt=1,
        raw_draft=raw_draft,
        normalized_draft=normalized,
        normalization_report=report,
    )

    ctx = PlannerStateContextBuilder.from_replay_result(
        replay,
        inputs=_nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )
    ledger = ctx.rewrite_ledger_payload

    assert any(
        item["old_ref"] == "fact:ii:c_expr_in_a_m"
        and item["new_ref"] == "fact:ii:parametric_parabola"
        and item["source_layer"] == "normalization"
        for item in ledger
    )
    alias_index = ctx.state.alias_index.by_handle
    assert (
        alias_index["fact:ii:c_expr_in_a_m"]
        == alias_index["fact:ii:parametric_parabola"]
    )


def test_planner_state_context_stable_prefix_keeps_verified_writes() -> None:
    """StableStep should preserve per-step verified slot writes."""
    step = _step(
        scope_id="i",
        step_id="derive_i_parabola",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:i:parabola_expression",
        produces=(
            ProducedFact(
                "fact:i:parabola_expression",
                "i",
                "第（Ⅰ）问抛物线解析式",
                output_type="Parabola",
            ),
        ),
    )
    draft = _single_scope_draft(step, scope_id="i")
    replay = PlannerRetryReplayResult(
        attempt=1,
        raw_draft=draft,
        normalized_draft=draft,
        effective_draft=draft,
        diagnostic=StepIntentExecutionDiagnostic(
            ok=True,
            accepted_prefix=(
                StepIntentAcceptedStep(
                    step_id="derive_i_parabola",
                    scope_id="i",
                    capability_id="quadratic_from_constraints",
                    method_ids=("quadratic_from_constraints",),
                    produced_handles=("fact:i:parabola_expression",),
                ),
            ),
        ),
    )

    ctx = PlannerStateContextBuilder.from_replay_result(
        replay,
        inputs=_nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )

    assert len(ctx.state.stable_prefix) == 1
    stable = ctx.state.stable_prefix[0]
    assert stable.step_id == "derive_i_parabola"
    assert stable.normalized_payload["step_id"] == "derive_i_parabola"
    assert stable.verified_slot_writes == (
        "function:parabola.expression@i:Parabola",
    )


def test_output_type_canonicalizer_fills_and_overwrites_unique_recipe_output() -> None:
    """Recipe output contract should override missing/wrong LLM output_type hints."""
    step = _step(
        scope_id="i",
        step_id="derive_i_parabola",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:i:parabola_expr",
        produces=(
            ProducedFact(
                "fact:i:parabola_expr",
                "i",
                "第（Ⅰ）问抛物线解析式",
                output_type="Expression",
            ),
        ),
    )

    canonical, actions = canonicalize_produced_output_types(
        _single_scope_draft(step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        method_specs=_nankai_inputs().method_specs,
        handle_registry=_registry(),
    )

    assert canonical.steps[0].produces[0].output_type == "Parabola"
    assert [(action.action, action.handle) for action in actions] == [
        ("infer_output_type", "fact:i:parabola_expr")
    ]


def test_output_type_canonicalizer_leaves_ambiguous_unknown_output_unmodified() -> None:
    """Unknown output shape should remain unresolved for existing failure paths."""
    step = _step(
        scope_id="i",
        step_id="derive_unknown",
        recipe_hint=None,
        goal_type="derive_unknown",
        target="fact:i:raw_result",
        produces=(ProducedFact("fact:i:raw_result", "i", ""),),
    )

    canonical, actions = canonicalize_produced_output_types(
        _single_scope_draft(step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        method_specs=_nankai_inputs().method_specs,
        handle_registry=_registry(),
    )

    assert canonical.steps[0].produces[0].output_type is None
    assert actions == ()


def test_output_type_canonicalizer_does_not_write_optional_transient_point_type() -> None:
    """Optional Point metadata remains absent to avoid typed valueless facts."""
    step = _step(
        scope_id="ii",
        step_id="derive_ii_B_coordinate_expr",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:ii:B_coordinate_expr",
        produces=(
            ProducedFact(
                "fact:ii:B_coordinate_expr",
                "ii",
                "第（Ⅱ）问 B 点坐标表达式",
            ),
        ),
    )

    canonical, actions = canonicalize_produced_output_types(
        _single_scope_draft(step, scope_id="ii"),
        family_spec=_nankai_inputs().family_spec,
        method_specs=_nankai_inputs().method_specs,
        handle_registry=_registry(),
    )

    assert canonical.steps[0].produces[0].output_type is None
    assert actions == ()


def test_output_type_canonicalizer_writes_required_contract_point_type() -> None:
    """A required contract write is authoritative even for transient Point types."""
    step = _step(
        scope_id="ii",
        step_id="derive_ii_B_coordinate_expr",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:ii:B_coordinate_expr",
        produces=(
            ProducedFact(
                "fact:ii:B_coordinate_expr",
                "ii",
                "第（Ⅱ）问 B 点坐标表达式",
            ),
        ),
    )
    inputs = _nankai_inputs()
    required_point_contract = CapabilityContractSpec(
        capability_id="quadratic_x_axis_intercept_point",
        slot_writes=(StateSlotPattern("coordinate", "Point", required=True),),
    )
    family = replace(
        inputs.family_spec,
        capability_contracts=(
            *inputs.family_spec.capability_contracts,
            required_point_contract,
        ),
    )

    canonical, actions = canonicalize_produced_output_types(
        _single_scope_draft(step, scope_id="ii"),
        family_spec=family,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert canonical.steps[0].produces[0].output_type == "Point"
    assert actions
    assert actions[0].action == "infer_output_type"


def test_planner_state_context_fallback_problem_payload_records_warning() -> None:
    """Minimal problem payload fallback should be visible in context issues."""
    inputs = replace(_nankai_inputs(), problem=None)
    ctx = _planner_state_context_from_replay(
        PlannerRetryReplayResult(attempt=1),
        inputs=inputs,
        handle_registry=_registry(),
        problem_payload=None,
    )

    assert ctx.state.problem_ir == {"problem_id": inputs.problem_id, "scopes": []}
    assert any(
        issue.get("code") == "incomplete_problem_payload"
        for issue in ctx.state.issues
    )


def test_write_strategy_debug_artifacts_writes_planner_state_context(
    tmp_path: Path,
) -> None:
    """Debug artifact writer should persist shadow context files."""
    ctx = PlannerStateContextBuilder.initial_from_inputs(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
        handle_registry=_registry(),
    )
    step = _step(
        scope_id="i",
        step_id="derive_i_parabola",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:i:parabola_expr",
    )

    write_strategy_debug_artifacts(
        tmp_path,
        payload={},
        prompt=StrategyPrompt(system="system", user="user"),
        raw_response="{}",
        draft=_single_scope_draft(step, scope_id="i"),
        report=StepIntentValidationReport(ok=True, step_count=1),
        planner_state_context=ctx,
    )

    assert (tmp_path / "planner-state-context.json").exists()
    assert (tmp_path / "context-retry-memory.json").exists()
    assert (tmp_path / "context-derived-retry-state.json").exists()
    assert (tmp_path / "context-baseline-draft.json").exists()
    assert (tmp_path / "context-stable-prefix.json").exists()
    assert (tmp_path / "state-rewrite-ledger.json").exists()
    assert (tmp_path / "context-events.json").exists()
    assert (tmp_path / "context-semantic-read-catalog.json").exists()
    assert json.loads((tmp_path / "planner-state-context.json").read_text())[
        "manifest"
    ]["context_type"] == "planner"


def test_planner_state_context_records_retry_memory_and_parent_context() -> None:
    """Replay should produce a context version whose retry state is a projection."""
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "bad_semantic_read",
                        "recipe_hint": None,
                        "goal_type": "derive_point",
                        "target": "fact:i:temp_point",
                        "strategy": "测试 semantic read 失败。",
                        "reads": [],
                        "semantic_reads": [{"ref": "missing_fact", "kind": "fact"}],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:i:temp_point",
                                "valid_scope": "i",
                                "description": "临时点",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "测试 context retry memory。",
                    }
                ],
            }
        ]
    }
    inputs = replace(
        _nankai_inputs(),
        question_goals=(),
        previous_errors=[
            {
                "planner_state_context_ref": {
                    "context_id": "ctx_planner_previous_attempt",
                }
            }
        ],
    )

    replay = PlannerRetryReplayService().replay_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=inputs,
        handle_registry=_registry(),
        context=_runtime_context(),
        attempt=2,
        problem_payload=_nankai_llm_problem(),
    )

    assert replay.planner_state_context is not None
    assert replay.retry_state is not None
    assert (
        replay.planner_state_context.manifest.parent_context_id
        == "ctx_planner_previous_attempt"
    )
    assert replay.retry_state.source_context_id == replay.planner_state_context.manifest.context_id
    assert replay.planner_state_context.state.retry_memory.issues
    assert replay.planner_state_context.state.retry_memory.baseline_draft is not None


def test_context_retry_projection_ignores_stable_prefix_noise_issue() -> None:
    """Stable-prefix issues should not become the primary repair target."""
    context = PlannerStateContext(
        manifest=ContextManifest(
            context_id="ctx_test_projection",
            context_type="planner",
            schema_version="planner-state-context/v1",
            parent_context_id=None,
            dependency_context_ids=(),
            problem_id="problem",
            family_id="family",
            family_spec_hash="family-hash",
            capability_pack_hash="pack-hash",
        ),
        state=PlannerState(
            problem_ir={},
            expanded_family_spec={},
            scope_graph=ScopeGraph(scope_ids=("problem",), scope_parents={}),
            stable_prefix=(
                StableStep(
                    step_id="derive_known_state",
                    normalized_payload={"step_id": "derive_known_state"},
                ),
            ),
            draft_snapshots=DraftSnapshots(
                effective={
                    "scopes": [
                        {
                            "scope_id": "problem",
                            "steps": [
                                {"step_id": "derive_known_state"},
                                {"step_id": "derive_blocked_state"},
                            ],
                        }
                    ]
                }
            ),
            retry_memory=RetryMemory(
                attempt=1,
                repair_suffix_start={
                    "step_id": "derive_blocked_state",
                    "scope_id": "problem",
                },
                replay_reports={
                    "trial_execution": {
                        "blockers": [
                            {
                                "step_id": "derive_blocked_state",
                                "scope_id": "problem",
                                "code": "recipe_trial_step_failed",
                                "missing_runtime_type": "Parabola",
                            }
                        ]
                    }
                },
                issues=(
                    {
                        "layer": "candidate_resolution",
                        "code": "unsupported_produced_handle_type",
                        "step_id": "derive_known_state",
                        "scope_id": "problem",
                        "repair_target": "step",
                        "message": "stable-prefix noise",
                    },
                    {
                        "layer": "trial_execution",
                        "code": "recipe_trial_step_failed",
                        "step_id": "derive_blocked_state",
                        "scope_id": "problem",
                        "repair_target": "step",
                        "message": "missing runtime state",
                        "related_handles": ["Parabola"],
                    },
                ),
            ),
        ),
    )

    retry_state = PlannerRetryStateProjector.from_context(context)

    assert retry_state is not None
    assert retry_state.issues[0].step_id == "derive_blocked_state"
    assert retry_state.issues[0].layer == "trial_execution"
    assert retry_state.recovered_issues[0].step_id == "derive_known_state"
    assert retry_state.selected_repair_layer == "trial_execution"
    assert "derive_blocked_state" in retry_state.repair_instruction


def test_context_retry_projection_keeps_replay_layer_issue() -> None:
    """Replay-layer context issues should survive retry-state projection."""
    context = PlannerStateContext(
        manifest=ContextManifest(
            context_id="ctx_test_replay_issue",
            context_type="planner",
            schema_version="planner-state-context/v1",
            parent_context_id=None,
            dependency_context_ids=(),
            problem_id="problem",
            family_id="family",
            family_spec_hash="family-hash",
            capability_pack_hash="pack-hash",
        ),
        state=PlannerState(
            problem_ir={},
            expanded_family_spec={},
            scope_graph=ScopeGraph(scope_ids=("problem",), scope_parents={}),
            issues=(
                {
                    "layer": "replay",
                    "code": "error",
                    "message": "synthetic replay failure",
                },
            ),
        ),
    )

    retry_state = PlannerRetryStateProjector.from_context(context)

    assert retry_state is not None
    assert retry_state.issues[0].layer == "replay"
    assert retry_state.issues[0].code == "error"
    assert retry_state.issues[0].message == "synthetic replay failure"
    assert retry_state.selected_repair_layer == "replay"


def test_functional_context_projection_keeps_all_graph_issues_outside_stable_calls() -> None:
    """A runtime-accepted StepIntent prefix cannot recover invalid Functional calls."""
    context = PlannerStateContext(
        manifest=ContextManifest(
            context_id="ctx_functional_graph_issues",
            context_type="planner",
            schema_version="planner-state-context/v1",
            parent_context_id=None,
            dependency_context_ids=(),
            problem_id="problem",
            family_id="family",
            family_spec_hash="family-hash",
            capability_pack_hash="pack-hash",
        ),
        state=PlannerState(
            problem_ir={},
            expanded_family_spec={},
            scope_graph=ScopeGraph(scope_ids=("problem",), scope_parents={}),
            stable_prefix=(
                StableStep(step_id="stable_call", normalized_payload={}),
                StableStep(step_id="invalid_call_a", normalized_payload={}),
                StableStep(step_id="invalid_call_b", normalized_payload={}),
            ),
            retry_memory=RetryMemory(
                attempt=1,
                candidate_format="functional_plan",
                stable_candidate_calls=(
                    {
                        "scope_id": "problem",
                        "call": {"call_id": "stable_call"},
                    },
                ),
                repair_call_ids=("invalid_call_a", "invalid_call_b"),
                repair_suffix_start={"call_id": "invalid_call_a"},
                issues=(
                    {
                        "layer": "goal_verification",
                        "code": "answer_unresolved_symbol_state",
                        "step_id": "invalid_call_a",
                        "scope_id": "problem",
                        "message": "first independent graph issue",
                    },
                    {
                        "layer": "goal_verification",
                        "code": "point_goal_source_mismatch",
                        "step_id": "invalid_call_b",
                        "scope_id": "problem",
                        "message": "second independent graph issue",
                    },
                ),
            ),
        ),
    )

    retry_state = PlannerRetryStateProjector.from_context(context)

    assert retry_state is not None
    assert {issue.step_id for issue in retry_state.issues} == {
        "invalid_call_a",
        "invalid_call_b",
    }
    assert retry_state.recovered_issues == ()
    assert retry_state.preserve_policy == "preserve_graph"
