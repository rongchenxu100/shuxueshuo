"""Shared proof values and bounded accounting; no checker or search imports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

import sympy as sp

from .expression_parser import ParsedMath
from .proof_algebra import ProofFailure


@dataclass(frozen=True)
class ProofLimits:
    premises: int = 16
    variables: int = 4
    radicals: int = 4
    equations: int = 4
    polynomial_degree: int = 12
    polynomial_terms: int = 128
    coefficient_bits: int = 4096
    reductions: int = 256
    depth: int = 32
    nodes: int = 512
    attempts: int = 512
    branches: int = 8
    algebraic_degree: int = 16
    refinements: int = 128


@dataclass(frozen=True)
class ProofContext:
    symbols: Mapping[str, sp.Symbol]
    premises: Mapping[str, ParsedMath] = field(default_factory=dict)
    limits: ProofLimits = field(default_factory=ProofLimits)
    scope_id: str = "authoring"


@dataclass(frozen=True)
class ProofNode:
    node_id: str
    rule_id: str
    conclusion: tuple
    children: tuple[str, ...]
    premises: tuple[str, ...]
    input_nodes: tuple[dict, ...]
    certificate: dict

    def to_payload(self):
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True)
class ProofResult:
    status: str
    code: str | None = None
    diagnostic: str | None = None
    proof: dict | None = None
    branches: tuple[dict, ...] = ()

    def to_payload(self):
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


@dataclass(frozen=True)
class Witness:
    assignments: Mapping[str, ParsedMath]
    # A single real parameter on a rational closed interval. This is a
    # candidate domain, validated by the witness rule, not a new source fact.
    parameter: str | None = None
    interval: tuple[str, str] | None = None


class _Budget:
    def __init__(self, limits):
        self.limits, self.counts = limits, {}
        # Exact algebra caches belong to this bounded request, including its
        # successive verified rows. They never cache proof authorization.
        self.gcd_cache, self.equation_divisors = {}, {}
        self.proven_goals = {}
        self.proof_nodes = set()
        if not isinstance(limits, ProofLimits) or any(
            type(v) is not int or v <= 0 for v in asdict(limits).values()
        ):
            raise ProofFailure(
                "invalid_input", "positive integer proof limits required"
            )

    def use(self, field, amount=1):
        self.counts[field] = self.counts.get(field, 0) + amount
        if self.counts[field] > getattr(self.limits, field):
            raise ProofFailure("proof_limit", f"{field} budget exhausted")
