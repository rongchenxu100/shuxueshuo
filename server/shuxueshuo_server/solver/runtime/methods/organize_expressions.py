"""Validate an authored rational rewrite chain and return one expression state."""

from __future__ import annotations

from jsonschema import ValidationError

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec
from shuxueshuo_server.solver.math_kernel.expression_rewrite import (
    RewriteError,
    verify_chain,
)
from shuxueshuo_server.solver.runtime.method_parameters import validate_parameters

from ._common import *
from ._spec import MethodSpecSource, declare_input_views

PARAMETERS_SCHEMA = {
    "type": "object",
    "required": ["steps"],
    "additionalProperties": False,
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 2,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["math"],
                "additionalProperties": False,
                "properties": {
                    "math": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "using": {
                        "type": "array",
                        "maxItems": 8,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 1024},
                    },
                },
            },
        }
    },
}

PROMPT = """调用 organize_expressions，为后续应用二元基本不等式整理目标表达式。
只输出提供的调用 JSON 协议。args 引用目录中已有的表达式和条件。
parameters.steps 每行 math 写完整表达式，从当前目标开始，保留关键中间式；
使用已知条件到达本行时填写 using（条件的数学式）。每行一次主要变形。
使用显式乘号 *、除号 /、括号和整数幂 ^；不写自然语言、操作标签或答案。
不能引入新变量，不能应用不等式。"""


class OrganizeExpressionsMethod:
    """整理式子：验证 LLM 推导，保留原结构，返回同对象的一个最终状态。"""

    method_id = "organize_expressions"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = inputs["expression"]
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            symbols = {s.name: s for s in expression.free_symbols}
            trace = verify_chain(
                expression,
                list(inputs.get("conditions", [])),
                parameters["steps"],
                symbols,
            )
        except ValidationError as exc:
            raise method_input_invalid(
                "推导参数不符合 schema",
                method_id=self.method_id,
                observed={"path": list(exc.absolute_path)},
                repair_action="repair_derivation",
            ) from exc
        except RewriteError as exc:
            raise method_input_invalid(
                str(exc),
                method_id=self.method_id,
                observed={"code": exc.code, "row": exc.row},
                repair_action="repair_derivation",
            ) from exc
        value = trace.pop("value")
        sources = inputs.get("__condition_sources__", [])
        for card in trace["conditionCards"]:
            index = card["boundIndex"]
            if index < len(sources):
                card["source"] = sources[index]
        trace.update(
            {
                "kind": "verified_expression_rewrite",
                "method_id": self.method_id,
                "title": "整理目标式",
                "goal": "整理目标表达式",
                "reason": "逐步等价变形",
                "calculation": trace["source"]["latex"]
                + "="
                + trace["result"]["latex"],
                "conclusion": trace["result"]["latex"],
            }
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "organized_expression": TypedValue(
                    "Expression", value, source=self.method_id
                )
            },
            checks=[
                _check(name, True, label)
                for name, label in (
                    ("rewrite_input_bound", "输入与链首一致"),
                    ("rewrite_domain_verified", "所有分母非零"),
                    ("rewrite_equivalence_verified", "逐步等价验证通过"),
                    ("rewrite_conditions_bound", "条件引用已绑定"),
                )
            ],
            trace_fragments=[trace],
        )


SPEC = MethodSpecSource(
    method_cls=OrganizeExpressionsMethod,
    title="整理式子",
    solves=("organize_expressions",),
    inputs={
        "expression": {
            "type": "Expression",
            "required": True,
            "state_kind": "expression",
        },
        "conditions": {"type": "ConditionList", "required": False},
    },
    input_views=declare_input_views(
        latest_state=("expression",), immutable_value=("conditions",)
    ),
    outputs={"organized_expression": "Expression"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="按 parameters.steps 验证完整有理式推导链；只返回最终表达式，不求极值。",
    preconditions=("所有变量和使用的条件已有绑定",),
    postconditions=("最终式与输入在原定义域上等价",),
    explanation=MethodExplanationSpec(
        role_schema={
            "source": "原式",
            "result": "整理结果",
            "derive_items": "已验证推导",
        },
        student_goal_template="整理目标表达式",
        student_title_template="整理目标式",
        student_nav_title_template="整理目标式",
        box_templates=("{result}",),
        role_binder_id="expression_rewrite",
    ),
    visual=MethodVisualSpec(
        role_schema={"rewrite": "已验证推导记录"},
        scene_templates=({"kind": "expression_rewrite"},),
        timeline_templates=({"kind": "expression_rewrite_beats"},),
        role_binder_id="expression_rewrite",
    ),
)
