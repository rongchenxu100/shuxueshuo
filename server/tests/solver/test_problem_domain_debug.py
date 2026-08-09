from __future__ import annotations

import json

from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_debug import (
    ProblemDomainDebugWriter,
)

from _problem_extraction_f3_support import make_f3_fixture
from test_problem_domain_retry import (
    _SequenceProvider,
    _domain_payload,
    _service,
)


def test_debug_pack_exposes_domain_tree_repair_cone_and_patch_diff(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path / "fixture")
    invalid = _domain_payload()
    expected_family = invalid["family_id"]
    invalid["family_id"] = "QuadraticWeightedPathMinimumSolver"
    revision = ProblemDraft.create(invalid).revision_id
    repair = {
        "schema_version": "problem-repair/v1",
        "base_revision_id": revision,
        "replacements": [
            {"unit_id": "family", "value": {"family_id": expected_family}}
        ],
        "additions": [],
        "removals": [],
    }
    provider = _SequenceProvider(
        [
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(repair, ensure_ascii=False),
        ]
    )
    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )

    output = tmp_path / "debug"
    review = ProblemDomainDebugWriter().write(result, output)

    assert review.is_file()
    expected_files = {
        "attempt-1.response-schema.json",
        "attempt-1.problem-domain.json",
        "attempt-1.problem-draft.json",
        "attempt-1.repair-cone.json",
        "attempt-2.problem-repair.json",
        "attempt-2.semantic-diff.json",
        "verified-problem.json",
        "solver-problem-ir.json",
        "context-before.json",
        "context-final.json",
        "run-result.json",
    }
    assert expected_files.issubset({item.name for item in output.iterdir()})
    diff = json.loads((output / "attempt-2.semantic-diff.json").read_text())
    assert diff["changed_unit_ids"] == ["family"]
    cone = json.loads((output / "attempt-1.repair-cone.json").read_text())
    assert "family" in cone["repairable_unit_ids"]
    redacted = (output / "attempt-1.provider-request.redacted.json").read_text()
    assert "data:image" not in redacted
    assert "base64" not in redacted
    assert "api_key" not in redacted
    response_schema = json.loads(
        (output / "attempt-2.response-schema.json").read_text()
    )
    assert response_schema["transport_response_format"]["type"] == "json_schema"
    assert response_schema["transport_response_format"]["json_schema"]["name"] == (
        "problem_repair_v1"
    )
    assert response_schema["schema"]["properties"]["schema_version"]["const"] == (
        "problem-repair/v1"
    )
    review_text = review.read_text()
    assert "Problem Domain Extraction · ACCEPTED" in review_text
    assert "Response schema · problem_repair_v1" in review_text
