"""Temporary face geometry and match groups, stored only in worker memory."""

import secrets
import threading
import time
from copy import deepcopy
from uuid import UUID

import httpx

from startnummer.core.batch import Conflict

FACE_SESSION_PROTOCOL = 1


def propagation_problem(data: dict) -> str | None:
    if not data.get("available"):
        return "Face session unavailable; saved names and captions remain editable."
    if data.get("protocol_version") != FACE_SESSION_PROTOCOL:
        return (
            "This worker session does not support name propagation. "
            "Restart the updated worker and analyze a fresh batch. "
            "Keep this batch to preserve your review edits."
        )
    faces = [face for values in data.get("photos", {}).values() for face in values]
    if not faces or any(not face.get("group") for face in faces):
        return "Face match groups are missing from this session. Analyze a fresh batch with the updated worker."
    return None


class FaceSessions:
    def __init__(self, ttl: int = 3600):
        self.ttl = ttl
        self._items: dict[tuple[str, str], tuple[float, str, dict, str | None, float]] = {}
        self._lock = threading.RLock()
        self._undo: dict[tuple[str, str], tuple[str, str, list[dict]]] = {}

    def put(
        self, owner_id: UUID, batch_id: UUID, faces: dict, *, run_id: str | None = None, ttl: int | None = None
    ) -> None:
        with self._lock:
            self._prune()
            key = (str(owner_id), str(batch_id))
            faces = deepcopy(faces)
            self._discard(key)
            if not faces:
                return
            lifetime = self.ttl if ttl is None else ttl
            self._items[key] = (
                time.monotonic() + lifetime,
                secrets.token_urlsafe(24),
                faces,
                run_id,
                time.time() + lifetime,
            )

    def _discard(self, key):
        item = self._items.pop(key, None)
        if item:
            item[2].clear()
        undo = self._undo.pop(key, None)
        if undo:
            undo[2].clear()

    def clear(self):
        with self._lock:
            for key in list(self._items):
                self._discard(key)
            self._undo.clear()

    def _prune(self):
        for key, value in list(self._items.items()):
            # A laptop's monotonic clock may pause during suspend. Neither clock
            # is allowed to extend a face session beyond its original lifetime.
            if value[0] <= time.monotonic() or value[4] <= time.time():
                self._discard(key)

    def expire(self):
        with self._lock:
            self._prune()

    def count(self):
        with self._lock:
            self._prune()
            return len(self._items)

    def get(self, owner_id: UUID, batch_id: UUID) -> dict:
        with self._lock:
            self._prune()
            item = self._items.get((str(owner_id), str(batch_id)))
            undo = self._undo.get((str(owner_id), str(batch_id)))
            return {
                "protocol_version": FACE_SESSION_PROTOCOL,
                "available": bool(item),
                "session_id": item[1] if item else None,
                "photos": deepcopy(item[2]) if item else {},
                "expires_at": min(item[4], time.time() + max(0, item[0] - time.monotonic())) if item else None,
                "undo_id": undo[1] if undo else None,
                "undo_count": len(undo[2]) if undo else 0,
            }

    def finish(self, owner_id: UUID, batch_id: UUID, *, run_id: str | None = None) -> None:
        with self._lock:
            key = (str(owner_id), str(batch_id))
            item = self._items.get(key)
            if item and (run_id is None or item[3] == run_id):
                self._discard(key)

    def remember(self, owner_id, batch_id, session_id, changes):
        with self._lock:
            self._prune()
            key = (str(owner_id), str(batch_id))
            item = self._items.get(key)
            if item is None or item[1] != session_id:
                raise Conflict("Face session expired; undo is unavailable")
            previous = self._undo.pop(key, None)
            if previous:
                previous[2].clear()
            undo_id = secrets.token_urlsafe(24)
            self._undo[key] = (session_id, undo_id, deepcopy(changes))
            return undo_id

    def undo(self, owner_id, batch_id, session_id, undo_id, *, consume=False):
        with self._lock:
            self._prune()
            key = (str(owner_id), str(batch_id))
            item = self._undo.get(key)
            if item is None or item[:2] != (session_id, undo_id):
                raise Conflict("Undo expired or a newer name assignment replaced it")
            changes = deepcopy(item[2])
            if consume:
                del self._undo[key]
                item[2].clear()
            return changes

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

    def _call(self, method: str, owner_id: UUID, batch_id: UUID, payload=None):
        try:
            response = httpx.request(
                method,
                f"{self.url}/sessions/{owner_id}/{batch_id}",
                headers={"Authorization": "Bearer " + self.secret},
                timeout=5,
                trust_env=False,
                json=payload,
            )
            if response.status_code == 409:
                raise Conflict(response.json()["detail"])
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            if method == "GET":
                return {"available": False, "session_id": None, "photos": {}}
            raise Conflict(
                "Worker unavailable; face-session operation could not be confirmed. Saved captions remain available."
            ) from exc

    def get(self, owner_id, batch_id):
        return self._call("GET", owner_id, batch_id)

    def finish(self, owner_id, batch_id):
        self._call("DELETE", owner_id, batch_id)

    def remember(self, owner_id, batch_id, session_id, changes):
        return self._call(
            "POST",
            owner_id,
            batch_id,
            {
                "action": "remember",
                "session_id": session_id,
                "changes": changes,
            },
        )["undo_id"]

    def undo(self, owner_id, batch_id, session_id, undo_id, *, consume=False):
        return self._call(
            "POST",
            owner_id,
            batch_id,
            {
                "action": "undo",
                "session_id": session_id,
                "undo_id": undo_id,
                "consume": consume,
            },
        )["changes"]

    def validate(self, owner_id, batch_id, photo_id, subject, session_id):
        data = self.get(owner_id, batch_id)
        if (
            not session_id
            or data["session_id"] != session_id
            or not any(face["subject"] == subject for face in data["photos"].get(str(photo_id), []))
        ):
            raise Conflict("Face session expired or selected face is unavailable")
