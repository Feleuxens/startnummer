"""Temporary face geometry for review; stored only in worker memory."""

import secrets
import threading
import time
from uuid import UUID

import httpx

from startnummer.core.batch import Conflict


class FaceSessions:
    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._items: dict[tuple[str, str], tuple[float, str, dict]] = {}
        self._lock = threading.RLock()

    def put(self, owner_id: UUID, batch_id: UUID, faces: dict) -> None:
        with self._lock:
            self._prune()
            self._items[(str(owner_id), str(batch_id))] = (
                time.monotonic() + self.ttl,
                secrets.token_urlsafe(24),
                faces,
            )

    def _prune(self):
        for key, value in list(self._items.items()):
            if value[0] <= time.monotonic():
                del self._items[key]

    def expire(self):
        with self._lock:
            self._prune()

    def get(self, owner_id: UUID, batch_id: UUID) -> dict:
        with self._lock:
            self._prune()
            item = self._items.get((str(owner_id), str(batch_id)))
            return {
                "available": bool(item),
                "session_id": item[1] if item else None,
                "photos": item[2] if item else {},
                "expires_at": time.time() + max(0, item[0] - time.monotonic()) if item else None,
            }

    def finish(self, owner_id: UUID, batch_id: UUID) -> None:
        with self._lock:
            self._items.pop((str(owner_id), str(batch_id)), None)

    def validate(self, owner_id: UUID, batch_id: UUID, photo_id: UUID, subject: int, session_id: str) -> None:
        data = self.get(owner_id, batch_id)
        if data["session_id"] != session_id or not any(
            face["subject"] == subject for face in data["photos"].get(str(photo_id), [])
        ):
            raise Conflict("Face session expired or selected face is unavailable")


class HttpFaceSessions:
    """HTTP client for the worker's in-memory face sessions."""

    def __init__(self, url: str, secret: str):
        self.url, self.secret = url.rstrip("/"), secret

    def _call(self, method: str, owner_id: UUID, batch_id: UUID):
        try:
            response = httpx.request(
                method,
                f"{self.url}/sessions/{owner_id}/{batch_id}",
                headers={"Authorization": "Bearer " + self.secret},
                timeout=5,
                trust_env=False,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            if method == "GET":
                return {"available": False, "session_id": None, "photos": {}}
            raise Conflict(
                "Worker unavailable; review was saved but face-session finish could not be confirmed"
            ) from exc

    def get(self, owner_id, batch_id):
        return self._call("GET", owner_id, batch_id)

    def finish(self, owner_id, batch_id):
        self._call("DELETE", owner_id, batch_id)

    def validate(self, owner_id, batch_id, photo_id, subject, session_id):
        data = self.get(owner_id, batch_id)
        if (
            not session_id
            or data["session_id"] != session_id
            or not any(face["subject"] == subject for face in data["photos"].get(str(photo_id), []))
        ):
            raise Conflict("Face session expired or selected face is unavailable")
