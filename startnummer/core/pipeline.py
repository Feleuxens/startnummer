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


def strong_bib(bibs: Sequence[Confident[str]]) -> Confident[str] | None:
    # Unambiguous = exactly one candidate; ambiguity is left for review/roster.
    if len(bibs) == 1 and bibs[0].confidence >= STRONG_BIB_CONFIDENCE:
        return bibs[0]
    return None


def _status(record: AnalysisRecord) -> Status:
    # Structural placeholder until the entry list provides ground truth: AUTO only
    # if every subject carries exactly one strong bib.
    if not record.subjects:
        return Status.NEEDS_REVIEW
    if all(strong_bib(s.bibs) is not None for s in record.subjects):
        return Status.AUTO
    return Status.NEEDS_REVIEW


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

    with_bib = [
        (item.key, strong_bibs[item.key]) for item in items if item.key in strong_bibs
    ]
    links.extend(
        (ka, kb) for (ka, va), (kb, vb) in combinations(with_bib, 2) if va != vb
    )
    return links


def _propagate_bibs(photos: list[_PhotoAnalysis], *, min_similarity: float) -> None:
    """Within-album: give face-matched subjects without a strong bib the bib of
    their cluster. Constraints ensure a cluster never holds two different strong
    bibs; the exactly-one check below remains as a defensive backstop."""
    items = [
        FaceItem(key=(pi, si), embeddings=[f.embedding for f in grouped.faces])
        for pi, photo in enumerate(photos)
        for si, grouped in enumerate(photo.grouped)
        if grouped.faces
    ]
    strong_bibs = {
        key: bib.value
        for key in (item.key for item in items)
        if (bib := strong_bib(photos[key[0]].record.subjects[key[1]].bibs)) is not None
    }

    clusters = cluster_faces(
        items,
        min_similarity=min_similarity,
        cannot_link=face_cannot_links(items, strong_bibs),
    )
    for cluster in clusters:
        donors = {
            key: strong_bib(photos[key[0]].record.subjects[key[1]].bibs)
            for key in cluster
            if key in strong_bibs
        }
        values = {bib.value for bib in donors.values()}
        if len(values) != 1:
            continue
        donor = max(donors.values(), key=lambda b: b.confidence)
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
        _propagate_bibs(photos, min_similarity=min_face_similarity)

    for photo in photos:
        photo.record.status = _status(photo.record)
    return [photo.record for photo in photos]
