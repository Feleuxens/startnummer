"""Confirmed face-name propagation using synthetic photos and transient groups."""

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from sqlalchemy import select

from startnummer.adapters.db.schema import BatchRow, PhotoRow
from startnummer.app.contracts import Edit, FaceTarget, PropagationApply, PropagationRequest, Selection
from startnummer.app.services import InputPhoto
from startnummer.app.worker import Worker
from startnummer.core.batch import Conflict, Missing
from startnummer.core.enums import Source
from startnummer.core.models import Athlete
from startnummer.core.types import OcrResult
from tests.test_workflow import HTML, Detector, Faces, image_bytes
from tests.test_workflow import environment as environment


class NoBibOcr:
    def read(self, path):
        return OcrResult([], [])


def prepare(service, count=4):
    batch = service.import_batch(
        service.settings.owner_id,
        "Face review",
        "Example Meet",
        [InputPhoto(f"original-{i}.jpg", image_bytes()) for i in range(count)],
        None,
        HTML,
        None,
    )
    service.analyze(batch.album.owner_id, batch.album.id)
    Worker(service.store, service.blobs, service.sessions, Detector(), NoBibOcr(), Faces()).run_once()
    batch = service.store.get(batch.album.owner_id, batch.album.id)
    data = service.sessions.get(batch.album.owner_id, batch.album.id)
    source = batch.photos[0]
    source = service.edit(
        batch.album.owner_id,
        batch.album.id,
        source.id,
        Edit(revision=source.revision, subject=0, athlete_name="Taylor Visitor", face_session_id=data["session_id"]),
    )
    request = PropagationRequest(
        source=FaceTarget(photo_id=source.id, revision=source.revision, subject=0),
        face_session_id=data["session_id"],
    )
    return batch, request


def test_preview_exclusions_manual_caption_and_approval(environment):
    service, _ = environment
    batch, request = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    target, excluded, manual = batch.photos[1:]
    target = service.edit(owner, batch_id, target.id, Edit(revision=target.revision, caption="My custom caption"))
    service.approve(owner, batch_id, [Selection(photo_id=target.id, revision=target.revision)])
    manual = service.edit(owner, batch_id, manual.id, Edit(revision=manual.revision, subject=0, athlete_name="Keep Me"))
    before = service.store.get(owner, batch_id)
    preview = service.preview_propagation(owner, batch_id, request)
    assert service.store.get(owner, batch_id) == before
    assert len(preview.candidates) == 3
    candidate = preview.candidates[0]
    assert candidate.caption_preserved
    assert candidate.proposed_caption == "My custom caption"
    assert preview.candidates[2].reason.startswith("Manual identity")
    result = service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[candidate.target]))
    assert len(result) == 1 and not result[0].approved
    assert result[0].caption == "My custom caption"
    assert "Taylor Visitor" in result[0].proposal
    assert result[0].analysis.record.subjects[0].bibs == []
    assert result[0].analysis.record.subjects[0].athlete.source is Source.MANUAL
    assert "matching face" in result[0].analysis.record.subjects[0].athlete.note
    saved = service.store.get(owner, batch_id)
    assert saved.photo(excluded.id) == before.photo(excluded.id)
    assert saved.photo(manual.id) == before.photo(manual.id)
    with service.store.transaction() as db:
        documents = [row.document for row in db.scalars(select(PhotoRow))]
        documents += [row.document for row in db.scalars(select(BatchRow))]
    import json

    serialized = json.dumps(documents)
    assert request.face_session_id not in serialized
    for field in ['"group":', '"box":', '"embedding":', '"face_session_id":']:
        assert field not in serialized
    service.finish(owner, batch_id)
    assert not service.sessions.get(owner, batch_id)["available"]
    assert service.store.get(owner, batch_id).photo(target.id).caption == "My custom caption"
    with pytest.raises(Conflict, match="expired"):
        service.preview_propagation(owner, batch_id, request)


def test_stale_or_ineligible_target_rejects_entire_selection(environment):
    service, _ = environment
    batch, request = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    preview = service.preview_propagation(owner, batch_id, request)
    stale = preview.candidates[1].target
    service.edit(owner, batch_id, stale.photo_id, Edit(revision=stale.revision, subject=0, athlete_name="Keep Me"))
    before = service.store.get(owner, batch_id)
    with pytest.raises(Conflict, match="changed"):
        service.propagate(
            owner,
            batch_id,
            PropagationApply(
                **request.model_dump(),
                targets=[c.target for c in preview.candidates],
            ),
        )
    assert service.store.get(owner, batch_id) == before
    fresh = service.preview_propagation(owner, batch_id, request)
    forbidden = next(c for c in fresh.candidates if c.target.photo_id == stale.photo_id)
    with pytest.raises(Conflict):
        service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[forbidden.target]))
    with pytest.raises(Exception, match="only once"):
        service.propagate(
            owner,
            batch_id,
            PropagationApply(
                **request.model_dump(),
                targets=[fresh.candidates[0].target] * 2,
            ),
        )


