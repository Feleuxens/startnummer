from uuid import uuid4

import pytest

from startnummer.core.enums import Source, Sport, Status
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete, Confident, Subject
from startnummer.core.pipeline import analyze_album
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.sports.athletics import AthleticsDiscipline
from startnummer.core.types import BibRead, BoundingBox, FaceDetection, OcrResult, PersonDetection, TextRead


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


def test_propagated_bib_replaces_name_only_roster_guess(tmp_path, athlete):
    paths = photo_paths(tmp_path, 2)
    other = Athlete(name="Other Person", bib="13")

    class NameHintOcr:
        def read(self, path):
            if path == paths[0]:
                return OcrResult([read("12")], [])
            return OcrResult([], [TextRead(BoundingBox(35, 90, 65, 120), "Other", 0.99)])

    records = analyze_album(
        Album(owner_id=uuid4(), name="Synthetic batch", sport=Sport.ATHLETICS),
        paths,
        detector=FakeDetector(),
        ocr=NameHintOcr(),
        faces=FakeFaces(second_person_photo=None),
        entry_list=EntryList(athletes=[athlete, other]),
    )
    target = records[1].subjects[0]
    assert target.bibs[0].source is Source.FACE_MATCH
    assert target.athlete.value == athlete
    assert target.athlete.confidence >= 0.8
    assert "Alex Example" in records[1].description
    assert "Other Person" not in records[1].description


@pytest.mark.parametrize("protection", ["manual_name", "edited_identity", "manual_bib", "strong_match"])
def test_propagated_bib_preserves_confirmed_identity(athlete, protection):
    from startnummer.core.entrytable import match_subject

    other = Athlete(name="Other Person", bib="13")
    subject = Subject(
        athlete=Confident(value=other, confidence=0.5, source=Source.ROSTER),
        bibs=[Confident(value="12", confidence=0.9, source=Source.FACE_MATCH)],
    )
    if protection == "manual_name":
        subject.athlete.source = Source.MANUAL
    elif protection == "edited_identity":
        subject.identity_edited = True
    elif protection == "manual_bib":
        subject.bibs.append(Confident(value="13", confidence=1, source=Source.MANUAL))
    else:
        subject.athlete.confidence = 0.95
    before = subject.model_copy(deep=True)
    match_subject(subject, [], EntryList(athletes=[athlete, other]))
    assert subject == before


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


@pytest.mark.parametrize("noisy_source", [False, True])
def test_unsupported_read_does_not_split_faces_or_displace_a_roster_bib(tmp_path, noisy_source):
    paths = photo_paths(tmp_path, 2)
    roster = EntryList(athletes=[Athlete(name="Alex Example", bib="12")])
    groups = []
    records = analyze_album(
        Album(owner_id=uuid4(), name="Synthetic batch", sport=Sport.ATHLETICS),
        paths,
        detector=FakeDetector(),
        ocr=FakeOcr(
            {
                paths[0]: [read("2030", 0.99), read("12")] if noisy_source else [read("12")],
                paths[1]: [] if noisy_source else [read("2030", 0.99)],
            }
        ),
        faces=FakeFaces(second_person_photo="unused"),
        entry_list=roster,
        on_face_groups=lambda result: groups.extend(result),
    )
    assert len(groups) == 1 and set(groups[0]) == {(0, 0), (1, 0)}
    assert records[1].subjects[0].athlete.value.bib == "12"
    assert any(b.value == "12" and b.source is Source.FACE_MATCH for b in records[1].subjects[0].bibs)
    assert not any(
        b.value == "2030" and b.source is Source.FACE_MATCH for r in records for s in r.subjects for b in s.bibs
    )
    noisy = records[0 if noisy_source else 1]
    assert any(b.value == "2030" and b.source is Source.OCR for b in noisy.subjects[0].bibs)
    assert noisy.status is Status.NEEDS_REVIEW


@pytest.mark.parametrize("with_roster", [False, True])
def test_unknown_read_is_not_donated_when_a_roster_is_present(tmp_path, with_roster):
    paths = photo_paths(tmp_path, 2)
    records = analyze_album(
        Album(owner_id=uuid4(), name="Synthetic batch", sport=Sport.ATHLETICS),
        paths,
        detector=FakeDetector(),
        ocr=FakeOcr({paths[0]: [read("2030")], paths[1]: []}),
        faces=FakeFaces(second_person_photo="unused"),
        entry_list=EntryList(athletes=[Athlete(name="Alex Example", bib="12")]) if with_roster else None,
    )
    assert records[0].subjects[0].bibs[0].value == "2030"
    assert bool(records[1].subjects[0].bibs) is not with_roster


def test_year_shaped_roster_bibs_still_prevent_conflicting_face_matches(tmp_path):
    paths = photo_paths(tmp_path, 2)
    groups = []
    records = analyze_album(
        Album(owner_id=uuid4(), name="Synthetic batch", sport=Sport.ATHLETICS),
        paths,
        detector=FakeDetector(),
        ocr=FakeOcr({paths[0]: [read("12")], paths[1]: [read("2030")]}),
        faces=FakeFaces(second_person_photo="unused"),
        entry_list=EntryList(
            athletes=[Athlete(name="Alex Example", bib="12"), Athlete(name="Other Athlete", bib="2030")]
        ),
        on_face_groups=lambda result: groups.extend(result),
    )
    assert len(groups) == 2
    assert [[bib.value for bib in r.subjects[0].bibs] for r in records] == [["12"], ["2030"]]
