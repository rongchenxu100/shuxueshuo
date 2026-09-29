"""Artifact publication is deduplicated by content, never object identity."""

import json
from dataclasses import dataclass
from hashlib import sha256

import pytest
from shuxueshuo_server.solver.runtime.llm_debug import DebugArtifactJournal


def test_same_role_version_materialized_once_and_mutation_detected(tmp_path):
    journal = DebugArtifactJournal(tmp_path)
    source = {"nested": [1, {"value": 2}]}
    first = journal.write_json("attempt-1.checkpoint.json", source)
    counts = dict(journal.metrics)
    assert journal.write_json("attempt-1.checkpoint.json", source) == first
    assert journal.metrics["serializations"] == counts["serializations"] + 1
    assert journal.metrics["writes"] == counts["writes"]
    source["nested"][1]["value"] = 3
    second = journal.write_json("attempt-1.checkpoint.json", source)
    assert second["sha256"] != first["sha256"]
    assert json.loads((tmp_path / first["file"]).read_text())["nested"][1]["value"] == 2
    assert (
        json.loads((tmp_path / second["file"]).read_text())["nested"][1]["value"] == 3
    )
    assert (
        json.loads((tmp_path / "attempt-1.checkpoint.json").read_text())["nested"][1][
            "value"
        ]
        == 3
    )


def test_dataclass_recreated_same_content_and_attempts_are_separate(tmp_path):
    @dataclass(frozen=True)
    class Payload:
        values: tuple

    journal = DebugArtifactJournal(tmp_path)
    first = journal.write_json("attempt-1.request.json", Payload((1, 2)))
    journal.write_json("attempt-1.request.json", Payload((1, 2)))
    assert journal.metrics["serializations"] == 2
    second = journal.write_json("attempt-2.request.json", Payload((1, 2)))
    assert second["file"] == first["file"]
    assert journal.metrics["writes"] == 1
    assert (tmp_path / "attempt-2.request.json").exists()
    assert journal.metrics["serializations"] == 3


def test_failed_publish_does_not_mark_version_saved(tmp_path, monkeypatch):
    from shuxueshuo_server.solver.runtime import llm_debug

    journal = DebugArtifactJournal(tmp_path)
    journal.write_json("attempt-1.request.json", {"v": 1})
    original = llm_debug.os.replace
    monkeypatch.setattr(
        llm_debug.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk"))
    )
    with pytest.raises(OSError):
        journal.write_json("attempt-1.request.json", {"v": 2})
    assert json.loads((tmp_path / "attempt-1.request.json").read_text()) == {"v": 1}
    monkeypatch.setattr(llm_debug.os, "replace", original)
    saved = journal.write_json("attempt-1.request.json", {"v": 2})
    assert (
        sha256((tmp_path / saved["file"]).read_bytes()).hexdigest() == saved["sha256"]
    )


def test_journal_rejects_unknown_mode_and_path_escape(tmp_path):
    with pytest.raises(ValueError):
        DebugArtifactJournal(tmp_path, mode="off")
    journal = DebugArtifactJournal(tmp_path)
    with pytest.raises(ValueError):
        journal.write_json("../elsewhere.json", {})


def test_return_to_earlier_version_does_not_rewrite_file(tmp_path):
    journal = DebugArtifactJournal(tmp_path)
    a = journal.write_json("attempt-1.report.json", {"v": 1})
    journal.write_json("attempt-1.report.json", {"v": 2})
    counts = dict(journal.metrics)
    assert journal.write_json("attempt-1.report.json", {"v": 1}) == a
    assert journal.metrics["serializations"] == counts["serializations"] + 1
    assert journal.metrics["conversions"] == counts["conversions"]
    assert journal.metrics["writes"] == counts["writes"]


