"""Both roster formats share URL/upload transport and saved-batch behavior."""

import pytest

from startnummer.app.services import InputPhoto
from startnummer.core.entrytable import match_subject
from startnummer.core.enums import Source
from startnummer.core.models import Confident, Subject
from tests.test_entrylist_parser import results_html
from tests.test_workflow import HTML, image_bytes
from tests.test_workflow import environment as environment


@pytest.mark.parametrize("gallery", [False, True])
@pytest.mark.parametrize("roster_url", [False, True])
def test_results_import_with_every_photo_and_roster_source_pairing(environment, gallery, roster_url):
    service, _ = environment
    content = results_html().encode()
    fetched = []

    def fetch(url, *, roster=False):
        fetched.append((url, roster))
        return content if roster else image_bytes()

    service.fetch = fetch
    url = "https://roster.test/Competitions/Resultoverview/123"
    batch = service.import_batch(
        service.settings.owner_id,
        "Result roster",
        "Example Meet",
        [] if gallery else [InputPhoto("original.jpg", image_bytes())],
        "http://gallery.test/album/a" if gallery else None,
        None if roster_url else content,
        url if roster_url else None,
    )
    restored = service.store.get(batch.album.owner_id, batch.album.id)
    assert restored == batch
    assert len(restored.roster.athletes) == 1
    athlete = restored.roster.by_bib("345")
    assert athlete is not None and athlete.name == "Alex Example"
    assert athlete.entered_events == ["100m", "long_jump"]
    assert bool([request for request in fetched if request[1]]) is roster_url
    assert all(bool(photo.destination) is gallery for photo in restored.photos)
    subject = Subject(bibs=[Confident(value="345", confidence=0.99, source=Source.OCR)])
    match_subject(subject, [], restored.roster)
    assert subject.athlete.value == athlete and subject.athlete.source is Source.ROSTER


def test_entry_list_without_bibs_and_results_with_bibs_remain_separate_explicit_sources(environment):
    service, _ = environment
    entry_list = service.import_batch(
        service.settings.owner_id,
        "Entries",
        "",
        [InputPhoto("original.jpg", image_bytes())],
        None,
        HTML.replace(b"<div>12</div>", b"<div></div>"),
        None,
    )
    results = service.import_batch(
        service.settings.owner_id,
        "Results",
        "",
        [InputPhoto("original.jpg", image_bytes())],
        None,
        results_html().encode(),
        None,
    )
    assert not entry_list.roster.athletes[0].bib
    assert results.roster.athletes[0].bib == "345"
    assert service.store.get(entry_list.album.owner_id, entry_list.album.id).roster == entry_list.roster
