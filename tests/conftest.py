from uuid import uuid4

import pytest

from startnummer.core.enums import Source
from startnummer.core.models import Athlete, Confident, Subject
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports.athletics import AthleticsDiscipline, AthleticsEvent


@pytest.fixture
def athlete() -> Athlete:
    return Athlete(
        name="Alex Example",
        bib="12",
        club="Example Club",
        entered_events=[AthleticsDiscipline.M_100, AthleticsDiscipline.LONG_JUMP],
    )


@pytest.fixture
def record(athlete: Athlete) -> AnalysisRecord:
    return AnalysisRecord(
        owner_id=uuid4(),
        album_id=uuid4(),
        content_hash="sha256:" + "a" * 64,
        event=AthleticsEvent(),
        subjects=[
            Subject(
                bibs=[Confident(value="12", confidence=0.96, source=Source.OCR, note="clear read")],
                athlete=Confident(value=athlete, confidence=0.95, source=Source.ROSTER, note="exact bib"),
            )
        ],
    )
