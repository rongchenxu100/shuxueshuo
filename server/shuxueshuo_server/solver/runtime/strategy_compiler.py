"""Strategy StepIntent 编译兼容 facade。

实现已拆分到 ``binding_index``、``binding_rules`` 和 ``recipe_compiler``。
本模块保留旧导入路径，避免调用方一次性迁移。
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    RuntimeHandleBinding,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    DEFAULT_BINDING_SELECTORS,
    DEFAULT_EXPANSION_SELECTORS,
    BindingSelectorFn,
    ExpansionSelectorFn,
    MethodBindingRuleRegistry,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    DEFAULT_RECIPE_COMPILERS,
    RecipeCompileStrategyFn,
    RecipeExecutionSpecRegistry,
    RecipeTrialExecutor,
    _method_output_union,
    _output_key_from_promote_source,
    _parameter_output_key_from_symbol_path,
)

__all__ = [
    "BindingSelectorFn",
    "CanonicalRuntimeBindingIndex",
    "DEFAULT_BINDING_SELECTORS",
    "DEFAULT_EXPANSION_SELECTORS",
    "DEFAULT_RECIPE_COMPILERS",
    "ExpansionSelectorFn",
    "MethodBindingRuleRegistry",
    "RecipeCompileStrategyFn",
    "RecipeExecutionSpecRegistry",
    "RecipeTrialExecutor",
    "RuntimeHandleBinding",
    "_method_output_union",
    "_output_key_from_promote_source",
    "_parameter_output_key_from_symbol_path",
]
