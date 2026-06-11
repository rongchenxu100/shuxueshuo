from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.runtime import strategy_payload as strategy_payload_module
from shuxueshuo_server.solver.family import (
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.family.models import (
    MethodCompanionOutputSpec,
    MethodBindingRuleSpec,
    MethodInputBindingSpec,
    MethodPrepInvocationSpec,
    RecipeExecutionSpec,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.problem_models import ProblemIR, QuestionGoal
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.entity_state_resolver import EntityStateResolver
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.orchestrator import _next_previous_errors
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    CanonicalRuntimeBindingIndex,
    CreatedEntity,
    MethodBindingRuleRegistry,
    ProducedFact,
    RecipeExecutionSpecRegistry,
    RecipeTrialExecutor,
    RepairFeedbackBuilder,
    RepairHintRegistry,
    RepairHintSpec,
    StepIntentCandidateResolver,
    STEP_INTENT_JSON_SCHEMA,
    StrategyPlanner,
    StepIntent,
    StepIntentAcceptedStep,
    StepIntentAppliedFill,
    StepIntentDraft,
    StepIntentExecutionBlocker,
    StepIntentExecutionDiagnostic,
    StepIntentPlannerInsight,
    StepIntentPreflightAnalyzer,
    StepIntentPreflightIssue,
    StepIntentNormalizationAction,
    StepIntentRepairAttempt,
    StepIntentValidator,
    StepIntentNormalizer,
    StrategyDraftValidationError,
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.session import StructuredSolveError
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import _last_previous_attempt
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import _repair_instruction
from shuxueshuo_server.solver.runtime.strategy_compiler import (
    DEFAULT_BINDING_SELECTORS,
    DEFAULT_RECIPE_COMPILERS,
    _output_key_from_promote_source,
    _parameter_output_key_from_symbol_path,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    PrepInvocationBuilder,
    _RecipePlanCompiler,
    _candidate_error_for_exception,
    _method_outputs_for_step,
    _promote_outputs_for_step,
    _target_path_for_produced,
)
from shuxueshuo_server.solver.runtime.binding_rules import _parameter_value_handle, _point_output_handle
from shuxueshuo_server.solver.runtime.strategy_resolver import build_executable_capabilities
from shuxueshuo_server.solver.runtime.strategy_normalizer import NormalizationRuleResult
from shuxueshuo_server.solver.runtime.strategy_models import StepIntentScope


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
LLM_SCHEMA = "../internal/schemas/solver-llm-problem-ir.schema.json"
NANKAI_EXECUTABLE_STEP_INTENTS = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-fixtures"
    / "tj-2026-nankai-yimo-25.executable-step-intents.json"
)
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
XIQING_FIXTURE = "../internal/solver-fixtures/tj-2026-xiqing-yimo-25.json"
HEPING_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-yimo-25.json"
HEPING_ERMO_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-ermo-25.json"
HEPING_ERMO_EXECUTABLE_STEP_INTENTS = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-fixtures"
    / "tj-2026-heping-ermo-25.executable-step-intents.json"
)

def _nankai_problem():
    """加载南开 25 runtime ProblemIR。"""
    return load_problem_ir(NANKAI_FIXTURE)


def _repo_root() -> Path:
    """测试文件位于 server/tests/solver，向上三层是仓库根目录。"""
    return Path(__file__).resolve().parents[3]


def _nankai_llm_problem() -> dict:
    """从 canonical ProblemIR 投影给 LLM prompt 使用的南开题目 IR。"""
    return problem_to_llm_payload(_nankai_problem())


def _registry() -> CanonicalHandleRegistry:
    """构建南开 LLM ProblemIR 的 canonical handle registry。"""
    return CanonicalHandleRegistry.from_problem_payload(_nankai_llm_problem())


def _nankai_inputs():
    """构建南开 25 的真实 Strategy probe 输入。"""
    return build_strategy_probe_inputs(_nankai_problem())


def _runtime_context():
    """构建南开 runtime context。"""
    return ContextBuilder().build(_nankai_problem())


def _question_goals():
    """读取南开 QuestionGoal。"""
    return extract_question_goals(_nankai_problem())


def _nankai_payload() -> dict:
    """构建使用精简 LLM IR 的 Strategy payload。"""
    return StrategyPayloadBuilder().build(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
    )


def _hexi_llm_problem() -> dict:
    """从 canonical ProblemIR 投影给 LLM prompt 使用的河西题目 IR。"""
    return problem_to_llm_payload(load_problem_ir(HEXI_FIXTURE))


def _heping_llm_problem() -> dict:
    """从 canonical ProblemIR 投影给 LLM prompt 使用的和平题目 IR。"""
    return problem_to_llm_payload(load_problem_ir(HEPING_FIXTURE))


def _heping_inputs():
    """构建和平 25 的真实 Strategy probe 输入。"""
    return build_strategy_probe_inputs(load_problem_ir(HEPING_FIXTURE))


def _heping_binding_index() -> CanonicalRuntimeBindingIndex:
    """构建和平 25 的 canonical handle 到 runtime path 索引。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    return CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )


def _heping_ermo_problem():
    """加载和平二模 25 runtime ProblemIR。"""
    return load_problem_ir(HEPING_ERMO_FIXTURE)


def _heping_ermo_llm_problem() -> dict:
    """从 canonical ProblemIR 投影给 LLM prompt 使用的和平二模题目 IR。"""
    return problem_to_llm_payload(_heping_ermo_problem())


def _heping_ermo_inputs():
    """构建和平二模 25 的真实 Strategy probe 输入。"""
    return build_strategy_probe_inputs(_heping_ermo_problem())


def _create(
    handle: str,
    entity_type: str,
    valid_scope: str,
    description: str | None = None,
) -> dict[str, str]:
    """测试用 creates 对象。"""
    return {
        "handle": handle,
        "entity_type": entity_type,
        "valid_scope": valid_scope,
        "description": description or f"{handle} 在 {valid_scope} 内有效",
    }


def _produce(
    handle: str,
    valid_scope: str,
    description: str | None = None,
    output_type: str | None = None,
) -> dict[str, str]:
    """测试用 produces 对象。"""
    payload = {
        "handle": handle,
        "valid_scope": valid_scope,
        "description": description or f"{handle} 在 {valid_scope} 内有效",
    }
    if output_type is not None:
        payload["output_type"] = output_type
    return payload


def _step(
    *,
    scope_id: str,
    step_id: str,
    recipe_hint: str | None,
    goal_type: str,
    target: str,
    reads: tuple[str, ...] = (),
    produces: tuple[ProducedFact, ...] = (),
    strategy: str = "测试 step",
) -> StepIntent:
    """构造 normalizer 单测使用的最小 StepIntent。"""
    return StepIntent(
        scope_id=scope_id,
        step_id=step_id,
        recipe_hint=recipe_hint,
        goal_type=goal_type,
        target=target,
        strategy=strategy,
        reads=reads,
        produces=produces,
    )


def _single_scope_draft(*steps: StepIntent, scope_id: str = "iii") -> StepIntentDraft:
    """构造单 scope StepIntentDraft。"""
    return StepIntentDraft(
        scopes=(StepIntentScope(scope_id=scope_id, label=f"scope {scope_id}", steps=steps),)
    )


def _heping_ermo_i2_curve_condition_draft(
    *,
    candidate_reads: tuple[str, ...],
) -> StepIntentDraft:
    """构造和平二模第（Ⅰ）②曲线条件候选点回归测试草稿。"""
    return StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="i_1",
                label="第（Ⅰ）①问",
                steps=(
                    _step(
                        scope_id="i_1",
                        step_id="derive_parabola_i1",
                        recipe_hint="quadratic_from_constraints",
                        goal_type="derive_parabola",
                        target="fact:i:parabola_expression",
                        reads=(
                            "symbol:problem:b",
                            "symbol:problem:c",
                            "fact:i:b_value",
                            "fact:i:c_value",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i:parabola_expression",
                                "i",
                                "第（Ⅰ）问抛物线解析式",
                                output_type="Parabola",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_1",
                        step_id="derive_left_intercept_i1",
                        recipe_hint="quadratic_x_axis_intercept_point",
                        goal_type="derive_x_axis_intercept_point",
                        target="answer:i_1.A",
                        reads=(
                            "fact:i:parabola_expression",
                            "point:problem:A",
                            "fact:problem:A_on_parabola",
                        ),
                        produces=(
                            ProducedFact("answer:i_1.A", "i_1", "A 点坐标", output_type="Point"),
                            ProducedFact("fact:i:A_coordinate", "i", "A 坐标后续可用", output_type="Point"),
                        ),
                    ),
                ),
            ),
            StepIntentScope(
                scope_id="i_2",
                label="第（Ⅰ）②问",
                steps=(
                    _step(
                        scope_id="i_2",
                        step_id="parameterize_point_E_i2",
                        recipe_hint="quadratic_axis_parameterized_point",
                        goal_type="parameterize_point_on_quadratic_axis",
                        target="fact:i_2:E_parametric_coordinate",
                        reads=(
                            "fact:i:parabola_expression",
                            "point:i_2:E",
                            "fact:i_2:E_on_axis",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:E_parametric_coordinate",
                                "i_2",
                                "E 坐标表达式",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_2",
                        step_id="construct_G_from_square_i2",
                        recipe_hint="square_adjacent_vertex_from_side",
                        goal_type="derive_square_adjacent_vertex_from_side",
                        target="fact:i_2:G_coordinate_expr",
                        reads=(
                            "fact:i:A_coordinate",
                            "fact:i_2:E_parametric_coordinate",
                            "point:i_2:G",
                            "fact:i_2:square_AEKG",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:G_coordinate_expr",
                                "i_2",
                                "G 坐标表达式",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_2",
                        step_id="derive_E_candidates_i2",
                        recipe_hint="point_candidates_from_curve_point_condition",
                        goal_type="derive_point_candidates_from_curve_point_condition",
                        target="answer:i_2.E",
                        reads=candidate_reads,
                        produces=(
                            ProducedFact(
                                "answer:i_2.E",
                                "i_2",
                                "E 的候选坐标",
                                output_type="PointList",
                            ),
                        ),
                    ),
                ),
            ),
        )
    )


def _parameter_answer_goal() -> QuestionGoal:
    """构造 normalizer 合并参数答案 step 所需的 QuestionGoal。"""
    return QuestionGoal(
        question_id="iii",
        id="iii_b",
        answer_key="b",
        target_path="$question.iii.outputs.b",
        value_type="ParameterValue",
        required=True,
    )


def _valid_step_intent_payload() -> dict[str, object]:
    """覆盖南开 required goals 的合法 StepIntent draft。"""
    return {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_axis_point",
                        "recipe_hint": "quadratic_axis_from_relation",
                        "goal_type": "derive_point",
                        "target": "answer:i.axis_point",
                        "strategy": "由系数关系确定对称轴，再得到对称轴与 x 轴交点。",
                        "reads": [
                            "function:problem:parabola",
                            "point:problem:D",
                            "fact:problem:coefficient_relation",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:problem:D_coordinate_value",
                                "problem",
                                "D 坐标结论，后续全题可用",
                            ),
                            _produce("answer:i.axis_point", "i", "第（Ⅰ）问 D 坐标答案"),
                        ],
                        "reason": "第（Ⅰ）问要求点 D 的坐标。",
                    },
                    {
                        "step_id": "derive_part_i_parabola",
                        "recipe_hint": "quadratic_from_constraints",
                        "goal_type": "derive_parabola",
                        "target": "answer:i.parabola",
                        "strategy": "把第（Ⅰ）问给定系数与系数关系代入抛物线。",
                        "reads": [
                            "function:problem:parabola",
                            "fact:i:a_value",
                            "fact:i:c_value",
                            "fact:problem:coefficient_relation",
                        ],
                        "creates": [],
                        "produces": [_produce("answer:i.parabola", "i")],
                        "reason": "第（Ⅰ）问要求抛物线解析式。",
                    },
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_constructed_point",
                        "recipe_hint": "right_angle_equal_length_construct_and_select",
                        "goal_type": "derive_point",
                        "target": "point:ii:N",
                        "strategy": "由直角等长关系先构造候选点，再结合第四象限和参数条件筛选。",
                        "reads": [
                            "point:problem:D",
                            "point:ii:M",
                            "point:ii:N",
                            "fact:problem:D_coordinate_value",
                            "fact:problem:m_gt_2",
                            "fact:ii:N_fourth_quadrant",
                            "fact:ii:right_angle_equal_length_MDN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii:N_coordinate_expr", "ii", "N 的坐标表达式")
                        ],
                        "reason": "第（Ⅱ）问后续都依赖 N 的坐标表达。",
                    },
                    {
                        "step_id": "solve_part_ii_one",
                        "recipe_hint": "path_minimum_by_straightened_distance",
                        "goal_type": "derive_parameter_and_minimum",
                        "target": "answer:ii_1.minimum_value",
                        "strategy": "先用 MN 长度条件求参数，再求抛物线与路径最小值。",
                        "reads": [
                            "function:problem:parabola",
                            "point:ii:M",
                            "point:ii:N",
                            "fact:ii:N_coordinate_expr",
                            "fact:ii_1:MN_length_squared_eq_10",
                            "fact:ii:path_minimum_target",
                        ],
                        "creates": [
                            _create(
                                "point:ii:D_prime",
                                "point",
                                "ii",
                                "折线拉直使用的辅助点",
                            )
                        ],
                        "produces": [
                            _produce("answer:ii_1.parabola", "ii_1"),
                            _produce("answer:ii_1.minimum_value", "ii_1"),
                        ],
                        "reason": "第（Ⅱ）①要求解析式和 EG+FG 最小值。",
                    }
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "solve_part_ii_two",
                        "recipe_hint": "parameter_from_minimum_value",
                        "goal_type": "derive_parameter_and_intersection",
                        "target": "answer:ii_2.intersection",
                        "strategy": "用路径最值条件反求参数，再求抛物线和最短路径对应的 G。",
                        "reads": [
                            "function:problem:parabola",
                            "point:ii:G",
                            "fact:ii:N_coordinate_expr",
                            "fact:ii:path_minimum_target",
                            "fact:ii_2:path_minimum_value_given",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("answer:ii_2.parabola", "ii_2"),
                            _produce("answer:ii_2.intersection", "ii_2"),
                        ],
                        "reason": "第（Ⅱ）②要求解析式和此时 G 的坐标。",
                    }
                ],
            },
        ]
    }


def _step_from_payload(raw_step: dict[str, object], *, scope_id: str):
    """测试中把单个 step dict 解析成 StepIntent。"""
    draft = StepIntentValidator().validate(
        {
            "scopes": [
                {
                    "scope_id": scope_id,
                    "label": scope_id,
                    "steps": [raw_step],
                }
            ]
        },
        handle_registry=_registry(),
    )
    return draft.steps[0]


def _unsafe_step_from_payload(raw_step: dict[str, object], *, scope_id: str):
    """只解析单个 step，不做跨 step handle 数据流校验。"""
    draft = StepIntentValidator().validate(
        {
            "scopes": [
                {
                    "scope_id": scope_id,
                    "label": scope_id,
                    "steps": [raw_step],
                }
            ]
        },
    )
    return draft.steps[0]


def test_step_intent_normalizer_accepts_injected_rule() -> None:
    """Normalizer 应通过 rule list 调度，新增 rule 不需要改主循环。"""

    class SyntheticRule:
        def apply(self, step, _context):  # noqa: ANN001
            return NormalizationRuleResult(
                step=StepIntent(
                    scope_id=step.scope_id,
                    step_id=step.step_id,
                    recipe_hint=step.recipe_hint,
                    goal_type=step.goal_type,
                    target="fact:i:synthetic_target",
                    strategy=step.strategy,
                    reads=step.reads,
                    creates=step.creates,
                    produces=step.produces,
                ),
                actions=(
                    StepIntentNormalizationAction(
                        action="synthetic_normalization_rule",
                        step_id=step.step_id,
                        handle=step.target,
                        target_step_id=None,
                        reason="测试注入 rule 被 normalizer 调用。",
                    ),
                ),
            )

    step = _step(
        scope_id="i",
        step_id="synthetic_rule_step",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_test",
        target="fact:i:old_target",
    )

    normalized, report = StepIntentNormalizer(rules=(SyntheticRule(),)).normalize(
        _single_scope_draft(step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].target == "fact:i:synthetic_target"
    assert [action.action for action in report.actions] == [
        "synthetic_normalization_rule"
    ]


def test_step_intent_validator_normalizes_string_null_recipe_hint() -> None:
    """LLM 偶尔会输出字符串 ``"null"``，应按空 recipe_hint 处理。"""
    step = _unsafe_step_from_payload(
        {
            "step_id": "derive_optional_utility",
            "recipe_hint": "null",
            "goal_type": "derive_utility",
            "target": "fact:i:utility",
            "strategy": "临时工具步骤",
            "reads": [],
            "creates": [],
            "produces": [],
            "reason": "测试字符串 null 归一化。",
        },
        scope_id="i",
    )

    assert step.recipe_hint is None


def test_step_intent_normalizer_merges_redundant_parameter_answer_step() -> None:
    """冗余参数答案 step 应合并到前序可输出 ParameterValue 的 recipe。"""
    recipe_step = _step(
        scope_id="iii",
        step_id="solve_candidate_and_parameter",
        recipe_hint="curve_candidate_parameter_solve",
        goal_type="derive_constructed_point",
        target="answer:ii_D",
        produces=(ProducedFact("fact:iii:b_value", "iii", "b 的参数值"),),
    )
    redundant_answer_step = _step(
        scope_id="iii",
        step_id="collect_b_answer",
        recipe_hint=None,
        goal_type="derive_parameter",
        target="answer:iii_b",
        produces=(ProducedFact("answer:iii_b", "iii", "第（Ⅲ）问 b 的答案"),),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(recipe_step, redundant_answer_step),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[_parameter_answer_goal()],
        handle_registry=_registry(),
    )

    steps = normalized.scopes[0].steps
    assert [step.step_id for step in steps] == ["solve_candidate_and_parameter"]
    assert [item.handle for item in steps[0].produces] == [
        "fact:iii:b_value",
        "answer:iii_b",
    ]
    assert [action.action for action in report.actions] == [
        "merge_redundant_parameter_answer_step"
    ]


def test_step_intent_normalizer_rewrites_quadratic_utility_fact_to_parabola() -> None:
    """quadratic_from_constraints 的 c_expr utility fact 应归一化成抛物线 fact。"""
    utility_step = _step(
        scope_id="ii",
        step_id="derive_c_expr",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:c_expr_in_b",
        produces=(
            ProducedFact(
                "fact:ii:c_expr_in_b",
                "ii",
                "由 a=2 和曲线点得到 c 用 b 表示的常数项",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(utility_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    produces = normalized.scopes[0].steps[0].produces
    assert [item.handle for item in produces] == ["fact:ii:parametric_parabola"]
    assert [action.action for action in report.actions] == [
        "normalize_quadratic_utility_fact_to_parabola"
    ]


@pytest.mark.parametrize("output_type", [None, "Equation", "Expression"])
def test_step_intent_normalizer_corrects_parabola_expr_marked_as_equation_or_expression(
    output_type: str | None,
) -> None:
    """抛物线解析式缺少类型或被标成 Equation/Expression 时应安全修正。"""
    parabola_step = _step(
        scope_id="i",
        step_id="derive_i_parabola",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:i:parabola_expr",
        produces=(
            ProducedFact(
                "fact:i:parabola_expr",
                "i",
                "第（Ⅰ）问抛物线解析式 y=-x^2+4x+3",
                output_type=output_type,
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(parabola_step, scope_id="i"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    produces = normalized.scopes[0].steps[0].produces
    assert produces[0].handle == "fact:i:parabola_expr"
    assert produces[0].output_type == "Parabola"
    assert [action.action for action in report.actions] == [
        "normalize_parabola_equation_output_type"
    ]


def test_step_intent_normalizer_rewrites_quadratic_relation_fact_to_parabola() -> None:
    """quadratic_from_constraints 的系数关系 utility fact 也应归一化成抛物线 fact。"""
    relation_step = _step(
        scope_id="ii",
        step_id="derive_b_c_relation",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:b_c_relation",
        produces=(ProducedFact("fact:ii:b_c_relation", "ii", "b 和 c 的关系"),),
    )
    use_step = _step(
        scope_id="ii",
        step_id="derive_C_coordinate",
        recipe_hint="quadratic_y_axis_intercept_point",
        goal_type="derive_point",
        target="fact:ii:C_coordinate_expr",
        reads=("fact:ii:b_c_relation",),
        produces=(ProducedFact("fact:ii:C_coordinate_expr", "ii", "C 坐标"),),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(relation_step, use_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].produces[0].handle == "fact:ii:parametric_parabola"
    assert normalized.scopes[0].steps[1].reads == ("fact:ii:parametric_parabola",)
    assert [action.action for action in report.actions] == [
        "normalize_quadratic_utility_fact_to_parabola"
    ]


def test_step_intent_normalizer_rewrites_coefficients_alias_to_existing_parabola_answer() -> None:
    """同一步已有 Parabola answer 时，coefficients 缓存应作为 Parabola alias。"""
    parabola_step = _step(
        scope_id="i_1",
        step_id="derive_parabola_i",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i_1_parabola",
        produces=(
            ProducedFact(
                "answer:i_1_parabola",
                "i_1",
                "第（Ⅰ）问抛物线解析式",
                output_type="Parabola",
            ),
            ProducedFact(
                "fact:i:parabola_coefficients",
                "i",
                "第（Ⅰ）问抛物线系数缓存",
            ),
        ),
    )
    use_step = _step(
        scope_id="i_2",
        step_id="derive_B_coordinate_i",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:i:B_coordinate",
        reads=("fact:i:parabola_coefficients", "point:problem:B"),
        produces=(
            ProducedFact(
                "fact:i:B_coordinate",
                "i",
                "第（Ⅰ）问 B 坐标",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i_1", label="第（Ⅰ）①问", steps=(parabola_step,)),
                StepIntentScope(scope_id="i_2", label="第（Ⅰ）②问", steps=(use_step,)),
            )
        ),
        family_spec=_heping_inputs().family_spec,
        question_goals=_heping_inputs().question_goals,
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert [item.handle for item in normalized.scopes[0].steps[0].produces] == [
        "answer:i_1_parabola"
    ]
    assert normalized.scopes[1].steps[0].reads == ("answer:i_1_parabola", "point:problem:B")
    assert [action.action for action in report.actions] == [
        "normalize_quadratic_utility_fact_to_parabola"
    ]


def test_step_intent_normalizer_drops_known_origin_coordinate_utility_step() -> None:
    """坐标原点这类已知点不需要单独 utility step 产生坐标 fact。"""
    origin_step = _step(
        scope_id="i_1",
        step_id="derive_origin_coordinate",
        recipe_hint=None,
        goal_type="derive_origin_coordinate",
        target="求原点 O 坐标",
        reads=("point:problem:O",),
        produces=(
            ProducedFact(
                "fact:problem:O_coordinate",
                "problem",
                "原点 O 坐标",
                output_type="Point",
            ),
        ),
    )
    use_step = _step(
        scope_id="i_2",
        step_id="derive_equal_angle",
        recipe_hint="angle_sum_equal_angle_candidates",
        goal_type="derive_equal_angle",
        target="fact:i_2:angle_OBF_eq_ACO",
        reads=("fact:problem:O_coordinate", "fact:i_2:angle_sum_CBE_ACO_45"),
        produces=(
            ProducedFact(
                "fact:i_2:angle_OBF_eq_ACO",
                "i_2",
                "等角关系",
                output_type="AngleEquality",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i_1", label="第（Ⅰ）①问", steps=(origin_step,)),
                StepIntentScope(scope_id="i_2", label="第（Ⅰ）②问", steps=(use_step,)),
            )
        ),
        family_spec=_heping_inputs().family_spec,
        question_goals=_heping_inputs().question_goals,
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert normalized.scopes[0].steps == ()
    assert normalized.scopes[1].steps[0].reads == (
        "point:problem:O",
        "fact:i_2:angle_sum_CBE_ACO_45",
    )
    assert [action.action for action in report.actions] == [
        "drop_known_point_coordinate_utility_step"
    ]


def test_step_intent_normalizer_corrects_wrong_hint_for_quadratic_utility_fact() -> None:
    """二次函数 utility relation 即使 hint 错填为参数 method，也应归一化。"""
    relation_step = _step(
        scope_id="ii",
        step_id="derive_coefficient_relation_from_A",
        recipe_hint="parameter_from_expression_value",
        goal_type="derive_coefficient_relation",
        target="fact:ii:b_expr_in_a",
        reads=(
            "function:problem:parabola",
            "fact:problem:A_on_parabola",
            "fact:problem:A_coordinate_value",
        ),
        produces=(
            ProducedFact(
                "fact:ii:b_expr_in_a",
                "ii",
                "由 A 在抛物线上得到 b 用 a 表示的系数关系",
                output_type="Equation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(relation_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    step = normalized.scopes[0].steps[0]
    assert step.recipe_hint == "quadratic_from_constraints"
    assert step.target == "fact:ii:parametric_parabola"
    assert step.produces[0].handle == "fact:ii:parametric_parabola"
    assert step.produces[0].output_type == "Parabola"
    assert [action.action for action in report.actions] == [
        "normalize_quadratic_utility_fact_to_parabola"
    ]


def test_step_intent_normalizer_does_not_absorb_shared_coefficients_cache() -> None:
    """公共含参系数缓存 step 仍应交给 LLM repair，不被 normalizer 吞掉。"""
    coefficients_step = _step(
        scope_id="ii",
        step_id="derive_parameter_expr_from_points",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parameter",
        target="fact:ii:coefficients_in_m",
        produces=(
            ProducedFact(
                "fact:ii:coefficients_in_m",
                "ii",
                "a,b,c 用 m 表示的表达式，公共可用",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(coefficients_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].produces[0].handle == "fact:ii:coefficients_in_m"
    assert report.actions == ()


def test_step_intent_normalizer_rewrites_parabola_coefficients_alias_to_parametric_parabola() -> None:
    """明确的 parabola coefficients alias 应归一化成可读 Parabola。"""
    coefficients_step = _step(
        scope_id="ii",
        step_id="derive_b_expr_a",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:parabola_coefficients_with_a",
        reads=(
            "function:problem:parabola",
            "fact:problem:A_coordinate_value",
            "fact:problem:A_on_parabola",
        ),
        produces=(
            ProducedFact(
                "fact:ii:parabola_coefficients_with_a",
                "ii",
                "抛物线系数 b = a - 3，保留参数 a",
                output_type="Coefficients",
            ),
        ),
    )
    use_step = _step(
        scope_id="ii",
        step_id="derive_B_coordinate_ii",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:ii:B_coordinate_expr",
        reads=(
            "function:problem:parabola",
            "fact:ii:parabola_coefficients_with_a",
            "point:problem:B",
        ),
        produces=(
            ProducedFact(
                "fact:ii:B_coordinate_expr",
                "ii",
                "B 坐标含参数 a",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(coefficients_step, use_step, scope_id="ii"),
        family_spec=QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
        question_goals=_heping_inputs().question_goals,
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    first, second = normalized.scopes[0].steps
    assert first.produces[0].handle == "fact:ii:parametric_parabola"
    assert first.produces[0].output_type == "Parabola"
    assert "fact:ii:parametric_parabola" in second.reads
    assert "fact:ii:parabola_coefficients_with_a" not in second.reads
    assert [action.action for action in report.actions] == [
        "normalize_quadratic_utility_fact_to_parabola"
    ]


def test_step_intent_normalizer_propagates_rewritten_handle_to_later_reads() -> None:
    """前序 utility fact 改名后，后续 reads 必须同步改写。"""
    utility_step = _step(
        scope_id="ii",
        step_id="derive_c_expr",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:c_expr_in_b",
        produces=(ProducedFact("fact:ii:c_expr_in_b", "ii", "c_expr"),),
    )
    use_step = _step(
        scope_id="ii",
        step_id="derive_C_coordinate",
        recipe_hint="quadratic_y_axis_intercept_point",
        goal_type="derive_point",
        target="fact:ii:C_coordinate_expr",
        reads=("fact:ii:c_expr_in_b",),
        produces=(ProducedFact("fact:ii:C_coordinate_expr", "ii", "C 坐标"),),
    )

    normalized, _report = StepIntentNormalizer().normalize(
        _single_scope_draft(utility_step, use_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[1].reads == ("fact:ii:parametric_parabola",)
    assert normalized.scopes[0].steps[1].target == "fact:ii:C_coordinate_expr"


def test_step_intent_normalizer_merges_candidate_point_facts_to_point_list() -> None:
    """候选生成 method 拆出的多个点坐标 fact 应合并为 PointList fact。"""
    candidate_step = _step(
        scope_id="ii",
        step_id="construct_D_candidates",
        recipe_hint="right_angle_equal_length_candidates",
        goal_type="derive_constructed_point",
        target="fact:ii:D_candidates",
        produces=(
            ProducedFact("fact:ii:D1_coordinate_expr", "ii", "候选点 D1 坐标"),
            ProducedFact("fact:ii:D2_coordinate_expr", "ii", "候选点 D2 坐标"),
        ),
    )
    use_step = _step(
        scope_id="ii",
        step_id="solve_D",
        recipe_hint="curve_candidate_parameter_solve",
        goal_type="derive_constructed_point",
        target="answer:ii_D",
        reads=("fact:ii:D1_coordinate_expr", "fact:ii:D2_coordinate_expr"),
        produces=(ProducedFact("answer:ii_D", "ii", "D 坐标"),),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(candidate_step, use_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].produces[0].handle == "fact:ii:D_candidates"
    assert normalized.scopes[0].steps[1].reads == (
        "fact:ii:D_candidates",
        "fact:ii:D_candidates",
    )
    assert {action.action for action in report.actions} == {
        "normalize_candidate_point_facts_to_point_list"
    }

    resolution = StepIntentCandidateResolver().resolve(
        normalized,
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        method_specs=MethodSpecRegistry.load_from_code(),
        handle_registry=_registry(),
    )
    construct_report = next(
        report for report in resolution.step_reports
        if report.step_id == "construct_D_candidates"
    )
    assert construct_report.selected_capability_id == "right_angle_equal_length_candidates"


def test_step_intent_normalizer_rewrites_generic_point_coordinate_from_answer_target() -> None:
    """泛化点坐标 fact 应按同 step Point answer 的 target_path 归一化真实点名。"""
    axis_step = _step(
        scope_id="i",
        step_id="derive_axis_point",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="answer:i.axis_point",
        produces=(
            ProducedFact("answer:i.axis_point", "i", "点坐标答案"),
            ProducedFact("fact:problem:axis_point_coordinate", "problem", "对称轴交点坐标"),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(axis_step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [item.handle for item in normalized.scopes[0].steps[0].produces] == [
        "answer:i.axis_point",
        "fact:problem:D_coordinate",
    ]
    assert [action.action for action in report.actions] == [
        "normalize_point_coordinate_answer_fact",
        "normalize_axis_point_alias_fact",
    ]


def test_axis_point_answer_and_reusable_fact_alias_pass_capability_alignment() -> None:
    """axis Point answer 和同点可复用 fact alias 不应被能力 gate 误杀。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_axis_point_i",
                        "recipe_hint": "quadratic_axis_from_relation",
                        "goal_type": "derive_axis_point",
                        "target": "answer:i.axis_point",
                        "strategy": "由抛物线对称轴公式和系数关系得到 D 点坐标。",
                        "reads": ["fact:problem:coefficient_relation", "point:problem:D"],
                        "creates": [],
                        "produces": [
                            _produce("answer:i.axis_point", "i", "第（Ⅰ）问 D 点坐标", output_type="Point"),
                            _produce("fact:problem:D_coordinate", "problem", "全题公共 D 坐标", output_type="Point"),
                        ],
                        "reason": "两个 produced 是同一个 Point 输出的 answer/fact alias。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=[],
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert report.recipe_alignment.capability_errors == ()


