"""Roster name order is explicit, reviewable, and independent of bibs or birth years."""

import pytest
from fastapi.testclient import TestClient

from startnummer.adapters.entrylist.ergebnisse_leichtathletik_de import LeichtathletikDeEntryListParser
from startnummer.adapters.entrylist.names import parse_name
from startnummer.app.api import create_app
from startnummer.app.contracts import Edit, RosterNameEdit, SubjectEdit
from startnummer.app.services import InputPhoto
from startnummer.core.batch import Conflict, WorkflowError
from startnummer.core.enums import NameOrder, Source
from startnummer.core.interfaces import EntryList
from tests.test_entrylist_parser import competitor_row, result_row, result_section
from tests.test_subject_review import review_batch
from tests.test_workflow import environment as environment
from tests.test_workflow import image_bytes


@pytest.mark.parametrize(
    ("raw", "expected", "order", "uncertain"),
    [
        ("EXAMPLE Alex", "Alex Example", "surname_first", False),
        ("Alex EXAMPLE", "Alex Example", "given_first", False),
        ("VAN EXAMPLE Alex Sam", "Alex Sam van Example", "surname_first", False),
        ("Alex Sam VAN EXAMPLE", "Alex Sam van Example", "given_first", False),
        ("van EXAMPLE Alex", "Alex van Example", "surname_first", False),
        ("VAN Example Alex", "Alex van Example", "surname_first", True),
        ("Alex van EXAMPLE", "Alex van Example", "given_first", False),
        ("van Example Alex", "Alex van Example", "surname_first", True),
        ("Van De Example Alex", "Alex Van De Example", "surname_first", True),
        ("Example Alex Sam", "Alex Sam Example", "surname_first", True),
        ("von Example, Alex Sam", "Alex Sam von Example", "surname_first", False),
        ("Alex K.", "Alex K.", "given_first", False),
        ("Alex K", "Alex K", "given_first", False),
        ("Alex Sam K.", "Alex Sam K.", "given_first", False),
        ("K. Alex", "Alex K.", "surname_first", False),
        ("ALEX EXAMPLE", "Alex Example", "as_written", True),
        ("Alex", "Alex", "as_written", False),
        ("  EXAMPLE-SAMPLE   Alex ", "Alex Example-Sample", "surname_first", False),
        ("ÉXAMPLE Alex", "Alex Éxample", "surname_first", False),
        ("O'EXAMPLE Alex", "Alex O'Example", "surname_first", False),
        ("McExample Alex", "Alex McExample", "surname_first", True),
        ("DeExample Alex", "Alex DeExample", "surname_first", True),
        ("EXAMPLE Alex K.", "Example Alex K.", "given_first", False),
        ("EXAMPLE", "Example", "as_written", False),
    ],
)
def test_auto_names_normalize_capitals_and_preserve_mixed_case_and_initials(raw, expected, order, uncertain):
    name, details = parse_name(raw)
    assert name == expected
    assert details.source_name == " ".join(raw.split())
    assert details.order == order and details.needs_review is uncertain


@pytest.mark.parametrize(
    ("raw", "order", "expected"),
    [
        ("Alex EXAMPLE", "surname_first", "Example Alex"),
        ("EXAMPLE Alex", "given_first", "Example Alex"),
        ("Example, Alex", "as_written", "Example, Alex"),
        ("Example Alex", "given_first", "Example Alex"),
        ("Example Alex", "surname_first", "Alex Example"),
        ("Van De Example Alex", "surname_first", "Alex Van De Example"),
        ("EXAMPLE FAMILY Alex", "surname_first", "Alex Example Family"),
        ("EXAMPLE Alex", "as_written", "Example Alex"),
        ("VAN EXAMPLE, ALEX K.", "as_written", "van Example, Alex K."),
    ],
)
def test_forced_formats_take_precedence(raw, order, expected):
    name, details = parse_name(raw, NameOrder(order))
    assert name == expected and not details.needs_review


@pytest.mark.parametrize("result", [False, True])
@pytest.mark.parametrize("year", ["", "2008"])
@pytest.mark.parametrize("raw", ["Alex K.", "Alex EXAMPLE", "VAN EXAMPLE Alex", "Example Alex"])
def test_both_layouts_use_the_same_name_rules_regardless_of_birth_year(result, year, raw):
    html = result_section("100m", result_row(name=raw, year=year)) if result else competitor_row(name=raw, year=year)
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    expected, details = parse_name(raw)
    assert roster.athletes[0].name == expected and roster.name_parsing == [details]
    assert EntryList.model_validate_json(roster.model_dump_json()) == roster


def test_results_keep_name_metadata_aligned_after_deduplication_and_relays():
    html = result_section("100m", result_row(name="EXAMPLE Alex"), result_row(name="EXAMPLE Alex"))
    html += result_section(
        "4x100m", result_row(bib="", name="Example Club", year="", club="Example, Alex (2006); Other, Sam (2005);")
    )
    roster = LeichtathletikDeEntryListParser().parse_content(html)
    assert [a.name for a in roster.athletes] == ["Alex Example", "Sam Other"]
    assert [n.source_name for n in roster.name_parsing] == ["EXAMPLE Alex", "Other, Sam"]
    assert roster.athletes[0].entered_events == ["100m", "4x100m"]


