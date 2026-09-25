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
    if evidence["data"].get("direction") == ">=":
        return step.title + "：" + step.goal
    conditions = "，".join(evidence["data"]["conditions"])
    return (
        f"观察结构：由 {conditions} 看出这是正项定和求积的问题，{DIRECT_AMGM_ROUTE}。"
    )


def unit(key, title, visual):
    return TeachingUnitSpec(
        unit_key=key,
        title_template=title,
        nav_title_template=title,
        goal_template="{goal}",
        derive_templates=(("∴", "{conclusion}"),),
        box_templates=(
            ("{observation}",) if key == "amgm_observe" else ("{conclusion}",)
        ),
        role_schema={
            "goal": "本步骤的教学目标。",
            "conclusion": "来自公开证据的数学结论。",
        },
        role_binder_id="basic_inequality",
        requires_independent_lesson_step=True,
        visuals=({"spec_id": visual, "roles": {"evidence": "$source"}},),
    )


AMGM_UNITS = (
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
    if d.get("direction") == ">=":
        return lower_bound_roles(source, d)
    if not d.get("fixed_condition"):
        raise ValueError("fixed_sum_teaching_condition_missing")
    bound = f"{d['target']}≤{d['bound']}"
    observation = [
        "∵" + "，".join(d["conditions"]),
        "∴条件为定和，目标为同一组正项的积，可以应用基本不等式求上界",
    ]
    if source.capability_id == "apply_two_term_amgm":
        return {
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
    pair = " 与 ".join(d["terms"])
    if source.capability_id == "apply_two_term_amgm":
        preview = "把 " + pair + " 配成两个正项，应用基本不等式求和的下界，保留其余项"
        application = ["∵" + "，".join(d["conditions"])] + [
            "∴" + v for v in d["derivation"]
        ]
        if d.get("constant_product_roles"):
            stages = d["constant_product_roles"]
            application = ["∵" + "，".join(term + ">0" for term in d["terms"])]
            application += [
                r"∴\(" + v + r"\)"
                for v in (
                    d["template_latex"],
                    stages["product_identity"],
                    stages["local_bound"],
                    stages["target_substitution"],
                    d["overall_relation"],
                )
                if v
            ]
        return {
            "goal": preview,
            "observation": "正项配对，求和的下界",
            "conclusion": d["overall_relation"],
            "derive_items_by_unit": {
                "amgm_observe": ["∵" + "，".join(d["conditions"]), "∴" + preview],
                "amgm_apply": application,
            },
        }
    if d.get("claim_scope") != "submitted_witness" or not d.get("verified_branches"):
        raise ValueError("verified_witness_teaching_missing")
    derive = ["∵取等须同时满足 " + "，".join(d["equalities"])]
    if d.get("equality_derivation"):
        derive += ["∵原条件为 " + "，".join(d["conditions"])]
        derive += [r"∴\(" + row["math"] + r"\)" for row in d["equality_derivation"]]
        for branch in d["verified_branches"]:
            if branch.get("equality_derivation"):
                derive += [r"∵当 \(" + branch["when"] + r"\) 时"]
                derive += [
                    r"∴\(" + row["math"] + r"\)"
                    for row in branch["equality_derivation"]
                ]
        derive += ["∴代回原条件与目标，等号成立，" + d["target"] + "=" + d["bound"]]
        return {
            "goal": "联立取等条件与原条件求出变量，再代回验证，确认最小值",
            "conclusion": f"{d['target']}的最小值为{d['bound']}",
            "derive_items": derive,
        }
    for branch in d["verified_branches"]:
        derive.append(
            "设取 " + "，".join(f"{k}={v}" for k, v in branch["assignments"].items())
        )
        derive += ["∴" + r for r in branch["relations"]]
    derive.append("∴以上取值满足原条件且等号成立")
    return {
        "goal": "验证各次取等条件可以同时成立，确认等号能够成立",
        "conclusion": f"{d['target']}的最小值为{d['bound']}",
        "derive_items": derive,
    }
