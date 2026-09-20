"""Versioned pure-code mathematical runtime binding and admission."""

from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0004_math_runtime_binding"
down_revision = "0003_problem_understanding"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix(".sql").read_text()))


def downgrade():
    raise RuntimeError("No destructive downgrade; restore into a new instance.")
