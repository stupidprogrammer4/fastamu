"""Explicit mysql repository; declare table on your subclass."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import delete, literal, select, union_all, update
from sqlalchemy.dialects.mysql import Insert
from sqlalchemy.dialects.mysql import insert as dialect_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Subquery
from sqlmodel import col

from papilio.infra.db.repositories.base import (
    IdentifiedRepository,
    PersistenceRepository,
    Reader,
    Repository,
    TimestampRepository,
)
from papilio.infra.db.repositories.contracts.mysql import (
    MySQLIdentifiedRepositoryContract,
    MySQLPersistenceRepositoryContract,
    MySQLReaderContract,
    MySQLRepositoryContract,
    MySQLTimestampRepositoryContract,
)
from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.uow import MySQLUnitOfWork


class MySQLReader(Reader[MySQLUnitOfWork], MySQLReaderContract):
    """Table-independent base for MySQL joins, aggregates and reports."""

    def __init__(self, uow: MySQLUnitOfWork) -> None:
        super().__init__(uow)


class MySQLRepository[T: BaseEntity](
    Repository[T, MySQLUnitOfWork], MySQLRepositoryContract[T]
):
    def __init__(self, uow: MySQLUnitOfWork):
        super().__init__(uow)

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


class MySQLIdentifiedRepository[T: IdentifiedEntity](
    MySQLRepository[T],
    IdentifiedRepository[T, MySQLUnitOfWork],
    MySQLIdentifiedRepositoryContract[T],
):
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


class MySQLTimestampRepository[T: TimestampEntity](
    MySQLRepository[T],
    TimestampRepository[T, MySQLUnitOfWork],
    MySQLTimestampRepositoryContract[T],
):
    pass


class MySQLPersistenceRepository[T: PersistenceEntity](
    MySQLIdentifiedRepository[T],
    MySQLTimestampRepository[T],
    PersistenceRepository[T, MySQLUnitOfWork],
    MySQLPersistenceRepositoryContract[T],
):
    pass
