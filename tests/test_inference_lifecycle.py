"""Process lifetime, cache cleanup, and temporary review memory."""

import gc
import json
import multiprocessing
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from queue import Empty
from uuid import UUID, uuid4

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
from tests.inference_fixture import (
    DecodedImage,
    blocked_models,
    crashed_models,
    failed_models,
    gated_models,
    retaining_models,
    unavailable_models,
)
from tests.test_accounts import accounts as accounts
from tests.test_accounts import imported, invite, setup
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


def test_safe_configuration_error_reaches_job_without_private_runtime_errors(environment):
    service, _ = environment
    batch = import_batch(service)
    worker = Worker(
        service.store, service.blobs, service.sessions, analyzer=ProcessAnalyzer(factory=unavailable_models)
    )
    service.analyze(batch.album.owner_id, batch.album.id)
    assert worker.run_once()
    assert (
        service.store.jobs(batch.album.owner_id, batch.album.id)[0].error
        == "CUDA is unavailable; check the device profile"
    )
    assert not service.sessions.get(batch.album.owner_id, batch.album.id)["available"]


def test_worker_stop_interrupts_inference_and_releases_staging(environment):
    service, _ = environment
    batch = import_batch(service)
    stopped = threading.Event()

    class StoppingAnalyzer(RecordingAnalyzer):
        def __call__(self, *args, on_progress, **kwargs):
            def stop_on_progress(*values):
                stopped.set()
                on_progress(*values)

            return super().__call__(*args, on_progress=stop_on_progress, **kwargs)

    runner = StoppingAnalyzer(factory=blocked_models)
    worker = Worker(service.store, service.blobs, service.sessions, analyzer=runner, stopped=stopped)
    service.analyze(batch.album.owner_id, batch.album.id)
    assert worker.run_once()
    assert runner.pids and runner.process is None
    assert all(process_identity(pid) is None for pid in runner.pids)
    assert all(not Path(path).exists() for path in runner.paths)
    assert service.store.jobs(batch.album.owner_id, batch.album.id)[0].state == "queued"
    assert not service.sessions.get(batch.album.owner_id, batch.album.id)["available"]


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


def test_live_album_limit_runs_distinct_children_and_keeps_their_review_sessions(accounts):
    app, _, settings, sessions = accounts
    with setup(app) as admin:
        member, _ = invite(admin, app)
        with member:
            batch_clients = [(imported(client), client) for client in (admin, member, admin)]
            for batch, client in batch_clients:
                assert client.post(f"/api/batches/{batch['album']['id']}/analysis").status_code == 200

            batches = [(UUID(batch["album"]["owner_id"]), UUID(batch["album"]["id"])) for batch, _ in batch_clients]
            photos = [batch["photos"][0]["id"] for batch, _ in batch_clients]
            context = multiprocessing.get_context("spawn")
            gates = {photo: context.Event() for photo in photos}
            started = context.Queue()
            service = app.state.services
            runner = ProcessAnalyzer(factory=partial(gated_models, gates, started))
            worker = Worker(service.store, service.blobs, sessions, analyzer=runner)
            options = {
                "revision": 0,
                "max_file_bytes": settings.max_file_bytes,
                "max_batch_bytes": settings.max_batch_bytes,
                "session_ttl": settings.session_ttl,
            }

            def set_limit(limit):
                response = admin.put("/api/admin/settings", json={**options, "max_concurrent_jobs": limit})
                assert response.status_code == 200, response.text
                options.update(response.json())

            def job_states():
                return [service.store.jobs(owner, batch)[0].state for owner, batch in batches]

            def wait_for_states(expected):
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if job_states() == expected:
                        return
                    time.sleep(0.05)
                assert job_states() == expected

            pids = []
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    dispatcher = pool.submit(worker.run)
                    try:
                        first, pid = started.get(timeout=10)
                        pids.append(pid)
                        assert first == photos[0] and job_states() == ["running", "queued", "queued"]
                        set_limit(2)
                        second, pid = started.get(timeout=10)
                        pids.append(pid)
                        assert second == photos[1] and job_states() == ["running", "running", "queued"]
                        assert len(set(pids)) == 2 and all(process_identity(pid) for pid in pids)

                        set_limit(1)
                        gates[first].set()
                        wait_for_states(["done", "running", "queued"])
                        assert worker.state == "busy" and sessions.get(*batches[0])["available"]
                        with pytest.raises(Empty):
                            started.get(timeout=1.3)

                        gates[second].set()
                        third, pid = started.get(timeout=10)
                        pids.append(pid)
                        gates[third].set()
                        assert third == photos[2]
                        wait_for_states(["done", "done", "done"])
                        assert all(sessions.get(*batch)["available"] for batch in batches)
                    finally:
                        worker.stopped.set()
                        dispatcher.result(timeout=10)
            finally:
                started.close()
                started.join_thread()
            assert worker.state == "idle" and all(process_identity(pid) is None for pid in pids)


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


def test_portable_guard_terminates_inference_after_parent_death():
    parent = subprocess.Popen(
        [sys.executable, "-m", "tests.parent_guard_fixture"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    watched = {}
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(parent.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=10)
        data = json.loads(parent.stdout.readline())
        watched = {data[key]: process_identity(data[key]) for key in ("inference_pid", "guardian_pid")}
        assert all(watched.values())
        parent.kill()
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while (
            any(process_identity(pid) == identity for pid, identity in watched.items()) and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        assert all(process_identity(pid) is None for pid in watched)
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        parent.stdout.close()
        for pid, identity in watched.items():
            if identity is not None and process_identity(pid) == identity:
                os.kill(pid, signal.SIGKILL)


def test_face_session_expires_after_suspend_without_monotonic_progress(monkeypatch):
    owner, batch = uuid4(), uuid4()
    sessions = FaceSessions(30)
    wall, monotonic = time.time(), time.monotonic()
    monkeypatch.setattr("startnummer.adapters.face.sessions.time.monotonic", lambda: monotonic)
    monkeypatch.setattr("startnummer.adapters.face.sessions.time.time", lambda: wall)
    sessions.put(owner, batch, {"synthetic": [{"subject": 0, "box": [0, 0, 1, 1]}]})
    session = sessions.get(owner, batch)
    sessions.remember(owner, batch, session["session_id"], [{"synthetic": True}])
    monkeypatch.setattr("startnummer.adapters.face.sessions.time.time", lambda: wall + 31)
    assert not sessions.get(owner, batch)["available"]
    assert not sessions._items and not sessions._undo
