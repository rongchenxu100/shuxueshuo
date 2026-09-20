"""Registry metadata for typed mathematical equivalence rules.

The parser and runtime keep their own representations; this module provides a
single auditable vocabulary for proofs emitted by the normalization pass.
LLM-facing prompts must never expose these internal rule names as output
syntax.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Callable, Mapping


RuleApply = Callable[[Any, Any], Any]


@dataclass(frozen=True)
class EquivalenceRule:
    rule_id: str
    input_kinds: tuple[str, ...] = ()
    output_kind: str = ""
    apply: RuleApply | None = None
    priority: int = 100
    reversible: bool = False
    strength: str = "equivalent"


_RULE_IDS = (
    "coordinate_axis_membership",
    "coordinate_symbol_binding",
    "bisector_unit_ratio",
    "duplicate_relation",
    "exact_numeric_intersection",
    "finite_set_membership_redundancy",
    "named_vertex_binding",
    "nondegenerate_parallelogram_diagonals",
    "parameter_state_extremum_witness",
    "point_coordinate_components",
    "point_intersection_definition",
    "positive_cut_ratio",
    "quadratic_axis_unique",
    "right_angle_from_angle",
    "right_angle_from_perpendicular",
    "standalone_segment_declaration",
)

RULES: Mapping[str, EquivalenceRule] = {
    rule_id: EquivalenceRule(rule_id=rule_id)
    for rule_id in _RULE_IDS
}

RULESET_VERSION = "semantic-equivalence/v1"


def ruleset_hash() -> str:
    payload = {
        "version": RULESET_VERSION,
        "rules": [
            {
                "id": rule.rule_id,
                "input_kinds": rule.input_kinds,
                "output_kind": rule.output_kind,
                "priority": rule.priority,
                "reversible": rule.reversible,
                "strength": rule.strength,
            }
            for rule in sorted(RULES.values(), key=lambda item: item.rule_id)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def known_rule(rule_id: str) -> bool:
    return rule_id in RULES


def rule_strength(rule_id: str) -> str:
    if rule_id in {"coordinate_axis_membership", "right_angle_from_angle", "right_angle_from_perpendicular"}:
        return "equivalent"
    if rule_id in {"coordinate_symbol_binding", "point_coordinate_components", "parameter_state_extremum_witness"}:
        return "entailed"
    return RULES.get(rule_id, EquivalenceRule(rule_id)).strength
