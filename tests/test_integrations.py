"""Gallery configuration precedence, credential storage, and destination safety."""

import hashlib
import json
from dataclasses import replace
from unittest.mock import MagicMock
from uuid import uuid4
from zipfile import ZipFile

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from startnummer.adapters.chevereto import Chevereto
from startnummer.adapters.db.schema import GalleryBindingRow, IntegrationRow
from startnummer.adapters.db.store import Store
from startnummer.app.api import create_app
from startnummer.app.backup import backup, restore
from startnummer.app.contracts import CheveretoConnection
from startnummer.app.integrations import Integrations
from startnummer.app.manage import migrate
from startnummer.core.batch import Conflict, DescriptionWrite, Destination, WorkflowError
from tests.test_workflow import HTML, FakeGallery, analyzed, image_bytes
from tests.test_workflow import environment as environment

KEY = Fernet.generate_key().decode()
PASSWORD = "synthetic-database-password/@"
URL = "http://gallery.test"


class Gallery(FakeGallery):
    def __init__(self, url=URL, identity="a" * 64):
        super().__init__()
        self.base_url = url
        self.actual_identity = identity
        self.identity = None
        self.allow_legacy = False
        self.probes = 0

    def probe(self):
        self.probes += 1
        return {"identity": self.actual_identity, "version": "4.5.9"}

    def album(self, url):
        name, photos = super().album(url)
        for photo in photos:
            photo.destination.gallery_identity = self.actual_identity
        return name, photos


class Factory:
    def __init__(self):
        self.gallery = Gallery()
        self.connections = []
        self.failure = False

    def __call__(self, url, dsn):
        self.connections.append((url, dsn))
        if self.failure:
            raise WorkflowError("Synthetic database unavailable")
        self.gallery.base_url = url
        return self.gallery


def configured(service, **changes):
    settings = replace(service.settings, chevereto_url=None, chevereto_dsn=None, integration_key=KEY, **changes)
    factory = Factory()
    return Integrations(service.store, settings, factory=factory), factory


def draft(**changes):
    return CheveretoConnection(
        url=URL, host="db.test", database="gallery", username="photographer", password=PASSWORD, **changes
    )


def test_encrypted_connection_survives_restart_and_preserves_password_without_echoing_it(environment):
    service, _ = environment
    manager, factory = configured(service)
    assert manager.status().editable and not manager.status().configured
    assert manager.test(draft()).version == "4.5.9"
    with service.store.transaction() as session:
        assert session.get(IntegrationRow, service.settings.owner_id) is None
        assert session.get(GalleryBindingRow, (service.settings.owner_id, URL)) is None
    status = manager.save(draft())
    assert status.configured and status.revision == 1 and status.password_set
    assert PASSWORD not in status.model_dump_json()
    with service.store.transaction() as session:
        stored = session.get(IntegrationRow, service.settings.owner_id).credentials
        assert PASSWORD not in stored and "db.test" not in stored
        decoded = json.loads(Fernet(KEY.encode()).decrypt(stored.encode()))
        assert decoded["password"] == PASSWORD
    assert factory.gallery.writes == []
    again = Integrations(service.store, manager.settings, factory=factory)
    assert again.public_url() == URL
    request = draft().model_copy(update={"revision": 1, "password": None, "port": 3307})
    assert again.save(request).revision == 2
    assert "synthetic-database-password%2F%40" in factory.connections[-1][1]
    with pytest.raises(Conflict, match="changed"):
        again.save(request)
    other = Integrations(service.store, replace(manager.settings, owner_id=uuid4()), factory=factory)
    assert not other.status().configured


@pytest.mark.parametrize("url,dsn", [(URL, None), (None, "mysql://user:password@db.test/gallery"), ("", "")])
def test_partial_environment_reserves_the_entire_connection_without_database_fallback(environment, url, dsn):
    service, _ = environment
    manager, factory = configured(service)
    manager.save(draft())
    manager = Integrations(
        service.store, replace(manager.settings, chevereto_url=url, chevereto_dsn=dsn), factory=factory
    )
    assert manager.status().source == "environment" and not manager.status().editable
    assert not manager.status().configured and manager.status().error
    assert manager.public_url() is None
    with pytest.raises(WorkflowError, match="incomplete"):
        manager.test()
    with pytest.raises(Conflict, match="environment"):
        manager.save(draft())


