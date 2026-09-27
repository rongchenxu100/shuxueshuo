"""Verify a submitted scalar substitution and retain original-target authority."""

from jsonschema import ValidationError

from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.math_kernel.substitution import (
    verify_substitution,
)
from shuxueshuo_server.solver.runtime.method_parameters import validate_parameters

from ...explanation.substitution import UNITS
from ._common import *
from ._spec import MethodSpecSource, declare_input_views
from .apply_two_term_amgm import PARAMETERS_SCHEMA as AMGM_PARAMETERS

PARAMETERS_SCHEMA = {
    "type": "object",
    "required": ["definitions", "steps", "expression"],
    "additionalProperties": False,
    "properties": {
        "definitions": {
            "type": "object",
            "minProperties": 1,
            "maxProperties": 2,
            "additionalProperties": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1024,
            },
        },
        "steps": AMGM_PARAMETERS["properties"]["steps"],
        "expression": {"type": "string", "minLength": 1, "maxLength": 1024},
    },
}


class SubstituteExpressionsMethod:
    method_id = "substitute_expressions"

    def run(self, inputs, kernel):
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            evidence, _ = verify_substitution(inputs["target"], parameters)
        except (
            ProofFailure,
            MathParseError,
            ValidationError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise method_input_invalid(
                str(exc),
                method_id=self.method_id,
                observed={"code": getattr(exc, "code", "invalid_input")},
                repair_action="repair_derivation",
            ) from exc
        return StatelessMethodResult(
            self.method_id,
            {
                "substitution": TypedValue(
                    "Substitution", evidence, source=self.method_id
                )
            },
            checks=[
                _check(
                    "substitution_verified",
                    True,
                    "换元定义、定义域与目标等价关系已验证",
                )
            ],
            trace_fragments=[
                {
                    "kind": "verified_substitution",
                    "method_id": self.method_id,
                    "source_target": inputs["target"],
                    "evidence": evidence,
                }
            ],
        )


SPEC = MethodSpecSource(
    method_cls=SubstituteExpressionsMethod,
    title="换元",
    solves=("substitute_expressions",),
    inputs={
        "target": {
            "type": "Condition",
            "required": True,
            "role": "题面极值目标及完整原条件，不是某一条等式条件",
        }
    },
    input_views=declare_input_views(immutable_value=("target",)),
    outputs={"substitution": "Substitution"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="引入一至两个新变量，definitions 为新变量名到原变量表达式的映射，如 {u: x-1, v: y-1} 或 {u: x^2, v: y^2}。本阶段每个定义仅含一个不同的原变量，支持有理系数一次式和单变量平方。禁止覆盖原变量或引用未定义符号。steps[].math 只提交必要关系，避免堆叠等价冗余等式。证明差式为正时可先把差式改写成已知正项的乘积或商，并提交此等式；不会自动搜索这些变形。steps[].math 提交必要正性、非零及换元后条件；全部验证，不能将平方直接断言为正数。expression 写按定义直接换元后的完整目标，只能作恒等整理，不能利用条件消去新变量。需要消元时将 substitution 输出交给 eliminate_by_constraint，并保持同一 target。代码保存所有原条件和一次/平方的完整反解分支。后续 M11 显式绑定 substitution 结果；M13 仍提交所有原变量的具体取值，代码按定义计算新变量并验证，不自动搜索取值。",
    teaching_units=UNITS,
    no_new_visual_reason="换元是标量关系变形，不新增几何对象。",
)
