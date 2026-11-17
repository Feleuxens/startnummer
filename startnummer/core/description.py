"""Captions with German/English discipline phrases and optional meet context."""

from startnummer.core.enums import Lang, Source
from startnummer.core.models import Athlete, Subject
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import get

DEFAULT_MIN_CONFIDENCE = 0.8


def _named_athletes(subjects: list[Subject], min_confidence: float) -> list[Athlete]:
    athletes: list[Athlete] = []
    seen: set[tuple[str, str | None]] = set()
    for subject in subjects:
        if subject.excluded_from_caption:
            continue
        match = subject.athlete
        if match is None:
            continue
        if match.source is not Source.MANUAL and match.confidence < min_confidence:
            continue
        athlete = match.value
        key = (athlete.name, athlete.bib)
        if key in seen:
            continue
        seen.add(key)
        athletes.append(athlete)
    return athletes


def _person(athlete: Athlete) -> str:
    details = ", ".join(value for value in (athlete.bib, athlete.club) if value)
    return f"{athlete.name} ({details})" if details else athlete.name.strip()


def _join(parts: list[str], conjunction: str) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {conjunction} {parts[-1]}"


def build_description(record: AnalysisRecord, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> str | None:
    """Build a caption from athlete names, DE/EN discipline phrases, and meet name.

    Omit unknown disciplines. Return None when no included athlete meets the confidence
    threshold; manually assigned athletes are included regardless of confidence.
    """
    athletes = _named_athletes(record.subjects, min_confidence)
    if not athletes:
        return None

    module = get(record.sport)

    people = _join([_person(athlete) for athlete in athletes], "&")
    phrases = [phrase for lang in (Lang.DE, Lang.EN) if (phrase := module.discipline_phrase(record.event, lang))]
    caption = f"{people} {'/'.join(phrases)}" if phrases else people
    meet_name = (record.meet_name or "").strip()
    return f"{caption} | {meet_name}" if meet_name else caption