def test_complete_environment_takes_precedence_and_stored_settings_return_when_removed(environment):
    service, _ = environment
    manager, factory = configured(service)
    manager.save(draft())
    settings = replace(
        manager.settings, chevereto_url="http://environment.test", chevereto_dsn="mysql://env:env-secret@env.test/site"
    )
    environment_manager = Integrations(service.store, settings, factory=factory)
    status = environment_manager.status()
    assert status.source == "environment" and status.host == "env.test" and not status.editable
    assert "env-secret" not in status.model_dump_json()
    assert environment_manager.test().version == "4.5.9"
    with pytest.raises(Conflict, match="environment"):
        environment_manager.test(draft())
    assert Integrations(service.store, manager.settings, factory=factory).status().host == "db.test"


def test_key_failure_does_not_fall_back_or_prevent_environment_configuration(environment):
    service, _ = environment
    manager, factory = configured(service)
    manager.save(draft())
    for key in (None, "invalid", Fernet.generate_key().decode()):
        broken = Integrations(service.store, replace(manager.settings, integration_key=key), factory=factory)
        assert not broken.status().configured and broken.status().error
        assert broken.public_url() is None
        with pytest.raises(WorkflowError):
            broken.snapshot()
    no_key = Integrations(service.store, replace(manager.settings, integration_key=None), factory=factory)
    with pytest.raises(WorkflowError, match="INTEGRATION_KEY"):
        no_key.save(draft())


def test_identity_is_pinned_and_legacy_confirmation_preserves_review_state(environment):
    service, _ = environment
    saved = analyzed(service)
    before = service.store.get(saved.album.owner_id, saved.album.id)
    manager, factory = configured(service)
    manager.save(draft())
    assert manager.status().legacy_photos == 2 and not manager.status().legacy_confirmed
    assert not manager.snapshot().allow_legacy
    manager.confirm_legacy(1)
    assert manager.status().legacy_confirmed and manager.snapshot().allow_legacy
    assert service.store.get(saved.album.owner_id, saved.album.id) == before
    factory.gallery.actual_identity = "b" * 64
    for operation in (
        manager.snapshot,
        manager.test,
        lambda: manager.save(draft(revision=1)),
        lambda: manager.confirm_legacy(1),
    ):
        with pytest.raises(Conflict, match="different gallery"):
            operation()
    assert service.store.get(saved.album.owner_id, saved.album.id) == before
    assert factory.gallery.writes == []


def test_api_saves_are_authenticated_private_and_apply_without_restarting(environment):
    service, _ = environment
    manager, factory = configured(service)
    app = create_app(
        manager.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        fetch=service.fetch,
        integration_factory=factory,
    )
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        assert client.get("/api/admin/integrations/chevereto").status_code == 401
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        body = draft().model_dump(mode="json") | {"password": PASSWORD}
        assert client.put("/api/admin/integrations/chevereto", json=body).status_code == 403
        invalid = client.put("/api/admin/integrations/chevereto", json={**body, "host": "bad/host"}, headers=headers)
        assert invalid.status_code == 422 and PASSWORD not in invalid.text and "bad/host" not in invalid.text
        response = client.put("/api/admin/integrations/chevereto", json=body, headers=headers)
        assert response.status_code == 200 and PASSWORD not in response.text
        assert response.headers["cache-control"] == "no-store, private"
        assert client.get("/api/session").json()["gallery_url"] == URL
        imported = client.post(
            "/api/batches",
            data={"gallery_url": URL + "/album/a"},
            files={"roster_file": ("roster.html", HTML, "text/html")},
            headers=headers,
        )
        assert imported.status_code == 200
        assert all(photo["destination"]["gallery_identity"] == "a" * 64 for photo in imported.json()["photos"])
        assert factory.gallery.writes == []


def test_backup_excludes_connections_and_keys_but_preserves_identity_bindings(environment, tmp_path):
    service, _ = environment
    saved = analyzed(service)
    manager, factory = configured(service)
    manager.save(draft())
    manager.confirm_legacy(1)
    archive = tmp_path / "integrations.snbak"
    backup(service.store, manager.settings, archive)
    with ZipFile(archive) as handle:
        content = handle.read("database.json").decode()
        assert "sn_integrations" not in content and PASSWORD not in content and KEY not in content
        assert "sn_gallery_bindings" in content
    target = replace(
        manager.settings, database_url="sqlite:///" + str(tmp_path / "restore.db"), blob_root=tmp_path / "restored"
    )
    engine = create_engine(target.database_url)
    restore(engine, target, archive, migrate=migrate)
    restored = Integrations(Store(engine), target, factory=factory)
    assert not restored.status().configured
    assert Store(engine).get(saved.album.owner_id, saved.album.id) == service.store.get(
        saved.album.owner_id, saved.album.id
    )
    restored.save(draft())
    assert restored.status().legacy_confirmed
    engine.dispose()


