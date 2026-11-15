"""Shared image-decode cache for the adapters."""

import os
import threading
from collections import OrderedDict
from collections.abc import Callable

DEFAULT_MAX_MB_BYTES = 4096  # 4 GB


def _decode_bgr(path: str):
    import cv2  # deferred: the cache is importable without the worker extra

    image = cv2.imread(path)  # BGR; applies EXIF orientation like the old per-adapter loads
    if image is None:
        raise FileNotFoundError(path)
    return image


class ImageCache:
    def __init__(
        self,
        max_mb_bytes: int = DEFAULT_MAX_MB_BYTES,
        decode: Callable[[str], object] = _decode_bgr,
    ) -> None:
        self._max_bytes = max_mb_bytes * 1024 * 1024
        self._decode = decode
        self._entries: OrderedDict[str, object] = OrderedDict()
        self._total = 0
        self._generation = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def load(self, path: str):
        key = os.path.abspath(path)
        with self._lock:
            generation = self._generation
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                self.hits += 1
                return cached

        image = self._decode(key)
        if hasattr(image, "flags"):
            image.flags.writeable = False
        size = int(getattr(image, "nbytes", 0))

        with self._lock:
            self.misses += 1
            if generation != self._generation or size > self._max_bytes:
                return image  # Do not retain an old decode or an image larger than the budget.
            if key not in self._entries:
                self._entries[key] = image
                self._total += size
                while self._total > self._max_bytes and len(self._entries) > 1:
                    _, evicted = self._entries.popitem(last=False)
                    self._total -= int(getattr(evicted, "nbytes", 0))
        return image

    def set_max_mb_bytes(self, max_bytes: int) -> None:
        with self._lock:
            self._max_bytes = max_bytes * 1024 * 1024
            while self._total > self._max_bytes and self._entries:
                _, evicted = self._entries.popitem(last=False)
                self._total -= int(getattr(evicted, "nbytes", 0))

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._entries.clear()
            self._total = 0

    def stats(self) -> str:
        return f"cache: {self.hits} hits, {self.misses} misses, {self._total / 1e6:.0f} MB held"


DEFAULT_CACHE = ImageCache()
