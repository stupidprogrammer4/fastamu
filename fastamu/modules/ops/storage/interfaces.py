from collections.abc import AsyncIterator
from typing import Protocol

from fastamu.common.schemas.results import PagedType
from fastamu.modules.ops.storage.domain.entities import MediaEntity


class IMediaService(Protocol):
    async def upload(
        self, stream: AsyncIterator[bytes], filename: str | None
    ) -> MediaEntity: ...

    async def get_by_id(self, id: int) -> MediaEntity: ...

    async def get_paged(
        self, page: int, per_page: int
    ) -> PagedType[MediaEntity]: ...

    async def open(self, path: str) -> tuple[AsyncIterator[bytes], str]: ...

    async def remove(self, id: int) -> MediaEntity: ...
