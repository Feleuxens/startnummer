"""Environment configuration. Gallery settings are not loaded by workers."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5


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
    cookie_secure: bool = False
    max_file_bytes: int = 50 * 1024 * 1024
    max_batch_bytes: int = 2 * 1024 * 1024 * 1024
    session_ttl: int = 3600

    @classmethod
    def from_env(cls):
        username = os.environ.get("STARTNUMMER_USERNAME", "photographer")
        secret = os.environ["STARTNUMMER_SESSION_SECRET"]
        worker_secret = os.environ["STARTNUMMER_WORKER_SECRET"]
        if len(secret) < 32 or len(worker_secret) < 32:
            raise ValueError("Session and worker secrets must each contain at least 32 characters")
        return cls(
            database_url=os.environ["STARTNUMMER_DATABASE_URL"],
            blob_root=Path(os.environ["STARTNUMMER_BLOB_ROOT"]),
            password=os.environ["STARTNUMMER_PASSWORD"],
            session_secret=secret,
            worker_secret=worker_secret,
            owner_id=uuid5(NAMESPACE_URL, "startnummer:" + username),
            username=username,
            worker_url=os.environ.get("STARTNUMMER_WORKER_URL", "http://127.0.0.1:8766"),
            roster_hosts=tuple(os.environ.get("STARTNUMMER_ROSTER_HOSTS", "ergebnisse.leichtathletik.de").split(",")),
            chevereto_url=os.environ.get("STARTNUMMER_CHEVERETO_URL"),
            chevereto_dsn=os.environ.get("STARTNUMMER_CHEVERETO_DSN"),
            cookie_secure=os.environ.get("STARTNUMMER_COOKIE_SECURE", "0") == "1",
            session_ttl=int(os.environ.get("STARTNUMMER_FACE_SESSION_TTL", "3600")),
            max_file_bytes=int(os.environ.get("STARTNUMMER_MAX_FILE_BYTES", str(50 * 1024 * 1024))),
            max_batch_bytes=int(os.environ.get("STARTNUMMER_MAX_BATCH_BYTES", str(2 * 1024 * 1024 * 1024))),
        )
