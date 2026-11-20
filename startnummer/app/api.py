from dataclasses import replace
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import create_engine

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.db.accounts import Account
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import HttpFaceSessions, propagation_problem
from startnummer.app.account_routes import account_routes
from startnummer.app.auth import Authentication
from startnummer.app.captions import caption_preferences
from startnummer.app.contracts import (
    AddPerson,
    Administration,
    AlbumSettings,
    BatchSummary,
    BatchView,
    CaptionNames,
    ChangePreview,
    CheveretoConnection,
    ConnectionTest,
    DisciplineAssignment,
    DisciplineOption,
    DisciplinePreview,
    Edit,
    FaceView,
    ImportProblem,
    IntegrationRevision,
    IntegrationStatus,
    PropagationApply,
    PropagationPreview,
    PropagationRequest,
    PropagationUndo,
    Revision,
    RosterNameEdit,
    RosterPreview,
    RuntimeSettings,
    Selected,
)
from startnummer.app.integrations import Integrations
from startnummer.app.operations import (
    administration,
    database_healthy,
    effective_settings,
    runtime_settings,
    storage_healthy,
)
from startnummer.app.services import ImportRejected, InputPhoto, Services, import_size_limit, run
from startnummer.app.settings import Settings
from startnummer.app.uploads import ROSTER_FILE_LIMIT, ROSTER_PREVIEW_PATH, upload_router
from startnummer.core.batch import Batch, Conflict, Job, Missing, Photo, Publication, WorkflowError, WriteResult
from startnummer.core.enums import NameOrder
from startnummer.core.errors import BlobNotFound
from startnummer.core.record import Album
from startnummer.core.sports.athletics import AthleticsDiscipline


