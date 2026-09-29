"""Validate an authored rational rewrite chain and return one expression state."""

from __future__ import annotations

from jsonschema import ValidationError

from shuxueshuo_server.solver.contracts import MethodVisualSpec, TeachingUnitSpec
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
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["math"],
                "additionalProperties": False,
                "properties": {
                    "math": {"type": "string", "minLength": 1, "maxLength": 1024,
                             "description": "用数学因为所以符号写推导：可用 ∵ 标识依据、∴ 标识结论，写完整数学关系，如 ∴ 3*u+3*v=3*(u+v)；引用条件时写 ∵ u+v=4；∴ 3*(u+v)=12。纯恒等变形无需虚构 ∵ 条件。"},
                    "using": {
                        "description": "可选的结构化条件引用，等价于 math 中的 ∵。填写已绑定等式数学原文，如 a*b=1，不填写内部标识。",
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
args.expression 必须引用表达式对象，不是 extremum_target 极值目标事实；例如目录同时有 target_expression 和 extremum_target_target_expression 时，expression 选择 target_expression。引用名称以实际目录为准。
parameters.steps 使用自然的数学推导格式：可用 ∵ 标识依据、∴ 标识结论；支持完整目标等式或唯一匹配的局部等式；
纯恒等变形写“∴ 左式=右式”，如“∴ 3*u+3*v=3*(u+v)”，无需虚构 ∵ 条件。
条件代入写“∵ 条件；∴ 左式=右式”，如“∵ u+v=4；∴ 3*(u+v)=12”。
∵ 可引用当前作用域可见的题目原条件，args.conditions 是可选提示，也可提交根据这些条件可证明的局部恒等式；代码验证依据及整体等价，不需要提供证明证书。允许自然等式链及正性、非零性说明，代码拆分关系并逐条验证。完整关系的一侧可写“原式”，它固定引用本次 M01 输入的完整表达式，不是最近改写结果。
∵ 标识所用条件，∴ 标识待验证结论；标记不能代替数学验证。局部等式可单独成行，代码唯一匹配目标中的局部并补出整体等价转换；也可写“∵ 局部等式；∴ 完整目标等式”。无法唯一匹配时请补充整体结论。
推导优先使用 ∵/∴ 和完整数学关系；衔接语本身不是证明。使用显式乘号 *、除号 /、括号和整数幂 ^；不写未识别的叙述、操作标签或答案。
不能引入新变量，不能对目标应用不等式求界；正性、非零性等辅助关系须由绑定条件证明。"""


class OrganizeExpressionsMethod:
    """整理式子：验证 LLM 推导，保留原结构，返回同对象的一个最终状态。"""

    method_id = "organize_expressions"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = inputs["expression"]
        try:
            parameters = validate_parameters(
                PARAMETERS_SCHEMA, inputs.get("__parameters__", {})
            )
            symbols = inputs.get("__visible_symbols__") or {
                s.name: s for s in expression.free_symbols
            }
            trace = verify_chain(
                expression,
                list(inputs.get("__scope_conditions__", inputs.get("conditions", []))),
                parameters["steps"],
                symbols,
                input_source=inputs.get("__source_expression__"),
            )
        except ValidationError as exc:
            raise method_input_invalid(
                "推导参数不符合 schema",
                method_id=self.method_id,
                observed={"path": list(exc.absolute_path)},
                repair_action="repair_derivation",
            ) from exc
        except RewriteError as exc:
            scoped_domain = exc.code == "input_domain_unverified" and inputs.get("__proof_protocol__") == "scoped-facts/v2"
            raise method_input_invalid(
                "原目标作用域条件已自动可用，仍无法证明所列分母非零。" if scoped_domain else str(exc),
                method_id=self.method_id,
                observed={"code": "domain_unproved" if scoped_domain else exc.code, "row": exc.row,
                          **({"unverified_conditions": exc.unverified_conditions}
                             if hasattr(exc, "unverified_conditions") else {})},
                repair_action=("repair_domain_proof" if scoped_domain else "bind_domain_conditions" if exc.code == "input_domain_unverified"
                               else "repair_local_rewrite" if exc.code in {
                    "ambiguous_local_rewrite", "rewrite_scope_mismatch", "proof_missing"
                } else "repair_derivation"),
            ) from exc
        trace["condition_protocol"] = inputs.get("__proof_protocol__", "bound-conditions/v1")
        value = trace.pop("value")
        sources = inputs.get("__scope_condition_sources__", inputs.get("__condition_sources__", []))
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
    summary='args.expression 必须引用表达式对象，不是 extremum_target 极值目标事实；例如目录同时有 target_expression 和 extremum_target_target_expression 时，expression 选择 target_expression。引用名称以实际目录为准。推导优先用 ∵ 表示依据、∴ 表示结论；同一角色的多个完整关系用逗号分隔，例如 ∵ a>b>0；∴ a>0，b>0。优先不用中文“因为”“所以”“且”，兼容解析不等于推荐输出。math 使用自然的数学推导格式：可用 ∵ 标识依据、∴ 标识结论，写完整数学关系，支持完整目标等式或唯一匹配的局部等式。例如 steps=[{"math":"∴ 3*u+3*v=3*(u+v)"},{"math":"∵ u+v=4；∴ 3*(u+v)=12"}]。纯恒等变形无需虚构 ∵ 条件；∵ 可引用当前作用域可见的题目原条件或由这些条件可证明的局部恒等式，代码自行匹配并证明，不要求 LLM 给出证明证书；也可使用可选 using 数组提供相同的等式引用。∵ 标识条件，∴ 标识待验证结论，标记本身不授予证明权限。局部等式可单独成行，代码唯一匹配目标中的局部并补出整体等价转换；也可写“∵ 局部等式；∴ 完整目标等式”。无法唯一匹配时请补充整体结论。完整关系的一侧可写“原式”，它固定引用本次 M01 输入的完整表达式，不是最近改写结果；代码展开引用后仍验证定义域与等价。允许自然等式链和由绑定条件可证明的正性、非零性等辅助关系；不能对目标作不等式估计。代码逐条验证每个关系。不写内部标识或未识别的自由文本理由。变量间乘法必须显式 *，ab 是独立标识符，不能表示 a*b。scoped-facts/v2 下，代码从准确目标绑定自动获取可见原条件并保留来源；args.conditions 为可选检索提示，不缩小前提集，可省略、为空或只列部分。显式引用仍须合法且可见。历史 bound-conditions/v1 证据只按原绑定前提集回放，不扩充条件。定义域始终须证明，不默认变量为正。逐行验证定义域、左侧衔接及等价并回放证书，只提交右侧作为同一目标对象的新状态，不求极值。不执行条件消元或注册新变量。支持有界整数幂与 sqrt 根式，优先保留原变量的配齐次、通分和展开结构。',
    preconditions=("目标与变量准确绑定，显式条件引用合法且可见",),
    postconditions=("最终式与输入在原定义域上等价",),
    teaching_unit=TeachingUnitSpec(
        unit_key="organize_expressions/rewrite",
        title_template="整理目标式",
        nav_title_template="整理目标式",
        goal_template="整理目标表达式",
        derive_templates=(
            ("推导", "{derive_items}"),
            ("∴", "{result}"),
        ),
        box_templates=("{result}",),
        role_schema={
            "source": "原式",
            "result": "整理结果",
            "derive_items": "已验证推导",
        },
        role_binder_id="expression_rewrite",
        requires_independent_lesson_step=True,
        visuals=({"spec_id": "expression_rewrite.chain", "roles": {"evidence": "$source"}},),
    ),
    visual=MethodVisualSpec(
        role_schema={"rewrite": "已验证推导记录"},
        scene_templates=({"kind": "expression_rewrite"},),
        timeline_templates=({"kind": "expression_rewrite_beats"},),
        role_binder_id="expression_rewrite",
    ),
)