def test_path_reduction_allows_distance_text_when_output_is_transformation() -> None:
    """路径降维 description 里出现“距离”时，不应被误判为最小值混产。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "reduce_two_moving_points_path",
                        "recipe_hint": "two_moving_points_path_reduction",
                        "goal_type": "reduce_path_expression",
                        "target": "fact:ii:single_moving_path_equivalence",
                        "strategy": "把两动点路径转化为到固定点的距离与另一段距离之和。",
                        "reads": [
                            "fact:ii:segment_DE_eq_sqrt2_NG",
                            "fact:ii:segment_E_on_DM",
                            "fact:ii:segment_G_on_MN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:single_moving_path_equivalence",
                                "ii",
                                "双动点路径 EG+FG 已转化为等价单动点折线路径，例如变为 E 到某固定点的距离与另一段的和",
                                output_type="PathTransformation",
                            )
                        ],
                        "reason": "这里只做路径等价转化，不计算最小值。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=[],
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert report.recipe_alignment.capability_errors == ()


def test_path_reduction_rejects_structured_minimum_expression_output() -> None:
    """路径降维 recipe 真正 produced MinimumExpression 时仍应被能力 gate 拦截。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "reduce_two_moving_points_path",
                        "recipe_hint": "two_moving_points_path_reduction",
                        "goal_type": "reduce_path_expression",
                        "target": "fact:ii:path_minimum_expression",
                        "strategy": "把路径降维并顺手算出最小值表达式。",
                        "reads": [
                            "fact:ii:segment_DE_eq_sqrt2_NG",
                            "fact:ii:segment_E_on_DM",
                            "fact:ii:segment_G_on_MN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:path_minimum_expression",
                                "ii",
                                "路径最小值表达式",
                                output_type="MinimumExpression",
                            )
                        ],
                        "reason": "混入了后续最小值计算。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=[],
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert report.recipe_alignment.capability_errors == (
        {
            "code": "recipe_mixes_minimum_value",
            "goal_type": "reduce_path_expression",
            "message": "path reduction must not produce minimum value",
            "recipe_hint": "two_moving_points_path_reduction",
            "step_id": "reduce_two_moving_points_path",
        },
    )


def test_axis_point_normalizer_merges_repeated_public_coordinate_step() -> None:
    """重复 public D coordinate utility step 应合并到前序 axis answer step。"""
    answer_step = _step(
        scope_id="i",
        step_id="derive_axis_point_i",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="answer:i.axis_point",
        reads=("fact:problem:coefficient_relation", "point:problem:D"),
        produces=(ProducedFact("answer:i.axis_point", "i", "第（Ⅰ）问 D 点坐标", output_type="Point"),),
    )
    repeated_fact_step = _step(
        scope_id="i",
        step_id="derive_public_D_coordinate",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="fact:problem:D_coordinate",
        reads=("fact:problem:coefficient_relation", "point:problem:D"),
        produces=(
            ProducedFact(
                "fact:problem:D_coordinate",
                "problem",
                "全题公共结论：D 点坐标",
                output_type="Point",
            ),
        ),
    )
    use_step = _step(
        scope_id="ii",
        step_id="construct_N_coordinate",
        recipe_hint="right_angle_equal_length_construct_and_select",
        goal_type="derive_constructed_point",
        target="fact:ii:N_coordinate_expr",
        reads=("fact:problem:D_coordinate",),
        produces=(ProducedFact("fact:ii:N_coordinate_expr", "ii", "N 坐标", output_type="Point"),),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i", label="第（Ⅰ）问", steps=(answer_step, repeated_fact_step)),
                StepIntentScope(scope_id="ii", label="第（Ⅱ）问", steps=(use_step,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [step.step_id for step in normalized.scopes[0].steps] == ["derive_axis_point_i"]
    assert [item.handle for item in normalized.scopes[0].steps[0].produces] == [
        "answer:i.axis_point",
        "fact:problem:D_coordinate",
    ]
    assert normalized.scopes[1].steps[0].reads == ("fact:problem:D_coordinate",)
    assert [action.action for action in report.actions] == ["normalize_axis_point_alias_fact"]


def test_axis_point_capability_rejects_multiple_coordinate_fact_points() -> None:
    """axis method 不能在同一步产出多个不同点名的坐标 fact。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_two_axis_points",
                        "recipe_hint": "quadratic_axis_from_relation",
                        "goal_type": "derive_axis_point",
                        "target": "answer:i.axis_point",
                        "strategy": "错误地同时产出两个不同点。",
                        "reads": ["fact:problem:coefficient_relation"],
                        "creates": [],
                        "produces": [
                            _produce("fact:problem:D_coordinate", "problem", output_type="Point"),
                            _produce("fact:problem:G_coordinate", "problem", output_type="Point"),
                        ],
                        "reason": "负例。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=[],
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert report.recipe_alignment.capability_errors[0]["code"] == (
        "method_mixes_multiple_axis_points"
    )


def test_distance_capability_allows_minimum_value_answer_handle() -> None:
    """distance method 不应把 minimum_value answer 误判为 m_value 参数输出。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "compute_minimum_value_ii1",
                        "recipe_hint": "distance_between_points",
                        "goal_type": "derive_minimum_value",
                        "target": "answer:ii_1.minimum_value",
                        "strategy": "代入 m 值计算具体最小值。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            _produce(
                                "answer:ii_1.minimum_value",
                                "ii_1",
                                "EG+FG 的最小值",
                                output_type="MinimumExpression",
                            )
                        ],
                        "reason": "minimum_value 是最小值答案，不是 m_value 参数 fact。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=[],
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert report.recipe_alignment.capability_errors == ()


def test_step_intent_normalizer_keeps_generic_point_coordinate_when_answer_ambiguous() -> None:
    """多个 Point answer 同步出现时不猜测泛化坐标 fact 的真实点名。"""
    ambiguous_goals = [
        QuestionGoal("i", "i.axis_point", "D", "$problem.points.D", "Point", True),
        QuestionGoal("i", "i.other_point", "G", "$question.i.points.G", "Point", True),
    ]
    step = _step(
        scope_id="i",
        step_id="derive_two_points",
        recipe_hint="line_intersection_point",
        goal_type="derive_point",
        target="answer:i.axis_point",
        produces=(
            ProducedFact("answer:i.axis_point", "i", "点 D"),
            ProducedFact("answer:i.other_point", "i", "点 G"),
            ProducedFact("fact:problem:axis_point_coordinate", "problem", "泛化坐标"),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=ambiguous_goals,
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].produces[-1].handle == "fact:problem:axis_point_coordinate"
    assert report.actions == ()


def test_curve_candidate_parameter_output_key_uses_dynamic_symbol_name() -> None:
    """候选点反求参数 recipe 的参数输出 key 不应固定为 b。"""
    assert _parameter_output_key_from_symbol_path("$problem.symbols.m") == "m"
    assert _parameter_output_key_from_symbol_path("$question.ii.symbols.t") == "t"


def test_dynamic_parameter_constraint_uses_step_reads_not_hardcoded_n() -> None:
    """weighted 动点参数约束应从 StepIntent reads 消歧，不应固定为 n。"""
    problem = load_problem_ir(HEXI_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_hexi_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    # 模拟同 family 的另一道题：主参数仍为 b，但动点参数叫 t。
    index.register("symbol:problem:t", "$problem.symbols.t", "Symbol", source="test")
    index.register("fact:problem:t_gt_0", "$problem.constraints.t", "Constraint", source="test")
    index.fact_types["fact:problem:t_gt_0"] = "symbol_constraint"
    step = _step(
        scope_id="iii",
        step_id="derive_minimum_expression",
        recipe_hint="linked_broken_path_minimum_expression",
        goal_type="derive_minimum_expression",
        target="fact:iii:minimum_expression",
        reads=(
            "symbol:problem:b",
            "fact:problem:b_gt_0",
            "symbol:problem:t",
            "fact:problem:t_gt_0",
        ),
    )

    assert index.parameter_symbol_path() == "$problem.symbols.b"
    assert index.parameter_constraint_path() == "$problem.constraints.b"
    assert index.dynamic_parameter_symbol_path(step=step) == "$problem.symbols.t"
    assert index.dynamic_constraint_path(step=step) == "$problem.constraints.t"


def test_parameter_symbol_uses_symbol_roles_not_fixed_coefficient_names() -> None:
    """主参数推断应读取 symbol_roles，不依赖固定的 a/b/c 排除表。"""
    problem = ProblemIR(
        problem_id="synthetic-symbol-role-parameter",
        pattern="path-minimum",
        problem_type="quadratic_path_minimum",
        symbols=["x", "p", "q", "r", "t"],
        symbol_roles={
            "x": "function_variable",
            "p": "quadratic_coefficient",
            "q": "quadratic_coefficient",
            "r": "quadratic_coefficient",
            "t": "dynamic_parameter",
        },
        constraints={"p": ">0", "t": ">1"},
        data={
            "function": {
                "expression": "p*x**2 + q*x + r",
            },
            "questions": [],
        },
    )
    problem_payload = {
        "original_text": ["synthetic"],
        "scopes": [{"scope_id": "problem", "parent": None}],
        "entities": [
            {"handle": f"symbol:problem:{name}", "entity_type": "symbol", "scope_id": "problem"}
            for name in ("x", "p", "q", "r", "t")
        ],
        "facts": [
            {
                "handle": "fact:problem:p_gt_0",
                "type": "symbol_constraint",
                "scope_id": "problem",
                "valid_scope": "problem",
            },
            {
                "handle": "fact:problem:t_gt_1",
                "type": "symbol_constraint",
                "scope_id": "problem",
                "valid_scope": "problem",
            },
        ],
        "question_goals": [],
    }
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(problem_payload),
        question_goals=(),
    )

    assert index.parameter_symbol_path() == "$problem.symbols.t"
    assert index.parameter_constraint_path() == "$problem.constraints.t"


def test_structural_symbol_value_detection_uses_symbol_roles() -> None:
    """结构符号 value fact 的判断应支持非 a/b/c 的二次函数系数名。"""
    problem = ProblemIR(
        problem_id="synthetic-structural-symbol-value",
        pattern="path-minimum",
        problem_type="quadratic_path_minimum",
        symbols=["x", "p", "q", "r", "t"],
        symbol_roles={
            "x": "function_variable",
            "p": "quadratic_coefficient",
            "q": "quadratic_coefficient",
            "r": "quadratic_coefficient",
            "t": "dynamic_parameter",
        },
        constraints={},
        data={
            "function": {
                "expression": "p*x**2 + q*x + r",
            },
            "questions": [],
        },
    )
    problem_payload = {
        "original_text": ["synthetic"],
        "scopes": [{"scope_id": "problem", "parent": None}],
        "entities": [
            {"handle": f"symbol:problem:{name}", "entity_type": "symbol", "scope_id": "problem"}
            for name in ("x", "p", "q", "r", "t")
        ],
        "facts": [
            {
                "handle": "fact:problem:p_value",
                "type": "symbol_value",
                "scope_id": "problem",
                "valid_scope": "problem",
            },
            {
                "handle": "fact:problem:t_value",
                "type": "symbol_value",
                "scope_id": "problem",
                "valid_scope": "problem",
            },
        ],
        "question_goals": [],
    }
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(problem_payload),
        question_goals=(),
    )

    assert index.is_structural_symbol_value_fact("fact:problem:p_value") is True
    assert index.is_structural_symbol_value_fact("fact:problem:t_value") is False


def test_parameter_value_binding_skips_structural_symbol_value_fact() -> None:
    """parameter_value_if_read 不应靠 a/b/c 硬编码排除已知系数值。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    index.fact_types["fact:i:a_value"] = "symbol_value"
    index.register("fact:i:a_value", "$question.i.outputs.a_value", "ParameterValue", source="test")
    index.register("fact:ii:m_value", "$question.ii.outputs.m", "ParameterValue", source="test")
    step = _step(
        scope_id="ii",
        step_id="use_parameter_value",
        recipe_hint="synthetic_method",
        goal_type="derive_expression",
        target="fact:ii:expression_value",
        reads=("fact:i:a_value", "fact:ii:m_value"),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="synthetic_method",
                expansion_selectors=("parameter_value_if_read",),
            ),
        )
    )

    inputs = rules.bind("synthetic_method", step, index)

    assert inputs["parameter"] == "$problem.symbols.m"
    assert inputs["parameter_value"] == "$question.ii.outputs.m"


def test_parameter_value_binding_uses_unique_visible_parameter_value_when_not_read() -> None:
    """若当前 scope 已有唯一参数值，LLM 未显式 reads 时也可传给支持代入的 method。"""
    problem = _heping_ermo_problem()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    index.register(
        "fact:ii:c_value",
        "$question.ii.outputs.c",
        "ParameterValue",
        source="step:solve_parameter_c",
    )
    step = _step(
        scope_id="ii",
        step_id="recover_point_E_from_square",
        recipe_hint="square_adjacent_vertex_from_side",
        goal_type="derive_square_adjacent_vertex_from_side",
        target="answer:ii.E",
        reads=(
            "fact:ii:A_coordinate_value",
            "fact:ii:optimal_G_coordinate",
            "fact:ii:square_AEKG",
        ),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="square_adjacent_vertex_from_side",
                expansion_selectors=("parameter_value_if_read",),
            ),
        )
    )

    inputs = rules.bind("square_adjacent_vertex_from_side", step, index)

    assert inputs["parameter"] == "$problem.symbols.c"
    assert inputs["parameter_value"] == "$question.ii.outputs.c"


def test_line_locus_minimum_point_uses_visible_straightening_endpoints_when_not_read() -> None:
    """LLM 若少读 path_minimum_point_1/2，binding 可从前序拉直 recipe 输出补位。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    payload = json.loads(HEPING_ERMO_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    for scope in payload["scopes"]:
        if scope["scope_id"] != "ii":
            continue
        for step in scope["steps"]:
            if step.get("recipe_hint") == "line_locus_minimum_point":
                step["reads"] = [
                    handle for handle in step["reads"]
                    if handle not in {
                        "fact:ii:path_minimum_point_1",
                        "fact:ii:path_minimum_point_2",
                    }
                ]
    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True


def test_llm_problem_ir_schema_file_exists_and_fixture_is_canonical() -> None:
    """LLM ProblemIR 以 Entity/Fact/answer 为一等结构，不夹带旧 solver 字段。"""
    schema_path = _repo_root() / "internal" / "schemas" / "solver-llm-problem-ir.schema.json"
    assert schema_path.exists()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["required"] == ["original_text", "scopes", "entities", "facts", "question_goals"]

    problem_payload = _nankai_llm_problem()
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    assert "point:problem:D" in registry.entity_handles
    assert "fact:ii:right_angle_equal_length_MDN" in registry.fact_handles
    assert "answer:ii_2.intersection" in registry.answer_handles

    serialized = json.dumps(problem_payload, ensure_ascii=False)
    assert '"relations"' not in serialized
    assert '"points"' not in serialized
    assert "target_path" not in serialized
    assert "expected" not in serialized


def test_strategy_payload_builder_uses_problem_ir_without_expected_answers() -> None:
    """payload 应直接携带 LLM ProblemIR JSON，并且不夹带 expected answer。"""
    payload = StrategyPayloadBuilder(
        few_shot_examples=[{"family_id": "fake", "steps": []}]
    ).build(_nankai_inputs(), problem_payload=_nankai_llm_problem())

    expected_keys = {
        "problem_ir",
        "naming_conventions",
        "family_spec",
        "method_catalog",
        "recipe_catalog",
        "few_shot_examples",
        "previous_attempts",
        "output_json_schema",
    }
    assert set(payload) == expected_keys | {"problem_id", "family_id"}
    assert payload["problem_ir"]["problem_id"] == "tj-2026-nankai-yimo-25"
    assert "已知抛物线" in "\n".join(payload["problem_ir"]["original_text"])
    assert payload["problem_ir"]["question_goals"][0]["handle"] == "answer:i.axis_point"
    assert payload["family_spec"]["family_id"] == "QuadraticPathMinimumSolver"
    assert payload["output_json_schema"] == STEP_INTENT_JSON_SCHEMA
    assert payload["few_shot_examples"] == [{"family_id": "fake", "steps": []}]

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "expected_answers" not in serialized
    assert "expected" not in serialized
    assert "target_path" not in serialized
    assert '"relations"' not in serialized
    assert '"points"' not in serialized


@pytest.mark.parametrize(
    ("fixture", "answer_handle", "expected_description", "forbidden_text"),
    [
        (
            NANKAI_FIXTURE,
            "answer:ii_1.minimum_value",
            "第（Ⅱ）①问输出 EG+FG 的最小值",
            None,
        ),
        (
            HEXI_FIXTURE,
            "answer:iii_b",
            "第（Ⅲ）问输出 由 sqrt(2)*MN+AN 的最小值求 b 的值",
            "EG+FG",
        ),
        (
            XIQING_FIXTURE,
            "answer:ii_2_b",
            "第（Ⅱ）②问输出 由 2DM+AM 的最小值求 b 的值",
            "EG+FG",
        ),
        (
            HEPING_FIXTURE,
            "answer:ii_a",
            "第（Ⅱ）问输出 由 OM+BN 的最小值求 a 的值",
            "EG+FG",
        ),
    ],
)
def test_projection_goal_description_uses_problem_path_minimum_fact(
    fixture: str,
    answer_handle: str,
    expected_description: str,
    forbidden_text: str | None,
) -> None:
    """最小值相关 answer 描述应从题目 path fact 派生，不能写死南开 EG+FG。"""
    payload = problem_to_llm_payload(load_problem_ir(fixture))
    descriptions = {
        goal["handle"]: goal["description"]
        for goal in payload["question_goals"]
    }

    assert descriptions[answer_handle] == expected_description
    if forbidden_text is not None:
        assert forbidden_text not in descriptions[answer_handle]


def test_strategy_payload_builder_projects_canonical_problem_ir() -> None:
    """不传外部 LLM payload 时，builder 可从 canonical ProblemIR 投影。"""
    payload = StrategyPayloadBuilder(
        few_shot_examples=[{"family_id": "fake", "steps": []}]
    ).build(_nankai_inputs())

    assert payload["problem_ir"] == _nankai_llm_problem()
    assert payload["problem_ir"]["problem_id"] == "tj-2026-nankai-yimo-25"


def test_strategy_probe_inputs_uses_empty_context_inventory() -> None:
    """Strategy probe 不再构建 visible paths / planning signals。"""
    inputs = _nankai_inputs()

    assert inputs.problem is not None
    assert inputs.problem.problem_id == "tj-2026-nankai-yimo-25"
    assert "_problem_ir" not in inputs.original_text
    assert inputs.context_inventory.visible_paths == ()
    assert inputs.context_inventory.planning_signals == ()


def test_method_catalog_is_family_allowlist_summary_not_method_schema() -> None:
    """StepIntent prompt 只暴露能力摘要，不暴露完整 input/output schema。"""
    payload = _nankai_payload()
    catalog = payload["method_catalog"]
    methods = catalog["methods"]

    assert methods
    assert all(set(method) == {"method_id", "title", "solves", "summary"} for method in methods)
    quadratic = next(
        method for method in methods
        if method["method_id"] == "quadratic_from_constraints"
    )
    spec = MethodSpecRegistry.load_from_code().require("quadratic_from_constraints")
    assert quadratic["summary"] == spec.summary
    assert "已知系数" in quadratic["summary"]
    assert "curve_point" not in json.dumps(catalog, ensure_ascii=False)
    assert "required" not in json.dumps(catalog, ensure_ascii=False)


def test_recipe_catalog_is_family_recipe_summary() -> None:
    """recipe_catalog 应完整来自 FamilySpec.step_recipes，不暴露 resolver 内部字段。"""
    payload = _nankai_payload()
    catalog = payload["recipe_catalog"]
    recipes = catalog["recipes"]

    recipe_ids = {recipe["recipe_id"] for recipe in recipes}
    assert recipe_ids == {
        "right_angle_equal_length_construct_and_select",
        "two_moving_points_path_reduction",
        "broken_path_straightening_and_select",
        "path_minimum_by_straightened_distance",
    }
    path_recipe = next(
        recipe for recipe in recipes
        if recipe["recipe_id"] == "two_moving_points_path_reduction"
    )
    assert path_recipe["priority"] == "preferred"
    assert set(path_recipe) == {
        "recipe_id",
        "goal_type",
        "title",
        "description",
        "method_ids",
        "priority",
    }
    serialized = json.dumps(catalog, ensure_ascii=False)
    assert "expected_reads" not in serialized
    assert "expected_creates" not in serialized
    assert "expected_produces" not in serialized
    assert "avoid_strategies" not in serialized
    assert "inputs" not in serialized


def test_strategy_payload_does_not_include_derived_context_tables() -> None:
    """Phase 1 prompt 不再发送派生 scope/relation/signal/semantic_context 表。"""
    payload = _nankai_payload()

    assert "visible_paths" not in payload
    assert "semantic_context" not in payload
    assert "scope_hierarchy" not in payload
    assert "relation_graph" not in payload
    assert "planning_signals" not in payload


def test_strategy_payload_includes_naming_conventions() -> None:
    """Strategy payload 应注入独立命名约定卡片。"""
    payload = _nankai_payload()
    conventions = payload["naming_conventions"]
    serialized = json.dumps(conventions, ensure_ascii=False)

    assert conventions["fact_handle_patterns"]["pattern"] == "fact:<scope>:<object_or_result>_<state>"
    assert "parametric_coordinate" in serialized
    assert "numeric_coordinate" in serialized
    assert "optimal_<Point>_coordinate" in serialized
    assert "path_minimum_expression" in serialized
    assert "$problem" not in serialized
    assert "$question" not in serialized
    assert "$subquestion" not in serialized
    assert "expected answer" not in serialized
    assert "raw DeepSeek" not in serialized


def test_strategy_payload_fails_when_naming_conventions_file_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命名约定文件缺失时应 fail fast，避免真实 LLM 静默少规则。"""
    monkeypatch.setattr(strategy_payload_module, "_default_template_dir", lambda: tmp_path)

    with pytest.raises(ValueError, match="naming conventions file missing"):
        _nankai_payload()


def test_strategy_payload_fails_when_naming_conventions_file_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """命名约定文件不是合法 JSON 时应 fail fast。"""
    (tmp_path / "strategy-naming-conventions.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(strategy_payload_module, "_default_template_dir", lambda: tmp_path)

    with pytest.raises(ValueError, match="naming conventions file is invalid JSON"):
        _nankai_payload()


def test_strategy_prompt_renderer_contains_core_sections() -> None:
    """prompt 应包含题目 JSON、FamilySpec、method 能力和 schema。"""
    payload = _nankai_payload()
    prompt = StrategyPromptRenderer().render(payload)

    assert "只输出 JSON" in prompt.system
    assert "JSON Schema" in prompt.system
    assert "顶层只能包含 `scopes`" in prompt.system
    assert "`problem` 是全题上下文根" in prompt.system
    assert "只能输出有 required answer goal 的 scope" in prompt.system
    assert "已知抛物线" in prompt.user
    assert "QuadraticPathMinimumSolver" in prompt.user
    assert "answer:i.parabola" in prompt.user
    assert "Recipe Catalog" in prompt.user
    assert "Method Catalog" in prompt.user
    assert "recipe_hint" in prompt.system
    assert "recipe_hint" in prompt.user
    assert "`recipe_hint: null` 是最后兜底" in prompt.system
    assert "不要把 `recipe_hint: null` 当成可执行兜底" in prompt.user
    assert "不要自造新的辅助点构造、路径转化或最值 recipe" in prompt.system
    assert "不要自造这类中间能力" in prompt.user
    assert "two_moving_points_path_reduction" in prompt.user
    assert "broken_path_straightening_and_select" in prompt.user
    assert "path_minimum_by_straightened_distance" in prompt.user
    assert "不创建辅助点或新轨迹" in prompt.user
    assert "path_minimum_by_straightened_distance" not in prompt.system
    assert "不要把多个 recipe 的职责混在同一个 step" in prompt.user
    assert "普通路径最值按 recipe 独立拆分" in prompt.user
    assert "单独求最小值表达式" in prompt.user
    assert "先定值，再代入" in prompt.user
    assert "不能定值但能降复杂度时先化简" in prompt.user
    assert "parabola_coefficients_expr" in prompt.user
    assert "coefficients_in_m" in prompt.user
    assert "不是独立 executable step" in prompt.user
    assert "父级 scope 只是组织子问" in prompt.user
    assert "输出公共推导段会被校验器拒绝" in prompt.user
    assert "Previous Attempts" in prompt.user
    assert "`repair_summary` 是最重要的修复摘要" in prompt.user
    assert "`frozen_prefix` 是系统已接受并会保留的步骤" in prompt.user
    assert "`do_not` 是硬约束" in prompt.user
    assert "public_derivation_scope_not_allowed" in prompt.user
    assert "create_overwrites_given_entity" in prompt.user
    assert "capability_errors" in prompt.user
    assert "executable_resolution_errors" in prompt.user
    assert "自由 Equation 中间关系" in prompt.user
    assert "严格对应一个 recipe 或一个 method" in prompt.user
    assert "已经出现在 ProblemIR 的 `entities[]`" in prompt.user
    assert "不能再放进 `creates`" in prompt.user
    assert "point:problem:Anchor" in prompt.system
    assert "不要改成当前子问 scope" in prompt.user
    assert "point:problem:Anchor" in prompt.user
    assert "## 当前题目 ProblemIR JSON" in prompt.user
    assert "## StepIntent Naming Conventions" in prompt.user
    assert "这些规则只用于你新输出的 `step_id`" in prompt.user
    assert "`reads` 中已有 handle 必须" in prompt.user
    assert "不要为了符合命名约定而改写已有 handle" in prompt.user
    assert "parametric_coordinate" in prompt.user
    assert "numeric_coordinate" in prompt.user
    assert "optimal_<Point>_coordinate" in prompt.user
    assert "path_minimum_expression" in prompt.user
    assert "## 示例题目 Few-shot" in prompt.user
    assert "不是当前题条件" in prompt.user
    assert "example.scopes[].steps[]" in prompt.user
    assert "同时输出 `answer:<goal.id>` 和公共 `fact:<scope>:<semantic_name>`" in prompt.user
    assert "同一个父级 Entity 点的坐标不能在兄弟小问分别 produces" in prompt.user
    assert "fact:problem:shared_coordinate_value" in prompt.user
    assert "derive_axis_point" in prompt.user
    assert "description 应说明结论可见范围" in prompt.system
    assert "`output_type` 是可选字段" in prompt.system
    assert "`output_type`：可选" in prompt.user
    assert "后续第（Ⅱ）①②可用" in prompt.user
    assert "一个 step 只解决一个清晰 goal_type" in prompt.system
    assert "answer:i.parabola" in prompt.user
    assert "strategy_principles" in prompt.user
    assert "quadratic_from_constraints" in prompt.user
    assert "Planning Signals" not in prompt.user
    assert "不要生成只复述已知条件的步骤" in prompt.user
    assert "record_relation" in prompt.user
    assert "utility step" in prompt.user
    assert "辅助点、中点、临时表达式" in prompt.user
    assert "Method Solver 可执行的最小解题颗粒度" in prompt.user
    assert "ExplanationBuilder" in prompt.system + prompt.user
    assert "只有 Recipe Catalog" in prompt.user
    assert "method_capability_hints" not in prompt.user
    assert "result_collection_policy" not in prompt.user
    assert "knowns" not in prompt.system
    assert "knowns" not in prompt.user
    assert "publish" not in prompt.system
    assert "publish" not in prompt.user
    combined = prompt.system + "\n" + prompt.user
    assert "ContextPath" not in combined
    assert "ctx_N" not in combined
    assert "$problem" not in combined
    assert "target_path" not in combined


def test_equal_length_family_uses_dedicated_mock_fallback_few_shot(tmp_path: Path) -> None:
    """等长射线路径 family 无真实样例时，应使用抽象辅助线 mock few-shot。"""
    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(_heping_inputs(), problem_payload=_heping_llm_problem())

    examples = payload["few_shot_examples"]
    assert len(examples) == 1
    example = examples[0]
    assert example["problem_id"] == "fallback-equal-length-ray-path-minimum"
    assert example["family_id"] == QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY.family_id

    steps = [
        step
        for scope in example["example"]["scopes"]
        for step in scope["steps"]
    ]
    assert [step["recipe_hint"] for step in steps] == [
        "equal_length_ray_path_reduction",
        "parameter_from_expression_value",
    ]
    assert [step["step_id"] for step in steps] == [
        "reduce_equal_length_ray_path",
        "solve_parameter_from_minimum",
    ]


def test_equal_length_fallback_does_not_reuse_heping_names(tmp_path: Path) -> None:
    """family mock few-shot 不能包含和平题 problem_id、路径名、点名或 fact 名。"""
    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(_heping_inputs(), problem_payload=_heping_llm_problem())
    serialized = json.dumps(payload["few_shot_examples"][0], ensure_ascii=False)

    forbidden_fragments = [
        "tj-2026-heping-yimo-25",
        "point:problem:B",
        "point:problem:C",
        "point:problem:D",
        "point:ii:M",
        "point:ii:N",
        "BC",
        "CD",
        "OM",
        "BN",
        "CN_eq_CM",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in serialized
    assert "equal_length_ray_path_reduction" in serialized
    assert "fact:demo:equal_length_condition" in serialized


def test_equal_length_fallback_is_rendered_as_example_not_current_problem(
    tmp_path: Path,
) -> None:
    """prompt 应把 family fallback 放在示例题目区，避免误当当前题条件。"""
    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(_heping_inputs(), problem_payload=_heping_llm_problem())
    prompt = StrategyPromptRenderer().render(payload)

    assert "## 当前题目 ProblemIR JSON" in prompt.user
    assert "## 示例题目 Few-shot" in prompt.user
    assert "fallback-equal-length-ray-path-minimum" in prompt.user
    assert "点 Moving 在一条线段上" in prompt.user
    assert "不是当前题条件" in prompt.user
    assert "抛物线" in prompt.user


def test_square_reflection_family_uses_dedicated_mock_fallback_few_shot(tmp_path: Path) -> None:
    """正方形反射路径 family 无真实样例时，应使用抽象 mock few-shot。"""
    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(_heping_ermo_inputs(), problem_payload=_heping_ermo_llm_problem())

    examples = payload["few_shot_examples"]
    assert len(examples) == 1
    example = examples[0]
    assert example["problem_id"] == "fallback-square-reflection-path-minimum"
    assert example["family_id"] == QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY.family_id

    steps = [
        step
        for scope in example["example"]["scopes"]
        for step in scope["steps"]
    ]
    assert [step["recipe_hint"] for step in steps] == [
        "quadratic_axis_parameterized_point",
        "square_adjacent_vertex_from_side",
        "point_candidates_from_curve_point_condition",
        "square_path_dimension_reduction",
        "parameterized_point_locus_line",
        "broken_path_straightening_minimum_expression",
        "parameter_from_expression_value",
        "line_locus_minimum_point",
        "square_adjacent_vertex_from_side",
    ]


def test_square_reflection_fallback_does_not_reuse_heping_ermo_names(tmp_path: Path) -> None:
    """square family mock few-shot 不能包含和平二模题号、点名、路径名或答案。"""
    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(_heping_ermo_inputs(), problem_payload=_heping_ermo_llm_problem())
    serialized = json.dumps(payload["few_shot_examples"][0], ensure_ascii=False)

    forbidden_fragments = [
        "tj-2026-heping-ermo-25",
        "point:problem:A",
        "point:i_2:E",
        "point:i_2:G",
        "point:ii:F",
        "point:ii:H",
        "point:problem:M",
        "HF+FM+MG",
        "3*sqrt(5)",
        "3√5",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in serialized
    assert "square_path_dimension_reduction" in serialized
    assert "broken_path_straightening_minimum_expression" in serialized


def test_other_families_keep_generic_fallback_few_shot(tmp_path: Path) -> None:
    """非等长射线路径 family 仍使用通用路径最值 fallback。"""
    payload = StrategyPayloadBuilder(
        few_shot_dir=tmp_path,
        allow_same_problem_few_shot=False,
    ).build(_nankai_inputs(), problem_payload=_nankai_llm_problem())
    serialized = json.dumps(payload["few_shot_examples"][0], ensure_ascii=False)

    assert payload["few_shot_examples"][0]["problem_id"] == "fallback-QuadraticPathMinimumSolver"
    assert "two_moving_points_path_reduction" in serialized
    assert "broken_path_straightening_and_select" in serialized
    assert "equal_length_ray_point" not in serialized


def test_step_intent_validator_accepts_valid_fake_draft() -> None:
    """合法 StepIntent draft 应能通过结构校验、handle 校验和 answer 覆盖校验。"""
    inputs = _nankai_inputs()
    raw = json.dumps(_valid_step_intent_payload(), ensure_ascii=False)

    draft = StepIntentValidator().validate_json(
        raw,
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
    )

    assert len(draft.steps) == 5
    assert [scope.scope_id for scope in draft.scopes] == ["i", "ii_1", "ii_2"]
    assert draft.scopes[0].steps[0].scope_id == "i"
    assert draft.steps[0].step_id == "derive_axis_point"
    assert draft.steps[0].recipe_hint == "quadratic_axis_from_relation"
    assert draft.steps[0].reads == (
        "function:problem:parabola",
        "point:problem:D",
        "fact:problem:coefficient_relation",
    )
    assert draft.steps[0].produces[0].handle == "fact:problem:D_coordinate_value"


def test_step_intent_validator_accepts_optional_produced_output_type() -> None:
    """produces.output_type 是可选结构化类型提示。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["produces"][0]["output_type"] = "Point"

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        question_goals=_nankai_inputs().question_goals,
        handle_registry=_registry(),
    )

    assert draft.steps[0].produces[0].output_type == "Point"
    assert draft.steps[0].to_payload()["produces"][0]["output_type"] == "Point"


def test_step_intent_validator_rejects_unknown_produced_output_type() -> None:
    """produces.output_type 必须来自 schema enum。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["produces"][0]["output_type"] = "Coordinate"

    with pytest.raises(
        StrategyDraftValidationError,
        match="output_type unsupported: Coordinate",
    ):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            question_goals=_nankai_inputs().question_goals,
            handle_registry=_registry(),
        )


def test_step_intent_validator_rejects_answer_output_type_mismatch() -> None:
    """answer handle 的 output_type 不能覆盖 QuestionGoal.value_type。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["produces"][0] = _produce(
        "answer:i.axis_point",
        "i",
        "点 D 的坐标答案",
        output_type="Parabola",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="produced_output_type_mismatch",
    ):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            question_goals=_nankai_inputs().question_goals,
            handle_registry=_registry(),
        )


