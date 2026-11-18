"""Add people and generate captions when detection misses a subject."""

from copy import deepcopy
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient

from startnummer.app.api import create_app
from startnummer.app.contracts import AddPerson, Edit, ManualPerson, Selection, SubjectEdit
from startnummer.app.worker import Worker
from startnummer.core.batch import AnalysisDocument, Conflict, Missing, WorkflowError
from startnummer.core.enums import Source, Status
from startnummer.core.models import Athlete
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports.athletics import AthleticsEvent
from tests.test_workflow import Detector, Faces, Ocr, analyzed, import_batch
from tests.test_workflow import environment as environment


@pytest.mark.parametrize("status", [None, Status.NEEDS_REVIEW, Status.FAILED])
def test_add_roster_person_with_no_subjects_generates_caption_and_requires_review(environment, status):
    service, _ = environment
    batch = import_batch(service)
    owner, batch_id, photo = batch.album.owner_id, batch.album.id, batch.photos[0]
    if status is not None:
        photo.analysis = AnalysisDocument(
            record=AnalysisRecord(
                owner_id=owner,
                album_id=batch_id,
                content_hash=photo.content_hash,
                meet_name="Example Meet",
                event=AthleticsEvent(),
                status=status,
                failure_reason="Test detector failure" if status is Status.FAILED else None,
            )
        )
        with service.store.transaction(owner) as db:
            service.store.save(db, batch)
    saved = service.add_person(owner, batch_id, photo.id, AddPerson(revision=photo.revision, roster_index=0))
    subject = saved.analysis.record.subjects[0]
    assert subject.athlete.value == batch.roster.athletes[0]
    assert subject.athlete.source is Source.MANUAL and subject.added_manually and subject.identity_edited
    assert subject.bibs == []
    assert saved.caption == "Alex Example (12, Example Club) über 100m/over 100m | Example Meet"
    assert not saved.approved and not saved.eligible
    if status is Status.FAILED:
        assert saved.analysis.record.failure_reason == "Test detector failure"
    with pytest.raises(Conflict):
        service.approve(owner, batch_id, [Selection(photo_id=saved.id, revision=saved.revision)])
    saved = service.edit(owner, batch_id, saved.id, Edit(revision=saved.revision, conflicts_resolved=True))
    service.approve(owner, batch_id, [Selection(photo_id=saved.id, revision=saved.revision)])
    assert service.store.get(owner, batch_id).photo(saved.id).approved
    assert not service.sessions.get(owner, batch_id)["available"]


def test_manual_caption_and_no_event_are_preserved_and_approval_is_revoked(environment):
    service, _ = environment
    batch = analyzed(service)
    photo = batch.photos[0]
    owner, batch_id = batch.album.owner_id, batch.album.id
    photo = service.edit(
        owner, batch_id, photo.id, Edit(revision=photo.revision, caption="Keep my text", discipline="no_event")
    )
    service.approve(owner, batch_id, [Selection(photo_id=photo.id, revision=photo.revision)])
    saved = service.add_person(owner, batch_id, photo.id, AddPerson(revision=photo.revision, roster_index=0))
    assert saved.caption == "Keep my text"
    assert saved.proposal == "Alex Example (12, Example Club)"
    assert saved.analysis.record.event.discipline.value == "no_event"
    assert saved.analysis.record.event.discipline.source is Source.MANUAL
    assert not saved.approved
    restored = service.remove_person(owner, batch_id, saved.id, 0, saved.revision)
    assert restored.caption == "Keep my text"
    assert restored.proposal is None
    assert restored.analysis.record.subjects == []


def test_roster_person_without_bib_and_ambiguous_discipline(environment):
    service, _ = environment
    batch = import_batch(service)
    batch.roster.athletes.append(Athlete(name="Sam Example", club="Second Club", entered_events=["100m", "long_jump"]))
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    photo = batch.photos[0]
    saved = service.add_person(
        batch.album.owner_id, batch.album.id, photo.id, AddPerson(revision=photo.revision, roster_index=1)
    )
    assert saved.caption == "Sam Example (Second Club) | Example Meet"
    assert saved.analysis.record.event.discipline is None
    assert saved.analysis.record.subjects[0].bibs == []


@pytest.mark.parametrize("from_roster", [True, False])
def test_added_people_survive_rerun_and_removal_preserves_detected_face_indexes(environment, from_roster):
    service, _ = environment
    batch = import_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    worker = Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces())
    service.analyze(owner, batch_id)
    worker.run_once()
    batch = service.store.get(owner, batch_id)
    if from_roster:
        batch.roster.athletes.append(Athlete(name="Other Person", bib="99"))
        with service.store.transaction(owner) as db:
            service.store.save(db, batch)
    source = {"roster_index": 1} if from_roster else {"person": ManualPerson(name="Other Person", bib="99")}
    photo = batch.photos[0]
    with pytest.raises(Conflict, match="Only people added manually"):
        service.remove_person(owner, batch_id, photo.id, 0, photo.revision)
    saved = service.add_person(owner, batch_id, photo.id, AddPerson(revision=photo.revision, **source))
    geometry = deepcopy(service.sessions.get(owner, batch_id)["photos"])
    removed = service.remove_person(owner, batch_id, photo.id, 1, saved.revision)
    assert service.sessions.get(owner, batch_id)["photos"] == geometry
    assert removed.analysis.record.subjects[0] == photo.analysis.record.subjects[0]
    added = service.add_person(owner, batch_id, photo.id, AddPerson(revision=removed.revision, **source))
    service.analyze(owner, batch_id)
    worker.run_once()
    saved = service.store.get(owner, batch_id).photo(photo.id)
    assert saved.caption == added.caption
    assert len(saved.analysis.record.subjects) == 2
    assert saved.analysis.record.subjects[1].added_manually


