"""Explicit SQL deduplication, independent of broker and commit ownership."""

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from functools import wraps
from types import MappingProxyType

from fastamu.infra.db.inbox.writer import claim
from fastamu.infra.db.transaction import current_transaction, transaction
from fastamu.messaging.calls import Call


@asynccontextmanager
async def consume(consumer: str, message_id: str) -> AsyncIterator[bool]:
    """Yield whether to execute; receipt and SQL effects commit together.

    Requires an existing application transaction. A competing insert waits
    for the first transaction to commit or roll back. Failures inside this
    scope mark the transaction rollback-only, even if caught by its caller.
    """
    current_transaction()
    async with transaction():
        yield await claim(consumer, message_id)


def consumer(name: str, *, message_id: Callable[[Call[None]], str]):
    """Skip duplicate SQL handler calls; duplicates return None.

    Place inside @transactional. The selector runs before the handler and
    receives bound arguments, with call.result set to None. A router should
    acknowledge only after the transaction-owning call returns successfully.
    """
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ValueError("Inbox consumer must contain 1 to 255 characters")
    if (
        not callable(message_id)
        or inspect.iscoroutinefunction(message_id)
        or inspect.iscoroutinefunction(getattr(message_id, "__call__", None))
    ):
        raise TypeError("Inbox message ID selector must be synchronous")

    def decorate[**P, R](
        function: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[None, None, R | None]]:
        if not inspect.iscoroutinefunction(function):
            raise TypeError("Inbox consumers require an async function")
        signature = inspect.signature(function)

        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R | None:
            current_transaction()
            async with transaction():
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                id = message_id(Call(None, MappingProxyType(bound.arguments)))
                async with consume(name, id) as execute:
                    if execute:
                        return await function(*args, **kwargs)
            return None

        return wrapped

    return decorate
