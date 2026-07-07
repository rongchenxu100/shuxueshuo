from __future__ import annotations

from importlib import util
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

from shuxueshuo_server.solver.runtime.planner_retry_projection import (  # noqa: E402
    PlannerRetryStateProjector,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (  # noqa: E402
    PlannerRetryReplayService,
)


def test_strategy_payload_builder_indexes_stable_and_semantic_attempt_state() -> None:
    """semantic 早失败不应冲掉上一轮 runtime 稳定前缀。"""
    stable_attempt = {
        "attempt": 1,
        "effective_draft": {
            "scopes": [
                {
                    "scope_id": "i",
                    "label": "第（Ⅰ）问",
                    "steps": [{"step_id": "derive_axis_point"}],
                }
            ]
        },
        "diagnostic": {
            "ok": False,
            "accepted_prefix": [
                {"step_id": "derive_axis_point", "scope_id": "i"}
            ],
            "blockers": [{"step_id": "derive_N_coordinate", "scope_id": "ii_1"}],
        },
        "repair_summary": {
            "frozen_prefix": [{"step_id": "derive_axis_point", "scope_id": "i"}],
            "next_actions": ["从 derive_N_coordinate 继续。"],
        },
        "repair_instruction": "保留 accepted prefix。",
        "errors": ["recipe_trial_step_failed:derive_N_coordinate"],
    }
    semantic_attempt = {
        "attempt": 2,
        "errors": ["semantic_read_errors: count=1"],
        "validation_report": {
            "ok": False,
            "errors": ["semantic_read_unknown:missing_read"],
            "semantic_read_resolution": {
                "ok": False,
                "changed": True,
                "errors": [
                    {
                        "step_id": "bad_read",
                        "scope_id": "ii_1",
                        "code": "semantic_read_unknown",
                        "message": "unknown semantic read",
                    }
                ],
                "resolutions": [
                    {
                        "step_id": "derive_axis_point",
                        "scope_id": "i",
                        "semantic_ref": "A",
                        "canonical_handle": "point:problem:A",
                    }
                ],
                "partially_resolved_payload": {
                    "scopes": [
                        {
                            "scope_id": "i",
                            "steps": [
                                {
                                    "step_id": "derive_axis_point",
                                    "reads": ["point:problem:A"],
                                }
                            ],
                        }
                    ]
                },
            },
        },
        "raw_preview": '{"scopes": []}',
    }
    inputs = replace(
        _nankai_inputs(),
        previous_errors=[stable_attempt, semantic_attempt],
    )

    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_nankai_llm_problem(),
    )
    state = payload["previous_attempt_state"]

    assert payload["previous_attempts"][0]["attempt"] == 1
    assert payload["previous_attempts"][0]["diagnostic_summary"]["accepted_prefix"] == [
        {"step_id": "derive_axis_point", "scope_id": "i"}
    ]
    assert payload["previous_attempts"][1]["attempt"] == 2
    assert "validation_report" not in payload["previous_attempts"][1]
    assert state["attempt_count"] == 2
    assert state["latest_stable_runtime"]["attempt"] == 1
    assert (
        state["latest_stable_runtime"]["diagnostic"]["accepted_prefix"][0]["step_id"]
        == "derive_axis_point"
    )
    assert state["latest_semantic_failure"]["attempt"] == 2
    assert state["latest_semantic_failure"]["validation_errors"] == [
        "semantic_read_unknown:missing_read"
    ]
    assert (
        state["latest_semantic_failure"]["semantic_read_resolution"][
            "partially_resolved_payload"
        ]["scopes"][0]["steps"][0]["reads"]
        == ["point:problem:A"]
    )


def test_strategy_payload_builder_indexes_planner_retry_state() -> None:
    """正式 retry state 应进入 prompt，并派生旧 latest_stable_runtime 镜像。"""
    retry_state = {
        "attempt": 3,
        "baseline_draft": {
            "scopes": [
                {
                    "scope_id": "ii_1",
                    "label": "第（Ⅱ）①问",
                    "steps": [{"step_id": "derive_N_coordinate"}],
                }
            ]
        },
        "stable_prefix": [
            {"step_id": "derive_axis_point", "scope_id": "i", "capability_id": "axis"}
        ],
        "repair_suffix_start": {"step_id": "derive_N_coordinate", "scope_id": "ii_1"},
        "issues": [
            {
                "layer": "trial_execution",
                "code": "recipe_trial_step_failed",
                "step_id": "derive_N_coordinate",
                "scope_id": "ii_1",
                "repair_target": "step",
                "preserve_policy": "preserve_prefix",
                "message": "runtime blocker",
                "hints": [],
                "related_handles": [],
            }
        ],
        "preserve_policy": "preserve_prefix",
        "repair_instruction": "以 baseline_draft 为基线。",
        "replay_reports": {
            "trial_execution": {
                "ok": False,
                "accepted_prefix": [
                    {"step_id": "derive_axis_point", "scope_id": "i"}
                ],
                "blockers": [
                    {"step_id": "derive_N_coordinate", "scope_id": "ii_1"}
                ],
            }
        },
    }
    inputs = replace(
        _nankai_inputs(),
        previous_errors=[{"attempt": 3, "planner_retry_state": retry_state}],
    )

    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_nankai_llm_problem(),
    )
    state = payload["previous_attempt_state"]

    assert state["latest_retry_state"]["baseline_draft"] == retry_state["baseline_draft"]
    assert state["latest_retry_state"]["stable_prefix"] == retry_state["stable_prefix"]
    assert "replay_reports" not in state["latest_retry_state"]
    assert state["latest_stable_runtime"]["attempt"] == 3
    assert "replay_reports" not in state["latest_stable_runtime"]["planner_retry_state"]
    assert state["latest_stable_runtime"]["effective_draft"] == retry_state["baseline_draft"]
    assert state["latest_stable_runtime"]["diagnostic"]["ok"] is False
    assert state["latest_stable_runtime"]["diagnostic"]["accepted_prefix"] == [
        {"step_id": "derive_axis_point", "scope_id": "i"}
    ]
    assert state["latest_stable_runtime"]["diagnostic"]["blockers"] == [
        {"step_id": "derive_N_coordinate", "scope_id": "ii_1"}
    ]


