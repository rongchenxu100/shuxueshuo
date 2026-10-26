"""A disposable native PostgreSQL cluster exercises the destructive local command."""
import os
import socket
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from alembic import command
from shuxueshuo_server.learning import content
from shuxueshuo_server.product.admin import database, learning, native
from shuxueshuo_server.product.config import REPO, Settings
from shuxueshuo_server.product.db import engine
from shuxueshuo_server.product.errors import Conflict, ProductError


def test_rebuild_rejects_server_before_reading_content(tmp_path):
    settings = Settings.load('server', tmp_path / 'server', 'test', initialize=True)
    with pytest.raises(ProductError, match='local_only'):
        learning.rebuild(settings)


@pytest.mark.skipif(os.getenv('RUN_LOCAL_REBUILD_TEST') != '1', reason='Explicit disposable PostgreSQL cluster test')
def test_local_0010_rebuild_is_atomic_and_preserves_other_data(tmp_path, monkeypatch):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    settings = Settings.load('local', tmp_path / 'legacy', 'legacy-stage3', port, initialize=True)
    native.start(settings)
    db = engine(settings.url('migration'))
    try:
        database.bootstrap(settings)
        config = Config(str(REPO / 'server/alembic.ini'))
        with db.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, '0010_learning_record_integrity')
        user = database.seed(db).user_id
        attempt = uuid4()
        with db.begin() as c:
            c.execute(text("INSERT INTO knowledge_nodes(id,label,kind,summary,explanation_md) VALUES('legacy-node','旧知识','knowledge','','')"))
            c.execute(text("INSERT INTO knowledge_drill_attempts(id,user_id,node_id) VALUES(:id,:u,'legacy-node')"), {'id': attempt, 'u': user})
            c.execute(text("INSERT INTO practice_problems(id,label,path,lesson_file,statement_md,problem_data) VALUES('legacy-problem','','/1/q01/','','','{}')"))
            c.execute(text("INSERT INTO student_learning_marks(user_id,problem_id,practiced) VALUES(:u,'legacy-problem',true),(:u,'unrelated-problem',true)"), {'u': user})
        with pytest.raises(DBAPIError, match='rebuild_required'):
            database.migrate(settings)

        rows = content.load_content()
        real_publish = content.publish

        def fail_after_import(connection, rows):
            real_publish(connection, rows)
            raise RuntimeError('injected failure after publication')

        monkeypatch.setattr(content, 'publish', fail_after_import)
        with pytest.raises(RuntimeError, match='injected failure'), db.begin() as c:
            learning.replace_legacy(c, settings, rows)
        with db.connect() as c:
            assert c.scalar(text('SELECT version_num FROM alembic_version')) == '0010_learning_record_integrity'
            assert c.scalar(text('SELECT count(*) FROM knowledge_drill_attempts')) == 1
            assert c.scalar(text('SELECT count(*) FROM student_learning_marks')) == 2
            assert c.scalar(text("SELECT to_regclass('learning_content_current')")) is None
        monkeypatch.setattr(content, 'publish', real_publish)
        result = learning.rebuild(settings)
        assert result['ok'] and result['cleared']['knowledge_drill_attempts'] == 1
        assert (Path(result['backup']) / 'database.dump').is_file()
        with db.connect() as c:
            assert c.scalar(text('SELECT count(*) FROM knowledge_nodes WHERE is_active')) == len(rows['knowledge_nodes'])
            assert c.scalar(text('SELECT count(*) FROM knowledge_drill_attempts')) == 0
            assert c.scalar(text('SELECT count(*) FROM users WHERE id=:u'), {'u': user}) == 1
            assert c.execute(text('SELECT problem_id FROM student_learning_marks')).scalars().all() == ['unrelated-problem']
        with pytest.raises(Conflict, match='requires_legacy_0010'):
            learning.rebuild(settings)
    finally:
        db.dispose()
        native.stop(settings)
