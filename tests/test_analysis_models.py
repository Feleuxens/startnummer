import pytest

from startnummer.core.enums import Source, Sport, Status
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete, Confident
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.sports.athletics import AthleticsDiscipline, AthleticsEvent, AthleticsKind
from startnummer.core.sports.handball import HandballDiscipline


@pytest.mark.parametrize(
    "disciplines",
    [
        [AthleticsDiscipline.M_100, AthleticsDiscipline.LONG_JUMP],
        [HandballDiscipline.MATCH],
        ["100m", "unknown_future_slug"],
    ],
)
def test_nonempty_roster_round_trips(disciplines):
    roster = EntryList(
        competition="Example Meet",
        athletes=[Athlete(name="Alex Example", bib="12", entered_events=disciplines)],
    )

    restored = EntryList.model_validate_json(roster.model_dump_json())

    assert restored == roster
    assert restored.athletes[0].entered_events == [str(d) for d in disciplines]


@pytest.mark.parametrize("custom", [False, True])
def test_analyzed_record_round_trips(record, custom):
    record.meet_name = "Example Meet"
    record.event = AthleticsEvent(
        discipline=Confident(
            value=AthleticsDiscipline.OTHER if custom else AthleticsDiscipline.LONG_JUMP,
            confidence=0.9,
            source=Source.MANUAL if custom else Source.ROSTER,
            note="reviewed custom event" if custom else "shared roster discipline",
        ),
        custom_kind=AthleticsKind.JUMP if custom else None,
        custom_label="Standing long jump" if custom else None,
    )
    record.status = Status.NEEDS_REVIEW
    record.extra_tags = ["first", "second"]
    record.description = "A reviewed caption"
    record.subjects[0].bibs.append(Confident(value="13", confidence=0.8, source=Source.OCR, note="competing read"))
    record.subjects.append(record.subjects[0].model_copy(deep=True))

    restored = AnalysisRecord.model_validate_json(record.model_dump_json())

    assert restored == record
    assert restored.model_dump(mode="json") == record.model_dump(mode="json")


def test_meet_name_round_trips_separately_from_album_display_name(record):
    album = Album(
        id=record.album_id,
        owner_id=record.owner_id,
        name="Saturday uploads",
        meet_name="Example Meet",
        sport=Sport.ATHLETICS,
    )

    assert Album.model_validate_json(album.model_dump_json()) == album
    assert album.name != album.meet_name
