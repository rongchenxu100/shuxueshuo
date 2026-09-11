"""Short, caller-owned transactions and deterministic transaction locks."""
from contextlib import contextmanager
from hashlib import sha256
import json

from sqlalchemy import create_engine, text


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def engine(url):
    return create_engine(url, isolation_level='READ COMMITTED', pool_pre_ping=True,
                         hide_parameters=True, connect_args={'options': '-c timezone=UTC'})


def lock(connection, *parts):
    key = int.from_bytes(sha256(canonical(parts).encode()).digest()[:8], 'big', signed=True)
    connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})


@contextmanager
def transaction(db):
    with db.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        yield connection
