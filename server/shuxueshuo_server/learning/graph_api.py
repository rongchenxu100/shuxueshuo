"""Authenticated student data; public content writes only through the publisher."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from ..product.db import lock, transaction
from . import associations, compatibility, drills, practice
from .api import Auth, User

router = APIRouter(prefix="/api/learning")


@router.get('/content')
def content(auth: Auth):
    with transaction(auth.db) as c:
        return associations.content_metadata(c)


@router.get('/content/problems/{problem_id}')
def problem_content(problem_id: str, auth: Auth):
    with transaction(auth.db) as c:
        lock(c, 'learning.publish', shared=True)
        return compatibility.metadata(compatibility.published(c, problem_id)) | {
            'content_version': associations.content_metadata(c)['content_version']}


class StartDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    node_id: str = Field(min_length=1, max_length=100)
    previous_attempt_id: UUID | None = None
    content_version: str | None = Field(default=None, min_length=1, max_length=100)
    drill_version: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def requires_version(self):
        if self.drill_version is None and self.content_version is None:
            raise ValueError('检测需要本节点题池版本。')
        return self


class AnswerDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected: list[str] = Field(max_length=30)


@router.post("/drills")
def start(body: StartDrill, user: User, auth: Auth):
    return drills.start(
        auth.db, UUID(user["id"]), body.node_id, body.id, body.previous_attempt_id,
        content_version=body.content_version, drill_version=body.drill_version,
    )


@router.get("/drills/{attempt_id}")
def read(attempt_id: UUID, user: User, auth: Auth):
    with transaction(auth.db) as c:
        return drills.view(c, drills.owned(c, attempt_id, UUID(user["id"])))


@router.post("/drills/{attempt_id}/answers/{position}")
def answer(attempt_id: UUID, position: int, body: AnswerDrill, user: User, auth: Auth):
    return drills.answer(auth.db, UUID(user["id"]), attempt_id, position, body.selected)


@router.get("/nodes")
def nodes(user: User, auth: Auth):
    with transaction(auth.db) as c:
        lock(c, "learning.publish", shared=True)
        return {"content_version": associations.content_metadata(c)["content_version"],
                "nodes": drills.statuses(c, UUID(user["id"]))}


@router.get('/progress')
def progress(scope: str, user: User, auth: Auth):
    with transaction(auth.db) as c:
        lock(c, 'learning.publish', shared=True)
        return associations.directory_progress(c, scope, drills.statuses(c, UUID(user['id']))) | {
            'content_version': associations.content_metadata(c)['content_version']}


@router.get('/progress/batch')
def progress_batch(
    user: User,
    auth: Auth,
    scope: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]],
        Query(min_length=1, max_length=100),
    ],
):
    with transaction(auth.db) as c:
        lock(c, 'learning.publish', shared=True)
        return {'content_version': associations.content_metadata(c)['content_version'],
                'progress': associations.directory_progress_batch(c, scope, drills.statuses(c, UUID(user['id'])))}


class StartPractice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    problem_id: str = Field(max_length=100)
    route_id: str = Field(max_length=100)
    previous_attempt_id: UUID | None = None
    content_version: str | None = Field(default=None, min_length=1, max_length=100)
    practice_version: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def requires_version(self):
        if self.practice_version is None and self.content_version is None:
            raise ValueError('练习需要本题版本。')
        return self


class SubmitPractice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    step_id: str = Field(max_length=100)
    answer: dict


@router.post("/practice")
def start_practice(body: StartPractice, user: User, auth: Auth):
    return practice.start(
        auth.db,
        UUID(user["id"]),
        body.problem_id,
        body.route_id,
        body.id,
        body.previous_attempt_id,
        content_version=body.content_version,
        practice_version=body.practice_version,
    )


@router.post("/practice/{attempt_id}/answers")
def submit_practice(attempt_id: UUID, body: SubmitPractice, user: User, auth: Auth):
    return practice.submit(
        auth.db, UUID(user["id"]), attempt_id, body.id, body.step_id, body.answer
    )


@router.post("/practice/{attempt_id}/displayed/{event_id}")
def displayed(attempt_id: UUID, event_id: UUID, user: User, auth: Auth):
    return practice.acknowledge(auth.db, UUID(user["id"]), attempt_id, event_id)


@router.get("/practice/{attempt_id}")
def read_practice(attempt_id: UUID, user: User, auth: Auth, practice_version: str | None = None):
    with transaction(auth.db) as c:
        lock(c, 'learning.publish', shared=True)
        a = practice.owned(c, attempt_id, UUID(user["id"]))
        if practice_version is not None:
            compatibility.require_attempt(c, a, practice_version)
        events = []
        for r in c.execute(
            text(
                "SELECT * FROM student_practice_events WHERE attempt_id=:a ORDER BY sequence"
            ),
            {"a": attempt_id},
        ).mappings():
            row = dict(r)
            if row["event_type"] == "context":
                row["payload"] = {
                    k: v
                    for k, v in row["payload"].items()
                    if k not in ("expected_answer", "criteria")
                }
            events.append(row)
        return practice.result(c, a) | {
            "problem_context": {
                k: v for k, v in a["problem_context"].items() if k not in ("contract_hash", "_lesson", "_graph_walk")
            },
            "events": events,
        }


@router.get("/nodes/{node_id}/evidence")
def evidence(node_id: str, user: User, auth: Auth, entry: str | None = None):
    with transaction(auth.db) as c:
        return practice.evidence(c, UUID(user['id']), node_id, entry)


class ShownReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    step_id: str = Field(max_length=100)
    node_id: str = Field(max_length=100)
    ref: str | None = Field(default=None, max_length=200)
    resource_id: str | None = Field(default=None, max_length=100)


@router.post("/practice/{attempt_id}/references")
def reference(attempt_id: UUID, body: ShownReference, user: User, auth: Auth):
    return practice.shown_reference(
        auth.db, UUID(user["id"]), attempt_id, body.id, body.step_id, body.node_id,
        body.ref, body.resource_id,
    )
