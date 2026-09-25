"""Declarative student-step visuals. No geometry inheritance or math solving."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from ..explanation.basic_inequality_teaching import DIRECT_AMGM_ROUTE, evidence_for
from ..explanation.models import iter_teaching_sources


class VisualGap(ValueError):
    pass


@dataclass(frozen=True)
class VisualSpec:
    spec_id: str
    component_id: str
    binder: Callable
    visual_kind: str = "teaching_diagram"
    version: int = 1
    evidence_kind: str = "inequality"


class VisualSpecRegistry:
    def __init__(self, specs=()):
        self.specs = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec):
        if spec.spec_id in self.specs or spec.visual_kind != "teaching_diagram":
            raise ValueError("duplicate or unsupported teaching diagram spec")
        self.specs[spec.spec_id] = spec

    def bind(self, declarations, *, snapshot, source_step_ids):
        sources = {
            s.source_step_id: s for s in iter_teaching_sources(snapshot.root_scope)
        }
        blocks = []
        for declaration in declarations:
            if set(declaration) != {"spec_id", "roles"}:
                raise VisualGap("visual_declaration_invalid")
            spec = self.specs.get(declaration["spec_id"])
            if spec is None:
                raise VisualGap("visual_spec_missing: " + declaration["spec_id"])
            roles = declaration["roles"]
            refs = roles.get("evidence")
            refs = refs if isinstance(refs, list) else [refs]
            if (
                set(roles) != {"evidence"}
                or not refs
                or any(r not in source_step_ids for r in refs)
            ):
                raise VisualGap("visual_role_outside_step_sources")
            try:
                entries = []
                for ref in refs:
                    source = sources[ref]
                    if spec.evidence_kind == "rewrite" or (
                        spec.evidence_kind == "rewrite_with_bound"
                        and source.capability_id == "organize_expressions"
                    ):
                        from ..explanation.expression_rewrite import (
                            rewrite_evidence_for,
                        )

                        entries.append(rewrite_evidence_for(source, snapshot))
                    else:
                        entries.append(evidence_for(source, snapshot))
                payload = spec.binder(
                    [e[1]["data"] for e in entries]
                    if isinstance(roles["evidence"], list)
                    else entries[0][1]["data"]
                )
            except (KeyError, ValueError, IndexError) as exc:
                raise VisualGap("visual_role_missing: " + str(exc)) from exc
            if payload.get("kind") != spec.component_id:
                raise VisualGap("visual_component_binding_mismatch")
            blocks.append(
                {
                    "spec_id": spec.spec_id,
                    "spec_version": spec.version,
                    "visual_kind": spec.visual_kind,
                    "component_id": spec.component_id,
                    "component_version": 1,
                    "source_step_ids": refs,
                    "evidence_refs": [e[0] for e in entries],
                    "data": payload,
                }
            )
        for block in blocks:
            validate_diagram_block(block)
        return tuple(blocks)


def math(value):
    return r"\(" + value + r"\)"


def structure(d):
    if d.get("direction") == ">=":
        return lower_structure(d)
    a, b = d["terms"]
    return {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "条件表达式",
            "expression": math(d["fixed_condition"]),
            "tag": "定和",
        },
        "target": {"label": "目标表达式", "expression": math(d["target"]), "tag": "积"},
        "pattern": {
            "first": {"value": a, "shape": "square"},
            "second": {"value": b, "shape": "circle"},
            "condition": {"operator": "+", "tag": "定和"},
            "target": {"operator": "·", "tag": "求最大值"},
        },
        "reading": "定和求积",
        "route": DIRECT_AMGM_ROUTE,
    }


def application(d):
    if d.get("direction") == ">=":
        return lower_application(d)
    a, b = d["terms"]
    roles = d["application_roles"]
    # Role selection and provenance belong to the verified evidence projection.
    # An omitted intermediate relation stays omitted; the visual never invents it.
    return {
        "kind": "basic-inequality-mapping",
        "template": r"\(u+v≥2√(uv)\)",
        "formulaStyle": "sum-geometric",
        "showPositiveStep": True,
        "mappings": [
            {
                "slot": "第一个正项",
                "shape": "square",
                "value": a,
                "condition": math(a + ">0"),
            },
            {
                "slot": "第二个正项",
                "shape": "circle",
                "value": b,
                "condition": math(b + ">0"),
            },
        ],
        "mapped": math(roles["amgm"]["math"]),
        "fixedCondition": math(d["fixed_condition"]),
        **(
            {"replaced": math(roles["fixed_sum_substitution"]["math"])}
            if "fixed_sum_substitution" in roles
            else {}
        ),
        **(
            {"substituted": math(roles["root_bound"]["math"])}
            if "root_bound" in roles
            else {}
        ),
        "conclusion": math(roles["bound"]["math"]),
        "relationOrigins": {role: item["origins"] for role, item in roles.items()},
        "stageLabel": "代入定和",
        "replacementText": "代入定和",
        "simplifyLabel": "化简",
    }


def equality(d):
    if d.get("direction") == ">=":
        return lower_equality(d)
    if d["claim_scope"] != "submitted_witness" or d["exhaustive"]:
        raise ValueError("witness_claim_invalid")
    a, b = d["terms"]
    witness = "，".join(f"{key}={value}" for key, value in d["witness"].items())
    return {
        "kind": "basic-inequality-equality-check",
        "first": {"value": a, "shape": "square"},
        "second": {"value": b, "shape": "circle"},
        "equality": math(d["equality"]),
        "condition": math(d["fixed_condition"]),
        "templateLabel": "基本不等式取等",
        "conditionLabel": "结合定和",
        "solvedLabel": "取一组满足条件的值",
        "solved": math(witness),
        "verificationLabel": "代回原条件与目标",
        "verification": "；".join(math(r) for r in d["witness_derivation"]),
        "conclusion": math(d["target"]) + "的最大值为" + math(d["bound"]),
    }


def default_visual_specs():
    from ..explanation.fraction_observation import VISUAL_ID as FRACTION_VISUAL_ID
    from ..explanation.fraction_observation import observation_visual as fraction_visual
    from ..explanation.homogenization import OBSERVATION, REWRITE, observation_visual
    from ..explanation.homogenization import rewrite_visual as homogeneous_visual

    return VisualSpecRegistry(
        (
            VisualSpec(
                FRACTION_VISUAL_ID,
                "basic-inequality-structure-scan",
                fraction_visual,
                evidence_kind="rewrite_with_bound",
            ),
            VisualSpec(
                "expression_rewrite.chain",
                "expression-rewrite",
                rewrite_visual,
                evidence_kind="rewrite",
            ),
            VisualSpec(
                OBSERVATION,
                "basic-inequality-structure-scan",
                observation_visual,
                evidence_kind="rewrite",
            ),
            VisualSpec(
                REWRITE,
                "basic-inequality-structure-scan",
                homogeneous_visual,
                evidence_kind="rewrite_with_bound",
            ),
            VisualSpec(
                "basic_inequality.amgm_sequence_overview",
                "basic-inequality-structure-scan",
                sequence_overview,
            ),
            VisualSpec(
                "basic_inequality.structure",
                "basic-inequality-structure-scan",
                structure,
            ),
            VisualSpec(
                "basic_inequality.application", "basic-inequality-mapping", application
            ),
            VisualSpec(
                "basic_inequality.equality", "basic-inequality-equality-check", equality
            ),
        )
    )


def bind_lesson_diagrams(visual_ir, lesson, snapshot, registry=None):
    registry = registry or default_visual_specs()
    by_id = {s.id: s for s in lesson.steps}
    gaps = []

    def steps(items):
        result = []
        for item in items:
            step = by_id[item.lesson_step_id]
            if step.visuals:
                try:
                    blocks = registry.bind(
                        step.visuals,
                        snapshot=snapshot,
                        source_step_ids=step.source_step_ids,
                    )
                    item = replace(item, diagram_blocks=blocks)
                except VisualGap as exc:
                    gaps.append(
                        {
                            "lesson_step_id": step.id,
                            "code": "VisualGap",
                            "message": str(exc),
                        }
                    )
            result.append(item)
        return tuple(result)

    def scope(node):
        return replace(
            node,
            steps=steps(node.steps),
            goals=tuple(replace(g, steps=steps(g.steps)) for g in node.goals),
            children=tuple(scope(c) for c in node.children),
        )

    root = scope(visual_ir.root_scope)
    metadata = dict(visual_ir.metadata)
    if gaps:
        metadata["visual_gaps"] = gaps
    return replace(visual_ir, root_scope=root, metadata=metadata)


def validate_diagram_block(block):
    """Validate persisted component identity and required data before rendering."""
    required = {
        "spec_id",
        "spec_version",
        "visual_kind",
        "component_id",
        "component_version",
        "source_step_ids",
        "evidence_refs",
        "data",
    }
    if (
        set(block) != required
        or block["visual_kind"] != "teaching_diagram"
        or block["spec_version"] != 1
        or block["component_version"] != 1
    ):
        raise VisualGap("visual_block_contract_invalid")
    for field in ("spec_id", "component_id"):
        if not isinstance(block[field], str) or not block[field]:
            raise VisualGap("visual_block_identity_missing")
    for field in ("source_step_ids", "evidence_refs"):
        if (
            not isinstance(block[field], list)
            or not block[field]
            or any(not isinstance(v, str) or not v for v in block[field])
        ):
            raise VisualGap("visual_block_source_missing")
    fields = {
        "expression-rewrite": ("source", "result", "transitions"),
        "basic-inequality-structure-scan": (
            "condition",
            "target",
            "reading",
            "route",
        ),
        "basic-inequality-mapping": ("mappings", "mapped", "conclusion"),
        "basic-inequality-equality-check": (
            "first",
            "second",
            "condition",
            "solved",
            "verification",
            "conclusion",
        ),
    }
    component = block["component_id"]
    data = block["data"]
    if (
        component not in fields
        or not isinstance(data, dict)
        or data.get("kind") != component
        or any(not data.get(f) for f in fields[component])
    ):
        raise VisualGap("visual_component_data_invalid")
    if component == "basic-inequality-structure-scan":
        cards = data.get("organization", {}).get("purposeCards")
        if cards is not None and (
            not isinstance(cards, list)
            or not cards
            or any(
                not isinstance(card, dict)
                or any(
                    not isinstance(card.get(key), str) or not card[key].strip()
                    for key in (
                        "label",
                        "purpose",
                        "tool",
                        "progress",
                        "before",
                        "after",
                        "detail",
                    )
                )
                for card in cards
            )
        ):
            raise VisualGap("visual_purpose_cards_invalid")
    if component == "basic-inequality-mapping" and any(
        field in data and (not isinstance(data[field], str) or not data[field].strip())
        for field in ("replaced", "substituted")
    ):
        raise VisualGap("visual_component_data_invalid")
    if component == "basic-inequality-mapping":
        extra = (
            ("relations", "equality")
            if data.get("formulaStyle") == "local-bound"
            else (
                ()
                if data.get("formulaStyle") == "sum-geometric"
                else ("fixedCondition",)
            )
        )
        if any(not data.get(field) for field in extra):
            raise VisualGap("visual_component_data_invalid")
    if component == "basic-inequality-equality-check" and "solutionBranches" in data:
        branches = data["solutionBranches"]
        if (
            not isinstance(branches, list)
            or not 2 <= len(branches) <= 8
            or not isinstance(data.get("solutionRelations"), list)
            or not data["solutionRelations"]
            or any(
                not isinstance(branch, dict)
                or not all(branch.get(k) for k in ("when", "relations", "result"))
                for branch in branches
            )
        ):
            raise VisualGap("visual_branch_solution_invalid")


def rewrite_visual(trace):
    from ..explanation.expression_rewrite import build_rewrite_presentation

    return build_rewrite_presentation(trace)["visual"]


def lower_structure(d):
    return {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "原条件",
            "expression": math("，".join(d["conditions"])),
            "tag": "已知条件",
        },
        "target": {
            "label": "当前求界表达式",
            "expression": math(d["source_expression"]),
            "tag": "求最小值",
        },
        "organization": {
            "label": "选出两个正项",
            "steps": [
                {"label": f"第{i + 1}项", "expression": math(term)}
                for i, term in enumerate(d["terms"])
            ],
            "note": "求两项和的下界，保留其余项",
        },
        "reading": "正项配对求和",
        "route": DIRECT_AMGM_ROUTE,
    }


def lower_application(d):
    relations = list(dict.fromkeys(item["math"] for item in d["local_relations"]))
    if not relations:
        raise ValueError("verified_local_amgm_relation_missing")
    visual = {
        "kind": "basic-inequality-mapping",
        "formulaStyle": "sum-geometric",
        "showPositiveStep": True,
        "stageLabel": "代入两个正项",
        "conclusionLabel": "得到下界",
        "template": math("u+v≥2√(u*v)"),
        "mapped": math(d["template_latex"]),
        "mappedSum": math("+".join(d["term_latex"])),
        "mappedProduct": math(
            r"\cdot ".join(r"\left(" + t + r"\right)" for t in d["term_latex"])
        ),
        "mappedParts": [math(part) for part in d["template_latex"].split(r"\geq ")],
        "mappings": [
            {
                "slot": f"第{i + 1}个正项",
                "shape": "square" if i == 0 else "circle",
                "value": math(term),
                "condition": math(term + ">0"),
            }
            for i, term in enumerate(d["term_latex"])
        ],
        "relations": [math(r) for r in dict.fromkeys(d["derivation"])],
        "conclusion": math(d["overall_relation"]),
        "equality": math(d["equality"]),
    }
    roles = d.get("constant_product_roles")
    if roles:
        visual.update(
            stageLabel="代入定积",
            fixedSourceTarget="product",
            fixedCondition=math(roles["product_identity"]),
            mappedProduct=math(roles["product"]),
            replaced=math(roles["local_bound"]),
            replacementText="应用基本不等式",
            relations=[],
        )
        if roles["target_substitution"]:
            visual.update(
                substituted=math(roles["target_substitution"]),
                simplifyLabel="代回整理式",
            )
    return visual


def lower_equality(d):
    if d["claim_scope"] != "submitted_witness" or d["exhaustive"]:
        raise ValueError("witness_claim_invalid")
    a, b = d["terms"]
    assignments = [
        "，".join(f"{k}={v}" for k, v in branch["assignments"].items())
        for branch in d["verified_branches"]
    ]
    visual = {
        "kind": "basic-inequality-equality-check",
        "first": {"value": a, "shape": "square"},
        "second": {"value": b, "shape": "circle"},
        "templateLabel": "同时满足各次取等条件",
        "equalityRelations": [math(r) for r in d["equalities"]],
        "conditionLabel": "原条件与取等条件",
        "condition": "；".join(math(r) for r in [*d["conditions"], *d["equalities"]]),
        "solvedLabel": "可取的具体值",
        "solved": " 或 ".join(math(v) for v in assignments),
        "verificationLabel": "各组取值均满足原条件，且等号成立",
        "verification": math(d["target"] + "=" + d["bound"]),
        "conclusion": math(d["target"]) + "的最小值为" + math(d["bound"]),
    }
    if d.get("equality_derivation"):
        visual.pop("equalityRelations")
        visual.update(
            first={"value": math(d["term_latex"][0]), "shape": "square"},
            second={"value": math(d["term_latex"][1]), "shape": "circle"},
            equality=math(d["equality"]),
            templateLabel="基本不等式取等",
            conditionLabel="结合原条件",
            condition="；".join(
                math(r) for r in (d["condition_equations_latex"] or d["conditions"])
            ),
            solvedLabel="联立求得",
            verificationLabel="代回目标",
        )
        if len(d["equalities"]) > 1:
            applications = d.get("equality_applications", [])
            if len(applications) != len(d["equalities"]) or any(
                not app["reduction"] for app in applications
            ):
                raise ValueError("verified_equality_reduction_missing")
            visual.update(
                templateLabel=f"{len(d['equalities'])}次基本不等式同时取等",
                equalities=[
                    {
                        "label": f"第{i + 1}次取等",
                        "first": {"value": math(app["terms"][0]), "shape": "square"},
                        "second": {"value": math(app["terms"][1]), "shape": "circle"},
                        "result": math(app["reduction"]),
                    }
                    for i, app in enumerate(applications)
                ],
                condition="；".join(math(r) for r in d["conditions"]),
            )
        if len(assignments) > 1:
            if any(
                not b.get("when") or not b.get("equality_derivation")
                for b in d["verified_branches"]
            ):
                raise ValueError("verified_branch_solution_missing")
            visual.update(
                solutionRelations=[
                    math(row["math"]) for row in d["equality_derivation"]
                ],
                solutionBranches=[
                    {
                        "when": math(b["when"]),
                        "relations": [
                            math(row["math"]) for row in b["equality_derivation"]
                        ],
                        "result": math(assignment),
                    }
                    for b, assignment in zip(
                        d["verified_branches"], assignments, strict=True
                    )
                ],
            )
    return visual


def sequence_overview(items):
    from ..explanation.bound_purpose import purpose_cards, relation_count_plan

    if len(items) < 2 or any(
        d["target_hash"] != items[0]["target_hash"] for d in items
    ):
        raise ValueError("amgm_sequence_owner_mismatch")
    for i, d in enumerate(items[1:], 1):
        if (
            not d.get("previous_bound")
            or d["previous_bound"]["bound"] != items[i - 1]["bound"]
        ):
            raise ValueError("amgm_sequence_dependency_missing")
    visual = {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "原条件",
            "expression": math("，".join(items[0]["conditions"])),
        },
        "target": {
            "label": "目标表达式",
            "expression": math(items[0]["target"]),
            "tag": "求最小值",
        },
        "organization": {
            "label": "路线预告：依次估计前一轮下界",
            "steps": [
                {
                    "label": f"第{i + 1}次配对",
                    "expression": " 与 ".join(math(t) for t in d["terms"]),
                }
                for i, d in enumerate(items)
            ],
            "note": "每轮记录取等条件，最后检查能否同时成立",
        },
        "reading": "连续求界",
        "route": f"本解法分{len(items)}次应用基本不等式",
    }
    cards = purpose_cards(items)
    if (
        cards
        and items[0]["teaching_effect"]["kind"] == "eliminate_variable"
        and items[-1]["teaching_effect"]["kind"] == "constant_bound"
    ):
        visual["organization"] = {
            "label": "变量多，先考虑减少变量",
            "purposeCards": cards,
            "note": "每轮保留取等条件，最后检查能否同时成立",
        }
        planning = relation_count_plan(items)
        if planning:
            visual["organization"].update(
                label="规划取等关系",
                relationCountHint=planning,
                note=f"考虑补充 {planning['result']['value']} 条取等关系；本解法分 {len(items)} 次应用不等式，最后联立检查取等",
            )
        visual.update(reading="先消元", route="再求解，最后检查取等")
        visual["target"]["tag"] = (
            f"含 {len(items[0]['teaching_effect']['input_symbols'])} 个变量"
        )
    return visual
