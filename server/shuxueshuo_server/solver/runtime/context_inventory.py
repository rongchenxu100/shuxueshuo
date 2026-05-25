"""Planner 使用的运行时上下文索引。

``ContextInventory`` 是从 ``RuntimeContext`` 派生出的只读规划摘要。它不是新的事实
源，也不参与执行；真正执行 method 时仍然必须回到 ``RuntimeContext`` 通过
``ContextPath`` 读取 typed value。

这层的目的，是把后续 LLM Planner 能看到的内容收束成有限集合：可见路径、关系图、
约束、规划信号和 method 候选，避免 Planner 自由编造变量、路径或答案。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shuxueshuo_server.solver.contracts import MethodSpec, TypedValue
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import PointRef, RuntimeScope


@dataclass(frozen=True)
class VisibleContextPath:
    """一个 Planner 可以引用的 ContextPath 摘要。

    ``readable_from`` 记录哪些 scope 能读取该路径。LLM Planner 后续只能选择这些已
    枚举路径，不能自己发明路径或直接写裸值。
    """

    path: str
    type: str
    scope_id: str
    scope_type: str
    container: str
    key: str
    locked: bool
    source: str
    readable_from: tuple[str, ...]
    description: str = ""


@dataclass(frozen=True)
class RelationGraphEntry:
    """ProblemIR relation 的轻量图索引。

    ``source_ref`` 是稳定文本引用，用来在调试和 LLM prompt 中回溯来源。
    relation graph 只索引 ``ProblemIR.data.relations`` 中的题面关系，不再从点
    definition 中反推出 method 化关系。
    """

    relation_type: str
    participants: tuple[str, ...]
    roles: dict[str, str] = field(default_factory=dict)
    scope_id: str = ""
    source_ref: str = ""


@dataclass(frozen=True)
class ConstraintInventoryEntry:
    """约束路径摘要。"""

    path: str
    type: str
    scope_id: str
    key: str
    locked: bool
    source: str
    expression_or_semantic_hint: str = ""


@dataclass(frozen=True)
class MethodCandidateEntry:
    """MethodSpec 的规划摘要。"""

    method_id: str
    title: str
    solves: tuple[str, ...]
    input_slots: dict[str, str]
    output_slots: dict[str, str]
    required_inputs: tuple[str, ...]


@dataclass(frozen=True)
class PlanningSignalEntry:
    """Planner 可注意的确定性上下文信号。

    ``PlanningSignal`` 不是目标，也不是步骤。它只提醒 Planner：当前上下文里有某个
    未解析对象、关系或约束值得关注。生成过程完全由代码规则完成，不调用 LLM。
    """

    signal_type: str
    path: str
    scope_id: str
    source_ref: str
    participants: tuple[str, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)
    reason: str = ""


@dataclass(frozen=True)
class ContextInventory:
    """RuntimeContext 的只读规划索引。"""

    visible_paths: tuple[VisibleContextPath, ...] = ()
    relation_graph: tuple[RelationGraphEntry, ...] = ()
    constraints: tuple[ConstraintInventoryEntry, ...] = ()
    planning_signals: tuple[PlanningSignalEntry, ...] = ()
    method_candidates: tuple[MethodCandidateEntry, ...] = ()

    def find_path(self, raw_path: str) -> VisibleContextPath | None:
        """按 ContextPath 查找索引记录。"""
        for item in self.visible_paths:
            if item.path == raw_path:
                return item
        return None

    def paths_by_type(self, value_type: str) -> tuple[VisibleContextPath, ...]:
        """返回某个 runtime 类型的全部可规划路径。"""
        return tuple(item for item in self.visible_paths if item.type == value_type)

    def find_method(self, method_id: str) -> MethodCandidateEntry | None:
        """按 method_id 查找 method 候选摘要。"""
        for item in self.method_candidates:
            if item.method_id == method_id:
                return item
        return None

    def methods_for_goal(self, goal_type: str) -> tuple[MethodCandidateEntry, ...]:
        """返回声明可解决某类 goal 的 method 候选。"""
        return tuple(
            item for item in self.method_candidates
            if goal_type in item.solves
        )

    def signals_by_type(self, signal_type: str) -> tuple[PlanningSignalEntry, ...]:
        """返回某类规划信号。"""
        return tuple(
            item for item in self.planning_signals
            if item.signal_type == signal_type
        )


class ContextInventoryBuilder:
    """从 RuntimeContext 和 MethodSpecRegistry 构建规划索引。"""

    def build(
        self,
        context: RuntimeContext,
        method_specs: MethodSpecRegistry,
    ) -> ContextInventory:
        """构建完整 ContextInventory。

        构建过程只读取 RuntimeContext，不写入 scope，也不解析答案。这样它可以安全地
        用在 Planner 前置阶段和测试里。
        """
        visible_paths = tuple(self._visible_paths(context))
        relation_graph = tuple(self._relation_graph(context))
        constraints = tuple(self._constraints(context))
        return ContextInventory(
            visible_paths=visible_paths,
            relation_graph=relation_graph,
            constraints=constraints,
            planning_signals=tuple(self._planning_signals(context, relation_graph)),
            method_candidates=tuple(self._method_candidates(method_specs)),
        )

    def _visible_paths(self, context: RuntimeContext) -> list[VisibleContextPath]:
        """枚举所有 scope 容器中的 typed value。"""
        paths: list[VisibleContextPath] = []
        for scope in context.scopes.values():
            for container, values in _scope_containers(scope).items():
                for key, typed_value in values.items():
                    paths.append(
                        VisibleContextPath(
                            path=_format_path(scope, container, key),
                            type=typed_value.type,
                            scope_id=scope.scope_id,
                            scope_type=scope.scope_type,
                            container=container,
                            key=key,
                            locked=typed_value.locked,
                            source=typed_value.source,
                            readable_from=_readable_from(context, scope.scope_id),
                            description=_describe_value(typed_value),
                        )
                    )
        return paths

    def _relation_graph(self, context: RuntimeContext) -> list[RelationGraphEntry]:
        """构建轻量 relation graph。

        relation graph 只来自 ``ProblemIR.data.relations``。点 definition 只表达点本身
        是否未知、是否可即时解析；几何语义必须由题面 relation 表达。
        """
        entries: list[RelationGraphEntry] = []
        for index, relation in enumerate(context.problem.data.get("relations", [])):
            if not isinstance(relation, dict):
                continue
            relation_type = str(relation.get("type", ""))
            entries.append(
                RelationGraphEntry(
                    relation_type=relation_type,
                    participants=tuple(sorted(_relation_point_names(relation))),
                    roles={
                        str(key): _stringify_role(value)
                        for key, value in relation.items()
                        if key not in {"type", "scope"}
                    },
                    scope_id=str(relation.get("scope", "")),
                    source_ref=f"ProblemIR.data.relations[{index}]",
                )
            )
        return entries

    def _constraints(self, context: RuntimeContext) -> list[ConstraintInventoryEntry]:
        """枚举每个 scope 的 constraints 固定容器。"""
        constraints: list[ConstraintInventoryEntry] = []
        for scope in context.scopes.values():
            for key, typed_value in scope.constraints.items():
                constraints.append(
                    ConstraintInventoryEntry(
                        path=_format_path(scope, "constraints", key),
                        type=typed_value.type,
                        scope_id=scope.scope_id,
                        key=key,
                        locked=typed_value.locked,
                        source=typed_value.source,
                        expression_or_semantic_hint=_stringify_role(typed_value.value),
                    )
                )
        return constraints

    def _method_candidates(
        self,
        method_specs: MethodSpecRegistry,
    ) -> list[MethodCandidateEntry]:
        """把 MethodSpecRegistry 转成 planner 容易消费的 method 摘要。"""
        candidates: list[MethodCandidateEntry] = []
        for spec in method_specs.specs.values():
            candidates.append(_method_candidate(spec))
        return candidates

    def _planning_signals(
        self,
        context: RuntimeContext,
        relation_graph: tuple[RelationGraphEntry, ...],
    ) -> list[PlanningSignalEntry]:
        """从上下文索引中生成确定性规划信号。"""
        signals: list[PlanningSignalEntry] = []
        unresolved_points = _unknown_point_refs(context)
        for point_name, (path, scope_id, _point_ref) in unresolved_points.items():
            signals.append(
                PlanningSignalEntry(
                    signal_type="unresolved_point_ref",
                    path=path,
                    scope_id=scope_id,
                    source_ref=f"{path}.definition",
                    participants=(point_name,),
                    roles={"point": point_name},
                    reason="点已声明但坐标未知",
                )
            )
        for scope in context.scopes.values():
            for key, typed_value in scope.constraints.items():
                if typed_value.type != "OrientationHint":
                    continue
                path = _format_path(scope, "constraints", key)
                point_name = key.removesuffix("_quadrant")
                signals.append(
                    PlanningSignalEntry(
                        signal_type="orientation_constraint",
                        path=path,
                        scope_id=scope.scope_id,
                        source_ref=path,
                        participants=(point_name,),
                        roles={"point": point_name, "constraint": key},
                        reason="题面给出点的方位约束",
                    )
                )
        for relation in relation_graph:
            if relation.relation_type != "right_angle_equal_length":
                continue
            for target in relation.participants:
                if target not in unresolved_points:
                    continue
                path, scope_id, _point_ref = unresolved_points[target]
                roles = _right_angle_roles_for_target(relation, target)
                signals.append(
                    PlanningSignalEntry(
                        signal_type="constructible_right_angle_equal_length_point",
                        path=path,
                        scope_id=scope_id,
                        source_ref=relation.source_ref,
                        participants=relation.participants,
                        roles=roles,
                        reason="未知点参与直角等长关系，可由候选构造与约束筛选",
                    )
                )
        return signals


def _scope_containers(scope: RuntimeScope) -> dict[str, dict[str, TypedValue]]:
    """返回 scope 中已经存在的容器，避免调用 ``container`` 时创建空容器。"""
    containers: dict[str, dict[str, TypedValue]] = dict(scope.facts)
    if scope.constraints:
        containers["constraints"] = scope.constraints
    if scope.temp_values:
        containers["temp"] = scope.temp_values
    if scope.outputs:
        containers["outputs"] = scope.outputs
    return containers


def _format_path(scope: RuntimeScope, container: str, key: str) -> str:
    """按 RuntimeContext 约定生成 ContextPath 字符串。"""
    if scope.scope_type == "problem":
        return f"$problem.{container}.{key}"
    return f"${scope.scope_type}.{scope.scope_id}.{container}.{key}"


def _readable_from(context: RuntimeContext, target_scope_id: str) -> tuple[str, ...]:
    """枚举哪些 scope 能读取目标 scope 的路径。"""
    return tuple(
        scope_id for scope_id in context.scopes
        if context.is_visible(scope_id, target_scope_id)
    )


def _describe_value(value: TypedValue) -> str:
    """生成给 Planner/调试使用的短描述，不承诺可逆解析。"""
    if value.type == "PointRef":
        return f"PointRef({getattr(value.value, 'name', '')})"
    return f"{value.type} from {value.source}"


def _method_candidate(spec: MethodSpec) -> MethodCandidateEntry:
    """把完整 MethodSpec 压缩成规划候选摘要。"""
    return MethodCandidateEntry(
        method_id=spec.method_id,
        title=spec.title,
        solves=spec.solves,
        input_slots={name: input_spec.type for name, input_spec in spec.inputs.items()},
        output_slots=dict(spec.outputs),
        required_inputs=tuple(
            name for name, input_spec in spec.inputs.items()
            if input_spec.required
        ),
    )


def _unknown_point_refs(
    context: RuntimeContext,
) -> dict[str, tuple[str, str, PointRef]]:
    """返回 definition=unknown 的点引用索引。"""
    refs: dict[str, tuple[str, str, PointRef]] = {}
    for scope in context.scopes.values():
        for name, typed_value in scope.container("points").items():
            if typed_value.type != "PointRef":
                continue
            point_ref: PointRef = typed_value.value
            if point_ref.definition.get("definition") != "unknown":
                continue
            refs[point_ref.name or name] = (
                _format_path(scope, "points", name),
                scope.scope_id,
                point_ref,
            )
    return refs


def _right_angle_roles_for_target(
    relation: RelationGraphEntry,
    target: str,
) -> dict[str, str]:
    """从 right_angle_equal_length relation 中推导 target 的角色。"""
    angle = relation.roles.get("angle", "")
    angle_points = [
        item.strip()
        for item in angle.strip("[]").split(",")
        if item.strip()
    ]
    anchor = ""
    reference = ""
    if len(angle_points) == 3:
        anchor = angle_points[1]
        endpoints = [angle_points[0], angle_points[2]]
        reference = endpoints[1] if endpoints[0] == target else endpoints[0]
    return {
        "target": target,
        "anchor": anchor,
        "reference": reference,
        "relation_type": relation.relation_type,
    }


def _relation_point_names(value: Any) -> set[str]:
    """递归提取 relation 结构中的大写点名。"""
    if isinstance(value, str):
        if value.isalpha() and value[:1].isupper():
            return {value}
        return set()
    if isinstance(value, dict):
        names: set[str] = set()
        for child in value.values():
            names.update(_relation_point_names(child))
        return names
    if isinstance(value, list):
        names: set[str] = set()
        for child in value:
            names.update(_relation_point_names(child))
        return names
    return set()


def _stringify_role(value: Any) -> str:
    """把 relation/constraint 的值压成短字符串，供 Planner prompt 或测试断言使用。"""
    if isinstance(value, dict):
        return ", ".join(
            f"{key}={_stringify_role(child)}"
            for key, child in sorted(value.items())
        )
    if isinstance(value, list):
        return "[" + ", ".join(_stringify_role(child) for child in value) + "]"
    return str(value)
