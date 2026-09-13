"""Typed SQL units of work: session lifetime and transaction tools."""

import asyncio
from collections.abc import Generator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, contextmanager
from contextvars import ContextVar
from datetime import datetime
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Any, Self, overload

from sqlalchemy import Result, func, select
from sqlalchemy.ext.asyncio import (
    AsyncResult,
    AsyncSession,
    AsyncSessionTransaction,
)
from sqlalchemy.sql.base import Executable
from sqlalchemy.sql.selectable import TypedReturnsRows

if TYPE_CHECKING:
    from papilio.infra.db.connection import DBConnection
    from papilio.infra.db.transaction import Transaction


type StatementParameters = Mapping[str, Any] | Sequence[Mapping[str, Any]]


class UnitOfWork:
    """Own one session per operation; closing never commits implicitly.

    Repositories receive a backend-specific subclass. Each concurrent task
    needs its own unit. Use transaction() for managed commit/rollback, or
    commit()/rollback() explicitly when managing the boundary yourself.
    """

    _scope: ContextVar[tuple["UnitOfWork", ...]] = ContextVar(
        "units_of_work", default=()
    )

    def __init__(self, connection: "DBConnection[Self]") -> None:
        self.connection = connection
        self._session: AsyncSession | None = None

    @property
    def is_open(self) -> bool:
        return self._session is not None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("Unit of work is not open")
        return self._session

    @property
    def in_transaction(self) -> bool:
        return self.session.in_transaction()

    async def open(self) -> Self:
        """Create the session; a SQL transaction starts when it is needed."""
        if self.is_open:
            raise RuntimeError("Unit of work is already open")
        self._session = self.connection.session_factory()
        self._scope.set((*self._scope.get(), self))
        return self

    async def close(self) -> None:
        """Finish session cleanup before propagating caller cancellation."""
        if self._session is None:
            return
        cleanup = asyncio.create_task(self._session.close())
        cancellation: asyncio.CancelledError | None = None
        try:
            while True:
                try:
                    await asyncio.shield(cleanup)
                    break
                except asyncio.CancelledError as exc:
                    if cleanup.cancelled():
                        raise
                    # Repeated cancellation must not interrupt cleanup.
                    cancellation = exc
        finally:
            self._session = None
            self._scope.set(
                tuple(unit for unit in self._scope.get() if unit is not self)
            )
        if cancellation is not None:
            raise cancellation

    async def __aenter__(self) -> Self:
        return await self.open()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @classmethod
    def current(cls) -> "UnitOfWork | None":
        """Return the current open unit for this operation."""
        for unit in reversed(cls._scope.get()):
            if unit.is_open:
                return unit
        return None

    @contextmanager
    def activate(self) -> Generator[Self]:
        """Select this open unit temporarily for an operation."""
        if not self.is_open:
            raise RuntimeError("Unit of work is not open")
        token = self._scope.set((*self._scope.get(), self))
        try:
            yield self
        finally:
            self._scope.reset(token)

    def transaction(self) -> AbstractAsyncContextManager["Transaction"]:
        """Manage commit/rollback, joining this unit's outer operation."""
        from papilio.infra.db.transaction import transaction

        return transaction(self)

    def savepoint(self) -> AsyncSessionTransaction:
        """Open a SQLAlchemy savepoint; entering flushes pending ORM changes.

        Catch a savepoint failure outside its scope to keep the outer
        transaction usable. Do not enter @transactional inside a savepoint.
        """
        return self.session.begin_nested()

    async def commit(self) -> None:
        """Flush and commit when manually owning the transaction boundary."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Roll back pending changes when manually owning the boundary."""
        await self.session.rollback()

    async def flush(self) -> None:
        """Send pending ORM changes to the database without committing."""
        await self.session.flush()

    async def refresh(
        self, instance: object, *, attributes: Sequence[str] | None = None
    ) -> None:
        """Explicitly reload an ORM instance or selected mapped attributes."""
        await self.session.refresh(instance, attribute_names=attributes)

    @overload
    async def execute[T: tuple[Any, ...]](
        self,
        stmt: TypedReturnsRows[T],
        params: StatementParameters | None = None,
        *,
        execution_options: Mapping[str, Any] = MappingProxyType({}),
        bind_arguments: dict[str, Any] | None = None,
    ) -> Result[T]: ...

    @overload
    async def execute(
        self,
        stmt: Executable,
        params: StatementParameters | None = None,
        *,
        execution_options: Mapping[str, Any] = MappingProxyType({}),
        bind_arguments: dict[str, Any] | None = None,
    ) -> Result[Any]: ...

    async def execute(
        self,
        stmt: Executable,
        params: StatementParameters | None = None,
        *,
        execution_options: Mapping[str, Any] = MappingProxyType({}),
        bind_arguments: dict[str, Any] | None = None,
    ) -> Result[Any]:
        """Execute SQL and return its unmodified buffered result."""
        return await self.session.execute(
            stmt,
            params,
            execution_options=execution_options,
            bind_arguments=bind_arguments,
        )

    @overload
    async def stream[T: tuple[Any, ...]](
        self,
        stmt: TypedReturnsRows[T],
        params: StatementParameters | None = None,
        *,
        execution_options: Mapping[str, Any] = MappingProxyType({}),
        bind_arguments: dict[str, Any] | None = None,
    ) -> AsyncResult[T]: ...

    @overload
    async def stream(
        self,
        stmt: Executable,
        params: StatementParameters | None = None,
        *,
        execution_options: Mapping[str, Any] = MappingProxyType({}),
        bind_arguments: dict[str, Any] | None = None,
    ) -> AsyncResult[Any]: ...

    async def stream(
        self,
        stmt: Executable,
        params: StatementParameters | None = None,
        *,
        execution_options: Mapping[str, Any] = MappingProxyType({}),
        bind_arguments: dict[str, Any] | None = None,
    ) -> AsyncResult[Any]:
        """Execute SQL and return an open cursor; the caller closes it."""
        return await self.session.stream(
            stmt,
            params,
            execution_options=execution_options,
            bind_arguments=bind_arguments,
        )

    async def now(self) -> datetime:
        """Read the current timestamp from this database transaction."""
        stmt = select(func.current_timestamp())
        result = await self.execute(stmt)
        return result.scalar_one()


class PostgreSQLUnitOfWork(UnitOfWork):
    pass


class MySQLUnitOfWork(UnitOfWork):
    pass


class MariaDBUnitOfWork(UnitOfWork):
    pass


class SQLiteUnitOfWork(UnitOfWork):
    pass


class OracleUnitOfWork(UnitOfWork):
    pass


class MSSQLUnitOfWork(UnitOfWork):
    pass
