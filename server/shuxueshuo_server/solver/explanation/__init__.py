"""ExplanationBuilder EB1：从成功求解产物生成文字讲解 IR。"""

from .builder import ExplanationBuilder, LessonIRValidator
from .llm import LLMLessonPlanner, write_explanation_debug_artifacts
from .models import (
    ExplanationSnapshot,
    LessonIR,
    LessonSection,
    LessonStep,
    TeachingTraceEntry,
)
from .snapshot import ExplanationSnapshotBuilder

__all__ = [
    "ExplanationBuilder",
    "ExplanationSnapshot",
    "ExplanationSnapshotBuilder",
    "LLMLessonPlanner",
    "LessonIR",
    "LessonIRValidator",
    "LessonSection",
    "LessonStep",
    "TeachingTraceEntry",
    "write_explanation_debug_artifacts",
]
