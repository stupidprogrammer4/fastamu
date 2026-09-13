"""Explicit mssql repository; declare table on your subclass."""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import column, delete, insert, literal, select, update, values
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Values
from sqlmodel import col

from fastamu.common.models.entities import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from fastamu.common.schemas.results import PagedType
from fastamu.infra.db.repositories.contracts.mssql import (
    MSSQLIdentifiedRepositoryContract,
    MSSQLPersistenceRepositoryContract,
    MSSQLReaderContract,
    MSSQLRepositoryContract,
    MSSQLTimestampRepositoryContract,
)
from fastamu.infra.db.tools.read import (
    fetch_page,
    stream,
)
from fastamu.infra.db.uow import MSSQLUnitOfWork


class MSSQLReader(MSSQLReaderContract):
    """Table-independent base for MSSQL joins, aggregates and reports."""

    def __init__(self, uow: MSSQLUnitOfWork) -> None:
        self.uow = uow


class MSSQLRepository[T: BaseEntity](MSSQLRepositoryContract[T]):
    table: type[T]

    def __init__(self, uow: MSSQLUnitOfWork):
        self.uow = uow

    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Mapping[str, ColumnClause[Any]],
        name: str = "incoming",
    ) -> Values:
        """Build a typed input relation using explicit input names/columns."""
        grid = values(
            *(column(key, field.type) for key, field in columns.items())
        ).data(
            [
                tuple(
                    literal(row[key], field.type)
                    for key, field in columns.items()
                )
                for row in rows
            ]
        )
        return grid.alias(name)

    async def create(self, data: T) -> T:
        stmt = insert(self.table).values(data.to_row()).returning(self.table)
        result = await self.uow.execute(stmt)
        return result.scalar_one()

    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        if not data:
            return []
        stmt = (
            insert(self.table)
            .returning(self.table)
            .execution_options(render_nulls=True)
        )
        result = await self.uow.execute(stmt, [item.to_row() for item in data])
        return result.scalars().all()

    async def get_all(self) -> Sequence[T]:
        stmt = select(self.table)
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    def get_all_stream(self, batch_size: int = 100) -> AsyncIterator[T]:
        stmt = select(self.table)
        return stream(self.uow, stmt, batch_size=batch_size)


class MSSQLIdentifiedRepository[T: IdentifiedEntity](
    MSSQLRepository[T], MSSQLIdentifiedRepositoryContract[T]
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

    async def update_by_id(
        self, id: int, changes: Mapping[str, Any]
    ) -> T | None:
        stmt = (
            update(self.table)
            .where(col(self.table.id) == id)
            .values(**changes)
            .returning(self.table)
            .execution_options(
                populate_existing=True, synchronize_session=False
            )
        )
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def update_by_ids(
        self, ids: Sequence[int], changes: Mapping[str, Any]
    ) -> Sequence[T]:
        stmt = (
            update(self.table)
            .where(col(self.table.id).in_(ids))
            .values(**changes)
            .returning(self.table)
            .execution_options(
                populate_existing=True, synchronize_session=False
            )
        )
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def update_row_by_id(self, id: int, data: T) -> T | None:
        return await self.update_by_id(id, data.to_changes())

    def _bulk_update_stmt(
        self,
        data: Sequence[T],
        *,
        update_columns: Mapping[str, ColumnClause[Any]],
    ) -> Update:
        """Build UPDATE without a result shape or execution policy."""
        grid = self._values_grid(
            [item.to_row() for item in data],
            columns={
                "id": cast(ColumnClause[Any], col(self.table.id)),
                **update_columns,
            },
        )
        stmt = update(self.table).where(col(self.table.id) == grid.c.id)
        stmt = stmt.values(
            {field: grid.c[key] for key, field in update_columns.items()}
        )
        return stmt

    async def bulk_update(
        self,
        data: Sequence[T],
        *,
        update_columns: Mapping[str, ColumnClause[Any]],
    ) -> Sequence[T]:
        """Update a nonempty batch with unique IDs and explicit columns."""
        stmt = self._bulk_update_stmt(data, update_columns=update_columns)
        stmt = stmt.returning(self.table).execution_options(
            populate_existing=True, synchronize_session=False
        )
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def remove_by_id(self, id: int) -> int:
        stmt = (
            delete(self.table)
            .where(col(self.table.id) == id)
            .execution_options(synchronize_session=False)
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

    async def remove_by_ids(self, ids: Sequence[int]) -> int:
        stmt = (
            delete(self.table)
            .where(col(self.table.id).in_(ids))
            .execution_options(synchronize_session=False)
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount


class MSSQLTimestampRepository[T: TimestampEntity](
    MSSQLRepository[T], MSSQLTimestampRepositoryContract[T]
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


class MSSQLPersistenceRepository[T: PersistenceEntity](
    MSSQLIdentifiedRepository[T],
    MSSQLTimestampRepository[T],
    MSSQLPersistenceRepositoryContract[T],
):
    def _time_query(self):
        return select(self.table).order_by(
            col(self.table.created_at), col(self.table.id)
        )
