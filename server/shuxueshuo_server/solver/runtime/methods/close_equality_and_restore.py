"""Close a certified upper bound with an explicitly submitted finite witness."""

from copy import deepcopy

from jsonschema import ValidationError

from shuxueshuo_server.solver.math_kernel.expression_parser import MathParseError
from shuxueshuo_server.solver.math_kernel.inequality_evidence import close_bound
from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
from shuxueshuo_server.solver.runtime.method_parameters import validate_parameters

from ._common import *
from ._spec import MethodSpecSource, declare_input_views
from .apply_two_term_amgm import PARAMETERS_SCHEMA as BOUND_SCHEMA

PARAMETERS_SCHEMA = deepcopy(BOUND_SCHEMA)
PARAMETERS_SCHEMA["properties"]["steps"].update(
    minItems=1,
    maxItems=12,
    description="完整取等推导和验算，可包含原条件、取等条件、具体赋值及目标值。支持 ∵/∴、逗号/分号、x=y=常数。必须明确给出每个原变量的具体取值；所有关系在该见证下验证，不声明对所有可行取值成立。",
)


class CloseEqualityAndRestoreMethod:
    method_id = "close_equality_and_restore"

    def run(self, inputs, kernel):
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            value, evidence = close_bound(
                inputs["target"], inputs["bound"], parameters["steps"]
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
            {"maximum": TypedValue("MaximumExpression", value, source=self.method_id)},
            checks=[
                _check("extremum_attained", True, "见证满足全部原条件并达到已证明上界")
            ],
            trace_fragments=[
                {
                    "kind": "verified_extremum",
                    "method_id": self.method_id,
                    "source_target": inputs["target"],
                    "evidence": evidence,
                    "conclusion": str(value),
                }
            ],
        )


SPEC = MethodSpecSource(
    method_cls=CloseEqualityAndRestoreMethod,
    title="取等并验证原条件",
    solves=("derive_maximum_value",),
    inputs={
        "target": {"type": "Condition", "required": True},
        "bound": {
            "type": "AmgmBound",
            "required": True,
            "allows_anonymous_result": True,
        },
    },
    input_views=declare_input_views(
        immutable_value=("target",), exact_result=("bound",)
    ),
    outputs={"maximum": "MaximumExpression"},
    parameters_schema=PARAMETERS_SCHEMA,
    summary="消费已验证上界和同一个题面目标。steps 用 1–12 行写出取等条件、具体取值、原条件代回与目标值验算；允许 ∵/∴ 和关系链。例如 ∵x=y,x+y=6；∴x=y=3；∴x+y=6,x*y=9（分行写）。每个原变量必须有明确常量赋值，不能只写待求方程。内核同步代入验证全部提交关系、原条件、定义域、AM-GM 取等条件和目标值；只在提交的取等见证下验证，不把取等假设提升为全局事实，不搜索或枚举全部解。",
    generic_teaching_reason="由上界证据及原条件代回证据组织取等讲解。",
    no_new_visual_reason="只验证有限见证，不产生几何对象。",
)
