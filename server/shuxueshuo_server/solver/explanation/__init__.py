"""ExplanationBuilder EB1：从成功求解产物生成文字讲解 IR。"""

from .annotated_teaching import (
    ANNOTATED_TEACHING_PLAN_CONTRACT,
    AnnotatedTeachingPlan,
    AnnotatedTeachingPlanProjector,
    AnnotatedTeachingProjection,
    AnnotatedTeachingProjectionError,
    AnnotatedTeachingPrompt,
    TeachingMaterialProjector,
    annotated_teaching_plan_schema,
    build_projection_audit,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from .builder import ExplanationBuilder, LessonIRValidator
from .llm import LLMLessonPlanner, write_explanation_debug_artifacts
from .models import (
    EXPLANATION_SNAPSHOT_CONTRACT,
    ExplanationSnapshot,
    LessonIR,
    LessonSection,
    LessonStep,
    TeachingGoal,
    TeachingScope,
    TeachingSource,
    explanation_snapshot_from_payload,
    lesson_ir_from_payload,
)
from .snapshot import ExplanationSnapshotBuilder

__all__ = [
    "ANNOTATED_TEACHING_PLAN_CONTRACT",
    "AnnotatedTeachingPlan",
    "AnnotatedTeachingPlanProjector",
    "AnnotatedTeachingProjection",
    "AnnotatedTeachingProjectionError",
    "AnnotatedTeachingPrompt",
    "ExplanationBuilder",
    "EXPLANATION_SNAPSHOT_CONTRACT",
    "ExplanationSnapshot",
    "ExplanationSnapshotBuilder",
    "LLMLessonPlanner",
    "LessonIR",
    "LessonIRValidator",
    "LessonSection",
    "LessonStep",
    "TeachingGoal",
    "TeachingMaterialProjector",
    "TeachingScope",
    "TeachingSource",
    "annotated_teaching_plan_schema",
    "build_projection_audit",
    "explanation_snapshot_from_payload",
    "lesson_scope_content_schema",
    "lesson_ir_from_payload",
    "render_annotated_teaching_prompt",
    "write_explanation_debug_artifacts",
]