def test_step_intent_validator_rejects_public_derivation_scope() -> None:
    """传入 question_goals 后，公共推导 scope 不能输出 steps。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"].insert(
        1,
        {
            "scope_id": "ii",
            "label": "第（Ⅱ）问公共推导",
            "steps": [
                {
                    "step_id": "derive_public_fact",
                    "goal_type": "derive_parameter",
                    "target": "fact:ii:shared_result",
                    "strategy": "公共推导。",
                    "reads": ["fact:problem:coefficient_relation"],
                    "creates": [],
                    "produces": [_produce("fact:ii:shared_result", "ii")],
                    "reason": "父级公共推导不应单独输出。",
                }
            ],
        },
    )

    with pytest.raises(StrategyDraftValidationError, match="public_derivation_scope_not_allowed"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            question_goals=inputs.question_goals,
            handle_registry=_registry(),
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"steps": []}, "top-level response contains unsupported fields"),
        ({"scopes": []}, "scopes must be a non-empty list"),
        (
            {
                "scopes": [
                    {
                        "scope_id": "i",
                        "label": "第（Ⅰ）问",
                        "steps": [
                            {
                                "step_id": "derive_axis_point",
                                "goal_type": "derive_point",
                                "target": "answer:i.axis_point",
                                "strategy": "求点",
                                "reads": [],
                                "creates": [],
                                "produces": [_produce("answer:i.axis_point", "i")],
                                "reason": "原因",
                            },
                            {
                                "step_id": "derive_axis_point",
                                "goal_type": "derive_point",
                                "target": "answer:i.parabola",
                                "strategy": "求式",
                                "reads": [],
                                "creates": [],
                                "produces": [_produce("answer:i.parabola", "i")],
                                "reason": "原因",
                            },
                        ],
                    },
                ]
            },
            "duplicate step_id",
        ),
        (
            {
                "scopes": [
                    {
                        "scope_id": "i",
                        "label": "第（Ⅰ）问",
                        "steps": [
                            {
                                "step_id": "step_1",
                                "goal_type": "derive_point",
                                "target": "answer:i.axis_point",
                                "strategy": "求点",
                                "reads": [],
                                "creates": [],
                                "produces": [_produce("answer:i.axis_point", "i")],
                                "reason": "原因",
                            }
                        ],
                    }
                ]
            },
            "must not be numbered",
        ),
        (
            {
                "scopes": [
                    {
                        "scope_id": "i",
                        "label": "第（Ⅰ）问",
                        "steps": [
                            {
                                "step_id": "derive_axis_point",
                                "goal_type": "derive_point",
                                "target": "$problem.points.D",
                                "strategy": "求点",
                                "reads": [],
                                "creates": [],
                                "produces": [_produce("answer:i.axis_point", "i")],
                                "reason": "原因",
                            }
                        ],
                    }
                ]
            },
            "forbidden token",
        ),
        (
            {
                "scopes": [
                    {
                        "scope_id": "i",
                        "label": "第（Ⅰ）问",
                        "steps": [
                            {
                                "step_id": "derive_axis_point",
                                "goal_type": "derive_point",
                                "target": "answer:i.axis_point",
                                "strategy": "求点",
                                "reads": [],
                                "creates": [],
                                "produces": [_produce("answer:i.axis_point", "i")],
                                "reason": "原因",
                                "coordinates": [1, 0],
                            }
                        ],
                    }
                ]
            },
            "forbidden field",
        ),
        (
            {
                "scopes": [
                    {
                        "scope_id": "i",
                        "label": "第（Ⅰ）问",
                        "steps": [
                            {
                                "step_id": "derive_axis_point",
                                "goal_type": "derive_point",
                                "target": "answer:i.axis_point",
                                "strategy": "求点",
                                "knowns": [],
                                "publish": [_produce("answer:i.axis_point", "i")],
                                "reason": "原因",
                            }
                        ],
                    }
                ]
            },
            "forbidden field",
        ),
    ],
)
def test_step_intent_validator_rejects_invalid_drafts(
    payload: dict[str, object],
    message: str,
) -> None:
    """非法 JSON shape、编号 step、裸路径、坐标和旧字段都应失败。"""
    with pytest.raises(StrategyDraftValidationError, match=message):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


@pytest.mark.parametrize(
    "handle",
    [
        "relation:right_angle_equal_length",
        "constraint:quadrant_fourth",
        "condition:MN_length",
        "point:D",
    ],
)
def test_step_intent_validator_rejects_noncanonical_read_handles(handle: str) -> None:
    """reads 中不能出现 LLM 自造的 relation/condition/point 短 handle。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["reads"] = [handle]

    with pytest.raises(StrategyDraftValidationError, match="noncanonical_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_step_intent_validator_explains_malformed_fact_handle() -> None:
    """fact:scope_name 少一个冒号时，应提示 fact handle 的规范格式。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["reads"] = ["fact:ii_MN_length_squared_eq_10"]

    with pytest.raises(StrategyDraftValidationError) as exc_info:
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )

    message = str(exc_info.value)
    assert "fact handles require fact:<scope>:<semantic_name>" in message
    assert "entity handles require" not in message


def test_step_intent_validator_rejects_future_step_or_undeclared_reads() -> None:
    """reads 只能引用题设已有 handle 或前序 step 已产生的 handle。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["reads"] = ["fact:ii:future_coordinate"]

    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )

    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["reads"] = ["point:ii:D_prime"]
    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_handle_resolver_corrects_current_scope_read_to_visible_parent_fact() -> None:
    """LLM 把父级 fact 误写成当前小问 scope 时，应自动修正并记录报告。"""
    payload = _valid_step_intent_payload()
    reads = payload["scopes"][1]["steps"][1]["reads"]
    reads[reads.index("fact:ii:path_minimum_target")] = "fact:ii_1:path_minimum_target"

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft is not None
    corrected_step = draft.scopes[1].steps[1]
    assert "fact:ii:path_minimum_target" in corrected_step.reads
    assert "fact:ii_1:path_minimum_target" not in corrected_step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "fact:ii_1:path_minimum_target"
    assert corrections[0].to_handle == "fact:ii:path_minimum_target"


def test_handle_resolver_corrects_intermediate_scope_read_to_visible_parent_entity() -> None:
    """LLM 把 problem 点 D 写成 ii scope 时，应修正到可见父级实体。"""
    payload = _valid_step_intent_payload()
    reads = payload["scopes"][1]["steps"][0]["reads"]
    reads[reads.index("point:problem:D")] = "point:ii:D"

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    assert draft is not None
    corrected_step = draft.scopes[1].steps[0]
    assert "point:problem:D" in corrected_step.reads
    assert "point:ii:D" not in corrected_step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "point:ii:D"
    assert corrections[0].to_handle == "point:problem:D"


def test_handle_resolver_corrects_state_point_alias_to_existing_point() -> None:
    """point:ii:OptimalG 这类状态化点名应修正为已有 point:ii:G。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "derive_optimal_G",
                        "recipe_hint": "line_locus_minimum_point",
                        "goal_type": "derive_line_locus_minimum_point",
                        "target": "fact:ii:optimal_G",
                        "strategy": "求最短状态下的 G 点。",
                        "reads": [
                            "point:ii:OptimalG",
                            "fact:ii:path_minimum_target",
                        ],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:ii:optimal_G",
                                "valid_scope": "ii",
                                "description": "最短状态下 G 的坐标",
                                "output_type": "Point",
                            }
                        ],
                        "reason": "OptimalG 是 G 的状态，不是新实体。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem()),
    )

    assert draft is not None
    corrected_step = draft.scopes[0].steps[0]
    assert "point:ii:G" in corrected_step.reads
    assert "point:ii:OptimalG" not in corrected_step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "point:ii:OptimalG"
    assert corrections[0].to_handle == "point:ii:G"
    assert corrections[0].reason.startswith("state_point_alias")


def test_point_output_handle_parses_extremal_state_fact_name() -> None:
    """optimal_G_expr 这类状态坐标 fact 应反推出真实点 G。"""
    problem = _heping_ermo_problem()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    step = _step(
        scope_id="ii",
        step_id="derive_optimal_G_expr",
        recipe_hint="line_locus_minimum_point",
        goal_type="derive_line_locus_minimum_point",
        target="fact:ii:optimal_G_expr",
        reads=(
            "fact:ii:G_locus_line",
            "fact:ii:path_minimum_point_1",
            "fact:ii:path_minimum_point_2",
        ),
        produces=(
            ProducedFact(
                "fact:ii:optimal_G_expr",
                "ii",
                "最短路径状态下 G 的坐标表达式",
                output_type="Point",
            ),
        ),
    )

    assert _point_output_handle(step, index) == "point:ii:G"


def test_handle_resolver_corrects_fact_namespace_to_visible_point_entity() -> None:
    """LLM 把点 O 误写成 fact handle 时，应修正为已有 point entity。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "第（Ⅰ）②问",
                "steps": [
                    {
                        "step_id": "read_origin_point",
                        "recipe_hint": "angle_sum_equal_angle_candidates",
                        "goal_type": "derive_equal_angle",
                        "target": "fact:i_2:angle_equality",
                        "strategy": "读取坐标原点 O。",
                        "reads": ["fact:problem:O"],
                        "creates": [],
                        "produces": [_produce("fact:i_2:angle_equality", "i_2", output_type="AngleEquality")],
                        "reason": "O 是题设已有点。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert "point:problem:O" in step.reads
    assert "fact:problem:O" not in step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "fact:problem:O"
    assert corrections[0].to_handle == "point:problem:O"


def test_handle_resolver_corrects_plural_facts_namespace() -> None:
    """LLM 偶发写出 facts:scope:name 时，只在 fact handle 已存在时修正。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_N_via_equal_length",
                        "recipe_hint": "equal_length_ray_point",
                        "goal_type": "derive_equal_length_constructed_point",
                        "target": "fact:ii:N_coordinate_expr",
                        "strategy": "由 CN=CM 和 M 在线段 BC 上构造 N。",
                        "reads": [
                            "facts:ii:M_on_segment_BC",
                            "fact:ii:CN_eq_CM",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:N_coordinate_expr",
                                "ii",
                                "N 坐标表达式",
                                output_type="Point",
                            )
                        ],
                        "reason": "facts: 是 LLM 的拼写错误。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert "fact:ii:M_on_segment_BC" in step.reads
    assert "facts:ii:M_on_segment_BC" not in step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "facts:ii:M_on_segment_BC"
    assert corrections[0].to_handle == "fact:ii:M_on_segment_BC"


def test_handle_resolver_corrects_segment_namespace_alias() -> None:
    """LLM 把 segment 缩写成 seg 时，应修正为 canonical entity handle。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_equal_length_ray_point",
                        "recipe_hint": "equal_length_ray_point",
                        "goal_type": "derive_equal_length_constructed_point",
                        "target": "fact:ii:path_minimum_expression",
                        "strategy": "由等长射线构造辅助点，再转化为单距离最值。",
                        "reads": [
                            "seg:ii:BC",
                            "fact:ii:M_on_segment_BC",
                            "fact:ii:N_on_ray_CD",
                            "fact:ii:CN_eq_CM",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:path_minimum_expression",
                                "ii",
                                "路径最小值表达式",
                                output_type="MinimumExpression",
                            )
                        ],
                        "reason": "seg 是 LLM 对 segment namespace 的缩写。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert "segment:ii:BC" in step.reads
    assert "seg:ii:BC" not in step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "seg:ii:BC"
    assert corrections[0].to_handle == "segment:ii:BC"


def test_handle_resolver_corrects_registered_handle_alias() -> None:
    """显式注册的 handle alias 可以被修正为 canonical fact。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "use_minimum_expression_alias",
                        "recipe_hint": "parameter_from_expression_value",
                        "goal_type": "derive_parameter_value",
                        "target": "answer:ii_a",
                        "strategy": "读取路径最小值表达式的缩写 alias。",
                        "reads": ["fact:ii:min_expr"],
                        "creates": [],
                        "produces": [_produce("answer:ii_a", "ii", output_type="ParameterValue")],
                        "reason": "min_expr 是系统登记的缩写。",
                    }
                ],
            }
        ]
    }
    problem_payload = _heping_llm_problem()
    for fact in problem_payload["facts"]:
        if fact["handle"] == "fact:ii:path_minimum_target":
            fact["aliases"] = ["fact:ii:min_expr"]
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert "fact:ii:path_minimum_target" in step.reads
    assert "fact:ii:min_expr" not in step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].reason.startswith("registered_alias")


def test_handle_resolver_does_not_guess_conflicting_registered_alias() -> None:
    """冲突 alias 等价于未注册，不能猜测。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "use_conflicting_alias",
                        "recipe_hint": "parameter_from_expression_value",
                        "goal_type": "derive_parameter_value",
                        "target": "answer:ii_a",
                        "strategy": "读取存在冲突的 alias。",
                        "reads": ["fact:ii:min_expr"],
                        "creates": [],
                        "produces": [_produce("answer:ii_a", "ii", output_type="ParameterValue")],
                        "reason": "冲突 alias 不能自动修。",
                    }
                ],
            }
        ]
    }
    problem_payload = _heping_llm_problem()
    for fact in problem_payload["facts"]:
        if fact["handle"] in {"fact:ii:path_minimum_target", "fact:ii:M_on_segment_BC"}:
            fact["aliases"] = ["fact:ii:min_expr"]
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    assert "fact:ii:min_expr" not in registry.handle_aliases

    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=registry,
        )


def test_handle_resolver_does_not_fuzzy_correct_typos() -> None:
    """开放式拼写错误不做 fuzzy correction，只进入 repair。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "use_typo_handle",
                        "recipe_hint": "parameter_from_expression_value",
                        "goal_type": "derive_parameter_value",
                        "target": "answer:ii_a",
                        "strategy": "读取拼错的最小值表达式 fact。",
                        "reads": ["fact:ii:minmum_expr"],
                        "creates": [],
                        "produces": [_produce("answer:ii_a", "ii", output_type="ParameterValue")],
                        "reason": "minmum 是拼写错误，不是系统 alias。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        )


def test_handle_resolver_moves_existing_created_entity_to_reads() -> None:
    """题设已有实体误放进 creates 时，应移动到 reads 而不是覆盖题设。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_N_via_equal_length",
                        "recipe_hint": "equal_length_ray_point",
                        "goal_type": "derive_equal_length_constructed_point",
                        "target": "point:ii:N",
                        "strategy": "误把题设动点 N 当作新建点。",
                        "reads": ["fact:ii:CN_eq_CM"],
                        "creates": [_create("point:ii:N", "point", "ii")],
                        "produces": [_produce("fact:ii:N_coordinate_expr", "ii", output_type="Point")],
                        "reason": "N 是题设已有动点，不能覆盖。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert step.creates == ()
    assert "point:ii:N" in step.reads
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 1
    assert corrections[0].from_handle == "creates:point:ii:N"
    assert corrections[0].to_handle == "point:ii:N"


def test_handle_resolver_moves_duplicate_auxiliary_creates_to_reads() -> None:
    """前序 step 已 creates 的辅助点，后续重复 creates 应转成 reads。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "第（Ⅰ）②问",
                "steps": [
                    {
                        "step_id": "derive_axis_intercept_point_F",
                        "recipe_hint": "axis_intercept_from_equal_acute_angles",
                        "goal_type": "derive_angle_constructed_point",
                        "target": "point:i_2:F",
                        "strategy": "先构造辅助点 F。",
                        "reads": [],
                        "creates": [_create("point:i_2:F", "point", "i_2")],
                        "produces": [_produce("fact:i_2:F_coordinate", "i_2", output_type="Point")],
                        "reason": "F 是本问推导产生的辅助点。",
                    },
                    {
                        "step_id": "derive_E_coordinate",
                        "recipe_hint": "line_parabola_second_intersection_point",
                        "goal_type": "derive_curve_intersection_point",
                        "target": "fact:i_2:E_coordinate",
                        "strategy": "后续误把同一个 F 再次放进 creates。",
                        "reads": [
                            "function:problem:parabola",
                            "point:problem:B",
                            "point:i_2:E",
                        ],
                            "creates": [_create("point:i_2:F", "point", "i_2")],
                        "produces": [_produce("fact:i_2:E_coordinate", "i_2", output_type="Point")],
                        "reason": "重复声明应视为读取前序辅助点。",
                    },
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=[],
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        family_spec=QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    )

    assert draft is not None
    second = draft.scopes[0].steps[1]
    assert second.creates == ()
    assert "point:i_2:F" in second.reads
    assert report.handle_resolution is not None
    correction = report.handle_resolution.corrections[-1]
    assert correction.from_handle == "creates:point:i_2:F"
    assert correction.to_handle == "point:i_2:F"
    assert "duplicate_created_entity_already_available" in correction.reason


def test_handle_resolver_corrects_answer_scope_dot_alias() -> None:
    """answer:scope.key 别名应从 question_goals 修正为 canonical handle。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "第（Ⅰ）①问",
                "steps": [
                    {
                        "step_id": "derive_parabola_i_1",
                        "recipe_hint": "quadratic_from_constraints",
                        "goal_type": "derive_parabola",
                        "target": "answer:i_1.parabola",
                        "strategy": "求第（Ⅰ）①问抛物线。",
                        "reads": ["fact:i:D_on_parabola"],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "answer:i_1.parabola",
                                "valid_scope": "i",
                                "description": "第（Ⅰ）①问抛物线",
                                "output_type": "Parabola",
                            }
                        ],
                        "reason": "answer handle 使用了 scope.key 别名。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert step.target == "answer:i_1_parabola"
    assert step.produces[0].handle == "answer:i_1_parabola"
    assert report.handle_resolution is not None
    corrections = report.handle_resolution.corrections
    assert len(corrections) == 2
    assert {item.to_handle for item in corrections} == {"answer:i_1_parabola"}


def test_handle_resolver_narrows_overbroad_produced_fact_scope() -> None:
    """局部条件推导的 fact 不应因为点在 problem scope 就声明成 problem 公共结论。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_B_coordinate",
                        "recipe_hint": "quadratic_x_axis_intercept_point",
                        "goal_type": "derive_axis_intercept_point",
                        "target": "fact:problem:B_coordinate",
                        "strategy": "由第（Ⅰ）问抛物线求 B。",
                        "reads": ["fact:i:D_on_parabola", "point:problem:B"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:problem:B_coordinate",
                                "problem",
                                "第（Ⅰ）问得到的 B 坐标",
                                output_type="Point",
                            )
                        ],
                        "reason": "这个坐标依赖第（Ⅰ）问条件，不能全题公共。",
                    },
                    {
                        "step_id": "derive_B_with_parameter_a",
                        "recipe_hint": "quadratic_x_axis_intercept_point",
                        "goal_type": "derive_axis_intercept_point",
                        "target": "fact:ii:B_coordinate_expr",
                        "strategy": "第（Ⅱ）问中 B 坐标含参数 a。",
                        "reads": ["point:problem:B"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:B_coordinate_expr",
                                "ii",
                                "第（Ⅱ）问 B 坐标含 a 表达式",
                                output_type="Point",
                            )
                        ],
                        "reason": "第（Ⅱ）问的 B 与第（Ⅰ）问具体 B 坐标不同。",
                    },
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    first_step = draft.scopes[0].steps[0]
    assert first_step.target == "fact:i:B_coordinate"
    assert first_step.produces[0].handle == "fact:i:B_coordinate"
    assert first_step.produces[0].valid_scope == "i"
    assert report.handle_resolution is not None
    assert any(
        correction.from_handle == "fact:problem:B_coordinate"
        and correction.to_handle == "fact:i:B_coordinate"
        for correction in report.handle_resolution.corrections
    )


def test_handle_resolver_narrows_reusable_fact_even_when_step_produces_answer() -> None:
    """同一步产生 answer 和复用 fact 时，复用 fact 仍需按 reads 收窄。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "第（Ⅰ）①问",
                "steps": [
                    {
                        "step_id": "derive_parabola_expression",
                        "recipe_hint": "quadratic_from_constraints",
                        "goal_type": "derive_parabola",
                        "target": "answer:i_1_parabola",
                        "strategy": "由第（Ⅰ）问 D 在抛物线上求解析式。",
                        "reads": [
                            "fact:problem:A_coordinate_value",
                            "fact:problem:A_on_parabola",
                            "fact:i:D_on_parabola",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "answer:i_1_parabola",
                                "i_1",
                                "第（Ⅰ）①问抛物线答案",
                                output_type="Parabola",
                            ),
                            _produce(
                                "fact:problem:parabola_expr",
                                "problem",
                                "第（Ⅰ）问抛物线解析式，供第（Ⅰ）②问复用",
                                output_type="Parabola",
                            ),
                        ],
                        "reason": "fact 依赖第（Ⅰ）问条件，不能全题公共。",
                    },
                    {
                        "step_id": "derive_B_coordinate_i",
                        "recipe_hint": "quadratic_x_axis_intercept_point",
                        "goal_type": "derive_axis_intercept_point",
                        "target": "fact:i:B_coordinate",
                        "strategy": "复用第（Ⅰ）问解析式求 B。",
                        "reads": ["fact:problem:parabola_expr", "point:problem:A"],
                        "creates": [],
                        "produces": [
                            _produce("fact:i:B_coordinate", "i", output_type="Point")
                        ],
                        "reason": "reads 应被同步改写。",
                    },
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    first_step, second_step = draft.scopes[0].steps
    assert first_step.produces[1].handle == "fact:i:parabola_expr"
    assert first_step.produces[1].valid_scope == "i"
    assert "fact:i:parabola_expr" in second_step.reads
    assert "fact:problem:parabola_expr" not in second_step.reads
    assert report.handle_resolution is not None
    assert any(
        correction.from_handle == "fact:problem:parabola_expr"
        and correction.to_handle == "fact:i:parabola_expr"
        for correction in report.handle_resolution.corrections
    )


