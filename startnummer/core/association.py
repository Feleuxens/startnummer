"""Geometric association of bib reads and faces to person detections.

Assignment is by center-containment: a read/face belongs to every person box whose
region contains its center. Overlapping person boxes (dense packs) are what produce
the multi-container case; an ambiguous bib is attached to each candidate with its
confidence diluted by the number of candidates.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from startnummer.core.enums import Source
from startnummer.core.models import Confident
from startnummer.core.types import BibRead, BoundingBox, FaceDetection


@dataclass
class GroupedSubject:
    person_box: BoundingBox | None  # None for an orphan read/face with no enclosing detection
    bibs: list[Confident[str]] = field(default_factory=list)
    faces: list[FaceDetection] = field(default_factory=list)  # transient; never persisted


def _center(box: BoundingBox) -> tuple[float, float]:
    return (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2


def _contains(box: BoundingBox, point: tuple[float, float]) -> bool:
    x, y = point
    return box.x1 <= x <= box.x2 and box.y1 <= y <= box.y2


def group_subjects(
    persons: Sequence[BoundingBox],
    bibs: Sequence[BibRead],
    faces: Sequence[FaceDetection],
) -> list[GroupedSubject]:
    groups = [GroupedSubject(person_box=p) for p in persons]

    for bib in bibs:
        center = _center(bib.box)
        containers = [g for g in groups if g.person_box is not None and _contains(g.person_box, center)]
        if not containers:
            groups.append(
                GroupedSubject(
                    person_box=None,
                    bibs=[Confident(value=bib.value, confidence=bib.confidence, source=Source.OCR,
                                    note="no enclosing person box")],
                )
            )
            continue
        n = len(containers)
        note = None if n == 1 else f"ambiguous: bib falls within {n} person boxes"
        for g in containers:
            g.bibs.append(
                Confident(value=bib.value, confidence=bib.confidence / n, source=Source.OCR, note=note)
            )

    for face in faces:
        center = _center(face.box)
        containers = [g for g in groups if g.person_box is not None and _contains(g.person_box, center)]
        if not containers:
            groups.append(GroupedSubject(person_box=None, faces=[face]))
            continue
        for g in containers:
            g.faces.append(face)

    # Drop person detections that ended up with nothing to identify.
    return [g for g in groups if g.bibs or g.faces]