def test_preview_and_corrected_import_are_bound_to_the_same_roster(environment):
    service, _ = environment
    content = competitor_row(name="Example Alex").encode()
    preview = service.preview_roster(content, None)
    assert not service.store.list_batches(service.settings.owner_id)
    assert not service.settings.blob_root.exists()
    batch = service.import_batch(
        service.settings.owner_id,
        "Names",
        "",
        [InputPhoto("photo.jpg", image_bytes())],
        None,
        content,
        None,
        roster_digest=preview.digest,
        roster_names=[RosterNameEdit(index=0, name="  Alex  Sample ")],
    )
    assert batch.roster.athletes[0].name == "Alex Sample"
    assert batch.roster.name_parsing[0].source_name == "Example Alex"
    assert not batch.roster.name_parsing[0].needs_review
    assert service.store.get(batch.album.owner_id, batch.album.id) == batch
    with pytest.raises(Conflict, match="Roster changed"):
        service.import_batch(
            service.settings.owner_id,
            "",
            "",
            [InputPhoto("photo.jpg", image_bytes())],
            None,
            competitor_row(name="Other Sam").encode(),
            None,
            roster_digest=preview.digest,
            roster_names=[RosterNameEdit(index=0, name="Alex Sample")],
        )


@pytest.mark.parametrize(
    "corrections", [[RosterNameEdit(index=8, name="Example")], [RosterNameEdit(index=0, name="Example")] * 2]
)
def test_invalid_corrections_do_not_write_photos(environment, corrections):
    service, _ = environment
    content = competitor_row().encode()
    preview = service.preview_roster(content, None)
    with pytest.raises(WorkflowError):
        service.import_batch(
            service.settings.owner_id,
            "",
            "",
            [InputPhoto("p.jpg", image_bytes())],
            None,
            content,
            None,
            roster_digest=preview.digest,
            roster_names=corrections,
        )
    assert not service.settings.blob_root.exists()


def test_roster_indexes_assign_people_without_bibs_and_keep_legacy_bib_corrections(environment):
    service, _ = environment
    batch, photo = review_batch(service)
    batch.roster.athletes[1].bib = None
    with service.store.transaction(batch.album.owner_id) as db:
        service.store.save(db, batch)
    saved = service.edit(
        batch.album.owner_id,
        batch.album.id,
        photo.id,
        Edit(revision=photo.revision, subjects=[SubjectEdit(subject=0, roster_index=1)]),
    )
    identity = saved.analysis.record.subjects[0].athlete
    assert identity.source is Source.MANUAL and identity.value.name == "Sam Example" and identity.value.bib is None
    assert "Sam Example" in saved.caption
    for correction in (
        SubjectEdit(subject=0, roster_index=99),
        SubjectEdit(subject=0, roster_index=0, roster_bib="12"),
    ):
        with pytest.raises(WorkflowError):
            service.edit(
                batch.album.owner_id, batch.album.id, photo.id, Edit(revision=saved.revision, subjects=[correction])
            )
        assert service.store.get(batch.album.owner_id, batch.album.id).photo(photo.id) == saved
    legacy = service.edit(
        batch.album.owner_id, batch.album.id, photo.id, Edit(revision=saved.revision, roster_bib="12", subject=0)
    )
    assert legacy.analysis.record.subjects[0].athlete.value.name == "Alex Example"


def test_http_preview_upload_url_formats_and_corrections(environment):
    service, fetched = environment
    app = create_app(
        service.settings, store=service.store, blobs=service.blobs, sessions=service.sessions, fetch=service.fetch
    )
    headers = {"X-Requested-With": "Startnummer"}
    files = {"roster_file": ("roster.html", competitor_row(name="Alex EXAMPLE").encode(), "text/html")}
    with TestClient(app) as client:
        assert client.post("/api/roster/preview", files=files, headers=headers).status_code == 401
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        assert client.post("/api/roster/preview", files=files).status_code == 403
        preview = client.post("/api/roster/preview", files=files, headers=headers)
        assert preview.status_code == 200 and preview.json()["roster"]["athletes"][0]["name"] == "Alex Example"
        forced = client.post("/api/roster/preview", files=files, data={"name_order": "surname_first"}, headers=headers)
        assert forced.json()["roster"]["athletes"][0]["name"] == "Example Alex"
        assert (
            client.post(
                "/api/roster/preview", data={"roster_url": "https://roster.test/roster"}, headers=headers
            ).status_code
            == 200
        )
        assert fetched[-1][1] is True
        assert (
            client.post(
                "/api/roster/preview", files=files, data={"name_order": "invented"}, headers=headers
            ).status_code
            == 422
        )
        imported = client.post(
            "/api/batches",
            files=[*files.items(), ("photos", ("p.jpg", image_bytes(), "image/jpeg"))],
            data={"roster_digest": preview.json()["digest"], "roster_names": '[{"index":0,"name":"Alex Corrected"}]'},
            headers=headers,
        )
        assert imported.status_code == 200 and imported.json()["roster"]["athletes"][0]["name"] == "Alex Corrected"
        for edits in ("not json", '[{"index":0,"name":" "}]', '[{"index":-1,"name":"Alex"}]'):
            assert (
                client.post("/api/batches", files=files, data={"roster_names": edits}, headers=headers).status_code
                == 400
            )
