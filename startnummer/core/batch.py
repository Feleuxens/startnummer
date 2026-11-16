"""Saved batches, review revisions, jobs, and publication records."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from startnummer.core.enums import Status
from startnummer.core.interfaces import EntryList
from startnummer.core.record import Album, AnalysisRecord


def now() -> datetime:
    return datetime.now(UTC)


class WorkflowError(Exception):
    """An expected, safe-to-display workflow error."""


class Missing(WorkflowError):
    pass


class Conflict(WorkflowError):
    pass


class AnalysisDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    record: AnalysisRecord


class Destination(BaseModel):
    instance: str
    image_id: int = Field(gt=0)
    page_url: str
    gallery_identity: str | None = None


class Photo(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID = Field(default_factory=uuid4)
    display_name: str
    blob_key: str
    content_hash: str
    size: int
    mime_type: str
    width: int = 0
    height: int = 0
    destination: Destination | None = None
    current_description: str | None = None
    analysis: AnalysisDocument | None = None
    proposal: str | None = None
    caption: str | None = None
    caption_edited: bool = False
    revision: int = 0
    approved_revision: int | None = None
    replace_existing: bool = False
    conflicts_resolved: bool = False

    @property
    def approved(self) -> bool:
        return self.approved_revision is not None and self.approved_revision == self.revision

    @property
    def can_approve(self) -> bool:
        return bool(
            self.caption
            and self.caption.strip()
            and self.analysis is not None
            and (not self.current_description or self.replace_existing or self.current_description == self.caption)
        )

    @property
    def eligible(self) -> bool:
        status = self.analysis.record.status if self.analysis else Status.PENDING
        return self.can_approve and (status is Status.AUTO or self.conflicts_resolved)

    def changed(self) -> None:
        self.revision += 1
        self.approved_revision = None


class Batch(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    schema_version: Literal[1] = 1
    album: Album
    roster: EntryList
    photos: list[Photo]
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    def photo(self, photo_id: UUID) -> Photo:
        for photo in self.photos:
            if photo.id == photo_id:
                return photo
        raise Missing("Photo not found")


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FAILED = "failed"
    DONE = "done"
    CANCELLED = "cancelled"


class Job(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    batch_id: UUID
    state: JobState = JobState.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    lease_token: UUID | None = None
    lease_until: datetime | None = None
    completed: int = 0
    total: int = 0
    phase: str = "queued"
    error: str | None = None
    created_at: datetime = Field(default_factory=now)


class JobSource(Protocol):
    def claim(self, lease_seconds: int) -> Job | None: ...
    def heartbeat(self, job: Job, lease_seconds: int, completed: int, phase: str) -> bool: ...
    def fail(self, job: Job, error: str) -> None: ...


class WriteState(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"
    FAILURE = "failure"


class DescriptionWrite(BaseModel):
    destination: Destination
    expected: str | None
    replacement: str | None


class WriteResult(BaseModel):
    state: WriteState
    live_value: str | None = None
    error: str | None = None


class DescriptionWriter(Protocol):
    def write(self, change: DescriptionWrite) -> WriteResult: ...
    def inspect(self, change: DescriptionWrite) -> WriteResult: ...


class Publication(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    batch_id: UUID
    photo_id: UUID
    revision: int
    change: DescriptionWrite
    result: WriteResult = Field(default_factory=lambda: WriteResult(state=WriteState.PENDING))
    restored: bool = False
    created_at: datetime = Field(default_factory=now)
