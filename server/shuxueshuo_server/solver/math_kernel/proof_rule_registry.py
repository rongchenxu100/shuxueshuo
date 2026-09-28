"""Immutable registry of trusted local certificate checkers.

Only application code registers packages. Certificate data can select an exact
registered identity; it cannot load code, add rules or replace a checker.
Every package uses the common envelope: schema_version, ruleset_hash and a
nodes list of objects with rule_id. The registry checks package identity, rule
ownership and the node-count cap. Package checkers own the remaining schema,
sources, premise authority, resource accounting and mathematical validation.
An explicitly supplied budget determines the effective limits; otherwise the
context limits apply, matching the legacy checker's environment.
This registry does not select search strategies or grant premise authority.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .proof_algebra import ProofFailure
from .proof_types import ProofContext, ProofResult, _Budget


@dataclass(frozen=True)
class RulePackage:
    """Trusted checker callable: checker(proof, context, *, budget)."""

    package_id: str
    ruleset_hash: str
    rule_ids: tuple[str, ...]
    checker: Callable[..., ProofResult]

    def __post_init__(self):
        if (
            not isinstance(self.package_id, str)
            or not self.package_id
            or not isinstance(self.ruleset_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.ruleset_hash) is None
            or not isinstance(self.rule_ids, tuple)
            or not self.rule_ids
            or any(not isinstance(r, str) or not r for r in self.rule_ids)
            or len(set(self.rule_ids)) != len(self.rule_ids)
            or not callable(self.checker)
        ):
            raise ValueError("invalid trusted rule package")

    @property
    def identity(self):
        return self.package_id, self.ruleset_hash


@dataclass(frozen=True)
class RuleRegistry:
    packages: tuple[RulePackage, ...] = ()

    def __post_init__(self):
        if not isinstance(self.packages, tuple) or any(
            not isinstance(p, RulePackage) for p in self.packages
        ):
            raise ValueError("immutable rule packages required")
        identities, owners = set(), {}
        for package in self.packages:
            if package.identity in identities:
                raise ValueError("duplicate rule package identity")
            identities.add(package.identity)
            for rule in package.rule_ids:
                if rule in owners and owners[rule] != package.package_id:
                    raise ValueError("rule ID already belongs to another package")
                owners[rule] = package.package_id

    def with_package(self, package: RulePackage) -> RuleRegistry:
        return RuleRegistry((*self.packages, package))

    def resolve(self, package_id, ruleset_hash):
        for package in self.packages:
            if package.identity == (package_id, ruleset_hash):
                return package
        raise ProofFailure("invalid_proof", "unknown rule package or version hash")

    def replay(
        self, proof: dict, context: ProofContext, *, budget: _Budget | None = None
    ) -> ProofResult:
        if not isinstance(proof, dict):
            raise ProofFailure("invalid_proof", "certificate object required")
        package = self.resolve(proof.get("schema_version"), proof.get("ruleset_hash"))
        # Membership precedes dispatch: a permissive extension checker must not
        # accidentally accept another package's rule ID. Each checker still owns
        # the remaining schema, sources, authority and mathematical verification.
        nodes = proof.get("nodes")
        if not isinstance(nodes, list):
            raise ProofFailure("invalid_proof", "certificate nodes required")
        limits = budget.limits if budget is not None else context.limits
        if len(nodes) > limits.nodes:
            raise ProofFailure("proof_limit", "certificate node count limit")
        for node in nodes:
            if (
                not isinstance(node, dict)
                or node.get("rule_id") not in package.rule_ids
            ):
                raise ProofFailure(
                    "invalid_proof",
                    "proof rule belongs to a different or unknown package",
                )
        return package.checker(proof, context, budget=budget)
