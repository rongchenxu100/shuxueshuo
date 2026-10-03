"""Minimal student learning marks; no answers or exercise history."""
from pathlib import Path

from sqlalchemy import text

from alembic import op

revision = "0007_learning_marks"
down_revision = "0006_tutor_usage"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix(".sql").read_text()))


def downgrade():
    raise RuntimeError("No destructive downgrade; restore into a new instance.")
