"""Administrator-controlled import limits and face-session lifetime."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sn_settings",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("sn_settings")
