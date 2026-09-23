"""Explicit Stage 4A admission; never included in the default Family registry."""

from dataclasses import replace

from .basic_inequality import BASIC_INEQUALITY_FAMILY
from .common_binding_rules import condition_arg_binding, exact_call_result_binding
from .models import (
    CapabilityContractSpec,
    FamilyRegistry,
    MethodBindingRuleSpec,
    StateSlotPattern,
)

BASIC_INEQUALITY_RUNTIME_FAMILY = replace(
    BASIC_INEQUALITY_FAMILY,
    method_ids=("apply_two_term_amgm", "close_equality_and_restore"),
    capability_contracts=(
        CapabilityContractSpec(
            "apply_two_term_amgm",
            slot_writes=(
                StateSlotPattern(
                    "amgmBound",
                    "AmgmBound",
                    output_key="bound",
                    semantic_role="bound",
                    identity_policy="value_only",
                ),
            ),
        ),
        CapabilityContractSpec(
            "close_equality_and_restore",
            slot_reads=(
                StateSlotPattern(
                    "amgmBound",
                    "AmgmBound",
                    semantic_role="bound",
                    allows_anonymous_result=True,
                ),
            ),
            slot_writes=(
                StateSlotPattern(
                    "maximumExpression",
                    "MaximumExpression",
                    output_key="maximum",
                    semantic_role="maximum",
                    identity_policy="value_only",
                ),
            ),
        ),
    ),
    method_binding_rules=(
        MethodBindingRuleSpec(
            "apply_two_term_amgm", input_bindings=(condition_arg_binding("target"),)
        ),
        MethodBindingRuleSpec(
            "close_equality_and_restore",
            input_bindings=(
                condition_arg_binding("target"),
                exact_call_result_binding("bound"),
            ),
        ),
    ),
    step_recipes=(),
    mechanism_packs=(),
)

STAGE4A_FAMILY_REGISTRY = FamilyRegistry((BASIC_INEQUALITY_RUNTIME_FAMILY,))
