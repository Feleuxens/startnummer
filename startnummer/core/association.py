"""Geometric association of bib reads and faces to person detections.

Pure (no I/O); testable with synthetic boxes. Output is intermediate and carries
transient face embeddings; the orchestrator resolves identities from it and builds
the persisted Subjects.

Ownership is keypoint-first and orientation-free:

- Face -> the person whose HEAD keypoint lies in/near the face box. At most one
  face per person, enforced by joint minimum-cost matching (greedy per-face
  ownership steals faces across box edges in dense scenes). A face that loses
  the matching becomes an orphan, never a forced wrong match.
- Bib -> the person whose SHOULDER-HIP torso quad contains the bib center.
  The quad moves with the body, so long-jump extension or an inverted pole
  vaulter need no special cases. Unique assignment when one torso is clearly
  nearest; genuine near-ties split as diluted-confidence candidates.

People without confident keypoints fall back to the box heuristics
(head-near-top face cost, torso-anchor bib distance) with an additive penalty,
so a keypointed owner beats a box-guessed one on ties. The fallback assumes an
upright pose - acceptable, because it only fires when the pose is unreadable.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from math import hypot

from startnummer.core.enums import Source
from startnummer.core.matching import FORBIDDEN, min_cost_assignment
from startnummer.core.models import Confident
from startnummer.core.types import BibRead, BoundingBox, FaceDetection, Keypoint, PersonDetection

# Keypoint path
_HEAD_MAX_DISTANCE = 1.2  # face-diagonals: head further than this cannot own the face
_TORSO_INFLATE = 1.3  # quad scaled about its centroid; bibs can overhang the strict quad

# Box-fallback path (fires only without confident keypoints; assumes upright)
_TORSO_ANCHOR = 0.35
_HORIZONTAL_WEIGHT = 0.5
_FALLBACK_PENALTY = 0.4  # faces (additive): flat disadvantage in the joint matching
_FALLBACK_FACTOR = 1.5  # bibs (multiplicative): preserves cost RATIOS so the
#   unique-vs-tie margin still separates two fallback candidates; an additive
#   penalty would compress ratios and turn clear winners into false ties

_UNIQUE_MARGIN = 0.8  # unique bib assignment if best cost < margin * runner-up


@dataclass
class GroupedSubject:
    person_box: BoundingBox | None  # None for an orphan read/face with no owner
    bibs: list[Confident[str]] = field(default_factory=list)
    bib_boxes: list[BoundingBox] = field(default_factory=list)  # aligned with bibs; transient
    faces: list[FaceDetection] = field(default_factory=list)  # transient; never persisted


def _center(box: BoundingBox) -> tuple[float, float]:
    return (box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2


def _contains(box: BoundingBox, point: tuple[float, float]) -> bool:
    x, y = point
    return box.x1 <= x <= box.x2 and box.y1 <= y <= box.y2


def _torso_quad(person: PersonDetection) -> list[Keypoint] | None:
    corners = (person.left_shoulder, person.right_shoulder, person.right_hip, person.left_hip)
    if any(c is None for c in corners):
        return None
    centroid_x = sum(c.x for c in corners) / 4
    centroid_y = sum(c.y for c in corners) / 4
    return [
        Keypoint(centroid_x + (c.x - centroid_x) * _TORSO_INFLATE,
                 centroid_y + (c.y - centroid_y) * _TORSO_INFLATE)
        for c in corners
    ]


def _in_polygon(point: tuple[float, float], polygon: Sequence[Keypoint]) -> bool:
    # Ray casting; orientation- and winding-agnostic.
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        if (a.y > y) != (b.y > y):
            x_cross = a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y)
            if x < x_cross:
                inside = not inside
    return inside


def _face_cost(person: PersonDetection, face_box: BoundingBox) -> float:
    center = _center(face_box)
    diagonal = max(hypot(face_box.x2 - face_box.x1, face_box.y2 - face_box.y1), 1.0)
    if person.head is not None:
        distance = hypot(center[0] - person.head.x, center[1] - person.head.y) / diagonal
        return distance if distance <= _HEAD_MAX_DISTANCE else FORBIDDEN
    # Fallback: upright-pose box heuristic.
    if not _contains(person.box, center):
        return FORBIDDEN
    width = max(person.box.x2 - person.box.x1, 1)
    height = max(person.box.y2 - person.box.y1, 1)
    relative_y = (center[1] - person.box.y1) / height
    offset_x = abs(center[0] - (person.box.x1 + person.box.x2) / 2) / width
    return relative_y + _HORIZONTAL_WEIGHT * offset_x + _FALLBACK_PENALTY


def _assign_faces(
    groups: list[GroupedSubject],
    persons: Sequence[PersonDetection],
    subjects: list[GroupedSubject],
    faces: Sequence[FaceDetection],
) -> None:
    if not faces:
        return
    costs = [[_face_cost(person, face.box) for person in persons] for face in faces]
    for face, assigned in zip(faces, min_cost_assignment(costs)):
        if assigned is None:
            groups.append(GroupedSubject(person_box=None, faces=[face]))
        else:
            subjects[assigned].faces.append(face)


def _bib_cost(person: PersonDetection, center: tuple[float, float]) -> float:
    quad = _torso_quad(person)
    if quad is not None:
        if not _in_polygon(center, quad):
            return FORBIDDEN
        centroid = (sum(k.x for k in quad) / 4, sum(k.y for k in quad) / 4)
        scale = max(
            hypot(quad[0].x - quad[2].x, quad[0].y - quad[2].y),
            hypot(quad[1].x - quad[3].x, quad[1].y - quad[3].y),
            1.0,
        )
        return hypot(center[0] - centroid[0], center[1] - centroid[1]) / scale
    # Fallback: upright-pose torso anchor within the box.
    if not _contains(person.box, center):
        return FORBIDDEN
    width = max(person.box.x2 - person.box.x1, 1)
    height = max(person.box.y2 - person.box.y1, 1)
    anchor_x = (person.box.x1 + person.box.x2) / 2
    anchor_y = person.box.y1 + _TORSO_ANCHOR * height
    return (
        hypot((center[0] - anchor_x) / width, (center[1] - anchor_y) / height)
        * _FALLBACK_FACTOR
    )


def group_subjects(
    persons: Sequence[PersonDetection],
    bibs: Sequence[BibRead],
    faces: Sequence[FaceDetection],
) -> list[GroupedSubject]:
    subjects = [GroupedSubject(person_box=p.box) for p in persons]
    groups: list[GroupedSubject] = list(subjects)

    for bib in bibs:
        center = _center(bib.box)
        scored = sorted(
            ((cost, i) for i, person in enumerate(persons)
             if (cost := _bib_cost(person, center)) is not FORBIDDEN),
            key=lambda pair: pair[0],
        )
        if not scored:
            groups.append(
                GroupedSubject(
                    person_box=None,
                    bibs=[Confident(value=bib.value, confidence=bib.confidence, source=Source.OCR,
                                    note="no plausible owner")],
                    bib_boxes=[bib.box],
                )
            )
            continue

        unique = len(scored) == 1 or scored[0][0] < _UNIQUE_MARGIN * scored[1][0]
        if unique:
            subjects[scored[0][1]].bibs.append(
                Confident(value=bib.value, confidence=bib.confidence, source=Source.OCR)
            )
            subjects[scored[0][1]].bib_boxes.append(bib.box)
        else:
            # near-tie set: candidates whose cost is within the margin of the best
            tied = [i for cost, i in scored if cost * _UNIQUE_MARGIN <= scored[0][0]]
            n = len(tied)
            note = f"ambiguous: {n} plausible owners"
            for i in tied:
                subjects[i].bibs.append(
                    Confident(value=bib.value, confidence=bib.confidence / n, source=Source.OCR, note=note)
                )
                subjects[i].bib_boxes.append(bib.box)

    _assign_faces(groups, persons, subjects, faces)

    # Drop person detections that ended up with nothing to identify.
    return [g for g in groups if g.bibs or g.faces]