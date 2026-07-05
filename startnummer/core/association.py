"""Geometric association of bib reads and faces to person detections.

Pure (no I/O); testable with synthetic boxes. Output is intermediate and carries
transient face embeddings; the orchestrator resolves identities from it and builds
the persisted Subjects.

Dense scenes (podiums, packs) produce heavily overlapping person boxes, so plain
center-containment misassigns: the box of a person standing behind contains the
face and bib of the person in front. Ownership rules:

- Faces: at most ONE face per person, enforced by a joint minimum-cost matching
  (greedy per-face ownership steals faces across box edges: a face just below a
  bigger box's top edge looks "highest" there and displaces the true owner, and
  the displaced face then chimeras onto someone else). Cost favors faces near a
  box's top and horizontally central; containment is required. A face that loses
  the matching becomes an orphan rather than being forced onto the wrong person.
- Bibs: anchored to the torso (x = box center, y = 35% down). Of the containing
  boxes, assigned uniquely to the clearly nearest anchor; only on a genuine
  near-tie split as diluted-confidence candidates for review/roster.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import hypot

from startnummer.core.enums import Source
from startnummer.core.matching import FORBIDDEN, min_cost_assignment
from startnummer.core.models import Confident
from startnummer.core.types import BibRead, BoundingBox, FaceDetection

_TORSO_ANCHOR = 0.35  # bib anchor: this fraction down the person box
_UNIQUE_MARGIN = 0.8  # unique bib assignment if best distance < margin * runner-up
_HORIZONTAL_WEIGHT = 0.5  # face cost: weight of horizontal offset vs vertical position


@dataclass
class GroupedSubject:
    person_box: (
        BoundingBox | None
    )  # None for an orphan read/face with no enclosing detection
    bibs: list[Confident[str]] = field(default_factory=list)
    faces: list[FaceDetection] = field(
        default_factory=list
    )  # transient; never persisted


def _center(box: BoundingBox) -> tuple[float, float]:
    return (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2


def _contains(box: BoundingBox, point: tuple[float, float]) -> bool:
    x, y = point
    return box.x1 <= x <= box.x2 and box.y1 <= y <= box.y2


def _containers(
    groups: list[GroupedSubject], point: tuple[float, float]
) -> list[GroupedSubject]:
    return [
        g for g in groups if g.person_box is not None and _contains(g.person_box, point)
    ]


def _face_cost(box: BoundingBox, center: tuple[float, float]) -> float:
    # Low when the face sits near the box top and horizontally central — where a
    # person's own face is. Purely relative ranking; absolute scale is irrelevant.
    width = max(box.x2 - box.x1, 1)
    height = max(box.y2 - box.y1, 1)
    relative_y = (center[1] - box.y1) / height
    offset_x = abs(center[0] - (box.x1 + box.x2) / 2) / width
    return relative_y + _HORIZONTAL_WEIGHT * offset_x


def _assign_faces(
    groups: list[GroupedSubject],
    persons: list[GroupedSubject],
    faces: Sequence[FaceDetection],
) -> None:
    if not faces:
        return
    centers = [_center(face.box) for face in faces]
    costs = [
        [
            (
                _face_cost(person.person_box, center)
                if _contains(person.person_box, center)
                else FORBIDDEN
            )
            for person in persons
        ]
        for center in centers
    ]
    for face, assigned in zip(faces, min_cost_assignment(costs)):
        if assigned is None:
            # Not contained anywhere, or every plausible owner already has a
            # face: orphan, never a forced wrong match.
            groups.append(GroupedSubject(person_box=None, faces=[face]))
        else:
            persons[assigned].faces.append(face)


def _anchor_distance(box: BoundingBox, point: tuple[float, float]) -> float:
    width = max(box.x2 - box.x1, 1)
    height = max(box.y2 - box.y1, 1)
    anchor_x = (box.x1 + box.x2) / 2
    anchor_y = box.y1 + _TORSO_ANCHOR * height
    return hypot((point[0] - anchor_x) / width, (point[1] - anchor_y) / height)


def group_subjects(
    persons: Sequence[BoundingBox],
    bibs: Sequence[BibRead],
    faces: Sequence[FaceDetection],
) -> list[GroupedSubject]:
    groups = [GroupedSubject(person_box=p) for p in persons]

    for bib in bibs:
        center = _center(bib.box)
        containers = _containers(groups, center)
        if not containers:
            groups.append(
                GroupedSubject(
                    person_box=None,
                    bibs=[
                        Confident(
                            value=bib.value,
                            confidence=bib.confidence,
                            source=Source.OCR,
                            note="no enclosing person box",
                        )
                    ],
                )
            )
            continue

        ranked = sorted(
            containers, key=lambda g: _anchor_distance(g.person_box, center)
        )
        unique = len(ranked) == 1 or (
            _anchor_distance(ranked[0].person_box, center)
            < _UNIQUE_MARGIN * _anchor_distance(ranked[1].person_box, center)
        )
        if unique:
            ranked[0].bibs.append(
                Confident(value=bib.value, confidence=bib.confidence, source=Source.OCR)
            )
        else:
            n = len(ranked)
            note = f"ambiguous: bib falls within {n} person boxes"
            for g in ranked:
                g.bibs.append(
                    Confident(
                        value=bib.value,
                        confidence=bib.confidence / n,
                        source=Source.OCR,
                        note=note,
                    )
                )

    _assign_faces(groups, groups[: len(persons)], faces)

    # Drop person detections that ended up with nothing to identify.
    return [g for g in groups if g.bibs or g.faces]
