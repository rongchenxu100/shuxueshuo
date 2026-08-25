"""Generic construction and verification primitives for path subplans."""

from __future__ import annotations

from collections.abc import Mapping

from shuxueshuo_server.solver.contracts import PredicatePublicationSpec

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


class ConstructPointOnRayAtReferenceDistanceMethod:
    """Construct a point on a ray with a prescribed reference distance."""

    method_id = "construct_point_on_ray_at_reference_distance"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        anchor: Point = inputs["anchor"]
        ray_point: Point = inputs["ray_point"]
        reference_point: Point = inputs["reference_point"]
        target: PointRef = inputs["target"]
        direction = (
            sp.simplify(ray_point[0] - anchor[0]),
            sp.simplify(ray_point[1] - anchor[1]),
        )
        direction_length = sp.simplify(kernel.distance(anchor, ray_point))
        if direction_length == 0:
            raise method_precondition_failed(
                "ray construction requires a nonzero direction",
                arg_name="ray_point",
                role="ray_direction_point",
                expected={"distance_from_anchor": "nonzero"},
                observed={"distance_from_anchor": 0},
                repair_action="provide_distinct_ray_points",
            )
        scale = sp.simplify(
            kernel.distance(anchor, reference_point) / direction_length
        )
        point = (
            sp.simplify(anchor[0] + scale * direction[0]),
            sp.simplify(anchor[1] + scale * direction[1]),
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "constructed_point_on_positive_ray",
                    _point_on_ray(point, anchor, ray_point),
                    f"{target.name} lies on the declared ray",
                ),
                _check(
                    "constructed_reference_distance",
                    _distance_equality(
                        kernel,
                        anchor,
                        point,
                        anchor,
                        reference_point,
                    ),
                    f"{target.name} has the declared reference distance",
                ),
            ],
        )


class VerifyPointOnRayMethod:
    """Verify that a point lies on the positive direction of a ray."""

    method_id = "verify_point_on_ray"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        del kernel
        passed = _point_on_ray(
            inputs["point"],
            inputs["anchor"],
            inputs["ray_point"],
        )
        return _predicate_result(self.method_id, passed, "point_on_ray")


class VerifyDistanceEqualityMethod:
    """Verify equality of two Euclidean segment lengths."""

    method_id = "verify_distance_equality"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        passed = _distance_equality(
            kernel,
            inputs["first_start"],
            inputs["first_end"],
            inputs["second_start"],
            inputs["second_end"],
        )
        return _predicate_result(self.method_id, passed, "distance_equality")


class ProveDistanceEqualityFromConditionsMethod:
    """Verify that structured Conditions support one distance substitution."""

    method_id = "prove_distance_equality_from_conditions"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        del kernel
        premises = tuple(
            _condition_payload(inputs[name])
            for name in (
                "equal_length_condition",
                "linking_condition",
                "ray_membership_condition",
                "constructed_equal_length_condition",
                "constructed_ray_condition",
            )
        )
        kinds = tuple(_condition_kind(item) for item in premises)
        common = inputs["common_vertex"]
        first_start = inputs["first_start"]
        first_end = inputs["first_end"]
        second_start = inputs["second_start"]
        second_end = inputs["second_end"]
        premises_valid = (
            kinds[0]
            in {
                "equal_length",
                "equal_length_condition",
                "length_equality",
                "distance_equality",
                "equal_length_on_ray",
            }
            and kinds[1] == "point_on_segment"
            and kinds[2] == "point_on_ray"
            and kinds[3] == "distance_equality"
            and kinds[4] == "point_on_ray"
            and _condition_mentions(premises[0], common, first_end, second_start)
            and _condition_mentions(
                premises[1], common, first_start, second_start
            )
            and _condition_mentions(premises[2], common, first_end)
            and _condition_mentions(premises[3], common, first_start, second_end)
            and _condition_mentions(premises[4], common, second_end)
        )
        return _predicate_result(
            self.method_id,
            premises_valid,
            "distance_equality_from_conditions",
        )


