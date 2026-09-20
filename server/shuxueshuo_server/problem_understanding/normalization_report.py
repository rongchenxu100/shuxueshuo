"""Serializable audit report for typed mathematical normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .equivalence_rules import RULESET_VERSION, rule_strength, ruleset_hash


@dataclass(frozen=True)
class DerivedFact:
    scope: str
    fact: Any
    rule_id: str
    premises: tuple[Any, ...] = ()
    proof: str = ""
    strength: str = "equivalent"
    confidence: str = "certain"
    source_paths: tuple[str, ...] = ()
    source_expression: str | None = None
    assumptions: tuple[Any, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "fact": self.fact,
            "rule_id": self.rule_id,
            "premises": list(self.premises),
            "proof": self.proof,
            "strength": self.strength,
            "confidence": self.confidence,
            "source_paths": list(self.source_paths),
            "source_expression": self.source_expression,
            "assumptions": list(self.assumptions),
        }


@dataclass(frozen=True)
class NormalizationReport:
    version: str = RULESET_VERSION
    ruleset_hash: str = field(default_factory=ruleset_hash)
    initial_facts: tuple[Mapping[str, Any], ...] = ()
    canonical_facts: tuple[Mapping[str, Any], ...] = ()
    derived_facts: tuple[DerivedFact, ...] = ()
    proofs: tuple[Mapping[str, Any], ...] = ()
    blocked: tuple[Mapping[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ruleset_hash": self.ruleset_hash,
            "initial_facts": list(self.initial_facts),
            "canonical_facts": list(self.canonical_facts),
            "derived_facts": [item.to_payload() for item in self.derived_facts],
            "proofs": list(self.proofs),
            "blocked": list(self.blocked),
        }


def _scope_facts(tree: Mapping[str, Any], key: str, path: str = "r"):
    for index, fact in enumerate(tree.get(key, ())):
        yield {"scope": path, "index": index, "fact": fact}
    for index, child in enumerate(tree.get("children", ())):
        yield from _scope_facts(child, key, f"{path}.c{index}")


def _is_material_fact(fact: Any) -> bool:
    """Reject normalization sentinels that mean a source fact was removed."""
    if not isinstance(fact, list) or not fact or fact == ["and"]:
        return False
    return not (
        fact[0] == "="
        and len(fact) == 3
        and fact[1] == fact[2]
    )


def from_normalization(
    semantic: Mapping[str, Any], normalized: Mapping[str, Any], *, proofs=()
) -> NormalizationReport:
    derived = []
    proof_payloads = tuple(dict(item) for item in proofs)
    for item in proof_payloads:
        rule_id = str(item.get("rule", "unknown"))
        derived.append(
            DerivedFact(
                scope=str(item.get("scope", "r")),
                fact=item.get("after"),
                rule_id=rule_id,
                premises=tuple(item.get("premises", ())),
                proof=str(item.get("proof", rule_id)),
                strength=rule_strength(rule_id),
                confidence="certain" if not item.get("assumptions") else "conditional",
                source_paths=tuple(item.get("source_paths", ())),
                source_expression=item.get("source_expression"),
                assumptions=tuple(item.get("assumptions", ())),
            )
        )
    canonical = list(_scope_facts(normalized.get("root", normalized), "facts"))
    # Keep the candidate tree source-preserving while exposing equivalent
    # internal facts to runtime/binding consumers through the report.
    for index, item in enumerate(derived):
        if item.strength == "equivalent" and _is_material_fact(item.fact):
            canonical.append(
                {
                    "scope": item.scope,
                    "index": f"derived:{index}",
                    "fact": item.fact,
                    "rule_id": item.rule_id,
                }
            )
    return NormalizationReport(
        initial_facts=tuple(_scope_facts(semantic, "facts")),
        canonical_facts=tuple(canonical),
        derived_facts=tuple(derived),
        proofs=proof_payloads,
        blocked=tuple(dict(item) for item in normalized.get("blocked", ())),
    )
