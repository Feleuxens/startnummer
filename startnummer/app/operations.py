"""Health checks and administrator settings, without inference imports."""

import os
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from startnummer.adapters.db.schema import Base, JobRow
from startnummer.app.contracts import Administration, RuntimeSettings, WorkerHealth

RUNTIME_FIELDS = {"max_file_bytes", "max_batch_bytes", "session_ttl", "max_concurrent_jobs"}


def effective_settings(store, settings):
    _, document = store.installation_settings(settings.owner_id)
    return replace(settings, **{key: value for key, value in document.items() if key in RUNTIME_FIELDS})


def runtime_settings(store, settings, *, owner_id=None, session=None):
    revision, document = store.installation_settings(owner_id or settings.owner_id, session=session)
    return RuntimeSettings(
        revision=revision,
        **{
            "max_file_bytes": settings.max_file_bytes,
            "max_batch_bytes": settings.max_batch_bytes,
            "session_ttl": settings.session_ttl,
            "max_concurrent_jobs": settings.max_concurrent_jobs,
            **{key: value for key, value in document.items() if key in RUNTIME_FIELDS},
        },
    )


def worker_health(url, secret):
    try:
        response = httpx.get(
            url.rstrip("/") + "/health",
            headers={"Authorization": "Bearer " + secret},
            timeout=2,
            trust_env=False,
        )
        response.raise_for_status()
        return WorkerHealth.model_validate({**response.json(), "reachable": True})
    except (httpx.HTTPError, ValueError):
        return WorkerHealth(reachable=False, state="unavailable")


def storage_healthy(root: Path):
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as probe:
            probe.write(b"startnummer-storage-probe")
            probe.flush()
            os.fsync(probe.fileno())
        return True
    except OSError:
        return False


def database_healthy(store):
    try:
        with store.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            for table in Base.metadata.sorted_tables:
                connection.execute(select(table).limit(0))
        return True
    except Exception:
        return False


def administration(store, settings):
    database = database_healthy(store)
    jobs = {}
    options = RuntimeSettings(
        max_file_bytes=settings.max_file_bytes,
        max_batch_bytes=settings.max_batch_bytes,
        session_ttl=settings.session_ttl,
        max_concurrent_jobs=settings.max_concurrent_jobs,
    )
    if database:
        try:
            with store.transaction() as session:
                jobs = dict(session.execute(select(JobRow.state, func.count()).group_by(JobRow.state)).all())
                options = runtime_settings(store, settings, session=session)
        except SQLAlchemyError:
            database = False
    return Administration(
        database=database,
        storage=storage_healthy(settings.blob_root),
        worker=worker_health(settings.worker_url, settings.worker_secret),
        jobs=jobs,
        settings=options,
    )
