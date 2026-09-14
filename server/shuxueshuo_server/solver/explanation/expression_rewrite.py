"""Student content and semantic visual spec from a verified Method trace only."""

from copy import deepcopy

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
    def bind(self, *, method_id, explanation, group, snapshot):
        traces = [
            f
            for t in group.traces
            for f in t.trace_fragments
            if f.get("kind") == "verified_expression_rewrite"
        ]
        if len(traces) != 1:
            raise ValueError("rewrite group must contain exactly one verified call")
        trace = traces[0]
        presentation = build_rewrite_presentation(trace)
        return {
            "source": "\\(" + trace["source"]["latex"] + "\\)",
            "result": "\\(" + trace["result"]["latex"] + "\\)",
            "derive_items": [" ".join(line) for line in presentation["derive"]],
        }


def build_rewrite_lesson(snapshot, method_spec):
    """Deterministic Method explanation through the existing role registry."""
    from .models import LessonCandidateGroup, LessonIR, LessonSection, LessonStep
    from .role_binders import RoleBinderRegistry

    if not snapshot.checks or not all(c.get("ok") for c in snapshot.checks):
        raise ValueError("successful execution checks required")
    if len(snapshot.teaching_trace) != 1 or len(snapshot.effective_steps) != 1:
        raise ValueError("rewrite prefix expects one committed Method call")
    entry = snapshot.teaching_trace[0]
    group = LessonCandidateGroup(snapshot.effective_steps[0], (entry,))
    roles = (
        RoleBinderRegistry.default()
        .require_method(method_spec.explanation.role_binder_id)
        .bind(
            method_id=method_spec.method_id,
            explanation=method_spec.explanation,
            group=group,
            snapshot=snapshot,
        )
    )
    step = LessonStep(
        id="organize",
        scope_id=entry.scope_id,
        source_step_ids=(entry.source_step_id,),
        capability_ids=(entry.capability_id,),
        trace_refs=(entry.trace_id,),
        title=method_spec.explanation.student_title_template,
        goal=method_spec.explanation.student_goal_template,
        derive=tuple(("", line) for line in roles["derive_items"]),
        box=(roles["result"],),
    )
    return LessonIR(
        snapshot.problem_id,
        snapshot.family_id,
        (LessonSection(entry.scope_id, "整理式子", (step.id,)),),
        (step,),
    )
