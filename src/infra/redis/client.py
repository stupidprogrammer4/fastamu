from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis


async def resolve[T](value: Awaitable[T] | T) -> T:
    """Await a redis-py return value only if it is awaitable.

    The async client types several commands as ``Awaitable[T] | T`` because the
    same method serves a pipeline, where the result is not a value yet. This
    keeps call sites free of that branch.
    """
    result: T
    if isinstance(value, Awaitable):
        result = await cast("Awaitable[T]", value)
    else:
        result = value
    return result


class RedisClient:
    """The async Redis client shared app-wide.

    `Redis` owns its connection pool internally, so one instance is the single
    client to inject everywhere. Use ``.client`` for any operation
    (``await rc.client.get(...)``); ``close()`` is wired to app shutdown.
    """

    def __init__(
        self,
        url: str,
        *,
        max_connections: int,
        socket_timeout: float,
        socket_connect_timeout: float,
        health_check_interval: int,
    ) -> None:
        self.client: Redis = Redis.from_url(
            url,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            decode_responses=True,
        )

    async def close(self) -> None:
        await self.client.aclose()