def test_strategy_payload_builder_compresses_previous_attempts_for_prompt() -> None:
    """LLM prompt history should not include full replay/context debug payloads."""
    retry_state = {
        "attempt": 1,
        "baseline_draft": {
            "scopes": [
                {
                    "scope_id": "ii_1",
                    "steps": [
                        {"step_id": "stable_step"},
                        {"step_id": "blocked_step"},
                    ],
                }
            ]
        },
        "stable_prefix": [{"step_id": "stable_step", "scope_id": "ii_1"}],
        "repair_suffix_start": {"step_id": "blocked_step", "scope_id": "ii_1"},
        "issues": [
            {
                "layer": "trial_execution",
                "code": "recipe_trial_step_failed",
                "step_id": "blocked_step",
                "scope_id": "ii_1",
                "repair_target": "step",
                "preserve_policy": "preserve_prefix",
                "message": "missing runtime state",
                "hints": [],
                "related_handles": ["Parabola"],
            }
        ],
        "preserve_policy": "preserve_prefix",
        "repair_instruction": "repair suffix only",
        "replay_reports": {
            "candidate_resolution": {"large": ["debug"] * 100},
            "trial_execution": {
                "ok": False,
                "blockers": [{"step_id": "blocked_step", "scope_id": "ii_1"}],
            },
        },
        "source_context_id": "ctx_planner_attempt_1",
    }
    previous_attempt = {
        "attempt": 1,
        "context_derived_retry_state": retry_state,
        "context_retry_memory": {"large": ["memory"] * 100},
        "diagnostic": {"large": ["diagnostic"] * 100},
        "effective_draft": {"large": ["draft"] * 100},
        "planner_state_context_ref": {
            "context_id": "ctx_planner_attempt_1",
            "parent_context_id": None,
            "schema_version": "planner-state-context/v1",
        },
        "errors": ["recipe_trial_step_failed:blocked_step"],
    }
    inputs = replace(_nankai_inputs(), previous_errors=[previous_attempt])

    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_nankai_llm_problem(),
    )

    prompt_attempt = payload["previous_attempts"][0]
    assert "context_derived_retry_state" not in prompt_attempt
    assert "context_retry_memory" not in prompt_attempt
    assert "diagnostic" not in prompt_attempt
    assert "effective_draft" not in prompt_attempt
    assert prompt_attempt["stable_prefix_step_ids"] == ["stable_step"]
    assert prompt_attempt["primary_issue"]["step_id"] == "blocked_step"
    latest_retry_state = payload["previous_attempt_state"]["latest_retry_state"]
    assert latest_retry_state["baseline_draft"] == retry_state["baseline_draft"]
    assert "replay_reports" not in latest_retry_state