class RewriteExpressionByConditionMethod:
    """Publish an expression rewrite after consuming its verified Condition."""

    method_id = "rewrite_expression_by_condition"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        original = sp.sympify(inputs["original_expression"])
        rewritten = sp.sympify(inputs["rewritten_expression"])
        condition = _condition_payload(inputs["condition"])
        if not _condition_kind(condition):
            raise method_input_invalid(
                "expression rewrite requires a verified Condition",
                arg_name="condition",
                role="rewrite_authority",
                expected={"condition_kind": "nonempty"},
                observed={"condition": condition},
            )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "expression": TypedValue(
                    "Expression",
                    sp.simplify(rewritten),
                    source=self.method_id,
                )
            },
            checks=[
                _check(
                    "rewrite_condition_consumed",
                    True,
                    "the exact verified Condition authorizes this rewrite",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "等价改写路径表达式",
                    "使用已证明关系替换一段距离",
                    "只在精确 Condition 已发布后应用等价替换。",
                    f"{kernel.sstr(original)}={kernel.sstr(rewritten)}",
                    kernel.sstr(rewritten),
                )
            ],
        )


class CertifyMinimumExpressionMethod:
    """Publish a standard minimum expression from a verified attainment."""

    method_id = "certify_minimum_expression"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        expression = sp.simplify(sp.sympify(inputs["expression"]))
        condition = _condition_payload(inputs["attainment_condition"])
        if _condition_kind(condition) != "path_minimum_attained":
            raise method_input_invalid(
                "minimum certification requires a verified attainment Condition",
                arg_name="attainment_condition",
                role="minimum_attainment_authority",
                expected={"condition_kind": "path_minimum_attained"},
                observed={"condition_kind": _condition_kind(condition)},
            )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "minimum_expression": TypedValue(
                    "MinimumExpression",
                    expression,
                    source=self.method_id,
                )
            },
            checks=[
                _check(
                    "minimum_attainment_condition_consumed",
                    True,
                    "the exact verified attainment authorizes the minimum expression",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "认证最小值表达式",
                    "使用已验证的达到性条件发布最小值",
                    "只有达到性 Condition 已发布时才认证该表达式。",
                    kernel.sstr(expression),
                    kernel.sstr(expression),
                )
            ],
        )


class ReflectPointAcrossLineMethod:
    """Reflect a point across the line through two distinct points."""

    method_id = "reflect_point_across_line"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        point: Point = inputs["point"]
        line_p1: Point = inputs["line_p1"]
        line_p2: Point = inputs["line_p2"]
        target: PointRef = inputs["target"]
        try:
            reflected = reflect_point_across_line(point, line_p1, line_p2)
        except ValueError as exc:
            raise method_precondition_failed(
                str(exc),
                role="reflection_line",
                expected={"line_points": "distinct"},
                observed={"line_points": [line_p1, line_p2]},
                repair_action="provide_distinct_line_points",
            ) from exc
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "reflected_point": TypedValue(
                    "Point", reflected, source=self.method_id
                )
            },
            checks=[
                _check(
                    "reflection_distance_to_line_point",
                    _distance_equality(
                        kernel,
                        point,
                        line_p1,
                        reflected,
                        line_p1,
                    ),
                    f"{target.name} preserves distance to the mirror line",
                )
            ],
        )


class VerifyPointOnClosedSegmentMethod:
    """Verify that a point belongs to a closed segment."""

    method_id = "verify_point_on_closed_segment"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        del kernel
        passed = _point_on_closed_segment(
            inputs["point"],
            inputs["segment_start"],
            inputs["segment_end"],
            domain_condition=_condition_payload(
                inputs.get("domain_condition")
            ),
        )
        return _predicate_result(self.method_id, passed, "point_on_segment")


class DistanceSumExpressionMethod:
    """Construct the sum of two consecutive segment lengths."""

    method_id = "distance_sum_expression"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        expression = sp.simplify(
            kernel.distance(inputs["start"], inputs["via"])
            + kernel.distance(inputs["via"], inputs["end"])
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "expression": TypedValue(
                    "MinimumExpression", expression, source=self.method_id
                )
            },
            checks=[
                _check(
                    "distance_sum_constructed",
                    True,
                    "the expression is the sum of two Euclidean distances",
                )
            ],
        )


