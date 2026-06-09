"""V1.5 计划校验与 invocation 执行。

Planner 产出的 StepPlan 不能被直接信任。即使未来由 LLM 生成 plan，也必须先经过
PlanValidator，确认：

- method_id 存在；
- 所有输入都是 ContextPath；
- 输入 path 在当前 step 可见，且类型满足 MethodSpec；
- 输出只能写入 invocation 所属 step 的 temp/outputs；
- promote 只能从 step 写到祖先 scope。

InvocationExecutor 则负责把通过校验的 ContextPath 解析成 typed inputs，调用无状态
method，再把 method output 写回 RuntimeContext。
"""

from __future__ import annotations

from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import (
    StatelessMethodRegistry,
    default_stateless_registry,
)
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    MethodInvocation,
    PlanExecutionResult,
    PointRef,
    StepExecutionResult,
    StepPlan,
    runtime_type_matches,
)


class DeclarationValidator:
    """校验 planner 声明是否可以安全写入 RuntimeContext。

    declaration 是 Planner 与 RuntimeContext 之间的新边界：Planner 可以声明“后续
    会求出某个点”，但不能借此写入题设答案、坐标或覆盖已锁定事实。
    """

    forbidden_definition_keys = {"coordinate", "coordinates", "value", "answer"}

    def validate_declarations(
        self,
        context: RuntimeContext,
        declarations: list[ContextDeclaration],
    ) -> None:
        """逐条校验一组 ContextDeclaration。"""
        for declaration in declarations:
            self.validate_declaration(context, declaration)

    def validate_declaration(
        self,
        context: RuntimeContext,
        declaration: ContextDeclaration,
    ) -> None:
        """校验单个 declaration。"""
        path = ContextPath.parse(declaration.path)
        if path.scope_id != declaration.scope_id:
            raise ValueError(
                f"declaration scope mismatch for {declaration.path}: {declaration.scope_id}"
            )
        if path.container != "points":
            raise PermissionError(
                f"declaration must write points container: {declaration.path}"
            )
        if path.key != declaration.name:
            raise ValueError(
                f"declaration name mismatch for {declaration.path}: {declaration.name}"
            )
        context.get_scope(path.scope_id)
        if declaration.type != "PointRef":
            raise TypeError(
                f"declaration {declaration.path} type must be PointRef, got {declaration.type}"
            )
        if declaration.source != "planner":
            raise PermissionError(
                f"declaration {declaration.path} source must be planner"
            )
        if self._contains_forbidden_value(declaration.definition):
            raise ValueError(
                f"declaration {declaration.path} must not include coordinates or answer values"
            )
        existing = context.get_scope(path.scope_id).container(path.container).get(path.key)
        if existing is None:
            return
        if existing.locked:
            raise PermissionError(f"declaration cannot overwrite locked path: {declaration.path}")
        if existing.type != "PointRef":
            raise PermissionError(
                f"declaration cannot overwrite existing non-PointRef path: {declaration.path}"
            )
        existing_ref: PointRef = existing.value
        if (
            existing_ref.name == declaration.name
            and existing_ref.scope_id == declaration.scope_id
            and dict(existing_ref.definition) == dict(declaration.definition)
        ):
            return
        raise PermissionError(
            f"declaration conflicts with existing PointRef: {declaration.path}"
        )

    def _contains_forbidden_value(self, value) -> bool:
        """检查 definition 中是否夹带坐标、答案或裸值。"""
        if isinstance(value, dict):
            if set(value) & self.forbidden_definition_keys:
                return True
            return any(self._contains_forbidden_value(child) for child in value.values())
        if isinstance(value, list | tuple):
            return any(self._contains_forbidden_value(child) for child in value)
        return False


