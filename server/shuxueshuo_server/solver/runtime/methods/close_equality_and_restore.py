"""Close a certified upper bound with an explicitly submitted finite witness."""

from copy import deepcopy

from jsonschema import ValidationError

from shuxueshuo_server.solver.contracts import MethodOutputActivationSpec
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

PARAMETERS_SCHEMA.pop("required")
PARAMETERS_SCHEMA["oneOf"] = [{"required": ["steps"]}, {"required": ["branches"]}]
PARAMETERS_SCHEMA["properties"]["branches"] = {
    "type": "array",
    "minItems": 1,
    "maxItems": 8,
    "items": {
        "type": "object",
        "required": ["steps"],
        "additionalProperties": False,
        "properties": {"steps": deepcopy(PARAMETERS_SCHEMA["properties"]["steps"])},
    },
}
PARAMETERS_SCHEMA["properties"]["equality_derivation"] = {
    "type": "array",
    "minItems": 1,
    "maxItems": 8,
    "description": "可选的联立求解过程。每行 math 是待证明等式，using 明确选择原条件、累计取等条件或此前已证明等式。单分支须推出全部赋值；多分支先给公共推导，再由每个分支的 when 与 equality_derivation 推出该分支全部赋值。不允许用见证赋值充当前提。",
    "items": {
        "type": "object",
        "required": ["math", "using"],
        "additionalProperties": False,
        "properties": {
            "math": {"type": "string", "minLength": 1, "maxLength": 1024},
            "using": {
                "type": "array",
                "maxItems": 4,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 1024},
            },
        },
    },
}
branch_schema = PARAMETERS_SCHEMA["properties"]["branches"]["items"]
branch_schema["properties"].update(
    when={
        "type": "string",
        "minLength": 1,
        "maxLength": 1024,
        "description": "该分支的显式 >= 或 <= 符号条件，仅在本分支中使用，且提交取值必须满足。",
    },
    equality_derivation=deepcopy(
        PARAMETERS_SCHEMA["properties"]["equality_derivation"]
    ),
)
branch_schema["dependentRequired"] = {
    "when": ["equality_derivation"],
    "equality_derivation": ["when"],
}


class CloseEqualityAndRestoreMethod:
    method_id = "close_equality_and_restore"

    def run(self, inputs, kernel):
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            value, evidence = close_bound(
                inputs["target"],
                inputs["bound"],
                parameters.get("steps"),
                branches=parameters.get("branches"),
                equality_derivation=parameters.get("equality_derivation"),
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
        key = (
            "maximum" if inputs["target"]["goal_kind"] == "find_maximum" else "minimum"
        )
        value_type = "MaximumExpression" if key == "maximum" else "MinimumExpression"
        return StatelessMethodResult(
            self.method_id,
            {key: TypedValue(value_type, value, source=self.method_id)},
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


from ...explanation.basic_inequality_teaching import EQUALITY_UNITS

SPEC = MethodSpecSource(
    method_cls=CloseEqualityAndRestoreMethod,
    title="取等并验证原条件",
    solves=("derive_maximum_value", "derive_minimum_value"),
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
    outputs={"maximum": "MaximumExpression", "minimum": "MinimumExpression"},
    output_activation={
        key: MethodOutputActivationSpec(
            kind="runtime_condition",
            runtime_condition=f"target.goal_kind == find_{key}",
        )
        for key in ("maximum", "minimum")
    },
    parameters_schema=PARAMETERS_SCHEMA,
    summary="math 只能写数学关系和 ∵/∴，不写“取等条件”“取”“此时”等文字或 ⇒。变量间乘法必须使用 *；a*b 与独立符号 ab 不同，所有条件和验算也必须显式 *。消费同一题面目标的最终常数界；最大值返回 maximum，最小值返回 minimum。验证全部前序取等条件。单见证用 steps；多个见证用互斥的 branches，每个分支提供 steps，全部通过，不宣称穷尽。steps 应简洁：关系链拆分后，加上累计取等条件和目标值验算，总计最多 16 个关系。原条件和目标值由内核自动代回，无需重复展开每个常量计算。steps 用 1–12 行写出取等条件、具体取值、原条件代回与目标值验算；允许 ∵/∴ 和关系链。例如 ∵x=y,x+y=6；∴x=y=3；∴x+y=6,x*y=9（分行写）。每个原变量必须有明确常量赋值，不能只写待求方程。内核同步代入验证全部提交关系、原条件、定义域、AM-GM 取等条件和目标值；只在提交的取等见证下验证，不把取等假设提升为全局事实，不搜索或枚举全部解。可选 equality_derivation 提交联立求解过程，每行 math/using 仅使用原条件、取等条件及此前已证明等式；全部赋值须由这些条件推出，验证后才允许教学投影描述为联立求得。多分支先提交公共 equality_derivation，再为每个 branches 项提供 when 和 equality_derivation；when 仅作为该分支的局部符号条件，仍须验证该分支取值满足它。各分支须分别推出全部赋值，不宣称分支穷尽。",
    teaching_units=EQUALITY_UNITS,
    no_new_visual_reason="几何场景无新增对象；自定义教学图由学生单元 visuals 声明。",
)
