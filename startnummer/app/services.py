"""Batch import, caption review, and publication use cases."""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import PurePath
from urllib.parse import urlparse
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError

from startnummer.adapters.db.store import Store
from startnummer.adapters.entrylist.ergebnisse_leichtathletik_de import LeichtathletikDeEntryListParser
from startnummer.adapters.face.sessions import propagation_problem
from startnummer.adapters.photo_dates import capture_time, modified_time
from startnummer.app.captions import caption_overrides
from startnummer.app.contracts import (
    DisciplineChange,
    DisciplinePreview,
    FaceTarget,
    PropagationCandidate,
    PropagationPreview,
    RosterPreview,
    SubjectEdit,
)
from startnummer.app.operations import effective_settings
from startnummer.core.batch import (
    AnalysisDocument,
    Batch,
    Conflict,
    DescriptionWrite,
    Missing,
    Photo,
    Publication,
    WorkflowError,
    WriteResult,
    WriteState,
)
from startnummer.core.description import build_description
from startnummer.core.entrytable import ATHLETE_AUTO, match_subject, trusted_bib_values
from startnummer.core.enums import NameOrder, Source, Sport, Status
from startnummer.core.errors import BlobNotFound
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete, Confident, Subject
from startnummer.core.pipeline import STRONG_BIB_CONFIDENCE
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.sports import get
from startnummer.core.sports.athletics import AthleticsDiscipline, AthleticsEvent


@dataclass
class InputPhoto:
    name: str
    data: bytes
    destination: object = None
    description: str | None = None
    date_modified: datetime | None = None


def run(awaitable):
    """Run an async blob operation from synchronous code."""
    return asyncio.run(awaitable)


async def chunks(data):
    yield data


@dataclass
class DownloadedSource:
    data: bytes
    date_modified: datetime | None


