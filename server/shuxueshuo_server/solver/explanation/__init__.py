"""ExplanationBuilder EB1：从成功求解产物生成文字讲解 IR。"""

from .builder import ExplanationBuilder, LessonIRValidator
from .llm import LLMLessonPlanner, write_explanation_debug_artifacts
from .models import (
    EXPLANATION_SNAPSHOT_CONTRACT,
    ExplanationSnapshot,
    LessonIR,
    LessonSection,
    LessonStep,
    TeachingCrossScopeReference,
    TeachingGoal,
    TeachingScope,
    TeachingSource,
    TeachingTraceEntry,
    explanation_snapshot_from_payload,
    lesson_ir_from_payload,
)
from .snapshot import ExplanationSnapshotBuilder

__all__ = [
    "ExplanationBuilder",
    "EXPLANATION_SNAPSHOT_CONTRACT",
    "ExplanationSnapshot",
    "ExplanationSnapshotBuilder",
    "LLMLessonPlanner",
    "LessonIR",
    "LessonIRValidator",
    "LessonSection",
    "LessonStep",
    "TeachingCrossScopeReference",
    "TeachingGoal",
    "TeachingScope",
    "TeachingSource",
    "TeachingTraceEntry",
    "explanation_snapshot_from_payload",
    "lesson_ir_from_payload",
    "write_explanation_debug_artifacts",
]
