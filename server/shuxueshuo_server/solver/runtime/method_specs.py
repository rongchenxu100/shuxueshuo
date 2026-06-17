"""MethodSpec 加载与检索。

MethodSpec 是无状态 method 的“能力说明书”。V1.5 之后，代码里的 method ``SPEC``
是唯一事实源；``internal/method-specs`` 下的 JSON 是由代码生成的派生产物，主要
用于 review、离线索引或跨语言消费。

这层只处理规格资产，不执行 method，也不读取具体题目 fixture。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
    MethodInputSpec,
    MethodSpec,
    MethodVisualSpec,
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
    return MethodSpec(
        method_id=str(raw["method_id"]),
        title=str(raw["title"]),
        solves=tuple(str(item) for item in raw["solves"]),
        inputs=inputs,
        outputs=outputs,
        summary=str(raw.get("summary", "")),
        preconditions=tuple(str(item) for item in raw.get("preconditions", [])),
        postconditions=tuple(str(item) for item in raw.get("postconditions", [])),
        trace_template=tuple(str(item) for item in raw.get("trace_template", [])),
        repair_hints=_parse_repair_hints(raw.get("repair_hints", [])),
        explanation=_parse_explanation(raw.get("explanation")),
        visual=_parse_visual(raw.get("visual")),
    )


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
        elif isinstance(raw, dict):
            input_type = str(raw.get("type", ""))
            role = str(raw.get("role", ""))
            required = bool(raw.get("required", True))
        else:
            raise ValueError(f"invalid input spec for {name}")
        if input_type not in _KNOWN_TYPES:
            raise ValueError(f"unknown input type for {name}: {input_type}")
        inputs[str(name)] = MethodInputSpec(
            name=str(name),
            type=input_type,
            role=role,
            required=required,
        )
    return inputs


def _parse_outputs(raw_outputs: object) -> dict[str, str]:
    """解析 MethodSpec.outputs，并校验输出类型属于 runtime 已知类型集合。"""
    if not isinstance(raw_outputs, dict) or not raw_outputs:
        raise ValueError("MethodSpec.outputs must be a non-empty object")
    outputs: dict[str, str] = {}
    for name, output_type in raw_outputs.items():
        output_type = str(output_type)
        if output_type not in _KNOWN_TYPES:
            raise ValueError(f"unknown output type for {name}: {output_type}")
        outputs[str(name)] = output_type
    return outputs


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
    if not isinstance(scene_templates, list | tuple):
        raise ValueError("MethodSpec.visual.scene_templates must be a list")
    if not isinstance(annotation_templates, list | tuple):
        raise ValueError("MethodSpec.visual.annotation_templates must be a list")
    return MethodVisualSpec(
        role_schema={str(key): str(value) for key, value in role_schema.items()},
        scene_templates=tuple(dict(item) for item in scene_templates if isinstance(item, dict)),
        annotation_templates=tuple(dict(item) for item in annotation_templates if isinstance(item, dict)),
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