def test_planner_retry_state_promotes_capability_alignment_error() -> None:
    """Method/recipe contract errors should become explicit retry tickets."""
    validation_report = StepIntentValidationReport(
        ok=True,
        step_count=1,
        recipe_alignment=RecipeAlignmentReport(
            matched_methods=("parameter_from_segment_length",),
            capability_errors=(
                {
                    "step_id": "solve_parameter_from_length",
                    "goal_type": "derive_parameter",
                    "recipe_hint": "parameter_from_segment_length",
                    "code": "method_outputs_answer",
                    "message": "parameter method should not produce final answer directly",
                },
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=("strategy_candidate_resolution_failed: []",),
        validation_report=validation_report,
    )

    assert state is not None
    assert state.issues[0].layer == "candidate_resolution"
    assert state.issues[0].code == "method_contract_mismatch"
    assert state.issues[0].step_id == "solve_parameter_from_length"
    assert "重新选择更合适的 catalog method/recipe" in state.issues[0].hints[0]
    assert state.issues[0].details == {
        "original_code": "method_outputs_answer",
        "recipe_hint": "parameter_from_segment_length",
        "goal_type": "derive_parameter",
    }
    assert state.replay_depth == "candidate_resolution"
    assert state.replay_timeline[-1]["layer"] == "candidate_resolution"
    assert state.replay_timeline[-1]["status"] == "blocked"


def test_replay_keeps_builder_retry_state_when_context_projection_empty(
    monkeypatch,
) -> None:
    """Context projection returning None must not erase the legacy retry state."""
    monkeypatch.setattr(
        PlannerRetryStateProjector,
        "from_context",
        staticmethod(lambda _context: None),
    )
    validation_report = StepIntentValidationReport(
        ok=False,
        errors=("synthetic_validation_error",),
    )

    replay = PlannerRetryReplayService().replay_from_artifacts(
        attempt=1,
        errors=("synthetic_validation_error",),
        validation_report=validation_report,
        inputs=_nankai_inputs(),
        handle_registry=_registry(),
        problem_payload=_nankai_llm_problem(),
    )

    assert replay.planner_state_context is not None
    assert replay.retry_state is not None
    assert replay.retry_state.issues[0].code == "synthetic_validation_error"


def test_strategy_payload_builder_derives_semantic_failure_from_retry_state() -> None:
    """有正式 retry state 时，semantic failure 镜像不再回扫旧 raw attempt。"""
    older_semantic_attempt = {
        "attempt": 1,
        "validation_report": {
            "ok": False,
            "errors": ["semantic_read_unknown:old"],
            "semantic_read_resolution": {
                "ok": False,
                "errors": [{"code": "semantic_read_unknown", "message": "old"}],
            },
        },
    }
    retry_state = {
        "attempt": 2,
        "baseline_draft": {
            "scopes": [
                {
                    "scope_id": "ii_1",
                    "label": "第（Ⅱ）①问",
                    "steps": [{"step_id": "repair_semantic_read"}],
                }
            ]
        },
        "stable_prefix": [],
        "repair_suffix_start": {"step_id": "repair_semantic_read", "scope_id": "ii_1"},
        "issues": [
            {
                "layer": "semantic_reads",
                "code": "semantic_read_unknown",
                "step_id": "repair_semantic_read",
                "scope_id": "ii_1",
                "repair_target": "semantic_reads",
                "preserve_policy": "none",
                "message": "new semantic failure",
                "hints": [],
                "related_handles": [],
            }
        ],
        "preserve_policy": "none",
        "repair_instruction": "只修 semantic_reads。",
        "replay_reports": {
            "validation": {
                "ok": False,
                "errors": ["semantic_read_unknown:new"],
                "semantic_read_resolution": {
                    "ok": False,
                    "changed": True,
                    "errors": [
                        {
                            "step_id": "repair_semantic_read",
                            "scope_id": "ii_1",
                            "code": "semantic_read_unknown",
                            "message": "new semantic failure",
                        }
                    ],
                    "partially_resolved_payload": {
                        "scopes": [
                            {
                                "scope_id": "ii_1",
                                "steps": [
                                    {
                                        "step_id": "repair_semantic_read",
                                        "reads": ["point:problem:A"],
                                    }
                                ],
                            }
                        ]
                    },
                },
            }
        },
    }
    inputs = replace(
        _nankai_inputs(),
        previous_errors=[
            older_semantic_attempt,
            {"attempt": 2, "planner_retry_state": retry_state},
        ],
    )

    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_nankai_llm_problem(),
    )
    state = payload["previous_attempt_state"]

    assert state["latest_retry_state"]["baseline_draft"] == retry_state["baseline_draft"]
    assert state["latest_retry_state"]["issues"] == retry_state["issues"]
    assert "replay_reports" not in state["latest_retry_state"]
    assert state["latest_semantic_failure"]["attempt"] == 2
    assert state["latest_semantic_failure"]["errors"] == ["new semantic failure"]
    assert state["latest_semantic_failure"]["validation_errors"] == [
        "semantic_read_unknown:new"
    ]
    assert (
        state["latest_semantic_failure"]["semantic_read_resolution"]["errors"][0][
            "message"
        ]
        == "new semantic failure"
    )


def test_planner_retry_state_builds_semantic_read_issue() -> None:
    """semantic_reads 失败应生成正式 issue envelope 和局部 baseline。"""
    partial = {"scopes": [{"scope_id": "ii_1", "steps": [{"step_id": "bad_read"}]}]}
    state = build_planner_retry_state(
        attempt=2,
        errors=("semantic_read_errors: count=1",),
        validation_report=StepIntentValidationReport(
            ok=False,
            errors=("semantic_read_unknown:A",),
            semantic_read_resolution=SemanticReadResolutionReport(
                errors=(
                    SemanticReadResolutionError(
                        step_id="bad_read",
                        scope_id="ii_1",
                        code="semantic_read_unknown",
                        message="unknown semantic read A",
                    ),
                ),
                partially_resolved_payload=partial,
            ),
        ),
    )

    assert state is not None
    assert state.baseline_draft == partial
    assert state.stable_prefix == ()
    assert state.preserve_policy == "none"
    assert state.issues[0].layer == "semantic_reads"
    assert state.issues[0].code == "semantic_read_unknown"
    assert state.repair_suffix_start == {"step_id": "bad_read", "scope_id": "ii_1"}


def test_planner_retry_replay_service_builds_semantic_read_issue() -> None:
    """replay service 应从 raw JSON 直接生成 semantic_reads issue。"""
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
                        "semantic_reads": [
                            {"ref": "missing_fact", "kind": "fact"}
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i:temp_point",
                                "i",
                                "临时点",
                                output_type="Point",
                            )
                        ],
                        "reason": "测试 replay service。",
                    }
                ],
            }
        ]
    }
    replay = PlannerRetryReplayService().replay_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=replace(_nankai_inputs(), question_goals=()),
        handle_registry=_registry(),
        context=_runtime_context(),
        attempt=1,
    )

    assert replay.raw_draft is None
    assert replay.validation_report is not None
    assert replay.retry_state is not None
    assert replay.retry_state.issues[0].layer == "semantic_reads"
    assert replay.retry_state.baseline_draft is not None


def test_planner_retry_state_builds_validation_issue() -> None:
    """普通 validator 错误应归一化成 validation issue。"""
    state = build_planner_retry_state(
        attempt=1,
        errors=("missing required answer handles: answer:ii_1.minimum_value",),
        validation_report=StepIntentValidationReport(
            ok=False,
            errors=("missing required answer handles: answer:ii_1.minimum_value",),
        ),
    )

    assert state is not None
    assert state.issues[0].layer == "validation"
    assert state.issues[0].code == "missing"
    assert state.replay_reports["validation"]["ok"] is False


