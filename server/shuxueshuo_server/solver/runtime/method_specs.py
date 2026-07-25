"""MethodSpec 加载与检索。

MethodSpec 是无状态 method 的“能力说明书”。V1.5 之后，代码里的 method ``SPEC``
是唯一事实源；``internal/method-specs`` 下的 JSON 是由代码生成的派生产物，主要
用于 review、离线索引或跨语言消费。

这层只处理规格资产，不执行 method，也不读取具体题目 fixture。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
    MethodInputSpec,
    MethodSpec,
    MethodVisualSpec,
    PlanTransformerScope,
    ScalarResultFormSpec,
)
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    runtime_type_union_is_well_formed,
    split_runtime_types,
)


class MethodSpecRegistry:
    """内存中的 MethodSpec 注册表。

    当前首版只有一个 spec，但注册表接口按多 method 设计：后续可以按 solves、
    required input、produces 或向量检索结果继续扩展。
    """

    def __init__(self, specs: dict[str, MethodSpec]) -> None:
        self.specs = specs

    @classmethod
    def load_dir(cls, path: str | Path | None = None) -> "MethodSpecRegistry":
        """从目录批量加载 JSON spec，并检查 method_id 是否重复。

        这个入口保留给“读取已生成 JSON”的场景；solver runtime 默认应使用
        ``load_from_code``，避免 JSON 与实现漂移。
        """
        spec_dir = _resolve_spec_dir(path)
        specs: dict[str, MethodSpec] = {}
        for spec_path in sorted(spec_dir.glob("*.json")):
            spec = load_method_spec(spec_path)
            if spec.method_id in specs:
                raise ValueError(f"duplicate method_id: {spec.method_id}")
            specs[spec.method_id] = spec
        return cls(specs)

    @classmethod
    def load_from_code(cls) -> "MethodSpecRegistry":
        """从 method 代码中的 ``SPEC`` 构建注册表。"""
        from shuxueshuo_server.solver.runtime.methods import method_spec_payloads

        specs: dict[str, MethodSpec] = {}
        for raw in method_spec_payloads():
            spec = parse_method_spec(raw)
            if spec.method_id in specs:
                raise ValueError(f"duplicate method_id: {spec.method_id}")
            specs[spec.method_id] = spec
        return cls(specs)

    def require(self, method_id: str) -> MethodSpec:
        """按 method_id 获取 spec；不存在时抛出带上下文的 KeyError。"""
        try:
            return self.specs[method_id]
        except KeyError as exc:
            raise KeyError(f"method spec not found: {method_id}") from exc

    def for_goal(self, goal_type: str) -> list[MethodSpec]:
        """返回声明可以解决某类 step goal 的 method specs。"""
        return [
            spec for spec in self.specs.values()
            if goal_type in spec.solves
        ]


def load_method_spec(path: str | Path) -> MethodSpec:
    """加载单个 JSON 文件并解析成 MethodSpec。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_method_spec(raw)


def parse_method_spec(raw: dict[str, Any]) -> MethodSpec:
    """把原始 JSON 对象解析成强类型 MethodSpec。

    这里做的是运行时最小校验：必填字段、solves 非空、输入输出类型已知。更复杂
    的 schema 校验可以后续接 JSON Schema，但当前测试切片先保持轻量。
    """
    required = {"method_id", "title", "solves", "inputs", "outputs"}
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"MethodSpec missing required fields: {', '.join(missing)}")
    if not isinstance(raw["solves"], list) or not raw["solves"]:
        raise ValueError("MethodSpec.solves must be a non-empty list")
    inputs = _parse_inputs(raw["inputs"])
    outputs = _parse_outputs(raw["outputs"])
    scalar_result_forms = _parse_scalar_result_forms(
        raw.get("scalar_result_forms", {}),
        output_names=set(outputs),
    )
    is_pure = raw.get("is_pure", False)
    if not isinstance(is_pure, bool):
        raise ValueError("MethodSpec.is_pure must be a boolean")
    plan_transformer_scope = _parse_plan_transformer_scope(
        raw.get("plan_transformer_scope", "single_invocation")
    )
    return MethodSpec(
        method_id=str(raw["method_id"]),
        title=str(raw["title"]),
        solves=tuple(str(item) for item in raw["solves"]),
        inputs=inputs,
        outputs=outputs,
        scalar_result_forms=scalar_result_forms,
        summary=str(raw.get("summary", "")),
        do_not_use_when=_parse_do_not_use_when(raw.get("do_not_use_when", ())),
        preconditions=tuple(str(item) for item in raw.get("preconditions", [])),
        postconditions=tuple(str(item) for item in raw.get("postconditions", [])),
        trace_template=tuple(str(item) for item in raw.get("trace_template", [])),
        repair_hints=_parse_repair_hints(raw.get("repair_hints", [])),
        explanation=_parse_explanation(raw.get("explanation")),
        visual=_parse_visual(raw.get("visual")),
        constraint_analyzer=(
            str(raw["constraint_analyzer"])
            if raw.get("constraint_analyzer") is not None
            else None
        ),
        plan_transformer=(
            str(raw["plan_transformer"])
            if raw.get("plan_transformer") is not None
            else None
        ),
        plan_transformer_scope=plan_transformer_scope,
        reconciliation_validators=_parse_identifier_list(
            raw.get("reconciliation_validators", ()),
            field_name="MethodSpec.reconciliation_validators",
        ),
        distinct_arg_groups=_parse_distinct_arg_groups(
            raw.get("distinct_arg_groups", ()),
            input_names=frozenset(inputs),
        ),
        is_pure=is_pure,
    )


