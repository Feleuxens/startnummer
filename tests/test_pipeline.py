from uuid import uuid4

import pytest

from startnummer.core.enums import Source, Sport, Status
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete
from startnummer.core.pipeline import analyze_album
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.sports.athletics import AthleticsDiscipline
from startnummer.core.types import BibRead, BoundingBox, FaceDetection, OcrResult, PersonDetection


class FakeDetector:
    def detect(self, image_path):
        return [PersonDetection(box=BoundingBox(0, 0, 100, 200))]


class FakeOcr:
    def __init__(self, reads):
        self.reads = reads

    def read(self, image_path):
        return OcrResult(bibs=self.reads[image_path], texts=[])


class TwoPeople:
    def detect(self, image_path):
        return [
            PersonDetection(box=BoundingBox(0, 0, 100, 200)),
            PersonDetection(box=BoundingBox(100, 0, 200, 200)),
        ]


class FakeFaces:
    def __init__(self, second_person_photo):
        self.second_person_photo = second_person_photo

    def detect(self, image_path):
        faces = [FaceDetection(box=BoundingBox(30, 10, 70, 50), embedding=[1.0, 0.0])]
        if image_path == self.second_person_photo:
            faces.append(FaceDetection(box=BoundingBox(130, 10, 170, 50), embedding=[0.0, 1.0]))
        return faces


def photo_paths(tmp_path, count):
    paths = []
    for i in range(count):
        path = tmp_path / f"photo-{i}.jpg"
        # Adapters are fake: only the core's content hashing reads these bytes.
        path.write_bytes(f"synthetic photo {i}".encode())
        paths.append(str(path))
    return paths


def read(value, confidence=0.96):
    return BibRead(box=BoundingBox(35, 90, 65, 120), value=value, confidence=confidence)


@pytest.mark.parametrize(
    ("values", "expected_status"),
    [
        ([("12", 0.96), ("13", 0.9)], Status.NEEDS_REVIEW),
        ([("12", 0.96), ("12", 0.9)], Status.AUTO),
        ([("12", 0.96), ("13", 0.4)], Status.AUTO),
    ],
)
def test_competing_strong_reads_require_review_after_roster_match(tmp_path, athlete, values, expected_status):
    paths = photo_paths(tmp_path, 1)
    records = analyze_album(
        Album(owner_id=uuid4(), name="Upload batch", sport=Sport.ATHLETICS),
        paths,
        detector=FakeDetector(),
        ocr=FakeOcr({paths[0]: [read(value, confidence) for value, confidence in values]}),
        entry_list=EntryList(athletes=[athlete]),
    )

    assert records[0].subjects[0].athlete.value.name == athlete.name
    assert records[0].status is expected_status
    assert records[0].description == "Alex Example (12, Example Club)"


@pytest.mark.parametrize("meet_name", [None, "Supplied Meet"])
def test_album_propagation_resolves_shared_roster_discipline_and_round_trips(tmp_path, meet_name):
    paths = photo_paths(tmp_path, 2)
    roster = EntryList(
        competition="Roster Meet",
        athletes=[
            Athlete(name="Alex Example", bib="12", entered_events=["100m", "long_jump"]),
            Athlete(name="Sam Example", bib="34", entered_events=["100m", "high_jump"]),
        ],
    )
    # Exercise the same JSON round-trip that a saved worker input will require.
    roster = EntryList.model_validate_json(roster.model_dump_json())
    album = Album(owner_id=uuid4(), name="Upload batch", meet_name=meet_name, sport=Sport.ATHLETICS)
    records = analyze_album(
        album,
        paths,
        detector=TwoPeople(),
        ocr=FakeOcr({paths[0]: [read("12")], paths[1]: [BibRead(BoundingBox(135, 90, 165, 120), "34", 0.96)]}),
        faces=FakeFaces(second_person_photo=paths[1]),
        entry_list=roster,
    )

    assert len(records) == 2
    propagated = records[1].subjects[0]
    assert propagated.athlete.value.name == "Alex Example"
    assert propagated.bibs[0].source is Source.FACE_MATCH
    # The donor frame alone cannot resolve Alex's two entered events. Once the
    # bib propagates, Alex and Sam's only shared event resolves the next frame.
    assert records[0].event.discipline is None
    assert records[1].event.discipline.value is AthleticsDiscipline.M_100
    assert records[1].event.discipline.source is Source.ROSTER
    assert records[1].meet_name == (meet_name or "Roster Meet")
    assert records[1].description == (
        f"Alex Example (12) & Sam Example (34) über 100m/over 100m | {meet_name or 'Roster Meet'}"
    )
    assert all(AnalysisRecord.model_validate_json(r.model_dump_json()) == r for r in records)
    serialized = records[1].model_dump_json()
    assert "embedding" not in serialized
    assert "face_box" not in serialized


def test_pipeline_resolves_only_shared_discipline_for_two_athletes(tmp_path):
    paths = photo_paths(tmp_path, 1)

    records = analyze_album(
        Album(owner_id=uuid4(), name="Upload batch", sport=Sport.ATHLETICS),
        paths,
        detector=TwoPeople(),
        ocr=FakeOcr({paths[0]: [read("12"), BibRead(BoundingBox(135, 90, 165, 120), "34", 0.96)]}),
        entry_list=EntryList(
            athletes=[
                Athlete(name="Alex Example", bib="12", entered_events=["100m", "long_jump"]),
                Athlete(name="Sam Example", bib="34", entered_events=["100m", "high_jump"]),
            ]
        ),
    )

    assert records[0].event.discipline.value is AthleticsDiscipline.M_100
    assert records[0].event.discipline.source is Source.ROSTER
    assert records[0].description == "Alex Example (12) & Sam Example (34) über 100m/over 100m"


def test_failed_photo_is_recorded_and_remaining_photos_continue(tmp_path, athlete):
    paths = photo_paths(tmp_path, 2)

    class SometimesFails(FakeDetector):
        def detect(self, path):
            if path == paths[0]:
                raise RuntimeError("private staging path must not reach stored errors")
            return super().detect(path)

    progress = []
    records = analyze_album(
        Album(owner_id=uuid4(), name="Failure test", sport=Sport.ATHLETICS),
        paths,
        detector=SometimesFails(),
        ocr=FakeOcr({path: [read("12")] for path in paths}),
        entry_list=EntryList(athletes=[athlete]),
        on_progress=lambda completed, total, phase: progress.append((completed, total, phase)),
    )
    assert records[0].status is Status.FAILED
    assert records[0].failure_reason == "Photo analysis failed (RuntimeError)"
    assert records[1].status is Status.AUTO
    assert records[1].description == "Alex Example (12, Example Club)"
    assert progress[-1][:2] == (2, 2)