def test_planner_retry_state_builds_candidate_resolution_issue() -> None:
    """candidate resolver 失败应保留 normalize 后 baseline，并定位 step。"""
    draft = _single_scope_draft(
        _step(
            scope_id="ii_1",
            step_id="free_expression",
            recipe_hint=None,
            goal_type="derive_utility_expression",
            target="fact:ii_1:free_expression",
            produces=(
                ProducedFact(
                    "fact:ii_1:free_expression",
                    "ii_1",
                    "自由中间表达式",
                    output_type="Expression",
                ),
            ),
        ),
        scope_id="ii_1",
    )
    report = ExecutablePlanResolutionReport(
        ok=False,
        step_reports=(
            StepIntentResolutionStepReport(
                step_id="free_expression",
                scope_id="ii_1",
                recipe_hint=None,
                produced_types=("Expression",),
                selected_capability_id=None,
                candidates=(),
                errors=("no_executable_candidate: free Expression",),
                warnings=("choose a method/recipe catalog item",),
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=("executable_resolution_errors: no_executable_candidate",),
        normalized_draft=draft,
        resolution_report=report,
    )

    assert state is not None
    assert state.baseline_draft == draft.to_payload()
    assert state.issues[0].layer == "candidate_resolution"
    assert state.issues[0].step_id == "free_expression"
    assert state.issues[0].hints == ("choose a method/recipe catalog item",)


def test_planner_retry_state_builds_compressed_step_work_order() -> None:
    """一步裸算多个数学动作时，应反馈缺失状态工单而不是推荐固定 method 链。"""
    draft = _single_scope_draft(
        _step(
            scope_id="i_2",
            step_id="derive_E_from_angle",
            recipe_hint=None,
            goal_type="derive_curve_intersection_point",
            target="answer:i_2_E",
            reads=(
                "function:problem:parabola",
                "fact:i_2:angle_sum_CBE_ACO_45",
                "fact:problem:A_coordinate_value",
                "fact:i:B_coordinate",
            ),
            produces=(
                ProducedFact(
                    "answer:i_2_E",
                    "i_2",
                    "E 点坐标答案",
                    output_type="Point",
                ),
            ),
        ),
        scope_id="i_2",
    )
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "i", "i_2")),
        entity_handles=frozenset(("function:problem:parabola",)),
        fact_handles=frozenset((
            "fact:i_2:angle_sum_CBE_ACO_45",
            "fact:problem:A_coordinate_value",
            "fact:i:B_coordinate",
        )),
        answer_handles=frozenset(("answer:i_2_E",)),
        scope_parents={"problem": None, "i": "problem", "i_2": "i"},
        fact_types={
            "fact:i_2:angle_sum_CBE_ACO_45": "angle_sum",
            "fact:problem:A_coordinate_value": "point_coordinate",
            "fact:i:B_coordinate": "point_coordinate",
        },
        answer_value_types={"answer:i_2_E": "Point"},
        handle_valid_scopes={
            "function:problem:parabola": "problem",
            "fact:i_2:angle_sum_CBE_ACO_45": "i_2",
            "fact:problem:A_coordinate_value": "problem",
            "fact:i:B_coordinate": "i",
            "answer:i_2_E": "i_2",
        },
    )
    report = ExecutablePlanResolutionReport(
        ok=False,
        step_reports=(
            StepIntentResolutionStepReport(
                step_id="derive_E_from_angle",
                scope_id="i_2",
                recipe_hint=None,
                produced_types=("Point",),
                selected_capability_id=None,
                candidates=(),
                errors=(
                    "no_executable_candidate:produced_types=['Point'], "
                    "candidate_errors=line_parabola_second_intersection_point:"
                    "missing_line_parabola_inputs: missing solved Parabola read|"
                    "missing_line_parabola_inputs: "
                    "missing_curve_intersection_target_pointref",
                ),
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=3,
        errors=("executable_resolution_errors: no_executable_candidate",),
        normalized_draft=draft,
        resolution_report=report,
        handle_registry=registry,
    )

    assert state is not None
    issue = state.issues[0]
    assert issue.code == "compressed_step_missing_prerequisites"
    assert issue.repair_target == "expand_step"
    assert issue.details is not None
    assert issue.details["method_guidance"] == {
        "policy": "only_when_unique_contract_match",
        "items": [],
    }
    missing_states = {
        item["state"]
        for item in issue.details["missing_prerequisites"]
    }
    assert {
        "solved_parabola",
        "target_point_ref",
        "line_defining_state",
        "angle_relation_state",
    } <= missing_states
    available_states = {
        item["state"]
        for item in issue.details["available_states"]
    }
    assert {"angle_sum", "point_coordinate", "function_entity"} <= available_states
    assert state.issues[1].code == "no_executable_candidate"

    retry_attempt = {"attempt": 3, "planner_retry_state": state.to_payload()}
    payload = StrategyPayloadBuilder().build(
        replace(_nankai_inputs(), previous_errors=[retry_attempt]),
        problem_payload=_nankai_llm_problem(),
    )
    prompt = StrategyPromptRenderer().render(payload)

    latest_retry_state = payload["previous_attempt_state"]["latest_retry_state"]
    assert latest_retry_state["issues"][0]["code"] == "compressed_step_missing_prerequisites"
    assert latest_retry_state["repair_suffix_start"] == {
        "scope_id": "i_2",
        "step_id": "derive_E_from_angle",
    }
    assert "compressed_step_missing_prerequisites" in prompt.system + prompt.user
    assert "suffix 拆成多个可执行 StepIntent" in prompt.user


def test_planner_retry_state_does_not_compress_generic_missing_text() -> None:
    """普通 missing 文案不应被误判为 over-compressed executable step。"""
    draft = _single_scope_draft(
        _step(
            scope_id="i_2",
            step_id="derive_E_from_angle",
            recipe_hint=None,
            goal_type="derive_curve_intersection_point",
            target="answer:i_2_E",
            reads=("function:problem:parabola",),
            produces=(
                ProducedFact(
                    "answer:i_2_E",
                    "i_2",
                    "E 点坐标答案",
                    output_type="Point",
                ),
            ),
        ),
        scope_id="i_2",
    )
    report = ExecutablePlanResolutionReport(
        ok=False,
        step_reports=(
            StepIntentResolutionStepReport(
                step_id="derive_E_from_angle",
                scope_id="i_2",
                recipe_hint=None,
                produced_types=("Point",),
                selected_capability_id=None,
                candidates=(),
                errors=(
                    "validation_missing: missing parabola context; missing line context",
                ),
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=3,
        errors=("executable_resolution_errors: validation_missing",),
        normalized_draft=draft,
        resolution_report=report,
        handle_registry=None,
    )

    assert state is not None
    assert all(
        issue.code != "compressed_step_missing_prerequisites"
        for issue in state.issues
    )


def test_planner_retry_state_prioritizes_family_route_deviation() -> None:
    """已有 preferred family route 时，null-hint utility 绕路应抢在局部 candidate 错误前反馈。"""
    validation_report = StepIntentValidationReport(
        ok=True,
        recipe_alignment=RecipeAlignmentReport(
            preferred_recipe_ids=(
                "two_moving_points_path_reduction",
                "broken_path_straightening_and_select",
                "path_minimum_by_straightened_distance",
            ),
            missing_preferred_recipe_ids=(
                "two_moving_points_path_reduction",
                "broken_path_straightening_and_select",
                "path_minimum_by_straightened_distance",
            ),
            null_hint_steps=(
                "parameterize_path_points",
                "compute_free_path_expression",
            ),
        ),
    )
    resolution_report = ExecutablePlanResolutionReport(
        ok=False,
        step_reports=(
            StepIntentResolutionStepReport(
                step_id="parameterize_path_points",
                scope_id="ii",
                recipe_hint=None,
                produced_types=("Point",),
                selected_capability_id="right_angle_equal_length_construct_and_select",
                candidates=(),
            ),
            StepIntentResolutionStepReport(
                step_id="compute_free_path_expression",
                scope_id="ii",
                recipe_hint=None,
                produced_types=("Expression", "MinimumExpression"),
                selected_capability_id=None,
                candidates=(),
                errors=("no_executable_candidate:free utility expression",),
            ),
        ),
        errors=("compute_free_path_expression:no_executable_candidate",),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=("executable_resolution_errors: no_executable_candidate",),
        validation_report=validation_report,
        resolution_report=resolution_report,
    )

    assert state is not None
    assert state.issues[0].code == "strategy_route_deviation"
    assert state.issues[0].step_id == "parameterize_path_points"
    assert state.issues[0].scope_id == "ii"
    assert state.repair_suffix_start == {
        "step_id": "parameterize_path_points",
        "scope_id": "ii",
    }
    assert any(
        "missing_preferred_recipes=two_moving_points_path_reduction" in hint
        for hint in state.issues[0].hints
    )


def test_planner_retry_state_does_not_retry_successful_route_warning() -> None:
    """route warning 只有在本轮失败时才升级为 retry issue。"""
    validation_report = StepIntentValidationReport(
        ok=True,
        recipe_alignment=RecipeAlignmentReport(
            preferred_recipe_ids=("path_minimum_by_straightened_distance",),
            missing_preferred_recipe_ids=("path_minimum_by_straightened_distance",),
            null_hint_steps=("derive_open_world_minimum",),
            avoid_pattern_hits=(
                {
                    "step_id": "derive_open_world_minimum",
                    "goal_type": "derive_minimum_value",
                    "pattern": "parameterization_or_derivative_route",
                },
            ),
        ),
    )
    resolution_report = ExecutablePlanResolutionReport(
        ok=True,
        step_reports=(
            StepIntentResolutionStepReport(
                step_id="derive_open_world_minimum",
                scope_id="ii",
                recipe_hint=None,
                produced_types=("MinimumExpression",),
                selected_capability_id="distance_between_points",
                candidates=(),
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=(),
        validation_report=validation_report,
        resolution_report=resolution_report,
        diagnostic=StepIntentExecutionDiagnostic(ok=True),
    )

    assert state is None


def test_planner_retry_state_keeps_open_world_candidate_issue_without_family_route() -> None:
    """没有 preferred route 覆盖时，未知 utility 仍走普通可执行性反馈。"""
    validation_report = StepIntentValidationReport(
        ok=True,
        recipe_alignment=RecipeAlignmentReport(
            null_hint_steps=("compute_free_expression",),
        ),
    )
    resolution_report = ExecutablePlanResolutionReport(
        ok=False,
        step_reports=(
            StepIntentResolutionStepReport(
                step_id="compute_free_expression",
                scope_id="ii",
                recipe_hint=None,
                produced_types=("Expression",),
                selected_capability_id=None,
                candidates=(),
                errors=("no_executable_candidate:free utility expression",),
                warnings=("split this into executable primitive steps",),
            ),
        ),
        errors=("compute_free_expression:no_executable_candidate",),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=("executable_resolution_errors: no_executable_candidate",),
        validation_report=validation_report,
        resolution_report=resolution_report,
    )

    assert state is not None
    assert state.issues[0].code == "no_executable_candidate"
    assert state.issues[0].step_id == "compute_free_expression"
    assert state.issues[0].hints == ("split this into executable primitive steps",)


def test_planner_retry_replay_service_uses_normalized_baseline() -> None:
    """replay state 的 baseline_draft 应来自 normalizer 后 draft。"""
    draft = _single_scope_draft(
        _step(
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
                    output_type="Equation",
                ),
            ),
        ),
        scope_id="i",
    )

    replay = PlannerRetryReplayService().replay_draft(
        draft,
        inputs=replace(_nankai_inputs(), question_goals=()),
        handle_registry=_registry(),
        context=_runtime_context(),
        attempt=1,
        errors=("executable_resolution_errors: expected for test",),
    )

    assert replay.normalized_draft is not None
    assert replay.retry_state is not None
    assert replay.retry_state.baseline_draft == replay.normalized_draft.to_payload()
    assert (
        replay.normalized_draft.scopes[0].steps[0].produces[0].output_type
        == "Parabola"
    )


def test_planner_retry_state_builds_trial_issue_with_stable_prefix() -> None:
    """runtime blocker 应冻结已通过 prefix，并从首个 blocker 修 suffix。"""
    draft = _single_scope_draft(
        _step(
            scope_id="ii_1",
            step_id="derive_N_coordinate",
            recipe_hint="line_intersection_point",
            goal_type="derive_point",
            target="fact:ii_1:N_coordinate",
        ),
        scope_id="ii_1",
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="derive_axis_point",
                scope_id="i",
                capability_id="quadratic_axis_point",
            ),
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="derive_N_coordinate",
                scope_id="ii_1",
                stage="recipe_trial",
                code="recipe_trial_step_failed",
                message="line intersection missing input",
                capability_errors=("line_intersection_point: missing Line",),
                missing_runtime_type="Line",
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=2,
        errors=("recipe_trial_step_failed:derive_N_coordinate",),
        effective_draft=draft,
        diagnostic=diagnostic,
    )

    assert state is not None
    assert state.preserve_policy == "preserve_prefix"
    assert state.stable_prefix[0]["step_id"] == "derive_axis_point"
    assert state.repair_suffix_start == {"step_id": "derive_N_coordinate", "scope_id": "ii_1"}
    assert state.issues[0].layer == "trial_execution"
    assert state.issues[0].preserve_policy == "preserve_prefix"
    assert state.issues[0].related_handles == ("Line",)


def test_planner_retry_state_keeps_recovered_semantic_fallback_out_of_blocking_issues() -> None:
    """已由 canonical reads 接管的 semantic 问题不应抢占 runtime blocker。"""
    validation_report = StepIntentValidationReport(
        ok=True,
        semantic_read_resolution=SemanticReadResolutionReport(
            fallbacks=(
                SemanticReadFallback(
                    step_id="derive_F_coordinate_ii",
                    scope_id="ii_1",
                    reason="semantic_reads_failed_legacy_reads_valid",
                    reads=("point:problem:D", "fact:ii:F_midpoint_of_DN"),
                    semantic_errors=(
                        SemanticReadResolutionError(
                            step_id="derive_F_coordinate_ii",
                            scope_id="ii_1",
                            code="semantic_read_unknown",
                            message="semantic_read_unknown: axis_point",
                        ),
                    ),
                ),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="derive_N_coordinate_ii",
                scope_id="ii_1",
                capability_id="right_angle_equal_length_construct_and_select",
            ),
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="derive_parabola_ii",
                scope_id="ii_1",
                stage="recipe_trial",
                code="recipe_trial_step_failed",
                message="quadratic_from_constraints: 约束不足以确定系数: b, c",
                capability_errors=(
                    "quadratic_from_constraints: 约束不足以确定系数: b, c",
                ),
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=2,
        errors=("recipe_trial_step_failed:derive_parabola_ii",),
        validation_report=validation_report,
        diagnostic=diagnostic,
    )

    assert state is not None
    payload = state.to_payload()
    assert payload["issues"][0]["layer"] == "trial_execution"
    assert payload["issues"][0]["step_id"] == "derive_parabola_ii"
    assert payload["recovered_issues"][0]["layer"] == "semantic_reads"
    assert payload["recovered_issues"][0]["step_id"] == "derive_F_coordinate_ii"
    assert payload["replay_depth"] == "trial_execution"
    assert payload["selected_repair_layer"] == "trial_execution"
    assert payload["repair_suffix_start"] == {
        "step_id": "derive_parabola_ii",
        "scope_id": "ii_1",
    }
    timeline_by_layer = {
        item["layer"]: item["status"]
        for item in payload["replay_timeline"]
    }
    assert timeline_by_layer["semantic_reads"] == "recovered"
    assert timeline_by_layer["trial_execution"] == "blocked"


def test_planner_retry_state_builds_sanitized_answer_check_issue() -> None:
    """answer mismatch issue 不应把 expected answer 泄漏给 prompt。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="derive_answer",
                scope_id="ii_1",
                capability_id="path_minimum_by_straightened_distance",
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=("answer_mismatch: ii_1.minimum_value; actual=13/2; expected=5/2",),
        diagnostic=diagnostic,
    )

    assert state is not None
    payload = state.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["preserve_policy"] == "none"
    assert payload["stable_prefix"] == []
    assert payload["issues"][0]["layer"] == "answer_check"
    assert "actual=13/2" in payload["issues"][0]["message"]
    assert "expected" not in serialized.lower()


def test_planner_retry_state_builds_unresolved_answer_check_with_path_hints() -> None:
    """answer unresolved 应进入 answer_check，并复用路径最值 insight 给出下一步。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="compute_path_minimum_expression",
                scope_id="ii",
                capability_id="broken_path_straightening_minimum_expression",
            ),
        ),
        planner_insights=(
            StepIntentPlannerInsight(
                step_id="reduce_square_path",
                scope_id="ii",
                produced_handle="fact:ii:reduced_path",
                output_type="PathTransformation",
                facts={
                    "moving_point": "point:ii:G",
                    "fixed_points": ["point:ii:A", "point:problem:M"],
                    "transformed_path": "AG+MG",
                },
                repair_note="moving point is point:ii:G",
            ),
            StepIntentPlannerInsight(
                step_id="compute_path_minimum_expression",
                scope_id="ii",
                produced_handle="fact:ii:path_minimum_expression",
                output_type="StraighteningMinimum",
                facts={
                    "minimum_points": [
                        "fact:ii:path_minimum_point_1",
                        "fact:ii:path_minimum_point_2",
                    ],
                    "next_method": "line_locus_minimum_point",
                },
                repair_note="use line_locus_minimum_point",
            ),
        ),
    )

    state = build_planner_retry_state(
        attempt=1,
        errors=(
            "answer_unresolved: goal=answer:ii.E; answer_key=E; "
            "value_type=Point; unresolved_symbols=_axis_param_E",
        ),
        diagnostic=diagnostic,
    )

    assert state is not None
    payload = state.to_payload()
    issue = payload["issues"][0]
    hint_text = " ".join(issue["hints"])
    assert payload["preserve_policy"] == "none"
    assert payload["stable_prefix"] == []
    assert issue["layer"] == "answer_check"
    assert issue["code"] == "answer_unresolved"
    assert issue["related_handles"] == ["answer:ii.E"]
    assert "line_locus_minimum_point" in hint_text
    assert "path_minimum_point_1" in hint_text
    assert "expected" not in json.dumps(payload, ensure_ascii=False).lower()


def test_merge_previous_accepted_prefix_prefers_planner_retry_state() -> None:
    """prefix 合并应优先使用 PlannerRetryState，而不是旧 diagnostic 镜像。"""
    inputs = replace(_nankai_inputs(), question_goals=())
    registry = _registry()
    current = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:current_axis_point",
            produces=(
                ProducedFact("fact:i:current_axis_point", "i", "当前输出", output_type="Point"),
            ),
        ),
        _step(
            scope_id="i",
            step_id="derive_suffix",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:suffix",
            produces=(ProducedFact("fact:i:suffix", "i", "后缀输出", output_type="Point"),),
        ),
        scope_id="i",
    )
    retry_baseline = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:retry_axis_point",
            produces=(
                ProducedFact("fact:i:retry_axis_point", "i", "retry state 前缀", output_type="Point"),
            ),
        ),
        scope_id="i",
    ).to_payload()
    retry_baseline["scopes"][0]["steps"][0]["reason"] = "测试 reason"
    legacy_effective = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="legacy_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:legacy_axis_point",
            produces=(
                ProducedFact("fact:i:legacy_axis_point", "i", "旧字段前缀", output_type="Point"),
            ),
        ),
        scope_id="i",
    ).to_payload()
    legacy_effective["scopes"][0]["steps"][0]["reason"] = "测试 reason"
    previous_attempt = {
        "attempt": 1,
        "planner_retry_state": {
            "attempt": 1,
            "baseline_draft": retry_baseline,
            "stable_prefix": [
                {"step_id": "derive_axis_point", "scope_id": "i", "capability_id": "axis"}
            ],
            "repair_suffix_start": {"step_id": "derive_suffix", "scope_id": "i"},
            "issues": [],
            "preserve_policy": "preserve_prefix",
            "repair_instruction": "preserve retry prefix",
            "replay_reports": {},
        },
        "effective_draft": legacy_effective,
        "diagnostic": {
            "accepted_prefix": [{"step_id": "legacy_axis_point", "scope_id": "i"}]
        },
    }

    merged = _merge_previous_accepted_prefix(
        current,
        previous_attempts=[previous_attempt],
        handle_registry=registry,
        inputs=inputs,
    )

    assert merged.scopes[0].steps[0].target == "fact:i:retry_axis_point"
    assert [step.step_id for step in merged.scopes[0].steps] == [
        "derive_axis_point",
        "derive_suffix",
    ]


