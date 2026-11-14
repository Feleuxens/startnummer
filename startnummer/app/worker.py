"""Analysis worker and in-memory face-session service."""

import argparse
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import create_engine

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.services import Services, run
from startnummer.core.batch import AnalysisDocument, Conflict, Job
from startnummer.core.enums import Status
from startnummer.core.pipeline import analyze_album
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import get


class Worker:
    def __init__(self, store, blobs, sessions, detector, ocr, faces=None, lease_seconds=90):
        self.store, self.blobs, self.sessions = store, blobs, sessions
        self.detector, self.ocr, self.faces = detector, ocr, faces
        self.lease_seconds = lease_seconds

    def run_once(self) -> bool:
        job = self.store.claim(self.lease_seconds)
        if job is None:
            self.sessions.expire()
            return False
        stopped = threading.Event()
        lost = threading.Event()
        progress = {"completed": 0, "phase": "staging"}

        def heartbeat():
            while not stopped.wait(max(0.1, self.lease_seconds / 3)):
                try:
                    if not self.store.heartbeat(job, self.lease_seconds, progress["completed"], progress["phase"]):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        renewal = threading.Thread(target=heartbeat, daemon=True)
        renewal.start()
        try:
            self._execute(job, progress, lost)
        except Exception as exc:
            self.sessions.finish(job.owner_id, job.batch_id)
            self.store.fail(job, f"Analysis job failed ({type(exc).__name__})")
        finally:
            stopped.set()
            renewal.join(timeout=5)
        return True

    def _execute(self, job: Job, progress, lost):
        batch = self.store.get(job.owner_id, job.batch_id)
        self.sessions.finish(job.owner_id, job.batch_id)
        results, geometry = {}, {}
        with TemporaryDirectory(prefix="startnummer-worker-") as directory:
            paths, staged = [], []
            for photo in batch.photos:
                try:
                    data = run(self.blobs.read(job.owner_id, photo.blob_key))
                    # The adapter receives generated paths, never user filenames.
                    path = Path(directory) / (str(photo.id) + ".image")
                    path.write_bytes(data)
                    paths.append(str(path))
                    staged.append(photo)
                except Exception:
                    results[photo.id] = AnalysisDocument(
                        record=AnalysisRecord(
                            owner_id=job.owner_id,
                            album_id=job.batch_id,
                            content_hash=photo.content_hash,
                            meet_name=batch.album.meet_name,
                            event=get(batch.album.sport).new_event(),
                            status=Status.FAILED,
                            failure_reason="Stored image bytes could not be staged",
                        )
                    )

            def on_progress(completed, total, phase):
                if lost.is_set():
                    raise Conflict("Worker lease was lost")
                progress.update(completed=completed + len(batch.photos) - len(staged), phase=phase)
                if not self.store.heartbeat(job, self.lease_seconds, progress["completed"], phase):
                    lost.set()
                    raise Conflict("Worker lease was lost")

            def on_faces(photo_index, subject_index, detections):
                photo = staged[photo_index]
                geometry.setdefault(str(photo.id), []).extend(
                    {"subject": subject_index, "box": list(face.box)} for face in detections
                )

            records = analyze_album(
                batch.album,
                paths,
                detector=self.detector,
                ocr=self.ocr,
                faces=self.faces,
                entry_list=batch.roster,
                on_progress=on_progress,
                on_faces=on_faces,
            )
            for photo, record in zip(staged, records, strict=True):
                record.source_path = None
                results[photo.id] = AnalysisDocument(record=record)
        if lost.is_set():
            raise Conflict("Worker lease was lost")

        def merge(current):
            retained = Services.merge_analysis(current, results)
            for photo_id in retained:
                # A retained manual layout may not align with fresh detections.
                geometry.pop(str(photo_id), None)
            # Hold the batch lock while exposing face geometry so completion
            # cannot recreate a session that review has already closed.
            self.sessions.put(job.owner_id, job.batch_id, geometry)

        self.store.complete(job, merge)


def session_server(sessions: FaceSessions, secret: str, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log transient face payloads or authorization headers.

        def do_GET(self):
            self.handle_session(False)

        def do_DELETE(self):
            self.handle_session(True)

        def handle_session(self, finish):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + secret):
                self.send_error(401)
                return
            parts = self.path.split("/")
            try:
                if len(parts) != 4 or parts[1] != "sessions":
                    raise ValueError
                owner, batch = UUID(parts[2]), UUID(parts[3])
            except ValueError:
                self.send_error(404)
                return
            if finish:
                sessions.finish(owner, batch)
            data = json.dumps(sessions.get(owner, batch)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def service_actions(self):
            sessions.expire()

    return Server(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Process one job; face sessions end when this command exits"
    )
    parser.add_argument("--no-faces", action="store_true")
    args = parser.parse_args()
    # Load ML runtimes only in the worker process.
    from startnummer.adapters.detect.yolo import YoloDetector
    from startnummer.adapters.ocr.rapid import RapidOcrReader

    store = Store(create_engine(os.environ["STARTNUMMER_DATABASE_URL"], pool_pre_ping=True))
    blobs = FilesystemBlobStore.from_env()
    secret = os.environ["STARTNUMMER_WORKER_SECRET"]
    if len(secret) < 32:
        raise ValueError("Worker secret must contain at least 32 characters")
    sessions = FaceSessions(int(os.environ.get("STARTNUMMER_FACE_SESSION_TTL", "3600")))
    faces = None
    if not args.no_faces:
        from startnummer.adapters.face.insight import InsightFaceEngine

        faces = InsightFaceEngine()
    worker = Worker(store, blobs, sessions, YoloDetector(), RapidOcrReader(), faces)
    server = session_server(sessions, secret, int(os.environ.get("STARTNUMMER_WORKER_PORT", "8766")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if args.once:
            worker.run_once()
        else:
            while True:
                if not worker.run_once():
                    time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
