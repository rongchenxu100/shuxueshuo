"""受控 LLM Planner 的 Phase C 核心组件。

本模块实现一条还没有接入默认 CLI 的新 planner 链路：

``PlannerInputs -> PlanningPayloadBuilder -> Jinja prompt -> LLM draft JSON
-> AbstractPlanValidator -> PlanCompiler -> PlannerOutput``。

它和 ``llm_step_planner.py`` 的 legacy slice 有意并存。legacy slice 仍把 LLM 的
抽象步骤编译回 deterministic template；本模块则开始让 LLM 选择 method 和输入槽位，
但选择空间被 ``SlotBinder`` 压缩成候选 id，避免 LLM 编造 ContextPath 或直接写答案。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.contracts import MethodSpec
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context_inventory import (
    ContextInventory,
    MethodCandidateEntry,
    PlanningSignalEntry,
    RelationGraphEntry,
    VisibleContextPath,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    MethodInvocation,
    PlannerOutput,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.planner import GenericPlanner, PlannerInputs


class AbstractPlanValidationError(ValueError):
    """LLM draft 在编译前校验失败时抛出的错误。"""


@dataclass(frozen=True)
class StepGoalDraft:
    """LLM draft 中的单步目标。

    ``StepGoalDraft`` 只说明这一步想推进什么，不保存答案值。真正执行时会被编译成
    runtime 的 ``StepGoal``。
    """

    type: str
    target_path: str
    value_type: str = ""
    description: str = ""


@dataclass(frozen=True)
class ContextDeclarationDraft:
    """LLM draft 中的上下文占位声明。

    draft 只允许写 ``definition_intent`` 字符串；编译时再转换成 runtime 需要的
    ``ContextDeclaration.definition`` 字典，避免 LLM 夹带坐标或答案。
    """

    path: str
    type: str
    name: str
    definition_intent: str
    scope_id: str
    source: str = "planner"


@dataclass(frozen=True)
class LLMStepDraft:
    """LLM draft 中的一个有序步骤。

    ``bindings`` 的 value 必须是 ``SlotBinder`` 提供的候选 id，例如 ``c_0``。
    ``depends_on`` 只用于编译前 DAG 校验，不进入 ``StepPlan``。
    """

    step_id: str
    scope_id: str
    step_goal: StepGoalDraft
    method_id: str
    bindings: dict[str, str] = field(default_factory=dict)
    promote_to: dict[str, str] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class PlannerDraft:
    """LLM 允许返回的完整 JSON draft。"""

    context_declarations: tuple[ContextDeclarationDraft, ...] = ()
    steps: tuple[LLMStepDraft, ...] = ()


@dataclass(frozen=True)
class SlotCandidate:
    """某个 method 输入槽位可选择的 ContextPath 候选。"""

    candidate_id: str
    path: str
    type: str
    scope_id: str
    readable_from: tuple[str, ...]
    description: str = ""


@dataclass(frozen=True)
class MethodSlotOptions:
    """一个 ``(method_id, input_name)`` 对应的候选集合。"""

    method_id: str
    input_name: str
    input_type: str
    required: bool
    candidates: tuple[SlotCandidate, ...] = ()


@dataclass(frozen=True)
class RenderedPlannerPrompt:
    """Jinja 渲染后的 system/user prompt。"""

    system: str
    user: str

    def as_messages(self) -> list[dict[str, str]]:
        """转换成 Chat Completions messages 形态。"""
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


@dataclass(frozen=True)
class PlanningPayloadBuildResult:
    """PlanningPayloadBuilder 的完整构建结果。

    payload 和 slot_options 必须来自同一次构建，避免 ControlledLLMPlanner 为了校验
    和编译重复枚举候选。``build()`` 仍保留旧的 dict 返回形态，方便现有测试和外部
    调用。
    """

    payload: dict[str, Any]
    slot_options: tuple[MethodSlotOptions, ...]


PLANNER_DRAFT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["context_declarations", "steps"],
    "properties": {
        "context_declarations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "path",
                    "type",
                    "name",
                    "definition_intent",
                    "scope_id",
                ],
                "properties": {
                    "path": {"type": "string"},
                    "type": {"const": "PointRef"},
                    "name": {"type": "string"},
                    "definition_intent": {"type": "string"},
                    "scope_id": {"type": "string"},
                    "source": {"const": "planner"},
                },
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "step_id",
                    "scope_id",
                    "step_goal",
                    "method_id",
                    "bindings",
                    "promote_to",
                    "depends_on",
                    "reason",
                ],
                "properties": {
                    "step_id": {"type": "string"},
                    "scope_id": {"type": "string"},
                    "step_goal": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "target_path"],
                        "properties": {
                            "type": {"type": "string"},
                            "target_path": {"type": "string"},
                            "value_type": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                    "method_id": {"type": "string"},
                    "bindings": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "promote_to": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


class SlotBinder:
    """把 MethodSpec 输入槽位收束成可枚举候选。

    LLM 不直接输出 ContextPath，而是从每个槽位的 ``c_0/c_1/...`` 候选中选择。
    候选 id 只在 ``(method_id, input_name)`` 内有意义，这能减少 token，也能避免
    LLM 看着完整路径自行拼接不存在的路径。
    """

    def build(
        self,
        *,
        method_specs: MethodSpecRegistry,
        context_inventory: ContextInventory,
    ) -> tuple[MethodSlotOptions, ...]:
        """为所有 method input 生成稳定排序的候选集合。"""
        options: list[MethodSlotOptions] = []
        visible_paths = tuple(
            sorted(
                context_inventory.visible_paths,
                key=lambda item: (item.scope_id, item.type, item.path),
            )
        )
        for method_id in sorted(method_specs.specs):
            spec = method_specs.specs[method_id]
            for input_name in sorted(spec.inputs):
                input_spec = spec.inputs[input_name]
                matching_paths = [
                    path for path in visible_paths
                    if _type_compatible(input_spec.type, path.type)
                ]
                candidates = tuple(
                    SlotCandidate(
                        candidate_id=f"c_{index}",
                        path=path.path,
                        type=path.type,
                        scope_id=path.scope_id,
                        readable_from=path.readable_from,
                        description=path.description,
                    )
                    for index, path in enumerate(matching_paths)
                )
                options.append(
                    MethodSlotOptions(
                        method_id=method_id,
                        input_name=input_name,
                        input_type=input_spec.type,
                        required=input_spec.required,
                        candidates=candidates,
                    )
                )
        return tuple(options)

    @staticmethod
    def index(
        slot_options: tuple[MethodSlotOptions, ...],
    ) -> dict[tuple[str, str, str], SlotCandidate]:
        """构建 ``(method_id, input_name, candidate_id)`` 到候选的索引。"""
        result: dict[tuple[str, str, str], SlotCandidate] = {}
        for option in slot_options:
            for candidate in option.candidates:
                result[(option.method_id, option.input_name, candidate.candidate_id)] = candidate
        return result

    @staticmethod
    def option_index(
        slot_options: tuple[MethodSlotOptions, ...],
    ) -> dict[tuple[str, str], MethodSlotOptions]:
        """构建 ``(method_id, input_name)`` 到槽位选项的索引。"""
        return {
            (option.method_id, option.input_name): option
            for option in slot_options
        }


class PlanningPayloadBuilder:
    """把 PlannerInputs 压缩成 LLM 可见的受控 payload。"""

    def __init__(
        self,
        *,
        slot_binder: SlotBinder | None = None,
        few_shot_loader: "FewShotExampleLoader | None" = None,
    ) -> None:
        self.slot_binder = slot_binder or SlotBinder()
        self.few_shot_loader = few_shot_loader or FewShotExampleLoader()

    def build(self, inputs: PlannerInputs) -> dict[str, Any]:
        """生成 prompt payload，并明确排除 expected answers。"""
        return self.build_with_slot_options(inputs).payload

    def build_with_slot_options(self, inputs: PlannerInputs) -> PlanningPayloadBuildResult:
        """生成 payload，并返回同一次构建得到的 slot_options。"""
        slot_options = self.slot_binder.build(
            method_specs=inputs.method_specs,
            context_inventory=inputs.context_inventory,
        )
        payload = {
            "problem_id": inputs.problem_id,
            "family_id": inputs.family_spec.family_id,
            "family_spec": _family_payload(inputs.family_spec),
            "question_goals": [_question_goal_payload(goal) for goal in inputs.question_goals],
            "planning_signals": [
                _planning_signal_payload(signal)
                for signal in inputs.context_inventory.planning_signals
            ],
            "relation_graph": [
                _relation_graph_payload(relation)
                for relation in inputs.context_inventory.relation_graph
            ],
            "visible_paths": [
                _visible_path_payload(path)
                for path in inputs.context_inventory.visible_paths
            ],
            "method_candidates": [
                _method_candidate_payload(method)
                for method in inputs.context_inventory.method_candidates
            ],
            "slot_options": [_slot_option_payload(option) for option in slot_options],
            "previous_errors": list(inputs.previous_errors),
            "output_json_schema": PLANNER_DRAFT_JSON_SCHEMA,
            "few_shot_examples": self.few_shot_loader.load_for_family(
                inputs.family_spec.family_id,
            ),
        }
        _assert_no_expected_answers(payload)
        return PlanningPayloadBuildResult(
            payload=payload,
            slot_options=slot_options,
        )


class FewShotExampleLoader:
    """加载同 family 的 few-shot 示例。

    首版不做 BM25/embedding 检索，只按 family_id 过滤并最多取 3 个。示例是 prompt
    辅助材料，不是答案库，因此加载后会检查不能含 expected answer 字段。
    """

    def __init__(self, example_dir: str | Path | None = None, *, limit: int = 3) -> None:
        self.example_dir = Path(example_dir) if example_dir else _default_example_dir()
        self.limit = limit

    def load_for_family(self, family_id: str) -> list[dict[str, Any]]:
        """返回同 family 的 few-shot 示例。"""
        if not self.example_dir.exists():
            return []
        examples: list[dict[str, Any]] = []
        for path in sorted(self.example_dir.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("family_id") != family_id:
                continue
            _assert_no_expected_answers(raw)
            examples.append(raw)
            if len(examples) >= self.limit:
                break
        return examples


class PlanningPromptRenderer:
    """渲染受控 planner 的 Jinja prompt 模板。"""

    def __init__(self, prompt_dir: str | Path | None = None) -> None:
        self.prompt_dir = Path(prompt_dir) if prompt_dir else _default_prompt_dir()
        self.environment = Environment(
            loader=FileSystemLoader(str(self.prompt_dir)),
            undefined=StrictUndefined,
            autoescape=False,
        )

    def render(self, payload: dict[str, Any]) -> RenderedPlannerPrompt:
        """把 payload 和完整 JSON schema 注入 system/user prompt。"""
        schema_json = json.dumps(
            payload["output_json_schema"],
            ensure_ascii=False,
            indent=2,
        )
        compact_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"output_json_schema", "few_shot_examples"}
        }
        system = self.environment.get_template("planner-system.jinja").render(
            output_json_schema_json=schema_json,
        )
        user = self.environment.get_template("planner-user.jinja").render(
            payload_json=json.dumps(compact_payload, ensure_ascii=False, indent=2),
            few_shot_examples_json=json.dumps(
                payload.get("few_shot_examples", []),
                ensure_ascii=False,
                indent=2,
            ),
        )
        return RenderedPlannerPrompt(system=system, user=user)


class AbstractPlanValidator:
    """校验 LLM draft 是否处于受控规划空间内。"""

    def validate_json(
        self,
        raw_response: str,
        inputs: PlannerInputs,
        slot_options: tuple[MethodSlotOptions, ...],
    ) -> PlannerDraft:
        """解析并校验 LLM 原始 JSON 字符串。"""
        draft = parse_planner_draft(raw_response)
        self.validate(draft, inputs, slot_options)
        return draft

    def validate(
        self,
        draft: PlannerDraft,
        inputs: PlannerInputs,
        slot_options: tuple[MethodSlotOptions, ...],
    ) -> None:
        """执行编译前语义校验，不读取或写入 RuntimeContext。"""
        known_scopes = _known_scope_ids(inputs.context_inventory, inputs.question_goals)
        known_promote_targets = _known_promote_targets(
            inputs.context_inventory,
            inputs.question_goals,
            draft.context_declarations,
        )
        slot_lookup = SlotBinder.index(slot_options)
        option_lookup = SlotBinder.option_index(slot_options)
        declaration_paths = _declaration_paths(draft.context_declarations)
        step_ids: set[str] = set()
        previous_outputs: dict[str, dict[str, str]] = {}
        previous_promotes: dict[str, dict[str, str]] = {}

        for declaration in draft.context_declarations:
            self._validate_declaration(declaration, known_scopes)

        for step in draft.steps:
            if step.step_id in step_ids:
                raise AbstractPlanValidationError(f"duplicate step_id: {step.step_id}")
            if step.scope_id not in known_scopes:
                raise AbstractPlanValidationError(f"unknown scope_id: {step.scope_id}")
            _parse_context_path(step.step_goal.target_path, "step_goal.target_path")
            self._validate_method_and_bindings(
                step,
                inputs.method_specs,
                slot_lookup,
                option_lookup,
                previous_outputs,
                previous_promotes,
                declaration_paths,
            )
            self._validate_promote_to(
                step,
                inputs.method_specs,
                known_scopes,
                known_promote_targets,
            )
            self._validate_depends_on(step, step_ids)
            step_ids.add(step.step_id)
            spec = inputs.method_specs.require(step.method_id)
            previous_outputs[step.step_id] = dict(spec.outputs)
            previous_promotes[step.step_id] = dict(step.promote_to)

    def _validate_declaration(
        self,
        declaration: ContextDeclarationDraft,
        known_scopes: set[str],
    ) -> None:
        """校验 declaration draft 不携带答案，只声明 PointRef 占位。"""
        parsed = _parse_context_path(declaration.path, "context_declaration.path")
        if declaration.type != "PointRef":
            raise AbstractPlanValidationError("context declaration type must be PointRef")
        if declaration.source != "planner":
            raise AbstractPlanValidationError("context declaration source must be planner")
        if parsed.container != "points":
            raise AbstractPlanValidationError("context declaration must write points container")
        if parsed.scope_id != declaration.scope_id:
            raise AbstractPlanValidationError("context declaration scope_id mismatch")
        if parsed.key != declaration.name:
            raise AbstractPlanValidationError("context declaration name mismatch")
        if declaration.scope_id not in known_scopes:
            raise AbstractPlanValidationError(
                f"unknown declaration scope_id: {declaration.scope_id}"
            )
        if not declaration.definition_intent:
            raise AbstractPlanValidationError("definition_intent must be non-empty")

    def _validate_method_and_bindings(
        self,
        step: LLMStepDraft,
        specs: MethodSpecRegistry,
        slot_lookup: dict[tuple[str, str, str], SlotCandidate],
        option_lookup: dict[tuple[str, str], MethodSlotOptions],
        previous_outputs: dict[str, dict[str, str]],
        previous_promotes: dict[str, dict[str, str]],
        declaration_paths: dict[tuple[str, str], str],
    ) -> None:
        """校验 method 存在，bindings 覆盖必填输入且只使用受控引用。"""
        try:
            spec = specs.require(step.method_id)
        except KeyError as exc:
            raise AbstractPlanValidationError(
                f"unknown method_id: {step.method_id}"
            ) from exc
        unknown_inputs = sorted(set(step.bindings) - set(spec.inputs))
        if unknown_inputs:
            raise AbstractPlanValidationError(
                f"unknown input binding(s) for {step.method_id}: {unknown_inputs}"
            )
        for input_name, input_spec in spec.inputs.items():
            if input_spec.required and input_name not in step.bindings:
                raise AbstractPlanValidationError(
                    f"missing required input {input_name} for {step.method_id}"
                )
        for input_name, candidate_id in step.bindings.items():
            input_spec = spec.inputs[input_name]
            if not isinstance(candidate_id, str) or not candidate_id:
                raise AbstractPlanValidationError(
                    f"binding {input_name} must be candidate id"
                )
            if candidate_id.startswith("$"):
                raise AbstractPlanValidationError(
                    f"binding {input_name} must use candidate id, not raw ContextPath"
                )
            if candidate_id.startswith("@step."):
                _validate_step_binding_ref(
                    candidate_id,
                    expected_type=input_spec.type,
                    current_step_id=step.step_id,
                    previous_outputs=previous_outputs,
                    previous_promotes=previous_promotes,
                )
                continue
            if candidate_id.startswith("@declaration."):
                _validate_declaration_binding_ref(
                    candidate_id,
                    expected_type=input_spec.type,
                    declaration_paths=declaration_paths,
                )
                continue
            option = option_lookup.get((step.method_id, input_name))
            if option is None:
                raise AbstractPlanValidationError(
                    f"slot options not found for {step.method_id}.{input_name}"
                )
            candidate = slot_lookup.get((step.method_id, input_name, candidate_id))
            if candidate is None:
                raise AbstractPlanValidationError(
                    f"unknown candidate id {candidate_id} for {step.method_id}.{input_name}"
                )
            if step.scope_id not in candidate.readable_from:
                raise AbstractPlanValidationError(
                    f"candidate {candidate_id} for {step.method_id}.{input_name} "
                    f"is not visible from scope {step.scope_id}"
                )
            if not _type_compatible(option.input_type, candidate.type):
                raise AbstractPlanValidationError(
                    f"candidate {candidate_id} type mismatch for {step.method_id}.{input_name}"
                )

    def _validate_promote_to(
        self,
        step: LLMStepDraft,
        specs: MethodSpecRegistry,
        known_scopes: set[str],
        known_promote_targets: set[str],
    ) -> None:
        """校验 promote_to 只引用 method 输出 key 和可写目标路径。

        对 Point 这类题设对象，target 必须已经可见或由 declaration 声明；对
        ``outputs`` 容器，Planner 可以创建新的 method 产物路径，但 scope 必须已知。
        这能比编译后的 PlanValidator 更早拦住拼错的点路径。
        """
        spec = specs.require(step.method_id)
        unknown_outputs = sorted(set(step.promote_to) - set(spec.outputs))
        if unknown_outputs:
            raise AbstractPlanValidationError(
                f"unknown promote output(s) for {step.method_id}: {unknown_outputs}"
            )
        for output_key, target_path in step.promote_to.items():
            parsed = _parse_context_path(target_path, f"promote_to.{output_key}")
            if target_path in known_promote_targets:
                continue
            if parsed.container == "outputs" and parsed.scope_id in known_scopes:
                continue
            raise AbstractPlanValidationError(
                f"unknown promote_to target_path: {target_path}"
            )

    def _validate_depends_on(self, step: LLMStepDraft, previous_step_ids: set[str]) -> None:
        """首版要求 depends_on 只能引用前序步骤，executor 仍按数组顺序执行。"""
        for dependency in step.depends_on:
            if dependency == step.step_id:
                raise AbstractPlanValidationError(
                    f"depends_on cannot reference itself: {step.step_id}"
                )
            if dependency not in previous_step_ids:
                raise AbstractPlanValidationError(
                    f"depends_on must reference an earlier step: {dependency}"
                )


class PlanCompiler:
    """把受控 LLM draft 编译成 runtime 可执行的 PlannerOutput。"""

    def __init__(self, validator: AbstractPlanValidator | None = None) -> None:
        self.validator = validator or AbstractPlanValidator()

    def compile(
        self,
        draft: PlannerDraft,
        inputs: PlannerInputs,
        slot_options: tuple[MethodSlotOptions, ...],
    ) -> PlannerOutput:
        """先做抽象校验，再生成 declarations 和 StepPlan。"""
        self.validator.validate(draft, inputs, slot_options)
        slot_lookup = SlotBinder.index(slot_options)
        declaration_paths = _declaration_paths(draft.context_declarations)
        declarations = [
            ContextDeclaration(
                path=declaration.path,
                type=declaration.type,
                name=declaration.name,
                definition={"definition": declaration.definition_intent},
                scope_id=declaration.scope_id,
                source=declaration.source,
            )
            for declaration in draft.context_declarations
        ]
        step_plans: list[StepPlan] = []
        previous_promotes: dict[str, dict[str, str]] = {}
        for step in draft.steps:
            spec = inputs.method_specs.require(step.method_id)
            step_plans.append(
                self._compile_step(
                    step,
                    spec,
                    slot_lookup,
                    declaration_paths,
                    previous_promotes,
                )
            )
            previous_promotes[step.step_id] = dict(step.promote_to)
        return PlannerOutput(
            context_declarations=declarations,
            step_plans=step_plans,
        )

    def _compile_step(
        self,
        step: LLMStepDraft,
        spec: MethodSpec,
        slot_lookup: dict[tuple[str, str, str], SlotCandidate],
        declaration_paths: dict[tuple[str, str], str],
        previous_promotes: dict[str, dict[str, str]],
    ) -> StepPlan:
        """把一个 LLMStepDraft 转为单 invocation 的 StepPlan。"""
        inputs = {
            input_name: _resolve_binding_path(
                step.method_id,
                input_name,
                candidate_id,
                slot_lookup,
                declaration_paths,
                previous_promotes,
            )
            for input_name, candidate_id in step.bindings.items()
        }
        outputs = {
            output_key: f"$step.{step.step_id}.temp.{output_key}"
            for output_key in spec.outputs
        }
        promote_outputs = {
            outputs[output_key]: target_path
            for output_key, target_path in step.promote_to.items()
        }
        goal = StepGoal(
            goal_id=f"{step.step_goal.type}:{step.step_id}",
            type=step.step_goal.type,
            target_path=step.step_goal.target_path,
            scope_id=step.scope_id,
            metadata={
                "value_type": step.step_goal.value_type,
                "description": step.step_goal.description,
                "reason": step.reason,
                "depends_on": list(step.depends_on),
            },
        )
        invocation = MethodInvocation(
            invocation_id=f"{step.step_id}.{step.method_id}",
            method_id=step.method_id,
            scope=step.step_id,
            inputs=inputs,
            outputs=outputs,
        )
        return StepPlan(
            step_id=step.step_id,
            goal=goal,
            scope=step.scope_id,
            invocations=[invocation],
            expected_outputs=list(step.promote_to.values()),
            promote_outputs=promote_outputs,
        )


class ControlledLLMPlanner(GenericPlanner):
    """Phase C 新增的受控 LLM Planner 入口。

    该类当前只在单测中直接实例化；默认 CLI 和 runtime config 仍走 legacy provider。
    """

    def __init__(
        self,
        client: LLMPlannerClient,
        *,
        payload_builder: PlanningPayloadBuilder | None = None,
        prompt_renderer: PlanningPromptRenderer | None = None,
        slot_binder: SlotBinder | None = None,
        compiler: PlanCompiler | None = None,
    ) -> None:
        self.client = client
        self.slot_binder = slot_binder or SlotBinder()
        self.payload_builder = payload_builder or PlanningPayloadBuilder(
            slot_binder=self.slot_binder,
        )
        self.prompt_renderer = prompt_renderer or PlanningPromptRenderer()
        self.compiler = compiler or PlanCompiler()
        self.last_payload: dict[str, Any] | None = None
        self.last_prompt: RenderedPlannerPrompt | None = None

    def plan(self, inputs: PlannerInputs) -> PlannerOutput:
        """构建 prompt、调用 LLM client，并编译成 PlannerOutput。"""
        build_result = self.payload_builder.build_with_slot_options(inputs)
        payload = build_result.payload
        prompt = self.prompt_renderer.render(payload)
        request_payload = {
            "family_id": inputs.family_spec.family_id,
            "problem_id": inputs.problem_id,
            "messages": prompt.as_messages(),
            "planner_payload": payload,
        }
        self.last_payload = payload
        self.last_prompt = prompt
        raw_response = self.client.complete(request_payload)
        slot_options = build_result.slot_options
        # 这里只做 JSON -> dataclass 解析；抽象语义校验统一交给 PlanCompiler，
        # 避免同一份 draft 被 validate 两次。
        draft = parse_planner_draft(raw_response)
        return self.compiler.compile(draft, inputs, slot_options)


def parse_planner_draft(raw_response: str) -> PlannerDraft:
    """把 LLM JSON 字符串解析成 PlannerDraft，并拒绝 schema 外字段。"""
    try:
        raw = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise AbstractPlanValidationError(f"invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise AbstractPlanValidationError("planner draft must be an object")
    _reject_extra_keys(raw, {"context_declarations", "steps"}, "planner draft")
    if "context_declarations" not in raw or "steps" not in raw:
        raise AbstractPlanValidationError(
            "planner draft requires context_declarations and steps"
        )
    declarations = _parse_declarations(raw["context_declarations"])
    steps = _parse_steps(raw["steps"])
    return PlannerDraft(
        context_declarations=tuple(declarations),
        steps=tuple(steps),
    )


def _parse_declarations(raw_declarations: Any) -> list[ContextDeclarationDraft]:
    """解析 context_declarations 数组。"""
    if not isinstance(raw_declarations, list):
        raise AbstractPlanValidationError("context_declarations must be list")
    declarations: list[ContextDeclarationDraft] = []
    allowed = {"path", "type", "name", "definition_intent", "scope_id", "source"}
    required = {"path", "type", "name", "definition_intent", "scope_id"}
    for index, raw in enumerate(raw_declarations):
        if not isinstance(raw, dict):
            raise AbstractPlanValidationError(f"context declaration {index} must be object")
        _reject_extra_keys(raw, allowed, f"context declaration {index}")
        _require_keys(raw, required, f"context declaration {index}")
        values = {key: raw[key] for key in required}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise AbstractPlanValidationError(
                f"context declaration {index} fields must be non-empty strings"
            )
        source = raw.get("source", "planner")
        if not isinstance(source, str) or not source:
            raise AbstractPlanValidationError(
                f"context declaration {index}.source must be non-empty string"
            )
        declarations.append(
            ContextDeclarationDraft(
                path=str(raw["path"]),
                type=str(raw["type"]),
                name=str(raw["name"]),
                definition_intent=str(raw["definition_intent"]),
                scope_id=str(raw["scope_id"]),
                source=source,
            )
        )
    return declarations


def _parse_steps(raw_steps: Any) -> list[LLMStepDraft]:
    """解析 steps 数组。"""
    if not isinstance(raw_steps, list):
        raise AbstractPlanValidationError("steps must be list")
    steps: list[LLMStepDraft] = []
    allowed = {
        "step_id",
        "scope_id",
        "step_goal",
        "method_id",
        "bindings",
        "promote_to",
        "depends_on",
        "reason",
    }
    required = set(allowed)
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise AbstractPlanValidationError(f"step {index} must be object")
        _reject_extra_keys(raw, allowed, f"step {index}")
        _require_keys(raw, required, f"step {index}")
        step_goal = _parse_step_goal(raw["step_goal"], index)
        bindings = _parse_string_map(raw["bindings"], f"step {index}.bindings")
        promote_to = _parse_string_map(raw["promote_to"], f"step {index}.promote_to")
        depends_on = _parse_string_list(raw["depends_on"], f"step {index}.depends_on")
        for field_name in ("step_id", "scope_id", "method_id", "reason"):
            if not isinstance(raw[field_name], str):
                raise AbstractPlanValidationError(
                    f"step {index}.{field_name} must be string"
                )
        if not raw["step_id"] or not raw["scope_id"] or not raw["method_id"]:
            raise AbstractPlanValidationError(
                f"step {index} id/scope/method fields must be non-empty"
            )
        steps.append(
            LLMStepDraft(
                step_id=str(raw["step_id"]),
                scope_id=str(raw["scope_id"]),
                step_goal=step_goal,
                method_id=str(raw["method_id"]),
                bindings=bindings,
                promote_to=promote_to,
                depends_on=tuple(depends_on),
                reason=str(raw["reason"]),
            )
        )
    return steps


def _parse_step_goal(raw: Any, index: int) -> StepGoalDraft:
    """解析 step_goal 对象。"""
    if not isinstance(raw, dict):
        raise AbstractPlanValidationError(f"step {index}.step_goal must be object")
    allowed = {"type", "target_path", "value_type", "description"}
    required = {"type", "target_path"}
    _reject_extra_keys(raw, allowed, f"step {index}.step_goal")
    _require_keys(raw, required, f"step {index}.step_goal")
    for key, value in raw.items():
        if not isinstance(value, str):
            raise AbstractPlanValidationError(
                f"step {index}.step_goal.{key} must be string"
            )
    if not raw["type"] or not raw["target_path"]:
        raise AbstractPlanValidationError(
            f"step {index}.step_goal type/target_path must be non-empty"
        )
    return StepGoalDraft(
        type=str(raw["type"]),
        target_path=str(raw["target_path"]),
        value_type=str(raw.get("value_type", "")),
        description=str(raw.get("description", "")),
    )


def _reject_extra_keys(raw: dict[str, Any], allowed: set[str], label: str) -> None:
    """拒绝 schema 外字段，尤其是 answer/value/coordinate 这类越界输出。"""
    extra = sorted(set(raw) - allowed)
    if extra:
        raise AbstractPlanValidationError(f"{label} has unknown field(s): {extra}")


def _require_keys(raw: dict[str, Any], required: set[str], label: str) -> None:
    """检查必填字段。"""
    missing = sorted(required - set(raw))
    if missing:
        raise AbstractPlanValidationError(f"{label} missing field(s): {missing}")


def _parse_string_map(raw: Any, label: str) -> dict[str, str]:
    """解析 string->string 对象。"""
    if not isinstance(raw, dict):
        raise AbstractPlanValidationError(f"{label} must be object")
    result: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise AbstractPlanValidationError(f"{label} must be string map")
        result[key] = value
    return result


def _parse_string_list(raw: Any, label: str) -> list[str]:
    """解析字符串数组。"""
    if not isinstance(raw, list):
        raise AbstractPlanValidationError(f"{label} must be list")
    if not all(isinstance(value, str) for value in raw):
        raise AbstractPlanValidationError(f"{label} must contain strings")
    return [str(value) for value in raw]


def _validate_step_binding_ref(
    reference: str,
    *,
    expected_type: str,
    current_step_id: str,
    previous_outputs: dict[str, dict[str, str]],
    previous_promotes: dict[str, dict[str, str]],
) -> str:
    """校验 ``@step.<step_id>.<output_key>``，并返回被引用输出的类型。"""
    step_id, output_key = _parse_step_binding_ref(reference)
    if step_id == current_step_id:
        raise AbstractPlanValidationError(
            f"step binding cannot reference itself: {reference}"
        )
    if step_id not in previous_outputs:
        raise AbstractPlanValidationError(
            f"step binding references unknown or future step: {reference}"
        )
    output_types = previous_outputs[step_id]
    if output_key not in output_types:
        raise AbstractPlanValidationError(
            f"step binding references unknown output: {reference}"
        )
    if output_key not in previous_promotes.get(step_id, {}):
        raise AbstractPlanValidationError(
            f"step binding references unpromoted output: {reference}"
        )
    actual_type = output_types[output_key]
    if not _type_compatible(expected_type, actual_type):
        raise AbstractPlanValidationError(
            f"step binding {reference} type mismatch: expected {expected_type}, got {actual_type}"
        )
    return actual_type


def _validate_declaration_binding_ref(
    reference: str,
    *,
    expected_type: str,
    declaration_paths: dict[tuple[str, str], str],
) -> str:
    """校验 ``@declaration.<scope_id>.<name>``，并返回 PointRef 类型。"""
    scope_id, name = _parse_declaration_binding_ref(reference)
    if (scope_id, name) not in declaration_paths:
        raise AbstractPlanValidationError(
            f"declaration binding references unknown declaration: {reference}"
        )
    if not _type_compatible(expected_type, "PointRef"):
        raise AbstractPlanValidationError(
            f"declaration binding {reference} type mismatch: expected {expected_type}, got PointRef"
        )
    return "PointRef"


def _parse_step_binding_ref(reference: str) -> tuple[str, str]:
    """解析 ``@step.<step_id>.<output_key>``。"""
    parts = reference.split(".")
    if len(parts) != 3 or parts[0] != "@step" or not parts[1] or not parts[2]:
        raise AbstractPlanValidationError(
            f"invalid step binding reference: {reference}"
        )
    return parts[1], parts[2]


def _parse_declaration_binding_ref(reference: str) -> tuple[str, str]:
    """解析 ``@declaration.<scope_id>.<name>``。"""
    parts = reference.split(".")
    if len(parts) != 3 or parts[0] != "@declaration" or not parts[1] or not parts[2]:
        raise AbstractPlanValidationError(
            f"invalid declaration binding reference: {reference}"
        )
    return parts[1], parts[2]


def _resolve_binding_path(
    method_id: str,
    input_name: str,
    binding: str,
    slot_lookup: dict[tuple[str, str, str], SlotCandidate],
    declaration_paths: dict[tuple[str, str], str],
    previous_promotes: dict[str, dict[str, str]],
) -> str:
    """把 candidate id / @step / @declaration 解析成真正 ContextPath。"""
    if binding.startswith("@step."):
        step_id, output_key = _parse_step_binding_ref(binding)
        return previous_promotes[step_id][output_key]
    if binding.startswith("@declaration."):
        scope_id, name = _parse_declaration_binding_ref(binding)
        return declaration_paths[(scope_id, name)]
    return slot_lookup[(method_id, input_name, binding)].path


def _declaration_paths(
    declarations: tuple[ContextDeclarationDraft, ...],
) -> dict[tuple[str, str], str]:
    """按 ``(scope_id, name)`` 索引 draft declaration path。"""
    return {
        (declaration.scope_id, declaration.name): declaration.path
        for declaration in declarations
    }


def _type_compatible(expected: str, actual: str) -> bool:
    """判断候选类型是否可用于 MethodSpec 输入类型。

    ``RuntimeContext.read_path(expected_type="Point")`` 可以即时解析 ``PointRef``，
    因此 planner 层也允许 Point 输入绑定到 PointRef 候选。
    """
    if expected == actual:
        return True
    return expected == "Point" and actual == "PointRef"


def _known_scope_ids(
    inventory: ContextInventory,
    question_goals: list[QuestionGoal],
) -> set[str]:
    """从 inventory 和 QuestionGoal 中收集 planner 可见 scope id。"""
    scopes = {"problem"}
    for path in inventory.visible_paths:
        scopes.add(path.scope_id)
        scopes.update(path.readable_from)
    for signal in inventory.planning_signals:
        scopes.add(signal.scope_id)
    for goal in question_goals:
        scopes.add(goal.question_id)
    return scopes


def _known_promote_targets(
    inventory: ContextInventory,
    question_goals: list[QuestionGoal],
    declarations: tuple[ContextDeclarationDraft, ...],
) -> set[str]:
    """收集 AbstractPlanValidator 可提前确认的 promote 目标路径。"""
    targets = {path.path for path in inventory.visible_paths}
    targets.update(goal.target_path for goal in question_goals)
    targets.update(signal.path for signal in inventory.planning_signals)
    targets.update(declaration.path for declaration in declarations)
    return targets


def _parse_context_path(raw: str, label: str) -> ContextPath:
    """解析 ContextPath，并把错误归一成 AbstractPlanValidationError。"""
    try:
        return ContextPath.parse(raw)
    except ValueError as exc:
        raise AbstractPlanValidationError(f"{label} must be valid ContextPath") from exc


def _family_payload(family_spec: Any) -> dict[str, Any]:
    """把 FamilySpec 转成 prompt 友好的只读摘要。"""
    return {
        "family_id": family_spec.family_id,
        "common_goal_types": list(family_spec.common_goal_types),
        "strategy_principles": list(family_spec.strategy_principles),
        "relation_patterns": list(family_spec.relation_patterns),
        "method_capability_hints": list(family_spec.method_capability_hints),
        "result_collection_policy": family_spec.result_collection_policy,
    }


def _question_goal_payload(goal: QuestionGoal) -> dict[str, Any]:
    """序列化题面最终作答目标。"""
    return {
        "question_id": goal.question_id,
        "id": goal.id,
        "answer_key": goal.answer_key,
        "target_path": goal.target_path,
        "value_type": goal.value_type,
        "required": goal.required,
    }


def _planning_signal_payload(signal: PlanningSignalEntry) -> dict[str, Any]:
    """序列化 PlanningSignal。"""
    return {
        "signal_type": signal.signal_type,
        "path": signal.path,
        "scope_id": signal.scope_id,
        "source_ref": signal.source_ref,
        "participants": list(signal.participants),
        "roles": dict(signal.roles),
        "reason": signal.reason,
    }


def _relation_graph_payload(relation: RelationGraphEntry) -> dict[str, Any]:
    """序列化 relation graph entry。"""
    return {
        "relation_type": relation.relation_type,
        "participants": list(relation.participants),
        "roles": dict(relation.roles),
        "scope_id": relation.scope_id,
        "source_ref": relation.source_ref,
    }


def _visible_path_payload(path: VisibleContextPath) -> dict[str, Any]:
    """序列化可见 ContextPath 摘要。"""
    return {
        "path": path.path,
        "type": path.type,
        "scope_id": path.scope_id,
        "scope_type": path.scope_type,
        "container": path.container,
        "key": path.key,
        "locked": path.locked,
        "source": path.source,
        "readable_from": list(path.readable_from),
        "description": path.description,
        "definition": dict(path.definition),
    }


def _method_candidate_payload(method: MethodCandidateEntry) -> dict[str, Any]:
    """序列化 method candidate 摘要。"""
    return {
        "method_id": method.method_id,
        "title": method.title,
        "solves": list(method.solves),
        "input_slots": dict(method.input_slots),
        "output_slots": dict(method.output_slots),
        "required_inputs": list(method.required_inputs),
    }


def _slot_option_payload(option: MethodSlotOptions) -> dict[str, Any]:
    """序列化槽位候选，供 LLM 只能按 candidate_id 选择。"""
    return {
        "method_id": option.method_id,
        "input_name": option.input_name,
        "input_type": option.input_type,
        "required": option.required,
        "candidates": [
            {
                "candidate_id": candidate.candidate_id,
                "path": candidate.path,
                "type": candidate.type,
                "scope_id": candidate.scope_id,
                "readable_from": list(candidate.readable_from),
                "description": candidate.description,
            }
            for candidate in option.candidates
        ],
    }


def _assert_no_expected_answers(payload: Any) -> None:
    """防止 prompt payload 或 few-shot 示例夹带测试期望答案。"""
    lowered = json.dumps(payload, ensure_ascii=False).lower()
    forbidden_tokens = ("expected_answer", "expected_answers")
    if any(token in lowered for token in forbidden_tokens):
        raise ValueError("planner payload must not include expected answers")


def _default_prompt_dir() -> Path:
    """返回默认 prompt 模板目录。"""
    return _repo_root() / "internal" / "llm-prompts"


def _default_example_dir() -> Path:
    """返回默认 few-shot 示例目录。"""
    return _default_prompt_dir() / "planner-examples"


def _repo_root() -> Path:
    """从当前文件向上查找仓库根目录。

    不使用固定 parents 下标，避免 runtime 模块移动后静默定位到错误目录。
    """
    current = Path(__file__).resolve()
    for directory in (current.parent, *current.parents):
        if (directory / ".git").exists():
            return directory
        if (directory / "internal").is_dir() and (directory / "server").is_dir():
            return directory
    raise RuntimeError(f"cannot locate repository root from {current}")


def summarize_slot_options(
    slot_options: tuple[MethodSlotOptions, ...],
) -> dict[str, dict[str, list[str]]]:
    """测试/调试 helper：按 method/input 汇总候选 path。"""
    summary: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for option in slot_options:
        summary[option.method_id][option.input_name] = [
            candidate.path for candidate in option.candidates
        ]
    return dict(summary)