def test_merge_previous_accepted_prefix_prefers_context_derived_retry_state() -> None:
    """Context-derived retry projection should outrank the compatibility mirror."""
    current_payload = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:current_axis_point",
            produces=(
                ProducedFact("fact:i:current_axis_point", "i", "当前输出", output_type="Point"),
            ),
        ),
        _step(
            scope_id="i",
            step_id="derive_suffix",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:suffix",
            produces=(ProducedFact("fact:i:suffix", "i", "后缀输出", output_type="Point"),),
        ),
        scope_id="i",
    ).to_payload()
    legacy_baseline = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:legacy_axis_point",
            produces=(
                ProducedFact("fact:i:legacy_axis_point", "i", "旧 retry state", output_type="Point"),
            ),
        ),
        scope_id="i",
    ).to_payload()
    context_baseline = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:context_axis_point",
            produces=(
                ProducedFact("fact:i:context_axis_point", "i", "context retry state", output_type="Point"),
            ),
        ),
        scope_id="i",
    ).to_payload()
    previous_attempt = {
        "attempt": 2,
        "planner_retry_state": {
            "attempt": 2,
            "baseline_draft": legacy_baseline,
            "stable_prefix": [{"step_id": "derive_axis_point", "scope_id": "i"}],
            "preserve_policy": "preserve_prefix",
            "issues": [],
            "replay_reports": {},
        },
        "context_derived_retry_state": {
            "attempt": 2,
            "baseline_draft": context_baseline,
            "stable_prefix": [{"step_id": "derive_axis_point", "scope_id": "i"}],
            "preserve_policy": "preserve_prefix",
            "issues": [],
            "replay_reports": {},
            "source_context_id": "ctx_planner_current",
        },
    }

    prepared = prepare_step_intent_raw_response(
        json.dumps(current_payload, ensure_ascii=False),
        previous_attempts=[previous_attempt],
    )
    merged = json.loads(prepared)

    assert merged["scopes"][0]["steps"][0]["target"] == "fact:i:context_axis_point"


