"""Analysis worker and in-memory face-session service."""

import argparse
import hmac
import json
import os
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from sqlalchemy import create_engine

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.adapters.runtime import Backend, BackendUnavailable
from startnummer.app.captions import caption_overrides
from startnummer.app.inference import InlineAnalyzer, ProcessAnalyzer
from startnummer.app.services import Services, run
from startnummer.core.batch import AnalysisDocument, Conflict, Job, WorkflowError
from startnummer.core.enums import Status
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import get


class Worker:
    def __init__(
        self,
        store,
        blobs,
        sessions,
        detector=None,
        ocr=None,
        faces=None,
        lease_seconds=90,
        *,
        analyzer=None,
        stopped=None,
    ):
        self.store, self.blobs, self.sessions = store, blobs, sessions
        if analyzer is not None and any(adapter is not None for adapter in (detector, ocr, faces)):
            raise ValueError("Use either an analyzer or injected adapters")
        if analyzer is None and (detector is None or ocr is None):
            raise ValueError("Provide an analyzer or detector/OCR adapters")
        self.analyzer = analyzer if analyzer is not None else InlineAnalyzer(detector, ocr, faces)
        self.lease_seconds = lease_seconds
        self.stopped = stopped if stopped is not None else threading.Event()
        self.state = "idle"

    def run_once(self) -> bool:
        job = self.store.claim(self.lease_seconds)
        if job is None:
            self.sessions.expire()
            return False
        self.state = "busy"
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
            self.sessions.finish(job.owner_id, job.batch_id, run_id=str(job.lease_token))
            self.store.fail(
                job, str(exc) if isinstance(exc, BackendUnavailable) else f"Analysis job failed ({type(exc).__name__})"
            )
        finally:
            stopped.set()
            renewal.join(timeout=5)
            self.state = "idle"
        return True

    def _execute(self, job: Job, progress, lost):
        batch = self.store.get(job.owner_id, job.batch_id)
        _, names = caption_overrides(self.store, job.owner_id)
        results, geometry = {}, {}
        with TemporaryDirectory(prefix="startnummer-worker-") as directory:
            paths, staged = [], []
            for photo in batch.photos:
                if lost.is_set() or self.stopped.is_set():
                    raise Conflict("Worker lease was lost")
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
                if lost.is_set() or self.stopped.is_set():
                    raise Conflict("Worker lease was lost")
                progress.update(completed=completed + len(batch.photos) - len(staged), phase=phase)
                if not self.store.heartbeat(job, self.lease_seconds, progress["completed"], phase):
                    lost.set()
                    raise Conflict("Worker lease was lost")

            output = self.analyzer(
                batch.album,
                paths,
                entry_list=batch.roster if batch.roster.athletes else None,
                on_progress=on_progress,
            )
            geometry = {
                str(staged[index].id): [face.model_dump(mode="json") for face in values]
                for index, values in output.geometry.items()
            }
            records = output.records
            for photo, record in zip(staged, records, strict=True):
                record.source_path = None
                results[photo.id] = AnalysisDocument(record=record)
        if lost.is_set() or self.stopped.is_set():
            raise Conflict("Worker lease was lost")

        _, options = self.store.installation_settings(job.owner_id)

        def merge(current):
            retained = Services.merge_analysis(current, results, names)
            for photo_id in retained:
                # A retained manual layout may not align with fresh detections.
                geometry.pop(str(photo_id), None)
            # Hold the batch lock while exposing face geometry so completion
            # cannot recreate a session that review has already closed.
            self.sessions.ttl = options.get("session_ttl", self.sessions.ttl)
            self.sessions.put(job.owner_id, job.batch_id, geometry, run_id=str(job.lease_token))

        self.store.complete(job, merge)


def session_server(sessions: FaceSessions, secret: str, port: int, *, state=None, host="127.0.0.1"):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log transient face payloads or authorization headers.

        def do_GET(self):
            self.handle_session(False)

        def do_DELETE(self):
            self.handle_session(True)

        def do_POST(self):
            self.handle_session(False, edit=True)

        def handle_session(self, finish, edit=False):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + secret):
                self.send_error(401)
                return
            if self.path == "/health" and self.command == "GET":
                data = json.dumps({"state": state() if state else "idle", "active_sessions": sessions.count()}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
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
            status = 200
            result = sessions.get(owner, batch)
            if edit:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 10 * 1024 * 1024:
                        raise ValueError
                    payload = json.loads(self.rfile.read(length))
                    session_id = payload["session_id"]
                    if payload["action"] == "remember":
                        result = {"undo_id": sessions.remember(owner, batch, session_id, payload["changes"])}
                    elif payload["action"] == "undo":
                        result = {
                            "changes": sessions.undo(
                                owner, batch, session_id, payload["undo_id"], consume=payload.get("consume", False)
                            )
                        }
                    else:
                        raise ValueError
                except WorkflowError as exc:
                    status, result = 409, {"detail": str(exc)}
                except (ValueError, KeyError, TypeError):
                    status, result = 400, {"detail": "Invalid face-session request"}
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def service_actions(self):
            sessions.expire()

    return Server((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="Process one job; face sessions end when this command exits"
    )
    parser.add_argument("--no-faces", action="store_true")
    parser.add_argument("--check-backend", action="store_true", help="Run synthetic inference without a database")
    parser.add_argument(
        "--backend", choices=list(Backend), default=os.environ.get("STARTNUMMER_INFERENCE_BACKEND", "auto")
    )
    parser.add_argument("--cache-mb", type=int, default=512, help="Maximum decoded-image cache size in MiB")
    args = parser.parse_args()
    if args.cache_mb < 0:
        parser.error("--cache-mb must be nonnegative")
    if args.check_backend:
        from startnummer.app.check_backend import check_backend

        try:
            check_backend(args.backend, args.cache_mb, not args.no_faces)
        except WorkflowError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from None
        return
    store = Store(create_engine(os.environ["STARTNUMMER_DATABASE_URL"], pool_pre_ping=True))
    blobs = FilesystemBlobStore.from_env()
    secret = os.environ["STARTNUMMER_WORKER_SECRET"]
    if len(secret) < 32:
        raise ValueError("Worker secret must contain at least 32 characters")
    sessions = FaceSessions(int(os.environ.get("STARTNUMMER_FACE_SESSION_TTL", "3600")))
    stopped = threading.Event()
    worker = Worker(
        store,
        blobs,
        sessions,
        analyzer=ProcessAnalyzer(args.cache_mb, not args.no_faces, backend=args.backend),
        stopped=stopped,
    )
    server = session_server(
        sessions,
        secret,
        int(os.environ.get("STARTNUMMER_WORKER_PORT", "8766")),
        state=lambda: worker.state,
        host=os.environ.get("STARTNUMMER_WORKER_HOST", "127.0.0.1"),
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    try:
        if args.once:
            worker.run_once()
        else:
            while not stopped.is_set():
                if not worker.run_once():
                    stopped.wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        sessions.clear()


if __name__ == "__main__":
    main()
