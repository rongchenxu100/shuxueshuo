"""Typed semantic catalog records exposed to Functional planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    StateVersionId,
)


@dataclass(frozen=True)
class SemanticReadCatalogItem:
    """Internal semantic catalog item with exact typed identity."""

    handle: str
    kind: str
    ref: str
    scope: str
    valid_scope: str
    value_type: str | None = None
    source_step_id: str | None = None
    description: str = ""
    state_slot_id: str | None = None
    condition_id: str | None = None
    source_context_id: str | None = None
    prompt_visible: bool = True
    math_object_id: MathObjectId | None = None
    state_version_id: StateVersionId | None = None

    def to_prompt_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ref": self.ref,
            "kind": self.kind,
            "scope": self.scope,
            "valid_scope": self.valid_scope,
        }
        if self.value_type is not None:
            payload["value_type"] = self.value_type
        if self.source_step_id is not None:
            payload["from_step"] = self.source_step_id
        if self.description:
            payload["description"] = self.description
        return payload


class ContextSemanticReadSource(Protocol):
    """Planner context projection required by Functional prompt building."""

    def semantic_read_catalog(
        self,
        scope_id: str | None = None,
    ) -> tuple[SemanticReadCatalogItem, ...]: ...

    def semantic_read_catalog_payload(self) -> dict[str, Any]: ...


__all__ = ["ContextSemanticReadSource", "SemanticReadCatalogItem"]
