"""Batch, photo, job, and publication tables."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SettingsRow(Base):
    __tablename__ = "sn_settings"
    owner_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)


class BatchRow(Base):
    __tablename__ = "sn_batches"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    document: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PhotoRow(Base):
    __tablename__ = "sn_photos"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("sn_batches.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    ordinal: Mapped[int] = mapped_column(Integer)
    blob_key: Mapped[str] = mapped_column(String(250))
    content_hash: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30))
    document: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (
        UniqueConstraint("batch_id", "ordinal"),
        Index("sn_photos_owner_blob", "owner_id", "blob_key"),
        Index("sn_photos_owner_status", "owner_id", "status"),
    )


class JobRow(Base):
    __tablename__ = "sn_jobs"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("sn_batches.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    state: Mapped[str] = mapped_column(String(20), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PublicationRow(Base):
    __tablename__ = "sn_publications"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("sn_batches.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    photo_id: Mapped[UUID] = mapped_column(ForeignKey("sn_photos.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)


class BlobGarbageRow(Base):
    __tablename__ = "sn_blob_garbage"
    owner_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    blob_key: Mapped[str] = mapped_column(String(250), primary_key=True)
