from contextvars import ContextVar
from datetime import datetime

from sqlalchemy import func, select

from fastamu.infra.db.connection import DBConnection
from fastamu.infra.db.transactions import TransactionRollbackOnly
from fastamu.infra.db.versions import ProjectionTicket, ProjectionVersions


class DBUnitOfWork:
    _current: ContextVar["DBUnitOfWork | None"] = ContextVar(
        "db_unit_of_work", default=None
    )

    def __init__(self, db: DBConnection):
        self.db = db
        self._session = None
        self._parent: DBUnitOfWork | None = None
        self._rollback_only = False

    @property
    def session(self):
        if not self._session:
            raise RuntimeError(
                "Session not initialized. "
                "Use 'async with' or call 'begin()' first."
            )
        return self._session

    @classmethod
    def current(cls) -> "DBUnitOfWork | None":
        unit = cls._current.get()
        return unit if unit is not None and unit._session is not None else None

    async def begin(self):
        if self._session is not None:
            raise RuntimeError("Unit of work is already open")
        self._session = self.db.session_factory()
        self._parent = self.current()
        self._current.set(self)
        return self

    async def close(self):
        try:
            await self.session.close()
        finally:
            self._session = None
            if self._current.get() is self:
                self._current.set(self._parent)
            self._parent = None
            self._clear_transaction_state()

    async def commit(self):
        if self._rollback_only:
            await self.rollback()
            raise TransactionRollbackOnly(
                "Transaction is marked rollback-only"
            )
        await self.session.commit()
        self._clear_transaction_state()

    async def rollback(self):
        await self.session.rollback()
        self._clear_transaction_state()

    def _clear_transaction_state(self) -> None:
        self._rollback_only = False

    @classmethod
    def mark_rollback_only(cls) -> None:
        unit = cls.current()
        if unit is not None:
            unit._rollback_only = True

    @classmethod
    async def stage_projection(
        cls, projection: type, ids: list[int], expires_at: float
    ) -> ProjectionTicket | None:
        unit = cls.current()
        if unit is None:
            return None
        if unit.session.in_nested_transaction():
            raise RuntimeError(
                "Projection publication inside a savepoint is unsupported"
            )
        name = f"{projection.__module__}.{projection.__qualname__}"
        return await ProjectionVersions(unit.session).stage(
            name, ids, expires_at
        )

    @classmethod
    async def pending_projection(
        cls, ticket: ProjectionTicket
    ) -> ProjectionTicket:
        unit = cls.current()
        if unit is None:
            raise RuntimeError("An active unit of work is required")
        return await ProjectionVersions(unit.session).pending(ticket)

    @classmethod
    async def complete_projection(cls, ticket: ProjectionTicket) -> None:
        unit = cls.current()
        if unit is None:
            raise RuntimeError("An active unit of work is required")
        await ProjectionVersions(unit.session).complete(ticket)

    async def now(self) -> datetime:
        result = await self.session.execute(select(func.current_timestamp()))
        return result.scalar_one()

    async def __aenter__(self):
        session = await self.begin()
        return session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                await self.rollback()
            else:
                await self.commit()
        finally:
            await self.close()


class Rollback:
    pass


async def rollback_transaction(uow: DBUnitOfWork) -> Rollback:
    """Roll back the current transaction before resolving the dependency."""
    await uow.rollback()
    return Rollback()
