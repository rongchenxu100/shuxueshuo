from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.family import QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
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
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    CanonicalRuntimeBindingIndex,
    CreatedEntity,
    MethodBindingRuleRegistry,
    ProducedFact,
    RecipeExecutionSpecRegistry,
    RecipeTrialExecutor,
    StepIntentCandidateResolver,
    STEP_INTENT_JSON_SCHEMA,
    StepIntent,
    StepIntentDraft,
    StepIntentNormalizationAction,
    StepIntentValidator,
    StepIntentNormalizer,
    StrategyDraftValidationError,
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.strategy_compiler import (
    DEFAULT_BINDING_SELECTORS,
    DEFAULT_RECIPE_COMPILERS,
    _output_key_from_promote_source,
    _parameter_output_key_from_symbol_path,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    PrepInvocationBuilder,
    _RecipePlanCompiler,
    _method_outputs_for_step,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import build_executable_capabilities
from shuxueshuo_server.solver.runtime.strategy_normalizer import NormalizationRuleResult
from shuxueshuo_server.solver.runtime.strategy_models import StepIntentScope


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_LLM_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.llm.json"
LLM_SCHEMA = "../internal/schemas/solver-llm-problem-ir.schema.json"
NANKAI_EXECUTABLE_STEP_INTENTS = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-fixtures"
    / "tj-2026-nankai-yimo-25.executable-step-intents.json"
)
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
HEXI_LLM_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "solver-fixtures"
    / "tj-2026-hexi-yimo-25.llm.json"
)


def _nankai_problem():
    """加载南开 25 runtime ProblemIR。"""
    return load_problem_ir(NANKAI_FIXTURE)


def _repo_root() -> Path:
    """测试文件位于 server/tests/solver，向上三层是仓库根目录。"""
    return Path(__file__).resolve().parents[3]


def _nankai_llm_problem() -> dict:
    """加载给 LLM prompt 使用的精简南开题目 IR。"""
    path = _repo_root() / "internal" / "solver-fixtures" / "tj-2026-nankai-yimo-25.llm.json"
    return json.loads(path.read_text(encoding="utf-8"))


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
    """加载给 LLM prompt 使用的精简河西题目 IR。"""
    return json.loads(HEXI_LLM_FIXTURE.read_text(encoding="utf-8"))


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
        "fact:problem:D_coordinate_value",
    ]
    assert [action.action for action in report.actions] == [
        "normalize_point_coordinate_answer_fact"
    ]


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


def test_strategy_payload_builder_requires_llm_problem_ir() -> None:
    """.llm.json 是 Strategy prompt 的唯一题目事实源，不再回退旧 solver fixture。"""
    with pytest.raises(TypeError):
        StrategyPayloadBuilder().build(_nankai_inputs())  # type: ignore[call-arg]


def test_strategy_probe_inputs_uses_empty_context_inventory() -> None:
    """Strategy probe 不再构建 visible paths / planning signals。"""
    inputs = _nankai_inputs()

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
    assert "公共结论只 produces 一次" in prompt.user
    assert "同时输出 `answer:<goal.id>` 和公共 `fact:<scope>:<semantic_name>`" in prompt.user
    assert "同一个父级 Entity 点的坐标不能在兄弟小问分别 produces" in prompt.user
    assert "fact:problem:shared_coordinate_value" in prompt.user
    assert "derive_anchor_coordinate" in prompt.user
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
    """无害多读不应让公共结论在 validator 阶段失败。"""
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
    assert step_report.selected_capability_id == "quadratic_axis_from_relation"
    assert any(
        warning.startswith("unused_child_read_ignored_for_valid_scope")
        for warning in step_report.warnings
    )


def test_candidate_resolver_rejects_used_child_read_for_parent_valid_scope() -> None:
    """实际会被参数 method 使用的子问 fact，不能产出父级公共 fact。"""
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
    hinted = step_report.candidates[0]
    assert hinted.capability_id == "parameter_from_segment_length"
    assert any("invalid_valid_scope" in error for error in hinted.errors)


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
    families = (_nankai_inputs().family_spec, QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY)

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


def test_recipe_compiler_registry_covers_family_execution_strategies() -> None:
    """FamilySpec 中的 recipe execution strategy 都应存在于默认编译策略注册表。"""
    families = (_nankai_inputs().family_spec, QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY)
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
