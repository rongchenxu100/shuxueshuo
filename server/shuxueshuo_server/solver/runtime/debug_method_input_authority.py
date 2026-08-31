"""Explicit typed authority adapters for deterministic Method debugging."""

from __future__ import annotations

from dataclasses import dataclass

from shuxueshuo_server.solver.contracts import MethodInputSpec
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    MethodInputReadAuthority,
    MethodInputReadSource,
)


@dataclass(frozen=True)
class DebugMethodInputAuthorityAdapter:
    """Build debug authority only from a caller-selected typed source."""

    @staticmethod
    def build(
        *,
        method_id: str,
        invocation_id: str,
        scope_id: str,
        input_name: str,
        item_index: int,
        input_spec: MethodInputSpec,
        source: MethodInputReadSource,
    ) -> MethodInputReadAuthority:
        return MethodInputReadAuthority(
            method_id=method_id,
            invocation_id=invocation_id,
            input_name=input_name,
            item_index=item_index,
            view_mode=input_spec.view.mode,
            domain_type=input_spec.domain_type,
            runtime_type=input_spec.runtime_type,
            scope_id=scope_id,
            source=source,
        )


__all__ = ["DebugMethodInputAuthorityAdapter"]
