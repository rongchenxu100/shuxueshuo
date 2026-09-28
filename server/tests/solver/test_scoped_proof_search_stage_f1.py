"""F1 metadata identity, authenticated memo boundaries and incremental restore."""

import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from shuxueshuo_server.solver.math_kernel.proof_algebra import digest
from shuxueshuo_server.solver.math_kernel.proof_facts import (
    FactValidity,
    VerifiedMathFact,
    canonical,
)
from shuxueshuo_server.solver.runtime.scoped_proof_facts import FactSnapshot
from test_scoped_proof_facts_stage_c import environment, publish


def test_metadata_freezes_input_lists_and_payload_copies():
    refs = ["definition"]
    validity = FactValidity("q", definition_refs=refs)
    dependencies = ["dependency"]
    fact = VerifiedMathFact(
        "x>0",
        [["x", "q/x"]],
        validity,
        "domain",
        "source",
        dependency_fact_refs=dependencies,
    )
    expected = fact.to_payload()
    refs.append("another")
    dependencies.append("another")
    assert fact.to_payload() == expected
    assert fact.fact_id == digest(asdict(fact))
    payload = fact.to_payload()
    payload["validity"]["definition_refs"].append("poison")
    assert fact.to_payload() == expected
    changed = replace(fact, source="different")
    assert (
        changed.statement_key == fact.statement_key and changed.fact_id != fact.fact_id
    )
    assert fact.canonical_bytes == canonical(expected).encode()


def test_commit_and_snapshot_preserve_legacy_hashes_and_fresh_payloads():
    store = environment()
    commit = publish(store)
    payload = commit.to_payload()
    assert commit.canonical_bytes == canonical(payload).encode()
    assert store.snapshot.committed_manifest_hash == digest(
        (store.snapshot.source_hash, [payload])
    )
    payload["facts"][0]["relation"] = "x<0"
    payload["records"].clear()
    assert commit.to_payload()["records"]
    assert commit.to_payload()["facts"][0]["relation"] != "x<0"
    commits = [commit]
    snapshot = FactSnapshot(
        store.snapshot.source_hash, list(store.snapshot.roots), commits
    )
    expected = snapshot.committed_manifest_hash
    commits.clear()
    assert snapshot.committed_manifest_hash == expected
    assert len(snapshot.commits) == 1
    assert replace(snapshot, commits=()).committed_manifest_hash != expected


def count_replays(monkeypatch, store):
    replayed = []
    original = type(store)._restore_one

    def counted(self, payload):
        replayed.append(payload["call_id"])
        return original(self, payload)

    monkeypatch.setattr(type(store), "_restore_one", counted)
    return replayed


def test_future_call_and_unrelated_outputs_do_not_invalidate_producer_memo(monkeypatch):
    store = environment()
    publish(store)
    replayed = count_replays(monkeypatch, store)
    before = store._verification_key()
    store.calls = (
        *store.calls,
        replace(store.calls[-1], call_id="future", input_fingerprint="future"),
    )
    store.context.scopes["q"].outputs["irrelevant"] = {"large": "payload"}
    assert store._verification_key() == before
    store.begin("second")
    store.fork(store.context.fork()).begin("second")
    assert replayed == []


def test_consumer_permission_is_checked_on_every_read(monkeypatch):
    store = environment()
    commit = publish(store)
    replayed = count_replays(monkeypatch, store)
    second = store.calls[1]
    store.calls = (
        store.calls[0],
        replace(second, symbol_bindings=(("x", "other/x"),)),
        *store.calls[2:],
    )
    assert not store.begin("second").view.facts
    assert replayed == []
    store.calls = (
        store.calls[0],
        replace(second, scope_id="other", validity=FactValidity("other")),
        *store.calls[2:],
    )
    assert commit.facts[0] not in store.begin("second").view.facts
    assert replayed == []


