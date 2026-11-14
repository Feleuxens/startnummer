"""Recovery and lifecycle checks for saved batches."""

from datetime import timedelta
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from sqlalchemy import select

from startnummer.adapters.db.schema import JobRow
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.contracts import Edit, Selection
from startnummer.app.services import InputPhoto
from startnummer.app.worker import Worker
from startnummer.core.batch import Conflict, DescriptionWrite, Publication, WriteState, now
from tests.test_face_propagation import NoBibOcr
from tests.test_workflow import HTML, Detector, Faces, Ocr, analyzed, image_bytes, import_batch
from tests.test_workflow import environment as environment


def test_cancel_fences_running_worker_and_preserves_saved_review(environment):
    service, _ = environment
    batch = analyzed(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    service.analyze(owner, batch_id)
    lease = service.store.claim()
    service.cancel_analysis(owner, batch_id)
    assert not service.store.heartbeat(lease, 90, 1, "stale")
    with pytest.raises(Conflict, match="lease"):
        service.store.complete(lease, lambda batch: None)
    assert service.store.jobs(owner, batch_id)[0].state == "cancelled"
    assert service.store.get(owner, batch_id).photos[0].caption == batch.photos[0].caption
    assert not service.sessions.get(owner, batch_id)["available"]
    service.analyze(owner, batch_id)
    assert service.store.claim().id != lease.id


def test_stale_worker_cannot_discard_newer_session(environment, monkeypatch):
    service, _ = environment
    batch = import_batch(service)
    service.analyze(batch.album.owner_id, batch.album.id)
    worker = Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces())

    def stale_execute(job, progress, lost):
        service.sessions.put(job.owner_id, job.batch_id, {"new": []}, run_id="new-worker")
        raise Conflict("Lease lost")

    monkeypatch.setattr(worker, "_execute", stale_execute)
    worker.run_once()
    assert service.sessions.get(batch.album.owner_id, batch.album.id)["photos"] == {"new": []}


def test_expiry_clears_match_groups_and_worker_generation():
    sessions = FaceSessions(ttl=0)
    sessions.put(
        uuid4(),
        uuid4(),
        {"photo": [{"group": "private-group", "subject": 0, "box": [1, 2, 3, 4]}]},
        run_id="old-worker",
    )
    sessions.expire()
    assert sessions._items == {}


