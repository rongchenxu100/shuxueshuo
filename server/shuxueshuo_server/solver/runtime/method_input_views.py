"""Resolve one Method input from its declared domain-to-runtime view contract."""

from __future__ import annotations

from dataclasses import dataclass, replace

from shuxueshuo_server.solver.contracts import MethodInputSpec, PointRef, TypedValue
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    method_input_state_unavailable,
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
    ) -> ResolvedMethodInputView:
        selected_path = raw_path
        if input_spec.view.mode == "latest_state" and input_spec.domain_type == "Point":
            selected_path = self._latest_point_path(
                context,
                raw_path=raw_path,
                scope_id=scope_id,
            )
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
                context,
                raw_path=selected_path,
                typed_value=typed_value,
                scope_id=scope_id,
            )
        return ResolvedMethodInputView(selected_path, typed_value, value)

    @staticmethod
    def _latest_point_path(
        context: RuntimeContext,
        *,
        raw_path: str,
        scope_id: str,
    ) -> str:
        try:
            typed_value = context.read_path(raw_path, from_scope_id=scope_id)
        except (KeyError, PermissionError, TypeError, ValueError):
            return raw_path
        point_ref = typed_value.value
        if typed_value.type != "PointRef" or not isinstance(point_ref, PointRef):
            return raw_path
        return context.find_visible_path(
            "points",
            point_ref.name,
            from_scope_id=scope_id,
        ) or raw_path

    @staticmethod
    def _point_identity(
        context: RuntimeContext,
        *,
        raw_path: str,
        typed_value: TypedValue,
        scope_id: str,
    ) -> object:
        if typed_value.type == "PointRef":
            point_ref = typed_value.value
        elif typed_value.type == "Point":
            point_ref = _point_ref_from_path(raw_path)
        else:
            return typed_value.value
        if not isinstance(point_ref, PointRef):
            return typed_value.value
        definition = dict(point_ref.definition)
        visible = context.find_visible_path(
            "points",
            point_ref.name,
            from_scope_id=scope_id,
        )
        if visible is not None:
            try:
                coordinate = context.read_path(
                    visible,
                    from_scope_id=scope_id,
                    expected_type="Point|PointRef",
                )
                if coordinate.type == "Point":
                    definition["existing_coordinate"] = coordinate.value
            except (KeyError, PermissionError, TypeError, ValueError):
                pass
        return replace(point_ref, definition=definition)


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


__all__ = [
    "MethodInputViewResolver",
    "ResolvedMethodInputView",
    "expected_runtime_type_for_view",
    "input_view_accepts_runtime_type",
]
