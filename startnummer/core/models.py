"""Shared athlete, subject, event, and confidence models."""

from enum import StrEnum
from typing import NamedTuple, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

from startnummer.core.enums import Source

T = TypeVar("T")


class Confident[T](BaseModel):
    # Inferred value with its confidence [0, 1] and provenance.
    value: T
    confidence: float = Field(ge=0.0, le=1.0)
    source: Source
    note: str | None = None


class BaseDiscipline(StrEnum):
    pass


class Athlete(BaseModel):
    """Roster data; match confidence belongs to Subject.athlete."""

    name: str
    bib: str | None = None
    club: str | None = None
    year_birth: int | None = None
    # Canonical slugs such as "100m" or "long_jump", interpreted by each sport.
    entered_events: list[str] = Field(default_factory=list)
    athlete_id: UUID | None = None  # optional roster identity


class Subject(BaseModel):
    """One detected person and their OCR, propagated bibs, and roster match."""

    bibs: list[Confident[str]] = Field(default_factory=list)
    athlete: Confident[Athlete] | None = None
    identity_edited: bool = False  # also preserves an explicit removal of a bib
    added_manually: bool = False


class SportEvent(BaseModel):
    # Marker base for per-sport event models. Subclasses add a Literal sport
    # discriminator plus sport-specific fields.
    pass


class TagNamespace(StrEnum):
    CLUB = "club"
    DISCIPLINE = "discipline"


class Tag(NamedTuple):
    namespace: TagNamespace
    value: str  # human-readable label
