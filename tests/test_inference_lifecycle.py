"""Process lifetime, cache cleanup, and temporary review memory."""

import gc
import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from startnummer.adapters.cache import DEFAULT_CACHE, ImageCache
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.inference import InlineAnalyzer, ProcessAnalyzer
from startnummer.app.manage import process_identity
from startnummer.app.worker import Worker
from startnummer.core.batch import Conflict
from startnummer.core.enums import Sport
from startnummer.core.interfaces import EntryList
from startnummer.core.record import Album
from tests.inference_fixture import DecodedImage, crashed_models, failed_models, retaining_models
from tests.test_workflow import Detector, Faces, Ocr, image_bytes, import_batch
from tests.test_workflow import environment as environment


class RecordingAnalyzer(ProcessAnalyzer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pids = set()
        self.paths = []

    def __call__(self, *args, on_progress, **kwargs):
        self.paths.extend(args[1])

        def progress(*values):
            self.pids.add(self.process.pid)
            on_progress(*values)

        return super().__call__(*args, on_progress=progress, **kwargs)


def test_inference_exits_before_review_and_preserves_other_active_sessions(environment):
    service, _ = environment
    runner = RecordingAnalyzer(factory=retaining_models)
    worker = Worker(service.store, service.blobs, service.sessions, analyzer=runner)
    batches = [import_batch(service), import_batch(service)]
    for batch in batches:
        service.analyze(batch.album.owner_id, batch.album.id)
        assert worker.run_once()
        assert runner.process is None
        assert all(not Path(path).exists() for path in runner.paths)
        assert runner.pids and all(process_identity(pid) is None for pid in runner.pids)
        assert service.store.jobs(batch.album.owner_id, batch.album.id)[0].state == "done"
        session = service.sessions.get(batch.album.owner_id, batch.album.id)
        assert session["available"] and session["photos"]
        assert "embedding" not in json.dumps(session)
        saved = service.store.get(batch.album.owner_id, batch.album.id)
        assert "embedding" not in saved.model_dump_json()
        assert all(photo.analysis.record.source_path is None for photo in saved.photos)
    assert len(runner.pids) == 2
    first, second = batches
    service.finish(first.album.owner_id, first.album.id)
    assert not service.sessions.get(first.album.owner_id, first.album.id)["available"]
    assert service.sessions.get(second.album.owner_id, second.album.id)["available"]
    service.sessions.clear()
    assert service.sessions.count() == 0 and worker.state == "idle"
    assert all(process_identity(pid) is None for pid in runner.pids)


@pytest.mark.parametrize("factory", [failed_models, crashed_models])
def test_failed_inference_has_no_live_child_or_review_session(environment, factory):
    service, _ = environment
    batch = import_batch(service)
    runner = RecordingAnalyzer(factory=factory)
    worker = Worker(service.store, service.blobs, service.sessions, analyzer=runner)
    service.analyze(batch.album.owner_id, batch.album.id)
    assert worker.run_once()
    assert runner.process is None and all(process_identity(pid) is None for pid in runner.pids)
    assert not service.sessions.get(batch.album.owner_id, batch.album.id)["available"]
    job = service.store.jobs(batch.album.owner_id, batch.album.id)[0]
    assert job.state == "queued"
    assert "synthetic-private-data" not in job.error
    assert worker.state == "idle"


def test_cancellation_stops_child_before_leaving_staging(environment):
    service, _ = environment
    batch = import_batch(service)
    runner = RecordingAnalyzer(factory=retaining_models)
    worker = Worker(service.store, service.blobs, service.sessions, analyzer=runner)
    service.analyze(batch.album.owner_id, batch.album.id)
    original = service.store.heartbeat
    cancelled = False

    def cancel_at_progress(job, *args):
        nonlocal cancelled
        if threading.current_thread() is threading.main_thread() and runner.process is not None and not cancelled:
            cancelled = True
            service.cancel_analysis(batch.album.owner_id, batch.album.id)
        return original(job, *args)

    service.store.heartbeat = cancel_at_progress
    assert worker.run_once()
    assert cancelled and runner.process is None
    assert all(not Path(path).exists() for path in runner.paths)
    assert all(process_identity(pid) is None for pid in runner.pids)
    assert service.store.jobs(batch.album.owner_id, batch.album.id)[0].state == "cancelled"
    assert not service.sessions.get(batch.album.owner_id, batch.album.id)["available"]


def test_inline_analysis_releases_decoded_images_on_error(tmp_path, monkeypatch):
    cache = ImageCache(decode=lambda _: DecodedImage())
    image = cache.load("synthetic")
    ref = weakref.ref(image)
    del image
    detector = Detector()
    detector._cache = cache
    runner = InlineAnalyzer(detector, Ocr(), Faces())
    path = tmp_path / "photo.jpg"
    path.write_bytes(image_bytes())
    album = Album(owner_id=uuid4(), name="Synthetic", sport=Sport.ATHLETICS)

    def cancelled(*args):
        raise Conflict("Cancelled")

    with pytest.raises(Conflict):
        runner(album, [str(path)], entry_list=EntryList(athletes=[]), on_progress=cancelled)
    gc.collect()
    assert ref() is None
    assert "0 MB held" in cache.stats()
    assert "0 MB held" in DEFAULT_CACHE.stats()


def test_clear_during_decode_does_not_repopulate_the_cache():
    decoding, resume = threading.Event(), threading.Event()

    def decode(path):
        decoding.set()
        assert resume.wait(5)
        return DecodedImage()

    cache = ImageCache(decode=decode)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cache.load, "synthetic")
        assert decoding.wait(5)
        cache.clear()
        resume.set()
        image = future.result(timeout=5)
        ref = weakref.ref(image)
        del image, future
    gc.collect()
    assert ref() is None and "0 MB held" in cache.stats()


