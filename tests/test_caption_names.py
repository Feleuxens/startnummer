"""Caption names are private display rules, never changes to athlete identity."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine

from startnummer.adapters.db.store import Store
from startnummer.app.backup import backup, restore
from startnummer.app.captions import caption_preferences
from startnummer.app.contracts import (
    AlbumSettings,
    CaptionNames,
    DisciplineAssignment,
    Edit,
    PropagationApply,
    Selection,
)
from startnummer.app.inference import InlineAnalyzer
from startnummer.app.manage import migrate
from startnummer.app.operations import effective_settings, runtime_settings
from startnummer.app.worker import Worker
from startnummer.core.batch import Conflict, Missing
from startnummer.core.description import build_description, caption_name_key
from startnummer.core.enums import Source
from startnummer.core.models import Confident, Subject
from tests.test_accounts import HEADERS, imported, invite, setup
from tests.test_accounts import accounts as accounts
from tests.test_face_propagation import prepare
from tests.test_workflow import Detector, Faces, Ocr, analyzed, import_batch
from tests.test_workflow import environment as environment

RULE = {"source_name": "Alex Example", "caption_name": "Alex van Example"}


def named_batch(service):
    batch = analyzed(service)
    for photo in batch.photos:
        record = photo.analysis.record
        record.subjects = [
            Subject(athlete=Confident(value=batch.roster.athletes[0], confidence=0.95, source=Source.ROSTER))
        ]
        photo.proposal = photo.caption = record.description = build_description(record)
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    return batch


def save_rules(service, rules=None, owner=None):
    owner = owner or service.settings.owner_id
    current = caption_preferences(service.store, owner)
    preferences = CaptionNames(revision=current.revision, overrides=[RULE] if rules is None else rules)
    service.store.save_settings(
        owner, preferences.revision, {"caption_name_overrides": [r.model_dump() for r in preferences.overrides]}
    )
    return caption_preferences(service.store, owner)


def test_core_overrides_only_the_full_caption_name_without_modifying_evidence(record):
    before = record.model_copy(deep=True)
    caption = build_description(
        record,
        name_overrides={
            caption_name_key("  ALEX  EXAMPLE "): "Alex van Example",
            "example": "Do not use",
            caption_name_key("Alex van Example"): "Do not chain",
        },
    )
    assert caption == "Alex van Example (12, Example Club)"
    assert record == before
    assert build_description(record, name_overrides={"alex": "Do not use"}) == "Alex Example (12, Example Club)"
    record.subjects[0].athlete.confidence = 0.1
    assert build_description(record, name_overrides={"alex example": "Still uncertain"}) is None


@pytest.mark.parametrize(
    "rules",
    [
        [{"source_name": " ", "caption_name": "Name"}],
        [{"source_name": "Name", "caption_name": " "}],
        [RULE, {"source_name": " ALEX  EXAMPLE ", "caption_name": "Other"}],
        [{**RULE, "owner_id": str(uuid4())}],
    ],
)
def test_invalid_or_ambiguous_rules_are_rejected(rules):
    with pytest.raises(ValidationError):
        CaptionNames(overrides=rules)


def test_names_and_runtime_settings_share_revision_without_overwriting_each_other(environment):
    service, _ = environment
    options = runtime_settings(service.store, service.settings)
    service.store.save_settings(service.settings.owner_id, 0, options.model_dump(exclude={"revision"}))
    names = save_rules(service)
    assert effective_settings(service.store, service.settings).max_file_bytes == options.max_file_bytes
    assert "caption_name_overrides" not in runtime_settings(service.store, service.settings).model_dump()
    service.store.save_settings(service.settings.owner_id, names.revision, {"session_ttl": 1200})
    assert caption_preferences(service.store, service.settings.owner_id).overrides == names.overrides
    assert effective_settings(service.store, service.settings).session_ttl == 1200
    with pytest.raises(Conflict):
        service.store.save_settings(service.settings.owner_id, names.revision, {"caption_name_overrides": []})


def test_analysis_and_regeneration_use_only_the_owners_overrides(environment):
    service, _ = environment
    batch = import_batch(service)
    original_roster = batch.roster.model_copy(deep=True)
    other = uuid4()
    save_rules(service, [{"source_name": "Alex Example", "caption_name": "Another account"}], other)
    save_rules(service)
    service.analyze(batch.album.owner_id, batch.album.id)
    assert Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces()).run_once()
    saved = service.store.get(batch.album.owner_id, batch.album.id)
    photo = saved.photos[0]
    assert "Alex van Example" in photo.caption
    assert saved.roster == original_roster
    assert photo.analysis.record.subjects[0].athlete.value.name == "Alex Example"
    photo = service.edit(
        batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, discipline="no_event")
    )
    assert photo.caption == "Alex van Example (12, Example Club) | Example Meet"


def test_edit_album_regenerates_suggestions_with_local_rules_and_keeps_manual_text_and_faces(environment):
    service, _ = environment
    batch, other = named_batch(service), named_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    first, second = batch.photos
    second = service.edit(owner, batch_id, second.id, Edit(revision=second.revision, caption="My reviewed caption"))
    service.approve_photo(owner, batch_id, first.id, first.revision)
    service.approve_photo(owner, batch_id, second.id, second.revision)
    service.sessions.put(owner, batch_id, {str(first.id): [{"subject": 0, "box": [1, 2, 3, 4]}]})
    face_session = service.sessions.get(owner, batch_id)["session_id"]
    save_rules(service)

    changed = AlbumSettings(
        revision=0,
        name=" Renamed album ",
        meet_name=" Corrected meet ",
        overrides=[{"source_name": "Alex Example", "caption_name": "Alex Album"}],
    )
    album = service.edit_album_settings(owner, batch_id, changed)
    saved = service.store.get(owner, batch_id)
    assert album.settings_revision == 1 and saved.album.name == "Renamed album"
    assert saved.album.meet_name == "Corrected meet"
    assert saved.photos[0].caption == "Alex Album (12, Example Club) | Corrected meet"
    assert saved.photos[1].caption == "My reviewed caption"
    assert saved.photos[1].proposal == saved.photos[0].caption
    assert [photo.approved for photo in saved.photos] == [False, False]
    assert saved.roster == batch.roster
    assert [photo.destination for photo in saved.photos] == [photo.destination for photo in batch.photos]
    assert saved.photos[0].analysis.record.subjects[0].athlete.value.name == "Alex Example"
    assert service.sessions.get(owner, batch_id)["session_id"] == face_session
    assert service.store.get(owner, other.album.id) == other
    with pytest.raises(Conflict, match="Album settings changed"):
        service.edit_album_settings(owner, batch_id, changed)

    removed = changed.model_copy(update={"revision": 1, "overrides": [], "meet_name": None})
    service.edit_album_settings(owner, batch_id, removed)
    assert service.store.get(owner, batch_id).photos[0].caption == "Alex van Example (12, Example Club)"


def test_running_analysis_uses_album_edits_made_after_inference(environment):
    service, _ = environment
    batch = import_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    inline = InlineAnalyzer(Detector(), Ocr(), Faces())
    edited = AlbumSettings(revision=0, name="Edited during analysis", meet_name="New meet", overrides=[RULE])

    def analyze(album, paths, **options):
        result = inline(album, paths, **options)
        assert result.records[0].meet_name == "Example Meet"
        service.edit_album_settings(owner, batch_id, edited)
        return result

    service.analyze(owner, batch_id)
    assert Worker(service.store, service.blobs, service.sessions, analyzer=analyze).run_once()
    saved = service.store.get(owner, batch_id)
    assert saved.album.name == "Edited during analysis"
    assert saved.photos[0].analysis.record.meet_name == "New meet"
    assert "Alex van Example" in saved.photos[0].caption and saved.photos[0].caption.endswith(" | New meet")
    assert service.sessions.get(owner, batch_id)["available"]


def test_album_revision_protects_previews_even_when_existing_captions_are_unaffected(environment):
    service, _ = environment
    batch = named_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    request = DisciplineAssignment(
        discipline="long_jump", photos=[Selection(photo_id=p.id, revision=p.revision) for p in batch.photos]
    )
    preview = service.preview_discipline(owner, batch_id, request)
    service.edit_album_settings(
        owner,
        batch_id,
        AlbumSettings(
            revision=0, name="New title", overrides=[{"source_name": "Other Runner", "caption_name": "Other"}]
        ),
    )
    assert service.store.get(owner, batch_id).photos == batch.photos
    confirmed = request.model_copy(update={"album_settings_revision": preview.album_settings_revision})
    with pytest.raises(Conflict, match="Album settings changed"):
        service.assign_discipline(owner, batch_id, confirmed)


def test_album_settings_endpoint_is_owner_scoped(accounts):
    app, _, _, _ = accounts
    with setup(app) as admin:
        member, _ = invite(admin, app)
        with member:
            batch = imported(member)
            path = f"/api/batches/{batch['album']['id']}/settings"
            settings = {"revision": 0, "name": "Renamed", "overrides": [RULE, RULE]}
            assert member.put(path, json=settings).status_code == 422
            settings["overrides"] = [RULE]
            assert admin.put(path, json=settings).status_code == 404
            saved = member.put(path, json=settings)
            assert saved.status_code == 200 and saved.json()["caption_name_overrides"] == [RULE]
            assert member.get("/api/account/caption-names").json()["overrides"] == []


@pytest.mark.parametrize("manual", [False, True])
def test_refresh_is_explicit_revision_checked_and_keeps_face_sessions_and_manual_text(environment, manual):
    service, _ = environment
    batch = named_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    photo = batch.photos[0]
    if manual:
        photo = service.edit(owner, batch_id, photo.id, Edit(revision=photo.revision, caption="Keep my text"))
    photo = service.approve_photo(owner, batch_id, photo.id, photo.revision)
    service.sessions.put(owner, batch_id, {str(photo.id): [{"subject": 0, "box": [1, 2, 3, 4]}]})
    faces = service.sessions.get(owner, batch_id)
    before = service.store.get(owner, batch_id)
    save_rules(service)
    assert service.store.get(owner, batch_id) == before
    result = service.refresh_caption_suggestion(owner, batch_id, photo.id, photo.revision)
    assert result.caption == ("Keep my text" if manual else "Alex van Example (12, Example Club)")
    assert result.proposal == "Alex van Example (12, Example Club)"
    assert not result.approved and result.revision == photo.revision + 1
    assert result.analysis.record.subjects == photo.analysis.record.subjects
    current_faces = service.sessions.get(owner, batch_id)
    assert current_faces["session_id"] == faces["session_id"]
    assert current_faces["photos"] == faces["photos"]
    assert current_faces["expires_at"] == pytest.approx(faces["expires_at"], abs=0.01, rel=0)
    assert service.store.get(owner, batch_id).photos[1] == before.photos[1]
    assert service.refresh_caption_suggestion(owner, batch_id, photo.id, result.revision) == result
    with pytest.raises(Conflict):
        service.refresh_caption_suggestion(owner, batch_id, photo.id, photo.revision)
    with pytest.raises(Missing):
        service.refresh_caption_suggestion(uuid4(), batch_id, photo.id, result.revision)
    if manual:
        result = service.edit(owner, batch_id, photo.id, Edit(revision=result.revision, use_generated_caption=True))
        assert result.caption == result.proposal and not result.caption_edited
    service.finish(owner, batch_id)
    save_rules(service, [])
    restored = service.refresh_caption_suggestion(owner, batch_id, photo.id, result.revision)
    assert restored.proposal == "Alex Example (12, Example Club)"
    assert not service.sessions.get(owner, batch_id)["available"]


def test_discipline_preview_is_bound_to_the_caption_preferences_revision(environment):
    service, _ = environment
    batch = named_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    request = DisciplineAssignment(
        discipline="long_jump", photos=[Selection(photo_id=p.id, revision=p.revision) for p in batch.photos]
    )
    names = save_rules(service)
    preview = service.preview_discipline(owner, batch_id, request)
    assert preview.caption_names_revision == names.revision
    assert "Alex van Example" in preview.photos[0].after_caption
    confirmed = request.model_copy(update={"caption_names_revision": preview.caption_names_revision})
    save_rules(service, [])
    with pytest.raises(Conflict, match="overrides changed"):
        service.assign_discipline(owner, batch_id, confirmed)
    assert service.store.get(owner, batch_id) == batch


def test_face_propagation_changes_caption_names_but_not_saved_identities(environment):
    service, _ = environment
    batch, request = prepare(service, count=2)
    owner, batch_id = batch.album.owner_id, batch.album.id
    save_rules(service, [{"source_name": "Taylor Visitor", "caption_name": "Taylor van Visitor"}])
    preview = service.preview_propagation(owner, batch_id, request)
    assert "Taylor van Visitor" in preview.candidates[0].proposed_caption
    applied = PropagationApply(
        **request.model_dump(exclude={"caption_names_revision"}),
        caption_names_revision=preview.caption_names_revision,
        targets=[preview.candidates[0].target],
    )
    result = service.propagate(owner, batch_id, applied)[0]
    assert result.analysis.record.subjects[0].athlete.value.name == "Taylor Visitor"
    assert "Taylor van Visitor" in result.caption
    save_rules(service, [])
    with pytest.raises(Conflict, match="overrides changed"):
        service.propagate(owner, batch_id, applied)


def test_accounts_only_read_and_write_their_own_name_overrides(accounts):
    app, _, _, _ = accounts
    with setup(app) as admin:
        member, _ = invite(admin, app)
        with member, TestClient(app, headers=HEADERS) as visitor:
            assert visitor.get("/api/account/caption-names").status_code == 401
            result = member.put("/api/account/caption-names", json={"revision": 0, "overrides": [RULE]})
            assert result.status_code == 200 and result.json()["revision"] == 1
            assert admin.get("/api/account/caption-names").json()["overrides"] == []
            assert member.get("/api/account/caption-names").json()["overrides"] == [RULE]
            assert member.put("/api/account/caption-names", json={"revision": 0, "overrides": []}).status_code == 409
            assert (
                member.put(
                    "/api/account/caption-names",
                    json={"revision": 1, "overrides": []},
                    headers={"X-Requested-With": ""},
                ).status_code
                == 403
            )
            assert (
                member.put("/api/account/caption-names", json={"revision": 1, "overrides": [RULE, RULE]}).status_code
                == 422
            )
            assert member.put("/api/admin/settings", json={}).status_code == 403


def test_name_overrides_are_included_in_the_account_backup(environment, tmp_path):
    service, _ = environment
    analyzed(service)
    names = save_rules(service)
    archive = tmp_path / "caption-names.snbak"
    backup(service.store, service.settings, archive)
    settings = replace(
        service.settings, blob_root=tmp_path / "restored", database_url="sqlite:///" + str(tmp_path / "restored.db")
    )
    engine = create_engine(settings.database_url)
    try:
        restore(engine, settings, archive, migrate=migrate)
        assert caption_preferences(Store(engine), settings.owner_id) == names
        assert effective_settings(Store(engine), settings).max_file_bytes == service.settings.max_file_bytes
    finally:
        engine.dispose()
