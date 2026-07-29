"""Compatibility-only projection from typed Functional state identity.

The Functional authoritative pipeline must decide identity, versions, scope,
and writer ownership before calling this adapter.  The adapter only emits the
legacy strings still consumed by StepIntent, compiler, and debug payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, TypeVar

from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    StateSemanticLineage,
)

_T = TypeVar("_T")


@dataclass
class FunctionalLegacyProjectionAdapter:
    """Project typed identities without acquiring semantic authority."""

    projection_count: int = 0
    identity_fallback_count: int = 0

    def state_slot_id(self, slot_id: StateSlotId) -> str:
        self.projection_count += 1
        return legacy_state_slot_aliases(slot_id)[0]

    def call_local_value_id(
        self,
        *,
        scope_id: str,
        call_id: str,
        return_name: str,
    ) -> str:
        self.projection_count += 1
        return f"functional:{scope_id}:{call_id}:{return_name}"

    def migrate_lineage(
        self,
        lineage: StateSemanticLineage,
        *,
        object_ids_by_ref: Mapping[str, MathObjectId],
        versions_by_legacy_slot: Mapping[str, StateVersionId],
    ) -> StateSemanticLineage:
        """Rebuild typed lineage once at the legacy Context load boundary."""

        migrated_roles: list[StateObjectRoleBinding] = []
        for role in lineage.object_roles:
            mapped_object_ids = _resolve_all(
                role.object_refs,
                object_ids_by_ref,
                category=f"object role {role.role}",
            )
            mapped_versions = _resolve_all(
                role.source_state_slot_ids,
                versions_by_legacy_slot,
                category=f"object role {role.role} source state",
            )
            object_ids = _merge_typed_values(
                role.object_ids,
                mapped_object_ids,
            )
            source_version_ids = _merge_typed_values(
                role.source_version_ids,
                mapped_versions,
            )
            self.identity_fallback_count += (
                len(object_ids) - len(role.object_ids)
                + len(source_version_ids) - len(role.source_version_ids)
            )
            migrated_roles.append(
                StateObjectRoleBinding(
                    role=role.role,
                    object_refs=role.object_refs,
                    source_state_slot_ids=_canonical_source_slot_ids(
                        role.source_state_slot_ids,
                        versions_by_legacy_slot,
                    ),
                    source_handles=role.source_handles,
                    object_ids=object_ids,
                source_version_ids=source_version_ids,
                state_requirement=role.state_requirement,
            )
            )
        mapped_lineage_versions = _resolve_all(
            lineage.source_state_slot_ids,
            versions_by_legacy_slot,
            category="lineage source state",
        )
        migrated_versions = _merge_typed_values(
            lineage.source_version_ids,
            mapped_lineage_versions,
        )
        self.identity_fallback_count += (
            len(migrated_versions) - len(lineage.source_version_ids)
        )
        return replace(
            lineage,
            object_roles=tuple(migrated_roles),
            source_state_slot_ids=_canonical_source_slot_ids(
                lineage.source_state_slot_ids,
                versions_by_legacy_slot,
            ),
            source_version_ids=migrated_versions,
        )

    def normalize_source_slot_ids(
        self,
        legacy_slot_ids: tuple[str, ...],
        *,
        versions_by_legacy_slot: Mapping[str, StateVersionId],
    ) -> tuple[str, ...]:
        """Normalize legacy dependency strings at the Context boundary."""

        return _canonical_source_slot_ids(
            legacy_slot_ids,
            versions_by_legacy_slot,
        )


def _resolve_all(
    legacy_values: tuple[str, ...],
    typed_by_legacy: Mapping[str, _T],
    *,
    category: str,
) -> tuple[_T, ...]:
    missing = tuple(
        value for value in legacy_values if value not in typed_by_legacy
    )
    if missing:
        raise ValueError(
            "planner_configuration_error: "
            "planner.context_identity_migration_failed: "
            f"{category} is missing typed identity for "
            f"{', '.join(missing)}"
        )
    return tuple(
        dict.fromkeys(typed_by_legacy[value] for value in legacy_values)
    )


def _merge_typed_values(
    existing: tuple[_T, ...],
    migrated: tuple[_T, ...],
) -> tuple[_T, ...]:
    return tuple(dict.fromkeys((*existing, *migrated)))


def _canonical_source_slot_ids(
    legacy_slot_ids: tuple[str, ...],
    versions_by_legacy_slot: Mapping[str, StateVersionId],
) -> tuple[str, ...]:
    versions = _resolve_all(
        legacy_slot_ids,
        versions_by_legacy_slot,
        category="lineage source state",
    )
    return tuple(
        dict.fromkeys(
            legacy_state_slot_aliases(version_id.slot_id)[0]
            for version_id in versions
        )
    )


def legacy_state_slot_aliases(slot_id: StateSlotId) -> tuple[str, ...]:
    """Return compatibility spellings for one typed slot."""

    prefix = (
        f"{slot_id.logical_key.object_id.value}."
        f"{slot_id.logical_key.state_kind}@{slot_id.storage_scope_id}"
    )
    return (
        f"{prefix}:{slot_id.logical_key.runtime_type}",
        prefix,
    )


__all__ = [
    "FunctionalLegacyProjectionAdapter",
    "legacy_state_slot_aliases",
]