def test_session_owner_source_revision_and_target_membership(environment):
    from uuid import uuid4

    service, _ = environment
    batch, request = prepare(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    with pytest.raises(Missing):
        service.preview_propagation(uuid4(), batch_id, request)
    wrong_session = request.model_copy(update={"face_session_id": "expired"})
    with pytest.raises(Conflict, match="expired"):
        service.preview_propagation(owner, batch_id, wrong_session)
    foreign = FaceTarget(photo_id=uuid4(), revision=0, subject=0)
    with pytest.raises(Conflict):
        service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[foreign]))
    source = batch.photos[0]
    service.edit(owner, batch_id, source.id, Edit(revision=request.source.revision, caption="Updated source"))
    with pytest.raises(Conflict, match="Source photo changed"):
        service.preview_propagation(owner, batch_id, request)


def test_groups_without_bibs_update_captions_but_keep_manual_no_event(environment):
    service, _ = environment
    batch, request = prepare(service, count=2)
    target = batch.photos[1]
    target = service.edit(
        batch.album.owner_id, batch.album.id, target.id, Edit(revision=target.revision, discipline="no_event")
    )
    preview = service.preview_propagation(batch.album.owner_id, batch.album.id, request)
    assert preview.candidates[0].proposed_caption == "Taylor Visitor | Example Meet"
    result = service.propagate(
        batch.album.owner_id,
        batch.album.id,
        PropagationApply(
            **request.model_dump(),
            targets=[preview.candidates[0].target],
        ),
    )[0]
    assert result.analysis.record.event.discipline.value == "no_event"
    assert result.analysis.record.event.discipline.source is Source.MANUAL
    assert result.caption == "Taylor Visitor | Example Meet"
    assert not result.conflicts_resolved and not result.approved


def test_different_roster_identity_is_shown_but_not_overwritten(environment):
    from startnummer.core.models import Confident

    service, _ = environment
    batch, request = prepare(service, count=2)
    batch = service.store.get(batch.album.owner_id, batch.album.id)
    target = batch.photos[1]
    target.analysis.record.subjects[0].athlete = Confident(
        value=batch.roster.athletes[0],
        confidence=0.95,
        source=Source.ROSTER,
    )
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    preview = service.preview_propagation(batch.album.owner_id, batch.album.id, request)
    assert "Different athlete" in preview.candidates[0].reason
    assert preview.candidates[0].state == "blocked"


def test_tentative_roster_name_can_be_replaced_only_after_confirmation(environment):
    from startnummer.core.models import Confident

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    source = service.edit(
        owner,
        batch_id,
        request.source.photo_id,
        Edit(revision=request.source.revision, subject=0, roster_bib="12"),
    )
    request.source.revision = source.revision
    saved = service.store.get(owner, batch_id)
    other = Athlete(name="Other Person", bib="13")
    saved.roster.athletes.append(other)
    target = saved.photos[1]
    target.analysis.record.subjects[0].athlete = Confident(value=other, confidence=0.5, source=Source.ROSTER)
    target.analysis.record.subjects[0].bibs = [Confident(value="12", confidence=0.9, source=Source.FACE_MATCH)]
    with service.store.transaction(owner) as db:
        service.store.save(db, saved)
    target = service.edit(owner, batch_id, target.id, Edit(revision=target.revision, caption="My edited caption"))
    service.approve(owner, batch_id, [Selection(photo_id=target.id, revision=target.revision)])
    preview = service.preview_propagation(owner, batch_id, request)
    candidate = preview.candidates[0]
    assert candidate.state == "eligible" and candidate.reason is None
    assert candidate.replaces_tentative_name and not candidate.requires_bib_confirmation
    assert "Other Person" in candidate.warnings[0] and "50%" in candidate.warnings[0]
    before = service.store.get(owner, batch_id)
    with pytest.raises(Conflict, match="Confirm replacement of the tentative names"):
        service.propagate(
            owner,
            batch_id,
            PropagationApply(
                **request.model_dump(),
                targets=[candidate.target],
                acknowledge_unsupported_bibs=True,
            ),
        )
    assert service.store.get(owner, batch_id) == before
    result = service.propagate(
        owner,
        batch_id,
        PropagationApply(
            **request.model_dump(),
            targets=[candidate.target],
            acknowledge_tentative_names=True,
        ),
    )[0]
    assert result.analysis.record.subjects[0].athlete.value.bib == "12"
    assert result.analysis.record.subjects[0].athlete.source is Source.MANUAL
    assert result.caption == "My edited caption"
    assert not result.approved and not result.conflicts_resolved
    assert result.revision > target.revision


