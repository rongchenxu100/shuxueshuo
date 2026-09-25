"""Verify a submitted two-term AM-GM and fixed-sum product bound."""

from jsonschema import ValidationError

from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
    public_bound,
    verify_bound,
)
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
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
            "minItems": 1,
            "maxItems": 12,
            "description": "完整数学推导，可写原条件、AM-GM、代入、缩放和上界。支持 ∵/∴、逗号/分号分隔关系和关系链；每个关系均验证。变量乘法用 *。最后归结为目标上界或当前式的下界；一次调用一个 AM-GM 应用。",
            "items": {
                "type": "object",
                "required": ["math"],
                "additionalProperties": False,
                "properties": {
                    "math": {"type": "string", "minLength": 1, "maxLength": 1024}
                },
            },
        },
    },
}


class ApplyTwoTermAmgmMethod:
    method_id = "apply_two_term_amgm"

    def run(self, inputs, kernel):
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            if inputs.get("expression") is not None:
                authority = inputs.get("__expression_authority__") or {}
                version = authority.get("state_version_id", {})
                owner = (
                    version.get("slot_id", {})
                    .get("logical_key", {})
                    .get("object_id", {})
                )
                if (
                    authority.get("kind") != "state_version"
                    or version.get("ordinal", 0) < 1
                    or owner.get("value") != inputs["target"].get("expression_owner")
                    or owner.get("origin_scope_id") != inputs["target"]["scope_id"]
                    or inputs.get("__expression_source__") != "organize_expressions"
                ):
                    raise ProofFailure(
                        "input_source_mismatch",
                        "expression must be a committed M01 version of this target",
                    )
            bound = verify_bound(
                inputs["target"],
                parameters["steps"],
                expression=inputs.get("expression"),
                previous_bound=inputs.get("previous_bound"),
            )
        except (
            ProofFailure,
            MathParseError,
            ValidationError,
            KeyError,
            TypeError,
            ValueError,
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
                "bound": TypedValue(
                    "AmgmBound", public_bound(bound), source=self.method_id
                )
            },
            checks=[
                _check(
                    "amgm_proof_verified", True, "正性、基本不等式与目标上界均已验证"
                )
            ],
            trace_fragments=[
                {
                    "kind": "verified_amgm_bound",
                    "method_id": self.method_id,
                    "source_target": inputs["target"],
                    "evidence": bound,
                    "conclusion": parameters["steps"][-1]["math"],
                }
            ],
        )


from ...explanation.basic_inequality_teaching import AMGM_UNITS

SPEC = MethodSpecSource(
    method_cls=ApplyTwoTermAmgmMethod,
    title="应用二元基本不等式",
    solves=("derive_product_upper_bound", "derive_expression_lower_bound"),
    inputs={
        "target": {
            "type": "Condition",
            "required": True,
            "role": "题面极值目标及完整原条件",
        },
        "expression": {
            "type": "Expression",
            "required": False,
            "state_kind": "expression",
        },
        "previous_bound": {
            "type": "AmgmBound",
            "required": False,
            "allows_anonymous_result": True,
        },
    },
    input_views=declare_input_views(
        immutable_value=("target",),
        latest_state=("expression",),
        exact_result=("previous_bound",),
    ),
    outputs={"bound": "AmgmBound"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="math 只能写数学关系和 ∵/∴，不写“取等条件”“取”“此时”等文字或 ⇒。变量间乘法必须使用 *；a*b 与独立符号 ab 不同，所有条件和验算也必须显式 *。对两个正项应用一次 AM-GM：定和求积上界，或当前完整表达式的局部下界（保留未变项）。需要配齐次、通分、展开或等式代入整理时先调用 M01。expression 用原目标对象的 SourceRef 读取 M01 提交后的准确版本，不能使用 StepResultRef。expression 可引用 M01 整理结果，previous_bound 可引用前次 M11，两者互斥；省略时从原目标开始。steps 写完整关系，可省略独立模板行，例如 3+u+4/u>=7。允许 ∵/∴、正性前置和等价中间式。最小值最后一行须为当前式或原目标>=下界，允许中间界含变量；继续估计须再次调用本方法并绑定 previous_bound。代码验证正性、域和所有关系，不因 ∵ 获得前提。取等闭合交给 M13。",
    do_not_use_when=("参与项不能证明为正，或一行含多种不唯一的局部配对。",),
    teaching_units=AMGM_UNITS,
    no_new_visual_reason="几何场景无新增对象；自定义教学图由学生单元 visuals 声明。",
)
