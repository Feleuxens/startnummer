"""Environment configuration. Gallery settings are not loaded by workers."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from startnummer.core.batch import WorkflowError


def required_setting(name):
    value = os.environ.get(name)
    if not value:
        raise WorkflowError(f"{name} is required")
    return value


def integer_setting(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        raise WorkflowError(f"{name} must be an integer") from None


@dataclass(frozen=True)
class Settings:
    database_url: str
    blob_root: Path
    password: str
    session_secret: str
    worker_secret: str
    owner_id: UUID
    username: str = "photographer"
    worker_url: str = "http://127.0.0.1:8766"
    roster_hosts: tuple[str, ...] = ("ergebnisse.leichtathletik.de",)
    chevereto_url: str | None = None
    chevereto_dsn: str | None = None
    integration_key: str | None = None
    cookie_secure: bool = False
    max_file_bytes: int = 50 * 1024 * 1024
    max_batch_bytes: int = 2 * 1024 * 1024 * 1024
    session_ttl: int = 3600

    @classmethod
    def from_env(cls):
        username = os.environ.get("STARTNUMMER_USERNAME", "photographer")
        secret = required_setting("STARTNUMMER_SESSION_SECRET")
        worker_secret = required_setting("STARTNUMMER_WORKER_SECRET")
        for name, value in (("STARTNUMMER_SESSION_SECRET", secret), ("STARTNUMMER_WORKER_SECRET", worker_secret)):
            if len(value) < 32:
                raise WorkflowError(f"{name} must contain at least 32 characters")
        return cls(
            database_url=required_setting("STARTNUMMER_DATABASE_URL"),
            blob_root=Path(required_setting("STARTNUMMER_BLOB_ROOT")),
            # Retained only to import an existing configured account once.
            password=os.environ.get("STARTNUMMER_PASSWORD", ""),
            session_secret=secret,
            worker_secret=worker_secret,
            owner_id=uuid5(NAMESPACE_URL, "startnummer:" + username),
            username=username,
            worker_url=os.environ.get("STARTNUMMER_WORKER_URL", "http://127.0.0.1:8766"),
            roster_hosts=tuple(os.environ.get("STARTNUMMER_ROSTER_HOSTS", "ergebnisse.leichtathletik.de").split(",")),
            chevereto_url=os.environ.get("STARTNUMMER_CHEVERETO_URL"),
            chevereto_dsn=os.environ.get("STARTNUMMER_CHEVERETO_DSN"),
            integration_key=os.environ.get("STARTNUMMER_INTEGRATION_KEY"),
            cookie_secure=os.environ.get("STARTNUMMER_COOKIE_SECURE", "0") == "1",
            session_ttl=integer_setting("STARTNUMMER_FACE_SESSION_TTL", 3600),
            max_file_bytes=integer_setting("STARTNUMMER_MAX_FILE_BYTES", 50 * 1024 * 1024),
            max_batch_bytes=integer_setting("STARTNUMMER_MAX_BATCH_BYTES", 2 * 1024 * 1024 * 1024),
        )