@pytest.mark.parametrize("mode", ["full_diagnostic", "compact_audit"])
def test_phase_history_and_failure_evidence_survive_next_attempt(tmp_path, mode):
    from dataclasses import replace
    from types import SimpleNamespace

    from shuxueshuo_server.solver.runtime.functional_scope_retry import (
        FunctionalScopeRetryError,
    )
    from shuxueshuo_server.solver.runtime.orchestrator import _write_debug_attempt
    from test_runtime_orchestrator_scoped_debug import _attempt

    journal = DebugArtifactJournal(tmp_path, mode=mode)
    first = _attempt(1, "functional-plan-content/v2")
    requested = replace(
        first, evidence_phase="requested", raw_response=None, llm_metadata=None
    )
    failed = replace(
        first, error=FunctionalScopeRetryError("invalid", "$", "bad candidate")
    )
    for record in (requested, failed, _attempt(2, "functional-plan-content/v2")):
        _write_debug_attempt(
            tmp_path,
            record.semantic_attempt,
            SimpleNamespace(),
            None,
            None,
            scoped_attempt=record,
            journal=journal,
        )
    history = json.loads((tmp_path / "attempt-1.evidence-history.json").read_text())
    assert [v["phase"] for v in history["versions"]] == ["requested", "completed"]
    indexes = [
        json.loads((tmp_path / v["file"]).read_text()) for v in history["versions"]
    ]
    assert indexes[0]["artifacts"]["raw-response"]["status"] == "not_available"
    assert indexes[1]["artifacts"]["attempt-error"]["status"] == "saved"
    for index in indexes:
        for saved in index["artifacts"].values():
            if saved["status"] == "saved":
                assert (
                    sha256((tmp_path / saved["file"]).read_bytes()).hexdigest()
                    == saved["sha256"]
                )
    assert (
        json.loads((tmp_path / "attempt-1.raw-response.json").read_text())["text"]
        == first.raw_response
    )
    assert (tmp_path / "attempt-1.raw-response.txt").read_text() == first.raw_response
    assert (tmp_path / "attempt-1.prompt.json").exists() == (mode == "full_diagnostic")


def test_modes_preserve_identical_canonical_evidence(tmp_path):
    from types import SimpleNamespace

    from shuxueshuo_server.solver.runtime.orchestrator import _write_debug_attempt
    from test_runtime_orchestrator_scoped_debug import _attempt

    artifacts = []
    for mode in ("full_diagnostic", "compact_audit"):
        directory = tmp_path / mode
        _write_debug_attempt(
            directory,
            1,
            SimpleNamespace(),
            None,
            None,
            scoped_attempt=_attempt(1, "functional-plan-content/v2"),
            journal=DebugArtifactJournal(directory, mode=mode),
        )
        index = json.loads((directory / "attempt-1.evidence-index.json").read_text())
        artifacts.append(
            {
                role: json.loads((directory / entry["file"]).read_text())
                if entry["status"] == "saved"
                else entry
                for role, entry in index["artifacts"].items()
            }
        )
    assert artifacts[0] == artifacts[1]


def test_mode_config_sources_and_validation(monkeypatch):
    from shuxueshuo_server.solver.runtime.config import (
        SolverRuntimeConfig,
        SolverRuntimeConfigError,
    )

    monkeypatch.setenv("SOLVER_LLM_DEBUG_ARTIFACT_MODE", "compact_audit")
    assert SolverRuntimeConfig.from_sources().llm_debug_artifact_mode == "compact_audit"
    assert (
        SolverRuntimeConfig.from_sources(
            llm_debug_artifact_mode="full_diagnostic"
        ).llm_debug_artifact_mode
        == "full_diagnostic"
    )
    with pytest.raises(SolverRuntimeConfigError):
        SolverRuntimeConfig(llm_debug_artifact_mode="off")


@pytest.mark.parametrize("mode", ["full_diagnostic", "compact_audit"])
def test_real_retry_keeps_rejected_response_and_verified_checkpoint(tmp_path, mode):
    from copy import deepcopy
    from types import SimpleNamespace

    from shuxueshuo_server.solver.runtime.context import ContextBuilder
    from shuxueshuo_server.solver.runtime.functional_plan_content import (
        FunctionalPlanAuthorityFrame,
        functional_plan_content_from_plan,
    )
    from shuxueshuo_server.solver.runtime.functional_scope_retry import (
        ScopedFunctionalScopeRetryService,
    )
    from shuxueshuo_server.solver.runtime.orchestrator import _write_debug_attempt
    from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
        ScopedFunctionalPlanValidator,
    )
    from shuxueshuo_server.solver.runtime.strategy_payload import StrategyPayloadBuilder
    from test_functional_scope_retry import goal_retry_fixture

    fixture = goal_retry_fixture(tmp_path)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok
    valid = functional_plan_content_from_plan(
        plan,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(
            fixture.planning_context
        ),
    ).to_payload()
    invalid = deepcopy(valid)
    next(iter(invalid["goal_plans"].values())).pop("answer_from")
    responses = iter([json.dumps(invalid), json.dumps(valid)])
    client = SimpleNamespace(complete=lambda payload: next(responses))
    directory = tmp_path / "audit"
    journal = DebugArtifactJournal(directory, mode=mode)
    result = ScopedFunctionalScopeRetryService(
        client,
        payload_builder=StrategyPayloadBuilder(scoped_functional_few_shot_examples=[]),
    ).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=2,
        attempt_observer=lambda attempt: _write_debug_attempt(
            directory,
            attempt.semantic_attempt,
            SimpleNamespace(),
            None,
            None,
            scoped_attempt=attempt,
            journal=journal,
        ),
    )
    assert result.status == "accepted" and len(result.attempts) == 2
    first = json.loads((directory / "attempt-1.evidence-index.json").read_text())
    second = json.loads((directory / "attempt-2.evidence-index.json").read_text())
    assert first["artifacts"]["attempt-error"]["status"] == "saved"
    assert second["artifacts"]["verified-execution"]["status"] == "saved"
    assert second["artifacts"]["checkpoint"]["status"] == "saved"
    for path in directory.glob("attempt-*.evidence-history.json"):
        history = json.loads(path.read_text())
        for revision in history["versions"]:
            data = (directory / revision["file"]).read_bytes()
            assert sha256(data).hexdigest() == revision["sha256"]
            for artifact in json.loads(data)["artifacts"].values():
                if artifact["status"] == "saved":
                    assert (
                        sha256((directory / artifact["file"]).read_bytes()).hexdigest()
                        == artifact["sha256"]
                    )