def test_incremental_restore_replays_only_new_commits_and_authenticates_old_outputs(
    monkeypatch,
):
    store = environment()
    first = publish(store)
    prefix = store.to_payload()
    second = publish(store, "second")
    full = store.to_payload()
    fresh = environment()
    replayed = count_replays(monkeypatch, store)
    fresh.restore(prefix, {"first": first.output_hash})
    fresh.restore(full, {"first": first.output_hash, "second": second.output_hash})
    assert replayed == ["first", "second"]
    before = fresh.to_payload()
    with pytest.raises(ValueError, match="outputs not authenticated"):
        fresh.restore(full, {"first": "wrong", "second": second.output_hash})
    assert fresh.to_payload() == before
    assert fresh.to_payload() == full


def test_incremental_restore_failure_is_atomic_and_cold_replay_still_checks(
    monkeypatch,
):
    store = environment()
    first = publish(store)
    prefix = store.to_payload()
    second = publish(store, "second")
    full = store.to_payload()
    fresh = environment()
    fresh.restore(prefix, {"first": first.output_hash})
    bad = deepcopy(full)
    bad["commits"][1]["facts"][0]["relation"] = "x<0"
    with pytest.raises(ValueError):
        fresh.restore(bad, {"first": first.output_hash, "second": second.output_hash})
    assert fresh.to_payload() == prefix
    replayed = count_replays(monkeypatch, store)
    environment().restore(
        full, {"first": first.output_hash, "second": second.output_hash}
    )
    assert replayed == ["first", "second"]


def test_reordered_or_mutated_producer_authority_invalidates_cache():
    store = environment()
    publish(store)
    publish(store, "second")
    store.calls = (store.calls[1], store.calls[0], *store.calls[2:])
    with pytest.raises(ValueError, match="prefix"):
        store.begin("third")


def test_warm_verification_does_not_reserialize_commit(monkeypatch):
    store = environment()
    publish(store)
    store.verify_snapshot()
    monkeypatch.setattr(
        type(store.snapshot.commits[0]),
        "to_payload",
        lambda *a: pytest.fail("re-serialized commit"),
    )
    store.verify_snapshot()
    store.begin("second")


def test_metadata_reuse_avoids_reparse_and_replace_gets_new_cache(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_facts

    fact = VerifiedMathFact("x>0", (("x", "q/x"),), FactValidity("q"), "domain", "s")
    payload = fact.to_payload()
    original = proof_facts.parse_math_relation
    parsed = []

    def counted(*args, **kwargs):
        parsed.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(proof_facts, "parse_math_relation", counted)
    assert fact.to_payload() == payload
    assert fact.fact_id and fact.statement_key
    assert parsed == []
    other = replace(fact, relation="x!=0")
    assert other.fact_id != fact.fact_id
    assert other.statement_key != fact.statement_key
    assert parsed


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_fingerprint", "changed"),
        ("symbol_bindings", (("x", "changed/x"),)),
        ("validity", FactValidity("q", definition_refs=("definition",))),
        ("validity", FactValidity("q", state_version_refs=("version",))),
    ],
)
def test_producer_changes_cannot_reuse_verified_memo(field, value):
    store = environment()
    publish(store)
    store.calls = (replace(store.calls[0], **{field: value}), *store.calls[1:])
    with pytest.raises(ValueError, match="binding changed"):
        store.begin("second")


def test_relevant_visibility_change_rechecks_producer_dependencies(monkeypatch):
    store = environment()
    first = publish(store)
    overlay = store.begin("third")
    overlay.prove("x!=0", [first.facts[0].fact_id])
    store.commit(overlay, "third")
    replayed = count_replays(monkeypatch, store)
    store.context.scopes["child"].parent_id = "other"
    with pytest.raises(ValueError):
        store.verify_snapshot()
    assert replayed == ["first", "third"]


def test_rule_registry_replacement_never_hits_old_verification_memo(monkeypatch):
    from shuxueshuo_server.solver.math_kernel import proof_checker
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure

    store = environment()
    publish(store)
    original = proof_checker.DEFAULT_RULE_REGISTRY

    def reject(*args, **kwargs):
        raise ProofFailure("invalid_proof", "changed checker")

    monkeypatch.setattr(
        proof_checker,
        "DEFAULT_RULE_REGISTRY",
        replace(original, packages=(replace(original.packages[0], checker=reject),)),
    )
    with pytest.raises(ValueError, match="changed checker"):
        store.verify_snapshot()


