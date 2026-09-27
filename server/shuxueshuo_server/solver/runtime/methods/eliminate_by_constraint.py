"""Verify a submitted scalar elimination and retain original-target authority."""

from jsonschema import ValidationError

from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
    verify_elimination,
)
from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.runtime.method_parameters import validate_parameters

from ...explanation.elimination import UNIT
from ._common import *
from ._spec import MethodSpecSource, declare_input_views
from .apply_two_term_amgm import PARAMETERS_SCHEMA as AMGM_PARAMETERS

PARAMETERS_SCHEMA = {
    "type": "object",
    "required": ["eliminate", "steps", "expression"],
    "additionalProperties": False,
    "properties": {
        "eliminate": {"type": "string", "minLength": 1, "maxLength": 64},
        "steps": {
            **AMGM_PARAMETERS["properties"]["steps"],
            "description": "提交由原条件得到的等式变形、分母正性或非零关系，以及唯一的显式还原公式。支持 ∵/∴、逗号或分号和关系链；每条关系均须证明，不允许不等式估计或未声明符号。变量乘法用 *。",
        },
        "expression": {"type": "string", "minLength": 1, "maxLength": 1024},
    },
}


class EliminateByConstraintMethod:
    method_id = "eliminate_by_constraint"

    def run(self, inputs, kernel):
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            evidence, _ = verify_elimination(
                inputs["target"], parameters, substitution=inputs.get("substitution")
            )
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
                "elimination": TypedValue(
                    "ConstraintElimination", evidence, source=self.method_id
                )
            },
            checks=[
                _check("elimination_verified", True, "条件变形、定义域及目标代入已验证")
            ],
            trace_fragments=[
                {
                    "kind": "verified_constraint_elimination",
                    "method_id": self.method_id,
                    "source_target": inputs["target"],
                    "evidence": evidence,
                }
            ],
        )


SPEC = MethodSpecSource(
    method_cls=EliminateByConstraintMethod,
    title="条件消元",
    solves=("eliminate_by_constraint",),
    inputs={
        "target": {
            "type": "Condition",
            "required": True,
            "role": "题面极值目标及完整原条件，不是某一条等式条件",
        },
        "substitution": {
            "type": "Substitution",
            "required": False,
            "allows_anonymous_result": True,
            "role": "同一原目标的准确换元结果；提供时对换元后的目标和条件消元",
        },
    },
    input_views=declare_input_views(
        immutable_value=("target",), exact_result=("substitution",)
    ),
    outputs={"elimination": "ConstraintElimination"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="推导优先用 ∵ 表示依据、∴ 表示结论；同一角色的多个完整关系用逗号分隔，例如 ∵ a>b>0；∴ a>0，b>0。优先不用中文“因为”“所以”“且”，兼容解析不等于推荐输出。可选 substitution 必须引用同一原目标的 M07 准确结果；提供时消去一个新变量，expression 写仅含剩余新变量的完整目标；省略时由原条件消去一个原变量。eliminate 写待消去的变量名；steps[].math 提交条件变形、必要正性/非零关系和唯一的还原公式，如 y=(c-x)/2；expression 写代入后不含该变量的完整目标标量式。所有关系逐条验证，∵/∴ 不赋予前提权限。先证明原目标和还原公式中所有分母的非零性，再使用除法；非负量要升级为正数，先明确提交非零关系，或把已知等式改写成含该量的乘积等于非零常数；不要省略这一理由。steps[].math 只填写数学关系，优先用 ∵/∴，不混入“假设”“矛盾”等未支持叙述或集合成员声明；正性可先把分母差式等价写成已知正量，再提交其 >0。已知条件不用重复写，避免冗长重复的展开/通分；保留必要中间式。原变量不删除，不注册新变量，不搜索方程解，不应用不等式。后续 M11 用 elimination 引用此结果，M13 仍需给出所有原变量的取值。",
    teaching_unit=UNIT,
    no_new_visual_reason="消元是标量关系变形，不新增几何对象。",
)
