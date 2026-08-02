"""Shared invariants for runtime-grounded symbolic closure writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.strategy_models import (
    SymbolicClosureProvenance,
)


@dataclass(frozen=True)
class SymbolicClosureWriteAuditRecord:
    return_name: str | None
    runtime_type: str
    math_object_id: MathObjectId | None
    free_symbol_ids: tuple[MathObjectId, ...]
    provenance: SymbolicClosureProvenance | None


@dataclass(frozen=True)
class SymbolicClosureWriteAuditIssue:
    code: str
    message: str
    return_name: str | None = None
    details: dict[str, object] | None = None


def audit_symbolic_closure_writes(
    records: Sequence[SymbolicClosureWriteAuditRecord],
    *,
    expected_provenance: SymbolicClosureProvenance | None,
    expected_return_names: frozenset[str] = frozenset(),
) -> tuple[SymbolicClosureWriteAuditIssue, ...]:
    """Validate shared closure invariants without choosing stage behavior."""
    issues: list[SymbolicClosureWriteAuditIssue] = []
    if expected_provenance is None:
        issues.append(
            SymbolicClosureWriteAuditIssue(
                "planner.symbolic_closure_provenance_missing",
                "verified closure write has no runtime provenance",
            )
        )
        return tuple(issues)
    if expected_provenance.status != "unique":
        issues.append(
            SymbolicClosureWriteAuditIssue(
                "planner.symbolic_closure_provenance_drift",
                "verified closure write has non-unique runtime provenance",
                details={"status": expected_provenance.status},
            )
        )

    materialized_returns = {
        record.return_name
        for record in records
        if record.return_name is not None
    }
    missing = expected_return_names - materialized_returns
    if missing:
        issues.append(
            SymbolicClosureWriteAuditIssue(
                "planner.symbolic_closure_provenance_missing",
                "closure companion outputs are missing writes",
                details={"missing_returns": sorted(missing)},
            )
        )

    expected_signature = expected_provenance.semantic_signature()
    for record in records:
        actual = record.provenance
        if (
            actual is None
            or actual.semantic_signature() != expected_signature
        ):
            issues.append(
                SymbolicClosureWriteAuditIssue(
                    "planner.symbolic_closure_provenance_drift",
                    "closure companion outputs do not share provenance",
                    return_name=record.return_name,
                )
            )
            continue
        if (
            record.runtime_type == "ParameterValue"
            and record.math_object_id
            != expected_provenance.target_object_id
        ):
            issues.append(
                SymbolicClosureWriteAuditIssue(
                    "planner.contract_runtime_symbol_drift",
                    "ParameterValue identity differs from closure target",
                    return_name=record.return_name,
                )
            )
        if not set(record.free_symbol_ids) <= set(
            expected_provenance.residual_symbol_ids
        ):
            issues.append(
                SymbolicClosureWriteAuditIssue(
                    "planner.symbolic_closure_provenance_drift",
                    "runtime free Symbols exceed closure residual Symbols",
                    return_name=record.return_name,
                )
            )
    return tuple(issues)
