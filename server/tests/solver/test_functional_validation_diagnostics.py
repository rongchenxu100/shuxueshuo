import json

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    compact_validation_feedback,
    schema_validation_diagnostics,
    FunctionalPromptDiagnostic,
    FunctionalPromptDiagnosticProjector,
    diagnostic_authority_from_issue,
)
from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FunctionalScopeRetryError,
    _project_diagnostic,
)
from _functional_scope_retry_support import scope_retry_fixture


def _schema():
    # Many capabilities make a top-level oneOf message noisy. The chosen
    # branch uses the same allOf discriminator shape as the public contract.
    return {"type": "object", "properties": {"steps": {"type": "array", "items": {
        "oneOf": [
            {"allOf": [{"type": "object"}, {"properties": {
                "capability_id": {"const": f"cap_{i}"},
                "args": {"type": "object", "required": ["parabola"], "properties": {
                    "parabola": {"type": "string"},
                    "points": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                }, "additionalProperties": False},
            }, "required": ["capability_id", "args"]}]}
            for i in range(40)
        ]
    }}}}


def _diagnose(payload, schema=None):
    schema = schema or _schema()
    return schema_validation_diagnostics(
        tuple(Draft202012Validator(schema).iter_errors(payload)),
        payload=payload, code="functional.plan_content_schema_invalid",
    )


def test_matching_capability_reports_field_type_not_other_capabilities():
    payload = {"steps": [{"step_id": "consumer", "capability_id": "cap_17", "args": {
        "parabola": {"step_id": "producer", "return": "parabola"},
    }}]}
    issues = _diagnose(payload)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["path"] == "$['steps'][0]['args']['parabola']"
    assert issue["details"]["capability_id"] == "cap_17"
    assert issue["details"]["step_id"] == "consumer"
    assert issue["details"]["expected"] == {"type": "string", "reference_form": "SourceRef"}
    assert issue["details"]["observed"]["reference_form"] == "StepResultRef"
    assert "Changing reference syntax does not grant visibility" in issue["details"]["reference_policy"]
    prompt = compact_validation_feedback(issues)
    assert prompt[0]["details"]["diagnostic_id"] == issue["details"]["diagnostic_id"]
    assert "schema_path" not in prompt[0]["details"]
    assert len(json.dumps(prompt)) < 1600
    assert "cap_16" not in json.dumps(prompt)


def test_unknown_capability_does_not_guess_argument_contract():
    issues = _diagnose({"steps": [{"step_id": "s", "capability_id": "unknown", "args": {}}]})
    assert len(issues) == 1
    assert issues[0]["path"].endswith("['capability_id']")
    assert issues[0]["details"]["observed"]["value"] == "unknown"
    assert len(issues[0]["details"]["expected"]["capability_ids"]) == 40
    prompt = compact_validation_feedback(issues)
    assert {"omitted_items": 32} in prompt[0]["details"]["expected"]["capability_ids"]


def test_nested_union_uses_array_branch_and_keeps_item_path():
    issues = _diagnose({"steps": [{"step_id": "s", "capability_id": "cap_17", "args": {
        "parabola": "p", "points": ["A", False],
    }}]})
    assert len(issues) == 1
    assert issues[0]["path"].endswith("['points'][1]")
    assert issues[0]["details"]["observed"]["type"] == "boolean"


def test_ambiguous_union_preserves_alternatives_without_picking_one():
    schema = {"oneOf": [{"type": "object", "required": ["x"]}, {"type": "object", "required": ["y"]}]}
    issues = _diagnose({}, schema)
    assert issues[0]["path"] == "$"
    assert issues[0]["details"]["expected"]["alternatives"] == schema["oneOf"]
    assert not _diagnose({"x": 1}, schema)


