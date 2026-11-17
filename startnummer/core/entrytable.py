"""Entry-table matcher: ties OCR evidence (bibs + name hints) to athletes.

Matches use difflib for name similarity. The first matching rule sets the
athlete and confidence:

  exact    bib value is in the table ................................ 0.95
           ... and a name hint confirms the athlete ................. 0.98
  partial  bib value is a substring of exactly ONE table bib ........ 0.65
           ... several candidates, a name hint picks exactly one .... 0.85
  name     no usable bib; hints match exactly one athlete ........... 0.50
"""

from collections.abc import Sequence
from difflib import SequenceMatcher

from startnummer.core.enums import Source
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete, Confident, Subject

EXACT = 0.95
EXACT_NAME_CONFIRMED = 0.98
PARTIAL_UNIQUE = 0.65
PARTIAL_NAME_PICKED = 0.85
NAME_ONLY = 0.50
ATHLETE_AUTO = 0.8  # minimum roster-match confidence for automatic resolution

NAME_SIMILARITY = 0.78  # difflib ratio; OCR reads printed surnames nearly verbatim
_MIN_PARTIAL_LENGTH = 2  # single-digit partial reads produce too many candidates


def _name_score(hint: str, athlete: Athlete) -> float:
    # Hints are single tokens (usually the surname printed on the bib); compare
    # against every name token and the full name, order-independent.
    hint_cf = hint.casefold()
    candidates = athlete.name.split() + [athlete.name]
    return max(
        (SequenceMatcher(None, hint_cf, token.casefold()).ratio() for token in candidates),
        default=0.0,
    )


def _best_name_match(hints: Sequence[str], athletes: Sequence[Athlete]) -> tuple[Athlete, str] | None:
    """The single athlete some hint clears the threshold for; None on miss or tie."""
    scored: dict[int, tuple[float, str]] = {}
    for index, athlete in enumerate(athletes):
        for hint in hints:
            score = _name_score(hint, athlete)
            if score >= NAME_SIMILARITY and score > scored.get(index, (0.0, ""))[0]:
                scored[index] = (score, hint)
    if len(scored) != 1:
        return None
    index, (_, hint) = next(iter(scored.items()))
    return athletes[index], hint


def table_supports(value: str, entries: EntryList) -> bool:
    """True if the table could explain this read: exact bib, or a partial of one."""
    if any(a.bib == value for a in entries.athletes):
        return True
    if len(value) < _MIN_PARTIAL_LENGTH:
        return False
    return any(a.bib and value in a.bib for a in entries.athletes)


def trusted_bib_values(bibs: Sequence[Confident[str]], entries: EntryList | None) -> set[str]:
    """Bibs usable as identity constraints: exact roster values or manual corrections.

    Without a roster, retain the existing confidence-based matching behavior.
    """
    roster_bibs = {athlete.bib for athlete in entries.athletes if athlete.bib} if entries and entries.athletes else None
    return {bib.value for bib in bibs if roster_bibs is None or bib.source is Source.MANUAL or bib.value in roster_bibs}


def _attach(subject: Subject, athlete: Athlete, confidence: float, note: str) -> None:
    subject.athlete = Confident(value=athlete, confidence=confidence, source=Source.ROSTER, note=note)


def _recover_bib(subject: Subject, athlete: Athlete, confidence: float, partial: str) -> None:
    subject.bibs.append(
        Confident(
            value=athlete.bib,
            confidence=confidence,
            source=Source.ROSTER,
            note=f"recovered from partial read '{partial}'",
        )
    )


def match_subject(
    subject: Subject,
    hints: Sequence[str],
    entries: EntryList,
    *,
    min_bib_confidence: float = 0.8,
) -> None:
    """Match the roster, allowing a propagated bib to replace an unconfirmed guess."""
    by_bib = {a.bib: a for a in entries.athletes if a.bib}
    if subject.athlete is not None:
        propagated = {
            bib.value
            for bib in subject.bibs
            if bib.source is Source.FACE_MATCH and bib.confidence >= min_bib_confidence and bib.value in by_bib
        }
        if (
            subject.identity_edited
            or any(bib.source is Source.MANUAL for bib in subject.bibs)
            or subject.athlete.source is not Source.ROSTER
            or subject.athlete.confidence >= ATHLETE_AUTO
            or len(propagated) != 1
        ):
            return
        subject.athlete = None

    # exact: strongest confident bib that the table knows
    for bib in sorted(subject.bibs, key=lambda b: b.confidence, reverse=True):
        if bib.confidence < min_bib_confidence:
            break
        athlete = by_bib.get(bib.value)
        if athlete is None:
            continue
        name = _best_name_match(hints, [athlete])
        if name is not None:
            _attach(
                subject, athlete, EXACT_NAME_CONFIRMED, f"bib {bib.value} in entry table; name confirmed by '{name[1]}'"
            )
        else:
            _attach(subject, athlete, EXACT, f"bib {bib.value} in entry table")
        return

    # partial: any read that is a strict substring of table bibs
    for bib in sorted(subject.bibs, key=lambda b: b.confidence, reverse=True):
        value = bib.value
        if len(value) < _MIN_PARTIAL_LENGTH:
            continue
        candidates = [a for a in entries.athletes if a.bib and value != a.bib and value in a.bib]
        if not candidates:
            continue
        if len(candidates) == 1:
            _attach(
                subject, candidates[0], PARTIAL_UNIQUE, f"partial read '{value}' matches only bib {candidates[0].bib}"
            )
            _recover_bib(subject, candidates[0], PARTIAL_UNIQUE, value)
            return
        picked = _best_name_match(hints, candidates)
        if picked is not None:
            athlete, hint = picked
            _attach(
                subject,
                athlete,
                PARTIAL_NAME_PICKED,
                f"partial read '{value}' + name hint '{hint}' -> bib {athlete.bib}",
            )
            _recover_bib(subject, athlete, PARTIAL_NAME_PICKED, value)
            return

    # name only: a suggestion, never auto-confirmed
    picked = _best_name_match(hints, entries.athletes)
    if picked is not None:
        athlete, hint = picked
        _attach(subject, athlete, NAME_ONLY, f"name hint '{hint}' only; no usable bib")


def match_photo(
    subjects: Sequence[Subject],
    hints_per_subject: Sequence[Sequence[str]],
    entries: EntryList,
    *,
    min_bib_confidence: float = 0.8,
) -> None:
    for subject, hints in zip(subjects, hints_per_subject, strict=True):
        match_subject(subject, hints, entries, min_bib_confidence=min_bib_confidence)