@pytest.mark.parametrize("action", ["finish", "expire", "clear", "replace"])
def test_review_cleanup_empties_geometry_and_undo_containers(monkeypatch, action):
    owner, batch = uuid4(), uuid4()
    sessions = FaceSessions(ttl=30)
    sessions.put(owner, batch, {"photo": [{"subject": 0, "box": [1, 2, 3, 4], "group": "synthetic"}]})
    token = sessions.get(owner, batch)["session_id"]
    sessions.remember(owner, batch, token, [{"photo_id": "synthetic", "before": {"name": "Synthetic"}}])
    geometry = sessions._items[(str(owner), str(batch))][2]
    undo = sessions._undo[(str(owner), str(batch))][2]
    if action == "expire":
        clock = time.monotonic()
        monkeypatch.setattr("startnummer.adapters.face.sessions.time.monotonic", lambda: clock + 31)
        sessions.expire()
    elif action == "replace":
        sessions.put(owner, batch, {})
    elif action == "finish":
        sessions.finish(owner, batch)
    else:
        sessions.clear()
    assert geometry == {} and undo == []
    assert sessions.count() == 0
    assert not sessions.get(owner, batch)["available"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux parent-death signal")
def test_worker_death_terminates_its_inference_child():
    parent = subprocess.Popen(
        [sys.executable, "-m", "tests.inference_fixture"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
    )
    child_pid, child_identity = None, None
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(parent.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=10), "Synthetic inference process did not start"
        child_pid = json.loads(parent.stdout.readline())["inference_pid"]
        child_identity = process_identity(child_pid)
        assert child_identity is not None
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while process_identity(child_pid) == child_identity and time.monotonic() < deadline:
            time.sleep(0.05)
        assert process_identity(child_pid) is None
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        parent.stdout.close()
        if child_pid is not None and child_identity is not None and process_identity(child_pid) == child_identity:
            os.kill(child_pid, signal.SIGKILL)
