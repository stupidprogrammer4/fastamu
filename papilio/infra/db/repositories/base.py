"""Implemented SQL behavior shared by the backend repository families.

Native writes and their protected builders belong to backend contracts.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from sqlalchemy import select
from sqlmodel import col

from papilio.infra.db.repositories.contracts.base import (
    IdentifiedRepositoryContract,
    PersistenceRepositoryContract,
    ReaderContract,
    RepositoryContract,
    TimestampRepositoryContract,
)
from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.tools.read import fetch_page, stream
from papilio.infra.db.uow import UnitOfWork
from papilio.schemas.results import PagedType


class Reader[U: UnitOfWork](ReaderContract[U]):
    def __init__(self, uow: U) -> None:
        self.uow = uow


class Repository[T: BaseEntity, U: UnitOfWork](RepositoryContract[T]):
    def __init__(self, uow: U) -> None:
        self.uow = uow

    async def get_all(self) -> Sequence[T]:
        stmt = select(self.table)
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    def get_all_stream(self, batch_size: int = 100) -> AsyncIterator[T]:
        stmt = select(self.table)
        return stream(self.uow, stmt, batch_size=batch_size)


class IdentifiedRepository[T: IdentifiedEntity, U: UnitOfWork](
    Repository[T, U], IdentifiedRepositoryContract[T]
):
    async def get_by_id(self, id: int) -> T | None:
        stmt = select(self.table).where(col(self.table.id) == id)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        stmt = select(self.table).where(col(self.table.id).in_(ids))
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def get_paged(self, limit: int, offset: int = 0) -> PagedType[T]:
        stmt = select(self.table).order_by(col(self.table.id))
        return await fetch_page(self.uow, stmt, limit=limit, offset=offset)


class TimestampRepository[T: TimestampEntity, U: UnitOfWork](
    Repository[T, U], TimestampRepositoryContract[T]
):
    def _time_query(self):
        return select(self.table).order_by(col(self.table.created_at))

    def _stream_time(self, condition, batch_size: int) -> AsyncIterator[T]:
        stmt = self._time_query().where(condition)
        return stream(self.uow, stmt, batch_size=batch_size)

    async def _page_time(
        self, condition, limit: int, offset: int
    ) -> PagedType[T]:
        stmt = self._time_query().where(condition)
        return await fetch_page(self.uow, stmt, limit=limit, offset=offset)

    def get_stream_range(
        self, start: datetime, end: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]:
        condition = col(self.table.created_at).between(start, end)
        return self._stream_time(condition, batch_size)

    async def get_paged_range(
        self, start: datetime, end: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]:
        condition = col(self.table.created_at).between(start, end)
        return await self._page_time(condition, limit, offset)

    def get_stream_gt(
        self, start: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]:
        condition = col(self.table.created_at) > start
        return self._stream_time(condition, batch_size)

    async def get_paged_gt(
        self, start: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]:
        condition = col(self.table.created_at) > start
        return await self._page_time(condition, limit, offset)

    def get_stream_ge(
        self, start: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]:
        condition = col(self.table.created_at) >= start
        return self._stream_time(condition, batch_size)

    async def get_paged_ge(
        self, start: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]:
        condition = col(self.table.created_at) >= start
        return await self._page_time(condition, limit, offset)

    def get_stream_lt(
        self, end: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]:
        condition = col(self.table.created_at) < end
        return self._stream_time(condition, batch_size)

    async def get_paged_lt(
        self, end: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]:
        condition = col(self.table.created_at) < end
        return await self._page_time(condition, limit, offset)

    def get_stream_le(
        self, end: datetime, batch_size: int = 100
    ) -> AsyncIterator[T]:
        condition = col(self.table.created_at) <= end
        return self._stream_time(condition, batch_size)

    async def get_paged_le(
        self, end: datetime, limit: int, offset: int = 0
    ) -> PagedType[T]:
        condition = col(self.table.created_at) <= end
        return await self._page_time(condition, limit, offset)


class PersistenceRepository[T: PersistenceEntity, U: UnitOfWork](
    IdentifiedRepository[T, U],
    TimestampRepository[T, U],
    PersistenceRepositoryContract[T],
):
    def _time_query(self):
        return select(self.table).order_by(
            col(self.table.created_at), col(self.table.id)
        )
