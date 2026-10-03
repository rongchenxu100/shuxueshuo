"""Student-owned marks, using the same database/session as site login."""
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from ..auth.api import require_origin, require_user, service
from ..auth.service import AuthService
from ..product import models as m
from ..product.db import transaction


class StatusBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    learning_status: Literal['unmarked', 'mastered', 'needs_review']


class CompleteBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


def learning_user(request: Request, user: Annotated[dict, Depends(require_user)],
                  auth: Annotated[AuthService, Depends(service)]):
    expected = request.headers.get('X-Learning-User')
    if expected and expected != user['id']:
        raise HTTPException(409, '账号已变化，请刷新后重试。')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        require_origin(request, auth)
    return user


User = Annotated[dict, Depends(learning_user)]
Auth = Annotated[AuthService, Depends(service)]
router = APIRouter(prefix='/api/learning', dependencies=[Depends(learning_user)])


def problem_ids():
    # Reuse the global lesson IDs: q01 and quadratic-always-q01 are different.
    return {p.stem for p in (Path(__file__).parents[1] / 'tutor_demo/lessons').glob('*.json')}


def known(problem_id):
    if problem_id not in problem_ids():
        raise HTTPException(404, '没有找到这道题。')


def view(row=None, problem_id=None):
    return {'problem_id': row['problem_id'] if row else problem_id,
            'practiced': row['practiced'] if row else False,
            'learning_status': row['learning_status'] if row else 'unmarked'}


def key(user, problem_id):
    t = m.student_learning_marks
    return (t.c.user_id == UUID(user['id'])) & (t.c.problem_id == problem_id)


@router.get('/marks')
def list_marks(user: User, auth: Auth):
    with transaction(auth.db) as c:
        rows = c.execute(select(m.student_learning_marks).where(
            m.student_learning_marks.c.user_id == UUID(user['id'])
        )).mappings().all()
    known_ids = problem_ids()
    return {'marks': [view(row) for row in rows if row['problem_id'] in known_ids]}


@router.get('/marks/{problem_id}')
def read_mark(problem_id: str, user: User, auth: Auth):
    known(problem_id)
    with transaction(auth.db) as c:
        row = c.execute(select(m.student_learning_marks).where(key(user, problem_id))).mappings().first()
    return view(row, problem_id)


@router.post('/marks/{problem_id}/complete')
def complete(problem_id: str, body: CompleteBody, user: User, auth: Auth):
    known(problem_id)
    t = m.student_learning_marks
    with transaction(auth.db) as c:
        row = c.execute(insert(t).values(user_id=UUID(user['id']), problem_id=problem_id, practiced=True)
                        .on_conflict_do_update(index_elements=[t.c.user_id, t.c.problem_id],
                                               set_={'practiced': True})
                        .returning(t)).mappings().one()
    return view(row)


@router.put('/marks/{problem_id}/status')
def set_status(problem_id: str, body: StatusBody, user: User, auth: Auth):
    known(problem_id)
    t = m.student_learning_marks
    with transaction(auth.db) as c:
        row = c.execute(update(t).where(key(user, problem_id), t.c.practiced.is_(True))
                        .values(learning_status=body.learning_status).returning(t)).mappings().first()
        if row is None:
            raise HTTPException(409, '先完成一次练习，再标记掌握情况。')
    return view(row)
