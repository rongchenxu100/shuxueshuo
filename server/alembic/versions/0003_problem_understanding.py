"""Independent source/candidate versions and durable extraction call reservations."""
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = '0003_problem_understanding'
down_revision = '0002_product_runtime_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix('.sql').read_text()))


def downgrade():
    raise RuntimeError('No destructive downgrade; restore a backup into a new instance.')