def test_tampered_prefix_does_not_hide_behind_matching_claimed_hash():
    store = environment()
    first = publish(store)
    prefix = store.to_payload()
    second = publish(store, "second")
    full = store.to_payload()
    fresh = environment()
    fresh.restore(prefix, {"first": first.output_hash})
    bad = deepcopy(full)
    bad["commits"][0]["facts"][0]["relation"] = "x<0"
    with pytest.raises(ValueError):
        fresh.restore(bad, {"first": first.output_hash, "second": second.output_hash})
    assert fresh.to_payload() == prefix


def test_verification_memo_is_bounded_and_not_serialized():
    store = environment()
    publish(store)
    for i in range(100):
        store.context.scopes["q"].outputs[str(i)] = i
        store._remember_verified_snapshot()
    assert len(store._verified_snapshots) == 1
    store._verified_snapshots.update(str(i) for i in range(64))
    store._remember_verified_snapshot()
    assert len(store._verified_snapshots) == 1
    assert "verified_snapshots" not in json.dumps(store.to_payload())


def test_cached_metadata_rejects_mutable_leaves_and_unchecked_subclasses():
    with pytest.raises(TypeError, match="immutable"):
        FactValidity("q", definition_refs=({"mutable": "definition"},))

    class UncheckedValidity(FactValidity):
        def __post_init__(self):
            pass

    with pytest.raises(TypeError, match="immutable"):
        VerifiedMathFact(
            "x>0",
            (("x", "q/x"),),
            UncheckedValidity("q", definition_refs=[]),
            "domain",
            "s",
        )


@pytest.mark.parametrize("entry", ["begin", "register_call"])
@pytest.mark.parametrize(
    "changes,message",
    [
        (
            {"symbol_bindings": (("x", "q/object/x"), ("y", "q/object/x"))},
            "duplicate symbol identity",
        ),
        (
            {"symbol_bindings": (("x", "q/object/x"), ("x", "q/object/y"))},
            "duplicate symbol name",
        ),
        (
            {"validity": FactValidity("other")},
            "publication Scope differs from call Scope",
        ),
        ({"scope_id": "nope", "validity": FactValidity("nope")}, "unknown call Scope"),
        ({"dependencies": ("future",)}, "future or cyclic explicit dependency"),
        ({"dependencies": ("second",)}, "future or cyclic explicit dependency"),
    ],
)
def test_invalid_consumer_grant_is_rejected_before_fact_access(
    monkeypatch, entry, changes, message
):
    store = environment()
    publish(store)
    first, second = store.calls[:2]
    store.calls = (first,)
    bad = replace(second, **changes)
    before = store.to_payload()

    def forbidden(*args, **kwargs):
        pytest.fail("invalid consumer grant reached snapshot verification or replay")

    monkeypatch.setattr(store, "verify_snapshot", forbidden)
    monkeypatch.setattr(type(store), "_restore_one", forbidden)
    if entry == "begin":
        # Defend the read boundary even if an internal caller bypassed registration.
        store.calls = (first, bad)
        action = lambda: store.begin("second")
    else:
        action = lambda: store.register_call(bad)
    with pytest.raises(ValueError, match="proof_facts: " + message):
        action()
    assert store.to_payload() == before
    if entry == "register_call":
        assert store.calls == (first,)


def test_register_call_keeps_producer_memo_and_rejects_duplicate_id(monkeypatch):
    store = environment()
    publish(store)
    first, second = store.calls[:2]
    store.calls = (first,)
    memo = store._verification_key()
    replayed = count_replays(monkeypatch, store)
    store.register_call(second)
    assert store._verification_key() == memo
    assert store.begin("second").view.facts
    assert replayed == []
    with pytest.raises(ValueError, match="duplicate proof call registration"):
        store.register_call(second)
    assert store.calls == (first, second)