class VerifyTwoSegmentPathAttainmentMethod:
    """Verify that a candidate point attains the global two-segment minimum."""

    method_id = "verify_two_segment_path_attainment"

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        objective = sp.sympify(inputs["objective"])
        candidate = sp.sympify(inputs["candidate"])
        difference = _refine_with_domain_condition(
            objective - candidate,
            _condition_payload(inputs.get("domain_condition")),
        )
        condition = _condition_payload(inputs.get("domain_condition"))
        candidate_point = inputs["candidate_point"]
        path_start = inputs["path_start"]
        path_end = inputs["path_end"]
        segment_start = inputs["segment_start"]
        segment_end = inputs["segment_end"]
        passed = difference == 0 and _two_segment_candidate_is_global_minimum(
            kernel,
            candidate_point=candidate_point,
            path_start=path_start,
            path_end=path_end,
            segment_start=segment_start,
            segment_end=segment_end,
            candidate_expression=candidate,
            domain_condition=condition,
        )
        return _predicate_result(self.method_id, passed, "path_attainment")


def _two_segment_candidate_is_global_minimum(
    kernel: SympyKernel,
    *,
    candidate_point: Point,
    path_start: Point,
    path_end: Point,
    segment_start: Point,
    segment_end: Point,
    candidate_expression: sp.Expr,
    domain_condition: Mapping[str, Any] | None,
) -> bool:
    """Prove the standard direct/reflection/endpoint finite candidate set."""

    direct = _safe_line_intersection(
        kernel,
        path_start,
        path_end,
        segment_start,
        segment_end,
    )
    if direct is not None and _point_on_closed_segment(
        direct,
        segment_start,
        segment_end,
        domain_condition=domain_condition,
    ):
        return _points_symbolically_equal(candidate_point, direct)

    reflected = _reflect_point(path_start, segment_start, segment_end)
    straightened = _safe_line_intersection(
        kernel,
        reflected,
        path_end,
        segment_start,
        segment_end,
    )
    if straightened is not None and _point_on_closed_segment(
        straightened,
        segment_start,
        segment_end,
        domain_condition=domain_condition,
    ):
        return _points_symbolically_equal(candidate_point, straightened)

    endpoint_expressions = tuple(
        sp.simplify(
            kernel.distance(path_start, endpoint)
            + kernel.distance(endpoint, path_end)
        )
        for endpoint in (segment_start, segment_end)
    )
    if not any(
        _points_symbolically_equal(candidate_point, endpoint)
        for endpoint in (segment_start, segment_end)
    ):
        return False
    return all(
        _expression_is_no_greater(
            candidate_expression,
            other,
            domain_condition=domain_condition,
        )
        for other in endpoint_expressions
    )