def test_handle_resolver_narrows_parent_fact_when_reads_child_scope_fact() -> None:
    """读取子问 fact 后产生父级 fact 时，应收窄到子问 scope。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "第（Ⅰ）②问",
                "steps": [
                    {
                        "step_id": "use_angle_sum_to_get_equality",
                        "recipe_hint": "angle_sum_equal_angle_candidates",
                        "goal_type": "derive_equal_angle_from_angle_sum",
                        "target": "fact:i:EBO_eq_ACO",
                        "strategy": "由第（Ⅰ）②问角和条件推出等角。",
                        "reads": [
                            "fact:i_2:angle_sum_CBE_ACO_45",
                            "point:problem:B",
                            "point:problem:A",
                            "point:problem:C",
                            "point:problem:O",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i:EBO_eq_ACO",
                                "i",
                                "等角关系只在第（Ⅰ）②问成立",
                                output_type="AngleEquality",
                            )
                        ],
                        "reason": "valid_scope 写成 i 过大。",
                    }
                ],
            }
        ]
    }

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
    )

    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert step.target == "fact:i_2:EBO_eq_ACO"
    assert step.produces[0].handle == "fact:i_2:EBO_eq_ACO"
    assert step.produces[0].valid_scope == "i_2"
    assert report.handle_resolution is not None
    assert any(
        correction.from_handle == "fact:i:EBO_eq_ACO"
        and correction.to_handle == "fact:i_2:EBO_eq_ACO"
        for correction in report.handle_resolution.corrections
    )


def test_handle_resolver_does_not_guess_unknown_fact_as_point() -> None:
    """不存在同名 point entity 时，fact handle 仍应按未知 reads 失败。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "第（Ⅰ）②问",
                "steps": [
                    {
                        "step_id": "read_unknown_point",
                        "recipe_hint": "angle_sum_equal_angle_candidates",
                        "goal_type": "derive_equal_angle",
                        "target": "fact:i_2:angle_equality",
                        "strategy": "读取不存在的点。",
                        "reads": ["fact:problem:Z"],
                        "creates": [],
                        "produces": [_produce("fact:i_2:angle_equality", "i_2", output_type="AngleEquality")],
                        "reason": "不能猜测不存在的点。",
                    }
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        )


def test_normalizer_infers_angle_sum_target_from_axis_intercept_step() -> None:
    """角和 step 产出等角 fact 时，可从后续轴截点 step 反推目标 PointRef。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    angle_step = StepIntent(
        scope_id="i_2",
        step_id="compute_angle_equality",
        recipe_hint="angle_sum_equal_angle_candidates",
        goal_type="derive_equal_angle_from_angle_sum",
        target="fact:i_2:angle_equality_CBE_eq_angle",
        strategy="由角和推出等角。",
        reads=("fact:i_2:angle_sum_CBE_ACO_45",),
        creates=(),
        produces=(
            ProducedFact(
                "fact:i_2:angle_equality_CBE_eq_angle",
                "i_2",
                "由角和推出等角",
                output_type="AngleEquality",
            ),
        ),
        reason="先找等角。",
    )
    axis_step = StepIntent(
        scope_id="i_2",
        step_id="derive_axis_intercept_G",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept_from_equal_acute_angles",
        target="fact:i_2:G_coordinate",
        strategy="由等角求轴截点。",
        reads=("fact:i_2:angle_equality_CBE_eq_angle",),
        creates=(),
        produces=(
            ProducedFact(
                "fact:i_2:G_coordinate",
                "i_2",
                "轴截点 G 坐标",
                output_type="Point",
            ),
        ),
        reason="再求截点。",
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="i_2",
                label="第（Ⅰ）②问",
                steps=(angle_step, axis_step),
            ),
        )
    )

    normalized, report = StepIntentNormalizer().normalize(
        draft,
        family_spec=build_strategy_probe_inputs(load_problem_ir(HEPING_FIXTURE)).family_spec,
        question_goals=extract_question_goals(load_problem_ir(HEPING_FIXTURE)),
        handle_registry=registry,
    )

    normalized_angle = normalized.scopes[0].steps[0]
    normalized_axis = normalized.scopes[0].steps[1]
    assert normalized_angle.target == "point:i_2:G"
    assert normalized_angle.creates == (
        CreatedEntity(
            "point:i_2:G",
            "point",
            "i_2",
            "由角和等角链路确定的轴截点目标",
        ),
    )
    assert normalized_angle.produces[0].handle == "fact:i_2:angle_OBG_eq_ACO"
    assert "fact:i_2:angle_OBG_eq_ACO" in normalized_axis.reads
    assert "fact:i_2:angle_equality_CBE_eq_angle" not in normalized_axis.reads
    assert "point:i_2:G" in normalized_axis.reads
    assert report.actions
    assert report.actions[0].action == "infer_angle_sum_target_from_axis_intercept_step"
    assert report.actions[1].action == "normalize_angle_equality_fact_handle"


def test_normalizer_drops_unreferenced_path_transformation_explanation_step() -> None:
    """未被后续读取的 PathTransformation 解释 step 不应阻断 executable plan。"""
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    transform_step = StepIntent(
        scope_id="ii",
        step_id="transform_path_to_PB",
        recipe_hint=None,
        goal_type="reduce_path_expression",
        target="OM+BN 转化为 PB",
        strategy="由全等得 OM=PN，因此 OM+BN=PN+BN，最小值转成 PB。",
        reads=("fact:ii:CN_eq_CM", "point:ii:P", "point:problem:B"),
        creates=(),
        produces=(
            ProducedFact(
                handle="fact:ii:path_equivalence",
                valid_scope="ii",
                description="OM+BN 的最小值等于 PB",
                output_type="PathTransformation",
            ),
        ),
        reason="这是讲解性路径转化说明。",
    )
    distance_step = StepIntent(
        scope_id="ii",
        step_id="compute_PB_distance",
        recipe_hint="distance_between_points",
        goal_type="derive_minimum_value",
        target="fact:ii:path_minimum_expression",
        strategy="计算 P、B 两点距离。",
        reads=("point:ii:P", "point:problem:B", "fact:ii:P_coordinate_expr", "fact:ii:B_coordinate_expr"),
        creates=(),
        produces=(
            ProducedFact(
                handle="fact:ii:path_minimum_expression",
                valid_scope="ii",
                description="OM+BN 的最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
        reason="真正执行的是两点距离。",
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii",
                label="第（Ⅱ）问",
                steps=(transform_step, distance_step),
            ),
        )
    )

    normalized, report = StepIntentNormalizer().normalize(
        draft,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    assert [step.step_id for step in normalized.scopes[0].steps] == ["compute_PB_distance"]
    assert any(
        action.action == "drop_unreferenced_path_transformation_step"
        for action in report.actions
    )


def test_handle_resolver_does_not_correct_sibling_scope_reads() -> None:
    """sibling scope 的 handle 不是可见父级结论，不能自动猜测修正。"""
    payload = _valid_step_intent_payload()
    payload["scopes"][2]["steps"][0]["reads"].append(
        "fact:ii_2:MN_length_squared_eq_10"
    )

    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )

    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][0]["reads"].append("point:ii_2:D")
    with pytest.raises(StrategyDraftValidationError, match="unknown_read_handle"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_step_intent_validator_accepts_previous_created_entity_reads() -> None:
    """前序 creates 的 derived Entity 可以被后续 step 直接 reads。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问公共步骤",
                "steps": [
                    {
                        "step_id": "create_auxiliary_point",
                        "goal_type": "construct_auxiliary",
                        "target": "point:ii:D_prime",
                        "strategy": "构造折线拉直辅助点。",
                        "reads": ["point:problem:D", "fact:ii:path_minimum_target"],
                        "creates": [_create("point:ii:D_prime", "point", "ii")],
                        "produces": [],
                        "reason": "路径转化需要辅助点。",
                    },
                    {
                        "step_id": "use_auxiliary_point",
                        "goal_type": "derive_minimum",
                        "target": "fact:ii:path_minimum_expr",
                        "strategy": "使用辅助点求路径最小值表达式。",
                        "reads": ["point:ii:D_prime"],
                        "creates": [],
                        "produces": [_produce("fact:ii:path_minimum_expr", "ii")],
                        "reason": "辅助点已经在前一步创建。",
                    },
                ],
            }
        ]
    }

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )
    assert len(draft.steps) == 2


def test_step_intent_validator_rejects_duplicate_point_coordinate_signature() -> None:
    """同一点坐标已有父级通用 fact 时，子问不应再重复产生数值/表达式 fact。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_f_coordinate_expr",
                        "goal_type": "derive_point_coordinate",
                        "target": "fact:ii:F_coordinate_expr",
                        "strategy": "由 D、N 求 F 的通用坐标。",
                        "reads": [
                            "point:problem:D",
                            "point:ii:N",
                            "fact:ii:F_midpoint_of_DN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii:F_coordinate_expr", "ii", "F 坐标通用表达式")
                        ],
                        "reason": "F 后续两个小问都可使用。",
                    },
                    {
                        "step_id": "derive_f_coordinate_numeric",
                        "goal_type": "derive_point_coordinate",
                        "target": "fact:ii_1:F_coordinate_numeric",
                        "strategy": "重复求 F 的数值坐标。",
                        "reads": [
                            "fact:ii:F_coordinate_expr",
                            "fact:ii_1:MN_length_squared_eq_10",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii_1:F_coordinate_numeric", "ii_1", "F 坐标数值")
                        ],
                        "reason": "这一步应被要求改成 reads 通用 F 坐标。",
                    },
                ],
            }
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="duplicate_point_coordinate_fact"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_step_intent_validator_rejects_common_fact_after_narrow_fact() -> None:
    """先产生子问窄 fact，再回头产生父级公共 fact，应提前失败并要求调整顺序。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_f_coordinate_numeric",
                        "goal_type": "derive_point_coordinate",
                        "target": "fact:ii_1:F_coordinate_numeric",
                        "strategy": "先在 ① 中求 F 的数值坐标。",
                        "reads": [
                            "point:problem:D",
                            "point:ii:N",
                            "fact:ii:F_midpoint_of_DN",
                            "fact:ii_1:MN_length_squared_eq_10",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii_1:F_coordinate_numeric", "ii_1", "F 坐标数值")
                        ],
                        "reason": "这是窄 scope 结论。",
                    }
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_f_coordinate_expr",
                        "goal_type": "derive_point_coordinate",
                        "target": "fact:ii:F_coordinate_expr",
                        "strategy": "后面又求 F 的父级通用坐标。",
                        "reads": [
                            "point:problem:D",
                            "point:ii:N",
                            "fact:ii:F_midpoint_of_DN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii:F_coordinate_expr", "ii", "F 坐标通用表达式")
                        ],
                        "reason": "这类公共 fact 应先产生。",
                    }
                ],
            },
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="common_fact_after_narrow_fact"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_step_intent_validator_allows_same_point_coordinate_with_different_curve_context() -> None:
    """同一点坐标若依赖不同曲线状态，不应被当成同一结论重复推导。"""
    payload = {
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "第（Ⅰ）①问",
                "steps": [
                    {
                        "step_id": "derive_B_coordinate_i",
                        "recipe_hint": "quadratic_x_axis_intercept_point",
                        "goal_type": "derive_axis_intercept_point",
                        "target": "fact:i:B_coordinate",
                        "strategy": "由第（Ⅰ）问已解抛物线求 B。",
                        "reads": ["answer:i_1_parabola", "point:problem:B"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i:B_coordinate",
                                "i",
                                "第（Ⅰ）问 B 坐标",
                                output_type="Point",
                            )
                        ],
                        "reason": "B 依赖第（Ⅰ）问完整抛物线。",
                    },
                    {
                        "step_id": "derive_B_coordinate_expr_ii",
                        "recipe_hint": "quadratic_x_axis_intercept_point",
                        "goal_type": "derive_axis_intercept_point",
                        "target": "fact:ii:B_coordinate_expr",
                        "strategy": "由第（Ⅱ）问含参抛物线求 B 坐标表达式。",
                        "reads": ["function:problem:parabola", "point:problem:B"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:B_coordinate_expr",
                                "ii",
                                "第（Ⅱ）问 B 坐标表达式",
                                output_type="Point",
                            )
                        ],
                        "reason": "B 依赖第（Ⅱ）问含参抛物线，不是第（Ⅰ）问 B 坐标重复。",
                    },
                ],
            }
        ]
    }
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())

    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    assert [step.step_id for step in draft.steps] == [
        "derive_B_coordinate_i",
        "derive_B_coordinate_expr_ii",
    ]


def test_step_intent_validator_rejects_sibling_point_coordinate_facts() -> None:
    """同一父级点实体不能在兄弟小问分别求坐标。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_f_coordinate_ii1",
                        "goal_type": "derive_midpoint_coordinate",
                        "target": "fact:ii_1:F_coordinate",
                        "strategy": "先在 ① 中求 F 的数值坐标。",
                        "reads": [
                            "point:problem:D",
                            "point:ii:N",
                            "fact:ii:F_midpoint_of_DN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii_1:F_coordinate", "ii_1", "F 坐标数值")
                        ],
                        "reason": "这会锁定父级点 F 的 runtime 坐标。",
                    }
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_f_coordinate_ii2",
                        "goal_type": "derive_midpoint_coordinate",
                        "target": "fact:ii_2:F_coordinate_expr",
                        "strategy": "又在 ② 中求 F 的含参坐标。",
                        "reads": [
                            "point:problem:D",
                            "point:ii:N",
                            "fact:ii:F_midpoint_of_DN",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii_2:F_coordinate_expr", "ii_2", "F 坐标表达式")
                        ],
                        "reason": "应先产生父级 F 坐标表达式，然后兄弟小问复用。",
                    }
                ],
            },
        ]
    }

    with pytest.raises(StrategyDraftValidationError, match="duplicate_point_coordinate_fact"):
        StepIntentValidator().validate_json(
            json.dumps(payload, ensure_ascii=False),
            handle_registry=_registry(),
        )


def test_candidate_resolver_ignores_unused_child_read_for_valid_scope() -> None:
    """无害多读会先把过宽 fact 收窄，再进入候选解析。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_axis_point_with_extra_a",
                        "recipe_hint": None,
                        "goal_type": "derive_axis_point",
                        "target": "answer:i.axis_point",
                        "strategy": "多读了 a=2，但求 D 只需要系数关系。",
                        "reads": [
                            "fact:i:a_value",
                            "fact:problem:coefficient_relation",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:problem:D_coordinate", "problem"),
                            _produce("answer:i.axis_point", "i"),
                        ],
                        "reason": "a_value 是无害多读。",
                    }
                ],
            }
        ]
    }
    draft, validation_report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )
    assert draft is not None
    assert draft.scopes[0].steps[0].produces[0].handle == "fact:i:D_coordinate"
    assert draft.scopes[0].steps[0].produces[0].valid_scope == "i"
    assert validation_report.handle_resolution is not None
    assert any(
        correction.from_handle == "fact:problem:D_coordinate"
        and correction.to_handle == "fact:i:D_coordinate"
        for correction in validation_report.handle_resolution.corrections
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id == "quadratic_axis_from_relation"


def test_handle_resolver_narrows_used_child_read_for_parent_valid_scope() -> None:
    """实际读取子问 fact 时，父级参数 fact 会被收窄到子问 scope。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_parent_m_from_child_length",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:m_value",
                        "strategy": "错误地把 ① 的长度条件推出父级 m 值。",
                        "reads": [
                            "point:ii:M",
                            "point:ii:N",
                            "fact:ii:M_coordinate_expr",
                            "fact:ii_1:MN_length_squared_eq_10",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii:m_value", "ii", "错误的父级有效范围")
                        ],
                        "reason": "MN 长度条件只属于 ①。",
                    }
                ],
            }
        ]
    }
    draft, validation_report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )
    assert draft is not None
    step = draft.scopes[0].steps[0]
    assert step.target == "fact:ii_1:m_value"
    assert step.produces[0].handle == "fact:ii_1:m_value"
    assert step.produces[0].valid_scope == "ii_1"
    assert validation_report.handle_resolution is not None
    assert any(
        correction.from_handle == "fact:ii:m_value"
        and correction.to_handle == "fact:ii_1:m_value"
        for correction in validation_report.handle_resolution.corrections
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id == "parameter_from_segment_length"


def test_runtime_binding_index_reports_computed_point_when_pointref_target_is_expected() -> None:
    """已计算 Point 再作为 PointRef target，应返回可修复的重复坐标错误。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    index.register("point:ii:F", "$question.ii.points.F", "Point", source="step:derive_f")

    with pytest.raises(StrategyDraftValidationError, match="duplicate_point_coordinate_fact"):
        index.path_for("point:ii:F", expected_type="PointRef")


def test_minimum_expression_binding_does_not_read_sibling_scope_output() -> None:
    """ii_2 反求参数不能误读 ii_1 的最终最小值输出。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    index.register(
        "answer:ii_1.minimum_value",
        "$subquestion.ii_1.outputs.min_value",
        "MinimumExpression",
        source="step:compute_minimum_value_ii_1",
    )
    step = _unsafe_step_from_payload(
        {
            "step_id": "solve_m_from_minimum",
            "recipe_hint": "parameter_from_minimum_value",
            "goal_type": "derive_parameter_from_minimum_value",
            "target": "fact:ii_2:m_value",
            "strategy": "由最小值条件反求参数。",
            "reads": [
                "fact:ii_2:path_minimum_value_given",
                "point:ii:Aux_for_straighten",
            ],
            "creates": [],
            "produces": [_produce("fact:ii_2:m_value", "ii_2")],
            "reason": "缺少公共最小值表达式 fact。",
        },
        scope_id="ii_2",
    )
    rules = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec)

    with pytest.raises(StrategyDraftValidationError, match="missing_required_runtime_fact: minimum_expression"):
        rules.bind("parameter_from_minimum_value", step, index)


def test_minimum_expression_binding_reads_visible_parent_output() -> None:
    """若已有父级公共 MinimumExpression fact，ii_2 可以读取它反求参数。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    index.register(
        "fact:ii:path_minimum_expression",
        "$question.ii.outputs.minimum_expression",
        "MinimumExpression",
        source="step:compute_common_minimum_expression",
    )
    step = _unsafe_step_from_payload(
        {
            "step_id": "solve_m_from_minimum",
            "recipe_hint": "parameter_from_minimum_value",
            "goal_type": "derive_parameter_from_minimum_value",
            "target": "fact:ii_2:m_value",
            "strategy": "由最小值条件反求参数。",
            "reads": [
                "fact:ii:path_minimum_expression",
                "fact:ii_2:path_minimum_value_given",
            ],
            "creates": [],
            "produces": [_produce("fact:ii_2:m_value", "ii_2")],
            "reason": "读取父级公共最小值表达式。",
        },
        scope_id="ii_2",
    )
    rules = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec)

    inputs = rules.bind("parameter_from_minimum_value", step, index)

    assert inputs["minimum_expression"] == "$question.ii.outputs.minimum_expression"
    assert inputs["condition"] == "$subquestion.ii_2.conditions.minimum_value"


def test_step_intent_validator_requires_required_question_goals() -> None:
    """缺少 required answer handle 时应失败，方便真实联调尽早暴露漏问。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"] = payload["scopes"][:1]

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
    )

    assert draft is None
    assert report.ok is False
    assert "answer:ii_1.parabola" in report.errors[0]


def test_recipe_alignment_report_classifies_recipe_method_null_and_unknown() -> None:
    """alignment report 应区分 recipe/method/null/unknown 四类 recipe_hint。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][0]["steps"][0]["recipe_hint"] = "not_a_known_recipe"
    payload["scopes"][0]["steps"][1]["recipe_hint"] = None

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    alignment = report.recipe_alignment
    assert "right_angle_equal_length_construct_and_select" in alignment.matched_recipes
    assert "parameter_from_minimum_value" in alignment.matched_methods
    assert "derive_part_i_parabola" in alignment.null_hint_steps
    assert "derive_axis_point:not_a_known_recipe" in alignment.unknown_hint_steps


def test_recipe_alignment_report_warns_on_parameterized_path_route() -> None:
    """路径最值若走参数化/求导主路线，应作为 recipe alignment warning 暴露。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][2]["steps"][0]["step_id"] = "parameterize_moving_points"
    payload["scopes"][2]["steps"][0]["goal_type"] = "derive_minimum_value"
    payload["scopes"][2]["steps"][0]["strategy"] = "把 E 和 G 参数化后建立函数并求导。"

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    hits = report.recipe_alignment.avoid_pattern_hits
    assert hits
    assert hits[0]["step_id"] == "parameterize_moving_points"


def test_recipe_alignment_blocks_symbolic_quadratic_before_parameter_value() -> None:
    """若同 scope 后续能求参数，公共含参系数缓存应作为 capability error。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][1]["step_id"] = "derive_parabola_coefficients_expr"
    payload["scopes"][1]["steps"][1]["recipe_hint"] = "quadratic_from_constraints"
    payload["scopes"][1]["steps"][1]["goal_type"] = "derive_parabola"
    payload["scopes"][1]["steps"][1]["produces"] = [
        _produce(
            "fact:ii:parabola_coefficients_expr",
            "ii_1",
            "抛物线系数 a,b,c 用 m 表示，后续①②问均可复用",
        )
    ]
    payload["scopes"][1]["steps"].append(
        {
            "step_id": "derive_m_from_length",
            "recipe_hint": "parameter_from_segment_length",
            "goal_type": "derive_parameter",
            "target": "fact:ii_1:m_value",
            "strategy": "由 MN 长度条件求出 m。",
            "reads": [
                "fact:ii_1:MN_length_squared_eq_10",
                "fact:ii:N_coordinate_expr",
                "point:ii:M",
            ],
            "creates": [],
            "produces": [
                _produce("fact:ii_1:m_value", "ii_1", "当前问可先确定的 m 值")
            ],
            "reason": "能先确定参数，应先求参数再代入。",
        }
    )

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    hits = report.recipe_alignment.avoid_pattern_hits
    assert hits
    assert hits[0]["pattern"] == "symbolic_quadratic_before_available_parameter_value"
    assert hits[0]["related_step_id"] == "derive_m_from_length"
    errors = report.recipe_alignment.capability_errors
    assert errors
    assert errors[0]["code"] == "utility_symbolic_coefficients_step_not_allowed"
    assert errors[0]["step_id"] == "derive_parabola_coefficients_expr"


def test_recipe_alignment_allows_symbolic_quadratic_simplification_without_parameter_step() -> None:
    """若当前还不能求参数，含参化简可以作为降低复杂度的 step 保留。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][1]["step_id"] = "simplify_quadratic_expression"
    payload["scopes"][1]["steps"][1]["recipe_hint"] = "quadratic_from_constraints"
    payload["scopes"][1]["steps"][1]["goal_type"] = "derive_parabola"
    payload["scopes"][1]["steps"][1]["produces"] = [
        _produce(
            "fact:ii:parabola_coefficients_expr",
            "ii_1",
            "参数暂不能定值时，先把抛物线系数用 m 表示以减少未知量",
        )
    ]

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert not report.recipe_alignment.avoid_pattern_hits


def test_recipe_alignment_reports_capability_boundary_errors() -> None:
    """method hint 命中后，produces 不能越过该 method 的能力边界。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][1]["recipe_hint"] = "parameter_from_segment_length"
    payload["scopes"][1]["steps"][1]["produces"].append(
        _produce("fact:ii_1:parabola_expr", "ii_1", "错误地顺手产出抛物线")
    )

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    errors = report.recipe_alignment.capability_errors
    assert errors
    assert errors[0]["step_id"] == "solve_part_ii_one"
    assert errors[0]["code"] == "method_mixes_non_parameter_outputs"


def test_recipe_alignment_allows_parameter_text_inside_path_recipe() -> None:
    """命中路径 recipe 时，说明文字里的“参数化”不应被误判为求导路线。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][1]["recipe_hint"] = "two_moving_points_path_reduction"
    payload["scopes"][1]["steps"][1]["goal_type"] = "reduce_path_expression"
    payload["scopes"][1]["steps"][1]["strategy"] = "用参数化坐标说明线段比例，再完成路径降维。"

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert not report.recipe_alignment.avoid_pattern_hits


def test_recipe_alignment_does_not_treat_minimum_value_as_m_value() -> None:
    """minimum_value handle 不能因为包含 m_value 子串被误判为参数输出。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][1]["recipe_hint"] = "path_minimum_by_straightened_distance"
    payload["scopes"][1]["steps"][1]["goal_type"] = "derive_minimum_value"
    payload["scopes"][1]["steps"][1]["produces"] = [
        _produce("answer:ii_1.minimum_value", "ii_1", "EG+FG 的最小值")
    ]

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    errors_for_step = [
        error for error in report.recipe_alignment.capability_errors
        if error["step_id"] == "solve_part_ii_one"
    ]
    assert not errors_for_step


def test_recipe_alignment_does_not_treat_minimum_value_expr_as_m_value() -> None:
    """minimum_value_expr 也不能因为包含 m_value 子串被误判为参数输出。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()
    payload["scopes"][1]["steps"][1]["recipe_hint"] = "path_minimum_by_straightened_distance"
    payload["scopes"][1]["steps"][1]["goal_type"] = "derive_minimum_value"
    payload["scopes"][1]["steps"][1]["produces"] = [
        _produce("fact:ii:minimum_value_expr", "ii_1", "EG+FG 的最小值表达式")
    ]

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    errors_for_step = [
        error for error in report.recipe_alignment.capability_errors
        if error["step_id"] == "solve_part_ii_one"
    ]
    assert not errors_for_step


def test_recipe_alignment_report_tracks_missing_preferred_recipes() -> None:
    """preferred recipe 缺失时不阻断校验，但应在报告中可见。"""
    inputs = _nankai_inputs()
    payload = _valid_step_intent_payload()

    draft, report = StepIntentValidator().validate_json_with_report(
        json.dumps(payload, ensure_ascii=False),
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
        family_spec=inputs.family_spec,
    )

    assert draft is not None
    assert report.recipe_alignment is not None
    assert "path_minimum_by_straightened_distance" in report.recipe_alignment.matched_recipes
    assert "two_moving_points_path_reduction" in (
        report.recipe_alignment.missing_preferred_recipe_ids
    )


def test_step_intent_candidate_resolver_finds_method_when_hint_is_null() -> None:
    """recipe_hint=null 时，resolver 应能按产物类型找到可尝试 method。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_part_i_parabola",
                        "recipe_hint": None,
                        "goal_type": "derive_parabola",
                        "target": "answer:i.parabola",
                        "strategy": "由已知系数和系数关系求抛物线解析式。",
                        "reads": [
                            "function:problem:parabola",
                            "fact:i:a_value",
                            "fact:i:c_value",
                            "fact:problem:coefficient_relation",
                        ],
                        "creates": [],
                        "produces": [_produce("answer:i.parabola", "i")],
                        "reason": "第（Ⅰ）问要求抛物线解析式。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id == "quadratic_from_constraints"
    assert "Parabola" in step_report.produced_types


