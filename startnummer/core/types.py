"""Shared primitives used by ports, interfaces, and association."""

from collections.abc import Sequence
from typing import NamedTuple

# Plain floats, not ndarray, so core carries no numpy dependency.
# Adapters convert to/from numpy at their boundary.
Embedding = Sequence[float]


class BoundingBox(NamedTuple):
    # Pixel coordinates, top-left origin. (x1, y1) top-left, (x2, y2) bottom-right.
    x1: int
    y1: int
    x2: int
    y2: int


class BibRead(NamedTuple):
    box: BoundingBox
    value: str
    confidence: float  # OCR read confidence [0, 1]


class FaceDetection(NamedTuple):
    box: BoundingBox
    embedding: Embedding


class TextRead(NamedTuple):
    box: BoundingBox
    value: str
    confidence: float


class OcrResult(NamedTuple):
    bibs: list[BibRead]  # digit tokens
    texts: list[TextRead]  # name/word tokens, fuzzy-matched against the roster later
