"""Album analysis pipeline.

Sequences the per-photo stages (detect -> OCR -> faces -> group -> cues/infer ->
resolve) and the cross-photo pass (face-identity linking, bib propagation).
Takes protocol instances so it runs identically with adapters or test fakes;
the only I/O here is hashing the image bytes.

Face embeddings stay transient: they exist inside this function and are never
written to the records (gallery persistence is a separate, opt-in port).
"""

import hashlib
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import NamedTuple

from startnummer.core.association import GroupedSubject, group_subjects
from startnummer.core.enums import Source, Status
from startnummer.core.identity import DEFAULT_MIN_SIMILARITY, FaceItem, cluster_faces
from startnummer.core.interfaces import CueDetector, Detector, FaceEngine, OcrReader
from startnummer.core.models import Confident, Subject
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.sports import get

# Placeholders until tuned against real albums.
STRONG_BIB_CONFIDENCE = 0.8  # a bib this confident may be propagated to face matches
PROPAGATION_DISCOUNT = 0.85  # propagated confidence = source confidence * discount

FaceKey = tuple[int, int]  # (photo index, subject index)


@dataclass
class _PhotoAnalysis:
    record: AnalysisRecord
    grouped: list[GroupedSubject]  # index-aligned with record.subjects


def _sha256(path: str) -> str:
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


class StrongBib(NamedTuple):
    bib: Confident[str]
    contested: bool  # True when several distinct confident values were tiebroken


def strong_bib(
    bibs: Sequence[Confident[str]],
    boxes: Sequence | None = None,  # aligned BoundingBoxes; enables the size tiebreak
    min_confidence: float = STRONG_BIB_CONFIDENCE,
) -> StrongBib | None:
    """The subject's usable bib, if any.

    One distinct confident value -> uncontested. Several distinct confident
    values (e.g. a club-logo glyph read as a digit next to the real bib) are
    tiebroken by confidence, then box area; the winner is usable for donation
    and constraints, but contested=True and the photo must go to review.
    """
    eligible = [
        (i, bib) for i, bib in enumerate(bibs) if bib.confidence >= min_confidence
    ]
    if not eligible:
        return None
    values = {bib.value for _, bib in eligible}
    if len(values) == 1:
        return StrongBib(max((b for _, b in eligible), key=lambda b: b.confidence), False)

    def _area(index: int) -> float:
        if boxes is None or index >= len(boxes):
            return 0.0
        box = boxes[index]
        return (box.x2 - box.x1) * (box.y2 - box.y1)

    _, winner = max(eligible, key=lambda pair: (pair[1].confidence, _area(pair[0])))
    return StrongBib(winner, True)


def _status(photo: "_PhotoAnalysis", min_bib_confidence: float) -> Status:
    # Structural placeholder until the entry list provides ground truth: AUTO only
    # if every subject has an UNCONTESTED strong bib; any tiebreak forces review.
    record = photo.record
    if not record.subjects:
        return Status.NEEDS_REVIEW
    for subject, grouped in zip(record.subjects, photo.grouped):
        pick = strong_bib(subject.bibs, grouped.bib_boxes, min_bib_confidence)
        if pick is None or pick.contested:
            return Status.NEEDS_REVIEW
    return Status.AUTO


def face_cannot_links(
    items: Sequence[FaceItem], strong_bibs: Mapping[Hashable, str]
) -> list[tuple[Hashable, Hashable]]:
    """Cannot-link pairs over FaceKey-keyed items: same photo, or different bibs."""
    links: list[tuple[Hashable, Hashable]] = []

    by_photo: dict[int, list[Hashable]] = {}
    for item in items:
        by_photo.setdefault(item.key[0], []).append(item.key)
    for keys in by_photo.values():
        links.extend(combinations(keys, 2))

    with_bib = [(item.key, strong_bibs[item.key]) for item in items if item.key in strong_bibs]
    links.extend(
        (ka, kb) for (ka, va), (kb, vb) in combinations(with_bib, 2) if va != vb
    )
    return links


def _propagate_bibs(
    photos: list[_PhotoAnalysis], *, min_similarity: float, min_bib_confidence: float
) -> None:
    """Within-album: give face-matched subjects without a strong bib the bib of
    their cluster. Constraints ensure a cluster never holds two different strong
    bibs; the exactly-one check below remains as a defensive backstop."""
    items = [
        FaceItem(key=(pi, si), embeddings=[f.embedding for f in grouped.faces])
        for pi, photo in enumerate(photos)
        for si, grouped in enumerate(photo.grouped)
        if grouped.faces
    ]
    def _pick(key: FaceKey) -> StrongBib | None:
        photo = photos[key[0]]
        return strong_bib(
            photo.record.subjects[key[1]].bibs,
            photo.grouped[key[1]].bib_boxes,
            min_bib_confidence,
        )

    strong_bibs = {
        key: pick.bib.value
        for key in (item.key for item in items)
        if (pick := _pick(key)) is not None
    }

    clusters = cluster_faces(
        items,
        min_similarity=min_similarity,
        cannot_link=face_cannot_links(items, strong_bibs),
    )
    for cluster in clusters:
        donors = {key: _pick(key) for key in cluster if key in strong_bibs}
        values = {pick.bib.value for pick in donors.values()}
        if len(values) != 1:
            continue
        donor = max((pick.bib for pick in donors.values()), key=lambda b: b.confidence)
        for key in cluster:
            if key in donors:
                continue
            subject = photos[key[0]].record.subjects[key[1]]
            subject.bibs.append(
                Confident(
                    value=donor.value,
                    confidence=donor.confidence * PROPAGATION_DISCOUNT,
                    source=Source.FACE_MATCH,
                    note="propagated from face match within album",
                )
            )


def analyze_album(
    album: Album,
    image_paths: Sequence[str],
    *,
    detector: Detector,
    ocr: OcrReader,
    faces: FaceEngine | None = None,
    cues: CueDetector | None = None,
    min_face_similarity: float = DEFAULT_MIN_SIMILARITY,
    min_bib_confidence: float = STRONG_BIB_CONFIDENCE,
) -> list[AnalysisRecord]:
    module = get(album.sport)
    photos: list[_PhotoAnalysis] = []

    for path in image_paths:
        persons = detector.detect(path)
        ocr_result = ocr.read(path)
        face_detections = faces.detect(path) if faces is not None else []
        grouped = group_subjects(persons, ocr_result.bibs, face_detections)

        event = module.new_event()
        if cues is not None:
            event = module.infer(event, cues.detect(path))

        subjects = [Subject(bibs=list(g.bibs)) for g in grouped]
        event = module.resolve(event, subjects)  # no-op until entry lists exist

        record = AnalysisRecord(
            owner_id=album.owner_id,
            album_id=album.id,
            content_hash=_sha256(path),
            source_path=path,
            event=event,
            subjects=subjects,
        )
        photos.append(_PhotoAnalysis(record=record, grouped=grouped))

    if faces is not None:
        _propagate_bibs(
            photos, min_similarity=min_face_similarity, min_bib_confidence=min_bib_confidence
        )

    for photo in photos:
        photo.record.status = _status(photo, min_bib_confidence)
    return [photo.record for photo in photos]