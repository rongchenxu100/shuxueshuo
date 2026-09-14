"""Scoped persistence helpers; never commit the caller's transaction."""
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from . import models as m
from .errors import Conflict, Forbidden, IntegrityFailure, NotFound
from .storage import parts


@dataclass(frozen=True)
class UserContext:
    workspace_id: UUID
    user_id: UUID


def row(connection, table, **where):
    statement = select(table).filter_by(**where)
    return connection.execute(statement).mappings().first()


def insert(connection, table, **values):
    return connection.execute(table.insert().values(**values).returning(table)).mappings().one()


def member(connection, ctx):
    result = row(connection, m.workspace_members, workspace_id=ctx.workspace_id, user_id=ctx.user_id)
    if result is None:
        raise Forbidden('workspace.not_member')
    return result


def scoped(connection, table, ctx, resource_id, *, lock=False):
    member(connection, ctx)
    query = select(table).where(table.c.workspace_id == ctx.workspace_id, table.c.id == resource_id)
    if lock:
        query = query.with_for_update()
    result = connection.execute(query).mappings().first()
    if result is None:
        raise NotFound(table.name + '.not_found')
    return result


def problem(connection, ctx, problem_id, *, write=False, lock=False):
    value = scoped(connection, m.problems, ctx, problem_id, lock=lock)
    if value['owner_user_id'] != ctx.user_id and (write or value['visibility'] != 'workspace'):
        raise Forbidden('problem.private')
    return value


class ArtifactRepository:
    def __init__(self, storage):
        self.storage = storage

    def register(self, metadata, transaction):
        ctx = UserContext(metadata['workspace_id'], metadata['owner_user_id'])
        member(transaction, ctx)
        key = metadata['storage_key']
        if not key.startswith(f'workspaces/{ctx.workspace_id}/'):
            raise Forbidden('artifact.workspace_path')
        names = parts(key)
        if len(names) != 5 or names[2] not in ('sources', 'builds') or names[4] != str(metadata.get('id')):
            raise IntegrityFailure('artifact.storage_identity')
        if names[2] == 'builds' and names[3] != str(metadata.get('producer_build_id')):
            raise IntegrityFailure('artifact.build_path')
        UUID(names[3])
        if metadata.get('access_class') == 'page' and metadata.get('artifact_type') not in (
            'page_html', 'page_css', 'page_js', 'page_svg', 'page_image', 'page_font'):
            raise Forbidden('artifact.private_type_in_page')
        if not self.storage.verify(key, metadata['sha256'], metadata['size_bytes']).ok:
            raise IntegrityFailure('artifact.unverified')
        existing = row(transaction, m.artifacts, storage_key=key)
        if existing:
            if any(existing[k] != v for k, v in metadata.items()):
                raise Conflict('artifact.registration_conflict')
            return existing
        return insert(transaction, m.artifacts, **metadata)

    def get(self, workspace_id, artifact_id, transaction):
        result = row(transaction, m.artifacts, workspace_id=workspace_id, id=artifact_id)
        if result is None:
            raise NotFound('artifact.not_found')
        return result

    def verified(self, connection, ctx, artifact_id, *, page=False):
        member(connection, ctx)
        value = self.get(ctx.workspace_id, artifact_id, connection)
        if page:
            if value['access_class'] != 'page':
                raise Forbidden('artifact.not_page_resource')
        elif value['owner_user_id'] != ctx.user_id:
            raise Forbidden('artifact.private')
        if value['availability'] != 'verified' or not self.storage.verify(value['storage_key'], value['sha256'], value['size_bytes']).ok:
            raise IntegrityFailure('artifact.unavailable')
        return value
