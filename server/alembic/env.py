from alembic import context
from sqlalchemy import text

from shuxueshuo_server.product.db import engine, lock
from shuxueshuo_server.product.models import metadata

config = context.config


def run(connection):
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        lock(connection, 'product.alembic')
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError('Use the reviewed SQL files for offline inspection; migrations require a PostgreSQL connection.')
elif config.attributes.get('connection') is not None:
    run(config.attributes['connection'])
else:
    import os
    db = engine(os.environ['PRODUCT_MIGRATION_DATABASE_URL'])
    with db.begin() as connection:
        run(connection)
    db.dispose()