def test_step_intent_candidate_resolver_rejects_free_intermediate_relation() -> None:
    """自由创造 relation_a_m 这类中间关系时，应暴露为不可执行候选错误。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_a_m_relation",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii:relation_a_m",
                        "strategy": "把 N 代入抛物线得到 a 与 m 的关系。",
                        "reads": [
                            "function:problem:parabola",
                            "fact:ii:N_on_parabola",
                            "fact:problem:coefficient_relation",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:relation_a_m",
                                "ii",
                                "由 N 在抛物线上导出的 a 与 m 的关系式",
                            )
                        ],
                        "reason": "这是 method 菜单外的自由中间代数关系。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is False
    assert "derive_a_m_relation:no_executable_candidate" in report.errors[0]
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id is None
    assert step_report.produced_types == ("Equation",)


def test_step_intent_candidate_resolver_rejects_utility_coefficient_value() -> None:
    """单独求 b_value 这类 utility 系数 fact 不应被误当成抛物线 step。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "第（Ⅰ）问",
                "steps": [
                    {
                        "step_id": "derive_b_value",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:i:b_value",
                        "strategy": "由 a=2 和 2a+b=0 得 b=-4。",
                        "reads": [
                            "fact:i:a_value",
                            "fact:problem:coefficient_relation",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i:b_value",
                                "i",
                                "第（Ⅰ）问抛物线的 b 值",
                            )
                        ],
                        "reason": "这是服务解析式的临时系数值。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is False
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id is None


def test_step_intent_candidate_resolver_rejects_method_output_boundary() -> None:
    """参数 method 不能承接直接产出抛物线答案的 step。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "solve_m_and_parabola",
                        "recipe_hint": "parameter_from_minimum_value",
                        "goal_type": "derive_parameter",
                        "target": "answer:ii_2.parabola",
                        "strategy": "错误地把反求参数和求抛物线合并。",
                        "reads": ["fact:ii_2:path_minimum_value_given"],
                        "creates": [],
                        "produces": [_produce("answer:ii_2.parabola", "ii_2")],
                        "reason": "这一步越过了 parameter method 的产物边界。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is False
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id is None
    hinted = next(
        candidate for candidate in step_report.candidates
        if candidate.capability_id == "parameter_from_minimum_value"
    )
    assert hinted.ok is False
    assert "output_type_not_supported" in hinted.errors[0]
    assert "solve_m_and_parabola:no_executable_candidate" in report.errors[0]


def test_weighted_auxiliary_locus_straightening_candidate_is_normalized_to_line() -> None:
    """weighted transform 中辅助轨迹被误标为 StraighteningCandidate 时应修成 Line。"""
    step = _step(
        scope_id="ii_2",
        step_id="transform_weighted_path",
        recipe_hint="weighted_axis_path_triangle_transform",
        goal_type="derive_weighted_path_minimum",
        target="fact:ii_2:path_transformation",
        produces=(
            ProducedFact(
                "fact:ii_2:path_transformation",
                "ii_2",
                "加权路径转化方案",
                output_type="PathTransformation",
            ),
            ProducedFact(
                "fact:ii_2:aux_locus",
                "ii_2",
                "辅助点 Aux 的运动轨迹（射线）",
                output_type="StraighteningCandidate",
            ),
        ),
    )

    normalized, normalization_report = StepIntentNormalizer().normalize(
        _single_scope_draft(step, scope_id="ii_2"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_hexi_llm_problem()),
    )

    produces = normalized.scopes[0].steps[0].produces
    assert [(item.handle, item.output_type) for item in produces] == [
        ("fact:ii_2:path_transformation", "PathTransformation"),
        ("fact:ii_2:aux_locus", "Line"),
    ]
    assert [action.action for action in normalization_report.actions] == [
        "normalize_weighted_auxiliary_locus_type"
    ]


def test_non_weighted_straightening_candidate_is_not_normalized_to_line() -> None:
    """普通折线拉直候选仍应保持 StraighteningCandidate 类型。"""
    step = _step(
        scope_id="ii",
        step_id="select_straightening",
        recipe_hint="broken_path_straightening_and_select",
        goal_type="straighten_broken_path",
        target="fact:ii:selected_straightening_candidate",
        produces=(
            ProducedFact(
                "fact:ii:selected_straightening_candidate",
                "ii",
                "折线拉直后的候选方案",
                output_type="StraighteningCandidate",
            ),
        ),
    )

    normalized, normalization_report = StepIntentNormalizer().normalize(
        _single_scope_draft(step, scope_id="ii"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].produces[0].output_type == "StraighteningCandidate"
    assert not any(
        action.action == "normalize_weighted_auxiliary_locus_type"
        for action in normalization_report.actions
    )


def test_weighted_auxiliary_locus_normalization_unblocks_candidate_resolution() -> None:
    """修正后的 weighted transform step 应能通过 candidate resolver 输出类型检查。"""
    inputs = build_strategy_probe_inputs(load_problem_ir(HEXI_FIXTURE))
    registry = CanonicalHandleRegistry.from_problem_payload(_hexi_llm_problem())
    step = _step(
        scope_id="iii",
        step_id="transform_weighted_path",
        recipe_hint="weighted_axis_path_triangle_transform",
        goal_type="derive_weighted_path_minimum",
        target="fact:iii:path_transformation",
        produces=(
            ProducedFact(
                "fact:iii:path_transformation",
                "iii",
                "加权路径转化方案",
                output_type="PathTransformation",
            ),
            ProducedFact(
                "fact:iii:aux_locus",
                "iii",
                "辅助点运动轨迹（射线）",
                output_type="StraighteningCandidate",
            ),
        ),
    )
    normalized, _normalization_report = StepIntentNormalizer().normalize(
        _single_scope_draft(step, scope_id="iii"),
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    resolution = StepIntentCandidateResolver().resolve(
        normalized,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    assert resolution.ok is True
    assert resolution.step_reports[0].selected_capability_id == "weighted_axis_path_triangle_transform"


def test_candidate_resolver_treats_m_value_from_minimum_as_parameter_value() -> None:
    """m_value handle 比 description 更可信，不能被“最小值”误判成最值表达式。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_m_from_minimum",
                        "recipe_hint": "parameter_from_minimum_value",
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:m_value",
                        "strategy": "由最小值条件反求参数。",
                        "reads": [
                            "fact:ii_2:path_minimum_value_given",
                            "fact:problem:m_gt_2",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii_2:m_value",
                                "ii_2",
                                "由最小值条件反求参数 m 的具体值",
                            )
                        ],
                        "reason": "令最小值表达式等于题设给定值，解出 m。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_minimum_value"


def test_candidate_resolver_uses_length_reads_for_null_hint_parameter_value() -> None:
    """recipe_hint=null 时，长度条件 reads 能确定参数求解 method。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "solve_m_from_mn_length",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_1:m_value",
                        "strategy": "由 MN 长度条件求参数 m。",
                        "reads": [
                            "point:ii:M",
                            "point:ii:N",
                            "fact:ii:M_coordinate_expr",
                            "fact:ii_1:MN_length_squared_eq_10",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii_1:m_value", "ii_1", "由 MN 长度求 m")
                        ],
                        "reason": "长度条件决定 m。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_segment_length"


def test_candidate_resolver_uses_minimum_reads_for_null_hint_parameter_value() -> None:
    """recipe_hint=null 时，公共最小值表达式 + 给定最小值能确定反求参数 method。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "derive_common_minimum_expression",
                        "recipe_hint": "path_minimum_by_straightened_distance",
                        "goal_type": "derive_minimum_value",
                        "target": "fact:ii:path_minimum_expression",
                        "strategy": "由拉直后距离得到含 m 的最小值表达式。",
                        "reads": ["fact:ii:path_minimum_target"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:path_minimum_expression",
                                "ii",
                                "公共最小值表达式",
                            )
                        ],
                        "reason": "后续 ①② 都可以读这个表达式。",
                    }
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "solve_m_from_given_minimum",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:m_value",
                        "strategy": "由公共最小值表达式和题设给定最小值求 m。",
                        "reads": [
                            "fact:ii:path_minimum_expression",
                            "fact:ii_2:path_minimum_value_given",
                        ],
                        "creates": [],
                        "produces": [
                            _produce("fact:ii_2:m_value", "ii_2", "由给定最小值求 m")
                        ],
                        "reason": "最小值条件决定 m。",
                    }
                ],
            },
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[1]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_minimum_value"


def test_candidate_resolver_treats_parameter_prefixed_value_as_parameter_value() -> None:
    """parameter_m_value / parameter_a_value 也应按参数 fact 识别。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_parameter_m_from_minimum",
                        "recipe_hint": "parameter_from_minimum_value",
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:parameter_m_value",
                        "strategy": "由最小值条件反求参数 m。",
                        "reads": [
                            "fact:ii_2:path_minimum_value_given",
                            "fact:problem:m_gt_2",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii_2:parameter_m_value",
                                "ii_2",
                                "由最小值条件反求参数 m 的具体值",
                            )
                        ],
                        "reason": "parameter_m_value 是参数值，不是最小值表达式。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_minimum_value"


def test_candidate_resolver_treats_parameter_symbol_handle_as_parameter_value() -> None:
    """parameter_m 这种 DeepSeek 常见短写也应识别为参数值。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "第（Ⅱ）①问",
                "steps": [
                    {
                        "step_id": "solve_m_from_mn_length_ii1",
                        "recipe_hint": None,
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_1:parameter_m",
                        "strategy": "由 MN=√10 求出参数 m。",
                        "reads": [
                            "fact:ii_1:MN_length_squared_eq_10",
                            "fact:ii:M_coordinate_expr",
                            "fact:problem:m_gt_2",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii_1:parameter_m",
                                "ii_1",
                                "m=3，满足 MN=√10 的参数值",
                            )
                        ],
                        "reason": "parameter_m 是参数值，不是普通自由 fact。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_segment_length"


def test_candidate_resolver_keeps_minimum_expression_as_minimum_expression() -> None:
    """真正的最小值表达式仍应解析成 MinimumExpression。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_minimum_expr",
                        "recipe_hint": "distance_between_points",
                        "goal_type": "derive_minimum_value",
                        "target": "fact:ii:path_minimum_expr",
                        "strategy": "由拉直后的两点距离得到最小值表达式。",
                        "reads": ["fact:ii:path_minimum_target"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:path_minimum_expr",
                                "ii",
                                "EG+FG 的最小值表达式",
                            )
                        ],
                        "reason": "拉直后路径长度就是端点距离。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("MinimumExpression",)
    assert step_report.selected_capability_id == "distance_between_points"


def test_candidate_resolver_keeps_segment_distance_expr_as_expression() -> None:
    """OM/BN 这类分段距离表达式不是可复用路径最小值表达式。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "compute_om_distance_expr",
                        "recipe_hint": "distance_between_points",
                        "goal_type": "derive_distance_between_points",
                        "target": "fact:ii:OM_distance_expr",
                        "strategy": "参数化 M 后计算 OM 的距离表达式。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:OM_distance_expr",
                                "ii",
                                "OM 距离表达式",
                            )
                        ],
                        "reason": "这是分段距离 utility expression，不是路径最小值表达式。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    step_report = report.step_reports[0]
    assert step_report.produced_types == ("Expression",)
    assert any(
        "unsupported_utility_distance_expression" in error
        for error in step_report.errors
    )


def test_candidate_resolver_explains_auxiliary_point_inside_distance_step() -> None:
    """distance_between_points 不能同时承担辅助点构造，应给出可修复反馈。"""
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "compute_path_minimum_expression",
                        "recipe_hint": None,
                        "goal_type": "derive_path_minimum_expression",
                        "target": "fact:ii:path_minimum_expression",
                        "strategy": "先构造辅助点，再把 OM+BN 转成距离最小值。",
                        "reads": [
                            "point:problem:O",
                            "point:problem:B",
                            "fact:ii:path_minimum_target",
                            "fact:ii:CN_eq_CM",
                        ],
                        "creates": [
                            _create(
                                "point:ii:B_prime",
                                "point",
                                "ii",
                                "射线上等长构造出的辅助点",
                            )
                        ],
                        "produces": [
                            _produce(
                                "fact:ii:path_minimum_expression",
                                "ii",
                                "OM+BN 的最小值表达式",
                                output_type="MinimumExpression",
                            )
                        ],
                        "reason": "这一步混合了构造辅助点和求距离。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    assert report.ok is False
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id is None
    assert any(
        "unsupported_auxiliary_minimum_distance_step" in error
        for error in step_report.errors
    )


def test_candidate_resolver_explains_unsupported_path_transformation_shape() -> None:
    """自造 PathTransformation 应提示改用等长射线路径降维 recipe。"""
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "construct_path_transformation",
                        "recipe_hint": None,
                        "goal_type": "transform_path",
                        "target": "fact:ii:path_transformation",
                        "strategy": "自造反射辅助点，把路径转化成另一个距离。",
                        "reads": [
                            "fact:ii:path_minimum_target",
                            "fact:ii:CN_eq_CM",
                        ],
                        "creates": [
                            _create("point:ii:B_sym", "point", "ii", "反射辅助点"),
                            _create("point:ii:O_sym", "point", "ii", "反射辅助点"),
                        ],
                        "produces": [
                            _produce(
                                "fact:ii:path_transformation",
                                "ii",
                                "OM+BN 转化为两个自造辅助点的距离",
                                output_type="PathTransformation",
                            )
                        ],
                        "reason": "这条路线不在当前 family 的 executable capability 中。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    assert report.ok is False
    step_report = report.step_reports[0]
    assert step_report.selected_capability_id is None
    assert any(
        "unsupported_path_transformation_without_recipe" in error
        and "equal_length_ray_path_reduction" in error
        for error in step_report.errors
    )


def test_validator_does_not_merge_distinct_segment_distance_signatures() -> None:
    """分段距离表达式不应因同 scope 被误判成同一个 minimum_expr。"""
    payload = {
        "scopes": [
            {
                "scope_id": "ii",
                "label": "第（Ⅱ）问",
                "steps": [
                    {
                        "step_id": "compute_om_distance_expr",
                        "recipe_hint": "distance_between_points",
                        "goal_type": "derive_distance_between_points",
                        "target": "fact:ii:OM_distance_expr",
                        "strategy": "计算 OM 距离表达式。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:OM_distance_expr",
                                "ii",
                                "OM 距离表达式",
                                output_type="MinimumExpression",
                            )
                        ],
                        "reason": "DeepSeek 可能把普通距离表达式错标成 MinimumExpression。",
                    },
                    {
                        "step_id": "compute_bn_distance_expr",
                        "recipe_hint": "distance_between_points",
                        "goal_type": "derive_distance_between_points",
                        "target": "fact:ii:BN_distance_expr",
                        "strategy": "计算 BN 距离表达式。",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii:BN_distance_expr",
                                "ii",
                                "BN 距离表达式",
                                output_type="MinimumExpression",
                            )
                        ],
                        "reason": "不同分段距离不应被合并成同一个公共最小值结论。",
                    },
                ],
            }
        ]
    }

    StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )


def test_candidate_resolver_uses_hint_for_description_only_output_type() -> None:
    """只有 description 能判断类型时，明确 recipe_hint 可窄化低置信度误判。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_m_from_minimum",
                        "recipe_hint": "parameter_from_minimum_value",
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:derived_result",
                        "strategy": "由最小值条件反求参数。",
                        "reads": ["fact:ii_2:path_minimum_value_given"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii_2:derived_result",
                                "ii_2",
                                "由最小值条件反求参数 m 的具体值",
                            )
                        ],
                        "reason": "这个 handle 本身不带类型，只能靠 hint 纠偏。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_minimum_value"
    assert step_report.warnings == (
        "capability_hint_corrected_output_type:derive_m_from_minimum:MinimumExpression->ParameterValue",
    )


def test_candidate_resolver_infers_equal_angle_pair_as_angle_equality() -> None:
    """equal_angle_pair 这类泛化 handle 应识别为 AngleEquality。"""
    inputs = _heping_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "第（Ⅰ）②问",
                "steps": [
                    {
                        "step_id": "derive_equal_angle_from_angle_sum",
                        "recipe_hint": "angle_sum_equal_angle_candidates",
                        "goal_type": "derive_equal_angle",
                        "target": "fact:i_2:equal_angle_pair",
                        "strategy": "由角和等于 45° 导出等锐角事实。",
                        "reads": [
                            "fact:i_2:angle_sum_CBE_ACO_45",
                            "point:problem:A",
                            "point:problem:C",
                            "point:problem:B",
                            "point:problem:O",
                            "point:i_2:E",
                        ],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i_2:equal_angle_pair",
                                "i_2",
                                "由角和等于 45° 导出的等锐角事实",
                            )
                        ],
                        "reason": "LLM 未显式填写 output_type。",
                    }
                ],
            }
        ]
    }
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("AngleEquality",)
    assert step_report.selected_capability_id == "angle_sum_equal_angle_candidates"


def test_candidate_resolver_prefers_explicit_produced_output_type() -> None:
    """produces.output_type 应优先于 handle/description 的自然语言猜测。"""
    inputs = _nankai_inputs()
    payload = {
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "第（Ⅱ）②问",
                "steps": [
                    {
                        "step_id": "derive_parameter_from_point_named_fact",
                        "recipe_hint": "parameter_from_minimum_value",
                        "goal_type": "derive_parameter",
                        "target": "fact:ii_2:point_like_parameter",
                        "strategy": "由最小值条件反求参数。",
                        "reads": ["fact:ii_2:path_minimum_value_given"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:ii_2:point_like_parameter",
                                "ii_2",
                                "这个 description 提到了点坐标，但结构类型是参数值",
                                output_type="ParameterValue",
                            )
                        ],
                        "reason": "显式 output_type 应避免 point/coordinate 文本误判。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=_registry(),
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
    )

    assert report.ok is True
    step_report = report.step_reports[0]
    assert step_report.produced_types == ("ParameterValue",)
    assert step_report.selected_capability_id == "parameter_from_minimum_value"
    assert not any("capability_hint_corrected_output_type" in warning for warning in step_report.warnings)


def test_candidate_resolver_treats_line_intercept_output_as_point() -> None:
    """target_line_intercept 这类截点产物应按 Point，而不是按 Line 推断。"""
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    payload = {
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "第（Ⅰ）②问",
                "steps": [
                    {
                        "step_id": "derive_equal_angle",
                        "recipe_hint": "angle_sum_equal_angle_candidates",
                        "goal_type": "derive_equal_angle",
                        "target": "fact:i_2:angle_OBF_eq_ACO",
                        "strategy": "由角和条件得到等角关系。",
                        "reads": ["fact:i_2:angle_sum_CBE_ACO_45"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i_2:angle_OBF_eq_ACO",
                                "i_2",
                                "等角关系",
                                output_type="AngleEquality",
                            )
                        ],
                        "reason": "前置等角 fact。",
                    },
                    {
                        "step_id": "derive_axis_intercept_from_angle",
                        "recipe_hint": "axis_intercept_from_equal_acute_angles",
                        "goal_type": "derive_axis_intercept_from_equal_acute_angles",
                        "target": "fact:i_2:target_line_intercept",
                        "strategy": "由等角关系求目标直线与坐标轴的截点。",
                        "reads": ["fact:i_2:angle_OBF_eq_ACO", "point:problem:B"],
                        "creates": [],
                        "produces": [
                            _produce(
                                "fact:i_2:target_line_intercept",
                                "i_2",
                                "目标直线与坐标轴的交点坐标",
                            )
                        ],
                        "reason": "intercept 是点，不是直线方程。",
                    }
                ],
            }
        ]
    }
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        handle_registry=registry,
    )

    report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    step_report = report.step_reports[1]
    assert step_report.produced_types == ("Point",)
    assert step_report.selected_capability_id == "axis_intercept_from_equal_acute_angles"


def test_candidate_resolver_does_not_match_null_curve_point_step_to_equal_length_ray() -> None:
    """无 hint 的曲线交点 Point step 不能只因 Point 输出误接到等长射线 method。"""
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    step = _step(
        scope_id="i_2",
        step_id="derive_E_coordinate",
        recipe_hint=None,
        goal_type="derive_curve_intersection_point",
        target="answer:i_2_E",
        reads=(
            "fact:i:parabola_expression",
            "point:problem:B",
            "point:i_2:E",
        ),
        produces=(
            ProducedFact(
                "answer:i_2_E",
                "i_2",
                "E 的坐标",
                output_type="Point",
            ),
        ),
    )

    report = StepIntentCandidateResolver().resolve(
        _single_scope_draft(step, scope_id="i_2"),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    step_report = report.step_reports[0]
    assert step_report.selected_capability_id is None
    assert not any(candidate.capability_id == "equal_length_ray_point" for candidate in step_report.candidates)
    assert "missing_line_parabola_inputs" in report.errors[0]


def test_candidate_resolver_selects_line_parabola_when_curve_intersection_has_line_point() -> None:
    """曲线交点 step 有已解抛物线和第二个定线点时，应选择 line-parabola method。"""
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    step = _step(
        scope_id="i_2",
        step_id="derive_E_coordinate",
        recipe_hint=None,
        goal_type="derive_curve_intersection_point",
        target="answer:i_2_E",
        reads=(
            "fact:i:parabola_expression",
            "point:problem:B",
            "point:i_2:F",
            "fact:i_2:F_coordinate",
            "point:i_2:E",
        ),
        produces=(
            ProducedFact(
                "answer:i_2_E",
                "i_2",
                "E 的坐标",
                output_type="Point",
            ),
        ),
    )

    report = StepIntentCandidateResolver().resolve(
        _single_scope_draft(step, scope_id="i_2"),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
    )

    step_report = report.step_reports[0]
    assert report.ok is True
    assert step_report.selected_capability_id == "line_parabola_second_intersection_point"


def test_canonical_runtime_binding_index_maps_handles_to_runtime_paths() -> None:
    """BindingIndex 应把 canonical handle 解析到真实 RuntimeContext path。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )

    assert index.path_for("point:problem:D") == "$problem.points.D"
    assert index.path_for("point:ii:N") == "$question.ii.points.N"
    assert index.binding_for("point:ii:N").value_type == "PointRef"
    assert index.path_for("function:problem:parabola") == "$problem.expressions.quadratic"
    assert index.path_for("fact:problem:coefficient_relation") == "$problem.equations.coefficient_relation"
    assert index.path_for("fact:ii:path_minimum_target") == "$problem.conditions.path_minimum"
    assert index.path_for("answer:ii_2.intersection") == "$question.ii.points.G"


def test_canonical_runtime_binding_index_declares_created_auxiliary_point() -> None:
    """LLM creates 的辅助点应直接成为 declaration，不强行改名。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )

    binding = index.register_created_entity(
        CreatedEntity(
            handle="point:ii:Aux",
            entity_type="point",
            valid_scope="ii",
            description="折线拉直辅助点",
        )
    )

    assert binding.path == "$question.ii.points.Aux"
    assert binding.value_type == "PointRef"
    declaration = index.declarations["point:ii:Aux"]
    assert declaration.path == "$question.ii.points.Aux"
    assert declaration.definition["definition"] == "straightening_auxiliary_point"


def test_output_key_mapping_prefers_structured_answer_parabola_handle() -> None:
    """answer:*.parabola 应按 handle/value_type 映射，不依赖 description 关键词。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    promote = {
        "$step.compute_parabola.temp.coefficients": "$subquestion.ii_1.outputs.coefficients",
        "$step.compute_parabola.temp.parabola": "$subquestion.ii_1.answers.parabola",
    }

    assert (
        _output_key_from_promote_source(
            "compute_parabola",
            ProducedFact(
                handle="answer:ii_1.parabola",
                valid_scope="ii_1",
                description="二次函数表达式",
            ),
            "quadratic_from_constraints",
            promote,
            index,
        )
        == "parabola"
    )


def test_output_key_mapping_prefers_structured_answer_minimum_value() -> None:
    """answer:*.minimum_value 应优先映射 evaluated_distance，而不是靠“最小值”文本。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    promote = {
        "$step.compute_min.temp.distance": "$question.ii.outputs.minimum_expression",
        "$step.compute_min.temp.evaluated_distance": "$subquestion.ii_1.outputs.min_value",
    }

    assert (
        _output_key_from_promote_source(
            "compute_min",
            ProducedFact(
                handle="answer:ii_1.minimum_value",
                valid_scope="ii_1",
                description="最终结果",
            ),
            "distance_between_points",
            promote,
            index,
        )
        == "evaluated_distance"
    )


def test_output_key_mapping_prefers_structured_parameter_fact_handle() -> None:
    """fact:*:m_value 应结构化映射到 parameter_value。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    promote = {
        "$step.solve_m.temp.distance": "$subquestion.ii_2.outputs.distance",
        "$step.solve_m.temp.parameter_value": "$subquestion.ii_2.outputs.m",
    }

    assert (
        _output_key_from_promote_source(
            "solve_m",
            ProducedFact(
                handle="fact:ii_2:m_value",
                valid_scope="ii_2",
                description="求得 m",
            ),
            "parameter_from_minimum_value",
            promote,
            index,
        )
        == "parameter_value"
    )


def test_output_key_mapping_prefers_structured_minimum_expression_fact_handle() -> None:
    """公共最小值表达式 fact 应映射 distance，而不是误选 evaluated_distance。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    promote = {
        "$step.compute_expr.temp.distance": "$question.ii.outputs.minimum_expression",
        "$step.compute_expr.temp.evaluated_distance": "$subquestion.ii_1.outputs.min_value",
    }

    assert (
        _output_key_from_promote_source(
            "compute_expr",
            ProducedFact(
                handle="fact:ii:minimum_value_expr",
                valid_scope="ii",
                description="路径表达式",
            ),
            "distance_between_points",
            promote,
            index,
        )
        == "distance"
    )


def test_recipe_execution_registry_is_built_from_family_spec() -> None:
    """Recipe 执行 registry 应从 FamilySpec 派生，不再依赖 runtime default 表。"""
    registry = RecipeExecutionSpecRegistry.from_family_spec(_nankai_inputs().family_spec)

    right_angle = registry.get("right_angle_equal_length_construct_and_select")
    assert right_angle is not None
    assert right_angle.method_sequence == (
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    )
    assert right_angle.execution_strategy == "right_angle_construct_select"
    assert not hasattr(RecipeExecutionSpecRegistry, "default")


def test_recipe_capability_output_types_come_from_execution_output_aliases() -> None:
    """Recipe capability 的输出类型应由 FamilySpec.output_aliases 派生。"""
    method_specs = MethodSpecRegistry.load_from_code()
    families = (
        _nankai_inputs().family_spec,
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    )

    for family in families:
        capabilities = {
            capability.capability_id: capability
            for capability in build_executable_capabilities(family, method_specs)
            if capability.kind == "recipe"
        }
        for recipe in family.step_recipes:
            if recipe.execution is None or not recipe.execution.output_aliases:
                continue
            expected: list[str] = []
            for _output_key, output_type in recipe.execution.output_aliases:
                if output_type not in expected:
                    expected.append(output_type)

            assert capabilities[recipe.recipe_id].output_types == tuple(expected)


def test_method_capability_allows_creates_is_data_driven() -> None:
    """非 Point 输出但可引出辅助点的 method 应通过 capability 字段声明 creates 许可。"""
    method_specs = MethodSpecRegistry.load_from_code()
    capabilities = {
        capability.capability_id: capability
        for capability in build_executable_capabilities(
            QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
            method_specs,
        )
    }

    angle_sum = capabilities["angle_sum_equal_angle_candidates"]
    assert angle_sum.output_types == ("AngleEquality",)
    assert angle_sum.allows_creates is True

    parameter_method = capabilities["parameter_from_expression_value"]
    assert parameter_method.output_types == ("ParameterValue",)
    assert parameter_method.allows_creates is False


def test_method_capability_goal_aliases_come_from_method_solves() -> None:
    """通用 goal alias 应来自 MethodSpec.solves，而不是 resolver 硬编码表。"""
    method_specs = MethodSpecRegistry.load_from_code()
    capabilities = {
        capability.capability_id: capability
        for capability in build_executable_capabilities(
            QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
            method_specs,
        )
    }

    line_parabola = capabilities["line_parabola_second_intersection_point"]
    assert line_parabola.goal_type == "derive_line_parabola_second_intersection"
    assert "derive_curve_intersection_point" in line_parabola.goal_aliases


def test_recipe_compiler_registry_covers_family_execution_strategies() -> None:
    """FamilySpec 中的 recipe execution strategy 都应存在于默认编译策略注册表。"""
    families = (
        _nankai_inputs().family_spec,
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    )
    missing: list[str] = []
    for family in families:
        for recipe in family.step_recipes:
            if recipe.execution is None:
                continue
            if recipe.execution.execution_strategy not in DEFAULT_RECIPE_COMPILERS:
                missing.append(
                    f"{family.family_id}:{recipe.recipe_id}:{recipe.execution.execution_strategy}"
                )

    assert missing == []


def test_recipe_compiler_reports_unknown_execution_strategy() -> None:
    """未知 recipe execution strategy 应给出稳定错误，方便补注册。"""
    compiler = _RecipePlanCompiler.__new__(_RecipePlanCompiler)
    compiler.recipe_compilers = {}
    step = StepIntent(
        scope_id="i",
        step_id="unknown_recipe_step",
        goal_type="derive_test",
        target="fact:i:test",
        recipe_hint="unknown_recipe",
        strategy="测试未知 recipe 编译策略",
    )
    recipe = RecipeExecutionSpec(
        recipe_id="unknown_recipe",
        method_sequence=("synthetic_method",),
        execution_strategy="unknown_strategy",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="recipe_execution_strategy_missing: unknown_recipe:unknown_strategy",
    ):
        compiler._compile_recipe(step, recipe)


def test_recipe_compiler_accepts_injected_strategy() -> None:
    """新增 recipe 编译策略应通过 registry 注入，不需要修改 _compile_recipe 主流程。"""
    compiler = _RecipePlanCompiler.__new__(_RecipePlanCompiler)
    compiler.recipe_compilers = {
        "synthetic_strategy": (
            lambda _compiler, _step, _recipe: (_ for _ in ()).throw(
                StrategyDraftValidationError("synthetic_recipe_compiler_called")
            )
        )
    }
    step = StepIntent(
        scope_id="i",
        step_id="synthetic_recipe_step",
        goal_type="derive_test",
        target="fact:i:test",
        recipe_hint="synthetic_recipe",
        strategy="测试注入 recipe 编译策略",
    )
    recipe = RecipeExecutionSpec(
        recipe_id="synthetic_recipe",
        method_sequence=("synthetic_method",),
        execution_strategy="synthetic_strategy",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="synthetic_recipe_compiler_called",
    ):
        compiler._compile_recipe(step, recipe)


def test_method_binding_registry_loads_rules_from_family_spec() -> None:
    """Method input 绑定应由 FamilySpec 的 declarative rule 驱动。"""
    payload = _valid_step_intent_payload()
    draft = StepIntentValidator().validate_json(
        json.dumps(payload, ensure_ascii=False),
        question_goals=_nankai_inputs().question_goals,
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )
    step = draft.steps[0]
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec)

    inputs = rules.bind("quadratic_axis_from_relation", step, index)

    assert inputs == {
        "coefficient_relation": "$problem.equations.coefficient_relation",
        "a": "$problem.symbols.a",
        "b": "$problem.symbols.b",
        "target": "$problem.points.D",
    }


def test_method_binding_registry_loads_companion_outputs_from_family_spec() -> None:
    """method 固有伴随输出应由 FamilySpec 声明，不在 compiler 里按 method_id 特判。"""
    nankai_rules = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec)
    quadratic_rule = nankai_rules.rule_for("quadratic_from_constraints")

    assert quadratic_rule is not None
    assert quadratic_rule.always_emit_outputs == ("coefficients",)
    assert quadratic_rule.companion_outputs == (
        MethodCompanionOutputSpec(
            "coefficients",
            "answer_scope_output:coefficients",
            "runtime_step_output:coefficients",
        ),
    )

    hexi_rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
    )
    weighted_rule = hexi_rules.rule_for("weighted_axis_path_triangle_transform")

    assert weighted_rule is not None
    assert weighted_rule.always_emit_outputs == ("auxiliary_point", "auxiliary_locus")
    assert weighted_rule.companion_outputs == (
        MethodCompanionOutputSpec(
            "auxiliary_point",
            "weighted_path_auxiliary_point",
            "weighted_path_auxiliary_point",
        ),
        MethodCompanionOutputSpec(
            "auxiliary_locus",
            "scope_output:auxiliary_locus",
            "runtime_step_output:auxiliary_locus",
        ),
    )


def test_method_binding_registry_loads_prep_invocations_from_family_spec() -> None:
    """method 前置补位规则应由 FamilySpec 声明。"""
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
    )
    rule = rules.rule_for("quadratic_vertex_point")

    assert rule is not None
    assert rule.prep_invocations == (
        MethodPrepInvocationSpec(
            trigger_selector="missing_readable_type:Parabola",
            method_id="quadratic_from_constraints",
            output_aliases=(
                ("coefficients", "prepared_coefficients"),
                ("parabola", "prepared_parabola"),
            ),
            local_output_aliases=(
                ("type:Coefficients", "coefficients"),
                ("type:Parabola", "parabola"),
            ),
        ),
    )


def test_equal_length_family_x_axis_intercept_has_parabola_prep_rule() -> None:
    """等长射线路径 family 中，x 轴交点 method 缺 Parabola 时也应可自动准备。"""
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    rule = rules.rule_for("quadratic_x_axis_intercept_point")

    assert rule is not None
    assert rule.prep_invocations == (
        MethodPrepInvocationSpec(
            trigger_selector="missing_readable_type:Parabola",
            method_id="quadratic_from_constraints",
            output_aliases=(
                ("coefficients", "prepared_coefficients"),
                ("parabola", "prepared_parabola"),
            ),
            local_output_aliases=(
                ("type:Coefficients", "coefficients"),
                ("type:Parabola", "parabola"),
            ),
        ),
    )


def test_square_family_parabola_methods_have_source_guarded_prep_rules() -> None:
    """square family 的二次函数后续 method 缺 Parabola 时应有受限 prep。"""
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY
    )
    for method_id in (
        "quadratic_x_axis_intercept_point",
        "quadratic_axis_parameterized_point",
        "point_candidates_from_curve_point_condition",
    ):
        rule = rules.rule_for(method_id)
        assert rule is not None
        assert rule.prep_invocations == (
            MethodPrepInvocationSpec(
                trigger_selector="missing_readable_type_with_quadratic_source:Parabola",
                method_id="quadratic_from_constraints",
                output_aliases=(
                    ("coefficients", "__local_only__"),
                    ("parabola", "__local_only__"),
                ),
                local_output_aliases=(
                    ("type:Coefficients", "coefficients"),
                    ("type:Parabola", "parabola"),
                ),
                expansion_selectors=("known_coefficients_if_read",),
            ),
        )


def test_prep_invocation_builder_generates_declared_local_outputs() -> None:
    """PrepInvocationBuilder 应按声明生成 prep invocation/promote/local outputs。"""
    problem = load_problem_ir(HEXI_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_hexi_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i",
        step_id="derive_vertex_i",
        recipe_hint="quadratic_vertex_point",
        goal_type="derive_vertex_point",
        target="answer:i.P",
    )

    result = PrepInvocationBuilder(binding_rules=rules, index=index).build(
        "quadratic_vertex_point",
        step,
    )

    assert len(result.invocations) == 1
    invocation = result.invocations[0]
    assert invocation.method_id == "quadratic_from_constraints"
    assert invocation.invocation_id == "derive_vertex_i.prepare_quadratic_from_constraints"
    assert invocation.outputs == {
        "coefficients": "$step.derive_vertex_i.temp.prepared_coefficients",
        "parabola": "$step.derive_vertex_i.temp.prepared_parabola",
    }
    assert result.promote == {
        "$step.derive_vertex_i.temp.prepared_coefficients": "$question.i.outputs.prepared_coefficients",
        "$step.derive_vertex_i.temp.prepared_parabola": "$question.i.outputs.prepared_parabola",
    }
    assert result.local_outputs == {
        "type:Coefficients": "$step.derive_vertex_i.temp.prepared_coefficients",
        "type:Parabola": "$step.derive_vertex_i.temp.prepared_parabola",
    }


def test_step_intent_preflight_warns_about_missing_reusable_parabola_state() -> None:
    """preflight 应发现和平二模 attempt-1 这类同源缺 Parabola 状态问题。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="i_1",
                label="第（Ⅰ）①问",
                steps=(
                    _step(
                        scope_id="i_1",
                        step_id="derive_A_left_intercept",
                        recipe_hint="quadratic_x_axis_intercept_point",
                        goal_type="derive_x_axis_intercept_point",
                        target="answer:i_1.A",
                        reads=(
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "point:problem:A",
                            "fact:problem:A_on_parabola",
                        ),
                        produces=(
                            ProducedFact("answer:i_1.A", "i_1", "A 坐标", output_type="Point"),
                        ),
                    ),
                ),
            ),
            StepIntentScope(
                scope_id="i_2",
                label="第（Ⅰ）②问",
                steps=(
                    _step(
                        scope_id="i_2",
                        step_id="parameterize_E_i2",
                        recipe_hint="quadratic_axis_parameterized_point",
                        goal_type="derive_parameterized_point",
                        target="fact:i_2:E_parametric_coordinate",
                        reads=(
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "point:i_2:E",
                            "fact:i_2:E_on_axis",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:E_parametric_coordinate",
                                "i_2",
                                "E 含参坐标",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_2",
                        step_id="solve_E_candidates",
                        recipe_hint="point_candidates_from_curve_point_condition",
                        goal_type="derive_point_candidates_from_curve_point_condition",
                        target="answer:i_2.E",
                        reads=(
                            "fact:i_2:E_parametric_coordinate",
                            "fact:i_2:G_parametric_coordinate",
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "fact:i_2:G_on_parabola",
                        ),
                        produces=(
                            ProducedFact("answer:i_2.E", "i_2", "E 候选", output_type="PointList"),
                        ),
                    ),
                ),
            ),
        )
    )

    issues = StepIntentPreflightAnalyzer().analyze(
        draft,
        family_spec=QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        handle_registry=registry,
    )

    assert [issue.step_id for issue in issues] == [
        "derive_A_left_intercept",
        "parameterize_E_i2",
        "solve_E_candidates",
    ]
    assert {issue.category for issue in issues} == {"code_fillable"}
    assert all(issue.code == "missing_explicit_parabola_state" for issue in issues)


