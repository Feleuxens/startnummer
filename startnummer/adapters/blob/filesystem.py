"""Content-addressed file storage, scoped to each owner.

Layout: <root>/<owner_id>/<algorithm>/<digest[:2]>/<digest[2:4]>/<digest><suffix>
"""

import asyncio
import os
import re
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from startnummer.core.errors import BlobNotFound
from startnummer.core.ports import BlobRef

ENV_ROOT = "STARTNUMMER_BLOB_ROOT"

# Accept algorithm-prefixed hashes with lowercase hexadecimal digests.
_HASH_RE = re.compile(r"^(?P<algorithm>[a-z0-9]{1,16}):(?P<digest>[0-9a-f]{32,128})$")

# Leading dot, lower case, no separators.
_SUFFIX_RE = re.compile(r"^\.[a-z0-9]{1,8}$")

# Validate persisted keys before resolving them as file paths.
_KEY_RE = re.compile(r"^[a-z0-9]{1,16}/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32,128}(\.[a-z0-9]{1,8})?$")

_CHUNK_BYTES = 1024 * 1024


class FilesystemBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @classmethod
    def from_env(cls) -> "FilesystemBlobStore":
        root = os.environ.get(ENV_ROOT)
        if not root:
            raise RuntimeError(f"{ENV_ROOT} is not set")
        return cls(Path(root))

    def _key(self, content_hash: str, suffix: str) -> str:
        match = _HASH_RE.fullmatch(content_hash)
        if match is None:
            raise ValueError(f"not a content hash: {content_hash!r}")
        if suffix and not _SUFFIX_RE.fullmatch(suffix):
            raise ValueError(f"not a file suffix: {suffix!r}")
        algorithm = match["algorithm"]
        digest = match["digest"]
        return f"{algorithm}/{digest[:2]}/{digest[2:4]}/{digest}{suffix}"

    def _path(self, owner_id: UUID, key: str) -> Path:
        owner_id = UUID(str(owner_id))
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"not a blob key: {key!r}")
        path = (self._root / str(owner_id) / key).resolve()
        # Reject symlinks that resolve outside the owner's directory.
        if not path.is_relative_to(self._root / str(owner_id)):
            raise ValueError(f"key escapes blob root: {key!r}")
        return path

    async def put(
        self,
        owner_id: UUID,
        content_hash: str,
        data: AsyncIterator[bytes],
        *,
        suffix: str = "",
    ) -> BlobRef:
        """A blob already at this key is left alone and `data` is not consumed."""
        key = self._key(content_hash, suffix)
        path = self._path(owner_id, key)

        existing = await asyncio.to_thread(_size_if_present, path)
        if existing is not None:
            return BlobRef(key=key, size=existing)

        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        # Keep the temporary file on the same filesystem for atomic replacement.
        fd, tmp_name = await asyncio.to_thread(tempfile.mkstemp, dir=path.parent, suffix=".part")
        tmp = Path(tmp_name)
        size = 0
        try:
            handle = os.fdopen(fd, "wb")
            try:
                async for chunk in data:
                    size += await asyncio.to_thread(handle.write, chunk)
                await asyncio.to_thread(handle.flush)
                await asyncio.to_thread(os.fsync, handle.fileno())
            finally:
                await asyncio.to_thread(handle.close)
            # A crash before replacement leaves only an incomplete .part file.
            await asyncio.to_thread(os.replace, tmp, path)
        except BaseException:
            await asyncio.to_thread(tmp.unlink, True)
            raise
        return BlobRef(key=key, size=size)

    async def read(self, owner_id: UUID, key: str) -> bytes:
        path = self._path(owner_id, key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise BlobNotFound(owner_id, key) from exc

    async def exists(self, owner_id: UUID, key: str) -> bool:
        return await asyncio.to_thread(self._path(owner_id, key).is_file)

    async def delete(self, owner_id: UUID, key: str) -> None:
        """Idempotent, so erasure can be retried."""
        await asyncio.to_thread(self._delete, self._path(owner_id, key))

    def _delete(self, path: Path) -> None:
        path.unlink(missing_ok=True)
        # Prune upwards so the last blob of an owner takes the owner directory with it.
        # rmdir fails on a non-empty directory, which makes this safe against a concurrent put.
        for parent in path.parents:
            if parent == self._root:
                break
            try:
                parent.rmdir()
            except OSError:
                break


def _size_if_present(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None
