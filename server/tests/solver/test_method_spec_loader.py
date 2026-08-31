"""V1.5 MethodSpec 加载测试。

这些测试确保 method 代码里的 SPEC 能被加载成强类型 MethodSpec，并且生成的 JSON
资产没有和代码事实源漂移。
"""

import ast
import importlib
import json
from pathlib import Path
import re

import pytest

from shuxueshuo_server.solver.runtime.method_specs import (
    MethodSpecRegistry,
    method_output_activity,
    parse_method_spec,
)
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    RETIRED_PATH_COMPONENT_REPLACEMENTS,
)
from shuxueshuo_server.solver.runtime.methods import (
    ALL_METHOD_SPEC_SOURCES,
    method_spec_payloads,
)
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry


PLACEHOLDER_RE = re.compile(r"{([A-Za-z_][A-Za-z0-9_]*)}")
ENGLISH_WORD_RE = re.compile(r"[A-Za-z]{2,}")
METHODS_DIR = (
    Path(__file__).resolve().parents[2]
    / "shuxueshuo_server"
    / "solver"
    / "runtime"
    / "methods"
)
PRIVATE_PATH_METHODS_DIR = METHODS_DIR / "_internal" / "path"


def test_loads_right_angle_candidate_and_selector_specs() -> None:
    registry = MethodSpecRegistry.load_from_code()
    candidate_spec = registry.require("right_angle_equal_length_candidates")
    selector_spec = registry.require("select_point_by_quadrant_constraint")

    assert candidate_spec.method_id == "right_angle_equal_length_candidates"
    assert "参数" in candidate_spec.summary
    assert candidate_spec.inputs["anchor"].type == "Point"
    assert candidate_spec.outputs["candidates"] == "PointList"
    assert selector_spec.inputs["parameter_constraint"].type == "Constraint"
    assert selector_spec.outputs["selected_point"] == "Point"


def test_retired_path_component_specs_are_not_planner_registered() -> None:
    registry = MethodSpecRegistry.load_from_code()
    retired = {
        "two_moving_points_path_reduction",
        "broken_path_straightening_candidates",
        "select_straightening_candidate",
        "square_path_dimension_reduction",
        "parameterized_point_locus_line",
        "line_locus_minimum_point",
        "weighted_axis_path_triangle_transform",
        "linked_broken_path_minimum_expression",
        "linked_broken_path_geometric_minimum",
    }

    assert retired.isdisjoint(registry.specs)
    assert {
        "coupled_segment_endpoint_replacement_path_minimum_kernel",
        "quadratic_square_path_minimum_kernel",
        "weighted_axis_path_minimum_kernel",
    } <= set(registry.specs)
    retired_recipes = {
        "broken_path_straightening_and_select",
        "broken_path_straightening_minimum_expression",
        "path_minimum_by_straightened_distance",
    }
    assert retired_recipes.isdisjoint(RecipeSpecRegistry.load_from_code().specs)


def test_every_root_method_spec_source_is_registered() -> None:
    """A new root ``SPEC`` cannot silently remain outside the registry."""

    registered_ids = {
        str(item.to_payload()["method_id"])
        for item in ALL_METHOD_SPEC_SOURCES
    }
    discovered_ids: set[str] = set()
    for source_path in METHODS_DIR.glob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        if not any(
            isinstance(node, (ast.Assign, ast.AnnAssign))
            and any(
                isinstance(target, ast.Name) and target.id == "SPEC"
                for target in (
                    node.targets if isinstance(node, ast.Assign) else (node.target,)
                )
            )
            for node in tree.body
        ):
            continue
        module = importlib.import_module(
            f"shuxueshuo_server.solver.runtime.methods.{source_path.stem}"
        )
        discovered_ids.add(str(module.SPEC.to_payload()["method_id"]))

    assert discovered_ids == registered_ids


