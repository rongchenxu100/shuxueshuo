"""Historical transport identification and independent KPI cohorts."""

import json

import pytest

from shuxueshuo_server.problem_understanding.transport_accounting import (
    request_image_transport,
    transport_cohorts,
    workflow_image_transport,
)


def request(*parts):
    return {"messages": [{"role": "user", "content": list(parts)}]}


FILES = {"type": "file", "pending_upload": True}
BASE64 = {"type": "image_url", "image_url": {"url": "artifact://sha256"}}


@pytest.mark.parametrize(
    "payload,expected",
    [
        (request(FILES), "files"),
        (request(BASE64), "base64"),
        (request(FILES, BASE64), "mixed"),
        ({}, "unknown"),
        (
            request(
                {"type": "image_url", "image_url": {"url": "https://example.com/p.png"}}
            ),
            "unknown",
        ),
        ({"image_transport": {"mode": "files"}, **request(BASE64)}, "mixed"),
    ],
)
def test_transport_is_read_from_request_evidence(payload, expected):
    assert request_image_transport(payload) == expected


def test_missing_historical_request_is_not_assumed_base64(tmp_path):
    ledger = {"calls": [{"directory": "calls/01-extract", "file_api_calls": 0}]}
    (tmp_path / "ledger.json").write_text(json.dumps(ledger))
    assert workflow_image_transport(tmp_path) == "unknown"
    call = tmp_path / "calls/01-extract"
    call.mkdir(parents=True)
    # Zero uploads can mean a Files cache hit; it does not identify base64.
    (call / "request.json").write_text(json.dumps(request(FILES)))
    assert workflow_image_transport(tmp_path) == "files"
    second = tmp_path / "calls/02-review"
    second.mkdir()
    (second / "request.json").write_text(json.dumps(request(BASE64)))
    ledger["calls"].append({"directory": "calls/02-review"})
    (tmp_path / "ledger.json").write_text(json.dumps(ledger))
    assert workflow_image_transport(tmp_path) == "mixed"


def test_files_and_base64_quality_cost_and_time_are_not_merged():
    rows = {
        "file-case": {
            "image_transport": "files",
            "passed": True,
            "first_passed": True,
            "elapsed_seconds": 3.5,
            "file_api_calls": 2,
            "stages": {"extract": {"input_tokens": 100, "output_tokens": 20}},
        },
        "base64-case": {
            "image_transport": "base64",
            "passed": False,
            "first_passed": False,
            "elapsed_seconds": 10,
            "file_api_calls": 0,
            "usage": {"input_tokens": 200, "output_tokens": 30},
        },
        "no-evidence": {"passed": True},
    }
    result = transport_cohorts(rows)
    assert set(result) == {"files", "base64", "unknown"}
    assert result["files"]["cases"] == ["file-case"]
    assert result["files"]["passed"] == 1 and result["base64"]["passed"] == 0
    assert result["files"]["elapsed_seconds"] == 3.5
    assert result["base64"]["elapsed_seconds"] == 10
    assert result["files"]["input_tokens"] == 100
    assert result["base64"]["input_tokens"] == 200
    assert result["unknown"]["input_tokens"] is None
    assert result["unknown"]["elapsed_seconds"] is None
