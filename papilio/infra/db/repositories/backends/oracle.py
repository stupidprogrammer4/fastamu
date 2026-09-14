"""Explicit oracle repository; declare table on your subclass."""

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import (
    delete,
    insert,
    literal,
    select,
    tuple_,
    union_all,
    update,
)
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
from papilio.infra.db.repositories.contracts.oracle import (
    OracleIdentifiedRepositoryContract,
    OraclePersistenceRepositoryContract,
    OracleReaderContract,
    OracleRepositoryContract,
    OracleTimestampRepositoryContract,
)
from papilio.infra.db.schema.entity import (
    BaseEntity,
    IdentifiedEntity,
    PersistenceEntity,
    TimestampEntity,
)
from papilio.infra.db.uow import OracleUnitOfWork


class OracleReader(Reader[OracleUnitOfWork], OracleReaderContract):
    """Table-independent base for Oracle joins, aggregates and reports."""

    def __init__(self, uow: OracleUnitOfWork) -> None:
        super().__init__(uow)


class OracleRepository[T: BaseEntity](
    Repository[T, OracleUnitOfWork], OracleRepositoryContract[T]
):
    def __init__(self, uow: OracleUnitOfWork):
        super().__init__(uow)

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


class OracleIdentifiedRepository[T: IdentifiedEntity](
    OracleRepository[T],
    IdentifiedRepository[T, OracleUnitOfWork],
    OracleIdentifiedRepositoryContract[T],
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
        incoming = (
            select(*(grid.c[key] for key in update_columns))
            .where(grid.c.id == col(self.table.id))
            .correlate(self.table)
        )
        stmt = update(self.table).where(
            col(self.table.id).in_([item.id for item in data])
        )
        stmt = stmt.values(
            {tuple_(*update_columns.values()): incoming.scalar_subquery()}
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


class OracleTimestampRepository[T: TimestampEntity](
    OracleRepository[T],
    TimestampRepository[T, OracleUnitOfWork],
    OracleTimestampRepositoryContract[T],
):
    pass


class OraclePersistenceRepository[T: PersistenceEntity](
    OracleIdentifiedRepository[T],
    OracleTimestampRepository[T],
    PersistenceRepository[T, OracleUnitOfWork],
    OraclePersistenceRepositoryContract[T],
):
    pass
