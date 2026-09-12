"""SQL session lifetime, commit/rollback, and the writes themselves."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    and_,
    func,
    insert,
    inspect,
    or_,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.sql.elements import ColumnElement

if TYPE_CHECKING:  # a dialect names its unit of work, so the import is a cycle
    from fastamu.infra.db.connection import DBConnection

type Mutation = Update | Delete


class DBUnitOfWork(ABC):
    """An open session. Leaving its scope never commits implicitly.

    Use ``@transactional`` or ``async with transaction()`` to commit.
    """

    _current: ContextVar["DBUnitOfWork | None"] = ContextVar(
        "db_unit_of_work", default=None
    )

    def __init__(self, db: "DBConnection"):
        self.db = db
        self._session: AsyncSession | None = None
        self._parent: DBUnitOfWork | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of work is not open")
        return self._session

    @classmethod
    def current(cls) -> "DBUnitOfWork | None":
        unit = cls._current.get()
        return unit if unit is not None and unit._session is not None else None

    async def begin(self) -> "DBUnitOfWork":
        if self._session is not None:
            raise RuntimeError("Unit of work is already open")
        self._session = self.db.session_factory()
        self._parent = self.current()
        self._current.set(self)
        return self

    async def close(self) -> None:
        if self._session is None:
            return
        try:
            await self._session.close()
        finally:
            self._session = None
            if self._current.get() is self:
                self._current.set(self._parent)
            self._parent = None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def now(self) -> datetime:
        result = await self.session.execute(select(func.current_timestamp()))
        return result.scalar_one()

    async def __aenter__(self) -> "DBUnitOfWork":
        return await self.begin()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @abstractmethod
    async def insert(
        self, table: type[Any], rows: Sequence[dict[str, Any]]
    ) -> Sequence[Any]: ...

    @abstractmethod
    async def update(
        self, table: type[Any], stmt: Update, where: ColumnElement[bool]
    ) -> Sequence[Any]: ...

    @abstractmethod
    async def delete(
        self, table: type[Any], stmt: Delete, where: ColumnElement[bool]
    ) -> Sequence[Any]: ...

    @abstractmethod
    async def upsert(
        self,
        table: type[Any],
        stmt: Insert,
        rows: Sequence[dict[str, Any]],
        keys: Sequence[str],
    ) -> Sequence[Any]: ...


class ReturningUnitOfWork(DBUnitOfWork):
    """One statement per write, where the database returns its rows."""

    async def _returned(
        self, table: type[Any], stmt: Insert | Mutation
    ) -> Sequence[Any]:
        # a row already in the session would otherwise keep its loaded values
        result = await self.session.execute(
            stmt.returning(table).execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def insert(
        self, table: type[Any], rows: Sequence[dict[str, Any]]
    ) -> Sequence[Any]:
        return await self._returned(table, insert(table).values(rows))

    async def update(
        self, table: type[Any], stmt: Update, where: ColumnElement[bool]
    ) -> Sequence[Any]:
        return await self._returned(table, stmt)

    async def delete(
        self, table: type[Any], stmt: Delete, where: ColumnElement[bool]
    ) -> Sequence[Any]:
        return await self._returned(table, stmt)

    async def upsert(
        self,
        table: type[Any],
        stmt: Insert,
        rows: Sequence[dict[str, Any]],
        keys: Sequence[str],
    ) -> Sequence[Any]:
        return await self._returned(table, stmt)


class FetchUnitOfWork(DBUnitOfWork):
    """Read the rows back, where the database cannot return them."""

    def _identity(
        self, table: type[Any], rows: Sequence[Any]
    ) -> ColumnElement[bool]:
        columns = list(inspect(table).primary_key)
        if not columns:
            raise ValueError("Repository tables require a primary key")
        keys = [str(column.key) for column in columns]
        if len(columns) == 1:
            return columns[0].in_([getattr(row, keys[0]) for row in rows])
        return tuple_(*columns).in_(
            [tuple(getattr(row, key) for key in keys) for row in rows]
        )

    async def _read(
        self, table: type[Any], where: ColumnElement[bool]
    ) -> Sequence[Any]:
        result = await self.session.execute(
            select(table)
            .where(where)
            .execution_options(populate_existing=True)
        )
        return result.scalars().all()

    async def _changed(
        self, table: type[Any], stmt: Mutation, where: ColumnElement[bool]
    ) -> tuple[Sequence[Any], ColumnElement[bool] | None]:
        """Hold the rows first: after the write the filter may not match."""
        locked = await self.session.execute(
            select(table).where(where).with_for_update()
        )
        rows = locked.scalars().all()
        if not rows:
            return [], None
        identity = self._identity(table, rows)
        await self.session.execute(
            stmt.where(identity).execution_options(synchronize_session=False)
        )
        return rows, identity

    async def insert(
        self, table: type[Any], rows: Sequence[dict[str, Any]]
    ) -> Sequence[Any]:
        # a bulk INSERT reports only the first generated key
        objects = [table(**row) for row in rows]
        self.session.add_all(objects)
        await self.session.flush()
        return await self._read(table, self._identity(table, objects))

    async def update(
        self, table: type[Any], stmt: Update, where: ColumnElement[bool]
    ) -> Sequence[Any]:
        _, identity = await self._changed(table, stmt, where)
        return [] if identity is None else await self._read(table, identity)

    async def delete(
        self, table: type[Any], stmt: Delete, where: ColumnElement[bool]
    ) -> Sequence[Any]:
        rows, _ = await self._changed(table, stmt, where)
        return rows

    async def upsert(
        self,
        table: type[Any],
        stmt: Insert,
        rows: Sequence[dict[str, Any]],
        keys: Sequence[str],
    ) -> Sequence[Any]:
        await self.session.execute(stmt)
        return await self._read(
            table,
            or_(
                *(
                    and_(*(getattr(table, key) == row[key] for key in keys))
                    for row in rows
                )
            ),
        )
