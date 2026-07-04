"""Compatibility facade for StepIntent normalization.

The implementation is split by responsibility across normalizer_core/common,
normalizer_quadratic, normalizer_path, and normalizer_binding. Keep this module
as the public import point for existing runtime callers and tests.
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.normalizer_common import (
    NormalizationRule,
    NormalizationRuleContext,
    NormalizationRuleResult,
)
from shuxueshuo_server.solver.runtime.normalizer_core import (
    DEFAULT_NORMALIZATION_RULES,
    StepIntentNormalizer,
)

__all__ = (
    "DEFAULT_NORMALIZATION_RULES",
    "NormalizationRule",
    "NormalizationRuleContext",
    "NormalizationRuleResult",
    "StepIntentNormalizer",
)
