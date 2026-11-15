"""Administrator boundaries, live settings, and private worker health."""

import threading
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from fastapi.testclient import TestClient
from pydantic import ValidationError

from startnummer.app.api import create_app
from startnummer.app.contracts import RuntimeSettings
from startnummer.app.operations import effective_settings, runtime_settings, worker_health
from startnummer.app.worker import Worker, session_server
from startnummer.core.batch import Conflict
from tests.test_workflow import Detector, Faces, Ocr, import_batch
from tests.test_workflow import environment as environment


def test_settings_are_persistent_owner_scoped_and_revision_checked(environment):
    service, _ = environment
    owner = service.settings.owner_id
    current = runtime_settings(service.store, service.settings)
    assert current.revision == 0 and current.session_ttl == 3600
    document = current.model_copy(update={"session_ttl": 120}).model_dump(exclude={"revision"})
    assert service.store.save_settings(owner, 0, document) == 1
    assert effective_settings(service.store, service.settings).session_ttl == 120
    assert service.store.runtime_settings(uuid4()) == (0, {})
    with pytest.raises(Conflict, match="changed"):
        service.store.save_settings(owner, 0, document)
    for invalid in [
        {**document, "session_ttl": 0},
        {**document, "database_url": "not-editable"},
        {**document, "max_batch_bytes": 1},
    ]:
        with pytest.raises(ValidationError):
            RuntimeSettings.model_validate(invalid)


def test_new_session_uses_new_lifetime_without_extending_existing_session(environment):
    service, _ = environment
    first = import_batch(service)
    worker = Worker(service.store, service.blobs, service.sessions, Detector(), Ocr(), Faces())
    service.analyze(service.settings.owner_id, first.album.id)
    worker.run_once()
    before = service.sessions.get(first.album.owner_id, first.album.id)
    options = runtime_settings(service.store, service.settings).model_copy(update={"session_ttl": 120})
    service.store.save_settings(service.settings.owner_id, 0, options.model_dump(exclude={"revision"}))
    second = import_batch(service)
    service.analyze(service.settings.owner_id, second.album.id)
    worker.run_once()
    after = service.sessions.get(first.album.owner_id, first.album.id)
    assert after["expires_at"] == pytest.approx(before["expires_at"], abs=0.01)
    assert service.sessions.get(second.album.owner_id, second.album.id)["expires_at"] < before["expires_at"] - 3000


def test_admin_authentication_settings_limits_and_health_without_secrets(environment):
    service, _ = environment
    app = create_app(
        replace(service.settings, worker_url="http://127.0.0.1:1"),
        store=service.store,
        blobs=service.blobs,
        sessions=service.sessions,
        gallery=service.gallery,
        fetch=service.fetch,
    )
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        assert client.get("/api/health/live").json() == {"alive": True}
        assert client.get("/api/health/ready").status_code == 200
        assert client.get("/api/admin").status_code == 401
        response = client.post(
            "/api/session", headers=headers, json={"username": "photographer", "password": "test-password"}
        )
        assert response.json()["is_admin"]
        response = client.get("/api/admin")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, private"
        for secret in [
            service.settings.password,
            service.settings.worker_secret,
            service.settings.session_secret,
            str(service.settings.blob_root),
        ]:
            assert secret not in response.text
        body = response.json()["settings"]
        body["session_ttl"] = 180
        assert client.put("/api/admin/settings", json=body).status_code == 403
        assert (
            client.put("/api/admin/settings", json={**body, "owner_id": str(uuid4())}, headers=headers).status_code
            == 422
        )
        assert client.put("/api/admin/settings", json=body, headers=headers).json()["revision"] == 1
        assert client.put("/api/admin/settings", json=body, headers=headers).status_code == 409
        assert runtime_settings(service.store, service.settings).session_ttl == 180


def test_runtime_limits_are_used_by_imports(environment):
    service, _ = environment
    options = runtime_settings(service.store, service.settings)
    document = options.model_copy(update={"max_file_bytes": 1024 * 1024, "max_batch_bytes": 1024 * 1024})
    service.store.save_settings(service.settings.owner_id, 0, document.model_dump(exclude={"revision"}))
    # Saved limits take precedence over startup defaults.
    assert effective_settings(service.store, service.settings).max_batch_bytes == 1024 * 1024
    settings = replace(service.settings, max_batch_bytes=1)
    assert effective_settings(service.store, settings).max_batch_bytes == 1024 * 1024
    assert import_batch(service).photos


def test_worker_health_is_private_and_does_not_expose_face_payloads(environment):
    service, _ = environment
    batch = import_batch(service)
    service.sessions.put(batch.album.owner_id, batch.album.id, {str(batch.photos[0].id): [{"box": [1, 2, 3, 4]}]})
    server = session_server(service.sessions, "test-secret", 0, state=lambda: "busy")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        assert httpx.get(url + "/health", trust_env=False).status_code == 401
        health = worker_health(url, "test-secret")
        assert health.reachable and health.state == "busy" and health.active_sessions == 1
        assert "box" not in health.model_dump_json() and "session_id" not in health.model_dump_json()
        assert not worker_health(url, "wrong-secret").reachable
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
