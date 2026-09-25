"""Student content and semantic visual spec from a verified Method trace only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

LABELS = {
    "combine_fractions": "通分",
    "substitute_condition": "代入条件",
    "equivalent_rewrite": "等价整理",
}


def build_rewrite_presentation(trace: dict) -> dict:
    if trace.get("kind") != "verified_expression_rewrite":
        raise ValueError("presentation requires verified_expression_rewrite trace")
    transitions = deepcopy(trace["transitions"])
    cards = deepcopy(trace["conditionCards"])
    for card in cards:
        card.pop("source", None)
        card.pop("boundIndex", None)
    reveal = trace["teachingEffect"] == "combine_fractions_revealing_condition"
    title = "整理目标式：通分显条件" if reveal else "整理目标式"
    beats = [
        {"kind": "focus", "transitionId": transitions[0]["id"], "title": "观察目标式"}
    ]
    derive = []
    for t in transitions:
        t["label"] = LABELS[t["operation"]]
        beats.append(
            {"kind": "transform", "transitionId": t["id"], "title": t["label"]}
        )
        condition_text = "，".join(
            c["latex"] for c in cards if c["id"] in t["conditionCardIds"]
        )
        equation = t["localBefore"]["latex"] + "=" + t["localAfter"]["latex"]
        if not t["localBefore"]["latex"] or not t["localAfter"]["latex"]:
            equation = t["before"]["latex"] + "=" + t["after"]["latex"]
        derive.append(
            [
                (
                    "由 \\(" + condition_text + "\\)"
                    if condition_text and t["operation"] == "substitute_condition"
                    else t["label"]
                ),
                "\\(" + equation + "\\)",
            ]
        )
    beats.append({"kind": "result", "title": "整理结果"})
    derive.append(["∴ 原式", "\\(" + trace["result"]["latex"] + "\\)"])
    visual = {
        "kind": "expression-rewrite",
        "title": title,
        "source": deepcopy(trace["source"]),
        "result": deepcopy(trace["result"]),
        "conditionCards": cards,
        "transitions": transitions,
        "beats": beats,
    }
    return {
        "id": "organize",
        "section": "整理式子",
        "title": title,
        "t": 0,
        "showDiagram": False,
        "derive": derive,
        "box": ["原式 \\(=" + trace["result"]["latex"] + "\\)"],
        "visual": visual,
    }


class ExpressionRewriteRoleBinder:
    """Bind a verified rewrite trace into student-facing role slots."""

    def bind(self, *, method_id, explanation, traces, snapshot=None):
        del method_id, explanation, snapshot
        rewrite_traces = [
            fragment
            for fragment in traces
            if fragment.get("kind") == "verified_expression_rewrite"
        ]
        if len(rewrite_traces) != 1:
            raise ValueError("rewrite group must contain exactly one verified call")
        presentation = build_rewrite_presentation(rewrite_traces[0])
        return {
            "source": "\\(" + rewrite_traces[0]["source"]["latex"] + "\\)",
            "result": "\\(" + rewrite_traces[0]["result"]["latex"] + "\\)",
            "derive_items": [" ".join(line) for line in presentation["derive"]],
        }


@dataclass(frozen=True)
class RewriteLessonStep:
    id: str
    scope_id: str
    source_step_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    trace_refs: tuple[str, ...]
    title: str
    goal: str
    derive: tuple[tuple[str, str], ...]
    box: tuple[str, ...]


@dataclass(frozen=True)
class RewriteLessonSection:
    scope_id: str
    title: str
    step_ids: tuple[str, ...]


@dataclass(frozen=True)
class RewriteLessonIR:
    problem_id: str
    family_id: str
    sections: tuple[RewriteLessonSection, ...]
    steps: tuple[RewriteLessonStep, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "sections": [
                {
                    "scope_id": section.scope_id,
                    "title": section.title,
                    "step_ids": list(section.step_ids),
                }
                for section in self.sections
            ],
            "steps": [
                {
                    "id": step.id,
                    "scope_id": step.scope_id,
                    "source_step_ids": list(step.source_step_ids),
                    "capability_ids": list(step.capability_ids),
                    "trace_refs": list(step.trace_refs),
                    "title": step.title,
                    "goal": step.goal,
                    "derive": [list(line) for line in step.derive],
                    "box": list(step.box),
                }
                for step in self.steps
            ],
        }


def build_rewrite_lesson(
    *,
    problem_id: str,
    family_id: str,
    method_spec,
    trace: dict,
    source_step_id: str,
    scope_id: str = "problem",
    trace_id: str | None = None,
) -> RewriteLessonIR:
    """Deterministic rewrite explanation from a verified Method trace."""

    binder = ExpressionRewriteRoleBinder()
    roles = binder.bind(
        method_id=method_spec.method_id,
        explanation=method_spec.teaching_unit,
        traces=(trace,),
    )
    resolved_trace_id = trace_id or f"{source_step_id}:trace"
    unit = method_spec.teaching_unit
    if unit is None:
        raise ValueError("organize_expressions requires teaching_unit")
    step = RewriteLessonStep(
        id="organize",
        scope_id=scope_id,
        source_step_ids=(source_step_id,),
        capability_ids=("organize_expressions",),
        trace_refs=(resolved_trace_id,),
        title=unit.title_template,
        goal=unit.goal_template,
        derive=tuple(("", line) for line in roles["derive_items"]),
        box=(roles["result"],),
    )
    return RewriteLessonIR(
        problem_id,
        family_id,
        (RewriteLessonSection(scope_id, "整理式子", (step.id,)),),
        (step,),
    )


class RewriteTeachingProjector:
    def project(self, evidence, *, planning_context=None):
        from .evidence_projectors import ProjectedTeachingEvidence

        presentation = build_rewrite_presentation(evidence.data)
        return ProjectedTeachingEvidence(
            evidence.evidence_id,
            evidence.to_payload(),
            calculations=(
                {
                    "calculation_id": "rewrite_chain",
                    "kind": "verified_relation_chain",
                    "statements": [" ".join(row) for row in presentation["derive"]],
                },
            ),
        )


def rewrite_evidence_for(source, snapshot):
    matches = [
        (key, payload)
        for key, payload in snapshot.evidence.items()
        if payload.get("schema_version") == "expression-rewrite-teaching-evidence/v1"
        and payload.get("step_id") == source.source_step_id
    ]
    if len(matches) != 1:
        raise ValueError("rewrite_teaching_evidence_missing_or_ambiguous")
    return matches[0]


def public_rewrite_roles(source, snapshot):
    _, evidence = rewrite_evidence_for(source, snapshot)
    trace = evidence["data"]
    presentation = build_rewrite_presentation(trace)
    return {
        "source": "\\(" + trace["source"]["latex"] + "\\)",
        "result": "\\(" + trace["result"]["latex"] + "\\)",
        "derive_items": [" ".join(row) for row in presentation["derive"]],
    }
