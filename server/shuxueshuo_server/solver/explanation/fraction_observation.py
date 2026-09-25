"""Compose a verified condition-revealing rewrite with its direct AM-GM observation.

Classification consumes M01's public structural trace. It never selects a solver
route or proves new facts, and an unsupported composition leaves materials intact.
"""

from copy import deepcopy
from dataclasses import replace
from itertools import pairwise

from .teaching_rules import RuleMaterial

RULE_ID = "basic_inequality.fraction_observation"
VISUAL_ID = "expression_rewrite.fraction_observation"


def _nodes(tree):
    yield tree
    for child in tree.get("children", ()):
        yield from _nodes(child)


def _key(tree):
    """Syntax only: ignore display IDs and normalize additive/multiplicative order."""
    op = tree["op"]
    if op in {"symbol", "integer"}:
        return op, tree["text"]
    children = [_key(c) for c in tree["children"]]
    if op in {"add", "mul"}:
        flat = []
        for child in children:
            flat.extend(child[1:] if child[0] == op else [child])
        children = sorted(flat)
    return op, *children


def recognized(trace, pair):
    from sympy import Symbol

    from ..math_kernel.expression_parser import MathParseError, parse_math_expression
    from ..math_kernel.expression_rewrite import _legacy_tree

    if trace.get("teachingEffect") != "combine_fractions_revealing_condition":
        return None
    transitions = trace.get("transitions", [])
    combines = [t for t in transitions if t.get("operation") == "combine_fractions"]
    if len(combines) != 1 or not transitions:
        return None
    combine = combines[0]
    if (
        combine.get("effect") != "reveal_condition"
        or combine.get("evidence", {}).get("kind") != "structural_common_denominator"
        or not combine["evidence"].get("localEquivalenceVerified")
        or not combine["evidence"].get("wholeEquivalenceVerified")
        or transitions[0]["before"] != trace["source"]
        or transitions[-1]["after"] != trace["result"]
        or any(a["after"] != b["before"] for a, b in pairwise(transitions))
        or any(
            t["operation"]
            not in {"combine_fractions", "substitute_condition", "equivalent_rewrite"}
            for t in transitions
        )
    ):
        return None
    substitutions = [
        t
        for t in transitions[transitions.index(combine) + 1 :]
        if t["operation"] == "substitute_condition"
    ]
    revealed = set(combine.get("revealedConditionIds", []))
    used = revealed.intersection(
        c for t in substitutions for c in t["conditionCardIds"]
    )
    cards = [c for c in trace["conditionCards"] if c["id"] in used]
    highlights = [h for h in combine["highlights"] if h["role"] == "condition_block"]
    if not cards or not highlights:
        return None
    if (
        pair.get("direction") != ">="
        or pair.get("previous_bound")
        or len(pair.get("applications", [])) != 1
        or not pair.get("constant_product_roles")
        or len(pair.get("term_latex", [])) != 2
    ):
        return None
    symbols = {
        n["text"]: Symbol(n["text"])
        for n in _nodes(trace["source"]["tree"])
        if n["op"] == "symbol"
    }
    try:
        terms = [
            _legacy_tree(parse_math_expression(t, symbols).ast)
            for t in pair["applications"][0]["terms"]
        ]
    except (MathParseError, ValueError):
        return None
    if len(terms) != 2 or _key({"op": "add", "children": terms}) != _key(
        trace["result"]["tree"]
    ):
        return None
    return {"combine": combine, "conditions": cards, "highlights": highlights}


def direct_observer(materials, index):
    """Require an adjacent observation of the exact committed source and owner."""
    original = materials[index]
    owner = original.authority["source_step_id"]
    followers = []
    for i, row in enumerate(materials):
        if row.authority["unit_key"] != "amgm_observe":
            continue
        expressions = (row.resolved_inputs or {}).get("expression", [])
        if len(expressions) == 1 and expressions[0].get("resolved_from") == {
            "kind": "step_result",
            "step_id": owner,
            "return": "organized_expression",
        }:
            followers.append((i, row))
    if len(followers) != 1 or followers[0][0] != index + 1:
        return None
    row = followers[0][1]
    expressions = (original.resolved_inputs or {}).get("expression", [])
    targets = (row.resolved_inputs or {}).get("target", [])
    if len(expressions) != 1 or len(targets) != 1:
        return None
    if targets[0].get("value", {}).get("expression_owner") != expressions[0].get(
        "ref", {}
    ).get("ref"):
        return None
    return row


