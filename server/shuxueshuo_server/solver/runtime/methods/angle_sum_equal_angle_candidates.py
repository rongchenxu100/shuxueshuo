"""angle_sum_equal_angle_candidates 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource


class AngleSumEqualAngleCandidatesMethod:
    """由角和条件寻找唯一可用的等角关系。

    首版覆盖一种稳定中学套路：题设给出两个角之和为 45°，代码在坐标系中验证
    另一个由水平/竖直轴点构成的 45° 参考角，再消去公共角，推出
    “目标线角 = 参考角”。该 method 只产出等角事实，不计算坐标。
    """

    method_id = "angle_sum_equal_angle_candidates"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        condition = dict(inputs["condition"])
        x_axis_point: Point = inputs["x_axis_point"]
        y_axis_point: Point = inputs["y_axis_point"]
        reference_x_axis_point: Point = inputs["reference_x_axis_point"]
        origin: Point = inputs["origin"]
        target: PointRef = inputs["target"]

        angle_terms = [str(item) for item in condition.get("angle_terms", [])]
        if len(angle_terms) != 2 or not all(len(item) == 3 for item in angle_terms):
            raise ValueError("angle_sum condition must contain two 3-letter angle terms")
        if sp.simplify(kernel.expr(str(condition.get("value", "45"))) - 45) != 0:
            raise ValueError("current angle equality search expects a 45 degree angle sum")

        if sp.simplify(x_axis_point[1] - origin[1]) != 0:
            raise ValueError("x_axis_point must lie on the horizontal axis through origin")
        if sp.simplify(y_axis_point[0] - origin[0]) != 0:
            raise ValueError("y_axis_point must lie on the vertical axis through origin")
        if sp.simplify(reference_x_axis_point[1] - origin[1]) != 0:
            raise ValueError("reference_x_axis_point must lie on the horizontal axis through origin")

        ob = kernel.distance(origin, x_axis_point)
        co = kernel.distance(origin, y_axis_point)
        ao = kernel.distance(origin, reference_x_axis_point)
        if sp.simplify(ob) == 0:
            raise ValueError(
                "angle_role_degenerate: x_axis_point must differ from origin"
            )
        if sp.simplify(co) == 0:
            raise ValueError(
                "angle_role_degenerate: y_axis_point must differ from origin"
            )
        if sp.simplify(ao) == 0:
            raise ValueError(
                "angle_role_degenerate: reference_x_axis_point must differ "
                "from origin"
            )
        if _same_point(x_axis_point, reference_x_axis_point):
            raise ValueError(
                "angle_role_degenerate: x_axis_point and "
                "reference_x_axis_point must be distinct"
            )
        if sp.simplify(ob - co) != 0:
            raise ValueError("no unique 45 degree reference angle found from axis triangle")

        shared, reference = _shared_and_reference_angles(angle_terms)
        origin_name = reference[2]
        x_axis_name = shared[1]
        target_name = target.name
        equality = {
            "left_angle": f"{origin_name}{x_axis_name}{target_name}",
            "right_angle": reference,
            "left_angle_points": [
                origin_name,
                x_axis_name,
                target_name,
            ],
            "right_angle_points": list(reference),
            "shared_angle": shared,
            "reference_angle": f"{shared[0]}{shared[1]}{origin_name}",
            "reference_angle_value": str(condition.get("value") or "45"),
            "source": condition.get("description") or condition.get("source") or "angle_sum",
        }

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "angle_equality": TypedValue(
                    "AngleEquality",
                    equality,
                    source=self.method_id,
                )
            },
            checks=[
                _check(
                    "reference_angle_is_45",
                    sp.simplify(ob - co) == 0,
                    "由坐标轴直角三角形找到另一个 45° 角",
                ),
                _check(
                    "angle_sum_comparison_ready",
                    equality["shared_angle"] in angle_terms and equality["right_angle"] in angle_terms,
                    "角和条件与 45° 参考角可消去公共角",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由角和寻找等角",
                    f"推出 ∠{equality['left_angle']}=∠{equality['right_angle']}",
                    "先在坐标轴直角三角形中找到另一个 45° 角，再与题设角和比较，消去公共角。",
                    f"∠{equality['reference_angle']}=45°，且 ∠{shared}+∠{reference}=45°",
                    f"∠{equality['left_angle']}=∠{equality['right_angle']}",
                )
            ],
        )


def _shared_and_reference_angles(angle_terms: list[str]) -> tuple[str, str]:
    """从两个角项中选择共享角与参考角。

    当前约定第一个角是与 45° 参考角比较时会被消去的共享角，第二个角是
    需要转移到目标线角上的参考角。
    """
    first, second = angle_terms
    return first, second


def _same_point(first: Point, second: Point) -> bool:
    return all(
        sp.simplify(left - right) == 0
        for left, right in zip(first, second, strict=True)
    )


SPEC = MethodSpecSource(
    method_cls=AngleSumEqualAngleCandidatesMethod,
    title="由角和条件寻找等角",
    summary=(
        "当题面给出两个角之和为 45°，且 angle_terms 的结构能够确定一个"
        "非退化的坐标轴等腰直角参考三角形时，消去公共角并输出 AngleEquality。"
        "只需提供结构化角和条件；水平轴点、竖直轴点、参考点和原点由代码从"
        "角的顶点顺序确定。点坐标可以含未定参数，只要坐标轴关系与等腰关系"
        "能够被符号恒等验证；无需先求出参数。本能力只推出等角事实，不计算"
        "目标点坐标。"
    ),
    do_not_use_when=(
        "角和不是 45°，或两个角的点顺序不能构成所需的坐标轴参考三角形。",
        "坐标轴关系或等腰关系只在某个尚未求出的参数值下成立，而不是符号恒等时。",
        "不要手工交换水平轴点、竖直轴点、参考点和原点；这些机械角色由结构化 angle_terms 决定。",
        "目标是直接求坐标时不能跳过等角事实的后续消费能力。",
    ),
    solves=("derive_equal_angle_from_angle_sum",),
    inputs={
        "condition": {"type": "Condition", "required": True},
        "x_axis_point": {"type": "Point", "required": True},
        "y_axis_point": {"type": "Point", "required": True},
        "reference_x_axis_point": {"type": "Point", "required": True},
        "origin": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"angle_equality": "AngleEquality"},
    preconditions=(
        "condition 是两个角之和等于 45° 的角和事实",
        "x_axis_point 与 reference_x_axis_point 在以 origin 为原点的水平轴上",
        "y_axis_point 在以 origin 为原点的竖直轴上",
        "x_axis_point、y_axis_point、origin 形成另一个 45° 坐标轴角",
    ),
    postconditions=("输出唯一等角事实：目标线角等于参考角",),
    explanation=MethodExplanationSpec(
        role_schema={
            "angle_sum_condition": "题设给出的角和条件。",
            "reference_angle": "可验证出的 45° 参考角。",
            "angle_equality": "消去公共角后得到的等角关系。",
        },
        student_goal_template="利用角和条件和 45° 参考角，推出后续可用的等角关系。",
        student_title_template="由角和条件推出等角关系",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "angle_equality": "当前讲解中需要展示的等角关系。",
            "reference_angle": "该方法从坐标轴参考三角形中验证出的 45° 角。",
            "guide_arms": "为了让角边界可见而补充的淡色辅助角边。",
        },
        scene_templates=(
            {
                "component": "AngleEqualityMarker",
                "equality_role": "angle_equality",
                "reference_angle_role": "reference_angle",
                "style_intent": "angle_comparison",
            },
        ),
        role_binder_id="angle_sum_equal_angle_candidates",
    ),
    repair_hints=(
        {
            "code": "point_output_handle_not_found",
            "applies_to": ("method:angle_sum_equal_angle_candidates",),
            "message": "角和等角 step 缺少目标 PointRef；该目标点定义了等角关系要服务的点输出。",
            "next_actions": (
                "让 `angle_sum_equal_angle_candidates` 的 target 或 creates 指向目标点 PointRef，例如 `point:<scope>:<target_point>`。",
                "后续消费该 AngleEquality 的点输出 step 应 reads 该 AngleEquality fact，并使用同一个目标 PointRef。",
            ),
            "do_not": (
                "不要只 produces 一个泛化 AngleEquality fact 而不声明目标点。",
            ),
        },
    ),
)