def test_rerun_revokes_approval_before_a_worker_claims_it(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    service.approve(batch.album.owner_id, batch.album.id, [Selection(photo_id=photo.id, revision=photo.revision)])
    service.analyze(batch.album.owner_id, batch.album.id)
    saved = service.store.get(batch.album.owner_id, batch.album.id)
    assert not saved.photos[0].approved
    assert saved.photos[0].revision > photo.revision


def test_ninety_three_photo_saved_workflow_with_worker_restart(environment):
    service, _ = environment
    roster = b"".join(HTML.replace(b"<div>12</div>", f"<div>{bib}</div>".encode()) for bib in range(100, 362))
    batch = service.import_batch(
        service.settings.owner_id,
        "Synthetic full album",
        "Meet",
        [InputPhoto(f"photo-{i}.jpg", image_bytes()) for i in range(93)],
        None,
        roster,
        None,
    )
    owner, batch_id = batch.album.owner_id, batch.album.id
    service.analyze(owner, batch_id)
    interrupted = service.store.claim()
    with service.store.transaction(owner) as db:
        db.get(JobRow, interrupted.id).lease_until = now() - timedelta(seconds=1)
    worker = Worker(service.store, service.blobs, FaceSessions(), Detector(), NoBibOcr(), Faces())
    assert worker.run_once()
    saved = service.store.get(owner, batch_id)
    assert len(saved.roster.athletes) == 262
    assert len(saved.photos) == 93 and len({p.id for p in saved.photos}) == 93
    job = service.store.jobs(owner, batch_id)[0]
    assert job.state == "done" and job.attempts == 2 and job.completed == 93
    service.sessions = worker.sessions
    edited = service.edit(
        owner,
        batch_id,
        saved.photos[0].id,
        Edit(revision=saved.photos[0].revision, caption="Saved after restart", conflicts_resolved=True),
    )
    service.approve(owner, batch_id, [Selection(photo_id=edited.id, revision=edited.revision)])
    service.finish(owner, batch_id)
    reopened = service.store.get(owner, batch_id)
    assert reopened.photos[0].approved and reopened.photos[0].caption == "Saved after restart"
    assert not service.sessions.get(owner, batch_id)["available"]
    with service.store.transaction() as db:
        assert len(db.scalars(select(JobRow)).all()) == 1


def test_interrupted_apply_reconciles_after_caption_changes_without_writing(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    operation = Publication(
        owner_id=batch.album.owner_id,
        batch_id=batch.album.id,
        photo_id=photo.id,
        revision=photo.revision,
        change=DescriptionWrite(destination=photo.destination, expected=None, replacement=photo.caption),
    )
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save_publication(db, operation)
    service.gallery.values[1] = photo.caption
    service.edit(batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, caption="New draft"))
    result = service.reconcile(batch.album.owner_id, batch.album.id, operation.id)
    assert result.result.state is WriteState.UNCHANGED
    assert service.gallery.writes == []
    assert service.store.get(batch.album.owner_id, batch.album.id).photos[0].caption == "New draft"
    assert service.restore(batch.album.owner_id, batch.album.id, operation.id).state is WriteState.APPLIED
    assert service.gallery.values[1] is None


def test_conflict_refresh_requires_renewed_review_and_replacement_consent(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    selected = Selection(photo_id=photo.id, revision=photo.revision)
    service.approve(batch.album.owner_id, batch.album.id, [selected])
    service.gallery.values[1] = "Changed in gallery"
    assert service.apply(batch.album.owner_id, batch.album.id, [selected])[0].result.state is WriteState.CONFLICT
    refreshed = service.refresh_description(batch.album.owner_id, batch.album.id, photo.id, photo.revision)
    assert refreshed.current_description == "Changed in gallery"
    assert not refreshed.approved and not refreshed.replace_existing and not refreshed.eligible
    assert service.gallery.values[1] == "Changed in gallery"


def test_private_worker_transport_keeps_match_groups_transient():
    import threading

    import httpx

    from startnummer.adapters.face.sessions import HttpFaceSessions
    from startnummer.app.worker import session_server

    sessions = FaceSessions()
    owner, batch_id, photo_id = uuid4(), uuid4(), uuid4()
    sessions.put(owner, batch_id, {str(photo_id): [{"subject": 0, "box": [1, 2, 3, 4], "group": "private-group"}]})
    server = session_server(sessions, "test-secret", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        assert httpx.get(f"{url}/sessions/{owner}/{batch_id}", trust_env=False).status_code == 401
        client = HttpFaceSessions(url, "test-secret")
        assert client.get(owner, batch_id)["photos"][str(photo_id)][0]["group"] == "private-group"
        session_id = client.get(owner, batch_id)["session_id"]
        client.validate(owner, batch_id, photo_id, 0, session_id)
        changes = [{"photo_id": str(photo_id), "revision": 2, "before": {"caption": "Before"}}]
        undo_id = client.remember(owner, batch_id, session_id, changes)
        assert client.get(owner, batch_id)["undo_count"] == 1
        assert "changes" not in client.get(owner, batch_id)
        assert client.undo(owner, batch_id, session_id, undo_id) == changes
        assert client.undo(owner, batch_id, session_id, undo_id, consume=True) == changes
        assert client.get(owner, batch_id)["undo_id"] is None
        assert not client.get(uuid4(), batch_id)["available"]
        client.finish(owner, batch_id)
        assert sessions._items == {}
        assert sessions._undo == {}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_import_stops_fetching_when_gallery_batch_limit_is_reached(environment):
    from dataclasses import replace

    service, fetched = environment
    service.settings = replace(service.settings, max_batch_bytes=1)
    with pytest.raises(Exception, match="Batch exceeds"):
        import_batch(service, gallery=True)
    assert len(fetched) == 1
    assert service.store.list_batches(service.settings.owner_id) == []
    assert not service.settings.blob_root.exists()


def test_finish_failure_is_reported_and_keeps_saved_work(environment, monkeypatch):
    service, _ = environment
    batch = analyzed(service)

    def unavailable(owner, batch_id):
        raise Conflict("Worker unavailable")

    monkeypatch.setattr(service.sessions, "finish", unavailable)
    with pytest.raises(Conflict, match="unavailable"):
        service.finish(batch.album.owner_id, batch.album.id)
    assert service.store.get(batch.album.owner_id, batch.album.id).photos[0].caption == batch.photos[0].caption
