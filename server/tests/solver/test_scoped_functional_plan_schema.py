from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    SCOPED_FUNCTIONAL_PLAN_CONTRACT,
    SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH,
    ScopedFunctionalPlan,
    ScopedFunctionalPlanValidator,
    ScopedFunctionalScope,
    scoped_functional_plan_schema,
)


SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "schemas"
    / "functional-plan-v3.schema.json"
)


def test_python_schema_matches_checked_in_snapshot() -> None:
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == (
        scoped_functional_plan_schema()
    )


def test_reference_schema_exposes_entity_only_state_contract() -> None:
    definitions = scoped_functional_plan_schema()["$defs"]

    source_description = definitions["source_ref"]["description"]
    result_description = definitions["step_result_ref"]["description"]
    functional_description = definitions["functional_ref"]["description"]
    assert "only wire form for a named Entity" in source_description
    assert "producer dependencies" in source_description
    assert "anonymous results only" in result_description
    assert "must use its SourceRef" in result_description
    assert "every named Entity" in functional_description
    assert "without a named Math Entity identity" in functional_description


def test_scope_schema_is_expanded_to_four_non_recursive_levels() -> None:
    schema = scoped_functional_plan_schema()
    definitions = schema["$defs"]

    assert SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH == 4
    assert schema["properties"]["root_scope"] == {
        "$ref": "#/$defs/scope_level_0"
    }
    assert {
        name for name in definitions if name.startswith("scope_level_")
    } == {"scope_level_0", "scope_level_1", "scope_level_2", "scope_level_3"}
    assert "scope" not in definitions
    for level in range(3):
        assert definitions[f"scope_level_{level}"]["properties"]["children"][
            "items"
        ] == {"$ref": f"#/$defs/scope_level_{level + 1}"}
    assert "children" not in definitions["scope_level_3"]["properties"]
    assert '"$ref":"#/$defs/scope"' not in json.dumps(
        schema, ensure_ascii=False, separators=(",", ":")
    )


def test_scope_schema_accepts_up_to_four_levels_and_rejects_fifth() -> None:
    validator = ScopedFunctionalPlanValidator()

    def payload_for_depth(depth: int) -> dict[str, object]:
        scope: dict[str, object] = {"scope_ref": f"scope_{depth - 1}"}
        for level in reversed(range(depth - 1)):
            scope = {
                "scope_ref": f"scope_{level}",
                "children": [scope],
            }
        return {
            "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
            "root_scope": scope,
        }

    for depth in range(1, SCOPED_FUNCTIONAL_PLAN_MAX_SCOPE_DEPTH + 1):
        parsed, report = validator.validate_payload_with_report(
            payload_for_depth(depth)
        )
        assert report.ok, (depth, report.to_payload())
        assert parsed is not None

    parsed, report = validator.validate_payload_with_report(payload_for_depth(5))
    assert parsed is None
    assert report.issues
    assert report.issues[0].code == "functional.plan_schema_invalid"
    assert report.issues[0].path == (
        "$.root_scope.children[0].children[0].children[0]"
    )
    assert "'children' was unexpected" in report.issues[0].message


def test_canonical_payload_omits_empty_collections() -> None:
    payload = ScopedFunctionalPlan(
        root_scope=ScopedFunctionalScope(scope_ref="problem")
    ).to_payload()

    assert payload == {
        "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
        "root_scope": {"scope_ref": "problem"},
    }
    parsed, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok
    assert parsed is not None
    assert parsed.to_payload() == payload


def test_optional_empty_collections_are_removed_before_schema_validation() -> None:
    validator = ScopedFunctionalPlanValidator()
    payload = {
        "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
        "root_scope": {
            "scope_ref": "problem",
            "steps": [],
            "goals": [],
            "children": [
                {
                    "scope_ref": "i",
                    "steps": [],
                    "goals": [],
                    "children": [],
                }
            ],
        },
    }

    parsed, report = validator.validate_payload_with_report(payload)
    assert report.ok
    assert parsed is not None
    assert parsed.to_payload() == {
        "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
        "root_scope": {
            "scope_ref": "problem",
            "children": [{"scope_ref": "i"}],
        },
    }


def test_optional_empty_step_inputs_are_removed_before_schema_validation() -> None:
    payload = {
        "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
        "root_scope": {
            "scope_ref": "problem",
            "steps": [
                {
                    "step_id": "derive_parabola",
                    "capability_id": "quadratic_from_constraints",
                    "args": {"curve_points": "A", "known_coefficients": []},
                    "return_bindings": {},
                    "return_expectations": {},
                }
            ],
        },
    }

    parsed, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )

    assert report.ok
    assert parsed is not None
    assert parsed.root_scope.steps[0].to_payload() == {
        "step_id": "derive_parabola",
        "capability_id": "quadratic_from_constraints",
        "args": {"curve_points": "A"},
    }


def test_v1_payload_is_still_rejected() -> None:
    validator = ScopedFunctionalPlanValidator()

    parsed, report = validator.validate_payload_with_report(
        {"format": "functional_plan/v1", "scopes": []}
    )
    assert parsed is None
    assert not report.ok


def test_all_object_nodes_are_strict() -> None:
    schema = scoped_functional_plan_schema()
    object_nodes = [schema, *schema["$defs"].values()]

    assert all(
        node.get("additionalProperties") is False
        for node in object_nodes
        if node.get("type") == "object"
    )
