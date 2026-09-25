"""Explicit Stage 4A admission; never included in the default Family registry."""

from dataclasses import replace

from .basic_inequality import BASIC_INEQUALITY_FAMILY
from .common_binding_rules import (
    condition_arg_binding,
    exact_call_result_binding,
    latest_state_binding,
)
from .expression_rewrite import (
    ORGANIZE_EXPRESSIONS_BINDING,
    ORGANIZE_EXPRESSIONS_CONTRACT,
)
from .models import (
    CapabilityContractSpec,
    FamilyRegistry,
    MethodBindingRuleSpec,
    StateSlotPattern,
)

BASIC_INEQUALITY_RUNTIME_FAMILY = replace(
    BASIC_INEQUALITY_FAMILY,
    method_ids=(
        "organize_expressions",
        "apply_two_term_amgm",
        "close_equality_and_restore",
    ),
    capability_contracts=(
        ORGANIZE_EXPRESSIONS_CONTRACT,
        CapabilityContractSpec(
            "apply_two_term_amgm",
            slot_reads=(
                StateSlotPattern(
                    "expression", "Expression", semantic_role="expression"
                ),
                StateSlotPattern(
                    "amgmBound",
                    "AmgmBound",
                    semantic_role="previous_bound",
                    allows_anonymous_result=True,
                ),
            ),
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
                    "minimumExpression",
                    "MinimumExpression",
                    output_key="minimum",
                    required=False,
                    semantic_role="minimum",
                    identity_policy="value_only",
                ),
                StateSlotPattern(
                    "maximumExpression",
                    "MaximumExpression",
                    output_key="maximum",
                    required=False,
                    semantic_role="maximum",
                    identity_policy="value_only",
                ),
            ),
        ),
    ),
    method_binding_rules=(
        ORGANIZE_EXPRESSIONS_BINDING,
        MethodBindingRuleSpec(
            "apply_two_term_amgm",
            input_bindings=(
                condition_arg_binding("target"),
                latest_state_binding("expression", required=False),
                exact_call_result_binding("previous_bound", required=False),
            ),
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