def test_step_intent_preflight_does_not_warn_when_parabola_fact_is_reusable() -> None:
    """显式产生并读取公共 Parabola fact 时，不应再提示缺状态。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _heping_ermo_i2_curve_condition_draft(
        candidate_reads=(
            "fact:i:parabola_expression",
            "fact:i_2:E_parametric_coordinate",
            "fact:i_2:G_coordinate_expr",
            "fact:i_2:G_on_parabola",
        ),
    )

    issues = StepIntentPreflightAnalyzer().analyze(
        draft,
        family_spec=QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        handle_registry=registry,
    )

    assert issues == ()


def test_step_intent_preflight_parabola_prep_uses_output_type_not_method_id() -> None:
    """preflight 判断 Parabola prep 时不应硬编码 prep method_id。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    family = replace(
        QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        method_binding_rules=(
            MethodBindingRuleSpec(
                method_id="synthetic_parabola_consumer",
                input_bindings=(
                    MethodInputBindingSpec("quadratic", "read_type:Parabola"),
                ),
                prep_invocations=(
                    MethodPrepInvocationSpec(
                        trigger_selector="missing_readable_type_with_quadratic_source:Parabola",
                        method_id="custom_parabola_builder",
                        local_output_aliases=(("type:Parabola", "parabola"),),
                    ),
                ),
            ),
        ),
        step_recipes=(),
    )
    draft = _single_scope_draft(
        _step(
            scope_id="i_1",
            step_id="consume_parabola",
            recipe_hint="synthetic_parabola_consumer",
            goal_type="derive_point",
            target="fact:i_1:point",
            reads=("function:problem:parabola", "fact:i:b_value"),
            produces=(
                ProducedFact("fact:i_1:point", "i_1", "点坐标", output_type="Point"),
            ),
        ),
        scope_id="i_1",
    )

    issues = StepIntentPreflightAnalyzer().analyze(
        draft,
        family_spec=family,
        handle_registry=registry,
    )

    assert len(issues) == 1
    assert issues[0].code == "missing_explicit_parabola_state"
    assert issues[0].category == "code_fillable"


def test_x_axis_intercept_prep_generates_parabola_when_missing() -> None:
    """求另一个 x 轴交点时，若当前无 Parabola，可先用约束准备临时抛物线。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="ii",
        step_id="derive_B_coordinate_expr_for_ii",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:ii:B_coordinate_expr",
        reads=(
            "function:problem:parabola",
            "fact:problem:A_coordinate_value",
            "fact:problem:A_on_parabola",
            "point:problem:B",
            "symbol:problem:a",
        ),
        produces=(
            ProducedFact(
                "fact:ii:B_coordinate_expr",
                "ii",
                "B 点坐标表达式，含参数 a",
                output_type="Point",
            ),
        ),
    )

    result = PrepInvocationBuilder(binding_rules=rules, index=index).build(
        "quadratic_x_axis_intercept_point",
        step,
    )

    assert len(result.invocations) == 1
    invocation = result.invocations[0]
    assert invocation.method_id == "quadratic_from_constraints"
    assert invocation.outputs == {
        "coefficients": "$step.derive_B_coordinate_expr_for_ii.temp.prepared_coefficients",
        "parabola": "$step.derive_B_coordinate_expr_for_ii.temp.prepared_parabola",
    }
    assert result.local_outputs["type:Parabola"] == (
        "$step.derive_B_coordinate_expr_for_ii.temp.prepared_parabola"
    )


def test_square_x_axis_intercept_executes_with_temporary_parabola_prep() -> None:
    """和平二模第（Ⅰ）① A 点：缺显式 Parabola 时应能用 function+b/c 临时补位。"""
    problem = _heping_ermo_problem()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="i_1",
                label="第（Ⅰ）①问",
                steps=(
                    _step(
                        scope_id="i_1",
                        step_id="derive_A_left_intercept",
                        recipe_hint="quadratic_x_axis_intercept_point",
                        goal_type="derive_x_axis_intercept_point",
                        target="answer:i_1.A",
                        reads=(
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "point:problem:A",
                            "fact:problem:A_on_parabola",
                        ),
                        produces=(
                            ProducedFact("answer:i_1.A", "i_1", "A 坐标", output_type="Point"),
                        ),
                    ),
                ),
            ),
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        method_specs=MethodSpecRegistry.load_from_code(),
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=extract_question_goals(problem),
    )

    assert output is not None
    assert diagnostic.ok
    assert diagnostic.accepted_prefix[0].method_ids == (
        "quadratic_from_constraints",
        "quadratic_x_axis_intercept_point",
    )
    assert diagnostic.preflight_issues[0].step_id == "derive_A_left_intercept"
    assert diagnostic.preflight_issues[0].category == "code_fillable"


def test_quadratic_constraints_uses_coordinate_fact_for_curve_point_ref() -> None:
    """曲线点实体仍是 PointRef 时，应读取同名坐标 fact 作为曲线点约束。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    index.register("fact:problem:D_coordinate", "$problem.points.D", "Point", source="test")
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i_1",
        step_id="derive_parabola_from_d",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i_1_parabola",
        reads=(
            "function:problem:parabola",
            "fact:problem:D_coordinate",
            "fact:i:D_on_parabola",
        ),
        produces=(
            ProducedFact("answer:i_1_parabola", "i_1", "抛物线答案", output_type="Parabola"),
        ),
    )

    inputs = rules.bind("quadratic_from_constraints", step, index)

    assert inputs["curve_point"] == "$problem.points.D"


def test_y_axis_intercept_target_accepts_point_handle_in_target_text() -> None:
    """target 中带完整 point handle 时，应提取为 y 轴交点 method 的 target。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i_1",
        step_id="derive_C_coordinate",
        recipe_hint="quadratic_y_axis_intercept_point",
        goal_type="derive_y_axis_intercept_point",
        target="point:problem:C coordinate",
        reads=("function:problem:parabola",),
        produces=(
            ProducedFact(
                "fact:problem:C_coordinate_value",
                "problem",
                "C 点坐标",
                output_type="Point",
            ),
        ),
    )

    inputs = rules.bind("quadratic_y_axis_intercept_point", step, index)

    assert inputs["target"] == "$problem.points.C"


def test_y_axis_intercept_generic_output_uses_unique_y_axis_entity() -> None:
    """y_intercept_coordinate 这类泛化产物应绑定到唯一 y_axis_intercept 点。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i_1",
        step_id="derive_C_coordinate",
        recipe_hint="quadratic_y_axis_intercept_point",
        goal_type="derive_y_axis_intercept_point",
        target="抛物线与 y 轴交点坐标",
        reads=("function:problem:parabola",),
        produces=(
            ProducedFact(
                "fact:i:y_intercept_coordinate",
                "i",
                "C 点坐标",
                output_type="Point",
            ),
        ),
    )

    inputs = rules.bind("quadratic_y_axis_intercept_point", step, index)
    target = _target_path_for_produced(step.produces[0], "Point", index, step)

    assert inputs["target"] == "$problem.points.C"
    assert target == "$question.i.outputs.y_intercept_coordinate"


def test_x_axis_known_point_infers_excluded_intercept_when_not_read() -> None:
    """LLM 少写 A reads 时，可由 B 的 PointRef 定义推断 known_point。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i_1",
        step_id="derive_B_coordinate_without_reading_a",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:i:B_coordinate",
        reads=("fact:i:parabola_expression", "point:problem:B"),
        produces=(
            ProducedFact("fact:i:B_coordinate", "i", "B 点坐标", output_type="Point"),
        ),
    )

    inputs = rules.bind(
        "quadratic_x_axis_intercept_point",
        step,
        index,
        local_outputs={"type:Parabola": "$question.i.outputs.parabola_expression"},
    )

    assert inputs["known_point"] == "$problem.points.A"


def test_quadratic_binding_infers_visible_curve_fact_from_read_point() -> None:
    """读入点和坐标时，可复用可见 point_on_curve 题设 fact 补曲线点约束。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i_1",
        step_id="derive_parabola_i",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i_1_parabola",
        reads=("point:problem:A", "fact:problem:A_coordinate_value"),
        produces=(
            ProducedFact(
                "answer:i_1_parabola",
                "i",
                "第（Ⅰ）问抛物线",
                output_type="Parabola",
            ),
        ),
    )

    inputs = rules.bind("quadratic_from_constraints", step, index)

    assert inputs["curve_point"] == "$problem.points.A"


def test_quadratic_binding_infers_visible_curve_fact_from_coordinate_read() -> None:
    """只读点坐标 fact 时，也可由可见 point_on_curve 题设 fact 补曲线点约束。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="i_1",
        step_id="derive_parabola_i",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i_1_parabola",
        reads=("fact:problem:A_coordinate_value",),
        produces=(
            ProducedFact(
                "answer:i_1_parabola",
                "i",
                "第（Ⅰ）问抛物线",
                output_type="Parabola",
            ),
        ),
    )

    inputs = rules.bind("quadratic_from_constraints", step, index)

    assert inputs["curve_point"] == "$problem.points.A"


def test_quadratic_binding_prefers_explicit_coordinate_fact_over_same_name_point() -> None:
    """同名点跨 scope 时，显式读取的坐标 fact 比已计算的同名点更具体。"""
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(problem_to_llm_payload(problem)),
        question_goals=extract_question_goals(problem),
    )
    # 模拟第（Ⅰ）问已经把 problem scope 的 A 求成 Point；第（Ⅱ）问仍应使用
    # 自己题设给出的 A(-c,0)，不能误用前序小问的 A(-3,0)。
    index.register("point:problem:A", "$problem.points.A", "Point", source="test")
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="ii",
        step_id="derive_parabola_in_c",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:parabola_expression_in_c",
        reads=("function:problem:parabola", "point:problem:A", "fact:ii:A_coordinate_value"),
        produces=(
            ProducedFact(
                "fact:ii:parabola_expression_in_c",
                "ii",
                "第（Ⅱ）问含参数 c 的抛物线",
                output_type="Parabola",
            ),
        ),
    )

    inputs = rules.bind("quadratic_from_constraints", step, index)

    assert inputs["curve_point"] == "$question.ii.points.A"


def test_promote_outputs_prefers_answer_target_over_reusable_fact_alias() -> None:
    """同一 Parabola output 同时服务答案和 fact alias 时，应优先写入答案目标。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = _heping_inputs()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=inputs.question_goals,
    )
    rules = MethodBindingRuleRegistry.from_family_spec(inputs.family_spec)
    step = _step(
        scope_id="i_1",
        step_id="derive_parabola_i",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i_1_parabola",
        produces=(
            ProducedFact(
                "answer:i_1_parabola",
                "i",
                "第（Ⅰ）问抛物线答案",
                output_type="Parabola",
            ),
            ProducedFact(
                "fact:i:parabola_expression",
                "i",
                "后续可复用的抛物线表达式",
                output_type="Parabola",
            ),
        ),
    )

    promote = _promote_outputs_for_step(
        step,
        "quadratic_from_constraints",
        {
            "parabola": "$step.derive_parabola_i.temp.parabola",
            "coefficients": "$step.derive_parabola_i.temp.coefficients",
        },
        {"parabola": "Parabola", "coefficients": "Coefficients"},
        index,
        rules,
    )

    assert promote["$step.derive_parabola_i.temp.parabola"] == "$question.i.outputs.parabola"


def test_equal_angle_axis_intercept_reads_computed_x_axis_point_fact() -> None:
    """等角截点 method 应从 reads 中的 B 坐标 fact 读取 B，而不是未解析 PointRef。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = _heping_inputs()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=inputs.question_goals,
    )
    index.register(
        "fact:i:B_coordinate",
        "$question.i.outputs.B_coordinate",
        "Point",
        source="test",
    )
    index.register(
        "fact:i_2:angle_OBF_eq_ACO",
        "$subquestion.i_2.outputs.angle_OBF_eq_ACO",
        "AngleEquality",
        source="test",
    )
    index.register_created_entity(
        CreatedEntity(
            "point:i_2:F",
            "point",
            "i_2",
            "直线 BE 与 y 轴交点",
        )
    )
    rules = MethodBindingRuleRegistry.from_family_spec(inputs.family_spec)
    step = _step(
        scope_id="i_2",
        step_id="derive_BE_y_intercept",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept_from_equal_acute_angles",
        target="point:i_2:F",
        reads=(
            "fact:i_2:angle_OBF_eq_ACO",
            "point:problem:B",
            "fact:i:B_coordinate",
            "point:problem:O",
            "point:problem:C",
            "point:problem:A",
        ),
        produces=(
            ProducedFact(
                "fact:i_2:F_coordinate",
                "i_2",
                "F 点坐标",
                output_type="Point",
            ),
        ),
    )

    bound = rules.bind("axis_intercept_from_equal_acute_angles", step, index)

    assert bound["x_axis_point"] == "$question.i.outputs.B_coordinate"


def test_equal_angle_axis_intercept_falls_back_to_visible_computed_point_fact() -> None:
    """若 LLM 漏写 B_coordinate reads，可使用唯一可见的前序 B 坐标 fact。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = _heping_inputs()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=inputs.question_goals,
    )
    index.register(
        "fact:i:B_coordinate",
        "$question.i.outputs.B_coordinate",
        "Point",
        source="test",
    )
    index.register(
        "fact:i_2:angle_OBF_eq_ACO",
        "$subquestion.i_2.outputs.angle_OBF_eq_ACO",
        "AngleEquality",
        source="test",
    )
    index.register_created_entity(
        CreatedEntity(
            "point:i_2:F",
            "point",
            "i_2",
            "直线 BE 与 y 轴交点",
        )
    )
    rules = MethodBindingRuleRegistry.from_family_spec(inputs.family_spec)
    step = _step(
        scope_id="i_2",
        step_id="derive_F_from_equal_angle",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept_from_equal_acute_angles",
        target="point:i_2:F",
        reads=(
            "fact:i_2:angle_OBF_eq_ACO",
            "point:problem:B",
            "point:problem:O",
            "point:problem:C",
            "point:problem:A",
        ),
        produces=(
            ProducedFact(
                "fact:i_2:F_coordinate",
                "i_2",
                "F 点坐标",
                output_type="Point",
            ),
        ),
    )

    bound = rules.bind("axis_intercept_from_equal_acute_angles", step, index)

    assert bound["x_axis_point"] == "$question.i.outputs.B_coordinate"


def test_equal_angle_axis_intercept_visible_point_fact_fill_is_not_point_name_specific() -> None:
    """坐标 fact 补位按 canonical 点名匹配，不依赖和平题的 B 点。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = _heping_inputs()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=inputs.question_goals,
    )
    index.register(
        "point:problem:Z",
        "$problem.points.Z",
        "PointRef",
        source="test",
    )
    index.register(
        "fact:i:Z_coordinate",
        "$question.i.outputs.Z_coordinate",
        "Point",
        source="test",
    )
    index.register(
        "fact:i_2:angle_OZF_eq_AZO",
        "$subquestion.i_2.outputs.angle_OZF_eq_AZO",
        "AngleEquality",
        source="test",
    )
    index.register_created_entity(
        CreatedEntity("point:i_2:F", "point", "i_2", "直线 CF 与 y 轴交点")
    )
    rules = MethodBindingRuleRegistry.from_family_spec(inputs.family_spec)
    step = _step(
        scope_id="i_2",
        step_id="derive_CF_y_intercept",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept_from_equal_acute_angles",
        target="point:i_2:F",
        reads=(
            "fact:i_2:angle_OZF_eq_AZO",
            "point:problem:Z",
            "point:problem:A",
            "point:problem:O",
        ),
        produces=(
            ProducedFact("fact:i_2:F_coordinate", "i_2", "F 点坐标", output_type="Point"),
        ),
    )

    bound = rules.bind("axis_intercept_from_equal_acute_angles", step, index)

    assert bound["x_axis_point"] == "$question.i.outputs.Z_coordinate"
    assert bound["y_axis_point"] == "$question.i.outputs.Z_coordinate"


def test_line_parabola_uses_visible_computed_point_fact_when_point_read_is_unresolved() -> None:
    """直线交抛物线 step 漏写 B_coordinate reads 时，也可复用唯一可见 B 坐标。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = _heping_inputs()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=inputs.question_goals,
    )
    index.register(
        "fact:i:parabola_expression",
        "$question.i.outputs.parabola",
        "Parabola",
        source="test",
    )
    index.register(
        "fact:i:B_coordinate",
        "$question.i.outputs.B_coordinate",
        "Point",
        source="test",
    )
    index.register_created_entity(
        CreatedEntity("point:i_2:F", "point", "i_2", "直线 BE 与 y 轴交点")
    )
    index.register(
        "fact:i_2:F_coordinate",
        "$subquestion.i_2.points.F",
        "Point",
        source="test",
    )
    index.register_created_entity(
        CreatedEntity("point:i_2:E", "point", "i_2", "抛物线与 BE 的交点")
    )
    rules = MethodBindingRuleRegistry.from_family_spec(inputs.family_spec)
    step = _step(
        scope_id="i_2",
        step_id="derive_E_point",
        recipe_hint="line_parabola_second_intersection_point",
        goal_type="derive_curve_intersection_point",
        target="answer:i_2_E",
        reads=(
            "fact:i:parabola_expression",
            "point:problem:B",
            "point:i_2:F",
            "fact:i_2:F_coordinate",
            "point:i_2:E",
        ),
        produces=(
            ProducedFact("answer:i_2_E", "i_2", "E 点坐标", output_type="Point"),
        ),
    )

    bound = rules.bind("line_parabola_second_intersection_point", step, index)

    assert "$question.i.outputs.B_coordinate" in {
        bound["line_p1"],
        bound["line_p2"],
    }


def test_entity_state_resolver_fills_point_from_unique_visible_coordinate_fact() -> None:
    """实体点读法可补到唯一可见坐标 fact，不依赖固定点名。"""
    index = _heping_binding_index()
    index.register(
        "fact:i:Z_coordinate",
        "$question.i.outputs.Z_coordinate",
        "Point",
        source="test",
    )
    step = _step(
        scope_id="i_2",
        step_id="use_Z_coordinate",
        recipe_hint="distance_between_points",
        goal_type="derive_distance",
        target="fact:i_2:distance",
        reads=("point:problem:Z",),
    )

    resolved = EntityStateResolver().resolve("point:problem:Z", "Point", step, index)

    assert resolved == "$question.i.outputs.Z_coordinate"


def test_entity_state_resolver_records_applied_fill_without_runtime_path() -> None:
    """EntityState 补位应记录 canonical handle 摘要，不把 RuntimePath 反馈给 LLM。"""
    index = _heping_binding_index()
    index.register(
        "fact:i:Z_coordinate",
        "$question.i.outputs.Z_coordinate",
        "Point",
        source="test",
    )
    step = _step(
        scope_id="i_2",
        step_id="use_Z_coordinate",
        recipe_hint="distance_between_points",
        goal_type="derive_distance",
        target="fact:i_2:distance",
        reads=("point:problem:Z",),
    )

    EntityStateResolver().resolve("point:problem:Z", "Point", step, index)

    assert len(index.applied_fills) == 1
    payload = index.applied_fills[0].to_payload()
    assert payload["input_handle"] == "point:problem:Z"
    assert payload["resolved_handle"] == "fact:i:Z_coordinate"
    assert "$question" not in json.dumps(payload, ensure_ascii=False)


def test_entity_state_resolver_fills_function_from_visible_parabola_state() -> None:
    """函数实体读法可补到已求出的 Parabola answer/fact。"""
    index = _heping_binding_index()
    step = _step(
        scope_id="i_2",
        step_id="use_resolved_parabola",
        recipe_hint="line_parabola_second_intersection_point",
        goal_type="derive_curve_intersection_point",
        target="answer:i_2_E",
        reads=("function:problem:parabola",),
    )

    resolved = EntityStateResolver().resolve(
        "function:problem:parabola",
        "Parabola",
        step,
        index,
    )

    assert resolved == "$question.i.outputs.parabola"


def test_entity_state_resolver_fills_symbol_from_unique_parameter_value_fact() -> None:
    """符号实体读法可补到唯一可见参数值 fact。"""
    index = _heping_binding_index()
    index.register(
        "fact:ii:z_value",
        "$question.ii.outputs.z",
        "ParameterValue",
        source="test",
    )
    step = _step(
        scope_id="ii",
        step_id="use_z_value",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="evaluate_expression",
        target="fact:ii:evaluated_expression",
        reads=("symbol:problem:z",),
    )

    resolved = EntityStateResolver().resolve(
        "symbol:problem:z",
        "ParameterValue",
        step,
        index,
    )

    assert resolved == "$question.ii.outputs.z"


def test_entity_state_resolver_fills_segment_from_structured_condition_fact() -> None:
    """线段实体读法可补到结构化指向该线段的题设条件 fact。"""
    index = _heping_binding_index()
    step = _step(
        scope_id="ii",
        step_id="use_segment_condition",
        recipe_hint="equal_length_ray_path_reduction",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        reads=("segment:ii:BC",),
    )

    resolved = EntityStateResolver().resolve("segment:ii:BC", "Condition", step, index)

    assert resolved == index.path_for("fact:ii:M_on_segment_BC", expected_type="Condition")


def test_entity_state_resolver_does_not_fill_from_sibling_scope() -> None:
    """补位只能读取当前 scope 可见的父级/本级状态，不能跨 sibling。"""
    index = _heping_binding_index()
    index.register(
        "fact:i_1:Z_coordinate",
        "$subquestion.i_1.outputs.Z_coordinate",
        "Point",
        source="test",
    )
    step = _step(
        scope_id="i_2",
        step_id="use_Z_from_sibling",
        recipe_hint="distance_between_points",
        goal_type="derive_distance",
        target="fact:i_2:distance",
        reads=("point:problem:Z",),
    )

    resolved = EntityStateResolver().resolve("point:problem:Z", "Point", step, index)

    assert resolved is None


def test_entity_state_resolver_rejects_ambiguous_visible_state_facts() -> None:
    """多个可见状态 fact 都匹配同一实体时，不猜测。"""
    index = _heping_binding_index()
    index.register(
        "fact:i:Z_coordinate",
        "$question.i.outputs.Z_coordinate",
        "Point",
        source="test",
    )
    index.register(
        "fact:i_2:Z_coordinate_alternate",
        "$subquestion.i_2.outputs.Z_coordinate_alternate",
        "Point",
        source="test",
    )
    step = _step(
        scope_id="i_2",
        step_id="use_ambiguous_Z",
        recipe_hint="distance_between_points",
        goal_type="derive_distance",
        target="fact:i_2:distance",
        reads=("point:problem:Z",),
    )

    with pytest.raises(StrategyDraftValidationError, match="ambiguous_runtime_fact"):
        EntityStateResolver().resolve("point:problem:Z", "Point", step, index)


def test_x_axis_intercept_target_uses_pointref_even_when_point_binding_exists() -> None:
    """目标点已有 Point 绑定时，x 轴交点 method 仍应读取底层 PointRef target。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    index.register("point:problem:B", "$problem.points.B", "Point", source="test")
    index.register("point:problem:A", "$problem.points.A", "Point", source="test")
    rules = MethodBindingRuleRegistry.from_family_spec(
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY
    )
    step = _step(
        scope_id="ii",
        step_id="derive_B_coordinate_expr_for_ii",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:ii:B_coordinate_expr",
        reads=("point:problem:B", "point:problem:A"),
        produces=(
            ProducedFact(
                "fact:ii:B_coordinate_expr",
                "ii",
                "B 点坐标表达式，含参数 a",
                output_type="Point",
            ),
        ),
    )

    inputs = rules.bind(
        "quadratic_x_axis_intercept_point",
        step,
        index,
        local_outputs={"type:Parabola": "$step.derive_B.temp.prepared_parabola"},
    )

    assert inputs["target"] == "$problem.points.B"
    assert inputs["known_point"] == "$problem.points.A"


def test_bare_point_coordinate_fact_promotes_to_scoped_output() -> None:
    """``B_coordinate`` 这类 bare 坐标 fact 不应写回题设 point path。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    step = _step(
        scope_id="ii",
        step_id="derive_B_coordinate_expr_for_ii",
        recipe_hint="quadratic_x_axis_intercept_point",
        goal_type="derive_axis_intercept_point",
        target="fact:ii:B_coordinate",
        reads=("point:problem:B", "point:problem:A"),
        produces=(
            ProducedFact(
                "fact:ii:B_coordinate",
                "ii",
                "B 点坐标表达式，含参数 a",
                output_type="Point",
            ),
        ),
    )

    target = _target_path_for_produced(
        step.produces[0],
        "Point",
        index,
        step,
    )

    assert target == "$question.ii.outputs.B_coordinate"


