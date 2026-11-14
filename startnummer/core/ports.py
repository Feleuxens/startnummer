"""Outbound ports. Implementations live in startnummer.adapters."""

from collections.abc import AsyncIterator, Sequence
from typing import NamedTuple, Protocol, runtime_checkable
from uuid import UUID

from startnummer.core.enums import Status
from startnummer.core.record import Album, AnalysisRecord
from startnummer.core.types import Embedding


class GalleryMatch(NamedTuple):
    athlete_id: UUID
    distance: float  # adapter-defined metric; lower is closer


@runtime_checkable
class AlbumStore(Protocol):
    """Legacy album-storage contract; the app uses the batch Store."""

    async def save(self, album: Album) -> None: ...

    async def get(self, owner_id: UUID, album_id: UUID) -> Album | None: ...

    async def list(self, owner_id: UUID) -> list[Album]: ...


@runtime_checkable
class MetadataStore(Protocol):
    """Legacy hash-keyed metadata contract; unsuitable for photo review state."""

    async def save(self, record: AnalysisRecord) -> None:
        # Upsert keyed on (record.owner_id, record.content_hash).
        ...

    async def save_many(self, records: Sequence[AnalysisRecord]) -> None:
        # Same upsert as save, as one write.
        ...

    async def get(self, owner_id: UUID, content_hash: str) -> AnalysisRecord | None: ...

    async def list_by_status(self, owner_id: UUID, status: Status) -> list[AnalysisRecord]: ...

    async def list_album(self, owner_id: UUID, album_id: UUID) -> list[AnalysisRecord]: ...


@runtime_checkable
class IdentityGallery(Protocol):
    """Unused cross-album matching contract. The app does not persist face data."""

    async def add(self, owner_id: UUID, athlete_id: UUID, embedding: Embedding) -> None: ...

    async def match(self, owner_id: UUID, embedding: Embedding, *, max_distance: float) -> list[GalleryMatch]:
        # Matches with distance <= max_distance, ascending. Empty if none.
        ...

    async def clear(self, owner_id: UUID) -> None:
        # Remove all embeddings for owner_id.
        ...


@runtime_checkable
class Exporter(Protocol):
    """Legacy export contract; description publishing uses DescriptionWriter."""

    async def export(self, records: Sequence[AnalysisRecord]) -> None:
        # Export new image metadata.
        ...

    async def update(self, records: Sequence[AnalysisRecord]) -> None:
        # Update previously exported image metadata.
        ...


class BlobRef(NamedTuple):
    key: str  # storage key, relative to the owner's root; goes on the photo row
    size: int


@runtime_checkable
class BlobStore(Protocol):
    # Content-addressed bytes, one copy per owner. Original filename and mime
    # type are columns on the photo row, not stored here.
    async def put(self, owner_id: UUID, content_hash: str, data: AsyncIterator[bytes], *, suffix: str = "") -> BlobRef:
        # Stored key and size. A blob that already exists is left alone.
        ...

    async def read(self, owner_id: UUID, key: str) -> bytes:
        # Raises BlobNotFound.
        ...

    async def exists(self, owner_id: UUID, key: str) -> bool: ...

    async def delete(self, owner_id: UUID, key: str) -> None:
        # Idempotent: deleting a missing blob is not an error.
        ...
