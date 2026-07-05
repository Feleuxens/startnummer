"""Outbound ports. Implementations live in startnummer.adapters."""

from collections.abc import Sequence
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
    def save(self, album: Album) -> None: ...

    def get(self, owner_id: UUID, album_id: UUID) -> Album | None: ...

    def list(self, owner_id: UUID) -> list[Album]: ...


@runtime_checkable
class MetadataStore(Protocol):
    def save(self, record: AnalysisRecord) -> None:
        # Upsert keyed on (record.owner_id, record.content_hash).
        ...

    def get(self, owner_id: UUID, content_hash: str) -> AnalysisRecord | None: ...

    def list_by_status(
        self, owner_id: UUID, status: Status
    ) -> list[AnalysisRecord]: ...

    def list_album(self, owner_id: UUID, album_id: UUID) -> list[AnalysisRecord]: ...


@runtime_checkable
class IdentityGallery(Protocol):
    def add(self, owner_id: UUID, athlete_id: UUID, embedding: Embedding) -> None: ...

    def match(
        self, owner_id: UUID, embedding: Embedding, *, max_distance: float
    ) -> list[GalleryMatch]:
        # Matches with distance <= max_distance, ascending. Empty if none.
        ...

    def clear(self, owner_id: UUID) -> None:
        # Remove all embeddings for owner_id.
        ...


@runtime_checkable
class Exporter(Protocol):
    def export(self, records: Sequence[AnalysisRecord]) -> None:
        # Create path: new images (e.g. JSON sidecars + bulk-importer trigger).
        ...

    def update(self, records: Sequence[AnalysisRecord]) -> None:
        # Mutate path: already-exported images (e.g. direct DB writes).
        ...