def test_already_named_face_is_reported_without_changes(environment):
    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    target = batch.photos[1]
    service.edit(owner, batch_id, target.id, Edit(revision=target.revision, subject=0, athlete_name="Taylor Visitor"))
    before = service.store.get(owner, batch_id)
    preview = service.preview_propagation(owner, batch_id, request)
    candidate = preview.candidates[0]
    assert candidate.state == "already_named"
    assert candidate.proposed_caption == before.photo(target.id).caption
    with pytest.raises(Conflict):
        service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[candidate.target]))
    assert service.store.get(owner, batch_id) == before


def test_expired_confirmation_cannot_write_and_manual_bib_removal_is_preserved(environment):
    service, _ = environment
    batch, request = prepare(service, count=3)
    owner, batch_id = batch.album.owner_id, batch.album.id
    target = batch.photos[1]
    service.edit(owner, batch_id, target.id, Edit(revision=target.revision, subject=0, bib=""))
    preview = service.preview_propagation(owner, batch_id, request)
    assert "Manual identity" in preview.candidates[0].reason
    before = service.store.get(owner, batch_id)
    key = (str(owner), str(batch_id))
    item = service.sessions._items[key]
    service.sessions._items[key] = (0, *item[1:])
    with pytest.raises(Conflict, match="expired"):
        service.propagate(
            owner,
            batch_id,
            PropagationApply(
                **request.model_dump(),
                targets=[preview.candidates[1].target],
            ),
        )
    assert service.store.get(owner, batch_id) == before
    service.analyze(owner, batch_id)
    Worker(service.store, service.blobs, service.sessions, Detector(), NoBibOcr(), Faces()).run_once()
    retained = service.store.get(owner, batch_id).photo(target.id)
    assert retained.analysis.record.subjects[0].identity_edited
    assert retained.analysis.record.subjects[0].bibs == []
    assert str(target.id) not in service.sessions.get(owner, batch_id)["photos"]


