"""PostgreSQL SQL builders and ready-to-use repositories.

Builders accept explicit rows and columns; only public operations execute SQL.
Declare ``table`` on the application repository; callers own transactions.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    Values,
    and_,
    column,
    delete,
    func,
    literal,
    select,
    update,
    values,
)
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlmodel import col

from fastamu.common.models.entities import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from fastamu.common.schemas.results import PagedType
from fastamu.infra.db.repositories.contracts.postgresql import (
    PostgreSQLIdentifiedRepositoryContract,
    PostgreSQLPersistenceRepositoryContract,
    PostgreSQLReaderContract,
    PostgreSQLRepositoryContract,
    PostgreSQLTimestampRepositoryContract,
)
from fastamu.infra.db.tools.read import (
    fetch_page,
    stream,
)
from fastamu.infra.db.uow import PostgreSQLUnitOfWork


class PostgreSQLReader(PostgreSQLReaderContract):
    """Table-independent base for PostgreSQL joins, aggregates and reports."""

    def __init__(self, uow: PostgreSQLUnitOfWork) -> None:
        self.uow = uow


class PostgreSQLRepository[T: BaseEntity](PostgreSQLRepositoryContract[T]):
    table: type[T]

    def __init__(self, uow: PostgreSQLUnitOfWork):
        self.uow = uow

    def _upsert_stmt(
        self,
        row: Mapping[str, Any],
        *,
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert:
        """Build one native upsert without RETURNING or execution."""
        stmt = insert(self.table).values(row)
        assignments = {
            field: stmt.excluded[field.key] for field in update_columns
        }
        assignments.update(changes or {})
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_columns), set_=assignments
        )
        return stmt

    def _bulk_upsert_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Insert:
        """Build a batch using only the supplied insertion columns."""
        stmt = insert(self.table).values(
            [
                {field: row[name] for name, field in insert_columns.items()}
                for row in rows
            ]
        )
        assignments = {
            field: stmt.excluded[field.key] for field in update_columns
        }
        assignments.update(changes or {})
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_columns), set_=assignments
        )
        return stmt

    async def upsert(
        self,
        data: T,
        *,
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> T:
        stmt = self._upsert_stmt(
            data.to_row(),
            conflict_columns=conflict_columns,
            update_columns=update_columns,
            changes=changes,
        )
        stmt = stmt.returning(self.table).execution_options(
            populate_existing=True
        )
        result = await self.uow.execute(stmt)
        return result.scalar_one()

    async def bulk_upsert(
        self,
        data: Sequence[T],
        *,
        insert_columns: Mapping[str, ColumnClause[Any]],
        conflict_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
        changes: Mapping[ColumnClause[Any], Any] | None = None,
    ) -> Sequence[T]:
        stmt = self._bulk_upsert_stmt(
            [item.to_row() for item in data],
            insert_columns=insert_columns,
            conflict_columns=conflict_columns,
            update_columns=update_columns,
            changes=changes,
        )
        stmt = stmt.returning(self.table).execution_options(
            populate_existing=True
        )
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    def _values_grid(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        columns: Sequence[ColumnClause[Any]],
        name: str = "incoming",
    ) -> Values:
        """Build a VALUES relation with exactly the supplied columns/types."""
        return values(
            *(column(field.key, field.type) for field in columns), name=name
        ).data(
            [
                tuple(literal(row[field.key], field.type) for field in columns)
                for row in rows
            ]
        )

    def _bulk_update_stmt(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        key_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
    ) -> Update:
        """Build UPDATE FROM VALUES, including composite match keys."""
        grid = self._values_grid(rows, columns=(*key_columns, *update_columns))
        stmt = update(self.table).where(
            and_(*(field == grid.c[field.key] for field in key_columns))
        )
        stmt = stmt.values(
            {field: grid.c[field.key] for field in update_columns}
        )
        return stmt

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

    async def bulk_update(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        key_columns: Sequence[ColumnClause[Any]],
        update_columns: Sequence[ColumnClause[Any]],
    ) -> Sequence[T]:
        stmt = (
            self._bulk_update_stmt(
                rows,
                key_columns=key_columns,
                update_columns=update_columns,
            )
            .returning(self.table)
            .execution_options(
                populate_existing=True,
                synchronize_session=False,
            )
        )
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def get_one(self, *where: ColumnElement[bool]) -> T | None:
        """Return one row or None; raise MultipleResultsFound on ambiguity."""
        stmt = select(self.table).where(*where)
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all(self, *where: ColumnElement[bool]) -> Sequence[T]:
        stmt = select(self.table).where(*where)
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    def get_all_stream(
        self,
        batch_size: int = 100,
        *,
        where: Sequence[ColumnElement[bool]] = (),
    ) -> AsyncIterator[T]:
        stmt = select(self.table).where(*where)
        return stream(self.uow, stmt, batch_size=batch_size)

    async def exists(self, *where: ColumnElement[bool]) -> bool:
        stmt = select(select(self.table).where(*where).exists())
        result = await self.uow.execute(stmt)
        return result.scalar_one()

    async def count(self, *where: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(self.table).where(*where)
        result = await self.uow.execute(stmt)
        return result.scalar_one()

    async def get_page(
        self,
        *,
        order_by: Sequence[ColumnElement[Any]],
        limit: int,
        offset: int = 0,
        where: Sequence[ColumnElement[bool]] = (),
    ) -> PagedType[T]:
        stmt = select(self.table).where(*where).order_by(*order_by)
        return await fetch_page(self.uow, stmt, limit=limit, offset=offset)

    async def update(
        self,
        where: ColumnElement[bool],
        changes: Mapping[str, Any],
    ) -> Sequence[T]:
        stmt = (
            update(self.table)
            .where(where)
            .values(**changes)
            .returning(self.table)
            .execution_options(
                populate_existing=True,
                synchronize_session=False,
            )
        )
        result = await self.uow.execute(stmt)
        return result.scalars().all()

    async def remove(self, where: ColumnElement[bool]) -> int:
        stmt = (
            delete(self.table)
            .where(where)
            .execution_options(synchronize_session=False)
        )
        result = await self.uow.execute(stmt)
        return cast(CursorResult[Any], result).rowcount


class PostgreSQLIdentifiedRepository[T: IdentifiedEntity](
    PostgreSQLRepository[T], PostgreSQLIdentifiedRepositoryContract[T]
):
    async def get_by_id(self, id: int) -> T | None:
        return await self.get_one(col(self.table.id) == id)

    async def get_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        return await self.get_all(col(self.table.id).in_(ids))

    async def get_paged(self, limit: int, offset: int = 0) -> PagedType[T]:
        return await self.get_page(
            order_by=[col(self.table.id).asc()], limit=limit, offset=offset
        )

    async def update_by_id(
        self, id: int, changes: Mapping[str, Any]
    ) -> T | None:
        stmt = (
            update(self.table)
            .where(col(self.table.id) == id)
            .values(**changes)
            .returning(self.table)
            .execution_options(
                populate_existing=True,
                synchronize_session=False,
            )
        )
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def update_by_ids(
        self, ids: Sequence[int], changes: Mapping[str, Any]
    ) -> Sequence[T]:
        return await self.update(col(self.table.id).in_(ids), changes)

    async def update_row_by_id(self, id: int, data: T) -> T | None:
        return await self.update_by_id(id, data.to_changes())

    async def remove_by_id(self, id: int) -> int:
        return await self.remove(col(self.table.id) == id)

    async def remove_by_ids(self, ids: Sequence[int]) -> int:
        return await self.remove(col(self.table.id).in_(ids))


class PostgreSQLTimestampRepository[T: TimestampEntity](
    PostgreSQLRepository[T], PostgreSQLTimestampRepositoryContract[T]
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


class PostgreSQLPersistenceRepository[T: PersistenceEntity](
    PostgreSQLIdentifiedRepository[T],
    PostgreSQLTimestampRepository[T],
    PostgreSQLPersistenceRepositoryContract[T],
):
    def _time_query(self):
        return select(self.table).order_by(
            col(self.table.created_at), col(self.table.id)
        )
