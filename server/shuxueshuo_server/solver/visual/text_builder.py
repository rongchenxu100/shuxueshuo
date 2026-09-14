"""MethodVisualSpec projection for semantic text-lesson components.

Geometry VisualStepIR remains unchanged. Text lessons compile this component
through build-text-page.mjs instead of introducing geometry scene objects.
"""

from shuxueshuo_server.solver.explanation.expression_rewrite import (
    build_rewrite_presentation,
)


class ExpressionRewriteVisualBinder:
    def bind(self, *, trace, spec):
        if spec.role_binder_id != "expression_rewrite" or not any(
            scene.get("kind") == "expression_rewrite" for scene in spec.scene_templates
        ):
            raise ValueError("expression rewrite visual contract mismatch")
        return build_rewrite_presentation(trace)["visual"]


TEXT_VISUAL_BINDERS = {"expression_rewrite": ExpressionRewriteVisualBinder()}


def build_text_method_visual(*, snapshot, lesson_step, method_spec):
    spec = method_spec.visual
    if spec is None or spec.role_binder_id not in TEXT_VISUAL_BINDERS:
        raise ValueError("unsupported text MethodVisualSpec")
    entries = [
        entry
        for entry in snapshot.teaching_trace
        if entry.trace_id in lesson_step.trace_refs
    ]
    if len(entries) != 1 or entries[0].method_id != method_spec.method_id:
        raise ValueError("visual trace binding mismatch")
    traces = [
        t
        for t in entries[0].trace_fragments
        if t.get("kind") == "verified_expression_rewrite"
    ]
    if len(traces) != 1:
        raise ValueError("verified rewrite trace required")
    return TEXT_VISUAL_BINDERS[spec.role_binder_id].bind(trace=traces[0], spec=spec)
