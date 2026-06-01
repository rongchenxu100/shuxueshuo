"""V1.5 多层运行时上下文与 ContextPath 解析。

RuntimeContext 是 Method Solver V1.5 的“黑板”。它把一份 ``ProblemIR`` 转成
有层级的 scope 树，让 planner/executor 可以在明确边界内读写事实：

``problem -> question -> subquestion -> step``

这层代码的核心目标不是解题，而是约束解题过程：

- 下层 scope 可以读取父级事实；
- sibling scope 不能互相读取，避免第（Ⅱ）①问的参数污染第（Ⅱ）②问；
- step 临时结果默认只能留在 step 内；
- 只有 StepPlan 显式 ``promote_outputs`` 的结果才能写回上层。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

import sympy as sp

from shuxueshuo_server.solver.math_ops import (
    axis_x_from_relation,
    vertex_of_quadratic,
    y_axis_intercept,
)
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    Point,
    PointRef,
    RuntimeScope,
    TypedValue,
)


class RuntimeContext:
    """V1.5 method invocation 使用的层级黑板。

    这个对象持有：

    - 原始 ``ProblemIR``，用于回溯题面结构；
    - ``SympyKernel`` 和符号表，供点定义解析使用；
    - ``RuntimeScope`` 树，保存 problem/question/subquestion/step 的 facts。

    RuntimeContext 自身不规划 method，也不执行数学 method；它只负责读写、解析、
    可见性和覆盖策略。
    """

    def __init__(
        self,
        problem: ProblemIR,
        kernel: SympyKernel,
        symbols: dict[str, sp.Symbol],
    ) -> None:
        self.problem = problem
        self.kernel = kernel
        self.symbols = symbols
        self.scopes: dict[str, RuntimeScope] = {
            "problem": RuntimeScope("problem", "problem")
        }

    @property
    def problem_scope(self) -> RuntimeScope:
        """整题根 scope，所有 question/subquestion/step 都可以向上读取它。"""
        return self.scopes["problem"]

    def add_scope(self, scope: RuntimeScope) -> None:
        """把一个 scope 挂到上下文树上，并维护父节点 children 列表。"""
        if scope.scope_id in self.scopes:
            raise ValueError(f"scope already exists: {scope.scope_id}")
        self.scopes[scope.scope_id] = scope
        if scope.parent_id is not None:
            self.scopes[scope.parent_id].children.append(scope.scope_id)

    def ensure_step_scope(self, step_id: str, parent_id: str) -> RuntimeScope:
        """确保某个 step scope 存在。

        Planner 会先生成 StepPlan，Validator/Executor 执行前需要有对应 step scope
        来承载临时输出。重复调用是允许的，但已有 step 的 parent 必须一致，避免
        不同问题步骤误用同一个 step id。
        """
        if step_id in self.scopes:
            scope = self.scopes[step_id]
            if scope.scope_type != "step" or scope.parent_id != parent_id:
                raise ValueError(f"step scope conflict: {step_id}")
            return scope
        scope = RuntimeScope(step_id, "step", parent_id)
        self.add_scope(scope)
        return scope

    def get_scope(self, scope_id: str) -> RuntimeScope:
        """按 id 获取 scope，失败时给出更明确的错误信息。"""
        try:
            return self.scopes[scope_id]
        except KeyError as exc:
            raise KeyError(f"scope not found: {scope_id}") from exc

    def is_visible(self, from_scope_id: str, target_scope_id: str) -> bool:
        """判断 ``from_scope`` 是否能读取 ``target_scope``。

        可见性只沿父链向上成立：step 能读 subquestion/question/problem；question
        不能读自己的 step；sibling subquestion 之间也不可见。
        """
        current: str | None = from_scope_id
        while current is not None:
            if current == target_scope_id:
                return True
            current = self.scopes[current].parent_id
        return False

    def is_ancestor(self, ancestor_id: str, scope_id: str) -> bool:
        """判断 ancestor 是否是 scope 的祖先或自身。

        写回 promote 时会用它确认目标 scope 是否在当前 step 的父链上。
        """
        current: str | None = scope_id
        while current is not None:
            if current == ancestor_id:
                return True
            current = self.scopes[current].parent_id
        return False

    def read_path(
        self,
        raw_path: str,
        *,
        from_scope_id: str = "problem",
        expected_type: str | None = None,
    ) -> TypedValue:
        """按 ContextPath 读取值，并可选做类型校验。

        当期望类型是 ``Point`` 时，读取到 ``PointRef`` 也可以继续解析：比如
        ``$problem.points.D`` 存的是“对称轴与 x 轴交点”定义，读取时会即时计算成
        坐标。其他类型必须严格匹配。
        """
        path = ContextPath.parse(raw_path)
        scope = self.get_scope(path.scope_id)
        if not self.is_visible(from_scope_id, path.scope_id):
            raise PermissionError(
                f"path {raw_path} is not visible from scope {from_scope_id}"
            )
        container = scope.container(path.container)
        if path.key not in container:
            raise KeyError(f"path not found: {raw_path}")
        value = container[path.key]
        if expected_type == "Point":
            return TypedValue(
                "Point",
                self.resolve_point_value(value, from_scope_id=from_scope_id),
                locked=value.locked,
                source=value.source,
            )
        if expected_type is not None and value.type != expected_type:
            raise TypeError(
                f"path {raw_path} expected {expected_type}, got {value.type}"
            )
        return value

    def write_path(
        self,
        raw_path: str,
        value: TypedValue,
        *,
        from_scope_id: str,
        allow_overwrite: bool = False,
        allow_ancestor_write: bool = False,
    ) -> None:
        """按 ContextPath 写入值。

        默认只能写当前 scope。只有 ``allow_ancestor_write=True`` 时，step 执行器才
        可以把临时结果 promote 到祖先 scope。题设锁定值 ``locked=True`` 永远不能
        被覆盖；未解出的 ``PointRef`` 可以被 method 产出的 ``Point`` 替换。
        """
        path = ContextPath.parse(raw_path)
        scope = self.get_scope(path.scope_id)
        same_scope = path.scope_id == from_scope_id
        ancestor_write = allow_ancestor_write and self.is_ancestor(path.scope_id, from_scope_id)
        if not same_scope and not ancestor_write:
            raise PermissionError(
                f"path {raw_path} is not writable from scope {from_scope_id}"
            )
        container = scope.container(path.container)
        existing = container.get(path.key)
        if existing is not None:
            if existing.locked:
                raise PermissionError(f"cannot overwrite locked path: {raw_path}")
            if existing.type == "PointRef" and value.type == "Point":
                pass
            elif not allow_overwrite:
                raise PermissionError(f"cannot overwrite existing path: {raw_path}")
        container[path.key] = value

    def can_write_path(
        self,
        raw_path: str,
        *,
        from_scope_id: str,
        allow_ancestor_write: bool = False,
    ) -> bool:
        """轻量写入预检，供 PlanValidator 在真正执行前发现非法输出路径。"""
        try:
            path = ContextPath.parse(raw_path)
            self.get_scope(path.scope_id)
            same_scope = path.scope_id == from_scope_id
            ancestor_write = allow_ancestor_write and self.is_ancestor(path.scope_id, from_scope_id)
            if not same_scope and not ancestor_write:
                return False
            existing = self.scopes[path.scope_id].container(path.container).get(path.key)
            return existing is None or not existing.locked
        except Exception:
            return False

    def apply_declaration(self, declaration: ContextDeclaration) -> None:
        """应用已经通过校验的 planner 声明。

        这里只负责把声明转成未锁定 ``PointRef`` 写入目标 scope。声明是否合法由
        DeclarationValidator 负责；这里仍做最基本的 path/scope 一致性检查，避免
        其他调用方绕过 validator 时写错位置。
        """
        path = ContextPath.parse(declaration.path)
        if path.scope_id != declaration.scope_id:
            raise ValueError(
                f"declaration scope mismatch: {declaration.path} vs {declaration.scope_id}"
            )
        point_ref = PointRef(
            name=declaration.name,
            path=declaration.path,
            definition=dict(declaration.definition),
            scope_id=declaration.scope_id,
        )
        self.write_path(
            declaration.path,
            TypedValue("PointRef", point_ref, locked=False, source="planner"),
            from_scope_id=declaration.scope_id,
            allow_overwrite=True,
        )

    def apply_declarations(self, declarations: Iterable[ContextDeclaration]) -> None:
        """按顺序应用一组 planner 声明。"""
        for declaration in declarations:
            self.apply_declaration(declaration)

    def find_visible_path(
        self,
        container_name: str,
        key: str,
        *,
        from_scope_id: str,
    ) -> str | None:
        """从当前 scope 沿父链查找某个容器里的 key，并返回第一个可见路径。

        Planner 用它把“点名 A/C/D”映射成具体 ContextPath。查找方向是当前 scope
        到 problem，因此局部定义会优先于整题共享定义。
        """
        current: str | None = from_scope_id
        while current is not None:
            scope = self.scopes[current]
            if key in scope.container(container_name):
                return _format_path(scope, container_name, key)
            current = scope.parent_id
        return None

    def resolve_point_value(
        self,
        value: TypedValue,
        *,
        from_scope_id: str,
    ) -> Point:
        """把 ``Point`` 或可推导的 ``PointRef`` 解析成 SymPy 坐标。

        首版只支持安全、局部、确定的点定义：显式坐标、对称轴交点、y 轴交点、
        顶点和中点。像“直角等腰派生点”这种真正需要 method 的定义会保持 unresolved，
        交给 planner/executor 处理。
        """
        if value.type == "Point":
            return value.value
        if value.type != "PointRef":
            raise TypeError(f"expected Point or PointRef, got {value.type}")
        point_ref: PointRef = value.value
        definition = point_ref.definition
        kind = definition.get("definition")
        if kind == "axis_x_intercept":
            return self._axis_x_intercept()
        if kind == "y_axis_intercept":
            return self._y_axis_intercept()
        if kind == "vertex":
            return self._vertex()
        if kind == "midpoint":
            p1, p2 = definition["of"]
            pt1 = self.resolve_named_point(str(p1), from_scope_id=from_scope_id)
            pt2 = self.resolve_named_point(str(p2), from_scope_id=from_scope_id)
            return (sp.simplify((pt1[0] + pt2[0]) / 2), sp.simplify((pt1[1] + pt2[1]) / 2))
        if kind == "square_opposite_point":
            vertex = self.resolve_named_point(str(definition["vertex"]), from_scope_id=from_scope_id)
            adj1_name, adj2_name = definition["adjacent"]
            adj1 = self.resolve_named_point(str(adj1_name), from_scope_id=from_scope_id)
            adj2 = self.resolve_named_point(str(adj2_name), from_scope_id=from_scope_id)
            return (
                sp.simplify(adj1[0] + adj2[0] - vertex[0]),
                sp.simplify(adj1[1] + adj2[1] - vertex[1]),
            )
        raise ValueError(f"point {point_ref.name} is unresolved: {kind}")

    def resolve_named_point(self, name: str, *, from_scope_id: str) -> Point:
        """按点名查找可见点并解析成坐标。"""
        path = self.find_visible_path("points", name, from_scope_id=from_scope_id)
        if path is None:
            raise KeyError(f"point not visible: {name}")
        return self.read_path(path, from_scope_id=from_scope_id, expected_type="Point").value

    def collect_answers(
        self,
        answer_paths: Mapping[str, Mapping[str, str]],
    ) -> dict[str, Any]:
        """按配置的 ContextPath 汇总 SolverResult.answers。

        Solver/Planner 决定哪些路径属于最终答案；RuntimeContext 只负责读取并转换成
        JSON 友好的字符串/列表格式。
        """
        answers: dict[str, Any] = {}
        for section, fields in answer_paths.items():
            section_answers: dict[str, Any] = {}
            for field, path in fields.items():
                parsed = ContextPath.parse(path)
                section_answers[field] = self.to_answer_value(
                    self.read_path(path, from_scope_id=parsed.scope_id).value
                )
            answers[section] = section_answers
        return answers

    def _quadratic_expr(self) -> sp.Expr:
        """读取题目中的二次函数表达式，并解析成 SymPy 表达式。"""
        expression = self.problem.data.get("function", {}).get(
            "expression", "a*x**2 + b*x + c"
        )
        return self.kernel.expr(expression, self.symbols)

    def _axis_x_intercept(self) -> Point:
        """解析“对称轴与 x 轴交点”。

        这里使用题设中的系数关系，例如 ``2a+b=0``，先得到对称轴横坐标，再返回
        ``(axis_x, 0)``。这是确定性点定义，所以可以在 ContextPath 读取阶段解析。
        """
        a = self.symbols["a"]
        b = self.symbols["b"]
        relation_text = self.problem.data.get("function", {}).get(
            "coefficient_relation",
            self.problem.data.get("coefficient_relation", ""),
        )
        if not relation_text:
            raise KeyError("axis_x_intercept requires coefficient_relation")
        relation = parse_equation(str(relation_text), self.symbols)
        return (axis_x_from_relation(self.kernel, relation, a, b), sp.Integer(0))

    def _y_axis_intercept(self) -> Point:
        """解析二次函数与 y 轴交点。"""
        x = self.symbols["x"]
        return y_axis_intercept(self._quadratic_expr(), x)

    def _vertex(self) -> Point:
        """解析当前二次函数表达式的顶点。"""
        x = self.symbols["x"]
        return vertex_of_quadratic(self._quadratic_expr(), x)

    def to_answer_value(self, value: Any) -> Any:
        """把 runtime 值转换成 SolverResult 可序列化答案。

        ResultBuilder 和旧的 ``collect_answers`` 都使用这个公开 helper，确保点、
        表达式、字典等结构在 CLI JSON 中保持同一种格式。
        """
        if isinstance(value, tuple) and len(value) == 2:
            return [self.kernel.sstr(value[0]), self.kernel.sstr(value[1])]
        if isinstance(value, dict):
            return {
                str(getattr(key, "name", key)): self.to_answer_value(child)
                for key, child in value.items()
            }
        if isinstance(value, sp.Expr):
            return self.kernel.sstr(value)
        return value

    def _json_value(self, value: Any) -> Any:
        """兼容旧测试/旧调用的私有别名。"""
        return self.to_answer_value(value)


class ContextBuilder:
    """从 ``ProblemIR`` 构建最小可用的多层 RuntimeContext。

    Builder 的职责是把 fixture 中的题意数据搬进 scope 树，而不是生成解法。它会：

    - 建立 question/subquestion 层级；
    - 放入 symbols、constraints、points、conditions；
    - 根据点出现位置和 relation scope 给点选择合适作用域。
    """

    def __init__(self, kernel: SympyKernel | None = None) -> None:
        self.kernel = kernel or SympyKernel()

    def build(self, problem: ProblemIR) -> RuntimeContext:
        """构建完整 RuntimeContext，供 Planner/Executor 使用。"""
        symbols = self.kernel.symbols(problem.symbols)
        context = RuntimeContext(problem, self.kernel, symbols)
        self._populate_problem_scope(context)
        self._build_question_scopes(context, problem.data.get("questions", []), "problem")
        self._populate_function(context)
        self._populate_question_coefficients(context)
        self._populate_points(context)
        self._populate_question_conditions(context)
        return context

    def _populate_problem_scope(self, context: RuntimeContext) -> None:
        """写入整题共享的符号和全局约束。"""
        root = context.problem_scope
        for name, symbol in context.symbols.items():
            root.container("symbols")[name] = TypedValue("Symbol", symbol, locked=True, source="symbols")
        coefficient_symbols = [
            context.symbols[name]
            for name in ("a", "b", "c")
            if name in context.symbols
        ]
        if coefficient_symbols:
            root.container("symbol_lists")["quadratic_coefficients"] = TypedValue(
                "SymbolList",
                coefficient_symbols,
                locked=True,
                source="symbols",
            )
        for name, raw in context.problem.constraints.items():
            value = _parse_constraint(raw, context.kernel, context.symbols)
            root.constraints[name] = TypedValue("Constraint", value, locked=True, source="constraints")
        self._populate_global_conditions(context)

    def _populate_global_conditions(self, context: RuntimeContext) -> None:
        """写入整题级路径条件和关系条件。

        这些不是某个小问独有的数值条件，而是题面中描述解题结构的条件，例如
        ``EG+FG``、``DE=sqrt(2)*NG``。Planner 会把它们显式传给相关 method。
        """
        root = context.problem_scope
        path_config = context.problem.data.get("path_problem")
        if isinstance(path_config, Mapping) and path_config.get("path"):
            # ``data.path_problem`` 是题面目标信息，只描述“要最小化哪条路径”。
            # 最短线段、辅助点、交点线等解法产物必须由 planner/runtime 生成，
            # 不能再从 fixture hints 注入。
            root.container("conditions")["path_minimum"] = TypedValue(
                "Condition",
                dict(path_config),
                locked=True,
                source="data.path_problem",
            )
        for relation in context.problem.data.get("relations", []):
            if not isinstance(relation, Mapping):
                continue
            key = _relation_condition_key(relation)
            if key:
                root.container("conditions")[key] = TypedValue(
                    "Condition",
                    dict(relation),
                    locked=True,
                    source="relations",
                )

    def _populate_function(self, context: RuntimeContext) -> None:
        """把二次函数表达式和系数关系写入 problem scope。"""
        function = context.problem.data.get("function", {})
        expression = function.get("expression", "a*x**2 + b*x + c")
        context.problem_scope.container("expressions")["quadratic"] = TypedValue(
            "Expression",
            context.kernel.expr(expression, context.symbols),
            locked=True,
            source="function.expression",
        )
        relation = function.get("coefficient_relation")
        if relation:
            context.problem_scope.container("equations")["coefficient_relation"] = TypedValue(
                "Equation",
                parse_equation(str(relation), context.symbols),
                locked=True,
                source="function.coefficient_relation",
            )

    def _populate_question_coefficients(self, context: RuntimeContext) -> None:
        """把每个 question 中的 known_coefficients 写入对应 scope。"""
        for scope in list(context.scopes.values()):
            raw_question = scope.container("questions").get(scope.scope_id)
            if raw_question is None:
                continue
            question = raw_question.value
            known = {
                context.symbols[name]: context.kernel.expr(value, context.symbols)
                for name, value in question.get("known_coefficients", {}).items()
            }
            if known:
                scope.container("coefficients")["known"] = TypedValue(
                    "Coefficients",
                    known,
                    locked=True,
                    source=f"question:{scope.scope_id}",
                )
            all_coefficients = context.problem_scope.container("symbol_lists").get("quadratic_coefficients")
            if all_coefficients is not None:
                # 每一问的“未定二次项系数”由题设已知系数确定。例如河西第（Ⅱ）问
                # 已知 a=2，则后续先代入 a，只把 b、c 作为自由系数保留下来。
                # 当前 deterministic planner 还没有直接读取这个字段；它是给后续
                # 通用 planner/参数映射阶段准备的上下文索引，避免 planner 反复从
                # known_coefficients 手工推断“这一问还剩哪些系数未定”。
                scope.container("symbol_lists")["unknown_quadratic_coefficients"] = TypedValue(
                    "SymbolList",
                    [symbol for symbol in all_coefficients.value if symbol not in known],
                    locked=True,
                    source=f"question:{scope.scope_id}",
                )

    def _build_question_scopes(
        self,
        context: RuntimeContext,
        questions: Iterable[Mapping[str, Any]],
        parent_id: str,
    ) -> None:
        """递归建立 question/subquestion scope 树。

        顶层 question 的父节点是 problem；嵌套在 question 下的节点视为 subquestion。
        """
        for question in questions:
            question_id = str(question["id"])
            scope_type = "question" if parent_id == "problem" else "subquestion"
            scope = RuntimeScope(question_id, scope_type, parent_id)
            scope.container("questions")[question_id] = TypedValue(
                "Question", dict(question), locked=True, source="question"
            )
            context.add_scope(scope)
            self._build_question_scopes(
                context, question.get("subquestions", []), question_id
            )

    def _populate_points(self, context: RuntimeContext) -> None:
        """把 fixture 中的点定义写入合适 scope。

        显式坐标点会直接写成 ``Point``；需要推导的点写成 ``PointRef``。如果点带
        象限信息，会额外写入 ``OrientationHint`` 约束，供旋转类 method 选择候选。
        """
        points = dict(context.problem.data.get("entities", {}).get("points", {}))
        for name, raw in points.items():
            if not isinstance(raw, Mapping):
                continue
            scope_id = self._choose_point_scope(context, name, raw)
            path = _format_path(context.get_scope(scope_id), "points", name)
            context.get_scope(scope_id).container("points")[name] = self._typed_point(
                context, name, raw, path, scope_id,
            )
            quadrant = raw.get("quadrant")
            if quadrant:
                context.get_scope(scope_id).constraints[f"{name}_quadrant"] = TypedValue(
                    "OrientationHint",
                    {"quadrant": str(quadrant)},
                    locked=True,
                    source=f"point:{name}",
                )

    def _populate_question_conditions(self, context: RuntimeContext) -> None:
        """把每个 question/subquestion 的 conditions 写入对应 scope。"""
        for scope in list(context.scopes.values()):
            raw_question = scope.container("questions").get(scope.scope_id)
            if raw_question is None:
                continue
            question = raw_question.value
            for condition in question.get("conditions", []):
                condition_type = str(condition.get("type", "condition"))
                scope.container("conditions")[condition_type] = TypedValue(
                    "Condition", dict(condition), locked=True, source=f"question:{scope.scope_id}",
                )

    def _choose_point_scope(
        self,
        context: RuntimeContext,
        name: str,
        raw: Mapping[str, Any],
    ) -> str:
        """决定点定义应该属于哪个 scope。

        规则尽量保守：

        - 对称轴交点这类整题定义放 problem；
        - 被多个关系 scope 使用的显式点放 problem；
        - 只在某个 relation scope 中出现的点放对应 question；
        - 无法判断时退回 problem，保证可见但不做解法假设。
        """
        definition = raw.get("definition")
        if definition == "axis_x_intercept":
            return "problem"
        if definition == "midpoint":
            dependency_scope = _definition_dependency_scope(
                context,
                raw,
                allow_problem_dependency=True,
            )
            if dependency_scope is not None:
                return dependency_scope
        if definition in {"square_opposite_point", "reflected_point"}:
            # 构造点不应该假设固定属于第（Ⅱ）问。先看题面 relation 是否已经给出
            # 作用域；若没有 relation，再尝试根据定义里依赖的点所在 scope 推断。
            relation_scopes = _relation_scopes_for_point(context, name)
            if len(relation_scopes) == 1:
                return next(iter(relation_scopes))
            dependency_scope = _definition_dependency_scope(context, raw)
            if dependency_scope is not None:
                return dependency_scope
            return "problem"
        relation_scopes = _relation_scopes_for_point(context, name)
        if "coordinate" in raw and (
            _point_name_used_in_many_top_questions(context, name)
            or len(relation_scopes) > 1
        ):
            return "problem"
        if len(relation_scopes) == 1:
            return next(iter(relation_scopes))
        matches = [
            scope.scope_id
            for scope in context.scopes.values()
            if scope.scope_type == "question" and _question_mentions(scope, name)
        ]
        if len(matches) == 1:
            return matches[0]
        return "problem"

    def _typed_point(
        self,
        context: RuntimeContext,
        name: str,
        raw: Mapping[str, Any],
        path: str,
        scope_id: str,
    ) -> TypedValue:
        """把原始点定义转换成 ``Point`` 或 ``PointRef``。"""
        coordinate = raw.get("coordinate")
        if isinstance(coordinate, list) and len(coordinate) == 2:
            return TypedValue(
                "Point",
                (
                    context.kernel.expr(coordinate[0], context.symbols),
                    context.kernel.expr(coordinate[1], context.symbols),
                ),
                locked=True,
                source=f"point:{name}",
            )
        return TypedValue(
            "PointRef",
            PointRef(
                name=name,
                path=path,
                # ``data.entities.points`` 现在也带 canonical Entity 元数据
                # （handle/entity_type/scope_id/source）。这些字段是 ProblemIR
                # 索引用的，不属于点的几何定义；写入 PointRef 前要过滤掉，
                # 否则 ContextInventory 会把元数据误暴露成 definition 依赖。
                definition=_point_definition_payload(raw),
                scope_id=scope_id,
            ),
            locked=False,
            source=f"point:{name}",
        )


def _format_path(scope: RuntimeScope, container: str, key: str) -> str:
    """根据 scope 类型生成规范 ContextPath 字符串。"""
    if scope.scope_type == "problem":
        return f"$problem.{container}.{key}"
    return f"${scope.scope_type}.{scope.scope_id}.{container}.{key}"


def _point_definition_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """返回真正参与几何推导的点定义字段。

    ``data.entities.points`` 既是当前 ContextBuilder 的兼容索引，也是
    ProblemIR canonical Entity 的一部分。canonical 元数据不应进入
    ``PointRef.definition``，因为后续 planner 只关心 ``definition/of/...``
    这类几何含义字段。
    """
    payload = {
        key: value
        for key, value in raw.items()
        if key not in {"handle", "entity_type", "scope_id"}
    }
    if str(payload.get("source", "")).startswith("ProblemIR."):
        payload.pop("source", None)
    return payload


def parse_equation(
    raw: str | Mapping[str, str],
    symbols: Mapping[str, sp.Symbol],
) -> sp.Equality:
    """将字符串或 ``{left, right}`` 字典解析为 SymPy Equality。"""
    if isinstance(raw, Mapping):
        return sp.Eq(
            sp.sympify(raw["left"], locals=dict(symbols)),
            sp.sympify(raw["right"], locals=dict(symbols)),
        )
    if "=" not in raw:
        raise ValueError(f"不是方程: {raw}")
    left, right = raw.split("=", 1)
    return sp.Eq(
        sp.sympify(left.strip(), locals=dict(symbols)),
        sp.sympify(right.strip(), locals=dict(symbols)),
    )


def _parse_constraint(
    raw: str,
    kernel: SympyKernel,
    symbols: Mapping[str, sp.Symbol],
) -> dict[str, sp.Expr | str]:
    """把 ``>0``、``>2`` 这类简单约束解析成结构化形式。"""
    if raw.startswith(">"):
        return {"operator": ">", "value": kernel.expr(raw[1:].strip(), dict(symbols))}
    return {"operator": str(raw), "value": str(raw)}


def _relation_condition_key(relation: Mapping[str, Any]) -> str:
    """为题面 relation 生成可预测的条件 key。"""
    relation_type = str(relation.get("type", ""))
    if relation_type == "segment_relation":
        left = str(relation.get("left", ""))
        right = _extract_segment_name(str(relation.get("right", "")))
        if left and right:
            return f"segment_relation_{left}_{right}"
    if relation_type == "segment_membership":
        point = str(relation.get("point", ""))
        if point:
            return f"segment_membership_{point}"
    return ""


def _extract_segment_name(raw: str) -> str:
    """从 ``sqrt(2)*NG`` 这类表达式中取出线段名 ``NG``。"""
    letters = "".join(char for char in raw if char.isalpha())
    if len(letters) >= 2:
        return letters[-2:]
    return letters


def _parameter_symbol(context: RuntimeContext) -> sp.Symbol | None:
    """寻找题目中的动态参数符号。

    优先读取 ``data.parameter``，其次使用 symbol_roles，最后退回到非 x/a/b/c 的
    第一个符号。这个 fallback 只服务 V1.5 样板，不代表完整抽取策略。
    """
    parameter = context.problem.data.get("parameter")
    if isinstance(parameter, str) and parameter in context.symbols:
        return context.symbols[parameter]
    for name, role in context.problem.data.get("symbol_roles", {}).items():
        if role == "dynamic_parameter" and name in context.symbols:
            return context.symbols[name]
    dynamic = [
        context.symbols[name]
        for name in context.problem.symbols
        if name not in {"x", "a", "b", "c"}
    ]
    return dynamic[0] if dynamic else None


def _parameter_lower_bound(context: RuntimeContext) -> sp.Expr | None:
    """读取动态参数的下界，用于带参点象限探测。"""
    symbol = _parameter_symbol(context)
    if symbol is None:
        return None
    raw = context.problem.constraints.get(symbol.name)
    if raw and raw.startswith(">"):
        return context.kernel.expr(raw[1:].strip(), context.symbols)
    return None


def _question_mentions(scope: RuntimeScope, name: str) -> bool:
    """粗略判断某个 question 文本结构是否提到点名。"""
    raw = scope.container("questions").get(scope.scope_id)
    if raw is None:
        return False
    # 单字母点名不能用简单 substring，否则会把 ``Parabola``、``ParameterValue`` 里
    # 的大写字母误判成点名。这里要求点名前后不是英文字符，中文标点、下划线、
    # ContextPath 分隔符仍可正常匹配。多字符点名会按 fixture 中的字面名称匹配：
    # ``D_prime`` 能匹配 ``D_prime``，但不会自动等同于 ``D'``；别名归一化留给
    # ProblemIR 生成阶段处理。
    pattern = re.compile(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])")
    return any(pattern.search(text) is not None for text in _question_strings(raw.value))


def _point_name_used_in_many_top_questions(context: RuntimeContext, name: str) -> bool:
    """判断显式点是否被多个顶层大问共同使用。"""
    count = 0
    for scope in context.scopes.values():
        if scope.scope_type == "question" and _question_mentions(scope, name):
            count += 1
    return count > 1


def _relation_scopes_for_point(context: RuntimeContext, name: str) -> set[str]:
    """从 relations 中收集某个点出现过的 question scope。"""
    scopes: set[str] = set()
    for relation in context.problem.data.get("relations", []):
        if name not in _relation_point_names(relation):
            continue
        raw_scope = str(relation.get("scope", ""))
        scopes.update(_relation_scope_to_question_ids(context, raw_scope))
    return {scope for scope in scopes if scope in context.scopes}


def _definition_dependency_scope(
    context: RuntimeContext,
    raw: Mapping[str, Any],
    *,
    allow_problem_dependency: bool = False,
) -> str | None:
    """从构造点定义依赖中推断 point scope。

    ``square_opposite_point``、``reflected_point`` 这类点经常是 planner 或 fixture
    声明的辅助点。它们的自然归属通常与依赖点一致，例如都依赖第（Ⅲ）问中的点，
    就应该放在第（Ⅲ）问 scope。若依赖横跨多个 scope，说明该辅助点不是某个局部
    问题的私有对象，调用方会回退到 problem scope。
    """
    dependency_names: set[str] = set()
    for field in ("vertex", "adjacent", "of", "source", "target", "line", "mirror_line"):
        dependency_names.update(_dependency_point_names(raw.get(field)))
    if not dependency_names:
        return None

    dependency_scopes: set[str] = set()
    for name in dependency_names:
        scope_id = _existing_point_scope(context, name)
        if scope_id is not None:
            dependency_scopes.add(scope_id)
            continue
        relation_scopes = _relation_scopes_for_point(context, name)
        if len(relation_scopes) == 1:
            dependency_scopes.add(next(iter(relation_scopes)))

    # 只有所有依赖都明确落在同一个非 step scope 时，才把构造点放到该 scope。
    # 依赖跨 scope 或无法判断时返回 None，让上层保守放 problem。
    if allow_problem_dependency and "problem" in dependency_scopes:
        local_scopes = dependency_scopes - {"problem"}
        if len(local_scopes) == 1:
            dependency_scopes = local_scopes
    if len(dependency_scopes) != 1:
        return None
    scope_id = next(iter(dependency_scopes))
    scope = context.get_scope(scope_id)
    if scope.scope_type == "step":
        return None
    return scope_id


def _existing_point_scope(context: RuntimeContext, name: str) -> str | None:
    """查找已经写入 RuntimeContext 的点所在 scope。"""
    for scope in context.scopes.values():
        if name in scope.container("points"):
            return scope.scope_id
    return None


def _dependency_point_names(value: Any) -> set[str]:
    """从点定义字段里提取依赖点名。

    relation 解析更偏向结构化字段；这里额外兼容 ``"MN"`` 这类线名写法，把它拆成
    ``M``、``N`` 两个单字母点名。首版 solver fixture 的点名均为单个大写字母。
    """
    if isinstance(value, str):
        if value.isalpha() and value.isupper() and len(value) > 1:
            return set(value)
        if value.isalpha() and value[:1].isupper():
            return {value}
        return set()
    if isinstance(value, Mapping):
        names: set[str] = set()
        for child in value.values():
            names.update(_dependency_point_names(child))
        return names
    if isinstance(value, list):
        names: set[str] = set()
        for child in value:
            names.update(_dependency_point_names(child))
        return names
    return set()


def _relation_point_names(value: Any) -> set[str]:
    """递归提取 relation 结构里的大写点名。

    这是 V1.5 的轻量解析器，用于 scope 归属判断；真正的数学语义仍由
    ContextInventory/Planner 处理。当前只从 ``ProblemIR.data.relations`` 的
    relation 值中调用，不会遇到 Python 类型名或内部类型名字符串。
    """
    if isinstance(value, str):
        if value.isalpha() and value[:1].isupper():
            return {value}
        # 路径/线段表达式常写成 ``sqrt(2)*MN+AN``。这里提取大写字母作为轻量点名
        # 索引，让动点 N 的 scope 来自题面 relation，而不是依赖 QuestionGoal。
        return set(re.findall(r"[A-Z]", value))
    if isinstance(value, Mapping):
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


def _relation_scope_to_question_ids(
    context: RuntimeContext,
    raw_scope: str,
) -> set[str]:
    """把 relation.scope 文本映射到 ``questions[].id``（即 RuntimeContext scope id）。

    ``scope`` 使用与 ``data.questions`` 相同的 id，多个作用域用 ``_and_`` 连接，
    例如 ``ii_and_iii`` 表示关系同时涉及第（Ⅱ）（Ⅲ）问。
    """
    if not raw_scope:
        return set()
    ids: set[str] = set()
    for piece in raw_scope.split("_and_"):
        piece = piece.strip()
        if piece in context.scopes:
            ids.add(piece)
    return ids


def _question_strings(value: Any) -> list[str]:
    """递归拉平 question 结构中的字符串，用于点名出现位置判断。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        strings: list[str] = []
        for child in value.values():
            strings.extend(_question_strings(child))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for child in value:
            strings.extend(_question_strings(child))
        return strings
    return []
