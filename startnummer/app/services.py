"""Batch import, caption review, and publication use cases."""

import asyncio
import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from urllib.parse import urlparse
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError

from startnummer.adapters.db.store import Store
from startnummer.adapters.entrylist.ergebnisse_leichtathletik_de import LeichtathletikDeEntryListParser
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
from startnummer.core.entrytable import match_subject
from startnummer.core.enums import Source, Sport
from startnummer.core.models import Athlete, Confident
from startnummer.core.record import Album
from startnummer.core.sports import get
from startnummer.core.sports.athletics import AthleticsDiscipline, AthleticsEvent


@dataclass
class InputPhoto:
    name: str
    data: bytes
    destination: object = None
    description: str | None = None


def run(awaitable):
    """Run an async blob operation from synchronous code."""
    return asyncio.run(awaitable)


async def chunks(data):
    yield data


class Services:
    def __init__(self, store: Store, blobs, settings, sessions, gallery=None, fetch=None):
        self.store, self.blobs, self.settings = store, blobs, settings
        self.sessions, self.gallery = sessions, gallery
        self.fetch = fetch or self._fetch

    def _fetch(self, url: str, *, roster: bool = False) -> bytes:
        parsed = urlparse(url)
        if roster:
            allowed = parsed.scheme in ("http", "https") and parsed.hostname in self.settings.roster_hosts
            allowed = allowed and parsed.port in (None, 80, 443)
        else:
            configured = urlparse(self.settings.chevereto_url or "")
            allowed = (parsed.scheme, parsed.netloc) == (configured.scheme, configured.netloc)
        if not allowed or parsed.username or parsed.password:
            raise WorkflowError("URL is not a supported/configured source")
        limit = min(self.settings.max_file_bytes, 10 * 1024 * 1024) if roster else self.settings.max_file_bytes
        try:
            with httpx.stream("GET", url, follow_redirects=False, timeout=60, trust_env=False) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > limit:
                        raise WorkflowError("Source exceeds the configured size limit")
                return bytes(data)
        except httpx.HTTPError as exc:
            raise WorkflowError("Could not fetch the configured source; check its URL and access") from exc

    def import_batch(
        self, owner_id, name, meet_name, photos, gallery_url, roster_html, roster_url, import_id=None
    ) -> Batch:
        if import_id:
            try:
                return self.store.get(owner_id, import_id)
            except Missing:
                pass
        if bool(roster_html) == bool(roster_url):
            raise WorkflowError("Choose exactly one roster source: HTML upload or supported URL")
        if roster_url:
            roster_html = self.fetch(roster_url, roster=True)
        try:
            roster = LeichtathletikDeEntryListParser().parse_content(roster_html.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise WorkflowError("Roster must be supported Competitoroverview HTML") from exc
        if not roster.athletes:
            raise WorkflowError("The roster contains no supported entries")
        bibs = [athlete.bib for athlete in roster.athletes if athlete.bib]
        if len(set(bibs)) != len(bibs):
            raise WorkflowError("Roster contains duplicate bib numbers; correct the roster before analysis")
        if gallery_url:
            if photos:
                raise WorkflowError("Choose either gallery import or uploaded photos")
            if self.gallery is None:
                raise WorkflowError("No gallery is configured")
            album_name, remote = self.gallery.album(gallery_url)
            photos = [InputPhoto(p.name, self.fetch(p.source_url), p.destination, p.description) for p in remote]
            name = (name or "").strip() or album_name
        if not photos:
            raise WorkflowError("The batch contains no photos")
        if sum(len(p.data) for p in photos) > self.settings.max_batch_bytes:
            raise WorkflowError("Batch exceeds the configured size limit")
        # Reject invalid images before storing the batch or its bytes.
        checked = []
        for photo in photos:
            if len(photo.data) > self.settings.max_file_bytes:
                raise WorkflowError(f"Image exceeds the size limit: {PurePath(photo.name).name}")
            try:
                with Image.open(BytesIO(photo.data)) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"}:
                        raise WorkflowError("Supported photo formats are JPEG, PNG, and WebP")
                    width, height = image.size
                    if width * height > 50_000_000:
                        raise WorkflowError("Image dimensions exceed the supported limit")
                    mime = Image.MIME[image.format]
                    if image.getexif().get(274, 1) in {5, 6, 7, 8}:
                        width, height = height, width
                    image.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise WorkflowError("A selected file is not a valid supported image") from exc
            checked.append((photo, width, height, mime))
        album = Album(
            owner_id=owner_id,
            name=(name or "").strip() or "New batch",
            sport=Sport.ATHLETICS,
            meet_name=(meet_name or "").strip() or (roster.competition or "").strip() or None,
            roster_source=roster_url or "uploaded Competitoroverview HTML",
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
                for photo, width, height, mime in checked:
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

    def delete_batch(self, owner_id, batch_id):
        # Clear face data before deleting the batch. Abort if the worker is unavailable.
        self.store.get(owner_id, batch_id)
        self.sessions.finish(owner_id, batch_id)
        with self.store.transaction(owner_id) as session:
            keys = self.store.delete_batch(session, owner_id, batch_id)
            self.store.schedule_cleanup(session, owner_id, keys)
        self.store.cleanup(owner_id, lambda key: run(self.blobs.delete(owner_id, key)))

    def edit(self, owner_id, batch_id, photo_id, patch):
        with self.store.transaction(owner_id) as session:
            batch = self.store.load(session, owner_id, batch_id, lock=True)
            self.store.require_idle(session, owner_id, batch_id)
            photo = batch.photo(photo_id)
            if photo.revision != patch.revision:
                raise Conflict("This photo changed since it was opened; reload before saving")
            fields = patch.model_fields_set
            record = photo.analysis.record if photo.analysis else None
            if fields & {"bib", "athlete_name", "roster_bib", "discipline", "club"}:
                if record is None:
                    raise Conflict("Analyze the photo before correcting subjects or discipline")
                if "discipline" in fields:
                    if not isinstance(record.event, AthleticsEvent):
                        raise WorkflowError("This discipline editor supports athletics")
                    record.event.discipline = (
                        Confident[AthleticsDiscipline](
                            value=AthleticsDiscipline(patch.discipline),
                            confidence=1,
                            source=Source.MANUAL,
                            note="discipline selected in review",
                        )
                        if patch.discipline is not None
                        else None
                    )
                    record.event.custom_kind = record.event.custom_label = None
                if fields & {"bib", "athlete_name", "roster_bib", "club"}:
                    if patch.subject is None or not 0 <= patch.subject < len(record.subjects):
                        raise WorkflowError("Select a valid subject")
                    subject = record.subjects[patch.subject]
                    if patch.face_session_id is not None:
                        self.sessions.validate(owner_id, batch_id, photo_id, patch.subject, patch.face_session_id)
                    if "bib" in fields:
                        subject.bibs = (
                            [Confident[str](value=patch.bib, confidence=1, source=Source.MANUAL)] if patch.bib else []
                        )
                        subject.athlete = None
                        match_subject(subject, [], batch.roster)
                    if "roster_bib" in fields:
                        if not patch.roster_bib:
                            raise WorkflowError("Select a roster athlete")
                        athlete = batch.roster.by_bib(patch.roster_bib)
                        if athlete is None:
                            raise WorkflowError("Roster athlete not found")
                        subject.athlete = Confident[Athlete](value=athlete, confidence=1, source=Source.MANUAL)
                    elif "athlete_name" in fields:
                        if not patch.athlete_name or not patch.athlete_name.strip():
                            raise WorkflowError("Enter a name or select a roster athlete")
                        subject.athlete = Confident[Athlete](
                            value=Athlete(name=patch.athlete_name.strip(), club=patch.club or None),
                            confidence=1,
                            source=Source.MANUAL,
                        )
                    if "club" in fields and subject.athlete is not None:
                        subject.athlete = Confident[Athlete](
                            value=subject.athlete.value.model_copy(update={"club": patch.club or None}),
                            confidence=1,
                            source=Source.MANUAL,
                        )
                    # Re-resolve machine discipline from the corrected entries.
                    if record.event.discipline is not None and record.event.discipline.source is not Source.MANUAL:
                        record.event = get(record.sport).new_event()
                    record.event = get(record.sport).resolve(record.event, record.subjects)
                photo.proposal = record.description = build_description(record)
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
    def merge_analysis(batch: Batch, results: dict[UUID, AnalysisDocument]):
        retained = set()
        for photo in batch.photos:
            result = results[photo.id]
            result.record.source_path = None
            previous = photo.analysis.record if photo.analysis else None
            if previous is not None:
                # Keep records with manual identity or discipline decisions. Fresh
                # detections cannot be mapped reliably to the old subject indexes.
                has_manual = any(
                    (s.athlete and s.athlete.source is Source.MANUAL) or any(b.source is Source.MANUAL for b in s.bibs)
                    for s in previous.subjects
                ) or (getattr(previous.event, "discipline", None) and previous.event.discipline.source is Source.MANUAL)
                if has_manual:
                    result = AnalysisDocument(record=previous.model_copy(deep=True))
                    retained.add(photo.id)
            photo.analysis = result
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
        if self.gallery is None:
            raise WorkflowError("No gallery is configured")
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
                result = self.gallery.write(operation.change)
                operation.result = result
                if result.state in (WriteState.APPLIED, WriteState.UNCHANGED):
                    photo.current_description = operation.change.replacement
                self.store.save_publication(session, operation)
                self.store.save(session, batch)
                results.append(operation)
        return results

    def restore(self, owner_id, batch_id, operation_id):
        if self.gallery is None:
            raise WorkflowError("No gallery is configured")
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
            result = self.gallery.write(
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
