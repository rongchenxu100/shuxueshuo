"""V1.5 Planner 接口与规则样板。

这个模块不是最终的智能 Planner，而是一个可测试的 V1.5 样板：

1. PlannerInputs 只携带题面作答目标、ContextInventory 和 MethodSpec；
2. 规则样板从 PlanningSignal 生成 StepGoal 和 MethodInvocation；
3. 只输出 ContextPath 映射，不直接计算答案。

后续接 LLM Planner 时，也应该输出同样的 StepPlan/MethodInvocation 结构，再交给
PlanValidator 和 InvocationExecutor。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from shuxueshuo_server.solver.family.models import SolverFamilySpec
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.context_inventory import (
    ContextInventory,
    PlanningSignalEntry,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    PlannerOutput,
    PointRef,
    StepGoal,
    StepPlan,
)


@dataclass(frozen=True)
class PlannerInputs:
    """通用 Planner 的输入包。

    ``question_goals`` 是题面最终作答目标；``context_inventory.planning_signals``
    是确定性上下文索引。Planner 根据它们生成 StepGoal/StepPlan。
    """

    problem_id: str
    family_spec: SolverFamilySpec
    question_goals: list[QuestionGoal]
    context_inventory: ContextInventory
    method_specs: MethodSpecRegistry
    previous_errors: list[object] = field(default_factory=list)


@runtime_checkable
class GenericPlanner(Protocol):
    """通用 Planner 接口。

    实现者只能返回 PlannerOutput，不应该直接执行 method、写 RuntimeContext 或
    生成最终 answers。真实 LLM Planner 接入后也必须遵守这个接口。
    """

    def plan(self, inputs: PlannerInputs) -> PlannerOutput:
        """把 PlannerInputs 转成 declarations + 可执行 StepPlan。"""
        ...


class Nankai25DeterministicPlannerAdapter:
    """把当前南开固定 planner 包装成 GenericPlanner 形状。

    Phase 4 的 RuntimeOrchestrator 通过静态 provider 使用它，让当前南开
    deterministic slice 可以先接入通用 Planner 接口。它不会读取 ``answer_paths()``。
    """

    def __init__(self, context: RuntimeContext, delegate: object | None = None) -> None:
        from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
            QuadraticPathMinimumPlannerV15,
        )

        self.context = context
        self.delegate = delegate or QuadraticPathMinimumPlannerV15()

    def plan(self, inputs: PlannerInputs) -> PlannerOutput:
        """委托当前南开 deterministic planner 生成 PlannerOutput。"""
        output = self.delegate.plan(self.context)
        if isinstance(output, PlannerOutput):
            return output
        # 兼容测试中注入的旧形态 delegate；仓库内置 planner 会全部迁移到 PlannerOutput。
        return PlannerOutput(step_plans=list(output))


class RuleBasedStepPlannerV15:
    """基于规则的 V1.5 StepPlan 生成器。

    这版 planner 的目标是验证 invocation 抽象，而不是覆盖所有题型。它通过
    MethodSpec 查找可解决 signal 的 method，再从 relation roles 中推断
    anchor/reference/target 三个输入槽位。
    """

    def __init__(self, specs: MethodSpecRegistry) -> None:
        self.specs = specs

    def plan(self, context: RuntimeContext, signal: PlanningSignalEntry) -> StepPlan | None:
        """把单个 PlanningSignal 展开成 StepPlan。

        找不到匹配 MethodSpec 或必要点路径时返回 ``None``，由调用方决定是否进入
        fallback。当前实现不会调用 LLM。
        """
        if signal.signal_type != "constructible_right_angle_equal_length_point":
            return None
        try:
            candidate_spec = self.specs.require("right_angle_equal_length_candidates")
            selector_spec = self.specs.require("select_point_by_quadrant_constraint")
        except KeyError:
            return None
        if not candidate_spec or not selector_spec:
            return None
        target_value = context.read_path(
            signal.path,
            from_scope_id=signal.scope_id,
            expected_type="PointRef",
        )
        target_ref: PointRef = target_value.value
        names = _resolve_right_angle_names(context, signal, target_ref)
        # 点名映射完成后，再交给 RuntimeContext 查找具体 ContextPath。这样 method
        # 不知道 D/M/N 或 A/C/D 这些题目局部命名。
        anchor_path = context.find_visible_path(
            "points", names["anchor"], from_scope_id=signal.scope_id,
        )
        reference_path = context.find_visible_path(
            "points", names["reference"], from_scope_id=signal.scope_id,
        )
        if anchor_path is None or reference_path is None:
            return None
        step_id = f"derive_{target_ref.name}"
        context.ensure_step_scope(step_id, signal.scope_id)
        inputs = {
            "anchor": anchor_path,
            "reference": reference_path,
            "target": signal.path,
        }
        orientation_path = context.find_visible_path(
            "constraints",
            f"{target_ref.name}_quadrant",
            from_scope_id=signal.scope_id,
        )
        parameter_name = _dynamic_parameter_name(context)
        parameter_path = f"$problem.symbols.{parameter_name}" if parameter_name else None
        constraint_path = f"$problem.constraints.{parameter_name}" if parameter_name else None
        if orientation_path is None or parameter_path is None or constraint_path is None:
            return None
        try:
            context.read_path(parameter_path, from_scope_id=signal.scope_id, expected_type="Symbol")
            context.read_path(constraint_path, from_scope_id=signal.scope_id, expected_type="Constraint")
        except (KeyError, TypeError, PermissionError):
            return None
        candidates_path = f"$step.{step_id}.temp.candidates"
        selected_path = f"$step.{step_id}.temp.selected_point"
        candidate_invocation = MethodInvocation(
            invocation_id=f"{step_id}.right_angle_equal_length_candidates",
            method_id=candidate_spec.method_id,
            scope=step_id,
            inputs=inputs,
            outputs={"candidates": candidates_path},
        )
        selector_invocation = MethodInvocation(
            invocation_id=f"{step_id}.select_point_by_quadrant_constraint",
            method_id=selector_spec.method_id,
            scope=step_id,
            inputs={
                "candidates": candidates_path,
                "target": signal.path,
                "quadrant": orientation_path,
                "parameter": parameter_path,
                "parameter_constraint": constraint_path,
            },
            outputs={"selected_point": selected_path},
        )
        return StepPlan(
            step_id=step_id,
            goal=StepGoal(
                goal_id=f"derive_point_coordinate:{signal.scope_id}:{target_ref.name}",
                type="derive_point_coordinate",
                target_path=signal.path,
                scope_id=signal.scope_id,
                metadata={
                    "point": target_ref.name,
                    "signal_type": signal.signal_type,
                    "source_ref": signal.source_ref,
                },
            ),
            scope=signal.scope_id,
            invocations=[candidate_invocation, selector_invocation],
            expected_outputs=[signal.path],
            # 先写 step temp，再显式 promote 到目标点路径。这个动作是防止临时结果
            # 默认污染上层 scope 的关键。
            promote_outputs={selected_path: signal.path},
        )


def _resolve_right_angle_names(
    context: RuntimeContext,
    signal: PlanningSignalEntry,
    target: PointRef,
) -> dict[str, str]:
    """解析直角等腰关系中的 anchor/reference/target 点名。

    优先读取 PlanningSignal 中由 relation graph 推导出的角色；缺失时再回到
    ProblemIR.data.relations 反推。
    """
    if signal.roles.get("anchor") and signal.roles.get("reference"):
        return {
            "anchor": str(signal.roles["anchor"]),
            "reference": str(signal.roles["reference"]),
            "target": target.name,
        }
    relation = _find_right_angle_relation(context, signal.scope_id, target.name)
    if relation is None:
        raise KeyError(f"right_angle_equal_length relation not found for {target.name}")
    angle = relation.get("angle", [])
    if not isinstance(angle, list) or len(angle) != 3:
        raise ValueError("right_angle_equal_length relation requires angle triplet")
    anchor = str(angle[1])
    if str(angle[0]) == target.name:
        reference = str(angle[2])
    else:
        reference = str(angle[0])
    return {"anchor": anchor, "reference": reference, "target": target.name}


def _find_right_angle_relation(
    context: RuntimeContext,
    scope_id: str,
    target_name: str,
) -> Mapping[str, object] | None:
    """在题目 relations 中查找包含 target 的 right_angle_equal_length 关系。"""
    for relation in context.problem.data.get("relations", []):
        if relation.get("type") != "right_angle_equal_length":
            continue
        if target_name not in str(relation):
            continue
        relation_scope = str(relation.get("scope", ""))
        if relation_scope and relation_scope not in {scope_id, f"part_{scope_id}"}:
            continue
        return relation
    return None


def _dynamic_parameter_name(context: RuntimeContext) -> str | None:
    """从题目结构中找动态参数名，用于显式绑定参数约束。"""
    parameter = context.problem.data.get("parameter")
    if isinstance(parameter, str):
        return parameter
    for name, role in context.problem.data.get("symbol_roles", {}).items():
        if role == "dynamic_parameter":
            return str(name)
    return None
