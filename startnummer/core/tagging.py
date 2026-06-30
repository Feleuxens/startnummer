"""Derive tags from a resolved record.

Clubs come from matched entry table data (unbounded). The discipline/distance tag comes
from the record's sport module.
"""

from startnummer.core.enums import Source
from startnummer.core.models import Tag, TagNamespace
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import get

DEFAULT_MIN_CONFIDENCE = 0.6


def _club_tags(record: AnalysisRecord, min_confidence: float) -> list[Tag]:
    seen: set[str] = set()
    tags: list[Tag] = []
    for subject in record.subjects:
        athlete = subject.athlete
        if athlete is None or athlete.value.club is None:
            continue
        if athlete.source is not Source.MANUAL and athlete.confidence < min_confidence:
            continue
        club = athlete.value.club
        if club not in seen:
            seen.add(club)
            tags.append(Tag(TagNamespace.CLUB, club))
    return tags


def derive_tags(
    record: AnalysisRecord, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE
) -> list[Tag]:
    tags = _club_tags(record, min_confidence)
    discipline = get(record.sport).discipline_tag(record.event)
    if discipline is not None:
        tags.append(discipline)
    return tags