def test_private_path_helpers_have_no_specs_and_all_ids_are_tombstoned() -> None:
    """Kernel helpers cannot be re-exported without updating atomicity policy."""

    internal_method_ids: set[str] = set()
    for source_path in PRIVATE_PATH_METHODS_DIR.glob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        assigned_names = {
            target.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else (node.target,)
            )
            if isinstance(target, ast.Name)
        }
        assert "SPEC" not in assigned_names
        assert "MINIMUM_EXPRESSION_SPEC" not in assigned_names
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            value = node.value
            if (
                any(
                    isinstance(target, ast.Name) and target.id == "method_id"
                    for target in targets
                )
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                internal_method_ids.add(value.value)

    assert internal_method_ids
    assert internal_method_ids <= set(RETIRED_PATH_COMPONENT_REPLACEMENTS)


def test_only_atomic_path_kernels_import_private_path_helpers() -> None:
    allowed_importers = {
        "coupled_segment_path_minimum.py",
        "quadratic_square_path_minimum.py",
        "weighted_axis_path_minimum.py",
    }
    actual_importers: set[str] = set()
    for source_path in METHODS_DIR.glob("*.py"):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        if any(
            isinstance(node, ast.ImportFrom)
            and str(node.module or "").startswith("_internal.path")
            for node in ast.walk(tree)
        ):
            actual_importers.add(source_path.name)

    assert actual_importers == allowed_importers


def test_loads_quadratic_from_constraints_spec() -> None:
    """统一二次函数约束 method 应暴露足够的可选约束输入槽位。"""
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("quadratic_from_constraints")

    assert "最简" in spec.summary
    assert "使用原则" in spec.summary
    assert spec.inputs["quadratic"].type == "Expression"
    assert spec.inputs["x"].type == "Symbol"
    assert spec.inputs["all_coefficients"].type == "SymbolList"
    assert spec.inputs["known_coefficients"].required is False
    assert spec.inputs["coefficient_relation"].type == "Equation"
    assert spec.inputs["curve_point"].type == "Point"
    assert spec.inputs["curve_points"].type == "PointList"
    assert spec.inputs["free_parameter"].type == "Symbol"
    assert spec.inputs["free_parameters"].type == "SymbolList"
    assert spec.inputs["free_parameters"].allows_empty_collection
    assert "开放状态必须填写非空基底" in spec.inputs["free_parameters"].role
    assert "闭合状态可填写[]或省略" in spec.inputs["free_parameters"].role
    assert spec.outputs["coefficients"] == "Coefficients"
    assert spec.outputs["parabola"] == "Parabola"
    assert any("重复求解" in item for item in spec.do_not_use_when)


def test_method_spec_usage_guidance_round_trips_and_validates() -> None:
    payload = next(
        item
        for item in method_spec_payloads()
        if item["method_id"] == "evaluate_point_at_parameter"
    )

    spec = parse_method_spec(payload)

    assert spec.do_not_use_when == tuple(payload["do_not_use_when"])
    duplicated = dict(payload)
    duplicated["do_not_use_when"] = ["avoid this", "avoid this"]
    assert parse_method_spec(duplicated).do_not_use_when == ("avoid this",)
    malformed = dict(payload)
    malformed["do_not_use_when"] = [""]
    with pytest.raises(
        ValueError,
        match="do_not_use_when items must be non-empty",
    ):
        parse_method_spec(malformed)


def test_loads_quadratic_candidate_filter_spec() -> None:
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("filter_point_candidates_by_quadratic_curve")

    assert spec.inputs["candidates"].type == "PointList"
    assert spec.inputs["parabola"].type == "Parabola"
    assert spec.inputs["parameter_constraint"].type == "Constraint"
    assert spec.outputs["filtered_candidates"] == "PointList"
    assert spec.outputs["rejected_candidates"] == "PointList"
    assert spec.outputs["selected_candidate"] == "Point"


def test_loads_square_axis_candidate_atomic_specs() -> None:
    registry = MethodSpecRegistry.load_from_code()
    axis_point = registry.require("quadratic_axis_parameterized_point")
    square_vertex = registry.require("square_adjacent_vertex_from_side")
    curve_condition = registry.require("point_candidates_from_curve_point_condition")
    point_at_parameter = registry.require("evaluate_point_at_parameter")

    assert axis_point.inputs["parabola"].type == "Parabola"
    assert axis_point.outputs["point"] == "Point"
    assert square_vertex.inputs["square_condition"].type == "Condition"
    assert square_vertex.inputs["target"].type == "PointRef|Point"
    assert square_vertex.inputs["side_start_ref"].type == "PointRef|Point"
    assert square_vertex.inputs["side_end_ref"].type == "PointRef|Point"
    assert square_vertex.outputs["point"] == "Point"
    assert curve_condition.inputs["target_point"].type == "Point"
    assert curve_condition.inputs["curve_point"].type == "Point"
    assert curve_condition.outputs["candidates"] == "PointList"
    assert point_at_parameter.inputs["point"].type == "Point"
    assert point_at_parameter.outputs["evaluated_point"] == "Point"


def test_loads_parameter_from_curve_point_on_quadratic_spec() -> None:
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("parameter_from_curve_point_on_quadratic")

    assert spec.inputs["quadratic"].type == "Parabola"
    assert spec.inputs["point"].type == "Point"
    assert spec.inputs["parameter"].type == "Symbol"
    assert spec.inputs["parameter_constraint"].type == "Constraint"
    assert spec.outputs["parameter_value"] == "ParameterValue"
    assert spec.outputs["point"] == "Point"
    assert spec.outputs["parabola"] == "Parabola"


def test_loads_atomic_weighted_path_kernel_spec() -> None:
    """Planner registry only exposes the atomic weighted-path kernel."""
    registry = MethodSpecRegistry.load_from_code()
    minimum = registry.require("weighted_axis_path_minimum_kernel")
    parameter = registry.require("parameter_from_expression_value")

    assert minimum.inputs["path_condition"].type == "Condition"
    assert minimum.inputs["moving_point_ref"].type == "PointRef"
    assert minimum.outputs["minimum_expression"] == "MinimumExpression"
    assert minimum.internal_outputs == ("evidence",)
    assert "parameter_value" not in minimum.outputs
    assert parameter.inputs["expression"].type == "MinimumExpression"
    assert parameter.outputs["parameter_value"] == "ParameterValue"
    assert parameter.explanation is not None
    assert parameter.explanation.student_title_template == "由表达式取值反求参数"


def test_method_spec_internal_outputs_must_reference_declared_outputs() -> None:
    payload = next(
        item
        for item in method_spec_payloads()
        if item["method_id"] == "weighted_axis_path_minimum_kernel"
    )
    invalid = dict(payload)
    invalid["internal_outputs"] = ["missing_output"]

    with pytest.raises(
        ValueError,
        match="internal_outputs references unknown outputs",
    ):
        parse_method_spec(invalid)


def test_y_axis_intercept_summary_allows_symbolic_coefficients() -> None:
    """y 轴交点 method 的能力摘要应说明可保留未定系数。"""
    registry = MethodSpecRegistry.load_from_code()
    spec = registry.require("quadratic_y_axis_intercept_point")

    assert spec.inputs["quadratic"].type == "Expression"
    assert "未定系数" in spec.summary


def test_searches_spec_by_goal_type() -> None:
    registry = MethodSpecRegistry.load_from_code()

    matches = registry.for_goal("derive_right_angle_equal_length_candidates")

    assert [spec.method_id for spec in matches] == ["right_angle_equal_length_candidates"]


def test_scalar_result_form_specs_round_trip_from_code() -> None:
    registry = MethodSpecRegistry.load_from_code()

    distance = registry.require("distance_between_points")
    assert set(distance.scalar_result_forms) == {
        "distance",
        "evaluated_distance",
    }
    assert distance.scalar_result_forms["distance"].possible_forms == (
        "open_expression",
        "closed_value",
    )
    assert distance.scalar_result_forms["distance"].closure_policy == (
        "no_free_symbols"
    )

    evaluate = registry.require("evaluate_expression_at_parameter")
    assert set(evaluate.scalar_result_forms) == {
        "evaluated_expression",
        "evaluated_minimum_expression",
    }
    assert "evaluated_parabola" not in evaluate.scalar_result_forms


def test_method_output_activation_is_code_owned_and_deterministic() -> None:
    registry = MethodSpecRegistry.load_from_code()
    distance = registry.require("distance_between_points")

    assert method_output_activity(
        distance,
        "distance",
        provided_input_names=frozenset({"p1", "p2"}),
    ) == "active"
    assert method_output_activity(
        distance,
        "evaluated_distance",
        provided_input_names=frozenset({"p1", "p2"}),
    ) == "inactive"
    assert method_output_activity(
        distance,
        "evaluated_distance",
        provided_input_names=frozenset(
            {"p1", "p2", "parameter", "parameter_value"}
        ),
    ) == "active"

    evaluate = registry.require("evaluate_expression_at_parameter")
    assert method_output_activity(
        evaluate,
        "evaluated_parabola",
        provided_input_names=frozenset(
            {"expression", "parameter", "parameter_value"}
        ),
        input_runtime_types={"expression": "Parabola"},
    ) == "active"
    assert method_output_activity(
        evaluate,
        "evaluated_expression",
        provided_input_names=frozenset(
            {"expression", "parameter", "parameter_value"}
        ),
        input_runtime_types={"expression": "Parabola"},
    ) == "inactive"

    selector = registry.require("filter_point_candidates_by_quadratic_curve")
    assert method_output_activity(
        selector,
        "selected_candidate",
        provided_input_names=frozenset(selector.inputs),
    ) == "runtime_conditional"


def test_symbolic_closure_spec_round_trips_from_code() -> None:
    spec = MethodSpecRegistry.load_from_code().require(
        "quadratic_from_constraints"
    )

    assert spec.symbolic_closure is not None
    assert spec.symbolic_closure.target_arg == "target_parameter"
    assert spec.symbolic_closure.preserved_symbol_args == (
        "free_parameter",
        "free_parameters",
    )
    assert spec.symbolic_closure.substitution_outputs == (
        "coefficients",
        "parabola",
        "parameter_value",
    )


def test_generated_json_specs_match_code_source() -> None:
    spec_dir = Path("../internal/method-specs")
    expected = {
        payload["method_id"]: payload
        for payload in method_spec_payloads()
    }
    actual = {
        raw["method_id"]: raw
        for raw in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in spec_dir.glob("*.json")
        )
    }

    assert actual == expected


