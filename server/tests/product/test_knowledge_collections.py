"""Exercise the additive collection migration and empty-topic publication."""

import os
import socket

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from alembic import command
from shuxueshuo_server.learning import content
from shuxueshuo_server.product.admin import database, native
from shuxueshuo_server.product.config import REPO, Settings
from shuxueshuo_server.product.db import engine


@pytest.mark.skipif(
    os.getenv('RUN_LOCAL_REBUILD_TEST') != '1',
    reason='Explicit disposable PostgreSQL cluster test',
)
def test_collection_upgrade_preserves_content_and_publishes_zero_question_topic(tmp_path):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    settings = Settings.load('local', tmp_path / 'collections', 'collections-test', port, initialize=True)
    native.start(settings)
    db = engine(settings.url('migration'))
    try:
        database.bootstrap(settings)
        config = Config(str(REPO / 'server/alembic.ini'))
        with db.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, '0016_search_admission')
            connection.execute(text("INSERT INTO knowledge_nodes(id,label,kind,summary,explanation_md) VALUES('existing-knowledge','已有知识','knowledge','保留内容','保留内容')"))
        with pytest.raises(IntegrityError), db.begin() as connection:
            connection.execute(text("INSERT INTO knowledge_nodes(id,label,kind,summary,explanation_md) VALUES('junior-probe','初中知识','collection','','')"))
        with db.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
            assert connection.scalar(text("SELECT summary FROM knowledge_nodes WHERE id='existing-knowledge'")) == '保留内容'
            rows = content.load_content()
            content.publish(connection, rows)
            assert connection.scalar(text("SELECT kind FROM knowledge_nodes WHERE id='junior-knowledge'")) == 'collection'
            assert connection.scalar(text("SELECT path FROM practice_topics WHERE id='function-concepts'")) == '/topics/function-concepts/'
            assert connection.scalar(text("SELECT count(*) FROM practice_topic_problems WHERE topic_id='function-concepts'")) == 0
            assert connection.scalar(text("SELECT count(*) FROM knowledge_nodes WHERE kind='problem_type' AND body->>'status'='planned' AND is_active")) == 5
            assert connection.scalar(text('SELECT count(*) FROM practice_problems WHERE is_active')) == 39
        with pytest.raises(IntegrityError), db.begin() as connection:
            connection.execute(text("INSERT INTO knowledge_nodes(id,label,kind,summary,explanation_md) VALUES('invalid-kind','错误类型','unknown','','')"))
    finally:
        db.dispose()
        native.stop(settings)
