from sqlmodel import col, select

from src.common.bases.results import PagedType
from src.infra.postgres.repository.base import PGIDRepository
from src.modules.ops.storage.domain.models import MediaModel


class MediaRepository(PGIDRepository[MediaModel]):
    async def get_by_hash(self, hash: str) -> MediaModel | None:
        """Get a media record by its content hash.

        Args:
            hash (str): SHA-256 hex digest of the file contents.
        Returns:
            (MediaModel | None): Found record or None.
        """
        stmt = select(MediaModel).where(col(MediaModel.hash) == hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_path(self, path: str) -> MediaModel | None:
        """Get a media record by its stored path.

        Args:
            path (str): Path relative to the storage base.
        Returns:
            (MediaModel | None): Found record or None.
        """
        stmt = select(MediaModel).where(col(MediaModel.path) == path)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_paged(self, limit: int, offset: int) -> PagedType[MediaModel]:
        """Get a page of media records, newest first, with the total count.

        Args:
            limit (int): Max rows to return.
            offset (int): Rows to skip.
        Returns:
            (PagedType[MediaModel]): The page rows and the total count.
        """
        stmt = select(MediaModel).order_by(col(MediaModel.id).desc())
        paged = await self._paginate(stmt, offset, limit)
        return paged
