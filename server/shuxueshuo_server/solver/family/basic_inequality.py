"""Basic inequality declaration for authoring; production admission is deferred.

Planning prose lives in basic-inequality-strategy.json. Neither the six planning
methods nor these reserved recipe/rule IDs authorize runtime execution.
"""

from .capability_packs import DEFAULT_CAPABILITY_PACK_REGISTRY
from .models import (
    FamilyMatchRule,
    FamilySourceRequirementSpec,
    SolverFamilySpec,
    expand_family_spec,
)


BASIC_INEQUALITY_FAMILY = expand_family_spec(
    SolverFamilySpec(
        family_id="basic_inequality",
        teaching_template="basic-inequality-v1.jinja",
        strategy_reference="internal/llm-prompts/basic-inequality-strategy.json",
        match=FamilyMatchRule(
            patterns=("basic-inequality",),
            problem_types=("basic_inequality",),
        ),
        title="基本不等式",
        description=(
            "由变量条件及代数等式或不等式约束，求表达式的最大值、最小值、"
            "取值范围或参数值；需验证求界依据、取等和原变量可达性。"
        ),
        use_when=(
            "题面给出变量域与代数关系，并明确提出最值、范围或参数目标；"
            "正项可以由原条件证明，不要求所有原变量均为正数。"
        ),
        required_source_requirements=(
            FamilySourceRequirementSpec(
                "entity_type", ("symbol",), "题面至少声明一个代数变量或参数。",
            ),
            FamilySourceRequirementSpec(
                "fact_type",
                ("equation", "symbol_constraint"),
                "题面至少给出一个等式或变量约束；不得添加未给出的正性条件。",
            ),
        ),
        do_not_use_when=(
            "题面缺少变量条件、代数关系或明确的最值、范围、参数目标。",
            "目标为几何路径最值且依赖射线、反射或加权几何构造。",
            "题目仅要求一般方程求解或函数量词证明，没有本题型的代数求界目标。",
        ),
        common_goal_types=(
            "derive_maximum_value",
            "derive_minimum_value",
            "derive_range",
            "derive_parameter",
        ),
        mechanism_packs=("basic_inequality_core",),
        explanation_rule_ids=(
            "basic_inequality.expression_chain",
            "basic_inequality.bound_application",
            "basic_inequality.equality_restore",
        ),
    ),
    DEFAULT_CAPABILITY_PACK_REGISTRY,
)
