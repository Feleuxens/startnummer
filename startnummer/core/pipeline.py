"""Analyze each photo, link faces within the album, and generate captions.

Detector, OCR, and face engines are injected. Face embeddings are used for
cross-photo bib propagation and are excluded from AnalysisRecord.
"""

import hashlib
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import NamedTuple

from startnummer.core.association import GroupedSubject, group_subjects
from startnummer.core.description import build_description
from startnummer.core.entrytable import match_photo, table_supports
from startnummer.core.enums import Source, Status
from startnummer.core.identity import DEFAULT_MIN_SIMILARITY, FaceItem, cluster_faces
from startnummer.core.interfaces import CueDetector, Detector, EntryList, FaceEngine, OcrReader
from startnummer.core.models import Confident, Subject
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.sports import get
from startnummer.core.types import FaceDetection

# Placeholders until tuned against real albums.
STRONG_BIB_CONFIDENCE = 0.8  # a bib this confident may be propagated to face matches
PROPAGATION_DISCOUNT = 0.9  # propagated confidence = source confidence * discount
ATHLETE_AUTO = 0.8  # minimum athlete confidence for automatic resolution

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
    eligible = [(i, bib) for i, bib in enumerate(bibs) if bib.confidence >= min_confidence]
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


def _subject_needs_review(subject: Subject, grouped: GroupedSubject, min_bib_confidence: float, matched: bool) -> bool:
    """Flag conflicting bibs, weak athlete matches, or unresolved roster evidence.

    A confident roster match resolves uncontested reads. With no match, ambiguous
    reads need review, as do strong bibs missing from the supplied roster.
    """
    pick = strong_bib(subject.bibs, grouped.bib_boxes, min_bib_confidence)
    if pick is not None and pick.contested:
        return True
    if subject.athlete is not None and subject.athlete.confidence >= ATHLETE_AUTO:
        return False
    if subject.athlete is not None:
        return True  # review partial or name-only suggestions
    if pick is None:
        # Split ownership can leave ambiguous reads below the confidence threshold.
        return _has_ambiguous_bib(subject)
    # A confident, uncontested read that nonetheless didn't match the table.
    return matched and subject.athlete is None


def _has_ambiguous_bib(subject: Subject) -> bool:
    return any(b.note is not None and b.note.startswith("ambiguous") for b in subject.bibs)


def _status(photo: "_PhotoAnalysis", min_bib_confidence: float, matched: bool) -> Status:
    record = photo.record
    if not record.subjects:
        return Status.NEEDS_REVIEW
    for subject, grouped in zip(record.subjects, photo.grouped, strict=True):
        if _subject_needs_review(subject, grouped, min_bib_confidence, matched):
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
    links.extend((ka, kb) for (ka, va), (kb, vb) in combinations(with_bib, 2) if va != vb)
    return links


