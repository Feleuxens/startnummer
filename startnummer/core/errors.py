from uuid import UUID


class StartnummerError(Exception):
    pass


class StoreError(StartnummerError):
    pass


class BlobNotFound(StoreError):
    def __init__(self, owner_id: UUID, content_hash: str) -> None:
        super().__init__(f"no blob {content_hash} for owner {owner_id}")
        self.owner_id = owner_id
        self.content_hash = content_hash
