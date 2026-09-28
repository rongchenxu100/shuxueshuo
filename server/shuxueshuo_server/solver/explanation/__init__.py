"""Teaching public interface; lazily loaded to keep Method imports acyclic."""

from importlib import import_module

_EXPORT_MODULES = {
    "ANNOTATED_TEACHING_PLAN_CONTRACT": "annotated_teaching",
    "AnnotatedTeachingPlan": "annotated_teaching",
    "AnnotatedTeachingPlanProjector": "annotated_teaching",
    "AnnotatedTeachingProjection": "annotated_teaching",
    "AnnotatedTeachingProjectionError": "annotated_teaching",
    "AnnotatedTeachingPrompt": "annotated_teaching",
    "TeachingMaterialProjector": "annotated_teaching",
    "annotated_teaching_plan_schema": "annotated_teaching",
    "build_projection_audit": "annotated_teaching",
    "lesson_scope_content_schema": "annotated_teaching",
    "render_annotated_teaching_prompt": "annotated_teaching",
    "LESSON_ASSEMBLY_AUTHORITY_CONTRACT": "lesson_ir",
    "LESSON_IR_CONTRACT": "lesson_ir",
    "LessonAuthoringPipeline": "lesson_ir",
    "LessonGoal": "lesson_ir",
    "LessonIR": "lesson_ir",
    "LessonIRValidationError": "lesson_ir",
    "LessonScope": "lesson_ir",
    "LessonStep": "lesson_ir",
    "LessonTraversalIndex": "lesson_ir",
    "OwnedLessonStep": "lesson_ir",
    "RecursiveLessonBuildResult": "lesson_ir",
    "RecursiveLessonIRAssembler": "lesson_ir",
    "RecursiveLessonIRValidator": "lesson_ir",
    "lesson_ir_from_payload": "lesson_ir",
    "EXPLANATION_SNAPSHOT_CONTRACT": "models",
    "ExplanationSnapshot": "models",
    "TeachingGoal": "models",
    "TeachingScope": "models",
    "TeachingSource": "models",
    "explanation_snapshot_from_payload": "models",
    "ExplanationSnapshotBuilder": "snapshot",
    "BoundLessonStep": "scope_lesson",
    "LessonScopeContentValidator": "scope_lesson",
    "ScopeLessonAuthoringService": "scope_lesson",
    "ScopeLessonConfigurationError": "scope_lesson",
    "ScopeLessonDiagnostic": "scope_lesson",
    "ScopeLessonGenerationResult": "scope_lesson",
    "ScopeLessonValidationResult": "scope_lesson",
    "build_deterministic_scope_content": "scope_lesson",
    "evaluate_scope_lesson_content": "scope_lesson",
}


def __getattr__(name):
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


__all__ = [
    "ANNOTATED_TEACHING_PLAN_CONTRACT",
    "EXPLANATION_SNAPSHOT_CONTRACT",
    "LESSON_ASSEMBLY_AUTHORITY_CONTRACT",
    "LESSON_IR_CONTRACT",
    "AnnotatedTeachingPlan",
    "AnnotatedTeachingPlanProjector",
    "AnnotatedTeachingProjection",
    "AnnotatedTeachingProjectionError",
    "AnnotatedTeachingPrompt",
    "BoundLessonStep",
    "ExplanationSnapshot",
    "ExplanationSnapshotBuilder",
    "LessonAuthoringPipeline",
    "LessonGoal",
    "LessonIR",
    "LessonIRValidationError",
    "LessonScope",
    "LessonScopeContentValidator",
    "LessonStep",
    "LessonTraversalIndex",
    "OwnedLessonStep",
    "RecursiveLessonBuildResult",
    "RecursiveLessonIRAssembler",
    "RecursiveLessonIRValidator",
    "ScopeLessonAuthoringService",
    "ScopeLessonConfigurationError",
    "ScopeLessonDiagnostic",
    "ScopeLessonGenerationResult",
    "ScopeLessonValidationResult",
    "TeachingGoal",
    "TeachingMaterialProjector",
    "TeachingScope",
    "TeachingSource",
    "annotated_teaching_plan_schema",
    "build_deterministic_scope_content",
    "build_projection_audit",
    "evaluate_scope_lesson_content",
    "explanation_snapshot_from_payload",
    "lesson_ir_from_payload",
    "lesson_scope_content_schema",
    "render_annotated_teaching_prompt",
]
