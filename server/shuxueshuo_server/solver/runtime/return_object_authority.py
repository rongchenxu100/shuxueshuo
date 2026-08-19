"""Shared authority for assigning public returns to named Math objects."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ReturnObjectAuthorityResolution:
    """One precedence-selected set of named object targets."""

    target_refs: frozenset[str]
    basis: str | None

    @property
    def unique_target_ref(self) -> str | None:
        return next(iter(self.target_refs)) if len(self.target_refs) == 1 else None


class ReturnObjectAuthorityResolver:
    """Resolve a return's named object without inventing mathematical identity.

    Callers may obtain candidates from different representations (raw Plan wire
    or typed reconciliation), but they must use this single precedence rule.
    The first non-empty authority source wins; ambiguity remains ambiguity.
    """

    _PRECEDENCE = (
        "explicit_output_target",
        "goal_answer_target",
        "identity_constraint",
        "declared_identity_arg",
        "compiler_selector",
    )

    @classmethod
    def resolve(
        cls,
        *,
        explicit_output_targets: Iterable[str] = (),
        goal_answer_targets: Iterable[str] = (),
        identity_constraint_targets: Iterable[str] = (),
        declared_identity_targets: Iterable[str] = (),
        compiler_selector_targets: Iterable[str] = (),
    ) -> ReturnObjectAuthorityResolution:
        candidates: Mapping[str, Iterable[str]] = {
            "explicit_output_target": explicit_output_targets,
            "goal_answer_target": goal_answer_targets,
            "identity_constraint": identity_constraint_targets,
            "declared_identity_arg": declared_identity_targets,
            "compiler_selector": compiler_selector_targets,
        }
        for basis in cls._PRECEDENCE:
            refs = frozenset(item for item in candidates[basis] if item)
            if refs:
                return ReturnObjectAuthorityResolution(refs, basis)
        return ReturnObjectAuthorityResolution(frozenset(), None)


@dataclass(frozen=True)
class ReturnRoleAuthorityResolution:
    """A deterministic one-to-one mapping from authored to public roles."""

    assignments: Mapping[str, str]
    candidates: Mapping[str, tuple[str, ...]]
    solution_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "assignments",
            MappingProxyType(dict(sorted(self.assignments.items()))),
        )
        object.__setattr__(
            self,
            "candidates",
            MappingProxyType(
                {
                    key: tuple(sorted(values))
                    for key, values in sorted(self.candidates.items())
                }
            ),
        )

    @property
    def unique(self) -> bool:
        return self.solution_count == 1


class ReturnRoleAuthorityResolver:
    """Resolve misspelled public return roles from semantic constraints.

    Callers construct each candidate set from typed capability evidence. This
    resolver deliberately knows nothing about spelling similarity or wire
    order; it accepts a repair only when the complete bipartite assignment has
    exactly one solution.
    """

    @classmethod
    def resolve(
        cls,
        candidates: Mapping[str, Iterable[str]],
    ) -> ReturnRoleAuthorityResolution:
        normalized = {
            str(authored): tuple(sorted({str(item) for item in roles if item}))
            for authored, roles in candidates.items()
        }
        if not normalized or any(not roles for roles in normalized.values()):
            return ReturnRoleAuthorityResolution({}, normalized, 0)

        authored_roles = tuple(
            sorted(normalized, key=lambda item: (len(normalized[item]), item))
        )
        solutions: list[dict[str, str]] = []

        def visit(
            index: int,
            used: frozenset[str],
            assignment: dict[str, str],
        ) -> None:
            if len(solutions) >= 2:
                return
            if index == len(authored_roles):
                solutions.append(dict(assignment))
                return
            authored = authored_roles[index]
            for public_role in normalized[authored]:
                if public_role in used:
                    continue
                assignment[authored] = public_role
                visit(index + 1, used | {public_role}, assignment)
                assignment.pop(authored, None)

        visit(0, frozenset(), {})
        return ReturnRoleAuthorityResolution(
            solutions[0] if len(solutions) == 1 else {},
            normalized,
            len(solutions),
        )


__all__ = [
    "ReturnObjectAuthorityResolution",
    "ReturnObjectAuthorityResolver",
    "ReturnRoleAuthorityResolution",
    "ReturnRoleAuthorityResolver",
]
