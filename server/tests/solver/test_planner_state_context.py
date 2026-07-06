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
    PlannerStateContextBuilder,
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
from shuxueshuo_server.solver.runtime.strategy_replay import (  # noqa: E402
    PlannerRetryReplayResult,
    _planner_state_context_from_replay,
)


def test_planner_state_context_initial_snapshot_is_json_serializable() -> None:
    """Initial context should snapshot registry-visible planner state."""
    ctx = PlannerStateContextBuilder.initial_from_inputs(
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
    assert any(
        item["kind"] == "coefficient_relation"
        for item in payload["state"]["conditions"]
    )
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
    assert (tmp_path / "state-rewrite-ledger.json").exists()
    assert (tmp_path / "context-events.json").exists()
    assert json.loads((tmp_path / "planner-state-context.json").read_text())[
        "manifest"
    ]["context_type"] == "planner"
