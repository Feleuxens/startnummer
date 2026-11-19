"""Imports without a roster retain manual naming and temporary face review."""

import pytest
from fastapi.testclient import TestClient

from startnummer.app.api import create_app
from startnummer.app.contracts import Edit, FaceTarget, PropagationApply, PropagationRequest
from startnummer.app.inference import InlineAnalyzer
from startnummer.app.services import InputPhoto
from startnummer.app.worker import Worker
from startnummer.core.batch import WorkflowError
from startnummer.core.enums import Source
from tests.test_face_propagation import NoBibOcr
from tests.test_workflow import HTML, Detector, Faces, Ocr, image_bytes
from tests.test_workflow import environment as environment


@pytest.mark.parametrize("gallery", [False, True])
@pytest.mark.parametrize("with_bibs", [False, True])
def test_import_analyze_name_propagate_and_finish_without_roster(environment, gallery, with_bibs):
    service, fetched = environment
    batch = service.import_batch(
        service.settings.owner_id,
        "Unofficial meet",
        "Example Meet",
        [] if gallery else [InputPhoto(f"photo-{i}.jpg", image_bytes()) for i in range(2)],
        "http://gallery.test/album/a" if gallery else None,
        None,
        None,
    )
    owner, batch_id = batch.album.owner_id, batch.album.id
    assert not batch.roster.athletes and batch.album.roster_source is None
    assert batch.album.meet_name == "Example Meet"
    assert service.store.get(owner, batch_id) == batch
    assert not any(roster for _, roster in fetched)
    assert all(bool(photo.destination) is gallery for photo in batch.photos)
    analyzer = InlineAnalyzer(Detector(), Ocr() if with_bibs else NoBibOcr(), Faces())

    def analyze(album, paths, *, entry_list, on_progress):
        # An empty saved roster must not suppress reads as an unmatched supplied roster would.
        assert entry_list is None
        return analyzer(album, paths, entry_list=entry_list, on_progress=on_progress)

    service.analyze(owner, batch_id)
    assert Worker(service.store, service.blobs, service.sessions, analyzer=analyze).run_once()
    assert service.store.jobs(owner, batch_id)[0].state == "done"
    batch = service.store.get(owner, batch_id)
    for photo in batch.photos:
        subject = photo.analysis.record.subjects[0]
        assert subject.athlete is None
        assert {bib.value for bib in subject.bibs} == ({"12"} if with_bibs else set())
        assert not photo.caption
    session_id = service.sessions.get(owner, batch_id)["session_id"]
    source = batch.photos[0]
    source = service.edit(
        owner,
        batch_id,
        source.id,
        Edit(
            revision=source.revision,
            subject=0,
            athlete_name="Taylor Visitor",
            club="Example Club",
            discipline="no_event",
            face_session_id=session_id,
        ),
    )
    request = PropagationRequest(
        source=FaceTarget(photo_id=source.id, revision=source.revision, subject=0),
        face_session_id=session_id,
    )
    preview = service.preview_propagation(owner, batch_id, request)
    assert len(preview.candidates) == 1
    candidate = preview.candidates[0]
    assert candidate.state == "eligible" and not candidate.warnings
    assigned = service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[candidate.target]))[
        0
    ]
    assert assigned.analysis.record.subjects[0].athlete.source is Source.MANUAL
    assert assigned.caption == "Taylor Visitor (Example Club) | Example Meet"
    service.approve_photo(owner, batch_id, assigned.id, assigned.revision)
    service.finish(owner, batch_id)
    assert not service.sessions.get(owner, batch_id)["available"]
    reopened = service.store.get(owner, batch_id)
    assert reopened.photo(assigned.id).caption == assigned.caption
    assert reopened.photo(assigned.id).approved
    assert not reopened.roster.athletes


def test_no_roster_propagation_still_protects_conflicting_bibs(environment):
    service, _ = environment
    batch = service.import_batch(
        service.settings.owner_id, "Conflicting bibs", "", [], "http://gallery.test/album/a", None, None
    )
    owner, batch_id = batch.album.owner_id, batch.album.id
    service.analyze(owner, batch_id)
    Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces()).run_once()
    batch = service.store.get(owner, batch_id)
    source, target = batch.photos
    session_id = service.sessions.get(owner, batch_id)["session_id"]
    source = service.edit(
        owner,
        batch_id,
        source.id,
        Edit(revision=source.revision, subject=0, bib="99", athlete_name="Taylor Visitor"),
    )
    preview = service.preview_propagation(
        owner,
        batch_id,
        PropagationRequest(
            source=FaceTarget(photo_id=source.id, revision=source.revision, subject=0),
            face_session_id=session_id,
        ),
    )
    candidate = preview.candidates[0]
    assert candidate.target.photo_id == target.id and candidate.state == "blocked"
    assert candidate.reason == "Bib differs from the selected person; review individually"


