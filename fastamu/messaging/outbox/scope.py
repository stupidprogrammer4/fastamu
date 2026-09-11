"""Explicit outbox scope for delivery after the SQL owner commits."""

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from functools import wraps
from importlib import import_module

from fastamu.core.config import get_settings
from fastamu.infra.db.outbox import repository
from fastamu.infra.db.transaction import active_transaction
from fastamu.infra.db.uow import DBUnitOfWork
from fastamu.messaging.outbox import receipts

logger = logging.getLogger(__name__)


@asynccontextmanager
async def delivery():
    parent = receipts.current.get()
    if parent is not None:
        parent.check()
        yield
        return
    if active_transaction() is not None:
        raise RuntimeError(
            "Outbox delivery must surround the outer transaction"
        )
    unit = DBUnitOfWork.current()
    if unit is None:
        raise RuntimeError("Outbox delivery requires an open UoW")
    config = get_settings().tasks.outbox
    if config is None:
        raise RuntimeError("Outbox is disabled; configure tasks.outbox")
    collected = receipts.Receipts(unit, asyncio.current_task())
    token = receipts.current.set(collected)
    try:
        yield
        collected.check()
        if active_transaction() is not None:
            raise RuntimeError(
                "Outbox delivery cannot run before transaction exit"
            )
    finally:
        collected.active = False
        receipts.current.reset(token)
    if collected.ids:
        try:
            relay = import_module("fastamu.tasks.outbox.relay")
            await relay.OutboxRelay(
                repository.OutboxRepository(unit.db), config
            ).run_once(collected.ids)
        except Exception:
            # SQL already committed. Recovery can claim these IDs later.
            logger.exception("Immediate outbox delivery unavailable")


def deliver(function):
    if not inspect.iscoroutinefunction(function):
        raise TypeError("Outbox delivery requires an async function")

    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with delivery():
            return await function(*args, **kwargs)

    return wrapped
