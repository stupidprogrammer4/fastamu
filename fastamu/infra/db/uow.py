"""SQL session lifetime and explicit commit/rollback operations."""

from contextvars import ContextVar
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastamu.infra.db.connection import DBConnection


class DBUnitOfWork:
    """An open session. Leaving its scope never commits implicitly.

    Use ``@transactional`` or ``async with transaction()`` to commit an
    application operation. Closing rolls back any outstanding SQL transaction.
    """

    _current: ContextVar["DBUnitOfWork | None"] = ContextVar(
        "db_unit_of_work", default=None
    )

    def __init__(self, db: DBConnection):
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