class Services:
    def __init__(self, store: Store, blobs, settings, sessions, gallery=None, fetch=None):
        self.store, self.blobs, self.settings = store, blobs, settings
        self.sessions, self.gallery = sessions, gallery
        self.fetch = fetch or self._fetch

    def _fetch(self, url: str, *, roster: bool = False, gallery_base: str | None = None) -> bytes:
        return self._download(url, roster=roster, gallery_base=gallery_base).data

    def _download(self, url: str, *, roster: bool = False, gallery_base: str | None = None) -> DownloadedSource:
        parsed = urlparse(url)
        if roster:
            allowed = parsed.scheme in ("http", "https") and parsed.hostname in self.settings.roster_hosts
            allowed = allowed and parsed.port in (None, 80, 443)
        else:
            configured = urlparse(gallery_base or self.settings.chevereto_url or "")
            allowed = (parsed.scheme, parsed.netloc) == (configured.scheme, configured.netloc)
        if not allowed or parsed.username or parsed.password:
            raise WorkflowError("URL is not a supported/configured source")
        maximum = effective_settings(self.store, self.settings).max_file_bytes
        limit = min(maximum, 10 * 1024 * 1024) if roster else maximum
        try:
            with httpx.stream("GET", url, follow_redirects=False, timeout=60, trust_env=False) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        raise WorkflowError("Source exceeds the configured size limit")
                return DownloadedSource(bytes(data), modified_time(response.headers.get("last-modified")))
        except httpx.HTTPError as exc:
            raise WorkflowError("Could not fetch the configured source; check its URL and access") from exc

    def _gallery(self):
        if self.gallery is None:
            raise WorkflowError("No gallery is configured")
        return self.gallery.snapshot() if hasattr(self.gallery, "snapshot") else self.gallery

    def _read_roster(self, roster_html, roster_url, name_order):
        roster_url = (roster_url or "").strip() or None
        if roster_html is not None and roster_url:
            raise WorkflowError("Choose only one roster source: HTML upload or supported URL")
        if roster_url:
            roster_html = self.fetch(roster_url, roster=True)
        roster = EntryList(name_order=name_order)
        if roster_html is not None:
            try:
                roster = LeichtathletikDeEntryListParser().parse_content(
                    roster_html.decode("utf-8-sig"), name_order=name_order
                )
            except (ValueError, UnicodeError) as exc:
                raise WorkflowError("Roster must be supported Competitoroverview or Resultoverview HTML") from exc
            if not roster.athletes:
                raise WorkflowError("The roster contains no supported entries")
        bibs = [athlete.bib for athlete in roster.athletes if athlete.bib]
        if len(set(bibs)) != len(bibs):
            raise WorkflowError("Roster contains duplicate bib numbers; correct the roster before analysis")
        return roster

    @staticmethod
    def _roster_digest(roster):
        return hashlib.sha256(roster.model_dump_json().encode()).hexdigest()

    def preview_roster(self, roster_html, roster_url, name_order=NameOrder.AUTO):
        roster = self._read_roster(roster_html, roster_url, name_order)
        if not roster.athletes:
            raise WorkflowError("Choose a roster to preview")
        return RosterPreview(roster=roster, digest=self._roster_digest(roster))

    def import_batch(
        self,
        owner_id,
        name,
        meet_name,
        photos,
        gallery_url,
        roster_html,
        roster_url,
        import_id=None,
        *,
        name_order=NameOrder.AUTO,
        roster_digest=None,
        roster_names=(),
    ) -> Batch:
        limits = effective_settings(self.store, self.settings)
        if import_id:
            try:
                return self.store.get(owner_id, import_id)
            except Missing:
                pass
        roster_url = (roster_url or "").strip() or None
        roster = self._read_roster(roster_html, roster_url, name_order)
        if roster_names and not roster_digest:
            raise WorkflowError("Preview roster names before correcting them")
        if roster_digest is not None and roster_digest != self._roster_digest(roster):
            raise Conflict("Roster changed since the preview; preview roster names again")
        if len({correction.index for correction in roster_names}) != len(roster_names):
            raise WorkflowError("Correct each roster name only once")
        for correction in roster_names:
            if correction.index >= len(roster.athletes):
                raise WorkflowError("Choose a valid roster entry")
            roster.athletes[correction.index].name = correction.name
            roster.name_parsing[correction.index].needs_review = False
        if gallery_url:
            if photos:
                raise WorkflowError("Choose either gallery import or uploaded photos")
            gallery = self._gallery()
            album_name, remote = gallery.album(gallery_url)
            photos = []
            total = 0
            for remote_photo in remote:
                downloaded = (
                    self._download(remote_photo.source_url, gallery_base=gallery.base_url)
                    if self.fetch == self._fetch
                    else DownloadedSource(self.fetch(remote_photo.source_url), None)
                )
                data = downloaded.data
                total += len(data)
                if total > limits.max_batch_bytes:
                    raise WorkflowError("Batch exceeds the configured size limit")
                photos.append(
                    InputPhoto(
                        remote_photo.name,
                        data,
                        remote_photo.destination,
                        remote_photo.description,
                        downloaded.date_modified,
                    )
                )
            name = (name or "").strip() or album_name
        if not photos:
            raise WorkflowError("The batch contains no photos")
        if sum(len(p.data) for p in photos) > limits.max_batch_bytes:
            raise WorkflowError("Batch exceeds the configured size limit")
        # Reject invalid images before storing the batch or its bytes.
        checked = []
        for photo in photos:
            if len(photo.data) > limits.max_file_bytes:
                raise WorkflowError(f"Image exceeds the size limit: {PurePath(photo.name).name}")
            try:
                with Image.open(BytesIO(photo.data)) as image:
                    if image.format not in {"JPEG", "MPO", "PNG", "WEBP"}:
                        raise WorkflowError(
                            f"Supported photo formats are JPEG, PNG, and WebP; unsupported file: "
                            f"{PurePath(photo.name).name} ({image.format})"
                        )
                    width, height = image.size
                    if width * height > 50_000_000:
                        raise WorkflowError("Image dimensions exceed the supported limit")
                    # MPO stores additional JPEG frames; serve the unchanged primary JPEG to the browser.
                    mime = "image/jpeg" if image.format == "MPO" else Image.MIME[image.format]
                    if image.getexif().get(274, 1) in {5, 6, 7, 8}:
                        width, height = height, width
                    date_taken = capture_time(image)
                    image.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise WorkflowError("A selected file is not a valid supported image") from exc
            checked.append((photo, width, height, mime, date_taken))
        album = Album(
            owner_id=owner_id,
            name=(name or "").strip() or "New batch",
            sport=Sport.ATHLETICS,
            meet_name=(meet_name or "").strip() or (roster.competition or "").strip() or None,
            roster_source=roster_url or ("uploaded roster HTML" if roster_html is not None else None),
        )
        if import_id:
            album.id = import_id
        batch = Batch(album=album, roster=roster, photos=[])
        written = set()
        try:
            with self.store.transaction(owner_id) as session:
                if import_id:
                    try:
                        return self.store.load(session, owner_id, import_id)
                    except Missing:
                        pass
                for photo, width, height, mime, date_taken in checked:
                    digest = "sha256:" + hashlib.sha256(photo.data).hexdigest()
                    ref = run(self.blobs.put(owner_id, digest, chunks(photo.data)))
                    written.add(ref.key)
                    batch.photos.append(
                        Photo(
                            display_name=PurePath(photo.name).name,
                            content_hash=digest,
                            blob_key=ref.key,
                            size=ref.size,
                            mime_type=mime,
                            width=width,
                            height=height,
                            date_modified=photo.date_modified,
                            date_taken=date_taken,
                            date_taken_read=True,
                            destination=photo.destination,
                            current_description=photo.description,
                        )
                    )
                self.store.save(session, batch)
                session.flush()
        except BaseException:
            # Cleanup also covers commit failures. Reference checks keep blobs
            # if the commit succeeded but its acknowledgement was lost.
            with self.store.transaction(owner_id) as cleanup:
                self.store.schedule_cleanup(cleanup, owner_id, written)
            self.store.cleanup(owner_id, lambda key: run(self.blobs.delete(owner_id, key)))
            raise
        return batch

    def read_photo_dates(self, owner_id, batch_id):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            pending = [photo for photo in batch.photos if not photo.date_taken_read]
            for photo in pending:
                try:
                    with self.blobs.open(owner_id, photo.blob_key) as original, Image.open(original) as image:
                        photo.date_taken = capture_time(image)
                except (BlobNotFound, OSError, ValueError) as exc:
                    raise WorkflowError(f"Could not read photo dates: {photo.display_name}") from exc
                photo.date_taken_read = True
            if pending:
                self.store.save(session, batch)
            return batch

    def delete_batch(self, owner_id, batch_id):
        with self.store.transaction(owner_id) as session:
            self.store.load(session, owner_id, batch_id, lock=True)
            # Serialize session cleanup with worker completion and new analysis.
            self.sessions.finish(owner_id, batch_id)
            keys = self.store.delete_batch(session, owner_id, batch_id)
            self.store.schedule_cleanup(session, owner_id, keys)
        self.store.cleanup(owner_id, lambda key: run(self.blobs.delete(owner_id, key)))

    def analyze(self, owner_id, batch_id):
        def discard_session():
            if self.sessions.get(owner_id, batch_id)["available"]:
                self.sessions.finish(owner_id, batch_id)

        return self.store.enqueue(owner_id, batch_id, before_queue=discard_session)

    def cancel_analysis(self, owner_id, batch_id):
        with self.store.transaction(owner_id) as session:
            self.store.load(session, owner_id, batch_id, lock=True)
            self.sessions.finish(owner_id, batch_id)
            self.store.cancel(session, owner_id, batch_id)

    def add_person(self, owner_id, batch_id, photo_id, request):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != request.revision:
                raise Conflict("This photo changed; reload before adding a person")
            if not 0 <= request.roster_index < len(batch.roster.athletes):
                raise WorkflowError("Choose a person from this batch's roster")
            athlete = batch.roster.athletes[request.roster_index]
            if not athlete.name.strip():
                raise WorkflowError("The selected roster entry has no name")
            if photo.analysis is None:
                photo.analysis = AnalysisDocument(
                    record=AnalysisRecord(
                        owner_id=owner_id,
                        album_id=batch_id,
                        content_hash=photo.content_hash,
                        meet_name=batch.album.meet_name,
                        event=get(batch.album.sport).new_event(),
                        status=Status.NEEDS_REVIEW,
                    )
                )
            if any(
                subject.athlete
                and (subject.athlete.value.name, subject.athlete.value.bib) == (athlete.name, athlete.bib)
                for subject in photo.analysis.record.subjects
            ):
                raise WorkflowError(
                    "This person is already listed in the photo; select their existing entry to edit it"
                )
            photo.analysis.record.subjects.append(
                Subject(
                    athlete=Confident[Athlete](
                        value=athlete.model_copy(deep=True),
                        confidence=1,
                        source=Source.MANUAL,
                        note="Added from the roster during review",
                    ),
                    identity_edited=True,
                    added_manually=True,
                )
            )
            self._regenerate_subject_caption(photo, caption_overrides(self.store, owner_id, session=session)[1])
            photo.conflicts_resolved = False
            photo.changed()
            self.store.save(session, batch)
            return photo

    def remove_person(self, owner_id, batch_id, photo_id, subject_index, revision):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != revision:
                raise Conflict("This photo changed; reload before removing a person")
            if photo.analysis is None or not 0 <= subject_index < len(photo.analysis.record.subjects):
                raise WorkflowError("Select a valid person")
            if not photo.analysis.record.subjects[subject_index].added_manually:
                raise Conflict("Only people added manually can be removed with this action")
            photo.analysis.record.subjects.pop(subject_index)
            self._regenerate_subject_caption(photo, caption_overrides(self.store, owner_id, session=session)[1])
            photo.conflicts_resolved = False
            photo.changed()
            self.store.save(session, batch)
            return photo

    def edit(self, owner_id, batch_id, photo_id, patch):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != patch.revision:
                raise Conflict("This photo changed since it was opened; reload before saving")
            fields = patch.model_fields_set
            record = photo.analysis.record if photo.analysis else None
            identity_fields = {"bib", "athlete_name", "roster_bib", "roster_index", "club"}
            corrections = patch.subjects
            if corrections and fields & (identity_fields | {"subject", "face_session_id"}):
                raise WorkflowError("Use either individual or multiple subject corrections, not both")
            if fields & identity_fields:
                if patch.subject is None:
                    raise WorkflowError("Select a valid subject")
                values = {key: getattr(patch, key) for key in fields & (identity_fields | {"face_session_id"})}
                corrections = [SubjectEdit(subject=patch.subject, **values)]
            if len({correction.subject for correction in corrections}) != len(corrections):
                raise WorkflowError("Correct each subject only once")
            if patch.use_generated_caption and "caption" in fields:
                raise WorkflowError("Choose either a manual caption or the generated caption")
            if corrections or "discipline" in fields or patch.use_generated_caption:
                if record is None:
                    raise Conflict("Analyze the photo before correcting subjects or discipline")
                _, names = caption_overrides(self.store, owner_id, session=session)
                for correction in corrections:
                    self._edit_subject(batch, photo, correction)
                if patch.use_generated_caption:
                    photo.caption_edited = False
                if corrections:
                    self._regenerate_subject_caption(photo, names)
                if "discipline" in fields:
                    self._set_discipline(photo, patch.discipline, names)
                elif not corrections:
                    photo.proposal = record.description = build_description(record, name_overrides=names)
                    if not photo.caption_edited:
                        photo.caption = photo.proposal
            if "caption" in fields:
                photo.caption = patch.caption
                photo.caption_edited = True
            if "replace_existing" in fields:
                photo.replace_existing = patch.replace_existing
            if "conflicts_resolved" in fields:
                photo.conflicts_resolved = patch.conflicts_resolved
            photo.changed()
            self.store.save(session, batch)
            return photo

    def refresh_caption_suggestion(self, owner_id, batch_id, photo_id, revision):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != revision:
                raise Conflict("This photo changed; reload before refreshing its caption suggestion")
            if photo.analysis is None:
                raise Conflict("Analyze the photo before generating a caption suggestion")
            _, names = caption_overrides(self.store, owner_id, session=session)
            suggestion = build_description(photo.analysis.record, name_overrides=names)
            if suggestion != photo.proposal or (not photo.caption_edited and suggestion != photo.caption):
                photo.proposal = photo.analysis.record.description = suggestion
                if not photo.caption_edited:
                    photo.caption = suggestion
                photo.changed()
                self.store.save(session, batch)
            return photo

    def _edit_subject(self, batch, photo, correction):
        record = photo.analysis.record
        if not 0 <= correction.subject < len(record.subjects):
            raise WorkflowError("Select a valid subject")
        subject = record.subjects[correction.subject]
        fields = correction.model_fields_set
        if correction.face_session_id is not None:
            self.sessions.validate(
                batch.album.owner_id, batch.album.id, photo.id, correction.subject, correction.face_session_id
            )
        if "excluded_from_caption" in fields:
            if correction.excluded_from_caption is None:
                raise WorkflowError("Choose whether to include the person in the caption")
            subject.excluded_from_caption = correction.excluded_from_caption
        if fields & {"bib", "athlete_name", "roster_bib", "roster_index", "club"}:
            subject.identity_edited = True
        if "bib" in fields:
            subject.bibs = (
                [Confident[str](value=correction.bib, confidence=1, source=Source.MANUAL)] if correction.bib else []
            )
            subject.athlete = None
            match_subject(subject, [], batch.roster)
        if "roster_bib" in fields and "roster_index" in fields:
            raise WorkflowError("Choose only one roster athlete reference")
        if "roster_index" in fields:
            if correction.roster_index is None or not 0 <= correction.roster_index < len(batch.roster.athletes):
                raise WorkflowError("Choose a person from this batch's roster")
            subject.athlete = Confident[Athlete](
                value=batch.roster.athletes[correction.roster_index], confidence=1, source=Source.MANUAL
            )
        elif "roster_bib" in fields:
            if not correction.roster_bib:
                raise WorkflowError("Select a roster athlete")
            athlete = batch.roster.by_bib(correction.roster_bib)
            if athlete is None:
                raise WorkflowError("Roster athlete not found")
            subject.athlete = Confident[Athlete](value=athlete, confidence=1, source=Source.MANUAL)
        elif "athlete_name" in fields:
            if not correction.athlete_name or not correction.athlete_name.strip():
                raise WorkflowError("Enter a name or select a roster athlete")
            subject.athlete = Confident[Athlete](
                value=Athlete(name=correction.athlete_name.strip(), club=correction.club or None),
                confidence=1,
                source=Source.MANUAL,
            )
        if "club" in fields and subject.athlete is not None:
            subject.athlete = Confident[Athlete](
                value=subject.athlete.value.model_copy(update={"club": correction.club or None}),
                confidence=1,
                source=Source.MANUAL,
            )

    @staticmethod
    def _set_discipline(photo, discipline, name_overrides=None):
        record = photo.analysis.record
        if not isinstance(record.event, AthleticsEvent):
            raise WorkflowError("This discipline editor supports athletics")
        record.event.discipline = (
            Confident[AthleticsDiscipline](
                value=discipline,
                confidence=1,
                source=Source.MANUAL,
                note="discipline selected in review",
            )
            if discipline is not None
            else None
        )
        record.event.custom_kind = record.event.custom_label = None
        photo.proposal = record.description = build_description(record, name_overrides=name_overrides)
        if not photo.caption_edited:
            photo.caption = photo.proposal

    def _discipline_changes(self, batch, request, caption_names_revision=None, name_overrides=None):
        ids = [selection.photo_id for selection in request.photos]
        if len(set(ids)) != len(ids):
            raise WorkflowError("Select each photo only once")
        changes, updated = [], []
        for selection in request.photos:
            photo = batch.photo(selection.photo_id)
            if photo.revision != selection.revision:
                raise Conflict("A selected photo changed; reload and preview the discipline changes again")
            if photo.analysis is None:
                raise Conflict("Analyze all selected photos before assigning a discipline")
            after = photo.model_copy(deep=True)
            self._set_discipline(after, request.discipline, name_overrides)
            before = photo.analysis.record.event.discipline
            changed = after != photo
            changes.append(
                DisciplineChange(
                    photo_id=photo.id,
                    revision=photo.revision,
                    display_name=photo.display_name,
                    before_discipline=before.value if before else None,
                    manual_discipline=bool(before and before.source is Source.MANUAL),
                    before_caption=photo.caption,
                    after_caption=after.caption,
                    caption_preserved=photo.caption_edited,
                    changed=changed,
                )
            )
            if changed:
                after.changed()
            updated.append(after)
        return DisciplinePreview(
            discipline=request.discipline, photos=changes, caption_names_revision=caption_names_revision
        ), updated

    def preview_discipline(self, owner_id, batch_id, request):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            revision, names = caption_overrides(
                self.store, owner_id, session=session, expected_revision=request.caption_names_revision
            )
            preview, _ = self._discipline_changes(batch, request, revision, names)
            return preview

    def assign_discipline(self, owner_id, batch_id, request):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            revision, names = caption_overrides(
                self.store, owner_id, session=session, expected_revision=request.caption_names_revision
            )
            _, updated = self._discipline_changes(batch, request, revision, names)
            by_id = {photo.id: photo for photo in updated}
            batch.photos = [by_id.get(photo.id, photo) for photo in batch.photos]
            self.store.save(session, batch)
            return updated

    def approve_photo(self, owner_id, batch_id, photo_id, revision):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != revision:
                raise Conflict("This photo changed since it was opened; reload before approving")
            if not photo.can_approve:
                raise Conflict("Approval requires an analyzed photo, a nonblank caption, and replacement consent")
            photo.conflicts_resolved = True
            photo.approved_revision = photo.revision
            self.store.save(session, batch)
            return photo

    def approve(self, owner_id, batch_id, selected):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            for selection in selected:
                photo = batch.photo(selection.photo_id)
                if photo.revision != selection.revision:
                    raise Conflict("Selected caption changed; reload before approving")
                if not photo.eligible:
                    raise Conflict("Only nonblank, resolved captions with explicit replacement consent can be approved")
                photo.approved_revision = photo.revision
            self.store.save(session, batch)

    def unapprove(self, owner_id, batch_id, photo_id, revision):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != revision:
                raise Conflict("This photo changed since it was opened; reload before removing approval")
            photo.approved_revision = None
            self.store.save(session, batch)
            return photo

    def finish(self, owner_id, batch_id):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            self.store.save(session, batch)
            self.sessions.finish(owner_id, batch_id)

    @staticmethod
    def _assign_face_name(photo, subject_index, athlete, name_overrides=None):
        record = photo.analysis.record
        record.subjects[subject_index].athlete = Confident[Athlete](
            value=athlete.model_copy(deep=True),
            confidence=1,
            source=Source.MANUAL,
            note="Name confirmed from a matching face in this batch",
        )
        record.subjects[subject_index].identity_edited = True
        Services._regenerate_subject_caption(photo, name_overrides)

    @staticmethod
    def _regenerate_subject_caption(photo, name_overrides=None):
        record = photo.analysis.record
        if record.event.discipline is not None and record.event.discipline.source is not Source.MANUAL:
            record.event = get(record.sport).new_event()
        record.event = get(record.sport).resolve(
            record.event, [subject for subject in record.subjects if not subject.excluded_from_caption]
        )
        photo.proposal = record.description = build_description(record, name_overrides=name_overrides)
        if not photo.caption_edited:
            photo.caption = photo.proposal

    @staticmethod
    def _propagation_bibs(subject, roster):
        trusted = trusted_bib_values(subject.bibs, roster)
        strong = {bib.value for bib in subject.bibs if bib.confidence >= STRONG_BIB_CONFIDENCE}
        warnings = [
            f"Bib read {value} is not in the saved roster; it will remain as uncertain evidence."
            for value in sorted(strong - trusted)
        ]
        return strong & trusted, warnings

    def _propagation_preview(self, batch, request, caption_names_revision=None, name_overrides=None):
        data = self.sessions.get(batch.album.owner_id, batch.album.id)
        source = batch.photo(request.source.photo_id)
        if source.revision != request.source.revision:
            raise Conflict("Source photo changed; save and reopen matching faces")
        if data["session_id"] != request.face_session_id or not data["available"]:
            raise Conflict("Face session expired; saved names and captions are unchanged")
        problem = propagation_problem(data)
        if problem:
            raise Conflict(problem)
        source_face = next(
            (face for face in data["photos"].get(str(source.id), []) if face["subject"] == request.source.subject),
            None,
        )
        if (
            source_face is None
            or source.analysis is None
            or request.source.subject >= len(source.analysis.record.subjects)
        ):
            raise Conflict("Selected face is unavailable")
        identity = source.analysis.record.subjects[request.source.subject].athlete
        if identity is None or identity.source is not Source.MANUAL:
            raise Conflict("Save a name or roster assignment for this face before finding matches")
        source_bibs, source_warnings = self._propagation_bibs(
            source.analysis.record.subjects[request.source.subject], batch.roster
        )
        if len(source_bibs) > 1 or (identity.value.bib and source_bibs and identity.value.bib not in source_bibs):
            raise Conflict("Resolve conflicting bib and name evidence in the source photo before propagating")
        expected_bib = identity.value.bib or next(iter(source_bibs), None)
        candidates = []
        group = source_face.get("group")
        for photo in batch.photos:
            seen = set()
            for face in data["photos"].get(str(photo.id), []):
                index = face["subject"]
                if not group or face.get("group") != group or index in seen or photo.id == source.id:
                    continue
                seen.add(index)
                if photo.analysis is None or not 0 <= index < len(photo.analysis.record.subjects):
                    continue
                subject = photo.analysis.record.subjects[index]
                target_bibs, warnings = self._propagation_bibs(subject, batch.roster)
                requires_bib_confirmation = bool(warnings)
                replaces_tentative_name = False
                reason = None
                state = "eligible"
                if subject.athlete is not None and subject.athlete.value == identity.value:
                    reason = "This name is already assigned"
                    state = "already_named"
                elif (
                    subject.identity_edited
                    or (subject.athlete and subject.athlete.source is Source.MANUAL)
                    or any(bib.source is Source.MANUAL for bib in subject.bibs)
                ):
                    reason = "Manual identity or bib correction; review individually"
                elif len(target_bibs) > 1 or any(
                    bib.note
                    and bib.note.startswith("ambiguous")
                    and bib.value in trusted_bib_values(subject.bibs, batch.roster)
                    for bib in subject.bibs
                ):
                    reason = "Conflicting bib evidence; review individually"
                elif expected_bib and target_bibs and expected_bib not in target_bibs:
                    reason = "Bib differs from the selected person; review individually"
                elif photo.analysis.record.status is Status.FAILED:
                    reason = "Photo analysis failed; review individually"
                elif subject.athlete is not None:
                    if subject.athlete.source is Source.ROSTER and subject.athlete.confidence < ATHLETE_AUTO:
                        replaces_tentative_name = True
                        warnings.append(
                            f'Tentative name "{subject.athlete.value.name}" '
                            f"({subject.athlete.confidence:.0%} confidence) "
                            f'will be replaced by "{identity.value.name}".'
                        )
                    else:
                        reason = "Different athlete already matched; review individually"
                if reason and state != "already_named":
                    state = "blocked"
                proposed = photo.model_copy(deep=True)
                if reason is None:
                    self._assign_face_name(proposed, index, identity.value, name_overrides)
                candidates.append(
                    PropagationCandidate(
                        target=FaceTarget(photo_id=photo.id, revision=photo.revision, subject=index),
                        display_name=photo.display_name,
                        box=face["box"],
                        current_name=subject.athlete.value.name if subject.athlete else None,
                        before_caption=photo.caption,
                        proposed_caption=proposed.caption,
                        caption_preserved=photo.caption_edited,
                        reason=reason,
                        state=state,
                        requires_bib_confirmation=requires_bib_confirmation,
                        replaces_tentative_name=replaces_tentative_name,
                        warnings=warnings,
                    )
                )
        return PropagationPreview(
            source=request.source,
            face_session_id=request.face_session_id,
            athlete_name=identity.value.name,
            candidates=candidates,
            expires_at=data["expires_at"],
            warnings=[f"Source photo: {warning}" for warning in source_warnings],
            caption_names_revision=caption_names_revision,
        )

    def preview_propagation(self, owner_id, batch_id, request):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            revision, names = caption_overrides(
                self.store, owner_id, session=session, expected_revision=request.caption_names_revision
            )
            return self._propagation_preview(batch, request, revision, names)

    def propagate(self, owner_id, batch_id, request):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            revision, names = caption_overrides(
                self.store, owner_id, session=session, expected_revision=request.caption_names_revision
            )
            preview = self._propagation_preview(batch, request, revision, names)
            candidates = {(c.target.photo_id, c.target.subject): c for c in preview.candidates}
            keys = [(target.photo_id, target.subject) for target in request.targets]
            if len(set(keys)) != len(keys):
                raise WorkflowError("Select each matching face only once")
            for target in request.targets:
                candidate = candidates.get((target.photo_id, target.subject))
                if candidate is None or candidate.state != "eligible" or candidate.target.revision != target.revision:
                    raise Conflict("A selected match changed or needs individual review; reopen matching faces")
            if (
                preview.warnings or any(candidates[key].requires_bib_confirmation for key in keys)
            ) and not request.acknowledge_unsupported_bibs:
                raise Conflict("Confirm the unsupported bib reads before assigning names to the selected faces")
            if any(candidates[key].replaces_tentative_name for key in keys) and not request.acknowledge_tentative_names:
                raise Conflict("Confirm replacement of the tentative names before assigning the selected name")
            athlete = (
                batch.photo(request.source.photo_id).analysis.record.subjects[request.source.subject].athlete.value
            )
            changed = {}
            before = {}
            for target in request.targets:
                photo = batch.photo(target.photo_id)
                before.setdefault(photo.id, photo.model_dump(mode="json"))
                self._assign_face_name(photo, target.subject, athlete, names)
                photo.conflicts_resolved = False
                changed[photo.id] = photo
            for photo in changed.values():
                photo.changed()
            self.sessions.remember(
                owner_id,
                batch_id,
                request.face_session_id,
                [
                    {"photo_id": str(photo.id), "revision": photo.revision, "before": before[photo.id]}
                    for photo in changed.values()
                ],
            )
            self.store.save(session, batch)
            return list(changed.values())

    def undo_propagation(self, owner_id, batch_id, request):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            changes = self.sessions.undo(owner_id, batch_id, request.face_session_id, request.undo_id)
            restored = {}
            for change in changes:
                current = batch.photo(UUID(change["photo_id"]))
                if current.revision != change["revision"]:
                    raise Conflict("A photo changed after propagation; correct it individually instead of undoing")
                previous = Photo.model_validate(change["before"])
                if previous.current_description != current.current_description:
                    previous.replace_existing = False
                previous.current_description = current.current_description
                previous.revision = current.revision
                previous.changed()
                restored[previous.id] = previous
            batch.photos = [restored.get(photo.id, photo) for photo in batch.photos]
            self.sessions.undo(owner_id, batch_id, request.face_session_id, request.undo_id, consume=True)
            self.store.save(session, batch)
            return list(restored.values())

    @staticmethod
    def merge_analysis(batch: Batch, results: dict[UUID, AnalysisDocument], name_overrides=None):
        retained = set()
        for photo in batch.photos:
            result = results[photo.id]
            result.record.source_path = None
            previous = photo.analysis.record if photo.analysis else None
            if previous is not None:
                # Keep records with manual identity or discipline decisions. Fresh
                # detections cannot be mapped reliably to the old subject indexes.
                has_manual = any(
                    s.identity_edited
                    or s.excluded_from_caption
                    or (s.athlete and s.athlete.source is Source.MANUAL)
                    or any(b.source is Source.MANUAL for b in s.bibs)
                    for s in previous.subjects
                ) or (getattr(previous.event, "discipline", None) and previous.event.discipline.source is Source.MANUAL)
                if has_manual:
                    result = AnalysisDocument(record=previous.model_copy(deep=True))
                    retained.add(photo.id)
            photo.analysis = result
            if name_overrides is not None:
                result.record.description = build_description(result.record, name_overrides=name_overrides)
            photo.proposal = result.record.description
            if not photo.caption_edited:
                photo.caption = photo.proposal
            photo.conflicts_resolved = False
            # Rerunning invalidates approval even when the caption is unchanged.
            photo.changed()
        return retained

    def preview(self, owner_id, batch_id):
        batch = self.store.get(owner_id, batch_id)
        return [
            {
                "photo_id": p.id,
                "revision": p.revision,
                "display_name": p.display_name,
                "change": DescriptionWrite(
                    destination=p.destination, expected=p.current_description, replacement=p.caption
                ),
            }
            for p in batch.photos
            if p.destination is not None and p.approved and p.eligible
        ]

    def apply(self, owner_id, batch_id, selections):
        gallery = self._gallery()
        results = []
        # Commit the intended change before writing to the gallery so retries
        # can reconcile an interrupted write. The second transaction rechecks
        # approval and holds the lock through the write and outcome save.
        for selection in selections:
            with self.store.transaction(owner_id) as session:
                batch = self.store.load(session, owner_id, batch_id, lock=True)
                self.store.require_idle(session, owner_id, batch_id)
                photo = batch.photo(selection.photo_id)
                if photo.revision != selection.revision or not photo.approved or not photo.eligible:
                    raise Conflict("Caption changed or is not approved/eligible; review before applying")
                if photo.destination is None:
                    raise Conflict("Uploaded photo has no gallery destination")
                history = self.store.publications(session, owner_id, batch_id)
                pending = next(
                    (
                        p
                        for p in reversed(history)
                        if p.photo_id == photo.id and p.revision == photo.revision and not p.restored
                    ),
                    None,
                )
                operation = pending or Publication(
                    owner_id=owner_id,
                    batch_id=batch_id,
                    photo_id=photo.id,
                    revision=photo.revision,
                    change=DescriptionWrite(
                        destination=photo.destination, expected=photo.current_description, replacement=photo.caption
                    ),
                )
                self.store.save_publication(session, operation)
            with self.store.transaction(owner_id) as session:
                batch = self.store.load(session, owner_id, batch_id, lock=True)
                self.store.require_idle(session, owner_id, batch_id)
                photo = batch.photo(selection.photo_id)
                if photo.revision != selection.revision or not photo.approved:
                    raise Conflict("Caption changed before the gallery write")
                result = gallery.write(operation.change)
                operation.result = result
                if result.state in (WriteState.APPLIED, WriteState.UNCHANGED):
                    photo.current_description = operation.change.replacement
                self.store.save_publication(session, operation)
                self.store.save(session, batch)
                results.append(operation)
        return results

    def reconcile(self, owner_id, batch_id, operation_id):
        gallery = self._gallery()
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            operation = next(
                (p for p in self.store.publications(session, owner_id, batch_id) if p.id == operation_id), None
            )
            if operation is None or operation.restored:
                raise Conflict("Publishing operation is unavailable or was already restored")
            result = gallery.inspect(operation.change)
            operation.result = result
            self.store.save_publication(session, operation)
            if result.state is WriteState.UNCHANGED:
                photo = batch.photo(operation.photo_id)
                if photo.current_description != result.live_value:
                    photo.current_description = result.live_value
                    photo.changed()
                self.store.save(session, batch)
            return operation

    def refresh_description(self, owner_id, batch_id, photo_id, revision):
        gallery = self._gallery()
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != revision or photo.destination is None:
                raise Conflict("Photo changed or has no gallery destination; reload before refreshing")
            result = gallery.inspect(
                DescriptionWrite(
                    destination=photo.destination, expected=photo.current_description, replacement=photo.caption
                )
            )
            if result.state is WriteState.FAILURE:
                raise WorkflowError(result.error or "Gallery description could not be read")
            photo.current_description = result.live_value
            photo.replace_existing = False
            photo.changed()
            self.store.save(session, batch)
            return photo

    def restore(self, owner_id, batch_id, operation_id):
        gallery = self._gallery()
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            operation = next(
                (p for p in self.store.publications(session, owner_id, batch_id) if p.id == operation_id), None
            )
            if operation is None or operation.result.state not in (WriteState.APPLIED, WriteState.UNCHANGED):
                raise Conflict("Only a completed publishing operation can be restored")
            if operation.restored:
                return WriteResult(state=WriteState.UNCHANGED, live_value=operation.change.expected)
            result = gallery.write(
                DescriptionWrite(
                    destination=operation.change.destination,
                    expected=operation.change.replacement,
                    replacement=operation.change.expected,
                )
            )
            if result.state in (WriteState.APPLIED, WriteState.UNCHANGED):
                operation.restored = True
                photo = batch.photo(operation.photo_id)
                photo.current_description = operation.change.expected
                photo.changed()
                self.store.save_publication(session, operation)
                self.store.save(session, batch)
            return result
