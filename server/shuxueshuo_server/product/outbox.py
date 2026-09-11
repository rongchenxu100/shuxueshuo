"""Outbox repository operations. P2 owns polling, RabbitMQ and publisher confirms."""
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, or_, and_

from . import models as m
from .errors import Conflict, ProductError
from .services import now, update


def reserve(connection, *, limit=20, lease_seconds=30):
    if not 1 <= limit <= 1000 or not 1 <= lease_seconds <= 300:
        raise ProductError('outbox.range')
    timestamp = now(connection)
    messages = connection.execute(select(m.outbox_messages).where(or_(
        and_(m.outbox_messages.c.status == 'pending', m.outbox_messages.c.available_at <= timestamp),
        and_(m.outbox_messages.c.status == 'publishing', m.outbox_messages.c.locked_until <= timestamp)))
        .order_by(m.outbox_messages.c.available_at, m.outbox_messages.c.created_at)
        .limit(limit).with_for_update(skip_locked=True)).mappings().all()
    reserved = []
    for message in messages:
        token = uuid4()
        update(connection, m.outbox_messages, message['id'], status='publishing', publisher_token=token,
               locked_until=timestamp + timedelta(seconds=lease_seconds), attempt_count=message['attempt_count'] + 1)
        reserved.append({**message, 'publisher_token': token, 'status': 'publishing'})
    return reserved


def acknowledge(connection, message_id, token, *, confirmed, error=None, retry_seconds=30):
    if retry_seconds < 0:
        raise ProductError('outbox.retry_range')
    message = connection.execute(select(m.outbox_messages).where(m.outbox_messages.c.id == message_id).with_for_update()).mappings().one()
    if message['status'] == 'published' and message['publisher_token'] == token and confirmed:
        return
    timestamp = now(connection)
    if message['status'] != 'publishing' or message['publisher_token'] != token or message['locked_until'] <= timestamp:
        raise Conflict('outbox.publisher_fenced')
    update(connection, m.outbox_messages, message_id, status='published' if confirmed else 'pending',
           published_at=timestamp if confirmed else None, locked_until=None,
           available_at=timestamp + timedelta(seconds=retry_seconds), last_error=error)
