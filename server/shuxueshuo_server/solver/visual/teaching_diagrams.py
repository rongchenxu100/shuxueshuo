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
            if set(roles) != {"evidence"} or roles["evidence"] not in source_step_ids:
                raise VisualGap("visual_role_outside_step_sources")
            source = sources.get(roles["evidence"])
            if source is None:
                raise VisualGap("visual_source_missing")
            try:
                ref, evidence = evidence_for(source, snapshot)
                payload = spec.binder(evidence["data"])
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
                    "source_step_ids": [source.source_step_id],
                    "evidence_refs": [ref],
                    "data": payload,
                }
            )
        for block in blocks:
            validate_diagram_block(block)
        return tuple(blocks)


def math(value):
    return r"\(" + value + r"\)"


def structure(d):
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
    return VisualSpecRegistry(
        (
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
        "basic-inequality-structure-scan": (
            "condition",
            "target",
            "pattern",
            "reading",
            "route",
        ),
        "basic-inequality-mapping": (
            "mappings",
            "mapped",
            "fixedCondition",
            "conclusion",
        ),
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
    if component == "basic-inequality-mapping" and any(
        field in data and (not isinstance(data[field], str) or not data[field].strip())
        for field in ("replaced", "substituted")
    ):
        raise VisualGap("visual_component_data_invalid")
