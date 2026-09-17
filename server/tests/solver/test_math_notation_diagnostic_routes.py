"""Mixed compiler outcomes retain code-gap content while repairing local syntax."""

import json

import pytest
from test_math_notation_workflow import Sequence, candidate, run

from shuxueshuo_server.problem_understanding import notation_compile
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    diagnose,
    permissions,
)


def test_mixed_findings_repair_syntax_then_stop_on_remaining_code_gap(tmp_path):
    initial = candidate(["t > (0", "t ~ 1"])
    repaired = candidate(["t > 0", "t ~ 1"])
    model = Sequence(initial, repaired)
    result = run(tmp_path, model)
    assert result["status"] == "code_gap" and result["candidate"] == repaired
    assert result["content_calls"] == 2 and result["review_calls"] == 0
    assert result["continuation"]["blocked"] and not result["source_reviewed"]
    request = json.loads(model.requests[1].prompt.user_prefix)
    assert request["allowed_changes"] == [
        {
            "path": "/root/facts/0",
            "mode": "replace",
            "reason": "notation.unexpected_end",
        },
        {
            "path": "/root/uncertainties",
            "mode": "append",
            "reason": "source_stop_diagnostic",
        },
    ]
    assert {d["action"] for d in result["events"][0]["diagnostics"]} == {
        "repair",
        "code_gap",
    }
    assert all(d["action"] == "code_gap" for d in result["diagnostics"])
    assert run(tmp_path, Sequence()) == result


def test_mixed_repair_cannot_delete_the_unsupported_relation(tmp_path):
    initial = candidate(["t > (0", "t ~ 1"])
    repaired = candidate(["t > 0", "t ~ 1"])
    model = Sequence(initial, candidate(["t > 0"]), repaired)
    result = run(tmp_path, model)
    assert result["candidate"] == repaired and result["status"] == "code_gap"
    rejected = result["events"][1]
    assert not rejected["adopted"] and not rejected["change_guard"]["ok"]
    assert result["content_calls"] == 3 and result["review_calls"] == 0


def test_unstructured_source_gap_does_not_hide_independent_syntax_repair(tmp_path):
    uncertainty = [{"kind": "unstructured", "text": "原题新概念尚无结构化表示"}]
    initial = candidate(["t > (0"], uncertainties=uncertainty)
    repaired = candidate(["t > 0"], uncertainties=uncertainty)
    result = run(tmp_path, Sequence(initial, repaired))
    assert result["candidate"] == repaired and result["status"] == "code_gap"
    assert result["content_calls"] == 2 and result["review_calls"] == 0
    assert result["diagnostics"][0]["code"] == "unstructured"


@pytest.mark.parametrize("gap_path", ["/root", "/root/facts", "/root/facts/0"])
def test_overlapping_code_gap_never_grants_a_rewrite(gap_path):
    source = candidate(["t > (0"])
    diagnostics = [
        {
            "stage": "compile",
            "code": "notation.expected",
            "path": "/root/facts/0",
            "action": "repair",
        },
        {
            "stage": "compile",
            "code": "internal.exception",
            "path": gap_path,
            "action": "code_gap",
        },
    ]
    assert permissions(source, diagnostics) == []


@pytest.mark.parametrize(
    "code,action",
    [("notation.expected", "repair"), ("notation.unrecognized_token", "code_gap")],
)
@pytest.mark.parametrize(
    "message", ["internal.error: translated text", "新的说明\n包含：冒号 和空格"]
)
def test_diagnostic_route_uses_explicit_code_not_message(
    monkeypatch, code, action, message
):
    def fail(*args, **kwargs):
        raise NotationError(code, message)

    monkeypatch.setattr(notation_compile, "definition", fail)
    source = candidate(["t > 0"])
    report = notation_compile.NotationValidator().validate(source)
    routed = diagnose({"reports": {"ir": {"issues": report.issues}}}, source)
    assert routed and all(d["code"] == code and d["action"] == action for d in routed)
    assert all(message in d["message"] for d in routed)


def test_message_cannot_accidentally_become_an_error_code():
    with pytest.raises(ValueError, match="explicit dotted error code"):
        NotationError("notation.expected: got a different token")
