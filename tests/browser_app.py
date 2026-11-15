"""Disposable browser-test app with fake models and an in-memory gallery writer."""

import os
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import create_engine

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.db.schema import Base
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.api import create_app
from startnummer.app.settings import Settings
from startnummer.app.worker import Worker, session_server
from startnummer.core.batch import WorkflowError
from tests.test_workflow import HTML, Detector, Faces, FakeGallery, Ocr, image_bytes


def create_fixture():
    administration = os.environ.get("STARTNUMMER_BROWSER_INTEGRATION_MODE") == "administration"
    directory = TemporaryDirectory(prefix="startnummer-browser-")
    root = Path(directory.name)
    engine = create_engine("sqlite:///" + str(root / "app.db"), connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    store = Store(engine)
    sessions = FaceSessions()
    blobs = FilesystemBlobStore(root / "photos")
    settings = Settings(
        database_url=str(engine.url),
        blob_root=root / "photos",
        owner_id=uuid4(),
        password="browser-test-only",
        session_secret="s" * 32,
        worker_secret="w" * 32,
        chevereto_url=None if administration else "http://gallery.test",
        chevereto_dsn=None if administration else "mysql://fixture:fixture-password@gallery.test/gallery",
        integration_key=Fernet.generate_key().decode() if administration else None,
        roster_hosts=("roster.test",),
    )
    worker = Worker(store, blobs, sessions, Detector(), Ocr(), Faces())
    private_server = session_server(sessions, settings.worker_secret, 0, state=lambda: worker.state)
    settings = replace(settings, worker_url=f"http://127.0.0.1:{private_server.server_port}")
    gallery = FakeGallery()

    def gallery_factory(url, dsn):
        if "unreachable.test" in dsn:
            raise WorkflowError("Could not read the Chevereto database; check the connection and schema")
        return gallery

    app = create_app(
        settings,
        store=store,
        blobs=blobs,
        sessions=sessions,
        integration_factory=gallery_factory,
        fetch=lambda url, roster=False: HTML if roster else image_bytes(),
    )
    stopped = threading.Event()

    def work():
        while not stopped.wait(0.2):
            worker.run_once()

    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        private_thread = threading.Thread(target=private_server.serve_forever, daemon=True)
        private_thread.start()
        yield
        stopped.set()
        thread.join(timeout=5)
        private_server.shutdown()
        private_server.server_close()
        private_thread.join(timeout=5)
        engine.dispose()
        directory.cleanup()

    app.router.lifespan_context = lifespan
    return app
