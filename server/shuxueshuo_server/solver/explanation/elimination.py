"""Teaching and visual roles for verified one-variable elimination."""

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

VISUAL_ID = "constraint_elimination.reduction"
UNIT = TeachingUnitSpec(
    unit_key="constraint_elimination",
    title_template="条件消元",
    nav_title_template="条件消元",
    goal_template="{goal}",
    derive_templates=(("∴", "{result}"),),
    box_templates=("{result}",),
    role_schema={"goal": "消元目的", "result": "代入后的目标"},
    role_binder_id="constraint_elimination",
    requires_independent_lesson_step=True,
    visuals=({"spec_id": VISUAL_ID, "roles": {"evidence": "$source"}},),
)


def evidence_for(source, snapshot):
    matches = [
        (k, v)
        for k, v in snapshot.evidence.items()
        if v.get("schema_version") == "elimination-teaching-evidence/v1"
        and v.get("step_id") == source.source_step_id
    ]
    if len(matches) != 1:
        raise ValueError("elimination teaching evidence missing or ambiguous")
    return matches[0]


def math(text):
    return r"\(" + text + r"\)"


def roles(source, snapshot):
    _, evidence = evidence_for(source, snapshot)
    d = evidence["data"]
    return {
        "goal": f"由原条件表示并消去 {d['eliminated_variable']}，把目标化为较少变量的表达式",
        "result": math(d["source"] + "=" + d["result"]),
        "derive_items": ["∵ " + "，".join(math(s) for s in d["conditions"])]
        + ["∴ " + math(s) for s in d["relations"]]
        + ["∴ " + math(d["source"] + "=" + d["result"])],
    }


class EliminationTeachingProjector:
    def project(self, evidence, *, planning_context=None):
        from .evidence_projectors import ProjectedTeachingEvidence

        return ProjectedTeachingEvidence(evidence.evidence_id, evidence.to_payload())


def visual(d):
    return {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "原条件",
            "expression": "，".join(math(s) for s in d["conditions"]),
        },
        "target": {"label": "目标表达式", "expression": math(d["source"])},
        "organization": {
            "label": "由条件消元，代入目标",
            "steps": [
                {
                    "label": "由条件表示待消去变量",
                    "expression": math(d["restoration"]),
                },
                *([{
                    "label": "代入后的条件",
                    "expression": "，".join(math(s) for s in d.get("display_remaining_conditions", d["remaining_conditions"])),
                }] if d.get("display_remaining_conditions", d["remaining_conditions"]) else []),
                {
                    "label": "代入目标",
                    "expression": math(d["source"] + "=" + d["result"]),
                },
            ],
        },
        "reading": "条件消元",
        "route": "减少变量，再应用不等式求界",
    }
