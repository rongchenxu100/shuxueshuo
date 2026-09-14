"""Recursive VisualStepIR v2 authoring and compilation helpers."""

from .animation import AnimationTimelineBuilder
from .builder import GeneratedVisualBase, GeometrySpecBuilder, VisualStepBuilder
from .compiler import CompiledVisualArtifacts, forward_compile
from .models import (
    JsonObject,
    VisualFrame,
    VisualGoal,
    VisualObject,
    VisualScope,
    VisualStep,
    VisualStepIR,
    VisualTraversalIndex,
    visual_step_ir_from_payload,
)
from .parametric import ParametricExpressionResolver
from .recursive_state import (
    BranchVisualState,
    RecursiveVisualStateResolver,
    RecursiveVisualStateResult,
    VisualStepResolution,
)
from .registry import (
    ComponentTypeSpec,
    ComponentTypeSpecRegistry,
    default_component_registry,
)
from .validator import VisualStepIRValidationError, VisualStepIRValidator

__all__ = [
    "CompiledVisualArtifacts",
    "ComponentTypeSpec",
    "ComponentTypeSpecRegistry",
    "AnimationTimelineBuilder",
    "BranchVisualState",
    "GeneratedVisualBase",
    "GeometrySpecBuilder",
    "JsonObject",
    "ParametricExpressionResolver",
    "RecursiveVisualStateResolver",
    "RecursiveVisualStateResult",
    "VisualFrame",
    "VisualGoal",
    "VisualObject",
    "VisualScope",
    "VisualStep",
    "VisualStepBuilder",
    "VisualStepIR",
    "VisualStepIRValidationError",
    "VisualStepIRValidator",
    "VisualStepResolution",
    "VisualTraversalIndex",
    "default_component_registry",
    "forward_compile",
    "visual_step_ir_from_payload",
]
