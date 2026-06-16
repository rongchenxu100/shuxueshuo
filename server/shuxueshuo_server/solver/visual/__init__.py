"""VisualStepIR VS0/VS1 compilation helpers."""

from .builder import BaseSceneBuilder, GeneratedVisualBase, GeometrySpecBuilder, VisualAuthoringBase, VisualStepBuilder
from .compiler import CompiledVisualArtifacts, forward_compile, reverse_compile
from .llm import LLMVisualStepOptimizer, write_visual_optimization_debug_artifacts
from .models import JsonObject, VisualStep, VisualStepIR
from .registry import (
    ComponentTypeSpec,
    ComponentTypeSpecRegistry,
    LayerRegistry,
    default_component_registry,
    default_layer_registry,
)
from .validator import VisualStepIRValidationError, VisualStepIRValidator

__all__ = [
    "CompiledVisualArtifacts",
    "ComponentTypeSpec",
    "ComponentTypeSpecRegistry",
    "BaseSceneBuilder",
    "GeneratedVisualBase",
    "GeometrySpecBuilder",
    "JsonObject",
    "LayerRegistry",
    "LLMVisualStepOptimizer",
    "VisualAuthoringBase",
    "VisualStep",
    "VisualStepBuilder",
    "VisualStepIR",
    "VisualStepIRValidationError",
    "VisualStepIRValidator",
    "default_component_registry",
    "default_layer_registry",
    "forward_compile",
    "reverse_compile",
    "write_visual_optimization_debug_artifacts",
]