def test_scalar_subclasses_match_legacy_json(tmp_path):
    from enum import Enum, IntEnum

    class Number(IntEnum):
        ONE = 1

    class Text(str, Enum):
        NAME = "name"

    value = {"number": Number.ONE, "text": Text.NAME}
    journal = DebugArtifactJournal(tmp_path)
    saved = journal.write_json("attempt-1.request.json", value)
    assert json.loads((tmp_path / saved["file"]).read_text()) == json.loads(
        json.dumps(value)
    )


def test_publication_encodes_once_without_recursive_snapshot_pass(tmp_path, monkeypatch):
    from shuxueshuo_server.solver.runtime import llm_debug

    journal = DebugArtifactJournal(tmp_path)
    original_dumps = llm_debug.json.dumps
    calls = []

    def encode(*a, **kw):
        calls.append(a[0])
        return original_dumps(*a, **kw)

    def forbidden(*a, **kw):
        raise AssertionError("recursive snapshot conversion")

    monkeypatch.setattr(llm_debug, "safe_debug_json", forbidden)
    monkeypatch.setattr(llm_debug.json, "dumps", encode)
    source = {"v": [1, 2]}
    original = journal.write_json("attempt-1.report.json", source)
    assert journal.write_json("attempt-1.report.json", {"v": (1, 2)}) == original
    assert len(calls) == 2
    assert journal.metrics["conversions"] == 0
    assert journal.metrics["writes"] == 1
    # Only small immutable-file references survive publication, not payloads.
    assert journal._latest["attempt-1.report.json"] == original
    assert all(set(v) == {"file", "sha256", "status"} for v in journal._versions.values())


def test_release_drops_payloads_and_reopen_preserves_history(tmp_path):
    journal = DebugArtifactJournal(tmp_path)
    journal.write_index(
        "attempt-1", {"semantic_attempt": 1, "phase": "requested", "artifacts": {}}
    )
    journal.release_snapshots()
    assert not journal._latest and not journal._versions and not journal._history
    reopened = DebugArtifactJournal(tmp_path)
    reopened.write_index(
        "attempt-1", {"semantic_attempt": 1, "phase": "completed", "artifacts": {}}
    )
    history = json.loads((tmp_path / "attempt-1.evidence-history.json").read_text())
    assert [v["phase"] for v in history["versions"]] == ["requested", "completed"]


