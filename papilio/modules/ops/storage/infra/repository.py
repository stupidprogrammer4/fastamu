from sqlmodel import col, select

from papilio.infra.db.repositories.backends.postgresql import (
    PostgreSQLIdentifiedRepository,
)
from papilio.infra.db.tools.read import fetch_page
from papilio.modules.ops.storage.domain.entities import MediaEntity
from papilio.modules.ops.storage.infra.tables import MediaTable
from papilio.schemas.results import PagedType


class MediaRepository(PostgreSQLIdentifiedRepository[MediaEntity]):
    table = MediaTable

    async def get_by_hash(self, hash: str) -> MediaEntity | None:
        """Get a media record by its content hash.

        Args:
            hash (str): SHA-256 hex digest of the file contents.
        Returns:
            (MediaEntity | None): Found record or None.
        """
        stmt = select(self.table).where(col(self.table.hash) == hash)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_path(self, path: str) -> MediaEntity | None:
        """Get a media record by its stored path.

        Args:
            path (str): Path relative to the storage base.
        Returns:
            (MediaEntity | None): Found record or None.
        """
        stmt = select(self.table).where(col(self.table.path) == path)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_paged(
        self, limit: int, offset: int = 0
    ) -> PagedType[MediaEntity]:
        """Get a page of media records, newest first, with the total count.

        Args:
            limit (int): Max rows to return.
            offset (int): Rows to skip.
        Returns:
            (PagedType[MediaEntity]): The page rows and the total count.
        """
        stmt = select(self.table).order_by(col(self.table.id).desc())
        paged = await fetch_page(self.uow, stmt, offset=offset, limit=limit)
        return paged