def test_http_propagation_is_authenticated_private_and_revision_checked(environment):
    from fastapi.testclient import TestClient

    from startnummer.app.api import create_app

    service, _ = environment
    batch, request = prepare(service, count=2)
    app = create_app(
        service.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    prefix = f"/api/batches/{batch.album.id}/face-propagation"
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        assert (
            client.post(prefix + "/preview", json=request.model_dump(mode="json"), headers=headers).status_code == 401
        )
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        response = client.post(prefix + "/preview", json=request.model_dump(mode="json"), headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        candidate = response.json()["candidates"][0]
        body = {**request.model_dump(mode="json"), "targets": [candidate["target"]]}
        assert client.post(prefix, json=body).status_code == 403
        response = client.post(prefix, json=body, headers=headers)
        assert response.status_code == 200
        assert response.json()[0]["analysis"]["record"]["subjects"][0]["athlete"]["value"]["name"] == "Taylor Visitor"
        assert client.post(prefix, json=body, headers=headers).status_code == 409


@pytest.mark.parametrize("tentative_name", [False, True])
def test_corrected_source_bib_cannot_override_a_different_target_bib(environment, tentative_name):
    from startnummer.core.models import Confident

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    saved = service.store.get(owner, batch_id)
    source, target = saved.photos
    saved.roster.athletes.append(Athlete(name="Another Athlete", bib="13"))
    source.analysis.record.subjects[0].bibs = [Confident(value="12", confidence=1, source=Source.MANUAL)]
    target.analysis.record.subjects[0].bibs = [Confident(value="13", confidence=0.95, source=Source.OCR)]
    if tentative_name:
        target.analysis.record.subjects[0].athlete = Confident(
            value=saved.roster.athletes[-1],
            confidence=0.5,
            source=Source.ROSTER,
        )
    with service.store.transaction(owner) as db:
        service.store.save(db, saved)
    preview = service.preview_propagation(owner, batch_id, request)
    assert "Bib differs" in preview.candidates[0].reason
    assert preview.candidates[0].state == "blocked"
    before = service.store.get(owner, batch_id)
    with pytest.raises(Conflict):
        service.propagate(
            owner,
            batch_id,
            PropagationApply(
                **request.model_dump(),
                targets=[preview.candidates[0].target],
                acknowledge_unsupported_bibs=True,
                acknowledge_tentative_names=True,
            ),
        )
    assert service.store.get(owner, batch_id) == before


def test_conflicting_source_bib_and_roster_name_require_individual_review(environment):
    from startnummer.core.models import Confident

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    saved = service.store.get(owner, batch_id)
    subject = saved.photos[0].analysis.record.subjects[0]
    saved.roster.athletes.append(Athlete(name="Another Athlete", bib="13"))
    subject.athlete.value.bib = "12"
    subject.bibs = [Confident(value="13", confidence=0.95, source=Source.OCR)]
    with service.store.transaction(owner) as db:
        service.store.save(db, saved)
    with pytest.raises(Conflict, match="conflicting bib and name"):
        service.preview_propagation(owner, batch_id, request)


def test_undo_restores_identity_and_caption_but_never_reuses_approval(environment):
    from startnummer.app.contracts import PropagationUndo

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    target = batch.photos[1]
    target = service.edit(owner, batch_id, target.id, Edit(revision=target.revision, caption="My caption"))
    service.approve(owner, batch_id, [Selection(photo_id=target.id, revision=target.revision)])
    preview = service.preview_propagation(owner, batch_id, request)
    service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[preview.candidates[0].target]))
    data = service.sessions.get(owner, batch_id)
    assert data["undo_count"] == 1
    undo = PropagationUndo(face_session_id=data["session_id"], undo_id=data["undo_id"])
    result = service.undo_propagation(owner, batch_id, undo)[0]
    assert result.analysis.record.subjects[0].athlete is None
    assert result.caption == "My caption" and not result.approved
    assert result.revision > preview.candidates[0].target.revision
    assert service.sessions.get(owner, batch_id)["undo_id"] is None
    with pytest.raises(Conflict, match="Undo expired"):
        service.undo_propagation(owner, batch_id, undo)


def test_undo_rejects_later_edits_and_expires_with_the_face_session(environment):
    from startnummer.app.contracts import PropagationUndo

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    preview = service.preview_propagation(owner, batch_id, request)
    target = service.propagate(
        owner,
        batch_id,
        PropagationApply(
            **request.model_dump(),
            targets=[preview.candidates[0].target],
        ),
    )[0]
    data = service.sessions.get(owner, batch_id)
    undo = PropagationUndo(face_session_id=data["session_id"], undo_id=data["undo_id"])
    service.edit(owner, batch_id, target.id, Edit(revision=target.revision, caption="Later edit"))
    with pytest.raises(Conflict, match="changed after"):
        service.undo_propagation(owner, batch_id, undo)
    assert service.store.get(owner, batch_id).photo(target.id).caption == "Later edit"
    service.finish(owner, batch_id)
    assert service.sessions._undo == {}
    with pytest.raises(Conflict, match="Undo expired"):
        service.undo_propagation(owner, batch_id, undo)


def test_undo_keeps_the_current_gallery_value_after_publishing(environment):
    from startnummer.app.contracts import PropagationUndo
    from startnummer.core.batch import Destination

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    saved = service.store.get(owner, batch_id)
    target = saved.photos[1]
    target.destination = Destination(instance="http://gallery.test", image_id=1, page_url="http://gallery.test/image/1")
    with service.store.transaction(owner) as db:
        service.store.save(db, saved)
    preview = service.preview_propagation(owner, batch_id, request)
    assigned = service.propagate(
        owner,
        batch_id,
        PropagationApply(
            **request.model_dump(),
            targets=[preview.candidates[0].target],
        ),
    )[0]
    selection = Selection(photo_id=assigned.id, revision=assigned.revision)
    service.approve(owner, batch_id, [selection])
    service.apply(owner, batch_id, [selection])
    data = service.sessions.get(owner, batch_id)
    restored = service.undo_propagation(
        owner,
        batch_id,
        PropagationUndo(
            face_session_id=data["session_id"],
            undo_id=data["undo_id"],
        ),
    )[0]
    assert restored.current_description == assigned.caption
    assert service.gallery.values[1] == assigned.caption
    assert restored.caption is None
    assert not restored.approved and not restored.replace_existing


