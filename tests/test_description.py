import pytest

from startnummer.core.description import build_description
from startnummer.core.enums import Source
from startnummer.core.models import Athlete, Confident
from startnummer.core.sports.athletics import AthleticsDiscipline, AthleticsEvent
from startnummer.core.sports.handball import HandballEvent


def test_known_discipline_preserves_bilingual_style(record):
    record.event = AthleticsEvent(
        discipline=Confident(value=AthleticsDiscipline.LONG_JUMP, confidence=0.9, source=Source.ROSTER)
    )

    assert build_description(record) == "Alex Example (12, Example Club) beim Weitsprung/in the Long jump"


@pytest.mark.parametrize("discipline", [None, AthleticsDiscipline.NO_EVENT, AthleticsDiscipline.OTHER])
@pytest.mark.parametrize("meet_name", [None, "Example Meet"])
def test_caption_without_resolved_discipline(record, discipline, meet_name):
    record.meet_name = meet_name
    record.event = AthleticsEvent(
        discipline=Confident(value=discipline, confidence=1, source=Source.MANUAL) if discipline else None
    )

    caption = build_description(record)

    assert caption == "Alex Example (12, Example Club)" + (" | Example Meet" if meet_name else "")


def test_custom_discipline_uses_supplied_label(record):
    record.event = AthleticsEvent(
        discipline=Confident(value=AthleticsDiscipline.OTHER, confidence=1, source=Source.MANUAL),
        custom_label="Standing long jump",
    )

    assert build_description(record) == ("Alex Example (12, Example Club) bei Standing long jump/Standing long jump")


def test_sport_without_discipline_phrase_still_has_caption(record):
    record.event = HandballEvent()

    assert build_description(record) == "Alex Example (12, Example Club)"


def test_meet_name_is_added_without_changing_discipline(record):
    record.meet_name = "  Example Meet  "
    record.event = AthleticsEvent(
        discipline=Confident(value=AthleticsDiscipline.LONG_JUMP, confidence=0.9, source=Source.ROSTER)
    )

    assert build_description(record) == (
        "Alex Example (12, Example Club) beim Weitsprung/in the Long jump | Example Meet"
    )


@pytest.mark.parametrize("meet_name", [None, "   "])
def test_manual_name_without_bib_or_club_has_no_extra_whitespace(record, meet_name):
    record.meet_name = meet_name
    record.subjects[0].athlete = Confident(value=Athlete(name="Sam Example"), confidence=0.5, source=Source.MANUAL)

    assert build_description(record) == "Sam Example"


def test_no_confident_name_does_not_invent_caption(record):
    record.subjects[0].athlete.confidence = 0.5

    assert build_description(record) is None


@pytest.mark.parametrize("club", [None, ""])
def test_bib_is_preserved_when_club_is_missing_or_empty(record, club):
    record.subjects[0].athlete.value.club = club
    assert build_description(record) == "Alex Example (12)"