def test_weighted_geometry_profiles_are_code_owned_by_atomic_kernel() -> None:
    from shuxueshuo_server.solver.runtime.weighted_triangle_geometry import (
        WEIGHTED_TRIANGLE_GEOMETRY_PROFILES,
    )

    assert {
        profile.profile_id
        for profile in WEIGHTED_TRIANGLE_GEOMETRY_PROFILES
    } == {
        "sqrt2_right_isosceles",
        "weight2_30_60",
    }


def test_evaluate_point_has_no_retired_path_trial_hint() -> None:
    spec = MethodSpecRegistry.load_from_code().require(
        "evaluate_point_at_parameter"
    )

    assert spec.trial_error_hints == ()


def test_trial_error_hint_rejects_non_boolean_predicate() -> None:
    payload = next(
        item
        for item in method_spec_payloads()
        if item["method_id"] == "evaluate_point_at_parameter"
    )
    malformed = dict(payload)
    malformed["trial_error_hints"] = [{
        "error_contains": "synthetic failure",
        "code": "synthetic_hint",
        "requires_point_answer": "true",
    }]

    with pytest.raises(
        ValueError,
        match="requires_point_answer must be a boolean",
    ):
        parse_method_spec(malformed)


def test_method_explanation_placeholders_are_declared_roles() -> None:
    registry = MethodSpecRegistry.load_from_code()

    for spec in registry.specs.values():
        explanation = spec.explanation
        if explanation is None:
            continue
        templates = (
            explanation.student_goal_template,
            explanation.student_title_template,
            explanation.student_nav_title_template,
            *explanation.derive_templates,
            *explanation.box_templates,
        )
        placeholders = {
            match
            for template in templates
            for match in PLACEHOLDER_RE.findall(template)
        }

        assert placeholders <= set(explanation.role_schema), spec.method_id


