"""Result selectors shared by independent event and projection decorators."""

import inspect
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from functools import wraps
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Call[T]:
    result: T
    arguments: Mapping[str, Any]


def after_result(
    send: Callable[[Call[Any]], Awaitable[None]],
):
    """Await the wrapped function, send from its result, then return it."""

    def decorate[**P, T](
        function: Callable[P, Awaitable[T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        if not inspect.iscoroutinefunction(function):
            raise TypeError("Message decorators require an async function")
        signature = inspect.signature(function)

        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = await function(*args, **kwargs)
            await send(Call(result, MappingProxyType(bound.arguments)))
            return result

        return wrapped

    return decorate
