"""Allow non-curricular knowledge collections without changing existing content."""

from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = '0017_knowledge_collections'
down_revision = '0016_search_admission'
branch_labels = depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('Restore into a separate instance; do not discard knowledge identities.')
