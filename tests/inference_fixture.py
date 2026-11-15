"""Synthetic adapters that deliberately retain input buffers inside a child."""

import json
import os
import time
from uuid import uuid4

from startnummer.adapters.cache import DEFAULT_CACHE
from startnummer.app.inference import ProcessAnalyzer
from startnummer.core.enums import Sport
from startnummer.core.interfaces import EntryList
from startnummer.core.record import Album
from tests.test_workflow import Detector, Faces, Ocr


class RetainingDetector(Detector):
    _cache = DEFAULT_CACHE

    def detect(self, path):
        self.last_image = self._cache.load(path)
        return super().detect(path)


class RetainingFaces(Faces):
    def detect(self, path):
        self.last_faces = super().detect(path)
        return self.last_faces


class DecodedImage:
    nbytes = 1024 * 1024

    def __init__(self):
        self.pixels = bytearray(self.nbytes)


def decode(path):
    return DecodedImage()


def retaining_models(cache_mb, faces_enabled):
    DEFAULT_CACHE.set_max_mb_bytes(cache_mb)
    DEFAULT_CACHE._decode = decode
    return RetainingDetector(), Ocr(), RetainingFaces() if faces_enabled else None


def failed_models(*args):
    raise RuntimeError("synthetic-private-data-must-not-leave-the-child")


def crashed_models(*args):
    os._exit(7)


def blocked_models(*args):
    print(json.dumps({"inference_pid": os.getpid()}), flush=True)
    while True:
        time.sleep(1)


def main():
    analyzer = ProcessAnalyzer(factory=blocked_models)
    album = Album(owner_id=uuid4(), name="Synthetic subprocess test", sport=Sport.ATHLETICS)
    analyzer(album, [], entry_list=EntryList(athletes=[]), on_progress=lambda *args: None)


if __name__ == "__main__":
    main()