def test_equal_length_ray_recipe_accepts_coordinate_fact_with_parameter_suffix() -> None:
    """B_coordinate_in_a 这类含参坐标 fact 应被 recipe 内部识别为点值。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    index.register("fact:ii:B_coordinate_in_a", "$question.ii.outputs.B_coordinate_in_a", "Point", source="test")
    step = _step(
        scope_id="ii",
        step_id="reduce_equal_length_ray_path",
        recipe_hint="equal_length_ray_path_reduction",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        reads=("fact:ii:B_coordinate_in_a",),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "路径最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )

    from shuxueshuo_server.solver.runtime.recipe_compiler import _point_value_path_for_step

    assert _point_value_path_for_step("point:problem:B", step, index) == "$question.ii.outputs.B_coordinate_in_a"


def test_method_outputs_for_step_uses_declared_companion_outputs() -> None:
    """输出路径生成应读取 binding rule 的 always/companion outputs。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    rules = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec)
    step = _step(
        scope_id="i",
        step_id="derive_i_parabola",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i.parabola",
        produces=(
            ProducedFact(
                "answer:i.parabola",
                "i",
                "第一问抛物线",
                output_type="Parabola",
            ),
        ),
    )

    outputs = _method_outputs_for_step(
        "quadratic_from_constraints",
        step,
        {"coefficients": "Coefficients", "parabola": "Parabola"},
        index,
        rules,
    )

    assert outputs == {
        "parabola": "$step.derive_i_parabola.temp.parabola",
        "coefficients": "$step.derive_i_parabola.temp.coefficients",
    }


def test_method_outputs_for_step_rejects_unknown_declared_output() -> None:
    """FamilySpec 声明 method 不存在的 companion output 时应尽早失败。"""
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="synthetic_method",
                companion_outputs=(
                    MethodCompanionOutputSpec(
                        "missing_output",
                        "scope_output:missing_output",
                    ),
                ),
            ),
        )
    )
    step = _step(
        scope_id="i",
        step_id="synthetic_step",
        recipe_hint="synthetic_method",
        goal_type="derive_expression",
        target="fact:i:value",
        produces=(
            ProducedFact(
                "fact:i:value",
                "i",
                "测试表达式",
                output_type="Expression",
            ),
        ),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="method_output_missing: synthetic_method.missing_output",
    ):
        _method_outputs_for_step(
            "synthetic_method",
            step,
            {"value": "Expression"},
            index,
            rules,
        )


def test_method_binding_registry_covers_family_selectors() -> None:
    """FamilySpec 中声明的 selector 应在构造 registry 时完成校验。"""
    rules = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec)

    assert rules.rules


def test_method_binding_registry_reports_unknown_selectors() -> None:
    """未知 selector 应在 registry 构造阶段失败。"""
    with pytest.raises(StrategyDraftValidationError, match="binding_selector_missing: unknown_selector"):
        MethodBindingRuleRegistry(
            (
                MethodBindingRuleSpec(
                    method_id="synthetic_method",
                    input_bindings=(
                        MethodInputBindingSpec("value", "unknown_selector"),
                    ),
                ),
            )
        )


def test_method_binding_registry_reports_unknown_expansion_selectors() -> None:
    """未知 expansion selector 应在 registry 构造阶段失败。"""
    with pytest.raises(
        StrategyDraftValidationError,
        match="binding_expansion_selector_missing: unknown_expansion",
    ):
        MethodBindingRuleRegistry(
            (
                MethodBindingRuleSpec(
                    method_id="synthetic_method",
                    expansion_selectors=("unknown_expansion",),
                ),
            )
        )


def test_method_binding_registry_accepts_injected_selector() -> None:
    """测试可注入 selector callable，新增 selector 不需要改 _select 主流程。"""
    step = StepIntentValidator().validate_json(
        json.dumps(_valid_step_intent_payload(), ensure_ascii=False),
        question_goals=_nankai_inputs().question_goals,
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    ).steps[0]
    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="synthetic_method",
                input_bindings=(
                    MethodInputBindingSpec("value", "synthetic_selector"),
                ),
            ),
        ),
        selectors={
            **DEFAULT_BINDING_SELECTORS,
            "synthetic_selector": lambda _step, _index, _local_outputs: "$problem.symbols.a",
        },
    )

    assert rules.bind("synthetic_method", step, index) == {
        "value": "$problem.symbols.a",
    }


def test_equal_length_ray_binding_uses_structured_canonical_facts() -> None:
    """射线上截等长点的 binding 应从 canonical fact payload 推断角色。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    # 本单测只验证角色推断；B/C/D 的实际坐标由前序 steps/runtime 提供。
    index.register("point:problem:B", "$problem.points.B", "Point", source="test")
    index.register("point:problem:C", "$problem.points.C", "Point", source="test")
    index.register("point:problem:D", "$problem.points.D", "Point", source="test")
    index.register("point:ii:G", "$question.ii.points.G", "PointRef", source="test")
    step = _step(
        scope_id="ii",
        step_id="construct_equal_length_ray_point",
        recipe_hint="equal_length_ray_point",
        goal_type="derive_equal_length_constructed_point",
        target="point:ii:G",
        reads=(
            "fact:ii:M_on_segment_BC",
            "fact:ii:N_on_ray_CD",
            "fact:ii:CN_eq_CM",
        ),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="equal_length_ray_point",
                input_bindings=(
                    MethodInputBindingSpec("anchor", "equal_length_ray:anchor"),
                    MethodInputBindingSpec("reference_point", "equal_length_ray:reference_point"),
                    MethodInputBindingSpec("ray_point", "equal_length_ray:ray_point"),
                    MethodInputBindingSpec("target", "equal_length_ray:target"),
                ),
            ),
        )
    )

    inputs = rules.bind("equal_length_ray_point", step, index)

    assert inputs["anchor"] == "$problem.points.C"
    assert inputs["reference_point"] == "$problem.points.B"
    assert inputs["ray_point"] == "$problem.points.D"
    assert inputs["target"] == "$question.ii.points.G"


def test_angle_sum_binding_uses_structured_canonical_fact_payload() -> None:
    """角和 binding 应读取 canonical fact 的 angle_terms，而不是解析 fact handle。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    index.register("point:problem:A", "$problem.points.A", "Point", source="test")
    index.register("point:problem:B", "$problem.points.B", "Point", source="test")
    index.register("point:problem:C", "$problem.points.C", "Point", source="test")
    index.register("point:problem:O", "$problem.points.O", "Point", source="test")
    index.register("point:i_2:F", "$subquestion.i_2.points.F", "PointRef", source="test")
    step = _step(
        scope_id="i_2",
        step_id="derive_equal_angle",
        recipe_hint="angle_sum_equal_angle_candidates",
        goal_type="derive_equal_angle",
        target="point:i_2:F",
        reads=("fact:i_2:angle_sum_CBE_ACO_45",),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="angle_sum_equal_angle_candidates",
                input_bindings=(
                    MethodInputBindingSpec("condition", "angle_sum:condition"),
                    MethodInputBindingSpec("x_axis_point", "angle_sum:x_axis_point"),
                    MethodInputBindingSpec("y_axis_point", "angle_sum:y_axis_point"),
                    MethodInputBindingSpec("reference_x_axis_point", "angle_sum:reference_x_axis_point"),
                    MethodInputBindingSpec("origin", "angle_sum:origin"),
                    MethodInputBindingSpec("target", "angle_sum:target"),
                ),
            ),
        )
    )

    inputs = rules.bind("angle_sum_equal_angle_candidates", step, index)

    assert inputs["condition"] == "$subquestion.i_2.conditions.angle_sum"
    assert inputs["x_axis_point"] == "$problem.points.B"
    assert inputs["y_axis_point"] == "$problem.points.C"
    assert inputs["reference_x_axis_point"] == "$problem.points.A"
    assert inputs["origin"] == "$problem.points.O"
    assert inputs["target"] == "$subquestion.i_2.points.F"


def test_angle_equality_binding_accepts_structured_payload() -> None:
    """等角 binding 支持 left_angle/right_angle 结构化 payload。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    fact_handle = "fact:i_2:target_reference_angles_equal"
    registry.fact_payloads[fact_handle] = {
        "handle": fact_handle,
        "type": "angle_equality",
        "left_angle": "OBF",
        "right_angle": "ACO",
    }
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=extract_question_goals(problem),
    )
    index.register("point:problem:A", "$problem.points.A", "Point", source="test")
    index.register("point:problem:B", "$problem.points.B", "Point", source="test")
    index.register("point:problem:C", "$problem.points.C", "Point", source="test")
    index.register("point:problem:O", "$problem.points.O", "Point", source="test")
    index.register("point:i_2:F", "$subquestion.i_2.points.F", "PointRef", source="test")
    index.register(fact_handle, "$subquestion.i_2.outputs.angle_equality", "AngleEquality", source="test")
    step = _step(
        scope_id="i_2",
        step_id="derive_axis_intercept",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_angle_constructed_point",
        target="point:i_2:F",
        reads=(fact_handle,),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="axis_intercept_from_equal_acute_angles",
                input_bindings=(
                    MethodInputBindingSpec("angle_equality", "angle_equality:fact"),
                    MethodInputBindingSpec("x_axis_point", "angle_equality:x_axis_point"),
                    MethodInputBindingSpec("y_axis_point", "angle_equality:y_axis_point"),
                    MethodInputBindingSpec("reference_x_axis_point", "angle_equality:reference_x_axis_point"),
                    MethodInputBindingSpec("origin", "angle_equality:origin"),
                    MethodInputBindingSpec("target", "angle_equality:target"),
                ),
            ),
        )
    )

    inputs = rules.bind("axis_intercept_from_equal_acute_angles", step, index)

    assert inputs["angle_equality"] == "$subquestion.i_2.outputs.angle_equality"
    assert inputs["x_axis_point"] == "$problem.points.B"
    assert inputs["y_axis_point"] == "$problem.points.C"
    assert inputs["reference_x_axis_point"] == "$problem.points.A"
    assert inputs["origin"] == "$problem.points.O"
    assert inputs["target"] == "$subquestion.i_2.points.F"


def test_axis_intercept_binding_uses_created_point_for_y_intercept_output() -> None:
    """y_intercept_F_coordinate 这类产物应优先绑定 creates 中的 F 点。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    fact_handle = "fact:i_2:angle_OBF_eq_ACO"
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=extract_question_goals(problem),
    )
    index.register("point:problem:A", "$problem.points.A", "Point", source="test")
    index.register("point:problem:B", "$problem.points.B", "Point", source="test")
    index.register("point:problem:C", "$problem.points.C", "Point", source="test")
    index.register("point:problem:O", "$problem.points.O", "Point", source="test")
    index.register("point:i_2:F", "$subquestion.i_2.points.F", "PointRef", source="test")
    index.register(fact_handle, "$subquestion.i_2.outputs.angle_equality", "AngleEquality", source="test")
    step = StepIntent(
        scope_id="i_2",
        step_id="derive_line_BE_y_intercept_F",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept",
        target="line BE y-intercept F",
        strategy="由等锐角求直线 BE 与 y 轴交点 F。",
        reads=(fact_handle, "point:problem:B", "point:problem:A", "point:problem:C", "point:problem:O"),
        creates=(
            CreatedEntity(
                handle="point:i_2:F",
                entity_type="point",
                valid_scope="i_2",
                description="直线 BE 与 y 轴的交点",
            ),
        ),
        produces=(
            ProducedFact(
                handle="fact:i_2:y_intercept_F_coordinate",
                valid_scope="i_2",
                description="F 点坐标",
                output_type="Point",
            ),
        ),
        reason="旧逻辑会把 semantic name 的第一个 token y 当成点名。",
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="axis_intercept_from_equal_acute_angles",
                input_bindings=(
                    MethodInputBindingSpec("angle_equality", "angle_equality:fact"),
                    MethodInputBindingSpec("x_axis_point", "angle_equality:x_axis_point"),
                    MethodInputBindingSpec("y_axis_point", "angle_equality:y_axis_point"),
                    MethodInputBindingSpec("reference_x_axis_point", "angle_equality:reference_x_axis_point"),
                    MethodInputBindingSpec("origin", "angle_equality:origin"),
                    MethodInputBindingSpec("target", "angle_equality:target"),
                ),
            ),
        )
    )

    inputs = rules.bind("axis_intercept_from_equal_acute_angles", step, index)

    assert inputs["target"] == "$subquestion.i_2.points.F"


def test_line_parabola_binding_uses_coordinate_fact_as_line_point() -> None:
    """直线第二点可由 reads 中的点坐标 fact 反推，不要求 LLM 额外 reads point handle。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=extract_question_goals(problem),
    )
    index.register("point:problem:B", "$problem.points.B", "Point", source="test")
    index.register("point:i_2:F", "$subquestion.i_2.points.F", "PointRef", source="test")
    index.register("fact:i_2:F_coordinate", "$subquestion.i_2.outputs.F_coordinate", "Point", source="test")
    index.register("point:i_2:E", "$subquestion.i_2.points.E", "PointRef", source="test")
    step = _step(
        scope_id="i_2",
        step_id="derive_E_coordinate",
        recipe_hint="line_parabola_second_intersection_point",
        goal_type="derive_curve_intersection_point",
        target="answer:i_2_E",
        reads=(
            "point:problem:B",
            "fact:i_2:F_coordinate",
            "point:i_2:E",
            "fact:i_2:E_on_parabola_with_x_m",
        ),
        produces=(
            ProducedFact(
                "answer:i_2_E",
                "i_2",
                "E 的坐标",
                output_type="Point",
            ),
        ),
    )
    rules = MethodBindingRuleRegistry(
        (
            MethodBindingRuleSpec(
                method_id="line_parabola_second_intersection_point",
                input_bindings=(
                    MethodInputBindingSpec("line_p1", "line_parabola:line_p1"),
                    MethodInputBindingSpec("line_p2", "line_parabola:line_p2"),
                    MethodInputBindingSpec("known_point", "line_parabola:known_point"),
                    MethodInputBindingSpec("target", "line_parabola:target"),
                ),
            ),
        )
    )

    inputs = rules.bind("line_parabola_second_intersection_point", step, index)

    assert inputs["line_p1"] == "$problem.points.B"
    assert inputs["line_p2"] == "$subquestion.i_2.outputs.F_coordinate"
    assert inputs["known_point"] == "$problem.points.B"
    assert inputs["target"] == "$subquestion.i_2.points.E"


def test_recipe_trial_executor_diagnostic_reports_blocker_and_skipped_steps() -> None:
    """执行诊断应保留首个 blocker 与后续 skipped step，而不是只抛异常文本。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = _heping_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    failing_step = _step(
        scope_id="i_2",
        step_id="derive_E_point",
        recipe_hint="line_parabola_second_intersection_point",
        goal_type="derive_curve_intersection_point",
        target="answer:i_2_E",
        reads=(
            "point:problem:B",
            "function:problem:parabola",
            "point:i_2:E",
            "fact:i_2:E_on_parabola_with_x_m",
        ),
        produces=(
            ProducedFact("answer:i_2_E", "i_2", "E 点坐标", output_type="Point"),
        ),
    )
    later_step = _step(
        scope_id="ii",
        step_id="derive_path_minimum",
        recipe_hint="equal_length_ray_path_reduction",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        reads=("fact:ii:path_minimum_target",),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "路径最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )

    output, diagnostic, effective = RecipeTrialExecutor().diagnose(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i_2", label="第（Ⅰ）②问", steps=(failing_step,)),
                StepIntentScope(scope_id="ii", label="第（Ⅱ）问", steps=(later_step,)),
            )
        ),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is None
    assert effective.steps[0].step_id == "derive_E_point"
    assert diagnostic.ok is False
    assert diagnostic.first_blocker is not None
    assert diagnostic.first_blocker.step_id == "derive_E_point"
    assert diagnostic.skipped_steps[0].step_id == "derive_path_minimum"


