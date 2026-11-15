"""Revision-checked discipline review across a selected sequence of photos."""

from copy import deepcopy
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient

from startnummer.app.api import create_app
from startnummer.app.contracts import DisciplineAssignment, Edit, Selection
from startnummer.app.services import InputPhoto
from startnummer.app.worker import Worker
from startnummer.core.batch import Conflict, Missing, WorkflowError
from startnummer.core.enums import Source
from startnummer.core.sports.athletics import AthleticsDiscipline
from tests.test_workflow import HTML, Detector, Faces, Ocr, image_bytes
from tests.test_workflow import environment as environment


def prepare(service):
    batch = service.import_batch(
        service.settings.owner_id,
        "Discipline review",
        "Example Meet",
        [InputPhoto(f"original-{i}.jpg", image_bytes()) for i in range(4)],
        None,
        HTML,
        None,
    )
    owner, batch_id = batch.album.owner_id, batch.album.id
    batch.roster.athletes[0].entered_events = ["100m", "long_jump"]
    with service.store.transaction(owner) as db:
        service.store.save(db, batch)
    service.analyze(owner, batch_id)
    Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces()).run_once()
    return service.store.get(owner, batch_id)


def assignment(photos, discipline="high_jump"):
    return DisciplineAssignment(
        photos=[Selection(photo_id=photo.id, revision=photo.revision) for photo in photos], discipline=discipline
    )


def test_preview_and_apply_preserve_captions_identities_sessions_and_unselected_photos(environment):
    service, _ = environment
    batch = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    photo = batch.photos[1]
    service.edit(owner, batch_id, photo.id, Edit(revision=photo.revision, caption="Photographer's caption"))
    batch = service.store.get(owner, batch_id)
    service.approve(owner, batch_id, assignment(batch.photos).photos)
    before = service.store.get(owner, batch_id)
    sessions = deepcopy(service.sessions.get(owner, batch_id))
    request = assignment(before.photos[:3])  # high jump is absent from the roster
    preview = service.preview_discipline(owner, batch_id, request)
    assert service.store.get(owner, batch_id) == before
    assert preview.photos[1].caption_preserved
    assert preview.photos[1].after_caption == "Photographer's caption"
    assert "Hochsprung" in preview.photos[0].after_caption
    assert "High jump" in preview.photos[0].after_caption
    assert all(photo.before_discipline is None for photo in preview.photos)
    updated = service.assign_discipline(owner, batch_id, request)
    after = service.store.get(owner, batch_id)
    for old, new, change in zip(before.photos[:3], updated, preview.photos, strict=True):
        assert new.caption == change.after_caption
        assert new.analysis.record.description == new.proposal
        assert new.analysis.record.subjects == old.analysis.record.subjects
        assert new.revision == old.revision + 1
        assert not new.approved
        assert new.analysis.record.event.discipline.value is AthleticsDiscipline.HIGH_JUMP
        assert new.analysis.record.event.discipline.source is Source.MANUAL
    assert after.photos[3] == before.photos[3]
    assert after.photos[3].approved
    current = service.sessions.get(owner, batch_id)
    assert current.pop("expires_at") == pytest.approx(sessions.pop("expires_at"))
    assert current == sessions
    assert service.gallery.writes == []


def test_no_event_is_manual_and_same_assignment_keeps_approval(environment):
    service, _ = environment
    batch = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    updated = service.assign_discipline(owner, batch_id, assignment(batch.photos[:1], "no_event"))
    record = updated[0].analysis.record
    assert record.event.discipline.value is AthleticsDiscipline.NO_EVENT
    assert record.event.discipline.source is Source.MANUAL
    assert "Example Meet" in updated[0].caption
    assert "100m" not in updated[0].caption
    request = assignment(updated, "no_event")
    service.approve(owner, batch_id, request.photos)
    before = service.store.get(owner, batch_id)
    assert not service.preview_discipline(owner, batch_id, request).photos[0].changed
    service.assign_discipline(owner, batch_id, request)
    assert service.store.get(owner, batch_id).photos == before.photos
    service.analyze(owner, batch_id)
    Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces()).run_once()
    assert service.store.get(owner, batch_id).photos[0].analysis.record.event == record.event


def test_preview_explains_replacing_a_manual_discipline(environment):
    service, _ = environment
    batch = prepare(service)
    owner, batch_id, photo = batch.album.owner_id, batch.album.id, batch.photos[0]
    photo = service.edit(owner, batch_id, photo.id, Edit(revision=photo.revision, discipline="no_event"))
    request = assignment([photo], "long_jump")
    preview = service.preview_discipline(owner, batch_id, request)
    assert preview.photos[0].manual_discipline
    assert preview.photos[0].before_discipline is AthleticsDiscipline.NO_EVENT
    assert "Weitsprung" in preview.photos[0].after_caption
    assert service.assign_discipline(owner, batch_id, request)[0].caption == preview.photos[0].after_caption


@pytest.mark.parametrize("action", ["preview_discipline", "assign_discipline"])
def test_stale_or_invalid_selection_is_atomic_and_owner_scoped(environment, action):
    service, _ = environment
    batch = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    request = assignment(batch.photos)
    service.edit(owner, batch_id, batch.photos[-1].id, Edit(revision=batch.photos[-1].revision, caption="Later edit"))
    before = service.store.get(owner, batch_id)
    operation = getattr(service, action)
    with pytest.raises(Conflict, match="changed"):
        operation(owner, batch_id, request)
    assert service.store.get(owner, batch_id) == before
    with pytest.raises(Missing):
        operation(uuid4(), batch_id, assignment(before.photos))
    with pytest.raises(WorkflowError, match="only once"):
        operation(owner, batch_id, assignment([before.photos[0]] * 2))
    other = prepare(service)
    with pytest.raises(Missing):
        operation(owner, batch_id, assignment([before.photos[0], other.photos[0]]))
    assert service.store.get(owner, batch_id) == before
    service.analyze(owner, batch_id)
    with pytest.raises(Conflict, match="analysis to finish"):
        operation(owner, batch_id, assignment(before.photos))


def test_unanalyzed_photo_rejects_entire_selection(environment):
    service, _ = environment
    batch = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    batch.photos[-1].analysis = None
    with service.store.transaction(owner) as db:
        service.store.save(db, batch)
    with pytest.raises(Conflict, match="Analyze all"):
        service.assign_discipline(owner, batch_id, assignment(batch.photos))
    assert service.store.get(owner, batch_id) == batch


def test_http_requires_auth_write_header_valid_contract_and_fresh_revisions(environment):
    service, _ = environment
    batch = prepare(service)
    app = create_app(
        service.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    url = f"/api/batches/{batch.album.id}/discipline"
    body = assignment(batch.photos).model_dump(mode="json")
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        assert client.post(url, json=body, headers=headers).status_code == 401
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        assert client.post(url, json=body).status_code == 403
        for invalid in [{**body, "discipline": "invented"}, {**body, "photos": []}, {**body, "owner_id": str(uuid4())}]:
            assert client.post(url, json=invalid, headers=headers).status_code == 422
        preview = client.post(url + "-preview", json=body, headers=headers)
        assert preview.status_code == 200
        assert preview.headers["cache-control"] == "no-store, private"
        assert client.post(url, json=body, headers=headers).status_code == 200
        assert client.post(url, json=body, headers=headers).status_code == 409
