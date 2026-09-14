"""Reusable rewrite capability contract; not a complete inequality Family."""

from .common_binding_rules import condition_arg_binding, latest_state_binding
from .models import CapabilityContractSpec, MethodBindingRuleSpec, StateSlotPattern

ORGANIZE_EXPRESSIONS_BINDING = MethodBindingRuleSpec(
    method_id="organize_expressions",
    input_bindings=(
        latest_state_binding("expression"),
        condition_arg_binding("conditions", required=False),
    ),
)

ORGANIZE_EXPRESSIONS_CONTRACT = CapabilityContractSpec(
    capability_id="organize_expressions",
    slot_reads=(
        StateSlotPattern("expression", "Expression", semantic_role="expression"),
    ),
    slot_writes=(
        StateSlotPattern(
            "expression",
            "Expression",
            output_key="organized_expression",
            semantic_role="organized_expression",
            identity_policy="preserve_input_object",
            identity_arg="expression",
            write_mode="transition",
        ),
    ),
    notes=("保留输入对象，只提交最后一行；条件通过显式参数绑定。",),
)
