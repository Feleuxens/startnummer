"""Atomic corrections and per-photo caption inclusion without removing evidence."""

from uuid import uuid4

import pytest

from startnummer.app.contracts import Edit, SubjectEdit
from startnummer.app.services import Services
from startnummer.core.batch import Conflict, Missing, WorkflowError
from startnummer.core.description import build_description
from startnummer.core.enums import Source
from startnummer.core.models import Athlete, Confident, Subject
from tests.test_workflow import analyzed
from tests.test_workflow import environment as environment


def review_batch(service):
    batch = analyzed(service)
    batch.roster.athletes.append(Athlete(name="Sam Example", bib="77", club="Other Club", entered_events=["long_jump"]))
    photo = batch.photos[0]
    photo.analysis.record.subjects = [
        Subject(
            athlete=Confident(value=athlete, confidence=0.95, source=Source.ROSTER),
            bibs=[Confident(value=athlete.bib, confidence=0.95, source=Source.OCR)],
        )
        for athlete in batch.roster.athletes
    ]
    photo.proposal = photo.caption = photo.analysis.record.description = build_description(photo.analysis.record)
    photo.approved_revision = photo.revision
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    return batch, photo


def test_multiple_subjects_are_corrected_and_captioned_in_one_revision(environment):
    service, _ = environment
    batch, photo = review_batch(service)
    saved = service.edit(
        batch.album.owner_id,
        batch.album.id,
        photo.id,
        Edit(
            revision=photo.revision,
            subjects=[
                SubjectEdit(subject=0, bib="77", roster_bib="77", club="Updated club"),
                SubjectEdit(subject=1, athlete_name="Visitor Example", club="Visitor Club"),
            ],
        ),
    )
    subjects = saved.analysis.record.subjects
    assert subjects[0].athlete.value.name == "Sam Example"
    assert subjects[0].athlete.value.club == "Updated club"
    assert subjects[0].bibs[0].value == "77"
    assert subjects[1].athlete.value.name == "Visitor Example"
    assert subjects[1].athlete.value.club == "Visitor Club"
    assert all(subject.identity_edited and subject.athlete.source is Source.MANUAL for subject in subjects)
    assert (
        saved.caption
        == "Sam Example (77, Updated club) & Visitor Example (Visitor Club) beim Weitsprung/in the Long jump"
    )
    assert saved.revision == photo.revision + 1 and not saved.approved
    assert service.store.get(batch.album.owner_id, batch.album.id).photos[1] == batch.photos[1]


@pytest.mark.parametrize(
    "invalid",
    [
        SubjectEdit(subject=9, athlete_name="Invalid subject"),
        SubjectEdit(subject=1, roster_bib="missing"),
        SubjectEdit(subject=1, athlete_name=""),
        SubjectEdit(subject=1, excluded_from_caption=None),
        SubjectEdit(subject=1, athlete_name="Expired face", face_session_id="expired"),
    ],
)
def test_invalid_subject_correction_rolls_back_every_change(environment, invalid):
    service, _ = environment
    batch, photo = review_batch(service)
    with pytest.raises(WorkflowError):
        service.edit(
            batch.album.owner_id,
            batch.album.id,
            photo.id,
            Edit(
                revision=photo.revision,
                subjects=[SubjectEdit(subject=0, athlete_name="Pending name"), invalid],
            ),
        )
    assert service.store.get(batch.album.owner_id, batch.album.id) == batch


