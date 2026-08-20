"""Resolve one Method input from its declared domain-to-runtime view contract."""

from __future__ import annotations

from dataclasses import dataclass

from shuxueshuo_server.solver.contracts import MethodInputSpec, PointRef, TypedValue
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
    method_input_state_unavailable,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CompilerSelectorReadSource,
    EntityIdentityReadSource,
    MethodInputReadAuthority,
)
from shuxueshuo_server.solver.runtime.models import ContextPath
from shuxueshuo_server.solver.runtime.runtime_type_declarations import (
    split_runtime_types,
)


@dataclass(frozen=True)
class ResolvedMethodInputView:
    selected_path: str
    typed_value: TypedValue
    value: object


class MethodInputViewResolver:
    """Materialize an authorized input path using the Method's declared view."""

    def resolve(
        self,
        context: RuntimeContext,
        *,
        method_id: str,
        invocation_id: str,
        scope_id: str,
        input_name: str,
        input_spec: MethodInputSpec,
        raw_path: str,
        item_index: int = 0,
        authority: MethodInputReadAuthority | None = None,
        require_authority: bool = False,
    ) -> ResolvedMethodInputView:
        if authority is None:
            if require_authority:
                raise StatelessMethodError(
                    "planner.method_input_view_authority_missing",
                    "production Method input has no typed read authority",
                    category="configuration",
                    retryability="configuration",
                    method_id=method_id,
                    scope_id=scope_id,
                    step_id=invocation_id,
                    arg_name=input_name,
                    item_index=item_index,
                    expected={
                        "domain_type": input_spec.domain_type,
                        "runtime_type": input_spec.runtime_type,
                        "view": input_spec.view.mode,
                    },
                    repair_action="fix_runtime_contract",
                )
            authority = debug_method_input_read_authority(
                context,
                method_id=method_id,
                invocation_id=invocation_id,
                scope_id=scope_id,
                input_name=input_name,
                item_index=item_index,
                input_spec=input_spec,
                raw_path=raw_path,
            )
        try:
            authority.verify(
                method_id=method_id,
                invocation_id=invocation_id,
                input_name=input_name,
                item_index=item_index,
                view_mode=input_spec.view.mode,
                domain_type=input_spec.domain_type,
                runtime_type=input_spec.runtime_type,
                scope_id=scope_id,
                raw_path=(raw_path if require_authority else authority.runtime_path),
                production=require_authority,
            )
        except ValueError as exc:
            raise StatelessMethodError(
                "planner.method_input_view_authority_drift",
                "Method input read authority differs from the invocation contract: "
                f"{exc}",
                category="configuration",
                retryability="configuration",
                method_id=method_id,
                scope_id=scope_id,
                step_id=invocation_id,
                arg_name=input_name,
                item_index=item_index,
                expected=authority.authority_payload(),
                observed={"raw_path": raw_path},
                repair_action="fix_runtime_contract",
            ) from exc
        selected_path = authority.runtime_path
        try:
            typed_value = context.read_path(
                selected_path,
                from_scope_id=scope_id,
                expected_type=expected_runtime_type_for_view(input_spec),
            )
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            raise method_input_state_unavailable(
                "declared Method input view is unavailable in the current scope",
                method_id=method_id,
                scope_id=scope_id,
                step_id=invocation_id,
                arg_name=input_name,
                role=input_name,
                internal_ref=raw_path,
                expected={
                    "domain_type": input_spec.domain_type,
                    "runtime_type": input_spec.runtime_type,
                    "view": input_spec.view.mode,
                },
                observed={"error": type(exc).__name__},
                repair_action=(
                    "provide_visible_entity_state"
                    if input_spec.view.mode == "latest_state"
                    else "provide_compatible_math_entity"
                ),
            ) from exc

        value = typed_value.value
        if input_spec.view.mode == "identity" and input_spec.domain_type == "Point":
            value = self._point_identity(
                raw_path=selected_path,
                typed_value=typed_value,
                authority=authority,
            )
        return ResolvedMethodInputView(selected_path, typed_value, value)

    @staticmethod
    def _point_identity(
        *,
        raw_path: str,
        typed_value: TypedValue,
        authority: MethodInputReadAuthority,
    ) -> object:
        if typed_value.type == "PointRef":
            point_ref = typed_value.value
        elif typed_value.type == "Point":
            point_ref = (
                _point_ref_from_entity_handle(
                    authority.source.entity_handle,
                    raw_path=raw_path,
                )
                if isinstance(authority.source, EntityIdentityReadSource)
                else _point_ref_from_path(raw_path)
            )
        else:
            return typed_value.value
        if not isinstance(point_ref, PointRef):
            return typed_value.value
        return point_ref


