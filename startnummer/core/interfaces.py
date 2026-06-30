"""Pipeline-stage interfaces and the Roster contract.

Implementations (pdfplumber, CSV, YOLO, PaddleOCR, InsightFace, Qwen-VL) live in
startnummer.adapters and depend on this module, never the reverse. Each EntryTable
input format is a separate EntryTable implementation.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from startnummer.core.models import Athlete
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import Event
from startnummer.core.types import BoundingBox, FaceDetection, OcrResult


class EntryList(BaseModel):
    competition: str | None = None
    athletes: list[Athlete] = Field(default_factory=list)

    def by_bib(self, bib: str) -> Athlete | None:
        return next((a for a in self.athletes if a.bib == bib), None)


@runtime_checkable
class EntryListParser(Protocol):
    # source is a path/id; format-specific (PDF, CSV, XLSX) parsers each implement this.
    def parse(self, source: str) -> EntryList: ...


@runtime_checkable
class Detector(Protocol):
    # Person/torso regions to crop before OCR and face detection.
    def detect(self, image_path: str) -> list[BoundingBox]: ...


@runtime_checkable
class OcrReader(Protocol):
    # OCRs the full frame once; classifies tokens into bib candidates and name hints.
    # Boxes are in image coordinates; group_subjects does the person attribution.
    def read(self, image_path: str) -> OcrResult: ...


@runtime_checkable
class FaceEngine(Protocol):
    # One detection (box + embedding) per face found within regions.
    def detect(self, image_path: str, regions: Sequence[BoundingBox]) -> list[FaceDetection]: ...


@runtime_checkable
class DisciplineClassifier(Protocol):
    # Returns a sport-specific Event (e.g. AthleticsEvent); None if undetermined.
    def classify(self, image_path: str) -> Event | None: ...


@runtime_checkable
class DescriptionBuilder(Protocol):
    # Builds the prose description (templated or VLM). Tags are derived in core.tagging.
    def describe(self, record: AnalysisRecord) -> str | None: ...