def test_method_role_schema_descriptions_are_student_facing_chinese() -> None:
    for payload in method_spec_payloads():
        for section in ("explanation", "visual"):
            role_schema = (payload.get(section) or {}).get("role_schema") or {}
            for role_id, description in role_schema.items():
                assert ENGLISH_WORD_RE.search(str(description)) is None, (
                    payload["method_id"],
                    section,
                    role_id,
                    description,
                )


def test_curve_point_candidate_visual_spec_is_not_square_bound() -> None:
    spec = MethodSpecRegistry.load_from_code().require("point_candidates_from_curve_point_condition")

    assert spec.visual is not None
    assert spec.visual.role_schema == {
        "target_candidates": "由曲线条件得到的目标点候选。",
        "candidate_context_regions": "可选的候选几何上下文区域，例如候选正方形。",
    }
    assert [template["component"] for template in spec.visual.scene_templates] == [
        "CurvePointCandidateMarker",
    ]


def test_empty_student_nav_title_template_is_omitted_from_generated_json() -> None:
    generated = {
        payload["method_id"]: payload
        for payload in method_spec_payloads()
    }
    raw_specs = {
        raw["method_id"]: raw
        for raw in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in Path("../internal/method-specs").glob("*.json")
        )
    }

    for method_id, payload in generated.items():
        explanation = payload.get("explanation")
        if not isinstance(explanation, dict):
            continue
        assert explanation.get("student_nav_title_template") != "", method_id
        assert raw_specs[method_id].get("explanation", {}).get("student_nav_title_template") != "", method_id


