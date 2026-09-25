"""Method-owned teaching units projected from public inequality evidence."""

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

DIRECT_AMGM_ROUTE = "直接应用基本不等式"


def lesson_key_point(step, snapshot):
    """Keep the observation's method choice explicit in the page overview."""
    if "amgm_observe" not in step.teaching_unit_keys:
        return step.title + "：" + step.goal
    from .models import iter_teaching_sources

    source = next(
        source
        for source in iter_teaching_sources(snapshot.root_scope)
        if source.source_step_id in step.source_step_ids
        and source.capability_id == "apply_two_term_amgm"
    )
    _, evidence = evidence_for(source, snapshot)
    if evidence["data"].get("direction") == ">=" or evidence["data"].get("reciprocal"):
        return step.title + "：" + step.goal
    conditions = "，".join(evidence["data"]["conditions"])
    return (
        f"观察结构：由 {conditions} 看出这是正项定和求积的问题，{DIRECT_AMGM_ROUTE}。"
    )


def unit(key, title, visual, activation_role=None):
    return TeachingUnitSpec(
        activation_role=activation_role,
        unit_key=key,
        title_template=title,
        nav_title_template=title,
        goal_template="{reciprocal_goal}" if key == "reciprocal_transform" else "{goal}",
        derive_templates=(("∴", "{conclusion}"),),
        box_templates=(
            ("{observation}",) if key == "amgm_observe" else
            ("{reciprocal_conclusion}",) if key == "reciprocal_transform" else ("{conclusion}",)
        ),
        role_schema={
            "goal": "本步骤的教学目标。",
            "conclusion": "来自公开证据的数学结论。",
            **({
                "has_reciprocal_transform": "代码从已验证证据绑定的布尔值，控制本单元是否生成。",
                "reciprocal_goal": "正数取倒数的目标转换。",
                "reciprocal_conclusion": "倒数的已验证等价整理。",
            } if key == "reciprocal_transform" else {}),
        },
        role_binder_id="basic_inequality",
        requires_independent_lesson_step=True,
        visuals=({"spec_id": visual, "roles": {"evidence": "$source"}},),
    )


AMGM_UNITS = (
    unit("reciprocal_transform", "取倒数并整理目标", "basic_inequality.reciprocal", "has_reciprocal_transform"),
    unit("amgm_observe", "观察结构", "basic_inequality.structure"),
    unit("amgm_apply", "应用基本不等式", "basic_inequality.application"),
)
EQUALITY_UNITS = (unit("equality_verify", "验证取等", "basic_inequality.equality"),)


class InequalityTeachingProjector:
    def project(self, evidence, *, planning_context=None):
        from .evidence_projectors import ProjectedTeachingEvidence

        data = evidence.data
        return ProjectedTeachingEvidence(
            evidence.evidence_id,
            evidence.to_payload(),
            calculations=(
                {
                    "calculation_id": "inequality_derivation",
                    "kind": "verified_relation_chain",
                    "statements": data.get("witness_derivation", data["derivation"]),
                },
            ),
        )


def evidence_for(source, snapshot):
    matches = [
        (key, value)
        for key, value in snapshot.evidence.items()
        if value.get("schema_version") == "inequality-teaching-evidence/v1"
        and value.get("step_id") == source.source_step_id
    ]
    if len(matches) != 1:
        raise ValueError("inequality_public_teaching_evidence_missing_or_ambiguous")
    return matches[0]


def roles(source, snapshot):
    _, evidence = evidence_for(source, snapshot)
    d = evidence["data"]
    if d.get("direction") == ">=" or d.get("reciprocal"):
        return {**lower_bound_roles(source, d), "has_reciprocal_transform": bool(d.get("reciprocal"))}
    if not d.get("fixed_condition"):
        raise ValueError("fixed_sum_teaching_condition_missing")
    bound = f"{d['target']}≤{d['bound']}"
    observation = [
        "∵" + "，".join(d["conditions"]),
        "∴条件为定和，目标为同一组正项的积，可以应用基本不等式求上界",
    ]
    if source.capability_id == "apply_two_term_amgm":
        return {
            "has_reciprocal_transform": False,
            "observation": "定和求积",
            "goal": "利用正项定和求积的上界",
            "conclusion": bound,
            "derive_items_by_unit": {
                "amgm_observe": observation,
                "amgm_apply": ["∵" + "，".join(d["conditions"])]
                + ["∴" + v for v in d["derivation"]],
            },
        }
    if d.get("claim_scope") != "submitted_witness" or not d.get("witness"):
        raise ValueError("verified_witness_teaching_missing")
    assignments = "，".join(f"{name}={value}" for name, value in d["witness"].items())
    return {
        "goal": "验证上界能够取到",
        "conclusion": f"{d['target']}的最大值为{d['bound']}",
        "derive_items": ["∵取等条件为" + d["equality"], "当" + assignments + "时"]
        + ["∴" + v for v in d["witness_derivation"]]
        + [f"∴该取值满足原条件且达到上界，最大值为{d['bound']}"],
    }


