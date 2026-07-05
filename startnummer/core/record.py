"""Album and AnalysisRecord — the persisted, owned entities.

Primitives live in core.models; the Event union is assembled in core.sports.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from startnummer.core.enums import Sport, Status
from startnummer.core.models import Subject
from startnummer.core.sports import Event

_HASH_PREFIX = "sha256:"
_HASH_LENGTH = len(_HASH_PREFIX) + 64  # prefix + 64 hex chars


class Album(BaseModel):
    # One competition. Sport is fixed here (set at upload).
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    name: str
    sport: Sport
    roster_source: str | None = None  # path/id the roster was parsed from
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnalysisRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID  # required, no default
    album_id: UUID  # required; sport comes from the album via the event

    content_hash: str  # "sha256:<64 hex>"
    source_path: str | None = None

    event: Event
    subjects: list[Subject] = Field(default_factory=list)

    description: str | None = (
        None  # stored: may come from the VLM and be edited in review
    )
    extra_tags: list[str] = Field(
        default_factory=list
    )  # manual additions; derived tags are not stored

    status: Status = Status.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        if not value.startswith(_HASH_PREFIX) or len(value) != _HASH_LENGTH:
            raise ValueError(f"content_hash must match '{_HASH_PREFIX}<64 hex chars>'")
        int(value[len(_HASH_PREFIX) :], 16)  # raises if not hex
        return value

    @property
    def sport(self) -> Sport:
        return self.event.sport