@pytest.mark.parametrize("source_warning", [False, True])
def test_unsupported_bib_requires_confirmation_and_remains_review_evidence(environment, source_warning):
    from startnummer.core.models import Confident

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    saved = service.store.get(owner, batch_id)
    source, target = saved.photos
    source.analysis.record.subjects[0].athlete.value.bib = "12"
    noisy = source if source_warning else target
    noisy.analysis.record.subjects[0].bibs = [Confident(value="2030", confidence=0.99, source=Source.OCR)]
    noisy.analysis.record.status = "needs_review"
    with service.store.transaction(owner) as db:
        service.store.save(db, saved)
    preview = service.preview_propagation(owner, batch_id, request)
    candidate = preview.candidates[0]
    assert candidate.reason is None
    assert ("2030" in " ".join(preview.warnings)) is source_warning
    assert ("2030" in " ".join(candidate.warnings)) is not source_warning
    before = service.store.get(owner, batch_id)
    with pytest.raises(Conflict, match="Confirm the unsupported bib reads"):
        service.propagate(owner, batch_id, PropagationApply(**request.model_dump(), targets=[candidate.target]))
    assert service.store.get(owner, batch_id) == before
    result = service.propagate(
        owner,
        batch_id,
        PropagationApply(
            **request.model_dump(),
            targets=[candidate.target],
            acknowledge_unsupported_bibs=True,
        ),
    )[0]
    assert result.analysis.record.subjects[0].athlete.value.name == "Taylor Visitor"
    assert not result.approved and not result.conflicts_resolved
    assert service.store.get(owner, batch_id).photo(noisy.id).analysis.record.subjects[0].bibs[0].value == "2030"


def test_excluded_unsupported_read_does_not_require_confirmation(environment):
    from startnummer.core.models import Confident

    service, _ = environment
    batch, request = prepare(service, count=3)
    owner, batch_id = batch.album.owner_id, batch.album.id
    saved = service.store.get(owner, batch_id)
    saved.photos[1].analysis.record.subjects[0].bibs = [Confident(value="2030", confidence=0.99, source=Source.OCR)]
    with service.store.transaction(owner) as db:
        service.store.save(db, saved)
    preview = service.preview_propagation(owner, batch_id, request)
    assert preview.candidates[0].warnings and not preview.candidates[1].warnings
    result = service.propagate(
        owner, batch_id, PropagationApply(**request.model_dump(), targets=[preview.candidates[1].target])
    )
    assert len(result) == 1
    assert service.store.get(owner, batch_id).photos[1].analysis.record.subjects[0].athlete is None


def test_legacy_worker_session_is_explained_and_individual_naming_still_works(environment):
    from fastapi.testclient import TestClient

    from startnummer.app.api import create_app

    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    current = service.sessions

    class Legacy:
        def get(self, *args):
            data = current.get(*args)
            return {key: value for key, value in data.items() if key != "protocol_version"}

        def validate(self, *args):
            return current.validate(*args)

    service.sessions = Legacy()
    before = service.store.get(owner, batch_id)
    with pytest.raises(Conflict, match="Restart the updated worker"):
        service.preview_propagation(owner, batch_id, request)
    assert service.store.get(owner, batch_id) == before
    app = create_app(
        service.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        faces = client.get(f"/api/batches/{batch_id}/faces").json()
        assert faces["available"] and not faces["propagation_available"]
        assert "Restart the updated worker" in faces["propagation_unavailable_reason"]
        assert "group" not in str(faces["photos"])
        target = before.photos[1]
        response = client.patch(
            f"/api/batches/{batch_id}/photos/{target.id}",
            headers=headers,
            json={
                "revision": target.revision,
                "subject": 0,
                "athlete_name": "Individually Named",
                "face_session_id": request.face_session_id,
            },
        )
        assert response.status_code == 200
        assert response.json()["analysis"]["record"]["subjects"][0]["athlete"]["value"]["name"] == "Individually Named"


def test_missing_groups_in_current_worker_are_not_reported_as_zero_matches(environment):
    service, _ = environment
    batch, request = prepare(service, count=2)
    data = service.sessions.get(batch.album.owner_id, batch.album.id)
    for faces in data["photos"].values():
        for face in faces:
            face.pop("group")
    service.sessions.put(batch.album.owner_id, batch.album.id, data["photos"])
    request.face_session_id = service.sessions.get(batch.album.owner_id, batch.album.id)["session_id"]
    with pytest.raises(Conflict, match="Face match groups are missing"):
        service.preview_propagation(batch.album.owner_id, batch.album.id, request)
