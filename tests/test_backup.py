"""Back up and restore synthetic records and shared blobs into empty stores."""

import json
from dataclasses import replace
from uuid import uuid4
from zipfile import ZipFile

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from sqlalchemy import create_engine, inspect, select

from startnummer.adapters.db.schema import JobRow
from startnummer.adapters.db.store import Store
from startnummer.app.backup import backup, inspect_backup, restore
from startnummer.app.contracts import Edit, Selection
from startnummer.app.manage import migrate
from startnummer.app.operations import runtime_settings
from startnummer.core.batch import Conflict, WorkflowError
from tests.test_workflow import analyzed, image_bytes
from tests.test_workflow import environment as environment


def target(service, tmp_path):
    settings = replace(
        service.settings,
        database_url="sqlite:///" + str(tmp_path / "restored.db"),
        blob_root=tmp_path / "restored-photos",
    )
    return create_engine(settings.database_url), settings


def test_roundtrip_shared_photos_review_publication_settings_and_no_face_data(environment, tmp_path):
    service, _ = environment
    batch = analyzed(service)
    owner, batch_id, photo = batch.album.owner_id, batch.album.id, batch.photos[0]
    photo = service.edit(owner, batch_id, photo.id, Edit(revision=photo.revision, caption="Reviewed caption"))
    selected = Selection(photo_id=photo.id, revision=photo.revision)
    service.approve(owner, batch_id, [selected])
    service.apply(owner, batch_id, [selected])
    options = runtime_settings(service.store, service.settings)
    service.store.save_settings(owner, 0, options.model_dump(exclude={"revision"}))
    service.sessions.put(owner, batch_id, {str(photo.id): [{"box": [1, 2, 3, 4], "group": "temporary-only"}]})
    before = service.store.get(owner, batch_id)
    archive = tmp_path / "backup.snbak"
    result = backup(service.store, service.settings, archive)
    assert result["photos"] == 2 and result["batches"] == 1
    assert archive.stat().st_mode & 0o777 == 0o600
    with ZipFile(archive) as saved:
        assert len([name for name in saved.namelist() if name.startswith("photos/")]) == 1
        metadata = saved.read("database.json").decode()
        for forbidden in ["temporary-only", '"box"', '"embedding"', '"face_session_id"', service.settings.password]:
            assert forbidden not in metadata
    assert inspect_backup(archive) == result
    engine, settings = target(service, tmp_path)
    assert restore(engine, settings, archive, migrate=migrate) == result
    recovered = Store(engine)
    assert recovered.get(owner, batch_id) == before
    with recovered.transaction() as session:
        publications = recovered.publications(session, owner, batch_id)
        assert publications[0].change.replacement == "Reviewed caption"
    assert recovered.runtime_settings(owner) == service.store.runtime_settings(owner)
    assert len(list(settings.blob_root.rglob("*"))) > 0
    assert [path.read_bytes() for path in settings.blob_root.rglob("*") if path.is_file()] == [image_bytes()]
    assert service.sessions.get(owner, batch_id)["available"]
    with pytest.raises(Conflict, match="overwrite"):
        restore(engine, settings, archive, migrate=migrate)


def test_restore_cancels_queued_or_running_jobs_but_preserves_completed_jobs(environment, tmp_path):
    service, _ = environment
    batch = analyzed(service)
    service.analyze(batch.album.owner_id, batch.album.id)
    assert service.store.claim() is not None
    archive = tmp_path / "jobs.snbak"
    backup(service.store, service.settings, archive)
    engine, settings = target(service, tmp_path)
    restore(engine, settings, archive, migrate=migrate)
    with Store(engine).transaction() as session:
        job = session.scalar(select(JobRow))
        assert job.state == "cancelled" and job.lease_token is None and job.lease_until is None
        assert "Restored from backup" in job.error
    assert Store(engine).claim() is None


def test_rejects_corruption_before_creating_target_schema_or_files(environment, tmp_path):
    service, _ = environment
    analyzed(service)
    archive = tmp_path / "backup.snbak"
    backup(service.store, service.settings, archive)
    broken = tmp_path / "broken.snbak"
    with ZipFile(archive) as source, ZipFile(broken, "w") as output:
        for name in source.namelist():
            output.writestr(name, b"corrupt" if name == "database.json" else source.read(name))
    engine, settings = target(service, tmp_path)
    with pytest.raises(WorkflowError, match="size|checksum"):
        restore(engine, settings, broken, migrate=migrate)
    assert inspect(engine).get_table_names() == []
    assert not settings.blob_root.exists()


