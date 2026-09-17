"""Independent PostgreSQL admission tests. No model provider is constructed."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.api import create_app
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import Conflict
from shuxueshuo_server.product.execution import ExecutionContext
from shuxueshuo_server.product.repositories import row
from shuxueshuo_server.product.runtime_binding import RuntimeBindings, run_product
from shuxueshuo_server.product.understanding_runtime import run_product as extract
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_understanding import (  # noqa: F401 - shared product fixture
    OK,
    RECORDINGS,
    Recorded,
    begin,
    create,
)
from test_understanding import (
    app as product_app,
)

app = product_app

CASE = "tj-2026-hexi-yimo-25"


def prepared(app, case=CASE, review=True):
    u, pid, source = create(app, case)
    responses = [p.read_text() for p in sorted(RECORDINGS.glob(f"{case}.*.txt"))]
    if not review:
        raw = json.loads(responses[0])
        saved = u.save_candidate(pid, None, source, raw, uuid4().hex)
    else:
        _, x = begin(app, pid, source)
        extract(x, Recorded(responses))
        saved = u.summary(pid)["candidate"]
    return u, pid, source, UUID(saved["id"])


def start(app, pid, source, candidate, key=None):
    service = RuntimeBindings(app)
    result = service.start(pid, candidate, source, key or uuid4().hex)
    execution = app.service.acquire_execution(
        app.ctx,
        UUID(result["job_id"]),
        "binding-test",
        deployment_version="understanding-test",
        lease_seconds=300,
    )
    x = ExecutionContext(
        app, app.ctx, UUID(result["build_id"]), execution["id"], execution["epoch"]
    )
    return service, result, x


@pytest.mark.parametrize(
    "case",
    [
        "tj-2026-nankai-yimo-25",
        "tj-2026-heping-ermo-25",
        "tj-2026-heping-yimo-25",
        "tj-2026-hexi-yimo-25",
        "tj-2026-xiqing-yimo-25",
    ],
)
def test_ready_is_independent_durable_and_idempotent(app, case):
    u, pid, source, candidate = prepared(app, case)
    before = u.summary(pid)
    with transaction(app.db) as c:
        generation = row(c, m.problems, id=pid)["understanding_generation"]
        calls = c.scalar(select(func.count()).select_from(m.model_calls))
    key = uuid4().hex
    service, result, x = start(app, pid, source, candidate, key)
    assert service.start(pid, candidate, source, key) == result
    assert u.summary(pid)["binding_status"] == "checking"
    bound = run_product(x)
    assert bound["solver_ready"], bound
    summary = u.summary(pid)
    assert summary["solver_ready"] and summary["binding_status"] == "ready"
    assert summary["source_reviewed"] and summary["latest_run"] == before["latest_run"]
    assert service.authority(UUID(result["run_id"])).bundle.problem_id == str(pid)
    with transaction(app.db) as c:
        p = row(c, m.problems, id=pid)
        assert p["understanding_generation"] == generation
        assert p["latest_build_id"] is None
        assert c.scalar(select(func.count()).select_from(m.model_calls)) == calls
    run = service.run(UUID(result["run_id"]))
    assert any(
        a["artifact_type"] == "math_runtime:compact-problem.json"
        for a in run["artifacts"]
    )
    assert service.runs(pid)["runs"][0]["id"] == result["run_id"]
    with TestClient(create_app(app)) as client:
        assert (
            client.get(
                f"/api/product/v1/runtime-binding-runs/{result['run_id']}"
            ).status_code
            == 200
        )
        artifact = next(
            a
            for a in run["artifacts"]
            if a["artifact_type"] == "math_runtime:compact-problem.json"
        )
        payload = client.get(
            f"/api/product/v1/builds/{result['build_id']}/artifacts/{artifact['id']}"
        ).json()
        assert (
            "optimizations" not in payload
            and payload["root"] == before["candidate"]["candidate_json"]["root"]
        )


def test_unreviewed_candidate_cannot_become_ready(app):
    u, pid, source, candidate = prepared(app, review=False)
    service, result, x = start(app, pid, source, candidate)
    output = run_product(x)
    assert not output["solver_ready"]
    assert any(
        d["code"] == "admission.source_review_required" for d in output["diagnostics"]
    )
    assert u.summary(pid)["binding_status"] == "blocked"
    with pytest.raises(Conflict):
        service.authority(UUID(result["run_id"]))


def test_same_problem_extraction_and_binding_can_both_be_cancelled(app):
    u, pid, source, candidate = prepared(app, review=False)
    extracting = u.start(pid, source, candidate, "validate", uuid4().hex)
    app.service.acquire_execution(
        app.ctx,
        UUID(extracting["job_id"]),
        "extract-cancel-test",
        deployment_version="understanding-test",
        lease_seconds=300,
    )
    service, checking, x = start(app, pid, source, candidate)
    summary = u.summary(pid)
    assert summary["latest_run"]["build_id"] == extracting["build_id"]
    assert summary["latest_binding_run"]["build_id"] == checking["build_id"]
    # The page's single action sends both requests. Either ordering is safe.
    with TestClient(create_app(app)) as client:
        for result in (checking, extracting):
            assert (
                client.post(
                    f"/api/product/v1/builds/{result['build_id']}/cancel"
                ).status_code
                == 200
            )
    assert u.run(UUID(extracting["run_id"]))["status"] == "cancelled"
    assert service.run(UUID(checking["run_id"]))["status"] == "cancelled"
    with pytest.raises(Conflict):
        run_product(x)
    assert not u.summary(pid)["solver_ready"]


def test_binding_keeps_existing_source_review_and_preflight_contracts(app):
    u, pid, source, candidate = prepared(app, review=False)
    raw = deepcopy(u.summary(pid)["candidate"]["candidate_json"])
    facts = raw["root"]["children"][2]["facts"]
    facts[-1] = "min(MN+AN) = 21/4"
    saved = u.save_candidate(pid, candidate, source, raw, uuid4().hex)
    _, _, x = start(app, pid, source, UUID(saved["id"]))
    run_product(x)
    with TestClient(create_app(app)) as client:
        summary = client.get(f"/api/product/v1/problems/{pid}/understanding").json()
    assert summary["binding_status"] == "blocked" and not summary["solver_ready"]
    assert summary["match_status"] == "matched"
    assert summary["candidate"]["candidate_json"]["family_id"] == raw["family_id"]
    assert {d["code"] for d in summary["blocking_reasons"]} == {
        "admission.source_review_required",
        "extraction.problem_ir_runtime_preflight_failed",
    }


@pytest.mark.parametrize("release", ["cancel", "lease_expiry"])
def test_binding_concurrency_is_capped_and_releases_slots(app, release):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Barrier

    from shuxueshuo_server.product.services import now, update

    service = RuntimeBindings(app)
    active = []
    try:
        for case in [
            CASE,
            "tj-2026-nankai-yimo-25",
            "tj-2026-heping-ermo-25",
            "tj-2026-heping-yimo-25",
        ]:
            _, pid, source, candidate = prepared(app, case, review=False)
            active.append(service.start(pid, candidate, source, uuid4().hex))
        barrier = Barrier(4)

        def acquire(submitted, synchronize=True):
            if synchronize:
                barrier.wait(timeout=10)
            try:
                app.service.acquire_execution(
                    app.ctx,
                    UUID(submitted["job_id"]),
                    "binding-slot-test",
                    deployment_version="understanding-test",
                    lease_seconds=300,
                )
                return "acquired"
            except Conflict as error:
                assert str(error) == "execution.capacity"
                return "capacity"

        with ThreadPoolExecutor(4) as pool:
            statuses = list(pool.map(acquire, active))
        assert sorted(statuses) == ["acquired"] * 3 + ["capacity"]

        # Filling binding slots must not starve extraction's independent pool.
        u, pid, source = create(app)
        extracting = u.start(pid, source, None, "extract", uuid4().hex)
        active.append(extracting)
        assert acquire(extracting, synchronize=False) == "acquired"

        held = active[statuses.index("acquired")]
        waiting = active[statuses.index("capacity")]
        if release == "cancel":
            app.service.cancel(app.ctx, UUID(held["build_id"]))
        else:
            with transaction(app.db) as c:
                update(
                    c,
                    m.jobs,
                    UUID(held["job_id"]),
                    lease_expires_at=now(c) - timedelta(seconds=1),
                )
        assert acquire(waiting, synchronize=False) == "acquired"
    finally:
        for submitted in active:
            app.service.cancel(app.ctx, UUID(submitted["build_id"]))


@pytest.mark.parametrize("case", ["k-quad", "function-quantifiers"])
def test_unsupported_and_missing_source_stay_queryable(app, case):
    u, pid, source, candidate = prepared(app, case)
    service, result, x = start(app, pid, source, candidate)
    assert not run_product(x)["solver_ready"]
    summary = u.summary(pid)
    assert summary["candidate"] and summary["blocking_reasons"]
    if case == "k-quad":
        assert any(d["code"] == "missing_figure" for d in summary["blocking_reasons"])
    assert service.run(UUID(result["run_id"]))["status"] == "completed"


def test_edits_and_configuration_invalidate_admission_without_erasing_review(
    app, monkeypatch
):
    u, pid, source, candidate = prepared(app)
    service, result, x = start(app, pid, source, candidate)
    run_product(x)
    from shuxueshuo_server.product import runtime_binding

    config = runtime_binding.configuration()
    monkeypatch.setattr(
        runtime_binding, "configuration", lambda: {**config, "code_hash": "changed"}
    )
    assert u.summary(pid)["binding_status"] == "stale"
    assert u.summary(pid)["source_reviewed"]
    with pytest.raises(Conflict):
        service.authority(UUID(result["run_id"]))
    monkeypatch.undo()
    raw = deepcopy(u.summary(pid)["candidate"]["candidate_json"])
    raw["root"]["facts"].append("b != 0")
    u.save_candidate(pid, candidate, source, raw, uuid4().hex)
    assert not u.summary(pid)["solver_ready"]
    assert u.summary(pid)["binding_status"] == "stale"


def test_edit_during_check_keeps_result_historical(app, monkeypatch):
    u, pid, source, candidate = prepared(app)
    service, result, x = start(app, pid, source, candidate)
    complete = x.complete

    def edited(summary):
        value = complete(summary)
        raw = deepcopy(u.summary(pid)["candidate"]["candidate_json"])
        raw["root"]["facts"].append("b != 0")
        u.save_candidate(pid, candidate, source, raw, uuid4().hex)
        return value

    monkeypatch.setattr(x, "complete", edited)
    run_product(x)
    assert service.run(UUID(result["run_id"]))["status"] == "superseded"
    assert not u.summary(pid)["solver_ready"]


def test_api_conflict_history_and_frozen_database_inputs(app):
    _u, pid, source, candidate = prepared(app)
    with TestClient(create_app(app)) as client:
        path = f"/api/product/v1/problems/{pid}/runtime-binding-runs"
        key = uuid4().hex
        body = {"candidate_id": str(candidate), "source_version_id": str(source)}
        response = client.post(path, json=body, headers={"Idempotency-Key": key})
        assert response.status_code == 202, response.text
        assert (
            client.post(path, json=body, headers={"Idempotency-Key": key}).json()
            == response.json()
        )
        assert client.get(path).json()["runs"][0]["id"] == response.json()["run_id"]
        body["candidate_id"] = str(uuid4())
        assert (
            client.post(
                path, json=body, headers={"Idempotency-Key": uuid4().hex}
            ).status_code
            == 409
        )
    with pytest.raises(DBAPIError), transaction(app.db) as c:
        c.execute(
            m.runtime_binding_runs.update()
            .where(m.runtime_binding_runs.c.id == UUID(response.json()["run_id"]))
            .values(snapshot={})
        )


def test_repeat_checks_supersede_pending_work_and_old_worker_cannot_publish(app):
    u, pid, source, candidate = prepared(app)
    service, first, x = start(app, pid, source, candidate)
    second = service.start(pid, candidate, source, uuid4().hex)
    assert service.run(UUID(first["run_id"]))["status"] == "superseded"
    with pytest.raises(Conflict):
        run_product(x)
    assert u.summary(pid)["latest_binding_run"]["id"] == second["run_id"]
    assert not u.summary(pid)["solver_ready"]


def test_review_and_source_changes_immediately_invalidate_ready_result(
    app, monkeypatch
):
    from shuxueshuo_server.product import understanding_runtime

    u, pid, source, candidate = prepared(app)
    _, _, x = start(app, pid, source, candidate)
    run_product(x)
    config = understanding_runtime.configuration()
    monkeypatch.setattr(
        understanding_runtime, "configuration", lambda: {**config, "changed": True}
    )
    assert u.summary(pid)["binding_status"] == "stale"
    monkeypatch.undo()
    # A new review attempt changes the source-review generation immediately.
    u.start(pid, source, candidate, "review", uuid4().hex)
    assert u.summary(pid)["binding_status"] == "stale"
    assert not u.summary(pid)["solver_ready"]


def test_checkpoint_recovery_finishes_without_rebinding_or_model_calls(
    app, monkeypatch
):
    from shuxueshuo_server.product import runtime_binding
    from test_understanding import Crash, resume

    u, pid, source, candidate = prepared(app)
    service, result, x = start(app, pid, source, candidate)
    original = x.complete

    def crash(summary):
        original(summary)
        raise Crash()

    monkeypatch.setattr(x, "complete", crash)
    with pytest.raises(Crash):
        run_product(x)
    recovered = resume(app, result, x)

    def no_rebinding(*args, **kwargs):
        raise AssertionError("accepted checkpoint must be restored")

    monkeypatch.setattr(runtime_binding, "bind_notation", no_rebinding)
    assert run_product(recovered)["solver_ready"]
    assert u.summary(pid)["solver_ready"]
    assert service.run(UUID(result["run_id"]))["status"] == "completed"


def test_technical_failure_can_be_rechecked(app, monkeypatch):
    from shuxueshuo_server.product import runtime_binding

    u, pid, source, candidate = prepared(app)
    _, _, x = start(app, pid, source, candidate)
    with monkeypatch.context() as patch:

        def broken(*a, **kw):
            raise RuntimeError("injected binding crash")

        patch.setattr(runtime_binding, "bind_notation", broken)
        with pytest.raises(RuntimeError):
            run_product(x)
    app.service.finish_failure(*x.args, "test.technical_failure")
    assert u.summary(pid)["binding_status"] == "failed"
    _, _, x = start(app, pid, source, candidate)
    assert run_product(x)["solver_ready"]


def test_cross_workspace_cannot_read_check_or_authorize(app):
    from dataclasses import replace

    from shuxueshuo_server.product.errors import Forbidden

    _u, pid, source, candidate = prepared(app)
    _service, result, x = start(app, pid, source, candidate)
    run_product(x)
    from shuxueshuo_server.product.application import Application

    stranger = Application(
        app.settings, app.service, replace(app.ctx, workspace_id=uuid4())
    )
    private = RuntimeBindings(stranger)
    for action in (
        lambda: private.run(UUID(result["run_id"])),
        lambda: private.runs(pid),
        lambda: private.authority(UUID(result["run_id"])),
        lambda: private.start(pid, candidate, source, uuid4().hex),
    ):
        with pytest.raises(Forbidden):
            action()


def test_concurrent_same_idempotency_key_reserves_one_check(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    _u, pid, source, candidate = prepared(app)
    key = uuid4().hex
    barrier = Barrier(2)
    service = RuntimeBindings(app)

    def submit(_):
        barrier.wait(timeout=10)
        return service.start(pid, candidate, source, key)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    assert len(service.runs(pid)["runs"]) == 1


def test_new_source_version_and_completed_result_immutability(app):
    from io import BytesIO

    from PIL import Image

    u, pid, source, candidate = prepared(app)
    service, result, x = start(app, pid, source, candidate)
    run_product(x)
    with pytest.raises(DBAPIError), transaction(app.db) as c:
        c.execute(
            m.runtime_binding_runs.update()
            .where(m.runtime_binding_runs.c.id == UUID(result["run_id"]))
            .values(result_json={})
        )
    image = BytesIO()
    Image.new("RGB", (10, 20), "red").save(image, format="PNG")
    extra = u.upload(pid, image.getvalue(), "附图.png", "image/png", uuid4().hex)
    original = u.summary(pid)["source_version"]["images"][0]["source_id"]
    u.source_version(
        pid, source, [UUID(original), UUID(extra["source_id"])], uuid4().hex
    )
    assert u.summary(pid)["binding_status"] == "stale"
    with pytest.raises(Conflict):
        service.authority(UUID(result["run_id"]))
