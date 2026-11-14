"""Disposable browser-test app with fake models and an in-memory gallery writer."""

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import create_engine

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.db.schema import Base
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.api import create_app
from startnummer.app.settings import Settings
from startnummer.app.worker import Worker
from tests.test_workflow import HTML, Detector, Faces, FakeGallery, Ocr, image_bytes


def create_fixture():
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
        chevereto_url="http://gallery.test",
        roster_hosts=("roster.test",),
    )
    app = create_app(
        settings,
        store=store,
        blobs=blobs,
        sessions=sessions,
        gallery=FakeGallery(),
        fetch=lambda url, roster=False: HTML if roster else image_bytes(),
    )
    worker = Worker(store, blobs, sessions, Detector(), Ocr(), Faces())
    stopped = threading.Event()

    def work():
        while not stopped.wait(0.2):
            worker.run_once()

    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        yield
        stopped.set()
        thread.join(timeout=5)
        engine.dispose()
        directory.cleanup()

    app.router.lifespan_context = lifespan
    return app