def test_square_side_binding_accepts_coordinate_fact_reads_for_side_endpoints() -> None:
    """正方形邻顶点 method 应能从已读坐标 fact 反推出边端点实体。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="i_1",
                label="第（Ⅰ）①问",
                steps=(
                    _step(
                        scope_id="i_1",
                        step_id="derive_parabola_i1",
                        recipe_hint="quadratic_from_constraints",
                        goal_type="derive_parabola",
                        target="fact:i:parabola_expression",
                        reads=(
                            "symbol:problem:b",
                            "symbol:problem:c",
                            "fact:i:b_value",
                            "fact:i:c_value",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i:parabola_expression",
                                "i",
                                "第（Ⅰ）问抛物线解析式",
                                output_type="Parabola",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_1",
                        step_id="derive_left_intercept_i1",
                        recipe_hint="quadratic_x_axis_intercept_point",
                        goal_type="derive_x_axis_intercept_point",
                        target="answer:i_1.A",
                        reads=(
                            "fact:i:parabola_expression",
                            "point:problem:A",
                            "fact:problem:A_on_parabola",
                        ),
                        produces=(
                            ProducedFact("answer:i_1.A", "i_1", "A 点坐标", output_type="Point"),
                            ProducedFact("fact:i:A_coordinate", "i", "A 坐标后续可用", output_type="Point"),
                        ),
                    ),
                ),
            ),
            StepIntentScope(
                scope_id="i_2",
                label="第（Ⅰ）②问",
                steps=(
                    _step(
                        scope_id="i_2",
                        step_id="parameterize_point_E_i2",
                        recipe_hint="quadratic_axis_parameterized_point",
                        goal_type="parameterize_point_on_quadratic_axis",
                        target="fact:i_2:E_parametric_coordinate",
                        reads=(
                            "fact:i:parabola_expression",
                            "point:i_2:E",
                            "fact:i_2:E_on_axis",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:E_parametric_coordinate",
                                "i_2",
                                "E 坐标表达式",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_2",
                        step_id="construct_G_from_square_i2",
                        recipe_hint="square_adjacent_vertex_from_side",
                        goal_type="derive_square_adjacent_vertex_from_side",
                        target="fact:i_2:G_coord_expr",
                        reads=(
                            "fact:i:A_coordinate",
                            "fact:i_2:E_parametric_coordinate",
                            "point:i_2:G",
                            "fact:i_2:square_AEKG",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:G_coord_expr",
                                "i_2",
                                "G 坐标表达式",
                                output_type="Point",
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    assert [item.step_id for item in diagnostic.accepted_prefix][-1] == "construct_G_from_square_i2"


def test_square_curve_candidates_parabola_prep_ignores_curve_point_condition() -> None:
    """临时 Parabola prep 不应把当前待解曲线点条件误当作求抛物线约束。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="i_1",
                label="第（Ⅰ）①问",
                steps=(
                    _step(
                        scope_id="i_1",
                        step_id="derive_A_left_intercept",
                        recipe_hint="quadratic_x_axis_intercept_point",
                        goal_type="derive_x_axis_intercept_point",
                        target="answer:i_1.A",
                        reads=(
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "point:problem:A",
                            "fact:problem:A_on_parabola",
                        ),
                        produces=(
                            ProducedFact("answer:i_1.A", "i_1", "A 点坐标", output_type="Point"),
                            ProducedFact("fact:i:A_coordinate", "i", "A 坐标后续可用", output_type="Point"),
                        ),
                    ),
                ),
            ),
            StepIntentScope(
                scope_id="i_2",
                label="第（Ⅰ）②问",
                steps=(
                    _step(
                        scope_id="i_2",
                        step_id="parameterize_E_i2",
                        recipe_hint="quadratic_axis_parameterized_point",
                        goal_type="parameterize_point_on_quadratic_axis",
                        target="fact:i_2:E_parametric_coordinate",
                        reads=(
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "point:i_2:E",
                            "fact:i_2:E_on_axis",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:E_parametric_coordinate",
                                "i_2",
                                "E 坐标表达式",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_2",
                        step_id="construct_G_i2",
                        recipe_hint="square_adjacent_vertex_from_side",
                        goal_type="derive_square_adjacent_vertex_from_side",
                        target="fact:i_2:G_parametric_coordinate",
                        reads=(
                            "fact:i:A_coordinate",
                            "fact:i_2:E_parametric_coordinate",
                            "point:i_2:G",
                            "fact:i_2:square_AEKG",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:i_2:G_parametric_coordinate",
                                "i_2",
                                "G 坐标表达式",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="i_2",
                        step_id="solve_E_candidates",
                        recipe_hint="point_candidates_from_curve_point_condition",
                        goal_type="derive_point_candidates_from_curve_point_condition",
                        target="answer:i_2.E",
                        reads=(
                            "fact:i_2:E_parametric_coordinate",
                            "fact:i_2:G_parametric_coordinate",
                            "function:problem:parabola",
                            "fact:i:b_value",
                            "fact:i:c_value",
                            "fact:i_2:G_on_parabola",
                        ),
                        produces=(
                            ProducedFact(
                                "answer:i_2.E",
                                "i_2",
                                "E 的候选坐标",
                                output_type="PointList",
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    assert diagnostic.accepted_prefix[-1].step_id == "solve_E_candidates"


def test_curve_condition_uses_visible_target_point_state_when_not_explicitly_read() -> None:
    """曲线条件候选 method 不应要求 LLM 同时读取目标实体和坐标 fact。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _heping_ermo_i2_curve_condition_draft(
        candidate_reads=(
            "point:i_2:E",
            "fact:i_2:G_coordinate_expr",
            "fact:i:parabola_expression",
            "fact:i_2:G_on_parabola",
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    assert diagnostic.accepted_prefix[-1].step_id == "derive_E_candidates_i2"
    assert "ambiguous_curve_condition_point_state" not in json.dumps(
        diagnostic.to_payload(),
        ensure_ascii=False,
    )


def test_curve_condition_uses_prefix_target_state_even_without_entity_read() -> None:
    """target answer 已指向 E 时，缺少 point:E read 也可用 prefix 中唯一 E 状态补位。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _heping_ermo_i2_curve_condition_draft(
        candidate_reads=(
            "fact:i_2:G_coordinate_expr",
            "fact:i:parabola_expression",
            "fact:i_2:G_on_parabola",
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    assert diagnostic.accepted_prefix[-1].step_id == "derive_E_candidates_i2"
    assert any(
        fill.resolved_handle == "fact:i_2:E_parametric_coordinate"
        and fill.required_type == "Point"
        for fill in diagnostic.applied_fills
    )


def test_curve_condition_prefers_computed_point_fact_over_entity_read() -> None:
    """同时读取 point entity 与同名 computed fact 时，应优先 computed fact。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _heping_ermo_i2_curve_condition_draft(
        candidate_reads=(
            "point:i_2:E",
            "fact:i_2:E_parametric_coordinate",
            "fact:i_2:G_coordinate_expr",
            "fact:i:parabola_expression",
            "fact:i_2:G_on_parabola",
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    assert diagnostic.accepted_prefix[-1].step_id == "derive_E_candidates_i2"
    assert "ambiguous_curve_condition_point_state" not in json.dumps(
        diagnostic.to_payload(),
        ensure_ascii=False,
    )


def test_binding_index_prefers_current_scope_point_when_names_repeat() -> None:
    """同名点出现在 sibling scope 时，binding 应优先当前 step scope。"""
    problem = _heping_ermo_problem()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    step = _step(
        scope_id="ii",
        step_id="derive_G_from_AE_ii",
        recipe_hint="square_adjacent_vertex_from_side",
        goal_type="derive_square_adjacent_vertex_from_side",
        target="fact:ii:G_coordinate_expr",
        produces=(
            ProducedFact(
                "fact:ii:G_coordinate_expr",
                "ii",
                "点 G 的坐标表达式",
                output_type="Point",
            ),
        ),
    )

    assert index.point_handle_by_name("G", step=step) == "point:ii:G"


def test_binding_index_prefers_visible_current_scope_fact_when_type_repeats() -> None:
    """同类型 fact 出现在 sibling scope 时，binding 不应读不可见 sibling。"""
    problem = _heping_ermo_problem()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    step = _step(
        scope_id="ii",
        step_id="derive_G_from_AE_ii",
        recipe_hint="square_adjacent_vertex_from_side",
        goal_type="derive_square_adjacent_vertex_from_side",
        target="fact:ii:G_coordinate_expr",
        reads=(
            "fact:ii:A_coordinate_value",
            "fact:ii:E_coordinate_param",
        ),
        produces=(
            ProducedFact(
                "fact:ii:G_coordinate_expr",
                "ii",
                "点 G 的坐标表达式",
                output_type="Point",
            ),
        ),
    )

    assert index.fact_handle_by_type("square", step=step) == "fact:ii:square_AEKG"


def test_square_path_dimension_reduction_exposes_planner_insight() -> None:
    """路径降维执行后应把真实 moving point 暴露给 repair loop。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _single_scope_draft(
        _step(
            scope_id="ii",
            step_id="reduce_square_path_dimension",
            recipe_hint="square_path_dimension_reduction",
            goal_type="reduce_path_expression",
            target="fact:ii:reduced_path",
            reads=(
                "fact:ii:square_AEKG",
                "fact:ii:F_midpoint_of_AE",
                "fact:ii:H_square_diagonal_intersection",
                "fact:ii:path_minimum_target",
            ),
            produces=(
                ProducedFact(
                    "fact:ii:reduced_path",
                    "ii",
                    "降维后的等价单动点路径",
                    output_type="PathTransformation",
                ),
            ),
        ),
        scope_id="ii",
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    insight = diagnostic.planner_insights[0]
    assert insight.produced_handle == "fact:ii:reduced_path"
    assert insight.output_type == "PathTransformation"
    assert insight.facts["moving_point"] == "point:ii:G"
    assert insight.facts["fixed_points"] == ["point:ii:A", "point:problem:M"]
    assert insight.facts["transformed_path"] == "AG+MG"
    assert "next_locus_step" not in insight.facts
    assert "moving_point=point:ii:G" in insight.repair_note

    payload = StepIntentRepairAttempt(
        attempt=1,
        effective_draft=None,
        diagnostic=diagnostic,
        repair_instruction="请从 insight 继续规划",
    ).to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "planner_insights" in serialized
    assert "$problem" not in serialized
    assert "$question" not in serialized
    assert "$subquestion" not in serialized


def test_path_transformation_insight_recommends_locus_step_when_moving_point_state_exists() -> None:
    """若已知 moving point 参数化坐标，降维 insight 应推荐先求轨迹线。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii",
                label="第（Ⅱ）问",
                steps=(
                    _step(
                        scope_id="ii",
                        step_id="derive_parabola_ii",
                        recipe_hint="quadratic_from_constraints",
                        goal_type="derive_parabola",
                        target="fact:ii:parabola_expression",
                        reads=("function:problem:parabola", "fact:ii:A_coordinate_value"),
                        produces=(
                            ProducedFact(
                                "fact:ii:parabola_expression",
                                "ii",
                                "第（Ⅱ）问抛物线",
                                output_type="Parabola",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="ii",
                        step_id="parameterize_E_ii",
                        recipe_hint="quadratic_axis_parameterized_point",
                        goal_type="derive_parameterized_point",
                        target="fact:ii:E_parametric_coordinate",
                        reads=("fact:ii:parabola_expression", "point:ii:E", "fact:ii:E_on_axis"),
                        produces=(
                            ProducedFact(
                                "fact:ii:E_parametric_coordinate",
                                "ii",
                                "E 的参数化坐标",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="ii",
                        step_id="derive_G_ii",
                        recipe_hint="square_adjacent_vertex_from_side",
                        goal_type="derive_square_adjacent_vertex",
                        target="fact:ii:G_parametric_coordinate",
                        reads=(
                            "fact:ii:A_coordinate_value",
                            "fact:ii:E_parametric_coordinate",
                            "fact:ii:square_AEKG",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:ii:G_parametric_coordinate",
                                "ii",
                                "G 的参数化坐标",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="ii",
                        step_id="reduce_square_path_ii",
                        recipe_hint="square_path_dimension_reduction",
                        goal_type="reduce_square_path_dimension",
                        target="fact:ii:reduced_path",
                        reads=(
                            "fact:ii:square_AEKG",
                            "fact:ii:F_midpoint_of_AE",
                            "fact:ii:H_square_diagonal_intersection",
                            "fact:ii:path_minimum_target",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:ii:reduced_path",
                                "ii",
                                "降维后的路径",
                                output_type="PathTransformation",
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    insight = diagnostic.planner_insights[0]
    next_locus = insight.facts["next_locus_step"]
    assert next_locus == {
        "recommended_next_capability": "parameterized_point_locus_line",
        "recommended_reads": ["fact:ii:G_parametric_coordinate"],
        "recommended_produces": "fact:ii:G_locus_line",
        "before_capability": "broken_path_straightening_minimum_expression",
    }
    assert "parameterized_point_locus_line" in insight.repair_note


def test_normalizer_drops_square_pre_reduction_point_utility_step() -> None:
    """降维前的 midpoint/center 坐标 utility step 不应阻止 square reduction 执行。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    f_utility = _step(
        scope_id="ii",
        step_id="derive_F_coordinate_ii",
        recipe_hint=None,
        goal_type="derive_midpoint_coordinate",
        target="fact:ii:F_coordinate_expr",
        reads=(
            "point:ii:A",
            "fact:ii:A_coordinate_value",
            "fact:ii:E_param_coord",
            "point:ii:F",
            "fact:ii:F_midpoint_of_AE",
        ),
        produces=(
            ProducedFact(
                "fact:ii:F_coordinate_expr",
                "ii",
                "点 F 的坐标表达式",
                output_type="Point",
            ),
        ),
    )
    reduction = _step(
        scope_id="ii",
        step_id="reduce_path_ii",
        recipe_hint="square_path_dimension_reduction",
        goal_type="reduce_square_path_dimension",
        target="fact:ii:reduced_path_transformation",
        reads=(
            "fact:ii:square_AEKG",
            "fact:ii:F_midpoint_of_AE",
            "fact:ii:H_square_diagonal_intersection",
            "fact:ii:path_minimum_target",
            "fact:ii:F_coordinate_expr",
        ),
        produces=(
            ProducedFact(
                "fact:ii:reduced_path_transformation",
                "ii",
                "降维后的路径",
                output_type="PathTransformation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(f_utility, reduction, scope_id="ii"),
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    assert [step.step_id for step in normalized.steps] == ["reduce_path_ii"]
    assert "fact:ii:F_coordinate_expr" not in normalized.steps[0].reads
    assert [action.action for action in report.actions] == [
        "drop_square_pre_reduction_point_utility_step"
    ]

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        normalized,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )
    assert output is not None
    assert diagnostic.ok is True
    assert diagnostic.planner_insights[0].facts["moving_point"] == "point:ii:G"


def test_normalizer_drops_square_pre_reduction_utility_when_reduction_does_not_read_output() -> None:
    """结构点坐标 utility 即使没被 reduction 显式读取，也不应阻止先降维。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    f_utility = _step(
        scope_id="ii",
        step_id="derive_F_coordinate_expr",
        recipe_hint=None,
        goal_type="derive_midpoint_coordinate",
        target="fact:ii:F_coordinate_expr",
        reads=(
            "point:ii:A",
            "fact:ii:A_coordinate_value",
            "fact:ii:E_param_coord",
            "point:ii:F",
            "fact:ii:F_midpoint_of_AE",
        ),
        produces=(
            ProducedFact(
                "fact:ii:F_coordinate_expr",
                "ii",
                "点 F 的坐标表达式",
                output_type="Point",
            ),
        ),
    )
    reduction = _step(
        scope_id="ii",
        step_id="reduce_square_path",
        recipe_hint="square_path_dimension_reduction",
        goal_type="reduce_square_path_dimension",
        target="fact:ii:reduced_path",
        reads=(
            "fact:ii:square_AEKG",
            "fact:ii:F_midpoint_of_AE",
            "fact:ii:H_square_diagonal_intersection",
            "fact:ii:path_minimum_target",
        ),
        produces=(
            ProducedFact(
                "fact:ii:reduced_path",
                "ii",
                "降维后的路径",
                output_type="PathTransformation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(f_utility, reduction, scope_id="ii"),
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    assert [step.step_id for step in normalized.steps] == ["reduce_square_path"]
    assert any(
        action.action == "drop_square_pre_reduction_point_utility_step"
        for action in report.actions
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        normalized,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )
    assert output is not None
    assert diagnostic.ok is True
    assert diagnostic.planner_insights[0].facts["moving_point"] == "point:ii:G"


def test_normalizer_adds_broken_path_minimum_endpoint_outputs() -> None:
    """直接使用将军饮马最值 recipe 时，应自动暴露最短线段端点。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    step = _step(
        scope_id="ii",
        step_id="compute_minimum_expression",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        reads=("fact:ii:reduced_path", "fact:ii:moving_point_locus"),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(step, scope_id="ii"),
        family_spec=QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        question_goals=extract_question_goals(_heping_ermo_problem()),
        handle_registry=registry,
    )

    handles = {item.handle for item in normalized.steps[0].produces}
    assert handles >= {
        "fact:ii:path_minimum_expression",
        "fact:ii:path_minimum_point_1",
        "fact:ii:path_minimum_point_2",
    }
    assert [action.action for action in report.actions] == [
        "add_broken_path_minimum_endpoint_outputs"
    ]


def test_broken_path_minimum_infers_fixed_points_from_square_path_context() -> None:
    """将军饮马 recipe 少读固定点实体时，可从降维路径结构推断端点。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    payload = json.loads(HEPING_ERMO_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    for scope in payload["scopes"]:
        if scope["scope_id"] != "ii":
            continue
        for step in scope["steps"]:
            if step.get("recipe_hint") == "broken_path_straightening_minimum_expression":
                step["reads"] = [
                    handle for handle in step["reads"]
                    if handle not in {"point:ii:A", "point:problem:M"}
                ]
    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    assert any(
        insight.output_type == "StraighteningMinimum"
        and insight.facts["minimum_points"] == [
            "fact:ii:path_minimum_point_1",
            "fact:ii:path_minimum_point_2",
        ]
        for insight in diagnostic.planner_insights
    )


def test_broken_path_minimum_reuses_prior_point_state_when_reads_omit_fixed_points() -> None:
    """LLM 只读降维路径和轨迹时，应复用前序点坐标状态，不重新 prepare 覆盖。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    payload = json.loads(HEPING_ERMO_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    for scope in payload["scopes"]:
        if scope["scope_id"] != "ii":
            continue
        for step in scope["steps"]:
            if step.get("step_id") == "derive_axis_point_M":
                step["produces"][0]["handle"] = "fact:ii:M_coordinate"
            if step.get("recipe_hint") == "broken_path_straightening_minimum_expression":
                step["reads"] = [
                    "fact:ii:square_path_transformation",
                    "fact:ii:G_locus_line",
                ]
    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    minimum_plan = next(
        plan
        for plan in output.step_plans
        if plan.step_id == "derive_path_minimum_expr"
    )
    assert all(
        invocation.method_id != "quadratic_axis_x_intercept_point"
        for invocation in minimum_plan.invocations
    )
    assert "$question.ii.outputs.M_coordinate" not in minimum_plan.promote_outputs.values()


def test_parameter_value_handle_accepts_bound_parameter_values_fact() -> None:
    """ParameterValue 绑定比 handle 后缀更可信，parameter_values 也可被识别。"""
    problem = _heping_ermo_problem()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem()),
        question_goals=extract_question_goals(problem),
    )
    index.register(
        "fact:ii:parameter_values",
        "$question.ii.outputs.parameter_values",
        "ParameterValue",
        source="step:solve_parameters",
    )
    step = _step(
        scope_id="ii",
        step_id="evaluate_E_coordinate",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="derive_extremal_point",
        target="answer:ii.E",
        reads=("fact:ii:E_parametric", "fact:ii:parameter_values"),
    )

    assert _parameter_value_handle(step, index) == "fact:ii:parameter_values"


def test_final_point_recovery_blocker_uses_specific_repair_instruction() -> None:
    """误用 evaluate_point_at_parameter 直接收尾时，应提示先求 moving point 再恢复答案点。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    step = _step(
        scope_id="ii",
        step_id="evaluate_E_coordinate",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="derive_extremal_point",
        target="answer:ii.E",
        reads=("fact:ii:E_parametric", "fact:ii:parameter_values"),
        produces=(ProducedFact("answer:ii.E", "ii", "最终 E 点", output_type="Point"),),
    )
    insight = StepIntentPlannerInsight(
        step_id="reduce_square_path",
        scope_id="ii",
        produced_handle="fact:ii:reduced_path",
        output_type="PathTransformation",
        facts={"moving_point": "point:ii:G"},
        repair_note="moving point is point:ii:G",
    )

    error = _candidate_error_for_exception(
        step=step,
        capability_id="evaluate_point_at_parameter",
        exc=ValueError("missing required input: parameter"),
        planner_insights=(insight,),
        handle_registry=registry,
    )
    assert "final_point_requires_square_recovery" in error

    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        planner_insights=(insight,),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="evaluate_E_coordinate",
                scope_id="ii",
                stage="recipe_trial",
                code="final_point_requires_square_recovery",
                message=error,
                capability_errors=(error,),
            ),
        ),
    )
    summary = RepairFeedbackBuilder(diagnostic=diagnostic).build()
    instruction = _repair_instruction(diagnostic, repair_summary=summary)
    assert "line_locus_minimum_point" in instruction
    assert "square_adjacent_vertex_from_side" in instruction
    assert "path_minimum_point_1/2" in instruction


def test_normalizer_folds_broken_path_internal_method_sequence() -> None:
    """LLM 拆开的将军饮马内部 method 应折叠成对外 recipe step。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    candidate_step = _step(
        scope_id="ii",
        step_id="generate_straightening_candidates",
        recipe_hint="broken_path_straightening_candidates",
        goal_type="derive_path_straightening_candidates",
        target="fact:ii:candidates",
        reads=("fact:ii:reduced_path",),
        produces=(
            ProducedFact("fact:ii:candidates", "ii", "拉直候选", output_type="StraighteningCandidate"),
        ),
    )
    select_step = _step(
        scope_id="ii",
        step_id="select_straightening_candidate",
        recipe_hint="select_straightening_candidate",
        goal_type="select_straightening_candidate",
        target="fact:ii:selected_candidate",
        reads=("fact:ii:candidates",),
        produces=(
            ProducedFact(
                "fact:ii:selected_candidate",
                "ii",
                "选定拉直方案",
                output_type="StraighteningCandidate",
            ),
        ),
    )
    distance_step = _step(
        scope_id="ii",
        step_id="compute_minimum_expr",
        recipe_hint="distance_between_points",
        goal_type="compute_distance_between_points",
        target="fact:ii:minimum_expr",
        reads=(
            "fact:ii:selected_candidate",
            "fact:ii:G_locus_line",
            "point:ii:A",
            "point:problem:M",
        ),
        produces=(
            ProducedFact("fact:ii:minimum_expr", "ii", "最小值表达式", output_type="MinimumExpression"),
        ),
    )
    final_step = _step(
        scope_id="ii",
        step_id="find_E_final",
        recipe_hint="line_locus_minimum_point",
        goal_type="derive_line_locus_minimum_point",
        target="answer:ii.E",
        reads=("fact:ii:selected_candidate", "fact:ii:G_locus_line"),
        produces=(ProducedFact("answer:ii.E", "ii", "E 点坐标", output_type="Point"),),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(candidate_step, select_step, distance_step, final_step, scope_id="ii"),
        family_spec=QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        question_goals=extract_question_goals(_heping_ermo_problem()),
        handle_registry=registry,
    )

    assert [step.step_id for step in normalized.steps] == ["compute_minimum_expr", "find_E_final"]
    folded = normalized.steps[0]
    assert folded.recipe_hint == "broken_path_straightening_minimum_expression"
    assert {item.handle for item in folded.produces} >= {
        "fact:ii:minimum_expr",
        "fact:ii:path_minimum_point_1",
        "fact:ii:path_minimum_point_2",
    }
    assert "fact:ii:selected_candidate" not in normalized.steps[1].reads
    assert "fact:ii:path_minimum_point_1" in normalized.steps[1].reads
    assert "fact:ii:path_minimum_point_2" in normalized.steps[1].reads
    assert any(action.action == "fold_broken_path_internal_sequence" for action in report.actions)


def test_recipe_trial_keeps_accepted_prefix_when_later_candidate_resolution_fails() -> None:
    """后续 step candidate 失败时，前面已可执行步骤仍应进入 accepted prefix。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    valid_step = _step(
        scope_id="i_1",
        step_id="derive_parabola_i1",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:i:parabola_expression",
        reads=(
            "symbol:problem:b",
            "symbol:problem:c",
            "fact:i:b_value",
            "fact:i:c_value",
        ),
        produces=(
            ProducedFact("fact:i:parabola_expression", "i", "第（Ⅰ）问抛物线", output_type="Parabola"),
        ),
    )
    bad_step = _step(
        scope_id="ii",
        step_id="unsupported_expression_utility",
        recipe_hint=None,
        goal_type="derive_utility_expression",
        target="fact:ii:free_expression",
        reads=("function:problem:parabola",),
        produces=(
            ProducedFact("fact:ii:free_expression", "ii", "自由中间表达式", output_type="Expression"),
        ),
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i_1", label="第（Ⅰ）①问", steps=(valid_step,)),
                StepIntentScope(scope_id="ii", label="第（Ⅱ）问", steps=(bad_step,)),
            )
        ),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is None
    assert [item.step_id for item in diagnostic.accepted_prefix] == ["derive_parabola_i1"]
    assert diagnostic.first_blocker is not None
    assert diagnostic.first_blocker.step_id == "unsupported_expression_utility"
    assert diagnostic.first_blocker.stage == "candidate_resolution"


def test_step_intent_repair_attempt_payload_is_safe() -> None:
    """previous_attempts 不应包含 RuntimePath、traceback 或 expected answer。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="derive_B_coordinate",
                scope_id="i",
                capability_id="quadratic_x_axis_intercept_point",
                method_ids=("quadratic_x_axis_intercept_point",),
                produced_handles=("fact:i:B_coordinate",),
            ),
        ),
        applied_fills=(
            StepIntentAppliedFill(
                step_id="derive_E_point",
                scope_id="i_2",
                input_handle="point:problem:B",
                required_type="Point",
                resolved_handle="fact:i:B_coordinate",
                reason="unique_visible_entity_state",
            ),
        ),
        preflight_issues=(
            StepIntentPreflightIssue(
                step_id="derive_A_point",
                scope_id="i_1",
                category="likely_downstream_issue",
                code="missing_explicit_parabola_state",
                message="后续 step 缺少显式 Parabola fact。",
                repair="先产生 fact:i:parabola_expression，再让后续 step 读取。",
            ),
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="derive_E_point",
                scope_id="i_2",
                stage="recipe_trial",
                code="missing_line_parabola_inputs",
                message="缺少可确定直线的另一个点",
            ),
        ),
    )
    repair = StepIntentRepairAttempt(
        attempt=1,
        effective_draft=_single_scope_draft(
            _step(
                scope_id="i_2",
                step_id="derive_E_point",
                recipe_hint="line_parabola_second_intersection_point",
                goal_type="derive_curve_intersection_point",
                target="answer:i_2_E",
            ),
            scope_id="i_2",
        ).to_payload(),
        diagnostic=diagnostic,
        repair_summary=RepairFeedbackBuilder(
            diagnostic=diagnostic,
            errors=("recipe_trial_step_failed:derive_E_point",),
        ).build(),
        repair_instruction="从 derive_E_point 开始修复。",
        errors=("recipe_trial_step_failed:derive_E_point",),
    )

    serialized = json.dumps(repair.to_payload(), ensure_ascii=False)

    assert "effective_draft" in serialized
    assert "repair_summary" in serialized
    assert "point:problem:B" in serialized
    assert "fact:i:B_coordinate" in serialized
    assert "preflight_issues" in serialized
    assert "missing_explicit_parabola_state" in serialized
    assert "$problem" not in serialized
    assert "$question" not in serialized
    assert "traceback" not in serialized.lower()
    assert "expected" not in serialized.lower()


def test_repair_feedback_builder_summarizes_square_side_endpoint_blocker() -> None:
    """正方形边端点绑定错误应提示不要新增 segment/utility step。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        accepted_prefix=(
            StepIntentAcceptedStep(
                step_id="parameterize_E_i2",
                scope_id="i_2",
                capability_id="quadratic_axis_parameterized_point",
            ),
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="construct_G_i2",
                scope_id="i_2",
                stage="recipe_trial",
                code="recipe_trial_step_failed",
                message="square_adjacent_vertex_from_side failed",
                capability_errors=(
                    "square_adjacent_vertex_from_side: square_side_end_not_found: step=construct_G_i2",
                ),
            ),
        ),
    )

    registry = RepairHintRegistry((
        RepairHintSpec(
            code="square_side_end_not_found",
            message="正方形边端点绑定失败；通常不需要新增 segment。",
            next_actions=(
                "保持 `square_adjacent_vertex_from_side`；不要新增 `segment:*` 或只为端点绑定服务的 utility step。",
            ),
            do_not=("不要新增 `segment:*` 只为让正方形边端点绑定通过。",),
            applies_to=("method:square_adjacent_vertex_from_side",),
        ),
    ))
    summary = RepairFeedbackBuilder(
        diagnostic=diagnostic,
        hint_registry=registry,
    ).build()
    serialized = json.dumps(summary, ensure_ascii=False)

    assert summary["frozen_prefix"][0]["step_id"] == "parameterize_E_i2"
    assert summary["current_blocker"]["step_id"] == "construct_G_i2"
    assert "square_side_end_not_found" not in summary["current_blocker"]["message"]
    assert "不要新增 `segment:*`" in serialized
    assert "square_adjacent_vertex_from_side" in serialized
    assert "$problem" not in serialized
    assert "$question" not in serialized
    assert "traceback" not in serialized.lower()
    assert "expected" not in serialized.lower()


def test_repair_hint_registry_prefers_method_hint_over_generic() -> None:
    """hint 查找应按 method/capability 命中优先于 generic。"""
    registry = RepairHintRegistry((
        RepairHintSpec(
            code="square_side_end_not_found",
            message="generic square side message",
            applies_to=("generic",),
        ),
        RepairHintSpec(
            code="square_side_end_not_found",
            message="method-specific square side message",
            applies_to=("method:square_adjacent_vertex_from_side",),
        ),
    ))
    blocker = StepIntentExecutionBlocker(
        step_id="construct_G_i2",
        scope_id="i_2",
        stage="recipe_trial",
        code="recipe_trial_step_failed",
        message="square_adjacent_vertex_from_side failed",
        capability_errors=(
            "square_adjacent_vertex_from_side: square_side_end_not_found: step=construct_G_i2",
        ),
    )

    hint = registry.find(blocker)

    assert hint is not None
    assert hint.message == "method-specific square side message"


def test_default_repair_hint_registry_loads_method_hints() -> None:
    """method Python SPEC 中的 repair_hints 应进入默认 registry。"""
    blocker = StepIntentExecutionBlocker(
        step_id="recover_E",
        scope_id="ii",
        stage="recipe_trial",
        code="final_point_requires_square_recovery",
        message="evaluate_point_at_parameter failed",
        capability_errors=("final_point_requires_square_recovery: evaluate_point_at_parameter",),
    )

    hint = RepairHintRegistry.default().find(blocker)

    assert hint is not None
    assert "line_locus_minimum_point" in " ".join(hint.next_actions)
    assert "square_adjacent_vertex_from_side" in " ".join(hint.next_actions)


def test_repair_feedback_builder_merges_path_and_straightening_insights() -> None:
    """PathTransformation 和将军饮马 insight 应同时进入 planner_state。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        planner_insights=(
            StepIntentPlannerInsight(
                step_id="reduce_path",
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
                step_id="compute_minimum",
                scope_id="ii",
                produced_handle="fact:ii:path_minimum_expression",
                output_type="StraighteningMinimum",
                facts={
                    "minimum_points": [
                        "fact:ii:straightened_endpoint_1",
                        "fact:ii:path_minimum_point_1",
                        "fact:ii:path_minimum_point_2",
                    ],
                    "next_method": "line_locus_minimum_point",
                },
                repair_note="use line_locus_minimum_point",
            ),
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="recover_E",
                scope_id="ii",
                stage="recipe_trial",
                code="final_point_requires_square_recovery",
                message="final_point_requires_square_recovery",
                capability_errors=("final_point_requires_square_recovery",),
            ),
        ),
    )

    summary = RepairFeedbackBuilder(diagnostic=diagnostic).build()

    assert summary["planner_state"]["reduced_path"]["moving_point"] == "point:ii:G"
    assert summary["planner_state"]["straightening_minimum"]["minimum_points"] == [
        "fact:ii:path_minimum_point_1",
        "fact:ii:path_minimum_point_2",
    ]
    assert any("line_locus_minimum_point" in action for action in summary["next_actions"])
    assert any("square_adjacent_vertex_from_side" in action for action in summary["next_actions"])


def test_repair_feedback_builder_guides_missing_locus_line_before_straightening() -> None:
    """将军饮马缺 Line 时，应引导先求 moving point 轨迹线。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
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
                    "next_locus_step": {
                        "recommended_next_capability": "parameterized_point_locus_line",
                        "recommended_reads": ["fact:ii:G_parametric_coordinate"],
                        "recommended_produces": "fact:ii:G_locus_line",
                        "before_capability": "broken_path_straightening_minimum_expression",
                    },
                },
                repair_note="先求 G 的轨迹线。",
            ),
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id="compute_path_minimum_expression",
                scope_id="ii",
                stage="recipe_trial",
                code="recipe_trial_step_failed",
                message="missing moving locus line",
                capability_errors=(
                    "broken_path_straightening_minimum_expression: "
                    "binding_type_not_found: step=compute_path_minimum_expression, type=Line",
                ),
                capability_id="broken_path_straightening_minimum_expression",
                missing_runtime_type="Line",
            ),
        ),
    )

    summary = RepairFeedbackBuilder(diagnostic=diagnostic).build()
    serialized = json.dumps(summary, ensure_ascii=False)

    assert summary["current_blocker"]["message"] == "将军饮马 recipe 缺少动点轨迹 Line；应先根据降维后的 moving point 求轨迹线。"
    assert summary["planner_state"]["reduced_path"]["next_locus_step"]["recommended_produces"] == "fact:ii:G_locus_line"
    assert "parameterized_point_locus_line" in serialized
    assert "fact:ii:G_parametric_coordinate" in serialized
    assert "fact:ii:G_locus_line" in serialized
    assert "broken_path_straightening_minimum_expression" in serialized
    assert "$problem" not in serialized
    assert "$question" not in serialized
    assert "traceback" not in serialized.lower()
    assert "expected" not in serialized.lower()


def test_repair_feedback_builder_marks_code_fillable_preflight_as_already_handled() -> None:
    """code_fillable preflight 是系统补位，不应变成 must-fix。"""
    diagnostic = StepIntentExecutionDiagnostic(
        ok=False,
        preflight_issues=(
            StepIntentPreflightIssue(
                step_id="derive_A_left_intercept",
                scope_id="i_1",
                category="code_fillable",
                code="missing_explicit_parabola_state",
                message="缺少显式 Parabola state",
                repair="可临时 prep Parabola",
            ),
        ),
    )

    summary = RepairFeedbackBuilder(diagnostic=diagnostic).build()

    assert summary["already_handled"][0]["code"] == "missing_explicit_parabola_state"
    assert summary["warnings"] == []
    assert any("already_handled" in item for item in summary["do_not"])


def test_repair_instruction_prefers_repair_summary() -> None:
    """repair_instruction 应优先压缩 summary，而不是只重复底层 diagnostic。"""
    summary = {
        "frozen_prefix": [{"step_id": "derive_A"}],
        "current_blocker": {"step_id": "recover_E", "code": "final_point_requires_square_recovery"},
        "next_actions": ["先用 line_locus_minimum_point 求最短状态 moving point。"],
        "do_not": ["不要用 evaluate_point_at_parameter 直接 produces 最终 Point answer。"],
    }

    instruction = _repair_instruction(None, repair_summary=summary)

    assert "repair_summary" in instruction
    assert "derive_A" in instruction
    assert "line_locus_minimum_point" in instruction
    assert "evaluate_point_at_parameter" in instruction


def test_previous_attempts_keep_rich_context_when_latest_error_is_thin() -> None:
    """validation 早失败不能覆盖上一轮 rich effective draft。"""
    rich_attempt = {
        "attempt": 1,
        "effective_draft": _single_scope_draft(
            _step(
                scope_id="i_2",
                step_id="derive_E_coordinate",
                recipe_hint="line_parabola_second_intersection_point",
                goal_type="derive_curve_intersection_point",
                target="answer:i_2_E",
            ),
            scope_id="i_2",
        ).to_payload(),
        "diagnostic": {
            "ok": False,
            "accepted_prefix": [
                {
                    "step_id": "derive_E_coordinate",
                    "scope_id": "i_2",
                    "capability_id": "line_parabola_second_intersection_point",
                }
            ],
            "blockers": [],
        },
        "repair_instruction": "保留 accepted prefix。",
        "errors": ["recipe_trial_step_failed: derive_B_coordinate_ii"],
    }

    class ThinPlanner:
        def repair_attempt_payload(self, *, attempt: int, errors: list[str]) -> dict[str, object]:
            return {
                "attempt": attempt,
                "effective_draft": None,
                "diagnostic": None,
                "errors": tuple(errors),
                "repair_instruction": "修复 validation error。",
            }

    latest_error = StructuredSolveError(
        stage="planning",
        code="planner_error",
        message="duplicate_created_entity: point:i_2:F",
    )

    merged = _next_previous_errors([rich_attempt], ThinPlanner(), 2, latest_error)

    assert merged[0] == rich_attempt
    assert merged[1]["attempt"] == 2
    assert merged[1]["effective_draft"] is None
    assert _last_previous_attempt(merged) == rich_attempt


def test_strategy_planner_keeps_raw_response_and_validation_report_on_validation_failure() -> None:
    """DeepSeek raw 输出 validation 失败时仍应保留 debug artifact 数据。"""
    class InvalidJsonClient:
        def complete(self, _payload: object) -> str:
            return "{not valid strategy json"

    problem = load_problem_ir(HEPING_FIXTURE)
    planner = StrategyPlanner(
        ContextBuilder().build(problem),
        mode="deepseek",
        client=InvalidJsonClient(),
    )

    with pytest.raises(StrategyDraftValidationError, match="strategy_validation_failed"):
        planner.plan(_heping_inputs())

    assert planner.last_raw_response == "{not valid strategy json"
    assert planner.last_validation_report is not None
    assert getattr(planner.last_validation_report, "ok") is False
    assert planner.last_draft is None


def test_strategy_runtime_has_no_nankai_answer_or_point_name_shortcuts() -> None:
    """runtime strategy 代码不应残留南开小问 id 或辅助点固定命名。"""
    source = (
        _repo_root()
        / "server"
        / "shuxueshuo_server"
        / "solver"
        / "runtime"
        / "strategy_planner.py"
    ).read_text(encoding="utf-8")

    forbidden = [
        "ii_1.minimum_value",
        "$question.ii.points.D",
        "D_prime",
        "tj-2026-nankai",
        "right_angle_equal_length_MDN",
        "F_midpoint_of_DN",
        "segment_E_on_DM",
    ]
    for text in forbidden:
        assert text not in source


def test_recipe_trial_executor_compiles_recorded_step_intents_without_d_prime_template() -> None:
    """固定 StepIntent fixture 应由通用 RecipeTrialExecutor 编译。"""
    payload = json.loads(NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    inputs = _nankai_inputs()
    registry = _registry()
    draft = StepIntentValidator().validate(
        payload,
        question_goals=inputs.question_goals,
        handle_registry=registry,
        family_spec=inputs.family_spec,
    )

    output = RecipeTrialExecutor().compile(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=_runtime_context(),
        question_goals=inputs.question_goals,
    )

    declaration_paths = [declaration.path for declaration in output.context_declarations]
    assert "$question.ii.points.Aux" in declaration_paths
    assert "$question.ii.points.D_prime" not in declaration_paths
    serialized = json.dumps(
        {
            "declarations": declaration_paths,
            "plans": [
                {
                    "step_id": plan.step_id,
                    "promote_outputs": plan.promote_outputs,
                    "inputs": [invocation.inputs for invocation in plan.invocations],
                }
                for plan in output.step_plans
            ],
        },
        ensure_ascii=False,
    )
    assert "$question.ii.points.D_prime" not in serialized


def test_write_strategy_debug_artifacts(tmp_path: Path) -> None:
    """debug helper 应按约定文件名写出 prompt、payload、raw response 和 report。"""
    payload = _nankai_payload()
    prompt = StrategyPromptRenderer().render(payload)
    raw = json.dumps(_valid_step_intent_payload(), ensure_ascii=False)
    draft, report = StepIntentValidator().validate_json_with_report(
        raw,
        question_goals=_nankai_inputs().question_goals,
        handle_registry=_registry(),
        family_spec=_nankai_inputs().family_spec,
    )
    resolution_report = StepIntentCandidateResolver().resolve(
        draft,
        family_spec=_nankai_inputs().family_spec,
        method_specs=_nankai_inputs().method_specs,
        handle_registry=_registry(),
    )

    write_strategy_debug_artifacts(
        tmp_path,
        payload=payload,
        prompt=prompt,
        raw_response=raw,
        draft=draft,
        report=report,
        resolution_report=resolution_report,
        llm_metadata={"provider": "fake"},
    )

    assert (tmp_path / "prompt.system.md").exists()
    assert (tmp_path / "payload.problem_ir.json").exists()
    assert (tmp_path / "payload.naming_conventions.json").exists()
    assert (tmp_path / "payload.method_catalog.json").exists()
    assert (tmp_path / "payload.recipe_catalog.json").exists()
    assert not (tmp_path / "payload.planning_signals.json").exists()
    assert (tmp_path / "raw-response.txt").read_text(encoding="utf-8") == raw
    parsed = json.loads((tmp_path / "parsed-step-intents.json").read_text(encoding="utf-8"))
    assert parsed["scopes"][0]["scope_id"] == "i"
    assert parsed["scopes"][0]["steps"][0]["step_id"] == "derive_axis_point"
    report_payload = json.loads((tmp_path / "validation-report.json").read_text(encoding="utf-8"))
    assert report_payload["ok"] is True
    assert (tmp_path / "handle-resolution-report.json").exists()
    handle_report = json.loads(
        (tmp_path / "handle-resolution-report.json").read_text(encoding="utf-8")
    )
    assert handle_report["corrections"] == []
    assert (tmp_path / "recipe-alignment.json").exists()
    assert (tmp_path / "candidate-resolution-report.json").exists()
