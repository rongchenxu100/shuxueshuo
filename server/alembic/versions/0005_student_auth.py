"""Student phone identities, OTP challenges and revocable site sessions."""
from pathlib import Path
from alembic import op
from sqlalchemy import text

revision = "0005_student_auth"
down_revision = "0004_math_runtime_binding"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(text(Path(__file__).with_suffix(".sql").read_text()))


def downgrade():
    raise RuntimeError("No destructive downgrade; restore into a new instance.")