@pytest.mark.parametrize("html", [b"", b"<html></html>"])
def test_a_supplied_empty_roster_is_not_silently_treated_as_no_roster(environment, html):
    service, _ = environment
    with pytest.raises(WorkflowError, match="no athlete entries"):
        service.import_batch(
            service.settings.owner_id, "", "", [InputPhoto("photo.jpg", image_bytes())], None, html, None
        )
    assert not service.store.list_batches(service.settings.owner_id)
    assert not service.settings.blob_root.exists()


def test_import_still_rejects_two_roster_sources(environment):
    service, fetched = environment
    with pytest.raises(WorkflowError, match="only one roster source"):
        service.import_batch(
            service.settings.owner_id,
            "",
            "",
            [InputPhoto("photo.jpg", image_bytes())],
            None,
            HTML,
            "https://roster.test/roster",
        )
    assert not fetched


def test_http_upload_without_roster_keeps_authentication_and_rejects_empty_roster_files(environment):
    service, _ = environment
    app = create_app(service.settings, store=service.store, blobs=service.blobs, sessions=service.sessions)
    headers = {"X-Requested-With": "Startnummer"}
    files = [("photos", ("photo.jpg", image_bytes(), "image/jpeg"))]
    with TestClient(app) as client:
        assert client.post("/api/batches", files=files, headers=headers).status_code == 401
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        result = client.post("/api/batches", files=files, headers=headers)
        assert result.status_code == 200
        batch = result.json()
        assert batch["roster"]["athletes"] == [] and batch["album"]["roster_source"] is None
        assert len(batch["photos"]) == 1
        assert client.post("/api/batches", files=files).status_code == 403
        invalid = client.post(
            "/api/batches", files=[*files, ("roster_file", ("empty.html", b"", "text/html"))], headers=headers
        )
        assert invalid.status_code == 400 and "no athlete entries" in invalid.json()["detail"]
        assert invalid.json()["field"] == "roster"


def test_roster_preview_distinguishes_an_unsupported_page_from_a_supported_empty_roster(environment):
    service, _ = environment
    app = create_app(service.settings, store=service.store, blobs=service.blobs, sessions=service.sessions)
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app, headers=headers) as client:
        client.post("/api/session", json={"username": "photographer", "password": "test-password"})
        for html, message in (
            (b"<html><h1>Other competition page</h1></html>", "Use a Competitoroverview or Resultoverview page"),
            (b'<div id="seltecdlv"><div class="blocktable">No entries</div></div>', "no athlete entries"),
        ):
            response = client.post("/api/roster/preview", files={"roster_file": ("roster.html", html)})
            assert response.status_code == 400 and response.json()["field"] == "roster"
            assert message in response.json()["detail"]


def test_review_read_cannot_pair_a_completed_job_with_pre_analysis_photos(environment, monkeypatch):
    service, _ = environment
    batch = service.import_batch(
        service.settings.owner_id, "Review read", "", [], "http://gallery.test/album/a", None, None
    )
    service.analyze(batch.album.owner_id, batch.album.id)
    worker = Worker(service.store, service.blobs, service.sessions, Detector(), NoBibOcr(), Faces())
    original_jobs = service.store.jobs

    def complete_before_reading_jobs(owner, batch_id, *, session=None):
        if session is not None:
            assert worker.run_once()
        return original_jobs(owner, batch_id, session=session)

    monkeypatch.setattr(service.store, "jobs", complete_before_reading_jobs)
    app = create_app(service.settings, store=service.store, blobs=service.blobs, sessions=service.sessions)
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        response = client.get(f"/api/batches/{batch.album.id}")
    assert response.status_code == 200
    view = response.json()
    assert view["jobs"][0]["state"] == "done"
    assert all(photo["analysis"]["record"]["subjects"] for photo in view["batch"]["photos"])
