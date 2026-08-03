"""One-time typed identity migration for legacy PlannerStateContext payloads."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, TypeVar

from shuxueshuo_server.solver.runtime.functional_debug_aliases import (
    legacy_state_slot_aliases,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    StateVersionId,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    StateSemanticLineage,
)

_T = TypeVar("_T")


class LegacyContextIdentityMigrator:
    """Rebuild typed lineage exactly once while loading an old Context."""

    def __init__(self) -> None:
        self.identity_fallback_count = 0

    def migrate_lineage(
        self,
        lineage: StateSemanticLineage,
        *,
        object_ids_by_ref: Mapping[str, MathObjectId],
        versions_by_legacy_slot: Mapping[str, StateVersionId],
    ) -> StateSemanticLineage:
        migrated_roles: list[StateObjectRoleBinding] = []
        for role in lineage.object_roles:
            object_ids = _merge_typed_values(
                role.object_ids,
                _resolve_all(
                    role.object_refs,
                    object_ids_by_ref,
                    category=f"object role {role.role}",
                ),
            )
            source_version_ids = _merge_typed_values(
                role.source_version_ids,
                _resolve_all(
                    role.source_state_slot_ids,
                    versions_by_legacy_slot,
                    category=f"object role {role.role} source state",
                ),
            )
            self.identity_fallback_count += (
                len(object_ids) - len(role.object_ids)
                + len(source_version_ids) - len(role.source_version_ids)
            )
            migrated_roles.append(
                replace(
                    role,
                    object_ids=object_ids,
                    source_state_slot_ids=_canonical_source_slot_ids(
                        role.source_state_slot_ids,
                        versions_by_legacy_slot,
                    ),
                    source_version_ids=source_version_ids,
                )
            )
        source_version_ids = _merge_typed_values(
            lineage.source_version_ids,
            _resolve_all(
                lineage.source_state_slot_ids,
                versions_by_legacy_slot,
                category="lineage source state",
            ),
        )
        self.identity_fallback_count += (
            len(source_version_ids) - len(lineage.source_version_ids)
        )
        return replace(
            lineage,
            object_roles=tuple(migrated_roles),
            source_state_slot_ids=_canonical_source_slot_ids(
                lineage.source_state_slot_ids,
                versions_by_legacy_slot,
            ),
            source_version_ids=source_version_ids,
        )

    def normalize_source_slot_ids(
        self,
        legacy_slot_ids: tuple[str, ...],
        *,
        versions_by_legacy_slot: Mapping[str, StateVersionId],
    ) -> tuple[str, ...]:
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
            f"{category} is missing typed identity for {', '.join(missing)}"
        )
    return tuple(dict.fromkeys(typed_by_legacy[value] for value in legacy_values))


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


__all__ = ["LegacyContextIdentityMigrator"]
