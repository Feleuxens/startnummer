"""Cross-sport primitives. Depends only on core.enums."""

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


class Athlete(BaseModel):
    # EntryTable data. The match to an athlete is confidence-wrapped (Subject.athlete);
    name: str
    bib: str | None = None
    club: str | None = None
    age_category: str | None = None
    entered_events: list[str] = Field(
        default_factory=list
    )  # raw entry labels, e.g. "100m"
    athlete_id: UUID | None = None  # stable key for the face gallery


class Subject(BaseModel):
    # One person in a photo; a photo may contain several.
    # Candidate bibs, highest confidence first; >1 element = unresolved ambiguity.
    bibs: list[Confident[str]] = Field(default_factory=list)
    athlete: Confident[Athlete] | None = None


class SportEvent(BaseModel):
    # Marker base for per-sport event models. Subclasses add a Literal sport
    # discriminator plus sport-specific fields.
    pass


class TagNamespace(StrEnum):
    CLUB = "club"
    DISCIPLINE = "discipline"


class Tag(NamedTuple):
    namespace: TagNamespace
    value: str  # human-readable; the exporter emits this and drops the namespace
