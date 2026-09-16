"""Human transcription of the retained source image; no runtime named-concept rule."""

import json
from pathlib import Path


def scope(
    label,
    text,
    points="",
    scalars=(),
    facts=(),
    goals=(),
    children=(),
    uncertainties=(),
):
    return {
        "label": label,
        "source_text": [text] if text else [],
        "entities": [{"kind": "point", "label": p} for p in points]
        + [{"kind": "scalar", "label": s} for s in scalars],
        "facts": list(facts),
        "goals": list(goals),
        "children": list(children),
        "uncertainties": list(uncertainties),
    }


def missing(n):
    return {"kind": "missing_figure", "text": f"原图未提供图{n}。"}


def gold():
    definition = "若四边形的一条对角线被另一条对角线平分，且另一条对角线被交点分成的两条线段长度之比为k（k≥1），则称该四边形为“k倍四边形”。"
    # Human gold retains a local X for AC/ED; this does NOT assert X != O.
    # Given collinearity can identify X with O; no automatic identity merger is applied here.
    q11 = scope(
        "图1",
        "如图1，在□ABCD中，对角线AC与BD交于点O，点E为OB中点。若四边形AECD为k倍四边形，则k的值为____。",
        "ABCDEOX",
        ["k"],
        [
            {"kind": "intersection", "point": "O", "segments": ["AC", "BD"]},
            {"kind": "midpoint", "point": "E", "segment": "OB"},
            {
                "kind": "scalar_constraint",
                "symbol": "k",
                "operator": ">=",
                "value": "1",
            },
            {"kind": "intersection", "point": "X", "segments": ["AC", "ED"]},
            {
                "kind": "any_of",
                "branches": [
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["EX", "XD"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XD", "EX"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "ED"},
                        {
                            "kind": "length_ratio",
                            "segments": ["AX", "XC"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "ED"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XC", "AX"],
                            "ratio": ["k", "1"],
                        },
                    ],
                ],
            },
        ],
        [{"kind": "find_value", "target": "k"}],
        uncertainties=[
            missing(1),
        ],
    )
    q12 = scope(
        "图2",
        "如图2，在k倍四边形ABCD中，若对角线AC被BD平分，则S△ACD/S△ACB=____（用含k的代数式表示）。",
        "ABCDX",
        ["k"],
        [
            {
                "kind": "scalar_constraint",
                "symbol": "k",
                "operator": ">=",
                "value": "1",
            },
            {"kind": "intersection", "point": "X", "segments": ["AC", "BD"]},
            {"kind": "midpoint", "point": "X", "segment": "AC"},
            {
                "kind": "any_of",
                "branches": [
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["BX", "XD"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XD", "BX"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "BD"},
                        {
                            "kind": "length_ratio",
                            "segments": ["AX", "XC"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "BD"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XC", "AX"],
                            "ratio": ["k", "1"],
                        },
                    ],
                ],
            },
        ],
        [
            {
                "kind": "find_area_ratio",
                "triangles": ["ACD", "ACB"],
                "in_terms_of": ["k"],
            }
        ],
        uncertainties=[missing(2)],
    )
    q2 = scope(
        "（2）",
        "如图3，四边形ABCD为k倍四边形，其对角线BD平分对角线AC，且满足∠BDC=2∠ABD，BD=4CD，求k的值。",
        "ABCDX",
        ["k"],
        [
            {
                "kind": "scalar_constraint",
                "symbol": "k",
                "operator": ">=",
                "value": "1",
            },
            {"kind": "intersection", "point": "X", "segments": ["AC", "BD"]},
            {"kind": "midpoint", "point": "X", "segment": "AC"},
            {
                "kind": "any_of",
                "branches": [
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["BX", "XD"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XD", "BX"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "BD"},
                        {
                            "kind": "length_ratio",
                            "segments": ["AX", "XC"],
                            "ratio": ["k", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "BD"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XC", "AX"],
                            "ratio": ["k", "1"],
                        },
                    ],
                ],
            },
            {"kind": "angle_ratio", "angles": ["BDC", "ABD"], "ratio": ["2", "1"]},
            {"kind": "length_ratio", "segments": ["BD", "CD"], "ratio": ["4", "1"]},
        ],
        [{"kind": "find_value", "target": "k"}],
        uncertainties=[missing(3)],
    )
    q3 = scope(
        "（3）",
        "如图4，已知定点A、B，且AB⊥BM，点C为射线BM上一动点，点D为平面内一点，连接A、B、C、D构成四边形ABCD。若BD平分AC，∠BAC=∠DAC，四边形ABCD为2倍四边形，求tan∠ACD的值。",
        "ABMCDX",
        (),
        [
            {"kind": "perpendicular", "segments": ["AB", "BM"]},
            {"kind": "point_on_ray", "point": "C", "ray": "BM"},
            {"kind": "intersection", "point": "X", "segments": ["AC", "BD"]},
            {"kind": "midpoint", "point": "X", "segment": "AC"},
            {
                "kind": "any_of",
                "branches": [
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["BX", "XD"],
                            "ratio": ["2", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "AC"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XD", "BX"],
                            "ratio": ["2", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "BD"},
                        {
                            "kind": "length_ratio",
                            "segments": ["AX", "XC"],
                            "ratio": ["2", "1"],
                        },
                    ],
                    [
                        {"kind": "midpoint", "point": "X", "segment": "BD"},
                        {
                            "kind": "length_ratio",
                            "segments": ["XC", "AX"],
                            "ratio": ["2", "1"],
                        },
                    ],
                ],
            },
            {"kind": "angle_equal", "angles": ["BAC", "DAC"]},
        ],
        [{"kind": "find_tan", "angle": "ACD"}],
        uncertainties=[missing(4)],
    )
    # User confirmed the source symbol means parallelogram for this case only.
    q11["facts"].append({"kind": "parallelogram", "polygon": "ABCD"})
    q11["facts"].extend(
        [
            {"kind": "polygon", "vertices": "ABCD"},
            {"kind": "polygon", "vertices": "AECD"},
        ]
    )
    for scene in (q12, q2, q3):
        scene["facts"].append({"kind": "polygon", "vertices": "ABCD"})
    for e in q3["entities"]:
        if e["label"] in ("A", "B"):
            e["role"] = "fixed"
        if e["label"] == "C":
            e["role"] = "moving"
    return {
        "schema_version": "problem-domain/v2",
        "family_id": None,
        "match_status": "unmatched",
        "match_reason": "当前注册的二次函数Solver不覆盖通用四边形分支、角度倍数、面积比及正切目标。",
        "root": scope(
            "整题",
            definition,
            children=[scope("（1）", "", children=[q11, q12]), q2, q3],
        ),
    }


if __name__ == "__main__":
    (Path(__file__).parent / "k-quad/gold.json").write_text(
        json.dumps(gold(), ensure_ascii=False, indent=2) + "\n"
    )
