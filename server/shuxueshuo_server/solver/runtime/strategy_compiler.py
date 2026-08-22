"""Functional capability compiler exports.

实现已拆分到 ``binding_index``、``binding_rules`` 和 ``recipe_compiler``。
The legacy planner-draft compiler was retired in Track D.
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    RuntimeHandleBinding,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    MethodBindingRuleRegistry,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    DEFAULT_RECIPE_COMPILERS,
    FunctionalCapabilityCompiler,
    RecipeCompileStrategyFn,
    RecipeExecutionSpecRegistry,
    _method_output_union,
    _output_key_from_promote_source,
    _parameter_output_key_from_symbol_path,
)

__all__ = [
    "CanonicalRuntimeBindingIndex",
    "DEFAULT_RECIPE_COMPILERS",
    "FunctionalCapabilityCompiler",
    "MethodBindingRuleRegistry",
    "RecipeCompileStrategyFn",
    "RecipeExecutionSpecRegistry",
    "RuntimeHandleBinding",
    "_method_output_union",
    "_output_key_from_promote_source",
    "_parameter_output_key_from_symbol_path",
]
