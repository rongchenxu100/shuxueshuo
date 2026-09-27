"""Method-owned substitution observation and verified transformation."""

from shuxueshuo_server.solver.contracts import TeachingUnitSpec

OBSERVATION_ID = "expression_substitution.observation"
VISUAL_ID = "expression_substitution.reduction"


def unit(key, title, visual):
    return TeachingUnitSpec(
        unit_key=key,
        title_template=title,
        nav_title_template=title,
        goal_template="{goal}",
        derive_templates=(("∴", "{result}"),),
        box_templates=("{result}",),
        role_schema={
            "goal": "换元目的",
            "result": "已验证的换元关系",
        },
        role_binder_id="expression_substitution",
        requires_independent_lesson_step=True,
        visuals=({"spec_id": visual, "roles": {"evidence": "$source"}},),
    )


UNITS = (
    unit("substitution_observe", "观察原式结构", OBSERVATION_ID),
    unit("expression_substitution", "整体换元", VISUAL_ID),
)


def evidence_for(source, snapshot):
    matches = [
        (k, v)
        for k, v in snapshot.evidence.items()
        if v.get("schema_version") == "substitution-teaching-evidence/v1"
        and v.get("step_id") == source.source_step_id
    ]
    if len(matches) != 1:
        raise ValueError("substitution teaching evidence missing or ambiguous")
    return matches[0]


def math(text):
    return r"\(" + text + r"\)"


def roles(source, snapshot, unit):
    _, evidence = evidence_for(source, snapshot)
    d = evidence["data"]
    if unit.unit_key == "substitution_observe":
        return {
            "goal": "识别可以整体替换的表达式，用新变量简化条件与目标",
            "result": "，".join(math(s) for s in d["definitions"]),
            "derive_items": [
                "∵ " + "，".join(math(s) for s in d["conditions"]),
                "∴ 选择整体换元：" + "，".join(math(s) for s in d["definitions"]),
            ],
        }
    return {
        "goal": "条件与目标同步换元，并保留还原关系",
        "result": math(d["source"] + "=" + d["result"]),
        "derive_items": ["设 " + math(s) for s in d["definitions"]]
        + ["∴ " + math(s) for s in d["transformed_conditions"]]
        + ["∴ " + math(d["source"] + "=" + d["result"])],
    }


class SubstitutionTeachingProjector:
    def project(self, evidence, *, planning_context=None):
        from .evidence_projectors import ProjectedTeachingEvidence

        return ProjectedTeachingEvidence(evidence.evidence_id, evidence.to_payload())


def observation_visual(d):
    denominator_only = bool(d["mappings"]) and all(
        m["kind"] == "denominator" for m in d["mappings"]
    )
    caption = "把整个分母作为新变量" if denominator_only else "把整个表达式作为新变量"
    organization = {
        "label": "识别整体换元的表达式",
        "steps": [
            {
                "label": "选定新变量",
                "expression": "，".join(math(s) for s in d["definitions"]),
            }
        ],
    }
    if d["mappings"]:
        organization = {
            "substitutionHint": {
                "presentation": "mapping",
                "ariaLabel": caption,
                "mappings": [
                    {k: (v if k == "kind" else math(v)) for k, v in m.items()}
                    for m in d["mappings"]
                ],
            },
        }
    return {
        "kind": "basic-inequality-structure-scan",
        "showFocus": False,
        "showRoute": False,
        "caption": caption,
        "condition": {
            "label": "原条件",
            "expression": "，".join(math(s) for s in d["conditions"]),
        },
        "target": {"label": "原目标", "expression": math(d["source"])},
        "organization": organization,
        "reading": "识别整体结构",
        "route": "换元法",
    }


def visual(d):
    return {
        "kind": "basic-inequality-structure-scan",
        "showFocus": False,
        "showRoute": False,
        "ariaLabel": "条件与目标同步换元",
        "condition": {
            "label": "原条件",
            "expression": "，".join(math(s) for s in d["conditions"]),
        },
        "target": {"label": "原目标", "expression": math(d["source"])},
        "organization": {
            "comparisons": [
                {
                    "label": "条件",
                    "before": "，".join(
                        math(s)
                        for s in (d.get("condition_equations") or d["conditions"])
                    ),
                    "after": "，".join(
                        math(s)
                        for s in (
                            d.get("transformed_equations")
                            or d["transformed_conditions"]
                        )
                    ),
                },
                {
                    "label": "目标",
                    "before": math(d["source"]),
                    "after": math(d["result"]),
                },
            ],
        },
        "caption": "条件与目标同步换元",
        "reading": "整体换元",
        "route": "观察换元后的结构",
    }