def _safe_line_intersection(
    kernel: SympyKernel,
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> Point | None:
    try:
        return kernel.line_intersection(
            (first_start, first_end),
            (second_start, second_end),
        )
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _reflect_point(point: Point, line_start: Point, line_end: Point) -> Point:
    dx = sp.simplify(line_end[0] - line_start[0])
    dy = sp.simplify(line_end[1] - line_start[1])
    denominator = sp.simplify(dx**2 + dy**2)
    if denominator == 0:
        raise method_precondition_failed(
            "reflection requires two distinct line points",
            arg_name="segment_end",
            role="reflection_line_endpoint",
            expected={"distance_from_segment_start": "nonzero"},
            observed={"distance_from_segment_start": 0},
            repair_action="provide_distinct_segment_endpoints",
        )
    projection = sp.simplify(
        ((point[0] - line_start[0]) * dx + (point[1] - line_start[1]) * dy)
        / denominator
    )
    foot = (
        sp.simplify(line_start[0] + projection * dx),
        sp.simplify(line_start[1] + projection * dy),
    )
    return (
        sp.simplify(2 * foot[0] - point[0]),
        sp.simplify(2 * foot[1] - point[1]),
    )


def _points_symbolically_equal(left: Point, right: Point) -> bool:
    return all(sp.simplify(a - b) == 0 for a, b in zip(left, right, strict=True))


def _expression_is_no_greater(
    left: sp.Expr,
    right: sp.Expr,
    *,
    domain_condition: Mapping[str, Any] | None,
) -> bool:
    difference = _refine_with_domain_condition(left - right, domain_condition)
    if difference == 0 or difference.is_nonpositive is True:
        return True
    return sp.ask(sp.Q.nonpositive(difference)) is True


def _predicate_result(
    method_id: str,
    passed: bool,
    check_code: str,
) -> StatelessMethodResult:
    return StatelessMethodResult(
        method_id=method_id,
        outputs={"verified": TypedValue("Boolean", bool(passed), source=method_id)},
        checks=[
            _check(
                "predicate_evaluated",
                True,
                f"predicate {check_code} evaluated deterministically",
            )
        ],
    )


def _point_on_ray(point: Point, anchor: Point, ray_point: Point) -> bool:
    direction = (
        sp.simplify(ray_point[0] - anchor[0]),
        sp.simplify(ray_point[1] - anchor[1]),
    )
    if direction == (0, 0) or not _points_symbolically_collinear(
        point,
        anchor,
        ray_point,
    ):
        return False
    dot = sp.simplify(
        (point[0] - anchor[0]) * direction[0]
        + (point[1] - anchor[1]) * direction[1]
    )
    return bool(dot == 0 or _manifestly_nonnegative_real(dot))


def _point_on_closed_segment(
    point: Point,
    start: Point,
    end: Point,
    *,
    domain_condition: Mapping[str, Any] | None = None,
) -> bool:
    if not _points_symbolically_collinear(
        point,
        start,
        end,
        domain_condition=domain_condition,
    ):
        return False
    dot = _refine_with_domain_condition(
        (point[0] - start[0]) * (point[0] - end[0])
        + (point[1] - start[1]) * (point[1] - end[1]),
        domain_condition,
    )
    return bool(dot == 0 or _manifestly_nonnegative_real(-dot))


def _points_symbolically_collinear(
    point: Point,
    first: Point,
    second: Point,
    *,
    domain_condition: Mapping[str, Any] | None = None,
) -> bool:
    """Prove collinearity without SymPy geometry's undecidable bool path."""

    cross = _refine_with_domain_condition(
        (point[0] - first[0]) * (second[1] - first[1])
        - (point[1] - first[1]) * (second[0] - first[0]),
        domain_condition,
    )
    if cross == 0:
        return True
    try:
        return cross.equals(0) is True
    except (NotImplementedError, TypeError, ValueError):
        return False


def _refine_with_domain_condition(
    value: object,
    condition: Mapping[str, Any] | None,
) -> sp.Expr:
    expression = sp.sympify(value)
    if not condition or _condition_kind(condition) != "symbol_constraint":
        return sp.simplify(expression)
    subject = str(condition.get("subject") or "").rsplit(":", 1)[-1]
    operator = str(condition.get("operator") or "")
    try:
        boundary = sp.sympify(condition.get("value"))
    except (TypeError, ValueError):
        return sp.simplify(expression)
    symbol = next(
        (item for item in expression.free_symbols if item.name == subject),
        None,
    )
    assumptions = {
        (">", sp.Integer(0)): {"positive": True},
        (">=", sp.Integer(0)): {"nonnegative": True},
        ("<", sp.Integer(0)): {"negative": True},
        ("<=", sp.Integer(0)): {"nonpositive": True},
    }.get((operator, boundary))
    if symbol is None or assumptions is None:
        return sp.simplify(expression)
    assumed_symbol = sp.Symbol(symbol.name, **assumptions)
    refined = sp.simplify(expression.xreplace({symbol: assumed_symbol}))
    return refined.xreplace({assumed_symbol: symbol})


def _manifestly_nonnegative_real(value: object) -> bool:
    """Prove signs encoded structurally by real geometric expressions."""

    expression = sp.factor_terms(sp.sympify(value))
    if expression.is_nonnegative is True:
        return True
    if expression.is_number:
        return bool(expression.is_real and expression >= 0)
    if expression.func is sp.Abs:
        return True
    if expression.is_Add:
        return all(_manifestly_nonnegative_real(item) for item in expression.args)
    if expression.is_Mul:
        return all(_manifestly_nonnegative_real(item) for item in expression.args)
    if expression.is_Pow:
        base, exponent = expression.as_base_exp()
        if exponent.is_integer and exponent.is_even:
            return True
        if exponent.is_rational and _manifestly_nonnegative_real(base):
            return True
    return False


def _distance_equality(
    kernel: SympyKernel,
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> bool:
    return (
        sp.simplify(
            kernel.distance_squared(first_start, first_end)
            - kernel.distance_squared(second_start, second_end)
        )
        == 0
    )


def _condition_payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        payload = to_payload()
        if isinstance(payload, Mapping):
            return payload
    return {}


def _condition_kind(condition: Mapping[str, Any]) -> str:
    return str(condition.get("kind") or condition.get("type") or "")


def _condition_mentions(
    condition: Mapping[str, Any],
    *points: PointRef,
) -> bool:
    values = _condition_strings(condition)
    return all(_identity_is_mentioned(point, values) for point in points)


def _condition_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return tuple(
            item
            for child in value.values()
            for item in _condition_strings(child)
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            item for child in value for item in _condition_strings(child)
        )
    return (value,) if isinstance(value, str) else ()


def _identity_is_mentioned(point: PointRef, values: tuple[str, ...]) -> bool:
    entity_handle = str(point.definition.get("entity_handle") or "")
    if entity_handle and entity_handle in values:
        return True
    if point.name in values:
        return True
    if len(point.name) != 1 or not point.name.isalpha():
        return False
    return any(
        point.name in value.rsplit(":", 1)[-1]
        and value.rsplit(":", 1)[-1].isalpha()
        and value.rsplit(":", 1)[-1].isupper()
        for value in values
    )


CONSTRUCT_POINT_ON_RAY_AT_REFERENCE_DISTANCE_SPEC = MethodSpecSource(
    method_cls=ConstructPointOnRayAtReferenceDistanceMethod,
    title="在射线上构造参考等长点",
    solves=("construct_point_on_ray_at_reference_distance",),
    inputs={
        "anchor": {"type": "Point", "required": True},
        "ray_point": {"type": "Point", "required": True},
        "reference_point": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    input_views=declare_input_views(
        latest_state=("anchor", "ray_point", "reference_point"),
        identity=("target",),
    ),
    outputs={"point": "Point"},
    preconditions=("anchor 与 ray_point 必须确定非零射线方向",),
    postconditions=("输出点位于正向射线且满足参考等长",),
)


VERIFY_POINT_ON_RAY_SPEC = MethodSpecSource(
    method_cls=VerifyPointOnRayMethod,
    title="验证点位于射线",
    solves=("verify_point_on_ray",),
    inputs={
        "point": {"type": "Point", "required": True},
        "anchor": {"type": "Point", "required": True},
        "ray_point": {"type": "Point", "required": True},
    },
    input_views=declare_input_views(
        latest_state=("point", "anchor", "ray_point")
    ),
    outputs={"verified": "Boolean"},
    predicate_publications=(
        PredicatePublicationSpec(
            "verified", "point_on_ray", ("point", "anchor", "ray_point")
        ),
    ),
)


VERIFY_DISTANCE_EQUALITY_SPEC = MethodSpecSource(
    method_cls=VerifyDistanceEqualityMethod,
    title="验证两线段等长",
    solves=("verify_distance_equality",),
    inputs={
        "first_start": {"type": "Point", "required": True},
        "first_end": {"type": "Point", "required": True},
        "second_start": {"type": "Point", "required": True},
        "second_end": {"type": "Point", "required": True},
    },
    input_views=declare_input_views(
        latest_state=(
            "first_start",
            "first_end",
            "second_start",
            "second_end",
        )
    ),
    outputs={"verified": "Boolean"},
    predicate_publications=(
        PredicatePublicationSpec(
            "verified",
            "distance_equality",
            ("first_start", "first_end", "second_start", "second_end"),
        ),
    ),
)


PROVE_DISTANCE_EQUALITY_FROM_CONDITIONS_SPEC = MethodSpecSource(
    method_cls=ProveDistanceEqualityFromConditionsMethod,
    title="由结构化条件证明距离等式",
    solves=("prove_distance_equality_from_conditions",),
    inputs={
        "equal_length_condition": {"type": "Condition", "required": True},
        "linking_condition": {"type": "Condition", "required": True},
        "ray_membership_condition": {"type": "Condition", "required": True},
        "constructed_equal_length_condition": {
            "type": "Condition",
            "required": True,
        },
        "constructed_ray_condition": {"type": "Condition", "required": True},
        "common_vertex": {"type": "PointRef", "required": True},
        "first_start": {"type": "PointRef", "required": True},
        "first_end": {"type": "PointRef", "required": True},
        "second_start": {"type": "PointRef", "required": True},
        "second_end": {"type": "PointRef", "required": True},
    },
    input_views=declare_input_views(
        immutable_value=(
            "equal_length_condition",
            "linking_condition",
            "ray_membership_condition",
            "constructed_equal_length_condition",
            "constructed_ray_condition",
        ),
        identity=(
            "common_vertex",
            "first_start",
            "first_end",
            "second_start",
            "second_end",
        ),
    ),
    outputs={"verified": "Boolean"},
    predicate_publications=(
        PredicatePublicationSpec(
            "verified",
            "distance_equality",
            ("first_start", "first_end", "second_start", "second_end"),
        ),
    ),
)


REWRITE_EXPRESSION_BY_CONDITION_SPEC = MethodSpecSource(
    method_cls=RewriteExpressionByConditionMethod,
    title="按已证条件改写表达式",
    solves=("rewrite_expression_by_condition",),
    inputs={
        "original_expression": {
            "type": "Expression|MinimumExpression",
            "required": True,
            "allows_anonymous_result": True,
        },
        "rewritten_expression": {
            "type": "Expression|MinimumExpression",
            "required": True,
            "allows_anonymous_result": True,
        },
        "condition": {"type": "Condition", "required": True},
    },
    input_views=declare_input_views(
        exact_result=("original_expression", "rewritten_expression"),
        immutable_value=("condition",),
    ),
    outputs={"expression": "Expression"},
)


CERTIFY_MINIMUM_EXPRESSION_SPEC = MethodSpecSource(
    method_cls=CertifyMinimumExpressionMethod,
    title="由达到性条件认证最小值表达式",
    solves=("certify_minimum_expression",),
    inputs={
        "expression": {
            "type": "Expression|MinimumExpression",
            "required": True,
            "allows_anonymous_result": True,
        },
        "attainment_condition": {"type": "Condition", "required": True},
    },
    input_views=declare_input_views(
        exact_result=("expression",),
        immutable_value=("attainment_condition",),
    ),
    outputs={"minimum_expression": "MinimumExpression"},
)


REFLECT_POINT_ACROSS_LINE_SPEC = MethodSpecSource(
    method_cls=ReflectPointAcrossLineMethod,
    title="点关于直线的对称点",
    solves=("reflect_point_across_line",),
    inputs={
        "point": {"type": "Point", "required": True},
        "line_p1": {"type": "Point", "required": True},
        "line_p2": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    input_views=declare_input_views(
        latest_state=("point", "line_p1", "line_p2"),
        identity=("target",),
    ),
    outputs={"reflected_point": "Point"},
    distinct_arg_groups=(("line_p1", "line_p2"),),
    interchangeable_arg_groups=(("line_p1", "line_p2"),),
)


VERIFY_POINT_ON_CLOSED_SEGMENT_SPEC = MethodSpecSource(
    method_cls=VerifyPointOnClosedSegmentMethod,
    title="验证点位于闭线段",
    solves=("verify_point_on_closed_segment",),
    inputs={
        "point": {"type": "Point", "required": True},
        "segment_start": {"type": "Point", "required": True},
        "segment_end": {"type": "Point", "required": True},
        "domain_condition": {"type": "Condition", "required": False},
    },
    input_views=declare_input_views(
        latest_state=("point", "segment_start", "segment_end"),
        immutable_value=("domain_condition",),
    ),
    outputs={"verified": "Boolean"},
    predicate_publications=(
        PredicatePublicationSpec(
            "verified",
            "point_on_segment",
            ("point", "segment_start", "segment_end"),
        ),
    ),
)


DISTANCE_SUM_EXPRESSION_SPEC = MethodSpecSource(
    method_cls=DistanceSumExpressionMethod,
    title="构造两段距离和表达式",
    solves=("derive_distance_sum_expression",),
    inputs={
        "start": {"type": "Point", "required": True},
        "via": {"type": "Point", "required": True},
        "end": {"type": "Point", "required": True},
    },
    input_views=declare_input_views(latest_state=("start", "via", "end")),
    outputs={"expression": "MinimumExpression"},
)


VERIFY_TWO_SEGMENT_PATH_ATTAINMENT_SPEC = MethodSpecSource(
    method_cls=VerifyTwoSegmentPathAttainmentMethod,
    title="验证两段路径达到候选值",
    solves=("verify_two_segment_path_attainment",),
    inputs={
        "objective": {
            "type": "Expression|MinimumExpression",
            "required": True,
            "allows_anonymous_result": True,
        },
        "candidate": {
            "type": "Expression|MinimumExpression",
            "required": True,
            "allows_anonymous_result": True,
        },
        "candidate_point": {"type": "Point", "required": True},
        "path_start": {"type": "Point", "required": True},
        "path_end": {"type": "Point", "required": True},
        "segment_start": {"type": "Point", "required": True},
        "segment_end": {"type": "Point", "required": True},
        "domain_condition": {"type": "Condition", "required": False},
    },
    input_views=declare_input_views(
        exact_result=("objective", "candidate"),
        latest_state=(
            "candidate_point",
            "path_start",
            "path_end",
            "segment_start",
            "segment_end",
        ),
        immutable_value=("domain_condition",),
    ),
    outputs={"verified": "Boolean"},
    predicate_publications=(
        PredicatePublicationSpec(
            "verified",
            "path_minimum_attained",
            (
                "objective",
                "candidate",
                "candidate_point",
                "path_start",
                "path_end",
                "segment_start",
                "segment_end",
            ),
        ),
    ),
)


PATH_VERIFICATION_METHODS = (
    ConstructPointOnRayAtReferenceDistanceMethod,
    VerifyPointOnRayMethod,
    VerifyDistanceEqualityMethod,
    ProveDistanceEqualityFromConditionsMethod,
    RewriteExpressionByConditionMethod,
    CertifyMinimumExpressionMethod,
    ReflectPointAcrossLineMethod,
    VerifyPointOnClosedSegmentMethod,
    DistanceSumExpressionMethod,
    VerifyTwoSegmentPathAttainmentMethod,
)


PATH_VERIFICATION_SPECS = (
    CONSTRUCT_POINT_ON_RAY_AT_REFERENCE_DISTANCE_SPEC,
    VERIFY_POINT_ON_RAY_SPEC,
    VERIFY_DISTANCE_EQUALITY_SPEC,
    PROVE_DISTANCE_EQUALITY_FROM_CONDITIONS_SPEC,
    REWRITE_EXPRESSION_BY_CONDITION_SPEC,
    CERTIFY_MINIMUM_EXPRESSION_SPEC,
    REFLECT_POINT_ACROSS_LINE_SPEC,
    VERIFY_POINT_ON_CLOSED_SEGMENT_SPEC,
    DISTANCE_SUM_EXPRESSION_SPEC,
    VERIFY_TWO_SEGMENT_PATH_ATTAINMENT_SPEC,
)