def _parse_plan_transformer_scope(raw: object) -> PlanTransformerScope:
    if raw not in {"single_invocation", "all_invocations"}:
        raise ValueError(
            "MethodSpec.plan_transformer_scope must be "
            "'single_invocation' or 'all_invocations'"
        )
    return cast(PlanTransformerScope, raw)


def _parse_do_not_use_when(raw: object) -> tuple[str, ...]:
    if raw in (None, ()):
        return ()
    if not isinstance(raw, list | tuple):
        raise ValueError("MethodSpec.do_not_use_when must be a list")
    result: list[str] = []
    for item in raw:
        value = str(item).strip()
        if not value:
            raise ValueError("MethodSpec.do_not_use_when items must be non-empty")
        if value not in result:
            result.append(value)
    return tuple(result)


def _parse_distinct_arg_groups(
    raw: object,
    *,
    input_names: frozenset[str],
) -> tuple[tuple[str, ...], ...]:
    """Parse declarative groups whose resolved object identities must differ."""
    if raw in (None, ()):
        return ()
    if not isinstance(raw, list | tuple):
        raise ValueError("MethodSpec.distinct_arg_groups must be a list")
    groups: list[tuple[str, ...]] = []
    for item in raw:
        if not isinstance(item, list | tuple):
            raise ValueError(
                "MethodSpec.distinct_arg_groups items must be lists"
            )
        group = tuple(str(name).strip() for name in item)
        if len(group) < 2 or any(not name for name in group):
            raise ValueError(
                "MethodSpec.distinct_arg_groups items require at least two names"
            )
        if len(set(group)) != len(group):
            raise ValueError(
                "MethodSpec.distinct_arg_groups cannot repeat an argument"
            )
        unknown = tuple(name for name in group if name not in input_names)
        if unknown:
            raise ValueError(
                "MethodSpec.distinct_arg_groups references unknown inputs: "
                + ", ".join(unknown)
            )
        if group not in groups:
            groups.append(group)
    return tuple(groups)


