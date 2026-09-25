"""Teaching projection of an already verified multiplication by a bound unit."""

from copy import deepcopy
from dataclasses import replace

from .teaching_rules import RuleMaterial

OBSERVATION = "expression_rewrite.homogeneous_observation"
REWRITE = "expression_rewrite.homogenization"


def recognized(trace):
    from ..math_kernel.expression_rewrite import homogeneous_degree

    matches = [t for t in trace["transitions"] if t.get("homogenization")]
    if len(matches) != 1 or homogeneous_degree(trace["result"]["tree"]) != 0:
        return None
    transition = matches[0]
    if transition["before"] != trace["source"]:
        return None
    return transition


def compose_homogenization(container, materials, evidence):
    result = list(materials)
    for original in materials:
        if original.authority["unit_key"] != "organize_expressions/rewrite":
            continue
        matches = [
            v["data"]
            for v in evidence.values()
            if v.get("schema_version") == "expression-rewrite-teaching-evidence/v1"
            and v.get("step_id") == original.authority["source_step_id"]
        ]
        if len(matches) != 1 or not (transition := recognized(matches[0])):
            continue
        trace = matches[0]
        owner = original.authority["source_step_id"]
        # Merge only the observation whose actual input is this committed state.
        followers = [
            r
            for r in result
            if r.authority["unit_key"] == "amgm_observe"
            and any(
                v.get("resolved_from")
                == {
                    "kind": "step_result",
                    "step_id": owner,
                    "return": "organized_expression",
                }
                for v in (r.resolved_inputs or {}).get("expression", [])
            )
        ]
        if len(followers) > 1:
            continue
        h = transition["homogenization"]
        authority = deepcopy(original.authority)
        authority.update(
            unit_key="homogeneous_observation",
            visuals=[{"spec_id": OBSERVATION, "roles": {"evidence": owner}}],
        )
        observation = replace(
            original.material,
            suggested_title="观察结构：配齐次式",
            suggested_nav_title="观察结构",
            suggested_goal="比较目标与条件的次数，选择配齐次式",
            suggested_derive=(
                (
                    "∵",
                    f"目标 \\({trace['source']['latex']}\\) 的次数为 {h['originalDegree']}，条件左式 \\({h['factor']['latex']}\\) 的次数为 {h['conditionDegree']}",
                ),
                ("∴", "乘入等于 1 的条件，次数相加为 0，配成零次齐次式"),
            ),
            suggested_box=("配齐次式",),
        )
        # Added observation references M01; coverage remains with the rewrite.
        added = RuleMaterial(
            observation, authority, original.source, (), original.covers
        )
        rewritten_authority = deepcopy(original.authority)
        rewritten_authority["fixed_title"] = "配齐次式"
        rewritten_authority["visuals"] = [
            {"spec_id": REWRITE, "roles": {"evidence": owner}}
        ]
        rewritten = replace(
            original.material,
            suggested_title="配齐次式",
            suggested_nav_title="配齐次式",
            suggested_goal="乘入等于 1 的条件并展开",
        )
        covers = original.covers
        if followers:
            follower = followers[0]
            covers += follower.covers
            rewritten_authority["visuals"][0]["roles"]["evidence"] = [
                owner,
                follower.authority["source_step_id"],
            ]
            rewritten_authority["source_step_ids"] = [
                owner,
                follower.authority["source_step_id"],
            ]
            rewritten_authority["evidence_refs"] = list(
                dict.fromkeys(
                    rewritten_authority["evidence_refs"]
                    + follower.authority["evidence_refs"]
                )
            )
            rewritten = replace(
                rewritten,
                suggested_derive=rewritten.suggested_derive
                + follower.material.suggested_derive,
            )
            result.remove(follower)
        index = result.index(original)
        result[index : index + 1] = [
            added,
            RuleMaterial(rewritten, rewritten_authority, original.source, covers),
        ]
    return tuple(result)


def observation_visual(trace):
    t = recognized(trace)
    if t is None:
        raise ValueError("homogenization_evidence_missing")
    h = t["homogenization"]
    math = lambda s: r"\(" + s + r"\)"
    return {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "条件表达式",
            "expression": math(h["factor"]["latex"] + "=1"),
            "tag": f"{h['conditionDegree']} 次",
        },
        "target": {
            "label": "目标表达式",
            "expression": math(trace["source"]["latex"]),
            "tag": f"{h['originalDegree']} 次",
        },
        "organization": {
            "label": "次数相加，配成零次齐次式",
            "homogenizationHint": {
                "originalLabel": "原式",
                "original": math(trace["source"]["latex"]),
                "originalDegree": str(h["originalDegree"]),
                "conditionLabel": "乘入定值 1",
                "condition": math(h["factor"]["latex"] + "=1"),
                "conditionDegree": str(h["conditionDegree"]),
                "resultDegree": "0",
                "resultLabel": "零次齐次式",
                "result": math(trace["result"]["latex"]),
                "balance": f"({h['originalDegree']})+({h['conditionDegree']})=0",
            },
        },
        "reading": "次数配成 0",
        "route": "配齐次式",
    }


def rewrite_visual(trace):
    pair = None
    if isinstance(trace, list):
        trace, pair = trace
    if recognized(trace) is None:
        raise ValueError("homogenization_evidence_missing")
    math = lambda s: r"\(" + s + r"\)"
    visual = {
        "kind": "basic-inequality-structure-scan",
        "showFocus": False,
        "condition": observation_visual(trace)["condition"],
        "target": observation_visual(trace)["target"],
        "organization": {
            "label": "配齐次式：乘入条件并展开",
            "steps": [
                {
                    "expression": math(
                        trace["source"]["latex"] + "=" + t["after"]["latex"]
                    )
                }
                for t in trace["transitions"]
            ],
            "note": "乘入的条件表达式等于 1，目标值不变",
        },
        "reading": "零次齐次式",
        "route": "选择正项配对求下界",
    }

    if pair is not None and pair.get("constant_product_latex") is not None:
        a, b = pair["term_latex"]
        visual["pattern"] = {
            "first": {"value": math(a), "shape": "square"},
            "second": {"value": math(b), "shape": "circle"},
            "condition": {
                "operator": "·",
                "tag": "定积 " + math(pair["constant_product_latex"]),
            },
            "target": {"operator": "+", "tag": "求最小值"},
        }
        visual.update(reading="定积求和", route="应用基本不等式")
    return visual
