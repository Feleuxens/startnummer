import asyncio
import hashlib
from uuid import uuid4

import pytest

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.core.ports import BlobRef, BlobStore


def test_storage_contract_atomic_failure_and_traversal(tmp_path):
    async def scenario():
        store = FilesystemBlobStore(tmp_path)
        assert isinstance(store, BlobStore)
        owner = uuid4()
        digest = "sha256:" + hashlib.sha256(b"photo").hexdigest()

        async def data():
            yield b"photo"

        ref = await store.put(owner, digest, data())
        assert isinstance(ref, BlobRef) and ref.size == 5
        assert await store.read(owner, ref.key) == b"photo"
        assert await store.exists(owner, ref.key)
        assert await store.put(owner, digest, data()) == ref
        with pytest.raises(ValueError):
            await store.read(owner, "../escape")
        with pytest.raises(ValueError):
            await store.read("../../other-owner", ref.key)
        other = uuid4()
        assert not await store.exists(other, ref.key)
        await store.delete(owner, ref.key)
        await store.delete(owner, ref.key)
        assert not (tmp_path / str(owner)).exists()

        async def failing():
            yield b"partial"
            raise RuntimeError("interrupted upload")

        with pytest.raises(RuntimeError):
            await store.put(owner, digest, failing())
        assert not await store.exists(owner, ref.key)
        assert not list(tmp_path.rglob("*.part"))

    asyncio.run(scenario())