def _parse_identifier_list(
    raw: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if raw in (None, ()):
        return ()
    if not isinstance(raw, list | tuple):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for item in raw:
        value = str(item).strip()
        if not value:
            raise ValueError(f"{field_name} items must be non-empty")
        if value not in result:
            result.append(value)
    return tuple(result)


def _parse_inputs(raw_inputs: object) -> dict[str, MethodInputSpec]:
    """解析 MethodSpec.inputs。

    输入支持两种写法：简单字符串类型，或带 role/required 的对象。首版 JSON 使用
    对象写法，让 planner 能根据 role 理解 anchor/reference/target 的语义。
    """
    if not isinstance(raw_inputs, dict) or not raw_inputs:
        raise ValueError("MethodSpec.inputs must be a non-empty object")
    inputs: dict[str, MethodInputSpec] = {}
    for name, raw in raw_inputs.items():
        if isinstance(raw, str):
            input_type = raw
            role = ""
            required = True
            functional_exposed = True
        elif isinstance(raw, dict):
            input_type = str(raw.get("type", ""))
            role = str(raw.get("role", ""))
            required = bool(raw.get("required", True))
            functional_exposed = bool(raw.get("functional_exposed", True))
        else:
            raise ValueError(f"invalid input spec for {name}")
        if not _input_type_is_known(input_type):
            raise ValueError(f"unknown input type for {name}: {input_type}")
        inputs[str(name)] = MethodInputSpec(
            name=str(name),
            type=input_type,
            role=role,
            required=required,
            functional_exposed=functional_exposed,
        )
    return inputs


def _parse_outputs(raw_outputs: object) -> dict[str, str]:
    """解析 MethodSpec.outputs，并校验输出类型属于 runtime 已知类型集合。"""
    if not isinstance(raw_outputs, dict) or not raw_outputs:
        raise ValueError("MethodSpec.outputs must be a non-empty object")
    outputs: dict[str, str] = {}
    for name, output_type in raw_outputs.items():
        output_type = str(output_type)
        if not _output_type_is_known(output_type):
            raise ValueError(f"unknown output type for {name}: {output_type}")
        outputs[str(name)] = output_type
    return outputs


def _parse_scalar_result_forms(
    raw_specs: object,
    *,
    output_names: set[str],
) -> dict[str, ScalarResultFormSpec]:
    if raw_specs in (None, {}):
        return {}
    if not isinstance(raw_specs, dict):
        raise ValueError("MethodSpec.scalar_result_forms must be an object")
    unknown = sorted(set(str(name) for name in raw_specs) - output_names)
    if unknown:
        raise ValueError(
            "MethodSpec.scalar_result_forms references unknown outputs: "
            + ", ".join(unknown)
        )
    result: dict[str, ScalarResultFormSpec] = {}
    allowed_forms = {
        "open_expression",
        "closed_value",
        "open_state",
        "closed_state",
    }
    for name, raw in raw_specs.items():
        if not isinstance(raw, dict):
            raise ValueError(f"invalid scalar result form spec for {name}")
        possible = raw.get("possible_forms")
        if not isinstance(possible, list) or not possible:
            raise ValueError(
                f"scalar result form possible_forms must be non-empty for {name}"
            )
        forms = tuple(dict.fromkeys(str(item) for item in possible))
        if set(forms) - allowed_forms:
            raise ValueError(f"unknown scalar result form for {name}: {forms}")
        description = str(raw.get("description", "")).strip()
        if not description:
            raise ValueError(
                f"scalar result form description must be non-empty for {name}"
            )
        closure_policy = str(raw.get("closure_policy", "no_free_symbols"))
        if closure_policy != "no_free_symbols":
            raise ValueError(
                f"unknown scalar result closure policy for {name}: {closure_policy}"
            )
        ignored_symbol_input_args = raw.get("ignored_symbol_input_args", ())
        if not isinstance(ignored_symbol_input_args, (list, tuple)):
            raise ValueError(
                "scalar result form ignored_symbol_input_args must be a list "
                f"for {name}"
            )
        max_independent_free_parameters = raw.get(
            "max_independent_free_parameters"
        )
        if (
            max_independent_free_parameters is not None
            and (
                not isinstance(max_independent_free_parameters, int)
                or isinstance(max_independent_free_parameters, bool)
                or max_independent_free_parameters < 0
            )
        ):
            raise ValueError(
                "scalar result form max_independent_free_parameters must be "
                f"a non-negative integer for {name}"
            )
        result[str(name)] = ScalarResultFormSpec(
            possible_forms=forms,  # type: ignore[arg-type]
            description=description,
            closure_policy="no_free_symbols",
            ignored_symbol_input_args=tuple(
                str(item)
                for item in ignored_symbol_input_args
                if str(item)
            ),
            max_independent_free_parameters=(
                max_independent_free_parameters
            ),
        )
    return result


def _parse_repair_hints(raw_hints: object) -> tuple[dict[str, Any], ...]:
    """解析 method spec 中面向 LLM repair 的提示。"""
    if raw_hints in (None, ()):
        return ()
    if not isinstance(raw_hints, list):
        raise ValueError("MethodSpec.repair_hints must be a list")
    hints: list[dict[str, Any]] = []
    for raw in raw_hints:
        if not isinstance(raw, dict):
            raise ValueError("MethodSpec.repair_hints items must be objects")
        hints.append(dict(raw))
    return tuple(hints)


def _parse_explanation(raw: object) -> MethodExplanationSpec | None:
    if raw in (None, ()):
        return None
    if not isinstance(raw, dict):
        raise ValueError("MethodSpec.explanation must be an object")
    role_schema = raw.get("role_schema", {})
    if not isinstance(role_schema, dict):
        raise ValueError("MethodSpec.explanation.role_schema must be an object")
    title_by_goal = raw.get("student_title_templates_by_goal", {})
    if not isinstance(title_by_goal, dict):
        raise ValueError("MethodSpec.explanation.student_title_templates_by_goal must be an object")
    return MethodExplanationSpec(
        role_schema={str(key): str(value) for key, value in role_schema.items()},
        student_goal_template=str(raw.get("student_goal_template", "")),
        student_title_template=str(raw.get("student_title_template", "")),
        student_nav_title_template=str(raw.get("student_nav_title_template", "")),
        student_title_templates_by_goal={
            str(key): str(value)
            for key, value in title_by_goal.items()
        },
        derive_templates=tuple(str(item) for item in raw.get("derive_templates", ())),
        box_templates=tuple(str(item) for item in raw.get("box_templates", ())),
        explanation_level=str(raw.get("explanation_level", "template")),
        role_binding_strategy=str(raw.get("role_binding_strategy", "role_name_registry")),
        role_binder_id=str(raw.get("role_binder_id", "generic_trace")),
    )


def _parse_visual(raw: object) -> MethodVisualSpec | None:
    if raw in (None, ()):
        return None
    if not isinstance(raw, dict):
        raise ValueError("MethodSpec.visual must be an object")
    role_schema = raw.get("role_schema", {})
    if not isinstance(role_schema, dict):
        raise ValueError("MethodSpec.visual.role_schema must be an object")
    scene_templates = raw.get("scene_templates", ())
    annotation_templates = raw.get("annotation_templates", ())
    timeline_templates = raw.get("timeline_templates", ())
    if not isinstance(scene_templates, list | tuple):
        raise ValueError("MethodSpec.visual.scene_templates must be a list")
    if not isinstance(annotation_templates, list | tuple):
        raise ValueError("MethodSpec.visual.annotation_templates must be a list")
    if not isinstance(timeline_templates, list | tuple):
        raise ValueError("MethodSpec.visual.timeline_templates must be a list")
    return MethodVisualSpec(
        role_schema={str(key): str(value) for key, value in role_schema.items()},
        scene_templates=tuple(dict(item) for item in scene_templates if isinstance(item, dict)),
        annotation_templates=tuple(dict(item) for item in annotation_templates if isinstance(item, dict)),
        timeline_templates=tuple(dict(item) for item in timeline_templates if isinstance(item, dict)),
        role_binder_id=str(raw.get("role_binder_id", "generic_visual")),
    )


def _resolve_spec_dir(path: str | Path | None) -> Path:
    """解析 spec 目录。

    不传 path 时，默认定位到仓库根目录下的 ``internal/method-specs``，这样测试在
    ``server`` 目录运行时也能找到同一份 method 资产。
    """
    if path is not None:
        return Path(path)
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "internal" / "method-specs"


_KNOWN_TYPES = {
    "AngleEquality",
    "Condition",
    "Constraint",
    "Coefficients",
    "Equation",
    "Expression",
    "Line",
    "MinimumExpression",
    "OrientationHint",
    "Parabola",
    "ParameterValue",
    "PathTransformation",
    "Point",
    "PointList",
    "PointRef",
    "Question",
    "Segment",
    "Symbol",
    "SymbolList",
    "StraighteningCandidate",
    "StraighteningCandidateList",
}


def _input_type_is_known(input_type: str) -> bool:
    """输入类型允许用 ``A|B`` 表达一个很窄的 runtime union。"""
    return _type_expression_is_known(input_type)


def _output_type_is_known(output_type: str) -> bool:
    """输出类型使用同一套 union-aware 校验，避免 JSON spec 漏掉坏成员。"""
    return _type_expression_is_known(output_type)


def _type_expression_is_known(type_expr: str) -> bool:
    if type_expr in _KNOWN_TYPES:
        return True
    if "|" not in type_expr:
        return False
    parts = split_runtime_types(type_expr)
    return (
        bool(parts)
        and runtime_type_union_is_well_formed(type_expr)
        and all(part in _KNOWN_TYPES for part in parts)
    )