def debug_method_input_read_authority(
    context: RuntimeContext,
    *,
    method_id: str,
    invocation_id: str,
    scope_id: str,
    input_name: str,
    item_index: int,
    input_spec: MethodInputSpec,
    raw_path: str,
) -> MethodInputReadAuthority:
    """Explicit compatibility adapter for deterministic Method/debug tests."""

    selected_path = raw_path
    if input_spec.view.mode == "latest_state" and input_spec.domain_type == "Point":
        try:
            typed_value = context.read_path(raw_path, from_scope_id=scope_id)
        except (KeyError, PermissionError, TypeError, ValueError):
            typed_value = None
        point_ref = typed_value.value if typed_value is not None else None
        if typed_value is not None and typed_value.type == "PointRef" and isinstance(
            point_ref,
            PointRef,
        ):
            selected_path = context.find_visible_path(
                "points",
                point_ref.name,
                from_scope_id=scope_id,
            ) or raw_path
    entity_handle = (
        _debug_entity_handle(
            context,
            raw_path=selected_path,
            scope_id=scope_id,
            input_spec=input_spec,
        )
        if input_spec.view.mode == "identity"
        else None
    )
    source = (
        EntityIdentityReadSource(
            entity_handle=entity_handle,
            runtime_path=selected_path,
        )
        if entity_handle is not None
        else CompilerSelectorReadSource(
            selector_id=f"debug:{input_name}",
            runtime_path=selected_path,
        )
    )
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


def expected_runtime_type_for_view(input_spec: MethodInputSpec) -> str:
    if input_spec.view.mode == "identity" and input_spec.domain_type == "Point":
        return "PointRef|Point"
    return input_spec.runtime_type


def input_view_accepts_runtime_type(
    input_spec: MethodInputSpec,
    actual_type: str,
) -> bool:
    expected = set(split_runtime_types(expected_runtime_type_for_view(input_spec)))
    return actual_type in expected or (
        input_spec.runtime_type == "Expression" and actual_type == "Parabola"
    )


def _point_ref_from_path(raw_path: str) -> PointRef | None:
    try:
        path = ContextPath.parse(raw_path)
    except ValueError:
        return None
    if path.container not in {"points", "object_refs"}:
        return None
    return PointRef(name=path.key, path=raw_path, scope_id=path.scope_id)


def _debug_entity_handle(
    context: RuntimeContext,
    *,
    raw_path: str,
    scope_id: str,
    input_spec: MethodInputSpec,
) -> str | None:
    """Build a semantic debug handle without treating a runtime path as one."""

    try:
        typed_value = context.read_path(raw_path, from_scope_id=scope_id)
    except (KeyError, PermissionError, TypeError, ValueError):
        typed_value = None
    point_ref = typed_value.value if typed_value is not None else None
    if (
        typed_value is not None
        and typed_value.type == "PointRef"
        and isinstance(point_ref, PointRef)
    ):
        return f"point:{point_ref.scope_id}:{point_ref.name}"
    try:
        path = ContextPath.parse(raw_path)
    except ValueError:
        return None
    object_kind = input_spec.view.object_kind or {
        "Point": "point",
        "QuadraticFunction": "function",
        "Function": "function",
        "Line": "line",
        "Symbol": "symbol",
    }.get(input_spec.domain_type)
    if object_kind is None or path.scope_type == "step":
        return None
    return f"{object_kind}:{path.scope_id}:{path.key}"


def _point_ref_from_entity_handle(
    handle: str,
    *,
    raw_path: str,
) -> PointRef | None:
    parts = handle.split(":", 2)
    if len(parts) != 3 or parts[0] != "point":
        return None
    return PointRef(
        name=parts[2],
        path=raw_path,
        scope_id=parts[1],
    )


__all__ = [
    "MethodInputViewResolver",
    "ResolvedMethodInputView",
    "debug_method_input_read_authority",
    "expected_runtime_type_for_view",
    "input_view_accepts_runtime_type",
]
