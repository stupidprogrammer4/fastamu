from collections.abc import AsyncIterator
from typing import Protocol

from src.common.bases.results import PagedType
from src.modules.ops.storage.domain.models import MediaModel


class IMediaService(Protocol):
    async def upload(self, stream: AsyncIterator[bytes], filename: str | None) -> MediaModel: ...

    async def get_by_id(self, id: int) -> MediaModel: ...

    async def get_paged(self, page: int, per_page: int) -> PagedType[MediaModel]: ...

    async def open(self, path: str) -> tuple[AsyncIterator[bytes], str]: ...

    async def remove(self, id: int) -> MediaModel: ...