def compose_fraction_observation(container, materials, evidence):
    result = list(materials)
    for index, original in enumerate(materials):
        if original.authority["unit_key"] != "organize_expressions/rewrite":
            continue
        follower = direct_observer(materials, index)
        if follower is None:
            continue
        owners = [
            original.authority["source_step_id"],
            follower.authority["source_step_id"],
        ]
        traces = [
            v["data"]
            for v in evidence.values()
            if v.get("step_id") == owners[0]
            and v.get("schema_version") == "expression-rewrite-teaching-evidence/v1"
        ]
        pairs = [
            v["data"]
            for v in evidence.values()
            if v.get("step_id") == owners[1]
            and v.get("schema_version") == "inequality-teaching-evidence/v1"
        ]
        if len(traces) != 1 or len(pairs) != 1:
            continue
        trace, pair = traces[0], pairs[0]
        match = recognized(trace, pair)
        if match is None:
            continue
        authority = deepcopy(original.authority)
        authority.update(
            unit_key="fraction_observation",
            source_step_ids=owners,
            requires_independent_lesson_step=True,
            evidence_refs=list(
                dict.fromkeys(
                    original.authority["evidence_refs"]
                    + follower.authority["evidence_refs"]
                )
            ),
            visuals=[{"spec_id": VISUAL_ID, "roles": {"evidence": owners}}],
        )
        visual = observation_visual([trace, pair])
        material = replace(
            original.material,
            suggested_title="观察结构：通分显条件",
            suggested_nav_title="观察结构",
            suggested_goal="通分使条件量显形，代入条件后识别两个正项，转化为定积求和",
            suggested_derive=(
                ("∵", "已知 " + visual["condition"]["expression"]),
                (
                    "∴",
                    "通分后出现条件量 "
                    + "、".join(math(h["latex"]) for h in match["highlights"]),
                ),
                *(("计算", s["expression"]) for s in visual["organization"]["steps"]),
                (
                    "∴",
                    "两个正项的乘积为 "
                    + math(pair["constant_product_roles"]["product"])
                    + "，直接应用基本不等式",
                ),
            ),
            suggested_box=("定积求和：直接应用基本不等式",),
        )
        position = result.index(original)
        result[position : position + 2] = [
            RuleMaterial(
                material, authority, original.source, original.covers + follower.covers
            )
        ]
    return tuple(result)


def math(value):
    return r"\(" + value + r"\)"


def observation_visual(data):
    from ..math_kernel.expression_rewrite import tree_latex

    trace, pair = data
    match = recognized(trace, pair)
    if match is None:
        raise ValueError("fraction_observation_evidence_missing")
    combine = match["combine"]
    selected = set(combine["localBefore"]["nodeIds"])
    fractions = [n for n in _nodes(combine["before"]["tree"]) if n["id"] in selected]
    steps = []
    for t in trace["transitions"]:
        before, after = t["localBefore"]["latex"], t["localAfter"]["latex"]
        steps.append(
            {
                "label": {
                    "combine_fractions": "通分",
                    "substitute_condition": "代入条件",
                }.get(t["operation"], "等价整理"),
                "expression": math(
                    (before + "=" + after)
                    if before and after
                    else t["before"]["latex"] + "=" + t["after"]["latex"]
                ),
            }
        )
    steps.append({"label": "整理结果", "expression": math(trace["result"]["latex"])})
    first, second = pair["term_latex"]
    return {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "原条件",
            "expression": "，".join(math(c["latex"]) for c in trace["conditionCards"]),
            "tag": "利用已知条件",
        },
        "target": {
            "label": "目标表达式",
            "expression": math(trace["source"]["latex"]),
            "tag": "先整理，再观察",
        },
        "organization": {
            "label": "整理目标式：通分显条件",
            "combineHint": {
                "terms": [math(tree_latex(t)) for t in fractions],
                "action": "通分使条件量显形",
                "mark": "、".join(h["latex"] for h in match["highlights"]),
                "note": "再代入已知条件",
                "ariaLabel": "通分后代入已知条件",
            },
            "steps": steps,
            "note": "整理后识别两个正项，转化为定积求和",
        },
        "pattern": {
            "first": {"value": math(first), "shape": "square"},
            "second": {"value": math(second), "shape": "circle"},
            "condition": {
                "operator": "·",
                "tag": "定积 " + math(pair["constant_product_roles"]["product"]),
            },
            "target": {"operator": "+", "tag": "求最小值"},
        },
        "reading": "定积求和",
        "route": "直接应用基本不等式",
    }
