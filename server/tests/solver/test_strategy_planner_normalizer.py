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

from shuxueshuo_server.solver.runtime.normalizer_core import (  # noqa: E402
    DEFAULT_NORMALIZATION_RULES,
    _validate_normalization_rule_order,
)


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


def test_normalizer_rule_order_constraints_reject_known_dependency_violation() -> None:
    """关键 rule 顺序依赖应由声明式约束检查，而不是只靠注释。"""
    rules = list(DEFAULT_NORMALIZATION_RULES)
    drop_index = next(
        index for index, rule in enumerate(rules)
        if rule.__class__.__name__ == "_DropUnavailableQuadraticCoefficientReadsRule"
    )
    quadratic_index = next(
        index for index, rule in enumerate(rules)
        if rule.__class__.__name__ == "_QuadraticFromConstraintsRule"
    )
    rules[drop_index], rules[quadratic_index] = rules[quadratic_index], rules[drop_index]

    with pytest.raises(
        ValueError,
        match="_DropUnavailableQuadraticCoefficientReadsRule must run before "
        "_QuadraticFromConstraintsRule",
    ):
        _validate_normalization_rule_order(tuple(rules))


def test_step_intent_normalizer_accepts_injected_scope_transform() -> None:
    """Scope 级变换也应通过 pipeline 调度，避免主循环硬编码。"""

    class SyntheticScopeTransform:
        name = "test.synthetic_scope_transform"

        def apply(self, steps, *, handle_registry):  # noqa: ANN001
            del handle_registry
            step = steps[0]
            return (
                (
                    StepIntent(
                        scope_id=step.scope_id,
                        step_id=step.step_id,
                        recipe_hint=step.recipe_hint,
                        goal_type=step.goal_type,
                        target="fact:i:scope_transform_target",
                        strategy=step.strategy,
                        reads=step.reads,
                        creates=step.creates,
                        produces=step.produces,
                    ),
                ),
                [
                    StepIntentNormalizationAction(
                        action="synthetic_scope_transform",
                        step_id=step.step_id,
                        handle=step.target,
                        target_step_id=None,
                        reason="测试 scope transform pipeline 被 normalizer 调用。",
                    )
                ],
            )

    step = _step(
        scope_id="i",
        step_id="synthetic_scope_transform_step",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_test",
        target="fact:i:old_target",
    )

    normalized, report = StepIntentNormalizer(
        rules=(),
        scope_transforms=(SyntheticScopeTransform(),),
    ).normalize(
        _single_scope_draft(step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=[],
        handle_registry=_registry(),
    )

    assert normalized.scopes[0].steps[0].target == "fact:i:scope_transform_target"
    assert [action.action for action in report.actions] == [
        "synthetic_scope_transform"
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


def test_step_intent_normalizer_keeps_independent_equation_fact_under_quadratic_hint() -> None:
    """普通 Equation fact 即使 hint 填成 quadratic_from_constraints，也不应被名字误吞。"""
    equation_step = _step(
        scope_id="ii",
        step_id="derive_independent_equation",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_relation",
        target="fact:ii:independent_equation",
        produces=(
            ProducedFact(
                "fact:ii:independent_equation",
                "ii",
                "由已知条件推出的独立方程",
                output_type="Equation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(equation_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_registry(),
    )

    step = normalized.scopes[0].steps[0]
    assert step.produces == equation_step.produces
    assert step.target == "fact:ii:independent_equation"
    assert report.actions == ()


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


def test_normalizer_drops_recomputed_visible_axis_point_coordinate_step() -> None:
    """已可见的题面轴点不应在后续小问中再 produced 成坐标 fact。"""
    recompute_d = _step(
        scope_id="ii_1",
        step_id="derive_D_coordinate_ii",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="fact:ii:D_coordinate",
        reads=("fact:problem:coefficient_relation",),
        produces=(
            ProducedFact(
                "fact:ii:D_coordinate",
                "ii",
                "D 点坐标",
                output_type="Point",
            ),
        ),
    )
    use_d = _step(
        scope_id="ii_1",
        step_id="derive_F_coordinate_expr",
        recipe_hint="midpoint_point",
        goal_type="derive_midpoint",
        target="fact:ii:F_coordinate_expr",
        reads=("fact:ii:D_coordinate", "fact:ii:F_midpoint_of_DN"),
        produces=(
            ProducedFact(
                "fact:ii:F_coordinate_expr",
                "ii",
                "F 点坐标",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(recompute_d, use_d, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [step.step_id for step in normalized.steps] == ["derive_F_coordinate_expr"]
    assert normalized.steps[0].reads == ("point:problem:D", "fact:ii:F_midpoint_of_DN")
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


def test_step_intent_normalizer_rewrites_all_folded_quadratic_utility_aliases() -> None:
    """同一 quadratic fold 中被删除的 utility facts 都必须同步到 canonical reads。"""
    utility_step = _step(
        scope_id="ii_1",
        step_id="derive_a_m_relation",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parameter",
        target="fact:ii_1:a_expression",
        reads=(
            "fact:ii:M_coordinate_expr",
            "fact:ii:N_coordinate_expr",
            "fact:ii:N_on_parabola",
            "fact:ii:M_on_parabola",
            "fact:problem:coefficient_relation",
            "symbol:problem:a",
            "symbol:problem:m",
            "point:ii:M",
            "point:ii:N",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:c_expression",
                "ii_1",
                "c=1-m，由 N 在抛物线上得出",
                output_type="Expression",
            ),
            ProducedFact(
                "fact:ii_1:a_expression",
                "ii_1",
                "a=1/(m-2)，由代入运算得出",
                output_type="Expression",
            ),
        ),
    )
    use_step = _step(
        scope_id="ii_1",
        step_id="derive_parabola_ii1",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:ii_1.parabola",
        reads=(
            "fact:ii_1:a_expression",
            "fact:ii_1:c_expression",
            "fact:ii_1:m_value",
            "fact:problem:coefficient_relation",
            "fact:ii:M_on_parabola",
            "point:ii:M",
        ),
        produces=(
            ProducedFact(
                "answer:ii_1.parabola",
                "ii_1",
                "第（Ⅱ）①问的抛物线解析式",
                output_type="Parabola",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(utility_step, use_step, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=[],
        handle_registry=_registry(),
    )

    first, second = normalized.scopes[0].steps
    assert [item.handle for item in first.produces] == ["fact:ii:parametric_parabola"]
    assert "fact:ii_1:a_expression" not in second.reads
    assert "fact:ii_1:c_expression" not in second.reads
    assert "fact:ii_1:parametric_parabola" not in second.reads
    assert "fact:ii:parametric_parabola" in second.reads
    folded_handles = {
        action.handle
        for action in report.actions
        if action.action == "normalize_quadratic_utility_fact_to_parabola"
    }
    assert folded_handles == {
        "fact:ii_1:a_expression",
        "fact:ii_1:c_expression",
    }


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


def test_step_intent_normalizer_folds_curve_candidate_parameter_internal_sequence() -> None:
    """候选点逐个代入曲线求参再筛选，应折叠为公开候选筛选 recipe。"""
    candidate_step = _step(
        scope_id="ii",
        step_id="construct_D_candidates",
        recipe_hint="right_angle_equal_length_candidates",
        goal_type="derive_constructed_point",
        target="fact:ii:D_candidates",
        produces=(
            ProducedFact("fact:ii:D_cand1_coordinate_expr", "ii", "候选点 D1 坐标", "Point"),
            ProducedFact("fact:ii:D_cand2_coordinate_expr", "ii", "候选点 D2 坐标", "Point"),
        ),
    )
    candidate_step = replace(
        candidate_step,
        creates=(
            CreatedEntity("point:ii:D_cand1", "point", "ii", "候选点 D1"),
            CreatedEntity("point:ii:D_cand2", "point", "ii", "候选点 D2"),
        ),
    )
    solve_d1 = _step(
        scope_id="ii",
        step_id="solve_D1_parameter",
        recipe_hint="parameter_from_curve_point_on_quadratic",
        goal_type="derive_parameter",
        target="fact:ii:b_candidate1",
        reads=(
            "fact:ii:D_cand1_coordinate_expr",
            "fact:ii:parabola_expr",
            "fact:problem:b_gt_0",
        ),
        produces=(
            ProducedFact("fact:ii:b_candidate1", "ii", "候选 D1 对应的 b", "ParameterValue"),
            ProducedFact("fact:ii:D1_solved_coordinate", "ii", "D1 代入参数后的坐标", "Point"),
        ),
    )
    solve_d2 = _step(
        scope_id="ii",
        step_id="solve_D2_parameter",
        recipe_hint="parameter_from_curve_point_on_quadratic",
        goal_type="derive_parameter",
        target="fact:ii:b_candidate2",
        reads=(
            "fact:ii:D_cand2_coordinate_expr",
            "fact:ii:parabola_expr",
            "fact:problem:b_gt_0",
        ),
        produces=(
            ProducedFact("fact:ii:b_candidate2", "ii", "候选 D2 对应的 b", "ParameterValue"),
            ProducedFact("fact:ii:D2_solved_coordinate", "ii", "D2 代入参数后的坐标", "Point"),
        ),
    )
    select_step = _step(
        scope_id="ii",
        step_id="select_D",
        recipe_hint=None,
        goal_type="derive_constructed_point",
        target="answer:ii_D",
        reads=(
            "fact:ii:b_candidate1",
            "fact:ii:b_candidate2",
            "fact:ii:D1_solved_coordinate",
            "fact:ii:D2_solved_coordinate",
            "fact:problem:b_gt_0",
        ),
        produces=(ProducedFact("answer:ii_D", "ii", "第（Ⅱ）问 D 点坐标", "Point"),),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(candidate_step, solve_d1, solve_d2, select_step, scope_id="ii"),
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=[],
        handle_registry=_hexi_registry(),
    )

    steps = normalized.scopes[0].steps
    assert [step.step_id for step in steps] == ["construct_D_candidates", "select_D"]
    assert steps[0].produces[0].handle == "fact:ii:D_candidates"
    assert steps[0].creates == ()
    assert steps[1].recipe_hint == "curve_candidate_parameter_solve"
    assert steps[1].reads == (
        "fact:ii:D_candidates",
        "fact:ii:parabola_expr",
        "fact:problem:b_gt_0",
    )
    assert [item.handle for item in steps[1].produces] == ["answer:ii_D"]
    assert {action.action for action in report.actions} == {
        "drop_internal_candidate_point_create",
        "normalize_candidate_point_facts_to_point_list",
        "fold_curve_candidate_parameter_internal_sequence",
    }


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


def test_normalizer_merges_visible_public_coordinate_alias_across_scopes() -> None:
    """后续 scope 重复求已发布公共点坐标时，应合并到前序 output。"""
    answer_step = _step(
        scope_id="i",
        step_id="derive_axis_point_i",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="answer:i.axis_point",
        reads=("fact:problem:coefficient_relation", "point:problem:D"),
        produces=(
            ProducedFact(
                "answer:i.axis_point",
                "problem",
                "第（Ⅰ）问 D 点坐标，全题可见",
                output_type="Point",
            ),
        ),
    )
    repeated_fact_step = _step(
        scope_id="ii_1",
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
        scope_id="ii_2",
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
                StepIntentScope(scope_id="i", label="第（Ⅰ）问", steps=(answer_step,)),
                StepIntentScope(scope_id="ii_1", label="第（Ⅱ）①问", steps=(repeated_fact_step,)),
                StepIntentScope(scope_id="ii_2", label="第（Ⅱ）②问", steps=(use_step,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [step.step_id for step in normalized.scopes[0].steps] == ["derive_axis_point_i"]
    assert normalized.scopes[1].steps == ()
    assert [item.handle for item in normalized.scopes[0].steps[0].produces] == [
        "answer:i.axis_point",
        "fact:problem:D_coordinate",
    ]
    assert normalized.scopes[2].steps[0].reads == ("fact:problem:D_coordinate",)
    assert [action.action for action in report.actions] == [
        "merge_visible_public_output_alias_step"
    ]
    assert report.actions[0].target_step_id == "derive_axis_point_i"


def test_normalizer_does_not_merge_visible_coordinate_when_reads_change_state() -> None:
    """后续 step 多读子问条件时，不应仅因同点和可见性而合并。"""
    answer_step = _step(
        scope_id="i",
        step_id="derive_axis_point_i",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="answer:i.axis_point",
        reads=("fact:problem:coefficient_relation", "point:problem:D"),
        produces=(
            ProducedFact(
                "answer:i.axis_point",
                "problem",
                "第（Ⅰ）问 D 点坐标，全题可见",
                output_type="Point",
            ),
        ),
    )
    narrower_step = _step(
        scope_id="ii_1",
        step_id="derive_D_coordinate_after_parameter",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="fact:problem:D_coordinate",
        reads=(
            "fact:problem:coefficient_relation",
            "point:problem:D",
            "fact:ii_1:m_value",
        ),
        produces=(
            ProducedFact(
                "fact:problem:D_coordinate",
                "problem",
                "读取子问参数后的 D 点坐标",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i", label="第（Ⅰ）问", steps=(answer_step,)),
                StepIntentScope(scope_id="ii_1", label="第（Ⅱ）①问", steps=(narrower_step,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [step.step_id for step in normalized.scopes[0].steps] == ["derive_axis_point_i"]
    assert [step.step_id for step in normalized.scopes[1].steps] == [
        "derive_D_coordinate_after_parameter"
    ]
    assert report.actions == ()


def test_normalizer_repairs_deepseek_nankai_first_attempt_shape() -> None:
    """真实 DeepSeek 首轮常见的讲解式 dataflow 应收敛成 executable 形状。"""
    axis_step = _step(
        scope_id="i",
        step_id="derive_axis_point_i",
        recipe_hint="quadratic_axis_x_intercept_point",
        goal_type="derive_axis_point",
        target="answer:i.axis_point",
        reads=("fact:i:parabola_expression", "point:problem:D"),
        produces=(
            ProducedFact("answer:i.axis_point", "problem", "D 点坐标", output_type="Point"),
            ProducedFact("fact:i:D_coordinate", "i", "D 点坐标", output_type="Point"),
        ),
    )
    n_step = _step(
        scope_id="ii_1",
        step_id="derive_N_coordinate",
        recipe_hint="right_angle_equal_length_construct_and_select",
        goal_type="derive_constructed_point",
        target="fact:ii_1:N_coordinate_expr",
        reads=(
            "point:problem:D",
            "fact:i:D_coordinate",
            "point:ii:M",
            "fact:ii:right_angle_equal_length_MDN",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:N_coordinate_expr",
                "ii_1",
                "N 坐标含参数",
                output_type="Point",
            ),
        ),
    )
    path_step = _step(
        scope_id="ii_1",
        step_id="reduce_two_moving_path",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii_1:single_moving_path_equivalence",
        reads=(
            "point:ii:F",
            "fact:ii:F_midpoint_of_DN",
            "fact:ii_1:N_coordinate_expr",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:single_moving_path_equivalence",
                "ii_1",
                "路径转化",
                output_type="PathTransformation",
            ),
        ),
    )
    parabola_cache = _step(
        scope_id="ii_1",
        step_id="derive_parabola_ii_param",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii_1:parabola_expression_with_param",
        produces=(
            ProducedFact(
                "fact:ii_1:parabola_expression_with_param",
                "ii_1",
                "含参抛物线缓存",
                output_type="Parabola",
            ),
        ),
    )
    final_parabola = _step(
        scope_id="ii_2",
        step_id="evaluate_parabola_ii2",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="derive_parabola",
        target="answer:ii_2.parabola",
        reads=("fact:ii_1:parabola_expression_with_param", "fact:ii_2:m_value"),
        produces=(
            ProducedFact(
                "answer:ii_2.parabola",
                "ii_2",
                "第（Ⅱ）②问抛物线",
                output_type="Parabola",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i", label="第（Ⅰ）问", steps=(axis_step,)),
                StepIntentScope(
                    scope_id="ii_1",
                    label="第（Ⅱ）①问",
                    steps=(n_step, path_step, parabola_cache),
                ),
                StepIntentScope(scope_id="ii_2", label="第（Ⅱ）②问", steps=(final_parabola,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for scope in normalized.scopes for step in scope.steps}
    assert steps["derive_axis_point_i"].recipe_hint == "quadratic_axis_from_relation"
    assert [item.handle for item in steps["derive_axis_point_i"].produces] == [
        "answer:i.axis_point",
        "fact:problem:D_coordinate",
    ]
    assert steps["derive_N_coordinate"].produces[0].handle == "fact:ii:N_coordinate_expr"
    assert "derive_F_coordinate_expr" in steps
    assert steps["derive_F_coordinate_expr"].recipe_hint == "midpoint_point"
    assert "fact:ii:N_coordinate_expr" in steps["derive_F_coordinate_expr"].reads
    assert "fact:ii_1:N_coordinate_expr" not in steps["derive_F_coordinate_expr"].reads
    assert steps["reduce_two_moving_path"].reads[-1] == "fact:ii:F_coordinate_expr"
    assert steps["reduce_two_moving_path"].produces[0].handle == (
        "fact:ii:single_moving_path_equivalence"
    )
    assert "derive_parabola_ii_param" not in steps
    assert steps["evaluate_parabola_ii2"].recipe_hint == "quadratic_from_constraints"
    assert steps["evaluate_parabola_ii2"].reads == ("fact:ii_2:m_value",)
    assert {action.action for action in report.actions} >= {
        "normalize_axis_point_method_alias",
        "normalize_axis_point_alias_fact",
        "promote_common_scope_output",
        "insert_midpoint_coordinate_backfill_step",
        "drop_parameterized_parabola_utility_step",
        "normalize_parameterized_parabola_evaluation",
    }


def test_midpoint_backfill_uses_midpoint_fact_not_fixed_point_name() -> None:
    """midpoint backfill 应由 midpoint_definition 触发，不依赖南开 F 点命名。"""
    base_registry = _registry()
    registry = replace(
        base_registry,
        entity_handles=frozenset(set(base_registry.entity_handles) | {"point:ii:G"}),
        fact_handles=frozenset(set(base_registry.fact_handles) | {"fact:ii:G_midpoint_of_DN"}),
        fact_types={
            **base_registry.fact_types,
            "fact:ii:G_midpoint_of_DN": "midpoint_definition",
        },
        handle_valid_scopes={
            **base_registry.handle_valid_scopes,
            "point:ii:G": "ii",
            "fact:ii:G_midpoint_of_DN": "ii",
        },
    )
    n_step = _step(
        scope_id="ii",
        step_id="derive_N_coordinate",
        recipe_hint="right_angle_equal_length_construct_and_select",
        goal_type="derive_constructed_point",
        target="fact:ii:N_coordinate_expr",
        reads=(
            "point:problem:D",
            "fact:problem:D_coordinate",
            "point:ii:M",
            "fact:ii:right_angle_equal_length_MDN",
        ),
        produces=(
            ProducedFact(
                "fact:ii:N_coordinate_expr",
                "ii",
                "N 坐标含参数",
                output_type="Point",
            ),
        ),
    )
    axis_step = _step(
        scope_id="i",
        step_id="derive_D_coordinate",
        recipe_hint="quadratic_axis_x_intercept_point",
        goal_type="derive_axis_point",
        target="fact:problem:D_coordinate",
        reads=("fact:i:parabola_expression", "point:problem:D"),
        produces=(
            ProducedFact(
                "fact:problem:D_coordinate",
                "problem",
                "D 点坐标",
                output_type="Point",
            ),
        ),
    )
    path_step = _step(
        scope_id="ii",
        step_id="reduce_two_moving_path",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii:single_moving_path_equivalence",
        reads=(
            "point:ii:G",
            "fact:ii:G_midpoint_of_DN",
            "fact:ii:N_coordinate_expr",
        ),
        produces=(
            ProducedFact(
                "fact:ii:single_moving_path_equivalence",
                "ii",
                "路径转化",
                output_type="PathTransformation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i", label="第（Ⅰ）问", steps=(axis_step,)),
                StepIntentScope(scope_id="ii", label="第（Ⅱ）问", steps=(n_step, path_step)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=registry,
    )

    steps = {step.step_id: step for step in normalized.steps}
    assert steps["derive_G_coordinate_expr"].recipe_hint == "midpoint_point"
    assert steps["derive_G_coordinate_expr"].target == "fact:ii:G_coordinate_expr"
    assert "fact:ii:G_coordinate_expr" in steps["reduce_two_moving_path"].reads
    assert "fact:ii:F_coordinate_expr" not in steps["reduce_two_moving_path"].reads
    assert any(
        action.action == "insert_midpoint_coordinate_backfill_step"
        and action.handle == "fact:ii:G_coordinate_expr"
        for action in report.actions
    )


def test_midpoint_backfill_parses_multi_character_endpoint_names() -> None:
    """midpoint backfill 应支持 Aux1、P_prime 等多字符端点名。"""
    registry = CanonicalHandleRegistry(
        scope_ids=frozenset(("problem", "ii")),
        entity_handles=frozenset((
            "point:ii:M",
            "point:ii:P_prime",
            "point:ii:Aux1",
        )),
        fact_handles=frozenset((
            "fact:ii:M_midpoint_of_P_prime_Aux1",
            "fact:ii:P_prime_coordinate",
            "fact:ii:Aux1_coordinate",
        )),
        answer_handles=frozenset(),
        scope_parents={"problem": None, "ii": "problem"},
        fact_types={
            "fact:ii:M_midpoint_of_P_prime_Aux1": "midpoint_definition",
            "fact:ii:P_prime_coordinate": "point_coordinate",
            "fact:ii:Aux1_coordinate": "point_coordinate",
        },
        handle_valid_scopes={
            "point:ii:M": "ii",
            "point:ii:P_prime": "ii",
            "point:ii:Aux1": "ii",
            "fact:ii:M_midpoint_of_P_prime_Aux1": "ii",
            "fact:ii:P_prime_coordinate": "ii",
            "fact:ii:Aux1_coordinate": "ii",
        },
    )
    path_step = _step(
        scope_id="ii",
        step_id="reduce_path_with_multi_name_midpoint",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii:path_equivalence",
        reads=(
            "point:ii:M",
            "fact:ii:M_midpoint_of_P_prime_Aux1",
        ),
        produces=(
            ProducedFact(
                "fact:ii:path_equivalence",
                "ii",
                "路径转化",
                output_type="PathTransformation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(path_step, scope_id="ii"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=(),
        handle_registry=registry,
    )

    steps = {step.step_id: step for step in normalized.steps}
    midpoint_step = steps["derive_M_coordinate_expr"]
    assert midpoint_step.recipe_hint == "midpoint_point"
    assert midpoint_step.reads == (
        "point:ii:P_prime",
        "point:ii:Aux1",
        "fact:ii:P_prime_coordinate",
        "fact:ii:Aux1_coordinate",
        "fact:ii:M_midpoint_of_P_prime_Aux1",
    )
    assert "fact:ii:M_coordinate_expr" in steps[
        "reduce_path_with_multi_name_midpoint"
    ].reads
    assert any(
        action.action == "insert_midpoint_coordinate_backfill_step"
        and action.handle == "fact:ii:M_coordinate_expr"
        for action in report.actions
    )


def test_midpoint_backfill_prefers_structured_payload_over_fact_name() -> None:
    """midpoint fact handle 可自由命名；端点应从 midpoint_definition payload 读取。"""
    base_registry = _registry()
    midpoint_fact = "fact:ii:midpoint_G_between_D_N"
    registry = replace(
        base_registry,
        entity_handles=frozenset(set(base_registry.entity_handles) | {"point:ii:G"}),
        fact_handles=frozenset(set(base_registry.fact_handles) | {midpoint_fact}),
        fact_types={
            **base_registry.fact_types,
            midpoint_fact: "midpoint_definition",
        },
        fact_payloads={
            **base_registry.fact_payloads,
            midpoint_fact: {
                "point": "point:ii:G",
                "of": ["point:problem:D", "point:ii:N"],
            },
        },
        handle_valid_scopes={
            **base_registry.handle_valid_scopes,
            "point:ii:G": "ii",
            midpoint_fact: "ii",
        },
    )
    n_step = _step(
        scope_id="ii",
        step_id="derive_N_coordinate",
        recipe_hint="right_angle_equal_length_construct_and_select",
        goal_type="derive_constructed_point",
        target="fact:ii:N_coordinate_expr",
        reads=(
            "point:problem:D",
            "fact:problem:D_coordinate",
            "point:ii:M",
            "fact:ii:right_angle_equal_length_MDN",
        ),
        produces=(
            ProducedFact(
                "fact:ii:N_coordinate_expr",
                "ii",
                "N 坐标含参数",
                output_type="Point",
            ),
        ),
    )
    axis_step = _step(
        scope_id="i",
        step_id="derive_D_coordinate",
        recipe_hint="quadratic_axis_x_intercept_point",
        goal_type="derive_axis_point",
        target="fact:problem:D_coordinate",
        reads=("fact:i:parabola_expression", "point:problem:D"),
        produces=(
            ProducedFact(
                "fact:problem:D_coordinate",
                "problem",
                "D 点坐标",
                output_type="Point",
            ),
        ),
    )
    path_step = _step(
        scope_id="ii",
        step_id="reduce_path_with_payload_midpoint",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii:single_moving_path_equivalence",
        reads=(
            "point:ii:G",
            midpoint_fact,
            "fact:problem:D_coordinate",
            "fact:ii:N_coordinate_expr",
        ),
        produces=(
            ProducedFact(
                "fact:ii:single_moving_path_equivalence",
                "ii",
                "路径转化",
                output_type="PathTransformation",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(scope_id="i", label="第（Ⅰ）问", steps=(axis_step,)),
                StepIntentScope(scope_id="ii", label="第（Ⅱ）问", steps=(n_step, path_step)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=registry,
    )

    steps = {step.step_id: step for step in normalized.steps}
    midpoint_step = steps["derive_G_coordinate_expr"]
    assert midpoint_step.reads == (
        "point:problem:D",
        "point:ii:N",
        "fact:problem:D_coordinate",
        "fact:ii:N_coordinate_expr",
        midpoint_fact,
    )
    assert "fact:ii:G_coordinate_expr" in steps[
        "reduce_path_with_payload_midpoint"
    ].reads
    assert any(
        action.action == "insert_midpoint_coordinate_backfill_step"
        and action.handle == "fact:ii:G_coordinate_expr"
        for action in report.actions
    )


def test_normalizer_routes_parameterized_minimum_answer_to_expression_evaluator() -> None:
    """MinimumExpression 代入参数求答案时，不应误走 distance_between_points。"""
    min_expr_step = _step(
        scope_id="ii_1",
        step_id="compute_path_minimum_expression",
        recipe_hint="path_minimum_by_straightened_distance",
        goal_type="derive_minimum_value",
        target="fact:ii:path_minimum_expression",
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "路径最小值关于参数 m 的表达式",
                output_type="MinimumExpression",
            ),
        ),
    )
    parameter_step = _step(
        scope_id="ii_1",
        step_id="derive_m_value_from_MN_length",
        recipe_hint="parameter_from_segment_length",
        goal_type="derive_parameter",
        target="fact:ii_1:m_value",
        produces=(
            ProducedFact(
                "fact:ii_1:m_value",
                "ii_1",
                "第（Ⅱ）①问参数值",
                output_type="ParameterValue",
            ),
        ),
    )
    eval_step = _step(
        scope_id="ii_1",
        step_id="evaluate_minimum_value_ii1",
        recipe_hint="distance_between_points",
        goal_type="evaluate_expression_at_parameter",
        target="answer:ii_1.minimum_value",
        reads=("fact:ii:path_minimum_expression", "fact:ii_1:m_value"),
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                "第（Ⅱ）①问 EG+FG 的最小值",
                output_type="MinimumExpression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(min_expr_step, parameter_step, eval_step, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )
    normalized_eval = normalized.scopes[0].steps[-1]

    assert normalized_eval.recipe_hint == "evaluate_expression_at_parameter"
    assert normalized_eval.goal_type == "evaluate_expression_at_parameter"
    assert any(
        action.action == "normalize_parameterized_minimum_evaluation"
        for action in report.actions
    )

    resolution = StepIntentCandidateResolver().resolve(
        _single_scope_draft(normalized_eval, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        method_specs=MethodSpecRegistry.load_from_code(),
        handle_registry=_registry(),
    )
    step_report = resolution.step_reports[0]
    assert step_report.ok is True
    assert step_report.selected_capability_id == "evaluate_expression_at_parameter"

    payload = StrategyPayloadBuilder().build(
        _nankai_inputs(),
        problem_payload=_nankai_llm_problem(),
    )
    prompt_method_ids = {
        item["method_id"] for item in payload["method_catalog"]["methods"]
    }
    assert "evaluate_expression_at_parameter" in prompt_method_ids

    index = CanonicalRuntimeBindingIndex.from_context(
        _runtime_context(),
        handle_registry=_registry(),
        question_goals=_question_goals(),
    )
    index.register(
        "fact:ii:path_minimum_expression",
        "$question.ii.outputs.path_minimum_expression",
        "MinimumExpression",
        source="test",
    )
    index.register(
        "fact:ii_1:m_value",
        "$subquestion.ii_1.outputs.m_value",
        "ParameterValue",
        source="test",
    )
    bound = MethodBindingRuleRegistry.from_family_spec(_nankai_inputs().family_spec).bind(
        "evaluate_expression_at_parameter",
        normalized_eval,
        index,
    )

    assert bound["expression"] == "$question.ii.outputs.path_minimum_expression"
    assert bound["parameter_value"] == "$subquestion.ii_1.outputs.m_value"


def test_normalizer_splits_deepseek_mixed_quadratic_outputs() -> None:
    """LLM 把求参数/点坐标/抛物线合成一步时，normalizer 应拆成可执行步骤。"""
    n_step = _step(
        scope_id="ii_1",
        step_id="construct_N_coordinate_ii",
        recipe_hint="right_angle_equal_length_construct_and_select",
        goal_type="derive_constructed_point",
        target="fact:ii:N_coordinate_expr",
        reads=(
            "point:problem:D",
            "point:ii:M",
            "fact:ii:M_coordinate_expr",
            "fact:ii:right_angle_equal_length_MDN",
            "fact:ii:N_fourth_quadrant",
        ),
        produces=(
            ProducedFact(
                "fact:ii:N_coordinate_expr",
                "ii",
                "N 点坐标表达式",
                output_type="Point",
            ),
        ),
    )
    mixed_quadratic = _step(
        scope_id="ii_1",
        step_id="solve_parabola_ii1",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:ii_1.parabola",
        reads=(
            "function:problem:parabola",
            "fact:problem:coefficient_relation",
            "fact:ii:M_coordinate_expr",
            "fact:ii:M_on_parabola",
            "fact:ii:N_coordinate_expr",
            "fact:ii:N_on_parabola",
            "fact:ii_1:MN_length_squared_eq_10",
        ),
        produces=(
            ProducedFact("answer:ii_1.parabola", "ii_1", "①问抛物线", output_type="Parabola"),
            ProducedFact("fact:ii_1:m_value", "ii_1", "参数 m", output_type="ParameterValue"),
            ProducedFact("fact:ii_1:a_value", "ii_1", "系数 a", output_type="ParameterValue"),
            ProducedFact("fact:ii_1:c_value", "ii_1", "系数 c", output_type="ParameterValue"),
            ProducedFact(
                "fact:ii_1:M_numeric_coordinate",
                "ii_1",
                "M 数值坐标",
                output_type="Point",
            ),
            ProducedFact(
                "fact:ii_1:N_numeric_coordinate",
                "ii_1",
                "N 数值坐标",
                output_type="Point",
            ),
        ),
    )
    minimum_step = _step(
        scope_id="ii_1",
        step_id="compute_minimum_ii1",
        recipe_hint="path_minimum_by_straightened_distance",
        goal_type="derive_minimum_value",
        target="answer:ii_1.minimum_value",
        reads=(
            "fact:ii_1:straightened_path_candidate",
            "point:ii_1:Aux",
            "fact:ii_1:a_value",
        ),
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                "①问最小值",
                output_type="MinimumExpression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(
                    scope_id="ii_1",
                    label="第（Ⅱ）①问",
                    steps=(n_step, mixed_quadratic, minimum_step),
                ),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for step in normalized.scopes[0].steps}
    assert [step.step_id for step in normalized.scopes[0].steps] == [
        "construct_N_coordinate_ii",
        "solve_parabola_ii1_solve_parameter",
        "solve_parabola_ii1_evaluate_m_coordinate",
        "solve_parabola_ii1_evaluate_n_coordinate",
        "solve_parabola_ii1",
        "compute_minimum_ii1",
    ]
    assert steps["solve_parabola_ii1_solve_parameter"].recipe_hint == (
        "parameter_from_segment_length"
    )
    assert steps["solve_parabola_ii1_evaluate_m_coordinate"].reads == (
        "fact:ii:M_coordinate_expr",
        "fact:ii_1:m_value",
    )
    assert steps["solve_parabola_ii1_evaluate_n_coordinate"].reads == (
        "fact:ii:N_coordinate_expr",
        "fact:ii_1:m_value",
    )
    assert [item.handle for item in steps["solve_parabola_ii1"].produces] == [
        "answer:ii_1.parabola"
    ]
    assert "fact:ii_1:m_value" in steps["solve_parabola_ii1"].reads
    assert "fact:ii_1:m_value" in steps["compute_minimum_ii1"].reads
    assert "fact:ii_1:a_value" not in steps["compute_minimum_ii1"].reads
    assert {action.action for action in report.actions} >= {
        "split_mixed_quadratic_parameter_step",
        "split_mixed_quadratic_point_evaluation",
        "drop_quadratic_coefficient_value_alias",
        "add_parameter_read_for_minimum_answer",
        "drop_unavailable_quadratic_coefficient_read",
    }


def test_normalizer_splits_multi_point_parameter_evaluation_step() -> None:
    """单个 evaluate_point_at_parameter step 产出多个点坐标时，应拆成多次单点代入。"""
    n_step = _step(
        scope_id="ii_1",
        step_id="construct_N_coordinate_ii",
        recipe_hint="right_angle_equal_length_construct_and_select",
        goal_type="derive_constructed_point",
        target="fact:ii:N_coordinate_expr",
        reads=(
            "point:problem:D",
            "point:ii:M",
            "fact:ii:right_angle_equal_length_MDN",
            "fact:ii:N_fourth_quadrant",
        ),
        produces=(
            ProducedFact(
                "fact:ii:N_coordinate_expr",
                "ii",
                "N 点坐标表达式",
                output_type="Point",
            ),
        ),
    )
    parameter_step = _step(
        scope_id="ii_1",
        step_id="solve_m_from_MN_length",
        recipe_hint="parameter_from_segment_length",
        goal_type="derive_parameter",
        target="fact:ii_1:m_value",
        reads=(
            "point:ii:M",
            "fact:ii:N_coordinate_expr",
            "fact:ii_1:MN_length_squared_eq_10",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:m_value",
                "ii_1",
                "第（Ⅱ）①问 m 的值",
                output_type="ParameterValue",
            ),
        ),
    )
    multi_point_step = _step(
        scope_id="ii_1",
        step_id="evaluate_MN_coords_ii1",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point_at_parameter",
        target="compute concrete coordinates of M and N",
        reads=(
            "point:ii:M",
            "fact:ii:N_coordinate_expr",
            "fact:ii_1:m_value",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:M_coordinate",
                "ii_1",
                "M 的具体坐标",
                output_type="Point",
            ),
            ProducedFact(
                "fact:ii_1:N_coordinate",
                "ii_1",
                "N 的具体坐标",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(
                    scope_id="ii_1",
                    label="第（Ⅱ）①问",
                    steps=(n_step, parameter_step, multi_point_step),
                ),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [step.step_id for step in normalized.scopes[0].steps] == [
        "construct_N_coordinate_ii",
        "solve_m_from_MN_length",
        "evaluate_mn_coords_ii1_evaluate_m_coordinate",
        "evaluate_mn_coords_ii1_evaluate_n_coordinate",
    ]
    steps = {step.step_id: step for step in normalized.scopes[0].steps}
    assert steps["evaluate_mn_coords_ii1_evaluate_m_coordinate"].reads == (
        "point:ii:M",
        "fact:ii_1:m_value",
    )
    assert steps["evaluate_mn_coords_ii1_evaluate_m_coordinate"].produces[0].handle == (
        "fact:ii_1:M_coordinate"
    )
    assert steps["evaluate_mn_coords_ii1_evaluate_n_coordinate"].reads == (
        "fact:ii:N_coordinate_expr",
        "fact:ii_1:m_value",
    )
    assert steps["evaluate_mn_coords_ii1_evaluate_n_coordinate"].produces[0].handle == (
        "fact:ii_1:N_coordinate"
    )
    assert [action.action for action in report.actions] == [
        "split_multi_point_evaluation_step",
        "split_multi_point_evaluation_step",
    ]


def test_normalizer_drops_coefficient_aliases_from_parameter_solver_step() -> None:
    """参数求解 step 夹带 a/b/c 系数值时，只保留唯一运行参数输出。"""
    parameter_step = _step(
        scope_id="ii_1",
        step_id="solve_parameters_from_length",
        recipe_hint="parameter_from_segment_length",
        goal_type="derive_parameter",
        target="求 a 和 m 的值",
        reads=(
            "fact:ii:N_coordinate_expr",
            "fact:ii:M_coordinate_expr",
            "fact:ii_1:MN_length_squared_eq_10",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:a_value",
                "ii_1",
                "系数 a",
                output_type="ParameterValue",
            ),
            ProducedFact(
                "fact:ii_1:m_value",
                "ii_1",
                "参数 m",
                output_type="ParameterValue",
            ),
        ),
    )
    derive_parabola = _step(
        scope_id="ii_1",
        step_id="derive_parabola_after_parameter",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:ii_1.parabola",
        reads=(
            "function:problem:parabola",
            "fact:problem:coefficient_relation",
            "fact:ii_1:a_value",
            "fact:ii_1:m_value",
        ),
        produces=(
            ProducedFact(
                "answer:ii_1.parabola",
                "ii_1",
                "①问抛物线",
                output_type="Parabola",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(
                    scope_id="ii_1",
                    label="第（Ⅱ）①问",
                    steps=(parameter_step, derive_parabola),
                ),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for step in normalized.scopes[0].steps}
    assert steps["solve_parameters_from_length"].target == "fact:ii_1:m_value"
    assert [item.handle for item in steps["solve_parameters_from_length"].produces] == [
        "fact:ii_1:m_value"
    ]
    assert "fact:ii_1:m_value" in steps["derive_parabola_after_parameter"].reads
    assert "fact:ii_1:a_value" not in steps["derive_parabola_after_parameter"].reads
    assert {action.action for action in report.actions} >= {
        "drop_parameter_solver_coefficient_value_alias",
        "drop_unavailable_quadratic_coefficient_read",
    }


def test_normalizer_splits_mixed_quadratic_parameter_from_minimum_value() -> None:
    """由给定最小值反求参数时，mixed quadratic step 应拆出 minimum-value 参数 step。"""
    mixed_quadratic = _step(
        scope_id="ii_2",
        step_id="derive_parabola_ii2",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:ii_2.parabola",
        reads=(
            "function:problem:parabola",
            "fact:problem:coefficient_relation",
            "fact:ii:M_coordinate_expr",
            "fact:ii:M_on_parabola",
            "fact:ii:N_coordinate_expr",
            "fact:ii:N_on_parabola",
            "fact:ii:path_minimum_expression",
            "fact:ii_2:path_minimum_value_given",
        ),
        produces=(
            ProducedFact("answer:ii_2.parabola", "ii_2", "②问抛物线", output_type="Parabola"),
            ProducedFact("fact:ii_2:a_value", "ii_2", "系数 a", output_type="ParameterValue"),
            ProducedFact("fact:ii_2:m_value", "ii_2", "参数 m", output_type="ParameterValue"),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(
                    scope_id="ii_2",
                    label="第（Ⅱ）②问",
                    steps=(mixed_quadratic,),
                ),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for step in normalized.scopes[0].steps}
    assert [step.step_id for step in normalized.scopes[0].steps] == [
        "derive_parabola_ii2_solve_parameter",
        "derive_parabola_ii2",
    ]
    assert steps["derive_parabola_ii2_solve_parameter"].recipe_hint == (
        "parameter_from_minimum_value"
    )
    assert steps["derive_parabola_ii2_solve_parameter"].goal_type == (
        "derive_parameter_from_minimum_value"
    )
    assert [item.handle for item in steps["derive_parabola_ii2"].produces] == [
        "answer:ii_2.parabola"
    ]
    assert "fact:ii_2:m_value" in steps["derive_parabola_ii2"].reads
    assert "fact:ii_2:a_value" not in steps["derive_parabola_ii2"].reads
    assert {action.action for action in report.actions} >= {
        "split_mixed_quadratic_parameter_step",
        "drop_quadratic_coefficient_value_alias",
    }


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


def test_normalizer_links_adjacent_angle_sum_when_axis_step_omits_angle_read() -> None:
    """DeepSeek 漏读等角 fact 时，相邻 angle->axis 链路应由 normalizer 补齐。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_llm_problem())
    angle_step = StepIntent(
        scope_id="i_2",
        step_id="derive_angle_equality",
        recipe_hint="angle_sum_equal_angle_candidates",
        goal_type="derive_equal_angle",
        target="fact:i_2:angle_equality_result",
        strategy="由角和条件推出等角关系。",
        reads=(
            "point:problem:A",
            "point:problem:B",
            "point:problem:C",
            "point:problem:O",
            "fact:i_2:angle_sum_CBE_ACO_45",
        ),
        creates=(),
        produces=(
            ProducedFact(
                "fact:i_2:angle_equality_result",
                "i_2",
                "由角和条件推出的等角关系",
                output_type="AngleEquality",
            ),
        ),
        reason="真实 DeepSeek 首轮曾只产出泛化等角 fact。",
    )
    axis_step = StepIntent(
        scope_id="i_2",
        step_id="derive_F_coordinate",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept_from_equal_acute_angles",
        target="fact:i_2:F_coordinate",
        strategy="由等角关系求 BE 与 y 轴交点 F。",
        reads=(
            "point:problem:B",
            "point:problem:A",
            "point:problem:C",
            "point:problem:O",
        ),
        creates=(
            CreatedEntity(
                handle="point:i_2:F",
                entity_type="point",
                valid_scope="i_2",
                description="BE 与 y 轴的交点",
            ),
        ),
        produces=(
            ProducedFact(
                "fact:i_2:F_coordinate",
                "i_2",
                "F 点坐标",
                output_type="Point",
            ),
        ),
        reason="真实 draft 漏读前序 angle equality。",
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
        family_spec=_heping_inputs().family_spec,
        question_goals=_heping_inputs().question_goals,
        handle_registry=registry,
    )

    normalized_angle = normalized.scopes[0].steps[0]
    normalized_axis = normalized.scopes[0].steps[1]
    assert normalized_angle.target == "point:i_2:F"
    assert normalized_angle.creates == (
        CreatedEntity(
            "point:i_2:F",
            "point",
            "i_2",
            "由角和等角链路确定的轴截点目标",
        ),
    )
    assert normalized_axis.creates == ()
    assert normalized_angle.produces[0].handle == "fact:i_2:angle_OBF_eq_ACO"
    assert "fact:i_2:angle_OBF_eq_ACO" in normalized_axis.reads
    assert "fact:i_2:angle_equality_result" not in normalized_axis.reads
    assert "point:i_2:F" in normalized_axis.reads
    assert [action.action for action in report.actions[:3]] == [
        "infer_angle_sum_target_from_axis_intercept_step",
        "link_adjacent_angle_sum_to_axis_intercept_step",
        "normalize_angle_equality_fact_handle",
    ]


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


def test_midpoint_point_resolves_parametric_coordinate_endpoint_state() -> None:
    """midpoint_point 应能把 E_parametric_coordinate 识别为点 E 的可见状态。"""
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
                        reads=(
                            "fact:ii:A_coordinate_value",
                            "function:problem:parabola",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:ii:parabola_expression",
                                "ii",
                                "第（Ⅱ）问含参抛物线",
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
                        reads=("fact:ii:parabola_expression",),
                        produces=(
                            ProducedFact(
                                "fact:ii:E_parametric_coordinate",
                                "ii",
                                "E 点参数化坐标",
                                output_type="Point",
                            ),
                        ),
                    ),
                    _step(
                        scope_id="ii",
                        step_id="derive_F_midpoint_ii",
                        recipe_hint="midpoint_point",
                        goal_type="derive_midpoint_coordinate",
                        target="fact:ii:F_coordinate",
                        reads=(
                            "fact:ii:A_coordinate_value",
                            "fact:ii:E_parametric_coordinate",
                            "fact:ii:F_midpoint_of_AE",
                        ),
                        produces=(
                            ProducedFact(
                                "fact:ii:F_coordinate",
                                "ii",
                                "F 点坐标",
                                output_type="Point",
                            ),
                        ),
                    ),
                ),
            ),
        ),
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
    assert diagnostic.accepted_prefix[-1].step_id == "derive_F_midpoint_ii"
    assert "fact:ii:F_coordinate" in diagnostic.accepted_prefix[-1].produced_handles


def test_midpoint_point_requires_current_midpoint_definition_read() -> None:
    """midpoint_point 不应把 square_center step 误绑定到其它可见 midpoint fact。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _single_scope_draft(
        _step(
            scope_id="ii",
            step_id="derive_H_coordinate_ii",
            recipe_hint="midpoint_point",
            goal_type="derive_midpoint_coordinate",
            target="fact:ii:H_coordinate",
            reads=(
                "fact:ii:E_parametric_coordinate",
                "fact:ii:G_parametric_coordinate",
                "point:ii:H",
                "fact:ii:H_square_diagonal_intersection",
            ),
            produces=(
                ProducedFact(
                    "fact:ii:H_coordinate",
                    "ii",
                    "H 点坐标",
                    output_type="Point",
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

    assert output is None
    assert diagnostic.first_blocker is not None
    assert diagnostic.first_blocker.step_id == "derive_H_coordinate_ii"
    assert "midpoint_definition_not_read" in diagnostic.first_blocker.message
    assert "square_path_dimension_reduction" not in diagnostic.first_blocker.message
    assert "point:ii:F" not in diagnostic.first_blocker.message
    repair_summary = RepairFeedbackBuilder(diagnostic=diagnostic).build()
    assert repair_summary["current_blocker"]["message"] == (
        "midpoint_point 缺少 midpoint_definition read；square_center 不是中点定义。"
    )
    serialized_repair = json.dumps(repair_summary, ensure_ascii=False)
    assert "square_path_dimension_reduction" in serialized_repair


def test_normalizer_auto_creates_required_recipe_point() -> None:
    """recipe execution 声明 creates=point 时，LLM 可省略辅助点 creates。"""
    step = _step(
        scope_id="ii_1",
        step_id="straighten_reduced_path_ii1",
        recipe_hint="broken_path_straightening_and_select",
        goal_type="straighten_broken_path",
        target="选择折线拉直方案",
        reads=(
            "fact:ii:single_moving_path_equivalence",
            "point:ii:F",
            "point:ii:N",
        ),
        produces=(
            ProducedFact(
                "fact:ii:straightened_path_choice",
                "ii",
                "EG+FG 拉直后最短路径方案",
                output_type="StraighteningCandidate",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(
                    scope_id="ii_1",
                    label="第（Ⅱ）①问",
                    steps=(step,),
                ),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    normalized_step = normalized.scopes[0].steps[0]
    assert [item.handle for item in normalized_step.creates] == ["point:ii:Aux"]
    assert normalized_step.creates[0].entity_type == "point"
    assert any(
        action.action == "auto_create_required_recipe_entity"
        and action.handle == "point:ii:Aux"
        for action in report.actions
    )


def test_normalizer_folds_internal_equation_utility_into_parameter_step() -> None:
    """无 hint 的中间方程 utility 可折叠到唯一的参数求解消费者。"""
    relation = _step(
        scope_id="ii_2",
        step_id="derive_relation_am_ii2",
        recipe_hint=None,
        goal_type="derive_parameter",
        target="推导 a 与 m 的关系式",
        reads=(
            "point:ii:M",
            "point:ii:N",
            "fact:ii:M_coordinate_expr",
            "fact:ii:N_coordinate_expr",
            "fact:ii:M_on_parabola",
            "fact:ii:N_on_parabola",
            "fact:problem:coefficient_relation",
        ),
        produces=(
            ProducedFact(
                "fact:ii_2:parameter_relation_a_m",
                "ii_2",
                "a(m-2)=1",
                output_type="Equation",
            ),
        ),
    )
    solve_parameter = _step(
        scope_id="ii_2",
        step_id="solve_m_from_minimum_ii2",
        recipe_hint="parameter_from_minimum_value",
        goal_type="derive_parameter_from_minimum_value",
        target="fact:ii_2:m_value",
        reads=(
            "fact:ii_2:parameter_relation_a_m",
            "fact:ii_2:path_minimum_expression",
            "fact:ii_2:path_minimum_value_given",
        ),
        produces=(
            ProducedFact(
                "fact:ii_2:m_value",
                "ii_2",
                "②问 m 的值",
                output_type="ParameterValue",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope(
                    scope_id="ii_2",
                    label="第（Ⅱ）②问",
                    steps=(relation, solve_parameter),
                ),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    assert [step.step_id for step in normalized.scopes[0].steps] == [
        "solve_m_from_minimum_ii2"
    ]
    reads = normalized.scopes[0].steps[0].reads
    assert "fact:ii_2:parameter_relation_a_m" not in reads
    assert "fact:ii_2:path_minimum_expression" in reads
    assert "fact:ii:M_coordinate_expr" in reads
    assert "fact:ii:N_on_parabola" in reads
    assert any(
        action.action == "fold_internal_equation_utility_step"
        and action.step_id == "derive_relation_am_ii2"
        and action.target_step_id == "solve_m_from_minimum_ii2"
        for action in report.actions
    )


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


def test_normalizer_rewrites_square_reduction_coordinate_reads_to_structure_facts() -> None:
    """DeepSeek 若先求 F/H 坐标再降维，应改回 reduction 的结构 fact 契约。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    f_utility = _step(
        scope_id="ii",
        step_id="derive_F_coordinate_ii",
        recipe_hint="midpoint_point",
        goal_type="derive_midpoint_coordinate",
        target="fact:ii:F_coordinate",
        reads=(
            "fact:ii:A_coordinate_value",
            "fact:ii:E_parametric_coordinate",
            "point:ii:F",
            "fact:ii:F_midpoint_of_AE",
        ),
        produces=(
            ProducedFact("fact:ii:F_coordinate", "ii", "F 点坐标", output_type="Point"),
        ),
    )
    h_utility = _step(
        scope_id="ii",
        step_id="derive_H_coordinate_ii",
        recipe_hint="midpoint_point",
        goal_type="derive_midpoint_coordinate",
        target="fact:ii:H_coordinate",
        reads=(
            "fact:ii:E_parametric_coordinate",
            "fact:ii:G_parametric_coordinate",
            "point:ii:H",
            "fact:ii:H_square_diagonal_intersection",
        ),
        produces=(
            ProducedFact("fact:ii:H_coordinate", "ii", "H 点坐标", output_type="Point"),
        ),
    )
    reduction = _step(
        scope_id="ii",
        step_id="reduce_square_path_ii",
        recipe_hint="square_path_dimension_reduction",
        goal_type="reduce_square_path_dimension",
        target="fact:ii:reduced_path",
        reads=(
            "fact:ii:square_AEKG",
            "fact:ii:F_coordinate",
            "fact:ii:H_coordinate",
            "fact:ii:M_coordinate",
            "segment:ii:HF",
            "segment:ii:FM",
            "segment:ii:MG",
            "fact:ii:path_minimum_target",
        ),
        produces=(
            ProducedFact("fact:ii:reduced_path", "ii", "降维后的路径", output_type="PathTransformation"),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(f_utility, h_utility, reduction, scope_id="ii"),
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    assert [step.step_id for step in normalized.steps] == ["reduce_square_path_ii"]
    reads = normalized.steps[0].reads
    assert "fact:ii:F_coordinate" not in reads
    assert "fact:ii:H_coordinate" not in reads
    assert "fact:ii:F_midpoint_of_AE" in reads
    assert "fact:ii:H_square_diagonal_intersection" in reads
    assert [
        action.action for action in report.actions
        if action.action == "drop_square_pre_reduction_point_utility_step"
    ] == [
        "drop_square_pre_reduction_point_utility_step",
        "drop_square_pre_reduction_point_utility_step",
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


def test_normalizer_adds_split_straightening_endpoint_outputs_and_minimum_reads() -> None:
    """拆开的拉直 + 求距离 recipe 也应通过 endpoint metadata 连接。"""
    registry = _registry()
    straighten_step = StepIntent(
        scope_id="ii_1",
        step_id="straighten_reduced_path",
        recipe_hint="broken_path_straightening_and_select",
        goal_type="straighten_broken_path",
        target="fact:ii:straightened_candidate",
        strategy="选择折线拉直方案",
        reads=("fact:ii:path_transformation", "point:problem:D", "point:ii:M", "point:ii:N"),
        creates=(
            CreatedEntity(
                handle="point:ii:aux_point",
                entity_type="point",
                valid_scope="ii",
                description="折线拉直辅助点",
            ),
        ),
        produces=(
            ProducedFact(
                "fact:ii:straightened_candidate",
                "ii",
                "选定的折线拉直方案",
                output_type="StraighteningCandidate",
            ),
        ),
    )
    minimum_step = _step(
        scope_id="ii_1",
        step_id="compute_path_minimum_expression",
        recipe_hint="path_minimum_by_straightened_distance",
        goal_type="derive_minimum_value",
        target="fact:ii:path_minimum_expression",
        reads=(
            "fact:ii:straightened_candidate",
            "point:ii:aux_point",
            "point:ii:N",
        ),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "公共最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(straighten_step, minimum_step, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=registry,
    )

    straightened = normalized.steps[0]
    minimum = normalized.steps[1]
    assert {item.handle for item in straightened.produces} >= {
        "fact:ii:path_minimum_point_1",
        "fact:ii:path_minimum_point_2",
    }
    assert "fact:ii:path_minimum_point_1" in minimum.reads
    assert "fact:ii:path_minimum_point_2" in minimum.reads
    assert [action.action for action in report.actions] == [
        "add_broken_path_minimum_endpoint_outputs",
        "add_straightened_distance_endpoint_reads",
    ]


def test_split_straightened_distance_uses_endpoint_metadata_and_prepares_midpoint() -> None:
    """南开 split route 少写 F 坐标时，runtime 用拉直 endpoint metadata 补位。"""
    problem = _nankai_problem()
    inputs = _nankai_inputs()
    registry = _registry()
    payload = json.loads(NANKAI_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    retained_scopes = []
    for scope in payload["scopes"]:
        if scope["scope_id"] == "i":
            retained_scopes.append(scope)
            continue
        if scope["scope_id"] != "ii_1":
            continue
        trimmed_steps = []
        for step in scope["steps"]:
            if step["step_id"] == "derive_F_coordinate_expr":
                continue
            if step["step_id"] == "reduce_two_moving_points_path":
                step["reads"] = [
                    handle for handle in step["reads"]
                    if handle != "fact:ii:F_coordinate_expr"
                ]
            if step["step_id"] == "straighten_broken_path":
                step["reads"] = [
                    handle for handle in step["reads"]
                    if handle != "fact:ii:F_coordinate_expr"
                ]
            if step["step_id"] == "compute_minimum_expr":
                step["reads"] = [
                    "fact:ii:straightened_scheme",
                    "point:ii:Aux",
                    "point:problem:D",
                    "point:ii:N",
                ]
                step["target"] = "fact:ii:minimum_value_expr"
                step["produces"] = [
                    _produce(
                        "fact:ii:minimum_value_expr",
                        "ii",
                        "EG+FG 的公共最小值表达式",
                        output_type="MinimumExpression",
                    )
                ]
                trimmed_steps.append(step)
                break
            trimmed_steps.append(step)
        scope["steps"] = trimmed_steps
        retained_scopes.append(scope)
    payload["scopes"] = retained_scopes
    draft = StepIntentValidator().validate(payload, handle_registry=registry)

    output, diagnostic, effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    straightening_plan = next(plan for plan in output.step_plans if plan.step_id == "straighten_broken_path")
    has_midpoint_prep = any(
        invocation.method_id == "midpoint_point"
        and invocation.invocation_id.endswith(".prepare_F_midpoint_coordinate")
        for invocation in straightening_plan.invocations
    )
    has_midpoint_backfill = any(
        step.recipe_hint == "midpoint_point"
        and step.target == "fact:ii:F_coordinate_expr"
        for step in effective.steps
    )
    assert has_midpoint_prep or has_midpoint_backfill
    minimum_step = next(step for step in effective.steps if step.step_id == "compute_minimum_expr")
    assert "fact:ii:path_minimum_point_1" in minimum_step.reads
    assert "fact:ii:path_minimum_point_2" in minimum_step.reads
    minimum_plan = next(plan for plan in output.step_plans if plan.step_id == "compute_minimum_expr")
    distance_invocation = minimum_plan.invocations[0]
    assert distance_invocation.method_id == "distance_between_points"
    assert distance_invocation.inputs["p1"] == "$question.ii.outputs.path_minimum_point_1"
    assert distance_invocation.inputs["p2"] == "$question.ii.outputs.path_minimum_point_2"


def test_normalizer_inserts_locus_line_before_broken_path_minimum() -> None:
    """缺少动点轨迹线 step 时，应由 normalizer 补出 prerequisite。"""
    problem = _heping_ermo_problem()
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    payload = json.loads(HEPING_ERMO_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    original = StepIntentValidator().validate(payload, handle_registry=registry)
    ii_steps: list[StepIntent] = []
    for step in original.steps:
        if step.scope_id != "ii":
            continue
        if step.step_id == "derive_G_locus_line":
            continue
        if step.recipe_hint == "broken_path_straightening_minimum_expression":
            ii_steps.append(
                replace(
                    step,
                    reads=tuple(
                        read for read in step.reads
                        if read != "fact:ii:G_locus_line"
                    ),
                )
            )
            break
        ii_steps.append(step)
    draft = _single_scope_draft(*ii_steps, scope_id="ii")

    normalized, report = StepIntentNormalizer().normalize(
        draft,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    normalized_steps = list(normalized.steps)
    step_ids = [step.step_id for step in normalized_steps]
    assert step_ids.index("derive_G_locus_line") < step_ids.index("derive_path_minimum_expr")
    minimum_step = next(
        step for step in normalized_steps
        if step.step_id == "derive_path_minimum_expr"
    )
    assert "fact:ii:G_locus_line" in minimum_step.reads
    assert any(
        action.action == "insert_square_path_locus_line_backfill_step"
        for action in report.actions
    )

    output, diagnostic, effective = RecipeTrialExecutor().diagnose(
        normalized,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert output is not None
    assert diagnostic.ok is True
    effective_steps = list(effective.steps)
    step_ids = [step.step_id for step in effective_steps]
    assert step_ids.index("derive_G_locus_line") < step_ids.index("derive_path_minimum_expr")
    minimum_step = next(
        step for step in effective_steps
        if step.step_id == "derive_path_minimum_expr"
    )
    assert "fact:ii:G_locus_line" in minimum_step.reads
    accepted_ids = [step.step_id for step in diagnostic.accepted_prefix]
    assert "derive_G_locus_line" in accepted_ids
    locus_plan = next(plan for plan in output.step_plans if plan.step_id == "derive_G_locus_line")
    assert [invocation.method_id for invocation in locus_plan.invocations] == [
        "parameterized_point_locus_line"
    ]


def test_normalizer_reuses_existing_locus_line_without_duplicate() -> None:
    """locus line step 已存在时，只补当前 reads，不重复插入 prerequisite。"""
    inputs = _heping_ermo_inputs()
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    payload = json.loads(HEPING_ERMO_EXECUTABLE_STEP_INTENTS.read_text(encoding="utf-8"))
    original = StepIntentValidator().validate(payload, handle_registry=registry)
    ii_steps: list[StepIntent] = []
    for step in original.steps:
        if step.scope_id != "ii":
            continue
        if step.recipe_hint == "broken_path_straightening_minimum_expression":
            ii_steps.append(
                replace(
                    step,
                    reads=tuple(
                        read for read in step.reads
                        if read != "fact:ii:G_locus_line"
                    ),
                )
            )
            break
        ii_steps.append(step)
    draft = _single_scope_draft(*ii_steps, scope_id="ii")

    normalized, report = StepIntentNormalizer().normalize(
        draft,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    steps = list(normalized.steps)
    assert [step.step_id for step in steps].count("derive_G_locus_line") == 1
    minimum_step = next(
        step for step in steps
        if step.recipe_hint == "broken_path_straightening_minimum_expression"
    )
    assert "fact:ii:G_locus_line" in minimum_step.reads
    assert any(
        action.action == "add_square_path_locus_line_read"
        for action in report.actions
    )


def test_normalizer_merges_null_hint_point_answer_to_existing_coordinate() -> None:
    """裸 Point answer step 若只是收口已有同点坐标，应合并为 answer alias。"""
    coordinate_step = _step(
        scope_id="ii",
        step_id="derive_G_coordinate",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point_at_parameter",
        target="fact:ii:G_coordinate",
        reads=("fact:ii:G_coordinate_expr", "fact:ii_2:m_value"),
        produces=(
            ProducedFact(
                "fact:ii:G_coordinate",
                "ii",
                "G 的坐标",
                output_type="Point",
            ),
        ),
    )
    answer_step = _step(
        scope_id="ii_2",
        step_id="collect_G_answer",
        recipe_hint=None,
        goal_type="derive_extremal_point",
        target="answer:ii_2.intersection",
        reads=("fact:ii:G_coordinate",),
        produces=(
            ProducedFact(
                "answer:ii_2.intersection",
                "ii_2",
                "第（Ⅱ）②问 G 的坐标",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope("ii", "第（Ⅱ）问", (coordinate_step,)),
                StepIntentScope("ii_2", "第（Ⅱ）②问", (answer_step,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    ii_step = normalized.scopes[0].steps[0]
    assert [step.step_id for step in normalized.scopes[1].steps] == []
    assert {item.handle for item in ii_step.produces} == {
        "fact:ii:G_coordinate",
        "answer:ii_2.intersection",
    }
    assert any(
        action.action == "merge_point_answer_alias_to_existing_state"
        and action.handle == "answer:ii_2.intersection"
        for action in report.actions
    )


def test_normalizer_adds_known_symbol_value_reads_for_quadratic_constraints() -> None:
    """quadratic_from_constraints 读取 symbol 时，应自动补题面已知 value fact。"""
    step = _step(
        scope_id="i",
        step_id="derive_parabola_i",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="answer:i.parabola",
        reads=(
            "symbol:problem:a",
            "symbol:problem:c",
            "fact:problem:coefficient_relation",
        ),
        produces=(
            ProducedFact(
                "answer:i.parabola",
                "i",
                "第（Ⅰ）问抛物线",
                output_type="Parabola",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(step, scope_id="i"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    reads = normalized.scopes[0].steps[0].reads
    assert "fact:i:a_value" in reads
    assert "fact:i:c_value" in reads
    assert [
        action.handle for action in report.actions
        if action.action == "add_known_symbol_value_read"
    ] == ["fact:i:a_value", "fact:i:c_value"]


def test_normalizer_reuses_existing_midpoint_coordinate_backfill() -> None:
    """已有同一 midpoint 坐标时，不应再插入 *_coordinate_expr backfill。"""
    midpoint_step = _step(
        scope_id="ii_1",
        step_id="derive_F_coordinate",
        recipe_hint="midpoint_point",
        goal_type="derive_midpoint",
        target="fact:ii:F_coordinate",
        reads=("fact:problem:D_coordinate", "fact:ii:N_coordinate_expr"),
        produces=(
            ProducedFact(
                "fact:ii:F_coordinate",
                "ii",
                "F 的坐标",
                output_type="Point",
            ),
        ),
    )
    minimum_step = _step(
        scope_id="ii_1",
        step_id="derive_path_minimum_expr",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        reads=(
            "point:problem:D",
            "point:ii:M",
            "point:ii:N",
            "point:ii:F",
            "fact:ii:F_midpoint_of_DN",
            "fact:ii:path_minimum_target",
        ),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "路径最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(midpoint_step, minimum_step, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    step_ids = [step.step_id for step in normalized.scopes[0].steps]
    assert "derive_F_coordinate_expr" not in step_ids
    normalized_midpoint = normalized.scopes[0].steps[0]
    assert "fact:ii:F_midpoint_of_DN" in normalized_midpoint.reads
    normalized_minimum = normalized.scopes[0].steps[-1]
    assert "fact:ii:F_coordinate" in normalized_minimum.reads
    assert "fact:ii:F_coordinate_expr" not in normalized_minimum.reads
    assert any(
        action.action == "add_midpoint_definition_read"
        and action.handle == "fact:ii:F_midpoint_of_DN"
        for action in report.actions
    )
    assert any(
        action.action == "reuse_existing_midpoint_coordinate_fact"
        and action.handle == "fact:ii:F_coordinate"
        for action in report.actions
    )


def test_normalizer_inserts_path_transformation_backfill_for_combined_minimum_recipe() -> None:
    """combined broken-path recipe 缺 PathTransformation 时应补公开降维 prerequisite。"""
    minimum_step = _step(
        scope_id="ii_1",
        step_id="derive_path_minimum_expr",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        reads=(
            "point:problem:D",
            "point:ii:M",
            "point:ii:N",
            "fact:ii:segment_DE_eq_sqrt2_NG",
            "fact:ii:segment_E_on_DM",
            "fact:ii:segment_G_on_MN",
            "fact:ii:M_coordinate_expr",
            "fact:ii:N_coordinate_expr",
            "fact:problem:D_coordinate",
        ),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                "路径最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        _single_scope_draft(minimum_step, scope_id="ii_1"),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = normalized.scopes[0].steps
    assert steps[0].recipe_hint == "two_moving_points_path_reduction"
    assert steps[0].target == "fact:ii:path_transformation"
    assert "fact:ii:path_minimum_target" in steps[0].reads
    assert steps[1].step_id == "derive_path_minimum_expr"
    assert "fact:ii:path_transformation" in steps[1].reads
    assert any(
        action.action == "insert_path_transformation_backfill_step"
        and action.handle == "fact:ii:path_transformation"
        for action in report.actions
    )


def test_normalizer_promotes_sibling_common_minimum_expression_read() -> None:
    """后续 sibling 读取公共 MinimumExpression 时，应提升源 output 到父 scope。"""
    local_endpoint_step = _step(
        scope_id="ii_1",
        step_id="derive_local_endpoint",
        recipe_hint="evaluate_point_at_parameter",
        goal_type="evaluate_point_at_parameter",
        target="fact:ii_1:local_endpoint_coordinate",
        produces=(
            ProducedFact(
                "fact:ii_1:local_endpoint_coordinate",
                "ii_1",
                "局部端点坐标",
                output_type="Point",
            ),
        ),
    )
    minimum_step = _step(
        scope_id="ii_1",
        step_id="compute_minimum_expression",
        recipe_hint="path_minimum_by_straightened_distance",
        goal_type="derive_minimum_value",
        target="fact:ii_1:path_minimum_expr",
        reads=("fact:ii_1:local_endpoint_coordinate",),
        produces=(
            ProducedFact(
                "fact:ii_1:path_minimum_expr",
                "ii_1",
                "适用于第（Ⅱ）问所有子问的路径最小值表达式",
                output_type="MinimumExpression",
            ),
        ),
    )
    local_consumer_step = _step(
        scope_id="ii_1",
        step_id="evaluate_local_minimum",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="evaluate_expression_at_parameter",
        target="answer:ii_1.minimum_value",
        reads=("fact:ii_1:path_minimum_expr", "fact:ii_1:m_value"),
        produces=(
            ProducedFact(
                "answer:ii_1.minimum_value",
                "ii_1",
                "第（Ⅱ）①问最小值",
                output_type="MinimumExpression",
            ),
        ),
    )
    solve_step = _step(
        scope_id="ii_2",
        step_id="solve_m_by_minimum",
        recipe_hint="parameter_from_minimum_value",
        goal_type="derive_parameter",
        target="fact:ii_2:m_value",
        reads=(
            "fact:ii_1:path_minimum_expr",
            "fact:ii_2:path_minimum_value_given",
        ),
        produces=(
            ProducedFact(
                "fact:ii_2:m_value",
                "ii_2",
                "m 的值",
                output_type="ParameterValue",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope("ii_1", "第（Ⅱ）①问", (local_endpoint_step, minimum_step, local_consumer_step)),
                StepIntentScope("ii_2", "第（Ⅱ）②问", (solve_step,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    promoted_step = normalized.scopes[0].steps[1]
    assert promoted_step.target == "fact:ii:path_minimum_expr"
    assert promoted_step.produces[0].handle == "fact:ii:path_minimum_expr"
    assert promoted_step.produces[0].valid_scope == "ii"
    normalized_local_consumer = normalized.scopes[0].steps[2]
    assert "fact:ii:path_minimum_expr" in normalized_local_consumer.reads
    assert "fact:ii_1:path_minimum_expr" not in normalized_local_consumer.reads
    normalized_solve = normalized.scopes[1].steps[0]
    assert "fact:ii:path_minimum_expr" in normalized_solve.reads
    assert "fact:ii_1:path_minimum_expr" not in normalized_solve.reads
    assert any(
        action.action == "promote_sibling_common_output_read"
        and action.handle == "fact:ii_1:path_minimum_expr"
        for action in report.actions
    )


def test_normalizer_drops_duplicate_producer_after_common_scope_promotion() -> None:
    """公共状态被 sibling scope 同时产生时，promotion 后应只保留首个 producer。"""
    first_reduction = _step(
        scope_id="ii_1",
        step_id="reduce_path_first",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii_1:reduced_path_equivalence",
        produces=(
            ProducedFact(
                "fact:ii_1:reduced_path_equivalence",
                "ii_1",
                "第一个 sibling 产生的公共路径转换",
                output_type="PathTransformation",
            ),
        ),
    )
    duplicate_reduction = _step(
        scope_id="ii_2",
        step_id="reduce_path_duplicate",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii_2:reduced_path_equivalence",
        produces=(
            ProducedFact(
                "fact:ii_2:reduced_path_equivalence",
                "ii_2",
                "第二个 sibling 重复产生的公共路径转换",
                output_type="PathTransformation",
            ),
        ),
    )
    consumer = _step(
        scope_id="ii_2",
        step_id="consume_reduced_path",
        recipe_hint="path_minimum_by_straightened_distance",
        goal_type="derive_minimum_value",
        target="fact:ii_2:minimum_expression",
        reads=("fact:ii_2:reduced_path_equivalence",),
        produces=(
            ProducedFact(
                "fact:ii_2:minimum_expression",
                "ii_2",
                "使用公共路径转换后的最小值表达式",
                output_type="Expression",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope("ii_1", "第（Ⅱ）①问", (first_reduction,)),
                StepIntentScope("ii_2", "第（Ⅱ）②问", (duplicate_reduction, consumer)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for scope in normalized.scopes for step in scope.steps}
    assert "reduce_path_duplicate" not in steps
    assert steps["reduce_path_first"].target == "fact:ii:reduced_path_equivalence"
    assert steps["reduce_path_first"].produces[0].handle == "fact:ii:reduced_path_equivalence"
    assert steps["consume_reduced_path"].reads == ("fact:ii:reduced_path_equivalence",)
    produced_handles = [
        item.handle
        for scope in normalized.scopes
        for step in scope.steps
        for item in step.produces
    ]
    assert produced_handles.count("fact:ii:reduced_path_equivalence") == 1
    assert any(
        action.action == "drop_duplicate_producer_step"
        and action.step_id == "reduce_path_duplicate"
        and action.target_step_id == "reduce_path_first"
        for action in report.actions
    )


def test_normalizer_merges_duplicate_path_transformation_signature_handles() -> None:
    """同一 valid_scope 的 PathTransformation 即使 handle 不同，也应复用首个状态。"""
    first_reduction = _step(
        scope_id="ii_1",
        step_id="reduce_path_ii1",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii:reduced_path_equivalence",
        produces=(
            ProducedFact(
                "fact:ii:reduced_path_equivalence",
                "ii",
                "公共路径转换",
                output_type="PathTransformation",
            ),
        ),
    )
    duplicate_reduction = _step(
        scope_id="ii_2",
        step_id="reduce_path_ii2",
        recipe_hint="two_moving_points_path_reduction",
        goal_type="reduce_path_expression",
        target="fact:ii:reduced_path_expr_in_m",
        produces=(
            ProducedFact(
                "fact:ii:reduced_path_expr_in_m",
                "ii",
                "同一公共路径转换的另一种命名",
                output_type="PathTransformation",
            ),
        ),
    )
    consumer = _step(
        scope_id="ii_2",
        step_id="straighten_path_ii2",
        recipe_hint="broken_path_straightening_and_select",
        goal_type="straighten_broken_path",
        target="fact:ii:straightened_candidate_in_m",
        reads=("fact:ii:reduced_path_expr_in_m",),
        produces=(
            ProducedFact(
                "fact:ii:straightened_candidate_in_m",
                "ii",
                "读取公共转换后的拉直候选",
                output_type="StraighteningCandidate",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope("ii_1", "第（Ⅱ）①问", (first_reduction,)),
                StepIntentScope("ii_2", "第（Ⅱ）②问", (duplicate_reduction, consumer)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for scope in normalized.scopes for step in scope.steps}
    assert "reduce_path_ii2" not in steps
    assert steps["straighten_path_ii2"].reads == ("fact:ii:reduced_path_equivalence",)
    assert any(
        action.action == "drop_duplicate_produced_state"
        and action.step_id == "reduce_path_ii2"
        and action.target_step_id == "reduce_path_ii1"
        and action.handle == "fact:ii:reduced_path_expr_in_m"
        for action in report.actions
    )
    assert any(
        action.action == "rewrite_duplicate_produced_state_read"
        and action.step_id == "straighten_path_ii2"
        and action.handle == "fact:ii:reduced_path_expr_in_m"
        for action in report.actions
    )


def test_normalizer_removes_duplicate_output_but_keeps_unique_outputs() -> None:
    """若 step 只有部分 output 重复，删除重复 produced 并保留唯一 output。"""
    first_candidate = _step(
        scope_id="ii_1",
        step_id="straighten_first",
        recipe_hint="broken_path_straightening_and_select",
        goal_type="straighten_broken_path",
        target="fact:ii_1:straightening_candidate",
        produces=(
            ProducedFact(
                "fact:ii_1:straightening_candidate",
                "ii_1",
                "第一个 sibling 产生的公共拉直方案",
                output_type="StraighteningCandidate",
            ),
        ),
    )
    duplicate_with_endpoint = _step(
        scope_id="ii_2",
        step_id="straighten_duplicate_with_endpoint",
        recipe_hint="broken_path_straightening_and_select",
        goal_type="straighten_broken_path",
        target="fact:ii_2:straightening_candidate",
        produces=(
            ProducedFact(
                "fact:ii_2:straightening_candidate",
                "ii_2",
                "第二个 sibling 重复产生的公共拉直方案",
                output_type="StraighteningCandidate",
            ),
            ProducedFact(
                "fact:ii_2:path_minimum_point_1",
                "ii_2",
                "第二个 sibling 仍需保留的唯一端点",
                output_type="Point",
            ),
        ),
    )

    normalized, report = StepIntentNormalizer().normalize(
        StepIntentDraft(
            scopes=(
                StepIntentScope("ii_1", "第（Ⅱ）①问", (first_candidate,)),
                StepIntentScope("ii_2", "第（Ⅱ）②问", (duplicate_with_endpoint,)),
            )
        ),
        family_spec=_nankai_inputs().family_spec,
        question_goals=_question_goals(),
        handle_registry=_registry(),
    )

    steps = {step.step_id: step for scope in normalized.scopes for step in scope.steps}
    retained = steps["straighten_duplicate_with_endpoint"]
    assert retained.target == "fact:ii_2:path_minimum_point_1"
    retained_handles = [item.handle for item in retained.produces]
    assert "fact:ii:straightening_candidate" not in retained_handles
    assert "fact:ii_2:path_minimum_point_1" in retained_handles
    produced_handles = [
        item.handle
        for scope in normalized.scopes
        for step in scope.steps
        for item in step.produces
    ]
    assert produced_handles.count("fact:ii:straightening_candidate") == 1
    assert any(
        action.action == "drop_duplicate_produced_handle"
        and action.step_id == "straighten_duplicate_with_endpoint"
        and action.target_step_id == "straighten_first"
        and action.handle == "fact:ii:straightening_candidate"
        for action in report.actions
    )


def test_normalizer_rewrites_square_final_parameter_substitution_to_vertex_recovery() -> None:
    """已有最短状态 G 时，最终 E 应用正方形关系恢复，而不是代入残留动点参数。"""
    registry = CanonicalHandleRegistry.from_problem_payload(_heping_ermo_llm_problem())
    draft = _single_scope_draft(
        _step(
            scope_id="ii",
            step_id="solve_parameter_c",
            recipe_hint="parameter_from_expression_value",
            goal_type="derive_parameter_from_expression_value",
            target="fact:ii:c_value",
            reads=(
                "fact:ii:path_minimum_expression",
                "fact:ii:path_minimum_value_given",
            ),
            produces=(
                ProducedFact(
                    "fact:ii:c_value",
                    "ii",
                    "参数 c",
                    output_type="ParameterValue",
                ),
            ),
        ),
        _step(
            scope_id="ii",
            step_id="derive_optimal_G",
            recipe_hint="line_locus_minimum_point",
            goal_type="derive_line_locus_minimum_point",
            target="fact:ii:optimal_G_coordinate",
            reads=(
                "fact:ii:G_locus_line",
                "fact:ii:path_minimum_point_1",
                "fact:ii:path_minimum_point_2",
                "fact:ii:c_value",
            ),
            produces=(
                ProducedFact(
                    "fact:ii:optimal_G_coordinate",
                    "ii",
                    "最短状态 G 坐标",
                    output_type="Point",
                ),
            ),
        ),
        _step(
            scope_id="ii",
            step_id="derive_e_value",
            recipe_hint="parameter_from_expression_value",
            goal_type="derive_parameter_from_expression_value",
            target="fact:ii:e_value",
            reads=(
                "fact:ii:G_parametric_coordinate",
                "fact:ii:optimal_G_coordinate",
                "fact:ii:c_value",
            ),
            produces=(
                ProducedFact(
                    "fact:ii:e_value",
                    "ii",
                    "E 纵坐标参数",
                    output_type="ParameterValue",
                ),
            ),
        ),
        _step(
            scope_id="ii",
            step_id="evaluate_E",
            recipe_hint="evaluate_point_at_parameter",
            goal_type="evaluate_point_at_parameter",
            target="answer:ii.E",
            reads=(
                "fact:ii:E_parametric_coordinate",
                "fact:ii:e_value",
                "fact:ii:c_value",
            ),
            produces=(
                ProducedFact(
                    "answer:ii.E",
                    "ii",
                    "最终 E 坐标",
                    output_type="Point",
                ),
            ),
        ),
        scope_id="ii",
    )

    normalized, report = StepIntentNormalizer().normalize(
        draft,
        family_spec=QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
        question_goals=extract_question_goals(_heping_ermo_problem()),
        handle_registry=registry,
    )

    final_step = normalized.scopes[0].steps[-1]
    assert final_step.step_id == "evaluate_E"
    assert final_step.recipe_hint == "square_adjacent_vertex_from_side"
    assert final_step.goal_type == "derive_square_adjacent_vertex"
    assert "fact:ii:square_AEKG" in final_step.reads
    assert "fact:ii:A_coordinate_value" in final_step.reads
    assert "fact:ii:optimal_G_coordinate" in final_step.reads
    assert "fact:ii:c_value" in final_step.reads
    assert "fact:ii:e_value" not in final_step.reads
    assert any(
        action.action == "rewrite_square_final_parameter_substitution_to_vertex_recovery"
        for action in report.actions
    )


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
