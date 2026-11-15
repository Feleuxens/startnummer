"""Album inference with a disposable process and a geometry-only review result."""

import ctypes
import multiprocessing
import os
import signal
import sys
import time
from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from startnummer.adapters.cache import DEFAULT_CACHE
from startnummer.core.batch import WorkflowError
from startnummer.core.pipeline import analyze_album
from startnummer.core.record import AnalysisRecord


class ReviewFace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: int
    box: tuple[int, int, int, int]
    group: str | None


class InferenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: list[AnalysisRecord]
    geometry: dict[int, list[ReviewFace]]


def clear_image_caches(adapters):
    caches = {id(DEFAULT_CACHE): DEFAULT_CACHE}
    for adapter in adapters:
        cache = getattr(adapter, "_cache", None)
        if cache is not None:
            caches[id(cache)] = cache
    for cache in caches.values():
        cache.clear()


class InlineAnalyzer:
    """Run injected adapters; production uses ProcessAnalyzer instead."""

    def __init__(self, detector, ocr, faces=None):
        self.adapters = detector, ocr, faces

    def __call__(self, album, paths, *, entry_list, on_progress):
        geometry, groups = {}, {}

        def on_groups(clusters):
            for cluster in clusters:
                group = str(uuid4())
                for key in cluster:
                    groups[key] = group

        def on_faces(photo, subject, detections):
            geometry.setdefault(photo, []).extend(
                ReviewFace(subject=subject, box=tuple(face.box), group=groups.get((photo, subject)))
                for face in detections
            )

        try:
            records = analyze_album(
                album,
                paths,
                detector=self.adapters[0],
                ocr=self.adapters[1],
                faces=self.adapters[2],
                entry_list=entry_list,
                on_progress=on_progress,
                on_faces=on_faces,
                on_face_groups=on_groups,
            )
            for record in records:
                record.source_path = None
            return InferenceResult(records=records, geometry=geometry)
        finally:
            clear_image_caches(self.adapters)


def load_models(cache_mb, faces_enabled):
    # Native runtimes and their retained buffers belong only to the inference child.
    from startnummer.adapters.detect.yolo import YoloDetector
    from startnummer.adapters.ocr.rapid import RapidOcrReader

    DEFAULT_CACHE.set_max_mb_bytes(cache_mb)
    faces = None
    if faces_enabled:
        from startnummer.adapters.face.insight import InsightFaceEngine

        faces = InsightFaceEngine()
    return YoloDetector(), RapidOcrReader(), faces


def die_with_parent(parent_pid):
    if sys.platform == "linux":
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise RuntimeError("Could not bind inference lifetime to its worker")
        if os.getppid() != parent_pid:
            os._exit(1)


def _child(connection, parent_pid, factory, cache_mb, faces_enabled, album, paths, entry_list):
    try:
        die_with_parent(parent_pid)
        for name in ("STARTNUMMER_CHEVERETO_DSN", "STARTNUMMER_INTEGRATION_KEY"):
            os.environ.pop(name, None)
        adapters = factory(cache_mb, faces_enabled)
        result = InlineAnalyzer(*adapters)(
            album,
            paths,
            entry_list=entry_list,
            on_progress=lambda *progress: connection.send(("progress", progress)),
        )
        # Embeddings and decoded pixels never cross this pipe.
        connection.send(("result", result.model_dump(mode="json")))
    except BaseException as exc:
        try:
            connection.send(("error", type(exc).__name__))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        DEFAULT_CACHE.clear()
        connection.close()


class ProcessAnalyzer:
    def __init__(self, cache_mb=512, faces_enabled=True, *, factory: Callable = load_models):
        self.cache_mb, self.faces_enabled, self.factory = cache_mb, faces_enabled, factory
        self.process = None

    def __call__(self, album, paths, *, entry_list, on_progress):
        if self.process is not None:
            raise RuntimeError("This analyzer is already running an album")
        context = multiprocessing.get_context("spawn")
        reader, writer = context.Pipe(duplex=False)
        process = context.Process(
            target=_child,
            args=(writer, os.getpid(), self.factory, self.cache_mb, self.faces_enabled, album, paths, entry_list),
        )
        self.process = process
        started = False
        progress = (0, len(paths), "loading models")
        next_check = 0.0
        try:
            process.start()
            started = True
            writer.close()
            while True:
                if reader.poll(0.2):
                    try:
                        kind, data = reader.recv()
                    except EOFError:
                        raise WorkflowError("Inference process exited without completing the album") from None
                    if kind == "progress":
                        progress = data
                        on_progress(*progress)
                        next_check = time.monotonic() + 1
                    elif kind == "error":
                        raise WorkflowError("Inference process failed; check model availability and retry")
                    elif kind == "result":
                        result = InferenceResult.model_validate(data)
                        process.join(timeout=5)
                        if process.is_alive() or process.exitcode != 0:
                            raise WorkflowError("Inference process did not shut down cleanly")
                        on_progress(len(paths), len(paths), "finishing")
                        return result
                    else:
                        raise WorkflowError("Unexpected inference process response")
                elif not process.is_alive():
                    raise WorkflowError("Inference process exited without completing the album")
                if time.monotonic() >= next_check:
                    # Keep cancellation and lease fencing responsive during model loading or inference.
                    on_progress(*progress)
                    next_check = time.monotonic() + 1
        finally:
            reader.close()
            writer.close()
            if started:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                if process.is_alive():
                    raise WorkflowError("Inference process could not be stopped")
            process.close()
            self.process = None
