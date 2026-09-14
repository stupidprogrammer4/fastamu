"""Explicit mysql repository; declare table on your subclass."""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, literal, select, union_all, update
from sqlalchemy.dialects.mysql import Insert
from sqlalchemy.dialects.mysql import insert as dialect_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Subquery
from sqlmodel import col

from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.repositories.contracts.mysql import (
    MySQLIdentifiedRepositoryContract,
    MySQLPersistenceRepositoryContract,
    MySQLReaderContract,
    MySQLRepositoryContract,
    MySQLTimestampRepositoryContract,
)
from papilio.infra.db.tools.read import (
    fetch_page,
    stream,
)
from papilio.infra.db.uow import MySQLUnitOfWork
from papilio.schemas.results import PagedType


class MySQLReader(MySQLReaderContract):
    """Table-independent base for MySQL joins, aggregates and reports."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        self.uow = uow


class MySQLRepository[T: BaseEntity](MySQLRepositoryContract[T]):
    table: type[T]

    def __init__(self, uow: MySQLUnitOfWork):
        self.uow = uow

    def _upsert_stmt(
        self,
        row: Mapping[str, Any],
        *,
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert:
        """Build one native upsert without RETURNING or execution."""
        stmt = dialect_insert(self.table).values(row)
        assignments = {
            field.key: stmt.inserted[field.key] for field in update_columns
        }
        assignments.update(
            (field.key, value) for field, value in (changes or {}).items()
        )
        stmt = stmt.on_duplicate_key_update(assignments)
        return stmt

    def _bulk_upsert_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert:
        """Build a batch using only the supplied insertion columns."""
        stmt = dialect_insert(self.table).values(
            [
                {field: row[name] for name, field in insert_columns.items()}
                for row in rows
            ]
        )
        assignments = {
            field.key: stmt.inserted[field.key] for field in update_columns
        }
        assignments.update(
            (field.key, value) for field, value in (changes or {}).items()
        )
        stmt = stmt.on_duplicate_key_update(assignments)
        return stmt

    async def upsert(
        self,
        data: T,
        *,
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> int:
        stmt = self._upsert_stmt(
            data.to_row(),
            update_columns=update_columns,
            changes=changes,
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

    async def bulk_upsert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> int:
        stmt = self._bulk_upsert_stmt(
            [item.to_row() for item in data],
            insert_columns=insert_columns,
            update_columns=update_columns,
            changes=changes,
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Mapping[str, ColumnClause[Any]],
        name: str = "incoming",
    ) -> Subquery:
        """Build a typed input relation using explicit input names/columns."""
        return union_all(
            *(
                select(
                    *(
                        literal(row[key], field.type).label(key)
                        for key, field in columns.items()
                    )
                )
                for row in rows
            )
        ).subquery(name)

    async def create(self, data: T) -> T:
        record = self.table(**data.to_row())
        self.uow.session.add(record)
        await self.uow.flush()
        await self.uow.refresh(record)
        return record

    def _bulk_insert_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
    ) -> Insert:
        """Build a native batch INSERT with explicit insertion columns."""
        stmt = dialect_insert(self.table).values(
            [
                {field: row[key] for key, field in insert_columns.items()}
                for row in rows
            ]
        )
        return stmt

    async def bulk_insert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
    ) -> int:
        """Insert without loading models; return the driver's row count."""
        if not data:
            return 0
        stmt = self._bulk_insert_stmt(
            [item.to_row() for item in data], insert_columns=insert_columns
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

    async def bulk_create(self, data: Sequence[T]) -> Sequence[T]:
        if not data:
            return []
        records = [self.table(**item.to_row()) for item in data]
        self.uow.session.add_all(records)
        await self.uow.flush()
        for record in records:
            await self.uow.refresh(record)
        return records

    async def get_all(self) -> Sequence[T]:
        stmt = select(self.table)
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    def get_all_stream(self, batch_size: int = 100) -> AsyncIterator[T]:
        stmt = select(self.table)
        return stream(self.uow, stmt, batch_size=batch_size)


class MySQLIdentifiedRepository[T: IdentifiedEntity](
    MySQLRepository[T], MySQLIdentifiedRepositoryContract[T]
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

    async def update_by_id(self, id: int, changes: Mapping[str, Any]) -> int:
        stmt = (
            update(self.table)
            .where(col(self.table.id) == id)
            .values(**changes)
            .execution_options(synchronize_session=False)
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

    async def update_by_ids(
        self, ids: Sequence[int], changes: Mapping[str, Any]
    ) -> int:
        stmt = (
            update(self.table)
            .where(col(self.table.id).in_(ids))
            .values(**changes)
            .execution_options(synchronize_session=False)
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

    async def update_row_by_id(self, id: int, data: T) -> int:
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
    ) -> int:
        """Update a nonempty batch with unique IDs and explicit columns."""
        stmt = self._bulk_update_stmt(data, update_columns=update_columns)
        stmt = stmt.execution_options(synchronize_session=False)
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount

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


class MySQLTimestampRepository[T: TimestampEntity](
    MySQLRepository[T], MySQLTimestampRepositoryContract[T]
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


class MySQLPersistenceRepository[T: PersistenceEntity](
    MySQLIdentifiedRepository[T],
    MySQLTimestampRepository[T],
    MySQLPersistenceRepositoryContract[T],
):
    def _time_query(self):
        return select(self.table).order_by(
            col(self.table.created_at), col(self.table.id)
        )
