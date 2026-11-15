"""Initial Startnummer schema: batches, jobs, settings, and integrations."""

import sqlalchemy as sa
from alembic import op

# Preserve the complete pre-release schema's revision for existing development databases.
revision = "0003"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sn_blob_garbage",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("blob_key", sa.String(250), primary_key=True),
    )
    op.create_table(
        "sn_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sn_batches_owner_id", "sn_batches", ["owner_id"])
    op.create_table(
        "sn_photos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("sn_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("blob_key", sa.String(250), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.UniqueConstraint("batch_id", "ordinal"),
    )
    op.create_index("ix_sn_photos_batch_id", "sn_photos", ["batch_id"])
    op.create_index("sn_photos_owner_blob", "sn_photos", ["owner_id", "blob_key"])
    op.create_index("sn_photos_owner_status", "sn_photos", ["owner_id", "status"])
    op.create_table(
        "sn_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("sn_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(40), nullable=False),
        sa.Column("error", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("owner_id", "batch_id", "state"):
        op.create_index("ix_sn_jobs_" + column, "sn_jobs", [column])
    op.create_table(
        "sn_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("batch_id", sa.Uuid(), sa.ForeignKey("sn_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("photo_id", sa.Uuid(), sa.ForeignKey("sn_photos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
    )
    for column in ("owner_id", "batch_id"):
        op.create_index("ix_sn_publications_" + column, "sn_publications", [column])
    op.create_table(
        "sn_settings",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
    )
    op.create_table(
        "sn_integrations",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("credentials", sa.Text(), nullable=False),
    )
    op.create_table(
        "sn_gallery_bindings",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("url", sa.String(2048), primary_key=True),
        sa.Column("identity", sa.String(64), nullable=False),
        sa.Column("legacy_confirmed", sa.Boolean(), nullable=False),
    )


def downgrade():
    for table in (
        "sn_gallery_bindings",
        "sn_integrations",
        "sn_settings",
        "sn_publications",
        "sn_jobs",
        "sn_photos",
        "sn_batches",
        "sn_blob_garbage",
    ):
        op.drop_table(table)