@pytest.mark.parametrize("mode", ["full_diagnostic", "compact_audit"])
def test_returned_attempt_content_is_checked_even_after_completed_event(
    tmp_path, monkeypatch, mode
):
    from dataclasses import replace

    from _problem_planning_support import cached_planning_binding_fixture
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
        StrategyPlanner,
    )

    original = StrategyPlanner.run_scoped

    def wrapped(self, inputs, *, max_attempts=3, attempt_observer=None):
        result = original(
            self, inputs, max_attempts=max_attempts, attempt_observer=attempt_observer
        )
        first = result.attempts[0]
        updated = replace(
            first, payload={**first.payload, "audit_marker": "returned revision"}
        )
        return replace(result, attempts=(updated, *result.attempts[1:]))

    monkeypatch.setattr(StrategyPlanner, "run_scoped", wrapped)
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    runtime = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        debug_dir=tmp_path,
        debug_artifact_mode=mode,
    )
    bundle, *_ = cached_planning_binding_fixture("tj-2026-heping-yimo-25")
    assert runtime.solve_verified(bundle).ok
    if mode == "full_diagnostic":
        assert (tmp_path / "attempt-1.problem-bundle-authority.json").exists()
        assert (tmp_path / "attempt-1.problem-planning-binding-catalog.json").exists()
    assert (
        json.loads((tmp_path / "attempt-1.request.json").read_text())[
            "planner_payload"
        ]["audit_marker"]
        == "returned revision"
    )
    history = json.loads((tmp_path / "attempt-1.evidence-history.json").read_text())
    completed = [v for v in history["versions"] if v["phase"] == "completed"]
    assert len(completed) == 2
    assert not runtime.debug_journal._latest and not runtime.debug_journal._versions


def test_cross_role_content_versions_are_shared_and_readonly(tmp_path):
    journal = DebugArtifactJournal(tmp_path)
    first = journal.write_json("attempt-1.candidate-plan.json", {"plan": [1]})
    second = journal.write_json("attempt-1.canonical-plan.json", {"plan": [1]})
    assert first == second
    version = tmp_path / first["file"]
    assert version.suffix == ".json"
    assert version.stat().st_mode & 0o222 == 0
    assert version.stat().st_ino == (tmp_path / "attempt-1.canonical-plan.json").stat().st_ino
    assert journal.metrics["writes"] == 1


def test_signed_zero_has_distinct_json_version(tmp_path):
    journal = DebugArtifactJournal(tmp_path)
    positive = journal.write_json("value.json", {"v": [0.0]})
    negative = journal.write_json("value.json", {"v": [-0.0]})
    assert positive != negative
    assert "-0.0" in (tmp_path / "value.json").read_text()
    assert journal.write_json("value.json", {"v": [0.0]}) == positive


def test_unsupported_hardlinks_fall_back_to_atomic_copy(tmp_path, monkeypatch):
    import errno

    from shuxueshuo_server.solver.runtime import llm_debug

    def unsupported(*args):
        raise OSError(errno.ENOTSUP, "hardlinks unsupported")

    monkeypatch.setattr(llm_debug.os, "link", unsupported)
    journal = DebugArtifactJournal(tmp_path)
    first = journal.write_json("value.json", {"v": 1})
    journal.write_json("value.json", {"v": 2})
    assert json.loads((tmp_path / first["file"]).read_text()) == {"v": 1}
    assert json.loads((tmp_path / "value.json").read_text()) == {"v": 2}
    assert (tmp_path / "value.json").stat().st_mode & 0o222 == 0
    assert journal.metrics["writes"] == 4


@pytest.mark.parametrize('nested', [False, True])
def test_debug_json_preserves_legacy_nonstring_key_conversion(tmp_path, nested):
    from types import MappingProxyType

    from shuxueshuo_server.solver.runtime.llm_debug import safe_debug_json

    @dataclass(frozen=True)
    class K:
        value: int

    @dataclass(frozen=True)
    class Payload:
        data: object

    source = {('a', 'b'): 1, K(1): 2}
    value = Payload({'items': [MappingProxyType(source), source]}) if nested else source
    journal = DebugArtifactJournal(tmp_path)
    saved = journal.write_json('attempt-1.request.json', value)
    raw = (tmp_path / saved['file']).read_bytes()
    assert json.loads(raw) == safe_debug_json(value)
    assert sha256(raw).hexdigest() == saved['sha256']
    assert journal.metrics['conversions'] == 1
    assert journal.metrics['serializations'] == 2
    assert source == {('a', 'b'): 1, K(1): 2}


def test_ordinary_debug_json_does_not_walk_payload_for_key_conversion(tmp_path, monkeypatch):
    from shuxueshuo_server.solver.runtime import llm_debug

    def forbidden(*args):
        raise AssertionError('ordinary payload recursively normalized')
    monkeypatch.setattr(llm_debug, 'safe_debug_json', forbidden)
    journal = DebugArtifactJournal(tmp_path)
    saved = journal.write_json('attempt-1.request.json', {'rows': [{'value': 2}]})
    assert json.loads((tmp_path / saved['file']).read_bytes()) == {'rows': [{'value': 2}]}
    assert journal.metrics['serializations'] == 1
    assert journal.metrics['conversions'] == 0
