"""Compiler diagnostics route complete-candidate retries."""

import json

import pytest
from test_math_notation_workflow import Sequence, candidate, run

from shuxueshuo_server.problem_understanding import notation_compile
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    diagnose,
    permissions,
)


def test_repair_retry_accepts_a_complete_candidate_without_scope_grants(tmp_path):
    initial = candidate(["t > (0", "t ~ 1"])
    repaired = candidate(["t > 0"])
    model = Sequence(initial, repaired, {"status": "confirmed", "findings": []})
    result = run(tmp_path, model)
    assert result["status"] == "reviewed_candidate" and result["candidate"] == repaired
    assert result["content_calls"] == 2 and result["review_calls"] == 1
    request = json.loads(model.requests[1].prompt.user_prefix)
    assert "allowed_changes" not in request
    assert "change_guard" not in json.dumps(result["events"], ensure_ascii=False)


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