def adapter_database(monkeypatch, *, salt="synthetic-site-salt", version="4.5.9"):
    db, cursor = MagicMock(), MagicMock()
    db.__enter__.return_value = db
    db.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = [
        {"variable_name": name, "variable_value": value}
        for name, value in {
            "crypt_salt": salt,
            "id_padding": "0",
            "chevereto_version_installed": version,
        }.items()
    ]
    cursor.fetchone.return_value = {"image_description": None}
    monkeypatch.setattr(Chevereto, "connect", lambda self: db)
    return cursor


def test_adapter_probe_is_read_only_and_never_exposes_salt(monkeypatch):
    cursor = adapter_database(monkeypatch)
    gallery = Chevereto(URL, "mysql://test:secret@db.test/gallery")
    info = gallery.probe()
    assert info == {"version": "4.5.9", "identity": hashlib.sha256(b"chevereto:synthetic-site-salt").hexdigest()}
    assert "synthetic-site-salt" not in json.dumps(info)
    assert all(call.args[0].startswith("SELECT ") for call in cursor.execute.call_args_list)


@pytest.mark.parametrize("identity,allow_legacy", [(None, False), ("b" * 64, False)])
def test_adapter_blocks_unconfirmed_or_wrong_gallery_before_reading_descriptions(monkeypatch, identity, allow_legacy):
    cursor = adapter_database(monkeypatch)
    gallery = Chevereto(URL, "mysql://test:secret@db.test/gallery", allow_legacy=allow_legacy)
    change = DescriptionWrite(
        destination=Destination(instance=URL, image_id=1, page_url=URL + "/image/1", gallery_identity=identity),
        expected=None,
        replacement="Synthetic caption",
    )
    assert gallery.inspect(change).state == "failure"
    assert gallery.write(change).state == "failure"
    assert all("image_description" not in call.args[0] for call in cursor.execute.call_args_list)


def test_unused_connection_can_be_corrected_to_a_different_database(environment):
    service, _ = environment
    manager, factory = configured(service)
    manager.save(draft())
    factory.gallery.actual_identity = "b" * 64
    assert manager.test().version == "4.5.9"
    manager.save(draft(revision=1))
    assert manager.snapshot().identity == "b" * 64


def test_original_format_backups_can_still_be_restored(environment, tmp_path):
    service, _ = environment
    saved = analyzed(service)
    source = tmp_path / "current.snbak"
    backup(service.store, service.settings, source)
    with ZipFile(source) as original:
        entries = {name: original.read(name) for name in original.namelist()}
    document = json.loads(entries["database.json"])
    document["tables"].pop("sn_gallery_bindings")
    data = json.dumps(document).encode()
    entries["database.json"] = data
    manifest = json.loads(entries["manifest.json"])
    manifest["format"] = 1
    manifest["files"]["database.json"] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    entries["manifest.json"] = json.dumps(manifest).encode()
    legacy = tmp_path / "original.snbak"
    with ZipFile(legacy, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    settings = replace(
        service.settings,
        database_url="sqlite:///" + str(tmp_path / "old-format.db"),
        blob_root=tmp_path / "old-format-photos",
    )
    engine = create_engine(settings.database_url)
    assert restore(engine, settings, legacy, migrate=migrate)["format"] == 1
    assert Store(engine).get(saved.album.owner_id, saved.album.id) == saved
    engine.dispose()


@pytest.mark.parametrize("outside_gallery", [False, True])
def test_configured_gallery_snapshot_controls_photo_fetches_without_environment_url(
    environment, monkeypatch, outside_gallery
):
    service, _ = environment
    manager, factory = configured(service)
    manager.save(draft())
    if outside_gallery:
        original = factory.gallery.album

        def album(url):
            name, photos = original(url)
            photos[0].source_url = "http://unconfigured.test/image.jpg"
            return name, photos

        factory.gallery.album = album
    stream = MagicMock()
    stream.return_value.__enter__.return_value.iter_bytes.return_value = [image_bytes()]
    monkeypatch.setattr("startnummer.app.services.httpx.stream", stream)
    app = create_app(
        manager.settings,
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        integration_factory=factory,
    )

    def import_photos():
        return app.state.services.import_batch(
            manager.settings.owner_id, "Dynamic gallery", None, [], URL + "/album/a", HTML, None
        )

    if outside_gallery:
        with pytest.raises(WorkflowError, match="configured source"):
            import_photos()
        stream.assert_not_called()
    else:
        batch = import_photos()
        assert len(batch.photos) == 2
        assert all(photo.destination.gallery_identity == "a" * 64 for photo in batch.photos)
        assert [call.args[1] for call in stream.call_args_list] == [URL + "/images/1.jpg", URL + "/images/2.jpg"]
