"""Durable pure-code Solver admission; independent of extraction and review."""

from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, or_, select

from shuxueshuo_server.problem_understanding.compact_planner_input import (
    compact_methods,
    compact_problem,
    coverage,
)
from shuxueshuo_server.problem_understanding.runtime_binding import (
    AdmissionEvidence,
    authorize_binding,
    bind_notation,
)
from shuxueshuo_server.problem_understanding.runtime_lowering import BindingError
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    diagnose,
    uncertainty_diagnostics,
)

from . import models as m
from .db import digest, transaction
from .errors import Conflict, IntegrityFailure, ProductError
from .repositories import insert, problem, row, scoped
from .services import append_event, now, update
from .understanding import Understanding, candidate_state, parse, public


@lru_cache(maxsize=4)
def _file_fingerprint(files):
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            str(Path(name).relative_to(root)): sha256(
                Path(name).read_bytes()
            ).hexdigest()
            for name, _, _ in files
        }
    )


def configuration():
    root = Path(__file__).resolve().parents[1]
    paths = [Path(__file__)] + [
        root / "problem_understanding" / name
        for name in (
            "runtime_binding.py",
            "runtime_lowering.py",
            "compact_planner_input.py",
        )
    ]
    for directory in (
        "solver/runtime",
        "solver/family",
        "solver/extraction",
        "solver/math_kernel",
    ):
        paths.extend((root / directory).rglob("*.py"))
        paths.extend((root / directory).rglob("*.json"))
    paths.extend(
        root / "solver" / name
        for name in (
            "contracts.py",
            "math_ops.py",
            "problem_models.py",
            "question_goals.py",
            "state_semantics.py",
        )
    )
    files = tuple(
        (str(p), p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(set(paths))
        if p.is_file()
    )
    return {
        "contract": "math-runtime-binding/v1",
        "code_hash": _file_fingerprint(files),
    }


def snapshot(c, p):
    from .understanding_runtime import configuration as review_configuration

    source = (
        row(c, m.problem_source_versions, id=p["current_source_version_id"])
        if p["current_source_version_id"]
        else None
    )
    candidate = (
        row(c, m.problem_candidates, id=p["current_candidate_id"])
        if p["current_candidate_id"]
        else None
    )
    review = (
        row(c, m.extraction_runs, id=p["latest_extraction_run_id"])
        if p["latest_extraction_run_id"]
        else None
    )
    state = candidate_state(p, candidate, review, review_configuration())
    return (
        {
            "candidate_id": str(candidate["id"]) if candidate else None,
            "candidate_hash": candidate["candidate_hash"] if candidate else None,
            "source_version_id": str(source["id"]) if source else None,
            "source_hash": source["source_hash"] if source else None,
            "generation": p["understanding_generation"],
            "review_run_id": str(review["id"]) if review else None,
            "review_result_hash": digest(review["result_json"])
            if review and review["result_json"]
            else None,
            "review_current": state["source_reviewed"],
        },
        candidate,
        source,
    )


def verify_source_artifacts(service, c, ctx, source):
    ids = []
    for item in source["images"]:
        artifact = service.artifacts.verified(c, ctx, UUID(item["artifact_id"]))
        if artifact["sha256"] != item["sha256"]:
            raise IntegrityFailure("source.hash_mismatch")
        ids.append(artifact["id"])
    return ids


def binding_state(c, p):
    run = (
        row(c, m.runtime_binding_runs, id=p["latest_runtime_binding_run_id"])
        if p["latest_runtime_binding_run_id"]
        else None
    )
    status = "not_checked"
    reasons = []
    if run:
        current, _, _ = snapshot(c, p)
        if run["snapshot"] != current or run["frozen"] != configuration():
            status = "stale"
            reasons = [
                {
                    "code": "admission.version_changed",
                    "message": "题意、来源复核或绑定代码已变化，请重新检查。",
                }
            ]
        elif run["status"] in ("queued", "running"):
            status = "checking"
        elif run["status"] == "completed":
            status = (
                "ready"
                if run["result_json"] and run["result_json"].get("solver_ready")
                else "blocked"
            )
            reasons = (run["result_json"] or {}).get("diagnostics", [])
        else:
            status = "stale" if run["status"] == "superseded" else "failed"
            reasons = [
                {
                    "code": run["error_code"] or "admission.check_incomplete",
                    "message": "检查未完成，可以重新检查。",
                }
            ]
    return {
        "binding_status": status,
        "solver_ready": status == "ready",
        "blocking_reasons": reasons,
        "latest_binding_run": public(dict(run)) if run else None,
    }


class RuntimeBindings(Understanding):
    def start(self, problem_id, candidate_id, source_id, key):
        config = configuration()

        def perform():
            with transaction(self.db) as c:
                p = problem(c, self.ctx, problem_id, write=True, lock=True)
                if (
                    p["current_candidate_id"] != candidate_id
                    or p["current_source_version_id"] != source_id
                ):
                    raise Conflict("candidate.base_changed")
                current, candidate, source = snapshot(c, p)
                if (
                    candidate is None
                    or source is None
                    or candidate["source_version_id"] != source_id
                ):
                    raise Conflict("candidate.source_changed")
                for active in c.execute(
                    select(m.runtime_binding_runs).where(
                        m.runtime_binding_runs.c.problem_id == problem_id,
                        m.runtime_binding_runs.c.status.in_(["queued", "running"]),
                    )
                ).mappings():
                    update(
                        c,
                        m.runtime_binding_runs,
                        active["id"],
                        status="superseded",
                        finished_at=now(c),
                    )
                    self.service.cancel(self.ctx, active["build_id"])
                from .application import deployment_version

                submitted = self.service.submit_build(
                    self.ctx,
                    problem_id,
                    request_id="runtime-binding:" + key,
                    source_id=UUID(source["images"][0]["source_id"]),
                    base_revision_id=p["current_revision_id"],
                    pipeline_key="problem_runtime_binding",
                    pipeline_version="v1",
                    from_stage="binding",
                    dependencies={
                        "binding": {
                            "inputs": current,
                            "resources": {},
                            "config": config,
                            "upstream": {},
                        }
                    },
                    config={"binding": config},
                    deployment_version=deployment_version(),
                )
                run = insert(
                    c,
                    m.runtime_binding_runs,
                    workspace_id=self.ctx.workspace_id,
                    problem_id=problem_id,
                    build_id=UUID(submitted["build_id"]),
                    candidate_id=candidate_id,
                    source_version_id=source_id,
                    review_run_id=UUID(current["review_run_id"])
                    if current["review_run_id"]
                    else None,
                    snapshot=current,
                    frozen=config,
                    status="queued",
                )
                update(
                    c,
                    m.problems,
                    problem_id,
                    latest_runtime_binding_run_id=run["id"],
                    updated_at=now(c),
                )
                append_event(
                    c,
                    self.ctx.workspace_id,
                    "problem",
                    problem_id,
                    "runtime_binding.queued",
                    {"run_id": str(run["id"])},
                )
                return {"run_id": str(run["id"]), **submitted}

        return self.app.request(
            "runtime_binding.run",
            key,
            jsonable_encoder(
                {
                    "problem_id": problem_id,
                    "candidate_id": candidate_id,
                    "source_version_id": source_id,
                }
            ),
            perform,
        )

    def runs(self, problem_id, limit=20, before=None):
        if not 1 <= limit <= 100:
            raise ProductError("query.limit")
        with transaction(self.db) as c:
            problem(c, self.ctx, problem_id)
            query = select(m.runtime_binding_runs).where(
                m.runtime_binding_runs.c.problem_id == problem_id
            )
            if before:
                cursor = self.owned(c, m.runtime_binding_runs, before, problem_id)
                query = query.where(
                    or_(
                        m.runtime_binding_runs.c.created_at < cursor["created_at"],
                        and_(
                            m.runtime_binding_runs.c.created_at == cursor["created_at"],
                            m.runtime_binding_runs.c.id < before,
                        ),
                    )
                )
            values = [
                public(dict(v))
                for v in c.execute(
                    query.order_by(
                        m.runtime_binding_runs.c.created_at.desc(),
                        m.runtime_binding_runs.c.id.desc(),
                    ).limit(limit)
                ).mappings()
            ]
            return {
                "runs": values,
                "next_cursor": values[-1]["id"] if len(values) == limit else None,
            }

    def run(self, run_id):
        with transaction(self.db) as c:
            run = dict(scoped(c, m.runtime_binding_runs, self.ctx, run_id))
            problem(c, self.ctx, run["problem_id"])
            run["artifacts"] = [
                dict(v)
                for v in c.execute(
                    select(
                        m.artifacts.c.id,
                        m.artifacts.c.artifact_type,
                        m.artifacts.c.sha256,
                        m.artifacts.c.content_type,
                    ).where(m.artifacts.c.producer_build_id == run["build_id"])
                ).mappings()
            ]
            return public(run)

    def authority(self, run_id):
        """Internal handoff for an explicit Solver caller; no Planner invocation."""
        with transaction(self.db) as c:
            run = scoped(c, m.runtime_binding_runs, self.ctx, run_id)
            p = problem(c, self.ctx, run["problem_id"], write=True)
            if (
                p["latest_runtime_binding_run_id"] != run_id
                or not binding_state(c, p)["solver_ready"]
            ):
                raise Conflict("admission.not_current_or_not_ready")
            current, candidate, source = snapshot(c, p)
            verify_source_artifacts(self.service, c, self.ctx, source)
            payload = candidate["candidate_json"]
        bound = bind_notation(
            payload,
            problem_id=str(run["problem_id"]),
            **{
                k: current[k]
                for k in ("candidate_id", "source_version_id", "source_hash")
            },
        )
        # Pin again after CPU work: a concurrent edit cannot receive authorization.
        with transaction(self.db) as c:
            p = problem(c, self.ctx, run["problem_id"], write=True, lock=True)
            if (
                p["latest_runtime_binding_run_id"] != run_id
                or not binding_state(c, p)["solver_ready"]
            ):
                raise Conflict("admission.version_changed")
            return authorize_binding(
                bound,
                AdmissionEvidence(
                    **{
                        k: current[k]
                        for k in (
                            "candidate_id",
                            "candidate_hash",
                            "source_version_id",
                            "source_hash",
                            "review_run_id",
                            "review_current",
                        )
                    }
                ),
            )


def run_product(x):
    with transaction(x.service.db) as c:
        run = dict(row(c, m.runtime_binding_runs, build_id=x.build["id"]))
        candidate = dict(scoped(c, m.problem_candidates, x.ctx, run["candidate_id"]))
        source = dict(
            scoped(c, m.problem_source_versions, x.ctx, run["source_version_id"])
        )
        stage = row(c, m.build_stages, build_id=x.build["id"], stage_key="binding")
        accepted = (
            row(c, m.stage_attempts, id=stage["accepted_attempt_id"])
            if stage["accepted_attempt_id"]
            else None
        )
    if accepted:
        x.restore(stage, accepted)
        x.stage_key, x.attempt = "binding", accepted
        result = x.read("binding", "binding-result.json")
    else:
        x.begin("binding")
        with transaction(x.service.db) as c:
            x.service._guard(c, *x.args)
            x.consumed.update(verify_source_artifacts(x.service, c, x.ctx, source))
            update(c, m.runtime_binding_runs, run["id"], status="running")
        validation = parse(
            candidate["candidate_json"], run["problem_id"], source["source_hash"]
        )
        diagnostics = diagnose(
            validation, candidate["candidate_json"]
        ) + uncertainty_diagnostics(candidate["candidate_json"])
        if not run["snapshot"]["review_current"]:
            diagnostics.append(
                {
                    "code": "admission.source_review_required",
                    "path": "/source_review",
                    "message": "当前版本尚无有效原图复核。",
                }
            )
        bound = None
        try:
            if not validation["contract_valid"]:
                if not diagnostics:
                    diagnostics.append(
                        {
                            "code": "admission.parse_invalid",
                            "path": "/",
                            "message": "题意解析未通过。",
                        }
                    )
            else:
                bound = bind_notation(
                    candidate["candidate_json"],
                    problem_id=str(run["problem_id"]),
                    candidate_id=str(candidate["id"]),
                    source_version_id=str(source["id"]),
                    source_hash=source["source_hash"],
                )
                artifacts = bound.artifacts()
                artifacts.update(
                    {
                        "compact-problem.json": compact_problem(bound),
                        "compact-methods.json": compact_methods(bound),
                        "coverage.json": coverage(bound),
                    }
                )
        except BindingError as error:
            bound = None
            # Deterministic unsupported/binding diagnostics remain inspectable.
            diagnostics.append(
                {
                    "code": getattr(error, "code", "admission.binding_failed"),
                    "path": getattr(error, "path", "/root"),
                    "message": str(error),
                }
            )
        result = {
            "schema_version": "math-runtime-binding/v1",
            "solver_ready": not diagnostics and bound is not None,
            "diagnostics": diagnostics,
            "snapshot": run["snapshot"],
            "configuration": run["frozen"],
        }
        if bound is not None:
            for name, data in artifacts.items():
                x.add(name, data, kind="math_runtime:" + name)
            if result["solver_ready"]:
                authority = authorize_binding(
                    bound,
                    AdmissionEvidence(
                        **{
                            k: run["snapshot"][k]
                            for k in (
                                "candidate_id",
                                "candidate_hash",
                                "source_version_id",
                                "source_hash",
                                "review_run_id",
                                "review_current",
                            )
                        }
                    ),
                )
                x.add("solver-authority.json", authority.authority_payload())
        x.add("binding-result.json", result, schema="math-runtime-binding/v1")
        x.complete("求解条件已检查")
    with transaction(x.service.db) as c:
        x.service._guard(c, *x.args)
        p = problem(c, x.ctx, run["problem_id"], write=True, lock=True)
        current, _, _ = snapshot(c, p)
        fresh = (
            p["latest_runtime_binding_run_id"] == run["id"]
            and current == run["snapshot"]
            and configuration() == run["frozen"]
        )
        status = "completed" if fresh else "superseded"
        update(
            c,
            m.runtime_binding_runs,
            run["id"],
            status=status,
            result_json=result,
            finished_at=now(c),
        )
        job = row(c, m.jobs, build_id=x.build["id"])
        update(c, m.builds, x.build["id"], status="succeeded", finished_at=now(c))
        update(c, m.jobs, job["id"], status="succeeded", lease_expires_at=None)
        update(c, m.job_executions, x.args[2], status="succeeded", finished_at=now(c))
        append_event(
            c,
            x.ctx.workspace_id,
            "build",
            x.build["id"],
            "runtime_binding.finished",
            {"run_id": str(run["id"]), "status": status},
        )
        append_event(
            c,
            x.ctx.workspace_id,
            "problem",
            p["id"],
            "runtime_binding.finished",
            {"run_id": str(run["id"]), "status": status},
        )
    return result
