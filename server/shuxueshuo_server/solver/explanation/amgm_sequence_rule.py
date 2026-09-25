"""Compose observations only for a verified, ordered bound dependency chain."""

from copy import deepcopy
from dataclasses import replace

from .bound_purpose import purpose_cards, relation_count_plan
from .teaching_rules import RuleMaterial, TeachingRuleRegistry

RULE_ID = "basic_inequality.amgm_sequence_overview"
VISUAL_ID = "basic_inequality.amgm_sequence_overview"


def compose_sequence(container, materials, evidence):
    observations = [r for r in materials if r.authority["unit_key"] == "amgm_observe"]
    if len(observations) < 2:
        return materials
    data = []
    for row in observations:
        matches = [
            v["data"]
            for v in evidence.values()
            if v.get("schema_version") == "inequality-teaching-evidence/v1"
            and v.get("step_id") == row.authority["source_step_id"]
        ]
        if len(matches) != 1:
            return materials
        data.append(matches[0])
    for i, d in enumerate(data):
        if i:
            previous = (observations[i].resolved_inputs or {}).get("previous_bound", [])
            if len(previous) != 1 or previous[0].get("ref") != {
                "kind": "step_result",
                "step_id": observations[i - 1].authority["source_step_id"],
                "return": "bound",
            }:
                return materials
        if d.get("direction") != ">=" or d.get("target_hash") != data[0].get(
            "target_hash"
        ):
            return materials
        if i and (
            (d.get("previous_bound") or {}).get("bound") != data[i - 1]["bound"]
            or d["applications"][:-1] != data[i - 1]["applications"]
        ):
            return materials
    if len(data[0]["applications"]) != 1 or any(
        len(d["applications"]) != i + 1 for i, d in enumerate(data)
    ):
        return materials
    first = observations[0]
    count = len(data)
    preview = tuple(
        ("∴", f"第{i + 1}次：将 {' 与 '.join(d['terms'])} 配对")
        for i, d in enumerate(data)
    )
    material = replace(
        first.material,
        suggested_title="观察结构：连续估计路线",
        suggested_nav_title="观察结构",
        suggested_goal=f"本解法分{count}次应用基本不等式，依次估计前一轮得到的下界",
        suggested_derive=preview,
        suggested_box=(f"分{count}次估计，最后联合验证取等",),
    )
    authority = deepcopy(first.authority)
    sources = [r.authority["source_step_id"] for r in observations]
    authority.update(
        unit_key="amgm_sequence_overview",
        source_step_ids=sources,
        evidence_refs=list(
            dict.fromkeys(k for r in observations for k in r.authority["evidence_refs"])
        ),
        visuals=[{"spec_id": VISUAL_ID, "roles": {"evidence": sources}}],
    )
    combined = RuleMaterial(
        material,
        authority,
        first.source,
        tuple(k for r in observations for k in r.covers),
    )
    cards = purpose_cards(data)
    replacements = {}
    if (
        cards
        and data[0]["teaching_effect"]["kind"] == "eliminate_variable"
        and data[-1]["teaching_effect"]["kind"] == "constant_bound"
    ):
        purpose_title = "观察结构：先消元，再求解"
        planning = relation_count_plan(data)
        planning_goal = (
            f"按变量数 {planning['variable']['value']} 减去已有取等条件数 {planning['condition']['value']}，规划补充 {planning['result']['value']} 条取等关系；"
            if planning
            else ""
        )
        authority.update(fixed_title=purpose_title, fixed_nav_title="观察结构")
        combined = replace(
            combined,
            material=replace(
                material,
                suggested_title=purpose_title,
                suggested_goal=planning_goal
                + f"本解法分{count}次应用基本不等式，先消元再求解，最后联立检查取等",
                suggested_derive=tuple(
                    (
                        "∴",
                        c["purpose"]
                        + "："
                        + c["before"]
                        + " ≥ "
                        + c["after"]
                        + "；"
                        + c["detail"],
                    )
                    for c in cards
                ),
                suggested_box=("先消元 → 再求解 → 检查取等",),
            ),
        )
        for observation, d in zip(observations, data, strict=True):
            effect = d["teaching_effect"]
            for row in materials:
                if (
                    row.authority["source_step_id"]
                    != observation.authority["source_step_id"]
                    or row.authority["unit_key"] != "amgm_apply"
                ):
                    continue
                eliminate = effect["kind"] == "eliminate_variable"
                title = (
                    "应用基本不等式消元" if eliminate else "再次应用基本不等式取极值"
                )
                nav = title
                auth = deepcopy(row.authority)
                auth.update(fixed_title=title, fixed_nav_title=nav)
                goal = (
                    (
                        "通过配对消去 "
                        + "、".join(effect["removed_symbols"])
                        + "，使后续求界式只含 "
                        + "、".join(effect["output_symbols"])
                    )
                    if eliminate
                    else "对剩余正项应用基本不等式得到常数下界，取等在下一步验证"
                )
                replacements[id(row)] = replace(
                    row,
                    authority=auth,
                    material=replace(
                        row.material,
                        suggested_title=title,
                        suggested_nav_title=nav,
                        suggested_goal=goal,
                    ),
                )
    return tuple(
        combined if r is first else replacements.get(id(r), r)
        for r in materials
        if r is first or r not in observations
    )


def label_route(container, materials, evidence):
    """Declare presentation labels from composed routes, never from case IDs."""
    units = {r.authority["unit_key"] for r in materials}
    capabilities = {r.authority["capability_id"] for r in materials}
    if "amgm_sequence_overview" in units:
        label = "多次应用基本不等式"
    elif "homogeneous_observation" in units:
        label = "配齐次式"
    elif "fraction_observation" in units:
        label = "整理后应用基本不等式"
    elif (
        capabilities <= {"apply_two_term_amgm", "close_equality_and_restore"}
        and len(
            {
                r.authority["source_step_id"]
                for r in materials
                if r.authority["unit_key"] == "amgm_apply"
            }
        )
        == 1
    ):
        label = "直接应用基本不等式"
    else:
        return materials
    return tuple(
        replace(r, authority={**r.authority, "section_label": label}) for r in materials
    )


def sequence_rule_registry():
    from .fraction_observation import RULE_ID as FRACTION_RULE_ID
    from .fraction_observation import compose_fraction_observation
    from .homogenization import compose_homogenization

    registry = TeachingRuleRegistry()
    registry.register(
        "basic_inequality.homogenization",
        compose_homogenization,
        merge_unit_keys=("organize_expressions/rewrite", "amgm_observe"),
    )
    registry.register(RULE_ID, compose_sequence, merge_unit_keys=("amgm_observe",))
    registry.register(
        FRACTION_RULE_ID,
        compose_fraction_observation,
        merge_unit_keys=("organize_expressions/rewrite", "amgm_observe"),
    )
    registry.register("basic_inequality.route_label", label_route)
    return registry
