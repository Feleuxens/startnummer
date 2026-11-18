"""Form uploads authenticate and enforce limits before reading excessive bodies."""

import asyncio

import httpx
import pytest
from starlette import formparsers

from tests.test_accounts import HEADERS, HTML, setup
from tests.test_accounts import accounts as accounts

MIB = 1024 * 1024
BATCH = "/api/batches"
PREVIEW = "/api/roster/preview"
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


def browser(app, cookies=None):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver", headers=HEADERS, cookies=cookies
    )


async def unread_body():
    pytest.fail("The server requested body bytes for a rejected upload")
    yield b""


def test_upload_routes_reject_unauthenticated_requests_without_reading_the_body(accounts):
    app, *_ = accounts

    async def scenario():
        async with browser(app) as client:
            for path in (BATCH, PREVIEW):
                response = await client.post(path, content=unread_body(), headers=FORM_HEADERS)
                assert response.status_code == 401
                assert response.headers["cache-control"] == "no-store, private"

    asyncio.run(scenario())


def test_declared_upload_size_is_checked_against_live_installation_settings(accounts):
    app, *_ = accounts
    admin = setup(app)
    settings = {"revision": 0, "max_file_bytes": MIB, "max_batch_bytes": MIB, "session_ttl": 600}
    assert admin.put("/api/admin/settings", json=settings).status_code == 200

    async def scenario():
        async with browser(app, admin.cookies) as client:
            for path, length in ((BATCH, 17 * MIB + 1), (PREVIEW, 11 * MIB + 1)):
                response = await client.post(
                    path, content=unread_body(), headers={**FORM_HEADERS, "Content-Length": str(length)}
                )
                assert response.status_code == 413
            response = await client.post(PREVIEW, files={"roster_file": ("roster.html", HTML)})
            assert response.status_code == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("declared_length", [None, "1024"])
def test_stream_limit_stops_consumption_and_closes_partial_uploads(accounts, monkeypatch, declared_length):
    app, *_ = accounts
    admin = setup(app)
    opened = []
    open_spool = formparsers.SpooledTemporaryFile

    def track_spool(*args, **kwargs):
        file = open_spool(*args, **kwargs)
        opened.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track_spool)

    async def body():
        yield b'--example\r\nContent-Disposition: form-data; name="roster_file"; filename="roster.html"\r\n\r\n'
        chunk = b"x" * MIB
        for _ in range(11):
            yield chunk
        pytest.fail("The server kept reading after the upload went over its limit")

    async def scenario():
        async with browser(app, admin.cookies) as client:
            headers = {"Content-Type": "multipart/form-data; boundary=example"}
            if declared_length is not None:
                headers["Content-Length"] = declared_length
            response = await client.post(PREVIEW, content=body(), headers=headers)
            assert response.status_code == 413
            assert len(opened) == 1 and opened[0].closed

    asyncio.run(scenario())


def test_import_and_preview_share_upload_slots_and_release_them(accounts):
    app, *_ = accounts
    admin = setup(app)

    async def scenario():
        started = [asyncio.Event(), asyncio.Event()]
        release = asyncio.Event()

        async def parked_body(index):
            started[index].set()
            await release.wait()
            yield b"name=Empty"

        async with browser(app, admin.cookies) as client:
            async with asyncio.TaskGroup() as tasks:
                for index, path in enumerate((BATCH, PREVIEW)):
                    tasks.create_task(client.post(path, content=parked_body(index), headers=FORM_HEADERS))
                    await asyncio.wait_for(started[index].wait(), timeout=5)
                try:
                    response = await client.post(BATCH, content=unread_body(), headers=FORM_HEADERS)
                    assert response.status_code == 429 and response.headers["retry-after"] == "5"
                    assert (await client.get(BATCH)).status_code == 200
                finally:
                    release.set()
            assert (await client.post(PREVIEW, files={"roster_file": ("roster.html", HTML)})).status_code == 200

    asyncio.run(scenario())
