"""State invariants independent of problem names, parameter names and coordinates."""
from types import SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.visual.math_state import (
    FrameMathStateResolver, resolve_attainment_constraints, validate_frame_math_state,
)
from shuxueshuo_server.solver.visual.models import VisualObject
from shuxueshuo_server.solver.visual.parameter_identity import verified_parameter_values_from_source
from shuxueshuo_server.solver.explanation.models import TeachingSource


def obj(ref, component="Parabola"):
    return VisualObject(ref, component, "curve", ({"scope_id": "problem"},), (ref,), "context")


def test_versions_are_visible_branch_local_and_preserve_distinct_objects():
    curves = [dict(id=ref, objectRef=identity, scopeId=scope, stateRevision=revision)
              for ref, identity, scope, revision in [
                  ("root", "f", "problem", 0), ("old", "f", "i", 1),
                  ("new", "f", "i", 2), ("future", "f", "i", 99),
                  ("sibling", "f", "ii", 100), ("other", "g", "i", 1)]]
    resolver = FrameMathStateResolver({"curves": curves}, {}, "i")
    projected, changes = resolver.project(tuple(map(obj, ["root", "old", "new", "other"])))
    assert changes == {"root": "new", "old": "new"}
    assert {r for o in projected for r in o.geometry_refs} == {"new", "other"}
    assert resolver.project((obj("old"),))[1] == {}
    assert FrameMathStateResolver({"curves": curves}, {}, "ii").project((obj("root"),))[1] == {}


def test_rebinding_drops_old_coordinate_text_and_keeps_anonymous_identity():
    geometry = {"pointMeta": {
        "old": {"label": "P", "scopeId": "problem"},
        "new": {"label": "P", "scopeId": "i"},
        "anonymous": {"label": "P", "scopeId": "i", "definition": "anonymous_step_result"}}}
    problem = {"entities": [{"entity_type": "point", "name": "P", "handle": "point:P"}]}
    projected, changes = FrameMathStateResolver(geometry, problem, "i").project(
        (obj("old", "Point"), obj("old", "CoordinateLabel"), obj("new", "Point"), obj("anonymous", "Point")))
    assert changes == {"old": "new"}
    assert {o.geometry_refs for o in projected} == {("new",), ("anonymous",)}
    assert not any(o.component == "CoordinateLabel" for o in projected)


def contract(name, value, exact=None):
    return {"name": name, "default_value": float(value),
            "mathematical_domain": {"kind": "exact", "value": str(exact)} if exact else {"kind": "interval"},
            "controls": ["slider"], "display_window": {}, "parameterized_points": {}}


@pytest.mark.parametrize("parameter,value", [("a", "3/4"), ("k", "2"), ("q", "5/12")])
def test_attainment_recomputes_relation_after_external_parameter_change(parameter, value):
    # Intersect C+t(B-C) with OG for B=(3/a,0), C=(0,-3), G=(3*sqrt(a*a+1)/a,-3).
    constraints = [{"parameter": "t", "equation": f"t/{parameter}+(t-1)*sqrt({parameter}**2+1)/{parameter}",
                    "domain": ["0", "1"]}]
    original = [contract(parameter, sp.Rational(value), value), contract("t", .7)]
    result, audit = resolve_attainment_constraints(original, constraints, active_parameters=set())
    expected = sp.sqrt(sp.Rational(value)**2+1)/(1+sp.sqrt(sp.Rational(value)**2+1))
    assert sp.simplify(sp.sympify(audit[0]["resolved_value"])-expected) == 0
    assert result[1]["controls"] == []
    assert original[1]["default_value"] == .7
    exploring, _ = resolve_attainment_constraints(original, constraints, active_parameters={"t"})
    assert exploring[1]["controls"] == ["slider"]


def test_constraint_failure_is_not_silently_replaced_by_sample_value():
    with pytest.raises(ValueError, match="ambiguous_attainment"):
        resolve_attainment_constraints([contract("t", .5)],
            [{"parameter": "t", "equation": "t*(t-1)", "domain": ["0", "1"]}], active_parameters=set())


def test_validator_checks_actual_geometry_even_when_audit_claims_zero_residual():
    frame = SimpleNamespace(objects=(), local_parameters=(), metadata={"mathematical_state": {
        "constraints": [{"geometry_refs": ["O", "M", "G"], "residual": "0"}]}})
    geometry = {"fixedPoints": {"O": [0,0], "M": [1,1], "G": [2,0]}}
    with pytest.raises(ValueError, match="constraint_failed"):
        validate_frame_math_state(frame, geometry)
    geometry["fixedPoints"]["M"] = [1,0]
    validate_frame_math_state(frame, geometry)


def test_closed_coefficients_publish_zero_but_not_open_relations():
    source = TeachingSource("s", "coefficients", {}, {
        "coefficients": {"runtime_type": "Coefficients", "value": {"a": "1", "b": 0, "c": "k-3"}}})
    assert verified_parameter_values_from_source(source) == {"a": "1", "b": "0"}
