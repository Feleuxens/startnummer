"""HTTP API for batch imports, review, and publishing."""

import hashlib
import hmac
import time
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.chevereto import Chevereto
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import HttpFaceSessions
from startnummer.app.contracts import (
    BatchSummary,
    BatchView,
    ChangePreview,
    DisciplineOption,
    Edit,
    FaceView,
    Login,
    Revision,
    Selected,
    SessionInfo,
)
from startnummer.app.services import InputPhoto, Services, run
from startnummer.app.settings import Settings
from startnummer.core.batch import Batch, Conflict, Job, Missing, Photo, Publication, WorkflowError, WriteResult
from startnummer.core.errors import BlobNotFound
from startnummer.core.sports.athletics import AthleticsDiscipline


def create_app(settings: Settings | None = None, *, store=None, blobs=None, sessions=None, gallery=None, fetch=None):
    settings = settings or Settings.from_env()
    store = store or Store(create_engine(settings.database_url, pool_pre_ping=True))
    blobs = blobs or FilesystemBlobStore(settings.blob_root)
    sessions = sessions or HttpFaceSessions(settings.worker_url, settings.worker_secret)
    if gallery is None and settings.chevereto_url and settings.chevereto_dsn:
        gallery = Chevereto(settings.chevereto_url, settings.chevereto_dsn)
    service = Services(store, blobs, settings, sessions, gallery, fetch)
    app = FastAPI(title="Startnummer", version="0.1.0", openapi_url="/api/openapi.json", docs_url="/api/docs")
    app.state.services = service

    @app.middleware("http")
    async def private_responses(request, call_next):
        if "owner_id" in request.query_params:
            return JSONResponse({"detail": "Owner is derived from authentication"}, status_code=400)
        if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("x-requested-with") != "Startnummer":
                return JSONResponse({"detail": "Missing same-origin request header"}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlparse

                if urlparse(origin).netloc != request.headers.get("host"):
                    return JSONResponse({"detail": "Cross-origin write rejected"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(WorkflowError)
    async def workflow_error(request, exc):
        status = 404 if isinstance(exc, Missing) else 409 if isinstance(exc, Conflict) else 400
        return JSONResponse({"detail": str(exc)}, status_code=status)

    def signature(payload):
        return hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def principal(request: Request) -> UUID:
        cookie = request.cookies.get("startnummer_session", "")
        try:
            identity, expires, supplied = cookie.split(".")
            payload = identity + "." + expires
            if not hmac.compare_digest(supplied, signature(payload)) or int(expires) <= time.time():
                raise ValueError
            if identity != str(settings.owner_id):
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(401, "Sign in to Startnummer") from None
        return settings.owner_id

    Owner = Annotated[UUID, Depends(principal)]

    async def validate_import_fields(request: Request):
        form = await request.form()
        allowed = {"import_id", "name", "meet_name", "gallery_url", "roster_url", "roster_file", "photos"}
        if set(form) - allowed:
            raise WorkflowError("Unknown import field; ownership comes from authentication")

    @app.post("/api/session", response_model=SessionInfo)
    def login(body: Login, response: Response) -> dict:
        if not hmac.compare_digest(body.username.encode(), settings.username.encode()) or not hmac.compare_digest(
            body.password.encode(), settings.password.encode()
        ):
            raise HTTPException(401, "Invalid username or password")
        payload = f"{settings.owner_id}.{int(time.time()) + 12 * 3600}"
        response.set_cookie(
            "startnummer_session",
            payload + "." + signature(payload),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=12 * 3600,
        )
        return {"username": settings.username, "gallery_url": settings.chevereto_url}

    @app.get("/api/session", response_model=SessionInfo)
    def session_info(owner: Owner) -> dict:
        return {"username": settings.username, "gallery_url": settings.chevereto_url}

    @app.delete("/api/session")
    def logout(owner: Owner, response: Response) -> dict:
        # Clear the owner's face sessions before ending the login session.
        for batch in store.list_batches(owner):
            if sessions.get(owner, batch["id"])["available"]:
                sessions.finish(owner, batch["id"])
        response.delete_cookie("startnummer_session")
        return {"signed_out": True}

    @app.get("/api/batches", response_model=list[BatchSummary])
    def list_batches(owner: Owner) -> list[dict]:
        store.cleanup(owner, lambda key: run(blobs.delete(owner, key)))
        return store.list_batches(owner)

    @app.post("/api/batches", response_model=Batch, dependencies=[Depends(validate_import_fields)])
    def import_batch(
        owner: Owner,
        import_id: Annotated[UUID | None, Form()] = None,
        name: Annotated[str, Form()] = "",
        meet_name: Annotated[str, Form()] = "",
        gallery_url: Annotated[str | None, Form()] = None,
        roster_url: Annotated[str | None, Form()] = None,
        roster_file: Annotated[UploadFile | None, File()] = None,
        photos: Annotated[list[UploadFile] | None, File()] = None,
    ):
        inputs = []
        total = 0
        for photo in photos or []:
            data = photo.file.read(settings.max_file_bytes + 1)
            total += len(data)
            if len(data) > settings.max_file_bytes or total > settings.max_batch_bytes:
                raise WorkflowError("Upload exceeds the configured size limit")
            inputs.append(InputPhoto(photo.filename or "photo", data))
        html = roster_file.file.read(10 * 1024 * 1024 + 1) if roster_file else None
        if html and len(html) > 10 * 1024 * 1024:
            raise WorkflowError("Roster exceeds the size limit")
        return service.import_batch(owner, name, meet_name, inputs, gallery_url, html, roster_url, import_id)

    @app.get("/api/batches/{batch_id}", response_model=BatchView)
    def get_batch(batch_id: UUID, owner: Owner):
        with store.transaction() as db:
            batch = store.load(db, owner, batch_id)
            publications = store.publications(db, owner, batch_id)
        return BatchView(batch=batch, publications=publications, jobs=store.jobs(owner, batch_id))

    @app.delete("/api/batches/{batch_id}")
    def delete_batch(batch_id: UUID, owner: Owner) -> dict:
        service.delete_batch(owner, batch_id)
        return {"deleted": True}

    @app.post("/api/batches/{batch_id}/analysis", response_model=Job)
    def analyze(batch_id: UUID, owner: Owner):
        # Discard old face selectors before new subject indexes arrive.
        store.get(owner, batch_id)
        if sessions.get(owner, batch_id)["available"]:
            sessions.finish(owner, batch_id)
        return store.enqueue(owner, batch_id)

    @app.get("/api/batches/{batch_id}/faces", response_model=FaceView)
    def get_faces(batch_id: UUID, owner: Owner):
        store.get(owner, batch_id)
        return sessions.get(owner, batch_id)

    @app.patch("/api/batches/{batch_id}/photos/{photo_id}", response_model=Photo)
    def edit_photo(batch_id: UUID, photo_id: UUID, body: Edit, owner: Owner):
        return service.edit(owner, batch_id, photo_id, body)

    @app.post("/api/batches/{batch_id}/approve")
    def approve(batch_id: UUID, body: Selected, owner: Owner) -> dict:
        service.approve(owner, batch_id, body.photos)
        return {"approved": len(body.photos)}

    @app.post("/api/batches/{batch_id}/photos/{photo_id}/unapprove", response_model=Photo)
    def unapprove(batch_id: UUID, photo_id: UUID, body: Revision, owner: Owner):
        return service.unapprove(owner, batch_id, photo_id, body.revision)

    @app.post("/api/batches/{batch_id}/finish")
    def finish(batch_id: UUID, owner: Owner) -> dict:
        service.finish(owner, batch_id)
        return {"saved": True, "face_session_finished": True}

    @app.get("/api/batches/{batch_id}/apply-preview", response_model=list[ChangePreview])
    def preview(batch_id: UUID, owner: Owner):
        return service.preview(owner, batch_id)

    @app.post("/api/batches/{batch_id}/apply", response_model=list[Publication])
    def apply(batch_id: UUID, body: Selected, owner: Owner):
        return service.apply(owner, batch_id, body.photos)

    @app.post("/api/batches/{batch_id}/publications/{operation_id}/restore", response_model=WriteResult)
    def restore(batch_id: UUID, operation_id: UUID, owner: Owner):
        return service.restore(owner, batch_id, operation_id)

    @app.get("/api/photos/{photo_id}")
    def photo_bytes(photo_id: UUID, owner: Owner):
        photo = store.photo(owner, photo_id)
        try:
            data = run(blobs.read(owner, photo.blob_key))
        except BlobNotFound:
            raise Missing("Stored photo bytes are unavailable") from None
        return Response(data, media_type=photo.mime_type)

    @app.get("/api/disciplines", response_model=list[DisciplineOption])
    def disciplines(owner: Owner) -> list[dict]:
        return [{"value": d.value, "de": d.de, "en": d.en} for d in AthleticsDiscipline]

    frontend = Path(__file__).resolve().parents[2] / "startnummer-web" / "dist"
    if frontend.exists():
        app.mount("/_astro", StaticFiles(directory=frontend / "_astro"), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(frontend / "index.html")

    return app


def main():
    import uvicorn

    uvicorn.run("startnummer.app.api:create_app", factory=True, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