def test_recipe_proof_outline_placeholders_are_declared_roles() -> None:
    registry = RecipeSpecRegistry.load_from_code()

    for spec in registry.specs.values():
        explanation = spec.explanation
        if explanation is None:
            continue
        placeholders = {
            match
            for template in explanation.proof_outline_templates
            for match in PLACEHOLDER_RE.findall(template)
        }
        assert placeholders <= set(explanation.role_schema), spec.recipe_id


def test_rejects_missing_required_field() -> None:
    with pytest.raises(ValueError, match="missing required"):
        parse_method_spec({"method_id": "broken"})


def _input(
    runtime_type: str,
    *,
    domain_type: str = "Expression",
    mode: str = "latest_state",
    **extra: object,
) -> dict[str, object]:
    state_kind = "expression" if mode == "latest_state" else None
    view = {"mode": mode, "domain_type": domain_type}
    if state_kind is not None:
        view["state_kind"] = state_kind
    return {
        "runtime_type": runtime_type,
        "domain_type": domain_type,
        "view": view,
        **extra,
    }


def test_rejects_unknown_input_type() -> None:
    with pytest.raises(ValueError, match="unknown input type"):
        parse_method_spec(
            {
                "method_id": "broken",
                "title": "Broken",
                "solves": ["derive_point_coordinate"],
                "inputs": {"x": _input("Unknown")},
                "outputs": {"derived_point": "Point"},
            }
        )


def test_accepts_known_output_union_type() -> None:
    spec = parse_method_spec(
        {
            "method_id": "union_output",
            "title": "Union Output",
            "solves": ["derive_expression"],
            "inputs": {"x": _input("Expression|MinimumExpression")},
            "outputs": {"value": "Expression|MinimumExpression"},
        }
    )

    assert spec.outputs["value"] == "Expression|MinimumExpression"


def test_rejects_runtime_union_with_empty_member() -> None:
    with pytest.raises(ValueError, match="unknown input type"):
        parse_method_spec(
            {
                "method_id": "broken_union",
                "title": "Broken Union",
                "solves": ["derive_expression"],
                "inputs": {"x": _input("Expression||MinimumExpression")},
                "outputs": {"value": "Expression"},
            }
        )


def test_method_purity_is_explicit_and_legacy_specs_are_conservative() -> None:
    raw = {
        "method_id": "synthetic_method",
        "title": "Synthetic",
        "solves": ["derive_expression"],
        "inputs": {"x": _input("Expression")},
        "outputs": {"value": "Expression"},
    }

    assert parse_method_spec(raw).is_pure is False
    assert parse_method_spec({**raw, "is_pure": True}).is_pure is True
    with pytest.raises(ValueError, match="is_pure must be a boolean"):
        parse_method_spec({**raw, "is_pure": "yes"})

    assert all(
        spec.is_pure
        for spec in MethodSpecRegistry.load_from_code().specs.values()
    )


