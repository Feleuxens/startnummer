"""Allow administrators to disable user accounts."""

import sqlalchemy as sa
from alembic import op

revision = "2"
down_revision = "1"


def upgrade():
    op.add_column("sn_users", sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("sn_users", "disabled")
