"""Transactional batch storage and a leased Postgres job queue."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, delete, func, or_, select, text
from sqlalchemy.orm import Session

from startnummer.adapters.db.schema import (
    BatchRow,
    BlobGarbageRow,
    InstanceRow,
    JobRow,
    PhotoRow,
    PublicationRow,
    SettingsRow,
)
from startnummer.core.batch import Batch, Conflict, Job, JobState, Missing, Photo, Publication, now
from startnummer.core.enums import Status


class Store:
    def __init__(self, engine: Engine):
        self.engine = engine

    def runtime_settings(self, owner_id, *, session=None):
        if session is None:
            with self.transaction() as current:
                return self.runtime_settings(owner_id, session=current)
        row = session.get(SettingsRow, owner_id)
        return (row.revision, row.document) if row else (0, {})

    def save_settings(self, owner_id, revision, document):
        with self.transaction(owner_id) as session:
            current, _ = self.runtime_settings(owner_id, session=session)
            if current != revision:
                raise Conflict("Settings changed; refresh before saving again")
            row = session.get(SettingsRow, owner_id)
            if row is None:
                row = SettingsRow(owner_id=owner_id)
                session.add(row)
            row.revision, row.document = current + 1, document
            return row.revision

    def installation_settings(self, fallback_owner_id, *, session=None):
        if session is None:
            with self.transaction() as current:
                return self.installation_settings(fallback_owner_id, session=current)
        instance = session.get(InstanceRow, 1)
        owner = instance.admin_owner_id if instance and instance.admin_owner_id else fallback_owner_id
        return self.runtime_settings(owner, session=session)

    @contextmanager
    def transaction(self, owner_id: UUID | None = None) -> Iterator[Session]:
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            # One photographer's imports and cleanup must agree about shared
            # blobs. Transaction-scoped locking also serializes concurrent edits.
            if owner_id is not None and self.engine.dialect.name == "postgresql":
                key = int.from_bytes(owner_id.bytes[:8], "big", signed=True)
                session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
            yield session

    def load(self, session: Session, owner_id: UUID, batch_id: UUID, *, lock: bool = False) -> Batch:
        statement = select(BatchRow).where(BatchRow.id == batch_id, BatchRow.owner_id == owner_id)
        if lock:
            statement = statement.with_for_update()
        row = session.scalar(statement)
        if row is None:
            raise Missing("Batch not found")
        photos = session.scalars(
            select(PhotoRow)
            .where(PhotoRow.batch_id == batch_id, PhotoRow.owner_id == owner_id)
            .order_by(PhotoRow.ordinal)
        )
        return Batch.model_validate({**row.document, "photos": [p.document for p in photos]})

    def save(self, session: Session, batch: Batch) -> None:
        owner = batch.album.owner_id
        batch.updated_at = now()
        row = session.get(BatchRow, batch.album.id)
        if row is not None and row.owner_id != owner:
            raise Missing("Batch not found")
        if row is None:
            row = BatchRow(id=batch.album.id, owner_id=owner, created_at=batch.created_at)
            session.add(row)
        row.updated_at = batch.updated_at
        row.document = batch.model_dump(mode="json", exclude={"photos"})
        session.flush()
        for ordinal, photo in enumerate(batch.photos):
            if photo.analysis is not None:
                record = photo.analysis.record
                if record.owner_id != owner or record.album_id != batch.album.id:
                    raise Conflict("Analysis does not belong to this batch")
                if record.source_path is not None:
                    raise Conflict("Staging paths cannot be saved as image references")
            stored = session.get(PhotoRow, photo.id)
            if stored is not None and (stored.owner_id != owner or stored.batch_id != batch.album.id):
                raise Conflict("Photo identity belongs to a different batch")
            if stored is None:
                stored = PhotoRow(id=photo.id, batch_id=batch.album.id, owner_id=owner)
                session.add(stored)
            stored.ordinal = ordinal
            stored.blob_key = photo.blob_key
            stored.content_hash = photo.content_hash
            stored.status = photo.analysis.record.status if photo.analysis else Status.PENDING
            stored.document = photo.model_dump(mode="json")

    def list_batches(self, owner_id: UUID) -> list[dict]:
        with self.transaction() as session:
            rows = session.scalars(
                select(BatchRow).where(BatchRow.owner_id == owner_id).order_by(BatchRow.updated_at.desc())
            )
            return [
                {
                    "id": row.id,
                    "name": row.document["album"]["name"],
                    "updated_at": row.updated_at,
                    "photo_count": session.scalar(
                        select(func.count())
                        .select_from(PhotoRow)
                        .where(PhotoRow.batch_id == row.id, PhotoRow.owner_id == owner_id)
                    ),
                }
                for row in rows
            ]

    def get(self, owner_id: UUID, batch_id: UUID) -> Batch:
        with self.transaction(owner_id) as session:
            return self.load(session, owner_id, batch_id)

    def referenced(self, session: Session, owner_id: UUID, key: str) -> bool:
        return bool(
            session.scalar(
                select(func.count())
                .select_from(PhotoRow)
                .where(PhotoRow.owner_id == owner_id, PhotoRow.blob_key == key)
            )
        )

    def schedule_cleanup(self, session, owner_id, keys):
        for key in keys:
            if session.get(BlobGarbageRow, (owner_id, key)) is None:
                session.add(BlobGarbageRow(owner_id=owner_id, blob_key=key))

    def cleanup(self, owner_id, delete_blob):
        with self.transaction(owner_id) as session:
            garbage = session.scalars(select(BlobGarbageRow).where(BlobGarbageRow.owner_id == owner_id)).all()
            for row in garbage:
                if not self.referenced(session, owner_id, row.blob_key):
                    delete_blob(row.blob_key)
                session.delete(row)

    def require_idle(self, session, owner_id, batch_id):
        active = session.scalar(
            select(JobRow.id)
            .where(
                JobRow.owner_id == owner_id,
                JobRow.batch_id == batch_id,
                JobRow.state.in_([JobState.RUNNING, JobState.QUEUED]),
            )
            .limit(1)
        )
        if active is not None:
            raise Conflict("Wait for analysis to finish before changing review state")

    def delete_batch(self, session: Session, owner_id: UUID, batch_id: UUID) -> list[str]:
        batch = self.load(session, owner_id, batch_id, lock=True)
        for table in (PublicationRow, JobRow, PhotoRow):
            session.execute(delete(table).where(table.owner_id == owner_id, table.batch_id == batch_id))
        session.execute(delete(BatchRow).where(BatchRow.owner_id == owner_id, BatchRow.id == batch_id))
        session.flush()
        return [key for key in {p.blob_key for p in batch.photos} if not self.referenced(session, owner_id, key)]

    def photo(self, owner_id: UUID, photo_id: UUID) -> Photo:
        with self.transaction() as session:
            row = session.scalar(select(PhotoRow).where(PhotoRow.id == photo_id, PhotoRow.owner_id == owner_id))
            if row is None:
                raise Missing("Photo not found")
            return Photo.model_validate(row.document)

    def enqueue(self, owner_id: UUID, batch_id: UUID, before_queue=None) -> Job:
        with self.transaction(owner_id) as session:
            batch = self.load(session, owner_id, batch_id, lock=True)
            pending = session.scalar(
                select(JobRow).where(
                    JobRow.batch_id == batch_id,
                    JobRow.owner_id == owner_id,
                    JobRow.state.in_([JobState.QUEUED, JobState.RUNNING]),
                )
            )
            if pending is not None:
                raise Conflict("Analysis is already queued or running")
            if before_queue is not None:
                before_queue()
            for photo in batch.photos:
                photo.changed()
            self.save(session, batch)
            job = Job(owner_id=owner_id, batch_id=batch_id, total=len(batch.photos))
            session.add(JobRow(**job.model_dump()))
            return job

    def cancel(self, session: Session, owner_id: UUID, batch_id: UUID) -> None:
        rows = session.scalars(
            select(JobRow)
            .where(
                JobRow.owner_id == owner_id,
                JobRow.batch_id == batch_id,
                JobRow.state.in_([JobState.QUEUED, JobState.RUNNING]),
            )
            .with_for_update()
        )
        for row in rows:
            row.state, row.phase = JobState.CANCELLED, "cancelled"
            row.lease_token = row.lease_until = None

    def jobs(self, owner_id: UUID, batch_id: UUID, *, session: Session | None = None) -> list[Job]:
        if session is None:
            with self.transaction(owner_id) as current:
                return self.jobs(owner_id, batch_id, session=current)
        self.load(session, owner_id, batch_id)
        return [
            self._job(row)
            for row in session.scalars(
                select(JobRow)
                .where(JobRow.owner_id == owner_id, JobRow.batch_id == batch_id)
                .order_by(JobRow.created_at.desc())
            )
        ]

    @staticmethod
    def _job(row: JobRow) -> Job:
        return Job.model_validate({field: getattr(row, field) for field in Job.model_fields})

    def claim(self, lease_seconds: int = 90) -> Job | None:
        with self.transaction() as session:
            expired = and_(JobRow.state == JobState.RUNNING, JobRow.lease_until < now())
            exhausted = session.scalars(
                select(JobRow).where(expired, JobRow.attempts >= JobRow.max_attempts).with_for_update(skip_locked=True)
            )
            for row in exhausted:
                row.state, row.error, row.phase = JobState.FAILED, "Worker lease expired; retries exhausted", "failed"
            row = session.scalar(
                select(JobRow)
                .where(or_(JobRow.state == JobState.QUEUED, expired), JobRow.attempts < JobRow.max_attempts)
                .order_by(JobRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.state = JobState.RUNNING
            row.attempts += 1
            row.lease_token = uuid4()
            row.lease_until = now() + timedelta(seconds=lease_seconds)
            row.completed, row.phase, row.error = 0, "staging", None
            session.flush()
            return self._job(row)

    def heartbeat(self, job: Job, lease_seconds: int, completed: int, phase: str) -> bool:
        with self.transaction() as session:
            row = session.scalar(
                select(JobRow)
                .where(
                    JobRow.id == job.id,
                    JobRow.owner_id == job.owner_id,
                    JobRow.state == JobState.RUNNING,
                    JobRow.lease_token == job.lease_token,
                    JobRow.lease_until > now(),
                )
                .with_for_update()
            )
            if row is None:
                return False
            row.lease_until = now() + timedelta(seconds=lease_seconds)
            row.completed, row.phase = completed, phase
            return True

    def complete(self, job: Job, merge) -> None:
        with self.transaction(job.owner_id) as session:
            row = session.scalar(
                select(JobRow)
                .where(
                    JobRow.id == job.id,
                    JobRow.owner_id == job.owner_id,
                    JobRow.state == JobState.RUNNING,
                    JobRow.lease_token == job.lease_token,
                    JobRow.lease_until > now(),
                )
                .with_for_update()
            )
            if row is None:
                raise Conflict("Worker lease is no longer valid")
            batch = self.load(session, job.owner_id, job.batch_id, lock=True)
            merged = merge(batch)
            self.save(session, batch)
            row.state, row.phase, row.completed = JobState.DONE, "done", row.total
            row.lease_until = None
            return merged

    def fail(self, job: Job, error: str) -> None:
        with self.transaction() as session:
            row = session.scalar(
                select(JobRow)
                .where(
                    JobRow.id == job.id,
                    JobRow.owner_id == job.owner_id,
                    JobRow.state == JobState.RUNNING,
                    JobRow.lease_token == job.lease_token,
                )
                .with_for_update()
            )
            if row is not None:
                row.error = error[:500]
                row.state = JobState.QUEUED if row.attempts < row.max_attempts else JobState.FAILED
                row.phase = row.state
                row.lease_until = None

    def save_publication(self, session: Session, publication: Publication) -> None:
        row = session.get(PublicationRow, publication.id)
        if row is None:
            row = PublicationRow(
                id=publication.id,
                batch_id=publication.batch_id,
                owner_id=publication.owner_id,
                photo_id=publication.photo_id,
                revision=publication.revision,
            )
            session.add(row)
        row.document = publication.model_dump(mode="json")

    def publications(self, session: Session, owner_id: UUID, batch_id: UUID) -> list[Publication]:
        rows = session.scalars(
            select(PublicationRow).where(PublicationRow.owner_id == owner_id, PublicationRow.batch_id == batch_id)
        )
        return sorted([Publication.model_validate(row.document) for row in rows], key=lambda p: p.created_at)
