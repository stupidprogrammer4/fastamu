from sqlmodel import col, select

from fastamu.common.schemas.results import PagedType
from fastamu.infra.db.repository import DBIDRepository
from fastamu.modules.ops.storage.domain.entities import MediaEntity


class MediaRepository(DBIDRepository[MediaEntity]):
    async def get_by_hash(self, hash: str) -> MediaEntity | None:
        """Get a media record by its content hash.

        Args:
            hash (str): SHA-256 hex digest of the file contents.
        Returns:
            (MediaEntity | None): Found record or None.
        """
        stmt = select(MediaEntity).where(col(MediaEntity.hash) == hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_path(self, path: str) -> MediaEntity | None:
        """Get a media record by its stored path.

        Args:
            path (str): Path relative to the storage base.
        Returns:
            (MediaEntity | None): Found record or None.
        """
        stmt = select(MediaEntity).where(col(MediaEntity.path) == path)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_paged(
        self, limit: int, offset: int
    ) -> PagedType[MediaEntity]:
        """Get a page of media records, newest first, with the total count.

        Args:
            limit (int): Max rows to return.
            offset (int): Rows to skip.
        Returns:
            (PagedType[MediaEntity]): The page rows and the total count.
        """
        stmt = select(MediaEntity).order_by(col(MediaEntity.id).desc())
        paged = await self._paginate(stmt, offset, limit)
        return paged
