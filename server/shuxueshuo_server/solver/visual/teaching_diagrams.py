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
                    if spec.evidence_kind == "substitution":
                        from ..explanation.substitution import (
                            evidence_for as substitution_evidence,
                        )
                        entries.append(substitution_evidence(source, snapshot))
                        continue
                    elif spec.evidence_kind == "elimination":
                        from ..explanation.elimination import (
                            evidence_for as elimination_evidence,
                        )

                        entries.append(elimination_evidence(source, snapshot))
                        continue
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
    if d.get("direction") == ">=" or d.get("reciprocal"):
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
    if d.get("direction") == ">=" or d.get("reciprocal"):
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
    if d.get("direction") == ">=" or d.get("reciprocal"):
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
    from ..explanation.elimination import VISUAL_ID as ELIMINATION_VISUAL
    from ..explanation.elimination import visual as elimination_visual
    from ..explanation.fraction_observation import VISUAL_ID as FRACTION_VISUAL_ID
    from ..explanation.fraction_observation import observation_visual as fraction_visual
    from ..explanation.homogenization import OBSERVATION, REWRITE, observation_visual
    from ..explanation.homogenization import rewrite_visual as homogeneous_visual
    from ..explanation.substitution import OBSERVATION_ID
    from ..explanation.substitution import VISUAL_ID as SUBSTITUTION_VISUAL
    from ..explanation.substitution import (
        observation_visual as substitution_observation,
    )
    from ..explanation.substitution import visual as substitution_visual

    return VisualSpecRegistry(
        (
            VisualSpec("basic_inequality.local_reciprocal_transform", "basic-inequality-structure-scan", reciprocal_local_transform),
            VisualSpec("basic_inequality.local_reciprocal", "basic-inequality-mapping", reciprocal_local),
            VisualSpec("basic_inequality.quadratic", "basic-inequality-structure-scan", quadratic),
            VisualSpec(OBSERVATION_ID, "basic-inequality-structure-scan", substitution_observation, evidence_kind="substitution"),
            VisualSpec(SUBSTITUTION_VISUAL, "basic-inequality-structure-scan", substitution_visual, evidence_kind="substitution"),
            VisualSpec(
                ELIMINATION_VISUAL,
                "basic-inequality-structure-scan",
                elimination_visual,
                evidence_kind="elimination",
            ),
            VisualSpec(
                FRACTION_VISUAL_ID,
                "basic-inequality-structure-scan",
                fraction_visual,
                evidence_kind="rewrite_with_bound",
            ),
            VisualSpec("expression_rewrite.fraction_merge", "basic-inequality-structure-scan", fraction_merge_visual, evidence_kind="rewrite"),
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
                "basic_inequality.reciprocal", "basic-inequality-structure-scan", reciprocal_transform
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
    if "presentation" in data:
        presentations = {
            "basic-inequality-mapping": "concept",
            "basic-inequality-equality-check": "concept",
            "expression-rewrite": "compact",
        }
        if data["presentation"] != presentations.get(component):
            raise VisualGap("visual_concept_presentation_invalid")
        if component == "basic-inequality-equality-check" and any(
            not isinstance(data.get(key), list) or not data[key]
            or any(not isinstance(row, str) or not row.strip() for row in data[key])
            for key in ("conceptEqualities", "conceptConditions")
        ):
            raise VisualGap("visual_concept_conditions_invalid")
    if "productNote" in data and (not isinstance(data["productNote"], str) or not data["productNote"].strip()):
        raise VisualGap("visual_concept_product_invalid")
    if component == "basic-inequality-equality-check" and "solutionMode" in data and (
        data["solutionMode"] != "witness" or any(
            key in data for key in ("solutionBranches", "solutionRelations", "equalities", "equalityRelations")
        )
    ):
        raise VisualGap("visual_equality_solution_mode_invalid")
    flow = data.get("expressionFlow", data.get("organization", {}).get("expressionFlow"))
    if flow is not None and (
        not isinstance(flow, list) or not flow
        or any(
            not isinstance(row, dict)
            or not isinstance(row.get("label"), str)
            or row.get("relation", "") not in ("", "=", "≥", "≤", "⇐", "→")
            or not isinstance(row.get("parts"), list) or not row["parts"]
            or any(not isinstance(part, dict)
                or not isinstance(part.get("expression"), str) or not part["expression"].strip()
                or ("highlight" in part and not isinstance(part["highlight"], bool))
                for part in row["parts"])
            for row in flow
        )
    ):
        raise VisualGap("visual_expression_flow_invalid")
    for key in ("sumNote", "localConclusion"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            raise VisualGap("visual_concept_note_invalid")
    items = data.get("conceptEqualityItems")
    if items is not None and (
        not isinstance(items, list) or len(items) != len(data.get("conceptEqualities", []))
        or any(not isinstance(item, dict) or item.get("kind") not in ("amgm", "quadratic")
            or any(not isinstance(item.get(key), str) or not item[key].strip()
                for key in (("first", "second") if item.get("kind") == "amgm" else ("expression",)))
            for item in items)
    ):
        raise VisualGap("visual_concept_equality_items_invalid")
    if component == "basic-inequality-structure-scan":
        if "showRoute" in data and not isinstance(data["showRoute"], bool):
            raise VisualGap("visual_component_data_invalid")
        comparisons = data.get("organization", {}).get("comparisons")
        if comparisons is not None and (
            not isinstance(comparisons, list) or not comparisons
            or any(not isinstance(row, dict) or any(
                not isinstance(row.get(key), str) or not row[key].strip()
                for key in ("label", "before", "after")
            ) for row in comparisons)
        ):
            raise VisualGap("visual_component_data_invalid")
        for row in comparisons or []:
            if any(
                key in row and (not isinstance(row[key], str) or not row[key].strip())
                for key in ("beforeLabel", "afterLabel", "arrow")
            ) or (("beforeLabel" in row) != ("afterLabel" in row)):
                raise VisualGap("visual_component_data_invalid")
        presentation = data.get("organization", {}).get("purposePresentation")
        if presentation not in (None, "concept"):
            raise ValueError("invalid_purpose_presentation")
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


def fraction_merge_visual(trace):
    from ..explanation.expression_rewrite import build_rewrite_presentation

    transitions = trace["transitions"]
    if len(transitions) == 1 and transitions[0]["operation"] == "combine_fractions" and not transitions[0].get("revealedConditionIds"):
        row = transitions[0]
        from .expression_flow import expression_row, flow_visual

        # The kernel records unchanged summands during structural classification.
        # Use that evidence, rather than formula text or the problem identity,
        # to distinguish a local merge from a whole-expression merge.
        local = bool(row["unchanged"])
        visual = flow_visual([
            expression_row(
                row["before"]["latex"],
                focus=row["localBefore"]["latex"] if local else None,
            ),
            expression_row(
                row["after"]["latex"],
                focus=row["localAfter"]["latex"] if local else None,
                label="局部通分后" if local else "整体通分后",
                relation="=",
            ),
        ], title="合并分式")
        visual["reading"] = "局部通分" if local else "整体通分"
        return visual
    return build_rewrite_presentation(trace)["visual"]


def rewrite_visual(trace):
    from ..explanation.expression_rewrite import build_rewrite_presentation
    return build_rewrite_presentation(trace)["visual"]


def reciprocal_transform(d):
    r = d["reciprocal_roles"]
    return {
        "kind": "basic-inequality-structure-scan",
        "showFocus": False,
        "showRoute": False,
        "ariaLabel": "正数取倒数，转换最值方向",
        "condition": {"label": "原式为正", "expression": math(r["reduced"] + ">0")},
        "target": {"label": "原式的倒数", "expression": math(r["inverse"])},
        "organization": {
            "comparisons": [
                {
                    "label": "取倒数",
                    "beforeLabel": "原式求最大值",
                    "afterLabel": "倒数求最小值",
                    "before": math(r["reduced"]),
                    "after": math(r["inverse"]),
                    "arrow": "⇄",
                },
            ],
        },
        "caption": "原式为正，取倒数后最值方向相反",
        "reading": "正数取倒数",
        "route": "重新观察结构",
    }


def lower_structure(d):
    visual = {
        "kind": "basic-inequality-structure-scan",
        "condition": {
            "label": "原条件",
            "expression": math("，".join(d["conditions"])),
            "tag": "已知条件",
        },
        "target": {
            "label": "原式的倒数" if d.get("reciprocal") else "当前求界表达式",
            "expression": math(d["reciprocal_roles"]["arranged"] if d.get("reciprocal") else d["source_expression"]),
            "tag": "先求正下界" if d.get("reciprocal") else "求最小值",
        },
        "organization": {
            "label": "选出两个正项",
            "steps": [
                {"label": f"第{i + 1}项", "expression": math(term)}
                for i, term in enumerate(d["terms"])
            ],
            "note": "倒数取得正下界，再取倒数得到原式上界"
            if d.get("reciprocal")
            else "求两项和的下界，保留其余项",
        },
        "reading": "正项配对求和",
        "route": DIRECT_AMGM_ROUTE,
    }

    if d.get("substitution_conditions_latex"):
        visual["condition"] = {"label": "换元后的条件", "expression": "，".join(math(r) for r in d["substitution_conditions_latex"])}
    if d.get("constant_product_latex"):
        visual["pattern"] = {
            "first": {"value": math(d["term_latex"][0]), "shape": "square"},
            "second": {"value": math(d["term_latex"][1]), "shape": "circle"},
            "condition": {"operator": "·", "tag": "定积 " + math(d["constant_product_latex"])},
            "target": {"operator": "+", "tag": "求最小值"}}
        visual.pop("organization", None)
        visual["reading"] = "定积求和"
    return visual


def quadratic(d):
    from .expression_flow import expression_row, flow_visual

    before = d["teaching_effect"]["before_latex"]
    after = d["teaching_effect"]["after_latex"]
    square = d["square_latex"]
    if d.get("existing_square_latex"):
        square = d["existing_square_latex"]
        return flow_visual([
            expression_row(square + "+" + after, focus=square),
            expression_row(after, relation="≥"),
        ], title="利用平方非负")
    return flow_visual([
        expression_row(before),
        expression_row(square + "+" + after, focus=square, label="配出平方项", relation="="),
        expression_row(after, relation="≥"),
    ], title="配方，利用平方非负")


def reciprocal_local_transform(d):
    from .expression_flow import expression_row, flow_visual

    roles = d["local_reciprocal_roles"]
    local = roles["reciprocal_bound"].split(r"\geq ")[0]
    product = roles["product_bound"].split(r"\leq ")[0]
    visual = flow_visual([
        expression_row(d["teaching_effect"]["before_latex"], focus=local),
    ], title="转换求界方向")
    visual["organization"]["comparisons"] = [{
        "label": "转换局部求界方向", "beforeLabel": "倒数项求下界", "afterLabel": "正分母求上界",
        "before": math(local), "after": math(product), "arrow": "⇐",
    }]
    return visual


def reciprocal_local(d):
    from .expression_flow import expression_row

    roles = d["local_reciprocal_roles"]
    local, lower = roles["reciprocal_bound"].split(r"\geq ")
    visual = lower_application(d)
    visual.update(
        sumNote="定和 " + math(roles["sum"]),
        localConclusion=math(roles["reciprocal_bound"]),
        expressionFlow=[
            expression_row(d["teaching_effect"]["before_latex"], focus=local),
            expression_row(d["teaching_effect"]["after_latex"], focus=lower, relation="≥"),
        ],
    )
    return visual


def lower_application(d):
    relations = list(dict.fromkeys(item["math"] for item in d["local_relations"]))
    if not relations:
        raise ValueError("verified_local_amgm_relation_missing")
    visual = {
        "kind": "basic-inequality-mapping",
        "formulaStyle": "sum-geometric",
        "presentation": "concept",
        "showPositiveStep": True,
        "stageLabel": "代入两个正项",
        "conclusionLabel": "取倒数得到上界" if d.get("reciprocal") else "得到下界",
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
    local = d.get("local_sum_roles")
    if local:
        visual.update(
            productNote="定积 " + math(local["product"]),
            expressionFlow=[
                {
                    "parts": [
                        {"expression": local[key], "highlight": True},
                        {"expression": local["remainder_tail"]},
                    ],
                    "label": "",
                    "relation": relation,
                }
                for key, relation in (("sum", ""), ("value", "≥"))
            ],
        )
    roles = d.get("constant_product_roles")
    if roles:
        visual.update(
            productNote="定积 " + math(roles["product"]),
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
        "conclusion": math(d["target"])
        + ("的最大值为" if d["direction"] == "<=" else "的最小值为")
        + math(d["bound"]),
    }
    if len(d["equalities"]) == 1:
        visual.pop("equalityRelations")
        visual.update(
            first={"value": math(d["term_latex"][0]), "shape": "square"},
            second={"value": math(d["term_latex"][1]), "shape": "circle"},
            equality=math(d["equality"]),
            templateLabel="基本不等式取等",
            solutionMode="witness",
            conditionLabel="满足原条件",
            condition="；".join(math(r) for r in d["conditions"]),
            verificationLabel="代回目标",
        )
    if d.get("equality_derivation"):
        visual.pop("equalityRelations", None)
        visual.pop("solutionMode", None)
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
                not app["reduction"] and not app.get("terms") for app in applications
            ):
                raise ValueError("verified_equality_reduction_missing")
            visual.update(
                templateLabel=("各次不等式同时取等" if any(a.get("kind") == "quadratic" for a in applications) else f"{len(d['equalities'])}次基本不等式同时取等"),
                equalities=[
                    {
                        "label": "平方项取零" if app.get("kind") == "quadratic" else f"第{i + 1}次取等",
                        "first": {"value": math(app["terms"][0]), "shape": "square"},
                        "second": {"value": math(app["terms"][1]), "shape": "circle"},
                        "result": math(app["reduction"] or "=".join(app["terms"])),
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
    if d.get("substitution_conditions_latex"):
        visual["conditionLabel"] = "换元后的条件与还原关系"
        visual["condition"] = "；".join(math(r) for r in [*d["substitution_conditions_latex"], *d["substitution_definitions_latex"]])
    applications = d.get("equality_applications", [])
    if applications:
        visual["conceptEqualityItems"] = [
            {"kind": "quadratic", "expression": math(app["square"] + "=0")}
            if app.get("kind") == "quadratic" else
            {"kind": "amgm", "first": math(app["terms"][0]), "second": math(app["terms"][1])}
            for app in applications
        ]
    # Display the simultaneous conditions, keeping witnesses and restoration in derive.
    conditions = (
        d.get("substitution_equations_latex")
        or d.get("substitution_conditions_latex")
        or d.get("condition_equations_latex")
        or d["conditions"]
    )
    visual.update(
        presentation="concept",
        conceptEqualities=[math(r) for r in d["equalities_latex"]],
        conceptConditions=[math(r) for r in conditions],
        conceptConditionLabel="换元后的条件" if d.get("substitution_conditions_latex") else "原条件",
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
            "expression": math(r"，".join(items[0]["conditions_latex"])),
        },
        "target": {
            "label": "目标表达式",
            "expression": math(items[0]["target_latex"]),
            "tag": "求最小值",
        },
        "organization": {
            "label": "路线预告：依次估计前一轮下界",
            "steps": [
                {
                    "label": f"第{i + 1}步：" + ("平方非负" if d.get("method_kind") == "quadratic" else "基本不等式"),
                    "expression": math(d["square_latex"] + r"\geq0") if d.get("method_kind") == "quadratic" else " 与 ".join(math(t) for t in d["terms"]),
                }
                for i, d in enumerate(items)
            ],
            "note": "每轮记录取等条件，最后检查能否同时成立",
        },
        "reading": "连续求界",
        "route": f"本解法分{len(items)}次连续求界",
    }
    planning = relation_count_plan(items)
    if planning:
        visual["organization"] = {"label": "规划取等关系", "relationCountHint": planning}
        visual.update(showFocus=False, showRoute=False)
        return visual
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
        visual.update(reading="先消元", route="再求解，最后检查取等")
        visual["target"]["tag"] = (
            f"含 {len(items[0]['teaching_effect']['input_symbols'])} 个变量"
        )
    if any(d.get("method_kind") == "quadratic" for d in items) and cards:
        visual["showFocus"] = False
        visual["organization"]["purposePresentation"] = "concept"
    return visual
