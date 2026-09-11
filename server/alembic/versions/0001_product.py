"""Initial product schema. Frozen SQL, independent of future Python model changes."""
from pathlib import Path
from alembic import op
from sqlalchemy import text

revision = '0001_product'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for name in ('0001_schema.sql', '0001_guards.sql'):
        op.get_bind().execute(text(Path(__file__).with_name(name).read_text()))


def downgrade():
    raise RuntimeError('No destructive downgrade; restore a backup into a new instance.')
