"""Bilingual DE+EN descriptions from a resolved record. German first, then English."""

from startnummer.core.enums import Lang, Source
from startnummer.core.models import Athlete, Subject
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports import get

DEFAULT_MIN_CONFIDENCE = 0.8


def _named_athletes(
    subjects: list[Subject], min_confidence: float
) -> list[Athlete]:
    athletes: list[Athlete] = []
    seen: set[tuple[str, str | None]] = set()
    for subject in subjects:
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
    if athlete.bib and athlete.club:
        detail = f"({athlete.bib}, {athlete.club})"
    elif athlete.bib and athlete.club is None:
        detail = f"({athlete.bib})"
    elif athlete.club and athlete.bib is None:
        detail = f"({athlete.club})"
    else:
        detail = ""

    return f"{athlete.name} {detail}"


def _join(parts: list[str], conjunction: str) -> str:
    # "a", "a und b", "a, b und c"
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} {conjunction} {parts[-1]}"


def build_description(
    record: AnalysisRecord, *, min_confidence: float = DEFAULT_MIN_CONFIDENCE
) -> str | None:
    """DE paragraph then EN, or None when no athlete is confidently named.

    None is not a failure: the discipline still reaches Chevereto as a tag via
    derive_tags. Prose without a name would add nothing searchable.
    """
    athletes = _named_athletes(record.subjects, min_confidence)
    if not athletes:
        return None

    module = get(record.sport)

    people = _join([_person(athlete) for athlete in athletes], "&")
    phrase = module.discipline_phrase(record.event, Lang.DE)
    phrase += "/"
    phrase += module.discipline_phrase(record.event, Lang.EN)

    return f"{people} {phrase}"