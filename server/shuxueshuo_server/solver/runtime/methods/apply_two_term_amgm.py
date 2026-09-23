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
            "description": "完整数学推导，可写原条件、AM-GM、代入、缩放和上界。支持 ∵/∴、逗号/分号分隔关系和关系链；每个关系均验证。变量乘法用 *。最后归结为目标表达式<=常数。",
            "items": {
                "type": "object",
                "required": ["math"],
                "additionalProperties": False,
                "properties": {
                    "math": {"type": "string", "minLength": 1, "maxLength": 1024}
                },
            },
        }
    },
}


class ApplyTwoTermAmgmMethod:
    method_id = "apply_two_term_amgm"

    def run(self, inputs, kernel):
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            bound = verify_bound(inputs["target"], parameters["steps"])
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


SPEC = MethodSpecSource(
    method_cls=ApplyTwoTermAmgmMethod,
    title="应用二元基本不等式",
    solves=("derive_product_upper_bound",),
    inputs={
        "target": {
            "type": "Condition",
            "required": True,
            "role": "题面极值目标及完整原条件",
        }
    },
    input_views=declare_input_views(immutable_value=("target",)),
    outputs={"bound": "AmgmBound"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="验证两个正项定和求积的完整上界推导。steps 可有 1–12 行，包含 U+V>=2*sqrt(U*V)，显式代入定和、缩放等中间步骤，最后目标表达式<=常数。允许 ∵/∴ 连续推理和 A<=B=C 关系链，所有陈述均由内核验证，∵ 不创造前提。例如 ∵x>0,y>0；∴x+y>=2*sqrt(x*y)；∵x+y=6；∴6>=2*sqrt(x*y)；∴sqrt(x*y)<=3；∴x*y<=9（分行写）。只产生上界，取等交给 close_equality_and_restore。",
    do_not_use_when=("项不为正、非二元定和求积或需要先换元整理。",),
    generic_teaching_reason="由已验证 AM-GM 证据组织讲解。",
    no_new_visual_reason="仅生成代数不等式证据。",
)
