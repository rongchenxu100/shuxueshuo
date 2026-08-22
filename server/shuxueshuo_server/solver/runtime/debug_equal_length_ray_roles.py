"""Debug-only role provider for the standalone equal-length ray Method."""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
)
from shuxueshuo_server.solver.runtime.binding_rules import _point_output_handle
from shuxueshuo_server.solver.runtime.equal_length_ray_roles import (
    EqualLengthRayRoleError,
    build_equal_length_ray_role_candidates,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    FunctionalCompileStepView,
    StrategyDraftValidationError,
)


class DebugEqualLengthRayRoleProvider:
    """Resolve one standalone debug invocation from structured facts."""

    @staticmethod
    def resolve(
        step: FunctionalCompileStepView,
        index: CanonicalRuntimeBindingIndex,
    ) -> dict[str, str]:
        fact_types = (
            "point_on_ray",
            "point_on_segment",
            "equal_length_condition",
            "path_minimum_target",
        )
        facts = {
            fact_type: index.fact_handle_by_type(fact_type, step=step)
            for fact_type in fact_types
        }
        visible_scopes = set(index.handle_registry.ancestor_scopes(step.scope_id))
        point_handles = tuple(
            sorted(
                handle
                for handle in index.handle_registry.entity_handles
                if handle.startswith("point:")
                and index.handle_registry.handle_valid_scopes.get(handle)
                in visible_scopes
            )
        )
        by_name: dict[str, list[str]] = {}
        for handle in point_handles:
            payload = index.handle_registry.entity_payloads.get(handle, {})
            name = str(payload.get("name", "")).strip() or handle.rsplit(":", 1)[-1]
            by_name.setdefault(name, []).append(handle)
        point_names = {
            name: handles[0]
            for name, handles in by_name.items()
            if len(handles) == 1
        }
        try:
            candidates = build_equal_length_ray_role_candidates(
                ray_facts=(
                    (facts["point_on_ray"], index.fact_payload(facts["point_on_ray"])),
                ),
                segment_facts=(
                    (
                        facts["point_on_segment"],
                        index.fact_payload(facts["point_on_segment"]),
                    ),
                ),
                equal_facts=(
                    (
                        facts["equal_length_condition"],
                        index.fact_payload(facts["equal_length_condition"]),
                    ),
                ),
                target_facts=(
                    (
                        facts["path_minimum_target"],
                        index.fact_payload(facts["path_minimum_target"]),
                    ),
                ),
                entity_payload=index.entity_payload,
                visible_point_handles=point_handles,
                resolve_point_name=lambda name: point_names[name],
            )
        except (EqualLengthRayRoleError, KeyError) as exc:
            raise StrategyDraftValidationError(
                f"planner.macro_contract_invalid: {exc}"
            ) from exc
        if len(candidates) != 1:
            raise StrategyDraftValidationError(
                "planner.macro_contract_invalid: debug equal-length binding "
                f"requires one role candidate, got {len(candidates)}"
            )
        return {
            **candidates[0].roles.to_payload(),
            "target": _point_output_handle(step, index),
        }


__all__ = ["DebugEqualLengthRayRoleProvider"]
