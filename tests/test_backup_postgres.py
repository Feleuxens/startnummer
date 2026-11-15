"""Opt-in backup consistency and restore checks in random PostgreSQL schemas."""

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from uuid import uuid4
from zipfile import ZipFile

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from startnummer.adapters.db.store import Store
from startnummer.app.backup import backup, restore
from startnummer.app.contracts import Edit
from startnummer.app.manage import migrate
from tests.test_database_integration import postgres as postgres
from tests.test_workflow import analyzed
from tests.test_workflow import environment as environment


def test_online_backup_blocks_caption_changes_keeps_heartbeats_alive_and_restores(
    postgres, environment, tmp_path, monkeypatch
):
    service, _ = environment
    migrate(postgres.engine)
    service.store = postgres
    batch = analyzed(service)
    owner, batch_id, photo = batch.album.owner_id, batch.album.id, batch.photos[0]
    active = analyzed(service)
    service.analyze(owner, active.album.id)
    before = postgres.get(owner, batch_id)
    entered, release = threading.Event(), threading.Event()
    original = ZipFile.open

    def paused(archive, name, mode="r", *args, **kwargs):
        if mode == "w" and getattr(name, "filename", name).startswith("photos/"):
            entered.set()
            assert release.wait(10)
        return original(archive, name, mode, *args, **kwargs)

    archive = tmp_path / "postgres.snbak"
    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=2) as executor:
        patch.setattr(ZipFile, "open", paused)
        copying = executor.submit(backup, postgres, service.settings, archive)
        assert entered.wait(5)
        editing = executor.submit(
            service.edit,
            owner,
            batch_id,
            photo.id,
            Edit(revision=before.photos[0].revision, caption="Changed after snapshot"),
        )
        try:
            with pytest.raises(TimeoutError):
                editing.result(timeout=0.1)
            job = postgres.claim()
            assert job is not None
            assert postgres.heartbeat(job, 90, 0, "test")
        finally:
            release.set()
        assert copying.result(timeout=5)["photos"] == 4
        editing.result(timeout=5)
    schema = "sn_restore_test_" + uuid4().hex
    with postgres.engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(postgres.engine.url).update_query_dict({"options": "-csearch_path=" + schema})
    engine = create_engine(url)
    settings = replace(service.settings, blob_root=tmp_path / "pg-restored-photos")
    try:
        restore(engine, settings, archive, migrate=migrate)
        recovered = Store(engine).get(owner, batch_id)
        assert recovered == before
        assert Store(engine).jobs(owner, active.album.id)[0].state == "cancelled"
        assert postgres.get(owner, batch_id).photos[0].caption == "Changed after snapshot"
    finally:
        engine.dispose()
        with postgres.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
