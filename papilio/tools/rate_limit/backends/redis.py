from typing import cast

from redis.asyncio import Redis
from throttled.asyncio.store import RedisStore
from throttled.types import AsyncRedisClientP

from .base import ThrottledBackend


class RedisBackend(ThrottledBackend):
    """Shared counters borrowing the application's Redis client."""

    def __init__(self, client: Redis) -> None:
        store = RedisStore()
        # throttled-py 3.4 lacks public client injection. Isolate the bridge;
        # the supplied client's provider owns its pool and shutdown.
        store._backend._client = cast(AsyncRedisClientP, client)
        super().__init__(store)
