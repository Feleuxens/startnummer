"""Synthetic inference for the opt-in Compose test; mounted only by that test."""

from functools import partial

from startnummer.app import worker
from startnummer.app.inference import ProcessAnalyzer
from startnummer.core.types import BibRead, BoundingBox, FaceDetection, OcrResult, PersonDetection


class Detector:
    def detect(self, path):
        return [PersonDetection(box=BoundingBox(0, 0, 100, 200))]


class Ocr:
    def read(self, path):
        return OcrResult(bibs=[BibRead(box=BoundingBox(20, 60, 60, 90), value="12", confidence=0.99)], texts=[])


class Faces:
    def detect(self, path):
        return [FaceDetection(box=BoundingBox(20, 10, 60, 50), embedding=[1.0, 0.0, 0.0])]


def models(cache_mb, faces_enabled):
    return Detector(), Ocr(), Faces() if faces_enabled else None


if __name__ == "__main__":
    worker.ProcessAnalyzer = partial(ProcessAnalyzer, factory=models)
    worker.main()