def test_refuses_existing_files_wrong_owner_foreign_tables_and_overwritten_backup(environment, tmp_path):
    service, _ = environment
    analyzed(service)
    archive = tmp_path / "backup.snbak"
    backup(service.store, service.settings, archive)
    with pytest.raises(WorkflowError, match="exists"):
        backup(service.store, service.settings, archive)
    engine, settings = target(service, tmp_path)
    with pytest.raises(Conflict, match="another configured account"):
        restore(engine, replace(settings, owner_id=uuid4()), archive, migrate=migrate)
    settings.blob_root.mkdir()
    retained = settings.blob_root / "keep.txt"
    retained.write_text("Keep me")
    with pytest.raises(Conflict, match="empty photo"):
        restore(engine, settings, archive, migrate=migrate)
    assert retained.read_text() == "Keep me"
    retained.unlink()
    with engine.begin() as connection:
        from sqlalchemy import text

        connection.execute(text("CREATE TABLE foreign_data (id INTEGER)"))
    with pytest.raises(Conflict, match="dedicated, empty"):
        restore(engine, settings, archive, migrate=migrate)


def test_failed_restore_cleans_staging_and_original_database_is_unchanged(environment, tmp_path):
    service, _ = environment
    batch = analyzed(service)
    archive = tmp_path / "backup.snbak"
    backup(service.store, service.settings, archive)
    before = service.store.get(batch.album.owner_id, batch.album.id)
    engine, settings = target(service, tmp_path)

    def failed(_):
        raise RuntimeError("simulated migration failure")

    with pytest.raises(RuntimeError):
        restore(engine, settings, archive, migrate=failed)
    assert not list(tmp_path.glob(".startnummer-restore-*"))
    assert not settings.blob_root.exists()
    assert service.store.get(batch.album.owner_id, batch.album.id) == before


def test_path_traversal_is_rejected_even_with_a_matching_checksum(environment, tmp_path):
    service, _ = environment
    analyzed(service)
    archive = tmp_path / "backup.snbak"
    backup(service.store, service.settings, archive)
    broken = tmp_path / "paths.snbak"
    with ZipFile(archive) as source, ZipFile(broken, "w") as output:
        manifest = json.loads(source.read("manifest.json"))
        name = next(name for name in manifest["files"] if name.startswith("photos/"))
        bad = f"photos/{service.settings.owner_id}/../../escape"
        manifest["files"][bad] = manifest["files"].pop(name)
        for item in source.namelist():
            if item != "manifest.json":
                output.writestr(bad if item == name else item, source.read(item))
        output.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(WorkflowError):
        inspect_backup(broken)
    assert not (tmp_path / "escape").exists()


def test_face_records_are_rejected_even_in_an_otherwise_valid_archive(environment, tmp_path):
    import hashlib

    service, _ = environment
    analyzed(service)
    archive = tmp_path / "backup.snbak"
    backup(service.store, service.settings, archive)
    broken = tmp_path / "face-data.snbak"
    with ZipFile(archive) as original, ZipFile(broken, "w") as output:
        manifest = json.loads(original.read("manifest.json"))
        document = json.loads(original.read("database.json"))
        document["tables"]["sn_photos"][0]["document"]["embedding"] = [0.1, 0.2]
        data = json.dumps(document).encode()
        manifest["files"]["database.json"] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name in original.namelist():
            if name not in {"manifest.json", "database.json"}:
                output.writestr(name, original.read(name))
        output.writestr("database.json", data)
        output.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(WorkflowError, match="Temporary face records"):
        inspect_backup(broken)


def test_uncertain_commit_keeps_prepared_bytes_instead_of_risking_missing_references(environment, tmp_path):
    from sqlalchemy import event

    service, _ = environment
    analyzed(service)
    archive = tmp_path / "backup.snbak"
    backup(service.store, service.settings, archive)
    engine, settings = target(service, tmp_path)

    def prepare_database(engine):
        migrate(engine)

        def interrupted(_):
            raise OSError("simulated lost commit acknowledgement")

        event.listen(engine, "commit", interrupted, once=True)

    with pytest.raises(OSError, match="commit acknowledgement"):
        restore(engine, settings, archive, migrate=prepare_database)
    assert [path.read_bytes() for path in settings.blob_root.rglob("*") if path.is_file()] == [image_bytes()]
    assert not list(tmp_path.glob(".startnummer-restore-*"))
