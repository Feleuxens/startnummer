"""End-to-end use cases with synthetic inputs and fake inference/gallery adapters."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.chevereto import RemotePhoto
from startnummer.adapters.db.schema import Base, JobRow, PhotoRow
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.api import create_app
from startnummer.app.contracts import Edit, Selection
from startnummer.app.services import InputPhoto, Services
from startnummer.app.settings import Settings
from startnummer.app.worker import Worker
from startnummer.core.batch import (
    AnalysisDocument,
    Conflict,
    DescriptionWrite,
    Destination,
    Missing,
    Publication,
    WriteResult,
    WriteState,
)
from startnummer.core.enums import Source, Status
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports.athletics import AthleticsEvent
from startnummer.core.types import BibRead, BoundingBox, FaceDetection, OcrResult, PersonDetection

HTML = b"""<html><div class="entryline">
<div></div><div>12</div><div></div><div>Example Alex</div><div>Example Club</div>
<div></div><div></div><div>2000</div><div><a>100</a></div>
</div></html>"""


def image_bytes():
    output = BytesIO()
    Image.new("RGB", (100, 200), "gray").save(output, format="JPEG")
    return output.getvalue()


class FakeGallery:
    def __init__(self):
        self.values = {1: None, 2: None}
        self.writes = []
        self.fail_once = False

    def album(self, url):
        return "Example album", [
            RemotePhoto(
                "same.jpg",
                f"http://gallery.test/images/{i}.jpg",
                Destination(instance="http://gallery.test", image_id=i, page_url=f"http://gallery.test/image/{i}"),
                self.values[i],
            )
            for i in (1, 2)
        ]

    def write(self, change: DescriptionWrite):
        self.writes.append(change)
        live = self.values[change.destination.image_id]
        if self.fail_once:
            self.fail_once = False
            return WriteResult(state=WriteState.FAILURE, error="temporary test failure")
        if live == change.replacement:
            return WriteResult(state=WriteState.UNCHANGED, live_value=live)
        if live != change.expected:
            return WriteResult(state=WriteState.CONFLICT, live_value=live)
        self.values[change.destination.image_id] = change.replacement
        return WriteResult(state=WriteState.APPLIED, live_value=change.replacement)


@pytest.fixture
def environment(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    store = Store(engine)
    owner = uuid4()
    settings = Settings(
        database_url="sqlite://",
        blob_root=tmp_path / "blobs",
        password="test-password",
        session_secret="s" * 32,
        worker_secret="w" * 32,
        owner_id=owner,
        chevereto_url="http://gallery.test",
        roster_hosts=("roster.test",),
    )
    sessions = FaceSessions()
    gallery = FakeGallery()
    fetched = []

    def fetch(url, *, roster=False):
        fetched.append((url, roster))
        return HTML if roster else image_bytes()

    service = Services(store, FilesystemBlobStore(settings.blob_root), settings, sessions, gallery, fetch)
    yield service, fetched
    engine.dispose()


def import_batch(service, *, gallery=False, roster_url=False, import_id=None):
    return service.import_batch(
        service.settings.owner_id,
        "Example batch",
        "Example Meet",
        [] if gallery else [InputPhoto("original.jpg", image_bytes())],
        "http://gallery.test/album/a" if gallery else None,
        None if roster_url else HTML,
        "https://roster.test/roster" if roster_url else None,
        import_id,
    )


def analyzed(service, *, gallery=True):
    batch = import_batch(service, gallery=gallery)
    for photo in batch.photos:
        record = AnalysisRecord(
            owner_id=batch.album.owner_id,
            album_id=batch.album.id,
            content_hash=photo.content_hash,
            event=AthleticsEvent(),
            status=Status.AUTO,
            description="Approved athlete caption",
        )
        photo.analysis = AnalysisDocument(record=record)
        photo.proposal = photo.caption = record.description
        photo.changed()
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    return batch


@pytest.mark.parametrize("gallery", [False, True])
@pytest.mark.parametrize("roster_url", [False, True])
def test_all_four_input_pairings(environment, gallery, roster_url):
    service, fetched = environment
    batch = import_batch(service, gallery=gallery, roster_url=roster_url)
    restored = service.store.get(service.settings.owner_id, batch.album.id)
    assert restored == batch
    assert len(batch.photos) == (2 if gallery else 1)
    assert batch.roster.athletes[0].name == "Alex Example"
    assert batch.roster.athletes[0].entered_events == ["100m"]
    assert bool([request for request in fetched if request[1]]) is roster_url
    assert all(bool(p.destination) is gallery for p in batch.photos)


def test_import_retry_has_same_photo_ids_and_does_not_refetch(environment):
    service, fetched = environment
    key = uuid4()
    first = import_batch(service, gallery=True, roster_url=True, import_id=key)
    requests = len(fetched)
    second = import_batch(service, gallery=True, roster_url=True, import_id=key)
    assert first == second
    assert len(fetched) == requests
    assert len(service.store.list_batches(service.settings.owner_id)) == 1


def test_duplicate_bytes_retain_independent_remote_ids_and_cleanup(environment):
    service, _ = environment
    first = import_batch(service, gallery=True)
    second = import_batch(service)
    a, b = first.photos
    assert a.id != b.id
    assert a.blob_key == b.blob_key == second.photos[0].blob_key
    assert a.destination.image_id != b.destination.image_id
    service.delete_batch(first.album.owner_id, first.album.id)
    assert Path(service.settings.blob_root / str(first.album.owner_id) / a.blob_key).exists()
    service.delete_batch(second.album.owner_id, second.album.id)
    assert not (service.settings.blob_root / str(first.album.owner_id)).exists()


def test_rejects_empty_roster_and_invalid_images_without_blobs(environment):
    service, _ = environment
    with pytest.raises(Exception, match="no supported entries"):
        service.import_batch(
            service.settings.owner_id, "", "", [InputPhoto("x.jpg", image_bytes())], None, b"<html></html>", None
        )
    with pytest.raises(Exception, match="valid supported image"):
        service.import_batch(
            service.settings.owner_id, "", "", [InputPhoto("x.jpg", b"not an image")], None, HTML, None
        )
    assert not service.settings.blob_root.exists()


def test_ownership_and_stale_edits(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    with pytest.raises(Missing):
        service.store.get(uuid4(), batch.album.id)
    service.edit(batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, caption="Human caption"))
    with pytest.raises(Conflict, match="changed"):
        service.edit(batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, caption="Stale"))


def test_approval_gates_and_changed_caption_revokes_approval(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    service.approve(batch.album.owner_id, batch.album.id, [Selection(photo_id=photo.id, revision=photo.revision)])
    assert service.store.get(batch.album.owner_id, batch.album.id).photos[0].approved
    saved = service.edit(batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, caption=""))
    assert not saved.approved
    with pytest.raises(Conflict, match="nonblank"):
        service.approve(batch.album.owner_id, batch.album.id, [Selection(photo_id=photo.id, revision=saved.revision)])


def test_unapprove_preserves_caption_evidence_other_photos_and_publishing(environment):
    service, _ = environment
    batch = analyzed(service)
    selected = [Selection(photo_id=p.id, revision=p.revision) for p in batch.photos]
    service.approve(batch.album.owner_id, batch.album.id, selected)
    service.apply(batch.album.owner_id, batch.album.id, selected)
    before = service.store.get(batch.album.owner_id, batch.album.id)
    photo = before.photos[0]
    writes = len(service.gallery.writes)
    result = service.unapprove(batch.album.owner_id, batch.album.id, photo.id, photo.revision)
    assert result.approved_revision is None
    assert result.model_dump(exclude={"approved_revision"}) == photo.model_dump(exclude={"approved_revision"})
    after = service.store.get(batch.album.owner_id, batch.album.id)
    assert after.photos[1] == before.photos[1]
    assert after.photos[1].approved
    assert not service.preview(batch.album.owner_id, batch.album.id)[0]["photo_id"] == photo.id
    assert len(service.gallery.writes) == writes
    assert service.gallery.values[1] == photo.caption
    with service.store.transaction() as db:
        assert len(service.store.publications(db, batch.album.owner_id, batch.album.id)) == 2
    assert service.unapprove(batch.album.owner_id, batch.album.id, photo.id, photo.revision) == result


def test_unapprove_checks_owner_revision_and_active_analysis(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    service.approve(batch.album.owner_id, batch.album.id, [Selection(photo_id=photo.id, revision=photo.revision)])
    with pytest.raises(Missing):
        service.unapprove(uuid4(), batch.album.id, photo.id, photo.revision)
    with pytest.raises(Conflict, match="changed"):
        service.unapprove(batch.album.owner_id, batch.album.id, photo.id, photo.revision + 1)
    assert service.store.get(batch.album.owner_id, batch.album.id).photos[0].approved
    service.store.enqueue(batch.album.owner_id, batch.album.id)
    with pytest.raises(Conflict, match="analysis to finish"):
        service.unapprove(batch.album.owner_id, batch.album.id, photo.id, photo.revision)


def test_existing_caption_and_unresolved_evidence_need_explicit_choices(environment):
    service, _ = environment
    service.gallery.values[1] = "Existing caption"
    batch = analyzed(service)
    photo = batch.photos[0]
    photo.analysis.record.status = Status.NEEDS_REVIEW
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    with pytest.raises(Conflict):
        service.approve(batch.album.owner_id, batch.album.id, [Selection(photo_id=photo.id, revision=photo.revision)])
    photo = service.edit(
        batch.album.owner_id,
        batch.album.id,
        photo.id,
        Edit(revision=photo.revision, replace_existing=True, conflicts_resolved=True),
    )
    service.approve(batch.album.owner_id, batch.album.id, [Selection(photo_id=photo.id, revision=photo.revision)])


def test_apply_retry_conflict_and_conditional_restore(environment):
    service, _ = environment
    batch = analyzed(service)
    photos = [Selection(photo_id=p.id, revision=p.revision) for p in batch.photos]
    service.approve(batch.album.owner_id, batch.album.id, photos)
    # No external write before explicit Apply.
    assert service.gallery.writes == []
    assert len(service.preview(batch.album.owner_id, batch.album.id)) == 2
    service.gallery.values[2] = "Someone else's edit"
    result = service.apply(batch.album.owner_id, batch.album.id, photos)
    assert [p.result.state for p in result] == [WriteState.APPLIED, WriteState.CONFLICT]
    assert service.gallery.values[2] == "Someone else's edit"
    repeated = service.apply(batch.album.owner_id, batch.album.id, photos[:1])
    assert repeated[0].id == result[0].id
    assert repeated[0].result.state == WriteState.UNCHANGED
    service.gallery.values[1] = "Later edit"
    assert service.restore(batch.album.owner_id, batch.album.id, result[0].id).state == WriteState.CONFLICT
    service.gallery.values[1] = result[0].change.replacement
    assert service.restore(batch.album.owner_id, batch.album.id, result[0].id).state == WriteState.APPLIED
    assert service.gallery.values[1] is None
    assert service.restore(batch.album.owner_id, batch.album.id, result[0].id).state == WriteState.UNCHANGED


def test_prepared_operation_reconciles_write_that_committed_before_crash(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    selected = [Selection(photo_id=photo.id, revision=photo.revision)]
    service.approve(batch.album.owner_id, batch.album.id, selected)
    operation = Publication(
        owner_id=batch.album.owner_id,
        batch_id=batch.album.id,
        photo_id=photo.id,
        revision=photo.revision,
        change=DescriptionWrite(destination=photo.destination, expected=None, replacement=photo.caption),
    )
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save_publication(db, operation)
    service.gallery.values[1] = photo.caption  # committed remotely, local outcome was never saved
    result = service.apply(batch.album.owner_id, batch.album.id, selected)
    assert result[0].id == operation.id
    assert result[0].result.state == WriteState.UNCHANGED


class Detector:
    def detect(self, path):
        return [PersonDetection(BoundingBox(0, 0, 100, 200))]


class Ocr:
    def read(self, path):
        return OcrResult([BibRead(BoundingBox(35, 90, 65, 120), "12", 0.96)], [])


class Faces:
    def detect(self, path):
        return [FaceDetection(BoundingBox(30, 10, 70, 50), [1.0, 0.0])]


def test_worker_save_name_finish_and_reopen_without_face_data(environment):
    service, _ = environment
    batch = import_batch(service)
    service.store.enqueue(batch.album.owner_id, batch.album.id)
    worker = Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces())
    assert worker.run_once()
    batch = service.store.get(batch.album.owner_id, batch.album.id)
    assert service.store.jobs(batch.album.owner_id, batch.album.id)[0].state == "done"
    photo = batch.photos[0]
    data = service.sessions.get(batch.album.owner_id, batch.album.id)
    assert data["available"]
    photo = service.edit(
        batch.album.owner_id,
        batch.album.id,
        photo.id,
        Edit(
            revision=photo.revision, subject=0, athlete_name="Someone Without a Bib", face_session_id=data["session_id"]
        ),
    )
    assert service.sessions.get(batch.album.owner_id, batch.album.id)["available"]
    service.finish(batch.album.owner_id, batch.album.id)
    restored = service.store.get(batch.album.owner_id, batch.album.id)
    assert not service.sessions.get(batch.album.owner_id, batch.album.id)["available"]
    assert "Someone Without a Bib" in restored.photos[0].caption
    assert restored.photos[0].analysis.record.subjects[0].athlete.source is Source.MANUAL
    serialized = restored.model_dump_json()
    assert "embedding" not in serialized and 'source_path":null' in serialized
    assert "face_box" not in serialized and "session_id" not in serialized
    # Expired face selections cannot be replayed against a reopened album.
    with pytest.raises(Conflict, match="expired"):
        service.edit(
            batch.album.owner_id,
            batch.album.id,
            photo.id,
            Edit(revision=photo.revision, subject=0, athlete_name="Stale Face", face_session_id=data["session_id"]),
        )


def test_worker_is_idempotent_and_preserves_manual_caption_on_rerun(environment):
    service, _ = environment
    batch = import_batch(service)
    worker = Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces())
    for _ in range(2):
        service.store.enqueue(batch.album.owner_id, batch.album.id)
        assert worker.run_once()
        photo = service.store.get(batch.album.owner_id, batch.album.id).photos[0]
        service.edit(
            batch.album.owner_id,
            batch.album.id,
            photo.id,
            Edit(revision=photo.revision, caption="Manually kept caption"),
        )
    with service.store.transaction() as db:
        assert len(db.scalars(select(PhotoRow)).all()) == 1
    assert service.store.get(batch.album.owner_id, batch.album.id).photos[0].caption == "Manually kept caption"


def test_expired_worker_retries_are_bounded(environment):
    from datetime import timedelta

    from startnummer.core.batch import now

    service, _ = environment
    batch = import_batch(service)
    service.store.enqueue(batch.album.owner_id, batch.album.id)
    original = service.store.claim()
    for attempt in range(3):
        with service.store.transaction() as db:
            row = db.get(JobRow, original.id)
            row.lease_until = now() - timedelta(seconds=1)
        current = service.store.claim()
        if attempt < 2:
            assert current.attempts == attempt + 2
        else:
            assert current is None
    assert not service.store.heartbeat(original, 90, 1, "stale")
    assert service.store.jobs(batch.album.owner_id, batch.album.id)[0].state == "failed"


def test_http_authentication_and_owner_rejection(environment):
    service, _ = environment
    app = create_app(
        service.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    with TestClient(app) as client:
        assert client.get("/api/batches").status_code == 401
        headers = {"X-Requested-With": "Startnummer"}
        assert (
            client.post(
                "/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers
            ).status_code
            == 200
        )
        assert client.get("/api/batches").status_code == 200
        assert client.get("/api/batches?owner_id=" + str(uuid4())).status_code == 400
        assert (
            client.post(
                "/api/session",
                json={"username": "photographer", "password": "test-password", "owner_id": str(uuid4())},
                headers=headers,
            ).status_code
            == 422
        )
        batch = import_batch(service)
        assert client.get("/api/photos/" + str(batch.photos[0].id)).headers["cache-control"] == "no-store, private"
        assert client.post(f"/api/batches/{batch.album.id}/analysis").status_code == 403


def test_unknown_analysis_schema_version_is_rejected(record):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AnalysisDocument.model_validate({"schema_version": 99, "record": record.model_dump()})


def test_import_commit_failure_cleans_unreferenced_bytes(environment):
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    service, _ = environment
    failed = False

    def fail_once(session):
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("simulated commit failure")

    event.listen(Session, "before_commit", fail_once)
    try:
        with pytest.raises(RuntimeError, match="commit failure"):
            import_batch(service)
    finally:
        event.remove(Session, "before_commit", fail_once)
    assert service.store.list_batches(service.settings.owner_id) == []
    assert not list(service.settings.blob_root.rglob("*.*"))


def test_failed_cleanup_is_durable_and_retryable(environment, monkeypatch):
    from startnummer.app.services import run

    service, _ = environment
    batch = import_batch(service)
    original_delete = service.blobs.delete

    async def failed_delete(owner, key):
        raise OSError("temporary filesystem failure")

    monkeypatch.setattr(service.blobs, "delete", failed_delete)
    with pytest.raises(OSError):
        service.delete_batch(batch.album.owner_id, batch.album.id)
    assert service.store.list_batches(batch.album.owner_id) == []
    monkeypatch.setattr(service.blobs, "delete", original_delete)
    service.store.cleanup(batch.album.owner_id, lambda key: run(service.blobs.delete(batch.album.owner_id, key)))
    assert not (service.settings.blob_root / str(batch.album.owner_id)).exists()


def test_face_session_expiry_discards_geometry():
    sessions = FaceSessions(ttl=0)
    owner, batch = uuid4(), uuid4()
    sessions.put(owner, batch, {"photo": [{"subject": 0, "box": [0, 0, 10, 10]}]})
    assert not sessions.get(owner, batch)["available"]
    assert sessions._items == {}


def test_review_cannot_change_or_apply_while_analysis_is_queued(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    selection = Selection(photo_id=photo.id, revision=photo.revision)
    service.approve(batch.album.owner_id, batch.album.id, [selection])
    service.store.enqueue(batch.album.owner_id, batch.album.id)
    with pytest.raises(Conflict, match="analysis to finish"):
        service.edit(batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, caption="new"))
    with pytest.raises(Conflict, match="analysis to finish"):
        service.finish(batch.album.owner_id, batch.album.id)
    with pytest.raises(Conflict, match="analysis to finish"):
        service.apply(batch.album.owner_id, batch.album.id, [selection])


def test_http_rejects_unknown_import_ownership_and_invalid_discipline(environment):
    service, _ = environment
    app = create_app(
        service.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    with TestClient(app) as client:
        headers = {"X-Requested-With": "Startnummer"}
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        response = client.post(
            "/api/batches",
            data={"owner_id": str(uuid4())},
            files={"roster_file": ("r.html", HTML, "text/html")},
            headers=headers,
        )
        assert response.status_code == 400
        batch = analyzed(service)
        response = client.patch(
            f"/api/batches/{batch.album.id}/photos/{batch.photos[0].id}",
            json={"revision": 1, "discipline": "invented"},
            headers=headers,
        )
        assert response.status_code == 422


def test_import_uses_oriented_dimensions_and_rejects_duplicate_bibs(environment):
    service, _ = environment
    output = BytesIO()
    image = Image.new("RGB", (20, 30))
    exif = Image.Exif()
    exif[274] = 6
    image.save(output, format="JPEG", exif=exif)
    batch = service.import_batch(
        service.settings.owner_id, "Rotated", "", [InputPhoto("rotated.jpg", output.getvalue())], None, HTML, None
    )
    assert (batch.photos[0].width, batch.photos[0].height) == (30, 20)
    with pytest.raises(Exception, match="duplicate bib"):
        service.import_batch(
            service.settings.owner_id,
            "Duplicate bibs",
            "",
            [InputPhoto("x.jpg", image_bytes())],
            None,
            HTML + HTML,
            None,
        )
