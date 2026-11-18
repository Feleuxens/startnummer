"""Authenticate and limit form uploads before FastAPI parses the body."""

from threading import BoundedSemaphore

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException

MIB = 1024 * 1024
ROSTER_FILE_LIMIT = 10 * MIB
BATCH_FORM_ALLOWANCE = 16 * MIB  # Roster, text fields, and multipart framing.
ROSTER_PREVIEW_PATH = "/api/roster/preview"
MAX_CONCURRENT_UPLOADS = 2


def upload_router(authenticate, batch_photo_limit):
    slots = BoundedSemaphore(MAX_CONCURRENT_UPLOADS)

    class UploadRoute(APIRoute):
        def get_route_handler(self):
            handle = super().get_route_handler()

            async def guarded(request: Request):
                await run_in_threadpool(authenticate, request)
                if not slots.acquire(blocking=False):
                    raise HTTPException(429, "Too many uploads in progress; try again shortly", {"Retry-After": "5"})
                try:
                    limit = (
                        ROSTER_FILE_LIMIT + MIB
                        if self.path == ROSTER_PREVIEW_PATH
                        else await run_in_threadpool(batch_photo_limit) + BATCH_FORM_ALLOWANCE
                    )
                    return await handle_limited(request, handle, limit)
                finally:
                    slots.release()

            return guarded

    return APIRouter(route_class=UploadRoute)


async def handle_limited(request, handle, limit):
    message = "Upload request exceeds the configured size limit"
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(400, "Invalid Content-Length") from None
    if length < 0:
        raise HTTPException(400, "Invalid Content-Length")
    if length > limit:
        raise HTTPException(413, message)

    received = 0
    too_large = False

    async def receive():
        nonlocal received, too_large
        event = await request.receive()
        if event["type"] == "http.disconnect":
            raise MultiPartException("Upload disconnected")
        if event["type"] == "http.request":
            received += len(event.get("body", b""))
            if received > limit:
                too_large = True
                # Starlette closes partially spooled files on multipart errors.
                raise MultiPartException(message)
        return event

    try:
        return await handle(Request(request.scope, receive))
    except StarletteHTTPException:
        if too_large:  # Starlette exposes multipart errors as HTTP 400.
            raise HTTPException(413, message) from None
        raise