def test_exclusion_preserves_evidence_and_face_indexes_and_can_be_reversed(environment):
    service, _ = environment
    batch, photo = review_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    service.sessions.put(
        owner,
        batch_id,
        {
            str(photo.id): [
                {"subject": 0, "box": [0, 0, 20, 20]},
                {"subject": 1, "box": [30, 0, 50, 20]},
            ]
        },
    )
    geometry = service.sessions.get(owner, batch_id)
    saved = service.edit(
        owner,
        batch_id,
        photo.id,
        Edit(
            revision=photo.revision,
            subjects=[SubjectEdit(subject=0, excluded_from_caption=True)],
        ),
    )
    assert saved.caption == "Sam Example (77, Other Club) beim Weitsprung/in the Long jump"
    assert saved.analysis.record.subjects[0].model_dump(exclude={"excluded_from_caption"}) == (
        photo.analysis.record.subjects[0].model_dump(exclude={"excluded_from_caption"})
    )
    assert saved.analysis.record.subjects[1] == photo.analysis.record.subjects[1]
    assert saved.analysis.record.subjects[0].excluded_from_caption
    assert not saved.approved
    session = service.sessions.get(owner, batch_id)
    assert session["photos"] == geometry["photos"]
    assert session["session_id"] == geometry["session_id"] and session["available"]
    assert service.store.get(owner, batch_id).photo(photo.id) == saved
    restored = service.edit(
        owner,
        batch_id,
        photo.id,
        Edit(
            revision=saved.revision,
            subjects=[SubjectEdit(subject=0, excluded_from_caption=False)],
        ),
    )
    assert restored.caption == photo.caption
    assert len(restored.analysis.record.subjects) == 2


def test_manual_caption_is_preserved_until_generated_caption_is_explicitly_selected(environment):
    service, _ = environment
    batch, photo = review_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    manual = service.edit(owner, batch_id, photo.id, Edit(revision=photo.revision, caption="My edited caption"))
    excluded = service.edit(
        owner,
        batch_id,
        photo.id,
        Edit(
            revision=manual.revision,
            subjects=[SubjectEdit(subject=0, excluded_from_caption=True)],
        ),
    )
    assert excluded.caption == "My edited caption" and excluded.caption_edited
    assert "Alex Example" not in excluded.proposal
    generated = service.edit(owner, batch_id, photo.id, Edit(revision=excluded.revision, use_generated_caption=True))
    assert generated.caption == excluded.proposal and not generated.caption_edited
    blank = service.edit(
        owner,
        batch_id,
        photo.id,
        Edit(
            revision=generated.revision,
            subjects=[SubjectEdit(subject=1, excluded_from_caption=True)],
        ),
    )
    assert blank.caption is None and blank.proposal is None and not blank.can_approve


def test_exclusion_survives_reruns_and_name_propagation(environment):
    service, _ = environment
    batch, photo = review_batch(service)
    saved = service.edit(
        batch.album.owner_id,
        batch.album.id,
        photo.id,
        Edit(
            revision=photo.revision,
            subjects=[SubjectEdit(subject=0, excluded_from_caption=True)],
        ),
    )
    batch = service.store.get(batch.album.owner_id, batch.album.id)
    results = {p.id: p.analysis.model_copy(deep=True) for p in batch.photos}
    results[photo.id].record.subjects = []
    retained = Services.merge_analysis(batch, results)
    assert photo.id in retained
    assert batch.photo(photo.id).analysis.record.subjects == saved.analysis.record.subjects
    Services._assign_face_name(batch.photo(photo.id), 0, Athlete(name="Propagated Example"))
    assert batch.photo(photo.id).analysis.record.subjects[0].excluded_from_caption
    assert "Propagated Example" not in batch.photo(photo.id).caption


def test_subject_edits_check_owner_revision_busy_and_ambiguous_requests(environment):
    service, _ = environment
    batch, photo = review_batch(service)
    correction = SubjectEdit(subject=0, excluded_from_caption=True)
    with pytest.raises(Missing):
        service.edit(uuid4(), batch.album.id, photo.id, Edit(revision=photo.revision, subjects=[correction]))
    with pytest.raises(Conflict, match="changed"):
        service.edit(
            batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision + 1, subjects=[correction])
        )
    for values in (
        {"subjects": [correction, correction]},
        {"subjects": [correction], "subject": 0, "club": "Conflicting edit"},
        {"use_generated_caption": True, "caption": "Conflicting caption"},
    ):
        with pytest.raises(WorkflowError):
            service.edit(batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, **values))
    assert service.store.get(batch.album.owner_id, batch.album.id) == batch
    service.analyze(batch.album.owner_id, batch.album.id)
    with pytest.raises(Conflict, match="analysis to finish"):
        service.edit(
            batch.album.owner_id, batch.album.id, photo.id, Edit(revision=photo.revision, subjects=[correction])
        )


def test_older_subject_records_default_to_included():
    subject = Subject.model_validate({"bibs": [], "athlete": None})
    assert not subject.excluded_from_caption
