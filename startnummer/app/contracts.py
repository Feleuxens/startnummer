"""HTTP contracts used to generate the frontend's TypeScript client."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from startnummer.core.batch import Batch, DescriptionWrite, Job, Publication
from startnummer.core.description import caption_name_key
from startnummer.core.interfaces import EntryList
from startnummer.core.models import CaptionNameOverride
from startnummer.core.sports.athletics import AthleticsDiscipline


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: str
    password: str


class SessionInfo(BaseModel):
    username: str
    gallery_url: str | None = None
    is_admin: bool = False


class AuthStatus(BaseModel):
    setup_required: bool
    registration_enabled: bool


class Registration(Input):
    username: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
    password: SecretStr = Field(min_length=12, max_length=1024)
    invitation: SecretStr | None = Field(default=None, max_length=128)


class Setup(Registration):
    code: SecretStr = Field(min_length=1, max_length=256)


class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    password: SecretStr = Field(min_length=12, max_length=1024)


class AdminPasswordReset(Input):
    administrator_password: SecretStr = Field(min_length=1, max_length=1024)
    password: SecretStr = Field(min_length=12, max_length=1024)


class AccountAccess(Input):
    disabled: bool


class AccountAccessResult(BaseModel):
    disabled: bool
    review_cleared: bool


class RegistrationPolicy(Input):
    revision: int = Field(ge=0)
    registration_enabled: bool


class UserInfo(BaseModel):
    id: UUID
    username: str
    is_admin: bool
    disabled: bool
    created_at: datetime


class InvitationInfo(BaseModel):
    id: UUID
    label: str
    expires_at: datetime
    state: Literal["available", "expired", "used", "revoked"]


class InvitationCreated(InvitationInfo):
    token: str


class InvitationRequest(Input):
    label: str = Field(default="", max_length=120)
    hours: int = Field(default=48, ge=1, le=168)


class AccountAdministration(RegistrationPolicy):
    users: list[UserInfo]
    invitations: list[InvitationInfo]


class CheveretoConnection(Input):
    revision: int = Field(default=0, ge=0)
    url: str = Field(min_length=1, max_length=2048)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr | None = None

    @field_validator("url")
    @classmethod
    def gallery_url(cls, value):
        from urllib.parse import urlparse

        parsed = urlparse(value)
        port = parsed.port
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (port is not None and port < 1)
        ):
            raise ValueError("Use an HTTP or HTTPS gallery URL without credentials, a query, or a fragment")
        return value.rstrip("/")

    @field_validator("host")
    @classmethod
    def database_host(cls, value):
        if any(char.isspace() or char in "/@?#\\" for char in value):
            raise ValueError("Enter a database hostname or IP address")
        return value


class IntegrationStatus(BaseModel):
    source: Literal["environment", "administration"]
    revision: int = 0
    configured: bool = False
    editable: bool = False
    url: str | None = None
    host: str = ""
    port: int = 3306
    database: str = ""
    username: str = ""
    password_set: bool = False
    encryption_ready: bool = False
    error: str | None = None
    legacy_photos: int = 0
    legacy_confirmed: bool = False


class ConnectionTest(BaseModel):
    version: str
    message: str = "Connection and Chevereto 4.5.9 schema verified. No descriptions were written."


class IntegrationRevision(Input):
    revision: int = Field(ge=0)


class RuntimeSettings(Input):
    revision: int = Field(default=0, ge=0)
    max_file_bytes: int = Field(ge=1024 * 1024, le=500 * 1024 * 1024)
    max_batch_bytes: int = Field(ge=1024 * 1024, le=100 * 1024 * 1024 * 1024)
    session_ttl: int = Field(ge=60, le=86400)

    @model_validator(mode="after")
    def batch_contains_file(self):
        if self.max_batch_bytes < self.max_file_bytes:
            raise ValueError("Batch limit must be at least the per-photo limit")
        return self


class CaptionNames(Input):
    revision: int = Field(default=0, ge=0)
    overrides: list[CaptionNameOverride] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def unique_names(self):
        keys = [caption_name_key(rule.source_name) for rule in self.overrides]
        if len(set(keys)) != len(keys):
            raise ValueError("Each full source name can have only one override")
        return self


class WorkerHealth(BaseModel):
    reachable: bool
    state: Literal["starting", "idle", "busy", "unavailable"]
    active_sessions: int = 0


class Administration(BaseModel):
    database: bool
    storage: bool
    worker: WorkerHealth
    jobs: dict[str, int]
    settings: RuntimeSettings


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


class DisciplineAssignment(Selected):
    discipline: AthleticsDiscipline
    caption_names_revision: int | None = Field(default=None, ge=0)


class DisciplineChange(BaseModel):
    photo_id: UUID
    revision: int
    display_name: str
    before_discipline: AthleticsDiscipline | None
    manual_discipline: bool
    before_caption: str | None
    after_caption: str | None
    caption_preserved: bool
    changed: bool


class DisciplinePreview(BaseModel):
    caption_names_revision: int | None = None
    discipline: AthleticsDiscipline
    photos: list[DisciplineChange]


class Revision(Input):
    revision: int = Field(ge=0)


class ManualPerson(Input):
    name: str = Field(min_length=1, max_length=200)
    bib: str = Field(default="", max_length=64)
    club: str = Field(default="", max_length=200)

    @field_validator("name", "bib", "club", mode="before")
    @classmethod
    def trim_details(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class AddPerson(Revision):
    roster_index: int | None = Field(default=None, ge=0)
    person: ManualPerson | None = None

    @model_validator(mode="after")
    def one_person_source(self):
        if (self.roster_index is None) == (self.person is None):
            raise ValueError("Select a roster entry or enter a person's details")
        return self


class SubjectEdit(Input):
    subject: int = Field(ge=0)
    bib: str | None = None
    roster_bib: str | None = None
    roster_index: int | None = Field(default=None, ge=0)
    athlete_name: str | None = None
    club: str | None = None
    excluded_from_caption: bool | None = None
    face_session_id: str | None = None


class Edit(Input):
    revision: int = Field(ge=0)
    caption: str | None = None
    subject: int | None = Field(default=None, ge=0)
    bib: str | None = None
    roster_bib: str | None = None
    roster_index: int | None = Field(default=None, ge=0)
    athlete_name: str | None = None
    club: str | None = None
    discipline: AthleticsDiscipline | None = None
    replace_existing: bool = False
    conflicts_resolved: bool = False
    face_session_id: str | None = None
    subjects: list[SubjectEdit] = Field(default_factory=list)
    use_generated_caption: bool = False


class RosterNameEdit(Input):
    index: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a name")
        return value


class RosterPreview(BaseModel):
    roster: EntryList
    digest: str


class ImportFileProblem(BaseModel):
    name: str
    detail: str
    index: int | None = None


class ImportProblem(BaseModel):
    field: Literal["photos", "album", "roster"] | None = None
    detail: str
    files: list[ImportFileProblem] = Field(default_factory=list)


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
    caption_names_revision: int | None = Field(default=None, ge=0)


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