def visual_refs(source, declarations):
    # Source-level reference is resolved against the snapshot at visual binding time.
    return [
        {
            "spec_id": item["spec_id"],
            "roles": {
                key: source.source_step_id if ref == "$source" else ref
                for key, ref in item["roles"].items()
            },
        }
        for item in declarations
    ]


def lower_bound_roles(source, d):
    def math(value):
        return r"\(" + value + r"\)"

    extremum = "最大值" if d["direction"] == "<=" else "最小值"
    terms = d.get("term_latex", d["terms"])
    pair = " 与 ".join(math(t) for t in terms)
    conditions = "，".join(math(c) for c in d.get("conditions_latex", d.get("conditions", [])))
    if source.capability_id == "apply_two_term_amgm":
        overall = math(d.get("overall_relation_latex", d["overall_relation"]))
        preview = "把 " + pair + " 配成两个正项，应用基本不等式求和的下界，保留其余项"
        if d.get("reciprocal"):
            preview = (
                "原式为正，对其倒数中的 "
                + pair
                + " 应用基本不等式，先求倒数的正下界，再求原式上界"
            )
        application = ["∵" + conditions] + [
            "∴" + math(v) for v in d.get("derivation_latex", d["derivation"])
        ]
        if d.get("constant_product_roles"):
            stages = d["constant_product_roles"]
            application = ["∵" + "，".join(math(term + ">0") for term in terms)]
            application += [
                r"∴\(" + v + r"\)"
                for v in (
                    d["template_latex"],
                    stages["product_identity"],
                    stages["local_bound"],
                    stages["target_substitution"],
                    None if d.get("reciprocal") else d.get("overall_relation_latex", d["overall_relation"]),
                )
                if v
            ]
        if d.get("reciprocal"):
            application += [
                "∴倒数至少为 "
                + math(d.get("reciprocal_lower_latex", d["reciprocal_lower_value"]) + ">0")
                + "，正数取倒数时不等号方向改变",
                "∴" + overall,
            ]
        result = {
            "goal": preview,
            "observation": "正项配对，求和的下界",
            "conclusion": overall,
            "derive_items_by_unit": {
                "amgm_observe": ["∵" + conditions, "∴" + preview],
                "amgm_apply": application,
            },
        }
        if d.get("reciprocal"):
            r = d["reciprocal_roles"]
            result["reciprocal_goal"] = "原式为正，将求最大值转为求倒数的最小值，并整理出可配对的正项"
            result["reciprocal_conclusion"] = r"\(" + r["rearrangement"] + r"\)"
            result["derive_items_by_unit"]["reciprocal_transform"] = [
                r"∵原式=\(" + r["reduced"] + r">0\)",
                "∴求原式的最大值等价于求其倒数的最小值",
                r"∴原式的倒数为\(" + r["inverse"] + r"\)",
                "∴" + result["reciprocal_conclusion"],
            ]
        return result
    if d.get("claim_scope") != "submitted_witness" or not d.get("verified_branches"):
        raise ValueError("verified_witness_teaching_missing")
    target = d.get("target_latex", d["target"])
    bound = d.get("bound_latex", d["bound"])
    # The answer box retains the runtime's canonical answer spelling for its
    # coverage check; derivation and diagram roles use structured LaTeX.
    conclusion = math(target) + "的" + extremum + "为" + math(d["bound"])
    derive = ["∵取等须同时满足 " + "，".join(math(e) for e in d.get("equalities_latex", d["equalities"]))]
    if d.get("equality_derivation"):
        derive += ["∵原条件为 " + conditions]
        derive += [r"∴\(" + row["math"] + r"\)" for row in d["equality_derivation"]]
        for branch in d["verified_branches"]:
            if branch.get("equality_derivation"):
                derive += [r"∵当 \(" + branch["when"] + r"\) 时"]
                derive += [
                    r"∴\(" + row["math"] + r"\)"
                    for row in branch["equality_derivation"]
                ]
        derive += ["∴代回原条件与目标，等号成立，" + math(target + "=" + bound)]
        return {
            "goal": "联立取等条件与原条件求出变量，再代回验证，确认" + extremum,
            "conclusion": conclusion,
            "derive_items": derive,
        }
    for branch in d["verified_branches"]:
        derive.append(
            "∵当 " + "，".join(math(f"{k}={v}") for k, v in branch["assignments"].items()) + " 时"
        )
        derive.append("∴满足原条件与全部取等条件，" + math(target + "=" + bound))
    derive.append("∴以上取值满足原条件且等号成立")
    return {
        "goal": "验证各次取等条件可以同时成立，确认等号能够成立",
        "conclusion": conclusion,
        "derive_items": derive,
    }
