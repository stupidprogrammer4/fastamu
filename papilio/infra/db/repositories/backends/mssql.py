"""Explicit mssql repository; declare table on your subclass."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import column, delete, insert, literal, update, values
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.elements import ColumnClause
from sqlalchemy.sql.selectable import Values
from sqlmodel import col

from papilio.infra.db.repositories.base import (
    IdentifiedRepository,
    PersistenceRepository,
    Reader,
    Repository,
    TimestampRepository,
)
from papilio.infra.db.repositories.contracts.mssql import (
    MSSQLIdentifiedRepositoryContract,
    MSSQLPersistenceRepositoryContract,
    MSSQLReaderContract,
    MSSQLRepositoryContract,
    MSSQLTimestampRepositoryContract,
)
from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.uow import MSSQLUnitOfWork


class MSSQLReader(Reader[MSSQLUnitOfWork], MSSQLReaderContract):
    """Table-independent base for MSSQL joins, aggregates and reports."""

    def __init__(self, uow: MSSQLUnitOfWork) -> None:
        super().__init__(uow)


class MSSQLRepository[T: BaseEntity](
    Repository[T, MSSQLUnitOfWork], MSSQLRepositoryContract[T]
):
    def __init__(self, uow: MSSQLUnitOfWork):
        super().__init__(uow)

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


class MSSQLIdentifiedRepository[T: IdentifiedEntity](
    MSSQLRepository[T],
    IdentifiedRepository[T, MSSQLUnitOfWork],
    MSSQLIdentifiedRepositoryContract[T],
):
    async def remove_by_id(self, id: int) -> T | None:
        stmt = (
            delete(self.table)
            .where(col(self.table.id) == id)
            .returning(self.table)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.uow.execute(stmt)
        return result.scalar_one_or_none()

    async def remove_by_ids(self, ids: Sequence[int]) -> Sequence[T]:
        stmt = (
            delete(self.table)
            .where(col(self.table.id).in_(ids))
            .returning(self.table)
            .execution_options(synchronize_session="fetch")
        )
        result = await self.uow.execute(stmt)
        return result.scalars().all()

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


class MSSQLTimestampRepository[T: TimestampEntity](
    MSSQLRepository[T],
    TimestampRepository[T, MSSQLUnitOfWork],
    MSSQLTimestampRepositoryContract[T],
):
    pass


class MSSQLPersistenceRepository[T: PersistenceEntity](
    MSSQLIdentifiedRepository[T],
    MSSQLTimestampRepository[T],
    PersistenceRepository[T, MSSQLUnitOfWork],
    MSSQLPersistenceRepositoryContract[T],
):
    pass
