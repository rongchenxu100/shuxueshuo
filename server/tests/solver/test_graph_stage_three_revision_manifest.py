"""Compact manifests preserve exact cards, frozen identity and legacy recovery."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from shuxueshuo_server.graph_lesson import domain_expression
from shuxueshuo_server.graph_lesson.stage_three import (
    calculations,
    driver,
    execution_contracts,
    runner,
)
from shuxueshuo_server.graph_lesson.stage_three.execution import _artifact
from shuxueshuo_server.graph_lesson.stage_three.revision_manifest import (
    manifest_ref,
    math_step_hash,
    revision_ref,
    validate_revision_ref,
)
from shuxueshuo_server.problem_understanding.identity import revision
from tests.solver.test_graph_stage_three_contract_cache import _arguments
from tests.solver.test_graph_stage_three_events import IDENTITY, fragment
from tests.solver.test_graph_stage_three_methods import ROOT, finish, start


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def test_legacy_card_hash_is_unchanged_and_binds_the_original_full_manifest():
    card = fragment()
    expected = revision({
        "content": {key: value for key, value in card.items() if key != "math_step_sha256"},
        "revisions": IDENTITY["revisions"],
    })
    original = deepcopy(card)
    assert math_step_hash(card) == card["math_step_sha256"] == expected
    assert math_step_hash(card, IDENTITY["revisions"]) == expected
    assert card == original
    with pytest.raises(ValueError, match="reference_mismatch"):
        math_step_hash(card, {"different": "f" * 64})


def test_manifest_reference_has_canonical_order_and_rejects_ambiguous_identity():
    manifest = {"first": "a" * 64, "second": "b" * 64}
    reference = manifest_ref(manifest)
    assert reference == manifest_ref(dict(reversed(list(manifest.items()))))
    assert revision_ref({"revisions": manifest}) == reference
    assert revision_ref({"revisions_ref": reference}) == reference
    validate_revision_ref({"revisions": manifest, "revisions_ref": reference}, manifest)
    with pytest.raises(ValueError, match="reference_mismatch"):
        revision_ref({"revisions": manifest, "revisions_ref": "0" * 64})
    with pytest.raises(ValueError, match="reference_mismatch"):
        validate_revision_ref({"revisions_ref": "0" * 64}, manifest)


@pytest.mark.parametrize("carrier", [{}, {"revisions_ref": "short"}, {"revisions": {}},
                                      {"revisions": {"bad": "not-a-digest"}}])
def test_invalid_manifest_identity_is_not_accepted(carrier):
    with pytest.raises(ValueError, match=r"revisions\."):
        revision_ref(carrier)


def test_new_state_cards_and_artifact_only_reference_the_frozen_manifest(tmp_path):
    arguments = _arguments()
    manifest = runner.fingerprint()
    arguments["revisions"] = manifest
    state = finish(driver.create_state(**arguments))
    reference = manifest_ref(manifest)
    assert "revisions" not in state and "revisions" not in state["trajectory"]
    assert state["revisions_ref"] == state["trajectory"]["revisions_ref"] == reference
    schema = Draft202012Validator(json.loads((ROOT / "internal/schemas/graph-math-step-v2.schema.json").read_text()))
    legacy_size, current_size = 0, 0
    for card in state["fragments"]:
        schema.validate(card)
        assert card["contract"] == "graph-math-step/v2" and "revisions" not in card
        assert card["revisions_ref"] == reference
        assert card["math_step_sha256"] == math_step_hash(card, manifest)
        legacy = {key: value for key, value in card.items() if key != "revisions_ref"}
        legacy.update(contract="graph-math-step/v1", revisions=manifest)
        legacy_size += _size(legacy)
        current_size += _size(card)
        forged = deepcopy(card)
        forged["revisions_ref"] = "0" * 64
        assert math_step_hash(forged) != card["math_step_sha256"]
        with pytest.raises(ValueError, match="reference_mismatch"):
            math_step_hash(forged, manifest)
        duplicated = {**card, "revisions": manifest}
        with pytest.raises(ValidationError):
            schema.validate(duplicated)
    assert current_size < legacy_size / 3
    state["status"] = "verified"
    route = _artifact(state, arguments["context"], tmp_path / "goals" / "one")
    assert route["contract"] == "graph-stage-three-route/v2"
    assert "revisions" not in route and route["revisions_ref"] == reference


def test_legacy_checkpoint_can_continue_without_rewriting_its_published_card():
    state = start()
    while not state["fragments"]:
        state = driver.advance(state)
    manifest = execution_contracts.revisions()
    # A persisted pre-v2 driver and card. Retain that exact prefix on resume.
    state["revisions"] = manifest
    del state["revisions_ref"]
    state["trajectory"].pop("revisions_ref")
    state["trajectory"].update(contract="graph-stage-three-route/v1", revisions=manifest)
    first = state["fragments"][0]
    first.pop("revisions_ref")
    first.update(contract="graph-math-step/v1", revisions=manifest)
    first["math_step_sha256"] = math_step_hash(first)
    state["trajectory"]["math_steps"][0]["math_step_sha256"] = first["math_step_sha256"]
    original = deepcopy(first)
    calculations._session_contracts.cache_clear()
    try:
        while state["status"] == "running":
            state = calculations.dispatch({"operation": "advance", "state": state})
        assert state["status"] == "method_complete"
        assert state["fragments"][0] == original
        assert math_step_hash(state["fragments"][0]) == original["math_step_sha256"]
        assert all(card["contract"] == "graph-math-step/v2" for card in state["fragments"][1:])
    finally:
        calculations._session_contracts.cache_clear()


def test_fingerprint_freezes_new_contracts_and_manifest_hash_implementation():
    frozen = runner.fingerprint()
    assert "internal/schemas/graph-math-step-v2.schema.json" in frozen
    assert "internal/schemas/graph-stage-three-route-v2.schema.json" in frozen
    assert "server/shuxueshuo_server/graph_lesson/stage_three/revision_manifest.py" in frozen


def test_fingerprint_freezes_shared_domain_expression_implementation():
    source = Path(domain_expression.__file__).resolve()
    assert runner.fingerprint()[str(source.relative_to(ROOT))] == sha256(source.read_bytes()).hexdigest()