def create_app(
    settings: Settings | None = None,
    *,
    store=None,
    blobs=None,
    sessions=None,
    gallery=None,
    fetch=None,
    integration_factory=None,
):
    settings = settings or Settings.from_env()
    store = store or Store(create_engine(settings.database_url, pool_pre_ping=True))
    blobs = blobs or FilesystemBlobStore(settings.blob_root)
    sessions = sessions or HttpFaceSessions(settings.worker_url, settings.worker_secret)
    integrations = Integrations(store, settings, **({"factory": integration_factory} if integration_factory else {}))
    service = Services(store, blobs, settings, sessions, gallery if gallery is not None else integrations, fetch)
    app = FastAPI(title="Startnummer", version="0.1.0", openapi_url="/api/openapi.json", docs_url="/api/docs")
    app.state.services = service
    authentication = Authentication(store.engine, settings)
    app.state.authentication = authentication

    def integrations_for(user):
        return Integrations(
            store,
            replace(settings, owner_id=user.id, username=user.username),
            **({"factory": integration_factory} if integration_factory else {}),
        )

    def service_for(user):
        scoped = replace(settings, owner_id=user.id, username=user.username)
        if not user.is_admin:
            scoped = replace(scoped, chevereto_url=None, chevereto_dsn=None)
        destination = (gallery if gallery is not None else integrations_for(user)) if user.is_admin else None
        return Services(store, blobs, scoped, sessions, destination, fetch)

    principal, administrator = account_routes(app, authentication, settings, service_for)
    uploads = upload_router(principal, lambda: effective_settings(store, settings).max_batch_bytes)
    User = Annotated[Account, Depends(principal)]
    Admin = Annotated[Account, Depends(administrator)]

    def owner_identity(user: User):
        return user.id

    def request_service(user: User):
        return service_for(user)

    Owner = Annotated[UUID, Depends(owner_identity)]
    Service = Annotated[Services, Depends(request_service)]

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Validation errors must not echo submitted passwords or connection strings.
        return JSONResponse(
            {"detail": [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]}, status_code=422
        )

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
        if isinstance(exc, ImportRejected):
            return JSONResponse(exc.problem.model_dump(mode="json"), status_code=status)
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @app.get("/api/health/live", include_in_schema=False)
    def live():
        return {"alive": True}

    @app.get("/api/health/ready", include_in_schema=False)
    def ready(response: Response):
        database = database_healthy(store)
        storage = storage_healthy(settings.blob_root)
        healthy = database and storage
        response.status_code = 200 if healthy else 503
        return {"ready": healthy, "database": database, "storage": storage}

    @app.get("/api/admin", response_model=Administration)
    def get_administration(user: Admin):
        return administration(store, replace(settings, owner_id=user.id))

    @app.get("/api/account/caption-names", response_model=CaptionNames)
    def get_caption_names(owner: Owner):
        return caption_preferences(store, owner)

    @app.put("/api/account/caption-names", response_model=CaptionNames)
    def save_caption_names(body: CaptionNames, owner: Owner):
        revision = store.save_settings(
            owner,
            body.revision,
            {"caption_name_overrides": [rule.model_dump() for rule in body.overrides]},
        )
        return body.model_copy(update={"revision": revision})

    @app.put("/api/admin/settings", response_model=RuntimeSettings)
    def update_settings(body: RuntimeSettings, user: Admin):
        store.save_settings(user.id, body.revision, body.model_dump(exclude={"revision"}, exclude_unset=True))
        return runtime_settings(store, settings, owner_id=user.id)

    @app.get("/api/admin/integrations/chevereto", response_model=IntegrationStatus)
    def integration_status(user: Admin):
        return integrations_for(user).status()

    @app.post("/api/admin/integrations/chevereto/test", response_model=ConnectionTest)
    def test_integration(user: Admin, body: CheveretoConnection | None = None):
        return integrations_for(user).test(body)

    @app.put("/api/admin/integrations/chevereto", response_model=IntegrationStatus)
    def save_integration(body: CheveretoConnection, user: Admin):
        return integrations_for(user).save(body)

    @app.post("/api/admin/integrations/chevereto/confirm-legacy", response_model=IntegrationStatus)
    def confirm_legacy(body: IntegrationRevision, user: Admin):
        return integrations_for(user).confirm_legacy(body.revision)

    async def validate_import_fields(request: Request):
        form = await request.form()
        allowed = {
            "import_id",
            "name",
            "meet_name",
            "gallery_url",
            "roster_url",
            "roster_file",
            "photos",
            "photo_modified",
            "name_order",
            "roster_digest",
            "roster_names",
        }
        if set(form) - allowed:
            raise WorkflowError("Unknown import field; ownership comes from authentication")

    @app.get("/api/batches", response_model=list[BatchSummary])
    def list_batches(owner: Owner, service: Service) -> list[dict]:
        store.cleanup(owner, lambda key: run(blobs.delete(owner, key)))
        return store.list_batches(owner)

    def roster_bytes(upload):
        data = upload.file.read(ROSTER_FILE_LIMIT + 1) if upload else None
        if data is not None and len(data) > ROSTER_FILE_LIMIT:
            raise ImportRejected(
                "roster",
                f"The roster HTML exceeds the {import_size_limit(ROSTER_FILE_LIMIT)} limit. "
                "Choose a smaller roster or No roster.",
            )
        return data

    @uploads.post(ROSTER_PREVIEW_PATH, response_model=RosterPreview, responses={400: {"model": ImportProblem}})
    def preview_roster(
        owner: Owner,
        service: Service,
        roster_url: Annotated[str | None, Form()] = None,
        roster_file: Annotated[UploadFile | None, File()] = None,
        name_order: Annotated[NameOrder, Form()] = NameOrder.AUTO,
    ):
        return service.preview_roster(roster_bytes(roster_file), roster_url, name_order)

    @uploads.post(
        "/api/batches",
        response_model=Batch,
        dependencies=[Depends(validate_import_fields)],
        responses={400: {"model": ImportProblem}, 409: {"model": ImportProblem}},
    )
    def import_batch(
        owner: Owner,
        service: Service,
        import_id: Annotated[UUID | None, Form()] = None,
        name: Annotated[str, Form()] = "",
        meet_name: Annotated[str, Form()] = "",
        gallery_url: Annotated[str | None, Form()] = None,
        roster_url: Annotated[str | None, Form()] = None,
        roster_file: Annotated[UploadFile | None, File()] = None,
        photos: Annotated[list[UploadFile] | None, File()] = None,
        photo_modified: Annotated[str | None, Form()] = None,
        name_order: Annotated[NameOrder, Form()] = NameOrder.AUTO,
        roster_digest: Annotated[str | None, Form()] = None,
        roster_names: Annotated[str | None, Form()] = None,
    ):
        limits = effective_settings(store, service.settings)
        inputs = []
        total = 0
        for photo in photos or []:
            filename = photo.filename or "photo"
            data = photo.file.read(limits.max_file_bytes + 1)
            if len(data) > limits.max_file_bytes:
                inputs.append(InputPhoto(filename, b"", exceeded_limit=limits.max_file_bytes))
                continue
            total += len(data)
            if total > limits.max_batch_bytes:
                raise ImportRejected(
                    "photos",
                    f"The selected photos exceed the {import_size_limit(limits.max_batch_bytes)} batch limit. "
                    "Select fewer photos and try again.",
                )
            inputs.append(InputPhoto(filename, data))
        if photo_modified is not None:
            try:
                dates = TypeAdapter(list[AwareDatetime | None]).validate_json(photo_modified)
            except ValidationError as exc:
                raise WorkflowError("Photo modification dates must be valid timestamps") from exc
            if gallery_url or len(dates) != len(inputs):
                raise WorkflowError("Photo modification dates must match uploaded files")
            for photo, date in zip(inputs, dates, strict=True):
                photo.date_modified = date
        html = roster_bytes(roster_file)
        try:
            corrections = TypeAdapter(list[RosterNameEdit]).validate_json(roster_names) if roster_names else []
        except ValidationError as exc:
            raise ImportRejected("roster", "Check the names in the roster preview and try again.") from exc
        if gallery_url and service.gallery is None:
            raise HTTPException(403, "Gallery access requires an administrator")
        return service.import_batch(
            owner,
            name,
            meet_name,
            inputs,
            gallery_url,
            html,
            roster_url,
            import_id,
            name_order=name_order,
            roster_digest=roster_digest,
            roster_names=corrections,
        )

    app.include_router(uploads)

    @app.get("/api/batches/{batch_id}", response_model=BatchView)
    def get_batch(batch_id: UUID, owner: Owner, service: Service):
        with store.transaction(owner) as db:
            # A completed job must be read before the photos committed with its result.
            jobs = store.jobs(owner, batch_id, session=db)
            batch = store.load(db, owner, batch_id)
            publications = store.publications(db, owner, batch_id)
            return BatchView(batch=batch, publications=publications, jobs=jobs)

    @app.post("/api/batches/{batch_id}/photo-dates", response_model=Batch)
    def read_photo_dates(batch_id: UUID, owner: Owner, service: Service):
        return service.read_photo_dates(owner, batch_id)

    @app.put("/api/batches/{batch_id}/settings", response_model=Album)
    def edit_album_settings(batch_id: UUID, body: AlbumSettings, owner: Owner, service: Service):
        return service.edit_album_settings(owner, batch_id, body)

    @app.post("/api/batches/{batch_id}/photos/{photo_id}/caption-suggestion", response_model=Photo)
    def refresh_caption_suggestion(batch_id: UUID, photo_id: UUID, body: Revision, owner: Owner, service: Service):
        return service.refresh_caption_suggestion(owner, batch_id, photo_id, body.revision)

    @app.delete("/api/batches/{batch_id}")
    def delete_batch(batch_id: UUID, owner: Owner, service: Service) -> dict:
        service.delete_batch(owner, batch_id)
        return {"deleted": True}

    @app.post("/api/batches/{batch_id}/analysis", response_model=Job)
    def analyze(batch_id: UUID, owner: Owner, service: Service):
        return service.analyze(owner, batch_id)

    @app.post("/api/batches/{batch_id}/analysis/cancel")
    def cancel_analysis(batch_id: UUID, owner: Owner, service: Service) -> dict:
        service.cancel_analysis(owner, batch_id)
        return {"cancelled": True}

    @app.get("/api/batches/{batch_id}/faces", response_model=FaceView)
    def get_faces(batch_id: UUID, owner: Owner, service: Service):
        with store.transaction(owner) as db:
            store.load(db, owner, batch_id, lock=True)
            try:
                store.require_idle(db, owner, batch_id)
            except Conflict:
                return {"available": False, "session_id": None, "photos": {}}
            data = sessions.get(owner, batch_id)
            problem = propagation_problem(data)
            return {**data, "propagation_available": problem is None, "propagation_unavailable_reason": problem}

    @app.post("/api/batches/{batch_id}/face-propagation/preview", response_model=PropagationPreview)
    def preview_propagation(batch_id: UUID, body: PropagationRequest, owner: Owner, service: Service):
        return service.preview_propagation(owner, batch_id, body)

    @app.post("/api/batches/{batch_id}/face-propagation", response_model=list[Photo])
    def propagate(batch_id: UUID, body: PropagationApply, owner: Owner, service: Service):
        return service.propagate(owner, batch_id, body)

    @app.post("/api/batches/{batch_id}/face-propagation/undo", response_model=list[Photo])
    def undo_propagation(batch_id: UUID, body: PropagationUndo, owner: Owner, service: Service):
        return service.undo_propagation(owner, batch_id, body)

    @app.patch("/api/batches/{batch_id}/photos/{photo_id}", response_model=Photo)
    def edit_photo(batch_id: UUID, photo_id: UUID, body: Edit, owner: Owner, service: Service):
        return service.edit(owner, batch_id, photo_id, body)

    @app.post("/api/batches/{batch_id}/photos/{photo_id}/subjects", response_model=Photo)
    def add_person(batch_id: UUID, photo_id: UUID, body: AddPerson, owner: Owner, service: Service):
        return service.add_person(owner, batch_id, photo_id, body)

    @app.delete("/api/batches/{batch_id}/photos/{photo_id}/subjects/{subject_index}", response_model=Photo)
    def remove_person(
        batch_id: UUID, photo_id: UUID, subject_index: int, body: Revision, owner: Owner, service: Service
    ):
        return service.remove_person(owner, batch_id, photo_id, subject_index, body.revision)

    @app.post("/api/batches/{batch_id}/discipline-preview", response_model=DisciplinePreview)
    def preview_discipline(batch_id: UUID, body: DisciplineAssignment, owner: Owner, service: Service):
        return service.preview_discipline(owner, batch_id, body)

    @app.post("/api/batches/{batch_id}/discipline", response_model=list[Photo])
    def assign_discipline(batch_id: UUID, body: DisciplineAssignment, owner: Owner, service: Service):
        return service.assign_discipline(owner, batch_id, body)

    @app.post("/api/batches/{batch_id}/approve")
    def approve(batch_id: UUID, body: Selected, owner: Owner, service: Service) -> dict:
        service.approve(owner, batch_id, body.photos)
        return {"approved": len(body.photos)}

    @app.post("/api/batches/{batch_id}/photos/{photo_id}/approve", response_model=Photo)
    def approve_photo(batch_id: UUID, photo_id: UUID, body: Revision, owner: Owner, service: Service):
        return service.approve_photo(owner, batch_id, photo_id, body.revision)

    @app.post("/api/batches/{batch_id}/photos/{photo_id}/unapprove", response_model=Photo)
    def unapprove(batch_id: UUID, photo_id: UUID, body: Revision, owner: Owner, service: Service):
        return service.unapprove(owner, batch_id, photo_id, body.revision)

    @app.post("/api/batches/{batch_id}/finish")
    def finish(batch_id: UUID, owner: Owner, service: Service) -> dict:
        service.finish(owner, batch_id)
        return {"saved": True, "face_session_finished": True}

    @app.get(
        "/api/batches/{batch_id}/apply-preview",
        dependencies=[Depends(administrator)],
        response_model=list[ChangePreview],
    )
    def preview(batch_id: UUID, owner: Owner, service: Service):
        return service.preview(owner, batch_id)

    @app.post("/api/batches/{batch_id}/apply", dependencies=[Depends(administrator)], response_model=list[Publication])
    def apply(batch_id: UUID, body: Selected, owner: Owner, service: Service):
        return service.apply(owner, batch_id, body.photos)

    @app.post(
        "/api/batches/{batch_id}/publications/{operation_id}/restore",
        dependencies=[Depends(administrator)],
        response_model=WriteResult,
    )
    def restore(batch_id: UUID, operation_id: UUID, owner: Owner, service: Service):
        return service.restore(owner, batch_id, operation_id)

    @app.post(
        "/api/batches/{batch_id}/publications/{operation_id}/reconcile",
        dependencies=[Depends(administrator)],
        response_model=Publication,
    )
    def reconcile(batch_id: UUID, operation_id: UUID, owner: Owner, service: Service):
        return service.reconcile(owner, batch_id, operation_id)

    @app.post(
        "/api/batches/{batch_id}/photos/{photo_id}/refresh-description",
        dependencies=[Depends(administrator)],
        response_model=Photo,
    )
    def refresh_description(batch_id: UUID, photo_id: UUID, body: Revision, owner: Owner, service: Service):
        return service.refresh_description(owner, batch_id, photo_id, body.revision)

    @app.get("/api/photos/{photo_id}")
    def photo_bytes(photo_id: UUID, owner: Owner, service: Service):
        photo = store.photo(owner, photo_id)
        try:
            data = run(blobs.read(owner, photo.blob_key))
        except BlobNotFound:
            raise Missing("Stored photo bytes are unavailable") from None
        return Response(data, media_type=photo.mime_type)

    @app.get("/api/disciplines", response_model=list[DisciplineOption])
    def disciplines(owner: Owner, service: Service) -> list[dict]:
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