def test_point_parameter_substitution_is_declared_by_method_spec() -> None:
    spec = MethodSpecRegistry.load_from_code().require(
        "evaluate_point_at_parameter"
    )

    assert spec.plan_transformer == "substitute_read_point_parameters"
    assert spec.plan_transformer_scope == "single_invocation"
    assert spec.reconciliation_validators == ("companion_symbol_coverage",)


@pytest.mark.parametrize(
    "method_id",
    (
        "parameter_from_expression_value",
        "parameter_from_minimum_value",
    ),
)
def test_student_parameter_solver_declares_runtime_complexity_gate(
    method_id: str,
) -> None:
    spec = MethodSpecRegistry.load_from_code().require(method_id)

    assert spec.plan_transformer == "validate_student_single_degree_of_freedom"
    assert spec.plan_transformer_scope == "all_invocations"
    assert spec.reconciliation_validators == ()


def test_reconciliation_validator_declarations_are_normalized() -> None:
    raw = {
        "method_id": "synthetic_method",
        "title": "Synthetic",
        "solves": ["derive_expression"],
        "inputs": {"x": _input("Expression")},
        "outputs": {"value": "Expression"},
        "reconciliation_validators": ["identity_check", "identity_check"],
    }

    assert parse_method_spec(raw).reconciliation_validators == (
        "identity_check",
    )
    with pytest.raises(
        ValueError,
        match="reconciliation_validators must be a list",
    ):
        parse_method_spec({**raw, "reconciliation_validators": "identity_check"})


def test_plan_transformer_scope_rejects_unknown_value() -> None:
    raw = {
        "method_id": "synthetic_method",
        "title": "Synthetic",
        "solves": ["derive_expression"],
        "inputs": {"x": _input("Expression")},
        "outputs": {"value": "Expression"},
        "plan_transformer_scope": "some_invocations",
    }

    with pytest.raises(ValueError, match="plan_transformer_scope"):
        parse_method_spec(raw)


def test_rejects_unknown_output_union_member() -> None:
    with pytest.raises(ValueError, match="unknown output type"):
        parse_method_spec(
            {
                "method_id": "broken_output",
                "title": "Broken Output",
                "solves": ["derive_expression"],
                "inputs": {"x": _input("Expression")},
                "outputs": {"value": "Expression|Unknown"},
            }
        )


def test_function_state_consumers_declare_symbolic_input_view_roles() -> None:
    specs = MethodSpecRegistry.load_from_code()
    consumers = {
        "filter_point_candidates_by_quadratic_curve": "parabola",
        "line_parabola_second_intersection_point": "parabola",
        "parameter_from_curve_point_on_quadratic": "quadratic",
        "point_candidates_from_curve_point_condition": "parabola",
        "point_on_parabola_at_x": "parabola",
        "quadratic_axis_parameterized_point": "parabola",
        "quadratic_axis_x_intercept_point": "parabola",
        "quadratic_vertex_point": "parabola",
        "quadratic_x_axis_intercept_point": "quadratic",
        "quadratic_y_axis_intercept_point": "quadratic",
    }

    for method_id, anchor_name in consumers.items():
        spec = specs.require(method_id)
        assert spec.inputs[anchor_name].symbolic_basis_role == "state_anchor"
        assert any(
            item.symbolic_basis_role == "align_to_anchor"
            for item in spec.inputs.values()
        )


def test_rejects_unknown_symbolic_basis_role() -> None:
    with pytest.raises(ValueError, match="invalid symbolic_basis_role"):
        parse_method_spec(
            {
                "method_id": "broken_symbolic_basis",
                "title": "Broken symbolic basis",
                "solves": ["derive_expression"],
                "inputs": {
                    "value": _input(
                        "Expression",
                        symbolic_basis_role="guess_from_name",
                    )
                },
                "outputs": {"value": "Expression"},
            }
        )
