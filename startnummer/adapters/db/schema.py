"""Account, batch, job, integration, and publication tables."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, false
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "sn_users"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    username: Mapped[str] = mapped_column(String(64))
    username_key: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InstanceRow(Base):
    __tablename__ = "sn_instance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("sn_users.id"))
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class SessionRow(Base):
    __tablename__ = "sn_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("sn_users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginAttemptRow(Base):
    __tablename__ = "sn_login_attempts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reservation: Mapped[UUID | None] = mapped_column(Uuid)


class InvitationRow(Base):
    __tablename__ = "sn_invitations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("sn_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SettingsRow(Base):
    __tablename__ = "sn_settings"
    owner_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    document: Mapped[dict] = mapped_column(JSON)


class IntegrationRow(Base):
    __tablename__ = "sn_integrations"
    owner_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    credentials: Mapped[str] = mapped_column(Text)


class GalleryBindingRow(Base):
    __tablename__ = "sn_gallery_bindings"
    owner_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), primary_key=True)
    identity: Mapped[str] = mapped_column(String(64))
    legacy_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


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
