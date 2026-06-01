"""select_straightening_candidate 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class SelectStraighteningCandidateMethod:
    """从折线拉直候选中选择更适合后续计算的一种。

    首版选择策略非常朴素：比较反射点坐标的符号复杂度，唯一最简单的候选胜出。
    这对应人工解题中“选择 D 的对称点，因为它正好是正方形顶点，坐标更干净”的
    思路。后续可以把策略扩展成多指标 rank：坐标复杂度、是否已有构造、是否利于
    求交点、是否利于参数消元等。
    """

    method_id = "select_straightening_candidate"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        candidates = list(inputs["candidates"])
        target: PointRef = inputs["target"]
        if not candidates:
            raise ValueError("select_straightening_candidate requires at least one candidate")
        scores = [
            (candidate["complexity_score"], candidate["id"], candidate)
            for candidate in candidates
        ]
        scores.sort(key=lambda item: (item[0], item[1]))
        if len(scores) > 1 and scores[0][0] == scores[1][0]:
            raise ValueError("straightening candidate selection is ambiguous")
        selected = dict(scores[0][2])
        point: Point = selected["reflected_point"]
        score_text = "；".join(
            (
                f"{candidate['reflected_point_name']} 坐标复杂度"
                f"={candidate['complexity_score']}"
            )
            for _, _, candidate in scores
        )
        # LLM Planner 可能只声明“一个拉直辅助点”，例如 Aux，而不是提前知道它
        # 最终会是哪个点的对称点。此时只要 target 的定义说明它是折线拉直辅助点，
        # 就允许由候选选择结果来决定具体几何身份；固定命名的 deterministic planner
        # 仍然会走严格名称匹配。
        target_is_generic_auxiliary = (
            target.definition.get("definition") == "straightening_auxiliary_point"
            or target.name.lower() in {"aux", "auxiliary"}
        )
        target_matches = (
            selected["reflected_point_name"] == target.name
            or target_is_generic_auxiliary
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "selected_candidate": TypedValue(
                    "StraighteningCandidate",
                    selected,
                    source=self.method_id,
                ),
                "auxiliary_point": TypedValue(
                    "Point",
                    point,
                    source=self.method_id,
                ),
            },
            checks=[
                _check("straightening_candidate_unique_minimum_score", True, "存在唯一最低复杂度候选"),
                _check(
                    "selected_candidate_matches_target_name",
                    target_matches,
                    f"选择结果对应目标辅助点 {target.name}",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "选择折线拉直候选",
                    f"确定使用哪个对称点构造 {target.name}",
                    "比较候选反射点坐标复杂度，优先选择后续距离和交点计算更简单的候选。",
                    score_text,
                    (
                        f"选择 {selected['reflected_point_name']}"
                        f"({_fmt_point(point, kernel)})，最小路径转化为"
                        f" {selected['minimum_segment']}"
                    ),
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=SelectStraighteningCandidateMethod,
    title='折线拉直候选选择',
    solves=('select_broken_path_straightening_candidate',),
    inputs={
    "candidates": {
        "type": "StraighteningCandidateList",
        "required": True,
        "description": "broken_path_straightening_candidates 生成的候选列表。"
    },
    "target": {
        "type": "PointRef",
        "required": True,
        "description": "计划希望写回的辅助点引用，仅用于命名和验算选择结果。"
    }
},
    outputs={
    "selected_candidate": "StraighteningCandidate",
    "auxiliary_point": "Point"
},
    preconditions=('candidates 至少包含一个候选', '候选包含 complexity_score'),
    postconditions=('唯一最低复杂度候选被选中', '选中候选的反射点坐标作为辅助点输出'),
    trace_template=(),
)