class PlanValidator:
    """校验 StepPlan 是否可执行。

    Validator 是“LLM/规则 planner”和“真实执行器”之间的防火墙。它不做数学计算，
    只校验计划是否引用了合法上下文、是否越权写入、是否试图传裸值。
    """

    def __init__(self, specs: MethodSpecRegistry) -> None:
        self.specs = specs

    def validate_step(self, context: RuntimeContext, plan: StepPlan) -> None:
        """校验整个 StepPlan。

        这里会先确保 step scope 存在，然后逐个校验 invocation，最后校验
        ``promote_outputs`` 是否只把 step 结果提升到父链上的 scope。
        """
        context.get_scope(plan.scope)
        context.ensure_step_scope(plan.step_id, plan.scope)
        produced_paths = {
            path
            for invocation in plan.invocations
            for path in invocation.outputs.values()
        }
        produced_types: dict[str, str] = {}
        for invocation in plan.invocations:
            self.validate_invocation(context, invocation, produced_types=produced_types)
            spec = self.specs.require(invocation.method_id)
            for output_name, raw_path in invocation.outputs.items():
                produced_types[raw_path] = spec.outputs[output_name]
        for source, target in plan.promote_outputs.items():
            if not isinstance(source, str) or not source.startswith("$"):
                raise ValueError(f"promote source must be ContextPath: {source!r}")
            if not isinstance(target, str) or not target.startswith("$"):
                raise ValueError(f"promote target must be ContextPath: {target!r}")
            if source not in produced_paths:
                # 允许 promote 之前已经存在的 step 临时值，但必须能从 step 读到。
                context.read_path(source, from_scope_id=plan.step_id)
            target_path = ContextPath.parse(target)
            if not context.is_ancestor(target_path.scope_id, plan.step_id):
                raise PermissionError(f"promote target is not an ancestor scope: {target}")
            if not context.can_write_path(
                target,
                from_scope_id=plan.step_id,
                allow_ancestor_write=True,
            ):
                raise PermissionError(f"promote target is not writable: {target}")

    def validate_invocation(
        self,
        context: RuntimeContext,
        invocation: MethodInvocation,
        produced_types: dict[str, str] | None = None,
    ) -> None:
        """校验单个 MethodInvocation。

        输入按 MethodSpec 的槽位逐项检查；输出首版限制只能写到当前 step 的
        ``temp`` 或 ``outputs``，这样 method 的临时结果不会绕过 StepPlan 污染上层。
        """
        spec = self.specs.require(invocation.method_id)
        produced_types = produced_types or {}
        context.get_scope(invocation.scope)
        unknown_inputs = set(invocation.inputs) - set(spec.inputs)
        if unknown_inputs:
            raise ValueError(f"unknown invocation inputs: {sorted(unknown_inputs)}")
        for input_name, input_spec in spec.inputs.items():
            raw_path = invocation.inputs.get(input_name)
            if raw_path is None:
                if input_spec.required:
                    raise ValueError(f"missing required input: {input_name}")
                continue
            if not isinstance(raw_path, str) or not raw_path.startswith("$"):
                # 这条规则防止 Planner 把坐标答案直接塞进 invocation。
                raise ValueError(f"input {input_name} must be a ContextPath")
            if raw_path in produced_types:
                if not runtime_type_matches(input_spec.type, produced_types[raw_path]):
                    raise TypeError(
                        f"path {raw_path} expected {input_spec.type}, got {produced_types[raw_path]}"
                    )
                produced_path = ContextPath.parse(raw_path)
                if produced_path.scope_id != invocation.scope:
                    raise PermissionError(
                        f"produced input must come from same step scope: {raw_path}"
                    )
            else:
                context.read_path(
                    raw_path,
                    from_scope_id=invocation.scope,
                    expected_type=input_spec.type,
                )
        unknown_outputs = sorted(set(invocation.outputs) - set(spec.outputs))
        if unknown_outputs:
            raise ValueError(f"unknown invocation outputs: {unknown_outputs}")
        if not invocation.outputs:
            raise ValueError("invocation must declare at least one output")
        for output_name, raw_path in invocation.outputs.items():
            if not isinstance(raw_path, str) or not raw_path.startswith("$"):
                raise ValueError(f"output {output_name} must be a ContextPath")
            path = ContextPath.parse(raw_path)
            if path.scope_id != invocation.scope:
                raise PermissionError(
                    f"invocation output must write to its step scope: {raw_path}"
                )
            if path.container not in {"temp", "outputs"}:
                raise PermissionError(
                    f"invocation output must write temp/outputs: {raw_path}"
                )
            if not context.can_write_path(raw_path, from_scope_id=invocation.scope):
                raise PermissionError(f"output is not writable: {raw_path}")


class InvocationExecutor:
    """执行已通过校验的 StepPlan。

    Executor 是 V1.5 runtime 中唯一允许调用无状态 method 并写 RuntimeContext 的地方。
    它把“method 如何计算”和“结果写到哪里”分开：method 只返回 outputs，executor
    根据 MethodInvocation/StepPlan 决定写入 step temp 还是 promote 到上层。
    """

    def __init__(
        self,
        specs: MethodSpecRegistry,
        methods: StatelessMethodRegistry | None = None,
        kernel: SympyKernel | None = None,
    ) -> None:
        self.specs = specs
        self.methods = methods or default_stateless_registry()
        self.kernel = kernel or SympyKernel()
        self.validator = PlanValidator(specs)

    def execute_step(
        self,
        context: RuntimeContext,
        plan: StepPlan,
    ) -> StepExecutionResult:
        """执行一个 StepPlan，并聚合 checks/trace fragments。"""
        self.validator.validate_step(context, plan)
        step_result = StepExecutionResult(step_id=plan.step_id)
        for invocation in plan.invocations:
            result = self.execute_invocation(context, invocation)
            step_result.method_results.append(result)
            step_result.checks.extend(result.checks)
            step_result.trace_fragments.extend(result.trace_fragments)
        for source, target in plan.promote_outputs.items():
            # promote 是显式动作：只有 StepPlan 声明的路径才会从 step 泄露到上层。
            value = context.read_path(source, from_scope_id=plan.step_id)
            context.write_path(
                target,
                value,
                from_scope_id=plan.step_id,
                allow_ancestor_write=True,
            )
        return step_result

    def execute_plan(
        self,
        context: RuntimeContext,
        plans: list[StepPlan],
    ) -> PlanExecutionResult:
        """按顺序执行一组 StepPlan。"""
        result = PlanExecutionResult()
        for plan in plans:
            step_result = self.execute_step(context, plan)
            result.step_results.append(step_result)
            result.checks.extend(step_result.checks)
            result.trace_fragments.extend(step_result.trace_fragments)
        return result

    def execute_invocation(
        self,
        context: RuntimeContext,
        invocation: MethodInvocation,
    ):
        """解析 invocation 输入，运行 method，并写回 invocation 输出。"""
        spec = self.specs.require(invocation.method_id)
        method = self.methods.require(invocation.method_id)
        inputs = {}
        for input_name, input_spec in spec.inputs.items():
            raw_path = invocation.inputs.get(input_name)
            if raw_path is None:
                continue
            # read_path 会同时做 scope 可见性校验和 expected_type 校验。
            inputs[input_name] = context.read_path(
                raw_path,
                from_scope_id=invocation.scope,
                expected_type=input_spec.type,
            ).value
        result = method.run(inputs, self.kernel)
        for output_name, raw_path in invocation.outputs.items():
            # 输出先写入 step scope；如需成为上层 fact，必须走 promote_outputs。
            context.write_path(
                raw_path,
                result.outputs[output_name],
                from_scope_id=invocation.scope,
            )
        return result
