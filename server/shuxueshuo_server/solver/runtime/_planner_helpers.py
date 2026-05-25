"""planner 共享的小工具函数。

这些 helper 不承载题型语义，只负责把常见的 StepPlan 结构写成一致的代码。
这样南开、河西等 deterministic template 仍然各自描述解题顺序，但不会复制
MethodInvocation 的样板代码。
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.models import MethodInvocation, StepGoal, StepPlan


def single_invocation_step(
    *,
    step_id: str,
    parent_scope: str,
    method_id: str,
    inputs: dict[str, str],
    outputs: dict[str, str],
    promote: dict[str, str],
    goal_type: str,
    target_path: str,
) -> StepPlan:
    """创建只包含一个 MethodInvocation 的 StepPlan。

    deterministic planner 里大量步骤都是“一个中间目标对应一个 method 调用”。
    这个函数统一 StepGoal、invocation_id、expected_outputs 和 promote_outputs 的
    生成规则，避免不同 planner 复制后逐渐漂移。
    """
    goal = StepGoal(
        goal_id=f"{goal_type}:{step_id}",
        type=goal_type,
        target_path=target_path,
        scope_id=parent_scope,
        metadata={},
    )
    invocation = MethodInvocation(
        invocation_id=f"{step_id}.{method_id}",
        method_id=method_id,
        scope=step_id,
        inputs=inputs,
        outputs=outputs,
    )
    return StepPlan(
        step_id=step_id,
        goal=goal,
        scope=parent_scope,
        invocations=[invocation],
        expected_outputs=list(promote.values()),
        promote_outputs=promote,
    )
