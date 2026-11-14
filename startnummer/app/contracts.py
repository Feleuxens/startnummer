"""HTTP contracts used to generate the frontend's TypeScript client."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from startnummer.core.batch import Batch, DescriptionWrite, Job, Publication
from startnummer.core.sports.athletics import AthleticsDiscipline


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: str
    password: str


class SessionInfo(BaseModel):
    username: str
    gallery_url: str | None = None


class BatchSummary(BaseModel):
    id: UUID
    name: str
    updated_at: datetime
    photo_count: int


class DisciplineOption(BaseModel):
    value: AthleticsDiscipline
    de: str | None
    en: str | None


class Selection(Input):
    photo_id: UUID
    revision: int = Field(ge=0)


class Selected(Input):
    photos: list[Selection] = Field(min_length=1)


class Revision(Input):
    revision: int = Field(ge=0)


class AddPerson(Revision):
    roster_index: int = Field(ge=0)


class Edit(Input):
    revision: int = Field(ge=0)
    caption: str | None = None
    subject: int | None = Field(default=None, ge=0)
    bib: str | None = None
    roster_bib: str | None = None
    athlete_name: str | None = None
    club: str | None = None
    discipline: AthleticsDiscipline | None = None
    replace_existing: bool = False
    conflicts_resolved: bool = False
    face_session_id: str | None = None


class BatchView(BaseModel):
    batch: Batch
    jobs: list[Job]
    publications: list[Publication]


class ChangePreview(BaseModel):
    photo_id: UUID
    revision: int
    display_name: str
    change: DescriptionWrite


class FaceBox(BaseModel):
    subject: int
    box: list[float]


class FaceView(BaseModel):
    available: bool
    session_id: str | None
    photos: dict[str, list[FaceBox]]
    expires_at: float | None = None
    undo_id: str | None = None
    undo_count: int = 0
    propagation_available: bool = False
    propagation_unavailable_reason: str | None = None


class FaceTarget(Selection):
    subject: int = Field(ge=0)


class PropagationRequest(Input):
    source: FaceTarget
    face_session_id: str = Field(min_length=1)


class PropagationApply(PropagationRequest):
    targets: list[FaceTarget] = Field(min_length=1)
    acknowledge_unsupported_bibs: bool = False
    acknowledge_tentative_names: bool = False


class PropagationUndo(Input):
    face_session_id: str = Field(min_length=1)
    undo_id: str = Field(min_length=1)


class PropagationCandidate(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    target: FaceTarget
    display_name: str
    box: list[float]
    current_name: str | None
    before_caption: str | None
    proposed_caption: str | None
    caption_preserved: bool
    reason: str | None
    state: Literal["eligible", "already_named", "blocked"]
    requires_bib_confirmation: bool = False
    replaces_tentative_name: bool = False
    warnings: list[str] = Field(default_factory=list)


class PropagationPreview(PropagationRequest):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    athlete_name: str
    candidates: list[PropagationCandidate]
    expires_at: float
    warnings: list[str] = Field(default_factory=list)
