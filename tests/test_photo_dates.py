"""Photo dates are metadata, independent of caption revisions and face sessions."""

from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import ExifTags, Image

from startnummer.adapters.photo_dates import capture_time, modified_time
from startnummer.app.api import create_app
from startnummer.app.services import InputPhoto
from startnummer.core.batch import AnalysisDocument, Missing, WorkflowError
from startnummer.core.enums import Status
from startnummer.core.record import AnalysisRecord
from startnummer.core.sports.athletics import AthleticsEvent
from tests.test_workflow import HTML
from tests.test_workflow import environment as environment


def dated_image(value="2025:06:01 12:30:00", *, fraction="123456", format="JPEG"):
    exif = Image.Exif()
    exif[ExifTags.IFD.Exif] = {
        ExifTags.Base.DateTimeOriginal: value,
        ExifTags.Base.SubsecTimeOriginal: fraction,
        ExifTags.Base.BodySerialNumber: "SYNTHETIC-SERIAL-NOT-FOR-RECORDS",
    }
    exif[ExifTags.Base.DateTime] = "2026:01:01 00:00:00"
    output = BytesIO()
    options = {"save_all": True, "append_images": [Image.new("RGB", (10, 10))]} if format == "MPO" else {}
    Image.new("RGB", (20, 30), "gray").save(output, format=format, exif=exif, **options)
    return output.getvalue()


@pytest.mark.parametrize("format", ["JPEG", "MPO", "PNG", "WEBP"])
def test_import_reads_capture_time_once_and_keeps_original_bytes(environment, format):
    service, _ = environment
    data = dated_image(format=format)
    batch = service.import_batch(
        service.settings.owner_id, "Dates", "", [InputPhoto("original.jpg", data)], None, HTML, None
    )
    photo = service.store.get(batch.album.owner_id, batch.album.id).photos[0]
    assert photo.date_taken == datetime(2025, 6, 1, 12, 30, 0, 123456)
    assert photo.date_modified is None and photo.date_taken_read
    assert "SYNTHETIC-SERIAL" not in photo.model_dump_json()
    with service.blobs.open(batch.album.owner_id, photo.blob_key) as original:
        assert original.read() == data


@pytest.mark.parametrize("value", ["", "not a date", "0000:00:00 00:00:00"])
def test_invalid_capture_dates_are_optional_and_never_fall_back_to_modification_time(value):
    with Image.open(BytesIO(dated_image(value))) as image:
        assert capture_time(image) is None


def test_capture_time_does_not_require_subseconds():
    with Image.open(BytesIO(dated_image(fraction=""))) as image:
        assert capture_time(image) == datetime(2025, 6, 1, 12, 30)


def old_batch(service):
    batch = service.import_batch(
        service.settings.owner_id,
        "Older batch",
        "",
        [InputPhoto("photo-2.jpg", dated_image()), InputPhoto("photo-1.jpg", dated_image("2025:06:01 12:31:00"))],
        None,
        HTML,
        None,
    )
    for photo in batch.photos:
        photo.date_modified = photo.date_taken = None
        photo.date_taken_read = False
        photo.analysis = AnalysisDocument(
            record=AnalysisRecord(
                owner_id=batch.album.owner_id,
                album_id=batch.album.id,
                content_hash=photo.content_hash,
                event=AthleticsEvent(),
                status=Status.AUTO,
            )
        )
        photo.caption = "Keep this manual caption"
        photo.caption_edited = True
        photo.approved_revision = photo.revision
    with service.store.transaction(batch.album.owner_id) as session:
        service.store.save(session, batch)
    return batch


def test_existing_albums_get_dates_without_changing_review_state_or_face_sessions(environment, monkeypatch):
    service, _ = environment
    batch = old_batch(service)
    owner, batch_id = batch.album.owner_id, batch.album.id
    service.sessions.put(owner, batch_id, {str(batch.photos[0].id): [{"subject": 0, "box": [0, 0, 10, 10]}]})
    faces = service.sessions.get(owner, batch_id)
    saved = service.read_photo_dates(owner, batch_id)
    for previous, current in zip(batch.photos, saved.photos, strict=True):
        assert current.date_modified is None and current.date_taken is not None
        assert current.date_taken_read and current.approved
        metadata = {"date_modified", "date_taken", "date_taken_read"}
        assert current.model_dump(exclude=metadata) == previous.model_dump(exclude=metadata)
    assert service.sessions.get(owner, batch_id)["session_id"] == faces["session_id"]
    assert service.sessions.get(owner, batch_id)["photos"] == faces["photos"]
    assert service.store.get(owner, batch_id) == saved
    monkeypatch.setattr(service.blobs, "open", lambda *args: pytest.fail("Dates should be cached"))
    assert service.read_photo_dates(owner, batch_id) == saved
    with pytest.raises(Missing):
        service.read_photo_dates(uuid4(), batch_id)


