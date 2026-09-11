"""SQL transaction ownership, commit and rollback."""

import asyncio
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSessionTransaction

from fastamu.infra.db.uow import DBUnitOfWork


class TransactionRollbackOnly(RuntimeError):
    pass


@dataclass
class Transaction:
    unit: DBUnitOfWork
    owner: asyncio.Task | None
    sql_transaction: AsyncSessionTransaction
    rollback_only: bool = False
    active: bool = True

    def check(self) -> None:
        if not self.active or self.owner is not asyncio.current_task():
            raise RuntimeError("Transaction belongs to another or closed task")
        if DBUnitOfWork.current() is not self.unit:
            raise RuntimeError("Cannot switch UoW inside a transaction")
        if self.unit.session.get_transaction() is not self.sql_transaction:
            raise RuntimeError(
                "Transaction was committed or rolled back manually"
            )
        if self.unit.session.in_nested_transaction():
            raise RuntimeError(
                "Application transactions do not support savepoints"
            )


_active_units: set[DBUnitOfWork] = set()

_current: ContextVar[Transaction | None] = ContextVar(
    "application_transaction", default=None
)


def active_transaction() -> Transaction | None:
    """Return the current application transaction, validating its owner."""
    scope = _current.get()
    if scope is not None:
        scope.check()
    return scope


def current_transaction() -> Transaction:
    scope = active_transaction()
    if scope is None:
        raise RuntimeError("No active application transaction")
    return scope


@asynccontextmanager
async def transaction() -> AsyncGenerator[Transaction, None]:
    """Join the current operation or commit as its outer owner.

    Nested failures mark the operation rollback-only even when caught. Each
    concurrent operation requires its own UoW. Do not commit/rollback manually
    or create savepoints inside this scope.
    """
    unit = DBUnitOfWork.current()
    if unit is None:
        raise RuntimeError("transaction() requires an open DBUnitOfWork")
    parent = _current.get()
    if parent is not None:
        parent.check()
        try:
            yield parent
        except BaseException:
            parent.rollback_only = True
            raise
        return

    if unit in _active_units:
        raise RuntimeError(
            "Concurrent transactions require separate units of work"
        )
    _active_units.add(unit)
    try:
        sql_transaction = unit.session.get_transaction()
        if sql_transaction is None:
            sql_transaction = await unit.session.begin()
        scope = Transaction(
            unit,
            asyncio.current_task(),
            sql_transaction,
        )
        scope.check()
        token = _current.set(scope)
        try:
            try:
                yield scope
                scope.check()
                if scope.rollback_only:
                    raise TransactionRollbackOnly("Nested operation failed")
                await unit.commit()
            except BaseException:
                await unit.rollback()
                raise
        finally:
            scope.active = False
            _current.reset(token)
    finally:
        _active_units.remove(unit)


def transactional[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    if not inspect.iscoroutinefunction(function):
        raise TypeError("@transactional requires an async function")

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        async with transaction():
            return await function(*args, **kwargs)

    return wrapped
