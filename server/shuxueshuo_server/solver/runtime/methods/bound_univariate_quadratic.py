"""Parameter square completion: verify a lower bound without closing attainment."""

from jsonschema import ValidationError

from ...math_kernel.expression_parser import MathParseError
from ...math_kernel.inequality_bound_v2 import public
from ...math_kernel.proof_algebra import ProofFailure
from ...math_kernel.quadratic_bound import verify_quadratic
from ..method_parameters import validate_parameters
from ._common import StatelessMethodResult, TypedValue, method_input_invalid
from ._spec import MethodSpecSource, declare_input_views

PARAMETERS_SCHEMA = {
    "type": "object",
    "required": ["variable", "steps"],
    "additionalProperties": False,
    "properties": {
        "variable": {"type": "string", "minLength": 1},
        "steps": {
            "type": "array",
            "minItems": 2,
            "maxItems": 12,
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


class BoundUnivariateQuadraticMethod:
    method_id = "bound_univariate_quadratic"

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
                        "expression must be this target's committed M01 version",
                    )
            evidence = verify_quadratic(
                inputs["target"],
                **parameters,
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
                    "QuadraticBound", public(evidence), source=self.method_id
                )
            },
            trace_fragments=[
                {
                    "kind": "verified_quadratic_bound",
                    "method_id": self.method_id,
                    "source_target": inputs["target"],
                    "evidence": evidence,
                    "conclusion": parameters["steps"][-1]["math"],
                }
            ],
        )


from ...explanation.basic_inequality_teaching import QUADRATIC_UNITS

SPEC = MethodSpecSource(
    method_cls=BoundUnivariateQuadraticMethod,
    title="配方利用平方非负求下界",
    solves=("derive_expression_lower_bound",),
    inputs={
        "target": {"type": "Condition", "required": True},
        "expression": {
            "type": "Expression",
            "required": False,
            "state_kind": "expression",
        },
        "previous_bound": {
            "type": "AmgmBound | QuadraticBound",
            "required": False,
            "allows_anonymous_result": True,
        },
    },
    input_views=declare_input_views(
        immutable_value=("target",),
        latest_state=("expression",),
        exact_result=("previous_bound",),
    ),
    outputs={"bound": "QuadraticBound"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="target 绑定 extremum_target 极值目标事实；expression 绑定同目标 M01 已提交的表达式对象，二者不是同一个引用。例如目录中的 extremum_target_target_expression 用于 target，target_expression 用于 expression；名称以实际目录为准。推导优先用 ∵ 表示依据、∴ 表示结论；同一角色的多个完整关系用逗号分隔，例如 ∵ a>b>0；∴ a>0，b>0。优先不用中文“因为”“所以”“且”，兼容解析不等于推荐输出。对当前完整表达式关于 variable 配方，其他已声明变量作为参数。steps 写完整关系，优先用 ∵/∴，逐条验证，不能将依据当作新假设。先提交配方恒等式 E=A*(z-h)^2+R，再提交下界关系 A*(z-h)^2+R>=R；不得把等式两侧拆成裸表达式行。A 必须可证明严格正，A、h、R 不含 z。expression 只能是同目标 M01 的 SourceRef，与 previous_bound 互斥；previous_bound 用 M11/M12 的 StepResultRef。省略时使用原目标。乘法显式写 *。不关闭最值，取等关系 z=h 自动保留，最终用 M13 联立验证。",
    teaching_units=QUADRATIC_UNITS,
    no_new_visual_reason="平方非负教学以共享表达式对照组件呈现。",
)