def test_add_remove_validate_owner_revision_duplicate_and_running_job(environment):
    service, _ = environment
    batch = import_batch(service)
    owner, batch_id, photo = batch.album.owner_id, batch.album.id, batch.photos[0]
    with pytest.raises(Missing):
        service.add_person(uuid4(), batch_id, photo.id, AddPerson(revision=photo.revision, roster_index=0))
    with pytest.raises(WorkflowError, match="Choose a person"):
        service.add_person(owner, batch_id, photo.id, AddPerson(revision=photo.revision, roster_index=100))
    saved = service.add_person(owner, batch_id, photo.id, AddPerson(revision=photo.revision, roster_index=0))
    with pytest.raises(Conflict, match="changed"):
        service.add_person(owner, batch_id, photo.id, AddPerson(revision=photo.revision, roster_index=0))
    with pytest.raises(WorkflowError, match="already listed"):
        service.add_person(owner, batch_id, photo.id, AddPerson(revision=saved.revision, roster_index=0))
    with pytest.raises(Conflict, match="changed"):
        service.remove_person(owner, batch_id, photo.id, 0, photo.revision)
    service.analyze(owner, batch_id)
    with pytest.raises(Conflict, match="analysis to finish"):
        service.add_person(owner, batch_id, photo.id, AddPerson(revision=saved.revision, roster_index=0))
    with pytest.raises(Conflict, match="analysis to finish"):
        service.remove_person(owner, batch_id, photo.id, 0, saved.revision)


def test_http_add_and_remove_are_authenticated_and_revision_checked(environment):
    service, _ = environment
    batch = import_batch(service)
    photo = batch.photos[0]
    app = create_app(
        service.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    url = f"/api/batches/{batch.album.id}/photos/{photo.id}/subjects"
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        body = {"revision": photo.revision, "roster_index": 0}
        assert client.post(url, json=body, headers=headers).status_code == 401
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        assert client.post(url, json=body).status_code == 403
        assert client.post(url, json={**body, "owner_id": str(uuid4())}, headers=headers).status_code == 422
        response = client.post(url, json=body, headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        saved = response.json()
        assert saved["analysis"]["record"]["subjects"][0]["added_manually"]
        assert client.post(url, json=body, headers=headers).status_code == 409
        response = client.request("DELETE", url + "/0", json={"revision": saved["revision"]}, headers=headers)
        assert response.status_code == 200
        assert response.json()["analysis"]["record"]["subjects"] == []


def test_add_unlisted_person_validates_input_and_preserves_manual_caption(environment):
    service, _ = environment
    batch = import_batch(service)
    owner, batch_id, photo = batch.album.owner_id, batch.album.id, batch.photos[0]
    photo = service.edit(owner, batch_id, photo.id, Edit(revision=photo.revision, caption="Keep my text"))
    app = create_app(service.settings, store=service.store, blobs=service.blobs, sessions=service.sessions)
    url = f"/api/batches/{batch_id}/photos/{photo.id}/subjects"
    headers = {"X-Requested-With": "Startnummer"}
    details = {"name": "  Sam   Visitor ", "bib": " 007 ", "club": " Away Club "}
    with TestClient(app, headers=headers) as client:
        client.post("/api/session", json={"username": "photographer", "password": "test-password"})
        for invalid in ({}, {"person": {"name": "  "}}, {"roster_index": 0, "person": details}):
            assert client.post(url, json={"revision": photo.revision, **invalid}).status_code == 422
        response = client.post(url, json={"revision": photo.revision, "person": details})
        assert response.status_code == 200
    saved = service.store.get(owner, batch_id).photo(photo.id)
    assert saved.caption == "Keep my text"
    assert saved.proposal == "Sam Visitor (007, Away Club) | Example Meet"
    subject = saved.analysis.record.subjects[0]
    assert subject.added_manually and subject.bibs == []
    assert not service.sessions.get(owner, batch_id)["available"]
    corrected = service.edit(
        owner,
        batch_id,
        photo.id,
        Edit(revision=saved.revision, subjects=[SubjectEdit(subject=0, athlete_name="Sam Guest", bib="008")]),
    )
    subject = corrected.analysis.record.subjects[0]
    assert subject.athlete.value.name == "Sam Guest"
    assert subject.athlete.value.bib == "008"
    assert subject.athlete.value.club == "Away Club"
    assert subject.bibs == []