def test_merge_previous_retry_state_preserve_handles_keeps_current_text() -> None:
    """preserve_handles 只冻结 dataflow/target/capability，不覆盖 strategy/reason。"""
    inputs = replace(_nankai_inputs(), question_goals=())
    registry = _registry()
    current = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint="current_hint",
            goal_type="derive_point",
            target="fact:i:current_axis_point",
            strategy="当前模型新的解释文字",
            reads=("fact:i:a_value",),
            produces=(
                ProducedFact("fact:i:current_axis_point", "i", "当前输出", output_type="Point"),
            ),
        ),
        scope_id="i",
    )
    baseline = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="derive_axis_point",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:retry_axis_point",
            strategy="旧解释文字",
            reads=("fact:i:c_value",),
            produces=(
                ProducedFact("fact:i:retry_axis_point", "i", "稳定输出", output_type="Point"),
            ),
        ),
        scope_id="i",
    ).to_payload()
    baseline["scopes"][0]["steps"][0]["reason"] = "稳定 reason"
    previous_attempt = {
        "planner_retry_state": {
            "attempt": 1,
            "baseline_draft": baseline,
            "stable_prefix": [
                {"step_id": "derive_axis_point", "scope_id": "i", "capability_id": "axis"}
            ],
            "repair_suffix_start": None,
            "issues": [],
            "preserve_policy": "preserve_handles",
            "repair_instruction": "preserve handles",
            "replay_reports": {},
        }
    }

    merged = _merge_previous_accepted_prefix(
        current,
        previous_attempts=[previous_attempt],
        handle_registry=registry,
        inputs=inputs,
    )
    step = merged.scopes[0].steps[0]

    assert step.strategy == "当前模型新的解释文字"
    assert step.target == "fact:i:retry_axis_point"
    assert step.reads == ("fact:i:c_value",)
    assert step.produces[0].handle == "fact:i:retry_axis_point"
    assert step.recipe_hint is None