def test_missing_and_extra_arguments_are_independent_and_compact():
    issues = _diagnose({"steps": [{"step_id": "s", "capability_id": "cap_17", "args": {"extra": "X"}}]})
    assert len(issues) == 2
    assert {x["details"]["validator"] for x in issues} == {"required", "additionalProperties"}
    assert any(x["path"].endswith("['parabola']") for x in issues)
    assert len(compact_validation_feedback((*issues, *issues))) == 2


def test_retry_and_projection_keep_path_and_full_evidence_separate():
    issues = _diagnose({"steps": [{"step_id": f"s{i}", "capability_id": "cap_17", "args": {"parabola": ["x" * 5000]}} for i in range(20)]})
    failure = FunctionalScopeRetryError.from_issues(issues)
    full = failure.to_payload()
    prompt = failure.to_prompt_payload()
    assert len(full["details"]["diagnostics"]) == 20
    assert prompt["path"] == issues[0]["path"]
    assert "functional.diagnostics_truncated" in json.dumps(prompt)
    assert len(json.dumps(prompt, ensure_ascii=False)) < 14000
    assert full["details"]["diagnostics"][0]["details"]["observed"]["value"][0] == "x" * 5000
    projected = _project_diagnostic(prompt, forbidden_values=frozenset())
    assert projected == prompt


def test_public_runtime_projection_preserves_owner_evidence_and_path(tmp_path):
    fixture = scope_retry_fixture(tmp_path)
    issue = {
        "code": "functional.step_scope_visibility_drift", "path": "$.steps['consumer'].args['parabola']",
        "message": "invisible producer", "details": {
            "step_id": "consumer", "capability_id": "quadratic_x_intercepts", "scope_id": "ii",
            "producer": {"step_id": "producer", "scope_ref": "i", "goal_ref": "i_1.parabola"},
            "consumer": {"step_id": "consumer", "scope_ref": "ii", "goal_ref": "ii.a"},
            "repair_action": "repair_input_binding",
            "allowed_actions": ["rewrite_open_scopes_with_compatible_visible_producers"],
        },
    }
    authority = diagnostic_authority_from_issue(issue, stage="validation")
    prompt = FunctionalPromptDiagnosticProjector().project(authority, fixture.binding_catalog, fixture.planning_context).to_payload()
    assert prompt["path"] == issue["path"]
    assert prompt["step_id"] == "consumer"
    assert prompt["details"]["producer"] == issue["details"]["producer"]
    assert prompt["details"]["consumer"] == issue["details"]["consumer"]
    assert "authorized_scope_refs" not in prompt["details"]
    assert FunctionalPromptDiagnostic.from_payload(prompt).to_payload() == prompt


def test_ref_union_preserves_resolved_type_and_missing_return_path():
    schema = {"$defs": {"source": {"type": "string"}, "result": {
        "type": "object", "required": ["step_id", "return"],
        "properties": {"step_id": {"type": "string"}, "return": {"type": "string"}},
    }}, "oneOf": [{"$ref": "#/$defs/source"}, {"$ref": "#/$defs/result"}]}
    missing = _diagnose({"step_id": "s"}, schema)
    assert len(missing) == 1
    assert missing[0]["path"] == "$['return']"
    bad = _diagnose(False, schema)
    assert {item["type"] for item in bad[0]["details"]["expected"]["alternatives"]} == {"string", "object"}
    assert not _diagnose({"step_id": "s", "return": "r"}, schema)


def test_large_observed_value_keeps_first_root_in_bounded_feedback():
    payload = {"steps": [{"step_id": "s", "capability_id": "cap_17", "args": {
        "parabola": {str(i): ["x" * 5000 for _ in range(15)] for i in range(50)},
    }}]}
    issues = _diagnose(payload)
    prompt = compact_validation_feedback(issues)
    assert prompt[0]["code"] == issues[0]["code"]
    assert prompt[0]["details"]["step_id"] == "s"
    assert prompt[0]["details"]["observed"]["truncated"]
    assert len(json.dumps(prompt, ensure_ascii=False)) < 3000
