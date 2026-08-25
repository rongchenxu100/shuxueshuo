"""Composable Function primitives for coupled-segment path minimum proofs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from shuxueshuo_server.solver.contracts import PredicatePublicationSpec

from ._common import *
from ._spec import MethodSpecSource, declare_input_views
from .coupled_segment_geometry import (
    CoupledSegmentGeometryError,
    coupled_segment_endpoint_residuals,
)


def _condition_payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_payload = getattr(value, "to_payload", None)
    payload = to_payload() if callable(to_payload) else None
    return payload if isinstance(payload, Mapping) else {}


def _condition_kind(value: Mapping[str, Any]) -> str:
    return str(value.get("kind") or value.get("type") or "")


def _point_identity(point: PointRef, *, arg_name: str) -> str:
    handle = point.definition.get("entity_handle")
    if not isinstance(handle, str) or not handle.startswith("point:"):
        handle = (
            f"point:{point.scope_id}:{point.name}"
            if point.scope_id and point.name
            else None
        )
    if not isinstance(handle, str) or not handle.startswith("point:"):
        raise method_input_invalid(
            "coupled path proof requires a typed Point identity",
            arg_name=arg_name,
            role=arg_name,
            expected={"identity": "canonical Point entity"},
            observed={"point": point.name, "identity": "missing"},
            repair_action="provide_visible_point_identity",
        )
    return handle


def _role_refs(
    condition: Mapping[str, Any],
    role: str,
) -> tuple[str, ...]:
    roles = condition.get("object_roles")
    if not isinstance(roles, Mapping):
        return ()
    raw = roles.get(role, ())
    values = raw if isinstance(raw, Sequence) and not isinstance(raw, str) else (raw,)
    return tuple(str(item) for item in values if isinstance(item, str))


def _require_role_set(
    condition: Mapping[str, Any],
    role: str,
    expected: frozenset[str],
    *,
    arg_name: str,
) -> None:
    observed = frozenset(_role_refs(condition, role))
    if observed != expected:
        raise method_input_invalid(
            "structured Condition roles do not match the selected entities",
            arg_name=arg_name,
            role=role,
            expected={"role": role, "entity_count": len(expected)},
            observed={"role": role, "entity_count": len(observed)},
            repair_action="select_condition_for_declared_entities",
        )


def _relation_scales(
    relation: Mapping[str, Any],
    *,
    first_pair: frozenset[str],
    second_pair: frozenset[str],
) -> tuple[sp.Expr, sp.Expr]:
    left_pair = frozenset(_role_refs(relation, "endpoint"))
    right_pair = frozenset(_role_refs(relation, "reference_endpoint"))
    scale = sp.simplify(sp.sympify(relation.get("scale", 1)))
    if left_pair == first_pair and right_pair == second_pair:
        return sp.Integer(1), scale
    if left_pair == second_pair and right_pair == first_pair:
        return scale, sp.Integer(1)
    raise method_input_invalid(
        "binding relation does not connect the selected moving segments",
        arg_name="binding_relation",
        role="coupled_segment_binding",
        expected={"first_pair_size": 2, "second_pair_size": 2},
        observed={
            "left_pair_size": len(left_pair),
            "right_pair_size": len(right_pair),
        },
        repair_action="select_binding_relation_for_moving_points",
    )


class ProveCoupledSegmentEndpointDistanceEqualityMethod:
    """Prove that a coupled moving segment equals one fixed-endpoint segment."""

    method_id = "prove_coupled_segment_endpoint_distance_equality"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        first_membership = _condition_payload(inputs["first_moving_membership"])
        second_membership = _condition_payload(inputs["second_moving_membership"])
        relation = _condition_payload(inputs["binding_relation"])
        if _condition_kind(first_membership) != "point_on_segment":
            raise method_input_invalid(
                "first moving membership must be a point_on_segment Condition",
                arg_name="first_moving_membership",
                expected={"condition_kind": "point_on_segment"},
                observed={"condition_kind": _condition_kind(first_membership)},
            )
        if _condition_kind(second_membership) != "point_on_segment":
            raise method_input_invalid(
                "second moving membership must be a point_on_segment Condition",
                arg_name="second_moving_membership",
                expected={"condition_kind": "point_on_segment"},
                observed={"condition_kind": _condition_kind(second_membership)},
            )
        if _condition_kind(relation) != "segment_length_relation":
            raise method_input_invalid(
                "binding relation must be a segment_length_relation Condition",
                arg_name="binding_relation",
                expected={"condition_kind": "segment_length_relation"},
                observed={"condition_kind": _condition_kind(relation)},
            )

        first_moving_ref = _point_identity(
            inputs["first_moving_point"],
            arg_name="first_moving_point",
        )
        second_moving_ref = _point_identity(
            inputs["second_moving_point"],
            arg_name="second_moving_point",
        )
        first_fixed_ref = _point_identity(
            inputs["first_track_fixed_endpoint_ref"],
            arg_name="first_track_fixed_endpoint",
        )
        joint_ref = _point_identity(
            inputs["joint_point_ref"],
            arg_name="joint_point",
        )
        second_fixed_ref = _point_identity(
            inputs["second_track_fixed_endpoint_ref"],
            arg_name="second_track_fixed_endpoint",
        )
        _require_role_set(
            first_membership,
            "point",
            frozenset({first_moving_ref}),
            arg_name="first_moving_membership",
        )
        _require_role_set(
            first_membership,
            "segment_endpoint",
            frozenset({first_fixed_ref, joint_ref}),
            arg_name="first_moving_membership",
        )
        _require_role_set(
            second_membership,
            "point",
            frozenset({second_moving_ref}),
            arg_name="second_moving_membership",
        )
        _require_role_set(
            second_membership,
            "segment_endpoint",
            frozenset({joint_ref, second_fixed_ref}),
            arg_name="second_moving_membership",
        )
        first_scale, second_scale = _relation_scales(
            relation,
            first_pair=frozenset({first_fixed_ref, first_moving_ref}),
            second_pair=frozenset({second_fixed_ref, second_moving_ref}),
        )
        try:
            binding_residual, replacement_residual = (
                coupled_segment_endpoint_residuals(
                    kernel,
                    first_track_fixed_endpoint=inputs[
                        "first_track_fixed_endpoint"
                    ],
                    joint_point=inputs["joint_point"],
                    second_track_fixed_endpoint=inputs[
                        "second_track_fixed_endpoint"
                    ],
                    first_relation_scale=first_scale,
                    second_relation_scale=second_scale,
                )
            )
        except CoupledSegmentGeometryError as exc:
            raise method_precondition_failed(
                str(exc),
                role="coupled_segment_tracks",
                expected={"tracks": "nondegenerate", "scales": "nonzero"},
                repair_action="select_nondegenerate_coupled_segments",
            ) from exc
        passed = binding_residual == 0 and replacement_residual == 0
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "verified": TypedValue("Boolean", passed, source=self.method_id)
            },
            checks=[
                _check(
                    "coupled_binding_relation_verified",
                    binding_residual == 0,
                    "the selected segment relation holds for the coupled parameterization",
                ),
                _check(
                    "coupled_endpoint_replacement_verified",
                    replacement_residual == 0,
                    "the moving segment equals the fixed-endpoint replacement segment",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "证明耦合线段可由固定端点替换",
                    "把两动点之间的距离改写为固定端点到第二动点的距离",
                    "由两点在线段上的位置关系和绑定长度关系作统一参数化。",
                    f"{inputs['first_moving_point'].name}{inputs['second_moving_point'].name}"
                    f"={inputs['first_track_fixed_endpoint_ref'].name}"
                    f"{inputs['second_moving_point'].name}",
                    "距离替换关系成立",
                )
            ],
        )


class RewritePathTargetByDistanceEqualityMethod:
    """Rewrite one two-term path target using an exact distance equality."""

    method_id = "rewrite_path_target_by_distance_equality"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        target = _condition_payload(inputs["path_minimum_target"])
        equality = _condition_payload(inputs["distance_equality"])
        if _condition_kind(target) != "path_minimum_target":
            raise method_input_invalid(
                "path rewrite requires a path_minimum_target Condition",
                arg_name="path_minimum_target",
                expected={"condition_kind": "path_minimum_target"},
                observed={"condition_kind": _condition_kind(target)},
            )
        if _condition_kind(equality) != "distance_equality":
            raise method_input_invalid(
                "path rewrite requires a verified distance_equality Condition",
                arg_name="distance_equality",
                expected={"condition_kind": "distance_equality"},
                observed={"condition_kind": _condition_kind(equality)},
            )
        replacement_ref = _point_identity(
            inputs["replacement_start_ref"],
            arg_name="replacement_start",
        )
        via_ref = _point_identity(inputs["via_ref"], arg_name="via")
        end_ref = _point_identity(inputs["end_ref"], arg_name="end")
        first_moving_refs = _role_refs(equality, "first_moving_point")
        second_moving_refs = _role_refs(equality, "second_moving_point")
        replacement_refs = _role_refs(
            equality,
            "first_track_fixed_endpoint",
        )
        if (
            len(first_moving_refs) != 1
            or second_moving_refs != (via_ref,)
            or replacement_refs != (replacement_ref,)
        ):
            raise method_input_invalid(
                "distance equality roles do not authorize this path rewrite",
                arg_name="distance_equality",
                role="endpoint_replacement",
                expected={"via": "selected via point", "replacement": "selected start"},
                observed={
                    "first_moving_count": len(first_moving_refs),
                    "second_moving_count": len(second_moving_refs),
                    "replacement_count": len(replacement_refs),
                },
                repair_action="select_matching_distance_equality",
            )
        terms = target.get("terms")
        path_terms = tuple(
            frozenset(str(item) for item in term)
            for term in terms
            if isinstance(term, Sequence)
            and not isinstance(term, str)
            and len(term) == 2
        ) if isinstance(terms, Sequence) and not isinstance(terms, str) else ()
        expected_terms = {
            frozenset({first_moving_refs[0], via_ref}),
            frozenset({end_ref, via_ref}),
        }
        if len(path_terms) != 2 or set(path_terms) != expected_terms:
            raise method_input_invalid(
                "distance equality does not rewrite the selected path target",
                arg_name="path_minimum_target",
                role="two_segment_path",
                expected={"term_count": 2, "shared_point": "via"},
                observed={"term_count": len(path_terms)},
                repair_action="select_matching_path_target",
            )
        expression = sp.simplify(
            kernel.distance(inputs["replacement_start"], inputs["via"])
            + kernel.distance(inputs["via"], inputs["end"])
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "expression": TypedValue(
                    "Expression",
                    expression,
                    source=self.method_id,
                )
            },
            checks=[
                _check(
                    "path_target_rewritten_by_verified_distance_equality",
                    True,
                    "the exact distance equality authorizes the two-term path rewrite",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "按等长关系改写路径目标",
                    "把原两段路径改写为同一动点上的折线路径",
                    "只使用已经发布的距离等式替换对应线段。",
                    str(target.get("path") or "two-segment path"),
                    kernel.sstr(expression),
                )
            ],
        )


PROVE_COUPLED_SEGMENT_ENDPOINT_DISTANCE_EQUALITY_SPEC = MethodSpecSource(
    method_cls=ProveCoupledSegmentEndpointDistanceEqualityMethod,
    title="证明耦合线段端点替换等长",
    summary=(
        "由两个动点的线段归属、绑定长度关系和三个位形点的精确状态，"
        "证明两动点线段可替换为已有固定端点到第二动点的等长线段。"
    ),
    solves=("prove_coupled_segment_endpoint_distance_equality",),
    inputs={
        "first_moving_membership": {"type": "Condition", "required": True},
        "second_moving_membership": {"type": "Condition", "required": True},
        "binding_relation": {"type": "Condition", "required": True},
        "first_moving_point": {"type": "PointRef", "required": True},
        "second_moving_point": {"type": "PointRef", "required": True},
        "first_track_fixed_endpoint": {"type": "Point", "required": True},
        "first_track_fixed_endpoint_ref": {"type": "PointRef", "required": True},
        "joint_point": {"type": "Point", "required": True},
        "joint_point_ref": {"type": "PointRef", "required": True},
        "second_track_fixed_endpoint": {"type": "Point", "required": True},
        "second_track_fixed_endpoint_ref": {"type": "PointRef", "required": True},
    },
    input_views=declare_input_views(
        immutable_value=(
            "first_moving_membership",
            "second_moving_membership",
            "binding_relation",
        ),
        identity=(
            "first_moving_point",
            "second_moving_point",
            "first_track_fixed_endpoint_ref",
            "joint_point_ref",
            "second_track_fixed_endpoint_ref",
        ),
        latest_state=(
            "first_track_fixed_endpoint",
            "joint_point",
            "second_track_fixed_endpoint",
        ),
    ),
    outputs={"verified": "Boolean"},
    predicate_publications=(
        PredicatePublicationSpec(
            "verified",
            "distance_equality",
            (
                "first_moving_point",
                "second_moving_point",
                "first_track_fixed_endpoint",
            ),
        ),
    ),
    preconditions=(
        "两个动点分别位于共享端点的两条非退化线段上",
        "绑定关系分别连接第一固定端点与第一动点、第二固定端点与第二动点",
    ),
    postconditions=("发布固定端点替换所需的精确 distance_equality Condition",),
)


REWRITE_PATH_TARGET_BY_DISTANCE_EQUALITY_SPEC = MethodSpecSource(
    method_cls=RewritePathTargetByDistanceEqualityMethod,
    title="按距离等式改写两段路径目标",
    summary=(
        "消费结构化两段路径目标和已验证的距离等式，输出使用替换端点后的标准Expression。"
    ),
    solves=("rewrite_path_target_by_distance_equality",),
    inputs={
        "path_minimum_target": {"type": "Condition", "required": True},
        "distance_equality": {"type": "Condition", "required": True},
        "replacement_start": {"type": "Point", "required": True},
        "replacement_start_ref": {"type": "PointRef", "required": True},
        "via": {"type": "Point", "required": True},
        "via_ref": {"type": "PointRef", "required": True},
        "end": {"type": "Point", "required": True},
        "end_ref": {"type": "PointRef", "required": True},
    },
    input_views=declare_input_views(
        immutable_value=("path_minimum_target", "distance_equality"),
        latest_state=("replacement_start", "via", "end"),
        identity=("replacement_start_ref", "via_ref", "end_ref"),
    ),
    outputs={"expression": "Expression"},
    preconditions=(
        "path_minimum_target包含恰好两段且共享via",
        "distance_equality的对象角色与被替换线段完全一致",
    ),
    postconditions=("输出替换后的两段距离和Expression，不直接声明其为最小值",),
)


COUPLED_SEGMENT_PATH_METHODS = (
    ProveCoupledSegmentEndpointDistanceEqualityMethod,
    RewritePathTargetByDistanceEqualityMethod,
)
COUPLED_SEGMENT_PATH_SPECS = (
    PROVE_COUPLED_SEGMENT_ENDPOINT_DISTANCE_EQUALITY_SPEC,
    REWRITE_PATH_TARGET_BY_DISTANCE_EQUALITY_SPEC,
)


__all__ = [
    "COUPLED_SEGMENT_PATH_METHODS",
    "COUPLED_SEGMENT_PATH_SPECS",
    "ProveCoupledSegmentEndpointDistanceEqualityMethod",
    "RewritePathTargetByDistanceEqualityMethod",
]
