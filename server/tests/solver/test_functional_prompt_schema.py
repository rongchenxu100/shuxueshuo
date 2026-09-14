from copy import deepcopy
from itertools import product
import json

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.runtime.functional_prompt_schema import compact_prompt_schema
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame, functional_plan_content_schema,
)
from _functional_scope_retry_support import scope_retry_fixture


def test_compaction_preserves_validation_and_does_not_rewrite_literal_data():
    repeated = {"type": "string", "enum": ["named_object_" + str(i) for i in range(12)]}
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"source": repeated},
        "type": "object", "additionalProperties": False,
        "properties": {
            "a": repeated, "b": repeated,
            "literal": {"const": {"description": "data, not a schema annotation", "properties": {"x": repeated}}},
            "c": {"allOf": [{"$ref": "#/$defs/source"}], "enum": ["named_object_0"]},
        },
        "required": ["a", "b"],
        "description": "Repeated prose belongs in the capability catalog.",
    }
    original = deepcopy(schema)
    compact = compact_prompt_schema(schema)
    assert schema == original
    Draft202012Validator.check_schema(compact)
    assert len(json.dumps(compact)) < len(json.dumps(schema))
    before, after = Draft202012Validator(schema), Draft202012Validator(compact)
    values = [None, 1, "named_object_0", "named_object_1", "unknown", []]
    for a, b, c in product(values, repeat=3):
        candidate = {"a": a, "b": b, "c": c}
        assert before.is_valid(candidate) == after.is_valid(candidate)
    assert after.is_valid({"a": "named_object_0", "b": "named_object_1", "literal": schema["properties"]["literal"]["const"]})


def test_prompt_omits_distinct_object_enumerations_but_runtime_keeps_them(tmp_path):
    fixture = scope_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context)
    runtime = functional_plan_content_schema(frame, capability_catalog=fixture.capability_catalog)
    prompt = functional_plan_content_schema(frame, capability_catalog=fixture.capability_catalog, for_prompt=True)

    def validator(schema):
        return Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/step"})

    repeated_point = {
        "step_id": "probe", "capability_id": "line_intersection_point",
        "args": {"line1_p1": "A", "line1_p2": "A", "line2_p1": "C", "line2_p2": "D"},
    }
    assert validator(prompt).is_valid(repeated_point)
    assert not validator(runtime).is_valid(repeated_point)
    # Wire types are still strict in the compact prompt.
    wrong_ref = {"step_id": "probe", "capability_id": "quadratic_x_axis_intercept_point", "args": {"parabola": {"step_id": "old", "return": "parabola"}}}
    assert not validator(prompt).is_valid(wrong_ref)
    assert "\"not\":" not in json.dumps(prompt, separators=(",", ":"))
