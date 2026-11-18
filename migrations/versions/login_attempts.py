"""Share login failure counters across API instances."""

import sqlalchemy as sa
from alembic import op

revision = "3"
down_revision = "2"


def upgrade():
    op.create_table(
        "sn_login_attempts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("reservation", sa.Uuid()),
    )
    op.create_index("ix_sn_login_attempts_expires_at", "sn_login_attempts", ["expires_at"])


def downgrade():
    op.drop_table("sn_login_attempts")