def test_missing_original_rolls_back_metadata_for_the_entire_batch(environment):
    service, _ = environment
    batch = old_batch(service)
    owner = batch.album.owner_id
    (service.settings.blob_root / str(owner) / batch.photos[1].blob_key).unlink()
    with pytest.raises(WorkflowError, match="Could not read photo dates"):
        service.read_photo_dates(owner, batch.album.id)
    assert service.store.get(owner, batch.album.id) == batch


def test_date_metadata_can_be_read_while_analysis_is_queued(environment):
    service, _ = environment
    batch = old_batch(service)
    service.analyze(batch.album.owner_id, batch.album.id)
    jobs = service.store.jobs(batch.album.owner_id, batch.album.id)
    saved = service.read_photo_dates(batch.album.owner_id, batch.album.id)
    assert all(photo.date_taken_read for photo in saved.photos)
    assert service.store.jobs(batch.album.owner_id, batch.album.id) == jobs


@pytest.mark.parametrize("header", ["Sun, 01 Jun 2025 12:00:00 GMT", None, "not a date"])
def test_gallery_import_uses_http_modification_time_without_inventing_missing_dates(environment, monkeypatch, header):
    service, _ = environment
    service.fetch = service._fetch

    @contextmanager
    def stream(method, url, **kwargs):
        response = httpx.Response(
            200,
            request=httpx.Request(method, url),
            content=dated_image(),
            headers={"Last-Modified": header} if header else {},
        )
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr("startnummer.app.services.httpx.stream", stream)
    batch = service.import_batch(
        service.settings.owner_id, "Gallery dates", "", [], "http://gallery.test/album/a", HTML, None
    )
    expected = datetime(2025, 6, 1, 12, tzinfo=UTC) if header and header != "not a date" else None
    assert all(photo.date_modified == expected for photo in batch.photos)
    assert all(photo.date_taken == datetime(2025, 6, 1, 12, 30, 0, 123456) for photo in batch.photos)


@pytest.mark.parametrize("header", [None, "", "broken", "Sun, 01 Jun 2025 12:00:00"])
def test_absent_or_unzoned_http_modification_time_stays_unknown(header):
    assert modified_time(header) is None


def test_upload_dates_are_bound_by_file_position_and_metadata_endpoint_requires_authentication(environment):
    service, _ = environment
    app = create_app(
        service.settings, store=service.store, blobs=service.blobs, sessions=service.sessions, gallery=service.gallery
    )
    headers = {"X-Requested-With": "Startnummer"}
    with TestClient(app) as client:
        assert client.post("/api/batches/" + str(uuid4()) + "/photo-dates", headers=headers).status_code == 401
        client.post("/api/session", json={"username": "photographer", "password": "test-password"}, headers=headers)
        files = [
            ("roster_file", ("roster.html", HTML, "text/html")),
            ("photos", ("same.jpg", dated_image(), "image/jpeg")),
            ("photos", ("same.jpg", dated_image(), "image/jpeg")),
        ]
        response = client.post(
            "/api/batches", data={"photo_modified": '["2025-06-01T12:00:00Z", null]'}, files=files, headers=headers
        )
        assert response.status_code == 200
        batch = response.json()
        assert batch["photos"][0]["date_modified"] == "2025-06-01T12:00:00Z"
        assert batch["photos"][1]["date_modified"] is None
        assert batch["photos"][0]["blob_key"] == batch["photos"][1]["blob_key"]
        assert batch["photos"][0]["id"] != batch["photos"][1]["id"]
        endpoint = "/api/batches/" + batch["album"]["id"] + "/photo-dates"
        assert client.post(endpoint).status_code == 403
        assert client.post(endpoint, headers=headers).status_code == 200
        for value in ("[]", "not JSON", '["2025-06-01T12:00:00"]'):
            assert (
                client.post("/api/batches", data={"photo_modified": value}, files=files, headers=headers).status_code
                == 400
            )
