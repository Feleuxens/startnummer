"""Pipeline-stage interfaces and the EntryList contract.

Implementations (pdfplumber, CSV, YOLO, PaddleOCR, InsightFace, Qwen-VL) live in
startnummer.adapters and depend on this module, never the reverse. Each EntryTable
input format is a separate EntryTable implementation.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from startnummer.core.models import Athlete
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import Event
from startnummer.core.types import FaceDetection, OcrResult, PersonDetection


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
    # Person detections (box + pose keypoints) for bib/face ownership in
    # core.association. Keypoints are optional per joint; association falls
    # back to box heuristics for persons without them.
    def detect(self, image_path: str) -> list[PersonDetection]: ...


@runtime_checkable
class OcrReader(Protocol):
    # OCRs the full frame once; classifies tokens into bib candidates and name hints.
    # Boxes are in image coordinates; group_subjects does the person attribution.
    def read(self, image_path: str) -> OcrResult: ...


@runtime_checkable
class FaceEngine(Protocol):
    # Detects faces on the full frame; one detection (box + embedding) per face.
    # Boxes are in image coordinates; group_subjects does the person attribution.
    def detect(self, image_path: str) -> list[FaceDetection]: ...


@runtime_checkable
class CueDetector(Protocol):
    # Sport-relevant object cues visible in the frame ("baton", "hurdle", ...),
    # deduped. Consumed by SportModule.infer to refine the event.
    def detect(self, image_path: str) -> list[str]: ...


@runtime_checkable
class DisciplineClassifier(Protocol):
    # Returns a sport-specific Event (e.g. AthleticsEvent); None if undetermined.
    def classify(self, image_path: str) -> Event | None: ...


@runtime_checkable
class DescriptionBuilder(Protocol):
    # Builds the prose description (templated or VLM). Tags are derived in core.tagging.
    def describe(self, record: AnalysisRecord) -> str | None: ...