def _propagate_bibs(photos: list[_PhotoAnalysis], *, min_similarity: float, min_bib_confidence: float) -> None:
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

    strong_bibs = {key: pick.bib.value for key in (item.key for item in items) if (pick := _pick(key)) is not None}

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
    entry_list: EntryList | None = None,
    min_face_similarity: float = DEFAULT_MIN_SIMILARITY,
    min_bib_confidence: float = STRONG_BIB_CONFIDENCE,
    on_progress: Callable[[int, int, str], None] | None = None,
    on_faces: Callable[[int, int, Sequence[FaceDetection]], None] | None = None,
) -> list[AnalysisRecord]:
    module = get(album.sport)
    photos: list[_PhotoAnalysis] = []

    time_total_person = 0
    time_total_ocr = 0
    time_total_face = 0
    time_total_grouping = 0

    start_time = perf_counter()
    for index, path in enumerate(image_paths):
        record = AnalysisRecord(
            owner_id=album.owner_id,
            album_id=album.id,
            content_hash=_sha256(path),
            source_path=path,
            meet_name=(album.meet_name or "").strip()
            or ((entry_list.competition or "").strip() if entry_list is not None else None)
            or None,
            event=module.new_event(),
        )
        grouped = []
        try:
            if on_progress:
                on_progress(index, len(image_paths), "detecting")
            intermediate_start = perf_counter()
            persons = detector.detect(path)
            time_total_person += perf_counter() - intermediate_start

            intermediate_start = perf_counter()
            ocr_result = ocr.read(path)
            time_total_ocr += perf_counter() - intermediate_start

            intermediate_start = perf_counter()
            face_detections = faces.detect(path) if faces is not None else []
            time_total_face += perf_counter() - intermediate_start

            intermediate_start = perf_counter()
            grouped = group_subjects(persons, ocr_result.bibs, face_detections, ocr_result.texts)
            time_total_grouping += perf_counter() - intermediate_start
            if cues is not None:
                record.event = module.infer(record.event, cues.detect(path))
            record.subjects = [Subject(bibs=list(g.bibs)) for g in grouped]
        except Exception as exc:
            # A model failure is a photo outcome, not the end of the batch.
            # Do not persist exception text, which may include paths or secrets.
            record.status = Status.FAILED
            record.failure_reason = f"Photo analysis failed ({type(exc).__name__})"
            grouped = []
            record.subjects = []
        photos.append(_PhotoAnalysis(record=record, grouped=grouped))
        if on_progress:
            on_progress(index + 1, len(image_paths), "analyzing")

    if entry_list is not None:
        for photo in photos:
            _match_and_filter(photo, entry_list, min_bib_confidence)

    if faces is not None:
        if on_progress:
            on_progress(len(image_paths), len(image_paths), "linking faces")
        _propagate_bibs(photos, min_similarity=min_face_similarity, min_bib_confidence=min_bib_confidence)

    if entry_list is not None:
        # Match propagated bibs to the roster, keeping existing athlete matches.
        for photo in photos:
            _match_photo(photo, entry_list, min_bib_confidence)

    for index, photo in enumerate(photos):
        if photo.record.status is Status.FAILED:
            continue
        photo.record.event = get(photo.record.sport).resolve(photo.record.event, photo.record.subjects)
        photo.record.status = _status(photo, min_bib_confidence, entry_list is not None)
        photo.record.description = build_description(photo.record)
        if on_faces:
            for subject_index, grouped in enumerate(photo.grouped):
                if grouped.faces:
                    on_faces(index, subject_index, grouped.faces)

    print(f"Finished pipeline in {perf_counter() - start_time}")
    print(f"Person detection (accumulated): {time_total_person}")
    print(f"Ocr detection (accumulated): {time_total_ocr}")
    print(f"Face detection (accumulated): {time_total_face}")
    print(f"Grouping detection (accumulated): {time_total_grouping}")

    return [photo.record for photo in photos]


def _hints(photo: _PhotoAnalysis) -> list[list[str]]:
    return [[t.value for t in g.texts] for g in photo.grouped]


def _match_photo(photo: _PhotoAnalysis, entries: EntryList, min_bib_confidence: float) -> None:
    match_photo(photo.record.subjects, _hints(photo), entries, min_bib_confidence=min_bib_confidence)


def _match_and_filter(photo: _PhotoAnalysis, entries: EntryList, min_bib_confidence: float) -> None:
    """Match the roster and remove unsupported, unowned reads."""
    _match_photo(photo, entries, min_bib_confidence)
    keep = [
        (subject, grouped)
        for subject, grouped in zip(photo.record.subjects, photo.grouped, strict=True)
        if not (
            grouped.person_box is None
            and subject.athlete is None
            and not grouped.faces
            and not any(table_supports(b.value, entries) for b in subject.bibs)
        )
    ]
    photo.record.subjects = [s for s, _ in keep]
    photo.grouped = [g for _, g in keep]
