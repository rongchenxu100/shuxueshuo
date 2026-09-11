"""Indexes for bounded runtime recovery scans; preserve P1 data and guards."""
from alembic import op
import sqlalchemy as sa

revision = '0002_product_runtime_indexes'
down_revision = '0001_product'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_jobs_expired_lease', 'jobs', ['lease_expires_at', 'id'],
                    postgresql_where=sa.text("status = 'running'"))
    op.create_index('ix_batch_items_problem', 'batch_items', ['problem_id', 'batch_id'])


def downgrade():
    op.drop_index('ix_batch_items_problem', table_name='batch_items')
    op.drop_index('ix_jobs_expired_lease', table_name='jobs')
