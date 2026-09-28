"""Immutable, solver-independent proof facts and conditional requirements.

These values carry evidence; constructing one does not authorize publication.
Runtime owns admission, Scope visibility, commit order and version validity.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass

from .expression_parser import parse_math_relation
from .proof_algebra import digest, from_node, names
from .proof_checker import fact_key


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class FactValidity:
    scope_id: str
    assumption_refs: tuple[str, ...] = ()
    definition_refs: tuple[str, ...] = ()
    state_version_refs: tuple[str, ...] = ()
    witness_ref: str | None = None

    def includes(self, other):
        return (
            set(other.assumption_refs) <= set(self.assumption_refs)
            and set(other.definition_refs) <= set(self.definition_refs)
            and set(other.state_version_refs) <= set(self.state_version_refs)
            and (other.witness_ref is None or other.witness_ref == self.witness_ref)
        )


@dataclass(frozen=True)
class VerifiedMathFact:
    relation: str
    symbol_bindings: tuple[tuple[str, str], ...]
    validity: FactValidity
    semantic_kind: str
    source: str
    proof_ref: str | None = None
    dependency_fact_refs: tuple[str, ...] = ()
    producer_call_id: str | None = None
    commit_id: str | None = None

    def __post_init__(self):
        import sympy as sp

        bindings = dict(self.symbol_bindings)
        parsed = parse_math_relation(
            self.relation, {name: sp.Symbol(name, real=True) for name in bindings}
        )
        used = names(from_node(parsed.ast))
        object.__setattr__(
            self,
            "symbol_bindings",
            tuple(sorted((name, bindings[name]) for name in used)),
        )

    @property
    def statement_key(self):
        # Deliberately structural: no cancellation or domain-erasing simplify.
        import sympy as sp

        parsed = parse_math_relation(
            self.relation, {n: sp.Symbol(n, real=True) for n, _ in self.symbol_bindings}
        )
        return digest((fact_key(from_node(parsed.ast)), self.symbol_bindings))

    @property
    def fact_id(self):
        return digest(asdict(self))

    def to_payload(self):
        return json.loads(
            canonical(
                {
                    **asdict(self),
                    "fact_id": self.fact_id,
                    "statement_key": self.statement_key,
                }
            )
        )


@dataclass(frozen=True)
class ConditionalRequirement:
    requirement_kind: str
    subject_ref: str
    required_relation: str
    validity: FactValidity
    characterization_proof_ref: str


@dataclass(frozen=True)
class AttainmentRequirement(ConditionalRequirement):
    bound_ref: str
    application_ref: str


@dataclass(frozen=True)
class FactKind:
    kind: str
    # Explicit authorization per producer capability, not inheritance from a
    # structurally similar kind. Trusted registrations, never payload callbacks.
    publishers: tuple[str, ...]
    unconditional: bool
    identity_key: Callable
    index_keys: Callable
    publishable: Callable


@dataclass(frozen=True)
class FactKindRegistry:
    kinds: tuple[FactKind, ...]

    def __post_init__(self):
        if len({k.kind for k in self.kinds}) != len(self.kinds):
            raise ValueError("duplicate semantic_kind")

    def with_kind(self, kind):
        return FactKindRegistry((*self.kinds, kind))

    def require(self, kind):
        found = next((k for k in self.kinds if k.kind == kind), None)
        if found is None:
            raise ValueError("unregistered semantic_kind: " + kind)
        return found

    def validate(self, fact, publisher):
        kind = self.require(fact.semantic_kind)
        if publisher not in kind.publishers or not kind.publishable(fact):
            raise ValueError("fact publication not authorized for semantic_kind")
        if not kind.unconditional and not (
            fact.validity.definition_refs
            or fact.validity.assumption_refs
            or fact.validity.witness_ref
        ):
            raise ValueError("conditional fact requires validity")
        kind.identity_key(fact)
        return kind.index_keys(fact)


def _identity(fact):
    return fact.statement_key


def _indices(fact):
    return (fact.statement_key, *(identity for _, identity in fact.symbol_bindings))


def _ordinary(fact):
    return fact.validity.witness_ref is None and not fact.validity.assumption_refs


def _definition(fact):
    return _ordinary(fact) and bool(fact.validity.definition_refs)


def default_fact_kinds(publishers):
    return FactKindRegistry(
        tuple(
            FactKind(kind, tuple(publishers), True, _identity, _indices, _ordinary)
            for kind in ("domain", "identity", "bound", "relation")
        )
        + (
            FactKind(
                "definition", tuple(publishers), False, _identity, _indices, _definition
            ),
        )
    )