def test_merge_previous_retry_state_preserve_step_locks_nearest_stable_step() -> None:
    """preserve_step 只冻结 stable_prefix 中最靠近 suffix 的一步。"""
    inputs = replace(_nankai_inputs(), question_goals=())
    registry = _registry()
    current = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="first_stable",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:first_current",
            produces=(ProducedFact("fact:i:first_current", "i", "当前第一步", output_type="Point"),),
        ),
        _step(
            scope_id="i",
            step_id="second_stable",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:second_current",
            produces=(ProducedFact("fact:i:second_current", "i", "当前第二步", output_type="Point"),),
        ),
        scope_id="i",
    )
    baseline = _single_scope_draft(
        _step(
            scope_id="i",
            step_id="first_stable",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:first_baseline",
            produces=(ProducedFact("fact:i:first_baseline", "i", "稳定第一步", output_type="Point"),),
        ),
        _step(
            scope_id="i",
            step_id="second_stable",
            recipe_hint=None,
            goal_type="derive_point",
            target="fact:i:second_baseline",
            produces=(ProducedFact("fact:i:second_baseline", "i", "稳定第二步", output_type="Point"),),
        ),
        scope_id="i",
    ).to_payload()
    for step in baseline["scopes"][0]["steps"]:
        step["reason"] = "稳定 reason"
    previous_attempt = {
        "planner_retry_state": {
            "attempt": 1,
            "baseline_draft": baseline,
            "stable_prefix": [
                {"step_id": "first_stable", "scope_id": "i", "capability_id": "first"},
                {"step_id": "second_stable", "scope_id": "i", "capability_id": "second"},
            ],
            "repair_suffix_start": {"step_id": "suffix", "scope_id": "i"},
            "issues": [],
            "preserve_policy": "preserve_step",
            "repair_instruction": "preserve nearest step",
            "replay_reports": {},
        }
    }

    merged = _merge_previous_accepted_prefix(
        current,
        previous_attempts=[previous_attempt],
        handle_registry=registry,
        inputs=inputs,
    )

    assert [step.target for step in merged.scopes[0].steps] == [
        "fact:i:first_current",
        "fact:i:second_baseline",
    ]
